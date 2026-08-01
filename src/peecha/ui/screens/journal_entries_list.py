"""فهرستِ اسنادِ حسابداری — معادلِ Qt برایِ journal_entries_list.py/.kv در Kivy.

طبقِ بازخوردِ صریح: ترتیبِ ستون‌ها (از راست) ردیف/شماره/تاریخِ شمسی/شرح/
مبلغ (با جداکننده‌ی سه‌رقمی)/وضعیت/کاربرِ صادرکننده/نامِ شرکت/سالِ مالی است؛
همچنین امکانِ «کپیِ مشابه» و «کپیِ معکوس» (جابه‌جاییِ بدهکار/بستانکارِ هر
ردیف) از رویِ سندِ انتخاب‌شده اضافه شده — هر دو فرمِ صدورِ سند را با اقلامِ
همان سند (به‌عنوانِ سندی کاملاً تازه، نه ویرایشِ همان سند) باز می‌کنند."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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

from peecha import numerals, session
from peecha.services import cartable as cartable_service
from peecha.services import currencies as currencies_service
from peecha.services import journal_entries as je_service
from peecha.ui.widgets import FieldHelpMixin

_STATUS_LABELS = {
    "DRAFT": "پیش‌نویس",
    "TEMPORARY": "موقت",
    "PERMANENT": "دائم",
    "REVERSED": "برگشت‌خورده",
    "CANCELLED": "ابطال‌شده",
}

_COLUMNS = ["ردیف", "شماره", "تاریخ", "شرح", "مبلغِ کل", "وضعیت", "کاربرِ صادرکننده", "نامِ شرکت", "سالِ مالی"]
_COL_ROW_NO = 0
_COL_NUMBER = 1
_COL_DATE = 2
_COL_DESC = 3
_COL_AMOUNT = 4
_COL_STATUS = 5
_COL_USER = 6
_COL_COMPANY = 7
_COL_FISCAL_YEAR = 8


class JournalEntriesListScreen(FieldHelpMixin, QWidget):
    def __init__(self, main_window) -> None:
        super().__init__()
        self._main_window = main_window
        self._entries: list[je_service.JournalEntrySummary] = []
        self._currency_decimal_places = 0
        self._currency_symbol: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("اسنادِ حسابداری")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        new_button = QPushButton("+ سندِ جدید")
        new_button.setObjectName("primaryButton")
        new_button.clicked.connect(self._open_new_entry)
        header.addWidget(new_button)
        layout.addLayout(header)

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("جستجو در شماره‌ی سند، شرح یا شماره‌ی عطف")
        self.search_field.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search_field)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(_COL_DESC, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self.table, stretch=1)

        buttons = QHBoxLayout()
        copy_button = QPushButton("کپیِ سندِ انتخاب‌شده (مشابه)")
        copy_button.setObjectName("flatButton")
        copy_button.clicked.connect(lambda: self._copy_selected(reverse=False))
        buttons.addWidget(copy_button)

        reverse_copy_button = QPushButton("کپیِ معکوسِ سندِ انتخاب‌شده")
        reverse_copy_button.setObjectName("flatButton")
        reverse_copy_button.clicked.connect(lambda: self._copy_selected(reverse=True))
        buttons.addWidget(reverse_copy_button)

        approve_button = QPushButton("تاییدِ سند (ارتقا به دائم)")
        approve_button.setObjectName("flatButton")
        approve_button.clicked.connect(self._approve_selected)
        buttons.addWidget(approve_button)

        reverse_button = QPushButton("برگشت‌زدنِ سندِ دائم")
        reverse_button.setObjectName("flatButton")
        reverse_button.clicked.connect(self._reverse_selected)
        buttons.addWidget(reverse_button)

        buttons.addStretch(1)

        delete_button = QPushButton("حذفِ سندِ انتخاب‌شده (موقت/پیش‌نویس)")
        delete_button.setObjectName("dangerButton")
        delete_button.clicked.connect(self._delete_selected)
        buttons.addWidget(delete_button)

        layout.addLayout(buttons)

        self.set_field_help([
            (
                self.search_field,
                "جستجو در شماره‌ی سند، شرح یا شماره‌ی عطف. برایِ بازکردنِ خودِ سند، رویِ ردیفش دابل‌کلیک کنید.",
            ),
        ])

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        self._entries = je_service.list_journal_entries(company_id) if company_id is not None else []

        base_currency_id = session.current_company.base_currency_id if session.current_company else None
        currency = next((c for c in currencies_service.list_all_currencies() if c.currency_id == base_currency_id), None)
        self._currency_decimal_places = currency.decimal_places if currency else 0
        self._currency_symbol = currency.symbol if currency else None

        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self.search_field.text().strip()
        filtered = [
            e for e in self._entries
            if not query
            or query in str(e.temporary_no)
            or query in (e.description or "")
            or query in (e.alternative_number or "")
        ]
        self.table.setRowCount(len(filtered))
        for row_index, e in enumerate(filtered):
            number_text = (
                f"دائم: {numerals.to_persian_digits(str(e.permanent_no))}"
                if e.permanent_no is not None
                else f"موقت: {numerals.to_persian_digits(str(e.temporary_no))}"
            )
            values = [
                str(row_index + 1),
                number_text,
                numerals.format_jalali_date(e.document_date),
                e.description or "—",
                numerals.format_money(e.total_amount, self._currency_decimal_places, self._currency_symbol),
                _STATUS_LABELS.get(e.status_code, e.status_code),
                e.created_by_name or "—",
                e.company_name or "—",
                e.fiscal_year_code or "—",
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, e.journal_entry_id)
                self.table.setItem(row_index, col_index, item)

    def _open_new_entry(self) -> None:
        self._main_window.open_screen("GL_JE", then=lambda screen: screen._reset_form())

    def _on_row_double_clicked(self, row: int, _column: int) -> None:
        journal_entry_id = self.table.item(row, 0).data(Qt.UserRole)
        self._main_window.open_screen("GL_JE", then=lambda screen: screen.edit_journal_entry(journal_entry_id))

    def _copy_selected(self, *, reverse: bool) -> None:
        selected = self.table.selectedItems()
        if not selected:
            return
        journal_entry_id = selected[0].data(Qt.UserRole)
        self._main_window.open_screen(
            "GL_JE", then=lambda screen: screen.copy_from_journal_entry(journal_entry_id, reverse=reverse)
        )

    def _delete_selected(self) -> None:
        selected = self.table.selectedItems()
        if not selected:
            return
        journal_entry_id = selected[0].data(Qt.UserRole)
        company_id = self._company_id()
        if company_id is None:
            return
        confirm = QMessageBox.question(
            self, "حذفِ سند", "این سند حذف شود؟ این کار قابلِ بازگشت نیست.", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            je_service.delete_journal_entry(journal_entry_id, company_id, session.current_user.user_id if session.current_user else None)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _approve_selected(self) -> None:
        selected = self.table.selectedItems()
        if not selected:
            return
        journal_entry_id = selected[0].data(Qt.UserRole)
        company_id = self._company_id()
        if company_id is None or session.current_user is None:
            return

        if cartable_service.has_active_workflow(company_id, "journal_entry"):
            confirm = QMessageBox.question(
                self,
                "ارسالِ سند برایِ تایید",
                "این سند برایِ زنجیره‌ی تاییدِ کارتابل ارسال شود؟",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return
            entry = next((e for e in self._entries if e.journal_entry_id == journal_entry_id), None)
            amount = entry.total_amount if entry is not None else None
            cartable_service.submit_for_approval(
                company_id, "journal_entry", journal_entry_id, "CREATE", session.current_user.user_id, amount=amount
            )
            QMessageBox.information(
                self, "ارسال شد", "سند برایِ تاییدِ کارتابل ارسال شد؛ بعدِ تاییدِ همه‌ی مراحل، خودکار دائم می‌شود."
            )
            self.refresh()
            return

        confirm = QMessageBox.question(
            self,
            "تاییدِ سند",
            "این سند تایید و به دائم ارتقا یابد؟ بعدِ تایید، سند دیگر قابلِ ویرایش/حذف نیست و شماره‌ی دائمش تغییرناپذیر می‌شود.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            permanent_no = je_service.approve_journal_entry(journal_entry_id, company_id, session.current_user.user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        QMessageBox.information(self, "تایید شد", f"سند با شماره‌ی دائمِ {numerals.to_persian_digits(str(permanent_no))} تایید شد.")
        self.refresh()

    def _reverse_selected(self) -> None:
        selected = self.table.selectedItems()
        if not selected:
            return
        journal_entry_id = selected[0].data(Qt.UserRole)
        company_id = self._company_id()
        if company_id is None or session.current_user is None:
            return
        confirm = QMessageBox.question(
            self,
            "برگشت‌زدنِ سند",
            "یک سندِ تازه با بدهکار/بستانکارِ معکوسِ این سند ساخته می‌شود تا اثرش را خنثی کند. ادامه می‌دهید؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            je_service.reverse_journal_entry(journal_entry_id, company_id, session.current_user.user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()
