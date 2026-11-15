"""Mock workspace: email, documents, calendar and tasks backed by persistent data."""
from sqlalchemy import select

from app.models import MockCalendarEvent, MockEmail, MockTask


def test_email_search_by_manager_alias_returns_real_rows(caller, db):
    body = caller.tool("search_emails", sender="my manager")
    emails = body["data"]["emails"]
    assert [e["email_id"] for e in emails] == ["em-1001", "em-1005"]  # newest first
    assert all(e["from"] == "Neha Kapoor" for e in emails)
    stored = db.get(MockEmail, "em-1001")
    assert emails[0]["subject"] == stored.subject


def test_email_search_unread_and_keyword(caller):
    unread = caller.tool("search_emails", unread_only=True)["data"]
    assert unread["count"] == 4 and all(e["unread"] for e in unread["emails"])
    hits = caller.tool("search_emails", query="staging")["data"]["emails"]
    assert [e["email_id"] for e in hits] == ["em-1002"]
    none = caller.tool("search_emails", query="zebra unicorn")
    assert none["ok"] and none["data"]["count"] == 0 and "no matching" in none["speech"]


def test_read_email_returns_exact_stored_body_marked_untrusted(caller, db):
    body = caller.tool("read_email", email_id="em-1001")["data"]
    assert body["body"]["trust"] == "untrusted"
    assert body["body"]["text"] == db.get(MockEmail, "em-1001").body
    missing = caller.tool("read_email", email_id="em-does-not-exist")
    assert missing["status"] == "not_found" and missing["ok"] is False and missing.get("data") is None


def test_document_search_and_retrieval(caller):
    found = caller.tool("search_documents", query="deployment")["data"]["documents"]
    assert found[0]["document_id"] == "doc-2001"  # title match ranks first
    doc = caller.tool("read_document", document_id="doc-2001")["data"]
    assert doc["title"] == "Deployment Runbook"
    assert "Rollback" in doc["content"]["text"] and doc["content"]["trust"] == "untrusted"
    assert doc["content"]["truncated"] is False
    assert caller.tool("read_document", document_id="doc-0000")["status"] == "not_found"
    assert caller.tool("search_documents", query="")["status"] == "invalid_request"


def test_calendar_availability_reports_events_and_free_slots(caller):
    data = caller.tool("check_calendar", date="tomorrow", part_of_day="afternoon")["data"]
    assert [e["title"] for e in data["events"]] == ["Design review"]
    assert data["free_slots"] == [{"start": "12:00 PM", "end": "2:00 PM"}, {"start": "2:45 PM", "end": "5:00 PM"}]
    assert data["is_free"] is False and data["timezone"] == "Asia/Kolkata"


def test_calendar_specific_time_window(caller):
    free = caller.tool("check_calendar", date="tomorrow", start_time="16:00", duration_minutes=30)
    assert free["data"]["is_free"] is True and "free" in free["speech"]
    busy = caller.tool("check_calendar", date="tomorrow", start_time="14:15", duration_minutes=30)
    assert busy["data"]["is_free"] is False and busy["data"]["free_slots"] == []


def test_list_calendar_events_for_day_and_range(caller):
    one = caller.tool("list_calendar_events", date="tomorrow")["data"]
    assert [e["title"] for e in one["events"]] == ["Sprint planning", "Design review"]
    span = caller.tool("list_calendar_events", date="today", end_date="day after tomorrow")["data"]
    assert span["count"] == 6
    bad = caller.tool("list_calendar_events", date="tomorrow", end_date="today")
    assert bad["status"] == "invalid_request"


def test_meeting_conflict_is_detected_and_nothing_is_prepared(caller, db):
    body = caller.tool("prepare_meeting", title="Clash", date="tomorrow", time="14:15")
    assert body["status"] == "conflict" and body["ok"] is False
    assert "I have not prepared anything" in body["speech"] and "{" not in body["speech"]
    assert body["data"]["conflicts"][0]["title"] == "Design review"
    assert body["data"]["free_slots"]
    assert caller.state()["actions"] == []
    assert db.scalars(select(MockCalendarEvent).where(MockCalendarEvent.title == "Clash")).all() == []


def test_meeting_in_the_past_is_refused(caller):
    body = caller.tool("prepare_meeting", title="Old", date="yesterday", time="10:00")
    assert body["status"] == "invalid_request" and "passed" in body["speech"]


def test_unknown_attendee_asks_for_clarification(caller):
    body = caller.tool("prepare_meeting", title="Sync", date="tomorrow", time="16:00", attendees=["Zaphod"])
    assert body["status"] == "needs_clarification" and "Zaphod" in body["speech"]
    ok = caller.tool("prepare_meeting", title="Sync", date="tomorrow", time="16:00", attendees="Neha and team")
    assert ok["data"]["details"]["attendees"] == ["neha.kapoor@example.test", "team@example.test"]


def test_tasks_list_and_filters(caller):
    open_tasks = caller.tool("list_tasks")["data"]
    assert open_tasks["count"] == 3
    assert open_tasks["tasks"][0]["title"] == "Submit expense report"  # earliest due first
    assert caller.tool("list_tasks", status="completed")["data"]["count"] == 1
    assert caller.tool("list_tasks", status="all")["data"]["count"] == 4
    assert caller.tool("list_tasks", status="bogus")["status"] == "invalid_request"


def test_task_is_created_only_after_approval_and_persists(caller, db):
    before = db.scalars(select(MockTask)).all()
    prepared = caller.tool("prepare_task", title="Review the deployment", due_date="friday")
    assert prepared["status"] == "awaiting_approval" and prepared["requires_approval"] is True
    db.expire_all()
    assert len(db.scalars(select(MockTask)).all()) == len(before)  # nothing written yet
    done = caller.approve(prepared["action_id"], prepared["version"])
    assert done["status"] == "completed" and done["data"]["verified"] is True
    db.expire_all()
    task = db.get(MockTask, done["data"]["steps"]["create_task"]["task_id"])
    assert task.title == "Review the deployment" and task.created_by == "callos" and task.due_date.weekday() == 4
    assert caller.tool("list_tasks")["data"]["count"] == 4


def test_task_completion_requires_approval(caller, db):
    prepared = caller.tool("prepare_task_completion", title="expense")
    assert prepared["status"] == "awaiting_approval" and "Submit expense report" in prepared["summary"]
    assert db.get(MockTask, "tsk-4003").status == "open"
    done = caller.approve(prepared["action_id"], 1)
    assert done["status"] == "completed"
    db.expire_all()
    assert db.get(MockTask, "tsk-4003").status == "completed"
    again = caller.tool("prepare_task_completion", task_id="tsk-4003")
    assert again["status"] == "conflict"
    assert caller.tool("prepare_task_completion", title="no such task")["status"] == "not_found"


def test_email_is_sent_only_after_approval(caller, db):
    prepared = caller.tool("prepare_email", to="my manager", subject="Rollback plan",
                           body="Hi Neha, I have signed off the rollback plan.")
    assert prepared["status"] == "awaiting_approval"
    assert prepared["data"]["details"]["to"] == ["neha.kapoor@example.test"]
    assert db.scalars(select(MockEmail).where(MockEmail.folder == "sent")).all() == []
    done = caller.approve(prepared["action_id"], 1)
    assert done["status"] == "completed"
    db.expire_all()
    sent = db.scalars(select(MockEmail).where(MockEmail.folder == "sent")).all()
    assert len(sent) == 1 and sent[0].subject == "Rollback plan" and sent[0].to_addrs == ["neha.kapoor@example.test"]
