from __future__ import annotations

from fastapi.testclient import TestClient


def test_openapi_contains_phase0_endpoints(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/health/live" in paths
    assert "/health/ready" in paths
    assert "/api/v1/system/info" in paths
