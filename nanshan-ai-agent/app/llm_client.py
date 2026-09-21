import time

import requests

from app.config import settings


class LLMError(Exception):
    pass


# 网关偶发 502/503/429 时重试：远端 LLM 网关在模型冷启动 / 并发时会短暂返回 502，
# 单次失败不代表模型不可用，退避重试可把瞬时抖动吸收掉，避免向业务层抛 502。
_RETRY_STATUS = {502, 503, 504, 429}
_RETRY_TIMES = 3
_RETRY_BACKOFF = (1.0, 2.0, 4.0)
_UPSTREAM_BODY_LIMIT = 800


def _snippet(text: str, limit: int = _UPSTREAM_BODY_LIMIT) -> str:
    text = (text or "").replace("\r\n", "\n").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _log_upstream_error(response, attempt: int) -> str:
    """把远端 LLM 网关的原始回包打到控制台，不向业务层透传。"""
    content_type = ""
    body = ""
    if response is not None:
        content_type = response.headers.get("Content-Type", "")
        try:
            body = response.text or ""
        except Exception:
            body = ""
    snippet = _snippet(body)
    print(
        f"[LLM] upstream HTTP {getattr(response, 'status_code', '?')} "
        f"attempt={attempt + 1}/{_RETRY_TIMES} "
        f"content_type={content_type!r} "
        f"body_len={len(body)} "
        f"body={snippet!r}"
    )
    return snippet


def chat_completion(
    messages: list[dict],
    max_tokens: int = 500,
    temperature: float = 0.1,
    response_format: dict | None = None,
    timeout: int = 60,
) -> str:
    """
    调用公司内部 Qwen Chat Completions API。
    """

    payload = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    if response_format:
        payload["response_format"] = response_format

    headers = {
        "Content-Type": "application/json",
        "x-api-key": settings.LLM_API_KEY,
    }

    response = None
    last_exc: requests.RequestException | None = None
    last_upstream = ""
    for attempt in range(_RETRY_TIMES):
        try:
            response = requests.post(
                settings.LLM_API_URL,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            # 网关瞬时错误（502/503/504/429）退避重试；其余 4xx/5xx 直接抛出
            if response.status_code >= 400:
                last_upstream = _log_upstream_error(response, attempt)
            if response.status_code in _RETRY_STATUS and attempt < _RETRY_TIMES - 1:
                time.sleep(_RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)])
                continue
            response.raise_for_status()
            break
        except requests.RequestException as exc:
            last_exc = exc
            if response is None:
                print(f"[LLM] 请求异常 attempt={attempt + 1}/{_RETRY_TIMES} err={exc!r}")
            if attempt < _RETRY_TIMES - 1:
                time.sleep(_RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)])
                continue
            extra = f" upstream={last_upstream!r}" if last_upstream else ""
            raise LLMError(f"调用大模型接口失败: {exc}{extra}") from exc

    if response is None:
        raise LLMError(f"调用大模型接口失败: {last_exc}")

    try:
        result = response.json()

        return result["choices"][0]["message"]["content"]

    except (
        ValueError,
        KeyError,
        IndexError,
        TypeError,
    ) as exc:
        raise LLMError(
            f"大模型返回格式异常: {response.text[:500]}"
        ) from exc
