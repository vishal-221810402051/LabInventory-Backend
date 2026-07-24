from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.capture import CaptureSession, utc_now
from app.domain.interpretation import InterpretationStatus


class CaptureInterpretation(Base):
    __tablename__ = "capture_interpretations"
    __table_args__ = (
        CheckConstraint(
            "source_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_capture_interpretations_source_fingerprint_sha256",
        ),
        CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_capture_interpretations_request_fingerprint_sha256",
        ),
        CheckConstraint(
            "input_token_count IS NULL OR input_token_count >= 0",
            name="ck_capture_interpretations_input_tokens_nonnegative",
        ),
        CheckConstraint(
            "output_token_count IS NULL OR output_token_count >= 0",
            name="ck_capture_interpretations_output_tokens_nonnegative",
        ),
        CheckConstraint(
            "total_token_count IS NULL OR total_token_count >= 0",
            name="ck_capture_interpretations_total_tokens_nonnegative",
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="ck_capture_interpretations_latency_nonnegative",
        ),
        CheckConstraint(
            "char_length(provider) <= 32",
            name="ck_capture_interpretations_provider_max",
        ),
        CheckConstraint("char_length(model) <= 100", name="ck_capture_interpretations_model_max"),
        CheckConstraint(
            "char_length(prompt_version) <= 100",
            name="ck_capture_interpretations_prompt_version_max",
        ),
        CheckConstraint(
            "char_length(schema_version) <= 32",
            name="ck_capture_interpretations_schema_version_max",
        ),
        CheckConstraint(
            "char_length(requested_locale) <= 16",
            name="ck_capture_interpretations_requested_locale_max",
        ),
        CheckConstraint(
            "provider_response_id IS NULL OR char_length(provider_response_id) <= 200",
            name="ck_capture_interpretations_provider_response_id_max",
        ),
        CheckConstraint(
            "safe_error_code IS NULL OR char_length(safe_error_code) <= 100",
            name="ck_capture_interpretations_safe_error_code_max",
        ),
        Index("ix_capture_interpretations_capture_session_id", "capture_session_id"),
        Index("ix_capture_interpretations_status", "status"),
        Index("ix_capture_interpretations_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    client_interpretation_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        unique=True,
        nullable=False,
    )
    capture_session_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("capture_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[InterpretationStatus] = mapped_column(
        Enum(InterpretationStatus, name="ai_interpretation_status"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_locale: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    suggestion_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    input_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_response_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    safe_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
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
