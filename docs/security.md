# Security model and limitations

This is an MVP. The controls below are implemented and tested; the limitations at the end are real and must be addressed before real accounts are connected.

## Three levels of access

| Level | What the caller can do | What is required |
|---|---|---|
| Anonymous | General AI conversation (handled by the voice agent) | Nothing. No account, no backend state |
| Verified | Read their own email, calendar, documents and tasks | A verified session **and** the read scope for that service |
| Approved write | Create a meeting or task, send an email, complete a task | Verified session, the write scope, **and** explicit approval of the exact version |

## Controls

**Tool endpoints.** `/api/voice/*` and `/api/actions/*` require `Authorization: Bearer <CALLOS_TOOL_API_KEY>`, compared in constant time. Admin routes use a separate key; the tool key does not open admin routes and vice versa. Outside local development the server refuses to start with default, short or identical keys.

**Allowlist.** Only tools registered in `tool_registry.py` run. Anything else returns `unsupported_action` and is audited. There is no tool for shell commands, file access, browsing, payments or deletion.

**Identity is never caller-supplied.** The user is the one bound to the session by server-side verification. `user_id`, account names and phone numbers in a request are ignored. Caller ID is not used at all.

**Scopes.** Each tool declares a scope (`calendar.read`, `calendar.write`, `email.read`, `email.send`, `documents.read`, `tasks.read`, `tasks.write`). The policy engine checks it on every call, and again at approval time, so a permission removed after an action was prepared still blocks execution.

**Isolation.** Every query filters by the verified user. Another user's record, and another session's action, are indistinguishable from "not found". Actions are bound to both the session and the user that prepared them.

**Approval.** Writes run only through `/api/actions/approve` with the action ID and current version. Changing an action increments the version and invalidates earlier approvals. Execution is claimed atomically, so an action runs at most once. Actions expire (default 15 minutes).

**Secrets.** Demo access codes are stored as salted PBKDF2-SHA256 hashes. Access codes, tokens and Authorization values are redacted before logging and auditing. Email bodies and task notes are stored in the audit trail only as a length. The admin API never returns credential fields. The dashboard keeps the admin key in `sessionStorage` for the current tab only; it is not built into the bundle.

**Untrusted content.** Text from emails and documents is returned in a labelled wrapper (`trust: "untrusted"` plus a notice) and the system prompt tells the model never to follow it. The backend does not rely on the model for this: reading content can never create or approve an action, and every write still needs the caller's approval. As an extra warning, if an email recipient or meeting invitee is not one of the user's contacts and its address appeared inside content read during the call, the server puts a spoken warning at the start of the approval summary and sets `risk_flags`.

**Verification attempts.** Five wrong codes lock verification for that call; twenty failures across all calls in fifteen minutes pause verification globally. Verification lapses after 60 minutes.

## The demo verification mechanism is not production authentication

A caller is verified by saying a six-digit access code (`verify_identity`). This exists only so the Act-with-AI flow can be demonstrated. Its weaknesses:

- The code is spoken aloud and passes through speech recognition, the voice model and, depending on Bolna settings, the call transcript and recordings.
- The code alone identifies the user; there is no second factor and no enrolment flow.
- Six digits is a small space; only the attempt limits stand between a guesser and an account.

It is enabled only when `CALLOS_DEMO_AUTH_ENABLED=true`, and the server refuses to start with it enabled when `CALLOS_ENV=production`. In production mode private tools therefore answer "not available". Real deployments need account linking through a trusted channel, proper verification (for example an out-of-band confirmation or keypad entry that bypasses the transcript), and OAuth tokens stored encrypted per user.

## Known limitations

- **The session ID is trusted from the tool caller.** Anyone holding the tool key can address any session ID. This is acceptable only because the tool key is a server-to-server secret held by Bolna. If the voice model were tricked into sending a different call ID it could reach another verified session; the tool definitions rely on Bolna's `{call_sid}` variable rather than model-chosen values to prevent this. Verify on a real call that `call_sid` is filled by Bolna.
- **Approval is as strong as the model's honesty about what the caller said.** The backend guarantees *which version* runs and that it runs once; it cannot hear the caller. A model that calls `approve_action` without a real "yes" would execute the action. The prompt forbids this, and the summary returned on `stale_version` tells the model to re-confirm, but there is no server-side proof of consent. A stronger design is a keypad (DTMF) confirmation delivered to the backend by the telephony layer.
- **No rate limiting** on tool endpoints beyond verification attempts. Add it at the reverse proxy or platform.
- **Single shared tool key**, no rotation mechanism, no IP allowlist. Bolna publishes its source IPs; restricting to them at the proxy is a cheap improvement.
- **No encryption at rest** for the database; no retention policy for sessions and audit events.
- **Admin dashboard** uses one shared key and no user accounts. Do not expose it publicly without additional protection.
- **Mock data only.** No real third-party tokens are stored, so token handling is designed but not exercised.
- Prompt injection defences reduce risk; they do not eliminate it. The approval step is the control that matters.
