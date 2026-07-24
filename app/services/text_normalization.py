from __future__ import annotations

import re
import unicodedata

MAX_OCR_TEXT_CHARS = 50_000
_HORIZONTAL_WHITESPACE_PATTERN = re.compile(r"[^\S\n]+")
_ALLOWED_INPUT_CONTROL_CHARS = {"\r", "\n", "\t"}


class OcrTextTooLargeError(ValueError):
    pass


class InvalidOcrTextError(ValueError):
    pass


def validate_ocr_text_input(value: str, *, field_name: str) -> None:
    if len(value) > MAX_OCR_TEXT_CHARS:
        msg = f"{field_name} must not exceed {MAX_OCR_TEXT_CHARS} Unicode characters."
        raise OcrTextTooLargeError(msg)
    for character in value:
        if character == "\x00":
            msg = f"{field_name} must not contain NUL characters."
            raise InvalidOcrTextError(msg)
        if _is_unsafe_input_control(character):
            msg = f"{field_name} contains an unsafe control character."
            raise InvalidOcrTextError(msg)


def normalize_ocr_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "".join(
        character
        for character in normalized
        if character == "\n" or not _is_removed_output_control(character)
    )
    normalized = _HORIZONTAL_WHITESPACE_PATTERN.sub(" ", normalized)
    lines = [line.strip() for line in normalized.split("\n")]
    lines = _trim_boundary_blank_lines(lines)
    lines = _collapse_internal_blank_lines(lines)
    return "\n".join(lines)


def _trim_boundary_blank_lines(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)
    while start < end and lines[start] == "":
        start += 1
    while end > start and lines[end - 1] == "":
        end -= 1
    return lines[start:end]


def _collapse_internal_blank_lines(lines: list[str]) -> list[str]:
    collapsed: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = line == ""
        if is_blank and previous_blank:
            continue
        collapsed.append(line)
        previous_blank = is_blank
    return collapsed


def _is_unsafe_input_control(character: str) -> bool:
    return unicodedata.category(character) == "Cc" and character not in _ALLOWED_INPUT_CONTROL_CHARS


def _is_removed_output_control(character: str) -> bool:
    category = unicodedata.category(character)
    return category in {"Cc", "Cf"} and character != "\t"
