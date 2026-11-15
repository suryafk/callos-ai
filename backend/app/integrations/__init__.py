from __future__ import annotations

from sqlalchemy.orm import Session

from app.integrations.base import Adapters, IntegrationNotConfigured


def get_adapters(db: Session, mode: str = "mock") -> Adapters:
    """Return the adapter set for the configured integration mode."""
    if mode == "mock":
        from app.integrations.mock.adapters import (
            MockCalendarAdapter, MockDocumentAdapter, MockEmailAdapter, MockTaskAdapter,
        )

        return Adapters(
            email=MockEmailAdapter(db), calendar=MockCalendarAdapter(db),
            documents=MockDocumentAdapter(db), tasks=MockTaskAdapter(db),
        )
    raise IntegrationNotConfigured(f"Integration mode '{mode}' is not implemented")
