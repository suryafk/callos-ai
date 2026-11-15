"""Single entry point for every tool call: session -> allowlist -> policy -> validate -> run -> audit."""
from __future__ import annotations

import re
import time
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import Settings
from app.core import audit, policy_engine, workflow_engine as wf
from app.core.tool_registry import REGISTRY, ToolSpec, get_tool
from app.core.types import ToolContext, ToolError, ToolResult
from app.database import utcnow
from app.integrations import get_adapters
from app.models import CallSession, User
from app.schemas.voice import VoiceActionResponse
from app.utils.logging import correlation_id_var, get_logger
from app.utils.security import redact
from app.utils.timeparse import iso_utc

log = get_logger("callos.orchestrator")

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{5,127}$")
# Values Bolna may leave behind when an optional argument was not collected.
_PLACEHOLDER_RE = re.compile(r"^(%\([^)]*\)[sif]|\{\{?[^{}]*\}?\}|null|none|undefined)$", re.IGNORECASE)
S = wf.WorkflowState


def clean_params(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Drop empty values and unsubstituted template placeholders."""
    cleaned: dict[str, Any] = {}
    for key, value in (raw or {}).items():
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value or _PLACEHOLDER_RE.match(value):
                continue
        cleaned[str(key)] = value
    return cleaned


def _response(*, ok: bool, status: str, action: str | None, speech: str, data: Any = None,
              session: CallSession | None = None, result: ToolResult | None = None) -> VoiceActionResponse:
    resp = VoiceActionResponse(
        ok=ok, status=status, action=action, speech=speech, data=data,
        session_id=session.id if session else None,
        auth_level=session.auth_level if session else None,
        workflow_state=session.state if session else None,
        correlation_id=correlation_id_var.get(),
    )
    if result is not None and result.action is not None:
        a = result.action
        resp.action_id, resp.version, resp.summary = a.id, a.version, a.summary
        resp.requires_approval = a.status == wf.ACTION_PENDING
        resp.expires_at = iso_utc(a.expires_at) if a.status == wf.ACTION_PENDING else None
        resp.execution_mode = a.execution_mode
    return resp


def _get_or_create_session(db: Session, session_id: str, channel: str, now) -> CallSession:
    session = db.get(CallSession, session_id)
    if session is None:
        session = CallSession(id=session_id, channel=channel, state=S.LISTENING.value, context={},
                              auth_level="anonymous", tool_call_count=0, failed_auth_attempts=0,
                              started_at=now, last_activity_at=now)
        db.add(session)
        audit.record(db, event_type="session_started", session_id=session_id, detail={"channel": channel})
    return session


def dispatch(db: Session, settings: Settings, *, session_id: str | None, action: str | None,
             params: dict[str, Any] | None, channel: str = "tool_api",
             via_endpoint: str | None = None) -> VoiceActionResponse:
    started = time.perf_counter()
    now = utcnow()
    params = clean_params(params)
    action_name = (action or "").strip().lower()[:60]

    sid = (session_id or "").strip()
    if not sid or _PLACEHOLDER_RE.match(sid):
        sid = settings.fallback_session_id
    if not SESSION_ID_RE.match(sid):
        log.warning("tool call without a usable session id", extra={"tool": action_name})
        return _response(ok=False, status="invalid_request", action=action_name or None,
                         speech="Sorry, I hit a technical problem identifying this call, so I cannot do that right now.",
                         data={"error": "session_id (call_sid) is missing or malformed"})

    session = _get_or_create_session(db, sid, channel, now)
    session.tool_call_count += 1
    session.last_activity_at = now
    user = db.get(User, session.user_id) if session.user_id else None
    if session.auth_level == "authenticated" and not policy_engine.auth_is_current(session, settings, now):
        session.auth_level = "anonymous"
        audit.record(db, event_type="auth_expired", session_id=sid, user_id=session.user_id)
    if session.auth_level != "authenticated":
        user = None
    db.commit()  # the session exists from here on, whatever happens to this request

    ctx = ToolContext(db=db, session=session, user=user, adapters=get_adapters(db, settings.integration_mode),
                      settings=settings, now=now, correlation_id=correlation_id_var.get())
    spec: ToolSpec | None = get_tool(action_name)
    result: ToolResult | None = None
    try:
        wf.transition(ctx, S.UNDERSTANDING, f"tool request: {action_name or 'none'}")
        wf.expire_overdue(ctx)
        resp = _run(ctx, spec, action_name, params, via_endpoint)
        result = resp[1]
        response = resp[0]
        db.commit()
    except Exception:  # noqa: BLE001 - last line of defence: never leak a stack trace to the caller
        log.exception("tool call crashed", extra={"tool": action_name, "session_id": sid})
        db.rollback()
        session = db.get(CallSession, sid)
        ctx.session = session
        if session.state != S.UNDERSTANDING.value:
            wf.transition(ctx, S.UNDERSTANDING, "error recovery")
        wf.transition(ctx, S.FAILED, "internal error")
        response = _response(ok=False, status="failed", action=action_name or None, session=session,
                             speech="Sorry, something went wrong on my side. Nothing was changed. Please try again.")
        db.commit()

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    audit.record(db, event_type="tool_call", session_id=sid, user_id=session.user_id, tool=action_name or None,
                 outcome=response.status, action_id=response.action_id, duration_ms=duration_ms,
                 detail={"parameters": params, "ok": response.ok, "channel": channel})
    db.commit()
    response.workflow_state, response.auth_level = session.state, session.auth_level
    log.info("tool_call", extra={"tool": action_name, "session_id": sid, "status": response.status,
                                 "ok": response.ok, "duration_ms": duration_ms, "channel": channel,
                                 "action_id": response.action_id, "parameters": redact(params)})
    return response


def _run(ctx: ToolContext, spec: ToolSpec | None, action_name: str, params: dict,
         via_endpoint: str | None) -> tuple[VoiceActionResponse, ToolResult | None]:
    session = ctx.session

    def fail(status: str, speech: str, data: Any = None, state: wf.WorkflowState | None = None):
        if status == "in_progress":
            # Another request owns the execution (and the session state) right now: do not touch it.
            ctx.db.refresh(session)
        elif state is not None:
            wf.transition(ctx, state, status)
        else:
            wf.settle_state(ctx)
        return _response(ok=False, status=status, action=action_name or None, speech=speech, data=data,
                         session=session), None

    # 1. Allowlist
    if spec is None:
        audit.record(ctx.db, event_type="tool_rejected", session_id=session.id, tool=action_name or None,
                     outcome="unsupported_action")
        return fail("unsupported_action", "I am not able to do that. That capability is not available.",
                    {"supported_actions": sorted(n for n, t in REGISTRY.items() if not t.dedicated_endpoint)})
    if spec.dedicated_endpoint and via_endpoint != spec.dedicated_endpoint:
        audit.record(ctx.db, event_type="tool_rejected", session_id=session.id, tool=spec.name,
                     outcome="wrong_endpoint")
        return fail("unsupported_action", "That step must go through the approval endpoint.",
                    {"use_endpoint": spec.dedicated_endpoint})

    # 2. Authorization
    try:
        policy_engine.check_tool_access(session, ctx.user, scope=spec.scope, requires_auth=spec.requires_auth,
                                        settings=ctx.settings, now=ctx.now)
    except policy_engine.PolicyDenied as denied:
        audit.record(ctx.db, event_type="access_denied", session_id=session.id, user_id=session.user_id,
                     tool=spec.name, outcome=denied.status, detail={"scope": spec.scope})
        return fail(denied.status, denied.speech,
                    state=S.NEEDS_AUTH if denied.status == "auth_required" else None)

    # 3. Input validation
    try:
        parsed = spec.params.model_validate(params)
    except ValidationError as exc:
        return fail("invalid_request", wf.describe_validation_error(exc),
                    {"errors": [{"field": ".".join(map(str, e["loc"])), "problem": e["msg"]} for e in exc.errors()]})

    # 4. Execute
    if spec.kind == "read":
        wf.transition(ctx, S.GATHERING_DATA, spec.name)
    elif spec.kind == "prepare" or spec.name == "update_pending_action":
        wf.transition(ctx, S.PLANNING, spec.name)
    try:
        result = spec.handler(ctx, parsed)
    except ToolError as err:
        return fail(err.status, err.speech, err.data)

    # 5. Settle the workflow state
    if spec.name == "approve_action":
        if session.state == S.UNDERSTANDING.value:  # replay of an already executed action
            wf.settle_state(ctx)
    elif spec.name == "cancel_action":
        wf.transition(ctx, S.CANCELLED, "cancelled by caller")
        if wf.pending_actions(ctx):
            wf.transition(ctx, S.AWAITING_APPROVAL, "other requests still pending")
    elif result.status == wf.ACTION_PENDING and spec.kind != "read":
        wf.transition(ctx, S.AWAITING_APPROVAL, "waiting for approval")
    else:
        wf.settle_state(ctx)
    return _response(ok=result.ok, status=result.status, action=spec.name, speech=result.speech,
                     data=result.data, session=session, result=result), result
