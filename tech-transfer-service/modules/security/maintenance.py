"""安全后台协调调度器（Redis 风控补偿 + 投递队列清理）。

仅负责有界批次的风险状态同步补偿与过期队列清理：
- 零外部 Provider 调用；
- 多实例通过 PostgreSQL FOR UPDATE SKIP LOCKED 互斥认领；
- 暴露可观测积压数量与最后成功时间。
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("nanshan.security.maintenance")

_DEFAULT_INTERVAL_SECONDS = 30.0
_state_lock = threading.Lock()
_stop_event = threading.Event()
_thread: threading.Thread | None = None
_status: dict[str, Any] = {
    "running": False,
    "lastRunAt": None,
    "lastSuccessAt": None,
    "lastError": None,
    "pendingRiskSyncCount": 0,
    "lastSummary": None,
}


def get_security_maintenance_status() -> dict[str, Any]:
    with _state_lock:
        return dict(_status)


def count_pending_risk_syncs(cursor_factory: Any = None) -> int:
    from db import get_cursor

    factory = cursor_factory or get_cursor
    with factory() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM auth_challenge
            WHERE risk_sync_state IN ('sync_pending', 'retryable_failure')
              AND risk_sync_target IS NOT NULL
            """
        )
        row = cur.fetchone()
    if isinstance(row, dict):
        return int(row.get("cnt") or 0)
    return int(row[0] or 0) if row else 0


def run_security_maintenance_tick(
    limit: int = 50,
    *,
    email_engine: Any = None,
    sms_engine: Any = None,
    cursor_factory: Any = None,
) -> dict[str, Any]:
    """执行一次有界风险协调与过期队列清理，并更新可观测状态。"""
    from modules.security.delivery_models import reconcile_pending_risk_syncs
    from modules.security.sms_gateway import cleanup_delivery_tasks

    now_iso = datetime.now(UTC).isoformat()
    try:
        summary = reconcile_pending_risk_syncs(
            limit=limit,
            email_engine=email_engine,
            sms_engine=sms_engine,
            cursor_factory=cursor_factory,
        )
        if cursor_factory is None:
            cleanup_delivery_tasks()
        backlog = count_pending_risk_syncs(cursor_factory=cursor_factory)
        with _state_lock:
            _status["lastRunAt"] = now_iso
            _status["lastSuccessAt"] = now_iso
            _status["lastError"] = None
            _status["pendingRiskSyncCount"] = backlog
            _status["lastSummary"] = dict(summary)
        return {"ok": True, "summary": summary, "pendingRiskSyncCount": backlog}
    except Exception as exc:
        logger.warning("Security maintenance tick failed: %s", type(exc).__name__)
        with _state_lock:
            _status["lastRunAt"] = now_iso
            _status["lastError"] = type(exc).__name__
        return {"ok": False, "error": type(exc).__name__}


def _loop(interval_seconds: float) -> None:
    while not _stop_event.wait(interval_seconds):
        run_security_maintenance_tick()


def start_security_maintenance(interval_seconds: float = _DEFAULT_INTERVAL_SECONDS) -> bool:
    """在应用生命周期内启动后台协调线程（幂等）。"""
    global _thread
    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("SECURITY_MAINTENANCE_DISABLED") == "1":
        return False
    with _state_lock:
        if _thread is not None and _thread.is_alive():
            return False
        _stop_event.clear()
        _status["running"] = True
        _thread = threading.Thread(
            target=_loop,
            args=(max(5.0, float(interval_seconds)),),
            name="nanshan-security-maintenance",
            daemon=True,
        )
        _thread.start()
        return True


def stop_security_maintenance(timeout: float = 2.0) -> None:
    global _thread
    _stop_event.set()
    t = _thread
    if t is not None and t.is_alive():
        t.join(timeout=timeout)
    with _state_lock:
        _status["running"] = False
        _thread = None
