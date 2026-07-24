from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None
    correlation_id: str


class ErrorEnvelope(BaseModel):
    error: ErrorBody

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "error": {
                "code": "DATABASE_UNAVAILABLE",
                "message": "Database readiness check failed.",
                "details": None,
                "correlation_id": "00000000-0000-4000-8000-000000000000",
            }
        }
    })
