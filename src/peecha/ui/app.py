"""نقطه‌ی ورود اپ Kivy/KivyMD — پوسته‌ی اولیه‌ی «پیچا».

فعلاً فقط صفحه‌ی ورود را نشان می‌دهد؛ ScreenManager و صفحات بعدی (پوسته‌ی
اصلی با ناوبری ماژول‌ها طبق docs/ui-ux-guidelines.md بخش ۵) در قدم بعدی
اضافه می‌شوند.
"""

from __future__ import annotations

import os

from kivy.core.text import LabelBase
from kivy.lang import Builder
from kivymd.app import MDApp
from kivymd.uix.screenmanager import MDScreenManager

_ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "assets",
)
_FONT_DIR = os.path.join(_ASSETS_DIR, "fonts")
_VAZIRMATN_REGULAR = os.path.join(_FONT_DIR, "Vazirmatn-Regular.ttf")
_VAZIRMATN_BOLD = os.path.join(_FONT_DIR, "Vazirmatn-Bold.ttf")
_WIDGETS_KV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "widgets.kv")


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

    def _apply_font_to_theme_styles(self) -> None:
        """جایگزینی فونت پیش‌فرض در تمام font_style های KivyMD.

        علت: در KivyMD، هر ویجتی که `font_style` دارد (اکثر MDLabel ها،
        و لیبل داخلی MDTextField برای hint_text) هنگام تنظیم font_style
        خودش font_name را از theme_cls.font_styles می‌خواند و override
        می‌کند — یعنی ست‌کردن `font_name` مستقیم روی خودِ ویجت در KV برای
        این‌ها کافی نیست (فقط ویجت‌های بدون font_style مثل دکمه را درست
        نشان می‌دهد). با عوض‌کردن خودِ جدول font_styles، این مشکل برای
        همه‌ی ویجت‌ها یک‌جا حل می‌شود.
        """
        for style_name, style_value in self.theme_cls.font_styles.items():
            style_value[0] = self.font_name

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
        self._apply_font_to_theme_styles()

        # استایل مرکزی (PLabel/PTextField/...) باید قبل از هر kv صفحه‌ای Builder
        # شود، وگرنه صفحاتی که از این کلاس‌ها استفاده می‌کنند خطای «کلاس ناشناخته» می‌گیرند
        Builder.load_file(_WIDGETS_KV_PATH)

        # بعد از ثبت فونت import می‌شوند تا شکل‌دهی/تم روی همه اعمال شده باشد
        from peecha.config import has_saved_settings  # noqa: PLC0415
        from peecha.ui.screens.connection_settings import ConnectionSettingsScreen  # noqa: PLC0415
        from peecha.ui.screens.login import LoginScreen  # noqa: PLC0415

        screen_manager = MDScreenManager()
        screen_manager.add_widget(ConnectionSettingsScreen())
        screen_manager.add_widget(LoginScreen())
        # اولین اجرا (بدون تنظیمات ذخیره‌شده) با فرم اتصال شروع می‌شود؛
        # دفعات بعد مستقیم می‌رود سراغ ورود (تنظیمات از صفحه‌ی ورود هم در دسترس است)
        screen_manager.current = "login" if has_saved_settings() else "connection_settings"
        return screen_manager


def main() -> None:
    PeechaApp().run()


if __name__ == "__main__":
    main()
