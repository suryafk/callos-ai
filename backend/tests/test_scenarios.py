"""End-to-end scenarios A–E through the HTTP API (automated backend coverage).

These tests exercise the backend exactly as the voice agent would. They are NOT
telephony tests: no phone call, speech recognition, language model or speech
synthesis is involved. Conversation quality (Scenario A's spoken answers) can
only be verified on a real Bolna call — see bolna/test_scenarios.md.
"""
from pathlib import Path

from sqlalchemy import select

from app.models import CallSession, MockCalendarEvent
from tests.conftest import PIN_PRIYA, Caller

PROMPT = (Path(__file__).resolve().parents[2] / "bolna" / "system_prompt.md").read_text(encoding="utf-8")


def created_events(db):
    db.expire_all()
    return db.scalars(select(MockCalendarEvent).where(MockCalendarEvent.created_by == "callos")).all()


def test_scenario_a_ask_ai_needs_no_backend_and_no_account(client, db):
    """General questions and follow-ups are answered by the Bolna-configured model.

    Backend-side guarantees: no tool exists for general knowledge (so no backend
    round trip is added), and an unverified caller is never asked for an account
    unless they request private data.
    """
    from app.core.tool_registry import REGISTRY

    # The allowlist contains only verification, workspace and approval tools — nothing for general Q&A.
    assert set(REGISTRY) == {
        "verify_identity", "search_emails", "read_email", "prepare_email", "list_calendar_events",
        "check_calendar", "prepare_meeting", "search_documents", "read_document", "list_tasks",
        "prepare_task", "prepare_task_completion", "get_pending_action", "update_pending_action",
        "cancel_action", "approve_action"}
    for rule in ("answer general questions yourself, immediately, without any tool",
                 "handle follow-up questions", "Reply in the language the caller is using",
                 "never chooses a mode"):
        assert rule in PROMPT, rule
    assert db.scalars(select(CallSession)).all() == []  # a pure Ask AI call creates no backend state


def test_scenario_b_act_with_ai_calendar_action(caller, db):
    availability = caller.tool("check_calendar", date="tomorrow", part_of_day="afternoon")
    assert availability["ok"] and {"start": "2:45 PM", "end": "5:00 PM"} in availability["data"]["free_slots"]

    prepared = caller.tool("prepare_meeting", title="Team sync", date="tomorrow", time="16:00",
                           duration_minutes=30)
    assert prepared["status"] == "awaiting_approval" and prepared["requires_approval"]
    assert caller.state()["session"]["workflow_state"] == "awaiting_approval"
    assert created_events(db) == []  # waits for approval

    done = caller.approve(prepared["action_id"], prepared["version"])
    assert done["status"] == "completed" and done["speech"].startswith("Done.")
    events = created_events(db)
    assert len(events) == 1 and events[0].id == done["data"]["steps"]["create_event"]["event_id"]


def test_scenario_c_ask_to_act_in_one_call(client, db):
    """Explain a retrospective (model) -> check calendar -> schedule at 4 PM -> 'yes, proceed'."""
    call = Caller(client, "call-scenario-c1")
    # 1-2. "Explain what a project retrospective is." Answered by the model: no backend call, no session.
    assert db.get(CallSession, call.session_id) is None

    # 3-4. "Check my calendar tomorrow afternoon." No mode switch: the first tool call simply arrives.
    first = call.tool("check_calendar", date="tomorrow", part_of_day="afternoon")
    assert first["status"] == "auth_required"          # private data needs verification first
    assert call.verify()["ok"]
    calendar = call.tool("check_calendar", date="tomorrow", part_of_day="afternoon")
    assert [e["title"] for e in calendar["data"]["events"]] == ["Design review"]

    # 5-6. "Schedule a retrospective meeting at 4 PM."
    prepared = call.tool("prepare_meeting", title="Project retrospective", date="tomorrow", time="16:00")
    assert prepared["status"] == "awaiting_approval" and "4:00 PM" in prepared["summary"]

    # 7-8. "Yes, proceed."
    done = call.approve(prepared["action_id"], prepared["version"])
    assert done["status"] == "completed" and done["data"]["verified"] is True
    assert "4:00 PM" in done["speech"]
    events = created_events(db)
    assert len(events) == 1 and events[0].title == "Project retrospective"

    # The call continues: context is retained and the next request needs no re-verification.
    after = call.tool("list_calendar_events", date="tomorrow")
    assert "Project retrospective" in [e["title"] for e in after["data"]["events"]]
    trail = [e["event_type"] for e in call.events()]
    for expected in ("session_started", "access_denied", "auth_succeeded", "action_prepared",
                     "action_approved", "action_executed"):
        assert expected in trail, expected


def test_scenario_d_change_of_mind_before_approval(caller, db):
    prepared = caller.tool("prepare_meeting", title="Project retrospective", date="tomorrow", time="15:00")
    changed = caller.tool("update_pending_action", action_id=prepared["action_id"], time="16:00")
    assert (prepared["version"], changed["version"]) == (1, 2)
    assert caller.approve(prepared["action_id"], 1)["status"] == "stale_version"  # the 3 PM approval is void
    assert created_events(db) == []
    done = caller.approve(prepared["action_id"], 2)
    assert done["status"] == "completed"
    events = created_events(db)
    assert len(events) == 1
    assert done["data"]["details"]["time"] == "16:00" and "4:00 PM" in done["speech"]
    three_pm = caller.tool("check_calendar", date="tomorrow", start_time="15:00", duration_minutes=30)
    assert three_pm["data"]["is_free"] is True  # nothing was ever created at 3 PM


def test_scenario_e_unauthorized_account_access_is_refused(client, caller, db):
    stranger = Caller(client, "call-scenario-e1")
    # An unverified caller asking for someone's mailbox gets nothing.
    refused = stranger.tool("search_emails", sender="Finance Desk", user_id="usr-priya", account="priya.nair@example.test")
    assert refused["status"] == "auth_required" and refused.get("data") is None
    # A verified caller asking for ANOTHER person's data is still confined to their own account.
    mine = caller.tool("search_emails", query="salary", user_id="usr-priya", account="priya.nair@example.test")
    assert mine["ok"] and mine["data"]["count"] == 0
    assert caller.tool("read_email", email_id="em-9001")["status"] == "not_found"
    # A user without the scope cannot write, verified or not.
    limited = Caller(client, "call-scenario-e2")
    limited.verify(PIN_PRIYA)
    assert limited.tool("prepare_meeting", title="x", date="tomorrow", time="10:00")["status"] == "forbidden"
    assert created_events(db) == []
    assert "access_denied" in [e["event_type"] for e in stranger.events()]
