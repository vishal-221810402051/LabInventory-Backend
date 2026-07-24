from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.domain.capture import (
    CaptureMode,
    CaptureStatus,
    datetime_to_wire,
    decimal_to_wire,
    ensure_aware_utc,
    normalize_optional_string,
    parse_quantity_string,
)


class ManualEntry(BaseModel):
    name: Annotated[str | None, Field(max_length=200)] = None
    quantity: Decimal | None = Field(
        default=None,
        description="Positive decimal quantity encoded as a JSON string with up to 6 decimals.",
        examples=["0.25", "2.000000", "1000.125000"],
    )
    unit: Annotated[str | None, Field(max_length=32)] = None
    category_hint: Annotated[str | None, Field(max_length=100)] = None
    notes: str | None = None

    @field_validator("name", "unit", "category_hint", "notes", mode="before")
    @classmethod
    def normalize_string_fields(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            msg = "Manual entry text fields must be strings."
            raise ValueError(msg)
        return normalize_optional_string(value)

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_quantity(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return parse_quantity_string(value)

    @field_serializer("quantity")
    def serialize_quantity(self, value: Decimal | None) -> str | None:
        if value is None:
            return None
        return decimal_to_wire(value)


class CaptureSessionCreateRequest(BaseModel):
    client_capture_id: UUID
    capture_mode: CaptureMode
    captured_at: datetime
    manual_entry: ManualEntry | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "client_capture_id": "550e8400-e29b-41d4-a716-446655440000",
                "capture_mode": "PHOTO",
                "captured_at": "2026-07-24T18:30:00Z",
                "manual_entry": {
                    "name": "HC-SR04 ultrasonic sensor",
                    "quantity": "2.000000",
                    "unit": "pcs",
                    "category_hint": "Sensors/Modules",
                    "notes": "Stored in drawer A3",
                },
            }
        }
    )

    @field_validator("captured_at")
    @classmethod
    def validate_captured_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)


class CaptureSessionResponse(BaseModel):
    id: UUID
    client_capture_id: UUID
    capture_mode: CaptureMode
    status: CaptureStatus
    captured_at: datetime
    manual_entry: ManualEntry | None
    photo_count: int
    created_at: datetime
    updated_at: datetime

    @field_serializer("captured_at", "created_at", "updated_at")
    def serialize_datetime(self, value: datetime) -> str:
        return datetime_to_wire(value)


class CapturePhotoResponse(BaseModel):
    id: UUID
    client_photo_id: UUID
    capture_session_id: UUID
    content_type: str
    size_bytes: int
    sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        examples=["2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"],
    )
    created_at: datetime

    @field_serializer("created_at")
    def serialize_datetime(self, value: datetime) -> str:
        return datetime_to_wire(value)
