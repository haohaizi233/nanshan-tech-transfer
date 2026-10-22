"""
AI 模块服务层（P0-2）—— 异步任务边界

Architecture source: 06-api-design.md §AI, openapi.yaml /ai/match-tasks,
                     05-data-model-design.md §7.1/§7.3

边界原则：
- POST 创建任务：校验、去重、限流、快照固化、落库 queued、审计，
  然后交由进程内执行器（modules.ai.eval_executor）后台自动执行
- 任务执行状态流转 queued → running → succeeded / failed，
  GET 对 queued/running 返回 results=null，禁止假 AI 结果回填
- ai_match_result 仅由执行器/worker 写入；GET 在 succeeded 时读取组装
- 容灾：queued 超过 5 分钟的任务自动清理为 failed，GET 对外返回 stale
  终态（前端展示"排队超时"并可重试），任务不会永远卡在"排队中"
"""
import hashlib
import json
import time
from collections import defaultdict
from threading import Lock

from modules.ai import eval_executor
from core.errors import (
    TT_ACH_40301,
    TT_ACH_40401,
    TT_AI_40301,
    TT_AI_40401,
    TT_AI_42901,
    BizError,
)
from db import get_cursor
from modules.ai.evaluation import build_evaluation_view
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


def get_card_view_counts(cards: list[dict]) -> list[dict]:
    results = []
    with get_cursor() as cur:
        for card_type, table in (("achievement", "achievement"), ("demand", "demand")):
            ids = list(dict.fromkeys(card["id"] for card in cards if card["card_type"] == card_type))
            if not ids:
                continue
            cur.execute(
                f"SELECT id, view_count FROM {table} "
                "WHERE id = ANY(%s) AND status = 'published' AND deleted_at IS NULL",
                (ids,),
            )
            results.extend({
                "card_type": card_type,
                "id": row["id"],
                "viewCount": int(row.get("view_count") or 0),
            } for row in cur.fetchall())
    return results


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
    # 机会式容灾清理：先把卡死的 queued/running 任务落终态，
    # 避免去重窗口复用一个永远不会执行的任务。
    _safe_reap_dead_tasks()
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
            # 去重命中也补偿提交：进程重启后遗留的 queued 任务可被重新唤起。
            eval_executor.submit(existing["id"])
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

    # 提交后台执行（非阻塞）：任务不会停留在 queued 等外部 worker。
    eval_executor.submit(task_id)
    return _task_view(task_id), True


def get_evaluation_task(user_id: int, task_id: int) -> dict:
    """查询评估任务（仅创建者；succeeded 时带多维评分 + 评价报告）。

    容灾：
    - queued 超过 5 分钟（stale）→ 清理落库 failed，对外返回 status='stale'
      终态，前端停止轮询并展示"排队超时"，可重新发起；
    - 未过期的 queued 任务补偿提交给进程内执行器（进程重启后轮询即可恢复执行）。
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, task_type, status, created_by_user_id, target_id,
                   input_data_version, model_version_id, fail_reason,
                   progress_stage, created_at, started_at, finished_at,
                   (status = 'queued' AND created_at < NOW()
                    - (%s || ' seconds')::interval) AS stale
            FROM ai_task WHERE id = %s AND task_type = 'evaluation'
            """,
            (str(eval_executor.STALE_QUEUED_SECONDS), task_id),
        )
        task = cur.fetchone()
        if not task:
            code, message, status = TT_AI_40401
            raise BizError(code, message, status)
        if task["created_by_user_id"] != user_id:
            code, message, status = TT_AI_40301
            raise BizError(code, message, status)

        stale_queued = bool(task.get("stale")) and task["status"] == "queued"
        if stale_queued:
            # 卡死的"排队中"任务不再占位：落库 failed（幂等），对外返回 stale 终态。
            _safe_reap_dead_tasks()
        elif task["status"] == "queued":
            # 补偿提交（非阻塞）：进程重启/队列丢失后，轮询即可重新唤起执行。
            eval_executor.submit(task_id)

        # 实时阶段：running/queued 任务的当前阶段文案（modules/ai/progress.py
        # 写入）；终态任务返回 None。progress_stage 为下划线别名，与库列名一致。
        progress_stage = task.get("progress_stage") or None
        view = {
            "taskId": task["id"],
            "status": "stale" if stale_queued else task["status"],
            "stale": stale_queued,
            "progressStage": progress_stage,
            "progress_stage": progress_stage,
            "evaluation": None,
            "failReason": (
                eval_executor.STALE_QUEUED_REASON
                if stale_queued
                else _desensitize_fail_reason(task.get("fail_reason"))
            ),
            "createdAt": _iso(task.get("created_at")),
            "finishedAt": _iso(task.get("finished_at")),
            "modelVersionLabel": None,
            "inputDataVersion": task["input_data_version"],
        }

        if task["status"] == "succeeded":
            # 结果仅由 worker 写入；此处只做读取组装（禁止假评分回填）。
            # 多维评分/评价报告见 evaluation.build_evaluation_view（旧数据只给旧四维）。
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
                view["evaluation"] = build_evaluation_view(dict(row))
        return view


def list_evaluations(
    user_id: int,
    page: int = 1,
    page_size: int = 10,
    achievement_id: int | None = None,
) -> dict:
    """评价历史记录：当前用户发起过的全部成果评价（分页，倒序）。

    数据权限：仅任务创建者（= 成果 owner，见 create_evaluation_task）可见。
    列表项不含 report 全文（详情经 taskId 走 get_evaluation_task）。
    """
    page = max(1, int(page))
    page_size = max(1, min(50, int(page_size)))
    where = "t.created_by_user_id = %s"
    params: list = [user_id]
    if achievement_id:
        where += " AND e.achievement_id = %s"
        params.append(achievement_id)

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*) AS n
            FROM ai_evaluation e
            JOIN ai_task t ON e.task_id = t.id
            WHERE {where}
            """,
            params,
        )
        count_row = dict(cur.fetchone() or {})
        total = int(count_row.get("n") or 0)
        cur.execute(
            f"""
            SELECT e.*, a.title AS achievement_title
            FROM ai_evaluation e
            JOIN ai_task t ON e.task_id = t.id
            JOIN achievement a ON e.achievement_id = a.id
            WHERE {where}
            ORDER BY e.id DESC
            LIMIT %s OFFSET %s
            """,
            [*params, page_size, (page - 1) * page_size],
        )
        items = []
        for row in cur.fetchall():
            data = dict(row)
            item = build_evaluation_view(data)
            item.pop("report", None)  # 列表不带全文，详情走任务查询
            item["createdAt"] = _iso(data.get("created_at"))
            items.append(item)
    return {"list": items, "total": total, "page": page, "pageSize": page_size}


def _task_view(task_id: int) -> dict:
    with get_cursor() as cur:
        cur.execute("SELECT id, status, progress_stage FROM ai_task WHERE id = %s", (task_id,))
        row = cur.fetchone()
    return {"taskId": row["id"], "status": row["status"], "progressStage": row.get("progress_stage")}


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

def _safe_reap_dead_tasks() -> int:
    """容灾清理（尽力而为）：卡死任务标记 failed，失败不影响业务主流程。"""
    try:
        return eval_executor.reap_dead_tasks()
    except Exception:
        return 0
