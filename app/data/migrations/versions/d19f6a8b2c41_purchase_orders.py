"""add purchase orders, receipts and outstanding closures

Revision ID: d19f6a8b2c41
Revises: 4c91a8e2d6f0
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.data.models.types


revision: str = "d19f6a8b2c41"
down_revision: Union[str, None] = "4c91a8e2d6f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("reference", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
    )

    op.create_table(
        "purchase_order_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column(
            "ordered_quantity",
            app.data.models.types.SqliteDecimal(),
            nullable=False,
        ),
        sa.Column(
            "unit_price",
            app.data.models.types.SqliteDecimal(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "CAST(ordered_quantity AS NUMERIC) > 0",
            name="ck_po_item_ordered_quantity_positive",
        ),
        sa.CheckConstraint(
            "CAST(unit_price AS NUMERIC) >= 0",
            name="ck_po_item_unit_price_nonnegative",
        ),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
    )

    op.create_table(
        "purchase_order_receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(200), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
    )

    op.create_table(
        "purchase_order_receipt_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("receipt_id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_item_id", sa.Integer(), nullable=False),
        sa.Column(
            "quantity",
            app.data.models.types.SqliteDecimal(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "CAST(quantity AS NUMERIC) > 0",
            name="ck_po_receipt_item_quantity_positive",
        ),
        sa.ForeignKeyConstraint(["receipt_id"], ["purchase_order_receipts.id"]),
        sa.ForeignKeyConstraint(
            ["purchase_order_item_id"], ["purchase_order_items.id"]
        ),
    )

    op.create_table(
        "purchase_order_closures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("closed_by_user_id", sa.Integer(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"]),
        sa.ForeignKeyConstraint(["closed_by_user_id"], ["users.id"]),
    )

    op.create_table(
        "purchase_order_closure_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("closure_id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_item_id", sa.Integer(), nullable=False),
        sa.Column(
            "quantity",
            app.data.models.types.SqliteDecimal(),
            nullable=False,
        ),
        sa.Column("reason_code", sa.String(60), nullable=False),
        sa.Column("explanation", sa.String(500), nullable=True),
        sa.CheckConstraint(
            "CAST(quantity AS NUMERIC) > 0",
            name="ck_po_closure_item_quantity_positive",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "reason_code != 'other' OR "
            "(explanation IS NOT NULL AND length(trim(explanation)) > 0)",
            name="ck_po_closure_other_explanation",
        ),
        sa.ForeignKeyConstraint(["closure_id"], ["purchase_order_closures.id"]),
        sa.ForeignKeyConstraint(
            ["purchase_order_item_id"], ["purchase_order_items.id"]
        ),
    )

    op.create_index(
        "ix_purchase_order_items_order",
        "purchase_order_items",
        ["purchase_order_id"],
    )
    op.create_index(
        "ix_purchase_order_receipts_order",
        "purchase_order_receipts",
        ["purchase_order_id"],
    )
    op.create_index(
        "ix_purchase_order_receipt_items_line",
        "purchase_order_receipt_items",
        ["purchase_order_item_id"],
    )
    op.create_index(
        "ix_purchase_order_closures_order",
        "purchase_order_closures",
        ["purchase_order_id"],
    )
    op.create_index(
        "ix_purchase_order_closure_items_line",
        "purchase_order_closure_items",
        ["purchase_order_item_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_purchase_order_closure_items_line",
        table_name="purchase_order_closure_items",
    )
    op.drop_index(
        "ix_purchase_order_closures_order",
        table_name="purchase_order_closures",
    )
    op.drop_index(
        "ix_purchase_order_receipt_items_line",
        table_name="purchase_order_receipt_items",
    )
    op.drop_index(
        "ix_purchase_order_receipts_order",
        table_name="purchase_order_receipts",
    )
    op.drop_index(
        "ix_purchase_order_items_order",
        table_name="purchase_order_items",
    )

    op.drop_table("purchase_order_closure_items")
    op.drop_table("purchase_order_closures")
    op.drop_table("purchase_order_receipt_items")
    op.drop_table("purchase_order_receipts")
    op.drop_table("purchase_order_items")
    op.drop_table("purchase_orders")
