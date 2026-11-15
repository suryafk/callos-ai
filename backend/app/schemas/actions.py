from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ApproveActionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True, json_schema_extra={"examples": [
        {"session_id": "call-demo-001", "action_id": "act-3f9c2a17b0", "version": 2}]})

    session_id: str | None = Field(None, max_length=200,
                                   validation_alias=AliasChoices("session_id", "call_sid", "call_id"))
    action_id: Any = Field(None, description="Id returned when the action was prepared.")
    version: Any = Field(None, description="The exact version that was read to the caller and approved.")


class CancelActionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True, json_schema_extra={"examples": [
        {"session_id": "call-demo-001", "action_id": "act-3f9c2a17b0"}]})

    session_id: str | None = Field(None, max_length=200,
                                   validation_alias=AliasChoices("session_id", "call_sid", "call_id"))
    action_id: Any = Field(None, description="Optional when exactly one action is pending on the call.")
    reason: Any = None
