"""Approval invariants: only the latest approved version executes, exactly once."""
import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app import database
from app.core import orchestrator
from app.models import Action, Approval, MockCalendarEvent
from tests.conftest import Caller

MEETING = dict(title="Project retrospective", date="tomorrow", time="16:00")


def retro_events(db):
    db.expire_all()
    return db.scalars(select(MockCalendarEvent).where(MockCalendarEvent.title == "Project retrospective")).all()


def test_nothing_is_written_before_approval(caller, db):
    prepared = caller.tool("prepare_meeting", **MEETING)
    assert prepared["status"] == "awaiting_approval" and prepared["requires_approval"] is True
    assert prepared["expires_at"].endswith("Z") and prepared["execution_mode"] == "mock"
    assert retro_events(db) == []
    assert db.scalars(select(Approval)).all() == []


def test_approval_executes_and_reports_verified_result(caller, db):
    prepared = caller.tool("prepare_meeting", **MEETING)
    done = caller.approve(prepared["action_id"], prepared["version"])
    assert done["ok"] and done["status"] == "completed" and done["data"]["verified"] is True
    event_id = done["data"]["steps"]["create_event"]["event_id"]
    db.expire_all()
    stored = db.get(MockCalendarEvent, event_id)
    assert stored is not None and stored.created_by == "callos" and stored.user_id == "usr-aarav"
    assert stored.idempotency_key == f"{prepared['action_id']}:v1:create_event"
    approval = db.scalar(select(Approval).where(Approval.action_id == prepared["action_id"]))
    assert approval.action_version == 1 and approval.consumed_at is not None
    listed = caller.tool("list_calendar_events", date="tomorrow")["data"]["events"]
    assert "Project retrospective" in [e["title"] for e in listed]


def test_repeated_approval_does_not_execute_twice(caller, db):
    prepared = caller.tool("prepare_meeting", **MEETING)
    first = caller.approve(prepared["action_id"], 1)
    for _ in range(3):
        again = caller.approve(prepared["action_id"], 1)
        assert again["status"] == "completed" and again["data"]["already_executed"] is True
        assert "already done" in again["speech"]
    assert len(retro_events(db)) == 1
    assert first["data"]["steps"]["create_event"]["event_id"] == again["data"]["steps"]["create_event"]["event_id"]
    executed = [e for e in caller.events() if e["event_type"] == "action_executed"]
    assert len(executed) == 1


def test_concurrent_approvals_execute_exactly_once(client, settings, caller, db):
    prepared = caller.tool("prepare_meeting", **MEETING)
    barrier = threading.Barrier(8)

    def approve():
        session = database.new_session()
        try:
            barrier.wait(timeout=10)
            return orchestrator.dispatch(
                session, settings, session_id=caller.session_id, action="approve_action",
                params={"action_id": prepared["action_id"], "version": 1},
                via_endpoint="/api/actions/approve").status
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [f.result(timeout=30) for f in [pool.submit(approve) for _ in range(8)]]
    assert set(results) <= {"completed", "in_progress"}, results
    assert "completed" in results
    assert len(retro_events(db)) == 1
    db.expire_all()
    assert db.get(Action, prepared["action_id"]).status == "completed"
    executed = [e for e in caller.events() if e["event_type"] == "action_executed"]
    assert len(executed) == 1


def test_stale_version_is_rejected_and_latest_executes(caller, db):
    prepared = caller.tool("prepare_meeting", title="Project retrospective", date="tomorrow", time="15:00")
    caller.tool("update_pending_action", time="15:30")
    caller.tool("update_pending_action", time="16:00")
    for stale in (1, 2, 99):
        out = caller.approve(prepared["action_id"], stale)
        assert out["status"] == "stale_version", stale
    assert retro_events(db) == []
    assert caller.approve(prepared["action_id"], 3)["status"] == "completed"
    events = retro_events(db)
    assert len(events) == 1 and events[0].start_utc.strftime("%H:%M") == "10:30"  # 16:00 IST in UTC


def test_approval_needs_action_id_and_version(caller):
    prepared = caller.tool("prepare_meeting", **MEETING)
    assert caller.approve(prepared["action_id"], None)["status"] == "invalid_request"
    assert caller.approve(None, 1)["status"] == "invalid_request"
    assert caller.approve(prepared["action_id"], "not-a-number")["status"] == "invalid_request"
    assert caller.approve(prepared["action_id"], "1")["status"] == "completed"  # numeric strings are fine


def test_unknown_action_id_is_not_found(caller):
    out = caller.approve("act-doesnotexist", 1)
    assert out["status"] == "not_found" and out["ok"] is False


def test_approval_requires_a_verified_session(client, caller, db):
    prepared = caller.tool("prepare_meeting", **MEETING)
    stranger = Caller(client, "call-stranger-01")
    out = stranger.approve(prepared["action_id"], 1)
    assert out["status"] == "auth_required"
    assert retro_events(db) == []


def test_action_cannot_be_approved_or_cancelled_from_another_session(client, caller, db):
    prepared = caller.tool("prepare_meeting", **MEETING)
    other = Caller(client, "call-aarav-002")  # same user, different call
    other.verify()
    assert other.approve(prepared["action_id"], 1)["status"] == "not_found"
    assert other.cancel(prepared["action_id"])["status"] == "not_found"
    assert other.tool("update_pending_action", action_id=prepared["action_id"], time="17:00")["status"] == "not_found"
    assert retro_events(db) == []
    assert caller.state()["pending_actions"][0]["version"] == 1
    assert caller.approve(prepared["action_id"], 1)["status"] == "completed"


def test_cancel_after_execution_is_refused(caller, db):
    prepared = caller.tool("prepare_meeting", **MEETING)
    caller.approve(prepared["action_id"], 1)
    out = caller.cancel(prepared["action_id"])
    assert out["status"] == "action_completed" and out["ok"] is False
    assert len(retro_events(db)) == 1


def test_conflict_appearing_after_preparation_blocks_execution(caller, db):
    first = caller.tool("prepare_meeting", **MEETING)
    second = caller.tool("prepare_meeting", title="Other meeting", date="tomorrow", time="16:15")
    assert caller.approve(first["action_id"], 1)["status"] == "completed"
    out = caller.approve(second["action_id"], 1)
    assert out["status"] == "failed" and "conflict" in out["speech"]
    db.expire_all()
    assert db.scalars(select(MockCalendarEvent).where(MockCalendarEvent.title == "Other meeting")).all() == []
