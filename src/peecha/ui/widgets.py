"""ویجت‌های پایتونی پیچا — برای رفتاری که فقط با خواص KV قابل‌تنظیم نیست.

KivyMD 1.2 برای MDTextField دو لیبل داخلی (hint/helper شناور بالای فیلد)
می‌سازد که halign‌شان مستقیم در کد پایتونِ خودِ KivyMD با "left" هاردکد
شده (`set_objects_labels()` در textfield.py) — هیچ property عمومی برای
override کردنش در KV نیست (فقط فونتشان از طریق font_name_hint_text/
font_name_helper_text قابل‌تنظیم است، نه جهتشان). برای همین این‌جا این دو
لیبل را بعد از ساخته‌شدن مستقیم در پایتون راست‌چین می‌کنیم.
"""

from __future__ import annotations

from kivy.factory import Factory
from kivymd.uix.textfield import MDTextField


class PTextField(MDTextField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        for label_attr in ("_hint_text_label", "_helper_text_label", "_max_length_label"):
            label = getattr(self, label_attr, None)
            if label is not None:
                label.halign = "right"


Factory.register("PTextField", cls=PTextField)
