"""عنوان فیلدها — R316: عنوان دلخواه هر برچسب، گزینه، سرستون و دکمهٔ همهٔ فرم‌ها (نه فقط هفت فرم قبلی)،
که واقعاً هنگام باز شدن فرم‌ها اعمال می‌شود (services.ui_texts + app_style)."""

from __future__ import annotations

from peecha.ui.screens.ui_text_editor import UiTextEditor
from peecha.ui.widgets import FieldHelpMixin


class FieldLabelsScreen(FieldHelpMixin, UiTextEditor):
    def __init__(self) -> None:
        super().__init__("labels")
        self.set_field_help([
            (self.language_combo, "زبانی که عنوان دلخواه برایش ثبت می‌شود؛ معمولاً همان زبان اصلی برنامه."),
            (self.form_search, "بخشی از نام فرم یا منو را بنویسید تا فهرست کوتاه شود."),
            (self.text_search, "جستجو در متن اصلی یا عنوان دلخواه ردیف‌ها."),
            (self.filter_combo, "نمایش همهٔ متن‌ها، فقط آن‌هایی که عنوان دلخواه دارند، یا فقط آن‌هایی که ندارند."),
        ])
