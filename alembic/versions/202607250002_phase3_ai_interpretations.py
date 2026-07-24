"""phase3 ai interpretations

Revision ID: 202607250002
Revises: 202607250001
Create Date: 2026-07-25 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202607250002"
down_revision = "202607250001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

ai_interpretation_status = postgresql.ENUM(
    "PROCESSING",
    "SUCCEEDED",
    "INSUFFICIENT_INFORMATION",
    "FAILED",
    "REFUSED",
    name="ai_interpretation_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    ai_interpretation_status.create(bind, checkfirst=True)

    op.create_table(
        "capture_interpretations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_interpretation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capture_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", ai_interpretation_status, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("requested_locale", sa.String(length=16), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("suggestion_json", postgresql.JSONB(), nullable=True),
        sa.Column("input_token_count", sa.Integer(), nullable=True),
        sa.Column("output_token_count", sa.Integer(), nullable=True),
        sa.Column("total_token_count", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("provider_response_id", sa.String(length=200), nullable=True),
        sa.Column("safe_error_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_capture_interpretations_source_fingerprint_sha256",
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_capture_interpretations_request_fingerprint_sha256",
        ),
        sa.CheckConstraint(
            "input_token_count IS NULL OR input_token_count >= 0",
            name="ck_capture_interpretations_input_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "output_token_count IS NULL OR output_token_count >= 0",
            name="ck_capture_interpretations_output_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "total_token_count IS NULL OR total_token_count >= 0",
            name="ck_capture_interpretations_total_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="ck_capture_interpretations_latency_nonnegative",
        ),
        sa.CheckConstraint(
            "char_length(provider) <= 32",
            name="ck_capture_interpretations_provider_max",
        ),
        sa.CheckConstraint(
            "char_length(model) <= 100",
            name="ck_capture_interpretations_model_max",
        ),
        sa.CheckConstraint(
            "char_length(prompt_version) <= 100",
            name="ck_capture_interpretations_prompt_version_max",
        ),
        sa.CheckConstraint(
            "char_length(schema_version) <= 32",
            name="ck_capture_interpretations_schema_version_max",
        ),
        sa.CheckConstraint(
            "char_length(requested_locale) <= 16",
            name="ck_capture_interpretations_requested_locale_max",
        ),
        sa.CheckConstraint(
            "provider_response_id IS NULL OR char_length(provider_response_id) <= 200",
            name="ck_capture_interpretations_provider_response_id_max",
        ),
        sa.CheckConstraint(
            "safe_error_code IS NULL OR char_length(safe_error_code) <= 100",
            name="ck_capture_interpretations_safe_error_code_max",
        ),
        sa.ForeignKeyConstraint(
            ["capture_session_id"],
            ["capture_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_interpretation_id"),
    )
    op.create_index(
        "ix_capture_interpretations_capture_session_id",
        "capture_interpretations",
        ["capture_session_id"],
    )
    op.create_index("ix_capture_interpretations_status", "capture_interpretations", ["status"])
    op.create_index(
        "ix_capture_interpretations_created_at",
        "capture_interpretations",
        ["created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("ix_capture_interpretations_created_at", table_name="capture_interpretations")
    op.drop_index("ix_capture_interpretations_status", table_name="capture_interpretations")
    op.drop_index(
        "ix_capture_interpretations_capture_session_id",
        table_name="capture_interpretations",
    )
    op.drop_table("capture_interpretations")
    ai_interpretation_status.drop(bind, checkfirst=True)
