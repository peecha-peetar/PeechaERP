"""ویجت‌هایِ اشتراکی بینِ چند صفحه — فیلدِ تاریخِ شمسی (که قبلاً فقط در
journal_entry.py تعریف شده بود، و حالا fiscal_years.py هم به آن نیاز دارد)
و اسپین‌باکسِ صفر-پَدشونده (برایِ کدهایی مثلِ «۰۰۱» که QSpinBoxِ معمولی
صفرهایِ ابتداییِ آن‌ها را بی‌صدا حذف می‌کند)."""

from __future__ import annotations

import datetime

from PySide6.QtWidgets import QLineEdit, QSpinBox

from peecha import numerals


class JalaliDateEdit(QLineEdit):
    """فیلدِ متنیِ تاریخِ شمسی با ارقامِ فارسی — معادلِ رفتارِ تاریخ‌گیرِ
    Kivy (که هم آن یک فیلدِ متنی بود، نه پاپ‌آپِ تقویم)."""

    def __init__(self, placeholder: str = "۱۴۰۳/۰۴/۲۸") -> None:
        super().__init__()
        self.setPlaceholderText(placeholder)
        self._date = datetime.date.today()
        self._refresh_text()
        self.textEdited.connect(self._on_text_edited)
        self.editingFinished.connect(self._on_editing_finished)

    def _refresh_text(self) -> None:
        self.setText(numerals.format_jalali_date(self._date))
        self.setCursorPosition(0)

    def _on_text_edited(self, text: str) -> None:
        converted = numerals.to_persian_digits(numerals.to_ascii_digits(text))
        if converted != text:
            cursor = self.cursorPosition()
            self.setText(converted)
            self.setCursorPosition(cursor)

    def _on_editing_finished(self) -> None:
        try:
            self._date = numerals.parse_jalali_date(self.text())
        except ValueError:
            pass
        self._refresh_text()

    def date(self) -> datetime.date:
        try:
            return numerals.parse_jalali_date(self.text())
        except ValueError:
            return self._date

    def setDate(self, value: datetime.date) -> None:
        self._date = value
        self._refresh_text()


class ZeroPaddedSpinBox(QSpinBox):
    """اسپین‌باکسی که مقدار را با صفرهایِ ابتداییِ متناسب با تعدادِ رقمِ
    تنظیم‌شده نمایش می‌دهد (مثلاً digits=3 -> «۰۰۱»)؛ QSpinBoxِ معمولی چون
    فقط عددِ صحیح را نگه می‌دارد، صفرهایِ ابتداییِ تایپ‌شده را بی‌درنگ حذف
    می‌کند و کدِ سه‌رقمی به یک‌رقمی تبدیل می‌شود — این کلاس با override‌کردنِ
    textFromValue همان مقدار را با طولِ ثابت نمایش می‌دهد."""

    def __init__(self, digits: int = 0) -> None:
        super().__init__()
        self._digits = digits

    def set_digits(self, digits: int) -> None:
        self._digits = digits
        self.lineEdit().setText(self.textFromValue(self.value()))

    def textFromValue(self, value: int) -> str:
        return str(value).zfill(self._digits) if self._digits > 0 else str(value)

    def valueFromText(self, text: str) -> int:
        text = text.strip()
        return int(text) if text else 0
