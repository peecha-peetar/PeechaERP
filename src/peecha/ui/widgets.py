"""ویجت‌هایِ اشتراکی بینِ چند صفحه — فیلدِ تاریخِ شمسی (که قبلاً فقط در
journal_entry.py تعریف شده بود، و حالا fiscal_years.py هم به آن نیاز دارد)
و اسپین‌باکسِ صفر-پَدشونده (برایِ کدهایی مثلِ «۰۰۱» که QSpinBoxِ معمولی
صفرهایِ ابتداییِ آن‌ها را بی‌صدا حذف می‌کند) و راهنمایِ فیلدها
(FieldHelpController + FieldHelpPanel، طبقِ درخواستِ صریح: مکانیزمی
سراسری که هر فرمی می‌تواند برایِ نمایشِ توضیحِ آموزشیِ هر فیلد با
فوکوس‌گرفتنِ آن به‌کار ببرد). سه نسخه امتحان شد تا به فرمِ فعلی رسید:
نوارِ ثابتِ داخلِ فرم (ارتفاعِ فرم را عوض می‌کرد) → QToolTip (در محیطِ
واقعیِ کاربر نمایش داده نمی‌شد) → پنجره‌یِ کاملاً مستقل (باگِ activeWindow
را می‌ساخت) → نسخه‌یِ نهایی: کادرِ روکارِ فرزندِ خودِ پنجره‌یِ اصلی، با
ظاهرِ روشن/رنگی (متفاوت از تمِ تیره‌یِ برنامه) و انیمیشنِ محوشدگی، گوشه‌یِ
بالا-راستِ پنجره؛ کلیدِ روشن/خاموش‌کردنِ کلی (field_help_is_enabled/
set_field_help_enabled) به دکمه‌ای در هدرِ برنامه منتقل شده، نه دیگر
داخلِ خودِ کادر."""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QSettings,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals
from peecha.ui import theme

_FIELD_HELP_SETTINGS_KEY = "field_help/enabled"


def field_help_is_enabled() -> bool:
    """وضعیتِ سراسریِ روشن/خاموشِ کادرِ راهنمایِ فیلدها — مستقل از اینکه
    خودِ FieldHelpPanel تا این لحظه ساخته شده باشد یا نه، چون کلیدِ
    روشن/خاموش‌کردن (در هدرِ برنامه) باید حتی پیش از بازکردنِ اولین
    صفحه‌ای که از راهنما استفاده می‌کند هم قابلِ‌استفاده باشد."""
    settings = QSettings("Peecha", "PeechaERP")
    return bool(settings.value(_FIELD_HELP_SETTINGS_KEY, True, type=bool))


def set_field_help_enabled(value: bool) -> None:
    settings = QSettings("Peecha", "PeechaERP")
    settings.setValue(_FIELD_HELP_SETTINGS_KEY, value)
    if FieldHelpPanel._instance is not None:
        FieldHelpPanel._instance.set_enabled(value)


class FormScreenBase(QWidget):
    """اسکلتِ استانداردِ فرم‌هایِ ورودِ اطلاعات — بدنه‌یِ اسکرول‌شونده +
    نوارِ دکمه‌یِ ثابتِ زیرِ آن (formFooter)، هردو داخلِ یک کارت. طبقِ
    گزارشِ تکراریِ کاربر («فرم‌هایِ جدید اسکرول ندارن»، «دکمه‌هایِ ذخیره
    زیرِ تسک‌بار می‌مونن»): پیش از این کلاس هر فرم این الگو را جداگانه و
    ناقص پیاده می‌کرد (`journal_entry.py` فقط جدول را اسکرول می‌کرد نه
    فوتر را؛ `treasury_voucher.py` اصلاً اسکرول نداشت)، و تنها نمونه‌یِ
    درستِ الگو (`treasury_checks.py`) دستی و بدونِ کلاسِ پایه تکرار شده
    بود. حالا هر فرمِ جدید فقط باید این کلاس را زیرکلاسی کند: بدنه در
    self.body_layout، دکمه‌ها در self.footer_layout.

    اگر این صفحه خودش داخلِ یک QScrollAreaِ دیگر (مثلِ
    system_settings.py::_sub_tabs) قرار می‌گیرد، manages_own_scroll=True
    به آن می‌گوید این ویجت را دوباره نپیچد — وگرنه همین فوترِ «ثابت» هم
    دوباره قابلِ‌اسکرول‌شدن و گم‌شدن می‌شود."""

    manages_own_scroll = True

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        wrapper = QWidget()
        wrapper.setObjectName("card")
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._body = QWidget()
        self.body_layout = QVBoxLayout(self._body)
        self._scroll.setWidget(self._body)
        wrapper_layout.addWidget(self._scroll, stretch=1)

        self.footer = QWidget()
        self.footer.setObjectName("formFooter")
        self.footer_layout = QHBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(18, 12, 18, 14)
        # طبقِ قانونِ ثابتِ چیدمانِ دکمه‌ها («همه‌یِ آیکن‌ها کنارِ هم، سمتِ
        # چپِ پایینِ فرم» — نه فقط رویِ این فرم، در همه‌جا): بدونِ این خط،
        # چون کلِ اپ RTL است (setLayoutDirection در main.py)، یک QHBoxLayout
        # معمولی دکمه‌هایِ اضافه‌شده را از راست به چپ می‌چیند و محلِ نهایی
        # به ترتیبِ کدنویسیِ هر فایل بستگی پیدا می‌کند، نه یک قاعده‌یِ ثابت.
        self.footer_layout.setDirection(QBoxLayout.LeftToRight)
        self.footer_layout.setSpacing(8)
        wrapper_layout.addWidget(self.footer)

        outer.addWidget(wrapper, stretch=1)

    def set_footer_visible(self, visible: bool) -> None:
        self.footer.setVisible(visible)

    def set_footer_buttons(self, buttons: list[QWidget]) -> None:
        """دکمه‌هایِ فوتر را با ترتیبِ چپ‌به‌راستِ داده‌شده جایگزین می‌کند —
        همیشه کنارِ هم، در سمتِ چپِ فرم می‌نشینند (طبقِ قانونِ ثابتِ چیدمان)."""
        while self.footer_layout.count():
            item = self.footer_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
        for button in buttons:
            self.footer_layout.addWidget(button)
        self.footer_layout.addStretch(1)


def wrap_scrollable(content: QWidget) -> QWidget:
    """بدنه‌یِ یک فرم را داخلِ یک QScrollAreaِ بی‌قاب می‌پیچد، درونِ یک
    کارتِ تمام‌عرض. برایِ صفحاتی که (برخلافِ FormScreenBase) ساختارِ
    خودشان را حفظ می‌کنند ولی همچنان باید نوارِ دکمه‌شان بیرونِ ناحیه‌یِ
    اسکرول‌شونده بماند تا هرگز زیرِ تسک‌بار/لبه‌یِ زیرپنجره گم نشود."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidget(content)
    wrapper = QWidget()
    wrapper.setObjectName("card")
    wrapper_layout = QVBoxLayout(wrapper)
    wrapper_layout.setContentsMargins(0, 0, 0, 0)
    wrapper_layout.setSpacing(0)
    wrapper_layout.addWidget(scroll)
    return wrapper


def wrap_scrollable_with_footer(content: QWidget, footer_buttons: list[QWidget]) -> QWidget:
    """معادلِ دستیِ همان اسکلتِ FormScreenBase (بدنه‌یِ اسکرول‌شونده +
    فوترِ ثابت، هردو داخلِ یک کارت) برایِ صفحاتی که به دلیلِ چیدمانِ
    خاصِ خودشان (مثلاً دو-پانلیِ فهرست+فرم در companies.py/roles.py/...)
    نمی‌توانند مستقیماً زیرکلاسِ FormScreenBase شوند. دکمه‌ها همیشه بیرونِ
    ناحیه‌یِ اسکرول می‌مانند، پس هرگز با محتوایِ زیاد از دیدِ کاربر گم/
    زیرِ تسک‌بار نمی‌شوند."""
    card = QWidget()
    card.setObjectName("card")
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(0, 0, 0, 0)
    card_layout.setSpacing(0)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidget(content)
    card_layout.addWidget(scroll, stretch=1)

    card_layout.addWidget(build_action_footer(footer_buttons))
    return card


def build_action_footer(buttons: list[QWidget]) -> QWidget:
    """نوارِ دکمه‌یِ استانداردِ پایینِ فرم برایِ صفحاتی که به‌جایِ
    زیرکلاسیِ FormScreenBase، ساختارِ چیدمانِ خودشان را حفظ می‌کنند
    (مثلِ فهرست‌هایِ جدول‌محور یا صفحاتِ چندتبیِ ساده). دکمه‌ها به همان
    قاعده‌یِ ثابت می‌نشینند: کنارِ هم، سمتِ چپِ پایینِ فرم. این ویجت باید
    به‌عنوانِ آخرین آیتمِ layoutِ اصلیِ صفحه اضافه شود — بیرونِ هر
    QScrollAreaای، نه داخلش."""
    footer = QWidget()
    footer.setObjectName("formFooter")
    footer_layout = QHBoxLayout(footer)
    footer_layout.setContentsMargins(18, 12, 18, 14)
    footer_layout.setDirection(QBoxLayout.LeftToRight)
    footer_layout.setSpacing(8)
    for button in buttons:
        footer_layout.addWidget(button)
    footer_layout.addStretch(1)
    return footer


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


class PersianDigitLineEdit(QLineEdit):
    """فیلدِ متنیِ ساده با نمایشِ زندهٔ ارقامِ فارسی حینِ تایپ — برایِ
    فیلدهایِ شناسه‌ای/عددی مثلِ سریال/شماره‌چک/شبا/شماره‌حساب/کدِملی/تلفن
    که نیازی به پردازشِ عددیِ JalaliDateEdit/ZeroPaddedSpinBox ندارند، فقط
    نمایشِ رقمِ فارسی (هم‌الگو با _on_text_edited آن دو)."""

    def __init__(self, initial_text: str = "", *, placeholder: str = "") -> None:
        super().__init__()
        if placeholder:
            self.setPlaceholderText(placeholder)
        self.textEdited.connect(self._on_text_edited)
        if initial_text:
            self.setText(initial_text)

    def _on_text_edited(self, text: str) -> None:
        converted = numerals.to_persian_digits(numerals.to_ascii_digits(text))
        if converted != text:
            cursor = self.cursorPosition()
            self.setText(converted)
            self.setCursorPosition(cursor)

    def setText(self, text: str) -> None:  # noqa: N802 — نامِ متدِ Qt
        """طبقِ درخواستِ صریح: ارقامِ فارسی «همه‌جا» — حتی وقتی مقدارِ اولیه
        برنامه‌ای (مثلاً بارگذاریِ چکِ ذخیره‌شده) با ارقامِ ASCII ست شود."""
        super().setText(numerals.to_persian_digits(numerals.to_ascii_digits(text)))


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
    گوشه‌یِ بالا-راستِ پنجره‌یِ اصلی (نه وابسته به layoutِ هیچ فرمی)، که با
    فوکوس‌گرفتنِ هر فیلدِ ثبت‌شده متنِ راهنمایِ همان فیلد را نشان می‌دهد.

    طبقِ بازخوردِ کاربر: نسخه‌یِ اول از QToolTip استفاده می‌کرد که در
    محیطِ واقعیِ کاربر اصلاً نمایش داده نمی‌شد. بررسی نشان داد QToolTip
    (و بعد eventFilter+QEvent.FocusIn هم) به‌طورِ کلی روی فوکوس‌هایی که
    بدونِ رویدادِ ماوس اتفاق می‌افتند، غیرِقابلِ‌اتکا هستند. تلاشِ بعدی —
    یک پنجره‌یِ کاملاً مستقل (Qt.Tool) — باگِ بدترِ دیگری آشکار کرد: آن
    پنجره خودش app.activeWindow() می‌شد و پنجره‌یِ اصلی را از حالتِ فعال
    می‌انداخت. راه‌حلِ نهایی: این کادر اصلاً پنجره‌یِ جدا نیست — یک
    QWidgetِ معمولیِ فرزندِ خودِ پنجره‌یِ اصلی است (بدونِ عضویت در هیچ
    layout)، با move()/raise_() در گوشه جا می‌گیرد.

    طبقِ درخواستِ صریح برایِ ظاهرِ متمایز: به‌جایِ همرنگیِ تمِ تیره‌یِ
    برنامه، این کادر پس‌زمینه‌یِ روشن با فونتِ تیره و لبه‌یِ رنگیِ نازک
    دارد تا رویِ زمینه‌یِ تیره‌یِ ریبون/سایدبار به‌وضوح جلبِ‌توجه کند؛ با
    هر به‌روزرسانیِ متن یک انیمیشنِ محوشدگیِ کوتاه (fade) هم اجرا می‌شود.
    کلیدِ روشن/خاموش‌کردنِ کلی دیگر داخلِ خودِ کادر نیست — طبقِ درخواستِ
    صریح به دکمه‌ی کوچکِ بالایِ صفحه (کنارِ نشانِ برند، در هدر) منتقل شده
    (نگاهِ کنید: shell_window.py — field_help_toggle).

    طبقِ درخواستِ صریح: با ماوس (از هر جایِ کادر — کلیک-و-بکش) قابلِ‌جابجایی
    است؛ آخرین مکانِ دلخواهِ کاربر با QSettings ذخیره و در همه‌یِ صفحه‌ها/
    اجراهایِ بعدی به‌کار می‌رود (نه فقط گوشه‌یِ پیش‌فرض). چون فرزندهایِ
    کادر (آیکن/عنوان/متن) صرفاً QLabelِ نمایشی‌اند،
    WA_TransparentForMouseEvents رویِ آن‌ها گذاشته شده تا کلیکِ رویِ متن هم
    به خودِ کادر برسد و درگ از هرجایِ کارت کار کند.

    یک نمونه‌یِ سراسریِ Singleton (از طریقِ FieldHelpPanel.instance(parent))
    برایِ کلِ برنامه کافی است — هر صفحه‌ای که فیلدهایش را با
    FieldHelpController ثبت کند، همین یک کادر را به‌روزرسانی می‌کند."""

    _instance: "FieldHelpPanel | None" = None
    _PLACEHOLDER = "برایِ دیدنِ راهنمایِ هر فیلد، رویِ آن کلیک کنید یا با کلیدِ Tab به آن بروید."
    _ACCENT = "#f5a524"
    _POSITION_SETTINGS_KEY = "field_help/position"

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
            "#fieldHelpPanel {"
            "   background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #fbf3e6);"
            f"   border: 1px solid {self._ACCENT};"
            "   border-right: 4px solid " + self._ACCENT + ";"
            "   border-radius: 14px;"
            "}"
            "#fieldHelpPanel QLabel#fieldHelpTitle {"
            f"   color: {self._ACCENT}; font-weight: bold; font-size: 12px;"
            "}"
            "#fieldHelpPanel QLabel#fieldHelpText { color: #2c2416; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 14)
        outer.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(6)
        icon = QLabel("💡")
        icon.setAttribute(Qt.WA_TransparentForMouseEvents)
        header.addWidget(icon)
        title = QLabel("راهنمایِ فیلد")
        title.setObjectName("fieldHelpTitle")
        title.setAttribute(Qt.WA_TransparentForMouseEvents)
        header.addWidget(title)
        header.addStretch(1)
        outer.addLayout(header)

        self.text_label = QLabel(self._PLACEHOLDER)
        self.text_label.setObjectName("fieldHelpText")
        self.text_label.setWordWrap(True)
        self.text_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        outer.addWidget(self.text_label)

        self._active = False
        self._enabled = field_help_is_enabled()
        self._drag_offset: QPoint | None = None
        self._custom_position = self._load_position()
        self.setCursor(Qt.SizeAllCursor)

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._fade_animation = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_animation.setDuration(220)
        self._fade_animation.setEasingCurve(QEasingCurve.OutCubic)

        parent.installEventFilter(self)

    def set_enabled(self, value: bool) -> None:
        self._enabled = value
        self._sync_visibility()

    def is_enabled(self) -> bool:
        return self._enabled

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
        if self._active and self._enabled:
            self._play_fade_in()

    def _play_fade_in(self) -> None:
        # طبقِ درخواستِ صریح برایِ «انیمیشنِ خاص»: با هر به‌روزرسانیِ متن،
        # کادر کوتاه محو و دوباره ظاهر می‌شود تا تغییرِ محتوا به‌چشم بیاید.
        self._fade_animation.stop()
        self._fade_animation.setStartValue(0.35)
        self._fade_animation.setEndValue(1.0)
        self._fade_animation.start()

    def _sync_visibility(self) -> None:
        if self._active and self._enabled:
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

    # --- جابجاییِ کادر با ماوس --------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            parent = self.parentWidget()
            new_pos = self.mapToParent(event.position().toPoint() - self._drag_offset)
            if parent is not None:
                new_pos.setX(max(0, min(new_pos.x(), max(0, parent.width() - self.width()))))
                new_pos.setY(max(0, min(new_pos.y(), max(0, parent.height() - self.height()))))
            self.move(new_pos)
            self._custom_position = new_pos
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self._save_position()
        super().mouseReleaseEvent(event)

    def _save_position(self) -> None:
        settings = QSettings("Peecha", "PeechaERP")
        settings.setValue(self._POSITION_SETTINGS_KEY, self.pos())

    def _load_position(self) -> QPoint | None:
        settings = QSettings("Peecha", "PeechaERP")
        value = settings.value(self._POSITION_SETTINGS_KEY, None)
        return value if isinstance(value, QPoint) else None

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        if self._custom_position is not None:
            # طبقِ درخواستِ صریح: اگر کاربر قبلاً کادر را جابجا کرده، همان
            # مکانِ دلخواه (با کلمپ‌کردن درونِ محدوده‌یِ ناحیه‌یِ محتوا، برایِ
            # وقتی اندازه‌یِ پنجره کوچک‌تر از قبل شده) استفاده می‌شود.
            x = max(0, min(self._custom_position.x(), max(0, parent.width() - self.width())))
            y = max(0, min(self._custom_position.y(), max(0, parent.height() - self.height())))
            self.move(x, y)
            return
        # پیش‌فرض (پیش از هر جابجاییِ دستی): گوشه‌یِ بالا-راستِ ناحیه‌یِ محتوا.
        margin = 20
        x = parent.width() - self.width() - margin
        y = margin
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


class FieldHelpMixin:
    """میکسینِ سراسری برایِ فعال‌کردنِ راهنمایِ فیلدها در هر صفحه‌ای، بدونِ
    تکرارِ شش‌هفت‌خطِ boilerplateِ نگه‌داشتنِ کنترلر/showEvent/hideEvent در
    هر فایلِ صفحه (که در نسخه‌یِ اولِ این مکانیزم — فقط در
    chart_of_accounts.py — دستی نوشته شده بود).

    استفاده: کلاسِ صفحه این را قبل از QWidget (یا هر پایه‌ی دیگرِ Qt) ارث
    ببرد:
        class MyScreen(FieldHelpMixin, QWidget):
            def __init__(self):
                super().__init__()
                ...  # ساختنِ فیلدها
                self.set_field_help([
                    (self.name_field, "توضیحِ آموزشیِ این فیلد..."),
                    ...
                ])

    ثبتِ واقعی (ساختنِ FieldHelpController) تا اولین showEvent به تعویق
    می‌افتد، چون در __init__ این ویجت هنوز به QStackedWidgetِ صفحه‌هایِ
    برنامه اضافه نشده و self.parentWidget() هنوز None است — نگاهِ کنید به
    یادداشتِ مشابه که اول در chart_of_accounts.py کشف شد."""

    _field_help_fields: list[tuple[QWidget, str]] = ()
    _field_help_controller: "FieldHelpController | None" = None
    _field_help_registered = False

    def set_field_help(self, fields: list[tuple[QWidget, str]]) -> None:
        self._field_help_fields = fields

    def showEvent(self, event) -> None:  # noqa: N802 — نامِ متدِ Qt
        super().showEvent(event)
        if not self._field_help_fields:
            return
        if not self._field_help_registered:
            self._field_help_registered = True
            controller = FieldHelpController(FieldHelpPanel.instance(self.parentWidget()))
            self._field_help_controller = controller
            for widget, text in self._field_help_fields:
                controller.register(widget, text)
        FieldHelpPanel.instance(self.parentWidget()).activate()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        if not self._field_help_fields:
            return
        parent = self.parentWidget()
        if parent is not None:
            FieldHelpPanel.instance(parent).deactivate()


@dataclass
class FieldSpec:
    """یک فیلدِ فرم برایِ FieldGrid — key شناسه‌یِ پایدار برایِ ذخیره‌یِ
    چیدمان است (نه متنِ نمایشی، که ممکن است بعداً عوض شود)؛ span تعدادِ
    ستون (از columnsِ FieldGrid) که این فیلد پیش‌فرض اشغال می‌کند."""

    key: str
    label: str
    widget: QWidget
    span: int = 3


class FieldGrid(QWidget):
    """گریدِ چندستونهٔ واکنش‌گرا برایِ چیدمانِ فیلدهایِ فرم — جایگزینِ
    الگویِ تکراریِ «یک QLabel + یک فیلد در هر ردیفِ QVBoxLayout» که تقریباً
    در همه‌یِ صفحه‌ها فیلدهایِ کوتاه (تلفن/کدپستی/کد) را بی‌دلیل
    تمامِ‌عرض می‌کرد. هر FieldSpec یک spanِ پیش‌فرض دارد که نویسنده‌یِ
    صفحه تعیین می‌کند؛ ریاضیِ ردیف/ستون همان الگویی است که قبلاً فقط در
    treasury_voucher.py (به‌صورتِ دوتاییِ ثابت) دستی نوشته شده بود، اینجا
    برایِ spanِ متغیر (۱ تا columns) تعمیم یافته.

    برایِ پشتیبانیِ ویرایشِ چیدمان (LayoutEditMixin) بدونِ بازساختِ
    ویجت‌ها در هر تغییر: هر فیلد یک container ثابت دارد (ساخته‌شده فقط
    یک‌بار در __init__) که در rebuild فقط موقعیتش در QGridLayout تغییر
    می‌کند — QLayout.addWidget رویِ ویجتی که از قبل عضوِ همان layout است،
    فقط موقعیتش را جابه‌جا می‌کند، نه دوباره می‌سازد."""

    layoutChanged = Signal()

    def __init__(self, fields: list[FieldSpec], columns: int = 3, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._columns = columns
        self._default_order: list[str] = [f.key for f in fields]
        self._specs: dict[str, FieldSpec] = {f.key: f for f in fields}
        self._current_span: dict[str, int] = {f.key: f.span for f in fields}
        self._order: list[str] = list(self._default_order)

        self._grid_layout = QGridLayout(self)
        self._grid_layout.setSpacing(10)

        self._containers: dict[str, QWidget] = {}
        self._toolbars: dict[str, QWidget] = {}
        self._span_buttons: dict[str, dict[int, QPushButton]] = {}
        for spec in fields:
            self._containers[spec.key] = self._build_container(spec)
        self._rebuild()

    def _build_container(self, spec: FieldSpec) -> QWidget:
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(4)
        if spec.label:
            header.addWidget(QLabel(spec.label), stretch=1)
        else:
            # مثلاً چک‌باکس‌ها که متنِ خودشان برچسب است — بدونِ QLabelِ
            # تکراری، فقط جایگاهِ تولبارِ ویرایش (راست‌چین) نگه داشته می‌شود.
            header.addStretch(1)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(2)
        span_buttons: dict[int, QPushButton] = {}
        for span_value, span_label in ((1, "۱"), (2, "۲"), (3, "۳")):
            button = QPushButton(span_label)
            button.setCheckable(True)
            button.setFixedSize(20, 20)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(f"عرضِ فیلد: {span_value} از {self._columns} ستون")
            button.clicked.connect(lambda _checked, key=spec.key, value=span_value: self._set_span(key, value))
            toolbar_layout.addWidget(button)
            span_buttons[span_value] = button
        up_button = QPushButton("▲")
        up_button.setFixedSize(20, 20)
        up_button.setCursor(Qt.PointingHandCursor)
        up_button.setToolTip("جابه‌جایی به بالا")
        up_button.clicked.connect(lambda _checked=False, key=spec.key: self._move(key, -1))
        toolbar_layout.addWidget(up_button)
        down_button = QPushButton("▼")
        down_button.setFixedSize(20, 20)
        down_button.setCursor(Qt.PointingHandCursor)
        down_button.setToolTip("جابه‌جایی به پایین")
        down_button.clicked.connect(lambda _checked=False, key=spec.key: self._move(key, 1))
        toolbar_layout.addWidget(down_button)
        toolbar.setVisible(False)
        header.addWidget(toolbar)
        outer.addLayout(header)
        outer.addWidget(spec.widget)

        self._toolbars[spec.key] = toolbar
        self._span_buttons[spec.key] = span_buttons
        return container

    def _rebuild(self) -> None:
        row = 0
        col = 0
        for key in self._order:
            span = max(1, min(self._columns, self._current_span[key]))
            if col + span > self._columns:
                row += 1
                col = 0
            self._grid_layout.addWidget(self._containers[key], row, col, 1, span)
            col += span
            if col >= self._columns:
                row += 1
                col = 0
        for key, buttons in self._span_buttons.items():
            current = self._current_span[key]
            for span_value, button in buttons.items():
                button.setChecked(span_value == current)

    def _set_span(self, key: str, span: int) -> None:
        self._current_span[key] = span
        self._rebuild()
        self.layoutChanged.emit()

    def _move(self, key: str, delta: int) -> None:
        index = self._order.index(key)
        new_index = index + delta
        if 0 <= new_index < len(self._order):
            self._order[index], self._order[new_index] = self._order[new_index], self._order[index]
            self._rebuild()
            self.layoutChanged.emit()

    def set_field_visible(self, key: str, visible: bool) -> None:
        """پنهان/آشکارکردنِ یک فیلد بدونِ حذفش از چیدمان — برایِ فیلدهایِ
        شرطی (مثلاً «پروژه» فقط وقتی نوعِ انبار پروژه‌ای است). اگر آن
        فیلد تنها عضوِ ردیفِ خودش باشد (span کاملِ ردیف)، با پنهان‌شدن
        همان ردیف هم جمع می‌شود — هم‌رفتار با project_row.setVisible
        قبلی."""
        self._containers[key].setVisible(visible)

    def set_edit_mode(self, enabled: bool) -> None:
        for toolbar in self._toolbars.values():
            toolbar.setVisible(enabled)

    def is_edit_mode(self) -> bool:
        # isVisible() به دیده‌بودنِ کلِ زنجیره‌یِ اجدادِ ویجت هم وابسته است
        # (مثلاً در تست‌هایِ آفلاین که پنجره show() نشده، همیشه False
        # برمی‌گرداند)؛ isHidden() فقط پرچمِ صریحِ خودِ ویجت را می‌سنجد —
        # هر تولبار (همه‌شان با هم روشن/خاموش می‌شوند) کافی‌ست برایِ تشخیص.
        return any(not toolbar.isHidden() for toolbar in self._toolbars.values())

    def current_overrides(self) -> dict[str, tuple[int, int]]:
        """span/orderِ فعلیِ هر فیلد — برایِ ذخیره در QSettings."""
        return {key: (self._current_span[key], index) for index, key in enumerate(self._order)}

    def set_layout_overrides(self, overrides: dict[str, tuple[int, int]]) -> None:
        """overrides: key -> (span, order). فیلدهایی که override ندارند طبقِ
        span/ترتیبِ پیش‌فرضِ کدنویسی‌شده باقی می‌مانند؛ کلیدهایِ ناشناخته
        (مثلاً از یک نسخهٔ قدیمی‌ترِ صفحه) بی‌سروصدا نادیده گرفته می‌شوند."""
        for key in self._default_order:
            span, _order = overrides.get(key, (self._specs[key].span, 0))
            self._current_span[key] = max(1, min(self._columns, span))

        def sort_key(key: str) -> tuple[int, int]:
            default_index = self._default_order.index(key)
            _span, order = overrides.get(key, (0, default_index))
            return (order, default_index)

        self._order = sorted(self._default_order, key=sort_key)
        self._rebuild()

    def reset_layout(self) -> None:
        self.set_layout_overrides({})


class LayoutEditMixin:
    """میکسینِ اختیاریِ کلیکِ‌راست‌برایِ‌ویرایشِ‌چیدمان — هم‌الگو با
    FieldHelpMixin (میکسینِ اختیاری که صفحه با فراخوانیِ یک متدِ ثبت،
    آن را فعال می‌کند)، ولی چون نیازی به موقعیت‌دهیِ نسبت‌به‌پنجره‌یِ‌اصلی
    ندارد (برخلافِ FieldHelpPanel)، ثبت بلافاصله در register_field_grids
    انجام می‌شود، نه به‌تعویق‌افتاده تا showEvent.

    استفاده: کلاسِ صفحه این را قبل از QWidget ارث ببرد و بعدِ ساختنِ
    FieldGridهایِ خودش صدا بزند:
        class MyScreen(LayoutEditMixin, QWidget):
            def __init__(self):
                super().__init__()
                self.basic_grid = FieldGrid([...])
                ...
                self.register_field_grids("my_screen", [self.basic_grid, ...])

    کلیکِ‌راست رویِ هر FieldGrid یک منو می‌دهد: «ویرایشِ چیدمان» (توگل)،
    «ذخیرهٔ چیدمان»، «بازنشانیِ چیدمان». ذخیره در QSettings با کلیدِ
    form_layout/{screen_code} به‌صورتِ یک JSONِ تخت `{field_key: [span, order]}`
    برایِ همه‌یِ FieldGridهایِ ثبت‌شده با هم (هم‌الگو با کلیدگذاریِ
    print_options/{title} در report_export.py) — چون هر فیلد فقط در یک
    FieldGrid وجود دارد، ترکیب‌کردنِ همه در یک دیکشنریِ تخت مشکلی ایجاد
    نمی‌کند (orderِ هر فیلد فقط درونِ همان FieldGridِ خودش معنا دارد).
    این یک ترجیحِ محلیِ کاربر است (هم‌رده با تمِ رنگی/تنظیماتِ چاپ)، نه
    داده‌یِ چندکاربره — به همین دلیل QSettings صحیح‌تر از جدولِ دیتابیس
    است."""

    _layout_edit_screen_code: str = ""
    _layout_edit_grids: list[FieldGrid] = ()

    def register_field_grids(self, screen_code: str, grids: list[FieldGrid]) -> None:
        self._layout_edit_screen_code = screen_code
        self._layout_edit_grids = list(grids)
        self._apply_saved_layout()
        for grid in grids:
            grid.setContextMenuPolicy(Qt.CustomContextMenu)
            grid.customContextMenuRequested.connect(lambda pos, g=grid: self._show_layout_menu(g, pos))

    def _settings_key(self) -> str:
        return f"form_layout/{self._layout_edit_screen_code}"

    def _apply_saved_layout(self) -> None:
        settings = QSettings("Peecha", "PeechaERP")
        raw = settings.value(self._settings_key(), "")
        if not raw:
            return
        try:
            data: dict[str, list[int]] = json.loads(raw)
        except (TypeError, ValueError):
            return
        overrides = {key: (int(span), int(order)) for key, (span, order) in data.items()}
        for grid in self._layout_edit_grids:
            grid.set_layout_overrides(overrides)

    def _show_layout_menu(self, grid: FieldGrid, pos: QPoint) -> None:
        menu = QMenu(grid)
        toggle_action = menu.addAction("ویرایشِ چیدمان")
        toggle_action.setCheckable(True)
        toggle_action.setChecked(grid.is_edit_mode())
        toggle_action.triggered.connect(lambda checked, g=grid: g.set_edit_mode(checked))
        menu.addSeparator()
        menu.addAction("ذخیرهٔ چیدمان", self._save_layout)
        menu.addAction("بازنشانیِ چیدمان", self._reset_layout)
        menu.exec(grid.mapToGlobal(pos))

    def _save_layout(self) -> None:
        merged: dict[str, tuple[int, int]] = {}
        for grid in self._layout_edit_grids:
            merged.update(grid.current_overrides())
        settings = QSettings("Peecha", "PeechaERP")
        settings.setValue(self._settings_key(), json.dumps({key: list(value) for key, value in merged.items()}))

    def _reset_layout(self) -> None:
        settings = QSettings("Peecha", "PeechaERP")
        settings.remove(self._settings_key())
        for grid in self._layout_edit_grids:
            grid.reset_layout()


class HoverButton(QPushButton):
    """QPushButton با پس‌زمینه‌یِ متحرک (fade) بینِ رنگِ عادی/هاور —
    به‌جایِ سوییچِ آنیِ QSS. طبقِ درخواستِ صریح برایِ حسِ «مدرنِ ۲۰۲۶ با
    هاورافکت»: خودِ QSS فقط رنگِ متن/فونت را کنترل می‌کند (background:
    transparent در stylesheet)، و این کلاس پس‌زمینه‌ی گردِ خودش را با
    QPropertyAnimation رویِ یک Q_PROPERTY رنگی نقاشی می‌کند — رنگِ متن/آیکن
    را با drawControl(CE_PushButtonLabel) بدونِ چارچوبِ پیش‌فرضِ دکمه
    می‌کشد تا پس‌زمینه‌یِ سفارشی زیرِ آن دیده شود، نه زیرِ یک مربعِ
    استایلِ بومیِ پلتفرم."""

    def __init__(
        self,
        *args,
        base_color: str = "transparent",
        hover_color: str,
        active_color: str | None = None,
        radius: int = 10,
        text_align: Qt.AlignmentFlag = Qt.AlignCenter,
        indent: int = 0,
        margin: int = 14,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._radius = radius
        self._base_color = QColor(base_color) if base_color != "transparent" else QColor(0, 0, 0, 0)
        self._hover_color = QColor(hover_color)
        self._active_color = QColor(active_color) if active_color else self._hover_color
        self._bg_color = QColor(self._base_color)
        self._active_hover_color: QColor | None = None
        self._text_align = text_align
        self._indent = indent
        self._margin = margin

        self._animation = QPropertyAnimation(self, b"bgColor", self)
        self._animation.setDuration(140)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setAttribute(Qt.WA_Hover, True)

    def _get_bg_color(self) -> QColor:
        return self._bg_color

    def _set_bg_color(self, color: QColor) -> None:
        self._bg_color = QColor(color)
        self.update()

    bgColor = Property(QColor, _get_bg_color, _set_bg_color)

    def set_active(self, active: bool) -> None:
        """رنگِ پس‌زمینه‌یِ «فعال» (مثلاً آیتمِ منویِ جاری) بدونِ نیاز به هاور."""
        self._active_hover_color = self._active_color if active else None
        self._animate_to(self._active_color if active else self._base_color)

    def enterEvent(self, event) -> None:  # noqa: N802
        if self._active_hover_color is None:
            self._animate_to(self._hover_color)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._active_hover_color is None:
            self._animate_to(self._base_color)
        super().leaveEvent(event)

    def _animate_to(self, color: QColor) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._bg_color)
        self._animation.setEndValue(color)
        self._animation.start()

    def paintEvent(self, event) -> None:  # noqa: N802 — نامِ متدِ Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._bg_color)
        painter.drawRoundedRect(self.rect(), self._radius, self._radius)

        painter.setPen(self.palette().color(QPalette.ButtonText))
        painter.setFont(self.font())
        # باگِ واقعیِ کشف‌شده (با گزارشِ عکسِ واقعیِ کاربر روی ویندوز، که
        # آفلاین/لینوکس آن را نشان نمی‌داد): دادنِ Qt.AlignRight به
        # drawText(rect, alignment, ...) قابلِ‌اتکا نیست — ظاهراً بسته به
        # پلتفرم/تایمینگِ layoutDirection می‌تواند برعکس (چسبیده‌به‌چپ)
        # رندر شود. برایِ رفعِ قطعی، دیگر به هیچ پرچمِ alignmentِ Qt متکی
        # نیستیم — خودمان با QFontMetrics عرضِ متن را حساب می‌کنیم و
        # مختصاتِ x را دستی، مستقیماً نسبت به لبه‌یِ راست/چپ/وسطِ ناحیه،
        # محاسبه می‌کنیم.
        metrics = painter.fontMetrics()
        text = self.text()
        text_width = metrics.horizontalAdvance(text)
        area = self.rect().adjusted(self._margin, 0, -(self._margin + self._indent), 0)
        if self._text_align == Qt.AlignRight:
            x = area.right() - text_width
        elif self._text_align == Qt.AlignLeft:
            x = area.left()
        else:
            x = area.left() + (area.width() - text_width) // 2
        baseline_y = area.top() + (area.height() + metrics.ascent() - metrics.descent()) // 2
        painter.drawText(x, baseline_y, text)
        painter.end()


class KpiCard(QFrame):
    """کارتِ آماریِ داشبورد با آیکونِ رنگی (ته‌رنگِ شیشه‌ایِ واقعی، با آلفا
    رویِ سطحِ تیره — نه دیگر مخلوطِ دستی با سفید) و سایه‌ای که با هاور
    «بلندتر» می‌شود (blur/yOffset بیشتر، رنگِ اکسنتِ خودِ کارت را هم کمی
    به سایه اضافه می‌کند تا هاور حسِ برجسته‌شدنِ رنگی/شیشه‌ای بدهد، نه فقط
    یک سایه‌یِ خنثیِ تیره‌تر)."""

    def __init__(self, title: str, icon: str, color: str = theme.ACCENT) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setAttribute(Qt.WA_Hover, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(12)

        self._icon_badge = QLabel(icon)
        self._icon_badge.setFixedSize(42, 42)
        self._icon_badge.setAlignment(Qt.AlignCenter)
        header.addWidget(self._icon_badge)

        self._title_label = QLabel(title)
        header.addWidget(self._title_label)
        header.addStretch(1)
        outer.addLayout(header)

        self.value_label = QLabel("۰")
        outer.addWidget(self.value_label)

        self._shadow_color = QColor(0, 0, 0, 130)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(30)
        self._shadow.setXOffset(0)
        self._shadow.setYOffset(8)
        self._shadow.setColor(self._shadow_color)
        self.setGraphicsEffect(self._shadow)

        self._blur_animation = QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._blur_animation.setDuration(180)
        self._y_animation = QPropertyAnimation(self._shadow, b"yOffset", self)
        self._y_animation.setDuration(180)
        self._color_animation = QPropertyAnimation(self._shadow, b"color", self)
        self._color_animation.setDuration(180)

        self.refresh_theme(color)

    def refresh_theme(self, color: str | None = None) -> None:
        """طبقِ باگِ واقعیِ کشف‌شده (سوییچِ روشن/تیره): این کارت رنگ‌هایش
        را در __init__ به‌صورتِ inline stylesheet منجمد می‌کند — یک
        setStyleSheet سراسریِ دوباره خودکار روشنشان نمی‌کند. صفحه‌یِ
        داشبورد (singleton، بازسازی‌نشدنی) باید بعدِ هر سوییچِ تم این را
        صریحاً صدا بزند (در `refresh()` خودش) تا متن/آیکون با تمِ تازه
        هماهنگ بمانند. اگر `color` داده نشود، فقط رنگ‌هایِ خنثی (عنوان/
        مقدار) به‌روز می‌شوند و ته‌رنگِ اکسنتِ خودِ کارت دست‌نخورده می‌ماند؛
        اگر داده شود (مثلاً theme.CHART_TEAL که مقدارش بینِ تمِ روشن/تیره
        فرق دارد)، ته‌رنگِ آیکون/سایه‌یِ هاور هم با آن هماهنگ می‌شود."""
        if color is not None:
            self._color = color
            self._shadow_color_hover = QColor(color)
            self._shadow_color_hover.setAlpha(70)
        self._icon_badge.setStyleSheet(
            f"background-color: {theme.rgba(self._color, 0.16)}; "
            f"border: 1px solid {theme.rgba(self._color, 0.30)}; "
            "border-radius: 13px; font-size: 18px;"
        )
        self._title_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12.5px; font-weight: 600;")
        self.value_label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 30px; font-weight: 800;")

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._animate_shadow(44, 16, self._shadow_color_hover)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._animate_shadow(30, 8, self._shadow_color)
        super().leaveEvent(event)

    def _animate_shadow(self, blur: float, y_offset: float, color: QColor) -> None:
        self._blur_animation.stop()
        self._blur_animation.setStartValue(self._shadow.blurRadius())
        self._blur_animation.setEndValue(blur)
        self._blur_animation.start()

        self._y_animation.stop()
        self._y_animation.setStartValue(self._shadow.yOffset())
        self._y_animation.setEndValue(y_offset)
        self._y_animation.start()

        self._color_animation.stop()
        self._color_animation.setStartValue(self._shadow.color())
        self._color_animation.setEndValue(color)
        self._color_animation.start()


# --- SummaryCard / SummaryCardBar --------------------------------------
# کارتِ رنگیِ خلاصه — الهام‌گرفته از نمونه‌طراحیِ فرمِ دریافت/پرداختِ
# خزانه‌داری که کاربر فرستاد (کارت‌هایِ رنگیِ جمع‌بندی بالایِ فرم، پیش از
# جدولِ ردیف‌ها). کوچک‌تر و فشرده‌تر از KpiCardِ داشبورد است چون داخلِ یک
# فرم می‌نشیند نه یک صفحه‌یِ مستقل، ولی از همان زبانِ بصری (کارت + ته‌رنگِ
# شیشه‌ای + برچسب کوچک بالایِ عددِ درشت) استفاده می‌کند.
_SUMMARY_CARD_ROLE_COLORS = {
    "neutral": None,  # در refresh_theme با theme.ACCENT جایگزین می‌شود
    "success": "SUCCESS",
    "warning": "WARNING",
    "danger": "DANGER",
    "info": "INFO",
}


class SummaryCard(QFrame):
    """کارتِ کوچکِ رنگیِ یک‌مقداره برایِ نوارِ خلاصه‌یِ بالایِ فرم‌هایِ
    تراکنشی (مثلاً «جمعِ دریافت»، «جمعِ ردیف‌ها»، «مانده»). با
    `set_role()` رنگش بینِ نقش‌هایِ success/warning/danger/info/neutral
    عوض می‌شود — برایِ نمایشِ زنده‌یِ وضعیت (مثلاً مانده=۰ سبز، غیرِصفر
    قرمز) بدونِ بازسازیِ کارت."""

    def __init__(self, title: str, role: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._role = role

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(4)

        self._title_label = QLabel(title)
        outer.addWidget(self._title_label)

        self.value_label = QLabel("۰")
        outer.addWidget(self.value_label)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(22)
        self._shadow.setXOffset(0)
        self._shadow.setYOffset(6)
        self._shadow.setColor(QColor(0, 0, 0, 110))
        self.setGraphicsEffect(self._shadow)

        self.refresh_theme()

    def _color(self) -> str:
        role_attr = _SUMMARY_CARD_ROLE_COLORS.get(self._role)
        return getattr(theme, role_attr) if role_attr else theme.ACCENT

    def set_role(self, role: str) -> None:
        self._role = role
        self.refresh_theme()

    def refresh_theme(self) -> None:
        color = self._color()
        self._title_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11.5px; font-weight: 600;")
        self.value_label.setStyleSheet(f"color: {color}; font-size: 21px; font-weight: 800;")
        self.setStyleSheet(
            f"QFrame#card {{ border: 1px solid {theme.rgba(color, 0.28)}; "
            f"background-color: {theme.rgba(color, 0.08)}; border-radius: 12px; }}"
        )

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class SummaryCardBar(QWidget):
    """ردیفِ افقیِ چند SummaryCard، هم‌عرض و با فاصله‌یِ یکسان — برایِ
    نمایشِ همزمانِ چند مقدارِ کلیدی (جمع، تعداد، مانده و ...) بالایِ فرم."""

    def __init__(self, cards: dict[str, SummaryCard], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cards = cards
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        for card in cards.values():
            layout.addWidget(card, stretch=1)

    def set_value(self, key: str, value: str) -> None:
        self.cards[key].set_value(value)

    def set_role(self, key: str, role: str) -> None:
        self.cards[key].set_role(role)


# --- SectionStepper ------------------------------------------------------
# نوارِ گام‌نمایِ افقی — صرفاً یک راهنمایِ بصری/پیمایشی است: با کلیک رویِ
# هر گام به بخشِ مربوطه در همان صفحه‌یِ تک‌صفحه‌ای اسکرول می‌کند، نه
# صفحه‌بندیِ واقعی (فیلدها هرگز hide/show نمی‌شوند). این تصمیمِ عمدی است
# تا زنجیره‌هایِ کیبورد/اعتبارسنجیِ فرم‌هایِ پیچیده (مثلِ صدورِ سندِ
# خزانه‌داری) دست‌نخورده بمانند و فقط لایه‌یِ بصری/ناوبری اضافه شود.
class _StepButton(QPushButton):
    def __init__(self, number: int, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self._number = number
        self._label = label
        self.setText(f"{numerals.to_persian_digits(str(number))}   {label}")
        self.setCheckable(False)
        self.set_state("upcoming")

    def set_state(self, state: str) -> None:
        # state: "upcoming" | "current" | "done"
        if state == "current":
            bg, fg, border = theme.rgba(theme.ACCENT, 0.16), theme.ACCENT, theme.ACCENT
            weight = 800
        elif state == "done":
            bg, fg, border = theme.rgba(theme.SUCCESS, 0.12), theme.SUCCESS, theme.rgba(theme.SUCCESS, 0.4)
            weight = 700
        else:
            bg, fg, border = "transparent", theme.TEXT_SECONDARY, theme.BORDER
            weight = 600
        self.setStyleSheet(
            f"QPushButton {{ background-color: {bg}; color: {fg}; border: 1px solid {border}; "
            f"border-radius: 16px; padding: 6px 14px; font-size: 12.5px; font-weight: {weight}; }}"
            f"QPushButton:hover {{ background-color: {theme.rgba(theme.ACCENT, 0.10)}; }}"
        )


class SectionStepper(QWidget):
    """نوارِ گام‌ها: `labels` نامِ هر بخش است، به همان ترتیبی که بخش‌ها
    در فرم ظاهر می‌شوند. `register_sections(scroll_area, section_widgets)`
    کلیکِ هر گام را به اسکرول‌کردنِ همان بخش وصل می‌کند و هم‌زمان با
    اسکرولِ دستیِ کاربر، گامِ جاری را زنده به‌روزرسانی می‌کند."""

    stepClicked = Signal(int)

    def __init__(self, labels: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buttons: list[_StepButton] = []
        self._current = 0
        self._sections: list[QWidget] = []
        self._scroll_area: QScrollArea | None = None
        self._suppress_scroll_sync = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for index, label in enumerate(labels):
            if index > 0:
                line = QFrame()
                line.setFrameShape(QFrame.HLine)
                line.setStyleSheet(f"background-color: {theme.BORDER}; max-height: 1px; border: none;")
                layout.addWidget(line, stretch=1)
            button = _StepButton(index + 1, label)
            button.clicked.connect(lambda _checked=False, idx=index: self._on_step_clicked(idx))
            self._buttons.append(button)
            layout.addWidget(button, stretch=0)
        layout.addStretch(0)
        self.set_current(0)

    def set_current(self, index: int) -> None:
        self._current = index
        for i, button in enumerate(self._buttons):
            if i < index:
                button.set_state("done")
            elif i == index:
                button.set_state("current")
            else:
                button.set_state("upcoming")

    def register_sections(self, scroll_area: QScrollArea, sections: list[QWidget]) -> None:
        self._scroll_area = scroll_area
        self._sections = sections
        scroll_area.verticalScrollBar().valueChanged.connect(self._on_scrolled)

    def _on_step_clicked(self, index: int) -> None:
        self.set_current(index)
        self.stepClicked.emit(index)
        if self._scroll_area is not None and index < len(self._sections):
            # جلوگیریِ از رقابتِ رویدادِ اسکرولِ برنامه‌ای (که هم‌زمان
            # valueChanged را شلیک می‌کند) با وضعیتِ گامی که کاربر تازه
            # صریحاً کلیک کرده — وگرنه _on_scrolled ممکن است بلافاصله
            # آن را رویِ محاسبه‌ی هندسیِ ناپایدار بازنویسی کند.
            self._suppress_scroll_sync = True
            self._scroll_area.ensureWidgetVisible(self._sections[index], 0, 0)
            self._suppress_scroll_sync = False

    def _on_scrolled(self, _value: int) -> None:
        if not self._sections or self._scroll_area is None or self._suppress_scroll_sync:
            return
        viewport_top = self._scroll_area.verticalScrollBar().value()
        current = 0
        for i, section in enumerate(self._sections):
            if section.y() <= viewport_top + 24:
                current = i
        if current != self._current:
            self.set_current(current)
