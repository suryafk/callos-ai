def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_unknown_action_blocked(call):
    r = call("delete_all_files")
    assert r["status"] == "rejected"


def test_unauthenticated_write_blocked(call):
    from store import store
    store.get_or_create("anon").authenticated = False
    r = call("prepare_order", session_id="anon", customer_name="Sharma", product_id="mat-001", quantity=1)
    assert r["status"] == "rejected"
    # Read-only still allowed
    assert call("list_products", session_id="anon")["status"] == "ok"


def test_flat_payload_accepted(client):
    r = client.post("/api/voice/action", json={"action": "calculate_quote", "product_id": "mat-001", "quantity": 2})
    assert r.json()["data"]["total_inr"] == 300


def test_missing_session_uses_demo_session(client):
    client.post("/api/voice/action", json={"action": "list_products"})
    assert client.get("/api/sessions/call-demo-001").status_code == 200


def test_invalid_params_give_spoken_error(call):
    r = call("approve_order", action_id="act-1")  # missing version
    assert r["status"] == "needs_input"
    assert "version" in r["spoken_summary"]


def test_garbage_body_is_speakable(client):
    r = client.post("/api/voice/action", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 200
    assert r.json()["status"] == "error"


def test_api_key_enforced(monkeypatch, client):
    import main
    monkeypatch.setattr(main, "API_KEY", "secret")
    assert client.post("/api/voice/action", json={"action": "list_products"}).status_code == 401
    r = client.post("/api/voice/action", json={"action": "list_products"}, headers={"X-CallOS-Key": "secret"})
    assert r.status_code == 200
