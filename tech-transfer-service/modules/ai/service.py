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

from db import get_cursor
from core.errors import BizError
from core.errors import (
    TT_DMD_40401, TT_DMD_40301, TT_AI_40301, TT_AI_40401, TT_AI_42901,
)
from modules.audit.service import record as audit_record

# 同一需求重复创建去重窗口（秒）
DEDUPE_WINDOW_SECONDS = 10 * 60
# 用户级创建限流：1 小时 N 次
USER_HOURLY_LIMIT = 5

# 进程内限流计数（一期进程内实现，触发量级后迁 Redis —— 02 §9）
_user_task_times: dict[int, list[float]] = defaultdict(list)
_rate_lock = Lock()

# 快照固化字段（创建时刻的需求数据版本）
SNAPSHOT_FIELDS = (
    "id", "title", "description", "org_name", "region", "category_name",
    "coop_mode", "budget_min_wan", "budget_max_wan", "status", "version",
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


def create_match_task(user_id: int, user_no: str, demand_id: int, request_id=None) -> tuple[dict, bool]:
    """创建需求匹配任务。返回 (任务视图, 是否新建)。

    去重：同需求活跃任务（queued/running）在 10 分钟窗口内直接返回既有任务，
    is_new=False（路由层用 200 而非 202）。
    限流：仅真正新建任务消耗额度（校验失败/去重命中不计）。
    """
    with get_cursor(commit=True) as cur:
        cur.execute(
            "SELECT id, title, owner_user_id FROM demand WHERE id = %s AND deleted_at IS NULL",
            (demand_id,),
        )
        demand = cur.fetchone()
        if not demand:
            code, message, status = TT_DMD_40401
            raise BizError(code, "需求不存在", status)
        if demand["owner_user_id"] != user_id:
            code, message, status = TT_DMD_40301
            raise BizError(code, "非需求所有者", status)

        # 去重：同需求活跃任务直接复用
        cur.execute(
            """
            SELECT id, status, created_at FROM ai_task
            WHERE task_type = 'match' AND target_id = %s
              AND status IN ('queued', 'running')
              AND created_at > NOW() - INTERVAL '10 minutes'
            ORDER BY id DESC LIMIT 1
            """,
            (demand_id,),
        )
        existing = cur.fetchone()
        if existing:
            return _task_view(existing["id"]), False

        # 限流：去重未命中才计数（真正新建才消耗额度）
        _check_user_rate(user_id)

        # 输入快照固化（任务创建时刻的需求数据版本）
        cur.execute(
            """
            SELECT d.id, d.title, d.description, d.status, d.version,
                   d.coop_mode, d.budget_min_wan, d.budget_max_wan, d.region,
                   o.name AS org_name, dc.name AS category_name
            FROM demand d
            LEFT JOIN institution o ON d.org_id = o.id
            LEFT JOIN demand_category dc ON d.category_id = dc.id
            WHERE d.id = %s
            """,
            (demand_id,),
        )
        full = cur.fetchone() or {}
        snapshot = {f: full.get(f) for f in SNAPSHOT_FIELDS}
        snapshot_raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
        input_data_version = hashlib.sha256(snapshot_raw.encode("utf-8")).hexdigest()[:16]

        cur.execute(
            """
            INSERT INTO ai_task
                (task_type, status, created_by_user_id, target_type, target_id,
                 input_snapshot, input_data_version)
            VALUES ('match', 'queued', %s, 'demand', %s, %s, %s)
            RETURNING id
            """,
            (user_id, demand_id, snapshot_raw, input_data_version),
        )
        task_id = cur.fetchone()["id"]

    audit_record(
        "ai.task.create", "ai_task", resource_id=task_id,
        actor_user_id=user_id, actor_user_no=user_no,
        details={"taskType": "match", "demandId": demand_id,
                 "inputDataVersion": input_data_version},
        request_id=request_id,
    )
    return _task_view(task_id), True


def get_match_task(user_id: int, task_id: int) -> dict:
    """查询匹配任务（仅创建者；succeeded 时带 results）"""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, task_type, status, created_by_user_id, target_id,
                   input_data_version, model_version_id, fail_reason,
                   created_at, started_at, finished_at
            FROM ai_task WHERE id = %s AND task_type = 'match'
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
            "results": None,
            "failReason": task.get("fail_reason"),
            "createdAt": _iso(task.get("created_at")),
            "finishedAt": _iso(task.get("finished_at")),
            "modelVersionLabel": None,
            "inputDataVersion": task["input_data_version"],
        }

        if task["status"] == "succeeded":
            # 结果仅由 worker 写入；此处只做读取组装
            cur.execute(
                """
                SELECT r.achievement_id, r.score, r.match_reasons,
                       a.title AS achievement_title, a.source_org_name
                FROM ai_match_result r
                JOIN achievement a ON r.achievement_id = a.id
                WHERE r.task_id = %s
                ORDER BY r.score DESC, r.achievement_id ASC
                """,
                (task_id,),
            )
            rows = cur.fetchall() or []
            view["results"] = [
                {
                    "achievementId": r["achievement_id"],
                    "achievementTitle": r["achievement_title"],
                    "orgName": r.get("source_org_name"),
                    "score": float(r["score"]),
                    "matchReasons": _parse_reasons(r.get("match_reasons")),
                    "modelVersionLabel": None,
                }
                for r in rows
            ]
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


def _iso(dt):
    return dt.isoformat() if dt else None
