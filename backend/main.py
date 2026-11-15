"""CallOS FastAPI backend — the tool endpoint Bolna calls.

Run:  uvicorn main:app --reload --port 8000   (from the backend/ folder)
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from orchestrator import dispatch
from schemas import ActionRequest, ActionResponse
from store import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("callos")

# Shared secret Bolna sends as a header. Unset = open (local dev only).
API_KEY = os.getenv("CALLOS_API_KEY", "")
# Used when Bolna's tool payload has no stable call identifier (disclosed demo limitation).
DEMO_SESSION_ID = os.getenv("CALLOS_DEMO_SESSION_ID", "call-demo-001")
# Set to "0" to protect /api/sessions in non-demo environments.
EXPOSE_SESSIONS = os.getenv("CALLOS_EXPOSE_SESSIONS", "1") == "1"

app = FastAPI(title="CallOS AI backend", version="0.1.0")


def require_key(x_callos_key: str = Header(default="")) -> None:
    if API_KEY and x_callos_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing X-CallOS-Key")


def _coerce(body: dict[str, Any]) -> ActionRequest:
    """Accept both {action, parameters:{...}} and a flat {action, quantity, ...} payload."""
    if "parameters" not in body or not isinstance(body.get("parameters"), dict):
        params = {k: v for k, v in body.items() if k not in ("session_id", "action")}
        body = {"session_id": body.get("session_id"), "action": body.get("action", ""), "parameters": params}
    return ActionRequest(**body)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "callos", "storage": "in-memory (resets on restart)"}


@app.post("/api/voice/action", response_model=ActionResponse, dependencies=[Depends(require_key)])
async def voice_action(request: Request) -> ActionResponse | JSONResponse:
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        req = _coerce(body)
    except Exception:  # noqa: BLE001 — always give the voice agent something speakable
        return JSONResponse(status_code=200, content=ActionResponse(
            status="error", spoken_summary="Sorry, I couldn't process that request. Please try again.",
        ).model_dump())

    session_id = (req.session_id or "").strip() or DEMO_SESSION_ID
    resp = dispatch(session_id, req.action, req.parameters)
    log.info("session=%s action=%s status=%s action_id=%s v=%s order=%s",
             session_id, req.action, resp.status, resp.action_id, resp.version, resp.order_id)
    return resp


def _session_or_404(session_id: str):
    if not EXPOSE_SESSIONS:
        raise HTTPException(status_code=404)
    s = store.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    return s


@app.get("/api/sessions", dependencies=[Depends(require_key)])
def list_sessions() -> list[dict[str, Any]]:
    if not EXPOSE_SESSIONS:
        raise HTTPException(status_code=404)
    return [{"session_id": s.session_id, "state": s.state, "orders": list(s.orders)} for s in store.all()]


@app.get("/api/sessions/{session_id}", dependencies=[Depends(require_key)])
def get_session(session_id: str) -> dict[str, Any]:
    return _session_or_404(session_id).model_dump(exclude={"approvals"})


@app.get("/api/sessions/{session_id}/events", dependencies=[Depends(require_key)])
def get_events(session_id: str) -> list[dict[str, Any]]:
    return [e.model_dump() for e in _session_or_404(session_id).events]
