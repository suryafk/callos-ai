# Bolna setup guide

The agent `CallOS AI` already exists in the Bolna account (ID `326ca6aa-b7b2-4d6b-ba26-f7e4d63aac93`) and can answer general questions. This guide covers testing it, attaching the backend tools, and assigning a phone number.

## Step 1 — Try Ask AI now (no backend needed)

1. Open https://platform.bolna.ai and select the agent **CallOS AI**.
2. Use the test options next to **Save agent**: **Chat with agent** (text) for quick checks, **Web Call** to talk in the browser, or **Get a call from agent** for a real phone call. Calls use account balance.
3. Run scenarios A1–A4 in [test_scenarios.md](test_scenarios.md).

If you ask for your calendar at this stage the agent should say that capability is not connected, because no tools are attached.

## Step 2 — Give the backend a public HTTPS URL

Follow [docs/deployment.md](../docs/deployment.md) section 4 (a tunnel for a quick demo, or a container host). Use `CALLOS_ENV=demo` with real keys. Check:

```bash
curl https://<your-backend-host>/health
```

```bash
cd backend && .venv/bin/python scripts/simulate_call.py --base-url https://<your-backend-host> --tool-key "<CALLOS_TOOL_API_KEY>" --pin <demo code> --scenario all
```

The second command proves the public URL, the key and the whole tool contract before Bolna is involved.

## Step 3 — Build the tool configuration

```bash
python3 bolna/build_agent_payload.py --base-url https://<your-backend-host> --tool-key "<CALLOS_TOOL_API_KEY>"
```

Output (in `bolna/out/`, git-ignored because it contains the key):

- `agent_payload.json` — the full agent body for the Bolna API
- `dashboard_tools.json` — an array with one custom-function JSON per tool

Add `--include-optional` for `prepare_email`, `prepare_task_completion` and `get_pending_action`. Start without them: fewer tools means more reliable tool selection.

## Step 4 — Attach the tools (pick one way)

**A. Bolna API**, using your own key from the Bolna dashboard:

```bash
BOLNA_API_KEY=<your key> python3 bolna/build_agent_payload.py --base-url https://<your-backend-host> --tool-key "<CALLOS_TOOL_API_KEY>" --apply --agent-id 326ca6aa-b7b2-4d6b-ba26-f7e4d63aac93
```

This sends `PUT /v2/agent/{id}` with the full configuration (prompt, voices and tools).

**B. Bolna dashboard:**

1. Open the agent → **Tools** tab → **Add a Custom Tool** → **Write manually**.
2. Paste one object from `dashboard_tools.json`, submit, and repeat for each tool. Add them in this order and test as you go: `verify_identity`, `check_calendar`, `list_calendar_events`, `prepare_meeting`, `update_pending_action`, `approve_action`, `cancel_action`, then the email, document and task tools.
3. Save the agent.

**C. Through Claude:** not available for tools. The Bolna connector's update is a partial update (name, welcome message, voice, prompt) and cannot change tools, and passing the tool key through the assistant is deliberately avoided.

Do not paste the tool key into chats, tickets or commits.

## Step 5 — Check the first tool call

1. Start a **Web Call** or phone call and say: "Check my calendar for tomorrow afternoon."
2. Expected: the agent asks for your access code. Say it. The agent then reads tomorrow afternoon's meetings and free slots.
3. In the CallOS dashboard, **Sessions** should show a new session whose ID is the call's ID, becoming *authenticated*, with `check_calendar` in its audit trail.

If it does not work:

| Symptom | Likely cause | Fix |
|---|---|---|
| No request in the backend log | Tool not triggered, or URL unreachable | Check the tool is saved on the agent; `curl` the URL from outside your network |
| Backend log shows 401 | Credential not sent as expected | Check `api_token` is `Bearer <key>`; otherwise put it in `headers.Authorization` (uncertainty 5 in [agent_configuration.md](agent_configuration.md)) |
| `invalid_request` about the session id | `{call_sid}` not substituted in this test mode | Test with a real phone call; for local development only, set `CALLOS_DEV_FALLBACK_SESSION_ID` |
| Agent says "done" but nothing changed | Prompt not followed | Check the backend audit trail for the real result and tighten the prompt; the backend never executes without `approve_action` |

## Step 6 — Run the call tests

Work through [test_scenarios.md](test_scenarios.md) and record the results in [docs/implementation_status.md](../docs/implementation_status.md). Only tests you actually performed on a call count as telephony results.

## Step 7 — Assign a phone number (optional)

In the agent's **Calling** tab, turn on **Inbound Calling** and choose a number from your Bolna account or a connected telephony provider. Buying or renting a number costs money and is your decision; it has not been done. Match the agent's telephony provider to the number's provider. Until a number is assigned, use **Web Call** or **Get a call from agent**, and describe the demo accordingly.

## Step 8 — Keep an eye on

- Account balance and per-minute pricing in the Bolna dashboard.
- Call recordings and transcripts: the spoken access code will appear in them. Treat it as a demo secret and rotate it (`CALLOS_DEMO_USER_PIN`, then reseed) after public demos.
