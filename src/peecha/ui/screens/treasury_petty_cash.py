"""فرمِ واقعیِ «تنخواه‌گردان» — طبقِ گزارشِ صریح:
  ۱) طرفِ‌حساب (تنخواه‌دار) باید تفصیلیِ سطحِ آخرِ گروهِ «تنخواه» باشد.
  ۲) هر تنخواه‌دار می‌تواند هم‌زمان چند تنخواهِ باز داشته باشد؛ هرکدام با
     شماره‌یِ خودکارِ مستقلِ خودش (per custodian).
  ۳) افتتاحِ تنخواه یک سندِ پرداختِ واقعیِ اولیه لازم دارد (واریزی به
     تنخواه‌دار) — همان روش‌هایِ پرداختِ ازپیش‌تعریف‌شده.
  ۴) ردیف‌هایی که در دورانِ بازبودنِ تنخواه ثبت می‌شوند هیچ سندِ
     حسابداری‌ای نمی‌سازند (نه حتی پیش‌نویس)؛ فقط وقتی تنخواه‌دار خودش
     تنخواه را می‌بندد، یک سندِ موقتِ پیش‌نویس ساخته می‌شود که او را به‌
     اندازه‌یِ جمعِ ردیف‌ها بستانکار می‌کند.

طبقِ گزارشِ صریحِ بعدی («این فرم باید همانِ نظم/روش‌هایِ فرمِ دریافت و
پرداخت را رعایت کند»): این فرم اکنون همان اجزایِ مشترکِ treasury_voucher.py
را دوباره‌استفاده می‌کند —
  • _resolve_row_detail_source (تشخیصِ صحیحِ اینکه معینِ نگاشته‌شده‌یِ هر
    روشِ پرداخت، اصلاً به تفصیلیِ الزامی نیاز دارد یا نه؛ رفعِ باگِ واقعی:
    قبلاً فقط روشِ «بانک» تفصیلی می‌پرسید، درحالی‌که هر روشی — ازجمله
    «نقد» — می‌تواند رویِ حسابی نشسته باشد که تفصیلی رویش الزامی است).
  • _EnterComboBox و زنجیره‌ی Enterِ کاملِ فرم (هدر و هر ردیف).
  • _AmountField (اعدادِ سه‌رقم‌سه‌رقم‌جداشده + ارقامِ فارسی + میان‌برِ «+»)."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals
from peecha import session
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import petty_cash as petty_cash_service
from peecha.services import treasury as treasury_service
from peecha.ui import theme
from peecha.ui.screens.journal_entry import _AmountField, _fill_options, _make_searchable_combo
from peecha.ui.screens.treasury_voucher import _EnterComboBox, _detail_option_label, _resolve_row_detail_source
from peecha.ui.widgets import FieldHelpMixin, FormScreenBase, JalaliDateEdit

_METHOD_LABELS = {"CASH": "نقد", "BANK": "بانک", "CHECK": "چک", "DISCOUNT": "تخفیف", "NETTING": "تهاتر"}
_LINE_METHOD_CODES = ("CASH", "BANK", "CHECK", "DISCOUNT", "NETTING")
_NEW_FUND_SENTINEL = "__NEW__"


_FREE_SEARCH_DETAIL_LABEL = "تفصیلی"


def _resolve_petty_cash_detail_options(company_id: int, method: str) -> tuple[list, bool]:
    """طبقِ همان منطقِ فرمِ دریافت/پرداخت (_resolve_row_detail_source):
    تفصیلیِ ردیفِ روشِ «method» — نه فقط برایِ روشِ بانک، برایِ هر روشی
    (نقد/چک هم اگر رویِ چنین حسابی نشسته باشند). خروجی: (گزینه‌ها, آیا
    انتخاب الزامی است). دو حالت ممکن است گزینه‌هایی برگردانند:
    ۱) معینِ نگاشته‌شده واقعاً بُعدِ الزامی (نوع‌بُعد یا گروهِ شخص) دارد —
       انتخاب الزامی است.
    ۲) هیچ الزامی نیست، ولی جستجویِ آزادِ همه‌ی تفصیلی‌هایِ شرکت پیشنهاد
       می‌شود (برچسبِ عمومیِ «تفصیلی») — انتخاب اختیاری است؛ خودِ
       _resolve_account_detail_options این دو حالت را فقط از رویِ همین
       برچسب متمایز می‌کند (برچسبِ عمومی=اختیاری، برچسبِ اختصاصی=الزامی)."""
    _account_id, preset, label, options = _resolve_row_detail_source(company_id, f"PAYMENT_{method}")
    if preset is not None or not options:
        return [], False
    is_required = label != _FREE_SEARCH_DETAIL_LABEL
    return options, is_required


class PettyCashScreen(FieldHelpMixin, FormScreenBase):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.company_id: int | None = None
        self._current_fund_id: int | None = None
        self._lines: list[petty_cash_service.PettyCashFundLineRow] = []
        self._opening_rows: list[tuple[QWidget, _EnterComboBox, QComboBox, _AmountField, QLineEdit]] = []

        layout = self.body_layout
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(6)

        title = QLabel("تنخواه‌گردان")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        # --- هدرِ یکپارچه: تنخواه‌دار/تنخواه + (فقط برایِ افتتاحِ تازه)
        # تاریخ/شرح/تفصیلی‌هایِ اضافیِ حسابِ پیش‌پرداخت — طبقِ گزارشِ صریح
        # («هدر دو تکه نباشد»)، همه در یک کارتِ واحد و جمع‌وجورند؛ ردیف‌هایِ
        # مخصوصِ افتتاح فقط وقتی «تنخواهِ تازه» انتخاب شده باشد نمایش
        # داده می‌شوند (بدونِ این‌که کارتِ دومی ساخته شود). ------------------
        header_card = QWidget()
        header_card.setObjectName("card")
        self.header_grid = QGridLayout(header_card)
        self.header_grid.setContentsMargins(10, 6, 10, 6)
        self.header_grid.setSpacing(4)

        self.header_grid.addWidget(QLabel("تنخواه‌دار (تفصیلیِ سطحِ آخرِ گروهِ تنخواه)"), 0, 0)
        self.custodian_combo = _make_searchable_combo([])
        self.header_grid.addWidget(self.custodian_combo, 1, 0)

        self.header_grid.addWidget(QLabel("تنخواه"), 0, 1)
        self.fund_combo = _EnterComboBox()
        self.header_grid.addWidget(self.fund_combo, 1, 1)

        self.fund_no_label = QLabel("")
        self.fund_no_label.setObjectName("sectionHint")
        self.header_grid.addWidget(self.fund_no_label, 2, 0, 1, 2)

        self.opening_date_label = QLabel("تاریخِ افتتاح")
        self.header_grid.addWidget(self.opening_date_label, 3, 0)
        self.opening_description_label = QLabel("شرح")
        self.header_grid.addWidget(self.opening_description_label, 3, 1)
        self.opening_date_field = JalaliDateEdit()
        self.header_grid.addWidget(self.opening_date_field, 4, 0)
        self.opening_description_field = QLineEdit()
        self.header_grid.addWidget(self.opening_description_field, 4, 1)

        self.header_grid.setColumnStretch(0, 2)
        self.header_grid.setColumnStretch(1, 1)
        layout.addWidget(header_card)

        # طبقِ رفعِ باگِ واقعی: اگر حسابِ پیش‌پرداختِ تنخواه خودش، جدا از
        # بُعدِ تنخواه‌دار، بُعد/گروهِ شخصِ دیگری هم الزامی کرده باشد، این
        # ردیف‌هایِ پویا (فقط وقتی واقعاً لازم باشد) در همین کارت اضافه
        # می‌شوند — قبلاً چون هیچ‌جا پرسیده نمی‌شد، ثبتِ سند همیشه با خطایِ
        # «تفصیلیِ الزامی فراموش شده» رد می‌شد.
        self._opening_header_widgets: list[QWidget] = [
            self.opening_date_label, self.opening_description_label,
            self.opening_date_field, self.opening_description_field,
        ]
        self._advance_extra_widgets: list[tuple[int, QLabel, QComboBox]] = []
        self._advance_extra_row = 5

        self.custodian_combo.currentIndexChanged.connect(self._on_custodian_changed)
        self.fund_combo.currentIndexChanged.connect(self._on_fund_changed)
        self.custodian_combo.lineEdit().returnPressed.connect(lambda: self.fund_combo.setFocus())
        self.fund_combo.enterPressed.connect(self._on_fund_combo_return)
        self.opening_date_field.returnPressed.connect(lambda: self.opening_description_field.setFocus())
        self.opening_description_field.returnPressed.connect(self._focus_after_header)

        # --- بخشِ افتتاحِ تنخواهِ تازه ---------------------------------------
        self.open_section = QWidget()
        open_layout = QVBoxLayout(self.open_section)
        open_layout.setContentsMargins(0, 0, 0, 0)
        open_layout.setSpacing(6)

        open_layout.addWidget(QLabel("واریزیِ اولیه (روشِ پرداخت)"))
        self.opening_rows_container = QVBoxLayout()
        self.opening_rows_container.setSpacing(4)
        open_layout.addLayout(self.opening_rows_container)

        add_opening_row_button = QPushButton("➕")
        add_opening_row_button.setObjectName("iconButton")
        add_opening_row_button.setFixedWidth(44)
        add_opening_row_button.setToolTip("ردیفِ واریزی")
        add_opening_row_button.clicked.connect(lambda: self._add_opening_row(focus=True))
        open_layout.addWidget(add_opening_row_button)

        self.open_fund_button = QPushButton("🔓")
        self.open_fund_button.setObjectName("primaryIconButton")
        self.open_fund_button.setFixedWidth(48)
        self.open_fund_button.setToolTip("افتتاحِ تنخواه")
        self.open_fund_button.clicked.connect(self._open_fund)
        open_layout.addWidget(self.open_fund_button)

        layout.addWidget(self.open_section)

        # --- بخشِ مدیریتِ ردیف‌هایِ یک تنخواهِ بازِ‌موجود ---------------------
        self.manage_section = QWidget()
        manage_layout = QVBoxLayout(self.manage_section)
        manage_layout.setContentsMargins(0, 0, 0, 0)
        manage_layout.setSpacing(6)

        self.lines_table = QTableWidget(0, 4)
        self.lines_table.setHorizontalHeaderLabels(["روش", "مبلغ", "شرح", ""])
        self.lines_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lines_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        manage_layout.addWidget(self.lines_table)

        self.lines_total_label = QLabel("")
        self.lines_total_label.setObjectName("sectionHint")
        manage_layout.addWidget(self.lines_total_label)

        add_line_row = QHBoxLayout()
        self.line_method_combo = _EnterComboBox()
        for code in _LINE_METHOD_CODES:
            self.line_method_combo.addItem(_METHOD_LABELS[code], code)
        self.line_method_combo.currentIndexChanged.connect(self._on_line_method_changed)
        self.line_method_combo.enterPressed.connect(self._on_line_method_return)
        add_line_row.addWidget(self.line_method_combo)

        self.line_detail_combo = _make_searchable_combo([])
        self.line_detail_combo.setVisible(False)
        add_line_row.addWidget(self.line_detail_combo)

        self.line_check_no_field = QLineEdit()
        self.line_check_no_field.setPlaceholderText("شماره‌یِ چک")
        self.line_check_no_field.setVisible(False)
        add_line_row.addWidget(self.line_check_no_field)
        self.line_check_due_field = JalaliDateEdit()
        self.line_check_due_field.setVisible(False)
        add_line_row.addWidget(self.line_check_due_field)

        self.line_amount_field = _AmountField()
        add_line_row.addWidget(self.line_amount_field)

        self.line_description_field = QLineEdit()
        self.line_description_field.setPlaceholderText("شرح")
        add_line_row.addWidget(self.line_description_field, stretch=1)

        add_line_button = QPushButton("➕")
        add_line_button.setObjectName("iconButton")
        add_line_button.setFixedWidth(44)
        add_line_button.setToolTip("افزودنِ ردیف")
        add_line_button.clicked.connect(self._add_line)
        add_line_row.addWidget(add_line_button)
        manage_layout.addLayout(add_line_row)

        self.line_detail_combo.lineEdit().returnPressed.connect(self._focus_after_line_detail)
        self.line_check_no_field.returnPressed.connect(lambda: self.line_check_due_field.setFocus())
        self.line_check_due_field.returnPressed.connect(lambda: self.line_amount_field.setFocus())
        self.line_amount_field.returnPressed.connect(lambda: self.line_description_field.setFocus())
        self.line_description_field.returnPressed.connect(self._add_line)

        self.close_fund_button = QPushButton("🔒")
        self.close_fund_button.setObjectName("dangerIconButton")
        self.close_fund_button.setFixedWidth(44)
        self.close_fund_button.setToolTip("بستنِ تنخواه")
        self.close_fund_button.clicked.connect(self._close_fund)
        manage_layout.addWidget(self.close_fund_button)

        layout.addWidget(self.manage_section)
        layout.addStretch(1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        self.footer_layout.addWidget(self.status_label, stretch=1)

        self._on_line_method_changed()

    # --- بارگذاری ----------------------------------------------------------
    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        self.company_id = self._company_id()
        if self.company_id is None:
            return
        custodians = petty_cash_service.list_custodians(self.company_id)
        custodian_options = [
            (c.detail_account_id, f"{c.full_code} — {c.name}" if c.name else c.full_code) for c in custodians
        ]
        _fill_options(self.custodian_combo, custodian_options)

        self._rebuild_advance_extra_widgets()
        self._rebuild_line_method_combo()
        self._reset_opening_rows()
        self._on_custodian_changed()

    def _reset_form(self) -> None:
        self.refresh()

    def _rebuild_advance_extra_widgets(self) -> None:
        """طبقِ رفعِ باگِ واقعی: اگر حسابِ پیش‌پرداختِ تنخواه بُعد/گروهِ
        شخصِ دیگری هم (غیر از بُعدِ تنخواه‌دار) الزامی کرده باشد، همین‌جا
        (فقط وقتی واقعاً لازم باشد) کمبویِ متناظرش ساخته می‌شود."""
        for _dim_type_id, label, combo in self._advance_extra_widgets:
            self.header_grid.removeWidget(label)
            self.header_grid.removeWidget(combo)
            label.deleteLater()
            combo.deleteLater()
        self._advance_extra_widgets = []
        if self.company_id is None:
            return
        requirements = petty_cash_service.get_advance_extra_requirements(self.company_id)
        row = self._advance_extra_row
        for requirement in requirements:
            label = QLabel(requirement.label)
            combo = _make_searchable_combo(
                [(o.detail_account_id, _detail_option_label(o)) for o in requirement.options]
            )
            self.header_grid.addWidget(label, row, 0, 1, 2)
            self.header_grid.addWidget(combo, row + 1, 0, 1, 2)
            row += 2
            self._advance_extra_widgets.append((requirement.dimension_type_id, label, combo))
        for (_dim, _label, combo), (_next_dim, _next_label, next_combo) in zip(
            self._advance_extra_widgets, self._advance_extra_widgets[1:]
        ):
            combo.lineEdit().returnPressed.connect(next_combo.setFocus)
        if self._advance_extra_widgets:
            self._advance_extra_widgets[-1][2].lineEdit().returnPressed.connect(self._focus_first_opening_row)

    def _focus_after_header(self) -> None:
        """زنجیره‌ی Enter بعدِ شرحِ افتتاح: اگر تفصیلیِ اضافه‌ای برایِ
        حسابِ پیش‌پرداخت لازم باشد، اول به آن‌ها می‌رود، وگرنه مستقیم به
        اولین ردیفِ واریزی."""
        if self._advance_extra_widgets:
            self._advance_extra_widgets[0][2].setFocus()
        else:
            self._focus_first_opening_row()

    def _rebuild_line_method_combo(self) -> None:
        """طبقِ درخواستِ صریح («همه‌یِ روش‌هایِ فرمِ پرداخت در تنخواه هم
        باشد»): علاوه بر نقد/بانک/چک/تخفیف/تهاتر، روش‌هایِ سفارشیِ فعالِ
        همین شرکت (جهتِ پرداخت) هم اضافه می‌شوند — دقیقاً هم‌الگو با
        treasury_voucher.py. خرجِ چک (CHECK_DISBURSEMENT) عمداً این‌جا
        نیست: منطقِ حسابداریِ آن (بازنشستگیِ یک چکِ دریافتیِ مشخص) با
        ردیف‌هایِ سادهِ «مبلغ + تفصیلیِ اختیاری» تفاوتِ بنیادی دارد."""
        current = self.line_method_combo.currentData()
        self.line_method_combo.blockSignals(True)
        self.line_method_combo.clear()
        for code in _LINE_METHOD_CODES:
            self.line_method_combo.addItem(_METHOD_LABELS[code], code)
        if self.company_id is not None:
            for custom_method in treasury_service.list_custom_methods(self.company_id, "PAYMENT", active_only=True):
                code = f"CUSTOM_{custom_method.custom_method_id}"
                _METHOD_LABELS[code] = custom_method.label
                self.line_method_combo.addItem(custom_method.label, code)
        self.line_method_combo.blockSignals(False)
        index = self.line_method_combo.findData(current) if current else -1
        self.line_method_combo.setCurrentIndex(index if index >= 0 else 0)

    def _on_custodian_changed(self) -> None:
        custodian_id = self.custodian_combo.currentData()
        self.fund_combo.clear()
        self.fund_combo.addItem("+ تنخواهِ تازه", _NEW_FUND_SENTINEL)
        if custodian_id is not None and self.company_id is not None:
            for fund in petty_cash_service.list_funds(self.company_id, custodian_id):
                status_word = "باز" if fund.status == "OPEN" else "بسته"
                self.fund_combo.addItem(f"شماره‌یِ {numerals.to_persian_digits(str(fund.fund_no))} ({status_word})", fund.fund_id)
        self.fund_combo.setCurrentIndex(0)
        self._on_fund_changed()

    def _on_fund_changed(self) -> None:
        data = self.fund_combo.currentData()
        is_new = data == _NEW_FUND_SENTINEL or data is None
        for widget in self._opening_header_widgets:
            widget.setVisible(is_new)
        for _dim_type_id, label, combo in self._advance_extra_widgets:
            label.setVisible(is_new)
            combo.setVisible(is_new)
        if is_new:
            self._current_fund_id = None
            self.open_section.setVisible(True)
            self.manage_section.setVisible(False)
            self.fund_no_label.setText("")
            return
        fund = petty_cash_service.get_fund(data)
        if fund is None:
            return
        self._current_fund_id = fund.fund_id
        self.open_section.setVisible(False)
        self.manage_section.setVisible(True)
        status_word = "باز" if fund.status == "OPEN" else "بسته"
        self.fund_no_label.setText(
            f"تنخواهِ شماره‌یِ {numerals.to_persian_digits(str(fund.fund_no))} — وضعیت: {status_word} — "
            f"مبلغِ افتتاح: {numerals.format_money(fund.opening_amount, 0)}"
        )
        self.close_fund_button.setEnabled(fund.status == "OPEN")
        self.line_method_combo.setEnabled(fund.status == "OPEN")
        # باگِ واقعیِ کشف‌شده: چون «نقد» اولین/پیش‌فرضِ خودِ کمبوست، انتخابِ
        # همان روش هیچ‌وقت currentIndexChanged را صدا نمی‌زند (ایندکس عوض
        # نشده) — پس تفصیلیِ الزامیِ آن (مثلاً صندوق) هرگز رفرش نمی‌شد و
        # کاربر تا وقتی روش را دستی عوض/برنمی‌گرداند، چیزی برایِ انتخاب
        # نمی‌دید. حالا هر بار که یک تنخواه فعال می‌شود، صریحاً رفرش می‌شود.
        self._on_line_method_changed()
        self._refresh_lines()

    def _on_fund_combo_return(self) -> None:
        """زنجیره‌ی Enter: تنخواه -> (اگر تازه) تاریخِ افتتاح، (اگر موجود)
        روشِ ردیفِ تازه."""
        if self._current_fund_id is None:
            self.opening_date_field.setFocus()
        else:
            self.line_method_combo.setFocus()

    # --- ردیف‌هایِ افتتاحِ تنخواهِ تازه ------------------------------------
    def _reset_opening_rows(self) -> None:
        while self.opening_rows_container.count():
            item = self.opening_rows_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._opening_rows = []
        self._add_opening_row()

    def _focus_first_opening_row(self) -> None:
        if self._opening_rows:
            self._opening_rows[0][1].setFocus()

    def _refresh_opening_row_detail_options(self, row_index: int) -> None:
        _row_widget, method_combo, detail_combo, _amount_field, _description_field = self._opening_rows[row_index]
        if self.company_id is None:
            detail_combo.setVisible(False)
            return
        options, _is_required = _resolve_petty_cash_detail_options(self.company_id, method_combo.currentData())
        _fill_options(detail_combo, [(o.detail_account_id, _detail_option_label(o)) for o in options])
        detail_combo.setVisible(bool(options))

    def _on_opening_row_method_return(self, row_index: int) -> None:
        _row_widget, _method_combo, detail_combo, amount_field, _description_field = self._opening_rows[row_index]
        self._refresh_opening_row_detail_options(row_index)
        if detail_combo.isVisible():
            detail_combo.setFocus()
        else:
            amount_field.setFocus()

    def _focus_opening_row_after(self, row_index: int) -> None:
        """زنجیره‌ی Enter بعدِ شرحِ یک ردیفِ واریزی: اگر آخرین ردیف است،
        ردیفِ تازه اضافه و فوکوس به روشِ همان ردیفِ تازه می‌رود؛ وگرنه به
        روشِ ردیفِ بعدی."""
        if row_index + 1 < len(self._opening_rows):
            self._opening_rows[row_index + 1][1].setFocus()
        else:
            self._add_opening_row(focus=True)

    def _add_opening_row(self, focus: bool = False) -> None:
        row_index = len(self._opening_rows)
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        method_combo = _EnterComboBox()
        method_combo.addItem("نقد", "CASH")
        method_combo.addItem("بانک", "BANK")
        row_layout.addWidget(method_combo)
        detail_combo = _make_searchable_combo([])
        detail_combo.setVisible(False)
        row_layout.addWidget(detail_combo)
        amount_field = _AmountField()
        row_layout.addWidget(amount_field)
        description_field = QLineEdit()
        description_field.setPlaceholderText("شرح")
        row_layout.addWidget(description_field, 1)
        self.opening_rows_container.addWidget(row_widget)
        self._opening_rows.append((row_widget, method_combo, detail_combo, amount_field, description_field))

        method_combo.currentIndexChanged.connect(lambda _i, r=row_index: self._refresh_opening_row_detail_options(r))
        method_combo.enterPressed.connect(lambda r=row_index: self._on_opening_row_method_return(r))
        detail_combo.lineEdit().returnPressed.connect(lambda r=row_index: self._opening_rows[r][3].setFocus())
        amount_field.returnPressed.connect(lambda r=row_index: self._opening_rows[r][4].setFocus())
        description_field.returnPressed.connect(lambda r=row_index: self._focus_opening_row_after(r))

        self._refresh_opening_row_detail_options(row_index)
        if focus:
            method_combo.setFocus()

    def _open_fund(self) -> None:
        if self.company_id is None or session.current_user is None:
            return
        custodian_id = self.custodian_combo.currentData()
        if custodian_id is None:
            theme.set_status_label(self.status_label, "تنخواه‌دار را انتخاب کنید.", ok=False)
            return
        extra_details: dict[int, int] = {}
        for dim_type_id, label, combo in self._advance_extra_widgets:
            if combo.currentData() is None:
                theme.set_status_label(
                    self.status_label, f"انتخابِ «{label.text()}» برایِ حسابِ پیش‌پرداختِ تنخواه الزامی است.", ok=False
                )
                combo.setFocus()
                return
            extra_details[dim_type_id] = combo.currentData()
        for _widget, method_combo, detail_combo, amount_field, _description_field in self._opening_rows:
            if amount_field.value() <= 0:
                continue
            _options, is_required = _resolve_petty_cash_detail_options(self.company_id, method_combo.currentData())
            if is_required and detail_combo.currentData() is None:
                theme.set_status_label(self.status_label, "تفصیلیِ الزامیِ یکی از ردیف‌هایِ واریزی انتخاب نشده است.", ok=False)
                detail_combo.setFocus()
                return
        method_lines = [
            treasury_service.MethodLine(
                method=method_combo.currentData(),
                amount=decimal.Decimal(str(amount_field.value())),
                description=description_field.text().strip(),
                detail_account_id=detail_combo.currentData() if detail_combo.isVisible() else None,
            )
            for _widget, method_combo, detail_combo, amount_field, description_field in self._opening_rows
            if amount_field.value() > 0
        ]
        if not method_lines:
            theme.set_status_label(self.status_label, "حداقل یک ردیفِ واریزیِ اولیه (با مبلغِ مثبت) لازم است.", ok=False)
            return
        try:
            fund_id, _result = petty_cash_service.open_fund(
                self.company_id, session.current_user.user_id, custodian_id,
                self.opening_date_field.date(), self.opening_description_field.text().strip(), method_lines,
                extra_details=extra_details,
            )
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return
        theme.set_status_label(self.status_label, "تنخواه با موفقیت افتتاح شد.", ok=True)
        self._on_custodian_changed()
        index = self.fund_combo.findData(fund_id)
        if index >= 0:
            self.fund_combo.setCurrentIndex(index)

    # --- ردیف‌هایِ یک تنخواهِ بازِ‌موجود ------------------------------------
    def _on_line_method_changed(self) -> None:
        method = self.line_method_combo.currentData()
        self.line_check_no_field.setVisible(method == "CHECK")
        self.line_check_due_field.setVisible(method == "CHECK")
        if self.company_id is None:
            self.line_detail_combo.setVisible(False)
            return
        options, _is_required = _resolve_petty_cash_detail_options(self.company_id, method)
        _fill_options(self.line_detail_combo, [(o.detail_account_id, _detail_option_label(o)) for o in options])
        self.line_detail_combo.setVisible(bool(options))

    def _on_line_method_return(self) -> None:
        """زنجیره‌ی Enter: روش -> تفصیلی (اگر لازم) وگرنه شماره‌یِ چک
        (اگر روش چک است) وگرنه مستقیم مبلغ."""
        if self.line_detail_combo.isVisible():
            self.line_detail_combo.setFocus()
        elif self.line_check_no_field.isVisible():
            self.line_check_no_field.setFocus()
        else:
            self.line_amount_field.setFocus()

    def _focus_after_line_detail(self) -> None:
        if self.line_check_no_field.isVisible():
            self.line_check_no_field.setFocus()
        else:
            self.line_amount_field.setFocus()

    def _refresh_lines(self) -> None:
        if self._current_fund_id is None:
            self._lines = []
        else:
            self._lines = petty_cash_service.list_lines(self._current_fund_id)
        self.lines_table.setRowCount(len(self._lines))
        for row_index, line in enumerate(self._lines):
            values = [_METHOD_LABELS.get(line.method, line.method), numerals.format_money(line.amount, 0), line.description or ""]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, line.line_id)
                self.lines_table.setItem(row_index, col_index, item)
            delete_button = QPushButton("🗑️")
            delete_button.setObjectName("dangerIconButton")
            delete_button.setFixedWidth(44)
            delete_button.setToolTip("حذف")
            delete_button.clicked.connect(lambda _checked=False, line_id=line.line_id: self._delete_line(line_id))
            delete_button.setEnabled(self.close_fund_button.isEnabled())
            self.lines_table.setCellWidget(row_index, 3, delete_button)
        total = sum((l.amount for l in self._lines), decimal.Decimal(0))
        self.lines_total_label.setText(f"جمعِ ردیف‌ها: {numerals.format_money(total, 0)}")

    def _add_line(self) -> None:
        if self._current_fund_id is None:
            return
        method = self.line_method_combo.currentData()
        amount = decimal.Decimal(str(self.line_amount_field.value()))
        if amount <= 0:
            theme.set_status_label(self.status_label, "مبلغِ ردیف را وارد کنید.", ok=False)
            return
        _options, is_required = _resolve_petty_cash_detail_options(self.company_id, method) if self.company_id else ([], False)
        if is_required and self.line_detail_combo.currentData() is None:
            theme.set_status_label(self.status_label, "تفصیلیِ الزامیِ این روش را انتخاب کنید.", ok=False)
            self.line_detail_combo.setFocus()
            return
        try:
            petty_cash_service.add_line(
                self._current_fund_id, method, amount, self.line_description_field.text().strip(),
                detail_account_id=self.line_detail_combo.currentData() if self.line_detail_combo.isVisible() else None,
                check_no=self.line_check_no_field.text().strip() or None if method == "CHECK" else None,
                check_due_date=self.line_check_due_field.date() if method == "CHECK" else None,
            )
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return
        self.line_amount_field.setValue(0)
        self.line_description_field.clear()
        self.line_check_no_field.clear()
        theme.set_status_label(self.status_label, "ردیف ثبت شد.", ok=True)
        self._refresh_lines()
        self.line_method_combo.setFocus()

    def _delete_line(self, line_id: int) -> None:
        confirm = QMessageBox.question(self, "حذفِ ردیف", "این ردیف حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            petty_cash_service.delete_line(line_id)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return
        self._refresh_lines()

    def _close_fund(self) -> None:
        if self._current_fund_id is None or session.current_user is None:
            return
        if not self._lines:
            theme.set_status_label(self.status_label, "برایِ بستنِ تنخواه حداقل یک ردیف لازم است.", ok=False)
            return
        confirm = QMessageBox.question(
            self, "بستنِ تنخواه",
            "با بستنِ تنخواه، سندِ موقتِ پیش‌نویسِ تسویه ساخته می‌شود و دیگر امکانِ افزودنِ ردیفِ تازه نیست. ادامه می‌دهید؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            result = petty_cash_service.close_fund(self._current_fund_id, session.current_user.user_id, datetime.date.today())
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return
        theme.set_status_label(
            self.status_label,
            f"تنخواه بسته شد؛ سندِ موقتِ پیش‌نویس با شماره‌ی موقتِ {numerals.to_persian_digits(str(result.temporary_no))} ساخته شد.",
            ok=True,
        )
        self._on_custodian_changed()
