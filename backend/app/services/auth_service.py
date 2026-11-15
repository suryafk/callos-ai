"""DEMO-ONLY caller verification with a spoken access code.

NOT PRODUCTION AUTHENTICATION. A spoken code passes through speech recognition,
the voice model and (depending on provider settings) call transcripts. It exists
so the Act-with-AI flow can be demonstrated without a real account-linking and
verification channel. It is disabled when CALLOS_ENV=production.

What it does enforce, server-side:
* the user id is derived from the matching stored hash — never from the caller,
  the phone number or anything the voice model sends;
* codes are stored as salted PBKDF2 hashes and never logged or audited;
* attempts are limited per session and globally.
"""
from __future__ import annotations

from datetime import timedelta

from pydantic import Field
from sqlalchemy import func, select

from app.core import audit
from app.core.types import ToolContext, ToolError, ToolParams, ToolResult
from app.models import AuditEvent, User
from app.utils.security import normalise_code, verify_pin


class VerifyIdentityParams(ToolParams):
    access_code: str = Field(min_length=1, max_length=64)


def verify_identity(ctx: ToolContext, p: VerifyIdentityParams) -> ToolResult:
    s, settings = ctx.session, ctx.settings
    if not settings.demo_auth_active:
        raise ToolError("unavailable", "Account verification by phone is not available on this system, "
                                       "so I cannot access private information.")
    if s.auth_level == "authenticated" and ctx.user is not None:
        return ToolResult(speech=f"You are already verified as {ctx.user.display_name}.",
                          data={"verified": True, "display_name": ctx.user.display_name})
    if s.failed_auth_attempts >= settings.max_pin_attempts:
        raise ToolError("locked", "Too many incorrect codes on this call. For your security I cannot "
                                  "verify you again on this call.")
    recent_failures = ctx.db.scalar(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.event_type == "auth_failed",
            AuditEvent.created_at >= ctx.now - timedelta(minutes=15))) or 0
    if recent_failures >= settings.global_pin_failure_limit:
        raise ToolError("locked", "Verification is temporarily unavailable. Please try again later.")

    code = normalise_code(p.access_code)
    matched: User | None = None
    if 4 <= len(code) <= 12:
        # Check every enrolled user so timing does not reveal which code matched.
        for user in ctx.db.scalars(select(User).where(User.pin_hash.is_not(None), User.status == "active")):
            if verify_pin(code, user.pin_salt, user.pin_hash):
                matched = user
    if matched is None:
        s.failed_auth_attempts += 1
        remaining = settings.max_pin_attempts - s.failed_auth_attempts
        audit.record(ctx.db, event_type="auth_failed", session_id=s.id, outcome="denied",
                     detail={"attempt": s.failed_auth_attempts})
        if remaining <= 0:
            raise ToolError("locked", "That code is not correct, and there are no attempts left on this call.")
        raise ToolError("auth_failed", f"That code is not correct. You have {remaining} "
                                       f"attempt{'s' if remaining != 1 else ''} left.")

    s.user_id, s.auth_level, s.authenticated_at, s.failed_auth_attempts = matched.id, "authenticated", ctx.now, 0
    ctx.user = matched
    audit.record(ctx.db, event_type="auth_succeeded", session_id=s.id, user_id=matched.id, outcome="success",
                 detail={"method": "demo_access_code"})
    return ToolResult(speech=f"Thank you. You are verified as {matched.display_name}.",
                      data={"verified": True, "display_name": matched.display_name, "auth_method": "demo_access_code"})
