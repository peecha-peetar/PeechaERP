"""اجرایِ محاسبهٔ حقوق (فصلِ ۱۱) — انتخاب/ساختِ دوره، اجرایِ موتور، و
نمایشِ نتیجه به‌ازایِ هر کارمند."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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
from peecha.services import payroll as payroll_service
from peecha.services import payroll_bank_file as bank_service
from peecha.services import payroll_engine as engine
from peecha.services import payroll_journal as journal_service
from peecha.services import payroll_payslip as payslip_service
from peecha.services import treasury as treasury_service
from peecha.ui import report_export
from peecha.ui import theme
from peecha.ui.widgets import FieldHelpMixin, JalaliDateEdit, ZeroPaddedSpinBox

_PERIOD_COLUMNS = ["وضعیت", "تا تاریخ", "از تاریخ", "ماه", "سال"]
_RUN_COLUMNS = ["پایانِ اجرا", "وضعیت", "نوع", "شمارهٔ اجرا"]
_PAYSLIP_COLUMNS = ["خالصِ پرداختنی", "کسورات", "ناخالص", "نامِ کارمند"]


def _company_id() -> int | None:
    return app_session.current_company.company_id if app_session.current_company else None


class PayrollRunScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._periods: list[payroll_service.PeriodRow] = []
        self._runs: list[engine.RunRow] = []
        self._selected_period_id: int | None = None
        self._selected_run_id: int | None = None
        self._selected_payslip_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_periods_panel(), stretch=2)
        outer.addWidget(self._build_runs_panel(), stretch=2)
        outer.addWidget(self._build_results_panel(), stretch=3)

        self.set_field_help([
            (self.year_field, "سالِ شمسیِ دوره."),
            (self.month_field, "ماهِ شمسیِ دوره (۱ تا ۱۲)."),
        ])

    def _wrap_scrollable(self, content: QWidget) -> QWidget:
        # طبقِ آیتمِ ۱ (اسکرول+فوترِ ثابت): هرکدام از سه ستونِ این صفحه
        # (دوره/اجرا/نتیجه) یک فرمِ مستقلِ کوچک با چند دکمه‌یِ پشتِ‌سرِهم
        # زیرِ جدولِ خودشان‌اند — نه یک فرمِ یکپارچه با یک فوترِ واحد،
        # پس FormScreenBase (یک اسکرول+یک فوتر برایِ کلِ صفحه) این‌جا
        # مناسب نیست؛ هرکدام جداگانه، دقیقاً هم‌الگو با
        # treasury_checks.py، در کارتِ خودش اسکرول می‌شود تا وقتی
        # زیرپنجره کوتاه است، دکمه‌هایِ پایینِ همان ستون هیچ‌وقت گم نشوند.
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

    def _build_periods_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("دوره‌هایِ حقوقی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.periods_table = QTableWidget(0, len(_PERIOD_COLUMNS))
        self.periods_table.setHorizontalHeaderLabels(_PERIOD_COLUMNS)
        self.periods_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.periods_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.periods_table.verticalHeader().setVisible(False)
        self.periods_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.periods_table.cellClicked.connect(self._on_period_clicked)
        layout.addWidget(self.periods_table, stretch=1)

        layout.addWidget(QLabel("سالِ شمسی"))
        self.year_field = ZeroPaddedSpinBox()
        self.year_field.setRange(1390, 1450)
        self.year_field.setValue(1404)
        layout.addWidget(self.year_field)

        layout.addWidget(QLabel("ماهِ شمسی"))
        self.month_field = ZeroPaddedSpinBox()
        self.month_field.setRange(1, 12)
        layout.addWidget(self.month_field)

        layout.addWidget(QLabel("از تاریخ"))
        self.period_start_field = JalaliDateEdit()
        layout.addWidget(self.period_start_field)

        layout.addWidget(QLabel("تا تاریخ"))
        self.period_end_field = JalaliDateEdit()
        layout.addWidget(self.period_end_field)

        self.period_status_label = QLabel("")
        self.period_status_label.setObjectName("statusError")
        self.period_status_label.setWordWrap(True)
        layout.addWidget(self.period_status_label)

        create_period_button = QPushButton("➕")
        create_period_button.setObjectName("primaryIconButton")
        create_period_button.setFixedWidth(40)
        create_period_button.setToolTip("دورهٔ تازه")
        create_period_button.clicked.connect(self._create_period)
        layout.addWidget(create_period_button)
        return self._wrap_scrollable(panel)

    def _build_runs_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("اجراهایِ محاسبه")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.runs_table = QTableWidget(0, len(_RUN_COLUMNS))
        self.runs_table.setHorizontalHeaderLabels(_RUN_COLUMNS)
        self.runs_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.runs_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.runs_table.verticalHeader().setVisible(False)
        self.runs_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.runs_table.cellClicked.connect(self._on_run_clicked)
        layout.addWidget(self.runs_table, stretch=1)

        self.run_status_label = QLabel("")
        self.run_status_label.setObjectName("statusError")
        self.run_status_label.setWordWrap(True)
        layout.addWidget(self.run_status_label)

        run_button = QPushButton("🧮")
        run_button.setObjectName("primaryIconButton")
        run_button.setFixedWidth(40)
        run_button.setToolTip("اجرایِ محاسبه برایِ این دوره")
        run_button.clicked.connect(self._create_and_run)
        layout.addWidget(run_button)

        recalc_button = QPushButton("🔄")
        recalc_button.setObjectName("iconButton")
        recalc_button.setFixedWidth(34)
        recalc_button.setToolTip("بازمحاسبهٔ اجرایِ انتخاب‌شده")
        recalc_button.clicked.connect(self._recalculate_selected)
        layout.addWidget(recalc_button)

        approve_button = QPushButton("✅")
        approve_button.setObjectName("iconButton")
        approve_button.setFixedWidth(34)
        approve_button.setToolTip("تاییدِ نهاییِ اجرا")
        approve_button.clicked.connect(self._approve_selected)
        layout.addWidget(approve_button)

        finalize_button = QPushButton("🔒")
        finalize_button.setObjectName("iconButton")
        finalize_button.setFixedWidth(34)
        finalize_button.setToolTip("قطعی‌سازیِ فیش‌ها (فصلِ ۱۴)")
        finalize_button.clicked.connect(self._finalize_selected)
        layout.addWidget(finalize_button)

        post_journal_button = QPushButton("📄")
        post_journal_button.setObjectName("primaryIconButton")
        post_journal_button.setFixedWidth(40)
        post_journal_button.setToolTip("صدورِ سندِ حسابداری (فصلِ ۱۶)")
        post_journal_button.clicked.connect(self._post_journal_selected)
        layout.addWidget(post_journal_button)
        return self._wrap_scrollable(panel)

    def _build_results_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("نتیجهٔ محاسبه")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.payslips_table = QTableWidget(0, len(_PAYSLIP_COLUMNS))
        self.payslips_table.setHorizontalHeaderLabels(_PAYSLIP_COLUMNS)
        self.payslips_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.payslips_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.payslips_table.verticalHeader().setVisible(False)
        self.payslips_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.payslips_table.cellClicked.connect(self._on_payslip_clicked)
        layout.addWidget(self.payslips_table, stretch=1)

        print_button = QPushButton("🖨️")
        print_button.setObjectName("iconButton")
        print_button.setFixedWidth(34)
        print_button.setToolTip("چاپِ فیشِ انتخاب‌شده")
        print_button.clicked.connect(self._print_selected_payslip)
        layout.addWidget(print_button)

        bank_row = QHBoxLayout()
        self.bank_combo = QComboBox()
        bank_row.addWidget(self.bank_combo, stretch=1)
        bank_batch_button = QPushButton("📁")
        bank_batch_button.setObjectName("iconButton")
        bank_batch_button.setFixedWidth(34)
        bank_batch_button.setToolTip("تولیدِ فایلِ بانکی (فصلِ ۱۵)")
        bank_batch_button.clicked.connect(self._create_bank_batch)
        bank_row.addWidget(bank_batch_button)
        layout.addLayout(bank_row)

        self.bank_status_label = QLabel("")
        self.bank_status_label.setWordWrap(True)
        layout.addWidget(self.bank_status_label)
        return self._wrap_scrollable(panel)

    def refresh(self) -> None:
        self.period_status_label.setText("")
        self.run_status_label.setText("")
        company_id = _company_id()
        if company_id is None:
            return
        self.period_start_field.setDate(datetime.date.today())
        self.period_end_field.setDate(datetime.date.today())
        self.bank_combo.clear()
        for bank in treasury_service.list_banks(company_id, active_only=True):
            self.bank_combo.addItem(bank.name, bank.bank_id)
        self._periods = payroll_service.list_periods(company_id)
        self.periods_table.setRowCount(len(self._periods))
        status_labels = {"OPEN": "باز", "CALCULATED": "محاسبه‌شده", "APPROVED": "تاییدشده", "LOCKED": "قفل‌شده"}
        for row_index, p in enumerate(self._periods):
            values = [
                status_labels.get(p.status, p.status),
                numerals.to_persian_digits(p.period_end_date.isoformat()),
                numerals.to_persian_digits(p.period_start_date.isoformat()),
                numerals.to_persian_digits(str(p.jalali_month)),
                numerals.to_persian_digits(str(p.jalali_year)),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, p.period_id)
                self.periods_table.setItem(row_index, col_index, item)
        self._refresh_runs()

    def _on_period_clicked(self, row: int, _column: int) -> None:
        self._selected_period_id = self.periods_table.item(row, 0).data(Qt.UserRole)
        self._refresh_runs()

    def _refresh_runs(self) -> None:
        self._runs = []
        self.runs_table.setRowCount(0)
        self._clear_results()
        if self._selected_period_id is None:
            return
        self._runs = engine.list_runs(self._selected_period_id)
        status_labels = {
            "DRAFT": "پیش‌نویس", "CALCULATING": "درحالِ محاسبه", "CALCULATED": "محاسبه‌شده",
            "UNDER_REVIEW": "درحالِ بازبینی", "APPROVED": "تاییدشده", "POSTED": "سندخورده", "LOCKED": "قفل‌شده",
        }
        type_labels = {"REGULAR": "معمولی", "CORRECTION": "اصلاحی", "OFF_CYCLE": "بین‌دوره‌ای"}
        self.runs_table.setRowCount(len(self._runs))
        for row_index, r in enumerate(self._runs):
            finished = numerals.to_persian_digits(r.finished_at.strftime("%Y-%m-%d %H:%M")) if r.finished_at else "—"
            values = [finished, status_labels.get(r.status, r.status), type_labels.get(r.run_type, r.run_type), numerals.to_persian_digits(str(r.run_no))]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, r.run_id)
                self.runs_table.setItem(row_index, col_index, item)

    def _on_run_clicked(self, row: int, _column: int) -> None:
        self._selected_run_id = self.runs_table.item(row, 0).data(Qt.UserRole)
        self._show_results(self._selected_run_id)

    def _clear_results(self) -> None:
        self._selected_run_id = None
        self._selected_payslip_id = None
        self.summary_label.setText("")
        self.payslips_table.setRowCount(0)
        self.bank_status_label.setText("")

    def _show_results(self, run_id: int) -> None:
        run = next((r for r in self._runs if r.run_id == run_id), None)
        payslips = engine.list_payslips(run_id)
        total_gross = sum((p.gross_amount for p in payslips), decimal.Decimal(0))
        total_net = sum((p.net_pay for p in payslips), decimal.Decimal(0))
        summary = f"تعدادِ کارمندانِ محاسبه‌شده: {numerals.to_persian_digits(str(len(payslips)))} — " \
                  f"جمعِ ناخالص: {numerals.format_amount(total_gross)} — جمعِ خالص: {numerals.format_amount(total_net)}"
        if run is not None and run.error_log:
            summary += f"\nخطاها: {run.error_log}"
        self.summary_label.setText(summary)

        self.payslips_table.setRowCount(len(payslips))
        for row_index, p in enumerate(payslips):
            values = [
                numerals.format_amount(p.net_pay),
                numerals.format_amount(p.total_deductions),
                numerals.format_amount(p.gross_amount),
                p.employee_name,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, p.payslip_id)
                self.payslips_table.setItem(row_index, col_index, item)

    def _on_payslip_clicked(self, row: int, _column: int) -> None:
        self._selected_payslip_id = self.payslips_table.item(row, 0).data(Qt.UserRole)

    def _create_period(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        try:
            payroll_service.create_period(
                company_id, self.year_field.value(), self.month_field.value(),
                self.period_start_field.date(), self.period_end_field.date(),
            )
        except ValueError as exc:
            theme.set_status_label(self.period_status_label, str(exc), ok=False)
            return
        theme.set_status_label(self.period_status_label, "دوره ساخته شد.", ok=True)
        self.refresh()

    def _create_and_run(self) -> None:
        if self._selected_period_id is None:
            QMessageBox.information(self, "اجرایِ محاسبه", "یک دوره را از فهرست انتخاب کنید.")
            return
        run_id = engine.create_run(self._selected_period_id)
        self._execute_run(run_id)

    def _recalculate_selected(self) -> None:
        if self._selected_run_id is None:
            QMessageBox.information(self, "بازمحاسبه", "یک اجرا را از فهرست انتخاب کنید.")
            return
        self._execute_run(self._selected_run_id)

    def _execute_run(self, run_id: int) -> None:
        try:
            result = engine.run_payroll(run_id)
        except ValueError as exc:
            theme.set_status_label(self.run_status_label, str(exc), ok=False)
            return
        message = f"محاسبه شد — موفق: {numerals.to_persian_digits(str(result.employees_calculated))}، خطا: {numerals.to_persian_digits(str(result.employees_failed))}"
        theme.set_status_label(self.run_status_label, message, ok=(result.employees_failed == 0))
        self._selected_run_id = run_id
        self._refresh_runs()
        self._show_results(run_id)

    def _approve_selected(self) -> None:
        if self._selected_run_id is None:
            QMessageBox.information(self, "تاییدِ اجرا", "یک اجرا را از فهرست انتخاب کنید.")
            return
        try:
            engine.approve_run(self._selected_run_id)
        except ValueError as exc:
            theme.set_status_label(self.run_status_label, str(exc), ok=False)
            return
        theme.set_status_label(self.run_status_label, "اجرا تایید شد.", ok=True)
        self._refresh_runs()

    def _finalize_selected(self) -> None:
        if self._selected_run_id is None:
            QMessageBox.information(self, "قطعی‌سازیِ فیش‌ها", "یک اجرا را از فهرست انتخاب کنید.")
            return
        try:
            result = payslip_service.finalize_payslips_for_run(self._selected_run_id)
        except ValueError as exc:
            theme.set_status_label(self.run_status_label, str(exc), ok=False)
            return
        message = (
            f"فیش‌ها قطعی شدند — تعداد: {numerals.to_persian_digits(str(result.finalized_count))}، "
            f"اقساطِ کسرشده: {numerals.to_persian_digits(str(result.loan_installments_deducted))}، "
            f"اقساطِ موکول‌شده: {numerals.to_persian_digits(str(result.loan_installments_deferred))}"
        )
        theme.set_status_label(self.run_status_label, message, ok=True)

    def _post_journal_selected(self) -> None:
        if self._selected_run_id is None:
            QMessageBox.information(self, "صدورِ سندِ حسابداری", "یک اجرا را از فهرست انتخاب کنید.")
            return
        if not app_session.current_user:
            return
        try:
            result = journal_service.post_run_to_journal(self._selected_run_id, app_session.current_user.user_id)
        except ValueError as exc:
            theme.set_status_label(self.run_status_label, str(exc), ok=False)
            return
        message = f"سند صادر شد — شمارهٔ سند: {numerals.to_persian_digits(str(result.journal_entry_id))}"
        theme.set_status_label(self.run_status_label, message, ok=True)
        self._refresh_runs()

    def _print_selected_payslip(self) -> None:
        if self._selected_payslip_id is None:
            QMessageBox.information(self, "چاپِ فیش", "یک فیش را از فهرست انتخاب کنید.")
            return
        printable = payslip_service.get_printable_payslip(self._selected_payslip_id)
        headers = ["نوع", "شرح", "مبلغ"]
        rows = [["مزایا", l.label, numerals.format_amount(l.amount)] for l in printable.earning_lines]
        rows += [["کسورات", l.label, numerals.format_amount(l.amount)] for l in printable.deduction_lines]
        footer = [
            ["", "ناخالص", numerals.format_amount(printable.gross_amount)],
            ["", "جمعِ کسورات", numerals.format_amount(printable.total_deductions)],
            ["", "خالصِ پرداختنی", numerals.format_amount(printable.net_pay)],
        ]
        title = f"فیشِ حقوقی — {printable.employee_full_name} — {numerals.to_persian_digits(f'{printable.jalali_year}/{printable.jalali_month:02d}')}"
        company_name = app_session.current_company.display_name if app_session.current_company else ""
        report_export.print_report(self, title, headers, rows, footer, company_name=company_name)

    def _create_bank_batch(self) -> None:
        if self._selected_run_id is None:
            QMessageBox.information(self, "فایلِ بانکی", "یک اجرا را از فهرست انتخاب کنید.")
            return
        bank_id = self.bank_combo.currentData()
        if bank_id is None:
            theme.set_status_label(self.bank_status_label, "ابتدا یک بانک تعریف/انتخاب کنید.", ok=False)
            return
        try:
            result = bank_service.create_bank_batch(self._selected_run_id, bank_id)
        except ValueError as exc:
            theme.set_status_label(self.bank_status_label, str(exc), ok=False)
            return
        message = f"batch ساخته شد — شامل: {numerals.to_persian_digits(str(result.included_count))} نفر، جمع: {numerals.format_amount(result.total_amount)}"
        if result.exceptions:
            message += "\nاستثناها: " + "، ".join(f"{e.employee_name} ({e.reason})" for e in result.exceptions)
        theme.set_status_label(self.bank_status_label, message, ok=True)

        path, _filter = QFileDialog.getSaveFileName(self, "ذخیره‌یِ فایلِ بانکی", "bank_batch.csv", "CSV (*.csv)")
        if path:
            csv_text = bank_service.export_bank_batch_csv(result.batch_id)
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(csv_text)
