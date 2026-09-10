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
import types

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
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
from peecha.reporting import registry as report_templates_registry
from peecha.services import chart_of_accounts as coa_service
from peecha.services import commercial_consignment as consignment_service
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import commercial_purchasing as purchasing_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import companies as companies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_engine as engine_service
from peecha.services import inventory_documents as inv_documents_service
from peecha.services import inventory_locations as locations_service
from peecha.services import item_variants as variants_service
from peecha.services import report_templates as report_templates_service
from peecha.services import roles as roles_service
from peecha.services import sales_assistant as assistant_service
from peecha.services import treasury as treasury_service
from peecha.ui import theme
from peecha.ui.screens.inventory_document import _enter_signal
from peecha.ui.screens.jasper_preview import JasperReportPreviewDialog
from peecha.ui.screens.journal_entry import _AmountField, _fill_options, _make_searchable_combo
from peecha.ui.screens.report_template_settings import pick_report_template
from peecha.ui.screens.treasury_voucher import (
    _EnterComboBox,
    _RowAmountField,
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
# طبقِ درخواستِ صریح («اگر اجازهٔ موجودیِ منفی نباشد فقط متغیرهایی که
# موجودی دارند نشان داده شوند»): این فیلترِ موجودی فقط برایِ اسنادی معنا
# دارد که واقعاً موجودی را کم می‌کنند -- نه اسنادی که موجودی را اضافه
# می‌کنند (خرید/برگشت از فروش/امانیِ ورودی)، چون آن‌جا نبودِ موجودیِ
# فعلی اصلاً محدودیت نیست (دقیقاً برایِ همین دارید کالا وارد می‌کنید).
_STOCK_OUTBOUND_TYPES = ("SALES_ORDER", "SALES_PROFORMA", "SALES_INVOICE", "CONSIGNMENT_OUT", "PURCHASE_RETURN")
# طبقِ درخواستِ صریح («سفارش/پیش‌فاکتور بتواند به فاکتور تبدیل شود»):
# امانیِ خروجی/ورودی هم از همین مکانیزم (تبدیلِ مرحله‌ایِ مانده به فاکتورِ
# واقعیِ فروش/خرید) استفاده می‌کنند.
_CONVERTIBLE_TO_INVOICE_TYPES = (
    "SALES_ORDER", "SALES_PROFORMA", "PURCHASE_ORDER", "PURCHASE_PROFORMA", "CONSIGNMENT_OUT", "CONSIGNMENT_IN",
)
_POST_BUTTON_DEFAULT_TOOLTIP = "۴) ثبتِ نهایی — قطعی و برگشت‌ناپذیر؛ سندِ انبار/حسابداریِ واقعی همین‌جا ساخته می‌شود"
# طبقِ همان تفکیک: کدام از انواعِ قابلِ‌تبدیل به فاکتورِ فروش تبدیل
# می‌شوند (بقیه به فاکتورِ خرید) -- برایِ عنوانِ پیامِ موفقیتِ تبدیل.
_CONVERTS_TO_SALES_INVOICE = ("SALES_ORDER", "SALES_PROFORMA", "CONSIGNMENT_OUT")
# طبقِ طرحِ نمونه‌یِ ارسالیِ کاربر: یک ستونِ شمارهٔ ردیف («#») در ابتدا و
# یک ستونِ «عملیات» (ویرایش/حذفِ همان ردیف) در انتها، به‌جایِ خوشه‌یِ
# جداگانه‌یِ دکمه‌هایِ زیرِ جدول که قبلاً روی «ردیفِ انتخاب‌شده»یِ کلی
# عمل می‌کرد -- حالا هر دکمه دقیقاً برایِ همان ردیفی است که رویش است.
_LINE_COLUMNS = ["#", "کالا", "مقدار", "بهایِ واحد", "تخفیف", "درصدِ مالیات", "مالیات", "جمعِ ردیف", "توضیح", "عملیات"]
_HISTORY_COLUMNS = ["نوع", "شماره", "تاریخ", "وضعیت", "جمعِ کل"]


# طبقِ درخواستِ صریح («به‌جایِ خلاصهٔ فاکتور، پرینتِ فاکتور را نمایش
# بده»): چون «خلاصه»یِ متنیِ قبلی اطلاعاتِ به‌دردبخوری نداشت، این‌جا به‌جایِ
# آن، از همان زیرساختِ چاپِ HTML/QPrintPreviewDialogِ رسیدِ دریافت‌وپرداخت
# (treasury_voucher.py) -- که از پیش جواب داده -- برایِ ساختِ یک پیش‌نمایشِ
# چاپیِ کاملِ سند (هدر + جدولِ ردیف‌ها + جمعِ کل) استفاده می‌شود.
def _build_invoice_print_html(
    company_name: str, doc, lines: list, items_by_id: dict, counterparty_label: str, decimal_places: int,
    font_family: str, header_text: str | None = None, footer_text: str | None = None,
) -> str:
    esc = _escape_receipt_html
    header_html = (
        f'<div style="text-align:center; font-size:10pt; margin-bottom:6px;">{esc(header_text)}</div>' if header_text else ""
    )
    footer_html = (
        f'<div style="text-align:center; font-size:10pt; margin-top:12px;">{esc(footer_text)}</div>' if footer_text else ""
    )
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
      {header_html}
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
      {footer_html}
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
    header_text: str | None = None,
    footer_text: str | None = None,
    form_code: str = "COMMERCIAL_INVOICE",
    printer_names: list[str] | None = None,
    fast: bool = False,
) -> None:
    doc, lines = documents_service.get_document(document_id, company_id)

    # طبقِ درخواستِ صریح («ارسالِ هم‌زمانِ چند فاکتور به چند پرینترِ
    # مختلف»): اگر بر اساسِ گروهِ POSِ اقلامِ این فاکتور، یک یا چند
    # پرینترِ مشخص resolve شده باشد، مستقیم رویِ همان(ها) چاپ می‌شود --
    # یک پیش‌نمایش به‌ازایِ هر پرینترِ متمایز؛ مسیرِ حرفه‌ایِ Jasper (که
    # فعلاً پرینترِ مقصد را نمی‌گیرد) این‌جا دور زده می‌شود.
    #
    # طبقِ رفعِ باگِ واقعیِ گزارش‌شده («دکمهٔ تسویه با پرینت خیلی طول
    # می‌کشد»): fast=True (پیش‌فرضِ فیشِ POS) هم همین مسیرِ سریعِ HTML را
    # انتخاب می‌کند -- حتی وقتی هیچ پرینترِ اختصاصی‌ای resolve نشده --
    # چون Jasper هر بار یک JVMِ تازه بالا می‌آورد (چند ثانیه طول می‌کشد).
    if printer_names or fast:
        decimal_places = companies_service.get_base_currency_decimal_places(company_id)
        if counterparty_label is None:
            counterparty_label = dimensions_service.get_detail_account_label(doc.counterparty_detail_account_id)
        company_name = app_session.current_company.display_name if app_session.current_company else ""
        items_by_id = {it.item_id: it for it in catalog_service.list_items(company_id)}
        html = _build_invoice_print_html(
            company_name, doc, lines, items_by_id, counterparty_label, decimal_places, _receipt_font_family(),
            header_text=header_text, footer_text=footer_text,
        )
        for printer_name in (printer_names or [None]):
            _print_receipt_document(parent, html, printer_name=printer_name)
        return

    if jasper_bridge.is_available():
        # طبقِ رجیستریِ گزارش‌هایِ حرفه‌ای: اگر مسیرِ صریحی داده نشده
        # (مثلاً از دکمه‌یِ «📄 گزارش»ِ خودِ فرم)، گزارشِ پیش‌فرضِ همین
        # شرکت برایِ همین form_code استفاده می‌شود، وگرنه قالبِ پایه‌یِ
        # داخلِ ریپازیتوری برایِ همان form_code -- طبقِ درخواستِ صریح
        # («نمونهٔ فاکتورِ تک‌فروشی مجزا از فاکتورِ عمده») صفحه‌یِ POS
        # اکنون form_code="POS_RECEIPT" را جدا از فاکتورِ عمده می‌فرستد.
        if jrxml_path is None:
            jrxml_path = report_templates_service.get_default_template_path(company_id, form_code)
        if jrxml_path is None:
            jrxml_path = jasper_bridge.template_path(report_templates_registry.FORM_DEFINITIONS[form_code]["base_template"])
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
        header_text=header_text, footer_text=footer_text,
    )
    _print_receipt_document(parent, html)


class _CounterpartyHistoryDialog(QDialog):
    """طبقِ درخواستِ صریح: مثلاً ۱۰ فاکتورِ آخرِ طرفِ‌حساب -- با تعدادِ
    ردیفِ قابلِ‌تنظیم. دابل‌کلیک رویِ هر ردیف، خلاصهٔ همان سند را نمایش
    می‌دهد -- طبقِ رفعِ باگِ واقعی، ناوبریِ مستقیم به آن سند از این‌جا
    عمداً حذف شده، چون آن صفحه (به‌ازایِ هر نوعِ سند) نمونه‌یِ واحد و
    مشترکِ همه‌جایِ برنامه است و چنین ناوبری‌ای هر ویرایشِ درحال‌انجامِ
    کاربر رویِ همان صفحه را پاک می‌کرد."""

    def __init__(
        self, parent: QWidget, company_id: int, counterparty_id: int, counterparty_label: str,
        *, default_document_type_code: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._company_id = company_id
        self._counterparty_id = counterparty_id
        self._counterparty_label = counterparty_label
        self.setWindowTitle(f"آخرین اسنادِ «{counterparty_label}»")
        self.setMinimumWidth(600)
        self.setMinimumHeight(420)
        layout = QVBoxLayout(self)

        # طبقِ گزارشِ صریحِ کاربر («هم فاکتور و هم سفارش نمایش می‌دهد،
        # فقط خریدِ قطعی مهم است»): پیش‌فرض رویِ همان نوعِ سندِ قطعی
        # (فاکتور) قرار می‌گیرد، ولی این فیلتر برایِ دیدنِ بقیه‌یِ انواع
        # هم قابلِ‌تغییر است.
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("نوعِ سند:"))
        self.type_combo = _EnterComboBox()
        self.type_combo.addItem("همه‌یِ انواع", None)
        for code, title in DOC_TYPE_TITLES.items():
            self.type_combo.addItem(title, code)
        default_index = self.type_combo.findData(default_document_type_code)
        self.type_combo.setCurrentIndex(default_index if default_index >= 0 else 0)
        self.type_combo.currentIndexChanged.connect(self._refresh)
        filter_row.addWidget(self.type_combo)
        filter_row.addSpacing(16)
        filter_row.addWidget(QLabel("تعدادِ ردیفِ نمایش‌داده‌شده:"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 500)
        self.count_spin.setValue(10)
        self.count_spin.valueChanged.connect(self._refresh)
        filter_row.addWidget(self.count_spin)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

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
            self._company_id, document_type_code=self.type_combo.currentData(),
            counterparty_detail_account_id=self._counterparty_id, limit=self.count_spin.value(),
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
        lock_price: bool = False, lock_discount: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ردیفِ فاکتور")
        self.setMinimumWidth(380)
        self._company_id = company_id
        self._counterparty_id = counterparty_id
        self._price_list_id = price_list_id
        self._document_type_code = document_type_code
        self._document_date = document_date
        self._main_window = main_window
        self._decimal_places = decimal_places
        self._uom_decimal_places = {u.uom_id: u.decimal_places for u in catalog_service.list_uoms(company_id)}
        self._is_new_row = initial is None
        self._default_warehouse_id = default_warehouse_id
        self._warehouses_by_id = {w.warehouse_id: w for w in (warehouses or [])}
        layout = QVBoxLayout(self)
        self._items_by_id = {it.item_id: it for it in items}
        # طبقِ درخواستِ صریح («کالایِ اصلیِ دارایِ متغیر نباید مستقیم در
        # سند ثبت شود؛ در جستجو فقط کالاهایِ اصلی بیایند و خودِ متغیرها
        # نیایند؛ بعدِ انتخابِ کالایِ اصلی، متغیرش انتخاب شود»): لیستِ
        # کمبویِ کالا فقط شاملِ کالاهایِ غیرمتغیر (variant_parent_item_id
        # خالی) است -- خودِ ردیف‌هایِ متغیر هرگز مستقیماً در این کمبو
        # ظاهر نمی‌شوند. اگر کالایِ انتخاب‌شده در این مجموعه دارایِ
        # متغیر باشد، کمبویِ دومِ «متغیرِ کالا» ظاهر می‌شود و انتخابِ یکی
        # از متغیرها الزامی است (_on_accept این را چک می‌کند).
        self._variant_parent_ids = {it.variant_parent_item_id for it in items if it.variant_parent_item_id}

        item_options = [(it.item_id, f"{it.code} — {it.name or ''}") for it in items if it.variant_parent_item_id is None]
        item_row_widget = QWidget()
        item_row_layout = QHBoxLayout(item_row_widget)
        item_row_layout.setContentsMargins(0, 0, 0, 0)
        item_row_layout.setSpacing(3)
        self.item_combo = _make_searchable_combo(item_options)
        item_row_layout.addWidget(self.item_combo, stretch=1)
        add_quick_add_button(item_row_layout, self.item_combo, main_window, "GL_DIM", "تعریفِ کالایِ تازه")

        self.variant_combo = _make_searchable_combo([])
        # طبقِ درخواستِ صریح («وقتی کالای دارایِ چند متغیر را وارد
        # می‌کنیم، لیستِ متغیرها نمایش داده شود... جلویِ هر متغیر مقدارِ
        # خرید/فروش را وارد کنیم»): برایِ ردیفِ *تازه* (نه ویرایشِ ردیفِ
        # ازپیش‌ذخیره‌شده -- که همچنان تک‌متغیره است و از همان
        # variant_combo بالا استفاده می‌کند)، به‌جایِ انتخابِ یک‌به‌یکِ
        # متغیر از کمبو، یک جدول با تمامِ متغیرهایِ مجاز نمایش داده
        # می‌شود و کاربر می‌تواند هم‌زمان برایِ چند متغیر مقدار وارد کند
        # -- هرکدام یک ردیفِ جداگانه در سند می‌شود.
        # طبقِ گزارشِ صریحِ کاربر («برایِ کالایِ متغیر فیلدِ قیمت ندارد»):
        # این جدول تا این‌جا هیچ ستونِ قیمتی نداشت -- بهایِ هر متغیر
        # کاملاً خودکار (و در سکوت) در result_fields_list محاسبه
        # می‌شد؛ اگر هیچ قیمتی (نه قرارداد، نه فهرستِ قیمت) پیدا
        # نمی‌شد، آن ردیف بی‌هیچ راهِ جبرانی با خطا رد می‌شد. حالا ستونِ
        # «قیمت» اضافه شده -- هر ردیف در _populate_variant_table با
        # resolve_price پیش‌پر می‌شود (اگر پیدا نشود، صفر و کاملاً
        # قابلِ‌ویرایشِ دستی می‌ماند).
        self.variant_table = QTableWidget(0, 4)
        self.variant_table.setHorizontalHeaderLabels(["متغیر", "موجودی", "قیمت", "مقدار"])
        self.variant_table.verticalHeader().setVisible(False)
        # طبقِ گزارشِ صریحِ کاربر («ردیف‌هایِ متغیر ارتفاعِ کمی دارند و
        # اصلاً معلوم نیستند»): بدونِ این خط، ارتفاعِ پیش‌فرضِ Qt برایِ
        # ردیف‌هایِ جدول (حدودِ ۲۰-۲۴ پیکسل) برایِ نمایشِ کاملِ فیلدِ
        # مبلغیِ هر ردیف (_AmountField) خیلی کوچک است -- همان عددِ ۴۰
        # که در lines_table (پایین‌تر در همین فایل) هم استفاده شده،
        # این‌جا هم به‌کار می‌رود.
        # طبقِ گزارشِ صریحِ کاربر (تکرارِ همین گزارش): ۴۰ پیکسل هنوز کافی
        # نبود -- با فونتِ فعلی، اعدادِ فارسیِ گروه‌بندی‌شده‌یِ داخلِ
        # _AmountField (که خودش padding دارد) در آن ارتفاع نصفه/بریده
        # دیده می‌شدند؛ ۴۶ پیکسل فضایِ کافی برایِ نمایشِ کاملِ رقم‌ها می‌دهد.
        self.variant_table.verticalHeader().setDefaultSectionSize(46)
        self.variant_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # طبقِ گزارشِ صریح («عرضِ لیست کمتر... جلویِ نامِ متغیر فضایِ خالی
        # هست»): قبلاً فقط ستونِ برچسبِ متغیر Stretch بود و بقیهٔ ستون‌ها
        # با پهنایِ پیش‌فرضِ Interactive تقریباً بی‌اندازه تنگ می‌شدند --
        # حالا موجودی/مقدار پهنایِ ثابتِ مشخص دارند (جا برایِ فیلدِ عددی)
        # و فقط ستونِ برچسبِ متغیر باقیِ فضا را پر می‌کند؛ چون متنِ آن هم
        # اکنون صریحاً راست‌چین است (هم‌سو با هدر)، دیگر فضایِ خالیِ
        # جلویِ نام دیده نمی‌شود.
        header = self.variant_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        # طبقِ گزارشِ صریحِ کاربر («اعداد و ارقام مشخص نیست»): پهنایِ قبلی
        # برایِ سه‌رقمی‌شدنِ گروه‌بندیِ اعدادِ فارسی (مثلاً «۱۲۰٬۰۰۰») کافی
        # نبود و رقم‌ها بریده/جمع می‌شدند.
        self.variant_table.setColumnWidth(1, 100)
        self.variant_table.setColumnWidth(2, 130)
        self.variant_table.setColumnWidth(3, 120)
        self.variant_table.setVisible(False)
        self._variant_table_item_ids: list[int] = []

        self.variant_area = QWidget()
        variant_area_layout = QVBoxLayout(self.variant_area)
        variant_area_layout.setContentsMargins(0, 0, 0, 0)
        variant_area_layout.setSpacing(4)
        variant_area_layout.addWidget(self.variant_combo)
        variant_area_layout.addWidget(self.variant_table)

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

        # طبقِ درخواستِ صریح («موتورِ پیشنهادِ قیمت»): بهایِ تمام‌شدهٔ
        # تخمینی، حاشیهٔ سود در قیمتِ فعلی، حداکثرِ تخفیفِ مجاز (طبقِ
        # حداقلِ حاشیهٔ سودِ تنظیم‌شده در تنظیمات)، و هشدارِ زنده اگر
        # تخفیفِ واردشده سود را زیرِ آن حد ببرد -- فقط برایِ اسنادِ فروش،
        # چون «حاشیهٔ سود» برایِ فاکتورِ خرید بی‌معناست.
        self.price_suggestion_label = QLabel("")
        self.price_suggestion_label.setWordWrap(True)
        self.price_suggestion_label.setObjectName("sectionHint")
        self.price_suggestion_label.setVisible(False)

        # طبقِ سندِ راهنمایِ UI/UX (بخشِ ۶.۲/۶.۳): فیلدهایِ مبلغ/عدد باید
        # _AmountField باشند (گروه‌بندیِ سه‌رقمیِ زنده + ارقامِ فارسی)، نه
        # QDoubleSpinBoxِ خام — دقیقاً هم‌الگو با journal_entry.py/
        # treasury_voucher.py/treasury_petty_cash.py.
        self.quantity_field = _AmountField()
        self.quantity_field.setDecimals(3)

        self.unit_price_field = _AmountField()
        self.unit_price_field.setDecimals(decimal_places)
        if lock_price:
            self.unit_price_field.setReadOnly(True)

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
        self._lock_discount = lock_discount
        if lock_discount:
            self.discount_field.setReadOnly(True)
            self.discount_type_combo.setEnabled(False)
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
            FieldSpec("variant", "متغیرِ کالا", self.variant_area, span=3),
            FieldSpec("stock_info", "", stock_row_widget, span=3),
            FieldSpec("quantity", "مقدار (واحدِ پایهٔ کالا)", self.quantity_field, span=1),
            FieldSpec("unit_price", "بهایِ واحد (پیشنهادی از فهرستِ قیمت — قابلِ‌ویرایش)", self.unit_price_field, span=1),
            FieldSpec("discount", "تخفیف", discount_row_widget, span=1),
            FieldSpec("tax_percent", "درصدِ مالیات (بعدِ تخفیف)", self.tax_percent_field, span=1),
            FieldSpec("price_suggestion", "", self.price_suggestion_label, span=3),
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
        self.fields_grid.set_field_visible("variant", False)
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
        self.ok_button = buttons.button(QDialogButtonBox.Ok)
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
        # طبقِ درخواستِ صریح («انتخابِ متغیر»): کمبویِ متغیر در زنجیره‌یِ
        # ثابتِ بالا نیست (چون معمولاً پنهان است و رویِ ویجتِ پنهان
        # setFocus بی‌اثر است) — جداگانه وصل می‌شود تا وقتی نمایان است،
        # Enter در آن هم مثلِ کمبویِ کالا به فیلدِ مقدار برود.
        _enter_signal(self.variant_combo).connect(self.quantity_field.setFocus)
        # طبقِ رفعِ باگِ واقعیِ گزارش‌شده («فوکوس در حالتِ جدولیِ چندمتغیره
        # بلاتکلیف است»): زنجیره‌یِ بالا (کالا -> مقدار) وقتی معنا دارد
        # که فیلدِ مقدار واقعاً نمایان باشد؛ در حالتِ جدولیِ چندمتغیره آن
        # فیلد پنهان است و setFocus رویِ آن بی‌اثر می‌ماند. این اتصالِ
        # اضافه (نه جایگزین -- بعدِ همان اتصال بالا اجرا می‌شود) وقتی
        # جدول نمایان است، فوکوس را به اولین ردیفِ آن هدایت می‌کند.
        _enter_signal(self.item_combo).connect(self._focus_first_variant_row)
        self.item_combo.setFocus()

        self._price_manually_edited = False
        self.unit_price_field.textEdited.connect(self._on_price_edited_manually)
        self.item_combo.currentIndexChanged.connect(self._on_item_combo_changed)
        self.variant_combo.currentIndexChanged.connect(self._on_variant_combo_changed)
        self.quantity_field.valueChanged.connect(self._suggest_price)

        # طبقِ درخواستِ صریح («موتورِ پیشنهادِ قیمت»): با هر تغییرِ کالا/
        # قیمت/تخفیف/مقدار، پنلِ حاشیهٔ سود دوباره محاسبه می‌شود.
        self.unit_price_field.valueChanged.connect(self._refresh_price_suggestion)
        self.discount_field.valueChanged.connect(self._refresh_price_suggestion)
        self.discount_type_combo.currentIndexChanged.connect(self._refresh_price_suggestion)
        self.quantity_field.valueChanged.connect(self._refresh_price_suggestion)
        self.item_combo.currentIndexChanged.connect(self._refresh_price_suggestion)
        self.variant_combo.currentIndexChanged.connect(self._refresh_price_suggestion)

        if initial is not None:
            # طبقِ درخواستِ صریح: اگر ردیفِ ازپیش‌ذخیره‌شده رویِ یک متغیرِ
            # کالا بوده (نه خودِ کالایِ اصلی -- که دیگر اصلاً در کمبویِ
            # کالا نیست)، اول کالایِ اصلیِ آن انتخاب می‌شود تا کمبویِ
            # متغیر ساخته/نمایان شود، بعد خودِ متغیرِ ذخیره‌شده در آن
            # انتخاب می‌شود.
            initial_item = self._items_by_id.get(initial["item_id"])
            if initial_item is not None and initial_item.variant_parent_item_id is not None:
                parent_index = self.item_combo.findData(initial_item.variant_parent_item_id)
                if parent_index >= 0:
                    self.item_combo.setCurrentIndex(parent_index)
                self._update_variant_options()
                variant_index = self.variant_combo.findData(initial["item_id"])
                if variant_index >= 0:
                    self.variant_combo.setCurrentIndex(variant_index)
            else:
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
            self._on_item_combo_changed()

    def keyPressEvent(self, event) -> None:
        # جلوگیریِ واقعی از باگِ autoDefault (هم‌الگو با
        # treasury_voucher._MethodDetailsDialog): چون همه‌یِ فیلدهایِ این
        # دیالوگ زنجیره‌یِ Enterِ خودشان را دارند، دیگر نیازی نیست QDialog
        # با دیدنِ Enter دوباره دکمه‌یِ پیش‌فرض را کلیک کند.
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    def _selected_item_id(self) -> int | None:
        """طبقِ درخواستِ صریح («کالایِ اصلیِ دارایِ متغیر نباید مستقیم
        ثبت شود؛ متغیرش انتخاب شود»): کالایِ *واقعیِ* این ردیف -- اگر
        کالایِ انتخاب‌شده در کمبویِ اصلی دارایِ متغیر باشد، این همان
        متغیرِ انتخاب‌شده در کمبویِ دوم است (یا None اگر هنوز انتخاب
        نشده)، وگرنه همان کالایِ کمبویِ اصلی. در حالتِ جدولیِ چندمتغیره
        (bulk_variant_mode) این تابع بی‌معناست -- آن‌جا هر ردیفِ جدول
        کالایِ خودش را دارد، نه یک کالایِ واحد."""
        parent_id = self.item_combo.currentData()
        if parent_id in self._variant_parent_ids:
            return self.variant_combo.currentData()
        return parent_id

    def _bulk_variant_mode(self) -> bool:
        """طبقِ درخواستِ صریح («جلویِ هر متغیر مقدار وارد کنیم»): فقط
        برایِ ردیفِ *تازه* (نه ویرایشِ ردیفِ ازپیش‌ذخیره‌شده -- که ذاتاً
        تک‌کالایی است) و فقط وقتی کالایِ انتخاب‌شده خودش دارایِ متغیر
        باشد."""
        return self._is_new_row and self.item_combo.currentData() in self._variant_parent_ids

    def _focus_first_variant_row(self) -> None:
        if not self._bulk_variant_mode() or self.variant_table.rowCount() == 0:
            return
        widget = self.variant_table.cellWidget(0, 2)
        if widget is not None:
            widget.setFocus()

    def _effective_warehouse_id(self) -> int | None:
        if self.warehouse_combo is not None:
            warehouse_id = self.warehouse_combo.currentData()
            if warehouse_id is not None:
                return warehouse_id
        return self._default_warehouse_id

    def _allow_negative_stock(self) -> bool:
        warehouse = self._warehouses_by_id.get(self._effective_warehouse_id())
        return bool(warehouse.fields.allow_negative_stock) if warehouse is not None else False

    def _populate_variant_table(self, parent_id: int) -> None:
        """طبقِ درخواستِ صریح («اگر اجازهٔ موجودیِ منفی باشد لیستِ همهٔ
        متغیرها و اگر نباشد فقط آن‌هایی که موجودی دارند نشان داده
        شود»): فیلترِ موجودی فقط برایِ اسنادی اعمال می‌شود که موجودی را
        کم می‌کنند (_STOCK_OUTBOUND_TYPES) -- برایِ خرید/برگشت از خرید و
        امانیِ ورودی، همیشه همه‌یِ متغیرها نشان داده می‌شوند."""
        variants = variants_service.list_item_variants(self._company_id, parent_id)
        stock_by_item: dict[int, decimal.Decimal] = {}
        warehouse_id = self._effective_warehouse_id()
        for v in variants:
            rows = engine_service.get_item_stock_by_warehouse(self._company_id, v.variant_item_id)
            if warehouse_id is not None:
                stock_by_item[v.variant_item_id] = next(
                    (r.quantity_on_hand for r in rows if r.warehouse_id == warehouse_id), decimal.Decimal(0),
                )
            else:
                stock_by_item[v.variant_item_id] = sum((r.quantity_on_hand for r in rows), decimal.Decimal(0))

        if self._document_type_code in _STOCK_OUTBOUND_TYPES and not self._allow_negative_stock():
            variants = [v for v in variants if stock_by_item.get(v.variant_item_id, decimal.Decimal(0)) > 0]

        self._variant_table_item_ids = [v.variant_item_id for v in variants]
        self.variant_table.setRowCount(len(variants))
        row_price_fields: list = []
        row_qty_fields: list = []
        for row, v in enumerate(variants):
            label = f"{v.code} — {v.attribute_labels or v.name or ''}"
            label_item = QTableWidgetItem(label)
            # طبقِ گزارشِ صریح («جلویِ نامِ متغیر فضایِ خالی هست»): بدونِ
            # این خط، تراز پیش‌فرضِ QTableWidgetItem چپ‌چین است -- در
            # ستونی که Stretch شده و راست‌به‌چپ نمایش داده می‌شود، همین
            # چپ‌چینی همان فضایِ خالیِ گزارش‌شده را جلویِ متن می‌سازد.
            label_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.variant_table.setItem(row, 0, label_item)
            stock_item = QTableWidgetItem(numerals.format_money(stock_by_item.get(v.variant_item_id, decimal.Decimal(0)), 3))
            stock_item.setTextAlignment(Qt.AlignCenter)
            self.variant_table.setItem(row, 1, stock_item)
            # طبقِ گزارشِ صریحِ کاربر («برایِ کالایِ متغیر فیلدِ قیمت
            # ندارد»): پیش‌فرض از همان resolve_price (اول قراردادِ
            # فعال، بعد فهرستِ قیمت) خوانده می‌شود؛ اگر هیچ‌کدام پیدا
            # نشود، صفر می‌ماند و کاربر خودش دستی وارد می‌کند -- دیگر
            # هیچ ردیفی صرفاً به‌خاطرِ نبودِ قیمتِ ازپیش‌تعریف‌شده رد
            # نمی‌شود (result_fields_list همین مقدارِ فیلد را عیناً
            # می‌خواند، نه اینکه دوباره resolve_price را صدا بزند).
            price_field = _AmountField()
            price_field.setDecimals(self._decimal_places)
            variant_item = self._items_by_id.get(v.variant_item_id)
            if self._counterparty_id is not None and self._document_type_code is not None and variant_item is not None:
                try:
                    resolved = pricing_service.resolve_price(
                        self._company_id, self._counterparty_id, v.variant_item_id, variant_item.base_uom_id,
                        decimal.Decimal(1), self._price_list_id, self._document_type_code, self._document_date,
                    )
                    price_field.setValue(float(resolved.unit_price))
                except ValueError:
                    pass
            self.variant_table.setCellWidget(row, 2, price_field)
            qty_field = _AmountField()
            qty_field.setDecimals(3)
            qty_field.valueChanged.connect(self._on_selection_changed)
            self.variant_table.setCellWidget(row, 3, qty_field)
            row_price_fields.append(price_field)
            row_qty_fields.append(qty_field)
        self.status_label.setText("" if variants else "هیچ متغیری با موجودیِ مثبت برایِ این کالا یافت نشد.")

        # طبقِ رفعِ باگِ واقعیِ گزارش‌شده («فوکوس در حالتِ جدولیِ
        # چندمتغیره بلاتکلیف است -- تمامِ فیلدها حتی ردیفِ متغیرها باید
        # با اینتر پیموده شوند»): زنجیره‌یِ Enterِ ثابتِ خودِ دیالوگ
        # (بالاتر در __init__) فقط فیلدهایِ تک‌کالاییِ همیشه‌حاضر را
        # می‌شناسد -- ردیف‌هایِ همین جدول که هر بار از نو ساخته می‌شوند
        # باید همین‌جا زنجیره‌یِ خودشان را بگیرند: بهایِ واحد -> مقدار
        # (همان ردیف)، مقدار -> بهایِ واحدِ ردیفِ بعدی، و مقدارِ آخرین
        # ردیف به اولین فیلدِ بعدِ جدول (تخفیف) می‌رود.
        for row in range(len(variants)):
            _enter_signal(row_price_fields[row]).connect(row_qty_fields[row].setFocus)
            if row + 1 < len(variants):
                _enter_signal(row_qty_fields[row]).connect(row_price_fields[row + 1].setFocus)
            else:
                _enter_signal(row_qty_fields[row]).connect(self.discount_field.setFocus)

        # طبقِ گزارشِ صریح («ارتفاع و تعدادِ متغیرها بیشتر دیده بشه»):
        # ارتفاعِ جدول بسته به تعدادِ واقعیِ ردیف‌ها (تا سقفِ ۶ ردیفِ
        # هم‌زمان، بعدِ آن اسکرول) تنظیم می‌شود -- نه یک عددِ ثابتِ کوچک
        # که فقط یک ردیف را واقعاً نشان می‌داد.
        row_height = self.variant_table.verticalHeader().defaultSectionSize()
        header_height = self.variant_table.horizontalHeader().height()
        visible_rows = max(1, min(len(variants), 6))
        self.variant_table.setMinimumHeight(header_height + row_height * min(len(variants), 2) + 6)
        self.variant_table.setMaximumHeight(header_height + row_height * visible_rows + 6)

    def _variant_table_quantity(self, row: int) -> decimal.Decimal:
        widget = self.variant_table.cellWidget(row, 3)
        if widget is None:
            return decimal.Decimal(0)
        return decimal.Decimal(str(widget.value()))

    def _variant_table_price(self, row: int) -> decimal.Decimal:
        widget = self.variant_table.cellWidget(row, 2)
        if widget is None:
            return decimal.Decimal(0)
        return decimal.Decimal(str(widget.value()))

    def _update_variant_options(self) -> None:
        parent_id = self.item_combo.currentData()
        if parent_id not in self._variant_parent_ids:
            _fill_options(self.variant_combo, [])
            self.variant_table.setRowCount(0)
            self.fields_grid.set_field_visible("variant", False)
            return

        if self._bulk_variant_mode():
            self.variant_combo.setVisible(False)
            self.variant_table.setVisible(True)
            self._populate_variant_table(parent_id)
            self.fields_grid.set_field_visible("variant", True)
            self.variant_table.setFocus()
        else:
            self.variant_combo.setVisible(True)
            self.variant_table.setVisible(False)
            self.variant_table.setRowCount(0)
            variants = variants_service.list_item_variants(self._company_id, parent_id)
            variant_options = [(v.variant_item_id, f"{v.code} — {v.attribute_labels or v.name or ''}") for v in variants]
            _fill_options(self.variant_combo, variant_options)
            self.fields_grid.set_field_visible("variant", True)
            self.variant_combo.setFocus()

    def _on_item_combo_changed(self) -> None:
        self._update_variant_options()
        self._on_selection_changed()

    def _on_variant_combo_changed(self) -> None:
        self._on_selection_changed()

    def _update_entry_state(self) -> None:
        """طبقِ درخواستِ صریح («از ابتدا که کالای اصلی انتخاب میشه باید
        جلوش گرفته بشه، نه بعدِ تاییدِ نهایی -- تمامِ کنترل‌ها در هنگامِ
        ورودِ اطلاعات چک بشه»): به‌محضِ انتخابِ کالایِ اصلیِ دارایِ متغیر
        (قبل از انتخابِ خودِ متغیر)، بلافاصله فیلدهایِ ورودِ اطلاعات و
        دکمهٔ تایید غیرفعال و پیامِ خطا نمایش داده می‌شود -- نه اینکه
        کاربر همه‌چیز را پر کند و فقط با زدنِ تایید متوجهِ رد شدن شود."""
        bulk = self._bulk_variant_mode()
        # طبقِ درخواستِ صریح («جلویِ هر متغیر مقدار وارد کنیم»): در حالتِ
        # جدولی، فیلدِ مقدار/بهایِ واحدِ مشترک اصلاً معنا ندارد (هر ردیفِ
        # جدول مقدارِ خودش را دارد و قیمت هم به‌صورتِ خودکار به‌ازایِ هر
        # متغیر محاسبه می‌شود) -- پس پنهان می‌شوند، نه فقط غیرفعال. طبقِ
        # گزارشِ صریحِ بعدی («فرم خیلی پخش و نامرتب شده») -- چون
        # QGridLayout جایگاهِ ردیف/ستونِ فیلدهایِ پنهان را خالی نگه
        # می‌دارد نه بازتوزیع، صرفاً پنهان‌کردنِ مقدار/قیمت باعث می‌شد
        # تخفیف/مالیات هرکدام فقط نیمی از عرض را بگیرند و در دو ردیفِ
        # جداگانه بیفتند. طبقِ گزارشِ صریحِ سوم («فیلدها فضایِ خالی
        # داره») -- span=3 (کاملِ عرض) برایِ یک فیلدِ عددیِ کوچک زیادی
        # پهن و خالی به‌نظر می‌رسید؛ حالا این دو در یک ردیفِ مشترک
        # (تخفیف=۲ و مالیات=۱ از ۳ ستون -- دقیقاً هم‌الگو با ردیفِ
        # مقدار/قیمت/تخفیفِ حالتِ عادی) قرار می‌گیرند: هم فشرده‌تر، هم
        # هیچ‌کدام بی‌جهت پهن نیست. در حالتِ عادی به همان spanِ ۱ی
        # پیش‌فرض برمی‌گردند. ردیفِ اطلاعاتِ موجودیِ تک‌کالایی و پیشنهادِ
        # قیمت هم چون در حالتِ جدولی بی‌معنایند (هر متغیر موجودی/قیمتِ
        # خودش را دارد) پنهان می‌شوند.
        self.fields_grid.set_field_visible("quantity", not bulk)
        self.fields_grid.set_field_visible("unit_price", not bulk)
        self.fields_grid.set_field_visible("stock_info", not bulk)
        self.fields_grid.set_field_visible("price_suggestion", not bulk)
        self.fields_grid._set_span("discount", 2 if bulk else 1)
        self.fields_grid._set_span("tax_percent", 1)
        # طبقِ گزارشِ صریحِ چهارم («فضایِ خالیِ جلویِ کالا»): چون در
        # حالتِ جدولی، ردیفِ خودِ «کالا» (span=۲) دیگر با هیچ فیلدِ
        # دیگری هم‌ردیف نیست (مقدار/قیمت که قبلاً کنارش بودند حالا
        # پنهانند)، ستونِ سومِ خالی کنارش یک فاصلهٔ واضح می‌سازد -- چون
        # عرضِ آن ستون در سراسرِ گرید مشترک است و تخفیف/مالیات هنوز از
        # آن استفاده می‌کنند. برایِ رفعِ همین فاصله، کالا هم مثلِ بقیهٔ
        # ردیف‌هایِ تک‌فیلدیِ حالتِ جدولی، کاملِ عرض می‌گیرد.
        self.fields_grid._set_span("item", 3 if bulk else 2)
        if bulk:
            for widget in (self.discount_field, self.tax_percent_field, self.description_field):
                widget.setEnabled(True)
            if self.warehouse_combo is not None:
                self.warehouse_combo.setEnabled(True)
            self.discount_type_combo.setEnabled(not self._lock_discount)
            has_any_qty = any(self._variant_table_quantity(row) > 0 for row in range(self.variant_table.rowCount()))
            self.ok_button.setEnabled(has_any_qty)
            if self.variant_table.rowCount() > 0:
                self.status_label.setText("" if has_any_qty else "برایِ حداقل یک متغیر مقدار وارد کنید.")
            return

        parent_id = self.item_combo.currentData()
        needs_variant = parent_id in self._variant_parent_ids and self.variant_combo.currentData() is None
        entry_widgets = [
            self.quantity_field, self.unit_price_field, self.discount_field,
            self.tax_percent_field, self.description_field,
        ]
        if self.warehouse_combo is not None:
            entry_widgets.append(self.warehouse_combo)
        for widget in entry_widgets:
            widget.setEnabled(not needs_variant)
        # طبقِ رفعِ رگرسیونِ واقعی: discount_type_combo علاوه بر این حالت،
        # یک قفلِ مستقلِ از قبل هم دارد (lock_discount -- مثلاً در فروشگاهیِ
        # POS که تغییرِ نوعِ تخفیف اصلاً مجاز نیست)؛ نباید با بازکردنِ
        # قفلِ متغیر، آن قفلِ دیگر را ناخواسته باز کند.
        self.discount_type_combo.setEnabled(not needs_variant and not self._lock_discount)
        self.ok_button.setEnabled(not needs_variant)
        self.status_label.setText(
            "این کالا دارایِ چند متغیر است؛ لطفاً یکی از متغیرها را انتخاب کنید." if needs_variant else ""
        )

    def _on_selection_changed(self) -> None:
        """طبقِ درخواستِ صریح: درصدِ مالیات با اولویتِ کالا -> تنظیماتِ
        کلیِ شرکت پیش‌پر می‌شود — فقط برایِ ردیفِ *تازه* (initial=None)،
        نه هنگامِ ویرایشِ ردیفِ ازپیش‌ذخیره‌شده که مقدارِ ثبت‌شده‌اش را
        نباید بازنویسی کند. در حالتِ جدولیِ چندمتغیره، تک‌کالایی معنا
        ندارد -- هر ردیفِ جدول بهایِ خودش را در result_fields_list
        جداگانه می‌گیرد."""
        self._update_entry_state()
        self._refresh_stock_info()
        if self._bulk_variant_mode():
            return
        item_id = self._selected_item_id()
        if item_id is None:
            return
        default_tax = catalog_service.resolve_default_tax_percent(self._company_id, item_id)
        self.tax_percent_field.setValue(float(default_tax))
        self._price_manually_edited = False
        self._suggest_price()

    def _refresh_stock_info(self) -> None:
        item_id = self._selected_item_id()
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
        item_id = self._selected_item_id()
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
        item_id = self._selected_item_id()
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
        item_id = self._selected_item_id()
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
            # طبقِ گزارشِ صریحِ کاربر («کالایی که قیمت ندارد ثبت
            # نمی‌شود»): قبلاً این خطا کاملاً در سکوت رد می‌شد -- کاربر
            # تا لحظه‌یِ ثبتِ نهاییِ ردیف (با پیامِ سرویس، بعدِ زدنِ
            # افزودن) متوجه نمی‌شد که باید خودش قیمت را وارد کند. حالا
            # همین‌جا -- از همان لحظه که کالا انتخاب می‌شود -- روشن
            # می‌گوید که باید دستی وارد شود.
            self.status_label.setText("قیمتی از قراردادِ فعال یا فهرستِ قیمت یافت نشد -- قیمت را دستی وارد کنید.")
            return
        self.status_label.setText("")
        self.unit_price_field.setValue(float(resolved.unit_price))
        if resolved.discount_amount and self.discount_field.value() == 0:
            self.discount_field.setValue(float(resolved.discount_amount))

    def _estimate_item_cost(self, item_id: int) -> decimal.Decimal | None:
        """طبقِ درخواستِ صریح («موتورِ پیشنهادِ قیمت... قیمتِ خرید»): چون
        این پروژه یک تابعِ آماده‌یِ «بهایِ فعلی» ندارد، این‌جا میانگینِ
        موزونِ average_unit_cost را از رویِ موجودیِ همه‌یِ انبارها
        می‌سازیم -- همان بهایی که موتورِ انبار خودش برایِ محاسبه‌یِ
        بهایِ تمام‌شده استفاده می‌کند."""
        balances = engine_service.list_balances(self._company_id, item_id=item_id)
        total_qty = sum((b.quantity_on_hand for b in balances), decimal.Decimal(0))
        if total_qty <= 0:
            return None
        total_value = sum((b.total_value for b in balances), decimal.Decimal(0))
        return total_value / total_qty

    def _refresh_price_suggestion(self) -> None:
        """طبقِ درخواستِ صریح («موتورِ پیشنهادِ قیمت»): بهایِ تمام‌شدهٔ
        تخمینی، حاشیهٔ سود در قیمتِ فعلی، حداکثرِ تخفیفِ مجاز (طبقِ
        حداقلِ حاشیهٔ سودِ تنظیم‌شده در تنظیماتِ بازرگانی)، و هشدارِ زنده
        اگر تخفیفِ واردشده سود را زیرِ آن حد ببرد."""
        if self._document_type_code not in _SALES_TYPES or self._bulk_variant_mode():
            self.price_suggestion_label.setVisible(False)
            return
        item_id = self._selected_item_id()
        unit_price = decimal.Decimal(str(self.unit_price_field.value()))
        if item_id is None or unit_price <= 0:
            self.price_suggestion_label.setVisible(False)
            return
        unit_cost = self._estimate_item_cost(item_id)
        if unit_cost is None or unit_cost <= 0:
            self.price_suggestion_label.setVisible(False)
            return

        quantity = decimal.Decimal(str(self.quantity_field.value())) or decimal.Decimal(1)
        is_percent_discount = self.discount_type_combo.currentData() == "PERCENT"
        discount_value = decimal.Decimal(str(self.discount_field.value()))
        if is_percent_discount:
            effective_price = unit_price * (1 - discount_value / 100)
        else:
            # تخفیفِ مبلغی رویِ جمعِ ناخالصِ ردیف اعمال می‌شود، نه لزوماً
            # تکِ واحد -- برایِ نمایشِ زنده، تقسیم بر مقدار کافی است.
            effective_price = unit_price - (discount_value / quantity)

        margin_percent = (unit_price - unit_cost) / unit_price * 100
        parts = [
            f"بهایِ تمام‌شدهٔ تخمینی: {numerals.format_money(unit_cost, self._decimal_places)}",
            f"حاشیهٔ سود در این قیمت: {numerals.format_money(margin_percent, 1)}٪",
        ]

        policy = pricing_service.get_pricing_policy(self._company_id)
        floor = policy.min_margin_percent_default if policy is not None else None
        if floor is not None:
            floor_ratio = decimal.Decimal(1) - (floor / decimal.Decimal(100))
            if floor_ratio > 0:
                min_price = unit_cost / floor_ratio
                max_discount_percent = max(decimal.Decimal(0), (1 - min_price / unit_price) * 100)
                parts.append(f"حداکثرِ تخفیفِ مجاز: {numerals.format_money(max_discount_percent, 1)}٪")

            no_discount_profit = unit_price - unit_cost
            discounted_profit = effective_price - unit_cost
            effective_margin_percent = (
                (effective_price - unit_cost) / effective_price * 100 if effective_price > 0 else decimal.Decimal(-999)
            )
            if effective_margin_percent < floor and no_discount_profit > 0:
                profit_drop_percent = (1 - discounted_profit / no_discount_profit) * 100
                parts.append(f"⚠️ این تخفیف سودِ این ردیف را {numerals.format_money(profit_drop_percent, 0)}٪ کاهش می‌دهد.")

        self.price_suggestion_label.setText("  |  ".join(parts))
        self.price_suggestion_label.setVisible(True)

    def _on_accept(self) -> None:
        parent_id = self.item_combo.currentData()
        if parent_id is None:
            self.status_label.setText("کالا را انتخاب کنید.")
            return
        if self._bulk_variant_mode():
            # طبقِ درخواستِ صریح («جلویِ هر متغیر مقدار وارد کنیم»): در
            # حالتِ جدولی، کافی‌ست حداقل یک ردیف مقدار داشته باشد -- بقیه
            # نادیده گرفته می‌شوند (result_fields_list خودش فیلتر می‌کند).
            if not any(self._variant_table_quantity(row) > 0 for row in range(self.variant_table.rowCount())):
                self.status_label.setText("برایِ حداقل یک متغیر مقدار وارد کنید.")
                return
            self.accept()
            return
        # طبقِ درخواستِ صریح («کالایِ اصلیِ دارایِ متغیر نباید اجازه‌یِ
        # ثبت مستقیم بدهد»): اگر کالا خودش دارایِ متغیر است، انتخابِ یکی
        # از متغیرها الزامی است -- بدونِ آن، ثبتِ ردیف رد می‌شود.
        if parent_id in self._variant_parent_ids and self.variant_combo.currentData() is None:
            self.status_label.setText("این کالا دارایِ چند متغیر است؛ لطفاً یکی از متغیرها را انتخاب کنید.")
            return
        if self.quantity_field.value() <= 0:
            self.status_label.setText("مقدار باید بزرگ‌تر از صفر باشد.")
            return
        self.accept()

    def result_fields_list(self) -> list[dict]:
        """طبقِ درخواستِ صریح («جلویِ هر متغیر مقدارِ خرید/فروش را وارد
        کنیم»): در حالتِ جدولیِ چندمتغیره، به‌ازایِ هر متغیرِ دارایِ
        مقدارِ مثبت یک ردیفِ کاملاً مستقل برمی‌گردد -- بهایِ واحد و
        درصدِ مالیات به‌صورتِ خودکار برایِ همان متغیرِ خاص محاسبه
        می‌شوند (نه یک مقدارِ مشترک برایِ همه)؛ فقط تخفیف/توضیح/انبار
        بینِ همه‌یِ ردیف‌هایِ تولیدشده مشترک است. برایِ حالتِ عادی (کالایِ
        بدونِ متغیر، یا ویرایشِ یک ردیفِ ازپیش‌ذخیره‌شده)، همان یک نتیجهٔ
        result_fields در یک لیستِ تک‌عضوی برمی‌گردد."""
        if not self._bulk_variant_mode():
            return [self.result_fields()]
        is_percent_discount = self.discount_type_combo.currentData() == "PERCENT"
        discount_value = decimal.Decimal(str(self.discount_field.value()))
        warehouse_id = self.warehouse_combo.currentData() if self.warehouse_combo is not None else None
        description = self.description_field.text().strip() or None
        results = []
        for row, item_id in enumerate(self._variant_table_item_ids):
            quantity = self._variant_table_quantity(row)
            if quantity <= 0:
                continue
            item = self._items_by_id.get(item_id)
            # طبقِ گزارشِ صریحِ کاربر («برایِ کالایِ متغیر فیلدِ قیمت
            # ندارد»): دیگر این‌جا دوباره resolve_price صدا زده
            # نمی‌شود -- همان مقدارِ فیلدِ قیمتِ همین ردیف (که در
            # _populate_variant_table پیش‌پر شده و کاملاً قابلِ‌ویرایشِ
            # دستی است) عیناً گرفته می‌شود؛ اگر صفر باشد (نه پیش‌فرضی
            # پیدا شده نه دستی واردشده)، None می‌ماند تا همان خطایِ
            # روشنِ add_line («قیمتی تعریف نشده») نمایش داده شود.
            row_price = self._variant_table_price(row)
            unit_price = row_price if row_price > 0 else None
            tax_percent = catalog_service.resolve_default_tax_percent(self._company_id, item_id)
            results.append({
                "item_id": item_id,
                "uom_id": item.base_uom_id if item else 0,
                "quantity": quantity,
                "quantity_base": quantity,
                "unit_price": unit_price,
                "discount_amount": decimal.Decimal(0) if is_percent_discount else discount_value,
                "discount_percent": discount_value if is_percent_discount else decimal.Decimal(0),
                "tax_percent": tax_percent,
                "description": description,
                "warehouse_id": warehouse_id,
            })
        return results

    def result_fields(self) -> dict:
        item_id = self._selected_item_id()
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


class _SettlementPlanDialog(QDialog):
    """طبقِ درخواستِ صریح («یک دکمه سمت راست... نحوه تسویه که ممکنه نقد/
    نسیه/بانک یا همون کارتخوان/بن/کالابرگ/تخفیف... و با تاییدِ مدیر»):
    ترکیبِ چند روشِ هم‌زمان + مانده‌یِ خودکار به‌عنوانِ نسیه؛ ذخیره‌یِ
    دوباره (حتی بعدِ تاییدِ قبلی) تاییدِ قبلی را باطل می‌کند -- ترکیبِ
    تازه باید دوباره تاییدشود.

    طبقِ گزارشِ صریحِ کاربر («روالِ ثبتِ فاکتور خیلی سخت شد... مدیر فقط
    دیدن و کارِ ثبتِ نهایی انجام دهد»): این دیالوگ دیگر دکمهٔ جداگانه‌یِ
    «تاییدِ مدیر» ندارد -- فقط واردکردن/ذخیره‌یِ ترکیبِ تسویه (یا کلیکِ
    نسیه). تاییدِ نحوه‌یِ تسویه از این پس فقط از طریقِ همان دکمهٔ ثبتِ
    نهاییِ فرمِ اصلی (CommercialDocumentScreen._post) انجام می‌شود -- تا
    مدیر نیازی به بازکردنِ این دیالوگ نداشته باشد؛ approve_settlement_
    plan (که فقط برایِ مدیر مجاز است) همان‌جا صدا زده می‌شود."""

    def __init__(
        self, document_id: int, company_id: int, document_type_code: str,
        total_amount: decimal.Decimal, decimal_places: int, parent=None,
        require_manager_approval: bool = True,
        seed_lines: list[tuple] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("نحوه‌یِ تسویه‌یِ فاکتور")
        # طبقِ گزارشِ صریح («اندازهٔ فونت‌ها و فیلدها کمی بزرگ‌تر باشه»):
        # فونتِ کلِ دیالوگ یک واحد بزرگ‌تر از فونتِ پیش‌فرضِ برنامه -- باید
        # پیش از ساختِ هر ویجتِ فرزند تنظیم شود تا رویِ همه اثر بگذارد.
        _dialog_font = self.font()
        _dialog_font.setPointSize(_dialog_font.pointSize() + 1)
        self.setFont(_dialog_font)
        # طبقِ گزارشِ صریح («ردیف‌هایِ این فرم اصلا معلوم نیست و ارتفاعش
        # کمه»): ۶۰۰×۴۴۰ برایِ ۵ ردیف (۵ روشِ ثابت + یادداشت + هر روش
        # ممکن است روشِ سفارشی هم داشته باشد) خیلی تنگ بود -- popupِ بازِ
        # کمبویِ روش، بقیه‌یِ ردیف‌ها را می‌پوشاند. حالا با ستونِ تفصیلیِ
        # تازه (+ در حالتِ تک‌فروشی، ستونِ افزودنِ ردیف) هم عریض‌تر شده.
        self.resize(940, 640)
        self._document_id = document_id
        self._company_id = company_id
        self._document_type_code = document_type_code
        self._total_amount = total_amount
        self._decimal_places = decimal_places
        self._direction = "RECEIPT" if document_type_code == "SALES_INVOICE" else "PAYMENT"
        # طبقِ درخواستِ صریح («صندوق‌دار فقط نقد می‌تونه بزنه، بانکی/سایرِ
        # روش‌ها را نمی‌تونه ثبت کنه»): برایِ فروشِ حضوریِ POS، صندوق‌دار
        # (که نقشِ مدیر ندارد) باید بتواند خودش همین‌جا ترکیب را ذخیره
        # کند، بدونِ نیازِ به تاییدِ جداگانهٔ مدیر -- تاییدِ سرپرست برایِ
        # POS از قبل با صفحهٔ «تاییدِ سرپرست» انجام می‌شود (نه این نقشه).
        self._require_manager_approval = require_manager_approval
        # طبقِ رفعِ باگِ واقعیِ کشف‌شده با گزارشِ زندهٔ کاربر («همه‌یِ
        # روش‌ها فیکس بشه»؛ «بعدِ اینترِ روشِ ردیفِ اول، ردیف پرید و دیگه
        # نبود»؛ «برایِ فاکتورهایِ بعدی دیگه هیچ ردیفی نیست»): طرحِ قبلی
        # -- کمبویِ آزادِ روش در هر ردیف + دکمه‌هایِ افزودن/حذفِ ردیف --
        # روی QTableWidget با _EnterComboBoxِ توکار به‌شدت ناپایدار بود
        # (فوکوسِ برنامه‌ای بینِ سلول‌هایِ حاویِ کمبو گاهی خودِ جدول را در
        # وضعیتِ نامعتبر می‌گذاشت). حالا هر ردیف دقیقاً به یک روشِ ثابت
        # (از self._method_codes()) قفل است -- فقط یک برچسبِ متنی، نه
        # کمبو. طبقِ گزارشِ بعدی («بتوان ردیفِ دومِ همان روش را هم اضافه
        # کرد» -- فقط در فرمِ تک‌فروشی)، دکمهٔ ➕ کنارِ هر ردیف، یک ردیفِ
        # تازه با همان روش را در انتهایِ جدول اضافه می‌کند -- باز هم
        # بدونِ کمبو، پس همان ناپایداری برنمی‌گردد.
        self._pos_mode = not require_manager_approval
        self._row_method_codes: list[str] = []
        self._row_detail_ids: list[int | None] = []
        # طبقِ درخواستِ صریح («سندِ تک‌فروشی در حالتِ اصلاح که باز می‌شود،
        # باید نوعِ تسویهٔ قبلی در حافظه بماند و فرمِ دریافت با همان
        # مقادیر باز شود»): وقتی این فاکتور از یک فروشِ قبلاً‌تاییدشده
        # بازگشایی شده (که نقشه‌اش پاک شده)، seed_lines همان نقشهٔ قبلی
        # را (پیش از پاک‌شدن) نگه داشته -- اگر در دیتابیس نقشه‌ای نباشد،
        # بجایِ ردیف‌هایِ خالی، همین مقادیر پیش‌فرض می‌شوند.
        self._seed_lines = seed_lines

        layout = QVBoxLayout(self)

        total_label = QLabel(f"مبلغِ کلِ فاکتور: {numerals.format_money(total_amount, decimal_places)}")
        total_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(total_label)

        self.status_banner = QLabel("")
        self.status_banner.setWordWrap(True)
        layout.addWidget(self.status_banner)

        column_count = 4 if self._pos_mode else 3
        headers = ["روش", "مبلغ", "تفصیلی"] + ([""] if self._pos_mode else [])
        self.table = QTableWidget(0, column_count)
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        table_header = self.table.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.setColumnWidth(0, 190)
        table_header.setSectionResizeMode(1, QHeaderView.Stretch)
        table_header.setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.setColumnWidth(2, 220)
        if self._pos_mode:
            table_header.setSectionResizeMode(3, QHeaderView.Fixed)
            self.table.setColumnWidth(3, 40)
        # طبقِ همان گزارش: ردیف‌هایِ کوتاه (ارتفاعِ پیش‌فرضِ Qt برایِ
        # ویجت‌هایِ توکار مثلِ فیلدِ مبلغ) به‌سختی دیده می‌شدند -- با
        # فونتِ بزرگ‌ترِ تازه، ارتفاع هم کمی بیشتر شد.
        self.table.verticalHeader().setDefaultSectionSize(50)
        self.table.setMinimumHeight(280)
        layout.addWidget(self.table, stretch=1)

        self.remaining_label = QLabel("")
        layout.addWidget(self.remaining_label)

        buttons_row = QHBoxLayout()
        self.save_button = QPushButton("💾")
        self.save_button.setObjectName("primaryIconButton")
        self.save_button.setFixedWidth(44)
        self.save_button.setToolTip("ذخیره")
        # طبقِ رفعِ ریشه‌ایِ باگِ واقعیِ گزارش‌شده («بعدِ اینترِ ردیفِ اول،
        # ردیف پرید و دیگه نبود»؛ «برایِ فاکتورهایِ بعدی هیچ ردیفی نیست»):
        # علتِ واقعی اصلاً ناپایداریِ فوکوسِ QTableWidget نبود -- چون اولین
        # دکمه‌یِ افزوده‌شده به یک QDialog به‌صورتِ خودکار isDefault()
        # می‌شود، هر اینترِ زده‌شده در هر QLineEdit (که Enter را مصرف
        # نمی‌کند تا رفتارِ استانداردِ دکمه‌یِ پیش‌فرض خراب نشود) هم‌زمان با
        # جابه‌جاییِ فوکوسِ خودمان، دکمه‌یِ ذخیره را هم کلیک می‌کرد -- یعنی
        # `_save()` وسطِ واردکردنِ مبالغ اجرا و دیالوگ زودهنگام بسته
        # می‌شد (با دیتایِ ناقص). راه‌حل: هیچ دکمه‌ای در این دیالوگ نباید
        # autoDefault باشد؛ ذخیره فقط با کلیکِ مستقیم یا رسیدنِ زنجیره‌یِ
        # اینتر به آخرین ردیف (که آگاهانه _save() را صدا می‌زند) انجام شود.
        self.save_button.setAutoDefault(False)
        self.save_button.clicked.connect(self._save)
        buttons_row.addWidget(self.save_button)
        # طبقِ گزارشِ صریحِ کاربر («در فاکتورها اگر نسیه باشد نحوه تسویه
        # در ابتدا مشخص نیست»): «نسیه» در این فرم ردیفِ روش نیست -- فقط
        # مانده‌یِ خودکارِ پوشش‌داده‌نشده است (SettlementPlan.remaining_on_
        # credit) -- پس برایِ فاکتورِ کاملاً نسیه، کاربر باید حدس بزند که
        # خالی‌گذاشتنِ همه‌یِ ردیف‌ها + زدنِ 💾 یعنی «کلِ فاکتور نسیه است».
        # این دکمه همان کار را با یک کلیکِ صریح انجام می‌دهد -- همه‌یِ
        # مبالغِ واردشده را صفر می‌کند و ذخیره می‌کند، تا از همان لحظه‌یِ
        # بازکردنِ دیالوگ روشن باشد که نسیه هم یک گزینه‌یِ مستقیم است.
        self.full_credit_button = QPushButton("🔖 ثبتِ کامل به‌عنوانِ نسیه")
        self.full_credit_button.setToolTip("هیچ دریافتی الان انجام نمی‌شود -- کلِ مبلغِ فاکتور به‌عنوانِ نسیه ثبت می‌شود.")
        self.full_credit_button.setAutoDefault(False)
        self.full_credit_button.clicked.connect(self._save_as_full_credit)
        buttons_row.addWidget(self.full_credit_button)
        close_button = QPushButton("بستن")
        close_button.setAutoDefault(False)
        close_button.clicked.connect(self.accept)
        buttons_row.addWidget(close_button)
        layout.addLayout(buttons_row)

        self._load_existing()

    def _method_codes(self) -> tuple[str, ...]:
        return settlements_service.settlement_plan_method_codes(self._document_type_code, self._company_id)

    def _row_index_for_widget(self, column: int, widget) -> int | None:
        for row_index in range(self.table.rowCount()):
            if self.table.cellWidget(row_index, column) is widget:
                return row_index
        return None

    def _detail_label(self, detail_account_id: int | None, options: list) -> str:
        if detail_account_id is None:
            return "— انتخاب —"
        for option in options:
            if option.detail_account_id == detail_account_id:
                return option.name or option.code
        return "— انتخاب —"

    def _pick_detail(self, button: QPushButton, options: list) -> None:
        row_index = self._row_index_for_widget(2, button)
        if row_index is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("انتخابِ تفصیلی")
        dialog.resize(420, 140)
        dialog_layout = QVBoxLayout(dialog)
        combo_options = [(None, "— هیچ‌کدام —")] + [
            (option.detail_account_id, option.name or option.code) for option in options
        ]
        combo = _make_searchable_combo(combo_options)
        current_id = self._row_detail_ids[row_index] if row_index < len(self._row_detail_ids) else None
        if current_id is not None:
            found_index = combo.findData(current_id)
            if found_index >= 0:
                combo.setCurrentIndex(found_index)
        dialog_layout.addWidget(combo)
        dialog_buttons = QHBoxLayout()
        ok_button = QPushButton("تایید")
        ok_button.setAutoDefault(False)
        ok_button.clicked.connect(dialog.accept)
        dialog_buttons.addWidget(ok_button)
        cancel_button = QPushButton("انصراف")
        cancel_button.setAutoDefault(False)
        cancel_button.clicked.connect(dialog.reject)
        dialog_buttons.addWidget(cancel_button)
        dialog_layout.addLayout(dialog_buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        chosen_id = combo.currentData()
        self._row_detail_ids[row_index] = chosen_id
        button.setText(self._detail_label(chosen_id, options))

    def _add_row(
        self, method_code: str, amount: decimal.Decimal | None = None, detail_account_id: int | None = None,
    ) -> None:
        row_index = self.table.rowCount()
        self.table.insertRow(row_index)
        self._row_method_codes.append(method_code)
        self._row_detail_ids.append(None)

        method_label = QLabel(settlements_service.SETTLEMENT_PLAN_METHOD_LABELS.get(method_code, method_code))
        method_label.setAlignment(Qt.AlignCenter)
        self.table.setCellWidget(row_index, 0, method_label)

        # طبقِ رفعِ باگِ واقعی («فیلدِ مبلغ قبلاً یک _AmountFieldِ ساده
        # بود -- اسپیس هیچ اثری نداشت»): _RowAmountField (هم‌الگو با
        # فرمِ دریافت/پرداخت) با اسپیس، باقیماندهٔ همین لحظه را در خودش
        # کپی می‌کند.
        amount_field = _RowAmountField(self._remaining_amount)
        amount_field.setDecimals(self._decimal_places)
        if amount is not None:
            amount_field.setValue(float(amount))
        amount_field.valueChanged.connect(self._update_remaining)
        # طبقِ درخواستِ صریح («صندوق‌دار با اینتر زدن روی فیلدها مبالغ را
        # وارد کنه و درنهایت تایید کنه»): اینتر رویِ هر ردیف به مبلغِ
        # ردیفِ بعدی می‌پرد؛ رویِ آخرین ردیف، همان اینتر ذخیره می‌کند.
        amount_field.returnPressed.connect(lambda af=amount_field: self._on_amount_return_pressed(af))
        self.table.setCellWidget(row_index, 1, amount_field)

        # طبقِ درخواستِ صریح («جلویِ هر ردیف... فیلدِ انتخابِ تفصیلی...
        # همیشه یک ستونِ ثابت در جدول»): اگر معینِ نگاشته‌شده‌یِ این روش
        # اصلاً وجود نداشته باشد یا هیچ گزینه‌ای نداشته باشد، دکمه
        # غیرفعال با «—» نشان داده می‌شود -- در غیرِ این صورت، اگر
        # تفصیلی صریحاً داده نشده، پیش‌فرضِ همین روش (از تنظیماتِ
        # pos_settlement_method_defaults) خوانده می‌شود.
        _account_id, options = settlements_service.resolve_method_detail_options(
            self._company_id, self._direction, method_code,
        )
        detail_button = QPushButton()
        detail_button.setAutoDefault(False)
        if _account_id is None or not options:
            detail_button.setText("—")
            detail_button.setEnabled(False)
        else:
            if detail_account_id is None:
                default = settlements_service.get_pos_settlement_method_default(self._company_id, method_code)
                if default is not None:
                    detail_account_id = default.detail_account_id
            self._row_detail_ids[row_index] = detail_account_id
            detail_button.setText(self._detail_label(detail_account_id, options))
            detail_button.clicked.connect(lambda _checked=False, b=detail_button, o=options: self._pick_detail(b, o))
        self.table.setCellWidget(row_index, 2, detail_button)

        if self._pos_mode:
            # طبقِ درخواستِ صریح («بتوان ردیفِ دومِ همان روش را هم اضافه
            # کرد»): این دکمه یک ردیفِ تازه با همان روش در انتهایِ جدول
            # اضافه می‌کند -- نه در همین‌جا (وسطِ جدول)، تا شماره‌ردیفِ
            # ردیف‌هایِ دیگر جابه‌جا نشود.
            add_button = QPushButton("➕")
            add_button.setAutoDefault(False)
            add_button.setFixedWidth(34)
            add_button.setToolTip("افزودنِ ردیفِ دیگری با همین روش")
            add_button.clicked.connect(lambda _checked=False, mc=method_code: self._add_row(mc))
            self.table.setCellWidget(row_index, 3, add_button)

        self._update_remaining()

    def _on_amount_return_pressed(self, amount_field: "_AmountField") -> None:
        row_index = self._row_index_for_widget(1, amount_field)
        if row_index is None:
            return
        next_index = row_index + 1
        if next_index < self.table.rowCount():
            next_field = self.table.cellWidget(next_index, 1)
            if next_field is not None:
                next_field.setFocus()
                next_field.selectAll()
        else:
            self._save()

    def _remaining_amount(self) -> decimal.Decimal:
        lines_total = sum((amount for _m, amount, _n, _d in self._collect_lines()), decimal.Decimal("0"))
        return self._total_amount - lines_total

    def _collect_lines(self) -> list[tuple[str, decimal.Decimal, str | None, int | None]]:
        lines: list[tuple[str, decimal.Decimal, str | None, int | None]] = []
        for row_index in range(self.table.rowCount()):
            amount_field = self.table.cellWidget(row_index, 1)
            amount = decimal.Decimal(str(amount_field.value()))
            if amount <= 0:
                continue
            detail_id = self._row_detail_ids[row_index] if row_index < len(self._row_detail_ids) else None
            lines.append((self._row_method_codes[row_index], amount, None, detail_id))
        return lines

    def _update_remaining(self, *_args) -> None:
        remaining = self._remaining_amount()
        self.remaining_label.setText(f"مانده (نسیه): {numerals.format_money(remaining, self._decimal_places)}")
        self.remaining_label.setStyleSheet("color: #b91c1c; font-weight: bold;" if remaining < 0 else "")

    def _load_existing(self) -> None:
        # طبقِ درخواستِ صریح («همه روش‌هایِ دریافت... فیکس بشه»): همیشه
        # به‌ازایِ هر روشِ ممکن (self._method_codes()) دقیقاً یک ردیفِ
        # ثابت ساخته می‌شود -- چه نقشه‌ای از قبل ذخیره شده باشد چه نه.
        # اگر نقشه‌ای از قبل باشد، مبلغ/تفصیلیِ همان روش در ردیفِ
        # متناظرش پر می‌شود. طبقِ گزارشِ بعدی («ردیفِ دومِ همان روش»)،
        # اگر نقشه بیش‌از‌یک ردیف با همان روش داشته باشد (دوپلیکیت)، هر
        # ردیفِ اضافی هم -- به همان ترتیب -- بازسازی می‌شود.
        plan = settlements_service.get_settlement_plan(self._document_id, self._company_id)
        lines_by_method: dict[str, list] = {}
        if plan is not None:
            for line in plan.lines:
                lines_by_method.setdefault(line.method_code, []).append(line)
        elif self._seed_lines:
            # طبقِ درخواستِ صریح («طبقِ حافظه مقادیرِ دریافتیِ قبلی، مثلاً
            # اگر نقدی بود در فیلدِ نقد...»): entry = (method_code,
            # amount, note, detail_account_id) -- هم‌الگو با فرمتِ
            # settlements_service.SettlementPlanLine.
            for entry in self._seed_lines:
                method_code, amount = entry[0], entry[1]
                detail_account_id = entry[3] if len(entry) > 3 else None
                seed_line = types.SimpleNamespace(method_code=method_code, amount=amount, detail_account_id=detail_account_id)
                lines_by_method.setdefault(method_code, []).append(seed_line)
        method_codes = self._method_codes()
        for code in method_codes:
            bucket = lines_by_method.get(code) or []
            if bucket:
                first_line = bucket.pop(0)
                self._add_row(code, first_line.amount, first_line.detail_account_id)
            else:
                self._add_row(code)
        # اگر نقشه ردیفی با روشی خارج از فهرستِ فعلی داشته باشد (مثلاً
        # روشِ سفارشیِ بعداً غیرفعال‌شده)، یا ردیفِ دومِ همان روش
        # (دوپلیکیت) باشد، برایِ اینکه مبلغِ آن گم نشود همان ردیف هم
        # اضافه می‌شود.
        for code, bucket in lines_by_method.items():
            for line in bucket:
                self._add_row(code, line.amount, line.detail_account_id)

        if plan is None:
            if self._require_manager_approval:
                self.status_banner.setText(
                    "هنوز نحوه‌یِ تسویه‌ای ذخیره نشده است. اگر بخشی نقد/بانکی دریافت شده، مبلغش را جلویِ همان روش "
                    "وارد کنید و 💾 بزنید؛ اگر کاملاً نسیه است، مبلغی وارد نکنید و «🔖 ثبتِ کامل به‌عنوانِ نسیه» را بزنید."
                )
        else:
            self._apply_plan_status(plan)
        if self.table.rowCount() > 0:
            first_amount_field = self.table.cellWidget(0, 1)
            if first_amount_field is not None:
                first_amount_field.setFocus()

    def _apply_plan_status(self, plan: settlements_service.SettlementPlan) -> None:
        if not self._require_manager_approval:
            # طبقِ همان دلیل: صندوق‌دار خودش ذخیره می‌کند، تاییدِ جداگانه
            # لازم نیست -- جدول همیشه قابلِ‌ویرایش می‌ماند.
            self.status_banner.setText("✅ ذخیره شد.")
            self.status_banner.setStyleSheet("color: #15803d; font-weight: bold;")
            return
        self.table.setEnabled(not plan.is_approved)
        if plan.is_approved:
            approved_at = numerals.to_persian_digits(plan.approved_at.strftime("%Y-%m-%d %H:%M")) if plan.approved_at else ""
            self.status_banner.setText(f"✅ نحوه‌یِ تسویه تاییدِ مدیر شد. ({approved_at})")
            self.status_banner.setStyleSheet("color: #15803d; font-weight: bold;")
        else:
            self.status_banner.setText(
                "⏳ ذخیره شد. تاییدِ نحوه‌یِ تسویه و ثبتِ نهایی، هر دو با هم، از طریقِ دکمهٔ 🔒 «ثبتِ نهایی» "
                "در فرمِ اصلیِ فاکتور توسطِ مدیر انجام می‌شود -- نیازی به بازکردنِ دوبارهٔ همین دیالوگ نیست."
            )
            self.status_banner.setStyleSheet("color: #b45309; font-weight: bold;")

    def _save(self) -> None:
        lines = self._collect_lines()
        try:
            settlements_service.save_settlement_plan(
                self._document_id, self._company_id, app_session.current_user.user_id, lines,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        plan = settlements_service.get_settlement_plan(self._document_id, self._company_id)
        self._apply_plan_status(plan)
        if self._require_manager_approval:
            QMessageBox.information(self, "نحوه‌یِ تسویه", "نحوه‌یِ تسویه ذخیره شد؛ برایِ ثبتِ نهایی نیازِ تاییدِ مدیر دارد.")
        else:
            # طبقِ درخواستِ صریح («صندوق‌دار با اینتر ... درنهایت تایید
            # کنه»): در حالتِ صندوق (بدونِ تاییدِ مدیر)، ذخیره یعنی
            # تاییدِ نهایی -- دیگر نیازی به پیامِ تاییدیه و بستنِ دستی
            # نیست.
            self.accept()

    def _save_as_full_credit(self) -> None:
        """طبقِ گزارشِ صریحِ کاربر: مسیرِ یک‌کلیکی برایِ فاکتورِ کاملاً
        نسیه -- همه‌یِ ردیف‌ها صفر می‌شوند (یعنی هیچ روشی انتخاب نشده) و
        بلافاصله ذخیره می‌شود؛ خودِ save_settlement_plan با فهرستِ خالی
        از قبل پشتیبانی می‌کند (نسیه = مانده‌یِ خودکار، نه یک ردیفِ روش)."""
        for row_index in range(self.table.rowCount()):
            amount_field = self.table.cellWidget(row_index, 1)
            if amount_field is not None:
                amount_field.setValue(0)
        self._save()


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
        self._upsell_suggestions: list = []
        self._main_window = main_window
        self._document_id: int | None = None
        self._settlement_plan: settlements_service.SettlementPlan | None = None
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

        # طبقِ طرحِ نمونه‌یِ ارسالیِ کاربر (کارت‌هایِ رنگیِ آیکون‌دار): چیدمانِ
        # این سه کارت هم‌راستا با ترتیبِ اهمیت است -- «جمعِ کل» (سبز، مهم‌ترین
        # عدد برایِ کاربر) در سمتِ راست، «تخفیف/مالیات» (کهربایی) وسط، و
        # «جمعِ ناخالص» (خنثی) در سمتِ چپ. چون QHBoxLayout در حالتِ راست‌به‌چپ
        # اولین ویجتِ اضافه‌شده را در سمتِ راست می‌گذارد، ترتیبِ درجِ دیکشنری
        # همین ترتیبِ بصری را تولید می‌کند.
        self.summary_cards = SummaryCardBar({
            "grand_total": SummaryCard("جمعِ کل", role="success", icon="✅"),
            "discount_tax": SummaryCard("تخفیف/مالیات", role="warning", icon="🏷️"),
            "subtotal": SummaryCard("جمعِ ناخالص", role="neutral", icon="📋"),
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
        # طبقِ رفعِ باگِ واقعی («پیمایشِ فیلدها ادامه پیدا نمی‌کند»): این
        # زنجیره قبلاً همیشه channel_combo/cost_center/project را
        # به‌صورتِ ثابت می‌گنجاند و due_date_field/consignment_warehouse_
        # combo/tax_posting_mode_combo را اصلاً نمی‌گنجاند -- برایِ فاکتورِ
        # خرید (که channel_box مخفی است) Enter رویِ فهرستِ قیمت، فوکوس را
        # به یک ویجتِ نامرئی می‌فرستاد و زنجیره همان‌جا متوقف می‌شد؛ و
        # برایِ هر فاکتوری، فیلدهایِ موعدِ تسویه/نوعِ ثبت (که واقعاً نمایان‌
        # اند) هیچ‌وقت با Enter قابلِ‌دسترس نبودند. حالا فقط فیلدهایِ واقعاً
        # نمایانِ همین نوعِ سند (که در سازنده‌یِ همین صفحه یک‌بار و برایِ
        # همیشه مشخص می‌شوند) به زنجیره اضافه می‌شوند -- طبقِ isHidden()
        # (نه isVisible()، چون این‌جا صفحه هنوز show() نشده و isVisible()
        # همیشه False برمی‌گرداند).
        header_chain = [
            self.date_field, self.counterparty_combo, self.warehouse_combo, self.reference_field,
            self.price_list_combo,
        ]
        if not self.channel_box.isHidden():
            header_chain.append(self.channel_combo)
        header_chain.append(self.description_field)
        header_chain += [self.cost_center_combo, self.project_combo]
        if not self.due_date_box.isHidden():
            header_chain.append(self.due_date_field)
        if not self.consignment_warehouse_box.isHidden():
            header_chain.append(self.consignment_warehouse_combo)
        if not self.tax_posting_mode_box.isHidden():
            header_chain.append(self.tax_posting_mode_combo)
        for widget, next_widget in zip(header_chain, header_chain[1:]):
            _enter_signal(widget).connect(next_widget.setFocus)
        # طبقِ گزارشِ صریحِ کاربر («بعد از اینکه هدر را تکمیل می‌کنیم، باز
        # فرمِ ردیفِ کالا باز می‌شه؛ انتظار اینه که مستقیم روی ردیفِ کالا
        # و نامِ کالا بیاد و اونجا جستجویِ کالا انجام بشه»): از R145 دیگر
        # نیازی به بازکردنِ دیالوگِ ردیف نیست -- یک ردیفِ ورودیِ
        # همیشه‌حاضر در انتهایِ lines_table وجود دارد؛ پس Enterِ فیلدِ
        # آخرِ هدر باید مستقیم فوکوس را به کمبویِ کالایِ همان ردیف ببرد
        # (نه اینکه دیالوگِ قدیمی را باز کند).
        _enter_signal(header_chain[-1]).connect(self._focus_entry_row_item)
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
        # طبقِ طرحِ نمونه‌یِ ارسالیِ کاربر («۲ ردیف» کنارِ عنوانِ جدول):
        # یک نشان‌واره‌یِ کوچکِ خاکستری با تعدادِ ردیفِ جاری -- در
        # _refresh_lines_table به‌روزرسانی می‌شود.
        self.line_count_badge = QLabel("")
        self.line_count_badge.setStyleSheet(
            f"background-color: {theme.rgba(theme.TEXT_SECONDARY, 0.12)}; color: {theme.TEXT_SECONDARY}; "
            "border-radius: 9px; padding: 1px 8px; font-size: 11px; font-weight: 700;"
        )
        status_row.addWidget(self.line_count_badge)
        # طبقِ گزارشِ صریحِ کاربر («لازم نیست اون علامتِ افزودنِ ردیف در
        # هدر باشه و فضا اشغال کنه»): از R145/R147 دیگر یک ردیفِ ورودیِ
        # همیشه‌حاضر در انتهایِ خودِ جدول هست که با زنجیره‌یِ Enter کاملاً
        # قابلِ‌استفاده است -- این دکمه دیگر لازم نیست. خودِ تابعِ
        # _add_line (بازکردنِ دیالوگِ قدیمی) هنوز به‌عنوانِ fallback در
        # _focus_entry_row_item نگه داشته می‌شود.
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
        # طبقِ گزارشِ صریحِ کاربر («همچنان ردیفِ فاکتور خیلی ارتفاعِ کمی
        # داره»): ارتفاعِ پیش‌فرضِ Qt برایِ ردیف‌ها فشرده است؛ این‌جا
        # آگاهانه بزرگ‌تر شده تا خواناییِ ردیف‌هایِ فاکتور بهتر شود. طبقِ
        # R145/R146 که چند ویجتِ تعاملیِ تازه (فیلدهایِ قابلِ‌ویرایش، کمبویِ
        # نوعِ تخفیف، و ۴ دکمهٔ ستونِ عملیات) به هر ردیف اضافه کردند،
        # عددِ قبلی (۴۰) دیگر برایِ این‌همه ویجتِ فشرده در یک ردیف کافی
        # نبود -- به ۴۸ افزایش یافت.
        self.lines_table.verticalHeader().setDefaultSectionSize(48)
        # طبقِ طرحِ نمونه‌یِ ارسالیِ کاربر: ستونِ «#» و «عملیات» عرضِ ثابتِ
        # کوچک دارند، ستونِ «کالا» (که حالا اندیسِ ۱ است، نه ۰) کاملِ
        # فضایِ باقی‌مانده را می‌گیرد.
        self.lines_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.lines_table.setColumnWidth(0, 32)
        last_col = len(_LINE_COLUMNS) - 1
        self.lines_table.horizontalHeader().setSectionResizeMode(last_col, QHeaderView.Fixed)
        # طبقِ موردِ ۳ («کاردکس/قیمتِ قبلی در همان ردیف»): دو دکمهٔ تازه
        # (📇/🕘) کنارِ ویرایش/حذفِ قدیمی اضافه شد -- پس این ستون هم
        # عریض‌تر شده تا هر چهار دکمه جا شوند.
        self.lines_table.setColumnWidth(last_col, 130)
        # طبقِ گزارشِ صریحِ کاربر («اندازه‌یِ فیلدِ کالا در ردیفِ فاکتور
        # کمتر بشه و اندازه‌یِ بهایِ واحد و توضیح بیشتر بشه»): «کالا»
        # دیگر Stretch نیست (کمبویِ جست‌وجوگر است، نیازی به نمایشِ کاملِ
        # نامِ کالا در همان عرض ندارد)، «توضیح» به‌جایش Stretch شده تا
        # فضایِ باقی‌ماندهٔ پنجره را بگیرد و با محتوایِ متنیِ متغیرش
        # هم‌خوان‌تر باشد.
        _line_column_widths = {
            1: 200,  # کالا
            2: 80,   # مقدار
            3: 130,  # بهایِ واحد
            4: 130,  # تخفیف (کمبویِ نوع + فیلدِ مبلغ/درصد)
            5: 70,   # درصدِ مالیات
            6: 90,   # مالیات
            7: 110,  # جمعِ ردیف
        }
        for column_index, width in _line_column_widths.items():
            self.lines_table.horizontalHeader().setSectionResizeMode(column_index, QHeaderView.Interactive)
            self.lines_table.setColumnWidth(column_index, width)
        self.lines_table.horizontalHeader().setSectionResizeMode(8, QHeaderView.Stretch)
        self.lines_table.setMinimumHeight(220)
        self.lines_table.cellDoubleClicked.connect(self._edit_line)
        self.body_layout.addWidget(self.lines_table)

        self.step_stepper.register_sections(self._scroll, [self.page_title, self.lines_table])

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

        # طبقِ درخواستِ صریح («فروشِ ارتقایی»): زیرساختِ کالاهایِ
        # جایگزین (catalog_service.list_related_items, نوعِ SUBSTITUTE)
        # از قبل در فرمِ کالا قابلِ‌تعریف بود ولی هیچ‌جا استفاده نمی‌شد --
        # این‌جا اگر کالایِ همین ردیف جایگزینی با قیمتِ فروشِ بالاتر
        # دارد، پیشنهادِ ارتقا نشان داده می‌شود.
        self.upsell_box = QWidget()
        self._upsell_layout = QVBoxLayout(self.upsell_box)
        self._upsell_layout.setContentsMargins(0, 0, 0, 0)
        self._upsell_layout.setSpacing(4)
        self.upsell_box.setVisible(False)
        self.body_layout.addWidget(self.upsell_box)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        self.body_layout.addWidget(self.status_label)
        self.body_layout.addStretch(1)

        # طبقِ درخواستِ صریح («یک دکمه سمت راست اضافه کن که بتونم نحوه‌یِ
        # تسویه را مشخص کنم»): چون در چیدمانِ راست‌به‌چپ اولین ویجتِ
        # اضافه‌شده به یک QHBoxLayout در سمتِ راست ظاهر می‌شود، این دکمه
        # پیش از همه‌یِ دکمه‌هایِ دیگرِ فوتر اضافه می‌شود -- فقط برایِ
        # فاکتورِ خرید/فروش نمایان است.
        self.settlement_plan_button = QPushButton("🧾")
        self.settlement_plan_button.setObjectName("iconButton")
        self.settlement_plan_button.setFixedWidth(44)
        self.settlement_plan_button.setToolTip(
            "نحوه‌یِ تسویه — تعیینِ ترکیبِ نقد/بانک(کارتخوان)/بن/کالابرگ/تخفیف/نسیه؛ "
            "پیش از ثبتِ نهایی نیازِ تاییدِ مدیر دارد."
        )
        self.settlement_plan_button.clicked.connect(self._open_settlement_plan)
        self.settlement_plan_button.setVisible(document_type_code in ("SALES_INVOICE", "PURCHASE_INVOICE"))
        self.footer_layout.addWidget(self.settlement_plan_button)

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
        if self._is_invoice:
            # طبقِ گزارشِ صریحِ کاربر («روالِ ثبتِ فاکتور خیلی سخت شد...
            # کاربر فاکتور را صادر می‌کند و نحوه‌یِ دریافت هم در ابتدا
            # مشخص می‌شود»): برایِ فاکتورِ خرید/فروش، همین یک دکمه هم
            # تاییدِ سند و هم پرسیدنِ نحوه‌یِ تسویه (نقد/بانکی یا نسیه) را
            # با هم انجام می‌دهد -- به‌جایِ اینکه کاربر مجبور باشد بعداً
            # جداگانه دکمهٔ 🧾 را پیدا کند.
            self.confirm_button.setToolTip(
                "۲) ثبتِ فاکتور — سند تایید می‌شود و بلافاصله نحوه‌یِ تسویه (دریافت/پرداختِ نقد و بانکی، یا نسیه) پرسیده می‌شود"
            )
        else:
            self.confirm_button.setToolTip("۲) تاییدِ سند — گامِ اولِ گردشِ کار پس از پیش‌نویس؛ سند برایِ تصویب/ثبتِ نهایی آماده می‌شود")
        self.confirm_button.clicked.connect(self._confirm_button_clicked)
        self.footer_layout.addWidget(self.confirm_button)

        self.approve_button = QPushButton("👍")
        self.approve_button.setObjectName("iconButton")
        self.approve_button.setFixedWidth(44)
        self.approve_button.setToolTip("۳) تصویبِ سند — تاییدِ مدیریتیِ اضافه پیش از ثبتِ نهایی (اختیاری، پیش از ثبتِ نهایی انجام می‌شود)")
        self.approve_button.clicked.connect(self._approve)
        # طبقِ همان گزارش («دکمه‌هایِ ثبتِ فراوان»): این دکمه برایِ فاکتورِ
        # خرید/فروش هیچ اثرِ واقعی‌ای ندارد -- approve_document فقط
        # قفلِ اعتباریِ SALES_ORDER را بررسی می‌کند (که برایِ فاکتور هرگز
        # ساخته نمی‌شود) و ثبتِ نهایی هم بدونش (فقط با CONFIRMED) کار
        # می‌کند؛ تنها نتیجه‌اش برایِ فاکتور، افزودنِ یک کلیکِ بی‌فایده به
        # گردشِ کار بود.
        self.approve_button.setVisible(not self._is_invoice)
        self.footer_layout.addWidget(self.approve_button)

        self.post_button = QPushButton("🔒")
        self.post_button.setObjectName("primaryIconButton")
        self.post_button.setFixedWidth(48)
        self.post_button.setToolTip(_POST_BUTTON_DEFAULT_TOOLTIP)
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
        default_type = "SALES_INVOICE" if self.document_type_code in _SALES_TYPES else "PURCHASE_INVOICE"
        dialog = _CounterpartyHistoryDialog(
            self, company_id, counterparty_id, self.counterparty_combo.currentText(),
            default_document_type_code=default_type,
        )
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
            # طبقِ درخواستِ صریح («فیلد برایِ نمایشِ کد و اسم کافی نیست --
            # فقط اسم کافی است»): برخلافِ فهرستِ قیمت که از قبل فقط نام
            # نشان می‌داد، این‌جا هنوز کد هم اضافه می‌شد و با عرضِ محدودِ
            # فیلدِ هدر بریده می‌شد.
            self.cost_center_combo.addItem(opt.name or opt.code, opt.detail_account_id)
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
            self.project_combo.addItem(opt.name or opt.code, opt.detail_account_id)
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
        # طبقِ درخواستِ صریح («دکمه‌یِ نحوهٔ تسویه در فرمِ فاکتور»): نقشه‌یِ
        # تسویه (اگر برایِ این فاکتور ذخیره شده) با هر بارگذاریِ سند
        # دوباره خوانده می‌شود -- هم برایِ نمایشِ وضعیت، هم برایِ گذرگاهِ
        # اجباریِ پیش از ثبتِ نهایی.
        self._settlement_plan = (
            settlements_service.get_settlement_plan(self._document_id, company_id) if self._is_invoice else None
        )
        self._apply_status_state()

    def _refresh_lines_table(self) -> None:
        # طبقِ سندِ راهنمایِ UI/UX (بخشِ ۶.۳ — نمایشِ مبلغ‌ها طبقِ تنظیماتِ
        # واحدِ پولی): قبلاً این جدول با str() خامِ Decimal پر می‌شد —
        # نه گروه‌بندیِ سه‌رقمی، نه ارقامِ فارسی، نه تعدادِ اعشارِ درستِ
        # واحدِ پول.
        #
        # طبقِ گزارشِ صریحِ کاربر («در همان ردیف تعداد و قیمت و تخفیف و
        # مالیات را وارد کرد و نیازی به فرمِ ردیفِ کالا وجود نداشته
        # باشه»): وقتی سند قابلِ‌ویرایش است، ستون‌هایِ مقدار/بهایِ واحد/
        # تخفیف/درصدِ مالیات دیگر متنِ صرفاً‌نمایشی نیستند -- فیلدهایِ
        # واقعاً قابلِ‌ویرایش‌اند (تغییرشان با خروج از فیلد بی‌درنگ ذخیره
        # می‌شود) و یک ردیفِ آخرِ همیشه‌حاضر برایِ افزودنِ ردیفِ تازه (بدونِ
        # دیالوگ، فقط برایِ کالاهایِ ساده -- کالایِ دارایِ متغیر همچنان
        # دیالوگِ جدولیِ چندمتغیره را باز می‌کند، چون ماهیتاً یک‌به‌چند
        # است) اضافه می‌شود.
        dp = self._decimal_places
        items_by_id = {it.item_id: it for it in self._items}
        editable = self._lines_are_editable()
        self.lines_table.setRowCount(len(self._lines) + (1 if editable else 0))
        for row_index, ln in enumerate(self._lines):
            item = items_by_id.get(ln.item_id)
            if editable:
                self._render_editable_line_row(row_index, ln, item, dp)
            else:
                self._render_readonly_line_row(row_index, ln, item, dp)
        if editable:
            self._render_entry_row(len(self._lines), dp)
        self.line_count_badge.setText(f"{numerals.to_persian_digits(str(len(self._lines)))} ردیف")

    def _lines_are_editable(self) -> bool:
        # هم‌الگو با شرطِ ویرایش‌پذیریِ فیلدهایِ هدر در _apply_status_state.
        is_draft = self._status_code == "DRAFT"
        is_confirmed = self._status_code == "CONFIRMED"
        is_approved = self._status_code == "APPROVED"
        is_order_type = self.document_type_code in _CONVERTIBLE_TO_INVOICE_TYPES
        return is_draft or (is_order_type and (is_confirmed or is_approved))

    def _render_readonly_line_row(self, row_index: int, ln, item, dp: int) -> None:
        for col in (2, 3, 4, 5):
            self.lines_table.removeCellWidget(row_index, col)
        values = [
            numerals.to_persian_digits(str(row_index + 1)),
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
            if col_index == 0:
                cell.setTextAlignment(Qt.AlignCenter)
            elif col_index == 1:
                # طبقِ موردِ ۳ («اطلاعاتِ کالا شاملِ کاردکس و قیمت‌هایِ
                # قبلی و موجودی در همان ردیف قابلِ‌مشاهده باشه»): موجودی
                # و آخرین قیمت‌ها به‌عنوانِ Tooltip رویِ نامِ کالا -- بدونِ
                # هیچ کلیکی، با نگه‌داشتنِ ماوس دیده می‌شود.
                cell.setToolTip(self._item_info_tooltip_text(ln.item_id))
            self.lines_table.setItem(row_index, col_index, cell)
        self.lines_table.setCellWidget(row_index, len(values), self._make_line_actions_widget(row_index))

    def _make_inline_discount_widget(self, dp: int, discount_amount: decimal.Decimal, discount_percent: decimal.Decimal) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(2)
        field = _AmountField()
        field.setObjectName("inlineDiscountField")
        field.setDecimals(dp)
        type_combo = _EnterComboBox()
        type_combo.setObjectName("inlineDiscountType")
        type_combo.addItem("مبلغی", "AMOUNT")
        type_combo.addItem("درصدی", "PERCENT")
        type_combo.setMaximumWidth(58)
        if discount_percent:
            type_combo.setCurrentIndex(type_combo.findData("PERCENT"))
            field.setValue(float(discount_percent))
        else:
            type_combo.setCurrentIndex(type_combo.findData("AMOUNT"))
            field.setValue(float(discount_amount))
        layout.addWidget(field, stretch=1)
        layout.addWidget(type_combo)
        return container

    def _render_editable_line_row(self, row_index: int, ln, item, dp: int) -> None:
        idx_cell = QTableWidgetItem(numerals.to_persian_digits(str(row_index + 1)))
        idx_cell.setTextAlignment(Qt.AlignCenter)
        idx_cell.setData(Qt.UserRole, ln.line_id)
        self.lines_table.setItem(row_index, 0, idx_cell)
        item_cell = QTableWidgetItem(f"{item.code} — {item.name or ''}" if item else str(ln.item_id))
        item_cell.setData(Qt.UserRole, ln.line_id)
        item_cell.setToolTip(self._item_info_tooltip_text(ln.item_id))
        self.lines_table.setItem(row_index, 1, item_cell)

        qty_field = _AmountField()
        qty_field.setDecimals(3)
        qty_field.setValue(float(ln.quantity))
        qty_field.editingFinished.connect(lambda r=row_index: self._commit_inline_line_edit(r))
        self.lines_table.setCellWidget(row_index, 2, qty_field)

        price_field = _AmountField()
        price_field.setDecimals(dp)
        price_field.setValue(float(ln.unit_price))
        price_field.editingFinished.connect(lambda r=row_index: self._commit_inline_line_edit(r))
        self.lines_table.setCellWidget(row_index, 3, price_field)

        discount_container = self._make_inline_discount_widget(dp, ln.discount_amount, ln.discount_percent)
        discount_field = discount_container.findChild(_AmountField, "inlineDiscountField")
        discount_type_combo = discount_container.findChild(_EnterComboBox, "inlineDiscountType")
        discount_field.editingFinished.connect(lambda r=row_index: self._commit_inline_line_edit(r))
        # طبقِ رفعِ باگِ واقعیِ کشف‌شده حینِ تست: عوض‌کردنِ نوعِ تخفیف
        # (مبلغی/درصدی) نباید بلافاصله همان عددِ قدیمی را زیرِ تفسیرِ
        # تازه ذخیره کند -- مثلاً «۱۰۰۰ تومان» که به «درصدی» تغییر کند،
        # به‌جایِ رد شدن با خطایِ سرریزِ عددی، خودش را ۱۰۰۰٪ ذخیره
        # می‌کرد. پس با هر تغییرِ نوع، فیلد صفر می‌شود -- کاربر خودش
        # عددِ تازه را در واحدِ جدید وارد می‌کند.
        discount_type_combo.currentIndexChanged.connect(
            lambda _i=0, f=discount_field, r=row_index: self._on_inline_discount_type_changed(r, f)
        )
        self.lines_table.setCellWidget(row_index, 4, discount_container)

        tax_field = _AmountField()
        tax_field.setDecimals(2)
        tax_field.setValue(float(ln.tax_percent))
        tax_field.editingFinished.connect(lambda r=row_index: self._commit_inline_line_edit(r))
        self.lines_table.setCellWidget(row_index, 5, tax_field)

        self.lines_table.setItem(row_index, 6, QTableWidgetItem(numerals.format_money(ln.tax_amount, dp)))
        self.lines_table.setItem(row_index, 7, QTableWidgetItem(numerals.format_money(ln.line_total, dp)))
        self.lines_table.setItem(row_index, 8, QTableWidgetItem(ln.description or ""))
        self.lines_table.setCellWidget(row_index, 9, self._make_line_actions_widget(row_index))

    def _on_inline_discount_type_changed(self, row_index: int, discount_field) -> None:
        discount_field.setValue(0)
        self._commit_inline_line_edit(row_index)

    def _commit_inline_line_edit(self, row_index: int) -> None:
        if not (0 <= row_index < len(self._lines)):
            return
        line = self._lines[row_index]
        qty_widget = self.lines_table.cellWidget(row_index, 2)
        price_widget = self.lines_table.cellWidget(row_index, 3)
        discount_container = self.lines_table.cellWidget(row_index, 4)
        tax_widget = self.lines_table.cellWidget(row_index, 5)
        if qty_widget is None or price_widget is None or discount_container is None or tax_widget is None:
            return
        discount_field = discount_container.findChild(_AmountField, "inlineDiscountField")
        discount_type_combo = discount_container.findChild(_EnterComboBox, "inlineDiscountType")
        quantity = decimal.Decimal(str(qty_widget.value()))
        unit_price = decimal.Decimal(str(price_widget.value()))
        discount_value = decimal.Decimal(str(discount_field.value())) if discount_field is not None else decimal.Decimal(0)
        is_percent_discount = discount_type_combo.currentData() == "PERCENT" if discount_type_combo is not None else False
        tax_percent = decimal.Decimal(str(tax_widget.value()))
        company_id = self._company_id()
        if self._document_id is None or company_id is None:
            return
        current_discount_percent = line.discount_percent or decimal.Decimal(0)
        current_discount_amount = line.discount_amount or decimal.Decimal(0)
        unchanged = (
            quantity == line.quantity and unit_price == line.unit_price and tax_percent == line.tax_percent
            and (
                (is_percent_discount and discount_value == current_discount_percent)
                or (not is_percent_discount and current_discount_percent == 0 and discount_value == current_discount_amount)
            )
        )
        if unchanged:
            return
        if quantity <= 0:
            QMessageBox.warning(self, "خطا", "مقدار باید بزرگ‌تر از صفر باشد.")
            self._load_document()
            return
        try:
            documents_service.update_line(
                line.line_id, self._document_id, company_id, quantity=quantity, unit_price=unit_price,
                discount_amount=decimal.Decimal(0) if is_percent_discount else discount_value,
                discount_percent=discount_value if is_percent_discount else decimal.Decimal(0),
                tax_percent=tax_percent,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
        self._load_document()

    def _render_entry_row(self, row_index: int, dp: int) -> None:
        idx_cell = QTableWidgetItem("+")
        idx_cell.setTextAlignment(Qt.AlignCenter)
        self.lines_table.setItem(row_index, 0, idx_cell)

        item_options = [
            (it.item_id, f"{it.code} — {it.name or ''}") for it in self._items if it.variant_parent_item_id is None
        ]
        item_combo = _make_searchable_combo(item_options)
        item_combo.setCurrentIndex(-1)
        item_combo.lineEdit().clear()
        self.lines_table.setCellWidget(row_index, 1, item_combo)

        qty_field = _AmountField()
        qty_field.setDecimals(3)
        self.lines_table.setCellWidget(row_index, 2, qty_field)

        price_field = _AmountField()
        price_field.setDecimals(dp)
        self.lines_table.setCellWidget(row_index, 3, price_field)

        discount_container = self._make_inline_discount_widget(dp, decimal.Decimal(0), decimal.Decimal(0))
        discount_field = discount_container.findChild(_AmountField, "inlineDiscountField")
        discount_type_combo = discount_container.findChild(_EnterComboBox, "inlineDiscountType")
        # هم‌الگو با _on_inline_discount_type_changed: عوض‌کردنِ نوعِ
        # تخفیف، عددِ واردشده در واحدِ قبلی را پاک می‌کند -- تا کاربر با
        # دیدنِ همان عددِ قدیمی زیرِ واحدِ تازه گمراه نشود.
        discount_type_combo.currentIndexChanged.connect(lambda _i=0, f=discount_field: f.setValue(0))
        self.lines_table.setCellWidget(row_index, 4, discount_container)

        tax_field = _AmountField()
        tax_field.setDecimals(2)
        self.lines_table.setCellWidget(row_index, 5, tax_field)

        self.lines_table.setItem(row_index, 6, QTableWidgetItem(""))
        self.lines_table.setItem(row_index, 7, QTableWidgetItem(""))

        description_field = QLineEdit()
        description_field.setPlaceholderText("توضیح (اختیاری)")
        self.lines_table.setCellWidget(row_index, 8, description_field)

        actions_container = QWidget()
        actions_layout = QHBoxLayout(actions_container)
        actions_layout.setContentsMargins(2, 0, 2, 0)
        actions_layout.setSpacing(2)
        add_button = QPushButton("➕")
        add_button.setObjectName("primaryIconButton")
        add_button.setFixedWidth(28)
        add_button.setToolTip("افزودنِ این ردیف به سند")
        actions_layout.addWidget(add_button)
        # طبقِ موردِ ۳: پیش از افزودن هم بتوان موجودی/کاردکس/قیمتِ قبلیِ
        # کالایِ انتخاب‌شده را دید -- تا انتخابِ کالا مشخص نشده غیرفعال‌اند.
        info_kardex_button = QPushButton("📇")
        info_kardex_button.setObjectName("iconButton")
        info_kardex_button.setFixedWidth(28)
        info_kardex_button.setToolTip("کاردکسِ کالایِ انتخاب‌شده")
        info_kardex_button.setEnabled(False)
        info_kardex_button.clicked.connect(
            lambda _checked=False, c=item_combo: self._open_item_kardex(c.currentData()) if c.currentData() is not None else None
        )
        actions_layout.addWidget(info_kardex_button)
        info_price_button = QPushButton("🕘")
        info_price_button.setObjectName("iconButton")
        info_price_button.setFixedWidth(28)
        info_price_button.setToolTip("قیمت‌هایِ قبلیِ کالایِ انتخاب‌شده")
        info_price_button.setEnabled(False)
        info_price_button.clicked.connect(
            lambda _checked=False, c=item_combo: self._open_item_price_history(c.currentData()) if c.currentData() is not None else None
        )
        actions_layout.addWidget(info_price_button)
        self.lines_table.setCellWidget(row_index, 9, actions_container)

        self._entry_row_widgets = {
            "item_combo": item_combo, "qty": qty_field, "price": price_field,
            "info_kardex_button": info_kardex_button, "info_price_button": info_price_button,
            "discount": discount_field, "discount_type": discount_type_combo,
            "tax": tax_field, "description": description_field,
        }
        item_combo.currentIndexChanged.connect(self._on_entry_row_item_changed)
        add_button.clicked.connect(self._commit_entry_row)
        enter_chain = [item_combo, qty_field, price_field, discount_field, discount_type_combo, tax_field, description_field]
        for widget, next_widget in zip(enter_chain, enter_chain[1:]):
            _enter_signal(widget).connect(next_widget.setFocus)
        _enter_signal(description_field).connect(self._commit_entry_row)

    def _on_entry_row_item_changed(self) -> None:
        widgets = getattr(self, "_entry_row_widgets", None)
        if not widgets:
            return
        item_id = widgets["item_combo"].currentData()
        if item_id is None:
            return
        variant_parent_ids = {it.variant_parent_item_id for it in self._items if it.variant_parent_item_id}
        if item_id in variant_parent_ids:
            # طبقِ ماهیتِ ذاتاً یک‌به‌چندِ کالایِ متغیر (چند ردیفِ هم‌زمان،
            # یکی به‌ازایِ هر متغیر) -- این حالت در همان یک ردیفِ ورودی
            # جا نمی‌شود؛ همان دیالوگِ جدولیِ چندمتغیره (بدونِ هیچ تغییری)
            # باز می‌شود.
            self._open_line_dialog_for_item(item_id)
            return
        item = next((it for it in self._items if it.item_id == item_id), None)
        if item is None:
            return
        # طبقِ موردِ ۳: به‌محضِ انتخابِ کالا در همین ردیفِ ورودی، دکمه‌هایِ
        # کاردکس/قیمتِ قبلی فعال می‌شوند و موجودی/آخرین قیمت به‌عنوانِ
        # Tooltipِ کمبویِ کالا نمایش داده می‌شود -- پیش از ثبتِ ردیف.
        widgets["info_kardex_button"].setEnabled(True)
        widgets["info_price_button"].setEnabled(True)
        widgets["item_combo"].setToolTip(self._item_info_tooltip_text(item_id))
        company_id = self._company_id()
        if company_id is None:
            return
        default_tax = catalog_service.resolve_default_tax_percent(company_id, item_id)
        widgets["tax"].setValue(float(default_tax))
        counterparty_id = self.counterparty_combo.currentData()
        if counterparty_id is None:
            return
        try:
            resolved = pricing_service.resolve_price(
                company_id, counterparty_id, item_id, item.base_uom_id, decimal.Decimal(1),
                self.price_list_combo.currentData(), self.document_type_code, self.date_field.date(),
            )
        except ValueError:
            self.status_label.setText("قیمتی از قراردادِ فعال یا فهرستِ قیمت یافت نشد -- قیمت را دستی وارد کنید.")
            return
        self.status_label.setText("")
        widgets["price"].setValue(float(resolved.unit_price))
        if resolved.discount_amount:
            widgets["discount"].setValue(float(resolved.discount_amount))

    def _open_line_dialog_for_item(self, item_id: int) -> None:
        if not self._ensure_saved():
            self._load_document()
            return
        dialog = _LineDialog(
            self, self._items, self._company_id(), self._main_window, self._decimal_places,
            counterparty_id=self.counterparty_combo.currentData(), price_list_id=self.price_list_combo.currentData(),
            document_type_code=self.document_type_code, document_date=self.date_field.date(),
            warehouses=self._warehouses, default_warehouse_id=self.warehouse_combo.currentData(),
            per_line_warehouse_enabled=self._per_line_warehouse_enabled,
        )
        index = dialog.item_combo.findData(item_id)
        if index >= 0:
            dialog.item_combo.setCurrentIndex(index)
        if dialog.exec() != QDialog.Accepted:
            self._load_document()
            return
        self._commit_line_dialog_result(dialog)

    def _commit_line_dialog_result(self, dialog: "_LineDialog") -> None:
        fields_list = dialog.result_fields_list()
        company_id = self._company_id()
        errors = []
        last_item_id = None
        for fields in fields_list:
            try:
                documents_service.add_line(self._document_id, company_id, **fields)
                last_item_id = fields.get("item_id")
                self._warn_if_consignment_cost_mixing(fields.get("item_id"), fields.get("warehouse_id") or self.warehouse_combo.currentData())
            except ValueError as exc:
                item = next((it for it in self._items if it.item_id == fields.get("item_id")), None)
                label = f"{item.code} — {item.name or ''}" if item else str(fields.get("item_id"))
                errors.append(f"{label}: {exc}")
        self._load_document()
        if last_item_id is not None:
            self._refresh_cross_sell_suggestion(last_item_id)
            self._refresh_upsell_suggestion(last_item_id)
        if errors:
            QMessageBox.warning(self, "خطا در برخی ردیف‌ها", "\n".join(errors))

    def _focus_entry_row_item(self) -> None:
        # طبقِ گزارشِ صریحِ کاربر: به‌جایِ بازکردنِ دیالوگِ ردیف، مستقیم
        # فوکوس به کمبویِ کالایِ ردیفِ ورودیِ همیشه‌حاضر می‌رود -- کاربر
        # بی‌درنگ می‌تواند جستجویِ کالا را همان‌جا شروع کند. اگر به هر
        # دلیلی (مثلاً سند دیگر قابلِ‌ویرایش نیست) این ردیف وجود نداشت،
        # به رفتارِ قدیمی (بازکردنِ دیالوگ) بازمی‌گردیم -- بی‌اثر نماندن.
        widgets = getattr(self, "_entry_row_widgets", None)
        if widgets is not None:
            widgets["item_combo"].setFocus()
        else:
            self._add_line()

    def _commit_entry_row(self) -> None:
        widgets = getattr(self, "_entry_row_widgets", None)
        if not widgets:
            return
        item_id = widgets["item_combo"].currentData()
        if item_id is None:
            self.status_label.setText("کالا را انتخاب کنید.")
            return
        if widgets["qty"].value() <= 0:
            self.status_label.setText("مقدار باید بزرگ‌تر از صفر باشد.")
            return
        item = next((it for it in self._items if it.item_id == item_id), None)
        if item is None:
            return
        # طبقِ رفعِ باگِ واقعی: اگر سند هنوز ذخیره نشده، _ensure_saved زیرِ
        # پوست _load_document (بازسازیِ کاملِ lines_table، از جمله همینِ
        # ردیفِ ورودی) را صدا می‌زند -- پس همه‌یِ مقادیر باید *پیش* از آن
        # از رویِ ویجت‌ها خوانده و به Python/Decimalِ خام تبدیل شوند،
        # وگرنه بعدِ بازسازی به شیءِ Qtِ ازبین‌رفته دسترسی پیدا می‌کردیم.
        quantity = decimal.Decimal(str(widgets["qty"].value()))
        unit_price = decimal.Decimal(str(widgets["price"].value())) if widgets["price"].value() > 0 else None
        is_percent_discount = widgets["discount_type"].currentData() == "PERCENT"
        discount_value = decimal.Decimal(str(widgets["discount"].value()))
        tax_percent = decimal.Decimal(str(widgets["tax"].value()))
        description = widgets["description"].text().strip() or None
        if not self._ensure_saved():
            return
        try:
            documents_service.add_line(
                self._document_id, self._company_id(), item_id=item_id, uom_id=item.base_uom_id,
                quantity=quantity, quantity_base=quantity, unit_price=unit_price,
                discount_amount=decimal.Decimal(0) if is_percent_discount else discount_value,
                discount_percent=discount_value if is_percent_discount else decimal.Decimal(0),
                tax_percent=tax_percent, description=description,
                warehouse_id=self.warehouse_combo.currentData() if self.warehouse_combo is not None else None,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._warn_if_consignment_cost_mixing(
            item_id, self.warehouse_combo.currentData() if self.warehouse_combo is not None else None
        )
        self._load_document()
        self._refresh_cross_sell_suggestion(item_id)
        self._refresh_upsell_suggestion(item_id)
        # طبقِ گزارشِ صریحِ کاربر («در پایانِ سطر، سطرِ بعدی را ایجاد
        # کند»): بعدِ ثبتِ موفقِ یک ردیف، فوکوس بلافاصله به کمبویِ کالایِ
        # همان ردیفِ ورودیِ تازه‌ساخته‌شده (که _load_document بالا از نو
        # ساخته) برمی‌گردد -- کاربر بدونِ برداشتنِ دست از صفحه‌کلید
        # می‌تواند بلافاصله ردیفِ بعدی را هم وارد کند.
        self._focus_entry_row_item()

    def _make_line_actions_widget(self, row_index: int) -> QWidget:
        # طبقِ طرحِ نمونه‌یِ ارسالیِ کاربر: دکمه‌هایِ ویرایش/حذف حالا در
        # همان ستونِ «عملیات»یِ ردیف نشسته‌اند -- نه یک خوشه‌یِ جداگانه‌یِ
        # زیرِ جدول که به «ردیفِ انتخاب‌شده»یِ کلی وابسته بود. طبقِ رفعِ
        # باگِ واقعی (کشف‌شده حینِ تست): `QTableWidget.selectRow()` در
        # چیدمانِ راست‌به‌چپ برایِ یافتنِ ستونِ لنگر به عرضِ واقعیِ
        # viewport نیاز دارد -- زیرِ پلتفرمِ offscreen (و گاهی حتی در
        # اجرایِ واقعی، پیش از یک چرخه‌یِ کاملِ layout) این عرض هنوز صفر
        # است و selectRow() هیچ سلولی را انتخاب نمی‌کند، پس _selected_line()
        # هم چیزی برنمی‌گرداند. برایِ همین این دکمه‌ها مستقیم رویِ
        # self._lines[row_index] عمل می‌کنند -- بدونِ وابستگی به هیچ
        # انتخابِ رویِ صفحه.
        container = QWidget()
        container.setLayoutDirection(Qt.LeftToRight)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(2)
        edit_button = QPushButton("✏️")
        edit_button.setObjectName("iconButton")
        edit_button.setFixedWidth(28)
        edit_button.setToolTip("ویرایشِ ردیف")
        edit_button.clicked.connect(lambda _checked=False, r=row_index: self._edit_line_at_row(r))
        layout.addWidget(edit_button)
        delete_button = QPushButton("🗑️")
        delete_button.setObjectName("dangerIconButton")
        delete_button.setFixedWidth(28)
        delete_button.setToolTip("حذفِ ردیف")
        delete_button.clicked.connect(lambda _checked=False, r=row_index: self._delete_line_at_row(r))
        layout.addWidget(delete_button)
        # طبقِ موردِ ۳ («کاردکس و قیمت‌هایِ قبلی و موجودی در همان ردیف
        # قابلِ‌مشاهده باشه»): دو دکمهٔ سریع، مستقیم رویِ کالایِ همین
        # ردیف -- بدونِ نیاز به بازکردنِ فرمِ ردیف/دیالوگِ افزودن.
        kardex_button = QPushButton("📇")
        kardex_button.setObjectName("iconButton")
        kardex_button.setFixedWidth(28)
        kardex_button.setToolTip("کاردکسِ این کالا")
        kardex_button.clicked.connect(
            lambda _checked=False, r=row_index: self._open_item_kardex(self._lines[r].item_id) if 0 <= r < len(self._lines) else None
        )
        layout.addWidget(kardex_button)
        price_history_button = QPushButton("🕘")
        price_history_button.setObjectName("iconButton")
        price_history_button.setFixedWidth(28)
        price_history_button.setToolTip("قیمت‌هایِ قبلیِ این کالا به همین طرفِ‌حساب")
        price_history_button.clicked.connect(
            lambda _checked=False, r=row_index: self._open_item_price_history(self._lines[r].item_id) if 0 <= r < len(self._lines) else None
        )
        layout.addWidget(price_history_button)
        return container

    def _item_info_tooltip_text(self, item_id: int) -> str:
        """طبقِ موردِ ۳ («اطلاعاتِ کالا شاملِ کاردکس و قیمت‌هایِ قبلی و
        موجودی در همان ردیف قابلِ‌مشاهده باشه»): موجودیِ کل/به‌ازایِ هر
        انبار + آخرین قیمت‌هایِ همین کالا به همین طرفِ‌حساب -- بدونِ هیچ
        کلیکی، فقط با نگه‌داشتنِ ماوس رویِ نامِ کالا دیده می‌شود."""
        company_id = self._company_id()
        if company_id is None:
            return ""
        item = next((it for it in self._items if it.item_id == item_id), None)
        uom_decimals = 2
        if item is not None:
            uom_row = next((u for u in catalog_service.list_uoms(company_id) if u.uom_id == item.base_uom_id), None)
            if uom_row is not None:
                uom_decimals = uom_row.decimal_places
        rows = engine_service.get_item_stock_by_warehouse(company_id, item_id)
        nonzero = [r for r in rows if r.quantity_on_hand]
        if not nonzero:
            stock_line = "موجودی: صفر"
        else:
            total = sum((r.quantity_on_hand for r in nonzero), decimal.Decimal(0))
            per_warehouse = " | ".join(
                f"{r.warehouse_name}: {numerals.format_money(r.quantity_on_hand, uom_decimals)}" for r in nonzero
            )
            stock_line = f"موجودیِ کل: {numerals.format_money(total, uom_decimals)} ({per_warehouse})"
        lines = [stock_line]
        counterparty_id = self.counterparty_combo.currentData()
        if counterparty_id is not None:
            history = documents_service.list_item_price_history(company_id, item_id, counterparty_id)[:3]
            if history:
                dp = self._decimal_places
                price_parts = [
                    f"{numerals.format_jalali_date(row.document_date)}: {numerals.format_money(row.unit_price, dp)}"
                    for row in history
                ]
                lines.append("آخرین قیمت‌ها: " + " | ".join(price_parts))
        return "\n".join(lines)

    def _open_item_kardex(self, item_id: int) -> None:
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

    def _open_item_price_history(self, item_id: int) -> None:
        company_id = self._company_id()
        counterparty_id = self.counterparty_combo.currentData()
        if company_id is None or counterparty_id is None:
            QMessageBox.information(self, "قیمت‌هایِ قبلی", "برایِ دیدنِ قیمت‌هایِ قبلی، ابتدا طرفِ‌حساب را انتخاب کنید.")
            return
        item = next((it for it in self._items if it.item_id == item_id), None)
        item_label = f"{item.code} — {item.name or ''}" if item else str(item_id)
        dialog = _ItemPriceHistoryDialog(self, company_id, item_id, counterparty_id, item_label)
        dialog.exec()

    def _edit_line_at_row(self, row_index: int) -> None:
        if 0 <= row_index < len(self._lines):
            self._edit_line_object(self._lines[row_index])

    def _delete_line_at_row(self, row_index: int) -> None:
        if 0 <= row_index < len(self._lines):
            self._delete_line_object(self._lines[row_index])

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
        # طبقِ درخواستِ صریح («با تاییدِ مدیر نسبت به نحوه‌یِ تسویه، فاکتور
        # سند بخوره و تسویه بشه»): برایِ فاکتورِ خرید/فروش، ثبتِ نهایی
        # بدونِ نقشه‌یِ تسویه‌یِ تاییدشده مسدود است (سرویس هم دوباره همین
        # را اعتبارسنجی می‌کند -- این‌جا فقط UX است).
        self.settlement_plan_button.setEnabled((is_draft or is_confirmed or is_approved) and self._document_id is not None)
        if self._is_invoice:
            has_plan = self._settlement_plan is not None
            has_approved_plan = has_plan and self._settlement_plan.is_approved
            # طبقِ گزارشِ صریحِ کاربر («روالِ ثبتِ فاکتور خیلی سخت شد...
            # مدیر فقط دیدن و کارِ ثبتِ نهایی انجام دهد»): دیگر لازم
            # نیست نقشه‌یِ تسویه از قبل و جداگانه تاییدشده باشد -- همین‌
            # یک دکمه، اگر نقشه‌ای موجود باشد، هم تاییدِ آن (فقط برایِ
            # مدیر -- همان اعتبارسنجیِ approve_settlement_plan) و هم
            # ثبتِ نهایی را با هم انجام می‌دهد (پیاده‌سازی در _post()).
            self.post_button.setEnabled((is_confirmed or is_approved) and has_plan)
            if self._settlement_plan is None:
                self.settlement_plan_button.setStyleSheet("font-weight: bold; color: #b45309;")
            elif not self._settlement_plan.is_approved:
                self.settlement_plan_button.setStyleSheet("font-weight: bold; color: #b91c1c;")
            else:
                self.settlement_plan_button.setStyleSheet("color: #15803d;")
            # طبقِ گزارشِ صریحِ کاربر («دکمهٔ ثبتِ نهایی غیرفعاله، چرا؟»):
            # هم‌الگو با correct_button -- دلیلِ دقیقِ غیرفعال‌بودن را در
            # Tooltip نشان می‌دهیم، نه فقط خاکستری‌کردنِ بی‌توضیح.
            if not has_plan and (is_confirmed or is_approved):
                self.post_button.setToolTip(
                    "۴) ثبتِ نهایی -- غیرِفعال است، چون: نحوه‌یِ تسویه هنوز مشخص نشده -- "
                    "از دکمهٔ 🧾 «نحوه‌یِ تسویه» آن را مشخص کنید."
                )
            elif has_plan and not has_approved_plan:
                self.post_button.setToolTip(
                    "۴) ثبتِ نهایی -- با این کلیک، هم نحوه‌یِ تسویه تاییدِ مدیر می‌شود (فقط برایِ مدیر ممکن است) "
                    "و هم سند قطعی می‌شود."
                )
            else:
                self.post_button.setToolTip(_POST_BUTTON_DEFAULT_TOOLTIP)
        else:
            # طبقِ گزارشِ صریحِ کاربر («سفارش هم دو مرحله‌ای باشه: تاییدِ
            # کاربر و ثبتِ نهاییِ مدیر؛ همه‌یِ فرم‌ها به همین شکل»): دکمه
            # همچنان بعدِ تاییدِ سند فعال است (تصمیمِ نهایی در _post()
            # گرفته می‌شود -- آن‌جا هم دلیلِ دقیقِ خطا نشان داده می‌شود)،
            # ولی Tooltip از همین‌جا روشن می‌کند که ثبتِ نهایی فقط برایِ
            # مدیر ممکن است.
            self.post_button.setEnabled(is_confirmed or is_approved)
            self.post_button.setToolTip(
                f"{_POST_BUTTON_DEFAULT_TOOLTIP}\n(ثبتِ نهایی فقط برایِ مدیر -- نقشِ ادمین/سوپروایزر/مدیر -- ممکن است.)"
            )
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
        self._settlement_plan = None
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

    def open_as_new(self) -> None:
        """طبقِ رفعِ باگِ واقعیِ گزارش‌شده («سفارشِ خریدِ جدید کالای سفارشِ
        قبلی را نگه می‌دارد»/«بعدِ تایید یا تصویب، صفحه خالی می‌ماند»):
        این صفحه یک نمونه‌یِ تکی و کش‌شده است -- شِلِ اصلی برایِ هر نوعِ
        سند فقط یک‌بار آن را می‌سازد، پس با هربار بازکردن دوباره‌اش از
        منویِ سادهٔ ساید‌بار (که هیچ callbackِ then‌ای -- برخلافِ ویرایشِ
        صریحِ یک سندِ مشخص از فهرستِ اسناد -- به آن نمی‌دهد)، بدونِ این
        ریست صرفاً هرچه آخرین‌بار رویِ صفحه بوده دوباره نشان داده می‌شد:
        چه سندِ قدیمیِ کاملاً نامرتبط (پس ردیفِ ورودی هم کالای همان سندِ
        قدیمی را نگه می‌داشت) و چه هیچ‌ سندی هرگز رویِ آن بار نشده باشد
        (پس کاملاً خالی می‌ماند). shell_window.open_screen این متد را
        خودکار صدا می‌زند وقتی هیچ then ای داده نشده باشد."""
        self._reset_form()

    def prefill_for_new(
        self, counterparty_detail_account_id: int, channel_code: str | None = None, description: str | None = None,
    ) -> None:
        """طبقِ نیازِ صفحه‌یِ فروشِ تلفنی: بازکردنِ فرمِ سندِ تازه با
        مشتری/کانال/توضیحِ از پیش‌انتخاب‌شده -- هم‌الگو با
        prefill_for_invoice در treasury_voucher.py."""
        self._reset_form()
        index = self.counterparty_combo.findData(counterparty_detail_account_id)
        if index >= 0:
            self.counterparty_combo.setCurrentIndex(index)
        if channel_code is not None:
            index = self.channel_combo.findData(channel_code)
            if index >= 0:
                self.channel_combo.setCurrentIndex(index)
        if description:
            self.description_field.setText(description)

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
        fields_list = dialog.result_fields_list()
        company_id = self._company_id()
        if len(fields_list) == 1:
            fields = fields_list[0]
            try:
                documents_service.add_line(self._document_id, company_id, **fields)
            except ValueError as exc:
                QMessageBox.warning(self, "خطا", str(exc))
                return
            self._warn_if_consignment_cost_mixing(fields.get("item_id"), fields.get("warehouse_id") or self.warehouse_combo.currentData())
            self._load_document()
            self._refresh_cross_sell_suggestion(fields.get("item_id"))
            self._refresh_upsell_suggestion(fields.get("item_id"))
            return

        # طبقِ درخواستِ صریح («جلویِ هر متغیر مقدار وارد کنیم»): افزودنِ
        # هم‌زمانِ چند ردیف (یکی به‌ازایِ هر متغیرِ واردشده) -- بهترین‌تلاش:
        # خطایِ یک ردیف بقیه را متوقف نمی‌کند، در پایان جمعِ خطاها نشان
        # داده می‌شود.
        errors = []
        last_item_id = None
        for fields in fields_list:
            try:
                documents_service.add_line(self._document_id, company_id, **fields)
                last_item_id = fields.get("item_id")
                self._warn_if_consignment_cost_mixing(fields.get("item_id"), fields.get("warehouse_id") or self.warehouse_combo.currentData())
            except ValueError as exc:
                item = next((it for it in self._items if it.item_id == fields.get("item_id")), None)
                label = f"{item.code} — {item.name or ''}" if item else str(fields.get("item_id"))
                errors.append(f"{label}: {exc}")
        self._load_document()
        if last_item_id is not None:
            self._refresh_cross_sell_suggestion(last_item_id)
            self._refresh_upsell_suggestion(last_item_id)
        if errors:
            QMessageBox.warning(self, "خطا در برخی ردیف‌ها", "\n".join(errors))

    def _refresh_customer_summary(self) -> None:
        """طبقِ درخواستِ صریح («فاکتورِ فوق‌هوشمند»): خلاصه‌یِ وضعیتِ همان
        مشتریِ رویِ هدر -- آخرین خرید، میانگینِ فاصله‌یِ خرید، سقفِ اعتبار،
        بدهیِ جاری، و امتیاز/ردیفِ مشتری -- درست زیرِ هدرِ سند. طبقِ
        درخواستِ صریحِ بعدی، خودِ فیلدِ انتخابِ مشتری هم رنگ‌آمیزی می‌شود:
        گرادیانِ افقی از رنگِ (قرمز تا سبز، متناسب با امتیاز) در سمتِ چپ
        تا سفید در سمتِ راست -- تا نامِ مشتری همیشه خوانا بماند.

        طبقِ گزارشِ صریحِ بعدی («بدهی از سقفِ اعتبار عبور کرده، آیا نباید
        تاثیری داشته باشه؟»): طبقِ تصمیمِ طراحی، این عمداً امتیازِ کلی را
        عوض نمی‌کند (چون امتیاز معیارِ ارزشِ رابطه است، نه ریسکِ لحظه‌ای)
        ولی یک نشانه‌یِ جداگانه و فوری می‌گیرد -- به‌جایِ چشمک‌زدن (که برایِ
        نرم‌افزارِ حرفه‌ای معمولاً توصیه نمی‌شود)، یک قابِ قرمزِ ثابت دورِ
        فیلد و یک خطِ هشدار در پنل، تا هم دیده شود و هم اذیت‌کننده نباشد."""
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
        border_rule = "border: 2px solid #dc2626;" if score_row.over_credit_limit else ""
        self.counterparty_combo.setStyleSheet(
            "QComboBox { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 {gradient_color}, stop:1 white); color: #1a1a1a; {border_rule} }}"
        )

        parts = [f"{score_row.emoji} امتیازِ مشتری: {numerals.to_persian_digits(str(score_row.score))} ({score_row.tier_label})"]
        if score_row.days_since_last is not None:
            parts.append(f"آخرین خرید: {numerals.to_persian_digits(str(score_row.days_since_last))} روز پیش")
        if score_row.avg_interval_days is not None:
            parts.append(f"میانگینِ خرید: هر {numerals.to_persian_digits(str(round(score_row.avg_interval_days)))} روز")

        if score_row.credit_limit_amount:
            parts.append(f"سقفِ اعتبار: {numerals.format_company_amount(score_row.credit_limit_amount)}")
            parts.append(f"بدهیِ جاری: {numerals.format_company_amount(score_row.current_exposure)}")
            if score_row.over_credit_limit:
                parts.append("🚨 بدهی از سقفِ اعتبار عبور کرده")

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

    def _clear_upsell_box(self) -> None:
        self._upsell_suggestions = []
        while self._upsell_layout.count():
            item = self._upsell_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
        self.upsell_box.setVisible(False)

    def _refresh_upsell_suggestion(self, item_id: int | None) -> None:
        """طبقِ درخواستِ صریح («فروشِ ارتقایی»): اگر کالایِ همین ردیف در
        فرمِ کالا یک یا چند «جایگزین» (RelatedItem با نوعِ SUBSTITUTE)
        دارد که قیمتِ فروشِ حل‌شده‌اش (طبقِ همان فهرستِ قیمت/طرفِ‌حسابِ
        همین سند) از قیمتِ همین ردیف بالاتر باشد، پیشنهادِ ارتقا نشان
        داده می‌شود -- یک جایگزینِ بدونِ قیمتِ قابلِ‌حل در همین بافت
        بی‌صدا نادیده گرفته می‌شود (چون سوگیریِ آن قابلِ‌فروش نیست)."""
        self._clear_upsell_box()
        company_id = self._company_id()
        counterparty_id = self.counterparty_combo.currentData()
        if not self._supports_cross_sell or item_id is None or company_id is None or counterparty_id is None:
            return
        original_line = next((ln for ln in self._lines if ln.item_id == item_id), None)
        if original_line is None:
            return
        substitute_ids = [
            related_item_id for related_item_id, relation_type_code in catalog_service.list_related_items(item_id)
            if relation_type_code == "SUBSTITUTE"
        ]
        if not substitute_ids:
            return
        suggestions = []
        for related_item_id in substitute_ids:
            substitute_item = next((it for it in self._items if it.item_id == related_item_id), None)
            if substitute_item is None:
                continue
            try:
                resolved = pricing_service.resolve_price(
                    company_id, counterparty_id, related_item_id, substitute_item.base_uom_id, decimal.Decimal(1),
                    self.price_list_combo.currentData(), self.document_type_code, self.date_field.date(),
                )
            except ValueError:
                continue
            if resolved.unit_price <= original_line.unit_price:
                continue
            suggestions.append((original_line, substitute_item, resolved.unit_price))
        if not suggestions:
            return
        for original, substitute_item, upgraded_price in suggestions:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            label = QLabel(
                f"⬆️ نسخهٔ بالاترِ این کالا هم موجود است: «{substitute_item.code} — {substitute_item.name}» "
                f"به‌قیمتِ {numerals.format_money(upgraded_price, self._decimal_places)}"
            )
            label.setWordWrap(True)
            row_layout.addWidget(label, stretch=1)
            upgrade_button = QPushButton("🔁 جایگزینی")
            upgrade_button.setObjectName("flatButton")
            upgrade_button.clicked.connect(
                lambda _checked=False, o=original, it=substitute_item: self._add_upsell_suggestion(o, it)
            )
            row_layout.addWidget(upgrade_button)
            self._upsell_layout.addWidget(row_widget)
        self._upsell_suggestions = suggestions
        self.upsell_box.setVisible(True)
        QTimer.singleShot(0, lambda: self._scroll.ensureWidgetVisible(self.upsell_box))

    def _add_upsell_suggestion(self, original_line, substitute_item) -> None:
        company_id = self._company_id()
        if self._document_id is None or company_id is None:
            return
        try:
            documents_service.add_line(
                self._document_id, company_id, item_id=substitute_item.item_id, uom_id=substitute_item.base_uom_id,
                quantity=original_line.quantity, quantity_base=original_line.quantity_base,
                warehouse_id=self.warehouse_combo.currentData() if self.warehouse_combo is not None else None,
            )
            documents_service.delete_line(original_line.line_id, self._document_id, company_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._load_document()
        self._clear_upsell_box()

    def _selected_line(self):
        selected = self.lines_table.selectedItems()
        if not selected:
            return None
        line_id = selected[0].data(Qt.UserRole)
        return next((ln for ln in self._lines if ln.line_id == line_id), None)

    def _edit_line(self, *_args) -> None:
        line = self._selected_line()
        if line is None:
            return
        self._edit_line_object(line)

    def _edit_line_object(self, line) -> None:
        if self._document_id is None:
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
        if line is None:
            return
        self._delete_line_object(line)

    def _delete_line_object(self, line) -> None:
        if self._document_id is None:
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

    def _confirm(self) -> bool:
        """طبقِ عمد: این تابع فقط خودِ تاییدِ سند را انجام می‌دهد (بدونِ
        هیچ دیالوگِ اضافه) -- چون تست‌هایِ زیادی (نامرتبط با نحوه‌یِ
        تسویه) این متد را مستقیماً برایِ رساندنِ سند به وضعیتِ CONFIRMED
        صدا می‌زنند و نباید با یک QMessageBox/دیالوگِ مسدودکننده‌یِ
        غیرمنتظره روبه‌رو شوند. پرسیدنِ نحوه‌یِ تسویه (طبقِ گزارشِ صریحِ
        کاربر) فقط در _confirm_button_clicked -- که مستقیماً به کلیکِ
        واقعیِ دکمهٔ ✅ وصل است -- انجام می‌شود."""
        if self._document_id is None:
            return False
        if not self._flush_header_changes():
            return False
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
            return False
        self._load_document()
        theme.set_status_label(self.status_label, "سند تایید شد.", ok=True)
        return True

    def _confirm_button_clicked(self) -> None:
        # طبقِ گزارشِ صریحِ کاربر («کاربر فاکتور را صادر می‌کند و نحوه‌یِ
        # دریافت هم در ابتدا مشخص می‌شود»): به‌جایِ اینکه کاربر بعداً
        # جداگانه دنبالِ دکمهٔ 🧾 بگردد، همین‌جا -- بلافاصله بعدِ تاییدِ
        # فاکتور -- پرسیده می‌شود.
        if self._confirm() and self._is_invoice:
            self._prompt_settlement_after_confirm()

    def _prompt_settlement_after_confirm(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._document_id is None:
            return
        has_receipt = QMessageBox.question(
            self, "نحوه‌یِ تسویه",
            "آیا همین الان دریافت/پرداختی (نقد یا بانکی) برایِ این فاکتور انجام شده؟\n"
            "«خیر» یعنی این فاکتور به‌طورِ کامل نسیه است.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if has_receipt == QMessageBox.Yes:
            self._open_settlement_plan()
            return
        try:
            settlements_service.save_settlement_plan(self._document_id, company_id, app_session.current_user.user_id, [])
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._load_document()
        theme.set_status_label(
            self.status_label, "فاکتور به‌عنوانِ نسیه ثبت شد؛ در انتظارِ ثبتِ نهاییِ مدیر است.", ok=True,
        )

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
        company_id = self._company_id()
        # طبقِ گزارشِ صریحِ کاربر («سفارش هم دو مرحله‌ای باشه، تاییدِ
        # کاربر و ثبتِ نهاییِ مدیر؛ همه‌یِ فرم‌هایِ خرید و فروش به همین
        # شکل باشه»): این چک برایِ *همه‌یِ* انواعِ سندی که همین یک فرمِ
        # مشترک (این کلاس) نمایش می‌دهد اعمال می‌شود -- سفارش/پیش‌فاکتور/
        # امانی، نه فقط فاکتور. (فروشِ صندوق/POS و ثبتِ سفارشِ موبایلِ
        # ون‌سیلز از این فرم عبور نمی‌کنند -- گذرگاهِ کاملاً جداگانه‌یِ
        # خودشان را دارند و عمداً دست‌نخورده می‌مانند.)
        user = app_session.current_user
        if company_id is not None and user is not None and not roles_service.is_manager(user.user_id, company_id):
            QMessageBox.warning(
                self, "ثبتِ نهایی",
                "ثبتِ نهایی فقط برایِ مدیر (نقشِ ادمین/سوپروایزر/مدیر) ممکن است -- این سند تاییدشده و آماده‌یِ ثبتِ نهایی است.",
            )
            return
        # طبقِ گزارشِ صریحِ کاربر («مدیر فقط دیدن و کارِ ثبتِ نهایی انجام
        # دهد»): برایِ فاکتورِ خرید/فروش، اگر نقشه‌یِ تسویه هنوز توسطِ
        # مدیر تاییدنشده، همین‌جا -- پیش از خودِ Post -- تاییدمی‌شود؛
        # approve_settlement_plan خودش نقشِ ادمین/سوپروایزر/مدیر را
        # اعتبارسنجی می‌کند، پس کاربرِ غیرِمدیر همین‌جا با خطایِ روشن
        # متوقف می‌شود. از پایگاه‌داده تازه خوانده می‌شود (نه کَشِ
        # self._settlement_plan) تا رفتارِ posted_settlement_plan پایین‌تر
        # هم‌الگو بماند.
        fresh_plan = (
            settlements_service.get_settlement_plan(self._document_id, company_id)
            if self._is_invoice and self._corrects_document_id is None and company_id is not None else None
        )
        needs_settlement_approval = fresh_plan is not None and not fresh_plan.is_approved
        question_text = "این سند ثبتِ نهایی شود؟ پسِ این کار، سند دیگر قابلِ‌ویرایش/حذف نیست."
        if needs_settlement_approval:
            question_text = (
                "این سند ثبتِ نهایی شود؟ (این کار هم نحوه‌یِ تسویه را تایید می‌کند و هم سند را قطعی می‌کند.)\n"
                "پسِ این کار، سند دیگر قابلِ‌ویرایش/حذف نیست."
            )
        confirm = QMessageBox.question(self, "ثبتِ نهایی", question_text, QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        if needs_settlement_approval:
            try:
                settlements_service.approve_settlement_plan(self._document_id, company_id, app_session.current_user.user_id)
            except ValueError as exc:
                QMessageBox.warning(self, "خطا در تاییدِ نحوه‌یِ تسویه", str(exc))
                return
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
        posted_document_id = self._document_id
        posted_counterparty_id = posted_doc.counterparty_detail_account_id
        posted_total = posted_doc.total_amount
        posted_no = posted_doc.document_no
        # طبقِ درخواستِ صریح («با تاییدِ مدیر نسبت به نحوه‌یِ تسویه، فاکتور
        # سند بخوره و تسویه بشه»): مسیرِ اصلاحِ فاکتور (که هیچ‌وقت نقشه‌یِ
        # تسویه نمی‌سازد) از این‌جا مستثنا می‌ماند -- طبقِ رفتارِ قبلی.
        # طبقِ رفعِ باگِ واقعی: self._settlement_plan فقط با _load_document
        # تازه می‌شود -- اگر نقشه بینِ آخرین رفرش و همین کلیکِ «ثبتِ
        # نهایی» ذخیره/تاییدشده باشد (بدونِ رفرشِ دوباره‌یِ فرم)، آن
        # کَشِ قدیمی هنوز None یا تاییدنشده می‌ماند. این‌جا -- درست مثلِ
        # posted_doc چند خط پایین‌تر -- دوباره از پایگاه‌داده خوانده می‌شود.
        posted_settlement_plan = (
            settlements_service.get_settlement_plan(self._document_id, company_id)
            if self._corrects_document_id is None else None
        )
        self._reset_form()
        theme.set_status_label(self.status_label, f"سند ثبتِ نهایی شد.{je_note}", ok=True)

        if posted_type in ("SALES_INVOICE", "PURCHASE_INVOICE") and self._main_window is not None:
            is_sales = posted_type == "SALES_INVOICE"
            nav_code = "TREASURY_RECEIPT" if is_sales else "TREASURY_PAYMENT"
            description = f"بابتِ {DOC_TYPE_TITLES[posted_type]}ِ #{numerals.to_persian_digits(str(posted_no))}"
            if posted_settlement_plan is not None and posted_settlement_plan.lines_total > 0:
                # نقشه‌یِ تسویه‌یِ ازپیش‌تاییدشده مستقیماً در فرمِ دریافت/
                # پرداخت پر می‌شود (دیگر پرسیدنِ «آیا ثبت شود؟» لازم
                # نیست -- خودِ ثبتِ نهایی مستلزمِ داشتنِ همین نقشه بود) و
                # با ذخیرهٔ همان فرم، خودکار به همین فاکتور هم تسویه/وصل
                # می‌شود (settle_invoices).
                method_lines = [(ln.method_code, ln.amount, ln.note) for ln in posted_settlement_plan.lines]
                self._main_window.open_screen(
                    nav_code,
                    then=lambda screen: screen.prefill_for_invoice(
                        posted_counterparty_id, posted_settlement_plan.lines_total, description,
                        settle_invoices=[(posted_document_id, posted_settlement_plan.lines_total)],
                        method_lines=method_lines,
                    ),
                )
            elif posted_settlement_plan is None:
                noun = "دریافتِ وجه" if is_sales else "پرداختِ وجه"
                confirm_payment = QMessageBox.question(
                    self, noun,
                    f"آیا برایِ این فاکتور {noun} ثبت می‌شود؟\n(اگر نسیه است و هنوز پرداختی صورت نگرفته، «خیر» را انتخاب کنید.)",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if confirm_payment == QMessageBox.Yes:
                    self._main_window.open_screen(
                        nav_code,
                        then=lambda screen: screen.prefill_for_invoice(posted_counterparty_id, posted_total, description),
                    )
            # وگرنه (نقشه تاییدشده ولی lines_total == ۰): کاملاً نسیه است -- هیچ فرمِ دریافت/پرداختی باز نمی‌شود.

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

    def _open_settlement_plan(self) -> None:
        if self._document_id is None:
            return
        company_id = self._company_id()
        if company_id is None:
            return
        doc, _lines = documents_service.get_document(self._document_id, company_id)
        dialog = _SettlementPlanDialog(
            self._document_id, company_id, self.document_type_code, doc.total_amount, self._decimal_places, self,
        )
        dialog.exec()
        self._load_document()

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
