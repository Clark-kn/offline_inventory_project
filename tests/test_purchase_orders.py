from decimal import Decimal

import pytest
from sqlalchemy import select, func

from app.data.db import create_db_engine, init_db, make_session_factory
from app.data.models import (
    AuditLog,
    PurchaseOrderClosureItem,
    PurchaseOrderReceipt,
    PurchaseOrder,
    PurchaseOrderClosure,
    StockTransaction,
)
from app.security.permissions import PermissionDeniedError
from app.security.session_context import get_current_user, set_current_user
from app.services.auth import create_user
from app.services.master_data import (
    create_product,
    save_supplier,
    set_supplier_active,
    set_product_active,
)
from app.services.purchase_orders import (
    PurchaseOrderLineItem,
    PurchaseOrderReceiptLineItem,
    PurchaseOrderClosureLineItem,
    PurchaseOrderValidationError,
    EmptyPurchaseOrderError,
    PurchaseOrderItemNotFoundError,
    PurchaseOrderNotFoundError,
    create_purchase_order,
    record_purchase_order_receipt,
    close_purchase_order_outstanding,
    get_purchase_order_balances,
    list_purchase_orders,
)


@pytest.fixture(autouse=True)
def reset_current_user():
    previous = get_current_user()
    set_current_user(None)
    yield
    set_current_user(previous)


@pytest.fixture()
def session():
    engine = create_db_engine(db_path=":memory:")
    init_db(engine)
    factory = make_session_factory(engine)

    with factory() as s:
        admin = create_user(
            s, "admin", "test-password-123", role="admin"
        )
        s.commit()
        set_current_user(admin)

        yield s

        set_current_user(None)


def _product(session, sku="PO-SKU-1", opening=Decimal("0")):
    return create_product(
        session,
        sku=sku,
        name="Test Beverage",
        category_id=None,
        unit_id=None,
        location_id=None,
        price=Decimal("1500"),
        reorder_level=Decimal("5"),
        opening_stock=opening,
    )


def _create_order(session, product, quantity=Decimal("10")):
    return create_purchase_order(
        session,
        supplier_id=None,
        reference="PO-TEST-001",
        items=[
            PurchaseOrderLineItem(
                product_id=product.id,
                ordered_quantity=quantity,
                unit_price=Decimal("1000"),
            )
        ],
    )


def _order_item(session, order):
    balances = get_purchase_order_balances(session, order.id)
    assert len(balances) == 1
    return balances[0].item


def test_create_purchase_order(session):
    product = _product(session)
    order = _create_order(session, product)

    session.commit()
    session.refresh(order)
    session.refresh(product)

    assert order.id is not None
    assert order.status == "open"
    assert order.reference == "PO-TEST-001"
    assert len(get_purchase_order_balances(session, order.id)) == 1
    assert _order_item(session, order).ordered_quantity == Decimal("10")
    assert _order_item(session, order).unit_price == Decimal("1000")
    assert product.current_stock == Decimal("0")


def test_list_purchase_orders(session):
    product = _product(session)
    order = _create_order(session, product)

    session.commit()
    orders = list_purchase_orders(session)

    assert len(orders) == 1
    assert orders[0].id == order.id


def test_partial_receipt_updates_stock_and_status(session):
    product = _product(session)
    order = _create_order(session, product)
    order_item = _order_item(session, order)

    receipt = record_purchase_order_receipt(
        session,
        order.id,
        [
            PurchaseOrderReceiptLineItem(
                purchase_order_item_id=order_item.id,
                quantity=Decimal("4"),
            )
        ],
        reference="DELIVERY-001",
    )

    session.commit()
    session.refresh(product)
    session.refresh(order)

    assert receipt.id is not None
    assert product.current_stock == Decimal("4")
    assert order.status == "partially_received"

    balances = get_purchase_order_balances(session, order.id)

    assert balances[0].received_quantity == Decimal("4")
    assert balances[0].closed_quantity == Decimal("0")
    assert balances[0].outstanding_quantity == Decimal("6")


def test_full_receipt_completes_order(session):
    product = _product(session)
    order = _create_order(session, product)
    order_item = _order_item(session, order)

    record_purchase_order_receipt(
        session,
        order.id,
        [
            PurchaseOrderReceiptLineItem(
                purchase_order_item_id=order_item.id,
                quantity=Decimal("10"),
            )
        ],
    )

    session.commit()
    session.refresh(product)
    session.refresh(order)

    assert product.current_stock == Decimal("10")
    assert order.status == "completed"


def test_multiple_receipts_cannot_receive_more_than_ordered(session):
    product = _product(session)
    order = _create_order(session, product)
    order_item = _order_item(session, order)

    record_purchase_order_receipt(
        session,
        order.id,
        [
            PurchaseOrderReceiptLineItem(
                purchase_order_item_id=order_item.id,
                quantity=Decimal("6"),
            )
        ],
    )

    session.flush()

    with pytest.raises(PurchaseOrderValidationError):
        record_purchase_order_receipt(
            session,
            order.id,
            [
                PurchaseOrderReceiptLineItem(
                    purchase_order_item_id=order_item.id,
                    quantity=Decimal("5"),
                )
            ],
        )

    session.commit()
    session.refresh(product)

    assert product.current_stock == Decimal("6")

    receipts = session.scalars(
        select(PurchaseOrderReceipt).where(
            PurchaseOrderReceipt.purchase_order_id == order.id
        )
    ).all()

    assert len(receipts) == 1


def test_receipt_rejects_item_from_another_order(session):
    product = _product(session)
    first_order = _create_order(session, product)

    second_order = create_purchase_order(
        session,
        supplier_id=None,
        reference="PO-TEST-002",
        items=[
            PurchaseOrderLineItem(
                product_id=product.id,
                ordered_quantity=Decimal("5"),
                unit_price=Decimal("900"),
            )
        ],
    )

    second_item = _order_item(session, second_order)

    with pytest.raises(PurchaseOrderItemNotFoundError):
        record_purchase_order_receipt(
            session,
            first_order.id,
            [
                PurchaseOrderReceiptLineItem(
                    purchase_order_item_id=second_item.id,
                    quantity=Decimal("2"),
                )
            ],
        )

    session.commit()
    session.refresh(product)

    assert product.current_stock == Decimal("0")


def test_closing_outstanding_quantity_does_not_increase_stock(session):
    product = _product(session)
    order = _create_order(session, product)
    order_item = _order_item(session, order)

    closure = close_purchase_order_outstanding(
        session,
        order.id,
        [
            PurchaseOrderClosureLineItem(
                purchase_order_item_id=order_item.id,
                quantity=Decimal("10"),
                reason_code="supplier_out_of_stock",
            )
        ],
    )

    session.commit()
    session.refresh(product)
    session.refresh(order)

    assert closure.id is not None
    assert product.current_stock == Decimal("0")
    assert order.status == "closed"

    balances = get_purchase_order_balances(session, order.id)

    assert balances[0].received_quantity == Decimal("0")
    assert balances[0].closed_quantity == Decimal("10")
    assert balances[0].outstanding_quantity == Decimal("0")


def test_partial_receipt_then_partial_closure(session):
    product = _product(session)
    order = _create_order(session, product)
    order_item = _order_item(session, order)

    record_purchase_order_receipt(
        session,
        order.id,
        [
            PurchaseOrderReceiptLineItem(
                purchase_order_item_id=order_item.id,
                quantity=Decimal("2"),
            )
        ],
    )

    close_purchase_order_outstanding(
        session,
        order.id,
        [
            PurchaseOrderClosureLineItem(
                purchase_order_item_id=order_item.id,
                quantity=Decimal("3"),
                reason_code="supplier_cancelled_remainder",
            )
        ],
    )

    session.commit()
    session.refresh(product)
    session.refresh(order)

    assert product.current_stock == Decimal("2")
    assert order.status == "partially_closed"

    balances = get_purchase_order_balances(session, order.id)

    assert balances[0].received_quantity == Decimal("2")
    assert balances[0].closed_quantity == Decimal("3")
    assert balances[0].outstanding_quantity == Decimal("5")


def test_other_closure_reason_requires_explanation(session):
    product = _product(session)
    order = _create_order(session, product)
    order_item = _order_item(session, order)

    with pytest.raises(PurchaseOrderValidationError):
        close_purchase_order_outstanding(
            session,
            order.id,
            [
                PurchaseOrderClosureLineItem(
                    purchase_order_item_id=order_item.id,
                    quantity=Decimal("2"),
                    reason_code="other",
                    explanation=None,
                )
            ],
        )

    session.commit()

    closure_items = session.scalars(
        select(PurchaseOrderClosureItem)
    ).all()

    assert len(closure_items) == 0


def test_closure_saves_full_explanation_and_audit_reference(session):
    product = _product(session)
    order = _create_order(session, product)
    order_item = _order_item(session, order)

    explanation = (
        "The supplier confirmed that this product is unavailable "
        "and cannot be delivered this month."
    )

    close_purchase_order_outstanding(
        session,
        order.id,
        [
            PurchaseOrderClosureLineItem(
                purchase_order_item_id=order_item.id,
                quantity=Decimal("5"),
                reason_code="other",
                explanation=explanation,
            )
        ],
    )

    session.commit()

    closure_item = session.scalars(
        select(PurchaseOrderClosureItem)
    ).one()

    assert closure_item.quantity == Decimal("5")
    assert closure_item.reason_code == "other"
    assert closure_item.explanation == explanation

    audit = session.scalars(
        select(AuditLog).where(
            AuditLog.action == "purchase_order_quantity_closed"
        )
    ).one()

    assert audit.user_id == get_current_user().id
    assert f"closure_item_id={closure_item.id}" in audit.details
    assert "reason=other" in audit.details


def test_operator_cannot_create_purchase_order(session):
    product = _product(session)

    operator = create_user(
        session,
        "operator",
        "operator-password-123",
        role="operator",
    )
    session.commit()

    set_current_user(operator)

    with pytest.raises(PermissionDeniedError):
        _create_order(session, product)


def test_operator_can_record_purchase_order_receipt(session):
    product = _product(session)
    order = _create_order(session, product)
    order_item = _order_item(session, order)

    operator = create_user(
        session,
        "operator",
        "operator-password-123",
        role="operator",
    )
    session.commit()

    set_current_user(operator)

    receipt = record_purchase_order_receipt(
        session,
        order.id,
        [
            PurchaseOrderReceiptLineItem(
                purchase_order_item_id=order_item.id,
                quantity=Decimal("3"),
            )
        ],
    )

    session.commit()
    session.refresh(product)

    assert receipt.created_by_user_id == operator.id
    assert product.current_stock == Decimal("3")


def test_receipt_creates_stock_ledger_entry_with_user_attribution(session):
    product = _product(session)
    order = _create_order(session, product)
    supplier = save_supplier(
        session,
        supplier_id=None,
        name="Ledger Receipt Supplier",
        contact="",
        address="",
    )
    order.supplier_id = supplier.id
    session.flush()
    order_item = _order_item(session, order)

    actor = get_current_user()

    record_purchase_order_receipt(
        session,
        order.id,
        [
            PurchaseOrderReceiptLineItem(
                purchase_order_item_id=order_item.id,
                quantity=Decimal("4"),
            )
        ],
        reference="PO-LEDGER-TEST",
    )

    session.commit()

    movements = session.scalars(
        select(StockTransaction).where(
            StockTransaction.reason == "purchase_order_receipt",
            StockTransaction.reference == "PO-LEDGER-TEST",
        )
    ).all()

    assert len(movements) == 1
    assert movements[0].qty_delta == Decimal("4")
    assert movements[0].user_id == actor.id
    assert movements[0].party_type == "Supplier"
    assert movements[0].party_name == supplier.name


def test_purchase_order_does_not_change_product_selling_price(session):
    product = _product(session)
    original_price = product.price

    order = _create_order(session, product)

    record_purchase_order_receipt(
        session,
        order.id,
        [
            PurchaseOrderReceiptLineItem(
                purchase_order_item_id=_order_item(session, order).id,
                quantity=Decimal("5"),
            )
        ],
    )

    session.commit()
    session.refresh(product)

    assert product.price == original_price
    assert _order_item(session, order).unit_price == Decimal("1000")


# ---------------------------------------------------------------------------
# Additional purchase-order validation, permission and integrity tests
# ---------------------------------------------------------------------------

def test_empty_purchase_order_is_rejected_without_creating_order(session):
    before = session.scalars(select(PurchaseOrder)).all()

    with pytest.raises(EmptyPurchaseOrderError):
        create_purchase_order(
            session,
            supplier_id=None,
            reference="EMPTY-PO",
            items=[],
        )

    session.commit()

    assert session.scalars(select(PurchaseOrder)).all() == before


def test_duplicate_product_lines_are_rejected(session):
    product = _product(session)

    with pytest.raises(PurchaseOrderValidationError):
        create_purchase_order(
            session,
            supplier_id=None,
            reference="DUPLICATE-PRODUCT",
            items=[
                PurchaseOrderLineItem(
                    product_id=product.id,
                    ordered_quantity=Decimal("5"),
                    unit_price=Decimal("1000"),
                ),
                PurchaseOrderLineItem(
                    product_id=product.id,
                    ordered_quantity=Decimal("3"),
                    unit_price=Decimal("1000"),
                ),
            ],
        )

    session.commit()

    assert session.scalars(select(PurchaseOrder)).all() == []


@pytest.mark.parametrize(
    "quantity",
    [
        Decimal("0"),
        Decimal("-1"),
        Decimal("NaN"),
        Decimal("Infinity"),
    ],
)
def test_invalid_ordered_quantity_is_rejected(session, quantity):
    product = _product(session)

    with pytest.raises(PurchaseOrderValidationError):
        create_purchase_order(
            session,
            supplier_id=None,
            reference="INVALID-QUANTITY",
            items=[
                PurchaseOrderLineItem(
                    product_id=product.id,
                    ordered_quantity=quantity,
                    unit_price=Decimal("1000"),
                )
            ],
        )

    session.commit()
    assert session.scalars(select(PurchaseOrder)).all() == []


@pytest.mark.parametrize(
    "unit_price",
    [
        Decimal("-0.01"),
        Decimal("NaN"),
        Decimal("Infinity"),
    ],
)
def test_invalid_order_unit_cost_is_rejected(session, unit_price):
    product = _product(session)

    with pytest.raises(PurchaseOrderValidationError):
        create_purchase_order(
            session,
            supplier_id=None,
            reference="INVALID-COST",
            items=[
                PurchaseOrderLineItem(
                    product_id=product.id,
                    ordered_quantity=Decimal("5"),
                    unit_price=unit_price,
                )
            ],
        )

    session.commit()
    assert session.scalars(select(PurchaseOrder)).all() == []


def test_inactive_product_cannot_be_added_to_new_order(session):
    product = _product(session)
    set_product_active(session, product.id, False)
    session.flush()

    with pytest.raises(PurchaseOrderValidationError):
        _create_order(session, product)

    session.commit()
    assert session.scalars(select(PurchaseOrder)).all() == []


def test_inactive_supplier_cannot_be_used_for_new_order(session):
    supplier = save_supplier(
        session,
        supplier_id=None,
        name="Inactive Supplier",
        contact="",
        address="",
    )
    session.flush()

    set_supplier_active(session, supplier.id, False)
    session.flush()

    product = _product(session)

    with pytest.raises(PurchaseOrderValidationError):
        create_purchase_order(
            session,
            supplier_id=supplier.id,
            reference="INACTIVE-SUPPLIER",
            items=[
                PurchaseOrderLineItem(
                    product_id=product.id,
                    ordered_quantity=Decimal("5"),
                    unit_price=Decimal("1000"),
                )
            ],
        )

    session.commit()
    assert session.scalars(select(PurchaseOrder)).all() == []


@pytest.mark.parametrize(
    "quantity",
    [
        Decimal("0"),
        Decimal("-1"),
        Decimal("NaN"),
        Decimal("Infinity"),
    ],
)
def test_invalid_receipt_quantity_is_rejected_without_records(
    session, quantity
):
    product = _product(session)
    order = _create_order(session, product)
    item = _order_item(session, order)

    with pytest.raises(PurchaseOrderValidationError):
        record_purchase_order_receipt(
            session,
            order.id,
            [
                PurchaseOrderReceiptLineItem(
                    purchase_order_item_id=item.id,
                    quantity=quantity,
                )
            ],
        )

    session.commit()

    assert session.scalars(
        select(PurchaseOrderReceipt).where(
            PurchaseOrderReceipt.purchase_order_id == order.id
        )
    ).all() == []

    assert product.current_stock == Decimal("0")

    movements = session.scalars(
        select(StockTransaction).where(
            StockTransaction.reason == "purchase_order_receipt"
        )
    ).all()
    assert movements == []


def test_duplicate_receipt_lines_are_rejected_without_partial_changes(session):
    product = _product(session)
    order = _create_order(session, product)
    item = _order_item(session, order)

    with pytest.raises(PurchaseOrderValidationError):
        record_purchase_order_receipt(
            session,
            order.id,
            [
                PurchaseOrderReceiptLineItem(
                    purchase_order_item_id=item.id,
                    quantity=Decimal("2"),
                ),
                PurchaseOrderReceiptLineItem(
                    purchase_order_item_id=item.id,
                    quantity=Decimal("3"),
                ),
            ],
        )

    session.commit()
    session.refresh(product)

    assert product.current_stock == Decimal("0")
    assert session.scalars(select(PurchaseOrderReceipt)).all() == []
    assert session.scalars(
        select(StockTransaction).where(
            StockTransaction.reason == "purchase_order_receipt"
        )
    ).all() == []


def test_invalid_second_receipt_line_does_not_process_first_line(session):
    first_product = _product(session, sku="PO-FIRST")
    second_product = _product(session, sku="PO-SECOND")

    order = create_purchase_order(
        session,
        supplier_id=None,
        reference="MULTI-LINE-RECEIPT",
        items=[
            PurchaseOrderLineItem(
                product_id=first_product.id,
                ordered_quantity=Decimal("5"),
                unit_price=Decimal("1000"),
            ),
            PurchaseOrderLineItem(
                product_id=second_product.id,
                ordered_quantity=Decimal("5"),
                unit_price=Decimal("1000"),
            ),
        ],
    )

    balances = get_purchase_order_balances(session, order.id)
    first_item = balances[0].item
    second_item = balances[1].item

    with pytest.raises(PurchaseOrderValidationError):
        record_purchase_order_receipt(
            session,
            order.id,
            [
                PurchaseOrderReceiptLineItem(
                    purchase_order_item_id=first_item.id,
                    quantity=Decimal("2"),
                ),
                PurchaseOrderReceiptLineItem(
                    purchase_order_item_id=second_item.id,
                    quantity=Decimal("6"),
                ),
            ],
        )

    session.commit()
    session.refresh(first_product)
    session.refresh(second_product)

    assert first_product.current_stock == Decimal("0")
    assert second_product.current_stock == Decimal("0")
    assert session.scalars(select(PurchaseOrderReceipt)).all() == []

    movements = session.scalars(
        select(StockTransaction).where(
            StockTransaction.reason == "purchase_order_receipt"
        )
    ).all()
    assert movements == []


def test_duplicate_closure_lines_are_rejected_without_partial_changes(session):
    product = _product(session)
    order = _create_order(session, product)
    item = _order_item(session, order)

    with pytest.raises(PurchaseOrderValidationError):
        close_purchase_order_outstanding(
            session,
            order.id,
            [
                PurchaseOrderClosureLineItem(
                    purchase_order_item_id=item.id,
                    quantity=Decimal("2"),
                    reason_code="supplier_out_of_stock",
                ),
                PurchaseOrderClosureLineItem(
                    purchase_order_item_id=item.id,
                    quantity=Decimal("3"),
                    reason_code="supplier_out_of_stock",
                ),
            ],
        )

    session.commit()

    assert session.scalars(select(PurchaseOrderClosure)).all() == []
    assert get_purchase_order_balances(
        session, order.id
    )[0].closed_quantity == Decimal("0")


def test_closure_cannot_exceed_outstanding_quantity(session):
    product = _product(session)
    order = _create_order(session, product)
    item = _order_item(session, order)

    with pytest.raises(PurchaseOrderValidationError):
        close_purchase_order_outstanding(
            session,
            order.id,
            [
                PurchaseOrderClosureLineItem(
                    purchase_order_item_id=item.id,
                    quantity=Decimal("11"),
                    reason_code="supplier_out_of_stock",
                )
            ],
        )

    session.commit()

    assert session.scalars(select(PurchaseOrderClosure)).all() == []
    assert get_purchase_order_balances(
        session, order.id
    )[0].outstanding_quantity == Decimal("10")


def test_invalid_closure_reason_is_rejected(session):
    product = _product(session)
    order = _create_order(session, product)
    item = _order_item(session, order)

    with pytest.raises(PurchaseOrderValidationError):
        close_purchase_order_outstanding(
            session,
            order.id,
            [
                PurchaseOrderClosureLineItem(
                    purchase_order_item_id=item.id,
                    quantity=Decimal("2"),
                    reason_code="supplier_changed_mind",
                )
            ],
        )

    session.commit()
    assert session.scalars(select(PurchaseOrderClosure)).all() == []


def test_operator_cannot_close_outstanding_quantity(session):
    product = _product(session)
    order = _create_order(session, product)
    item = _order_item(session, order)

    operator = create_user(
        session,
        "operator_closure_denied",
        "operator-password-123",
        role="operator",
    )
    session.commit()
    set_current_user(operator)

    with pytest.raises(PermissionDeniedError):
        close_purchase_order_outstanding(
            session,
            order.id,
            [
                PurchaseOrderClosureLineItem(
                    purchase_order_item_id=item.id,
                    quantity=Decimal("2"),
                    reason_code="supplier_out_of_stock",
                )
            ],
        )

    session.commit()
    assert session.scalars(select(PurchaseOrderClosure)).all() == []


def test_viewer_cannot_record_purchase_order_receipt(session):
    product = _product(session)
    order = _create_order(session, product)
    item = _order_item(session, order)

    viewer = create_user(
        session,
        "viewer_receipt_denied",
        "viewer-password-123",
        role="viewer",
    )
    session.commit()
    set_current_user(viewer)

    with pytest.raises(PermissionDeniedError):
        record_purchase_order_receipt(
            session,
            order.id,
            [
                PurchaseOrderReceiptLineItem(
                    purchase_order_item_id=item.id,
                    quantity=Decimal("2"),
                )
            ],
        )

    session.commit()
    session.refresh(product)

    assert product.current_stock == Decimal("0")
    assert session.scalars(select(PurchaseOrderReceipt)).all() == []


def test_manager_can_receive_but_cannot_create_purchase_order(session):
    product = _product(session)
    order = _create_order(session, product)
    item = _order_item(session, order)

    manager = create_user(
        session,
        "manager_po_test",
        "manager-password-123",
        role="manager",
    )
    session.commit()
    set_current_user(manager)

    with pytest.raises(PermissionDeniedError):
        create_purchase_order(
            session,
            supplier_id=None,
            reference="MANAGER-CREATE-DENIED",
            items=[
                PurchaseOrderLineItem(
                    product_id=product.id,
                    ordered_quantity=Decimal("5"),
                    unit_price=Decimal("1000"),
                )
            ],
        )

    receipt = record_purchase_order_receipt(
        session,
        order.id,
        [
            PurchaseOrderReceiptLineItem(
                purchase_order_item_id=item.id,
                quantity=Decimal("2"),
            )
        ],
    )

    session.commit()
    session.refresh(product)

    assert receipt.created_by_user_id == manager.id
    assert product.current_stock == Decimal("2")


def test_receipt_cannot_be_recorded_after_order_is_fully_closed(session):
    product = _product(session)
    order = _create_order(session, product)
    item = _order_item(session, order)

    close_purchase_order_outstanding(
        session,
        order.id,
        [
            PurchaseOrderClosureLineItem(
                purchase_order_item_id=item.id,
                quantity=Decimal("10"),
                reason_code="supplier_out_of_stock",
            )
        ],
    )
    session.flush()

    with pytest.raises(PurchaseOrderValidationError):
        record_purchase_order_receipt(
            session,
            order.id,
            [
                PurchaseOrderReceiptLineItem(
                    purchase_order_item_id=item.id,
                    quantity=Decimal("1"),
                )
            ],
        )

    session.commit()
    session.refresh(product)

    assert product.current_stock == Decimal("0")
    assert get_purchase_order_balances(
        session, order.id
    )[0].outstanding_quantity == Decimal("0")


def test_fully_received_order_cannot_be_closed_again(session):
    product = _product(session)
    order = _create_order(session, product)
    item = _order_item(session, order)

    record_purchase_order_receipt(
        session,
        order.id,
        [
            PurchaseOrderReceiptLineItem(
                purchase_order_item_id=item.id,
                quantity=Decimal("10"),
            )
        ],
    )
    session.flush()

    with pytest.raises(PurchaseOrderValidationError):
        close_purchase_order_outstanding(
            session,
            order.id,
            [
                PurchaseOrderClosureLineItem(
                    purchase_order_item_id=item.id,
                    quantity=Decimal("1"),
                    reason_code="supplier_out_of_stock",
                )
            ],
        )

    session.commit()
    session.refresh(product)

    assert product.current_stock == Decimal("10")
    assert get_purchase_order_balances(
        session, order.id
    )[0].closed_quantity == Decimal("0")


def test_partial_closure_then_receipt_updates_status_correctly(session):
    product = _product(session)
    order = _create_order(session, product)
    item = _order_item(session, order)

    close_purchase_order_outstanding(
        session,
        order.id,
        [
            PurchaseOrderClosureLineItem(
                purchase_order_item_id=item.id,
                quantity=Decimal("3"),
                reason_code="supplier_out_of_stock",
            )
        ],
    )

    session.flush()

    record_purchase_order_receipt(
        session,
        order.id,
        [
            PurchaseOrderReceiptLineItem(
                purchase_order_item_id=item.id,
                quantity=Decimal("7"),
            )
        ],
    )

    session.commit()
    session.refresh(order)
    session.refresh(product)

    assert order.status == "closed"
    assert product.current_stock == Decimal("7")

    balance = get_purchase_order_balances(session, order.id)[0]
    assert balance.received_quantity == Decimal("7")
    assert balance.closed_quantity == Decimal("3")
    assert balance.outstanding_quantity == Decimal("0")


# ---------------------------------------------------------------------------
# Additional purchase-order edge-case tests
# ---------------------------------------------------------------------------

def test_po_multi_product_receipt_and_closure_are_isolated(session):
    product_a = _product(session, sku="PO-MULTI-A")
    product_b = _product(session, sku="PO-MULTI-B")

    order = create_purchase_order(
        session,
        supplier_id=None,
        reference="PO-MULTI-001",
        items=[
            PurchaseOrderLineItem(
                product_id=product_a.id,
                ordered_quantity=Decimal("10"),
                unit_price=Decimal("1000"),
            ),
            PurchaseOrderLineItem(
                product_id=product_b.id,
                ordered_quantity=Decimal("20"),
                unit_price=Decimal("1200"),
            ),
        ],
    )

    balances = get_purchase_order_balances(session, order.id)
    by_product = {
        balance.item.product_id: balance
        for balance in balances
    }

    line_a = by_product[product_a.id].item
    line_b = by_product[product_b.id].item

    record_purchase_order_receipt(
        session,
        order.id,
        [
            PurchaseOrderReceiptLineItem(
                purchase_order_item_id=line_a.id,
                quantity=Decimal("3"),
            )
        ],
    )

    close_purchase_order_outstanding(
        session,
        order.id,
        [
            PurchaseOrderClosureLineItem(
                purchase_order_item_id=line_b.id,
                quantity=Decimal("2"),
                reason_code="no_longer_required",
            )
        ],
    )

    updated = {
        balance.item.product_id: balance
        for balance in get_purchase_order_balances(session, order.id)
    }

    assert updated[product_a.id].received_quantity == Decimal("3")
    assert updated[product_a.id].closed_quantity == Decimal("0")
    assert updated[product_a.id].outstanding_quantity == Decimal("7")

    assert updated[product_b.id].received_quantity == Decimal("0")
    assert updated[product_b.id].closed_quantity == Decimal("2")
    assert updated[product_b.id].outstanding_quantity == Decimal("18")

    assert order.status == "partially_closed"


def test_po_nonexistent_order_raises_not_found(session):
    with pytest.raises(PurchaseOrderNotFoundError):
        get_purchase_order_balances(session, 999999)


def test_po_receipt_for_nonexistent_order_line_creates_no_audit(session):
    product = _product(session)
    order = _create_order(session, product)

    audit_before = session.scalar(
        select(func.count()).select_from(AuditLog)
    )

    with pytest.raises(PurchaseOrderItemNotFoundError):
        record_purchase_order_receipt(
            session,
            order.id,
            [
                PurchaseOrderReceiptLineItem(
                    purchase_order_item_id=999999,
                    quantity=Decimal("1"),
                )
            ],
        )

    session.flush()

    audit_after = session.scalar(
        select(func.count()).select_from(AuditLog)
    )

    assert audit_after == audit_before
    assert session.scalar(
        select(func.count()).select_from(PurchaseOrderReceipt)
    ) == 0


def test_po_closure_for_nonexistent_order_line_creates_no_audit(session):
    product = _product(session)
    order = _create_order(session, product)

    audit_before = session.scalar(
        select(func.count()).select_from(AuditLog)
    )

    with pytest.raises(PurchaseOrderItemNotFoundError):
        close_purchase_order_outstanding(
            session,
            order.id,
            [
                PurchaseOrderClosureLineItem(
                    purchase_order_item_id=999999,
                    quantity=Decimal("1"),
                    reason_code="no_longer_required",
                )
            ],
        )

    session.flush()

    audit_after = session.scalar(
        select(func.count()).select_from(AuditLog)
    )

    assert audit_after == audit_before
    assert session.scalar(
        select(func.count()).select_from(PurchaseOrderClosure)
    ) == 0


def test_po_receipt_rollback_reverts_receipt_stock_status_and_audit(session):
    product = _product(session, sku="PO-ROLLBACK")
    order = _create_order(session, product)
    order_id = order.id
    order_item_id = _order_item(session, order).id
    product_id = product.id

    # Commit setup first so the rollback applies only to the receipt.
    session.commit()

    audit_before = session.scalar(
        select(func.count()).select_from(AuditLog)
    )

    record_purchase_order_receipt(
        session,
        order_id,
        [
            PurchaseOrderReceiptLineItem(
                purchase_order_item_id=order_item_id,
                quantity=Decimal("4"),
            )
        ],
        reference="PO-ROLLBACK-REC",
    )
    session.flush()

    assert session.get(PurchaseOrder, order_id).status == "partially_received"

    session.rollback()

    restored_order = session.get(PurchaseOrder, order_id)
    assert restored_order.status == "open"

    balances = get_purchase_order_balances(session, order_id)
    assert balances[0].received_quantity == Decimal("0")
    assert balances[0].outstanding_quantity == Decimal("10")

    receipt_count = session.scalar(
        select(func.count()).select_from(PurchaseOrderReceipt)
    )
    assert receipt_count == 0

    receipt_movement_count = session.scalar(
        select(func.count())
        .select_from(StockTransaction)
        .where(
            StockTransaction.product_id == product_id,
            StockTransaction.reason == "purchase_order_receipt",
        )
    )
    assert receipt_movement_count == 0

    audit_after = session.scalar(
        select(func.count()).select_from(AuditLog)
    )
    assert audit_after == audit_before


def test_po_creation_rejects_reference_over_200_characters(session):
    product = _product(session)

    with pytest.raises(PurchaseOrderValidationError):
        create_purchase_order(
            session,
            supplier_id=None,
            reference="R" * 201,
            items=[
                PurchaseOrderLineItem(
                    product_id=product.id,
                    ordered_quantity=Decimal("2"),
                    unit_price=Decimal("1000"),
                )
            ],
        )


def test_po_creation_rejects_notes_over_500_characters(session):
    product = _product(session)

    with pytest.raises(PurchaseOrderValidationError):
        create_purchase_order(
            session,
            supplier_id=None,
            reference="PO-LENGTH-001",
            notes="N" * 501,
            items=[
                PurchaseOrderLineItem(
                    product_id=product.id,
                    ordered_quantity=Decimal("2"),
                    unit_price=Decimal("1000"),
                )
            ],
        )


def test_po_receipt_rejects_reference_over_200_characters(session):
    product = _product(session)
    order = _create_order(session, product)
    line = _order_item(session, order)

    with pytest.raises(PurchaseOrderValidationError):
        record_purchase_order_receipt(
            session,
            order.id,
            [
                PurchaseOrderReceiptLineItem(
                    purchase_order_item_id=line.id,
                    quantity=Decimal("1"),
                )
            ],
            reference="R" * 201,
        )


def test_po_receipt_rejects_notes_over_500_characters(session):
    product = _product(session)
    order = _create_order(session, product)
    line = _order_item(session, order)

    with pytest.raises(PurchaseOrderValidationError):
        record_purchase_order_receipt(
            session,
            order.id,
            [
                PurchaseOrderReceiptLineItem(
                    purchase_order_item_id=line.id,
                    quantity=Decimal("1"),
                )
            ],
            notes="N" * 501,
        )


def test_po_closure_rejects_notes_over_500_characters(session):
    product = _product(session)
    order = _create_order(session, product)
    line = _order_item(session, order)

    with pytest.raises(PurchaseOrderValidationError):
        close_purchase_order_outstanding(
            session,
            order.id,
            [
                PurchaseOrderClosureLineItem(
                    purchase_order_item_id=line.id,
                    quantity=Decimal("1"),
                    reason_code="no_longer_required",
                )
            ],
            notes="N" * 501,
        )


def test_po_closure_rejects_explanation_over_500_characters(session):
    product = _product(session)
    order = _create_order(session, product)
    line = _order_item(session, order)

    with pytest.raises(PurchaseOrderValidationError):
        close_purchase_order_outstanding(
            session,
            order.id,
            [
                PurchaseOrderClosureLineItem(
                    purchase_order_item_id=line.id,
                    quantity=Decimal("1"),
                    reason_code="other",
                    explanation="E" * 501,
                )
            ],
        )


def test_purchase_order_reads_require_authentication(session):
    admin = get_current_user()
    product = _product(session)
    order = _create_order(session, product)
    session.commit()

    set_current_user(None)

    with pytest.raises(PermissionDeniedError):
        list_purchase_orders(session)

    with pytest.raises(PermissionDeniedError):
        get_purchase_order_balances(session, order.id)

    for role in ("admin", "manager", "operator", "viewer"):
        set_current_user(admin)

        if role == "admin":
            user = admin
        else:
            user = create_user(
                session,
                f"po_read_test_{role}",
                "test-password-123",
                role=role,
            )
            session.commit()

        set_current_user(user)

        assert isinstance(list_purchase_orders(session), list)
        assert isinstance(get_purchase_order_balances(session, order.id), list)