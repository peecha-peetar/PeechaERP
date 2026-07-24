"""صدور سند — معادلِ Qt برایِ journal_entry.py/.kv در Kivy.

ردیف‌هایِ سند در یک جدولِ واقعی (QTableWidget) نمایش داده می‌شوند — هر
ردیف = یک سطرِ افقیِ حساب/تفصیلی/شرح/بدهکار/بستانکار.

طبقِ بازخوردِ صریح («نسخه‌ی Kivy کاملاً کار می‌کرد، همه‌ی امکاناتش را
منتقل کن»)، این نسخه امکاناتِ زیر را که در مهاجرتِ اولیه جا افتاده بودند
هم دارد: تاریخِ شمسی + ارقامِ فارسی (numerals.py)، تکمیلِ خودکارِ شرحِ
ردیف از رویِ شرح‌هایِ اخیر، نرمال‌سازیِ ارقامِ فارسی/عربیِ تایپ‌شده در
جستجویِ حساب/تفصیلی، پاک‌شدنِ خودکارِ فیلدِ حساب/تفصیلی اگر متنِ تایپ‌شده
با هیچ گزینه‌ای مطابقت نداشت (به‌جایِ ماندنِ یک انتخابِ نامعتبر/گم‌شده)،
مبلغ‌به‌حروف، پیغامِ تأییدِ ذخیره با شماره‌ی سند، میان‌برهایِ صفحه‌کلید
(Ctrl+S ذخیره، Esc انصراف/فرمِ جدید، Ctrl+Delete حذفِ سندِ درحالِ ویرایش)،
دکمه‌های حالتِ ویرایش (لغوِ ویرایش، حذفِ سند، برچسبِ «ذخیره‌ی تغییرات»،
تاریخِ ثبت)، Enter در آخرین ردیف یک ردیفِ تازه اضافه می‌کند (با شرحِ
همان ردیف)، و نگه‌داشتنِ ارزِ ردیف‌هایِ موجود (تا ویرایشِ یک سندِ
چندارزی، ردیف‌هایش را بی‌صدا به ارزِ پایه تبدیل نکند).

زنجیره‌ی Enter (طبقِ درخواستِ صریح، تمامِ فرم را پوشش می‌دهد):
تاریخ -> شرحِ سند -> شماره‌ی عطف -> حسابِ ردیفِ اول -> تفصیلی (اگر
حساب بپذیرد) -> مرکزِ هزینه (اگر لازم باشد) -> پروژه (اگر لازم باشد)
-> شرحِ ردیف -> بدهکار -> (اگر بدهکار صفر باشد) بستانکار -> ردیفِ
بعدی (اگر نبود، ساخته می‌شود). هر بار که صفحه از سایدبار باز شود،
فوکوس دوباره رویِ تاریخ می‌رود.

طبقِ بازخوردِ صریح: ستونِ «تفصیلی» دیگر فقط تفصیلیِ اشخاص را نشان
نمی‌دهد — همه‌ی نوع‌بُعدهایِ الزامیِ حسابِ انتخاب‌شده به‌جز مرکزِ هزینه
و پروژه (که ستونِ اختصاصیِ خودشان را دارند) در همین یک ستون یک‌جا
قابلِ‌جستجو/انتخاب‌اند — پنجره‌ی جداگانه‌ی «ابعاد» حذف شده.

ساده‌سازیِ عمدیِ این مرحله از مهاجرت: ردیفِ *تازه* با ارزِ پایه‌ی شرکت
ثبت می‌شود (بدونِ انتخابِ ارز/نرخِ اختصاصی) — ردیف‌هایی که از یک سندِ
موجود بارگذاری شده‌اند اما ارز/نرخِ خودشان را حفظ می‌کنند."""

from __future__ import annotations

import dataclasses
import datetime
import decimal
import re

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import currencies as currencies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import journal_entries as je_service
from peecha import numerals
from peecha.ui import theme
from peecha.ui.widgets import JalaliDateEdit

_COL_ROW_NO = 0
_COL_ACCOUNT = 1
_COL_DETAIL = 2
_COL_COST_CENTER = 3
_COL_PROJECT = 4
_COL_DESC = 5
_COL_DEBIT = 6
_COL_CREDIT = 7
_COL_REMOVE = 8
_COLUMN_LABELS = [
    "ردیف", "حساب", "تفصیلی", "مرکزِ هزینه", "پروژه", "شرحِ ردیف", "بدهکار", "بستانکار", "",
]


def _fill_options(combo: QComboBox, options: list[tuple[int, str]]) -> None:
    """پرکردنِ گزینه‌هایِ یک کمبویِ جستجوپذیرِ *موجود* — بدونِ دست‌زدن به
    handlerهایِ متصل‌شده (که فقط یک‌بار در _make_searchable_combo وصل می‌شوند)."""
    combo.clear()
    combo.addItem("", None)
    for value, label in options:
        combo.addItem(label, value)
    completer = QCompleter([label for _v, label in options])
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setFilterMode(Qt.MatchContains)
    combo.setCompleter(completer)


def _normalize_typed_digits(combo: QComboBox, text: str) -> None:
    """ارقامِ فارسی/عربیِ تایپ‌شده را بی‌درنگ به ASCII تبدیل می‌کند — چون
    کدهایِ حساب/تفصیلی همیشه با ارقامِ ASCII ذخیره شده‌اند و جستجو بدونِ
    این تبدیل، با تایپِ ارقامِ فارسی هیچ‌چیز پیدا نمی‌کند."""
    converted = numerals.to_ascii_digits(text)
    if converted != text:
        line_edit = combo.lineEdit()
        cursor = line_edit.cursorPosition()
        line_edit.setText(converted)
        line_edit.setCursorPosition(cursor)


def _display_name_only(text: str) -> str:
    """طبقِ درخواستِ صریح: در نوارِ خلاصه، فقط نامِ انتخاب‌شده (بدونِ کدِ
    جلویِ آن) نمایش داده شود — چون تمامِ کمبوهایِ این فرم با الگویِ ثابتِ
    «کد — نام» ساخته می‌شوند، جداکردن از رویِ آخرین رخدادِ « — » کافی است."""
    if " — " in text:
        return text.rsplit(" — ", 1)[-1].strip()
    return text.strip()


def _clear_if_unmatched(combo: QComboBox) -> None:
    """اگر با ترکِ فیلد، متنِ تایپ‌شده دقیقاً با هیچ گزینه‌ای یکی نباشد،
    انتخاب را به حالتِ خالی برمی‌گرداند — وگرنه ممکن است یک متنِ‌ ناقص/غلط
    با یک account_id قبلی/نامعتبر همراه بماند و سند به حسابِ اشتباه ثبت شود.

    نکته: مکان‌نما همیشه به ابتدایِ متن برمی‌گردد — وگرنه فیلد رویِ آخرِ
    متنِ تایپ‌شده اسکرول‌شده می‌ماند و شروعِ برچسبِ حساب/تفصیلی (که معمولاً
    مهم‌تر است) دیده نمی‌شود."""
    if combo.findText(combo.currentText(), Qt.MatchExactly) < 0:
        combo.setCurrentIndex(0)
    combo.lineEdit().setCursorPosition(0)


class _AmountField(QLineEdit):
    """فیلدِ مبلغ با ارقامِ فارسیِ زنده + گروه‌بندیِ سه‌رقمی — جایگزینِ
    QDoubleSpinBox که همیشه ارقامِ ASCII نشان می‌داد (حتی با زبانِ فارسی)
    و فقط بعدِ تأیید/ازدست‌دادنِ فوکوس گروه‌بندی می‌کرد، نه حینِ تایپ.

    رابطِ (.value/.setValue/.valueChanged) با QDoubleSpinBoxِ قبلی سازگار
    نگه داشته شده تا محلِ استفاده تغییرِ کمی نیاز داشته باشد."""

    valueChanged = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self._value = 0.0
        self._decimals = 0
        self.setAlignment(Qt.AlignCenter)
        self._set_display()
        self.textEdited.connect(self._on_text_edited)
        self.editingFinished.connect(self._set_display)

    def setDecimals(self, decimals: int) -> None:
        self._decimals = decimals
        self._set_display()

    def setRange(self, _minimum: float, _maximum: float) -> None:
        pass  # فقط برایِ سازگاریِ رابط؛ این فیلد مقدارِ منفی تولید نمی‌کند.

    def setGroupSeparatorShown(self, _shown: bool) -> None:
        pass  # این فیلد همیشه گروه‌بندی‌شده نمایش می‌دهد.

    def value(self) -> float:
        return self._value

    def setValue(self, value: float) -> None:
        value = float(value)
        changed = value != self._value
        self._value = value
        self._set_display()
        if changed:
            self.valueChanged.emit(self._value)

    def _quantize(self, value: float) -> decimal.Decimal:
        quant = decimal.Decimal(1).scaleb(-self._decimals) if self._decimals else decimal.Decimal(1)
        return decimal.Decimal(str(value)).quantize(quant, rounding=decimal.ROUND_HALF_UP)

    def _format(self, value: float) -> str:
        quantized = self._quantize(value)
        text = f"{quantized:,.{self._decimals}f}" if self._decimals else f"{int(quantized):,}"
        return numerals.to_persian_digits(text)

    def _set_display(self) -> None:
        self.blockSignals(True)
        self.setText(self._format(self._value))
        self.setCursorPosition(0)
        self.blockSignals(False)

    def _on_text_edited(self, text: str) -> None:
        cursor = self.cursorPosition()
        ascii_text = numerals.to_ascii_digits(text)
        digits_before_cursor = len(re.sub(r"[^0-9]", "", ascii_text[:cursor]))
        raw = re.sub(r"[^0-9.]", "", ascii_text)
        if self._decimals == 0:
            raw = raw.replace(".", "")
        elif raw.count(".") > 1:
            first, rest = raw.split(".", 1)
            raw = first + "." + rest.replace(".", "")

        if raw in ("", "."):
            self._value = 0.0
            grouped = raw
        else:
            if "." in raw:
                int_part, frac_part = raw.split(".", 1)
                frac_part = frac_part[: self._decimals]
            else:
                int_part, frac_part = raw, None
            int_part = int_part.lstrip("0") or "0"
            grouped = f"{int(int_part):,}"
            if frac_part is not None:
                grouped += "." + frac_part
            elif raw.endswith("."):
                grouped += "."
            self._value = float(raw) if raw not in ("", ".") else 0.0

        if digits_before_cursor == 0:
            new_cursor = 0
        else:
            new_cursor = len(grouped)
            seen_digits = 0
            for i, ch in enumerate(grouped):
                if ch.isdigit():
                    seen_digits += 1
                if seen_digits >= digits_before_cursor:
                    new_cursor = i + 1
                    break

        persian = numerals.to_persian_digits(grouped)
        self.blockSignals(True)
        self.setText(persian)
        self.setCursorPosition(new_cursor)
        self.blockSignals(False)
        self.valueChanged.emit(self._value)


def _make_searchable_combo(options: list[tuple[int, str]]) -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    _fill_options(combo, options)
    line_edit = combo.lineEdit()
    line_edit.textEdited.connect(lambda text, c=combo: _normalize_typed_digits(c, text))
    line_edit.editingFinished.connect(lambda c=combo: _clear_if_unmatched(c))
    return combo


class _LineRow:
    """یک ردیفِ سند — مجموعه‌ای از ویجت‌هایی که به‌عنوانِ cellWidget درونِ
    QTableWidgetِ صفحه جا می‌گیرند (خودش QWidget نیست)."""

    def __init__(self, screen: "JournalEntryScreen", table: QTableWidget) -> None:
        self._screen = screen
        self._table = table
        self.account_id: int | None = None
        # ارز/نرخِ ردیف — فقط برایِ ردیف‌هایِ بارگذاری‌شده از سندِ موجود پر
        # می‌شود؛ ردیفِ تازه با None (=ارزِ پایه‌ی شرکت) ثبت می‌شود.
        self.currency_id: int | None = None
        self.exchange_rate: decimal.Decimal | None = None
        # طبقِ بازخوردِ صریح: مرکزِ هزینه و پروژه ستونِ اختصاصیِ خودشان را
        # دارند (چون پرکاربردترند و باید مستقیم قابلِ‌جستجو باشند)؛ بقیه‌ی
        # نوع‌بُعدهایِ الزامیِ حساب (تفصیلیِ شخص، صندوق، بانک، کالا، ...)
        # همه در همین یک ستونِ «تفصیلی» یک‌جا جمع می‌شوند — دیگر پنجره‌ی
        # جداگانه‌ای لازم نیست.
        self._required_dimensions: list[dimensions_service.RequiredDimension] = []
        # نگاشتِ detail_account_id -> dimension_type_id برایِ گزینه‌هایِ
        # جاریِ کمبویِ تفصیلی — چون detail_account_id خودش کلیدِ سراسریِ
        # یکتاست (نه فقط یکتا در نوع‌بُعدِ خودش)، همان را به‌عنوانِ itemData
        # ذخیره می‌کنیم (نه یک تاپلِ (نوع‌بُعد، شناسه)؛ در PySide6، findData
        # تاپل‌هایِ هم‌ارزش-ولی-غیرِهم‌هویت را برابر تشخیص نمی‌دهد).
        self._detail_dimension_type_by_id: dict[int, int] = {}

        self.account_combo = _make_searchable_combo(screen.account_options)
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)
        self.account_combo.lineEdit().returnPressed.connect(self._on_account_return)

        self.detail_combo = _make_searchable_combo([])
        self.detail_combo.lineEdit().returnPressed.connect(self._on_detail_return)
        self.detail_combo.currentIndexChanged.connect(lambda _i: self._screen._refresh_preview_strip())

        self.cost_center_combo = _make_searchable_combo([])
        self.cost_center_combo.setEnabled(False)
        self.cost_center_combo.lineEdit().returnPressed.connect(self._on_cost_center_return)
        self.cost_center_combo.currentIndexChanged.connect(lambda _i: self._screen._refresh_preview_strip())

        self.project_combo = _make_searchable_combo([])
        self.project_combo.setEnabled(False)
        self.project_combo.lineEdit().returnPressed.connect(self._on_project_return)
        self.project_combo.currentIndexChanged.connect(lambda _i: self._screen._refresh_preview_strip())

        self.description_field = QLineEdit()
        self._attach_description_completer()
        self.description_field.returnPressed.connect(lambda: self.debit_field.setFocus())
        self.description_field.editingFinished.connect(lambda: self.description_field.setCursorPosition(0))

        self.debit_field = _AmountField()
        self.debit_field.setDecimals(screen.currency_decimal_places)
        self.debit_field.valueChanged.connect(self._on_debit_changed)
        self.debit_field.returnPressed.connect(self._on_debit_return)

        self.credit_field = _AmountField()
        self.credit_field.setDecimals(screen.currency_decimal_places)
        self.credit_field.valueChanged.connect(self._on_credit_changed)
        self.credit_field.returnPressed.connect(lambda: screen.focus_next_row_after(self))

        self.remove_button = QPushButton("✕")
        self.remove_button.setObjectName("dangerButton")
        self.remove_button.setFixedWidth(34)
        self.remove_button.setStyleSheet("padding: 2px 0px;")
        self.remove_button.clicked.connect(lambda: screen.remove_line(self))

    def _attach_description_completer(self) -> None:
        completer = QCompleter(self._screen.recent_line_descriptions)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.description_field.setCompleter(completer)

    def install(self, row: int) -> None:
        table = self._table
        row_no_item = QTableWidgetItem(str(row + 1))
        row_no_item.setTextAlignment(Qt.AlignCenter)
        row_no_item.setFlags(Qt.ItemIsEnabled)
        table.setItem(row, _COL_ROW_NO, row_no_item)
        table.setCellWidget(row, _COL_ACCOUNT, self.account_combo)
        table.setCellWidget(row, _COL_DETAIL, self.detail_combo)
        table.setCellWidget(row, _COL_COST_CENTER, self.cost_center_combo)
        table.setCellWidget(row, _COL_PROJECT, self.project_combo)
        table.setCellWidget(row, _COL_DESC, self.description_field)
        table.setCellWidget(row, _COL_DEBIT, self.debit_field)
        table.setCellWidget(row, _COL_CREDIT, self.credit_field)
        table.setCellWidget(row, _COL_REMOVE, self.remove_button)

    def _on_debit_changed(self, value: float) -> None:
        if value:
            self.credit_field.blockSignals(True)
            self.credit_field.setValue(0)
            self.credit_field.blockSignals(False)
            self.debit_field.setToolTip(
                numerals.amount_to_words(decimal.Decimal(str(value)), unit=self._screen.currency_symbol or "ریال")
            )
        else:
            self.debit_field.setToolTip("")
        self._screen.update_balance()

    def _on_credit_changed(self, value: float) -> None:
        if value:
            self.debit_field.blockSignals(True)
            self.debit_field.setValue(0)
            self.debit_field.blockSignals(False)
            self.credit_field.setToolTip(
                numerals.amount_to_words(decimal.Decimal(str(value)), unit=self._screen.currency_symbol or "ریال")
            )
        else:
            self.credit_field.setToolTip("")
        self._screen.update_balance()

    def _on_account_changed(self, _index: int) -> None:
        self.account_id = self.account_combo.currentData()
        self._refresh_dimension_ui()
        self._screen._refresh_preview_strip()

    def _on_account_return(self) -> None:
        """زنجیره‌ی Enter: حساب -> تفصیلی (اگر حسابی انتخاب شده باشد)."""
        if self.account_id is None:
            return
        self.detail_combo.setFocus()
        self.detail_combo.lineEdit().selectAll()

    def _on_detail_return(self) -> None:
        """زنجیره‌ی Enter: تفصیلی -> مرکزِ هزینه (اگر لازم باشد) -> پروژه
        (اگر لازم باشد) -> شرحِ ردیف."""
        if self.cost_center_combo.isEnabled():
            self.cost_center_combo.setFocus()
            self.cost_center_combo.lineEdit().selectAll()
            return
        self._advance_after_cost_center()

    def _on_cost_center_return(self) -> None:
        self._advance_after_cost_center()

    def _advance_after_cost_center(self) -> None:
        if self.project_combo.isEnabled():
            self.project_combo.setFocus()
            self.project_combo.lineEdit().selectAll()
            return
        self._advance_after_project()

    def _on_project_return(self) -> None:
        self._advance_after_project()

    def _advance_after_project(self) -> None:
        self.description_field.setFocus()
        self.description_field.selectAll()

    def _on_debit_return(self) -> None:
        """زنجیره‌ی Enter: اگر بدهکار صفر/خالی بماند برو به بستانکار، وگرنه
        (چون ردیف بدهکار پر شده) مستقیم به ردیفِ بعدی."""
        if self.debit_field.value() == 0:
            self.credit_field.setFocus()
            self.credit_field.selectAll()
        else:
            self._screen.focus_next_row_after(self)

    def _refresh_dimension_ui(self) -> None:
        if self.account_id is None:
            _fill_options(self.detail_combo, [])
            _fill_options(self.cost_center_combo, [])
            _fill_options(self.project_combo, [])
            self.cost_center_combo.setEnabled(False)
            self.project_combo.setEnabled(False)
            self._required_dimensions = []
            self._detail_dimension_type_by_id = {}
            return

        self._required_dimensions = dimensions_service.get_required_dimensions_for_account(self.account_id)

        # طبقِ بازخوردِ صریح: ستونِ «تفصیلی» همه‌ی نوع‌بُعدهایِ الزامیِ این
        # حساب را به‌جز مرکزِ هزینه/پروژه (که ستونِ اختصاصیِ خودشان را
        # دارند) یک‌جا نشان می‌دهد — تفصیلیِ اشخاص همچنان همیشه حاضر است
        # (چه الزامی باشد چه نه)، بقیه (صندوق/بانک/کالا/...) فقط وقتی که
        # برایِ این حساب الزامی شده باشند.
        person_dimension_type_id = dimensions_service.get_person_dimension_type_id(self._screen.company_id)
        person_group_ids = [
            g.person_group_id for g in dimensions_service.get_required_person_groups_for_account(self.account_id)
        ]
        other_dims = [
            d
            for d in self._required_dimensions
            if d.code not in (dimensions_service.COST_CENTER_CODE, dimensions_service.PROJECT_CODE)
        ]
        # طبقِ بازخوردِ صریح: اگر این حساب هرنوع الزامِ تفصیلی داشته باشد
        # (چه محدودیتِ گروهِ شخص، چه نوع‌بُعدِ دیگری مثلِ صندوق)، گزینه‌ی
        # «بدون تفصیلی» اصلاً نباید پیشنهاد شود — انتخابِ واقعی الزامی است.
        # وگرنه (حسابی که هیچ الزامی ندارد)، «بدون تفصیلی» به‌طورِ پیش‌فرض
        # انتخاب می‌شود (نه فقط در فهرست باشد).
        has_requirement = bool(person_group_ids) or bool(other_dims)

        persons = dimensions_service.list_active_persons(self._screen.company_id)
        if person_group_ids:
            persons = [p for p in persons if p.person_group_id in person_group_ids]
        elif has_requirement:
            persons = [p for p in persons if p.code != dimensions_service.NO_DETAIL_CODE]
        self._detail_dimension_type_by_id = {p.detail_account_id: person_dimension_type_id for p in persons}
        detail_options = [(p.detail_account_id, f"{p.full_code} — {p.name or ''}") for p in persons]

        for dim in other_dims:
            label_prefix = dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(dim.code, dim.code)
            for d in dim.detail_accounts:
                self._detail_dimension_type_by_id[d.detail_account_id] = dim.dimension_type_id
                detail_options.append((d.detail_account_id, f"{label_prefix}: {d.full_code} — {d.name or ''}"))
        _fill_options(self.detail_combo, detail_options)
        self.detail_combo.setToolTip("تفصیلی (الزامی)" if has_requirement else "")

        if not has_requirement:
            no_detail_id = next((p.detail_account_id for p in persons if p.code == dimensions_service.NO_DETAIL_CODE), None)
            if no_detail_id is not None:
                idx = self.detail_combo.findData(no_detail_id)
                if idx >= 0:
                    self.detail_combo.setCurrentIndex(idx)

        cost_center_dim = next(
            (d for d in self._required_dimensions if d.code == dimensions_service.COST_CENTER_CODE), None
        )
        _fill_options(
            self.cost_center_combo,
            [(d.detail_account_id, f"{d.full_code} — {d.name or ''}") for d in cost_center_dim.detail_accounts]
            if cost_center_dim
            else [],
        )
        self.cost_center_combo.setEnabled(cost_center_dim is not None)
        self.cost_center_combo.setToolTip("مرکزِ هزینه (الزامی)" if cost_center_dim else "")

        project_dim = next((d for d in self._required_dimensions if d.code == dimensions_service.PROJECT_CODE), None)
        _fill_options(
            self.project_combo,
            [(d.detail_account_id, f"{d.full_code} — {d.name or ''}") for d in project_dim.detail_accounts]
            if project_dim
            else [],
        )
        self.project_combo.setEnabled(project_dim is not None)
        self.project_combo.setToolTip("پروژه (الزامی)" if project_dim else "")

    def collect_details(self) -> dict[int, int]:
        details: dict[int, int] = {}
        detail_account_id = self.detail_combo.currentData()
        if detail_account_id is not None:
            dimension_type_id = self._detail_dimension_type_by_id.get(detail_account_id)
            if dimension_type_id is not None:
                details[dimension_type_id] = detail_account_id
        cost_center_detail_id = self.cost_center_combo.currentData()
        if cost_center_detail_id is not None:
            dimension_type_id = dimensions_service.get_specialized_dimension_type_id(
                self._screen.company_id, dimensions_service.COST_CENTER_CODE
            )
            details[dimension_type_id] = cost_center_detail_id
        project_detail_id = self.project_combo.currentData()
        if project_detail_id is not None:
            dimension_type_id = dimensions_service.get_specialized_dimension_type_id(
                self._screen.company_id, dimensions_service.PROJECT_CODE
            )
            details[dimension_type_id] = project_detail_id
        return details

    def to_line_input(self) -> je_service.LineInput | None:
        if self.account_id is None:
            return None
        debit = decimal.Decimal(str(self.debit_field.value()))
        credit = decimal.Decimal(str(self.credit_field.value()))
        if debit == 0 and credit == 0:
            return None
        return je_service.LineInput(
            account_id=self.account_id,
            description=self.description_field.text().strip(),
            debit=debit,
            credit=credit,
            details=self.collect_details(),
            currency_id=self.currency_id,
            exchange_rate=self.exchange_rate,
        )

    def load_from(self, line: je_service.LineInput, account_label: str) -> None:
        index = self.account_combo.findData(line.account_id)
        if index < 0:
            self.account_combo.addItem(account_label, line.account_id)
            index = self.account_combo.count() - 1
        self.account_combo.setCurrentIndex(index)
        self.account_combo.lineEdit().setCursorPosition(0)
        self.account_id = line.account_id
        self.currency_id = line.currency_id
        self.exchange_rate = line.exchange_rate
        self._refresh_dimension_ui()

        cost_center_dimension_type_id = dimensions_service.get_specialized_dimension_type_id(
            self._screen.company_id, dimensions_service.COST_CENTER_CODE
        )
        project_dimension_type_id = dimensions_service.get_specialized_dimension_type_id(
            self._screen.company_id, dimensions_service.PROJECT_CODE
        )
        excluded_type_ids = {cost_center_dimension_type_id, project_dimension_type_id}
        for dim_id, detail_id in line.details.items():
            if dim_id in excluded_type_ids:
                continue
            idx = self.detail_combo.findData(detail_id)
            if idx >= 0:
                self.detail_combo.setCurrentIndex(idx)
                break
        self.detail_combo.lineEdit().setCursorPosition(0)

        cost_center_detail_id = line.details.get(cost_center_dimension_type_id)
        if cost_center_detail_id is not None:
            idx = self.cost_center_combo.findData(cost_center_detail_id)
            if idx >= 0:
                self.cost_center_combo.setCurrentIndex(idx)
        self.cost_center_combo.lineEdit().setCursorPosition(0)

        project_detail_id = line.details.get(project_dimension_type_id)
        if project_detail_id is not None:
            idx = self.project_combo.findData(project_detail_id)
            if idx >= 0:
                self.project_combo.setCurrentIndex(idx)
        self.project_combo.lineEdit().setCursorPosition(0)

        self.description_field.setText(line.description or "")
        self.description_field.setCursorPosition(0)
        self.debit_field.setValue(float(line.debit))
        self.credit_field.setValue(float(line.credit))


class JournalEntryScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.company_id: int | None = None
        self.account_options: list[tuple[int, str]] = []
        self.recent_line_descriptions: list[str] = []
        # طبقِ ارزِ پایه‌ی شرکت (تنظیماتِ ارزها) — نه یک عددِ ثابت.
        self.currency_decimal_places = 0
        self.currency_symbol: str | None = None
        self._line_rows: list[_LineRow] = []
        self._editing_journal_entry_id: int | None = None
        self._editing_registration_at: datetime.datetime | None = None
        # widget -> (ردیف، نامِ فیلد) — برایِ ناوبریِ کلیدهایِ بالا/پایین
        # بینِ ردیف‌هایِ سند.
        self._nav_widgets: dict[QWidget, tuple[_LineRow, str]] = {}
        # ردیفِ «جاری» برایِ نوارِ خلاصه — آخرین ردیفی که فوکوس داشته.
        self._active_row: _LineRow | None = None

        # طبقِ گزارشِ صریح (با اعدادِ واقعیِ فرستاده‌شده تأیید شد): قبلاً
        # کلِ صفحه (هدر+ردیف‌ها+فوتر) در یک QScrollAreaِ واحد بود که فوتر
        # را از دیدرس خارج می‌کرد؛ حذفِ کاملِ آن QScrollArea هم رگرسیونِ
        # تازه‌ای ساخت (چون فونتِ فارسیِ واقعیِ کاربر بلندتر از فونتِ
        # آزمایشیِ ماست، حداقلِ ارتفاعِ کلِ صفحه از ارتفاعِ واقعیِ
        # صفحه‌نمایش بیشتر می‌شد و دیگر هیچ اسکرولی برایِ رسیدن به فوتر
        # نبود). راه‌حلِ درست (هم‌راستا با فیکسِ قدیمیِ Kivyِ همین فرم):
        # فقط کارتِ ردیف‌ها درونِ یک QScrollAreaِ اختصاصی با حداقل‌ارتفاعِ
        # کم قرار می‌گیرد — هدر و فوتر مستقیماً در چیدمانِ اصلی و همیشه
        # ثابت/قابلِ‌مشاهده‌اند، مستقل از اینکه فونت/صفحه‌نمایش چقدر بلند/
        # کوتاه باشد.
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(24, 24, 24, 24)
        root_layout.setSpacing(12)
        outer = root_layout

        header_card = QWidget()
        header_card.setObjectName("card")
        header_layout = QGridLayout(header_card)
        header_layout.setContentsMargins(18, 18, 18, 18)
        header_layout.setSpacing(8)

        self.form_title = QLabel("صدورِ سندِ جدید")
        self.form_title.setObjectName("pageTitle")
        header_layout.addWidget(self.form_title, 0, 0, 1, 4)

        self.registration_label = QLabel("")
        self.registration_label.setObjectName("sectionHint")
        header_layout.addWidget(self.registration_label, 0, 3, 1, 1, Qt.AlignLeft)

        header_layout.addWidget(QLabel("تاریخِ سند"), 1, 0)
        self.date_field = JalaliDateEdit("تاریخِ سند (۱۴۰۳/۰۴/۲۸)")
        self.date_field.setMaximumWidth(140)
        header_layout.addWidget(self.date_field, 1, 1)

        header_layout.addWidget(QLabel("شرحِ سند"), 1, 2)
        self.description_field = QLineEdit()
        self.description_field.setMinimumWidth(280)
        header_layout.addWidget(self.description_field, 1, 3)

        header_layout.addWidget(QLabel("شماره‌ی عطف"), 2, 0)
        self.alt_number_field = QLineEdit()
        self.alt_number_field.setMaximumWidth(140)
        header_layout.addWidget(self.alt_number_field, 2, 1)

        self.draft_checkbox = QCheckBox("پیش‌نویس (غیرِتراز هم قابلِ‌ذخیره)")
        header_layout.addWidget(self.draft_checkbox, 2, 3)

        # ستونِ شرحِ سند (۳) بیشترینِ فضایِ اضافه را می‌گیرد — طبقِ بازخورد،
        # تاریخ/شماره‌یِ عطف (ستونِ ۱) عرضِ کوچکِ ثابت کافی است.
        header_layout.setColumnStretch(0, 0)
        header_layout.setColumnStretch(1, 0)
        header_layout.setColumnStretch(2, 0)
        header_layout.setColumnStretch(3, 1)

        # زنجیره‌ی Enter در هدر: تاریخ -> شرحِ سند -> شماره‌ی عطف -> ردیفِ اول.
        self.date_field.returnPressed.connect(lambda: self.description_field.setFocus())
        self.description_field.returnPressed.connect(lambda: self.alt_number_field.setFocus())
        self.alt_number_field.returnPressed.connect(self._focus_first_row_account)
        self.description_field.editingFinished.connect(lambda: self.description_field.setCursorPosition(0))
        self.alt_number_field.editingFinished.connect(lambda: self.alt_number_field.setCursorPosition(0))

        outer.addWidget(header_card)

        # طبقِ درخواستِ صریح: نوارِ خلاصه‌یِ عناوینِ انتخاب‌شده (بدونِ کد) —
        # حساب/تفصیلی/مرکزِ هزینه/پروژه‌یِ ردیفِ جاری (آخرین ردیفی که فوکوس
        # داشته)، با رنگِ متفاوت برایِ حساب در برابرِ تفصیلی/مرکزِ هزینه/پروژه.
        preview_card = QWidget()
        preview_card.setObjectName("card")
        preview_layout = QHBoxLayout(preview_card)
        preview_layout.setContentsMargins(14, 10, 14, 10)
        preview_layout.setSpacing(24)
        self._preview_value_labels: dict[str, QLabel] = {}
        for key, title in (
            ("account", "حساب"),
            ("detail", "تفصیلی"),
            ("cost_center", "مرکزِ هزینه"),
            ("project", "پروژه"),
        ):
            value_color = theme.PRIMARY if key == "account" else theme.SUCCESS
            label = QLabel()
            label.setTextFormat(Qt.RichText)
            label.setText(
                f'<span style="color:{theme.TEXT_SECONDARY};">{title}: </span>'
                f'<span style="color:{value_color}; font-weight:600;">—</span>'
            )
            self._preview_value_labels[key] = label
            preview_layout.addWidget(label)
        preview_layout.addStretch(1)
        outer.addWidget(preview_card)

        add_line_button = QPushButton("+ افزودنِ ردیف")
        add_line_button.setObjectName("flatButton")
        add_line_button.clicked.connect(lambda: self.add_line())
        outer.addWidget(add_line_button)

        table_card = QWidget()
        table_card.setObjectName("card")
        table_card_layout = QVBoxLayout(table_card)
        table_card_layout.setContentsMargins(6, 6, 6, 6)

        self.table = QTableWidget(0, len(_COLUMN_LABELS))
        self.table.setHorizontalHeaderLabels(_COLUMN_LABELS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # طبقِ بازخورد: ارتفاعِ ردیف ۴۴ کافی نبود — فیلدها (با پدینگ+حاشیه)
        # حسِ فشرده/نصفه داشتند؛ ۵۲ فضایِ عمودیِ راحت‌تری به متن می‌دهد.
        self.table.verticalHeader().setDefaultSectionSize(52)
        self.table.setMinimumHeight(160)
        header = self.table.horizontalHeader()
        # طبقِ بازخورد: حساب/تفصیلی نباید غالب/بزرگ‌تر از بقیه باشند —
        # عرضِ ثابتِ متعادل می‌گیرند؛ شرحِ ردیف (تنها ستونِ Stretch) بیشترین
        # فضا را می‌گیرد؛ بدهکار/بستانکار عرضِ ثابتِ بزرگ‌تر برایِ خوانایی.
        header.setSectionResizeMode(_COL_ROW_NO, QHeaderView.Fixed)
        header.setSectionResizeMode(_COL_ACCOUNT, QHeaderView.Interactive)
        header.setSectionResizeMode(_COL_DETAIL, QHeaderView.Interactive)
        header.setSectionResizeMode(_COL_COST_CENTER, QHeaderView.Interactive)
        header.setSectionResizeMode(_COL_PROJECT, QHeaderView.Interactive)
        header.setSectionResizeMode(_COL_DESC, QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_DEBIT, QHeaderView.Interactive)
        header.setSectionResizeMode(_COL_CREDIT, QHeaderView.Interactive)
        header.setSectionResizeMode(_COL_REMOVE, QHeaderView.Fixed)
        self.table.setColumnWidth(_COL_ROW_NO, 44)
        self.table.setColumnWidth(_COL_ACCOUNT, 220)
        self.table.setColumnWidth(_COL_DETAIL, 190)
        # طبقِ بازخوردِ صریح: عرضِ مرکزِ هزینه/پروژه خیلی زیاد بود — چون
        # این دو دیگر گزینه‌یِ تنهایِ همه‌ی ابعاد نیستند (بقیه به ستونِ
        # تفصیلی منتقل شدند)، عرضِ کوچک‌تر برایشان کافی است.
        self.table.setColumnWidth(_COL_COST_CENTER, 110)
        self.table.setColumnWidth(_COL_PROJECT, 110)
        self.table.setColumnWidth(_COL_DEBIT, 140)
        self.table.setColumnWidth(_COL_CREDIT, 140)
        self.table.setColumnWidth(_COL_REMOVE, 40)
        table_card_layout.addWidget(self.table)

        # طبقِ گزارشِ صریح (با اعدادِ واقعی تأیید شد): حذفِ کاملِ
        # QScrollAreaِ دورِ صفحه (تلاشِ قبلی) یک رگرسیونِ تازه ساخت —
        # چون فونتِ فارسیِ واقعی (Vazirmatn، lineSpacing≈۲۳px) بلندتر از
        # فونتِ آزمایشیِ ماست، حداقلِ ارتفاعِ لازمِ کلِ صفحه (هدر+پیش‌نمایش+
        # جدول+فوتر) از ارتفاعِ واقعیِ صفحه‌نمایشِ کاربر (۸۵۲px) بیشتر
        # می‌شد و چون دیگر هیچ اسکرولی نبود، فوتر کاملاً خارج از دیدرس
        # می‌ماند. راه‌حلِ درست (هم‌راستا با فیکسِ قدیمیِ Kivy): فقط
        # کارتِ ردیف‌ها درونِ یک QScrollAreaِ اختصاصی با حداقل‌ارتفاعِ کم
        # قرار می‌گیرد — این‌طوری حداقلِ ارتفاعِ کلِ صفحه هرگز به حداقلِ
        # ارتفاعِ خودِ جدول (که می‌تواند زیاد باشد) وابسته نیست، ولی وقتی
        # فضا کافی است (اکثرِ اوقات)، جدول با stretch=1 همان فضایِ اضافه
        # را می‌گیرد؛ هدر و فوتر همچنان مستقیماً در چیدمانِ اصلی و همیشه
        # قابلِ‌مشاهده‌اند.
        table_scroll = QScrollArea()
        table_scroll.setWidgetResizable(True)
        table_scroll.setFrameShape(QFrame.NoFrame)
        table_scroll.setMinimumHeight(120)
        table_scroll.setWidget(table_card)
        outer.addWidget(table_scroll, stretch=1)

        self.amount_words_label = QLabel("")
        self.amount_words_label.setObjectName("sectionHint")
        outer.addWidget(self.amount_words_label)

        footer = QHBoxLayout()
        self.balance_label = QLabel("")
        footer.addWidget(self.balance_label)
        footer.addStretch(1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        footer.addWidget(self.status_label)

        self.cancel_edit_button = QPushButton("لغوِ ویرایش (Esc)")
        self.cancel_edit_button.setObjectName("flatButton")
        self.cancel_edit_button.clicked.connect(lambda: self._reset_form())
        footer.addWidget(self.cancel_edit_button)

        self.delete_button = QPushButton("حذفِ سند")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self._delete_current_entry)
        footer.addWidget(self.delete_button)

        self.save_button = QPushButton("ثبتِ سند")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save)
        footer.addWidget(self.save_button)

        new_button = QPushButton("سندِ جدید")
        new_button.setObjectName("flatButton")
        new_button.clicked.connect(lambda: self._reset_form())
        footer.addWidget(new_button)

        outer.addLayout(footer)

        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._save)
        QShortcut(QKeySequence("Escape"), self, activated=self._reset_form)
        QShortcut(QKeySequence("Ctrl+Delete"), self, activated=self._delete_current_entry)

        QApplication.instance().focusChanged.connect(self._on_focus_changed)

        self._update_footer_for_mode()

    def refresh(self) -> None:
        self.company_id = session.current_company.company_id if session.current_company else None
        if self.company_id is None:
            return
        accounts = coa_service.list_postable_accounts(self.company_id)
        self.account_options = [(a.account_id, f"{a.full_code} — {a.name}") for a in accounts]
        self.recent_line_descriptions = je_service.list_recent_line_descriptions(self.company_id)

        base_currency_id = session.current_company.base_currency_id
        currency = next((c for c in currencies_service.list_all_currencies() if c.currency_id == base_currency_id), None)
        self.currency_decimal_places = currency.decimal_places if currency else 0
        self.currency_symbol = currency.symbol if currency else None
        for row in self._line_rows:
            row.debit_field.setDecimals(self.currency_decimal_places)
            row.credit_field.setDecimals(self.currency_decimal_places)

        if not self._line_rows:
            self._reset_form()
        # هر بار که این صفحه (از سایدبار) باز می‌شود، فوکوس رویِ تاریخ
        # می‌رود — شروعِ زنجیره‌ی Enter از اولین فیلد.
        self.date_field.setFocus()
        self.date_field.selectAll()

    def _reset_form(self) -> None:
        self._editing_journal_entry_id = None
        self._editing_registration_at = None
        self.form_title.setText("صدورِ سندِ جدید")
        self.date_field.setDate(datetime.date.today())
        self.alt_number_field.clear()
        self.description_field.clear()
        self.draft_checkbox.setChecked(False)
        self.status_label.setText("")
        for row in list(self._line_rows):
            self.remove_line(row, force=True)
        self.add_line()
        self.add_line()
        self._update_footer_for_mode()

    def _update_footer_for_mode(self) -> None:
        editing = self._editing_journal_entry_id is not None
        self.save_button.setText("ذخیره‌ی تغییرات" if editing else "ثبتِ سند")
        self.cancel_edit_button.setVisible(editing)
        self.delete_button.setVisible(editing)
        if editing and self._editing_registration_at is not None:
            self.registration_label.setText(f"تاریخِ ثبت: {numerals.format_jalali_datetime(self._editing_registration_at)}")
        else:
            self.registration_label.setText("")

    def add_line(self) -> _LineRow:
        row = _LineRow(self, self.table)
        self.table.insertRow(self.table.rowCount())
        row.install(self.table.rowCount() - 1)
        row._refresh_dimension_ui()
        self._line_rows.append(row)
        self._register_row_nav(row)
        self._renumber_rows()
        if self._active_row is None:
            self._active_row = row
            self._refresh_preview_strip()
        return row

    def _register_row_nav(self, row: _LineRow) -> None:
        """کلیدهایِ بالا/پایین را رویِ فیلدهایِ این ردیف قابل‌شنیدن می‌کند
        تا بشود بینِ ردیف‌هایِ پرشده جابه‌جا شد (طبقِ بازخورد).

        نکته: خودِ QComboBox (نه فقط lineEdit) هم رجیستر می‌شود — چون
        QApplication.focusChanged برایِ یک کمبویِ editable، خودِ کمبو را
        به‌عنوانِ ویجتِ فوکوس‌دار گزارش می‌کند (نه lineEdit داخلی‌اش)."""
        for combo, field in (
            (row.account_combo, "account"),
            (row.detail_combo, "detail"),
            (row.cost_center_combo, "cost_center"),
            (row.project_combo, "project"),
        ):
            self._register_nav_widget(combo.lineEdit(), row, field)
            self._register_nav_widget(combo, row, field)
        self._register_nav_widget(row.description_field, row, "description")
        self._register_nav_widget(row.debit_field, row, "debit")
        self._register_nav_widget(row.credit_field, row, "credit")

    def _register_nav_widget(self, widget: QWidget, row: _LineRow, field: str) -> None:
        self._nav_widgets[widget] = (row, field)
        widget.installEventFilter(self)

    def _unregister_row_nav(self, row: _LineRow) -> None:
        for widget in (
            row.account_combo.lineEdit(),
            row.account_combo,
            row.detail_combo.lineEdit(),
            row.detail_combo,
            row.cost_center_combo.lineEdit(),
            row.cost_center_combo,
            row.project_combo.lineEdit(),
            row.project_combo,
            row.description_field,
            row.debit_field,
            row.credit_field,
        ):
            self._nav_widgets.pop(widget, None)

    def _on_focus_changed(self, _old: QWidget | None, new: QWidget | None) -> None:
        """طبقِ درخواستِ صریح: نوارِ خلاصه باید ردیفِ «جاری» را دنبال کند —
        QApplication.focusChanged (به‌جایِ eventFilter رویِ QEvent.FocusIn)
        چون زیرِ QPAیِ offscreen، فوکوس‌شدنِ لاین‌ادیتِ داخلیِ یک کمبویِ
        editable همیشه به‌عنوانِ رخدادِ FocusIn به خودِ آن ویجت نمی‌رسد، ولی
        این سیگنالِ سراسری همیشه قابل‌اتکاست."""
        entry = self._nav_widgets.get(new)
        if entry is not None:
            row, _field = entry
            if row is not self._active_row:
                self._active_row = row
                self._refresh_preview_strip()

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Up, Qt.Key_Down):
            entry = self._nav_widgets.get(obj)
            if entry is not None:
                row, field = entry
                # اگر پاپ‌آپِ تکمیلِ خودکار (رویِ همین فیلد) باز است، بالا/
                # پایین باید بینِ گزینه‌هایِ آن پاپ‌آپ حرکت کند، نه بینِ ردیف‌ها.
                completer = obj.completer()
                popup_open = completer is not None and completer.popup().isVisible()
                if not popup_open:
                    direction = -1 if event.key() == Qt.Key_Up else 1
                    self._move_row_focus(row, field, direction)
                    return True
        return super().eventFilter(obj, event)

    def _refresh_preview_strip(self) -> None:
        """طبقِ درخواستِ صریح: نمایشِ عناوینِ حساب/تفصیلی/مرکزِ هزینه/پروژه‌یِ
        ردیفِ جاری، بدونِ کد، در نوارِ خلاصه‌یِ بالایِ جدول."""
        row = self._active_row if self._active_row in self._line_rows else (
            self._line_rows[0] if self._line_rows else None
        )
        combos = (
            {
                "account": row.account_combo,
                "detail": row.detail_combo,
                "cost_center": row.cost_center_combo,
                "project": row.project_combo,
            }
            if row is not None
            else {}
        )
        for key, label in self._preview_value_labels.items():
            combo = combos.get(key)
            name = _display_name_only(combo.currentText()) if combo is not None else ""
            value_color = theme.PRIMARY if key == "account" else theme.SUCCESS
            title = {"account": "حساب", "detail": "تفصیلی", "cost_center": "مرکزِ هزینه", "project": "پروژه"}[key]
            label.setText(
                f'<span style="color:{theme.TEXT_SECONDARY};">{title}: </span>'
                f'<span style="color:{value_color}; font-weight:600;">{name or "—"}</span>'
            )

    def _move_row_focus(self, row: _LineRow, field: str, direction: int) -> None:
        index = self._line_rows.index(row)
        target_index = index + direction
        if not (0 <= target_index < len(self._line_rows)):
            return
        target_row = self._line_rows[target_index]
        column = {
            "account": _COL_ACCOUNT,
            "detail": _COL_DETAIL,
            "cost_center": _COL_COST_CENTER,
            "project": _COL_PROJECT,
            "description": _COL_DESC,
            "debit": _COL_DEBIT,
            "credit": _COL_CREDIT,
        }[field]
        self.table.setCurrentCell(target_index, column)
        combo_attrs = {
            "account": "account_combo",
            "detail": "detail_combo",
            "cost_center": "cost_center_combo",
            "project": "project_combo",
        }
        if field in combo_attrs:
            widget = getattr(target_row, combo_attrs[field])
            widget.setFocus()
            widget.lineEdit().selectAll()
        else:
            widget = getattr(target_row, f"{field}_field")
            widget.setFocus()
            widget.selectAll()

    def focus_next_row_after(self, row: _LineRow) -> None:
        """زنجیره‌ی Enter: بستانکار (یا بدهکارِ پرشده) -> ردیفِ بعدی؛ اگر
        ردیفِ بعدی وجود نداشته باشد، تازه ساخته می‌شود. شرحِ ردیف همیشه
        (چه ردیفِ بعدی موجود باشد چه تازه ساخته شود) به ردیفِ بعدی منتقل
        می‌شود — تا لازم نباشد دوباره تایپ شود.

        نکته: اگر ردیفِ فعلی هنوز ناقص است (حساب انتخاب نشده، یا هم بدهکار
        و هم بستانکار صفرند)، هیچ ردیفِ تازه‌ای ساخته نمی‌شود — تا Enterِ
        تصادفی رویِ ردیفِ خالی، ردیف‌هایِ اضافیِ بی‌مصرف نسازد."""
        if row.account_id is None or (row.debit_field.value() == 0 and row.credit_field.value() == 0):
            return
        description = row.description_field.text()
        if row is self._line_rows[-1]:
            target = self.add_line()
        else:
            target = self._line_rows[self._line_rows.index(row) + 1]
        if description and not target.description_field.text():
            target.description_field.setText(description)
            target.description_field.setCursorPosition(0)
        self.table.setCurrentCell(self._line_rows.index(target), _COL_ACCOUNT)
        target.account_combo.setFocus()
        target.account_combo.lineEdit().selectAll()

    def _focus_first_row_account(self) -> None:
        if self._line_rows:
            self.table.setCurrentCell(0, _COL_ACCOUNT)
            self._line_rows[0].account_combo.setFocus()
            self._line_rows[0].account_combo.lineEdit().selectAll()

    def remove_line(self, row: _LineRow, *, force: bool = False) -> None:
        if not force and len(self._line_rows) <= 2:
            return
        index = self._line_rows.index(row)
        self.table.removeRow(index)
        self._line_rows.remove(row)
        self._unregister_row_nav(row)
        self._renumber_rows()
        self.update_balance()
        if self._active_row is row:
            self._active_row = None
            self._refresh_preview_strip()

    def _renumber_rows(self) -> None:
        for i in range(len(self._line_rows)):
            item = self.table.item(i, _COL_ROW_NO)
            if item is not None:
                item.setText(str(i + 1))

    def update_balance(self) -> None:
        total_debit = sum((decimal.Decimal(str(r.debit_field.value())) for r in self._line_rows), decimal.Decimal(0))
        total_credit = sum((decimal.Decimal(str(r.credit_field.value())) for r in self._line_rows), decimal.Decimal(0))
        debit_text = numerals.format_money(total_debit, self.currency_decimal_places, self.currency_symbol)
        credit_text = numerals.format_money(total_credit, self.currency_decimal_places, self.currency_symbol)
        if total_debit == total_credit and total_debit > 0:
            theme.set_status_label(
                self.balance_label, f"تراز — بدهکار: {debit_text} | بستانکار: {credit_text}", ok=True
            )
        else:
            theme.set_status_label(
                self.balance_label, f"غیرِ تراز — بدهکار: {debit_text} | بستانکار: {credit_text}", ok=False
            )

        reference_amount = total_debit if total_debit > 0 else total_credit
        if reference_amount > 0:
            unit = self.currency_symbol or "ریال"
            self.amount_words_label.setText(f"مبلغ به حروف: {numerals.amount_to_words(reference_amount, unit=unit)}")
        else:
            self.amount_words_label.setText("")

    def _save(self) -> None:
        if self.company_id is None or session.current_user is None:
            theme.set_status_label(self.status_label, "ابتدا یک شرکت را انتخاب کنید.", ok=False)
            return

        lines = [ln for row in self._line_rows if (ln := row.to_line_input()) is not None]
        document_date = self.date_field.date()
        description = self.description_field.text().strip()
        alt_number = self.alt_number_field.text().strip()
        as_draft = self.draft_checkbox.isChecked()
        editing_id = self._editing_journal_entry_id

        try:
            if editing_id is not None:
                je_service.update_journal_entry(
                    editing_id, self.company_id, document_date, description, lines,
                    changed_by_user_id=session.current_user.user_id, alternative_number=alt_number, as_draft=as_draft,
                )
                summary = next(
                    (s for s in je_service.list_journal_entries(self.company_id) if s.journal_entry_id == editing_id),
                    None,
                )
                temp_no = summary.temporary_no if summary else None
            else:
                result = je_service.create_journal_entry(
                    self.company_id, session.current_user.user_id, document_date, description, lines,
                    alternative_number=alt_number, as_draft=as_draft,
                )
                temp_no = result.temporary_no
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return

        self._reset_form()
        draft_note = "به‌صورتِ پیش‌نویس " if as_draft else ""
        temp_no_text = numerals.to_persian_digits(str(temp_no)) if temp_no is not None else "؟"
        theme.set_status_label(self.status_label, f"سند {draft_note}با شماره‌ی موقتِ {temp_no_text} ثبت شد.", ok=True)

    def _delete_current_entry(self) -> None:
        if self._editing_journal_entry_id is None or self.company_id is None or session.current_user is None:
            return
        confirm = QMessageBox.question(
            self,
            "حذفِ سند",
            "آیا از حذفِ این سند مطمئن هستید؟ این عمل قابلِ بازگشت نیست.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            je_service.delete_journal_entry(self._editing_journal_entry_id, self.company_id, session.current_user.user_id)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return
        self._reset_form()
        theme.set_status_label(self.status_label, "سند حذف شد.", ok=True)

    def edit_journal_entry(self, journal_entry_id: int) -> None:
        if self.company_id is None:
            return
        summary = next(
            (s for s in je_service.list_journal_entries(self.company_id) if s.journal_entry_id == journal_entry_id),
            None,
        )
        self._editing_journal_entry_id = journal_entry_id
        self._editing_registration_at = summary.registration_at if summary else None
        self.form_title.setText("ویرایشِ سند")
        if summary is not None:
            self.date_field.setDate(summary.document_date)
            self.description_field.setText(summary.description or "")
            self.description_field.setCursorPosition(0)
            self.alt_number_field.setText(summary.alternative_number or "")
            self.alt_number_field.setCursorPosition(0)
            self.draft_checkbox.setChecked(summary.status_code == "DRAFT")

        for row in list(self._line_rows):
            self.remove_line(row, force=True)
        lines = je_service.get_journal_entry_lines(journal_entry_id)
        accounts_by_id = {a[0]: a[1] for a in self.account_options}
        for line in lines:
            row = self.add_line()
            row.load_from(line, accounts_by_id.get(line.account_id, "?"))
        if len(self._line_rows) < 2:
            self.add_line()
        self.update_balance()
        self._update_footer_for_mode()

    def copy_from_journal_entry(self, journal_entry_id: int, *, reverse: bool = False) -> None:
        """طبقِ درخواستِ صریح: کپیِ سند («مشابه» یا «معکوس» — بدهکار/بستانکارِ
        هر ردیف جابه‌جا می‌شود) — بر خلافِ edit_journal_entry، این یک سندِ
        کاملاً تازه می‌سازد (با تاریخِ امروز)، نه ویرایشِ همان سند."""
        if self.company_id is None:
            return
        summary = next(
            (s for s in je_service.list_journal_entries(self.company_id) if s.journal_entry_id == journal_entry_id),
            None,
        )
        self._editing_journal_entry_id = None
        self._editing_registration_at = None
        self.form_title.setText("کپیِ معکوسِ سند" if reverse else "کپیِ سند")
        self.date_field.setDate(datetime.date.today())
        self.alt_number_field.clear()
        self.draft_checkbox.setChecked(False)
        if summary is not None:
            self.description_field.setText(summary.description or "")
            self.description_field.setCursorPosition(0)

        for row in list(self._line_rows):
            self.remove_line(row, force=True)
        lines = je_service.get_journal_entry_lines(journal_entry_id)
        accounts_by_id = {a[0]: a[1] for a in self.account_options}
        for line in lines:
            if reverse:
                line = dataclasses.replace(line, debit=line.credit, credit=line.debit)
            row = self.add_line()
            row.load_from(line, accounts_by_id.get(line.account_id, "?"))
        if len(self._line_rows) < 2:
            self.add_line()
        self.update_balance()
        self._update_footer_for_mode()
        self.status_label.setText("")
