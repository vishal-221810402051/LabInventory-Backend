# Phase 1 Validation

Run from the backend repository root on `phase/1-capture-drafts`.

## Required Commands

```powershell
docker compose config
docker compose up -d --build db backend
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend alembic current
docker compose exec -T backend alembic heads
docker compose exec -T backend python -m compileall app tests tools
docker compose exec -T backend pytest -q
docker compose exec -T backend ruff check .
docker compose exec -T backend mypy app tools
```

Validate Phase 0 contracts:

```powershell
Invoke-RestMethod "http://localhost:8000/health/live"
Invoke-RestMethod "http://localhost:8000/health/ready"
Invoke-RestMethod "http://localhost:8000/api/v1/system/info"
```

Run the Phase 1 validation script:

```powershell
.\scripts\validate-phase1.ps1
```

Finish with:

```powershell
git diff --check
git status
```

## Migration Round Trip

For a clean Phase 1 development database, validate:

```powershell
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend alembic downgrade 202607240001
docker compose exec -T backend alembic upgrade head
```

This drops Phase 1 capture tables during downgrade. It does not delete Docker volumes, but do not run the downgrade on a database that contains capture data you need to keep.

## Sample Flow

Create a capture:

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

Upload with `curl.exe`:

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

Complete:

```powershell
Invoke-RestMethod `
  -Uri "http://localhost:8000/api/v1/capture-sessions/$captureId/complete" `
  -Method Post
```
