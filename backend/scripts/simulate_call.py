#!/usr/bin/env python3
"""Local tool-call simulator: plays the Bolna agent's side of a call against a running backend.

It sends the same HTTP requests Bolna's custom functions would send (flat JSON body,
Bearer tool key) and prints each spoken result with the measured round-trip time.
This verifies the backend contract. It is NOT a phone call: no speech or language
model is involved, and the "caller" lines are scripted.

Usage (backend must be running):
  python scripts/simulate_call.py                      # scenario C: ask -> act
  python scripts/simulate_call.py --scenario all
  python scripts/simulate_call.py --base-url https://your-host --tool-key ... --pin ...
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
import uuid

import httpx

timings: list[float] = []


class Call:
    def __init__(self, client: httpx.Client, pin: str) -> None:
        self.client, self.pin = client, pin
        self.sid = f"sim-{uuid.uuid4().hex[:12]}"

    def _post(self, path: str, body: dict) -> dict:
        started = time.perf_counter()
        r = self.client.post(path, json={"call_sid": self.sid, **body})
        elapsed = (time.perf_counter() - started) * 1000
        timings.append(elapsed)
        if r.status_code != 200:
            sys.exit(f"HTTP {r.status_code} from {path}: {r.text[:500]}")
        data = r.json()
        extra = f" action={data['action_id']} v{data['version']}" if data.get("action_id") else ""
        print(f"    tool -> [{data['status']}]{extra} ({elapsed:.0f} ms, state={data.get('workflow_state')})")
        print(f"    CallOS: {data['speech']}")
        return data

    def tool(self, name: str, **args) -> dict:
        return self._post(f"/api/voice/tools/{name}", args)

    def approve(self, action_id: str, version: int) -> dict:
        return self._post("/api/actions/approve", {"action_id": action_id, "version": version})

    def cancel(self, action_id: str | None = None) -> dict:
        return self._post("/api/actions/cancel", {"action_id": action_id} if action_id else {})


def say(text: str) -> None:
    print(f"\n  Caller: {text}")


def model_answers(topic: str) -> None:
    print(f"    (answered by the voice model itself — {topic}; no backend call)")


def expect(data: dict, status: str) -> dict:
    if data["status"] != status:
        sys.exit(f"UNEXPECTED: wanted status '{status}', got '{data['status']}'")
    return data


def scenario_a(call: Call) -> None:
    say("What is compound interest?")
    model_answers("general question")
    say("Explain it more simply.")
    model_answers("follow-up, using conversation context")


def scenario_b(call: Call) -> None:
    say("Am I free tomorrow afternoon?")
    expect(call.tool("check_calendar", date="tomorrow", part_of_day="afternoon"), "auth_required")
    say(f"My access code is {' '.join(call.pin)}.")
    expect(call.tool("verify_identity", access_code=call.pin), "success")
    expect(call.tool("check_calendar", date="tomorrow", part_of_day="afternoon"), "success")
    say("Schedule a team sync at 5 PM tomorrow.")
    p = expect(call.tool("prepare_meeting", title="Team sync", date="tomorrow", time="17:00"), "awaiting_approval")
    say("Yes, go ahead.")
    expect(call.approve(p["action_id"], p["version"]), "completed")


def scenario_c(call: Call) -> None:
    say("Explain what a project retrospective is.")
    model_answers("general question")
    say("Check my calendar tomorrow afternoon.")
    expect(call.tool("check_calendar", date="tomorrow", part_of_day="afternoon"), "auth_required")
    say(f"My access code is {' '.join(call.pin)}.")
    expect(call.tool("verify_identity", access_code=call.pin), "success")
    expect(call.tool("check_calendar", date="tomorrow", part_of_day="afternoon"), "success")
    say("Schedule a retrospective meeting at 4 PM with my team.")
    p = expect(call.tool("prepare_meeting", title="Project retrospective", date="tomorrow", time="16:00",
                         attendees="my team"), "awaiting_approval")
    say("Yes, proceed.")
    expect(call.approve(p["action_id"], p["version"]), "completed")
    say("Thanks. By the way, how many minutes are in a day?")
    model_answers("back to Ask AI in the same call")


def scenario_d(call: Call) -> None:
    say(f"(verifies) My access code is {' '.join(call.pin)}.")
    expect(call.tool("verify_identity", access_code=call.pin), "success")
    say("Schedule a budget chat tomorrow at 9 AM.")
    p = expect(call.tool("prepare_meeting", title="Budget chat", date="tomorrow", time="09:00"), "awaiting_approval")
    say("Actually, make it 9:30.")
    u = expect(call.tool("update_pending_action", action_id=p["action_id"], time="09:30"), "awaiting_approval")
    print("    (if the agent wrongly approved the old version, the backend refuses:)")
    expect(call.approve(p["action_id"], p["version"]), "stale_version")
    say("Yes, 9:30 is right.")
    expect(call.approve(u["action_id"], u["version"]), "completed")
    print("    (a repeated approval does not create a second meeting:)")
    expect(call.approve(u["action_id"], u["version"]), "completed")
    say("Also create a task to review the deployment... no wait, cancel that.")
    t = expect(call.tool("prepare_task", title="Review the deployment"), "awaiting_approval")
    expect(call.cancel(t["action_id"]), "cancelled")


def scenario_e(call: Call) -> None:
    say("Read me Priya's emails.")
    expect(call.tool("search_emails", sender="Finance Desk", user_id="usr-priya"), "auth_required")
    say("My access code is 0 0 0 0 0 0.")
    expect(call.tool("verify_identity", access_code="000000"), "auth_failed")
    say("Delete all my files.")
    expect(call.tool("delete_files", path="/"), "unsupported_action")


SCENARIOS = {"a": ("A — Ask AI", scenario_a), "b": ("B — Act with AI", scenario_b),
             "c": ("C — Ask to Act (primary acceptance flow)", scenario_c),
             "d": ("D — Change of mind, duplicate approval, cancel", scenario_d),
             "e": ("E — Security", scenario_e)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("CALLOS_BASE_URL", "http://127.0.0.1:8787"))
    ap.add_argument("--tool-key", default=os.environ.get("CALLOS_TOOL_API_KEY", "dev-tool-key-change-me"))
    ap.add_argument("--pin", default=os.environ.get("CALLOS_DEMO_USER_PIN", "482916"))
    ap.add_argument("--scenario", default="c", choices=[*SCENARIOS, "all"])
    args = ap.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=20,
                      headers={"Authorization": f"Bearer {args.tool_key}"}) as client:
        health = client.get("/health")
        if health.status_code != 200:
            sys.exit(f"Backend not healthy at {args.base_url}: HTTP {health.status_code}")
        print(f"Backend {args.base_url}: {health.json()}")
        for key in (SCENARIOS if args.scenario == "all" else [args.scenario]):
            title, fn = SCENARIOS[key]
            print(f"\n=== Scenario {title} ===")
            fn(Call(client, args.pin))

    if timings:
        ordered = sorted(timings)
        print(f"\nAll steps behaved as expected. {len(timings)} tool calls; round trip from this machine: "
              f"median {statistics.median(ordered):.0f} ms, max {ordered[-1]:.0f} ms.")
        print("Simulated tool calls only — this is not evidence of a phone call.")


if __name__ == "__main__":
    main()
