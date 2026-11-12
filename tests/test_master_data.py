from decimal import Decimal

import pytest
from sqlalchemy import select

from app.data.db import create_db_engine, init_db, make_session_factory
from app.security.permissions import PermissionDeniedError
from app.security.session_context import get_current_user, set_current_user
from app.services.auth import create_user
from app.data.models import AuditLog, Category
from app.services.master_data import (
    DuplicateNameError,
    DuplicateSkuError,
    create_product,
    create_reference,
    list_customers,
    list_products,
    list_reference,
    list_suppliers,
    save_customer,
    save_supplier,
    set_customer_active,
    set_product_active,
    set_reference_active,
    set_supplier_active,
    update_product,
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
        admin = create_user(s, "admin", "test-password-123", role="admin")
        s.commit()
        set_current_user(admin)
        yield s


def test_create_reference_rejects_duplicate_name(session):
    create_reference(session, Category, "Beverages")
    with pytest.raises(DuplicateNameError):
        create_reference(session, Category, "Beverages")


def test_create_product_rejects_duplicate_sku(session):
    create_product(
        session, sku="SKU-1", name="Widget", category_id=None, unit_id=None,
        location_id=None, price=Decimal("2"),
        reorder_level=Decimal("0"), opening_stock=Decimal("0"),
    )
    with pytest.raises(DuplicateSkuError):
        create_product(
            session, sku="SKU-1", name="Other", category_id=None, unit_id=None,
            location_id=None, price=Decimal("2"),
            reorder_level=Decimal("0"), opening_stock=Decimal("0"),
        )


def test_create_product_with_opening_stock_creates_ledger_entry(session):
    product = create_product(
        session, sku="SKU-2", name="Gadget", category_id=None, unit_id=None,
        location_id=None, price=Decimal("9"),
        reorder_level=Decimal("2"), opening_stock=Decimal("40"),
    )
    session.commit()
    session.refresh(product)
    assert product.current_stock == Decimal("40")


def test_deactivate_product_does_not_delete_it(session):
    product = create_product(
        session, sku="SKU-3", name="Thing", category_id=None, unit_id=None,
        location_id=None, price=Decimal("1"),
        reorder_level=Decimal("0"), opening_stock=Decimal("0"),
    )
    set_product_active(session, product.id, False)
    session.commit()

    active_only = list_products(session)
    everything = list_products(session, include_inactive=True)
    assert product.id not in [p.id for p in active_only]
    assert product.id in [p.id for p in everything]


def test_deactivate_reference_does_not_delete_it(session):
    category = create_reference(session, Category, "Snacks")
    set_reference_active(session, Category, category.id, False)
    session.commit()

    active_only = list_reference(session, Category)
    everything = list_reference(session, Category, include_inactive=True)
    assert category.id not in [c.id for c in active_only]
    assert category.id in [c.id for c in everything]


def test_deactivate_supplier_does_not_delete_it(session):
    supplier = save_supplier(session, None, "Acme Supplies", "", "")
    set_supplier_active(session, supplier.id, False)
    session.commit()

    active_only = list_suppliers(session)
    everything = list_suppliers(session, include_inactive=True)
    assert supplier.id not in [s.id for s in active_only]
    assert supplier.id in [s.id for s in everything]


def test_deactivate_customer_does_not_delete_it(session):
    customer = save_customer(session, None, "Jane Doe", "")
    set_customer_active(session, customer.id, False)
    session.commit()

    active_only = list_customers(session)
    everything = list_customers(session, include_inactive=True)
    assert customer.id not in [c.id for c in active_only]
    assert customer.id in [c.id for c in everything]


def test_update_product_rejects_sku_collision_with_other_product(session):
    p1 = create_product(
        session, sku="SKU-A", name="A", category_id=None, unit_id=None,
        location_id=None, price=Decimal("1"),
        reorder_level=Decimal("0"), opening_stock=Decimal("0"),
    )
    p2 = create_product(
        session, sku="SKU-B", name="B", category_id=None, unit_id=None,
        location_id=None, price=Decimal("1"),
        reorder_level=Decimal("0"), opening_stock=Decimal("0"),
    )
    with pytest.raises(DuplicateSkuError):
        update_product(
            session, p2.id, sku="SKU-A", name="B", category_id=None, unit_id=None,
            location_id=None, price=Decimal("1"),
            reorder_level=Decimal("0"),
        )


def test_operator_can_create_product_only_with_zero_selling_price(session):
    operator = create_user(session, "operator", "operator-password", role="operator")
    session.commit()
    set_current_user(operator)

    product = create_product(
        session, sku="WORKER-001", name="Worker Product",
        category_id=None, unit_id=None, location_id=None,
        price=Decimal("0"), reorder_level=Decimal("0"),
        opening_stock=Decimal("0"),
    )
    assert product.price == Decimal("0")

    with pytest.raises(PermissionDeniedError):
        create_product(
            session, sku="WORKER-002", name="Priced Product",
            category_id=None, unit_id=None, location_id=None,
            price=Decimal("100"), reorder_level=Decimal("0"),
            opening_stock=Decimal("0"),
        )


def test_operator_cannot_edit_existing_product(session):
    product = create_product(
        session, sku="EDIT-001", name="Original",
        category_id=None, unit_id=None, location_id=None,
        price=Decimal("100"), reorder_level=Decimal("0"),
        opening_stock=Decimal("0"),
    )

    operator = create_user(session, "operator", "operator-password", role="operator")
    session.commit()
    set_current_user(operator)

    with pytest.raises(PermissionDeniedError):
        update_product(
            session, product.id, sku="EDIT-001", name="Updated",
            category_id=None, unit_id=None, location_id=None,
            price=Decimal("100"), reorder_level=Decimal("2"),
        )

    assert product.name == "Original"
    assert product.price == Decimal("100")
    assert product.reorder_level == Decimal("0")

def test_admin_product_price_changes_are_audited(session):
    admin = get_current_user()

    product = create_product(
        session, sku="ADMIN-001", name="Admin Product",
        category_id=None, unit_id=None, location_id=None,
        price=Decimal("100"), reorder_level=Decimal("0"),
        opening_stock=Decimal("0"),
    )

    update_product(
        session, product.id, sku="ADMIN-001", name="Admin Product",
        category_id=None, unit_id=None, location_id=None,
        price=Decimal("125"), reorder_level=Decimal("0"),
    )

    price_set = session.scalars(
        select(AuditLog).where(AuditLog.action == "product_price_set")
    ).all()
    price_changed = session.scalars(
        select(AuditLog).where(AuditLog.action == "product_price_changed")
    ).all()

    assert len(price_set) == 1
    assert price_set[0].user_id == admin.id
    assert "new_price=100" in price_set[0].details

    assert len(price_changed) == 1
    assert price_changed[0].user_id == admin.id
    assert "old_price=100" in price_changed[0].details
    assert "new_price=125" in price_changed[0].details


def test_operator_cannot_deactivate_product(session):
    product = create_product(
        session, sku="ACTIVE-001", name="Active Product",
        category_id=None, unit_id=None, location_id=None,
        price=Decimal("100"), reorder_level=Decimal("0"),
        opening_stock=Decimal("0"),
    )

    operator = create_user(session, "operator", "operator-password", role="operator")
    session.commit()
    set_current_user(operator)

    with pytest.raises(PermissionDeniedError):
        set_product_active(session, product.id, False)

    assert product.is_active is True


# --- service-layer authorization for reference data, suppliers and customers ---

from app.services import master_data


MASTER_DATA_MUTATIONS = [
    "create_reference",
    "rename_reference",
    "set_reference_active",
    "save_supplier",
    "set_supplier_active",
    "save_customer",
    "set_customer_active",
]


def _prepare_master_data_mutation(session, action):
    """Prepare records while the fixture's administrator is still active."""
    category = create_reference(session, Category, "Protected Category")
    supplier = save_supplier(session, None, "Protected Supplier", "", "")
    customer = save_customer(session, None, "Protected Customer", "")

    if action == "create_reference":
        return lambda: master_data.create_reference(
            session, Category, "Another Category"
        )
    if action == "rename_reference":
        return lambda: master_data.rename_reference(
            session, Category, category.id, "Renamed Category"
        )
    if action == "set_reference_active":
        return lambda: master_data.set_reference_active(
            session, Category, category.id, False
        )
    if action == "save_supplier":
        return lambda: master_data.save_supplier(
            session, supplier.id, "Updated Supplier", "", ""
        )
    if action == "set_supplier_active":
        return lambda: master_data.set_supplier_active(
            session, supplier.id, False
        )
    if action == "save_customer":
        return lambda: master_data.save_customer(
            session, customer.id, "Updated Customer", ""
        )
    if action == "set_customer_active":
        return lambda: master_data.set_customer_active(
            session, customer.id, False
        )

    raise AssertionError(f"Unknown master-data mutation: {action}")


@pytest.mark.parametrize("action", MASTER_DATA_MUTATIONS)
@pytest.mark.parametrize("role", ["operator", "viewer", None])
def test_restricted_roles_cannot_mutate_master_data(session, action, role):
    mutation = _prepare_master_data_mutation(session, action)

    if role is None:
        set_current_user(None)
    else:
        user = create_user(
            session,
            f"restricted_{role}",
            "test-password-123",
            role=role,
        )
        session.commit()
        set_current_user(user)

    with pytest.raises(PermissionDeniedError):
        mutation()


@pytest.mark.parametrize("action", MASTER_DATA_MUTATIONS)
def test_manager_can_mutate_master_data(session, action):
    mutation = _prepare_master_data_mutation(session, action)

    manager = create_user(
        session,
        "manager_user",
        "manager-password-123",
        role="manager",
    )
    session.commit()
    set_current_user(manager)

    result = mutation()
    assert result is not None


# MASTER DATA AUDIT COVERAGE TESTS

def _audit_events(session, action):
    return session.scalars(
        select(AuditLog).where(AuditLog.action == action)
    ).all()


def test_reference_creation_and_rename_are_audited(session):
    category = create_reference(session, Category, "Audit Beverages")
    rename_reference = master_data.rename_reference
    rename_reference(session, Category, category.id, "Renamed Beverages")

    created = _audit_events(session, "reference_created")
    renamed = _audit_events(session, "reference_renamed")

    assert len(created) == 1
    assert f"id={category.id}" in created[0].details
    assert "name=Audit Beverages" in created[0].details
    assert created[0].user_id == get_current_user().id

    assert len(renamed) == 1
    assert "old_name=Audit Beverages" in renamed[0].details
    assert "new_name=Renamed Beverages" in renamed[0].details
    assert renamed[0].user_id == get_current_user().id


def test_supplier_creation_and_update_are_audited_without_private_values(session):
    supplier = save_supplier(
        session, None, "Audit Supplier",
        "PRIVATE_CONTACT_123", "PRIVATE_ADDRESS_456",
    )
    save_supplier(
        session, supplier.id, "Updated Audit Supplier",
        "PRIVATE_CONTACT_789", "PRIVATE_ADDRESS_999",
    )

    created = _audit_events(session, "supplier_created")
    updated = _audit_events(session, "supplier_updated")

    assert len(created) == 1
    assert "name=Audit Supplier" in created[0].details
    assert "PRIVATE_CONTACT" not in created[0].details
    assert "PRIVATE_ADDRESS" not in created[0].details

    assert len(updated) == 1
    assert "name=Updated Audit Supplier" in updated[0].details
    assert "changed_fields=name,contact,address" in updated[0].details
    assert "PRIVATE_CONTACT" not in updated[0].details
    assert "PRIVATE_ADDRESS" not in updated[0].details
    assert updated[0].user_id == get_current_user().id


def test_customer_creation_and_update_are_audited_without_private_values(session):
    customer = save_customer(
        session, None, "Audit Customer", "PRIVATE_CUSTOMER_CONTACT_123"
    )
    save_customer(
        session, customer.id, "Updated Audit Customer",
        "PRIVATE_CUSTOMER_CONTACT_456",
    )

    created = _audit_events(session, "customer_created")
    updated = _audit_events(session, "customer_updated")

    assert len(created) == 1
    assert "name=Audit Customer" in created[0].details
    assert "PRIVATE_CUSTOMER_CONTACT" not in created[0].details

    assert len(updated) == 1
    assert "name=Updated Audit Customer" in updated[0].details
    assert "changed_fields=name,contact" in updated[0].details
    assert "PRIVATE_CUSTOMER_CONTACT" not in updated[0].details
    assert updated[0].user_id == get_current_user().id


def test_product_creation_is_audited(session):
    product = create_product(
        session, sku="AUDIT-CREATE-001", name="Audit Product",
        category_id=None, unit_id=None, location_id=None,
        price=Decimal("100"), reorder_level=Decimal("5"),
        opening_stock=Decimal("10"),
    )

    entries = _audit_events(session, "product_created")

    assert len(entries) == 1
    assert f"id={product.id}" in entries[0].details
    assert "sku=AUDIT-CREATE-001" in entries[0].details
    assert "name=Audit Product" in entries[0].details
    assert entries[0].user_id == get_current_user().id


def test_product_non_price_updates_are_audited(session):
    product = create_product(
        session, sku="AUDIT-UPDATE-001", name="Original Product",
        category_id=None, unit_id=None, location_id=None,
        price=Decimal("100"), reorder_level=Decimal("0"),
        opening_stock=Decimal("0"),
    )

    update_product(
        session, product.id, sku="AUDIT-UPDATE-002",
        name="Renamed Product", category_id=None, unit_id=None,
        location_id=None, price=Decimal("100"),
        reorder_level=Decimal("5"), barcode="BARCODE-001",
    )

    entries = _audit_events(session, "product_updated")

    assert len(entries) == 1
    assert "sku=AUDIT-UPDATE-002" in entries[0].details
    assert "sku" in entries[0].details
    assert "name" in entries[0].details
    assert "barcode" in entries[0].details
    assert "reorder_level" in entries[0].details
    assert entries[0].user_id == get_current_user().id


def test_product_price_only_update_does_not_create_generic_update_event(session):
    product = create_product(
        session, sku="AUDIT-PRICE-001", name="Price Only Product",
        category_id=None, unit_id=None, location_id=None,
        price=Decimal("100"), reorder_level=Decimal("0"),
        opening_stock=Decimal("0"),
    )

    update_product(
        session, product.id, sku="AUDIT-PRICE-001",
        name="Price Only Product", category_id=None, unit_id=None,
        location_id=None, price=Decimal("125"),
        reorder_level=Decimal("0"),
    )

    assert len(_audit_events(session, "product_price_changed")) == 1
    assert len(_audit_events(session, "product_updated")) == 0


def test_unchanged_supplier_and_customer_do_not_create_update_events(session):
    supplier = save_supplier(session, None, "Unchanged Supplier", "Contact", "Address")
    customer = save_customer(session, None, "Unchanged Customer", "Contact")

    save_supplier(session, supplier.id, "Unchanged Supplier", "Contact", "Address")
    save_customer(session, customer.id, "Unchanged Customer", "Contact")

    assert len(_audit_events(session, "supplier_updated")) == 0
    assert len(_audit_events(session, "customer_updated")) == 0

def test_manager_can_edit_product_details_but_not_price(session):
    product = create_product(
        session, sku="MANAGER-EDIT-001", name="Original",
        category_id=None, unit_id=None, location_id=None,
        price=Decimal("100"), reorder_level=Decimal("0"),
        opening_stock=Decimal("0"),
    )

    manager = create_user(
        session, "product_manager", "manager-password", role="manager"
    )
    session.commit()
    set_current_user(manager)

    updated = update_product(
        session, product.id, sku="MANAGER-EDIT-001", name="Manager Updated",
        category_id=None, unit_id=None, location_id=None,
        price=Decimal("100"), reorder_level=Decimal("2"),
    )

    assert updated.name == "Manager Updated"
    assert updated.reorder_level == Decimal("2")
    assert updated.price == Decimal("100")

    with pytest.raises(PermissionDeniedError):
        update_product(
            session, product.id, sku="MANAGER-EDIT-001", name="Manager Updated",
            category_id=None, unit_id=None, location_id=None,
            price=Decimal("125"), reorder_level=Decimal("2"),
        )

    assert product.price == Decimal("100")


def test_manager_cannot_deactivate_product(session):
    product = create_product(
        session, sku="MANAGER-ACTIVE-001", name="Protected Product",
        category_id=None, unit_id=None, location_id=None,
        price=Decimal("100"), reorder_level=Decimal("0"),
        opening_stock=Decimal("0"),
    )

    manager = create_user(
        session, "manager_status", "manager-password", role="manager"
    )
    session.commit()
    set_current_user(manager)

    with pytest.raises(PermissionDeniedError):
        set_product_active(session, product.id, False)

    assert product.is_active is True



def test_master_data_lists_require_authentication(session):
    admin = get_current_user()

    list_calls = [
        lambda: list_reference(session, Category),
        lambda: list_suppliers(session),
        lambda: list_customers(session),
        lambda: list_products(session),
    ]

    set_current_user(None)
    for list_call in list_calls:
        with pytest.raises(PermissionDeniedError):
            list_call()

    for role in ("admin", "manager", "operator", "viewer"):
        set_current_user(admin)

        if role == "admin":
            user = admin
        else:
            user = create_user(
                session,
                f"list_test_{role}",
                "test-password-123",
                role=role,
            )
            session.commit()

        set_current_user(user)

        for list_call in list_calls:
            assert isinstance(list_call(), list)

from app.data.models import Category, Unit, Location

REFERENCE_FIELDS = [
    (Category, "category_id"),
    (Unit, "unit_id"),
    (Location, "location_id"),
]


@pytest.mark.parametrize("model,field", REFERENCE_FIELDS)
def test_create_product_rejects_inactive_reference(session, model, field):
    reference = create_reference(session, model, f"Inactive {model.__name__}")
    set_reference_active(session, model, reference.id, False)

    references = {"category_id": None, "unit_id": None, "location_id": None}
    references[field] = reference.id

    with pytest.raises(master_data.InvalidProductDataError):
        create_product(
            session, sku=f"INACTIVE-{field}", name="Invalid Product",
            **references, price=Decimal("10"),
            reorder_level=Decimal("0"), opening_stock=Decimal("0"),
        )


@pytest.mark.parametrize("model,field", REFERENCE_FIELDS)
def test_create_product_rejects_nonexistent_reference(session, model, field):
    references = {"category_id": None, "unit_id": None, "location_id": None}
    references[field] = 999999

    with pytest.raises(master_data.InvalidProductDataError):
        create_product(
            session, sku=f"MISSING-{field}", name="Invalid Product",
            **references, price=Decimal("10"),
            reorder_level=Decimal("0"), opening_stock=Decimal("0"),
        )


@pytest.mark.parametrize("model,field", REFERENCE_FIELDS)
def test_update_product_rejects_new_inactive_reference(session, model, field):
    product = create_product(
        session, sku=f"UPDATE-INACTIVE-{field}", name="Existing Product",
        category_id=None, unit_id=None, location_id=None,
        price=Decimal("10"), reorder_level=Decimal("0"),
        opening_stock=Decimal("0"),
    )
    reference = create_reference(session, model, f"Inactive Update {model.__name__}")
    set_reference_active(session, model, reference.id, False)

    references = {"category_id": None, "unit_id": None, "location_id": None}
    references[field] = reference.id

    with pytest.raises(master_data.InvalidProductDataError):
        update_product(
            session, product.id, sku=product.sku, name=product.name,
            **references, price=product.price,
            reorder_level=product.reorder_level,
        )


@pytest.mark.parametrize("model,field", REFERENCE_FIELDS)
def test_update_product_rejects_new_nonexistent_reference(session, model, field):
    product = create_product(
        session, sku=f"UPDATE-MISSING-{field}", name="Existing Product",
        category_id=None, unit_id=None, location_id=None,
        price=Decimal("10"), reorder_level=Decimal("0"),
        opening_stock=Decimal("0"),
    )

    references = {"category_id": None, "unit_id": None, "location_id": None}
    references[field] = 999999

    with pytest.raises(master_data.InvalidProductDataError):
        update_product(
            session, product.id, sku=product.sku, name=product.name,
            **references, price=product.price,
            reorder_level=product.reorder_level,
        )


@pytest.mark.parametrize("model,field", REFERENCE_FIELDS)
def test_update_product_can_retain_unchanged_inactive_reference(session, model, field):
    reference = create_reference(session, model, f"Retained {model.__name__}")
    references = {"category_id": None, "unit_id": None, "location_id": None}
    references[field] = reference.id

    product = create_product(
        session, sku=f"RETAIN-{field}", name="Existing Product",
        **references, price=Decimal("10"),
        reorder_level=Decimal("0"), opening_stock=Decimal("0"),
    )
    set_reference_active(session, model, reference.id, False)

    updated = update_product(
        session, product.id, sku=product.sku, name="Updated Product",
        **references, price=product.price,
        reorder_level=product.reorder_level,
    )

    assert updated.name == "Updated Product"
    assert getattr(updated, field) == reference.id
