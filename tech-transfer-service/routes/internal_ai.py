"""
内部 AI 评估 API —— nanshan-ai-agent 服务间调用（对话内发起/查询成果评估）。

背景：对话的异步 run 通道执行时只有 user_id、没有用户 JWT（core/middleware.identity
只接受用户 Bearer 令牌），agent 无法透传用户身份调公共 /ai/evaluation-tasks。
因此这里提供 service-key 鉴权的内部端点，鉴权后按 userId 以「服务代用户」语义
复用 modules.ai.service 的原有链路：owner 校验、10 分钟去重、每小时限流、
输入快照、审计记录全部不变（数据权限仍由 create_evaluation_task 的
「仅成果 owner 可评估」保证）。

鉴权：X-AI-Service-Key 对 settings.AI_INTERNAL_SERVICE_KEY（hmac 常数时间比较）；
未配置密钥时仅接受本机回环来源（主服务与 agent 同机部署即满足）。

响应沿用统一 success() 信封；错误沿用 BizError → 全局异常处理器。
"""
import hmac
import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from config import settings
from core.errors import TT_COMMON_40101, BizError, bad_request
from core.response import get_request_id, success
from modules.ai.service import (
    create_evaluation_task,
    get_evaluation_task,
    list_evaluations,
)

logger = logging.getLogger("nanshan.error")

router = APIRouter(prefix="/internal/ai", tags=["internal-ai"])

# 未配置服务密钥时允许的回环来源（socket 对端地址，不可伪造）
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _client_host(request: Request) -> str:
    return (request.client.host if request.client else "") or ""


def require_service_key(request: Request) -> None:
    """服务间鉴权：X-AI-Service-Key；未配置密钥时仅放行本机回环。"""
    configured = (settings.AI_INTERNAL_SERVICE_KEY or "").strip()
    supplied = (request.headers.get("X-AI-Service-Key") or "").strip()
    if configured:
        if not supplied or not hmac.compare_digest(supplied, configured):
            code, _, status = TT_COMMON_40101
            raise BizError(code, "服务间鉴权失败", status)
        return
    if _client_host(request) not in _LOOPBACK_HOSTS:
        code, _, status = TT_COMMON_40101
        raise BizError(code, "服务间鉴权失败", status)


def _lookup_user_no(user_id: int) -> str:
    """审计字段 userNo 从 app_user.user_no 补齐（尽力而为，失败不阻塞评估）。"""
    from db import get_cursor

    try:
        with get_cursor() as cur:
            cur.execute("SELECT user_no FROM app_user WHERE id = %s", (user_id,))
            row = dict(cur.fetchone() or {})
        return str(row.get("user_no") or "")
    except Exception:
        logger.exception("[internal/ai] user_no 查询失败 user_id=%s", user_id)
        return ""


def _positive_int(raw, field: str) -> int:
    if isinstance(raw, bool):
        raise bad_request(f"{field} 必须为正整数")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise bad_request(f"{field} 必须为正整数")
    if value <= 0:
        raise bad_request(f"{field} 必须为正整数")
    return value


class InternalEvaluationCreateBody(BaseModel):
    """宽松解析：字段类型错误走 _positive_int 的统一 400 语义。"""

    model_config = ConfigDict(extra="ignore")
    userId: object = None
    achievementId: object = None


@router.post("/evaluation-tasks")
def internal_evaluation_create(
    body: InternalEvaluationCreateBody,
    request: Request,
    _auth: None = Depends(require_service_key),
):
    """创建评估任务。body: {"userId": int, "achievementId": int}。

    语义与 POST /api/tech-transfer/v1/ai/evaluation-tasks 一致（owner 校验、
    去重、限流、快照、审计），仅鉴权方式换成服务密钥、身份由 body 指定。
    """
    user_id = _positive_int(body.userId, "userId")
    achievement_id = _positive_int(body.achievementId, "achievementId")
    task, is_new = create_evaluation_task(
        user_id,
        _lookup_user_no(user_id),
        achievement_id,
        request_id=get_request_id(),
    )
    return success({**task, "isNew": is_new}, "任务已受理" if is_new else "任务进行中")


@router.get("/evaluation-tasks/{task_id}")
def internal_evaluation_detail(
    task_id: int,
    request: Request,
    _auth: None = Depends(require_service_key),
):
    """查询评估任务视图（含 succeeded 时的多维评分 + 评价报告）。"""
    user_id = _positive_int(request.query_params.get("userId"), "userId")
    return success(get_evaluation_task(user_id, task_id))


@router.get("/evaluations")
def internal_evaluation_history(
    request: Request,
    _auth: None = Depends(require_service_key),
):
    """评价历史（倒序分页）：query userId 必填，achievementId 可选过滤。"""
    user_id = _positive_int(request.query_params.get("userId"), "userId")
    raw_achievement = request.query_params.get("achievementId")
    achievement_id = None
    if raw_achievement not in (None, ""):
        achievement_id = _positive_int(raw_achievement, "achievementId")
    try:
        page = int(request.query_params.get("page") or 1)
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = int(request.query_params.get("pageSize") or 10)
    except (TypeError, ValueError):
        page_size = 10
    return success(list_evaluations(user_id, page, page_size, achievement_id))
