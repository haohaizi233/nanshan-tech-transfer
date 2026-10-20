"""Bounded, server-owned context built from complete successful turns."""

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.errors import bad_request


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    intent: Literal["search_achievement", "search_demand", "out_of_scope"]
    keywords: list[str] = Field(default_factory=list, max_length=20)
    organization: str | None = None
    region: str | None = None
    min_price_wan: float | None = Field(None, ge=0)
    max_price_wan: float | None = Field(None, ge=0)
    min_budget_wan: float | None = Field(None, ge=0)
    max_budget_wan: float | None = Field(None, ge=0)
    min_maturity: (
        Literal["01_idea", "02_lab", "03_pilot_ready", "04_pilot_done", "05_mass_ready", "06_mass_done"] | None
    ) = None
    coop_modes: list[str] = Field(default_factory=list)
    limit: int = Field(10, ge=1, le=10)
    reason: str = ""

    @model_validator(mode="after")
    def validate_ranges(self):
        for lower, upper in ((self.min_price_wan, self.max_price_wan), (self.min_budget_wan, self.max_budget_wan)):
            if lower is not None and upper is not None and lower > upper:
                raise ValueError("金额范围无效")
        if any(len(keyword) > 100 for keyword in self.keywords):
            raise ValueError("关键词过长")
        return self


def validate_query_plan(plan):
    if not isinstance(plan, dict) or len(json.dumps(plan, ensure_ascii=False)) > 2000:
        raise ValueError("查询条件超出限制")
    if plan:
        QueryPlan.model_validate(plan)
    return plan


def _text(value, limit):
    text = str(value or "")
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱]", text)
    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[手机号]", text)
    return text[:limit]


def validate_reference_cards(cards, reference):
    for card in cards or []:
        if (
            isinstance(card, dict)
            and card.get("card_type") == reference["cardType"]
            and card.get("id") == reference["cardId"]
        ):
            return {"card_type": reference["cardType"], "id": reference["cardId"]}
    raise bad_request("引用卡片不属于当前聊天记录")


def validate_reference(cur, user_id, generation, reference):
    if reference is None:
        return None
    cur.execute(
        """SELECT cards FROM ai_chat_message WHERE id = %s AND user_id = %s
                   AND generation = %s AND role = 'assistant'""",
        (reference["messageId"], user_id, generation),
    )
    row = cur.fetchone()
    if not row:
        raise bad_request("引用消息不属于当前聊天记录")
    return validate_reference_cards(row.get("cards"), reference)


def build_context(rows, generation, reference=None):
    rows = [row for row in rows if type(row.get("assistant_message_id")) is int and row["assistant_message_id"] > 0]
    context = {"schemaVersion": 1, "generation": generation, "queryPlan": {}, "cards": [], "messages": []}
    for row in reversed(rows):
        plan = row.get("query_plan") or {}
        if plan:
            try:
                context["queryPlan"] = validate_query_plan(plan)
            except ValueError as exc:
                raise bad_request("历史查询条件不可用，请重新说明完整条件") from exc
            break
    for row in rows[-2:]:
        context["messages"].extend(
            [
                {"role": "user", "content": _text(row.get("user_message"), 800)},
                {"role": "assistant", "content": _text(row.get("reply"), 800)},
            ]
        )
    seen = set()
    for row in reversed(rows):
        locators = []
        for card in row.get("cards") or []:
            if not isinstance(card, dict) or card.get("card_type") not in ("achievement", "demand"):
                continue
            card_id = card.get("id")
            key = (card.get("card_type"), card_id)
            if type(card_id) is not int or card_id < 1 or key in seen:
                continue
            seen.add(key)
            locators.append(
                {
                    "card_type": key[0],
                    "id": key[1],
                    "title": _text(card.get("title"), 80),
                    "messageId": row.get("assistant_message_id"),
                }
            )
        if locators:
            context["cards"] = locators[:10]
            break
    if reference:
        context["reference"] = {"card_type": reference["cardType"], "id": reference["cardId"]}
        source = next((row for row in rows if row.get("assistant_message_id") == reference["messageId"]), None)
        if source:
            target = next(
                (
                    card
                    for card in source.get("cards") or []
                    if card.get("id") == reference["cardId"] and card.get("card_type") == reference["cardType"]
                ),
                None,
            )
            if target and not any(
                card["id"] == reference["cardId"]
                and card["card_type"] == reference["cardType"]
                and card["messageId"] == reference["messageId"]
                for card in context["cards"]
            ):
                context["cards"] = [
                    {
                        "card_type": reference["cardType"],
                        "id": reference["cardId"],
                        "title": _text(target.get("title"), 80),
                        "messageId": reference["messageId"],
                    },
                    *context["cards"][:9],
                ]
        if not any(
            card["id"] == reference["cardId"]
            and card["card_type"] == reference["cardType"]
            and card["messageId"] == reference["messageId"]
            for card in context["cards"]
        ):
            raise bad_request("引用不属于可恢复的完整成功轮次，请重新选择卡片")
    while len(json.dumps(context, ensure_ascii=False)) > 8000 and context["messages"]:
        del context["messages"][:2]
    return context


def load_context(cur, user_id, generation, reference=None):
    validate_reference(cur, user_id, generation, reference)
    cur.execute(
        """WITH owned AS NOT MATERIALIZED (
                       SELECT id, user_message, reply, cards, query_plan, assistant_message_id
                       FROM ai_chat_turn WHERE user_id = %s AND generation = %s AND status = 'succeeded'
                       AND assistant_message_id IS NOT NULL
                   ), recent AS (SELECT id FROM owned ORDER BY id DESC LIMIT 2),
                   last_query AS (SELECT id FROM owned WHERE query_plan IS NOT NULL AND query_plan <> '{}'::jsonb
                                  ORDER BY id DESC LIMIT 1),
                   last_cards AS (SELECT id FROM owned WHERE jsonb_typeof(cards) = 'array' AND cards <> '[]'::jsonb
                                  ORDER BY id DESC LIMIT 1),
                   referenced AS (SELECT id FROM owned WHERE assistant_message_id = %s LIMIT 1)
                   SELECT * FROM owned WHERE id IN (
                       SELECT id FROM recent UNION SELECT id FROM last_query
                       UNION SELECT id FROM last_cards UNION SELECT id FROM referenced
                   ) ORDER BY id""",
        (user_id, generation, reference["messageId"] if reference else None),
    )
    return build_context(cur.fetchall() or [], generation, reference)
