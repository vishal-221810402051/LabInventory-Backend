from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import assert_uuid


def test_system_info_matches_phase0_contract(client: TestClient) -> None:
    response = client.get("/api/v1/system/info")

    assert response.status_code == 200
    body = response.json()
    assert_uuid(body["instance_id"])
    assert body == {
        "application": "LabInventory",
        "api_version": "v1",
        "protocol_version": 1,
        "service_type": "_labinventory._tcp.",
        "service_name": "LabInventory Backend",
        "instance_id": body["instance_id"],
        "pairing_required": True,
        "capabilities": ["health", "discovery"],
    }


def test_instance_id_remains_stable_across_app_reinstantiation(
    tmp_path: Path,
    settings: Settings,
) -> None:
    instance_root = tmp_path / "instance"
    first_settings = settings.model_copy(update={"instance_data_root": instance_root})
    second_settings = settings.model_copy(update={"instance_data_root": instance_root})

    with TestClient(create_app(first_settings)) as client:
        first_id = client.get("/api/v1/system/info").json()["instance_id"]

    with TestClient(create_app(second_settings)) as client:
        second_id = client.get("/api/v1/system/info").json()["instance_id"]

    assert first_id == second_id
