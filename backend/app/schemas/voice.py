"""Request/response contracts for the voice tool endpoints.

Requests are deliberately lenient: Bolna sends a flat JSON body built from the
tool's ``param`` template, so tool arguments may arrive either nested under
``parameters`` or as top-level keys, and numbers may arrive as strings. Strict
validation of each tool's arguments happens in the tool's own parameter model.
"""
from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class VoiceActionRequest(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True, json_schema_extra={"examples": [{
        "session_id": "call-demo-001", "action": "prepare_meeting",
        "parameters": {"title": "Project retrospective", "date": "tomorrow", "time": "16:00",
                       "duration_minutes": 30, "attendees": ["team"]},
    }]})

    session_id: str | None = Field(
        None, max_length=200, validation_alias=AliasChoices("session_id", "call_sid", "call_id"),
        description="Call identifier. Bolna supplies it through the auto-injected {call_sid} variable.")
    action: str | None = Field(None, max_length=80, description="Tool name from the allowlist.")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Tool arguments.")

    def merged_parameters(self) -> dict[str, Any]:
        """Tool arguments from ``parameters`` plus any flat top-level keys."""
        return {**(self.model_extra or {}), **self.parameters}


class VoiceActionResponse(BaseModel):
    """Compact, speech-oriented tool result. ``speech`` is always safe to read aloud."""

    ok: bool
    status: str = Field(description="success | awaiting_approval | completed | cancelled | auth_required | "
                                    "forbidden | not_found | conflict | invalid_request | stale_version | "
                                    "failed | partially_completed | unknown_outcome | unsupported_action | ...")
    action: str | None = None
    speech: str
    data: Any = None
    action_id: str | None = None
    version: int | None = None
    requires_approval: bool | None = None
    summary: str | None = None
    expires_at: str | None = None
    execution_mode: str = Field("mock", description="'mock' means a simulated workspace, not a real account.")
    session_id: str | None = None
    auth_level: str | None = None
    workflow_state: str | None = None
    correlation_id: str | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None


class ErrorResponse(BaseModel):
    """Envelope for transport-level errors (401/403/404/422/500)."""

    ok: bool = False
    status: str = "error"
    error: ErrorBody
    speech: str = "Sorry, I ran into a technical problem. Please try again."
    correlation_id: str | None = None
