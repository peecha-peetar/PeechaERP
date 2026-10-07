"""فرم استعلام قیمت — R242: ردیف‌ها، دعوت از تامین‌کنندگان، ثبت پیشنهاد، مقایسه، انتخاب برنده و سفارش."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from peecha import decimals, numerals, session as app_session
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import purchase_requests as pr_service
from peecha.services import rfqs as rfq_service
from peecha.services import unit_conversion as uc
from peecha.ui import theme
from peecha.ui.screens.purchase_requests import _editable_combo, _labeled, _searchable
from peecha.ui.widgets import JalaliDateEdit


def _table(headers: list[str], stretch: int = 0) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.Stretch)
    return table


def _fill(table: QTableWidget, rows: list[list[str]]) -> None:
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            table.setItem(r, c, QTableWidgetItem(numerals.to_persian_digits("" if text is None else str(text))))


def _money(value) -> str:
    return decimals.format_amount(value) if value is not None else ""


class QuoteDialog(QDialog):
    """ثبت پیشنهاد یک تامین‌کننده برای همهٔ ردیف‌ها (ردیف بدون فی ثبت نمی‌شود)."""

    def __init__(self, parent, supplier_label: str, lines, quotes_by_line: dict, item_labels: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"پیشنهاد {supplier_label}")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(820, 420)
        self.lines = lines
        layout = QVBoxLayout(self)
        self.table = QTableWidget(len(lines), 6)
        self.table.setHorizontalHeaderLabels(["کالا", "مقدار", "فی", "تخفیف٪", "زمان تحویل (روز)", "اعتبار تا"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.fields = []
        for r, ln in enumerate(lines):
            q = quotes_by_line.get(ln.line_id)
            self.table.setItem(r, 0, QTableWidgetItem(numerals.to_persian_digits(item_labels.get(ln.item_id, ""))))
            self.table.setItem(r, 1, QTableWidgetItem(decimals.format_qty(ln.quantity)))
            price = QLineEdit(numerals.to_persian_digits(format(q.unit_price.normalize(), "f")) if q else "")
            discount = QLineEdit(numerals.to_persian_digits(format(q.discount_percent.normalize(), "f")) if q else "")
            lead = QSpinBox()
            lead.setRange(0, 999)
            lead.setValue(q.lead_time_days or 0 if q else 0)
            valid = JalaliDateEdit()
            valid.setDate((q.valid_until if q and q.valid_until else datetime.date.today() + datetime.timedelta(days=30)))
            for c, widget in ((2, price), (3, discount), (4, lead), (5, valid)):
                self.table.setCellWidget(r, c, widget)
            self.fields.append((price, discount, lead, valid))
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> list[tuple]:
        out = []
        for ln, (price, discount, lead, valid) in zip(self.lines, self.fields):
            if not price.text().strip():
                continue
            out.append((ln.line_id, numerals.parse_decimal(price.text()),
                        numerals.parse_decimal(discount.text()) if discount.text().strip() else decimal.Decimal(0),
                        lead.value() or None, valid.date()))
        return out


class RfqScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self._rfq_id: int | None = None
        self._status = "DRAFT"
        self._lines, self._suppliers, self._quotes, self._comparison, self._rfqs = [], [], [], [], []
        self._items: dict[int, str] = {}
        self._supplier_labels: dict[int, str] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        self.page_title = QLabel("استعلام قیمت")
        self.page_title.setObjectName("pageTitle")
        layout.addWidget(self.page_title)
        splitter = QSplitter(Qt.Vertical)
        self.list_table = _table(["شماره", "تاریخ", "مهلت پاسخ", "وضعیت", "ردیف", "دعوت", "پاسخ", "شرح"], 7)
        self.list_table.cellDoubleClicked.connect(lambda row, _c: self.edit_document(self._rfqs[row].rfq_id))
        splitter.addWidget(self.list_table)

        editor = QWidget()
        ed = QVBoxLayout(editor)
        header = QGridLayout()
        self.date_field, self.due_field, self.description_field = JalaliDateEdit(), JalaliDateEdit(), QLineEdit()
        self.request_combo = QComboBox()
        from_request = QPushButton("استعلام از درخواست خرید")
        from_request.clicked.connect(self.create_from_request)
        for col, (text, widget) in enumerate((("تاریخ", self.date_field), ("مهلت پاسخ", self.due_field),
                                              ("شرح", self.description_field), ("درخواست خرید تصویب‌شده", self.request_combo))):
            _labeled(header, col, text, widget)
        header.addWidget(from_request, 1, 4)
        ed.addLayout(header)

        self.tabs = QTabWidget()
        # ردیف‌ها
        lines_tab = QWidget()
        lt = QVBoxLayout(lines_tab)
        row = QHBoxLayout()
        self.item_combo, self.uom_combo, self.qty_field = _editable_combo(), QComboBox(), QLineEdit()
        self.item_combo.setMinimumWidth(240)
        self.item_combo.currentIndexChanged.connect(lambda _i: self._reload_units())
        self.qty_field.setMaximumWidth(90)
        self.line_date_field = JalaliDateEdit()
        for text, widget in (("کالا:", self.item_combo), ("واحد:", self.uom_combo), ("مقدار:", self.qty_field),
                             ("تاریخ نیاز:", self.line_date_field)):
            row.addWidget(QLabel(text))
            row.addWidget(widget)
        self.add_line_button, self.delete_line_button = QPushButton("افزودن ردیف"), QPushButton("حذف ردیف")
        self.add_line_button.clicked.connect(self.add_line)
        self.delete_line_button.clicked.connect(self.delete_line)
        row.addWidget(self.add_line_button)
        row.addWidget(self.delete_line_button)
        lt.addLayout(row)
        self.lines_table = _table(["کالا", "واحد", "مقدار", "تاریخ نیاز", "از درخواست"])
        lt.addWidget(self.lines_table)
        self.tabs.addTab(lines_tab, "ردیف‌ها")
        # تامین‌کنندگان و پیشنهادها
        sup_tab = QWidget()
        st = QVBoxLayout(sup_tab)
        row = QHBoxLayout()
        self.supplier_combo = _editable_combo()
        self.supplier_combo.setMinimumWidth(260)
        row.addWidget(QLabel("تامین‌کننده:"))
        row.addWidget(self.supplier_combo)
        self.buttons: dict[str, QPushButton] = {}
        for key, text, slot in (("invite", "دعوت", self.add_supplier), ("uninvite", "حذف دعوت", self.remove_supplier),
                                ("quote", "ثبت پیشنهاد", self.enter_quote), ("decline", "ثبت انصراف", self.decline)):
            button = QPushButton(text)
            button.clicked.connect(lambda _c=False, s=slot: s())
            row.addWidget(button)
            self.buttons[key] = button
        row.addStretch(1)
        st.addLayout(row)
        self.suppliers_table = _table(["تامین‌کننده", "وضعیت", "زمان پاسخ", "ردیف‌های پیشنهادشده", "جمع پیشنهاد (خالص)"])
        st.addWidget(self.suppliers_table)
        self.tabs.addTab(sup_tab, "تامین‌کنندگان و پیشنهادها")
        # مقایسه
        cmp_tab = QWidget()
        ct = QVBoxLayout(cmp_tab)
        self.comparison_table = _table(["کالا", "تامین‌کننده", "فی", "تخفیف٪", "فی خالص", "جمع", "زمان تحویل", "اعتبار تا", "رتبه", "وضعیت"])
        self.comparison_table.setSelectionMode(QAbstractItemView.MultiSelection)
        ct.addWidget(self.comparison_table)
        row = QHBoxLayout()
        for key, text, slot in (("award_best", "انتخاب بهترین پیشنهاد هر ردیف", lambda: self.award(None)),
                                ("award_selected", "انتخاب ردیف‌های علامت‌خورده", self.award_selected),
                                ("order", "ساخت سفارش خرید برای برنده‌ها", self.create_orders)):
            button = QPushButton(text)
            if key == "order":
                button.setObjectName("primaryButton")
            button.clicked.connect(lambda _c=False, s=slot: s())
            row.addWidget(button)
            self.buttons[key] = button
        row.addStretch(1)
        ct.addLayout(row)
        self.tabs.addTab(cmp_tab, "مقایسه و انتخاب")
        ed.addWidget(self.tabs, stretch=1)

        footer = QHBoxLayout()
        self.status_label = QLabel("")
        footer.addWidget(self.status_label, stretch=1)
        for key, text, slot in (("new", "جدید", self.new_rfq), ("save", "ذخیره", self.save_header), ("send", "ارسال", self.send),
                                ("cancel", "لغو", self.cancel)):
            button = QPushButton(text)
            if key == "save":
                button.setObjectName("primaryButton")
            button.clicked.connect(lambda _c=False, s=slot: s())
            footer.addWidget(button)
            self.buttons[key] = button
        ed.addLayout(footer)
        splitter.addWidget(editor)
        splitter.setSizes([220, 560])
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
        self._supplier_labels = {s["detail_account_id"]: f"{s['code']} — {s['name'] or ''}" for s in dimensions_service.list_suppliers(company_id)}
        _searchable(self.supplier_combo, [(label, sid) for sid, label in self._supplier_labels.items()])
        _searchable(self.request_combo, [(f"درخواست {r.request_no}", r.request_id)
                                         for r in pr_service.list_requests(company_id, statuses=("APPROVED",))], "—")
        self._reload_units()
        self._reload_list()
        if self._rfq_id is None:
            self.new_rfq()
        else:
            self.edit_document(self._rfq_id)

    def _reload_units(self) -> None:
        self.uom_combo.clear()
        item_id = self.item_combo.currentData()
        if item_id is not None:
            for unit in uc.get_item_units(item_id, purpose="PURCHASE"):
                self.uom_combo.addItem(unit.name, unit.uom_id)

    def _reload_list(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._rfqs = list(reversed(rfq_service.list_rfqs(company_id)))
        rows = []
        for r in self._rfqs:
            _row, lines, suppliers, _q = rfq_service.get_rfq(r.rfq_id, company_id)
            rows.append([r.rfq_no, numerals.format_jalali_date(r.rfq_date),
                         numerals.format_jalali_date(r.response_due_date) if r.response_due_date else "",
                         rfq_service.STATUS_LABELS[r.status_code], len(lines), len(suppliers),
                         sum(s.status_code == "RESPONDED" for s in suppliers), r.description or ""])
        _fill(self.list_table, rows)

    def new_rfq(self) -> None:
        self._rfq_id, self._status = None, "DRAFT"
        self._lines, self._suppliers, self._quotes, self._comparison = [], [], [], []
        self.page_title.setText("استعلام قیمت جدید")
        self.date_field.setDate(datetime.date.today())
        self.due_field.setDate(datetime.date.today() + datetime.timedelta(days=5))
        self.line_date_field.setDate(datetime.date.today() + datetime.timedelta(days=14))
        self.description_field.clear()
        self.status_label.setText("")
        self._render()

    def edit_document(self, rfq_id: int) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        row, self._lines, self._suppliers, self._quotes = rfq_service.get_rfq(rfq_id, company_id)
        self._rfq_id, self._status = rfq_id, row.status_code
        self._comparison = rfq_service.compare(rfq_id, company_id)
        self.page_title.setText(numerals.to_persian_digits(f"استعلام قیمت شمارهٔ {row.rfq_no} -- {rfq_service.STATUS_LABELS[row.status_code]}"))
        self.date_field.setDate(row.rfq_date)
        self.due_field.setDate(row.response_due_date or row.rfq_date)
        self.description_field.setText(row.description or "")
        self._render()

    def _render(self) -> None:
        units: dict[int, dict] = {}
        rows = []
        for ln in self._lines:
            if ln.item_id not in units:
                units[ln.item_id] = {u.uom_id: u.name for u in uc.get_item_units(ln.item_id, active_only=False)}
            rows.append([self._items.get(ln.item_id, ln.item_id), units[ln.item_id].get(ln.uom_id, ""), decimals.format_qty(ln.quantity),
                         numerals.format_jalali_date(ln.required_date) if ln.required_date else "",
                         "بله" if ln.purchase_request_line_id else ""])
        _fill(self.lines_table, rows)
        by_line = {ln.line_id: ln for ln in self._lines}
        rows = []
        for sp in self._suppliers:
            qs = [q for q in self._quotes if q.rfq_supplier_id == sp.rfq_supplier_id]
            total = sum((rfq_service.net_price(q) * by_line[q.rfq_line_id].quantity for q in qs), decimal.Decimal(0))
            rows.append([self._supplier_labels.get(sp.supplier_detail_account_id, ""), rfq_service.SUPPLIER_STATUS_LABELS[sp.status_code],
                         numerals.format_jalali_datetime(sp.responded_at) if sp.responded_at else "", len(qs), _money(total) if qs else ""])
        _fill(self.suppliers_table, rows)
        rows = []
        for c in self._comparison:
            rows.append([self._items.get(c.line.item_id, ""), self._supplier_labels.get(c.supplier.supplier_detail_account_id, ""),
                         _money(c.quote.unit_price), numerals.format_money(c.quote.discount_percent, 1, None), _money(c.net), _money(c.total),
                         c.quote.lead_time_days or "", numerals.format_jalali_date(c.quote.valid_until) if c.quote.valid_until else "",
                         c.rank, "برنده" if c.quote.is_awarded else ("بهترین" if c.is_best else "")])
        _fill(self.comparison_table, rows)
        for r, c in enumerate(self._comparison):
            if c.quote.is_awarded or c.is_best:
                color = QColor(theme.SUCCESS if c.quote.is_awarded else theme.ACCENT)
                for col in range(self.comparison_table.columnCount()):
                    self.comparison_table.item(r, col).setForeground(color)
        draft, sent = self._status == "DRAFT", self._status == "SENT"
        self.buttons["save"].setEnabled(draft or sent or self._rfq_id is None)
        self.add_line_button.setEnabled(draft)
        self.delete_line_button.setEnabled(draft and self._rfq_id is not None)
        self.buttons["invite"].setEnabled(self._rfq_id is not None and (draft or sent))
        self.buttons["uninvite"].setEnabled(draft and self._rfq_id is not None)
        self.buttons["quote"].setEnabled(sent)
        self.buttons["decline"].setEnabled(sent)
        self.buttons["send"].setEnabled(draft and self._rfq_id is not None)
        self.buttons["award_best"].setEnabled(self._status in ("SENT", "AWARDED") and bool(self._comparison))
        self.buttons["award_selected"].setEnabled(self._status in ("SENT", "AWARDED") and bool(self._comparison))
        self.buttons["order"].setEnabled(self._status == "AWARDED")
        self.buttons["cancel"].setEnabled(self._rfq_id is not None and self._status in ("DRAFT", "SENT", "AWARDED"))

    def _run(self, action, success: str, reload: bool = True) -> bool:
        try:
            action()
        except ValueError as exc:
            self.status_label.setText(str(exc))
            QMessageBox.warning(self, "استعلام قیمت", str(exc))
            return False
        theme.set_status_label(self.status_label, success, ok=True)
        if reload and self._rfq_id is not None:
            self.edit_document(self._rfq_id)
            self._reload_list()
        return True

    # --- عملیات ----------------------------------------------------------
    def save_header(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return

        def action():
            if self._rfq_id is None:
                self._rfq_id = rfq_service.create_rfq(company_id, self._user_id(), self.date_field.date(), self.due_field.date(),
                                                      self.description_field.text().strip() or None)
            else:
                rfq_service.update_rfq(self._rfq_id, company_id, self.date_field.date(), self.due_field.date(),
                                       self.description_field.text().strip() or None)

        self._run(action, "استعلام ذخیره شد.")

    def create_from_request(self) -> None:
        company_id, request_id = self._company_id(), self.request_combo.currentData()
        if company_id is None or request_id is None:
            return

        def action():
            self._rfq_id = rfq_service.create_from_request(request_id, company_id, self._user_id(), self.due_field.date())

        self._run(action, "استعلام از درخواست خرید ساخته شد.")

    def add_line(self) -> None:
        company_id = self._company_id()
        if company_id is None or self.item_combo.currentData() is None:
            return
        if self._rfq_id is None:
            self.save_header()
            if self._rfq_id is None:
                return
        if self._run(lambda: rfq_service.add_line(self._rfq_id, company_id, self.item_combo.currentData(), self.uom_combo.currentData(),
                                                  numerals.parse_decimal(self.qty_field.text()), self.line_date_field.date()),
                     "ردیف افزوده شد."):
            self.qty_field.clear()

    def delete_line(self) -> None:
        rows = self.lines_table.selectionModel().selectedRows()
        if rows and self._rfq_id is not None:
            line = self._lines[rows[0].row()]
            self._run(lambda: rfq_service.delete_line(line.line_id, self._rfq_id, self._company_id()), "ردیف حذف شد.")

    def _selected_supplier(self):
        rows = self.suppliers_table.selectionModel().selectedRows()
        return self._suppliers[rows[0].row()] if rows else None

    def add_supplier(self) -> None:
        if self._rfq_id is not None and self.supplier_combo.currentData() is not None:
            self._run(lambda: rfq_service.add_supplier(self._rfq_id, self._company_id(), self.supplier_combo.currentData()), "دعوت ثبت شد.")

    def remove_supplier(self) -> None:
        sp = self._selected_supplier()
        if sp is not None:
            self._run(lambda: rfq_service.remove_supplier(sp.rfq_supplier_id, self._rfq_id, self._company_id()), "دعوت حذف شد.")

    def enter_quote(self, values: list[tuple] | None = None, supplier=None) -> None:
        sp = supplier or self._selected_supplier()
        if sp is None:
            QMessageBox.information(self, "پیشنهاد", "ابتدا تامین‌کننده را در جدول انتخاب کنید.")
            return
        if values is None:
            existing = {q.rfq_line_id: q for q in self._quotes if q.rfq_supplier_id == sp.rfq_supplier_id}
            dialog = QuoteDialog(self, self._supplier_labels.get(sp.supplier_detail_account_id, ""), self._lines, existing, self._items)
            if dialog.exec() != QDialog.Accepted:
                return
            values = dialog.values()

        def action():
            for line_id, price, discount, lead, valid in values:
                rfq_service.record_quote(sp.rfq_supplier_id, line_id, self._company_id(), price, discount, lead, valid)

        self._run(action, "پیشنهاد ثبت شد.")

    def decline(self) -> None:
        sp = self._selected_supplier()
        if sp is not None:
            self._run(lambda: rfq_service.decline(sp.rfq_supplier_id, self._company_id()), "انصراف تامین‌کننده ثبت شد.")

    def send(self) -> None:
        if self._rfq_id is not None:
            self._run(lambda: rfq_service.send_rfq(self._rfq_id, self._company_id()), "استعلام ارسال شد.")

    def award(self, quote_ids: list[int] | None) -> None:
        if self._rfq_id is not None:
            self._run(lambda: rfq_service.award(self._rfq_id, self._company_id(), self._user_id(), quote_ids), "برنده انتخاب شد.")

    def award_selected(self) -> None:
        rows = sorted({i.row() for i in self.comparison_table.selectedIndexes()})
        if rows:
            self.award([self._comparison[r].quote.quote_id for r in rows])

    def create_orders(self) -> list[int]:
        created: list[int] = []
        if self._rfq_id is None:
            return created
        if self._run(lambda: created.extend(rfq_service.create_orders(self._rfq_id, self._company_id(), self._user_id())),
                     "سفارش خرید ساخته شد.") and self._main_window is not None and len(created) == 1:
            order_id = created[0]
            self._main_window.open_screen("PURCH_ORDER", then=lambda screen: screen.edit_document(order_id))
        return created

    def cancel(self, confirm: bool = True) -> None:
        if self._rfq_id is None:
            return
        if confirm and QMessageBox.question(self, "لغو استعلام", "این استعلام لغو شود؟") != QMessageBox.Yes:
            return
        self._run(lambda: rfq_service.cancel_rfq(self._rfq_id, self._company_id()), "استعلام لغو شد.")
