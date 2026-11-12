from decimal import Decimal

import pytest

from app.data.db import create_db_engine, init_db, make_session_factory
from app.data.models import Customer, Purchase, Sale, StockTransaction, Supplier
from app.security.session_context import set_current_user
from app.services.auth import create_user
from app.services.master_data import create_product, set_product_active
from app.services.stock_ledger import InsufficientStockError
from app.security.permissions import PermissionDeniedError
from app.services.transactions import (
    EmptyTransactionError,
    InvalidLineItemError,
    LineItem,
    ProductInactiveError,
    SupplierNotFoundError,
    SupplierInactiveError,
    CustomerNotFoundError,
    CustomerInactiveError,
    SalePriceMismatchError,
    create_adjustment,
    create_purchase,
    create_sale,
)


@pytest.fixture()
def session():
    engine = create_db_engine(db_path=":memory:")
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as s:
        admin = create_user(s, "admin", "test-password-123", role="admin")
        s.commit()
        set_current_user(admin)
        yield s
        set_current_user(None)


def _product(session, opening=Decimal("0")):
    return create_product(
        session, sku="SKU-1", name="Widget", category_id=None, unit_id=None,
        location_id=None, price=Decimal("15"),
        reorder_level=Decimal("5"), opening_stock=opening,
    )


def test_purchase_increases_stock(session):
    product = _product(session, opening=Decimal("0"))
    create_purchase(
        session, supplier_id=None, reference="INV-1",
        items=[LineItem(product.id, Decimal("30"), Decimal("10"))],
    )
    session.commit()
    session.refresh(product)
    assert product.current_stock == Decimal("30")


def test_sale_decreases_stock(session):
    product = _product(session, opening=Decimal("50"))
    create_sale(
        session, customer_id=None, reference="SALE-1",
        items=[LineItem(product.id, Decimal("20"), Decimal("15"))],
    )
    session.commit()
    session.refresh(product)
    assert product.current_stock == Decimal("30")


def test_sale_blocked_when_insufficient_stock(session):
    product = _product(session, opening=Decimal("5"))
    with pytest.raises(InsufficientStockError):
        create_sale(
            session, customer_id=None, reference="SALE-2",
            items=[LineItem(product.id, Decimal("10"), Decimal("15"))],
        )


def test_purchase_requires_at_least_one_item(session):
    with pytest.raises(EmptyTransactionError):
        create_purchase(session, supplier_id=None, reference="INV-EMPTY", items=[])


def test_adjustment_requires_reason(session):
    product = _product(session, opening=Decimal("10"))
    with pytest.raises(ValueError):
        create_adjustment(session, product.id, Decimal("-2"), reason="   ")


def test_adjustment_updates_ledger_and_stock(session):
    product = _product(session, opening=Decimal("10"))
    create_adjustment(session, product.id, Decimal("-3"), reason="physical count shortage")
    session.commit()
    session.refresh(product)
    assert product.current_stock == Decimal("7")


def test_sale_rejects_price_different_from_product_price(session):
    product = _product(session, opening=Decimal("20"))

    with pytest.raises(SalePriceMismatchError):
        create_sale(
            session,
            customer_id=None,
            reference="SALE-WRONG-PRICE",
            items=[LineItem(product.id, Decimal("2"), Decimal("14"))],
        )


def test_operator_cannot_override_sale_price(session):
    product = _product(session, opening=Decimal("20"))
    operator = create_user(
        session, "operator", "operator-password-123", role="operator"
    )
    session.commit()
    set_current_user(operator)

    with pytest.raises(SalePriceMismatchError):
        create_sale(
            session,
            customer_id=None,
            reference="SALE-OPERATOR-OVERRIDE",
            items=[LineItem(product.id, Decimal("2"), Decimal("14"))],
        )


def test_unauthenticated_user_cannot_create_purchase(session):
    product = _product(session, opening=Decimal("0"))
    set_current_user(None)

    with pytest.raises(PermissionDeniedError):
        create_purchase(
            session,
            supplier_id=None,
            reference="PURCHASE-UNAUTHENTICATED",
            items=[LineItem(product.id, Decimal("5"), Decimal("10"))],
        )


def test_unauthenticated_user_cannot_create_adjustment(session):
    product = _product(session, opening=Decimal("10"))
    set_current_user(None)

    with pytest.raises(PermissionDeniedError):
        create_adjustment(
            session, product.id, Decimal("-1"), reason="test"
        )


def test_purchase_cost_can_differ_from_selling_price(session):
    product = _product(session, opening=Decimal("0"))


    purchase = create_purchase(
        session,
        supplier_id=None,
        reference="PURCHASE-COST-TEST",
        items=[LineItem(product.id, Decimal("5"), Decimal("9"))],
    )
    session.commit()

    assert purchase.id is not None
    assert product.price == Decimal("15")



def test_transaction_records_capture_authenticated_user(session):
    from app.data.models import Purchase, Sale, StockAdjustment

    admin = session.query(type(session.get_bind())).first() if False else None
    from app.security.session_context import get_current_user
    actor = get_current_user()

    product = _product(session, opening=Decimal("20"))

    supplier = Supplier(name="Attribution Supplier")
    customer = Customer(name="Attribution Customer")
    session.add_all([supplier, customer])
    session.flush()

    purchase = create_purchase(
        session,
        supplier_id=supplier.id,
        reference="ATTR-PURCHASE",
        items=[LineItem(product.id, Decimal("5"), Decimal("9"))],
    )

    sale = create_sale(
        session,
        customer_id=customer.id,
        reference="ATTR-SALE",
        items=[LineItem(product.id, Decimal("2"), Decimal("15"))],
    )

    adjustment = create_adjustment(
        session,
        product.id,
        Decimal("-1"),
        reason="attribution test",
    )

    session.commit()

    assert purchase.created_by_user_id == actor.id
    assert sale.created_by_user_id == actor.id
    assert adjustment.created_by_user_id == actor.id

    movements = (
        session.query(StockTransaction)
        .filter(StockTransaction.reference.in_([
            "ATTR-PURCHASE",
            "ATTR-SALE",
            "attribution test",
        ]))
        .all()
    )
    assert len(movements) == 3
    assert all(movement.user_id == actor.id for movement in movements)

    purchase_movement = next(
        movement for movement in movements
        if movement.reference == "ATTR-PURCHASE"
    )
    sale_movement = next(
        movement for movement in movements
        if movement.reference == "ATTR-SALE"
    )
    assert purchase_movement.party_type == "Supplier"
    assert purchase_movement.party_name == "Attribution Supplier"
    assert sale_movement.party_type == "Customer"
    assert sale_movement.party_name == "Attribution Customer"


def test_opening_stock_movement_captures_authenticated_user(session):
    from app.data.models import StockTransaction

    actor_id = __import__(
        "app.security.session_context",
        fromlist=["get_current_user"],
    ).get_current_user().id

    product = create_product(
        session,
        sku="OPENING-ATTR",
        name="Opening Stock Attribution",
        category_id=None,
        unit_id=None,
        location_id=None,
        price=Decimal("15"),
        reorder_level=Decimal("5"),
        opening_stock=Decimal("12"),
    )
    session.commit()

    movement = (
        session.query(StockTransaction)
        .filter_by(product_id=product.id, reason="opening_stock")
        .one()
    )
    assert movement.user_id == actor_id


def test_purchase_rejects_inactive_product_before_creating_records(session):
    product = _product(session, opening=Decimal("10"))
    set_product_active(session, product.id, False)
    session.commit()

    purchase_count_before = session.query(Purchase).count()
    movement_count_before = session.query(StockTransaction).count()
    stock_before = product.current_stock

    with pytest.raises(ProductInactiveError):
        create_purchase(
            session,
            supplier_id=None,
            reference="PURCHASE-INACTIVE",
            items=[LineItem(product.id, Decimal("5"), Decimal("10"))],
        )

    assert session.query(Purchase).count() == purchase_count_before
    assert session.query(StockTransaction).count() == movement_count_before
    assert product.current_stock == stock_before


def test_sale_rejects_inactive_product_before_creating_records(session):
    product = _product(session, opening=Decimal("10"))
    set_product_active(session, product.id, False)
    session.commit()

    sale_count_before = session.query(Sale).count()
    movement_count_before = session.query(StockTransaction).count()
    stock_before = product.current_stock

    with pytest.raises(ProductInactiveError):
        create_sale(
            session,
            customer_id=None,
            reference="SALE-INACTIVE",
            items=[LineItem(product.id, Decimal("2"), Decimal("15"))],
        )

    assert session.query(Sale).count() == sale_count_before
    assert session.query(StockTransaction).count() == movement_count_before
    assert product.current_stock == stock_before


def test_purchase_rejects_inactive_product_in_multi_item_transaction(session):
    active_product = _product(session, opening=Decimal("0"))
    inactive_product = create_product(
        session,
        sku="SKU-INACTIVE",
        name="Inactive Widget",
        category_id=None,
        unit_id=None,
        location_id=None,
        price=Decimal("15"),
        reorder_level=Decimal("0"),
        opening_stock=Decimal("0"),
    )
    set_product_active(session, inactive_product.id, False)
    session.commit()

    purchase_count_before = session.query(Purchase).count()
    movement_count_before = session.query(StockTransaction).count()

    with pytest.raises(ProductInactiveError):
        create_purchase(
            session,
            supplier_id=None,
            reference="PURCHASE-MIXED-INACTIVE",
            items=[
                LineItem(active_product.id, Decimal("5"), Decimal("10")),
                LineItem(inactive_product.id, Decimal("3"), Decimal("10")),
            ],
        )

    assert session.query(Purchase).count() == purchase_count_before
    assert session.query(StockTransaction).count() == movement_count_before
    assert active_product.current_stock == Decimal("0")


def test_purchase_rejects_inactive_supplier_without_creating_records(session):
    product = _product(session, opening=Decimal("0"))
    supplier = Supplier(name="Inactive Supplier", is_active=False)
    session.add(supplier)
    session.commit()

    purchase_count_before = session.query(Purchase).count()
    movement_count_before = session.query(StockTransaction).count()
    stock_before = product.current_stock

    with pytest.raises(SupplierInactiveError):
        create_purchase(
            session,
            supplier_id=supplier.id,
            reference="PURCHASE-INACTIVE-SUPPLIER",
            items=[LineItem(product.id, Decimal("5"), Decimal("10"))],
        )

    assert session.query(Purchase).count() == purchase_count_before
    assert session.query(StockTransaction).count() == movement_count_before
    assert product.current_stock == stock_before


def test_purchase_rejects_nonexistent_supplier(session):
    product = _product(session, opening=Decimal("0"))

    with pytest.raises(SupplierNotFoundError):
        create_purchase(
            session,
            supplier_id=999999,
            reference="PURCHASE-MISSING-SUPPLIER",
            items=[LineItem(product.id, Decimal("5"), Decimal("10"))],
        )

    assert session.query(Purchase).count() == 0
    assert session.query(StockTransaction).count() == 0
    assert product.current_stock == Decimal("0")


def test_sale_rejects_inactive_customer_without_creating_records(session):
    product = _product(session, opening=Decimal("20"))
    customer = Customer(name="Inactive Customer", is_active=False)
    session.add(customer)
    session.commit()

    sale_count_before = session.query(Sale).count()
    movement_count_before = session.query(StockTransaction).count()
    stock_before = product.current_stock

    with pytest.raises(CustomerInactiveError):
        create_sale(
            session,
            customer_id=customer.id,
            reference="SALE-INACTIVE-CUSTOMER",
            items=[LineItem(product.id, Decimal("2"), Decimal("15"))],
        )

    assert session.query(Sale).count() == sale_count_before
    assert session.query(StockTransaction).count() == movement_count_before
    assert product.current_stock == stock_before


def test_sale_rejects_nonexistent_customer(session):
    product = _product(session, opening=Decimal("20"))
    sale_count_before = session.query(Sale).count()
    movement_count_before = session.query(StockTransaction).count()
    stock_before = product.current_stock

    with pytest.raises(CustomerNotFoundError):
        create_sale(
            session,
            customer_id=999999,
            reference="SALE-MISSING-CUSTOMER",
            items=[LineItem(product.id, Decimal("2"), Decimal("15"))],
        )

    assert session.query(Sale).count() == sale_count_before
    assert session.query(StockTransaction).count() == movement_count_before
    assert product.current_stock == stock_before
