from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import Request, Response

from app.core.logging import get_logger
from app.core.request_context import (
    reset_correlation_id,
    set_correlation_id,
)

CORRELATION_ID_HEADER = "X-Correlation-ID"
MAX_CORRELATION_ID_LENGTH = 64
_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
logger = get_logger(__name__)


def is_valid_correlation_id(value: str | None) -> bool:
    if value is None:
        return False
    if len(value) > MAX_CORRELATION_ID_LENGTH:
        return False
    return bool(_UUID_PATTERN.fullmatch(value))


def normalize_correlation_id(value: str | None) -> str:
    if value is not None:
        stripped = value.strip()
        if is_valid_correlation_id(stripped):
            return stripped
    return str(uuid4())


async def correlation_id_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    correlation_id = normalize_correlation_id(request.headers.get(CORRELATION_ID_HEADER))
    token = set_correlation_id(correlation_id)
    start = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 3)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        logger.info(
            "HTTP request completed",
            extra={
                "event": "http.request.completed",
                "http_method": request.method,
                "request_path": request.url.path,
                "response_status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response
    finally:
        reset_correlation_id(token)
