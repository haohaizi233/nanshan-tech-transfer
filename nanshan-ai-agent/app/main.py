import asyncio
import logging
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
from app.runtime_budget import reset_deadline, set_deadline


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


@app.post("/api/ai/chat", response_model=ChatResponse)
async def ai_chat(body: ChatRequest, http_request: Request):
    if not _chat_slots.acquire(blocking=False):
        raise HTTPException(
            status_code=503,
            detail={"message": "AI 请求繁忙，请稍后重试。", "reason": "overloaded"},
        )
    # H4: 槽位由本协程的 finally 统一释放（恰好一次）。
    # 不能依赖工作线程的 finally —— future.cancel() 在任务未启动时会直接取消任务，
    # 线程体（含 finally）根本不执行，槽位会永久泄漏直到 BoundedSemaphore 溢出。
    try:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(_chat_executor, _run_ai_chat, body)
        deadline = loop.time() + settings.AI_CHAT_TIMEOUT_SECONDS
        while not future.done():
            remaining = deadline - loop.time()
            if remaining <= 0:
                # 线程池任务无法被真正中断：cancel() 只对尚未出队的任务生效，
                # 已在跑的线程会继续到自然结束（线程池 max_workers 已兜底真实并发）。
                # 无论 cancel 成败，槽位都在外层 finally 释放，不再泄漏。
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
        _chat_slots.release()


def _run_ai_chat(body: ChatRequest):
    deadline_token = set_deadline(settings.AI_CHAT_TIMEOUT_SECONDS)
    try:
        return _process_ai_chat(body)
    finally:
        reset_deadline(deadline_token)


def _process_ai_chat(request: ChatRequest):

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
                "当前仅支持南山科转通相关的"
                "科技成果查询和技术需求查询。"
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
                message="暂未找到匹配的科技成果。",
                data=[],
            )

        cards = [
            format_achievement_card(item)
            for item in results
        ]

        return ChatResponse(
            success=True,
            intent="search_achievement",
            message=f"找到 {len(cards)} 条相关科技成果。",
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
                message="暂未找到匹配的技术需求。",
                data=[],
            )

        cards = [
            format_demand_card(item)
            for item in results
        ]

        return ChatResponse(
            success=True,
            intent="search_demand",
            message=f"找到 {len(cards)} 条相关技术需求。",
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
