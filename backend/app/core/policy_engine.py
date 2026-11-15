"""Authorization policy, enforced on the server for every tool call.

The voice model only *requests* tools. This module decides, from trusted state
(the session's verified user and that user's scopes), whether the request runs.
Nothing the caller or the model sends can supply an identity.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.config import Settings
from app.models import CallSession, User


class PolicyDenied(Exception):
    def __init__(self, status: str, speech: str) -> None:
        super().__init__(speech)
        self.status = status
        self.speech = speech


def auth_is_current(session: CallSession, settings: Settings, now: datetime) -> bool:
    return (
        session.auth_level == "authenticated"
        and session.user_id is not None
        and session.authenticated_at is not None
        and now - session.authenticated_at <= timedelta(minutes=settings.auth_ttl_minutes)
    )


def check_tool_access(session: CallSession, user: User | None, *, scope: str | None,
                      requires_auth: bool, settings: Settings, now: datetime) -> None:
    """Raise PolicyDenied unless this session may run a tool needing ``scope``."""
    if not requires_auth:
        return  # anonymous tool (e.g. verify_identity)
    if not auth_is_current(session, settings, now) or user is None:
        if settings.demo_auth_active:
            raise PolicyDenied("auth_required",
                               "I need to verify who you are before I can access private information. "
                               "Please tell me your CallOS access code.")
        raise PolicyDenied("auth_required",
                           "I cannot access private information because this call is not linked to a "
                           "verified account, and phone verification is not available on this system.")
    if user.status != "active":
        raise PolicyDenied("forbidden", "This account is not active, so I cannot access it.")
    if scope and scope not in (user.scopes or []):
        area = scope.split(".")[0]
        verb = "change" if scope.endswith((".write", ".send")) else "read"
        raise PolicyDenied("forbidden", f"Your account does not have permission to {verb} {area} data here.")
