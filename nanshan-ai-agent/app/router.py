import logging
import re

from app.llm_client import LLMError, chat_completion, extract_llm_json
from app.schemas import RouteResult
from app.runtime_trace import trace_stage
from app.services import taxonomy
from app.services.amount_parser import find_amount_bounds, has_negative_amount

_logger = logging.getLogger(__name__)


ROUTER_SYSTEM_PROMPT = """
你是“南山科转通”平台的业务查询参数解析器。

你的任务：

1. 判断用户是在查询科技成果、查询技术需求，
   还是提出了与当前业务无关的问题。

2. 从用户原话中提取数据库查询条件。

你不能闲聊。
你不能回答业务问题。
你不能查询数据库。
你不能编造用户没有提供的条件。

========================
允许的 intent
========================

search_achievement
search_demand
out_of_scope

========================
search_achievement
========================

用于：

科技成果
科研成果
技术成果
技术方案
科研技术

例如：

“帮我查人工智能成果”
“找100万元以内的机器视觉成果”
“找已经中试完成的人工智能技术”
“深圳先进院有哪些AI成果”
“介绍一下机器视觉成果”
“推荐适合产线缺陷检测的机器视觉成果”
“介绍一下机器视觉”

========================
search_demand
========================

用于：

企业技术需求
技术需求
企业难题
市场技术需求

例如：

“有哪些企业需要机器视觉”
“找深圳的AI技术需求”
“有没有预算100万以内的人工智能需求”
“有哪些联合开发的技术需求”

========================
out_of_scope
========================

例如：

“你好”
“讲个笑话”
“写首诗”
“今天天气怎么样”
“帮我写Python代码”

========================
字段提取规则
========================

keywords:
只提取用户真正想搜索的技术、产品、行业或应用场景。

例如：

“人工智能相关成果”
→ ["人工智能"]

“机器视觉缺陷检测成果”
→ ["机器视觉", "缺陷检测"]

不要把：
查询、介绍、解读、推荐、帮我、成果、需求、相关、有没有
放入 keywords。

------------------------

organization:

用户明确指定机构时提取。

例如：

“深圳先进院的人工智能成果”
→ "深圳先进院"

没有指定：
null

------------------------

region:

用户明确指定地域时提取。

例如：

“深圳南山区的技术需求”
→ "南山区"

没有指定：
null

------------------------

成果价格：

仅 search_achievement 使用。

“100万元以内”
→ max_price_wan = 100

“50万元以上”
→ min_price_wan = 50

“50到100万元”
→ min_price_wan = 50
→ max_price_wan = 100

------------------------

需求预算：

仅 search_demand 使用。

“预算100万元以内”
→ max_budget_wan = 100

“预算50万元以上”
→ min_budget_wan = 50

“预算50到100万元”
→ min_budget_wan = 50
→ max_budget_wan = 100

------------------------

成熟度：

仅 search_achievement 使用。

数据库枚举：

01_idea = 概念阶段
02_lab = 实验室验证
03_pilot_ready = 中试就绪
04_pilot_done = 中试完成
05_mass_ready = 量产就绪
06_mass_done = 已量产

例如：

“中试完成以上”
→ min_maturity = "04_pilot_done"

“量产就绪以上”
→ min_maturity = "05_mass_ready"

"实验室验证以上"
→ min_maturity = "02_lab"

只有裸等级、没有"以上/不低于"时属于软偏好，不要写进 min_maturity：

"最好是中试完成的成果"
→ min_maturity = null
→ preferences = ["prefer_mature"]

没有明确成熟度要求：
null

------------------------

coop_modes:

仅 search_demand 使用。

数据库里实际存在的合作方式取值只有：
联合研发、技术服务、成果转化、工艺授权

例如：

"找联合开发的技术需求"
→ ["联合研发"]

"找技术服务或成果转化类的需求"
→ ["技术服务", "成果转化"]

"找联合研发的需求"
→ ["联合研发"]

多个合作方式是"或"的关系（命中任一即可）。
没有指定：
[]

------------------------

preferences（软偏好）:

只影响排序权重，永远不会变成数据库硬过滤。
可选值：

prefer_recent        优先最新发布
prefer_mature       优先成熟度更高
prefer_stable_price 优先报价或预算明确
prefer_low_price    优先报价落在用户预算内
prefer_local        优先本地或同机构
prefer_popular      优先热度高

例如：

"优先最新的机器视觉成果"
→ preferences = ["prefer_recent"]

"优先成熟的成果"
→ preferences = ["prefer_mature"]

"优先本地机构的成果"
→ preferences = ["prefer_local"]

没有软偏好：
[]

------------------------

limit:

如果用户明确说：
“3条”
→ 3

“5个”
→ 5

没有明确数量：
10

最大不能超过10。

========================
硬性条件 vs 软偏好（最重要）
========================

硬性条件（写进对应字段，数据库会硬过滤）：

- 明确金额边界：以内 / 不超过 / 不高于 / 最多 / 最高 / 上限 / 以上 / 不少于 / 至少 / 最低
- 明确成熟度边界：X 及以上 / X 起步
- 明确机构、地域、合作方式

软偏好（只写进 preferences，绝不写进硬性字段）：

- 出现"最好 / 最佳 / 优先 / 首选 / 倾向 / 更希望 / 尽量 / 酌情"等词修饰的条件
- 主观倾向：更成熟、更新、便宜一点、本地一些、热门一些

反例（严禁这样输出）：

用户："找最好中试完成的机器视觉成果"
错误：min_maturity = "04_pilot_done"   ← 硬过滤会排掉所有不满足的成果
正确：min_maturity = null，preferences = ["prefer_mature"]

用户："优先100万元以内的机器视觉成果"
错误：max_price_wan = 100              ← 硬过滤
正确：max_price_wan = null，preferences = ["prefer_low_price"]

用户："100万元以内的机器视觉成果"（没有最好/优先等修饰）
正确：max_price_wan = 100              ← 明确边界属于硬性条件

========================
重要规则
========================

用户没有提供的条件必须使用 null 或 []。

禁止自己增加：

价格
预算
机构
地域
成熟度
合作方式

不要主动扩展同义词。
关键词扩展由后端程序处理。

========================
输出
========================

只能输出 JSON。

格式：

{
  "intent": "search_achievement",
  "keywords": ["人工智能"],
  "organization": null,
  "region": null,
  "min_price_wan": null,
  "max_price_wan": 100,
  "min_budget_wan": null,
  "max_budget_wan": null,
  "min_maturity": "04_pilot_done",
  "coop_modes": [],
  "preferences": [],
  "limit": 10,
  "reason": "用户希望查询100万元以内且成熟度达到中试完成以上的人工智能成果"
}

禁止 Markdown。
禁止代码块。
禁止思考过程。
禁止输出 JSON 以外的内容。
"""


def _extract_json(text: str) -> dict:
    return extract_llm_json(text, required_any=("intent",))


_ACHIEVEMENT_MARKERS = re.compile(
    r"成果|科研成果|技术成果|科技成果|技术方案",
)
_DEMAND_MARKERS = re.compile(
    r"技术需求|企业需求|企业难题|技术难题|(?:的)?需求",
)
_GREETING_ONLY = re.compile(
    r"^(你好|您好|早上好|下午好|晚上好|谢谢|再见|在吗|嗨|hello|hi)[!！。.?？~～\s]*$",
    re.IGNORECASE,
)

_QUERY_STOPWORDS = {
    "帮我", "给我", "请", "查一下", "查询", "查", "找", "搜索", "搜", "看看",
    "有没有", "有哪些", "一下", "有关", "相关", "方面", "领域", "的", "科技",
    "技术", "成果", "需求", "企业", "公司", "一些", "几个", "多少", "什么",
    "如何", "怎么", "能否", "可以", "想要", "希望", "关于", "用于", "需要",
}

_KEYWORD_NOISE = (
    "有没有", "有哪些", "关于", "有关", "帮我", "给我", "用于", "需要",
    "企业", "查询", "搜索", "适合",
)

_LEADING_NOISE = re.compile(
    r"^(?:帮我|给我|请|麻烦|我要|我想要|想要|我想|我需要|需要|"
    r"查一下|找一下|搜一下|查询一下|搜索一下|"
    r"查询|搜索|介绍|解读|推荐|讲讲|讲解|看看|查查|找找|查|找|搜|一下|"
    r"有没有|有哪些|有啥|是否有|关于|有关)+"
)
_DOMAIN_ONLY = re.compile(
    r"^([\u4e00-\u9fa5A-Za-z0-9]{2,12}?)(?:方面|领域|相关)的?$"
)
_TRAILING_NOISE = re.compile(
    r"(?:有哪些|有没有|吗|呢|看看|一下|[?？。！!，,.\s])+$"
)


def apply_condition_guards(route: RouteResult, message: str, inherited: bool = False) -> RouteResult:
    """硬性条件 / 软偏好分离闸门（确定性，不依赖模型行为）。

    模型可能把"最好中试完成"这类软偏好直接写成 ``min_maturity``，
    进而在数据库里变成硬过滤、把符合技术方向的结果全部排空。
    这里对**所有**路由（规则解析与模型解析 alike）统一做一次纠正：

    1. 用户原话中该条件出现在软偏好标记之后且没有硬性覆盖词 → 降级为 preferences；
    2. 原话里根本没有这个条件 → 视为模型臆造，直接清除
       （``inherited=True`` 时跳过：多轮继承的条件本就不在当轮原话里）；
    3. 成熟度等级若在原话中只以裸等级出现（无"以上/不低于"）→ 降级为 prefer_mature。
    """
    values = route.model_dump()
    preferences = list(values.get("preferences") or [])
    text = message or ""

    def add_preference(code: str) -> None:
        if code not in preferences:
            preferences.append(code)

    # ── 成熟度 ──────────────────────────────────────────────
    maturity_span = taxonomy.find_maturity_span(text)
    hard_maturity_words = ("以上", "不低于", "不少于", "至少", "起步", "达到", "高于")
    if values.get("min_maturity"):
        if maturity_span is None:
            # 原话没有提到任何成熟度等级 → 模型臆造，清除。
            if not inherited:
                values["min_maturity"] = None
        else:
            level, position = maturity_span
            if level != values["min_maturity"]:
                # 原话说的等级与模型填的不一致，以原话为准。
                values["min_maturity"] = level
            window = text[position:position + len(level) + 8]
            explicit_set = taxonomy.has_explicit_set(text[max(0, position - taxonomy.PREFERENCE_LOOKBACK):position])
            if not explicit_set and not any(word in window for word in hard_maturity_words):
                # 裸等级（例如"最好是中试完成的"）是偏好，不是硬性下限。
                values["min_maturity"] = None
                add_preference("prefer_mature")
            elif taxonomy.is_soft_condition(text, position):
                values["min_maturity"] = None
                add_preference("prefer_mature")

    # ── 金额 / 价格 / 预算 ─────────────────────────────────
    bounds = find_amount_bounds(text)
    if bounds.get("cancelled"):
        values["min_price_wan"] = None
        values["max_price_wan"] = None
        values["min_budget_wan"] = None
        values["max_budget_wan"] = None
    else:
        span = bounds.get("span_start")
        soft_amount = span is not None and taxonomy.is_soft_condition(text, span)
        for lower_key, upper_key in (
            ("min_price_wan", "max_price_wan"),
            ("min_budget_wan", "max_budget_wan"),
        ):
            if values.get(lower_key) is not None and bounds.get("min_wan") is None and not inherited:
                values[lower_key] = None
            if values.get(upper_key) is not None and bounds.get("max_wan") is None and not inherited:
                values[upper_key] = None
        if soft_amount:
            if values.get("max_price_wan") is not None or values.get("max_budget_wan") is not None:
                values["max_price_wan"] = None
                values["max_budget_wan"] = None
                add_preference("prefer_low_price")
            if values.get("min_price_wan") is not None or values.get("min_budget_wan") is not None:
                values["min_price_wan"] = None
                values["min_budget_wan"] = None

    # ── 合作方式 ────────────────────────────────────────────
    if values.get("coop_modes"):
        mentioned = [
            mode for mode in values["coop_modes"]
            if mode in text or taxonomy.coop_mode_stem(mode) in text
        ]
        if not mentioned:
            mentioned = list(values["coop_modes"])
        values["coop_modes"] = mentioned
        for mode in mentioned:
            position = text.find(mode)
            if position >= 0 and taxonomy.is_soft_condition(text, position):
                values["coop_modes"] = []
                break

    # ── 软偏好编码补齐 ─────────────────────────────────────
    for code in taxonomy.detect_preferences(text):
        add_preference(code)
    values["preferences"] = [code for code in preferences if code in taxonomy.PREFERENCE_CODE_SET]

    try:
        return RouteResult.model_validate(values)
    except Exception:
        # 纠正过程不应把整轮查询打挂：保留原路线，只丢软偏好。
        values["preferences"] = []
        try:
            return RouteResult.model_validate(values)
        except Exception:
            return route


def _normalize_query_keyword(keyword: str) -> str:
    keyword = (keyword or "").strip()
    while keyword:
        trimmed = False
        for suffix in ("方面", "领域", "相关", "科技", "技术", "的"):
            if keyword.endswith(suffix) and len(keyword) > len(suffix):
                keyword = keyword[: -len(suffix)]
                trimmed = True
                break
        if not trimmed:
            break
    if not keyword or keyword in _QUERY_STOPWORDS:
        return ""
    if any(noise in keyword for noise in _KEYWORD_NOISE):
        return ""
    return keyword


def _strip_query_noise(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^再(?=找|查|搜|推荐)", "", cleaned)
    prev = None
    while prev != cleaned:
        prev = cleaned
        cleaned = _LEADING_NOISE.sub("", cleaned)
        cleaned = _TRAILING_NOISE.sub("", cleaned)
        cleaned = cleaned.strip()
    return cleaned


def _extract_simple_topic(cleaned: str, suffix: str) -> str:
    """只接受「主题 + 方面/相关 + 成果/需求」短模板，避免把整句当关键词。"""
    match = re.fullmatch(
        rf"([\u4e00-\u9fa5A-Za-z0-9]{{2,12}}?)(?:方面|领域|相关)?的?{suffix}",
        cleaned,
    )
    if not match:
        return ""
    return _normalize_query_keyword(match.group(1))


def _extract_query_keywords(text: str, kind: str) -> list[str]:
    cleaned = _strip_query_noise(text)
    if not cleaned:
        return []

    if kind == "achievement":
        keyword = _extract_simple_topic(
            cleaned,
            r"(?:科技)?(?:成果|技术方案)",
        )
    else:
        keyword = _extract_simple_topic(
            cleaned,
            r"(?:技术)?需求",
        )

    return [keyword] if keyword else []


def try_heuristic_classify(user_message: str) -> RouteResult | None:
    """短句模板快速路由；复杂问法返回 None，交给 LLM。"""
    text = (user_message or "").strip()
    if not text:
        return None

    if _GREETING_ONLY.match(text):
        return RouteResult(
            intent="out_of_scope",
            keywords=[],
            reason="寒暄问候",
        )

    has_achievement = bool(_ACHIEVEMENT_MARKERS.search(text))
    has_demand = bool(_DEMAND_MARKERS.search(text))

    if has_achievement and has_demand:
        return None

    if has_achievement:
        keywords = _extract_query_keywords(text, "achievement")
        if not keywords:
            return None
        return RouteResult(
            intent="search_achievement",
            keywords=keywords,
            reason="规则解析：科技成果查询",
        )

    if has_demand:
        keywords = _extract_query_keywords(text, "demand")
        if not keywords:
            return None
        return RouteResult(
            intent="search_demand",
            keywords=keywords,
            reason="规则解析：技术需求查询",
        )

    cleaned = _strip_query_noise(text)
    domain_match = _DOMAIN_ONLY.fullmatch(cleaned)
    domain = _normalize_query_keyword(domain_match.group(1)) if domain_match else ""
    # 裸领域短句只有在命中已登记的技术领域时才直接判为业务查询，
    # 否则"讲个笑话""今天天气怎么样"这类闲聊会被误当成领域检索。
    if domain and taxonomy.is_registered_domain(domain):
        return RouteResult(
            intent="search_achievement",
            keywords=[domain],
            reason="规则解析：领域关键词",
        )

    return None


def _fallback_classify(user_message: str) -> RouteResult | None:
    """Use explicit business markers when the model is unavailable; never infer filters."""
    text = (user_message or "").strip()
    has_achievement = bool(_ACHIEVEMENT_MARKERS.search(text))
    has_demand = bool(_DEMAND_MARKERS.search(text))
    if has_achievement == has_demand:
        return None

    intent = "search_achievement" if has_achievement else "search_demand"
    kind = "achievement" if has_achievement else "demand"
    keywords = _extract_query_keywords(text, kind)
    if not keywords:
        marker = (_ACHIEVEMENT_MARKERS if has_achievement else _DEMAND_MARKERS).search(text)
        topic = _normalize_query_keyword(_strip_query_noise(text[:marker.start()])) if marker else ""
        if topic:
            keywords = [topic[:80]]
    return RouteResult(
        intent=intent,
        keywords=keywords,
        reason="规则兜底：模型暂不可用，未提取未明确条件",
    )


def _degraded_classify(user_message: str) -> RouteResult | None:
    """模型不可用时的降级路由（比 _fallback_classify 更宽松，但不臆造筛选条件）。

    上游 502/超时时不应该让整轮查询直接失败。只要用户话里出现
    已登记的技术领域，就按成果查询兜底；仍然只提取技术词，
    不推断价格、成熟度、机构等筛选条件。
    """
    text = (user_message or "").strip()
    if not text or _GREETING_ONLY.match(text):
        return None
    for domain in sorted(taxonomy.REGISTERED_DOMAINS, key=len, reverse=True):
        if domain in text:
            return RouteResult(
                intent="search_achievement",
                keywords=[domain],
                reason="降级路由：模型暂不可用，按已登记技术领域兜底",
            )
    return None


@trace_stage("route")
def classify_intent(
    user_message: str,
) -> RouteResult:
    heuristic = try_heuristic_classify(user_message)
    # 寒暄可跳过 LLM；短模板查询也可跳过。复杂问法必须走 LLM 抽词。
    if heuristic is not None:
        return apply_condition_guards(heuristic, user_message)

    try:
        route = _classify_intent_llm(user_message)
    except LLMError as exc:
        fallback = _fallback_classify(user_message) or _degraded_classify(user_message)
        if fallback is not None:
            _logger.warning("[Router] LLM 不可用，使用规则兜底: %r", exc)
            return apply_condition_guards(fallback, user_message)
        raise
    return apply_condition_guards(route, user_message)


def _classify_intent_llm(
    user_message: str,
) -> RouteResult:

    messages = [
        {
            "role": "system",
            "content": ROUTER_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": user_message,
        },
    ]

    # 第一次调用
    output = chat_completion(
        messages=messages,
        max_tokens=800,
        temperature=0.0,
        timeout=45,
    )

    try:
        parsed = _extract_json(output)
        return RouteResult.model_validate(parsed)

    except Exception:
        # 如果模型输出了思考过程，没有按要求给 JSON，
        # 再进行一次强制格式修复
        retry_messages = [            {
                "role": "system",
                "content": """
你是一个严格的 JSON 格式转换器。

根据用户原始问题进行业务分类。

只允许以下三个 intent：
search_achievement
search_demand
out_of_scope

硬性条件与软偏好必须分开：
- 明确边界（以内/不超过/以上/不少于/至少/最低/最多）写进对应硬性字段。
- 带"最好/最佳/优先/首选/倾向/更希望/尽量"修饰的条件一律写进 preferences，
  绝不能写进 min_maturity / min_price_wan / max_price_wan / min_budget_wan /
  max_budget_wan / organization / region / coop_modes。

你只能返回 JSON。

禁止：
- 输出思考过程
- 输出解释
- 输出 Markdown
- 输出代码块
- 输出 JSON 以外的任何文字

格式必须严格为：

{
  "intent": "search_achievement",
  "keywords": ["关键词"],
  "preferences": [],
  "reason": "分类原因"
}

如果与科技成果查询、技术需求查询无关：

{
  "intent": "out_of_scope",
  "keywords": [],
  "preferences": [],
  "reason": "与业务范围无关"
}
"""
            },
            {
                "role": "user",
                "content": user_message,
            },
        ]

        try:
            retry_output = chat_completion(
                messages=retry_messages,
                max_tokens=800,
                temperature=0.0,
                timeout=45,
            )
            parsed = _extract_json(retry_output)
        except LLMError:
            raise
        except Exception as exc:
            _logger.warning("[Router] JSON 修复失败，降级为最小查询计划: %r", exc)
            return _safe_route_from_payload({})

        return _safe_route_from_payload(parsed)


_ROUTE_FIELDS = set(RouteResult.model_fields)


def _sanitize_route_payload(payload: dict) -> dict:
    """把模型返回的 JSON 收敛成可校验的 RouteResult 入参。

    模型偶尔会带上未知字段、把成果/需求专用条件混在一起、或给出越界 limit。
    这些都不应该让整轮查询直接 500：能安全纠正就纠正，只保留可解释的字段。
    """
    if not isinstance(payload, dict):
        raise ValueError("路由结果必须是 JSON 对象")
    values = {key: payload[key] for key in payload if key in _ROUTE_FIELDS}

    intent = values.get("intent")
    if intent not in ("search_achievement", "search_demand", "out_of_scope"):
        raise ValueError(f"未知 intent: {intent!r}")

    if intent == "search_achievement":
        for key in ("min_budget_wan", "max_budget_wan", "coop_modes"):
            values.pop(key, None)
    elif intent == "search_demand":
        for key in ("min_price_wan", "max_price_wan", "min_maturity"):
            values.pop(key, None)

    keywords = values.get("keywords")
    if isinstance(keywords, str):
        values["keywords"] = [keywords]
    elif not isinstance(keywords, list):
        values["keywords"] = []
    values["keywords"] = [
        str(word).strip()[:100] for word in values["keywords"] if str(word).strip()
    ][:20]

    preferences = values.get("preferences")
    if isinstance(preferences, str):
        preferences = [preferences]
    if not isinstance(preferences, list):
        preferences = []
    values["preferences"] = [
        code for code in dict.fromkeys(str(code) for code in preferences)
        if code in taxonomy.PREFERENCE_CODE_SET
    ][: len(taxonomy.PREFERENCE_CODES)]

    for key in (
        "min_price_wan", "max_price_wan", "min_budget_wan", "max_budget_wan",
    ):
        raw = values.get(key)
        if raw is None:
            values[key] = None
            continue
        try:
            number = float(raw)
        except (TypeError, ValueError):
            values[key] = None
            continue
        values[key] = number if number == number and number not in (float("inf"), float("-inf")) and number >= 0 else None

    limit = values.get("limit")
    try:
        limit_value = int(limit)
    except (TypeError, ValueError):
        limit_value = 10
    values["limit"] = min(max(limit_value, 1), 10)

    if not isinstance(values.get("reason"), str):
        values["reason"] = ""
    return values


def _safe_route_from_payload(payload: dict) -> RouteResult:
    """尽最大努力从模型输出构造合法 RouteResult，失败时降级为纯关键词查询。"""
    try:
        return RouteResult.model_validate(payload)
    except Exception:
        pass
    try:
        return RouteResult.model_validate(_sanitize_route_payload(payload))
    except Exception:
        pass
    intent = payload.get("intent") if isinstance(payload, dict) else None
    if intent not in ("search_achievement", "search_demand", "out_of_scope"):
        intent = "search_achievement"
    keywords = payload.get("keywords") if isinstance(payload, dict) else None
    if isinstance(keywords, str):
        keywords = [keywords]
    if not isinstance(keywords, list):
        keywords = []
    return RouteResult(
        intent=intent,
        keywords=[str(word).strip()[:100] for word in keywords if str(word).strip()][:20],
        reason="模型输出不合法，已降级为最小可用查询计划",
    )
