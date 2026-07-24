from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.capture import datetime_to_fingerprint, ensure_aware_utc


class OcrEngine(StrEnum):
    ML_KIT_TEXT_RECOGNITION_V2 = "ML_KIT_TEXT_RECOGNITION_V2"


class OcrStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    NO_TEXT = "NO_TEXT"
    FAILED = "FAILED"


@dataclass(frozen=True)
class OcrFingerprintSnapshot:
    client_ocr_id: UUID
    client_photo_id: UUID
    engine: OcrEngine
    engine_version: str | None
    status: OcrStatus
    processed_at: datetime
    raw_text: str
    normalized_corrected_text: str | None
    block_count: int
    line_count: int
    element_count: int
    detected_language_tags: list[str]


MAX_ENGINE_VERSION_CHARS = 100
MAX_LANGUAGE_TAGS = 16
MAX_LANGUAGE_TAG_CHARS = 35
MAX_BLOCK_COUNT = 10_000
MAX_LINE_COUNT = 50_000
MAX_ELEMENT_COUNT = 250_000
_LANGUAGE_TAG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def parse_ocr_engine(value: str) -> OcrEngine:
    try:
        return OcrEngine(value.strip())
    except ValueError as exc:
        msg = "Unsupported OCR engine."
        raise ValueError(msg) from exc


def parse_ocr_status(value: str) -> OcrStatus:
    try:
        return OcrStatus(value.strip())
    except ValueError as exc:
        msg = "Unsupported OCR status."
        raise ValueError(msg) from exc


def normalize_engine_version(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized:
        return None
    if len(normalized) > MAX_ENGINE_VERSION_CHARS:
        msg = f"engine_version must not exceed {MAX_ENGINE_VERSION_CHARS} characters."
        raise ValueError(msg)
    if _contains_disallowed_control(normalized):
        msg = "engine_version contains an unsafe control character."
        raise ValueError(msg)
    return normalized


def normalize_language_tags(values: list[str]) -> list[str]:
    if len(values) > MAX_LANGUAGE_TAGS:
        msg = f"detected_language_tags must not contain more than {MAX_LANGUAGE_TAGS} entries."
        raise ValueError(msg)

    normalized_tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = unicodedata.normalize("NFKC", value).strip().replace("_", "-").lower()
        if not normalized:
            msg = "Language tags must not be empty."
            raise ValueError(msg)
        if len(normalized) > MAX_LANGUAGE_TAG_CHARS:
            msg = f"Language tags must not exceed {MAX_LANGUAGE_TAG_CHARS} characters."
            raise ValueError(msg)
        if (
            _contains_disallowed_control(normalized)
            or _LANGUAGE_TAG_PATTERN.fullmatch(normalized) is None
        ):
            msg = "Language tags must use alphanumeric BCP-47 style subtags separated by hyphens."
            raise ValueError(msg)
        if normalized not in seen:
            normalized_tags.append(normalized)
            seen.add(normalized)
    return normalized_tags


def validate_structural_count(value: int, *, field_name: str, maximum: int) -> None:
    if value < 0:
        msg = f"{field_name} must be non-negative."
        raise ValueError(msg)
    if value > maximum:
        msg = f"{field_name} must not exceed {maximum}."
        raise ValueError(msg)


def ocr_request_fingerprint(snapshot: OcrFingerprintSnapshot) -> str:
    processed_at = ensure_aware_utc(snapshot.processed_at)
    normalized = {
        "client_ocr_id": str(snapshot.client_ocr_id),
        "client_photo_id": str(snapshot.client_photo_id),
        "engine": snapshot.engine.value,
        "engine_version": snapshot.engine_version,
        "status": snapshot.status.value,
        "processed_at": datetime_to_fingerprint(processed_at),
        "raw_text": snapshot.raw_text,
        "normalized_corrected_text": snapshot.normalized_corrected_text,
        "block_count": snapshot.block_count,
        "line_count": snapshot.line_count,
        "element_count": snapshot.element_count,
        "detected_language_tags": snapshot.detected_language_tags,
    }
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _contains_disallowed_control(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)
