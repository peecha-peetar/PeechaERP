"""ترجمه‌ها — R316: ترجمهٔ منوها و همهٔ متن‌های فرم‌ها (برچسب، گزینه، سرستون، دکمه) به زبان‌های دیگر،
با جستجو، درصد پیشرفت و خروجی/ورود CSV برای ترجمه بیرون از برنامه."""

from __future__ import annotations

from peecha.ui.screens.ui_text_editor import UiTextEditor
from peecha.ui.widgets import FieldHelpMixin


class TranslationsScreen(FieldHelpMixin, UiTextEditor):
    def __init__(self) -> None:
        super().__init__("translate")
        self.set_field_help([
            (self.language_combo, "زبانی که ترجمه می‌کنید. زبان اصلی برنامه اینجا نیست؛ عنوان آن در «عنوان فیلدها» عوض می‌شود."),
            (self.form_search, "بخشی از نام فرم یا منو را بنویسید تا فهرست کوتاه شود."),
            (self.text_search, "جستجو در متن اصلی یا ترجمهٔ ردیف‌ها."),
            (self.filter_combo, "نمایش همهٔ متن‌ها، فقط ترجمه‌شده‌ها، یا فقط آن‌هایی که هنوز ترجمه ندارند."),
        ])
