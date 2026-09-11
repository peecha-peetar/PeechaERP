"""پخشِ سرد/گرم -- R130: بارگیریِ خودرو (Pick List) از دسکتاپ. طبقِ
سندِ کاربر («سیستم پیشنهاد بدهد چقدر کارتن نیاز داری، چقدر موجودیِ
خودرو داری، چقدر کسری داری»): هنگامِ ساختِ بارگیری، موجودیِ لحظه‌ای/
کسریِ هر ردیف محاسبه می‌شود؛ تاییدِ راننده سندِ TRANSFERِ واقعی می‌سازد
(services/vehicle_loading.py، R129)."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
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
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import vehicle_loading as vehicle_loading_service
from peecha.ui.widgets import JalaliDateEdit, build_action_footer, wrap_scrollable

_LIST_COLUMNS = ["تاریخ", "خودرو", "انبارِ مبدا", "وضعیت"]
_LINE_COLUMNS = ["کالا", "واحد", "مقدارِ برنامه‌ریزی‌شده", "موجودیِ لحظهٔ برنامه‌ریزی", "کسری"]
_STATUS_LABELS = {"DRAFT": "پیش‌نویس", "CONFIRMED": "تاییدشده"}


def _fmt_qty(value: decimal.Decimal) -> str:
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


class VehicleLoadingScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._loadings: list[vehicle_loading_service.VehicleLoadingRow] = []
        self._items: list = []
        self._warehouses_by_id: dict[int, locations_service.WarehouseRow] = {}
        self._pending_lines: list[tuple[int, int, str, str]] = []  # item_id, uom_id, item_label, uom_label
        self._editing_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=2)
        outer.addWidget(self._build_form_panel(), stretch=3)

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        title = QLabel("بارگیریِ خودرو")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        new_button = QPushButton("➕")
        new_button.setObjectName("primaryIconButton")
        new_button.setFixedWidth(48)
        new_button.setToolTip("بارگیریِ جدید")
        new_button.clicked.connect(self._reset_form)
        layout.addWidget(new_button, alignment=Qt.AlignLeft)

        self.table = QTableWidget(0, len(_LIST_COLUMNS))
        self.table.setHorizontalHeaderLabels(_LIST_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)
        return wrap_scrollable(panel)

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        self.form_title = QLabel("بارگیریِ جدید")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("خودرو"))
        self.vehicle_combo = QComboBox()
        header_row.addWidget(self.vehicle_combo, stretch=1)
        header_row.addWidget(QLabel("انبارِ مبدا"))
        self.source_warehouse_combo = QComboBox()
        header_row.addWidget(self.source_warehouse_combo, stretch=1)
        header_row.addWidget(QLabel("تاریخ"))
        self.date_field = JalaliDateEdit()
        header_row.addWidget(self.date_field)
        layout.addLayout(header_row)

        add_line_row = QHBoxLayout()
        self.item_combo = QComboBox()
        add_line_row.addWidget(self.item_combo, stretch=1)
        self.quantity_field = QDoubleSpinBox()
        self.quantity_field.setRange(0.001, 999_999)
        self.quantity_field.setDecimals(3)
        add_line_row.addWidget(self.quantity_field)
        self.add_line_button = QPushButton("➕")
        self.add_line_button.setObjectName("iconButton")
        self.add_line_button.setFixedWidth(44)
        self.add_line_button.setToolTip("افزودنِ ردیف")
        self.add_line_button.clicked.connect(self._add_pending_line)
        add_line_row.addWidget(self.add_line_button)
        layout.addLayout(add_line_row)

        self.lines_table = QTableWidget(0, len(_LINE_COLUMNS))
        self.lines_table.setHorizontalHeaderLabels(_LINE_COLUMNS)
        self.lines_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lines_table.verticalHeader().setVisible(False)
        self.lines_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.lines_table)

        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.create_button = QPushButton("💾")
        self.create_button.setObjectName("primaryIconButton")
        self.create_button.setFixedWidth(48)
        self.create_button.setToolTip("ثبتِ بارگیری")
        self.create_button.clicked.connect(self._create)

        self.confirm_button = QPushButton("🚚 تاییدِ راننده")
        self.confirm_button.setObjectName("primaryIconButton")
        self.confirm_button.clicked.connect(self._confirm)
        self.confirm_button.setVisible(False)

        cancel_button = QPushButton("↩️")
        cancel_button.setObjectName("iconButton")
        cancel_button.setFixedWidth(44)
        cancel_button.setToolTip("انصراف")
        cancel_button.clicked.connect(self._reset_form)

        layout.addWidget(build_action_footer([self.create_button, self.confirm_button, cancel_button]))
        return wrap_scrollable(panel)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        self._reset_form()
        company_id = self._company_id()
        if company_id is None:
            return
        warehouses = locations_service.list_warehouses(company_id)
        self._warehouses_by_id = {w.warehouse_id: w for w in warehouses}
        vehicles = locations_service.list_vehicles(company_id)

        self.vehicle_combo.clear()
        for v in vehicles:
            self.vehicle_combo.addItem(f"{v.code} — {v.name}", v.warehouse_id)

        self.source_warehouse_combo.clear()
        for w in warehouses:
            if w.fields.warehouse_type_code != "VEHICLE":
                self.source_warehouse_combo.addItem(f"{w.code} — {w.name}", w.warehouse_id)

        self._items = catalog_service.list_items(company_id, active_only=True)
        self.item_combo.clear()
        for it in self._items:
            self.item_combo.addItem(f"{it.code} — {it.name or ''}", it.item_id)

        self._loadings = vehicle_loading_service.list_vehicle_loadings(company_id)
        self.table.setRowCount(len(self._loadings))
        for row_index, loading in enumerate(self._loadings):
            vehicle = self._warehouses_by_id.get(loading.vehicle_warehouse_id)
            source = self._warehouses_by_id.get(loading.source_warehouse_id)
            values = [
                loading.loading_date.isoformat(),
                vehicle.name if vehicle else str(loading.vehicle_warehouse_id),
                source.name if source else str(loading.source_warehouse_id),
                _STATUS_LABELS.get(loading.status_code, loading.status_code),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, loading.vehicle_loading_id)
                self.table.setItem(row_index, col_index, item)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        loading_id = self.table.item(row, 0).data(Qt.UserRole)
        loading = next((r for r in self._loadings if r.vehicle_loading_id == loading_id), None)
        if loading is not None:
            self._load_into_form(loading)

    def _item_uom_label(self, item_id: int, uom_id: int) -> tuple[str, str]:
        item = next((it for it in self._items if it.item_id == item_id), None)
        item_label = f"{item.code} — {item.name or ''}" if item else str(item_id)
        uom_label = item.base_uom_code if item and item.base_uom_id == uom_id else str(uom_id)
        return item_label, uom_label

    def _load_into_form(self, loading: vehicle_loading_service.VehicleLoadingRow) -> None:
        self._editing_id = loading.vehicle_loading_id
        self.form_title.setText(f"بارگیریِ {loading.loading_date.isoformat()}")
        self.status_label.setText("")
        index = self.vehicle_combo.findData(loading.vehicle_warehouse_id)
        self.vehicle_combo.setCurrentIndex(max(0, index))
        self.vehicle_combo.setEnabled(False)
        index = self.source_warehouse_combo.findData(loading.source_warehouse_id)
        self.source_warehouse_combo.setCurrentIndex(max(0, index))
        self.source_warehouse_combo.setEnabled(False)
        self.date_field.setDate(loading.loading_date)
        self.date_field.setEnabled(False)
        self.item_combo.setEnabled(False)
        self.quantity_field.setEnabled(False)
        self.add_line_button.setEnabled(False)

        self.lines_table.setRowCount(len(loading.lines))
        for row_index, line in enumerate(loading.lines):
            item_label, uom_label = self._item_uom_label(line.item_id, line.uom_id)
            values = [
                item_label, uom_label, _fmt_qty(line.planned_quantity),
                _fmt_qty(line.available_quantity_at_planning) if line.available_quantity_at_planning is not None else "—",
                _fmt_qty(line.shortage_quantity),
            ]
            for col_index, value in enumerate(values):
                self.lines_table.setItem(row_index, col_index, QTableWidgetItem(value))

        if loading.status_code == "DRAFT":
            self.info_label.setText("این بارگیری هنوز تایید نشده -- موجودیِ خودرو پسِ تاییدِ راننده به‌روز می‌شود.")
            self.confirm_button.setVisible(True)
            self.create_button.setVisible(False)
        else:
            self.info_label.setText(f"تاییدشده -- سندِ انتقالِ شمارهٔ {loading.stock_document_id}")
            self.confirm_button.setVisible(False)
            self.create_button.setVisible(False)

    def _reset_form(self) -> None:
        self._editing_id = None
        self._pending_lines = []
        self.form_title.setText("بارگیریِ جدید")
        self.status_label.setText("")
        self.info_label.setText("")
        self.vehicle_combo.setEnabled(True)
        self.vehicle_combo.setCurrentIndex(0)
        self.source_warehouse_combo.setEnabled(True)
        self.source_warehouse_combo.setCurrentIndex(0)
        self.date_field.setEnabled(True)
        import datetime
        self.date_field.setDate(datetime.date.today())
        self.item_combo.setEnabled(True)
        self.quantity_field.setEnabled(True)
        self.quantity_field.setValue(0.001)
        self.add_line_button.setEnabled(True)
        self.lines_table.setRowCount(0)
        self.create_button.setVisible(True)
        self.confirm_button.setVisible(False)
        self.table.clearSelection()

    def _add_pending_line(self) -> None:
        item_id = self.item_combo.currentData()
        if item_id is None or self.quantity_field.value() <= 0:
            return
        item = next((it for it in self._items if it.item_id == item_id), None)
        if item is None:
            return
        self._pending_lines.append((item_id, item.base_uom_id, f"{item.code} — {item.name or ''}", item.base_uom_code))
        row = self.lines_table.rowCount()
        self.lines_table.setRowCount(row + 1)
        self.lines_table.setItem(row, 0, QTableWidgetItem(f"{item.code} — {item.name or ''}"))
        self.lines_table.setItem(row, 1, QTableWidgetItem(item.base_uom_code))
        self.lines_table.setItem(row, 2, QTableWidgetItem(f"{self.quantity_field.value():g}"))
        self.lines_table.setItem(row, 3, QTableWidgetItem("—"))
        self.lines_table.setItem(row, 4, QTableWidgetItem("—"))
        self.quantity_field.setValue(0.001)

    def _create(self) -> None:
        import decimal

        company_id = self._company_id()
        vehicle_id = self.vehicle_combo.currentData()
        source_id = self.source_warehouse_combo.currentData()
        if company_id is None or vehicle_id is None or source_id is None:
            self.status_label.setText("خودرو و انبارِ مبدا را انتخاب کنید.")
            return
        if not self._pending_lines:
            self.status_label.setText("حداقل یک ردیف اضافه کنید.")
            return
        lines = [
            vehicle_loading_service.VehicleLoadingLineFields(item_id, uom_id, decimal.Decimal(str(self.lines_table.item(row, 2).text())))
            for row, (item_id, uom_id, _item_label, _uom_label) in enumerate(self._pending_lines)
        ]
        try:
            vehicle_loading_service.create_vehicle_loading(
                company_id, app_session.current_user.user_id, vehicle_id, source_id, self.date_field.date(), lines,
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()

    def _confirm(self) -> None:
        if self._editing_id is None:
            return
        confirm = QMessageBox.question(
            self, "تاییدِ بارگیری", "بعدِ تایید، موجودیِ خودرو واقعاً به‌روز می‌شود. ادامه می‌دهید؟", QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        company_id = self._company_id()
        try:
            vehicle_loading_service.confirm_vehicle_loading(self._editing_id, company_id, app_session.current_user.user_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
