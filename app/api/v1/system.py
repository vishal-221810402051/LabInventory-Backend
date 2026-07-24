from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_system_info_service
from app.schemas.system import SystemInfoResponse
from app.services.system_info import SystemInfoService

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/info", response_model=SystemInfoResponse)
def info(
    system_info_service: Annotated[SystemInfoService, Depends(get_system_info_service)],
) -> SystemInfoResponse:
    return system_info_service.get_info()
