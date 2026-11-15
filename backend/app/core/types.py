"""Shared types for tools, pending-action handlers and execution steps."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.config import Settings
from app.integrations.base import Adapters
from app.models import Action, CallSession, User
from app.utils.timeparse import get_zone, local_today


class ToolParams(BaseModel):
    """Base for tool parameter models: lenient about extra keys and string numbers."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


@dataclass
class ToolContext:
    db: Session
    session: CallSession
    user: User | None
    adapters: Adapters
    settings: Settings
    now: datetime  # naive UTC
    correlation_id: str = "-"

    @property
    def tz(self) -> ZoneInfo:
        return get_zone(self.user.timezone if self.user else None, self.settings.default_timezone)

    @property
    def today(self) -> date:
        return local_today(self.tz, self.now)

    def remember(self, **values: Any) -> None:
        """Store small pieces of conversation context on the session."""
        self.session.context = {**(self.session.context or {}), **values}


@dataclass
class ToolResult:
    status: str = "success"
    speech: str = ""
    data: Any = None
    ok: bool = True
    action: Action | None = None  # pending/executed action to surface in the response


class ToolError(Exception):
    """A handled, speakable failure of a tool call (not a server error)."""

    def __init__(self, status: str, speech: str, data: Any = None) -> None:
        super().__init__(speech)
        self.status = status
        self.speech = speech
        self.data = data


@dataclass
class BuiltAction:
    payload: dict
    summary: str
    risk_flags: list[str] = field(default_factory=list)


@dataclass
class StepResult:
    ok: bool
    status: str = "success"  # success | failed | conflict | not_found | unknown_outcome
    detail: dict = field(default_factory=dict)
    message: str = ""


@dataclass
class Step:
    name: str
    # run(ctx, action, idempotency_key, previous_step_details) -> StepResult
    run: Callable[[ToolContext, Action, str, dict], StepResult]
    # reconcile(ctx, action, idempotency_key) -> StepResult if the effect exists, else None
    reconcile: Callable[[ToolContext, Action, str], StepResult | None] | None = None
    applies: Callable[[dict], bool] = lambda payload: True
    description: str = ""


@dataclass
class ActionHandler:
    type: str
    scope: str
    label: str
    # build(ctx, inputs) validates inputs and returns the payload + spoken summary.
    build: Callable[[ToolContext, dict], BuiltAction]
    editable_fields: tuple[str, ...]
    steps: list[Step]
    success_speech: Callable[[Action, dict], str]


ACTION_HANDLERS: dict[str, ActionHandler] = {}


def register_action_handler(handler: ActionHandler) -> ActionHandler:
    ACTION_HANDLERS[handler.type] = handler
    return handler
