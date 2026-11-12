from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.data.db import create_db_engine, init_db, make_session_factory
from app.data.models import (
    AuditLog,
    DamagedGood,
    StockTransaction,
    Supplier,
    Unit,
    User,
)
from app.security.permissions import PermissionDeniedError
from app.security.session_context import get_current_user, set_current_user
from app.services.damaged_goods import (
    InvalidDamagedGoodsError,
    ReferenceNotFoundError,
    damaged_goods_totals,
    delete_damaged_goods,
    DamagedGoodsNotFoundError,
    list_damaged_goods,
    record_damaged_goods,
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
        viewer = User(
            username="damage-viewer",
            password_hash="test-hash",
            salt="test-salt",
            role="viewer",
        )
        unit = Unit(name="Bottles")
        supplier = Supplier(name="Mushimire")
        s.add_all([viewer, unit, supplier])
        s.commit()

        s.info["viewer"] = viewer
        s.info["unit"] = unit
        s.info["supplier"] = supplier
        set_current_user(viewer)
        yield s


def test_viewer_can_record_damaged_goods_without_stock_movement(session):
    unit = session.info["unit"]
    supplier = session.info["supplier"]

    record = record_damaged_goods(
        session,
        unit_id=unit.id,
        quantity="12",
        supplier_id=supplier.id,
        date_brought=date(2026, 11, 9),
    )
    session.commit()

    assert record.recorded_by_user_id == session.info["viewer"].id
    assert record.unit_name == "Bottles"
    assert record.supplier_name == "Mushimire"
    assert record.quantity == Decimal("12")
    assert record.date_brought == date(2026, 11, 9)
    assert record.recorded_at is not None

    assert session.scalar(select(func.count()).select_from(StockTransaction)) == 0


def test_damaged_goods_store_unit_and_supplier_snapshots(session):
    unit = session.info["unit"]
    supplier = session.info["supplier"]

    record = record_damaged_goods(
        session,
        unit_id=unit.id,
        quantity=5,
        supplier_id=supplier.id,
        date_brought=date(2026, 11, 8),
    )
    session.commit()

    unit.name = "Bottle(s)"
    supplier.name = "Renamed Supplier"
    session.commit()

    saved = session.get(DamagedGood, record.id)
    assert saved.unit_name == "Bottles"
    assert saved.supplier_name == "Mushimire"


@pytest.mark.parametrize("quantity", [0, -1, "abc", None, "NaN", "Infinity"])
def test_invalid_quantity_is_rejected(session, quantity):
    with pytest.raises(InvalidDamagedGoodsError):
        record_damaged_goods(
            session,
            unit_id=session.info["unit"].id,
            quantity=quantity,
            supplier_id=session.info["supplier"].id,
            date_brought=date(2026, 11, 9),
        )


def test_inactive_unit_is_rejected(session):
    unit = session.info["unit"]
    unit.is_active = False
    session.flush()

    with pytest.raises(ReferenceNotFoundError):
        record_damaged_goods(
            session,
            unit_id=unit.id,
            quantity=1,
            supplier_id=session.info["supplier"].id,
            date_brought=date(2026, 11, 9),
        )


def test_inactive_supplier_is_rejected(session):
    supplier = session.info["supplier"]
    supplier.is_active = False
    session.flush()

    with pytest.raises(ReferenceNotFoundError):
        record_damaged_goods(
            session,
            unit_id=session.info["unit"].id,
            quantity=1,
            supplier_id=supplier.id,
            date_brought=date(2026, 11, 9),
        )


def test_recording_requires_authentication(session):
    set_current_user(None)

    with pytest.raises(PermissionDeniedError):
        record_damaged_goods(
            session,
            unit_id=session.info["unit"].id,
            quantity=1,
            supplier_id=session.info["supplier"].id,
            date_brought=date(2026, 11, 9),
        )


def test_history_and_bottle_crate_totals(session):
    viewer = session.info["viewer"]
    session.add_all([
        DamagedGood(
            unit_name="Bottles",
            quantity=Decimal("12"),
            supplier_name="Supplier A",
            date_brought=date(2026, 11, 8),
            recorded_by_user_id=viewer.id,
        ),
        DamagedGood(
            unit_name="Bottle(s)",
            quantity=Decimal("3"),
            supplier_name="Supplier A",
            date_brought=date(2026, 11, 9),
            recorded_by_user_id=viewer.id,
        ),
        DamagedGood(
            unit_name="Crates",
            quantity=Decimal("2"),
            supplier_name="Supplier B",
            date_brought=date(2026, 11, 9),
            recorded_by_user_id=viewer.id,
        ),
        DamagedGood(
            unit_name="Cartons",
            quantity=Decimal("4"),
            supplier_name="Supplier C",
            date_brought=date(2026, 11, 9),
            recorded_by_user_id=viewer.id,
        ),
    ])
    session.commit()

    totals = damaged_goods_totals(session)
    history = list_damaged_goods(session)

    assert totals == {
        "bottles": Decimal("15"),
        "crates": Decimal("2"),
    }
    assert len(history) == 4
    assert history[0].date_brought >= history[-1].date_brought


def test_damaged_goods_do_not_create_stock_ledger_rows(session):
    unit = session.info["unit"]
    supplier = session.info["supplier"]

    record_damaged_goods(
        session,
        unit_id=unit.id,
        quantity=7,
        supplier_id=supplier.id,
        date_brought=date(2026, 11, 9),
    )
    session.commit()

    assert session.scalar(select(func.count()).select_from(DamagedGood)) == 1
    assert session.scalar(select(func.count()).select_from(StockTransaction)) == 0


def test_datetime_is_rejected_as_date_brought(session):
    with pytest.raises(InvalidDamagedGoodsError):
        record_damaged_goods(
            session,
            unit_id=session.info["unit"].id,
            quantity=1,
            supplier_id=session.info["supplier"].id,
            date_brought=datetime(2026, 11, 9, 14, 30),
        )



def test_admin_can_delete_damaged_goods_and_audit_details(session):
    viewer = session.info["viewer"]
    admin = User(
        username="damage-admin",
        password_hash="test-hash",
        salt="test-salt",
        role="admin",
    )
    session.add(admin)
    session.flush()

    record = DamagedGood(
        unit_name="Bottles",
        quantity=Decimal("18"),
        supplier_name="Mushimire",
        date_brought=date(2026, 11, 9),
        recorded_by_user_id=viewer.id,
    )
    session.add(record)
    session.flush()
    record_id = record.id

    set_current_user(admin)
    delete_damaged_goods(session, record_id)
    session.commit()

    assert session.get(DamagedGood, record_id) is None

    audit = session.scalars(
        select(AuditLog).where(AuditLog.action == "damaged_good_deleted")
    ).one()
    assert audit.user_id == admin.id
    assert f"id={record_id}" in audit.details
    assert "unit=Bottles" in audit.details
    assert "quantity=18" in audit.details
    assert "supplier=Mushimire" in audit.details
    assert "deleted_by=damage-admin" in audit.details


@pytest.mark.parametrize("role", ["viewer", "operator", "manager"])
def test_non_admin_cannot_delete_damaged_goods(session, role):
    viewer = session.info["viewer"]
    record = DamagedGood(
        unit_name="Bottles",
        quantity=Decimal("5"),
        supplier_name="Mushimire",
        date_brought=date(2026, 11, 9),
        recorded_by_user_id=viewer.id,
    )
    session.add(record)
    session.flush()
    record_id = record.id

    user = User(
        username=f"damage-{role}-{__import__('uuid').uuid4().hex}",
        password_hash="test-hash",
        salt="test-salt",
        role=role,
    )
    session.add(user)
    session.flush()
    set_current_user(user)

    with pytest.raises(PermissionDeniedError):
        delete_damaged_goods(session, record_id)

    assert session.get(DamagedGood, record_id) is not None
    assert session.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "damaged_good_deleted"
        )
    ) == 0


def test_deleting_missing_damaged_goods_record_is_rejected(session):
    admin = User(
        username="damage-admin-missing",
        password_hash="test-hash",
        salt="test-salt",
        role="admin",
    )
    session.add(admin)
    session.flush()
    set_current_user(admin)

    with pytest.raises(DamagedGoodsNotFoundError):
        delete_damaged_goods(session, 999999)

    assert session.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "damaged_good_deleted"
        )
    ) == 0
