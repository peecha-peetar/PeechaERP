"""فرم درخواست خرید — R241: فهرست + ویرایشگر، ارسال/تصویب/رد/لغو و تبدیل به سفارش خرید."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QCompleter, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
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
from peecha.ui.screens import module_style as ms
from peecha.ui.widgets import JalaliDateEdit


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


def _labeled(grid: QGridLayout, col: int, text: str, widget: QWidget, row: int = 0) -> None:
    grid.addWidget(QLabel(text), row * 2, col)
    grid.addWidget(widget, row * 2 + 1, col)


class ConvertToOrderDialog(QDialog):
    """انتخاب تامین‌کننده (یا تامین‌کنندهٔ پیشنهادی هر ردیف) و مقدار سفارش."""

    def __init__(self, parent, suppliers: list[tuple[str, int]], lines, ordered, item_labels) -> None:
        super().__init__(parent)
        self.setWindowTitle("تبدیل به سفارش خرید")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(760, 420)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("تامین‌کننده:"))
        self.supplier_combo = _editable_combo()
        _searchable(self.supplier_combo, suppliers, "— تامین‌کنندهٔ پیشنهادی هر ردیف —")
        row.addWidget(self.supplier_combo, stretch=1)
        layout.addLayout(row)
        self._lines = [ln for ln in lines if ln.quantity_base - ordered.get(ln.line_id, decimal.Decimal(0)) > 0]
        self.table = QTableWidget(len(self._lines), 4)
        self.table.setHorizontalHeaderLabels(["کالا", "مقدار درخواست", "ماندهٔ قابل‌سفارش", "مقدار این سفارش"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.qty_fields: list[QLineEdit] = []
        for r, ln in enumerate(self._lines):
            remaining = (ln.quantity_base - ordered.get(ln.line_id, decimal.Decimal(0))) / ln.conversion_factor
            self.table.setItem(r, 0, QTableWidgetItem(numerals.to_persian_digits(item_labels.get(ln.item_id, ""))))
            self.table.setItem(r, 1, QTableWidgetItem(decimals.format_qty(ln.quantity)))
            self.table.setItem(r, 2, QTableWidgetItem(decimals.format_qty(remaining, uom_id=ln.uom_id)))
            field = QLineEdit(numerals.to_persian_digits(format(remaining.normalize(), "f")))
            self.table.setCellWidget(r, 3, field)
            self.qty_fields.append(field)
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def quantities(self) -> dict[int, decimal.Decimal]:
        out = {}
        for ln, field in zip(self._lines, self.qty_fields):
            value = numerals.parse_decimal(field.text()) if field.text().strip() else decimal.Decimal(0)
            if value > 0:
                out[ln.line_id] = value
        return out


class PurchaseRequestScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self._request_id: int | None = None
        self._status = "DRAFT"
        self._lines: list = []
        self._requests: list = []
        self._items: dict[int, str] = {}
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
        self.list_table = QTableWidget(0, 8)
        self.list_table.setHorizontalHeaderLabels(
            ["شماره", "تاریخ", "درخواست‌کننده", "اولویت", "تاریخ نیاز", "وضعیت", "وضعیت سفارش", "شرح"])
        self.list_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.list_table.verticalHeader().setVisible(False)
        self.list_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.list_table.cellDoubleClicked.connect(lambda row, _c: self._open_list_row(row))
        splitter.addWidget(self.list_table)

        editor = QWidget()
        ed = QVBoxLayout(editor)
        header = QGridLayout()
        self.date_field, self.required_field = JalaliDateEdit(), JalaliDateEdit()
        self.priority_combo = QComboBox()
        for code, label in pr_service.PRIORITY_LABELS.items():
            self.priority_combo.addItem(label, code)
        self.type_combo, self.warehouse_combo = QComboBox(), QComboBox()
        self.cost_center_combo, self.project_combo = _editable_combo(), _editable_combo()
        self.description_field = QLineEdit()
        self.branch_combo, self.department_combo = QComboBox(), QComboBox()
        for col, (text, widget) in enumerate((("تاریخ", self.date_field), ("تاریخ نیاز", self.required_field),
                                              ("اولویت", self.priority_combo), ("نوع خرید", self.type_combo),
                                              ("انبار تحویل", self.warehouse_combo), ("مرکز هزینه", self.cost_center_combo),
                                              ("پروژه", self.project_combo), ("شعبه", self.branch_combo),
                                              ("دپارتمان", self.department_combo), ("شرح", self.description_field))):
            _labeled(header, col, text, widget)
        ed.addLayout(header)
        self.info_label = QLabel("")
        self.info_label.setObjectName("sectionHint")
        ed.addWidget(self.info_label)

        line_row = QHBoxLayout()
        self.item_combo, self.uom_combo, self.supplier_combo = _editable_combo(), QComboBox(), _editable_combo()
        self.item_combo.setMinimumWidth(240)
        self.item_combo.currentIndexChanged.connect(lambda _i: self._reload_units())
        self.qty_field, self.price_field = QLineEdit(), QLineEdit()
        self.qty_field.setMaximumWidth(90)
        self.price_field.setMaximumWidth(110)
        self.line_date_field = JalaliDateEdit()
        for text, widget in (("کالا:", self.item_combo), ("واحد:", self.uom_combo), ("مقدار:", self.qty_field),
                             ("تاریخ نیاز:", self.line_date_field), ("تامین‌کنندهٔ پیشنهادی:", self.supplier_combo),
                             ("فی برآوردی:", self.price_field)):
            line_row.addWidget(QLabel(text))
            line_row.addWidget(widget)
        self.add_line_button = QPushButton("افزودن ردیف")
        self.add_line_button.clicked.connect(self.add_line)
        self.delete_line_button = QPushButton("حذف ردیف")
        self.delete_line_button.clicked.connect(self.delete_line)
        line_row.addWidget(self.add_line_button)
        line_row.addWidget(self.delete_line_button)
        ed.addLayout(line_row)

        self.lines_table = QTableWidget(0, 8)
        self.lines_table.setHorizontalHeaderLabels(
            ["کالا", "واحد", "مقدار", "تاریخ نیاز", "تامین‌کنندهٔ پیشنهادی", "فی برآوردی", "سفارش‌شده (پایه)", "مانده (پایه)"])
        self.lines_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lines_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.lines_table.verticalHeader().setVisible(False)
        self.lines_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        ed.addWidget(self.lines_table, stretch=1)
        # R295: نوار گردش کار تایید (فقط وقتی فرایندی فعال است)
        from peecha.ui.screens.workflow_bar import WorkflowBar

        self.workflow_bar = WorkflowBar("PURCHASE_REQUEST")
        self.workflow_bar.on_started = lambda: self._request_id and self.edit_document(self._request_id)
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
            button = ms.style_button(QPushButton(text))
            button.clicked.connect(slot)
            footer.addWidget(button)
            self.buttons[key] = button
        footer.addWidget(self.status_label, stretch=1)
        ed.addLayout(footer)
        splitter.addWidget(editor)
        splitter.setSizes([260, 520])
        layout.addWidget(splitter, stretch=1)

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
        cc_type = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.COST_CENTER_CODE)
        pj_type = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.PROJECT_CODE)
        details = dimensions_service.list_all_detail_accounts(company_id)
        _searchable(self.cost_center_combo, [(f"{d.full_code} — {d.name or ''}", d.detail_account_id) for d in details
                                             if d.dimension_type_id == cc_type], "—")
        _searchable(self.project_combo, [(f"{d.full_code} — {d.name or ''}", d.detail_account_id) for d in details
                                         if d.dimension_type_id == pj_type], "—")
        self._reload_units()
        self._reload_list()
        if self._request_id is None:
            self.new_request()
        else:
            self.edit_document(self._request_id)

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
        self.line_date_field.setDate(today + datetime.timedelta(days=7))
        for combo in (self.priority_combo, self.type_combo, self.warehouse_combo, self.cost_center_combo, self.project_combo,
                      self.branch_combo, self.department_combo):
            combo.setCurrentIndex(0)
        self.description_field.clear()
        self.info_label.setText("")
        self.status_label.setText("")
        self._render_lines()
        self._update_buttons()
        self.workflow_bar.set_entity("PURCHASE_REQUEST", None)

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
                             (self.cost_center_combo, row.cost_center_detail_account_id), (self.project_combo, row.project_detail_account_id),
                             (self.branch_combo, row.branch_id), (self.department_combo, row.org_unit_id)):
            combo.setCurrentIndex(max(0, combo.findData(value)))
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
        self._render_lines()
        self._update_buttons()
        self.workflow_bar.set_entity("PURCHASE_REQUEST", request_id)

    def _render_lines(self) -> None:
        ordered = pr_service.ordered_quantities([ln.line_id for ln in self._lines])
        suppliers = dict((v, k) for k, v in getattr(self, "_suppliers", []))
        units = {}
        self.lines_table.setRowCount(len(self._lines))
        for r, ln in enumerate(self._lines):
            if ln.item_id not in units:
                units[ln.item_id] = {u.uom_id: u.name for u in uc.get_item_units(ln.item_id, active_only=False)}
            done = ordered.get(ln.line_id, decimal.Decimal(0))
            cells = [self._items.get(ln.item_id, str(ln.item_id)), units[ln.item_id].get(ln.uom_id, ""),
                     decimals.format_qty(ln.quantity),
                     numerals.format_jalali_date(ln.required_date) if ln.required_date else "",
                     suppliers.get(ln.suggested_supplier_detail_account_id, ""),
                     decimals.format_amount(ln.estimated_unit_price) if ln.estimated_unit_price is not None else "",
                     decimals.format_qty(done), decimals.format_qty(max(ln.quantity_base - done, 0), item_id=ln.item_id)]
            for c, text in enumerate(cells):
                self.lines_table.setItem(r, c, QTableWidgetItem(numerals.to_persian_digits(text)))

    def _update_buttons(self) -> None:
        editable = self._status in ("DRAFT", "REJECTED")
        is_manager = bool(self._user_id()) and roles_service.is_manager(self._user_id(), self._company_id()) if self._company_id() else False
        self.buttons["save"].setEnabled(editable)
        self.add_line_button.setEnabled(editable)
        self.delete_line_button.setEnabled(editable and self._request_id is not None)
        self.buttons["submit"].setEnabled(editable and self._request_id is not None)
        self.buttons["approve"].setEnabled(self._status == "SUBMITTED" and is_manager)
        self.buttons["reject"].setEnabled(self._status == "SUBMITTED" and is_manager)
        self.buttons["cancel"].setEnabled(self._request_id is not None and self._status != "CANCELLED")
        self.buttons["convert"].setEnabled(self._status == "APPROVED")

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

    def add_line(self) -> None:
        company_id = self._company_id()
        if company_id is None or self.item_combo.currentData() is None:
            return
        if self._request_id is None:
            self.save_header()
            if self._request_id is None:
                return

        def action():
            qty = numerals.parse_decimal(self.qty_field.text())
            price = numerals.parse_decimal(self.price_field.text()) if self.price_field.text().strip() else None
            pr_service.add_line(self._request_id, company_id, self.item_combo.currentData(), self.uom_combo.currentData(), qty,
                                self.line_date_field.date(), self.supplier_combo.currentData(), price)

        if self._run(action, "ردیف افزوده شد."):
            self.qty_field.clear()
            self.price_field.clear()
            self.edit_document(self._request_id)

    def delete_line(self) -> None:
        rows = self.lines_table.selectionModel().selectedRows()
        if not rows or self._request_id is None:
            return
        line = self._lines[rows[0].row()]
        if self._run(lambda: pr_service.delete_line(line.line_id, self._request_id, self._company_id()), "ردیف حذف شد."):
            self.edit_document(self._request_id)

    def _transition(self, action, success: str) -> None:
        if self._request_id is not None and self._run(action, success):
            self.edit_document(self._request_id)
            self._reload_list()

    def submit(self) -> None:
        self._transition(lambda: pr_service.submit_request(self._request_id, self._company_id()), "درخواست برای تصویب ارسال شد.")

    def approve(self) -> None:
        self._transition(lambda: pr_service.approve_request(self._request_id, self._company_id(), self._user_id()), "درخواست تصویب شد.")

    def reject(self, reason: str | None = None) -> None:
        if reason is None:
            reason, ok = QInputDialog.getText(self, "رد درخواست", "علت رد:")
            if not ok:
                return
        self._transition(lambda: pr_service.reject_request(self._request_id, self._company_id(), reason), "درخواست رد شد.")

    def cancel(self, reason_id: int | None = None, confirm: bool = True) -> None:
        if confirm and QMessageBox.question(self, "لغو درخواست", "این درخواست لغو شود؟") != QMessageBox.Yes:
            return
        self._transition(lambda: pr_service.cancel_request(self._request_id, self._company_id(), reason_id), "درخواست لغو شد.")

    def convert(self, supplier_id: int | None = None, quantities: dict | None = None, ask: bool = True) -> list[int]:
        company_id = self._company_id()
        if self._request_id is None or company_id is None:
            return []
        if ask:
            dialog = ConvertToOrderDialog(self, self._suppliers, self._lines,
                                          pr_service.ordered_quantities([ln.line_id for ln in self._lines]), self._items)
            if dialog.exec() != QDialog.Accepted:
                return []
            supplier_id, quantities = dialog.supplier_combo.currentData(), dialog.quantities()
        created: list[int] = []

        def action():
            created.extend(pr_service.convert_to_orders(self._request_id, company_id, self._user_id(), supplier_id, quantities))

        if self._run(action, "سفارش خرید ساخته شد."):
            self.edit_document(self._request_id)
            self._reload_list()
            if self._main_window is not None and len(created) == 1:
                order_id = created[0]
                self._main_window.open_screen("PURCH_ORDER", then=lambda screen: screen.edit_document(order_id))
        return created
