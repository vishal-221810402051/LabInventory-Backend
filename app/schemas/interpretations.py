from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.domain.capture import datetime_to_wire, ensure_aware_utc
from app.domain.interpretation import (
    AI_IMAGE_INPUT_ENABLED,
    AiProvider,
    InterpretationStatus,
    InterpretationSuggestion,
)


class AiStatusResponse(BaseModel):
    enabled: bool
    configured: bool
    provider: AiProvider
    model: str
    prompt_version: str
    schema_version: str
    image_input_enabled: bool = AI_IMAGE_INPUT_ENABLED


class InterpretationCreateRequest(BaseModel):
    client_interpretation_id: UUID
    requested_at: datetime
    requested_locale: str = Field(examples=["en"], max_length=16)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "client_interpretation_id": "550e8400-e29b-41d4-a716-446655440020",
                "requested_at": "2026-07-25T15:00:00Z",
                "requested_locale": "en",
            }
        }
    )

    @field_validator("requested_at")
    @classmethod
    def validate_requested_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("requested_locale")
    @classmethod
    def normalize_requested_locale(cls, value: str) -> str:
        return value.strip().lower()


class InterpretationResponse(BaseModel):
    id: UUID
    client_interpretation_id: UUID
    capture_session_id: UUID
    status: InterpretationStatus
    provider: AiProvider
    model: str
    prompt_version: str
    schema_version: str
    suggestion: InterpretationSuggestion | None
    input_token_count: int | None
    output_token_count: int | None
    total_token_count: int | None
    latency_ms: int | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, value: datetime) -> str:
        return datetime_to_wire(value)


class InterpretationListResponse(BaseModel):
    items: list[InterpretationResponse]
    total: int
