"""انبارگردانی با واحد شمارش (R225): کاربر هر کالا را با واحد دلخواه
می‌شمارد (مثلاً ۱۰ کارتن)، سیستم به واحد پایه تبدیل و با موجودی دفتری
مقایسه می‌کند؛ «ثبت نهایی» اختلاف را با سند اصلاح موجودی ثبت می‌کند.
همهٔ منطق در services/stock_count.py و services/unit_conversion.py است."""

from __future__ import annotations

import decimal

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

from peecha import decimals, numerals, session as app_session
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import stock_count as count_service
from peecha.ui import theme
from peecha.ui.screens.journal_entry import _AmountField, _make_searchable_combo

_COLUMNS = ["کالا", "واحد شمارش", "مقدار شمارش", "معادل به واحد پایه", "موجودی دفتری", "اختلاف", "بچ/سریال"]


class StockCountScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._items: list = []
        self._uom_names: dict[int, str] = {}
        self._uom_factors: dict[int, decimal.Decimal] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)
        title = QLabel("انبارگردانی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        hint = QLabel(
            "هر کالا را با واحد دلخواه (عدد/بسته/کارتن/...) بشمارید؛ مقدار به واحد پایه تبدیل و با موجودی دفتری "
            "مقایسه می‌شود. «ثبت نهایی» اختلاف را با سند اصلاح موجودی (مازاد/کسری) ثبت می‌کند."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        session_row = QHBoxLayout()
        session_row.addWidget(QLabel("انبار"))
        self.warehouse_combo = QComboBox()
        session_row.addWidget(self.warehouse_combo, stretch=1)
        new_button = QPushButton("➕ انبارگردانی جدید")
        new_button.setObjectName("primaryButton")
        new_button.clicked.connect(self._new_session)
        session_row.addWidget(new_button)
        session_row.addWidget(QLabel("جلسه"))
        self.session_combo = QComboBox()
        self.session_combo.currentIndexChanged.connect(lambda _i=0: self._load_session())
        session_row.addWidget(self.session_combo, stretch=1)
        layout.addLayout(session_row)

        entry_row = QHBoxLayout()
        self.item_combo = _make_searchable_combo([])
        self.item_combo.currentIndexChanged.connect(self._on_item_changed)
        entry_row.addWidget(self.item_combo, stretch=3)
        self.uom_combo = QComboBox()
        self.uom_combo.currentIndexChanged.connect(self._apply_decimals)
        entry_row.addWidget(self.uom_combo, stretch=1)
        self.quantity_field = _AmountField()
        self.quantity_field.setDecimals(3)
        entry_row.addWidget(self.quantity_field, stretch=1)
        self.record_button = QPushButton("ثبت شمارش")
        self.record_button.clicked.connect(self._record)
        entry_row.addWidget(self.record_button)
        # R228: شمارش به تفکیکِ بچ/سریال (موجودیِ دفتریِ هر بچ پیش‌پر می‌شود)
        self.track_count_button = QPushButton("🏷 شمارش به تفکیک بچ/سریال")
        self.track_count_button.setEnabled(False)
        self.track_count_button.clicked.connect(lambda: self._open_tracking_count(self.item_combo.currentData()))
        entry_row.addWidget(self.track_count_button)
        layout.addLayout(entry_row)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

        self.finalize_button = QPushButton("✅ ثبت نهایی و صدور سند اختلاف")
        self.finalize_button.setObjectName("primaryButton")
        self.finalize_button.clicked.connect(self._finalize)
        layout.addWidget(self.finalize_button)
        # R295: نوار گردش کار تایید انبارگردانی (فقط وقتی فرایندی فعال است)
        from peecha.ui.screens.workflow_bar import WorkflowBar

        self.workflow_bar = WorkflowBar("INVENTORY_COUNT")
        self.workflow_bar.on_started = self._load_session
        layout.addWidget(self.workflow_bar)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self.warehouse_combo.clear()
        for w in locations_service.list_warehouses(company_id, active_only=True):
            self.warehouse_combo.addItem(f"{w.code} — {w.name}", w.warehouse_id)
        self._items = [it for it in catalog_service.list_items(company_id, active_only=True, transactable_only=True) if it.is_stock_tracked]
        self._uom_names = {u.uom_id: u.name for u in catalog_service.list_uoms(company_id)}
        self._uom_decimals = {u.uom_id: (u.decimal_places if u.allow_decimal else 0) for u in catalog_service.list_uoms(company_id)}
        self.item_combo.blockSignals(True)
        self.item_combo.clear()
        for it in self._items:
            self.item_combo.addItem(f"{it.code} — {it.name or ''}", it.item_id)
        self.item_combo.setCurrentIndex(-1)
        self.item_combo.blockSignals(False)
        self._reload_sessions()

    def open_session(self, session_id: int) -> None:
        """بازکردن یک انبارگردانی مشخص (از کارتابل گردش کار)."""
        self._reload_sessions(session_id)

    def _reload_sessions(self, select_session_id: int | None = None) -> None:
        company_id = self._company_id()
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        status_labels = {"COUNTING": "در حال شمارش", "POSTED": "ثبت‌شده"}
        for s in count_service.list_count_sessions(company_id):
            self.session_combo.addItem(f"{s.session_code} ({status_labels.get(s.status_code, s.status_code)})", s.session_id)
        if select_session_id is not None:
            self.session_combo.setCurrentIndex(max(0, self.session_combo.findData(select_session_id)))
        self.session_combo.blockSignals(False)
        self._load_session()

    def _new_session(self) -> None:
        company_id = self._company_id()
        warehouse_id = self.warehouse_combo.currentData()
        if company_id is None or warehouse_id is None:
            return
        try:
            session_id = count_service.create_count_session(company_id, warehouse_id, app_session.current_user.user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._reload_sessions(session_id)

    def _on_item_changed(self) -> None:
        item_id = self.item_combo.currentData()
        self.uom_combo.clear()
        self._uom_factors = {}
        item = next((it for it in self._items if it.item_id == item_id), None)
        self.track_count_button.setEnabled(item is not None and (item.track_batch or item.track_serial))
        if item_id is None:
            return
        for option in catalog_service.list_item_uom_options(item_id, purpose="INVENTORY"):
            label = option.name if option.is_base else f"{option.name} (×{numerals.to_persian_digits(format(option.factor.normalize(), 'f'))})"
            self.uom_combo.addItem(label, option.uom_id)
            self._uom_factors[option.uom_id] = option.factor
        self._apply_decimals()

    def _apply_decimals(self) -> None:
        uom_id = self.uom_combo.currentData()
        self.quantity_field.setDecimals(getattr(self, "_uom_decimals", {}).get(uom_id, 3) if uom_id is not None else 3)

    def _record(self) -> None:
        company_id = self._company_id()
        session_id = self.session_combo.currentData()
        item_id = self.item_combo.currentData()
        uom_id = self.uom_combo.currentData()
        if company_id is None or session_id is None or item_id is None or uom_id is None:
            self.status_label.setText("جلسهٔ انبارگردانی، کالا و واحد را انتخاب کنید.")
            return
        try:
            count_service.record_count(session_id, company_id, item_id, uom_id, decimal.Decimal(str(self.quantity_field.value())))
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.quantity_field.setValue(0)
        self._load_session()
        theme.set_status_label(self.status_label, "شمارش ثبت شد.", ok=True)

    def _load_session(self) -> None:
        company_id = self._company_id()
        session_id = self.session_combo.currentData()
        self.table.setRowCount(0)
        self.workflow_bar.set_entity("INVENTORY_COUNT", session_id)
        if company_id is None or session_id is None:
            self.finalize_button.setEnabled(False)
            self.record_button.setEnabled(False)
            return
        data = count_service.get_count_session(session_id, company_id)
        is_open = data.status_code == "COUNTING"
        self.finalize_button.setEnabled(is_open)
        self.record_button.setEnabled(is_open)
        items_by_id = {it.item_id: it for it in self._items}
        self.table.setRowCount(len(data.lines))
        for i, ln in enumerate(data.lines):
            item = items_by_id.get(ln.item_id)
            base_name = self._uom_names.get(item.base_uom_id, "") if item else ""
            variance = ln.variance_quantity_base
            values = [
                f"{item.code} — {item.name or ''}" if item else str(ln.item_id),
                self._uom_names.get(ln.counted_uom_id, ""),
                decimals.format_qty(ln.counted_quantity) if ln.counted_quantity is not None else "",
                f"{decimals.format_qty(ln.counted_quantity_base)} {base_name}" if ln.counted_quantity_base is not None else "",
                f"{decimals.format_qty(ln.expected_quantity_base)} {base_name}",
                (("+" if variance > 0 else "") + decimals.format_qty(variance)) if variance is not None else "",
            ]
            for j, v in enumerate(values):
                self.table.setItem(i, j, QTableWidgetItem(v))
            if item is not None and (item.track_batch or item.track_serial):
                button = QPushButton("🏷 بچ/سریال")
                button.clicked.connect(lambda _c=False, iid=ln.item_id, lid=ln.line_id, ro=not is_open: self._open_tracking_count(iid, lid, ro))
                self.table.setCellWidget(i, len(values), button)

    def _open_tracking_count(self, item_id: int | None, line_id: int | None = None, read_only: bool = False) -> None:
        from peecha.ui.screens.lot_tracking_dialog import LotTrackingDialog

        company_id = self._company_id()
        session_id = self.session_combo.currentData()
        if company_id is None or session_id is None or item_id is None:
            self.status_label.setText("جلسهٔ انبارگردانی و کالا را انتخاب کنید.")
            return
        item = next((it for it in self._items if it.item_id == item_id), None)
        data = count_service.get_count_session(session_id, company_id)
        if line_id is None:
            line_id = next((ln.line_id for ln in data.lines if ln.item_id == item_id), None)

        def save(entries) -> None:
            count_service.record_count_tracking(session_id, company_id, item_id, entries)

        LotTrackingDialog(
            self, company_id, item_id, f"{item.code} — {item.name or ''}" if item else str(item_id), None,
            self._uom_names.get(item.base_uom_id, "") if item else "", cycle_count_line_id=line_id,
            read_only=read_only or data.status_code != "COUNTING", direction="COUNT", warehouse_id=data.warehouse_id,
            on_save=save,
        ).exec()
        self._load_session()

    def _finalize(self) -> None:
        company_id = self._company_id()
        session_id = self.session_combo.currentData()
        if company_id is None or session_id is None:
            return
        if not self.workflow_bar.guard("POSTED", None, "ثبت نهایی"):
            return
        if QMessageBox.question(self, "ثبت نهایی", "اختلاف‌ها با سند اصلاح موجودی ثبت شوند؟", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            documents = count_service.finalize_count_session(session_id, company_id, app_session.current_user.user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._reload_sessions(session_id)
        theme.set_status_label(
            self.status_label,
            f"انبارگردانی ثبت شد؛ {numerals.to_persian_digits(str(len(documents)))} سند اصلاح موجودی صادر شد." if documents
            else "انبارگردانی بدون اختلاف بسته شد.", ok=True,
        )
