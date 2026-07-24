from __future__ import annotations

from fastapi import status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import ApplicationError
from app.core.logging import get_logger

logger = get_logger(__name__)


class ReadinessService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def ensure_ready(self) -> None:
        try:
            self._session.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            logger.warning(
                "Database readiness check failed",
                exc_info=exc,
                extra={"event": "readiness.failure"},
            )
            raise ApplicationError(
                code="DATABASE_UNAVAILABLE",
                message="Database readiness check failed.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc
