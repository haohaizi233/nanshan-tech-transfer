"""统一安全投递结果模型、能力声明、脱敏日志与低基数指标。

为 SMS Security Gateway 与 Email Security Gateway 提供共享基础设施，
同时保持 `modules.security.sms_delivery` 既有接口完全向后兼容。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from core.errors import BizError


class ProviderError(BizError):
    """第三方/本地投递服务商结构化异常（不携带未脱敏响应或用户凭证）。"""

    def __init__(
        self,
        message: str,
        code: str = "TT_COMMON_50301",
        status: int = 503,
        *,
        outcome_unknown: bool = False,
        reason_code: str = "provider_error",
        provider_status: int | None = None,
        retryable: bool = False,
        request_attempted: bool = False,
    ):
        super().__init__(code, message, status)
        self.outcome_unknown = outcome_unknown
        self.reason_code = reason_code
        self.provider_status = provider_status
        self.retryable = retryable
        self.request_attempted = request_attempted


DeliveryProviderError = ProviderError


@dataclass(frozen=True)
class DeliveryReceipt:
    """结构化投递受理回执。accepted=True 仅表示服务商已受理请求，不代表最终送达。"""

    accepted: bool
    provider: str
    channel: str
    request_id: str
    provider_message_ids: tuple[str, ...] = ()

    @property
    def provider_ids(self) -> tuple[str, ...]:
        """兼容 SmsReceipt.provider_ids 字段名。"""
        return self.provider_message_ids


@dataclass(frozen=True)
class ProviderCapabilities:
    """服务商能力显式声明；不支持的能力必须明确拒绝而不能静默模拟。"""

    send_otp: bool = False
    send_reset_link: bool = False
    provider_message_id: bool = False
    idempotency: bool = False
    delivery_status_query: bool = False
    delivery_webhook: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {
            "send_otp": self.send_otp,
            "send_reset_link": self.send_reset_link,
            "provider_message_id": self.provider_message_id,
            "idempotency": self.idempotency,
            "delivery_status_query": self.delivery_status_query,
            "delivery_webhook": self.delivery_webhook,
        }


@dataclass(frozen=True)
class DeliveryTaskResult:
    """内部投递任务执行结果，绝不直接暴露给未认证公开接口。"""

    task_id: str
    outcome: str
    failure_stage: str | None = None
    failure_reason: str | None = None
    provider_status: int | None = None
    provider_ids: tuple[str, ...] = ()
    retryable: bool = False
    outcome_unknown: bool = False
    risk_rule_id: str | None = None
    provider_called: bool = False
    challenge_id: str | None = None
    elapsed_ms: int = 0
    channel: str = "sms"
    purpose: str | None = None
    provider: str | None = None

    @property
    def queue_state(self) -> str:
        if self.outcome_unknown:
            return "unknown"
        return {
            "COMPLETED": "completed",
            "INELIGIBLE": "ineligible",
            "RISK_BLOCKED": "blocked",
            "CONFIG_ERROR": "config_error",
            "PROVIDER_REJECTED": "failed",
            "PROVIDER_UNKNOWN": "unknown",
            "DELIVERY_FAILED": "failed",
            "INTERNAL_ERROR": "failed_internal",
        }[self.outcome]


class DeliveryStageError(ProviderError):
    """带阶段标识与限流退避秒数的网关内部异常。"""

    def __init__(
        self,
        stage: str,
        reason: str,
        *,
        risk_rule_id: str | None = None,
        provider_status: int | None = None,
        provider_ids: tuple[str, ...] = (),
        outcome_unknown: bool = False,
        provider_called: bool = False,
        retryable: bool = False,
        retry_after: int = 0,
        provider_name: str | None = None,
    ):
        super().__init__(
            "验证服务暂时不可用，请稍后重试",
            outcome_unknown=outcome_unknown,
            reason_code=reason,
            provider_status=provider_status,
            retryable=retryable,
            request_attempted=provider_called,
        )
        self.stage = stage
        self.risk_rule_id = risk_rule_id
        self.provider_ids = tuple(provider_ids)
        self.retry_after = max(0, int(retry_after or 0))
        self.provider_name = provider_name
        if stage == "risk":
            self.code = "TT_COMMON_42901"
            self.http_status = 503 if reason == "REDIS_UNAVAILABLE" else 429
        elif stage == "config" and reason == "CHANNEL_DISABLED":
            self.code = "TT_COMMON_50301"
            self.http_status = 503


_ALLOWED_METRIC_LABELS = frozenset({"channel", "purpose", "provider", "reason", "rule_id"})


class DeliveryMetrics:
    """线程安全的低基数投递指标收集器（严禁将邮箱/user_id/challenge_id 作为标签）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = defaultdict(int)
        self._latency: dict[tuple[tuple[str, str], ...], dict[str, float]] = {}

    @staticmethod
    def _sanitize_labels(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
        items: list[tuple[str, str]] = []
        for k in sorted(labels):
            if k not in _ALLOWED_METRIC_LABELS:
                continue
            v = str(labels[k] or "unknown")[:48]
            if "@" in v:
                v = "redacted"
            items.append((k, v))
        return tuple(items)

    def inc(self, metric_name: str, amount: int = 1, **labels: str) -> None:
        key = (metric_name, self._sanitize_labels(labels))
        with self._lock:
            self._counters[key] += amount

    def observe_latency(self, elapsed_ms: float, **labels: str) -> None:
        key = self._sanitize_labels(labels)
        val = max(0.0, float(elapsed_ms))
        with self._lock:
            bucket = self._latency.get(key)
            if bucket is None:
                self._latency[key] = {"count": 1.0, "sum_ms": val, "max_ms": val, "last_ms": val}
            else:
                bucket["count"] += 1.0
                bucket["sum_ms"] += val
                bucket["max_ms"] = max(bucket["max_ms"], val)
                bucket["last_ms"] = val

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            counters: dict[str, list[dict[str, object]]] = defaultdict(list)
            for (name, label_pairs), value in sorted(self._counters.items()):
                counters[name].append({"labels": dict(label_pairs), "value": value})
            latencies = [{"labels": dict(label_pairs), **stats} for label_pairs, stats in sorted(self._latency.items())]
        return {"counters": dict(counters), "email_delivery_latency": latencies}

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._latency.clear()


metrics = DeliveryMetrics()


def risk_reason(rule: str) -> str:
    """将风控规则 ID 映射为标准化脱敏原因码。"""
    rule_text = str(rule or "")
    if "redis" in rule_text:
        return "REDIS_UNAVAILABLE"
    if rule_text.startswith("email."):
        if "pending_outcome" in rule_text:
            return "EMAIL_PENDING_OUTCOME"
        if "duplicate" in rule_text:
            return "EMAIL_DUPLICATE_TASK"
        if "cooldown" in rule_text:
            return "EMAIL_COOLDOWN"
        if "global.day" in rule_text:
            return "EMAIL_GLOBAL_BUDGET"
        if "domain" in rule_text:
            return "EMAIL_DOMAIN_ANOMALY"
        if "email.day" in rule_text or "destination.day" in rule_text:
            return "EMAIL_DAILY_LIMIT"
        if "device" in rule_text:
            return "EMAIL_DEVICE_RATE_LIMIT"
        if ".ip." in rule_text:
            return "EMAIL_IP_RATE_LIMIT"
        if "account" in rule_text:
            return "EMAIL_ACCOUNT_RATE_LIMIT"
        return "EMAIL_RISK_BLOCKED"

    if "pending_outcome" in rule_text:
        return "SMS_PENDING_OUTCOME"
    if "duplicate" in rule_text:
        return "SMS_DUPLICATE_TASK"
    if "cooldown" in rule_text:
        return "SMS_PHONE_COOLDOWN"
    if rule_text == "sms.phone.day":
        return "SMS_PHONE_DAILY_LIMIT"
    if "device" in rule_text:
        return "SMS_DEVICE_RATE_LIMIT"
    if ".ip." in rule_text:
        return "SMS_IP_RATE_LIMIT"
    return "SMS_RISK_BLOCKED"


def safe_id(value: object) -> str:
    """日志安全标识脱敏：屏蔽手机号、邮箱及异常字符。"""
    text = str(value or "")
    if "@" in text or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", text) or re.search(r"1[3-9][0-9]{9}", text):
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
    return text


def task_event(
    logger: logging.Logger,
    result: DeliveryTaskResult,
    request_id: object,
    event: str,
    exception_type: str | None = None,
) -> None:
    """记录脱敏后的结构化投递事件日志。"""
    fields = {
        "event": "security.delivery.result" if result.channel != "sms" else event,
        "task_event": event,
        "channel": result.channel,
        "purpose": result.purpose,
        "provider": result.provider,
        "request_id": safe_id(request_id),
        "task_id": safe_id(result.task_id),
        "challenge_id": safe_id(result.challenge_id) if result.challenge_id else None,
        "stage": result.failure_stage or "provider_accepted",
        "failure_stage": result.failure_stage,
        "failure_reason": result.failure_reason,
        "reason_code": result.failure_reason,
        "provider_status": result.provider_status,
        "risk_rule_id": result.risk_rule_id,
        "elapsed_ms": result.elapsed_ms,
        "outcome": "accepted" if (result.channel != "sms" and result.outcome == "COMPLETED") else result.outcome,
        "task_outcome": result.outcome,
        "outcome_unknown": result.outcome_unknown,
        "provider_called": result.provider_called,
        "exception_type": exception_type,
    }
    msg = "SMS delivery task event" if result.channel == "sms" else "security.delivery.result"
    logger.log(logging.INFO if result.outcome == "COMPLETED" else logging.WARNING, msg, extra=fields)


def _parse_uuid_str(value: object) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _classify_false_transition(engine: Any, challenge_id: str) -> tuple[str, str]:
    """当 Redis risk transition 返回 False 时，细分为 missing / conflict / retryable_failure。"""
    try:
        from modules.security.risk_engine import BaseRiskEngine
    except Exception:
        BaseRiskEngine = None  # type: ignore[assignment,misc]

    if BaseRiskEngine is not None and isinstance(engine, BaseRiskEngine):
        if engine._is_dev_bypass_allowed():
            return "synced", "dev_bypass"
        try:
            raw = engine._client().get(engine._key("reservation", challenge_id))
        except Exception as exc:
            return "retryable_failure", f"inspect_exc_{type(exc).__name__}"[:64]
        if raw is None:
            return "reservation_missing", "reservation_missing"
        raw_text = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
        try:
            parsed = json.loads(raw_text) if raw_text else {}
        except Exception:
            return "conflict", "invalid_reservation_payload"
        cur_state = parsed.get("state") if isinstance(parsed, dict) else None
        return "conflict", (f"state_conflict_{cur_state}" if cur_state else "state_conflict")[:64]

    return "conflict", "transition_returned_false"


def _persist_risk_sync_outcome(
    challenge_id: str,
    target_state: str,
    *,
    sync_state: str,
    error_code: str | None = None,
    cursor_factory: Any = None,
) -> str:
    """持久化 auth_challenge.risk_sync_* 状态并返回最终落盘的 risk_sync_state。"""
    cid_uuid = _parse_uuid_str(challenge_id)
    if cid_uuid is None:
        return sync_state

    from config import settings
    from db import get_cursor

    factory = cursor_factory or get_cursor
    diag_logger = logging.getLogger("nanshan.security.risk_coordination")
    err_val = error_code[:64] if error_code else None

    try:
        with factory(commit=True) as cur:
            if sync_state == "synced":
                cur.execute(
                    """
                    UPDATE auth_challenge
                    SET risk_sync_state = 'synced',
                        risk_sync_target = COALESCE(risk_sync_target, %s),
                        risk_sync_next_retry_at = NULL,
                        risk_sync_last_error_code = NULL,
                        risk_sync_claimed_at = NULL,
                        risk_sync_updated_at = NOW()
                    WHERE id = %s
                      AND (risk_sync_target IS NULL OR risk_sync_target = %s)
                    RETURNING risk_sync_state
                    """,
                    (target_state, cid_uuid, target_state),
                )
                row = cur.fetchone()
                return str(row["risk_sync_state"]) if isinstance(row, dict) and row.get("risk_sync_state") else "synced"

            if sync_state in {"reservation_missing", "conflict"}:
                cur.execute(
                    """
                    UPDATE auth_challenge
                    SET risk_sync_state = %s,
                        risk_sync_target = COALESCE(risk_sync_target, %s),
                        risk_sync_next_retry_at = NULL,
                        risk_sync_last_error_code = %s,
                        risk_sync_claimed_at = NULL,
                        risk_sync_updated_at = NOW()
                    WHERE id = %s
                    RETURNING risk_sync_state
                    """,
                    (sync_state, target_state, err_val, cid_uuid),
                )
                row = cur.fetchone()
                return (
                    str(row["risk_sync_state"]) if isinstance(row, dict) and row.get("risk_sync_state") else sync_state
                )

            max_attempts = max(1, int(settings.RISK_SYNC_MAX_ATTEMPTS))
            base_secs = max(1, int(settings.RISK_SYNC_RETRY_BASE_SECONDS))
            max_secs = max(base_secs, int(settings.RISK_SYNC_RETRY_MAX_SECONDS))
            cur.execute(
                """
                UPDATE auth_challenge
                SET risk_sync_attempts = COALESCE(risk_sync_attempts, 0) + 1,
                    risk_sync_target = COALESCE(risk_sync_target, %s),
                    risk_sync_state = CASE
                        WHEN COALESCE(risk_sync_attempts, 0) + 1 >= %s THEN 'manual_review_required'
                        ELSE 'retryable_failure'
                    END,
                    risk_sync_next_retry_at = CASE
                        WHEN COALESCE(risk_sync_attempts, 0) + 1 >= %s THEN NULL
                        ELSE NOW() + make_interval(
                            secs => LEAST(
                                %s,
                                %s * POWER(2, GREATEST(0, LEAST(COALESCE(risk_sync_attempts, 0), 10)))
                            )
                        )
                    END,
                    risk_sync_last_error_code = %s,
                    risk_sync_claimed_at = NULL,
                    risk_sync_updated_at = NOW()
                WHERE id = %s
                RETURNING risk_sync_state
                """,
                (target_state, max_attempts, max_attempts, max_secs, base_secs, err_val, cid_uuid),
            )
            row = cur.fetchone()
            return (
                str(row["risk_sync_state"])
                if isinstance(row, dict) and row.get("risk_sync_state")
                else "retryable_failure"
            )
    except Exception as db_exc:
        diag_logger.warning(
            "Persist risk_sync_state failed (challenge=%s target=%s err=%s)",
            safe_id(challenge_id),
            target_state,
            type(db_exc).__name__,
        )
        return sync_state


def _transition_risk_checked_detail(
    engine: Any,
    challenge_id: str,
    target_state: str,
    *,
    channel: str,
    purpose: str,
    request_id: str | None = None,
    cursor_factory: Any = None,
) -> tuple[bool, str]:
    diag_logger = logging.getLogger("nanshan.security.risk_coordination")
    try:
        ok = bool(engine.transition(challenge_id, target_state))
    except Exception as exc:
        err_code = f"exc_{type(exc).__name__}"[:64]
        metrics.inc(
            "risk_transition_failed_total",
            channel=channel,
            purpose=purpose,
            reason=err_code[:48],
        )
        diag_logger.warning(
            "Redis risk state transition raised exception (channel=%s purpose=%s target=%s challenge=%s err=%s req=%s)",
            channel,
            purpose,
            target_state,
            safe_id(challenge_id),
            type(exc).__name__,
            safe_id(request_id) if request_id else "-",
        )
        persisted_state = _persist_risk_sync_outcome(
            challenge_id,
            target_state,
            sync_state="retryable_failure",
            error_code=err_code,
            cursor_factory=cursor_factory,
        )
        return False, persisted_state

    if ok:
        persisted_state = _persist_risk_sync_outcome(
            challenge_id,
            target_state,
            sync_state="synced",
            cursor_factory=cursor_factory,
        )
        return True, persisted_state

    classified_state, reason_code = _classify_false_transition(engine, challenge_id)
    metrics.inc(
        "risk_transition_failed_total",
        channel=channel,
        purpose=purpose,
        reason=f"{classified_state}_{target_state}"[:48],
    )
    diag_logger.warning(
        "Redis risk state transition returned False (channel=%s purpose=%s target=%s state=%s reason=%s challenge=%s req=%s)",
        channel,
        purpose,
        target_state,
        classified_state,
        reason_code,
        safe_id(challenge_id),
        safe_id(request_id) if request_id else "-",
    )
    persisted_state = _persist_risk_sync_outcome(
        challenge_id,
        target_state,
        sync_state=classified_state,
        error_code=reason_code,
        cursor_factory=cursor_factory,
    )
    return False, persisted_state


def transition_risk_checked(
    engine: Any,
    challenge_id: str,
    target_state: str,
    *,
    channel: str,
    purpose: str,
    request_id: str | None = None,
    cursor_factory: Any = None,
) -> bool:
    """显式消费并检查 Redis 风控状态转换结果并持久化协调态，绝不触发重发。"""
    ok, _state = _transition_risk_checked_detail(
        engine,
        challenge_id,
        target_state,
        channel=channel,
        purpose=purpose,
        request_id=request_id,
        cursor_factory=cursor_factory,
    )
    return ok


def reconcile_pending_risk_syncs(
    limit: int = 50,
    *,
    email_engine: Any = None,
    sms_engine: Any = None,
    cursor_factory: Any = None,
) -> dict[str, int]:
    """扫描并补偿同步待处理的 auth_challenge Redis 风控状态（严禁在 DB 锁内执行 Redis I/O，严禁触发外部发信）。"""
    from db import get_cursor

    factory = cursor_factory or get_cursor
    batch_limit = min(100, max(1, int(limit)))

    with factory(commit=True) as cur:
        cur.execute(
            """
            WITH candidate AS (
                SELECT id
                FROM auth_challenge
                WHERE risk_sync_state IN ('sync_pending', 'retryable_failure')
                  AND risk_sync_target IS NOT NULL
                  AND (risk_sync_next_retry_at IS NULL OR risk_sync_next_retry_at <= NOW())
                  AND (risk_sync_claimed_at IS NULL OR risk_sync_claimed_at < NOW() - INTERVAL '60 seconds')
                ORDER BY COALESCE(risk_sync_next_retry_at, created_at) ASC, id ASC
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            )
            UPDATE auth_challenge ac
            SET risk_sync_claimed_at = NOW(),
                risk_sync_updated_at = NOW()
            FROM candidate c
            WHERE ac.id = c.id
            RETURNING ac.id, ac.channel, ac.purpose, ac.risk_sync_target
            """,
            (batch_limit,),
        )
        claimed_rows = [dict(r) for r in cur.fetchall() if isinstance(r, dict)]

    summary: dict[str, int] = {
        "claimed": len(claimed_rows),
        "synced": 0,
        "retryable_failure": 0,
        "reservation_missing": 0,
        "conflict": 0,
        "manual_review_required": 0,
    }
    if not claimed_rows:
        return summary

    resolved_email_engine = email_engine
    resolved_sms_engine = sms_engine

    for row in claimed_rows:
        cid = str(row["id"])
        ch = str(row.get("channel") or "email_otp")
        purp = str(row.get("purpose") or "password_recovery")
        target = str(row.get("risk_sync_target") or "")
        if ch == "sms":
            if resolved_sms_engine is None:
                from modules.security.sms_risk import get_sms_risk_engine

                resolved_sms_engine = get_sms_risk_engine()
            eng = resolved_sms_engine
        else:
            if resolved_email_engine is None:
                from modules.security.email_risk import get_email_risk_engine

                resolved_email_engine = get_email_risk_engine()
            eng = resolved_email_engine

        ok, final_state = _transition_risk_checked_detail(
            eng,
            cid,
            target,
            channel=ch,
            purpose=purp,
            cursor_factory=factory,
        )
        if ok:
            summary["synced"] += 1
        elif final_state in summary:
            summary[final_state] += 1
        else:
            summary["retryable_failure"] += 1

    return summary
