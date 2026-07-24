from __future__ import annotations

import contextvars
from uuid import uuid4

CorrelationToken = contextvars.Token[str | None]

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id",
    default=None,
)


def get_correlation_id() -> str:
    correlation_id = _correlation_id.get()
    if correlation_id is None:
        correlation_id = str(uuid4())
        _correlation_id.set(correlation_id)
    return correlation_id


def current_correlation_id() -> str | None:
    return _correlation_id.get()


def set_correlation_id(correlation_id: str | None) -> CorrelationToken:
    return _correlation_id.set(correlation_id)


def reset_correlation_id(token: CorrelationToken) -> None:
    _correlation_id.reset(token)
