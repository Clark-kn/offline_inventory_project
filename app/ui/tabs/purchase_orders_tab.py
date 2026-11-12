from decimal import Decimal, InvalidOperation

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.data.models import Product, Supplier
from app.utils.timezone import format_kigali
from app.data.session import new_session
from app.security.permissions import (
    PermissionDeniedError,
    current_role,
)
from app.services.master_data import list_products, list_suppliers
from app.services.purchase_orders import (
    CLOSURE_REASONS,
    PurchaseOrderClosureLineItem,
    PurchaseOrderError,
    PurchaseOrderLineItem,
    PurchaseOrderReceiptLineItem,
    close_purchase_order_outstanding,
    create_purchase_order,
    get_purchase_order_balances,
    list_purchase_orders,
    record_purchase_order_receipt,
)


CLOSURE_REASON_LABELS = {
    "supplier_out_of_stock": "Supplier out of stock",
    "product_discontinued": "Product discontinued",
    "supplier_cancelled_remainder": "Supplier cancelled remainder",
    "no_longer_required": "Delivery no longer required",
    "quality_specification_issue": "Quality/specification issue",
    "price_terms_changed": "Price or terms changed",
    "other": "Other",
}


def _decimal_value(text, label):
    try:
        value = Decimal(str(text).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{label} must be a valid number.")

    if not value.is_finite():
        raise ValueError(f"{label} must be finite.")

    if value <= 0:
        raise ValueError(f"{label} must be greater than zero.")

    return value


class PurchaseOrderCreateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Purchase Order")
        self.resize(880, 560)
        self.setMinimumSize(760, 460)

        self.supplier_combo = QComboBox()
        self.supplier_combo.addItem("(No supplier)", None)

        self.reference_edit = QLineEdit()
        self.reference_edit.setPlaceholderText("Optional supplier/order reference")

        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Optional notes")

        with new_session() as session:
            for supplier in list_suppliers(session):
                self.supplier_combo.addItem(supplier.name, supplier.id)

            self.products = list_products(session)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            ["Product", "Ordered quantity", "Unit cost"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 145)
        self.table.setColumnWidth(2, 130)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setMinimumHeight(180)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)

        add_button = QPushButton("Add Product")
        remove_button = QPushButton("Remove Selected")
        add_button.clicked.connect(self._add_line)
        remove_button.clicked.connect(self._remove_line)

        line_buttons = QHBoxLayout()
        line_buttons.addWidget(add_button)
        line_buttons.addWidget(remove_button)
        line_buttons.addStretch()

        form = QFormLayout()
        form.addRow("Supplier", self.supplier_combo)
        form.addRow("Order reference", self.reference_edit)
        form.addRow("Notes", self.notes_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addLayout(form)
        layout.addWidget(QLabel("Products in this order"))
        layout.addLayout(line_buttons)
        layout.addWidget(self.table)
        layout.addWidget(buttons)

        self._add_line()

    def _add_line(self):
        if not self.products:
            QMessageBox.information(
                self,
                "No active products",
                "Add an active product before creating a purchase order.",
            )
            return

        row = self.table.rowCount()
        self.table.insertRow(row)

        product_combo = QComboBox()
        for product in self.products:
            product_combo.addItem(
                f"{product.sku} - {product.name}",
                product.id,
            )
        product_combo.setMinimumContentsLength(24)
        product_combo.setMinimumWidth(280)

        quantity_edit = QLineEdit("1")
        quantity_edit.setMinimumWidth(100)
        cost_edit = QLineEdit("0")
        cost_edit.setMinimumWidth(100)

        self.table.setCellWidget(row, 0, product_combo)
        self.table.setCellWidget(row, 1, quantity_edit)
        self.table.setCellWidget(row, 2, cost_edit)

    def _remove_line(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _validate(self):
        if self.table.rowCount() == 0:
            QMessageBox.warning(
                self,
                "No products",
                "Add at least one product to the order.",
            )
            return

        try:
            self.values()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid order", str(exc))
            return

        self.accept()

    def values(self):
        items = []
        seen_products = set()

        for row in range(self.table.rowCount()):
            product_combo = self.table.cellWidget(row, 0)
            quantity_edit = self.table.cellWidget(row, 1)
            cost_edit = self.table.cellWidget(row, 2)

            product_id = product_combo.currentData()

            if product_id in seen_products:
                raise ValueError(
                    "A product appears more than once. "
                    "Use one line per product."
                )
            seen_products.add(product_id)

            quantity = _decimal_value(
                quantity_edit.text(),
                f"Row {row + 1} ordered quantity",
            )

            try:
                unit_cost = Decimal(cost_edit.text().strip())
            except (InvalidOperation, ValueError):
                raise ValueError(
                    f"Row {row + 1} unit cost must be numeric."
                )

            if not unit_cost.is_finite() or unit_cost < 0:
                raise ValueError(
                    f"Row {row + 1} unit cost must be finite and nonnegative."
                )

            items.append(
                PurchaseOrderLineItem(
                    product_id=product_id,
                    ordered_quantity=quantity,
                    unit_price=unit_cost,
                )
            )

        return (
            self.supplier_combo.currentData(),
            self.reference_edit.text().strip() or None,
            items,
            self.notes_edit.text().strip() or None,
        )


class PurchaseOrderActionDialog(QDialog):
    def __init__(self, balances, action, parent=None):
        super().__init__(parent)
        self.action = action
        self.balances = balances
        self.setObjectName("PurchaseOrderActionDialog")

        title = (
            "Record Purchase Order Receipt"
            if action == "receive"
            else "Close Outstanding Quantities"
        )
        self.setWindowTitle(title)
        # Keep the dialog usable on smaller displays.
        self.resize(1000, 620)
        self.setMinimumSize(680, 420)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [
                "Product",
                "Ordered",
                "Received",
                "Closed",
                "Outstanding",
                "Quantity",
            ]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column, width in {
            1: 85, 2: 85, 3: 80, 4: 110, 5: 130
        }.items():
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            self.table.setColumnWidth(column, width)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed,
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)

        self.quantity_edits = {}

        for balance in balances:
            row = self.table.rowCount()
            self.table.insertRow(row)

            item = balance.item

            with new_session() as session:
                product = session.get(Product, item.product_id)
                product_label = (
                    f"{product.sku} - {product.name}"
                    if product else f"Product #{item.product_id}"
                )

            values = [
                product_label,
                str(item.ordered_quantity),
                str(balance.received_quantity),
                str(balance.closed_quantity),
                str(balance.outstanding_quantity),
            ]

            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                self.table.setItem(row, column, cell)

            quantity_edit = QLineEdit()
            quantity_edit.setPlaceholderText("Enter quantity")
            self.table.setCellWidget(row, 5, quantity_edit)
            self.quantity_edits[item.id] = quantity_edit

        # Compact tables for short orders; internally scroll long orders.
        table_content_height = (
            self.table.horizontalHeader().height()
            + self.table.rowCount() * 38
            + 8
        )
        self.table.setFixedHeight(min(360, max(76, table_content_height)))

        self.reference_edit = QLineEdit()
        self.notes_edit = QLineEdit()

        form = QFormLayout()

        if action == "receive":
            self.reference_edit.setPlaceholderText(
                "Optional delivery note/reference"
            )
            self.notes_edit.setPlaceholderText("Optional receipt notes")
            form.addRow("Receipt reference", self.reference_edit)
            form.addRow("Receipt notes", self.notes_edit)
        else:
            self.reason_combo = QComboBox()
            for code in CLOSURE_REASONS:
                self.reason_combo.addItem(
                    CLOSURE_REASON_LABELS[code],
                    code,
                )

            self.explanation_edit = QLineEdit()
            self.explanation_edit.setPlaceholderText(
                "Required only when reason is Other"
            )

            self.notes_edit.setPlaceholderText("Optional closure notes")

            form.addRow("Closure reason", self.reason_combo)
            form.addRow("Explanation", self.explanation_edit)
            form.addRow("Closure notes", self.notes_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)

        # Scroll the dialog content while keeping Save/Cancel accessible.
        content = QWidget()
        content.setObjectName("PurchaseOrderDialogContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(12)
        content_layout.addWidget(
            QLabel(
                "Enter quantities only for the lines being processed. "
                "Leave other lines blank."
            )
        )
        content_layout.addWidget(self.table)
        content_layout.addLayout(form)

        scroll_area = QScrollArea()
        scroll_area.setObjectName("PurchaseOrderDialogScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setWidget(content)

        buttons.setMinimumHeight(52)
        save_button = buttons.button(QDialogButtonBox.Save)
        cancel_button = buttons.button(QDialogButtonBox.Cancel)

        if save_button:
            save_button.setObjectName("PrimaryButton")
            save_button.setMinimumWidth(100)

        if cancel_button:
            cancel_button.setMinimumWidth(100)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)
        layout.addWidget(scroll_area, 1)
        layout.addWidget(buttons)

        # Keep this styling local to the two Purchase Order action dialogs.
        self.setStyleSheet("""
            QDialog#PurchaseOrderActionDialog {
                background-color: #f8fafc;
            }

            QDialog#PurchaseOrderActionDialog QLabel {
                color: #334155;
                background-color: transparent;
            }

            QWidget#PurchaseOrderDialogContent {
                background-color: #f8fafc;
            }

            QScrollArea#PurchaseOrderDialogScrollArea {
                background-color: #f8fafc;
                border: none;
            }

            QScrollArea#PurchaseOrderDialogScrollArea QWidget {
                background-color: #f8fafc;
            }

            QDialog#PurchaseOrderActionDialog QLineEdit,
            QDialog#PurchaseOrderActionDialog QComboBox {
                background-color: #ffffff;
                color: #1e293b;
            }

            QDialog#PurchaseOrderActionDialog QDialogButtonBox {
                background-color: #ffffff;
            }
        """)

    def _validate(self):
        try:
            self.values()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid quantities", str(exc))
            return

        self.accept()

    def values(self):
        selected = []

        for item_id, edit in self.quantity_edits.items():
            raw = edit.text().strip()
            if not raw:
                continue

            quantity = _decimal_value(raw, "Quantity")

            if self.action == "receive":
                selected.append(
                    PurchaseOrderReceiptLineItem(
                        purchase_order_item_id=item_id,
                        quantity=quantity,
                    )
                )
            else:
                selected.append(
                    PurchaseOrderClosureLineItem(
                        purchase_order_item_id=item_id,
                        quantity=quantity,
                        reason_code=self.reason_combo.currentData(),
                        explanation=self.explanation_edit.text().strip() or None,
                    )
                )

        if not selected:
            raise ValueError("Enter a quantity for at least one order line.")

        notes = self.notes_edit.text().strip() or None

        if self.action == "receive":
            return (
                selected,
                self.reference_edit.text().strip() or None,
                notes,
            )

        return selected, notes


class PurchaseOrdersTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("Card")
        self.role = current_role()
        self._order_ids = []

        self.create_button = QPushButton("Create Order")
        self.create_button.setObjectName("PrimaryButton")
        self.create_button.setVisible(self.role == "admin")
        self.create_button.clicked.connect(self._create_order)

        self.receive_button = QPushButton("Record Receipt")
        self.receive_button.setVisible(
            self.role in {"admin", "manager", "operator"}
        )
        self.receive_button.clicked.connect(self._record_receipt)

        self.close_button = QPushButton("Close Outstanding Quantity")
        self.close_button.setVisible(self.role == "admin")
        self.close_button.clicked.connect(self._close_outstanding)

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)

        buttons = QHBoxLayout()
        buttons.addWidget(self.create_button)
        buttons.addWidget(self.receive_button)
        buttons.addWidget(self.close_button)
        buttons.addStretch()
        buttons.addWidget(refresh_button)

        self.orders_table = QTableWidget(0, 5)
        self.orders_table.setHorizontalHeaderLabels(
            ["PO #", "Supplier", "Reference", "Status", "Created"]
        )
        self.orders_table.horizontalHeader().setStretchLastSection(True)
        self.orders_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.orders_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.orders_table.setAlternatingRowColors(True)
        self.orders_table.itemSelectionChanged.connect(
            self._show_selected_order
        )

        self.details_table = QTableWidget(0, 7)
        self.details_table.setHorizontalHeaderLabels(
            [
                "SKU",
                "Product",
                "Ordered",
                "Received",
                "Closed",
                "Outstanding",
                "Unit cost",
            ]
        )
        self.details_table.horizontalHeader().setStretchLastSection(True)
        self.details_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.details_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.details_table.setAlternatingRowColors(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addLayout(buttons)
        layout.addWidget(QLabel("Purchase Orders"))
        layout.addWidget(self.orders_table, stretch=2)
        layout.addWidget(QLabel("Selected Order — Line Balances"))
        layout.addWidget(self.details_table, stretch=3)

        self.refresh()

    def refresh_products(self):
        self.refresh()

    def refresh(self):
        selected_id = self._selected_order_id()

        with new_session() as session:
            orders = list_purchase_orders(session)

            self.orders_table.blockSignals(True)
            self.orders_table.setRowCount(0)
            self._order_ids = []

            for order in orders:
                row = self.orders_table.rowCount()
                self.orders_table.insertRow(row)

                supplier = (
                    session.get(Supplier, order.supplier_id)
                    if order.supplier_id is not None
                    else None
                )

                created = (
                    format_kigali(order.created_at)
                )

                values = [
                    str(order.id),
                    supplier.name if supplier else "(No supplier)",
                    order.reference or "",
                    order.status.replace("_", " ").title(),
                    created,
                ]

                for column, value in enumerate(values):
                    self.orders_table.setItem(
                        row,
                        column,
                        QTableWidgetItem(value),
                    )

                self._order_ids.append(order.id)

            self.orders_table.blockSignals(False)

        target_row = (
            self._order_ids.index(selected_id)
            if selected_id in self._order_ids
            else (0 if self._order_ids else -1)
        )

        if target_row >= 0:
            self.orders_table.selectRow(target_row)
        else:
            self.details_table.setRowCount(0)

    def _selected_order_id(self):
        row = self.orders_table.currentRow()
        if 0 <= row < len(self._order_ids):
            return self._order_ids[row]
        return None

    def _show_selected_order(self):
        order_id = self._selected_order_id()
        self.details_table.setRowCount(0)

        if order_id is None:
            return

        with new_session() as session:
            balances = get_purchase_order_balances(session, order_id)

            for balance in balances:
                product = session.get(Product, balance.item.product_id)
                row = self.details_table.rowCount()
                self.details_table.insertRow(row)

                values = [
                    product.sku if product else "",
                    product.name if product else "(Missing product)",
                    str(balance.item.ordered_quantity),
                    str(balance.received_quantity),
                    str(balance.closed_quantity),
                    str(balance.outstanding_quantity),
                    str(balance.item.unit_price),
                ]

                for column, value in enumerate(values):
                    self.details_table.setItem(
                        row,
                        column,
                        QTableWidgetItem(value),
                    )

    def _create_order(self):
        dialog = PurchaseOrderCreateDialog(self)
        if not dialog.exec():
            return

        try:
            supplier_id, reference, items, notes = dialog.values()

            with new_session() as session:
                order = create_purchase_order(
                    session,
                    supplier_id=supplier_id,
                    reference=reference,
                    items=items,
                    notes=notes,
                )
                order_id = order.id
                session.commit()

        except (PermissionDeniedError, PurchaseOrderError, ValueError) as exc:
            QMessageBox.warning(self, "Could not create order", str(exc))
            return

        QMessageBox.information(
            self,
            "Purchase order created",
            f"Purchase order #{order_id} was created.",
        )
        self.refresh()

    def _record_receipt(self):
        order_id = self._selected_order_id()
        if order_id is None:
            QMessageBox.information(
                self,
                "No order selected",
                "Select a purchase order first.",
            )
            return

        with new_session() as session:
            balances = get_purchase_order_balances(session, order_id)

        outstanding = [
            balance for balance in balances
            if balance.outstanding_quantity > 0
        ]

        if not outstanding:
            QMessageBox.information(
                self,
                "Nothing outstanding",
                "This order has no outstanding quantities to receive.",
            )
            return

        dialog = PurchaseOrderActionDialog(
            outstanding,
            action="receive",
            parent=self,
        )

        if not dialog.exec():
            return

        try:
            items, reference, notes = dialog.values()

            with new_session() as session:
                record_purchase_order_receipt(
                    session,
                    purchase_order_id=order_id,
                    items=items,
                    reference=reference,
                    notes=notes,
                )
                session.commit()

        except (PermissionDeniedError, PurchaseOrderError, ValueError) as exc:
            QMessageBox.warning(self, "Receipt not saved", str(exc))
            return

        QMessageBox.information(
            self,
            "Receipt recorded",
            "The received quantities have been added to stock.",
        )
        self.refresh()

    def _close_outstanding(self):
        if self.role != "admin":
            QMessageBox.warning(
                self,
                "Not allowed",
                "Only an administrator can close outstanding quantities.",
            )
            return

        order_id = self._selected_order_id()
        if order_id is None:
            QMessageBox.information(
                self,
                "No order selected",
                "Select a purchase order first.",
            )
            return

        with new_session() as session:
            balances = get_purchase_order_balances(session, order_id)

        outstanding = [
            balance for balance in balances
            if balance.outstanding_quantity > 0
        ]

        if not outstanding:
            QMessageBox.information(
                self,
                "Nothing outstanding",
                "This order has no outstanding quantities to close.",
            )
            return

        dialog = PurchaseOrderActionDialog(
            outstanding,
            action="close",
            parent=self,
        )

        if not dialog.exec():
            return

        items, notes = dialog.values()

        confirmation = QMessageBox.question(
            self,
            "Confirm closure",
            "Close the selected outstanding quantities?\n\n"
            "Closed quantities will NOT be added to stock and cannot "
            "be received later.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if confirmation != QMessageBox.Yes:
            return

        try:
            with new_session() as session:
                close_purchase_order_outstanding(
                    session,
                    purchase_order_id=order_id,
                    items=items,
                    notes=notes,
                )
                session.commit()

        except (PermissionDeniedError, PurchaseOrderError, ValueError) as exc:
            QMessageBox.warning(self, "Closure not saved", str(exc))
            return

        QMessageBox.information(
            self,
            "Outstanding quantities closed",
            "The selected quantities have been closed. Stock was not changed.",
        )
        self.refresh()
