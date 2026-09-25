"""chat pipeline: model status and output cap, provider call log, thin usage log

- llm_models: `is_active` becomes `status` ('enabled' | 'disabled'), plus
  `max_output_tokens` and `updated_at` for admin changes.
- llm_model_audit_logs: admin enable/disable events.
- llm_usage_logs: only what quota was charged (tokens, source, key,
  request id). `total_tokens` is renamed, so existing history is kept; model
  and per-call detail move to llm_provider_call_logs.
- llm_provider_call_logs: one metadata row per provider call.
- llm_quotas dropped: quota lives in the main application's Redis hash
  `quota:{user_id}`, with our in-flight reservations beside it.

Revision ID: 20260925_chat
Revises: 20260925_retention
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "20260925_chat"
down_revision: str | None = "20260925_retention"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DATETIME = mysql.DATETIME(fsp=6)

# Published output limits for the seeded models; anything else starts at a
# conservative cap an admin can raise.
_MAX_OUTPUT = {"gpt-4o": 16_384, "gpt-4.1": 32_768}
_DEFAULT_MAX_OUTPUT = 4_096


def upgrade() -> None:
    # llm_models: add nullable, backfill, then tighten.
    op.add_column("llm_models", sa.Column("max_output_tokens", sa.Integer()))
    op.add_column("llm_models", sa.Column("status", sa.String(length=10)))
    op.add_column("llm_models", sa.Column("updated_at", _DATETIME))
    op.execute(
        "UPDATE llm_models SET "
        "status = IF(is_active, 'enabled', 'disabled'), "
        "updated_at = UTC_TIMESTAMP(6), "
        f"max_output_tokens = {_DEFAULT_MAX_OUTPUT}"
    )
    models = sa.table(
        "llm_models", sa.column("name", sa.String), sa.column("max_output_tokens")
    )
    for name, cap in _MAX_OUTPUT.items():
        op.execute(
            models.update().where(models.c.name == name).values(max_output_tokens=cap)
        )
    op.alter_column(
        "llm_models", "max_output_tokens", existing_type=sa.Integer(), nullable=False
    )
    op.alter_column(
        "llm_models", "status", existing_type=sa.String(length=10), nullable=False
    )
    op.alter_column("llm_models", "updated_at", existing_type=_DATETIME, nullable=False)
    op.create_check_constraint(
        "ck_llm_models_status", "llm_models", "status IN ('enabled', 'disabled')"
    )
    op.drop_column("llm_models", "is_active")

    op.create_table(
        "llm_model_audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("source_ip", sa.String(length=45), nullable=True),
        sa.Column("created_at", _DATETIME, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_llm_model_audit_logs_actor_id"), "llm_model_audit_logs", ["actor_id"]
    )
    op.create_index(
        op.f("ix_llm_model_audit_logs_created_at"),
        "llm_model_audit_logs",
        ["created_at"],
    )
    op.create_index(
        op.f("ix_llm_model_audit_logs_target_id"), "llm_model_audit_logs", ["target_id"]
    )

    op.create_table(
        "llm_provider_call_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.String(length=26), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", _DATETIME, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["identity_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_llm_provider_call_logs_created_at"),
        "llm_provider_call_logs",
        ["created_at"],
    )
    op.create_index(
        op.f("ix_llm_provider_call_logs_request_id"),
        "llm_provider_call_logs",
        ["request_id"],
    )
    op.create_index(
        "ix_llm_provider_call_logs_user_id_created_at",
        "llm_provider_call_logs",
        ["user_id", "created_at"],
    )

    # llm_usage_logs: keep the charged amount, drop per-call detail.
    op.alter_column(
        "llm_usage_logs",
        "total_tokens",
        new_column_name="tokens",
        existing_type=sa.Integer(),
        existing_nullable=False,
    )
    op.add_column(
        "llm_usage_logs", sa.Column("request_id", sa.String(length=64), nullable=True)
    )
    op.create_index(
        op.f("ix_llm_usage_logs_request_id"), "llm_usage_logs", ["request_id"]
    )
    for column in ("model", "prompt_tokens", "completion_tokens", "latency_ms"):
        op.drop_column("llm_usage_logs", column)

    op.drop_table("llm_quotas")


def downgrade() -> None:
    op.create_table(
        "llm_quotas",
        sa.Column("user_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("token_limit", sa.BigInteger(), nullable=False),
        sa.Column("token_used", sa.BigInteger(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["identity_users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.add_column(
        "llm_usage_logs",
        sa.Column("model", sa.String(length=64), nullable=False, server_default=""),
    )
    for column in ("prompt_tokens", "completion_tokens", "latency_ms"):
        op.add_column(
            "llm_usage_logs",
            sa.Column(column, sa.Integer(), nullable=False, server_default="0"),
        )
    op.drop_index(op.f("ix_llm_usage_logs_request_id"), table_name="llm_usage_logs")
    op.drop_column("llm_usage_logs", "request_id")
    op.alter_column(
        "llm_usage_logs",
        "tokens",
        new_column_name="total_tokens",
        existing_type=sa.Integer(),
        existing_nullable=False,
    )

    op.drop_table("llm_provider_call_logs")
    op.drop_table("llm_model_audit_logs")

    op.add_column(
        "llm_models",
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
    )
    op.execute("UPDATE llm_models SET is_active = (status = 'enabled')")
    op.drop_constraint("ck_llm_models_status", "llm_models", type_="check")
    for column in ("updated_at", "status", "max_output_tokens"):
        op.drop_column("llm_models", column)
