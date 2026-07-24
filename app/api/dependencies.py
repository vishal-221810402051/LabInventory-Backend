from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import get_session_factory
from app.providers.item_interpretation import (
    DisabledItemInterpretationProvider,
    ItemInterpretationProvider,
    OpenAiItemInterpretationProvider,
)
from app.services.capture_sessions import CaptureSessionService
from app.services.interpretations import InterpretationService
from app.services.ocr_results import OcrResultService
from app.services.readiness import ReadinessService
from app.services.system_info import SystemInfoService
from app.storage.local import LocalStorage


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


def get_capture_session_service(
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
) -> CaptureSessionService:
    return CaptureSessionService(session, LocalStorage(settings.upload_root))


def get_ocr_result_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> OcrResultService:
    return OcrResultService(session)


def get_item_interpretation_provider(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings_dependency)],
) -> ItemInterpretationProvider:
    provider = getattr(request.app.state, "item_interpretation_provider", None)
    if provider is not None:
        return provider
    if not settings.ai_interpretation_enabled or not settings.openai_configured:
        return DisabledItemInterpretationProvider()
    return OpenAiItemInterpretationProvider(settings)


def get_interpretation_service(
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
    provider: Annotated[ItemInterpretationProvider, Depends(get_item_interpretation_provider)],
) -> InterpretationService:
    return InterpretationService(session, settings, provider)
