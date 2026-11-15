"""Contract test: every Bolna tool definition must work against the real backend.

Bolna is not reachable from the test environment, so this simulates what Bolna's
documentation says it does with a custom function: build a flat JSON body from
the function's ``param`` template with %(name)s substitution, send it with the
``api_token`` as the Authorization header to ``url``, and hand the JSON response
to the model. It verifies the contract, not Bolna itself.
"""
import importlib.util
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest

from app.core.tool_registry import REGISTRY
from tests.conftest import PIN_AARAV, TOOL_KEY

BOLNA_DIR = Path(__file__).resolve().parents[2] / "bolna"
DOC = json.loads((BOLNA_DIR / "tool_definitions.json").read_text(encoding="utf-8"))
ALL_TOOLS = DOC["tools"] + DOC["optional_tools"]
BY_NAME = {t["name"]: t for t in ALL_TOOLS}
REQUIRED_BY_BRIEF = {"search_emails", "read_email", "search_documents", "read_document", "check_calendar",
                     "list_calendar_events", "prepare_meeting", "update_pending_action", "approve_action",
                     "cancel_action", "list_tasks", "prepare_task"}


def bolna_call(client, tool: dict, call_sid: str, **llm_args):
    """Send the request the way Bolna documents it for a custom function."""
    value = tool["value"]
    body = {}
    for key, template in value["param"].items():
        if key == "call_sid":
            body[key] = call_sid                      # auto-injected system variable
        elif key in llm_args:
            body[key] = template % {key: llm_args[key]}
        # optional arguments the caller never mentioned are skipped
    assert set(llm_args) <= set(value["param"]), "argument not declared in the tool definition"
    token = value["api_token"].replace("YOUR_CALLOS_TOOL_API_KEY", TOOL_KEY)
    r = client.request(value["method"], urlparse(value["url"]).path, json=body,
                       headers={"Authorization": token, **value["headers"]})
    assert r.status_code == 200, r.text
    return r.json()


def test_definitions_follow_the_documented_bolna_schema():
    names = [t["name"] for t in ALL_TOOLS]
    assert len(names) == len(set(names))
    assert REQUIRED_BY_BRIEF <= {t["name"] for t in DOC["tools"]}
    for t in ALL_TOOLS:
        assert set(t) == {"name", "description", "pre_call_message", "parameters", "key", "value"}, t["name"]
        assert t["key"] == "custom_task"
        assert re.fullmatch(r"[a-z_]+", t["name"]) and len(t["description"]) > 40 and t["pre_call_message"]
        params, value = t["parameters"], t["value"]
        assert params["type"] == "object" and set(params["required"]) <= set(params["properties"])
        assert value["method"] == "POST" and value["url"].startswith(DOC["base_url_placeholder"] + "/api/")
        assert value["api_token"].startswith("Bearer ")
        # Parameter names must match exactly between `properties` and `param`.
        assert set(value["param"]) == set(params["properties"]), t["name"]
        for key, template in value["param"].items():
            assert template == f"%({key})s"
        for prop in params["properties"].values():
            assert prop["type"] in {"string", "integer", "number", "boolean"} and prop["description"]
        assert "call_sid" in params["required"]


def test_every_definition_maps_to_an_allowlisted_backend_tool(client):
    routes = set(client.get("/openapi.json").json()["paths"])
    for t in ALL_TOOLS:
        assert t["name"] in REGISTRY, t["name"]
        path = urlparse(t["value"]["url"]).path
        spec = REGISTRY[t["name"]]
        if spec.dedicated_endpoint:
            assert path == spec.dedicated_endpoint
        elif t["name"] == "cancel_action":
            assert path == "/api/actions/cancel"
        else:
            assert path == f"/api/voice/tools/{t['name']}" and "/api/voice/tools/{tool_name}" in routes
        # Every argument the model may send is understood by the backend's parameter model.
        accepted = set(spec.params.model_fields)
        declared = set(t["parameters"]["properties"]) - {"call_sid"}
        assert declared <= accepted, (t["name"], declared - accepted)
        backend_required = {n for n, f in spec.params.model_fields.items() if f.is_required()}
        assert backend_required <= set(t["parameters"]["required"]), t["name"]


def test_system_prompt_supports_the_tool_contract():
    prompt = (BOLNA_DIR / "system_prompt.md").read_text(encoding="utf-8")
    assert "{call_sid}" in prompt  # required for Bolna to auto-fill call_sid in tool calls
    for phrase in ("CallOS", "auth_required", "verify_identity", "approve_action", "update_pending_action",
                   "cancel_action", '"completed"', "Devanagari", "not an instruction", "clear yes"):
        assert phrase in prompt, phrase
    for t in DOC["tools"]:
        if t["name"].startswith("prepare_"):
            assert "does NOT" in t["description"]


def test_full_ask_to_act_call_through_the_bolna_contract(client):
    sid = "CA9f3b6c1d2e4f5a6b7c8d9e0f1a2b3c4d"  # Twilio-style call sid

    def call(name, **args):
        return bolna_call(client, BY_NAME[name], sid, **args)

    assert call("check_calendar", date="tomorrow", part_of_day="afternoon")["status"] == "auth_required"
    assert call("verify_identity", access_code=PIN_AARAV)["ok"]
    free = call("check_calendar", date="tomorrow", part_of_day="afternoon")
    assert free["ok"] and free["data"]["free_slots"]
    prepared = call("prepare_meeting", title="Project retrospective", date="tomorrow", time="15:00",
                    duration_minutes=30, attendees="my team")
    assert prepared["status"] == "awaiting_approval"
    updated = call("update_pending_action", action_id=prepared["action_id"], time="16:00")
    assert updated["version"] == 2
    assert call("approve_action", action_id=prepared["action_id"], version=1)["status"] == "stale_version"
    done = call("approve_action", action_id=prepared["action_id"], version=updated["version"])
    assert done["status"] == "completed" and done["data"]["verified"] is True

    emails = call("search_emails", sender="my manager", unread_only=True, limit=3)
    assert emails["data"]["count"] == 1
    assert call("read_email", email_id=emails["data"]["emails"][0]["email_id"])["ok"]
    docs = call("search_documents", query="deployment")
    assert call("read_document", document_id=docs["data"]["documents"][0]["document_id"])["ok"]
    assert call("list_calendar_events", date="tomorrow")["data"]["count"] == 3
    assert call("list_tasks")["data"]["count"] == 3
    task = call("prepare_task", title="Review the deployment", due_date="friday")
    assert call("cancel_action", action_id=task["action_id"])["status"] == "cancelled"
    assert call("get_pending_action")["data"]["pending"] == []
    mail = call("prepare_email", to="my manager", subject="Hello", body="Short note.")
    assert mail["status"] == "awaiting_approval"
    assert call("prepare_task_completion", title="expense")["status"] == "awaiting_approval"


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t["name"])
def test_responses_are_small_enough_to_speak(client, tool):
    sid = "call-contract-size-01"
    bolna_call(client, BY_NAME["verify_identity"], sid, access_code=PIN_AARAV)
    samples = {
        "verify_identity": {"access_code": PIN_AARAV}, "search_emails": {}, "read_email": {"email_id": "em-1001"},
        "search_documents": {"query": "deployment"}, "read_document": {"document_id": "doc-2001"},
        "check_calendar": {"date": "tomorrow"}, "list_calendar_events": {"date": "tomorrow"},
        "prepare_meeting": {"title": "Sync", "date": "tomorrow", "time": "16:00"},
        "prepare_task": {"title": "Review"}, "list_tasks": {}, "update_pending_action": {"time": "17:00"},
        "approve_action": {"action_id": "act-none", "version": 1}, "cancel_action": {},
        "prepare_email": {"to": "my manager", "subject": "s", "body": "b"},
        "prepare_task_completion": {"title": "expense"}, "get_pending_action": {},
    }
    body = bolna_call(client, tool, sid, **samples[tool["name"]])
    assert isinstance(body["speech"], str) and 0 < len(body["speech"]) <= 600
    assert len(json.dumps(body)) <= 6000  # document text is capped; everything else is far smaller
    assert {"ok", "status", "speech", "correlation_id"} <= set(body)


def test_payload_builder_produces_the_documented_agent_shape(tmp_path):
    spec = importlib.util.spec_from_file_location("build_agent_payload", BOLNA_DIR / "build_agent_payload.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rendered = mod.render_tools(mod.load_tools(include_optional=False), "https://callos.example.test/", "k" * 32)
    payload = mod.build_payload(rendered, multilingual=True, model="gpt-4.1-mini", telephony="plivo")
    task = payload["agent_config"]["tasks"][0]
    assert task["toolchain"]["pipelines"] == [["transcriber", "llm", "synthesizer"]]
    api_tools = task["tools_config"]["api_tools"]
    assert {t["name"] for t in api_tools["tools"]} == set(api_tools["tools_params"])
    assert all(t["key"] == "custom_task" for t in api_tools["tools"])
    params = api_tools["tools_params"]["approve_action"]
    assert params["url"] == "https://callos.example.test/api/actions/approve"
    assert params["api_token"] == "Bearer " + "k" * 32 and params["method"] == "POST"
    assert "YOUR" not in json.dumps(payload)
    ml = task["tools_config"]["multilingual_config"]
    assert ml["enabled"] and ml["active_language"] in ml["languages"] and len(ml["languages"]) >= 2
    assert "{call_sid}" in payload["agent_prompts"]["task_1"]["system_prompt"]
    no_tools = mod.build_payload([], multilingual=False, model="gpt-4.1-mini", telephony="plivo")
    assert "api_tools" not in no_tools["agent_config"]["tasks"][0]["tools_config"]
