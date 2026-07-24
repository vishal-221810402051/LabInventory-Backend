# Phase 0 Validation

Run from PowerShell in the repository root.

```powershell
docker compose config
docker compose build
docker compose up -d db backend
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend alembic current
docker compose exec -T backend python -m compileall app
docker compose exec -T backend pytest -q
```

Validate the HTTP contract:

```powershell
Invoke-RestMethod `
    -Uri "http://localhost:8000/health/live" `
    -Method Get

Invoke-RestMethod `
    -Uri "http://localhost:8000/health/ready" `
    -Method Get

Invoke-RestMethod `
    -Uri "http://localhost:8000/api/v1/system/info" `
    -Method Get
```

Validate correlation headers:

```powershell
$response = Invoke-WebRequest `
    -Uri "http://localhost:8000/health/live" `
    -Method Get `
    -UseBasicParsing

$response.Headers["X-Correlation-ID"]
```

Validate stable instance identity:

```powershell
$first = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/system/info" -Method Get
docker compose restart backend
Start-Sleep -Seconds 8
$second = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/system/info" -Method Get
$first.instance_id -eq $second.instance_id
```

Or run the bundled non-destructive validation script:

```powershell
.\scripts\validate-phase0.ps1
```

Stop services without deleting volumes:

```powershell
.\scripts\stop.ps1
```

Do not use `docker compose down -v` unless you intentionally want to delete persisted PostgreSQL, uploads, and backend instance data.
