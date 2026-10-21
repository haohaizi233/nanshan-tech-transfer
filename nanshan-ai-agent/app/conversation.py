import math
import re
from dataclasses import dataclass, field

from app.schemas import CardLocator, ChatRequest, RouteResult
from app.router import apply_condition_guards
from app.services import taxonomy
from app.services.amount_parser import find_amount_bounds, has_negative_amount


_POINTER = re.compile(r"第([一二三四五六七八九十\d]+)(?:个|项|条)|这个|那个|上一个|刚才|上述|上面|(?:^|[，。\s])它|介绍它|比较它|它们")
_FOLLOWUP = re.compile(r"^(?:那就|那么|再|把|只看|只要|还是|改为|改成|改到|换成|调整为|调整到|调整一下|继续|加上|限定|限制|取消|去掉|不限制|不限|不要限制|预算|价格|报价|金额|成熟度|地区|地域|机构|合作方式|最高|最低|最多|至少|不超过|不低于)")
_MATURITY = list(taxonomy.MATURITY_LABEL_GROUPS)
_TOPIC_SWITCH = re.compile(r"^\s*(?:那|就|帮我|请|我想|我要)?\s*(?:换成|换到|改为|改成|转向|换个方向(?:看|找)?)\s*([^，。；\s]{1,20})")
_TOPIC_SWITCH_CONDITION = re.compile(
    r"预算|价格|报价|金额|机构|地区|地域|成熟度|合作方式|上限|下限|\d|"
    + "|".join(re.escape(spelling) for spelling in taxonomy.COOP_MODE_ALL_SPELLINGS)
)
_CLARIFY = "请提供明确的成果名称或选择卡片；一次最多比较两项，避免误指。"


@dataclass
class ContextResolution:
    route: RouteResult | None = None
    targets: list[CardLocator] = field(default_factory=list)
    clarification: str | None = None


def _mentions_new_domain(text: str, previous_keywords: list[str]) -> bool:
    """用户是否提到了与上一轮不同的技术方向（是 → 视为新主题，不继承旧条件）。"""
    known = {keyword.casefold() for keyword in previous_keywords or []}
    for domain in taxonomy.REGISTERED_DOMAINS:
        if domain in text and domain.casefold() not in known:
            return True
    return False


def _merge_preferences(values: dict, message: str) -> None:
    """合并软偏好：继承上一次的 preference，并补上本轮识别到的。"""
    preferences = list(values.get("preferences") or [])
    for code in taxonomy.detect_preferences(message):
        if code not in preferences:
            preferences.append(code)
    values["preferences"] = [code for code in preferences if code in taxonomy.PREFERENCE_CODE_SET]


def merge_route(message: str, route: RouteResult, previous: RouteResult | None = None) -> RouteResult:
    values = (previous or route).model_dump()
    if previous:
        values["reason"] = "继承上次成功查询并应用当前明确条件"
    prefix = "budget" if values["intent"] == "search_demand" else "price"
    lower, upper = "min_" + prefix + "_wan", "max_" + prefix + "_wan"
    bounds = find_amount_bounds(message)
    if bounds.get("cancelled"):
        values["min_price_wan"] = values["max_price_wan"] = None
        values["min_budget_wan"] = values["max_budget_wan"] = None
    else:
        if bounds.get("min_wan") is not None:
            values[lower] = bounds["min_wan"]
        if bounds.get("max_wan") is not None:
            values[upper] = bounds["max_wan"]
        if has_negative_amount(message):
            raise ValueError("预算不能为负数")
    maturity_span = taxonomy.find_maturity_span(message)
    if maturity_span:
        values["min_maturity"] = maturity_span[0]
    if re.search(r"(?:不限|取消|去掉).{0,4}成熟度", message):
        values["min_maturity"] = None
    if previous:
        for label, key in [("机构", "organization"), ("地域", "region"), ("地区", "region")]:
            if re.search(r"(?:不限|取消|去掉|不限制).{0,4}" + label, message):
                values[key] = None
            match = re.search(label + r"(?:改成|改为|换成|限定为|是|为|到)\s*([^，。；\s]{1,40})", message)
            if match:
                values[key] = match[1]
        if "不限合作方式" in message or re.search(r"(?:不限|取消|去掉).{0,4}合作方式", message):
            values["coop_modes"] = []
        detected_modes = taxonomy.detect_coop_modes(message)
        if detected_modes:
            values["coop_modes"] = detected_modes
    # 意图冲突：成果 / 需求专用条件互相串场时，按条件归属切换意图。
    if values["intent"] == "search_achievement" and values.get("coop_modes"):
        values["intent"] = "search_demand"
        values["min_price_wan"] = values["max_price_wan"] = None
        values["min_maturity"] = None
    elif values["intent"] == "search_demand" and values.get("min_maturity"):
        values["intent"] = "search_achievement"
        values["min_budget_wan"] = values["max_budget_wan"] = None
        values["coop_modes"] = []
    _merge_preferences(values, message)
    return RouteResult.model_validate(values)


def resolve_context(request: ChatRequest) -> ContextResolution:
    text = request.message.strip()
    context = request.context
    cards = context.cards if context else []
    explicit = context.reference if context else None
    pointer = bool(_POINTER.search(text))
    comparison = bool(re.search(r"比较|对比|选哪|哪个好|哪一个|哪个更", text))
    named = [card for card in cards if card.title and card.title in text]
    if explicit or pointer or (named and comparison):
        recent = [card for card in cards if card.messageId == cards[-1].messageId] if cards else []
        targets = []
        if explicit:
            targets = [card for card in cards if card.id == explicit.id and card.card_type == explicit.card_type][-1:]
        ordinals = re.findall(r"第([一二三四五六七八九十\d]+)(?:个|项|条)", text)
        for ordinal in ordinals:
            number = int(ordinal) if ordinal.isdigit() else "一二三四五六七八九十".find(ordinal) + 1
            if not 1 <= number <= len(recent):
                return ContextResolution(clarification=_CLARIFY)
            targets.append(recent[number - 1])
        if not ordinals and not explicit:
            targets = named or (recent if len(recent) == 1 else [])
        unique = {(card.card_type, card.id): card for card in targets}
        targets = list(unique.values())
        if not targets or len(targets) > 2 or (comparison and len(targets) != 2):
            return ContextResolution(clarification=_CLARIFY)
        expected_kind = "demand" if "需求" in text else "achievement" if "成果" in text else None
        if expected_kind and any(card.card_type != expected_kind for card in targets):
            return ContextResolution(clarification="所指卡片类型与问题不一致，请重新选择成果或需求。")
        return ContextResolution(targets=targets)
    condition_text = re.sub(r"^(?:请|帮我|麻烦)+", "", text)
    condition_text = re.sub(r"^(?:成果|需求)(?=预算|价格|不限)", "", condition_text)
    followup = bool(_FOLLOWUP.search(condition_text))
    topic_switch = _TOPIC_SWITCH.search(condition_text)
    previous_plan = None
    if context and context.queryPlan:
        try:
            previous_plan = RouteResult.model_validate(context.queryPlan)
        except Exception:
            previous_plan = None
    if followup and topic_switch and not _TOPIC_SWITCH_CONDITION.search(topic_switch.group(1)):
        followup = False
    if followup and re.search(r"(?:成果|需求|技术方向|推荐|寻找|查找)", condition_text) and not re.search(r"(?:仍然|继续|这些|之前|刚才)", text):
        followup = False
    if followup and previous_plan is not None:
        # 出现了与上一轮不同的技术方向 → 视为新主题，旧条件不再继承。
        if _mentions_new_domain(text, previous_plan.keywords):
            followup = False
    if followup:
        if not context or not context.queryPlan:
            return ContextResolution(clarification="请先说明要筛选的技术方向和成果或需求类型，再补充条件。")
        previous = previous_plan or RouteResult.model_validate(context.queryPlan)
        try:
            route = merge_route(text, previous, previous)
            # 多轮继承：只做「软偏好降级」，不清除上一轮继承来的硬性条件。
            route = apply_condition_guards(route, text, inherited=True)
            if route.model_dump(exclude={"reason"}) == previous.model_dump(exclude={"reason"}):
                return ContextResolution(clarification="请说明要修改的具体条件及取值。")
            return ContextResolution(route=route)
        except ValueError:
            return ContextResolution(clarification="请确认预算或价格范围，最低值不能超过最高值，金额不能为负数。")
    return ContextResolution()


def record_matches(item: dict, route: RouteResult) -> bool:
    """硬性条件的最终校验（与 SQL 过滤语义保持一致）。

    金额采用「区间重叠」语义：记录端价格未知（面议）不等于价格不符，
    因此不会被排除；记录端出现非法数值（NaN / Inf）则一律排除。
    """
    achievement = route.intent == "search_achievement"
    prefix = "price" if achievement else "budget"
    lower_expected = getattr(route, f"min_{prefix}_wan")
    upper_expected = getattr(route, f"max_{prefix}_wan")
    if lower_expected is not None or upper_expected is not None:
        record_lower = item.get(f"{prefix}_min_wan")
        record_upper = item.get(f"{prefix}_max_wan")
        if not taxonomy.amount_band_matches(record_lower, record_upper, lower_expected, upper_expected):
            return False
    organization = item.get("source_org_name" if achievement else "org_name_snapshot")
    if route.organization and route.organization.casefold() not in str(organization or "").casefold():
        return False
    if route.region and route.region.casefold() not in str(item.get("region") or "").casefold():
        return False
    if achievement and route.min_maturity:
        if not taxonomy.maturity_at_least(item.get("maturity_level"), route.min_maturity):
            return False
    if not achievement and route.coop_modes:
        allowed: set[str] = set()
        for mode in route.coop_modes:
            allowed.update(taxonomy.resolve_coop_modes(mode))
        actual = item.get("coop_mode")
        if isinstance(actual, str):
            actual = [actual]
        if not isinstance(actual, (list, tuple, set)):
            actual = []
        if not any(
            any(term in str(entry) for term in allowed)
            for entry in actual
        ):
            return False
    return True
