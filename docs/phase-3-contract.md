# Phase 3 AI Interpretation Contract

Phase 3 adds backend-controlled, text-only OpenAI item interpretation for completed captures. Results are untrusted suggestions for human review on Android. The backend does not create inventory items, change stock, approve suggestions, run server-side OCR, send image bytes, or use OpenAI tools.

## Configuration

The feature is disabled by default:

```text
AI_INTERPRETATION_ENABLED=false
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-mini
OPENAI_STORE=false
```

`OPENAI_API_KEY` is read only by the backend process. It is never returned to Android, logged, committed, or placed in Dockerfile defaults. `OPENAI_MODEL` is configurable; production deployments should prefer a pinned model snapshot for repeatable behavior.

`/health/ready` does not require an OpenAI key.

## Status

`GET /api/v1/ai/status`

```json
{
  "enabled": false,
  "configured": false,
  "provider": "OPENAI",
  "model": "gpt-5-mini",
  "prompt_version": "phase3-item-interpretation-v1",
  "schema_version": "1",
  "image_input_enabled": false
}
```

The response never exposes the API key.

## Create Interpretation

`POST /api/v1/capture-sessions/{capture_session_id}/interpretations`

Required header:

`Idempotency-Key: <client_interpretation_id UUID>`

Request:

```json
{
  "client_interpretation_id": "550e8400-e29b-41d4-a716-446655440020",
  "requested_at": "2026-07-25T15:00:00Z",
  "requested_locale": "en"
}
```

Supported locale:

- `en`

Responses:

- `201 Created` for the first terminal interpretation request
- `200 OK` for exact terminal replay
- `202 Accepted` for exact replay while the original row is `PROCESSING`
- `409 AI_INTERPRETATION_IDEMPOTENCY_CONFLICT` for conflicting replay

## Response Shape

```json
{
  "id": "UUID",
  "client_interpretation_id": "UUID",
  "capture_session_id": "UUID",
  "status": "SUCCEEDED",
  "provider": "OPENAI",
  "model": "gpt-5-mini",
  "prompt_version": "phase3-item-interpretation-v1",
  "schema_version": "1",
  "suggestion": {
    "result": "SUGGESTION",
    "suggested_name": "Capacitive non-contact liquid level sensor",
    "suggested_category": "Sensors/Modules",
    "suggested_unit": "pcs",
    "manufacturer": null,
    "part_number": "HYB11067",
    "short_description": "Non-contact capacitive liquid-level sensor module.",
    "evidence_strength": "STRONG",
    "evidence": ["OCR contains HYB11067"],
    "warnings": ["Exact electrical specifications were not verified"]
  },
  "input_token_count": 540,
  "output_token_count": 130,
  "total_token_count": 670,
  "latency_ms": 1450,
  "created_at": "2026-07-25T15:00:01Z",
  "updated_at": "2026-07-25T15:00:03Z"
}
```

`suggestion` is `null` for safe failed/refused rows.

Allowed statuses:

- `PROCESSING`
- `SUCCEEDED`
- `INSUFFICIENT_INFORMATION`
- `FAILED`
- `REFUSED`

Allowed result values:

- `SUGGESTION`
- `INSUFFICIENT_INFORMATION`

Allowed evidence strengths:

- `STRONG`
- `MODERATE`
- `WEAK`
- `INSUFFICIENT`

No percentage confidence is returned.

## Taxonomies

Allowed categories:

- `Boards/Compute`
- `Sensors/Modules`
- `Actuators/Drivers`
- `Passive Components`
- `ICs`
- `Wires/Cables`
- `Tubes/Pipes`
- `Mechanical/Fasteners`
- `Tools`
- `Power Supplies`
- `Misc`

Allowed units:

- `pcs`
- `m`
- `ft`
- `ml`
- `l`
- `g`
- `kg`
- `box`
- `roll`
- `spool`
- `kit`

The model must use `null` when evidence is insufficient. Unknown provider output is rejected; the backend does not map arbitrary output to `Misc`.

## Retrieval

`GET /api/v1/capture-sessions/{capture_session_id}/interpretations`

Returns all interpretations sorted by `created_at` and then `id`.

`GET /api/v1/capture-sessions/{capture_session_id}/interpretations/{interpretation_id}`

Returns one interpretation or `404 AI_INTERPRETATION_NOT_FOUND`.

## Eligibility

Interpretation requires `READY_FOR_PROCESSING`.

- `MANUAL`: manual name, quantity, and unit required.
- `PHOTO`: at least one uploaded photo and at least one OCR result with `SUCCEEDED` or `NO_TEXT`.
- `PHOTO_WITH_MANUAL`: valid manual fields, at least one uploaded photo, and OCR required.

The backend never mutates capture status during interpretation.

## OpenAI Use

Production calls use the official OpenAI Python SDK and Responses API with:

- `store=false`
- text input only
- no image input
- no web search
- no file search
- no code interpreter
- no function tools
- no remote MCP
- no conversation history
- strict JSON schema response format

Structured provider output is validated again with Pydantic before persistence.
