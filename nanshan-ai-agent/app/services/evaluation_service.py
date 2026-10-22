"""
成果评估工具 —— 对话内发起 / 查询成果评估。

异步 run 通道只有 user_id、没有用户 JWT，不能调公共 /ai/evaluation-tasks；
这里走 tech-transfer-service 的 service-key 鉴权内部端点（routes/internal_ai.py）：

  POST /internal/ai/evaluation-tasks            创建（或复用）评估任务
  GET  /internal/ai/evaluation-tasks/{taskId}   轮询任务状态（succeeded 时带评估视图）
  GET  /internal/ai/evaluations                 查询已有评价历史（「查看评估结果」）

响应沿用后端统一 success() 信封 {"code": 0, "message": ..., "data": ...}；
错误沿用 BizError 结构 {"code": "TT_*", "message": ...}（HTTP 状态码非 2xx）。

轮询预算：EVAL_POLL_TIMEOUT_SECONDS 减去 EVAL_POLL_RESERVE_SECONDS
（为组装回复/入库留余量）。超预算返回 pending，由对话回复
「任务进行中，稍后查看评估结果」，不做无界等待。
"""
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from app.config import settings
from app.database import get_db
from app.services.query_utils import escape_like_term

logger = logging.getLogger("nanshan.ai-agent")

# 单次 HTTP 调用超时（秒）；轮询时与剩余预算取小。
DEFAULT_HTTP_TIMEOUT_SECONDS = 10.0

# 后端业务错误 → 对话可直接转述的用户文案（其余走通用兜底）。
_ERROR_MESSAGES = {
    "TT_ACH_40401": "成果不存在或已删除，无法发起评估。",
    "TT_ACH_40301": "仅成果所有者可以发起评估，请确认该成果属于你。",
    "TT_AI_40301": "无权查看该评估任务。",
    "TT_AI_40401": "评估任务不存在，请重新发起评估。",
    "TT_AI_42901": "评估发起太频繁了，请稍后再试。",
    "TT_COMMON_40001": "评估请求参数无效，请重新选择成果。",
    "TT_COMMON_40101": "评估服务暂时不可用，请稍后重试。",
}

GENERIC_ERROR = "评估服务暂时不可用，请稍后重试"
SUCCEEDED_WITHOUT_RESULT = "任务已完成，评估结果暂未生成，可稍后重新查看或重新发起"


class EvaluationError(Exception):
    """评估服务不可用 / 业务拒绝。user_message 可直接回给用户。"""

    def __init__(self, user_message: str, code: str | None = None, status_code: int | None = None):
        super().__init__(user_message)
        self.user_message = user_message
        self.code = code
        self.status_code = status_code


def _service_key() -> str:
    return (settings.TECH_TRANSFER_SERVICE_KEY or settings.AI_INTERNAL_SERVICE_KEY or "").strip()


def _api(method: str, path: str, payload: dict | None = None, query: dict | None = None,
         timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS) -> dict | None:
    """调用内部端点并解 success() 信封，返回 data。失败抛 EvaluationError。"""
    url = settings.TECH_TRANSFER_API_URL + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-AI-Service-Key": _service_key(),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            parsed = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        raise EvaluationError(_http_error_message(exc), status_code=exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        logger.warning("evaluation_api_unreachable path=%s reason=%s", path, type(exc).__name__)
        raise EvaluationError(GENERIC_ERROR) from exc
    if not isinstance(parsed, dict) or parsed.get("code") != 0:
        raise EvaluationError(GENERIC_ERROR)
    return parsed.get("data")


def _http_error_message(exc: urllib.error.HTTPError) -> str:
    """HTTP 非 2xx：解析 BizError 信封，映射成用户可读文案（内部细节不外泄）。"""
    code = None
    try:
        payload = json.loads(exc.read().decode("utf-8") or "{}")
        code = str(payload.get("code") or "")
    except Exception:
        payload = {}
    if code in _ERROR_MESSAGES:
        return _ERROR_MESSAGES[code]
    logger.warning("evaluation_api_error status=%s code=%s", exc.code, code)
    return GENERIC_ERROR


# ── 目标成果定位 ──────────────────────────────────────────────────

_TARGET_COLUMNS = (
    "id, owner_user_id, status, deleted_at, title, source_org_name, tech_intro, "
    "pricing_mode, price_min_wan, price_max_wan, maturity_level, application_fields, "
    "innovation_points, contact_name, contact_phone, contact_email, view_count, created_at"
)


def resolve_target(user_id: int, target_id: int | None = None, target_name: str | None = None) -> dict | None:
    """按成果 ID / 名称定位待评估成果。

    评估走 owner 通道（数据权限由后端 create_evaluation_task 复核），
    不套用搜索的可见性过滤；名称模糊命中时优先本人名下成果。
    """
    if target_id is not None:
        sql = f"SELECT {_TARGET_COLUMNS} FROM achievement WHERE id = %s AND deleted_at IS NULL"
        params: list = [target_id]
    elif target_name:
        sql = (
            f"SELECT {_TARGET_COLUMNS} FROM achievement "
            "WHERE deleted_at IS NULL AND title ILIKE %s ESCAPE E'\\\\' "
            "ORDER BY (owner_user_id = %s) DESC, (title = %s) DESC, id DESC LIMIT 1"
        )
        params = [f"%{escape_like_term(target_name)}%", user_id, target_name]
    else:
        return None
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
    return dict(row) if row else None


def list_owned_targets(user_id: int, limit: int = 10) -> list[dict]:
    """用户名下成果列表（未删除，最新在前）。

    评估请求没给出具体成果（无 ID/名称）时不盲猜目标，
    返回本人名下成果供用户挑选；权限口径与 resolve_target 一致（owner 通道）。
    """
    sql = (
        f"SELECT {_TARGET_COLUMNS} FROM achievement "
        "WHERE owner_user_id = %s AND deleted_at IS NULL "
        "ORDER BY id DESC LIMIT %s"
    )
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (user_id, limit))
            rows = cur.fetchall()
    return [dict(row) for row in rows]


# ── 评估摘要 ──────────────────────────────────────────────────


def summarize(evaluation: dict | None) -> dict | None:
    """build_evaluation_view 视图 → 对话卡片摘要。"""
    if not isinstance(evaluation, dict):
        return None
    dimensions = evaluation.get("dimensions") or []
    return {
        "totalScore": evaluation.get("totalScore"),
        "rating": evaluation.get("rating"),
        "ratingLabel": evaluation.get("ratingLabel"),
        "conclusion": evaluation.get("conclusion") or "",
        "highlights": [str(item) for item in (evaluation.get("highlights") or []) if str(item).strip()],
        "dimensions": [item for item in dimensions if isinstance(item, dict)],
    }


def latest_evaluation(user_id: int, achievement_id: int) -> dict | None:
    """最近一次已完成的评估摘要；无历史返回 None。"""
    data = _api(
        "GET", "/internal/ai/evaluations",
        query={"userId": user_id, "achievementId": achievement_id, "page": 1, "pageSize": 1},
    )
    items = (data or {}).get("list") or []
    if not items:
        return None
    summary = summarize(items[0])
    if summary is None:
        return None
    return {"status": "succeeded", "taskId": items[0].get("taskId"), "evaluation": summary}


def evaluate(user_id: int, achievement_id: int, prefer_existing: bool = False) -> dict:
    """发起（或查询）成果评估。

    返回 {"status": ..., "taskId": ..., ...}：
      succeeded — evaluation 为摘要 dict（totalScore/rating/ratingLabel/
                  conclusion/highlights/dimensions）
      pending   — 轮询预算耗尽，任务仍在跑（progressStage 为当前阶段文案）
      failed    — 任务失败 / 排队超时（failReason 已脱敏）
      missing   — 仅查询（prefer_existing=True）且该成果还没有评估记录
    """
    if prefer_existing:
        existing = latest_evaluation(user_id, achievement_id)
        return existing if existing else {"status": "missing", "taskId": None, "evaluation": None}

    created = _api(
        "POST", "/internal/ai/evaluation-tasks",
        payload={"userId": user_id, "achievementId": achievement_id},
    ) or {}
    task_id = created.get("taskId")
    # 立即返回pending，不轮询等待（前端通过/ai/evaluation-tasks/{id}/stream获取进度）
    if task_id is not None:
        return {"status": "pending", "taskId": task_id, "progressStage": created.get("progressStage", "排队中"), "evaluation": None}
    if task_id is None:
        raise EvaluationError(GENERIC_ERROR)

    budget = max(0.0, settings.EVAL_POLL_TIMEOUT_SECONDS - settings.EVAL_POLL_RESERVE_SECONDS)
    deadline = time.monotonic() + budget
    view: dict = {}
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            view = _api(
                "GET", f"/internal/ai/evaluation-tasks/{task_id}",
                query={"userId": user_id},
                timeout=min(DEFAULT_HTTP_TIMEOUT_SECONDS, remaining),
            ) or {}
        except EvaluationError as exc:
            # 轮询瞬时故障不推翻已受理的任务：按进行中收尾。
            logger.warning("evaluation_poll_failed task_id=%s code=%s", task_id, exc.code)
            break
        status = view.get("status")
        if status == "succeeded":
            summary = summarize(view.get("evaluation"))
            if summary is None:
                return {"status": "failed", "taskId": task_id, "failReason": SUCCEEDED_WITHOUT_RESULT}
            return {"status": "succeeded", "taskId": task_id, "evaluation": summary}
        if status in ("failed", "stale"):
            return {"status": "failed", "taskId": task_id, "failReason": view.get("failReason") or ""}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(settings.EVAL_POLL_INTERVAL_SECONDS, remaining))
    return {"status": "pending", "taskId": task_id, "progressStage": view.get("progressStage") or None}
