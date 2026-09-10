"""外部专利检索 Provider。密钥与源站 URL 只留在服务端。"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator

from config import settings
from core.errors import patent_unavailable

logger = logging.getLogger("nanshan.error")

JsonFetcher = Callable[[str, dict, int], dict]


def _configured() -> bool:
    return bool(settings.PATENT_PROVIDER_BASE.strip() and settings.PATENT_PROVIDER_KEY.strip())


def _build_url(path: str, params: dict) -> str:
    base = settings.PATENT_PROVIDER_BASE.rstrip("/")
    query = dict(params)
    query["key"] = settings.PATENT_PROVIDER_KEY
    return f"{base}{path}?{urllib.parse.urlencode(query)}"


def _http_json(path: str, params: dict, timeout: int) -> dict:
    url = _build_url(path, params)
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "nanshan-tech-transfer/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        logger.warning("patent provider http error path=%s status=%s", path, exc.code)
        if exc.code == 404:
            return {}
        raise patent_unavailable() from None
    except Exception as exc:
        logger.warning("patent provider fetch failed path=%s err=%r", path, exc)
        raise patent_unavailable() from None

    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("patent provider returned non-json path=%s", path)
        raise patent_unavailable() from None
    return data if isinstance(data, dict) else {}


def search_raw(
    *,
    keyword: str,
    assignee: str,
    page: int,
    page_size: int,
    fetcher: JsonFetcher | None = None,
) -> dict:
    if not _configured() and fetcher is None:
        raise patent_unavailable()
    fetch = fetcher or _http_json
    return fetch(
        "/patent_search",
        {
            "q": keyword,
            "assignee": assignee,
            "num": page_size,
            "page": max(0, page - 1),
        },
        settings.PATENT_PROVIDER_TIMEOUT,
    )


def info_raw(publication_no: str, fetcher: JsonFetcher | None = None) -> dict:
    if not _configured() and fetcher is None:
        raise patent_unavailable()
    fetch = fetcher or _http_json
    return fetch(
        "/patent_info",
        {"query": publication_no},
        settings.PATENT_PROVIDER_TIMEOUT,
    )


def iter_pdf_bytes(publication_no: str) -> Iterator[bytes]:
    if not _configured():
        raise patent_unavailable()
    url = _build_url("/patent_pdf", {"query": publication_no})
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/pdf,*/*",
            "User-Agent": "nanshan-tech-transfer/1.0",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=settings.PATENT_PDF_TIMEOUT)
    except urllib.error.HTTPError as exc:
        logger.warning("patent pdf http error pub=%s status=%s", publication_no, exc.code)
        if exc.code == 404:
            from core.errors import patent_not_found
            raise patent_not_found() from None
        raise patent_unavailable() from None
    except Exception as exc:
        logger.warning("patent pdf fetch failed pub=%s err=%r", publication_no, exc)
        raise patent_unavailable() from None

    content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if content_type and "pdf" not in content_type and "octet-stream" not in content_type:
        resp.close()
        logger.warning("patent pdf unexpected content-type=%s pub=%s", content_type, publication_no)
        raise patent_unavailable()

    try:
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            yield chunk
    finally:
        resp.close()
