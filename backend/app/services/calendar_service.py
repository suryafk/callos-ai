"""Calendar tools: list events, check availability, prepare and create meetings."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from pydantic import Field, field_validator

from app.core.types import (
    Action, ActionHandler, BuiltAction, Step, StepResult, ToolContext, ToolError, ToolParams, ToolResult,
    register_action_handler,
)
from app.integrations.base import AdapterStatus
from app.services.common import (
    as_list, join_words, require_ok, resolve_addresses, untrusted_recipients, untrusted_warning,
)
from app.utils.timeparse import (
    TimeParseError, fmt_date, fmt_time, get_zone, iso_utc, parse_date, parse_time, to_local, to_utc,
)

PARTS_OF_DAY = {"morning": (9, 12), "afternoon": (12, 17), "evening": (17, 21), "day": (9, 18)}


class CheckCalendarParams(ToolParams):
    date: str = "today"
    part_of_day: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    duration_minutes: int = Field(30, ge=5, le=480)


class ListEventsParams(ToolParams):
    date: str = "today"
    end_date: str | None = None


class MeetingParams(ToolParams):
    title: str = Field(min_length=1, max_length=200)
    date: str = Field(min_length=1)
    time: str = Field(min_length=1)
    duration_minutes: int = Field(30, ge=5, le=480)
    attendees: list[str] = Field(default_factory=list, max_length=20)
    timezone: str | None = None

    @field_validator("attendees", mode="before")
    @classmethod
    def _attendees(cls, v: Any) -> list[str]:
        return as_list(v)


def _parse(fn, *args):
    try:
        return fn(*args)
    except TimeParseError as exc:
        raise ToolError("invalid_request", str(exc))


def event_view(ev, tz) -> dict:
    start, end = to_local(ev.start_utc, tz), to_local(ev.end_utc, tz)
    return {
        "id": ev.id, "title": ev.title, "date": start.date().isoformat(),
        "start": fmt_time(start), "end": fmt_time(end), "attendees": ev.attendees or [],
    }


def _speak_events(events: list[dict]) -> str:
    return join_words([f"{e['title']} from {e['start']} to {e['end']}" for e in events])


def free_slots(events, start_utc: datetime, end_utc: datetime, min_minutes: int) -> list[tuple[datetime, datetime]]:
    slots, cursor, need = [], start_utc, timedelta(minutes=min_minutes)
    for ev in sorted(events, key=lambda e: e.start_utc):
        if ev.start_utc - cursor >= need:
            slots.append((cursor, min(ev.start_utc, end_utc)))
        cursor = max(cursor, ev.end_utc)
    if end_utc - cursor >= need:
        slots.append((cursor, end_utc))
    return slots


def check_calendar(ctx: ToolContext, p: CheckCalendarParams) -> ToolResult:
    tz = ctx.tz
    day = _parse(parse_date, p.date, tz, ctx.now)
    part = (p.part_of_day or "").lower().strip() or None
    if part and part not in PARTS_OF_DAY:
        raise ToolError("invalid_request", "part_of_day must be morning, afternoon or evening.")
    if p.start_time:
        start_t = _parse(parse_time, p.start_time)
        start = to_utc(day, start_t, tz)
        end = to_utc(day, _parse(parse_time, p.end_time), tz) if p.end_time \
            else start + timedelta(minutes=p.duration_minutes)
        if end <= start:
            raise ToolError("invalid_request", "The end time must be after the start time.")
        window_label = f"between {fmt_time(to_local(start, tz))} and {fmt_time(to_local(end, tz))}"
    else:
        lo, hi = PARTS_OF_DAY[part or "day"]
        start, end = to_utc(day, time(lo), tz), to_utc(day, time(hi), tz)
        window_label = f"in the {part}" if part else "during working hours"
    events = require_ok(ctx.adapters.calendar.list_events(ctx.user.id, start_utc=start, end_utc=end), "calendar")
    views = [event_view(e, tz) for e in events]
    slots = free_slots(events, start, end, p.duration_minutes)
    slot_views = [{"start": fmt_time(to_local(a, tz)), "end": fmt_time(to_local(b, tz))} for a, b in slots]

    when = f"{fmt_date(day, ctx.today)}, {window_label}"
    if not views:
        speech = f"You have nothing scheduled {when}. You are free the whole time."
    else:
        noun = "meeting" if len(views) == 1 else "meetings"
        speech = f"For {when}, you have {len(views)} {noun}: {_speak_events(views)}. "
        if slot_views:
            speech += "You are free " + join_words([f"from {s['start']} to {s['end']}" for s in slot_views]) + "."
        else:
            speech += f"There is no free slot of {p.duration_minutes} minutes in that window."
    return ToolResult(speech=speech, data={
        "date": day.isoformat(), "timezone": str(tz), "is_free": not views,
        "events": views, "free_slots": slot_views,
    })


def list_calendar_events(ctx: ToolContext, p: ListEventsParams) -> ToolResult:
    tz = ctx.tz
    first = _parse(parse_date, p.date, tz, ctx.now)
    last = _parse(parse_date, p.end_date, tz, ctx.now) if p.end_date else first
    if last < first or (last - first).days > 31:
        raise ToolError("invalid_request", "The date range must be between one day and one month.")
    start, end = to_utc(first, time(0), tz), to_utc(last + timedelta(days=1), time(0), tz)
    events = require_ok(ctx.adapters.calendar.list_events(ctx.user.id, start_utc=start, end_utc=end), "calendar")
    views = [event_view(e, tz) for e in events]
    span = fmt_date(first, ctx.today) if first == last else f"{fmt_date(first, ctx.today)} to {fmt_date(last, ctx.today)}"
    if not views:
        speech = f"You have no events on {span}."
    else:
        shown = views[:5]
        if first == last:
            listing = _speak_events(shown)
        else:
            listing = join_words([f"{e['title']} on {e['date']} at {e['start']}" for e in shown])
        speech = f"You have {len(views)} event{'s' if len(views) != 1 else ''} on {span}: {listing}."
        if len(views) > len(shown):
            speech += f" Plus {len(views) - len(shown)} more."
    return ToolResult(speech=speech, data={"timezone": str(tz), "count": len(views), "events": views[:10]})


# ---------------------------------------------------------------- pending action: create_meeting

def build_meeting(ctx: ToolContext, inputs: dict) -> BuiltAction:
    p = MeetingParams.model_validate(inputs)
    try:
        tz = get_zone(p.timezone or ctx.user.timezone, ctx.settings.default_timezone)
    except TimeParseError as exc:
        raise ToolError("invalid_request", str(exc))
    day, at = _parse(parse_date, p.date, tz, ctx.now), _parse(parse_time, p.time)
    start = to_utc(day, at, tz)
    end = start + timedelta(minutes=p.duration_minutes)
    if start < ctx.now - timedelta(minutes=1):
        raise ToolError("invalid_request", "That time has already passed. Please choose a future time.")
    attendees = resolve_addresses(ctx, p.attendees, "attendee")

    clashes = require_ok(ctx.adapters.calendar.list_events(ctx.user.id, start_utc=start, end_utc=end), "calendar")
    if clashes:
        day_events = require_ok(ctx.adapters.calendar.list_events(
            ctx.user.id, start_utc=to_utc(day, time(9), tz), end_utc=to_utc(day, time(18), tz)), "calendar")
        slots = free_slots(day_events, max(to_utc(day, time(9), tz), ctx.now), to_utc(day, time(18), tz),
                           p.duration_minutes)
        slot_views = [{"start": fmt_time(to_local(a, tz)), "end": fmt_time(to_local(b, tz))} for a, b in slots]
        clash = event_view(clashes[0], tz)
        speech = (f"That time conflicts with {clash['title']}, from {clash['start']} to {clash['end']}. "
                  "{effect} ")
        if slot_views:
            speech += "You are free " + join_words([f"from {s['start']} to {s['end']}" for s in slot_views[:3]]) + "."
        raise ToolError("conflict", speech, {"conflicts": [event_view(c, tz) for c in clashes],
                                             "free_slots": slot_views})

    local_start, local_end = to_local(start, tz), to_local(end, tz)
    summary = (f"Create the meeting '{p.title}' on {fmt_date(day)} from {fmt_time(local_start)} "
               f"to {fmt_time(local_end)} {local_start.tzname()}")
    summary += f", and send invitations to {join_words(attendees)}." if attendees else ", with no invitees."
    flags: list[str] = []
    risky = untrusted_recipients(ctx, attendees)
    if risky:
        flags.append("recipient_from_untrusted_content")
        summary = untrusted_warning(risky) + summary
    payload = {
        "title": p.title, "date": day.isoformat(), "time": at.strftime("%H:%M"), "timezone": str(tz),
        "duration_minutes": p.duration_minutes, "attendees": attendees,
        "start_utc": iso_utc(start), "end_utc": iso_utc(end),
    }
    return BuiltAction(payload=payload, summary=summary, risk_flags=flags)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.rstrip("Z"))


def _event_detail(ev, deduplicated: bool) -> dict:
    return {"event_id": ev.id, "title": ev.title, "start_utc": iso_utc(ev.start_utc),
            "end_utc": iso_utc(ev.end_utc), "deduplicated": deduplicated}


def _step_create_event(ctx: ToolContext, action: Action, key: str, _prev: dict) -> StepResult:
    pl = action.payload
    res = ctx.adapters.calendar.create_event(
        ctx.user.id, title=pl["title"], start_utc=_dt(pl["start_utc"]), end_utc=_dt(pl["end_utc"]),
        attendees=pl["attendees"], idempotency_key=key)
    if res.status == AdapterStatus.CONFLICT:
        return StepResult(False, "conflict", message=f"the calendar now has a conflict: {res.message}")
    if not res.ok:
        return StepResult(False, "failed", message=res.message or "the calendar rejected the request")
    # Verify the effect by reading the event back before reporting success.
    check = ctx.adapters.calendar.get_event(ctx.user.id, res.data.id)
    if not check.ok or check.data.start_utc != _dt(pl["start_utc"]):
        return StepResult(False, "unknown_outcome", message="the new event could not be verified")
    return StepResult(True, detail={**_event_detail(check.data, res.meta.get("deduplicated", False)), "verified": True})


def _reconcile_event(ctx: ToolContext, action: Action, key: str) -> StepResult | None:
    found = ctx.adapters.calendar.find_by_key(ctx.user.id, key)
    if found.ok:
        return StepResult(True, detail={**_event_detail(found.data, True), "verified": True})
    return None


def _step_send_invitations(ctx: ToolContext, action: Action, key: str, prev: dict) -> StepResult:
    pl = action.payload
    tz = get_zone(pl["timezone"])
    start = to_local(_dt(pl["start_utc"]), tz)
    body = (f"You are invited to '{pl['title']}' on {fmt_date(start.date())} at {fmt_time(start)} "
            f"{start.tzname()} for {pl['duration_minutes']} minutes.\n\nScheduled by phone through CallOS AI "
            f"on behalf of {ctx.user.display_name}. Calendar event: {prev.get('create_event', {}).get('event_id')}.")
    res = ctx.adapters.email.send(ctx.user.id, to=pl["attendees"], subject=f"Invitation: {pl['title']}",
                                  body=body, idempotency_key=key)
    if not res.ok:
        return StepResult(False, "failed", message=res.message or "the invitations could not be sent")
    return StepResult(True, detail={"email_id": res.data.id, "recipients": pl["attendees"], "verified": True})


def _reconcile_invitations(ctx: ToolContext, action: Action, key: str) -> StepResult | None:
    found = ctx.adapters.email.find_by_key(ctx.user.id, key)
    if found.ok:
        return StepResult(True, detail={"email_id": found.data.id, "recipients": found.data.to_addrs, "verified": True})
    return None


def _meeting_success(action: Action, details: dict) -> str:
    pl = action.payload
    start = to_local(_dt(pl["start_utc"]), get_zone(pl["timezone"]))
    speech = (f"Done. '{pl['title']}' is now on your calendar for {fmt_date(start.date())} at "
              f"{fmt_time(start)} {start.tzname()}.")
    if "send_invitations" in details:
        speech += f" Invitations were sent to {join_words(pl['attendees'])}."
    return speech


MEETING_HANDLER = register_action_handler(ActionHandler(
    type="create_meeting", scope="calendar.write", label="meeting",
    build=build_meeting,
    editable_fields=("title", "date", "time", "duration_minutes", "attendees", "timezone"),
    steps=[
        Step("create_event", _step_create_event, _reconcile_event, description="Create the calendar event"),
        Step("send_invitations", _step_send_invitations, _reconcile_invitations,
             applies=lambda payload: bool(payload.get("attendees")), description="Email invitations to attendees"),
    ],
    success_speech=_meeting_success,
))
