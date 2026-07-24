# LabInventory Backend

LabInventory is a laptop-hosted backend for an Android-first lab inventory system. Phase 0 builds the service foundation only: health checks, readiness, system information, stable backend identity, structured logs, correlation IDs, PostgreSQL/Alembic wiring, local storage safety, Docker, and mDNS discovery support.

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

## Architecture

Routes are intentionally thin. API handlers call services, services call infrastructure, and shared concerns live in `app/core`.

```text
app/
  api/             FastAPI dependencies, error handlers, route modules
  core/            Settings, logging, correlation IDs, application errors
  db/              SQLAlchemy base and session factory
  discovery/       mDNS configuration, IP selection, Zeroconf advertiser
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
docker compose exec -T backend python -m compileall app
docker compose exec -T backend pytest -q
```

Run the full safe validation script:

```powershell
.\scripts\validate-phase0.ps1
```

The script validates Compose, builds services, starts containers, applies migrations, runs tests, calls all Phase 0 endpoints, checks correlation headers, restarts only the backend container to verify the stable instance ID, and prints Git status. It does not delete volumes.

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
