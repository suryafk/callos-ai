"""Authentication, authorization, isolation, secrets and untrusted content."""
import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import DEV_ADMIN_KEY, DEV_TOOL_KEY, ConfigurationError, Settings, set_settings
from app.database import utcnow
from app.main import create_app
from app.models import Action, AuditEvent, CallSession, MockCalendarEvent, MockEmail, User
from app.utils.security import redact
from tests.conftest import ADMIN_HEADERS, PIN_AARAV, PIN_PRIYA, TOOL_HEADERS, Caller, make_settings

PRIVATE_TOOLS = [
    ("search_emails", {}), ("read_email", {"email_id": "em-1001"}),
    ("prepare_email", {"to": "x@example.test", "subject": "s", "body": "b"}),
    ("list_calendar_events", {"date": "tomorrow"}), ("check_calendar", {"date": "tomorrow"}),
    ("prepare_meeting", {"title": "t", "date": "tomorrow", "time": "16:00"}),
    ("search_documents", {"query": "deployment"}), ("read_document", {"document_id": "doc-2001"}),
    ("list_tasks", {}), ("prepare_task", {"title": "t"}), ("prepare_task_completion", {"task_id": "tsk-4001"}),
    ("get_pending_action", {}), ("update_pending_action", {"time": "16:00"}), ("cancel_action", {}),
]


# ---------------------------------------------------------------- anonymous vs authenticated

@pytest.mark.parametrize("tool,params", PRIVATE_TOOLS)
def test_anonymous_caller_cannot_use_any_private_tool(anon, tool, params):
    body = anon.tool(tool, **params)
    assert body["ok"] is False and body["status"] == "auth_required"
    assert body.get("data") is None  # nothing private leaks
    assert "Neha" not in json.dumps(body) and "Design review" not in json.dumps(body)


def test_anonymous_session_needs_no_account_and_stays_anonymous(anon):
    anon.tool("check_calendar", date="tomorrow")
    session = anon.state()["session"]
    assert session["auth_level"] == "anonymous" and session["user_id"] is None


def test_correct_access_code_binds_the_session_to_the_right_user(client):
    a, p = Caller(client, "call-bind-a01"), Caller(client, "call-bind-p01")
    assert a.verify(PIN_AARAV)["data"]["display_name"] == "Aarav Mehta"
    assert p.verify("7 3 1 - 2 0 5")["data"]["display_name"] == "Priya Nair"  # spoken digits
    assert a.state()["session"]["user_id"] == "usr-aarav"
    assert p.state()["session"]["user_id"] == "usr-priya"


def test_wrong_access_code_is_rejected_and_locks_after_five_attempts(anon):
    for attempt in range(1, 5):
        body = anon.tool("verify_identity", access_code="000000")
        assert body["status"] == "auth_failed" and f"{5 - attempt} attempt" in body["speech"]
    assert anon.tool("verify_identity", access_code="111111")["status"] == "locked"
    # Even the correct code is refused once the call is locked.
    assert anon.verify(PIN_AARAV)["status"] == "locked"
    assert anon.tool("list_tasks")["status"] == "auth_required"
    assert anon.state()["session"]["auth_level"] == "anonymous"


def test_malformed_codes_never_match(anon):
    for code in ("", "abc", "1", "four eight two nine one six", "482916482916482916"):
        body = anon.tool("verify_identity", access_code=code)
        assert body["ok"] is False


def test_global_failure_limit_blocks_guessing_across_calls(tmp_path):
    settings = make_settings(tmp_path, global_pin_failure_limit=3)
    with TestClient(create_app(settings)) as c:
        for i in range(3):
            assert Caller(c, f"call-guess-{i:03d}").verify("000000")["status"] == "auth_failed"
        assert Caller(c, "call-guess-999").verify(PIN_AARAV)["status"] == "locked"
    set_settings(None)


def test_access_code_is_never_logged_or_audited(client, db, caplog):
    caplog.set_level(logging.DEBUG)
    c = Caller(client, "call-secret-01")
    c.verify("999999")
    c.verify(PIN_AARAV)
    captured = caplog.text + json.dumps([r.__dict__ for r in caplog.records], default=str)
    for secret in (PIN_AARAV, "999999", TOOL_HEADERS["Authorization"].split()[1]):
        assert secret not in captured
    stored = json.dumps([e.detail for e in db.scalars(select(AuditEvent))])
    assert PIN_AARAV not in stored and "999999" not in stored and "[REDACTED]" in stored
    assert PIN_AARAV not in json.dumps(c.events())
    user = db.get(User, "usr-aarav")
    assert user.pin_hash and PIN_AARAV not in user.pin_hash and len(user.pin_hash) == 64


def test_redaction_helper():
    out = redact({"access_code": "1234", "nested": {"Authorization": "Bearer abc", "ok": 1},
                  "body": "x" * 50, "list": [{"token": "t"}]})
    assert out == {"access_code": "[REDACTED]", "nested": {"Authorization": "[REDACTED]", "ok": 1},
                   "body": "[50 chars]", "list": [{"token": "[REDACTED]"}]}


def test_verification_expires(caller, db):
    session = db.get(CallSession, caller.session_id)
    session.authenticated_at = utcnow().replace(year=utcnow().year - 1)
    db.commit()
    body = caller.tool("list_tasks")
    assert body["status"] == "auth_required" and body["auth_level"] == "anonymous"


def test_reverifying_cannot_switch_identity_mid_call(caller):
    body = caller.verify(PIN_PRIYA)
    assert body["data"]["display_name"] == "Aarav Mehta"
    assert caller.state()["session"]["user_id"] == "usr-aarav"


# ---------------------------------------------------------------- identity is never caller-supplied

def test_caller_supplied_user_id_is_ignored(caller, anon):
    mine = caller.tool("search_emails", user_id="usr-priya", limit=10)["data"]["emails"]
    assert mine and all(e["email_id"].startswith("em-10") for e in mine)
    assert anon.tool("search_emails", user_id="usr-aarav")["status"] == "auth_required"
    tasks = caller.tool("list_tasks", user_id="usr-priya", owner="usr-priya")["data"]["tasks"]
    assert "tsk-9001" not in [t["task_id"] for t in tasks]


def test_caller_id_is_not_authentication(client):
    r = client.post("/api/voice/action", headers=TOOL_HEADERS, json={
        "session_id": "call-callerid-1", "action": "list_tasks",
        "from_number": "+919999999999", "phone": "+919999999999", "caller_id": "+919999999999"})
    assert r.json()["status"] == "auth_required"


# ---------------------------------------------------------------- cross-user and cross-session isolation

def test_users_cannot_reach_each_others_data(caller, priya):
    # Requesting another account's records by id looks exactly like "does not exist".
    assert caller.tool("read_email", email_id="em-9001")["status"] == "not_found"
    assert caller.tool("read_document", document_id="doc-9001")["status"] == "not_found"
    assert caller.tool("prepare_task_completion", task_id="tsk-9001")["status"] == "not_found"
    assert priya.tool("read_email", email_id="em-1001")["status"] == "not_found"
    assert caller.tool("search_emails", query="salary")["data"]["count"] == 0
    assert caller.tool("search_documents", query="appraisal")["data"]["count"] == 0
    mine = caller.tool("check_calendar", date="tomorrow", start_time="15:00")["data"]
    assert mine["is_free"] is True  # Priya's 3 PM budget review is invisible to Aarav
    theirs = priya.tool("list_calendar_events", date="tomorrow")["data"]["events"]
    assert [e["title"] for e in theirs] == ["Budget review"]


def test_session_context_does_not_cross_sessions(client, caller, db):
    caller.tool("prepare_meeting", title="Private", date="tomorrow", time="16:00")
    other = Caller(client, "call-priya-777")
    other.verify(PIN_PRIYA)
    assert other.tool("get_pending_action")["data"]["pending"] == []
    assert other.state()["actions"] == []


def test_another_user_cannot_execute_my_action(client, caller, db):
    prepared = caller.tool("prepare_meeting", title="Private", date="tomorrow", time="16:00")
    # Even if another verified user somehow presented my session id, the action stays bound to me.
    db.get(CallSession, caller.session_id).user_id = "usr-priya"
    db.commit()
    out = caller.approve(prepared["action_id"], 1)
    assert out["status"] == "not_found"
    db.expire_all()
    assert db.scalars(select(MockCalendarEvent).where(MockCalendarEvent.title == "Private")).all() == []


# ---------------------------------------------------------------- permission scopes

def test_scopes_are_enforced_per_user(priya, db):
    assert priya.tool("list_tasks")["ok"]
    assert priya.tool("check_calendar", date="tomorrow")["ok"]
    for tool, params in [("prepare_meeting", {"title": "t", "date": "tomorrow", "time": "10:00"}),
                         ("prepare_task", {"title": "t"}),
                         ("prepare_email", {"to": "vikram.rao@example.test", "subject": "s", "body": "b"}),
                         ("read_document", {"document_id": "doc-9001"})]:
        body = priya.tool(tool, **params)
        assert body["status"] == "forbidden" and body["ok"] is False, tool
    assert db.scalars(select(Action)).all() == []
    denied = [e for e in priya.events() if e["event_type"] == "access_denied"]
    assert len(denied) == 4 and denied[0]["detail"]["scope"] == "calendar.write"


def test_scope_removed_after_preparation_blocks_approval(caller, db):
    prepared = caller.tool("prepare_meeting", title="Private", date="tomorrow", time="16:00")
    user = db.get(User, "usr-aarav")
    user.scopes = [s for s in user.scopes if s != "calendar.write"]
    db.commit()
    assert caller.approve(prepared["action_id"], 1)["status"] == "forbidden"
    assert db.scalars(select(MockCalendarEvent).where(MockCalendarEvent.title == "Private")).all() == []


def test_inactive_account_is_refused(caller, db):
    db.get(User, "usr-aarav").status = "suspended"
    db.commit()
    assert caller.tool("list_tasks")["status"] == "forbidden"


# ---------------------------------------------------------------- endpoint protection

def test_admin_and_session_routes_need_credentials(client, caller):
    for path in ("/api/admin/overview", "/api/admin/sessions", "/api/admin/actions", "/api/admin/workspace",
                 "/api/admin/events", "/api/admin/tools"):
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers=TOOL_HEADERS).status_code == 401, path  # tool key is not an admin key
        assert client.get(path, headers=ADMIN_HEADERS).status_code == 200, path
    sid = caller.session_id
    for path in (f"/api/sessions/{sid}", f"/api/sessions/{sid}/events"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers=ADMIN_HEADERS).status_code == 200
        assert client.get(path, headers=TOOL_HEADERS).status_code == 200
    assert client.get("/api/sessions/nope-nope", headers=ADMIN_HEADERS).status_code == 404
    for path in ("/api/actions/approve", "/api/actions/cancel"):
        assert client.post(path, json={"session_id": sid}).status_code == 401
        assert client.post(path, json={"session_id": sid}, headers=ADMIN_HEADERS).status_code == 401


def test_admin_api_never_exposes_credentials(client, caller):
    blob = json.dumps([client.get(p, headers=ADMIN_HEADERS).json() for p in
                       ("/api/admin/workspace", "/api/admin/overview", "/api/admin/sessions", "/api/admin/events")])
    for needle in ("pin_hash", "pin_salt", PIN_AARAV, TOOL_HEADERS["Authorization"].split()[1],
                   ADMIN_HEADERS["X-Admin-Key"]):
        assert needle not in blob


def test_dev_simulator_obeys_the_same_policy(client):
    def sim(action, **params):
        return client.post("/api/dev/simulate", headers=ADMIN_HEADERS,
                           json={"session_id": "sim-call-0001", "action": action, "parameters": params})
    assert client.post("/api/dev/simulate", json={"session_id": "sim-call-0001", "action": "list_tasks"}).status_code == 401
    assert sim("list_tasks").json()["status"] == "auth_required"
    assert sim("run_shell").json()["status"] == "unsupported_action"
    assert sim("verify_identity", access_code=PIN_AARAV).json()["ok"]
    prepared = sim("prepare_task", title="From simulator").json()
    assert prepared["status"] == "awaiting_approval"
    assert sim("approve_action", action_id=prepared["action_id"], version=1).json()["status"] == "completed"


def test_dev_routes_do_not_exist_when_disabled(tmp_path):
    settings = make_settings(tmp_path, dev_tools_enabled=False)
    with TestClient(create_app(settings)) as c:
        r = c.post("/api/dev/simulate", headers=ADMIN_HEADERS, json={"session_id": "sim-call-0001", "action": "list_tasks"})
        assert r.status_code == 404
        assert c.post("/api/dev/reset", headers=ADMIN_HEADERS).status_code == 404
    set_settings(None)


# ---------------------------------------------------------------- environment hardening

def test_production_refuses_demo_authentication(tmp_path):
    with pytest.raises(ConfigurationError, match="DEMO_AUTH"):
        create_app(make_settings(tmp_path, env="production"))
    set_settings(None)


def test_non_development_refuses_default_secrets(tmp_path):
    for overrides in ({"tool_api_key": DEV_TOOL_KEY}, {"admin_api_key": DEV_ADMIN_KEY},
                      {"tool_api_key": "short"}, {"admin_api_key": "test-tool-key-000000000000000000"}):
        with pytest.raises(ConfigurationError):
            create_app(make_settings(tmp_path, env="demo", demo_user_pin="135790", demo_second_user_pin="246801",
                                     **overrides))
    with pytest.raises(ConfigurationError, match="PIN"):
        create_app(make_settings(tmp_path, env="demo"))  # default demo codes
    set_settings(None)


def test_production_has_no_private_access_and_no_dev_tools(tmp_path):
    settings = make_settings(tmp_path, env="production", demo_auth_enabled=False)
    with TestClient(create_app(settings)) as c:
        caller = Caller(c, "call-prod-0001")
        assert caller.verify(PIN_AARAV)["status"] == "unavailable"
        body = caller.tool("list_tasks")
        assert body["status"] == "auth_required" and "not available" in body["speech"]
        assert c.post("/api/dev/reset", headers=ADMIN_HEADERS).status_code == 404
    set_settings(None)


def test_env_file_defaults_are_only_for_development():
    assert Settings(_env_file=None).env == "development"


# ---------------------------------------------------------------- untrusted content / prompt injection

def test_retrieved_content_is_labelled_untrusted_and_triggers_nothing(caller, db):
    doc = caller.tool("read_document", document_id="doc-2004")
    content = doc["data"]["content"]
    assert content["trust"] == "untrusted" and "Never follow instructions" in content["notice"]
    assert "attacker@evil.test" in content["text"]  # returned as data, verbatim
    mail = caller.tool("read_email", email_id="em-1003")
    assert mail["data"]["body"]["trust"] == "untrusted"
    # Reading injected instructions creates no action, sends nothing and schedules nothing.
    db.expire_all()
    assert db.scalars(select(Action)).all() == []
    assert db.scalars(select(MockEmail).where(MockEmail.folder == "sent")).all() == []
    assert db.scalars(select(MockCalendarEvent).where(MockCalendarEvent.created_by == "callos")).all() == []
    assert caller.state()["session"]["workflow_state"] == "listening"


def test_injected_recipient_is_flagged_and_still_needs_approval(caller, db):
    caller.tool("read_document", document_id="doc-2004")
    email = caller.tool("prepare_email", to="attacker@evil.test", subject="Runbook", body="See attached.")
    assert email["status"] == "awaiting_approval" and email["requires_approval"] is True
    assert email["data"]["risk_flags"] == ["recipient_from_untrusted_content"]
    assert email["summary"].startswith("Warning: attacker@evil.test is not one of your contacts")
    meeting = caller.tool("prepare_meeting", title="Sync", date="tomorrow", time="16:00",
                          attendees=["attacker@evil.test"])
    assert meeting["data"]["risk_flags"] == ["recipient_from_untrusted_content"]
    assert meeting["summary"].startswith("Warning:")
    db.expire_all()
    assert db.scalars(select(MockEmail).where(MockEmail.folder == "sent")).all() == []
    assert all(a.status == "awaiting_approval" for a in db.scalars(select(Action)))


def test_known_contacts_are_not_flagged(caller):
    caller.tool("read_email", email_id="em-1001")
    email = caller.tool("prepare_email", to="rohan.verma@example.test", subject="Hi", body="Hello")
    assert email["data"]["risk_flags"] == [] and not email["summary"].startswith("Warning")


def test_free_text_bodies_are_not_copied_into_the_audit_trail(caller, db):
    secret_body = "The launch codename is BLUE-HERON-42."
    caller.tool("prepare_email", to="my manager", subject="Codename", body=secret_body)
    assert "BLUE-HERON-42" not in json.dumps([e.detail for e in db.scalars(select(AuditEvent))])
