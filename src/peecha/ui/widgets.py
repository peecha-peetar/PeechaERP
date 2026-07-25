"""ویجت‌هایِ اشتراکی بینِ چند صفحه — فیلدِ تاریخِ شمسی (که قبلاً فقط در
journal_entry.py تعریف شده بود، و حالا fiscal_years.py هم به آن نیاز دارد)
و اسپین‌باکسِ صفر-پَدشونده (برایِ کدهایی مثلِ «۰۰۱» که QSpinBoxِ معمولی
صفرهایِ ابتداییِ آن‌ها را بی‌صدا حذف می‌کند) و راهنمایِ فیلدها
(FieldHelpController، طبقِ درخواستِ صریح: مکانیزمی سراسری که هر فرمی
می‌تواند برایِ نمایشِ توضیحِ آموزشیِ هر فیلد — به‌صورتِ پاپ‌آپِ شناور، نه
نوارِ ثابتِ داخلِ فرم — با فوکوس‌گرفتنِ آن به‌کار ببرد)."""

from __future__ import annotations

import datetime

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QLineEdit, QSpinBox, QToolTip, QWidget

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
        text = str(value).zfill(self._digits) if self._digits > 0 else str(value)
        return numerals.to_persian_digits(text)

    def valueFromText(self, text: str) -> int:
        text = numerals.to_ascii_digits(text).strip()
        return int(text) if text else 0

    def validate(self, text: str, pos: int) -> object:
        from PySide6.QtGui import QValidator

        normalized = numerals.to_ascii_digits(text)
        if normalized == "" or normalized.isdigit():
            return (QValidator.State.Acceptable, text, pos)
        return (QValidator.State.Invalid, text, pos)


class FieldHelpController(QObject):
    """راهنمایِ فیلدها به‌صورتِ پاپ‌آپِ شناور (QToolTip) — طبقِ بازخوردِ
    صریح: نسخه‌یِ اولِ این مکانیزم یک نوارِ ثابت داخلِ فرم بود که با
    تغییرِ طولِ متن، ارتفاعش عوض می‌شد و کلِ فیلدهایِ پایین‌ترِ فرم را
    بالا/پایین می‌برد — خیلی آزاردهنده برایِ جابجاییِ کاربر بینِ فیلدها.
    این نسخه به‌جایِ نوارِ داخلِ layout، با فوکوس‌گرفتنِ هر فیلدِ ثبت‌شده
    (کلیک یا Tab) یک QToolTip شناور کنارِ همان فیلد نشان می‌دهد که هیچ
    فضایی از layout نمی‌گیرد و با از‌دست‌رفتنِ فوکوس خودش محو می‌شود.

    با installEventFilter رویِ هر ویجتِ ثبت‌شده کار می‌کند (نه با override
    کردنِ کلاس‌هایِ ویجت)، چون فوکوس‌گرفتن رویِ QLineEdit/QComboBox/
    QCheckBox/QSpinBox و... همه یکسان با QEvent.FocusIn قابلِ‌تشخیص است —
    همین باعث می‌شود این مکانیزم بدونِ تغییر در خودِ فیلدها، در هر فرمی
    قابلِ‌استفاده باشد.

    نکته‌یِ مهم برایِ هر صفحه‌ای که این را استفاده می‌کند: حتماً نمونه را
    رویِ self نگه دارید (مثلاً self._field_help_controller = ...)؛
    installEventFilter به‌تنهایی یک ارجاعِ قویِ پایتونی نمی‌سازد، و بدونِ
    نگه‌داشتنِ صریح، PySide6 این آبجکت را gc می‌کند و رویدادهایِ FocusIn
    بدونِ هیچ خطایی دیگر به eventFilter نمی‌رسند (باگی که در تستِ واقعی
    پیدا شد)."""

    def __init__(self) -> None:
        super().__init__()
        self._help_texts: dict[QWidget, str] = {}

    def register(self, widget: QWidget, text: str) -> None:
        self._help_texts[widget] = text
        widget.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.FocusIn:
            text = self._help_texts.get(watched)
            if text is not None and isinstance(watched, QWidget):
                position = watched.mapToGlobal(watched.rect().bottomLeft())
                QToolTip.showText(position, text, watched)
        elif event.type() == QEvent.FocusOut and watched in self._help_texts:
            QToolTip.hideText()
        return False
