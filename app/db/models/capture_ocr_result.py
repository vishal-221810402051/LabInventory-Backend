from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.capture import CapturePhoto, CaptureSession, utc_now
from app.domain.ocr import OcrEngine, OcrStatus


class CaptureOcrResult(Base):
    __tablename__ = "capture_ocr_results"
    __table_args__ = (
        CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_capture_ocr_results_request_fingerprint_sha256",
        ),
        CheckConstraint("block_count >= 0", name="ck_capture_ocr_results_block_count_nonnegative"),
        CheckConstraint("line_count >= 0", name="ck_capture_ocr_results_line_count_nonnegative"),
        CheckConstraint(
            "element_count >= 0",
            name="ck_capture_ocr_results_element_count_nonnegative",
        ),
        CheckConstraint("block_count <= 10000", name="ck_capture_ocr_results_block_count_max"),
        CheckConstraint("line_count <= 50000", name="ck_capture_ocr_results_line_count_max"),
        CheckConstraint("element_count <= 250000", name="ck_capture_ocr_results_element_count_max"),
        CheckConstraint(
            "char_length(raw_text) <= 50000",
            name="ck_capture_ocr_results_raw_text_max",
        ),
        CheckConstraint(
            "corrected_text IS NULL OR char_length(corrected_text) <= 50000",
            name="ck_capture_ocr_results_corrected_text_max",
        ),
        CheckConstraint(
            "engine_version IS NULL OR char_length(engine_version) <= 100",
            name="ck_capture_ocr_results_engine_version_max",
        ),
        CheckConstraint(
            "jsonb_typeof(detected_language_tags) = 'array'",
            name="ck_capture_ocr_results_language_tags_array",
        ),
        Index("ix_capture_ocr_results_capture_session_id", "capture_session_id"),
        Index("ix_capture_ocr_results_capture_photo_id", "capture_photo_id"),
        Index("ix_capture_ocr_results_status", "status"),
        Index("ix_capture_ocr_results_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    client_ocr_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        unique=True,
        nullable=False,
    )
    capture_session_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("capture_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    capture_photo_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("capture_photos.id", ondelete="CASCADE"),
        nullable=False,
    )
    engine: Mapped[OcrEngine] = mapped_column(Enum(OcrEngine, name="ocr_engine"), nullable=False)
    engine_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[OcrStatus] = mapped_column(Enum(OcrStatus, name="ocr_status"), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    block_count: Mapped[int] = mapped_column(Integer, nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    element_count: Mapped[int] = mapped_column(Integer, nullable=False)
    detected_language_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    capture_session: Mapped[CaptureSession] = relationship("CaptureSession")
    capture_photo: Mapped[CapturePhoto] = relationship("CapturePhoto")
