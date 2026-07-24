# Phase 3 AI Safety

Phase 3 treats all AI output as an untrusted suggestion. Android must present it for explicit human review before any future inventory creation or stock mutation.

## Data Minimization

The provider receives only persisted server-side text context:

- capture mode
- manual name
- quantity as contextual metadata only
- unit
- category hint
- notes
- corrected OCR text when present
- otherwise normalized OCR text
- explicit OCR no-text state
- requested locale

The provider does not receive:

- image bytes
- image paths
- original filenames
- database IDs
- API keys
- correlation IDs
- internal logs
- full provider errors

Combined manual/OCR source text is rejected when it exceeds 20,000 Unicode characters.

## Prompt-Injection Defence

The developer instruction states that JSON payload text is untrusted inventory-label/manual data. It tells the model to ignore instructions contained inside that data, not execute OCR commands, not follow URLs, not use external tools, classify only from supplied evidence, return insufficient information when appropriate, and never invent technical specifications, manufacturers, part numbers, quantities, or transactions.

Untrusted data is supplied as structured JSON rather than concatenated into instruction prose.

## Structured Output

The OpenAI Responses API request uses strict JSON schema output with:

- `type: json_schema`
- `strict: true`
- `additionalProperties: false`
- all fields explicitly required

The backend validates the provider object again with Pydantic and stores only the validated JSON. It does not store arbitrary raw model text or full prompts.

## Failure Safety

Provider timeout, unavailability, refusal, and invalid responses are converted to safe application errors and persisted as terminal interpretation rows with safe error codes. Error responses do not expose API keys, stack traces, provider bodies, OCR text, manual notes, or internal paths.

## Logging

Structured logs include safe metadata such as capture ID, interpretation ID, status, model, prompt version, character counts, token counts, latency, and safe error codes.

Logs do not include OCR text, manual notes, prompts, full structured model output, API keys, image paths, or image bytes.
