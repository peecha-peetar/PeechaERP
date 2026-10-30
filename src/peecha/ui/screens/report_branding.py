"""لوگو و سربرگ گزارش‌ها — R245: بارگذاری لوگوی شرکت و انتخاب محل آن (راست/چپ/بدون لوگو).

لوگو در سربرگ چاپ/PDF/اکسل همهٔ گزارش‌ها و در قالب‌های حرفه‌ای (Jasper) استفاده می‌شود."""

from __future__ import annotations

import mimetypes

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from peecha import session as app_session
from peecha.services import companies as companies_service
from peecha.ui import theme


class ReportBrandingScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(14)
        title = QLabel("لوگو و سربرگ گزارش‌ها")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        hint = QLabel("لوگوی شرکت در سربرگ چاپ، PDF و اکسل همهٔ گزارش‌ها و در گزارش‌های حرفه‌ای نمایش داده می‌شود. "
                      "تصویر PNG یا JPG تا ۲ مگابایت؛ تصویر با زمینهٔ شفاف بهتر است.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.preview = QLabel("بدون لوگو")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setFixedSize(220, 140)
        self.preview.setFrameShape(QFrame.StyledPanel)
        layout.addWidget(self.preview, alignment=Qt.AlignRight)

        row = QHBoxLayout()
        self.upload_button = QPushButton("انتخاب لوگو…")
        self.upload_button.setObjectName("primaryButton")
        self.upload_button.clicked.connect(self.choose_logo)
        self.remove_button = QPushButton("حذف لوگو")
        self.remove_button.clicked.connect(self.remove_logo)
        row.addWidget(self.upload_button)
        row.addWidget(self.remove_button)
        row.addSpacing(30)
        row.addWidget(QLabel("محل لوگو در گزارش‌ها:"))
        self.position_combo = QComboBox()
        for code, label in companies_service.LOGO_POSITIONS.items():
            self.position_combo.addItem(label, code)
        self.position_combo.currentIndexChanged.connect(self._on_position_changed)
        row.addWidget(self.position_combo)
        row.addStretch(1)
        layout.addLayout(row)
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        layout.addStretch(1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self.position_combo.blockSignals(True)
        self.position_combo.setCurrentIndex(max(0, self.position_combo.findData(companies_service.get_report_logo_position(company_id))))
        self.position_combo.blockSignals(False)
        self._show_preview()

    def _show_preview(self) -> None:
        company_id = self._company_id()
        from peecha.db.base import new_session
        from peecha.db.models.core import Company

        data = None
        if company_id is not None:
            with new_session() as session:
                row = session.get(Company, company_id)
                data = row.logo_image if row is not None else None
        pixmap = QPixmap()
        if data and pixmap.loadFromData(data):
            self.preview.setPixmap(pixmap.scaled(self.preview.size() * 0.9, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("بدون لوگو")
        self.remove_button.setEnabled(bool(data))

    def set_logo_file(self, path: str) -> bool:
        company_id = self._company_id()
        if company_id is None:
            return False
        try:
            with open(path, "rb") as f:
                data = f.read()
            companies_service.set_company_logo(company_id, data, mimetypes.guess_type(path)[0])
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "لوگو", str(exc))
            return False
        theme.set_status_label(self.status_label, "لوگو ذخیره شد.", ok=True)
        self._show_preview()
        return True

    def choose_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "انتخاب لوگو", "", "تصویر (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if path:
            self.set_logo_file(path)

    def remove_logo(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        companies_service.set_company_logo(company_id, None)
        theme.set_status_label(self.status_label, "لوگو حذف شد.", ok=True)
        self._show_preview()

    def _on_position_changed(self) -> None:
        company_id = self._company_id()
        if company_id is not None:
            companies_service.set_report_logo_position(company_id, self.position_combo.currentData())
            theme.set_status_label(self.status_label, "محل لوگو ذخیره شد.", ok=True)
