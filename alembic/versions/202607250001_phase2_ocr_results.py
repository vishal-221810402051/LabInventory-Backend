"""phase2 ocr results

Revision ID: 202607250001
Revises: 202607240002
Create Date: 2026-07-25 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202607250001"
down_revision = "202607240002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

ocr_engine = postgresql.ENUM(
    "ML_KIT_TEXT_RECOGNITION_V2",
    name="ocr_engine",
    create_type=False,
)
ocr_status = postgresql.ENUM(
    "SUCCEEDED",
    "NO_TEXT",
    "FAILED",
    name="ocr_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    ocr_engine.create(bind, checkfirst=True)
    ocr_status.create(bind, checkfirst=True)

    op.create_table(
        "capture_ocr_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_ocr_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capture_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capture_photo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("engine", ocr_engine, nullable=False),
        sa.Column("engine_version", sa.String(length=100), nullable=True),
        sa.Column("status", ocr_status, nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("corrected_text", sa.Text(), nullable=True),
        sa.Column("block_count", sa.Integer(), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column("element_count", sa.Integer(), nullable=False),
        sa.Column("detected_language_tags", postgresql.JSONB(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_capture_ocr_results_request_fingerprint_sha256",
        ),
        sa.CheckConstraint(
            "block_count >= 0",
            name="ck_capture_ocr_results_block_count_nonnegative",
        ),
        sa.CheckConstraint(
            "line_count >= 0",
            name="ck_capture_ocr_results_line_count_nonnegative",
        ),
        sa.CheckConstraint(
            "element_count >= 0",
            name="ck_capture_ocr_results_element_count_nonnegative",
        ),
        sa.CheckConstraint("block_count <= 10000", name="ck_capture_ocr_results_block_count_max"),
        sa.CheckConstraint("line_count <= 50000", name="ck_capture_ocr_results_line_count_max"),
        sa.CheckConstraint(
            "element_count <= 250000",
            name="ck_capture_ocr_results_element_count_max",
        ),
        sa.CheckConstraint(
            "char_length(raw_text) <= 50000",
            name="ck_capture_ocr_results_raw_text_max",
        ),
        sa.CheckConstraint(
            "corrected_text IS NULL OR char_length(corrected_text) <= 50000",
            name="ck_capture_ocr_results_corrected_text_max",
        ),
        sa.CheckConstraint(
            "engine_version IS NULL OR char_length(engine_version) <= 100",
            name="ck_capture_ocr_results_engine_version_max",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(detected_language_tags) = 'array'",
            name="ck_capture_ocr_results_language_tags_array",
        ),
        sa.ForeignKeyConstraint(
            ["capture_photo_id"],
            ["capture_photos.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["capture_session_id"],
            ["capture_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_ocr_id"),
    )
    op.create_index(
        "ix_capture_ocr_results_capture_session_id",
        "capture_ocr_results",
        ["capture_session_id"],
    )
    op.create_index(
        "ix_capture_ocr_results_capture_photo_id",
        "capture_ocr_results",
        ["capture_photo_id"],
    )
    op.create_index("ix_capture_ocr_results_status", "capture_ocr_results", ["status"])
    op.create_index("ix_capture_ocr_results_created_at", "capture_ocr_results", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("ix_capture_ocr_results_created_at", table_name="capture_ocr_results")
    op.drop_index("ix_capture_ocr_results_status", table_name="capture_ocr_results")
    op.drop_index("ix_capture_ocr_results_capture_photo_id", table_name="capture_ocr_results")
    op.drop_index("ix_capture_ocr_results_capture_session_id", table_name="capture_ocr_results")
    op.drop_table("capture_ocr_results")
    ocr_status.drop(bind, checkfirst=True)
    ocr_engine.drop(bind, checkfirst=True)
