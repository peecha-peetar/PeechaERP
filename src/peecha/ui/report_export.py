"""زیرساختِ مشترکِ خروجیِ گزارش‌ها — چاپ/PDF با QtPrintSupport (بدونِ
وابستگیِ بیرونی) و Excel با openpyxl. هر صفحه‌یِ گزارش (reports_common.py و
زیرکلاس‌هایش) همین سه تابع را با دیتایِ جدولِ فعلی‌اش صدا می‌زند.

طبقِ گزارشِ صریحِ کاربر، دو مشکلِ واقعی در خروجیِ چاپ/PDF پیدا و رفع شد:

۱. ترتیبِ ستون‌ها برعکس بود. آزمایشِ مستقیم نشان داد QTextDocument با
   `dir="rtl"` رویِ `<html>`، ستونِ *اول*ِ نوشته‌شده در HTML را چپ‌ترین و
   ستونِ *آخر* را راست‌ترین رسم می‌کند — یعنی دقیقاً برعکسِ قراردادِ
   استانداردِ صفحه‌گسترده‌هایِ راست‌به‌چپ (که ستونِ اول باید راست‌ترین
   باشد، مثلِ اکسلِ راست‌به‌چپ یا خودِ QTableWidgetِ برنامه که با
   app.setLayoutDirection(Qt.RightToLeft) این‌طور نمایش می‌دهد). راه‌حل:
   ترتیبِ سلول‌ها را در خودِ HTML معکوس می‌نویسیم (نه با تکیه بر
   dir="rtl" برایِ بازچینشِ جدول) — همین باعث می‌شود ستونِ اولِ منطقی
   واقعاً راست‌ترین دیده شود.
   (توجه: خروجیِ Excel این باگ را ندارد چون sheet_view.rightToLeft خودش
   به‌درستی این بازچینش را انجام می‌دهد — آزمایش/تغییری در آن لازم نبود.)

۲. هدرِ چاپ فقط عنوانِ گزارش را داشت، بدونِ نامِ شرکتِ فعال/تاریخِ گزارش/
   فیلترهایِ اعمال‌شده — که برایِ یک سندِ چاپیِ رسمی (که ممکن است از
   کنارِ کامپیوتر جدا شود) ناقص است. حالا سه سطرِ هدر دارد: نامِ شرکت
   (بالا)، عنوانِ گزارش (وسط)، و یک سطرِ تاریخِ گزارش (شمسی) + فیلترهایِ
   اعمال‌شده به همان ترتیبی که در فرمِ فیلتر ظاهر می‌شوند (پایین)."""

from __future__ import annotations

from PySide6.QtGui import QPageLayout, QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget


def _escape(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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
    # طبقِ آزمایشِ مستقیم: برایِ اینکه ستونِ اولِ منطقی راست‌ترین دیده
    # شود، باید سلول‌ها را در HTML به ترتیبِ معکوس بنویسیم — نه با
    # تکیه بر dir="rtl" (که خودش جدول را عکسِ موردِ انتظار می‌چیند).
    reversed_headers = list(reversed(headers))
    head_cells = "".join(f"<th>{_escape(h)}</th>" for h in reversed_headers)
    body_rows = "".join(
        "<tr>" + "".join(f"<td>{_escape(c)}</td>" for c in reversed(row)) + "</tr>" for row in rows
    )
    footer_html = ""
    if footer:
        footer_cells = "".join(f"<td><b>{_escape(c)}</b></td>" for c in reversed(footer))
        footer_html = f"<tr>{footer_cells}</tr>"

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
    printer.setPageOrientation(QPageLayout.Orientation.Landscape)
    doc = _build_document(
        title, headers, rows, footer, company_name=company_name, report_date=report_date, filters=filters
    )
    preview = QPrintPreviewDialog(printer, parent_widget)
    preview.paintRequested.connect(doc.print_)
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
    printer.setPageOrientation(QPageLayout.Orientation.Landscape)
    printer.setOutputFileName(path)
    doc = _build_document(
        title, headers, rows, footer, company_name=company_name, report_date=report_date, filters=filters
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
        QMessageBox.warning(parent_widget, "خطا", "کتابخانه‌یِ openpyxl نصب نیست.")
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
