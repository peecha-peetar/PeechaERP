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
حساب بپذیرد) -> [پنجره‌ی ابعادِ دیگر مثلِ مرکزِ هزینه/پروژه به‌طورِ
خودکار باز می‌شود اگر حساب نیاز داشته باشد] -> شرحِ ردیف -> بدهکار ->
(اگر بدهکار صفر باشد) بستانکار -> ردیفِ بعدی (اگر نبود، ساخته می‌شود).
هر بار که صفحه از سایدبار باز شود، فوکوس دوباره رویِ تاریخ می‌رود.

ساده‌سازیِ عمدیِ این مرحله از مهاجرت: ردیفِ *تازه* با ارزِ پایه‌ی شرکت
ثبت می‌شود (بدونِ انتخابِ ارز/نرخِ اختصاصی) — ردیف‌هایی که از یک سندِ
موجود بارگذاری شده‌اند اما ارز/نرخِ خودشان را حفظ می‌کنند."""

from __future__ import annotations

import datetime
import decimal
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
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
from peecha.ui import numerals

_COL_ROW_NO = 0
_COL_ACCOUNT = 1
_COL_PERSON = 2
_COL_DESC = 3
_COL_DEBIT = 4
_COL_CREDIT = 5
_COL_DIMENSIONS = 6
_COL_REMOVE = 7
_COLUMN_LABELS = ["ردیف", "حساب", "تفصیلی", "شرحِ ردیف", "بدهکار", "بستانکار", "ابعاد", ""]


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


def _live_group_amount(spin: QDoubleSpinBox) -> None:
    """گروه‌بندیِ سه‌رقمیِ زنده حینِ تایپ — QDoubleSpinBox حتی با
    setGroupSeparatorShown(True) فقط *بعدِ* تأیید/ازدست‌دادنِ فوکوس
    گروه‌بندی می‌کند، نه حینِ خودِ تایپ؛ این تابع با هر تغییرِ متن (اگر
    اعشار نداشته باشد) دوباره ویرگول‌ها را می‌گذارد و مکان‌نما را متناسب
    نگه می‌دارد."""
    line_edit = spin.lineEdit()
    text = line_edit.text()
    if "." in text:
        return
    cursor = line_edit.cursorPosition()
    raw_digits = re.sub(r"[^0-9]", "", text)
    if not raw_digits:
        return
    digits_before_cursor = len(re.sub(r"[^0-9]", "", text[:cursor]))
    grouped = f"{int(raw_digits):,}"
    if grouped == text:
        return
    new_cursor = len(grouped)
    seen_digits = 0
    for i, ch in enumerate(grouped):
        if ch.isdigit():
            seen_digits += 1
        if seen_digits >= digits_before_cursor:
            new_cursor = i + 1
            break
    line_edit.setText(grouped)
    line_edit.setCursorPosition(new_cursor)


def _clear_if_unmatched(combo: QComboBox) -> None:
    """اگر با ترکِ فیلد، متنِ تایپ‌شده دقیقاً با هیچ گزینه‌ای یکی نباشد،
    انتخاب را به حالتِ خالی برمی‌گرداند — وگرنه ممکن است یک متنِ‌ ناقص/غلط
    با یک account_id قبلی/نامعتبر همراه بماند و سند به حسابِ اشتباه ثبت شود."""
    if combo.findText(combo.currentText(), Qt.MatchExactly) < 0:
        combo.setCurrentIndex(0)


def _make_searchable_combo(options: list[tuple[int, str]]) -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    _fill_options(combo, options)
    line_edit = combo.lineEdit()
    line_edit.textEdited.connect(lambda text, c=combo: _normalize_typed_digits(c, text))
    line_edit.editingFinished.connect(lambda c=combo: _clear_if_unmatched(c))
    return combo


class _JalaliDateEdit(QLineEdit):
    """فیلدِ متنیِ تاریخِ شمسی با ارقامِ فارسی — معادلِ رفتارِ تاریخ‌گیرِ
    Kivy (که هم آن یک فیلدِ متنی بود، نه پاپ‌آپِ تقویم)."""

    def __init__(self) -> None:
        super().__init__()
        self.setPlaceholderText("تاریخِ سند (۱۴۰۳/۰۴/۲۸)")
        self._date = datetime.date.today()
        self._refresh_text()
        self.textEdited.connect(self._on_text_edited)
        self.editingFinished.connect(self._on_editing_finished)

    def _refresh_text(self) -> None:
        self.setText(numerals.format_jalali_date(self._date))

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


class _DimensionsDialog(QDialog):
    """برچسب‌زدنِ ابعادِ تفصیلیِ غیر-شخص (مثلِ مرکزِ هزینه) برایِ یک ردیف —
    تفصیلیِ شخص خودش همیشه به‌عنوانِ ستونی در جدول نمایان است، اما بقیه‌ی
    ابعادِ الزامی (کمتر پرکاربرد) در این پنجره تنظیم می‌شوند تا جدول شلوغ نشود."""

    def __init__(
        self,
        required_dimensions: list[dimensions_service.RequiredDimension],
        current_values: dict[int, int],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ابعادِ تفصیلیِ ردیف")
        self._combos: dict[int, QComboBox] = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()
        for dim in required_dimensions:
            combo = _make_searchable_combo(
                [(d.detail_account_id, f"{d.full_code} — {d.name or ''}") for d in dim.detail_accounts]
            )
            current = current_values.get(dim.dimension_type_id)
            if current is not None:
                index = combo.findData(current)
                if index >= 0:
                    combo.setCurrentIndex(index)
            form.addRow(dim.code, combo)
            self._combos[dim.dimension_type_id] = combo
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict[int, int]:
        result: dict[int, int] = {}
        for dimension_type_id, combo in self._combos.items():
            detail_id = combo.currentData()
            if detail_id is not None:
                result[dimension_type_id] = detail_id
        return result


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
        self._required_dimensions: list[dimensions_service.RequiredDimension] = []
        self._extra_dimension_values: dict[int, int] = {}

        self.account_combo = _make_searchable_combo(screen.account_options)
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)
        self.account_combo.lineEdit().returnPressed.connect(self._on_account_return)

        self.person_combo = _make_searchable_combo([])
        self.person_combo.lineEdit().returnPressed.connect(self._on_person_return)

        self.description_field = QLineEdit()
        self._attach_description_completer()
        self.description_field.returnPressed.connect(lambda: self.debit_field.setFocus())

        self.debit_field = QDoubleSpinBox()
        self.debit_field.setRange(0, 10**12)
        self.debit_field.setGroupSeparatorShown(True)
        self.debit_field.setDecimals(screen.currency_decimal_places)
        self.debit_field.valueChanged.connect(self._on_debit_changed)
        self.debit_field.lineEdit().returnPressed.connect(self._on_debit_return)
        self.debit_field.lineEdit().textEdited.connect(lambda _t, s=self.debit_field: _live_group_amount(s))

        self.credit_field = QDoubleSpinBox()
        self.credit_field.setRange(0, 10**12)
        self.credit_field.setGroupSeparatorShown(True)
        self.credit_field.setDecimals(screen.currency_decimal_places)
        self.credit_field.valueChanged.connect(self._on_credit_changed)
        self.credit_field.lineEdit().returnPressed.connect(lambda: screen.focus_next_row_after(self))
        self.credit_field.lineEdit().textEdited.connect(lambda _t, s=self.credit_field: _live_group_amount(s))

        # نکته: به‌جایِ setVisible(False/True)، از enabled+متن استفاده
        # می‌کنیم — چون QTableWidget هر بارِ محاسبه‌ی geometryِ ادیتورها
        # (مثلاً موقعِ show شدنِ کلِ جدول) دوباره widget.show() را صدا
        # می‌زند و مخفی‌کردنِ دستی را نادیده می‌گیرد.
        self.dimensions_button = QPushButton("—")
        self.dimensions_button.setObjectName("flatButton")
        self.dimensions_button.setStyleSheet("padding: 2px 6px;")
        self.dimensions_button.clicked.connect(self._open_dimensions_dialog)
        self.dimensions_button.setEnabled(False)

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
        table.setCellWidget(row, _COL_PERSON, self.person_combo)
        table.setCellWidget(row, _COL_DESC, self.description_field)
        table.setCellWidget(row, _COL_DEBIT, self.debit_field)
        table.setCellWidget(row, _COL_CREDIT, self.credit_field)
        table.setCellWidget(row, _COL_DIMENSIONS, self.dimensions_button)
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

    def _on_account_return(self) -> None:
        """زنجیره‌ی Enter: حساب -> تفصیلی (اگر حسابی انتخاب شده باشد)."""
        if self.account_id is None:
            return
        self.person_combo.setFocus()
        self.person_combo.lineEdit().selectAll()

    def _on_person_return(self) -> None:
        """زنجیره‌ی Enter: تفصیلی -> (اگر ابعادِ دیگری مثلِ مرکزِ هزینه/
        پروژه هم لازم باشد) پنجره‌ی ابعاد به‌طورِ خودکار باز می‌شود -> شرحِ
        ردیف."""
        if self._required_dimensions and not self._extra_dimensions_complete():
            self._open_dimensions_dialog()
        self.description_field.setFocus()
        self.description_field.selectAll()

    def _extra_dimensions_complete(self) -> bool:
        required_ids = {d.dimension_type_id for d in self._required_dimensions}
        return required_ids <= set(self._extra_dimension_values.keys())

    def _on_debit_return(self) -> None:
        """زنجیره‌ی Enter: اگر بدهکار صفر/خالی بماند برو به بستانکار، وگرنه
        (چون ردیف بدهکار پر شده) مستقیم به ردیفِ بعدی."""
        if self.debit_field.value() == 0:
            self.credit_field.setFocus()
            self.credit_field.lineEdit().selectAll()
        else:
            self._screen.focus_next_row_after(self)

    def _refresh_dimension_ui(self) -> None:
        if self.account_id is None:
            _fill_options(self.person_combo, [])
            self._required_dimensions = []
            self._extra_dimension_values = {}
            self.dimensions_button.setEnabled(False)
            self.dimensions_button.setText("—")
            return

        person_group_ids = [
            g.person_group_id for g in dimensions_service.get_required_person_groups_for_account(self.account_id)
        ]
        persons = dimensions_service.list_active_persons(self._screen.company_id)
        if person_group_ids:
            persons = [p for p in persons if p.person_group_id in person_group_ids]
        _fill_options(self.person_combo, [(p.detail_account_id, f"{p.full_code} — {p.name or ''}") for p in persons])
        self.person_combo.setToolTip("تفصیلی (الزامی)" if person_group_ids else "")

        self._required_dimensions = dimensions_service.get_required_dimensions_for_account(self.account_id)
        valid_ids = {d.dimension_type_id for d in self._required_dimensions}
        self._extra_dimension_values = {k: v for k, v in self._extra_dimension_values.items() if k in valid_ids}
        has_extra_dims = bool(self._required_dimensions)
        self.dimensions_button.setEnabled(has_extra_dims)
        self.dimensions_button.setText("ابعاد" if has_extra_dims else "—")

    def _open_dimensions_dialog(self) -> None:
        dialog = _DimensionsDialog(self._required_dimensions, self._extra_dimension_values, self._table)
        if dialog.exec() == QDialog.Accepted:
            self._extra_dimension_values = dialog.values()

    def collect_details(self) -> dict[int, int]:
        details: dict[int, int] = dict(self._extra_dimension_values)
        person_detail_id = self.person_combo.currentData()
        if person_detail_id is not None:
            details[dimensions_service.get_person_dimension_type_id(self._screen.company_id)] = person_detail_id
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
        self.account_id = line.account_id
        self.currency_id = line.currency_id
        self.exchange_rate = line.exchange_rate
        self._refresh_dimension_ui()

        person_dimension_type_id = dimensions_service.get_person_dimension_type_id(self._screen.company_id)
        self._extra_dimension_values = {
            dim_id: detail_id for dim_id, detail_id in line.details.items() if dim_id != person_dimension_type_id
        }
        person_detail_id = line.details.get(person_dimension_type_id)
        if person_detail_id is not None:
            idx = self.person_combo.findData(person_detail_id)
            if idx >= 0:
                self.person_combo.setCurrentIndex(idx)

        self.description_field.setText(line.description or "")
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

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        # نکته: کلِ صفحه در یک QScrollArea قرار می‌گیرد — وگرنه اگر پنجره
        # کوچک باشد یا ردیف‌ها زیاد شوند، فوتر (شاملِ دکمه‌ی ذخیره) بدونِ
        # هیچ راهی برایِ اسکرول‌کردن، خارج از دیدرس می‌ماند (باگی که گزارش شد).
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(12)

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
        self.date_field = _JalaliDateEdit()
        header_layout.addWidget(self.date_field, 1, 1)

        header_layout.addWidget(QLabel("شرحِ سند"), 1, 2)
        self.description_field = QLineEdit()
        header_layout.addWidget(self.description_field, 1, 3)

        header_layout.addWidget(QLabel("شماره‌ی عطف"), 2, 0)
        self.alt_number_field = QLineEdit()
        header_layout.addWidget(self.alt_number_field, 2, 1)

        self.draft_checkbox = QCheckBox("پیش‌نویس (نامتعادل هم قابلِ‌ذخیره)")
        header_layout.addWidget(self.draft_checkbox, 2, 3)

        # زنجیره‌ی Enter در هدر: تاریخ -> شرحِ سند -> شماره‌ی عطف -> ردیفِ اول.
        self.date_field.returnPressed.connect(lambda: self.description_field.setFocus())
        self.description_field.returnPressed.connect(lambda: self.alt_number_field.setFocus())
        self.alt_number_field.returnPressed.connect(self._focus_first_row_account)

        outer.addWidget(header_card)

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
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setMinimumHeight(160)
        header = self.table.horizontalHeader()
        # طبقِ بازخورد: حساب/تفصیلی نباید غالب/بزرگ‌تر از بقیه باشند —
        # عرضِ ثابتِ متعادل می‌گیرند؛ شرحِ ردیف (تنها ستونِ Stretch) بیشترین
        # فضا را می‌گیرد؛ بدهکار/بستانکار عرضِ ثابتِ بزرگ‌تر برایِ خوانایی.
        header.setSectionResizeMode(_COL_ROW_NO, QHeaderView.Fixed)
        header.setSectionResizeMode(_COL_ACCOUNT, QHeaderView.Interactive)
        header.setSectionResizeMode(_COL_PERSON, QHeaderView.Interactive)
        header.setSectionResizeMode(_COL_DESC, QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_DEBIT, QHeaderView.Interactive)
        header.setSectionResizeMode(_COL_CREDIT, QHeaderView.Interactive)
        header.setSectionResizeMode(_COL_DIMENSIONS, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_REMOVE, QHeaderView.Fixed)
        self.table.setColumnWidth(_COL_ROW_NO, 44)
        self.table.setColumnWidth(_COL_ACCOUNT, 220)
        self.table.setColumnWidth(_COL_PERSON, 190)
        self.table.setColumnWidth(_COL_DEBIT, 140)
        self.table.setColumnWidth(_COL_CREDIT, 140)
        self.table.setColumnWidth(_COL_REMOVE, 40)
        table_card_layout.addWidget(self.table)
        outer.addWidget(table_card, stretch=1)

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

        scroll.setWidget(content)
        root_layout.addWidget(scroll)

        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._save)
        QShortcut(QKeySequence("Escape"), self, activated=self._reset_form)
        QShortcut(QKeySequence("Ctrl+Delete"), self, activated=self._delete_current_entry)

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
        self._renumber_rows()
        return row

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
        self._renumber_rows()
        self.update_balance()

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
            self.balance_label.setText(f"تراز — بدهکار: {debit_text} | بستانکار: {credit_text}")
            self.balance_label.setObjectName("statusOk")
        else:
            self.balance_label.setText(f"غیرِ تراز — بدهکار: {debit_text} | بستانکار: {credit_text}")
            self.balance_label.setObjectName("statusError")
        self.balance_label.setStyleSheet("")

        reference_amount = total_debit if total_debit > 0 else total_credit
        if reference_amount > 0:
            unit = self.currency_symbol or "ریال"
            self.amount_words_label.setText(f"مبلغ به حروف: {numerals.amount_to_words(reference_amount, unit=unit)}")
        else:
            self.amount_words_label.setText("")

    def _save(self) -> None:
        if self.company_id is None or session.current_user is None:
            self.status_label.setObjectName("statusError")
            self.status_label.setStyleSheet("")
            self.status_label.setText("ابتدا یک شرکت را انتخاب کنید.")
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
            self.status_label.setObjectName("statusError")
            self.status_label.setStyleSheet("")
            self.status_label.setText(str(exc))
            return

        self._reset_form()
        draft_note = "به‌صورتِ پیش‌نویس " if as_draft else ""
        temp_no_text = numerals.to_persian_digits(str(temp_no)) if temp_no is not None else "؟"
        self.status_label.setObjectName("statusOk")
        self.status_label.setStyleSheet("")
        self.status_label.setText(f"سند {draft_note}با شماره‌ی موقتِ {temp_no_text} ثبت شد.")

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
            self.status_label.setObjectName("statusError")
            self.status_label.setStyleSheet("")
            self.status_label.setText(str(exc))
            return
        self._reset_form()
        self.status_label.setObjectName("statusOk")
        self.status_label.setStyleSheet("")
        self.status_label.setText("سند حذف شد.")

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
            self.alt_number_field.setText(summary.alternative_number or "")
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
