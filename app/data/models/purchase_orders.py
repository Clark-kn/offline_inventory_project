from datetime import datetime
from app.utils.timezone import utc_now_naive

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.data.models.base import Base
from app.data.models.types import SqliteDecimal


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    reference: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(default=utc_now_naive)
    notes: Mapped[str | None] = mapped_column(String(500))


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    __table_args__ = (
        CheckConstraint(
            "CAST(ordered_quantity AS NUMERIC) > 0",
            name="ck_po_item_ordered_quantity_positive",
        ),
        CheckConstraint(
            "CAST(unit_price AS NUMERIC) >= 0",
            name="ck_po_item_unit_price_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    ordered_quantity = mapped_column(SqliteDecimal, nullable=False)
    unit_price = mapped_column(SqliteDecimal, nullable=False)


class PurchaseOrderReceipt(Base):
    __tablename__ = "purchase_order_receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id"), nullable=False
    )
    reference: Mapped[str | None] = mapped_column(String(200))
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(default=utc_now_naive)
    notes: Mapped[str | None] = mapped_column(String(500))


class PurchaseOrderReceiptItem(Base):
    __tablename__ = "purchase_order_receipt_items"

    __table_args__ = (
        CheckConstraint(
            "CAST(quantity AS NUMERIC) > 0",
            name="ck_po_receipt_item_quantity_positive",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_order_receipts.id"), nullable=False
    )
    purchase_order_item_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_order_items.id"), nullable=False
    )
    quantity = mapped_column(SqliteDecimal, nullable=False)


class PurchaseOrderClosure(Base):
    __tablename__ = "purchase_order_closures"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id"), nullable=False
    )
    closed_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    closed_at: Mapped[datetime] = mapped_column(default=utc_now_naive)
    notes: Mapped[str | None] = mapped_column(String(500))


class PurchaseOrderClosureItem(Base):
    __tablename__ = "purchase_order_closure_items"

    __table_args__ = (
        CheckConstraint(
            "CAST(quantity AS NUMERIC) > 0",
            name="ck_po_closure_item_quantity_positive",
        ),
        CheckConstraint(
            "reason_code IN ("
            "'supplier_out_of_stock', "
            "'product_discontinued', "
            "'supplier_cancelled_remainder', "
            "'no_longer_required', "
            "'quality_specification_issue', "
            "'price_terms_changed', "
            "'other'"
            ")",
            name="ck_po_closure_reason_code",
        ),
        CheckConstraint(
            "reason_code != 'other' OR "
            "(explanation IS NOT NULL AND length(trim(explanation)) > 0)",
            name="ck_po_closure_other_explanation",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    closure_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_order_closures.id"), nullable=False
    )
    purchase_order_item_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_order_items.id"), nullable=False
    )
    quantity = mapped_column(SqliteDecimal, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(60), nullable=False)
    explanation: Mapped[str | None] = mapped_column(String(500))
