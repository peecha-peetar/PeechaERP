"""صدور سند — معادلِ Qt برایِ journal_entry.py/.kv در Kivy.

طبقِ بازخوردِ صریح: ردیف‌هایِ سند به‌جایِ کارتِ عمودیِ قبلی، در یک جدولِ
واقعی (QTableWidget) نمایش داده می‌شوند — دقیقاً مشابهِ نرم‌افزارهایِ
حسابداریِ رایج (هر ردیف = یک سطرِ افقیِ حساب/تفصیلی/شرح/بدهکار/بستانکار).

نکته: در Kivy، زنجیره‌ی Enter/جستجویِ زنده‌ی حساب/تفصیلی به‌خاطرِ نبودِ
Tab-order بومی، کدِ دستیِ زیادی لازم داشت. در Qt این‌کار خودکار است:
QComboBox قابل‌ویرایش+تکمیل‌خودکار جستجویِ زنده می‌دهد و Tab-order بومیِ Qt
خودش حرکتِ منطقیِ بینِ فیلدها را انجام می‌دهد.

ساده‌سازیِ عمدیِ این مرحله از مهاجرت: هر ردیف با ارزِ پایه‌ی شرکت ثبت
می‌شود (بدونِ انتخابِ ارز/نرخِ اختصاصیِ هر ردیف)؛ همچنین ستونِ «حساب» کد و
نامِ حساب را در یک فیلدِ جستجوپذیرِ واحد نشان می‌دهد (به‌جایِ دو ستونِ
جداگانه‌ی کد/عنوان)."""

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
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import journal_entries as je_service

_COL_ROW_NO = 0
_COL_ACCOUNT = 1
_COL_PERSON = 2
_COL_DESC = 3
_COL_DEBIT = 4
_COL_CREDIT = 5
_COL_DIMENSIONS = 6
_COL_REMOVE = 7
_COLUMN_LABELS = ["ردیف", "حساب", "تفصیلی", "شرحِ ردیف", "بدهکار", "بستانکار", "ابعاد", ""]


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
            combo = QComboBox()
            _fill_searchable_combo(
                combo, [(d.detail_account_id, f"{d.full_code} — {d.name or ''}") for d in dim.detail_accounts]
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
        self._required_dimensions: list[dimensions_service.RequiredDimension] = []
        self._extra_dimension_values: dict[int, int] = {}

        self.account_combo = QComboBox()
        _fill_searchable_combo(self.account_combo, screen.account_options)
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)

        self.person_combo = QComboBox()
        _fill_searchable_combo(self.person_combo, [])

        self.description_field = QLineEdit()

        self.debit_field = QDoubleSpinBox()
        self.debit_field.setRange(0, 10**12)
        self.debit_field.setGroupSeparatorShown(True)
        self.debit_field.setDecimals(0)
        self.debit_field.valueChanged.connect(self._on_debit_changed)

        self.credit_field = QDoubleSpinBox()
        self.credit_field.setRange(0, 10**12)
        self.credit_field.setGroupSeparatorShown(True)
        self.credit_field.setDecimals(0)
        self.credit_field.valueChanged.connect(self._on_credit_changed)

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
        self._screen.update_balance()

    def _on_credit_changed(self, value: float) -> None:
        if value:
            self.debit_field.blockSignals(True)
            self.debit_field.setValue(0)
            self.debit_field.blockSignals(False)
        self._screen.update_balance()

    def _on_account_changed(self, _index: int) -> None:
        self.account_id = self.account_combo.currentData()
        self._refresh_dimension_ui()

    def _refresh_dimension_ui(self) -> None:
        if self.account_id is None:
            _fill_searchable_combo(self.person_combo, [])
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
        _fill_searchable_combo(self.person_combo, [(p.detail_account_id, f"{p.full_code} — {p.name or ''}") for p in persons])

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
        )

    def load_from(self, line: je_service.LineInput, account_label: str) -> None:
        index = self.account_combo.findData(line.account_id)
        if index < 0:
            self.account_combo.addItem(account_label, line.account_id)
            index = self.account_combo.count() - 1
        self.account_combo.setCurrentIndex(index)
        self.account_id = line.account_id
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
        self._line_rows: list[_LineRow] = []
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
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_COL_ROW_NO, QHeaderView.Fixed)
        header.setSectionResizeMode(_COL_ACCOUNT, QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_PERSON, QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_DESC, QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_DEBIT, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_CREDIT, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_DIMENSIONS, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_REMOVE, QHeaderView.Fixed)
        self.table.setColumnWidth(_COL_ROW_NO, 44)
        self.table.setColumnWidth(_COL_REMOVE, 40)
        table_card_layout.addWidget(self.table)
        outer.addWidget(table_card, stretch=1)

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

    def add_line(self) -> _LineRow:
        row = _LineRow(self, self.table)
        self.table.insertRow(self.table.rowCount())
        row.install(self.table.rowCount() - 1)
        # نکته: QTableWidget.setCellWidget همیشه ویجت را show() می‌کند —
        # حتیِ اگر قبل از نصب صریحاً hide شده باشد — پس مخفی‌کردنِ اولیه‌ی
        # دکمه‌ی «ابعاد» باید *بعدِ* نصب دوباره اعمال شود.
        row._refresh_dimension_ui()
        self._line_rows.append(row)
        self._renumber_rows()
        return row

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
        self.form_title.setText("ویرایشِ سند")
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
