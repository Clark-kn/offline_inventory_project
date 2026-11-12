from datetime import date
from sqlalchemy import select

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.data.models import DamagedGood, Supplier, Unit, User
from app.data.session import new_session
from app.services.damaged_goods import (
    DamagedGoodsError,
    delete_damaged_goods,
    record_damaged_goods,
)
from app.services.master_data import list_reference, list_suppliers
from app.utils.timezone import format_kigali
from app.security.session_context import get_current_user


class DamagedGoodsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")

        self.unit_combo = QComboBox()
        self.unit_combo.setObjectName('DamagedGoodsUnitCombo')
        self.supplier_combo = QComboBox()
        self.supplier_combo.setObjectName('DamagedGoodsSupplierCombo')

        self.quantity_edit = QLineEdit()
        self.quantity_edit.setPlaceholderText("Enter damaged quantity")

        self.date_edit = QDateEdit()
        self.date_edit.setObjectName('DamagedGoodsDateEdit')
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd/MM/yyyy")
        self.date_edit.setDate(QDate.currentDate())
        calendar = self.date_edit.calendarWidget()
        calendar.setObjectName('DamagedGoodsCalendar')
        calendar.setGridVisible(True)

        form = QFormLayout()
        form.addRow("Unit", self.unit_combo)
        form.addRow("Quantity", self.quantity_edit)
        form.addRow("Supplier", self.supplier_combo)
        form.addRow("Date brought", self.date_edit)

        self.record_button = QPushButton("Record Damaged Goods")
        self.record_button.clicked.connect(self.record)
        self.delete_button = QPushButton("Delete Selected Record")
        self.delete_button.clicked.connect(self.delete_selected)
        current_user = get_current_user()
        self.delete_button.setVisible(
            current_user is not None and current_user.role == "admin"
        )

        form_layout = QHBoxLayout()
        form_layout.addLayout(form, 1)
        form_layout.addWidget(self.record_button)

        self.status_label = QLabel(
            "These records do not change stock or appear in the Stock Ledger."
        )
        self.status_label.setWordWrap(True)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Date Brought",
            "Unit",
            "Quantity",
            "Supplier",
            "Recorded By",
            "Recorded At",
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        layout.addLayout(form_layout)
        layout.addWidget(self.status_label)
        layout.addWidget(self.delete_button, alignment=Qt.AlignRight)
        layout.addWidget(self.table)

        self.refresh()

    def refresh_references(self):
        selected_unit_id = self.unit_combo.currentData()
        selected_supplier_id = self.supplier_combo.currentData()

        with new_session() as session:
            units = list_reference(session, Unit)
            suppliers = list_suppliers(session)

        self.unit_combo.clear()
        for unit in units:
            self.unit_combo.addItem(unit.name, unit.id)

        if selected_unit_id is not None:
            index = self.unit_combo.findData(selected_unit_id)
            if index >= 0:
                self.unit_combo.setCurrentIndex(index)

        self.supplier_combo.clear()
        for supplier in suppliers:
            self.supplier_combo.addItem(supplier.name, supplier.id)

        if selected_supplier_id is not None:
            index = self.supplier_combo.findData(selected_supplier_id)
            if index >= 0:
                self.supplier_combo.setCurrentIndex(index)

        self.record_button.setEnabled(
            self.unit_combo.count() > 0 and self.supplier_combo.count() > 0
        )

    def record(self):
        unit_id = self.unit_combo.currentData()
        supplier_id = self.supplier_combo.currentData()

        if unit_id is None or supplier_id is None:
            QMessageBox.warning(
                self,
                "Missing reference",
                "An active Unit and Supplier are required. Add them first.",
            )
            return

        quantity = self.quantity_edit.text().strip()
        if not quantity:
            QMessageBox.warning(
                self,
                "Missing quantity",
                "Enter the damaged quantity.",
            )
            return

        qdate = self.date_edit.date()
        brought_date = date(qdate.year(), qdate.month(), qdate.day())

        try:
            with new_session() as session:
                record_damaged_goods(
                    session,
                    unit_id=unit_id,
                    quantity=quantity,
                    supplier_id=supplier_id,
                    date_brought=brought_date,
                )
                session.commit()
        except DamagedGoodsError as exc:
            QMessageBox.warning(self, "Cannot record damaged goods", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Error",
                f"Could not save the damaged-goods record:\n{exc}",
            )
            return

        self.quantity_edit.clear()
        self.refresh()
        QMessageBox.information(
            self,
            "Saved",
            "Damaged-goods record saved. Stock was not changed.",
        )

    def delete_selected(self):
        if not self.delete_button.isVisible():
            QMessageBox.warning(
                self,
                "Permission denied",
                "Only an administrator can delete damaged-goods records.",
            )
            return

        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Select a record",
                "Select the damaged-goods record you want to delete.",
            )
            return

        first_item = self.table.item(row, 0)
        record_id = first_item.data(Qt.UserRole) if first_item else None
        if record_id is None:
            QMessageBox.warning(
                self,
                "Cannot delete",
                "The selected record could not be identified. Refresh and try again.",
            )
            return

        answer = QMessageBox.question(
            self,
            "Confirm deletion",
            "Permanently delete this damaged-goods record?\\n"
            "This will also update the damaged-goods totals. "
            "The deletion will be recorded in the audit log.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            with new_session() as session:
                delete_damaged_goods(session, record_id)
                session.commit()
        except DamagedGoodsError as exc:
            QMessageBox.warning(self, "Cannot delete record", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Deletion failed",
                f"Could not delete the damaged-goods record:\\n{exc}",
            )
            return

        self.refresh()
        QMessageBox.information(
            self,
            "Deleted",
            "The damaged-goods record was deleted and the action was audited.",
        )

    def refresh(self):
        self.refresh_references()
        self.table.setRowCount(0)

        with new_session() as session:
            rows = session.execute(
                select(DamagedGood, User.username)
                .join(User, User.id == DamagedGood.recorded_by_user_id)
                .order_by(
                    DamagedGood.date_brought.desc(),
                    DamagedGood.recorded_at.desc(),
                    DamagedGood.id.desc(),
                )
            ).all()

            self.table.setRowCount(len(rows))

            for row_index, (record, username) in enumerate(rows):
                values = [
                    record.date_brought.strftime("%d/%m/%Y"),
                    record.unit_name,
                    str(record.quantity),
                    record.supplier_name,
                    username,
                    format_kigali(record.recorded_at),
                ]

                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 0:
                        item.setData(Qt.UserRole, record.id)
                    self.table.setItem(row_index, column, item)
