from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, utcnow


class CallSession(Base):
    """One phone call (or simulated call). The id is the provider call id."""

    __tablename__ = "call_sessions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    auth_level: Mapped[str] = mapped_column(String(20), default="anonymous")
    authenticated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failed_auth_attempts: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(32), default="listening")
    channel: Mapped[str] = mapped_column(String(20), default="tool_api")  # tool_api | simulator
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)
    # Small conversation context kept by the backend (never the transcript).
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
