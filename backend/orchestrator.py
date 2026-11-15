"""Action dispatcher + order state machine.

Invariants (see context.md section 7):
- Prices/totals come from the catalog, never from LLM text.
- A revision increments the version and invalidates earlier approvals.
- Approval must name the exact current action_id + version for this session.
- Approval is idempotent: retrying the same approval returns the same result.
- Cancelled / superseded actions never execute.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from pydantic import ValidationError

import policy
from catalog import Customer, Product, catalog
from schemas import (
    ActionResponse,
    ApproveOrderParams,
    CancelOrderParams,
    Order,
    OrderStatusParams,
    PendingAction,
    PrepareOrderParams,
    QuoteParams,
    ReviseOrderParams,
    SessionState,
)
from store import Session, now_iso, store

CHARGES_NOTE = "before taxes and delivery charges"


def _rupees(n: int | float) -> str:
    return f"{int(n):,} rupees" if float(n).is_integer() else f"{n:,.2f} rupees"


def _reject(msg: str, **data: Any) -> ActionResponse:
    return ActionResponse(status="rejected", spoken_summary=msg, data=data)


def _resolve_product(p_id: Optional[str], p_name: Optional[str]) -> Optional[Product]:
    return catalog.find_product(product_id=p_id, name=p_name)


def _resolve_customer(c_id: Optional[str], c_name: Optional[str]) -> Optional[Customer]:
    return catalog.find_customer(customer_id=c_id, name=c_name)


def _describe(a: PendingAction) -> str:
    return (
        f"Draft order for {a.customer_name}: {a.quantity} {a.product_name}s at "
        f"{_rupees(a.unit_price_inr)} each, total {_rupees(a.total_inr)} {CHARGES_NOTE}."
    )


# ---------------------------------------------------------------------------
# Read-only actions
# ---------------------------------------------------------------------------

def list_products(session: Session, params: dict[str, Any]) -> ActionResponse:
    items = [
        {"product_id": p.product_id, "name": p.name, "unit_price_inr": p.unit_price_inr, "inventory": p.inventory}
        for p in catalog.products.values()
    ]
    return ActionResponse(
        status="ok",
        spoken_summary=f"We have {catalog.product_names()}. Customers on file: {catalog.customer_names()}.",
        data={"products": items, "customers": [c.name for c in catalog.customers.values()]},
    )


def calculate_quote(session: Session, params: dict[str, Any]) -> ActionResponse:
    p = QuoteParams(**params)
    if p.quantity is None:
        return ActionResponse(status="needs_input", spoken_summary="How many units should I calculate for?",
                              data={"missing": ["quantity"]})

    # Pure profit maths on caller-supplied buy/sell prices (no catalog needed).
    if p.unit_cost_inr is not None and p.unit_sell_inr is not None:
        cost = p.unit_cost_inr * p.quantity
        revenue = p.unit_sell_inr * p.quantity
        profit = revenue - cost
        markup = (profit / cost * 100) if cost else 0.0
        margin = (profit / revenue * 100) if revenue else 0.0
        return ActionResponse(
            status="ok",
            spoken_summary=(
                f"Buying {p.quantity} at {_rupees(p.unit_cost_inr)} costs {_rupees(cost)}. Selling at "
                f"{_rupees(p.unit_sell_inr)} brings {_rupees(revenue)}. Gross profit is {_rupees(profit)} "
                f"before other expenses. That is a {markup:.0f} percent markup on cost and a "
                f"{margin:.0f} percent margin on revenue."
            ),
            data={"cost_inr": cost, "revenue_inr": revenue, "gross_profit_inr": profit,
                  "markup_pct": round(markup, 2), "margin_pct": round(margin, 2)},
        )

    product = _resolve_product(p.product_id, p.product_name)
    if product is None:
        return _reject(f"I couldn't find that product. Available products are {catalog.product_names()}.")
    total = product.unit_price_inr * p.quantity
    return ActionResponse(
        status="ok",
        spoken_summary=(f"{p.quantity} {product.name}s at {_rupees(product.unit_price_inr)} each comes to "
                        f"{_rupees(total)} {CHARGES_NOTE}."),
        data={"product_id": product.product_id, "quantity": p.quantity,
              "unit_price_inr": product.unit_price_inr, "total_inr": total},
    )


def get_order_status(session: Session, params: dict[str, Any]) -> ActionResponse:
    p = OrderStatusParams(**params)
    order = session.orders.get(p.order_id.upper()) if p.order_id else (
        list(session.orders.values())[-1] if session.orders else None
    )
    if order is None:
        pending = session.pending_action
        if pending and pending.status == "pending":
            return ActionResponse(status="awaiting_approval", requires_approval=True,
                                  action_id=pending.action_id, version=pending.version,
                                  spoken_summary=f"No order is created yet. Pending: {_describe(pending)} Shall I create it?")
        return ActionResponse(status="ok", spoken_summary="There are no orders in this call yet.")
    return ActionResponse(
        status="ok", order_id=order.order_id,
        spoken_summary=(f"Order {order.order_id} for {order.customer_name} is a created draft: "
                        f"{order.quantity} {order.product_name}s, total {_rupees(order.total_inr)}."),
        data=order.model_dump(),
    )


# ---------------------------------------------------------------------------
# Write actions
# ---------------------------------------------------------------------------

def _build_action(session: Session, action_id: str, version: int, customer: Customer,
                  product: Product, quantity: int) -> ActionResponse | PendingAction:
    if quantity > product.inventory:
        return _reject(f"We only have {product.inventory} {product.name}s in stock. Please choose a smaller quantity.")
    total = product.unit_price_inr * quantity
    if total > policy.MAX_ORDER_TOTAL_INR:
        return _reject(f"That total of {_rupees(total)} exceeds the demo order limit of "
                       f"{_rupees(policy.MAX_ORDER_TOTAL_INR)}.")
    return PendingAction(
        action_id=action_id, version=version,
        customer_id=customer.customer_id, customer_name=customer.name,
        product_id=product.product_id, product_name=product.name,
        quantity=quantity, unit_price_inr=product.unit_price_inr, total_inr=total,
    )


def _awaiting(a: PendingAction, prefix: str = "") -> ActionResponse:
    return ActionResponse(
        status="awaiting_approval", requires_approval=True,
        action_id=a.action_id, version=a.version,
        spoken_summary=f"{prefix}{_describe(a)} Shall I create it?",
        data=a.model_dump(),
    )


def prepare_order(session: Session, params: dict[str, Any]) -> ActionResponse:
    p = PrepareOrderParams(**params)
    missing = []
    if not (p.customer_id or p.customer_name):
        missing.append("customer")
    if not (p.product_id or p.product_name):
        missing.append("product")
    if p.quantity is None:
        missing.append("quantity")
    if missing:
        session.state = SessionState.GATHERING_DATA
        return ActionResponse(status="needs_input", data={"missing": missing},
                              spoken_summary=f"To prepare the order I still need the {' and '.join(missing)}.")

    customer = _resolve_customer(p.customer_id, p.customer_name)
    if customer is None:
        return _reject(f"I couldn't find that customer. Customers on file are {catalog.customer_names()}.")
    product = _resolve_product(p.product_id, p.product_name)
    if product is None:
        return _reject(f"I couldn't find that product. Available products are {catalog.product_names()}.")

    result = _build_action(session, store.next_action_id(), 1, customer, product, p.quantity)
    if isinstance(result, ActionResponse):
        return result

    prev = session.pending_action
    if prev and prev.status == "pending":
        prev.status = "superseded"
        session.log("action_superseded", action_id=prev.action_id, version=prev.version,
                    by=result.action_id)
    session.pending_action = result
    session.action_history.append(result)
    session.state = SessionState.AWAITING_APPROVAL
    session.log("action_proposed", action_id=result.action_id, version=1, total_inr=result.total_inr)
    return _awaiting(result)


def revise_order(session: Session, params: dict[str, Any]) -> ActionResponse:
    p = ReviseOrderParams(**params)
    cur = session.pending_action
    if cur is None or cur.status != "pending":
        return _reject("There is no pending draft to change. Would you like me to prepare a new one?")
    if p.action_id and p.action_id != cur.action_id:
        return _reject("That draft is no longer current. I'll use the latest pending draft instead.",
                       current_action_id=cur.action_id, current_version=cur.version)

    customer = (_resolve_customer(p.customer_id, p.customer_name)
                if (p.customer_id or p.customer_name) else catalog.customers[cur.customer_id])
    if customer is None:
        return _reject(f"I couldn't find that customer. Customers on file are {catalog.customer_names()}.")
    product = (_resolve_product(p.product_id, p.product_name)
               if (p.product_id or p.product_name) else catalog.products[cur.product_id])
    if product is None:
        return _reject(f"I couldn't find that product. Available products are {catalog.product_names()}.")
    quantity = p.quantity or cur.quantity

    result = _build_action(session, cur.action_id, cur.version + 1, customer, product, quantity)
    if isinstance(result, ActionResponse):
        return result

    cur.status = "superseded"
    session.pending_action = result
    session.action_history.append(result)
    session.state = SessionState.AWAITING_APPROVAL
    session.log("action_revised", action_id=result.action_id, from_version=cur.version,
                to_version=result.version, total_inr=result.total_inr)
    return _awaiting(result, prefix="Updated. ")


def approve_order(session: Session, params: dict[str, Any]) -> ActionResponse:
    p = ApproveOrderParams(**params)
    key = f"{p.action_id}:{p.version}"

    # Idempotent replay: same approval -> same result, no new order.
    if key in session.approvals:
        session.log("approval_replayed", action_id=p.action_id, version=p.version)
        return ActionResponse(**session.approvals[key])

    cur = session.pending_action
    known = next((a for a in session.action_history
                  if a.action_id == p.action_id and a.version == p.version), None)
    if known is None:
        session.log("approval_rejected", reason="unknown_action", action_id=p.action_id, version=p.version)
        return _reject("I can't find that draft in this call, so nothing was created.")
    if known.status == "cancelled":
        session.log("approval_rejected", reason="cancelled", action_id=p.action_id, version=p.version)
        return _reject("That draft was cancelled, so nothing was created.")
    if cur is None or known is not cur or cur.status != "pending":
        session.log("approval_rejected", reason="stale_version", action_id=p.action_id, version=p.version)
        extra = {}
        if cur and cur.status == "pending":
            extra = {"current_action_id": cur.action_id, "current_version": cur.version}
        return _reject("That version of the draft has been replaced, so nothing was created. "
                       + (f"The current draft is: {_describe(cur)} Shall I create that one?" if extra else ""),
                       **extra)

    # Execute.
    session.state = SessionState.EXECUTING
    product = catalog.products[cur.product_id]
    if cur.quantity > product.inventory:  # re-check at execution time
        session.state = SessionState.FAILED
        session.log("execution_failed", action_id=cur.action_id, reason="insufficient_inventory")
        return ActionResponse(status="error", spoken_summary="Stock changed and the order could not be created.")

    order = Order(order_id=store.next_order_id(), action_id=cur.action_id, version=cur.version,
                  customer_id=cur.customer_id, customer_name=cur.customer_name,
                  product_id=cur.product_id, product_name=cur.product_name,
                  quantity=cur.quantity, unit_price_inr=cur.unit_price_inr,
                  total_inr=cur.total_inr, created_at=now_iso())
    session.orders[order.order_id] = order
    cur.status = "approved"
    session.state = SessionState.COMPLETED
    session.log("order_created", order_id=order.order_id, action_id=cur.action_id,
                version=cur.version, total_inr=order.total_inr)

    spoken_id = " ".join(order.order_id.split("-")[-1])  # "1 0 0 1" reads better on TTS
    resp = ActionResponse(
        status="completed", order_id=order.order_id, action_id=cur.action_id, version=cur.version,
        spoken_summary=(f"Done. Draft order {order.order_id} is created for {order.customer_name}: "
                        f"{order.quantity} {order.product_name}s, total {_rupees(order.total_inr)}. "
                        f"Your order number is {spoken_id}."),
        data=order.model_dump(),
    )
    session.approvals[key] = resp.model_dump()
    return resp


def cancel_order(session: Session, params: dict[str, Any]) -> ActionResponse:
    p = CancelOrderParams(**params)
    cur = session.pending_action
    if cur is None or cur.status != "pending":
        return ActionResponse(status="ok", spoken_summary="There is no pending draft to cancel.")
    if p.action_id and p.action_id != cur.action_id:
        return _reject("That draft is not the current one.")
    cur.status = "cancelled"
    session.state = SessionState.CANCELLED
    session.log("action_cancelled", action_id=cur.action_id, version=cur.version)
    return ActionResponse(status="cancelled", action_id=cur.action_id, version=cur.version,
                          spoken_summary="Okay, I've cancelled that draft. Nothing was created.")


HANDLERS: dict[str, Callable[[Session, dict[str, Any]], ActionResponse]] = {
    "list_products": list_products,
    "calculate_quote": calculate_quote,
    "prepare_order": prepare_order,
    "revise_order": revise_order,
    "approve_order": approve_order,
    "cancel_order": cancel_order,
    "get_order_status": get_order_status,
}
assert set(HANDLERS) == policy.ALLOWED_ACTIONS


def dispatch(session_id: str, action: str, parameters: dict[str, Any]) -> ActionResponse:
    action = (action or "").strip().lower()
    with store.lock:
        session = store.get_or_create(session_id)
        if not policy.is_allowed(action):
            session.log("action_blocked", action=action[:64], reason="not_allowlisted")
            return _reject("Sorry, I can't do that over the phone yet. I can give quotes, and prepare, "
                           "change, approve or cancel draft orders.")
        if not policy.check_authorized(session, action):
            session.state = SessionState.NEEDS_AUTH
            session.log("action_blocked", action=action, reason="not_authenticated")
            return _reject("You need to be an authorized business user for that. "
                           "I can still answer general questions.")
        session.log("action_received", action=action, parameter_keys=sorted(parameters.keys()))
        try:
            return HANDLERS[action](session, parameters)
        except ValidationError as e:
            fields = sorted({str(err["loc"][0]) for err in e.errors() if err.get("loc")})
            session.log("validation_error", action=action, fields=fields)
            return ActionResponse(status="needs_input", data={"invalid_fields": fields},
                                  spoken_summary=f"I need valid values for: {', '.join(fields)}.")
