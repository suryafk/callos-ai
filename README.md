# CallOS AI

**One phone number. Ask anything. Get authorized things done.**

Built for *Build Out Loud — Wispr Flow × Bolna Hackathon* (15 Nov 2026). A Bolna voice agent answers general questions and, through a single custom tool, calls this FastAPI backend to quote, draft, revise, approve and cancel wholesale orders — safely. See [context.md](context.md) for the full spec.

```
Phone → Bolna (STT + LLM + TTS) → callos_action tool → FastAPI backend
                                                        ├─ policy (allowlist, auth)
                                                        ├─ orchestrator (state machine, versions, idempotency)
                                                        ├─ catalog (data/*.json)
                                                        └─ store + audit events (in-memory)
```

## Layout

| Path | What |
|---|---|
| `backend/main.py` | FastAPI app: `POST /api/voice/action`, `GET /api/health`, session/event inspection |
| `backend/orchestrator.py` | Dispatcher + order state machine |
| `backend/policy.py` | Action allowlist and auth checks |
| `backend/store.py` | In-memory sessions, events, idempotency |
| `backend/catalog.py` | Loads `data/products.json`, `data/customers.json` |
| `backend/schemas.py` | Pydantic models |
| `backend/tests/` | pytest suite (orders, approval, dispatch) |
| `prompts/` | Bolna system prompt + tool schema |
| `demo/` | Demo script, test-call log, pitch |

## Run locally

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q
uvicorn main:app --reload --port 8000
```

Expose to Bolna over HTTPS (e.g. `cloudflared tunnel --url http://localhost:8000` or `ngrok http 8000`), then set the tool URL to `https://<host>/api/voice/action`.

### Environment

| Var | Default | Purpose |
|---|---|---|
| `CALLOS_API_KEY` | *(unset = open)* | Required `X-CallOS-Key` header value. Set it in Bolna's tool headers. |
| `CALLOS_DEMO_SESSION_ID` | `call-demo-001` | Session used when the tool payload has no `session_id`. |
| `CALLOS_EXPOSE_SESSIONS` | `1` | Set `0` to hide `/api/sessions*` outside the demo. |

## API

`POST /api/voice/action`

```json
{ "session_id": "call-demo-001", "action": "prepare_order",
  "parameters": { "customer_name": "Sharma Traders", "product_id": "mat-001", "quantity": 200 } }
```

→

```json
{ "status": "awaiting_approval", "action_id": "act-201", "version": 1, "requires_approval": true,
  "spoken_summary": "Draft order for Sharma Traders: 200 Floor Mats at 150 rupees each, total 30,000 rupees before taxes and delivery charges. Shall I create it?" }
```

Actions: `list_products`, `calculate_quote`, `prepare_order`, `revise_order`, `approve_order` (needs `action_id` + `version`), `cancel_order`, `get_order_status`. Flat payloads (`{"action": ..., "quantity": ...}`) are also accepted. Responses always contain a speakable `spoken_summary`, even on errors.

## Safety guarantees (enforced server-side)

- Prices and totals come from the catalog; LLM-supplied prices are ignored.
- Revisions bump the version; approving an old version is rejected.
- Approval is idempotent — the same approval twice creates one order.
- Cancelled/superseded drafts never execute; approvals are bound to the session.
- Unknown actions are blocked.

## Bolna setup

1. System prompt: [prompts/bolna_system_prompt.md](prompts/bolna_system_prompt.md)
2. Custom tool: [prompts/tool_schema.json](prompts/tool_schema.json) — confirm field names against your Bolna workspace.
3. Greeting: "Hello, I'm CallOS. You can ask me questions or ask me to perform permitted tasks. How can I help?"

## Mocked / limitations (disclose in demo)

Catalog, customers and orders are mock data. Every session is pre-authorized as the demo business user (caller ID is not authentication). State is in memory and resets on restart. If Bolna doesn't pass a stable call ID, all calls share `CALLOS_DEMO_SESSION_ID`.
