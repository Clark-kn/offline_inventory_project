from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.data.session import new_session
from app.utils.timezone import format_kigali
from app.services.audit import recent_audit_log
from app.services.audit_display import (
    audit_action_label,
    format_audit_details,
    format_audit_summary,
)


class AuditLogTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._entry_details = []

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)

        btn_row = QHBoxLayout()
        btn_row.addWidget(QLabel("Activity history"))
        btn_row.addStretch()
        btn_row.addWidget(refresh_btn)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Date & Time", "User", "Activity", "Summary"]
        )
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)

        self.table.itemSelectionChanged.connect(self.show_selected_details)

        detail_group = QGroupBox("Activity details")
        detail_layout = QVBoxLayout(detail_group)

        self.details_hint = QLabel(
            "Select an activity above to see more information."
        )
        self.details_hint.setWordWrap(True)

        self.details_text = QPlainTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setPlaceholderText(
            "Details for the selected activity will appear here."
        )
        self.details_text.setMinimumHeight(125)
        self.details_text.setStyleSheet(
            """
            QPlainTextEdit {
                background-color: #ffffff;
                color: #263449;
                border: 1px solid #d7deea;
                border-radius: 6px;
                padding: 10px;
                selection-background-color: #dce6ff;
                selection-color: #172033;
            }
            """
        )

        detail_layout.addWidget(self.details_hint)
        detail_layout.addWidget(self.details_text)

        time_note = QLabel("All dates and times are shown in Kigali time.")
        time_note.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addLayout(btn_row)
        layout.addWidget(self.table, 3)
        layout.addWidget(detail_group, 1)
        layout.addWidget(time_note)

        self.refresh()

    def refresh(self):
        with new_session() as session:
            rows = recent_audit_log(session, limit=200)

            entries = []
            for log, user in rows:
                entries.append({
                    "date": format_kigali(log.created_at, "%d %b %Y, %H:%M"),
                    "user": user.username if user else "System",
                    "action": log.action,
                    "activity": audit_action_label(log.action),
                    "summary": format_audit_summary(log.action, log.details),
                    "details": format_audit_details(log.action, log.details),
                })

        self._entry_details = entries
        self.table.setRowCount(len(entries))

        for row_index, entry in enumerate(entries):
            values = (
                entry["date"],
                entry["user"],
                entry["activity"],
                entry["summary"],
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_index, column, item)

        self.details_text.clear()

        if entries:
            self.table.selectRow(0)
        else:
            self.details_hint.setText("No activity has been recorded yet.")

    def show_selected_details(self):
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            self.details_hint.setText(
                "Select an activity above to see more information."
            )
            self.details_text.clear()
            return

        row = selected[0].row()
        if row < 0 or row >= len(self._entry_details):
            return

        entry = self._entry_details[row]
        self.details_hint.setText(
            f"{entry['activity']} — {entry['date']} — User: {entry['user']}"
        )
        self.details_text.setPlainText(entry["details"])
