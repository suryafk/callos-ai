"""Tool endpoints called by the Bolna voice agent."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_tool_key
from app.config import Settings, get_settings
from app.core import orchestrator
from app.database import get_db
from app.schemas.voice import ErrorResponse, VoiceActionRequest, VoiceActionResponse

router = APIRouter(prefix="/api/voice", tags=["voice"], dependencies=[Depends(require_tool_key)],
                   responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})

_SESSION_KEYS = ("session_id", "call_sid", "call_id")


@router.post("/action", response_model=VoiceActionResponse, response_model_exclude_none=True,
             summary="Dispatch an allowlisted tool (action name in the body)")
def voice_action(req: VoiceActionRequest, db: Session = Depends(get_db),
                 settings: Settings = Depends(get_settings)) -> VoiceActionResponse:
    """Runs a read / prepare / update / cancel tool for the given call.

    Tool-level outcomes (not found, verification required, conflict, invalid
    arguments, unsupported action) return HTTP 200 with ``ok: false`` and a
    ``speech`` string, so the voice agent always has something accurate to say.
    Only credential and malformed-body problems use 401 / 422.
    """
    return orchestrator.dispatch(db, settings, session_id=req.session_id, action=req.action,
                                 params=req.merged_parameters())


@router.post("/tools/{tool_name}", response_model=VoiceActionResponse, response_model_exclude_none=True,
             summary="Dispatch an allowlisted tool (action name in the path, flat body)")
def voice_tool(tool_name: str, body: dict[str, Any] = Body(...), db: Session = Depends(get_db),
               settings: Settings = Depends(get_settings)) -> VoiceActionResponse:
    """Same dispatcher as ``/api/voice/action``; convenient for Bolna custom functions,
    whose request body is a flat object built from the function's ``param`` template."""
    session_id = next((str(body[k]) for k in _SESSION_KEYS if body.get(k)), None)
    nested = body.get("parameters") if isinstance(body.get("parameters"), dict) else {}
    params = {k: v for k, v in body.items() if k not in (*_SESSION_KEYS, "action", "parameters")}
    return orchestrator.dispatch(db, settings, session_id=session_id, action=tool_name,
                                 params={**params, **nested})
