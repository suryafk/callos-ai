# Bolna agent configuration

## Live agent

| | |
|---|---|
| Agent name | `CallOS AI` |
| Agent ID | `326ca6aa-b7b2-4d6b-ba26-f7e4d63aac93` |
| Created | 15 November 2026, through the Bolna connector (Bolna reported `state: created`, then `agent_status: processed`) |
| Tools attached | **None yet.** The tool payload is built (`bolna/out/`), but attaching it needs a full update with your Bolna API key or a dashboard paste — see [setup_guide.md](setup_guide.md) step 4. Until then the agent does Ask AI only |
| Inbound phone number | None assigned |
| Calls placed or received | None |

The system prompt stored on the agent is identical to [system_prompt.md](system_prompt.md).

## Settings and why

| Setting | Value | Reason |
|---|---|---|
| Agent type | `simple_llm_agent`, streaming | One agent for both Ask AI and Act with AI; no mode switch, no transfers |
| LLM | OpenAI `gpt-4.1-mini`, temperature 0.2, max tokens 220 | Low latency, reliable tool calling, short spoken answers. It is on the account's preferential-pricing model list |
| Welcome message | "Hello, this is CallOS, your AI assistant. You can ask me any question, or ask me to check your email, calendar, documents or tasks. How can I help?" | Tells the caller both things they can do |
| English speech-to-text | Deepgram `nova-3`, `en`, endpointing 250 ms | Bolna's documented low-latency default for English |
| English voice | ElevenLabs `eleven_turbo_v2_5`, voice "Angelica" | The voice used in Bolna's own create-agent example; accepted by the API |
| Hindi speech-to-text | Sarvam `saaras:v4`, `hi` | Bolna's Hindi guide recommends Sarvam for Indian callers and code-mixed (Hinglish) speech |
| Hindi voice | Sarvam `bulbul:v4-flash`, voice "Aparna (Customer)" | The pair used in Bolna's Hindi agent example; accepted by the API |
| Multilingual | `multilingual_config` enabled, starts in English, `requested_or_auto_detected` switching, Hindi welcome and hand-off messages | Lets one agent serve English and Hindi callers |
| Interruption | 2 words | Lets the caller cut in and change topic |
| Silence hang-up / max call | 20 s / 600 s | Room to think; bounded cost |
| Telephony | `plivo` input/output | Bolna's default; change it to match the number you attach |

To change any of these, edit the constants at the top of [build_agent_payload.py](build_agent_payload.py) (or change them in the Bolna dashboard).

## What has and has not been verified

Verified: Bolna's API accepted this configuration, including the multilingual block and both voice/model pairs.

Not verified (needs a real call): speech recognition accuracy, voice quality, Hindi and Hinglish behaviour, language switching, interruption handling, response latency, and whether the model follows the prompt's approval rules in conversation.

## Integration details that are documented by Bolna

- Custom function format: `name`, `description`, `pre_call_message`, `parameters`, `key: "custom_task"`, and `value` with `method`, `param`, `url`, `api_token`, `headers`.
- Over the API the same information is split into `api_tools.tools` (definition) and `api_tools.tools_params[name]` (HTTP details).
- `param` maps arguments with `%(name)s` specifiers; parameter names must match `properties` exactly.
- `{call_sid}` is a system variable. It is substituted into tool calls when the prompt references it — which is why the prompt contains `The call ID is "{call_sid}"`.
- The current date and time are appended to the system prompt automatically.
- Tool and webhook calls come from three fixed source IPs: `13.203.39.153`, `13.126.9.249`, `13.202.133.53`.

## Uncertain details — check these on the first tool-enabled call

Each was designed around so that an unexpected answer degrades gracefully rather than breaking the call.

| # | Unknown | How the backend copes | What to check |
|---|---|---|---|
| 1 | Whether `call_sid` is filled for **Web Call** and **Chat with agent** tests (the docs describe it as the phone call's ID) | A missing or unsubstituted ID is rejected with a clear error. For local testing only, `CALLOS_DEV_FALLBACK_SESSION_ID` supplies a shared session ID in `development` | Backend log line `tool call without a usable session id` |
| 2 | What Bolna sends for an optional argument the caller never gave | Empty strings, `null` and leftover `%(name)s` placeholders are dropped | Audit trail → parameters of the tool call |
| 3 | How integer and boolean arguments are serialised with `%(name)s` | Numeric and boolean strings are coerced | A `prepare_meeting` with a duration, `search_emails` with `unread_only` |
| 4 | What the model receives when a tool returns a non-200 status | Tool-level outcomes always return 200 with a `speech` field | A 401 (wrong key) should be the only failure the model cannot explain |
| 5 | Whether `api_token` or `headers.Authorization` is the right place for the credential when tools are created through the API (the docs show both) | — | If every tool call is 401 in the backend log, move the value to `headers: {"Authorization": "Bearer …"}` |
| 6 | Which prompt is active after switching to Hindi when no per-language `system_prompt` is given (the field is optional) | The single prompt already covers Hindi | Do tools and the approval rules still work after switching to Hindi? If not, add the same prompt under `languages.hi.system_prompt` |
| 7 | Tool timeout and maximum response size | Responses are capped (documents 3,000 characters, emails 1,500); measured backend time is a few milliseconds locally | Long documents being cut off; a sleeping free-tier host timing out |
| 8 | Whether the model reliably copies `action_id` and `version` from the last tool response | A wrong version is refused (`stale_version`) and the response restates the current summary | The change-of-mind scenario |
