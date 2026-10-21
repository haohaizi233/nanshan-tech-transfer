"""零结果诊断：让「没找到」有据可依，而不是一句「不符合条件」。

背景：生产库里成果成熟度全部为 02_lab、报价绝大多数为「面议」。
用户问「中试完成以上的成果」或「100 万元以内的成果」时，如果只回一句
「暂未找到符合当前条件的成果」，用户会以为是自己条件写错了，
而事实是"库里根本没有满足该硬性条件的记录"。

这里在**结果为空且存在硬性条件**时才跑一次轻量聚合查询，
把库里的客观事实取出来，用于生成如实说明。
"""

from __future__ import annotations

from app.database import get_db
from app.runtime_trace import trace_stage
from app.services import taxonomy


@trace_stage("diagnose_empty")
def achievement_facts() -> dict:
    """成果库客观事实（已发布口径）。"""
    sql = """
        SELECT
            count(*) AS total,
            count(*) FILTER (
                WHERE price_min_wan IS NOT NULL OR price_max_wan IS NOT NULL
            ) AS priced,
            count(*) FILTER (
                WHERE pricing_mode = 'negotiable'
                OR (price_min_wan IS NULL AND price_max_wan IS NULL)
            ) AS unpriced,
            max(maturity_level) AS max_maturity
        FROM achievement
        WHERE status = 'published' AND deleted_at IS NULL
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
    except Exception:
        return {}
    if not row:
        return {}
    data = dict(row)
    return {
        "total": int(data.get("total") or 0),
        "priced": int(data.get("priced") or 0),
        "unpriced": int(data.get("unpriced") or 0),
        "max_maturity": data.get("max_maturity"),
    }


@trace_stage("diagnose_empty")
def demand_facts() -> dict:
    """需求库客观事实（已发布口径）。"""
    sql = """
        SELECT
            count(*) AS total,
            count(*) FILTER (
                WHERE budget_min_wan IS NOT NULL OR budget_max_wan IS NOT NULL
            ) AS priced,
            count(*) FILTER (
                WHERE budget_negotiable
                OR (budget_min_wan IS NULL AND budget_max_wan IS NULL)
            ) AS unpriced
        FROM demand
        WHERE status = 'published' AND deleted_at IS NULL
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
    except Exception:
        return {}
    if not row:
        return {}
    data = dict(row)
    return {
        "total": int(data.get("total") or 0),
        "priced": int(data.get("priced") or 0),
        "unpriced": int(data.get("unpriced") or 0),
    }


def facts_for(intent: str) -> dict:
    if intent == "search_achievement":
        return achievement_facts()
    if intent == "search_demand":
        return demand_facts()
    return {}
