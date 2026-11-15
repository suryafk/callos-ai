"""Session inspection (protected: tool credential or admin credential)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_tool_or_admin_key
from app.api.serializers import action_view, event_view, session_view
from app.database import get_db
from app.models import Action, AuditEvent, CallSession, User
from app.schemas.voice import ErrorResponse

router = APIRouter(prefix="/api/sessions", tags=["sessions"], dependencies=[Depends(require_tool_or_admin_key)],
                   responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})


class SessionDetail(BaseModel):
    session: dict[str, Any]
    pending_actions: list[dict[str, Any]]
    actions: list[dict[str, Any]]


class SessionEvents(BaseModel):
    session_id: str
    count: int
    events: list[dict[str, Any]]


def _session_or_404(db: Session, session_id: str) -> CallSession:
    session = db.get(CallSession, session_id)
    if session is None:
        raise HTTPException(404, "Session not found")
    return session


@router.get("/{session_id}", response_model=SessionDetail, summary="Session status and its actions")
def get_session(session_id: str, db: Session = Depends(get_db)) -> SessionDetail:
    s = _session_or_404(db, session_id)
    user = db.get(User, s.user_id) if s.user_id else None
    actions = [action_view(a) for a in db.scalars(
        select(Action).where(Action.session_id == s.id).order_by(Action.created_at.desc()))]
    return SessionDetail(session=session_view(s, user),
                         pending_actions=[a for a in actions if a["status"] == "awaiting_approval"],
                         actions=actions)


@router.get("/{session_id}/events", response_model=SessionEvents, summary="Audit trail for a session")
def get_session_events(session_id: str, limit: int = Query(200, ge=1, le=1000),
                       db: Session = Depends(get_db)) -> SessionEvents:
    s = _session_or_404(db, session_id)
    events = [event_view(e) for e in db.scalars(
        select(AuditEvent).where(AuditEvent.session_id == s.id).order_by(AuditEvent.id).limit(limit))]
    return SessionEvents(session_id=s.id, count=len(events), events=events)
