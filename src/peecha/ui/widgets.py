"""ویجت‌های اشتراکی بین چند صفحه — فیلد تاریخ شمسی (که قبلاً فقط در
journal_entry.py تعریف شده بود، و حالا fiscal_years.py هم به آن نیاز دارد)
و اسپین‌باکس صفر-پَدشونده (برای کدهایی مثل «۰۰۱» که QSpinBox معمولی
صفرهای ابتدایی آن‌ها را بی‌صدا حذف می‌کند) و راهنمای فیلدها
(FieldHelpController + FieldHelpPanel، طبق درخواست صریح: مکانیزمی
سراسری که هر فرمی می‌تواند برای نمایش توضیح آموزشی هر فیلد با
فوکوس‌گرفتن آن به‌کار ببرد). سه نسخه امتحان شد تا به فرم فعلی رسید:
نوار ثابت داخل فرم (ارتفاع فرم را عوض می‌کرد) → QToolTip (در محیط
واقعی کاربر نمایش داده نمی‌شد) → پنجرهٔ کاملاً مستقل (باگ activeWindow
را می‌ساخت) → نسخهٔ نهایی: کادر روکار فرزند خود پنجرهٔ اصلی، با
ظاهر روشن/رنگی (متفاوت از تم تیرهٔ برنامه) و انیمیشن محوشدگی، گوشهٔ
بالا-راست پنجره؛ کلید روشن/خاموش‌کردن کلی (field_help_is_enabled/
set_field_help_enabled) به دکمه‌ای در هدر برنامه منتقل شده، نه دیگر
داخل خود کادر."""

from __future__ import annotations

import datetime
import json
import time
from dataclasses import dataclass

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QSettings,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import shiboken6

from peecha import numerals
from peecha.ui import theme

_FIELD_HELP_SETTINGS_KEY = "field_help/enabled"


def persist_column_widths(table, key: str, skip_columns: tuple[int, ...] = ()) -> None:
    """R230: عرض ستون‌هایی که کاربر دستی تغییر داده ذخیره و دفعهٔ بعد اعمال می‌شود."""
    settings = QSettings("Peecha", "PeechaERP")
    header = table.horizontalHeader()
    for column in range(table.columnCount()):
        if column in skip_columns:
            continue
        width = settings.value(f"columnWidths/{key}/{column}", None, type=int)
        if width:
            table.setColumnWidth(column, width)

    def save(column: int, _old: int, new: int) -> None:
        if column not in skip_columns and new > 0:
            QSettings("Peecha", "PeechaERP").setValue(f"columnWidths/{key}/{column}", new)

    header.sectionResized.connect(save)


def show_saved_dialog(parent: QWidget | None, text: str, title: str = "ذخیره") -> QMessageBox:
    """R226 (درخواست صریح): پیام ذخیره در یک پنجرهٔ تعاملی با دکمهٔ «تایید»،
    نه فقط متن وضعیت. غیرمسدودکننده (open) تا جریان فرم/تست قفل نشود."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle(title)
    box.setText(text)
    box.setLayoutDirection(Qt.RightToLeft)
    box.addButton("تایید", QMessageBox.AcceptRole)
    box.setAttribute(Qt.WA_DeleteOnClose, True)
    box.open()
    return box

# ---------------------------------------------------------------------
# استانداردِ چیدمانِ صفحه‌ها -- طبقِ درخواستِ صریح («طراحیِ فرم‌ها یک
# رویهٔ خاص داشته باشه»). بررسیِ کدِ موجود نشان داد ده‌ها مقدارِ
# پراکنده‌یِ margin/spacing در سراسرِ صفحه‌ها دستی نوشته شده بود (بعضی
# فرم‌ها ۴px حاشیه داشتند، بعضی ۲۴px، بدونِ هیچ قاعده‌ای) -- همین
# پراکندگی دلیلِ اصلیِ «بعضی فرم‌ها فضایِ خالیِ زیاد دارند، بعضی فشرده‌اند»
# است. این چند مقدار از این پس تنها منبعِ حقیقتِ فاصله‌گذاریِ صفحه‌هاست؛
# مقدارها از رویِ رایج‌ترین الگویِ ازپیش‌موجود انتخاب شده‌اند (نه
# اختراعِ عددهایِ تازه) تا کمترین اصطکاک را با ظاهرِ فعلی داشته باشد.
PAGE_MARGINS = (20, 14, 20, 14)
SECTION_MARGINS = (14, 10, 14, 10)
SECTION_SPACING = 10


def build_page_layout(widget: QWidget) -> QVBoxLayout:
    """چیدمان سطح‌بالای یک صفحهٔ کامل (ثبت‌شده در shell_window) --
    حاشیه/فاصلهٔ استاندارد بیرونی. جایگزین نوشتن دستی
    setContentsMargins/setSpacing با عددهای دلخواه در هر صفحه."""
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(*PAGE_MARGINS)
    layout.setSpacing(SECTION_SPACING)
    return layout


def build_section_layout(widget: QWidget) -> QVBoxLayout:
    """چیدمان یک بخش/تب/کارت داخل صفحه — حاشیه/فاصلهٔ استاندارد
    داخلی. اکثر محتوای تب‌ها/کارت‌ها باید از همین به‌جای margin/spacing
    دستی خودشان استفاده کنند."""
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(*SECTION_MARGINS)
    layout.setSpacing(SECTION_SPACING)
    return layout


def build_page_header(title_text: str, hint_text: str | None = None) -> QWidget:
    """کارت استاندارد عنوان (+ راهنمای اختیاری) بالای هر صفحه — الگویی
    که تقریباً هر صفحه (با فاصله‌گذاری کمی متفاوت) خودش دوباره می‌نوشت."""
    card = QWidget()
    card.setObjectName("card")
    layout = build_section_layout(card)
    title = QLabel(title_text)
    title.setObjectName("pageTitle")
    layout.addWidget(title)
    if hint_text:
        hint = QLabel(hint_text)
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
    return card


def field_help_is_enabled() -> bool:
    """وضعیت سراسری روشن/خاموش کادر راهنمای فیلدها — مستقل از اینکه
    خود FieldHelpPanel تا این لحظه ساخته شده باشد یا نه، چون کلید
    روشن/خاموش‌کردن (در هدر برنامه) باید حتی پیش از بازکردن اولین
    صفحه‌ای که از راهنما استفاده می‌کند هم قابل‌استفاده باشد."""
    settings = QSettings("Peecha", "PeechaERP")
    return bool(settings.value(_FIELD_HELP_SETTINGS_KEY, True, type=bool))


def set_field_help_enabled(value: bool) -> None:
    settings = QSettings("Peecha", "PeechaERP")
    settings.setValue(_FIELD_HELP_SETTINGS_KEY, value)
    if FieldHelpPanel._instance is not None:
        FieldHelpPanel._instance.set_enabled(value)


class FormScreenBase(QWidget):
    """اسکلت استاندارد فرم‌های ورود اطلاعات — بدنهٔ اسکرول‌شونده +
    نوار دکمهٔ ثابت زیر آن (formFooter)، هردو داخل یک کارت. طبق
    گزارش تکراری کاربر («فرم‌های جدید اسکرول ندارن»، «دکمه‌های ذخیره
    زیر تسک‌بار می‌مونن»): پیش از این کلاس هر فرم این الگو را جداگانه و
    ناقص پیاده می‌کرد (`journal_entry.py` فقط جدول را اسکرول می‌کرد نه
    فوتر را؛ `treasury_voucher.py` اصلاً اسکرول نداشت)، و تنها نمونهٔ
    درست الگو (`treasury_checks.py`) دستی و بدون کلاس پایه تکرار شده
    بود. حالا هر فرم جدید فقط باید این کلاس را زیرکلاسی کند: بدنه در
    self.body_layout، دکمه‌ها در self.footer_layout.

    اگر این صفحه خودش داخل یک QScrollArea دیگر (مثل
    system_settings.py::_sub_tabs) قرار می‌گیرد، manages_own_scroll=True
    به آن می‌گوید این ویجت را دوباره نپیچد — وگرنه همین فوتر «ثابت» هم
    دوباره قابل‌اسکرول‌شدن و گم‌شدن می‌شود."""

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
        # طبقِ قانونِ ثابتِ چیدمانِ دکمه‌ها («همه‌یِ آیکن‌ها کنارِ هم، سمتِ
        # چپِ پایینِ فرم» — نه فقط رویِ این فرم، در همه‌جا): چون کلِ اپ
        # RTL است (setLayoutDirection در main.py)، QBoxLayout.setDirection
        # به‌تنهایی اثری ندارد — Qt جهتِ نمایشِ QBoxLayout را از
        # layoutDirection() خودِ ویجتِ صاحبِ آن می‌گیرد، نه از Direction
        # enum. پس باید layoutDirection خودِ ویجتِ فوتر را صریحاً LTR کرد؛
        # وگرنه دکمه‌ها همچنان از راست به چپ می‌چینند و ترتیبشان معکوس
        # (و محل‌شان وابسته به کدنویسیِ هر فایل) می‌ماند.
        self.footer.setLayoutDirection(Qt.LeftToRight)
        self.footer_layout = QHBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(18, 12, 18, 14)
        self.footer_layout.setSpacing(8)
        wrapper_layout.addWidget(self.footer)

        outer.addWidget(wrapper, stretch=1)

    def set_footer_visible(self, visible: bool) -> None:
        self.footer.setVisible(visible)

    def set_footer_buttons(self, buttons: list[QWidget]) -> None:
        """دکمه‌های فوتر را با ترتیب چپ‌به‌راست داده‌شده جایگزین می‌کند —
        همیشه کنار هم، در سمت چپ فرم می‌نشینند (طبق قانون ثابت چیدمان)."""
        while self.footer_layout.count():
            item = self.footer_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
        for button in buttons:
            self.footer_layout.addWidget(button)
        self.footer_layout.addStretch(1)


def wrap_scrollable(content: QWidget) -> QWidget:
    """بدنهٔ یک فرم را داخل یک QScrollArea بی‌قاب می‌پیچد، درون یک
    کارت تمام‌عرض. برای صفحاتی که (برخلاف FormScreenBase) ساختار
    خودشان را حفظ می‌کنند ولی همچنان باید نوار دکمه‌شان بیرون ناحیهٔ
    اسکرول‌شونده بماند تا هرگز زیر تسک‌بار/لبهٔ زیرپنجره گم نشود."""
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
    """معادل دستی همان اسکلت FormScreenBase (بدنهٔ اسکرول‌شونده +
    فوتر ثابت، هردو داخل یک کارت) برای صفحاتی که به دلیل چیدمان
    خاص خودشان (مثلاً دو-پانلی فهرست+فرم در companies.py/roles.py/...)
    نمی‌توانند مستقیماً زیرکلاس FormScreenBase شوند. دکمه‌ها همیشه بیرون
    ناحیهٔ اسکرول می‌مانند، پس هرگز با محتوای زیاد از دید کاربر گم/
    زیر تسک‌بار نمی‌شوند."""
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
    """نوار دکمهٔ استاندارد پایین فرم برای صفحاتی که به‌جای
    زیرکلاسی FormScreenBase، ساختار چیدمان خودشان را حفظ می‌کنند
    (مثل فهرست‌های جدول‌محور یا صفحات چندتبی ساده). دکمه‌ها به همان
    قاعدهٔ ثابت می‌نشینند: کنار هم، سمت چپ پایین فرم. این ویجت باید
    به‌عنوان آخرین آیتم layout اصلی صفحه اضافه شود — بیرون هر
    QScrollAreaای، نه داخلش."""
    footer = QWidget()
    footer.setObjectName("formFooter")
    # طبقِ قانونِ ثابتِ چیدمانِ دکمه‌ها: باید layoutDirection خودِ ویجتِ
    # فوتر صریحاً LTR شود (نه فقط Direction خودِ QBoxLayout) — دلیل را
    # در FormScreenBase.__init__ ببینید.
    footer.setLayoutDirection(Qt.LeftToRight)
    footer_layout = QHBoxLayout(footer)
    footer_layout.setContentsMargins(18, 12, 18, 14)
    footer_layout.setSpacing(8)
    for button in buttons:
        footer_layout.addWidget(button)
    footer_layout.addStretch(1)
    return footer


def add_quick_add_button(
    row_layout: QHBoxLayout, combo: QWidget, main_window, screen_code: str, tooltip: str = "افزودن مقدار تازه"
) -> QPushButton:
    """طبق سند راهنمای UI/UX (بخش ۶.۳ — دکمهٔ + استاندارد): هر
    فیلدی که مقدارش از یک جدول/فرم دیگر می‌آید باید کنارش یک دکمهٔ +
    داشته باشد که همان فرم تعریف را باز کند — بدون نیاز به بستن سند
    در حال ویرایش. برگشتن از آن فرم، refresh() فرم میزبان (که خود
    ناوبری برنامه صدا می‌زند) فهرست را از نو می‌سازد، پس مقدار
    تازه‌ساخته خودکار در آن ظاهر می‌شود — هم‌الگو با
    treasury_voucher._quick_add_counterparty، فقط به‌صورت تابع
    عمومی یک‌بار پیاده‌شده به‌جای کپی‌شدن در هر فرم.

    combo از قبل باید به row_layout اضافه شده باشد (این تابع فقط دکمه
    را می‌سازد و کنارش اضافه می‌کند، خود combo را جابه‌جا نمی‌کند)."""
    button = QPushButton("+")
    button.setObjectName("iconButton")
    button.setFixedWidth(28)
    button.setToolTip(tooltip)

    def _open() -> None:
        if main_window is not None:
            main_window.open_screen(screen_code)

    button.clicked.connect(_open)
    row_layout.addWidget(button)
    return button


class JalaliDateEdit(QLineEdit):
    """فیلد متنی تاریخ شمسی با ارقام فارسی — معادل رفتار تاریخ‌گیر
    Kivy (که هم آن یک فیلد متنی بود، نه پاپ‌آپ تقویم).

    allow_empty (طبق درخواست صریح کاربر «همه‌جا فقط تاریخ شمسی
    باشه» — جایگزین ترفند minimumDate/setSpecialValueText QDateEdit
    برای فیلدهای تاریخ اختیاری): وقتی True باشد، خالی‌گذاشتن متن
    یعنی «بدون تاریخ» — date() مقدار None برمی‌گرداند و setDate(None)
    فیلد را خالی می‌کند. پیش‌فرض False است تا رفتار همهٔ استفاده‌های
    قبلی (که همیشه یک تاریخ معتبر می‌خواهند) دست‌نخورده بماند."""

    def __init__(self, placeholder: str = "۱۴۰۳/۰۴/۲۸", *, allow_empty: bool = False) -> None:
        super().__init__()
        self.setPlaceholderText(placeholder)
        # اندازه‌یِ ثابت و یکسان در همه‌یِ فرم‌ها — قبلاً هر صفحه یک
        # setMaximumWidth دلبخواهی (۱۲۰ تا ۱۵۰) می‌گذاشت یا اصلاً نمی‌گذاشت
        # و فیلد کشیده می‌شد؛ حالا این کلاسِ مشترک اندازه را تعیین می‌کند.
        self.setFixedWidth(118)
        self._allow_empty = allow_empty
        self._date: datetime.date | None = None if allow_empty else datetime.date.today()
        self._refresh_text()
        self.textEdited.connect(self._on_text_edited)
        self.editingFinished.connect(self._on_editing_finished)

    def _refresh_text(self) -> None:
        self.setText(numerals.format_jalali_date(self._date) if self._date is not None else "")
        self.setCursorPosition(0)

    def _on_text_edited(self, text: str) -> None:
        converted = numerals.to_persian_digits(numerals.to_ascii_digits(text))
        if converted != text:
            cursor = self.cursorPosition()
            self.setText(converted)
            self.setCursorPosition(cursor)

    def _on_editing_finished(self) -> None:
        if self._allow_empty and not self.text().strip():
            self._date = None
            return
        try:
            self._date = numerals.parse_jalali_date(self.text())
        except ValueError:
            pass
        self._refresh_text()

    def date(self) -> datetime.date | None:
        if self._allow_empty and not self.text().strip():
            return None
        try:
            return numerals.parse_jalali_date(self.text())
        except ValueError:
            return self._date

    def setDate(self, value: datetime.date | None) -> None:
        self._date = value
        self._refresh_text()


class PersianDigitLineEdit(QLineEdit):
    """فیلد متنی ساده با نمایش زندهٔ ارقام فارسی حین تایپ — برای
    فیلدهای شناسه‌ای/عددی مثل سریال/شماره‌چک/شبا/شماره‌حساب/کد ملی/تلفن
    که نیازی به پردازش عددی JalaliDateEdit/ZeroPaddedSpinBox ندارند، فقط
    نمایش رقم فارسی (هم‌الگو با _on_text_edited آن دو)."""

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
        """طبق درخواست صریح: ارقام فارسی «همه‌جا» — حتی وقتی مقدار اولیه
        برنامه‌ای (مثلاً بارگذاری چک ذخیره‌شده) با ارقام ASCII ست شود."""
        super().setText(numerals.to_persian_digits(numerals.to_ascii_digits(text)))


class ZeroPaddedSpinBox(QSpinBox):
    """اسپین‌باکسی که مقدار را با صفرهای ابتدایی متناسب با تعداد رقم
    تنظیم‌شده نمایش می‌دهد (مثلاً digits=3 -> «۰۰۱»)؛ QSpinBox معمولی چون
    فقط عدد صحیح را نگه می‌دارد، صفرهای ابتدایی تایپ‌شده را بی‌درنگ حذف
    می‌کند و کد سه‌رقمی به یک‌رقمی تبدیل می‌شود — این کلاس با override‌کردن
    textFromValue همان مقدار را با طول ثابت نمایش می‌دهد."""

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


FIELD_HELP_PROPERTY = "peechaFieldHelp"
_INPUT_TYPES = (QLineEdit, QAbstractSpinBox, QComboBox, QTextEdit, QPlainTextEdit, QCheckBox, QRadioButton)


def set_widget_help(widget: QWidget, text: str) -> None:
    """R277: متن راهنما روی خود ویجت ذخیره می‌شود (نه در فهرست هر صفحه) تا در زیرپنجره‌ها و دیالوگ‌ها هم کار کند."""
    widget.setProperty(FIELD_HELP_PROPERTY, text)
    FieldHelpController.ensure()


def _input_target(widget: QWidget) -> QWidget:
    # ویجت داخلی کمبو/عددی/تاریخ فوکوس می‌گیرد؛ برچسب و راهنما مال ویجت بیرونی است
    parent = widget.parentWidget()
    if parent is not None and isinstance(parent, (QComboBox, QAbstractSpinBox)):
        return parent
    return widget


def _label_of(widget: QWidget) -> str:
    parent = widget.parentWidget()
    if parent is None:
        return ""
    layout = parent.layout()
    if isinstance(layout, QFormLayout):
        label = layout.labelForField(widget)
        if isinstance(label, QLabel):
            return label.text()
    for label in parent.findChildren(QLabel, options=Qt.FindDirectChildrenOnly):
        if label.buddy() is widget:
            return label.text()
    if layout is not None:
        found = _layout_neighbor_label(layout, widget)
        if found:
            return found
    # خانهٔ FieldGrid (یا ظرف مشابه): یک برچسب و فقط یک فیلد؛ فیلد ممکن است تا دو لایه داخل‌تر باشد
    child, container = widget, parent
    for _depth in range(3):
        if container is None or container.isWindow():
            break
        labels = [lb for lb in container.findChildren(QLabel, options=Qt.FindDirectChildrenOnly) if lb.text().strip()]
        holders = [w for w in container.findChildren(QWidget, options=Qt.FindDirectChildrenOnly)
                   if not isinstance(w, QLabel) and (isinstance(w, _INPUT_TYPES) or any(isinstance(d, _INPUT_TYPES) for d in w.findChildren(QWidget)))]
        if len(labels) == 1 and holders == [child]:
            return labels[0].text()
        if len(holders) > 1:
            break
        child, container = container, container.parentWidget()
    return ""


def _layout_neighbor_label(layout, widget: QWidget) -> str:
    index = layout.indexOf(widget)
    if index < 0:
        for i in range(layout.count()):
            child = layout.itemAt(i).layout()
            if child is not None:
                text = _layout_neighbor_label(child, widget)
                if text:
                    return text
        return ""
    if isinstance(layout, QGridLayout):
        row, col, _rs, _cs = layout.getItemPosition(index)
        for r, c in ((row, col - 1), (row - 1, col)):
            item = layout.itemAtPosition(r, c) if r >= 0 and c >= 0 else None
            if item is not None and isinstance(item.widget(), QLabel):
                return item.widget().text()
        return ""
    if index > 0:
        prev = layout.itemAt(index - 1).widget()
        if isinstance(prev, QLabel):
            return prev.text()
    return ""


def _generic_hint(widget: QWidget) -> str:
    if isinstance(widget, JalaliDateEdit):
        return "تاریخ شمسی. می‌توانید تایپ کنید (مثلاً ۱۴۰۴/۰۱/۱۵) یا از تقویم انتخاب کنید."
    if isinstance(widget, QComboBox):
        if widget.isEditable():
            return "از فهرست انتخاب کنید؛ برای پیدا کردن سریع، بخشی از نام را تایپ کنید."
        return "یکی از گزینه‌های فهرست را انتخاب کنید."
    if isinstance(widget, QAbstractSpinBox):
        return "یک عدد وارد کنید؛ با کلیدهای بالا و پایین هم می‌توانید مقدار را تغییر دهید."
    if isinstance(widget, (QCheckBox, QRadioButton)):
        return "با انتخاب این گزینه، این حالت فعال می‌شود."
    return ""


def resolve_field_help(widget: QWidget | None) -> tuple[str, str, QWidget] | None:
    """(عنوان، متن، ویجت لنگر) برای فیلدی که فوکوس گرفته؛ اول راهنمای اختصاصی، بعد واژه‌نامه."""
    from peecha.ui import field_help_glossary

    if widget is None:
        return None
    target = _input_target(widget)
    current = widget
    while current is not None:
        text = current.property(FIELD_HELP_PROPERTY)
        if text:
            anchor = target if current in (widget, target) else current
            return field_help_glossary.normalize_label(_label_of(anchor)), str(text), anchor
        if current.isWindow():
            break
        current = current.parentWidget()
    if not isinstance(target, _INPUT_TYPES):
        return None
    label = _label_of(target)
    if not label and isinstance(target, (QCheckBox, QRadioButton)):
        label = target.text()
    if not label and isinstance(target, QLineEdit):
        label = target.placeholderText()
    title = field_help_glossary.normalize_label(label)
    text = field_help_glossary.lookup(label) or (_generic_hint(target) if title else "")
    return (title, text, target) if text else None


class FieldHelpPanel(QFrame):
    """کادر راهنمای فیلدها — یک نمونه برای کل برنامه، روی همان پنجره‌ای (اصلی یا دیالوگ) که
    فیلد فوکوس‌گرفته در آن است، کنار همان فیلد ظاهر می‌شود و پس از چند ثانیه پنهان می‌شود.
    با ماوس جابه‌جا می‌شود و جای دلخواه کاربر ذخیره می‌شود؛ کلید روشن/خاموش در هدر برنامه است."""

    _instance: "FieldHelpPanel | None" = None
    _PLACEHOLDER = "برای دیدن راهنمای هر فیلد، روی آن کلیک کنید یا با کلید Tab به آن بروید."
    _DEFAULT_TITLE = "راهنمای فیلد"
    _ACCENT = "#f5a524"
    _POSITION_SETTINGS_KEY = "field_help/position"

    @classmethod
    def instance(cls, parent: QWidget) -> "FieldHelpPanel":
        if cls._instance is not None and not shiboken6.isValid(cls._instance):
            cls._instance = None
        if cls._instance is None:
            cls._instance = cls(parent)
        elif cls._instance.parentWidget() is not parent:
            old_parent = cls._instance.parentWidget()
            if old_parent is not None and shiboken6.isValid(old_parent):
                old_parent.removeEventFilter(cls._instance)
            cls._instance.hide()
            cls._instance.setParent(parent)
            parent.installEventFilter(cls._instance)
        return cls._instance

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("fieldHelpPanel")
        self.setFixedWidth(320)
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
        self.title_label = QLabel(self._DEFAULT_TITLE)
        self.title_label.setObjectName("fieldHelpTitle")
        self.title_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        header.addWidget(self.title_label)
        header.addStretch(1)
        outer.addLayout(header)

        self.text_label = QLabel(self._PLACEHOLDER)
        self.text_label.setObjectName("fieldHelpText")
        self.text_label.setWordWrap(True)
        self.text_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        outer.addWidget(self.text_label)

        self._active = True
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
        self._has_text = False
        self._anchor: QWidget | None = None
        self._quiet_until = 0.0
        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.timeout.connect(self.dismiss)
        self.hide()

    def dismiss(self) -> None:
        self._has_text = False
        self.hide()

    def set_enabled(self, value: bool) -> None:
        self._enabled = value
        self._sync_visibility()

    def is_enabled(self) -> bool:
        return self._enabled

    def activate(self) -> None:
        """تا یک ثانیه پس از بازشدن صفحه، فوکوس خودکار کادر را باز نمی‌کند."""
        self._active = True
        self._has_text = False
        self._quiet_until = time.monotonic() + 1.0
        self.text_label.setText(self._PLACEHOLDER)
        self._sync_visibility()

    def deactivate(self) -> None:
        self._has_text = False
        self._sync_visibility()

    def show_text(self, text: str, anchor: QWidget | None = None, title: str = "") -> None:
        self.title_label.setText(title or self._DEFAULT_TITLE)
        self.text_label.setText(text)
        self._anchor = anchor
        if time.monotonic() < self._quiet_until:
            return
        self._has_text = True
        self._sync_visibility()
        self._auto_hide.start(max(6000, min(20000, len(text) * 80)))
        if self._enabled:
            self._play_fade_in()

    def _play_fade_in(self) -> None:
        self._fade_animation.stop()
        self._fade_animation.setStartValue(0.35)
        self._fade_animation.setEndValue(1.0)
        self._fade_animation.start()

    def _sync_visibility(self) -> None:
        if self._active and self._enabled and self._has_text:
            self._reposition()
            self.show()
            self.raise_()
        else:
            self.hide()

    def eventFilter(self, watched: QObject, event) -> bool:
        if watched is self.parentWidget() and event.type() == QEvent.Resize and self.isVisible():
            self._reposition()
        return False

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.position().toPoint()
            self._auto_hide.stop()
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
            self._auto_hide.start(6000)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        # دوبار کلیک: برگشت به حالت «کنار فیلد» به‌جای جای ثابت
        self._custom_position = None
        QSettings("Peecha", "PeechaERP").remove(self._POSITION_SETTINGS_KEY)
        self._reposition()
        super().mouseDoubleClickEvent(event)

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
            x = max(0, min(self._custom_position.x(), max(0, parent.width() - self.width())))
            y = max(0, min(self._custom_position.y(), max(0, parent.height() - self.height())))
            self.move(x, y)
            return
        anchor = self._anchor
        if anchor is not None and shiboken6.isValid(anchor) and anchor.isVisible() and parent.isAncestorOf(anchor):
            top_left = anchor.mapTo(parent, QPoint(0, 0))
            x = top_left.x() + anchor.width() - self.width()
            y = top_left.y() + anchor.height() + 6
            if y + self.height() > parent.height():
                y = top_left.y() - self.height() - 6
            self.move(max(0, min(x, parent.width() - self.width())), max(0, min(y, parent.height() - self.height())))
            return
        margin = 20
        self.move(max(0, parent.width() - self.width() - margin), margin)


class FieldHelpController(QObject):
    """یک کنترلر سراسری برای کل برنامه (با QApplication.focusChanged). راهنما فقط وقتی باز می‌شود
    که فوکوس با کلیک یا کلید کاربر جابه‌جا شده باشد، نه با فوکوس خودکار هنگام بازشدن فرم."""

    _instance: "FieldHelpController | None" = None
    _USER_INPUT_WINDOW = 0.8

    @classmethod
    def ensure(cls) -> "FieldHelpController | None":
        app = QApplication.instance()
        if app is None:
            return None
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, panel: FieldHelpPanel | None = None) -> None:
        super().__init__()
        self._last_user_input = 0.0
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_focus_changed)
            app.installEventFilter(self)
        if FieldHelpController._instance is None:
            FieldHelpController._instance = self

    def register(self, widget: QWidget, text: str) -> None:
        widget.setProperty(FIELD_HELP_PROPERTY, text)

    def eventFilter(self, watched: QObject, event) -> bool:
        if event.type() in (QEvent.MouseButtonPress, QEvent.KeyPress, QEvent.ShortcutOverride):
            self._last_user_input = time.monotonic()
        return False

    def note_user_input(self) -> None:
        self._last_user_input = time.monotonic()

    def _on_focus_changed(self, _old: QWidget | None, new: QWidget | None) -> None:
        if new is None or not shiboken6.isValid(new):
            return
        window = new.window()
        current = FieldHelpPanel._instance
        if current is not None and not shiboken6.isValid(current):
            FieldHelpPanel._instance = current = None
        if window is None:
            return
        found = resolve_field_help(new)
        if found is None:
            if current is not None and current.isVisible():
                current.dismiss()
            return
        # فعال‌شدن زیرپنجره ممکن است فوکوس را پیش از رسیدن رویداد ماوس جابه‌جا کند؛ تصمیم پس از پردازش رویداد
        QTimer.singleShot(0, lambda: self._show_if_user_moved(new, found))

    def _show_if_user_moved(self, widget: QWidget, found: tuple[str, str, QWidget]) -> None:
        focused = QApplication.focusWidget()
        if not shiboken6.isValid(widget) or (focused is not None and focused is not widget):
            return
        if time.monotonic() - self._last_user_input > self._USER_INPUT_WINDOW:
            return
        title, text, anchor = found
        if not shiboken6.isValid(anchor):
            return
        FieldHelpPanel.instance(widget.window()).show_text(text, anchor, title)


class FieldHelpMixin:
    """راهنمای فیلدهای یک صفحه: self.set_field_help([(ویجت، متن), ...]). هر بار صدا زدن، فیلدهای
    تازه را اضافه می‌کند (جایگزین قبلی‌ها نمی‌شود)؛ نیازی به ثبت در showEvent نیست."""

    _field_help_fields: list[tuple[QWidget, str]] = ()

    def set_field_help(self, fields: list[tuple[QWidget, str]]) -> None:
        fields = list(fields)
        self._field_help_fields = [*self._field_help_fields, *fields]
        for widget, text in fields:
            if widget is not None:
                set_widget_help(widget, text)


@dataclass
class FieldSpec:
    """یک فیلد فرم برای FieldGrid — key شناسهٔ پایدار برای ذخیرهٔ
    چیدمان است (نه متن نمایشی، که ممکن است بعداً عوض شود)؛ span تعداد
    ستون (از columns FieldGrid) که این فیلد پیش‌فرض اشغال می‌کند."""

    key: str
    label: str
    widget: QWidget
    span: int = 3


class FieldGrid(QWidget):
    """گرید چندستونهٔ واکنش‌گرا برای چیدمان فیلدهای فرم — جایگزین
    الگوی تکراری «یک QLabel + یک فیلد در هر ردیف QVBoxLayout» که تقریباً
    در همهٔ صفحه‌ها فیلدهای کوتاه (تلفن/کدپستی/کد) را بی‌دلیل
    تمام‌عرض می‌کرد. هر FieldSpec یک span پیش‌فرض دارد که نویسندهٔ
    صفحه تعیین می‌کند؛ ریاضی ردیف/ستون همان الگویی است که قبلاً فقط در
    treasury_voucher.py (به‌صورت دوتایی ثابت) دستی نوشته شده بود، اینجا
    برای span متغیر (۱ تا columns) تعمیم یافته.

    برای پشتیبانی ویرایش چیدمان (LayoutEditMixin) بدون بازساخت
    ویجت‌ها در هر تغییر: هر فیلد یک container ثابت دارد (ساخته‌شده فقط
    یک‌بار در __init__) که در rebuild فقط موقعیتش در QGridLayout تغییر
    می‌کند — QLayout.addWidget روی ویجتی که از قبل عضو همان layout است،
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
            button.setToolTip(f"عرض فیلد: {span_value} از {self._columns} ستون")
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
        """پنهان/آشکارکردن یک فیلد بدون حذفش از چیدمان — برای فیلدهای
        شرطی (مثلاً «پروژه» فقط وقتی نوع انبار پروژه‌ای است). اگر آن
        فیلد تنها عضو ردیف خودش باشد (span کامل ردیف)، با پنهان‌شدن
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
        """span/order فعلی هر فیلد — برای ذخیره در QSettings."""
        return {key: (self._current_span[key], index) for index, key in enumerate(self._order)}

    def set_layout_overrides(self, overrides: dict[str, tuple[int, int]]) -> None:
        """overrides: key -> (span, order). فیلدهایی که override ندارند طبق
        span/ترتیب پیش‌فرض کدنویسی‌شده باقی می‌مانند؛ کلیدهای ناشناخته
        (مثلاً از یک نسخهٔ قدیمی‌تر صفحه) بی‌سروصدا نادیده گرفته می‌شوند."""
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
    """میکسین اختیاری کلیک‌راست‌برای‌ویرایش‌چیدمان — هم‌الگو با
    FieldHelpMixin (میکسین اختیاری که صفحه با فراخوانی یک متد ثبت،
    آن را فعال می‌کند)، ولی چون نیازی به موقعیت‌دهی نسبت‌به‌پنجرهٔ‌اصلی
    ندارد (برخلاف FieldHelpPanel)، ثبت بلافاصله در register_field_grids
    انجام می‌شود، نه به‌تعویق‌افتاده تا showEvent.

    استفاده: کلاس صفحه این را قبل از QWidget ارث ببرد و بعد ساختن
    FieldGridهای خودش صدا بزند:
        class MyScreen(LayoutEditMixin, QWidget):
            def __init__(self):
                super().__init__()
                self.basic_grid = FieldGrid([...])
                ...
                self.register_field_grids("my_screen", [self.basic_grid, ...])

    کلیک‌راست روی هر FieldGrid یک منو می‌دهد: «ویرایش چیدمان» (توگل)،
    «ذخیرهٔ چیدمان»، «بازنشانی چیدمان». ذخیره در QSettings با کلید
    form_layout/{screen_code} به‌صورت یک JSON تخت `{field_key: [span, order]}`
    برای همهٔ FieldGridهای ثبت‌شده با هم (هم‌الگو با کلیدگذاری
    print_options/{title} در report_export.py) — چون هر فیلد فقط در یک
    FieldGrid وجود دارد، ترکیب‌کردن همه در یک دیکشنری تخت مشکلی ایجاد
    نمی‌کند (order هر فیلد فقط درون همان FieldGrid خودش معنا دارد).
    این یک ترجیح محلی کاربر است (هم‌رده با تم رنگی/تنظیمات چاپ)، نه
    دادهٔ چندکاربره — به همین دلیل QSettings صحیح‌تر از جدول دیتابیس
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
        toggle_action = menu.addAction("ویرایش چیدمان")
        toggle_action.setCheckable(True)
        toggle_action.setChecked(grid.is_edit_mode())
        toggle_action.triggered.connect(lambda checked, g=grid: g.set_edit_mode(checked))
        menu.addSeparator()
        menu.addAction("ذخیرهٔ چیدمان", self._save_layout)
        menu.addAction("بازنشانی چیدمان", self._reset_layout)
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
    """QPushButton با پس‌زمینهٔ متحرک (fade) بین رنگ عادی/هاور —
    به‌جای سوییچ آنی QSS. طبق درخواست صریح برای حس «مدرن ۲۰۲۶ با
    هاورافکت»: خود QSS فقط رنگ متن/فونت را کنترل می‌کند (background:
    transparent در stylesheet)، و این کلاس پس‌زمینهٔ گرد خودش را با
    QPropertyAnimation روی یک Q_PROPERTY رنگی نقاشی می‌کند — رنگ متن/آیکن
    را با drawControl(CE_PushButtonLabel) بدون چارچوب پیش‌فرض دکمه
    می‌کشد تا پس‌زمینهٔ سفارشی زیر آن دیده شود، نه زیر یک مربع
    استایل بومی پلتفرم."""

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
        """رنگ پس‌زمینهٔ «فعال» (مثلاً آیتم منوی جاری) بدون نیاز به هاور."""
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
    """کارت آماری داشبورد با آیکون رنگی (ته‌رنگ شیشه‌ای واقعی، با آلفا
    روی سطح تیره — نه دیگر مخلوط دستی با سفید) و سایه‌ای که با هاور
    «بلندتر» می‌شود (blur/yOffset بیشتر، رنگ اکسنت خود کارت را هم کمی
    به سایه اضافه می‌کند تا هاور حس برجسته‌شدن رنگی/شیشه‌ای بدهد، نه فقط
    یک سایهٔ خنثی تیره‌تر)."""

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
        """طبق باگ واقعی کشف‌شده (سوییچ روشن/تیره): این کارت رنگ‌هایش
        را در __init__ به‌صورت inline stylesheet منجمد می‌کند — یک
        setStyleSheet سراسری دوباره خودکار روشنشان نمی‌کند. صفحهٔ
        داشبورد (singleton، بازسازی‌نشدنی) باید بعد هر سوییچ تم این را
        صریحاً صدا بزند (در `refresh()` خودش) تا متن/آیکون با تم تازه
        هماهنگ بمانند. اگر `color` داده نشود، فقط رنگ‌های خنثی (عنوان/
        مقدار) به‌روز می‌شوند و ته‌رنگ اکسنت خود کارت دست‌نخورده می‌ماند؛
        اگر داده شود (مثلاً theme.CHART_TEAL که مقدارش بین تم روشن/تیره
        فرق دارد)، ته‌رنگ آیکون/سایهٔ هاور هم با آن هماهنگ می‌شود."""
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
    """کارت کوچک رنگی یک‌مقداره برای نوار خلاصهٔ بالای فرم‌های
    تراکنشی (مثلاً «جمع دریافت»، «جمع ردیف‌ها»، «مانده»). با
    `set_role()` رنگش بین نقش‌های success/warning/danger/info/neutral
    عوض می‌شود — برای نمایش زندهٔ وضعیت (مثلاً مانده=۰ سبز، غیرصفر
    قرمز) بدون بازسازی کارت."""

    def __init__(self, title: str, role: str = "neutral", parent: QWidget | None = None, icon: str = "") -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._role = role

        outer = QVBoxLayout(self)
        # طبقِ گزارشِ صریح («هدرِ فرم‌ها خیلی بزرگ است، فضا به آیتم‌ها
        # بدهید»): پدینگِ قبلی (۱۶/۱۲) این کارت‌هایِ خلاصه را بی‌جهت
        # بلند می‌کرد — همه‌ی صفحاتی که SummaryCard دارند یک‌جا جمع‌تر شدند.
        outer.setContentsMargins(10, 4, 10, 4)
        outer.setSpacing(0)

        # طبقِ طرحِ نمونه‌یِ ارسالیِ کاربر (کارت‌هایِ رنگیِ آیکون‌دار در
        # نوارِ خلاصه‌یِ فاکتور): آیکون اختیاری است -- صفحاتِ قدیمی‌تر
        # (journal_entry.py/treasury_voucher.py) بدونِ آن صدا زده می‌شوند
        # و دقیقاً مثلِ قبل بدونِ آیکون می‌مانند.
        self._title_label = QLabel(f"{icon}  {title}" if icon else title)
        outer.addWidget(self._title_label)

        self.value_label = QLabel("۰")
        outer.addWidget(self.value_label)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(14)
        self._shadow.setXOffset(0)
        self._shadow.setYOffset(3)
        self._shadow.setColor(QColor(0, 0, 0, 90))
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
        self.value_label.setStyleSheet(f"color: {color}; font-size: 17px; font-weight: 800;")
        self.setStyleSheet(
            f"QFrame#card {{ border: 1px solid {theme.rgba(color, 0.28)}; "
            f"background-color: {theme.rgba(color, 0.08)}; border-radius: 12px; }}"
        )

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class SummaryCardBar(QWidget):
    """ردیف افقی چند SummaryCard، هم‌عرض و با فاصلهٔ یکسان — برای
    نمایش همزمان چند مقدار کلیدی (جمع، تعداد، مانده و ...) بالای فرم."""

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
    """نوار گام‌ها: `labels` نام هر بخش است، به همان ترتیبی که بخش‌ها
    در فرم ظاهر می‌شوند. `register_sections(scroll_area, section_widgets)`
    کلیک هر گام را به اسکرول‌کردن همان بخش وصل می‌کند و هم‌زمان با
    اسکرول دستی کاربر، گام جاری را زنده به‌روزرسانی می‌کند."""

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


class FormDrawer(QWidget):
    """R275: فرم ورود کنار فهرست، کشوی جمع‌شونده است — فهرست تمام‌عرض می‌ماند و فرم
    فقط با کلیک یک ردیف یا «جدید» باز می‌شود (✕ دوباره جمعش می‌کند). فقط چیدمان:
    همان ویجت فرم با همهٔ فیلدها و هندلرهایش جابه‌جا می‌شود، چیزی حذف یا عوض نمی‌شود.

    layout: چیدمان یا QSplitterی که form_panel در آن نشسته (جایگاه و stretch همان خانه حفظ می‌شود).
    open_signals: سیگنال‌های کلیک ردیف؛ on_new: هندلر «جدید» خود صفحه (مثل _reset_form)؛
    new_buttons: دکمه‌های «جدید» موجود صفحه که باید کشو را هم باز کنند؛
    handle_new=False برای فرم‌های فقط‌ثبت که دکمهٔ ثبت خودشان ➕ است.
    """

    RAIL_WIDTH = 60

    def __init__(
        self,
        layout,
        form_panel: QWidget,
        *,
        open_signals=(),
        on_new=None,
        new_buttons=(),
        new_tooltip: str = "جدید",
        handle_new: bool = True,
        start_open: bool = False,
    ) -> None:
        super().__init__()
        self.setObjectName("formDrawer")
        self.form_panel = form_panel
        self._splitter = layout if isinstance(layout, QSplitter) else None
        self._open_ratio = 0.6
        if self._splitter is not None:
            index = layout.indexOf(form_panel)
            sizes = layout.sizes()
            if sum(sizes) > 0 and sizes[index] > 0:
                self._open_ratio = sizes[index] / sum(sizes)
            layout.replaceWidget(index, self)
            layout.setCollapsible(index, False)
            at_start = index == 0
        else:
            layout.replaceWidget(form_panel, self)
            at_start = layout.indexOf(self) == 0
        self._on_new = on_new

        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)

        # نوارِ باریکِ حالتِ جمع‌شده: «جدید» و «نمایشِ فرم»
        self.rail = QWidget()
        self.rail.setObjectName("formDrawerRail")
        self.rail.setAttribute(Qt.WA_StyledBackground, True)
        self.rail.setFixedWidth(self.RAIL_WIDTH)
        rail_layout = QVBoxLayout(self.rail)
        rail_layout.setContentsMargins(6, 10, 6, 10)
        rail_layout.setSpacing(8)
        self.new_button = None
        if on_new is not None:
            self.new_button = self._tool_button("➕", new_tooltip, primary=True)
            self.new_button.clicked.connect(self._new)
            rail_layout.addWidget(self.new_button, alignment=Qt.AlignHCenter)
        self.show_button = self._tool_button("📝", "نمایش فرم")
        self.show_button.clicked.connect(self.open)
        rail_layout.addWidget(self.show_button, alignment=Qt.AlignHCenter)
        rail_layout.addStretch(1)

        # حالتِ باز: دکمهٔ جمع‌کردن در لبهٔ کشو + خودِ فرم
        self.handle = QWidget()
        handle_layout = QVBoxLayout(self.handle)
        handle_layout.setContentsMargins(0, 4, 0, 4)
        handle_layout.setSpacing(6)
        self.close_button = self._tool_button("✕", "بستن فرم (فهرست تمام‌عرض)")
        self.close_button.clicked.connect(self.collapse)
        handle_layout.addWidget(self.close_button)
        if on_new is not None and handle_new:
            self.handle_new_button = self._tool_button("➕", new_tooltip, primary=True)
            self.handle_new_button.clicked.connect(self._new)
            handle_layout.addWidget(self.handle_new_button)
        handle_layout.addStretch(1)

        # دستگیره همیشه لبهٔ رو به فهرست را می‌گیرد (کشو اولِ چیدمان باشد یا آخرش)
        for widget in ((form_panel, self.handle) if at_start else (self.handle, form_panel)):
            box.addWidget(widget, 1 if widget is form_panel else 0)
        box.addWidget(self.rail)

        for signal in open_signals:
            signal.connect(lambda *_args: self.open())
        for button in new_buttons:
            button.clicked.connect(lambda *_args: self.open())
        self.set_open(start_open)

    @staticmethod
    def _tool_button(text: str, tooltip: str, primary: bool = False) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setObjectName("drawerPrimary" if primary else "drawerButton")
        button.setFixedSize(40, 36)
        button.setCursor(Qt.PointingHandCursor)
        return button

    def is_open(self) -> bool:
        return self._open

    def set_open(self, value: bool) -> None:
        was_open = getattr(self, "_open", None)
        self._open = bool(value)
        if self._splitter is not None and was_open and not self._open:
            sizes = self._splitter.sizes()
            if sum(sizes) > 0:
                self._open_ratio = sizes[self._splitter.indexOf(self)] / sum(sizes)
        self.rail.setVisible(not self._open)
        self.handle.setVisible(self._open)
        self.form_panel.setVisible(self._open)
        self.setMaximumWidth(16777215 if self._open else self.RAIL_WIDTH)
        if self._splitter is not None and self._open and was_open is False:
            self._restore_splitter_size()

    def _restore_splitter_size(self) -> None:
        # QSplitter پهنایِ کشویِ جمع‌شده را نگه می‌دارد؛ هنگامِ باز شدن سهمِ قبلی‌اش برمی‌گردد
        sizes = self._splitter.sizes()
        index = self._splitter.indexOf(self)
        total = sum(sizes)
        if total <= 0:
            return
        want = min(max(int(total * self._open_ratio), self.RAIL_WIDTH * 4), total - self.RAIL_WIDTH)
        others = [i for i in range(len(sizes)) if i != index]
        rest = total - want
        other_total = sum(sizes[i] for i in others) or len(others)
        for i in others:
            sizes[i] = max(1, int(rest * (sizes[i] or 1) / other_total))
        sizes[index] = want
        self._splitter.setSizes(sizes)

    def open(self) -> None:
        if not self._open:
            self.set_open(True)

    def collapse(self) -> None:
        self.set_open(False)

    def _new(self) -> None:
        self._on_new()
        self.open()



def confirm_and_delete(parent: QWidget, title: str, label: str, model, pk: int | None, company_id: int | None,
                       after=None, children=()) -> bool:
    """R276: «حذف» یکسان فرم‌های تعریف — تایید، حذف امن (یا غیرفعال‌سازی اگر استفاده شده)، پیام و رفرش."""
    from peecha.services import master_data

    if pk is None:
        QMessageBox.warning(parent, title, "ابتدا یک ردیف را انتخاب کنید.")
        return False
    if QMessageBox.question(parent, title, f"«{label}» حذف شود؟") != QMessageBox.Yes:
        return False
    try:
        result = master_data.delete_or_deactivate(model, pk, company_id, children)
    except ValueError as exc:
        QMessageBox.warning(parent, title, str(exc))
        return False
    QMessageBox.information(parent, title, master_data.result_message(result, label))
    if after is not None:
        after()
    return True


def delete_button(tooltip: str = "حذف ردیف انتخاب‌شده") -> QPushButton:
    button = QPushButton("🗑️")
    button.setObjectName("dangerIconButton")
    button.setFixedWidth(44)
    button.setToolTip(tooltip)
    return button


def row_actions(*buttons: QWidget) -> QWidget:
    """R276: چند دکمهٔ عملیات (مثلاً انتشار + حذف) در یک خانهٔ جدول."""
    host = QWidget()
    box = QHBoxLayout(host)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(4)
    for button in buttons:
        box.addWidget(button)
    box.addStretch(1)
    return host
