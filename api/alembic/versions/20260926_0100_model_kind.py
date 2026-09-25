"""model kind: chat or embedding, and seed text-embedding-3-small

- llm_models.kind ('chat' | 'embedding'). Existing rows are chat models.
  Each endpoint accepts only its own kind, so an embedding model can never
  be sent to /chat/completions or the other way round.
- Seeds text-embedding-3-small (8,191-token input, no output: embeddings
  return vectors, so max_output_tokens is 0).

Revision ID: 20260926_kind
Revises: 20260925_chat
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260926_kind"
down_revision: str | None = "20260925_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_models",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="chat"),
    )
    op.create_check_constraint(
        "ck_llm_models_kind", "llm_models", "kind IN ('chat', 'embedding')"
    )
    op.execute(
        "INSERT INTO llm_models "
        "(name, kind, context_window, max_output_tokens, status, updated_at) "
        "VALUES ('text-embedding-3-small', 'embedding', 8191, 0, 'enabled', "
        "UTC_TIMESTAMP(6))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM llm_models WHERE kind = 'embedding'")
    op.drop_constraint("ck_llm_models_kind", "llm_models", type_="check")
    op.drop_column("llm_models", "kind")
