"""زیرساختِ مشترکِ خروجیِ گزارش‌ها — چاپ/PDF با QtPrintSupport (بدونِ
وابستگیِ بیرونی) و Excel با openpyxl. هر صفحه‌یِ گزارش (reports_common.py و
زیرکلاس‌هایش) همین سه تابع را با دیتایِ جدولِ فعلی‌اش صدا می‌زند.

طبقِ گزارش‌هایِ صریحِ کاربر، چند مشکلِ واقعی در خروجیِ چاپ/PDF پیدا و رفع شد:

۱. ترتیبِ ستون‌ها برعکس بود. آزمایشِ مستقیم نشان داد QTextDocument با
   `dir="rtl"` رویِ `<html>`، ستونِ *اول*ِ نوشته‌شده در HTML را چپ‌ترین و
   ستونِ *آخر* را راست‌ترین رسم می‌کند — یعنی دقیقاً برعکسِ قراردادِ
   استانداردِ صفحه‌گسترده‌هایِ راست‌به‌چپ. راه‌حل: ترتیبِ سلول‌ها را در
   خودِ HTML معکوس می‌نویسیم.

۲. هدرِ چاپ فقط عنوانِ گزارش را داشت. حالا سه سطرِ هدر دارد: نامِ شرکت،
   عنوانِ گزارش، و تاریخِ گزارش + فیلترهایِ اعمال‌شده.

۳. حاشیه‌یِ چاپ زیاد بود. حاشیه‌هایِ صفحه به‌صراحت به مقدارِ کمی
   (۶ میلی‌متر) تنظیم می‌شوند. محدودیتِ صادقانه: اگر چاپگرِ فیزیکی خودش
   حداقلِ‌حاشیه‌یِ سخت‌افزاریِ بزرگ‌تری تحمیل کند، Qt/درایور آن مقدار را
   جایگزین می‌کند — این محدودیت فقط رویِ خروجیِ PDF (بدونِ محدودیتِ
   سخت‌افزاری) همیشه دقیقاً اعمال می‌شود.

۴. فونتِ متنِ چاپ/PDF قبلاً `sans-serif` خامِ عمومی بود — حالا از همان
   فونتِ برنامه (get_font_family در ui/main.py) استفاده می‌کند، و
   اندازه‌ی پیش‌فرض هم از ۱۰ به ۹pt کاهش یافت (طبقِ گزارشِ «فونت درشتی
   داره»).

۵. گزارش‌هایِ چندصفحه‌ای «جمعِ هر صفحه» نداشتند و مرزِ صفحات با
   **تخمینِ میانگین** (pageCount / تعدادِ ردیف) تعیین می‌شد — این تخمین
   وقتی ارتفاعِ ردیف‌ها یکنواخت نبود (مثلاً نام‌هایِ بلند که به دو خط
   می‌شکنند) کاملاً نادرست از آب درمی‌آمد: عکسِ واقعیِ کاربر نشان داد
   صفحه‌ای با فقط یک ردیف و باقیِ صفحه کاملاً خالی (اسرافِ کاغذ). حالا
   مرزِ هر صفحه با **جستجویِ دودویی رویِ اندازه‌گیریِ واقعیِ خودِ
   QTextDocument.pageCount()** پیدا می‌شود — یعنی دقیقاً همان تعداد
   ردیفی که واقعاً در یک صفحه جا می‌شود، نه یک میانگینِ تقریبی.

۶. فرمِ «تنظیماتِ چاپ» پیش از هر چاپ/PDF/اکسل باز می‌شود — اندازه‌یِ
   فونت، عرضِ هر ستون (٪)، و یک خطِ اضافه برایِ هدر/فوتر (مثلاً محلِ
   امضا) از همان‌جا قابلِ‌تنظیم است."""

from __future__ import annotations

import decimal
from dataclasses import dataclass

from PySide6.QtCore import QSizeF, QMarginsF
from PySide6.QtGui import QPageLayout, QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals
from peecha.ui.main import get_font_family

_PAGE_MARGIN_MM = 6.0
_DEFAULT_FONT_SIZE_PT = 9.0
# طبقِ عنوانِ ستون تشخیص داده می‌شود که «جمعِ صفحه» برایش معنا دارد —
# نه فقط قابلِ‌پارس‌بودنِ عدد، وگرنه ستون‌هایی مثلِ «شماره‌یِ سند» هم
# اشتباهی جمع می‌شدند.
_AMOUNT_HEADER_KEYWORDS = ("بدهکار", "بستانکار", "بد)", "بس)", "مانده", "مبلغ")


@dataclass
class PrintOptions:
    font_size_pt: float = _DEFAULT_FONT_SIZE_PT
    # درصدِ عرضِ هر ستون، هم‌ترتیب با headers (نه معکوس‌شده) — None یعنی
    # عرضِ خودکار/مساوی (پیش‌فرضِ قبلی).
    column_widths: list[float] | None = None
    extra_header_text: str = ""
    extra_footer_text: str = ""


def _escape(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _print_font_family() -> str:
    try:
        return get_font_family()
    except Exception:
        return "Tahoma"


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


def _subtotal_row(headers: list[str], amount_col_indices: list[int], chunk_rows: list[list]) -> list:
    totals: list[str] = ["" for _ in headers]
    totals[0] = "جمعِ این صفحه"
    for col in amount_col_indices:
        totals[col] = numerals.format_amount(_sum_amount_cells(chunk_rows, col))
    return totals


def _header_block_html(
    title: str,
    company_name: str,
    report_date: str,
    filters: list[tuple[str, str]] | None,
    extra_header_text: str = "",
) -> str:
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
    if extra_header_text:
        header_lines += f'<div style="font-size:9pt; margin-top:4px;">{_escape(extra_header_text)}</div>'
    return header_lines


def _colgroup_html(column_widths: list[float] | None, num_cols: int) -> str:
    if not column_widths or len(column_widths) != num_cols:
        return ""
    reversed_widths = list(reversed(column_widths))
    cols = "".join(f'<col style="width:{w:.2f}%">' for w in reversed_widths)
    return f"<colgroup>{cols}</colgroup>"


def _rows_html(rows: list[list]) -> str:
    return "".join(
        "<tr>" + "".join(f"<td>{_escape(c)}</td>" for c in reversed(row)) + "</tr>" for row in rows
    )


def _bold_row_html(cells: list) -> str:
    return "<tr>" + "".join(f"<td><b>{_escape(c)}</b></td>" for c in reversed(cells)) + "</tr>"


def _page_body_html(
    *, page_header_html: str, colgroup_html: str, head_cells: str, body_rows_html: str,
    extra_row_html: str, extra_footer_html: str,
) -> str:
    return f"""
    <div style="text-align:center; margin-bottom:8px;">{page_header_html}</div>
    <table border="1" cellspacing="0" cellpadding="3" width="100%" style="border-collapse: collapse; table-layout: fixed;">
    {colgroup_html}
    <thead><tr>{head_cells}</tr></thead>
    <tbody>{body_rows_html}{extra_row_html}</tbody>
    </table>
    {extra_footer_html}
    """


def _wrap_document(body_html: str, font_family: str, font_size_pt: float) -> str:
    return f"""
    <html dir="rtl"><head><meta charset="utf-8"></head>
    <body style="font-family: '{font_family}', Tahoma, sans-serif; font-size: {font_size_pt}pt;">
    {body_html}
    </body></html>
    """


def _extra_footer_html(text: str) -> str:
    if not text:
        return ""
    return f'<div style="margin-top:16px; font-size:9pt;">{_escape(text)}</div>'


def _fits_one_page(page_size: QSizeF, page_html_kwargs: dict, font_family: str, font_size_pt: float) -> bool:
    doc = QTextDocument()
    doc.setHtml(_wrap_document(_page_body_html(**page_html_kwargs), font_family, font_size_pt))
    doc.setPageSize(page_size)
    return doc.pageCount() <= 1


def _compute_page_chunks(
    rows: list[list],
    headers: list[str],
    *,
    page_size: QSizeF,
    colgroup_html: str,
    head_cells: str,
    header_lines: str,
    title: str,
    amount_col_indices: list[int],
    font_family: str,
    font_size_pt: float,
) -> list[list]:
    """مرزِ هر صفحه را با جستجویِ دودویی رویِ اندازه‌گیریِ واقعیِ
    QTextDocument.pageCount() پیدا می‌کند — نه با تخمینِ میانگین."""
    chunks: list[list] = []
    remaining = rows
    is_first = True
    while remaining:
        page_header_html = header_lines if is_first else f'<h4 style="margin:4px 0;">ادامه — {_escape(title)}</h4>'
        lo, hi, best = 1, len(remaining), 1
        while lo <= hi:
            mid = (lo + hi) // 2
            trial_rows = remaining[:mid]
            trial_extra_html = (
                _bold_row_html(_subtotal_row(headers, amount_col_indices, trial_rows)) if amount_col_indices else ""
            )
            fits = _fits_one_page(
                page_size,
                {
                    "page_header_html": page_header_html,
                    "colgroup_html": colgroup_html,
                    "head_cells": head_cells,
                    "body_rows_html": _rows_html(trial_rows),
                    "extra_row_html": trial_extra_html,
                    "extra_footer_html": "",
                },
                font_family,
                font_size_pt,
            )
            if fits:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        chunks.append(remaining[:best])
        remaining = remaining[best:]
        is_first = False
    return chunks


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
    options: PrintOptions | None = None,
) -> QTextDocument:
    """سندِ نهایی برایِ چاپ/PDF — اگر همه‌چیز در یک صفحه جا شود، همان
    جدولِ ساده؛ وگرنه نسخه‌یِ صفحه‌بندی‌شده (با مرزِ دقیقِ اندازه‌گیری‌شده)
    و جمعِ هر صفحه."""
    options = options or PrintOptions()
    font_family = _print_font_family()
    font_size_pt = options.font_size_pt
    header_lines = _header_block_html(title, company_name, report_date, filters, options.extra_header_text)
    reversed_headers = list(reversed(headers))
    head_cells = "".join(f"<th>{_escape(h)}</th>" for h in reversed_headers)
    colgroup_html = _colgroup_html(options.column_widths, len(headers))
    amount_col_indices = _amount_column_indices(headers, rows)
    extra_footer_html = _extra_footer_html(options.extra_footer_text)

    page_rect = printer.pageRect(QPrinter.Unit.Point)
    page_size = QSizeF(page_rect.width(), page_rect.height())

    single_extra_row = _bold_row_html(footer) if footer else ""
    doc = QTextDocument()
    doc.setHtml(
        _wrap_document(
            _page_body_html(
                page_header_html=header_lines, colgroup_html=colgroup_html, head_cells=head_cells,
                body_rows_html=_rows_html(rows), extra_row_html=single_extra_row, extra_footer_html=extra_footer_html,
            ),
            font_family, font_size_pt,
        )
    )
    doc.setPageSize(page_size)
    if doc.pageCount() <= 1 or len(rows) < 2:
        return doc

    chunks = _compute_page_chunks(
        rows, headers, page_size=page_size, colgroup_html=colgroup_html, head_cells=head_cells,
        header_lines=header_lines, title=title, amount_col_indices=amount_col_indices,
        font_family=font_family, font_size_pt=font_size_pt,
    )
    body_blocks = []
    for i, chunk_rows in enumerate(chunks):
        is_last = i == len(chunks) - 1
        page_header_html = header_lines if i == 0 else f'<h4 style="margin:4px 0;">ادامه — {_escape(title)}</h4>'
        if is_last and footer:
            extra_row_html = _bold_row_html(footer)
        elif amount_col_indices:
            extra_row_html = _bold_row_html(_subtotal_row(headers, amount_col_indices, chunk_rows))
        else:
            extra_row_html = ""
        page_break = "" if is_last else '<div style="page-break-after: always;"></div>'
        body_blocks.append(
            _page_body_html(
                page_header_html=page_header_html, colgroup_html=colgroup_html, head_cells=head_cells,
                body_rows_html=_rows_html(chunk_rows), extra_row_html=extra_row_html,
                extra_footer_html=extra_footer_html if is_last else "",
            )
            + page_break
        )
    paginated_doc = QTextDocument()
    paginated_doc.setHtml(_wrap_document("".join(body_blocks), font_family, font_size_pt))
    paginated_doc.setPageSize(page_size)
    return paginated_doc


class _PrintOptionsDialog(QDialog):
    def __init__(self, parent: QWidget | None, title: str, headers: list[str], defaults: PrintOptions | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"تنظیماتِ چاپ — {title}")
        self.setMinimumWidth(420)
        defaults = defaults or PrintOptions()
        layout = QVBoxLayout(self)

        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("اندازه‌یِ فونت (pt):"))
        self.font_size_field = QSpinBox()
        self.font_size_field.setRange(6, 16)
        self.font_size_field.setValue(int(round(defaults.font_size_pt)))
        font_row.addWidget(self.font_size_field)
        font_row.addStretch(1)
        layout.addLayout(font_row)

        layout.addWidget(QLabel("عرضِ ستون‌ها (٪ از عرضِ کلِ جدول):"))
        columns_scroll = QScrollArea()
        columns_scroll.setWidgetResizable(True)
        columns_scroll.setMaximumHeight(220)
        columns_widget = QWidget()
        columns_form = QFormLayout(columns_widget)
        self._width_fields: list[QSpinBox] = []
        default_widths = defaults.column_widths if defaults.column_widths and len(defaults.column_widths) == len(headers) else None
        if default_widths is None:
            default_widths = [round(100 / max(len(headers), 1), 1)] * len(headers)
        for header, default_w in zip(headers, default_widths):
            field_widget = QSpinBox()
            field_widget.setRange(3, 60)
            field_widget.setValue(int(round(default_w)))
            field_widget.setSuffix(" ٪")
            columns_form.addRow(header, field_widget)
            self._width_fields.append(field_widget)
        columns_scroll.setWidget(columns_widget)
        layout.addWidget(columns_scroll)

        layout.addWidget(QLabel("متنِ اضافه‌یِ هدر (اختیاری):"))
        self.header_text_field = QLineEdit(defaults.extra_header_text)
        layout.addWidget(self.header_text_field)

        layout.addWidget(QLabel("متنِ اضافه‌یِ فوتر (اختیاری — مثلاً محلِ امضا):"))
        self.footer_text_field = QLineEdit(defaults.extra_footer_text)
        layout.addWidget(self.footer_text_field)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("تاییدِ تنظیمات و ادامه")
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_options(self) -> PrintOptions:
        widths = [f.value() for f in self._width_fields]
        total = sum(widths) or 1
        normalized = [w * 100 / total for w in widths]
        return PrintOptions(
            font_size_pt=float(self.font_size_field.value()),
            column_widths=normalized,
            extra_header_text=self.header_text_field.text().strip(),
            extra_footer_text=self.footer_text_field.text().strip(),
        )


def prompt_print_options(
    parent_widget: QWidget, title: str, headers: list[str], defaults: PrintOptions | None = None
) -> PrintOptions | None:
    dialog = _PrintOptionsDialog(parent_widget, title, headers, defaults)
    if dialog.exec() != QDialog.Accepted:
        return None
    return dialog.result_options()


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
    options: PrintOptions | None = None,
) -> None:
    if not rows:
        QMessageBox.information(parent_widget, "چاپ", "گزارشی برایِ چاپ وجود ندارد.")
        return
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    _apply_page_setup(printer)
    doc = _build_final_document(
        printer, title, headers, rows, footer,
        company_name=company_name, report_date=report_date, filters=filters, options=options,
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
    options: PrintOptions | None = None,
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
        printer, title, headers, rows, footer,
        company_name=company_name, report_date=report_date, filters=filters, options=options,
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
    options: PrintOptions | None = None,
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

    options = options or PrintOptions()
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = (title[:31] or "گزارش").replace("/", "-")
    sheet.sheet_view.rightToLeft = True

    # طبقِ همان درخواستِ سربرگِ چاپ: نامِ شرکت + عنوان + تاریخ/فیلترها به‌عنوانِ
    # چند سطرِ اول، پیش از جدولِ خودِ گزارش. توجه: بازچینیِ ستون این‌جا لازم
    # نیست چون sheet_view.rightToLeft خودش راست‌ترین=ستونِ اول را درست می‌چیند.
    if company_name:
        sheet.append([company_name])
        sheet.cell(row=sheet.max_row, column=1).font = Font(bold=True, size=13)
    sheet.append([title])
    sheet.cell(row=sheet.max_row, column=1).font = Font(bold=True, size=12)
    meta_parts = []
    if report_date:
        meta_parts.append(f"تاریخِ گزارش: {report_date}")
    for label, value in filters or []:
        meta_parts.append(f"{label}: {value}")
    if meta_parts:
        sheet.append([" | ".join(meta_parts)])
    if options.extra_header_text:
        sheet.append([options.extra_header_text])
    sheet.append([])

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
    if options.extra_footer_text:
        sheet.append([])
        sheet.append([options.extra_footer_text])
    sheet.freeze_panes = f"A{header_row + 1}"

    if options.column_widths and len(options.column_widths) == len(headers):
        # درصدها را به واحدِ عرضِ اکسل (تقریباً کاراکتر) تبدیل می‌کنیم —
        # مجموعِ عرضِ همه‌ی ستون‌ها را حدودِ ۱۲۰ کاراکتر در نظر می‌گیریم.
        for col_index, width_pct in enumerate(options.column_widths, start=1):
            letter = sheet.cell(row=header_row, column=col_index).column_letter
            sheet.column_dimensions[letter].width = max(8, round(120 * width_pct / 100))
    else:
        for col_cells in sheet.columns:
            length = max((len(str(c.value)) for c in col_cells if c.value is not None), default=10)
            sheet.column_dimensions[col_cells[0].column_letter].width = min(max(length + 2, 10), 40)

    workbook.save(path)
    QMessageBox.information(parent_widget, "خروجیِ Excel", "فایلِ Excel با موفقیت ساخته شد.")
