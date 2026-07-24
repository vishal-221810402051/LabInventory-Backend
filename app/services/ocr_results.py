from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Generic, TypeVar
from uuid import UUID, uuid4

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApplicationError
from app.core.logging import get_logger
from app.db.models.capture import utc_now
from app.db.models.capture_ocr_result import CaptureOcrResult
from app.domain.capture import CaptureStatus
from app.domain.ocr import (
    MAX_BLOCK_COUNT,
    MAX_ELEMENT_COUNT,
    MAX_LINE_COUNT,
    OcrEngine,
    OcrFingerprintSnapshot,
    OcrStatus,
    normalize_engine_version,
    normalize_language_tags,
    ocr_request_fingerprint,
    parse_ocr_engine,
    parse_ocr_status,
    validate_structural_count,
)
from app.repositories.ocr_results import OcrResultRepository
from app.schemas.ocr_results import (
    OcrResultCreateRequest,
    OcrResultResponse,
    OcrResultsListResponse,
)
from app.services.text_normalization import (
    InvalidOcrTextError,
    OcrTextTooLargeError,
    normalize_ocr_text,
    validate_ocr_text_input,
)

logger = get_logger(__name__)

ResponseT = TypeVar("ResponseT")
_STACK_TRACE_MARKERS = (
    "Traceback (most recent call last)",
    "java.lang.",
    "kotlin.",
    "android.os.",
)


def _bounded_log_value(value: str | None, *, max_chars: int = 100) -> str | None:
    if value is None or len(value) <= max_chars:
        return value
    return f"{value[:max_chars]}..."


@dataclass(frozen=True)
class ServiceResult(Generic[ResponseT]):
    response: ResponseT
    status_code: int


@dataclass(frozen=True)
class PreparedOcrRequest:
    engine: OcrEngine
    engine_version: str | None
    status: OcrStatus
    raw_text: str
    normalized_text: str
    corrected_text: str | None
    detected_language_tags: list[str]
    request_fingerprint: str


class OcrResultService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = OcrResultRepository(session)

    def create_ocr_result(
        self,
        capture_session_id: UUID,
        request: OcrResultCreateRequest,
        *,
        idempotency_key: str | None,
    ) -> ServiceResult[OcrResultResponse]:
        start = time.perf_counter()
        try:
            return self._create_ocr_result(
                capture_session_id,
                request,
                idempotency_key=idempotency_key,
                start=start,
            )
        except ApplicationError as exc:
            self._log_rejected_ocr_result(capture_session_id, request, exc, start)
            raise

    def _create_ocr_result(
        self,
        capture_session_id: UUID,
        request: OcrResultCreateRequest,
        *,
        idempotency_key: str | None,
        start: float,
    ) -> ServiceResult[OcrResultResponse]:
        self._ensure_matching_idempotency_key(idempotency_key, request.client_ocr_id)
        prepared = self._prepare_request(request)

        existing = self._repository.get_by_client_ocr_id(request.client_ocr_id)
        if existing is not None:
            return self._handle_existing_result(existing, capture_session_id, prepared)

        capture_session = self._repository.get_capture_session(capture_session_id)
        if capture_session is None:
            raise self._capture_not_found()

        capture_photo = self._repository.get_photo_by_client_photo_id(request.client_photo_id)
        if capture_photo is None:
            raise ApplicationError(
                code="OCR_PHOTO_NOT_FOUND",
                message="OCR result references a photo that was not uploaded.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        if capture_photo.capture_session_id != capture_session_id:
            raise ApplicationError(
                code="OCR_PHOTO_CAPTURE_MISMATCH",
                message="OCR result photo does not belong to the supplied capture session.",
                status_code=status.HTTP_409_CONFLICT,
            )
        if capture_session.status == CaptureStatus.READY_FOR_PROCESSING:
            raise ApplicationError(
                code="OCR_CAPTURE_ALREADY_COMPLETED",
                message="Completed capture sessions cannot accept new OCR results.",
                status_code=status.HTTP_409_CONFLICT,
            )

        ocr_result = CaptureOcrResult(
            id=uuid4(),
            client_ocr_id=request.client_ocr_id,
            capture_session_id=capture_session_id,
            capture_photo_id=capture_photo.id,
            engine=prepared.engine,
            engine_version=prepared.engine_version,
            status=prepared.status,
            processed_at=request.processed_at,
            raw_text=prepared.raw_text,
            normalized_text=prepared.normalized_text,
            corrected_text=prepared.corrected_text,
            block_count=request.block_count,
            line_count=request.line_count,
            element_count=request.element_count,
            detected_language_tags=prepared.detected_language_tags,
            request_fingerprint=prepared.request_fingerprint,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self._session.add(ocr_result)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            existing = self._repository.get_by_client_ocr_id(request.client_ocr_id)
            if existing is not None:
                return self._handle_existing_result(existing, capture_session_id, prepared)
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 3)
        logger.info(
            "OCR result created",
            extra={
                "event": "ocr.result_created",
                "capture_id": str(capture_session_id),
                "photo_id": str(capture_photo.id),
                "ocr_result_id": str(ocr_result.id),
                "engine": prepared.engine.value,
                "status": prepared.status.value,
                "character_count": len(prepared.normalized_text),
                "line_count": request.line_count,
                "duration_ms": duration_ms,
            },
        )
        return ServiceResult(
            response=self._result_response(ocr_result),
            status_code=status.HTTP_201_CREATED,
        )

    def list_ocr_results(self, capture_session_id: UUID) -> OcrResultsListResponse:
        capture_session = self._repository.get_capture_session(capture_session_id)
        if capture_session is None:
            raise self._capture_not_found()

        results = self._repository.list_by_capture_session_id(capture_session_id)
        logger.info(
            "OCR results listed",
            extra={
                "event": "ocr.results_listed",
                "capture_id": str(capture_session_id),
                "status": capture_session.status.value,
                "result_count": len(results),
            },
        )
        items = [self._result_response(result) for result in results]
        return OcrResultsListResponse(items=items, total=len(items))

    def _log_rejected_ocr_result(
        self,
        capture_session_id: UUID,
        request: OcrResultCreateRequest,
        error: ApplicationError,
        start: float,
    ) -> None:
        duration_ms = round((time.perf_counter() - start) * 1000, 3)
        logger.info(
            "OCR result rejected",
            extra={
                "event": "ocr.result_rejected",
                "capture_id": str(capture_session_id),
                "client_ocr_id": str(request.client_ocr_id),
                "client_photo_id": str(request.client_photo_id),
                "engine": _bounded_log_value(request.engine),
                "status": _bounded_log_value(request.status, max_chars=30),
                "error_code": error.code,
                "response_status": error.status_code,
                "duration_ms": duration_ms,
            },
        )

    def _prepare_request(self, request: OcrResultCreateRequest) -> PreparedOcrRequest:
        engine = self._parse_engine(request.engine)
        ocr_status = self._parse_status(request.status)
        engine_version = self._normalize_engine_version(request.engine_version)
        self._validate_text("raw_text", request.raw_text)
        normalized_text = normalize_ocr_text(request.raw_text)
        corrected_text = self._normalize_corrected_text(request.corrected_text)
        language_tags = self._normalize_language_tags(request.detected_language_tags)
        self._validate_counts(request)
        self._validate_status_specific_rules(
            ocr_status=ocr_status,
            raw_text=request.raw_text,
            normalized_text=normalized_text,
            corrected_text=corrected_text,
            block_count=request.block_count,
            line_count=request.line_count,
            element_count=request.element_count,
        )
        fingerprint = ocr_request_fingerprint(
            OcrFingerprintSnapshot(
                client_ocr_id=request.client_ocr_id,
                client_photo_id=request.client_photo_id,
                engine=engine,
                engine_version=engine_version,
                status=ocr_status,
                processed_at=request.processed_at,
                raw_text=request.raw_text,
                normalized_corrected_text=corrected_text,
                block_count=request.block_count,
                line_count=request.line_count,
                element_count=request.element_count,
                detected_language_tags=language_tags,
            )
        )
        return PreparedOcrRequest(
            engine=engine,
            engine_version=engine_version,
            status=ocr_status,
            raw_text=request.raw_text,
            normalized_text=normalized_text,
            corrected_text=corrected_text,
            detected_language_tags=language_tags,
            request_fingerprint=fingerprint,
        )

    def _handle_existing_result(
        self,
        existing: CaptureOcrResult,
        capture_session_id: UUID,
        prepared: PreparedOcrRequest,
    ) -> ServiceResult[OcrResultResponse]:
        if (
            existing.capture_session_id != capture_session_id
            or existing.request_fingerprint != prepared.request_fingerprint
        ):
            logger.info(
                "OCR idempotency conflict",
                extra={
                    "event": "ocr.idempotency_conflict",
                    "capture_id": str(capture_session_id),
                    "ocr_result_id": str(existing.id),
                    "engine": prepared.engine.value,
                    "status": prepared.status.value,
                },
            )
            raise ApplicationError(
                code="OCR_IDEMPOTENCY_CONFLICT",
                message="OCR result idempotency key conflicts with a different request.",
                status_code=status.HTTP_409_CONFLICT,
            )

        logger.info(
            "OCR idempotent replay",
            extra={
                "event": "ocr.idempotent_replay",
                "capture_id": str(capture_session_id),
                "photo_id": str(existing.capture_photo_id),
                "ocr_result_id": str(existing.id),
                "engine": existing.engine.value,
                "status": existing.status.value,
                "character_count": len(existing.normalized_text),
                "line_count": existing.line_count,
            },
        )
        return ServiceResult(
            response=self._result_response(existing),
            status_code=status.HTTP_200_OK,
        )

    def _parse_engine(self, value: str) -> OcrEngine:
        try:
            return parse_ocr_engine(value)
        except ValueError as exc:
            raise ApplicationError(
                code="UNSUPPORTED_OCR_ENGINE",
                message="Unsupported OCR engine.",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            ) from exc

    def _parse_status(self, value: str) -> OcrStatus:
        try:
            return parse_ocr_status(value)
        except ValueError as exc:
            raise ApplicationError(
                code="INVALID_OCR_STATUS",
                message="Unsupported OCR status.",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            ) from exc

    def _normalize_engine_version(self, value: str | None) -> str | None:
        try:
            return normalize_engine_version(value)
        except ValueError as exc:
            raise ApplicationError(
                code="OCR_RESULT_NOT_ACCEPTABLE",
                message=str(exc),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            ) from exc

    def _normalize_language_tags(self, values: list[str]) -> list[str]:
        try:
            return normalize_language_tags(values)
        except ValueError as exc:
            raise ApplicationError(
                code="OCR_RESULT_NOT_ACCEPTABLE",
                message=str(exc),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            ) from exc

    def _validate_text(self, field_name: str, value: str) -> None:
        try:
            validate_ocr_text_input(value, field_name=field_name)
        except OcrTextTooLargeError as exc:
            raise ApplicationError(
                code="OCR_TEXT_TOO_LARGE",
                message=str(exc),
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            ) from exc
        except InvalidOcrTextError as exc:
            raise ApplicationError(
                code="INVALID_OCR_TEXT",
                message=str(exc),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            ) from exc

    def _normalize_corrected_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        self._validate_text("corrected_text", value)
        normalized = normalize_ocr_text(value)
        return normalized or None

    def _validate_counts(self, request: OcrResultCreateRequest) -> None:
        try:
            validate_structural_count(
                request.block_count,
                field_name="block_count",
                maximum=MAX_BLOCK_COUNT,
            )
            validate_structural_count(
                request.line_count,
                field_name="line_count",
                maximum=MAX_LINE_COUNT,
            )
            validate_structural_count(
                request.element_count,
                field_name="element_count",
                maximum=MAX_ELEMENT_COUNT,
            )
        except ValueError as exc:
            raise ApplicationError(
                code="OCR_RESULT_NOT_ACCEPTABLE",
                message=str(exc),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            ) from exc

    def _validate_status_specific_rules(
        self,
        *,
        ocr_status: OcrStatus,
        raw_text: str,
        normalized_text: str,
        corrected_text: str | None,
        block_count: int,
        line_count: int,
        element_count: int,
    ) -> None:
        if ocr_status == OcrStatus.SUCCEEDED:
            if not normalized_text:
                raise self._not_acceptable("SUCCEEDED OCR results require usable raw text.")
            if line_count < 1:
                raise self._not_acceptable("SUCCEEDED OCR results require at least one line.")
            return

        if ocr_status == OcrStatus.NO_TEXT:
            if normalized_text:
                raise self._not_acceptable("NO_TEXT OCR results must not include raw text.")
            if corrected_text is not None:
                raise self._not_acceptable("NO_TEXT OCR results must not include corrected text.")
            if block_count != 0 or line_count != 0 or element_count != 0:
                raise self._not_acceptable("NO_TEXT OCR results must have zero structural counts.")
            return

        if ocr_status == OcrStatus.FAILED:
            if corrected_text is not None:
                raise self._not_acceptable("FAILED OCR results must not include corrected text.")
            if any(marker in raw_text for marker in _STACK_TRACE_MARKERS):
                raise ApplicationError(
                    code="INVALID_OCR_TEXT",
                    message="FAILED OCR raw text must not contain diagnostic stack traces.",
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )

    def _ensure_matching_idempotency_key(self, idempotency_key: str | None, expected: UUID) -> None:
        if idempotency_key is None:
            raise ApplicationError(
                code="INVALID_OCR_IDEMPOTENCY_KEY",
                message="Idempotency-Key header is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            parsed_key = UUID(idempotency_key)
        except ValueError as exc:
            raise ApplicationError(
                code="INVALID_OCR_IDEMPOTENCY_KEY",
                message="Idempotency-Key header must be a UUID.",
                status_code=status.HTTP_400_BAD_REQUEST,
            ) from exc
        if parsed_key != expected:
            raise ApplicationError(
                code="INVALID_OCR_IDEMPOTENCY_KEY",
                message="Idempotency-Key header must match client_ocr_id.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    def _not_acceptable(self, message: str) -> ApplicationError:
        return ApplicationError(
            code="OCR_RESULT_NOT_ACCEPTABLE",
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    def _capture_not_found(self) -> ApplicationError:
        return ApplicationError(
            code="CAPTURE_SESSION_NOT_FOUND",
            message="Capture session was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    def _result_response(self, ocr_result: CaptureOcrResult) -> OcrResultResponse:
        return OcrResultResponse(
            id=ocr_result.id,
            client_ocr_id=ocr_result.client_ocr_id,
            capture_session_id=ocr_result.capture_session_id,
            capture_photo_id=ocr_result.capture_photo_id,
            engine=ocr_result.engine,
            engine_version=ocr_result.engine_version,
            status=ocr_result.status,
            processed_at=ocr_result.processed_at,
            raw_text=ocr_result.raw_text,
            normalized_text=ocr_result.normalized_text,
            corrected_text=ocr_result.corrected_text,
            block_count=ocr_result.block_count,
            line_count=ocr_result.line_count,
            element_count=ocr_result.element_count,
            detected_language_tags=ocr_result.detected_language_tags,
            created_at=ocr_result.created_at,
            updated_at=ocr_result.updated_at,
        )
