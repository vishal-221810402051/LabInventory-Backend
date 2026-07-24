from __future__ import annotations

from pathlib import Path

import pytest

from app.storage.base import StorageError
from app.storage.local import LocalStorage


def test_local_storage_saves_and_reads_bytes(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)

    storage.save("captures/item-photo.bin", b"image-bytes")

    assert storage.exists("captures/item-photo.bin")
    assert storage.read("captures/item-photo.bin") == b"image-bytes"


@pytest.mark.parametrize("key", ["../secret.txt", "captures/../secret.txt"])
def test_local_storage_rejects_path_traversal(tmp_path: Path, key: str) -> None:
    storage = LocalStorage(tmp_path)

    with pytest.raises(StorageError):
        storage.resolve_safe_key(key)


@pytest.mark.parametrize("key", ["/tmp/secret.txt", "C:\\temp\\secret.txt"])
def test_local_storage_rejects_absolute_paths(tmp_path: Path, key: str) -> None:
    storage = LocalStorage(tmp_path)

    with pytest.raises(StorageError):
        storage.resolve_safe_key(key)
