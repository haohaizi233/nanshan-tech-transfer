"""AI 全链路数据分级与隐私脱敏契约（与主服务 extract.strip_private_contact_text 保持语义一致）。

数据分类策略：
- PUBLIC: 已发布成果/需求公开正文、官网链接、专利号、技术参数、价格区间
- AUTHENTICATED: 登录态下可浏览的脱敏摘要、个人收藏
- OWNER_ONLY: 草稿/未发布/已下架成果或需求（仅所有者可评估或引用）
- COOPERATION_AUTHORIZED: 对接双方授权后可见的真实联系方式
- ADMIN_ONLY: 后台审核、风控状态、审计日志
- SECRET: 手机/邮箱明文、私人微信号、OTP、JWT、API Key、恢复链接 Token、内部 DB DSN
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class DataClassification(str, Enum):
    PUBLIC = "PUBLIC"
    AUTHENTICATED = "AUTHENTICATED"
    OWNER_ONLY = "OWNER_ONLY"
    COOPERATION_AUTHORIZED = "COOPERATION_AUTHORIZED"
    ADMIN_ONLY = "ADMIN_ONLY"
    SECRET = "SECRET"


_LABEL_RE = re.compile(r"^\s*([^:：]{1,32})\s*[:：]\s*(.*)$")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

_PRIVATE_CONTACT_LABELS = frozenset(
    {
        "联系人",
        "联系人姓名",
        "对接人",
        "团队负责人",
        "负责人",
        "联系电话",
        "电话",
        "手机",
        "手机号",
        "联系邮箱",
        "邮箱",
        "电子邮箱",
        "Email",
        "微信",
        "微信号",
    }
)
_WECHAT_LABELS = frozenset({"微信", "微信号"})
_CONTACT_LABEL_RE = re.compile(
    r"^\s*(?:联系方式|联络方式|联系号码|手机号码|电子邮件|座机|微信ID)\s*(?:[:：]\s*(.*))?$",
    re.I,
)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._\-+/=]{12,}", re.I)
_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "auth",
        "secret",
        "key",
        "api_key",
        "apikey",
        "code",
        "signature",
        "sig",
        "password",
        "passwd",
        "pwd",
        "reset_token",
        "ticket",
        "session",
        "session_id",
        "sid",
        "otp",
    }
)
_SENSITIVE_QUERY_SUFFIXES = ("_token", "_secret", "_key", "_password", "_passwd")
_PUBLIC_TEXT_CONTACT_RE = re.compile(
    r"(?P<url>https?://[^\s<>，。；！？、（）【】《》]+)"
    r"|(?:mailto:)?(?:" + _EMAIL_RE.pattern + r")"
    r"|(?:微信号|微信\s*ID|WeChat)\s*[:：]\s*[A-Za-z][A-Za-z0-9_-]{2,}"
    r"|(?:tel:)?(?<!\d)(?:(?:\+?86)[ \t-]*)?1[3-9](?:[ \t-]*\d){9}(?!\d)"
    r"|(?<!\d)(?:\(0\d{2,3}\)|（0\d{2,3}）|0\d{2,3}-)[ \t]*\d{7,8}(?!\d)",
    re.I,
)
_CONTACT_VALUE_LINE_RE = re.compile(r"[\s\d+*()（）-]{5,}")


def _clean_label(label: str) -> str:
    return re.sub(r"[\s（）()【】\[\]-]", "", label or "")


_CLEANED_PRIVATE_LABELS = {_clean_label(name): name for name in _PRIVATE_CONTACT_LABELS}
_CLEANED_WECHAT_LABELS = {_clean_label(name) for name in _WECHAT_LABELS}


def _parse_labeled_line(line: str) -> tuple[str | None, str]:
    text = (line or "").strip()
    if not text:
        return None, ""
    matched = _LABEL_RE.match(text)
    if matched:
        cleaned = _clean_label(matched.group(1))
        return _CLEANED_PRIVATE_LABELS.get(cleaned), matched.group(2).strip()
    cleaned = _clean_label(text)
    return _CLEANED_PRIVATE_LABELS.get(cleaned), ""


def _is_sensitive_query_key(name: str) -> bool:
    lower = (name or "").strip().lower()
    return lower in _SENSITIVE_QUERY_KEYS or lower.endswith(_SENSITIVE_QUERY_SUFFIXES)


def _sanitize_url(url: str) -> str:
    """保留公开 URL 主体与非敏感查询参数，剥离 URL 内的账号凭据与认证 Token 参数。"""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    netloc = parts.netloc
    if "@" in netloc:
        netloc = netloc.rsplit("@", 1)[-1]
    query = parts.query
    if query:
        kept_params = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True) if not _is_sensitive_query_key(k)]
        query = urlencode(kept_params, doseq=True)
    fragment = parts.fragment
    if fragment and any(tok in fragment.lower() for tok in ("token=", "secret=", "password=", "auth=")):
        fragment = ""
    return urlunsplit((parts.scheme, netloc, parts.path, query, fragment))


def strip_private_contact_text(text: str | None) -> str | None:
    """剥离正文中的私人手机号、座机、邮箱、微信号、JWT/Bearer 与敏感 URL 参数。"""
    if not text:
        return text

    kept: list[str] = []
    pending_wechat = False
    pending_contact = False
    for line in text.splitlines():
        if not line.strip():
            kept.append(line)
            continue
        label, value = _parse_labeled_line(line)
        extra_label = _CONTACT_LABEL_RE.fullmatch(line)
        if label is not None or extra_label:
            has_value = value if label is not None else extra_label.group(1)
            pending_contact = not bool(has_value)
            pending_wechat = bool(pending_contact and label is not None and _clean_label(label) in _CLEANED_WECHAT_LABELS)
            continue
        if pending_contact and (
            _CONTACT_VALUE_LINE_RE.fullmatch(line)
            or (pending_wechat and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{2,}", line.strip()))
        ):
            pending_contact = False
            pending_wechat = False
            continue
        pending_contact = False
        pending_wechat = False
        cleaned = _PUBLIC_TEXT_CONTACT_RE.sub(lambda m: _sanitize_url(m.group("url")) if m.group("url") else "", line)
        cleaned = _JWT_RE.sub("[REDACTED]", cleaned)
        cleaned = _BEARER_RE.sub("[REDACTED]", cleaned)
        if cleaned == line or cleaned.strip(" \t:：,，.;；。/、"):
            kept.append(cleaned.rstrip())

    return "\n".join(kept).strip()


def sanitize_text_for_llm(value: Any, max_length: int | None = None) -> str:
    """将任意文本/字段值脱敏后供 LLM 输入或检索引用使用。"""
    if value is None:
        return ""
    cleaned = strip_private_contact_text(str(value)) or ""
    cleaned = cleaned.strip()
    if max_length is not None and len(cleaned) > max_length:
        return cleaned[:max_length] + "..."
    return cleaned


def sanitize_list_for_llm(value: Any, *, max_items: int = 6, item_max_len: int = 80) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = sanitize_text_for_llm(value, item_max_len)
        return [cleaned] if cleaned else []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            cleaned = sanitize_text_for_llm(item, item_max_len)
            if cleaned:
                out.append(cleaned)
            if len(out) >= max_items:
                break
        return out
    return []


def sanitize_history_messages(history: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """清洗多轮历史上下文，防止历史消息中的敏感信息进入后续模型请求。"""
    if not history:
        return []
    sanitized: list[dict[str, Any]] = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        item = dict(entry)
        for key in ("content", "message", "reply", "text"):
            if isinstance(item.get(key), str):
                item[key] = sanitize_text_for_llm(item[key])
        sanitized.append(item)
    return sanitized
