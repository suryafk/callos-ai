"""Integration contracts. Mock and real providers implement the same interfaces.

Adapters return an :class:`AdapterResult` for every outcome they can determine and
raise :class:`IntegrationTimeout` / :class:`IntegrationError` when the outcome of a
call is not known. Write methods take an ``idempotency_key`` so a retried call can
never create a second resource, and ``find_by_key`` lets the workflow engine
reconcile a write whose outcome is uncertain.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any


class AdapterStatus(str, Enum):
    SUCCESS = "success"
    NOT_FOUND = "not_found"
    UNAUTHORIZED = "unauthorized"
    CONFLICT = "conflict"
    FAILED = "failed"
    TIMEOUT = "timeout"
    UNKNOWN_OUTCOME = "unknown_outcome"


@dataclass
class AdapterResult:
    status: AdapterStatus
    data: Any = None
    message: str = ""
    execution_mode: str = "mock"
    meta: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == AdapterStatus.SUCCESS


class IntegrationError(Exception):
    """The provider call failed and its outcome is not known to the adapter."""


class IntegrationTimeout(IntegrationError):
    """The provider did not answer in time; a write may or may not have happened."""


class IntegrationNotConfigured(IntegrationError):
    """The provider has no credentials / is not implemented."""


class EmailAdapter(ABC):
    execution_mode = "mock"

    @abstractmethod
    def search(self, user_id: str, *, query: str | None, sender: str | None,
               unread_only: bool, limit: int) -> AdapterResult: ...

    @abstractmethod
    def get(self, user_id: str, email_id: str) -> AdapterResult: ...

    @abstractmethod
    def known_addresses(self, user_id: str) -> AdapterResult: ...

    @abstractmethod
    def send(self, user_id: str, *, to: list[str], subject: str, body: str,
             idempotency_key: str) -> AdapterResult: ...

    @abstractmethod
    def find_by_key(self, user_id: str, idempotency_key: str) -> AdapterResult: ...


class CalendarAdapter(ABC):
    execution_mode = "mock"

    @abstractmethod
    def list_events(self, user_id: str, *, start_utc: datetime, end_utc: datetime) -> AdapterResult: ...

    @abstractmethod
    def get_event(self, user_id: str, event_id: str) -> AdapterResult: ...

    @abstractmethod
    def create_event(self, user_id: str, *, title: str, start_utc: datetime, end_utc: datetime,
                     attendees: list[str], idempotency_key: str) -> AdapterResult: ...

    @abstractmethod
    def find_by_key(self, user_id: str, idempotency_key: str) -> AdapterResult: ...


class DocumentAdapter(ABC):
    execution_mode = "mock"

    @abstractmethod
    def search(self, user_id: str, *, query: str, limit: int) -> AdapterResult: ...

    @abstractmethod
    def get(self, user_id: str, document_id: str) -> AdapterResult: ...


class TaskAdapter(ABC):
    execution_mode = "mock"

    @abstractmethod
    def list(self, user_id: str, *, status: str) -> AdapterResult: ...

    @abstractmethod
    def get(self, user_id: str, task_id: str) -> AdapterResult: ...

    @abstractmethod
    def create(self, user_id: str, *, title: str, due_date: date | None, notes: str | None,
               idempotency_key: str) -> AdapterResult: ...

    @abstractmethod
    def complete(self, user_id: str, task_id: str, *, idempotency_key: str) -> AdapterResult: ...

    @abstractmethod
    def find_by_key(self, user_id: str, idempotency_key: str) -> AdapterResult: ...


@dataclass
class Adapters:
    email: EmailAdapter
    calendar: CalendarAdapter
    documents: DocumentAdapter
    tasks: TaskAdapter
