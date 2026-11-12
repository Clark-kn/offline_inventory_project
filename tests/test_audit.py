from decimal import Decimal

import pytest

from app.data.db import create_db_engine, init_db, make_session_factory
from app.security.permissions import PermissionDeniedError
from app.security.session_context import get_current_user, set_current_user
from app.services.audit import log_action, recent_audit_log
from app.services.auth import create_user
from app.services.master_data import create_product, set_product_active, set_reference_active
from app.services.transactions import create_adjustment
from app.data.models import Category


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


@pytest.fixture(autouse=True)
def reset_current_user():
    previous = get_current_user()
    set_current_user(None)
    yield
    set_current_user(previous)


def test_actions_are_attributed_to_the_logged_in_user(session):
    admin = get_current_user()
    assert admin is not None

    category = Category(name="Snacks")
    session.add(category)
    session.flush()
    set_reference_active(session, Category, category.id, False)
    session.commit()

    entries = recent_audit_log(session)
    log, user = entries[0]
    assert log.action == "reference_status_changed"
    assert user.username == "admin"


def test_stock_adjustment_is_audited(session):
    product = create_product(
        session, sku="SKU-1", name="Widget", category_id=None, unit_id=None,
        location_id=None, price=Decimal("2"),
        reorder_level=Decimal("0"), opening_stock=Decimal("10"),
    )
    session.commit()

    create_adjustment(session, product.id, Decimal("-2"), reason="damaged in transit")
    session.commit()

    entries = recent_audit_log(session)
    actions = [log.action for log, _ in entries]
    assert "stock_adjustment" in actions


def test_product_deactivation_is_audited(session):
    product = create_product(
        session, sku="SKU-2", name="Gadget", category_id=None, unit_id=None,
        location_id=None, price=Decimal("2"),
        reorder_level=Decimal("0"), opening_stock=Decimal("0"),
    )
    session.commit()

    set_product_active(session, product.id, False)
    session.commit()

    entries = recent_audit_log(session)
    actions = [log.action for log, _ in entries]
    assert "product_status_changed" in actions


def test_audit_entry_has_no_user_when_nobody_is_logged_in(session):
    admin = get_current_user()
    set_current_user(None)

    log_action(
        session,
        "unattributed_test_action",
        "Generated while nobody was logged in",
    )
    session.commit()

    with pytest.raises(PermissionDeniedError):
        recent_audit_log(session)

    set_current_user(admin)
    log, user = recent_audit_log(session)[0]
    assert log.action == "unattributed_test_action"
    assert log.user_id is None
    assert user is None
def test_recent_audit_log_requires_admin(session):
    admin = get_current_user()
    operator = create_user(session, "operator_audit_test", "test-password-123", role="operator")
    session.commit()

    set_current_user(operator)
    with pytest.raises(PermissionDeniedError):
        recent_audit_log(session)

    set_current_user(admin)
    assert recent_audit_log(session)


def test_audit_display_uses_business_friendly_labels():
    from app.services.audit_display import (
        audit_action_label,
        format_audit_details,
        format_audit_summary,
    )

    assert audit_action_label("product_price_changed") == "Changed a product selling price"

    details = "sku=PRIMUS-01 old_price=1000 new_price=1200"
    summary = format_audit_summary("product_price_changed", details)
    assert "PRIMUS-01: 1000 RWF" in summary
    assert "1200 RWF" in summary

    readable = format_audit_details("product_price_changed", details)
    assert "Product code: PRIMUS-01" in readable
    assert "Previous selling price: 1000 RWF" in readable
    assert "New selling price: 1200 RWF" in readable


def test_audit_display_parses_values_containing_spaces():
    from app.services.audit_display import (
        format_audit_details,
        format_audit_summary,
    )

    details = "id=12 name=Primus Lager changed_fields=name, price"
    summary = format_audit_summary("product_updated", details)
    readable = format_audit_details("product_updated", details)

    assert summary == "Product code: not specified"
    assert "Name: Primus Lager" in readable
    assert "Information changed: name, price" in readable


def test_audit_display_handles_unknown_actions_and_plain_text():
    from app.services.audit_display import (
        audit_action_label,
        format_audit_details,
        format_audit_summary,
    )

    assert audit_action_label("future_test_event") == "Future test event"
    assert format_audit_summary(
        "future_test_event", "A future event happened"
    ) == "A future event happened"
    assert "A future event happened" in format_audit_details(
        "future_test_event", "A future event happened"
    )


def test_audit_display_formats_damaged_goods_deletion():
    from app.services.audit_display import (
        format_audit_details,
        format_audit_summary,
    )

    details = (
        "id=7 unit=crate quantity=2 supplier=ABC Beverages "
        "date_brought=2026-11-10 recorded_by_user_id=3 "
        "recorded_at=2026-11-10T10:00:00 deleted_by=admin"
    )
    summary = format_audit_summary("damaged_good_deleted", details)
    readable = format_audit_details("damaged_good_deleted", details)

    assert summary.startswith("2 crate")
    assert "Supplier: ABC Beverages" in summary
    assert "Supplier: ABC Beverages" in readable
    assert "Deleted by: admin" in readable
