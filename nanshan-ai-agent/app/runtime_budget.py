from contextvars import ContextVar
from time import monotonic


_deadline = ContextVar("ai_request_deadline", default=None)


def set_deadline(seconds: float):
    return _deadline.set(monotonic() + seconds)


def reset_deadline(token) -> None:
    _deadline.reset(token)


def remaining_seconds() -> float | None:
    deadline = _deadline.get()
    if deadline is None:
        return None
    return max(0.0, deadline - monotonic())