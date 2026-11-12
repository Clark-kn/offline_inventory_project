from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.data.models import DamagedGood, Supplier, Unit
from app.security.permissions import require_admin, require_authenticated
from app.services.audit import log_action


class DamagedGoodsError(Exception):
    """Base error for damaged-goods operations."""


class InvalidDamagedGoodsError(DamagedGoodsError):
    """Raised when damaged-goods input is invalid."""


class ReferenceNotFoundError(DamagedGoodsError):
    """Raised when a selected unit or supplier is unavailable."""


def record_damaged_goods(
    session,
    *,
    unit_id: int,
    quantity,
    supplier_id: int,
    date_brought: date,
) -> DamagedGood:
    """Record damaged goods without changing stock or the stock ledger."""
    user = require_authenticated()

    try:
        amount = Decimal(str(quantity))
    except (InvalidOperation, TypeError, ValueError):
        raise InvalidDamagedGoodsError("Quantity must be a valid number.") from None

    if not amount.is_finite() or amount <= 0:
        raise InvalidDamagedGoodsError("Quantity must be greater than zero.")

    if not isinstance(date_brought, date) or isinstance(date_brought, datetime):
        raise InvalidDamagedGoodsError("Date brought must be a valid date.")

    unit = session.scalar(
        select(Unit).where(Unit.id == unit_id, Unit.is_active.is_(True))
    )
    if unit is None:
        raise ReferenceNotFoundError("The selected unit is unavailable or inactive.")

    supplier = session.scalar(
        select(Supplier).where(
            Supplier.id == supplier_id,
            Supplier.is_active.is_(True),
        )
    )
    if supplier is None:
        raise ReferenceNotFoundError(
            "The selected supplier is unavailable or inactive."
        )

    record = DamagedGood(
        unit_name=unit.name,
        quantity=amount,
        supplier_name=supplier.name,
        date_brought=date_brought,
        recorded_by_user_id=user.id,
    )
    session.add(record)
    session.flush()
    return record


def list_damaged_goods(session) -> list[DamagedGood]:
    """Return damaged-goods history, newest records first."""
    require_authenticated()
    return list(
        session.scalars(
            select(DamagedGood).order_by(
                DamagedGood.date_brought.desc(),
                DamagedGood.recorded_at.desc(),
                DamagedGood.id.desc(),
            )
        ).all()
    )


def damaged_goods_totals(session) -> dict[str, Decimal]:
    """Return bottle and crate totals; other units are intentionally excluded."""
    require_authenticated()

    rows = session.execute(
        select(DamagedGood.unit_name, DamagedGood.quantity)
    ).all()

    bottle_labels = {"bottle", "bottles", "bottle(s)"}
    crate_labels = {"crate", "crates", "crate(s)"}

    totals = {"bottles": Decimal("0"), "crates": Decimal("0")}
    for unit_name, quantity in rows:
        normalized = unit_name.strip().lower()
        if normalized in bottle_labels:
            totals["bottles"] += quantity
        elif normalized in crate_labels:
            totals["crates"] += quantity

    return totals



class DamagedGoodsNotFoundError(DamagedGoodsError):
    """Raised when the requested damaged-goods record does not exist."""


def delete_damaged_goods(session, record_id: int) -> DamagedGood:
    """Delete one damaged-goods record; administrators only.

    The audit entry is written in the same transaction as the deletion.
    The caller is responsible for committing or rolling back the session.
    """
    actor = require_admin()

    record = session.get(DamagedGood, record_id)
    if record is None:
        raise DamagedGoodsNotFoundError(
            f"Damaged-goods record {record_id} does not exist."
        )

    details = (
        f"id={record.id} "
        f"unit={record.unit_name} "
        f"quantity={record.quantity} "
        f"supplier={record.supplier_name} "
        f"date_brought={record.date_brought.isoformat()} "
        f"recorded_by_user_id={record.recorded_by_user_id} "
        f"recorded_at={record.recorded_at.isoformat()} "
        f"deleted_by={actor.username}"
    )

    log_action(
        session,
        "damaged_good_deleted",
        details,
        actor_user_id=actor.id,
    )
    session.delete(record)
    session.flush()
    return record
