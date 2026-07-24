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
    def read(self, key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def exists(self, key: str) -> bool:
        raise NotImplementedError
