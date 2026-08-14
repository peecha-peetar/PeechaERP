"""مدیریتِ سال‌های مالی — معادلِ Qt برایِ fiscal_years.py/.kv در Kivy.

طبقِ حسابرسیِ صریح: قبلاً این صفحه فقط بازکردن/بستنِ کلِ سالِ مالی را
نشان می‌داد؛ جدولِ دوره‌هایِ ماهانه (FiscalPeriod) در دیتابیس ساخته
می‌شد ولی هیچ‌جای برنامه دیده/بسته نمی‌شد. حالا با انتخابِ یک سالِ
مالی از فهرست، ۱۲ دوره‌ی ماهانه‌اش هم پایین دیده می‌شود و هرکدام
جداگانه قابلِ‌بستن/بازکردن است (services/journal_entries.py هم این
وضعیت را واقعاً هنگامِ ثبت/ویرایشِ سند چک می‌کند)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals
from peecha import session as app_session
from peecha.services import fiscal_years as fiscal_years_service
from peecha.ui.widgets import FieldHelpMixin, JalaliDateEdit

_YEAR_COLUMNS = ["وضعیت", "تاریخِ پایان", "تاریخِ شروع", "کد"]
_PERIOD_COLUMNS = ["وضعیت", "تاریخِ پایان", "تاریخِ شروع", "دوره"]


class FiscalYearsScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[fiscal_years_service.FiscalYearRow] = []
        self._period_rows: list[fiscal_years_service.FiscalPeriodRow] = []
        self._selected_fiscal_year_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=1)

        self.set_field_help([
            (
                self.date_field,
                "هر تاریخِ دلخواه از سالِ مالی‌ای که می‌خواهید بسازید را وارد کنید. لازم نیست اولِ سال باشد. "
                "برنامه با استفاده از «ماه و روزِ شروعِ سالِ مالی» شرکت، بازه‌ی کاملِ آن سال را خودش حساب می‌کند. "
                "نکته: لازم نیست حتماً از این‌جا سالِ مالی بسازید — با ثبتِ اولین سند در یک تاریخ، اگر سالِ "
                "مالی‌اش وجود نداشته باشد، خودکار ساخته می‌شود (بدونِ دوره‌بندیِ ماهانه).",
            ),
        ])

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("سال‌های مالی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel("روی یک سالِ مالی کلیک کنید تا دوره‌های ماهانه‌اش پایین نمایش داده شود.")
        hint.setObjectName("sectionHint")
        layout.addWidget(hint)

        self.table = QTableWidget(0, len(_YEAR_COLUMNS))
        self.table.setHorizontalHeaderLabels(_YEAR_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_year_row_clicked)
        layout.addWidget(self.table, stretch=1)

        toggle_year_row = QHBoxLayout()
        self.toggle_year_button = QPushButton("📂")
        self.toggle_year_button.setObjectName("iconButton")
        self.toggle_year_button.setFixedWidth(44)
        self.toggle_year_button.setToolTip("بازکردن/بستنِ سالِ مالیِ انتخاب‌شده")
        self.toggle_year_button.setEnabled(False)
        self.toggle_year_button.clicked.connect(self._toggle_selected_year)
        toggle_year_row.addWidget(self.toggle_year_button)
        toggle_year_row.addStretch(1)
        layout.addLayout(toggle_year_row)

        self.periods_title = QLabel("دوره‌های ماهانه")
        self.periods_title.setObjectName("sectionHint")
        layout.addWidget(self.periods_title)

        self.periods_table = QTableWidget(0, len(_PERIOD_COLUMNS))
        self.periods_table.setHorizontalHeaderLabels(_PERIOD_COLUMNS)
        self.periods_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.periods_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.periods_table.verticalHeader().setVisible(False)
        self.periods_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.periods_table.cellClicked.connect(self._on_period_row_clicked)
        layout.addWidget(self.periods_table, stretch=1)

        return panel

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("افزودنِ سالِ مالیِ جدید")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel("یک تاریخِ دلخواهِ شمسی در سالِ موردنظر را وارد کنید — بازه‌ی کامل خودکار محاسبه می‌شود.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.date_field = JalaliDateEdit()
        layout.addWidget(self.date_field)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        create_button = QPushButton("➕")
        create_button.setObjectName("primaryIconButton")
        create_button.setFixedWidth(48)
        create_button.setToolTip("ایجادِ سالِ مالی")
        create_button.clicked.connect(self._create)
        layout.addWidget(create_button)

        layout.addStretch(1)
        return panel

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        self.status_label.setText("")
        company_id = self._company_id()
        self._rows = fiscal_years_service.list_fiscal_years(company_id) if company_id is not None else []
        self.table.setRowCount(len(self._rows))
        for row_index, fy in enumerate(self._rows):
            values = [
                "بسته" if fy.is_closed else "باز",
                numerals.format_jalali_date(fy.end_date),
                numerals.format_jalali_date(fy.start_date),
                numerals.to_persian_digits(fy.code),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, fy.fiscal_year_id)
                self.table.setItem(row_index, col_index, item)

        if self._selected_fiscal_year_id is not None and any(
            r.fiscal_year_id == self._selected_fiscal_year_id for r in self._rows
        ):
            self._load_periods(self._selected_fiscal_year_id)
        else:
            self._selected_fiscal_year_id = None
            self.toggle_year_button.setEnabled(False)
            self.periods_table.setRowCount(0)

    def _selected_year_row(self) -> fiscal_years_service.FiscalYearRow | None:
        return next((r for r in self._rows if r.fiscal_year_id == self._selected_fiscal_year_id), None)

    def _on_year_row_clicked(self, row: int, _column: int) -> None:
        fiscal_year_id = self.table.item(row, 0).data(Qt.UserRole)
        self._selected_fiscal_year_id = fiscal_year_id
        self.toggle_year_button.setEnabled(True)
        self._load_periods(fiscal_year_id)

    def _load_periods(self, fiscal_year_id: int) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        try:
            self._period_rows = fiscal_years_service.list_periods(fiscal_year_id, company_id)
        except ValueError:
            self._period_rows = []
        self.periods_table.setRowCount(len(self._period_rows))
        for row_index, period in enumerate(self._period_rows):
            values = [
                "بسته" if period.is_closed else "باز",
                numerals.format_jalali_date(period.end_date),
                numerals.format_jalali_date(period.start_date),
                numerals.to_persian_digits(str(period.period_no)),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, period.fiscal_period_id)
                self.periods_table.setItem(row_index, col_index, item)
        if not self._period_rows:
            self.periods_title.setText("دوره‌های ماهانه — این سالِ مالی دوره‌بندی ندارد (خودکار از رویِ سند ساخته شده).")
        else:
            self.periods_title.setText("دوره‌های ماهانه")

    def _toggle_selected_year(self) -> None:
        fy = self._selected_year_row()
        company_id = self._company_id()
        if fy is None or company_id is None:
            return
        confirm = QMessageBox.question(
            self,
            "تغییرِ وضعیت",
            f"سالِ مالیِ «{fy.code}» {'باز' if fy.is_closed else 'بسته'} شود؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        fiscal_years_service.set_closed(fy.fiscal_year_id, company_id, not fy.is_closed)
        self.refresh()

    def _on_period_row_clicked(self, row: int, _column: int) -> None:
        fiscal_period_id = self.periods_table.item(row, 0).data(Qt.UserRole)
        period = next((p for p in self._period_rows if p.fiscal_period_id == fiscal_period_id), None)
        company_id = self._company_id()
        if period is None or company_id is None:
            return
        confirm = QMessageBox.question(
            self,
            "تغییرِ وضعیت",
            f"دوره‌ی شماره‌ی {numerals.to_persian_digits(str(period.period_no))} "
            f"{'باز' if period.is_closed else 'بسته'} شود؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        fiscal_years_service.set_period_closed(period.fiscal_period_id, company_id, not period.is_closed)
        if self._selected_fiscal_year_id is not None:
            self._load_periods(self._selected_fiscal_year_id)

    def _create(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            self.status_label.setText("ابتدا یک شرکت را انتخاب کنید.")
            return
        company = app_session.current_company
        on_date = self.date_field.date()
        try:
            fiscal_years_service.create_fiscal_year_for_date(
                company_id, company.fiscal_year_start_month, company.fiscal_year_start_day, on_date
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
