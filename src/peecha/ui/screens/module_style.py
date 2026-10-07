"""R274: ظاهرِ یکسانِ صفحه‌هایِ تولید/دارایی/بها با فرم‌هایِ خرید و فروش.

همان اجزایِ موجود (SummaryCard، دکمه‌هایِ آیکونیِ iconButton/primaryIconButton با تول‌تیپ، کارتِ سرِ صفحه
و نوارِ دکمه‌هایِ پایینِ فرم) -- منطقِ صفحه‌ها دست نمی‌خورد، فقط ظاهر.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from peecha.ui.widgets import SummaryCard, SummaryCardBar

# برچسبِ دکمه ← (آیکن، نوع)؛ برچسب به تول‌تیپ می‌رود
ICONS: dict[str, tuple[str, str]] = {
    # عمومی
    "ذخیره": ("💾", "primary"), "ذخیرهٔ سیاست‌ها": ("💾", "primary"), "ویرایش": ("✏️", ""), "به‌روزرسانی": ("🔄", ""),
    "پیش‌نمایش": ("👁️", ""), "محاسبه": ("🧮", ""), "تأیید": ("✅", ""), "بررسی": ("🔍", ""), "ثبت": ("📌", "primary"),
    "برگشت": ("↩️", ""), "بازگشایی": ("🔓", ""), "لغو": ("🚫", "danger"), "پیش‌فرض": ("⭐", ""), "بایگانی": ("🗄️", ""),
    # دستورِ تولید
    "دستورِ جدید": ("🆕", ""), "ویزاردِ تولید": ("🧙", "primary"), "صدور": ("📤", ""), "رزروِ مواد": ("📌", ""),
    "شروعِ تولید": ("▶️", ""), "توقف": ("⏸️", ""), "ادامه": ("⏯️", ""), "ثبتِ مصرف": ("📦", ""),
    "مصرفِ کاملِ استاندارد": ("📥", ""), "برگشتِ مواد": ("↪️", ""), "ثبتِ ضایعات": ("♻️", ""), "ثبتِ دستمزد": ("👷", ""),
    "ثبتِ ساعتِ ماشین": ("⚙️", ""), "ثبتِ تولید": ("🏭", "primary"), "برگشتِ تولید": ("⏪", ""),
    "اتمامِ تولید": ("🏁", "primary"), "بستنِ دستور": ("🔒", ""), "دستورِ نیمه‌ساخته‌ها": ("🧱", ""),
    # اطلاعاتِ پایه
    "نرخِ دستمزدِ جدید": ("💵", ""), "عملیاتِ استاندارد": ("🛠️", ""), "مرکزِ کاریِ جدید": ("🏗️", ""), "اتصالِ ماشین": ("🔌", ""),
    "مسیرِ جدید": ("🧭", ""), "افزودنِ عملیات": ("➕", ""), "حذفِ عملیات": ("🗑️", "danger"), "نسخهٔ جدید": ("🆕", ""),
    "کپی به نسخهٔ جدید": ("📋", ""), "افزودنِ جزء": ("➕", ""), "حذفِ جزء": ("🗑️", "danger"), "جانبی/مشترک": ("🔀", ""),
    "انفجارِ چندسطحی": ("🌳", ""), "مشخصاتِ تولیدیِ کالا": ("🏷️", ""),
    # برنامه‌ریزی
    "اجرایِ MRP": ("🧠", "primary"), "تبدیلِ پیشنهادهایِ انتخاب‌شده": ("🔁", ""), "برنامهٔ جدید": ("🆕", ""),
    "افزودنِ ردیف": ("➕", ""), "از سفارش‌هایِ فروش": ("🛒", ""), "از حداقلِ موجودی": ("📉", ""),
    "تبدیل به دستورِ تولید": ("🏭", ""),
    # بهایِ تولید
    "بستنِ دوره": ("🔒", ""), "ثبت به‌عنوانِ بهایِ استاندارد": ("📏", ""), "استخرِ هزینهٔ جدید": ("🪣", ""),
    "پیش‌نمایشِ سرشکن": ("👁️", ""), "سرشکن": ("➗", ""),
    # دارایی
    "ثبتِ دارایی": ("🆕", "primary"), "سرمایه‌ای‌کردن": ("🏗️", ""), "انتقال": ("🚚", ""), "محاسبهٔ استهلاک": ("🧮", ""),
    "افزایشِ سرمایه / تعمیر": ("🔧", ""), "کاهشِ ارزش": ("📉", ""), "تجدیدِ ارزیابی": ("📈", ""), "فروش": ("💰", ""),
    "اسقاط": ("🗑️", "danger"), "تغییرِ طبقه": ("🗂️", ""), "ثبتِ کارکرد": ("⏱️", ""), "برچسبِ QR": ("🔳", ""),
    "دفترِ دارایی": ("📒", ""), "افزودنِ مدرک": ("📎", ""), "پروژهٔ جدید": ("🆕", ""), "ثبتِ هزینه": ("🧾", ""),
    "مصرفِ مواد از انبار": ("📦", ""), "تبدیل به دارایی": ("🏗️", ""), "شمارشِ جدید": ("🆕", ""), "بستنِ شمارش": ("🔒", ""),
    "افزودنِ گروه": ("➕", ""), "افزودنِ محل": ("📍", ""), "طبقهٔ جدید": ("🆕", ""), "محلِ جدید": ("🆕", ""), "ذخیرهٔ محل": ("💾", "primary"), "ذخیرهٔ گروه": ("💾", "primary"),
    "گروهِ جدید": ("🆕", ""),
    # بهایِ تمام‌شده
    "ثبتِ بهایِ جایگزینی": ("💾", "primary"), "اجرایِ بازمحاسبه": ("🔁", "primary"),
}
_OBJECT_NAMES = {"primary": "primaryIconButton", "danger": "dangerIconButton", "": "iconButton"}


def style_button(button: QPushButton, label: str | None = None) -> QPushButton:
    """دکمهٔ متنی ← دکمهٔ آیکونیِ هم‌شکلِ فرم‌هایِ خرید/فروش (برچسب در تول‌تیپ)."""
    label = label or button.text()
    glyph, kind = ICONS.get(label, ("", ""))
    if not glyph:
        if not button.objectName():
            button.setObjectName("primaryButton")
        return button
    extra = button.toolTip()
    button.setText(glyph)
    button.setToolTip(label + (f" -- {extra}" if extra and extra != label else ""))
    button.setAccessibleName(label)
    button.setProperty("label", label)
    button.setObjectName(_OBJECT_NAMES[kind])
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


def apply(root: QWidget) -> None:
    """همهٔ دکمه‌هایِ متنیِ صفحه (و زیرتب‌ها) را هم‌شکلِ ماژول‌هایِ قبلی می‌کند."""
    for button in root.findChildren(QPushButton):
        text = button.text()
        if text and (text in ICONS or not button.objectName()) and len(text) > 2:
            style_button(button)
            button.style().unpolish(button)
            button.style().polish(button)


def summary(specs: list[tuple[str, str, str, str]], per_row: int = 4) -> tuple[QWidget, dict[str, QLabel]]:
    """[(کلید، عنوان، نقش، آیکن)] ← کارت‌هایِ رنگیِ خلاصه (مثلِ «جمعِ کل» فاکتور)، و کلید ← برچسبِ مقدار."""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    values: dict[str, QLabel] = {}
    for start in range(0, len(specs), per_row):
        cards = {}
        for key, title, role, icon in specs[start:start + per_row]:
            card = SummaryCard(title, role=role, icon=icon)
            card.value_label.setText("—")
            card.value_label.setWordWrap(True)
            cards[key] = card
            values[key] = card.value_label
        layout.addWidget(SummaryCardBar(cards))
    return box, values


def header_card(*widgets: QWidget) -> QWidget:
    """ردیفِ عنوان/جستجو/فیلتر در کارت (مثلِ سرِ فرمِ سند)."""
    card = QWidget()
    card.setObjectName("card")
    row = QHBoxLayout(card)
    row.setContentsMargins(10, 6, 10, 6)
    row.setSpacing(8)
    for w in widgets:
        row.addWidget(w)
    return card


def footer(groups: list[list[QPushButton]]) -> QWidget:
    """نوارِ دکمه‌هایِ آیکونیِ پایینِ فرم، گروه‌ها با جداکننده (مثلِ فوترِ فاکتور)."""
    bar = QWidget()
    bar.setObjectName("card")
    row = QHBoxLayout(bar)
    row.setContentsMargins(8, 6, 8, 6)
    row.setSpacing(6)
    for index, group in enumerate(groups):
        if index:
            line = QFrame()
            line.setFrameShape(QFrame.VLine)
            line.setFrameShadow(QFrame.Sunken)
            row.addWidget(line)
        for button in group:
            style_button(button)
            row.addWidget(button)
    row.addStretch(1)
    return bar


def styled(cls):
    """دکوراتورِ کلاسِ صفحه: پس از ساخت، apply رویِ کلِ صفحه."""
    original = cls.__init__

    def __init__(self, *args, **kwargs):
        original(self, *args, **kwargs)
        apply(self)

    cls.__init__ = __init__
    return cls
