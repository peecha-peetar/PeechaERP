"""تنظیماتِ Smart Publish -- طبقِ بازخوردِ صریحِ کاربر («امکاناتِ حیاتیِ
PeechaSync -- پردازشِ خودکارِ تصویرِ محصول»): واترمارک، حکِ کدِ/نامِ
کالا، و کیفیتِ WebP -- اِعمالِ واقعی از دکمه‌یِ «پردازشِ هوشمند» در
تبِ مرکزِ رسانه انجام می‌شود."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.services import smart_publish as smart_publish_service
from peecha.ui import theme
from peecha.ui.widgets import LayoutEditMixin

_POSITION_LABELS = {
    "bottom-right": "پایین راست", "bottom-left": "پایین چپ",
    "top-right": "بالا راست", "top-left": "بالا چپ", "center": "وسط",
}
_SOURCE_LABELS = {"item_code": "کدِ کالا", "item_name": "نامِ کالا"}


class SmartPublishSettingsScreen(LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("تنظیماتِ Smart Publish")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        info = QLabel("این تنظیمات هنگامِ زدنِ دکمهٔ «✨ پردازشِ هوشمند» رویِ هر عکسِ تبِ «مرکزِ رسانه» اِعمال می‌شود.")
        info.setWordWrap(True)
        outer.addWidget(info)

        watermark_row = QHBoxLayout()
        self.watermark_preview = QLabel("بدونِ واترمارک")
        self.watermark_preview.setFixedSize(64, 64)
        self.watermark_preview.setStyleSheet("border: 1px solid palette(mid); border-radius: 4px;")
        watermark_row.addWidget(self.watermark_preview)
        watermark_button = QPushButton("🖼️ انتخابِ عکسِ واترمارک")
        watermark_button.clicked.connect(self._choose_watermark)
        watermark_row.addWidget(watermark_button)
        watermark_row.addStretch(1)
        outer.addLayout(watermark_row)

        opacity_row = QHBoxLayout()
        opacity_row.addWidget(QLabel("شفافیتِ واترمارک:"))
        self.opacity_field = QDoubleSpinBox()
        self.opacity_field.setRange(0.0, 1.0)
        self.opacity_field.setSingleStep(0.05)
        opacity_row.addWidget(self.opacity_field)
        opacity_row.addWidget(QLabel("اندازه (نسبت به عرضِ عکس):"))
        self.scale_field = QDoubleSpinBox()
        self.scale_field.setRange(0.02, 1.0)
        self.scale_field.setSingleStep(0.02)
        opacity_row.addWidget(self.scale_field)
        opacity_row.addStretch(1)
        outer.addLayout(opacity_row)

        position_row = QHBoxLayout()
        position_row.addWidget(QLabel("موقعیتِ واترمارک:"))
        self.position_combo = QComboBox()
        for code, label in _POSITION_LABELS.items():
            self.position_combo.addItem(label, code)
        position_row.addWidget(self.position_combo)
        position_row.addStretch(1)
        outer.addLayout(position_row)

        stamp_row = QHBoxLayout()
        self.stamp_checkbox = QCheckBox("حکِ کدِ/نامِ کالا رویِ عکس")
        stamp_row.addWidget(self.stamp_checkbox)
        self.stamp_source_combo = QComboBox()
        for code, label in _SOURCE_LABELS.items():
            self.stamp_source_combo.addItem(label, code)
        stamp_row.addWidget(self.stamp_source_combo)
        stamp_row.addStretch(1)
        outer.addLayout(stamp_row)

        quality_row = QHBoxLayout()
        quality_row.addWidget(QLabel("کیفیتِ WebP:"))
        self.quality_field = QSpinBox()
        self.quality_field.setRange(10, 100)
        quality_row.addWidget(self.quality_field)
        quality_row.addStretch(1)
        outer.addLayout(quality_row)

        save_button = QPushButton("💾 ذخیره")
        save_button.setObjectName("primaryIconButton")
        save_button.clicked.connect(self._save)
        outer.addWidget(save_button)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        outer.addWidget(self.status_label)
        outer.addStretch(1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        settings = smart_publish_service.get_settings(company_id)
        self.opacity_field.setValue(float(settings.watermark_opacity))
        self.scale_field.setValue(float(settings.watermark_scale))
        index = self.position_combo.findData(settings.watermark_position)
        if index >= 0:
            self.position_combo.setCurrentIndex(index)
        self.stamp_checkbox.setChecked(settings.stamp_text_enabled)
        source_index = self.stamp_source_combo.findData(settings.stamp_text_source)
        if source_index >= 0:
            self.stamp_source_combo.setCurrentIndex(source_index)
        self.quality_field.setValue(settings.webp_quality)

        if settings.watermark_storage_key:
            pixmap = QPixmap(settings.watermark_storage_key)
            if not pixmap.isNull():
                self.watermark_preview.setPixmap(pixmap.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.watermark_preview.setText("")
        else:
            self.watermark_preview.setText("بدونِ واترمارک")

    def _choose_watermark(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        path, _filter = QFileDialog.getOpenFileName(self, "انتخابِ عکسِ واترمارک", "", "تصاویر (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        try:
            smart_publish_service.set_watermark_image(company_id, path)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()

    def _save(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        try:
            smart_publish_service.set_settings(
                company_id,
                watermark_opacity=decimal.Decimal(str(self.opacity_field.value())),
                watermark_scale=decimal.Decimal(str(self.scale_field.value())),
                watermark_position=self.position_combo.currentData(),
                stamp_text_enabled=self.stamp_checkbox.isChecked(),
                stamp_text_source=self.stamp_source_combo.currentData(),
                webp_quality=self.quality_field.value(),
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        theme.set_status_label(self.status_label, "تنظیماتِ Smart Publish ذخیره شد.", ok=True)
