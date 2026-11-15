from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, utcnow


class Action(Base):
    """A write operation prepared during a call. Executes only after approval."""

    __tablename__ = "actions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("call_sessions.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="awaiting_approval", index=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    risk_flags: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    # Set when execution is claimed; unique so one version can be claimed only once.
    idempotency_key: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_mode: Mapped[str] = mapped_column(String(20), default="mock")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Approval(Base):
    """An explicit approval of exactly one version of an action."""

    __tablename__ = "approvals"
    __table_args__ = (UniqueConstraint("action_id", "action_version", name="uq_approval_action_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("actions.id"), index=True)
    action_version: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    session_id: Mapped[str] = mapped_column(ForeignKey("call_sessions.id"))
    method: Mapped[str] = mapped_column(String(20), default="voice")
    approved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
