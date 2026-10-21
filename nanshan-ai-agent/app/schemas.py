import json
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


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

# 软偏好编码：只影响排序加权，永远不进入数据库硬过滤。
PreferenceType = Literal[
    "prefer_recent",
    "prefer_mature",
    "prefer_stable_price",
    "prefer_local",
    "prefer_popular",
]


class RouteResult(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
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

    # 软偏好：只参与排序加权，不作为数据库硬性过滤条件
    preferences: list[PreferenceType] = []

    limit: int = Field(
        default=10,
        ge=1,
        le=10,
    )

    reason: str = ""

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.intent == "search_achievement" and (self.min_budget_wan is not None or self.max_budget_wan is not None or self.coop_modes):
            raise ValueError("成果查询不能包含需求专用条件")
        if self.intent == "search_demand" and (self.min_price_wan is not None or self.max_price_wan is not None or self.min_maturity is not None):
            raise ValueError("需求查询不能包含成果专用条件")
        for lower, upper in [(self.min_price_wan, self.max_price_wan), (self.min_budget_wan, self.max_budget_wan)]:
            if lower is not None and upper is not None and lower > upper:
                raise ValueError("最低金额不能超过最高金额")
        if len(self.keywords) > 20 or any(len(word) > 100 for word in self.keywords):
            raise ValueError("关键词超出限制")
        if len(self.preferences) > len(PreferenceType.__args__):
            raise ValueError("软偏好超出限制")
        if len(set(self.preferences)) != len(self.preferences):
            raise ValueError("软偏好不能重复")
        return self


class CardReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    card_type: Literal["achievement", "demand"]
    id: int = Field(gt=0, strict=True)


class CardLocator(CardReference):
    title: str = Field(default="", max_length=80)
    messageId: int = Field(gt=0, strict=True)


class ContextMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(max_length=800)


class ConversationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemaVersion: Literal[1]
    generation: int = Field(ge=0, strict=True)
    queryPlan: dict = Field(default_factory=dict)
    cards: list[CardLocator] = Field(default_factory=list, max_length=10)
    messages: list[ContextMessage] = Field(default_factory=list, max_length=4)
    reference: CardReference | None = None

    @model_validator(mode="after")
    def validate_context(self):
        if len(json.dumps(self.queryPlan, ensure_ascii=False, separators=(",", ":"))) > 2000:
            raise ValueError("查询状态超出限制")
        if self.queryPlan:
            RouteResult.model_validate(self.queryPlan)
        if len(self.messages) % 2 or any(message.role != ("user" if index % 2 == 0 else "assistant") for index, message in enumerate(self.messages)):
            raise ValueError("历史消息必须是完整的成功轮次")
        if self.reference and not any(card.card_type == self.reference.card_type and card.id == self.reference.id for card in self.cards):
            raise ValueError("引用不在服务端卡片上下文中")
        if len(self.model_dump_json()) > 8000:
            raise ValueError("上下文超出限制")
        return self


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
    exclude_owner_user_id: int | None = Field(default=None, gt=0)
    context: ConversationContext | None = None


class InternalChatRequest(ChatRequest):
    executionId: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")


class ChatResponse(BaseModel):
    success: bool
    intent: str | None = None
    message: str
    data: Any = None
    queryPlan: dict | None = None
