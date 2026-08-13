"""کدینگِ حساب‌ها — معادلِ Qt برایِ chart_of_accounts.py/.kv در Kivy.

فهرست (چپ) + فرمِ ساخت/ویرایش (راست، طبقِ ترتیبِ RTLِ Qt، «راست» یعنی
اولین‌اعلام‌شده در QHBoxLayout, بر خلافِ Kivy که نیاز به ترتیبِ معکوس
داشت)."""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.ui import report_export, theme
from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.ui.excel_import import ExcelColumnMappingDialog, read_excel_rows
from peecha.ui.widgets import FieldHelpMixin

# طبقِ درخواستِ صریح («در فرمِ تعریفِ حساب‌ها هم بتوان از اکسل ایمپورت
# کرد») — «کدِ کامل» (full_code، مثلِ 1-01-001) به‌جایِ کدِ بخش گرفته
# می‌شود چون سلسله‌مراتب را یک‌جا مشخص می‌کند؛ ماهیت/دسته/نوع فقط برایِ
# ردیف‌هایِ سطحِ گروه (بدونِ خط‌تیره در کد) لازم‌اند — بقیه از والدشان
# به‌ارث می‌برند (دقیقاً هم‌رفتار با فرمِ دستی).
_COA_IMPORT_TARGET_FIELDS: list[tuple[str, str, bool]] = [
    ("full_code", "کدِ کاملِ حساب (مثلِ 1-01-001)", True),
    ("name", "نام", True),
    ("nature_code", "ماهیت (فقط سطحِ گروه: بدهکار/بستانکار/دوطرفه)", False),
    ("category_code", "دسته (فقط سطحِ گروه)", False),
    ("account_type_code", "نوعِ حساب (فقط سطحِ گروه)", False),
    ("is_postable", "قابلِ ثبتِ سند؟ (بله/خیر)", False),
]
_COA_IMPORT_GUESS_KEYWORDS: dict[str, list[str]] = {
    "full_code": ["کد کامل", "کدحساب", "کد حساب", "کد"],
    "name": ["نام"],
    "nature_code": ["ماهیت"],
    "category_code": ["دسته"],
    "account_type_code": ["نوع حساب", "نوعِ حساب"],
    "is_postable": ["قابل ثبت", "قابلِ ثبت"],
}

_NATURE_OPTIONS = [("DEBIT", "بدهکار"), ("CREDIT", "بستانکار"), ("BOTH", "دوطرفه")]
_CATEGORY_OPTIONS = [
    ("ASSET", "دارایی"), ("LIABILITY", "بدهی"), ("EQUITY", "حقوق صاحبان سهام"),
    ("REVENUE", "درآمد"), ("COGS", "بهایِ تمام‌شده"), ("EXPENSE", "هزینه"),
    ("STATISTICAL", "حساب‌هایِ آماری"),
]
_ACCOUNT_TYPE_OPTIONS = [("PERMANENT", "ترازنامه‌ای"), ("TEMPORARY", "موقت"), ("STATISTICAL", "انتظامی")]
# طبقِ درخواستِ صریح: برخلافِ سه فیلدِ بالا، این یکی اختیاری است — گزینه‌ی
# اول (None) یعنی «این حساب در گردشِ وجوهِ نقدِ غیرمستقیم دیده نمی‌شود»
# (مثلِ خودِ صندوق/بانک، یا حساب‌هایِ درآمد/هزینه که در سودِ خالص از قبل
# لحاظ شده‌اند).
_CASH_FLOW_SECTION_OPTIONS = [
    (None, "— بدونِ طبقه‌بندی —"),
    ("OPERATING", "عملیاتی"),
    ("INVESTING", "سرمایه‌گذاری"),
    ("FINANCING", "تامینِ مالی"),
]
# طبقِ همان الگویِ بالا: اختیاری — فقط حساب‌هایِ دارایی/بدهی که باید در
# نسبتِ جاری/آنی (گزارشِ نسبت‌هایِ مالی) دیده شوند طبقه‌بندی می‌شوند.
# CURRENT_INVENTORY زیرمجموعه‌یِ دارایی‌هایِ جاری است ولی از دارایی‌هایِ
# آنی (Quick Assets) کم می‌شود.
_LIQUIDITY_CLASS_OPTIONS = [
    (None, "— بدونِ طبقه‌بندی —"),
    ("CURRENT", "جاری"),
    ("CURRENT_INVENTORY", "جاری (موجودی)"),
    ("NON_CURRENT", "غیرِجاری"),
]
_LEVEL_LABELS = {1: "گروه", 2: "کل", 3: "معین"}
_LEVEL_COLORS = {1: theme.LEVEL_GROUP, 2: theme.LEVEL_KOL, 3: theme.LEVEL_MOEIN}
# طبقِ درخواستِ صریح: برچسبِ فیلدهایِ کد/نام باید متناسب با سطحِ حسابِ
# درحالِ‌ساخت (بر اساسِ والدِ انتخاب‌شده) تغییر کند، نه همیشه «کدِ بخش»/«نام».
_SEGMENT_CODE_LABELS = {1: "کدِ گروه", 2: "کدِ کل", 3: "کدِ معین"}
_ACCOUNT_NAME_LABELS = {1: "نامِ گروه", 2: "نامِ حسابِ کل", 3: "نامِ حسابِ معین"}

# طبقِ گزارشِ صریح: ترتیبِ نمایشِ ستون‌ها راست‌چین نبود — چون QTableWidget
# با راست‌چین بودنِ برنامه ترتیبِ افزودنِ ستون‌ها را آینه می‌کند (اولین
# ستون در راست‌ترین جا می‌نشیند)، «کدِ کامل» (مهم‌ترین/اولین ستون از نظرِ
# خواندن) باید *اول* در این فهرست بیاید، نه آخر.
_COLUMNS = ["کدِ کامل", "نام", "سطح", "قابلِ ثبت", "فعال؟"]


def _fill_combo(combo: QComboBox, options: list[tuple[str, str]]) -> None:
    combo.clear()
    for code, label in options:
        combo.addItem(label, code)


def _combo_value(combo: QComboBox) -> str | None:
    return combo.currentData()


def _select_combo_value(combo: QComboBox, value: str | None) -> None:
    if value is None:
        combo.setCurrentIndex(0)
        return
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else 0)


class ChartOfAccountsScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[coa_service.AccountRow] = []
        self._editing_account_id: int | None = None
        self._parent_options: list[coa_service.AccountRow] = []

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)

    # --- فهرست --------------------------------------------------------------
    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        title = QLabel("کدینگِ حساب‌ها")
        title.setObjectName("pageTitle")
        header_row.addWidget(title)
        header_row.addStretch(1)
        # طبقِ درخواستِ صریح («خروجیِ اکسل و چاپی از کدینگ، برایِ برگرداندن
        # روی دیتابیسِ جدید»): ستون‌هایِ خروجیِ اکسل دقیقاً هم‌شکلِ همان
        # فیلدهایِ ایمپورت (_COA_IMPORT_TARGET_FIELDS) هستند تا فایلِ
        # خروجی بدونِ ویرایشِ دستی، دوباره از همین صفحه قابلِ‌ایمپورت باشد.
        print_button = QPushButton("🖨 چاپ")
        print_button.setObjectName("flatButton")
        print_button.clicked.connect(self._on_print)
        header_row.addWidget(print_button)
        pdf_button = QPushButton("📄 PDF")
        pdf_button.setObjectName("flatButton")
        pdf_button.clicked.connect(self._on_export_pdf)
        header_row.addWidget(pdf_button)
        excel_export_button = QPushButton("📊 خروجیِ اکسل")
        excel_export_button.setObjectName("flatButton")
        excel_export_button.clicked.connect(self._on_export_excel)
        header_row.addWidget(excel_export_button)
        import_excel_button = QPushButton("📥 ایمپورت از اکسل")
        import_excel_button.setObjectName("flatButton")
        import_excel_button.clicked.connect(self._on_import_excel)
        header_row.addWidget(import_excel_button)
        layout.addLayout(header_row)

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("جستجو در کد یا نامِ حساب")
        self.search_field.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search_field)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        layout.addWidget(self.table)

        return panel

    # --- فرم ------------------------------------------------------------
    def _build_form_panel(self) -> QWidget:
        # طبقِ گزارشِ صریح: این فرم (چک‌لیستِ نوع‌هایِ تفصیلی + گروه‌هایِ
        # اشخاصِ مجاز + فیلدهایِ اصلیِ حساب) می‌تواند طولانی شود و هیچ
        # اسکرولی نداشت.
        #
        # باگِ واقعیِ گزارش‌شده: دکمه‌هایِ ذخیره/انصراف/حذف قبلاً *داخلِ*
        # همین محتوایِ اسکرول‌شونده بودند — با چک‌لیستِ بلند (مثلاً حسابی
        # که همه‌یِ گروه‌هایِ شخص + مرکزِهزینه/پروژه را دارد)، این دکمه‌ها
        # چندین صفحه پایین‌تر می‌رفتند و در حالتِ تمام‌صفحه، عملاً از دیدِ
        # کاربر خارج می‌شدند (زیرِ نوارِ وظیفه به‌نظر می‌رسید). حالا این
        # دکمه‌ها به یک نوارِ ثابتِ زیرِ اسکرول منتقل شده‌اند — همیشه دیده
        # می‌شوند، صرفِ‌نظر از طولِ چک‌لیست یا اندازه‌یِ پنجره.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.form_title = QLabel("حسابِ جدید")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        grid = QGridLayout()
        grid.setSpacing(8)
        row = 0

        grid.addWidget(QLabel("والد"), row, 0)
        self.parent_combo = QComboBox()
        self.parent_combo.currentIndexChanged.connect(self._update_level_preview)
        grid.addWidget(self.parent_combo, row, 1)
        row += 1

        self.segment_code_label = QLabel("کدِ گروه")
        grid.addWidget(self.segment_code_label, row, 0)
        self.segment_code_field = QLineEdit()
        grid.addWidget(self.segment_code_field, row, 1)
        row += 1

        self.name_label = QLabel("نامِ گروه")
        grid.addWidget(self.name_label, row, 0)
        self.name_field = QLineEdit()
        grid.addWidget(self.name_field, row, 1)
        row += 1

        grid.addWidget(QLabel("ماهیت"), row, 0)
        self.nature_combo = QComboBox()
        _fill_combo(self.nature_combo, _NATURE_OPTIONS)
        grid.addWidget(self.nature_combo, row, 1)
        row += 1

        grid.addWidget(QLabel("دسته"), row, 0)
        self.category_combo = QComboBox()
        _fill_combo(self.category_combo, _CATEGORY_OPTIONS)
        grid.addWidget(self.category_combo, row, 1)
        row += 1

        grid.addWidget(QLabel("نوعِ حساب"), row, 0)
        self.account_type_combo = QComboBox()
        _fill_combo(self.account_type_combo, _ACCOUNT_TYPE_OPTIONS)
        grid.addWidget(self.account_type_combo, row, 1)
        row += 1

        grid.addWidget(QLabel("بخشِ گردشِ وجوهِ نقد"), row, 0)
        self.cash_flow_section_combo = QComboBox()
        _fill_combo(self.cash_flow_section_combo, _CASH_FLOW_SECTION_OPTIONS)
        grid.addWidget(self.cash_flow_section_combo, row, 1)
        row += 1

        grid.addWidget(QLabel("طبقه‌یِ نقدینگی"), row, 0)
        self.liquidity_class_combo = QComboBox()
        _fill_combo(self.liquidity_class_combo, _LIQUIDITY_CLASS_OPTIONS)
        grid.addWidget(self.liquidity_class_combo, row, 1)
        row += 1

        self.is_postable_checkbox = QCheckBox("قابلِ ثبتِ سند")
        self.is_postable_checkbox.toggled.connect(self._update_dimension_checklists_visibility)
        grid.addWidget(self.is_postable_checkbox, row, 1)
        row += 1

        layout.addLayout(grid)

        self.level_preview_label = QLabel("")
        self.level_preview_label.setObjectName("sectionHint")
        layout.addWidget(self.level_preview_label)

        # طبقِ درخواستِ صریح: در فرمِ حسابِ سطحِ آخر (قابلِ ثبتِ سند)، فهرستِ
        # تفصیلی‌هایِ الزامی نمایش داده می‌شود تا مشخص شود کدام‌ها به این
        # معین مرتبط‌اند — فقط برایِ حسابِ از-قبل-ذخیره‌شده (چون ذخیره‌شان به
        # account_id نیاز دارد). طبقِ بازخوردِ صریح، همه‌یِ تفصیلی‌ها
        # (گروه‌هایِ اشخاص + نوع‌بُعدهایِ دیگر) در یک فهرستِ واحد با عنوانِ
        # فارسی می‌آیند — فقط مرکزِ هزینه/پروژه در بخشِ جداگانه‌ای‌اند، چون
        # در سند هم ستونِ اختصاصیِ خودشان را دارند (موازیِ تفصیلیِ دیگر).
        # طبقِ درخواستِ صریح: این چک‌لیست دیگر دکمه‌ی ذخیره‌یِ جداگانه‌ای
        # ندارد — با همان دکمه‌ی «ذخیره»یِ اصلیِ فرم ذخیره می‌شود (_save)،
        # و به‌جایِ اسکرولِ داخلیِ یک کادرِ کوچک، ارتفاعش با تعدادِ آیتم‌ها
        # هم‌اندازه می‌شود (_fit_list_height) تا معمولاً نیازی به اسکرول
        # نباشد؛ اگر خیلی زیاد شد، خودِ اسکرولِ بیرونیِ کلِ فرم کار می‌کند.
        self.detail_types_label = QLabel("تفصیلی‌هایِ الزامی برایِ این معین")
        self.detail_types_label.setObjectName("sectionHint")
        layout.addWidget(self.detail_types_label)
        self.detail_types_list = QListWidget()
        layout.addWidget(self.detail_types_list)

        self.cost_project_label = QLabel("مرکزِ هزینه و پروژه (ستونِ مجزا در سند)")
        self.cost_project_label.setObjectName("sectionHint")
        layout.addWidget(self.cost_project_label)
        self.cost_project_list = QListWidget()
        layout.addWidget(self.cost_project_list)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

        layout.addStretch(1)

        self.set_field_help([
            (
                self.parent_combo,
                "اگر این حساب زیرمجموعه‌یِ یک حسابِ دیگر است، والدش را این‌جا انتخاب کنید. "
                "بدونِ والد یعنی «گروه» است، یعنی سطحِ ۱. "
                "ماهیت، دسته، نوعِ حساب، بخشِ وجوهِ نقد و طبقه‌یِ نقدینگی از والد به‌ارث می‌رسند.",
            ),
            (
                self.segment_code_field,
                "فقط کدِ همین سطح را بنویسید، نه کدِ کامل. کدِ کامل خودش از کدِ والد + این کد ساخته می‌شود. "
                "مثلاً اگر گروه «۱» باشد و این کل «۰۱» بگیرد، کدِ کاملش «۱-۰۱» می‌شود.",
            ),
            (self.name_field, "نامی که در فهرستِ حساب‌ها، سندها و گزارش‌ها نشان داده می‌شود."),
            (
                self.nature_combo,
                "ماهیت یعنی این حساب معمولاً با بدهکار زیاد می‌شود یا بستانکار. "
                "«بدهکار» برایِ دارایی‌ها و هزینه‌هاست. «بستانکار» برایِ بدهی‌ها، سرمایه و درآمد است. "
                "«دوطرفه» برایِ حساب‌هایی مثلِ صندوق و بانک است که هردو طرف زیاد می‌شوند.",
            ),
            (
                self.category_combo,
                "این حساب به کدام دسته‌یِ اصلیِ حسابداری تعلق دارد؟ دارایی، بدهی، حقوقِ صاحبانِ سهام، درآمد یا هزینه. "
                "همین انتخاب مشخص می‌کند حساب در ترازنامه بیاید یا در صورتِ سود و زیان.",
            ),
            (
                self.account_type_combo,
                "«ترازنامه‌ای» یعنی مانده‌اش تا آخرِ عمرِ شرکت می‌ماند، مثلِ دارایی و بدهی. در ترازنامه می‌آید. "
                "«موقت» یعنی هر دوره از نو شروع می‌شود، مثلِ درآمد و هزینه. در صورتِ سود و زیان می‌آید.",
            ),
            (
                self.cash_flow_section_combo,
                "این حساب در کدام بخشِ صورتِ گردشِ وجوهِ نقد می‌آید؟ "
                "«عملیاتی» یعنی فعالیتِ روزمره. «سرمایه‌گذاری» یعنی خرید یا فروشِ دارایی‌هایِ ثابت. "
                "«تامینِ مالی» یعنی وام یا سرمایه. این فیلد اختیاری است؛ اگر مطمئن نیستید خالی بگذارید.",
            ),
            (
                self.liquidity_class_combo,
                "این فیلد برایِ محاسبه‌یِ نسبتِ جاری و آنی در گزارشِ نسبت‌هایِ مالی است. "
                "«جاری» یعنی حدودِ یک سالِ دیگر نقد می‌شود، مثلِ صندوق و بانک و دریافتنی/پرداختنی. "
                "«جاری (موجودی)» فقط برایِ حساب‌هایِ موجودیِ کالاست. «غیرِجاری» یعنی بلندمدت است. اختیاری است.",
            ),
            (
                self.is_postable_checkbox,
                "فقط حساب‌هایِ سطحِ معین (آخرین سطح) می‌توانند رویشان سند ثبت شود. "
                "گروه و کل فقط برایِ دسته‌بندی و جمعِ حساب‌هایِ زیرشان به‌کار می‌روند.",
            ),
        ])

        scroll.setWidget(panel)

        wrapper = QWidget()
        wrapper.setObjectName("card")
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(0)
        wrapper_layout.addWidget(scroll, stretch=1)

        footer = QWidget()
        footer.setObjectName("formFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(18, 12, 18, 14)

        self.save_button = QPushButton("ذخیره")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save)
        footer_layout.addWidget(self.save_button)

        cancel_button = QPushButton("انصراف")
        cancel_button.setObjectName("flatButton")
        cancel_button.clicked.connect(self._reset_form)
        footer_layout.addWidget(cancel_button)

        self.delete_button = QPushButton("حذف")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self._delete)
        self.delete_button.setVisible(False)
        footer_layout.addWidget(self.delete_button)

        footer_layout.addStretch(1)
        wrapper_layout.addWidget(footer)

        return wrapper

    # --- بارگذاری/فیلتر --------------------------------------------------
    def refresh(self) -> None:
        self._reset_form()
        company_id = self._company_id()
        self._rows = coa_service.list_accounts(company_id) if company_id is not None else []
        self._reload_parent_options()
        self._apply_filter()

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    # --- خروجیِ اکسل/چاپ (طبقِ درخواستِ صریح: بکاپ/انتقالِ کدینگ به
    # دیتابیسِ جدید) ------------------------------------------------------
    _EXPORT_HEADERS = [
        "کدِ کاملِ حساب (مثلِ 1-01-001)", "نام", "ماهیت (فقط سطحِ گروه: بدهکار/بستانکار/دوطرفه)",
        "دسته (فقط سطحِ گروه)", "نوعِ حساب (فقط سطحِ گروه)", "قابلِ ثبتِ سند؟ (بله/خیر)", "سطح",
    ]

    def _export_rows(self) -> tuple[list[str], list[list], list]:
        nature_label = dict(_NATURE_OPTIONS)
        category_label = dict(_CATEGORY_OPTIONS)
        account_type_label = dict(_ACCOUNT_TYPE_OPTIONS)
        table_rows = [
            [
                r.full_code, r.name,
                nature_label.get(r.nature_code, r.nature_code),
                category_label.get(r.category_code, r.category_code),
                account_type_label.get(r.account_type_code, r.account_type_code),
                "بله" if r.is_postable else "خیر",
                r.account_level,
            ]
            for r in self._rows
        ]
        return list(self._EXPORT_HEADERS), table_rows, []

    def _export_kwargs(self) -> dict:
        return {
            "company_name": session.current_company.display_name if session.current_company else "",
            "report_date": numerals.format_jalali_date(datetime.date.today()),
        }

    def _on_print(self) -> None:
        headers, rows, footer = self._export_rows()
        report_export.print_report(self, "کدینگِ حساب‌ها", headers, rows, footer, **self._export_kwargs())

    def _on_export_pdf(self) -> None:
        headers, rows, footer = self._export_rows()
        report_export.export_report_pdf(self, "کدینگِ حساب‌ها", headers, rows, footer, **self._export_kwargs())

    def _on_export_excel(self) -> None:
        _headers, rows, _footer = self._export_rows()
        report_export.export_plain_excel(self, "کدینگِ حساب‌ها", self._EXPORT_HEADERS, rows)

    def _on_import_excel(self) -> None:
        """طبقِ درخواستِ صریح: ایمپورتِ کدینگِ حساب‌ها از اکسل — هم‌الگو با
        ایمپورتِ ردیف‌هایِ سند در journal_entry.py (همان دیالوگِ تناظرِ
        ستون‌ها، از excel_import.py). ردیف‌ها بر اساسِ تعدادِ بخش‌هایِ
        full_code (گروه قبل از کل، کل قبل از معین) مرتب می‌شوند تا والد
        همیشه پیش از فرزند ساخته شده باشد."""
        company_id = self._company_id()
        if company_id is None:
            self.status_label.setText("ابتدا یک شرکت را انتخاب کنید.")
            return
        path, _filter = QFileDialog.getOpenFileName(self, "انتخابِ فایلِ اکسل", "", "Excel Files (*.xlsx)")
        if not path:
            return
        rows = read_excel_rows(self, path)
        if rows is None:
            return

        dialog = ExcelColumnMappingDialog(
            _COA_IMPORT_TARGET_FIELDS,
            _COA_IMPORT_GUESS_KEYWORDS,
            rows[0],
            self,
            title="ایمپورتِ کدینگِ حساب‌ها از اکسل — تناظرِ ستون‌ها",
        )
        if dialog.exec() != QDialog.Accepted:
            return
        mapping = dialog.mapping()
        data_rows = rows[1:] if dialog.skip_header_row() else rows

        def cell(row: tuple, field: str) -> str:
            idx = mapping.get(field)
            if idx is None or idx >= len(row):
                return ""
            value = row[idx]
            return str(value).strip() if value is not None else ""

        nature_by_label = {label: code for code, label in _NATURE_OPTIONS}
        nature_by_label.update({code: code for code, _label in _NATURE_OPTIONS})
        category_by_label = {label: code for code, label in _CATEGORY_OPTIONS}
        category_by_label.update({code: code for code, _label in _CATEGORY_OPTIONS})
        account_type_by_label = {label: code for code, label in _ACCOUNT_TYPE_OPTIONS}
        account_type_by_label.update({code: code for code, _label in _ACCOUNT_TYPE_OPTIONS})

        existing_by_full_code = {a.full_code: a for a in coa_service.list_accounts(company_id)}
        language_id = self._current_language_id()
        user_id = session.current_user.user_id if session.current_user else None

        parsed_rows = []
        errors: list[str] = []
        for offset, row in enumerate(data_rows):
            excel_row_no = offset + (2 if dialog.skip_header_row() else 1)
            full_code = cell(row, "full_code")
            name = cell(row, "name")
            if not full_code or not name:
                errors.append(f"ردیفِ {excel_row_no}: کدِ کامل یا نام خالی است.")
                continue
            parsed_rows.append((excel_row_no, full_code, name, row))

        # مرتب‌سازیِ بر اساسِ عمق (تعدادِ خط‌تیره) تا والد همیشه پیش از
        # فرزند پردازش شود — بدونِ این، وارداتِ یک فایلِ تخت (بدونِ ترتیبِ
        # خاص) می‌تواند به خطایِ کاذبِ «والد پیدا نشد» بینجامد.
        parsed_rows.sort(key=lambda item: item[1].count("-"))

        created_count = 0
        skipped_existing = 0
        for excel_row_no, full_code, name, row in parsed_rows:
            if full_code in existing_by_full_code:
                skipped_existing += 1
                continue
            segments = full_code.split("-")
            segment_code = segments[-1].strip()
            parent_full_code = "-".join(segments[:-1]) if len(segments) > 1 else None
            parent_account = existing_by_full_code.get(parent_full_code) if parent_full_code else None
            if parent_full_code is not None and parent_account is None:
                errors.append(f"ردیفِ {excel_row_no}: والدِ «{parent_full_code}» پیدا نشد (باید پیش از فرزندانش بیاید).")
                continue

            is_group_level = parent_full_code is None
            nature_code = "DEBIT"
            category_code = "ASSET"
            account_type_code = "PERMANENT"
            if is_group_level:
                nature_text = cell(row, "nature_code")
                category_text = cell(row, "category_code")
                account_type_text = cell(row, "account_type_code")
                if not nature_text or nature_text not in nature_by_label:
                    errors.append(f"ردیفِ {excel_row_no}: ماهیت (بدهکار/بستانکار/دوطرفه) برایِ حسابِ سطحِ گروه لازم است.")
                    continue
                if not category_text or category_text not in category_by_label:
                    errors.append(f"ردیفِ {excel_row_no}: دسته‌یِ حساب برایِ حسابِ سطحِ گروه لازم است.")
                    continue
                if not account_type_text or account_type_text not in account_type_by_label:
                    errors.append(f"ردیفِ {excel_row_no}: نوعِ حساب برایِ حسابِ سطحِ گروه لازم است.")
                    continue
                nature_code = nature_by_label[nature_text]
                category_code = category_by_label[category_text]
                account_type_code = account_type_by_label[account_type_text]

            is_postable_text = cell(row, "is_postable")
            if is_postable_text:
                is_postable = is_postable_text in ("بله", "true", "True", "1", "yes")
            else:
                is_postable = len(segments) == coa_service.MAX_ACCOUNT_LEVEL

            try:
                created = coa_service.create_account(
                    company_id,
                    segment_code,
                    name,
                    nature_code,
                    category_code,
                    account_type_code,
                    is_postable,
                    language_id,
                    parent_account_id=parent_account.account_id if parent_account else None,
                    changed_by_user_id=user_id,
                )
            except ValueError as exc:
                errors.append(f"ردیفِ {excel_row_no} ({full_code}): {exc}")
                continue
            existing_by_full_code[full_code] = created
            created_count += 1

        if errors:
            preview = "\n".join(errors[:30])
            if len(errors) > 30:
                preview += f"\n… و {len(errors) - 30} موردِ دیگر."
            QMessageBox.warning(
                self,
                "خطاهایِ ایمپورت",
                f"{len(errors)} ردیف با خطا مواجه شد و وارد نشدند:\n\n{preview}\n\n"
                f"{created_count} حسابِ دیگر با موفقیت ساخته شد.",
            )
        message = f"{created_count} حسابِ تازه ساخته شد."
        if skipped_existing:
            message += f" ({skipped_existing} ردیف چون از قبل وجود داشت، رد شد.)"
        QMessageBox.information(self, "ایمپورت انجام شد", message)
        self.refresh()

    def _reload_parent_options(self) -> None:
        self._parent_options = [r for r in self._rows if r.account_level < coa_service.MAX_ACCOUNT_LEVEL]
        self.parent_combo.blockSignals(True)
        self.parent_combo.clear()
        self.parent_combo.addItem("— بدونِ والد (سطحِ گروه) —", None)
        for account in self._parent_options:
            self.parent_combo.addItem(f"{account.full_code} — {account.name}", account.account_id)
        self.parent_combo.blockSignals(False)
        self._update_level_preview()

    def _apply_filter(self) -> None:
        query = self.search_field.text().strip()
        filtered = [r for r in self._rows if not query or query in r.full_code or query in r.name]
        self.table.setRowCount(len(filtered))
        for row_index, account in enumerate(filtered):
            values = [
                account.full_code,
                account.name,
                _LEVEL_LABELS[account.account_level],
                "بله" if account.is_postable else "خیر",
                "فعال" if True else "",  # حساب‌ها فیلدِ is_active ندارند در این نسخه؛ جایگزین: قابلِ‌ثبت
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, account.account_id)
                if col_index == 1:
                    item.setForeground(_hex_to_qcolor(_LEVEL_COLORS[account.account_level]))
                self.table.setItem(row_index, col_index, item)

    def _on_row_selected(self) -> None:
        selected = self.table.selectedItems()
        if not selected:
            return
        account_id = selected[0].data(Qt.UserRole)
        row = next((r for r in self._rows if r.account_id == account_id), None)
        if row is not None:
            self._load_into_form(row)

    # --- فرم: بارگذاری/ذخیره/حذف -----------------------------------------
    def _load_into_form(self, account: coa_service.AccountRow) -> None:
        self._editing_account_id = account.account_id
        self.form_title.setText(f"ویرایشِ حساب — {account.full_code}")
        self.status_label.setText("")
        self.level_preview_label.setVisible(False)
        self.segment_code_label.setText(_SEGMENT_CODE_LABELS[account.account_level])
        self.name_label.setText(_ACCOUNT_NAME_LABELS[account.account_level])
        self.name_field.setText(account.name)
        _select_combo_value(self.nature_combo, account.nature_code)
        _select_combo_value(self.category_combo, account.category_code)
        _select_combo_value(self.account_type_combo, account.account_type_code)
        _select_combo_value(self.cash_flow_section_combo, account.cash_flow_section_code)
        _select_combo_value(self.liquidity_class_combo, account.liquidity_class_code)
        self.is_postable_checkbox.setChecked(account.is_postable)
        self.segment_code_field.setText(account.full_code.rsplit("-", 1)[-1])
        self.segment_code_field.setEnabled(False)
        self.parent_combo.setEnabled(False)
        self.delete_button.setVisible(True)

        # طبقِ درخواستِ صریح: فقط سطحِ آخر (معین) می‌تواند قابلِ ثبتِ سند
        # باشد.
        is_leaf_level = account.account_level == coa_service.MAX_ACCOUNT_LEVEL
        self.is_postable_checkbox.setEnabled(is_leaf_level)

        # طبقِ درخواستِ صریح: حسابی که سندی رویش ثبت شده، اصلاً قابلِ‌ویرایش
        # نیست.
        locked = coa_service.account_has_posted_lines(account.account_id)
        self.name_field.setEnabled(not locked)
        # طبقِ درخواستِ صریح: ماهیت/دسته/نوعِ حساب فقط رویِ حسابِ سطحِ گروه
        # قابلِ‌تغییر است — زیرشاخه (کل/معین) همیشه این سه را از والدِ
        # خودش به‌ارث می‌برد، حتی اگر سندی هم نداشته باشد.
        has_parent = account.account_level > 1
        for widget in (
            self.nature_combo,
            self.category_combo,
            self.account_type_combo,
            self.cash_flow_section_combo,
            self.liquidity_class_combo,
        ):
            widget.setEnabled(not locked and not has_parent)
        if locked:
            self.is_postable_checkbox.setEnabled(False)
        self.delete_button.setEnabled(not locked)
        # طبقِ درخواستِ صریحِ کاربر: حتی برایِ حسابِ قفل‌شده، دکمه‌یِ ذخیره
        # فعال می‌ماند — چون ذخیره‌کردنِ چک‌لیستِ تفصیلی‌هایِ الزامی (تنها
        # چیزِ باقی‌مانده‌یِ قابلِ‌تغییر) همچنان با همین دکمه انجام می‌شود.
        self.save_button.setEnabled(True)
        if locked:
            self.status_label.setObjectName("sectionHint")
            self.status_label.setStyleSheet("")
            self.status_label.setText(
                "این حساب در سندهای حسابداری استفاده شده؛ نام/ماهیت/دسته/نوع قابلِ‌ویرایش نیستند — "
                "فقط چک‌لیستِ تفصیلی‌هایِ الزامیِ زیر همچنان قابلِ‌تغییر و ذخیره است."
            )

        self._populate_dimension_checklists(account.account_id if is_leaf_level else None)
        self._update_dimension_checklists_visibility()

    def _reset_form(self) -> None:
        self._editing_account_id = None
        self.form_title.setText("حسابِ جدید")
        self.status_label.setText("")
        self.segment_code_field.clear()
        self.segment_code_field.setEnabled(True)
        self.parent_combo.setEnabled(True)
        self.parent_combo.setCurrentIndex(0)
        self.name_field.clear()
        for widget in (
            self.name_field,
            self.nature_combo,
            self.category_combo,
            self.account_type_combo,
            self.cash_flow_section_combo,
            self.liquidity_class_combo,
        ):
            widget.setEnabled(True)
        self.nature_combo.setCurrentIndex(0)
        self.category_combo.setCurrentIndex(0)
        self.account_type_combo.setCurrentIndex(0)
        self.cash_flow_section_combo.setCurrentIndex(0)
        self.liquidity_class_combo.setCurrentIndex(0)
        self.is_postable_checkbox.setEnabled(True)
        self.is_postable_checkbox.setChecked(False)
        self.delete_button.setVisible(False)
        self.delete_button.setEnabled(True)
        self.save_button.setEnabled(True)
        self.level_preview_label.setVisible(True)
        self.table.clearSelection()
        self._populate_dimension_checklists(None)
        self._update_dimension_checklists_visibility()
        # طبقِ‌بالا: اگر parent_combo از قبل هم رویِ ایندکسِ ۰ بود (مثلاً
        # درست بعدِ ویرایشِ یک حسابِ سطحِ کل/معین)، setCurrentIndex سیگنال
        # نمی‌دهد و برچسب‌هایِ کد/نامِ قدیمی می‌ماندند — این‌جا صراحتاً
        # دوباره محاسبه می‌شود.
        self._update_level_preview()

    def _update_level_preview(self) -> None:
        parent_id = self.parent_combo.currentData()
        if parent_id is None:
            level = 1
            parent = None
        else:
            parent = next((r for r in self._parent_options if r.account_id == parent_id), None)
            level = (parent.account_level + 1) if parent is not None else 1
        self.level_preview_label.setText(f"سطحِ حسابِ جدید: {_LEVEL_LABELS[level]}")
        if self._editing_account_id is None:
            self.segment_code_label.setText(_SEGMENT_CODE_LABELS[level])
            self.name_label.setText(_ACCOUNT_NAME_LABELS[level])
            is_leaf_level = level == coa_service.MAX_ACCOUNT_LEVEL
            self.is_postable_checkbox.setEnabled(is_leaf_level)
            if not is_leaf_level:
                self.is_postable_checkbox.setChecked(False)
            self._apply_nature_inheritance(parent)

    def _apply_nature_inheritance(self, parent: coa_service.AccountRow | None) -> None:
        # طبقِ درخواستِ صریح: ماهیت/دسته/نوعِ حساب فقط رویِ حسابِ سطحِ گروه
        # (بدونِ والد) قابلِ‌انتخاب است — با انتخابِ یک والد، این سه فیلد
        # از همان والد پر و غیرفعال می‌شوند تا زیردرخت همیشه با گروهِ
        # خودش هم‌خوان بماند.
        has_parent = parent is not None
        if has_parent:
            _select_combo_value(self.nature_combo, parent.nature_code)
            _select_combo_value(self.category_combo, parent.category_code)
            _select_combo_value(self.account_type_combo, parent.account_type_code)
            _select_combo_value(self.cash_flow_section_combo, parent.cash_flow_section_code)
            _select_combo_value(self.liquidity_class_combo, parent.liquidity_class_code)
        for widget in (
            self.nature_combo,
            self.category_combo,
            self.account_type_combo,
            self.cash_flow_section_combo,
            self.liquidity_class_combo,
        ):
            widget.setEnabled(not has_parent)

    # --- چک‌لیستِ تفصیلی‌هایِ الزامی -----------------------------------------
    def _update_dimension_checklists_visibility(self) -> None:
        visible = self._editing_account_id is not None and self.is_postable_checkbox.isChecked()
        for widget in (
            self.detail_types_label,
            self.detail_types_list,
            self.cost_project_label,
            self.cost_project_list,
        ):
            widget.setVisible(visible)

    @staticmethod
    def _fit_list_height(list_widget: QListWidget, *, max_height: int = 320, min_height: int = 40) -> None:
        """طبقِ درخواستِ صریح: به‌جایِ یک کادرِ کوچکِ ثابت با اسکرولِ داخلی،
        ارتفاعِ فهرست با تعدادِ آیتم‌هایش هم‌اندازه می‌شود — اسکرولِ کلِ
        فرم (که خودش از قبل در یک QScrollArea است) برایِ حالت‌هایِ خیلی
        پرتعداد کافی است."""
        count = list_widget.count()
        if count == 0:
            list_widget.setFixedHeight(min_height)
            return
        row_height = list_widget.sizeHintForRow(0)
        if row_height <= 0:
            row_height = 24
        content_height = row_height * count + 2 * list_widget.frameWidth() + 6
        list_widget.setFixedHeight(max(min_height, min(content_height, max_height)))

    def _populate_dimension_checklists(self, account_id: int | None) -> None:
        company_id = self._company_id()
        self.detail_types_list.clear()
        self.cost_project_list.clear()
        if company_id is None:
            self._fit_list_height(self.detail_types_list)
            self._fit_list_height(self.cost_project_list)
            return

        required_type_ids = set(dimensions_service.get_account_dimension_type_ids(account_id)) if account_id else set()
        required_group_ids = set(dimensions_service.get_account_person_group_ids(account_id)) if account_id else set()
        cost_project_codes = (dimensions_service.COST_CENTER_CODE, dimensions_service.PROJECT_CODE)

        # همه‌ی گروه‌هایِ اشخاص (مشتری/تامین‌کننده/پرسنل) در فهرستِ واحد،
        # چون عنوانِ فارسی از قبل دارند و ستونِ اختصاصیِ جداگانه‌ای در سند نمی‌خواهند.
        for group in dimensions_service.list_person_groups(company_id):
            item = QListWidgetItem(group.name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if group.person_group_id in required_group_ids else Qt.Unchecked)
            item.setData(Qt.UserRole, ("person", group.person_group_id))
            self.detail_types_list.addItem(item)

        for dim in dimensions_service.list_active_dimension_types(company_id):
            label = dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(dim.code, dim.code)
            checked = Qt.Checked if dim.dimension_type_id in required_type_ids else Qt.Unchecked
            if dim.code in cost_project_codes:
                item = QListWidgetItem(label)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(checked)
                item.setData(Qt.UserRole, dim.dimension_type_id)
                self.cost_project_list.addItem(item)
            else:
                item = QListWidgetItem(label)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(checked)
                item.setData(Qt.UserRole, ("dim", dim.dimension_type_id))
                self.detail_types_list.addItem(item)

        self._fit_list_height(self.detail_types_list)
        self._fit_list_height(self.cost_project_list)

    def _save_dimensions(self) -> None:
        """طبقِ درخواستِ صریح، این تابع دیگر پشتِ دکمه‌یِ جداگانه‌ای نیست —
        از _save فراخوانی می‌شود (درونِ همان try/except)، فقط وقتی
        چک‌لیست اصلاً نمایان است (یعنی حسابِ از-قبل-ذخیره‌شده‌یِ
        قابلِ‌ثبتِ سند در حالِ ویرایش است). خطا را raise می‌کند تا _save
        همان‌جا با پیامِ یکسان مدیریتش کند، نه با پیامِ جداگانه."""
        if self._editing_account_id is None or not self.is_postable_checkbox.isChecked():
            return
        company_id = self._company_id()
        if company_id is None:
            return
        dimension_type_ids = []
        person_group_ids = []
        for i in range(self.detail_types_list.count()):
            item = self.detail_types_list.item(i)
            if item.checkState() != Qt.Checked:
                continue
            kind, value = item.data(Qt.UserRole)
            if kind == "dim":
                dimension_type_ids.append(value)
            else:
                person_group_ids.append(value)
        for i in range(self.cost_project_list.count()):
            item = self.cost_project_list.item(i)
            if item.checkState() == Qt.Checked:
                dimension_type_ids.append(item.data(Qt.UserRole))
        dimensions_service.set_account_dimension_types(self._editing_account_id, company_id, dimension_type_ids)
        dimensions_service.set_account_person_groups(self._editing_account_id, company_id, person_group_ids)

    def _current_language_id(self) -> int | None:
        return session.current_company.default_language_id if session.current_company else None

    def _save(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            self.status_label.setText("ابتدا یک شرکت را انتخاب کنید.")
            return

        name = self.name_field.text().strip()
        nature_code = _combo_value(self.nature_combo)
        category_code = _combo_value(self.category_combo)
        account_type_code = _combo_value(self.account_type_combo)
        cash_flow_section_code = _combo_value(self.cash_flow_section_combo)
        liquidity_class_code = _combo_value(self.liquidity_class_combo)
        is_postable = self.is_postable_checkbox.isChecked()

        if not name:
            self.status_label.setText("نام را وارد کنید.")
            return

        created_account_id: int | None = None
        try:
            if self._editing_account_id is not None:
                # طبقِ درخواستِ صریحِ کاربر: حتی حسابی که در سندهایِ
                # حسابداری استفاده شده (و بقیه‌یِ فیلدهایش قفل است)، باید
                # بتوان تفصیلی‌هایِ الزامی‌اش را کم/زیاد کرد — این تنها
                # چیزی‌ست که ذخیره می‌شود؛ update_account (که نام/ماهیت/...
                # را عوض می‌کند) اصلاً صدا زده نمی‌شود، چون خودش برایِ
                # چنین حسابی همیشه خطا می‌دهد.
                locked = coa_service.account_has_posted_lines(self._editing_account_id)
                if not locked:
                    coa_service.update_account(
                        self._editing_account_id,
                        company_id,
                        name,
                        nature_code,
                        category_code,
                        account_type_code,
                        is_postable,
                        self._current_language_id(),
                        changed_by_user_id=session.current_user.user_id if session.current_user else None,
                        cash_flow_section_code=cash_flow_section_code,
                        liquidity_class_code=liquidity_class_code,
                    )
                # طبقِ درخواستِ صریح: دیگر دکمه‌ی ذخیره‌یِ جداگانه‌ای برایِ
                # نوع‌هایِ تفصیلی نیست — همین‌جا با همان «ذخیره»یِ اصلی
                # ذخیره می‌شود (اگر چک‌لیست اصلاً نمایان باشد).
                self._save_dimensions()
            else:
                segment_code = self.segment_code_field.text().strip()
                if not segment_code:
                    self.status_label.setText("کدِ بخش را وارد کنید.")
                    return
                created = coa_service.create_account(
                    company_id,
                    segment_code,
                    name,
                    nature_code,
                    category_code,
                    account_type_code,
                    is_postable,
                    self._current_language_id(),
                    parent_account_id=self.parent_combo.currentData(),
                    changed_by_user_id=session.current_user.user_id if session.current_user else None,
                    cash_flow_section_code=cash_flow_section_code,
                    liquidity_class_code=liquidity_class_code,
                )
                created_account_id = created.account_id
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return

        edited_account_id = self._editing_account_id if created_account_id is None else None
        self.refresh()
        if edited_account_id is not None:
            # طبقِ همان اصلاح: بعدِ ذخیره‌یِ موفقِ ویرایشِ یک حسابِ
            # از-قبل-موجود (شاملِ حالتِ «فقط تفصیلی‌هایِ حسابِ قفل‌شده»)،
            # فرم باید همچنان رویِ همان حساب بماند — نه به «حسابِ جدید»
            # خالی برگردد — تا کاربر نتیجه‌یِ ذخیره را همان‌جا ببیند.
            edited_row = next((r for r in self._rows if r.account_id == edited_account_id), None)
            if edited_row is not None:
                self._load_into_form(edited_row)
                for row_index in range(self.table.rowCount()):
                    if self.table.item(row_index, 0).data(Qt.UserRole) == edited_account_id:
                        self.table.blockSignals(True)
                        self.table.selectRow(row_index)
                        self.table.blockSignals(False)
                        break
                theme.set_status_label(self.status_label, "ذخیره شد.", ok=True)
        if created_account_id is not None:
            # طبقِ اصلاحِ ریشه‌ای: چک‌لیستِ گروه‌هایِ شخصی/بُعدهایِ الزامی فقط
            # برایِ حسابِ در-حالِ-ویرایش نمایان می‌شود (_update_dimension_checklists_visibility)
            # — بدونِ این، بلافاصله بعدِ ساختنِ یک معینِ تازه، امکانِ
            # محدودکردنش به یک گروهِ شخص (مثلاً «فقط مشتری») در همان‌جا
            # اصلاً وجود نداشت؛ کاربر باید بعداً دوباره پیدایش می‌کرد و
            # ویرایش می‌زد که به‌سادگی فراموش می‌شد و محدودیت هرگز ذخیره
            # نمی‌شد. حالا حسابِ تازه‌ساخته‌شده خودکار در همان فرم برایِ
            # ویرایش انتخاب می‌شود.
            new_row = next((r for r in self._rows if r.account_id == created_account_id), None)
            if new_row is not None:
                self._load_into_form(new_row)
                for row_index in range(self.table.rowCount()):
                    if self.table.item(row_index, 0).data(Qt.UserRole) == created_account_id:
                        self.table.blockSignals(True)
                        self.table.selectRow(row_index)
                        self.table.blockSignals(False)
                        break

    def _delete(self) -> None:
        if self._editing_account_id is None:
            return
        company_id = self._company_id()
        if company_id is None:
            return
        confirm = QMessageBox.question(
            self, "حذفِ حساب", "این حساب حذف شود؟", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            coa_service.delete_account(
                self._editing_account_id,
                company_id,
                changed_by_user_id=session.current_user.user_id if session.current_user else None,
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()


def _hex_to_qcolor(hex_code: str):
    from PySide6.QtGui import QColor

    return QColor(hex_code)
