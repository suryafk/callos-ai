# API reference

Interactive, always-current documentation is served by the backend at `/docs` (Swagger UI) and `/openapi.json`. This page is the summary.

## Credentials

| Routes | Header |
|---|---|
| `/api/voice/*`, `/api/actions/*` | `Authorization: Bearer <CALLOS_TOOL_API_KEY>` |
| `/api/admin/*`, `/api/dev/*` | `X-Admin-Key: <CALLOS_ADMIN_API_KEY>` |
| `/api/sessions/*` | either of the above |
| `/health` | none |

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness and database check |
| POST | `/api/voice/action` | Run an allowlisted tool; action name in the body |
| POST | `/api/voice/tools/{tool_name}` | Same dispatcher; action name in the path, flat body (used by the Bolna tool definitions) |
| POST | `/api/actions/approve` | Approve and execute the current version of a pending action |
| POST | `/api/actions/cancel` | Cancel a pending action |
| GET | `/api/sessions/{session_id}` | Session status, pending actions, action history |
| GET | `/api/sessions/{session_id}/events` | Audit trail for the session |
| GET | `/api/admin/overview` · `/sessions` · `/actions` · `/events` · `/tools` · `/workspace` | Dashboard data |
| POST | `/api/dev/simulate` · `/api/dev/reset` | Development only (404 unless dev tools are enabled; always off in production) |

## Request shape

```json
{
  "session_id": "call-demo-001",
  "action": "prepare_meeting",
  "parameters": { "title": "Project retrospective", "date": "tomorrow", "time": "16:00", "attendees": ["team"] }
}
```

- `session_id` may also be sent as `call_sid` or `call_id`. It must be 6–128 characters of letters, digits, `.`, `_`, `:` or `-`.
- Tool arguments may be nested under `parameters` or sent flat at the top level. Numbers and booleans may be strings.
- Dates: `today`, `tomorrow`, `day after tomorrow`, a weekday name, `YYYY-MM-DD`, or `16 November`. Times: 24-hour `HH:MM` or `4 pm`. A bare `4` is rejected as ambiguous.
- Unknown extra fields are ignored. In particular any `user_id`, phone number or account name in the request has no effect: identity comes only from the verified session.

## Response shape

```json
{
  "ok": true,
  "status": "awaiting_approval",
  "action": "prepare_meeting",
  "speech": "Create the meeting 'Project retrospective' on Monday, 16 November from 4:00 PM to 4:30 PM IST, with no invitees. Shall I go ahead?",
  "data": { "details": { "title": "Project retrospective", "date": "2026-11-16", "time": "16:00" }, "risk_flags": [] },
  "action_id": "act-3f9c2a17b0",
  "version": 1,
  "requires_approval": true,
  "summary": "Create the meeting 'Project retrospective' on Monday, 16 November from 4:00 PM to 4:30 PM IST, with no invitees.",
  "expires_at": "2026-11-15T09:30:00Z",
  "execution_mode": "mock",
  "session_id": "call-demo-001",
  "auth_level": "authenticated",
  "workflow_state": "awaiting_approval",
  "correlation_id": "4b4d6fc9e1e748a9"
}
```

`speech` is always present and safe to read aloud. Fields that do not apply are omitted.

### Status values

| Status | `ok` | Meaning |
|---|---|---|
| `success` | true | A read or verification succeeded |
| `awaiting_approval` | true | An action was prepared or updated; read `summary` and ask for approval |
| `completed` | true | The action ran and its effect was verified |
| `cancelled` | true | The pending action was cancelled; nothing changed |
| `auth_required` | false | The caller must be verified first |
| `auth_failed`, `locked` | false | Wrong access code / too many attempts |
| `forbidden` | false | The verified user lacks the permission scope, or is inactive |
| `not_found` | false | No such item for this user or this call (also returned for other users' items) |
| `conflict` | false | For example a calendar clash; `data.free_slots` suggests alternatives |
| `needs_clarification` | false | For example an unknown attendee, or more than one pending action |
| `invalid_request` | false | Missing or invalid arguments; `speech` says what is needed |
| `stale_version` | false | The approved version is not the current one; `data` has the current version and summary |
| `action_expired`, `action_cancelled`, `action_failed` | false | The action can no longer be approved |
| `in_progress` | false | Another request is executing this action right now |
| `partially_completed` | false | Some steps ran, a later one failed; `speech` says which |
| `unknown_outcome` | false | The result could not be confirmed; approving again retries safely |
| `failed` | false | The action or tool failed; nothing is reported as done |
| `unsupported_action` | false | Not on the allowlist (or `approve_action` sent to the generic endpoint) |
| `unavailable` | false | Phone verification is switched off on this server |

### HTTP errors

Used only for credentials and malformed requests:

```json
{ "ok": false, "status": "error",
  "error": { "code": "unauthorized", "message": "Missing or invalid tool credential", "details": null },
  "speech": "Sorry, I ran into a technical problem. Please try again.", "correlation_id": "…" }
```

Codes: `unauthorized` (401), `not_found` (404), `validation_error` (422, with `details` listing fields), `internal_error` (500).

## Tools

| Tool | Kind | Scope | Arguments (required in bold) |
|---|---|---|---|
| `verify_identity` | public | — | **access_code** |
| `search_emails` | read | `email.read` | query, sender, unread_only, limit |
| `read_email` | read | `email.read` | **email_id** |
| `prepare_email` | prepare | `email.send` | **to**, **subject**, **body** |
| `list_calendar_events` | read | `calendar.read` | date (default today), end_date |
| `check_calendar` | read | `calendar.read` | date, part_of_day, start_time, end_time, duration_minutes |
| `prepare_meeting` | prepare | `calendar.write` | **title**, **date**, **time**, duration_minutes, attendees, timezone |
| `search_documents` | read | `documents.read` | **query**, limit |
| `read_document` | read | `documents.read` | **document_id** |
| `list_tasks` | read | `tasks.read` | status (`open`, `completed`, `all`) |
| `prepare_task` | prepare | `tasks.write` | **title**, due_date, notes |
| `prepare_task_completion` | prepare | `tasks.write` | task_id or title |
| `get_pending_action` | read | — (verified) | — |
| `update_pending_action` | control | action's scope | action_id (optional if one is pending) plus the fields to change |
| `cancel_action` | control | — (verified) | action_id (optional if one is pending), reason |
| `approve_action` | control | action's scope | **action_id**, **version** — only via `/api/actions/approve` |

Email and document text is returned as `{ "trust": "untrusted", "notice": "…", "text": "…", "truncated": false }`. Email bodies are capped at 1,500 characters and documents at 3,000 so responses stay small enough for a voice model.

## Example: change of mind

```
POST /api/voice/tools/prepare_meeting        {"call_sid":"c1…","title":"Project retrospective","date":"tomorrow","time":"15:00"}
  → status awaiting_approval, action_id act-…, version 1
POST /api/voice/tools/update_pending_action  {"call_sid":"c1…","action_id":"act-…","time":"16:00"}
  → status awaiting_approval, version 2, new summary
POST /api/actions/approve                    {"call_sid":"c1…","action_id":"act-…","version":1}
  → status stale_version (nothing executed)
POST /api/actions/approve                    {"call_sid":"c1…","action_id":"act-…","version":2}
  → status completed, data.steps.create_event.event_id, data.verified true
POST /api/actions/approve                    (same again)
  → status completed, data.already_executed true (nothing executed twice)
```
