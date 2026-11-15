"""Append-only audit trail helper."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AuditEvent
from app.utils.logging import correlation_id_var
from app.utils.security import redact


def record(db: Session, *, event_type: str, session_id: str | None = None, action_id: str | None = None,
           user_id: str | None = None, tool: str | None = None, outcome: str | None = None,
           detail: dict | None = None, duration_ms: float | None = None) -> AuditEvent:
    event = AuditEvent(
        session_id=session_id, action_id=action_id, user_id=user_id, event_type=event_type,
        tool=tool, outcome=outcome, detail=redact(detail or {}),
        correlation_id=correlation_id_var.get(), duration_ms=duration_ms,
    )
    db.add(event)
    return event
