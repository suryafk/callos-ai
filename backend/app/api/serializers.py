"""Plain-dict views of database rows for the inspection/admin API."""
from __future__ import annotations

from app.models import Action, AuditEvent, CallSession, User
from app.utils.timeparse import iso_utc


def session_view(s: CallSession, user: User | None = None, counts: dict | None = None) -> dict:
    return {
        "session_id": s.id, "channel": s.channel, "workflow_state": s.state, "auth_level": s.auth_level,
        "user_id": s.user_id, "user_name": user.display_name if user else None,
        "started_at": iso_utc(s.started_at), "last_activity_at": iso_utc(s.last_activity_at),
        "authenticated_at": iso_utc(s.authenticated_at), "tool_call_count": s.tool_call_count,
        "failed_auth_attempts": s.failed_auth_attempts, **(counts or {}),
    }


def action_view(a: Action) -> dict:
    return {
        "action_id": a.id, "session_id": a.session_id, "user_id": a.user_id, "type": a.type,
        "parameters": a.payload, "summary": a.summary, "version": a.version, "status": a.status,
        "requires_approval": a.requires_approval, "risk_flags": a.risk_flags or [],
        "approval_status": approval_status(a), "execution_mode": a.execution_mode,
        "result": a.result, "steps": a.steps or [], "error": a.error,
        "created_at": iso_utc(a.created_at), "updated_at": iso_utc(a.updated_at),
        "executed_at": iso_utc(a.executed_at), "expires_at": iso_utc(a.expires_at),
    }


def approval_status(a: Action) -> str:
    if a.status == "awaiting_approval":
        return "pending"
    if a.status in ("cancelled", "expired"):
        return a.status
    return "approved"


def event_view(e: AuditEvent) -> dict:
    return {
        "id": e.id, "session_id": e.session_id, "action_id": e.action_id, "user_id": e.user_id,
        "event_type": e.event_type, "tool": e.tool, "outcome": e.outcome, "detail": e.detail,
        "correlation_id": e.correlation_id, "duration_ms": e.duration_ms, "created_at": iso_utc(e.created_at),
    }
