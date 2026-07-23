"""نقطه‌ی ورودِ برنامه‌ی پیچا (Qt6).

اجرا: python -m peecha.ui.main
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from peecha.ui import theme

_ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "assets",
)
_FONT_DIR = os.path.join(_ASSETS_DIR, "fonts")
_IRANSANS_REGULAR = os.path.join(_FONT_DIR, "IRANSans-Regular.ttf")
_IRANSANS_BOLD = os.path.join(_FONT_DIR, "IRANSans-Bold.ttf")
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


def _try_register(regular_path: str, bold_path: str, expected_substring: str) -> str | None:
    """اگر فایلِ فونت موجود باشد، ثبتش می‌کند و نامِ خانواده‌ی واقعی را
    برمی‌گرداند؛ فقط اگر نامِ خانواده واقعاً شاملِ expected_substring باشد
    (وگرنه یعنی فایل placeholder/جعلی است، مثلِ اتفاقی که برایِ
    Vazirmatn افتاد — یک .ttf با این نام اما محتوایِ DejaVu Sans)."""
    if not os.path.exists(regular_path):
        return None
    font_id = QFontDatabase.addApplicationFont(regular_path)
    if os.path.exists(bold_path):
        QFontDatabase.addApplicationFont(bold_path)
    families = QFontDatabase.applicationFontFamilies(font_id)
    if families and expected_substring in families[0].lower():
        return families[0]
    return None


def _register_font() -> str:
    """فونتِ ترجیحی را ثبت می‌کند و نامِ خانواده‌ی واقعی‌اش را برمی‌گرداند؛
    وگرنه فونتِ پیش‌فرضِ سیستم را نگه می‌دارد — برخلافِ Kivy، Qt خودش برایِ
    گلیفِ فارسی به فونتِ سیستم (که معمولاً پشتیبانی دارد) بازمی‌گردد، پس
    نبودِ این فونت‌ها اینجا کرش/جعبه‌ی خالی نمی‌سازد، فقط ظاهرِ فونت را
    عوض می‌کند.

    اولویت: IRANSans (طبقِ استایلِ مرجعِ کاربر) -> Vazirmatn -> Tahoma.
    هر دویِ IRANSans/Vazirmatn قبل از پذیرفته‌شدن با نامِ خانواده‌شان
    اعتبارسنجی می‌شوند (نکته: فایلِ فعلیِ Vazirmatn-Regular.ttf در واقع
    یک placeholder اشتباهاً commit‌شده است، نه فونتِ واقعی — پس عملاً به
    Tahoma برمی‌گردد تا وقتی فایل‌هایِ واقعی جایگزین شوند)."""
    iran_sans = _try_register(_IRANSANS_REGULAR, _IRANSANS_BOLD, "iran")
    if iran_sans:
        return iran_sans
    vazirmatn = _try_register(_VAZIRMATN_REGULAR, _VAZIRMATN_BOLD, "vazir")
    if vazirmatn:
        return vazirmatn
    return "Tahoma"


def main() -> None:
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    # سبکِ پایه‌ی Fusion — تخت و یک‌دست رویِ همه‌ی سیستم‌عامل‌ها؛ بر خلافِ
    # سبکِ بومیِ ویندوز/مک که ظاهرِ کارت/دکمه‌های مدرنِ QSSِ ما را با
    # جلوه‌های پیش‌فرضِ خودش (سایه/حاشیه‌ی متفاوت) قاطی می‌کند.
    app.setStyle("Fusion")

    font_family = get_font_family()
    app.setFont(QFont(font_family, 10.5))
    # علاوه بر QApplication.setFont، فونت را صریحاً در QSS هم می‌گذاریم —
    # بعضی کنترل‌های استایل‌شده (مثلِ سرستونِ جدول) به‌طورِ قابلِ‌اتکا فقط
    # به font-family در stylesheet واکنش نشان می‌دهند، نه setFont برنامه.
    app.setStyleSheet(f'* {{ font-family: "{font_family}"; }}\n' + theme.GLOBAL_QSS)

    from peecha.ui.login_window import LoginWindow  # noqa: PLC0415

    window = LoginWindow(font_family)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
