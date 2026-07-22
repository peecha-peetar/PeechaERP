"""ردِ حسابرسی — معادلِ Qt برایِ audit_log.py/.kv در Kivy.

فقط‌خواندنی (طبقِ ماهیتِ تغییرناپذیرِ خودِ جدول)."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import audit as audit_service

_COLUMNS = ["تاریخ/ساعت", "کاربر", "عملیات", "شناسه", "نوعِ موجودیت"]


class AuditLogScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[audit_service.ActivityLogRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("ردِ حسابرسی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel("رویدادهای ایجاد/ویرایش/حذفِ اطلاعاتِ کسب‌وکاری — فقط‌خواندنی و تغییرناپذیر.")
        hint.setObjectName("sectionHint")
        layout.addWidget(hint)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("نوعِ موجودیت"))
        self.entity_type_combo = QComboBox()
        self.entity_type_combo.currentIndexChanged.connect(self._apply_filter)
        filter_row.addWidget(self.entity_type_combo)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("sectionHint")
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self._show_changes)
        layout.addWidget(self.table, stretch=1)

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        entity_types = audit_service.list_entity_types()
        self.entity_type_combo.blockSignals(True)
        self.entity_type_combo.clear()
        self.entity_type_combo.addItem("همه‌ی انواع", None)
        for et in entity_types:
            self.entity_type_combo.addItem(et, et)
        self.entity_type_combo.blockSignals(False)
        self._apply_filter()

    def _apply_filter(self) -> None:
        company_id = self._company_id()
        entity_type = self.entity_type_combo.currentData()
        self._rows = audit_service.list_activity_log(company_id, entity_type)
        self.status_label.setText("هنوز رویدادی ثبت نشده است." if not self._rows else f"{len(self._rows)} رویداد یافت شد.")
        self.table.setRowCount(len(self._rows))
        for row_index, r in enumerate(self._rows):
            values = [
                r.created_at.strftime("%Y-%m-%d %H:%M"),
                r.user_full_name or "سیستم",
                r.action,
                str(r.entity_id),
                r.entity_type,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, r.changes)
                self.table.setItem(row_index, col_index, item)

    def _show_changes(self, row: int, _column: int) -> None:
        from PySide6.QtWidgets import QMessageBox  # noqa: PLC0415

        changes = self.table.item(row, 0).data(Qt.UserRole)
        QMessageBox.information(self, "جزئیاتِ تغییرات", json.dumps(changes, ensure_ascii=False, indent=2, default=str))
