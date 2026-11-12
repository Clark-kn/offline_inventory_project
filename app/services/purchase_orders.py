
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import (
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderReceipt,
    PurchaseOrderReceiptItem,
    PurchaseOrderClosure,
    PurchaseOrderClosureItem,
    Supplier,
)
from app.security.permissions import require_admin, require_authenticated, require_transaction_access
from app.services.audit import log_action
from app.services.stock_ledger import record_movement


ORDER_STATUSES = {
    "open",
    "partially_received",
    "partially_closed",
    "completed",
    "closed",
}

CLOSURE_REASONS = {
    "supplier_out_of_stock",
    "product_discontinued",
    "supplier_cancelled_remainder",
    "no_longer_required",
    "quality_specification_issue",
    "price_terms_changed",
    "other",
}


class PurchaseOrderError(Exception):
    """Base exception for purchase-order operations."""


class PurchaseOrderNotFoundError(PurchaseOrderError):
    pass


class PurchaseOrderItemNotFoundError(PurchaseOrderError):
    pass


class PurchaseOrderValidationError(PurchaseOrderError):
    pass


class PurchaseOrderStateError(PurchaseOrderError):
    pass


class EmptyPurchaseOrderError(PurchaseOrderValidationError):
    pass


@dataclass(frozen=True)
class PurchaseOrderLineItem:
    product_id: int
    ordered_quantity: Decimal
    unit_price: Decimal


@dataclass(frozen=True)
class PurchaseOrderReceiptLineItem:
    purchase_order_item_id: int
    quantity: Decimal


@dataclass(frozen=True)
class PurchaseOrderClosureLineItem:
    purchase_order_item_id: int
    quantity: Decimal
    reason_code: str
    explanation: str | None = None


@dataclass(frozen=True)
class PurchaseOrderLineBalance:
    item: PurchaseOrderItem
    received_quantity: Decimal
    closed_quantity: Decimal
    outstanding_quantity: Decimal


def _decimal(value, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise PurchaseOrderValidationError(
            f"{field_name} must be a valid number."
        )

    if not result.is_finite():
        raise PurchaseOrderValidationError(
            f"{field_name} must be a finite number."
        )

    return result


def _positive_quantity(value, field_name="Quantity") -> Decimal:
    result = _decimal(value, field_name)
    if result <= 0:
        raise PurchaseOrderValidationError(
            f"{field_name} must be greater than zero."
        )
    return result


def _nonnegative_price(value) -> Decimal:
    result = _decimal(value, "Unit cost")
    if result < 0:
        raise PurchaseOrderValidationError(
            "Unit cost cannot be negative."
        )
    return result


def _optional_text(value, field_name, max_length):
    if value is None:
        return None

    result = str(value).strip()
    if not result:
        return None

    if len(result) > max_length:
        raise PurchaseOrderValidationError(
            f"{field_name} cannot exceed {max_length} characters."
        )

    return result


def _get_order(session: Session, purchase_order_id: int):
    order = session.get(PurchaseOrder, purchase_order_id)
    if order is None:
        raise PurchaseOrderNotFoundError(
            f"Purchase order {purchase_order_id} does not exist."
        )
    return order


def _calculate_line_balances(
    session: Session,
    purchase_order_id: int,
) -> list[PurchaseOrderLineBalance]:
    order = _get_order(session, purchase_order_id)

    order_items = session.scalars(
        select(PurchaseOrderItem)
        .where(PurchaseOrderItem.purchase_order_id == order.id)
        .order_by(PurchaseOrderItem.id)
    ).all()

    received = {item.id: Decimal("0") for item in order_items}
    closed = {item.id: Decimal("0") for item in order_items}

    receipt_rows = session.execute(
        select(
            PurchaseOrderReceiptItem.purchase_order_item_id,
            PurchaseOrderReceiptItem.quantity,
        )
        .join(
            PurchaseOrderReceipt,
            PurchaseOrderReceipt.id == PurchaseOrderReceiptItem.receipt_id,
        )
        .where(PurchaseOrderReceipt.purchase_order_id == order.id)
    ).all()

    for item_id, quantity in receipt_rows:
        if item_id in received:
            received[item_id] += quantity

    closure_rows = session.execute(
        select(
            PurchaseOrderClosureItem.purchase_order_item_id,
            PurchaseOrderClosureItem.quantity,
        )
        .join(
            PurchaseOrderClosure,
            PurchaseOrderClosure.id == PurchaseOrderClosureItem.closure_id,
        )
        .where(PurchaseOrderClosure.purchase_order_id == order.id)
    ).all()

    for item_id, quantity in closure_rows:
        if item_id in closed:
            closed[item_id] += quantity

    balances = []

    for item in order_items:
        received_quantity = received[item.id]
        closed_quantity = closed[item.id]
        outstanding = (
            item.ordered_quantity
            - received_quantity
            - closed_quantity
        )

        balances.append(
            PurchaseOrderLineBalance(
                item=item,
                received_quantity=received_quantity,
                closed_quantity=closed_quantity,
                outstanding_quantity=outstanding,
            )
        )

    return balances


def _refresh_order_status(
    session: Session,
    order: PurchaseOrder,
) -> str:
    balances = _calculate_line_balances(session, order.id)

    if not balances:
        raise PurchaseOrderStateError(
            "A purchase order cannot have no order lines."
        )

    has_received = any(
        balance.received_quantity > 0 for balance in balances
    )
    has_closed = any(
        balance.closed_quantity > 0 for balance in balances
    )
    has_outstanding = any(
        balance.outstanding_quantity > 0 for balance in balances
    )

    if not has_outstanding:
        order.status = "closed" if has_closed else "completed"
    elif has_closed:
        order.status = "partially_closed"
    elif has_received:
        order.status = "partially_received"
    else:
        order.status = "open"

    session.flush()
    return order.status


def list_purchase_orders(session: Session):
    require_authenticated()
    """Return purchase orders, newest first."""
    return session.scalars(
        select(PurchaseOrder).order_by(
            PurchaseOrder.created_at.desc(),
            PurchaseOrder.id.desc(),
        )
    ).all()


def get_purchase_order_balances(
    session: Session,
    purchase_order_id: int,
) -> list[PurchaseOrderLineBalance]:
    require_authenticated()
    """Return each order line with calculated received, closed and outstanding quantities."""
    return _calculate_line_balances(session, purchase_order_id)


def create_purchase_order(
    session: Session,
    supplier_id: int | None,
    reference: str | None,
    items: list[PurchaseOrderLineItem],
    notes: str | None = None,
) -> PurchaseOrder:
    actor = require_admin()

    if not items:
        raise EmptyPurchaseOrderError(
            "A purchase order must contain at least one product."
        )

    reference = _optional_text(reference, "Reference", 200)
    notes = _optional_text(notes, "Notes", 500)

    if supplier_id is not None:
        supplier = session.get(Supplier, supplier_id)
        if supplier is None:
            raise PurchaseOrderValidationError(
                f"Supplier {supplier_id} does not exist."
            )
        if not supplier.is_active:
            raise PurchaseOrderValidationError(
                "An inactive supplier cannot be used for a new purchase order."
            )

    prepared_items = []
    seen_products = set()

    for line in items:
        if line.product_id in seen_products:
            raise PurchaseOrderValidationError(
                f"Product {line.product_id} appears more than once in this order."
            )
        seen_products.add(line.product_id)

        quantity = _positive_quantity(
            line.ordered_quantity,
            "Ordered quantity",
        )
        unit_price = _nonnegative_price(line.unit_price)

        product = session.get(Product, line.product_id)
        if product is None:
            raise PurchaseOrderValidationError(
                f"Product {line.product_id} does not exist."
            )
        if not product.is_active:
            raise PurchaseOrderValidationError(
                f"Inactive product '{product.name}' cannot be ordered."
            )

        prepared_items.append(
            (product.id, quantity, unit_price)
        )

    order = PurchaseOrder(
        supplier_id=supplier_id,
        reference=reference,
        status="open",
        created_by_user_id=actor.id,
        notes=notes,
    )
    session.add(order)
    session.flush()

    for product_id, quantity, unit_price in prepared_items:
        session.add(
            PurchaseOrderItem(
                purchase_order_id=order.id,
                product_id=product_id,
                ordered_quantity=quantity,
                unit_price=unit_price,
            )
        )

    session.flush()

    log_action(
        session,
        "purchase_order_created",
        f"purchase_order_id={order.id} reference={reference} "
        f"lines={len(prepared_items)} created_by={actor.id}",
    )

    session.flush()
    return order


def record_purchase_order_receipt(
    session: Session,
    purchase_order_id: int,
    items: list[PurchaseOrderReceiptLineItem],
    reference: str | None = None,
    notes: str | None = None,
) -> PurchaseOrderReceipt:
    actor = require_transaction_access()
    order = _get_order(session, purchase_order_id)
    supplier = session.get(Supplier, order.supplier_id) if order.supplier_id else None

    if not items:
        raise EmptyPurchaseOrderError(
            "A receipt must contain at least one received quantity."
        )

    reference = _optional_text(reference, "Receipt reference", 200)
    notes = _optional_text(notes, "Receipt notes", 500)

    balances = _calculate_line_balances(session, order.id)
    balance_by_id = {
        balance.item.id: balance for balance in balances
    }

    prepared_items = []
    seen_items = set()

    for line in items:
        item_id = line.purchase_order_item_id

        if item_id in seen_items:
            raise PurchaseOrderValidationError(
                f"Order line {item_id} appears more than once in this receipt."
            )
        seen_items.add(item_id)

        balance = balance_by_id.get(item_id)
        if balance is None:
            raise PurchaseOrderItemNotFoundError(
                f"Order line {item_id} does not belong to purchase order {order.id}."
            )

        quantity = _positive_quantity(
            line.quantity,
            "Received quantity",
        )

        if quantity > balance.outstanding_quantity:
            raise PurchaseOrderValidationError(
                f"Cannot receive {quantity} for order line {item_id}; "
                f"only {balance.outstanding_quantity} remains outstanding."
            )

        prepared_items.append((balance, quantity))

    receipt = PurchaseOrderReceipt(
        purchase_order_id=order.id,
        reference=reference,
        created_by_user_id=actor.id,
        notes=notes,
    )
    session.add(receipt)
    session.flush()

    movement_reference = (
        reference or f"PO-{order.id}-REC-{receipt.id}"
    )

    for balance, quantity in prepared_items:
        session.add(
            PurchaseOrderReceiptItem(
                receipt_id=receipt.id,
                purchase_order_item_id=balance.item.id,
                quantity=quantity,
            )
        )

        record_movement(
            session,
            product_id=balance.item.product_id,
            qty_delta=quantity,
            reason="purchase_order_receipt",
            reference=movement_reference,
            user_id=actor.id,
            party_type="Supplier" if supplier else None,
            party_name=supplier.name if supplier else None,
        )

        log_action(
            session,
            "purchase_order_line_received",
            f"po_id={order.id} receipt_id={receipt.id} "
            f"item_id={balance.item.id} quantity={quantity} "
            f"user_id={actor.id}",
        )

    _refresh_order_status(session, order)

    log_action(
        session,
        "purchase_order_receipt_recorded",
        f"po_id={order.id} receipt_id={receipt.id} "
        f"reference={movement_reference} lines={len(prepared_items)}",
    )

    session.flush()
    return receipt


def close_purchase_order_outstanding(
    session: Session,
    purchase_order_id: int,
    items: list[PurchaseOrderClosureLineItem],
    notes: str | None = None,
) -> PurchaseOrderClosure:
    actor = require_admin()
    order = _get_order(session, purchase_order_id)

    if not items:
        raise EmptyPurchaseOrderError(
            "Select at least one outstanding quantity to close."
        )

    notes = _optional_text(notes, "Closure notes", 500)

    balances = _calculate_line_balances(session, order.id)
    balance_by_id = {
        balance.item.id: balance for balance in balances
    }

    prepared_items = []
    seen_items = set()

    for line in items:
        item_id = line.purchase_order_item_id

        if item_id in seen_items:
            raise PurchaseOrderValidationError(
                f"Order line {item_id} appears more than once in this closure."
            )
        seen_items.add(item_id)

        balance = balance_by_id.get(item_id)
        if balance is None:
            raise PurchaseOrderItemNotFoundError(
                f"Order line {item_id} does not belong to purchase order {order.id}."
            )

        quantity = _positive_quantity(
            line.quantity,
            "Closure quantity",
        )

        if quantity > balance.outstanding_quantity:
            raise PurchaseOrderValidationError(
                f"Cannot close {quantity} for order line {item_id}; "
                f"only {balance.outstanding_quantity} remains outstanding."
            )

        reason_code = (line.reason_code or "").strip()
        if reason_code not in CLOSURE_REASONS:
            raise PurchaseOrderValidationError(
                "Choose a valid closure reason from the approved list."
            )

        explanation = _optional_text(
            line.explanation,
            "Closure explanation",
            500,
        )

        if reason_code == "other" and explanation is None:
            raise PurchaseOrderValidationError(
                "An explanation is required when the reason is 'Other'."
            )

        prepared_items.append(
            (balance, quantity, reason_code, explanation)
        )

    closure = PurchaseOrderClosure(
        purchase_order_id=order.id,
        closed_by_user_id=actor.id,
        notes=notes,
    )
    session.add(closure)
    session.flush()

    for balance, quantity, reason_code, explanation in prepared_items:
        closure_item = PurchaseOrderClosureItem(
            closure_id=closure.id,
            purchase_order_item_id=balance.item.id,
            quantity=quantity,
            reason_code=reason_code,
            explanation=explanation,
        )
        session.add(closure_item)

        session.flush()

        log_action(
            session,
            "purchase_order_quantity_closed",
            f"po_id={order.id} closure_id={closure.id} "
            f"closure_item_id={closure_item.id} "
            f"item_id={balance.item.id} quantity={quantity} "
            f"reason={reason_code} user_id={actor.id}",
        )

    _refresh_order_status(session, order)

    log_action(
        session,
        "purchase_order_outstanding_closed",
        f"po_id={order.id} closure_id={closure.id} "
        f"lines={len(prepared_items)} closed_by={actor.id}",
    )

    session.flush()
    return closure
