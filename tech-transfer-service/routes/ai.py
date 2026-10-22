"""
AI 路由 —— POST /ai/chat、POST /ai/match（同步，转发 nanshan-ai-agent），
POST /ai/evaluation-tasks、GET /ai/evaluation-tasks/{taskId}（异步任务）。

需求匹配与自然语言对话同步经本服务转发到独立的 ai-agent；成果评估沿用
异步任务制（202 + 轮询），执行由独立 worker 认领，不把企业微信长连接嵌进本进程。
"""
import json
import logging
import threading
import time
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from config import settings
from core.errors import (
    TT_COMMON_42901,
    BizError,
    ai_provider_failed,
    ai_unavailable,
    bad_request,
    conflict,
)
from core.idempotency import cache_response as cache_idem_response
from core.idempotency import idempotent_create
from core.middleware import identity
from core.rate_limit import check_user_rate
from core.pagination import parse_page_args
from core.request_schemas import AiCardViewCountsRequest, AiChatRequest, AiMatchRequest, EvaluationTaskRequest
from core.response import get_request_id, success
from modules.ai.chat_store import (
    append_turn, capture_generation, clear_messages, complete_turn, fail_turn, get_turn as get_chat_turn,
    list_history, start_turn,
)
from modules.ai.chat_runs import submit_run, clear_runs, has_durable_history
from modules.ai import eval_stream
from modules.ai.service import (
    create_evaluation_task,
    get_card_view_counts,
    get_evaluation_task,
    list_evaluations,
)

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


@router.post("/ai/cards/view-counts")
def card_view_counts(body: AiCardViewCountsRequest, user: dict = Depends(identity)):
    return success({"list": get_card_view_counts([card.model_dump() for card in body.cards])})


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


# ── 成果评估 SSE 流式（打字机效果）────────────────────────────
# 事件流（text/event-stream，每条 data: 帧为一个 JSON 对象）：
#   {"type":"snapshot","text":"<已生成全文>"}                  订阅回放（迟到连接补齐历史）
#   {"type":"content_delta","text":"<增量>"}                   LLM 实时增量（报告原文）
#   {"type":"stage","text":"正在生成评价报告"}                  阶段文案（ai_task.progress_stage）
#   {"type":"done","status":"succeeded","result":{...}}        终态（result 同 GET 任务视图）
#   {"type":"timeout"}                                        服务端流到时（前端转轮询兜底）
#   {"type":"error","message":"..."}                          流内异常（前端转轮询兜底）
# 前端无 SSE 能力（小程序）或流中断时降级 GET 轮询，轮询契约不变。

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # 反代（Nginx/Caddy）默认缓冲响应体：显式关闭，保证逐 token 到达
    "X-Accel-Buffering": "no",
}
# 单条 SSE 流最长持续时间（秒）：与前端轮询上限（120s）同量级。
_SSE_MAX_SECONDS = 150.0
# DB 状态巡检间隔（秒）：外部 worker 执行时进程内总线无事件，靠巡检收敛终态。
_SSE_POLL_SECONDS = 1.0
# 心跳注释间隔（秒）：防反代/移动网络空闲断连；客户端忽略 ":" 开头的行。
_SSE_HEARTBEAT_SECONDS = 10.0
_SSE_TERMINAL_STATUSES = ("succeeded", "failed", "stale")


def _sse_frame(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


@router.get("/ai/evaluation-tasks/{task_id}/stream")
def evaluation_task_stream(task_id: int, user: dict = Depends(identity)):
    """评估报告 SSE 流式通道（ChatGPT 式打字机实时渲染）。

    queued/running：持续推送 content_delta（LLM 生成中的报告原文）与 stage，
    终态推 done（result 为 GET /ai/evaluation-tasks/{id} 同款任务视图，含
    结构化评分/报告）后关闭。已终态任务单帧 done 直接返回。
    数据权限同 GET：仅任务创建者可见。
    """
    # 预检：归属校验 + stale 清理 + queued 补偿提交（复用 GET 的全部容灾语义）
    view = get_evaluation_task(user["userId"], task_id)
    if view["status"] in _SSE_TERMINAL_STATUSES:
        return StreamingResponse(
            iter([_sse_frame({"type": "done", "status": view["status"], "result": view})]),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )
    return StreamingResponse(
        _evaluation_event_stream(user["userId"], task_id),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


def _evaluation_event_stream(user_id: int, task_id: int):
    """SSE 事件生成器（同步生成器，由 StreamingResponse 放入线程池执行）。

    双通道收敛：
    - 进程内流式总线（eval_stream）：LLM 增量 content_delta + 终态信号（实时）；
    - DB 巡检（get_evaluation_task）：progress_stage 阶段文案 + 外部 worker
      执行时的终态兜底（独立 worker 进程不共享内存总线）。
    任一通道看到终态即推 done（查库组装结构化结果）收尾。
    """
    sub = eval_stream.subscribe(task_id)
    deadline = time.monotonic() + _SSE_MAX_SECONDS
    last_stage = None
    last_poll = 0.0
    last_beat = 0.0
    terminal = False
    try:
        yield _sse_frame({"type": "snapshot", "text": sub.text})
        while time.monotonic() < deadline:
            event = sub.get(timeout=0.5)
            now = time.monotonic()
            if event is not None:
                if event.get("type") == "terminal":
                    terminal = True
                    break
                yield _sse_frame(event)
            if now - last_poll >= _SSE_POLL_SECONDS:
                last_poll = now
                try:
                    view = get_evaluation_task(user_id, task_id)
                except BizError as exc:
                    yield _sse_frame({"type": "error", "message": exc.message})
                    return
                stage = view.get("progressStage")
                if stage and stage != last_stage:
                    last_stage = stage
                    yield _sse_frame({"type": "stage", "text": stage})
                if view["status"] in _SSE_TERMINAL_STATUSES:
                    yield _sse_frame({"type": "done", "status": view["status"], "result": view})
                    return
            if now - last_beat >= _SSE_HEARTBEAT_SECONDS:
                last_beat = now
                yield ": ping\n\n"
        if terminal:
            # 总线终态信号：结果体查库组装（worker 先落库后广播，此处必能读到）
            try:
                view = get_evaluation_task(user_id, task_id)
            except BizError as exc:
                yield _sse_frame({"type": "error", "message": exc.message})
                return
            yield _sse_frame({"type": "done", "status": view["status"], "result": view})
        else:
            # 流到时仍未终态：前端转 GET 轮询兜底
            yield _sse_frame({"type": "timeout"})
    finally:
        sub.close()


@router.get("/ai/evaluations")
def evaluation_history(request: Request, user: dict = Depends(identity)):
    """评价历史记录：当前用户发起过的全部成果评价（分页倒序）。

    query: page/pageSize（约定同 core.pagination）、achievementId 可选过滤。
    """
    page, page_size, _ = parse_page_args(request)
    raw_ach = request.query_params.get("achievementId")
    achievement_id = None
    if raw_ach not in (None, ""):
        try:
            achievement_id = int(raw_ach)
        except (ValueError, TypeError):
            achievement_id = 0
        if achievement_id <= 0:
            from core.errors import bad_request
            raise bad_request("achievementId 必须为正整数")
    return success(list_evaluations(user["userId"], page, page_size, achievement_id))


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


def _wait_for_agent_retry(attempt: int, deadline: float) -> bool:
    delay = _AGENT_RETRY_BACKOFF[min(attempt, len(_AGENT_RETRY_BACKOFF) - 1)]
    if deadline - time.monotonic() <= delay + 0.1:
        return False
    time.sleep(delay)
    return True


def _forward_to_agent(message: str, exclude_user_id: int | None = None) -> dict:
    budget = max(0.1, min(float(settings.AI_AGENT_TIMEOUT), settings.MAX_REQUEST_SECONDS - 1.0))
    deadline = time.monotonic() + budget
    payload_dict = {"message": message}
    # 透传当前用户 id，agent 检索时排除该用户自己的成果/需求，避免自我推荐。
    if exclude_user_id is not None:
        payload_dict["exclude_owner_user_id"] = exclude_user_id
    payload = json.dumps(payload_dict).encode("utf-8")
    # 服务间身份：主服务 → ai-agent 必须携带共享密钥。
    # ai-agent 侧 /api/ai/chat 在配置了密钥时强制校验；
    # 未配置密钥时仅接受本机回环来源（主服务与 agent 同机部署即满足）。
    agent_headers = {"Content-Type": "application/json", "X-Request-Id": get_request_id() or ""}
    service_key = settings.AI_PUBLIC_API_KEY or settings.AI_INTERNAL_SERVICE_KEY
    if service_key:
        agent_headers["X-AI-Service-Key"] = service_key
    req = urllib.request.Request(
        settings.AI_AGENT_URL,
        data=payload,
        headers=agent_headers,
        method="POST",
    )
    last_exc: Exception | None = None
    last_http: tuple[int, str] | None = None
    for attempt in range(_AGENT_RETRY_TIMES):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _raise_from_agent_network(TimeoutError("AI request budget exhausted"))
        try:
            # D6: 信号量 acquire 加超时，防止无限阻塞导致线程饥饿
            if not _AI_CONCURRENCY.acquire(timeout=min(3.0, remaining)):
                raise urllib.error.URLError("AI 并发繁忙，请稍后重试")
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("AI request budget exhausted")
                req.add_header("X-AI-Timeout-Seconds", str(max(0.001, remaining - 0.1)))
                with urllib.request.urlopen(req, timeout=remaining) as resp:
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
            if retryable and attempt < _AGENT_RETRY_TIMES - 1 and _wait_for_agent_retry(attempt, deadline):
                continue
            _raise_from_agent_http(exc.code, body)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last_exc = exc
            logger.warning("[ai/chat] agent 调用失败 attempt=%s err=%r", attempt + 1, exc)
            retryable = isinstance(exc, (TimeoutError, OSError)) or (
                isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError)
            )
            if retryable and attempt < _AGENT_RETRY_TIMES - 1 and _wait_for_agent_retry(attempt, deadline):
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


def _persist_failed_turn(user_id: int, user_message: str, assistant_message: str, **generation_options) -> None:
    """失败时也保留问答痕迹，避免刷新后用户看不到自己刚发的问题。"""
    try:
        append_turn(user_id, user_message, assistant_message, **generation_options)
    except Exception:
        logger.exception("[ai/chat] 失败对话入库失败 user_id=%s", user_id)


@router.post("/ai/chat")
def ai_chat(body: AiChatRequest, user: dict = Depends(identity), request: Request = None):
    message = body.as_dict().get("message")
    if not isinstance(message, str) or not message.strip():
        raise bad_request("message 不能为空")
    user_message = message.strip()
    turn_id = body.as_dict().get("turnId")
    if settings.AI_CHAT_RUNS_ENABLED and turn_id and request is not None and "respond-async" in request.headers.get("Prefer", "").lower():
        turn = submit_run(user["userId"], turn_id, user_message, body.reference.model_dump() if body.reference else None)
        return JSONResponse(status_code=202 if turn["status"] == "running" else 200, content=success(turn, "任务已受理"))
    check_user_rate(user["userId"], "ai_chat", limit=30, window_s=300)
    generation = None
    if turn_id:
        reference_options = {"reference": body.reference.model_dump()} if body.reference else {}
        turn, is_new = start_turn(user["userId"], turn_id, user_message, **reference_options)
        generation = turn.get("generation")
        if not is_new:
            if turn["status"] == "succeeded":
                return success(
                    {"success": True, "message": turn.get("reply") or "", "data": turn.get("cards") or []},
                    turn.get("reply") or "ok",
                )
            if turn["status"] == "failed":
                raise BizError(
                    turn.get("errorCode") or "TT_AI_50301",
                    turn.get("errorMessage") or "AI 助手暂时不可用，请稍后重试",
                    turn.get("errorStatus") or 503,
                )
            return JSONResponse(
                status_code=202,
                content=success({"turnId": turn_id, "status": "running"}, "AI 回答仍在生成中"),
            )
    else:
        generation = capture_generation(user["userId"])
    generation_options = {"expected_generation": generation} if generation is not None else {}
    if not settings.AI_AGENT_URL:
        exc = ai_unavailable("AI 助手未配置")
        if turn_id:
            fail_turn(user["userId"], turn_id, user_message, exc.message, exc.code, exc.http_status, **generation_options)
        raise exc
    try:
        result = _forward_to_agent(user_message, exclude_user_id=user["userId"])
    except BizError as exc:
        if turn_id:
            fail_turn(user["userId"], turn_id, user_message, exc.message, exc.code, exc.http_status, **generation_options)
        elif exc.http_status in (502, 503, 429):
            _persist_failed_turn(user["userId"], user_message, exc.message or "AI 助手暂时不可用，请稍后重试", **generation_options)
        raise
    except Exception:
        if turn_id:
            fail_turn(
                user["userId"], turn_id, user_message,
                "AI 助手暂时不可用，请稍后重试", "TT_COMMON_50001", 500,
                **generation_options,
            )
        raise
    # 入库：用户提问 + 助手回复（含卡片快照）
    agent_message = (result or {}).get("message") or ""
    data = (result or {}).get("data")
    cards = [c for c in data if isinstance(c, dict)] if isinstance(data, list) else None
    if turn_id:
        completed_turn = complete_turn(
            user["userId"], turn_id, user_message, agent_message, cards=cards, **generation_options
        )
        if completed_turn is None:
            raise conflict(
                "聊天记录已清空，本次回答未保存",
                {"reason": "chat_history_cleared", "turnId": turn_id},
            )
        if completed_turn.get("status") != "succeeded":
            raise conflict(
                "本次回答状态已变化，请刷新聊天记录",
                {"reason": "turn_state_changed", "turnId": turn_id},
            )
    else:
        try:
            append_turn(user["userId"], user_message, agent_message, cards=cards, **generation_options)
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

    from core.errors import TT_DMD_40301, TT_DMD_40401, BizError
    from db import get_cursor

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

    generation = capture_generation(user["userId"])
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
            expected_generation=generation,
        )
    except Exception:
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
    history = list_history(user["userId"])
    return success({**history, "referenceSupported": settings.AI_CHAT_RUNS_ENABLED}, "ok")


@router.get("/ai/chat/turns/{turn_id}")
def ai_chat_turn_detail(turn_id: str, user: dict = Depends(identity)):
    turn = get_chat_turn(user["userId"], turn_id)
    if turn is None:
        from core.errors import TT_AI_40401
        code, message, status = TT_AI_40401
        raise BizError(code, "AI 问答轮次不存在", status)
    return success(turn, "ok")


@router.delete("/ai/chat/messages")
def ai_chat_messages_clear(user: dict = Depends(identity)):
    if settings.AI_CHAT_RUNS_ENABLED or has_durable_history(user["userId"]):
        return success(clear_runs(user["userId"]), "聊天记录已清空")
    deleted = clear_messages(user["userId"])
    return success({"deleted": deleted}, "聊天记录已清空")
