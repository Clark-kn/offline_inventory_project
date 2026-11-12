"""create standalone damaged goods records

Revision ID: f82a6c1d9e40
Revises: e71c4a9d2f60
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.data.models.types


revision: str = "f82a6c1d9e40"
down_revision: Union[str, None] = "e71c4a9d2f60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "damaged_goods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("unit_name", sa.String(length=60), nullable=False),
        sa.Column(
            "quantity",
            app.data.models.types.SqliteDecimal(),
            nullable=False,
        ),
        sa.Column("supplier_name", sa.String(length=200), nullable=False),
        sa.Column("date_brought", sa.Date(), nullable=False),
        sa.Column(
            "recorded_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_damaged_goods_quantity_positive",
        ),
    )


def downgrade() -> None:
    op.drop_table("damaged_goods")
