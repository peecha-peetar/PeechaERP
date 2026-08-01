"""زیرساختِ مشترکِ خروجیِ گزارش‌ها — چاپ/PDF با QtPrintSupport (بدونِ
وابستگیِ بیرونی) و Excel با openpyxl. هر صفحه‌یِ گزارش (reports_common.py و
زیرکلاس‌هایش) همین سه تابع را با دیتایِ جدولِ فعلی‌اش صدا می‌زند.

طبقِ گزارشِ صریحِ کاربر، چند مشکلِ واقعی در خروجیِ چاپ/PDF پیدا و رفع شد:

۱. ترتیبِ ستون‌ها برعکس بود. آزمایشِ مستقیم نشان داد QTextDocument با
   `dir="rtl"` رویِ `<html>`، ستونِ *اول*ِ نوشته‌شده در HTML را چپ‌ترین و
   ستونِ *آخر* را راست‌ترین رسم می‌کند — یعنی دقیقاً برعکسِ قراردادِ
   استانداردِ صفحه‌گسترده‌هایِ راست‌به‌چپ. راه‌حل: ترتیبِ سلول‌ها را در
   خودِ HTML معکوس می‌نویسیم.

۲. هدرِ چاپ فقط عنوانِ گزارش را داشت. حالا سه سطرِ هدر دارد: نامِ شرکت،
   عنوانِ گزارش، و تاریخِ گزارش + فیلترهایِ اعمال‌شده.

۳. حاشیه‌یِ چاپ زیاد بود و فضایِ کناریِ خالی داشت — حاشیه‌هایِ صفحه به
   صراحت به مقدارِ کمی (۸ میلی‌متر) تنظیم می‌شوند (پیش‌فرضِ سیستم‌عامل/
   چاپگر می‌توانست تا ۲۰ میلی‌متر باشد که رویِ صفحه‌یِ landscape خیلی
   محسوس بود).

۴. گزارش‌هایِ چندصفحه‌ای «جمعِ هر صفحه» نداشتند — جمعِ کل فقط در آخرین
   صفحه (زیرِ آخرین ردیف) دیده می‌شد. حالا اگر گزارش در یک صفحه جا
   نشود، ردیف‌ها بینِ صفحات تقسیم می‌شوند (با محاسبه‌یِ تقریبیِ تعدادِ
   ردیفِ هر صفحه از رویِ pageCount شمسِ کاملِ سند) و زیرِ هر صفحه (به‌جز
   آخرین) یک ردیفِ «جمعِ این صفحه» برایِ ستون‌هایِ مبلغی (بدهکار/
   بستانکار/مانده/مبلغ — تشخیص از رویِ عنوانِ ستون) اضافه می‌شود.
   محدودیتِ صادقانه: تعدادِ ردیفِ هر صفحه از رویِ میانگینِ
   pageCount/تعدادِ ردیف تخمین زده می‌شود (نه شبیه‌سازیِ دقیقِ چیدمانِ
   داخلیِ Qt) — برایِ جدول‌هایِ با ارتفاعِ ردیفِ یکنواخت (حالتِ معمولِ
   همه‌یِ گزارش‌هایِ این برنامه) این تخمین عملاً دقیق است."""

from __future__ import annotations

import decimal
import math

from PySide6.QtCore import QMarginsF, QSizeF
from PySide6.QtGui import QPageLayout, QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from peecha import numerals

_PAGE_MARGIN_MM = 8.0
# طبقِ عنوانِ ستون تشخیص داده می‌شود که «جمعِ صفحه» برایش معنا دارد —
# نه فقط قابلِ‌پارس‌بودنِ عدد، وگرنه ستون‌هایی مثلِ «شماره‌یِ سند» هم
# اشتباهی جمع می‌شدند.
_AMOUNT_HEADER_KEYWORDS = ("بدهکار", "بستانکار", "بد)", "بس)", "مانده", "مبلغ")


def _escape(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _amount_column_indices(headers: list[str], rows: list[list]) -> list[int]:
    indices = []
    for i, header in enumerate(headers):
        if not any(kw in header for kw in _AMOUNT_HEADER_KEYWORDS):
            continue
        parseable = True
        for row in rows:
            cell = str(row[i]).strip() if i < len(row) else ""
            if not cell:
                continue
            try:
                numerals.parse_decimal(cell)
            except ValueError:
                parseable = False
                break
        if parseable:
            indices.append(i)
    return indices


def _sum_amount_cells(rows: list[list], col_index: int) -> decimal.Decimal:
    total = decimal.Decimal(0)
    for row in rows:
        cell = str(row[col_index]).strip() if col_index < len(row) else ""
        if cell:
            total += numerals.parse_decimal(cell)
    return total


def _header_block_html(title: str, company_name: str, report_date: str, filters: list[tuple[str, str]] | None) -> str:
    header_lines = ""
    if company_name:
        header_lines += f'<div style="font-size:12pt; font-weight:bold;">{_escape(company_name)}</div>'
    header_lines += f'<h3 style="margin:4px 0;">{_escape(title)}</h3>'
    meta_parts = []
    if report_date:
        meta_parts.append(f"تاریخِ گزارش: {_escape(report_date)}")
    for label, value in filters or []:
        meta_parts.append(f"{_escape(label)}: {_escape(value)}")
    if meta_parts:
        header_lines += (
            '<div style="font-size:9pt; color:#444;">' + " &nbsp;|&nbsp; ".join(meta_parts) + "</div>"
        )
    return header_lines


def _build_html(
    title: str,
    headers: list[str],
    rows: list[list],
    footer: list | None,
    *,
    company_name: str = "",
    report_date: str = "",
    filters: list[tuple[str, str]] | None = None,
) -> str:
    reversed_headers = list(reversed(headers))
    head_cells = "".join(f"<th>{_escape(h)}</th>" for h in reversed_headers)
    body_rows = "".join(
        "<tr>" + "".join(f"<td>{_escape(c)}</td>" for c in reversed(row)) + "</tr>" for row in rows
    )
    footer_html = ""
    if footer:
        footer_cells = "".join(f"<td><b>{_escape(c)}</b></td>" for c in reversed(footer))
        footer_html = f"<tr>{footer_cells}</tr>"

    header_lines = _header_block_html(title, company_name, report_date, filters)

    return f"""
    <html dir="rtl"><head><meta charset="utf-8"></head>
    <body style="font-family: sans-serif; font-size: 10pt;">
    <div style="text-align:center; margin-bottom:8px;">{header_lines}</div>
    <table border="1" cellspacing="0" cellpadding="4" width="100%" style="border-collapse: collapse;">
    <thead><tr>{head_cells}</tr></thead>
    <tbody>{body_rows}{footer_html}</tbody>
    </table>
    </body></html>
    """


def _build_paginated_html(
    title: str,
    headers: list[str],
    rows: list[list],
    footer: list | None,
    rows_per_page: int,
    *,
    company_name: str = "",
    report_date: str = "",
    filters: list[tuple[str, str]] | None = None,
) -> str:
    """طبقِ گزارشِ صریح («جمعِ هر صفحه نداره»): وقتی گزارش در یک صفحه
    جا نمی‌شود، ردیف‌ها را خودمان بینِ صفحات (با CSS
    page-break-after) تقسیم می‌کنیم — نه به شکستنِ خودکارِ Qt تکیه
    می‌کنیم — تا زیرِ هر صفحه (به‌جز آخرین) بشود یک ردیفِ «جمعِ این
    صفحه» برایِ ستون‌هایِ مبلغی اضافه کرد."""
    reversed_headers = list(reversed(headers))
    head_cells = "".join(f"<th>{_escape(h)}</th>" for h in reversed_headers)
    header_lines = _header_block_html(title, company_name, report_date, filters)
    amount_col_indices = _amount_column_indices(headers, rows)

    rows_per_page = max(1, rows_per_page)
    chunks = [rows[i : i + rows_per_page] for i in range(0, len(rows), rows_per_page)] or [[]]

    page_blocks = []
    for chunk_index, chunk_rows in enumerate(chunks):
        is_last = chunk_index == len(chunks) - 1
        body_rows = "".join(
            "<tr>" + "".join(f"<td>{_escape(c)}</td>" for c in reversed(row)) + "</tr>" for row in chunk_rows
        )
        extra_row = ""
        if is_last and footer:
            footer_cells = "".join(f"<td><b>{_escape(c)}</b></td>" for c in reversed(footer))
            extra_row = f"<tr>{footer_cells}</tr>"
        elif amount_col_indices:
            page_totals: list[str] = ["" for _ in headers]
            page_totals[0] = "جمعِ این صفحه"
            for col in amount_col_indices:
                page_totals[col] = numerals.format_amount(_sum_amount_cells(chunk_rows, col))
            footer_cells = "".join(f"<td><b>{_escape(c)}</b></td>" for c in reversed(page_totals))
            extra_row = f"<tr>{footer_cells}</tr>"

        page_header_html = header_lines if chunk_index == 0 else f'<h4 style="margin:4px 0;">ادامه — {_escape(title)}</h4>'
        page_break = "" if is_last else '<div style="page-break-after: always;"></div>'
        page_blocks.append(
            f"""
            <div style="text-align:center; margin-bottom:8px;">{page_header_html}</div>
            <table border="1" cellspacing="0" cellpadding="4" width="100%" style="border-collapse: collapse;">
            <thead><tr>{head_cells}</tr></thead>
            <tbody>{body_rows}{extra_row}</tbody>
            </table>
            {page_break}
            """
        )

    return f"""
    <html dir="rtl"><head><meta charset="utf-8"></head>
    <body style="font-family: sans-serif; font-size: 10pt;">
    {"".join(page_blocks)}
    </body></html>
    """


def _build_document(
    title: str,
    headers: list[str],
    rows: list[list],
    footer: list | None,
    *,
    company_name: str = "",
    report_date: str = "",
    filters: list[tuple[str, str]] | None = None,
) -> QTextDocument:
    doc = QTextDocument()
    doc.setHtml(
        _build_html(
            title, headers, rows, footer, company_name=company_name, report_date=report_date, filters=filters
        )
    )
    return doc


def _apply_page_setup(printer: QPrinter) -> None:
    printer.setPageOrientation(QPageLayout.Orientation.Landscape)
    printer.setPageMargins(QMarginsF(_PAGE_MARGIN_MM, _PAGE_MARGIN_MM, _PAGE_MARGIN_MM, _PAGE_MARGIN_MM), QPageLayout.Unit.Millimeter)


def _build_final_document(
    printer: QPrinter,
    title: str,
    headers: list[str],
    rows: list[list],
    footer: list | None,
    *,
    company_name: str,
    report_date: str,
    filters: list[tuple[str, str]] | None,
) -> QTextDocument:
    """سندِ نهایی برایِ چاپ/PDF — اگر همه‌چیز در یک صفحه جا شود، همان
    ساختِ سابق؛ وگرنه نسخه‌یِ صفحه‌بندی‌شده با جمعِ هر صفحه."""
    doc = _build_document(title, headers, rows, footer, company_name=company_name, report_date=report_date, filters=filters)
    page_rect = printer.pageRect(QPrinter.Unit.Point)
    doc.setPageSize(QSizeF(page_rect.width(), page_rect.height()))
    page_count = doc.pageCount()
    if page_count <= 1 or len(rows) < 2:
        return doc

    rows_per_page = max(1, math.ceil(len(rows) / page_count))
    paginated_doc = QTextDocument()
    paginated_doc.setHtml(
        _build_paginated_html(
            title, headers, rows, footer, rows_per_page,
            company_name=company_name, report_date=report_date, filters=filters,
        )
    )
    paginated_doc.setPageSize(QSizeF(page_rect.width(), page_rect.height()))
    return paginated_doc


def print_report(
    parent_widget: QWidget,
    title: str,
    headers: list[str],
    rows: list[list],
    footer: list | None = None,
    *,
    company_name: str = "",
    report_date: str = "",
    filters: list[tuple[str, str]] | None = None,
) -> None:
    if not rows:
        QMessageBox.information(parent_widget, "چاپ", "گزارشی برایِ چاپ وجود ندارد.")
        return
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    _apply_page_setup(printer)
    doc = _build_final_document(
        printer, title, headers, rows, footer, company_name=company_name, report_date=report_date, filters=filters
    )
    preview = QPrintPreviewDialog(printer, parent_widget)
    preview.paintRequested.connect(doc.print_)
    # طبقِ درخواستِ صریح: فرمِ پیش‌نمایشِ چاپ به‌طورِ پیش‌فرض تمامِ صفحه باز شود.
    preview.showMaximized()
    preview.exec()


def export_report_pdf(
    parent_widget: QWidget,
    title: str,
    headers: list[str],
    rows: list[list],
    footer: list | None = None,
    *,
    company_name: str = "",
    report_date: str = "",
    filters: list[tuple[str, str]] | None = None,
) -> None:
    if not rows:
        QMessageBox.information(parent_widget, "PDF", "گزارشی برایِ خروجیِ PDF وجود ندارد.")
        return
    path, _filter = QFileDialog.getSaveFileName(parent_widget, "ذخیره‌یِ PDF", f"{title}.pdf", "PDF (*.pdf)")
    if not path:
        return
    if not path.lower().endswith(".pdf"):
        path += ".pdf"
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    _apply_page_setup(printer)
    printer.setOutputFileName(path)
    doc = _build_final_document(
        printer, title, headers, rows, footer, company_name=company_name, report_date=report_date, filters=filters
    )
    doc.print_(printer)
    QMessageBox.information(parent_widget, "خروجیِ PDF", "فایلِ PDF با موفقیت ساخته شد.")


def export_report_excel(
    parent_widget: QWidget,
    title: str,
    headers: list[str],
    rows: list[list],
    footer: list | None = None,
    *,
    company_name: str = "",
    report_date: str = "",
    filters: list[tuple[str, str]] | None = None,
) -> None:
    if not rows:
        QMessageBox.information(parent_widget, "Excel", "گزارشی برایِ خروجیِ Excel وجود ندارد.")
        return
    try:
        import openpyxl
        from openpyxl.styles import Font
    except ImportError:
        QMessageBox.warning(parent_widget, "خطا", "امکانِ ساختِ فایلِ Excel روی این سیستم فراهم نیست.")
        return

    path, _filter = QFileDialog.getSaveFileName(parent_widget, "ذخیره‌یِ Excel", f"{title}.xlsx", "Excel (*.xlsx)")
    if not path:
        return
    if not path.lower().endswith(".xlsx"):
        path += ".xlsx"

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = (title[:31] or "گزارش").replace("/", "-")
    sheet.sheet_view.rightToLeft = True

    # طبقِ همان درخواستِ سربرگِ چاپ: نامِ شرکت + عنوان + تاریخ/فیلترها به‌عنوانِ
    # چند سطرِ اول، پیش از جدولِ خودِ گزارش. توجه: بازچینیِ ستون این‌جا لازم
    # نیست چون sheet_view.rightToLeft خودش راست‌ترین=ستونِ اول را درست می‌چیند.
    header_row_count = 0
    if company_name:
        sheet.append([company_name])
        sheet.cell(row=sheet.max_row, column=1).font = Font(bold=True, size=13)
        header_row_count += 1
    sheet.append([title])
    sheet.cell(row=sheet.max_row, column=1).font = Font(bold=True, size=12)
    header_row_count += 1
    meta_parts = []
    if report_date:
        meta_parts.append(f"تاریخِ گزارش: {report_date}")
    for label, value in filters or []:
        meta_parts.append(f"{label}: {value}")
    if meta_parts:
        sheet.append([" | ".join(meta_parts)])
        header_row_count += 1
    sheet.append([])
    header_row_count += 1

    header_row = sheet.max_row + 1
    sheet.append(headers)
    for cell in sheet[header_row]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append(list(row))
    if footer:
        sheet.append(list(footer))
        for cell in sheet[sheet.max_row]:
            cell.font = Font(bold=True)
    sheet.freeze_panes = f"A{header_row + 1}"
    for col_cells in sheet.columns:
        length = max((len(str(c.value)) for c in col_cells if c.value is not None), default=10)
        sheet.column_dimensions[col_cells[0].column_letter].width = min(max(length + 2, 10), 40)

    workbook.save(path)
    QMessageBox.information(parent_widget, "خروجیِ Excel", "فایلِ Excel با موفقیت ساخته شد.")
