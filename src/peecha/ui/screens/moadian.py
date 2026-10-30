"""R348: سامانهٔ مودیان — صورتحساب الکترونیکی فاکتورهای فروش ثبت‌شده: ساخت، ارسال، استعلام نتیجه، ابطال، و تنظیمات
(شناسهٔ حافظه، شمارهٔ اقتصادی، کلید و گواهی، کد واحدهای سنجش)."""

from __future__ import annotations

import datetime
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services import inventory_catalog as catalog_service
from peecha.services import moadian as moadian_service
from peecha.ui import theme
from peecha.ui.screens.fixed_assets import P, company_id, fill, table, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec, JalaliDateEdit, build_page_header

_TYPE_LABELS = {"SALES_INVOICE": "فاکتور فروش", "SALES_RETURN": "برگشت از فروش"}


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName("primaryIconButton" if kind == "primary" else "iconButton")
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


def _messages(errors: list) -> list[str]:
    return [f"{e.get('code') or ''} {e.get('message') or ''}".strip() for e in errors or [] if isinstance(e, dict)]


class MoadianScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.rows: list[moadian_service.InvoiceRow] = []
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "سامانهٔ مودیان", "صورتحساب الکترونیکی فاکتورهای فروش و برگشت از فروش ثبت‌شده: ساخت، ارسال، پیگیری نتیجه و ابطال."))
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_invoices_tab(), "صورتحساب‌ها")
        self.tabs.addTab(self._build_settings_tab(), "تنظیمات")
        layout.addWidget(self.tabs, 1)

    # --- صورتحساب‌ها -----------------------------------------------------------------------------------------------
    def _build_invoices_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        filters = QHBoxLayout()
        today = datetime.date.today()
        self.date_from = JalaliDateEdit()
        self.date_from.setDate(today - datetime.timedelta(days=30))
        self.date_to = JalaliDateEdit()
        self.date_to.setDate(today)
        search = _btn("نمایش فاکتورهای بازه", "🔍", "primary")
        search.clicked.connect(self.load)
        for widget in (QLabel("از تاریخ"), self.date_from, QLabel("تا تاریخ"), self.date_to, search):
            filters.addWidget(widget)
        filters.addStretch(1)
        layout.addLayout(filters)
        self.table = table(["نوع سند", "شماره", "تاریخ", "مشتری", "مبلغ", "موضوع", "شمارهٔ مالیاتی", "وضعیت در سامانه"])
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        self.prepare_button = _btn("ساخت صورتحساب برای ردیف‌های انتخاب‌شده", "🧾", "primary")
        self.send_button = _btn("ارسال همهٔ صورتحساب‌های آماده", "📤")
        self.check_button = _btn("استعلام نتیجه از سامانه", "🔄")
        self.cancel_button = _btn("ابطال صورتحساب پذیرفته‌شدهٔ ردیف انتخاب‌شده", "⛔")
        self.details_button = _btn("ایرادها و پیام‌های سامانه برای ردیف انتخاب‌شده", "📋")
        self.export_button = _btn("ذخیرهٔ متن صورتحساب ردیف انتخاب‌شده", "💾")
        for button, handler in ((self.prepare_button, self.prepare_selected), (self.send_button, self.send),
                                (self.check_button, self.check), (self.cancel_button, self.cancel_selected),
                                (self.details_button, self.show_details), (self.export_button, self.export_selected)):
            button.clicked.connect(handler)
            bar.addWidget(button)
        bar.addStretch(1)
        layout.addLayout(bar)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        return tab

    def refresh(self) -> None:
        if company_id() is None:
            return
        self.load()
        self.load_settings()

    def load(self) -> None:
        self.rows = moadian_service.list_documents(company_id(), self.date_from.date(), self.date_to.date())
        fill(self.table, [[_TYPE_LABELS.get(r.document_type_code, r.document_type_code), r.document_no, r.document_date,
                           r.customer, r.total, moadian_service.SUBJECT_LABELS.get(r.subject_code, ""), "",
                           moadian_service.STATUS_LABELS.get(r.status, "ساخته نشده")] for r in self.rows],
             [r.document_id for r in self.rows])
        for index, row in enumerate(self.rows):
            self.table.setItem(index, 6, QTableWidgetItem(row.tax_id))  # شمارهٔ مالیاتی با همان حروف و ارقام لاتین

    def _selected_rows(self) -> list[moadian_service.InvoiceRow]:
        indexes = sorted({item.row() for item in self.table.selectedItems()})
        return [self.rows[i] for i in indexes if i < len(self.rows)]

    def _one(self, title: str) -> moadian_service.InvoiceRow | None:
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self, title, "یک ردیف را انتخاب کنید.")
            return None
        return rows[0]

    def _report(self, text: str, ok: bool = True) -> None:
        theme.set_status_label(self.status_label, text, ok=ok)

    def prepare_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self, "ساخت صورتحساب", "فاکتورهایی را که صورتحساب می‌خواهند انتخاب کنید.")
            return
        made, failed = 0, []
        for row in rows:
            try:
                moadian_service.prepare(row.document_id, company_id(), user_id())
                made += 1
            except ValueError as exc:
                failed.append(f"سند {P(row.document_no)}: {exc}")
        self.load()
        self._report(P(f"{made} صورتحساب آمادهٔ ارسال شد.") + ("\n" + "\n".join(failed) if failed else ""), ok=not failed)

    def send(self) -> None:
        try:
            count = moadian_service.send_prepared(company_id())
        except ValueError as exc:
            self.load()
            self._report(str(exc), ok=False)
            return
        self.load()
        self._report(P(f"{count} صورتحساب ارسال شد؛ چند دقیقهٔ دیگر نتیجه را استعلام کنید.") if count
                     else "صورتحساب آماده‌ای برای ارسال نیست.", ok=True)

    def check(self) -> None:
        try:
            count = moadian_service.check_sent(company_id())
        except ValueError as exc:
            self._report(str(exc), ok=False)
            return
        self.load()
        self._report(P(f"نتیجهٔ {count} صورتحساب از سامانه دریافت شد."), ok=True)

    def cancel_selected(self) -> None:
        row = self._one("ابطال صورتحساب")
        if row is None:
            return
        if QMessageBox.question(self, "ابطال صورتحساب", "صورتحساب ابطالی این سند ساخته شود؟ پس از آن باید ارسال شود.",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            moadian_service.prepare_cancel(row.document_id, company_id(), user_id())
        except ValueError as exc:
            self._report(str(exc), ok=False)
            return
        self.load()
        self._report("صورتحساب ابطالی آمادهٔ ارسال شد.", ok=True)

    def show_details(self) -> None:
        row = self._one("جزئیات صورتحساب")
        if row is None:
            return
        if row.moadian_invoice_id is None:
            _payload, problems = moadian_service.build_payload(row.document_id, company_id())
            text = "\n".join(f"• {p}" for p in problems) or "این سند آمادهٔ ساخت صورتحساب است."
        else:
            messages = _messages(row.errors)
            text = (f"شمارهٔ مالیاتی: {row.tax_id}\nوضعیت: {moadian_service.STATUS_LABELS.get(row.status, row.status)}"
                    + ("\n\n" + "\n".join(f"• {m}" for m in messages) if messages else ""))
        QMessageBox.information(self, "جزئیات صورتحساب", text)

    def export_selected(self) -> None:
        row = self._one("ذخیرهٔ صورتحساب")
        if row is None or row.moadian_invoice_id is None:
            if row is not None:
                QMessageBox.information(self, "ذخیرهٔ صورتحساب", "برای این سند هنوز صورتحسابی ساخته نشده است.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "ذخیرهٔ صورتحساب", f"{row.tax_id}.json", "JSON (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(moadian_service.get_payload(row.moadian_invoice_id, company_id()), handle, ensure_ascii=False, indent=2)

    # --- تنظیمات ---------------------------------------------------------------------------------------------------
    def _build_settings_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.memory_field, self.tin_field, self.branch_field, self.url_field = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.url_field.setLayoutDirection(Qt.LeftToRight)
        self.key_field, self.cert_field = QLineEdit(), QLineEdit()
        for field in (self.key_field, self.cert_field):
            field.setReadOnly(True)
            field.setPlaceholderText("فایلی انتخاب نشده")
        key_row, cert_row = QHBoxLayout(), QHBoxLayout()
        for row_layout, field, title in ((key_row, self.key_field, "انتخاب فایل کلید خصوصی"),
                                         (cert_row, self.cert_field, "انتخاب فایل گواهی امضا")):
            button = _btn(title, "📂")
            button.clicked.connect(lambda _checked=False, f=field, t=title: self._pick(f, t))
            row_layout.addWidget(field, 1)
            row_layout.addWidget(button)
        key_box, cert_box = QWidget(), QWidget()
        key_box.setLayout(key_row)
        cert_box.setLayout(cert_row)
        grid = FieldGrid([
            FieldSpec("memory_id", "شناسهٔ یکتای حافظهٔ مالیاتی", self.memory_field, span=1),
            FieldSpec("seller_tin", "شمارهٔ اقتصادی فروشنده", self.tin_field, span=1),
            FieldSpec("branch_code", "کد شعبه (اختیاری)", self.branch_field, span=1),
            FieldSpec("api_url", "آدرس سامانه", self.url_field, span=3),
            FieldSpec("private_key", "کلید خصوصی (PEM)", key_box, span=3),
            FieldSpec("certificate", "گواهی امضا (PEM)", cert_box, span=3),
        ])
        layout.addWidget(grid)
        self.credentials_label = QLabel("")
        layout.addWidget(self.credentials_label)
        save = _btn("ذخیرهٔ تنظیمات مودیان", "💾", "primary")
        save.clicked.connect(self.save_settings)
        layout.addWidget(save)
        units_title = QLabel("کد واحدهای سنجش در سامانهٔ مودیان")
        units_title.setObjectName("sectionTitle")
        layout.addWidget(units_title)
        self.units_table = table(["کد", "نام واحد", "کد واحد مودیان"])
        self.units_table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        layout.addWidget(self.units_table, 1)
        save_units = _btn("ذخیرهٔ کد واحدها", "💾")
        save_units.clicked.connect(self.save_units)
        layout.addWidget(save_units)
        self.settings_status = QLabel("")
        self.settings_status.setWordWrap(True)
        layout.addWidget(self.settings_status)
        return tab

    def _pick(self, field: QLineEdit, title: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, title, "", "PEM (*.pem *.key *.crt *.cer);;همهٔ فایل‌ها (*)")
        if path:
            field.setText(path)

    def load_settings(self) -> None:
        settings = moadian_service.get_settings(company_id())
        self.memory_field.setText(settings.memory_id)
        self.tin_field.setText(settings.seller_tin)
        self.branch_field.setText(settings.branch_code)
        self.url_field.setText(settings.api_url)
        self.key_field.clear()
        self.cert_field.clear()
        self.credentials_label.setText("کلید و گواهی امضا ثبت شده است؛ برای تعویض، فایل‌های جدید را انتخاب کنید."
                                       if settings.has_credentials else "کلید و گواهی امضا هنوز ثبت نشده است.")
        self.units = catalog_service.list_uoms(company_id(), active_only=True)
        fill(self.units_table, [[u.code, u.name, ""] for u in self.units], [u.uom_id for u in self.units])
        for index, unit in enumerate(self.units):
            for col in (0, 1):
                item = self.units_table.item(index, col)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.units_table.setItem(index, 2, QTableWidgetItem(unit.moadian_unit_code or ""))

    def save_settings(self) -> None:
        try:
            key_pem = cert_pem = None
            if self.key_field.text() or self.cert_field.text():
                if not (self.key_field.text() and self.cert_field.text()):
                    raise ValueError("کلید خصوصی و گواهی را با هم انتخاب کنید.")
                with open(self.key_field.text(), encoding="utf-8") as handle:
                    key_pem = handle.read()
                with open(self.cert_field.text(), encoding="utf-8") as handle:
                    cert_pem = handle.read()
            moadian_service.save_settings(company_id(), self.memory_field.text(), self.tin_field.text(),
                                          self.branch_field.text(), self.url_field.text(), key_pem, cert_pem)
        except (OSError, UnicodeDecodeError) as exc:
            theme.set_status_label(self.settings_status, f"فایل خوانده نشد: {exc}", ok=False)
            return
        except ValueError as exc:
            theme.set_status_label(self.settings_status, str(exc), ok=False)
            return
        self.load_settings()
        theme.set_status_label(self.settings_status, "تنظیمات مودیان ذخیره شد.", ok=True)

    def save_units(self) -> None:
        try:
            for index, unit in enumerate(self.units):
                item = self.units_table.item(index, 2)
                code = numerals.to_ascii_digits(item.text().strip()) if item else ""
                if (unit.moadian_unit_code or "") != code:
                    catalog_service.set_uom_moadian_code(unit.uom_id, company_id(), code)
        except ValueError as exc:
            theme.set_status_label(self.settings_status, str(exc), ok=False)
            return
        self.load_settings()
        theme.set_status_label(self.settings_status, "کد واحدها ذخیره شد.", ok=True)
