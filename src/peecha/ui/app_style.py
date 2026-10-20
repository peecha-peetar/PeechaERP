"""R316: استایل پایهٔ برنامه — هر ویجت هنگام polish یک‌بار بررسی می‌شود:
اسپین‌باکس و جدول با ارقام فارسی، دکمهٔ متنی به آیکن. فقط در اجرای واقعی (ui.main) نصب می‌شود."""

from __future__ import annotations

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QComboBox, QDoubleSpinBox, QGroupBox, QHeaderView, QLabel, QProxyStyle, QPushButton, QSpinBox,
    QStyleFactory, QWidget,
)

from peecha.ui import icon_buttons, layout_guard, persian_numbers, touch, ui_text_apply


class AppStyle(QProxyStyle):
    def polish(self, arg):  # noqa: D102
        if isinstance(arg, (QSpinBox, QDoubleSpinBox)):
            persian_numbers.localize_spinbox(arg)
        elif isinstance(arg, QAbstractItemView):
            persian_numbers.localize_view(arg)
        elif isinstance(arg, QPushButton):
            icon_buttons.iconize(arg)
        # عنوان دلخواه/ترجمه بعد از آیکونی‌شدن، تا نگاشت آیکن با متن فارسی اصلی انجام شود
        if isinstance(arg, (QLabel, QAbstractButton, QGroupBox, QHeaderView)):
            ui_text_apply.apply(arg)
        if isinstance(arg, (QAbstractItemView, QComboBox)):
            layout_guard.guard(arg)
        if touch.is_enabled() and isinstance(arg, QWidget):
            touch.prepare(arg)
        return super().polish(arg)


_KEEP: list = []


def install(app, base_style: str = "Fusion") -> None:
    style = AppStyle(QStyleFactory.create(base_style))
    app.setStyle(style)
    # متن‌های خود Qt (دکمه‌های پیام، منوی راست‌کلیک فیلدها) فارسی شوند
    translator = QTranslator(app)
    if translator.load(QLocale(QLocale.Persian, QLocale.Iran), "qtbase", "_",
                       QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(translator)
    _KEEP[:] = [style, translator]
