from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.capture import CapturePhoto, CaptureSession
from app.db.models.capture_interpretation import CaptureInterpretation
from app.db.models.capture_ocr_result import CaptureOcrResult


class InterpretationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_capture_session(self, capture_session_id: UUID) -> CaptureSession | None:
        statement = select(CaptureSession).where(CaptureSession.id == capture_session_id)
        return self._session.scalar(statement)

    def count_photos(self, capture_session_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(CapturePhoto)
            .where(CapturePhoto.capture_session_id == capture_session_id)
        )
        return self._session.scalar(statement) or 0

    def list_ocr_results(self, capture_session_id: UUID) -> list[CaptureOcrResult]:
        statement = (
            select(CaptureOcrResult)
            .where(CaptureOcrResult.capture_session_id == capture_session_id)
            .order_by(CaptureOcrResult.created_at, CaptureOcrResult.id)
        )
        return list(self._session.scalars(statement))

    def get_by_client_interpretation_id(
        self,
        client_interpretation_id: UUID,
    ) -> CaptureInterpretation | None:
        statement = select(CaptureInterpretation).where(
            CaptureInterpretation.client_interpretation_id == client_interpretation_id
        )
        return self._session.scalar(statement)

    def get_by_id(
        self,
        capture_session_id: UUID,
        interpretation_id: UUID,
    ) -> CaptureInterpretation | None:
        statement = select(CaptureInterpretation).where(
            CaptureInterpretation.capture_session_id == capture_session_id,
            CaptureInterpretation.id == interpretation_id,
        )
        return self._session.scalar(statement)

    def list_by_capture_session_id(
        self,
        capture_session_id: UUID,
    ) -> list[CaptureInterpretation]:
        statement = (
            select(CaptureInterpretation)
            .where(CaptureInterpretation.capture_session_id == capture_session_id)
            .order_by(CaptureInterpretation.created_at, CaptureInterpretation.id)
        )
        return list(self._session.scalars(statement))
