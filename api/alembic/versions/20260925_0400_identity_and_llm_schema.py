"""identity and llm schema — replaces 20260905_llm

The previous migration never created the identity_* tables and gave llm_models
different columns from the ORM. This one matches app/models.py exactly; it is
the only migration, so databases created from the old one must be recreated.

Datetime columns are DATETIME(6) holding UTC (app.db.UtcDateTime). They are
spelled as the MySQL type here so the migration never depends on app code.

Revision ID: 20260925_schema
Revises:
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "20260925_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identity_auth_failure_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("key_id", sa.String(length=26), nullable=False),
        sa.Column("source_ip", sa.String(length=45), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_identity_auth_failure_logs_key_id"),
        "identity_auth_failure_logs",
        ["key_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_identity_auth_failure_logs_source_ip"),
        "identity_auth_failure_logs",
        ["source_ip"],
        unique=False,
    )
    op.create_table(
        "identity_users",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    llm_models = op.create_table(
        "llm_models",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    # An empty whitelist rejects every request, so ship a usable one.
    # TODO(chat-pipeline): confirm names and windows with the pipeline owner.
    op.bulk_insert(
        llm_models,
        [
            {"name": "gpt-4o", "context_window": 128_000, "is_active": True},
            {"name": "gpt-4.1", "context_window": 1_047_576, "is_active": True},
        ],
    )
    op.create_table(
        "identity_api_key_audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=26), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("source_ip", sa.String(length=45), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity_users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_identity_api_key_audit_logs_request_id"),
        "identity_api_key_audit_logs",
        ["request_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_identity_api_key_audit_logs_target_id"),
        "identity_api_key_audit_logs",
        ["target_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_identity_api_key_audit_logs_user_id"),
        "identity_api_key_audit_logs",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "identity_api_keys",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("key_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("deleted_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("last_used_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'revoked', 'deleted')",
            name="ck_identity_api_keys_status",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity_users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index(
        "ix_identity_api_keys_user_id_status",
        "identity_api_keys",
        ["user_id", "status"],
        unique=False,
    )
    op.create_table(
        "llm_quotas",
        sa.Column("user_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("token_limit", sa.BigInteger(), nullable=False),
        sa.Column("token_used", sa.BigInteger(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity_users.id"],
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "llm_usage_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("key_id", sa.String(length=26), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint("source IN ('api', 'web')", name="ck_llm_usage_logs_source"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity_users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_llm_usage_logs_key_id"), "llm_usage_logs", ["key_id"], unique=False
    )
    op.create_index(
        "ix_llm_usage_logs_user_id_created_at",
        "llm_usage_logs",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_llm_usage_logs_user_id_created_at", table_name="llm_usage_logs")
    op.drop_index(op.f("ix_llm_usage_logs_key_id"), table_name="llm_usage_logs")
    op.drop_table("llm_usage_logs")
    op.drop_table("llm_quotas")
    op.drop_index("ix_identity_api_keys_user_id_status", table_name="identity_api_keys")
    op.drop_table("identity_api_keys")
    op.drop_index(
        op.f("ix_identity_api_key_audit_logs_user_id"),
        table_name="identity_api_key_audit_logs",
    )
    op.drop_index(
        op.f("ix_identity_api_key_audit_logs_target_id"),
        table_name="identity_api_key_audit_logs",
    )
    op.drop_index(
        op.f("ix_identity_api_key_audit_logs_request_id"),
        table_name="identity_api_key_audit_logs",
    )
    op.drop_table("identity_api_key_audit_logs")
    op.drop_table("llm_models")
    op.drop_table("identity_users")
    op.drop_index(
        op.f("ix_identity_auth_failure_logs_source_ip"),
        table_name="identity_auth_failure_logs",
    )
    op.drop_index(
        op.f("ix_identity_auth_failure_logs_key_id"),
        table_name="identity_auth_failure_logs",
    )
    op.drop_table("identity_auth_failure_logs")
