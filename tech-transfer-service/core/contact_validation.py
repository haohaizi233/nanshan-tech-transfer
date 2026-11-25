"""Phone / email format checks shared by profile, publication, and membership flows."""

import re

from core.errors import bad_request

PHONE_PATTERN = re.compile(r"^\d{11}$")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_EMAIL_LOCAL_PATTERN = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$")
_DOMAIN_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
# Institution 联系方式: mobile, landline, or local numbers from crawled sources.
CONTACT_WAY_PATTERN = re.compile(r"^[\d+() （）\s-]{5,32}$")


def normalize_contact(value):
    if value is None:
        return ""
    return str(value).strip()


def _has_unsafe_chars(text: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 or ch.isspace() for ch in text)


def normalize_email(value, *, field_name: str = "邮箱") -> str:
    """规范化并严格校验安全邮箱（保留 +tag 与本地点号，IDN 转 Punycode）。"""
    text = normalize_contact(value)
    if not text:
        raise bad_request(f"请填写{field_name}")
    if len(text) > 254 or _has_unsafe_chars(text) or text.count("@") != 1:
        raise bad_request(f"{field_name}格式不正确")

    local, domain = text.split("@", 1)
    if not local or len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in local:
        raise bad_request(f"{field_name}格式不正确")
    if not _EMAIL_LOCAL_PATTERN.fullmatch(local):
        raise bad_request(f"{field_name}格式不正确")

    if not domain or domain.startswith(".") or domain.endswith(".") or ".." in domain:
        raise bad_request(f"{field_name}格式不正确")
    try:
        ascii_domain = domain.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise bad_request(f"{field_name}格式不正确") from None

    labels = ascii_domain.split(".")
    if len(labels) < 2:
        raise bad_request(f"{field_name}格式不正确")
    if any(not _DOMAIN_LABEL_PATTERN.fullmatch(label) for label in labels):
        raise bad_request(f"{field_name}格式不正确")
    tld = labels[-1]
    if len(tld) < 2 or tld.isdigit():
        raise bad_request(f"{field_name}格式不正确")

    normalized = f"{local.lower()}@{ascii_domain}"
    if len(normalized) > 254:
        raise bad_request(f"{field_name}格式不正确")
    return normalized


def email_domain(normalized_email: str) -> str:
    """提取已规范化邮箱的小写 ASCII 域名。"""
    text = str(normalize_contact(normalized_email))
    if "@" not in text:
        return ""
    return text.rsplit("@", 1)[-1].lower()


def is_valid_phone(value) -> bool:
    text = normalize_contact(value)
    return bool(text) and bool(PHONE_PATTERN.fullmatch(text))


def is_valid_email(value) -> bool:
    text = normalize_contact(value)
    if not text or len(text) > 254 or _has_unsafe_chars(text) or ".." in text:
        return False
    return bool(EMAIL_PATTERN.fullmatch(text))


def is_valid_contact_way(value) -> bool:
    text = normalize_contact(value)
    return bool(text) and bool(CONTACT_WAY_PATTERN.fullmatch(text))


def validate_phone(value, *, required=False, field_name="手机号"):
    text = normalize_contact(value)
    if not text:
        if required:
            raise bad_request(f"请填写{field_name}")
        return None
    if not PHONE_PATTERN.fullmatch(text):
        raise bad_request(f"{field_name}须为11位数字")
    return text


def validate_contact_way(value, *, required=False, field_name="联系方式"):
    text = normalize_contact(value)
    if not text:
        if required:
            raise bad_request(f"请填写{field_name}")
        return ""
    if len(text) > 64:
        raise bad_request(f"{field_name}过长")
    if not CONTACT_WAY_PATTERN.fullmatch(text):
        raise bad_request(f"{field_name}格式不正确")
    return text


def validate_email(value, *, required=False, field_name="邮箱"):
    text = normalize_contact(value)
    if not text:
        if required:
            raise bad_request(f"请填写{field_name}")
        return None
    if not is_valid_email(text):
        raise bad_request(f"{field_name}格式不正确")
    return text
