"""
AI 模块服务层（P0-2）—— 异步任务边界

Architecture source: 06-api-design.md §AI, openapi.yaml /ai/match-tasks,
                     05-data-model-design.md §7.1/§7.3

边界原则（P0-2 只交付稳定边界，不实现 AI 执行）：
- POST 创建任务：校验、去重、限流、快照固化、落库 queued、审计
- 任务执行由外部 worker 认领（本阶段未接入）——任务保持 queued，
  GET 对 queued/running 返回 results=null，禁止假 AI 结果回填
- ai_match_result 仅由 worker 写入；GET 在 succeeded 时读取组装
"""
import hashlib
import json
import time
from collections import defaultdict
from threading import Lock

from core.errors import (
    TT_ACH_40301,
    TT_ACH_40401,
    TT_AI_40301,
    TT_AI_40401,
    TT_AI_42901,
    BizError,
)
from db import get_cursor
from modules.audit.service import record as audit_record

# 同一需求重复创建去重窗口（秒）—— 评估任务复用同一限流，保留常量供未来匹配复用
DEDUPE_WINDOW_SECONDS = 10 * 60
# 用户级创建限流：1 小时 N 次
USER_HOURLY_LIMIT = 5

# 进程内限流计数（一期进程内实现，触发量级后迁 Redis —— 02 §9）
_user_task_times: dict[int, list[float]] = defaultdict(list)
_rate_lock = Lock()

# 成果评估快照字段（创建时刻的成果数据版本）
SNAPSHOT_FIELDS_EVAL = (
    "id", "title", "tech_intro", "maturity_level", "source_org_name",
    "category_name", "status", "version",
)


def _check_user_rate(user_id: int):
    now = time.time()
    with _rate_lock:
        times = _user_task_times[user_id]
        _user_task_times[user_id] = [t for t in times if now - t < 3600]
        if len(_user_task_times[user_id]) >= USER_HOURLY_LIMIT:
            code, message, status = TT_AI_42901
            raise BizError(code, message, status)
        _user_task_times[user_id].append(now)


def create_evaluation_task(user_id: int, user_no: str, achievement_id: int, request_id=None) -> tuple[dict, bool]:
    """创建成果评估任务。返回 (任务视图, 是否新建)。

    数据权限：成果 owner only（评估触发权归成果方）。
    去重/限流与 match 同模式：同成果活跃任务 10 分钟窗口复用；
    仅真正新建消耗用户小时额度（与 match 共享）。
    """
    with get_cursor(commit=True) as cur:
        cur.execute(
            "SELECT id, title, owner_user_id FROM achievement WHERE id = %s AND deleted_at IS NULL FOR UPDATE",
            (achievement_id,),
        )
        achievement = cur.fetchone()
        if not achievement:
            code, message, status = TT_ACH_40401
            raise BizError(code, "成果不存在", status)
        if achievement["owner_user_id"] != user_id:
            code, message, status = TT_ACH_40301
            raise BizError(code, "非成果所有者", status)

        # 去重：同成果活跃任务直接复用
        cur.execute(
            """
            SELECT id, status, created_at FROM ai_task
            WHERE task_type = 'evaluation' AND target_id = %s
              AND status IN ('queued', 'running')
              AND created_at > NOW() - INTERVAL '10 minutes'
            ORDER BY id DESC LIMIT 1
            """,
            (achievement_id,),
        )
        existing = cur.fetchone()
        if existing:
            return _task_view(existing["id"]), False

        # 限流：去重未命中才计数（与 match 共享小时额度）
        _check_user_rate(user_id)

        # 输入快照固化（任务创建时刻的成果数据版本）
        cur.execute(
            """
            SELECT a.id, a.title, a.tech_intro, a.maturity_level,
                   a.source_org_name, a.status, a.version,
                   c.name AS category_name
            FROM achievement a
            LEFT JOIN achievement_category c ON a.category_id = c.id
            WHERE a.id = %s
            """,
            (achievement_id,),
        )
        full = cur.fetchone() or {}
        snapshot = {f: full.get(f) for f in SNAPSHOT_FIELDS_EVAL}
        snapshot_raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
        input_data_version = hashlib.sha256(snapshot_raw.encode("utf-8")).hexdigest()[:16]

        cur.execute(
            """
            INSERT INTO ai_task
                (task_type, status, created_by_user_id, target_type, target_id,
                 input_snapshot, input_data_version)
            VALUES ('evaluation', 'queued', %s, 'achievement', %s, %s, %s)
            RETURNING id
            """,
            (user_id, achievement_id, snapshot_raw, input_data_version),
        )
        task_id = cur.fetchone()["id"]

        audit_record(
            "ai.task.create", "ai_task", resource_id=task_id,
            actor_user_id=user_id, actor_user_no=user_no,
            details={"taskType": "evaluation", "achievementId": achievement_id,
                     "inputDataVersion": input_data_version},
            request_id=request_id, cur=cur,
        )

    return _task_view(task_id), True


def get_evaluation_task(user_id: int, task_id: int) -> dict:
    """查询评估任务（仅创建者；succeeded 时带 evaluation 四维评分）"""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, task_type, status, created_by_user_id, target_id,
                   input_data_version, model_version_id, fail_reason,
                   created_at, started_at, finished_at
            FROM ai_task WHERE id = %s AND task_type = 'evaluation'
            """,
            (task_id,),
        )
        task = cur.fetchone()
        if not task:
            code, message, status = TT_AI_40401
            raise BizError(code, message, status)
        if task["created_by_user_id"] != user_id:
            code, message, status = TT_AI_40301
            raise BizError(code, message, status)

        view = {
            "taskId": task["id"],
            "status": task["status"],
            "evaluation": None,
            "failReason": _desensitize_fail_reason(task.get("fail_reason")),
            "createdAt": _iso(task.get("created_at")),
            "finishedAt": _iso(task.get("finished_at")),
            "modelVersionLabel": None,
            "inputDataVersion": task["input_data_version"],
        }

        if task["status"] == "succeeded":
            # 结果仅由 worker 写入；此处只做读取组装（禁止假评分回填）
            cur.execute(
                """
                SELECT e.*, a.title AS achievement_title
                FROM ai_evaluation e
                JOIN achievement a ON e.achievement_id = a.id
                WHERE e.task_id = %s
                """,
                (task_id,),
            )
            row = cur.fetchone()
            if row:
                view["evaluation"] = {
                    "achievementId": row["achievement_id"],
                    "achievementTitle": row["achievement_title"],
                    "scores": {
                        "techFeature": float(row["score_tech"]),
                        "applyScope": float(row["score_application"]),
                        "maturity": float(row["score_maturity"]),
                        "cooperation": float(row["score_feasibility"]),
                    },
                    "totalScore": float(row["total_score"]),
                    "conclusion": row.get("summary") or "",
                    "highlights": _parse_reasons(row.get("suggestions")),
                    "modelVersionLabel": None,
                }
        return view


def _task_view(task_id: int) -> dict:
    with get_cursor() as cur:
        cur.execute("SELECT id, status FROM ai_task WHERE id = %s", (task_id,))
        row = cur.fetchone()
    return {"taskId": row["id"], "status": row["status"]}


def _parse_reasons(raw):
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


# fail_reason 脱敏：屏蔽 Provider 内部细节，避免泄露给客户端。
_DESENSITIZE_HINTS = (
    "qwen", "openai", "hermes", "deepseek", "provider", "http",
    "https://", "http://", "timeout", "timed out", "url", "connection",
    "socket", "ssl", "proxy", "ai_agent", "api_key", "authorization",
)
_DESENSITIZE_MSG = "AI 服务暂时不可用，请稍后重试"


def _desensitize_fail_reason(reason: str | None) -> str | None:
    if not reason:
        return reason
    text = str(reason).strip()
    if not text:
        return reason
    lowered = text.lower()
    if any(hint in lowered for hint in _DESENSITIZE_HINTS):
        return _DESENSITIZE_MSG
    return text


def _iso(dt):
    return dt.isoformat() if dt else None
