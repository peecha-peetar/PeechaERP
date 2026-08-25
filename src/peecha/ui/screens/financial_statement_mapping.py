"""نگاشتِ صورت‌هایِ مالی — محیطی برایِ مرور/ویرایشِ سریعِ اینکه هر گروهِ
حساب (سطحِ ۱) در کدام صورتِ مالی و کدام بخشِ آن قرار می‌گیرد، بدونِ نیاز
به بازکردنِ تک‌تکِ فرمِ هرکدام در «کدینگِ حسابداری».

طبقِ درخواستِ صریح: تشخیصِ ترازنامه/سود-زیان از قبل با category_code
(ASSET/LIABILITY/EQUITY/REVENUE/EXPENSE) و account_type_code
(PERMANENT/TEMPORARY) انجام می‌شود — این دو همیشه در فرمِ حسابِ سطحِ گروه
قابلِ‌تنظیم بوده‌اند (chart_of_accounts.py)؛ این صفحه فقط یک نمایِ
متمرکز و سریع‌ترِ همان دو فیلد + فیلدِ تازه‌یِ سوم (بخشِ گردشِ وجوهِ نقد)
است، برایِ مرورِ همه‌یِ گروه‌ها یک‌جا."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import chart_of_accounts as coa_service
from peecha.ui import theme
from peecha.ui.widgets import wrap_scrollable_with_footer

_CATEGORY_OPTIONS = [
    ("ASSET", "دارایی"), ("LIABILITY", "بدهی"), ("EQUITY", "حقوق صاحبان سهام"),
    ("REVENUE", "درآمد"), ("COGS", "بهایِ تمام‌شده"), ("EXPENSE", "هزینه"),
    ("STATISTICAL", "حساب‌هایِ آماری"),
]
_ACCOUNT_TYPE_OPTIONS = [("PERMANENT", "ترازنامه‌ای"), ("TEMPORARY", "موقت"), ("STATISTICAL", "انتظامی")]
_CASH_FLOW_SECTION_OPTIONS = [
    (None, "— بدونِ طبقه‌بندی —"),
    ("OPERATING", "۱. فعالیت‌هایِ عملیاتی"),
    ("INVESTMENT_RETURNS_FINANCE_COST", "۲. بازده‌یِ سرمایه‌گذاری‌ها و سودِ پرداختیِ تامینِ مالی"),
    ("INCOME_TAX", "۳. مالیات بر درآمد"),
    ("INVESTING", "۴. فعالیت‌هایِ سرمایه‌گذاری"),
    ("FINANCING", "۵. فعالیت‌هایِ تامینِ مالی"),
]
_LIQUIDITY_CLASS_OPTIONS = [
    (None, "— بدونِ طبقه‌بندی —"),
    ("CURRENT", "جاری"),
    ("CURRENT_INVENTORY", "جاری (موجودی)"),
    ("NON_CURRENT", "غیرِجاری"),
]
_BALANCE_SHEET_SIDE_OPTIONS = [
    (None, "— خودکار (از رویِ دسته) —"),
    ("RIGHT", "راست"),
    ("LEFT", "چپ"),
]

_COLUMNS = [
    "کد", "نام", "دسته‌یِ حساب", "نوعِ حساب", "بخشِ گردشِ نقد", "طبقه‌یِ نقدینگی", "سمتِ ترازنامه",
]


def _fill_combo(combo: QComboBox, options: list[tuple[str | None, str]], current: str | None) -> None:
    combo.clear()
    for code, label in options:
        combo.addItem(label, code)
    index = combo.findData(current)
    combo.setCurrentIndex(index if index >= 0 else 0)


class FinancialStatementMappingScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[coa_service.AccountRow] = []
        # ردیف‌هایی که کاربر تغییر داده ولی هنوز ذخیره نشده‌اند — طبقِ
        # رفعِ باگِ صریح («چندین دکمه‌ی ذخیره روی هر ردیف، خیلی شلوغ و
        # سخت‌مدیریت است»)، دیگر هر ردیف دکمه‌ی ذخیره‌ی جداگانه ندارد؛ یک
        # دکمه‌ی واحد در فوترِ صفحه همه‌ی ردیف‌هایِ تغییریافته را یک‌جا
        # ذخیره می‌کند (هم‌الگو با یکپارچه‌سازیِ نوارِ دکمه‌هایِ بقیه‌یِ
        # فرم‌ها طبقِ همان قاعده‌یِ ثابتِ چیدمان).
        self._dirty_rows: set[int] = set()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)

        title = QLabel("تنظیماتِ صورت‌هایِ مالی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "مشخص کنید هر گروهِ حساب در کدام گزارشِ مالی بیاید: دارایی/بدهی/سرمایه در ترازنامه، "
            "درآمد/هزینه در سود و زیان. «بخشِ گردشِ نقد» و «طبقه‌یِ نقدینگی» اختیاری‌اند و فقط در "
            "گزارش‌هایِ مربوطه اثر دارند. تغییراتِ همه‌یِ ردیف‌ها را با یک دکمه‌یِ ذخیره در پایینِ "
            "صفحه یک‌جا ثبت کنید."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        # طبقِ بازخورد: ارتفاعِ پیش‌فرضِ ردیف برایِ پنج‌تا کمبوباکس در یک
        # ردیف کافی نبود (فیلدها فشرده/نصفه دیده می‌شدند) — هم‌الگو با
        # همین رفعِ باگ در journal_entry.py.
        self.table.verticalHeader().setDefaultSectionSize(48)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        # ستون‌هایِ کمبوباکس باید به‌اندازه‌یِ کافی عریض باشند، وگرنه متنِ
        # گزینه‌هایِ بلندتر (مثلِ «حقوق صاحبانِ سهام») بریده نشان داده می‌شود.
        combo_widths = {2: 190, 3: 130, 4: 340, 5: 150, 6: 170}
        for combo_col, width in combo_widths.items():
            self.table.setColumnWidth(combo_col, width)
            header.setSectionResizeMode(combo_col, QHeaderView.Fixed)
        layout.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

        self.save_button = QPushButton("💾")
        self.save_button.setObjectName("primaryIconButton")
        self.save_button.setFixedWidth(48)
        self.save_button.setToolTip("ذخیره‌یِ تغییرات")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save_all)
        outer.addWidget(wrap_scrollable_with_footer(content, [self.save_button]), stretch=1)

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        self.status_label.setText("")
        self._dirty_rows = set()
        self.save_button.setEnabled(False)
        company_id = self._company_id()
        self._rows = (
            [r for r in coa_service.list_accounts(company_id) if r.account_level == 1] if company_id is not None else []
        )
        self.table.setRowCount(len(self._rows))
        for row_index, account in enumerate(self._rows):
            self.table.setItem(row_index, 0, QTableWidgetItem(account.full_code))
            self.table.setItem(row_index, 1, QTableWidgetItem(account.name))

            category_combo = QComboBox()
            _fill_combo(category_combo, _CATEGORY_OPTIONS, account.category_code)
            self.table.setCellWidget(row_index, 2, category_combo)

            account_type_combo = QComboBox()
            _fill_combo(account_type_combo, _ACCOUNT_TYPE_OPTIONS, account.account_type_code)
            self.table.setCellWidget(row_index, 3, account_type_combo)

            cash_flow_combo = QComboBox()
            _fill_combo(cash_flow_combo, _CASH_FLOW_SECTION_OPTIONS, account.cash_flow_section_code)
            self.table.setCellWidget(row_index, 4, cash_flow_combo)

            liquidity_class_combo = QComboBox()
            _fill_combo(liquidity_class_combo, _LIQUIDITY_CLASS_OPTIONS, account.liquidity_class_code)
            self.table.setCellWidget(row_index, 5, liquidity_class_combo)

            balance_sheet_side_combo = QComboBox()
            _fill_combo(balance_sheet_side_combo, _BALANCE_SHEET_SIDE_OPTIONS, account.balance_sheet_side_code)
            self.table.setCellWidget(row_index, 6, balance_sheet_side_combo)

            for combo in (
                category_combo, account_type_combo, cash_flow_combo, liquidity_class_combo, balance_sheet_side_combo,
            ):
                combo.currentIndexChanged.connect(lambda _index, r=row_index: self._mark_dirty(r))

    def _mark_dirty(self, row_index: int) -> None:
        self._dirty_rows.add(row_index)
        self.save_button.setEnabled(True)

    def _save_all(self) -> None:
        company_id = self._company_id()
        if company_id is None or not self._dirty_rows:
            return
        saved_codes: list[str] = []
        for row_index in sorted(self._dirty_rows):
            if row_index >= len(self._rows):
                continue
            account = self._rows[row_index]
            category_combo = self.table.cellWidget(row_index, 2)
            account_type_combo = self.table.cellWidget(row_index, 3)
            cash_flow_combo = self.table.cellWidget(row_index, 4)
            liquidity_class_combo = self.table.cellWidget(row_index, 5)
            balance_sheet_side_combo = self.table.cellWidget(row_index, 6)
            try:
                coa_service.update_account(
                    account.account_id,
                    company_id,
                    account.name,
                    account.nature_code,
                    category_combo.currentData(),
                    account_type_combo.currentData(),
                    account.is_postable,
                    session.current_company.default_language_id if session.current_company else None,
                    changed_by_user_id=session.current_user.user_id if session.current_user else None,
                    cash_flow_section_code=cash_flow_combo.currentData(),
                    liquidity_class_code=liquidity_class_combo.currentData(),
                    balance_sheet_side_code=balance_sheet_side_combo.currentData(),
                )
                saved_codes.append(account.full_code)
            except ValueError as exc:
                theme.set_status_label(self.status_label, f"«{account.full_code}»: {exc}", ok=False)
                return
        self.refresh()
        theme.set_status_label(
            self.status_label, f"تنظیماتِ {len(saved_codes)} گروهِ حساب ذخیره شد.", ok=True
        )
