from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class StorageError(ValueError):
    pass


class ObjectStorage(ABC):
    @abstractmethod
    def resolve_safe_key(self, key: str) -> Path:
        raise NotImplementedError

    @abstractmethod
    def save(self, key: str, data: bytes) -> Path:
        raise NotImplementedError

    @abstractmethod
    def create_staging_path(self, suffix: str = ".tmp") -> Path:
        raise NotImplementedError

    @abstractmethod
    def commit_staged_file(self, staged_path: Path, key: str) -> Path:
        raise NotImplementedError

    @abstractmethod
    def discard_path(self, path: Path) -> None:
        raise NotImplementedError

    @abstractmethod
    def read(self, key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def exists(self, key: str) -> bool:
        raise NotImplementedError
