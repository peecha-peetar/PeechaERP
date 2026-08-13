"""مدیریتِ وام و مساعده (فصلِ ۱۳) — درخواست، تایید، پرداخت، و مشاهده/
موکول‌کردن/بخششِ اقساط، به‌ازایِ هر کارمند."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
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
from peecha.services import hr as hr_service
from peecha.services import payroll as payroll_service
from peecha.services import payroll_loans as loan_service
from peecha.ui import theme
from peecha.ui.widgets import FieldHelpMixin, ZeroPaddedSpinBox

_LOAN_COLUMNS = ["وضعیت", "منبعِ تامین", "تعدادِ اقساط", "نرخِ کارمزد", "مبلغِ اصل", "نوع"]
_INSTALLMENT_COLUMNS = ["وضعیت", "مبلغ", "دورهٔ سررسید", "شمارهٔ قسط"]
_LOAN_STATUS_LABELS = {
    "REQUESTED": "درخواست‌شده", "APPROVED": "تاییدشده", "DISBURSED": "پرداخت‌شده",
    "ACTIVE": "درحالِ کسر", "SETTLED": "تسویه‌شده", "REJECTED": "ردشده", "CANCELLED": "لغوشده",
}
_INSTALLMENT_STATUS_LABELS = {"PENDING": "درانتظار", "DEDUCTED": "کسرشده", "DEFERRED": "موکول‌شده", "WAIVED": "بخشیده‌شده"}


def _company_id() -> int | None:
    return app_session.current_company.company_id if app_session.current_company else None


class PayrollLoansScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._employees: list[hr_service.EmployeeRow] = []
        self._loans: list[loan_service.LoanRow] = []
        self._periods: list[payroll_service.PeriodRow] = []
        self._selected_loan_id: int | None = None
        self._selected_installment_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_form_panel(), stretch=2)
        outer.addWidget(self._build_loans_panel(), stretch=3)
        outer.addWidget(self._build_installments_panel(), stretch=3)

        self.set_field_help([
            (self.principal_field, "مبلغِ اصلِ وام/مساعده."),
            (self.fee_rate_field, "نرخِ کارمزد به‌صورتِ اعشاری (مثلاً ۰٫۰۵ برایِ ۵٪) — می‌تواند صفر باشد."),
        ])

    def _wrap_scrollable(self, content: QWidget) -> QWidget:
        # طبقِ آیتمِ ۱ (اسکرول+فوترِ ثابت): سه ستونِ این صفحه (فرمِ
        # درخواست/وام‌ها/اقساط) فرم‌هایِ کوچکِ مستقل‌اند، نه یک فرمِ
        # یکپارچه با یک فوترِ واحد — هرکدام جداگانه، هم‌الگو با
        # treasury_checks.py و payroll_run.py، در کارتِ خودش اسکرول
        # می‌شود تا دکمه‌هایِ پایینِ همان ستون هیچ‌وقت با کوچک‌شدنِ
        # زیرپنجره گم نشوند.
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

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("درخواستِ وام/مساعدهٔ تازه")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        layout.addWidget(QLabel("کارمند"))
        self.employee_combo = QComboBox()
        self.employee_combo.currentIndexChanged.connect(self._on_employee_changed)
        layout.addWidget(self.employee_combo)

        layout.addWidget(QLabel("نوعِ وام"))
        self.loan_type_combo = QComboBox()
        self.loan_type_combo.addItem("وام (چندقسطی)", "LOAN")
        self.loan_type_combo.addItem("مساعده (معمولاً تک‌قسطی)", "ADVANCE")
        layout.addWidget(self.loan_type_combo)

        layout.addWidget(QLabel("مبلغِ اصل"))
        self.principal_field = QLineEdit()
        layout.addWidget(self.principal_field)

        layout.addWidget(QLabel("نرخِ کارمزد (۰ تا ۱)"))
        self.fee_rate_field = QLineEdit()
        self.fee_rate_field.setText("0")
        layout.addWidget(self.fee_rate_field)

        layout.addWidget(QLabel("تعدادِ اقساط"))
        self.installments_field = ZeroPaddedSpinBox()
        self.installments_field.setRange(1, 60)
        self.installments_field.setValue(1)
        layout.addWidget(self.installments_field)

        layout.addWidget(QLabel("دورهٔ شروعِ کسر"))
        self.start_period_combo = QComboBox()
        layout.addWidget(self.start_period_combo)

        layout.addWidget(QLabel("منبعِ تامینِ مالی"))
        self.funding_source_field = QLineEdit()
        layout.addWidget(self.funding_source_field)

        self.form_status_label = QLabel("")
        self.form_status_label.setWordWrap(True)
        layout.addWidget(self.form_status_label)

        create_button = QPushButton("+ ثبتِ درخواست")
        create_button.setObjectName("primaryButton")
        create_button.clicked.connect(self._create_loan)
        layout.addWidget(create_button)
        layout.addStretch(1)
        return self._wrap_scrollable(panel)

    def _build_loans_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("وام‌هایِ کارمندِ انتخاب‌شده")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.loans_table = QTableWidget(0, len(_LOAN_COLUMNS))
        self.loans_table.setHorizontalHeaderLabels(_LOAN_COLUMNS)
        self.loans_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.loans_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.loans_table.verticalHeader().setVisible(False)
        self.loans_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.loans_table.cellClicked.connect(self._on_loan_clicked)
        layout.addWidget(self.loans_table, stretch=1)

        self.loan_status_label = QLabel("")
        self.loan_status_label.setWordWrap(True)
        layout.addWidget(self.loan_status_label)

        button_row = QHBoxLayout()
        approve_button = QPushButton("تایید")
        approve_button.clicked.connect(self._approve_selected_loan)
        button_row.addWidget(approve_button)
        reject_button = QPushButton("رد")
        reject_button.clicked.connect(self._reject_selected_loan)
        button_row.addWidget(reject_button)
        disburse_button = QPushButton("پرداخت (تولیدِ اقساط)")
        disburse_button.setObjectName("primaryButton")
        disburse_button.clicked.connect(self._disburse_selected_loan)
        button_row.addWidget(disburse_button)
        cancel_button = QPushButton("لغو")
        cancel_button.setObjectName("dangerButton")
        cancel_button.clicked.connect(self._cancel_selected_loan)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)
        return self._wrap_scrollable(panel)

    def _build_installments_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("اقساطِ وامِ انتخاب‌شده")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.installments_table = QTableWidget(0, len(_INSTALLMENT_COLUMNS))
        self.installments_table.setHorizontalHeaderLabels(_INSTALLMENT_COLUMNS)
        self.installments_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.installments_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.installments_table.verticalHeader().setVisible(False)
        self.installments_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.installments_table.cellClicked.connect(self._on_installment_clicked)
        layout.addWidget(self.installments_table, stretch=1)

        self.outstanding_label = QLabel("")
        layout.addWidget(self.outstanding_label)

        button_row = QHBoxLayout()
        defer_button = QPushButton("موکول‌کردن به دورهٔ بعد")
        defer_button.clicked.connect(self._defer_selected_installment)
        button_row.addWidget(defer_button)
        waive_button = QPushButton("بخشش")
        waive_button.clicked.connect(self._waive_selected_installment)
        button_row.addWidget(waive_button)
        layout.addLayout(button_row)
        return self._wrap_scrollable(panel)

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        self._employees = hr_service.list_employees(company_id)
        # طبقِ‌بالا، rebuildِ combo موقتاً currentIndexChanged (و درنتیجه
        # _refresh_loans) را با index=-1 صدا می‌زند و انتخابِ فعلی را پاک
        # می‌کند؛ برایِ اینکه پرداختِ وام/تاییدِ وام بعدِ refresh() انتخاب
        # را از دست ندهد، این‌جا نگه‌داشته و در پایان بازگردانده می‌شود.
        preserved_loan_id = self._selected_loan_id
        self.employee_combo.clear()
        for e in self._employees:
            self.employee_combo.addItem(f"{e.employee_code} — {e.full_name}", e.employee_id)
        self._selected_loan_id = preserved_loan_id

        self._periods = payroll_service.list_periods(company_id)
        self.start_period_combo.clear()
        for p in self._periods:
            label = numerals.to_persian_digits(f"{p.jalali_year}/{p.jalali_month:02d}")
            self.start_period_combo.addItem(label, p.period_id)

        self._refresh_loans()

    def _selected_employee_id(self) -> int | None:
        return self.employee_combo.currentData()

    def _on_employee_changed(self, _index: int) -> None:
        self._refresh_loans()

    def _refresh_loans(self) -> None:
        self._loans = []
        self.loans_table.setRowCount(0)
        self._clear_installments()
        employee_id = self._selected_employee_id()
        if employee_id is None:
            self._selected_loan_id = None
            return
        self._loans = loan_service.list_loans(employee_id)
        self.loans_table.setRowCount(len(self._loans))
        for row_index, loan in enumerate(self._loans):
            values = [
                _LOAN_STATUS_LABELS.get(loan.status, loan.status),
                loan.funding_source or "—",
                numerals.to_persian_digits(str(loan.installments_count)),
                numerals.to_persian_digits(str(loan.fee_rate)),
                numerals.format_amount(loan.principal_amount),
                "وام" if loan.loan_type == "LOAN" else "مساعده",
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, loan.loan_id)
                self.loans_table.setItem(row_index, col_index, item)
        # حفظِ انتخابِ فعلی پس از بازخوانی (مثلاً بعدِ تایید/پرداخت) — فقط
        # هنگامِ تغییرِ کارمند باید انتخاب واقعاً پاک شود، نه هر بازخوانی
        if self._selected_loan_id is not None and self._selected_loan_id not in {loan.loan_id for loan in self._loans}:
            self._selected_loan_id = None
        if self._selected_loan_id is not None:
            self._refresh_installments()

    def _on_loan_clicked(self, row: int, _column: int) -> None:
        self._selected_loan_id = self.loans_table.item(row, 0).data(Qt.UserRole)
        self._refresh_installments()

    def _clear_installments(self) -> None:
        self._selected_installment_id = None
        self.installments_table.setRowCount(0)
        self.outstanding_label.setText("")

    def _refresh_installments(self) -> None:
        self.installments_table.setRowCount(0)
        if self._selected_loan_id is None:
            return
        installments = loan_service.list_installments(self._selected_loan_id)
        periods_by_id = {p.period_id: p for p in self._periods}
        self.installments_table.setRowCount(len(installments))
        for row_index, inst in enumerate(installments):
            period = periods_by_id.get(inst.due_period_id)
            period_label = numerals.to_persian_digits(f"{period.jalali_year}/{period.jalali_month:02d}") if period else "—"
            values = [
                _INSTALLMENT_STATUS_LABELS.get(inst.status, inst.status),
                numerals.format_amount(inst.amount),
                period_label,
                numerals.to_persian_digits(str(inst.installment_no)),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, inst.loan_installment_id)
                self.installments_table.setItem(row_index, col_index, item)
        outstanding = loan_service.total_outstanding_balance(self._selected_loan_id)
        self.outstanding_label.setText(f"ماندهٔ پرداخت‌نشده: {numerals.format_amount(outstanding)}")

    def _on_installment_clicked(self, row: int, _column: int) -> None:
        self._selected_installment_id = self.installments_table.item(row, 0).data(Qt.UserRole)

    def _create_loan(self) -> None:
        employee_id = self._selected_employee_id()
        start_period_id = self.start_period_combo.currentData()
        if employee_id is None or start_period_id is None:
            theme.set_status_label(self.form_status_label, "کارمند و دورهٔ شروع را انتخاب کنید.", ok=False)
            return
        try:
            principal = decimal.Decimal(numerals.to_ascii_digits(self.principal_field.text()) or "0")
            fee_rate = decimal.Decimal(numerals.to_ascii_digits(self.fee_rate_field.text()) or "0")
        except decimal.InvalidOperation:
            theme.set_status_label(self.form_status_label, "مبلغ/نرخِ واردشده نامعتبر است.", ok=False)
            return
        try:
            loan_service.create_loan(
                employee_id, self.loan_type_combo.currentData(), principal, fee_rate,
                self.installments_field.value(), start_period_id, self.funding_source_field.text().strip() or None,
            )
        except ValueError as exc:
            theme.set_status_label(self.form_status_label, str(exc), ok=False)
            return
        theme.set_status_label(self.form_status_label, "درخواست ثبت شد.", ok=True)
        self.principal_field.clear()
        self.fee_rate_field.setText("0")
        self.funding_source_field.clear()
        self._refresh_loans()

    def _approve_selected_loan(self) -> None:
        if self._selected_loan_id is None:
            QMessageBox.information(self, "تاییدِ وام", "یک وام را از فهرست انتخاب کنید.")
            return
        try:
            loan_service.approve_loan(self._selected_loan_id)
        except ValueError as exc:
            theme.set_status_label(self.loan_status_label, str(exc), ok=False)
            return
        theme.set_status_label(self.loan_status_label, "وام تایید شد.", ok=True)
        self._refresh_loans()

    def _reject_selected_loan(self) -> None:
        if self._selected_loan_id is None:
            QMessageBox.information(self, "ردِ وام", "یک وام را از فهرست انتخاب کنید.")
            return
        try:
            loan_service.reject_loan(self._selected_loan_id)
        except ValueError as exc:
            theme.set_status_label(self.loan_status_label, str(exc), ok=False)
            return
        theme.set_status_label(self.loan_status_label, "وام رد شد.", ok=True)
        self._refresh_loans()

    def _disburse_selected_loan(self) -> None:
        if self._selected_loan_id is None:
            QMessageBox.information(self, "پرداختِ وام", "یک وام را از فهرست انتخاب کنید.")
            return
        company_id = _company_id()
        if company_id is None:
            return
        try:
            loan_service.disburse_loan(self._selected_loan_id, company_id)
        except ValueError as exc:
            theme.set_status_label(self.loan_status_label, str(exc), ok=False)
            return
        theme.set_status_label(self.loan_status_label, "وام پرداخت شد و جدولِ اقساط ساخته شد.", ok=True)
        self.refresh()

    def _cancel_selected_loan(self) -> None:
        if self._selected_loan_id is None:
            QMessageBox.information(self, "لغوِ وام", "یک وام را از فهرست انتخاب کنید.")
            return
        try:
            loan_service.cancel_loan(self._selected_loan_id)
        except ValueError as exc:
            theme.set_status_label(self.loan_status_label, str(exc), ok=False)
            return
        theme.set_status_label(self.loan_status_label, "وام لغو شد.", ok=True)
        self._refresh_loans()

    def _defer_selected_installment(self) -> None:
        installment_id = self._selected_installment_id
        company_id = _company_id()
        if installment_id is None or company_id is None:
            QMessageBox.information(self, "موکول‌کردنِ قسط", "یک قسط را از فهرست انتخاب کنید.")
            return
        try:
            loan_service.defer_installment(installment_id, company_id)
        except ValueError as exc:
            QMessageBox.warning(self, "موکول‌کردنِ قسط", str(exc))
            return
        self._refresh_installments()

    def _waive_selected_installment(self) -> None:
        installment_id = self._selected_installment_id
        company_id = _company_id()
        if installment_id is None or company_id is None:
            QMessageBox.information(self, "بخششِ قسط", "یک قسط را از فهرست انتخاب کنید.")
            return
        reason, ok = QInputDialog.getText(self, "بخششِ قسط", "دلیلِ بخشش (الزامی):")
        if not ok:
            return
        user_id = app_session.current_user.user_id if app_session.current_user else None
        try:
            loan_service.waive_installment(installment_id, reason, company_id, user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "بخششِ قسط", str(exc))
            return
        self._refresh_installments()
