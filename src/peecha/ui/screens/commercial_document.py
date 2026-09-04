"""فرمِ اسنادِ بازرگانی — سفارش/فاکتور/برگشت (خرید و فروش)، همه رویِ
همان اسکلتِ سرِسند+ردیفِ واحدِ comm.commercial_documents/commercial_document_lines
(services/commercial_documents.py).

طبقِ اسکوپِ آگاهانهٔ این دور: تبدیلِ واحد (هر ردیف با واحدِ پایهٔ کالا)،
بچ/سریال، نمایندهٔ فروش/کمیسیون، و بُعدِ مرکزِ هزینه/پروژه رویِ سرِسند،
به دورهایِ بعدی موکول شده‌اند."""

from __future__ import annotations

import datetime
import decimal
import os
import tempfile

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session as app_session
from peecha.reporting import jasper_bridge
from peecha.services import chart_of_accounts as coa_service
from peecha.services import commercial_consignment as consignment_service
from peecha.services import commercial_credit as credit_service
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_partners as partners_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import commercial_purchasing as purchasing_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import companies as companies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_engine as engine_service
from peecha.services import inventory_documents as inv_documents_service
from peecha.services import inventory_locations as locations_service
from peecha.services import report_templates as report_templates_service
from peecha.services import sales_assistant as assistant_service
from peecha.services import treasury as treasury_service
from peecha.ui import theme
from peecha.ui.screens.inventory_document import _enter_signal
from peecha.ui.screens.jasper_preview import JasperReportPreviewDialog
from peecha.ui.screens.journal_entry import _AmountField, _fill_options, _make_searchable_combo
from peecha.ui.screens.report_template_settings import pick_report_template
from peecha.ui.screens.treasury_voucher import (
    _EnterComboBox,
    _escape_receipt_html,
    _print_receipt_document,
    _receipt_font_family,
)
from peecha.ui.widgets import (
    FieldGrid,
    FieldHelpMixin,
    FieldSpec,
    FormScreenBase,
    JalaliDateEdit,
    LayoutEditMixin,
    SectionStepper,
    SummaryCard,
    SummaryCardBar,
    add_quick_add_button,
)

DOC_TYPE_TITLES = {
    "SALES_ORDER": "سفارشِ فروش",
    "SALES_PROFORMA": "پیش‌فاکتورِ فروش",
    "SALES_INVOICE": "فاکتورِ فروش",
    "SALES_RETURN": "برگشت از فروش",
    "PURCHASE_ORDER": "سفارشِ خرید",
    "PURCHASE_PROFORMA": "پیش‌فاکتورِ خرید",
    "PURCHASE_INVOICE": "فاکتورِ خرید",
    "PURCHASE_RETURN": "برگشت به تامین‌کننده",
    # طبقِ درخواستِ صریح («فاکتورِ امانی -- هردو جهت»): امانیِ خروجی
    # (کالایِ خودمان نزدِ نماینده/مشتری تا فروش) و امانیِ ورودی (کالایِ
    # تامین‌کننده نزدِ ما تا مصرف/فروش) -- خودِ سند بدونِ اثرِ حسابداری،
    # تسویه از طریقِ همان دکمه‌یِ «تبدیل به فاکتور».
    "CONSIGNMENT_OUT": "امانیِ خروجی",
    "CONSIGNMENT_IN": "امانیِ ورودی",
}
STATUS_LABELS = {
    "DRAFT": "پیش‌نویس", "CONFIRMED": "تاییدشده", "APPROVED": "تصویب‌شده", "POSTED": "ثبتِ‌نهایی‌شده",
    "CANCELLED": "لغوشده", "CORRECTED": "اصلاح‌شده",
}
# امانیِ خروجی از نظرِ طرفِ‌حساب (مشتری/نماینده) و کانالِ فروش، هم‌الگویِ
# اسنادِ فروش است.
_SALES_TYPES = ("SALES_ORDER", "SALES_PROFORMA", "SALES_INVOICE", "SALES_RETURN", "CONSIGNMENT_OUT")
# طبقِ درخواستِ صریح («سفارش/پیش‌فاکتور بتواند به فاکتور تبدیل شود»):
# امانیِ خروجی/ورودی هم از همین مکانیزم (تبدیلِ مرحله‌ایِ مانده به فاکتورِ
# واقعیِ فروش/خرید) استفاده می‌کنند.
_CONVERTIBLE_TO_INVOICE_TYPES = (
    "SALES_ORDER", "SALES_PROFORMA", "PURCHASE_ORDER", "PURCHASE_PROFORMA", "CONSIGNMENT_OUT", "CONSIGNMENT_IN",
)
# طبقِ همان تفکیک: کدام از انواعِ قابلِ‌تبدیل به فاکتورِ فروش تبدیل
# می‌شوند (بقیه به فاکتورِ خرید) -- برایِ عنوانِ پیامِ موفقیتِ تبدیل.
_CONVERTS_TO_SALES_INVOICE = ("SALES_ORDER", "SALES_PROFORMA", "CONSIGNMENT_OUT")
_LINE_COLUMNS = ["کالا", "مقدار", "بهایِ واحد", "تخفیف", "درصدِ مالیات", "مالیات", "جمعِ ردیف", "توضیح"]
_HISTORY_COLUMNS = ["نوع", "شماره", "تاریخ", "وضعیت", "جمعِ کل"]


# طبقِ درخواستِ صریح («به‌جایِ خلاصهٔ فاکتور، پرینتِ فاکتور را نمایش
# بده»): چون «خلاصه»یِ متنیِ قبلی اطلاعاتِ به‌دردبخوری نداشت، این‌جا به‌جایِ
# آن، از همان زیرساختِ چاپِ HTML/QPrintPreviewDialogِ رسیدِ دریافت‌وپرداخت
# (treasury_voucher.py) -- که از پیش جواب داده -- برایِ ساختِ یک پیش‌نمایشِ
# چاپیِ کاملِ سند (هدر + جدولِ ردیف‌ها + جمعِ کل) استفاده می‌شود.
def _build_invoice_print_html(
    company_name: str, doc, lines: list, items_by_id: dict, counterparty_label: str, decimal_places: int,
    font_family: str,
) -> str:
    esc = _escape_receipt_html
    rows_html = ""
    for ln in lines:
        item = items_by_id.get(ln.item_id)
        item_label = f"{item.code} — {item.name or ''}" if item else str(ln.item_id)
        rows_html += (
            "<tr>"
            f"<td>{esc(item_label)}</td>"
            f"<td style='text-align:center;'>{numerals.format_money(ln.quantity, 3)}</td>"
            f"<td style='text-align:center;'>{numerals.format_money(ln.unit_price, decimal_places)}</td>"
            f"<td style='text-align:center;'>{numerals.format_money(ln.discount_amount, decimal_places)}</td>"
            f"<td style='text-align:center;'>{numerals.format_money(ln.tax_amount, decimal_places)}</td>"
            f"<td style='text-align:center;'>{numerals.format_money(ln.line_total, decimal_places)}</td>"
            "</tr>"
        )
    total = doc.subtotal_amount - doc.discount_amount + doc.tax_amount
    return f"""
    <html dir="rtl"><head><meta charset="utf-8"></head>
    <body style="font-family:'{font_family}', Tahoma, sans-serif; font-size:11pt;">
      <div style="text-align:center; font-size:13pt; font-weight:bold;">{esc(company_name)}</div>
      <div style="text-align:center; font-size:12pt; font-weight:bold; margin:6px 0 16px 0;">
        {esc(DOC_TYPE_TITLES.get(doc.document_type_code, doc.document_type_code))}
      </div>
      <table width="100%" style="margin-bottom:12px;">
        <tr>
          <td>شماره‌یِ سند: {numerals.to_persian_digits(str(doc.document_no))}</td>
          <td style="text-align:center;">تاریخ: {numerals.format_jalali_date(doc.document_date)}</td>
          <td style="text-align:left;">طرفِ‌حساب: {esc(counterparty_label)}</td>
        </tr>
      </table>
      <table width="100%" border="1" cellspacing="0" cellpadding="6" style="border-collapse:collapse;">
        <tr style="background:#eee; font-weight:bold;">
          <td>کالا</td><td>مقدار</td><td>بهایِ واحد</td><td>تخفیف</td><td>مالیات</td><td>جمعِ ردیف</td>
        </tr>
        {rows_html}
      </table>
      <div style="text-align:left; margin-top:12px; font-weight:bold;">
        جمعِ کل: {numerals.format_money(total, decimal_places)}
      </div>
    </body></html>
    """


def _score_gradient_color(score: int) -> str:
    """طبقِ درخواستِ صریح («فیلدِ مشتری بر اساسِ امتیاز رنگ‌آمیزی شود --
    از قرمز تا سبز»): امتیازِ ۰ تا ۱۰۰ را به یک رنگِ پیوسته (قرمز →
    زرد → سبز، مثلِ چراغ‌راهنما) تبدیل می‌کند -- مستقل از قالبِ روشن/
    تیره، چون این رنگ همیشه باید همان معنایِ «خطر/میانه/خوب» را برساند."""
    score = max(0, min(100, score))
    if score <= 50:
        ratio = score / 50
        r1, g1, b1 = 220, 38, 38  # قرمز
        r2, g2, b2 = 234, 179, 8  # زرد
    else:
        ratio = (score - 50) / 50
        r1, g1, b1 = 234, 179, 8  # زرد
        r2, g2, b2 = 22, 163, 74  # سبز
    r = round(r1 + (r2 - r1) * ratio)
    g = round(g1 + (g2 - g1) * ratio)
    b = round(b1 + (b2 - b1) * ratio)
    return f"#{r:02x}{g:02x}{b:02x}"


def _money_or_blank(value: decimal.Decimal | None, decimal_places: int) -> str:
    return numerals.format_money(value, decimal_places) if value else ""


def _build_invoice_print_rows_and_params(company_id: int, doc, lines: list) -> tuple[list[dict], dict]:
    """طبقِ درخواستِ صریح («طراحیِ فاکتورِ حرفه‌ای»): دیتایِ کاملِ سند --
    اطلاعاتِ شرکت (شناسه‌یِ ملی/کدِ اقتصادی)، اطلاعاتِ کاملِ طرفِ‌حساب
    (تلفن/موبایل/آدرس)، واحدِ شمارشِ هر ردیف، و جمعِ کل (شاملِ هزینه‌یِ
    حمل -- که در نسخه‌یِ قبلیِ HTML سهواً از جمعِ چاپی جا افتاده بود) --
    برایِ قالبِ templates/invoice.jrxml آماده می‌کند."""
    decimal_places = companies_service.get_base_currency_decimal_places(company_id)
    company = companies_service.get_company_model(company_id)
    company_ids_parts = []
    if company.national_id:
        company_ids_parts.append(f"شناسه‌یِ ملی: {numerals.to_persian_digits(company.national_id)}")
    if company.economic_code:
        company_ids_parts.append(f"کدِ اقتصادی: {numerals.to_persian_digits(company.economic_code)}")
    if company.registration_no:
        company_ids_parts.append(f"شماره‌یِ ثبت: {numerals.to_persian_digits(company.registration_no)}")

    is_customer_side = doc.document_type_code in _SALES_TYPES
    party_rows = dimensions_service.list_customers(company_id) if is_customer_side else dimensions_service.list_suppliers(company_id)
    party_detail = next((p for p in party_rows if p["detail_account_id"] == doc.counterparty_detail_account_id), None)
    counterparty_label = dimensions_service.get_detail_account_label(doc.counterparty_detail_account_id)
    counterparty_ids_parts = []
    if party_detail and party_detail.get("national_id"):
        counterparty_ids_parts.append(f"شناسه‌یِ ملی: {numerals.to_persian_digits(party_detail['national_id'])}")
    if party_detail and party_detail.get("economic_code"):
        counterparty_ids_parts.append(f"کدِ اقتصادی: {numerals.to_persian_digits(party_detail['economic_code'])}")
    counterparty_contact_parts = []
    if party_detail and party_detail.get("phone"):
        counterparty_contact_parts.append(f"تلفن: {numerals.to_persian_digits(party_detail['phone'])}")
    if party_detail and party_detail.get("mobile"):
        counterparty_contact_parts.append(f"موبایل: {numerals.to_persian_digits(party_detail['mobile'])}")

    warehouse_name = ""
    if doc.warehouse_id:
        warehouse = next((w for w in locations_service.list_warehouses(company_id) if w.warehouse_id == doc.warehouse_id), None)
        warehouse_name = warehouse.name if warehouse else ""

    items_by_id = {it.item_id: it for it in catalog_service.list_items(company_id)}
    uoms_by_id = {u.uom_id: u for u in catalog_service.list_uoms(company_id)}
    warehouses_by_id = {w.warehouse_id: w.name for w in locations_service.list_warehouses(company_id)}

    # طبقِ درخواستِ صریح («همه‌یِ فیلدهایِ ممکن در گزارش باشند، حتی اگر
    # فعلاً در چیدمان استفاده نشوند»): فیلدها/پارامترهایِ زیر عمداً در
    # جدولِ ردیف‌ها/سرِسندِ فعلیِ invoice.jrxml چیده نشده‌اند، ولی چون در
    # لیستِ Fields/Parametersِ Studio ظاهر می‌شوند، کاربر می‌تواند خودش
    # با Drag & Drop هرکدام را به گزارش اضافه کند، بدونِ نیاز به کدنویسیِ
    # جدید.
    print_rows = []
    for row_no, ln in enumerate(lines, start=1):
        item = items_by_id.get(ln.item_id)
        item_label = f"{item.code} — {item.name or ''}" if item else str(ln.item_id)
        if ln.description:
            item_label = f"{item_label} — {ln.description}"
        uom = uoms_by_id.get(ln.uom_id)
        print_rows.append({
            "row_no_display": numerals.to_persian_digits(str(row_no)),
            "item_label": item_label,
            "uom_display": uom.name if uom else "",
            "quantity_display": numerals.format_money(ln.quantity, uom.decimal_places if uom else 2),
            "unit_price_display": numerals.format_money(ln.unit_price, decimal_places),
            "discount_display": _money_or_blank(ln.discount_amount, decimal_places),
            "tax_display": _money_or_blank(ln.tax_amount, decimal_places),
            "line_total_display": numerals.format_money(ln.line_total, decimal_places),
            # فیلدهایِ اضافیِ در دسترس (فعلاً در چیدمان استفاده نشده):
            "item_code": item.code if item else "",
            "item_name": item.name or "" if item else "",
            "line_description": ln.description or "",
            "discount_percent_display": numerals.format_money(ln.discount_percent, 2) if ln.discount_percent else "",
            "tax_percent_display": numerals.format_money(ln.tax_percent, 2) if ln.tax_percent else "",
            "line_warehouse_name": warehouses_by_id.get(ln.warehouse_id, "") if ln.warehouse_id else "",
        })

    params = {
        "companyDisplayName": app_session.current_company.display_name if app_session.current_company else "",
        "companyLegalName": company.legal_name or "",
        "companyIdsLine": "  —  ".join(company_ids_parts),
        "documentTypeLabel": DOC_TYPE_TITLES.get(doc.document_type_code, doc.document_type_code),
        "documentNoDisplay": numerals.to_persian_digits(str(doc.document_no)),
        "documentDateDisplay": numerals.format_jalali_date(doc.document_date),
        "dueDateDisplay": numerals.format_jalali_date(doc.due_date) if doc.due_date else "—",
        "referenceNo": doc.reference_no or "",
        "statusLabel": STATUS_LABELS.get(doc.status_code, doc.status_code),
        "warehouseName": warehouse_name,
        "counterpartyLabel": counterparty_label,
        "counterpartyIdsLine": "  —  ".join(counterparty_ids_parts),
        "counterpartyContactLine": "  —  ".join(counterparty_contact_parts),
        "counterpartyAddress": (party_detail.get("address") or "") if party_detail else "",
        "headerDescription": doc.description or "",
        "subtotalDisplay": numerals.format_money(doc.subtotal_amount, decimal_places),
        "discountDisplay": _money_or_blank(doc.discount_amount, decimal_places),
        "taxDisplay": _money_or_blank(doc.tax_amount, decimal_places),
        "shippingDisplay": _money_or_blank(doc.shipping_amount, decimal_places),
        "totalDisplay": numerals.format_money(doc.total_amount, decimal_places),
        "totalInWordsDisplay": numerals.amount_to_words(doc.total_amount),
        "generatedAt": numerals.format_jalali_datetime(datetime.datetime.now()),
        # پارامترهایِ اضافیِ در دسترس (فعلاً در چیدمان استفاده نشده --
        # همان توضیحِ بالایِ حلقه‌یِ ردیف‌ها):
        "companyNationalId": numerals.to_persian_digits(company.national_id) if company.national_id else "",
        "companyEconomicCode": numerals.to_persian_digits(company.economic_code) if company.economic_code else "",
        "companyRegistrationNo": numerals.to_persian_digits(company.registration_no) if company.registration_no else "",
        "counterpartyPhone": numerals.to_persian_digits(party_detail["phone"]) if party_detail and party_detail.get("phone") else "",
        "counterpartyMobile": numerals.to_persian_digits(party_detail["mobile"]) if party_detail and party_detail.get("mobile") else "",
        "counterpartyNationalId": numerals.to_persian_digits(party_detail["national_id"]) if party_detail and party_detail.get("national_id") else "",
        "counterpartyEconomicCode": numerals.to_persian_digits(party_detail["economic_code"]) if party_detail and party_detail.get("economic_code") else "",
        "counterpartyCreditLimitDisplay": (
            numerals.format_money(party_detail["credit_limit"], decimal_places)
            if is_customer_side and party_detail and party_detail.get("credit_limit") else ""
        ),
        "counterpartyBankAccountNo": (
            numerals.to_persian_digits(party_detail["bank_account_no"])
            if not is_customer_side and party_detail and party_detail.get("bank_account_no") else ""
        ),
        "counterpartyNotes": (party_detail.get("notes") or "") if party_detail else "",
    }
    return print_rows, params


def _show_invoice_print(
    parent: QWidget,
    company_id: int,
    document_id: int,
    counterparty_label: str | None = None,
    jrxml_path=None,
) -> None:
    doc, lines = documents_service.get_document(document_id, company_id)

    if jasper_bridge.is_available():
        # طبقِ رجیستریِ گزارش‌هایِ حرفه‌ای: اگر مسیرِ صریحی داده نشده
        # (مثلاً از دکمه‌یِ «📄 گزارش»ِ خودِ فرم)، گزارشِ پیش‌فرضِ همین
        # شرکت برایِ فاکتور استفاده می‌شود، وگرنه قالبِ پایه‌یِ داخلِ ریپازیتوری.
        if jrxml_path is None:
            jrxml_path = report_templates_service.get_default_template_path(company_id, "COMMERCIAL_INVOICE")
        if jrxml_path is None:
            jrxml_path = jasper_bridge.template_path("invoice.jrxml")
        print_rows, params = _build_invoice_print_rows_and_params(company_id, doc, lines)
        if counterparty_label is not None:
            params["counterpartyLabel"] = counterparty_label
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix="peecha_invoice_")
            os.close(fd)
            jasper_bridge.render_report_at_path(jrxml_path, print_rows, params, tmp_path, "pdf")
            dialog = JasperReportPreviewDialog(parent, jrxml_path, print_rows, params, "فاکتور", title="پیش‌نمایشِ فاکتور", pdf_path=tmp_path)
            dialog.exec()
            return
        except Exception as exc:
            QMessageBox.warning(
                parent, "چاپِ حرفه‌ای",
                f"ساختِ فاکتورِ حرفه‌ای ناموفق بود؛ نسخه‌یِ ساده نمایش داده می‌شود.\n{exc}",
            )

    # طبقِ حفظِ سازگاری: اگر موتورِ چاپِ حرفه‌ای هنوز build نشده (یا خطا
    # داد)، همان پیش‌نمایشِ HTMLِ ساده -- که قبلاً کار می‌کرد -- جایگزین
    # می‌شود؛ چاپِ فاکتور نباید برایِ کاربرانِ بدونِ Java کاملاً از کار بیفتد.
    decimal_places = companies_service.get_base_currency_decimal_places(company_id)
    if counterparty_label is None:
        counterparty_label = dimensions_service.get_detail_account_label(doc.counterparty_detail_account_id)
    company_name = app_session.current_company.display_name if app_session.current_company else ""
    items_by_id = {it.item_id: it for it in catalog_service.list_items(company_id)}
    html = _build_invoice_print_html(
        company_name, doc, lines, items_by_id, counterparty_label, decimal_places, _receipt_font_family(),
    )
    _print_receipt_document(parent, html)


class _CounterpartyHistoryDialog(QDialog):
    """طبقِ درخواستِ صریح: مثلاً ۱۰ فاکتورِ آخرِ طرفِ‌حساب -- با تعدادِ
    ردیفِ قابلِ‌تنظیم. دابل‌کلیک رویِ هر ردیف، خلاصهٔ همان سند را نمایش
    می‌دهد -- طبقِ رفعِ باگِ واقعی، ناوبریِ مستقیم به آن سند از این‌جا
    عمداً حذف شده، چون آن صفحه (به‌ازایِ هر نوعِ سند) نمونه‌یِ واحد و
    مشترکِ همه‌جایِ برنامه است و چنین ناوبری‌ای هر ویرایشِ درحال‌انجامِ
    کاربر رویِ همان صفحه را پاک می‌کرد."""

    def __init__(self, parent: QWidget, company_id: int, counterparty_id: int, counterparty_label: str) -> None:
        super().__init__(parent)
        self._company_id = company_id
        self._counterparty_id = counterparty_id
        self._counterparty_label = counterparty_label
        self.setWindowTitle(f"آخرین اسنادِ «{counterparty_label}»")
        self.setMinimumWidth(600)
        self.setMinimumHeight(420)
        layout = QVBoxLayout(self)

        count_row = QHBoxLayout()
        count_row.addWidget(QLabel("تعدادِ ردیفِ نمایش‌داده‌شده:"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 500)
        self.count_spin.setValue(10)
        self.count_spin.valueChanged.connect(self._refresh)
        count_row.addWidget(self.count_spin)
        count_row.addStretch(1)
        layout.addLayout(count_row)

        self.table = QTableWidget(0, len(_HISTORY_COLUMNS))
        self.table.setHorizontalHeaderLabels(_HISTORY_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self._open_selected)
        layout.addWidget(self.table, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._documents: list = []
        self._refresh()

    def _refresh(self) -> None:
        self._documents = documents_service.list_documents(
            self._company_id, counterparty_detail_account_id=self._counterparty_id, limit=self.count_spin.value(),
        )
        decimal_places = companies_service.get_base_currency_decimal_places(self._company_id)
        self.table.setRowCount(len(self._documents))
        for row_index, doc in enumerate(self._documents):
            total = doc.subtotal_amount - doc.discount_amount + doc.tax_amount
            values = [
                DOC_TYPE_TITLES.get(doc.document_type_code, doc.document_type_code),
                numerals.to_persian_digits(str(doc.document_no)),
                numerals.format_jalali_date(doc.document_date),
                STATUS_LABELS.get(doc.status_code, doc.status_code),
                numerals.format_money(total, decimal_places),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, doc.document_id)
                self.table.setItem(row_index, col_index, item)
        self.table.resizeRowsToContents()

    def _open_selected(self, row: int, _column: int) -> None:
        # طبقِ رفعِ باگِ واقعیِ گزارش‌شده («سندِ بازِ فعلی پاک و با سندِ
        # کلیک‌شده جایگزین می‌شود»): چون این صفحه‌هایِ سند (به‌ازایِ هر
        # نوع) نمونه‌یِ واحد و مشترک‌اند، ناوبریِ مستقیم به آن‌ها از اینجا
        # هر ویرایشِ درحالِ‌انجامِ کاربر رویِ همان صفحه را پاک می‌کرد --
        # به‌جایش، طبقِ درخواستِ صریح («خلاصه اطلاعاتِ به‌دردبخوری نداره،
        # پرینتِ فاکتور را نشان بده»)، پیش‌نمایشِ چاپیِ کاملِ سند باز می‌شود.
        doc = self._documents[row]
        _show_invoice_print(self, self._company_id, doc.document_id, self._counterparty_label)


_PRICE_HISTORY_COLUMNS = ["نوع", "شماره", "تاریخ", "بهایِ واحد"]


class _ItemPriceHistoryDialog(QDialog):
    """طبقِ درخواستِ صریح: ۱۰ قیمتِ آخرِ این کالا به همین طرفِ‌حساب --
    با کلیک رویِ هر ردیف، خلاصهٔ همان سند نمایش داده می‌شود (بدونِ
    بستنِ خودِ دیالوگِ ردیف که این پنجره از آن باز شده)."""

    def __init__(self, parent: QWidget, company_id: int, item_id: int, counterparty_id: int, item_label: str) -> None:
        super().__init__(parent)
        self._company_id = company_id
        self._decimal_places = companies_service.get_base_currency_decimal_places(company_id)
        self.setWindowTitle(f"قیمت‌هایِ قبلیِ «{item_label}»")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)

        self._rows = documents_service.list_item_price_history(company_id, item_id, counterparty_id)
        if not self._rows:
            layout.addWidget(QLabel("برایِ این کالا و این طرفِ‌حساب هنوز سابقه‌یِ قیمتی ثبت نشده است."))

        self.table = QTableWidget(0, len(_PRICE_HISTORY_COLUMNS))
        self.table.setHorizontalHeaderLabels(_PRICE_HISTORY_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.cellDoubleClicked.connect(self._show_summary)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(QLabel("برایِ دیدنِ خلاصهٔ سند، رویِ ردیفِ موردِنظر دابل‌کلیک کنید."))

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.table.setRowCount(len(self._rows))
        for row_index, row in enumerate(self._rows):
            values = [
                DOC_TYPE_TITLES.get(row.document_type_code, row.document_type_code),
                numerals.to_persian_digits(str(row.document_no)),
                numerals.format_jalali_date(row.document_date),
                numerals.format_money(row.unit_price, self._decimal_places),
            ]
            for col_index, value in enumerate(values):
                self.table.setItem(row_index, col_index, QTableWidgetItem(value))
        self.table.resizeRowsToContents()

    def _show_summary(self, row: int, _column: int) -> None:
        # طبقِ درخواستِ صریح («خلاصه اطلاعاتِ به‌دردبخوری نداره، پرینتِ
        # فاکتور را نشان بده»).
        history_row = self._rows[row]
        _show_invoice_print(self, self._company_id, history_row.document_id)


class _LineDialog(LayoutEditMixin, QDialog):
    def __init__(
        self, parent: QWidget, items: list[catalog_service.ItemRow], company_id: int, main_window,
        decimal_places: int, initial: dict | None = None, *, counterparty_id: int | None = None,
        price_list_id: int | None = None, document_type_code: str | None = None,
        document_date: datetime.date | None = None, warehouses: list | None = None,
        default_warehouse_id: int | None = None, per_line_warehouse_enabled: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ردیفِ سند")
        self.setMinimumWidth(380)
        self._company_id = company_id
        self._counterparty_id = counterparty_id
        self._price_list_id = price_list_id
        self._document_type_code = document_type_code
        self._document_date = document_date
        self._main_window = main_window
        self._decimal_places = decimal_places
        self._uom_decimal_places = {u.uom_id: u.decimal_places for u in catalog_service.list_uoms(company_id)}
        layout = QVBoxLayout(self)
        self._items_by_id = {it.item_id: it for it in items}

        item_options = [(it.item_id, f"{it.code} — {it.name or ''}") for it in items]
        item_row_widget = QWidget()
        item_row_layout = QHBoxLayout(item_row_widget)
        item_row_layout.setContentsMargins(0, 0, 0, 0)
        item_row_layout.setSpacing(3)
        self.item_combo = _make_searchable_combo(item_options)
        item_row_layout.addWidget(self.item_combo, stretch=1)
        add_quick_add_button(item_row_layout, self.item_combo, main_window, "GL_DIM", "تعریفِ کالایِ تازه")

        stock_row_widget = QWidget()
        stock_row_layout = QHBoxLayout(stock_row_widget)
        stock_row_layout.setContentsMargins(0, 0, 0, 0)
        self.stock_info_label = QLabel("")
        self.stock_info_label.setWordWrap(True)
        stock_row_layout.addWidget(self.stock_info_label, stretch=1)
        self.kardex_button = QPushButton("📇 کاردکس")
        self.kardex_button.setObjectName("flatButton")
        self.kardex_button.setEnabled(False)
        self.kardex_button.clicked.connect(self._open_kardex)
        stock_row_layout.addWidget(self.kardex_button)
        self.price_history_button = QPushButton("🕘 قیمت‌هایِ قبلی")
        self.price_history_button.setObjectName("flatButton")
        self.price_history_button.setEnabled(False)
        self.price_history_button.setToolTip("۱۰ قیمتِ آخرِ این کالا به همین طرفِ‌حساب")
        self.price_history_button.clicked.connect(self._open_price_history)
        stock_row_layout.addWidget(self.price_history_button)

        # طبقِ سندِ راهنمایِ UI/UX (بخشِ ۶.۲/۶.۳): فیلدهایِ مبلغ/عدد باید
        # _AmountField باشند (گروه‌بندیِ سه‌رقمیِ زنده + ارقامِ فارسی)، نه
        # QDoubleSpinBoxِ خام — دقیقاً هم‌الگو با journal_entry.py/
        # treasury_voucher.py/treasury_petty_cash.py.
        self.quantity_field = _AmountField()
        self.quantity_field.setDecimals(3)

        self.unit_price_field = _AmountField()
        self.unit_price_field.setDecimals(decimal_places)

        # طبقِ درخواستِ صریح («تخفیف روی ردیف کالا فقط مبلغی است، باید
        # درصدی هم باشد»): یک کمبویِ نوعِ تخفیف کنارِ همان فیلدِ عددیِ
        # قبلی — عددِ واردشده بسته به نوعِ انتخاب‌شده، یا مبلغِ مستقیمِ
        # تخفیف است یا درصدِ آن (که خودِ commercial_documents.add_line
        # رویِ جمعِ ناخالصِ همین ردیف حساب می‌کند، دقیقاً هم‌الگو با
        # tax_percent).
        self.discount_field = _AmountField()
        self.discount_field.setDecimals(decimal_places)
        self.discount_type_combo = _EnterComboBox()
        self.discount_type_combo.addItem("مبلغی", "AMOUNT")
        self.discount_type_combo.addItem("درصدی", "PERCENT")
        self.discount_type_combo.setMaximumWidth(80)
        discount_row_widget = QWidget()
        discount_row_layout = QHBoxLayout(discount_row_widget)
        discount_row_layout.setContentsMargins(0, 0, 0, 0)
        discount_row_layout.setSpacing(3)
        discount_row_layout.addWidget(self.discount_field, stretch=1)
        discount_row_layout.addWidget(self.discount_type_combo)

        self.tax_percent_field = _AmountField()
        self.tax_percent_field.setDecimals(2)

        self.description_field = QLineEdit()

        # طبقِ درخواستِ صریح («کالایِ ردیف بتواند انبارِ مستقل از هدر داشته
        # باشد») — Toggleِ اختیاریِ PER_LINE_WAREHOUSE؛ وقتی خاموش است این
        # فیلد اصلاً ساخته/نمایش داده نمی‌شود (رفتارِ قدیم بدونِ تغییر).
        self._per_line_warehouse_enabled = per_line_warehouse_enabled
        self.warehouse_combo: _EnterComboBox | None = None
        field_specs = [
            FieldSpec("item", "کالا", item_row_widget, span=2),
            FieldSpec("stock_info", "", stock_row_widget, span=3),
            FieldSpec("quantity", "مقدار (واحدِ پایهٔ کالا)", self.quantity_field, span=1),
            FieldSpec("unit_price", "بهایِ واحد (پیشنهادی از فهرستِ قیمت — قابلِ‌ویرایش)", self.unit_price_field, span=1),
            FieldSpec("discount", "تخفیف", discount_row_widget, span=1),
            FieldSpec("tax_percent", "درصدِ مالیات (بعدِ تخفیف)", self.tax_percent_field, span=1),
        ]
        if per_line_warehouse_enabled:
            warehouse_row_widget = QWidget()
            warehouse_row_layout = QHBoxLayout(warehouse_row_widget)
            warehouse_row_layout.setContentsMargins(0, 0, 0, 0)
            warehouse_row_layout.setSpacing(3)
            self.warehouse_combo = _EnterComboBox()
            self.warehouse_combo.addItem("(انبارِ پیش‌فرضِ سند)", None)
            for w in warehouses or []:
                self.warehouse_combo.addItem(f"{w.code} — {w.name}", w.warehouse_id)
            if default_warehouse_id is not None:
                index = self.warehouse_combo.findData(default_warehouse_id)
                if index >= 0:
                    self.warehouse_combo.setCurrentIndex(index)
            warehouse_row_layout.addWidget(self.warehouse_combo, stretch=1)
            add_quick_add_button(warehouse_row_layout, self.warehouse_combo, main_window, "INV_WAREHOUSES", "تعریفِ انبارِ تازه")
            field_specs.append(FieldSpec("warehouse", "انبار", warehouse_row_widget, span=1))
        field_specs.append(FieldSpec("description", "توضیح", self.description_field, span=3))

        self.fields_grid = FieldGrid(field_specs)
        layout.addWidget(self.fields_grid)
        self.register_field_grids("commercial_document_line", [self.fields_grid])

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        # طبقِ بررسیِ عملی (هم‌الگو با treasury_voucher.py — این‌جا با
        # QTestِ واقعی دوباره تاییدشد): setAutoDefault(False) به‌تنهایی
        # کافی نیست، چون QDialogButtonBox با هر show() دوباره دکمه‌یِ
        # نقشِ AcceptRole را default (isDefault=True) می‌کند، جدا از
        # پرچمِ autoDefault؛ جلوگیریِ واقعی در keyPressEvent پایین‌تر است.
        buttons.button(QDialogButtonBox.Ok).setAutoDefault(False)
        buttons.button(QDialogButtonBox.Cancel).setAutoDefault(False)
        layout.addWidget(buttons)

        # طبقِ سندِ راهنما (زنجیره‌یِ کاملِ Enter، بدونِ استثنا).
        enter_chain = [
            self.item_combo, self.quantity_field, self.unit_price_field,
            self.discount_field, self.discount_type_combo, self.tax_percent_field,
        ]
        if self.warehouse_combo is not None:
            enter_chain.append(self.warehouse_combo)
        enter_chain.append(self.description_field)
        for widget, next_widget in zip(enter_chain, enter_chain[1:]):
            _enter_signal(widget).connect(next_widget.setFocus)
        _enter_signal(enter_chain[-1]).connect(self._on_accept)
        self.item_combo.setFocus()

        self._is_new_row = initial is None
        self._price_manually_edited = False
        self.unit_price_field.textEdited.connect(self._on_price_edited_manually)
        self.item_combo.currentIndexChanged.connect(self._on_item_changed)
        self.quantity_field.valueChanged.connect(self._suggest_price)

        if initial is not None:
            index = self.item_combo.findData(initial["item_id"])
            if index >= 0:
                self.item_combo.setCurrentIndex(index)
            self.quantity_field.setValue(float(initial["quantity"]))
            self.unit_price_field.setValue(float(initial["unit_price"]))
            # طبقِ رفعِ باگِ واقعی: اگر ردیف قبلاً با تخفیفِ درصدی ذخیره شده
            # (discount_percent > 0)، همان درصد دوباره نمایش داده شود -- نه
            # مبلغِ نهاییِ محاسبه‌شده (که در حالتِ درصدی گمراه‌کننده است).
            initial_discount_percent = decimal.Decimal(str(initial.get("discount_percent") or 0))
            if initial_discount_percent > 0:
                self.discount_type_combo.setCurrentIndex(self.discount_type_combo.findData("PERCENT"))
                self.discount_field.setValue(float(initial_discount_percent))
            else:
                self.discount_type_combo.setCurrentIndex(self.discount_type_combo.findData("AMOUNT"))
                self.discount_field.setValue(float(initial["discount_amount"]))
            self.tax_percent_field.setValue(float(initial["tax_percent"]))
            self.description_field.setText(initial["description"] or "")
            if self.warehouse_combo is not None:
                index = self.warehouse_combo.findData(initial.get("warehouse_id"))
                self.warehouse_combo.setCurrentIndex(max(0, index))
        else:
            self._on_item_changed()

    def keyPressEvent(self, event) -> None:
        # جلوگیریِ واقعی از باگِ autoDefault (هم‌الگو با
        # treasury_voucher._MethodDetailsDialog): چون همه‌یِ فیلدهایِ این
        # دیالوگ زنجیره‌یِ Enterِ خودشان را دارند، دیگر نیازی نیست QDialog
        # با دیدنِ Enter دوباره دکمه‌یِ پیش‌فرض را کلیک کند.
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_item_changed(self) -> None:
        """طبقِ درخواستِ صریح: درصدِ مالیات با اولویتِ کالا -> تنظیماتِ
        کلیِ شرکت پیش‌پر می‌شود — فقط برایِ ردیفِ *تازه* (initial=None)،
        نه هنگامِ ویرایشِ ردیفِ ازپیش‌ذخیره‌شده که مقدارِ ثبت‌شده‌اش را
        نباید بازنویسی کند."""
        item_id = self.item_combo.currentData()
        self._refresh_stock_info()
        if item_id is None:
            return
        default_tax = catalog_service.resolve_default_tax_percent(self._company_id, item_id)
        self.tax_percent_field.setValue(float(default_tax))
        self._price_manually_edited = False
        self._suggest_price()

    def _refresh_stock_info(self) -> None:
        item_id = self.item_combo.currentData()
        if item_id is None:
            self.stock_info_label.setText("")
            self.kardex_button.setEnabled(False)
            self.price_history_button.setEnabled(False)
            return
        rows = engine_service.get_item_stock_by_warehouse(self._company_id, item_id)
        nonzero = [r for r in rows if r.quantity_on_hand]
        # طبقِ رفعِ باگِ واقعی («موجودیِ کالا هم باید رقمِ اعشارش را از
        # تنظیمات بگیرد»): قبلاً numerals.format_amount خامِ Decimal را
        # (با ۶ رقمِ اعشارِ ذخیره‌شده در ستونِ Numeric(18,6)) بی‌کم‌وکاست
        # نشان می‌داد -- حالا مثلِ quantity_field، تعدادِ رقمِ اعشارِ واحدِ
        # شمارشِ خودِ همان کالا اعمال می‌شود.
        item = self._items_by_id.get(item_id)
        qty_decimals = self._uom_decimal_places.get(item.base_uom_id, 2) if item else 2
        if not nonzero:
            self.stock_info_label.setText("موجودی: صفر")
        else:
            total = sum((r.quantity_on_hand for r in nonzero), decimal.Decimal(0))
            per_warehouse = " | ".join(f"{r.warehouse_name}: {numerals.format_money(r.quantity_on_hand, qty_decimals)}" for r in nonzero)
            self.stock_info_label.setText(f"موجودیِ کل: {numerals.format_money(total, qty_decimals)} ({per_warehouse})")
        self.kardex_button.setEnabled(True)
        self.price_history_button.setEnabled(self._counterparty_id is not None)

    def _open_kardex(self) -> None:
        # طبقِ رفعِ باگِ واقعیِ گزارش‌شده («فرمِ کاردکس زیرِ دیالوگِ ردیف
        # می‌رود»): چون این دیالوگ با exec() به‌صورتِ Application-Modal
        # نمایش داده می‌شود، ناوبری به main_window (یک پنجره‌یِ کاملاً
        # جدا، از طریقِ MDI) اصلاً نمی‌تواند بالا بیاید -- کاردکس این‌جا
        # به‌جایش درونِ یک دیالوگِ فرزندِ همین دیالوگ (که به‌درستی رویِ آن
        # می‌نشیند) نمایش داده می‌شود.
        item_id = self.item_combo.currentData()
        if item_id is None:
            return
        from peecha.ui.screens.report_item_ledger import ItemLedgerScreen

        dialog = QDialog(self)
        dialog.setWindowTitle("کاردکسِ کالا")
        dialog.resize(900, 560)
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(0, 0, 0, 0)
        ledger_screen = ItemLedgerScreen()
        dialog_layout.addWidget(ledger_screen)
        ledger_screen.show_ledger_for_item(item_id)
        dialog.exec()

    def _open_price_history(self) -> None:
        item_id = self.item_combo.currentData()
        if item_id is None or self._counterparty_id is None:
            return
        item = self._items_by_id.get(item_id)
        item_label = f"{item.code} — {item.name or ''}" if item else str(item_id)
        dialog = _ItemPriceHistoryDialog(self, self._company_id, item_id, self._counterparty_id, item_label)
        dialog.exec()

    def _on_price_edited_manually(self) -> None:
        self._price_manually_edited = True

    def _suggest_price(self) -> None:
        """طبقِ رفعِ باگِ واقعی («قیمتِ کالا از لیستِ قیمت پیشنهاد
        نمی‌شود»): قبلاً این مقدار فقط داخلِ سرویس (add_line) و در
        سکوت محاسبه می‌شد — کاربر پیش از ذخیره هرگز آن را نمی‌دید. حالا
        همان منطق (commercial_pricing.resolve_price) این‌جا هم صدا زده
        می‌شود تا بهایِ واحد، همین که کالا/مقدار مشخص شد، در فیلد نمایش
        داده شود — هنوز کاملاً قابلِ‌ویرایشِ دستی."""
        if not self._is_new_row or self._price_manually_edited:
            return
        item_id = self.item_combo.currentData()
        if item_id is None or self._counterparty_id is None or self._document_type_code is None:
            return
        item = self._items_by_id.get(item_id)
        if item is None:
            return
        quantity = decimal.Decimal(str(self.quantity_field.value())) if self.quantity_field.value() > 0 else decimal.Decimal(1)
        try:
            resolved = pricing_service.resolve_price(
                self._company_id, self._counterparty_id, item_id, item.base_uom_id, quantity,
                self._price_list_id, self._document_type_code, self._document_date,
            )
        except ValueError:
            return
        self.unit_price_field.setValue(float(resolved.unit_price))
        if resolved.discount_amount and self.discount_field.value() == 0:
            self.discount_field.setValue(float(resolved.discount_amount))

    def _on_accept(self) -> None:
        if self.item_combo.currentData() is None:
            self.status_label.setText("کالا را انتخاب کنید.")
            return
        if self.quantity_field.value() <= 0:
            self.status_label.setText("مقدار باید بزرگ‌تر از صفر باشد.")
            return
        self.accept()

    def result_fields(self) -> dict:
        item_id = self.item_combo.currentData()
        item = self._items_by_id.get(item_id)
        quantity = decimal.Decimal(str(self.quantity_field.value()))
        # طبقِ درخواستِ صریح («تخفیف روی ردیف کالا فقط مبلغی است، باید
        # درصدی هم باشد»): اگر نوعِ انتخاب‌شده درصدی است، عددِ واردشده
        # درصد است و مبلغِ نهایی رویِ جمعِ ناخالصِ همین ردیف در خودِ
        # commercial_documents.add_line محاسبه می‌شود (هم‌الگو با
        # tax_percent) -- نه این‌جا، چون unit_price ممکن است هنوز None
        # باشد (رزروِ خودکار از فهرستِ قیمت).
        is_percent_discount = self.discount_type_combo.currentData() == "PERCENT"
        discount_value = decimal.Decimal(str(self.discount_field.value()))
        return {
            "item_id": item_id,
            "uom_id": item.base_uom_id if item else 0,
            "quantity": quantity,
            # طبقِ رفعِ باگِ واقعی («ردیف بعدِ ثبت نمایش داده نمی‌شود»):
            # این فیلد قبلاً اصلاً در این دیکشنری نبود — چون
            # documents_service.add_line آن را الزامی (بدونِ مقدارِ
            # پیش‌فرض) می‌خواهد، هر افزودنِ ردیف با TypeErrorِ خاموش
            # (فقط رویِ کنسول، نه در UI) رد می‌شد و کاربر فقط می‌دید که
            # هیچ ردیفی اضافه نشد. چون این فرم هنوز تبدیلِ واحد ندارد
            # (طبقِ داکیومنتِ بالایِ فایل)، quantity_base همیشه با
            # quantity برابر است — هم‌الگو با inventory_document.py.
            "quantity_base": quantity,
            "unit_price": decimal.Decimal(str(self.unit_price_field.value())) if self.unit_price_field.value() > 0 else None,
            "discount_amount": decimal.Decimal(0) if is_percent_discount else discount_value,
            "discount_percent": discount_value if is_percent_discount else decimal.Decimal(0),
            "tax_percent": decimal.Decimal(str(self.tax_percent_field.value())),
            "description": self.description_field.text().strip() or None,
            "warehouse_id": self.warehouse_combo.currentData() if self.warehouse_combo is not None else None,
        }


class _ConvertToInvoiceDialog(LayoutEditMixin, QDialog):
    """طبقِ درخواستِ صریح («صرفِ دکمه‌یِ تبدیلِ یک‌باره خیلی ساده است»):
    به‌جایِ تبدیلِ کاملِ خودکارِ همه‌یِ ردیف‌ها با یک کلیک، این دیالوگ
    مقدارِ سفارش‌شده/فاکتورشده/مانده‌یِ هر ردیف را نشان می‌دهد و اجازه
    می‌دهد کاربر برایِ همین‌بار مقدارِ کمتری (تبدیلِ مرحله‌ای) وارد کند —
    پیش‌فرضِ هر ردیف، کلِ مانده‌اش است."""

    _COLUMNS = ["کالا", "سفارش‌شده", "فاکتورشده", "مانده", "مقدارِ این‌بار"]

    def __init__(self, parent: QWidget, fulfillment: list, items_by_id: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle("تبدیل به فاکتور")
        self.setMinimumWidth(520)
        self._fulfillment = [f for f in fulfillment if f.remaining_quantity > 0]
        self._qty_fields: dict[int, _AmountField] = {}

        layout = QVBoxLayout(self)
        info = QLabel("مقدارِ این‌بار برایِ هر ردیف را مشخص کنید (پیش‌فرض: کلِ مانده).")
        layout.addWidget(info)

        table = QTableWidget(len(self._fulfillment), len(self._COLUMNS))
        table.setHorizontalHeaderLabels(self._COLUMNS)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for row_index, f in enumerate(self._fulfillment):
            item = items_by_id.get(f.item_id)
            table.setItem(row_index, 0, QTableWidgetItem(f"{item.code} — {item.name or ''}" if item else str(f.item_id)))
            table.setItem(row_index, 1, QTableWidgetItem(numerals.format_money(f.quantity, 3)))
            table.setItem(row_index, 2, QTableWidgetItem(numerals.format_money(f.invoiced_quantity, 3)))
            table.setItem(row_index, 3, QTableWidgetItem(numerals.format_money(f.remaining_quantity, 3)))
            qty_field = _AmountField()
            qty_field.setDecimals(3)
            qty_field.setValue(float(f.remaining_quantity))
            self._qty_fields[f.line_id] = qty_field
            table.setCellWidget(row_index, 4, qty_field)
        table.resizeRowsToContents()
        layout.addWidget(table)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("تبدیل")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Ok).setAutoDefault(False)
        buttons.button(QDialogButtonBox.Cancel).setAutoDefault(False)
        layout.addWidget(buttons)

    def keyPressEvent(self, event) -> None:
        # هم‌الگو با _LineDialog — جلوگیریِ واقعی از باگِ autoDefaultِ
        # QDialogButtonBox (طبقِ سندِ راهنما، بخشِ ۶.۳-ت).
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_accept(self) -> None:
        quantities = {line_id: decimal.Decimal(str(field.value())) for line_id, field in self._qty_fields.items()}
        if all(q <= 0 for q in quantities.values()):
            self.status_label.setText("حداقل برایِ یک ردیف مقداری وارد کنید.")
            return
        for f in self._fulfillment:
            if quantities[f.line_id] > f.remaining_quantity:
                self.status_label.setText("مقدارِ واردشده برایِ یک ردیف از مانده‌اش بیشتر است.")
                return
        self.accept()

    def result_quantities(self) -> dict[int, decimal.Decimal]:
        return {line_id: decimal.Decimal(str(field.value())) for line_id, field in self._qty_fields.items() if field.value() > 0}


class _LandedCostDialog(QDialog):
    """طبقِ درخواستِ صریح («فرمِ تسهیمِ هزینه در فاکتورِ خرید»): مدیریتِ
    هزینه‌هایِ جانبیِ همین فاکتورِ خرید (ترخیص/گمرک/هزینه‌هایِ ارزیِ دیگر).
    هر ردیف یک مبلغ و یک حسابِ معین+تفصیلیِ آزادانه دارد (مثلاً یک
    تفصیلیِ گروهِ «سفارشاتِ در راه») که با Postِ فاکتور بستانکار می‌شود --
    تسهیمِ خودِ مبلغ رویِ ردیف‌هایِ فاکتور (به بهایِ موجودی/تمام‌شده) و
    ساختِ ردیف‌هایِ بستانکاریِ سندِ حسابداری، هردو در همان لحظه (درونِ
    commercial_documents.post_document، همراهِ خودِ سندِ فاکتور) انجام
    می‌شود -- این فرم فقط ردیف‌هایِ هزینه را قبل از Post مدیریت می‌کند."""

    def __init__(self, document_id: int, company_id: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("تسهیمِ هزینه‌هایِ جانبیِ خرید")
        self.resize(760, 480)
        self._document_id = document_id
        self._company_id = company_id
        self._decimal_places = companies_service.get_base_currency_decimal_places(company_id)
        self._account_options = [
            (a.account_id, f"{a.full_code} — {a.name}") for a in coa_service.list_accounts(company_id) if a.is_postable
        ]
        self._required_dimension_type_by_detail_id: dict[int, int] = {}

        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["مبلغ", "حساب", "تفصیلی", "توضیحات", ""])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        # طبقِ گزارشِ صریح («عرضِ ستون‌ها متناسب نیست و مبلغ خیلی کنه
        # است»): بدونِ عرضِ صریح، ستونِ «مبلغ» فقط به‌اندازهٔ همان چهار
        # حرفِ سرستون تنگ می‌ماند، نه به‌اندازهٔ مبلغِ واقعی.
        table_header = self.table.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.setColumnWidth(0, 140)
        table_header.setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.setColumnWidth(1, 220)
        table_header.setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.setColumnWidth(2, 200)
        table_header.setSectionResizeMode(3, QHeaderView.Stretch)
        table_header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(4, 40)
        layout.addWidget(self.table, stretch=1)

        # طبقِ گزارشِ صریح («فیلدهایِ ورودی تناسب با اطلاعاتِ ورودی
        # ندارند»): بدونِ حداقلِ عرضِ صریح، کمبویِ حساب (که متنِ طولانیِ
        # کد+نامِ حساب دارد) کل فضا را می‌گرفت و فیلدهایِ مبلغ/توضیحات به
        # عرضی نزدیکِ صفر فشرده می‌شدند -- ضریبِ stretch به‌تنهایی مانعِ این
        # فشردگی نمی‌شود، چون Qt اول حداقل‌سایزِ هر ویجت را برآورده می‌کند.
        entry_row = QHBoxLayout()
        self.amount_field = _AmountField()
        self.amount_field.setDecimals(self._decimal_places)
        self.amount_field.setMinimumWidth(110)
        entry_row.addWidget(self.amount_field, stretch=1)
        self.account_combo = _make_searchable_combo(self._account_options)
        self.account_combo.setMinimumWidth(180)
        entry_row.addWidget(self.account_combo, stretch=2)
        self.detail_combo = _make_searchable_combo([])
        self.detail_combo.setMinimumWidth(160)
        entry_row.addWidget(self.detail_combo, stretch=2)
        self.notes_field = QLineEdit()
        self.notes_field.setPlaceholderText("توضیحات (اختیاری)")
        self.notes_field.setMinimumWidth(140)
        entry_row.addWidget(self.notes_field, stretch=1)
        add_button = QPushButton("➕")
        add_button.setObjectName("primaryIconButton")
        add_button.setFixedWidth(44)
        add_button.setToolTip("افزودنِ ردیفِ هزینه")
        add_button.clicked.connect(self._add_row)
        entry_row.addWidget(add_button)
        layout.addLayout(entry_row)

        # طبقِ درخواستِ صریح («با زدنِ اینتر ردیفِ جدید ایجاد بشه و همینطور
        # تا ردیف‌هایِ بعدی»): زنجیره‌یِ Enter رویِ همین چهار فیلد.
        self.amount_field.returnPressed.connect(self.account_combo.setFocus)
        self.account_combo.lineEdit().returnPressed.connect(self.detail_combo.setFocus)
        self.detail_combo.lineEdit().returnPressed.connect(self.notes_field.setFocus)
        self.notes_field.returnPressed.connect(self._add_row)

        self.account_combo.currentIndexChanged.connect(self._refresh_detail_options)
        self.detail_combo.currentIndexChanged.connect(self._refresh_balance_label)

        self.balance_label = QLabel("")
        layout.addWidget(self.balance_label)

        self.total_label = QLabel("")
        layout.addWidget(self.total_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("بستن")
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)

        self._refresh_detail_options()
        self._refresh_table()

    def _refresh_detail_options(self) -> None:
        account_id = self.account_combo.currentData()
        self._required_dimension_type_by_detail_id = {}
        if account_id is None:
            _fill_options(self.detail_combo, [])
            self.balance_label.setText("")
            return
        required = dimensions_service.get_required_dimensions_for_account(account_id)
        detail_options: list[tuple[int, str]] = []
        for dim in required:
            prefix = dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(dim.code)
            for d in dim.detail_accounts:
                self._required_dimension_type_by_detail_id[d.detail_account_id] = dim.dimension_type_id
                label = f"{d.code} — {d.name or ''}" if prefix is None else f"{prefix}: {d.code} — {d.name or ''}"
                detail_options.append((d.detail_account_id, label))
        _fill_options(self.detail_combo, detail_options)
        self.detail_combo.setToolTip("تفصیلی (الزامی)" if required else "")
        self._refresh_balance_label()

    def _refresh_balance_label(self) -> None:
        detail_account_id = self.detail_combo.currentData()
        if detail_account_id is None:
            self.balance_label.setText("")
            return
        balance, nature = treasury_service.get_counterparty_balance(self._company_id, detail_account_id)
        self.balance_label.setText(f"ماندهٔ فعلیِ همین تفصیلی: {numerals.format_money(balance, self._decimal_places)} ({nature})")

    def _refresh_table(self) -> None:
        allocations = purchasing_service.list_landed_cost_allocations(self._document_id)
        accounts_by_id = dict(self._account_options)
        self.table.setRowCount(len(allocations))
        total = decimal.Decimal(0)
        for row_index, a in enumerate(allocations):
            total += a.amount
            detail_label = (
                dimensions_service.get_detail_account_label(a.credit_detail_account_id)
                if a.credit_detail_account_id is not None else ""
            )
            values = [
                numerals.format_money(a.amount, self._decimal_places), accounts_by_id.get(a.credit_account_id, str(a.credit_account_id)),
                detail_label, a.notes or "",
            ]
            for col_index, value in enumerate(values):
                self.table.setItem(row_index, col_index, QTableWidgetItem(value))
            delete_button = QPushButton("✕")
            delete_button.setObjectName("dangerIconButton")
            delete_button.setFixedWidth(32)
            delete_button.clicked.connect(lambda _checked=False, allocation_id=a.allocation_id: self._delete_row(allocation_id))
            self.table.setCellWidget(row_index, 4, delete_button)
        self.total_label.setText(f"جمعِ کلِ هزینه‌هایِ جانبی: {numerals.format_money(total, self._decimal_places)}")

    def _add_row(self) -> None:
        account_id = self.account_combo.currentData()
        if account_id is None:
            self.status_label.setText("انتخابِ حساب الزامی است.")
            return
        detail_account_id = self.detail_combo.currentData()
        if self._required_dimension_type_by_detail_id and detail_account_id is None:
            self.status_label.setText("این حساب نیازمندِ انتخابِ تفصیلی است.")
            return
        amount = decimal.Decimal(str(self.amount_field.value()))
        if amount <= 0:
            self.status_label.setText("مبلغ باید بزرگ‌تر از صفر باشد.")
            return
        try:
            purchasing_service.add_landed_cost_line(
                self._document_id, amount, account_id, credit_detail_account_id=detail_account_id,
                notes=self.notes_field.text().strip() or None,
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("")
        self.amount_field.setValue(0)
        self.notes_field.clear()
        self._refresh_table()
        self.amount_field.setFocus()

    def _delete_row(self, allocation_id: int) -> None:
        try:
            purchasing_service.delete_landed_cost_line(allocation_id, self._company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._refresh_table()


class CommercialDocumentScreen(FieldHelpMixin, FormScreenBase):
    def __init__(self, document_type_code: str, main_window) -> None:
        super().__init__()
        self.document_type_code = document_type_code
        self._is_sales = document_type_code in _SALES_TYPES
        # طبقِ درخواستِ صریح («موعدِ تسویه فقط برایِ فاکتور معنا دارد»):
        # سفارش/پیش‌فاکتور/برگشت این فیلد را نمی‌بینند.
        self._is_invoice = document_type_code in ("SALES_INVOICE", "PURCHASE_INVOICE")
        # طبقِ درخواستِ صریح («برای برگشت از خرید و برگشت از فروش هم به
        # همین صورت انجام بشه»): نوعِ ثبتِ رسمی/غیررسمی رویِ برگشت هم
        # قابلِ‌override است، نه فقط فاکتور.
        self._supports_tax_posting_mode = document_type_code in (
            "SALES_INVOICE", "PURCHASE_INVOICE", "SALES_RETURN", "PURCHASE_RETURN",
        )
        # طبقِ درخواستِ صریح («سبدِ پیشنهادی» -- کالاهایی که معمولاً همراهِ
        # کالایِ تازه‌اضافه‌شده خریده می‌شوند): فقط برایِ اسنادِ فروشِ رو
        # به جلو معنا دارد -- نه برگشت (که خودش یک اصلاح است، نه فروشِ
        # تازه) و نه امانی (که مسیرِ تسویه‌اش جداست).
        self._supports_cross_sell = document_type_code in ("SALES_ORDER", "SALES_PROFORMA", "SALES_INVOICE")
        self._cross_sell_suggestions: list = []
        self._main_window = main_window
        self._document_id: int | None = None
        self._status_code = "DRAFT"
        self._corrects_document_id: int | None = None
        self._lines: list = []
        self._items: list[catalog_service.ItemRow] = []
        self._decimal_places = 0
        self._cost_center_required = False
        self._project_required = False
        self._per_line_warehouse_enabled = False
        self._warehouses: list = []

        title = DOC_TYPE_TITLES[document_type_code]
        self.page_title = QLabel(title)
        self.page_title.setObjectName("pageTitle")
        self.body_layout.addWidget(self.page_title)

        # طبقِ نمونه‌طراحیِ استپردار/کارت‌رنگیِ ارسالیِ کاربر — هم‌الگو با
        # treasury_voucher.py/journal_entry.py: صرفاً لایه‌یِ بصری/ناوبری،
        # هیچ ویجتِ موجودی جابه‌جا نمی‌شود. چون این فرم (بر خلافِ آن دو)
        # هدرش را در یک کارتِ جداگانه نمی‌پیچد، از خودِ page_title/
        # lines_table به‌عنوانِ لنگرِ شروعِ هر بخش استفاده می‌شود.
        self.step_stepper = SectionStepper(["اطلاعاتِ سند", "ردیف‌ها"])
        self.body_layout.addWidget(self.step_stepper)

        self.summary_cards = SummaryCardBar({
            "subtotal": SummaryCard("جمعِ ناخالص", role="neutral"),
            "discount_tax": SummaryCard("تخفیف/مالیات", role="warning"),
            "grand_total": SummaryCard("جمعِ کل", role="success"),
        })
        self.body_layout.addWidget(self.summary_cards)

        # طبقِ گزارشِ تکراریِ کاربر («هدرِ فرم‌هایِ انبار/فروش/خرید هنوز
        # نامرتب است — فقط یک فرم درست شد»): این هدر هم اکنون هم‌الگو با
        # journal_entry.py/treasury_voucher.py یک کارتِ واحد با
        # QGridLayoutِ فشرده است، نه چند QHBoxLayoutِ خامِ پشتِ سرهم.
        header_card = QWidget()
        header_card.setObjectName("card")
        header_grid = QGridLayout(header_card)
        header_grid.setContentsMargins(8, 4, 8, 4)
        header_grid.setHorizontalSpacing(6)
        header_grid.setVerticalSpacing(2)

        header_grid.addWidget(QLabel("تاریخ"), 0, 0)
        self.date_field = JalaliDateEdit()
        header_grid.addWidget(self.date_field, 1, 0)

        # طبقِ درخواستِ صریح (فاکتورِ امانی): طرفِ‌حسابِ امانیِ خروجی
        # نماینده/مشتری است، امانیِ ورودی همان تامین‌کننده -- برچسبِ
        # روشن‌تر از «مشتری/تامین‌کننده»یِ عمومی.
        if document_type_code == "CONSIGNMENT_OUT":
            counterparty_label_text = "نماینده/مشتری (طرفِ امانی)"
        elif document_type_code == "CONSIGNMENT_IN":
            counterparty_label_text = "تامین‌کننده (طرفِ امانی)"
        else:
            counterparty_label_text = "مشتری" if self._is_sales else "تامین‌کننده"
        header_grid.addWidget(QLabel(counterparty_label_text), 0, 1)
        counterparty_row = QHBoxLayout()
        counterparty_row.setContentsMargins(0, 0, 0, 0)
        counterparty_row.setSpacing(3)
        self.counterparty_combo = _make_searchable_combo([])
        counterparty_row.addWidget(self.counterparty_combo, stretch=1)
        add_quick_add_button(
            counterparty_row, self.counterparty_combo, main_window, "GL_DIM",
            "تعریفِ مشتریِ تازه" if self._is_sales else "تعریفِ تامین‌کننده‌یِ تازه",
        )
        header_grid.addLayout(counterparty_row, 1, 1)

        self.warehouse_label = QLabel("انبار")
        header_grid.addWidget(self.warehouse_label, 0, 2)
        warehouse_row = QHBoxLayout()
        warehouse_row.setContentsMargins(0, 0, 0, 0)
        warehouse_row.setSpacing(3)
        self.warehouse_combo = _EnterComboBox()
        warehouse_row.addWidget(self.warehouse_combo, stretch=1)
        add_quick_add_button(warehouse_row, self.warehouse_combo, main_window, "INV_WAREHOUSES", "تعریفِ انبارِ تازه")
        header_grid.addLayout(warehouse_row, 1, 2)

        # طبقِ درخواستِ صریح («فیلدِ شماره‌یِ سفارش روی هدر باز بشه»):
        # قبلاً شماره‌یِ سند فقط داخلِ عنوانِ صفحه («سفارشِ فروش #۵»، فقط
        # بعدِ ذخیره) دیده می‌شد؛ حالا یک فیلدِ صریح و همیشه‌حاضر در هدر
        # هم دارد (پیش از ذخیره: «—»).
        header_grid.addWidget(QLabel("شمارهٔ سند"), 0, 3)
        self.document_no_field = QLineEdit()
        self.document_no_field.setReadOnly(True)
        self.document_no_field.setFocusPolicy(Qt.NoFocus)
        self.document_no_field.setAlignment(Qt.AlignCenter)
        self.document_no_field.setText("—")
        header_grid.addWidget(self.document_no_field, 1, 3)

        header_grid.addWidget(QLabel("شمارهٔ مرجع"), 0, 4)
        self.reference_field = QLineEdit()
        header_grid.addWidget(self.reference_field, 1, 4)

        # طبقِ درخواستِ صریح («هدر ۳ ردیفه — عرضِ فیلدهایِ ردیفِ دوم را کم
        # کن و مرکزِ هزینه/پروژه هم در همان ردیفِ دوم بگنجد، فاصله‌یِ بینِ
        # ردیف‌ها را به حداقل برسان»): فهرستِ قیمت/کانال/توضیح/مرکزِ هزینه/
        # پروژه پنج تا هستند و برایِ این‌که عرضشان مستقلِ ستون‌بندیِ ردیفِ
        # اول (تاریخ/طرفِ‌حساب/انبار/شماره‌ها) بماند، در یک QGridLayoutِ
        # تودرتوی جدا چیده می‌شوند — نه مستقیم در header_grid — وگرنه
        # تغییرِ عرضِ ستون‌هایشان عرضِ فیلدهایِ ردیفِ اول را هم به‌هم می‌زد.
        # همین یک ردیفِ بیرونی هم باعث می‌شود دیگر ردیفِ سومِ جدا لازم نباشد.
        row2_widget = QWidget()
        row2_grid = QGridLayout(row2_widget)
        row2_grid.setContentsMargins(0, 0, 0, 0)
        row2_grid.setSpacing(3)

        row2_grid.addWidget(QLabel("فهرستِ قیمت"), 0, 0)
        self.price_list_combo = _EnterComboBox()
        row2_grid.addWidget(self.price_list_combo, 1, 0)

        self.channel_box = QWidget()
        channel_layout = QVBoxLayout(self.channel_box)
        channel_layout.setContentsMargins(0, 0, 0, 0)
        channel_layout.setSpacing(3)
        channel_layout.addWidget(QLabel("کانال"))
        self.channel_combo = _EnterComboBox()
        channel_layout.addWidget(self.channel_combo)
        row2_grid.addWidget(self.channel_box, 0, 1, 2, 1)
        self.channel_box.setVisible(self._is_sales)

        row2_grid.addWidget(QLabel("توضیح"), 0, 2)
        self.description_field = QLineEdit()
        row2_grid.addWidget(self.description_field, 1, 2)

        # طبقِ رفعِ باگِ واقعی («برای حساب X انتخابِ گروه‌هایِ تفصیلیِ
        # الزامی فراموش شده است» با این‌که تفصیلیِ طرفِ‌حساب درست انتخاب
        # شده بود): بعضی حساب‌هایِ نقش‌محورِ این سند (دریافتنی/پرداختنی/
        # درآمد/موجودی/...) ممکن است علاوه‌بر تفصیلیِ طرفِ‌حساب، به مرکزِ
        # هزینه/پروژه هم نیاز داشته باشند — هم‌الگو با فیلدهایِ همیشه‌حاضرِ
        # مشابه در فرمِ تنخواه‌گردان. برچسب با «*» یعنی برایِ این نوعِ سند
        # (طبقِ تنظیماتِ نگاشتِ حساب‌ها) الزامی است.
        self.cost_center_label = QLabel("مرکزِ هزینه")
        row2_grid.addWidget(self.cost_center_label, 0, 3)
        cost_center_row = QHBoxLayout()
        cost_center_row.setContentsMargins(0, 0, 0, 0)
        cost_center_row.setSpacing(3)
        self.cost_center_combo = _EnterComboBox()
        cost_center_row.addWidget(self.cost_center_combo, stretch=1)
        add_quick_add_button(cost_center_row, self.cost_center_combo, main_window, "GL_DIM", "تعریفِ مرکزِ هزینه‌یِ تازه")
        row2_grid.addLayout(cost_center_row, 1, 3)

        self.project_box = QWidget()
        project_layout = QVBoxLayout(self.project_box)
        project_layout.setContentsMargins(0, 0, 0, 0)
        project_layout.setSpacing(3)
        self.project_label = QLabel("پروژه")
        project_layout.addWidget(self.project_label)
        project_row = QHBoxLayout()
        project_row.setContentsMargins(0, 0, 0, 0)
        project_row.setSpacing(3)
        self.project_combo = _EnterComboBox()
        project_row.addWidget(self.project_combo, stretch=1)
        add_quick_add_button(project_row, self.project_combo, main_window, "GL_DIM", "تعریفِ پروژه‌یِ تازه")
        project_layout.addLayout(project_row)
        row2_grid.addWidget(self.project_box, 0, 4, 2, 1)

        # طبقِ درخواستِ صریح («در هر فاکتور موعدِ تسویه را بر اساسِ
        # تعاریفِ آن در تفصیلی نمایش دهد و بتوان آن را هم ویرایش کرد»):
        # فقط برایِ فاکتورِ خرید/فروش نمایش داده می‌شود -- با انتخابِ
        # طرفِ‌حساب خودکار از رویِ payment_term_days محاسبه می‌شود، ولی
        # کاملاً قابلِ‌ویرایشِ دستی هم هست.
        self.due_date_box = QWidget()
        due_date_layout = QVBoxLayout(self.due_date_box)
        due_date_layout.setContentsMargins(0, 0, 0, 0)
        due_date_layout.setSpacing(3)
        due_date_layout.addWidget(QLabel("موعدِ تسویه"))
        self.due_date_field = JalaliDateEdit()
        due_date_layout.addWidget(self.due_date_field)
        row2_grid.addWidget(self.due_date_box, 0, 5, 2, 1)
        self.due_date_box.setVisible(self._is_invoice)

        # طبقِ درخواستِ صریح (فاکتورِ امانیِ خروجی): علاوه‌بر انبارِ خودمان
        # (فیلدِ «انبار» بالا -- مبدأِ ارسال)، یک انبارِ دوم لازم است که
        # ردِ کالایِ فیزیکاً نزدِ نماینده/مشتری را نگه دارد (تا فروشِ
        # واقعی/تسویه). فقط برایِ همین یک نوعِ سند نمایش داده می‌شود.
        self.consignment_warehouse_box = QWidget()
        consignment_warehouse_layout = QVBoxLayout(self.consignment_warehouse_box)
        consignment_warehouse_layout.setContentsMargins(0, 0, 0, 0)
        consignment_warehouse_layout.setSpacing(3)
        consignment_warehouse_layout.addWidget(QLabel("انبارِ نمایندگی/طرفِ امانی"))
        consignment_warehouse_row = QHBoxLayout()
        consignment_warehouse_row.setContentsMargins(0, 0, 0, 0)
        consignment_warehouse_row.setSpacing(3)
        self.consignment_warehouse_combo = _EnterComboBox()
        consignment_warehouse_row.addWidget(self.consignment_warehouse_combo, stretch=1)
        add_quick_add_button(consignment_warehouse_row, self.consignment_warehouse_combo, main_window, "INV_WAREHOUSES", "تعریفِ انبارِ تازه")
        consignment_warehouse_layout.addLayout(consignment_warehouse_row)
        row2_grid.addWidget(self.consignment_warehouse_box, 0, 6, 2, 1)
        self.consignment_warehouse_box.setVisible(document_type_code == "CONSIGNMENT_OUT")

        # طبقِ درخواستِ صریح («دو نوعِ ثبت: رسمی/غیررسمی»): فقط برایِ
        # فاکتورِ خرید/فروش -- override رویِ همین سند، پیش‌فرض یعنی از
        # تنظیماتِ سراسریِ شرکت (Feature Toggleِ INFORMAL_TAX_POSTING)
        # پیروی کن.
        self.tax_posting_mode_box = QWidget()
        tax_posting_mode_layout = QVBoxLayout(self.tax_posting_mode_box)
        tax_posting_mode_layout.setContentsMargins(0, 0, 0, 0)
        tax_posting_mode_layout.setSpacing(3)
        tax_posting_mode_layout.addWidget(QLabel("نوعِ ثبت"))
        self.tax_posting_mode_combo = _EnterComboBox()
        self.tax_posting_mode_combo.addItem("پیش‌فرضِ شرکت", None)
        self.tax_posting_mode_combo.addItem("رسمی", "OFFICIAL")
        self.tax_posting_mode_combo.addItem("غیررسمی", "INFORMAL")
        tax_posting_mode_layout.addWidget(self.tax_posting_mode_combo)
        row2_grid.addWidget(self.tax_posting_mode_box, 0, 7, 2, 1)
        self.tax_posting_mode_box.setVisible(self._supports_tax_posting_mode)

        row2_grid.setColumnStretch(0, 1)
        row2_grid.setColumnStretch(1, 1)
        row2_grid.setColumnStretch(2, 2)
        row2_grid.setColumnStretch(3, 1)
        row2_grid.setColumnStretch(4, 1)
        row2_grid.setColumnStretch(5, 1)
        row2_grid.setColumnStretch(6, 1)
        row2_grid.setColumnStretch(7, 1)
        header_grid.addWidget(row2_widget, 2, 0, 1, 5)

        header_grid.setColumnStretch(0, 1)
        header_grid.setColumnStretch(1, 2)
        header_grid.setColumnStretch(2, 1)
        header_grid.setColumnStretch(3, 1)
        header_grid.setColumnStretch(4, 1)
        self.body_layout.addWidget(header_card)

        # طبقِ درخواستِ صریح («فاکتورِ فوق‌هوشمند... کنارِ مشتری: آخرین
        # خرید، میانگینِ خرید، اعتبار، بدهی، امتیازِ مشتری») -- فقط برایِ
        # اسنادِ روبه‌جلویِ فروش (همان مجموعه‌ای که سبدِ پیشنهادی دارند)
        # و فقط وقتی طرفِ‌حساب انتخاب شده باشد.
        self.customer_summary_box = QWidget()
        self.customer_summary_box.setObjectName("card")
        customer_summary_layout = QHBoxLayout(self.customer_summary_box)
        customer_summary_layout.setContentsMargins(12, 6, 12, 6)
        self.customer_summary_label = QLabel("")
        self.customer_summary_label.setWordWrap(True)
        customer_summary_layout.addWidget(self.customer_summary_label)
        self.customer_summary_box.setVisible(False)
        self.body_layout.addWidget(self.customer_summary_box)

        # زنجیره‌ی کاملِ Enter رویِ هدر — بدونِ استثنا (طبقِ سندِ راهنما).
        header_chain = [
            self.date_field, self.counterparty_combo, self.warehouse_combo, self.reference_field,
            self.price_list_combo, self.channel_combo, self.description_field,
            self.cost_center_combo, self.project_combo,
        ]
        for widget, next_widget in zip(header_chain, header_chain[1:]):
            _enter_signal(widget).connect(next_widget.setFocus)
        # طبقِ درخواستِ صریح («بعدِ اینترِ فیلدِ آخرِ هدر خودکار برود به
        # اولین ردیف»): زنجیره‌یِ Enterِ هدر حالا مستقیم به افزودنِ اولین
        # ردیف می‌رسد، به‌جایِ متوقف‌شدن روی توضیح.
        _enter_signal(header_chain[-1]).connect(self._add_line)
        if self._is_invoice:
            self.counterparty_combo.currentIndexChanged.connect(self._recompute_due_date)
        if self._supports_cross_sell:
            self.counterparty_combo.currentIndexChanged.connect(self._refresh_customer_summary)

        # طبقِ رفعِ باگِ واقعی («هدر هنوز فضایِ زیادی اشغال کرده»): وضعیت و
        # پیوندهایِ سند هردو متنِ کوتاهِ اطلاعاتی‌اند — قبلاً هرکدام یک
        # ردیفِ کاملِ جدا بودند؛ حالا کنارِ هم، یک ردیف.
        # طبقِ درخواستِ صریح («فضایِ بینِ هدر خیلی خالی است و فقط دکمه‌یِ
        # افزودنِ ردیف دارد؛ این دکمه برود داخلِ هدر تا فضایِ بیشتری برایِ
        # جزئیاتِ فاکتور آزاد شود»): ردیفِ جداگانه‌یِ «ردیف‌ها + دکمه‌یِ
        # افزودن» حذف شد -- عنوانِ بخش و دکمه‌یِ افزودن حالا کنارِ نوارِ
        # وضعیت/پیوندهایِ سند می‌نشینند، در همان یک ردیفِ فشرده.
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(8)
        lines_title = QLabel("ردیف‌ها")
        lines_title.setObjectName("sectionTitle")
        status_row.addWidget(lines_title)
        add_line_button = QPushButton("➕")
        add_line_button.setObjectName("primaryIconButton")
        add_line_button.setFixedWidth(48)
        add_line_button.setToolTip("افزودنِ ردیف")
        add_line_button.clicked.connect(self._add_line)
        status_row.addWidget(add_line_button)
        self.status_badge = QLabel("")
        self.status_badge.setObjectName("statusBadge")
        status_row.addWidget(self.status_badge)
        self.links_label = QLabel("")
        status_row.addWidget(self.links_label)
        status_row.addStretch(1)
        self.body_layout.addLayout(status_row)

        self.lines_table = QTableWidget(0, len(_LINE_COLUMNS))
        self.lines_table.setHorizontalHeaderLabels(_LINE_COLUMNS)
        self.lines_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lines_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.lines_table.verticalHeader().setVisible(False)
        self.lines_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.lines_table.setMinimumHeight(220)
        self.lines_table.cellDoubleClicked.connect(self._edit_line)
        self.body_layout.addWidget(self.lines_table)

        self.step_stepper.register_sections(self._scroll, [self.page_title, self.lines_table])

        line_button_cluster = QWidget()
        line_button_cluster.setLayoutDirection(Qt.LeftToRight)
        line_buttons = QHBoxLayout(line_button_cluster)
        line_buttons.setContentsMargins(0, 0, 0, 0)
        edit_line_button = QPushButton("✏️")
        edit_line_button.setObjectName("iconButton")
        edit_line_button.setFixedWidth(44)
        edit_line_button.setToolTip("ویرایشِ ردیف")
        edit_line_button.clicked.connect(self._edit_line)
        line_buttons.addWidget(edit_line_button)
        delete_line_button = QPushButton("🗑️")
        delete_line_button.setObjectName("dangerIconButton")
        delete_line_button.setFixedWidth(44)
        delete_line_button.setToolTip("حذفِ ردیف")
        delete_line_button.clicked.connect(self._delete_line)
        line_buttons.addWidget(delete_line_button)
        self.body_layout.addWidget(line_button_cluster, alignment=Qt.AlignLeft)

        # طبقِ درخواستِ صریح («سبدِ پیشنهادی»): بعدِ افزودنِ هر ردیف، اگر
        # کالاهایی وجود دارند که همینِ مشتری معمولاً همراهِ آن خریده،
        # همه‌شان این‌جا (هرکدام یک ردیفِ جدا با دکمهٔ افزودنِ خودش) نشان
        # داده می‌شوند -- غیرِمزاحم و پیش‌فرض پنهان.
        self.cross_sell_box = QWidget()
        self._cross_sell_layout = QVBoxLayout(self.cross_sell_box)
        self._cross_sell_layout.setContentsMargins(0, 0, 0, 0)
        self._cross_sell_layout.setSpacing(4)
        self.cross_sell_box.setVisible(False)
        self.body_layout.addWidget(self.cross_sell_box)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        self.body_layout.addWidget(self.status_label)
        self.body_layout.addStretch(1)

        # طبقِ گزارشِ صریح («بعضی فرم‌ها روی دکمه‌هاش نوشته داره و نصف
        # نوشته‌هاست»): این فوتر ۶ دکمه‌یِ متنیِ کنارِ هم داشت — دقیقاً
        # الگویِ فشرده‌شدنی که باعثِ بریده‌شدنِ متن می‌شود. همه آیکنی
        # شدند؛ توضیح از طریقِ تول‌تیپ.
        self.new_button = QPushButton("🆕")
        self.new_button.setObjectName("iconButton")
        self.new_button.setFixedWidth(44)
        self.new_button.setToolTip("سندِ جدید — فرم را برایِ ثبتِ سندِ بعدی خالی می‌کند")
        self.new_button.clicked.connect(self._reset_form)
        self.footer_layout.addWidget(self.new_button)

        self.save_button = QPushButton("💾")
        self.save_button.setObjectName("primaryIconButton")
        self.save_button.setFixedWidth(48)
        self.save_button.setToolTip("۱) ذخیرهٔ پیش‌نویس — سند ثبت می‌شود ولی هنوز قطعی نیست؛ سرِسند و ردیف‌ها بعداً قابلِ‌ویرایش/حذف‌اند")
        self.save_button.clicked.connect(self._save_header)
        self.footer_layout.addWidget(self.save_button)

        self.confirm_button = QPushButton("✅")
        self.confirm_button.setObjectName("iconButton")
        self.confirm_button.setFixedWidth(44)
        self.confirm_button.setToolTip("۲) تاییدِ سند — گامِ اولِ گردشِ کار پس از پیش‌نویس؛ سند برایِ تصویب/ثبتِ نهایی آماده می‌شود")
        self.confirm_button.clicked.connect(self._confirm)
        self.footer_layout.addWidget(self.confirm_button)

        self.approve_button = QPushButton("👍")
        self.approve_button.setObjectName("iconButton")
        self.approve_button.setFixedWidth(44)
        self.approve_button.setToolTip("۳) تصویبِ سند — تاییدِ مدیریتیِ اضافه پیش از ثبتِ نهایی (اختیاری، پیش از ثبتِ نهایی انجام می‌شود)")
        self.approve_button.clicked.connect(self._approve)
        self.footer_layout.addWidget(self.approve_button)

        self.post_button = QPushButton("🔒")
        self.post_button.setObjectName("primaryIconButton")
        self.post_button.setFixedWidth(48)
        self.post_button.setToolTip("۴) ثبتِ نهایی — قطعی و برگشت‌ناپذیر؛ سندِ انبار/حسابداریِ واقعی همین‌جا ساخته می‌شود")
        self.post_button.clicked.connect(self._post)
        self.footer_layout.addWidget(self.post_button)

        self.cancel_button = QPushButton("🚫")
        self.cancel_button.setObjectName("dangerIconButton")
        self.cancel_button.setFixedWidth(44)
        self.cancel_button.setToolTip("لغوِ سند — سند باطل می‌شود (فقط پیش از ثبتِ نهایی ممکن است)")
        self.cancel_button.clicked.connect(self._cancel)
        self.footer_layout.addWidget(self.cancel_button)

        # طبقِ درخواستِ صریح («مدیر بتواند فاکتورِ ثبت‌شده را اصلاح کند»):
        # فقط برایِ فاکتورِ خرید/فروش نمایش داده می‌شود؛ فعال‌بودنش هم به
        # وضعیتِ POSTED هم به مجازبودنِ کاربر (نقشِ مدیر + تنظیمِ روشنِ
        # شرکت) بستگی دارد -- can_correct_posted_document() هردو را
        # دوباره در start_invoice_correction() هم اعتبارسنجی می‌کند.
        self.correct_button = QPushButton("♻️")
        self.correct_button.setObjectName("iconButton")
        self.correct_button.setFixedWidth(44)
        self.correct_button.setToolTip(
            "اصلاحِ فاکتورِ ثبت‌شده — فقط برایِ مدیر و در صورتِ فعال‌بودنِ تنظیمِ «اجازه‌یِ اصلاحِ فاکتورِ ثبت‌شده».\n"
            "سندِ فعلی عیناً و با تاریخِ امروز برگشت می‌خورد (بدونِ تغییرِ تاریخِ فاکتورهایِ قبلی) "
            "و یک پیش‌نویسِ تازه برایِ ویرایش باز می‌شود."
        )
        self.correct_button.clicked.connect(self._correct_invoice)
        self.correct_button.setVisible(document_type_code in ("SALES_INVOICE", "PURCHASE_INVOICE"))
        self.footer_layout.addWidget(self.correct_button)

        # طبقِ درخواستِ صریح («فرمِ تسهیمِ هزینه در فاکتورِ خرید»): فقط
        # برایِ فاکتورِ خرید، و فقط پیش از Post (سندِ ذخیره‌شده باشد).
        self.landed_cost_button = QPushButton("🧮")
        self.landed_cost_button.setObjectName("iconButton")
        self.landed_cost_button.setFixedWidth(44)
        self.landed_cost_button.setToolTip(
            "تسهیمِ هزینه‌هایِ جانبیِ خرید (ترخیص/گمرک/هزینه‌هایِ ارزیِ دیگر) — "
            "با Postِ فاکتور، این هزینه‌ها متناسب با ارزشِ ردیف‌ها به بهایِ موجودی/تمام‌شده اضافه می‌شوند "
            "و حساب‌هایِ انتخاب‌شده برایِ هرکدام بستانکار می‌شوند."
        )
        self.landed_cost_button.clicked.connect(self._open_landed_costs)
        self.landed_cost_button.setVisible(document_type_code == "PURCHASE_INVOICE")
        self.footer_layout.addWidget(self.landed_cost_button)

        # طبقِ درخواستِ صریح («سفارش/پیش‌فاکتور بتواند به فاکتور تبدیل
        # شود»): فقط برایِ انواعِ سفارش/پیش‌فاکتور نمایش داده می‌شود.
        self.convert_button = QPushButton("→")
        self.convert_button.setObjectName("primaryIconButton")
        self.convert_button.setFixedWidth(48)
        self.convert_button.setToolTip("تبدیل به فاکتور — از مقدارِ باقی‌ماندهٔ این سند، فاکتورِ تازه می‌سازد")
        self.convert_button.clicked.connect(self._convert_to_invoice)
        self.convert_button.setVisible(document_type_code in _CONVERTIBLE_TO_INVOICE_TYPES)
        self.footer_layout.addWidget(self.convert_button)

        # طبقِ درخواستِ صریح («در انتهایِ فرم‌هایِ بازرگانی دکمه‌ای که
        # مثلاً ۱۰ فاکتورِ آخرِ طرفِ‌حساب نمایش داده بشه»): فقط وقتی
        # طرفِ‌حسابی انتخاب شده باشد فعال است.
        self.history_button = QPushButton("🕘")
        self.history_button.setObjectName("iconButton")
        self.history_button.setFixedWidth(44)
        self.history_button.setToolTip("آخرین اسنادِ این طرفِ‌حساب — تعدادِ ردیف قابلِ‌تنظیم است")
        self.history_button.clicked.connect(self._open_counterparty_history)
        self.footer_layout.addWidget(self.history_button)

        self.report_button = QPushButton("📄")
        self.report_button.setObjectName("iconButton")
        self.report_button.setFixedWidth(44)
        self.report_button.setToolTip(
            "اجرایِ یکی از گزارش‌هایِ حرفه‌ایِ تخصیص‌داده‌شده به فاکتور -- "
            "برایِ تعریف/ویرایشِ گزارش‌ها به «تنظیماتِ سیستم ›  گزارش‌هایِ حرفه‌ای» مراجعه کنید."
        )
        self.report_button.clicked.connect(self._run_invoice_report)
        self.footer_layout.addWidget(self.report_button)
        self.footer_layout.addStretch(1)

        self.set_field_help([
            (self.date_field, "تاریخِ سند — پایهٔ تعیینِ سالِ مالی."),
            (self.price_list_combo, "اگر برایِ ردیفی بهایِ واحد وارد نشود، از همین فهرستِ قیمت (یا قراردادِ فعالِ طرفِ‌حساب) محاسبه می‌شود."),
        ])

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def _open_counterparty_history(self) -> None:
        company_id = self._company_id()
        counterparty_id = self.counterparty_combo.currentData()
        if company_id is None or counterparty_id is None:
            QMessageBox.information(self, "طرفِ‌حساب", "ابتدا یک طرفِ‌حساب انتخاب کنید.")
            return
        dialog = _CounterpartyHistoryDialog(self, company_id, counterparty_id, self.counterparty_combo.currentText())
        dialog.exec()

    def _run_invoice_report(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._document_id is None:
            QMessageBox.information(self, "گزارش", "ابتدا سند را ذخیره کنید.")
            return
        template_row = pick_report_template(self, company_id, "COMMERCIAL_INVOICE")
        if template_row is None:
            return
        jrxml_path = report_templates_service.get_template_path(template_row.report_template_id, company_id)
        _show_invoice_print(self, company_id, self._document_id, self.counterparty_combo.currentText(), jrxml_path=jrxml_path)

    def _recompute_due_date(self) -> None:
        """طبقِ درخواستِ صریح: با انتخابِ طرفِ‌حساب، موعدِ تسویه از رویِ
        payment_term_days همان طرفِ‌حساب دوباره محاسبه می‌شود -- ویرایشِ
        دستیِ بعدی (بدونِ تغییرِ طرفِ‌حساب) دست‌نخورده می‌ماند."""
        company_id = self._company_id()
        counterparty_id = self.counterparty_combo.currentData()
        if company_id is None or counterparty_id is None:
            return
        due = settlements_service.compute_due_date(
            company_id, self.document_type_code, counterparty_id, self.date_field.date(),
        )
        self.due_date_field.setDate(due or self.date_field.date())

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._items = catalog_service.list_items(company_id, active_only=True)
        self._decimal_places = companies_service.get_base_currency_decimal_places(company_id)
        warehouses = locations_service.list_warehouses(company_id, active_only=True)
        self._warehouses = warehouses
        self._per_line_warehouse_enabled = documents_service.is_per_line_warehouse_enabled(company_id)
        if self.document_type_code == "CONSIGNMENT_IN":
            # طبقِ درخواستِ صریح: در امانیِ ورودی، همین فیلدِ «انبار»
            # جایی‌ست که کالایِ تامین‌کننده تا مصرف/فروش/تسویه نگه‌داری
            # می‌شود -- نه انبارِ نهاییِ فروش.
            self.warehouse_label.setText("انبارِ نگه‌داری")
        else:
            self.warehouse_label.setText("انبار (پیش‌فرضِ ردیف‌ها)" if self._per_line_warehouse_enabled else "انبار")
        current_wh = self.warehouse_combo.currentData()
        self.warehouse_combo.blockSignals(True)
        self.warehouse_combo.clear()
        self.warehouse_combo.addItem("(انتخاب کنید)", None)
        for w in warehouses:
            self.warehouse_combo.addItem(f"{w.code} — {w.name}", w.warehouse_id)
        if current_wh is not None:
            self.warehouse_combo.setCurrentIndex(max(0, self.warehouse_combo.findData(current_wh)))
        self.warehouse_combo.blockSignals(False)

        if self.document_type_code == "CONSIGNMENT_OUT":
            current_consignment_wh = self.consignment_warehouse_combo.currentData()
            self.consignment_warehouse_combo.blockSignals(True)
            self.consignment_warehouse_combo.clear()
            self.consignment_warehouse_combo.addItem("(انتخاب کنید)", None)
            for w in warehouses:
                self.consignment_warehouse_combo.addItem(f"{w.code} — {w.name}", w.warehouse_id)
            if current_consignment_wh is not None:
                self.consignment_warehouse_combo.setCurrentIndex(max(0, self.consignment_warehouse_combo.findData(current_consignment_wh)))
            self.consignment_warehouse_combo.blockSignals(False)

        if self._is_sales:
            counterparty_options = [(c["detail_account_id"], f"{c['code']} — {c['name'] or ''}") for c in dimensions_service.list_customers(company_id)]
            price_lists = pricing_service.list_price_lists(company_id, "SALES")
            channels = pricing_service.list_channels(company_id)
            current_channel = self.channel_combo.currentData()
            self.channel_combo.clear()
            self.channel_combo.addItem("(بدونِ کانال)", None)
            for ch in channels:
                self.channel_combo.addItem(f"{ch.channel_code} — {ch.name}", ch.channel_code)
            if current_channel is not None:
                self.channel_combo.setCurrentIndex(max(0, self.channel_combo.findData(current_channel)))
        else:
            counterparty_options = [(c["detail_account_id"], f"{c['code']} — {c['name'] or ''}") for c in dimensions_service.list_suppliers(company_id)]
            price_lists = pricing_service.list_price_lists(company_id, "PURCHASE")
        current_counterparty = self.counterparty_combo.currentData()
        _fill_options(self.counterparty_combo, counterparty_options)
        if current_counterparty is not None:
            index = self.counterparty_combo.findData(current_counterparty)
            if index >= 0:
                self.counterparty_combo.setCurrentIndex(index)

        current_price_list = self.price_list_combo.currentData()
        self.price_list_combo.clear()
        self.price_list_combo.addItem("(بدونِ فهرستِ قیمت)", None)
        for pl in price_lists:
            # طبقِ درخواستِ صریح: فقط نامِ فهرستِ قیمت نمایش داده شود،
            # نه «کد — نام» (که با عرضِ محدودِ فیلد بریده می‌شد).
            self.price_list_combo.addItem(pl.name, pl.price_list_id)
        if current_price_list is not None:
            index = self.price_list_combo.findData(current_price_list)
            if index >= 0:
                self.price_list_combo.setCurrentIndex(index)

        # طبقِ رفعِ باگِ واقعی («برای حساب X انتخابِ گروه‌هایِ تفصیلیِ
        # الزامی فراموش شده است»): مرکزِ هزینه/پروژه فیلدهایِ همیشه‌حاضرِ
        # هدرند؛ فقط بر اساسِ نگاشتِ حساب‌هایِ این نوعِ سند enable/الزامی
        # می‌شوند (هم‌الگو با فرمِ تنخواه‌گردان).
        self._cost_center_required, cost_center_options = documents_service.get_header_dimension_requirement(
            company_id, self.document_type_code, dimensions_service.COST_CENTER_CODE
        )
        current_cc = self.cost_center_combo.currentData()
        self.cost_center_combo.clear()
        self.cost_center_combo.addItem("(بدونِ مرکزِ هزینه)", None)
        for opt in cost_center_options:
            self.cost_center_combo.addItem(f"{opt.code} — {opt.name or ''}", opt.detail_account_id)
        if current_cc is not None:
            index = self.cost_center_combo.findData(current_cc)
            if index >= 0:
                self.cost_center_combo.setCurrentIndex(index)
        self.cost_center_label.setText("مرکزِ هزینه *" if self._cost_center_required else "مرکزِ هزینه")

        self._project_required, project_options = documents_service.get_header_dimension_requirement(
            company_id, self.document_type_code, dimensions_service.PROJECT_CODE
        )
        current_project = self.project_combo.currentData()
        self.project_combo.clear()
        self.project_combo.addItem("(بدونِ پروژه)", None)
        for opt in project_options:
            self.project_combo.addItem(f"{opt.code} — {opt.name or ''}", opt.detail_account_id)
        if current_project is not None:
            index = self.project_combo.findData(current_project)
            if index >= 0:
                self.project_combo.setCurrentIndex(index)
        self.project_label.setText("پروژه *" if self._project_required else "پروژه")

        if self._document_id is not None:
            self._load_document()
        else:
            self._reset_form(clear_only=True)

        # طبقِ درخواستِ صریح: هر بار این فرم باز می‌شود، فوکوس مستقیم
        # رویِ تاریخ می‌رود — هم‌الگو با inventory_document.py.
        self.date_field.setFocus()
        self.date_field.selectAll()

    def _load_document(self) -> None:
        # طبقِ درخواستِ صریح («سبدِ پیشنهادی»): این نکته فقط بلافاصله
        # بعدِ افزودنِ یک ردیفِ تازه معنا دارد، نه بعدِ هر بارگذاریِ سند
        # (مثلاً بعدِ تایید/تصویب/ثبتِ نهایی) -- پس این‌جا همیشه پنهان
        # می‌شود و فقط _add_line/_add_cross_sell_suggestion دوباره نشانش
        # می‌دهند.
        self._clear_cross_sell_box()
        company_id = self._company_id()
        try:
            doc, lines = documents_service.get_document(self._document_id, company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._status_code = doc.status_code
        self._corrects_document_id = doc.corrects_document_id
        self.page_title.setText(f"{DOC_TYPE_TITLES[self.document_type_code]} #{numerals.to_persian_digits(str(doc.document_no))}")
        self.document_no_field.setText(numerals.to_persian_digits(str(doc.document_no)))
        self.date_field.setDate(doc.document_date)
        index = self.counterparty_combo.findData(doc.counterparty_detail_account_id)
        if index >= 0:
            self.counterparty_combo.setCurrentIndex(index)
        if doc.warehouse_id is not None:
            self.warehouse_combo.setCurrentIndex(max(0, self.warehouse_combo.findData(doc.warehouse_id)))
        if self.document_type_code == "CONSIGNMENT_OUT" and doc.consignment_warehouse_id is not None:
            self.consignment_warehouse_combo.setCurrentIndex(
                max(0, self.consignment_warehouse_combo.findData(doc.consignment_warehouse_id))
            )
        if doc.price_list_id is not None:
            self.price_list_combo.setCurrentIndex(max(0, self.price_list_combo.findData(doc.price_list_id)))
        if self._is_sales and doc.channel_code is not None:
            self.channel_combo.setCurrentIndex(max(0, self.channel_combo.findData(doc.channel_code)))
        if doc.cost_center_detail_account_id is not None:
            self.cost_center_combo.setCurrentIndex(max(0, self.cost_center_combo.findData(doc.cost_center_detail_account_id)))
        if doc.project_detail_account_id is not None:
            self.project_combo.setCurrentIndex(max(0, self.project_combo.findData(doc.project_detail_account_id)))
        if self._is_invoice:
            # طبقِ رفعِ باگِ واقعی: setCurrentIndexِ بالا برایِ
            # counterparty_combo سیگنالِ _recompute_due_date را هم شلیک
            # می‌کند -- این‌جا با مقدارِ واقعاً ذخیره‌شده رویِ سند
            # جای‌گزینش می‌کنیم تا موعدِ دستی‌تنظیم‌شده گم نشود.
            self.due_date_field.setDate(doc.due_date or doc.document_date)
        self.reference_field.setText(doc.reference_no or "")
        self.description_field.setText(doc.description or "")
        self.tax_posting_mode_combo.setCurrentIndex(max(0, self.tax_posting_mode_combo.findData(doc.tax_posting_mode)))
        # طبقِ رفعِ باگِ واقعی («سندِ بهایِ تمام‌شده/موجودی انجام نمی‌شود»
        # — درواقع انجام می‌شد، فقط دیده نمی‌شد): برایِ SALES_INVOICE دو
        # سندِ حسابداریِ کاملاً جدا ساخته می‌شود (طبقِ اصلِ همین فایل، بالایِ
        # سند) — یکی دریافتنی/درآمد (doc.journal_entry_id) و دیگری بهایِ
        # تمام‌شده/موجودی (سندِ انبار خودش journal_entry_id دارد). قبلاً
        # این‌جا فقط اولی نمایش داده می‌شد، پس کاربر گمان می‌کرد دومی هرگز
        # ثبت نشده.
        links = []
        stock_journal_entry_id = None
        if doc.stock_document_id is not None:
            links.append(f"سندِ انبار: #{numerals.to_persian_digits(str(doc.stock_document_id))}")
            try:
                stock_doc_row, _ = inv_documents_service.get_stock_document(doc.stock_document_id, company_id)
                stock_journal_entry_id = stock_doc_row.journal_entry_id
            except ValueError:
                stock_journal_entry_id = None
        if doc.journal_entry_id is not None and stock_journal_entry_id is not None:
            links.append(f"سندِ حسابداریِ فروش/دریافتنی: #{numerals.to_persian_digits(str(doc.journal_entry_id))}")
            links.append(f"سندِ حسابداریِ بهایِ تمام‌شده/موجودی: #{numerals.to_persian_digits(str(stock_journal_entry_id))}")
        elif doc.journal_entry_id is not None:
            links.append(f"سندِ حسابداری: #{numerals.to_persian_digits(str(doc.journal_entry_id))}")
        elif stock_journal_entry_id is not None:
            links.append(f"سندِ حسابداریِ بهایِ تمام‌شده/موجودی: #{numerals.to_persian_digits(str(stock_journal_entry_id))}")
        if doc.source_document_id is not None:
            links.append(f"سندِ مبدا: #{numerals.to_persian_digits(str(doc.source_document_id))}")
        self.links_label.setText("  |  ".join(links))
        self._lines = lines
        self._refresh_lines_table()
        dp = self._decimal_places
        self.summary_cards.set_value("subtotal", numerals.format_money(doc.subtotal_amount, dp))
        self.summary_cards.set_value(
            "discount_tax", numerals.format_money(doc.discount_amount + doc.tax_amount, dp)
        )
        self.summary_cards.set_value("grand_total", numerals.format_money(doc.total_amount, dp))
        if self._supports_cross_sell:
            self._refresh_customer_summary()
        self._apply_status_state()

    def _refresh_lines_table(self) -> None:
        # طبقِ سندِ راهنمایِ UI/UX (بخشِ ۶.۳ — نمایشِ مبلغ‌ها طبقِ تنظیماتِ
        # واحدِ پولی): قبلاً این جدول با str() خامِ Decimal پر می‌شد —
        # نه گروه‌بندیِ سه‌رقمی، نه ارقامِ فارسی، نه تعدادِ اعشارِ درستِ
        # واحدِ پول.
        dp = self._decimal_places
        items_by_id = {it.item_id: it for it in self._items}
        self.lines_table.setRowCount(len(self._lines))
        for row_index, ln in enumerate(self._lines):
            item = items_by_id.get(ln.item_id)
            values = [
                f"{item.code} — {item.name or ''}" if item else str(ln.item_id),
                numerals.format_money(ln.quantity, 3),
                numerals.format_money(ln.unit_price, dp),
                (
                    f"{numerals.format_money(ln.discount_amount, dp)} ({numerals.format_money(ln.discount_percent, 2)}٪)"
                    if ln.discount_percent else numerals.format_money(ln.discount_amount, dp)
                ),
                numerals.format_money(ln.tax_percent, 2),
                numerals.format_money(ln.tax_amount, dp),
                numerals.format_money(ln.line_total, dp),
                ln.description or "",
            ]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, ln.line_id)
                self.lines_table.setItem(row_index, col_index, cell)

    def _apply_status_state(self) -> None:
        self.status_badge.setText(STATUS_LABELS.get(self._status_code, self._status_code))
        is_draft = self._status_code == "DRAFT"
        is_confirmed = self._status_code == "CONFIRMED"
        is_approved = self._status_code == "APPROVED"
        # طبقِ رفعِ باگِ واقعی («سفارشات در حال حاضر ویرایش نمیشه»):
        # برخلافِ فاکتور/برگشت که بعدِ تاییدشدن برایِ همیشه قفل می‌ماند،
        # سفارش/پیش‌فاکتور تا وقتی ثبتِ‌نهایی/لغو نشده قابلِ‌ویرایش است
        # (هم‌الگو با services/commercial_documents.py:_get_editable_document).
        is_order_type = self.document_type_code in _CONVERTIBLE_TO_INVOICE_TYPES
        is_editable = is_draft or (is_order_type and (is_confirmed or is_approved))
        for widget in (
            self.date_field, self.counterparty_combo, self.warehouse_combo, self.price_list_combo, self.channel_combo,
            self.cost_center_combo, self.project_combo, self.reference_field, self.description_field,
            self.consignment_warehouse_combo,
        ):
            widget.setEnabled(is_editable)
        self.save_button.setEnabled(is_editable)
        self.confirm_button.setEnabled(is_draft and self._document_id is not None)
        self.approve_button.setEnabled(is_confirmed)
        self.post_button.setEnabled(is_confirmed or is_approved)
        self.cancel_button.setEnabled(is_draft or is_confirmed or is_approved)
        self.landed_cost_button.setEnabled(is_draft and self._document_id is not None)
        is_posted = self._status_code == "POSTED"
        self.convert_button.setEnabled(is_confirmed or is_approved or is_posted)
        can_correct = is_posted and self._document_id is not None and self._can_correct_posted()
        self.correct_button.setEnabled(can_correct)
        if is_posted and self._document_id is not None and not can_correct:
            # طبقِ گزارشِ صریح («دکمه غیرِفعاله ولی معلوم نیست چرا»): به‌جایِ
            # فقط خاکستری‌کردن، دلیلِ دقیق را در Tooltip نشان می‌دهیم.
            company_id = self._company_id()
            user = app_session.current_user
            reason = documents_service.describe_correction_ineligibility(company_id, user.user_id) if company_id and user else ""
            self.correct_button.setToolTip(f"اصلاحِ فاکتورِ ثبت‌شده -- غیرِفعال است، چون: {reason}")
        else:
            self.correct_button.setToolTip(
                "اصلاحِ فاکتورِ ثبت‌شده — فقط برایِ مدیر و در صورتِ فعال‌بودنِ تنظیمِ «اجازه‌یِ اصلاحِ فاکتورِ ثبت‌شده».\n"
                "سندِ فعلی عیناً و با تاریخِ امروز برگشت می‌خورد (بدونِ تغییرِ تاریخِ فاکتورهایِ قبلی) "
                "و یک پیش‌نویسِ تازه برایِ ویرایش باز می‌شود."
            )

    def _reset_form(self, clear_only: bool = False) -> None:
        self._document_id = None
        self._status_code = "DRAFT"
        self._corrects_document_id = None
        self._lines = []
        self._clear_cross_sell_box()
        self.page_title.setText(f"{DOC_TYPE_TITLES[self.document_type_code]}ِ جدید")
        self.document_no_field.setText("—")
        self.status_label.setText("")
        self.links_label.setText("")
        self.date_field.setDate(datetime.date.today())
        if self._is_invoice:
            self.due_date_field.setDate(datetime.date.today())
        self.counterparty_combo.setCurrentIndex(0)
        self.warehouse_combo.setCurrentIndex(0)
        if self.document_type_code == "CONSIGNMENT_OUT":
            self.consignment_warehouse_combo.setCurrentIndex(0)
        self.price_list_combo.setCurrentIndex(0)
        self.channel_combo.setCurrentIndex(0)
        self.cost_center_combo.setCurrentIndex(0)
        self.project_combo.setCurrentIndex(0)
        self.reference_field.clear()
        self.description_field.clear()
        self.tax_posting_mode_combo.setCurrentIndex(0)
        for key in ("subtotal", "discount_tax", "grand_total"):
            self.summary_cards.set_value(key, "۰")
        self._refresh_lines_table()
        if self._supports_cross_sell:
            self._refresh_customer_summary()
        self._apply_status_state()
        if not clear_only:
            self.refresh()

    def edit_document(self, document_id: int) -> None:
        self._document_id = document_id
        self.refresh()

    def _header_fields(self) -> documents_service.DocumentHeaderFields | None:
        counterparty_id = self.counterparty_combo.currentData()
        if counterparty_id is None:
            self.status_label.setText("انتخابِ طرفِ‌حساب الزامی است.")
            return None
        # طبقِ رفعِ باگِ واقعی («برای حساب X انتخابِ گروه‌هایِ تفصیلیِ
        # الزامی فراموش شده است»): اگر حسابِ نقش‌محورِ این نوعِ سند به
        # مرکزِ هزینه/پروژه نیاز داشته باشد، همین‌جا (پیش از تلاشِ ذخیره)
        # با یک پیامِ روشن جلوگیری می‌شود — نه با خطایِ گنگِ عمقیِ
        # اعتبارسنجیِ سندِ حسابداری در لحظه‌یِ ثبتِ نهایی.
        company_id = self._company_id()
        if company_id is not None:
            if self.cost_center_combo.currentData() is None and self._cost_center_required:
                self.status_label.setText("انتخابِ «مرکزِ هزینه» برایِ این نوعِ سند الزامی است.")
                return None
            if self.project_combo.currentData() is None and self._project_required:
                self.status_label.setText("انتخابِ «پروژه» برایِ این نوعِ سند الزامی است.")
                return None
        consignment_warehouse_id = None
        if self.document_type_code == "CONSIGNMENT_OUT":
            consignment_warehouse_id = self.consignment_warehouse_combo.currentData()
            if consignment_warehouse_id is None:
                self.status_label.setText("انتخابِ «انبارِ نمایندگی/طرفِ امانی» الزامی است.")
                return None
        company = app_session.current_company
        return documents_service.DocumentHeaderFields(
            counterparty_detail_account_id=counterparty_id, currency_id=company.base_currency_id,
            warehouse_id=self.warehouse_combo.currentData(),
            consignment_warehouse_id=consignment_warehouse_id,
            channel_code=self.channel_combo.currentData() if self._is_sales else None,
            price_list_id=self.price_list_combo.currentData(),
            cost_center_detail_account_id=self.cost_center_combo.currentData(),
            project_detail_account_id=self.project_combo.currentData(),
            due_date=self.due_date_field.date() if self._is_invoice else None,
            reference_no=self.reference_field.text().strip() or None,
            description=self.description_field.text().strip() or None,
            tax_posting_mode=self.tax_posting_mode_combo.currentData() if self._supports_tax_posting_mode else None,
        )

    def _save_header(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        fields = self._header_fields()
        if fields is None:
            return
        is_new = self._document_id is None
        try:
            if is_new:
                self._document_id = documents_service.create_document(
                    company_id, app_session.current_user.user_id, self.document_type_code, self.date_field.date(), fields
                )
            else:
                # طبقِ رفعِ باگِ واقعی: قبلاً ذخیره‌یِ هدرِ سندِ ازپیش‌موجود
                # اصلاً هیچ صدازدنی به سرویس نداشت — تغییراتِ فیلدهایِ هدر
                # (برایِ سفارش/پیش‌فاکتورِ تاییدشده، که حالا قابلِ‌ویرایش
                # است) در سکوت گم می‌شد.
                documents_service.update_document_header(self._document_id, company_id, self.date_field.date(), fields)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            QMessageBox.warning(self, "خطا در ذخیره", str(exc))
            return
        self._load_document()
        # طبقِ رفعِ باگِ واقعی («بعدِ ذخیره هیچ پیامی نمی‌دهد»): قبلاً این
        # مسیرِ موفقیت فقط status_label را خالی می‌کرد — بدونِ هیچ
        # تاییدِ مثبتی، کاربر نمی‌فهمید سند واقعاً ذخیره شده یا نه.
        theme.set_status_label(
            self.status_label, "سند به‌عنوانِ پیش‌نویس ذخیره شد." if is_new else "تغییراتِ سند ذخیره شد.", ok=True,
        )

    def _ensure_saved(self) -> bool:
        if self._document_id is None:
            self._save_header()
        return self._document_id is not None

    def _flush_header_changes(self) -> bool:
        """طبقِ گزارشِ صریح («نوعِ ثبت را عوض می‌کنم ولی اثر نمی‌کند»):
        اگر کاربر پیش از تاییدِ سند یک فیلدِ هدر (مثلاً نوعِ ثبتِ رسمی/
        غیررسمی) را تغییر داده باشد ولی دوباره رویِ «ذخیره» نزده باشد،
        آن تغییر هرگز به سرور نمی‌رسید -- confirm_document فقط وضعیت را
        عوض می‌کند، هیچ فیلدی از خودِ فرم نمی‌خواند. حالا پیش از هر
        تاییدی، آخرین مقادیرِ فرم دوباره ذخیره می‌شود تا تصمیمِ رسمی/
        غیررسمی (و تسهیمِ هزینه‌هایِ جانبی، که هردو در لحظهٔ Post خوانده
        می‌شوند) همیشه با چیزی که کاربر واقعاً رویِ صفحه می‌بیند یکی باشد."""
        if self._document_id is None:
            return True
        company_id = self._company_id()
        if company_id is None:
            return False
        fields = self._header_fields()
        if fields is None:
            return False
        try:
            documents_service.update_document_header(self._document_id, company_id, self.date_field.date(), fields)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            QMessageBox.warning(self, "خطا در ذخیره", str(exc))
            return False
        return True

    def _warn_if_consignment_cost_mixing(self, item_id: int | None, warehouse_id: int | None) -> None:
        """طبقِ بررسیِ موردِ ۳ (رهگیریِ کالایِ امانیِ ورودی): وقتی روشِ
        بهایابی WEIGHTED_AVERAGE است، اگر همین انبار از قبل موجودیِ
        *خریداری‌شده* (نه امانی) از همین کالا هم داشته باشد، بهایِ
        توافقیِ امانی با آن مخلوط می‌شود و ممکن است در تسویه‌یِ نهایی
        (که همیشه دقیقاً با بهایِ توافقیِ اصلی جمع می‌بندد) یک اختلافِ
        جزئی در حسابِ موجودیِ کالا باقی بگذارد. این فقط یک هشدارِ
        اطلاع‌رسانی است -- هیچ‌چیزی مسدود نمی‌شود، چون فروشِ امانیِ
        تسویه‌نشده پیش از تسویه یک ویژگیِ آگاهانه و تست‌شده است."""
        if self.document_type_code != "CONSIGNMENT_IN" or item_id is None or warehouse_id is None:
            return
        company_id = self._company_id()
        if company_id is None:
            return
        item = next((it for it in self._items if it.item_id == item_id), None)
        if item is not None and item.costing_method_code not in (None, "WEIGHTED_AVERAGE"):
            return
        on_hand_by_warehouse = {r.warehouse_id: r.quantity_on_hand for r in engine_service.get_item_stock_by_warehouse(company_id, item_id)}
        on_hand = on_hand_by_warehouse.get(warehouse_id, decimal.Decimal(0))
        unsettled = consignment_service.unsettled_consignment_in_quantity(company_id, item_id, warehouse_id)
        if on_hand > unsettled:
            QMessageBox.information(
                self, "هشدارِ اختلاطِ بهایِ میانگین",
                "این انبار از قبل، علاوه‌بر امانی، موجودیِ خریداری‌شده از همین کالا هم دارد. "
                "چون روشِ بهایابی «میانگینِ موزون» است، بهایِ توافقیِ امانی با بهایِ خریدِ واقعی مخلوط "
                "می‌شود و ممکن است در تسویه‌یِ نهاییِ امانی یک اختلافِ جزئی در حسابِ موجودیِ کالا "
                "باقی بماند. برایِ جلوگیریِ کامل از این اختلاط، توصیه می‌شود کالاهایِ امانیِ ورودی را "
                "در یک انبارِ مجزا نگه‌داری کنید.",
            )

    def _add_line(self) -> None:
        if not self._ensure_saved():
            return
        dialog = _LineDialog(
            self, self._items, self._company_id(), self._main_window, self._decimal_places,
            counterparty_id=self.counterparty_combo.currentData(), price_list_id=self.price_list_combo.currentData(),
            document_type_code=self.document_type_code, document_date=self.date_field.date(),
            warehouses=self._warehouses, default_warehouse_id=self.warehouse_combo.currentData(),
            per_line_warehouse_enabled=self._per_line_warehouse_enabled,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        fields = dialog.result_fields()
        try:
            documents_service.add_line(self._document_id, self._company_id(), **fields)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._warn_if_consignment_cost_mixing(fields.get("item_id"), fields.get("warehouse_id") or self.warehouse_combo.currentData())
        self._load_document()
        self._refresh_cross_sell_suggestion(fields.get("item_id"))

    def _refresh_customer_summary(self) -> None:
        """طبقِ درخواستِ صریح («فاکتورِ فوق‌هوشمند»): خلاصه‌یِ وضعیتِ همان
        مشتریِ رویِ هدر -- آخرین خرید، میانگینِ فاصله‌یِ خرید، سقفِ اعتبار،
        بدهیِ جاری، و امتیاز/ردیفِ مشتری -- درست زیرِ هدرِ سند. طبقِ
        درخواستِ صریحِ بعدی، خودِ فیلدِ انتخابِ مشتری هم رنگ‌آمیزی می‌شود:
        گرادیانِ افقی از رنگِ (قرمز تا سبز، متناسب با امتیاز) در سمتِ چپ
        تا سفید در سمتِ راست -- تا نامِ مشتری همیشه خوانا بماند."""
        company_id = self._company_id()
        counterparty_id = self.counterparty_combo.currentData()
        if not self._supports_cross_sell or company_id is None or counterparty_id is None:
            self.customer_summary_box.setVisible(False)
            self.counterparty_combo.setStyleSheet("")
            return

        score_row = assistant_service.get_customer_score(company_id, counterparty_id)
        if score_row is None:
            self.customer_summary_box.setVisible(False)
            self.counterparty_combo.setStyleSheet("")
            return

        gradient_color = _score_gradient_color(score_row.score)
        self.counterparty_combo.setStyleSheet(
            "QComboBox { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 {gradient_color}, stop:1 white); color: #1a1a1a; }}"
        )

        parts = [f"{score_row.emoji} امتیازِ مشتری: {numerals.to_persian_digits(str(score_row.score))} ({score_row.tier_label})"]
        if score_row.days_since_last is not None:
            parts.append(f"آخرین خرید: {numerals.to_persian_digits(str(score_row.days_since_last))} روز پیش")
        if score_row.avg_interval_days is not None:
            parts.append(f"میانگینِ خرید: هر {numerals.to_persian_digits(str(round(score_row.avg_interval_days)))} روز")

        profile = partners_service.get_customer_profile(counterparty_id)
        if profile is not None and profile.credit_limit_amount:
            parts.append(f"سقفِ اعتبار: {numerals.format_company_amount(profile.credit_limit_amount)}")
            exposure = credit_service.compute_customer_exposure(company_id, counterparty_id)
            parts.append(f"بدهیِ جاری: {numerals.format_company_amount(exposure)}")

        self.customer_summary_label.setText("  |  ".join(parts))
        self.customer_summary_box.setVisible(True)

    def _clear_cross_sell_box(self) -> None:
        self._cross_sell_suggestions = []
        while self._cross_sell_layout.count():
            item = self._cross_sell_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
        self.cross_sell_box.setVisible(False)

    def _refresh_cross_sell_suggestion(self, item_id: int | None) -> None:
        """طبقِ درخواستِ صریح («سبدِ پیشنهادی»): بعدِ افزودنِ یک ردیف، اگر
        کالاهایی هست که همینِ مشتریِ رویِ هدرِ سند معمولاً همراهِ همین
        کالا خریده، همه‌شان این‌جا نشان داده می‌شوند (نه فقط یکی) --
        کاملاً غیرِمزاحم -- بدونِ مشتریِ انتخاب‌شده یا بدونِ سابقه‌یِ
        کافی، هیچ‌چیزی نمایش داده نمی‌شود.

        باگِ واقعیِ گزارش‌شده (۱): چون کالایِ A و B معمولاً هردو باهم
        دیده می‌شوند، بعدِ افزودنِ B (که خودش به‌خاطرِ A پیشنهاد شده
        بود)، دوباره خودِ A پیشنهاد می‌شد -- در حالی‌که از قبل در همین
        فاکتور هست. پس این‌جا کالاهایی که از پیش در سندِ جاری‌اند فیلتر
        می‌شوند.

        باگِ واقعیِ گزارش‌شده (۲): پیام به «مشتری‌ها» به‌طورِ کلی اشاره
        می‌کرد، در حالی‌که نامِ مشتریِ مشخص از قبل رویِ هدر هست -- حالا
        فقط سابقه‌یِ خودِ همین مشتری در نظر گرفته می‌شود و در متنِ پیام
        هم به نامِ او اشاره می‌شود."""
        self._clear_cross_sell_box()
        company_id = self._company_id()
        counterparty_id = self.counterparty_combo.currentData()
        if not self._supports_cross_sell or item_id is None or company_id is None or counterparty_id is None:
            return
        existing_item_ids = {ln.item_id for ln in self._lines}
        suggestions = [
            s
            for s in documents_service.suggest_frequently_bought_together(
                company_id, item_id, limit=10, counterparty_detail_account_id=counterparty_id,
            )
            if s.item_id not in existing_item_ids
        ]
        if not suggestions:
            return
        customer_name = self.counterparty_combo.currentText()
        for suggestion in suggestions:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            label = QLabel(
                f"💡 «{customer_name}» معمولاً همراهِ این کالا «{suggestion.item_code} — {suggestion.item_name}» را هم می‌خرد "
                f"({numerals.to_persian_digits(str(suggestion.confidence_percent))}٪)"
            )
            label.setWordWrap(True)
            row_layout.addWidget(label, stretch=1)
            add_button = QPushButton("➕ افزودن")
            add_button.setObjectName("flatButton")
            add_button.clicked.connect(lambda _checked=False, s=suggestion: self._add_cross_sell_suggestion(s))
            row_layout.addWidget(add_button)
            self._cross_sell_layout.addWidget(row_widget)
        self._cross_sell_suggestions = suggestions
        self.cross_sell_box.setVisible(True)
        # طبقِ رفعِ بازخوردِ صریح («پیام زیرِ فرم می‌ماند و اسکرول هم به
        # آن نمی‌رسد»): ensureWidgetVisible باید *بعدِ* اجرایِ واقعیِ
        # چیدمانِ Qt (که هنوز اندازه/جایگاهِ تازه‌یِ این ویجت را محاسبه
        # نکرده) صدا زده شود، نه بلافاصله در همین Frame -- وگرنه با
        # جایگاهِ کهنه/نادرست کار می‌کند.
        QTimer.singleShot(0, lambda: self._scroll.ensureWidgetVisible(self.cross_sell_box))

    def _add_cross_sell_suggestion(self, suggestion) -> None:
        company_id = self._company_id()
        if self._document_id is None or company_id is None:
            return
        item = next((it for it in self._items if it.item_id == suggestion.item_id), None)
        if item is None:
            return
        try:
            documents_service.add_line(
                self._document_id, company_id, item_id=item.item_id, uom_id=item.base_uom_id,
                quantity=decimal.Decimal(1), quantity_base=decimal.Decimal(1),
                warehouse_id=self.warehouse_combo.currentData() if self.warehouse_combo is not None else None,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._load_document()
        self._refresh_cross_sell_suggestion(item.item_id)

    def _selected_line(self):
        selected = self.lines_table.selectedItems()
        if not selected:
            return None
        line_id = selected[0].data(Qt.UserRole)
        return next((ln for ln in self._lines if ln.line_id == line_id), None)

    def _edit_line(self, *_args) -> None:
        line = self._selected_line()
        if line is None or self._document_id is None:
            return
        initial = {
            "item_id": line.item_id, "quantity": line.quantity, "unit_price": line.unit_price,
            "discount_amount": line.discount_amount, "discount_percent": line.discount_percent,
            "tax_percent": line.tax_percent, "description": line.description,
            "warehouse_id": line.warehouse_id,
        }
        dialog = _LineDialog(
            self, self._items, self._company_id(), self._main_window, self._decimal_places, initial,
            warehouses=self._warehouses, default_warehouse_id=self.warehouse_combo.currentData(),
            per_line_warehouse_enabled=self._per_line_warehouse_enabled,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        fields = dialog.result_fields()
        try:
            documents_service.delete_line(line.line_id, self._document_id, self._company_id())
            documents_service.add_line(self._document_id, self._company_id(), **fields)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._warn_if_consignment_cost_mixing(fields.get("item_id"), fields.get("warehouse_id") or self.warehouse_combo.currentData())
        self._load_document()

    def _delete_line(self) -> None:
        line = self._selected_line()
        if line is None or self._document_id is None:
            return
        confirm = QMessageBox.question(self, "حذفِ ردیف", "این ردیف حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            documents_service.delete_line(line.line_id, self._document_id, self._company_id())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._load_document()

    def _confirm(self) -> None:
        if self._document_id is None:
            return
        if not self._flush_header_changes():
            return
        try:
            documents_service.confirm_document(self._document_id, self._company_id(), app_session.current_user.user_id)
        except ValueError as exc:
            # طبقِ رفعِ باگِ واقعی: قبلاً این خطا فقط در یک برچسبِ ساکت
            # نمایش داده می‌شد — کاربر (به‌خصوص خطایِ «حساب هنوز در
            # تنظیمات مشخص نشده») به‌راحتی آن را نمی‌دید و فکر می‌کرد
            # هیچ اتفاقی نیفتاده. حالا هم‌الگو با خطاهایِ ردیف، یک
            # دیالوگِ مسدودکننده هم نمایش می‌دهد.
            self.status_label.setText(str(exc))
            QMessageBox.warning(self, "خطا در تاییدِ سند", str(exc))
            return
        self._load_document()
        theme.set_status_label(self.status_label, "سند تایید شد.", ok=True)

    def _approve(self) -> None:
        if self._document_id is None:
            return
        try:
            documents_service.approve_document(self._document_id, self._company_id())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            QMessageBox.warning(self, "خطا در تصویبِ سند", str(exc))
            return
        self._load_document()
        theme.set_status_label(self.status_label, "سند تصویب شد.", ok=True)

    def _post(self) -> None:
        if self._document_id is None:
            return
        confirm = QMessageBox.question(
            self, "ثبتِ نهایی", "این سند ثبتِ نهایی شود؟ پسِ این کار، سند دیگر قابلِ‌ویرایش/حذف نیست.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        company_id = self._company_id()
        try:
            if self._corrects_document_id is not None:
                result = documents_service.post_invoice_correction(self._document_id, company_id, app_session.current_user.user_id)
            else:
                result = documents_service.post_document(self._document_id, company_id, app_session.current_user.user_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            QMessageBox.warning(self, "خطا در ثبتِ نهایی", str(exc))
            return
        # طبقِ رفعِ باگِ واقعی («بعدِ تایید، فرم ریست نمی‌شود»): بعدِ ثبتِ
        # نهایی، سند برایِ همیشه قفل است — دیگر کاری رویِ همین رکورد از
        # این فرم ممکن نیست، پس فرم برایِ سندِ بعدی ریست می‌شود، به‌جایِ
        # نگه‌داشتنِ سندِ بسته‌شده روی صفحه.
        je_note = (
            f" (سندِ حسابداریِ #{numerals.to_persian_digits(str(result.journal_entry_id))} ساخته شد.)"
            if result.journal_entry_id is not None else ""
        )
        # طبقِ درخواستِ صریح («بعدِ تاییدِ فاکتورِ فروش فرمِ دریافت باز
        # بشه ... همین‌طور برایِ فاکتورِ خرید فرمِ پرداخت»): پیش از ریست،
        # اطلاعاتِ لازم برایِ فرمِ دریافت/پرداخت را نگه می‌داریم.
        posted_doc, _ = documents_service.get_document(self._document_id, company_id)
        posted_type = self.document_type_code
        posted_counterparty_id = posted_doc.counterparty_detail_account_id
        posted_total = posted_doc.total_amount
        posted_no = posted_doc.document_no
        self._reset_form()
        theme.set_status_label(self.status_label, f"سند ثبتِ نهایی شد.{je_note}", ok=True)

        if posted_type in ("SALES_INVOICE", "PURCHASE_INVOICE") and self._main_window is not None:
            is_sales = posted_type == "SALES_INVOICE"
            noun = "دریافتِ وجه" if is_sales else "پرداختِ وجه"
            confirm_payment = QMessageBox.question(
                self, noun,
                f"آیا برایِ این فاکتور {noun} ثبت می‌شود؟\n(اگر نسیه است و هنوز پرداختی صورت نگرفته، «خیر» را انتخاب کنید.)",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm_payment == QMessageBox.Yes:
                nav_code = "TREASURY_RECEIPT" if is_sales else "TREASURY_PAYMENT"
                description = f"بابتِ {DOC_TYPE_TITLES[posted_type]}ِ #{numerals.to_persian_digits(str(posted_no))}"
                self._main_window.open_screen(
                    nav_code,
                    then=lambda screen: screen.prefill_for_invoice(posted_counterparty_id, posted_total, description),
                )

    def _cancel(self) -> None:
        if self._document_id is None:
            return
        confirm = QMessageBox.question(self, "لغوِ سند", "این سند لغو شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            documents_service.cancel_document(self._document_id, self._company_id())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            QMessageBox.warning(self, "خطا در لغوِ سند", str(exc))
            return
        # لغو هم مثلِ ثبتِ نهایی یک وضعیتِ نهایی‌ست — سند دیگر رویِ همین
        # فرم قابلِ‌ادامه‌کاری نیست، پس فرم برایِ سندِ بعدی ریست می‌شود.
        self._reset_form()
        theme.set_status_label(self.status_label, "سند لغو شد.", ok=True)

    def _open_landed_costs(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._document_id is None:
            return
        dialog = _LandedCostDialog(self._document_id, company_id, self)
        dialog.exec()

    def _can_correct_posted(self) -> bool:
        company_id = self._company_id()
        user = app_session.current_user
        if company_id is None or user is None:
            return False
        return documents_service.can_correct_posted_document(company_id, user.user_id)

    def _correct_invoice(self) -> None:
        if self._document_id is None:
            return
        company_id = self._company_id()
        confirm = QMessageBox.question(
            self, "اصلاحِ فاکتور",
            "این فاکتور اصلاح شود؟\n"
            "سندِ انبار و حسابداریِ فعلی عیناً و با تاریخِ امروز برگشت می‌خورد (بدونِ تغییرِ تاریخِ فاکتورهایِ ثبت‌شده‌یِ "
            "دیگر) و یک پیش‌نویسِ تازه با اطلاعاتِ همین فاکتور برایِ ویرایش باز می‌شود.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            new_document_id = documents_service.start_invoice_correction(
                self._document_id, company_id, app_session.current_user.user_id
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا در اصلاحِ فاکتور", str(exc))
            return
        self.edit_document(new_document_id)
        theme.set_status_label(
            self.status_label,
            f"فاکتورِ اصلی برگشت خورد و اصلاح شد؛ اکنون پیش‌نویسِ اصلاحیِ #{numerals.to_persian_digits(str(new_document_id))} را ویرایش کنید.",
            ok=True,
        )

    def _convert_to_invoice(self) -> None:
        if self._document_id is None:
            return
        company_id = self._company_id()
        try:
            fulfillment = documents_service.get_line_fulfillment(self._document_id, company_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا در تبدیل به فاکتور", str(exc))
            return
        if not any(f.remaining_quantity > 0 for f in fulfillment):
            QMessageBox.information(self, "تبدیل به فاکتور", "چیزی برایِ تبدیل به فاکتور باقی نمانده است — کل این سند قبلاً فاکتور شده.")
            return
        items_by_id = {it.item_id: it for it in self._items}
        dialog = _ConvertToInvoiceDialog(self, fulfillment, items_by_id)
        if dialog.exec() != QDialog.Accepted:
            return
        converts_to_sales = self.document_type_code in _CONVERTS_TO_SALES_INVOICE
        target_title = "فاکتورِ فروش" if converts_to_sales else "فاکتورِ خرید"
        try:
            new_document_id = documents_service.convert_to_invoice(
                self._document_id, company_id, app_session.current_user.user_id, datetime.date.today(),
                line_quantities=dialog.result_quantities(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا در تبدیل به فاکتور", str(exc))
            return
        # طبقِ درخواستِ صریح («مانده‌یِ هر سفارش را بتوان دید و دوباره به
        # فاکتور تبدیل کرد»): برخلافِ نسخه‌یِ قبلی که به فاکتورِ تازه
        # می‌پرید، این‌جا رویِ همان سفارش می‌مانیم و دوباره بارگذاری
        # می‌کنیم تا مانده‌یِ به‌روزشده بلافاصله دیده شود.
        self._load_document()
        theme.set_status_label(
            self.status_label,
            f"{target_title} #{numerals.to_persian_digits(str(new_document_id))} از رویِ این سند ساخته شد.",
            ok=True,
        )
