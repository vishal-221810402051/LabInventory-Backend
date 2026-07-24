from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select

from app.core.config import Settings
from app.db.models.capture_ocr_result import CaptureOcrResult
from app.db.session import get_engine, get_session_factory
from app.main import create_app
from app.schemas.capture_sessions import CaptureSessionCreateRequest
from app.schemas.ocr_results import OcrResultCreateRequest
from app.services.capture_sessions import CaptureSessionService
from app.services.ocr_results import OcrResultService
from app.storage.local import LocalStorage

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1",
    reason="PostgreSQL integration tests are opt-in with RUN_DB_TESTS=1.",
)

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"ocr-photo-bytes"


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


def create_capture(client: TestClient) -> dict[str, Any]:
    client_capture_id = uuid4()
    payload = {
        "client_capture_id": str(client_capture_id),
        "capture_mode": "PHOTO",
        "captured_at": "2026-07-25T09:00:00Z",
        "manual_entry": {"name": "OCR sample", "quantity": "1.000000", "unit": "pcs"},
    }
    response = client.post(
        "/api/v1/capture-sessions",
        json=payload,
        headers={"Idempotency-Key": str(client_capture_id)},
    )
    assert response.status_code == 201
    return response.json()


def upload_photo(client: TestClient, capture_session_id: str) -> tuple[UUID, dict[str, Any]]:
    client_photo_id = uuid4()
    response = client.post(
        f"/api/v1/capture-sessions/{capture_session_id}/photos",
        data={"client_photo_id": str(client_photo_id), "sha256": sha256_hex(JPEG_BYTES)},
        files={"file": ("ignored.jpg", JPEG_BYTES, "image/jpeg")},
        headers={"Idempotency-Key": str(client_photo_id)},
    )
    assert response.status_code == 201
    return client_photo_id, response.json()


def capture_with_photo(client: TestClient) -> tuple[dict[str, Any], UUID, dict[str, Any]]:
    capture = create_capture(client)
    client_photo_id, photo = upload_photo(client, capture["id"])
    return capture, client_photo_id, photo


def ocr_payload(
    *,
    client_ocr_id: UUID | None = None,
    client_photo_id: UUID,
    raw_text: str = "HC-SR04\r\nUltrasonic   Sensor\r\n5V",
    corrected_text: str | None = "HC-SR04\nUltrasonic Sensor\n5V",
    status: str = "SUCCEEDED",
    processed_at: str = "2026-07-25T10:00:00Z",
    block_count: int = 1,
    line_count: int = 3,
    element_count: int = 5,
    detected_language_tags: list[str] | None = None,
    engine: str = "ML_KIT_TEXT_RECOGNITION_V2",
) -> dict[str, Any]:
    resolved_client_ocr_id = client_ocr_id or uuid4()
    return {
        "client_ocr_id": str(resolved_client_ocr_id),
        "client_photo_id": str(client_photo_id),
        "engine": engine,
        "engine_version": None,
        "status": status,
        "processed_at": processed_at,
        "raw_text": raw_text,
        "corrected_text": corrected_text,
        "block_count": block_count,
        "line_count": line_count,
        "element_count": element_count,
        "detected_language_tags": detected_language_tags or ["en"],
    }


def post_ocr(
    client: TestClient,
    *,
    capture_session_id: str,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> tuple[int, dict[str, Any]]:
    headers = {}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    response = client.post(
        f"/api/v1/capture-sessions/{capture_session_id}/ocr-results",
        json=payload,
        headers=headers,
    )
    return response.status_code, response.json()


def test_phase2_migration_table_exists(db_settings: Settings) -> None:
    inspector = inspect(get_engine(db_settings.effective_database_url))

    assert "capture_ocr_results" in inspector.get_table_names()
    assert inspector.get_indexes("capture_ocr_results")


def test_successful_ocr_result_creation_and_raw_storage(api_client: TestClient) -> None:
    capture, client_photo_id, photo = capture_with_photo(api_client)
    payload = ocr_payload(client_photo_id=client_photo_id)

    response_status, body = post_ocr(
        api_client,
        capture_session_id=capture["id"],
        payload=payload,
        idempotency_key=payload["client_ocr_id"],
    )

    assert response_status == 201
    assert body["capture_session_id"] == capture["id"]
    assert body["capture_photo_id"] == photo["id"]
    assert body["raw_text"] == "HC-SR04\r\nUltrasonic   Sensor\r\n5V"
    assert body["normalized_text"] == "HC-SR04\nUltrasonic Sensor\n5V"
    assert body["corrected_text"] == "HC-SR04\nUltrasonic Sensor\n5V"


def test_normalization_and_language_tag_handling(api_client: TestClient) -> None:
    capture, client_photo_id, _ = capture_with_photo(api_client)
    payload = ocr_payload(
        client_photo_id=client_photo_id,
        raw_text="  ＨＣ－ＳＲ０４\t\tSensor!!!\r\nPart No. HC-SR04  ",
        corrected_text="  Fixed\t\tText  ",
        line_count=2,
        detected_language_tags=[" EN_us ", "en-US"],
    )

    response_status, body = post_ocr(
        api_client,
        capture_session_id=capture["id"],
        payload=payload,
        idempotency_key=payload["client_ocr_id"],
    )

    assert response_status == 201
    assert body["normalized_text"] == "HC-SR04 Sensor!!!\nPart No. HC-SR04"
    assert body["corrected_text"] == "Fixed Text"
    assert body["detected_language_tags"] == ["en-us"]


@pytest.mark.parametrize(
    ("payload_updates", "expected_code"),
    [
        ({"raw_text": "", "line_count": 1}, "OCR_RESULT_NOT_ACCEPTABLE"),
        (
            {
                "status": "NO_TEXT",
                "raw_text": "",
                "corrected_text": "",
                "block_count": 0,
                "line_count": 0,
                "element_count": 0,
            },
            None,
        ),
        (
            {
                "status": "NO_TEXT",
                "raw_text": "",
                "corrected_text": "unexpected",
                "block_count": 0,
                "line_count": 0,
                "element_count": 0,
            },
            "OCR_RESULT_NOT_ACCEPTABLE",
        ),
        (
            {
                "status": "FAILED",
                "raw_text": "partial safe text",
                "corrected_text": None,
                "block_count": 0,
                "line_count": 0,
                "element_count": 0,
            },
            None,
        ),
        ({"raw_text": "A\x00B"}, "INVALID_OCR_TEXT"),
        ({"raw_text": "x" * 50_001}, "OCR_TEXT_TOO_LARGE"),
        (
            {"detected_language_tags": [f"en-{index}" for index in range(17)]},
            "OCR_RESULT_NOT_ACCEPTABLE",
        ),
        ({"block_count": -1}, "OCR_RESULT_NOT_ACCEPTABLE"),
        ({"line_count": 50_001}, "OCR_RESULT_NOT_ACCEPTABLE"),
        ({"element_count": 250_001}, "OCR_RESULT_NOT_ACCEPTABLE"),
        ({"engine": "TESSERACT"}, "UNSUPPORTED_OCR_ENGINE"),
        ({"status": "DONE"}, "INVALID_OCR_STATUS"),
    ],
)
def test_ocr_validation_rules(
    api_client: TestClient,
    payload_updates: dict[str, Any],
    expected_code: str | None,
) -> None:
    capture, client_photo_id, _ = capture_with_photo(api_client)
    payload = ocr_payload(client_photo_id=client_photo_id) | payload_updates

    response_status, body = post_ocr(
        api_client,
        capture_session_id=capture["id"],
        payload=payload,
        idempotency_key=payload["client_ocr_id"],
    )

    if expected_code is None:
        assert response_status == 201
        return
    assert response_status in {400, 409, 413, 422}
    assert body["error"]["code"] == expected_code


def test_ocr_idempotency_key_validation(api_client: TestClient) -> None:
    capture, client_photo_id, _ = capture_with_photo(api_client)
    payload = ocr_payload(client_photo_id=client_photo_id)

    missing_status, missing_body = post_ocr(
        api_client,
        capture_session_id=capture["id"],
        payload=payload,
    )
    invalid_status, invalid_body = post_ocr(
        api_client,
        capture_session_id=capture["id"],
        payload=payload,
        idempotency_key="not-a-uuid",
    )
    mismatched_status, mismatched_body = post_ocr(
        api_client,
        capture_session_id=capture["id"],
        payload=payload,
        idempotency_key=str(uuid4()),
    )

    assert (missing_status, missing_body["error"]["code"]) == (400, "INVALID_OCR_IDEMPOTENCY_KEY")
    assert (invalid_status, invalid_body["error"]["code"]) == (400, "INVALID_OCR_IDEMPOTENCY_KEY")
    assert (mismatched_status, mismatched_body["error"]["code"]) == (
        400,
        "INVALID_OCR_IDEMPOTENCY_KEY",
    )


def test_ocr_idempotency_replay_and_conflict(api_client: TestClient) -> None:
    capture, client_photo_id, _ = capture_with_photo(api_client)
    client_ocr_id = uuid4()
    payload = ocr_payload(client_ocr_id=client_ocr_id, client_photo_id=client_photo_id)

    first_status, first = post_ocr(
        api_client,
        capture_session_id=capture["id"],
        payload=payload,
        idempotency_key=str(client_ocr_id),
    )
    replay_status, replay = post_ocr(
        api_client,
        capture_session_id=capture["id"],
        payload=payload,
        idempotency_key=str(client_ocr_id),
    )
    conflict_status, conflict = post_ocr(
        api_client,
        capture_session_id=capture["id"],
        payload=payload | {"raw_text": "different text"},
        idempotency_key=str(client_ocr_id),
    )

    assert first_status == 201
    assert replay_status == 200
    assert replay["id"] == first["id"]
    assert conflict_status == 409
    assert conflict["error"]["code"] == "OCR_IDEMPOTENCY_CONFLICT"


def test_missing_capture_photo_and_photo_mismatch(api_client: TestClient) -> None:
    first_capture, first_client_photo_id, _ = capture_with_photo(api_client)
    second_capture, second_client_photo_id, _ = capture_with_photo(api_client)

    missing_capture_payload = ocr_payload(client_photo_id=first_client_photo_id)
    missing_capture_status, missing_capture = post_ocr(
        api_client,
        capture_session_id=str(uuid4()),
        payload=missing_capture_payload,
        idempotency_key=missing_capture_payload["client_ocr_id"],
    )
    missing_photo_payload = ocr_payload(client_photo_id=uuid4())
    missing_photo_status, missing_photo = post_ocr(
        api_client,
        capture_session_id=first_capture["id"],
        payload=missing_photo_payload,
        idempotency_key=missing_photo_payload["client_ocr_id"],
    )
    mismatch_payload = ocr_payload(client_photo_id=second_client_photo_id)
    mismatch_status, mismatch = post_ocr(
        api_client,
        capture_session_id=first_capture["id"],
        payload=mismatch_payload,
        idempotency_key=mismatch_payload["client_ocr_id"],
    )

    assert missing_capture_status == 404
    assert missing_capture["error"]["code"] == "CAPTURE_SESSION_NOT_FOUND"
    assert missing_photo_status == 404
    assert missing_photo["error"]["code"] == "OCR_PHOTO_NOT_FOUND"
    assert second_capture["id"] != first_capture["id"]
    assert mismatch_status == 409
    assert mismatch["error"]["code"] == "OCR_PHOTO_CAPTURE_MISMATCH"


def test_ocr_after_completion_rejected_but_exact_replay_allowed(api_client: TestClient) -> None:
    capture, client_photo_id, _ = capture_with_photo(api_client)
    payload = ocr_payload(client_photo_id=client_photo_id)

    created_status, created = post_ocr(
        api_client,
        capture_session_id=capture["id"],
        payload=payload,
        idempotency_key=payload["client_ocr_id"],
    )
    complete_response = api_client.post(f"/api/v1/capture-sessions/{capture['id']}/complete")
    replay_status, replay = post_ocr(
        api_client,
        capture_session_id=capture["id"],
        payload=payload,
        idempotency_key=payload["client_ocr_id"],
    )
    new_payload = ocr_payload(client_photo_id=client_photo_id)
    new_status, new_body = post_ocr(
        api_client,
        capture_session_id=capture["id"],
        payload=new_payload,
        idempotency_key=new_payload["client_ocr_id"],
    )

    assert created_status == 201
    assert complete_response.status_code == 200
    assert replay_status == 200
    assert replay["id"] == created["id"]
    assert new_status == 409
    assert new_body["error"]["code"] == "OCR_CAPTURE_ALREADY_COMPLETED"


def test_list_ocr_results_empty_and_deterministic_order(api_client: TestClient) -> None:
    capture, client_photo_id, _ = capture_with_photo(api_client)

    empty = api_client.get(f"/api/v1/capture-sessions/{capture['id']}/ocr-results")
    first_payload = ocr_payload(
        client_photo_id=client_photo_id,
        processed_at="2026-07-25T10:00:01Z",
    )
    second_payload = ocr_payload(
        client_photo_id=client_photo_id,
        processed_at="2026-07-25T10:00:02Z",
        raw_text="Second text",
        corrected_text=None,
        line_count=1,
    )
    first_status, first = post_ocr(
        api_client,
        capture_session_id=capture["id"],
        payload=first_payload,
        idempotency_key=first_payload["client_ocr_id"],
    )
    second_status, second = post_ocr(
        api_client,
        capture_session_id=capture["id"],
        payload=second_payload,
        idempotency_key=second_payload["client_ocr_id"],
    )
    listed = api_client.get(f"/api/v1/capture-sessions/{capture['id']}/ocr-results")

    assert empty.status_code == 200
    assert empty.json() == {"items": [], "total": 0}
    assert first_status == 201
    assert second_status == 201
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [first["id"], second["id"]]
    assert listed.json()["total"] == 2


def test_concurrent_duplicate_ocr_submission_creates_one_row(db_settings: Settings) -> None:
    session_factory = get_session_factory(db_settings.effective_database_url)
    with session_factory() as session:
        capture_service = CaptureSessionService(session, LocalStorage(db_settings.upload_root))
        capture_request = CaptureSessionCreateRequest.model_validate(
            {
                "client_capture_id": str(uuid4()),
                "capture_mode": "PHOTO",
                "captured_at": "2026-07-25T09:00:00Z",
                "manual_entry": {"name": "Concurrent OCR", "quantity": "1", "unit": "pcs"},
            }
        )
        capture = capture_service.create_capture_session(
            capture_request,
            idempotency_key=str(capture_request.client_capture_id),
        )
        client_photo_id = uuid4()
        photo = asyncio.run(
            capture_service.upload_photo(
                capture_session_id=capture.response.id,
                client_photo_id=client_photo_id,
                declared_sha256=sha256_hex(JPEG_BYTES),
                upload=BytesUpload(JPEG_BYTES, "image/jpeg"),
                idempotency_key=str(client_photo_id),
            )
        )

    client_ocr_id = uuid4()
    payload = ocr_payload(client_ocr_id=client_ocr_id, client_photo_id=client_photo_id)

    def create_once() -> tuple[int, str]:
        with session_factory() as session:
            service = OcrResultService(session)
            result = service.create_ocr_result(
                capture.response.id,
                OcrResultCreateRequest.model_validate(payload),
                idempotency_key=str(client_ocr_id),
            )
            return result.status_code, str(result.response.id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: create_once(), range(2)))

    with session_factory() as session:
        ocr_count = session.scalar(
            select(func.count()).select_from(CaptureOcrResult).where(
                CaptureOcrResult.client_ocr_id == client_ocr_id
            )
        )

    assert photo.status_code == 201
    assert sorted(status_code for status_code, _ in results) == [200, 201]
    assert len({ocr_id for _, ocr_id in results}) == 1
    assert ocr_count == 1


def test_missing_capture_list_returns_404(api_client: TestClient) -> None:
    response = api_client.get(f"/api/v1/capture-sessions/{uuid4()}/ocr-results")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CAPTURE_SESSION_NOT_FOUND"


def test_ocr_logs_do_not_include_full_text(
    api_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    capture, client_photo_id, _ = capture_with_photo(api_client)
    raw_text = "SECRET-DO-NOT-LOG-HC-SR04"
    payload = ocr_payload(
        client_photo_id=client_photo_id,
        raw_text=raw_text,
        corrected_text=None,
        line_count=1,
    )

    caplog.set_level(logging.INFO)
    response_status, _ = post_ocr(
        api_client,
        capture_session_id=capture["id"],
        payload=payload,
        idempotency_key=payload["client_ocr_id"],
    )

    assert response_status == 201
    assert raw_text not in caplog.text
