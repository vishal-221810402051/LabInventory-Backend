"""phase1 capture sessions

Revision ID: 202607240002
Revises: 202607240001
Create Date: 2026-07-24 00:00:01.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202607240002"
down_revision = "202607240001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

capture_mode = postgresql.ENUM(
    "PHOTO",
    "MANUAL",
    "PHOTO_WITH_MANUAL",
    name="capture_mode",
    create_type=False,
)
capture_status = postgresql.ENUM(
    "DRAFT",
    "READY_FOR_PROCESSING",
    name="capture_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    capture_mode.create(bind, checkfirst=True)
    capture_status.create(bind, checkfirst=True)

    op.create_table(
        "capture_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_capture_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capture_mode", capture_mode, nullable=False),
        sa.Column("status", capture_status, nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("quantity", sa.Numeric(), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("category_hint", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity > 0",
            name="ck_capture_sessions_quantity_gt_0",
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_capture_sessions_request_fingerprint_sha256",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_capture_id"),
    )
    op.create_index("ix_capture_sessions_status", "capture_sessions", ["status"])
    op.create_index("ix_capture_sessions_created_at", "capture_sessions", ["created_at"])

    op.create_table(
        "capture_photos",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_photo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capture_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("size_bytes > 0", name="ck_capture_photos_size_bytes_gt_0"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_capture_photos_sha256"),
        sa.ForeignKeyConstraint(
            ["capture_session_id"],
            ["capture_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_photo_id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        "ix_capture_photos_capture_session_id",
        "capture_photos",
        ["capture_session_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("ix_capture_photos_capture_session_id", table_name="capture_photos")
    op.drop_table("capture_photos")
    op.drop_index("ix_capture_sessions_created_at", table_name="capture_sessions")
    op.drop_index("ix_capture_sessions_status", table_name="capture_sessions")
    op.drop_table("capture_sessions")
    capture_status.drop(bind, checkfirst=True)
    capture_mode.drop(bind, checkfirst=True)
