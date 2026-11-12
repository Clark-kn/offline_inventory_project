from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import Category, Customer, Location, Product, Supplier, Unit
from app.security.permissions import PermissionDeniedError, require_admin, require_authenticated, require_management_access, require_transaction_access
from app.services.audit import log_action
from app.services.stock_ledger import record_movement


class DuplicateNameError(Exception):
    pass


class DuplicateSkuError(Exception):
    pass


class InvalidProductDataError(Exception):
    pass


def _validate_product_fields(price: Decimal, reorder_level: Decimal) -> None:
    if price < 0 or reorder_level < 0:
        raise InvalidProductDataError("Price and reorder level cannot be negative")


def _validate_reference_assignment(
    session: Session,
    model,
    reference_id: int | None,
    current_reference_id: int | None = None,
) -> None:
    if reference_id is None or reference_id == current_reference_id:
        return

    reference = session.get(model, reference_id)
    if reference is None or not reference.is_active:
        raise InvalidProductDataError(
            f"Cannot assign an inactive or nonexistent {model.__name__.lower()}."
        )


# --- generic name-only reference data (Category, Unit, Location) ---------

def list_reference(session: Session, model, include_inactive: bool = False):
    require_authenticated()
    stmt = select(model).order_by(model.name)
    if not include_inactive:
        stmt = stmt.where(model.is_active.is_(True))
    return session.scalars(stmt).all()



def create_reference(session: Session, model, name: str):
    require_management_access()
    name = name.strip()
    existing = session.scalar(select(model).where(model.name == name))
    if existing is not None:
        raise DuplicateNameError(f"{model.__name__} '{name}' already exists")
    row = model(name=name)
    session.add(row)
    session.flush()
    log_action(
        session,
        "reference_created",
        f"{model.__name__} id={row.id} name={row.name}",
    )
    return row


def rename_reference(session: Session, model, row_id: int, new_name: str):
    require_management_access()
    new_name = new_name.strip()
    existing = session.scalar(
        select(model).where(model.name == new_name, model.id != row_id)
    )
    if existing is not None:
        raise DuplicateNameError(f"{model.__name__} '{new_name}' already exists")
    row = session.get(model, row_id)
    old_name = row.name
    if old_name != new_name:
        row.name = new_name
        session.flush()
        log_action(
            session,
            "reference_renamed",
            f"{model.__name__} id={row.id} old_name={old_name} new_name={new_name}",
        )
    return row

def set_reference_active(session: Session, model, row_id: int, is_active: bool):
    require_management_access()
    """Reference rows are never hard-deleted once they may be referenced by
    products; toggle status instead."""
    row = session.get(model, row_id)
    row.is_active = is_active
    log_action(session, "reference_status_changed", f"{model.__name__} id={row_id} name={row.name} is_active={is_active}")
    session.flush()
    return row


# --- suppliers / customers ------------------------------------------------

def list_suppliers(session: Session, include_inactive: bool = False):
    require_authenticated()
    stmt = select(Supplier).order_by(Supplier.name)
    if not include_inactive:
        stmt = stmt.where(Supplier.is_active.is_(True))
    return session.scalars(stmt).all()



def save_supplier(session: Session, supplier_id: int | None, name: str, contact: str, address: str):
    require_management_access()

    new_name = name.strip()
    new_contact = contact.strip() or None
    new_address = address.strip() or None

    if supplier_id is None:
        row = Supplier(
            name=new_name,
            contact=new_contact,
            address=new_address,
        )
        session.add(row)
        session.flush()
        log_action(
            session,
            "supplier_created",
            f"id={row.id} name={row.name}",
        )
        return row

    row = session.get(Supplier, supplier_id)
    changed_fields = []

    if row.name != new_name:
        changed_fields.append("name")
    if row.contact != new_contact:
        changed_fields.append("contact")
    if row.address != new_address:
        changed_fields.append("address")

    if changed_fields:
        row.name = new_name
        row.contact = new_contact
        row.address = new_address
        session.flush()
        log_action(
            session,
            "supplier_updated",
            f"id={row.id} name={row.name} changed_fields={','.join(changed_fields)}",
        )

    return row

def set_supplier_active(session: Session, supplier_id: int, is_active: bool):
    require_management_access()
    row = session.get(Supplier, supplier_id)
    row.is_active = is_active
    log_action(session, "supplier_status_changed", f"id={supplier_id} name={row.name} is_active={is_active}")
    session.flush()
    return row


def list_customers(session: Session, include_inactive: bool = False):
    require_authenticated()
    stmt = select(Customer).order_by(Customer.name)
    if not include_inactive:
        stmt = stmt.where(Customer.is_active.is_(True))
    return session.scalars(stmt).all()



def save_customer(session: Session, customer_id: int | None, name: str, contact: str):
    require_management_access()

    new_name = name.strip()
    new_contact = contact.strip() or None

    if customer_id is None:
        row = Customer(name=new_name, contact=new_contact)
        session.add(row)
        session.flush()
        log_action(
            session,
            "customer_created",
            f"id={row.id} name={row.name}",
        )
        return row

    row = session.get(Customer, customer_id)
    changed_fields = []

    if row.name != new_name:
        changed_fields.append("name")
    if row.contact != new_contact:
        changed_fields.append("contact")

    if changed_fields:
        row.name = new_name
        row.contact = new_contact
        session.flush()
        log_action(
            session,
            "customer_updated",
            f"id={row.id} name={row.name} changed_fields={','.join(changed_fields)}",
        )

    return row

def set_customer_active(session: Session, customer_id: int, is_active: bool):
    require_management_access()
    row = session.get(Customer, customer_id)
    row.is_active = is_active
    log_action(session, "customer_status_changed", f"id={customer_id} name={row.name} is_active={is_active}")
    session.flush()
    return row


# --- products --------------------------------------------------------------

def list_products(session: Session, include_inactive: bool = False):
    require_authenticated()
    stmt = select(Product).order_by(Product.name)
    if not include_inactive:
        stmt = stmt.where(Product.is_active.is_(True))
    return session.scalars(stmt).all()



def create_product(
    session: Session,
    sku: str,
    name: str,
    category_id: int | None,
    unit_id: int | None,
    location_id: int | None,
    price: Decimal,
    reorder_level: Decimal,
    opening_stock: Decimal,
    barcode: str | None = None,
) -> Product:
    user = require_transaction_access()
    sku = sku.strip()
    _validate_product_fields(price, reorder_level)

    if user.role != "admin" and price != Decimal("0"):
        raise PermissionDeniedError(
            "Only an administrator can set a product selling price. "
            "Workers must create products with a price of 0."
        )

    if opening_stock < 0:
        raise InvalidProductDataError("Opening stock cannot be negative")

    _validate_reference_assignment(session, Category, category_id)
    _validate_reference_assignment(session, Unit, unit_id)
    _validate_reference_assignment(session, Location, location_id)

    existing = session.scalar(select(Product).where(Product.sku == sku))
    if existing is not None:
        raise DuplicateSkuError(f"SKU '{sku}' already exists")

    product = Product(
        sku=sku,
        barcode=(barcode or "").strip() or None,
        name=name.strip(),
        category_id=category_id,
        unit_id=unit_id,
        location_id=location_id,
        price=price,
        reorder_level=reorder_level,
        current_stock=Decimal("0"),
        is_active=True,
    )
    session.add(product)
    session.flush()

    log_action(
        session,
        "product_created",
        f"id={product.id} sku={product.sku} name={product.name}",
    )

    if user.role == "admin" and price != Decimal("0"):
        log_action(
            session,
            "product_price_set",
            f"sku={sku} old_price=None new_price={price}",
        )

    if opening_stock and opening_stock != 0:
        record_movement(session, product.id, opening_stock, reason="opening_stock")

    return product


def update_product(
    session: Session,
    product_id: int,
    sku: str,
    name: str,
    category_id: int | None,
    unit_id: int | None,
    location_id: int | None,
    price: Decimal,
    reorder_level: Decimal,
    barcode: str | None = None,
) -> Product:
    user = require_management_access()
    sku = sku.strip()
    name = name.strip()
    barcode = (barcode or "").strip() or None
    _validate_product_fields(price, reorder_level)

    product = session.get(Product, product_id)
    if product is None:
        raise InvalidProductDataError(f"Product {product_id} does not exist")

    _validate_reference_assignment(
        session, Category, category_id, product.category_id
    )
    _validate_reference_assignment(
        session, Unit, unit_id, product.unit_id
    )
    _validate_reference_assignment(
        session, Location, location_id, product.location_id
    )

    old_price = product.price

    if user.role != "admin" and price != old_price:
        raise PermissionDeniedError(
            "Only an administrator can change a product selling price."
        )

    existing = session.scalar(
        select(Product).where(Product.sku == sku, Product.id != product_id)
    )
    if existing is not None:
        raise DuplicateSkuError(f"SKU '{sku}' already exists")

    changed_fields = []
    proposed_values = {
        "sku": sku,
        "barcode": barcode,
        "name": name,
        "category_id": category_id,
        "unit_id": unit_id,
        "location_id": location_id,
        "reorder_level": reorder_level,
    }

    for field, new_value in proposed_values.items():
        if getattr(product, field) != new_value:
            changed_fields.append(field)
            setattr(product, field, new_value)

    product.price = price

    if user.role == "admin" and price != old_price:
        log_action(
            session,
            "product_price_changed",
            f"sku={sku} old_price={old_price} new_price={price}",
        )

    if changed_fields:
        session.flush()
        log_action(
            session,
            "product_updated",
            f"id={product.id} sku={product.sku} changed_fields={','.join(changed_fields)}",
        )

    session.flush()
    return product

def set_product_active(session: Session, product_id: int, is_active: bool):
    """Only administrators may activate or deactivate products."""
    require_admin()

    product = session.get(Product, product_id)
    if product is None:
        raise InvalidProductDataError(f"Product {product_id} does not exist")

    product.is_active = is_active
    log_action(
        session,
        "product_status_changed",
        f"sku={product.sku} is_active={is_active}",
    )
    session.flush()
    return product
