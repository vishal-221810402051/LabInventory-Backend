from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.capture import CapturePhoto, CaptureSession


class CaptureSessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(
        self,
        capture_session_id: UUID,
        *,
        for_update: bool = False,
    ) -> CaptureSession | None:
        statement = select(CaptureSession).where(CaptureSession.id == capture_session_id)
        if for_update:
            statement = statement.with_for_update()
        return self._session.scalar(statement)

    def get_by_client_capture_id(self, client_capture_id: UUID) -> CaptureSession | None:
        statement = select(CaptureSession).where(
            CaptureSession.client_capture_id == client_capture_id
        )
        return self._session.scalar(statement)

    def get_photo_by_client_photo_id(self, client_photo_id: UUID) -> CapturePhoto | None:
        statement = select(CapturePhoto).where(CapturePhoto.client_photo_id == client_photo_id)
        return self._session.scalar(statement)

    def count_photos(self, capture_session_id: UUID) -> int:
        statement = select(func.count()).select_from(CapturePhoto).where(
            CapturePhoto.capture_session_id == capture_session_id
        )
        return self._session.scalar(statement) or 0
