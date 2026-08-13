"""فرمِ واحدِ ثبتِ همه‌ی حساب‌هایِ تفصیلی — معادلِ Qt برایِ detail_dimensions.py/.kv.

طبقِ درخواستِ صریح: «تعریفِ تفصیلی‌ها همه در یک فرم باشد و از هدرِ فرم
نوعِ تفصیلی انتخاب و تعریف شود، منویِ جداگانه نداشته باشیم» — این صفحه
قبلاً فقط گروه‌هایِ «ساده» (بدونِ صفحه‌ی اختصاصی) را پوشش می‌داد؛ حالا
همان یک فرم، با یک کمبویِ سرستون («گروه»)، هرسه نوعِ زیر را یک‌جا پوشش
می‌دهد:
  ۱) گروه‌هایِ اشخاص (مشتری/تامین‌کننده/پرسنل) — فیلدهایِ هاردکدِ
     اختصاصیِ خودشان (کدِ اقتصادی، شناسه‌یِ ملی، ...) را دارند، چون در
     جدولِ SQLِ جداگانه‌ای (customer_details/...) ذخیره می‌شوند.
  ۲) ۷ نوعِ «فرمِ خاص» (کالا/دارایی‌ثابت/بانک/صندوق/تنخواه/مرکزِهزینه/
     پروژه) که قبلاً صفحه‌ی اختصاصیِ خودشان را داشتند (specialized_dimensions.py) —
     هیچ فیلدِ هاردکدی ندارند، فقط با فیلدهایِ اختصاصیِ پیکربندی‌شده کار می‌کنند.
  ۳) گروه‌هایِ «ساده»یِ تعریف‌شده‌یِ کاربر — مثلِ قبل.

هرسه نوع از یک زیرساختِ مشترک (سلسله‌مراتب/کدِ پیشنهادی/فیلدهایِ
اختصاصیِ پیکربندی‌شده) استفاده می‌کنند؛ فرقشان فقط در این است که
گروه‌هایِ اشخاص یک ردیفِ اضافه از فیلدهایِ هاردکد هم دارند و با
تابع‌هایِ سرویسِ اختصاصیِ خودشان (create_customer/...) ذخیره می‌شوند."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFrame,
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
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals
from peecha import session
from peecha.services import commercial_partners as partners_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import hr as hr_service
from peecha.services import payroll as payroll_service
from peecha.services import treasury as treasury_service
from peecha.ui.widgets import FieldHelpMixin, JalaliDateEdit, PersianDigitLineEdit

# طبقِ درخواستِ صریح («کد باید اولین ستون از سمتِ راست باشد، در همه‌ی
# فرم‌هایِ این‌شکلی») — هم‌الگو با ترتیبِ ستون‌هایِ کدینگِ حساب‌ها.
_COLUMNS = ["کدِ کامل", "نام", "سطح", "وضعیت"]
# طبقِ یکپارچه‌سازیِ «تعریفِ کارمند فقط از طریقِ تفصیلی»: فهرستِ کارمندان
# (که قبلاً در صفحه‌یِ جداگانه‌یِ «تعریفِ کارکنان» این ستون‌ها را داشت)
# باید همین‌جا هم دیده شود، پس فقط برایِ گروهِ PERSONNEL این ۴ ستونِ
# اضافه به ستون‌هایِ عمومی افزوده می‌شود.
_PERSONNEL_EXTRA_COLUMNS = ["واحدِ سازمانی", "پست", "حقوقِ پایه", "وضعیتِ استخدام"]
# طبقِ گزارشِ صریح («نوعِ حساب جاری/پس‌انداز») — گزینه‌هایِ ثابتِ کیندِ
# «account_type»یِ فیلدهایِ اختصاصی (فقط برایِ BANK_ACCOUNT کاربرد دارد).
_ACCOUNT_TYPE_OPTIONS = ["جاری", "پس‌انداز"]
_EMPLOYEE_STATUS_LABELS = {"ACTIVE": "فعال", "ON_LEAVE": "مرخصی", "TERMINATED": "پایان‌یافته"}
# طبقِ یکپارچه‌سازیِ مشتری/تامین‌کننده در فرمِ تفصیلی (مرحلهٔ بازرگانی):
# وضعیتِ گردشِ کارِ تاییدِ اعتباری (comm.customer_profiles/supplier_profiles.status_code).
_PARTNER_STATUS_LABELS = {
    "DRAFT": "پیش‌نویس", "PENDING_APPROVAL": "درانتظارِ تاییدِ اعتباری", "ACTIVE": "فعال",
    "SUSPENDED": "معلق", "BLACKLISTED": "لیستِ سیاه", "ON_HOLD": "متوقف", "DISQUALIFIED": "ردِ صلاحیت",
    "INACTIVE": "غیرفعال",
}

_PERSON_FIELD_LABELS = {
    "economic_code": "کدِ اقتصادی",
    "national_id": "شناسه/کدِ ملی",
    "phone": "تلفن",
    "mobile": "موبایل",
    "address": "آدرس",
    "credit_limit": "سقفِ اعتبار",
    "notes": "یادداشت",
    "bank_account_no": "شماره‌حسابِ بانکی",
    "personnel_no": "شماره‌ی پرسنلی",
    "position_title": "سمت",
    "hire_date": "تاریخِ استخدام",
    "org_unit_id": "واحدِ سازمانی",
    "position_id": "پست",
    "employment_type_lookup_id": "نوعِ استخدام",
    "base_salary": "حقوقِ پایه (ریال)",
    "customer_group_id": "گروهِ مشتری",
    "supplier_group_id": "گروهِ تامین‌کننده",
    "default_price_list_id": "فهرستِ قیمتِ پیش‌فرض",
    "default_channel_code": "کانالِ پیش‌فرض",
    "payment_term_days": "مهلتِ پرداخت (روز)",
    "credit_limit_amount": "سقفِ اعتبار (بازرگانی)",
    "is_tax_exempt": "معافِ مالیاتی",
}

# طبقِ یکپارچه‌سازیِ «تعریفِ کارمند فقط از طریقِ تفصیلی»: این کمبوها
# نیاز به company_id دارند، پس بر خلافِ فیلدهایِ متنی/تاریخ/عددی، توسطِ
# _render_person_fields مستقیم (نه _make_field_widget) پر می‌شوند. کلیدِ
# گروه‌محور (group_code, field_key) برایِ فیلدهایی که در چند گروه با
# منبعِ داده‌یِ متفاوت تکرار می‌شوند (مثلِ default_price_list_id).
_PERSON_COMBO_LOADERS = {
    "org_unit_id": lambda company_id: [(u.org_unit_id, f"{u.code} — {u.name}") for u in hr_service.list_org_units(company_id)],
    "position_id": lambda company_id: [(p.position_id, f"{p.code} — {p.title}") for p in hr_service.list_positions(company_id)],
    "employment_type_lookup_id": lambda company_id: [
        (t.lookup_value_id, t.name) for t in hr_service.list_lookup_values(company_id, "EMPLOYMENT_TYPE")
    ],
    (dimensions_service.CUSTOMER_GROUP_CODE, "customer_group_id"): lambda company_id: [
        (g.group_id, g.name) for g in partners_service.list_customer_groups(company_id)
    ],
    (dimensions_service.CUSTOMER_GROUP_CODE, "default_price_list_id"): lambda company_id: [
        (pl.price_list_id, f"{pl.code} — {pl.name}") for pl in pricing_service.list_price_lists(company_id, "SALES")
    ],
    (dimensions_service.CUSTOMER_GROUP_CODE, "default_channel_code"): lambda company_id: [
        (ch.channel_code, f"{ch.channel_code} — {ch.name}") for ch in pricing_service.list_channels(company_id)
    ],
    (dimensions_service.SUPPLIER_GROUP_CODE, "supplier_group_id"): lambda company_id: [
        (g.group_id, g.name) for g in partners_service.list_supplier_groups(company_id)
    ],
    (dimensions_service.SUPPLIER_GROUP_CODE, "default_price_list_id"): lambda company_id: [
        (pl.price_list_id, f"{pl.code} — {pl.name}") for pl in pricing_service.list_price_lists(company_id, "PURCHASE")
    ],
}

# طبقِ گزارشِ صریح («وقتی گروهِ پرسنل چند سطح دارد، فقط آخرین سطح باید
# شغل/سازمان/رده‌یِ شغلی/حقوقِ پایه بپرسد — سطوحِ بالاتر صرفاً گره‌هایِ
# گروه‌بندی‌اند»): این فیلدها فقط در سطحِ آخرِ گروه نمایش داده می‌شوند؛
# باید با _PERSONNEL_HR_FIELD_KEYSِ hr.py هم‌گام بماند.
_LEAF_ONLY_FIELD_KEYS = {"org_unit_id", "position_id", "employment_type_lookup_id", "base_salary"}

# طبقِ همان الگویِ قبلی در person_group_screens.py — این سه گروه علاوه بر
# فیلدهایِ اختصاصیِ عمومی/قابلِ‌پیکربندی، یک دسته فیلدِ هاردکدِ ثابت هم
# دارند چون در جدولِ SQLِ جداگانه‌ای ذخیره می‌شوند (نه extra_fields JSONB).
_PERSON_GROUP_META = {
    # طبقِ یکپارچه‌سازیِ مشتری/تامین‌کننده با مرحلهٔ مدیریتِ بازرگانی —
    # فیلدِ قدیمیِ آزادِ «credit_limit» (که هیچ‌جا واقعاً مصرف نمی‌شد) با
    # فیلدهایِ واقعیِ comm.customer_profiles جایگزین شد (که موتورِ
    # commercial_credit از رویِ آن‌ها مواجههٔ اعتباری حساب می‌کند)؛
    # توابعِ list/create/update/delete هم به جایِ dimensions_service.*_customer
    # از commercial_partners می‌آیند که هم‌زمان تفصیلی و comm.customer_profiles
    # را می‌سازند/به‌روزرسانی می‌کنند.
    dimensions_service.CUSTOMER_GROUP_CODE: {
        "field_specs": (
            ("economic_code", "text"), ("national_id", "text"), ("phone", "text"), ("mobile", "text"),
            ("address", "text"), ("customer_group_id", "combo"), ("default_price_list_id", "combo"),
            ("default_channel_code", "combo"), ("payment_term_days", "decimal"), ("credit_limit_amount", "decimal"),
            ("is_tax_exempt", "bool"), ("notes", "text"),
        ),
        "list_fn": partners_service.list_customer_detail_accounts,
        "create_fn": partners_service.create_customer_detail_account,
        "update_fn": partners_service.update_customer_detail_account,
        "delete_fn": partners_service.delete_customer_detail_account,
    },
    dimensions_service.SUPPLIER_GROUP_CODE: {
        "field_specs": (
            ("economic_code", "text"), ("national_id", "text"), ("phone", "text"), ("mobile", "text"),
            ("address", "text"), ("bank_account_no", "text"), ("supplier_group_id", "combo"),
            ("default_price_list_id", "combo"), ("payment_term_days", "decimal"), ("credit_limit_amount", "decimal"),
            ("notes", "text"),
        ),
        "list_fn": partners_service.list_supplier_detail_accounts,
        "create_fn": partners_service.create_supplier_detail_account,
        "update_fn": partners_service.update_supplier_detail_account,
        "delete_fn": partners_service.delete_supplier_detail_account,
    },
    dimensions_service.PERSONNEL_GROUP_CODE: {
        # طبقِ درخواستِ صریح («تعریفِ کارمند فقط از طریقِ تفصیلی»): این
        # فیلدها دیگر فقط PersonnelDetail (national_id/phone/...) نیستند —
        # فیلدهایِ قراردادِ استخدام (واحدِ سازمانی/پست/نوعِ استخدام/حقوقِ
        # پایه) هم اضافه شده‌اند؛ توابعِ list/create/update/delete هم به
        # جایِ dimensions_service.*_personnel از hr_service می‌آیند که
        # هم‌زمان تفصیلی و hr.employees/EmploymentContract را می‌سازند/
        # به‌روزرسانی می‌کنند. «سمت» (متنِ آزاد) و «شماره‌یِ پرسنلی» (که
        # همیشه برابرِ کدِ حساب می‌شد) از فیلدها حذف شدند — اولی جایِ خودش
        # را به کمبویِ واقعیِ پست داده، دومی دیگر لازم نیست.
        "field_specs": (
            ("national_id", "text"), ("hire_date", "date"),
            ("org_unit_id", "combo"), ("position_id", "combo"),
            ("employment_type_lookup_id", "combo"), ("base_salary", "decimal"),
            ("phone", "text"), ("mobile", "text"),
            ("bank_account_no", "text"), ("notes", "text"),
        ),
        "list_fn": hr_service.list_personnel_detail_accounts,
        "create_fn": hr_service.create_personnel_detail_account,
        "update_fn": hr_service.update_personnel_detail_account,
        "delete_fn": hr_service.delete_personnel_detail_account,
    },
}


def _find_combo_index(combo: QComboBox, data: tuple[str, int | str] | None) -> int:
    """جایگزینِ combo.findData(...) — طبقِ آزمایشِ عملی، findDataیِ Qt برایِ
    داده‌یِ نوعِ tuple (که یک شیءِ خامِ پایتون است، نه نوعِ بومیِ Qt) رفتارِ
    قابلِ‌اتکایی ندارد، هرچند itemData(i) خودش مقدارِ درست/قابلِ‌مقایسه
    برمی‌گرداند؛ پس این‌جا با یک پیمایشِ دستی همان مقایسه را انجام می‌دهیم."""
    for i in range(combo.count()):
        if combo.itemData(i) == data:
            return i
    return -1


def _make_field_widget(kind: str) -> QWidget:
    if kind == "decimal":
        widget = QDoubleSpinBox()
        widget.setRange(0, 10_000_000_000)
        widget.setDecimals(2)
        return widget
    if kind == "date":
        widget = QDateEdit()
        widget.setCalendarPopup(True)
        widget.setSpecialValueText(" ")
        widget.setDate(widget.minimumDate())
        return widget
    if kind == "bool":
        return QCheckBox()
    return PersianDigitLineEdit()


class DetailDimensionsScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        # combo_data ذخیره‌شده رویِ هر آیتمِ group_combo یکی از این دو شکل است:
        #   ("dim", dimension_type_id)   -> گروهِ ساده یا یکی از ۷ نوعِ خاص
        #   ("person", group_code)       -> CUSTOMER/SUPPLIER/PERSONNEL
        self._person_groups: list[dimensions_service.PersonGroupRow] = []
        self._types: list[dimensions_service.DimensionTypeRow] = []
        self._selected: tuple[str, int | str] | None = None
        self._accounts_by_id: dict[int, dimensions_service.DetailAccountRow] = {}
        self._person_rows_by_id: dict[int, dict] = {}
        self._editing_account_id: int | None = None
        self._extra_widgets: dict[str, tuple[QWidget, str]] = {}
        self._person_field_widgets: dict[str, QWidget] = {}
        self._current_max_level_no: int = 1
        # طبقِ درخواستِ صریح («حکمِ حقوق داخلِ فرمِ تفصیلیِ پرسنل»): مزایا/
        # کسوراتِ اختصاصیِ کارمندِ درحالِ‌ویرایش (payroll.EmployeePayComponent).
        self._current_employee_id: int | None = None
        self._pay_components: list[payroll_service.EmployeePayComponentRow] = []
        self._editing_pay_component_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_account_panel(), stretch=2)

        self.set_field_help([
            (
                self.group_combo,
                "نوعِ حسابِ تفصیلی‌ای که می‌خواهید بسازید یا ویرایش کنید — مشتری/تامین‌کننده/پرسنل، "
                "کالا/بانک/صندوق/... یا یک گروهِ سفارشی. ساختنِ گروهِ تازه و تنظیمِ سطح/فیلدهایش در "
                "«پیکربندیِ گروه‌هایِ تفصیلی» انجام می‌شود، نه این‌جا.",
            ),
            (
                self.show_all_levels_checkbox,
                "به‌طورِ پیش‌فرض فقط آخرین سطح (برگ‌ها) نشان داده می‌شود. با این تیک، کلِ درختِ والد و فرزند را می‌بینید.",
            ),
            (
                self.parent_combo,
                "اگر این حساب زیرمجموعه‌یِ یک حسابِ دیگر است، آن را این‌جا انتخاب کنید. "
                "بدونِ والد یعنی این حساب در سطحِ اول قرار می‌گیرد.",
            ),
            (
                self.account_code_field,
                "کدِ این حساب. برنامه بعدِ انتخابِ والد یک کدِ پیشنهادی خودش پر می‌کند، ولی می‌توانید تغییرش دهید.",
            ),
            (self.account_name_field, "نامی که در فهرست‌ها و سندها برایِ این حساب نشان داده می‌شود."),
            (
                self.account_active_checkbox,
                "حساب‌هایِ غیرِفعال از فهرستِ انتخاب در سندها کنار گذاشته می‌شوند، ولی سوابقِ قبلی‌شان می‌ماند.",
            ),
        ])

    # --- ستونِ چپ: انتخابِ گروه + فهرستِ حساب‌ها -----------------------------
    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("تعریفِ حساب‌هایِ تفصیلی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "ساختِ گروهِ تازه و تنظیمِ تعدادِ رقم/بازه/فیلدِ اختصاصی در «پیکربندیِ گروه‌هایِ تفصیلی» انجام می‌شود."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(QLabel("گروه"))
        self.group_combo = QComboBox()
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)
        layout.addWidget(self.group_combo)

        self.show_all_levels_checkbox = QCheckBox("نمایشِ همه‌یِ سطوح")
        self.show_all_levels_checkbox.toggled.connect(lambda _checked: self._rebuild_accounts_tree())
        layout.addWidget(self.show_all_levels_checkbox)

        self.accounts_table = QTreeWidget()
        self.accounts_table.setColumnCount(len(_COLUMNS))
        self.accounts_table.setHeaderLabels(_COLUMNS)
        self.accounts_table.itemClicked.connect(self._on_account_item_clicked)
        layout.addWidget(self.accounts_table, stretch=1)

        return panel

    # --- ستونِ راست: فرمِ حسابِ تفصیلی ---------------------------------------
    def _build_account_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.account_form_title = QLabel("حسابِ تفصیلیِ جدید")
        self.account_form_title.setObjectName("pageTitle")
        layout.addWidget(self.account_form_title)

        grid = QGridLayout()
        grid.addWidget(QLabel("والد"), 0, 0)
        self.parent_combo = QComboBox()
        self.parent_combo.currentIndexChanged.connect(self._on_parent_combo_changed)
        grid.addWidget(self.parent_combo, 0, 1)

        grid.addWidget(QLabel("کد"), 1, 0)
        self.account_code_field = QLineEdit()
        grid.addWidget(self.account_code_field, 1, 1)

        grid.addWidget(QLabel("نام"), 2, 0)
        self.account_name_field = QLineEdit()
        grid.addWidget(self.account_name_field, 2, 1)

        self.account_active_checkbox = QCheckBox("فعال")
        self.account_active_checkbox.setChecked(True)
        grid.addWidget(self.account_active_checkbox, 3, 1)
        layout.addLayout(grid)

        # طبقِ درخواستِ صریح: گروه‌هایِ اشخاص (مشتری/تامین‌کننده/پرسنل)
        # فیلدهایِ هاردکدِ اختصاصیِ خودشان را هم دارند (چون در جدولِ
        # جداگانه‌یِ SQL ذخیره می‌شوند) — این ردیف فقط وقتی آن گروه‌ها
        # انتخاب شده باشند نمایان می‌شود.
        self.person_fields_label = QLabel("فیلدهایِ اختصاصیِ این گروه")
        layout.addWidget(self.person_fields_label)
        # طبقِ یکپارچه‌سازیِ مشتری/تامین‌کننده: وضعیتِ گردشِ کارِ تاییدِ
        # اعتباری (comm.customer_profiles/supplier_profiles.status_code) —
        # فقط برایِ همین دو گروه نمایان می‌شود.
        self.partner_status_label = QLabel("")
        self.partner_status_label.setVisible(False)
        layout.addWidget(self.partner_status_label)
        self.person_fields_grid = QGridLayout()
        person_fields_widget = QWidget()
        person_fields_widget.setLayout(self.person_fields_grid)
        layout.addWidget(person_fields_widget)

        self.extra_fields_label = QLabel("فیلدهایِ اختصاصیِ تعریف‌شده")
        layout.addWidget(self.extra_fields_label)
        self.extra_fields_container = QVBoxLayout()
        extra_widget = QWidget()
        extra_widget.setLayout(self.extra_fields_container)
        layout.addWidget(extra_widget)

        layout.addWidget(self._build_pay_components_section())

        self.account_status_label = QLabel("")
        self.account_status_label.setObjectName("statusError")
        self.account_status_label.setWordWrap(True)
        layout.addWidget(self.account_status_label)

        layout.addStretch(1)
        scroll.setWidget(panel)

        # باگِ واقعیِ گزارش‌شده (هم‌الگو با chart_of_accounts.py): دکمه‌ها
        # دیگر داخلِ محتوایِ اسکرول‌شونده نیستند — نوارِ ثابتِ پایینی.
        wrapper = QWidget()
        wrapper.setObjectName("card")
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(0)
        wrapper_layout.addWidget(scroll, stretch=1)

        footer = QWidget()
        footer.setObjectName("formFooter")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(18, 12, 18, 14)
        self.save_button = QPushButton("ذخیره")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save_account)
        buttons.addWidget(self.save_button)
        cancel_button = QPushButton("انصراف")
        cancel_button.setObjectName("flatButton")
        cancel_button.clicked.connect(self._cancel_account_edit)
        buttons.addWidget(cancel_button)
        self.delete_button = QPushButton("حذف")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self._delete_account)
        self.delete_button.setVisible(False)
        buttons.addWidget(self.delete_button)
        self.terminate_employee_button = QPushButton("ثبتِ ترکِ کار")
        self.terminate_employee_button.setObjectName("dangerButton")
        self.terminate_employee_button.clicked.connect(self._terminate_employee)
        self.terminate_employee_button.setVisible(False)
        buttons.addWidget(self.terminate_employee_button)
        self.approve_partner_button = QPushButton("تاییدِ اعتباری")
        self.approve_partner_button.setObjectName("primaryButton")
        self.approve_partner_button.clicked.connect(self._approve_partner)
        self.approve_partner_button.setVisible(False)
        buttons.addWidget(self.approve_partner_button)
        buttons.addStretch(1)
        wrapper_layout.addWidget(footer)

        self.account_panel = wrapper
        wrapper.setEnabled(False)
        return wrapper

    # --- حکمِ حقوق (فقط برایِ گروهِ پرسنل، رویِ کارمندِ ازپیش‌ذخیره‌شده) -----
    def _build_pay_components_section(self) -> QWidget:
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(QLabel("حکمِ حقوق — مزایا/کسوراتِ اختصاصیِ این کارمند"))

        self.pay_components_table = QTableWidget(0, 4)
        self.pay_components_table.setHorizontalHeaderLabels(["آیتم", "مبلغ", "از تاریخ", "تا تاریخ"])
        self.pay_components_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pay_components_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.pay_components_table.verticalHeader().setVisible(False)
        self.pay_components_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.pay_components_table.cellClicked.connect(self._on_pay_component_row_clicked)
        self.pay_components_table.setMaximumHeight(140)
        layout.addWidget(self.pay_components_table)

        form_row = QHBoxLayout()
        self.pay_component_item_combo = QComboBox()
        form_row.addWidget(self.pay_component_item_combo, stretch=2)
        self.pay_component_amount_field = QDoubleSpinBox()
        self.pay_component_amount_field.setRange(0, 10_000_000_000)
        self.pay_component_amount_field.setDecimals(0)
        form_row.addWidget(self.pay_component_amount_field, stretch=1)
        layout.addLayout(form_row)

        dates_row = QHBoxLayout()
        dates_row.addWidget(QLabel("از تاریخ"))
        self.pay_component_from_field = JalaliDateEdit()
        dates_row.addWidget(self.pay_component_from_field)
        dates_row.addWidget(QLabel("تا تاریخ"))
        self.pay_component_to_field = JalaliDateEdit()
        dates_row.addWidget(self.pay_component_to_field)
        layout.addLayout(dates_row)

        self.pay_component_unbounded_checkbox = QCheckBox("تا اطلاعِ ثانوی (بدونِ تاریخِ پایان)")
        self.pay_component_unbounded_checkbox.setChecked(True)
        self.pay_component_unbounded_checkbox.toggled.connect(
            lambda checked: self.pay_component_to_field.setEnabled(not checked)
        )
        self.pay_component_to_field.setEnabled(False)
        layout.addWidget(self.pay_component_unbounded_checkbox)

        self.pay_component_status_label = QLabel("")
        self.pay_component_status_label.setObjectName("statusError")
        self.pay_component_status_label.setWordWrap(True)
        layout.addWidget(self.pay_component_status_label)

        pc_buttons = QHBoxLayout()
        add_button = QPushButton("افزودن/به‌روزرسانی")
        add_button.clicked.connect(self._save_pay_component)
        pc_buttons.addWidget(add_button)
        clear_button = QPushButton("انصراف")
        clear_button.setObjectName("flatButton")
        clear_button.clicked.connect(self._reset_pay_component_form)
        pc_buttons.addWidget(clear_button)
        self.delete_pay_component_button = QPushButton("حذفِ ردیف")
        self.delete_pay_component_button.setObjectName("dangerButton")
        self.delete_pay_component_button.clicked.connect(self._delete_pay_component)
        self.delete_pay_component_button.setVisible(False)
        pc_buttons.addWidget(self.delete_pay_component_button)
        pc_buttons.addStretch(1)
        layout.addLayout(pc_buttons)

        self.pay_components_section = section
        section.setVisible(False)
        return section

    def _eligible_pay_items_for_decree(self, company_id: int) -> list[payroll_service.PayItemRow]:
        """فقط آیتم‌هایی که واقعاً از رویِ EmployeePayComponent خوانده
        می‌شوند (فصلِ ۶/۸ در payroll_engine.py): همه‌یِ کسورات + مزایا/
        درآمدهایِ با روشِ محاسبه‌یِ MANUAL. آیتم‌هایِ FIXED/PERCENTAGE/
        FORMULA این‌جا معنا ندارند چون مبلغ‌شان از رویِ خودِ تعریفِ آیتم
        محاسبه می‌شود، نه رویِ حکمِ کارمند."""
        items = payroll_service.list_pay_items(company_id, active_only=True)
        return [
            item for item in items
            if item.item_type == "DEDUCTION" or item.calculation_method == "MANUAL"
        ]

    def _refresh_pay_components_section(self, employee_id: int | None) -> None:
        self._current_employee_id = employee_id
        self._reset_pay_component_form()
        self.pay_components_section.setVisible(employee_id is not None)
        if employee_id is None:
            self._pay_components = []
            self.pay_components_table.setRowCount(0)
            return
        company_id = self._company_id()
        self.pay_component_item_combo.clear()
        if company_id is not None:
            for item in self._eligible_pay_items_for_decree(company_id):
                self.pay_component_item_combo.addItem(f"{item.code} — {item.name}", item.pay_item_id)
        self._pay_components = payroll_service.list_employee_pay_components(employee_id)
        self.pay_components_table.setRowCount(len(self._pay_components))
        for row_index, c in enumerate(self._pay_components):
            values = [
                f"{c.pay_item_code} — {c.pay_item_name}",
                numerals.format_amount(c.amount) if c.amount is not None else "—",
                numerals.to_persian_digits(c.effective_from.isoformat()),
                numerals.to_persian_digits(c.effective_to.isoformat()) if c.effective_to else "—",
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, c.component_id)
                self.pay_components_table.setItem(row_index, col_index, item)

    def _on_pay_component_row_clicked(self, row: int, _column: int) -> None:
        component_id = self.pay_components_table.item(row, 0).data(Qt.UserRole)
        component = next((c for c in self._pay_components if c.component_id == component_id), None)
        if component is None:
            return
        self._editing_pay_component_id = component.component_id
        self.pay_component_status_label.setText("")
        index = self.pay_component_item_combo.findData(component.pay_item_id)
        self.pay_component_item_combo.setCurrentIndex(index if index >= 0 else 0)
        self.pay_component_amount_field.setValue(float(component.amount) if component.amount is not None else 0)
        self.pay_component_from_field.setDate(component.effective_from)
        self.pay_component_unbounded_checkbox.setChecked(component.effective_to is None)
        if component.effective_to is not None:
            self.pay_component_to_field.setDate(component.effective_to)
        self.delete_pay_component_button.setVisible(True)

    def _reset_pay_component_form(self) -> None:
        self._editing_pay_component_id = None
        self.pay_component_status_label.setText("")
        self.pay_component_amount_field.setValue(0)
        self.pay_component_from_field.setDate(datetime.date.today())
        self.pay_component_unbounded_checkbox.setChecked(True)
        self.pay_component_to_field.setDate(datetime.date.today())
        self.delete_pay_component_button.setVisible(False)
        self.pay_components_table.clearSelection()

    def _save_pay_component(self) -> None:
        if self._current_employee_id is None:
            return
        pay_item_id = self.pay_component_item_combo.currentData()
        if pay_item_id is None:
            self.pay_component_status_label.setText("آیتمِ حقوقی را انتخاب کنید.")
            return
        amount = decimal.Decimal(str(self.pay_component_amount_field.value()))
        effective_from = self.pay_component_from_field.date()
        effective_to = None if self.pay_component_unbounded_checkbox.isChecked() else self.pay_component_to_field.date()
        try:
            if self._editing_pay_component_id is not None:
                payroll_service.delete_employee_pay_component(self._editing_pay_component_id)
            payroll_service.set_employee_pay_component(
                self._current_employee_id, pay_item_id, amount, effective_from, effective_to
            )
        except ValueError as exc:
            self.pay_component_status_label.setText(str(exc))
            return
        self._refresh_pay_components_section(self._current_employee_id)

    def _delete_pay_component(self) -> None:
        if self._editing_pay_component_id is None:
            return
        confirm = QMessageBox.question(
            self, "حذفِ ردیف", "این ردیفِ حکمِ حقوق حذف شود؟", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        payroll_service.delete_employee_pay_component(self._editing_pay_component_id)
        self._refresh_pay_components_section(self._current_employee_id)

    # --- بارگذاری --------------------------------------------------------
    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        previous = self._selected

        self._person_groups = dimensions_service.list_person_groups(company_id) if company_id is not None else []
        self._types = dimensions_service.list_dimension_types(company_id) if company_id is not None else []

        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItem("— انتخابِ گروه —", None)
        for g in self._person_groups:
            if g.code in _PERSON_GROUP_META:
                self.group_combo.addItem(g.name, ("person", g.code))
        for t in self._types:
            label = dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(t.code, t.code)
            self.group_combo.addItem(f"{label} ({t.detail_account_count})", ("dim", t.dimension_type_id))
        self.group_combo.blockSignals(False)

        previous_index = _find_combo_index(self.group_combo, previous) if previous is not None else -1
        if previous_index >= 0:
            self.group_combo.setCurrentIndex(previous_index)
        else:
            self._selected = None
            self.account_panel.setEnabled(False)

    def _on_group_changed(self) -> None:
        self._select(self.group_combo.currentData())

    def _select(self, combo_data: tuple[str, int | str] | None) -> None:
        self._selected = combo_data
        if combo_data is None:
            self.account_panel.setEnabled(False)
            return
        self.account_panel.setEnabled(True)
        self._cancel_account_edit()
        self._reload_accounts()

    def _is_person(self) -> bool:
        return self._selected is not None and self._selected[0] == "person"

    def _person_meta(self) -> dict:
        return _PERSON_GROUP_META[self._selected[1]]

    def _dimension_type_id(self) -> int | None:
        """dimension_type_idِ فعلی — برایِ گروه‌هایِ اشخاص، همیشه نوع‌بُعدِ
        سیستمیِ PERSON (سراسری برایِ هرسه‌شان)، برایِ بقیه همان انتخابِ کمبو."""
        if self._selected is None:
            return None
        if self._is_person():
            company_id = self._company_id()
            return dimensions_service.get_person_dimension_type_id(company_id) if company_id is not None else None
        return self._selected[1]

    def _person_group_id(self) -> int:
        if not self._is_person():
            return 0
        company_id = self._company_id()
        return dimensions_service.get_person_group_id(company_id, self._selected[1]) if company_id is not None else 0

    # --- فرمِ حسابِ تفصیلی --------------------------------------------------
    def _reload_accounts(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected is None:
            return
        dimension_type_id = self._dimension_type_id()
        person_group_id = self._person_group_id()

        if self._is_person():
            rows = self._person_meta()["list_fn"](company_id)
            self._person_rows_by_id = {r["detail_account_id"]: r for r in rows}
            self._accounts_by_id = {}
        else:
            rows = dimensions_service.list_detail_accounts(company_id, dimension_type_id)
            self._accounts_by_id = {r.detail_account_id: r for r in rows}
            self._person_rows_by_id = {}

        max_level_no = dimensions_service.get_group_max_level_no(dimension_type_id, person_group_id)
        self._current_max_level_no = max_level_no

        self.parent_combo.blockSignals(True)
        self.parent_combo.clear()
        self.parent_combo.addItem("— بدونِ والد (سطحِ ۱) —", None)
        if self._is_person():
            for r in rows:
                if r["level_no"] < max_level_no and r["detail_account_id"] != self._editing_account_id:
                    self.parent_combo.addItem(f"{r['full_code']} — {r['name'] or ''}", r["detail_account_id"])
        else:
            for r in rows:
                if r.level_no < max_level_no and r.detail_account_id != self._editing_account_id:
                    self.parent_combo.addItem(f"{r.full_code} — {r.name or ''}", r.detail_account_id)
        self.parent_combo.blockSignals(False)

        self._rebuild_accounts_tree()
        self._render_person_fields()
        self._render_extra_fields()
        if self._editing_account_id is None:
            self._suggest_code_for_current_parent()

    def _rebuild_accounts_tree(self) -> None:
        """طبقِ درخواستِ صریح: نمایِ درختی + رنگِ گروه — به‌طورِ پیش‌فرض فقط
        برگ‌ها (سطحِ آخر) نشان داده می‌شوند؛ چک‌باکسِ «نمایشِ همه‌یِ سطوح»
        سلسله‌مراتبِ کاملِ والد/فرزند را می‌سازد."""
        self.accounts_table.clear()
        if self._selected is None:
            return
        color = dimensions_service.get_group_color(self._dimension_type_id(), self._person_group_id())
        is_personnel_view = self._is_person() and self._selected[1] == dimensions_service.PERSONNEL_GROUP_CODE
        columns = _COLUMNS + _PERSONNEL_EXTRA_COLUMNS if is_personnel_view else _COLUMNS
        self.accounts_table.setColumnCount(len(columns))
        self.accounts_table.setHeaderLabels(columns)

        if self._is_person():
            rows = [
                (
                    r["detail_account_id"], r["parent_detail_account_id"], r["full_code"], r["name"],
                    r["level_no"], r["is_active"],
                    r.get("org_unit_name") or "—", r.get("position_name") or "—",
                    numerals.format_amount(r["base_salary"]) if r.get("base_salary") is not None else "—",
                    _EMPLOYEE_STATUS_LABELS.get(r.get("employee_status"), "—"),
                )
                for r in self._person_rows_by_id.values()
            ]
        else:
            rows = [
                (r.detail_account_id, r.parent_detail_account_id, r.full_code, r.name, r.level_no, r.is_active)
                for r in self._accounts_by_id.values()
            ]

        def make_item(row: tuple) -> QTreeWidgetItem:
            detail_account_id, _parent_id, full_code, name, level_no, is_active = row[:6]
            values = [full_code, name or "—", str(level_no), "فعال" if is_active else "غیرفعال"]
            if is_personnel_view:
                values.extend(row[6:])
            item = QTreeWidgetItem(values)
            item.setData(0, Qt.UserRole, detail_account_id)
            if color:
                for col in range(len(columns)):
                    item.setForeground(col, QBrush(QColor(color)))
            return item

        if self.show_all_levels_checkbox.isChecked():
            children_by_parent: dict[int | None, list[tuple]] = {}
            for row in rows:
                children_by_parent.setdefault(row[1], []).append(row)
            for siblings in children_by_parent.values():
                siblings.sort(key=lambda row: row[2])

            def add_children(parent_item: QTreeWidgetItem | None, parent_id: int | None) -> None:
                for row in children_by_parent.get(parent_id, []):
                    item = make_item(row)
                    if parent_item is None:
                        self.accounts_table.addTopLevelItem(item)
                    else:
                        parent_item.addChild(item)
                    add_children(item, row[0])

            add_children(None, None)
            self.accounts_table.expandAll()
        else:
            parent_ids = {row[1] for row in rows if row[1] is not None}
            leaves = [row for row in rows if row[0] not in parent_ids]
            for row in sorted(leaves, key=lambda row: row[2]):
                self.accounts_table.addTopLevelItem(make_item(row))

        for col in range(len(columns)):
            self.accounts_table.resizeColumnToContents(col)

    def _on_parent_combo_changed(self, _index: int) -> None:
        if self._editing_account_id is not None:
            return
        self._suggest_code_for_current_parent()
        if self._is_person():
            self._render_person_fields()
        self._render_extra_fields()

    def _current_level_no(self) -> int:
        """سطحِ حسابی که در حالِ ساخت/ویرایشِ آن هستیم — از رویِ والدِ
        انتخاب‌شده در parent_combo، هم برایِ رکوردِ تازه و هم (چون هنگامِ
        ویرایش والدِ درست از قبل رویِ کمبو ست شده) برایِ رکوردِ درحالِ‌ویرایش."""
        parent_id = self.parent_combo.currentData()
        if parent_id is None:
            return 1
        if self._is_person():
            parent = self._person_rows_by_id.get(parent_id)
            return (parent["level_no"] + 1) if parent else 1
        parent = self._accounts_by_id.get(parent_id)
        return (parent.level_no + 1) if parent else 1

    def _suggest_code_for_current_parent(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected is None:
            return
        dimension_type_id = self._dimension_type_id()
        parent_id = self.parent_combo.currentData()
        level_no = 1
        if parent_id is not None:
            if self._is_person():
                parent = self._person_rows_by_id.get(parent_id)
                if parent is None:
                    return
                level_no = parent["level_no"] + 1
            else:
                parent = self._accounts_by_id.get(parent_id)
                if parent is None:
                    return
                level_no = parent.level_no + 1
        self.account_code_field.setText(
            dimensions_service.suggest_next_code(company_id, dimension_type_id, level_no, self._person_group_id())
        )

    # --- فیلدهایِ هاردکدِ گروه‌هایِ اشخاص -------------------------------------
    def _render_person_fields(self, values: dict | None = None) -> None:
        while self.person_fields_grid.count():
            child = self.person_fields_grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._person_field_widgets = {}
        is_person = self._is_person()
        self.person_fields_label.setVisible(is_person)
        if not is_person:
            return
        company_id = self._company_id()
        group_code = self._selected[1]
        is_leaf_level = self._current_level_no() >= self._current_max_level_no
        row_index = 0
        for field_key, kind in self._person_meta()["field_specs"]:
            if field_key in _LEAF_ONLY_FIELD_KEYS and not is_leaf_level:
                continue
            self.person_fields_grid.addWidget(QLabel(_PERSON_FIELD_LABELS.get(field_key, field_key)), row_index, 0)
            if kind == "combo":
                widget = QComboBox()
                widget.addItem("— انتخاب —", None)
                loader = _PERSON_COMBO_LOADERS.get((group_code, field_key)) or _PERSON_COMBO_LOADERS.get(field_key)
                if company_id is not None and loader is not None:
                    for item_value, item_label in loader(company_id):
                        widget.addItem(item_label, item_value)
            else:
                widget = _make_field_widget(kind)
            self.person_fields_grid.addWidget(widget, row_index, 1)
            self._person_field_widgets[field_key] = widget
            if values is not None and values.get(field_key) is not None:
                value = values[field_key]
                if kind == "decimal":
                    widget.setValue(float(value))
                elif kind == "date" and isinstance(value, datetime.date):
                    widget.setDate(value)
                elif kind == "combo":
                    index = widget.findData(value)
                    widget.setCurrentIndex(index if index >= 0 else 0)
                elif kind == "bool":
                    widget.setChecked(bool(value))
                else:
                    widget.setText(str(value))
            row_index += 1

    def _collect_person_fields(self) -> dict:
        result: dict = {}
        for field_key, kind in self._person_meta()["field_specs"]:
            widget = self._person_field_widgets.get(field_key)
            if widget is None:
                result[field_key] = None
                continue
            if kind == "decimal":
                value = widget.value()
                result[field_key] = decimal.Decimal(str(value)) if value else None
            elif kind == "date":
                qdate = widget.date()
                result[field_key] = None if qdate == widget.minimumDate() else datetime.date(qdate.year(), qdate.month(), qdate.day())
            elif kind == "combo":
                result[field_key] = widget.currentData()
            elif kind == "bool":
                result[field_key] = widget.isChecked()
            else:
                text = widget.text().strip()
                result[field_key] = text or None
        return result

    # --- فیلدهایِ اختصاصیِ عمومی/قابلِ‌پیکربندی -------------------------------
    def _render_extra_fields(self, values: dict | None = None) -> None:
        while self.extra_fields_container.count():
            child = self.extra_fields_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._extra_widgets = {}
        if self._selected is None:
            return
        # طبقِ گزارشِ صریح: فیلدهایِ اختصاصیِ تعریف‌شده (برایِ همه‌یِ
        # گروه‌ها، نه فقط پرسنل) فقط در سطحِ آخرِ گروه معنا دارند — سطوحِ
        # بالاتر صرفاً گروه‌بندی‌اند و نباید این فیلدها را نشان بدهند/الزام
        # کنند. همان تعریفِ سطحِ آخر که برایِ فیلدهایِ هاردکدِ پرسنل استفاده
        # می‌شود (_current_level_no در برابرِ _current_max_level_no) این‌جا
        # هم به‌کار می‌رود.
        is_leaf_level = self._current_level_no() >= self._current_max_level_no
        self.extra_fields_label.setVisible(is_leaf_level)
        if not is_leaf_level:
            return
        company_id = self._company_id()
        for field_def in dimensions_service.list_group_fields(self._dimension_type_id(), self._person_group_id()):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(QLabel(field_def.label))
            if field_def.kind == "boolean":
                widget = QCheckBox()
            elif field_def.kind == "bank":
                # طبقِ گزارشِ صریح («نام بانک از جدولِ بانک‌ها»): کمبویی که
                # از فهرستِ treasury.banks پر می‌شود، نه متنِ آزاد.
                widget = QComboBox()
                widget.addItem("— انتخابِ بانک —", None)
                if company_id is not None:
                    for bank in treasury_service.list_banks(company_id):
                        widget.addItem(bank.name, bank.bank_id)
            elif field_def.kind == "account_type":
                widget = QComboBox()
                widget.addItems(_ACCOUNT_TYPE_OPTIONS)
            else:
                widget = _make_field_widget(field_def.kind)
            row_layout.addWidget(widget)
            self.extra_fields_container.addWidget(row)
            self._extra_widgets[field_def.field_key] = (widget, field_def.kind)

            if values is not None and values.get(field_def.field_key) is not None:
                value = values[field_def.field_key]
                if field_def.kind == "boolean":
                    widget.setChecked(bool(value))
                elif field_def.kind == "decimal":
                    widget.setValue(float(value))
                elif field_def.kind == "date" and isinstance(value, datetime.date):
                    widget.setDate(value)
                elif field_def.kind == "bank":
                    index = widget.findData(value)
                    widget.setCurrentIndex(index if index >= 0 else 0)
                elif field_def.kind == "account_type":
                    index = widget.findText(str(value))
                    widget.setCurrentIndex(index if index >= 0 else 0)
                else:
                    widget.setText(str(value))

    def _collect_extra_fields(self) -> dict:
        result = {}
        for key, (widget, kind) in self._extra_widgets.items():
            if kind == "boolean":
                result[key] = widget.isChecked()
            elif kind == "decimal":
                result[key] = decimal.Decimal(str(widget.value())) if widget.value() else None
            elif kind == "date":
                qdate = widget.date()
                result[key] = None if qdate == widget.minimumDate() else datetime.date(qdate.year(), qdate.month(), qdate.day())
            elif kind == "bank":
                result[key] = widget.currentData()
            elif kind == "account_type":
                result[key] = widget.currentText()
            else:
                text = widget.text().strip()
                result[key] = text or None
        return result

    # --- ویرایش/ذخیره/حذف --------------------------------------------------
    def _on_account_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        detail_account_id = item.data(0, Qt.UserRole)
        if detail_account_id is None:
            return
        self.edit_detail_account(detail_account_id)

    def edit_detail_account(self, detail_account_id: int) -> None:
        if self._is_person():
            row = self._person_rows_by_id.get(detail_account_id)
            if row is None:
                return
            self._editing_account_id = detail_account_id
            self._reload_accounts()
            self.account_form_title.setText(f"ویرایشِ «{row['full_code']}»")
            self.account_code_field.setText(row["code"])
            self.account_name_field.setText(row["name"] or "")
            self.account_active_checkbox.setChecked(row["is_active"])
            parent_id = row.get("parent_detail_account_id")
            index = self.parent_combo.findData(parent_id) if parent_id is not None else 0
            self.parent_combo.setCurrentIndex(index if index >= 0 else 0)
            self.parent_combo.setEnabled(False)
            self._render_person_fields(row)
            self._render_extra_fields(row.get("custom_fields"))
            self.delete_button.setVisible(True)
            is_employee = self._selected[1] == dimensions_service.PERSONNEL_GROUP_CODE and row.get("employee_id") is not None
            self.terminate_employee_button.setVisible(is_employee and row.get("employee_status") != "TERMINATED")
            self._refresh_pay_components_section(row.get("employee_id") if is_employee else None)
            self._update_partner_status_display(row)
            return

        account = self._accounts_by_id.get(detail_account_id)
        if account is None:
            return
        self._editing_account_id = detail_account_id
        self._reload_accounts()
        self.account_form_title.setText(f"ویرایشِ «{account.full_code}»")
        self.account_code_field.setText(account.code)
        self.account_name_field.setText(account.name or "")
        self.account_active_checkbox.setChecked(account.is_active)
        if account.parent_detail_account_id is not None:
            index = self.parent_combo.findData(account.parent_detail_account_id)
            self.parent_combo.setCurrentIndex(index if index >= 0 else 0)
        else:
            self.parent_combo.setCurrentIndex(0)
        self.parent_combo.setEnabled(False)
        self._render_extra_fields(account.extra_fields)
        self.delete_button.setVisible(True)
        self.terminate_employee_button.setVisible(False)
        self._refresh_pay_components_section(None)

    def _update_partner_status_display(self, row: dict) -> None:
        group_code = self._selected[1] if self._selected else None
        is_partner_group = group_code in (dimensions_service.CUSTOMER_GROUP_CODE, dimensions_service.SUPPLIER_GROUP_CODE)
        status_code = row.get("status_code") if is_partner_group else None
        if status_code is None:
            self.partner_status_label.setVisible(False)
            self.approve_partner_button.setVisible(False)
            return
        self.partner_status_label.setText(f"وضعیتِ اعتباری: {_PARTNER_STATUS_LABELS.get(status_code, status_code)}")
        self.partner_status_label.setVisible(True)
        self.approve_partner_button.setVisible(status_code == "PENDING_APPROVAL")

    def _approve_partner(self) -> None:
        if self._editing_account_id is None or self._selected is None:
            return
        group_code = self._selected[1]
        account_id = self._editing_account_id
        try:
            if group_code == dimensions_service.CUSTOMER_GROUP_CODE:
                partners_service.approve_customer(account_id, session.current_user.user_id)
            elif group_code == dimensions_service.SUPPLIER_GROUP_CODE:
                partners_service.approve_supplier(account_id, session.current_user.user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        # طبقِ همان الگویِ _terminate_employee: بعدِ تغییرِ وضعیت رویِ
        # پایگاه‌داده، باید یک refresh/reselectِ کامل انجام شود تا
        # self._person_rows_by_id (که edit_detail_account از رویِ آن
        # می‌خواند) واقعاً به‌روز شود — خواندنِ مستقیمِ edit_detail_account
        # بدونِ این چرخه، دادهٔ قدیمی (پیشِ‌ازتایید) را دوباره نشان می‌دهد.
        selected = self._selected
        self._cancel_account_edit()
        self.refresh()
        self._select(selected)
        self.edit_detail_account(account_id)

    def _cancel_account_edit(self) -> None:
        self._editing_account_id = None
        self.account_form_title.setText("حسابِ تفصیلیِ جدید")
        self.account_status_label.setText("")
        self.account_code_field.clear()
        self.account_name_field.clear()
        self.account_active_checkbox.setChecked(True)
        self.parent_combo.setEnabled(True)
        if self.parent_combo.count():
            self.parent_combo.setCurrentIndex(0)
        self._render_person_fields()
        self._render_extra_fields()
        self._refresh_pay_components_section(None)
        self._suggest_code_for_current_parent()
        self.accounts_table.clearSelection()
        self.delete_button.setVisible(False)
        self.terminate_employee_button.setVisible(False)
        self.partner_status_label.setVisible(False)
        self.approve_partner_button.setVisible(False)

    def _terminate_employee(self) -> None:
        if self._editing_account_id is None:
            return
        row = self._person_rows_by_id.get(self._editing_account_id)
        employee_id = row.get("employee_id") if row else None
        if employee_id is None:
            return
        confirm = QMessageBox.question(
            self, "ثبتِ ترکِ کار", "همکاری با این کارمند پایان یابد؟", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            hr_service.terminate_employee(employee_id, datetime.date.today(), None, None)
        except ValueError as exc:
            self.account_status_label.setText(str(exc))
            return
        selected = self._selected
        self._cancel_account_edit()
        self.refresh()
        self._select(selected)

    def _save_account(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected is None:
            return
        code = self.account_code_field.text().strip()
        if not code:
            self.account_status_label.setText("کد را وارد کنید.")
            return
        name = self.account_name_field.text().strip() or None
        extra_fields = self._collect_extra_fields()

        try:
            if self._is_person():
                meta = self._person_meta()
                person_fields = self._collect_person_fields()
                if self._editing_account_id is not None:
                    meta["update_fn"](
                        detail_account_id=self._editing_account_id, company_id=company_id, code=code,
                        name=name or "", is_active=self.account_active_checkbox.isChecked(),
                        custom_fields=extra_fields, **person_fields,
                    )
                else:
                    meta["create_fn"](
                        company_id=company_id, code=code, name=name or "", custom_fields=extra_fields,
                        parent_detail_account_id=self.parent_combo.currentData(), **person_fields,
                    )
            elif self._editing_account_id is not None:
                dimensions_service.update_detail_account(
                    self._editing_account_id, company_id, code, self.account_active_checkbox.isChecked(),
                    name=name, extra_fields=extra_fields,
                )
            else:
                dimensions_service.create_detail_account(
                    company_id, self._dimension_type_id(), code, name=name,
                    parent_detail_account_id=self.parent_combo.currentData(), extra_fields=extra_fields,
                )
        except ValueError as exc:
            self.account_status_label.setText(str(exc))
            return

        selected = self._selected
        self._cancel_account_edit()
        self.refresh()
        self._select(selected)

    def _delete_account(self) -> None:
        if self._editing_account_id is None or self._selected is None:
            return
        company_id = self._company_id()
        if company_id is None:
            return
        confirm = QMessageBox.question(
            self, "حذف", "این حساب حذف شود؟ این کار قابلِ بازگشت نیست.", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            if self._is_person():
                self._person_meta()["delete_fn"](self._editing_account_id, company_id)
            else:
                dimensions_service.delete_detail_account(self._editing_account_id, company_id)
        except ValueError as exc:
            self.account_status_label.setText(str(exc))
            return

        selected = self._selected
        self._cancel_account_edit()
        self.refresh()
        self._select(selected)

    # --- برایِ ناوبری از فهرستِ واحدِ تفصیلی‌ها -----------------------------
    def select_type_and_edit(self, combo_data: tuple[str, int | str], detail_account_id: int) -> None:
        self.refresh()
        index = _find_combo_index(self.group_combo, combo_data)
        if index >= 0:
            self.group_combo.setCurrentIndex(index)
        self.edit_detail_account(detail_account_id)

    def select_type_for_new_entry(self, combo_data: tuple[str, int | str]) -> None:
        """برایِ دکمه‌ی «تفصیلیِ جدید» در فهرستِ واحد — همان گروه را انتخاب
        می‌کند و فرم را در حالتِ «رکوردِ تازه» نگه می‌دارد. صراحتاً _select
        را هم صدا می‌زند (نه فقط setCurrentIndex) چون اگر همین گروه از قبل
        انتخاب‌شده باشد، تغییرِ ایندکس سیگنال نمی‌دهد و ریست انجام نمی‌شود."""
        self.refresh()
        index = _find_combo_index(self.group_combo, combo_data)
        if index >= 0:
            self.group_combo.setCurrentIndex(index)
        self._select(combo_data)
