"""پایه‌یِ مشترکِ صفحاتِ گزارش — نوارِ فیلترِ بازه‌یِ تاریخ + وضعیتِ سند +
جستجویِ متنی + نوارِ خروجی (چاپ/PDF/Excel) + جدولِ نتایج (ستون‌هایِ
تغییرپذیر، بدونِ واحدِ پول، با فونتِ درشت‌تر برایِ خوانایی). پیرو الگویِ
کشف‌شده در journal_entries_list.py: بدونِ QScrollArea اضافه (خودِ
QTableWidget اسکرول می‌کند)، هدر/نوارها ثابت در VBoxِ بیرونی.

طبقِ درخواستِ صریح:
- واحدِ پول از همه‌یِ گزارش‌ها حذف شد (فقط عدد، بدونِ نمادِ ارز).
- فونتِ جدول درشت‌تر شد.
- ستون‌ها با کشیدنِ لبه قابلِ‌تغییرِ عرض‌اند (Interactive، به‌جایِ حالتِ
  پیش‌فرضِ نامشخص).
- فیلترِ وضعیتِ سند (موقت/قطعی) و جستجویِ متنیِ نتایج در همه‌یِ گزارش‌ها
  (این پایه) وجود دارد؛ فیلترهایِ پیشرفته‌ترِ اختیاری (بازه‌یِ کدِ حساب،
  مرکزِ هزینه/پروژه، شماره‌یِ سند) هرکدام با یک متدِ enable_* توسطِ
  زیرکلاسی که به آن نیاز دارد فعال می‌شوند."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
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

from peecha import numerals, session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services.reports import code_in_range
from peecha.ui import report_export
from peecha.ui.widgets import FieldHelpMixin, JalaliDateEdit

_ZERO = decimal.Decimal("0")

_STATUS_OPTIONS = [
    ("EXCLUDE_DRAFT", "بدونِ پیش‌نویس (پیش‌فرض)"),
    ("ALL", "همه (شاملِ پیش‌نویس)"),
    ("DRAFT_ONLY", "فقط پیش‌نویس"),
]


class _LiveAccountCodeField(QComboBox):
    """طبقِ درخواستِ صریح («در فیلدِ از‌کد‌تا‌حساب جستجویِ زنده باشه و
    بتوان کد را انتخاب کرد»): کمبویِ ویرایش‌پذیری که با تایپِ کد یا نام،
    فهرستِ حساب‌ها فیلتر می‌شود. سازگار با API قدیمیِ QLineEdit
    (فقط .text()، که بقیه‌ی reports_common.py/زیرکلاس‌هایش استفاده
    می‌کنند) نگه داشته شده تا نیازی به تغییرِ جایِ دیگر نباشد."""

    def __init__(self) -> None:
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)

    def set_options(self, accounts: list[tuple[str, str]]) -> None:
        current = self.text()
        self.blockSignals(True)
        super().clear()
        for full_code, name in accounts:
            self.addItem(f"{full_code} — {name}" if name else full_code)
        completer = QCompleter([self.itemText(i) for i in range(self.count())])
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.setCompleter(completer)
        self.blockSignals(False)
        self.lineEdit().setText(current)

    def text(self) -> str:
        raw = self.currentText().strip()
        if " — " in raw:
            return raw.split(" — ", 1)[0].strip()
        return raw

    def setText(self, text: str) -> None:
        self.lineEdit().setText(text)


def dimension_label(code: str) -> str:
    """برچسبِ فارسیِ یک نوع‌بُعدِ تفصیلی برایِ فیلترهایِ گزارش — PERSON
    (که خودش شخص نیست، فقط بسترِ مشتری/تامین‌کننده/پرسنل است) جداگانه
    برچسب می‌گیرد، بقیه از SPECIALIZED_DIMENSION_LABELS یا کدِ خودشان."""
    if code == dimensions_service.PERSON_DIMENSION_CODE:
        return "اشخاص (مشتری/تامین‌کننده/پرسنل)"
    return dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(code, code)


def net_split(debit: decimal.Decimal, credit: decimal.Decimal) -> tuple[decimal.Decimal, decimal.Decimal]:
    """مانده‌یِ خالص را به‌صورتِ یک‌طرفه (فقط بدهکار یا فقط بستانکار) برمی‌گرداند
    — قراردادِ استانداردِ نمایشِ «مانده» در تراز/دفترِ کل."""
    net = debit - credit
    return (net, _ZERO) if net >= 0 else (_ZERO, -net)


class ReportScreenBase(FieldHelpMixin, QWidget):
    """زیرکلاس‌ها باید `load_report(company_id, date_from, date_to)` را
    override کنند و (headers, rows, footer) برگردانند؛ فیلترهایِ اختصاصیِ
    خودشان را می‌توانند به `self.extra_filter_row` اضافه کنند و در
    `load_report` از `self.status_filter()`/`self.code_range()`/
    `self.cost_center_id()`/`self.document_no()` استفاده کنند."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title
        self._headers: list[str] = []
        self._all_rows: list[list] = []
        self._rows: list[list] = []
        self._footer: list | None = None
        # زیرکلاس‌هایی که دابل‌کلیکِ ردیف (Drill-down) دارند (مثلِ
        # report_account_ledger.py) این را در load_report() هم‌زمان با
        # rows پر می‌کنند تا بعدِ فیلترِ جستجو هم اندیس‌ها هم‌گام بمانند —
        # چون جستجو ممکن است زیرمجموعه‌ای از all_rows را نشان دهد و اندیسِ
        # ردیفِ نمایش‌داده‌شده دیگر با اندیسِ اصلی یکی نیست.
        self._all_row_ids: list = []
        self._row_ids: list = []
        # زیرکلاس‌هایی که ردیف‌هایِ بولد دارند (مثلِ report_custom_statement.py،
        # زیرکل‌هایِ فرمولی) این را در load_report() هم‌زمان با rows پر
        # می‌کنند — هم‌الگو با _all_row_ids/_row_ids؛ اگر خالی بماند
        # (گزارش‌هایِ دیگر) هیچ ردیفی بولد نمی‌شود.
        self._all_row_bold: list[bool] = []
        self._row_bold: list[bool] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        header.addWidget(title_label)
        header.addStretch(1)
        layout.addLayout(header)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("از تاریخ:"))
        self.date_from = JalaliDateEdit()
        filter_row.addWidget(self.date_from)
        filter_row.addWidget(QLabel("تا تاریخ:"))
        self.date_to = JalaliDateEdit()
        filter_row.addWidget(self.date_to)

        filter_row.addWidget(QLabel("وضعیتِ سند:"))
        self.status_combo = QComboBox()
        for value, label in _STATUS_OPTIONS:
            self.status_combo.addItem(label, value)
        filter_row.addWidget(self.status_combo)

        self.extra_filter_row = QHBoxLayout()
        filter_row.addLayout(self.extra_filter_row)

        apply_button = QPushButton("اعمالِ فیلتر")
        apply_button.setObjectName("primaryButton")
        apply_button.clicked.connect(self._reload)
        filter_row.addWidget(apply_button)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        # فیلترهایِ پیشرفته‌یِ اختیاری — پیش‌فرض مخفی، هر زیرکلاسی که لازم
        # دارد با enable_* نمایانشان می‌کند.
        advanced_row = QHBoxLayout()
        self.code_from_label = QLabel("از کدِ حساب:")
        self.code_from_field = _LiveAccountCodeField()
        self.code_from_field.setMinimumWidth(260)
        self.code_from_field.setMaximumWidth(420)
        self.code_to_label = QLabel("تا کدِ حساب:")
        self.code_to_field = _LiveAccountCodeField()
        self.code_to_field.setMinimumWidth(260)
        self.code_to_field.setMaximumWidth(420)
        self.cost_center_label = QLabel("مرکزِ هزینه/پروژه:")
        self.cost_center_combo = QComboBox()
        self.document_no_label = QLabel("شماره‌یِ سند:")
        self.document_no_field = QLineEdit()
        self.document_no_field.setMaximumWidth(110)
        for widget in (
            self.code_from_label,
            self.code_from_field,
            self.code_to_label,
            self.code_to_field,
            self.cost_center_label,
            self.cost_center_combo,
            self.document_no_label,
            self.document_no_field,
        ):
            widget.setVisible(False)
            advanced_row.addWidget(widget)
        advanced_row.addStretch(1)
        layout.addLayout(advanced_row)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("جستجو در نتایج:"))
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("جستجو در کد، نام یا شرح...")
        self.search_field.textChanged.connect(self._apply_search_filter)
        search_row.addWidget(self.search_field, stretch=1)

        print_button = QPushButton("🖨 چاپ")
        print_button.setObjectName("flatButton")
        print_button.clicked.connect(self._on_print)
        search_row.addWidget(print_button)

        pdf_button = QPushButton("📄 خروجیِ PDF")
        pdf_button.setObjectName("flatButton")
        pdf_button.clicked.connect(self._on_export_pdf)
        search_row.addWidget(pdf_button)

        excel_button = QPushButton("📊 خروجیِ Excel")
        excel_button.setObjectName("flatButton")
        excel_button.clicked.connect(self._on_export_excel)
        search_row.addWidget(excel_button)
        layout.addLayout(search_row)

        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        # طبقِ درخواستِ صریح، اعدادِ گزارش‌ها درشت‌تر از بقیه‌یِ برنامه باشند —
        # چون سراسرِ استایلِ برنامه با واحدِ px تعریف شده (نه pt)، دستکاریِ
        # QFont.setPointSize بی‌اثر می‌ماند (pointSize() برایِ فونتِ استایل‌شده
        # با px مقدارِ -1 برمی‌گرداند)؛ به‌جایش مستقیماً رویِ خودِ جدول یک
        # استایل‌شیتِ px-محور اعمال می‌شود.
        self.table.setStyleSheet(
            "QTableWidget { font-size: 15px; }"
            " QHeaderView::section { font-size: 14px; font-weight: bold; }"
        )
        layout.addWidget(self.table, stretch=1)

        # طبقِ درخواستِ صریح برایِ گسترشِ راهنمایِ فیلدها به همه‌یِ صفحات:
        # چون همه‌یِ گزارش‌ها از همین پایه ارث می‌برند، ثبتِ فیلترهایِ
        # مشترک این‌جا کافی است تا همه‌یِ صفحاتِ گزارش را یک‌جا پوشش دهد؛
        # زیرکلاس‌هایی که فیلترهایِ اختصاصیِ خودشان را در extra_filter_row
        # اضافه می‌کنند، می‌توانند با self.add_field_help(...) موارد
        # بیشتری هم ثبت کنند.
        self.set_field_help([
            (self.date_from, "ابتدایِ بازه‌یِ گزارش، به شمسی. یعنی از کجایِ زمان گزارش را می‌خواهید ببینید."),
            (self.date_to, "انتهایِ بازه‌یِ گزارش، به شمسی. در گزارش‌هایِ ترازنامه‌ای، همین تاریخ برایِ گرفتنِ مانده استفاده می‌شود."),
            (
                self.status_combo,
                "کدام اسناد در گزارش بیایند؟ «بدونِ پیش‌نویس» یعنی فقط اسنادِ قطعی — این پیش‌فرض است. "
                "«همه» یعنی پیش‌نویس‌ها هم بیایند. «فقط پیش‌نویس» یعنی فقط سندهایِ هنوز ثبت‌نشده.",
            ),
            (
                self.search_field,
                "جستجویِ زنده در همین نتایج — رویِ کد، نام یا شرحِ هر ردیف. گزارش را دوباره اجرا نمی‌کند.",
            ),
            (
                self.code_from_field,
                "کدِ حسابِ شروعِ بازه. با تایپِ کد یا نام، فهرستِ زنده‌ی حساب‌ها فیلتر می‌شود و می‌توانید انتخاب کنید؛ "
                "دستی تایپ‌کردن هم جواب می‌دهد. اختیاری است؛ اگر خالی بماند، از ابتدا محدودیتی ندارد.",
            ),
            (
                self.code_to_field,
                "کدِ حسابِ پایانِ بازه — مثلِ فیلدِ «از کدِ حساب»، با جستجویِ زنده. اختیاری است؛ اگر خالی بماند، تا انتها محدودیتی ندارد.",
            ),
            (self.cost_center_combo, "فقط اسنادِ همین مرکزِ هزینه یا پروژه نشان داده شوند. «همه» یعنی بدونِ این فیلتر."),
            (self.document_no_field, "فقط سندی با همین شماره نشان داده شود. اختیاری است."),
        ])

    def add_field_help(self, fields: list[tuple[QWidget, str]]) -> None:
        """زیرکلاس‌هایی که فیلترهایِ اختصاصیِ خودشان را دارند، با این متد
        (به‌جایِ صدازدنِ set_field_help که فهرستِ پایه را جایگزین می‌کند)
        فیلدهایِ بیشتری به همان راهنمایِ مشترک اضافه می‌کنند."""
        self._field_help_fields = [*self._field_help_fields, *fields]

    # --- فعال‌سازیِ فیلترهایِ پیشرفته‌یِ اختیاری، توسطِ زیرکلاس -----------
    def enable_code_range_filter(self) -> None:
        for widget in (self.code_from_label, self.code_from_field, self.code_to_label, self.code_to_field):
            widget.setVisible(True)

    def enable_cost_center_filter(self) -> None:
        self.cost_center_label.setVisible(True)
        self.cost_center_combo.setVisible(True)

    def enable_document_no_filter(self) -> None:
        self.document_no_label.setVisible(True)
        self.document_no_field.setVisible(True)

    def _reload_cost_center_options(self) -> None:
        company_id = self._company_id()
        self.cost_center_combo.clear()
        self.cost_center_combo.addItem("— همه —", None)
        if company_id is None:
            return
        cost_center_type_id = dimensions_service.get_specialized_dimension_type_id(
            company_id, dimensions_service.COST_CENTER_CODE
        )
        project_type_id = dimensions_service.get_specialized_dimension_type_id(
            company_id, dimensions_service.PROJECT_CODE
        )
        for row in dimensions_service.list_all_detail_accounts(company_id):
            if row.dimension_type_id in (cost_center_type_id, project_type_id):
                self.cost_center_combo.addItem(
                    f"{row.group_name}: {row.full_code} — {row.name or ''}", row.detail_account_id
                )

    def code_range_account_level(self) -> int | None:
        """زیرکلاس‌هایی که کمبویِ «سطح» (گروه/کل/معین/تفصیلی) دارند این را
        override می‌کنند تا طبقِ درخواستِ صریح، فهرستِ زنده‌ی کدِ حساب فقط
        به همان سطحِ انتخاب‌شده محدود بماند (نه همه‌ی سطوح با هم). مقدارِ
        پیش‌فرض None یعنی بدونِ محدودیت (گزارش‌هایی که سطح ندارند)."""
        return None

    def _reload_code_range_options(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        level = self.code_range_account_level()
        accounts = coa_service.list_accounts(company_id)
        # تفصیلی (سطحِ ۴) از جدولِ دیگری می‌آید و در این فهرستِ زنده
        # نیست؛ برایِ آن سطح، تایپِ دستیِ کد همچنان کار می‌کند.
        if level in (1, 2, 3):
            accounts = [a for a in accounts if a.account_level == level]
        options = [(a.full_code, a.name) for a in accounts]
        self.code_from_field.set_options(options)
        self.code_to_field.set_options(options)

    # --- خواندنِ مقدارِ فیلترها --------------------------------------------
    def status_filter(self) -> str:
        return self.status_combo.currentData()

    def code_range(self) -> tuple[str, str]:
        return self.code_from_field.text().strip(), self.code_to_field.text().strip()

    def cost_center_id(self) -> int | None:
        return self.cost_center_combo.currentData()

    def document_no(self) -> int | None:
        text = self.document_no_field.text().strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def _default_date_range(self) -> tuple[datetime.date, datetime.date]:
        today = datetime.date.today()
        fiscal_year = session.current_fiscal_year
        start = fiscal_year.start_date if fiscal_year is not None else today.replace(month=1, day=1)
        return start, today

    def refresh(self) -> None:
        start, end = self._default_date_range()
        self.date_from.setDate(start)
        self.date_to.setDate(end)
        if self.cost_center_combo.isVisibleTo(self):
            self._reload_cost_center_options()
        if self.code_from_field.isVisibleTo(self):
            self._reload_code_range_options()
        self._reload()

    def _reload(self) -> None:
        company_id = self._company_id()
        self._all_row_ids = []
        self._all_row_bold = []
        if company_id is None:
            self._headers, self._all_rows, self._footer = [], [], None
            self._apply_search_filter()
            return
        headers, rows, footer = self.load_report(company_id, self.date_from.date(), self.date_to.date())
        self._headers, self._all_rows, self._footer = headers, rows, footer
        self._apply_search_filter()

    def _apply_search_filter(self) -> None:
        query = self.search_field.text().strip()
        has_ids = len(self._all_row_ids) == len(self._all_rows)
        has_bold = len(self._all_row_bold) == len(self._all_rows)
        if not query:
            self._rows = self._all_rows
            if has_ids:
                self._row_ids = self._all_row_ids
            if has_bold:
                self._row_bold = self._all_row_bold
        else:
            indices = [i for i, row in enumerate(self._all_rows) if any(query in str(cell) for cell in row)]
            self._rows = [self._all_rows[i] for i in indices]
            if has_ids:
                self._row_ids = [self._all_row_ids[i] for i in indices]
            if has_bold:
                self._row_bold = [self._all_row_bold[i] for i in indices]
        self._set_table(self._headers, self._rows, self._footer)

    def _set_table(self, headers: list[str], rows: list[list], footer: list | None) -> None:
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        for col_index in range(len(headers)):
            self.table.horizontalHeader().setSectionResizeMode(col_index, QHeaderView.Interactive)
        extra = 1 if footer else 0
        self.table.setRowCount(len(rows) + extra)
        has_bold = len(self._row_bold) == len(rows)
        for row_index, row in enumerate(rows):
            row_is_bold = has_bold and self._row_bold[row_index]
            for col_index, value in enumerate(row):
                item = QTableWidgetItem(str(value))
                if row_is_bold:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.table.setItem(row_index, col_index, item)
        if footer:
            footer_row = len(rows)
            for col_index, value in enumerate(footer):
                item = QTableWidgetItem(str(value))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                self.table.setItem(footer_row, col_index, item)
        self.table.resizeColumnsToContents()

    def load_report(
        self, company_id: int, date_from: datetime.date, date_to: datetime.date
    ) -> tuple[list[str], list[list], list | None]:
        raise NotImplementedError

    # --- سربرگِ چاپ/PDF/Excel: نامِ شرکت + تاریخِ گزارش + فیلترها --------
    def extra_filters_summary(self) -> list[tuple[str, str]]:
        """زیرکلاس‌هایی که فیلترِ اختصاصیِ خودشان را دارند (extra_filter_row)
        این متد را override می‌کنند تا همان فیلترها هم در سربرگِ چاپ/PDF/
        Excel، به همان ترتیبی که در فرم دیده می‌شوند، ظاهر شوند."""
        return []

    def _filters_summary(self) -> list[tuple[str, str]]:
        # طبقِ گزارشِ صریح: سربرگِ چاپ باید فیلترهایِ اِعمال‌شده را به همان
        # ترتیبِ نمایش در فرمِ فیلتر نشان دهد — این‌جا هم به همان ترتیب
        # (تاریخ‌ها -> وضعیت -> فیلترهایِ پیشرفته‌یِ فعال -> جستجو) ساخته
        # می‌شود.
        parts: list[tuple[str, str]] = [
            ("از تاریخ", numerals.format_jalali_date(self.date_from.date())),
            ("تا تاریخ", numerals.format_jalali_date(self.date_to.date())),
            ("وضعیتِ سند", self.status_combo.currentText()),
        ]
        if self.code_from_field.isVisibleTo(self) and (
            self.code_from_field.text().strip() or self.code_to_field.text().strip()
        ):
            parts.append(("بازه‌یِ کد", f"{self.code_from_field.text().strip()} تا {self.code_to_field.text().strip()}"))
        if self.cost_center_combo.isVisibleTo(self) and self.cost_center_combo.currentData() is not None:
            parts.append(("مرکزِ هزینه/پروژه", self.cost_center_combo.currentText()))
        if self.document_no_field.isVisibleTo(self) and self.document_no_field.text().strip():
            parts.append(("شماره‌یِ سند", self.document_no_field.text().strip()))
        parts.extend(self.extra_filters_summary())
        if self.search_field.text().strip():
            parts.append(("جستجو در نتایج", self.search_field.text().strip()))
        return parts

    def _export_kwargs(self) -> dict:
        return {
            "company_name": session.current_company.display_name if session.current_company else "",
            "report_date": numerals.format_jalali_date(datetime.date.today()),
            "filters": self._filters_summary(),
        }

    def _prompt_print_options(self) -> "report_export.PrintOptions | None":
        """طبقِ درخواستِ صریح: پیش از هر چاپ/PDF/اکسل، فرمِ تنظیماتِ چاپ
        (اندازه‌یِ فونت، عرضِ ستون‌ها، متنِ اضافه‌یِ هدر/فوتر) باز می‌شود؛
        انتخابِ قبلی به‌عنوانِ پیش‌فرضِ دفعه‌یِ بعد نگه داشته می‌شود."""
        options = report_export.prompt_print_options(
            self, self._title, self._headers, getattr(self, "_last_print_options", None)
        )
        if options is not None:
            self._last_print_options = options
        return options

    def _on_print(self) -> None:
        if not self._rows:
            report_export.print_report(self, self._title, self._headers, self._rows, self._footer, **self._export_kwargs())
            return
        options = self._prompt_print_options()
        if options is None:
            return
        report_export.print_report(
            self, self._title, self._headers, self._rows, self._footer, options=options, **self._export_kwargs()
        )

    def _on_export_pdf(self) -> None:
        if not self._rows:
            report_export.export_report_pdf(self, self._title, self._headers, self._rows, self._footer, **self._export_kwargs())
            return
        options = self._prompt_print_options()
        if options is None:
            return
        report_export.export_report_pdf(
            self, self._title, self._headers, self._rows, self._footer, options=options, **self._export_kwargs()
        )

    def _on_export_excel(self) -> None:
        if not self._rows:
            report_export.export_report_excel(self, self._title, self._headers, self._rows, self._footer, **self._export_kwargs())
            return
        options = self._prompt_print_options()
        if options is None:
            return
        report_export.export_report_excel(
            self, self._title, self._headers, self._rows, self._footer, options=options, **self._export_kwargs()
        )
