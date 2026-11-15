from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, utcnow


class AuditEvent(Base):
    """Append-only audit trail. ``detail`` is redacted before it is stored."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    action_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    tool: Mapped[str | None] = mapped_column(String(60), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
