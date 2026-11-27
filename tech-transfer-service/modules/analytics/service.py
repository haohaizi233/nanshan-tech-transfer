"""产品业务事件与运营指标聚合（与安全审计日志严格分离）。

严禁记录明文 OTP、认证 Token、密码恢复链接、私人联系方式及完整 AI 对话原文。
"""

from __future__ import annotations

import logging
from typing import Any

from psycopg2.extras import Json

from db import get_cursor

logger = logging.getLogger("nanshan.analytics")

ALLOWED_PRODUCT_EVENTS = frozenset(
    {
        "achievement_viewed",
        "demand_viewed",
        "search_executed",
        "ai_match_requested",
        "ai_result_clicked",
        "cooperation_requested",
        "cooperation_accepted",
        "cooperation_confirmed",
        "cooperation_completed",
        "organization_joined",
    }
)

_FORBIDDEN_METADATA_KEYS = frozenset(
    {
        "phone",
        "mobile",
        "email",
        "wechat",
        "otp",
        "code",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "reset_link",
        "prompt",
        "message",
        "contact",
    }
)


def sanitize_event_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    cleaned: dict[str, Any] = {}
    for k, v in metadata.items():
        lk = str(k).strip().lower()
        if lk in _FORBIDDEN_METADATA_KEYS or any(
            bad in lk for bad in ("token", "secret", "password", "otp", "phone", "email", "wechat")
        ):
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            cleaned[str(k)[:48]] = v[:120] if isinstance(v, str) else v
    return cleaned


def record_product_event(
    event_name: str,
    *,
    actor_user_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    cur: Any = None,
) -> bool:
    if event_name not in ALLOWED_PRODUCT_EVENTS:
        return False
    safe_meta = sanitize_event_metadata(metadata)
    sql = """
        INSERT INTO product_event (event_name, actor_user_id, target_type, target_id, metadata)
        VALUES (%s, %s, %s, %s, %s)
    """
    params = (event_name, actor_user_id, target_type, target_id, Json(safe_meta))
    try:
        if cur is not None:
            cur.execute(sql, params)
        else:
            with get_cursor(commit=True) as db_cur:
                db_cur.execute(sql, params)
        return True
    except Exception as exc:
        logger.debug("record_product_event skipped event=%s err=%s", event_name, type(exc).__name__)
        return False


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def get_operational_metrics(days: int = 30) -> dict[str, Any]:
    """按显式时间窗口与分母聚合基础运营指标。"""
    window_days = max(1, min(365, int(days or 30)))
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT event_name, COUNT(*) AS cnt
            FROM product_event
            WHERE created_at >= NOW() - make_interval(days => %s)
            GROUP BY event_name
            """,
            (window_days,),
        )
        event_counts = dict.fromkeys(sorted(ALLOWED_PRODUCT_EVENTS), 0)
        for row in cur.fetchall() or []:
            ename = str(row["event_name"])
            if ename in event_counts:
                event_counts[ename] = int(row["cnt"] or 0)

        cur.execute(
            """
            SELECT COUNT(DISTINCT actor_user_id) AS cnt
            FROM product_event
            WHERE actor_user_id IS NOT NULL
              AND created_at >= NOW() - make_interval(days => %s)
            """,
            (window_days,),
        )
        active_users = int((cur.fetchone() or {}).get("cnt") or 0)

        cur.execute("SELECT COUNT(*) AS cnt FROM achievement WHERE status = 'published' AND deleted_at IS NULL")
        published_achievements = int((cur.fetchone() or {}).get("cnt") or 0)

        cur.execute("SELECT COUNT(*) AS cnt FROM demand WHERE status = 'published' AND deleted_at IS NULL")
        published_demands = int((cur.fetchone() or {}).get("cnt") or 0)

        cur.execute(
            """
            SELECT
                COUNT(*) AS total_reqs,
                COUNT(*) FILTER (WHERE accepted_at IS NOT NULL) AS accepted_cnt,
                COUNT(*) FILTER (WHERE completed_at IS NOT NULL) AS completed_cnt,
                AVG(EXTRACT(EPOCH FROM (completed_at - created_at)) / 3600.0)
                    FILTER (WHERE completed_at IS NOT NULL) AS avg_hours
            FROM cooperation_intent
            WHERE created_at >= NOW() - make_interval(days => %s)
            """,
            (window_days,),
        )
        coop_row = cur.fetchone() or {}
        total_reqs = int(coop_row.get("total_reqs") or 0)
        accepted_cnt = int(coop_row.get("accepted_cnt") or 0)
        completed_cnt = int(coop_row.get("completed_cnt") or 0)
        avg_hours = round(float(coop_row["avg_hours"]), 2) if coop_row.get("avg_hours") is not None else None

    return {
        "windowDays": window_days,
        "activeUsers": active_users,
        "publishedAchievements": published_achievements,
        "publishedDemands": published_demands,
        "eventCounts": event_counts,
        "aiCtr": _rate(event_counts["ai_result_clicked"], event_counts["ai_match_requested"]),
        "cooperationAcceptRate": _rate(accepted_cnt, total_reqs),
        "cooperationCompleteRate": _rate(completed_cnt, total_reqs),
        "avgCooperationHours": avg_hours,
        "definitions": {
            "aiCtr": "ai_result_clicked / ai_match_requested",
            "cooperationAcceptRate": "accepted_intents / total_intents_in_window",
            "cooperationCompleteRate": "completed_intents / total_intents_in_window",
        },
    }
