"""Workflow state machine and the pending-action lifecycle.

Session states: listening -> understanding -> (needs_auth | gathering_data | planning)
-> awaiting_approval -> executing -> (completed | failed), plus cancelled.

Action invariants enforced here, on the server, regardless of what the voice
model says:

1. A write is only ever *prepared* by a tool call; it runs only through
   :func:`approve`, which needs the action id AND the exact current version.
2. Changing a pending action increments its version and invalidates every
   earlier approval, so only the latest version can execute.
3. Execution is claimed with a compare-and-swap UPDATE (status + version), so an
   action executes at most once even with concurrent or repeated approvals.
4. External writes carry an idempotency key. They are not assumed to share our
   database transaction: the claim is committed first, steps run afterwards and
   an uncertain outcome is reconciled or reported as ``unknown_outcome``.
5. Success is reported only from a verified adapter result.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from enum import Enum

from pydantic import Field, ValidationError, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.core import audit
from app.core.types import (
    ACTION_HANDLERS, ActionHandler, StepResult, ToolContext, ToolError, ToolParams, ToolResult,
)
from app.integrations.base import IntegrationError, IntegrationTimeout
from app.models import Action, Approval
from app.services.common import as_list
from app.utils.logging import get_logger
from app.utils.timeparse import iso_utc

log = get_logger("callos.workflow")


class WorkflowState(str, Enum):
    LISTENING = "listening"
    UNDERSTANDING = "understanding"
    NEEDS_AUTH = "needs_auth"
    GATHERING_DATA = "gathering_data"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


S = WorkflowState
# Every state may move to UNDERSTANDING: a new request can always arrive.
TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    S.LISTENING: {S.UNDERSTANDING},
    S.UNDERSTANDING: {S.NEEDS_AUTH, S.GATHERING_DATA, S.PLANNING, S.EXECUTING, S.CANCELLED,
                      S.LISTENING, S.AWAITING_APPROVAL, S.FAILED},
    S.NEEDS_AUTH: {S.UNDERSTANDING},
    S.GATHERING_DATA: {S.LISTENING, S.AWAITING_APPROVAL, S.FAILED, S.UNDERSTANDING},
    S.PLANNING: {S.AWAITING_APPROVAL, S.LISTENING, S.FAILED, S.UNDERSTANDING},
    S.AWAITING_APPROVAL: {S.UNDERSTANDING},
    S.EXECUTING: {S.COMPLETED, S.FAILED, S.UNDERSTANDING},
    S.COMPLETED: {S.UNDERSTANDING},
    S.FAILED: {S.UNDERSTANDING},
    S.CANCELLED: {S.UNDERSTANDING, S.AWAITING_APPROVAL},
}

ACTION_PENDING = "awaiting_approval"
ACTION_TERMINAL = {"completed", "partially_completed", "failed", "cancelled", "expired"}


class InvalidTransition(RuntimeError):
    pass


def transition(ctx: ToolContext, new_state: WorkflowState, reason: str = "") -> None:
    current = WorkflowState(ctx.session.state)
    if current == new_state:
        return
    if new_state not in TRANSITIONS[current]:
        raise InvalidTransition(f"{current.value} -> {new_state.value} is not allowed")
    ctx.session.state = new_state.value
    audit.record(ctx.db, event_type="state_changed", session_id=ctx.session.id,
                 user_id=ctx.session.user_id, detail={"from": current.value, "to": new_state.value, "reason": reason})


# ------------------------------------------------------------------ parameter models

class UpdatePendingParams(ToolParams):
    action_id: str | None = Field(None, max_length=40)
    title: str | None = Field(None, max_length=200)
    date: str | None = None
    time: str | None = None
    duration_minutes: int | None = Field(None, ge=5, le=480)
    attendees: list[str] | None = None
    timezone: str | None = None
    to: list[str] | None = None
    subject: str | None = Field(None, max_length=200)
    body: str | None = Field(None, max_length=4000)
    due_date: str | None = None
    notes: str | None = Field(None, max_length=1000)

    @field_validator("attendees", "to", mode="before")
    @classmethod
    def _lists(cls, v):
        return None if v is None else as_list(v)


class ApproveParams(ToolParams):
    action_id: str = Field(min_length=1, max_length=40)
    version: int = Field(ge=1)


class CancelParams(ToolParams):
    action_id: str | None = Field(None, max_length=40)
    reason: str | None = Field(None, max_length=200)


class NoParams(ToolParams):
    pass


# ------------------------------------------------------------------ helpers

def pending_actions(ctx: ToolContext) -> list[Action]:
    return list(ctx.db.scalars(
        select(Action).where(Action.session_id == ctx.session.id, Action.status == ACTION_PENDING)
        .order_by(Action.created_at)))


def expire_overdue(ctx: ToolContext) -> None:
    for action in pending_actions(ctx):
        if action.expires_at <= ctx.now:
            action.status, action.updated_at = "expired", ctx.now
            audit.record(ctx.db, event_type="action_expired", session_id=ctx.session.id,
                         action_id=action.id, user_id=action.user_id, outcome="expired")


def settle_state(ctx: ToolContext) -> None:
    """Return to awaiting_approval if something is still pending, else listening."""
    transition(ctx, S.AWAITING_APPROVAL if pending_actions(ctx) else S.LISTENING, "request handled")


def _load_owned(ctx: ToolContext, action_id: str) -> Action:
    """Load an action only if it belongs to this session AND this user.

    Any mismatch looks identical to "does not exist" so nothing leaks across
    sessions or users.
    """
    action = ctx.db.get(Action, action_id)
    if action is None or action.session_id != ctx.session.id or ctx.user is None or action.user_id != ctx.user.id:
        raise ToolError("not_found", "I could not find that pending request on this call.")
    return action


def _resolve_pending(ctx: ToolContext, action_id: str | None) -> Action:
    if action_id:
        action = _load_owned(ctx, action_id)
        if action.status != ACTION_PENDING:
            raise ToolError(f"action_{action.status}",
                            f"That request is {action.status.replace('_', ' ')} and can no longer be changed.")
        return action
    pending = [a for a in pending_actions(ctx) if ctx.user and a.user_id == ctx.user.id]
    if not pending:
        raise ToolError("not_found", "There is no pending request on this call.")
    if len(pending) > 1:
        raise ToolError("needs_clarification", "There is more than one pending request. Which one do you mean?",
                        {"pending": [action_view(a) for a in pending]})
    return pending[0]


def _require_scope(ctx: ToolContext, handler: ActionHandler) -> None:
    if handler.scope not in (ctx.user.scopes or []):
        raise ToolError("forbidden", f"Your account does not have permission for this {handler.label} action.")


def action_view(a: Action) -> dict:
    return {"action_id": a.id, "type": a.type, "version": a.version, "status": a.status,
            "summary": a.summary, "expires_at": iso_utc(a.expires_at)}


def _approval_prompt(action: Action) -> str:
    return f"{action.summary} Shall I go ahead?"


# ------------------------------------------------------------------ prepare / update / cancel

def create_pending(ctx: ToolContext, action_type: str, inputs: dict) -> ToolResult:
    handler = ACTION_HANDLERS[action_type]
    _require_scope(ctx, handler)
    built = _build(ctx, handler, inputs, on_reject="I have not prepared anything.")
    action = Action(
        id=f"act-{uuid.uuid4().hex[:10]}", session_id=ctx.session.id, user_id=ctx.user.id, type=action_type,
        payload=built.payload, summary=built.summary, risk_flags=built.risk_flags, version=1,
        status=ACTION_PENDING, requires_approval=True,
        expires_at=ctx.now + timedelta(minutes=ctx.settings.action_ttl_minutes),
        execution_mode=ctx.adapters.calendar.execution_mode, created_at=ctx.now, updated_at=ctx.now,
    )
    ctx.db.add(action)
    ctx.db.flush()
    audit.record(ctx.db, event_type="action_prepared", session_id=ctx.session.id, action_id=action.id,
                 user_id=ctx.user.id, outcome=ACTION_PENDING,
                 detail={"type": action_type, "version": 1, "payload": built.payload, "risk_flags": built.risk_flags})
    return ToolResult(status=ACTION_PENDING, speech=_approval_prompt(action), action=action,
                      data={"details": built.payload, "risk_flags": built.risk_flags})


def _build(ctx: ToolContext, handler: ActionHandler, inputs: dict, *, on_reject: str):
    """Validate inputs and build the payload. ``on_reject`` says what a refusal means for the caller."""
    try:
        return handler.build(ctx, inputs)
    except ValidationError as exc:
        raise ToolError("invalid_request", describe_validation_error(exc))
    except ToolError as err:
        err.speech = err.speech.replace("{effect}", on_reject)
        raise


def describe_validation_error(exc: ValidationError) -> str:
    missing = [str(e["loc"][0]) for e in exc.errors() if e["type"] == "missing" and e["loc"]]
    invalid = [f"{e['loc'][0] if e['loc'] else 'value'} ({e['msg']})" for e in exc.errors() if e["type"] != "missing"]
    parts = []
    if missing:
        parts.append("I still need: " + ", ".join(m.replace("_", " ") for m in missing) + ".")
    if invalid:
        parts.append("These values are not valid: " + "; ".join(invalid) + ".")
    return " ".join(parts) or "The request was not valid."


def update_pending(ctx: ToolContext, p: UpdatePendingParams) -> ToolResult:
    action = _resolve_pending(ctx, p.action_id)
    handler = ACTION_HANDLERS[action.type]
    _require_scope(ctx, handler)
    changes = {k: v for k, v in p.model_dump(exclude_none=True).items()
               if k != "action_id" and k in handler.editable_fields}
    if not changes:
        allowed = ", ".join(handler.editable_fields) or "nothing"
        raise ToolError("invalid_request",
                        f"Nothing to change. For this {handler.label} you can change: {allowed}.")
    inputs = {k: action.payload[k] for k in handler.editable_fields if action.payload.get(k) is not None}
    inputs.update(changes)
    # A failed rebuild (for example a time conflict) leaves the pending action untouched.
    built = _build(ctx, handler, inputs, on_reject="I left your pending request as it was.")
    if built.payload == action.payload:
        return ToolResult(status=ACTION_PENDING, action=action, data={"details": action.payload, "changed": False},
                          speech="That is already what I have. " + _approval_prompt(action))

    old_version = action.version
    changed = sorted(k for k in built.payload if built.payload.get(k) != action.payload.get(k))
    action.payload, action.summary, action.risk_flags = built.payload, built.summary, built.risk_flags
    action.version = old_version + 1
    action.updated_at = ctx.now
    action.expires_at = ctx.now + timedelta(minutes=ctx.settings.action_ttl_minutes)
    # Any approval given for an earlier version is void.
    ctx.db.execute(update(Approval)
                   .where(Approval.action_id == action.id, Approval.action_version < action.version,
                          Approval.invalidated_at.is_(None))
                   .values(invalidated_at=ctx.now))
    audit.record(ctx.db, event_type="action_updated", session_id=ctx.session.id, action_id=action.id,
                 user_id=ctx.user.id, outcome=ACTION_PENDING,
                 detail={"from_version": old_version, "to_version": action.version,
                         "changed_fields": changed, "payload": built.payload})
    return ToolResult(status=ACTION_PENDING, action=action,
                      data={"details": built.payload, "changed": True, "previous_version": old_version,
                            "risk_flags": built.risk_flags},
                      speech="Updated. " + _approval_prompt(action))


def cancel(ctx: ToolContext, p: CancelParams) -> ToolResult:
    if p.action_id:
        action = _load_owned(ctx, p.action_id)
        if action.status == "cancelled":
            return ToolResult(status="cancelled", action=action, speech="That request was already cancelled.")
        if action.status != ACTION_PENDING:
            raise ToolError(f"action_{action.status}",
                            f"That request is already {action.status.replace('_', ' ')}, so I cannot cancel it.")
    else:
        action = _resolve_pending(ctx, None)
    # Compare-and-swap so a cancel can never race with an approval that already claimed execution.
    won = ctx.db.execute(update(Action).where(Action.id == action.id, Action.status == ACTION_PENDING)
                         .values(status="cancelled", updated_at=ctx.now)).rowcount
    if won != 1:
        ctx.db.refresh(action)
        raise ToolError(f"action_{action.status}", "That request has already been processed, so I cannot cancel it.")
    ctx.db.execute(update(Approval).where(Approval.action_id == action.id, Approval.consumed_at.is_(None),
                                          Approval.invalidated_at.is_(None)).values(invalidated_at=ctx.now))
    ctx.db.refresh(action)
    audit.record(ctx.db, event_type="action_cancelled", session_id=ctx.session.id, action_id=action.id,
                 user_id=ctx.user.id, outcome="cancelled", detail={"version": action.version, "reason": p.reason})
    return ToolResult(status="cancelled", action=action, speech="Cancelled. Nothing was changed.",
                      data={"details": action.payload})


def get_pending(ctx: ToolContext, _p: NoParams) -> ToolResult:
    pending = [a for a in pending_actions(ctx) if ctx.user and a.user_id == ctx.user.id]
    if not pending:
        return ToolResult(speech="There is nothing waiting for your approval.", data={"pending": []})
    speech = "Waiting for your approval: " + " ".join(a.summary for a in pending)
    return ToolResult(speech=speech, data={"pending": [action_view(a) for a in pending]},
                      action=pending[0] if len(pending) == 1 else None, status=ACTION_PENDING)


# ------------------------------------------------------------------ approve + execute

def approve(ctx: ToolContext, p: ApproveParams) -> ToolResult:
    action = _load_owned(ctx, p.action_id)
    handler = ACTION_HANDLERS[action.type]
    _require_scope(ctx, handler)

    if action.status in ("completed", "partially_completed"):
        return _replay(action)
    if action.status == "executing":
        raise ToolError("in_progress", "That request is already being carried out. Please wait a moment.")
    if action.status in ("cancelled", "expired", "failed"):
        raise ToolError(f"action_{action.status}",
                        f"That request is {action.status}, so I cannot run it. Nothing was changed. "
                        "I can prepare it again if you like.")
    if action.status == ACTION_PENDING and action.expires_at <= ctx.now:
        action.status, action.updated_at = "expired", ctx.now
        audit.record(ctx.db, event_type="action_expired", session_id=ctx.session.id, action_id=action.id,
                     user_id=action.user_id, outcome="expired")
        raise ToolError("action_expired", "That request has expired. Nothing was changed. "
                                          "I can prepare it again if you like.")
    if p.version != action.version:
        audit.record(ctx.db, event_type="approval_rejected", session_id=ctx.session.id, action_id=action.id,
                     user_id=ctx.user.id, outcome="stale_version",
                     detail={"approved_version": p.version, "current_version": action.version})
        raise ToolError("stale_version",
                        "That request was changed after it was read out, so I did not run it. "
                        f"The current request is: {action.summary} Please ask the caller to confirm this version.",
                        {"action_id": action.id, "version": action.version, "summary": action.summary})

    key = f"{action.id}:v{action.version}"
    try:
        approval = ctx.db.scalar(select(Approval).where(
            Approval.action_id == action.id, Approval.action_version == action.version))
        if approval is None:
            approval = Approval(action_id=action.id, action_version=action.version, user_id=ctx.user.id,
                                session_id=ctx.session.id, method="voice", approved_at=ctx.now)
            ctx.db.add(approval)
            ctx.db.flush()
        # Claim execution: exactly one request can move this version to "executing".
        claimed = ctx.db.execute(
            update(Action)
            .where(Action.id == action.id, Action.version == p.version,
                   Action.status.in_([ACTION_PENDING, "unknown_outcome"]))
            .values(status="executing", idempotency_key=key, updated_at=ctx.now)).rowcount
        audit.record(ctx.db, event_type="action_approved", session_id=ctx.session.id, action_id=action.id,
                     user_id=ctx.user.id, outcome="approved" if claimed == 1 else "not_claimed",
                     detail={"version": p.version, "idempotency_key": key})
        if claimed == 1:
            transition(ctx, S.EXECUTING, "approved")
        ctx.db.commit()
    except IntegrityError:
        ctx.db.rollback()
        claimed = 0
    ctx.db.refresh(action)
    if claimed != 1:
        if action.status in ("completed", "partially_completed"):
            return _replay(action)
        raise ToolError("in_progress", "That request is already being carried out. Please wait a moment.")
    return _execute(ctx, action, handler, approval)


def _replay(action: Action) -> ToolResult:
    """A repeated approval returns the stored outcome; nothing runs twice."""
    result = action.result or {}
    return ToolResult(status=action.status, ok=action.status == "completed", action=action,
                      speech="That was already done, so I did not repeat it. " + result.get("speech", ""),
                      data={**result, "already_executed": True})


def _run_step(ctx: ToolContext, action: Action, step, key: str, details: dict) -> StepResult:
    try:
        return step.run(ctx, action, key, details)
    except IntegrationTimeout as exc:
        uncertain = f"the {step.name.replace('_', ' ')} request timed out ({exc})"
    except IntegrationError as exc:
        ctx.db.rollback()
        return StepResult(False, "failed", message=f"the service is unavailable ({exc})")
    except Exception:  # noqa: BLE001 - never let a step crash leave the action stuck in "executing"
        log.exception("step crashed", extra={"action_id": action.id, "step": step.name})
        uncertain = f"the {step.name.replace('_', ' ')} step failed unexpectedly"
    ctx.db.rollback()
    # Outcome uncertain: look for the effect by idempotency key before deciding.
    if step.reconcile is not None:
        try:
            found = step.reconcile(ctx, action, key)
            if found is not None:
                found.detail["reconciled"] = True
                return found
            return StepResult(False, "failed", message=uncertain + "; I checked and nothing was created")
        except Exception:  # noqa: BLE001
            ctx.db.rollback()
            log.exception("reconciliation failed", extra={"action_id": action.id, "step": step.name})
    return StepResult(False, "unknown_outcome", message=uncertain)


def _execute(ctx: ToolContext, action: Action, handler: ActionHandler, approval: Approval) -> ToolResult:
    steps_log: list[dict] = []
    details: dict = {}
    outcome, error = "completed", None
    for step in handler.steps:
        if not step.applies(action.payload):
            continue
        key = f"{action.idempotency_key}:{step.name}"
        res = _run_step(ctx, action, step, key, details)
        steps_log.append({"step": step.name, "status": res.status, "idempotency_key": key,
                          "detail": res.detail, "message": res.message})
        if res.ok:
            details[step.name] = res.detail
            continue
        error = res.message
        if res.status == "unknown_outcome":
            outcome = "unknown_outcome"
        else:
            outcome = "partially_completed" if details else "failed"
        break

    done = [s["step"].replace("_", " ") for s in steps_log if s["status"] == "success"]
    if outcome == "completed":
        speech = handler.success_speech(action, details)
    elif outcome == "partially_completed":
        speech = (f"This only partly worked. Completed: {', '.join(done)}. "
                  f"But {error}. I have not retried anything.")
    elif outcome == "unknown_outcome":
        speech = (f"I could not confirm whether this went through: {error}. I am not reporting it as done. "
                  "You can ask me to try again, and I will check first so nothing is duplicated.")
    else:
        speech = f"I could not complete that: {error}. Nothing was changed."

    action = ctx.db.get(Action, action.id)
    action.status, action.steps, action.error = outcome, steps_log, error
    action.result = {"speech": speech, "outcome": outcome, "steps": details,
                     "verified": outcome == "completed" and all(d.get("verified") for d in details.values())}
    action.updated_at = ctx.now
    if outcome != "unknown_outcome":
        action.executed_at = ctx.now
        approval = ctx.db.get(Approval, approval.id)
        approval.consumed_at = ctx.now
    audit.record(ctx.db, event_type="action_executed", session_id=ctx.session.id, action_id=action.id,
                 user_id=action.user_id, outcome=outcome,
                 detail={"version": action.version, "steps": steps_log, "execution_mode": action.execution_mode})
    transition(ctx, S.COMPLETED if outcome == "completed" else S.FAILED, f"execution {outcome}")
    ctx.db.commit()
    return ToolResult(status=outcome, ok=outcome == "completed", speech=speech, action=action,
                      data={"outcome": outcome, "steps": details, "verified": action.result["verified"],
                            "details": action.payload})
