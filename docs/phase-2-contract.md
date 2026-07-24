# Phase 2 OCR Contract

Phase 2 stores OCR text supplied by Android. The backend normalizes and persists the text, but it does not interpret it, classify inventory items, call GPT, or run server-side OCR.

## Scope

Included:

- `POST /api/v1/capture-sessions/{capture_session_id}/ocr-results`
- `GET /api/v1/capture-sessions/{capture_session_id}/ocr-results`
- PostgreSQL-backed OCR result persistence
- Deterministic Unicode/text normalization
- Idempotent OCR ingestion
- Validation that OCR references an uploaded photo in the same capture session

Not included:

- GPT, item identification, category inference, inventory creation, server-side OCR
- Authentication, pairing, synchronization orchestration, background processing

## OCR Submit

`POST /api/v1/capture-sessions/{capture_session_id}/ocr-results`

Required header:

`Idempotency-Key: <client_ocr_id UUID>`

Request:

```json
{
  "client_ocr_id": "550e8400-e29b-41d4-a716-446655440010",
  "client_photo_id": "550e8400-e29b-41d4-a716-446655440011",
  "engine": "ML_KIT_TEXT_RECOGNITION_V2",
  "engine_version": null,
  "status": "SUCCEEDED",
  "processed_at": "2026-07-25T10:00:00Z",
  "raw_text": "HC-SR04\r\nUltrasonic   Sensor\r\n5V",
  "corrected_text": "HC-SR04\nUltrasonic Sensor\n5V",
  "block_count": 1,
  "line_count": 3,
  "element_count": 5,
  "detected_language_tags": ["en"]
}
```

Responses:

- `201 Created` for first successful ingestion
- `200 OK` for exact normalized replay
- `409 OCR_IDEMPOTENCY_CONFLICT` for a conflicting replay

## OCR List

`GET /api/v1/capture-sessions/{capture_session_id}/ocr-results`

Returns:

```json
{
  "items": [],
  "total": 0
}
```

Results are sorted by `created_at` and then `id`.

## Text Fields

`raw_text` is stored exactly as Android submitted it after input validation. `normalized_text` is generated from `raw_text`. `corrected_text` is optional and is normalized separately before storage.

Normalization rules:

- Unicode NFKC
- CRLF and CR become LF
- NUL rejected
- unsafe controls rejected on input or removed from normalized output
- horizontal whitespace and tabs collapse to one space
- each line is trimmed
- empty leading and trailing lines are removed
- repeated internal blank lines collapse to one blank line
- case, punctuation, line order, and part numbers are preserved

## Status Rules

- `SUCCEEDED`: raw text must normalize to usable text; `line_count >= 1`
- `NO_TEXT`: raw and corrected text must be empty after normalization; all counts must be zero
- `FAILED`: partial safe raw text is allowed; corrected text must be empty; diagnostic stack traces are rejected

Allowed engine:

- `ML_KIT_TEXT_RECOGNITION_V2`

## Limits

- `raw_text`: 50,000 Unicode characters
- `corrected_text`: 50,000 Unicode characters
- `engine_version`: 100 characters
- `detected_language_tags`: 16 entries
- language tag length: 35 characters
- `block_count`: 0 to 10,000
- `line_count`: 0 to 50,000
- `element_count`: 0 to 250,000

Language tags are NFKC-normalized, trimmed, underscore-to-hyphen normalized, lowercased, and de-duplicated while preserving first-seen order.

## Synchronization Order

Preferred Phase 2 order:

1. Create capture session.
2. Upload photo.
3. Upload OCR result.
4. Complete capture session.

New OCR results are rejected once the capture is `READY_FOR_PROCESSING`. Exact replay of an OCR result stored before completion still returns `200 OK`.

## Errors

All errors use the common envelope. Phase 2 codes include:

- `OCR_IDEMPOTENCY_CONFLICT`
- `INVALID_OCR_IDEMPOTENCY_KEY`
- `UNSUPPORTED_OCR_ENGINE`
- `INVALID_OCR_STATUS`
- `OCR_TEXT_TOO_LARGE`
- `INVALID_OCR_TEXT`
- `OCR_PHOTO_NOT_FOUND`
- `OCR_PHOTO_CAPTURE_MISMATCH`
- `OCR_CAPTURE_ALREADY_COMPLETED`
- `OCR_RESULT_NOT_ACCEPTABLE`
- `CAPTURE_SESSION_NOT_FOUND`
- `VALIDATION_ERROR`
