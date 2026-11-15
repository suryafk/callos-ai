"""Persistent mock workspace. Every row belongs to exactly one user."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, utcnow


class MockEmail(Base):
    __tablename__ = "mock_emails"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    folder: Mapped[str] = mapped_column(String(20), default="inbox")  # inbox | sent
    from_name: Mapped[str] = mapped_column(String(120))
    from_addr: Mapped[str] = mapped_column(String(200))
    to_addrs: Mapped[list] = mapped_column(JSON, default=list)
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_by: Mapped[str] = mapped_column(String(20), default="seed")  # seed | callos
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)


class MockCalendarEvent(Base):
    __tablename__ = "mock_calendar_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    start_utc: Mapped[datetime] = mapped_column(DateTime, index=True)
    end_utc: Mapped[datetime] = mapped_column(DateTime)
    attendees: Mapped[list] = mapped_column(JSON, default=list)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by: Mapped[str] = mapped_column(String(20), default="seed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)


class MockDocument(Base):
    __tablename__ = "mock_documents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MockTask(Base):
    __tablename__ = "mock_tasks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | completed
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(String(20), default="seed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    completion_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
