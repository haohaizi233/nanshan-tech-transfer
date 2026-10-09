"""
AI 路由 —— POST /ai/chat、POST /ai/match（同步，转发 nanshan-ai-agent），
POST /ai/evaluation-tasks、GET /ai/evaluation-tasks/{taskId}（异步任务）。

需求匹配与自然语言对话同步经本服务转发到独立的 ai-agent；成果评估沿用
异步任务制（202 + 轮询），执行由独立 worker 认领，不把企业微信长连接嵌进本进程。
"""
import json
import logging
import time
import threading
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from config import settings
from core.response import success, get_request_id
from core.middleware import identity
from core.errors import BizError, TT_COMMON_42901, ai_provider_failed, ai_unavailable, bad_request
from core.idempotency import idempotent_create, cache_response as cache_idem_response
from core.rate_limit import check_user_rate
from core.request_schemas import AiChatRequest, AiMatchRequest, EvaluationTaskRequest
from modules.ai.service import (
    create_evaluation_task, get_evaluation_task,
)
from modules.ai.chat_store import append_message, append_turn, list_messages, clear_messages

logger = logging.getLogger("nanshan.error")

# 与小程序 config/feature-flags.js 同步；实际开关读 settings.AI_FEATURE_ENABLED。
AI_FEATURE_ENABLED = settings.AI_FEATURE_ENABLED

# 同步阻塞 LLM 调用并发上限：避免少量请求同时打满上游连接/线程池。
# 信号量在进程内共享，acquire 期间阻塞调用线程，release 后下一请求进入。
_AI_CONCURRENCY = threading.Semaphore(max(1, int(getattr(settings, "AI_MAX_CONCURRENT", 4))))
_AGENT_RETRY_STATUS = {502, 503, 504, 429}
_AGENT_RETRY_TIMES = 2
_AGENT_RETRY_BACKOFF = (0.5, 1.5)


def require_ai_enabled():
    if not settings.AI_FEATURE_ENABLED:
        raise ai_unavailable("该功能即将开放")


router = APIRouter(
    prefix="/api/tech-transfer/v1",
    tags=["ai"],
    dependencies=[Depends(require_ai_enabled)],
)


# ── 成果评估（异步任务）──────────────────────────────────────
@router.post("/ai/evaluation-tasks", status_code=202)
def evaluation_tasks_create(request: Request, body: EvaluationTaskRequest, user: dict = Depends(identity)):
    achievement_id = body.as_dict().get("achievementId")
    if not isinstance(achievement_id, int) or achievement_id <= 0:
        from core.errors import bad_request
        raise bad_request("achievementId 必须为正整数")
    # L2: X-Idempotency-Key 幂等去重（TTL 10min，重复请求直接回放缓存响应）
    idem_resp = idempotent_create(request, user)
    if idem_resp is not None:
        return idem_resp
    task, is_new = create_evaluation_task(
        user["userId"], user.get("userNo", ""), achievement_id,
        request_id=get_request_id(),
    )
    if not is_new:
        resp = JSONResponse(status_code=200, content=success(task, "任务进行中"))
    else:
        resp = JSONResponse(status_code=202, content=success(task, "任务已受理"))
    # L2: 仅缓存成功响应，供后续重复请求回放
    cache_idem_response(user["userId"], (request.headers.get("X-Idempotency-Key") or "").strip(), resp.status_code, success(task, "任务已受理"))
    return resp


@router.get("/ai/evaluation-tasks/{task_id}")
def evaluation_task_detail(task_id: int, user: dict = Depends(identity)):
    return success(get_evaluation_task(user["userId"], task_id))


# ── 自然语言对话代理（nanshan-ai-agent demo）──────────────────
# 小程序自由问答经本路由转发到独立的 ai-agent 服务，回包结构为
# {success, intent, message, data:[achievement|demand 卡片]}。
# 失败不再一律映射 503：agent 不可达 → 503；上层模型/agent 有回包 → 502，
# details 带 layer / llmStatus / reason，方便区分是模型还是本地代理的问题。
_UPSTREAM_BODY_LIMIT = 300


def _read_http_error_body(exc: urllib.error.HTTPError, limit: int = _UPSTREAM_BODY_LIMIT) -> str:
    try:
        return exc.read(limit).decode("utf-8", "replace")
    except Exception:
        return ""


def _safe_snippet(text: str, limit: int = _UPSTREAM_BODY_LIMIT) -> str:
    text = (text or "").replace("\r\n", "\n").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _network_reason(exc: BaseException) -> str:
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        name = type(cur).__name__
        text = str(cur).lower()
        if isinstance(cur, TimeoutError) or name in {"TimeoutError", "ReadTimeoutError"}:
            return "timeout"
        if "timed out" in text:
            return "timeout"
        if name in {"RemoteDisconnected", "ConnectionResetError"} or (
            "closed connection" in text or "connection reset" in text or "disconnected" in text
        ):
            return "connection_reset"
        if name == "ConnectionRefusedError" or "refused" in text:
            return "connection_refused"
        nxt = None
        if isinstance(cur, urllib.error.URLError) and not isinstance(cur, urllib.error.HTTPError):
            reason = getattr(cur, "reason", None)
            if isinstance(reason, BaseException):
                nxt = reason
        cur = nxt or cur.__cause__
    return "unreachable"


def _parse_agent_error_details(agent_status: int, body: str) -> dict:
    """从 ai-agent 错误回包抽出可对外的诊断字段，不含内部路径/密钥。"""
    details: dict = {
        "layer": "agent",
        "agentStatus": agent_status,
        "reason": "http_error",
    }
    payload = None
    if body:
        try:
            payload = json.loads(body)
        except (ValueError, TypeError):
            payload = None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        layer = detail.get("layer")
        if layer in ("llm", "agent"):
            details["layer"] = layer
        if detail.get("llmStatus") is not None:
            try:
                details["llmStatus"] = int(detail["llmStatus"])
            except (TypeError, ValueError):
                details["llmStatus"] = detail["llmStatus"]
        reason = detail.get("llmReason") or detail.get("agentReason") or detail.get("reason")
        if reason:
            details["reason"] = str(reason)[:64]
        llm_body = detail.get("llmBody")
        if isinstance(llm_body, str) and llm_body.strip():
            details["upstreamBody"] = _safe_snippet(llm_body)
        elif details.get("layer") != "llm" and detail.get("message"):
            details["upstreamBody"] = _safe_snippet(str(detail["message"]))
    elif isinstance(detail, str) and detail.strip():
        details["upstreamBody"] = _safe_snippet(detail)
    elif body:
        details["upstreamBody"] = _safe_snippet(body)
    return details


def _raise_from_agent_http(agent_status: int, body: str) -> None:
    details = _parse_agent_error_details(agent_status, body)
    logger.warning(
        "[ai/chat] agent http error status=%s layer=%s llm_status=%s reason=%s body=%s",
        agent_status,
        details.get("layer"),
        details.get("llmStatus"),
        details.get("reason"),
        details.get("upstreamBody"),
    )
    if agent_status == 429:
        code, message, status = TT_COMMON_42901
        raise BizError(code, "AI 请求过于频繁，请稍后重试", status, details)
    if details.get("layer") == "llm" or agent_status in (500, 502, 504):
        raise ai_provider_failed("AI 服务暂时不可用，请稍后重试", details)
    raise ai_unavailable("AI 助手暂时不可用，请稍后重试", details)


def _raise_from_agent_network(exc: Exception) -> None:
    reason = _network_reason(exc)
    details = {"layer": "agent", "reason": reason}
    logger.warning("[ai/chat] agent 调用失败 reason=%s err=%r", reason, exc)
    raise ai_unavailable("AI 助手暂时不可用，请稍后重试", details)


def _forward_to_agent(message: str, exclude_user_id: int | None = None) -> dict:
    payload_dict = {"message": message}
    # 透传当前用户 id，agent 检索时排除该用户自己的成果/需求，避免自我推荐。
    if exclude_user_id is not None:
        payload_dict["exclude_owner_user_id"] = exclude_user_id
    payload = json.dumps(payload_dict).encode("utf-8")
    req = urllib.request.Request(
        settings.AI_AGENT_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    last_exc: Exception | None = None
    last_http: tuple[int, str] | None = None
    for attempt in range(_AGENT_RETRY_TIMES):
        try:
            # D6: 信号量 acquire 加超时，防止无限阻塞导致线程饥饿
            if not _AI_CONCURRENCY.acquire(timeout=30.0):
                raise urllib.error.URLError("AI 并发繁忙，请稍后重试")
            try:
                with urllib.request.urlopen(req, timeout=settings.AI_AGENT_TIMEOUT) as resp:
                    body = resp.read()
            finally:
                _AI_CONCURRENCY.release()
            data = json.loads(body.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("agent response is not a JSON object")
            return data
        except urllib.error.HTTPError as exc:
            last_exc = exc
            body = _read_http_error_body(exc)
            last_http = (exc.code, body)
            logger.warning(
                "[ai/chat] agent http error status=%s attempt=%s body=%s",
                exc.code, attempt + 1, body,
            )
            # 上层模型已经在 agent 内重试过；再转一圈只会把浏览器空等拉长。
            preview = _parse_agent_error_details(exc.code, body)
            retryable = exc.code in _AGENT_RETRY_STATUS and preview.get("layer") != "llm"
            if retryable and attempt < _AGENT_RETRY_TIMES - 1:
                time.sleep(_AGENT_RETRY_BACKOFF[min(attempt, len(_AGENT_RETRY_BACKOFF) - 1)])
                continue
            _raise_from_agent_http(exc.code, body)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last_exc = exc
            logger.warning("[ai/chat] agent 调用失败 attempt=%s err=%r", attempt + 1, exc)
            retryable = isinstance(exc, (TimeoutError, OSError)) or (
                isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError)
            )
            if retryable and attempt < _AGENT_RETRY_TIMES - 1:
                time.sleep(_AGENT_RETRY_BACKOFF[min(attempt, len(_AGENT_RETRY_BACKOFF) - 1)])
                continue
            if isinstance(exc, ValueError):
                raise ai_provider_failed(
                    "AI Agent 返回格式异常",
                    {"layer": "agent", "reason": "invalid_response"},
                ) from None
            _raise_from_agent_network(exc)
    logger.warning("[ai/chat] agent 调用失败 err=%r", last_exc)
    if last_http is not None:
        _raise_from_agent_http(last_http[0], last_http[1])
    if last_exc is not None:
        _raise_from_agent_network(last_exc)
    raise ai_unavailable("AI 助手暂时不可用，请稍后重试", {"layer": "agent", "reason": "unreachable"})


def _persist_failed_turn(user_id: int, user_message: str, assistant_message: str) -> None:
    """失败时也保留问答痕迹，避免刷新后用户看不到自己刚发的问题。"""
    try:
        append_turn(user_id, user_message, assistant_message)
    except Exception:
        logger.exception("[ai/chat] 失败对话入库失败 user_id=%s", user_id)


@router.post("/ai/chat")
def ai_chat(body: AiChatRequest, user: dict = Depends(identity)):
    # M5: 用户级频控防 LLM 成本刷单（30 次/5 分钟，正常多轮对话不受影响）
    check_user_rate(user["userId"], "ai_chat", limit=30, window_s=300)
    message = body.as_dict().get("message")
    if not isinstance(message, str) or not message.strip():
        raise bad_request("message 不能为空")
    if not settings.AI_AGENT_URL:
        raise ai_unavailable("AI 助手未配置")
    user_message = message.strip()
    try:
        result = _forward_to_agent(user_message, exclude_user_id=user["userId"])
    except BizError as exc:
        if exc.http_status in (502, 503, 429):
            _persist_failed_turn(user["userId"], user_message, exc.message or "AI 助手暂时不可用，请稍后重试")
        raise
    # 入库：用户提问 + 助手回复（含卡片快照）
    try:
        agent_message = (result or {}).get("message") or ""
        data = (result or {}).get("data")
        cards = [c for c in data if isinstance(c, dict)] if isinstance(data, list) else None
        append_turn(user["userId"], user_message, agent_message, cards=cards)
    except Exception:
        logger.exception("[ai/chat] 聊天记录入库失败 user_id=%s", user["userId"])
    return success(result, result.get("message") or "ok")


# ── 需求-成果匹配（同步，复用 ai-agent 的成果检索）─────────
# 角色与可见性自洽规则：
# - 仅需求所有者可发起匹配（owner_user_id == 当前用户）
# - 仅 published / matched 状态的需求可匹配（与前端「我的需求」可见集合一致）
# - 命中的成果由 ai-agent 侧 status='published' 过滤，即前端成果列表可见集合
# - 匹配即「把我的需求当成一次成果检索」，复用 /ai/chat 的 LLM 关键词抽取 + 检索，
#   不引入新的 worker / 任务队列，逻辑与自由问答同源。
_DEMAND_MATCHABLE_STATUSES = ("published", "matched")

# 中文停用词（需求标题里常见但无技术语义的词，不作为匹配理由）
_DEMAND_STOPWORDS = {
    "的", "了", "和", "与", "及", "或", "在", "为", "对", "由", "基于", "一种", "一个",
    "系统", "方法", "装置", "设备", "技术", "研究", "应用", "开发", "寻求", "需要",
    "需求", "希望", "想要", "请问", "帮我", "找", "有关", "相关", "方面",
}


def _extract_demand_keywords(title: str, description: str) -> list[str]:
    """从需求标题/描述里抽取技术关键词，用于生成「匹配理由」。

    简单分词：按非字母数字汉字切分，保留长度 >= 2 的片段，去停用词、去重、限 6 个。
    不依赖 LLM，确定且可解释，与「只匹配前端可见数据」的确定性语义一致。
    """
    import re

    text = (title or "") + " " + (description or "")
    # 连续的中文/字母数字串各算一个候选
    tokens = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fa5]{2,}", text)
    seen: list[str] = []
    for tok in tokens:
        tok = tok.strip()
        if not tok or tok in _DEMAND_STOPWORDS:
            continue
        if tok.lower() in ("the", "and", "for"):
            continue
        if tok not in seen:
            seen.append(tok)
        if len(seen) >= 6:
            break
    return seen


def _build_match_reasons(card: dict, keywords: list[str]) -> list[str]:
    """根据命中字段生成可读的匹配理由 chips，最多 4 条。"""
    reasons: list[str] = []
    title = str(card.get("title") or "")
    desc = str(card.get("description") or "")
    fields = card.get("application_fields")
    if not isinstance(fields, list):
        fields = []
    fields_text = " ".join(str(f) for f in fields)
    for kw in keywords:
        if not reasons.__len__() >= 4 and kw in title:
            reasons.append("标题命中：" + kw)
        elif kw in desc and "简介命中：" + kw not in reasons:
            reasons.append("简介命中：" + kw)
        elif kw in fields_text and "应用领域：" + kw not in reasons:
            reasons.append("应用领域：" + kw)
        if len(reasons) >= 4:
            break
    return reasons


@router.post("/ai/match")
def ai_match(body: AiMatchRequest, user: dict = Depends(identity)):
    # M5: 用户级频控（10 次/5 分钟）；匹配比对话更贵（全量检索 + 重排）
    check_user_rate(user["userId"], "ai_match", limit=10, window_s=300)
    demand_id = body.as_dict().get("demandId")
    if not isinstance(demand_id, int) or demand_id <= 0:
        raise bad_request("demandId 必须为正整数")
    if not settings.AI_AGENT_URL:
        raise ai_unavailable("AI 助手未配置")

    from db import get_cursor
    from core.errors import BizError, TT_DMD_40401, TT_DMD_40301

    with get_cursor() as cur:
        cur.execute(
            "SELECT id, title, description, owner_user_id, status "
            "FROM demand WHERE id = %s AND deleted_at IS NULL",
            (demand_id,),
        )
        demand = cur.fetchone()

    if not demand:
        code, message, status = TT_DMD_40401
        raise BizError(code, "需求不存在", status)
    if demand["owner_user_id"] != user["userId"]:
        code, message, status = TT_DMD_40301
        raise BizError(code, "非需求所有者，无法匹配", status)
    if demand["status"] not in _DEMAND_MATCHABLE_STATUSES:
        raise bad_request("该需求当前状态不支持匹配，仅已发布/已匹配需求可发起")

    title = (demand.get("title") or "").strip()
    description = (demand.get("description") or "").strip()
    if description and len(description) > 200:
        description = description[:200] + "…"
    # 把需求当成一次「找成果」的自然语言检索，交给 ai-agent 抽取关键词并检索
    message = f"帮我找能解决以下技术需求的科技成果：「{title}」。{description}".strip()
    if not title and not description:
        raise bad_request("需求内容为空，无法匹配")

    result = _forward_to_agent(message, exclude_user_id=user["userId"])
    cards = []
    if isinstance(result, dict):
        data = result.get("data")
        # 仅取成果卡（ai-agent 偶发把需求文本误判为 search_demand / out_of_scope 时，
        # 不把需求卡混入「成果推荐」结果，保持语义自洽）
        if isinstance(data, list):
            cards = [c for c in data if isinstance(c, dict) and c.get("card_type") == "achievement"]

    # 生成「匹配理由」：用需求关键词在成果各字段上的命中情况，确定且可解释
    keywords = _extract_demand_keywords(title, description)
    for card in cards:
        card["matchReason"] = _build_match_reasons(card, keywords)

    # 入库：用户发起匹配（以需求标题记录）+ 助手成果推荐（卡片快照）
    try:
        agent_message = (result or {}).get("message") or ""
        append_turn(
            user["userId"],
            f"匹配需求：{title}" if title else "匹配需求",
            agent_message,
            cards=cards if cards else None,
        )
    except Exception as exc:
        logger.exception("[ai/match] 聊天记录入库失败 user_id=%s", user["userId"])

    return success(
        {
            "demandId": demand["id"],
            "demandTitle": title,
            "intent": (result or {}).get("intent"),
            "agentMessage": (result or {}).get("message") or "",
            "cards": cards,
        },
        ("找到 " + str(len(cards)) + " 条相关科技成果。") if cards else "暂未找到匹配的科技成果。",
    )


# ── 聊天记录持久化（切页/重登后历史不丢）──────────────────────
@router.get("/ai/chat/messages")
def ai_chat_messages_list(user: dict = Depends(identity)):
    messages = list_messages(user["userId"])
    return success({"messages": messages}, "ok")


@router.delete("/ai/chat/messages")
def ai_chat_messages_clear(user: dict = Depends(identity)):
    deleted = clear_messages(user["userId"])
    return success({"deleted": deleted}, "聊天记录已清空")
