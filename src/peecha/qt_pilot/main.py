"""نقطه‌ی ورودِ نمونه‌ی آزمایشیِ Qt6.

اجرا: python -m peecha.qt_pilot.main
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from peecha.qt_pilot import theme

_ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "assets",
)
_FONT_DIR = os.path.join(_ASSETS_DIR, "fonts")
_VAZIRMATN_REGULAR = os.path.join(_FONT_DIR, "Vazirmatn-Regular.ttf")
_VAZIRMATN_BOLD = os.path.join(_FONT_DIR, "Vazirmatn-Bold.ttf")

_font_family_cache: str | None = None


def get_font_family() -> str:
    """نامِ خانواده‌ی فونتِ ثبت‌شده — برایِ صفحاتی (مثلِ صفحه‌ی ورودِ بعدِ
    خروج) که بعد از build اولیه هم به آن نیاز دارند."""
    global _font_family_cache
    if _font_family_cache is None:
        _font_family_cache = _register_font()
    return _font_family_cache


def _register_font() -> str:
    """فونتِ Vazirmatn را (اگر موجود باشد) ثبت می‌کند و نامِ خانواده‌ی
    واقعی‌اش را برمی‌گرداند؛ وگرنه فونتِ پیش‌فرضِ سیستم را نگه می‌دارد —
    برخلافِ Kivy، Qt خودش برایِ گلیفِ فارسی به فونتِ سیستم (که معمولاً
    پشتیبانی دارد) بازمی‌گردد، پس نبودِ این فونت اینجا کرش/جعبه‌ی خالی
    نمی‌سازد، فقط ظاهرِ فونت را عوض می‌کند."""
    if os.path.exists(_VAZIRMATN_REGULAR):
        font_id = QFontDatabase.addApplicationFont(_VAZIRMATN_REGULAR)
        if os.path.exists(_VAZIRMATN_BOLD):
            QFontDatabase.addApplicationFont(_VAZIRMATN_BOLD)
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            return families[0]
    return "Tahoma"


def main() -> None:
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)

    font_family = get_font_family()
    app.setFont(QFont(font_family, 11))
    app.setStyleSheet(theme.GLOBAL_QSS)

    from peecha.qt_pilot.login_window import LoginWindow  # noqa: PLC0415

    window = LoginWindow(font_family)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
