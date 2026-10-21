"""金额 / 价格区间的确定性解析（Router、Conversation、Reranker 共用）。

存在的理由：金额边界在三个阶段都要被识别，如果各写各的正则，
「软偏好被误当成硬过滤」「区间上下限被反解析」这类问题会反复出现。
这里提供唯一实现，调用方只消费结果，不再各自拼正则。
"""

from __future__ import annotations

import re


_AMOUNT = r"(-?\d+(?:\.\d+)?)\s*(万(?:元)?|亿(?:元)?|元)?"
_MONEY_LABEL = re.compile(r"预算|价格|报价|金额|费用|成本")
_MEASURE_UNIT = re.compile(
    r"帧|微米|纳米|毫米|厘米|米|秒|毫秒|分钟|小时|次|个|件|吨|度|伏|瓦|赫兹|元素|[%％µμ]|[A-Za-z]"
)

# 「取消 / 不限」类指令：命中后对应上下限都要清空。
CANCEL_PATTERN = re.compile(
    r"(?:不限|不限制|取消|去掉|不要限制).{0,6}(?:预算|价格|报价|金额|费用|成本)"
    r"|(?:预算|价格|报价|金额|费用|成本).{0,5}(?:不限|不限制|取消|去掉)"
)


def amount_to_wan(value, unit) -> float:
    """把「数值 + 单位」换算成万元。"""
    number = float(value)
    if number < 0:
        raise ValueError("预算不能为负数")
    if unit and unit.startswith("亿"):
        return number * 10000
    if unit == "元":
        return number * 0.0001
    return number


def _money_match(pattern, text, interval=False):
    for match in re.finditer(pattern, text):
        if _MEASURE_UNIT.match(text[match.end():].lstrip()):
            continue
        has_unit = bool(match[2] or (interval and match[4]))
        prefix = text[:match.start()]
        contextual = bool(
            re.search(r"(?:预算|价格|报价|金额|费用|成本)[^\d，。；;]{0,16}$", prefix)
        )
        if has_unit or contextual or _MONEY_LABEL.search(match[0]):
            return match
    return None


def find_amount_bounds(text: str) -> dict:
    """解析文本中的金额上下限。

    返回：``{"min_wan": float|None, "max_wan": float|None,
    "span_start": int|None, "cancelled": bool}``。

    - ``min_wan`` / ``max_wan``：以万元为单位的硬性上下限；无则 None。
    - ``span_start``：命中区间的起始下标，用于判断该条件是否只是软偏好。
    - ``cancelled``：用户是否显式要求取消金额限制。
    """
    message = text or ""
    result: dict = {"min_wan": None, "max_wan": None, "span_start": None, "cancelled": False}

    if CANCEL_PATTERN.search(message):
        result["cancelled"] = True
        return result

    interval = _money_match(
        _AMOUNT + r"\s*(?:到|至|[-~～—])\s*" + _AMOUNT, message, interval=True
    )
    maximum = _money_match(
        r"(?:不超过|不高于|不大于|最多|最高|上限)(?:改成|改为|调整为|为|是)?\s*" + _AMOUNT, message
    )
    minimum = _money_match(
        r"(?<!不)(?:不少于|不低于|至少|最低|下限(?:为|是)?|高于|超过)\s*" + _AMOUNT, message
    )
    suffix_max = _money_match(_AMOUNT + r"\s*(?:以内|以下|之内|封顶)", message)
    suffix_min = _money_match(_AMOUNT + r"\s*(?:以上|起步)", message)

    if interval:
        result["min_wan"] = amount_to_wan(interval[1], interval[2] or interval[4])
        result["max_wan"] = amount_to_wan(interval[3], interval[4] or interval[2])
        result["span_start"] = interval.start()
        return result

    if maximum or suffix_max:
        match = maximum or suffix_max
        result["max_wan"] = amount_to_wan(match[1], match[2])
        result["span_start"] = match.start()
    if minimum or suffix_min:
        match = minimum or suffix_min
        result["min_wan"] = amount_to_wan(match[1], match[2])
        result["span_start"] = match.start() if result["span_start"] is None else result["span_start"]
    return result


def has_negative_amount(text: str) -> bool:
    return bool(re.search(r"(?:-|负)\s*\d+(?:\.\d+)?\s*(?:万|亿|元)", text or ""))
