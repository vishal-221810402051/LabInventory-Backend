from __future__ import annotations

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import ApplicationError
from app.core.logging import get_logger
from app.core.request_context import get_correlation_id
from app.schemas.errors import ErrorEnvelope

logger = get_logger(__name__)


def error_response(
    *,
    code: str,
    message: str,
    status_code: int,
    details: object = None,
) -> JSONResponse:
    envelope = ErrorEnvelope(
        error={
            "code": code,
            "message": message,
            "details": details,
            "correlation_id": get_correlation_id(),
        }
    )
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


async def application_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApplicationError):
        return error_response(
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected error occurred.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return error_response(
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
        details=exc.details,
    )


async def validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        return error_response(
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected error occurred.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    safe_details = [
        {"loc": error.get("loc"), "msg": error.get("msg"), "type": error.get("type")}
        for error in exc.errors()
    ]
    return error_response(
        code="VALIDATION_ERROR",
        message="Request validation failed.",
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        details=safe_details,
    )


async def unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Unhandled application exception",
        exc_info=exc,
        extra={"event": "application.unexpected_exception"},
    )
    return error_response(
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred.",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
