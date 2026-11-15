"""In-memory session store.

WARNING: all state lives in process memory and disappears on restart.
Fine for the hackathon demo; production would use PostgreSQL/Redis.
"""
from __future__ import annotations

import itertools
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from schemas import Event, Order, PendingAction, SessionState

DEMO_USER_ID = "demo-business-001"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Session(BaseModel):
    session_id: str
    user_id: str = DEMO_USER_ID
    # Demo pre-authorization (disclosed): every session is treated as the demo business user.
    authenticated: bool = True
    state: SessionState = SessionState.LISTENING
    pending_action: Optional[PendingAction] = None
    action_history: list[PendingAction] = Field(default_factory=list)
    orders: dict[str, Order] = Field(default_factory=dict)
    # Idempotency: "action_id:version" -> serialized ActionResponse
    approvals: dict[str, dict[str, Any]] = Field(default_factory=dict)
    events: list[Event] = Field(default_factory=list)

    def log(self, type_: str, **detail: Any) -> None:
        self.events.append(Event(ts=now_iso(), type=type_, detail=detail))


class Store:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()
        self._action_seq = itertools.count(201)
        self._order_seq = itertools.count(1001)

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def get_or_create(self, session_id: str) -> Session:
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None:
                s = Session(session_id=session_id)
                s.log("session_created")
                self._sessions[session_id] = s
            return s

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def all(self) -> list[Session]:
        return list(self._sessions.values())

    def next_action_id(self) -> str:
        return f"act-{next(self._action_seq)}"

    def next_order_id(self) -> str:
        return f"ORD-{next(self._order_seq)}"

    def reset(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._action_seq = itertools.count(201)
            self._order_seq = itertools.count(1001)


store = Store()
