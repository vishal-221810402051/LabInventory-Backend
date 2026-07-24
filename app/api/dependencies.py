from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import get_session_factory
from app.services.readiness import ReadinessService
from app.services.system_info import SystemInfoService


def get_settings_dependency(request: Request) -> Settings:
    return request.app.state.settings


def get_db_session(
    settings: Annotated[Settings, Depends(get_settings_dependency)],
) -> Generator[Session, None, None]:
    session_factory = get_session_factory(settings.effective_database_url)
    with session_factory() as session:
        yield session


def get_readiness_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> ReadinessService:
    return ReadinessService(session)


def get_system_info_service(request: Request) -> SystemInfoService:
    return request.app.state.system_info_service
