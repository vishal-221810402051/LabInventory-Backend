from __future__ import annotations

import pytest

from app.services.text_normalization import (
    InvalidOcrTextError,
    normalize_ocr_text,
    validate_ocr_text_input,
)


def test_nfkc_normalization() -> None:
    assert normalize_ocr_text("ＨＣ－ＳＲ０４") == "HC-SR04"


def test_crlf_and_cr_normalization() -> None:
    assert normalize_ocr_text("A\r\nB\rC") == "A\nB\nC"


def test_tab_and_repeated_space_normalization() -> None:
    assert normalize_ocr_text("  Ultrasonic\t\t  Sensor   5V  ") == "Ultrasonic Sensor 5V"


def test_case_punctuation_and_part_numbers_are_preserved() -> None:
    assert normalize_ocr_text("HC-SR04: Ultrasonic Sensor, 5V") == "HC-SR04: Ultrasonic Sensor, 5V"


def test_internal_blank_lines_are_collapsed_to_one() -> None:
    assert normalize_ocr_text("\n\nA\n\n\nB\n\n") == "A\n\nB"


def test_nul_is_rejected() -> None:
    with pytest.raises(InvalidOcrTextError):
        validate_ocr_text_input("A\x00B", field_name="raw_text")
