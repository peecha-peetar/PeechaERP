"""R358: تنظیم سرویس فاصلهٔ جاده‌ای (نشان) برای پیشنهاد مسیر پخش."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from peecha import numerals
from peecha.services import road_distance
from peecha.ui import theme
from peecha.ui.screens.fixed_assets import combo, company_id, set_combo, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName("primaryIconButton" if kind == "primary" else "iconButton")
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


class RoadRoutingSettingsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        title = QLabel("مسیریابی جاده‌ای پخش")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        hint = QLabel("با روشن‌کردن نشان، پیشنهاد ترتیب تحویل در «تیم پخش» با فاصلهٔ جاده‌ای ساخته می‌شود. اگر سرویس در دسترس "
                      "نباشد، همان فاصلهٔ خط مستقیم به کار می‌رود. کلید API را از پنل توسعه‌دهندگان نشان بگیرید؛ کلید رمزشده "
                      "ذخیره می‌شود و نمایش داده نمی‌شود.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.provider_combo = combo([(label, code) for code, label in road_distance.PROVIDERS.items()])
        self.vehicle_combo = combo([(label, code) for code, label in road_distance.VEHICLE_TYPES.items()])
        self.key_field = QLineEdit()
        self.key_field.setEchoMode(QLineEdit.Password)
        self.url_field = QLineEdit()
        self.url_field.setLayoutDirection(Qt.LeftToRight)
        layout.addWidget(FieldGrid([
            FieldSpec("road_provider", "سرویس فاصله", self.provider_combo, span=2),
            FieldSpec("road_vehicle", "نوع وسیله", self.vehicle_combo, span=1),
            FieldSpec("road_api_key", "کلید API", self.key_field, span=2),
            FieldSpec("road_api_url", "آدرس سرویس", self.url_field, span=2),
        ]))
        bar = QHBoxLayout()
        self.save_button = _btn("ذخیرهٔ تنظیمات مسیریابی", "💾", "primary")
        self.test_button = _btn("آزمون اتصال به نشان", "🔌")
        for button, handler in ((self.save_button, self.save), (self.test_button, self.test)):
            button.clicked.connect(handler)
            bar.addWidget(button)
        bar.addStretch(1)
        layout.addLayout(bar)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

    def refresh(self) -> None:
        if company_id() is None:
            return
        s = road_distance.get_settings(company_id())
        set_combo(self.provider_combo, s.provider_code)
        set_combo(self.vehicle_combo, s.vehicle_type)
        self.url_field.setText(s.api_url)
        self.key_field.clear()
        self.key_field.setPlaceholderText("کلید ذخیره شده است؛ برای نگه‌داشتن، خالی بگذارید" if s.has_key else "service.…")
        if s.last_error:
            theme.set_status_label(self.status_label, f"آخرین خطای سرویس ({numerals.format_jalali_datetime(s.last_error_at)}): "
                                                      f"{s.last_error}", ok=False)
        else:
            self.status_label.setText("")

    def save(self) -> bool:
        try:
            road_distance.save_settings(company_id(), user_id(), self.provider_combo.currentData(), self.key_field.text(),
                                        self.url_field.text(), self.vehicle_combo.currentData())
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return False
        self.refresh()
        theme.set_status_label(self.status_label, "ذخیره شد.", ok=True)
        return True

    def test(self) -> bool:
        try:
            km = road_distance.test_connection(company_id())
        except road_distance.RoadDistanceError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return False
        theme.set_status_label(self.status_label, f"اتصال برقرار است؛ مسیر نمونهٔ تهران "
                                                  f"{numerals.to_persian_digits(f'{km:.1f}')} کیلومتر.", ok=True)
        return True
