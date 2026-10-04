"""برچسبِ محلِ انبار -- R248: QR (segno) + بارکدِ Code128 (python-barcode) + کدِ محل، رسم با QPainter
(همان الگویِ barcode_print.py برایِ برچسبِ کالا، بدونِ HTML)."""

from __future__ import annotations

from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPageLayout, QPainter
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import QDialog, QWidget

from peecha.services import warehouse_locations as wl

_LABEL_W_MM, _LABEL_H_MM, _GAP_MM, _PAGE_MARGIN_MM = 70.0, 35.0, 3.0, 6.0


def draw_label(painter: QPainter, rect: QRectF, location_id: int, location_code: str, title: str = "") -> None:
    """QR در یک سو، بارکدِ Code128 و کدِ محل در سویِ دیگر."""
    painter.save()
    painter.setPen(QColor("#000000"))
    inner = rect.adjusted(rect.width() * 0.03, rect.height() * 0.06, -rect.width() * 0.03, -rect.height() * 0.06)
    matrix = wl.qr_matrix(wl.qr_payload(location_id, location_code))
    qr_side = inner.height()
    cell = qr_side / len(matrix)
    for r, row in enumerate(matrix):
        for c, bit in enumerate(row):
            if bit:
                painter.fillRect(QRectF(inner.left() + c * cell, inner.top() + r * cell, cell, cell), Qt.GlobalColor.black)
    text_left = inner.left() + qr_side + inner.width() * 0.04
    text_w = inner.right() - text_left
    font = QFont(painter.font())
    font.setPointSizeF(max(6.0, inner.height() / 9))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRectF(text_left, inner.top(), text_w, inner.height() * 0.22), int(Qt.AlignCenter), location_code)
    if title:
        font.setBold(False)
        font.setPointSizeF(max(5.0, inner.height() / 12))
        painter.setFont(font)
        painter.drawText(QRectF(text_left, inner.top() + inner.height() * 0.22, text_w, inner.height() * 0.16), int(Qt.AlignCenter), title)
    bits = wl.barcode_bits(location_code)
    bar_top, bar_h = inner.top() + inner.height() * 0.42, inner.height() * 0.55
    unit = text_w / len(bits)
    x = text_left
    for bit in bits:
        if bit == "1":
            painter.fillRect(QRectF(x, bar_top, unit, bar_h), Qt.GlobalColor.black)
        x += unit
    painter.restore()


def label_image(location_id: int, location_code: str, title: str = "", dpi: int = 300) -> QImage:
    """تصویرِ یک برچسب (برایِ پیش‌نمایش/ذخیره/تست)."""
    w, h = int(_LABEL_W_MM / 25.4 * dpi), int(_LABEL_H_MM / 25.4 * dpi)
    image = QImage(w, h, QImage.Format_RGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    draw_label(painter, QRectF(0, 0, w, h), location_id, location_code, title)
    painter.end()
    return image


def print_location_labels(parent: QWidget | None, labels: list[tuple[int, str, str]], printer: QPrinter | None = None) -> bool:
    """چاپِ گروهیِ برچسب‌ها رویِ A4 (چند ستون/ردیف). labels: (شناسه، کدِ کامل، عنوان)."""
    if not labels:
        return False
    if printer is None:
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageLayout(QPageLayout(printer.pageLayout().pageSize(), QPageLayout.Portrait,
                                          QMarginsF(_PAGE_MARGIN_MM, _PAGE_MARGIN_MM, _PAGE_MARGIN_MM, _PAGE_MARGIN_MM),
                                          QPageLayout.Millimeter))
        dialog = QPrintDialog(printer, parent)
        if dialog.exec() != QDialog.Accepted:
            return False
    mm = lambda v: v * printer.resolution() / 25.4  # noqa: E731
    page = printer.pageLayout().paintRectPixels(printer.resolution())
    cols = max(1, int((page.width() + mm(_GAP_MM)) // (mm(_LABEL_W_MM) + mm(_GAP_MM))))
    rows = max(1, int((page.height() + mm(_GAP_MM)) // (mm(_LABEL_H_MM) + mm(_GAP_MM))))
    painter = QPainter(printer)
    for i, (location_id, code, title) in enumerate(labels):
        slot = i % (cols * rows)
        if i and slot == 0:
            printer.newPage()
        r, c = divmod(slot, cols)
        rect = QRectF(c * (mm(_LABEL_W_MM) + mm(_GAP_MM)), r * (mm(_LABEL_H_MM) + mm(_GAP_MM)), mm(_LABEL_W_MM), mm(_LABEL_H_MM))
        painter.drawRect(rect)
        draw_label(painter, rect, location_id, code, title)
    painter.end()
    return True
