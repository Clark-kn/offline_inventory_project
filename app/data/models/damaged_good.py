from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.data.models.base import Base
from app.data.models.types import SqliteDecimal
from app.utils.timezone import utc_now_naive


class DamagedGood(Base):
    """Standalone damaged-goods record; never changes inventory stock."""

    __tablename__ = "damaged_goods"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_damaged_goods_quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_name: Mapped[str] = mapped_column(String(60), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(SqliteDecimal, nullable=False)
    supplier_name: Mapped[str] = mapped_column(String(200), nullable=False)
    date_brought: Mapped[date] = mapped_column(Date, nullable=False)
    recorded_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
