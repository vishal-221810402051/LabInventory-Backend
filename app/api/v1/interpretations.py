from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from fastapi.responses import JSONResponse

from app.api.dependencies import get_interpretation_service
from app.schemas.errors import ErrorEnvelope
from app.schemas.interpretations import (
    AiStatusResponse,
    InterpretationCreateRequest,
    InterpretationListResponse,
    InterpretationResponse,
)
from app.services.interpretations import InterpretationService

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    409: {"model": ErrorEnvelope},
    413: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
    502: {"model": ErrorEnvelope},
    503: {"model": ErrorEnvelope},
    504: {"model": ErrorEnvelope},
}

ai_router = APIRouter(prefix="/api/v1/ai", tags=["ai"])
interpretations_router = APIRouter(
    prefix="/api/v1/capture-sessions/{capture_session_id}/interpretations",
    tags=["interpretations"],
)


@ai_router.get("/status", response_model=AiStatusResponse)
def get_ai_status(
    service: Annotated[InterpretationService, Depends(get_interpretation_service)],
) -> AiStatusResponse:
    return service.ai_status()


@interpretations_router.post(
    "",
    response_model=InterpretationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_200_OK: {"model": InterpretationResponse},
        status.HTTP_202_ACCEPTED: {"model": InterpretationResponse},
        **ERROR_RESPONSES,
    },
)
def create_interpretation(
    capture_session_id: UUID,
    request: InterpretationCreateRequest,
    service: Annotated[InterpretationService, Depends(get_interpretation_service)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="UUID idempotency key. Must equal client_interpretation_id.",
        ),
    ] = None,
) -> JSONResponse:
    result = service.create_interpretation(
        capture_session_id,
        request,
        idempotency_key=idempotency_key,
    )
    return JSONResponse(
        status_code=result.status_code,
        content=result.response.model_dump(mode="json"),
    )


@interpretations_router.get(
    "",
    response_model=InterpretationListResponse,
    responses=ERROR_RESPONSES,
)
def list_interpretations(
    capture_session_id: UUID,
    service: Annotated[InterpretationService, Depends(get_interpretation_service)],
) -> InterpretationListResponse:
    return service.list_interpretations(capture_session_id)


@interpretations_router.get(
    "/{interpretation_id}",
    response_model=InterpretationResponse,
    responses=ERROR_RESPONSES,
)
def get_interpretation(
    capture_session_id: UUID,
    interpretation_id: UUID,
    service: Annotated[InterpretationService, Depends(get_interpretation_service)],
) -> InterpretationResponse:
    return service.get_interpretation(capture_session_id, interpretation_id)
