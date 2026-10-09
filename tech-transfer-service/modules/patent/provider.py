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
from core.errors import BizError, TT_COMMON_42901, patent_provider_failed, patent_unavailable

logger = logging.getLogger("nanshan.error")

JsonFetcher = Callable[[str, dict, int], dict]

# 上游偶发 429/502/503/504 或网络抖动时短暂重试，避免一次失败就把检索打成 503。
_RETRY_STATUS = {429, 502, 503, 504}
_RETRY_TIMES = 3
_RETRY_BACKOFF = (0.3, 0.8, 1.6)
_UPSTREAM_BODY_LIMIT = 300


def _configured() -> bool:
    return bool(settings.PATENT_PROVIDER_BASE.strip() and settings.PATENT_PROVIDER_KEY.strip())


def _provider_key() -> str:
    return settings.PATENT_PROVIDER_KEY.strip()


def _build_url(path: str, params: dict) -> str:
    base = settings.PATENT_PROVIDER_BASE.rstrip("/")
    query = dict(params)
    # 上游 FastAPI 把 key 声明为必填 query 参数；只发 Authorization 会 422，
    # 再被映射成 TT_PATENT_50201。Bearer 头一并带上，便于后续源站切鉴权。
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


def _read_http_error_body(exc: urllib.error.HTTPError, limit: int = _UPSTREAM_BODY_LIMIT) -> str:
    try:
        return exc.read(limit).decode("utf-8", "replace")
    except Exception:
        return ""


def _safe_snippet(text: str, limit: int = _UPSTREAM_BODY_LIMIT) -> str:
    text = (text or "").replace("\r\n", "\n").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _network_reason(exc: BaseException) -> str:
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        name = type(cur).__name__
        text = str(cur).lower()
        if isinstance(cur, TimeoutError) or name in {"TimeoutError", "ReadTimeoutError"}:
            return "timeout"
        if "timed out" in text:
            return "timeout"
        if name in {"RemoteDisconnected", "ConnectionResetError"} or (
            "closed connection" in text or "connection reset" in text or "disconnected" in text
        ):
            return "connection_reset"
        if name == "ConnectionRefusedError" or "refused" in text:
            return "connection_refused"
        nxt = None
        if isinstance(cur, urllib.error.URLError) and not isinstance(cur, urllib.error.HTTPError):
            reason = getattr(cur, "reason", None)
            if isinstance(reason, BaseException):
                nxt = reason
        cur = nxt or cur.__cause__
    return "unreachable"


def _raise_from_http(path: str, status: int, body: str) -> None:
    details = {
        "layer": "provider",
        "providerStatus": status,
        "reason": "http_error",
    }
    if body:
        details["upstreamBody"] = _safe_snippet(body)
    logger.warning(
        "patent provider http error path=%s status=%s body=%s",
        path, status, details.get("upstreamBody"),
    )
    if status == 429:
        code, _message, http_status = TT_COMMON_42901
        raise BizError(code, "专利查询过于频繁，请稍后重试", http_status, details)
    raise patent_provider_failed("专利查询上游调用失败", details)


def _raise_from_network(path: str, exc: Exception) -> None:
    reason = _network_reason(exc)
    details = {"layer": "provider", "reason": reason}
    logger.warning("patent provider fetch failed path=%s reason=%s err=%r", path, reason, exc)
    raise patent_unavailable("专利查询服务不可用", details)


def _not_configured() -> None:
    raise patent_unavailable(
        "专利查询服务不可用",
        {"layer": "local", "reason": "not_configured"},
    )


def _http_json(path: str, params: dict, timeout: int) -> dict:
    url = _build_url(path, params)
    req = urllib.request.Request(url, headers=_auth_headers())
    raw = b""
    last_exc: Exception | None = None
    last_http: tuple[int, str] | None = None
    for attempt in range(_RETRY_TIMES):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            break
        except urllib.error.HTTPError as exc:
            last_exc = exc
            body = _read_http_error_body(exc)
            last_http = (exc.code, body)
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
            _raise_from_http(path, exc.code, body)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "patent provider fetch failed path=%s attempt=%s err=%r",
                path, attempt + 1, exc,
            )
            if attempt < _RETRY_TIMES - 1:
                time.sleep(_RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)])
                continue
            _raise_from_network(path, exc)
    else:
        logger.warning("patent provider fetch failed path=%s err=%r", path, last_exc)
        if last_http is not None:
            _raise_from_http(path, last_http[0], last_http[1])
        if last_exc is not None:
            _raise_from_network(path, last_exc)
        raise patent_unavailable(
            "专利查询服务不可用",
            {"layer": "provider", "reason": "unreachable"},
        )

    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("patent provider returned non-json path=%s", path)
        raise patent_provider_failed(
            "专利查询上游返回格式异常",
            {"layer": "provider", "reason": "invalid_response"},
        ) from None
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
        _not_configured()
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
        _not_configured()
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
        _not_configured()
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
        _raise_from_http("/patent_pdf", exc.code, body)
    except Exception as exc:
        logger.warning("patent pdf fetch failed pub=%s err=%r", publication_no, exc)
        _raise_from_network("/patent_pdf", exc)

    content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if content_type and "pdf" not in content_type and "octet-stream" not in content_type:
        resp.close()
        logger.warning("patent pdf unexpected content-type=%s pub=%s", content_type, publication_no)
        raise patent_provider_failed(
            "专利查询上游返回格式异常",
            {"layer": "provider", "reason": "invalid_content_type"},
        )

    try:
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            yield chunk
    finally:
        resp.close()
