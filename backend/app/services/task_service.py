"""Personal task tools: list, prepare a new task, prepare completing a task."""
from __future__ import annotations

from datetime import date

from pydantic import Field

from app.core.types import (
    Action, ActionHandler, BuiltAction, Step, StepResult, ToolContext, ToolError, ToolParams, ToolResult,
    register_action_handler,
)
from app.services.common import join_words, require_ok
from app.utils.timeparse import TimeParseError, fmt_date, parse_date


class ListTasksParams(ToolParams):
    status: str = "open"


class TaskParams(ToolParams):
    title: str = Field(min_length=1, max_length=200)
    due_date: str | None = None
    notes: str | None = Field(None, max_length=1000)


class TaskCompletionParams(ToolParams):
    task_id: str | None = Field(None, max_length=40)
    title: str | None = Field(None, max_length=200)


def task_view(ctx: ToolContext, t) -> dict:
    return {"task_id": t.id, "title": t.title, "status": t.status,
            "due": fmt_date(t.due_date, ctx.today) if t.due_date else None,
            "due_date": t.due_date.isoformat() if t.due_date else None}


def list_tasks(ctx: ToolContext, p: ListTasksParams) -> ToolResult:
    status = p.status.lower()
    if status not in ("open", "completed", "all"):
        raise ToolError("invalid_request", "status must be open, completed or all.")
    rows = require_ok(ctx.adapters.tasks.list(ctx.user.id, status=status), "task list")
    items = [task_view(ctx, t) for t in rows]
    label = "" if status == "all" else f"{status} "
    if not items:
        speech = f"You have no {label}tasks."
    else:
        shown = items[:5]
        listing = "; ".join(it["title"] + (f", due {it['due']}" if it["due"] else "") for it in shown)
        speech = f"You have {len(items)} {label}task{'s' if len(items) != 1 else ''}: {listing}."
        if len(items) > len(shown):
            speech += f" Plus {len(items) - len(shown)} more."
    return ToolResult(speech=speech, data={"count": len(items), "tasks": items[:10]})


# ---------------------------------------------------------------- pending action: create_task

def build_task(ctx: ToolContext, inputs: dict) -> BuiltAction:
    p = TaskParams.model_validate(inputs)
    due: date | None = None
    if p.due_date:
        try:
            due = parse_date(p.due_date, ctx.tz, ctx.now)
        except TimeParseError as exc:
            raise ToolError("invalid_request", str(exc))
    summary = f"Create the task '{p.title}'" + (f", due {fmt_date(due)}." if due else ", with no due date.")
    return BuiltAction(payload={"title": p.title, "due_date": due.isoformat() if due else None,
                                "notes": p.notes}, summary=summary)


def _step_create_task(ctx: ToolContext, action: Action, key: str, _prev: dict) -> StepResult:
    pl = action.payload
    due = date.fromisoformat(pl["due_date"]) if pl.get("due_date") else None
    res = ctx.adapters.tasks.create(ctx.user.id, title=pl["title"], due_date=due, notes=pl.get("notes"),
                                    idempotency_key=key)
    if not res.ok:
        return StepResult(False, "failed", message=res.message or "the task service rejected the request")
    check = ctx.adapters.tasks.get(ctx.user.id, res.data.id)
    if not check.ok:
        return StepResult(False, "unknown_outcome", message="the new task could not be verified")
    return StepResult(True, detail={"task_id": res.data.id, "title": res.data.title, "verified": True,
                                    "deduplicated": res.meta.get("deduplicated", False)})


def _reconcile_task(ctx: ToolContext, action: Action, key: str) -> StepResult | None:
    found = ctx.adapters.tasks.find_by_key(ctx.user.id, key)
    if found.ok:
        return StepResult(True, detail={"task_id": found.data.id, "title": found.data.title,
                                        "verified": True, "deduplicated": True})
    return None


TASK_HANDLER = register_action_handler(ActionHandler(
    type="create_task", scope="tasks.write", label="task",
    build=build_task, editable_fields=("title", "due_date", "notes"),
    steps=[Step("create_task", _step_create_task, _reconcile_task, description="Create the task")],
    success_speech=lambda action, details: f"Done. I added the task '{action.payload['title']}' to your list.",
))


# ---------------------------------------------------------------- pending action: complete_task

def build_task_completion(ctx: ToolContext, inputs: dict) -> BuiltAction:
    p = TaskCompletionParams.model_validate(inputs)
    if p.task_id:
        task = require_ok(ctx.adapters.tasks.get(ctx.user.id, p.task_id), "task")
    elif p.title:
        tokens = p.title.lower().split()
        open_tasks = require_ok(ctx.adapters.tasks.list(ctx.user.id, status="open"), "task list")
        hits = [t for t in open_tasks if all(tok in t.title.lower() for tok in tokens)]
        if not hits:
            raise ToolError("not_found", f"I could not find an open task matching {p.title}.")
        if len(hits) > 1:
            raise ToolError("needs_clarification",
                            "More than one task matches: " + join_words([t.title for t in hits[:4]]) + ". Which one?",
                            {"matches": [task_view(ctx, t) for t in hits[:4]]})
        task = hits[0]
    else:
        raise ToolError("invalid_request", "Tell me which task to complete, by its ID or its title.")
    if task.status == "completed":
        raise ToolError("conflict", f"The task '{task.title}' is already marked complete.")
    return BuiltAction(payload={"task_id": task.id, "title": task.title},
                       summary=f"Mark the task '{task.title}' as complete.")


def _step_complete_task(ctx: ToolContext, action: Action, key: str, _prev: dict) -> StepResult:
    res = ctx.adapters.tasks.complete(ctx.user.id, action.payload["task_id"], idempotency_key=key)
    if not res.ok:
        return StepResult(False, res.status.value, message=res.message or "the task could not be updated")
    check = ctx.adapters.tasks.get(ctx.user.id, res.data.id)
    if not check.ok or check.data.status != "completed":
        return StepResult(False, "unknown_outcome", message="the task update could not be verified")
    return StepResult(True, detail={"task_id": res.data.id, "title": res.data.title, "verified": True})


def _reconcile_completion(ctx: ToolContext, action: Action, key: str) -> StepResult | None:
    got = ctx.adapters.tasks.get(ctx.user.id, action.payload["task_id"])
    if got.ok and got.data.status == "completed":
        return StepResult(True, detail={"task_id": got.data.id, "title": got.data.title, "verified": True})
    return None


TASK_COMPLETION_HANDLER = register_action_handler(ActionHandler(
    type="complete_task", scope="tasks.write", label="task completion",
    build=build_task_completion, editable_fields=(),
    steps=[Step("complete_task", _step_complete_task, _reconcile_completion, description="Mark the task complete")],
    success_speech=lambda action, details: f"Done. '{action.payload['title']}' is marked complete.",
))
