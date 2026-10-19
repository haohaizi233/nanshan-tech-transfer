import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic
from uuid import uuid4


_trace_id = ContextVar("ai_trace_id", default="")
_logger = logging.getLogger("nanshan.ai.trace")


def current_trace_id() -> str:
    return _trace_id.get()


@contextmanager
def request_trace(request_id: str | None = None):
    identifier = request_id if isinstance(request_id, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", request_id) else uuid4().hex
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
