"""Bound finite slot counts before converting or persisting them."""

from decimal import Decimal, InvalidOperation

from core.errors import bad_request

MAX_COOPERATION_CAPACITY = 9999


def normalize_cooperation_capacity(value):
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise bad_request("cooperationCapacity 必须是正整数或空（不限量）")
    if not number.is_finite() or number != number.to_integral_value():
        raise bad_request("cooperationCapacity 必须是正整数或空（不限量）")
    if number < 1:
        raise bad_request("cooperationCapacity 必须大于 0")
    if number > MAX_COOPERATION_CAPACITY:
        return None
    return int(number)
