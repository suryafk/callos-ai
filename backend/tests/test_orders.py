def test_profit_calculation(call):
    r = call("calculate_quote", quantity=200, unit_cost_inr=120, unit_sell_inr=150)
    assert r["status"] == "ok"
    assert r["data"]["gross_profit_inr"] == 6000
    assert r["data"]["markup_pct"] == 25.0
    assert r["data"]["margin_pct"] == 20.0


def test_catalog_quote(call):
    r = call("calculate_quote", product_name="mats", quantity=200)
    assert r["data"]["total_inr"] == 30000


def test_prepare_order_server_side_total(call):
    r = call("prepare_order", customer_name="Sharma Traders", product_id="mat-001", quantity=200)
    assert r["status"] == "awaiting_approval"
    assert r["requires_approval"] is True
    assert r["version"] == 1
    assert r["data"]["total_inr"] == 30000


def test_llm_supplied_price_is_ignored(call):
    r = call("prepare_order", customer_name="Sharma", product_name="mat", quantity=10,
             unit_price_inr=1, total_inr=10)
    assert r["data"]["unit_price_inr"] == 150
    assert r["data"]["total_inr"] == 1500


def test_missing_customer_asks(call):
    r = call("prepare_order", product_id="mat-001", quantity=5)
    assert r["status"] == "needs_input"
    assert "customer" in r["data"]["missing"]


def test_unknown_product_rejected_with_alternatives(call):
    r = call("prepare_order", customer_name="Sharma Traders", product_name="laptops", quantity=5)
    assert r["status"] == "rejected"
    assert "Floor Mat" in r["spoken_summary"]


def test_unknown_customer_rejected(call):
    r = call("prepare_order", customer_name="Nobody Ltd", product_id="mat-001", quantity=5)
    assert r["status"] == "rejected"


def test_inventory_limit(call):
    r = call("prepare_order", customer_name="Sharma Traders", product_id="mat-001", quantity=5000)
    assert r["status"] == "rejected"


def test_order_status_after_create(call):
    p = call("prepare_order", customer_name="Sharma Traders", product_id="mat-001", quantity=10)
    a = call("approve_order", action_id=p["action_id"], version=p["version"])
    s = call("get_order_status", order_id=a["order_id"])
    assert s["order_id"] == a["order_id"]
