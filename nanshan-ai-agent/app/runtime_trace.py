import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic
from uuid import uuid4


_trace_id = ContextVar("ai_trace_id", default="")
_stage_observer = ContextVar("ai_stage_observer", default=None)
_logger = logging.getLogger("nanshan.ai.trace")

# 阶段级计数白名单：只允许业务可解释的指标名进日志，避免任意 key 注入。
_COUNT_WHITELIST = {
    "candidate_count",
    "selected_count",
    "returned_count",
    "llm_call_count",
    "llm_error_count",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "db_query_count",
    "stage_count",
}

# 降级原因白名单。
_DEGRADATION_WHITELIST = {
    "small_candidate_set",
    "budget_low",
    "rerank_failed",
    "context_limit",
    "no_candidates",
    "visibility_changed",
    "preference_weighted",
    "llm_degraded",
    "retrieval_degraded",
    "empty_diagnostics",
}


def current_trace_id() -> str:
    return _trace_id.get()


@contextmanager
def stage_observer(observer):
    token = _stage_observer.set(observer)
    try:
        yield
    finally:
        _stage_observer.reset(token)


def emit_stage(stage: str):
    observer = _stage_observer.get()
    if observer is not None:
        observer(stage)


def trace_count(name: str, count: int):
    if name not in _COUNT_WHITELIST:
        return
    if type(count) is int and count >= 0:
        _logger.info(
            "agent_count trace_id=%s metric=%s value=%d", current_trace_id(), name, count
        )


def trace_degradation(reason: str):
    if reason in _DEGRADATION_WHITELIST:
        _logger.info(
            "agent_degradation trace_id=%s reason=%s", current_trace_id(), reason
        )


@contextmanager
def request_trace(request_id: str | None = None):
    identifier = (
        request_id
        if isinstance(request_id, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", request_id)
        else uuid4().hex
    )
    token = _trace_id.set(identifier)
    try:
        yield identifier
    finally:
        _trace_id.reset(token)


@contextmanager
def trace_stage(name: str):
    started = monotonic()
    outcome = "ok"
    try:
        yield
    except BaseException:
        outcome = "error"
        raise
    finally:
        _logger.info(
            "agent_stage trace_id=%s stage=%s duration_ms=%.1f outcome=%s",
            current_trace_id(), name, (monotonic() - started) * 1000, outcome,
        )
