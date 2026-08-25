"""مغایرتِ بانکی/حساب از اکسل — طبقِ آیتمِ ۵ (درخواستِ صریح: «مغایرتِ
بانکی/حساب از اکسل، فقط نمایشِ اختلاف‌ها») + پاسخِ تاییدشده‌یِ کاربر
(«فقط نمایشِ اختلاف‌ها، پیشنهادی»): کاربر یک حسابِ کدینگی (معمولاً بانک/
صندوق) و بازه‌یِ تاریخ را انتخاب می‌کند، صورت‌حسابِ اکسلِ همان حساب را
ایمپورت می‌کند، و فقط ردیف‌هایی که در یک طرف هستند و طرفِ مقابل ندارند
نمایش داده می‌شوند — بدونِ هیچ مکانیزمِ تطبیق‌دادن/رفع‌مغایرتِ دستی."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFileDialog,
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

from peecha import numerals, session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import currencies as currencies_service
from peecha.services import reconciliation as reconciliation_service
from peecha.ui.excel_import import ExcelColumnMappingDialog, read_excel_rows
from peecha.ui.screens.journal_entry import _fill_options, _make_searchable_combo
from peecha.ui.widgets import FieldHelpMixin, JalaliDateEdit, wrap_scrollable

_TARGET_FIELDS: list[tuple[str, str, bool]] = [
    ("date", "تاریخ", False),
    ("description", "شرح", False),
    ("debit", "بدهکار (واریز به حساب)", False),
    ("credit", "بستانکار (برداشت از حساب)", False),
]
_GUESS_KEYWORDS: dict[str, list[str]] = {
    "date": ["تاریخ"],
    "description": ["شرح", "توضیح", "بابت"],
    "debit": ["بدهکار", "واریز"],
    "credit": ["بستانکار", "برداشت"],
}

_COLUMNS = ["منبع", "تاریخ", "مرجع", "شرح", "بدهکار", "بستانکار"]
_SOURCE_LABELS = {"LEDGER": "فقط در دفترِ حساب", "STATEMENT": "فقط در صورت‌حسابِ اکسل"}


class BankReconciliationScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._currency_decimal_places = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(16)

        title_label = QLabel("مغایرتِ بانکی/حساب از اکسل")
        title_label.setObjectName("pageTitle")
        layout.addWidget(title_label)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("حساب:"))
        self.account_combo = _make_searchable_combo([])
        filter_row.addWidget(self.account_combo, stretch=1)
        filter_row.addWidget(QLabel("از تاریخ:"))
        self.date_from_field = JalaliDateEdit()
        filter_row.addWidget(self.date_from_field)
        filter_row.addWidget(QLabel("تا تاریخ:"))
        self.date_to_field = JalaliDateEdit()
        filter_row.addWidget(self.date_to_field)
        import_button = QPushButton("📥 ایمپورتِ صورت‌حساب از اکسل")
        import_button.setObjectName("primaryButton")
        import_button.clicked.connect(self._on_import_excel)
        filter_row.addWidget(import_button)
        layout.addLayout(filter_row)

        self.summary_label = QLabel("یک حساب و بازه‌یِ تاریخ را انتخاب کنید، سپس صورت‌حسابِ بانک را از اکسل ایمپورت کنید.")
        self.summary_label.setObjectName("sectionHint")
        layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

        outer.addWidget(wrap_scrollable(panel))

        self.set_field_help([
            (
                self.account_combo,
                "حسابِ کدینگی (معمولاً بانک یا صندوق) که صورت‌حسابش می‌خواهید مقایسه شود.",
            ),
            (
                import_button,
                "فایلِ اکسلِ صورت‌حسابِ بانک را انتخاب کنید؛ فقط ردیف‌هایی که در یک طرف هستند و طرفِ مقابل ندارند نشان داده می‌شوند — هیچ ردیفی تغییر/تایید نمی‌شود.",
            ),
        ])

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        current_account_id = self.account_combo.currentData()
        options: list[tuple[int, str]] = []
        if company_id is not None:
            currency = next(
                (c for c in currencies_service.list_all_currencies() if c.currency_id == session.current_company.base_currency_id),
                None,
            )
            self._currency_decimal_places = currency.decimal_places if currency else 0
            options = [
                (a.account_id, f"{a.full_code} — {a.name}")
                for a in coa_service.list_accounts(company_id)
                if a.is_postable
            ]
        _fill_options(self.account_combo, options)
        if current_account_id is not None:
            index = self.account_combo.findData(current_account_id)
            if index >= 0:
                self.account_combo.setCurrentIndex(index)
        self.table.setRowCount(0)
        self.summary_label.setText("یک حساب و بازه‌یِ تاریخ را انتخاب کنید، سپس صورت‌حسابِ بانک را از اکسل ایمپورت کنید.")

    def _fmt(self, value) -> str:
        return numerals.format_money(value, self._currency_decimal_places, None) if value else ""

    def _on_import_excel(self) -> None:
        company_id = self._company_id()
        account_id = self.account_combo.currentData()
        if company_id is None or account_id is None:
            QMessageBox.warning(self, "خطا", "ابتدا یک حساب را انتخاب کنید.")
            return
        date_from = self.date_from_field.date()
        date_to = self.date_to_field.date()
        if date_from > date_to:
            QMessageBox.warning(self, "خطا", "بازه‌یِ تاریخ نامعتبر است.")
            return

        path, _filter = QFileDialog.getOpenFileName(self, "انتخابِ فایلِ صورت‌حسابِ اکسل", "", "Excel Files (*.xlsx)")
        if not path:
            return
        rows = read_excel_rows(self, path)
        if rows is None:
            return

        dialog = ExcelColumnMappingDialog(
            _TARGET_FIELDS, _GUESS_KEYWORDS, rows[0], self, title="ایمپورتِ صورت‌حسابِ بانک — تناظرِ ستون‌ها"
        )
        if dialog.exec() != ExcelColumnMappingDialog.Accepted:
            return
        mapping = dialog.mapping()
        data_rows = rows[1:] if dialog.skip_header_row() else rows

        statement_rows: list[reconciliation_service.StatementRow] = []
        errors: list[str] = []
        for row_no, row in enumerate(data_rows, start=2 if dialog.skip_header_row() else 1):
            date_col = mapping.get("date")
            desc_col = mapping.get("description")
            debit_col = mapping.get("debit")
            credit_col = mapping.get("credit")
            try:
                debit = numerals.parse_decimal(str(row[debit_col])) if debit_col is not None and row[debit_col] is not None else numerals.parse_decimal("0")
                credit = numerals.parse_decimal(str(row[credit_col])) if credit_col is not None and row[credit_col] is not None else numerals.parse_decimal("0")
            except ValueError as exc:
                errors.append(f"ردیفِ {row_no}: {exc}")
                continue
            if debit == 0 and credit == 0:
                continue
            date_value = None
            if date_col is not None and row[date_col] is not None:
                raw_date = row[date_col]
                try:
                    date_value = raw_date.date() if hasattr(raw_date, "date") and not isinstance(raw_date, str) else raw_date
                    if not hasattr(date_value, "year"):
                        date_value = numerals.parse_jalali_date(str(raw_date))
                except ValueError as exc:
                    errors.append(f"ردیفِ {row_no}: {exc}")
                    continue
            description = str(row[desc_col]).strip() if desc_col is not None and row[desc_col] is not None else ""
            statement_rows.append(
                reconciliation_service.StatementRow(row_no=row_no, date=date_value, description=description, debit=debit, credit=credit)
            )

        if errors:
            QMessageBox.warning(self, "خطاهایِ ایمپورت", "\n".join(errors[:20]))

        differences = reconciliation_service.compute_differences(company_id, account_id, date_from, date_to, statement_rows)
        self._show_differences(differences)

    def _show_differences(self, differences: list[reconciliation_service.DifferenceRow]) -> None:
        self.table.setRowCount(len(differences))
        for row_index, d in enumerate(differences):
            values = [
                _SOURCE_LABELS.get(d.source, d.source),
                numerals.format_jalali_date(d.date) if d.date else "—",
                d.reference,
                d.description or "—",
                self._fmt(d.debit),
                self._fmt(d.credit),
            ]
            for col_index, value in enumerate(values):
                self.table.setItem(row_index, col_index, QTableWidgetItem(value))
        if not differences:
            self.summary_label.setText("هیچ اختلافی یافت نشد — همه‌یِ ردیف‌هایِ دفترِ حساب و صورت‌حسابِ اکسل تطبیق داده شدند.")
        else:
            ledger_only = sum(1 for d in differences if d.source == "LEDGER")
            statement_only = sum(1 for d in differences if d.source == "STATEMENT")
            self.summary_label.setText(
                f"{numerals.to_persian_digits(str(len(differences)))} اختلاف یافت شد — "
                f"{numerals.to_persian_digits(str(ledger_only))} فقط در دفترِ حساب، "
                f"{numerals.to_persian_digits(str(statement_only))} فقط در صورت‌حسابِ اکسل."
            )
