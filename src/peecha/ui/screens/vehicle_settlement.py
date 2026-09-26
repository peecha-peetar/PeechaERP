"""تسویهٔ پایانِ روزِ خودرو (فازِ ۲، بخشِ ۲ از پخشِ گرم) -- طبقِ درخواستِ
صریحِ کاربر: تعیینِ نقشِ مسئولِ تسویه + دو گیتِ تاییدِ مستقل (انبار،
حسابداری) پیش از قطعی‌شدنِ برگشتِ کالا."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.numerals import format_jalali_date
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import vehicle_settlement as settlement_service
from peecha.services import vehicle_team as vehicle_team_service
from peecha.ui.widgets import FieldHelpMixin

_ROLE_LABELS = {"DRIVER": "راننده", "VISITOR": "ویزیتور", "DISTRIBUTOR": "موزع"}
_STATUS_LABELS = {
    "SUBMITTED": "منتظرِ تاییدِ انبار", "WAREHOUSE_APPROVED": "منتظرِ تاییدِ حسابداری",
    "ACCOUNTING_APPROVED": "قطعی‌شده",
}
_LIST_COLUMNS = ["تاریخ", "ساعتِ ثبت", "خودرو", "وضعیت", "مبلغِ فاکتورشده", "نقدِ اعلامی"]


def _fmt_qty(value: decimal.Decimal) -> str:
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


class VehicleSettlementScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._settlements: list[settlement_service.SettlementRow] = []
        self._items_by_id: dict = {}
        self._warehouses_by_id: dict[int, locations_service.WarehouseRow] = {}
        self._selected: settlement_service.SettlementRow | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        title = QLabel("تسویهٔ خودرو")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        role_row = QHBoxLayout()
        role_row.addWidget(QLabel("نقشِ مسئولِ ثبتِ تسویهٔ آخرِ روز"))
        self.role_combo = QComboBox()
        for code, label in _ROLE_LABELS.items():
            self.role_combo.addItem(label, code)
        role_row.addWidget(self.role_combo)
        save_role_button = QPushButton("ذخیره")
        save_role_button.clicked.connect(self._save_role)
        role_row.addWidget(save_role_button)
        role_row.addStretch(1)
        layout.addLayout(role_row)

        self.table = QTableWidget(0, len(_LIST_COLUMNS))
        self.table.setHorizontalHeaderLabels(_LIST_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)

        self.lines_table = QTableWidget(0, 5)
        self.lines_table.setHorizontalHeaderLabels(["کالا", "بارگیری‌شده", "فروخته‌شده", "برگشتی", "کسری/اضافی"])
        self.lines_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lines_table.verticalHeader().setVisible(False)
        self.lines_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.lines_table)

        actions_row = QHBoxLayout()
        self.approve_warehouse_button = QPushButton("تاییدِ انبار")
        self.approve_warehouse_button.clicked.connect(self._approve_warehouse)
        actions_row.addWidget(self.approve_warehouse_button)
        self.approve_accounting_button = QPushButton("تاییدِ حسابداری")
        self.approve_accounting_button.clicked.connect(self._approve_accounting)
        actions_row.addWidget(self.approve_accounting_button)
        actions_row.addStretch(1)
        layout.addLayout(actions_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self.status_label.setText("")

        current_role = settlement_service.get_settlement_role(company_id)
        if current_role is not None:
            index = self.role_combo.findData(current_role)
            self.role_combo.setCurrentIndex(index if index >= 0 else 0)

        self._items_by_id = {i.item_id: i for i in catalog_service.list_items(company_id)}
        self._warehouses_by_id = {w.warehouse_id: w for w in locations_service.list_warehouses(company_id)}

        self._settlements = settlement_service.list_settlements(company_id)
        self.table.setRowCount(len(self._settlements))
        for row, s in enumerate(self._settlements):
            vehicle = self._warehouses_by_id.get(s.vehicle_warehouse_id)
            values = [
                format_jalali_date(s.settlement_date),
                s.submitted_at.strftime("%H:%M"),
                vehicle.name if vehicle else str(s.vehicle_warehouse_id),
                _STATUS_LABELS.get(s.status_code, s.status_code),
                f"{s.invoiced_amount:,.0f}",
                f"{s.declared_cash_amount:,.0f}",
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))
        self.lines_table.setRowCount(0)
        self._update_action_buttons(None)

    def _on_row_clicked(self, row: int, _col: int) -> None:
        if row < 0 or row >= len(self._settlements):
            return
        s = self._settlements[row]
        self.lines_table.setRowCount(len(s.lines))
        for i, line in enumerate(s.lines):
            item = self._items_by_id.get(line.item_id)
            values = [
                item.name if item else str(line.item_id),
                _fmt_qty(line.loaded_quantity), _fmt_qty(line.sold_quantity), _fmt_qty(line.returned_quantity),
                _fmt_qty(line.shortage_or_surplus),
            ]
            for col, value in enumerate(values):
                self.lines_table.setItem(i, col, QTableWidgetItem(value))
        self._update_action_buttons(s)

    def _update_action_buttons(self, s: settlement_service.SettlementRow | None) -> None:
        self._selected = s
        self.approve_warehouse_button.setEnabled(s is not None and s.status_code == "SUBMITTED")
        self.approve_accounting_button.setEnabled(s is not None and s.status_code == "WAREHOUSE_APPROVED")

    def _save_role(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        settlement_service.set_settlement_role(company_id, self.role_combo.currentData())
        self.status_label.setText("نقشِ مسئولِ تسویه ذخیره شد.")

    def _approve_warehouse(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected is None:
            return
        try:
            settlement_service.approve_warehouse(self._selected.vehicle_settlement_id, company_id, app_session.current_user.user_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()

    def _approve_accounting(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected is None:
            return
        if QMessageBox.question(
            self, "تاییدِ حسابداری",
            "با تاییدِ نهایی، سندِ برگشتِ کالا ساخته و پست می‌شود. ادامه می‌دهید؟",
        ) != QMessageBox.Yes:
            return
        try:
            settlement_service.approve_accounting(self._selected.vehicle_settlement_id, company_id, app_session.current_user.user_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
