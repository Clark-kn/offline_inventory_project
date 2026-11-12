from decimal import Decimal

from sqlalchemy.orm import Session

from app.data.models.product import Product
from app.data.models.stock_transaction import StockTransaction
from app.security.permissions import (
    PermissionDeniedError,
    require_transaction_access,
)


class InsufficientStockError(Exception):
    pass


class ProductNotFoundError(Exception):
    pass


def record_movement(
    session: Session,
    product_id: int,
    qty_delta: Decimal,
    reason: str,
    reference: str | None = None,
    allow_negative: bool = False,
    user_id: int | None = None,
    party_type: str | None = None,
    party_name: str | None = None,
) -> StockTransaction:
    """Apply a stock movement and append it to the stock ledger.

    The movement is part of the caller's database transaction.
    Every movement requires an authenticated transaction-authorized user.
    Attribution always belongs to that authenticated user.
    """
    actor = require_transaction_access()

    if user_id is not None and user_id != actor.id:
        raise PermissionDeniedError(
            "Stock movement attribution must match the logged-in user."
        )

    if (party_type is None) != (party_name is None):
        raise ValueError("Party type and name must both be supplied.")

    if party_type is not None:
        if party_type not in {"Supplier", "Customer"}:
            raise ValueError("Party type must be Supplier or Customer.")
        if not party_name.strip():
            raise ValueError("Party name cannot be empty.")

    product = session.get(Product, product_id, with_for_update=True)
    if product is None:
        raise ProductNotFoundError(f"Product {product_id} does not exist")

    new_balance = product.current_stock + qty_delta
    if new_balance < 0 and not allow_negative:
        raise InsufficientStockError(
            f"Movement would take product {product_id} stock to {new_balance}"
        )

    product.current_stock = new_balance

    txn = StockTransaction(
        product_id=product_id,
        user_id=actor.id,
        qty_delta=qty_delta,
        balance_after=new_balance,
        reason=reason,
        reference=reference,
        party_type=party_type,
        party_name=party_name.strip() if party_name else None,
    )
    session.add(txn)
    session.flush()
    return txn
