"""زیرساختِ مشترکِ خروجیِ گزارش‌ها — چاپ/PDF با QtPrintSupport (بدونِ
وابستگیِ بیرونی) و Excel با openpyxl. هر صفحه‌یِ گزارش (reports_common.py و
زیرکلاس‌هایش) همین سه تابع را با دیتایِ جدولِ فعلی‌اش صدا می‌زند."""

from __future__ import annotations

from PySide6.QtGui import QPageLayout, QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget


def _escape(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _build_html(title: str, headers: list[str], rows: list[list], footer: list | None) -> str:
    head_cells = "".join(f"<th>{_escape(h)}</th>" for h in headers)
    body_rows = "".join("<tr>" + "".join(f"<td>{_escape(c)}</td>" for c in row) + "</tr>" for row in rows)
    footer_html = ""
    if footer:
        footer_cells = "".join(f"<td><b>{_escape(c)}</b></td>" for c in footer)
        footer_html = f"<tr>{footer_cells}</tr>"
    return f"""
    <html dir="rtl"><head><meta charset="utf-8"></head>
    <body style="font-family: sans-serif; font-size: 10pt;">
    <h3 style="text-align:center;">{_escape(title)}</h3>
    <table border="1" cellspacing="0" cellpadding="4" width="100%" style="border-collapse: collapse;">
    <thead><tr>{head_cells}</tr></thead>
    <tbody>{body_rows}{footer_html}</tbody>
    </table>
    </body></html>
    """


def _build_document(title: str, headers: list[str], rows: list[list], footer: list | None) -> QTextDocument:
    doc = QTextDocument()
    doc.setHtml(_build_html(title, headers, rows, footer))
    return doc


def print_report(
    parent_widget: QWidget, title: str, headers: list[str], rows: list[list], footer: list | None = None
) -> None:
    if not rows:
        QMessageBox.information(parent_widget, "چاپ", "گزارشی برایِ چاپ وجود ندارد.")
        return
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageOrientation(QPageLayout.Orientation.Landscape)
    doc = _build_document(title, headers, rows, footer)
    preview = QPrintPreviewDialog(printer, parent_widget)
    preview.paintRequested.connect(doc.print_)
    preview.exec()


def export_report_pdf(
    parent_widget: QWidget, title: str, headers: list[str], rows: list[list], footer: list | None = None
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
    doc = _build_document(title, headers, rows, footer)
    doc.print_(printer)
    QMessageBox.information(parent_widget, "خروجیِ PDF", "فایلِ PDF با موفقیت ساخته شد.")


def export_report_excel(
    parent_widget: QWidget, title: str, headers: list[str], rows: list[list], footer: list | None = None
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
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append(list(row))
    if footer:
        sheet.append(list(footer))
        for cell in sheet[sheet.max_row]:
            cell.font = Font(bold=True)
    sheet.freeze_panes = "A2"
    for col_cells in sheet.columns:
        length = max((len(str(c.value)) for c in col_cells if c.value is not None), default=10)
        sheet.column_dimensions[col_cells[0].column_letter].width = min(max(length + 2, 10), 40)

    workbook.save(path)
    QMessageBox.information(parent_widget, "خروجیِ Excel", "فایلِ Excel با موفقیت ساخته شد.")
