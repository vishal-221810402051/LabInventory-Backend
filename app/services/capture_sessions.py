from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Protocol, TypeVar
from uuid import UUID, uuid4

from fastapi import status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import ApplicationError
from app.core.logging import get_logger
from app.db.models.capture import CapturePhoto, CaptureSession, utc_now
from app.domain.capture import (
    CaptureMode,
    CaptureStatus,
    ManualEntrySnapshot,
    capture_request_fingerprint,
)
from app.repositories.capture_sessions import CaptureSessionRepository
from app.schemas.capture_sessions import (
    CapturePhotoResponse,
    CaptureSessionCreateRequest,
    CaptureSessionResponse,
    ManualEntry,
)
from app.storage.base import ObjectStorage, StorageError

logger = get_logger(__name__)

MAX_PHOTO_BYTES = 15 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
_SHA256_HEX_LENGTH = 64
_SAFE_PHOTO_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
_SUPPORTED_IMAGE_TYPES = set(_SAFE_PHOTO_EXTENSIONS)

ResponseT = TypeVar("ResponseT")


class UploadFileLike(Protocol):
    content_type: str | None

    async def read(self, size: int = -1) -> bytes:
        raise NotImplementedError


@dataclass(frozen=True)
class ServiceResult(Generic[ResponseT]):
    response: ResponseT
    status_code: int


@dataclass(frozen=True)
class StagedPhoto:
    path: Path
    content_type: str
    size_bytes: int
    sha256: str


class CaptureSessionService:
    def __init__(self, session: Session, storage: ObjectStorage) -> None:
        self._session = session
        self._storage = storage
        self._repository = CaptureSessionRepository(session)

    def create_capture_session(
        self,
        request: CaptureSessionCreateRequest,
        *,
        idempotency_key: str | None,
    ) -> ServiceResult:
        self._ensure_matching_idempotency_key(
            idempotency_key,
            request.client_capture_id,
        )
        manual_entry = self._manual_entry_snapshot(request.manual_entry)
        fingerprint = capture_request_fingerprint(
            client_capture_id=request.client_capture_id,
            capture_mode=request.capture_mode,
            captured_at=request.captured_at,
            manual_entry=manual_entry,
        )

        existing = self._repository.get_by_client_capture_id(request.client_capture_id)
        if existing is not None:
            return self._handle_existing_capture(existing, fingerprint)

        capture_session = CaptureSession(
            id=uuid4(),
            client_capture_id=request.client_capture_id,
            capture_mode=request.capture_mode,
            status=CaptureStatus.DRAFT,
            captured_at=request.captured_at,
            name=manual_entry.name if manual_entry else None,
            quantity=manual_entry.quantity if manual_entry else None,
            unit=manual_entry.unit if manual_entry else None,
            category_hint=manual_entry.category_hint if manual_entry else None,
            notes=manual_entry.notes if manual_entry else None,
            request_fingerprint=fingerprint,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self._session.add(capture_session)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            existing = self._repository.get_by_client_capture_id(request.client_capture_id)
            if existing is not None:
                return self._handle_existing_capture(existing, fingerprint)
            raise

        logger.info(
            "Capture session created",
            extra={
                "event": "capture.created",
                "capture_id": str(capture_session.id),
                "client_capture_id": str(capture_session.client_capture_id),
                "status": capture_session.status.value,
            },
        )
        return ServiceResult(
            response=self._session_response(capture_session),
            status_code=status.HTTP_201_CREATED,
        )

    def get_capture_session(self, capture_session_id: UUID) -> CaptureSessionResponse:
        capture_session = self._repository.get_by_id(capture_session_id)
        if capture_session is None:
            raise self._not_found()
        return self._session_response(capture_session)

    async def upload_photo(
        self,
        *,
        capture_session_id: UUID,
        client_photo_id: UUID,
        declared_sha256: str,
        upload: UploadFileLike,
        idempotency_key: str | None,
    ) -> ServiceResult:
        start = time.perf_counter()
        self._ensure_matching_idempotency_key(idempotency_key, client_photo_id)
        expected_sha256 = self._validate_sha256(declared_sha256)

        capture_session = self._repository.get_by_id(capture_session_id)
        if capture_session is None:
            raise self._not_found()
        if capture_session.status == CaptureStatus.READY_FOR_PROCESSING:
            raise ApplicationError(
                code="CAPTURE_ALREADY_COMPLETED",
                message="Completed capture sessions cannot accept new photos.",
                status_code=status.HTTP_409_CONFLICT,
            )

        staged_photo: StagedPhoto | None = None
        final_key: str | None = None
        try:
            staged_photo = await self._stage_upload(upload)
            if not hmac.compare_digest(staged_photo.sha256, expected_sha256):
                raise ApplicationError(
                    code="PHOTO_HASH_MISMATCH",
                    message="Declared SHA-256 does not match the uploaded file.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            existing = self._repository.get_photo_by_client_photo_id(client_photo_id)
            if existing is not None:
                self._storage.discard_path(staged_photo.path)
                staged_photo = None
                return self._handle_existing_photo(existing, capture_session_id, expected_sha256)

            photo_id = uuid4()
            content_type = staged_photo.content_type
            size_bytes = staged_photo.size_bytes
            final_key = (
                f"captures/{capture_session_id}/{photo_id}."
                f"{_SAFE_PHOTO_EXTENSIONS[content_type]}"
            )
            self._storage.commit_staged_file(staged_photo.path, final_key)
            staged_photo = None
            capture_photo = CapturePhoto(
                id=photo_id,
                client_photo_id=client_photo_id,
                capture_session_id=capture_session_id,
                storage_key=final_key,
                content_type=content_type,
                size_bytes=size_bytes,
                sha256=expected_sha256,
                created_at=utc_now(),
            )
            self._session.add(capture_photo)
            try:
                self._session.commit()
            except IntegrityError:
                self._session.rollback()
                self._storage.delete(final_key)
                existing = self._repository.get_photo_by_client_photo_id(client_photo_id)
                if existing is not None:
                    return self._handle_existing_photo(
                        existing,
                        capture_session_id,
                        expected_sha256,
                    )
                raise
            except SQLAlchemyError as exc:
                self._session.rollback()
                self._storage.delete(final_key)
                raise self._storage_failed(exc) from exc

            duration_ms = round((time.perf_counter() - start) * 1000, 3)
            logger.info(
                "Capture photo uploaded",
                extra={
                    "event": "capture.photo_uploaded",
                    "capture_id": str(capture_session_id),
                    "photo_id": str(capture_photo.id),
                    "client_photo_id": str(client_photo_id),
                    "size": capture_photo.size_bytes,
                    "duration_ms": duration_ms,
                },
            )
            return ServiceResult(
                response=self._photo_response(capture_photo),
                status_code=status.HTTP_201_CREATED,
            )
        except ApplicationError:
            if staged_photo is not None:
                self._storage.discard_path(staged_photo.path)
            logger.info(
                "Capture photo rejected",
                extra={
                    "event": "capture.photo_rejected",
                    "capture_id": str(capture_session_id),
                    "client_photo_id": str(client_photo_id),
                },
            )
            raise
        except (OSError, StorageError) as exc:
            if staged_photo is not None:
                self._storage.discard_path(staged_photo.path)
            if final_key is not None:
                self._storage.delete(final_key)
            self._session.rollback()
            raise self._storage_failed(exc) from exc

    def complete_capture_session(self, capture_session_id: UUID) -> CaptureSessionResponse:
        try:
            with self._session.begin():
                capture_session = self._repository.get_by_id(capture_session_id, for_update=True)
                if capture_session is None:
                    raise self._not_found()
                photo_count = self._repository.count_photos(capture_session_id)
                if capture_session.status == CaptureStatus.READY_FOR_PROCESSING:
                    return self._session_response(capture_session, photo_count=photo_count)

                failures = self._completion_failures(capture_session, photo_count)
                if failures:
                    logger.info(
                        "Capture completion rejected",
                        extra={
                            "event": "capture.completion_rejected",
                            "capture_id": str(capture_session.id),
                            "client_capture_id": str(capture_session.client_capture_id),
                            "status": capture_session.status.value,
                        },
                    )
                    raise ApplicationError(
                        code="CAPTURE_NOT_COMPLETABLE",
                        message="Capture session does not meet completion requirements.",
                        status_code=status.HTTP_409_CONFLICT,
                        details={"failures": failures},
                    )

                capture_session.status = CaptureStatus.READY_FOR_PROCESSING
                capture_session.updated_at = utc_now()
                response = self._session_response(capture_session, photo_count=photo_count)
        except ApplicationError:
            raise

        logger.info(
            "Capture session completed",
            extra={
                "event": "capture.completed",
                "capture_id": str(capture_session_id),
                "status": CaptureStatus.READY_FOR_PROCESSING.value,
            },
        )
        return response

    def _handle_existing_capture(
        self,
        existing: CaptureSession,
        fingerprint: str,
    ) -> ServiceResult:
        if existing.request_fingerprint != fingerprint:
            logger.info(
                "Capture idempotency conflict",
                extra={
                    "event": "capture.idempotency_conflict",
                    "capture_id": str(existing.id),
                    "client_capture_id": str(existing.client_capture_id),
                    "status": existing.status.value,
                },
            )
            raise ApplicationError(
                code="CAPTURE_IDEMPOTENCY_CONFLICT",
                message="Capture session idempotency key conflicts with a different request.",
                status_code=status.HTTP_409_CONFLICT,
            )

        logger.info(
            "Capture idempotent replay",
            extra={
                "event": "capture.idempotent_replay",
                "capture_id": str(existing.id),
                "client_capture_id": str(existing.client_capture_id),
                "status": existing.status.value,
            },
        )
        return ServiceResult(
            response=self._session_response(existing),
            status_code=status.HTTP_200_OK,
        )

    def _handle_existing_photo(
        self,
        existing: CapturePhoto,
        capture_session_id: UUID,
        sha256: str,
    ) -> ServiceResult:
        if existing.capture_session_id != capture_session_id or existing.sha256 != sha256:
            logger.info(
                "Capture photo idempotency conflict",
                extra={
                    "event": "capture.photo_rejected",
                    "capture_id": str(capture_session_id),
                    "photo_id": str(existing.id),
                },
            )
            raise ApplicationError(
                code="PHOTO_IDEMPOTENCY_CONFLICT",
                message="Photo idempotency key conflicts with a different upload.",
                status_code=status.HTTP_409_CONFLICT,
            )

        logger.info(
            "Capture photo idempotent replay",
            extra={
                "event": "capture.photo_replayed",
                "capture_id": str(capture_session_id),
                "photo_id": str(existing.id),
                "client_photo_id": str(existing.client_photo_id),
            },
        )
        return ServiceResult(
            response=self._photo_response(existing),
            status_code=status.HTTP_200_OK,
        )

    async def _stage_upload(self, upload: UploadFileLike) -> StagedPhoto:
        declared_content_type = upload.content_type or ""
        if declared_content_type not in _SUPPORTED_IMAGE_TYPES:
            raise ApplicationError(
                code="UNSUPPORTED_PHOTO_TYPE",
                message="Only JPEG, PNG, and WebP photos are supported.",
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )

        staged_path = self._storage.create_staging_path(".upload")
        digest = hashlib.sha256()
        size_bytes = 0
        signature = bytearray()
        try:
            with staged_path.open("xb") as handle:
                while True:
                    chunk = await upload.read(UPLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    if size_bytes + len(chunk) > MAX_PHOTO_BYTES:
                        raise ApplicationError(
                            code="PHOTO_TOO_LARGE",
                            message="Uploaded photos must not exceed 15 MiB.",
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        )
                    size_bytes += len(chunk)
                    if len(signature) < 16:
                        signature.extend(chunk[: 16 - len(signature)])
                    digest.update(chunk)
                    handle.write(chunk)

            if size_bytes == 0:
                raise ApplicationError(
                    code="VALIDATION_ERROR",
                    message="Uploaded photo must not be empty.",
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )

            detected_content_type = _detect_image_content_type(bytes(signature))
            if detected_content_type != declared_content_type:
                raise ApplicationError(
                    code="UNSUPPORTED_PHOTO_TYPE",
                    message="Uploaded file content does not match the declared image type.",
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                )
        except Exception:
            self._storage.discard_path(staged_path)
            raise

        return StagedPhoto(
            path=staged_path,
            content_type=declared_content_type,
            size_bytes=size_bytes,
            sha256=digest.hexdigest(),
        )

    def _completion_failures(self, capture_session: CaptureSession, photo_count: int) -> list[str]:
        failures: list[str] = []
        if capture_session.capture_mode in {CaptureMode.PHOTO, CaptureMode.PHOTO_WITH_MANUAL}:
            if photo_count < 1:
                failures.append("At least one valid photo is required.")
        if capture_session.capture_mode in {CaptureMode.MANUAL, CaptureMode.PHOTO_WITH_MANUAL}:
            if capture_session.name is None:
                failures.append("Manual entry name is required.")
        if capture_session.quantity is None:
            failures.append("Quantity is required.")
        if capture_session.unit is None:
            failures.append("Unit is required.")
        return failures

    def _session_response(
        self,
        capture_session: CaptureSession,
        *,
        photo_count: int | None = None,
    ) -> CaptureSessionResponse:
        resolved_photo_count = (
            photo_count
            if photo_count is not None
            else self._repository.count_photos(capture_session.id)
        )
        manual_entry = None
        if any(
            value is not None
            for value in (
                capture_session.name,
                capture_session.quantity,
                capture_session.unit,
                capture_session.category_hint,
                capture_session.notes,
            )
        ):
            manual_entry = ManualEntry(
                name=capture_session.name,
                quantity=capture_session.quantity,
                unit=capture_session.unit,
                category_hint=capture_session.category_hint,
                notes=capture_session.notes,
            )
        return CaptureSessionResponse(
            id=capture_session.id,
            client_capture_id=capture_session.client_capture_id,
            capture_mode=capture_session.capture_mode,
            status=capture_session.status,
            captured_at=capture_session.captured_at,
            manual_entry=manual_entry,
            photo_count=resolved_photo_count,
            created_at=capture_session.created_at,
            updated_at=capture_session.updated_at,
        )

    def _photo_response(self, capture_photo: CapturePhoto) -> CapturePhotoResponse:
        return CapturePhotoResponse(
            id=capture_photo.id,
            client_photo_id=capture_photo.client_photo_id,
            capture_session_id=capture_photo.capture_session_id,
            content_type=capture_photo.content_type,
            size_bytes=capture_photo.size_bytes,
            sha256=capture_photo.sha256,
            created_at=capture_photo.created_at,
        )

    def _manual_entry_snapshot(
        self,
        manual_entry: ManualEntry | None,
    ) -> ManualEntrySnapshot | None:
        if manual_entry is None:
            return None
        return ManualEntrySnapshot(
            name=manual_entry.name,
            quantity=manual_entry.quantity,
            unit=manual_entry.unit,
            category_hint=manual_entry.category_hint,
            notes=manual_entry.notes,
        )

    def _ensure_matching_idempotency_key(self, idempotency_key: str | None, expected: UUID) -> None:
        if idempotency_key is None:
            raise ApplicationError(
                code="INVALID_IDEMPOTENCY_KEY",
                message="Idempotency-Key header is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            parsed_key = UUID(idempotency_key)
        except ValueError as exc:
            raise ApplicationError(
                code="INVALID_IDEMPOTENCY_KEY",
                message="Idempotency-Key header must be a UUID.",
                status_code=status.HTTP_400_BAD_REQUEST,
            ) from exc
        if parsed_key != expected:
            raise ApplicationError(
                code="INVALID_IDEMPOTENCY_KEY",
                message="Idempotency-Key header must match the client identifier.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    def _validate_sha256(self, value: str) -> str:
        normalized = value.strip()
        if len(normalized) != _SHA256_HEX_LENGTH or any(
            char not in "0123456789abcdef" for char in normalized
        ):
            raise ApplicationError(
                code="INVALID_PHOTO_HASH",
                message="sha256 must be a lowercase 64-character hexadecimal string.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return normalized

    def _not_found(self) -> ApplicationError:
        return ApplicationError(
            code="CAPTURE_SESSION_NOT_FOUND",
            message="Capture session was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    def _storage_failed(self, exc: Exception) -> ApplicationError:
        logger.warning(
            "Photo storage failed",
            exc_info=exc,
            extra={"event": "capture.photo_storage_failed"},
        )
        return ApplicationError(
            code="PHOTO_STORAGE_FAILED",
            message="Photo upload could not be persisted.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def _detect_image_content_type(prefix: bytes) -> str | None:
    if prefix.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP":
        return "image/webp"
    return None
