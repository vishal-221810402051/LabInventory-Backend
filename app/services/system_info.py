from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.logging import get_logger
from app.schemas.system import SystemInfoResponse

logger = get_logger(__name__)
PHASE0_CAPABILITIES = ["health", "discovery"]


class InstanceIdStore:
    def __init__(self, root: Path, filename: str = "backend-instance-id") -> None:
        self.root = root
        self.path = root / filename
        self.lock_path = root / f".{filename}.lock"

    def get_or_create(self) -> UUID:
        self.root.mkdir(parents=True, exist_ok=True)
        existing = self._read_valid()
        if existing is not None:
            return existing

        with self._lock():
            existing = self._read_valid()
            if existing is not None:
                return existing
            new_id = uuid4()
            self._write_atomic(str(new_id))
            return new_id

    def _read_valid(self) -> UUID | None:
        if not self.path.exists():
            return None
        value = self.path.read_text(encoding="utf-8").strip()
        try:
            return UUID(value)
        except ValueError:
            logger.warning(
                "Invalid backend instance ID persisted; replacing it.",
                extra={"event": "instance_id.invalid_persisted"},
            )
            return None

    def _write_atomic(self, value: str) -> None:
        with NamedTemporaryFile("w", encoding="utf-8", dir=self.root, delete=False) as handle:
            temp_name = handle.name
            handle.write(f"{value}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, self.path)

    @contextmanager
    def _lock(self, timeout_seconds: float = 5.0) -> Iterator[None]:
        deadline = time.monotonic() + timeout_seconds
        fd: int | None = None
        while fd is None:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    msg = "Timed out waiting for backend instance ID initialization lock."
                    raise TimeoutError(msg) from None
                time.sleep(0.025)
        try:
            yield
        finally:
            os.close(fd)
            try:
                os.unlink(self.lock_path)
            except FileNotFoundError:
                pass


class SystemInfoService:
    def __init__(self, settings: Settings, instance_store: InstanceIdStore) -> None:
        self._settings = settings
        self._instance_store = instance_store
        self._instance_id: UUID | None = None

    def get_info(self) -> SystemInfoResponse:
        if self._instance_id is None:
            self._instance_id = self._instance_store.get_or_create()
        return SystemInfoResponse(
            application="LabInventory",
            api_version=self._settings.api_version,
            protocol_version=self._settings.protocol_version,
            service_type=self._settings.mdns_service_type,
            service_name=self._settings.mdns_service_name,
            instance_id=self._instance_id,
            pairing_required=True,
            capabilities=PHASE0_CAPABILITIES,
        )
