"""پیش‌نمایشِ چاپیِ گزارش‌هایِ حرفه‌ای (JasperReports).

به‌جایِ ذخیره‌یِ مستقیمِ PDF از طریقِ یک پنجره‌یِ Save، گزارش ابتدا این‌جا
به‌صورتِ تمام‌صفحه پیش‌نمایش داده می‌شود؛ از همین پنجره می‌توان آن را به
PDF یا Excel ذخیره کرد یا مستقیماً رویِ چاپگر چاپ کرد -- دقیقاً همان سه
گزینه‌ای که پیش‌ازاین یک دیالوگِ Save با انتخابِ فرمت انجام می‌داد، ولی
حالا کاربر قبل از تصمیم‌گیری، خودِ گزارش را می‌بیند."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtPrintSupport import QPrintDialog
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

_ZOOM_STEP = 1.2
_ZOOM_MIN = 0.2
_ZOOM_MAX = 5.0

from peecha.reporting import jasper_bridge


class JasperReportPreviewDialog(QDialog):
    def __init__(
        self, parent, jrxml_path, rows: list[dict], params: dict, default_name: str,
        title: str = "پیش‌نمایشِ گزارش", pdf_path: str | None = None,
    ):
        """اگر pdf_path داده شده باشد (فراخوان خودش از قبل رندر کرده --
        معمولاً چون می‌خواهد در صورتِ خطا به پیش‌نمایشِ HTMLِ قدیمی برگردد
        به‌جایِ نمایشِ این دیالوگِ خالی)، آن فایل مستقیماً بارگذاری می‌شود
        و رندرِ دوباره‌ای انجام نمی‌شود؛ در غیرِ این صورت (کاربردِ معمولِ
        صفحاتِ گزارش) خودِ دیالوگ رندر را انجام می‌دهد."""
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(950, 1050)
        self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

        self._jrxml_path = jrxml_path
        self._rows = rows
        self._params = params
        self._default_name = default_name or "گزارش"
        self._tmp_dir = tempfile.mkdtemp(prefix="peecha_preview_")
        self._pdf_path: str | None = str(Path(self._tmp_dir) / "preview.pdf")

        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self.save_pdf_button = QPushButton("💾 ذخیره‌یِ PDF")
        self.save_excel_button = QPushButton("📊 خروجیِ Excel")
        self.print_button = QPushButton("🖨 چاپ")
        self.zoom_out_button = QPushButton("🔍−")
        self.zoom_out_button.setToolTip("کوچک‌نمایی")
        self.zoom_label = QLabel()
        self.zoom_in_button = QPushButton("🔍+")
        self.zoom_in_button.setToolTip("بزرگ‌نمایی")
        self.fit_width_button = QPushButton("عرضِ صفحه")
        self.close_button = QPushButton("بستن")
        for button in (self.save_pdf_button, self.save_excel_button, self.print_button):
            toolbar.addWidget(button)
        toolbar.addStretch()
        toolbar.addWidget(self.zoom_out_button)
        toolbar.addWidget(self.zoom_label)
        toolbar.addWidget(self.zoom_in_button)
        toolbar.addWidget(self.fit_width_button)
        toolbar.addWidget(self.close_button)
        layout.addLayout(toolbar)

        self._document = QPdfDocument(self)
        self._view = QPdfView(self)
        self._view.setDocument(self._document)
        self._view.setPageMode(QPdfView.PageMode.MultiPage)
        self._view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        layout.addWidget(self._view)

        self.save_pdf_button.clicked.connect(self._save_pdf)
        self.save_excel_button.clicked.connect(self._save_excel)
        self.print_button.clicked.connect(self._print)
        self.zoom_in_button.clicked.connect(self._zoom_in)
        self.zoom_out_button.clicked.connect(self._zoom_out)
        self.fit_width_button.clicked.connect(self._fit_width)
        self.close_button.clicked.connect(self.close)
        self._view.zoomFactorChanged.connect(self._update_zoom_label)
        self._update_zoom_label()

        if pdf_path is not None:
            shutil.copy2(pdf_path, self._pdf_path)
            self._document.load(self._pdf_path)
        else:
            self._render_preview()

    def _zoom_in(self) -> None:
        self._view.setZoomMode(QPdfView.ZoomMode.Custom)
        self._view.setZoomFactor(min(_ZOOM_MAX, self._view.zoomFactor() * _ZOOM_STEP))

    def _zoom_out(self) -> None:
        self._view.setZoomMode(QPdfView.ZoomMode.Custom)
        self._view.setZoomFactor(max(_ZOOM_MIN, self._view.zoomFactor() / _ZOOM_STEP))

    def _fit_width(self) -> None:
        self._view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

    def _update_zoom_label(self) -> None:
        self.zoom_label.setText(f"{round(self._view.zoomFactor() * 100)}٪")

    def _render_preview(self) -> None:
        try:
            jasper_bridge.render_report_at_path(self._jrxml_path, self._rows, self._params, self._pdf_path, "pdf")
        except jasper_bridge.JasperNotAvailableError as exc:
            QMessageBox.warning(self, "گزارش", str(exc))
            self._disable_all()
            return
        except Exception as exc:
            QMessageBox.critical(self, "گزارش", f"تولیدِ گزارش ناموفق بود:\n{exc}")
            self._disable_all()
            return
        self._document.load(self._pdf_path)

    def _disable_all(self) -> None:
        self._pdf_path = None
        self.save_pdf_button.setEnabled(False)
        self.save_excel_button.setEnabled(False)
        self.print_button.setEnabled(False)

    def _save_pdf(self) -> None:
        if not self._pdf_path:
            return
        path, _ = QFileDialog.getSaveFileName(self, "ذخیره‌یِ PDF", f"{self._default_name}.pdf", "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            shutil.copy2(self._pdf_path, path)
        except Exception as exc:
            QMessageBox.critical(self, "گزارش", f"ذخیره‌یِ فایل ناموفق بود:\n{exc}")
            return
        QMessageBox.information(self, "گزارش", "فایل با موفقیت ذخیره شد.")

    def _save_excel(self) -> None:
        if not self._pdf_path:
            return
        path, _ = QFileDialog.getSaveFileName(self, "ذخیره‌یِ Excel", f"{self._default_name}.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            jasper_bridge.render_report_at_path(self._jrxml_path, self._rows, self._params, path, "xlsx")
        except jasper_bridge.JasperNotAvailableError as exc:
            QMessageBox.warning(self, "گزارش", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "گزارش", f"تولیدِ خروجیِ Excel ناموفق بود:\n{exc}")
            return
        QMessageBox.information(self, "گزارش", "فایلِ Excel با موفقیت ذخیره شد.")

    def _print(self) -> None:
        if not self._pdf_path:
            return
        dialog = QPrintDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        printer = dialog.printer()
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.critical(self, "گزارش", "اتصال به چاپگر ناموفق بود.")
            return
        try:
            target_rect = painter.viewport()
            page_count = self._document.pageCount()
            for page_index in range(page_count):
                if page_index > 0:
                    printer.newPage()
                image = self._document.render(page_index, target_rect.size())
                painter.drawImage(target_rect, image)
        finally:
            painter.end()

    def closeEvent(self, event) -> None:
        shutil.rmtree(self._tmp_dir, ignore_errors=True)
        super().closeEvent(event)
