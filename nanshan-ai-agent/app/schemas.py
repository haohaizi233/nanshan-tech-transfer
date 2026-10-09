from typing import Any, Literal
from pydantic import BaseModel, Field


IntentType = Literal[
    "search_achievement",
    "search_demand",
    "out_of_scope",
]

MaturityType = Literal[
    "01_idea",
    "02_lab",
    "03_pilot_ready",
    "04_pilot_done",
    "05_mass_ready",
    "06_mass_done",
]


class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
    )

    # 调用方（tech-transfer-service）传入的当前用户 id；
    # agent 检索时排除该用户自己的成果/需求，避免把用户自己的内容推荐给自己。
    exclude_owner_user_id: int | None = None


class RouteResult(BaseModel):
    intent: IntentType

    keywords: list[str] = []

    # 机构
    organization: str | None = None

    # 地域，主要用于需求
    region: str | None = None

    # 成果报价
    min_price_wan: float | None = Field(
        default=None,
        ge=0,
    )
    max_price_wan: float | None = Field(
        default=None,
        ge=0,
    )

    # 需求预算
    min_budget_wan: float | None = Field(
        default=None,
        ge=0,
    )
    max_budget_wan: float | None = Field(
        default=None,
        ge=0,
    )

    # 成果最低成熟度
    min_maturity: MaturityType | None = None

    # 需求合作方式
    coop_modes: list[str] = []

    limit: int = Field(
        default=10,
        ge=1,
        le=10,
    )

    reason: str = ""


class ChatResponse(BaseModel):
    success: bool
    intent: str | None = None
    message: str
    data: Any = None