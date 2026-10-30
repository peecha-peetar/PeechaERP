"""R365: زبانهٔ «فهرست بها و صورت‌وضعیت» فرم پروژه‌ها."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services import inventory_catalog as catalog
from peecha.services.projects import billing
from peecha.ui import report_export, theme
from peecha.ui.screens.fixed_assets import P, combo, company_id, dec, fill, money, selected_data, set_combo, table, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec, JalaliDateEdit

_QTY_COL = 7


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


def _bar(*buttons) -> QHBoxLayout:
    row = QHBoxLayout()
    for label, glyph, kind, slot in buttons:
        button = _btn(label, glyph, kind)
        button.clicked.connect(slot)
        row.addWidget(button)
    row.addStretch(1)
    return row


def _q(value: decimal.Decimal) -> str:
    return P(f"{value.normalize():f}")


def _percent() -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(0, 100)
    box.setSuffix("٪")
    return box


class ProjectBillingTab(QWidget):
    def __init__(self, status) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self._status = status
        self.project_id: int | None = None
        self.project_label = ""
        self.contract_amount = decimal.Decimal(0)
        self.items: list = []
        self.statements: list = []
        self.statement = None
        self._item_id: int | None = None
        v = QVBoxLayout(self)
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        v.addWidget(self.summary_label)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._boq_tab(), "فهرست بها و تنظیمات")
        self.tabs.addTab(self._statements_tab(), "صورت‌وضعیت‌ها")
        v.addWidget(self.tabs, 1)

    # --- فهرست بها ---------------------------------------------------------------------------------------------------
    def _boq_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.service_combo = combo([], "—")
        self.retention_field, self.insurance_field, self.recovery_field = _percent(), _percent(), _percent()
        self.advance_field = QLineEdit()
        self.advance_field.setPlaceholderText("۰")
        row = QHBoxLayout()
        row.addWidget(FieldGrid([
            FieldSpec("bill_service", "کالای خدماتی فاکتور", self.service_combo, span=1),
            FieldSpec("bill_retention", "حسن انجام کار", self.retention_field, span=1),
            FieldSpec("bill_insurance", "کسر بیمه", self.insurance_field, span=1),
            FieldSpec("bill_advance", "پیش‌پرداخت دریافتی", self.advance_field, span=1),
            FieldSpec("bill_recovery", "استرداد پیش‌پرداخت از هر صورت‌وضعیت", self.recovery_field, span=1)]), 1)
        save = _btn("ذخیرهٔ تنظیمات صورت‌وضعیت", "💾", "primary")
        save.clicked.connect(self.save_settings)
        row.addWidget(save)
        v.addLayout(row)
        self.item_table = table(["کد", "شرح", "واحد", "مقدار قرارداد", "بهای واحد", "مبلغ"])
        self.item_table.itemSelectionChanged.connect(self._load_item)
        v.addWidget(self.item_table, 1)
        self.code_field, self.description_field, self.unit_field = QLineEdit(), QLineEdit(), QLineEdit()
        self.quantity_field, self.price_field = QLineEdit(), QLineEdit()
        v.addWidget(FieldGrid([
            FieldSpec("boq_code", "کد", self.code_field, span=1), FieldSpec("boq_desc", "شرح", self.description_field, span=2),
            FieldSpec("boq_unit", "واحد", self.unit_field, span=1), FieldSpec("boq_qty", "مقدار قرارداد", self.quantity_field, span=1),
            FieldSpec("boq_price", "بهای واحد", self.price_field, span=1)]))
        v.addLayout(_bar(("ذخیرهٔ ردیف فهرست بها", "💾", "primary", self.save_item), ("ردیف جدید", "🆕", "", self.new_item),
                         ("حذف ردیف", "🗑️", "danger", self.delete_item)))
        return w

    def set_project(self, project) -> None:
        self.project_id = project.project_id if project else None
        self.project_label = project.label if project else ""
        self.contract_amount = project.contract_amount if project else decimal.Decimal(0)
        self.statement = None
        self.new_item()
        self.refresh()

    def refresh(self) -> None:
        cid = company_id()
        self.item_table.setRowCount(0)
        self.statement_table.setRowCount(0)
        self.line_table.setRowCount(0)
        if cid is None or self.project_id is None:
            self.summary_label.setText("")
            return
        current = self.service_combo.currentData()
        self.service_combo.clear()
        self.service_combo.addItem("—", None)
        for it in catalog.list_items(cid, active_only=True, transactable_only=True):
            if it.item_kind_code == "SERVICE":
                self.service_combo.addItem(P(f"{it.code} — {it.name or ''}"), it.item_id)
        s = billing.get_settings(cid, self.project_id)
        set_combo(self.service_combo, s.service_item_id if s.service_item_id is not None else current)
        self.retention_field.setValue(float(s.retention_percent))
        self.insurance_field.setValue(float(s.insurance_percent))
        self.recovery_field.setValue(float(s.advance_recovery_percent))
        self.advance_field.setText(_q(s.advance_amount) if s.advance_amount else "")
        self.items = billing.list_contract_items(cid, self.project_id)
        fill(self.item_table, [[i.code, i.description, i.unit, _q(i.contract_quantity), i.unit_price,
                                (i.contract_quantity * i.unit_price).quantize(billing.CENT)] for i in self.items],
             [i.contract_item_id for i in self.items])
        total = billing.contract_total(cid, self.project_id)
        summary = billing.billing_summary(cid, self.project_id)
        text = (f"جمع فهرست بها {money(total)} | مبلغ قرارداد {money(self.contract_amount)} | کارکرد تاییدشده تا کنون "
                f"{money(summary['gross'])} | فاکتورشده {money(summary['invoiced'])} | حسن انجام کار نگه‌داشته‌شده "
                f"{money(summary['retention'])} | پیش‌پرداخت مستردشده {money(summary['advance_recovered'])}")
        if self.contract_amount and total != self.contract_amount:
            text += " | جمع فهرست بها با مبلغ قرارداد یکی نیست"
        self.summary_label.setText(text)
        self.statements = billing.list_statements(cid, self.project_id)
        fill(self.statement_table, [[s.statement_no, s.period_end, s.status_label, s.period_gross, s.deductions, s.net_payable,
                                     P(s.sales_invoice_no) if s.sales_invoice_no else "—"] for s in self.statements],
             [s.statement_id for s in self.statements])
        draft = next((s for s in self.statements if s.status_code == "DRAFT"), None)
        if self.statement is not None:
            self.open_statement(self.statement.statement_id)
        elif draft is not None:
            self.open_statement(draft.statement_id)

    def save_settings(self) -> bool:
        if self.project_id is None:
            self._status("یک پروژه را انتخاب کنید.", False)
            return False
        try:
            billing.save_settings(company_id(), self.project_id, billing.SettingsFields(
                self.service_combo.currentData(), decimal.Decimal(str(self.retention_field.value())),
                decimal.Decimal(str(self.insurance_field.value())), dec(self.advance_field.text()),
                decimal.Decimal(str(self.recovery_field.value()))))
        except (ValueError, decimal.InvalidOperation) as exc:
            self._status(str(exc) if isinstance(exc, ValueError) else "مبلغ پیش‌پرداخت نامعتبر است.", False)
            return False
        self.refresh()
        self._status("تنظیمات صورت‌وضعیت ذخیره شد.", True)
        return True

    def _load_item(self) -> None:
        cid = selected_data(self.item_table)
        i = next((x for x in self.items if x.contract_item_id == cid), None)
        if i is None:
            return
        self._item_id = i.contract_item_id
        self.code_field.setText(i.code)
        self.description_field.setText(i.description)
        self.unit_field.setText(i.unit)
        self.quantity_field.setText(_q(i.contract_quantity))
        self.price_field.setText(_q(i.unit_price))

    def new_item(self) -> None:
        self._item_id = None
        self.item_table.clearSelection()
        for f in (self.code_field, self.description_field, self.unit_field, self.quantity_field, self.price_field):
            f.clear()

    def save_item(self) -> int | None:
        if self.project_id is None:
            self._status("یک پروژه را انتخاب کنید.", False)
            return None
        try:
            item_id = billing.save_contract_item(company_id(), self.project_id, billing.ContractItemFields(
                self.code_field.text(), self.description_field.text(), self.unit_field.text(), dec(self.quantity_field.text()),
                dec(self.price_field.text())), self._item_id)
        except (ValueError, decimal.InvalidOperation) as exc:
            self._status(str(exc) if isinstance(exc, ValueError) else "مقدار یا بها نامعتبر است.", False)
            return None
        self.new_item()
        self.refresh()
        self._status("ردیف فهرست بها ذخیره شد.", True)
        return item_id

    def delete_item(self) -> bool:
        cid = selected_data(self.item_table)
        if cid is None:
            self._status("یک ردیف فهرست بها را انتخاب کنید.", False)
            return False
        try:
            billing.delete_contract_item(company_id(), self.project_id, cid)
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self.new_item()
        self.refresh()
        self._status("ردیف حذف شد.", True)
        return True

    # --- صورت‌وضعیت ---------------------------------------------------------------------------------------------------
    def _statements_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.period_field = JalaliDateEdit()
        row.addWidget(FieldGrid([FieldSpec("st_period", "پایان دوره", self.period_field, span=1)], columns=1))
        for label, glyph, kind, slot in (("صورت‌وضعیت جدید", "🆕", "primary", self.new_statement),
                                         ("تایید صورت‌وضعیت", "✅", "", self.confirm),
                                         ("ساخت فاکتور فروش پیش‌نویس", "🧾", "", self.create_invoice),
                                         ("چاپ صورت‌وضعیت", "🖨️", "", self.print_statement),
                                         ("خروجی Excel صورت‌وضعیت", "📊", "", self.export_statement),
                                         ("لغو صورت‌وضعیت", "🚫", "danger", self.cancel)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        v.addLayout(row)
        self.statement_table = table(["شماره", "پایان دوره", "وضعیت", "کارکرد این دوره", "کسور", "خالص قابل پرداخت", "فاکتور فروش"])
        self.statement_table.setMaximumHeight(170)
        self.statement_table.itemSelectionChanged.connect(lambda: self.open_statement(selected_data(self.statement_table)))
        v.addWidget(self.statement_table)
        self.statement_label = QLabel("")
        self.statement_label.setWordWrap(True)
        v.addWidget(self.statement_label)
        self.line_table = table(["کد", "شرح", "واحد", "مقدار قرارداد", "بهای واحد", "مقدار تا قبل", "مقدار این دوره", "مقدار تا کنون",
                                 "مبلغ تا کنون", "مبلغ این دوره"])
        v.addWidget(self.line_table, 1)
        v.addLayout(_bar(("ذخیرهٔ مقدارهای تا کنون (ستون قابل ویرایش)", "💾", "primary", self.save_quantities)))
        return w

    def open_statement(self, statement_id) -> None:
        if statement_id is None or company_id() is None:
            return
        s = self.statement = billing.get_statement(company_id(), statement_id)
        self.statement_label.setText(
            f"صورت‌وضعیت {P(s.statement_no)} ({s.status_label}) تا {numerals.format_jalali_date(s.period_end)} | کارکرد این دوره "
            f"{money(s.period_gross)} | حسن انجام کار {money(s.retention_amount)} | بیمه {money(s.insurance_amount)} | استرداد "
            f"پیش‌پرداخت {money(s.advance_recovery)} | خالص قابل پرداخت {money(s.net_payable)}")
        editable = s.status_code == "DRAFT"
        self.line_table.blockSignals(True)
        fill(self.line_table, [[ln.code, ln.description, ln.unit, _q(ln.contract_quantity), ln.unit_price, _q(ln.previous_quantity),
                                _q(ln.period_quantity), _q(ln.cumulative_quantity), ln.amount_to_date, ln.period_amount]
                               for ln in s.lines], [ln.contract_item_id for ln in s.lines])
        danger = theme.DANGER
        for r, ln in enumerate(s.lines):
            cell = self.line_table.item(r, _QTY_COL)
            flags = cell.flags()
            cell.setFlags(flags | Qt.ItemIsEditable if editable else flags & ~Qt.ItemIsEditable)
            if ln.over_contract:
                cell.setForeground(QColor(danger))
        self.line_table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed if editable
                                        else QAbstractItemView.NoEditTriggers)
        self.line_table.blockSignals(False)

    def set_cumulative(self, contract_item_id: int, value) -> None:
        """برای آزمون و ورود سریع: مقدار تا کنون یک ردیف در جدول."""
        for r in range(self.line_table.rowCount()):
            if self.line_table.item(r, 0).data(Qt.UserRole) == contract_item_id:
                self.line_table.setItem(r, _QTY_COL, QTableWidgetItem(P(value)))

    def save_quantities(self) -> bool:
        s = self.statement
        if s is None or s.status_code != "DRAFT":
            self._status("یک صورت‌وضعیت پیش‌نویس را باز کنید.", False)
            return False
        try:
            values = {self.line_table.item(r, 0).data(Qt.UserRole): dec(self.line_table.item(r, _QTY_COL).text())
                      for r in range(self.line_table.rowCount())}
            billing.save_quantities(company_id(), s.statement_id, values, self.period_field.date())
        except (ValueError, decimal.InvalidOperation) as exc:
            self._status(str(exc) if isinstance(exc, ValueError) else "مقدار واردشده نامعتبر است.", False)
            return False
        self.refresh()
        self._status("مقدارهای صورت‌وضعیت ذخیره شد.", True)
        return True

    def new_statement(self) -> int | None:
        if self.project_id is None:
            self._status("یک پروژه را انتخاب کنید.", False)
            return None
        try:
            statement_id = billing.new_statement(company_id(), user_id(), self.project_id, self.period_field.date())
        except ValueError as exc:
            self._status(str(exc), False)
            return None
        self.statement = None
        self.refresh()
        self.open_statement(statement_id)
        self._status("صورت‌وضعیت جدید با مقدارهای قبلی باز شد؛ مقدار تا کنون هر ردیف را وارد و ذخیره کنید.", True)
        return statement_id

    def _act(self, fn, done: str) -> bool:
        if self.statement is None:
            self._status("یک صورت‌وضعیت را انتخاب کنید.", False)
            return False
        try:
            fn(self.statement.statement_id)
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self.refresh()
        self._status(done, True)
        return True

    def confirm(self) -> bool:
        return self._act(lambda sid: billing.confirm(company_id(), user_id(), sid), "صورت‌وضعیت تایید شد.")

    def cancel(self) -> bool:
        return self._act(lambda sid: billing.cancel(company_id(), sid), "صورت‌وضعیت لغو شد.")

    def create_invoice(self) -> bool:
        return self._act(lambda sid: billing.create_invoice(company_id(), user_id(), sid),
                         "فاکتور فروش پیش‌نویس ساخته شد؛ مالیات و ثبت آن را در فرم فاکتور فروش انجام دهید.")

    def _print_args(self):
        return billing.statement_print_table(company_id(), self.statement.statement_id, self.project_label)

    def print_statement(self) -> bool:
        if self.statement is None:
            self._status("یک صورت‌وضعیت را انتخاب کنید.", False)
            return False
        title, headers, rows, head = self._print_args()
        report_export.print_report(self, title, headers, rows, filters=head)
        return True

    def export_statement(self) -> bool:
        if self.statement is None:
            self._status("یک صورت‌وضعیت را انتخاب کنید.", False)
            return False
        title, headers, rows, head = self._print_args()
        report_export.export_report_excel(self, title, headers, rows, filters=head)
        return True
