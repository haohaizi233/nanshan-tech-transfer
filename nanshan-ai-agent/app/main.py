import asyncio
import logging
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings

# L5: 启动自检 — 必填配置缺失时终止进程，避免启动假成功
settings.validate()

# L7: 统一 logger，替代 print()
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("nanshan.ai-agent")
from app.database import get_db
from app.llm_client import LLMError, set_fallback_provider
from app.router import apply_condition_guards, classify_intent
from app.schemas import ChatRequest, ChatResponse, InternalChatRequest, RouteResult
from app.conversation import merge_route, record_matches, resolve_context

from app.services.achievement_service import (
    search_achievements,
)

from app.services.demand_service import (
    search_demands,
)

from app.services.amount_parser import find_amount_bounds
from app.services.diagnostics import facts_for
from app.services import evaluation_service

from app.formatters import (
    format_achievement_card,
    format_demand_card,
    number_text,
)

from app.reranker import rerank_results
from app.advisor import enrich_cards, local_reply, result_message
from app.runtime_budget import reset_deadline, set_deadline
from app.runtime_trace import emit_stage, request_trace, stage_observer, trace_count, trace_degradation, trace_stage
from app.internal_stream import authorize_internal, prepare_stream
from app.auth import authorize_service_call


app = FastAPI(
    title="南山科转通 AI Agent",
    version="0.3.0",
)

# 注册备用 LLM Provider（主 Provider 不可用时自动切换）
if settings.LLM_FALLBACK_URL and settings.LLM_FALLBACK_KEY:
    set_fallback_provider(
        settings.LLM_FALLBACK_URL,
        settings.LLM_FALLBACK_KEY,
        settings.LLM_FALLBACK_MODEL or "gpt-4o-mini",
    )

_chat_slots = BoundedSemaphore(settings.AI_CHAT_MAX_CONCURRENCY)
_chat_executor = ThreadPoolExecutor(
    max_workers=settings.AI_CHAT_MAX_CONCURRENCY,
    thread_name_prefix="ai-chat",
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "nanshan-ai-agent",
        "version": "0.3.0",
    }


@app.get("/health/db")
def db_health():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                result = cur.fetchone()

        return {
            "status": "ok",
            "database": "tech_transfer",
            "result": result,
        }

    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "database": "tech_transfer",
                "error": "database_unavailable",
            },
        )


def chat_timeout_seconds(value: str | None) -> float:
    try:
        requested = float(value)
    except (ValueError, TypeError):
        return settings.AI_CHAT_TIMEOUT_SECONDS
    if math.isfinite(requested) and 0 < requested < settings.AI_CHAT_TIMEOUT_SECONDS:
        return requested
    return settings.AI_CHAT_TIMEOUT_SECONDS


@app.post("/api/ai/chat", response_model=ChatResponse)
async def ai_chat(body: ChatRequest, http_request: Request):
    # 服务间鉴权：后端 → Agent 必须携带共享密钥；
    # 未配置密钥时仅接受本机回环调用，避免 Agent 被当成公开模型代理。
    authorize_service_call(
        http_request.headers.get("X-AI-Service-Key"),
        getattr(http_request.client, "host", None),
    )
    if not _chat_slots.acquire(blocking=False):
        raise HTTPException(
            status_code=503,
            detail={"message": "AI 请求繁忙，请稍后重试。", "reason": "overloaded"},
        )
    try:
        loop = asyncio.get_running_loop()
        timeout_seconds = chat_timeout_seconds(http_request.headers.get("X-AI-Timeout-Seconds"))
        deadline_at = time.monotonic() + timeout_seconds
        worker = _chat_executor.submit(_run_ai_chat, body, http_request.headers.get("X-Request-Id"), deadline_at)
    except BaseException:
        _chat_slots.release()
        raise
    worker.add_done_callback(lambda completed: _chat_slots.release())
    future = asyncio.wrap_future(worker, loop=loop)
    future.add_done_callback(lambda completed: None if completed.cancelled() else completed.exception())
    try:
        deadline = loop.time() + timeout_seconds
        while not future.done():
            remaining = deadline - loop.time()
            if remaining <= 0:
                future.cancel()
                raise HTTPException(
                    status_code=504,
                    detail={"message": "AI 响应超时，请缩短问题后重试。", "reason": "timeout"},
                )
            if await http_request.is_disconnected():
                # 客户端断开 ≠ 取消生成：后台继续跑完并存储结果
                # 前端重新连上后可以通过 turnId 查询结果
                pass  # 不cancel，继续等待完成
            await asyncio.wait((future,), timeout=min(0.2, remaining))
        return await future
    finally:
        if not worker.running() and not worker.done():
            worker.cancel()


@app.post("/internal/ai/chat/stream")
async def internal_ai_chat(body: InternalChatRequest, http_request: Request):
    return prepare_stream(
        body, http_request, slots=_chat_slots, executor=_chat_executor, run=_run_ai_chat,
        timeout_seconds=min(55.0, chat_timeout_seconds(http_request.headers.get("X-AI-Timeout-Seconds"))),
    )


@app.get("/internal/ai/ready")
async def internal_ready(http_request: Request):
    authorize_internal(http_request.headers.get("X-AI-Service-Key"))
    return {
        "schemaVersion": 1,
        "capacity": settings.AI_CHAT_MAX_CONCURRENCY,
        "executionBudgetSeconds": min(55.0, settings.AI_CHAT_TIMEOUT_SECONDS),
        "modelConfigured": bool(settings.LLM_API_URL and settings.LLM_API_KEY and settings.LLM_MODEL),
    }


def _run_ai_chat(body: ChatRequest, request_id: str | None = None, deadline_at: float | None = None, observer=None):
    remaining = max(0.0, deadline_at - time.monotonic()) if deadline_at is not None else settings.AI_CHAT_TIMEOUT_SECONDS
    deadline_token = set_deadline(remaining)
    try:
        with request_trace(request_id), stage_observer(observer), trace_stage("request"):
            return _process_ai_chat(body)
    finally:
        reset_deadline(deadline_token)


def _search(route, request, target_ids=None):
    common = {
        "keywords": route.keywords,
        "organization": route.organization,
        "limit": min(route.limit, 10) if target_ids is not None else 20,
        "exclude_owner_user_id": request.exclude_owner_user_id,
    }
    if target_ids is not None:
        common["target_ids"] = target_ids
    if route.intent == "search_achievement":
        if route.region:
            common["region"] = route.region
        return search_achievements(
            **common, min_price_wan=route.min_price_wan,
            max_price_wan=route.max_price_wan, min_maturity=route.min_maturity,
        )
    return search_demands(
        **common, region=route.region, min_budget_wan=route.min_budget_wan,
        max_budget_wan=route.max_budget_wan, coop_modes=route.coop_modes,
    )


def get_visible_records(card_type, ids, exclude_owner_user_id=None):
    route = RouteResult(intent="search_" + card_type, limit=10)
    request = ChatRequest(message="visibility", exclude_owner_user_id=exclude_owner_user_id)
    return _search(route, request, ids)


def _visible(item, owner):
    return (
        item.get("status", "published") == "published"
        and item.get("deleted_at") is None
        and (owner is None or item.get("owner_user_id") != owner)
    )


def _final_records(results, request, route):
    if not results:
        return []
    kind = "achievement" if route.intent == "search_achievement" else "demand"
    current = get_visible_records(kind, [item["id"] for item in results], request.exclude_owner_user_id)
    by_id = {item["id"]: item for item in current if _visible(item, request.exclude_owner_user_id)}
    records = []
    for item in results:
        latest = by_id.get(item["id"])
        if latest is None or not record_matches(latest, route):
            continue
        refreshed = dict(latest)
        for key in ("_advisor_evidence", "_advisor_insight"):
            if item.get(key) and all(item.get(field) == latest.get(field) for field in ("title", "tech_intro", "description", "application_fields", "innovation_points", "region", "coop_mode")):
                refreshed[key] = item[key]
        records.append(refreshed)
    if len(records) < len(results):
        trace_degradation("visibility_changed")
    return records[:route.limit]


def _respond(route, request, records, facts=None):
    emit_stage("formatting")
    formatter = format_achievement_card if route.intent == "search_achievement" else format_demand_card
    cards = enrich_cards([formatter(item) for item in records], records, route)
    trace_count("returned_count", len(cards))
    return ChatResponse(
        success=True, intent=route.intent, message=result_message(request.message, cards, route, facts),
        data=cards, queryPlan=route.model_dump(),
    )


def _clarification(message):
    emit_stage("formatting")
    return ChatResponse(success=True, intent="out_of_scope", message=message, data=[])


# ── evaluate_achievement：对话内发起/查询成果评估 ──────────────────
# 评估意图提到「成果」但不含比较措辞（比较仍走两卡片对比流程）。
_EVAL_MENTION = re.compile(r"评估|评价")
_EVAL_COMPARE = re.compile(r"比较|对比|选哪|哪个好|哪一个|哪个更")
# 「查看评估结果 / 报告出来了吗」→ 先查已有结果，不重复发起耗时评估。
_EVAL_VIEW_ONLY = re.compile(r"查看|看看|查一下|出来了吗|好了吗|进度|状态|评估报告|评估结果")
_EVAL_TRIGGER = re.compile(r"重新|发起|再评|评估一下|帮我评估|评估[一二三四五六七八九十\d]|评估$")


def _is_evaluation_request(text):
    return bool(_EVAL_MENTION.search(text)) and not _EVAL_COMPARE.search(text)


def _wants_existing_result(text):
    return bool(_EVAL_VIEW_ONLY.search(text)) and not _EVAL_TRIGGER.search(text)


def _evaluation_message(record, summary):
    title = record.get("title") or "该成果"
    score = number_text(summary.get("totalScore"))
    label = summary.get("ratingLabel") or ""
    conclusion = (summary.get("conclusion") or "").strip()
    parts = [f"「{title}」评估完成：综合评分 {score or '—'} 分（{label}）。"]
    if conclusion:
        parts.append(conclusion[:160])
    return "".join(parts)


# 「评估成果」这类泛指词不算具体目标：清掉这些词后没有实义 → 列出成果供选择。
_EVAL_GENERIC_TARGET_TOKENS = (
    "帮我", "麻烦", "请", "一下", "看看", "查一下", "查看", "发起", "进行",
    "评估", "评价", "分析",
    "科技成果", "技术成果", "成果", "技术方案",
    "我的", "我们", "我", "该", "这个", "这些", "哪项", "哪些", "什么",
    "一个", "一项", "所有", "全部", "哪个", "的",
)


def _is_generic_target_name(name):
    """True 表示没有给出可定位的具体成果名称（空或纯泛指词）。"""
    rest = (name or "").strip()
    while rest:
        for token in _EVAL_GENERIC_TARGET_TOKENS:
            if rest.startswith(token):
                rest = rest[len(token):].strip()
                break
        else:
            return False
    return True


def _evaluation_picker(request, user_id, route=None, query_plan=None):
    """没给出具体成果：列出用户名下成果供选择，不盲猜评估目标。"""
    try:
        records = evaluation_service.list_owned_targets(user_id)
    except Exception as exc:
        logger.error("evaluate_target_list_failed type=%s", type(exc).__name__)
        raise HTTPException(status_code=503, detail={"message": "数据库暂时繁忙，请稍后重试。", "agentReason": "database_unavailable"}) from exc
    if not records:
        return _clarification("你名下还没有可评估的科技成果。发布成果并通过审核后，再来发起 AI 评估。")
    view_only = _wants_existing_result(request.message)
    cards = []
    for item in records:
        card = format_achievement_card(item)
        card["pickAction"] = "view-evaluation" if view_only else "evaluate"
        cards.append(card)
    message = (
        "请选择要查看评估结果的成果（点卡片上的「查看评估」）："
        if view_only else
        "请选择要评估的成果（点卡片上的「评估这个」发起 AI 评估）："
    )
    emit_stage("formatting")
    return ChatResponse(
        success=True, intent="evaluate_achievement", message=message,
        data=cards,
        queryPlan=query_plan if query_plan is not None else (route.model_dump() if route else None),
    )


def _evaluation_reply(request, route=None, target_id=None, target_name=None, card_target=None, query_plan=None):
    """evaluate_achievement 意图分发：定位成果 → 服务代用户发起/查询评估 → 组卡片回复。"""
    emit_stage("retrieving")
    user_id = request.exclude_owner_user_id
    if not user_id:
        return _clarification("请先登录后再发起成果评估。")
    if card_target is not None and card_target.card_type != "achievement":
        return _clarification("仅支持对科技成果发起评估，请选择成果卡片。")
    chosen_id = card_target.id if card_target is not None else target_id
    chosen_name = None if card_target is not None else target_name
    if chosen_id is None and _is_generic_target_name(chosen_name):
        # 「评估成果」「查看评估结果」等没给具体目标：返回本人成果列表供选择。
        return _evaluation_picker(request, user_id, route, query_plan)
    try:
        record = evaluation_service.resolve_target(
            user_id,
            target_id=chosen_id,
            target_name=chosen_name,
        )
    except Exception as exc:
        logger.error("evaluate_target_lookup_failed type=%s", type(exc).__name__)
        raise HTTPException(status_code=503, detail={"message": "数据库暂时繁忙，请稍后重试。", "agentReason": "database_unavailable"}) from exc
    if record is None:
        return _clarification("没有找到可评估的成果，请确认成果名称或直接选择成果卡片。")
    if record.get("owner_user_id") != user_id:
        return _clarification("仅成果所有者可以发起评估，请确认该成果属于你。")
    try:
        outcome = evaluation_service.evaluate(
            user_id, record["id"], prefer_existing=_wants_existing_result(request.message),
        )
    except evaluation_service.EvaluationError as exc:
        logger.warning("evaluation_tool_failed code=%s status=%s", exc.code, exc.status_code)
        return _clarification(exc.user_message)
    summary = outcome.get("evaluation")
    status = outcome.get("status")
    if status == "succeeded":
        message = _evaluation_message(record, summary)
    elif status == "pending":
        stage = outcome.get("progressStage")
        message = f"评估任务进行中（{stage}），稍后查看评估结果。" if stage else "评估任务进行中，稍后查看评估结果。"
    elif status == "missing":
        message = "该成果暂无评估结果，可回复「评估」发起一次评估。"
    else:
        message = "评估未完成：" + (outcome.get("failReason") or "AI 服务暂时不可用，请稍后重试")
    card = format_achievement_card(record)
    card["evaluation"] = summary
    if type(outcome.get("taskId")) is int and outcome["taskId"] > 0:
        card["evaluationTask"] = {
            "taskId": outcome["taskId"],
            "status": status,
            "progressStage": outcome.get("progressStage"),
        }
    emit_stage("formatting")
    return ChatResponse(
        success=True, intent="evaluate_achievement", message=message,
        data=[card],
        queryPlan=query_plan if query_plan is not None else (route.model_dump() if route else None),
    )


def _process_ai_chat(request: ChatRequest):
    emit_stage("context")
    command = re.fullmatch(r"/(?:评估|评估成果|evaluate|ai评估)(?:\s+(.*))?", request.message.strip(), re.IGNORECASE)
    if command:
        argument = (command.group(1) or "").strip()
        identifier = re.fullmatch(r"(?:成果\s*|#)?([1-9]\d*)", argument)
        if len(argument) > 80:
            return _clarification("成果名称不能超过80字，请缩短名称或使用成果编号。")
        route = RouteResult(
            intent="evaluate_achievement",
            target_id=int(identifier.group(1)) if identifier else None,
            target_name=argument if argument and not identifier else None,
        )
        emit_stage("routing")
        return _evaluation_reply(request, route=route, target_id=route.target_id, target_name=route.target_name)
    reply = local_reply(request.message, resolve_references=False)
    if reply is not None:
        return _clarification(reply)
    resolution = resolve_context(request)
    if resolution.clarification:
        return _clarification(resolution.clarification)
    if resolution.targets:
        if _is_evaluation_request(request.message):
            # 「评估刚才那个成果」：指代解析先于意图分类拿到卡片目标，
            # 评估走 owner 通道，不受搜索可见性过滤（自己的成果自己看不到）。
            if len(resolution.targets) != 1:
                return _clarification("一次只能评估一项成果，请选择一张成果卡片。")
            return _evaluation_reply(
                request,
                card_target=resolution.targets[0],
                query_plan=request.context.queryPlan if request.context and request.context.queryPlan else None,
            )
        emit_stage("retrieving")
        records = []
        for target in resolution.targets:
            current = get_visible_records(target.card_type, [target.id], request.exclude_owner_user_id)
            matches = [item for item in current if item.get("id") == target.id and _visible(item, request.exclude_owner_user_id)]
            if not matches:
                return _clarification("所选成果或需求已不可用，请重新选择当前可见的卡片。")
            records.append(matches[0])
        kinds = {target.card_type for target in resolution.targets}
        if len(kinds) != 1:
            return _clarification("请选取相同类型的两项成果或需求进行比较。")
        route = RouteResult(
            intent="search_" + resolution.targets[0].card_type,
            keywords=[], limit=len(records),
        )
        records = _final_records(records, request, route)
        if len(records) != len(resolution.targets):
            return _clarification("所选成果或需求已不可用，请重新选择当前可见的卡片。")
        response = _respond(route, request, records)
        if request.context and request.context.queryPlan:
            response.queryPlan = request.context.queryPlan
        return response
    emit_stage("routing")
    try:
        if resolution.route is not None:
            route = resolution.route
        else:
            route = classify_intent(request.message)
    except ValueError:
        return _clarification("请确认筛选条件，预算、价格范围或成熟度存在冲突，不能直接取消条件检索。")
    except LLMError as exc:
        logger.warning("router_failed llm_status=%s reason=%s", exc.status_code, exc.reason)
        trace_degradation("llm_degraded")
        raise HTTPException(status_code=502, detail={"message": "AI服务暂时不可用，请稍后重试。", "layer": "llm", "llmReason": exc.reason}) from exc
    except Exception as exc:
        logger.warning("router_failed type=%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail={"message": "AI业务意图识别失败，请稍后重试。", "agentReason": "router_error"}) from exc
    if route.intent == "evaluate_achievement":
        # 评估意图不走搜索管线：merge_route/条件闸门只服务检索条件，
        # 且会把「评估成果3」的编号误解析成金额条件，必须在它们之前分发。
        return _evaluation_reply(
            request, route=route, target_id=route.target_id, target_name=route.target_name,
        )
    try:
        if resolution.route is None:
            route = merge_route(request.message, route)
        # 硬性条件 / 软偏好分离闸门：merge_route 会按原话重新解析条件，
        # 必须在它之后再跑一次闸门，否则软偏好会被还原成硬过滤。
            route = apply_condition_guards(route, request.message)
    except ValueError:
        return _clarification("请确认筛选条件，预算、价格范围或成熟度存在冲突，不能直接取消条件检索。")
    except Exception as exc:
        logger.warning("route_guard_failed type=%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail={"message": "AI业务意图识别失败，请稍后重试。", "agentReason": "router_error"}) from exc
    if route.intent == "out_of_scope":
        return _clarification("我可以帮你查找、介绍科技成果和技术需求，说明依据并指导平台操作。请告诉我技术方向、成果名称或想完成的操作。")
    if not route.keywords:
        return _clarification("请告诉我你想查询的技术方向，例如人工智能、机器视觉、生物医药等。")
    if route.intent == "search_achievement" and route.region:
        return _clarification("成果资料未披露可核实的地域字段，请确认是否保留地域要求或改查技术需求。")
    emit_stage("retrieving")
    try:
        candidates = _search(route, request)
        candidates = [item for item in candidates[:20] if _visible(item, request.exclude_owner_user_id) and record_matches(item, route)]
        trace_count("candidate_count", len(candidates))
        soft_cap = None
        if "prefer_low_price" in route.preferences:
            soft_cap = find_amount_bounds(request.message).get("max_wan")
        results = rerank_results(
            intent=route.intent,
            user_message=request.message,
            candidates=candidates,
            top_n=route.limit,
            preferences=route.preferences,
            soft_cap_wan=soft_cap,
        )
        candidates_by_id = {item["id"]: item for item in candidates}
        selected = []
        selected_ids = set()
        for item in results:
            identifier = item.get("id")
            if identifier not in candidates_by_id or identifier in selected_ids:
                continue
            original = dict(candidates_by_id[identifier])
            for key in ("_advisor_evidence", "_advisor_insight"):
                if key in item:
                    original[key] = item[key]
            selected.append(original)
            selected_ids.add(identifier)
        trace_count("selected_count", len(selected))
        selected = _final_records(selected, request, route)
    except Exception as exc:
        logger.error("retrieval_failed type=%s", type(exc).__name__)
        trace_degradation("retrieval_degraded")
        raise HTTPException(status_code=503, detail={"message": "数据库暂时繁忙，请稍后重试。", "agentReason": "database_unavailable"}) from exc
    facts = None
    if not selected and settings.AI_EMPTY_DIAGNOSTICS:
        # 零结果时补一次轻量聚合查询，把库里的客观事实带进说明里，
        # 避免把"库里没有"说成"你条件不合适"。
        facts = facts_for(route.intent)
        trace_degradation("empty_diagnostics")
    return _respond(route, request, selected, facts)
