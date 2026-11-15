# Architecture

CallOS is a modular monolith: one FastAPI service, one database, one small React dashboard. Bolna provides the phone call, speech recognition, the conversational model and speech synthesis.

## Who does what

| Component | Responsible for | Not responsible for |
|---|---|---|
| Telephony provider + Bolna | Answering the call, speech-to-text, the LLM conversation, text-to-speech, interruptions, choosing which tool to request, transcripts | Authorization, deciding whether a write may run, storing workspace data |
| CallOS backend | Tool credential check, tool allowlist, sessions, caller verification, permission scopes, pending actions, approval, execution, verification, audit log | Speech, general-knowledge answers |
| Integration adapters | Reading and writing one service (email, calendar, documents, tasks) for one user | Policy decisions |
| Dashboard | Showing sessions, actions, the audit trail and the mock workspace; development-only tool simulator | Anything a caller depends on |

General questions never reach the backend: there is no tool for them, so Ask AI adds no backend latency and creates no backend state.

## Request path for one tool call

`app/core/orchestrator.py::dispatch` is the only way a tool runs (the voice endpoints, the approval endpoints and the dev simulator all call it):

1. **Credential** — the route dependency checks `Authorization: Bearer <tool key>` (constant-time compare). Failure is HTTP 401.
2. **Clean input** — empty values and unsubstituted template placeholders such as `%(time)s` are dropped.
3. **Session** — the call ID (Bolna's `call_sid`) identifies the session; it is created on first use. A missing or malformed ID is rejected.
4. **Allowlist** — the action must exist in `tool_registry.REGISTRY`. `approve_action` is additionally refused unless the request came through `/api/actions/approve`.
5. **Authorization** — `policy_engine.check_tool_access`: the session must be verified and unexpired, the user active, and the user must hold the tool's scope.
6. **Validation** — the tool's Pydantic parameter model (lenient about numeric strings, strict about ranges and required fields).
7. **Execution** — the tool handler runs. Handled problems raise `ToolError` (a speakable status); anything unexpected is caught, rolled back and reported as `failed` without leaking internals.
8. **State + audit** — the workflow state is settled, an audit event with the redacted parameters and the measured duration is written, and a structured log line is emitted with the correlation ID.

Tool-level outcomes return HTTP 200 with `ok: false` and a `speech` string, because the voice agent needs something accurate to say. Only bad credentials (401) and malformed bodies (422) use HTTP errors.

## Workflow state machine

Session states: `listening`, `understanding`, `needs_auth`, `gathering_data`, `planning`, `awaiting_approval`, `executing`, `completed`, `failed`, `cancelled`.

```
listening ─▶ understanding ─┬─▶ needs_auth                         (private tool, caller not verified)
                            ├─▶ gathering_data ─▶ listening        (read tools)
                            ├─▶ planning ─▶ awaiting_approval      (prepare / update tools)
                            ├─▶ executing ─▶ completed | failed    (approval)
                            └─▶ cancelled                          (cancel)
every state ─▶ understanding                                        (the next request can always arrive)
```

Transitions are validated against a table (`workflow_engine.TRANSITIONS`) and each one is written to the audit trail.

## Pending actions

A write is an `Action` row: `type`, `payload`, `summary`, `version`, `status`, `expires_at`, `idempotency_key`, `steps`, `result`.

Action statuses: `awaiting_approval` → `executing` → `completed` | `failed` | `partially_completed` | `unknown_outcome`; or `cancelled` / `expired`.

- **Prepare** validates everything up front (dates, attendees, conflicts) and stores the action. Nothing external changes.
- **Update** rebuilds the payload from the stored inputs plus the changes. If the rebuild is refused (for example a time conflict) the action is left untouched. Otherwise the version increases, the expiry resets and every approval of an earlier version is marked invalid.
- **Approve** requires the action ID and the exact current version. Then, in order:
  1. An `Approval` row is recorded (unique per action + version).
  2. Execution is *claimed* with a single conditional update: `UPDATE actions SET status='executing' WHERE id=? AND version=? AND status IN ('awaiting_approval','unknown_outcome')`. Exactly one request can win, so concurrent or repeated approvals cannot execute twice.
  3. The claim is committed **before** any external call. External services are not assumed to share the database transaction.
  4. Steps run in order with idempotency keys (`<action>:v<version>:<step>`). The adapter rejects a second write with the same key.
  5. Each step reads its effect back before reporting success.
  6. The outcome is stored and returned. A repeated approval of a finished action returns the stored result.
- **Uncertain outcomes** — if a step times out, the engine looks for the effect by idempotency key. Found: the step counts as done. Not found: `failed`, nothing was created. Lookup also failing: `unknown_outcome`, reported as *not confirmed*; approving again retries safely with the same key.
- **Multi-step actions** — creating a meeting with invitees is two dependent steps (create event, then email invitations using the new event's ID). If the second fails the action is `partially_completed` and the caller is told exactly which part happened.

## Data model

| Table | Purpose |
|---|---|
| `users` | Demo users, scopes, spoken aliases ("my manager"), hashed demo access code |
| `call_sessions` | One row per call: verified user, auth level, workflow state, small context |
| `actions`, `approvals` | Pending/executed writes and the approval of a specific version |
| `audit_events` | Append-only trail: tool calls, state changes, denials, approvals, executions |
| `mock_emails`, `mock_calendar_events`, `mock_documents`, `mock_tasks` | The simulated workspace, every row owned by one user |

Timestamps are stored as UTC. Relative dates ("tomorrow", "friday") are resolved on the server in the user's timezone. The schema uses only portable column types and is tested on SQLite and PostgreSQL 16. Tables are created at startup; there is no migration tool yet (add Alembic before the schema needs to change in a deployed database).

## Integrations

`app/integrations/base.py` defines one interface per service. The mock adapters implement them against the database; writes commit immediately to behave like an external system. `app/integrations/google/` marks where real adapters go and refuses to run. Adding a real provider means implementing the interface (including `find_by_key` for reconciliation), mapping its errors to `AdapterResult`, and returning `execution_mode="live"`.

## Extension point: desktop companion (not built)

Remote computer control is out of scope. If it is added later it should follow the same pattern rather than a new path: a separately installed, separately authenticated companion registers as another adapter set; its operations are added to the allowlist as *prepare* tools with their own scopes; and every operation goes through the existing pending-action → approval → execute-once flow. No endpoint for this exists today.

## Observability

- Every response carries `X-Correlation-ID` (accepted from the request or generated) and `X-Response-Time-Ms`; the correlation ID is also in the response body, each log line and each audit event.
- Logs are JSON on stdout. Secrets and access codes are redacted before logging; email bodies and notes are recorded only as a length.
- The dashboard overview shows the median and p95 backend processing time per tool call, computed from the audit trail.
