"""Admin dashboard API (admin credential) and development-only simulator routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.actions import APPROVE_PATH
from app.api.deps import require_admin_key, require_dev_tools
from app.api.serializers import action_view, event_view, session_view
from app.config import Settings, get_settings
from app.core import orchestrator
from app.core.tool_registry import catalog
from app.database import get_db
from app.models import (
    Action, AuditEvent, CallSession, MockCalendarEvent, MockDocument, MockEmail, MockTask, User,
)
from app.schemas.voice import VoiceActionResponse
from app.utils.timeparse import fmt_time, get_zone, iso_utc, to_local

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin_key)])
dev_router = APIRouter(prefix="/api/dev", tags=["development only"],
                       dependencies=[Depends(require_dev_tools), Depends(require_admin_key)])


@router.get("/overview", summary="Dashboard counters and recent activity")
def overview(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    by_status = dict(db.execute(select(Action.status, func.count()).group_by(Action.status)).all())
    recent = [action_view(a) for a in db.scalars(select(Action).order_by(Action.updated_at.desc()).limit(8))]
    durations = [d for (d,) in db.execute(
        select(AuditEvent.duration_ms).where(AuditEvent.event_type == "tool_call",
                                             AuditEvent.duration_ms.is_not(None))
        .order_by(AuditEvent.id.desc()).limit(500))]
    durations.sort()
    latency = None
    if durations:
        latency = {"samples": len(durations), "median_ms": durations[len(durations) // 2],
                   "p95_ms": durations[min(len(durations) - 1, int(len(durations) * 0.95))],
                   "note": "Backend processing time per tool call, measured server-side. "
                           "Excludes telephony, speech and model latency."}
    return {
        "total_sessions": db.scalar(select(func.count()).select_from(CallSession)) or 0,
        "authenticated_sessions": db.scalar(select(func.count()).select_from(CallSession)
                                            .where(CallSession.auth_level == "authenticated")) or 0,
        "total_actions": sum(by_status.values()),
        "completed_actions": by_status.get("completed", 0),
        "failed_actions": sum(by_status.get(k, 0) for k in ("failed", "partially_completed", "unknown_outcome")),
        "pending_approvals": by_status.get("awaiting_approval", 0),
        "cancelled_actions": by_status.get("cancelled", 0),
        "actions_by_status": by_status,
        "tool_calls": db.scalar(select(func.count()).select_from(AuditEvent)
                                .where(AuditEvent.event_type == "tool_call")) or 0,
        "recent_actions": recent,
        "tool_latency": latency,
        "environment": settings.env, "integration_mode": settings.integration_mode,
        "dev_tools_enabled": settings.dev_tools_active, "demo_auth_enabled": settings.demo_auth_active,
    }


@router.get("/sessions", summary="List sessions, newest first")
def list_sessions(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)) -> dict[str, Any]:
    users = {u.id: u for u in db.scalars(select(User))}
    counts = dict(db.execute(select(Action.session_id, func.count()).group_by(Action.session_id)).all())
    rows = db.scalars(select(CallSession).order_by(CallSession.last_activity_at.desc()).limit(limit))
    return {"sessions": [session_view(s, users.get(s.user_id), {"action_count": counts.get(s.id, 0)})
                         for s in rows]}


@router.get("/actions", summary="List actions, newest first")
def list_actions(status: str | None = None, limit: int = Query(200, ge=1, le=500),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    stmt = select(Action).order_by(Action.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Action.status == status)
    return {"actions": [action_view(a) for a in db.scalars(stmt)]}


@router.get("/events", summary="Recent audit events across all sessions")
def list_events(limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit))
    return {"events": [event_view(e) for e in rows]}


@router.get("/tools", summary="The tool allowlist")
def list_tools() -> dict[str, Any]:
    return {"tools": catalog()}


@router.get("/workspace", summary="Mock workspace contents (simulated data, not a real account)")
def workspace(user_id: str | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    users = list(db.scalars(select(User).order_by(User.id)))
    user = next((u for u in users if u.id == user_id), users[0] if users else None)
    if user is None:
        return {"execution_mode": "mock", "users": [], "user": None, "emails": [], "events": [],
                "documents": [], "tasks": []}
    tz = get_zone(user.timezone)

    def local(dt):
        loc = to_local(dt, tz)
        return f"{loc.strftime('%a %d %b')} {fmt_time(loc)}"

    return {
        "execution_mode": "mock",
        "users": [{"user_id": u.id, "display_name": u.display_name} for u in users],
        "user": {"user_id": user.id, "display_name": user.display_name, "email": user.email,
                 "timezone": user.timezone, "scopes": user.scopes},
        "emails": [{"id": e.id, "folder": e.folder, "from": e.from_name, "from_address": e.from_addr,
                    "to": e.to_addrs, "subject": e.subject, "body": e.body, "unread": not e.is_read,
                    "received": local(e.received_at), "created_by": e.created_by}
                   for e in db.scalars(select(MockEmail).where(MockEmail.user_id == user.id)
                                       .order_by(MockEmail.received_at.desc()))],
        "events": [{"id": ev.id, "title": ev.title, "start": local(ev.start_utc), "end": local(ev.end_utc),
                    "start_utc": iso_utc(ev.start_utc), "attendees": ev.attendees, "created_by": ev.created_by}
                   for ev in db.scalars(select(MockCalendarEvent).where(MockCalendarEvent.user_id == user.id)
                                        .order_by(MockCalendarEvent.start_utc))],
        "documents": [{"id": d.id, "title": d.title, "content": d.content, "tags": d.tags,
                       "updated": local(d.updated_at)}
                      for d in db.scalars(select(MockDocument).where(MockDocument.user_id == user.id)
                                          .order_by(MockDocument.title))],
        "tasks": [{"id": t.id, "title": t.title, "notes": t.notes, "status": t.status,
                   "due_date": t.due_date.isoformat() if t.due_date else None, "created_by": t.created_by}
                  for t in db.scalars(select(MockTask).where(MockTask.user_id == user.id)
                                      .order_by(MockTask.status.desc(), MockTask.due_date))],
    }


class SimulateRequest(BaseModel):
    session_id: str = Field(min_length=6, max_length=128)
    action: str = Field(min_length=1, max_length=80)
    parameters: dict[str, Any] = Field(default_factory=dict)


@dev_router.post("/simulate", response_model=VoiceActionResponse, response_model_exclude_none=True,
                 summary="DEV ONLY: run a tool call exactly as the voice agent would")
def simulate(req: SimulateRequest, db: Session = Depends(get_db),
             settings: Settings = Depends(get_settings)) -> VoiceActionResponse:
    """Goes through the same orchestrator, allowlist, policy and approval checks as a real
    tool call. It grants no extra power: private tools still need a verified session."""
    via = APPROVE_PATH if req.action.strip().lower() == "approve_action" else None
    return orchestrator.dispatch(db, settings, session_id=req.session_id, action=req.action,
                                 params=req.parameters, channel="simulator", via_endpoint=via)


@dev_router.post("/reset", summary="DEV ONLY: wipe all data and reseed the demo workspace")
def reset(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    from app.seed.demo_data import reset_and_seed

    return {"ok": True, "seeded": reset_and_seed(db, settings)}
