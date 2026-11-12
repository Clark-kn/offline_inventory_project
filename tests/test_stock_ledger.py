from decimal import Decimal

import pytest

from app.data.db import create_db_engine, init_db, make_session_factory
from app.data.models import Product, User
from app.security.permissions import PermissionDeniedError
from app.security.session_context import set_current_user
from app.services.auth import create_user
from app.services.stock_ledger import (
    InsufficientStockError,
    ProductNotFoundError,
    record_movement,
)
from app.services.reports import product_ledger


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


def _make_product(session, sku="SKU-1", opening=Decimal("0")):
    product = Product(sku=sku, name="Test Product", current_stock=opening)
    session.add(product)
    session.flush()
    return product



def test_stock_movement_requires_authentication(session):
    product = _make_product(session)
    set_current_user(None)

    with pytest.raises(PermissionDeniedError):
        record_movement(
            session, product.id, Decimal("1"), reason="purchase"
        )


def test_viewer_cannot_create_stock_movement(session):
    product = _make_product(session)
    viewer = User(
        username="ledger-viewer",
        password_hash="test-hash",
        salt="test-salt",
        role="viewer",
    )
    session.add(viewer)
    session.flush()
    set_current_user(viewer)

    with pytest.raises(PermissionDeniedError):
        record_movement(
            session, product.id, Decimal("1"), reason="purchase"
        )


def test_stock_movement_uses_authenticated_user_attribution(session):
    from sqlalchemy import select
    from app.data.models.stock_transaction import StockTransaction

    product = _make_product(session)
    from app.security.session_context import get_current_user
    actor = get_current_user()

    record_movement(
        session, product.id, Decimal("4"), reason="purchase"
    )
    session.flush()

    movement = session.scalar(
        select(StockTransaction).where(
            StockTransaction.product_id == product.id
        )
    )

    assert actor is not None
    assert movement.user_id == actor.id


def test_stock_movement_rejects_forged_user_attribution(session):
    product = _make_product(session)
    other_user = User(
        username="other-ledger-user",
        password_hash="test-hash",
        salt="test-salt",
        role="operator",
    )
    session.add(other_user)
    session.flush()

    with pytest.raises(PermissionDeniedError):
        record_movement(
            session,
            product.id,
            Decimal("1"),
            reason="purchase",
            user_id=other_user.id,
        )

def test_example_movement_sequence_from_plan(session):
    product = _make_product(session, opening=Decimal("100"))

    record_movement(session, product.id, Decimal("50"), reason="purchase")
    record_movement(session, product.id, Decimal("-20"), reason="sale")
    record_movement(session, product.id, Decimal("-2"), reason="damage")
    session.commit()

    session.refresh(product)
    assert product.current_stock == Decimal("128")


def test_ledger_matches_cached_balance(session):
    product = _make_product(session, opening=Decimal("10"))
    record_movement(session, product.id, Decimal("5"), reason="purchase")
    record_movement(session, product.id, Decimal("-3"), reason="sale")
    session.commit()

    from sqlalchemy import select
    from app.data.models.stock_transaction import StockTransaction

    rows = session.scalars(
        select(StockTransaction).where(StockTransaction.product_id == product.id)
    ).all()
    total_delta = sum((r.qty_delta for r in rows), Decimal("0"))

    session.refresh(product)
    assert product.current_stock == Decimal("10") + total_delta


def test_negative_stock_blocked_by_default(session):
    product = _make_product(session, opening=Decimal("5"))
    with pytest.raises(InsufficientStockError):
        record_movement(session, product.id, Decimal("-10"), reason="sale")


def test_negative_stock_allowed_when_flagged(session):
    product = _make_product(session, opening=Decimal("5"))
    record_movement(session, product.id, Decimal("-10"), reason="sale", allow_negative=True)
    session.refresh(product)
    assert product.current_stock == Decimal("-5")


def test_unknown_product_raises(session):
    with pytest.raises(ProductNotFoundError):
        record_movement(session, 999, Decimal("1"), reason="purchase")


def test_decimal_precision_is_exact(session):
    product = _make_product(session, opening=Decimal("0.1"))
    record_movement(session, product.id, Decimal("0.2"), reason="purchase")
    session.refresh(product)
    assert product.current_stock == Decimal("0.3")



def test_product_ledger_preserves_user_and_reference_attribution(session):
    product = _make_product(session)

    actor = User(
        username="ledger-worker",
        password_hash="test-hash",
        salt="test-salt",
        role="operator",
    )
    session.add(actor)
    session.flush()
    set_current_user(actor)

    record_movement(
        session,
        product.id,
        Decimal("12"),
        reason="purchase_order_receipt",
        reference="PO-12-REC-3",
        user_id=actor.id,
    )
    session.commit()

    rows = product_ledger(session, product.id)

    assert len(rows) == 1
    assert rows[0].user_id == actor.id
    assert rows[0].reference == "PO-12-REC-3"
    assert rows[0].reason == "purchase_order_receipt"



def test_ledger_preserves_optional_party_snapshot(session):
    product = _make_product(session)

    record_movement(
        session,
        product.id,
        Decimal("8"),
        reason="purchase",
        party_type="Supplier",
        party_name="Mushimire",
    )
    session.commit()

    rows = product_ledger(session, product.id)
    assert len(rows) == 1
    assert rows[0].party_type == "Supplier"
    assert rows[0].party_name == "Mushimire"


@pytest.mark.parametrize(
    ("party_type", "party_name"),
    [
        ("Supplier", None),
        (None, "Mushimire"),
        ("Other", "Mushimire"),
        ("Customer", "   "),
    ],
)
def test_ledger_rejects_invalid_party_attribution(
    session, party_type, party_name
):
    product = _make_product(session)

    with pytest.raises(ValueError):
        record_movement(
            session,
            product.id,
            Decimal("1"),
            reason="purchase",
            party_type=party_type,
            party_name=party_name,
        )
