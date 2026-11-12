from sqlalchemy import select
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.data.models import User
from app.utils.timezone import format_kigali
from app.data.session import new_session
from app.services.master_data import list_products
from app.services.reports import product_ledger


MOVEMENT_LABELS = {
    "purchase": "Purchase",
    "sale": "Sale",
    "adjustment": "Stock Adjustment",
    "purchase_order_receipt": "Purchase Order Receipt",
    "damage": "Damage",
    "return": "Return",
    "opening_stock": "Opening Stock",
}


def movement_label(reason: str) -> str:
    """Return a readable label while preserving unknown movement reasons."""
    return MOVEMENT_LABELS.get(
        reason,
        reason.replace("_", " ").strip().title() or "Unknown",
    )


class StockLedgerTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")

        self.product_combo = QComboBox()
        self.product_combo.currentIndexChanged.connect(self.refresh)

        form = QFormLayout()
        form.addRow("Product", self.product_combo)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Date & Time",
            "Movement",
            "Reference",
            "Party",
            "Performed By",
            "Qty Change",
            "Balance After",
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        layout.addLayout(form)
        layout.addWidget(self.table)

        self.refresh_products()

    def refresh_products(self):
        self.product_combo.blockSignals(True)
        self.product_combo.clear()

        with new_session() as session:
            for product in list_products(session, include_inactive=True):
                self.product_combo.addItem(
                    f"{product.sku} - {product.name}",
                    product.id,
                )

        self.product_combo.blockSignals(False)
        self.refresh()

    def refresh(self):
        product_id = self.product_combo.currentData()
        self.table.setRowCount(0)

        if product_id is None:
            return

        with new_session() as session:
            rows = product_ledger(session, product_id)

            # Fetch all relevant usernames in one query, avoiding one query
            # per ledger row.
            user_ids = {
                txn.user_id
                for txn in rows
                if txn.user_id is not None
            }

            usernames = {}
            if user_ids:
                usernames = dict(
                    session.execute(
                        select(User.id, User.username).where(
                            User.id.in_(user_ids)
                        )
                    ).all()
                )

            self.table.setRowCount(len(rows))

            for i, txn in enumerate(rows):
                performed_by = (
                    usernames.get(txn.user_id, "System / Unattributed")
                    if txn.user_id is not None
                    else "System / Unattributed"
                )

                reference = (txn.reference or "").strip() or "—"

                party_type = (
                    (txn.party_type or "").replace("_", " ").strip().title()
                )
                party_name = (txn.party_name or "").strip()

                if party_type and party_name:
                    party = f"{party_type} — {party_name}"
                else:
                    party = party_type or party_name or "—"

                values = [
                    format_kigali(txn.created_at),
                    movement_label(txn.reason),
                    reference,
                    party,
                    performed_by,
                    str(txn.qty_delta),
                    str(txn.balance_after),
                ]

                for column, value in enumerate(values):
                    self.table.setItem(
                        i,
                        column,
                        QTableWidgetItem(value),
                    )
