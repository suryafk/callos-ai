"""Authorization and action allowlist. Enforced server-side, never by the LLM."""
from __future__ import annotations

from store import Session

READ_ONLY_ACTIONS = {"list_products", "calculate_quote", "get_order_status"}
WRITE_ACTIONS = {"prepare_order", "revise_order", "approve_order", "cancel_order"}
ALLOWED_ACTIONS = READ_ONLY_ACTIONS | WRITE_ACTIONS

MAX_ORDER_TOTAL_INR = 1_000_000


def is_allowed(action: str) -> bool:
    return action in ALLOWED_ACTIONS


def requires_auth(action: str) -> bool:
    return action in WRITE_ACTIONS or action == "get_order_status"


def check_authorized(session: Session, action: str) -> bool:
    if not requires_auth(action):
        return True
    return session.authenticated
