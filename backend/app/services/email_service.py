"""Email tools: search, read, and prepare/send (send only after explicit approval)."""
from __future__ import annotations

import re
from typing import Any

from pydantic import Field, field_validator

from app.core.types import (
    Action, ActionHandler, BuiltAction, Step, StepResult, ToolContext, ToolError, ToolParams, ToolResult,
    register_action_handler,
)
from app.services.common import (
    as_list, join_words, note_untrusted_addresses, require_ok, resolve_addresses, untrusted,
    untrusted_recipients, untrusted_warning,
)
from app.utils.timeparse import fmt_date, fmt_time, to_local

BODY_LIMIT = 1500


class SearchEmailsParams(ToolParams):
    query: str | None = Field(None, max_length=200)
    sender: str | None = Field(None, max_length=120)
    unread_only: bool = False
    limit: int = Field(5, ge=1, le=10)


class ReadEmailParams(ToolParams):
    email_id: str = Field(min_length=1, max_length=40)


class EmailDraftParams(ToolParams):
    to: list[str] = Field(min_length=1, max_length=10)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)

    @field_validator("to", mode="before")
    @classmethod
    def _to(cls, v: Any) -> list[str]:
        return as_list(v)


def _when(ctx: ToolContext, dt_utc) -> str:
    local = to_local(dt_utc, ctx.tz)
    return f"{fmt_date(local.date(), ctx.today)} at {fmt_time(local)}"


def _resolve_sender(ctx: ToolContext, sender: str | None) -> str | None:
    """'my manager' -> the manager's address, using only the user's own aliases."""
    if not sender:
        return None
    key = re.sub(r"^(my|the)\s+", "", sender.lower().strip())
    return (ctx.user.aliases or {}).get(key, sender)


def search_emails(ctx: ToolContext, p: SearchEmailsParams) -> ToolResult:
    res = ctx.adapters.email.search(ctx.user.id, query=p.query, sender=_resolve_sender(ctx, p.sender),
                                    unread_only=p.unread_only, limit=p.limit)
    rows = require_ok(res, "mailbox")
    total = res.meta.get("total", len(rows))
    items = [{
        "email_id": e.id, "from": e.from_name, "from_address": e.from_addr, "subject": e.subject,
        "received": _when(ctx, e.received_at), "unread": not e.is_read,
        "preview": untrusted(" ".join(e.body.split()), 140)["text"],
    } for e in rows]
    kind = "unread email" if p.unread_only else "email"
    if not items:
        speech = f"I found no matching {kind}s."
    else:
        listing = "; ".join(f"{i + 1}, from {it['from']}, {it['subject']}" for i, it in enumerate(items[:5]))
        speech = f"I found {total} {kind}{'s' if total != 1 else ''}. {listing}."
        if total > len(items):
            speech += f" I am showing the latest {len(items)}."
    ctx.remember(last_email_ids=[it["email_id"] for it in items])
    return ToolResult(speech=speech, data={"count": total, "emails": items, "preview_trust": "untrusted"})


def read_email(ctx: ToolContext, p: ReadEmailParams) -> ToolResult:
    email = require_ok(ctx.adapters.email.get(ctx.user.id, p.email_id), "email")
    note_untrusted_addresses(ctx, email.body)
    data = {
        "email_id": email.id, "from": email.from_name, "from_address": email.from_addr,
        "to": email.to_addrs, "subject": email.subject, "received": _when(ctx, email.received_at),
        "body": untrusted(email.body, BODY_LIMIT),
    }
    speech = (f"Email from {email.from_name}, received {data['received']}, subject: {email.subject}. "
              "The body is included for you to summarise.")
    return ToolResult(speech=speech, data=data)


# ---------------------------------------------------------------- pending action: send_email

def build_email(ctx: ToolContext, inputs: dict) -> BuiltAction:
    p = EmailDraftParams.model_validate(inputs)
    recipients = resolve_addresses(ctx, p.to, "recipient")
    risky = untrusted_recipients(ctx, recipients)
    preview = " ".join(p.body.split())
    summary = (f"Send an email to {join_words(recipients)} with the subject '{p.subject}'. "
               f"The message says: {preview[:300]}{'…' if len(preview) > 300 else ''}")
    flags: list[str] = []
    if risky:
        flags.append("recipient_from_untrusted_content")
        summary = untrusted_warning(risky) + summary
    return BuiltAction(payload={"to": recipients, "subject": p.subject, "body": p.body},
                       summary=summary, risk_flags=flags)


def _step_send(ctx: ToolContext, action: Action, key: str, _prev: dict) -> StepResult:
    pl = action.payload
    res = ctx.adapters.email.send(ctx.user.id, to=pl["to"], subject=pl["subject"], body=pl["body"],
                                  idempotency_key=key)
    if not res.ok:
        return StepResult(False, "failed", message=res.message or "the mail service rejected the message")
    check = ctx.adapters.email.get(ctx.user.id, res.data.id)
    if not check.ok or check.data.folder != "sent":
        return StepResult(False, "unknown_outcome", message="the sent message could not be verified")
    return StepResult(True, detail={"email_id": res.data.id, "recipients": pl["to"], "verified": True,
                                    "deduplicated": res.meta.get("deduplicated", False)})


def _reconcile_send(ctx: ToolContext, action: Action, key: str) -> StepResult | None:
    found = ctx.adapters.email.find_by_key(ctx.user.id, key)
    if found.ok:
        return StepResult(True, detail={"email_id": found.data.id, "recipients": found.data.to_addrs,
                                        "verified": True, "deduplicated": True})
    return None


EMAIL_HANDLER = register_action_handler(ActionHandler(
    type="send_email", scope="email.send", label="email",
    build=build_email, editable_fields=("to", "subject", "body"),
    steps=[Step("send_email", _step_send, _reconcile_send, description="Send the email")],
    success_speech=lambda action, details: (
        f"Done. Your email '{action.payload['subject']}' was sent to {join_words(action.payload['to'])}."),
))
