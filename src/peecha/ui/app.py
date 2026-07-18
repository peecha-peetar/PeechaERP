"""نقطه‌ی ورود اپ Kivy/KivyMD — پوسته‌ی اولیه‌ی «پیچا».

فعلاً فقط صفحه‌ی ورود را نشان می‌دهد؛ ScreenManager و صفحات بعدی (پوسته‌ی
اصلی با ناوبری ماژول‌ها طبق docs/ui-ux-guidelines.md بخش ۵) در قدم بعدی
اضافه می‌شوند.
"""

from __future__ import annotations

import os

from kivy.core.text import LabelBase
from kivymd.app import MDApp
from kivymd.uix.screenmanager import MDScreenManager

_ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "assets",
)
_FONT_DIR = os.path.join(_ASSETS_DIR, "fonts")
_VAZIRMATN_REGULAR = os.path.join(_FONT_DIR, "Vazirmatn-Regular.ttf")
_VAZIRMATN_BOLD = os.path.join(_FONT_DIR, "Vazirmatn-Bold.ttf")


def _register_persian_font() -> str:
    """فونت Vazirmatn را اگر موجود باشد ثبت می‌کند، وگرنه به فونت پیش‌فرض
    KivyMD برمی‌گردد (که گلیف فارسی ندارد — طبق assets/fonts/README.md)."""
    if os.path.exists(_VAZIRMATN_REGULAR):
        LabelBase.register(
            name="Vazirmatn",
            fn_regular=_VAZIRMATN_REGULAR,
            fn_bold=_VAZIRMATN_BOLD if os.path.exists(_VAZIRMATN_BOLD) else _VAZIRMATN_REGULAR,
        )
        return "Vazirmatn"
    return "Roboto"


class PeechaApp(MDApp):
    font_name = "Roboto"  # در build() با نتیجه‌ی _register_persian_font جایگزین می‌شود

    def build(self):
        self.font_name = _register_persian_font()
        if self.font_name == "Roboto":
            print(
                "[peecha] هشدار: فونت Vazirmatn پیدا نشد "
                f"({_VAZIRMATN_REGULAR}) — متن فارسی درست نمایش داده نمی‌شود. "
                "طبق assets/fonts/README.md فونت را دانلود کنید."
            )

        self.theme_cls.theme_style = "Light"  # طبق docs/ui-ux-guidelines.md بخش ۳؛ سوییچ تیره در قدم بعدی
        self.theme_cls.primary_palette = "Blue"

        from peecha.ui.screens.login import LoginScreen  # noqa: PLC0415 (بعد از ثبت فونت import می‌شود)

        screen_manager = MDScreenManager()
        screen_manager.add_widget(LoginScreen())
        return screen_manager


def main() -> None:
    PeechaApp().run()


if __name__ == "__main__":
    main()
