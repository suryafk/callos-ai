from store import store


def _prepare(call, qty=200, sid="t-1"):
    return call("prepare_order", session_id=sid, customer_name="Sharma Traders",
                product_id="mat-001", quantity=qty)


def test_demo_flow_revise_then_approve(call):
    p = _prepare(call)
    r = call("revise_order", action_id=p["action_id"], quantity=250)
    assert r["status"] == "awaiting_approval"
    assert r["action_id"] == p["action_id"]
    assert r["version"] == 2
    assert r["data"]["total_inr"] == 37500

    a = call("approve_order", action_id=r["action_id"], version=2)
    assert a["status"] == "completed"
    assert a["order_id"].startswith("ORD-")
    assert a["data"]["quantity"] == 250


def test_stale_version_rejected(call):
    p = _prepare(call)
    call("revise_order", quantity=250)
    a = call("approve_order", action_id=p["action_id"], version=1)
    assert a["status"] == "rejected"
    assert a["data"]["current_version"] == 2
    assert not store.get("t-1").orders


def test_duplicate_approval_creates_one_order(call):
    p = _prepare(call)
    a1 = call("approve_order", action_id=p["action_id"], version=1)
    a2 = call("approve_order", action_id=p["action_id"], version=1)
    assert a1["order_id"] == a2["order_id"]
    assert len(store.get("t-1").orders) == 1


def test_cancel_then_approve_creates_nothing(call):
    p = _prepare(call)
    c = call("cancel_order")
    assert c["status"] == "cancelled"
    a = call("approve_order", action_id=p["action_id"], version=1)
    assert a["status"] == "rejected"
    assert not store.get("t-1").orders


def test_approval_from_other_session_rejected(call):
    p = _prepare(call, sid="caller-a")
    a = call("approve_order", session_id="caller-b", action_id=p["action_id"], version=1)
    assert a["status"] == "rejected"
    assert not store.get("caller-a").orders


def test_new_prepare_supersedes_old_pending(call):
    p1 = _prepare(call, qty=100)
    p2 = _prepare(call, qty=300)
    a = call("approve_order", action_id=p1["action_id"], version=1)
    assert a["status"] == "rejected"
    a = call("approve_order", action_id=p2["action_id"], version=1)
    assert a["status"] == "completed"


def test_revise_without_pending(call):
    r = call("revise_order", quantity=5)
    assert r["status"] == "rejected"


def test_events_log_supersede_and_single_create(call, client):
    p = _prepare(call)
    call("revise_order", quantity=250)
    call("approve_order", action_id=p["action_id"], version=2)
    call("approve_order", action_id=p["action_id"], version=2)
    events = client.get("/api/sessions/t-1/events").json()
    types = [e["type"] for e in events]
    assert "action_revised" in types
    assert types.count("order_created") == 1
    assert "approval_replayed" in types
