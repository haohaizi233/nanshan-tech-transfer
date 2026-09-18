import json
import re

from app.llm_client import chat_completion
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
    """
    尽可能从模型输出中提取 JSON。

    即使模型偶尔返回 ```json ... ```，
    也能做容错处理。
    """

    text = text.strip()

    # 去掉 Markdown code fence
    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\s*```$",
        "",
        text,
    )

    # 优先直接解析
    try:
        return json.loads(text)

    except json.JSONDecodeError:
        pass

    # 容错：提取第一个 {...}
    match = re.search(
        r"\{.*\}",
        text,
        flags=re.DOTALL,
    )

    if not match:
        raise ValueError(
            f"模型没有返回 JSON: {text[:300]}"
        )

    return json.loads(match.group())


def classify_intent(
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
        max_tokens=1200,
        temperature=0.0,
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
            max_tokens=1200,
            temperature=0.0,
        )

        parsed = _extract_json(retry_output)

        return RouteResult.model_validate(parsed)