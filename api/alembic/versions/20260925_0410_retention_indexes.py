"""retention indexes: created_at on every append-only log

The retention job deletes by age across all users; without these it would
scan whole tables (docs/NON_FUNCTIONAL.md §2.2).

Revision ID: 20260925_retention
Revises: 20260925_schema
Create Date: 2026-09-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260925_retention"
down_revision: str | None = "20260925_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_identity_api_key_audit_logs_created_at"),
        "identity_api_key_audit_logs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_identity_auth_failure_logs_created_at"),
        "identity_auth_failure_logs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_usage_logs_created_at"),
        "llm_usage_logs",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_llm_usage_logs_created_at"), table_name="llm_usage_logs")
    op.drop_index(
        op.f("ix_identity_auth_failure_logs_created_at"),
        table_name="identity_auth_failure_logs",
    )
    op.drop_index(
        op.f("ix_identity_api_key_audit_logs_created_at"),
        table_name="identity_api_key_audit_logs",
    )
