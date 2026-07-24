# Phase 2 Validation

Run from the backend repository root on `phase/2-label-ocr`.

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

Migration round trip:

```powershell
docker compose exec -T backend alembic downgrade 202607240002
docker compose exec -T backend alembic upgrade head
```

The downgrade removes Phase 2 OCR rows and table definitions. It does not delete Docker volumes, but do not run it against OCR data you need to keep.

Validate Phase 0:

```powershell
Invoke-RestMethod "http://localhost:8000/health/live"
Invoke-RestMethod "http://localhost:8000/health/ready"
Invoke-RestMethod "http://localhost:8000/api/v1/system/info"
```

Run:

```powershell
.\scripts\validate-phase2.ps1
git diff --check
git status
```

## Sample OCR Submit

```powershell
$ocrId = [guid]::NewGuid()
$body = @{
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
  -Body ($body | ConvertTo-Json -Depth 5)
```
