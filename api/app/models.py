"""ORM models. Alembic autogenerate imports this module, so every table must land here.

Table names carry a domain prefix (money_transactions, task_items) and every
user-owned table carries user_id, even while the app has a single user.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

__all__ = ["ApiKey", "ApiKeyAuditLog", "Base", "LlmModel", "User"]


class User(Base):
    __tablename__ = "identity_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    api_keys: Mapped[list["ApiKey"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class ApiKey(Base):
    __tablename__ = "identity_api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("identity_users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="api_keys")


class LlmModel(Base):
    __tablename__ = "llm_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    max_tokens: Mapped[int] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")


class ApiKeyAuditLog(Base):
    __tablename__ = "identity_api_key_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("identity_users.id"), nullable=False, index=True
    )  # owner of this API Key

    action: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # [create, revoke, delete]
    actor_id: Mapped[int | None] = mapped_column(BigInteger)  # nullable if its "system"
    actor_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # person who create, revoke, delete : [owner, admin, system]

    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_ip: Mapped[str | None] = mapped_column(String(45))
