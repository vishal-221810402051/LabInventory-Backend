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


def test_local_storage_commits_staged_file_atomically(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    staged_path = storage.create_staging_path(".upload")
    staged_path.write_bytes(b"photo")

    target = storage.commit_staged_file(staged_path, "captures/session/photo.jpg")

    assert target == storage.resolve_safe_key("captures/session/photo.jpg")
    assert target.read_bytes() == b"photo"
    assert not staged_path.exists()


def test_local_storage_rejects_staged_path_outside_root(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "uploads")
    outside_path = tmp_path / "outside.tmp"
    outside_path.write_bytes(b"photo")

    with pytest.raises(StorageError):
        storage.commit_staged_file(outside_path, "captures/session/photo.jpg")


@pytest.mark.parametrize("key", ["/tmp/secret.txt", "C:\\temp\\secret.txt"])
def test_local_storage_rejects_absolute_paths(tmp_path: Path, key: str) -> None:
    storage = LocalStorage(tmp_path)

    with pytest.raises(StorageError):
        storage.resolve_safe_key(key)
