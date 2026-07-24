from __future__ import annotations

from fastapi import status
from fastapi.testclient import TestClient

from app.api.dependencies import get_readiness_service
from app.core.config import Settings
from app.core.errors import ApplicationError
from app.main import create_app
from tests.conftest import assert_uuid


class FailingReadinessService:
    def ensure_ready(self) -> None:
        raise ApplicationError(
            code="DATABASE_UNAVAILABLE",
            message="Database readiness check failed.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


def test_missing_correlation_id_generates_uuid(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert_uuid(response.headers["X-Correlation-ID"])


def test_valid_incoming_correlation_id_is_preserved(client: TestClient) -> None:
    incoming = "11111111-2222-4333-8444-555555555555"

    response = client.get("/health/live", headers={"X-Correlation-ID": incoming})

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == incoming


def test_invalid_incoming_correlation_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Correlation-ID": "../bad-id"})

    assert response.status_code == 200
    generated = response.headers["X-Correlation-ID"]
    assert generated != "../bad-id"
    assert_uuid(generated)


def test_error_body_and_header_share_correlation_id(settings: Settings) -> None:
    app = create_app(settings)
    app.dependency_overrides[get_readiness_service] = lambda: FailingReadinessService()

    with TestClient(app) as client:
        response = client.get(
            "/health/ready",
            headers={"X-Correlation-ID": "not-a-safe-correlation-id"},
        )

    assert response.status_code == 503
    header_id = response.headers["X-Correlation-ID"]
    body_id = response.json()["error"]["correlation_id"]
    assert header_id == body_id
    assert header_id != "not-a-safe-correlation-id"
    assert_uuid(header_id)
