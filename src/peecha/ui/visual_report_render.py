"""موتورِ چیدمان+رسمِ طراحِ بصریِ گزارشِ چاپی — پیجینیشن (خالصِ پایتون،
بدونِ Qt) جدا از رسم (QPainter) است تا هم برایِ پیش‌نمایشِ زنده و هم
چاپ/PDF یک‌بار محاسبه و به‌سادگی رسم شود.

الگوریتمِ پیجینیشن: یک عبورِ ساده رویِ ردیف‌هایِ گزارش — برایِ گزارشِ
DETAIL که group_by_account دارد، ردیف‌هایِ بولد (که از قبل در
compute_detail_report به‌عنوانِ جمعِ فرعی ساخته شده‌اند) مستقیماً باندِ
GROUP_FOOTER را رسم می‌کنند و شروعِ هر دنباله‌یِ ردیفِ غیربولد باندِ
GROUP_HEADER را — یعنی گروه‌بندیِ بصری رویِ همان مکانیزمِ موجودِ
گزارش‌سازِ کامل سوار می‌شود، نه یک موتورِ تازه."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPen, QPixmap
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from peecha import numerals
from peecha.services import report_designer as report_designer_service
from peecha.services import reports as reports_service
from peecha.services import visual_reports as visual_reports_service
from peecha.services.reports import ReportCell, ReportRow

_PAGE_SIZES_MM = {
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
    "LETTER": (215.9, 279.4),
}

_GLOBAL_FIELD_CODES = {
    "COMPANY_NAME",
    "REPORT_TITLE",
    "PRINT_DATE",
    "PAGE_NUMBER",
    "PAGE_COUNT",
    "GRAND_TOTAL_DEBIT",
    "GRAND_TOTAL_CREDIT",
}


def page_size_mm(page_size: str, orientation: str) -> tuple[float, float]:
    w, h = _PAGE_SIZES_MM.get(page_size, _PAGE_SIZES_MM["A4"])
    return (h, w) if orientation == "LANDSCAPE" else (w, h)


@dataclass
class PlacedItem:
    band: visual_reports_service.VisualBandRow
    y_mm: float
    row: ReportRow | None


@dataclass
class RenderContext:
    company_name: str
    report_title: str
    print_date_str: str
    grand_total_debit: decimal.Decimal | None
    grand_total_credit: decimal.Decimal | None
    total_pages: int = 1


def compute_layout_plan(
    bands_by_type: dict[str, visual_reports_service.VisualBandRow],
    rows: list[ReportRow],
    page_content_height_mm: float,
) -> list[list[PlacedItem]]:
    report_header = bands_by_type.get("REPORT_HEADER")
    page_header = bands_by_type.get("PAGE_HEADER")
    page_footer = bands_by_type.get("PAGE_FOOTER")
    report_footer = bands_by_type.get("REPORT_FOOTER")
    group_header = bands_by_type.get("GROUP_HEADER")
    group_footer = bands_by_type.get("GROUP_FOOTER")
    detail = bands_by_type.get("DETAIL")

    footer_reserve = float(page_footer.height_mm) if page_footer else 0.0
    pages: list[list[PlacedItem]] = []
    current_page: list[PlacedItem] = []
    cursor = 0.0

    def start_page(first: bool) -> None:
        nonlocal cursor, current_page
        cursor = 0.0
        current_page = []
        if first and report_header:
            current_page.append(PlacedItem(report_header, cursor, None))
            cursor += float(report_header.height_mm)
        if page_header:
            current_page.append(PlacedItem(page_header, cursor, None))
            cursor += float(page_header.height_mm)

    def finish_page() -> None:
        if page_footer:
            current_page.append(PlacedItem(page_footer, page_content_height_mm - footer_reserve, None))
        pages.append(current_page)

    def ensure_space(height: float) -> None:
        nonlocal cursor
        if cursor + height + footer_reserve > page_content_height_mm:
            finish_page()
            start_page(False)

    start_page(True)
    if detail is None:
        finish_page()
        return pages

    at_group_start = True
    for row in rows:
        if row.is_bold and group_footer:
            ensure_space(float(group_footer.height_mm))
            current_page.append(PlacedItem(group_footer, cursor, row))
            cursor += float(group_footer.height_mm)
            at_group_start = True
        else:
            if at_group_start and group_header:
                ensure_space(float(group_header.height_mm))
                current_page.append(PlacedItem(group_header, cursor, row))
                cursor += float(group_header.height_mm)
            at_group_start = False
            ensure_space(float(detail.height_mm))
            current_page.append(PlacedItem(detail, cursor, row))
            cursor += float(detail.height_mm)

    if report_footer:
        ensure_space(float(report_footer.height_mm))
        current_page.append(PlacedItem(report_footer, cursor, None))
        cursor += float(report_footer.height_mm)
    finish_page()
    return pages if pages else [[]]


def _detail_field_index_map(report_template_id: int) -> dict[str, int]:
    columns = report_designer_service.list_columns(report_template_id)
    return {c.field_code: i for i, c in enumerate(columns) if c.field_code}


def _resolve_row_field(row: ReportRow | None, is_summary: bool, index_map: dict[str, int], field_code: str) -> ReportCell | None:
    if row is None:
        return None
    if is_summary:
        if field_code == "ROW_LABEL":
            return row.cells[0] if row.cells else None
        if field_code.startswith("COL_"):
            try:
                idx = int(field_code[4:])
            except ValueError:
                return None
            return row.cells[idx] if idx < len(row.cells) else None
        return None
    idx = index_map.get(field_code)
    if idx is None or idx >= len(row.cells):
        return None
    return row.cells[idx]


def _format_cell(cell: ReportCell | None, decimal_places: int) -> str:
    if cell is None or cell.value is None:
        return ""
    if cell.kind == "MONEY":
        return numerals.format_money(cell.value, decimal_places, None)
    if cell.kind == "DATE":
        return numerals.format_jalali_date(cell.value)
    return str(cell.value)


def _resolve_global_field(field_code: str, context: RenderContext, page_number: int) -> str:
    if field_code == "COMPANY_NAME":
        return context.company_name
    if field_code == "REPORT_TITLE":
        return context.report_title
    if field_code == "PRINT_DATE":
        return context.print_date_str
    if field_code == "PAGE_NUMBER":
        return numerals.to_persian_digits(str(page_number))
    if field_code == "PAGE_COUNT":
        return numerals.to_persian_digits(str(context.total_pages))
    if field_code == "GRAND_TOTAL_DEBIT":
        return numerals.format_money(context.grand_total_debit, 0, None) if context.grand_total_debit is not None else ""
    if field_code == "GRAND_TOTAL_CREDIT":
        return numerals.format_money(context.grand_total_credit, 0, None) if context.grand_total_credit is not None else ""
    return ""


def _prepare(
    visual_template_id: int,
    company_id: int,
    company_name: str,
    date_from: datetime.date,
    date_to: datetime.date,
    *,
    status_filter: str = "EXCLUDE_DRAFT",
    cost_center_id: int | None = None,
    document_no_filter: int | None = None,
    decimal_places: int = 0,
):
    visual_template = visual_reports_service.get_template(visual_template_id)
    if visual_template is None:
        raise ValueError("گزارشِ بصری پیدا نشد.")
    bands = visual_reports_service.list_bands(visual_template_id)
    bands_by_type = {b.band_type: b for b in bands}
    objects_by_band = visual_reports_service.list_objects_by_band(visual_template_id)

    report_templates = {t.report_template_id: t for t in report_designer_service.list_templates(company_id)}
    report_template = report_templates.get(visual_template.report_template_id)
    if report_template is None:
        raise ValueError("منبعِ داده‌یِ این گزارش پیدا نشد.")
    is_summary = report_template.report_kind == "SUMMARY"

    if is_summary:
        _headers, rows = reports_service.compute_summary_report(
            report_template.report_template_id, company_id, date_from, date_to, status_filter=status_filter
        )
        index_map: dict[str, int] = {}
    else:
        _headers, rows = reports_service.compute_detail_report(
            report_template.report_template_id,
            company_id,
            date_from,
            date_to,
            status_filter=status_filter,
            cost_center_id=cost_center_id,
            document_no_filter=document_no_filter,
        )
        index_map = _detail_field_index_map(report_template.report_template_id)

    grand_debit = grand_credit = None
    if not is_summary:
        debit_idx = index_map.get("DEBIT")
        credit_idx = index_map.get("CREDIT")
        if debit_idx is not None:
            grand_debit = sum(
                (r.cells[debit_idx].value for r in rows if not r.is_bold and r.cells[debit_idx].value), decimal.Decimal(0)
            )
        if credit_idx is not None:
            grand_credit = sum(
                (r.cells[credit_idx].value for r in rows if not r.is_bold and r.cells[credit_idx].value), decimal.Decimal(0)
            )

    context = RenderContext(
        company_name=company_name,
        report_title=visual_template.name,
        print_date_str=numerals.format_jalali_date(datetime.date.today()),
        grand_total_debit=grand_debit,
        grand_total_credit=grand_credit,
    )

    page_w_mm, page_h_mm = page_size_mm(visual_template.page_size, visual_template.orientation)
    content_h_mm = page_h_mm - float(visual_template.margin_top_mm) - float(visual_template.margin_bottom_mm)
    pages = compute_layout_plan(bands_by_type, rows, content_h_mm)
    context.total_pages = len(pages)

    return {
        "visual_template": visual_template,
        "is_summary": is_summary,
        "index_map": index_map,
        "objects_by_band": objects_by_band,
        "pages": pages,
        "context": context,
        "page_w_mm": page_w_mm,
        "page_h_mm": page_h_mm,
        "decimal_places": decimal_places,
    }


def _draw_object(painter, obj, rect: QRect, cell: ReportCell | None, decimal_places: int) -> None:
    if obj.object_type == "IMAGE":
        if obj.image_data:
            pixmap = QPixmap()
            pixmap.loadFromData(obj.image_data)
            if not pixmap.isNull():
                painter.drawPixmap(rect, pixmap)
        return
    if obj.object_type == "LINE":
        pen = QPen(Qt.black)
        pen.setWidth(max(1, int(obj.height_mm)))
        painter.setPen(pen)
        painter.drawLine(rect.left(), rect.top(), rect.right(), rect.top())
        return
    if obj.object_type == "RECTANGLE":
        painter.setPen(QPen(Qt.black, 1))
        painter.drawRect(rect)
        return

    # TEXT | FIELD
    font = QFont(None if obj.font_family == "default" else obj.font_family)
    font.setPointSize(obj.font_size)
    font.setBold(obj.font_bold)
    painter.setFont(font)
    painter.setPen(QPen(Qt.black))

    align = {"RIGHT": Qt.AlignRight, "CENTER": Qt.AlignHCenter, "LEFT": Qt.AlignLeft}.get(
        obj.text_align, Qt.AlignRight
    )
    text = obj.text_content or "" if obj.object_type == "TEXT" else _format_cell(cell, decimal_places)
    painter.drawText(rect, int(align | Qt.AlignVCenter | Qt.TextWordWrap), text)

    if obj.border_style != "NONE":
        pen = QPen(Qt.black, 1)
        painter.setPen(pen)
        if obj.border_style in ("ALL", "BOTTOM"):
            painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        if obj.border_style in ("ALL", "TOP"):
            painter.drawLine(rect.topLeft(), rect.topRight())
        if obj.border_style == "ALL":
            painter.drawLine(rect.topLeft(), rect.bottomLeft())
            painter.drawLine(rect.topRight(), rect.bottomRight())


def _paint_page(painter, page_items, prepared: dict, px_per_mm: float, page_number: int) -> None:
    visual_template = prepared["visual_template"]
    margin_left_px = float(visual_template.margin_left_mm) * px_per_mm
    margin_top_px = float(visual_template.margin_top_mm) * px_per_mm
    objects_by_band = prepared["objects_by_band"]
    is_summary = prepared["is_summary"]
    index_map = prepared["index_map"]
    context = prepared["context"]
    decimal_places = prepared["decimal_places"]

    for item in page_items:
        for obj in objects_by_band.get(item.band.band_id, []):
            x = margin_left_px + float(obj.x_mm) * px_per_mm
            y = margin_top_px + item.y_mm * px_per_mm + float(obj.y_mm) * px_per_mm
            w = float(obj.width_mm) * px_per_mm
            h = float(obj.height_mm) * px_per_mm
            rect = QRect(int(x), int(y), int(w), int(h))

            cell = None
            if obj.object_type == "FIELD" and obj.field_code:
                if obj.field_code in _GLOBAL_FIELD_CODES:
                    text = _resolve_global_field(obj.field_code, context, page_number)
                    cell = ReportCell(value=text, kind="TEXT")
                else:
                    cell = _resolve_row_field(item.row, is_summary, index_map, obj.field_code)
            _draw_object(painter, obj, rect, cell, decimal_places)


def _paint_all(printer: QPrinter, prepared: dict) -> None:
    from PySide6.QtGui import QPainter

    painter = QPainter(printer)
    px_per_mm = printer.resolution() / 25.4
    pages = prepared["pages"]
    for page_number, page_items in enumerate(pages, start=1):
        if page_number > 1:
            printer.newPage()
        _paint_page(painter, page_items, prepared, px_per_mm, page_number)
    painter.end()


def _setup_printer(printer: QPrinter, visual_template: visual_reports_service.VisualTemplateRow) -> None:
    page_size = {"A4": QPageSize.A4, "A5": QPageSize.A5, "LETTER": QPageSize.Letter}.get(
        visual_template.page_size, QPageSize.A4
    )
    printer.setPageSize(QPageSize(page_size))
    printer.setPageOrientation(
        QPageLayout.Orientation.Landscape
        if visual_template.orientation == "LANDSCAPE"
        else QPageLayout.Orientation.Portrait
    )
    printer.setFullPage(True)


def print_visual_report(
    parent_widget: QWidget,
    visual_template_id: int,
    company_id: int,
    company_name: str,
    date_from: datetime.date,
    date_to: datetime.date,
    *,
    status_filter: str = "EXCLUDE_DRAFT",
    cost_center_id: int | None = None,
    document_no_filter: int | None = None,
    decimal_places: int = 0,
) -> None:
    prepared = _prepare(
        visual_template_id,
        company_id,
        company_name,
        date_from,
        date_to,
        status_filter=status_filter,
        cost_center_id=cost_center_id,
        document_no_filter=document_no_filter,
        decimal_places=decimal_places,
    )
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    _setup_printer(printer, prepared["visual_template"])
    preview = QPrintPreviewDialog(printer, parent_widget)
    preview.paintRequested.connect(lambda p: _paint_all(p, prepared))
    preview.exec()


def export_visual_report_pdf(
    parent_widget: QWidget,
    visual_template_id: int,
    company_id: int,
    company_name: str,
    date_from: datetime.date,
    date_to: datetime.date,
    *,
    status_filter: str = "EXCLUDE_DRAFT",
    cost_center_id: int | None = None,
    document_no_filter: int | None = None,
    decimal_places: int = 0,
) -> None:
    prepared = _prepare(
        visual_template_id,
        company_id,
        company_name,
        date_from,
        date_to,
        status_filter=status_filter,
        cost_center_id=cost_center_id,
        document_no_filter=document_no_filter,
        decimal_places=decimal_places,
    )
    title = prepared["visual_template"].name
    path, _filter = QFileDialog.getSaveFileName(parent_widget, "ذخیره‌یِ PDF", f"{title}.pdf", "PDF (*.pdf)")
    if not path:
        return
    if not path.lower().endswith(".pdf"):
        path += ".pdf"
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    _setup_printer(printer, prepared["visual_template"])
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(path)
    _paint_all(printer, prepared)
    QMessageBox.information(parent_widget, "PDF", "فایلِ PDF ذخیره شد.")


def render_preview_pixmap(prepared: dict, page_index: int, px_per_mm: float) -> QPixmap:
    """یک صفحه را به QPixmap می‌کشد — برایِ پیش‌نمایشِ زنده داخلِ صفحه‌یِ
    طراحی (بدونِ نیازِ به QPrinter/دیالوگِ چاپ)."""
    from PySide6.QtGui import QPainter

    page_w_px = int(prepared["page_w_mm"] * px_per_mm)
    page_h_px = int(prepared["page_h_mm"] * px_per_mm)
    pixmap = QPixmap(page_w_px, page_h_px)
    pixmap.fill(Qt.white)
    painter = QPainter(pixmap)
    pages = prepared["pages"]
    if 0 <= page_index < len(pages):
        _paint_page(painter, pages[page_index], prepared, px_per_mm, page_index + 1)
    painter.end()
    return pixmap
