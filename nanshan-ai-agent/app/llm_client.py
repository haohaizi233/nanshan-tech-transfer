import json
import logging
import random
import re
import threading
import time

import requests

from app.config import settings
from app.llm_log import enqueue_llm_log, parse_error_fields
from app.runtime_budget import remaining_seconds


class LLMError(Exception):
    """上层模型调用失败。status_code 为网关 HTTP 状态；无 HTTP 回包时为 None。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str = "",
        reason: str = "unreachable",
    ):
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.reason = reason


# 网关偶发 502/503/429 时重试：远端 LLM 网关在模型冷启动 / 并发时会短暂返回 502，
# 单次失败不代表模型不可用，退避重试可把瞬时抖动吸收掉。
_RETRY_STATUS = {502, 503, 504, 429}
_RETRY_TIMES = 2
_RETRY_BACKOFF = (0.25, 0.5)
_UPSTREAM_BODY_LIMIT = 800
_LLM_SLOTS = threading.BoundedSemaphore(4)
_logger = logging.getLogger(__name__)

# ── LLM Provider 轮询 fallback ──────────────────────────────────────────
# 主 Provider 不可用时自动切换到备用 Provider。
# 配置方式：在 .env 中添加 LLM_FALLBACK_URL / LLM_FALLBACK_KEY / LLM_FALLBACK_MODEL
_FALLBACK_URL = None  # 由 config.py 注入
_FALLBACK_KEY = None
_FALLBACK_MODEL = None

# N5: fallback 总超时预算。主 + 备 Provider 共享同一墙钟预算：
# - _fallback_deadline 在每次 _chat_completion() 入口重置（单次调用内有效）；
# - 预算耗尽时跳过 fallback 直接抛主 Provider 错误，杜绝「重试 + fallback」无界叠加。
# - settings.LLM_FALLBACK_BUDGET_SECONDS > 0 时用配置值；否则自动 = min(2×timeout, timeout+60)。
_FALLBACK_MIN_BUDGET = 1.0  # fallback 至少需要 1s 预算才值得切换
# D5: 改为 thread-local 避免并发请求互相覆盖 deadline
_fallback_deadline_local = threading.local()


def _fallback_total_budget(timeout: float) -> float:
    configured = getattr(settings, "LLM_FALLBACK_BUDGET_SECONDS", 0.0)
    if configured and configured > 0:
        return float(configured)
    return min(timeout * 2, timeout + 60)


def set_fallback_provider(url: str, key: str, model: str):
    """注册备用 LLM Provider（由 app 启动时调用）。"""
    global _FALLBACK_URL, _FALLBACK_KEY, _FALLBACK_MODEL
    _FALLBACK_URL = url
    _FALLBACK_KEY = key
    _FALLBACK_MODEL = model


def _snippet(text: str, limit: int = _UPSTREAM_BODY_LIMIT) -> str:
    text = (text or "").replace("\r\n", "\n").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _requests_reason(exc: BaseException) -> str:
    if isinstance(exc, requests.Timeout):
        return "timeout"
    text = str(exc).lower()
    name = type(exc).__name__.lower()
    if "timed out" in text or "timeout" in name:
        return "timeout"
    if "refused" in text:
        return "connection_refused"
    if (
        "reset" in text
        or "disconnected" in text
        or "closed connection" in text
        or "remotedisconnected" in name
    ):
        return "connection_reset"
    return "unreachable"


def _log_upstream_error(response, attempt: int) -> str:
    """把远端 LLM 网关的原始回包打到控制台，并返回截断正文供业务层回传状态。"""
    content_type = ""
    body = ""
    if response is not None:
        content_type = response.headers.get("Content-Type", "")
        try:
            body = response.text or ""
        except Exception:
            body = ""
    snippet = _snippet(body)
    _logger.warning(
        "LLM upstream HTTP %s attempt=%s/%s content_type=%r body_len=%s body=%r",
        getattr(response, "status_code", "?"), attempt + 1, _RETRY_TIMES,
        content_type, len(body), snippet,
    )
    return snippet


def chat_completion(
    messages: list[dict],
    max_tokens: int = 500,
    temperature: float = 0.1,
    response_format: dict | None = None,
    timeout: int = 60,
) -> str:
    remaining = remaining_seconds()
    if remaining is not None and remaining <= 0:
        raise LLMError("AI 请求已超过总时限", reason="timeout")
    acquire_timeout = min(3.0, remaining) if remaining is not None else 3.0  # L6: 放宽到 3s 防误报 overloaded
    if not _LLM_SLOTS.acquire(timeout=acquire_timeout):
        raise LLMError("AI 模型并发繁忙，请稍后重试", reason="overloaded")
    try:
        remaining = remaining_seconds()
        call_timeout = min(timeout, remaining) if remaining is not None else timeout
        if call_timeout <= 0:
            raise LLMError("AI 请求已超过总时限", reason="timeout")
        return _chat_completion(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
            timeout=call_timeout,
        )
    finally:
        _LLM_SLOTS.release()


def _chat_completion(
    messages: list[dict],
    max_tokens: int = 500,
    temperature: float = 0.1,
    response_format: dict | None = None,
    timeout: int = 60,
) -> str:
    """
    调用公司内部 Qwen Chat Completions API。
    主 Provider 不可用时自动切换到备用 Provider（如 Hermes）。
    """
    # D5: 记录本次「主 + 备」调用的墙钟总预算截止点（thread-local，避免并发竞态）
    deadline = time.monotonic() + _fallback_total_budget(timeout)
    _fallback_deadline_local.value = deadline
    try:
        return _call_llm(
            settings.LLM_API_URL,
            settings.LLM_API_KEY,
            settings.LLM_MODEL,
            messages, max_tokens, temperature, response_format, timeout,
        )
    except LLMError as primary_err:
        # D14: 401（API Key 错误）不触发 fallback，直接抛出
        # 配置错误应被立即发现，而非静默烧备用额度
        if primary_err.status_code == 401:
            raise
        if _FALLBACK_URL and _FALLBACK_KEY:
            # N5: 主 + 备 Provider 共享墙钟总超时预算，防止主 Provider 重试耗尽
            # timeout 后 fallback 又拿到完整 timeout，总耗时无上界、线程被长期占用。
            remaining = _fallback_deadline_local.value - time.monotonic()
            if remaining < _FALLBACK_MIN_BUDGET:
                _logger.warning(
                    "LLM fallback 跳过：总超时预算已耗尽（剩余 %.2fs）reason=%s",
                    max(remaining, 0.0), primary_err.reason,
                )
                raise
            _logger.warning("LLM 主 Provider 不可用（%s），切换到备用 Provider", primary_err.reason)
            return _call_llm(
                _FALLBACK_URL,
                _FALLBACK_KEY,
                _FALLBACK_MODEL,
                messages, max_tokens, temperature, response_format,
                min(timeout, remaining),
            )
        raise


def _call_llm(
    api_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    max_tokens: int = 500,
    temperature: float = 0.1,
    response_format: dict | None = None,
    timeout: float = 60,
) -> str:
    """调用指定的 LLM Provider。"""
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        # Qwen3.6 思考模型默认会先吐 CoT，占满 max_tokens 后截断真正的 JSON。
        "enable_thinking": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    if response_format:
        payload["response_format"] = response_format

    input_payload = {
        "model": payload["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "response_format": response_format,
        "enable_thinking": False,
        "url": api_url,
    }

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "Authorization": f"Bearer {api_key}",
    }

    response = None
    last_exc: requests.RequestException | None = None
    last_upstream = ""
    last_status: int | None = None
    last_reason = "unreachable"
    for attempt in range(_RETRY_TIMES):
        response = None
        remaining = remaining_seconds()
        if remaining is not None and remaining <= 0:
            raise LLMError("AI 请求已超过总时限", reason="timeout")
        attempt_timeout = min(timeout, remaining) if remaining is not None else timeout
        try:
            response = requests.post(
                api_url,
                headers=headers,
                json=payload,
                timeout=(min(3.0, attempt_timeout), attempt_timeout),
                # M4: 默认校验 TLS 证书（防中间人替换模型回包）；
                # 仅内网自签证书场景可通过 .env LLM_VERIFY_SSL=false 显式关闭。
                verify=settings.LLM_VERIFY_SSL,
            )
            last_status = response.status_code
            # 网关瞬时错误（502/503/504/429）退避重试；其余 4xx/5xx 直接抛出
            if response.status_code >= 400:
                last_upstream = _log_upstream_error(response, attempt)
                last_reason = "http_error"
                _write_call_log(
                    ok=False,
                    input_payload=input_payload,
                    attempt=attempt,
                    status=response.status_code,
                    reason=last_reason,
                    error_type="HTTPError",
                    error_message=f"HTTP {response.status_code}",
                    body=last_upstream,
                )
            if response.status_code in _RETRY_STATUS and attempt < _RETRY_TIMES - 1:
                _sleep_before_retry(attempt)
                continue
            response.raise_for_status()
            break
        except requests.HTTPError as exc:
            last_exc = exc
            last_status = response.status_code if response is not None else exc.response.status_code
            last_reason = "http_error"
            raise LLMError(
                f"调用大模型接口失败: HTTP {last_status}",
                status_code=last_status,
                body=last_upstream,
                reason=last_reason,
            ) from exc
        except requests.RequestException as exc:
            last_exc = exc
            if response is None:
                last_status = None
                last_reason = _requests_reason(exc)
                _logger.warning(
                    "LLM request failed attempt=%s/%s reason=%s error=%r",
                    attempt + 1, _RETRY_TIMES, last_reason, exc,
                )
                _write_call_log(
                    ok=False,
                    input_payload=input_payload,
                    attempt=attempt,
                    status=None,
                    reason=last_reason,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    body="",
                )
            else:
                last_status = response.status_code
                last_reason = "http_error"
            retryable = isinstance(exc, (requests.Timeout, requests.ConnectionError))
            if retryable and attempt < _RETRY_TIMES - 1 and _sleep_before_retry(attempt):
                continue
            extra = f" upstream={last_upstream!r}" if last_upstream else ""
            raise LLMError(
                f"调用大模型接口失败: {exc}{extra}",
                status_code=last_status,
                body=last_upstream,
                reason=last_reason,
            ) from exc

    if response is None:
        raise LLMError(
            f"调用大模型接口失败: {last_exc}",
            status_code=last_status,
            body=last_upstream,
            reason=last_reason,
        )

    try:
        result = response.json()

        content = result["choices"][0]["message"]["content"]
        content = strip_thinking(content)
        _write_call_log(
            ok=True,
            input_payload=input_payload,
            attempt=attempt,
            status=response.status_code,
            output=content,
            usage=result.get("usage"),
        )
        return content

    except (
        ValueError,
        KeyError,
        IndexError,
        TypeError,
    ) as exc:
        body = _snippet(response.text)
        _write_call_log(
            ok=False,
            input_payload=input_payload,
            attempt=attempt,
            status=response.status_code,
            reason="invalid_response",
            error_type=type(exc).__name__,
            error_message=str(exc),
            body=body,
            extra_fields={"choices": (response.json().get("choices") if _safe_json(response) else None)},
        )
        raise LLMError(
            f"大模型返回格式异常: {response.text[:500]}",
            status_code=response.status_code,
            body=body,
            reason="invalid_response",
        ) from exc


_THINK_BLOCK = re.compile(
    r"<think>.*?</think>",
    flags=re.DOTALL | re.IGNORECASE,
)
_THINK_PREFIX = re.compile(
    r"^(?:here's a thinking process:|thinking process:|thinking:)\s*",
    flags=re.IGNORECASE,
)


def strip_thinking(text: str) -> str:
    """去掉思考模型泄漏的 CoT，避免把示例 JSON 当成最终结果。"""
    text = _THINK_BLOCK.sub("", text or "").strip()
    text = _THINK_PREFIX.sub("", text).strip()
    return text


def extract_llm_json(text: str, required_any: tuple[str, ...] = ()) -> dict:
    """从模型输出中取出最后一个完整 JSON 对象。"""
    text = strip_thinking(text)
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            if not required_any or any(key in parsed for key in required_any):
                return parsed
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    candidates: list[dict] = []
    for match in re.finditer(r"\{", text):
        try:
            parsed, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            candidates.append(parsed)

    if required_any:
        matched = [
            item
            for item in candidates
            if any(key in item for key in required_any)
        ]
        if matched:
            return matched[-1]

    if candidates:
        return candidates[-1]

    raise ValueError(f"模型没有返回 JSON: {text[:300]}")


def _safe_json(response):
    try:
        data = response.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _sleep_before_retry(attempt: int) -> bool:
    remaining = remaining_seconds()
    base = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
    delay = min(1.5, random.uniform(base * 0.6, base * 1.4))
    if remaining is not None:
        if remaining <= delay + 0.25:
            return False
        delay = min(delay, remaining - 0.25)
    time.sleep(delay)
    return True


def _write_call_log(
    *,
    ok: bool,
    input_payload: dict,
    attempt: int,
    status: int | None,
    reason: str = "",
    error_type: str = "",
    error_message: str = "",
    body: str = "",
    output: str = "",
    usage=None,
    extra_fields=None,
) -> None:
    event = {
        "ok": ok,
        "model": input_payload.get("model"),
        "url": input_payload.get("url"),
        "attempt": attempt + 1,
        "attempts": _RETRY_TIMES,
        "status": status,
        "input": {
            "messages": input_payload.get("messages"),
            "max_tokens": input_payload.get("max_tokens"),
            "temperature": input_payload.get("temperature"),
            "response_format": input_payload.get("response_format"),
        },
    }
    if ok:
        event["output"] = output
        if usage is not None:
            event["usage"] = usage
    else:
        event["reason"] = reason
        event["error"] = {
            "type": error_type,
            "message": error_message,
            "status": status,
            "body": body,
            "fields": parse_error_fields(body),
        }
        if extra_fields:
            event["error"]["fields"].update(
                {key: value for key, value in extra_fields.items() if value is not None}
            )
    try:
        enqueue_llm_log(event)
    except Exception as exc:
        print(f"[LLM] 写日志失败 err={exc!r}")
