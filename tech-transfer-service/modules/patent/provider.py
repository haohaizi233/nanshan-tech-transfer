"""外部专利检索 Provider。密钥与源站 URL 只留在服务端。"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator

from config import settings
from core.errors import patent_unavailable

logger = logging.getLogger("nanshan.error")

JsonFetcher = Callable[[str, dict, int], dict]

# 上游偶发 429/502/503/504 或网络抖动时短暂重试，避免一次失败就把检索打成 503。
_RETRY_STATUS = {429, 502, 503, 504}
_RETRY_TIMES = 3
_RETRY_BACKOFF = (0.3, 0.8, 1.6)


def _configured() -> bool:
    return bool(settings.PATENT_PROVIDER_BASE.strip() and settings.PATENT_PROVIDER_KEY.strip())


def _provider_key() -> str:
    return settings.PATENT_PROVIDER_KEY.strip()


def _build_url(path: str, params: dict) -> str:
    base = settings.PATENT_PROVIDER_BASE.rstrip("/")
    query = dict(params)
    # 上游 FastAPI 把 key 声明为必填 query 参数；只发 Authorization 会 422，
    # 再被映射成 TT_PATENT_50301。Bearer 头一并带上，便于后续源站切鉴权。
    key = _provider_key()
    if key:
        query["key"] = key
    return f"{base}{path}?{urllib.parse.urlencode(query)}"


def _auth_headers(*, accept: str = "application/json") -> dict:
    headers = {
        "Accept": accept,
        "User-Agent": "nanshan-tech-transfer/1.0",
    }
    key = _provider_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _read_http_error_body(exc: urllib.error.HTTPError, limit: int = 300) -> str:
    try:
        return exc.read(limit).decode("utf-8", "replace")
    except Exception:
        return ""


def _http_json(path: str, params: dict, timeout: int) -> dict:
    url = _build_url(path, params)
    req = urllib.request.Request(url, headers=_auth_headers())
    raw = b""
    last_exc: Exception | None = None
    for attempt in range(_RETRY_TIMES):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            break
        except urllib.error.HTTPError as exc:
            last_exc = exc
            body = _read_http_error_body(exc)
            if exc.code == 404:
                return {}
            retryable = exc.code in _RETRY_STATUS and attempt < _RETRY_TIMES - 1
            logger.warning(
                "patent provider http error path=%s status=%s attempt=%s body=%s",
                path, exc.code, attempt + 1, body,
            )
            if retryable:
                time.sleep(_RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)])
                continue
            raise patent_unavailable() from None
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "patent provider fetch failed path=%s attempt=%s err=%r",
                path, attempt + 1, exc,
            )
            if attempt < _RETRY_TIMES - 1:
                time.sleep(_RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)])
                continue
            raise patent_unavailable() from None
    else:
        logger.warning("patent provider fetch failed path=%s err=%r", path, last_exc)
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


def info_raw(publication_no: str, language: str = "", fetcher: JsonFetcher | None = None) -> dict:
    if not _configured() and fetcher is None:
        raise patent_unavailable()
    fetch = fetcher or _http_json
    params = {"query": publication_no}
    if language:
        params["language"] = language
    return fetch(
        "/patent_info",
        params,
        settings.PATENT_PROVIDER_TIMEOUT,
    )


def iter_pdf_bytes(publication_no: str) -> Iterator[bytes]:
    if not _configured():
        raise patent_unavailable()
    url = _build_url("/patent_pdf", {"query": publication_no})
    req = urllib.request.Request(url, headers=_auth_headers(accept="application/pdf,*/*"))
    try:
        resp = urllib.request.urlopen(req, timeout=settings.PATENT_PDF_TIMEOUT)
    except urllib.error.HTTPError as exc:
        body = _read_http_error_body(exc)
        logger.warning(
            "patent pdf http error pub=%s status=%s body=%s",
            publication_no, exc.code, body,
        )
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
