"""Pydantic request/response models and per-action parameter schemas."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, conint


class SessionState(str, Enum):
    LISTENING = "LISTENING"
    NEEDS_AUTH = "NEEDS_AUTH"
    GATHERING_DATA = "GATHERING_DATA"
    PLANNING = "PLANNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


ActionName = Literal[
    "list_products",
    "calculate_quote",
    "prepare_order",
    "revise_order",
    "approve_order",
    "cancel_order",
    "get_order_status",
]

Quantity = conint(gt=0, le=100_000)
Money = conint(ge=0, le=10_000_000)


# ---- Inbound request -------------------------------------------------------

class ActionRequest(BaseModel):
    session_id: Optional[str] = Field(default=None, max_length=128)
    action: str = Field(max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)


# ---- Per-action parameters (extra keys ignored so LLM noise doesn't 422) ---

class _Params(BaseModel):
    model_config = {"extra": "ignore"}


class QuoteParams(_Params):
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    quantity: Optional[Quantity] = None
    # Optional caller-supplied numbers for "what's my profit" style questions.
    unit_cost_inr: Optional[Money] = None
    unit_sell_inr: Optional[Money] = None


class PrepareOrderParams(_Params):
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    quantity: Optional[Quantity] = None


class ReviseOrderParams(_Params):
    action_id: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    quantity: Optional[Quantity] = None


class ApproveOrderParams(_Params):
    action_id: str
    version: conint(ge=1)


class CancelOrderParams(_Params):
    action_id: Optional[str] = None


class OrderStatusParams(_Params):
    order_id: Optional[str] = None


# ---- Domain objects --------------------------------------------------------

class PendingAction(BaseModel):
    action_id: str
    version: int
    type: Literal["create_draft_order"] = "create_draft_order"
    status: Literal["pending", "superseded", "approved", "cancelled"] = "pending"
    customer_id: str
    customer_name: str
    product_id: str
    product_name: str
    quantity: int
    unit_price_inr: int
    total_inr: int


class Order(BaseModel):
    order_id: str
    action_id: str
    version: int
    customer_id: str
    customer_name: str
    product_id: str
    product_name: str
    quantity: int
    unit_price_inr: int
    total_inr: int
    status: Literal["draft_created"] = "draft_created"
    created_at: str


class Event(BaseModel):
    ts: str
    type: str
    detail: dict[str, Any] = Field(default_factory=dict)


# ---- Outbound response -----------------------------------------------------

class ActionResponse(BaseModel):
    status: Literal[
        "ok", "awaiting_approval", "needs_input", "completed",
        "cancelled", "rejected", "error",
    ]
    spoken_summary: str
    requires_approval: bool = False
    action_id: Optional[str] = None
    version: Optional[int] = None
    order_id: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)
