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
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.services import cartable as cartable_service
from peecha.services import companies as companies_service
from peecha.services import company_transfer
from peecha.services import currencies as currencies_service
from peecha.services import journal_entries as je_service
from peecha.ui.widgets import FieldHelpMixin, JalaliDateEdit

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


class _TransferDialog(QDialog):
    """طبقِ آیتمِ ۳ («ارسال/انتقال/کپیِ سند بینِ شرکت‌ها، هر دو حالت،
    انتخابی + کپیِ خودکارِ حساب‌هایِ نبود») — پیش‌نمایشِ حساب‌ها/تفصیلی‌هایِ
    ناموجود در شرکتِ مقصد قبل از اجرا نشان داده می‌شود؛ اگر تفصیلیِ شخصی
    (مشتری/تامین‌کننده/پرسنل) ناموجود باشد، دکمه‌ی تایید غیرفعال می‌ماند
    (باید دستی در مقصد تعریف شود)."""

    def __init__(self, parent, source_company_id: int, journal_entry_ids: list[int], user_id: int) -> None:
        super().__init__(parent)
        self.setWindowTitle("ارسال/کپیِ سند به شرکتِ دیگر")
        self.resize(640, 480)
        self._source_company_id = source_company_id
        self._journal_entry_ids = journal_entry_ids
        self._user_id = user_id
        self._companies = [
            c for c in companies_service.list_companies_for_user(user_id) if c.company_id != source_company_id
        ]
        self.new_entry_ids: list[int] = []

        layout = QVBoxLayout(self)

        company_row = QHBoxLayout()
        company_row.addWidget(QLabel("شرکتِ مقصد:"))
        self.company_combo = QComboBox()
        for c in self._companies:
            self.company_combo.addItem(c.display_name or c.legal_name, c.company_id)
        self.company_combo.currentIndexChanged.connect(self._refresh_preview)
        company_row.addWidget(self.company_combo, stretch=1)
        layout.addLayout(company_row)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("حالت:"))
        self.copy_radio = QRadioButton("کپی (سندِ اصلی در شرکتِ مبدأ دست‌نخورده می‌ماند)")
        self.copy_radio.setChecked(True)
        self.transfer_radio = QRadioButton("انتقال (سندِ اصلی ابطال می‌شود — فقط اسنادِ موقت)")
        mode_row.addWidget(self.copy_radio)
        mode_row.addWidget(self.transfer_radio)
        layout.addLayout(mode_row)

        layout.addWidget(QLabel("حساب‌ها/تفصیلی‌هایِ استفاده‌شده که در شرکتِ مقصد هنوز تعریف نشده‌اند:"))
        self.preview_table = QTableWidget(0, 3)
        self.preview_table.setHorizontalHeaderLabels(["نوع", "کد", "نام"])
        self.preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.preview_table, stretch=1)

        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        layout.addWidget(self.warning_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.confirm_button = QPushButton("✅")
        self.confirm_button.setObjectName("primaryIconButton")
        self.confirm_button.setFixedWidth(40)
        self.confirm_button.setToolTip("تایید و انجام")
        self.confirm_button.clicked.connect(self._on_confirm)
        button_row.addWidget(self.confirm_button)
        cancel_button = QPushButton("↩️")
        cancel_button.setObjectName("iconButton")
        cancel_button.setFixedWidth(34)
        cancel_button.setToolTip("انصراف")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

        if not self._companies:
            self.warning_label.setText("هیچ شرکتِ مقصدِ دیگری که به آن دسترسی داشته باشید یافت نشد.")
            self.confirm_button.setEnabled(False)
        else:
            self._refresh_preview()

    def _refresh_preview(self) -> None:
        target_company_id = self.company_combo.currentData()
        if target_company_id is None:
            return
        missing = company_transfer.preview_transfer(self._source_company_id, target_company_id, self._journal_entry_ids)
        self.preview_table.setRowCount(len(missing))
        blocking = False
        for row, m in enumerate(missing):
            label = "حسابِ کدینگی" if m.kind == "GL" else m.dimension_label
            if not m.copyable:
                label += " — نیازمندِ تعریفِ دستی"
                blocking = True
            for col, text in enumerate([label, m.full_code, m.name]):
                item = QTableWidgetItem(text)
                if not m.copyable:
                    item.setForeground(Qt.red)
                self.preview_table.setItem(row, col, item)
        if blocking:
            self.warning_label.setText(
                "برخی تفصیلی‌هایِ شخص (مشتری/تامین‌کننده/پرسنل) در شرکتِ مقصد تعریف نشده‌اند — "
                "این‌ها هرگز خودکار کپی نمی‌شوند؛ باید پیش از ادامه، دستی در شرکتِ مقصد تعریف شوند."
            )
        elif missing:
            self.warning_label.setText("موارد بالا هنگامِ انجام، خودکار در شرکتِ مقصد ساخته می‌شوند.")
        else:
            self.warning_label.setText("همه‌یِ حساب‌ها/تفصیلی‌هایِ لازم از قبل در شرکتِ مقصد موجودند.")
        self.confirm_button.setEnabled(not blocking)

    def _on_confirm(self) -> None:
        target_company_id = self.company_combo.currentData()
        target_company = next(c for c in self._companies if c.company_id == target_company_id)
        try:
            self.new_entry_ids = company_transfer.transfer_journal_entries(
                self._source_company_id,
                target_company_id,
                self._journal_entry_ids,
                self._user_id,
                void_originals=self.transfer_radio.isChecked(),
                target_language_id=target_company.default_language_id,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.accept()


class JournalEntriesListScreen(FieldHelpMixin, QWidget):
    def __init__(
        self,
        main_window,
        *,
        entry_type_codes: list[str] | None = None,
        title: str = "اسنادِ حسابداری",
        new_entry_options: list[tuple[str, str]] | None = None,
        edit_screen_by_type: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self._main_window = main_window
        self._entry_type_codes = entry_type_codes
        # طبقِ درخواستِ صریح («خزانه‌داری با ساختارِ بنیادیِ برنامه»): همین
        # صفحه‌یِ فهرستِ اسناد، با فیلترِ نوعِ سند و مسیریابیِ ویرایش/سندِ
        # جدیدِ متفاوت، برایِ فهرستِ اسنادِ خزانه‌داری (دریافت/پرداخت) هم
        # دوباره استفاده می‌شود — بدونِ کپی‌کردنِ کدِ فهرست.
        self._new_entry_options = new_entry_options or [("+ سندِ جدید", "GL_JE")]
        self._edit_screen_by_type = edit_screen_by_type or {}
        self._entries: list[je_service.JournalEntrySummary] = []
        self._currency_decimal_places = 0
        self._currency_symbol: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        header.addWidget(title_label)
        header.addStretch(1)
        for button_label, screen_code in self._new_entry_options:
            clean_label = button_label.lstrip("+ ").strip() or button_label
            new_button = QPushButton(f"➕ {clean_label}")
            new_button.setObjectName("primaryButton")
            new_button.setToolTip(f"{clean_label}یِ تازه")
            new_button.clicked.connect(lambda _checked=False, code=screen_code: self._open_new_entry(code))
            header.addWidget(new_button)
        layout.addLayout(header)

        search_row = QHBoxLayout()
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("جستجو در شماره‌ی سند، شرح یا شماره‌ی عطف")
        self.search_field.textChanged.connect(self._apply_filter)
        search_row.addWidget(self.search_field, stretch=1)

        # طبقِ درخواستِ صریح («ادغامِ اسناد بر اساسِ تاریخ و فیلترهایِ
        # زمانی») — فیلترِ بازه‌یِ تاریخ اختیاری است (پیش‌فرض غیرِفعال، تا
        # رفتارِ فعلیِ فهرست دست‌نخورده بماند)؛ وقتی فعال شود، فقط اسنادِ
        # همان بازه در جدول می‌مانند و انتخاب/ادغام رویِ همان‌ها انجام می‌شود.
        self.date_filter_checkbox = QCheckBox("فیلترِ بازه‌یِ تاریخ:")
        self.date_filter_checkbox.stateChanged.connect(self._apply_filter)
        search_row.addWidget(self.date_filter_checkbox)
        self.date_from_field = JalaliDateEdit()
        self.date_from_field.textChanged.connect(self._apply_filter)
        search_row.addWidget(self.date_from_field)
        search_row.addWidget(QLabel("تا"))
        self.date_to_field = JalaliDateEdit()
        self.date_to_field.textChanged.connect(self._apply_filter)
        search_row.addWidget(self.date_to_field)
        layout.addLayout(search_row)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        # طبقِ درخواستِ صریح («ادغامِ چند سندِ انتخاب‌شده») — چندانتخابی،
        # به‌جایِ حالتِ پیش‌فرضِ تک‌ردیفی.
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(_COL_DESC, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self.table, stretch=1)

        buttons = QHBoxLayout()
        copy_button = QPushButton("📋")
        copy_button.setObjectName("iconButton")
        copy_button.setFixedWidth(34)
        copy_button.setToolTip("کپیِ سندِ انتخاب‌شده (مشابه)")
        copy_button.clicked.connect(lambda: self._copy_selected(reverse=False))
        buttons.addWidget(copy_button)

        reverse_copy_button = QPushButton("🔄")
        reverse_copy_button.setObjectName("iconButton")
        reverse_copy_button.setFixedWidth(34)
        reverse_copy_button.setToolTip("کپیِ معکوسِ سندِ انتخاب‌شده")
        reverse_copy_button.clicked.connect(lambda: self._copy_selected(reverse=True))
        buttons.addWidget(reverse_copy_button)

        approve_button = QPushButton("✅")
        approve_button.setObjectName("iconButton")
        approve_button.setFixedWidth(34)
        approve_button.setToolTip("تاییدِ سند (ارتقا به دائم)")
        approve_button.clicked.connect(self._approve_selected)
        buttons.addWidget(approve_button)

        reverse_button = QPushButton("↩️")
        reverse_button.setObjectName("iconButton")
        reverse_button.setFixedWidth(34)
        reverse_button.setToolTip("برگشت‌زدنِ سندِ دائم")
        reverse_button.clicked.connect(self._reverse_selected)
        buttons.addWidget(reverse_button)

        merge_button = QPushButton("🔗")
        merge_button.setObjectName("iconButton")
        merge_button.setFixedWidth(34)
        merge_button.setToolTip("ادغامِ اسنادِ انتخاب‌شده در یک سند")
        merge_button.clicked.connect(self._merge_selected)
        buttons.addWidget(merge_button)

        transfer_button = QPushButton("📤")
        transfer_button.setObjectName("iconButton")
        transfer_button.setFixedWidth(34)
        transfer_button.setToolTip("ارسال/کپی به شرکتِ دیگر")
        transfer_button.clicked.connect(self._transfer_selected)
        buttons.addWidget(transfer_button)

        buttons.addStretch(1)

        delete_button = QPushButton("🗑️")
        delete_button.setObjectName("dangerIconButton")
        delete_button.setFixedWidth(34)
        delete_button.setToolTip("حذفِ سندِ انتخاب‌شده (موقت/پیش‌نویس)")
        delete_button.clicked.connect(self._delete_selected)
        buttons.addWidget(delete_button)

        layout.addLayout(buttons)

        self.set_field_help([
            (
                self.search_field,
                "جستجو در شماره‌ی سند، شرح یا شماره‌ی عطف. برایِ بازکردنِ خودِ سند، رویِ ردیفش دابل‌کلیک کنید.",
            ),
            (
                self.date_filter_checkbox,
                "فقط اسنادِ یک بازه‌یِ تاریخِ مشخص نشان داده شوند — مثلاً پیش از ادغامِ چند سندِ یک روز/هفته.",
            ),
        ])

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        self._entries = (
            je_service.list_journal_entries(company_id, entry_type_codes=self._entry_type_codes)
            if company_id is not None
            else []
        )

        base_currency_id = session.current_company.base_currency_id if session.current_company else None
        currency = next((c for c in currencies_service.list_all_currencies() if c.currency_id == base_currency_id), None)
        self._currency_decimal_places = currency.decimal_places if currency else 0
        self._currency_symbol = currency.symbol if currency else None

        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self.search_field.text().strip()
        date_filter_on = self.date_filter_checkbox.isChecked()
        date_from = self.date_from_field.date() if date_filter_on else None
        date_to = self.date_to_field.date() if date_filter_on else None
        filtered = [
            e for e in self._entries
            if (
                not query
                or query in str(e.temporary_no)
                or query in (e.description or "")
                or query in (e.alternative_number or "")
            )
            and (date_from is None or e.document_date >= date_from)
            and (date_to is None or e.document_date <= date_to)
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

    def _open_new_entry(self, screen_code: str) -> None:
        self._main_window.open_screen(screen_code, then=lambda screen: screen._reset_form())

    def _on_row_double_clicked(self, row: int, _column: int) -> None:
        journal_entry_id = self.table.item(row, 0).data(Qt.UserRole)
        entry = next((e for e in self._entries if e.journal_entry_id == journal_entry_id), None)
        entry_type_code = entry.entry_type_code if entry is not None else "NORMAL"
        screen_code = self._edit_screen_by_type.get(entry_type_code, "GL_JE")
        self._main_window.open_screen(screen_code, then=lambda screen: screen.edit_journal_entry(journal_entry_id))

    def _copy_selected(self, *, reverse: bool) -> None:
        selected = self.table.selectedItems()
        if not selected:
            return
        journal_entry_id = selected[0].data(Qt.UserRole)
        entry = next((e for e in self._entries if e.journal_entry_id == journal_entry_id), None)
        entry_type_code = entry.entry_type_code if entry is not None else "NORMAL"
        screen_code = self._edit_screen_by_type.get(entry_type_code, "GL_JE")
        self._main_window.open_screen(
            screen_code, then=lambda screen: screen.copy_from_journal_entry(journal_entry_id, reverse=reverse)
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

    def _merge_selected(self) -> None:
        """طبقِ درخواستِ صریح («ادغامِ اسناد در لیستِ اسناد، بر اساسِ تاریخ
        و فیلترهایِ زمانی و نوعِ سند، در یک سندِ واحدِ جدید») — فیلترهایِ
        بالایِ همین فهرست (جستجو + بازه‌یِ تاریخ) و انتخابِ چندتاییِ
        کاربر با هم مشخص می‌کنند کدام اسناد ادغام شوند؛ نوعِ سند در همان
        merge_journal_entries اعتبارسنجی می‌شود (باید همه یک نوع باشند)."""
        selected_rows = {item.row() for item in self.table.selectedItems()}
        journal_entry_ids = list({self.table.item(row, 0).data(Qt.UserRole) for row in selected_rows})
        if len(journal_entry_ids) < 2:
            QMessageBox.warning(self, "ادغام", "حداقل دو سند را از فهرست انتخاب کنید.")
            return
        company_id = self._company_id()
        if company_id is None or session.current_user is None:
            return
        confirm = QMessageBox.question(
            self,
            "ادغامِ اسناد",
            f"{len(journal_entry_ids)} سندِ انتخاب‌شده در یک سندِ تازه ادغام شوند؟ "
            "اسنادِ اصلی حذف نمی‌شوند، فقط به وضعیتِ «ابطال‌شده» تغییر می‌کنند.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            result = je_service.merge_journal_entries(company_id, journal_entry_ids, session.current_user.user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        QMessageBox.information(
            self, "ادغام شد", f"سندِ تازه با شماره‌ی موقتِ {numerals.to_persian_digits(str(result.temporary_no))} ساخته شد."
        )
        self.refresh()

    def _transfer_selected(self) -> None:
        """طبقِ آیتمِ ۳ («ارسال/انتقال/کپیِ سند بینِ شرکت‌ها، هر دو حالت،
        انتخابی»): انتخابِ چندتاییِ همین فهرست، بدونِ نیاز به فیلترِ نوعِ
        سند (بر خلافِ ادغام) — چون کپی/انتقال محدود به یک نوعِ سند نیست."""
        selected_rows = {item.row() for item in self.table.selectedItems()}
        journal_entry_ids = list({self.table.item(row, 0).data(Qt.UserRole) for row in selected_rows})
        if not journal_entry_ids:
            QMessageBox.warning(self, "ارسال/کپی", "حداقل یک سند را از فهرست انتخاب کنید.")
            return
        company_id = self._company_id()
        if company_id is None or session.current_user is None:
            return
        dialog = _TransferDialog(self, company_id, journal_entry_ids, session.current_user.user_id)
        if dialog.exec() == QDialog.Accepted:
            QMessageBox.information(
                self, "انجام شد", f"{numerals.to_persian_digits(str(len(dialog.new_entry_ids)))} سند در شرکتِ مقصد ساخته شد."
            )
            self.refresh()
