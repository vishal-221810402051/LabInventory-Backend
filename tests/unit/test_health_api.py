from __future__ import annotations

from fastapi import status
from fastapi.testclient import TestClient

from app.api.dependencies import get_readiness_service
from app.core.config import Settings
from app.core.errors import ApplicationError
from app.main import create_app
from tests.conftest import assert_uuid


class PassingReadinessService:
    def ensure_ready(self) -> None:
        return None


class FailingReadinessService:
    def ensure_ready(self) -> None:
        raise ApplicationError(
            code="DATABASE_UNAVAILABLE",
            message="Database readiness check failed.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class ExplodingReadinessService:
    def ensure_ready(self) -> None:
        msg = "Readiness should not be called by liveness."
        raise AssertionError(msg)


def test_live_returns_ok(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_live_does_not_depend_on_database_readiness(settings: Settings) -> None:
    app = create_app(settings)
    app.dependency_overrides[get_readiness_service] = lambda: ExplodingReadinessService()

    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_ready_when_database_check_succeeds(settings: Settings) -> None:
    app = create_app(settings)
    app.dependency_overrides[get_readiness_service] = lambda: PassingReadinessService()

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "available"}


def test_ready_returns_common_error_when_database_check_fails(settings: Settings) -> None:
    app = create_app(settings)
    app.dependency_overrides[get_readiness_service] = lambda: FailingReadinessService()

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    correlation_id = body["error"]["correlation_id"]
    assert_uuid(correlation_id)
    assert response.headers["X-Correlation-ID"] == correlation_id
    assert body == {
        "error": {
            "code": "DATABASE_UNAVAILABLE",
            "message": "Database readiness check failed.",
            "details": None,
            "correlation_id": correlation_id,
        }
    }
