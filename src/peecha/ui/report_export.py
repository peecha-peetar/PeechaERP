"""زیرساختِ مشترکِ خروجیِ گزارش‌ها — چاپ/PDF با QtPrintSupport (بدونِ
وابستگیِ بیرونی) و Excel با openpyxl. هر صفحه‌یِ گزارش (reports_common.py و
زیرکلاس‌هایش) همین سه تابع را با دیتایِ جدولِ فعلی‌اش صدا می‌زند.

طبقِ گزارش‌هایِ صریحِ کاربر، چند مشکلِ واقعی در خروجیِ چاپ/PDF پیدا و رفع شد:

۱. ترتیبِ ستون‌ها برعکس بود — ترتیبِ سلول‌ها در خودِ HTML معکوس نوشته
   می‌شود (نکته‌ی فنی: QTextDocument با dir="rtl" ستونِ *اول*ِ HTML را
   چپ‌ترین رسم می‌کند، برعکسِ قراردادِ راست‌به‌چپ).

۲. حاشیه‌یِ چاپ به‌صراحت به ۶ میلی‌متر تنظیم می‌شود.

۳. فونتِ چاپ از فونتِ واقعیِ برنامه (get_font_family) استفاده می‌کند،
   با اندازه‌یِ پیش‌فرضِ ۹pt (کوچک‌تر از حالتِ قبلی).

۴. **ریشه‌یِ واقعیِ باگِ «صفحه‌های نصفه/خالی» پیدا شد**: نسخه‌هایِ قبلی
   گزارش را به چند جدولِ جدا با CSS`page-break-after: always` بینِ آن‌ها
   می‌شکستند. این روش با عکسِ واقعیِ کاربر (صفحه‌ی ۲ کاملاً خالی، صفحه‌ی
   ۳ دوباره شروعِ محتوا) رد شد — پشتیبانیِ QTextDocument از
   page-break-* رویِ جدول‌هایِ چندبخشی قابلِ‌اتکا نیست و صفحه‌یِ خالیِ
   اضافه می‌سازد. **راه‌حلِ درست**: دیگر هیچ شکستِ صفحه‌ای دستی اعمال
   نمی‌شود — کلِ گزارش یک جدولِ پیوسته‌یِ واحد است و Qt خودش (که برایِ
   جدول‌هایِ بلند این کار را بومی و درست انجام می‌دهد) صفحه‌بندی می‌کند؛
   ردیف‌هایِ «جمعِ این صفحه» به‌عنوانِ ردیف‌هایِ عادیِ همان جدول، در
   فاصله‌هایِ تخمین‌زده‌شده (یا دستی‌تنظیم‌شده) درج می‌شوند — بدونِ هیچ
   شکستِ اجباری، پس دیگر هرگز صفحه‌یِ خالی نمی‌سازد؛ محدودیتِ صادقانه:
   ردیفِ جمع ممکن است دقیقاً رویِ خطِ لبه‌ی صفحه نیفتد (یکی-دو ردیف
   جابه‌جا)، ولی این بی‌ضرر است چون هیچ شکستی به آن وابسته نیست. `<thead>`
   خودِ Qt هم به‌صورتِ بومی رویِ هر صفحه تکرار می‌شود.

۵. **فرمِ «تنظیماتِ چاپ»** پیش از هر چاپ/PDF/اکسل باز می‌شود: اندازه‌یِ
   فونت، عرضِ هر ستون (٪)، تعدادِ ردیف در هر صفحه (یا خودکار)، و متنِ
   *کاملِ* هدر/فوتر (چندخطی، با متنِ پیش‌فرضِ همان نام‌شرکت/عنوان/تاریخ
   به‌عنوانِ نقطه‌یِ شروعِ قابلِ‌ویرایش، نه فقط یک خطِ اضافه)."""

from __future__ import annotations

import decimal
from dataclasses import dataclass

from PySide6.QtCore import QMarginsF, QSizeF
from PySide6.QtGui import QPageLayout, QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QTextEdit,
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
    # عرضِ خودکار/مساوی.
    column_widths: list[float] | None = None
    # اگر خالی باشد، هدرِ خودکار (نامِ شرکت+عنوان+تاریخ+فیلترها) ساخته
    # می‌شود؛ اگر پر باشد، *کاملاً جایگزینِ* آن می‌شود (چندخطی، آزاد).
    header_text: str = ""
    # زیرِ جدول (پس از ردیفِ جمعِ کل) اضافه می‌شود — مثلاً محلِ امضا.
    footer_text: str = ""
    # ۰ یعنی خودکار (تخمینِ تعدادِ ردیفی که در یک صفحه جا می‌شود)؛ عددِ
    # مثبت یعنی کاربر خودش فاصله‌یِ ردیف‌هایِ «جمعِ این صفحه» را تعیین کرده.
    rows_per_page: int = 0


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


def _default_header_plain_text(title: str, company_name: str, report_date: str, filters: list[tuple[str, str]] | None) -> str:
    lines = []
    if company_name:
        lines.append(company_name)
    lines.append(title)
    meta_parts = []
    if report_date:
        meta_parts.append(f"تاریخِ گزارش: {report_date}")
    for label, value in filters or []:
        meta_parts.append(f"{label}: {value}")
    if meta_parts:
        lines.append(" | ".join(meta_parts))
    return "\n".join(lines)


def _auto_header_html(title: str, company_name: str, report_date: str, filters: list[tuple[str, str]] | None) -> str:
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


def _multiline_html(text: str) -> str:
    lines = text.splitlines() or [""]
    return "".join(f"<div>{_escape(line) if line.strip() else '&nbsp;'}</div>" for line in lines)


def _resolve_header_html(options: PrintOptions, title: str, company_name: str, report_date: str, filters: list[tuple[str, str]] | None) -> str:
    if options.header_text.strip():
        return _multiline_html(options.header_text)
    return _auto_header_html(title, company_name, report_date, filters)


def _footer_extra_html(text: str) -> str:
    if not text.strip():
        return ""
    return f'<div style="margin-top:16px; font-size:9pt;">{_multiline_html(text)}</div>'


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


def _fits_one_page(page_size: QSizeF, page_html_kwargs: dict, font_family: str, font_size_pt: float) -> bool:
    doc = QTextDocument()
    doc.setHtml(_wrap_document(_page_body_html(**page_html_kwargs), font_family, font_size_pt))
    doc.setPageSize(page_size)
    return doc.pageCount() <= 1


def _estimate_rows_per_page(
    rows: list[list],
    headers: list[str],
    amount_col_indices: list[int],
    *,
    page_size: QSizeF,
    colgroup_html: str,
    head_cells: str,
    font_family: str,
    font_size_pt: float,
) -> int:
    """چند ردیفِ *اول* در یک صفحه جا می‌شوند — با جستجویِ دودویی رویِ
    اندازه‌گیریِ واقعیِ QTextDocument.pageCount(). این فقط برایِ تعیینِ
    فاصله‌یِ درجِ ردیف‌هایِ «جمعِ این صفحه» استفاده می‌شود (نه برایِ شکستِ
    اجباریِ صفحه) — پس یک تخمینِ کمی نادرست هم صفحه‌یِ خالی نمی‌سازد،
    فقط ردیفِ جمع را یکی-دو ردیف زودتر/دیرتر می‌نشاند."""
    lo, hi, best = 1, len(rows), 1
    while lo <= hi:
        mid = (lo + hi) // 2
        trial_rows = rows[:mid]
        trial_extra_html = _bold_row_html(_subtotal_row(headers, amount_col_indices, trial_rows))
        fits = _fits_one_page(
            page_size,
            {
                "page_header_html": "",
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
    return max(1, best)


def _rows_with_subtotals_html(
    rows: list[list],
    headers: list[str],
    amount_col_indices: list[int],
    rows_per_page_override: int,
    *,
    page_size: QSizeF,
    colgroup_html: str,
    head_cells: str,
    font_family: str,
    font_size_pt: float,
) -> str:
    if not amount_col_indices or len(rows) < 2:
        return _rows_html(rows)

    if rows_per_page_override and rows_per_page_override > 0:
        chunk_size = rows_per_page_override
    else:
        chunk_size = _estimate_rows_per_page(
            rows, headers, amount_col_indices, page_size=page_size, colgroup_html=colgroup_html,
            head_cells=head_cells, font_family=font_family, font_size_pt=font_size_pt,
        )

    parts = []
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        parts.append(_rows_html(chunk))
        is_last_chunk = i + chunk_size >= len(rows)
        if not is_last_chunk:
            parts.append(_bold_row_html(_subtotal_row(headers, amount_col_indices, chunk)))
    return "".join(parts)


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
    """سندِ نهایی برایِ چاپ/PDF — یک جدولِ پیوسته‌یِ واحد (بدونِ هیچ
    شکستِ صفحه‌ی دستی)؛ اگر چندصفحه‌ای شود، خودِ Qt صفحه‌بندی می‌کند و
    ردیفِ هدرِ جدول (thead) را خودکار در هر صفحه تکرار می‌کند."""
    options = options or PrintOptions()
    font_family = _print_font_family()
    font_size_pt = options.font_size_pt
    header_html = _resolve_header_html(options, title, company_name, report_date, filters)
    reversed_headers = list(reversed(headers))
    head_cells = "".join(f"<th>{_escape(h)}</th>" for h in reversed_headers)
    colgroup_html = _colgroup_html(options.column_widths, len(headers))
    amount_col_indices = _amount_column_indices(headers, rows)
    footer_extra_html = _footer_extra_html(options.footer_text)

    page_rect = printer.pageRect(QPrinter.Unit.Point)
    page_size = QSizeF(page_rect.width(), page_rect.height())

    body_rows_html = _rows_with_subtotals_html(
        rows, headers, amount_col_indices, options.rows_per_page,
        page_size=page_size, colgroup_html=colgroup_html, head_cells=head_cells,
        font_family=font_family, font_size_pt=font_size_pt,
    )
    footer_row_html = _bold_row_html(footer) if footer else ""

    doc = QTextDocument()
    doc.setHtml(
        _wrap_document(
            _page_body_html(
                page_header_html=header_html, colgroup_html=colgroup_html, head_cells=head_cells,
                body_rows_html=body_rows_html, extra_row_html=footer_row_html, extra_footer_html=footer_extra_html,
            ),
            font_family, font_size_pt,
        )
    )
    doc.setPageSize(page_size)
    return doc


class _PrintOptionsDialog(QDialog):
    def __init__(
        self, parent: QWidget | None, title: str, headers: list[str], defaults: PrintOptions | None,
        *, company_name: str, report_date: str, filters: list[tuple[str, str]] | None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"تنظیماتِ چاپ — {title}")
        self.setMinimumWidth(460)
        defaults = defaults or PrintOptions()
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("اندازه‌یِ فونت (pt):"))
        self.font_size_field = QSpinBox()
        self.font_size_field.setRange(6, 16)
        self.font_size_field.setValue(int(round(defaults.font_size_pt)))
        top_row.addWidget(self.font_size_field)
        top_row.addSpacing(16)
        top_row.addWidget(QLabel("ردیف در هر صفحه (۰=خودکار):"))
        self.rows_per_page_field = QSpinBox()
        self.rows_per_page_field.setRange(0, 500)
        self.rows_per_page_field.setValue(defaults.rows_per_page)
        top_row.addWidget(self.rows_per_page_field)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        layout.addWidget(QLabel("عرضِ ستون‌ها (٪ از عرضِ کلِ جدول):"))
        columns_scroll = QScrollArea()
        columns_scroll.setWidgetResizable(True)
        columns_scroll.setMaximumHeight(200)
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

        layout.addWidget(QLabel("متنِ هدر (کاملاً قابلِ‌ویرایش — همین متن به‌جایِ هدرِ خودکار چاپ می‌شود):"))
        self.header_text_field = QTextEdit()
        self.header_text_field.setPlainText(
            defaults.header_text or _default_header_plain_text(title, company_name, report_date, filters)
        )
        self.header_text_field.setMaximumHeight(90)
        layout.addWidget(self.header_text_field)

        layout.addWidget(QLabel("متنِ فوتر (اختیاری — چندخطی، مثلاً محلِ امضا):"))
        self.footer_text_field = QTextEdit()
        self.footer_text_field.setPlainText(defaults.footer_text)
        self.footer_text_field.setMaximumHeight(70)
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
            header_text=self.header_text_field.toPlainText().strip(),
            footer_text=self.footer_text_field.toPlainText().strip(),
            rows_per_page=self.rows_per_page_field.value(),
        )


def prompt_print_options(
    parent_widget: QWidget,
    title: str,
    headers: list[str],
    defaults: PrintOptions | None = None,
    *,
    company_name: str = "",
    report_date: str = "",
    filters: list[tuple[str, str]] | None = None,
) -> PrintOptions | None:
    dialog = _PrintOptionsDialog(
        parent_widget, title, headers, defaults,
        company_name=company_name, report_date=report_date, filters=filters,
    )
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

    # طبقِ همان درخواستِ سربرگِ چاپ: نامِ شرکت + عنوان + تاریخ/فیلترها (یا
    # متنِ سفارشیِ کاربر) به‌عنوانِ چند سطرِ اول، پیش از جدولِ خودِ گزارش.
    header_text = options.header_text.strip() or _default_header_plain_text(title, company_name, report_date, filters)
    for line in header_text.splitlines():
        sheet.append([line])
    sheet.cell(row=1, column=1).font = Font(bold=True, size=13)
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
    if options.footer_text.strip():
        sheet.append([])
        for line in options.footer_text.strip().splitlines():
            sheet.append([line])
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
