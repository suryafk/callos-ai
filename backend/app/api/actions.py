"""Guarded approval and cancellation endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_tool_key
from app.config import Settings, get_settings
from app.core import orchestrator
from app.database import get_db
from app.schemas.actions import ApproveActionRequest, CancelActionRequest
from app.schemas.voice import ErrorResponse, VoiceActionResponse

router = APIRouter(prefix="/api/actions", tags=["actions"], dependencies=[Depends(require_tool_key)],
                   responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})

APPROVE_PATH = "/api/actions/approve"


@router.post("/approve", response_model=VoiceActionResponse, response_model_exclude_none=True,
             summary="Approve and execute the latest version of a pending action")
def approve_action(req: ApproveActionRequest, db: Session = Depends(get_db),
                   settings: Settings = Depends(get_settings)) -> VoiceActionResponse:
    """Executes a pending action exactly once.

    The server checks: the call is verified, the action belongs to this call and
    this user, the user holds the required scope, the action is still pending and
    unexpired, and ``version`` equals the current version. Repeating the call
    returns the stored result without executing again.
    """
    return orchestrator.dispatch(db, settings, session_id=req.session_id, action="approve_action",
                                 params={"action_id": req.action_id, "version": req.version},
                                 via_endpoint=APPROVE_PATH)


@router.post("/cancel", response_model=VoiceActionResponse, response_model_exclude_none=True,
             summary="Cancel a pending action")
def cancel_action(req: CancelActionRequest, db: Session = Depends(get_db),
                  settings: Settings = Depends(get_settings)) -> VoiceActionResponse:
    return orchestrator.dispatch(db, settings, session_id=req.session_id, action="cancel_action",
                                 params={"action_id": req.action_id, "reason": req.reason})
