"""تنظیماتِ حقوق و دستمزد — فازِ ۲: اطلاعاتِ پایه + قوانینِ حقوق (فصلِ ۴ و ۵
از سندِ طراحی). سه بخش: تنظیماتِ کلیِ شرکت، حداقلِ دستمزدِ مصوب (نسخه‌بندی‌
شده)، و قوانینِ حقوق و دستمزد (پارامترهایِ قانونِ کار، هرکدام با امکانِ
override اختصاصیِ شرکت)."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
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

from peecha import numerals
from peecha import session as app_session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import currencies as currencies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import hr_attendance as attendance_service
from peecha.services import payroll as payroll_service
from peecha.services import payroll_overtime as overtime_service
from peecha.ui import theme
from peecha.ui.excel_import import ExcelColumnMappingDialog, read_excel_rows
from peecha.ui.screens.journal_entry import _AmountField, _make_searchable_combo
from peecha.ui.screens.hr_attendance_entries import _IMPORT_GUESS_KEYWORDS, _IMPORT_TARGET_FIELDS
from peecha.ui.widgets import (
    FieldGrid,
    FieldHelpMixin,
    FieldSpec,
    FormScreenBase,
    JalaliDateEdit,
    LayoutEditMixin,
    PersianDigitLineEdit,
    ZeroPaddedSpinBox,
    wrap_scrollable_with_footer,
)

_CALCULATION_BASIS_LABELS = [("DAILY", "روزانه"), ("HOURLY", "ساعتی")]
_ROUNDING_RULE_LABELS = [
    ("NONE", "بدونِ گردکردن"),
    ("ROUND_1000", "گردکردن به هزار"),
    ("ROUND_100", "گردکردن به صد"),
    ("TRUNCATE", "قطعِ اعشار"),
]

_ITEM_TYPE_LABELS = [
    ("EARNING", "مزایایِ نقدی (Earning)"),
    ("BENEFIT", "مزیت (Benefit)"),
    ("DEDUCTION", "کسورات"),
    ("INSURANCE", "بیمه"),
    ("TAX", "مالیات"),
]
_CALCULATION_METHOD_LABELS = [
    ("BASE_SALARY_FROM_CONTRACT", "حقوقِ پایه از قرارداد"),
    ("FIXED", "مبلغِ ثابت"),
    ("PERCENTAGE_OF_BASE", "درصدی از حقوقِ پایه"),
    ("FORMULA", "فرمول"),
    ("MANUAL", "دستی (به‌ازایِ هر کارمند)"),
    ("SYSTEM_TAX_ENGINE", "سیستمی (موتورِ بیمه/مالیات)"),
]
_CALCULATION_PHASE_LABELS = [
    ("EARNING_PHASE", "فازِ مزایا"),
    ("INSURANCE_PHASE", "فازِ بیمه"),
    ("DEDUCTION_PHASE", "فازِ کسورات"),
    ("TAX_PHASE", "فازِ مالیات"),
]


def _company_id() -> int | None:
    return app_session.current_company.company_id if app_session.current_company else None


def _wrap_scrollable(content: QWidget) -> QWidget:
    # طبقِ آیتمِ ۱ (اسکرول+فوترِ ثابت): این تب دو ستون (لیست/فرم) دارد که
    # هرکدام یک فرمِ مستقلِ کوچک با دکمه‌هایِ پشتِ‌سرِهم زیرِ خودشان‌اند —
    # نه یک فرمِ یکپارچه با یک فوترِ واحد، پس FormScreenBase این‌جا مناسب
    # نیست؛ هرکدام جداگانه، هم‌الگو با payroll_run.py/treasury_checks.py،
    # در کارتِ خودش اسکرول می‌شود تا دکمه‌هایِ پایینِ همان ستون گم نشوند.
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


# ---------------------------------------------------------------------
# تبِ تنظیماتِ کلی
# ---------------------------------------------------------------------
class _GeneralSettingsTab(FieldHelpMixin, LayoutEditMixin, FormScreenBase):
    def __init__(self) -> None:
        super().__init__()
        layout = self.body_layout
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        title = QLabel("تنظیماتِ کلیِ حقوق و دستمزد")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.standard_month_days_field = ZeroPaddedSpinBox()
        self.standard_month_days_field.setRange(1, 31)

        self.calculation_basis_combo = QComboBox()
        for code, label in _CALCULATION_BASIS_LABELS:
            self.calculation_basis_combo.addItem(label, code)

        self.rounding_rule_combo = QComboBox()
        for code, label in _ROUNDING_RULE_LABELS:
            self.rounding_rule_combo.addItem(label, code)

        self.default_pay_day_field = ZeroPaddedSpinBox()
        self.default_pay_day_field.setRange(0, 31)

        self.payslip_currency_combo = QComboBox()

        self.salary_payable_account_combo = _make_searchable_combo([])

        self.salary_payable_detail_combo = _make_searchable_combo([])

        self.payable_description_template_field = QLineEdit()
        self.payable_description_template_field.setPlaceholderText("مثلاً: پرداختنیِ حقوقِ خالص — دورهٔ {دوره} — اجرایِ {اجرا}")

        self.general_grid = FieldGrid([
            FieldSpec("standard_month_days", "تعدادِ روزهایِ استانداردِ ماه", self.standard_month_days_field, span=1),
            FieldSpec("calculation_basis", "مبنایِ محاسبه", self.calculation_basis_combo, span=1),
            FieldSpec("rounding_rule", "قاعدهٔ گردکردن", self.rounding_rule_combo, span=1),
            FieldSpec("default_pay_day", "روزِ پرداخت (۰ یعنی تنظیم‌نشده)", self.default_pay_day_field, span=1),
            FieldSpec("payslip_currency", "ارزِ فیشِ حقوقی", self.payslip_currency_combo, span=2),
            FieldSpec("salary_payable_account", "حسابِ حقوقِ پرداختنی/بانک (برایِ صدورِ سندِ حقوق)", self.salary_payable_account_combo, span=3),
            FieldSpec("salary_payable_detail", "تفصیلیِ حسابِ حقوقِ پرداختنی (اختیاری)", self.salary_payable_detail_combo, span=3),
            FieldSpec("payable_description_template", "قالبِ شرحِ ردیفِ حقوقِ پرداختنی (اختیاری)", self.payable_description_template_field, span=3),
        ])
        layout.addWidget(self.general_grid)
        self.register_field_grids("payroll_settings_general", [self.general_grid])

        save_button = QPushButton("💾")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(48)
        save_button.setToolTip("ذخیره")
        save_button.clicked.connect(self._save)
        self.footer_layout.addWidget(save_button)
        self.footer_layout.addStretch(1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        self.footer_layout.addWidget(self.status_label)

        self.set_field_help([
            (self.standard_month_days_field, "پایهٔ محاسباتِ پرو-راتا (نسبی‌سازی) — پیش‌فرضِ رایج ۳۰ روز."),
            (self.calculation_basis_combo, "آیا محاسباتِ نسبی بر مبنایِ روز باشد یا ساعت."),
            (self.rounding_rule_combo, "قاعدهٔ گردکردنِ مبالغِ نهاییِ فیش."),
            (self.default_pay_day_field, "روزِ ماهِ شمسی‌ای که حقوق معمولاً پرداخت می‌شود."),
            (self.payslip_currency_combo, "ارزی که فیشِ حقوقی با آن نمایش داده می‌شود."),
            (self.salary_payable_account_combo, "حسابِ کلی که خالصِ پرداختنیِ حقوق در سندِ خودکار به آن بستانکار می‌شود — بدونِ این، صدورِ سند ممکن نیست."),
            (self.salary_payable_detail_combo, "تفصیلیِ اختیاری برایِ همان ردیف (مثلاً بانکِ مشخص)."),
            (self.payable_description_template_field, "شرحِ ردیفِ حقوقِ پرداختنی — جای‌گذارهایِ مجاز: {دوره} {اجرا}."),
        ])

    def refresh(self) -> None:
        self.status_label.setText("")
        self.payslip_currency_combo.blockSignals(True)
        self.payslip_currency_combo.clear()
        self.payslip_currency_combo.addItem("(ارزِ پایهٔ شرکت)", None)
        for c in currencies_service.list_all_currencies():
            self.payslip_currency_combo.addItem(c.iso_code, c.currency_id)
        self.payslip_currency_combo.blockSignals(False)

        company_id = _company_id()
        if company_id is None:
            return

        self.salary_payable_account_combo.blockSignals(True)
        self.salary_payable_account_combo.clear()
        self.salary_payable_account_combo.addItem("", None)
        for a in coa_service.list_postable_accounts(company_id):
            self.salary_payable_account_combo.addItem(f"{a.full_code} — {a.name}", a.account_id)
        self.salary_payable_account_combo.blockSignals(False)

        self.salary_payable_detail_combo.blockSignals(True)
        self.salary_payable_detail_combo.clear()
        self.salary_payable_detail_combo.addItem("", None)
        for d in dimensions_service.list_all_leaf_detail_accounts(company_id):
            label = f"{d.full_code} — {d.name}" if d.name else d.full_code
            self.salary_payable_detail_combo.addItem(label, d.detail_account_id)
        self.salary_payable_detail_combo.blockSignals(False)

        settings = payroll_service.get_company_settings(company_id)
        self.standard_month_days_field.setValue(settings.standard_month_days)
        index = self.calculation_basis_combo.findData(settings.calculation_basis)
        self.calculation_basis_combo.setCurrentIndex(index if index >= 0 else 0)
        index = self.rounding_rule_combo.findData(settings.rounding_rule)
        self.rounding_rule_combo.setCurrentIndex(index if index >= 0 else 0)
        self.default_pay_day_field.setValue(settings.default_pay_day or 0)
        index = self.payslip_currency_combo.findData(settings.payslip_currency_id)
        self.payslip_currency_combo.setCurrentIndex(index if index >= 0 else 0)
        index = self.salary_payable_account_combo.findData(settings.salary_payable_gl_account_id)
        self.salary_payable_account_combo.setCurrentIndex(index if index >= 0 else 0)
        index = self.salary_payable_detail_combo.findData(settings.salary_payable_detail_account_id)
        self.salary_payable_detail_combo.setCurrentIndex(index if index >= 0 else 0)
        self.payable_description_template_field.setText(
            payroll_service.get_payroll_description_template(company_id, "PAYROLL_PAYABLE")
        )

    def _save(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        try:
            payroll_service.save_company_settings(
                company_id,
                self.standard_month_days_field.value(),
                self.calculation_basis_combo.currentData(),
                self.rounding_rule_combo.currentData(),
                self.default_pay_day_field.value() or None,
                self.payslip_currency_combo.currentData(),
                salary_payable_gl_account_id=self.salary_payable_account_combo.currentData(),
                salary_payable_detail_account_id=self.salary_payable_detail_combo.currentData(),
            )
            template_text = self.payable_description_template_field.text().strip() or payroll_service.DEFAULT_PAYROLL_DESCRIPTION
            payroll_service.set_payroll_description_template(company_id, "PAYROLL_PAYABLE", template_text)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return
        theme.set_status_label(self.status_label, "ذخیره شد.", ok=True)


# ---------------------------------------------------------------------
# تبِ حداقلِ دستمزد
# ---------------------------------------------------------------------
_WAGE_COLUMNS = ["نرخِ ساعتی", "نرخِ روزانه", "مبلغِ ماهانه", "تا تاریخ", "از تاریخ"]


class _MinimumWageTab(FieldHelpMixin, LayoutEditMixin, QWidget):
    # طبقِ رفعِ باگِ «دکمه‌یِ ذخیره زیرِ تسک‌بار»: هر دو ستون (لیست/فرم)
    # خودشان اسکرول+فوترِ ثابت دارند (_wrap_scrollable) — نباید
    # system_settings.py::_sub_tabs دوباره کلِ این ویجت را بپیچد.
    manages_own_scroll = True

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[payroll_service.MinimumWageRateRow] = []
        self._editing_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)

        self.set_field_help([
            (self.from_date_field, "شروعِ اعتبارِ این نرخِ حداقل‌دستمزد."),
            (self.to_date_field, "پایانِ اعتبار — خالی یعنی تا اطلاعِ ثانوی."),
            (self.monthly_field, "حداقلِ دستمزدِ ماهانهٔ مصوب."),
        ])

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        title = QLabel("حداقلِ دستمزدِ مصوب")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.table = QTableWidget(0, len(_WAGE_COLUMNS))
        self.table.setHorizontalHeaderLabels(_WAGE_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)
        return _wrap_scrollable(panel)

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        self.form_title = QLabel("دورهٔ تازه")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        self.from_date_field = JalaliDateEdit()

        self.to_date_field = JalaliDateEdit()

        self.to_date_unbounded_checkbox = QCheckBox("تا اطلاعِ ثانوی (بدونِ تاریخِ پایان)")
        self.to_date_unbounded_checkbox.setChecked(True)
        self.to_date_unbounded_checkbox.toggled.connect(lambda checked: self.to_date_field.setEnabled(not checked))
        self.to_date_field.setEnabled(False)

        self.monthly_field = _AmountField()

        self.daily_field = _AmountField()

        self.hourly_field = _AmountField()

        self.wage_grid = FieldGrid([
            FieldSpec("from_date", "از تاریخ", self.from_date_field, span=1),
            FieldSpec("to_date", "تا تاریخ", self.to_date_field, span=1),
            FieldSpec("to_date_unbounded", "", self.to_date_unbounded_checkbox, span=1),
            FieldSpec("monthly", "مبلغِ ماهانه (ریال)", self.monthly_field, span=1),
            FieldSpec("daily", "مبلغِ روزانه (اختیاری)", self.daily_field, span=1),
            FieldSpec("hourly", "مبلغِ ساعتی (اختیاری)", self.hourly_field, span=1),
        ])
        layout.addWidget(self.wage_grid)
        self.register_field_grids("payroll_settings_minimum_wage", [self.wage_grid])

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        save_button = QPushButton("💾")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(48)
        save_button.setToolTip("ذخیره")
        save_button.clicked.connect(self._save)

        cancel_button = QPushButton("↩️")
        cancel_button.setObjectName("iconButton")
        cancel_button.setFixedWidth(44)
        cancel_button.setToolTip("انصراف")
        cancel_button.clicked.connect(self._reset_form)

        self.delete_button = QPushButton("🗑️")
        self.delete_button.setObjectName("dangerIconButton")
        self.delete_button.setFixedWidth(44)
        self.delete_button.setToolTip("حذف")
        self.delete_button.clicked.connect(self._delete)
        self.delete_button.setVisible(False)

        return wrap_scrollable_with_footer(panel, [save_button, cancel_button, self.delete_button])

    def refresh(self) -> None:
        self._reset_form()
        company_id = _company_id()
        if company_id is None:
            return
        self._rows = payroll_service.list_minimum_wage_rates(company_id)
        self.table.setRowCount(len(self._rows))
        for row_index, w in enumerate(self._rows):
            values = [
                numerals.format_company_amount(w.hourly_amount) if w.hourly_amount is not None else "—",
                numerals.format_company_amount(w.daily_amount) if w.daily_amount is not None else "—",
                numerals.format_company_amount(w.monthly_amount),
                numerals.to_persian_digits(w.effective_to.isoformat()) if w.effective_to else "—",
                numerals.to_persian_digits(w.effective_from.isoformat()),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, w.minimum_wage_rate_id)
                self.table.setItem(row_index, col_index, item)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        rate_id = self.table.item(row, 0).data(Qt.UserRole)
        rate = next((r for r in self._rows if r.minimum_wage_rate_id == rate_id), None)
        if rate is not None:
            self._load_into_form(rate)

    def _load_into_form(self, w: payroll_service.MinimumWageRateRow) -> None:
        self._editing_id = w.minimum_wage_rate_id
        self.form_title.setText("ویرایشِ دوره")
        self.status_label.setText("")
        self.from_date_field.setDate(w.effective_from)
        self.to_date_unbounded_checkbox.setChecked(w.effective_to is None)
        if w.effective_to is not None:
            self.to_date_field.setDate(w.effective_to)
        self.monthly_field.setValue(float(w.monthly_amount))
        self.daily_field.setValue(float(w.daily_amount or 0))
        self.hourly_field.setValue(float(w.hourly_amount or 0))
        self.delete_button.setVisible(True)

    def _reset_form(self) -> None:
        self._editing_id = None
        self.form_title.setText("دورهٔ تازه")
        self.status_label.setText("")
        self.from_date_field.setDate(datetime.date.today())
        self.to_date_unbounded_checkbox.setChecked(True)
        self.to_date_field.setDate(datetime.date.today())
        self.monthly_field.setValue(0)
        self.daily_field.setValue(0)
        self.hourly_field.setValue(0)
        self.delete_button.setVisible(False)
        self.table.clearSelection()

    def _save(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        effective_from = self.from_date_field.date()
        effective_to = None if self.to_date_unbounded_checkbox.isChecked() else self.to_date_field.date()
        monthly = decimal.Decimal(str(self.monthly_field.value()))
        daily = decimal.Decimal(str(self.daily_field.value())) or None
        hourly = decimal.Decimal(str(self.hourly_field.value())) or None
        try:
            if self._editing_id is not None:
                payroll_service.update_minimum_wage_rate(
                    self._editing_id, company_id, effective_from, effective_to, monthly, daily, hourly
                )
            else:
                payroll_service.create_minimum_wage_rate(
                    company_id, effective_from, effective_to, monthly, daily, hourly
                )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        confirm = QMessageBox.question(
            self, "حذفِ دوره", "این دورهٔ حداقل‌دستمزد حذف شود؟", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        payroll_service.delete_minimum_wage_rate(self._editing_id)
        self.refresh()


# ---------------------------------------------------------------------
# تبِ قوانینِ حقوق و دستمزد
# ---------------------------------------------------------------------
_POLICY_COLUMNS = ["اختصاصیِ شرکت", "از تاریخِ اجرا", "مقدار", "عنوانِ قانون"]


class _SetPolicyDialog(QDialog):
    def __init__(self, parent: QWidget, label: str, current_value: decimal.Decimal | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"ویرایشِ قانون — {label}")
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("تاریخِ اجرا (نسخهٔ تازه از این تاریخ به بعد)"))
        self.effective_from_field = JalaliDateEdit()
        self.effective_from_field.setDate(datetime.date.today())
        layout.addWidget(self.effective_from_field)

        layout.addWidget(QLabel("مقدارِ تازه"))
        self.value_field = _AmountField()
        self.value_field.setValue(float(current_value or 0))
        layout.addWidget(self.value_field)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def effective_from(self) -> datetime.date:
        return self.effective_from_field.date()

    def value(self) -> decimal.Decimal:
        return decimal.Decimal(str(self.value_field.value()))


class _PoliciesTab(FormScreenBase):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[payroll_service.PolicyRow] = []

        layout = self.body_layout
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        title = QLabel("قوانینِ حقوق و دستمزد")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "مقدارِ بدونِ نشانِ «اختصاصیِ شرکت» یعنی پیش‌فرضِ سراسری در حالِ استفاده است. "
            "برایِ این شرکت مقدارِ اختصاصی تعریف کنید تا از تاریخِ انتخابی به‌بعد جایگزینِ پیش‌فرض شود؛ "
            "نسخهٔ قبلی برایِ محاسبهٔ دوره‌هایِ گذشته دست‌نخورده می‌ماند."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, len(_POLICY_COLUMNS))
        self.table.setHorizontalHeaderLabels(_POLICY_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self.table, stretch=1)

        edit_button = QPushButton("✏️")
        edit_button.setObjectName("primaryIconButton")
        edit_button.setFixedWidth(48)
        edit_button.setToolTip("ویرایشِ قانونِ انتخاب‌شده")
        edit_button.clicked.connect(self._edit_selected)
        self.footer_layout.addWidget(edit_button)
        self.footer_layout.addStretch(1)

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        self._rows = payroll_service.list_policies(company_id)
        self.table.setRowCount(len(self._rows))
        for row_index, p in enumerate(self._rows):
            value_str = (
                numerals.to_persian_digits(str(p.value_numeric))
                if p.value_numeric is not None
                else (p.value_text or "—")
            )
            values = [
                "بله" if p.is_company_override else "خیر",
                numerals.to_persian_digits(p.effective_from.isoformat()),
                value_str,
                p.label,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, p.policy_code)
                self.table.setItem(row_index, col_index, item)

    def _on_row_double_clicked(self, row: int, _column: int) -> None:
        self._edit_row(row)

    def _edit_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "ویرایشِ قانون", "یک ردیف را انتخاب کنید.")
            return
        self._edit_row(row)

    def _edit_row(self, row: int) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        policy_code = self.table.item(row, 0).data(Qt.UserRole)
        policy = next(p for p in self._rows if p.policy_code == policy_code)
        dialog = _SetPolicyDialog(self, policy.label, policy.value_numeric)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            payroll_service.set_policy(company_id, policy_code, dialog.effective_from(), dialog.value())
        except ValueError as exc:
            QMessageBox.warning(self, "ویرایشِ قانون", str(exc))
            return
        self.refresh()


# ---------------------------------------------------------------------
# تبِ آیتم‌هایِ حقوقی (موتورِ عمومیِ فصلِ ۶ + تکمیل‌هایِ فصلِ ۷/۸)
# ---------------------------------------------------------------------
_PAY_ITEM_COLUMNS = ["فعال", "فاز", "روشِ محاسبه", "نوع", "نام", "کد"]


class _PayItemsTab(FieldHelpMixin, LayoutEditMixin, QWidget):
    # طبقِ رفعِ باگِ «دکمه‌یِ ذخیره زیرِ تسک‌بار»: هر دو ستون (لیست/فرم)
    # خودشان اسکرول+فوترِ ثابت دارند (_wrap_scrollable) — نباید
    # system_settings.py::_sub_tabs دوباره کلِ این ویجت را بپیچد.
    manages_own_scroll = True

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[payroll_service.PayItemRow] = []
        self._editing_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)

        self.set_field_help([
            (self.formula_field, "زبانِ محدودِ فرمول: + - * / ( )، اعداد، BASE_SALARY/WORKED_DAYS/CALENDAR_DAYS/"
                                  "CHILDREN_COUNT/WEEKLY_HOURS، ارجاع به آیتمِ دیگر با {CODE}، و POLICY(CODE)."),
            (self.eligibility_field, "شرطِ تخصیصِ خودکار، مثلاً «CHILDREN_COUNT > 0» — خالی یعنی همیشه اعمال شود."),
            (self.gl_account_combo, "حسابِ کلی که این آیتم در سندِ حسابداریِ خودکارِ حقوق به آن می‌رود."),
            (self.detail_account_combo, "تفصیلیِ اختیاری برایِ همین ردیفِ سند (مثلاً مرکزِ هزینه)."),
            (self.description_template_field, "شرحِ ردیفِ این آیتم در سند — جای‌گذارهایِ مجاز: {نام_آیتم} {دوره} {اجرا}."),
        ])
        self.register_field_grids("payroll_settings_pay_items", [self.form_grid])

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        title = QLabel("آیتم‌هایِ حقوقی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.table = QTableWidget(0, len(_PAY_ITEM_COLUMNS))
        self.table.setHorizontalHeaderLabels(_PAY_ITEM_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)
        return _wrap_scrollable(panel)

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        self.form_title = QLabel("آیتمِ تازه")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        self.code_field = QLineEdit()

        self.name_field = QLineEdit()

        self.item_type_combo = QComboBox()
        for code, label in _ITEM_TYPE_LABELS:
            self.item_type_combo.addItem(label, code)

        self.calculation_method_combo = QComboBox()
        for code, label in _CALCULATION_METHOD_LABELS:
            self.calculation_method_combo.addItem(label, code)
        self.calculation_method_combo.currentIndexChanged.connect(self._update_method_fields_visibility)

        self.calculation_phase_combo = QComboBox()
        for code, label in _CALCULATION_PHASE_LABELS:
            self.calculation_phase_combo.addItem(label, code)

        self.formula_field = QLineEdit()

        self.fixed_amount_field = _AmountField()

        self.percentage_field = PersianDigitLineEdit()

        self.gl_account_combo = _make_searchable_combo([])

        self.detail_account_combo = _make_searchable_combo([])

        self.description_template_field = QLineEdit()
        self.description_template_field.setPlaceholderText("مثلاً: بابتِ {نام_آیتم} — دورهٔ {دوره} — اجرایِ {اجرا}")

        self.eligibility_field = QLineEdit()

        self.is_prorated_checkbox = QCheckBox("نسبی‌سازی بر اساسِ روزِ کارکرد")
        self.is_taxable_checkbox = QCheckBox("مشمولِ مالیات")
        self.is_insurable_checkbox = QCheckBox("مشمولِ بیمه")
        self.is_continuous_checkbox = QCheckBox("مستمر (مبنایِ سنوات/اضافه‌کاری)")
        self.is_cash_checkbox = QCheckBox("نقدی (در جمعِ قابلِ‌پرداخت لحاظ شود)")
        self.is_cash_checkbox.setChecked(True)
        self.is_court_order_checkbox = QCheckBox("کسرِ حکمِ دادگاه")

        self.deduction_priority_field = ZeroPaddedSpinBox()
        self.deduction_priority_field.setRange(0, 99)

        self.is_active_checkbox = QCheckBox("فعال")
        self.is_active_checkbox.setChecked(True)

        self.form_grid = FieldGrid([
            FieldSpec("code", "کد", self.code_field, span=1),
            FieldSpec("name", "نام", self.name_field, span=2),
            FieldSpec("item_type", "نوع", self.item_type_combo, span=1),
            FieldSpec("calculation_method", "روشِ محاسبه", self.calculation_method_combo, span=1),
            FieldSpec("calculation_phase", "فازِ محاسبه", self.calculation_phase_combo, span=1),
            FieldSpec("formula", "فرمول", self.formula_field, span=3),
            FieldSpec("fixed_amount", "مبلغِ ثابت (ریال)", self.fixed_amount_field, span=2),
            FieldSpec("percentage", "درصد (از حقوقِ پایه)", self.percentage_field, span=1),
            FieldSpec("gl_account", "حسابِ کلِ مرتبط (اختیاری)", self.gl_account_combo, span=3),
            FieldSpec("detail_account", "تفصیلیِ مرتبط (اختیاری)", self.detail_account_combo, span=3),
            FieldSpec("description_template", "قالبِ شرحِ سند (اختیاری — خالی یعنی شرحِ پیش‌فرض)", self.description_template_field, span=3),
            FieldSpec("eligibility", "شرطِ تخصیص (اختیاری)", self.eligibility_field, span=3),
            FieldSpec("is_prorated", "", self.is_prorated_checkbox, span=1),
            FieldSpec("is_taxable", "", self.is_taxable_checkbox, span=1),
            FieldSpec("is_insurable", "", self.is_insurable_checkbox, span=1),
            FieldSpec("is_continuous", "", self.is_continuous_checkbox, span=1),
            FieldSpec("is_cash", "", self.is_cash_checkbox, span=1),
            FieldSpec("is_court_order", "", self.is_court_order_checkbox, span=1),
            FieldSpec("deduction_priority", "اولویتِ کسر (عددِ کوچک‌تر = اولویتِ بالاتر)", self.deduction_priority_field, span=2),
            FieldSpec("is_active", "", self.is_active_checkbox, span=1),
        ])
        layout.addWidget(self.form_grid)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        save_button = QPushButton("💾")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(48)
        save_button.setToolTip("ذخیره")
        save_button.clicked.connect(self._save)

        cancel_button = QPushButton("↩️")
        cancel_button.setObjectName("iconButton")
        cancel_button.setFixedWidth(44)
        cancel_button.setToolTip("انصراف")
        cancel_button.clicked.connect(self._reset_form)

        self.delete_button = QPushButton("🗑️")
        self.delete_button.setObjectName("dangerIconButton")
        self.delete_button.setFixedWidth(44)
        self.delete_button.setToolTip("حذف")
        self.delete_button.clicked.connect(self._delete)
        self.delete_button.setVisible(False)

        self._update_method_fields_visibility()
        return wrap_scrollable_with_footer(panel, [save_button, cancel_button, self.delete_button])

    def _update_method_fields_visibility(self) -> None:
        method = self.calculation_method_combo.currentData()
        self.form_grid.set_field_visible("formula", method == "FORMULA")
        self.form_grid.set_field_visible("fixed_amount", method == "FIXED")
        self.form_grid.set_field_visible("percentage", method == "PERCENTAGE_OF_BASE")
        is_deduction_method = self.item_type_combo.currentData() == "DEDUCTION"
        self.form_grid.set_field_visible("deduction_priority", is_deduction_method)
        self.form_grid.set_field_visible("is_court_order", is_deduction_method)

    def refresh(self) -> None:
        self._reset_form()
        company_id = _company_id()
        if company_id is None:
            return
        accounts = coa_service.list_postable_accounts(company_id)
        account_options = [(a.account_id, f"{a.full_code} — {a.name}") for a in accounts]
        current = self.gl_account_combo.currentData()
        self.gl_account_combo.blockSignals(True)
        self.gl_account_combo.clear()
        self.gl_account_combo.addItem("", None)
        for account_id, label in account_options:
            self.gl_account_combo.addItem(label, account_id)
        index = self.gl_account_combo.findData(current)
        self.gl_account_combo.setCurrentIndex(index if index >= 0 else 0)
        self.gl_account_combo.blockSignals(False)

        detail_options = [
            (d.detail_account_id, f"{d.full_code} — {d.name}" if d.name else d.full_code)
            for d in dimensions_service.list_all_leaf_detail_accounts(company_id)
        ]
        current_detail = self.detail_account_combo.currentData()
        self.detail_account_combo.blockSignals(True)
        self.detail_account_combo.clear()
        self.detail_account_combo.addItem("", None)
        for detail_account_id, label in detail_options:
            self.detail_account_combo.addItem(label, detail_account_id)
        index = self.detail_account_combo.findData(current_detail)
        self.detail_account_combo.setCurrentIndex(index if index >= 0 else 0)
        self.detail_account_combo.blockSignals(False)

        self._rows = payroll_service.list_pay_items(company_id)
        item_type_labels = dict(_ITEM_TYPE_LABELS)
        method_labels = dict(_CALCULATION_METHOD_LABELS)
        phase_labels = dict(_CALCULATION_PHASE_LABELS)
        self.table.setRowCount(len(self._rows))
        for row_index, p in enumerate(self._rows):
            values = [
                "بله" if p.is_active else "خیر",
                phase_labels.get(p.calculation_phase, p.calculation_phase),
                method_labels.get(p.calculation_method, p.calculation_method),
                item_type_labels.get(p.item_type, p.item_type),
                p.name,
                p.code,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, p.pay_item_id)
                self.table.setItem(row_index, col_index, item)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        pay_item_id = self.table.item(row, 0).data(Qt.UserRole)
        item = next((r for r in self._rows if r.pay_item_id == pay_item_id), None)
        if item is not None:
            self._load_into_form(item)

    def _load_into_form(self, p: payroll_service.PayItemRow) -> None:
        self._editing_id = p.pay_item_id
        self.form_title.setText(f"ویرایشِ آیتم — {p.name}")
        self.status_label.setText("")
        self.code_field.setText(p.code)
        self.code_field.setEnabled(False)
        self.name_field.setText(p.name)
        self.item_type_combo.setCurrentIndex(self.item_type_combo.findData(p.item_type))
        self.calculation_method_combo.setCurrentIndex(self.calculation_method_combo.findData(p.calculation_method))
        self.calculation_phase_combo.setCurrentIndex(self.calculation_phase_combo.findData(p.calculation_phase))
        self.formula_field.setText(p.formula_expression or "")
        self.fixed_amount_field.setValue(float(p.fixed_amount or 0))
        self.percentage_field.setText(numerals.to_persian_digits(str(p.percentage)) if p.percentage is not None else "")
        index = self.gl_account_combo.findData(p.gl_account_id)
        self.gl_account_combo.setCurrentIndex(index if index >= 0 else 0)
        index = self.detail_account_combo.findData(p.detail_account_id)
        self.detail_account_combo.setCurrentIndex(index if index >= 0 else 0)
        self.description_template_field.setText(p.description_template or "")
        self.eligibility_field.setText(p.eligibility_condition or "")
        self.is_prorated_checkbox.setChecked(p.is_prorated)
        self.is_taxable_checkbox.setChecked(p.is_taxable)
        self.is_insurable_checkbox.setChecked(p.is_insurable)
        self.is_continuous_checkbox.setChecked(p.is_continuous_benefit)
        self.is_cash_checkbox.setChecked(p.is_cash)
        self.is_court_order_checkbox.setChecked(p.is_court_order)
        self.deduction_priority_field.setValue(p.deduction_priority or 0)
        self.is_active_checkbox.setChecked(p.is_active)
        self.delete_button.setVisible(True)
        self._update_method_fields_visibility()

    def _reset_form(self) -> None:
        self._editing_id = None
        self.form_title.setText("آیتمِ تازه")
        self.status_label.setText("")
        self.code_field.clear()
        self.code_field.setEnabled(True)
        self.name_field.clear()
        self.item_type_combo.setCurrentIndex(0)
        self.calculation_method_combo.setCurrentIndex(0)
        self.calculation_phase_combo.setCurrentIndex(0)
        self.formula_field.clear()
        self.fixed_amount_field.setValue(0)
        self.percentage_field.clear()
        self.gl_account_combo.setCurrentIndex(0)
        self.detail_account_combo.setCurrentIndex(0)
        self.description_template_field.clear()
        self.eligibility_field.clear()
        self.is_prorated_checkbox.setChecked(False)
        self.is_taxable_checkbox.setChecked(False)
        self.is_insurable_checkbox.setChecked(False)
        self.is_continuous_checkbox.setChecked(False)
        self.is_cash_checkbox.setChecked(True)
        self.is_court_order_checkbox.setChecked(False)
        self.deduction_priority_field.setValue(0)
        self.is_active_checkbox.setChecked(True)
        self.delete_button.setVisible(False)
        self.table.clearSelection()
        self._update_method_fields_visibility()

    def _save(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        name = self.name_field.text().strip()
        if not name:
            self.status_label.setText("نام را وارد کنید.")
            return
        item_type = self.item_type_combo.currentData()
        calculation_method = self.calculation_method_combo.currentData()
        calculation_phase = self.calculation_phase_combo.currentData()
        formula_expression = self.formula_field.text().strip() or None
        fixed_amount = decimal.Decimal(str(self.fixed_amount_field.value())) if calculation_method == "FIXED" else None
        percentage_text = numerals.to_ascii_digits(self.percentage_field.text().strip())
        percentage = decimal.Decimal(percentage_text) if calculation_method == "PERCENTAGE_OF_BASE" and percentage_text else None
        gl_account_id = self.gl_account_combo.currentData()
        detail_account_id = self.detail_account_combo.currentData()
        description_template = self.description_template_field.text().strip() or None
        eligibility_condition = self.eligibility_field.text().strip() or None
        deduction_priority = self.deduction_priority_field.value() if item_type == "DEDUCTION" else None
        kwargs = dict(
            formula_expression=formula_expression, fixed_amount=fixed_amount, percentage=percentage,
            is_prorated=self.is_prorated_checkbox.isChecked(), is_taxable=self.is_taxable_checkbox.isChecked(),
            is_insurable=self.is_insurable_checkbox.isChecked(), is_continuous_benefit=self.is_continuous_checkbox.isChecked(),
            gl_account_id=gl_account_id, detail_account_id=detail_account_id, description_template=description_template,
            eligibility_condition=eligibility_condition,
            is_cash=self.is_cash_checkbox.isChecked(), tax_exempt_ceiling_policy_code=None,
            insurance_exempt_ceiling_policy_code=None, is_court_order=self.is_court_order_checkbox.isChecked(),
            deduction_priority=deduction_priority,
        )
        try:
            if self._editing_id is not None:
                payroll_service.update_pay_item(
                    self._editing_id, name, item_type, calculation_method, calculation_phase,
                    is_active=self.is_active_checkbox.isChecked(), **kwargs,
                )
            else:
                code = self.code_field.text().strip()
                if not code:
                    self.status_label.setText("کد را وارد کنید.")
                    return
                payroll_service.create_pay_item(company_id, code, name, item_type, calculation_method, calculation_phase, **kwargs)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return
        self.refresh()

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        confirm = QMessageBox.question(self, "حذفِ آیتم", "این آیتمِ حقوقی حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            payroll_service.delete_pay_item(self._editing_id)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return
        self.refresh()


# ---------------------------------------------------------------------
# تبِ بیمه (فصلِ ۹)
# ---------------------------------------------------------------------
_INSURANCE_COLUMNS = ["نرخِ بیکاری", "نرخِ کارفرما", "نرخِ کارمند", "تا تاریخ", "از تاریخ"]


class _InsuranceTab(FieldHelpMixin, LayoutEditMixin, QWidget):
    # طبقِ رفعِ باگِ «دکمه‌یِ ذخیره زیرِ تسک‌بار»: هر دو ستون (لیست/فرم)
    # خودشان اسکرول+فوترِ ثابت دارند (_wrap_scrollable) — نباید
    # system_settings.py::_sub_tabs دوباره کلِ این ویجت را بپیچد.
    manages_own_scroll = True

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[payroll_service.InsuranceConfigRow] = []
        self._editing_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)

        self.set_field_help([
            (self.employee_rate_field, "سهمِ بیمهٔ کارمند به‌صورتِ درصد، مثلاً ۷ برایِ ۷٪."),
            (self.floor_field, "کفِ مزدِ مشمولِ بیمه — خالی یعنی حداقل‌دستمزدِ مصوب."),
            (self.employer_expense_account_combo, "حسابِ هزینه‌ای که سهمِ کارفرمایِ بیمه در سندِ خودکار به‌عنوانِ بدهکار به آن می‌رود."),
            (self.employer_expense_detail_combo, "تفصیلیِ اختیاری برایِ همان ردیف."),
            (self.insurance_description_template_field, "شرحِ ردیفِ سهمِ کارفرما — جای‌گذارهایِ مجاز: {دوره} {اجرا}."),
        ])
        self.register_field_grids("payroll_settings_insurance", [self.form_grid])

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        title = QLabel("تنظیماتِ بیمهٔ اختصاصیِ این شرکت")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel("اگر دوره‌ای این‌جا تعریف نشود، نرخِ پیش‌فرضِ سراسری (۷٪/۲۰٪/۳٪) استفاده می‌شود.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, len(_INSURANCE_COLUMNS))
        self.table.setHorizontalHeaderLabels(_INSURANCE_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)
        return _wrap_scrollable(panel)

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        self.form_title = QLabel("دورهٔ تازه")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        self.from_date_field = JalaliDateEdit()

        self.to_date_field = JalaliDateEdit()
        self.to_date_unbounded_checkbox = QCheckBox("تا اطلاعِ ثانوی (بدونِ تاریخِ پایان)")
        self.to_date_unbounded_checkbox.setChecked(True)
        self.to_date_unbounded_checkbox.toggled.connect(lambda checked: self.to_date_field.setEnabled(not checked))
        self.to_date_field.setEnabled(False)

        self.employee_rate_field = PersianDigitLineEdit()

        self.employer_rate_field = PersianDigitLineEdit()

        self.unemployment_rate_field = PersianDigitLineEdit()

        self.floor_field = _AmountField()

        self.employer_expense_account_combo = _make_searchable_combo([])

        self.employer_expense_detail_combo = _make_searchable_combo([])

        self.insurance_description_template_field = QLineEdit()
        self.insurance_description_template_field.setPlaceholderText("مثلاً: سهمِ کارفرمایِ بیمه — دورهٔ {دوره} — اجرایِ {اجرا}")

        self.form_grid = FieldGrid([
            FieldSpec("from_date", "از تاریخ", self.from_date_field, span=1),
            FieldSpec("to_date", "تا تاریخ", self.to_date_field, span=1),
            FieldSpec("to_date_unbounded", "", self.to_date_unbounded_checkbox, span=1),
            FieldSpec("employee_rate", "نرخِ سهمِ کارمند (درصد)", self.employee_rate_field, span=1),
            FieldSpec("employer_rate", "نرخِ سهمِ کارفرما (درصد)", self.employer_rate_field, span=1),
            FieldSpec("unemployment_rate", "نرخِ بیمهٔ بیکاری — سهمِ کارفرما (درصد)", self.unemployment_rate_field, span=1),
            FieldSpec("floor", "کفِ مزدِ مشمول (ریال، اختیاری)", self.floor_field, span=1),
            FieldSpec("employer_expense_account", "حسابِ هزینهٔ سهمِ کارفرما (برایِ صدورِ سندِ حقوق)", self.employer_expense_account_combo, span=2),
            FieldSpec("employer_expense_detail", "تفصیلیِ حسابِ هزینهٔ سهمِ کارفرما (اختیاری)", self.employer_expense_detail_combo, span=3),
            FieldSpec("insurance_description_template", "قالبِ شرحِ ردیفِ سهمِ کارفرما (اختیاری)", self.insurance_description_template_field, span=3),
        ])
        layout.addWidget(self.form_grid)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        save_button = QPushButton("💾")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(48)
        save_button.setToolTip("ذخیره")
        save_button.clicked.connect(self._save)

        cancel_button = QPushButton("↩️")
        cancel_button.setObjectName("iconButton")
        cancel_button.setFixedWidth(44)
        cancel_button.setToolTip("انصراف")
        cancel_button.clicked.connect(self._reset_form)

        self.delete_button = QPushButton("🗑️")
        self.delete_button.setObjectName("dangerIconButton")
        self.delete_button.setFixedWidth(44)
        self.delete_button.setToolTip("حذف")
        self.delete_button.clicked.connect(self._delete)
        self.delete_button.setVisible(False)

        return wrap_scrollable_with_footer(panel, [save_button, cancel_button, self.delete_button])

    def refresh(self) -> None:
        self._reset_form()
        company_id = _company_id()
        if company_id is None:
            return

        self.employer_expense_account_combo.blockSignals(True)
        self.employer_expense_account_combo.clear()
        self.employer_expense_account_combo.addItem("", None)
        for a in coa_service.list_postable_accounts(company_id):
            self.employer_expense_account_combo.addItem(f"{a.full_code} — {a.name}", a.account_id)
        self.employer_expense_account_combo.blockSignals(False)

        self.employer_expense_detail_combo.blockSignals(True)
        self.employer_expense_detail_combo.clear()
        self.employer_expense_detail_combo.addItem("", None)
        for d in dimensions_service.list_all_leaf_detail_accounts(company_id):
            label = f"{d.full_code} — {d.name}" if d.name else d.full_code
            self.employer_expense_detail_combo.addItem(label, d.detail_account_id)
        self.employer_expense_detail_combo.blockSignals(False)

        self.insurance_description_template_field.setText(
            payroll_service.get_payroll_description_template(company_id, "PAYROLL_INSURANCE_EMPLOYER")
        )
        self._rows = payroll_service.list_insurance_configs(company_id)
        self.table.setRowCount(len(self._rows))
        for row_index, c in enumerate(self._rows):
            values = [
                numerals.to_persian_digits(str(c.unemployment_rate * 100)),
                numerals.to_persian_digits(str(c.employer_rate * 100)),
                numerals.to_persian_digits(str(c.employee_rate * 100)),
                numerals.to_persian_digits(c.effective_to.isoformat()) if c.effective_to else "—",
                numerals.to_persian_digits(c.effective_from.isoformat()),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, c.insurance_config_id)
                self.table.setItem(row_index, col_index, item)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        config_id = self.table.item(row, 0).data(Qt.UserRole)
        config = next((r for r in self._rows if r.insurance_config_id == config_id), None)
        if config is not None:
            self._load_into_form(config)

    def _load_into_form(self, c: payroll_service.InsuranceConfigRow) -> None:
        self._editing_id = c.insurance_config_id
        self.form_title.setText("ویرایشِ دوره")
        self.status_label.setText("")
        self.from_date_field.setDate(c.effective_from)
        self.to_date_unbounded_checkbox.setChecked(c.effective_to is None)
        if c.effective_to is not None:
            self.to_date_field.setDate(c.effective_to)
        self.employee_rate_field.setText(numerals.to_persian_digits(str(c.employee_rate * 100)))
        self.employer_rate_field.setText(numerals.to_persian_digits(str(c.employer_rate * 100)))
        self.unemployment_rate_field.setText(numerals.to_persian_digits(str(c.unemployment_rate * 100)))
        self.floor_field.setValue(float(c.insurable_wage_floor or 0))
        index = self.employer_expense_account_combo.findData(c.employer_expense_gl_account_id)
        self.employer_expense_account_combo.setCurrentIndex(index if index >= 0 else 0)
        index = self.employer_expense_detail_combo.findData(c.employer_expense_detail_account_id)
        self.employer_expense_detail_combo.setCurrentIndex(index if index >= 0 else 0)
        self.delete_button.setVisible(True)

    def _reset_form(self) -> None:
        self._editing_id = None
        self.form_title.setText("دورهٔ تازه")
        self.status_label.setText("")
        self.from_date_field.setDate(datetime.date.today())
        self.to_date_unbounded_checkbox.setChecked(True)
        self.to_date_field.setDate(datetime.date.today())
        self.employee_rate_field.clear()
        self.employer_rate_field.clear()
        self.unemployment_rate_field.clear()
        self.floor_field.setValue(0)
        self.employer_expense_account_combo.setCurrentIndex(0)
        self.employer_expense_detail_combo.setCurrentIndex(0)
        self.delete_button.setVisible(False)
        self.table.clearSelection()

    def _save(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        try:
            employee_rate = decimal.Decimal(numerals.to_ascii_digits(self.employee_rate_field.text())) / decimal.Decimal(100)
            employer_rate = decimal.Decimal(numerals.to_ascii_digits(self.employer_rate_field.text())) / decimal.Decimal(100)
            unemployment_rate = decimal.Decimal(numerals.to_ascii_digits(self.unemployment_rate_field.text())) / decimal.Decimal(100)
        except (decimal.InvalidOperation, ValueError):
            self.status_label.setText("نرخ‌ها را به‌صورتِ عدد وارد کنید.")
            return
        effective_from = self.from_date_field.date()
        effective_to = None if self.to_date_unbounded_checkbox.isChecked() else self.to_date_field.date()
        floor = decimal.Decimal(str(self.floor_field.value())) or None
        try:
            payroll_service.create_insurance_config(
                company_id, effective_from, effective_to, employee_rate, employer_rate, unemployment_rate, None, floor,
                employer_expense_gl_account_id=self.employer_expense_account_combo.currentData(),
                employer_expense_detail_account_id=self.employer_expense_detail_combo.currentData(),
            )
            template_text = (
                self.insurance_description_template_field.text().strip() or payroll_service.DEFAULT_PAYROLL_DESCRIPTION
            )
            payroll_service.set_payroll_description_template(company_id, "PAYROLL_INSURANCE_EMPLOYER", template_text)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return
        self.refresh()

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        confirm = QMessageBox.question(self, "حذفِ دوره", "این تنظیماتِ بیمه حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        payroll_service.delete_insurance_config(self._editing_id)
        self.refresh()


# ---------------------------------------------------------------------
# تبِ مالیات (فصلِ ۱۰)
# ---------------------------------------------------------------------
class _TaxTab(FieldHelpMixin, FormScreenBase):
    def __init__(self) -> None:
        super().__init__()
        self._bracket_rows: list[tuple[QLineEdit, QLineEdit, QLineEdit]] = []

        layout = self.body_layout
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        title = QLabel("پلکان‌هایِ مالیاتِ سالانه")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "پلکان‌ها باید پیوسته باشند (سقفِ هر پلکان = کفِ پلکانِ بعدی) و نرخ‌ها صعودی. "
            "سقفِ آخرین پلکان را خالی بگذارید (بدونِ سقف)."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.current_brackets_label = QLabel("")
        self.current_brackets_label.setWordWrap(True)
        layout.addWidget(self.current_brackets_label)

        self.brackets_container = QVBoxLayout()
        layout.addLayout(self.brackets_container)

        bracket_buttons = QHBoxLayout()
        add_row_button = QPushButton("➕")
        add_row_button.setObjectName("iconButton")
        add_row_button.setFixedWidth(44)
        add_row_button.setToolTip("افزودنِ پلکان")
        add_row_button.clicked.connect(lambda: self._add_bracket_row())
        bracket_buttons.addWidget(add_row_button)
        layout.addLayout(bracket_buttons)

        layout.addWidget(QLabel("از تاریخِ اجرا"))
        self.brackets_from_date_field = JalaliDateEdit()
        layout.addWidget(self.brackets_from_date_field)

        self.brackets_status_label = QLabel("")
        self.brackets_status_label.setObjectName("statusError")
        self.brackets_status_label.setWordWrap(True)
        layout.addWidget(self.brackets_status_label)

        layout.addWidget(QLabel("سقفِ معافیتِ سالانه (ریال)"))
        exemption_row = QHBoxLayout()
        self.exemption_field = _AmountField()
        exemption_row.addWidget(self.exemption_field)
        self.exemption_from_date_field = JalaliDateEdit()
        exemption_row.addWidget(self.exemption_from_date_field)
        layout.addLayout(exemption_row)

        self.exemption_status_label = QLabel("")
        self.exemption_status_label.setObjectName("statusError")
        self.exemption_status_label.setWordWrap(True)
        layout.addWidget(self.exemption_status_label)

        save_brackets_button = QPushButton("💾")
        save_brackets_button.setObjectName("primaryIconButton")
        save_brackets_button.setFixedWidth(48)
        save_brackets_button.setToolTip("ذخیرهٔ پلکان‌ها")
        save_brackets_button.clicked.connect(self._save_brackets)
        self.footer_layout.addWidget(save_brackets_button)

        save_exemption_button = QPushButton("💾")
        save_exemption_button.setObjectName("primaryIconButton")
        save_exemption_button.setFixedWidth(48)
        save_exemption_button.setToolTip("ذخیرهٔ سقفِ معافیت")
        save_exemption_button.clicked.connect(self._save_exemption)
        self.footer_layout.addWidget(save_exemption_button)
        self.footer_layout.addStretch(1)

    def _add_bracket_row(self, from_amount: str = "", to_amount: str = "", rate: str = "") -> None:
        row_layout = QHBoxLayout()
        from_field = _AmountField()
        if from_amount:
            from_field.setValue(float(from_amount))
        to_field = _AmountField()
        if to_amount:
            to_field.setValue(float(to_amount))
        rate_field = PersianDigitLineEdit(rate)
        row_layout.addWidget(QLabel("از"))
        row_layout.addWidget(from_field)
        row_layout.addWidget(QLabel("تا"))
        row_layout.addWidget(to_field)
        row_layout.addWidget(QLabel("نرخ٪"))
        row_layout.addWidget(rate_field)
        remove_button = QPushButton("✕")
        remove_button.setObjectName("dangerIconButton")
        remove_button.setFixedWidth(44)
        remove_button.setToolTip("حذفِ این ردیف")
        container = QWidget()
        container.setLayout(row_layout)
        row_layout.addWidget(remove_button)

        def _remove() -> None:
            self._bracket_rows.remove((from_field, to_field, rate_field))
            container.setParent(None)

        remove_button.clicked.connect(_remove)
        self.brackets_container.addWidget(container)
        self._bracket_rows.append((from_field, to_field, rate_field))

    def _clear_bracket_rows(self) -> None:
        while self._bracket_rows:
            from_field, to_field, rate_field = self._bracket_rows[0]
            from_field.parent().setParent(None)
            self._bracket_rows.pop(0)

    def refresh(self) -> None:
        company_id = _company_id()
        self._clear_bracket_rows()
        self.brackets_status_label.setText("")
        self.exemption_status_label.setText("")
        self.brackets_from_date_field.setDate(datetime.date.today())
        self.exemption_from_date_field.setDate(datetime.date.today())
        self.exemption_field.setValue(0)
        if company_id is None:
            return
        as_of = datetime.date.today()
        brackets = payroll_service.get_tax_brackets(company_id, as_of)
        if brackets:
            parts = []
            for b in brackets:
                to_text = numerals.format_company_amount(b.to_annual_amount) if b.to_annual_amount is not None else "∞"
                parts.append(f"{numerals.format_company_amount(b.from_annual_amount)} تا {to_text}: {numerals.to_persian_digits(str(b.rate * 100))}٪")
            self.current_brackets_label.setText("پلکان‌هایِ فعلی — " + " | ".join(parts))
            for b in brackets:
                self._add_bracket_row(str(b.from_annual_amount), str(b.to_annual_amount) if b.to_annual_amount is not None else "", str(b.rate * 100))
        else:
            self.current_brackets_label.setText("هیچ پلکانِ مالیاتی‌ای هنوز تعریف نشده است.")
            self._add_bracket_row()

        exemption = payroll_service.get_tax_exemption(company_id, as_of)
        if exemption is not None:
            self.exemption_field.setValue(float(exemption))

    def _save_brackets(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        brackets = []
        try:
            for from_field, to_field, rate_field in self._bracket_rows:
                from_amount = decimal.Decimal(str(from_field.value()))
                to_amount = decimal.Decimal(str(to_field.value())) if to_field.value() > 0 else None
                rate = decimal.Decimal(numerals.to_ascii_digits(rate_field.text()) or "0") / decimal.Decimal(100)
                brackets.append((from_amount, to_amount, rate))
        except (decimal.InvalidOperation, ValueError):
            self.brackets_status_label.setText("مقادیرِ پلکان‌ها را به‌صورتِ عدد وارد کنید.")
            return
        try:
            payroll_service.set_tax_brackets(company_id, self.brackets_from_date_field.date(), brackets)
        except ValueError as exc:
            theme.set_status_label(self.brackets_status_label, str(exc), ok=False)
            return
        theme.set_status_label(self.brackets_status_label, "ذخیره شد.", ok=True)
        self.refresh()

    def _save_exemption(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        amount = decimal.Decimal(str(self.exemption_field.value()))
        try:
            payroll_service.set_tax_exemption(company_id, self.exemption_from_date_field.date(), amount)
        except ValueError as exc:
            theme.set_status_label(self.exemption_status_label, str(exc), ok=False)
            return
        theme.set_status_label(self.exemption_status_label, "ذخیره شد.", ok=True)


# ---------------------------------------------------------------------
# تبِ قوانینِ اضافه‌کاری (فصلِ ۱۲) — طبقِ گزارشِ کاربر: بک‌اند از قبل
# پیاده‌سازی شده بود ولی هیچ UIای برایِ تعریفِ قوانین/ثبتِ ساعات نداشت.
# این تب فقط «قوانین» (ضریب/حالتِ ترکیب/بازهٔ اجرا) را مدیریت می‌کند؛
# «ثبت/تاییدِ ساعات» در صفحهٔ عملیاتیِ جداگانه‌یِ payroll_overtime_entries.py
# است، چون آن‌ها تراکنشی‌اند نه تنظیماتی.
# ---------------------------------------------------------------------
_OVERTIME_RULE_CODE_LABELS = [
    ("OVERTIME", "اضافه‌کاریِ عادی"),
    ("NIGHT_SHIFT", "شب‌کاری"),
    ("HOLIDAY_WORK", "تعطیل‌کاری"),
    ("FRIDAY_WORK", "جمعه‌کاری"),
    ("ROTATING_SHIFT_BONUS", "فوق‌العادهٔ شیفتِ گردشی"),
]
_STACKING_MODE_LABELS = [
    ("ADDITIVE", "جمعی (افزایشی)"),
    ("MULTIPLICATIVE", "ضربی"),
    ("MAX_ONLY", "فقط بیشترین"),
]
_OVERTIME_RULE_COLUMNS = ["تا تاریخ", "از تاریخ", "حالتِ ترکیب", "ضریب", "نوع"]


class _OvertimeRulesTab(FieldHelpMixin, LayoutEditMixin, QWidget):
    # طبقِ رفعِ باگِ «دکمه‌یِ ذخیره زیرِ تسک‌بار»: هر دو ستون (لیست/فرم)
    # خودشان اسکرول+فوترِ ثابت دارند (_wrap_scrollable) — نباید
    # system_settings.py::_sub_tabs دوباره کلِ این ویجت را بپیچد.
    manages_own_scroll = True

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[overtime_service.OvertimeRuleRow] = []
        self._editing_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)

        self.set_field_help([
            (self.multiplier_field, "ضریبِ این نوعِ اضافه‌کاری — مثلاً ۱٫۴ برایِ ۴۰٪ اضافه."),
            (self.stacking_mode_combo, "وقتی چند نوعِ اضافه‌کاری هم‌زمان رخ می‌دهد، ضرایب چگونه ترکیب شوند."),
        ])
        self.register_field_grids("payroll_settings_overtime_rules", [self.form_grid])

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        title = QLabel("قوانینِ اضافه‌کاری")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.table = QTableWidget(0, len(_OVERTIME_RULE_COLUMNS))
        self.table.setHorizontalHeaderLabels(_OVERTIME_RULE_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)
        return _wrap_scrollable(panel)

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        self.form_title = QLabel("قانونِ تازه")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        self.code_combo = QComboBox()
        for code, label in _OVERTIME_RULE_CODE_LABELS:
            self.code_combo.addItem(label, code)

        self.multiplier_field = PersianDigitLineEdit()

        self.stacking_mode_combo = QComboBox()
        for code, label in _STACKING_MODE_LABELS:
            self.stacking_mode_combo.addItem(label, code)

        self.max_hours_policy_field = QLineEdit()

        self.from_date_field = JalaliDateEdit()

        self.to_date_field = JalaliDateEdit()
        self.to_date_unbounded_checkbox = QCheckBox("تا اطلاعِ ثانوی (بدونِ تاریخِ پایان)")
        self.to_date_unbounded_checkbox.setChecked(True)
        self.to_date_unbounded_checkbox.toggled.connect(lambda checked: self.to_date_field.setEnabled(not checked))
        self.to_date_field.setEnabled(False)

        self.form_grid = FieldGrid([
            FieldSpec("code", "نوع", self.code_combo, span=1),
            FieldSpec("multiplier", "ضریب", self.multiplier_field, span=1),
            FieldSpec("stacking_mode", "حالتِ ترکیبِ ضرایب", self.stacking_mode_combo, span=1),
            FieldSpec("max_hours_policy", "کدِ سیاستِ سقفِ ساعتِ ماهانه (اختیاری)", self.max_hours_policy_field, span=2),
            FieldSpec("from_date", "از تاریخِ اجرا", self.from_date_field, span=1),
            FieldSpec("to_date", "تا تاریخ", self.to_date_field, span=1),
            FieldSpec("to_date_unbounded", "", self.to_date_unbounded_checkbox, span=2),
        ])
        layout.addWidget(self.form_grid)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        save_button = QPushButton("💾")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(48)
        save_button.setToolTip("ذخیره")
        save_button.clicked.connect(self._save)

        cancel_button = QPushButton("↩️")
        cancel_button.setObjectName("iconButton")
        cancel_button.setFixedWidth(44)
        cancel_button.setToolTip("انصراف")
        cancel_button.clicked.connect(self._reset_form)

        self.delete_button = QPushButton("🗑️")
        self.delete_button.setObjectName("dangerIconButton")
        self.delete_button.setFixedWidth(44)
        self.delete_button.setToolTip("حذف")
        self.delete_button.clicked.connect(self._delete)
        self.delete_button.setVisible(False)

        return wrap_scrollable_with_footer(panel, [save_button, cancel_button, self.delete_button])

    def refresh(self) -> None:
        self._reset_form()
        company_id = _company_id()
        if company_id is None:
            return
        self._rows = overtime_service.list_overtime_rules(company_id)
        code_labels = dict(_OVERTIME_RULE_CODE_LABELS)
        stacking_labels = dict(_STACKING_MODE_LABELS)
        self.table.setRowCount(len(self._rows))
        for row_index, r in enumerate(self._rows):
            values = [
                numerals.to_persian_digits(r.effective_to.isoformat()) if r.effective_to else "—",
                numerals.to_persian_digits(r.effective_from.isoformat()),
                stacking_labels.get(r.stacking_mode, r.stacking_mode),
                numerals.to_persian_digits(str(r.multiplier)),
                code_labels.get(r.code, r.code),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, r.overtime_rule_id)
                self.table.setItem(row_index, col_index, item)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        rule_id = self.table.item(row, 0).data(Qt.UserRole)
        rule = next((r for r in self._rows if r.overtime_rule_id == rule_id), None)
        if rule is not None:
            self._load_into_form(rule)

    def _load_into_form(self, r: overtime_service.OvertimeRuleRow) -> None:
        self._editing_id = r.overtime_rule_id
        self.form_title.setText("ویرایشِ قانون")
        self.status_label.setText("")
        self.code_combo.setCurrentIndex(self.code_combo.findData(r.code))
        self.code_combo.setEnabled(False)
        self.multiplier_field.setText(numerals.to_persian_digits(str(r.multiplier)))
        self.stacking_mode_combo.setCurrentIndex(self.stacking_mode_combo.findData(r.stacking_mode))
        self.max_hours_policy_field.setText(r.max_monthly_hours_policy_code or "")
        self.from_date_field.setDate(r.effective_from)
        self.from_date_field.setEnabled(False)
        self.to_date_unbounded_checkbox.setChecked(r.effective_to is None)
        self.to_date_unbounded_checkbox.setEnabled(False)
        if r.effective_to is not None:
            self.to_date_field.setDate(r.effective_to)
        self.delete_button.setVisible(True)

    def _reset_form(self) -> None:
        self._editing_id = None
        self.form_title.setText("قانونِ تازه")
        self.status_label.setText("")
        self.code_combo.setCurrentIndex(0)
        self.code_combo.setEnabled(True)
        self.multiplier_field.clear()
        self.stacking_mode_combo.setCurrentIndex(0)
        self.max_hours_policy_field.clear()
        self.from_date_field.setDate(datetime.date.today())
        self.from_date_field.setEnabled(True)
        self.to_date_unbounded_checkbox.setChecked(True)
        self.to_date_unbounded_checkbox.setEnabled(True)
        self.to_date_field.setDate(datetime.date.today())
        self.delete_button.setVisible(False)
        self.table.clearSelection()

    def _save(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        try:
            multiplier = decimal.Decimal(numerals.to_ascii_digits(self.multiplier_field.text()) or "0")
        except decimal.InvalidOperation:
            self.status_label.setText("ضریب را به‌صورتِ عدد وارد کنید.")
            return
        stacking_mode = self.stacking_mode_combo.currentData()
        max_hours_policy_code = self.max_hours_policy_field.text().strip() or None
        try:
            if self._editing_id is not None:
                overtime_service.update_overtime_rule(self._editing_id, multiplier, stacking_mode, max_hours_policy_code)
            else:
                effective_to = None if self.to_date_unbounded_checkbox.isChecked() else self.to_date_field.date()
                overtime_service.create_overtime_rule(
                    company_id, self.code_combo.currentData(), multiplier, stacking_mode,
                    max_hours_policy_code, self.from_date_field.date(), effective_to,
                )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        confirm = QMessageBox.question(self, "حذفِ قانون", "این قانونِ اضافه‌کاری حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            overtime_service.delete_overtime_rule(self._editing_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()


_DATE_FORMAT_OPTIONS = [
    ("%Y-%m-%d", "۱۴۰۴-۰۵-۱۶ (سال-ماه-روز، خط‌تیره)"),
    ("%Y/%m/%d", "۱۴۰۴/۰۵/۱۶ (سال/ماه/روز)"),
    ("%d/%m/%Y", "۱۶/۰۵/۱۴۰۴ (روز/ماه/سال)"),
    ("%m/%d/%Y", "۰۵/۱۶/۱۴۰۴ (ماه/روز/سال)"),
]
_TIME_FORMAT_OPTIONS = [
    ("%H:%M", "۰۸:۳۰ (۲۴ساعته)"),
    ("%H:%M:%S", "۰۸:۳۰:۰۰ (۲۴ساعته با ثانیه)"),
    ("%I:%M %p", "۰۸:۳۰ AM (۱۲ساعته)"),
]


class _AttendanceTemplatesTab(FieldHelpMixin, LayoutEditMixin, QWidget):
    """الگوهایِ ذخیره‌شدهٔ ایمپورتِ CSV/اکسلِ دستگاه‌هایِ حضوروغیاب — طبقِ
    خواستهٔ صریح («الگویِ فایلِ csv شرکت‌هایِ دستگاه‌دارِ حضوروغیاب تعریف
    کنم») تا فرمِ ورود/خروجِ کارکنان (hr_attendance_entries.py) بتواند با
    فقط انتخابِ مسیرِ فایل، بدونِ تناظرِ دستیِ ستون‌ها، ایمپورت کند."""

    manages_own_scroll = True

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[attendance_service.AttendanceImportTemplateRow] = []
        self._editing_id: int | None = None
        self._pending_mapping: dict | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)

        self.set_field_help([
            (
                self.define_columns_button,
                "یک فایلِ نمونهٔ خروجیِ دستگاه (CSV یا اکسل) را انتخاب کنید و ستون‌هایش را یک‌بار مشخص کنید — "
                "این تناظر با همین الگو ذخیره می‌شود تا دفعاتِ بعد تکرار نشود.",
            ),
        ])
        self.register_field_grids("payroll_settings_attendance_templates", [self.form_grid])

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        title = QLabel("الگوهایِ ایمپورتِ حضوروغیاب")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "هر الگو، تناظرِ ستون‌هایِ فایلِ خروجیِ یک شرکتِ سازندهٔ دستگاهِ حضوروغیاب را ذخیره می‌کند — "
            "برایِ ایمپورتِ بعدی، فقط کافی‌ست الگو و مسیرِ فایل انتخاب شود."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["فرمتِ ساعت/تاریخ", "نامِ الگو"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)
        return _wrap_scrollable(panel)

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        self.form_title = QLabel("الگویِ تازه")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        self.name_field = QLineEdit()

        self.header_row_checkbox = QCheckBox("ردیفِ اولِ فایل، عنوانِ ستون‌هاست")
        self.header_row_checkbox.setChecked(True)

        self.date_format_combo = QComboBox()
        for value, label in _DATE_FORMAT_OPTIONS:
            self.date_format_combo.addItem(label, value)

        self.time_format_combo = QComboBox()
        for value, label in _TIME_FORMAT_OPTIONS:
            self.time_format_combo.addItem(label, value)

        self.form_grid = FieldGrid([
            FieldSpec("name", "نامِ الگو (مثلاً نامِ شرکتِ سازندهٔ دستگاه)", self.name_field, span=2),
            FieldSpec("header_row", "", self.header_row_checkbox, span=1),
            FieldSpec("date_format", "فرمتِ تاریخ در فایل", self.date_format_combo, span=2),
            FieldSpec("time_format", "فرمتِ ساعت در فایل", self.time_format_combo, span=1),
        ])
        layout.addWidget(self.form_grid)

        self.define_columns_button = QPushButton("➕")
        self.define_columns_button.setObjectName("iconButton")
        self.define_columns_button.setFixedWidth(44)
        self.define_columns_button.setToolTip("تعریفِ ستون‌ها از رویِ فایلِ نمونه…")
        self.define_columns_button.clicked.connect(self._on_define_columns)
        layout.addWidget(self.define_columns_button)

        self.mapping_status_label = QLabel("هنوز ستون‌ها مشخص نشده‌اند.")
        self.mapping_status_label.setObjectName("sectionHint")
        self.mapping_status_label.setWordWrap(True)
        layout.addWidget(self.mapping_status_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        save_button = QPushButton("💾")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(48)
        save_button.setToolTip("ذخیره")
        save_button.clicked.connect(self._save)

        cancel_button = QPushButton("↩️")
        cancel_button.setObjectName("iconButton")
        cancel_button.setFixedWidth(44)
        cancel_button.setToolTip("انصراف")
        cancel_button.clicked.connect(self._reset_form)

        self.delete_button = QPushButton("🗑️")
        self.delete_button.setObjectName("dangerIconButton")
        self.delete_button.setFixedWidth(44)
        self.delete_button.setToolTip("حذف")
        self.delete_button.clicked.connect(self._delete)
        self.delete_button.setVisible(False)

        return wrap_scrollable_with_footer(panel, [save_button, cancel_button, self.delete_button])

    def refresh(self) -> None:
        self._reset_form()
        company_id = _company_id()
        if company_id is None:
            return
        self._rows = attendance_service.list_attendance_import_templates(company_id)
        self.table.setRowCount(len(self._rows))
        for row_index, t in enumerate(self._rows):
            values = [f"{t.date_format} / {t.time_format}", t.name]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, t.template_id)
                self.table.setItem(row_index, col_index, item)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        template_id = self.table.item(row, 0).data(Qt.UserRole)
        template = next((t for t in self._rows if t.template_id == template_id), None)
        if template is not None:
            self._load_into_form(template)

    def _load_into_form(self, t: attendance_service.AttendanceImportTemplateRow) -> None:
        self._editing_id = t.template_id
        self._pending_mapping = dict(t.column_mapping)
        self.form_title.setText("ویرایشِ الگو")
        self.status_label.setText("")
        self.name_field.setText(t.name)
        self.header_row_checkbox.setChecked(t.has_header_row)
        index = self.date_format_combo.findData(t.date_format)
        self.date_format_combo.setCurrentIndex(index if index >= 0 else 0)
        index = self.time_format_combo.findData(t.time_format)
        self.time_format_combo.setCurrentIndex(index if index >= 0 else 0)
        self.mapping_status_label.setText("ستون‌هایِ این الگو قبلاً مشخص شده‌اند؛ برایِ تغییر، دوباره تعریف کنید.")
        self.delete_button.setVisible(True)

    def _reset_form(self) -> None:
        self._editing_id = None
        self._pending_mapping = None
        self.form_title.setText("الگویِ تازه")
        self.status_label.setText("")
        self.name_field.clear()
        self.header_row_checkbox.setChecked(True)
        self.date_format_combo.setCurrentIndex(0)
        self.time_format_combo.setCurrentIndex(0)
        self.mapping_status_label.setText("هنوز ستون‌ها مشخص نشده‌اند.")
        self.delete_button.setVisible(False)
        self.table.clearSelection()

    def _on_define_columns(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "انتخابِ فایلِ نمونهٔ حضوروغیاب", "", "Excel/CSV Files (*.xlsx *.csv)"
        )
        if not path:
            return
        rows = read_excel_rows(self, path)
        if rows is None:
            return
        dialog = ExcelColumnMappingDialog(
            _IMPORT_TARGET_FIELDS, _IMPORT_GUESS_KEYWORDS, rows[0], self,
            title="تعریفِ ستون‌هایِ الگو",
        )
        if dialog.exec() != QDialog.Accepted:
            return
        mapping = dialog.mapping()
        if mapping.get("worked_hours") is None and (mapping.get("clock_in") is None or mapping.get("clock_out") is None):
            QMessageBox.warning(
                self, "ناقص", "یا «مجموعِ ساعتِ کارکرد» را مشخص کنید، یا هر دویِ «ساعتِ ورود» و «ساعتِ خروج» را."
            )
            return
        self._pending_mapping = mapping
        self.header_row_checkbox.setChecked(dialog.skip_header_row())
        self.mapping_status_label.setText("ستون‌ها از رویِ فایلِ نمونه مشخص شدند — حالا نام را وارد و ذخیره کنید.")

    def _save(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        if self._pending_mapping is None:
            self.status_label.setText("اول ستون‌ها را از رویِ یک فایلِ نمونه تعریف کنید.")
            return
        name = self.name_field.text().strip()
        date_format = self.date_format_combo.currentData()
        time_format = self.time_format_combo.currentData()
        has_header_row = self.header_row_checkbox.isChecked()
        try:
            if self._editing_id is not None:
                attendance_service.update_attendance_import_template(
                    self._editing_id, name, has_header_row, date_format, time_format, self._pending_mapping
                )
            else:
                attendance_service.create_attendance_import_template(
                    company_id, name, has_header_row, date_format, time_format, self._pending_mapping
                )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        confirm = QMessageBox.question(self, "حذفِ الگو", "این الگویِ ایمپورت حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        attendance_service.delete_attendance_import_template(self._editing_id)
        self.refresh()


# طبقِ درخواستِ صریح: دیگر صفحه‌یِ مستقلِ خودش نیست — این ۷ کلاسِ تب مستقیم
# در system_settings.py::_build_payroll_tab (با _sub_tabs) استفاده می‌شوند،
# هم‌الگو با financial_statement_mapping.py.
