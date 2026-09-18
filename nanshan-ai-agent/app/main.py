from fastapi import FastAPI, HTTPException

from app.database import get_db
from app.llm_client import LLMError
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


app = FastAPI(
    title="南山科转通 AI Agent",
    version="0.3.0",
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

    except Exception as exc:
        return {
            "status": "error",
            "database": "tech_transfer",
            "error": str(exc),
        }


@app.post(
    "/api/ai/chat",
    response_model=ChatResponse,
)
def ai_chat(
    request: ChatRequest,
):

    try:
        route = classify_intent(
            request.message
        )

    except LLMError as exc:
        print(
            "[LLM Error]",
            repr(exc),
        )

        raise HTTPException(
            status_code=502,
            detail="AI服务暂时不可用，请稍后重试。",
        )

    except Exception as exc:
        print(
            "[Router Error]",
            repr(exc),
        )

        raise HTTPException(
            status_code=500,
            detail="AI业务意图识别失败，请稍后重试。",
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

            results = rerank_results(
                intent="search_achievement",
                user_message=request.message,
                candidates=candidates,
                top_n=route.limit,
            )

        except Exception as exc:
            print(
                "[Achievement DB Error]",
                repr(exc),
            )

            raise HTTPException(
                status_code=500,
                detail="科技成果查询失败。",
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

            results = rerank_results(
                intent="search_demand",
                user_message=request.message,
                candidates=candidates,
                top_n=route.limit,
            )

        except Exception as exc:
            print(
                "[Demand DB Error]",
                repr(exc),
            )

            raise HTTPException(
                status_code=500,
                detail="技术需求查询失败。",
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
        detail="未知业务类型。",
    )
