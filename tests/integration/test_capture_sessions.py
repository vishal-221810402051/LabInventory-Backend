from __future__ import annotations

import asyncio
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.db.models.capture import CapturePhoto
from app.db.session import get_engine, get_session_factory
from app.main import create_app
from app.schemas.capture_sessions import CaptureSessionCreateRequest
from app.services.capture_sessions import MAX_PHOTO_BYTES, CaptureSessionService
from app.storage.base import StorageError
from app.storage.local import LocalStorage

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1",
    reason="PostgreSQL integration tests are opt-in with RUN_DB_TESTS=1.",
)

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"jpeg-test-bytes"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"png-test-bytes"
WEBP_BYTES = b"RIFF\x10\x00\x00\x00WEBP" + b"webp-test-bytes"


class BytesUpload:
    def __init__(self, content: bytes, content_type: str) -> None:
        self.content_type = content_type
        self._content = content
        self._offset = 0

    async def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._content):
            return b""
        if size < 0:
            size = len(self._content) - self._offset
        chunk = self._content[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class FailingCommitStorage(LocalStorage):
    def commit_staged_file(self, staged_path: Path, key: str) -> Path:
        raise StorageError("simulated storage failure")


@pytest.fixture
def db_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=os.environ["DATABASE_URL"],
        cors_origins="",
        instance_data_root=tmp_path / "instance",
        upload_root=tmp_path / "uploads",
        mdns_enabled=False,
    )


@pytest.fixture
def api_client(db_settings: Settings) -> TestClient:
    with TestClient(create_app(db_settings)) as client:
        yield client


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def capture_payload(
    *,
    client_capture_id: UUID | None = None,
    mode: str = "PHOTO",
    manual_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_client_capture_id = client_capture_id or uuid4()
    return {
        "client_capture_id": str(resolved_client_capture_id),
        "capture_mode": mode,
        "captured_at": "2026-07-24T18:30:00Z",
        "manual_entry": manual_entry
        if manual_entry is not None
        else {"quantity": "2.000000", "unit": "pcs"},
    }


def create_capture(
    client: TestClient,
    *,
    mode: str = "PHOTO",
    manual_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = capture_payload(mode=mode, manual_entry=manual_entry)
    response = client.post(
        "/api/v1/capture-sessions",
        json=payload,
        headers={"Idempotency-Key": payload["client_capture_id"]},
    )
    assert response.status_code == 201
    return response.json()


def upload_photo(
    client: TestClient,
    *,
    capture_session_id: str,
    client_photo_id: UUID | None = None,
    content: bytes = JPEG_BYTES,
    content_type: str = "image/jpeg",
    declared_sha256: str | None = None,
) -> tuple[int, dict[str, Any]]:
    resolved_client_photo_id = client_photo_id or uuid4()
    response = client.post(
        f"/api/v1/capture-sessions/{capture_session_id}/photos",
        data={
            "client_photo_id": str(resolved_client_photo_id),
            "sha256": declared_sha256 or sha256_hex(content),
        },
        files={"file": ("ignored-name.bin", content, content_type)},
        headers={"Idempotency-Key": str(resolved_client_photo_id)},
    )
    return response.status_code, response.json()


def test_phase1_migration_tables_exist(db_settings: Settings) -> None:
    inspector = inspect(get_engine(db_settings.effective_database_url))

    assert "capture_sessions" in inspector.get_table_names()
    assert "capture_photos" in inspector.get_table_names()
    assert inspector.get_indexes("capture_sessions")
    assert inspector.get_indexes("capture_photos")


@pytest.mark.parametrize("mode", ["PHOTO", "MANUAL", "PHOTO_WITH_MANUAL"])
def test_create_capture_modes(api_client: TestClient, mode: str) -> None:
    body = create_capture(
        api_client,
        mode=mode,
        manual_entry={"name": "HC-SR04", "quantity": "2.000000", "unit": "pcs"},
    )

    assert body["capture_mode"] == mode
    assert body["status"] == "DRAFT"
    assert body["manual_entry"]["quantity"] == "2.000000"
    assert body["photo_count"] == 0


def test_quantity_025_is_preserved(api_client: TestClient) -> None:
    body = create_capture(
        api_client,
        manual_entry={"name": "resistor pack", "quantity": "0.25", "unit": "pcs"},
    )

    assert body["manual_entry"]["quantity"] == "0.25"


@pytest.mark.parametrize("quantity", ["0", "-1", "1.1234567", 1.25])
def test_invalid_quantities_are_rejected(api_client: TestClient, quantity: object) -> None:
    payload = capture_payload(manual_entry={"quantity": quantity, "unit": "pcs"})

    response = api_client.post(
        "/api/v1/capture-sessions",
        json=payload,
        headers={"Idempotency-Key": payload["client_capture_id"]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_create_idempotency_replay_and_conflict(api_client: TestClient) -> None:
    client_capture_id = uuid4()
    payload = capture_payload(client_capture_id=client_capture_id)

    first = api_client.post(
        "/api/v1/capture-sessions",
        json=payload,
        headers={"Idempotency-Key": str(client_capture_id)},
    )
    replay = api_client.post(
        "/api/v1/capture-sessions",
        json=payload,
        headers={"Idempotency-Key": str(client_capture_id)},
    )
    conflict_payload = payload | {"capture_mode": "MANUAL"}
    conflict = api_client.post(
        "/api/v1/capture-sessions",
        json=conflict_payload,
        headers={"Idempotency-Key": str(client_capture_id)},
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "CAPTURE_IDEMPOTENCY_CONFLICT"


def test_create_requires_matching_idempotency_header(api_client: TestClient) -> None:
    payload = capture_payload()

    missing = api_client.post("/api/v1/capture-sessions", json=payload)
    mismatched = api_client.post(
        "/api/v1/capture-sessions",
        json=payload,
        headers={"Idempotency-Key": str(uuid4())},
    )

    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "INVALID_IDEMPOTENCY_KEY"
    assert mismatched.status_code == 400
    assert mismatched.json()["error"]["code"] == "INVALID_IDEMPOTENCY_KEY"


def test_get_capture_session_and_missing(api_client: TestClient) -> None:
    created = create_capture(api_client)

    existing = api_client.get(f"/api/v1/capture-sessions/{created['id']}")
    missing = api_client.get(f"/api/v1/capture-sessions/{uuid4()}")

    assert existing.status_code == 200
    assert existing.json()["id"] == created["id"]
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "CAPTURE_SESSION_NOT_FOUND"


@pytest.mark.parametrize(
    ("content", "content_type"),
    [(JPEG_BYTES, "image/jpeg"), (PNG_BYTES, "image/png"), (WEBP_BYTES, "image/webp")],
)
def test_valid_photo_uploads(api_client: TestClient, content: bytes, content_type: str) -> None:
    capture = create_capture(api_client)

    response_status, body = upload_photo(
        api_client,
        capture_session_id=capture["id"],
        content=content,
        content_type=content_type,
    )

    assert response_status == 201
    assert body["capture_session_id"] == capture["id"]
    assert body["content_type"] == content_type
    assert body["size_bytes"] == len(content)
    assert body["sha256"] == sha256_hex(content)


def test_invalid_photo_uploads_are_rejected(api_client: TestClient) -> None:
    capture = create_capture(api_client)

    empty_status, empty_body = upload_photo(
        api_client,
        capture_session_id=capture["id"],
        content=b"",
        declared_sha256=sha256_hex(b""),
    )
    oversized = b"\xff\xd8\xff" + (b"x" * MAX_PHOTO_BYTES)
    oversized_status, oversized_body = upload_photo(
        api_client,
        capture_session_id=capture["id"],
        content=oversized,
        declared_sha256=sha256_hex(oversized),
    )
    unsupported_status, unsupported_body = upload_photo(
        api_client,
        capture_session_id=capture["id"],
        content=JPEG_BYTES,
        content_type="text/plain",
    )
    mismatch_status, mismatch_body = upload_photo(
        api_client,
        capture_session_id=capture["id"],
        content=b"%PDF-1.7 not an image",
        content_type="image/jpeg",
        declared_sha256=sha256_hex(b"%PDF-1.7 not an image"),
    )
    hash_status, hash_body = upload_photo(
        api_client,
        capture_session_id=capture["id"],
        content=JPEG_BYTES,
        declared_sha256="0" * 64,
    )

    assert (empty_status, empty_body["error"]["code"]) == (422, "VALIDATION_ERROR")
    assert (oversized_status, oversized_body["error"]["code"]) == (413, "PHOTO_TOO_LARGE")
    assert (unsupported_status, unsupported_body["error"]["code"]) == (
        415,
        "UNSUPPORTED_PHOTO_TYPE",
    )
    assert (mismatch_status, mismatch_body["error"]["code"]) == (
        415,
        "UNSUPPORTED_PHOTO_TYPE",
    )
    assert (hash_status, hash_body["error"]["code"]) == (400, "PHOTO_HASH_MISMATCH")


def test_photo_idempotency_replay_and_conflict(api_client: TestClient) -> None:
    capture = create_capture(api_client)
    client_photo_id = uuid4()

    first_status, first = upload_photo(
        api_client,
        capture_session_id=capture["id"],
        client_photo_id=client_photo_id,
    )
    replay_status, replay = upload_photo(
        api_client,
        capture_session_id=capture["id"],
        client_photo_id=client_photo_id,
    )
    conflict_status, conflict = upload_photo(
        api_client,
        capture_session_id=capture["id"],
        client_photo_id=client_photo_id,
        content=PNG_BYTES,
        content_type="image/png",
    )

    assert first_status == 201
    assert replay_status == 200
    assert replay["id"] == first["id"]
    assert conflict_status == 409
    assert conflict["error"]["code"] == "PHOTO_IDEMPOTENCY_CONFLICT"


def test_upload_to_missing_capture_returns_404(api_client: TestClient) -> None:
    response_status, body = upload_photo(api_client, capture_session_id=str(uuid4()))

    assert response_status == 404
    assert body["error"]["code"] == "CAPTURE_SESSION_NOT_FOUND"


def test_completion_rules_and_idempotency(api_client: TestClient) -> None:
    manual_without_name = create_capture(
        api_client,
        mode="MANUAL",
        manual_entry={"quantity": "1", "unit": "pcs"},
    )
    photo_without_photo = create_capture(
        api_client,
        mode="PHOTO",
        manual_entry={"quantity": "1", "unit": "pcs"},
    )
    photo_with_manual = create_capture(
        api_client,
        mode="PHOTO_WITH_MANUAL",
        manual_entry={"name": "camera", "quantity": "1.000000", "unit": "pcs"},
    )

    manual_response = api_client.post(
        f"/api/v1/capture-sessions/{manual_without_name['id']}/complete"
    )
    photo_response = api_client.post(
        f"/api/v1/capture-sessions/{photo_without_photo['id']}/complete"
    )
    upload_status, _ = upload_photo(api_client, capture_session_id=photo_with_manual["id"])
    complete_response = api_client.post(
        f"/api/v1/capture-sessions/{photo_with_manual['id']}/complete"
    )
    repeated_response = api_client.post(
        f"/api/v1/capture-sessions/{photo_with_manual['id']}/complete"
    )
    upload_after_completion_status, upload_after_completion = upload_photo(
        api_client,
        capture_session_id=photo_with_manual["id"],
        content=PNG_BYTES,
        content_type="image/png",
    )

    assert manual_response.status_code == 409
    assert manual_response.json()["error"]["code"] == "CAPTURE_NOT_COMPLETABLE"
    assert photo_response.status_code == 409
    assert photo_response.json()["error"]["code"] == "CAPTURE_NOT_COMPLETABLE"
    assert upload_status == 201
    assert complete_response.status_code == 200
    assert complete_response.json()["status"] == "READY_FOR_PROCESSING"
    assert repeated_response.status_code == 200
    assert repeated_response.json()["id"] == complete_response.json()["id"]
    assert upload_after_completion_status == 409
    assert upload_after_completion["error"]["code"] == "CAPTURE_ALREADY_COMPLETED"


def test_concurrent_duplicate_capture_creation(db_settings: Settings) -> None:
    client_capture_id = uuid4()
    payload = capture_payload(client_capture_id=client_capture_id)

    def create_once() -> tuple[int, str]:
        session_factory = get_session_factory(db_settings.effective_database_url)
        with session_factory() as session:
            service = CaptureSessionService(session, LocalStorage(db_settings.upload_root))
            request = CaptureSessionCreateRequest.model_validate(payload)
            result = service.create_capture_session(
                request,
                idempotency_key=str(client_capture_id),
            )
            return result.status_code, str(result.response.id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: create_once(), range(2)))

    assert sorted(status_code for status_code, _ in results) == [200, 201]
    assert len({capture_id for _, capture_id in results}) == 1


def test_concurrent_duplicate_photo_upload(db_settings: Settings) -> None:
    client_photo_id = uuid4()
    session_factory = get_session_factory(db_settings.effective_database_url)
    with session_factory() as session:
        service = CaptureSessionService(session, LocalStorage(db_settings.upload_root))
        request = CaptureSessionCreateRequest.model_validate(capture_payload())
        created = service.create_capture_session(
            request,
            idempotency_key=str(request.client_capture_id),
        )
        capture_session_id = created.response.id

    def upload_once() -> tuple[int, str]:
        with session_factory() as session:
            service = CaptureSessionService(session, LocalStorage(db_settings.upload_root))
            result = asyncio.run(
                service.upload_photo(
                    capture_session_id=capture_session_id,
                    client_photo_id=client_photo_id,
                    declared_sha256=sha256_hex(JPEG_BYTES),
                    upload=BytesUpload(JPEG_BYTES, "image/jpeg"),
                    idempotency_key=str(client_photo_id),
                )
            )
            return result.status_code, str(result.response.id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: upload_once(), range(2)))

    with session_factory() as session:
        photo_count = session.scalar(
            select(func.count()).select_from(CapturePhoto).where(
                CapturePhoto.client_photo_id == client_photo_id
            )
        )

    assert sorted(status_code for status_code, _ in results) == [200, 201]
    assert len({photo_id for _, photo_id in results}) == 1
    assert photo_count == 1


def test_db_failure_cleans_up_uploaded_file(
    db_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = get_session_factory(db_settings.effective_database_url)
    with session_factory() as session:
        service = CaptureSessionService(session, LocalStorage(db_settings.upload_root))
        request = CaptureSessionCreateRequest.model_validate(capture_payload())
        capture = service.create_capture_session(
            request,
            idempotency_key=str(request.client_capture_id),
        )

    with session_factory() as session:
        service = CaptureSessionService(session, LocalStorage(db_settings.upload_root))
        client_photo_id = uuid4()

        def fail_commit() -> None:
            raise SQLAlchemyError("simulated commit failure")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(ApplicationError) as exc_info:
            asyncio.run(
                service.upload_photo(
                    capture_session_id=capture.response.id,
                    client_photo_id=client_photo_id,
                    declared_sha256=sha256_hex(JPEG_BYTES),
                    upload=BytesUpload(JPEG_BYTES, "image/jpeg"),
                    idempotency_key=str(client_photo_id),
                )
            )

    stored_files = [
        path
        for path in db_settings.upload_root.rglob("*")
        if path.is_file() and ".staging" not in path.parts
    ]
    assert getattr(exc_info.value, "code", None) == "PHOTO_STORAGE_FAILED"
    assert stored_files == []


def test_storage_failure_rolls_back_photo_row(db_settings: Settings) -> None:
    session_factory = get_session_factory(db_settings.effective_database_url)
    with session_factory() as session:
        service = CaptureSessionService(session, LocalStorage(db_settings.upload_root))
        request = CaptureSessionCreateRequest.model_validate(capture_payload())
        capture = service.create_capture_session(
            request,
            idempotency_key=str(request.client_capture_id),
        )

    client_photo_id = uuid4()
    with session_factory() as session:
        service = CaptureSessionService(session, FailingCommitStorage(db_settings.upload_root))
        with pytest.raises(ApplicationError) as exc_info:
            asyncio.run(
                service.upload_photo(
                    capture_session_id=capture.response.id,
                    client_photo_id=client_photo_id,
                    declared_sha256=sha256_hex(JPEG_BYTES),
                    upload=BytesUpload(JPEG_BYTES, "image/jpeg"),
                    idempotency_key=str(client_photo_id),
                )
            )

    with session_factory() as session:
        photo_count = session.scalar(
            select(func.count()).select_from(CapturePhoto).where(
                CapturePhoto.client_photo_id == client_photo_id
            )
        )

    assert getattr(exc_info.value, "code", None) == "PHOTO_STORAGE_FAILED"
    assert photo_count == 0
