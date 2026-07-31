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

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QSettings,
    Qt,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals
from peecha.ui import theme

_FIELD_HELP_SETTINGS_KEY = "field_help/enabled"


def _tint(color: str, amount: float) -> str:
    """رنگِ داده‌شده را با سفید مخلوط می‌کند (amount=۰..۱ سهمِ خودِ رنگ) —
    ته‌رنگِ روشنِ قابلِ‌اتکا برایِ پس‌زمینه‌یِ نشان‌ها؛ به‌جایِ تکنیکِ ناموفقِ
    پسوندِ آلفا رویِ کدِ هگز (Qt در QSS این را #AARRGGBB می‌خواند، نه
    #RRGGBBAA مثلِ CSS، پس نتیجه‌اش رنگِ کاملاً غلط بود)."""
    base = QColor(color)
    r = round(base.red() * amount + 255 * (1 - amount))
    g = round(base.green() * amount + 255 * (1 - amount))
    b = round(base.blue() * amount + 255 * (1 - amount))
    return QColor(r, g, b).name()


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
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._radius = radius
        self._base_color = QColor(base_color) if base_color != "transparent" else QColor(0, 0, 0, 0)
        self._hover_color = QColor(hover_color)
        self._active_color = QColor(active_color) if active_color else self._hover_color
        self._bg_color = QColor(self._base_color)
        self._active_hover_color: QColor | None = None

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
        painter.end()

        option = QStyleOptionButton()
        self.initStyleOption(option)
        label_painter = QPainter(self)
        label_painter.setRenderHint(QPainter.Antialiasing)
        self.style().drawControl(QStyle.CE_PushButtonLabel, option, label_painter, self)
        label_painter.end()


class KpiCard(QFrame):
    """کارتِ آماریِ داشبورد با آیکونِ رنگی و سایه‌ای که با هاور «بلندتر»
    می‌شود (blur/yOffset بیشتر) — جایگزینِ کارتِ ساده‌ی متنیِ قبلی که هیچ
    واکنشی به هاور نداشت و حسِ «فرمِ اداریِ قدیمی» می‌داد."""

    def __init__(self, title: str, icon: str, color: str = theme.ACCENT) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setAttribute(Qt.WA_Hover, True)
        self._color = color

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)

        icon_badge = QLabel(icon)
        icon_badge.setFixedSize(38, 38)
        icon_badge.setAlignment(Qt.AlignCenter)
        icon_badge.setStyleSheet(
            f"background-color: {_tint(color, 0.16)}; border-radius: 12px; font-size: 17px;"
        )
        header.addWidget(icon_badge)

        title_label = QLabel(title)
        title_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px; font-weight: 600;")
        header.addWidget(title_label)
        header.addStretch(1)
        outer.addLayout(header)

        self.value_label = QLabel("۰")
        self.value_label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 28px; font-weight: 800;")
        outer.addWidget(self.value_label)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(24)
        self._shadow.setXOffset(0)
        self._shadow.setYOffset(6)
        self._shadow.setColor(QColor(79, 70, 229, 24))
        self.setGraphicsEffect(self._shadow)

        self._blur_animation = QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._blur_animation.setDuration(160)
        self._y_animation = QPropertyAnimation(self._shadow, b"yOffset", self)
        self._y_animation.setDuration(160)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._animate_shadow(38, 14)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._animate_shadow(24, 6)
        super().leaveEvent(event)

    def _animate_shadow(self, blur: float, y_offset: float) -> None:
        self._blur_animation.stop()
        self._blur_animation.setStartValue(self._shadow.blurRadius())
        self._blur_animation.setEndValue(blur)
        self._blur_animation.start()

        self._y_animation.stop()
        self._y_animation.setStartValue(self._shadow.yOffset())
        self._y_animation.setEndValue(y_offset)
        self._y_animation.start()
