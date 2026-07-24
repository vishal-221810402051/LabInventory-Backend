from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.capture import CaptureMode, CaptureStatus


def utc_now() -> datetime:
    return datetime.now(UTC)


class CaptureSession(Base):
    __tablename__ = "capture_sessions"
    __table_args__ = (
        CheckConstraint(
            "quantity IS NULL OR quantity > 0",
            name="ck_capture_sessions_quantity_gt_0",
        ),
        CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_capture_sessions_request_fingerprint_sha256",
        ),
        Index("ix_capture_sessions_status", "status"),
        Index("ix_capture_sessions_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    client_capture_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        unique=True,
        nullable=False,
    )
    capture_mode: Mapped[CaptureMode] = mapped_column(
        Enum(CaptureMode, name="capture_mode"),
        nullable=False,
    )
    status: Mapped[CaptureStatus] = mapped_column(
        Enum(CaptureStatus, name="capture_status"),
        nullable=False,
        default=CaptureStatus.DRAFT,
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    category_hint: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    photos: Mapped[list[CapturePhoto]] = relationship(
        "CapturePhoto",
        back_populates="capture_session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class CapturePhoto(Base):
    __tablename__ = "capture_photos"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_capture_photos_size_bytes_gt_0"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_capture_photos_sha256"),
        Index("ix_capture_photos_capture_session_id", "capture_session_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    client_photo_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        unique=True,
        nullable=False,
    )
    capture_session_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("capture_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    storage_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    capture_session: Mapped[CaptureSession] = relationship(
        "CaptureSession",
        back_populates="photos",
    )
