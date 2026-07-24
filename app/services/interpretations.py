from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Generic, TypeVar
from uuid import UUID, uuid4

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.core.logging import get_logger
from app.db.models.capture import CaptureSession, utc_now
from app.db.models.capture_interpretation import CaptureInterpretation
from app.db.models.capture_ocr_result import CaptureOcrResult
from app.domain.capture import CaptureMode, CaptureStatus, decimal_to_fingerprint
from app.domain.interpretation import (
    AI_IMAGE_INPUT_ENABLED,
    MAX_AI_SOURCE_TEXT_CHARS,
    SUPPORTED_AI_LOCALES,
    AiInterpretationSource,
    AiManualSource,
    AiOcrTextSource,
    AiProvider,
    InterpretationResult,
    InterpretationStatus,
    InterpretationSuggestion,
    ai_request_fingerprint,
    ai_source_fingerprint,
    normalize_ai_source_text,
)
from app.domain.ocr import OcrStatus
from app.providers.item_interpretation import (
    InvalidProviderResponseError,
    ItemInterpretationProvider,
    ProviderRefusedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.repositories.interpretations import InterpretationRepository
from app.schemas.interpretations import (
    AiStatusResponse,
    InterpretationCreateRequest,
    InterpretationListResponse,
    InterpretationResponse,
)

logger = get_logger(__name__)

ResponseT = TypeVar("ResponseT")


@dataclass(frozen=True)
class ServiceResult(Generic[ResponseT]):
    response: ResponseT
    status_code: int


@dataclass(frozen=True)
class PreparedInterpretationRequest:
    source: AiInterpretationSource
    source_fingerprint: str
    request_fingerprint: str


class InterpretationService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        provider: ItemInterpretationProvider,
    ) -> None:
        self._session = session
        self._settings = settings
        self._provider = provider
        self._repository = InterpretationRepository(session)

    def ai_status(self) -> AiStatusResponse:
        return AiStatusResponse(
            enabled=self._settings.ai_interpretation_enabled,
            configured=self._settings.openai_configured,
            provider=AiProvider.OPENAI.value,
            model=self._settings.openai_model,
            prompt_version=self._settings.ai_prompt_version,
            schema_version=self._settings.ai_schema_version,
            image_input_enabled=AI_IMAGE_INPUT_ENABLED,
        )

    def create_interpretation(
        self,
        capture_session_id: UUID,
        request: InterpretationCreateRequest,
        *,
        idempotency_key: str | None,
    ) -> ServiceResult[InterpretationResponse]:
        start = time.perf_counter()
        try:
            return self._create_interpretation(
                capture_session_id,
                request,
                idempotency_key=idempotency_key,
                start=start,
            )
        except ApplicationError as exc:
            self._log_failed_without_row(capture_session_id, request, exc, start)
            raise

    def _create_interpretation(
        self,
        capture_session_id: UUID,
        request: InterpretationCreateRequest,
        *,
        idempotency_key: str | None,
        start: float,
    ) -> ServiceResult[InterpretationResponse]:
        self._ensure_matching_idempotency_key(
            idempotency_key,
            request.client_interpretation_id,
        )
        self._ensure_locale_supported(request.requested_locale)
        self._ensure_enabled_and_configured()

        capture_session = self._repository.get_capture_session(capture_session_id)
        if capture_session is None:
            raise self._capture_not_found()

        prepared = self._prepare_request(capture_session, request)
        existing = self._repository.get_by_client_interpretation_id(
            request.client_interpretation_id
        )
        if existing is not None:
            return self._handle_existing_interpretation(
                existing,
                capture_session_id,
                prepared.request_fingerprint,
            )

        interpretation = CaptureInterpretation(
            id=uuid4(),
            client_interpretation_id=request.client_interpretation_id,
            capture_session_id=capture_session_id,
            status=InterpretationStatus.PROCESSING,
            provider=AiProvider.OPENAI,
            model=self._settings.openai_model,
            prompt_version=self._settings.ai_prompt_version,
            schema_version=self._settings.ai_schema_version,
            requested_locale=request.requested_locale,
            requested_at=request.requested_at,
            source_fingerprint=prepared.source_fingerprint,
            request_fingerprint=prepared.request_fingerprint,
            suggestion_json=None,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self._session.add(interpretation)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            existing = self._repository.get_by_client_interpretation_id(
                request.client_interpretation_id
            )
            if existing is not None:
                return self._handle_existing_interpretation(
                    existing,
                    capture_session_id,
                    prepared.request_fingerprint,
                )
            raise

        logger.info(
            "AI interpretation started",
            extra={
                "event": "ai.interpretation_started",
                "capture_id": str(capture_session_id),
                "interpretation_id": str(interpretation.id),
                "status": interpretation.status.value,
                "model": interpretation.model,
                "prompt_version": interpretation.prompt_version,
                "character_count": prepared.source.source_character_count,
            },
        )

        try:
            provider_result = self._provider.interpret(prepared.source)
            terminal_status = (
                InterpretationStatus.INSUFFICIENT_INFORMATION
                if provider_result.suggestion.result
                == InterpretationResult.INSUFFICIENT_INFORMATION
                else InterpretationStatus.SUCCEEDED
            )
            interpretation.status = terminal_status
            interpretation.suggestion_json = provider_result.suggestion.model_dump(mode="json")
            interpretation.input_token_count = provider_result.input_token_count
            interpretation.output_token_count = provider_result.output_token_count
            interpretation.total_token_count = provider_result.total_token_count
            interpretation.latency_ms = provider_result.latency_ms
            interpretation.provider_response_id = provider_result.provider_response_id
            interpretation.safe_error_code = None
            interpretation.updated_at = utc_now()
            self._session.commit()
        except ProviderTimeoutError as exc:
            raise self._persist_provider_failure(
                interpretation,
                status=InterpretationStatus.FAILED,
                error_code="AI_PROVIDER_TIMEOUT",
                message="AI provider request timed out.",
                http_status=status.HTTP_504_GATEWAY_TIMEOUT,
                start=start,
            ) from exc
        except ProviderRefusedError as exc:
            raise self._persist_provider_failure(
                interpretation,
                status=InterpretationStatus.REFUSED,
                error_code="AI_PROVIDER_REFUSED",
                message="AI provider refused the interpretation request.",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                start=start,
            ) from exc
        except InvalidProviderResponseError as exc:
            raise self._persist_provider_failure(
                interpretation,
                status=InterpretationStatus.FAILED,
                error_code="AI_RESPONSE_INVALID",
                message="AI provider returned invalid structured output.",
                http_status=status.HTTP_502_BAD_GATEWAY,
                start=start,
            ) from exc
        except ProviderUnavailableError as exc:
            raise self._persist_provider_failure(
                interpretation,
                status=InterpretationStatus.FAILED,
                error_code="AI_PROVIDER_UNAVAILABLE",
                message="AI provider is unavailable.",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                start=start,
            ) from exc

        self._log_terminal_interpretation(interpretation, prepared.source.source_character_count)
        return ServiceResult(
            response=self._interpretation_response(interpretation),
            status_code=status.HTTP_201_CREATED,
        )

    def list_interpretations(self, capture_session_id: UUID) -> InterpretationListResponse:
        capture_session = self._repository.get_capture_session(capture_session_id)
        if capture_session is None:
            raise self._capture_not_found()
        interpretations = self._repository.list_by_capture_session_id(capture_session_id)
        logger.info(
            "AI interpretations listed",
            extra={
                "event": "ai.interpretations_listed",
                "capture_id": str(capture_session_id),
                "status": capture_session.status.value,
                "result_count": len(interpretations),
            },
        )
        items = [self._interpretation_response(item) for item in interpretations]
        return InterpretationListResponse(items=items, total=len(items))

    def get_interpretation(
        self,
        capture_session_id: UUID,
        interpretation_id: UUID,
    ) -> InterpretationResponse:
        capture_session = self._repository.get_capture_session(capture_session_id)
        if capture_session is None:
            raise self._capture_not_found()
        interpretation = self._repository.get_by_id(capture_session_id, interpretation_id)
        if interpretation is None:
            raise ApplicationError(
                code="AI_INTERPRETATION_NOT_FOUND",
                message="AI interpretation was not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return self._interpretation_response(interpretation)

    def _prepare_request(
        self,
        capture_session: CaptureSession,
        request: InterpretationCreateRequest,
    ) -> PreparedInterpretationRequest:
        source = self._build_source(capture_session, request.requested_locale)
        source_fingerprint = ai_source_fingerprint(
            source=source,
            prompt_version=self._settings.ai_prompt_version,
            schema_version=self._settings.ai_schema_version,
        )
        request_fingerprint = ai_request_fingerprint(
            client_interpretation_id=request.client_interpretation_id,
            requested_at=request.requested_at,
            requested_locale=request.requested_locale,
            source_fingerprint=source_fingerprint,
            provider=AiProvider.OPENAI,
            model=self._settings.openai_model,
            prompt_version=self._settings.ai_prompt_version,
            schema_version=self._settings.ai_schema_version,
        )
        return PreparedInterpretationRequest(
            source=source,
            source_fingerprint=source_fingerprint,
            request_fingerprint=request_fingerprint,
        )

    def _build_source(
        self,
        capture_session: CaptureSession,
        requested_locale: str,
    ) -> AiInterpretationSource:
        if capture_session.status != CaptureStatus.READY_FOR_PROCESSING:
            raise ApplicationError(
                code="AI_INTERPRETATION_NOT_ALLOWED",
                message="AI interpretation requires a completed capture session.",
                status_code=status.HTTP_409_CONFLICT,
            )

        photo_count = self._repository.count_photos(capture_session.id)
        ocr_results = self._repository.list_ocr_results(capture_session.id)
        manual = AiManualSource(
            name=normalize_ai_source_text(capture_session.name),
            quantity=capture_session.quantity,
            unit=normalize_ai_source_text(capture_session.unit),
            category_hint=normalize_ai_source_text(capture_session.category_hint),
            notes=normalize_ai_source_text(capture_session.notes),
        )

        self._validate_capture_source_eligibility(capture_session, photo_count, ocr_results, manual)
        ocr_sources = self._ocr_sources(ocr_results)
        source_character_count = self._source_character_count(manual, ocr_sources)
        if source_character_count > MAX_AI_SOURCE_TEXT_CHARS:
            raise ApplicationError(
                code="AI_SOURCE_TOO_LARGE",
                message="AI interpretation source text exceeds the Phase 3 limit.",
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        if self._source_has_no_evidence(manual, ocr_sources):
            raise ApplicationError(
                code="AI_SOURCE_INSUFFICIENT",
                message="Capture does not contain enough text for AI interpretation.",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        return AiInterpretationSource(
            capture_mode=capture_session.capture_mode,
            manual=manual,
            ocr=ocr_sources,
            requested_locale=requested_locale,
            source_character_count=source_character_count,
        )

    def _validate_capture_source_eligibility(
        self,
        capture_session: CaptureSession,
        photo_count: int,
        ocr_results: list[CaptureOcrResult],
        manual: AiManualSource,
    ) -> None:
        mode = capture_session.capture_mode
        if mode in {CaptureMode.MANUAL, CaptureMode.PHOTO_WITH_MANUAL}:
            if manual.name is None or manual.quantity is None or manual.unit is None:
                raise ApplicationError(
                    code="AI_SOURCE_INSUFFICIENT",
                    message="Completed manual captures require name, quantity, and unit.",
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
        if mode in {CaptureMode.PHOTO, CaptureMode.PHOTO_WITH_MANUAL}:
            if photo_count < 1:
                raise ApplicationError(
                    code="AI_SOURCE_INSUFFICIENT",
                    message="Photo captures require at least one uploaded photo.",
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            acceptable_ocr_statuses = {OcrStatus.SUCCEEDED, OcrStatus.NO_TEXT}
            if not any(result.status in acceptable_ocr_statuses for result in ocr_results):
                raise ApplicationError(
                    code="AI_SOURCE_INSUFFICIENT",
                    message="Photo captures require at least one completed OCR result.",
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )

    def _ocr_sources(self, ocr_results: list[CaptureOcrResult]) -> list[AiOcrTextSource]:
        sources: list[AiOcrTextSource] = []
        for result in ocr_results:
            if result.status == OcrStatus.SUCCEEDED:
                has_correction = result.corrected_text is not None
                text_source = "corrected_text" if has_correction else "normalized_text"
                text = result.corrected_text if has_correction else result.normalized_text
                sources.append(
                    AiOcrTextSource(
                        status=result.status.value,
                        text_source=text_source,
                        text=normalize_ai_source_text(text),
                    )
                )
            elif result.status == OcrStatus.NO_TEXT:
                sources.append(
                    AiOcrTextSource(
                        status=result.status.value,
                        text_source="no_text",
                        text=None,
                    )
                )
        return sources

    def _source_character_count(
        self,
        manual: AiManualSource,
        ocr_sources: list[AiOcrTextSource],
    ) -> int:
        manual_text = [
            manual.name,
            decimal_to_fingerprint(manual.quantity),
            manual.unit,
            manual.category_hint,
            manual.notes,
        ]
        ocr_text = [source.text for source in ocr_sources]
        return sum(len(value) for value in [*manual_text, *ocr_text] if value is not None)

    def _source_has_no_evidence(
        self,
        manual: AiManualSource,
        ocr_sources: list[AiOcrTextSource],
    ) -> bool:
        return not any(
            (
                manual.name,
                manual.unit,
                manual.category_hint,
                manual.notes,
                *(source.text for source in ocr_sources),
            )
        )

    def _handle_existing_interpretation(
        self,
        existing: CaptureInterpretation,
        capture_session_id: UUID,
        request_fingerprint: str,
    ) -> ServiceResult[InterpretationResponse]:
        if (
            existing.capture_session_id != capture_session_id
            or existing.request_fingerprint != request_fingerprint
        ):
            logger.info(
                "AI interpretation conflict",
                extra={
                    "event": "ai.interpretation_conflict",
                    "capture_id": str(capture_session_id),
                    "interpretation_id": str(existing.id),
                    "status": existing.status.value,
                    "model": existing.model,
                    "prompt_version": existing.prompt_version,
                    "safe_error_code": "AI_INTERPRETATION_IDEMPOTENCY_CONFLICT",
                },
            )
            raise ApplicationError(
                code="AI_INTERPRETATION_IDEMPOTENCY_CONFLICT",
                message="AI interpretation idempotency key conflicts with a different request.",
                status_code=status.HTTP_409_CONFLICT,
            )

        replay_status = (
            status.HTTP_202_ACCEPTED
            if existing.status == InterpretationStatus.PROCESSING
            else status.HTTP_200_OK
        )
        event_name = (
            "ai.interpretation_in_progress"
            if existing.status == InterpretationStatus.PROCESSING
            else "ai.interpretation_replayed"
        )
        logger.info(
            "AI interpretation replay",
            extra={
                "event": event_name,
                "capture_id": str(capture_session_id),
                "interpretation_id": str(existing.id),
                "status": existing.status.value,
                "model": existing.model,
                "prompt_version": existing.prompt_version,
                "input_token_count": existing.input_token_count,
                "output_token_count": existing.output_token_count,
                "total_token_count": existing.total_token_count,
                "latency_ms": existing.latency_ms,
                "safe_error_code": existing.safe_error_code,
            },
        )
        return ServiceResult(
            response=self._interpretation_response(existing),
            status_code=replay_status,
        )

    def _persist_provider_failure(
        self,
        interpretation: CaptureInterpretation,
        *,
        status: InterpretationStatus,
        error_code: str,
        message: str,
        http_status: int,
        start: float,
    ) -> ApplicationError:
        interpretation.status = status
        interpretation.safe_error_code = error_code
        interpretation.latency_ms = round((time.perf_counter() - start) * 1000)
        interpretation.updated_at = utc_now()
        self._session.commit()
        logger.info(
            "AI interpretation failed",
            extra={
                "event": "ai.interpretation_failed",
                "capture_id": str(interpretation.capture_session_id),
                "interpretation_id": str(interpretation.id),
                "status": interpretation.status.value,
                "model": interpretation.model,
                "prompt_version": interpretation.prompt_version,
                "latency_ms": interpretation.latency_ms,
                "safe_error_code": error_code,
            },
        )
        return ApplicationError(code=error_code, message=message, status_code=http_status)

    def _log_terminal_interpretation(
        self,
        interpretation: CaptureInterpretation,
        character_count: int,
    ) -> None:
        event_name = (
            "ai.interpretation_insufficient"
            if interpretation.status == InterpretationStatus.INSUFFICIENT_INFORMATION
            else "ai.interpretation_succeeded"
        )
        logger.info(
            "AI interpretation completed",
            extra={
                "event": event_name,
                "capture_id": str(interpretation.capture_session_id),
                "interpretation_id": str(interpretation.id),
                "status": interpretation.status.value,
                "model": interpretation.model,
                "prompt_version": interpretation.prompt_version,
                "character_count": character_count,
                "input_token_count": interpretation.input_token_count,
                "output_token_count": interpretation.output_token_count,
                "total_token_count": interpretation.total_token_count,
                "latency_ms": interpretation.latency_ms,
            },
        )

    def _log_failed_without_row(
        self,
        capture_session_id: UUID,
        request: InterpretationCreateRequest,
        error: ApplicationError,
        start: float,
    ) -> None:
        if error.code.startswith("AI_PROVIDER_") or error.code == "AI_RESPONSE_INVALID":
            return
        logger.info(
            "AI interpretation failed",
            extra={
                "event": "ai.interpretation_failed",
                "capture_id": str(capture_session_id),
                "client_interpretation_id": str(request.client_interpretation_id),
                "status": None,
                "model": self._settings.openai_model,
                "prompt_version": self._settings.ai_prompt_version,
                "latency_ms": round((time.perf_counter() - start) * 1000),
                "safe_error_code": error.code,
            },
        )

    def _interpretation_response(
        self,
        interpretation: CaptureInterpretation,
    ) -> InterpretationResponse:
        suggestion = (
            None
            if interpretation.suggestion_json is None
            else InterpretationSuggestion.model_validate(interpretation.suggestion_json)
        )
        return InterpretationResponse(
            id=interpretation.id,
            client_interpretation_id=interpretation.client_interpretation_id,
            capture_session_id=interpretation.capture_session_id,
            status=interpretation.status,
            provider=AiProvider(interpretation.provider),
            model=interpretation.model,
            prompt_version=interpretation.prompt_version,
            schema_version=interpretation.schema_version,
            suggestion=suggestion,
            input_token_count=interpretation.input_token_count,
            output_token_count=interpretation.output_token_count,
            total_token_count=interpretation.total_token_count,
            latency_ms=interpretation.latency_ms,
            created_at=interpretation.created_at,
            updated_at=interpretation.updated_at,
        )

    def _ensure_enabled_and_configured(self) -> None:
        if not self._settings.ai_interpretation_enabled:
            raise ApplicationError(
                code="AI_INTERPRETATION_DISABLED",
                message="AI interpretation is disabled.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if not self._settings.openai_configured:
            raise ApplicationError(
                code="AI_PROVIDER_NOT_CONFIGURED",
                message="AI interpretation provider is not configured.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    def _ensure_locale_supported(self, requested_locale: str) -> None:
        if requested_locale not in SUPPORTED_AI_LOCALES:
            raise ApplicationError(
                code="UNSUPPORTED_AI_LOCALE",
                message="Requested AI interpretation locale is not supported.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    def _ensure_matching_idempotency_key(self, idempotency_key: str | None, expected: UUID) -> None:
        if idempotency_key is None:
            raise ApplicationError(
                code="INVALID_AI_IDEMPOTENCY_KEY",
                message="Idempotency-Key header is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            parsed_key = UUID(idempotency_key)
        except ValueError as exc:
            raise ApplicationError(
                code="INVALID_AI_IDEMPOTENCY_KEY",
                message="Idempotency-Key header must be a UUID.",
                status_code=status.HTTP_400_BAD_REQUEST,
            ) from exc
        if parsed_key != expected:
            raise ApplicationError(
                code="INVALID_AI_IDEMPOTENCY_KEY",
                message="Idempotency-Key header must match client_interpretation_id.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    def _capture_not_found(self) -> ApplicationError:
        return ApplicationError(
            code="CAPTURE_SESSION_NOT_FOUND",
            message="Capture session was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
