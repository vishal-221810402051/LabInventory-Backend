from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def assert_uuid(value: str) -> UUID:
    return UUID(value)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        cors_origins="",
        database_url="postgresql+psycopg://labinventory:password@127.0.0.1:5432/labinventory",
        instance_data_root=tmp_path / "instance",
        upload_root=tmp_path / "uploads",
        mdns_enabled=False,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
