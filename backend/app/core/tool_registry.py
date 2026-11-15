"""The tool allowlist. A tool that is not registered here cannot run."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.core import workflow_engine as wf
from app.core.types import ToolContext, ToolParams, ToolResult
from app.services import auth_service, calendar_service, document_service, email_service, task_service


@dataclass(frozen=True)
class ToolSpec:
    name: str
    kind: str  # public | read | prepare | control
    scope: str | None
    params: type[ToolParams]
    handler: Callable[[ToolContext, ToolParams], ToolResult]
    description: str
    requires_auth: bool = True
    # Only callable through its dedicated guarded endpoint, never the generic dispatcher.
    dedicated_endpoint: str | None = None


def _prepare(action_type: str):
    return lambda ctx, p: wf.create_pending(ctx, action_type, p.model_dump(exclude_none=True))


_TOOLS = [
    ToolSpec("verify_identity", "public", None, auth_service.VerifyIdentityParams, auth_service.verify_identity,
             "Verify the caller with their access code (demo authentication).", requires_auth=False),
    ToolSpec("search_emails", "read", "email.read", email_service.SearchEmailsParams, email_service.search_emails,
             "Search the caller's inbox."),
    ToolSpec("read_email", "read", "email.read", email_service.ReadEmailParams, email_service.read_email,
             "Read one email."),
    ToolSpec("prepare_email", "prepare", "email.send", email_service.EmailDraftParams, _prepare("send_email"),
             "Prepare an email draft. It is sent only after approval."),
    ToolSpec("list_calendar_events", "read", "calendar.read", calendar_service.ListEventsParams,
             calendar_service.list_calendar_events, "List calendar events for a date or range."),
    ToolSpec("check_calendar", "read", "calendar.read", calendar_service.CheckCalendarParams,
             calendar_service.check_calendar, "Check availability and free slots."),
    ToolSpec("prepare_meeting", "prepare", "calendar.write", calendar_service.MeetingParams,
             _prepare("create_meeting"), "Prepare a meeting. It is created only after approval."),
    ToolSpec("search_documents", "read", "documents.read", document_service.SearchDocumentsParams,
             document_service.search_documents, "Search the caller's documents."),
    ToolSpec("read_document", "read", "documents.read", document_service.ReadDocumentParams,
             document_service.read_document, "Read a document's text."),
    ToolSpec("list_tasks", "read", "tasks.read", task_service.ListTasksParams, task_service.list_tasks,
             "List the caller's tasks."),
    ToolSpec("prepare_task", "prepare", "tasks.write", task_service.TaskParams, _prepare("create_task"),
             "Prepare a new task. It is created only after approval."),
    ToolSpec("prepare_task_completion", "prepare", "tasks.write", task_service.TaskCompletionParams,
             _prepare("complete_task"), "Prepare marking a task complete. Applied only after approval."),
    ToolSpec("get_pending_action", "read", None, wf.NoParams, wf.get_pending,
             "Report what is waiting for approval on this call."),
    ToolSpec("update_pending_action", "control", None, wf.UpdatePendingParams, wf.update_pending,
             "Change a pending action before approval (new version, old approvals void)."),
    ToolSpec("cancel_action", "control", None, wf.CancelParams, wf.cancel, "Cancel a pending action."),
    ToolSpec("approve_action", "control", None, wf.ApproveParams, wf.approve,
             "Approve and execute the latest version of a pending action.",
             dedicated_endpoint="/api/actions/approve"),
]

REGISTRY: dict[str, ToolSpec] = {t.name: t for t in _TOOLS}


def get_tool(name: str | None) -> ToolSpec | None:
    return REGISTRY.get((name or "").strip().lower())


def catalog() -> list[dict]:
    return [{
        "name": t.name, "kind": t.kind, "scope": t.scope, "requires_auth": t.requires_auth,
        "description": t.description, "dedicated_endpoint": t.dedicated_endpoint,
        "parameters": t.params.model_json_schema().get("properties", {}),
        "required": t.params.model_json_schema().get("required", []),
    } for t in _TOOLS]
