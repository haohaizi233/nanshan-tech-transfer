"""patent service —— 检索 / 详情 / PDF 代理。"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from io import BytesIO

from core.errors import BizError, bad_request, patent_not_found, patent_unavailable
from modules.patent import provider
from modules.patent.normalize import (
    is_publication_no,
    map_patent_info,
    map_search_hit,
    page_meta,
)

logger = logging.getLogger("nanshan.error")

_PDF_CACHE_TTL = 3600
_PDF_CACHE_MAX = 8
_PDF_MAX_BYTES = 30 * 1024 * 1024
_PAGE_CACHE_MAX = 64
_RENDER_SCALE = 2.0

_pdf_cache: dict[str, tuple[bytes, float]] = {}
_page_cache: dict[tuple[str, int], bytes] = {}
_cache_lock = threading.Lock()


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


def get_patent(publication_no: str, language: str = "", fetcher=None) -> dict:
    pub = (publication_no or "").strip()
    if not is_publication_no(pub):
        raise bad_request("专利公开号无效")

    language = (language or "").strip()[:8]
    info = provider.info_raw(pub, language=language, fetcher=fetcher)
    has_parsed = isinstance(info, dict) and any(
        info.get(key) for key in ("title", "abstract", "description", "claims", "number")
    )
    if not has_parsed:
        raise patent_not_found()
    detail = map_patent_info(info, pub, None)
    if language:
        detail["language"] = language
    return detail


def iter_patent_pdf(publication_no: str) -> Iterator[bytes]:
    return provider.iter_pdf_bytes(_require_pub(publication_no))


def clear_pdf_preview_cache() -> None:
    with _cache_lock:
        _pdf_cache.clear()
        _page_cache.clear()


def get_patent_pdf_pages_meta(publication_no: str) -> dict:
    pub = _require_pub(publication_no)
    data = _pdf_bytes(pub)
    return {"pageCount": _pdf_page_count(pub, data)}


def render_patent_pdf_page(publication_no: str, page: int) -> bytes:
    pub = _require_pub(publication_no)
    if page < 1:
        raise bad_request("页码无效")
    with _cache_lock:
        cached = _page_cache.get((pub, page))
    if cached:
        return cached

    data = _pdf_bytes(pub)
    png = _render_page(pub, data, page)
    with _cache_lock:
        if len(_page_cache) >= _PAGE_CACHE_MAX:
            _page_cache.pop(next(iter(_page_cache)))
        _page_cache[(pub, page)] = png
    return png


def _require_pub(publication_no: str) -> str:
    pub = (publication_no or "").strip()
    if not is_publication_no(pub):
        raise bad_request("专利公开号无效")
    return pub


def _pdf_bytes(pub: str) -> bytes:
    now = time.monotonic()
    with _cache_lock:
        hit = _pdf_cache.get(pub)
        if hit and hit[1] > now:
            return hit[0]

    chunks: list[bytes] = []
    total = 0
    for chunk in provider.iter_pdf_bytes(pub):
        if not chunk:
            continue
        total += len(chunk)
        if total > _PDF_MAX_BYTES:
            raise patent_unavailable("说明书文件过大，暂无法预览")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise patent_not_found()

    with _cache_lock:
        if len(_pdf_cache) >= _PDF_CACHE_MAX:
            oldest = min(_pdf_cache, key=lambda key: _pdf_cache[key][1])
            _pdf_cache.pop(oldest, None)
        _pdf_cache[pub] = (data, now + _PDF_CACHE_TTL)
    return data


def _pdfium():
    try:
        import pypdfium2 as pdfium
    except ImportError:
        logger.warning("pypdfium2 is not installed")
        raise patent_unavailable("说明书预览组件未安装，请执行 pip install pypdfium2 Pillow") from None
    return pdfium


def _open_pdf(pub: str, data: bytes):
    pdfium = _pdfium()
    try:
        return pdfium.PdfDocument(data)
    except BizError:
        raise
    except Exception:
        logger.warning("patent pdf open failed pub=%s", pub, exc_info=True)
        raise patent_unavailable() from None


def _pdf_page_count(pub: str, data: bytes) -> int:
    pdf = _open_pdf(pub, data)
    try:
        return len(pdf)
    finally:
        pdf.close()


def _render_page(pub: str, data: bytes, page: int) -> bytes:
    pdf = _open_pdf(pub, data)
    try:
        page_count = len(pdf)
        if page > page_count:
            raise bad_request("页码无效")
        try:
            bitmap = pdf[page - 1].render(scale=_RENDER_SCALE)
            image = bitmap.to_pil()
        except Exception:
            logger.warning("patent pdf render failed pub=%s page=%s", pub, page, exc_info=True)
            raise patent_unavailable() from None
        buf = BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()
    finally:
        pdf.close()
