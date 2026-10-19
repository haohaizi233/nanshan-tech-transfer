import asyncio
import logging
import math
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
from app.router import classify_intent
from app.schemas import ChatRequest, ChatResponse

from app.services.achievement_service import (
    search_achievements,
)

from app.services.demand_service import (
    search_demands,
)

from app.formatters import (
    format_achievement_card,
    format_demand_card,
)

from app.reranker import rerank_results
from app.advisor import enrich_cards, local_reply, result_message
from app.runtime_budget import reset_deadline, set_deadline
from app.runtime_trace import request_trace, trace_stage


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


def _run_ai_chat(body: ChatRequest, request_id: str | None = None, deadline_at: float | None = None):
    remaining = max(0.0, deadline_at - time.monotonic()) if deadline_at is not None else settings.AI_CHAT_TIMEOUT_SECONDS
    deadline_token = set_deadline(remaining)
    try:
        with request_trace(request_id), trace_stage("request"):
            return _process_ai_chat(body)
    finally:
        reset_deadline(deadline_token)


def _process_ai_chat(request: ChatRequest):

    reply = local_reply(request.message)
    if reply is not None:
        return ChatResponse(success=True, intent="out_of_scope", message=reply, data=[])

    try:
        route = classify_intent(
            request.message
        )

    except LLMError as exc:
        logger.warning(
            "[LLM Error] %r llmStatus=%s reason=%s",
            exc, exc.status_code, exc.reason,
        )

        raise HTTPException(
            status_code=502,
            detail={
                "message": "AI服务暂时不可用，请稍后重试。",
                "layer": "llm",
                "llmStatus": exc.status_code,
                "llmReason": exc.reason,
                "llmBody": (exc.body or "")[:300],
            },
        )

    except Exception as exc:
        logger.warning("[Router Error] %r", exc)

        raise HTTPException(
            status_code=500,
            detail={
                "message": "AI业务意图识别失败，请稍后重试。",
                "layer": "agent",
                "agentReason": "router_error",
            },
        )

    # =========================
    # 非业务问题
    # =========================

    if route.intent == "out_of_scope":

        return ChatResponse(
            success=True,
            intent="out_of_scope",
            message=(
                "我可以帮你查找、介绍科技成果和技术需求，结合场景推荐并说明依据，"
                "也可以介绍平台功能和指导发布、收藏、认证、申请对接等操作。"
                "请告诉我技术方向、成果名称或想完成的操作。"
            ),
            data=[],
        )

    # 没有关键词
    if not route.keywords:

        return ChatResponse(
            success=True,
            intent=route.intent,
            message=(
                "请告诉我你想查询的技术方向，"
                "例如人工智能、机器视觉、生物医药等。"
            ),
            data=[],
        )

    # =========================
    # 查询成果
    # =========================

    if route.intent == "search_achievement":

        try:
            candidates = search_achievements(
                keywords=route.keywords,
                organization=route.organization,
                min_price_wan=route.min_price_wan,
                max_price_wan=route.max_price_wan,
                min_maturity=route.min_maturity,
                limit=20,
                exclude_owner_user_id=request.exclude_owner_user_id,
            )
            # 种子账号挂了绝大部分成果时，排除归属会把库搜空或只剩噪音；
            # 他人成果不足 3 条则回退不过滤，避免「暂未找到」。
            if (
                request.exclude_owner_user_id is not None
                and len(candidates) < 3
            ):
                fallback = search_achievements(
                    keywords=route.keywords,
                    organization=route.organization,
                    min_price_wan=route.min_price_wan,
                    max_price_wan=route.max_price_wan,
                    min_maturity=route.min_maturity,
                    limit=20,
                    exclude_owner_user_id=None,
                )
                if len(fallback) > len(candidates):
                    logger.info(
                        "[Achievement] exclude_owner 候选不足，回退为不过滤归属 %s kept=%d",
                        request.exclude_owner_user_id, len(fallback),
                    )
                    candidates = fallback

            results = rerank_results(
                intent="search_achievement",
                user_message=request.message,
                candidates=candidates,
                top_n=route.limit,
            )

        except Exception as exc:
            logger.error("[Achievement DB Error] %r", exc)

            raise HTTPException(
                status_code=503,
                detail={
                    "message": "数据库暂时繁忙，请稍后重试。",
                    "layer": "agent",
                    "agentReason": "achievement_database_unavailable",
                },
            )

        if not results:

            return ChatResponse(
                success=True,
                intent="search_achievement",
                message=result_message(request.message, [], route),
                data=[],
            )

        cards = [
            format_achievement_card(item)
            for item in results
        ]
        cards = enrich_cards(cards, results, route)

        return ChatResponse(
            success=True,
            intent="search_achievement",
            message=result_message(request.message, cards, route),
            data=cards,
        )

    # =========================
    # 查询需求
    # =========================

    if route.intent == "search_demand":

        try:
            candidates = search_demands(
                keywords=route.keywords,
                organization=route.organization,
                region=route.region,
                min_budget_wan=route.min_budget_wan,
                max_budget_wan=route.max_budget_wan,
                coop_modes=route.coop_modes,
                limit=20,
                exclude_owner_user_id=request.exclude_owner_user_id,
            )
            if (
                request.exclude_owner_user_id is not None
                and len(candidates) < 3
            ):
                fallback = search_demands(
                    keywords=route.keywords,
                    organization=route.organization,
                    region=route.region,
                    min_budget_wan=route.min_budget_wan,
                    max_budget_wan=route.max_budget_wan,
                    coop_modes=route.coop_modes,
                    limit=20,
                    exclude_owner_user_id=None,
                )
                if len(fallback) > len(candidates):
                    logger.info(
                        "[Demand] exclude_owner 候选不足，回退为不过滤归属 %s kept=%d",
                        request.exclude_owner_user_id, len(fallback),
                    )
                    candidates = fallback

            results = rerank_results(
                intent="search_demand",
                user_message=request.message,
                candidates=candidates,
                top_n=route.limit,
            )

        except Exception as exc:
            logger.error("[Demand DB Error] %r", exc)

            raise HTTPException(
                status_code=503,
                detail={
                    "message": "数据库暂时繁忙，请稍后重试。",
                    "layer": "agent",
                    "agentReason": "demand_database_unavailable",
                },
            )

        if not results:

            return ChatResponse(
                success=True,
                intent="search_demand",
                message=result_message(request.message, [], route),
                data=[],
            )

        cards = [
            format_demand_card(item)
            for item in results
        ]
        cards = enrich_cards(cards, results, route)

        return ChatResponse(
            success=True,
            intent="search_demand",
            message=result_message(request.message, cards, route),
            data=cards,
        )

    raise HTTPException(
        status_code=500,
        detail={
            "message": "未知业务类型。",
            "layer": "agent",
            "agentReason": "unknown_intent",
        },
    )
