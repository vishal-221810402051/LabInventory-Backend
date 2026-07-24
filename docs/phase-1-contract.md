# Phase 1 Capture Contract

Phase 1 adds draft capture persistence and secure photo ingestion under `/api/v1`.

## Scope

Included:

- Capture sessions with `PHOTO`, `MANUAL`, and `PHOTO_WITH_MANUAL` modes
- Draft and `READY_FOR_PROCESSING` statuses
- Idempotent capture creation
- Idempotent photo upload
- Local upload-volume persistence
- Completion validation

Not included:

- OCR, GPT, AI classification, inventory item creation, background processing
- Authentication, pairing, device authorization, Android sync orchestration
- Public file serving or static upload routes

## Create Capture Session

`POST /api/v1/capture-sessions`

Required header:

`Idempotency-Key: <client_capture_id UUID>`

Request:

```json
{
  "client_capture_id": "550e8400-e29b-41d4-a716-446655440000",
  "capture_mode": "PHOTO",
  "captured_at": "2026-07-24T18:30:00Z",
  "manual_entry": {
    "name": "HC-SR04 ultrasonic sensor",
    "quantity": "2.000000",
    "unit": "pcs",
    "category_hint": "Sensors/Modules",
    "notes": "Stored in drawer A3"
  }
}
```

Responses:

- `201 Created` for first creation
- `200 OK` for exact idempotent replay
- `409 CAPTURE_IDEMPOTENCY_CONFLICT` for the same client ID with a different normalized payload

`manual_entry` may be `null` while the session is still a draft. Completion enforces the mode-specific required metadata.

## Get Capture Session

`GET /api/v1/capture-sessions/{capture_session_id}`

Returns `200 OK` with the persisted draft or completed capture. Missing sessions return `404 CAPTURE_SESSION_NOT_FOUND`.

## Upload Photo

`POST /api/v1/capture-sessions/{capture_session_id}/photos`

Required header:

`Idempotency-Key: <client_photo_id UUID>`

Multipart fields:

- `client_photo_id`: UUID
- `sha256`: lowercase 64-character SHA-256 hex digest of the uploaded bytes
- `file`: JPEG, PNG, or WebP image

Limits and validation:

- Maximum size: 15 MiB
- Empty files are rejected
- Declared MIME type must be `image/jpeg`, `image/png`, or `image/webp`
- File magic bytes must match the declared MIME type
- The streamed SHA-256 digest must match the declared `sha256`
- Original filenames are ignored for storage

Responses:

- `201 Created` for first upload
- `200 OK` for exact photo replay
- `409 PHOTO_IDEMPOTENCY_CONFLICT` for the same photo client ID with different content

Files are stored below:

```text
captures/{capture_session_id}/{photo_id}.{jpg|png|webp}
```

The API does not expose uploaded files publicly.

## Complete Capture

`POST /api/v1/capture-sessions/{capture_session_id}/complete`

Completion is idempotent and returns `200 OK`. First completion changes status to `READY_FOR_PROCESSING`; repeated completion returns the same completed state.

Rules:

- `MANUAL`: name, quantity, and unit required
- `PHOTO`: at least one valid photo, quantity, and unit required; name optional
- `PHOTO_WITH_MANUAL`: at least one valid photo, name, quantity, and unit required

Completed sessions cannot accept more photo uploads in Phase 1.

## Error Envelope

All errors preserve the Phase 0 envelope:

```json
{
  "error": {
    "code": "MACHINE_READABLE_CODE",
    "message": "Human-readable message.",
    "details": null,
    "correlation_id": "00000000-0000-4000-8000-000000000000"
  }
}
```

Phase 1 error codes include:

- `CAPTURE_SESSION_NOT_FOUND`
- `INVALID_IDEMPOTENCY_KEY`
- `CAPTURE_IDEMPOTENCY_CONFLICT`
- `CAPTURE_ALREADY_COMPLETED`
- `CAPTURE_NOT_COMPLETABLE`
- `PHOTO_TOO_LARGE`
- `UNSUPPORTED_PHOTO_TYPE`
- `INVALID_PHOTO_HASH`
- `PHOTO_HASH_MISMATCH`
- `PHOTO_IDEMPOTENCY_CONFLICT`
- `PHOTO_STORAGE_FAILED`
- `VALIDATION_ERROR`
