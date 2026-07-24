from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_readiness_service
from app.schemas.errors import ErrorEnvelope
from app.schemas.health import LiveResponse, ReadyResponse
from app.services.readiness import ReadinessService

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=LiveResponse)
def live() -> LiveResponse:
    return LiveResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ErrorEnvelope}},
)
def ready(
    readiness_service: Annotated[ReadinessService, Depends(get_readiness_service)],
) -> ReadyResponse:
    readiness_service.ensure_ready()
    return ReadyResponse(status="ready", database="available")
