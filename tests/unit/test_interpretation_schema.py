from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.interpretation import (
    ALLOWED_CATEGORIES,
    ALLOWED_UNITS,
    ITEM_INTERPRETATION_JSON_SCHEMA,
    InterpretationSuggestion,
)


def suggestion_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "result": "SUGGESTION",
        "suggested_name": "Capacitive liquid level sensor",
        "suggested_category": "Sensors/Modules",
        "suggested_unit": "pcs",
        "manufacturer": None,
        "part_number": "HYB11067",
        "short_description": "Non-contact liquid-level sensor module.",
        "evidence_strength": "STRONG",
        "evidence": ["OCR contains HYB11067"],
        "warnings": ["Exact electrical specifications were not verified"],
    }
    payload.update(updates)
    return payload


def test_allowed_category_and_unit_are_accepted() -> None:
    suggestion = InterpretationSuggestion.model_validate(suggestion_payload())

    assert suggestion.suggested_category in ALLOWED_CATEGORIES
    assert suggestion.suggested_unit in ALLOWED_UNITS


@pytest.mark.parametrize(
    "updates",
    [
        {"suggested_category": "Power Supply"},
        {"suggested_unit": "piece"},
        {"quantity": "2.000000"},
    ],
)
def test_unknown_taxonomy_values_and_quantity_field_are_rejected(
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        InterpretationSuggestion.model_validate(suggestion_payload(**updates))


def test_strict_schema_has_no_extra_properties_and_no_quantity() -> None:
    assert ITEM_INTERPRETATION_JSON_SCHEMA["additionalProperties"] is False
    assert ITEM_INTERPRETATION_JSON_SCHEMA["properties"]["suggested_category"]["enum"] == [
        *ALLOWED_CATEGORIES,
        None,
    ]
    assert ITEM_INTERPRETATION_JSON_SCHEMA["properties"]["suggested_unit"]["enum"] == [
        *ALLOWED_UNITS,
        None,
    ]
    assert "quantity" not in ITEM_INTERPRETATION_JSON_SCHEMA["properties"]
