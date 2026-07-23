"""صدور سند — معادلِ Qt برایِ journal_entry.py/.kv در Kivy.

نکته‌ی مهم: در Kivy، زنجیره‌ی Enter/جستجویِ زنده‌ی حساب/تفصیلی به‌خاطرِ
نبودِ Tab-order بومی، کدِ دستیِ زیادی لازم داشت (rtl.py، شرح کاملِ
Kivy-property-observer، و غیره). در Qt این‌کار خودکار است: QComboBox
قابل‌ویرایش+تکمیل‌خودکار جستجویِ زنده می‌دهد و Tab-order بومیِ Qt خودش
حرکتِ منطقیِ بینِ فیلدها را انجام می‌دهد — نیازی به کدِ اضافه نیست.

ساده‌سازیِ عمدیِ این مرحله از مهاجرت: هر ردیف با ارزِ پایه‌ی شرکت ثبت
می‌شود (بدونِ انتخابِ ارز/نرخِ اختصاصیِ هر ردیف — که در Kivy وجود داشت)؛
این می‌تواند در قدمِ بعدیِ مهاجرت اضافه شود."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDateEdit,
    QDoubleSpinBox,
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
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import journal_entries as je_service


def _fill_searchable_combo(combo: QComboBox, options: list[tuple[int, str]]) -> None:
    combo.clear()
    combo.addItem("", None)
    for value, label in options:
        combo.addItem(label, value)
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    completer = QCompleter([label for _v, label in options])
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setFilterMode(Qt.MatchContains)
    combo.setCompleter(completer)


class _LineRowWidget(QWidget):
    def __init__(self, screen: "JournalEntryScreen") -> None:
        super().__init__()
        self._screen = screen
        self._dimension_combos: dict[int, QComboBox] = {}
        self._person_combo: QComboBox | None = None
        self._person_group_ids: list[int] = []
        self.account_id: int | None = None

        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(6)

        top_row = QHBoxLayout()
        self.remove_button = QPushButton("حذفِ ردیف")
        self.remove_button.setObjectName("dangerButton")
        self.remove_button.clicked.connect(lambda: screen.remove_line(self))
        top_row.addWidget(self.remove_button)
        top_row.addStretch(1)
        outer.addLayout(top_row)

        grid = QGridLayout()
        grid.setSpacing(6)

        grid.addWidget(QLabel("حساب"), 0, 0)
        self.account_combo = QComboBox()
        _fill_searchable_combo(self.account_combo, screen.account_options)
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)
        grid.addWidget(self.account_combo, 0, 1, 1, 3)

        grid.addWidget(QLabel("شرحِ ردیف"), 1, 0)
        self.description_field = QLineEdit()
        grid.addWidget(self.description_field, 1, 1, 1, 3)

        grid.addWidget(QLabel("بدهکار"), 2, 0)
        self.debit_field = QDoubleSpinBox()
        self.debit_field.setRange(0, 10**12)
        self.debit_field.setGroupSeparatorShown(True)
        self.debit_field.setDecimals(0)
        self.debit_field.valueChanged.connect(self._on_debit_changed)
        grid.addWidget(self.debit_field, 2, 1)

        grid.addWidget(QLabel("بستانکار"), 2, 2)
        self.credit_field = QDoubleSpinBox()
        self.credit_field.setRange(0, 10**12)
        self.credit_field.setGroupSeparatorShown(True)
        self.credit_field.setDecimals(0)
        self.credit_field.valueChanged.connect(self._on_credit_changed)
        grid.addWidget(self.credit_field, 2, 3)

        outer.addLayout(grid)

        self.dimensions_container = QVBoxLayout()
        outer.addLayout(self.dimensions_container)

        self._render_dimension_fields()

    def _on_debit_changed(self, value: float) -> None:
        if value:
            self.credit_field.blockSignals(True)
            self.credit_field.setValue(0)
            self.credit_field.blockSignals(False)
        self._screen.update_balance()

    def _on_credit_changed(self, value: float) -> None:
        if value:
            self.debit_field.blockSignals(True)
            self.debit_field.setValue(0)
            self.debit_field.blockSignals(False)
        self._screen.update_balance()

    def _on_account_changed(self, _index: int) -> None:
        self.account_id = self.account_combo.currentData()
        self._render_dimension_fields()

    def _render_dimension_fields(self) -> None:
        while self.dimensions_container.count():
            child = self.dimensions_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._dimension_combos = {}
        self._person_combo = None

        if self.account_id is None:
            return

        self._person_group_ids = [
            g.person_group_id for g in dimensions_service.get_required_person_groups_for_account(self.account_id)
        ]
        company_id = self._screen.company_id
        persons = dimensions_service.list_active_persons(company_id)
        if self._person_group_ids:
            persons = [p for p in persons if p.person_group_id in self._person_group_ids]

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(QLabel("تفصیلی"))
        person_combo = QComboBox()
        _fill_searchable_combo(person_combo, [(p.detail_account_id, f"{p.full_code} — {p.name or ''}") for p in persons])
        row_layout.addWidget(person_combo)
        self.dimensions_container.addWidget(row)
        self._person_combo = person_combo

        for required_dim in dimensions_service.get_required_dimensions_for_account(self.account_id):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(QLabel(required_dim.code))
            combo = QComboBox()
            _fill_searchable_combo(
                combo, [(d.detail_account_id, f"{d.full_code} — {d.name or ''}") for d in required_dim.detail_accounts]
            )
            row_layout.addWidget(combo)
            self.dimensions_container.addWidget(row)
            self._dimension_combos[required_dim.dimension_type_id] = combo

    def collect_details(self) -> dict[int, int]:
        details: dict[int, int] = {}
        if self._person_combo is not None:
            person_detail_id = self._person_combo.currentData()
            if person_detail_id is not None:
                details[dimensions_service.get_person_dimension_type_id(self._screen.company_id)] = person_detail_id
        for dimension_type_id, combo in self._dimension_combos.items():
            detail_id = combo.currentData()
            if detail_id is not None:
                details[dimension_type_id] = detail_id
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
        )

    def load_from(self, line: je_service.LineInput, account_label: str) -> None:
        index = self.account_combo.findData(line.account_id)
        if index < 0:
            self.account_combo.addItem(account_label, line.account_id)
            index = self.account_combo.count() - 1
        self.account_combo.setCurrentIndex(index)
        self.account_id = line.account_id
        self._render_dimension_fields()
        self.description_field.setText(line.description or "")
        self.debit_field.setValue(float(line.debit))
        self.credit_field.setValue(float(line.credit))
        for dimension_type_id, detail_account_id in line.details.items():
            combo = self._dimension_combos.get(dimension_type_id)
            if combo is not None:
                idx = combo.findData(detail_account_id)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            elif self._person_combo is not None:
                idx = self._person_combo.findData(detail_account_id)
                if idx >= 0:
                    self._person_combo.setCurrentIndex(idx)


class JournalEntryScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.company_id: int | None = None
        self.account_options: list[tuple[int, str]] = []
        self._line_rows: list[_LineRowWidget] = []
        self._editing_journal_entry_id: int | None = None

        outer = QVBoxLayout(self)
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

        header_layout.addWidget(QLabel("تاریخِ سند"), 1, 0)
        self.date_field = QDateEdit()
        self.date_field.setCalendarPopup(True)
        self.date_field.setDate(datetime.date.today())
        header_layout.addWidget(self.date_field, 1, 1)

        header_layout.addWidget(QLabel("شماره‌ی عطف"), 1, 2)
        self.alt_number_field = QLineEdit()
        header_layout.addWidget(self.alt_number_field, 1, 3)

        header_layout.addWidget(QLabel("شرحِ سند"), 2, 0)
        self.description_field = QLineEdit()
        header_layout.addWidget(self.description_field, 2, 1, 1, 2)

        self.draft_checkbox = QCheckBox("پیش‌نویس (نامتعادل هم قابلِ‌ذخیره)")
        header_layout.addWidget(self.draft_checkbox, 2, 3)

        outer.addWidget(header_card)

        add_line_button = QPushButton("+ افزودنِ ردیف")
        add_line_button.setObjectName("flatButton")
        add_line_button.clicked.connect(lambda: self.add_line())
        outer.addWidget(add_line_button)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.lines_container_widget = QWidget()
        self.lines_container = QVBoxLayout(self.lines_container_widget)
        self.lines_container.addStretch(1)
        scroll.setWidget(self.lines_container_widget)
        outer.addWidget(scroll, stretch=1)

        footer = QHBoxLayout()
        self.balance_label = QLabel("")
        footer.addWidget(self.balance_label)
        footer.addStretch(1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        footer.addWidget(self.status_label)

        save_button = QPushButton("ثبتِ سند")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._save)
        footer.addWidget(save_button)

        new_button = QPushButton("سندِ جدید")
        new_button.setObjectName("flatButton")
        new_button.clicked.connect(lambda: self._reset_form())
        footer.addWidget(new_button)

        outer.addLayout(footer)

    def refresh(self) -> None:
        self.company_id = session.current_company.company_id if session.current_company else None
        if self.company_id is None:
            return
        accounts = coa_service.list_postable_accounts(self.company_id)
        self.account_options = [(a.account_id, f"{a.full_code} — {a.name}") for a in accounts]
        if not self._line_rows:
            self._reset_form()

    def _reset_form(self) -> None:
        self._editing_journal_entry_id = None
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

    def add_line(self) -> _LineRowWidget:
        row = _LineRowWidget(self)
        self._line_rows.append(row)
        self.lines_container.insertWidget(self.lines_container.count() - 1, row)
        return row

    def remove_line(self, row: _LineRowWidget, *, force: bool = False) -> None:
        if not force and len(self._line_rows) <= 2:
            return
        self._line_rows.remove(row)
        self.lines_container.removeWidget(row)
        row.deleteLater()
        self.update_balance()

    def update_balance(self) -> None:
        total_debit = sum((decimal.Decimal(str(r.debit_field.value())) for r in self._line_rows), decimal.Decimal(0))
        total_credit = sum((decimal.Decimal(str(r.credit_field.value())) for r in self._line_rows), decimal.Decimal(0))
        if total_debit == total_credit and total_debit > 0:
            self.balance_label.setText(f"تراز — بدهکار: {total_debit} | بستانکار: {total_credit}")
            self.balance_label.setObjectName("statusOk")
        else:
            self.balance_label.setText(f"غیرِ تراز — بدهکار: {total_debit} | بستانکار: {total_credit}")
            self.balance_label.setObjectName("statusError")
        self.balance_label.setStyleSheet("")

    def _save(self) -> None:
        if self.company_id is None or session.current_user is None:
            self.status_label.setText("ابتدا یک شرکت را انتخاب کنید.")
            return

        lines = [ln for row in self._line_rows if (ln := row.to_line_input()) is not None]
        qdate = self.date_field.date()
        document_date = datetime.date(qdate.year(), qdate.month(), qdate.day())
        description = self.description_field.text().strip()
        alt_number = self.alt_number_field.text().strip()
        as_draft = self.draft_checkbox.isChecked()

        try:
            if self._editing_journal_entry_id is not None:
                je_service.update_journal_entry(
                    self._editing_journal_entry_id, self.company_id, document_date, description, lines,
                    changed_by_user_id=session.current_user.user_id, alternative_number=alt_number, as_draft=as_draft,
                )
            else:
                je_service.create_journal_entry(
                    self.company_id, session.current_user.user_id, document_date, description, lines,
                    alternative_number=alt_number, as_draft=as_draft,
                )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return

        self.status_label.setText("")
        self._reset_form()

    def edit_journal_entry(self, journal_entry_id: int) -> None:
        if self.company_id is None:
            return
        self._editing_journal_entry_id = journal_entry_id
        self.form_title.setText(f"ویرایشِ سند")
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
