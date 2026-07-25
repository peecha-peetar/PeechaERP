"""ویجت‌هایِ اشتراکی بینِ چند صفحه — فیلدِ تاریخِ شمسی (که قبلاً فقط در
journal_entry.py تعریف شده بود، و حالا fiscal_years.py هم به آن نیاز دارد)
و اسپین‌باکسِ صفر-پَدشونده (برایِ کدهایی مثلِ «۰۰۱» که QSpinBoxِ معمولی
صفرهایِ ابتداییِ آن‌ها را بی‌صدا حذف می‌کند) و راهنمایِ فیلدها
(FieldHelpController + FieldHelpPanel، طبقِ درخواستِ صریح: مکانیزمی
سراسری که هر فرمی می‌تواند برایِ نمایشِ توضیحِ آموزشیِ هر فیلد با
فوکوس‌گرفتنِ آن به‌کار ببرد. نسخه‌یِ اول یک نوارِ ثابتِ داخلِ فرم بود
(ارتفاعِ فرم را عوض می‌کرد)، نسخه‌یِ دوم QToolTip بود (طبقِ بازخوردِ کاربر
در محیطِ واقعی اصلاً نمایش داده نمی‌شد)؛ این نسخه یک پنجره‌یِ مستقلِ کوچکِ
خودش‌دار است، ثابت در گوشه‌یِ صفحه‌نمایش، با چک‌باکسی برایِ خاموش/
روشن‌کردنِ کلی — پس همیشه قابلِ‌مشاهده و هم قابلِ‌تنظیم است)."""

from __future__ import annotations

import datetime

from PySide6.QtCore import QEvent, QObject, QSettings, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

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


class FieldHelpPanel(QFrame):
    """کادرِ سراسریِ راهنمایِ فیلدها — یک ویجتِ روکار (overlay)، ثابت در
    گوشه‌یِ پنجره‌یِ اصلی (نه وابسته به layoutِ هیچ فرمی)، که با
    فوکوس‌گرفتنِ هر فیلدِ ثبت‌شده متنِ راهنمایِ همان فیلد را نشان می‌دهد.

    طبقِ بازخوردِ کاربر: نسخه‌یِ اول از QToolTip استفاده می‌کرد که در
    محیطِ واقعیِ کاربر اصلاً نمایش داده نمی‌شد. بررسی نشان داد QToolTip
    (و بعد eventFilter+QEvent.FocusIn هم) به‌طورِ کلی روی فوکوس‌هایی که
    بدونِ رویدادِ ماوس اتفاق می‌افتند، غیرِقابلِ‌اتکا هستند. تلاشِ بعدی —
    یک پنجره‌یِ کاملاً مستقل (Qt.Tool) — باگِ بدترِ دیگری آشکار کرد: حتی با
    WindowDoesNotAcceptFocus، آن پنجره خودش app.activeWindow() می‌شد و
    پنجره‌یِ اصلی را از حالتِ فعال می‌انداخت — و چون Qt فوکوسِ ویجت‌هایِ
    پنجره‌یِ غیرِفعال را دنبال نمی‌کند، هیچ رویدادِ فوکوسی اصلاً به گوشِ
    برنامه نمی‌رسید (همان چیزی که کاربر «هیچی نشون نمیده» گزارش داد).

    راه‌حلِ نهایی: این کادر اصلاً پنجره‌یِ جدا نیست — یک QWidgetِ معمولیِ
    فرزندِ خودِ پنجره‌یِ اصلی است (بدونِ عضویت در هیچ layout)، با move() در
    گوشه‌یِ آن جا می‌گیرد و با raise_() همیشه رویِ سایرِ ویجت‌ها می‌ماند.
    چون پنجره‌یِ جداگانه‌ای نیست، هیچ‌وقت رویِ فوکوس/فعال‌بودنِ پنجره‌یِ
    اصلی اثر نمی‌گذارد. یک چک‌باکسِ «نمایش» هم دارد که با آن می‌شود کلاً
    خاموشش کرد؛ وضعیت با QSettings ذخیره و در اجراهایِ بعدی هم حفظ
    می‌شود.

    یک نمونه‌یِ سراسریِ Singleton (از طریقِ FieldHelpPanel.instance(parent))
    برایِ کلِ برنامه کافی است — هر صفحه‌ای که فیلدهایش را با
    FieldHelpController ثبت کند، همین یک کادر را به‌روزرسانی می‌کند."""

    _instance: "FieldHelpPanel | None" = None
    _SETTINGS_KEY = "field_help/enabled"
    _PLACEHOLDER = "برایِ دیدنِ راهنمایِ هر فیلد، رویِ آن کلیک کنید یا با کلیدِ Tab به آن بروید."

    @classmethod
    def instance(cls, parent: QWidget) -> "FieldHelpPanel":
        if cls._instance is None:
            cls._instance = cls(parent)
        elif cls._instance.parentWidget() is not parent:
            cls._instance.setParent(parent)
        return cls._instance

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("fieldHelpPanel")
        self.setFixedWidth(300)
        self.setStyleSheet(
            "#fieldHelpPanel { background: #1f2a3c; border: 1px solid #3a4a63; border-radius: 10px; }"
            "#fieldHelpPanel QLabel { color: #e7ecf3; }"
            "#fieldHelpPanel QCheckBox { color: #b8c4d6; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 12)
        outer.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("راهنمایِ فیلد")
        title.setStyleSheet("font-weight: bold;")
        header.addWidget(title)
        header.addStretch(1)
        self._settings = QSettings("Peecha", "PeechaERP")
        is_enabled = bool(self._settings.value(self._SETTINGS_KEY, True, type=bool))
        self.enabled_checkbox = QCheckBox("نمایش")
        self.enabled_checkbox.setChecked(is_enabled)
        self.enabled_checkbox.toggled.connect(self._on_toggle)
        header.addWidget(self.enabled_checkbox)
        outer.addLayout(header)

        self.text_label = QLabel(self._PLACEHOLDER)
        self.text_label.setWordWrap(True)
        outer.addWidget(self.text_label)

        self._active = False
        parent.installEventFilter(self)

    def _on_toggle(self, checked: bool) -> None:
        self._settings.setValue(self._SETTINGS_KEY, checked)
        self._sync_visibility()

    def is_enabled(self) -> bool:
        return self.enabled_checkbox.isChecked()

    def activate(self) -> None:
        """صدا زده می‌شود وقتی صفحه‌ای که از این راهنما استفاده می‌کند نمایان می‌شود."""
        self._active = True
        self.text_label.setText(self._PLACEHOLDER)
        self._sync_visibility()

    def deactivate(self) -> None:
        """صدا زده می‌شود وقتی از صفحه خارج می‌شویم — کادر پنهان می‌شود تا متنِ
        قدیمی رویِ صفحه‌یِ بعدی باقی نماند."""
        self._active = False
        self._sync_visibility()

    def show_text(self, text: str) -> None:
        self.text_label.setText(text)
        self._sync_visibility()

    def _sync_visibility(self) -> None:
        if self._active and self.is_enabled():
            self._reposition()
            self.show()
            self.raise_()
        else:
            self.hide()

    def eventFilter(self, watched: QObject, event) -> bool:
        # با تغییرِ اندازه‌یِ پنجره‌یِ اصلی (مثلاً ماکسیمایز)، جایگاهِ گوشه
        # باید دوباره محاسبه شود.
        if watched is self.parentWidget() and event.type() == QEvent.Resize and self.isVisible():
            self._reposition()
        return False

    def _reposition(self) -> None:
        # گوشه‌یِ پایین-چپِ پنجره‌یِ اصلی: طبقِ درخواستِ صریح، جایی ثابت
        # (نه وابسته به فرم)، دورتر از نوارِ ناوبریِ سمتِ راست.
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        margin = 20
        x = margin
        y = parent.height() - self.height() - margin
        self.move(x, y)


class FieldHelpController(QObject):
    """با QApplication.focusChanged کار می‌کند — نه installEventFilter/
    QEvent.FocusIn. طبقِ یک باگِ واقعیِ کشف‌شده در دیباگ: با ردیابیِ مستقیمِ
    eventFilter مشخص شد که QEvent.FocusIn هرگز به eventFilterِ ویجت‌هایِ
    ثبت‌شده نمی‌رسد (نه‌فقط در محیطِ headless تست، بلکه همین دلیلِ گزارشِ
    کاربر بود که «چیزی نشون نمیده» — احتمالاً چون setFocus() وقتی پنجره از
    نظرِ سیستم‌عامل «فعال/Active» نیست، رویدادِ FocusIn را هم‌زمان تحویل
    نمی‌دهد). سیگنالِ سراسریِ QApplication.focusChanged اما با هر تغییرِ
    فوکوس در کلِ برنامه — صرفِ‌نظر از وضعیتِ فعال‌بودنِ پنجره — قابلِ‌اتکا
    fire می‌شود؛ همین باعث می‌شود این مکانیزم بدونِ تغییر در خودِ فیلدها،
    در هر فرمی قابلِ‌استفاده باشد.

    نکته‌یِ مهم برایِ هر صفحه‌ای که این را استفاده می‌کند: حتماً نمونه را
    رویِ self نگه دارید (مثلاً self._field_help_controller = ...) تا
    PySide6 پیش از موعد gc‌اش نکند."""

    def __init__(self, panel: FieldHelpPanel) -> None:
        super().__init__()
        self._panel = panel
        self._help_texts: dict[QWidget, str] = {}
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_focus_changed)

    def register(self, widget: QWidget, text: str) -> None:
        self._help_texts[widget] = text

    def _on_focus_changed(self, old: QWidget | None, new: QWidget | None) -> None:
        if new is None:
            return
        text = self._help_texts.get(new)
        if text is not None:
            self._panel.show_text(text)
