# Implementation status

Last updated: 15 November 2026. Statuses: **DONE** (built and verified as described), **PARTIAL**, **BLOCKED** (needs something external), **NOT STARTED**.

## Summary

The locally testable MVP is complete: backend, workflow and approval engine, mock workspace, security controls, dashboard, Docker setup, Bolna artifacts and documentation. A Bolna agent exists in the account for Ask AI. What remains needs things outside this repository: a public HTTPS URL for the backend, attaching the tools to the agent, and real calls.

**No phone call, web call or chat with the Bolna agent has been made.** Every result below marked "automated" or "simulated" exercised the backend over HTTP with scripted input; none involved speech recognition, the language model or speech synthesis.

## Phases

| Phase | Status | Evidence / what is missing |
|---|---|---|
| 0 Repository and environment | DONE | `make setup`, `.env.example`, `.gitignore`, Dockerfiles, Compose, README. The earlier wholesale-order prototype was removed (it is still in git history) |
| 1 Bolna voice agent configuration | PARTIAL | Prompt, tool definitions, configuration and setup guide written. Agent `326ca6aa-b7b2-4d6b-ba26-f7e4d63aac93` created through the Bolna connector and confirmed by Bolna (`processed`). Conversation behaviour is **unverified** — no call made |
| 2 FastAPI backend | DONE | All required endpoints; typed schemas; validation; consistent errors; persistence; JSON logs; correlation IDs; allowlist. OpenAPI at `/docs` |
| 3 Mock digital workspace | DONE | Email, calendar, documents, tasks as persistent per-user data behind adapter interfaces; writes are real rows; responses and dashboard marked mock |
| 4 Workflow orchestration | DONE | Ten-state machine; versioned pending actions; approval invalidation; atomic single execution; idempotency keys; multi-step actions; partial failure; timeout reconciliation; expiry; audit trail |
| 5 Authentication and security | DONE for the MVP model | Tool and admin credentials; server-side identity; scopes; isolation; redaction; untrusted-content handling; startup safety checks. Caller verification is a **demo mechanism only** — see [security.md](security.md) |
| 6 Bolna tool integration | PARTIAL | Tool definitions in Bolna's documented format, a contract test and a local simulator are done. `cloudflared` is installed and the backend was reached through a temporary public tunnel in `demo` mode with generated secrets: the acceptance flow passed through the public URL (5 tool calls, median 106 ms round trip). The payload with all 13 tools is built in `bolna/out/`. **Not done:** sending it to Bolna. The connector available to the assistant can only make partial updates (no tools), and the full update needs your `BOLNA_API_KEY` — see [bolna/setup_guide.md](../bolna/setup_guide.md) step 4 |
| 7 Admin dashboard | DONE | Overview, Sessions (with detail and audit trail), Actions, Demo workspace, API testing (development only). Checked in a browser at desktop and phone widths, no console errors |
| 8 Testing and QA | DONE (automated) / NOT STARTED (telephony) | 135 automated tests pass. Call test plan written, not run |
| 9 Deployment preparation | DONE (prepared, not deployed) | Compose stack built and run locally; Render blueprint written but never applied; nothing deployed anywhere |

## Test report

### Automated backend tests

Command: `make test` — **135 passed** (about 20–30 s on SQLite). The same 135 pass against PostgreSQL 16 in a throwaway container (`CALLOS_TEST_DATABASE_URL`, about 59 s).

| File | Tests | Covers |
|---|---|---|
| `test_health.py` | 6 | Health endpoint, OpenAPI contents, correlation IDs, error envelope |
| `test_voice.py` | 13 | Credentials, malformed bodies, unknown actions, session-ID validation, flat and path-style requests, placeholder handling, argument validation, response size, audit |
| `test_workspace.py` | 14 | Email search and read, document search and retrieval, calendar availability and listing, conflict detection, attendee resolution, tasks, writes only after approval, persistence |
| `test_workflows.py` | 22 | State sequence, change of mind, approval invalidation, update conflicts, disambiguation, cancellation, multi-step execution, partial failure, definite failure, timeout before/after the write, unknown outcome and safe retry, crash containment, expiry, persistence across restart |
| `test_approvals.py` | 11 | Nothing written before approval, verified result, repeated approval, **8 concurrent approvals → one execution**, stale versions, missing arguments, unverified and cross-session approval, cancel after execution, late conflict |
| `test_security.py` | 43 | Every private tool refused when anonymous, verification and lockout, global attempt limit, code never logged or audited, expiry, caller-supplied identity ignored, cross-user and cross-session isolation, scopes, endpoint protection, dev routes, production and demo startup checks, untrusted content, injected recipients flagged |
| `test_bolna_contract.py` | 21 | Tool definitions match Bolna's documented schema and the backend allowlist; a full call replayed the way Bolna documents it builds requests; response sizes; payload builder output |
| `test_scenarios.py` | 5 | Scenarios A–E end to end over HTTP |

Required coverage → where: health (`test_health`), input validation and tool routing (`test_voice`), email search / document retrieval / calendar availability / meeting preparation (`test_workspace`), approval / duplicate execution (`test_approvals`), cancellation / action modification / tool failures / state persistence (`test_workflows`), unauthorized access / cross-session isolation (`test_security`).

Scenario A (general question and follow-up) cannot be tested without the model. The automated test only checks the supporting facts: no backend tool exists for general questions, the prompt contains the Ask AI rules, and such a call creates no backend state.

One real defect was found by the tests and fixed: a request that lost the race to execute an action could overwrite the session's workflow state.

### Simulated calls against the running server

`make simulate` plays scenarios A–E as HTTP tool calls against the live local server, and separately against the Docker Compose stack. All 21 tool calls returned the expected status both times. The dashboard's guided demo was also run in a browser.

### Measured latency (backend only)

Measured on the development machine (macOS, SQLite, loopback). These exclude telephony, speech recognition, the language model and speech synthesis, which will dominate what a caller experiences.

| Measurement | Result |
|---|---|
| Server-side processing per tool call, 21 calls (dashboard overview) | median 3.4 ms, p95 64 ms |
| HTTP round trip from the simulator, local server | median 6 ms, max 68–72 ms |
| HTTP round trip from the simulator, Docker Compose stack | median 10 ms, max 57 ms |

The slowest call is always `verify_identity`: the access code is checked with a deliberately slow password hash.

### Telephony and conversation tests

**None performed.** The plan is [bolna/test_scenarios.md](../bolna/test_scenarios.md).

## User stories

| Story | Backend / artifacts | Verified on a call |
|---|---|---|
| US01 General AI access without an app or account | Agent created; prompt covers it; no account needed | No |
| US02 Hindi accessibility | Hindi transcriber and voice configured and accepted by Bolna; prompt rules for simple Hindi | No — speech quality and switching untested |
| US03 Email retrieval | DONE with mock data; permission checked; contents returned verbatim, never invented by the backend | No |
| US04 Calendar management | DONE with mock data: availability, prepare, approval, single execution, verified result | No |
| US05 Contextual task switching | No mode exists in the backend; the session keeps context across requests | No |
| US06 Mid-call correction | DONE: payload updated, version incremented, earlier approval void, only the latest version executes | No |
| US07 Security | DONE for the MVP model; limitations documented | No |

## What is simulated or not real

- **Email, calendar, documents, tasks:** mock adapters over the CallOS database. No Google or Microsoft account is involved. `app/integrations/google/` is an extension point that refuses to run.
- **Caller verification:** a spoken demo code. Not production authentication.
- **"Sending" an email or invitation:** writes a row in the mock Sent folder. No message leaves the system.
- **Simulator and guided demo:** scripted tool calls, not conversations.

## Blockers and next steps (in order)

1. **Public HTTPS URL for the backend** — done for this session with a temporary `trycloudflare.com` tunnel. The URL changes whenever the tunnel restarts, and the tools must then be re-attached; use a container host ([deployment.md](deployment.md) §4) for a stable URL.
2. **Attach the tools to the Bolna agent** — one command with your `BOLNA_API_KEY`, or a dashboard paste ([bolna/setup_guide.md](../bolna/setup_guide.md) steps 3–4).
3. **Make real calls** and run [bolna/test_scenarios.md](../bolna/test_scenarios.md); record results here. Check the eight uncertain integration details listed in [bolna/agent_configuration.md](../bolna/agent_configuration.md), especially whether `call_sid` is filled in Web Call mode.
4. **Assign a phone number** in Bolna if a dial-in number is wanted (costs money).

## Known gaps

- No database migrations (tables are created at startup).
- No rate limiting on tool endpoints apart from verification attempts.
- Seeded calendar dates are relative to the seeding day and go stale on a long-running deployment; re-seed before a demo.
- Tested on Python 3.13 locally and 3.12 in Docker; Python 3.11 is expected to work but was not run.
- Frontend has a type check and a production build but no automated UI tests.
- Real Google integrations, a desktop companion and production authentication are not started.
- Nothing has been committed to git in this session; the changes are in the working tree.
