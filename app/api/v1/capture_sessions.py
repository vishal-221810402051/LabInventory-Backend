from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile, status
from fastapi.responses import JSONResponse

from app.api.dependencies import get_capture_session_service
from app.schemas.capture_sessions import (
    CapturePhotoResponse,
    CaptureSessionCreateRequest,
    CaptureSessionResponse,
)
from app.schemas.errors import ErrorEnvelope
from app.services.capture_sessions import CaptureSessionService

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    409: {"model": ErrorEnvelope},
    413: {"model": ErrorEnvelope},
    415: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
    500: {"model": ErrorEnvelope},
}

router = APIRouter(prefix="/api/v1/capture-sessions", tags=["capture-sessions"])


@router.post(
    "",
    response_model=CaptureSessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_200_OK: {"model": CaptureSessionResponse}, **ERROR_RESPONSES},
)
def create_capture_session(
    request: CaptureSessionCreateRequest,
    service: Annotated[CaptureSessionService, Depends(get_capture_session_service)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="UUID idempotency key. Must equal client_capture_id.",
        ),
    ] = None,
) -> JSONResponse:
    result = service.create_capture_session(request, idempotency_key=idempotency_key)
    return JSONResponse(
        status_code=result.status_code,
        content=result.response.model_dump(mode="json"),
    )


@router.get(
    "/{capture_session_id}",
    response_model=CaptureSessionResponse,
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
def get_capture_session(
    capture_session_id: UUID,
    service: Annotated[CaptureSessionService, Depends(get_capture_session_service)],
) -> CaptureSessionResponse:
    return service.get_capture_session(capture_session_id)


@router.post(
    "/{capture_session_id}/photos",
    response_model=CapturePhotoResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_200_OK: {"model": CapturePhotoResponse}, **ERROR_RESPONSES},
)
async def upload_capture_photo(
    capture_session_id: UUID,
    client_photo_id: Annotated[
        UUID,
        Form(description="Client-generated UUID for this photo upload."),
    ],
    sha256: Annotated[
        str,
        Form(description="Lowercase SHA-256 hex digest of the uploaded photo bytes."),
    ],
    file: Annotated[
        UploadFile,
        File(description="JPEG, PNG, or WebP photo. Maximum size is 15 MiB."),
    ],
    service: Annotated[CaptureSessionService, Depends(get_capture_session_service)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="UUID idempotency key. Must equal client_photo_id.",
        ),
    ] = None,
) -> JSONResponse:
    result = await service.upload_photo(
        capture_session_id=capture_session_id,
        client_photo_id=client_photo_id,
        declared_sha256=sha256,
        upload=file,
        idempotency_key=idempotency_key,
    )
    return JSONResponse(
        status_code=result.status_code,
        content=result.response.model_dump(mode="json"),
    )


@router.post(
    "/{capture_session_id}/complete",
    response_model=CaptureSessionResponse,
    responses=ERROR_RESPONSES,
)
def complete_capture_session(
    capture_session_id: UUID,
    service: Annotated[CaptureSessionService, Depends(get_capture_session_service)],
) -> CaptureSessionResponse:
    return service.complete_capture_session(capture_session_id)
