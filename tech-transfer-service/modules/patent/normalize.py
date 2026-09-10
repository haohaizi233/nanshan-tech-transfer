"""把上游专利检索结果收成对外契约，并去掉源站痕迹。"""

from __future__ import annotations

import html
import math
import re

# 对外禁止出现的源站域名/路径片段（大小写不敏感）
_LEAK_MARKERS = (
    "googleapis.com",
    "googleusercontent.com",
    "patents.google",
    "patentimages.storage",
    "google.com/patents",
    "google.com/patent",
)

_DROP_KEYS = {
    "pdf_url",
    "thumbnail",
    "patent_id",
    "patentId",
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SOURCE_URL_RE = re.compile(
    r"https?://[^\s\"'<>]*(?:googleapis|googleusercontent|patents\.google|patentimages\.storage|google\.com/patent)[^\s\"'<>]*",
    re.IGNORECASE,
)
_PUB_NO_RE = re.compile(r"^[A-Za-z]{1,4}[\d.]{4,24}[A-Za-z]?$", re.IGNORECASE)


def is_publication_no(value: str) -> bool:
    text = (value or "").strip()
    return bool(text) and bool(_PUB_NO_RE.match(text)) and len(text) <= 32


def clean_text(value) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = _HTML_TAG_RE.sub("", text)
    text = _SOURCE_URL_RE.sub("", text)
    return " ".join(text.split()).strip()


def clean_multiline(value) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = _HTML_TAG_RE.sub("", text)
    text = _SOURCE_URL_RE.sub("", text)
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(lines).strip()


def clean_date(value) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    return text[:10]


def infer_patent_type(publication_no: str) -> str:
    pub = (publication_no or "").strip().upper()
    if pub.endswith("U") or pub.endswith("Y"):
        return "utility_model"
    if pub.endswith("S") or pub.endswith("D"):
        return "design"
    return "invention"


def contains_source_leak(value) -> bool:
    blob = str(value or "").lower()
    return any(marker in blob for marker in _LEAK_MARKERS)


def assert_no_source_leak(payload) -> None:
    """测试与出站前扫描：任何谷歌源站痕迹都视为实现错误。"""
    stack = [payload]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for key, val in cur.items():
                if str(key) in _DROP_KEYS or contains_source_leak(key):
                    raise ValueError(f"outbound leak key: {key}")
                stack.append(val)
        elif isinstance(cur, (list, tuple)):
            stack.extend(cur)
        elif contains_source_leak(cur):
            raise ValueError("outbound leak in value")


def map_search_hit(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    publication_no = clean_text(raw.get("pub_number") or raw.get("number") or "")
    if not publication_no:
        return None
    title = clean_text(raw.get("title"))
    snippet = clean_text(raw.get("snippet"))
    item = {
        "publicationNo": publication_no,
        "title": title,
        "snippet": snippet,
        "applicant": clean_text(raw.get("assignee")),
        "inventor": clean_text(raw.get("inventor")),
        "priorityDate": clean_date(raw.get("priority_date")),
        "applyDate": clean_date(raw.get("filing_date")),
        "publicationDate": clean_date(raw.get("publication_date")),
        "grantDate": clean_date(raw.get("grant_date")),
        "patentType": infer_patent_type(publication_no),
        "language": clean_text(raw.get("language"))[:8],
        "hasPdf": bool(str(raw.get("pdf_url") or "").strip()),
    }
    assert_no_source_leak(item)
    return item


def map_patent_info(raw: dict, publication_no: str, bibliographic: dict | None = None) -> dict:
    info = raw if isinstance(raw, dict) else {}
    number = clean_text(info.get("number") or publication_no)
    mapped = dict(bibliographic or {})
    mapped.update({
        "publicationNo": number or publication_no,
        "title": clean_text(info.get("title")) or mapped.get("title") or "",
        "abstract": clean_multiline(info.get("abstract")),
        "description": clean_multiline(info.get("description")),
        "claims": clean_multiline(info.get("claims")),
        "patentType": mapped.get("patentType") or infer_patent_type(number or publication_no),
    })
    mapped.setdefault("snippet", "")
    mapped.setdefault("applicant", "")
    mapped.setdefault("inventor", "")
    mapped.setdefault("priorityDate", None)
    mapped.setdefault("applyDate", None)
    mapped.setdefault("publicationDate", None)
    mapped.setdefault("grantDate", None)
    mapped.setdefault("language", "")
    mapped.setdefault("hasPdf", True)
    assert_no_source_leak(mapped)
    return mapped


def page_meta(total: int, page: int, page_size: int) -> dict:
    total = max(0, int(total or 0))
    page = max(1, int(page or 1))
    page_size = max(1, min(50, int(page_size or 10)))
    total_pages = math.ceil(total / page_size) if total else 0
    return {
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": total_pages,
    }
