"""Phone / email format checks shared by profile, publication, and membership flows."""

import re

from core.errors import bad_request

PHONE_PATTERN = re.compile(r"^\d{11}$")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_contact(value):
    if value is None:
        return ""
    return str(value).strip()


def is_valid_phone(value) -> bool:
    text = normalize_contact(value)
    return bool(text) and bool(PHONE_PATTERN.fullmatch(text))


def is_valid_email(value) -> bool:
    text = normalize_contact(value)
    return bool(text) and bool(EMAIL_PATTERN.fullmatch(text))


def validate_phone(value, *, required=False, field_name="手机号"):
    text = normalize_contact(value)
    if not text:
        if required:
            raise bad_request(f"请填写{field_name}")
        return None
    if not PHONE_PATTERN.fullmatch(text):
        raise bad_request(f"{field_name}须为11位数字")
    return text


def validate_email(value, *, required=False, field_name="邮箱"):
    text = normalize_contact(value)
    if not text:
        if required:
            raise bad_request(f"请填写{field_name}")
        return None
    if not EMAIL_PATTERN.fullmatch(text):
        raise bad_request(f"{field_name}格式不正确")
    return text
