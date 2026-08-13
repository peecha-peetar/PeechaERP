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
    QHBoxLayout,
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
    "کد", "نام", "دسته‌یِ حساب", "نوعِ حساب", "بخشِ گردشِ نقد", "طبقه‌یِ نقدینگی", "سمتِ ترازنامه", "",
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("نگاشتِ صورت‌هایِ مالی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "مشخص کنید هر گروهِ حساب در کدام گزارشِ مالی بیاید: دارایی/بدهی/سرمایه در ترازنامه، "
            "درآمد/هزینه در سود و زیان. «بخشِ گردشِ نقد» و «طبقه‌یِ نقدینگی» اختیاری‌اند و فقط در "
            "گزارش‌هایِ مربوطه اثر دارند. با ذخیره، همه‌یِ زیرمجموعه‌هایِ همان گروه هم به‌روز می‌شوند."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        # طبقِ بازخورد: ارتفاعِ پیش‌فرضِ ردیف برایِ سه‌تا کمبوباکس+دکمه در
        # یک ردیف کافی نبود (فیلدها فشرده/نصفه دیده می‌شدند) — هم‌الگو با
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
        self.table.setColumnWidth(7, 90)
        header.setSectionResizeMode(7, QHeaderView.Fixed)
        layout.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        self.status_label.setText("")
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

            # طبقِ درخواستِ صریح («دکمه‌ی ذخیره مثلِ دکمه‌هایِ روشِ دریافت/
            # پرداخت باشد»): تا این ردیف تغییری نکرده، دکمه غیرفعال/طوسی
            # می‌ماند؛ همین علامتِ بصری از گم‌شدنِ ذخیره‌ی یک ردیف (وقتیِ
            # کاربر چند ردیف را با هم ویرایش می‌کند ولی فقط رویِ یکی
            # کلیک می‌کند) جلوگیری می‌کند — چون refresh() همه‌ی کمبوها را
            # از رویِ دیتابیس بازمی‌سازد و تغییرِ ذخیره‌نشده‌ی ردیف‌هایِ
            # دیگر گم می‌شود.
            save_button = QPushButton("ذخیره")
            save_button.setObjectName("primaryButton")
            save_button.setEnabled(False)
            # نکته‌یِ مهم: کمبوها باید با آرگومانِ پیش‌فرض به لامبدا مقیّد
            # شوند (نه فقط با closure) — وگرنه چون همه‌یِ ردیف‌هایِ حلقه در
            # یک اسکوپِ مشترک‌اند، دکمه‌یِ همه‌یِ ردیف‌ها به کمبوهایِ
            # *آخرین* ردیف اشاره می‌کرد و ذخیره‌یِ هر ردیفی جز آخرین،
            # مقادیرِ ردیفِ اشتباه را می‌نوشت — دقیقاً همان باگِ گزارش‌شده.
            save_button.clicked.connect(
                lambda _checked=False, r=row_index, b=save_button,
                cc=category_combo, tc=account_type_combo, fc=cash_flow_combo,
                lc=liquidity_class_combo, sc=balance_sheet_side_combo: self._save_row(
                    r, cc, tc, fc, lc, sc, b
                )
            )
            for combo in (category_combo, account_type_combo, cash_flow_combo, liquidity_class_combo, balance_sheet_side_combo):
                combo.currentIndexChanged.connect(lambda _index, b=save_button: b.setEnabled(True))
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(4, 0, 4, 0)
            cell_layout.addWidget(save_button)
            self.table.setCellWidget(row_index, 7, cell)

    def _save_row(
        self,
        row_index: int,
        category_combo: QComboBox,
        account_type_combo: QComboBox,
        cash_flow_combo: QComboBox,
        liquidity_class_combo: QComboBox,
        balance_sheet_side_combo: QComboBox,
        save_button: QPushButton,
    ) -> None:
        company_id = self._company_id()
        if company_id is None or row_index >= len(self._rows):
            return
        account = self._rows[row_index]
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
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return
        save_button.setEnabled(False)
        theme.set_status_label(self.status_label, f"نگاشتِ حسابِ «{account.full_code}» ذخیره شد.", ok=True)
