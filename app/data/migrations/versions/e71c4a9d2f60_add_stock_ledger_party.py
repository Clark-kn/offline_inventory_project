"""add optional party snapshots to stock ledger

Revision ID: e71c4a9d2f60
Revises: d19f6a8b2c41
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e71c4a9d2f60"
down_revision: Union[str, None] = "d19f6a8b2c41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stock_transactions",
        sa.Column("party_type", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "stock_transactions",
        sa.Column("party_name", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stock_transactions", "party_name")
    op.drop_column("stock_transactions", "party_type")
