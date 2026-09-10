"""patent service —— 检索 / 详情 / PDF 代理。"""

from __future__ import annotations

from collections.abc import Iterator

from core.errors import bad_request, patent_not_found
from modules.patent import provider
from modules.patent.normalize import (
    is_publication_no,
    map_patent_info,
    map_search_hit,
    page_meta,
)


def _require_query(keyword: str, assignee: str) -> None:
    if not keyword and not assignee:
        raise bad_request("keyword 与 assignee 至少填写一项")
    if len(keyword) > 64:
        raise bad_request("keyword 长度不能超过 64")
    if len(assignee) > 64:
        raise bad_request("assignee 长度不能超过 64")


def search_patents(keyword: str, assignee: str, page: int, page_size: int, fetcher=None) -> dict:
    keyword = (keyword or "").strip()
    assignee = (assignee or "").strip()
    _require_query(keyword, assignee)

    raw = provider.search_raw(
        keyword=keyword,
        assignee=assignee,
        page=page,
        page_size=page_size,
        fetcher=fetcher,
    )
    hits = raw.get("results") if isinstance(raw, dict) else None
    items = []
    if isinstance(hits, list):
        for row in hits:
            mapped = map_search_hit(row)
            if mapped:
                items.append(mapped)
                if len(items) >= page_size:
                    break
    total = raw.get("total") if isinstance(raw, dict) else 0
    try:
        total = int(total or 0)
    except (TypeError, ValueError):
        total = len(items)
    meta = page_meta(total, page, page_size)
    meta["list"] = items
    return meta


def get_patent(publication_no: str, fetcher=None) -> dict:
    pub = (publication_no or "").strip()
    if not is_publication_no(pub):
        raise bad_request("专利公开号无效")

    info = provider.info_raw(pub, fetcher=fetcher)
    has_parsed = isinstance(info, dict) and any(
        info.get(key) for key in ("title", "abstract", "description", "claims", "number")
    )
    if not has_parsed:
        raise patent_not_found()
    return map_patent_info(info, pub, None)


def iter_patent_pdf(publication_no: str) -> Iterator[bytes]:
    pub = (publication_no or "").strip()
    if not is_publication_no(pub):
        raise bad_request("专利公开号无效")
    return provider.iter_pdf_bytes(pub)
