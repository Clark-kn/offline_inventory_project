from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.data.models import (
    Customer, Product, Purchase, PurchaseItem, Sale, SaleItem,
    StockAdjustment, Supplier,
)
from app.security.permissions import require_transaction_access
from app.services.audit import log_action
from app.services.stock_ledger import (
    ProductNotFoundError, record_movement
)


@dataclass
class LineItem:
    product_id: int
    quantity: Decimal
    unit_price: Decimal


class EmptyTransactionError(Exception):
    pass


class InvalidLineItemError(Exception):
    pass


class SalePriceMismatchError(InvalidLineItemError):
    """Raised when a sale line does not use the product's authorized price."""


class ProductInactiveError(InvalidLineItemError):
    """Raised when a purchase or sale references an inactive product."""


class SupplierNotFoundError(InvalidLineItemError):
    """Raised when a purchase references a nonexistent supplier."""


class SupplierInactiveError(InvalidLineItemError):
    """Raised when a purchase references an inactive supplier."""


class CustomerNotFoundError(InvalidLineItemError):
    """Raised when a sale references a nonexistent customer."""


class CustomerInactiveError(InvalidLineItemError):
    """Raised when a sale references an inactive customer."""


def _validate_line_items(items: list[LineItem]) -> None:
    for item in items:
        if item.quantity <= 0:
            raise InvalidLineItemError(
                f"Line item quantity must be greater than zero (got {item.quantity})"
            )
        if item.unit_price < 0:
            raise InvalidLineItemError(
                f"Line item price cannot be negative (got {item.unit_price})"
            )


def create_purchase(
    session: Session,
    supplier_id: int | None,
    reference: str | None,
    items: list[LineItem],
) -> Purchase:
    actor = require_transaction_access()

    if not items:
        raise EmptyTransactionError("A purchase needs at least one line item")
    _validate_line_items(items)

    # Supplier is optional. If supplied, it must exist and be active.
    supplier = None
    if supplier_id is not None:
        supplier = session.get(Supplier, supplier_id)
        if supplier is None:
            raise SupplierNotFoundError(
                f"Supplier {supplier_id} does not exist."
            )
        if not supplier.is_active:
            raise SupplierInactiveError(
                f"Supplier '{supplier.name}' is inactive and cannot be used "
                "for a new purchase."
            )

    for item in items:
        product = session.get(Product, item.product_id)
        if product is None:
            raise ProductNotFoundError(
                f"Product {item.product_id} does not exist"
            )
        if not product.is_active:
            raise ProductInactiveError(
                f"Product '{product.name}' is inactive and cannot be purchased."
            )

    purchase = Purchase(
        supplier_id=supplier_id,
        reference=reference,
        created_by_user_id=actor.id,
    )
    session.add(purchase)
    session.flush()

    for item in items:
        session.add(
            PurchaseItem(
                purchase_id=purchase.id,
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=item.unit_price,
            )
        )
        record_movement(
            session,
            item.product_id,
            item.quantity,
            reason="purchase",
            reference=reference or f"purchase#{purchase.id}",
            user_id=actor.id,
            party_type="Supplier" if supplier else None,
            party_name=supplier.name if supplier else None,
        )

    log_action(
        session,
        "purchase_created",
        f"purchase_id={purchase.id} reference={reference or ''}",
    )
    session.flush()
    return purchase


def create_sale(
    session: Session,
    customer_id: int | None,
    reference: str | None,
    items: list[LineItem],
) -> Sale:
    actor = require_transaction_access()

    if not items:
        raise EmptyTransactionError("A sale needs at least one line item")
    _validate_line_items(items)

    # Customer is optional. If supplied, it must exist and be active.
    customer = None
    if customer_id is not None:
        customer = session.get(Customer, customer_id)
        if customer is None:
            raise CustomerNotFoundError(
                f"Customer {customer_id} does not exist."
            )
        if not customer.is_active:
            raise CustomerInactiveError(
                f"Customer '{customer.name}' is inactive and cannot be used "
                "for a new sale."
            )

    # Never trust a price supplied by the UI or caller. The product's
    # stored selling price is the authoritative price for every sale.
    for item in items:
        product = session.get(Product, item.product_id)
        if product is None:
            raise ProductNotFoundError(
                f"Product {item.product_id} does not exist"
            )
        if not product.is_active:
            raise ProductInactiveError(
                f"Product '{product.name}' is inactive and cannot be sold."
            )
        if item.unit_price != product.price:
            raise SalePriceMismatchError(
                f"Sale price for product '{product.name}' must be "
                f"{product.price}; received {item.unit_price}. "
                "Update the product selling price first if it has changed."
            )

    sale = Sale(
        customer_id=customer_id,
        reference=reference,
        created_by_user_id=actor.id,
    )
    session.add(sale)
    session.flush()

    for item in items:
        session.add(
            SaleItem(
                sale_id=sale.id,
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=item.unit_price,
            )
        )
        record_movement(
            session,
            item.product_id,
            -item.quantity,
            reason="sale",
            reference=reference or f"sale#{sale.id}",
            user_id=actor.id,
            party_type="Customer" if customer else None,
            party_name=customer.name if customer else None,
        )

    log_action(
        session,
        "sale_created",
        f"sale_id={sale.id} reference={reference or ''}",
    )
    session.flush()
    return sale


def create_adjustment(
    session: Session,
    product_id: int,
    quantity_delta: Decimal,
    reason: str,
) -> StockAdjustment:
    actor = require_transaction_access()

    reason = reason.strip()
    if not reason:
        raise ValueError("Stock adjustment requires a reason")
    if quantity_delta == 0:
        raise InvalidLineItemError("Adjustment quantity change cannot be zero")

    adjustment = StockAdjustment(
        product_id=product_id,
        created_by_user_id=actor.id,
        quantity_delta=quantity_delta,
        reason=reason,
    )
    session.add(adjustment)
    session.flush()

    record_movement(
        session,
        product_id,
        quantity_delta,
        reason="adjustment",
        reference=reason,
        user_id=actor.id,
    )
    log_action(
        session,
        "stock_adjustment",
        f"product_id={product_id} delta={quantity_delta} reason={reason}",
    )

    return adjustment
