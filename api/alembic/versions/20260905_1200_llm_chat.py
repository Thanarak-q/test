"""llm chat pipeline: models whitelist, quotas, usage logs

Revision ID: 20260905_llm
Revises:
Create Date: 2026-09-05
"""

import sqlalchemy as sa

from alembic import op

revision = "20260905_llm"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    models = op.create_table(
        "llm_models",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_id"),
    )
    # Empty whitelist rejects every request, so ship the pipeline with a usable one.
    op.bulk_insert(
        models,
        [
            {"model_id": "gpt-4o", "is_active": True},
            {"model_id": "gpt-4.1", "is_active": True},
        ],
    )

    op.create_table(
        "llm_quotas",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_limit", sa.BigInteger(), nullable=False),
        sa.Column("token_used", sa.BigInteger(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "llm_usage_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_usage_logs_user_id", "llm_usage_logs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_logs_user_id", table_name="llm_usage_logs")
    op.drop_table("llm_usage_logs")
    op.drop_table("llm_quotas")
    op.drop_table("llm_models")
