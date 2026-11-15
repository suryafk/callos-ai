# CallOS AI

**One phone call. AI for everyone. Actions when you need them.**

CallOS is a voice AI assistant reached by an ordinary phone call. In one conversation a caller can

- **Ask AI** — ask general questions, get explanations, tutoring, calculations and translations, in English, Hindi or Hinglish, with no app and no account; and
- **Act with AI** — once verified, check email, calendar, documents and tasks, and have changes (a meeting, a task, an email) prepared, read back, approved and carried out.

The caller never switches modes. The voice agent (Bolna) answers general questions itself and calls this backend only when it needs the caller's data or an action.

```
Phone ─▶ telephony ─▶ Bolna voice agent (speech-to-text · LLM · text-to-speech)
                          │  general question ─▶ answered by the model
                          │  data / action    ─▶ HTTPS tool call
                          ▼
                    CallOS backend (FastAPI)
                    credential check ▸ tool allowlist ▸ session + identity ▸ permission scopes
                    ▸ pending action (versioned) ▸ explicit approval ▸ execute once ▸ verify ▸ audit
                          ▼
                    Mock email · calendar · documents · tasks   (persistent, per user)
```

## What is real and what is simulated

| Area | Status |
|---|---|
| Backend, workflow engine, approvals, security rules, audit trail | Working, 135 automated tests (SQLite and PostgreSQL 16) |
| Admin dashboard | Working |
| Email / calendar / documents / tasks | **Mock** — real persisted data in the CallOS database, not a real Google or Microsoft account. Marked `execution_mode: "mock"` in every response and "MOCK" in the dashboard |
| Bolna agent | Created in the Bolna account (Ask AI only). Tools are **not attached yet** because the backend has no public HTTPS URL |
| Phone calls | **Not tested.** No call has been placed or received |
| Caller verification | A spoken demo access code — **not production authentication** |

Full detail: [docs/implementation_status.md](docs/implementation_status.md).

## Run it locally

Needs Python 3.11+ and Node 20+ (tested with Python 3.13 locally and 3.12 in Docker, Node 26 locally and 22 in Docker).

```bash
make setup
```

```bash
make backend
```

```bash
make frontend
```

- API: http://localhost:8787 — interactive docs at http://localhost:8787/docs
- Dashboard: http://localhost:5174 — sign in with the admin key (`dev-admin-key-change-me` in local development)

With the backend running, play the demo scenarios as scripted tool calls:

```bash
make simulate
```

Run the tests:

```bash
make test
```

Or run everything in Docker:

```bash
docker compose up --build -d
```

Local development works with no `.env`. To change settings, copy `.env.example` to `.env`. Ports are set with `BACKEND_PORT` / `FRONTEND_PORT` (defaults 8787 / 5174).

### Try the main flow by hand

```bash
curl -s localhost:8787/api/voice/action -H "Authorization: Bearer dev-tool-key-change-me" -H "Content-Type: application/json" -d '{"session_id":"call-demo-001","action":"verify_identity","parameters":{"access_code":"482916"}}'
```

```bash
curl -s localhost:8787/api/voice/action -H "Authorization: Bearer dev-tool-key-change-me" -H "Content-Type: application/json" -d '{"session_id":"call-demo-001","action":"prepare_meeting","parameters":{"title":"Project retrospective","date":"tomorrow","time":"16:00"}}'
```

The second response contains an `action_id` and `version`. Nothing is on the calendar until you approve that exact version:

```bash
curl -s localhost:8787/api/actions/approve -H "Authorization: Bearer dev-tool-key-change-me" -H "Content-Type: application/json" -d '{"session_id":"call-demo-001","action_id":"<action_id>","version":1}'
```

## Repository layout

| Path | Contents |
|---|---|
| `backend/app/api/` | HTTP routes: health, voice tools, approve/cancel, sessions, admin, dev simulator |
| `backend/app/core/` | `orchestrator` (single entry point for tool calls), `tool_registry` (allowlist), `policy_engine` (authorization), `workflow_engine` (state machine, pending actions, approval, execution) |
| `backend/app/services/` | Email, calendar, document, task and demo-verification logic |
| `backend/app/integrations/` | Adapter interfaces, the mock adapters, and the (unimplemented) Google extension point |
| `backend/app/seed/` | Demo workspace data |
| `backend/tests/` | Automated tests, including the Bolna contract test and scenarios A–E |
| `backend/scripts/simulate_call.py` | Local tool-call simulator |
| `bolna/` | System prompt, tool definitions, agent configuration, setup guide, call test scenarios, payload builder |
| `frontend/` | React + TypeScript + Vite + Tailwind admin dashboard |
| `docs/` | Architecture, API reference, security, deployment, demo script, implementation status |

## Connecting the phone side

1. Deploy the backend to a public HTTPS URL — [docs/deployment.md](docs/deployment.md).
2. Attach the tools to the Bolna agent and run the call tests — [bolna/setup_guide.md](bolna/setup_guide.md).

## Safety rules the backend enforces

These hold whatever the voice model says or is tricked into saying:

- Tool calls need a server-to-server credential; only allowlisted tools run.
- Identity comes from server-side verification, never from the caller's phone number or any ID in the request.
- Each tool needs a permission scope on the verified user; data is always filtered by that user.
- Changes are only *prepared* by tools. They run through one approval endpoint that needs the action ID **and** its current version; editing an action bumps the version and voids earlier approvals.
- An action executes at most once (atomic claim + idempotency keys), and success is reported only after the result is read back.
- Text from emails and documents is returned as labelled, untrusted data. It cannot start an action.

Out of scope by design: operating-system or browser control, shell commands, payments, purchases, banking, file deletion.
