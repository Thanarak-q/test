"""ORM models. Alembic autogenerate imports this module, so every table must land here.

Table names carry a domain prefix (money_transactions, task_items) and every
user-owned table carries user_id, even while the app has a single user.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

__all__ = ["Base", "LlmModel", "LlmQuota", "LlmUsageLog"]


class LlmModel(Base):
    """Model whitelist. Source of truth for llm_models service; Redis only caches it."""

    __tablename__ = "llm_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[str] = mapped_column(String(64), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")


class LlmQuota(Base):
    __tablename__ = "llm_quotas"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    token_limit: Mapped[int] = mapped_column(BigInteger)
    token_used: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class LlmUsageLog(Base):
    __tablename__ = "llm_usage_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    model: Mapped[str] = mapped_column(String(64))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
