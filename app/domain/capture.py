from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID


class CaptureMode(StrEnum):
    PHOTO = "PHOTO"
    MANUAL = "MANUAL"
    PHOTO_WITH_MANUAL = "PHOTO_WITH_MANUAL"


class CaptureStatus(StrEnum):
    DRAFT = "DRAFT"
    READY_FOR_PROCESSING = "READY_FOR_PROCESSING"


@dataclass(frozen=True)
class ManualEntrySnapshot:
    name: str | None
    quantity: Decimal | None
    unit: str | None
    category_hint: str | None
    notes: str | None


MAX_QUANTITY_INTEGER_DIGITS = 18
MAX_QUANTITY_FRACTIONAL_DIGITS = 6
MAX_QUANTITY_TOTAL_DIGITS = 24
_FINGERPRINT_QUANTUM = Decimal("0.000001")
_QUANTITY_PATTERN = re.compile(r"^-?(?P<integer>\d+)(?:\.(?P<fraction>\d+))?$")


def normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def parse_quantity_string(value: object) -> Decimal:
    if isinstance(value, Decimal):
        quantity = value
        if not quantity.is_finite():
            msg = "Quantity must be finite."
            raise ValueError(msg)
        quantity_tuple = quantity.as_tuple()
        exponent = quantity_tuple.exponent
        fractional_digits = max(-exponent, 0) if isinstance(exponent, int) else 0
        digits = len(quantity_tuple.digits)
        if quantity <= 0:
            msg = "Quantity must be greater than zero."
            raise ValueError(msg)
        if fractional_digits > MAX_QUANTITY_FRACTIONAL_DIGITS:
            msg = "Quantity must not have more than 6 fractional digits."
            raise ValueError(msg)
        if digits > MAX_QUANTITY_TOTAL_DIGITS:
            msg = "Quantity has too many total digits."
            raise ValueError(msg)
        return quantity

    if not isinstance(value, str):
        msg = "Quantity must be provided as a decimal string."
        raise ValueError(msg)

    raw_value = value.strip()
    match = _QUANTITY_PATTERN.fullmatch(raw_value)
    if match is None:
        msg = "Quantity must be a plain decimal string without exponent notation."
        raise ValueError(msg)

    integer_part = match.group("integer").lstrip("-")
    fraction_part = match.group("fraction") or ""
    if len(integer_part) > MAX_QUANTITY_INTEGER_DIGITS:
        msg = "Quantity has too many integer digits."
        raise ValueError(msg)
    if len(fraction_part) > MAX_QUANTITY_FRACTIONAL_DIGITS:
        msg = "Quantity must not have more than 6 fractional digits."
        raise ValueError(msg)
    if len(integer_part) + len(fraction_part) > MAX_QUANTITY_TOTAL_DIGITS:
        msg = "Quantity has too many total digits."
        raise ValueError(msg)

    try:
        quantity = Decimal(raw_value)
    except InvalidOperation as exc:
        msg = "Quantity must be a valid decimal string."
        raise ValueError(msg) from exc

    if not quantity.is_finite():
        msg = "Quantity must be finite."
        raise ValueError(msg)
    if quantity <= 0:
        msg = "Quantity must be greater than zero."
        raise ValueError(msg)
    return quantity


def decimal_to_wire(value: Decimal) -> str:
    return format(value, "f")


def decimal_to_fingerprint(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(_FINGERPRINT_QUANTUM), "f")


def ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "Timestamp must include timezone information."
        raise ValueError(msg)
    return value.astimezone(UTC)


def datetime_to_wire(value: datetime) -> str:
    utc_value = ensure_aware_utc(value)
    return utc_value.isoformat().replace("+00:00", "Z")


def datetime_to_fingerprint(value: datetime) -> str:
    utc_value = ensure_aware_utc(value)
    return utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def capture_request_fingerprint(
    *,
    client_capture_id: UUID,
    capture_mode: CaptureMode,
    captured_at: datetime,
    manual_entry: ManualEntrySnapshot | None,
) -> str:
    normalized = {
        "client_capture_id": str(client_capture_id),
        "capture_mode": capture_mode.value,
        "captured_at": datetime_to_fingerprint(captured_at),
        "manual_entry": None
        if manual_entry is None
        else {
            "name": normalize_optional_string(manual_entry.name),
            "quantity": decimal_to_fingerprint(manual_entry.quantity),
            "unit": normalize_optional_string(manual_entry.unit),
            "category_hint": normalize_optional_string(manual_entry.category_hint),
            "notes": normalize_optional_string(manual_entry.notes),
        },
    }
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
