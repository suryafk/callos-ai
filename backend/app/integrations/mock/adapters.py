"""Mock workspace adapters backed by real database tables.

These simulate external services: every read is scoped to ``user_id`` and every
write persists a row. Writes commit immediately — an external API does not take
part in the caller's database transaction, and the workflow engine must not
assume it does. No method returns a canned success.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import utcnow
from app.integrations.base import (
    AdapterResult, AdapterStatus, CalendarAdapter, DocumentAdapter, EmailAdapter, TaskAdapter,
)
from app.models import MockCalendarEvent, MockDocument, MockEmail, MockTask

MODE = "mock"


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _ok(data, **meta) -> AdapterResult:
    return AdapterResult(AdapterStatus.SUCCESS, data=data, execution_mode=MODE, meta=meta)


def _not_found(what: str) -> AdapterResult:
    return AdapterResult(AdapterStatus.NOT_FOUND, message=f"{what} not found", execution_mode=MODE)


def _tokens(text: str | None) -> list[str]:
    return [t for t in (text or "").lower().split() if t]


def _matches(tokens: list[str], *fields: str) -> bool:
    haystack = " ".join(f.lower() for f in fields if f)
    return all(t in haystack for t in tokens)


class MockEmailAdapter(EmailAdapter):
    def __init__(self, db: Session) -> None:
        self.db = db

    def search(self, user_id, *, query, sender, unread_only, limit) -> AdapterResult:
        stmt = (select(MockEmail)
                .where(MockEmail.user_id == user_id, MockEmail.folder == "inbox")
                .order_by(MockEmail.received_at.desc()))
        if unread_only:
            stmt = stmt.where(MockEmail.is_read.is_(False))
        q_tokens, s_tokens = _tokens(query), _tokens(sender)
        rows = [
            e for e in self.db.scalars(stmt)
            if _matches(q_tokens, e.subject, e.body, e.from_name, e.from_addr)
            and _matches(s_tokens, e.from_name, e.from_addr)
        ]
        return _ok(rows[:limit], total=len(rows))

    def get(self, user_id, email_id) -> AdapterResult:
        row = self.db.scalar(select(MockEmail).where(MockEmail.id == email_id, MockEmail.user_id == user_id))
        return _ok(row) if row else _not_found("Email")

    def known_addresses(self, user_id) -> AdapterResult:
        known: dict[str, str] = {}
        for e in self.db.scalars(select(MockEmail).where(MockEmail.user_id == user_id)):
            known.setdefault(e.from_addr.lower(), e.from_name)
            for addr in e.to_addrs or []:
                known.setdefault(str(addr).lower(), "")
        return _ok(known)

    def send(self, user_id, *, to, subject, body, idempotency_key) -> AdapterResult:
        existing = self.find_by_key(user_id, idempotency_key)
        if existing.ok:
            return _ok(existing.data, deduplicated=True)
        from app.models import User

        user = self.db.get(User, user_id)
        row = MockEmail(
            id=_new_id("em"), user_id=user_id, folder="sent", from_name=user.display_name,
            from_addr=user.email, to_addrs=list(to), subject=subject, body=body, is_read=True,
            received_at=utcnow(), created_by="callos", idempotency_key=idempotency_key,
        )
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:  # concurrent retry with the same key
            self.db.rollback()
            return self.find_by_key(user_id, idempotency_key)
        return _ok(row, deduplicated=False)

    def find_by_key(self, user_id, idempotency_key) -> AdapterResult:
        row = self.db.scalar(select(MockEmail).where(
            MockEmail.user_id == user_id, MockEmail.idempotency_key == idempotency_key))
        return _ok(row) if row else _not_found("Email")


class MockCalendarAdapter(CalendarAdapter):
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_events(self, user_id, *, start_utc: datetime, end_utc: datetime) -> AdapterResult:
        rows = list(self.db.scalars(
            select(MockCalendarEvent)
            .where(MockCalendarEvent.user_id == user_id,
                   MockCalendarEvent.start_utc < end_utc, MockCalendarEvent.end_utc > start_utc)
            .order_by(MockCalendarEvent.start_utc)))
        return _ok(rows)

    def get_event(self, user_id, event_id) -> AdapterResult:
        row = self.db.scalar(select(MockCalendarEvent).where(
            MockCalendarEvent.id == event_id, MockCalendarEvent.user_id == user_id))
        return _ok(row) if row else _not_found("Event")

    def create_event(self, user_id, *, title, start_utc, end_utc, attendees, idempotency_key) -> AdapterResult:
        existing = self.find_by_key(user_id, idempotency_key)
        if existing.ok:
            return _ok(existing.data, deduplicated=True)
        clash = self.list_events(user_id, start_utc=start_utc, end_utc=end_utc).data
        if clash:
            return AdapterResult(AdapterStatus.CONFLICT, data=clash, execution_mode=MODE,
                                 message=f"Overlaps with '{clash[0].title}'")
        row = MockCalendarEvent(
            id=_new_id("evt"), user_id=user_id, title=title, start_utc=start_utc, end_utc=end_utc,
            attendees=list(attendees), created_by="callos", idempotency_key=idempotency_key,
        )
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            return self.find_by_key(user_id, idempotency_key)
        return _ok(row, deduplicated=False)

    def find_by_key(self, user_id, idempotency_key) -> AdapterResult:
        row = self.db.scalar(select(MockCalendarEvent).where(
            MockCalendarEvent.user_id == user_id, MockCalendarEvent.idempotency_key == idempotency_key))
        return _ok(row) if row else _not_found("Event")


class MockDocumentAdapter(DocumentAdapter):
    def __init__(self, db: Session) -> None:
        self.db = db

    def search(self, user_id, *, query, limit) -> AdapterResult:
        tokens = _tokens(query)
        rows = list(self.db.scalars(
            select(MockDocument).where(MockDocument.user_id == user_id)
            .order_by(MockDocument.updated_at.desc())))
        # Title/tag matches rank ahead of body-only matches.
        title_hits = [d for d in rows if _matches(tokens, d.title, " ".join(d.tags or []))]
        body_hits = [d for d in rows if d not in title_hits and _matches(tokens, d.content)]
        hits = title_hits + body_hits
        return _ok(hits[:limit], total=len(hits))

    def get(self, user_id, document_id) -> AdapterResult:
        row = self.db.scalar(select(MockDocument).where(
            MockDocument.id == document_id, MockDocument.user_id == user_id))
        return _ok(row) if row else _not_found("Document")


class MockTaskAdapter(TaskAdapter):
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, user_id, *, status) -> AdapterResult:
        stmt = select(MockTask).where(MockTask.user_id == user_id)
        if status in ("open", "completed"):
            stmt = stmt.where(MockTask.status == status)
        rows = list(self.db.scalars(stmt.order_by(MockTask.created_at)))
        rows.sort(key=lambda t: (t.due_date is None, t.due_date or date.max))
        return _ok(rows)

    def get(self, user_id, task_id) -> AdapterResult:
        row = self.db.scalar(select(MockTask).where(MockTask.id == task_id, MockTask.user_id == user_id))
        return _ok(row) if row else _not_found("Task")

    def create(self, user_id, *, title, due_date, notes, idempotency_key) -> AdapterResult:
        existing = self.find_by_key(user_id, idempotency_key)
        if existing.ok:
            return _ok(existing.data, deduplicated=True)
        row = MockTask(id=_new_id("tsk"), user_id=user_id, title=title, due_date=due_date, notes=notes,
                       created_by="callos", idempotency_key=idempotency_key)
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            return self.find_by_key(user_id, idempotency_key)
        return _ok(row, deduplicated=False)

    def complete(self, user_id, task_id, *, idempotency_key) -> AdapterResult:
        got = self.get(user_id, task_id)
        if not got.ok:
            return got
        task: MockTask = got.data
        if task.status == "completed":
            return _ok(task, deduplicated=True)
        task.status = "completed"
        task.completed_at = utcnow()
        task.completion_key = idempotency_key
        self.db.commit()
        return _ok(task, deduplicated=False)

    def find_by_key(self, user_id, idempotency_key) -> AdapterResult:
        row = self.db.scalar(select(MockTask).where(
            MockTask.user_id == user_id,
            (MockTask.idempotency_key == idempotency_key) | (MockTask.completion_key == idempotency_key)))
        return _ok(row) if row else _not_found("Task")
