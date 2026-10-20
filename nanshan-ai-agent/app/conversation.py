import math
import re
from dataclasses import dataclass, field

from app.schemas import CardLocator, ChatRequest, RouteResult


_POINTER = re.compile(r"第([一二三四五六七八九十\d]+)(?:个|项|条)|这个|那个|上一个|刚才|上述|上面|(?:^|[，。\s])它|介绍它|比较它|它们")
_FOLLOWUP = re.compile(r"^(?:那就|那么|再|把|只看|只要|还是|改为|改成|改到|换成|调整为|调整到|调整一下|继续|加上|限定|限制|取消|去掉|不限制|不限|不要限制|预算|价格|报价|金额|成熟度|地区|地域|机构|合作方式|最高|最低|最多|至少|不超过|不低于)")
_AMOUNT = r"(-?\d+(?:\.\d+)?)\s*(万(?:元)?|亿(?:元)?|元)?"
_MONEY_LABEL = re.compile(r"预算|价格|报价|金额|费用|成本")
_MEASURE_UNIT = re.compile(r"帧|微米|纳米|毫米|厘米|米|秒|毫秒|分钟|小时|次|个|件|吨|度|伏|瓦|赫兹|元素|[%％µμ]|[A-Za-z]")
_MATURITY = [("已量产", "06_mass_done"), ("量产完成", "06_mass_done"), ("量产就绪", "05_mass_ready"), ("中试完成", "04_pilot_done"), ("中试就绪", "03_pilot_ready"), ("实验室验证", "02_lab"), ("概念阶段", "01_idea")]
_TOPIC_SWITCH = re.compile(r"^\s*(?:那|就|帮我|请|我想|我要)?\s*(?:换成|换到|改为|改成|转向|换个方向(?:看|找)?)\s*([^，。；\s]{1,20})")
_TOPIC_SWITCH_CONDITION = re.compile(r"预算|价格|报价|金额|费用|成本|机构|地区|地域|成熟度|合作方式|上限|下限|\d")
_CLARIFY = "请提供明确的成果名称或选择卡片；一次最多比较两项，避免误指。"


@dataclass
class ContextResolution:
    route: RouteResult | None = None
    targets: list[CardLocator] = field(default_factory=list)
    clarification: str | None = None


def _amount(value, unit):
    number = float(value)
    if number < 0:
        raise ValueError("预算不能为负数")
    return number * (10000 if unit and unit.startswith("亿") else 0.0001 if unit == "元" else 1)


def _money_match(pattern, text, interval=False):
    for match in re.finditer(pattern, text):
        if _MEASURE_UNIT.match(text[match.end():].lstrip()):
            continue
        has_unit = bool(match[2] or (interval and match[4]))
        prefix = text[:match.start()]
        contextual = bool(re.search(r"(?:预算|价格|报价|金额|费用|成本)[^\d，。；;]{0,16}$", prefix))
        if has_unit or contextual or _MONEY_LABEL.search(match[0]):
            return match
    return None


def merge_route(message: str, route: RouteResult, previous: RouteResult | None = None) -> RouteResult:
    values = (previous or route).model_dump()
    if previous:
        values["reason"] = "继承上次成功查询并应用当前明确条件"
    prefix = "budget" if values["intent"] == "search_demand" else "price"
    lower, upper = "min_" + prefix + "_wan", "max_" + prefix + "_wan"
    if re.search(r"(?:不限|不限制|取消|去掉|不要限制).{0,6}(?:预算|价格|报价|金额)|(?:预算|价格|报价|金额).{0,5}(?:不限|不限制|取消)", message):
        values[lower] = values[upper] = None
    else:
        interval = _money_match(_AMOUNT + r"\s*(?:到|至|[-~～—])\s*" + _AMOUNT, message, interval=True)
        maximum = _money_match(r"(?:不超过|不高于|不大于|最多|最高|上限)(?:改成|改为|调整为|为|是)?\s*" + _AMOUNT, message)
        minimum = _money_match(r"(?<!不)(?:不少于|不低于|至少|最低|下限(?:为|是)?|高于|超过)\s*" + _AMOUNT, message)
        suffix_max = _money_match(_AMOUNT + r"\s*(?:以内|以下|之内|封顶)", message)
        suffix_min = _money_match(_AMOUNT + r"\s*(?:以上|起步)", message)
        if interval:
            values[lower] = _amount(interval[1], interval[2] or interval[4])
            values[upper] = _amount(interval[3], interval[4] or interval[2])
        else:
            if maximum or suffix_max:
                match = maximum or suffix_max
                values[upper] = _amount(match[1], match[2])
            if minimum or suffix_min:
                match = minimum or suffix_min
                values[lower] = _amount(match[1], match[2])
            if re.search(r"(?:-|负)\s*\d+(?:\.\d+)?\s*(?:万|亿|元)", message):
                raise ValueError("预算不能为负数")
    for label, maturity in _MATURITY:
        if label in message:
            values["min_maturity"] = maturity
            break
    if re.search(r"(?:不限|取消|去掉).{0,4}成熟度", message):
        values["min_maturity"] = None
    if previous:
        for label, key in [("机构", "organization"), ("地域", "region"), ("地区", "region")]:
            if re.search(r"(?:不限|取消|去掉|不限制).{0,4}" + label, message):
                values[key] = None
            match = re.search(label + r"(?:改成|改为|换成|限定为|是|为|到)\s*([^，。；\s]{1,40})", message)
            if match:
                values[key] = match[1]
        if "不限合作方式" in message:
            values["coop_modes"] = []
        modes = [mode for mode in ("联合开发", "技术转让", "技术许可", "委托开发") if mode in message]
        if modes:
            values["coop_modes"] = modes
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
    condition_text = re.sub(r"^(?:成果|需求)(?=预算|价格|不限)", "", text)
    followup = bool(_FOLLOWUP.search(condition_text))
    if followup and re.search(r"(?:成果|需求|技术方向|推荐|寻找|查找)", condition_text) and not re.search(r"(?:仍然|继续|这些|之前|刚才)", text):
        followup = False
    topic_switch = _TOPIC_SWITCH.search(condition_text)
    if followup and topic_switch and not _TOPIC_SWITCH_CONDITION.search(topic_switch.group(1)):
        followup = False
    if followup:
        if not context or not context.queryPlan:
            return ContextResolution(clarification="请先说明要筛选的技术方向和成果或需求类型，再补充条件。")
        previous = RouteResult.model_validate(context.queryPlan)
        try:
            route = merge_route(text, previous, previous)
            if route.model_dump(exclude={"reason"}) == previous.model_dump(exclude={"reason"}):
                return ContextResolution(clarification="请说明要修改的具体条件及取值。")
            return ContextResolution(route=route)
        except ValueError:
            return ContextResolution(clarification="请确认预算或价格范围，最低值不能超过最高值，金额不能为负数。")
    return ContextResolution()


def record_matches(item: dict, route: RouteResult) -> bool:
    achievement = route.intent == "search_achievement"
    prefix = "price" if achievement else "budget"
    for bound in ("min", "max"):
        expected = getattr(route, f"{bound}_{prefix}_wan")
        actual = item.get(f"{prefix}_{bound}_wan")
        if expected is not None:
            if actual is None:
                return False
            try:
                actual = float(actual)
                if not math.isfinite(actual):
                    return False
                if (bound == "min" and actual < expected) or (bound == "max" and actual > expected):
                    return False
            except (ValueError, TypeError):
                return False
    organization = item.get("source_org_name" if achievement else "org_name_snapshot")
    if route.organization and route.organization.casefold() not in str(organization or "").casefold():
        return False
    if route.region and route.region.casefold() not in str(item.get("region") or "").casefold():
        return False
    if achievement and route.min_maturity:
        maturity = item.get("maturity_level")
        allowed = {value for _, value in _MATURITY}
        if maturity not in allowed or maturity < route.min_maturity:
            return False
    if not achievement and any(mode.casefold() not in str(item.get("coop_mode") or "").casefold() for mode in route.coop_modes):
        return False
    return True
