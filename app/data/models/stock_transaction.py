from datetime import datetime
from app.utils.timezone import utc_now_naive
from decimal import Decimal

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.data.models.base import Base
from app.data.models.types import SqliteDecimal


class StockTransaction(Base):
    """Stock movement ledger.

    Every stock movement creates one row here. Separate damaged-goods
    records do not affect stock. Product.current_stock is a cached
    projection of the ledger.
    """

    __tablename__ = "stock_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    qty_delta: Mapped[Decimal] = mapped_column(SqliteDecimal, nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(SqliteDecimal, nullable=False)

    reason: Mapped[str] = mapped_column(String(60), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(200))
    party_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    party_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=utc_now_naive)
