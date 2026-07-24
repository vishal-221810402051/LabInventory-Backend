# LabInventory Backend

LabInventory is a laptop-hosted backend for an Android-first lab inventory system. Phase 0 builds the service foundation: health checks, readiness, system information, stable backend identity, structured logs, correlation IDs, PostgreSQL/Alembic wiring, local storage safety, Docker, and mDNS discovery support. Phase 1 adds draft capture-session persistence and secure local photo ingestion. Phase 2 adds Android-supplied OCR result ingestion, deterministic text normalization, persistence, and retrieval. Phase 3 adds controlled, text-only OpenAI item interpretation suggestions for completed captures.

## Phase 0 Scope

Included:

- FastAPI with typed response schemas
- Pydantic v2 settings
- SQLAlchemy 2 with Psycopg 3
- PostgreSQL 16 through Docker Compose
- Alembic baseline migration
- Structured JSON logs to stdout
- `X-Correlation-ID` middleware
- Common API error envelope
- `/health/live`
- `/health/ready`
- `/api/v1/system/info`
- Persistent backend instance UUID
- mDNS/DNS-SD support with a Windows host companion
- Local disk storage abstraction
- Pytest, Ruff, Mypy, and GitHub Actions CI

Not included in Phase 0:

- Inventory items
- Stock transactions
- Projects
- Users or authentication
- Pairing or device authorization
- Upload endpoints
- OCR
- GPT or AI classification
- Synchronization
- CSV exports
- Analytics

## Phase 1 Scope

Included:

- `POST /api/v1/capture-sessions`
- `GET /api/v1/capture-sessions/{capture_session_id}`
- `POST /api/v1/capture-sessions/{capture_session_id}/photos`
- `POST /api/v1/capture-sessions/{capture_session_id}/complete`
- PostgreSQL-backed capture drafts and photo metadata
- Idempotent create and upload behavior
- Streamed JPEG, PNG, and WebP upload validation
- Local persistence under the `upload-data` Docker volume
- Completion validation into `READY_FOR_PROCESSING`

Not included in Phase 1:

- OCR
- GPT or AI classification
- Inventory item creation
- Authentication, pairing, or device authorization
- Background processing or Android sync orchestration
- Public file serving for uploaded photos

## Phase 2 Scope

Included:

- `POST /api/v1/capture-sessions/{capture_session_id}/ocr-results`
- `GET /api/v1/capture-sessions/{capture_session_id}/ocr-results`
- PostgreSQL-backed OCR result persistence
- Android-supplied OCR model linked to an uploaded capture photo
- Deterministic Unicode/text normalization
- Idempotent OCR ingestion
- Status-specific OCR validation

Not included in Phase 2:

- GPT or AI item identification
- Automatic category or manufacturer inference
- Inventory item creation
- Server-side image OCR
- Authentication, pairing, or device authorization
- Background processing or sync orchestration

## Phase 3 Scope

Included:

- `GET /api/v1/ai/status`
- `POST /api/v1/capture-sessions/{capture_session_id}/interpretations`
- `GET /api/v1/capture-sessions/{capture_session_id}/interpretations`
- `GET /api/v1/capture-sessions/{capture_session_id}/interpretations/{interpretation_id}`
- PostgreSQL-backed AI interpretation persistence
- Official OpenAI Python SDK with Responses API
- Strict JSON schema structured output
- Provider abstraction so normal tests never call OpenAI
- Idempotent interpretation requests
- Safe provider failure persistence
- Token and latency metadata

Not included in Phase 3:

- Inventory item creation
- Stock changes
- Automatic approval
- Background processing
- Server-side OCR
- Image input to OpenAI
- Web search, file search, code interpreter, function tools, or remote MCP

AI interpretation output is not authoritative. It is an untrusted suggestion requiring explicit human review on Android before any future inventory workflow may use it.

## Architecture

Routes are intentionally thin. API handlers call services, services call infrastructure, and shared concerns live in `app/core`.

```text
app/
  api/             FastAPI dependencies, error handlers, route modules
  core/            Settings, logging, correlation IDs, application errors
  db/              SQLAlchemy base and session factory
  domain/          Phase-specific business enums and normalization rules
  discovery/       mDNS configuration, IP selection, Zeroconf advertiser
  repositories/    Database query helpers
  schemas/         Typed API response and error models
  services/        Readiness and system-info services
  storage/         Storage interface and local-disk implementation
```

Alembic is wired to `app.db.base.Base.metadata`. Phase 0 has an empty baseline migration so future model migrations have a clean root.

## Required Software

- Docker Desktop
- Docker Compose
- Windows PowerShell
- Git
- Python for the optional Windows mDNS companion virtual environment

The backend runtime uses Python 3.11 inside Docker. It does not depend on globally installed host Python packages.

## Environment Setup

Create a local `.env` from the example:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and change `POSTGRES_PASSWORD` for your local machine. Do not commit `.env`.

AI interpretation is disabled by default. To enable it locally, set values in `.env`:

```text
AI_INTERPRETATION_ENABLED=true
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-mini
OPENAI_STORE=false
```

Do not commit a real key. `OPENAI_API_KEY` is read only by the backend process and is never returned through an endpoint, sent to Android, or logged. For controlled production behavior, prefer a pinned model snapshot rather than an unpinned moving target.

## Build And Startup

```powershell
docker compose config
docker compose build
docker compose up -d db backend
```

The API is available at:

- `http://localhost:8000/health/live`
- `http://localhost:8000/health/ready`
- `http://localhost:8000/api/v1/system/info`
- `http://localhost:8000/api/v1/ai/status`
- `http://localhost:8000/docs`
- `http://localhost:8000/redoc`
- `http://localhost:8000/openapi.json`

## Alembic Commands

```powershell
docker compose exec -T backend alembic heads
docker compose exec -T backend alembic history
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend alembic current
```

Do not use `Base.metadata.create_all()` at runtime.

## Tests

```powershell
docker compose exec -T backend python -m compileall app tests tools
docker compose exec -T backend pytest -q
```

Run the full safe validation script:

```powershell
.\scripts\validate-phase0.ps1
```

The script validates Compose, builds services, starts containers, applies migrations, runs tests, calls all Phase 0 endpoints, checks correlation headers, restarts only the backend container to verify the stable instance ID, and prints Git status. It does not delete volumes.

Run the Phase 1 validation script:

```powershell
.\scripts\validate-phase1.ps1
```

The Phase 1 script validates Compose, starts DB and backend, applies Alembic, checks the single migration head, compiles `app`, `tests`, and `tools`, runs Pytest, Ruff, and Mypy, calls Phase 0 endpoints, creates a sample capture, uploads a tiny generated JPEG from a temporary host directory, completes the capture, fetches it, validates OpenAPI surfaces, removes temporary host files, and prints Git status. It does not delete Docker volumes.

Run the Phase 2 validation script:

```powershell
.\scripts\validate-phase2.ps1
```

The Phase 2 script validates Compose, starts DB and backend, applies Alembic, compiles, tests, runs Ruff and Mypy, verifies Phase 0 endpoints, creates a sample photo capture, uploads a tiny generated JPEG, submits and replays OCR, retrieves OCR results, completes the capture, verifies new OCR is rejected after completion, removes temporary host files, and prints Git status. It does not delete Docker volumes.

Run the Phase 3 validation script:

```powershell
.\scripts\validate-phase3.ps1
```

The Phase 3 script validates Compose, starts DB and backend in safe AI-disabled mode, applies Alembic, compiles, tests, runs Ruff and Mypy, verifies Phase 0 endpoints, checks AI status, verifies disabled and unconfigured AI behavior, validates OpenAPI, removes no Docker volumes, and makes no live OpenAI request.

Live OpenAI validation is opt-in and billable:

```powershell
.\scripts\validate-phase3-live.ps1 -ConfirmLiveAi
```

The live script requires `AI_INTERPRETATION_ENABLED=true` and `OPENAI_API_KEY`, creates a temporary sample capture, uploads a tiny image, uploads sample OCR, completes the capture, requests one interpretation, replays it to verify idempotency, and prints only the safe structured result.

## Phase 3 AI Safety

The backend sends only text derived from persisted capture/OCR/manual data:

- capture mode
- manual name, unit, category hint, notes, and quantity as contextual metadata
- corrected OCR text when present
- otherwise normalized OCR text
- explicit no-text OCR state
- locale

The backend does not send image bytes, image paths, original filenames, database IDs, API keys, correlation IDs, internal logs, or unrelated capture data. Combined manual/OCR source text is rejected above 20,000 Unicode characters rather than silently truncated.

OpenAI requests use `store=false`, no tools, no web search, no conversation history, no image input, and strict JSON schema output. Provider output is validated again with Pydantic before storage. Prompt-injection defenses treat OCR and manual fields as untrusted data; instructions inside label text are ignored, URLs are not followed, and the model is told to return insufficient information rather than invent technical specifications, manufacturers, part numbers, quantities, or transactions.

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

Unknown model categories or units are rejected. The model must use `null` when evidence is insufficient. No percentage confidence is returned; `evidence_strength` is qualitative only.

## Phase 1 API Examples

Create a capture session. The `Idempotency-Key` header must equal `client_capture_id`.

```powershell
$captureId = [guid]::NewGuid()
$body = @{
  client_capture_id = "$captureId"
  capture_mode = "PHOTO"
  captured_at = "2026-07-24T18:30:00Z"
  manual_entry = @{
    name = "HC-SR04 ultrasonic sensor"
    quantity = "2.000000"
    unit = "pcs"
    category_hint = "Sensors/Modules"
    notes = "Stored in drawer A3"
  }
} | ConvertTo-Json -Depth 4

Invoke-RestMethod `
  -Uri "http://localhost:8000/api/v1/capture-sessions" `
  -Method Post `
  -ContentType "application/json" `
  -Headers @{ "Idempotency-Key" = "$captureId" } `
  -Body $body
```

Quantities must be JSON strings, not floating-point numbers. They must be greater than zero, finite, plain decimal notation, and have no more than 6 fractional digits. Responses emit quantities as canonical JSON strings.

Upload a photo. The `Idempotency-Key` header must equal `client_photo_id`.

```powershell
$photoId = [guid]::NewGuid()
$sha = (Get-FileHash -Algorithm SHA256 .\sample.jpg).Hash.ToLowerInvariant()

curl.exe -sS -X POST `
  "http://localhost:8000/api/v1/capture-sessions/$captureId/photos" `
  -H "Idempotency-Key: $photoId" `
  -F "client_photo_id=$photoId" `
  -F "sha256=$sha" `
  -F "file=@sample.jpg;type=image/jpeg"
```

Supported media types are `image/jpeg`, `image/png`, and `image/webp`. The limit is 15 MiB. The backend validates MIME type, image signature, size, non-empty content, and SHA-256 while streaming. Original filenames are ignored, and files are persisted below `captures/{capture_session_id}/{photo_id}.{extension}` in the configured upload root. Uploaded files are not exposed through a static route.

Complete a capture:

```powershell
Invoke-RestMethod `
  -Uri "http://localhost:8000/api/v1/capture-sessions/$captureId/complete" `
  -Method Post
```

Completion rules:

- `MANUAL`: name, quantity, and unit required
- `PHOTO`: at least one valid photo, quantity, and unit required; name optional
- `PHOTO_WITH_MANUAL`: at least one valid photo, name, quantity, and unit required

Create and upload requests are idempotent by client UUID. Exact replays return the original server record; conflicting replays return `409`. Completed captures cannot accept more photo uploads in Phase 1.

Security limitations: Phase 1 still has no authentication, pairing, or device authorization. Run it only on a trusted local network. Discovery is not authorization.

Data warning: uploads and database rows persist in Docker named volumes. Do not run `docker compose down -v` unless you intentionally want to erase local development data.

## Phase 2 OCR Examples

Phase 2 expects Android to run OCR and submit the result. The backend stores raw OCR exactly as supplied after validation, generates `normalized_text`, and stores `corrected_text` after applying the same conservative normalization. It does not infer item identity, category, quantity, manufacturer, or inventory records.

Preferred synchronization order:

1. Create capture session.
2. Upload photo.
3. Upload OCR result.
4. Complete capture session.

Submit OCR. The `Idempotency-Key` header must equal `client_ocr_id`.

```powershell
$ocrId = [guid]::NewGuid()
$ocrBody = @{
  client_ocr_id = "$ocrId"
  client_photo_id = "$photoId"
  engine = "ML_KIT_TEXT_RECOGNITION_V2"
  engine_version = $null
  status = "SUCCEEDED"
  processed_at = "2026-07-25T10:00:00Z"
  raw_text = "HC-SR04`r`nUltrasonic   Sensor`r`n5V"
  corrected_text = "HC-SR04`nUltrasonic Sensor`n5V"
  block_count = 1
  line_count = 3
  element_count = 5
  detected_language_tags = @("en")
}

Invoke-RestMethod `
  -Uri "http://localhost:8000/api/v1/capture-sessions/$captureId/ocr-results" `
  -Method Post `
  -ContentType "application/json" `
  -Headers @{ "Idempotency-Key" = "$ocrId" } `
  -Body ($ocrBody | ConvertTo-Json -Depth 5)
```

List OCR results:

```powershell
Invoke-RestMethod `
  -Uri "http://localhost:8000/api/v1/capture-sessions/$captureId/ocr-results" `
  -Method Get
```

Normalization uses Unicode NFKC, converts CRLF and CR to LF, rejects NUL, removes unsafe controls from normalized output, trims lines, collapses tabs and repeated horizontal whitespace, removes empty boundary lines, and collapses repeated internal blank lines to one blank line. It preserves case, punctuation, line order, and part numbers.

Limits: raw and corrected text are each limited to 50,000 Unicode characters. `engine_version` is limited to 100 characters. Up to 16 language tags are accepted; each tag is limited to 35 characters. Language tags are trimmed, NFKC-normalized, underscore-to-hyphen normalized, lowercased, and de-duplicated in first-seen order.

Statuses:

- `SUCCEEDED`: usable raw text and at least one line required
- `NO_TEXT`: raw and corrected text must be empty after normalization; all counts must be zero
- `FAILED`: partial safe raw text is allowed; corrected text must be empty; diagnostic stack traces are rejected

Create and OCR requests are idempotent by client UUID. Exact OCR replays return the original server record; conflicting replays return `409`. New OCR is rejected once a capture is `READY_FOR_PROCESSING`, while exact replay of an OCR result stored before completion still returns `200`.

Security and privacy notes: Phase 2 still has no authentication, pairing, or device authorization. OCR text may contain sensitive labels or notes, so application logs include only counts and IDs, not raw or corrected OCR content.

## Safe Shutdown

```powershell
.\scripts\stop.ps1
```

This stops services without deleting PostgreSQL data, upload data, or backend instance data.

## Stable Instance ID

The backend writes a UUID under `INSTANCE_DATA_ROOT`. Docker Compose mounts that path on the named `instance-data` volume, so the same backend identity survives API process restarts, backend container restarts, and laptop restarts while Docker volumes remain intact.

Deleting the `instance-data` Docker volume will generate a new identity.

## mDNS Discovery

Android discovers the backend through:

- Service type: `_labinventory._tcp.`
- Zeroconf type: `_labinventory._tcp.local.`
- Instance name: `LabInventory Backend._labinventory._tcp.local.`
- TXT records: `api=v1`, `protocol=1`, `pairing=required`

Docker Desktop on Windows may not reliably multicast from inside Linux containers to physical Android devices. For Windows Docker Desktop, use the host companion:

```powershell
.\scripts\start-mdns.ps1
```

The companion uses its own lightweight virtual environment at `.mdns-venv`. That environment intentionally installs only the host-advertiser dependencies: HTTPX, Pydantic, Pydantic Settings, python-json-logger, and Zeroconf. It does not install FastAPI, SQLAlchemy, Alembic, Psycopg, or Uvicorn.

Core logging used by the companion must stay framework-neutral. If the companion fails during import with a missing FastAPI or Starlette module, fix the backend import dependency direction rather than installing FastAPI into `.mdns-venv`.

Verify the companion interpreter and import path:

```powershell
.\.mdns-venv\Scripts\python.exe -c "import importlib.util; print(importlib.util.find_spec('fastapi'))"

.\.mdns-venv\Scripts\python.exe -c "import app.core.request_context; import app.core.logging; import tools.mdns_advertiser; print('mDNS imports OK')"
```

The first command should print `None`. The second should print `mDNS imports OK`.

Expected startup shape:

```text
Using mDNS Python: <repo>\.mdns-venv\Scripts\python.exe
Verifying backend before mDNS advertisement
Backend ready
Backend contract compatible
Advertising LabInventory Backend
Address: <laptop-lan-ip>
Port: 8000
Service type: _labinventory._tcp.local.
Press Ctrl+C to stop
```

The companion verifies:

- `http://127.0.0.1:8000/health/ready`
- `http://127.0.0.1:8000/api/v1/system/info`

It refuses incompatible backends and advertises the laptop LAN IPv4 address, not `127.0.0.1`, `0.0.0.0`, APIPA, or a public address.

Use an override only for troubleshooting:

```powershell
$env:MDNS_ADVERTISE_IP="192.168.1.20"
.\scripts\start-mdns.ps1
```

Discovery is not authentication. It only helps the Android app find the service. Pairing and authorization are future phases.

## Windows Firewall

Allow inbound traffic on the Private network profile where possible:

- TCP `8000` for the backend API
- UDP `5353` for mDNS

Guest Wi-Fi, AP/client isolation, VPN clients, and corporate endpoint security tools can block Android-to-laptop discovery or API access.

## Physical Android Testing

1. Connect the laptop and Android device to the same private LAN.
2. Start Docker Compose.
3. Start the Windows mDNS companion.
4. Confirm Android discovers `_labinventory._tcp.`.
5. Confirm Android can call `http://<laptop-lan-ip>:8000/health/live`.

If discovery fails but direct IP works, check UDP 5353, VPNs, Wi-Fi isolation, and Windows Firewall.

## Data Volumes

Compose creates named volumes:

- `postgres-data`
- `instance-data`
- `upload-data`

Use `docker compose stop` for routine shutdown. Avoid `docker compose down -v` unless you intentionally want to erase persisted data.

## Troubleshooting

Check service state:

```powershell
docker compose ps
docker compose logs backend
docker compose logs db
```

Check API health:

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/health/live" -Method Get
Invoke-RestMethod -Uri "http://localhost:8000/health/ready" -Method Get
```

Check the correlation header on Windows PowerShell:

```powershell
$response = Invoke-WebRequest `
    -Uri "http://localhost:8000/health/live" `
    -Method Get `
    -UseBasicParsing

$response.Headers["X-Correlation-ID"]
```

Check mDNS companion logs in the PowerShell window where it is running.

If the mDNS companion exits before printing `Verifying backend before mDNS advertisement`, run the interpreter checks from the mDNS section. If `fastapi` is found in `.mdns-venv`, the virtual environment is too heavy and should be recreated. If importing `app.core.logging` or `tools.mdns_advertiser` fails because FastAPI is missing, a framework-specific import has leaked into the host companion path.

### Stale PostgreSQL Password After `.env` Changes

PostgreSQL reads `POSTGRES_USER`, `POSTGRES_DB`, and `POSTGRES_PASSWORD` only when its data directory is initialized for the first time. If the named `postgres-data` Docker volume already exists, PostgreSQL logs this during startup:

```text
Database directory appears to contain a database; Skipping initialization
```

Changing `.env` later updates the backend container environment and the DB container environment, but it does not rewrite the already-created PostgreSQL role password inside the existing data volume. The symptom is:

- `/health/live` returns `ok`
- `/api/v1/system/info` returns normally
- `/health/ready` returns `DATABASE_UNAVAILABLE`
- DB logs contain `password authentication failed for user "labinventory"`

Diagnose without printing passwords:

```powershell
docker compose exec -T backend python -c "import os; from sqlalchemy.engine import make_url; print(make_url(os.environ['DATABASE_URL']).render_as_string(hide_password=True))"

docker compose exec -T backend python -c "import os, hashlib; from sqlalchemy.engine import make_url; password = make_url(os.environ['DATABASE_URL']).password or ''; print(hashlib.sha256(password.encode()).hexdigest())"

docker compose exec -T db sh -lc 'printf "%s" "$POSTGRES_PASSWORD" | sha256sum'

docker compose logs --tail 100 db
```

If the backend and DB password hashes match but PostgreSQL still rejects authentication and reports skipped initialization, the persisted PostgreSQL role password is stale.

For Phase 0 only, after confirming there is no real inventory or user data, use the guarded reset script:

```powershell
.\scripts\reset-phase0-database.ps1 -ConfirmPhase0DataLoss
```

The script removes only the PostgreSQL data volume after checking that the database has no application-domain tables. It preserves the backend instance-data and upload volumes, recreates PostgreSQL, applies Alembic, and verifies `/health/ready`.

Do not use this reset script after real inventory, user, upload, sync, or transaction data exists.

## Current Known Limitations

- No authentication or pairing yet.
- No upload endpoints yet.
- No inventory domain models yet.
- No Android synchronization endpoints yet.
- Real multicast behavior must be tested on the actual Windows LAN and Android device; unit tests only validate mDNS metadata and address-selection rules.
