"""چاپِ برچسبِ بارکد — طبقِ درخواستِ صریح («برایِ کالا و متغیرها هم بارکدِ
ترکیبی ایجاد و پرینت گرفت»). چون برچسبِ بارکد نیازمندِ رسمِ دقیقِ میله‌هاست
(نه HTML/QTextDocument که برایِ گزارش‌هایِ متنی در report_export.py
استفاده می‌شود)، این‌جا مستقیماً با QPainter رسم می‌شود -- بدونِ هیچ
وابستگیِ بیرونی، از رویِ الگویِ ۹۵بیتیِ ean13.encode."""

from __future__ import annotations

from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QPageLayout, QPainter
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import QDialog, QWidget

from peecha import ean13

_LABEL_WIDTH_MM = 60.0
_LABEL_HEIGHT_MM = 32.0
_LABEL_MARGIN_MM = 2.0
_PAGE_MARGIN_MM = 6.0


def _mm_to_px(printer: QPrinter, value_mm: float) -> float:
    return value_mm * printer.resolution() / 25.4


def _draw_one_label(painter: QPainter, rect: QRectF, title: str, subtitle: str, barcode: str) -> None:
    inner = rect.adjusted(2, 2, -2, -2)
    title_h = inner.height() * 0.16
    subtitle_h = inner.height() * 0.14
    text_h = inner.height() * 0.12
    bars_h = inner.height() - title_h - subtitle_h - text_h

    center_flags = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
    painter.drawText(
        QRectF(inner.left(), inner.top(), inner.width(), title_h), int(center_flags), title,
    )
    if subtitle:
        painter.drawText(
            QRectF(inner.left(), inner.top() + title_h, inner.width(), subtitle_h), int(center_flags), subtitle,
        )

    bits = ean13.encode(barcode)
    bar_top = inner.top() + title_h + subtitle_h
    bar_area_width = inner.width()
    bar_unit_width = bar_area_width / len(bits)
    x = inner.left()
    for bit in bits:
        if bit == "1":
            painter.fillRect(QRectF(x, bar_top, bar_unit_width, bars_h), Qt.GlobalColor.black)
        x += bar_unit_width

    spaced_digits = " ".join(barcode)
    painter.drawText(
        QRectF(inner.left(), bar_top + bars_h, inner.width(), text_h), int(center_flags), spaced_digits,
    )


def print_barcode_labels(
    parent_widget: QWidget | None,
    labels: list[tuple[str, str, str]],
    output_pdf_path: str | None = None,
) -> bool:
    """چاپِ یک یا چند برچسبِ بارکد. هر عضوِ labels یک سه‌تایی است: (عنوان
    -- مثلاً نامِ کالا، زیرعنوان -- مثلاً ترکیبِ ویژگی‌ها، بارکدِ ۱۳رقمی).
    اگر output_pdf_path داده شود مستقیم به فایل نوشته می‌شود (برایِ تستِ
    خودکار/ذخیره‌یِ مستقیم)؛ در غیرِ این صورت دیالوگِ چاپِ استانداردِ سیستم
    باز می‌شود. خروجی True یعنی چاپ/ذخیره انجام شد."""
    if not labels:
        return False

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    if output_pdf_path:
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(output_pdf_path)
    else:
        dialog = QPrintDialog(printer, parent_widget)
        if dialog.exec() != QDialog.Accepted:
            return False

    printer.setPageMargins(
        QMarginsF(_PAGE_MARGIN_MM, _PAGE_MARGIN_MM, _PAGE_MARGIN_MM, _PAGE_MARGIN_MM), QPageLayout.Unit.Millimeter
    )

    page_rect_px = printer.pageRect(QPrinter.Unit.DevicePixel)
    label_w_px = _mm_to_px(printer, _LABEL_WIDTH_MM)
    label_h_px = _mm_to_px(printer, _LABEL_HEIGHT_MM)
    margin_px = _mm_to_px(printer, _LABEL_MARGIN_MM)
    cols = max(1, int(page_rect_px.width() // (label_w_px + margin_px)))
    rows = max(1, int(page_rect_px.height() // (label_h_px + margin_px)))
    per_page = cols * rows

    painter = QPainter()
    if not painter.begin(printer):
        return False
    try:
        for index, (title, subtitle, barcode) in enumerate(labels):
            position_in_page = index % per_page
            if index and position_in_page == 0:
                printer.newPage()
            col = position_in_page % cols
            row = position_in_page // cols
            x = col * (label_w_px + margin_px)
            y = row * (label_h_px + margin_px)
            _draw_one_label(painter, QRectF(x, y, label_w_px, label_h_px), title, subtitle, barcode)
    finally:
        painter.end()
    return True
