from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from fastapi.responses import JSONResponse

from app.api.dependencies import get_ocr_result_service
from app.schemas.errors import ErrorEnvelope
from app.schemas.ocr_results import (
    OcrResultCreateRequest,
    OcrResultResponse,
    OcrResultsListResponse,
)
from app.services.ocr_results import OcrResultService

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    409: {"model": ErrorEnvelope},
    413: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
    500: {"model": ErrorEnvelope},
}

router = APIRouter(
    prefix="/api/v1/capture-sessions/{capture_session_id}/ocr-results",
    tags=["ocr-results"],
)


@router.post(
    "",
    response_model=OcrResultResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_200_OK: {"model": OcrResultResponse}, **ERROR_RESPONSES},
)
def create_ocr_result(
    capture_session_id: UUID,
    request: OcrResultCreateRequest,
    service: Annotated[OcrResultService, Depends(get_ocr_result_service)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="UUID idempotency key. Must equal client_ocr_id.",
        ),
    ] = None,
) -> JSONResponse:
    result = service.create_ocr_result(
        capture_session_id,
        request,
        idempotency_key=idempotency_key,
    )
    return JSONResponse(
        status_code=result.status_code,
        content=result.response.model_dump(mode="json"),
    )


@router.get(
    "",
    response_model=OcrResultsListResponse,
    responses=ERROR_RESPONSES,
)
def list_ocr_results(
    capture_session_id: UUID,
    service: Annotated[OcrResultService, Depends(get_ocr_result_service)],
) -> OcrResultsListResponse:
    return service.list_ocr_results(capture_session_id)
