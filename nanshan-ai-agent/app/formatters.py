import json
from decimal import Decimal
from typing import Any


MATURITY_MAP = {
    "01_idea": "概念阶段",
    "02_lab": "实验室验证",
    "03_pilot_ready": "中试就绪",
    "04_pilot_done": "中试完成",
    "05_mass_ready": "量产就绪",
    "06_mass_done": "已量产",
}


def empty_text(value: Any) -> str:
    """
    空值统一返回“未填写”
    """
    if value is None:
        return "未填写"

    if isinstance(value, str):
        value = value.strip()
        return value if value else "未填写"

    return str(value)


def number_text(value: Any) -> str | None:
    """
    Decimal / int / float 格式化
    """
    if value is None:
        return None

    if isinstance(value, Decimal):
        value = float(value)

    try:
        value = float(value)

        if value.is_integer():
            return str(int(value))

        return f"{value:g}"

    except (TypeError, ValueError):
        return str(value)


def normalize_list(value: Any) -> list[str]:
    """
    处理 PostgreSQL jsonb 字段。

    可能拿到：
    list
    dict
    JSON字符串
    普通字符串
    """
    if value is None:
        return []

    if isinstance(value, list):
        result = []

        for item in value:
            if isinstance(item, dict):
                # 尽量取常见可读字段
                text = (
                    item.get("name")
                    or item.get("title")
                    or item.get("label")
                    or item.get("content")
                )

                if text:
                    result.append(str(text))
                else:
                    result.append(
                        json.dumps(
                            item,
                            ensure_ascii=False
                        )
                    )

            elif item is not None:
                result.append(str(item))

        return result

    if isinstance(value, dict):
        return [
            json.dumps(
                value,
                ensure_ascii=False
            )
        ]

    if isinstance(value, str):
        value = value.strip()

        if not value:
            return []

        try:
            parsed = json.loads(value)
            return normalize_list(parsed)
        except json.JSONDecodeError:
            return [value]

    return [str(value)]


def mask_name(name: str | None) -> str:
    """
    中文：
    张三 -> 张**

    英文：
    John Smith -> J***
    """
    if not name:
        return "未填写"

    name = name.strip()

    if not name:
        return "未填写"

    # 包含英文字符时按照英文格式处理
    if any(ch.isascii() and ch.isalpha() for ch in name):
        return name[0] + "***"

    return name[0] + "**"


def mask_phone(phone: str | None) -> str:
    """
    13812341234 -> 138****1234
    """
    if not phone:
        return "未填写"

    phone = str(phone).strip()

    if not phone:
        return "未填写"

    if len(phone) >= 7:
        return f"{phone[:3]}****{phone[-4:]}"

    return "***"


def mask_email(email: str | None) -> str:
    """
    zhangsan@example.com
    ->
    z***@example.com
    """
    if not email:
        return "未填写"

    email = email.strip()

    if not email or "@" not in email:
        return "***"

    local, domain = email.split("@", 1)

    if not local:
        return f"***@{domain}"

    return f"{local[0]}***@{domain}"


def format_maturity(
    maturity_level: str | None
) -> dict:
    if not maturity_level:
        return {
            "code": None,
            "label": "未填写",
        }

    return {
        "code": maturity_level,
        "label": MATURITY_MAP.get(
            maturity_level,
            maturity_level,
        ),
    }


def format_achievement_price(
    pricing_mode: str | None,
    price_min: Any,
    price_max: Any,
) -> dict:

    minimum = number_text(price_min)
    maximum = number_text(price_max)

    if pricing_mode == "negotiable":
        text = "面议"

    elif minimum and maximum:

        if minimum == maximum:
            text = f"{minimum}万元"
        else:
            text = f"{minimum} - {maximum}万元"

    elif minimum:
        text = f"{minimum}万元起"

    elif maximum:
        text = f"不高于{maximum}万元"

    else:
        text = "未填写"

    return {
        "mode": pricing_mode,
        "min": minimum,
        "max": maximum,
        "text": text,
    }


def format_demand_budget(
    negotiable: bool | None,
    budget_min: Any,
    budget_max: Any,
) -> dict:

    minimum = number_text(budget_min)
    maximum = number_text(budget_max)

    if negotiable is True:
        text = "面议"

    elif minimum and maximum:

        if minimum == maximum:
            text = f"{minimum}万元"
        else:
            text = f"{minimum} - {maximum}万元"

    elif minimum:
        text = f"{minimum}万元起"

    elif maximum:
        text = f"不高于{maximum}万元"

    else:
        text = "未填写"

    return {
        "negotiable": negotiable,
        "min": minimum,
        "max": maximum,
        "text": text,
    }


def format_contact(item: dict) -> dict:
    return {
        "name": mask_name(
            item.get("contact_name")
        ),
        "phone": mask_phone(
            item.get("contact_phone")
        ),
        "email": mask_email(
            item.get("contact_email")
        ),
    }


def format_achievement_card(
    item: dict
) -> dict:

    application_fields = normalize_list(
        item.get("application_fields")
    )

    return {
        "card_type": "achievement",
        "viewCount": int(item.get("view_count") or 0),

        "id": item.get("id"),

        "title": empty_text(
            item.get("title")
        ),

        "organization": empty_text(
            item.get("source_org_name")
        ),

        "description": empty_text(
            item.get("tech_intro")
        ),

        "maturity": format_maturity(
            item.get("maturity_level")
        ),

        "price": format_achievement_price(
            item.get("pricing_mode"),
            item.get("price_min_wan"),
            item.get("price_max_wan"),
        ),

        "application_fields": (
            application_fields
            if application_fields
            else ["未填写"]
        ),

        "contact": format_contact(item),

    }


def format_demand_card(
    item: dict
) -> dict:

    coop_mode = normalize_list(
        item.get("coop_mode")
    )

    return {
        "card_type": "demand",
        "viewCount": int(item.get("view_count") or 0),

        "id": item.get("id"),

        "title": empty_text(
            item.get("title")
        ),

        "organization": empty_text(
            item.get("org_name_snapshot")
        ),

        "description": empty_text(
            item.get("description")
        ),

        "region": empty_text(
            item.get("region")
        ),

        "budget": format_demand_budget(
            item.get("budget_negotiable"),
            item.get("budget_min_wan"),
            item.get("budget_max_wan"),
        ),

        "coop_mode": (
            coop_mode
            if coop_mode
            else ["未填写"]
        ),

        "contact": format_contact(item),

    }
