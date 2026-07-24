from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.services.system_info import InstanceIdStore
from tests.conftest import assert_uuid


def test_instance_id_first_call_creates_valid_id(tmp_path: Path) -> None:
    store = InstanceIdStore(tmp_path)

    instance_id = store.get_or_create()

    assert_uuid(str(instance_id))
    assert (tmp_path / "backend-instance-id").exists()


def test_instance_id_later_reads_return_same_id(tmp_path: Path) -> None:
    store = InstanceIdStore(tmp_path)

    first = store.get_or_create()
    second = InstanceIdStore(tmp_path).get_or_create()

    assert first == second


def test_invalid_persisted_instance_id_is_replaced(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "backend-instance-id").write_text("not-a-uuid\n", encoding="utf-8")
    store = InstanceIdStore(tmp_path)

    instance_id = store.get_or_create()

    assert_uuid(str(instance_id))
    persisted = (tmp_path / "backend-instance-id").read_text(encoding="utf-8").strip()
    assert persisted == str(instance_id)


def test_concurrent_instance_id_initialization_is_stable(tmp_path: Path) -> None:
    store = InstanceIdStore(tmp_path)

    with ThreadPoolExecutor(max_workers=8) as executor:
        values = list(executor.map(lambda _: store.get_or_create(), range(16)))

    assert len(set(values)) == 1
