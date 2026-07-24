from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.capture import (
    CaptureMode,
    datetime_to_fingerprint,
    decimal_to_fingerprint,
    ensure_aware_utc,
)


class AiProvider(StrEnum):
    OPENAI = "OPENAI"


class InterpretationStatus(StrEnum):
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"
    FAILED = "FAILED"
    REFUSED = "REFUSED"


class InterpretationResult(StrEnum):
    SUGGESTION = "SUGGESTION"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"


class EvidenceStrength(StrEnum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    INSUFFICIENT = "INSUFFICIENT"


AllowedCategory = Literal[
    "Boards/Compute",
    "Sensors/Modules",
    "Actuators/Drivers",
    "Passive Components",
    "ICs",
    "Wires/Cables",
    "Tubes/Pipes",
    "Mechanical/Fasteners",
    "Tools",
    "Power Supplies",
    "Misc",
]
AllowedUnit = Literal["pcs", "m", "ft", "ml", "l", "g", "kg", "box", "roll", "spool", "kit"]
EvidenceText = Annotated[str, Field(max_length=200)]

ALLOWED_CATEGORIES: tuple[str, ...] = (
    "Boards/Compute",
    "Sensors/Modules",
    "Actuators/Drivers",
    "Passive Components",
    "ICs",
    "Wires/Cables",
    "Tubes/Pipes",
    "Mechanical/Fasteners",
    "Tools",
    "Power Supplies",
    "Misc",
)
ALLOWED_UNITS: tuple[str, ...] = (
    "pcs",
    "m",
    "ft",
    "ml",
    "l",
    "g",
    "kg",
    "box",
    "roll",
    "spool",
    "kit",
)
SUPPORTED_AI_LOCALES = {"en"}
AI_IMAGE_INPUT_ENABLED = False
AI_TAXONOMY_VERSION = "phase3-taxonomy-v1"
MAX_AI_SOURCE_TEXT_CHARS = 20_000


ITEM_INTERPRETATION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "result",
        "suggested_name",
        "suggested_category",
        "suggested_unit",
        "manufacturer",
        "part_number",
        "short_description",
        "evidence_strength",
        "evidence",
        "warnings",
    ],
    "properties": {
        "result": {
            "type": "string",
            "enum": [
                InterpretationResult.SUGGESTION.value,
                InterpretationResult.INSUFFICIENT_INFORMATION.value,
            ],
        },
        "suggested_name": {"type": ["string", "null"], "maxLength": 200},
        "suggested_category": {
            "type": ["string", "null"],
            "enum": [*ALLOWED_CATEGORIES, None],
        },
        "suggested_unit": {"type": ["string", "null"], "enum": [*ALLOWED_UNITS, None]},
        "manufacturer": {"type": ["string", "null"], "maxLength": 200},
        "part_number": {"type": ["string", "null"], "maxLength": 200},
        "short_description": {"type": ["string", "null"], "maxLength": 500},
        "evidence_strength": {
            "type": "string",
            "enum": [strength.value for strength in EvidenceStrength],
        },
        "evidence": {
            "type": "array",
            "maxItems": 5,
            "items": {"type": "string", "maxLength": 200},
        },
        "warnings": {
            "type": "array",
            "maxItems": 5,
            "items": {"type": "string", "maxLength": 200},
        },
    },
}


class InterpretationSuggestion(BaseModel):
    result: InterpretationResult
    suggested_name: Annotated[str | None, Field(max_length=200)] = None
    suggested_category: AllowedCategory | None = None
    suggested_unit: AllowedUnit | None = None
    manufacturer: Annotated[str | None, Field(max_length=200)] = None
    part_number: Annotated[str | None, Field(max_length=200)] = None
    short_description: Annotated[str | None, Field(max_length=500)] = None
    evidence_strength: EvidenceStrength
    evidence: Annotated[list[EvidenceText], Field(max_length=5)]
    warnings: Annotated[list[EvidenceText], Field(max_length=5)]

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "suggested_name",
        "manufacturer",
        "part_number",
        "short_description",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        normalized = unicodedata.normalize("NFKC", value).strip()
        return normalized or None


@dataclass(frozen=True)
class AiManualSource:
    name: str | None
    quantity: Decimal | None
    unit: str | None
    category_hint: str | None
    notes: str | None


@dataclass(frozen=True)
class AiOcrTextSource:
    status: str
    text_source: str
    text: str | None


@dataclass(frozen=True)
class AiInterpretationSource:
    capture_mode: CaptureMode
    manual: AiManualSource
    ocr: list[AiOcrTextSource]
    requested_locale: str
    source_character_count: int

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "locale": self.requested_locale,
            "taxonomy": {
                "version": AI_TAXONOMY_VERSION,
                "allowed_categories": list(ALLOWED_CATEGORIES),
                "allowed_units": list(ALLOWED_UNITS),
            },
            "capture": {
                "mode": self.capture_mode.value,
                "manual": {
                    "name": self.manual.name,
                    "quantity": decimal_to_fingerprint(self.manual.quantity),
                    "unit": self.manual.unit,
                    "category_hint": self.manual.category_hint,
                    "notes": self.manual.notes,
                },
                "ocr": [
                    {
                        "status": item.status,
                        "text_source": item.text_source,
                        "text": item.text,
                    }
                    for item in self.ocr
                ],
            },
        }


def normalize_ai_source_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in normalized.split("\n")]
    normalized = "\n".join(lines).strip()
    return normalized or None


def ai_source_fingerprint(
    *,
    source: AiInterpretationSource,
    prompt_version: str,
    schema_version: str,
) -> str:
    payload = {
        "source": source.to_prompt_payload(),
        "taxonomy_version": AI_TAXONOMY_VERSION,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
    }
    return _fingerprint_payload(payload)


def ai_request_fingerprint(
    *,
    client_interpretation_id: UUID,
    requested_at: datetime,
    requested_locale: str,
    source_fingerprint: str,
    provider: AiProvider,
    model: str,
    prompt_version: str,
    schema_version: str,
) -> str:
    payload = {
        "client_interpretation_id": str(client_interpretation_id),
        "requested_at": datetime_to_fingerprint(ensure_aware_utc(requested_at)),
        "requested_locale": requested_locale,
        "source_fingerprint": source_fingerprint,
        "provider": provider.value,
        "model": model,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
    }
    return _fingerprint_payload(payload)


def _fingerprint_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()
