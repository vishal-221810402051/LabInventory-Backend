from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1",
    reason="PostgreSQL integration tests are opt-in with RUN_DB_TESTS=1.",
)


def test_ready_endpoint_against_postgres(tmp_path: Path) -> None:
    database_url = os.environ["DATABASE_URL"]
    settings = Settings(
        database_url=database_url,
        cors_origins="",
        instance_data_root=tmp_path / "instance",
        upload_root=tmp_path / "uploads",
        mdns_enabled=False,
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "available"}
