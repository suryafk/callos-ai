from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    status: Mapped[str] = mapped_column(String(20), default="active")
    # Permission scopes granted to this user, e.g. ["calendar.read", "calendar.write"].
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    # Spoken aliases -> email address, e.g. {"manager": "neha.kapoor@example.test"}.
    aliases: Mapped[dict] = mapped_column(JSON, default=dict)
    # Demo access code, stored only as a salted PBKDF2 hash.
    pin_salt: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pin_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
