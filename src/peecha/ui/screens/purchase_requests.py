"""فرم درخواست خرید — R241: فهرست + ویرایشگر، ارسال/تصویب/رد/لغو و تبدیل به سفارش خرید.

R321: فیلدهای سر و ردیف در کارت‌های چندستونه با اندازهٔ مناسب، پیمایش با Enter، ذخیرهٔ عرض ستون‌ها،
ویرایش ردیف، لغو/رد واقعی (دکمه‌ها قبلاً مقدار تیک دکمه را به‌جای علت می‌فرستادند)، و تبدیل به سفارش
به تفکیک تامین‌کنندهٔ هر ردیف یا همه در یک سفارش."""

from __future__ import annotations

import datetime
import decimal
from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QCompleter, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from peecha import decimals, numerals, session as app_session
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import procurement_masters as masters_service
from peecha.services import purchase_requests as pr_service
from peecha.services import roles as roles_service
from peecha.services import unit_conversion as uc
from peecha.ui import theme
from peecha.ui.persian_numbers import NumberEdit
from peecha.ui.screens import module_style as ms
from peecha.ui.screens.procurement_dialogs import CancellationReasonDialog
from peecha.ui.widgets import JalaliDateEdit, enter_navigation, live_check, persist_column_widths

_ZERO = decimal.Decimal(0)


def _searchable(combo: QComboBox, options: list[tuple[str, object]], empty: str | None = None) -> None:
    current = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    if empty is not None:
        combo.addItem(empty, None)
    for label, value in options:
        combo.addItem(numerals.to_persian_digits(label), value)
    if combo.isEditable():
        completer = QCompleter([combo.itemText(i) for i in range(combo.count())])
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        combo.setCompleter(completer)
    combo.setCurrentIndex(max(0, combo.findData(current)))
    combo.blockSignals(False)


def _editable_combo() -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    return combo


def _labeled(grid, col: int, text: str, widget: QWidget, row: int = 0) -> None:
    grid.addWidget(QLabel(text), row * 2, col)
    grid.addWidget(widget, row * 2 + 1, col)


def _select(combo: QComboBox, value, legacy_label: str | None = None) -> None:
    """مقدار ذخیره‌شده‌ای که دیگر در فهرست نیست (مثلاً مرکز هزینهٔ سطح بالاتر) برای نمایش افزوده می‌شود."""
    index = combo.findData(value)
    if index < 0 and value is not None and legacy_label:
        combo.addItem(legacy_label, value)
        index = combo.findData(value)
    combo.setCurrentIndex(max(0, index))


def _icon(label: str, slot) -> QPushButton:
    button = ms.style_button(QPushButton(label))
    button.clicked.connect(lambda _c=False, f=slot: f())  # بدون فرستادن مقدار تیک دکمه به‌جای آرگومان
    return button


class ConvertToOrderDialog(QDialog):
    """R321: تامین‌کنندهٔ هر ردیف (پیش‌فرض: پیشنهادی) و مقدار سفارش؛ سفارش جدا برای هر تامین‌کننده یا همه در یک سفارش."""

    def __init__(self, parent, suppliers: list[tuple[str, int]], lines, ordered, item_labels) -> None:
        super().__init__(parent)
        self.setWindowTitle("تبدیل به سفارش خرید")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(900, 460)
        self._suppliers = suppliers
        self._supplier_names = {value: label for label, value in suppliers}
        layout = QVBoxLayout(self)

        mode_row = QHBoxLayout()
        self.split_radio = QRadioButton("سفارش جدا برای هر تامین‌کننده")
        self.single_radio = QRadioButton("همهٔ ردیف‌ها در یک سفارش، با تامین‌کنندهٔ")
        group = QButtonGroup(self)
        group.addButton(self.split_radio)
        group.addButton(self.single_radio)
        self.split_radio.setChecked(True)
        self.supplier_combo = _editable_combo()
        _searchable(self.supplier_combo, suppliers, "—")
        self.supplier_combo.setMinimumWidth(260)
        mode_row.addWidget(self.split_radio)
        mode_row.addSpacing(18)
        mode_row.addWidget(self.single_radio)
        mode_row.addWidget(self.supplier_combo)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self._lines = [ln for ln in lines if ln.quantity_base - ordered.get(ln.line_id, _ZERO) > 0]
        self.table = QTableWidget(len(self._lines), 5)
        self.table.setHorizontalHeaderLabels(["کالا", "مقدار درخواست", "ماندهٔ قابل‌سفارش", "مقدار این سفارش", "تامین‌کننده"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setColumnWidth(3, 130)
        self.table.setColumnWidth(4, 260)
        persist_column_widths(self.table, "purchaseRequest/convert", skip_columns=(0,))
        self.qty_fields: list[NumberEdit] = []
        self.line_supplier_combos: list[QComboBox] = []
        for r, ln in enumerate(self._lines):
            remaining = (ln.quantity_base - ordered.get(ln.line_id, _ZERO)) / ln.conversion_factor
            self.table.setItem(r, 0, QTableWidgetItem(numerals.to_persian_digits(item_labels.get(ln.item_id, ""))))
            self.table.setItem(r, 1, QTableWidgetItem(decimals.format_qty(ln.quantity)))
            self.table.setItem(r, 2, QTableWidgetItem(decimals.format_qty(remaining, uom_id=ln.uom_id)))
            field = NumberEdit(format(remaining.normalize(), "f"))
            self.table.setCellWidget(r, 3, field)
            self.qty_fields.append(field)
            combo = _editable_combo()
            _searchable(combo, suppliers, "— بدون تامین‌کننده —")
            combo.setCurrentIndex(max(0, combo.findData(ln.suggested_supplier_detail_account_id)))
            combo.currentIndexChanged.connect(lambda _i: self._update_preview())
            self.table.setCellWidget(r, 4, combo)
            self.line_supplier_combos.append(combo)
            field.textChanged.connect(lambda _t: self._update_preview())
        layout.addWidget(self.table, stretch=1)
        # پیش‌فرض «یک سفارش»: رایج‌ترین تامین‌کنندهٔ پیشنهادی ردیف‌ها
        common = Counter(ln.suggested_supplier_detail_account_id for ln in self._lines if ln.suggested_supplier_detail_account_id)
        if common:
            self.supplier_combo.setCurrentIndex(max(0, self.supplier_combo.findData(common.most_common(1)[0][0])))

        self.preview_label = QLabel("")
        self.preview_label.setObjectName("sectionHint")
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)
        self.error_label = QLabel("")
        self.error_label.setObjectName("statusError")
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for widget in (self.split_radio, self.single_radio):
            widget.toggled.connect(lambda _c: self._update_preview())
        self.supplier_combo.currentIndexChanged.connect(lambda _i: self._update_preview())
        self._update_preview()

    def single_order(self) -> bool:
        return self.single_radio.isChecked()

    def quantities(self) -> dict[int, decimal.Decimal]:
        out = {}
        for ln, field in zip(self._lines, self.qty_fields):
            try:
                value = numerals.parse_decimal(field.text()) if field.text().strip() else _ZERO
            except ValueError:
                value = _ZERO
            if value > 0:
                out[ln.line_id] = value
        return out

    def line_suppliers(self) -> dict[int, int]:
        return {ln.line_id: combo.currentData() for ln, combo in zip(self._lines, self.line_supplier_combos)
                if combo.currentData() is not None}

    def selected_supplier(self) -> int | None:
        return self.supplier_combo.currentData() if self.single_order() else None

    def plan(self) -> tuple[dict[int | None, int], list[str]]:
        """{تامین‌کننده: تعداد ردیف} و خطاها — همان چیزی که پس از تایید ساخته می‌شود."""
        quantities, suppliers = self.quantities(), self.line_suppliers()
        groups: Counter = Counter()
        errors = []
        for ln in self._lines:
            if ln.line_id not in quantities:
                continue
            supplier = self.selected_supplier() if self.single_order() else suppliers.get(ln.line_id)
            groups[supplier] += 1
        if not groups:
            errors.append("مقدار هیچ ردیفی برای سفارش وارد نشده است.")
        if None in groups:
            errors.append("تامین‌کنندهٔ سفارش را انتخاب کنید." if self.single_order()
                          else "برای همهٔ ردیف‌های سفارش تامین‌کننده انتخاب کنید.")
        return dict(groups), errors

    def _update_preview(self) -> None:
        self.supplier_combo.setEnabled(self.single_order())
        for combo in self.line_supplier_combos:
            combo.setEnabled(not self.single_order())
        groups, errors = self.plan()
        named = [f"{self._supplier_names.get(s, '؟')} ({numerals.to_persian_digits(str(n))} ردیف)" for s, n in groups.items() if s]
        count = numerals.to_persian_digits(str(len(named)))
        self.preview_label.setText(f"{count} سفارش خرید ساخته می‌شود: " + "، ".join(named) if named else "")
        self.error_label.setText(" ".join(errors))

    def _accept(self) -> None:
        _groups, errors = self.plan()
        if errors:
            self.error_label.setText(" ".join(errors))
            return
        self.accept()


class PurchaseRequestScreen(QWidget):
    scroll_in_mdi = True  # R325: پنجرهٔ کوچک‌تر از فرم: اسکرول، نه له‌شدن ارتفاع فیلدها

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self._request_id: int | None = None
        self._status = "DRAFT"
        self._lines: list = []
        self._requests: list = []
        self._items: dict[int, str] = {}
        self._suppliers: list[tuple[str, int]] = []
        self._editing_line_id: int | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        title_row = QHBoxLayout()
        self.page_title = QLabel("درخواست خرید")
        self.page_title.setObjectName("pageTitle")
        title_row.addWidget(self.page_title)
        title_row.addStretch(1)
        title_row.addWidget(QLabel("نمایش:"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("همهٔ درخواست‌ها", None)
        for code, label in pr_service.STATUS_LABELS.items():
            self.status_filter.addItem(label, code)
        self.status_filter.currentIndexChanged.connect(lambda _i: self._reload_list())
        title_row.addWidget(self.status_filter)
        layout.addLayout(title_row)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)  # R325: فرم ویرایش با کشیدن جداکننده له نشود
        self.list_table = QTableWidget(0, 8)
        self.list_table.setMinimumHeight(110)
        self.list_table.setHorizontalHeaderLabels(
            ["شماره", "تاریخ", "درخواست‌کننده", "اولویت", "تاریخ نیاز", "وضعیت", "وضعیت سفارش", "شرح"])
        self.list_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.list_table.verticalHeader().setVisible(False)
        self.list_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        persist_column_widths(self.list_table, "purchaseRequest/list", skip_columns=(7,))
        self.list_table.cellDoubleClicked.connect(lambda row, _c: self._open_list_row(row))
        splitter.addWidget(self.list_table)

        editor = QWidget()
        ed = QVBoxLayout(editor)
        ed.setContentsMargins(0, 6, 0, 0)
        self.date_field, self.required_field = JalaliDateEdit(), JalaliDateEdit()
        self.priority_combo = QComboBox()
        for code, label in pr_service.PRIORITY_LABELS.items():
            self.priority_combo.addItem(label, code)
        self.type_combo, self.warehouse_combo = QComboBox(), QComboBox()
        self.cost_center_combo, self.project_combo = _editable_combo(), _editable_combo()
        self.description_field = QLineEdit()
        self.branch_combo, self.department_combo = QComboBox(), QComboBox()
        for widget in (self.date_field, self.required_field):
            widget.setMinimumWidth(120)
        for widget in (self.cost_center_combo, self.project_combo):
            widget.setMinimumWidth(220)
        self.description_field.setMinimumWidth(260)
        self._header_fields = [
            ("تاریخ", self.date_field), ("تاریخ نیاز", self.required_field), ("اولویت", self.priority_combo),
            ("نوع خرید", self.type_combo), ("انبار تحویل", self.warehouse_combo), ("مرکز هزینه", self.cost_center_combo),
            ("پروژه", self.project_combo), ("شعبه", self.branch_combo), ("دپارتمان", self.department_combo),
            ("شرح", self.description_field),
        ]
        ed.addWidget(ms.field_grid(self._header_fields, columns=5))
        self.info_label = QLabel("")
        self.info_label.setObjectName("sectionHint")
        self.info_label.setWordWrap(True)
        ed.addWidget(self.info_label)

        self.item_combo, self.uom_combo, self.supplier_combo = _editable_combo(), QComboBox(), _editable_combo()
        self.item_combo.setMinimumWidth(300)
        self.supplier_combo.setMinimumWidth(240)
        self.uom_combo.setMinimumWidth(110)
        self.item_combo.currentIndexChanged.connect(lambda _i: self._reload_units())
        self.qty_field, self.price_field = NumberEdit(), NumberEdit()
        self.qty_field.setMinimumWidth(130)
        self.price_field.setMinimumWidth(160)
        self.line_date_field = JalaliDateEdit()
        self.line_date_field.setMinimumWidth(120)
        self.line_description_field = QLineEdit()
        self.line_description_field.setMinimumWidth(220)
        self.add_line_button = _icon("افزودن ردیف", self.add_line)
        self.delete_line_button = _icon("حذف ردیف", self.delete_line)
        self.cancel_edit_button = _icon("انصراف از ویرایش ردیف", self._clear_line_entry)
        self.cancel_edit_button.setVisible(False)
        ed.addWidget(ms.field_grid(
            [("کالا", self.item_combo), ("واحد", self.uom_combo), ("مقدار", self.qty_field),
             ("فی برآوردی", self.price_field), ("تاریخ نیاز", self.line_date_field),
             ("تامین‌کنندهٔ پیشنهادی", self.supplier_combo), ("شرح ردیف", self.line_description_field)],
            columns=4, tail=[self.add_line_button, self.cancel_edit_button, self.delete_line_button]))

        self.lines_table = QTableWidget(0, 9)
        self.lines_table.setHorizontalHeaderLabels(
            ["کالا", "واحد", "مقدار", "تاریخ نیاز", "تامین‌کنندهٔ پیشنهادی", "فی برآوردی", "سفارش‌شده (پایه)", "مانده (پایه)",
             "شرح ردیف"])
        self.lines_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lines_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.lines_table.verticalHeader().setVisible(False)
        self.lines_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        persist_column_widths(self.lines_table, "purchaseRequest/lines", skip_columns=(0,))
        self.lines_table.setMinimumHeight(130)
        self.lines_table.cellDoubleClicked.connect(lambda row, _c: self.edit_line(row))
        ed.addWidget(self.lines_table, stretch=1)
        # R295: نوار گردش کار تایید (فقط وقتی فرایندی فعال است)
        from peecha.ui.screens.workflow_bar import WorkflowBar

        self.workflow_bar = WorkflowBar("PURCHASE_REQUEST")
        self.workflow_bar.on_started = lambda: self._request_id and self.edit_document(self._request_id)
        self.workflow_bar.main_window = self._main_window
        ed.addWidget(self.workflow_bar)

        # R301: دکمه‌های آیکونی، کنار هم سمت راست پایین فرم
        footer = QHBoxLayout()
        self.status_label = QLabel("")
        self.buttons: dict[str, QPushButton] = {}
        for key, text, slot in (
            ("save", "ذخیره", self.save_header), ("new", "جدید", self.new_request), ("submit", "ارسال برای تصویب", self.submit),
            ("approve", "تصویب", self.approve), ("reject", "رد", self.reject), ("cancel", "لغو", self.cancel),
            ("convert", "تبدیل به سفارش خرید", self.convert),
        ):
            button = _icon(text, slot)
            footer.addWidget(button)
            self.buttons[key] = button
        footer.addWidget(self.status_label, stretch=1)
        ed.addLayout(footer)
        splitter.addWidget(editor)
        splitter.setSizes([220, 560])
        layout.addWidget(splitter, stretch=1)

        # R322: کنترل همان لحظهٔ ورود، نه هنگام ذخیره
        live_check(self.required_field, self._check_required_date, self.status_label)
        live_check(self.line_date_field, self._check_line_date, self.status_label)
        live_check(self.qty_field, self._check_qty, self.status_label)
        live_check(self.price_field, self._check_price, self.status_label)

        # R321: پیمایش با Enter — سر درخواست، سپس ردیف کالا؛ Enter در آخرین فیلد ردیف را می‌افزاید
        self._enter = enter_navigation(
            [w for _l, w in self._header_fields]
            + [self.item_combo, self.uom_combo, self.qty_field, self.price_field, self.line_date_field, self.supplier_combo,
               self.line_description_field],
            on_last=self.add_line)

    # --- کنترل‌های لحظه‌ای ---------------------------------------------------
    def _check_required_date(self) -> str | None:
        start, need = self.date_field.date(), self.required_field.date()
        return "تاریخ نیاز نمی‌تواند پیش از تاریخ درخواست باشد." if start and need and need < start else None

    def _check_line_date(self) -> str | None:
        start, need = self.date_field.date(), self.line_date_field.date()
        return "تاریخ نیاز ردیف نمی‌تواند پیش از تاریخ درخواست باشد." if start and need and need < start else None

    def _check_qty(self) -> str | None:
        if not self.qty_field.text().strip():
            return None
        try:
            qty = numerals.parse_decimal(self.qty_field.text())
        except ValueError as exc:
            return str(exc)
        if qty <= 0:
            return "مقدار باید بزرگ‌تر از صفر باشد."
        item_id, uom_id = self.item_combo.currentData(), self.uom_combo.currentData()
        if item_id is not None and uom_id is not None:
            try:
                uc.validate_quantity(item_id, uom_id, qty, purpose="PURCHASE")
            except ValueError as exc:
                return str(exc)
        return None

    def _check_price(self) -> str | None:
        if not self.price_field.text().strip():
            return None
        try:
            price = numerals.parse_decimal(self.price_field.text())
        except ValueError as exc:
            return str(exc)
        return "فی برآوردی نمی‌تواند منفی باشد." if price < 0 else None

    # ------------------------------------------------------------------
    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def _user_id(self) -> int | None:
        return app_session.current_user.user_id if app_session.current_user else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._items = {i.item_id: f"{i.code} — {i.name or ''}" for i in catalog_service.list_items(company_id, transactable_only=True)
                       if i.is_purchasable}
        _searchable(self.item_combo, [(label, item_id) for item_id, label in self._items.items()])
        self._suppliers = [(f"{s['code']} — {s['name'] or ''}", s["detail_account_id"]) for s in dimensions_service.list_suppliers(company_id)]
        _searchable(self.supplier_combo, self._suppliers, "—")
        _searchable(self.type_combo, [(t.name, t.purchase_type_id) for t in masters_service.list_purchase_types(company_id, active_only=True)], "—")
        _searchable(self.warehouse_combo, [(w.name, w.warehouse_id) for w in locations_service.list_warehouses(company_id)], "—")
        _searchable(self.branch_combo, [(b.name, b.branch_id) for b in masters_service.list_branches(company_id, active_only=True)], "—")
        _searchable(self.department_combo, [(d.name, d.org_unit_id) for d in masters_service.list_departments(company_id)], "—")
        # R321: فقط آخرین سطح مرکز هزینه و پروژه قابل انتخاب است
        cc_type = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.COST_CENTER_CODE)
        pj_type = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.PROJECT_CODE)
        _searchable(self.cost_center_combo, [(f"{d.full_code} — {d.name or ''}", d.detail_account_id)
                                             for d in dimensions_service.list_leaf_detail_accounts(company_id, cc_type)], "—")
        _searchable(self.project_combo, [(f"{d.full_code} — {d.name or ''}", d.detail_account_id)
                                         for d in dimensions_service.list_leaf_detail_accounts(company_id, pj_type)], "—")
        self._reload_units()
        self._reload_list()
        if self._request_id is None:
            self.new_request()
            return
        try:
            self.edit_document(self._request_id)
        except ValueError:
            # R321: درخواستی که دیگر وجود ندارد (مثلاً پس از خام‌کردن داده‌ها) — فرم و ردیف‌هایش خالی می‌شود
            self._request_id = None
            self.new_request()

    def _reload_units(self) -> None:
        item_id = self.item_combo.currentData()
        self.uom_combo.clear()
        if item_id is None:
            return
        for unit in uc.get_item_units(item_id, purpose="PURCHASE"):
            self.uom_combo.addItem(unit.name, unit.uom_id)

    def _reload_list(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        status = self.status_filter.currentData()
        self._requests = list(reversed(pr_service.list_requests(company_id, statuses=(status,) if status else None)))
        users = self._users()
        self.list_table.setRowCount(len(self._requests))
        for r, req in enumerate(self._requests):
            _row, lines = pr_service.get_request(req.request_id, company_id)
            fulfil = pr_service.FULFILMENT_LABELS[pr_service.fulfilment(lines, pr_service.ordered_quantities([ln.line_id for ln in lines]))] \
                if req.status_code == "APPROVED" else ""
            cells = [str(req.request_no), numerals.format_jalali_date(req.request_date), users.get(req.requester_user_id, ""),
                     pr_service.PRIORITY_LABELS[req.priority_code],
                     numerals.format_jalali_date(req.required_date) if req.required_date else "",
                     pr_service.STATUS_LABELS[req.status_code], fulfil, req.description or ""]
            for c, text in enumerate(cells):
                self.list_table.setItem(r, c, QTableWidgetItem(numerals.to_persian_digits(text)))

    @staticmethod
    def _users() -> dict[int, str]:
        from peecha.services.purchase_reports_ext import _users

        return _users()

    def _open_list_row(self, row: int) -> None:
        if 0 <= row < len(self._requests):
            self.edit_document(self._requests[row].request_id)

    # --- ویرایشگر --------------------------------------------------------
    def new_request(self) -> None:
        self._request_id, self._status, self._lines = None, "DRAFT", []
        self.page_title.setText("درخواست خرید جدید")
        today = datetime.date.today()
        self.date_field.setDate(today)
        self.required_field.setDate(today + datetime.timedelta(days=7))
        for combo in (self.priority_combo, self.type_combo, self.warehouse_combo, self.cost_center_combo, self.project_combo,
                      self.branch_combo, self.department_combo):
            combo.setCurrentIndex(0)
        self.description_field.clear()
        self.info_label.setText("")
        self.status_label.setText("")
        self._clear_line_entry()
        self._render_lines()
        self._update_buttons()
        self.workflow_bar.set_entity("PURCHASE_REQUEST", None)
        self.date_field.setFocus()

    def edit_document(self, request_id: int) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        row, lines = pr_service.get_request(request_id, company_id)
        self._request_id, self._status, self._lines = request_id, row.status_code, lines
        self.page_title.setText(numerals.to_persian_digits(f"درخواست خرید شمارهٔ {row.request_no} -- {pr_service.STATUS_LABELS[row.status_code]}"))
        self.date_field.setDate(row.request_date)
        self.required_field.setDate(row.required_date or row.request_date)
        self.priority_combo.setCurrentIndex(max(0, self.priority_combo.findData(row.priority_code)))
        for combo, value in ((self.type_combo, row.purchase_type_id), (self.warehouse_combo, row.warehouse_id),
                             (self.branch_combo, row.branch_id), (self.department_combo, row.org_unit_id)):
            combo.setCurrentIndex(max(0, combo.findData(value)))
        for combo, value in ((self.cost_center_combo, row.cost_center_detail_account_id),
                             (self.project_combo, row.project_detail_account_id)):
            _select(combo, value, dimensions_service.get_detail_account_label(value) if value else None)
        self.description_field.setText(row.description or "")
        users = self._users()
        info = [f"درخواست‌کننده: {users.get(row.requester_user_id, '')}"]
        if row.approved_by_user_id:
            info.append(f"تصویب: {users.get(row.approved_by_user_id, '')} -- {numerals.format_jalali_datetime(row.approved_at)}")
        if row.rejected_reason:
            info.append(f"علت رد: {row.rejected_reason}")
        orders = pr_service.linked_orders(request_id)
        if orders:
            info.append("سفارش‌ها: " + "، ".join(numerals.to_persian_digits(str(o.document_no)) +
                                                 (" (لغوشده)" if o.status_code == "CANCELLED" else "") for o in orders))
        self.info_label.setText("   |   ".join(info))
        self._clear_line_entry()
        self._render_lines()
        self._update_buttons()
        self.workflow_bar.set_entity("PURCHASE_REQUEST", request_id)

    def _render_lines(self) -> None:
        ordered = pr_service.ordered_quantities([ln.line_id for ln in self._lines])
        suppliers = dict((v, k) for k, v in self._suppliers)
        units = {}
        self.lines_table.setRowCount(len(self._lines))
        for r, ln in enumerate(self._lines):
            if ln.item_id not in units:
                units[ln.item_id] = {u.uom_id: u.name for u in uc.get_item_units(ln.item_id, active_only=False)}
            done = ordered.get(ln.line_id, _ZERO)
            cells = [self._items.get(ln.item_id, str(ln.item_id)), units[ln.item_id].get(ln.uom_id, ""),
                     decimals.format_qty(ln.quantity),
                     numerals.format_jalali_date(ln.required_date) if ln.required_date else "",
                     suppliers.get(ln.suggested_supplier_detail_account_id, ""),
                     decimals.format_amount(ln.estimated_unit_price) if ln.estimated_unit_price is not None else "",
                     decimals.format_qty(done), decimals.format_qty(max(ln.quantity_base - done, 0), item_id=ln.item_id),
                     ln.description or ""]
            for c, text in enumerate(cells):
                self.lines_table.setItem(r, c, QTableWidgetItem(numerals.to_persian_digits(text)))

    def _update_buttons(self) -> None:
        editable = self._status in ("DRAFT", "REJECTED")
        is_manager = bool(self._user_id()) and roles_service.is_manager(self._user_id(), self._company_id()) if self._company_id() else False
        self.buttons["save"].setEnabled(editable)
        self.add_line_button.setEnabled(editable)
        self.delete_line_button.setEnabled(editable and self._request_id is not None)
        for widget in [w for _l, w in self._header_fields] + [
                self.item_combo, self.uom_combo, self.qty_field, self.price_field, self.line_date_field, self.supplier_combo,
                self.line_description_field]:
            widget.setEnabled(editable)
        self.buttons["submit"].setEnabled(editable and self._request_id is not None)
        # R323: تا گردش کار تعریف‌شده تمام نشده، تصویب/رد/تبدیل فقط از مسیر همان گردش کار است
        busy = None
        if self._request_id is not None and self._status in ("SUBMITTED", "APPROVED"):
            from peecha.services.workflow import model_events

            try:
                busy = model_events.busy(self._company_id(), "PURCHASE_REQUEST", self._request_id)
            except Exception:  # noqa: BLE001 -- بررسی کمکی نباید بارگذاری فرم را متوقف کند
                busy = None
        self.buttons["approve"].setEnabled(self._status == "SUBMITTED" and is_manager and not busy)
        self.buttons["reject"].setEnabled(self._status == "SUBMITTED" and is_manager and not busy)
        self.buttons["cancel"].setEnabled(self._request_id is not None and self._status != "CANCELLED")
        self.buttons["convert"].setEnabled(self._status == "APPROVED" and not busy)
        for key, label in (("approve", "تصویب"), ("reject", "رد"), ("convert", "تبدیل به سفارش خرید")):
            self.buttons[key].setToolTip(f"{label} -- {busy}" if busy else label)

    def _fields(self) -> pr_service.RequestFields:
        return pr_service.RequestFields(
            request_date=self.date_field.date(), required_date=self.required_field.date(), priority_code=self.priority_combo.currentData(),
            purchase_type_id=self.type_combo.currentData(), warehouse_id=self.warehouse_combo.currentData(),
            cost_center_detail_account_id=self.cost_center_combo.currentData(), project_detail_account_id=self.project_combo.currentData(),
            description=self.description_field.text().strip() or None,
            branch_id=self.branch_combo.currentData(), org_unit_id=self.department_combo.currentData(),
        )

    def _run(self, action, success: str) -> bool:
        try:
            action()
        except ValueError as exc:
            self.status_label.setText(str(exc))
            QMessageBox.warning(self, "درخواست خرید", str(exc))
            return False
        theme.set_status_label(self.status_label, success, ok=True)
        return True

    def save_header(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return

        def action():
            if self._request_id is None:
                self._request_id = pr_service.create_request(company_id, self._user_id(), self._fields())
            else:
                pr_service.update_request(self._request_id, company_id, self._fields())

        if self._run(action, "درخواست ذخیره شد."):
            self.edit_document(self._request_id)
            self._reload_list()

    # --- ردیف‌ها ----------------------------------------------------------
    def _clear_line_entry(self) -> None:
        self._editing_line_id = None
        self.item_combo.setEnabled(self._status in ("DRAFT", "REJECTED"))
        self.uom_combo.setEnabled(self._status in ("DRAFT", "REJECTED"))
        self.qty_field.clear()
        self.price_field.clear()
        self.line_description_field.clear()
        self.supplier_combo.setCurrentIndex(0)
        self.line_date_field.setDate(self.required_field.date() or datetime.date.today() + datetime.timedelta(days=7))
        self.add_line_button.setText(ms.ICONS["افزودن ردیف"][0])
        self.add_line_button.setToolTip("افزودن ردیف")
        self.cancel_edit_button.setVisible(False)

    def edit_line(self, row: int) -> None:
        """ردیف انتخاب‌شده در فیلدهای ورود می‌نشیند؛ کالا و واحد ثابت می‌مانند (مثل سرویس update_line)."""
        if not (0 <= row < len(self._lines)) or self._status not in ("DRAFT", "REJECTED"):
            return
        ln = self._lines[row]
        self._editing_line_id = ln.line_id
        self.item_combo.setCurrentIndex(max(0, self.item_combo.findData(ln.item_id)))
        self.uom_combo.setCurrentIndex(max(0, self.uom_combo.findData(ln.uom_id)))
        self.item_combo.setEnabled(False)
        self.uom_combo.setEnabled(False)
        self.qty_field.setText(format(ln.quantity.normalize(), "f"))
        self.price_field.setText(format(ln.estimated_unit_price.normalize(), "f") if ln.estimated_unit_price is not None else "")
        if ln.required_date:
            self.line_date_field.setDate(ln.required_date)
        self.supplier_combo.setCurrentIndex(max(0, self.supplier_combo.findData(ln.suggested_supplier_detail_account_id)))
        self.line_description_field.setText(ln.description or "")
        self.add_line_button.setText("💾")
        self.add_line_button.setToolTip("ذخیرهٔ ردیف")
        self.cancel_edit_button.setVisible(True)
        self.qty_field.setFocus()
        self.qty_field.selectAll()

    def add_line(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._status not in ("DRAFT", "REJECTED"):
            return
        if self._editing_line_id is None and self.item_combo.currentData() is None:
            self.status_label.setText("کالا را انتخاب کنید.")
            self.item_combo.setFocus()
            return
        editing = self._editing_line_id
        # مقدارها پیش از ذخیرهٔ خودکار سر درخواست خوانده می‌شوند (ذخیرهٔ سر، فیلدهای ردیف را خالی می‌کند)
        entry = (self.item_combo.currentData(), self.uom_combo.currentData(), self.qty_field.text(), self.price_field.text(),
                 self.line_date_field.date(), self.supplier_combo.currentData(), self.line_description_field.text().strip() or None)
        if self._request_id is None:
            self.save_header()
            if self._request_id is None:
                return
        item_id, uom_id, qty_text, price_text, line_date, supplier_id, description = entry

        def action():
            qty = numerals.parse_decimal(qty_text)
            price = numerals.parse_decimal(price_text) if price_text.strip() else None
            if editing is not None:
                pr_service.update_line(editing, self._request_id, company_id, qty, line_date, supplier_id, price, description)
            else:
                pr_service.add_line(self._request_id, company_id, item_id, uom_id, qty, line_date, supplier_id, price, description)

        if self._run(action, "ردیف ذخیره شد." if editing else "ردیف افزوده شد."):
            self.edit_document(self._request_id)
            self.item_combo.setFocus()

    def delete_line(self) -> None:
        rows = self.lines_table.selectionModel().selectedRows()
        if not rows or self._request_id is None:
            self.status_label.setText("ابتدا ردیفی را در جدول انتخاب کنید.")
            return
        line = self._lines[rows[0].row()]
        if self._run(lambda: pr_service.delete_line(line.line_id, self._request_id, self._company_id()), "ردیف حذف شد."):
            self.edit_document(self._request_id)

    # --- گردش وضعیت ---------------------------------------------------------
    def _transition(self, action, success: str) -> None:
        if self._request_id is not None and self._run(action, success):
            self.edit_document(self._request_id)
            self._reload_list()

    def submit(self) -> None:
        self._transition(lambda: pr_service.submit_request(self._request_id, self._company_id()), "درخواست برای تصویب ارسال شد.")
        # R326: اگر فرایند تایید «دستی» تعریف شده، همین ارسال آن را شروع می‌کند (وگرنه درخواست بی‌صاحب می‌ماند)
        if self._request_id is not None and self._status == "SUBMITTED":
            self.workflow_bar.set_entity("PURCHASE_REQUEST", self._request_id)
            if self.workflow_bar.start_if_pending():
                self.edit_document(self._request_id)
                theme.set_status_label(self.status_label, "درخواست برای تایید به مسئول مرحلهٔ اول فرستاده شد.", ok=True)

    def approve(self) -> None:
        self._transition(lambda: pr_service.approve_request(self._request_id, self._company_id(), self._user_id()), "درخواست تصویب شد.")

    def reject(self, reason: str | None = None) -> None:
        if reason is None:
            reason, ok = QInputDialog.getText(self, "رد درخواست", "علت رد:")
            if not ok:
                return
        self._transition(lambda: pr_service.reject_request(self._request_id, self._company_id(), reason), "درخواست رد شد.")

    def cancel(self, reason_id: int | None = None, confirm: bool = True) -> None:
        if self._request_id is None:
            return
        if confirm:
            answer = CancellationReasonDialog.ask(self, self._company_id())
            if answer is None:
                return
            reason_id = answer[0]
        self._transition(lambda: pr_service.cancel_request(self._request_id, self._company_id(), reason_id), "درخواست لغو شد.")

    def convert(self, supplier_id: int | None = None, quantities: dict | None = None, ask: bool = True,
                line_suppliers: dict | None = None) -> list[int]:
        company_id = self._company_id()
        if self._request_id is None or company_id is None:
            return []
        if ask:
            dialog = ConvertToOrderDialog(self, self._suppliers, self._lines,
                                          pr_service.ordered_quantities([ln.line_id for ln in self._lines]), self._items)
            if dialog.exec() != QDialog.Accepted:
                return []
            supplier_id, quantities, line_suppliers = dialog.selected_supplier(), dialog.quantities(), dialog.line_suppliers()
        created: list[int] = []

        def action():
            created.extend(pr_service.convert_to_orders(self._request_id, company_id, self._user_id(), supplier_id, quantities,
                                                        line_suppliers=line_suppliers))

        if self._run(action, "سفارش خرید ساخته شد."):
            self.edit_document(self._request_id)
            self._reload_list()
            if len(created) > 1:
                theme.set_status_label(self.status_label, numerals.to_persian_digits(
                    f"{len(created)} سفارش خرید جدا برای تامین‌کننده‌ها ساخته شد."), ok=True)
            if self._main_window is not None and len(created) == 1:
                order_id = created[0]
                self._main_window.open_screen("PURCH_ORDER", then=lambda screen: screen.edit_document(order_id))
        return created
