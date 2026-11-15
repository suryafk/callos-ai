#!/usr/bin/env python3
"""Build the Bolna agent configuration for CallOS AI (standard library only).

It combines bolna/system_prompt.md and bolna/tool_definitions.json with your
public backend URL and tool key, and writes two files into bolna/out/ (which is
git-ignored because the output contains your tool key):

  agent_payload.json   body for POST https://api.bolna.ai/v2/agent  (or PUT /v2/agent/{id})
  dashboard_tools.json one custom-function JSON per tool, to paste into the Bolna dashboard

Usage:
  python bolna/build_agent_payload.py --base-url https://callos.example.com --tool-key "$CALLOS_TOOL_API_KEY"
  python bolna/build_agent_payload.py --no-tools                    # Ask-AI-only agent, no backend needed
  BOLNA_API_KEY=... python bolna/build_agent_payload.py --base-url ... --tool-key ... --apply
  BOLNA_API_KEY=... python bolna/build_agent_payload.py ... --apply --agent-id <existing agent id>

--apply calls the documented Bolna Agent API. Nothing is sent without --apply.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOLNA_API = "https://api.bolna.ai"

WELCOME_EN = ("Hello, this is CallOS, your AI assistant. You can ask me any question, or ask me to check "
              "your email, calendar, documents or tasks. How can I help?")
WELCOME_HI = ("नमस्ते, मैं CallOS हूँ, आपका AI assistant. आप मुझसे कोई भी सवाल पूछ सकते हैं, या अपना email, "
              "calendar, documents या tasks check करवा सकते हैं। बताइए, मैं क्या मदद करूँ?")
HANDOFF_HI = "ठीक है, अब मैं हिंदी में बात करूँगा।"
HANDOFF_EN = "Sure, I will continue in English."

# Provider values below are taken from Bolna's own documentation examples
# (create-agent minimal example, multilingual-config reference, Hindi agent guide).
# Voice catalogs change: if agent creation rejects a voice, pick one from the
# dashboard's voice list and change it here.
EN_TRANSCRIBER = {"provider": "deepgram", "model": "nova-3", "language": "en", "stream": True,
                  "endpointing": 250}
EN_SYNTHESIZER = {"provider": "elevenlabs", "stream": True, "buffer_size": 250, "audio_format": "wav",
                  "provider_config": {"voice": "Angelica", "voice_id": "IkSv4tkouLJ6kYsQA7XD",
                                      "model": "eleven_turbo_v2_5"}}
HI_TRANSCRIBER = {"provider": "sarvam", "model": "saaras:v4", "language": "hi"}
HI_SYNTHESIZER = {"provider": "sarvam", "stream": True, "buffer_size": 150,
                  "provider_config": {"voice": "Aparna (Customer)", "voice_id": "aparna_hi_customer",
                                      "model": "bulbul:v4-flash", "language": "hi", "speed": 1.0}}


def load_tools(include_optional: bool) -> list[dict]:
    doc = json.loads((HERE / "tool_definitions.json").read_text(encoding="utf-8"))
    return doc["tools"] + (doc["optional_tools"] if include_optional else [])


def render_tools(tools: list[dict], base_url: str, tool_key: str) -> list[dict]:
    """Substitute the real backend URL and credential into the tool definitions."""
    doc = json.loads((HERE / "tool_definitions.json").read_text(encoding="utf-8"))
    rendered = copy.deepcopy(tools)
    for tool in rendered:
        value = tool["value"]
        value["url"] = value["url"].replace(doc["base_url_placeholder"], base_url.rstrip("/"))
        value["api_token"] = f"Bearer {tool_key}"
    return rendered


def api_tools_block(rendered: list[dict]) -> dict:
    """The documented api_tools shape: definitions in `tools`, HTTP details in `tools_params`."""
    return {
        "tools": [{k: t[k] for k in ("name", "description", "pre_call_message", "parameters", "key")}
                  for t in rendered],
        "tools_params": {t["name"]: t["value"] for t in rendered},
    }


def build_payload(rendered_tools: list[dict], *, multilingual: bool, model: str, telephony: str) -> dict:
    prompt = (HERE / "system_prompt.md").read_text(encoding="utf-8").strip()
    tools_config: dict = {
        "llm_agent": {
            "agent_type": "simple_llm_agent", "agent_flow_type": "streaming",
            "llm_config": {"provider": "openai", "model": model, "max_tokens": 220, "temperature": 0.2},
        },
        "transcriber": EN_TRANSCRIBER,
        "synthesizer": EN_SYNTHESIZER,
        "input": {"provider": telephony, "format": "wav"},
        "output": {"provider": telephony, "format": "wav"},
    }
    if rendered_tools:
        tools_config["api_tools"] = api_tools_block(rendered_tools)
    if multilingual:
        tools_config["multilingual_config"] = {
            "enabled": True, "active_language": "en",
            "language_switch_trigger": "requested_or_auto_detected",
            "languages": {
                "en": {"synthesizer": EN_SYNTHESIZER, "handoff_message": HANDOFF_EN},
                "hi": {"transcriber": HI_TRANSCRIBER, "synthesizer": HI_SYNTHESIZER,
                       "handoff_message": HANDOFF_HI, "welcome_message": WELCOME_HI},
            },
        }
    return {
        "agent_config": {
            "agent_name": "CallOS AI",
            "agent_welcome_message": WELCOME_EN,
            "agent_type": "other",
            "tasks": [{
                "task_type": "conversation",
                "toolchain": {"execution": "sequential", "pipelines": [["transcriber", "llm", "synthesizer"]]},
                "tools_config": tools_config,
                "task_config": {
                    "hangup_after_silence": 20, "call_terminate": 600,
                    "number_of_words_for_interruption": 2, "incremental_delay": 400,
                },
            }],
        },
        "agent_prompts": {"task_1": {"system_prompt": prompt}},
    }


def call_bolna(method: str, path: str, body: dict, api_key: str) -> dict:
    req = urllib.request.Request(BOLNA_API + path, data=json.dumps(body).encode(), method=method,
                                 headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        sys.exit(f"Bolna API returned {exc.code}: {exc.read().decode()[:2000]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", help="Public HTTPS URL of the CallOS backend, e.g. https://callos.onrender.com")
    ap.add_argument("--tool-key", default=os.environ.get("CALLOS_TOOL_API_KEY"),
                    help="CALLOS_TOOL_API_KEY of that backend (default: env CALLOS_TOOL_API_KEY)")
    ap.add_argument("--no-tools", action="store_true", help="Build an Ask-AI-only agent without backend tools")
    ap.add_argument("--include-optional", action="store_true", help="Also add the optional tools")
    ap.add_argument("--single-language", action="store_true", help="English only (omit multilingual_config)")
    ap.add_argument("--model", default="gpt-4.1-mini")
    ap.add_argument("--telephony", default="plivo", help="plivo | twilio | exotel | vobiz")
    ap.add_argument("--apply", action="store_true", help="Create/update the agent through the Bolna API")
    ap.add_argument("--agent-id", help="With --apply: update this agent (PUT) instead of creating one")
    args = ap.parse_args()

    rendered: list[dict] = []
    if not args.no_tools:
        if not args.base_url or not args.tool_key:
            ap.error("--base-url and --tool-key are required unless --no-tools is given")
        if not args.base_url.startswith("https://"):
            ap.error("--base-url must be a public https:// URL (Bolna cannot reach localhost)")
        rendered = render_tools(load_tools(args.include_optional), args.base_url, args.tool_key)

    payload = build_payload(rendered, multilingual=not args.single_language, model=args.model,
                            telephony=args.telephony)
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    (out / "agent_payload.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "dashboard_tools.json").write_text(json.dumps(rendered, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out / 'agent_payload.json'} and {out / 'dashboard_tools.json'} ({len(rendered)} tools).")
    print("These files contain your tool key. bolna/out/ is git-ignored; do not commit or share them.")

    if args.apply:
        api_key = os.environ.get("BOLNA_API_KEY")
        if not api_key:
            sys.exit("Set BOLNA_API_KEY to use --apply.")
        if args.agent_id:
            print(json.dumps(call_bolna("PUT", f"/v2/agent/{args.agent_id}", payload, api_key), indent=2))
        else:
            print(json.dumps(call_bolna("POST", "/v2/agent", payload, api_key), indent=2))
    else:
        print("Nothing was sent to Bolna (no --apply).")


if __name__ == "__main__":
    main()
