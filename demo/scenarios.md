# Demo scenarios

## 90-second demo (Ask → Act → Revise → Approve → Verify)

1. "What is the profit if I buy 200 mats for 120 rupees each and sell them for 150?"
   → `calculate_quote` with cost/sell → ₹6,000 gross profit, 25% markup, 20% margin.
2. "Create a draft order for Sharma Traders for 200 mats."
   → `prepare_order` → act-201 v1, ₹30,000. Agent asks to confirm.
3. "Actually make it 250 mats."
   → `revise_order` → act-201 v2, ₹37,500 at ₹150 (catalog price).
4. "Yes, create the draft."
   → `approve_order` act-201 v2 → ORD-1001 spoken back.
5. Show `GET /api/sessions/<id>/events`: v1 superseded, one `order_created`.

Note: the buy price (₹120) in step 1 is the caller's own number; the order uses the catalog selling price (₹150).

## Test calls (each > 45 s, consented)

- **Call A — accessibility:** explain a concept in English, then Hindi, ask a follow-up.
- **Call B — task:** profit question → draft order → approve → order ID.
- **Call C — adversarial:** change quantity, try approving old version, cancel, ask for an unsupported action ("delete my files").

## Curl smoke test

```bash
H=http://localhost:8000
curl -s $H/api/voice/action -H 'content-type: application/json' -d '{"session_id":"demo","action":"prepare_order","parameters":{"customer_name":"Sharma Traders","product_name":"mats","quantity":200}}'
curl -s $H/api/voice/action -H 'content-type: application/json' -d '{"session_id":"demo","action":"revise_order","parameters":{"quantity":250}}'
curl -s $H/api/voice/action -H 'content-type: application/json' -d '{"session_id":"demo","action":"approve_order","parameters":{"action_id":"act-201","version":2}}'
curl -s $H/api/sessions/demo/events
```
