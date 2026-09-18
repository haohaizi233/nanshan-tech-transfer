import json
import re
from typing import Any

from app.llm_client import chat_completion


RERANK_SYSTEM_PROMPT = """
你是“南山科转通”的科技成果与技术需求搜索结果重排器。

你的任务：
根据用户原始问题，对数据库已经查询出的候选结果进行相关性排序。

你不能创造新的成果或需求。
你不能修改候选数据。
你只能对输入候选项进行排序。

相关性判断优先级：

1. 技术方向
2. 应用场景
3. 用户明确提出的关键词
4. 行业领域
5. 成熟度
6. 价格或预算
7. 地域、机构、合作方式等明确条件

注意：

不能因为只出现一个相同词就判定高相关。
技术方向明显不同的结果应该排在后面。
应用场景明显不同的结果应该排在后面。

只返回最相关的候选，按相关性从高到低排列，最多 10 条。

你只能输出合法 JSON。

格式：

{
    "results": [
    {
      "id": 123
    }
  ]
}

禁止 Markdown。
禁止代码块。
禁止思考过程。
禁止输出 JSON 之外的文字。
"""


def _extract_json(text: str) -> dict:
    text = text.strip()

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

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            parsed, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue

        if isinstance(parsed, dict) and "results" in parsed:
            return parsed

    raise ValueError(
        f"模型没有返回有效 JSON: {text[:300]}"
    )


def _short_text(
    value: Any,
    max_length: int = 400,
) -> str:
    if value is None:
        return ""

    text = str(value).strip()

    if len(text) <= max_length:
        return text

    return text[:max_length] + "..."


def _achievement_for_llm(item: dict) -> dict:
    """
    只提供重排所需字段。
    不发送联系方式。
    """
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "organization": item.get("source_org_name"),
        "tech_intro": _short_text(
            item.get("tech_intro"),
            500,
        ),
        "application_fields": item.get(
            "application_fields"
        ),
        "innovation_points": item.get(
            "innovation_points"
        ),
        "maturity_level": item.get(
            "maturity_level"
        ),
        "pricing_mode": item.get(
            "pricing_mode"
        ),
        "price_min_wan": item.get(
            "price_min_wan"
        ),
        "price_max_wan": item.get(
            "price_max_wan"
        ),
    }


def _demand_for_llm(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "organization": item.get(
            "org_name_snapshot"
        ),
        "description": _short_text(
            item.get("description"),
            500,
        ),
        "region": item.get("region"),
        "coop_mode": item.get("coop_mode"),
        "budget_negotiable": item.get(
            "budget_negotiable"
        ),
        "budget_min_wan": item.get(
            "budget_min_wan"
        ),
        "budget_max_wan": item.get(
            "budget_max_wan"
        ),
    }


def rerank_results(
    intent: str,
    user_message: str,
    candidates: list[dict],
    top_n: int = 10,
) -> list[dict]:

    if not candidates:
        return []

    top_n = min(max(top_n, 1), 10)

    # 最多送20条给模型，控制上下文长度
    candidates = candidates[:20]

    if intent == "search_achievement":
        llm_candidates = [
            _achievement_for_llm(item)
            for item in candidates
        ]

    elif intent == "search_demand":
        llm_candidates = [
            _demand_for_llm(item)
            for item in candidates
        ]

    else:
        return candidates[:top_n]

    user_content = {
        "user_query": user_message,
        "candidate_type": intent,
        "candidates": llm_candidates,
    }

    try:
        parsed = _call_reranker(
            user_content
        )

        rankings = parsed.get(
            "results",
            []
        )

        if not isinstance(rankings, list):
            raise ValueError("重排结果 results 必须是列表")

    except Exception as exc:
        print(
            "[Reranker Error]",
            repr(exc),
        )

        # 语义重排失败
        return candidates[:top_n]

    candidate_map = {
        str(item["id"]): item
        for item in candidates
        if item.get("id") is not None
    }

    selected_items = []
    used_ids = set()

    for ranking in rankings:

        item_id = str(
            ranking.get("id")
        )

        if item_id not in candidate_map:
            continue

        if item_id in used_ids:
            continue

        original = dict(
            candidate_map[item_id]
        )

        selected_items.append(original)
        used_ids.add(item_id)

        if len(selected_items) >= top_n:
            break

    return selected_items or candidates[:top_n]

def _call_reranker(
    user_content: dict,
) -> dict:

    messages = [
        {
            "role": "system",
            "content": RERANK_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": json.dumps(
                user_content,
                ensure_ascii=False,
                default=str,
            ),
        },
    ]

    try:
        output = chat_completion(
            messages=messages,
            max_tokens=2000,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        return _extract_json(output)

    except Exception as exc:
        first_error = exc

    # 第二次强制 JSON
    retry_messages = [
        {
            "role": "system",
            "content": """
你是一个严格的JSON输出器。

你只能返回：

{
  "results": [
    {
      "id": 123
    }
  ]
}

要求：

只能使用输入候选中真实存在的id。

禁止新增候选。
禁止编造数据。
禁止Markdown。
禁止代码块。
禁止思考过程。
禁止JSON之外的任何内容。
"""
        },
        {
            "role": "user",
            "content": json.dumps(
                user_content,
                ensure_ascii=False,
                default=str,
            ),
        },
    ]

    try:
        retry_output = chat_completion(
            messages=retry_messages,
            max_tokens=2000,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        return _extract_json(retry_output)
    except Exception as exc:
        raise RuntimeError(
            "重排两次调用均失败: "
            f"首次={first_error!r}; 重试={exc!r}"
        ) from exc
