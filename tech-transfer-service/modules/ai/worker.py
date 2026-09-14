"""独立 AI worker：认领 queued 任务，调用 AiProvider，写回结果。

不嵌入 FastAPI lifespan，不占用企业微信长连接。
由 tools/run_ai_worker.py 启动。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from psycopg2.extras import Json

from db import close_pool, get_cursor, transaction
from modules.ai import provider

logger = logging.getLogger("nanshan.ai.worker")
MATCH_CANDIDATE_LIMIT = 30
FAIL_REASON_MAX = 500


def _clip(reason: str) -> str:
    text = (reason or "AI Provider 调用失败").strip()
    return text[:FAIL_REASON_MAX]


def claim_one() -> dict | None:
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, task_type, target_id, input_snapshot, version
            FROM ai_task
            WHERE status = 'queued'
            ORDER BY id
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute(
            """
            UPDATE ai_task
            SET status = 'running',
                started_at = NOW(),
                timeout_at = NOW() + INTERVAL '5 minutes',
                version = version + 1
            WHERE id = %s AND status = 'queued'
            RETURNING id, task_type, target_id, input_snapshot, version
            """,
            (row["id"],),
        )
        claimed = cur.fetchone()
    return dict(claimed) if claimed else None


def _fail(task_id: int, reason: str) -> None:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE ai_task
            SET status = 'failed', fail_reason = %s, finished_at = NOW(),
                version = version + 1
            WHERE id = %s AND status = 'running'
            """,
            (_clip(reason), task_id),
        )


def _snapshot(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _load_achievements() -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.title, a.tech_intro, a.maturity_level, a.source_org_name,
                   c.name AS category_name
            FROM achievement a
            LEFT JOIN achievement_category c ON a.category_id = c.id
            WHERE a.status = 'published' AND a.deleted_at IS NULL
            ORDER BY a.published_at DESC NULLS LAST, a.id DESC
            LIMIT %s
            """,
            (MATCH_CANDIDATE_LIMIT,),
        )
        rows = cur.fetchall() or []
    return [
        {
            "id": r["id"],
            "title": r.get("title"),
            "techIntro": (r.get("tech_intro") or "")[:800],
            "maturity": r.get("maturity_level"),
            "orgName": r.get("source_org_name"),
            "category": r.get("category_name"),
        }
        for r in rows
    ]


def _run_match(task: dict) -> None:
    demand_id = task["target_id"]
    snapshot = _snapshot(task.get("input_snapshot"))
    achievements = _load_achievements()
    results = provider.match_demand(snapshot, achievements)
    with transaction() as conn:
        cur = conn.cursor()
        for item in results:
            cur.execute(
                """
                INSERT INTO ai_match_result
                    (task_id, demand_id, achievement_id, score, match_reasons, model_version_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (task_id, achievement_id) DO NOTHING
                """,
                (
                    task["id"],
                    demand_id,
                    item["achievementId"],
                    item["score"],
                    Json(item["matchReasons"]),
                    0,
                ),
            )
        cur.execute(
            """
            UPDATE ai_task
            SET status = 'succeeded', fail_reason = NULL, finished_at = NOW(),
                version = version + 1
            WHERE id = %s AND status = 'running'
            """,
            (task["id"],),
        )


def _run_evaluation(task: dict) -> None:
    achievement_id = task["target_id"]
    snapshot = _snapshot(task.get("input_snapshot"))
    evaluation = provider.evaluate_achievement(snapshot)
    scores = evaluation["scores"]
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO ai_evaluation
                (task_id, achievement_id, score_tech, score_application,
                 score_maturity, score_feasibility, total_score, summary,
                 suggestions, model_version_id, input_data_version)
            SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, t.input_data_version
            FROM ai_task t
            WHERE t.id = %s
            ON CONFLICT (task_id) DO NOTHING
            """,
            (
                task["id"],
                achievement_id,
                scores["techFeature"],
                scores["applyScope"],
                scores["maturity"],
                scores["cooperation"],
                evaluation["totalScore"],
                evaluation["conclusion"],
                Json(evaluation["highlights"]),
                0,
                task["id"],
            ),
        )
        cur.execute(
            """
            UPDATE ai_task
            SET status = 'succeeded', fail_reason = NULL, finished_at = NOW(),
                version = version + 1
            WHERE id = %s AND status = 'running'
            """,
            (task["id"],),
        )


def process_one() -> str:
    """认领并执行一条任务。返回 idle / succeeded / failed / unconfigured。"""
    if not provider.configured():
        return "unconfigured"
    task = claim_one()
    if not task:
        return "idle"
    task_id = task["id"]
    try:
        if task["task_type"] == "match":
            _run_match(task)
        elif task["task_type"] == "evaluation":
            _run_evaluation(task)
        else:
            _fail(task_id, f"unknown task_type={task['task_type']}")
            return "failed"
        return "succeeded"
    except provider.AiProviderError as exc:
        logger.warning("ai worker provider error task=%s err=%s", task_id, exc)
        _fail(task_id, str(exc))
        return "failed"
    except Exception as exc:
        logger.exception("ai worker crashed task=%s", task_id)
        _fail(task_id, f"{type(exc).__name__}: {exc}")
        return "failed"


def close() -> None:
    close_pool()
