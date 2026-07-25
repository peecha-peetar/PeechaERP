"""مدیریتِ سال‌های مالی — معادلِ Qt برایِ fiscal_years.py/.kv در Kivy."""

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

_COLUMNS = ["وضعیت", "تاریخِ پایان", "تاریخِ شروع", "کد"]


class FiscalYearsScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[fiscal_years_service.FiscalYearRow] = []

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
                "مالی‌اش وجود نداشته باشد، خودکار ساخته می‌شود.",
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

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)
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

        create_button = QPushButton("ایجادِ سالِ مالی")
        create_button.setObjectName("primaryButton")
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

    def _on_row_clicked(self, row: int, _column: int) -> None:
        fiscal_year_id = self.table.item(row, 0).data(Qt.UserRole)
        fy = next((r for r in self._rows if r.fiscal_year_id == fiscal_year_id), None)
        if fy is None:
            return
        company_id = self._company_id()
        if company_id is None:
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
