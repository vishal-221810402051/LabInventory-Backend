from __future__ import annotations

import posixpath
from pathlib import Path, PurePosixPath, PureWindowsPath

from app.storage.base import ObjectStorage, StorageError


class LocalStorage(ObjectStorage):
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve_safe_key(self, key: str) -> Path:
        normalized_key = self._normalize_key(key)
        root = self.root.resolve()
        candidate = (root / normalized_key).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            msg = "Storage key escapes the configured storage root."
            raise StorageError(msg) from exc
        return candidate

    def save(self, key: str, data: bytes) -> Path:
        target = self.resolve_safe_key(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def read(self, key: str) -> bytes:
        return self.resolve_safe_key(key).read_bytes()

    def delete(self, key: str) -> None:
        try:
            self.resolve_safe_key(key).unlink()
        except FileNotFoundError:
            return

    def exists(self, key: str) -> bool:
        return self.resolve_safe_key(key).exists()

    def _normalize_key(self, key: str) -> str:
        if not key or not key.strip():
            msg = "Storage key must not be empty."
            raise StorageError(msg)
        raw = key.replace("\\", "/").strip()
        if PurePosixPath(raw).is_absolute() or PureWindowsPath(key).is_absolute():
            msg = "Absolute storage keys are not allowed."
            raise StorageError(msg)
        if any(part in {"", ".", ".."} for part in raw.split("/")):
            msg = "Storage key contains an unsafe path segment."
            raise StorageError(msg)
        normalized = posixpath.normpath(raw)
        if normalized == "." or normalized.startswith("../") or "/../" in normalized:
            msg = "Storage key contains path traversal."
            raise StorageError(msg)
        return normalized
