from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.capture import CapturePhoto, CaptureSession
from app.db.models.capture_ocr_result import CaptureOcrResult


class OcrResultRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_capture_session(self, capture_session_id: UUID) -> CaptureSession | None:
        statement = select(CaptureSession).where(CaptureSession.id == capture_session_id)
        return self._session.scalar(statement)

    def get_photo_by_client_photo_id(self, client_photo_id: UUID) -> CapturePhoto | None:
        statement = select(CapturePhoto).where(CapturePhoto.client_photo_id == client_photo_id)
        return self._session.scalar(statement)

    def get_by_client_ocr_id(self, client_ocr_id: UUID) -> CaptureOcrResult | None:
        statement = select(CaptureOcrResult).where(CaptureOcrResult.client_ocr_id == client_ocr_id)
        return self._session.scalar(statement)

    def list_by_capture_session_id(self, capture_session_id: UUID) -> list[CaptureOcrResult]:
        statement = (
            select(CaptureOcrResult)
            .where(CaptureOcrResult.capture_session_id == capture_session_id)
            .order_by(CaptureOcrResult.created_at, CaptureOcrResult.id)
        )
        return list(self._session.scalars(statement))
