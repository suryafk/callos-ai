from tests.conftest import TOOL_HEADERS


def test_health_reports_ok_and_database(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["database"] == "ok"
    assert body["integration_mode"] == "mock"
    assert "X-Response-Time-Ms" in r.headers


def test_health_needs_no_credentials_and_leaks_no_secrets(client, settings):
    text = client.get("/health").text
    assert settings.tool_api_key not in text and settings.admin_api_key not in text


def test_openapi_documents_required_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path in ["/health", "/api/voice/action", "/api/sessions/{session_id}",
                 "/api/sessions/{session_id}/events", "/api/actions/approve", "/api/actions/cancel"]:
        assert path in paths, path
    assert client.get("/docs").status_code == 200


def test_correlation_id_is_echoed_and_generated(client):
    r = client.get("/health", headers={"X-Correlation-ID": "trace-abc-123"})
    assert r.headers["X-Correlation-ID"] == "trace-abc-123"
    assert len(client.get("/health").headers["X-Correlation-ID"]) >= 8


def test_correlation_id_reaches_body_and_audit_trail(client):
    r = client.post("/api/voice/action", headers={**TOOL_HEADERS, "X-Correlation-ID": "trace-xyz-789"},
                    json={"session_id": "call-corr-001", "action": "list_tasks"})
    assert r.json()["correlation_id"] == "trace-xyz-789"
    events = client.get("/api/sessions/call-corr-001/events", headers=TOOL_HEADERS).json()["events"]
    assert any(e["correlation_id"] == "trace-xyz-789" and e["event_type"] == "tool_call" for e in events)


def test_unknown_route_uses_error_envelope(client):
    r = client.get("/api/nope")
    assert r.status_code == 404
    body = r.json()
    assert body["ok"] is False and body["error"]["code"] == "not_found" and body["correlation_id"]
