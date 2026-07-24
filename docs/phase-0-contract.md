# LabInventory Phase 0 Contract

Phase 0 exposes only the backend foundation needed by the Android-first client and future phases.

## Endpoints

### GET /health/live

Returns `200 OK`.

```json
{
  "status": "ok"
}
```

This endpoint does not access PostgreSQL.

### GET /health/ready

Returns `200 OK` when PostgreSQL is reachable.

```json
{
  "status": "ready",
  "database": "available"
}
```

When PostgreSQL is unavailable, returns `503 Service Unavailable`.

```json
{
  "error": {
    "code": "DATABASE_UNAVAILABLE",
    "message": "Database readiness check failed.",
    "details": null,
    "correlation_id": "00000000-0000-4000-8000-000000000000"
  }
}
```

### GET /api/v1/system/info

Returns `200 OK`.

```json
{
  "application": "LabInventory",
  "api_version": "v1",
  "protocol_version": 1,
  "service_type": "_labinventory._tcp.",
  "service_name": "LabInventory Backend",
  "instance_id": "00000000-0000-4000-8000-000000000000",
  "pairing_required": true,
  "capabilities": [
    "health",
    "discovery"
  ]
}
```

`instance_id` is generated once and persisted under `INSTANCE_DATA_ROOT`.

## Error Contract

Controlled API errors use this envelope:

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

Unexpected exceptions are logged server-side and returned as a generic `INTERNAL_SERVER_ERROR`.

## Correlation IDs

Every response includes `X-Correlation-ID`.

The backend preserves syntactically valid UUID correlation IDs from incoming requests. Missing, malformed, or oversized values are replaced with a UUID4. The same ID appears in controlled error responses.

## Protocol Compatibility

Phase 0 fixes:

- `api_version`: `v1`
- `protocol_version`: `1`
- `service_type`: `_labinventory._tcp.`

Android clients should reject incompatible values before attempting future pairing or sync flows.

## mDNS Records

The service advertises:

- Zeroconf type: `_labinventory._tcp.local.`
- Instance name: `LabInventory Backend._labinventory._tcp.local.`
- TXT: `api=v1`
- TXT: `protocol=1`
- TXT: `pairing=required`

Discovery is not authentication. It only helps the Android app find the laptop backend on the local network. Pairing and authorization belong to later phases.
