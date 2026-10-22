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
from modules.ai import progress

logger = logging.getLogger("nanshan.ai.worker")
FAIL_REASON_MAX = 500

# 单进程并发上限：避免 worker 把所有 queued 都认领导致内存/连接堆积。
# 多 worker 部署时各自独立计数；该上限是软上限，超过仅跳过新认领。
MAX_RUNNING = 8
# 卡住任务回收阈值：running 超过该时长视为崩溃，标记 failed。
_STUCK_RUNNING_SECONDS = 10 * 60
_running_count = 0


def _clip(reason: str) -> str:
    text = (reason or "AI 服务暂时不可用，请稍后重试").strip()
    return text[:FAIL_REASON_MAX]


# 对外文案脱敏：fail_reason 中可能包含上游 Provider 名称、HTTP 状态、URL 片段、
# 超时栈细节等内部信息。这里替换为通用文案，原始 reason 仍保留在日志中。
_DESENSITIZE_HINTS = (
    "qwen", "openai", "hermes", "deepseek", "provider", "http",
    "https://", "http://", "timeout", "timed out", "url", "connection",
    "socket", "ssl", "proxy", "ai_agent", "api_key", "authorization",
)
_DESENSITIZE_MSG = "AI 服务暂时不可用，请稍后重试"


def _desensitize_reason(reason: str) -> str:
    """屏蔽 fail_reason 中的 Provider 内部细节，避免泄露给客户端。"""
    text = (reason or "").strip()
    if not text:
        return _DESENSITIZE_MSG
    lowered = text.lower()
    if any(hint in lowered for hint in _DESENSITIZE_HINTS):
        return _DESENSITIZE_MSG
    return _clip(text)


def reap_stuck() -> int:
    """回收卡住的 running 任务：超过 _STUCK_RUNNING_SECONDS 标记为 failed。

    worker 崩溃/被 kill 后，认领为 running 的任务会一直停留在该状态，
    阻塞用户重试。reaper 在每次轮询前调用，幂等且安全。
    """
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE ai_task
            SET status = 'failed',
                fail_reason = %s,
                finished_at = NOW(),
                version = version + 1
            WHERE status = 'running'
              AND started_at IS NOT NULL
              AND NOW() - started_at > (%s || ' seconds')::interval
            """,
            (_clip("timeout: 任务执行超时，已被回收"), str(_STUCK_RUNNING_SECONDS)),
        )
        return int(cur.rowcount or 0)


def claim_one() -> dict | None:
    global _running_count
    if _running_count >= MAX_RUNNING:
        return None
    with transaction() as conn:
        cur = conn.cursor()
        try:
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
        finally:
            cur.close()
    if claimed:
        _running_count += 1
    return dict(claimed) if claimed else None


def _finish_running() -> None:
    global _running_count
    if _running_count > 0:
        _running_count -= 1


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


def _report_stage(task_id: int, stage: str) -> None:
    """实时阶段回传（best-effort）：进度写库失败绝不打断评估主流程。"""
    try:
        progress.set_stage(task_id, stage)
    except Exception:
        logger.exception("ai evaluation stage report failed task=%s stage=%s", task_id, stage)


def _run_evaluation(task: dict, timeout: float | None = None) -> None:
    task_id = task["id"]
    achievement_id = task["target_id"]
    # 实时阶段回传：每个关键阶段把文案写入 ai_task.progress_stage，
    # 供 GET /ai/evaluation-tasks/{id} 轮询返回（best-effort，失败不影响评估）。
    _report_stage(task_id, progress.STAGE_READING)  # 阶段1：快照加载
    snapshot = _snapshot(task.get("input_snapshot"))
    result = provider.evaluate_achievement(
        snapshot,
        timeout=timeout,
        # 阶段2/3/4（LLM 调用 → 解析输出 → 评分换算）由 provider 回传
        on_stage=lambda stage: _report_stage(task_id, stage),
    )
    legacy = result["legacyScores"]
    _report_stage(task_id, progress.STAGE_SAVING)  # 阶段5：写入数据库
    with transaction() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO ai_evaluation
                    (task_id, achievement_id, score_tech, score_application,
                     score_maturity, score_feasibility, total_score, summary,
                     suggestions, dimensions, report_sections, rating,
                     model_version_id, input_data_version)
                SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       t.input_data_version
                FROM ai_task t
                WHERE t.id = %s AND t.status = 'running'
                ON CONFLICT (task_id) DO NOTHING
                """,
                (
                    task["id"],
                    achievement_id,
                    legacy["techFeature"],
                    legacy["applyScope"],
                    legacy["maturity"],
                    legacy["cooperation"],
                    result["totalScore"],
                    result["conclusion"],
                    Json(result["highlights"]),
                    Json(result["dimensions"]),
                    Json(result["report"]),
                    result["rating"],
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
            if not cur.rowcount:
                # 超时看门狗/清理器已把任务标记 failed：迟到的结果被丢弃，
                # 不覆盖终态（INSERT 的 SELECT 同样带 status='running' 条件，
                # 不会留下孤儿评分行）。
                logger.warning("ai worker result discarded task=%s (no longer running)", task["id"])
        finally:
            cur.close()


def process_one() -> str:
    """认领并执行一条任务。返回 idle / succeeded / failed / unconfigured。"""
    if not provider.configured():
        return "unconfigured"
    # 每轮先回收卡住的 running 任务，避免长期占用名额导致新任务无法认领。
    try:
        reaped = reap_stuck()
        if reaped:
            logger.info("ai worker reaped %s stuck task(s)", reaped)
    except Exception:
        logger.exception("ai worker reap_stuck failed")
    task = claim_one()
    if not task:
        return "idle"
    task_id = task["id"]
    try:
        if task["task_type"] == "evaluation":
            _run_evaluation(task)
        else:
            _fail(task_id, f"unknown task_type={task['task_type']}")
            return "failed"
        return "succeeded"
    except provider.AiProviderError as exc:
        logger.warning("ai worker provider error task=%s err=%s", task_id, exc)
        _fail(task_id, _desensitize_reason(str(exc)))
        return "failed"
    except Exception as exc:
        logger.exception("ai worker crashed task=%s", task_id)
        _fail(task_id, _desensitize_reason(f"{type(exc).__name__}: {exc}"))
        return "failed"
    finally:
        _finish_running()


def close() -> None:
    close_pool()
