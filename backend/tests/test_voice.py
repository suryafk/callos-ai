"""Tool endpoint: credentials, input validation, routing and the allowlist."""
from sqlalchemy import select

from app.models import AuditEvent
from tests.conftest import TOOL_HEADERS, Caller


def post(client, body, headers=TOOL_HEADERS, path="/api/voice/action"):
    return client.post(path, json=body, headers=headers)


def test_missing_or_wrong_tool_credential_is_rejected(client):
    body = {"session_id": "call-x-0001", "action": "list_tasks"}
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic abc"},
                    {"X-Admin-Key": "test-admin-key-00000000000000000"}):
        r = post(client, body, headers)
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "unauthorized"


def test_malformed_body_returns_consistent_422(client):
    r = post(client, {"session_id": "call-x-0001", "action": "list_tasks", "parameters": "not-an-object"})
    assert r.status_code == 422
    body = r.json()
    assert body["ok"] is False and body["error"]["code"] == "validation_error"
    assert body["error"]["details"][0]["field"].endswith("parameters")
    r = client.post("/api/voice/action", content="{not json", headers={**TOOL_HEADERS,
                                                                        "Content-Type": "application/json"})
    assert r.status_code == 422


def test_unknown_action_is_rejected_safely_and_audited(client, db):
    r = post(client, {"session_id": "call-x-0001", "action": "run_shell", "parameters": {"cmd": "rm -rf /"}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and body["status"] == "unsupported_action"
    assert "run_shell" not in body["data"]["supported_actions"]
    rejected = db.scalars(select(AuditEvent).where(AuditEvent.event_type == "tool_rejected")).all()
    assert [e.tool for e in rejected] == ["run_shell"]


def test_missing_action_is_rejected(client):
    body = post(client, {"session_id": "call-x-0001"}).json()
    assert body["status"] == "unsupported_action" and body["ok"] is False


def test_approve_cannot_go_through_generic_dispatcher(caller):
    prepared = caller.tool("prepare_task", title="Review the deployment")
    body = caller.tool("approve_action", action_id=prepared["action_id"], version=1)
    assert body["status"] == "unsupported_action"
    assert body["data"]["use_endpoint"] == "/api/actions/approve"
    assert caller.state()["pending_actions"][0]["status"] == "awaiting_approval"


def test_missing_or_placeholder_session_id_is_rejected(client):
    for sid in (None, "", "%(call_sid)s", "{call_sid}", "ab", "has spaces in it", "x" * 200):
        payload = {"action": "list_tasks"}
        if sid is not None:
            payload["session_id"] = sid
        r = post(client, payload)
        assert r.status_code in (200, 422)
        if r.status_code == 200:
            assert r.json()["status"] == "invalid_request", sid


def test_flat_payload_and_call_sid_alias_are_accepted(client):
    Caller(client, "CA1234567890abcdef").verify()
    r = post(client, {"call_sid": "CA1234567890abcdef", "action": "check_calendar",
                      "date": "tomorrow", "part_of_day": "afternoon"})
    body = r.json()
    assert body["ok"] and body["session_id"] == "CA1234567890abcdef"
    assert body["data"]["events"][0]["title"] == "Design review"


def test_tool_path_endpoint_routes_like_the_generic_one(client):
    Caller(client, "call-path-001").verify()
    r = post(client, {"call_sid": "call-path-001", "status": "open"}, path="/api/voice/tools/list_tasks")
    assert r.status_code == 200 and r.json()["action"] == "list_tasks" and r.json()["data"]["count"] == 3
    r = post(client, {"call_sid": "call-path-001"}, path="/api/voice/tools/format_disk")
    assert r.json()["status"] == "unsupported_action"
    assert post(client, {"call_sid": "call-path-001"}, headers={}, path="/api/voice/tools/list_tasks").status_code == 401


def test_unsubstituted_placeholders_and_blank_values_are_ignored(caller):
    body = caller.tool("check_calendar", date="tomorrow", part_of_day="%(part_of_day)s", start_time="",
                       end_time="null")
    assert body["ok"], body
    assert len(body["data"]["events"]) == 2  # whole working day, no part_of_day filter


def test_numeric_strings_are_coerced(caller):
    body = caller.tool("prepare_meeting", title="Sync", date="tomorrow", time="16:00", duration_minutes="45")
    assert body["status"] == "awaiting_approval"
    assert body["data"]["details"]["duration_minutes"] == 45


def test_invalid_tool_arguments_get_a_speakable_error(caller):
    body = caller.tool("prepare_meeting", date="tomorrow", time="16:00")
    assert body["status"] == "invalid_request" and "title" in body["speech"]
    body = caller.tool("prepare_meeting", title="Sync", date="tomorrow", time="16:00", duration_minutes=5000)
    assert body["status"] == "invalid_request"
    body = caller.tool("prepare_meeting", title="Sync", date="the day of the party", time="16:00")
    assert body["status"] == "invalid_request" and "date" in body["speech"]
    body = caller.tool("prepare_meeting", title="Sync", date="tomorrow", time="4")
    assert body["status"] == "invalid_request" and "AM or" in body["speech"]
    assert caller.state()["actions"] == []


def test_responses_are_concise_and_marked_mock(caller):
    body = caller.tool("check_calendar", date="tomorrow", part_of_day="afternoon")
    assert body["execution_mode"] == "mock"
    assert len(body["speech"]) < 400
    assert set(body) <= {"ok", "status", "action", "speech", "data", "execution_mode", "session_id",
                         "auth_level", "workflow_state", "correlation_id"}


def test_every_tool_call_is_audited_with_duration(caller):
    caller.tool("list_tasks")
    calls = [e for e in caller.events() if e["event_type"] == "tool_call"]
    assert [c["tool"] for c in calls] == ["verify_identity", "list_tasks"]
    assert all(c["duration_ms"] is not None and c["duration_ms"] >= 0 for c in calls)
