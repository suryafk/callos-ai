"""Workflow state machine, pending actions, corrections, failures and persistence."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import set_settings
from app.core.workflow_engine import TRANSITIONS, WorkflowState
from app.database import utcnow
from app.integrations.base import AdapterResult, AdapterStatus, IntegrationError, IntegrationTimeout
from app.integrations.mock.adapters import MockCalendarAdapter, MockEmailAdapter
from app.main import create_app
from app.models import Action, Approval, MockCalendarEvent, MockEmail
from tests.conftest import Caller

MEETING = dict(title="Project retrospective", date="tomorrow", time="15:00", duration_minutes=30)


def retro_events(db):
    db.expire_all()
    return db.scalars(select(MockCalendarEvent).where(MockCalendarEvent.title == "Project retrospective")).all()


def states(caller):
    return [e["detail"]["to"] for e in caller.events() if e["event_type"] == "state_changed"]


def test_all_required_states_exist_and_can_always_restart():
    required = {"listening", "understanding", "needs_auth", "gathering_data", "planning",
                "awaiting_approval", "executing", "completed", "failed", "cancelled"}
    assert {s.value for s in WorkflowState} == required
    for state, targets in TRANSITIONS.items():
        if state is not WorkflowState.UNDERSTANDING:
            assert WorkflowState.UNDERSTANDING in targets


def test_state_sequence_for_read_prepare_approve(caller):
    caller.tool("check_calendar", date="tomorrow")
    prepared = caller.tool("prepare_meeting", **MEETING)
    assert prepared["workflow_state"] == "awaiting_approval"
    done = caller.approve(prepared["action_id"], 1)
    assert done["workflow_state"] == "completed"
    assert states(caller) == [
        "understanding", "listening",                       # verify_identity
        "understanding", "gathering_data", "listening",     # check_calendar
        "understanding", "planning", "awaiting_approval",   # prepare_meeting
        "understanding", "executing", "completed",          # approve
    ]
    assert caller.tool("list_tasks")["workflow_state"] == "listening"  # ready for the next request


def test_anonymous_private_request_moves_to_needs_auth(anon):
    body = anon.tool("check_calendar", date="tomorrow")
    assert body["status"] == "auth_required" and body["workflow_state"] == "needs_auth"
    assert anon.verify()["workflow_state"] == "listening"


def test_change_of_mind_updates_pending_action_and_invalidates_approval(caller, db):
    prepared = caller.tool("prepare_meeting", **MEETING)
    aid = prepared["action_id"]
    assert prepared["version"] == 1 and "3:00 PM" in prepared["summary"]

    updated = caller.tool("update_pending_action", action_id=aid, time="16:00")
    assert updated["action_id"] == aid and updated["version"] == 2
    assert "4:00 PM" in updated["summary"] and "3:00 PM" not in updated["summary"]
    assert updated["data"]["changed"] is True and updated["data"]["previous_version"] == 1
    assert updated["requires_approval"] is True

    stale = caller.approve(aid, 1)
    assert stale["status"] == "stale_version" and stale["ok"] is False
    assert stale["data"]["version"] == 2
    assert retro_events(db) == []

    done = caller.approve(aid, 2)
    assert done["status"] == "completed"
    events = retro_events(db)
    assert len(events) == 1
    assert events[0].start_utc.isoformat() == done["data"]["details"]["start_utc"].rstrip("Z")
    assert done["data"]["details"]["time"] == "16:00"
    types = [e["event_type"] for e in caller.events()]
    assert types.count("action_updated") == 1 and "approval_rejected" in types


def test_an_approval_recorded_for_an_old_version_is_invalidated(caller, db):
    prepared = caller.tool("prepare_meeting", **MEETING)
    aid = prepared["action_id"]
    # An approval row for v1 exists (e.g. recorded just before the caller changed their mind).
    db.add(Approval(action_id=aid, action_version=1, user_id="usr-aarav", session_id=caller.session_id))
    db.commit()
    caller.tool("update_pending_action", time="16:00")
    db.expire_all()
    old = db.scalar(select(Approval).where(Approval.action_id == aid, Approval.action_version == 1))
    assert old.invalidated_at is not None and old.consumed_at is None
    assert caller.approve(aid, 1)["status"] == "stale_version"
    assert retro_events(db) == []


def test_update_without_action_id_uses_the_single_pending_action(caller):
    prepared = caller.tool("prepare_meeting", **MEETING)
    updated = caller.tool("update_pending_action", title="Sprint retrospective", duration_minutes=45)
    assert updated["action_id"] == prepared["action_id"] and updated["version"] == 2
    assert updated["data"]["details"]["title"] == "Sprint retrospective"
    assert updated["data"]["details"]["duration_minutes"] == 45
    assert updated["data"]["details"]["time"] == "15:00"  # untouched fields are kept


def test_update_to_conflicting_time_leaves_action_untouched(caller):
    prepared = caller.tool("prepare_meeting", **MEETING)
    clash = caller.tool("update_pending_action", time="14:15")
    assert clash["status"] == "conflict" and "left your pending request as it was" in clash["speech"]
    assert "{" not in clash["speech"]
    current = caller.state()["pending_actions"][0]
    assert current["version"] == 1 and current["parameters"]["time"] == "15:00"
    assert caller.approve(prepared["action_id"], 1)["status"] == "completed"


def test_update_with_no_real_change_keeps_the_version(caller):
    caller.tool("prepare_meeting", **MEETING)
    same = caller.tool("update_pending_action", time="15:00")
    assert same["version"] == 1 and same["data"]["changed"] is False
    irrelevant = caller.tool("update_pending_action", subject="not a meeting field")
    assert irrelevant["status"] == "invalid_request"


def test_update_with_nothing_pending(caller):
    assert caller.tool("update_pending_action", time="16:00")["status"] == "not_found"


def test_two_pending_actions_require_disambiguation(caller):
    a = caller.tool("prepare_meeting", **MEETING)
    b = caller.tool("prepare_task", title="Review the deployment")
    ambiguous = caller.tool("update_pending_action", title="New title")
    assert ambiguous["status"] == "needs_clarification"
    assert {p["action_id"] for p in ambiguous["data"]["pending"]} == {a["action_id"], b["action_id"]}
    assert caller.cancel()["status"] == "needs_clarification"
    assert caller.cancel(b["action_id"])["workflow_state"] == "awaiting_approval"  # one still pending
    pending = caller.tool("get_pending_action")
    assert pending["action_id"] == a["action_id"]


def test_cancellation_writes_nothing_and_is_final(caller, db):
    prepared = caller.tool("prepare_meeting", **MEETING)
    cancelled = caller.cancel(prepared["action_id"])
    assert cancelled["status"] == "cancelled" and cancelled["workflow_state"] == "cancelled"
    assert "Nothing was changed" in cancelled["speech"]
    assert retro_events(db) == []
    refused = caller.approve(prepared["action_id"], 1)
    assert refused["status"] == "action_cancelled" and refused["ok"] is False
    assert retro_events(db) == []
    assert caller.tool("update_pending_action", action_id=prepared["action_id"], time="16:00")["status"] == "action_cancelled"
    assert caller.cancel(prepared["action_id"])["status"] == "cancelled"  # idempotent
    assert "action_cancelled" in [e["event_type"] for e in caller.events()]


def test_cancel_via_generic_dispatcher_without_id(caller):
    caller.tool("prepare_task", title="Review the deployment")
    assert caller.tool("cancel_action")["status"] == "cancelled"
    assert caller.tool("cancel_action")["status"] == "not_found"


def test_multi_step_workflow_runs_dependent_steps_in_order(caller, db):
    prepared = caller.tool("prepare_meeting", attendees=["team"], **MEETING)
    assert "send invitations to team@example.test" in prepared["summary"]
    done = caller.approve(prepared["action_id"], 1)
    steps = done["data"]["steps"]
    assert list(steps) == ["create_event", "send_invitations"]
    db.expire_all()
    invite = db.get(MockEmail, steps["send_invitations"]["email_id"])
    assert invite.folder == "sent" and invite.to_addrs == ["team@example.test"]
    assert steps["create_event"]["event_id"] in invite.body  # second step used the first step's result
    action = db.get(Action, prepared["action_id"])
    assert [s["status"] for s in action.steps] == ["success", "success"]


def test_partial_failure_is_reported_honestly(caller, db, monkeypatch):
    monkeypatch.setattr(MockEmailAdapter, "send", lambda self, *a, **k: AdapterResult(
        AdapterStatus.FAILED, message="mail server rejected the message"))
    prepared = caller.tool("prepare_meeting", attendees=["team"], **MEETING)
    out = caller.approve(prepared["action_id"], 1)
    assert out["status"] == "partially_completed" and out["ok"] is False
    assert out["workflow_state"] == "failed"
    assert "partly" in out["speech"] and "create event" in out["speech"] and "Done." not in out["speech"]
    assert len(retro_events(db)) == 1  # the first step really happened
    assert db.scalars(select(MockEmail).where(MockEmail.folder == "sent")).all() == []
    replay = caller.approve(prepared["action_id"], 1)
    assert replay["status"] == "partially_completed" and replay["data"]["already_executed"] is True
    assert len(retro_events(db)) == 1


def test_definite_tool_failure_never_claims_success(caller, db, monkeypatch):
    def boom(self, *a, **k):
        raise IntegrationError("connection refused")
    monkeypatch.setattr(MockCalendarAdapter, "create_event", boom)
    prepared = caller.tool("prepare_meeting", **MEETING)
    out = caller.approve(prepared["action_id"], 1)
    assert out["status"] == "failed" and out["ok"] is False and out["workflow_state"] == "failed"
    assert "Nothing was changed" in out["speech"] and retro_events(db) == []
    assert caller.approve(prepared["action_id"], 1)["status"] == "action_failed"
    assert caller.tool("list_tasks")["ok"]  # the session recovers


def test_timeout_before_the_write_is_reconciled_as_not_created(caller, db, monkeypatch):
    def timeout(self, *a, **k):
        raise IntegrationTimeout("no response in 10s")
    monkeypatch.setattr(MockCalendarAdapter, "create_event", timeout)
    prepared = caller.tool("prepare_meeting", **MEETING)
    out = caller.approve(prepared["action_id"], 1)
    assert out["status"] == "failed" and "nothing was created" in out["speech"]
    assert retro_events(db) == []


def test_timeout_after_the_write_is_reconciled_as_completed(caller, db, monkeypatch):
    real = MockCalendarAdapter.create_event

    def write_then_timeout(self, *a, **k):
        real(self, *a, **k)
        raise IntegrationTimeout("response lost")
    monkeypatch.setattr(MockCalendarAdapter, "create_event", write_then_timeout)
    prepared = caller.tool("prepare_meeting", **MEETING)
    out = caller.approve(prepared["action_id"], 1)
    assert out["status"] == "completed"
    assert out["data"]["steps"]["create_event"]["reconciled"] is True
    assert len(retro_events(db)) == 1


def test_unknown_outcome_is_reported_and_retry_does_not_duplicate(caller, db, monkeypatch):
    real_create, real_find = MockCalendarAdapter.create_event, MockCalendarAdapter.find_by_key

    outage = {"active": False}

    def write_then_timeout(self, *a, **k):
        real_create(self, *a, **k)  # the write lands...
        outage["active"] = True     # ...then the provider stops answering
        raise IntegrationTimeout("response lost")

    def lookup_down(self, *a, **k):
        if outage["active"]:
            raise IntegrationTimeout("lookup unavailable")
        return real_find(self, *a, **k)
    monkeypatch.setattr(MockCalendarAdapter, "create_event", write_then_timeout)
    monkeypatch.setattr(MockCalendarAdapter, "find_by_key", lookup_down)
    prepared = caller.tool("prepare_meeting", **MEETING)
    out = caller.approve(prepared["action_id"], 1)
    assert out["status"] == "unknown_outcome" and out["ok"] is False
    assert "could not confirm" in out["speech"] and "Done." not in out["speech"]

    assert len(retro_events(db)) == 1  # the write did land, we just could not confirm it

    # The service recovers; approving again reuses the same idempotency key.
    outage["active"] = False
    monkeypatch.setattr(MockCalendarAdapter, "create_event", real_create)
    monkeypatch.setattr(MockCalendarAdapter, "find_by_key", real_find)
    retry = caller.approve(prepared["action_id"], 1)
    assert retry["status"] == "completed"
    assert retry["data"]["steps"]["create_event"]["deduplicated"] is True
    assert len(retro_events(db)) == 1


def test_unexpected_crash_in_a_tool_is_contained(caller, monkeypatch):
    def crash(self, *a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(MockCalendarAdapter, "list_events", crash)
    out = caller.tool("check_calendar", date="tomorrow")
    assert out["status"] == "failed" and out["workflow_state"] == "failed"
    assert "boom" not in out["speech"] and "Traceback" not in str(out)
    monkeypatch.undo()
    assert caller.tool("check_calendar", date="tomorrow")["ok"]


def test_pending_action_expires(caller, db):
    prepared = caller.tool("prepare_meeting", **MEETING)
    action = db.get(Action, prepared["action_id"])
    action.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    out = caller.approve(prepared["action_id"], 1)
    assert out["status"] == "action_expired" and retro_events(db) == []
    assert "action_expired" in [e["event_type"] for e in caller.events()]
    assert caller.tool("get_pending_action")["data"]["pending"] == []


def test_state_persists_across_a_restart(client, settings, caller, db):
    prepared = caller.tool("prepare_meeting", **MEETING)
    caller.tool("update_pending_action", time="16:00")

    restarted = create_app(settings)  # same database file, fresh process state
    with TestClient(restarted) as c2:
        same_call = Caller(c2, caller.session_id)
        snapshot = same_call.state()
        assert snapshot["session"]["auth_level"] == "authenticated"
        assert snapshot["session"]["workflow_state"] == "awaiting_approval"
        assert snapshot["pending_actions"][0]["version"] == 2
        done = same_call.approve(prepared["action_id"], 2)
        assert done["status"] == "completed"
        assert len(same_call.events()) > 8
    set_settings(settings)
    assert len(retro_events(db)) == 1


def test_seed_is_not_repeated_on_restart(client, settings, db):
    create_app(settings)
    assert len(db.scalars(select(MockEmail)).all()) == 8
