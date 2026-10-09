import re

from app.llm_client import LLMError, chat_completion, extract_llm_json
from app.schemas import RouteResult


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
查询、帮我、成果、需求、相关、有没有
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

“实验室验证以上”
→ min_maturity = "02_lab"

没有明确成熟度要求：
null

------------------------

coop_modes:

仅 search_demand 使用。

例如：

“找联合开发的技术需求”
→ ["联合开发"]

没有指定：
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
    "企业", "查询", "搜索",
)

_LEADING_NOISE = re.compile(
    r"^(?:帮我|给我|请|麻烦|我要|我想要|想要|我想|我需要|需要|"
    r"查一下|找一下|搜一下|查询一下|搜索一下|"
    r"查询|搜索|看看|查查|找找|查|找|搜|一下|"
    r"有没有|有哪些|有啥|是否有|关于|有关)+"
)
_DOMAIN_ONLY = re.compile(
    r"^([\u4e00-\u9fa5A-Za-z0-9]{2,12}?)(?:方面|领域|相关)的?$"
)
_TRAILING_NOISE = re.compile(
    r"(?:有哪些|有没有|吗|呢|看看|一下|[?？。！!，,.\s])+$"
)


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
    if domain:
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


def classify_intent(
    user_message: str,
) -> RouteResult:
    heuristic = try_heuristic_classify(user_message)
    # 寒暄可跳过 LLM；短模板查询也可跳过。复杂问法必须走 LLM 抽词。
    if heuristic is not None:
        return heuristic

    try:
        return _classify_intent_llm(user_message)
    except LLMError as exc:
        fallback = _fallback_classify(user_message)
        if fallback is not None:
            print("[Router] LLM 不可用，使用显式业务标记兜底:", repr(exc))
            return fallback
        raise


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
        retry_messages = [
            {
                "role": "system",
                "content": """
你是一个严格的 JSON 格式转换器。

根据用户原始问题进行业务分类。

只允许以下三个 intent：

search_achievement
search_demand
out_of_scope

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
  "reason": "分类原因"
}

如果与科技成果查询、技术需求查询无关：

{
  "intent": "out_of_scope",
  "keywords": [],
  "reason": "与业务范围无关"
}
"""
            },
            {
                "role": "user",
                "content": user_message,
            },
        ]

        retry_output = chat_completion(
            messages=retry_messages,
            max_tokens=800,
            temperature=0.0,
            timeout=45,
        )

        parsed = _extract_json(retry_output)

        return RouteResult.model_validate(parsed)