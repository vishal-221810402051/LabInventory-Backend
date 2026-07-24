from __future__ import annotations

from fastapi.testclient import TestClient


def test_openapi_contains_phase0_endpoints(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/health/live" in paths
    assert "/health/ready" in paths
    assert "/api/v1/system/info" in paths


def test_openapi_contains_phase1_capture_endpoints(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/capture-sessions" in paths
    assert "/api/v1/capture-sessions/{capture_session_id}" in paths
    assert "/api/v1/capture-sessions/{capture_session_id}/photos" in paths
    assert "/api/v1/capture-sessions/{capture_session_id}/complete" in paths
    assert "multipart/form-data" in paths["/api/v1/capture-sessions/{capture_session_id}/photos"][
        "post"
    ]["requestBody"]["content"]


def test_openapi_contains_phase2_ocr_endpoints(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    ocr_path = "/api/v1/capture-sessions/{capture_session_id}/ocr-results"
    assert ocr_path in paths
    assert "post" in paths[ocr_path]
    assert "get" in paths[ocr_path]
    assert "Idempotency-Key" in {
        parameter["name"] for parameter in paths[ocr_path]["post"]["parameters"]
    }
