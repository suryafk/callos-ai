# Demo script

**Title:** From a question to a completed task — without touching a screen.

There are two ways to show it. Say clearly which one you are using.

- **Live call** — a real conversation with the Bolna agent. Needs the backend on a public URL and the tools attached ([bolna/setup_guide.md](../bolna/setup_guide.md)). Not yet performed.
- **Simulated tool calls** — the dashboard's **API testing → Guided demo**, or `make simulate`. This shows the real backend doing real work, but the caller's lines are scripted and no speech or language model is involved.

## Before you start

1. Backend and dashboard running; signed in to the dashboard.
2. Dashboard → **API testing → Reset demo data** so tomorrow's calendar is in its starting state (Sprint planning 11:00–12:00, Design review 2:00–2:45 PM).
3. Have the demo access code ready (`CALLOS_DEMO_USER_PIN`).
4. Open **Demo workspace** in one tab and **Sessions** in another.

## The call (about three minutes)

| # | Caller says | What to point out |
|---|---|---|
| 1 | "What is a project retrospective?" | Ask AI. The agent answers by itself. Nothing appears in the dashboard, because no backend call is needed |
| 2 | "Can you explain that more simply?" | Follow-up uses the conversation context |
| 3 | "Check my calendar for tomorrow afternoon." | No mode switch. The backend refuses private data until the caller is verified, and the agent asks for the access code |
| 4 | Says the access code | Session becomes *authenticated* in **Sessions**. The code itself is not stored or logged |
| 5 | (agent answers) | "One meeting, Design review 2:00 to 2:45, free from 12 to 2 and 2:45 to 5" — read from the mock calendar |
| 6 | "Schedule a retrospective at 3 PM with my team." | The agent reads back the summary and asks for approval. **Actions** shows it *pending*, version 1. The calendar is unchanged |
| 7 | "Actually, make it 4 PM." | Same action, **version 2**; the audit trail shows the change. The 3 PM approval can no longer be used |
| 8 | "Yes, proceed." | Executes once. The agent reports success only after the backend verifies the event. **Demo workspace** shows "Project retrospective — created by CallOS" at 4:00 PM, and the invitation email in Sent |
| 9 | "How many minutes are there in a day?" | Straight back to Ask AI in the same call |

## Optional extras (30 seconds each)

- **Cancel:** "Create a task to review the deployment." → "No, cancel that." → the action is *cancelled*, no task exists.
- **Conflict:** "Schedule a call tomorrow at 2:15 PM." → refused, with free slots offered.
- **Documents:** "Summarise the document about deployment." → search, read, spoken summary.
- **Email:** "Find the latest email from my manager." → uses the user's own alias for "manager".
- **Injection:** "Read the vendor onboarding notes." → the document tells AI assistants to email an attacker. Nothing happens: no action is created. If you then ask to email that address, the approval summary starts with a warning.
- **Not available:** "Open my laptop and delete my downloads." → the agent says it cannot do that.

## Closing points

- The model asks; the backend decides. Authorization, versions, single execution and verification are enforced in code and covered by tests.
- Open a session's **Audit trail** to show every step: denied → verified → prepared → changed → approved → executed.
- Be explicit about limits: the workspace is simulated; verification by spoken code is a demo mechanism; say whether a real phone call was part of what you showed.
