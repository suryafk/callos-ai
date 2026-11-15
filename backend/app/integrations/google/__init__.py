"""Google Workspace adapters — NOT IMPLEMENTED in the MVP.

Real Gmail / Calendar / Drive / Tasks access needs an OAuth consent flow, per-user
token storage and a verified identity binding, none of which exist yet. These
classes exist only to mark the extension point: each one implements the same
interface as the mock adapter (see ``app.integrations.base``) and refuses to run
rather than pretending to succeed.

To add a real integration:
1. Implement the abstract methods using the Google API client and the user's
   stored OAuth token (looked up by ``user_id``; never taken from the request).
2. Map provider errors to ``AdapterResult`` statuses; raise ``IntegrationTimeout``
   when a write's outcome is unknown and implement ``find_by_key`` for
   reconciliation (e.g. store the idempotency key in an extended property).
3. Return ``execution_mode="live"`` and wire the class into ``get_adapters``.
"""
from __future__ import annotations

from app.integrations.base import IntegrationNotConfigured


class _GoogleNotConfigured:
    execution_mode = "live"
    service = "Google"

    def __init__(self, *_args, **_kwargs) -> None:
        raise IntegrationNotConfigured(
            f"{self.service} integration is not implemented; no credentials are configured. "
            "Use CALLOS_INTEGRATION_MODE=mock."
        )


class GoogleCalendarAdapter(_GoogleNotConfigured):
    service = "Google Calendar"


class GmailAdapter(_GoogleNotConfigured):
    service = "Gmail"


class GoogleDriveAdapter(_GoogleNotConfigured):
    service = "Google Drive"


class GoogleTasksAdapter(_GoogleNotConfigured):
    service = "Google Tasks"
