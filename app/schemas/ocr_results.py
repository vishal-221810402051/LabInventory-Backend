from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.domain.capture import datetime_to_wire, ensure_aware_utc
from app.domain.ocr import (
    MAX_BLOCK_COUNT,
    MAX_ELEMENT_COUNT,
    MAX_ENGINE_VERSION_CHARS,
    MAX_LANGUAGE_TAG_CHARS,
    MAX_LANGUAGE_TAGS,
    MAX_LINE_COUNT,
    OcrEngine,
    OcrStatus,
)
from app.services.text_normalization import MAX_OCR_TEXT_CHARS


class OcrResultCreateRequest(BaseModel):
    client_ocr_id: UUID
    client_photo_id: UUID
    engine: str = Field(examples=[OcrEngine.ML_KIT_TEXT_RECOGNITION_V2.value])
    engine_version: str | None = Field(
        default=None,
        json_schema_extra={"maxLength": MAX_ENGINE_VERSION_CHARS},
    )
    status: str = Field(examples=[OcrStatus.SUCCEEDED.value])
    processed_at: datetime
    raw_text: str = Field(
        description="Raw OCR text exactly as supplied by Android after input validation.",
        json_schema_extra={"maxLength": MAX_OCR_TEXT_CHARS},
    )
    corrected_text: str | None = Field(
        default=None,
        description=(
            "Optional Android/user-corrected OCR text; normalized separately by the backend."
        ),
        json_schema_extra={"maxLength": MAX_OCR_TEXT_CHARS},
    )
    block_count: int = Field(json_schema_extra={"minimum": 0, "maximum": MAX_BLOCK_COUNT})
    line_count: int = Field(json_schema_extra={"minimum": 0, "maximum": MAX_LINE_COUNT})
    element_count: int = Field(json_schema_extra={"minimum": 0, "maximum": MAX_ELEMENT_COUNT})
    detected_language_tags: list[str] = Field(
        default_factory=list,
        json_schema_extra={
            "maxItems": MAX_LANGUAGE_TAGS,
            "items": {"maxLength": MAX_LANGUAGE_TAG_CHARS},
        },
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "client_ocr_id": "550e8400-e29b-41d4-a716-446655440010",
                "client_photo_id": "550e8400-e29b-41d4-a716-446655440011",
                "engine": "ML_KIT_TEXT_RECOGNITION_V2",
                "engine_version": None,
                "status": "SUCCEEDED",
                "processed_at": "2026-07-25T10:00:00Z",
                "raw_text": "HC-SR04\r\nUltrasonic   Sensor\r\n5V",
                "corrected_text": "HC-SR04\nUltrasonic Sensor\n5V",
                "block_count": 1,
                "line_count": 3,
                "element_count": 5,
                "detected_language_tags": ["en"],
            }
        }
    )

    @field_validator("processed_at")
    @classmethod
    def validate_processed_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)


class OcrResultResponse(BaseModel):
    id: UUID
    client_ocr_id: UUID
    capture_session_id: UUID
    capture_photo_id: UUID
    engine: OcrEngine
    engine_version: str | None
    status: OcrStatus
    processed_at: datetime
    raw_text: str
    normalized_text: str
    corrected_text: str | None
    block_count: int
    line_count: int
    element_count: int
    detected_language_tags: list[str]
    created_at: datetime
    updated_at: datetime

    @field_serializer("processed_at", "created_at", "updated_at")
    def serialize_datetime(self, value: datetime) -> str:
        return datetime_to_wire(value)


class OcrResultsListResponse(BaseModel):
    items: list[OcrResultResponse]
    total: int
