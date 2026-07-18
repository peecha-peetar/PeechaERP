"""نقطه‌ی ورود اپ Kivy/KivyMD — پوسته‌ی اولیه‌ی «پیچا».

فعلاً فقط صفحه‌ی ورود را نشان می‌دهد؛ ScreenManager و صفحات بعدی (پوسته‌ی
اصلی با ناوبری ماژول‌ها طبق docs/ui-ux-guidelines.md بخش ۵) در قدم بعدی
اضافه می‌شوند.
"""

from __future__ import annotations

import os

from kivy.core.text import LabelBase
from kivy.lang import Builder
from kivy.uix.floatlayout import FloatLayout
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
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
        font_missing = self.font_name == "Roboto"
        if font_missing:
            print(
                f"[peecha] WARNING: Vazirmatn font not found at {_VAZIRMATN_REGULAR} "
                "-- Persian text will render as empty boxes. See assets/fonts/README.md."
            )

        self.theme_cls.theme_style = "Light"  # طبق docs/ui-ux-guidelines.md بخش ۳؛ سوییچ تیره در قدم بعدی
        self.theme_cls.primary_palette = "Blue"
        self._apply_font_to_theme_styles()

        # استایل مرکزی (PLabel/PTextField/...) باید قبل از هر kv صفحه‌ای Builder
        # شود، وگرنه صفحاتی که از این کلاس‌ها استفاده می‌کنند خطای «کلاس ناشناخته» می‌گیرند.
        # import قبل از Builder.load_file لازم است تا PTextField در Factory ثبت شده باشد.
        import peecha.ui.widgets  # noqa: F401,PLC0415

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

        if not font_missing:
            return screen_manager

        # اگر فونت پیدا نشد، یک نوار هشدار انگلیسی (نه فارسی — چون خودِ فارسی
        # هم بدون این فونت جعبه‌ی خالی می‌شود) بالای همه‌ی صفحات ثابت می‌ماند،
        # تا وقتی کاربر می‌بیند «چرا فارسی درست نیست»، پاسخش تضمینی خوانا باشد.
        root = FloatLayout()
        root.add_widget(screen_manager)
        warning_bar = MDBoxLayout(
            size_hint=(1, None),
            height="48dp",
            pos_hint={"top": 1},
        )
        warning_bar.md_bg_color = (0.75, 0.15, 0.15, 1)
        warning_bar.add_widget(
            MDLabel(
                text=(
                    "Persian font not found - Persian text below is boxes, not a bug.\n"
                    "Copy Vazirmatn-Regular.ttf + Vazirmatn-Bold.ttf into assets/fonts/ and restart. "
                    "See assets/fonts/README.md."
                ),
                halign="center",
                theme_text_color="Custom",
                text_color=(1, 1, 1, 1),
            )
        )
        root.add_widget(warning_bar)
        return root


def main() -> None:
    PeechaApp().run()


if __name__ == "__main__":
    main()
