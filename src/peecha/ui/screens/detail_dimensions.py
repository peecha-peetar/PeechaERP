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
import traceback

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals
from peecha import session
from peecha.services import commercial_contracts as contracts_service
from peecha.services import commercial_partners as partners_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import hr as hr_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import payroll as payroll_service
from peecha.services import sales_assistant as assistant_service
from peecha.services import treasury as treasury_service
from peecha.ui.screens.inventory_item_panel import ItemDetailPanel, _KIND_LABELS, _LIFECYCLE_LABELS
from peecha.ui.widgets import (
    FieldGrid,
    FieldHelpMixin,
    FieldSpec,
    LayoutEditMixin,
    JalaliDateEdit,
    PersianDigitLineEdit,
    build_action_footer,
    build_page_header,
    build_section_layout,
)

# طبقِ درخواستِ صریح («کد باید اولین ستون از سمتِ راست باشد، در همه‌ی
# فرم‌هایِ این‌شکلی») — هم‌الگو با ترتیبِ ستون‌هایِ کدینگِ حساب‌ها.
_COLUMNS = ["کدِ کامل", "نام", "سطح", "وضعیت"]
# طبقِ یکپارچه‌سازیِ «تعریفِ کارمند فقط از طریقِ تفصیلی»: فهرستِ کارمندان
# (که قبلاً در صفحه‌یِ جداگانه‌یِ «تعریفِ کارکنان» این ستون‌ها را داشت)
# باید همین‌جا هم دیده شود، پس فقط برایِ گروهِ PERSONNEL این ۴ ستونِ
# اضافه به ستون‌هایِ عمومی افزوده می‌شود.
_PERSONNEL_EXTRA_COLUMNS = ["واحدِ سازمانی", "پست", "حقوقِ پایه", "وضعیتِ استخدام"]
# طبقِ ادغامِ فرمِ «کالا و خدمت» در گروهِ تفصیلیِ INVENTORY_ITEM: فقط برایِ
# ردیف‌هایِ سطحِ‌آخرِ همین گروه، این ۳ ستونِ اضافه دیده می‌شود (گره‌هایِ
# میانیِ گروه‌بندی مقدارِ «—» می‌گیرند، چون ردیفِ inv.items ندارند).
_ITEM_EXTRA_COLUMNS = ["نوع", "واحدِ پایه", "وضعیتِ چرخهٔ‌عمر"]
# طبقِ گزارشِ صریح («نوعِ حساب جاری/پس‌انداز») — گزینه‌هایِ ثابتِ کیندِ
# «account_type»یِ فیلدهایِ اختصاصی (فقط برایِ BANK_ACCOUNT کاربرد دارد).
_ACCOUNT_TYPE_OPTIONS = ["جاری", "پس‌انداز"]
# طبقِ بازبینیِ ساختارِ «تعریفِ مشتری» (R216، بخشِ ۱): گزینه‌هایِ ثابتِ
# فیلدهایِ هویتیِ تکمیلی -- کمبویِ کدنویسی‌شده (نه از DB)، هم‌الگو با
# _ACCOUNT_TYPE_OPTIONS بالا.
_CUSTOMER_TYPE_OPTIONS = [
    ("INDIVIDUAL", "شخص"), ("COMPANY", "شرکت"), ("STORE", "فروشگاه"), ("ORGANIZATION", "سازمان"),
    ("WHOLESALER", "عمده‌فروش"), ("RETAILER", "خرده‌فروش"), ("AGENT", "نماینده"), ("ONLINE", "مشتریِ آنلاین"),
]
_PERSON_TYPE_OPTIONS = [("NATURAL", "حقیقی"), ("LEGAL", "حقوقی")]
_CUSTOMER_CLASS_OPTIONS = [("A", "A"), ("B", "B"), ("C", "C"), ("D", "D")]
# طبقِ بازبینیِ ساختارِ «تعریفِ مشتری» (R219، بخشِ ۳ -- طبقه‌بندیِ فروش/تنظیماتِ سفارش).
_OUTLET_TYPE_OPTIONS = [
    ("SUPERMARKET", "سوپرمارکت"), ("CHAIN_STORE", "فروشگاهِ زنجیره‌ای"), ("WHOLESALE", "عمده‌فروشی"),
    ("RESTAURANT", "رستوران"), ("PHARMACY", "داروخانه"), ("SPECIALTY_STORE", "فروشگاهِ تخصصی"),
    ("ORGANIZATIONAL", "سازمانی"), ("OTHER", "سایر"),
]
_PRIORITY_OPTIONS = [("LOW", "کم"), ("NORMAL", "عادی"), ("HIGH", "بالا"), ("VIP", "ویژه/VIP")]
_SHIPMENT_TYPE_OPTIONS = [
    ("VEHICLE_ROUTE", "خودرو/مسیرِ پخش"), ("COURIER", "پیک"), ("FREIGHT", "باربری"), ("PICKUP", "حضوری/تحویلِ درِ انبار"),
]
_EMPLOYEE_STATUS_LABELS = {"ACTIVE": "فعال", "ON_LEAVE": "مرخصی", "TERMINATED": "پایان‌یافته"}
# طبقِ یکپارچه‌سازیِ مشتری/تامین‌کننده در فرمِ تفصیلی (مرحلهٔ بازرگانی):
# وضعیتِ گردشِ کارِ تاییدِ اعتباری (comm.customer_profiles/supplier_profiles.status_code).
_PARTNER_STATUS_LABELS = {
    "DRAFT": "پیش‌نویس", "PENDING_APPROVAL": "درانتظارِ تاییدِ اعتباری", "ACTIVE": "فعال",
    "SUSPENDED": "معلق", "BLACKLISTED": "لیستِ سیاه", "ON_HOLD": "متوقف", "DISQUALIFIED": "ردِ صلاحیت",
    "INACTIVE": "غیرفعال",
}
# طبقِ آیتمِ ۱۰ از بازبینیِ «تعریفِ مشتری» (R219): تبِ آدرس‌هایِ چندگانه در
# فرمِ حسابِ تفصیلی -- کدهایِ نوعِ آدرس هم‌الگو با comm.party_addresses و
# مشابهِ ADDRESS_TYPE_LABELS در موبایل (CustomerAddressesScreen.tsx).
_PARTY_ADDRESS_TYPE_LABELS = {
    "OFFICE": "دفتر", "STORE": "فروشگاه", "WAREHOUSE": "انبار",
    "DELIVERY": "تحویل", "BILLING": "صورتحساب", "RETURN": "مرجوعی",
}
# طبقِ آیتمِ ۲ از بازخوردِ کاربر رویِ R220: تبِ ضمانت‌هایِ مشتری در فرمِ
# دسکتاپ (سرویس/API از R219 آماده بود، فقط UI نداشت).
_GUARANTEE_TYPE_LABELS = {
    "CHECK": "چکِ تضمینی", "PROMISSORY_NOTE": "سفته", "BANK_GUARANTEE": "ضمانت‌نامه",
    "GUARANTOR": "ضامن", "COLLATERAL": "وثیقه",
}
_GUARANTEE_STATUS_LABELS = {"ACTIVE": "فعال", "RELEASED": "آزادشده", "CALLED": "ضبط‌شده", "EXPIRED": "منقضی"}
_GUARANTEE_RELEASE_STATUS_OPTIONS = [("RELEASED", "آزادسازی"), ("CALLED", "ضبط"), ("EXPIRED", "اعلامِ انقضا")]
# طبقِ آیتمِ ۳ از همان بازخورد: تبِ قراردادهایِ مشتری/تامین‌کننده.
_CONTRACT_CATEGORY_LABELS = {"STANDARD": "استاندارد", "AGENCY": "نمایندگی", "ORGANIZATIONAL": "سازمانی"}
_CONTRACT_CATEGORY_OPTIONS = [("STANDARD", "استاندارد"), ("AGENCY", "نمایندگی"), ("ORGANIZATIONAL", "سازمانی")]
_CONTRACT_STATUS_LABELS = {"ACTIVE": "فعال", "CANCELLED": "لغوشده", "EXPIRED": "منقضی"}

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
    "distribution_route_detail_account_id": "مسیرِ توزیع",
    "customer_type_code": "نوعِ مشتری",
    "person_type_code": "نوعِ شخصیت",
    "customer_class": "طبقه‌یِ مشتری",
    "geographic_region": "منطقه‌یِ جغرافیایی",
    "outlet_type_code": "نوعِ فروشگاه",
    "priority_code": "اولویتِ مشتری",
    "min_order_amount": "حداقلِ مبلغِ سفارش",
    "min_order_quantity": "حداقلِ تعدادِ سفارش",
    "allowed_order_days_mask": "روزهایِ مجازِ سفارش (بیت‌مسک، ۱-۱۲۷)",
    "allowed_order_hour_from": "ساعتِ مجازِ سفارش -- از",
    "allowed_order_hour_to": "ساعتِ مجازِ سفارش -- تا",
    "expected_delivery_days": "زمانِ تحویلِ موردِانتظار (روز)",
    "shipment_type_code": "نوعِ ارسال",
    "default_warehouse_id": "انبارِ پیش‌فرض",
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
    (dimensions_service.CUSTOMER_GROUP_CODE, "distribution_route_detail_account_id"): lambda company_id: [
        (r.detail_account_id, f"{r.code} — {r.name or ''}")
        for r in dimensions_service.list_leaf_detail_accounts(
            company_id, dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.DISTRIBUTION_ROUTE_CODE)
        )
    ],
    (dimensions_service.SUPPLIER_GROUP_CODE, "supplier_group_id"): lambda company_id: [
        (g.group_id, g.name) for g in partners_service.list_supplier_groups(company_id)
    ],
    (dimensions_service.SUPPLIER_GROUP_CODE, "default_price_list_id"): lambda company_id: [
        (pl.price_list_id, f"{pl.code} — {pl.name}") for pl in pricing_service.list_price_lists(company_id, "PURCHASE")
    ],
    "customer_type_code": lambda company_id: _CUSTOMER_TYPE_OPTIONS,
    "person_type_code": lambda company_id: _PERSON_TYPE_OPTIONS,
    "customer_class": lambda company_id: _CUSTOMER_CLASS_OPTIONS,
    "outlet_type_code": lambda company_id: _OUTLET_TYPE_OPTIONS,
    "priority_code": lambda company_id: _PRIORITY_OPTIONS,
    "shipment_type_code": lambda company_id: _SHIPMENT_TYPE_OPTIONS,
    "default_warehouse_id": lambda company_id: [
        (w.warehouse_id, f"{w.code} — {w.name}") for w in locations_service.list_warehouses(company_id)
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
            ("customer_type_code", "combo"), ("person_type_code", "combo"), ("customer_class", "combo"),
            ("geographic_region", "text"),
            ("economic_code", "text"), ("national_id", "text"), ("phone", "text"), ("mobile", "text"),
            ("address", "text"), ("customer_group_id", "combo"), ("default_price_list_id", "combo"),
            ("default_channel_code", "combo"), ("payment_term_days", "decimal"), ("credit_limit_amount", "decimal"),
            ("is_tax_exempt", "bool"), ("distribution_route_detail_account_id", "combo"), ("notes", "text"),
            ("outlet_type_code", "combo"), ("priority_code", "combo"), ("min_order_amount", "decimal"),
            ("min_order_quantity", "decimal"), ("allowed_order_days_mask", "decimal"),
            ("allowed_order_hour_from", "decimal"), ("allowed_order_hour_to", "decimal"),
            ("expected_delivery_days", "decimal"), ("shipment_type_code", "combo"), ("default_warehouse_id", "combo"),
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
        return JalaliDateEdit(allow_empty=True)
    if kind == "bool":
        return QCheckBox()
    return PersianDigitLineEdit()


class _ClickableLabel(QLabel):
    """طبقِ درخواستِ صریح («با کلیک روی عکسهای آپلود شده زوم هم بشه»):
    QLabelِ معمولی سیگنالِ کلیک ندارد -- این زیرکلاسِ ساده همان را اضافه
    می‌کند."""

    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (نامِ متدِ Qt)
        self.clicked.emit()
        super().mousePressEvent(event)


class _PhotoZoomDialog(QDialog):
    """طبقِ درخواستِ صریح («تمام صفحه ببینیم»): نمایِ بزرگِ یک عکس، تا
    حدِ ۸۰٪ اندازه‌یِ صفحه‌نمایش (بدونِ خرابیِ نسبت)."""

    def __init__(self, pixmap: QPixmap, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        screen = QApplication.primaryScreen()
        if screen is not None and not pixmap.isNull():
            max_size = screen.availableSize() * 0.8
            if pixmap.width() > max_size.width() or pixmap.height() > max_size.height():
                pixmap = pixmap.scaled(
                    max_size.width(), max_size.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
        label.setPixmap(pixmap)
        layout.addWidget(label)


class DetailDimensionsScreen(FieldHelpMixin, LayoutEditMixin, QWidget):
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
        # طبقِ ادغامِ فرمِ کالا: نگاشتِ detail_account_id -> ItemRow برایِ
        # ردیف‌هایِ سطحِ‌آخرِ گروهِ INVENTORY_ITEM (فقط وقتی همین گروه
        # انتخاب شده — هم‌الگو با self._person_rows_by_id).
        self._item_rows_by_detail_id: dict[int, catalog_service.ItemRow] = {}
        self._editing_account_id: int | None = None
        self._extra_widgets: dict[str, tuple[QWidget, str]] = {}
        self._person_field_widgets: dict[str, QWidget] = {}
        self._current_max_level_no: int = 1
        # طبقِ درخواستِ صریح («حکمِ حقوق داخلِ فرمِ تفصیلیِ پرسنل»): مزایا/
        # کسوراتِ اختصاصیِ کارمندِ درحالِ‌ویرایش (payroll.EmployeePayComponent).
        self._current_employee_id: int | None = None
        self._pay_components: list[payroll_service.EmployeePayComponentRow] = []
        self._editing_pay_component_id: int | None = None
        # طبقِ آیتمِ ۱۰ از بازبینیِ «تعریفِ مشتری» (R219): چندآدرسیِ مشتری/
        # تامین‌کننده (comm.party_addresses) که در موبایل از پیش هست، این‌جا
        # هم در تبِ جداگانه‌یِ فرمِ حسابِ تفصیلی مدیریت می‌شود.
        self._addresses: list = []
        self._editing_address_id: int | None = None
        self._address_lat: float | None = None
        self._address_lon: float | None = None
        self._guarantees: list = []
        self._selected_guarantee_id: int | None = None
        self._contracts: list = []
        self._selected_contract_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(16)
        # طبقِ درخواستِ صریحِ کاربر («لیستِ تفصیلی حذف بشه و فقط ورودِ
        # تفصیلیِ جدید باشه، تا تبِ تعریفِ تفصیلی (مثلاً فرمِ کالا) فضایِ
        # بهتری داشته باشد»): فهرستِ همیشه-نمایانِ حساب‌ها (که قبلاً یک
        # ستونِ کاملِ کنارِ فرم بود) کاملاً حذف شد؛ کلِ عرضِ صفحه به فرمِ
        # ورودِ اطلاعات می‌رسد. انتخابِ گروه به‌تنهایی فرم را برایِ ثبتِ
        # رکوردِ *تازه* آماده می‌کند (طبقِ منطقِ ازپیش‌موجودِ _select)؛
        # برایِ بازکردنِ یک حسابِ *موجود* جهتِ ویرایش، دکمهٔ 🔍 یک دیالوگِ
        # جداگانه (حاویِ همان درختِ قبلی) باز می‌کند -- پس امکانِ ویرایش
        # از بین نرفته، فقط دیگر همیشه فضا اشغال نمی‌کند.
        outer.addWidget(self._build_account_panel(), stretch=1)
        self._account_picker_dialog = self._build_account_picker_dialog()

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
            (self.copy_from_combo, "یک حسابِ تفصیلیِ ازپیش‌موجود را انتخاب کنید تا فیلدهایِ اضافیِ آن (نه کد/نام) در همین فرم کپی شوند."),
            (self.pay_component_item_combo, "آیتمِ حقوقیِ اختصاصیِ این کارمند (مثلاً یک پاداشِ ثابتِ ماهانه)."),
            (self.pay_component_amount_field, "مبلغِ ثابتِ همین آیتمِ حقوقی برایِ این کارمند."),
            (self.pay_component_unbounded_checkbox, "اگر روشن باشد، فیلدِ «تا تاریخ» غیرِفعال می‌شود -- این آیتم تا اطلاعِ ثانوی برایِ این کارمند فعال می‌ماند."),
        ])

    # --- دیالوگِ انتخابِ حسابِ تفصیلیِ *موجود* (برایِ ویرایش) -----------------
    def _build_account_picker_dialog(self) -> QDialog:
        """طبقِ رفعِ باگِ گزارش‌شده («لیستِ تفصیلی حذف بشه»): درختِ حساب‌ها
        دیگر همیشه رویِ صفحه نیست -- فقط با زدنِ دکمهٔ 🔍 (کنارِ کمبویِ
        گروه در فرمِ اصلی) به‌صورتِ یک دیالوگِ جدا باز می‌شود؛ کلیک رویِ
        هر ردیف هم مثلِ قبل رکورد را در فرم بارگذاری می‌کند و هم خودش
        دیالوگ را می‌بندد."""
        dialog = QDialog(self)
        dialog.setWindowTitle("بازکردنِ حسابِ تفصیلیِ موجود")
        dialog.resize(680, 560)
        layout = QVBoxLayout(dialog)

        self.show_all_levels_checkbox = QCheckBox("نمایشِ همه‌یِ سطوح")
        self.show_all_levels_checkbox.toggled.connect(lambda _checked: self._rebuild_accounts_tree())
        layout.addWidget(self.show_all_levels_checkbox)

        self.accounts_table = QTreeWidget()
        self.accounts_table.setColumnCount(len(_COLUMNS))
        self.accounts_table.setHeaderLabels(_COLUMNS)
        self.accounts_table.itemClicked.connect(self._on_account_item_clicked)
        self.accounts_table.itemClicked.connect(lambda *_args: dialog.accept())
        layout.addWidget(self.accounts_table, stretch=1)

        return dialog

    def _open_account_picker(self) -> None:
        if self._selected is None:
            self.account_status_label.setText("ابتدا یک گروه انتخاب کنید.")
            return
        self._rebuild_accounts_tree()
        self._account_picker_dialog.exec()

    # --- ستونِ راست: فرمِ حسابِ تفصیلی ---------------------------------------
    def _build_account_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        panel = QWidget()
        layout = build_section_layout(panel)

        self.account_form_title = QLabel("حسابِ تفصیلیِ جدید")
        self.account_form_title.setObjectName("pageTitle")
        layout.addWidget(self.account_form_title)

        # طبقِ درخواستِ صریح («بشه از تفضیلی‌هایِ دیگر کپی کرد و تفصیلیِ
        # جدید ایجاد نمود»): وقتی در حالِ ساختنِ رکوردِ تازه هستیم، انتخابِ
        # یک حسابِ تفصیلیِ موجود از همین گروه، تمامِ فیلدهایش (بجز کد --
        # که باید یکتا بماند) را در فرم پر می‌کند؛ فقط یک محرکِ یک‌باره
        # است، بعدِ کپی خودش به حالتِ اولیه برمی‌گردد.
        # طبقِ درخواستِ صریحِ کاربر («این فضاهایِ هدرِ کالا می‌تونه در یک
        # ردیف هم باشه و نیاز به ردیف‌هایِ اضافی نیست»): «کپی از» هم یک
        # فیلدِ دیگرِ همینِ FieldGrid است (نه یک ردیفِ جداگانه‌یِ بالاتر)
        # تا کپی‌از/والد/کد/نام/فعال هرچه‌بیشتر در یک ردیف جا شوند؛ چون
        # خودش از قبل یک QLabelِ داخلی («کپی از:») دارد، با label=""
        # اضافه می‌شود تا برچسبِ تکراری ساخته نشود.
        copy_from_row = QHBoxLayout()
        copy_from_row.setContentsMargins(0, 0, 0, 0)
        copy_from_row.addWidget(QLabel("کپی از:"))
        self.copy_from_combo = QComboBox()
        self.copy_from_combo.addItem("— انتخابِ نمونه برایِ کپی —", None)
        self.copy_from_combo.currentIndexChanged.connect(self._on_copy_from_changed)
        copy_from_row.addWidget(self.copy_from_combo, stretch=1)
        self.copy_from_widget = QWidget()
        self.copy_from_widget.setLayout(copy_from_row)

        self.parent_combo = QComboBox()
        self.parent_combo.currentIndexChanged.connect(self._on_parent_combo_changed)

        self.account_code_field = QLineEdit()
        self.account_code_field.setMaximumWidth(90)

        self.account_name_field = QLineEdit()

        self.account_active_checkbox = QCheckBox("فعال")
        self.account_active_checkbox.setChecked(True)

        # ستون‌بندی=۸ تا هر پنج فیلد (کپی‌از/والد/کد/نام/فعال) در یک
        # ردیفِ واحد جا شوند؛ نسبتِ عرضِ فیلدها (والد/نامِ پهن‌تر از
        # کد/فعالِ کوتاه) همانِ نسبتِ قبلی حفظ شده، فقط با ستونِ اضافه
        # برایِ «کپی از».
        self.account_basic_grid = FieldGrid([
            FieldSpec("copy_from", "", self.copy_from_widget, span=2),
            FieldSpec("parent", "والد", self.parent_combo, span=2),
            FieldSpec("code", "کد", self.account_code_field, span=1),
            FieldSpec("name", "نام", self.account_name_field, span=2),
            FieldSpec("active", "", self.account_active_checkbox, span=1),
        ], columns=8)
        layout.addWidget(self.account_basic_grid)
        self.register_field_grids("detail_dimensions", [self.account_basic_grid])

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
        # طبقِ درخواستِ صریح («رتبه‌بندیِ هوشمندِ مشتریان... Customer
        # Score») و تصمیمِ طراحیِ توافق‌شده (نمایش به‌صورتِ یک بَج در همینِ
        # فرمِ موجود، نه یک داشبوردِ جداگانه) -- فقط برایِ مشتری (نه
        # تامین‌کننده) و فقط رویِ رکوردِ از قبل ذخیره‌شده.
        self.customer_score_label = QLabel("")
        self.customer_score_label.setVisible(False)
        layout.addWidget(self.customer_score_label)
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

        # طبقِ ادغامِ فرمِ «کالا و خدمت»: پنلِ اختصاصیِ ۱۱‌تبیِ کالا فقط در
        # سطحِ‌آخرِ گروهِ INVENTORY_ITEM نمایان می‌شود — هم‌الگو با پنلِ
        # حکمِ حقوقِ زیر که فقط برایِ PERSONNEL کاربرد دارد.
        self.item_level_hint_label = QLabel("")
        self.item_level_hint_label.setWordWrap(True)
        self.item_level_hint_label.setObjectName("itemLevelHint")
        self.item_level_hint_label.setVisible(False)
        layout.addWidget(self.item_level_hint_label)

        self.item_detail_panel = ItemDetailPanel()
        self.item_detail_panel.setVisible(False)
        layout.addWidget(self.item_detail_panel)

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

        # طبقِ درخواستِ صریح («یک تب درست بشه که عکسها و کاتالوگ و
        # فایلها در آنجا مدیریت بشه»): تبِ دوم فقط وقتی گروهِ انتخاب‌شده
        # امکانِ آپلودِ عکس را روشن کرده باشد نمایان می‌شود (_refresh_files_tab).
        self.account_tabs = QTabWidget()
        self.account_tabs.addTab(scroll, "اطلاعات")
        self.files_tab = self._build_files_tab()
        self.account_tabs.addTab(self.files_tab, "عکس‌ها و فایل‌ها")
        self.addresses_tab = self._build_addresses_tab()
        self.account_tabs.addTab(self.addresses_tab, "آدرس‌ها")
        self.guarantees_tab = self._build_guarantees_tab()
        self.account_tabs.addTab(self.guarantees_tab, "ضمانت‌ها")
        self.contracts_tab = self._build_contracts_tab()
        self.account_tabs.addTab(self.contracts_tab, "قراردادها")
        wrapper_layout.addWidget(self.account_tabs, stretch=1)

        self.save_button = QPushButton("💾")
        self.save_button.setObjectName("primaryIconButton")
        self.save_button.setFixedWidth(48)
        self.save_button.setToolTip("ذخیره")
        self.save_button.clicked.connect(self._save_account)
        cancel_button = QPushButton("↩️")
        cancel_button.setObjectName("iconButton")
        cancel_button.setFixedWidth(44)
        cancel_button.setToolTip("انصراف")
        cancel_button.clicked.connect(self._cancel_account_edit)
        self.delete_button = QPushButton("🗑️")
        self.delete_button.setObjectName("dangerIconButton")
        self.delete_button.setFixedWidth(44)
        self.delete_button.setToolTip("حذف")
        self.delete_button.clicked.connect(self._delete_account)
        self.delete_button.setVisible(False)
        self.terminate_employee_button = QPushButton("🚪")
        self.terminate_employee_button.setObjectName("dangerIconButton")
        self.terminate_employee_button.setFixedWidth(44)
        self.terminate_employee_button.setToolTip("ثبتِ ترکِ کار")
        self.terminate_employee_button.clicked.connect(self._terminate_employee)
        self.terminate_employee_button.setVisible(False)
        self.approve_partner_button = QPushButton("💳")
        self.approve_partner_button.setObjectName("primaryIconButton")
        self.approve_partner_button.setFixedWidth(48)
        self.approve_partner_button.setToolTip("تاییدِ اعتباری")
        self.approve_partner_button.clicked.connect(self._approve_partner)
        self.approve_partner_button.setVisible(False)
        footer = build_action_footer([
            self.save_button, cancel_button, self.delete_button,
            self.terminate_employee_button, self.approve_partner_button,
        ])
        wrapper_layout.addWidget(footer)

        self.account_panel = wrapper
        wrapper.setEnabled(False)

        # طبقِ درخواستِ صریح: کمبویِ گروه باید همیشه (حتی پیش از انتخابِ
        # هیچ گروهی) فعال بماند تا اصلاً بشود گروه را انتخاب کرد -- پس
        # این هدر بیرونِ wrapperِ غیرِفعال‌شدنی قرار می‌گیرد، نه داخلش.
        header = build_page_header(
            "تعریفِ حساب‌هایِ تفصیلی",
            "ساختِ گروهِ تازه و تنظیمِ تعدادِ رقم/بازه/فیلدِ اختصاصی در «پیکربندیِ گروه‌هایِ تفصیلی» انجام می‌شود.",
        )
        header_layout = header.layout()

        group_row = QHBoxLayout()
        group_row.addWidget(QLabel("گروه"))
        self.group_combo = QComboBox()
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)
        group_row.addWidget(self.group_combo, stretch=1)
        open_picker_button = QPushButton("🔍")
        open_picker_button.setObjectName("iconButton")
        open_picker_button.setFixedWidth(44)
        open_picker_button.setToolTip("بازکردنِ حسابِ تفصیلیِ موجود برایِ ویرایش")
        open_picker_button.clicked.connect(self._open_account_picker)
        group_row.addWidget(open_picker_button)
        header_layout.addLayout(group_row)

        combined = QWidget()
        combined_layout = QVBoxLayout(combined)
        combined_layout.setContentsMargins(0, 0, 0, 0)
        combined_layout.setSpacing(12)
        combined_layout.addWidget(header)
        combined_layout.addWidget(wrapper, stretch=1)
        return combined

    # --- تبِ «عکس‌ها و فایل‌ها» (طبقِ درخواستِ صریح: چند عکس + فایلِ
    # کاتالوگ + زوم + عکسِ اصلی، همه در یک تبِ جدا از فیلدهایِ اصلی) -----
    def _build_files_tab(self) -> QWidget:
        tab = QWidget()
        layout = build_section_layout(tab)

        upload_row = QHBoxLayout()
        upload_photo_button = QPushButton("📷 آپلودِ عکس")
        upload_photo_button.clicked.connect(self._upload_photo)
        upload_row.addWidget(upload_photo_button)
        upload_file_button = QPushButton("📎 الصاقِ فایل (کاتالوگ و ...)")
        upload_file_button.clicked.connect(self._upload_file)
        upload_row.addWidget(upload_file_button)
        upload_row.addStretch(1)
        self.files_upload_row_widget = QWidget()
        self.files_upload_row_widget.setLayout(upload_row)
        layout.addWidget(self.files_upload_row_widget)

        self.files_gallery_container = QWidget()
        self.files_gallery_layout = QVBoxLayout(self.files_gallery_container)
        self.files_gallery_layout.setContentsMargins(0, 0, 0, 0)
        self.files_gallery_layout.setSpacing(6)
        self.files_gallery_layout.addStretch(1)

        gallery_scroll = QScrollArea()
        gallery_scroll.setWidgetResizable(True)
        gallery_scroll.setFrameShape(QFrame.NoFrame)
        gallery_scroll.setWidget(self.files_gallery_container)
        layout.addWidget(gallery_scroll, stretch=1)

        self.files_empty_label = QLabel("هنوز عکس یا فایلی برایِ این حساب ثبت نشده.")
        self.files_empty_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.files_empty_label)

        return tab

    def _build_file_row(self, attachment) -> QWidget:
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(4, 4, 4, 4)

        is_image = dimensions_service.is_image_extension(attachment.file_extension)
        if is_image:
            thumb = _ClickableLabel()
            thumb.setFixedSize(56, 56)
            thumb.setAlignment(Qt.AlignCenter)
            thumb.setStyleSheet("border: 1px solid palette(mid); border-radius: 4px;")
            pixmap = QPixmap(attachment.storage_key)
            if not pixmap.isNull():
                thumb.setPixmap(pixmap.scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            thumb.setCursor(Qt.PointingHandCursor)
            thumb.setToolTip("برایِ نمایِ بزرگ کلیک کنید")
            thumb.clicked.connect(lambda a=attachment: self._zoom_photo(a))
            row.addWidget(thumb)
        else:
            file_label = QLabel("📄")
            file_label.setFixedSize(56, 56)
            file_label.setAlignment(Qt.AlignCenter)
            file_label.setStyleSheet("border: 1px solid palette(mid); border-radius: 4px; font-size: 22px;")
            row.addWidget(file_label)

        name_text = attachment.file_name + ("  ⭐ عکسِ اصلی" if attachment.is_primary else "")
        name_label = QLabel(name_text)
        row.addWidget(name_label, stretch=1)

        if is_image and not attachment.is_primary:
            primary_button = QPushButton("⭐ عکسِ اصلی")
            primary_button.clicked.connect(lambda _checked=False, a=attachment: self._set_primary_photo(a.attachment_id))
            row.addWidget(primary_button)
        if not is_image:
            open_button = QPushButton("🔗 بازکردن")
            open_button.clicked.connect(lambda _checked=False, a=attachment: self._open_file(a))
            row.addWidget(open_button)

        remove_button = QPushButton("🚫 حذف")
        remove_button.clicked.connect(lambda _checked=False, a=attachment: self._remove_attachment(a.attachment_id))
        row.addWidget(remove_button)

        return row_widget

    def _refresh_files_tab(self) -> None:
        while self.files_gallery_layout.count() > 1:
            item = self.files_gallery_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if self._selected is None:
            self.account_tabs.setTabVisible(self.account_tabs.indexOf(self.files_tab), False)
            return

        photo_enabled = dimensions_service.get_group_photo_enabled(self._dimension_type_id(), self._person_group_id())
        tab_index = self.account_tabs.indexOf(self.files_tab)
        self.account_tabs.setTabVisible(tab_index, photo_enabled)
        if not photo_enabled:
            return

        # عکس/فایل به detail_account_id متصل می‌شود، نه به فرمِ هنوز-
        # ذخیره‌نشده -- پس برایِ رکوردِ تازه، فقط پیامِ راهنما نشان داده می‌شود.
        can_show = self._editing_account_id is not None
        self.files_upload_row_widget.setVisible(can_show)
        if not can_show:
            self.files_empty_label.setVisible(True)
            self.files_empty_label.setText("برایِ آپلودِ عکس/فایل، اول این حساب را ذخیره کنید.")
            return

        company_id = self._company_id()
        files = dimensions_service.list_detail_account_files(company_id, self._editing_account_id) if company_id else []
        self.files_empty_label.setVisible(not files)
        self.files_empty_label.setText("هنوز عکس یا فایلی برایِ این حساب ثبت نشده.")
        for attachment in files:
            self.files_gallery_layout.insertWidget(self.files_gallery_layout.count() - 1, self._build_file_row(attachment))

    def _zoom_photo(self, attachment) -> None:
        pixmap = QPixmap(attachment.storage_key)
        if pixmap.isNull():
            QMessageBox.warning(self, "خطا", "بارگذاریِ عکس ممکن نشد.")
            return
        dialog = _PhotoZoomDialog(pixmap, attachment.file_name, self)
        dialog.exec()

    def _open_file(self, attachment) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(attachment.storage_key))

    def _upload_photo(self) -> None:
        if self._editing_account_id is None:
            return
        company_id = self._company_id()
        if company_id is None:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "انتخابِ عکس", "", "تصاویر (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"
        )
        if not path:
            return
        try:
            dimensions_service.attach_detail_account_file(
                company_id, self._editing_account_id, session.current_user.user_id, path
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh_files_tab()

    def _upload_file(self) -> None:
        if self._editing_account_id is None:
            return
        company_id = self._company_id()
        if company_id is None:
            return
        path, _filter = QFileDialog.getOpenFileName(self, "انتخابِ فایل", "", "همه‌ی فایل‌ها (*)")
        if not path:
            return
        try:
            dimensions_service.attach_detail_account_file(
                company_id, self._editing_account_id, session.current_user.user_id, path
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh_files_tab()

    def _set_primary_photo(self, attachment_id: int) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        try:
            dimensions_service.set_primary_detail_account_photo(attachment_id, company_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh_files_tab()

    def _remove_attachment(self, attachment_id: int) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        try:
            dimensions_service.delete_detail_account_file(attachment_id, company_id, session.current_user.user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh_files_tab()

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

        pc_button_cluster = QWidget()
        pc_button_cluster.setLayoutDirection(Qt.LeftToRight)
        pc_buttons = QHBoxLayout(pc_button_cluster)
        pc_buttons.setContentsMargins(0, 0, 0, 0)
        add_button = QPushButton("➕")
        add_button.setObjectName("iconButton")
        add_button.setFixedWidth(44)
        add_button.setToolTip("افزودن/به‌روزرسانی")
        add_button.clicked.connect(self._save_pay_component)
        pc_buttons.addWidget(add_button)
        clear_button = QPushButton("↩️")
        clear_button.setObjectName("iconButton")
        clear_button.setFixedWidth(44)
        clear_button.setToolTip("انصراف")
        clear_button.clicked.connect(self._reset_pay_component_form)
        pc_buttons.addWidget(clear_button)
        self.delete_pay_component_button = QPushButton("🗑️")
        self.delete_pay_component_button.setObjectName("dangerIconButton")
        self.delete_pay_component_button.setFixedWidth(44)
        self.delete_pay_component_button.setToolTip("حذفِ ردیف")
        self.delete_pay_component_button.clicked.connect(self._delete_pay_component)
        self.delete_pay_component_button.setVisible(False)
        pc_buttons.addWidget(self.delete_pay_component_button)
        layout.addWidget(pc_button_cluster, alignment=Qt.AlignLeft)

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
                numerals.format_company_amount(c.amount) if c.amount is not None else "—",
                numerals.format_jalali_date(c.effective_from),
                numerals.format_jalali_date(c.effective_to) if c.effective_to else "—",
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

    # --- تبِ «آدرس‌ها» (طبقِ آیتمِ ۱۰ از بازبینیِ «تعریفِ مشتری»، R219):
    # چندآدرسیِ مشتری/تامین‌کننده، هم‌الگو با تبِ «حکمِ حقوق». -----------
    def _build_addresses_tab(self) -> QWidget:
        tab = QWidget()
        layout = build_section_layout(tab)

        layout.addWidget(QLabel("آدرس‌هایِ این حساب — دفتر/فروشگاه/انبار/تحویل/صورتحساب/مرجوعی"))

        self.addresses_table = QTableWidget(0, 4)
        self.addresses_table.setHorizontalHeaderLabels(["نوع", "آدرس", "شهر", "پیش‌فرض"])
        self.addresses_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.addresses_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.addresses_table.verticalHeader().setVisible(False)
        self.addresses_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.addresses_table.cellClicked.connect(self._on_address_row_clicked)
        self.addresses_table.setMaximumHeight(160)
        layout.addWidget(self.addresses_table)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("نوع"))
        self.address_type_combo = QComboBox()
        for code, label in _PARTY_ADDRESS_TYPE_LABELS.items():
            self.address_type_combo.addItem(label, code)
        type_row.addWidget(self.address_type_combo, stretch=1)
        self.address_default_checkbox = QCheckBox("پیش‌فرضِ این نوع")
        type_row.addWidget(self.address_default_checkbox)
        layout.addLayout(type_row)

        self.address_line1_field = QLineEdit()
        self.address_line1_field.setPlaceholderText("متنِ کاملِ آدرس")
        layout.addWidget(self.address_line1_field)

        city_row = QHBoxLayout()
        self.address_city_field = QLineEdit()
        self.address_city_field.setPlaceholderText("شهر")
        city_row.addWidget(self.address_city_field)
        self.address_province_field = QLineEdit()
        self.address_province_field.setPlaceholderText("استان")
        city_row.addWidget(self.address_province_field)
        self.address_postal_code_field = QLineEdit()
        self.address_postal_code_field.setPlaceholderText("کدِپستی")
        city_row.addWidget(self.address_postal_code_field)
        layout.addLayout(city_row)

        gps_row = QHBoxLayout()
        self.address_gps_label = QLabel("موقعیتِ مکانی: ثبت‌نشده")
        gps_row.addWidget(self.address_gps_label, stretch=1)
        pick_on_map_button = QPushButton("انتخاب رویِ نقشه")
        pick_on_map_button.clicked.connect(self._pick_address_location_on_map)
        gps_row.addWidget(pick_on_map_button)
        gps_row.addWidget(QLabel("شعاعِ GeoFence (متر)"))
        self.address_geofence_field = QSpinBox()
        self.address_geofence_field.setRange(0, 100_000)
        self.address_geofence_field.setSpecialValueText("—")
        gps_row.addWidget(self.address_geofence_field)
        layout.addLayout(gps_row)

        self.address_status_label = QLabel("")
        self.address_status_label.setObjectName("statusError")
        self.address_status_label.setWordWrap(True)
        layout.addWidget(self.address_status_label)

        addr_button_cluster = QWidget()
        addr_button_cluster.setLayoutDirection(Qt.LeftToRight)
        addr_buttons = QHBoxLayout(addr_button_cluster)
        addr_buttons.setContentsMargins(0, 0, 0, 0)
        add_address_button = QPushButton("➕")
        add_address_button.setObjectName("iconButton")
        add_address_button.setFixedWidth(44)
        add_address_button.setToolTip("افزودن/به‌روزرسانی")
        add_address_button.clicked.connect(self._save_address)
        addr_buttons.addWidget(add_address_button)
        clear_address_button = QPushButton("↩️")
        clear_address_button.setObjectName("iconButton")
        clear_address_button.setFixedWidth(44)
        clear_address_button.setToolTip("انصراف")
        clear_address_button.clicked.connect(self._reset_address_form)
        addr_buttons.addWidget(clear_address_button)
        self.delete_address_button = QPushButton("🗑️")
        self.delete_address_button.setObjectName("dangerIconButton")
        self.delete_address_button.setFixedWidth(44)
        self.delete_address_button.setToolTip("حذفِ آدرس")
        self.delete_address_button.clicked.connect(self._delete_address)
        self.delete_address_button.setVisible(False)
        addr_buttons.addWidget(self.delete_address_button)
        layout.addWidget(addr_button_cluster, alignment=Qt.AlignLeft)

        layout.addStretch(1)
        return tab

    def _refresh_addresses_tab(self) -> None:
        self._reset_address_form()
        group_code = self._selected[1] if self._selected else None
        is_partner_group = group_code in (dimensions_service.CUSTOMER_GROUP_CODE, dimensions_service.SUPPLIER_GROUP_CODE)
        tab_index = self.account_tabs.indexOf(self.addresses_tab)
        can_show = is_partner_group and self._editing_account_id is not None
        self.account_tabs.setTabVisible(tab_index, can_show)
        if not can_show:
            self._addresses = []
            self.addresses_table.setRowCount(0)
            return
        self._addresses = partners_service.list_party_addresses(self._editing_account_id)
        self.addresses_table.setRowCount(len(self._addresses))
        for row_index, a in enumerate(self._addresses):
            values = [
                _PARTY_ADDRESS_TYPE_LABELS.get(a.address_type_code, a.address_type_code),
                a.line1,
                a.city or "—",
                "بله" if a.is_default else "—",
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, a.address_id)
                self.addresses_table.setItem(row_index, col_index, item)

    def _on_address_row_clicked(self, row: int, _column: int) -> None:
        address_id = self.addresses_table.item(row, 0).data(Qt.UserRole)
        address = next((a for a in self._addresses if a.address_id == address_id), None)
        if address is None:
            return
        self._editing_address_id = address.address_id
        self.address_status_label.setText("")
        index = self.address_type_combo.findData(address.address_type_code)
        self.address_type_combo.setCurrentIndex(index if index >= 0 else 0)
        self.address_line1_field.setText(address.line1 or "")
        self.address_city_field.setText(address.city or "")
        self.address_province_field.setText(address.province or "")
        self.address_postal_code_field.setText(address.postal_code or "")
        self.address_default_checkbox.setChecked(address.is_default)
        self._address_lat = float(address.gps_latitude) if address.gps_latitude is not None else None
        self._address_lon = float(address.gps_longitude) if address.gps_longitude is not None else None
        self._refresh_address_gps_label()
        self.address_geofence_field.setValue(address.geofence_radius_meters or 0)
        self.delete_address_button.setVisible(True)

    def _refresh_address_gps_label(self) -> None:
        if self._address_lat is None or self._address_lon is None:
            self.address_gps_label.setText("موقعیتِ مکانی: ثبت‌نشده")
        else:
            self.address_gps_label.setText(f"موقعیتِ مکانی: {self._address_lat:.6f}, {self._address_lon:.6f}")

    def _pick_address_location_on_map(self) -> None:
        from peecha.ui.map_picker import MapPickerDialog

        dialog = MapPickerDialog(self, initial_lat=self._address_lat, initial_lon=self._address_lon)
        if dialog.exec() == QDialog.Accepted:
            self._address_lat = dialog.result_lat
            self._address_lon = dialog.result_lon
            self._refresh_address_gps_label()

    def _reset_address_form(self) -> None:
        self._editing_address_id = None
        self.address_status_label.setText("")
        self.address_type_combo.setCurrentIndex(0)
        self.address_line1_field.clear()
        self.address_city_field.clear()
        self.address_province_field.clear()
        self.address_postal_code_field.clear()
        self.address_default_checkbox.setChecked(False)
        self._address_lat = None
        self._address_lon = None
        self._refresh_address_gps_label()
        self.address_geofence_field.setValue(0)
        self.delete_address_button.setVisible(False)
        self.addresses_table.clearSelection()

    def _save_address(self) -> None:
        if self._editing_account_id is None:
            return
        address_type_code = self.address_type_combo.currentData()
        line1 = self.address_line1_field.text().strip()
        if not line1:
            self.address_status_label.setText("متنِ آدرس را وارد کنید.")
            return
        lat = decimal.Decimal(str(self._address_lat)) if self._address_lat is not None else None
        lon = decimal.Decimal(str(self._address_lon)) if self._address_lon is not None else None
        geofence = self.address_geofence_field.value() or None
        try:
            if self._editing_address_id is not None:
                partners_service.update_party_address(
                    self._editing_address_id, self._editing_account_id, address_type_code, line1,
                    city=self.address_city_field.text().strip() or None,
                    province=self.address_province_field.text().strip() or None,
                    postal_code=self.address_postal_code_field.text().strip() or None,
                    is_default=self.address_default_checkbox.isChecked(),
                    gps_latitude=lat, gps_longitude=lon, geofence_radius_meters=geofence,
                )
            else:
                partners_service.add_party_address(
                    self._editing_account_id, address_type_code, line1,
                    city=self.address_city_field.text().strip() or None,
                    province=self.address_province_field.text().strip() or None,
                    postal_code=self.address_postal_code_field.text().strip() or None,
                    is_default=self.address_default_checkbox.isChecked(),
                    gps_latitude=lat, gps_longitude=lon, geofence_radius_meters=geofence,
                )
        except ValueError as exc:
            self.address_status_label.setText(str(exc))
            return
        self._refresh_addresses_tab()

    def _delete_address(self) -> None:
        if self._editing_address_id is None or self._editing_account_id is None:
            return
        confirm = QMessageBox.question(
            self, "حذفِ آدرس", "این آدرس حذف شود؟", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        partners_service.delete_party_address(self._editing_address_id, self._editing_account_id)
        self._refresh_addresses_tab()

    # --- تبِ «ضمانت‌ها» (طبقِ آیتمِ ۲ از بازخوردِ کاربر رویِ R220): سفته/
    # ضامن/وثیقه/چکِ تضمینی روی خودِ مشتری -- فقط برایِ گروهِ CUSTOMER،
    # هم‌الگو با تبِ «آدرس‌ها». ---------------------------------------
    def _build_guarantees_tab(self) -> QWidget:
        tab = QWidget()
        layout = build_section_layout(tab)

        self.guarantees_summary_label = QLabel("")
        layout.addWidget(self.guarantees_summary_label)

        self.guarantees_table = QTableWidget(0, 4)
        self.guarantees_table.setHorizontalHeaderLabels(["نوع", "مبلغ", "وضعیت", "تاریخِ انقضا"])
        self.guarantees_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.guarantees_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.guarantees_table.verticalHeader().setVisible(False)
        self.guarantees_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.guarantees_table.cellClicked.connect(self._on_guarantee_row_clicked)
        self.guarantees_table.setMaximumHeight(150)
        layout.addWidget(self.guarantees_table)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("نوع"))
        self.guarantee_type_combo = QComboBox()
        for code, label in _GUARANTEE_TYPE_LABELS.items():
            self.guarantee_type_combo.addItem(label, code)
        type_row.addWidget(self.guarantee_type_combo, stretch=1)
        type_row.addWidget(QLabel("مبلغ"))
        self.guarantee_amount_field = QDoubleSpinBox()
        self.guarantee_amount_field.setRange(0, 1_000_000_000_000)
        self.guarantee_amount_field.setDecimals(0)
        type_row.addWidget(self.guarantee_amount_field, stretch=1)
        layout.addLayout(type_row)

        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("تاریخِ انقضا"))
        self.guarantee_valid_until_field = JalaliDateEdit()
        date_row.addWidget(self.guarantee_valid_until_field)
        self.guarantee_no_expiry_checkbox = QCheckBox("بدونِ تاریخِ انقضا")
        self.guarantee_no_expiry_checkbox.setChecked(True)
        self.guarantee_no_expiry_checkbox.toggled.connect(
            lambda checked: self.guarantee_valid_until_field.setEnabled(not checked)
        )
        self.guarantee_valid_until_field.setEnabled(False)
        date_row.addWidget(self.guarantee_no_expiry_checkbox)
        layout.addLayout(date_row)

        bank_row = QHBoxLayout()
        bank_row.addWidget(QLabel("بانک (چک/ضمانت‌نامه)"))
        self.guarantee_bank_combo = QComboBox()
        bank_row.addWidget(self.guarantee_bank_combo, stretch=1)
        layout.addLayout(bank_row)

        check_row = QHBoxLayout()
        self.guarantee_check_no_field = QLineEdit()
        self.guarantee_check_no_field.setPlaceholderText("شماره‌یِ چک/سفته")
        check_row.addWidget(self.guarantee_check_no_field)
        check_row.addWidget(QLabel("سررسید"))
        self.guarantee_check_due_field = JalaliDateEdit()
        check_row.addWidget(self.guarantee_check_due_field)
        layout.addLayout(check_row)

        self.guarantee_description_field = QLineEdit()
        self.guarantee_description_field.setPlaceholderText("توضیح")
        layout.addWidget(self.guarantee_description_field)

        self.guarantee_status_label = QLabel("")
        self.guarantee_status_label.setObjectName("statusError")
        self.guarantee_status_label.setWordWrap(True)
        layout.addWidget(self.guarantee_status_label)

        button_row = QHBoxLayout()
        add_guarantee_button = QPushButton("➕ ثبتِ ضمانتِ تازه")
        add_guarantee_button.clicked.connect(self._save_guarantee)
        button_row.addWidget(add_guarantee_button)
        self.guarantee_release_status_combo = QComboBox()
        for code, label in _GUARANTEE_RELEASE_STATUS_OPTIONS:
            self.guarantee_release_status_combo.addItem(label, code)
        button_row.addWidget(self.guarantee_release_status_combo)
        self.release_guarantee_button = QPushButton("بستنِ ضمانتِ انتخاب‌شده")
        self.release_guarantee_button.clicked.connect(self._release_guarantee)
        self.release_guarantee_button.setVisible(False)
        button_row.addWidget(self.release_guarantee_button)
        layout.addLayout(button_row)

        layout.addStretch(1)
        return tab

    def _refresh_guarantees_tab(self) -> None:
        self._reset_guarantee_form()
        group_code = self._selected[1] if self._selected else None
        tab_index = self.account_tabs.indexOf(self.guarantees_tab)
        can_show = group_code == dimensions_service.CUSTOMER_GROUP_CODE and self._editing_account_id is not None
        self.account_tabs.setTabVisible(tab_index, can_show)
        company_id = self._company_id()
        self.guarantee_bank_combo.clear()
        self.guarantee_bank_combo.addItem("—", None)
        if company_id is not None:
            for bank in treasury_service.list_banks(company_id, active_only=True):
                self.guarantee_bank_combo.addItem(bank.name, bank.bank_id)
        if not can_show:
            self._guarantees = []
            self.guarantees_table.setRowCount(0)
            self.guarantees_summary_label.setText("")
            return
        self._guarantees = partners_service.list_customer_guarantees(self._editing_account_id)
        total_active = partners_service.total_active_guarantee_amount(self._editing_account_id)
        self.guarantees_summary_label.setText(f"جمعِ ضمانتِ فعال: {numerals.format_company_amount(total_active)}")
        self.guarantees_table.setRowCount(len(self._guarantees))
        for row_index, g in enumerate(self._guarantees):
            values = [
                _GUARANTEE_TYPE_LABELS.get(g.guarantee_type_code, g.guarantee_type_code),
                numerals.format_company_amount(g.amount),
                _GUARANTEE_STATUS_LABELS.get(g.status_code, g.status_code),
                numerals.format_jalali_date(g.valid_until_date) if g.valid_until_date else "—",
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, g.guarantee_id)
                self.guarantees_table.setItem(row_index, col_index, item)

    def _on_guarantee_row_clicked(self, row: int, _column: int) -> None:
        guarantee_id = self.guarantees_table.item(row, 0).data(Qt.UserRole)
        guarantee = next((g for g in self._guarantees if g.guarantee_id == guarantee_id), None)
        if guarantee is None:
            return
        self._selected_guarantee_id = guarantee.guarantee_id
        self.guarantee_status_label.setText("")
        self.release_guarantee_button.setVisible(guarantee.status_code == "ACTIVE")

    def _reset_guarantee_form(self) -> None:
        self._selected_guarantee_id = None
        self.guarantee_status_label.setText("")
        self.guarantee_type_combo.setCurrentIndex(0)
        self.guarantee_amount_field.setValue(0)
        self.guarantee_no_expiry_checkbox.setChecked(True)
        self.guarantee_check_no_field.clear()
        self.guarantee_description_field.clear()
        self.release_guarantee_button.setVisible(False)
        self.guarantees_table.clearSelection()

    def _save_guarantee(self) -> None:
        if self._editing_account_id is None:
            return
        company_id = self._company_id()
        if company_id is None:
            return
        amount = decimal.Decimal(str(self.guarantee_amount_field.value()))
        valid_until = None if self.guarantee_no_expiry_checkbox.isChecked() else self.guarantee_valid_until_field.date()
        try:
            partners_service.add_customer_guarantee(
                company_id, self._editing_account_id, self.guarantee_type_combo.currentData(), amount,
                session.current_user.user_id, valid_until_date=valid_until,
                bank_id=self.guarantee_bank_combo.currentData(),
                check_no=self.guarantee_check_no_field.text().strip() or None,
                check_due_date=self.guarantee_check_due_field.date(),
                description=self.guarantee_description_field.text().strip() or None,
            )
        except ValueError as exc:
            self.guarantee_status_label.setText(str(exc))
            return
        self._refresh_guarantees_tab()

    def _release_guarantee(self) -> None:
        if self._selected_guarantee_id is None:
            return
        status_code = self.guarantee_release_status_combo.currentData()
        try:
            partners_service.release_customer_guarantee(
                self._selected_guarantee_id, self._company_id(), session.current_user.user_id, status_code=status_code
            )
        except ValueError as exc:
            self.guarantee_status_label.setText(str(exc))
            return
        self._refresh_guarantees_tab()

    # --- تبِ «قراردادها» (طبقِ آیتمِ ۳ از همان بازخورد): قراردادِ
    # نمایندگی/سازمانی/سهمیه، برایِ مشتری (SALES) و تامین‌کننده (PURCHASE). --
    def _build_contracts_tab(self) -> QWidget:
        tab = QWidget()
        layout = build_section_layout(tab)

        self.contracts_table = QTableWidget(0, 4)
        self.contracts_table.setHorizontalHeaderLabels(["دسته", "وضعیت", "سهمیه‌یِ مبلغی", "مصرف‌شده"])
        self.contracts_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.contracts_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.contracts_table.verticalHeader().setVisible(False)
        self.contracts_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.contracts_table.cellClicked.connect(self._on_contract_row_clicked)
        self.contracts_table.setMaximumHeight(150)
        layout.addWidget(self.contracts_table)

        cat_row = QHBoxLayout()
        cat_row.addWidget(QLabel("دسته"))
        self.contract_category_combo = QComboBox()
        for code, label in _CONTRACT_CATEGORY_OPTIONS:
            self.contract_category_combo.addItem(label, code)
        cat_row.addWidget(self.contract_category_combo, stretch=1)
        layout.addLayout(cat_row)

        dates_row = QHBoxLayout()
        dates_row.addWidget(QLabel("از تاریخ"))
        self.contract_valid_from_field = JalaliDateEdit()
        dates_row.addWidget(self.contract_valid_from_field)
        dates_row.addWidget(QLabel("تا تاریخ"))
        self.contract_valid_to_field = JalaliDateEdit()
        dates_row.addWidget(self.contract_valid_to_field)
        self.contract_unbounded_checkbox = QCheckBox("تا اطلاعِ ثانوی")
        self.contract_unbounded_checkbox.setChecked(True)
        self.contract_unbounded_checkbox.toggled.connect(
            lambda checked: self.contract_valid_to_field.setEnabled(not checked)
        )
        self.contract_valid_to_field.setEnabled(False)
        dates_row.addWidget(self.contract_unbounded_checkbox)
        layout.addLayout(dates_row)

        amount_row = QHBoxLayout()
        amount_row.addWidget(QLabel("سهمیه‌یِ مبلغی (اختیاری)"))
        self.contract_committed_amount_field = QDoubleSpinBox()
        self.contract_committed_amount_field.setRange(0, 1_000_000_000_000)
        self.contract_committed_amount_field.setDecimals(0)
        amount_row.addWidget(self.contract_committed_amount_field, stretch=1)
        layout.addLayout(amount_row)

        item_row = QHBoxLayout()
        item_row.addWidget(QLabel("کالایِ خاص (اختیاری)"))
        self.contract_item_combo = QComboBox()
        item_row.addWidget(self.contract_item_combo, stretch=2)
        item_row.addWidget(QLabel("سهمیه‌یِ تعدادی"))
        self.contract_committed_quantity_field = QDoubleSpinBox()
        self.contract_committed_quantity_field.setRange(0, 1_000_000_000)
        self.contract_committed_quantity_field.setDecimals(2)
        item_row.addWidget(self.contract_committed_quantity_field, stretch=1)
        layout.addLayout(item_row)

        self.contract_commitments_field = QLineEdit()
        self.contract_commitments_field.setPlaceholderText("تعهداتِ متنیِ قرارداد")
        layout.addWidget(self.contract_commitments_field)

        self.contract_status_label = QLabel("")
        self.contract_status_label.setObjectName("statusError")
        self.contract_status_label.setWordWrap(True)
        layout.addWidget(self.contract_status_label)

        button_row = QHBoxLayout()
        add_contract_button = QPushButton("➕ ثبتِ قراردادِ تازه")
        add_contract_button.clicked.connect(self._save_contract)
        button_row.addWidget(add_contract_button)
        self.cancel_contract_button = QPushButton("لغوِ قراردادِ انتخاب‌شده")
        self.cancel_contract_button.clicked.connect(self._cancel_contract)
        self.cancel_contract_button.setVisible(False)
        button_row.addWidget(self.cancel_contract_button)
        layout.addLayout(button_row)

        layout.addStretch(1)
        return tab

    def _contract_type_for_current_group(self) -> str | None:
        group_code = self._selected[1] if self._selected else None
        if group_code == dimensions_service.CUSTOMER_GROUP_CODE:
            return "SALES"
        if group_code == dimensions_service.SUPPLIER_GROUP_CODE:
            return "PURCHASE"
        return None

    def _refresh_contracts_tab(self) -> None:
        self._reset_contract_form()
        contract_type = self._contract_type_for_current_group()
        tab_index = self.account_tabs.indexOf(self.contracts_tab)
        can_show = contract_type is not None and self._editing_account_id is not None
        self.account_tabs.setTabVisible(tab_index, can_show)
        company_id = self._company_id()
        self.contract_item_combo.clear()
        self.contract_item_combo.addItem("—", None)
        if company_id is not None:
            for item in catalog_service.list_items(company_id, transactable_only=True):
                self.contract_item_combo.addItem(f"{item.code} — {item.name}", item.item_id)
        if not can_show:
            self._contracts = []
            self.contracts_table.setRowCount(0)
            return
        self._contracts = [
            c for c in contracts_service.list_contracts(company_id, counterparty_detail_account_id=self._editing_account_id)
            if c.contract_type_code == contract_type
        ]
        self.contracts_table.setRowCount(len(self._contracts))
        for row_index, c in enumerate(self._contracts):
            values = [
                _CONTRACT_CATEGORY_LABELS.get(c.contract_category_code, c.contract_category_code),
                _CONTRACT_STATUS_LABELS.get(c.status_code, c.status_code),
                numerals.format_company_amount(c.committed_amount) if c.committed_amount is not None else "—",
                numerals.format_company_amount(c.consumed_amount) if c.consumed_amount is not None else "—",
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, c.contract_id)
                self.contracts_table.setItem(row_index, col_index, item)

    def _on_contract_row_clicked(self, row: int, _column: int) -> None:
        contract_id = self.contracts_table.item(row, 0).data(Qt.UserRole)
        contract = next((c for c in self._contracts if c.contract_id == contract_id), None)
        if contract is None:
            return
        self._selected_contract_id = contract.contract_id
        self.contract_status_label.setText("")
        self.cancel_contract_button.setVisible(contract.status_code == "ACTIVE")

    def _reset_contract_form(self) -> None:
        self._selected_contract_id = None
        self.contract_status_label.setText("")
        self.contract_category_combo.setCurrentIndex(0)
        self.contract_valid_from_field.setDate(datetime.date.today())
        self.contract_unbounded_checkbox.setChecked(True)
        self.contract_committed_amount_field.setValue(0)
        self.contract_committed_quantity_field.setValue(0)
        self.contract_commitments_field.clear()
        self.cancel_contract_button.setVisible(False)
        self.contracts_table.clearSelection()

    def _save_contract(self) -> None:
        if self._editing_account_id is None:
            return
        company_id = self._company_id()
        contract_type = self._contract_type_for_current_group()
        if company_id is None or contract_type is None:
            return
        valid_to = None if self.contract_unbounded_checkbox.isChecked() else self.contract_valid_to_field.date()
        committed_amount = (
            decimal.Decimal(str(self.contract_committed_amount_field.value()))
            if self.contract_committed_amount_field.value() else None
        )
        item_id = self.contract_item_combo.currentData()
        committed_quantity = (
            decimal.Decimal(str(self.contract_committed_quantity_field.value()))
            if item_id is not None and self.contract_committed_quantity_field.value() else None
        )
        try:
            contracts_service.create_contract(
                company_id, contract_type, self._editing_account_id, self.contract_valid_from_field.date(),
                item_id=item_id, committed_quantity=committed_quantity, valid_to=valid_to,
                contract_category_code=self.contract_category_combo.currentData(),
                committed_amount=committed_amount,
                commitments_text=self.contract_commitments_field.text().strip() or None,
            )
        except ValueError as exc:
            self.contract_status_label.setText(str(exc))
            return
        self._refresh_contracts_tab()

    def _cancel_contract(self) -> None:
        if self._selected_contract_id is None:
            return
        confirm = QMessageBox.question(
            self, "لغوِ قرارداد", "این قرارداد لغو شود؟", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        contracts_service.cancel_contract(self._selected_contract_id, self._company_id())
        self._refresh_contracts_tab()

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

    def _is_inventory_item_group(self) -> bool:
        """طبقِ ادغامِ فرمِ «کالا و خدمت»: برخلافِ CUSTOMER/SUPPLIER/PERSONNEL
        (که زیرِ نوع‌بُعدِ سیستمیِ PERSON‌اند و در _PERSON_GROUP_META جا
        می‌شوند)، INVENTORY_ITEM یک DetailDimensionType کاملاً جداست — پس
        یک مسیرِ شرطیِ موازی و مستقل لازم است."""
        if self._selected is None or self._selected[0] != "dim":
            return False
        return any(
            t.dimension_type_id == self._selected[1] and t.code == dimensions_service.INVENTORY_ITEM_CODE
            for t in self._types
        )

    def _render_item_panel(self, item_row: catalog_service.ItemRow | None = None) -> None:
        """نمایش/مخفی‌کردنِ پنلِ اختصاصیِ کالا — فقط وقتی گروهِ انتخاب‌شده
        INVENTORY_ITEM باشد و سطحِ درحالِ‌ساخت/ویرایش، سطحِ‌آخر باشد
        (دقیقاً هم‌شرطِ is_leaf_level در _render_person_fields/_render_extra_fields)."""
        # طبقِ رفعِ باگِ احتمالی: قفلِ زیر فقط باید هنگامِ *ویرایشِ* واقعیِ
        # یک متغیرِ ازپیش‌موجود اعمال شود -- نه هنگامِ «کپی از» یک متغیر
        # به‌عنوانِ نمونه برایِ ساختنِ یک رکوردِ کاملاً تازه (که در آن حالت
        # self._editing_account_id هنوز None است).
        is_variant = (
            self._editing_account_id is not None
            and item_row is not None
            and item_row.variant_parent_item_id is not None
        )
        self._apply_variant_lock(is_variant)
        if not self._is_inventory_item_group():
            self.item_detail_panel.setVisible(False)
            self.item_level_hint_label.setVisible(False)
            return
        is_leaf_level = self._current_level_no() >= self._current_max_level_no
        self.item_detail_panel.setVisible(is_leaf_level)
        self.item_level_hint_label.setVisible(not is_leaf_level or is_variant)
        if not is_leaf_level:
            self.item_level_hint_label.setText(
                f"این یک سطحِ دسته‌بندی است، نه خودِ کالا (سطحِ فعلی: {self._current_level_no()} از "
                f"{self._current_max_level_no}). برایِ تعریفِ کالا، یک زیرمجموعه در همین سطح بسازید تا به "
                "سطحِ آخر برسید؛ یا اگر نمی‌خواهید دسته‌بندی داشته باشید، تعدادِ سطوحِ گروهِ «کالا» را در "
                "«تنظیماتِ گروه‌هایِ تفصیلی» به ۱ کاهش دهید."
            )
            return
        company_id = self._company_id()
        if company_id is not None:
            self.item_detail_panel.refresh(company_id)
        self.item_detail_panel.load(item_row)
        if is_variant:
            # طبقِ درخواستِ صریح («فقط کالایِ اصلی امکانِ ویرایش را داشته
            # باشد، متغیرها همه از کالایِ اصلی ارث ببرند»): این ردیف خودش
            # یک متغیر است -- ویرایشِ مستقیمِ فیلدهایِ عمومیِ آن از همین‌جا
            # ممنوع می‌شود (هم چون منطقاً همه‌چیز باید از کالایِ اصلی ارث
            # برود، هم چون همین مسیر پیش‌تر باعثِ یتیم‌شدنِ متغیر از کالایِ
            # اصلی‌اش و کرشِ گزارش‌شده می‌شد) -- توضیحات/قیمت/عکسِ مخصوصِ
            # همین متغیر هم‌چنان از تبِ «ویژگی‌ها و متغیرها»یِ خودِ کالایِ
            # اصلی قابلِ‌ویرایش است.
            self.item_level_hint_label.setText(
                "این یک «متغیر» است، نه خودِ کالایِ اصلی — همه‌یِ ویژگی‌هایِ این‌جا از کالایِ اصلی به ارث "
                "می‌رسند و مستقیماً قابلِ‌ویرایش نیستند. برایِ تغییرِ توضیحات/قیمت/عکسِ همین متغیر یا حذفِ آن، "
                "به تبِ «ویژگی‌ها و متغیرها»یِ کالایِ اصلی مراجعه کنید."
            )

    def _apply_variant_lock(self, is_variant: bool) -> None:
        """قفل‌کردنِ فرمِ عمومیِ حسابِ تفصیلی وقتی رکوردِ درحالِ‌ویرایش خودش
        یک «متغیر» است -- طبقِ توضیحِ _render_item_panel."""
        self.account_code_field.setEnabled(not is_variant)
        self.account_name_field.setEnabled(not is_variant)
        self.account_active_checkbox.setEnabled(not is_variant)
        self.item_detail_panel.setEnabled(not is_variant)
        self.save_button.setEnabled(not is_variant)
        if is_variant:
            self.delete_button.setEnabled(False)
            self.delete_button.setToolTip("حذفِ متغیر فقط از تبِ «ویژگی‌ها و متغیرها»یِ کالایِ اصلی ممکن است.")
        else:
            self.delete_button.setEnabled(True)
            self.delete_button.setToolTip("حذف")

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

        self._item_rows_by_detail_id = (
            {r.item_detail_account_id: r for r in catalog_service.list_items(company_id)}
            if self._is_inventory_item_group() else {}
        )

        if self._is_person():
            rows = self._person_meta()["list_fn"](company_id)
            self._person_rows_by_id = {r["detail_account_id"]: r for r in rows}
            self._accounts_by_id = {}
        else:
            rows = dimensions_service.list_detail_accounts(company_id, dimension_type_id)
            if self._is_inventory_item_group():
                # طبقِ درخواستِ صریح («متغیرها دیگر بعنوانِ تفصیلی معرفی
                # نشوند»): ردیفِ تفصیلیِ فنیِ زیرینِ یک متغیر (که فقط برایِ
                # threadingِ بُعدِ حسابداری در پس‌زمینه نگه داشته می‌شود --
                # جدولِ inv.item_variants نمایندهٔ واقعیِ آن است) دیگر
                # هرگز در این درخت/فهرست/کمبوهایِ همین صفحه ظاهر نمی‌شود.
                rows = [
                    r for r in rows
                    if (item_row := self._item_rows_by_detail_id.get(r.detail_account_id)) is None
                    or item_row.variant_parent_item_id is None
                ]
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

        # طبقِ درخواستِ صریح («کپی از تفصیلی‌هایِ دیگر»): همه‌یِ حساب‌هایِ
        # همین گروه (در هر سطحی) به‌عنوانِ نمونه‌یِ کپی در دسترس‌اند.
        self.copy_from_combo.blockSignals(True)
        self.copy_from_combo.clear()
        self.copy_from_combo.addItem("— انتخابِ نمونه برایِ کپی —", None)
        if self._is_person():
            for r in rows:
                if r["detail_account_id"] != self._editing_account_id:
                    self.copy_from_combo.addItem(f"{r['full_code']} — {r['name'] or ''}", r["detail_account_id"])
        else:
            for r in rows:
                if r.detail_account_id != self._editing_account_id:
                    self.copy_from_combo.addItem(f"{r.full_code} — {r.name or ''}", r.detail_account_id)
        self.copy_from_combo.blockSignals(False)
        self.copy_from_widget.setVisible(self._editing_account_id is None)

        self._rebuild_accounts_tree()
        self._render_person_fields()
        self._render_extra_fields()
        self._render_item_panel()
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
        is_item_view = self._is_inventory_item_group()
        if is_personnel_view:
            columns = _COLUMNS + _PERSONNEL_EXTRA_COLUMNS
        elif is_item_view:
            columns = _COLUMNS + _ITEM_EXTRA_COLUMNS
        else:
            columns = _COLUMNS
        self.accounts_table.setColumnCount(len(columns))
        self.accounts_table.setHeaderLabels(columns)

        if self._is_person():
            rows = [
                (
                    r["detail_account_id"], r["parent_detail_account_id"], r["full_code"], r["name"],
                    r["level_no"], r["is_active"],
                    r.get("org_unit_name") or "—", r.get("position_name") or "—",
                    numerals.format_company_amount(r["base_salary"]) if r.get("base_salary") is not None else "—",
                    _EMPLOYEE_STATUS_LABELS.get(r.get("employee_status"), "—"),
                )
                for r in self._person_rows_by_id.values()
            ]
        elif is_item_view:
            rows = []
            for r in self._accounts_by_id.values():
                item_row = self._item_rows_by_detail_id.get(r.detail_account_id)
                if item_row is None:
                    extra = ("—", "—", "—")
                else:
                    extra = (
                        _KIND_LABELS.get(item_row.item_kind_code, item_row.item_kind_code),
                        item_row.base_uom_code or "—",
                        _LIFECYCLE_LABELS.get(item_row.lifecycle_status_code, item_row.lifecycle_status_code),
                    )
                rows.append((r.detail_account_id, r.parent_detail_account_id, r.full_code, r.name, r.level_no, r.is_active, *extra))
        else:
            rows = [
                (r.detail_account_id, r.parent_detail_account_id, r.full_code, r.name, r.level_no, r.is_active)
                for r in self._accounts_by_id.values()
            ]

        # طبقِ درخواستِ صریح («بندانگشتی کنارِ نام»): عکسِ اصلیِ هر حساب
        # (اگر گروه این امکان را روشن کرده و آن حساب عکسِ اصلی دارد) به‌
        # صورتِ آیکونِ کوچک کنارِ ستونِ «نام» نشان داده می‌شود — یک واکشیِ
        # دسته‌ای، نه یک کوئریِ جدا به‌ازایِ هر ردیف.
        photo_enabled = dimensions_service.get_group_photo_enabled(self._dimension_type_id(), self._person_group_id())
        primary_photos: dict[int, object] = {}
        if photo_enabled:
            company_id = self._company_id()
            if company_id is not None:
                primary_photos = dimensions_service.get_primary_photos_for_accounts(
                    company_id, [row[0] for row in rows]
                )

        def make_item(row: tuple) -> QTreeWidgetItem:
            detail_account_id, _parent_id, full_code, name, level_no, is_active = row[:6]
            values = [full_code, name or "—", str(level_no), "فعال" if is_active else "غیرفعال"]
            if is_personnel_view or is_item_view:
                values.extend(row[6:])
            item = QTreeWidgetItem(values)
            item.setData(0, Qt.UserRole, detail_account_id)
            if color:
                for col in range(len(columns)):
                    item.setForeground(col, QBrush(QColor(color)))
            photo = primary_photos.get(detail_account_id)
            if photo is not None:
                pixmap = QPixmap(photo.storage_key)
                if not pixmap.isNull():
                    item.setIcon(1, QIcon(pixmap.scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
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
        self._render_item_panel()

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
                result[field_key] = widget.date()
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
                result[key] = widget.date()
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
        try:
            self.edit_detail_account(detail_account_id)
        except Exception:
            # طبقِ رفعِ باگِ گزارش‌شده («کلیک رویِ یک ردیفِ دیالوگِ جستجو
            # کرش می‌کند»): این متد از یک اسلاتِ Qt (itemClicked) صدا زده
            # می‌شود -- یک استثنایِ پیش‌بینی‌نشده این‌جا هرگز نباید بی‌صدا
            # کرش کند یا بلعیده شود؛ ردش رویِ کنسول چاپ و پیامی به کاربر
            # نشان داده می‌شود.
            traceback.print_exc()
            self.account_status_label.setText(
                "بارگذاریِ این حساب با خطا مواجه شد؛ لطفاً دوباره تلاش کنید."
            )

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
            self._refresh_files_tab()
            self._refresh_addresses_tab()
            self._refresh_guarantees_tab()
            self._refresh_contracts_tab()
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
        item_row = None
        if self._is_inventory_item_group():
            item_row = catalog_service.get_item_row_by_detail_account_id(self._company_id(), detail_account_id)
        self._render_item_panel(item_row)
        self.delete_button.setVisible(True)
        self.terminate_employee_button.setVisible(False)
        self._refresh_pay_components_section(None)
        self._refresh_files_tab()
        self._refresh_addresses_tab()
        self._refresh_guarantees_tab()
        self._refresh_contracts_tab()

    def _on_copy_from_changed(self) -> None:
        source_id = self.copy_from_combo.currentData()
        if source_id is None:
            return
        self._apply_copy_from(source_id)
        # طبقِ طراحی: این کمبو فقط یک محرکِ یک‌باره است، نه یک انتخابِ
        # پایدار -- بعدِ اعمالِ کپی به حالتِ «— انتخابِ نمونه... —» برمی‌گردد
        # تا کاربر بتواند دوباره از نمونه‌یِ دیگری هم کپی کند.
        self.copy_from_combo.blockSignals(True)
        self.copy_from_combo.setCurrentIndex(0)
        self.copy_from_combo.blockSignals(False)

    def _apply_copy_from(self, source_id: int) -> None:
        """طبقِ درخواستِ صریح («بشه از تفصیلی‌هایِ دیگر کپی کرد»): تمامِ
        فیلدهایِ یک حسابِ تفصیلیِ موجود -- بجز کد، که باید یکتا بماند و
        دوباره پیشنهاد می‌شود -- در فرمِ «حسابِ تفصیلیِ جدید» از پیش پر
        می‌شود. فقط وقتی معنا دارد که در حالِ ساختنِ رکوردِ تازه باشیم
        (نه ویرایشِ یک رکوردِ موجود) -- copy_from_widget هم دقیقاً به
        همین شرط پنهان/نمایان می‌شود."""
        if self._editing_account_id is not None:
            return
        if self._is_person():
            row = self._person_rows_by_id.get(source_id)
            if row is None:
                return
            self.account_name_field.setText(row["name"] or "")
            self.account_active_checkbox.setChecked(row["is_active"])
            parent_id = row.get("parent_detail_account_id")
            index = self.parent_combo.findData(parent_id) if parent_id is not None else 0
            self.parent_combo.setCurrentIndex(index if index >= 0 else 0)
            self._render_person_fields(row)
            self._render_extra_fields(row.get("custom_fields"))
        else:
            account = self._accounts_by_id.get(source_id)
            if account is None:
                return
            self.account_name_field.setText(account.name or "")
            self.account_active_checkbox.setChecked(account.is_active)
            if account.parent_detail_account_id is not None:
                index = self.parent_combo.findData(account.parent_detail_account_id)
                self.parent_combo.setCurrentIndex(index if index >= 0 else 0)
            else:
                self.parent_combo.setCurrentIndex(0)
            self._render_extra_fields(account.extra_fields)
            item_row = None
            if self._is_inventory_item_group():
                item_row = self._item_rows_by_detail_id.get(source_id)
            self._render_item_panel(item_row)
        self._suggest_code_for_current_parent()

    def _update_partner_status_display(self, row: dict) -> None:
        group_code = self._selected[1] if self._selected else None
        is_partner_group = group_code in (dimensions_service.CUSTOMER_GROUP_CODE, dimensions_service.SUPPLIER_GROUP_CODE)
        status_code = row.get("status_code") if is_partner_group else None
        if status_code is None:
            self.partner_status_label.setVisible(False)
            self.approve_partner_button.setVisible(False)
        else:
            self.partner_status_label.setText(f"وضعیتِ اعتباری: {_PARTNER_STATUS_LABELS.get(status_code, status_code)}")
            self.partner_status_label.setVisible(True)
            self.approve_partner_button.setVisible(status_code == "PENDING_APPROVAL")

        company_id = self._company_id()
        is_customer = group_code == dimensions_service.CUSTOMER_GROUP_CODE
        detail_account_id = row.get("detail_account_id")
        score_row = (
            assistant_service.get_customer_score(company_id, detail_account_id)
            if is_customer and company_id is not None and detail_account_id is not None
            else None
        )
        if score_row is None:
            self.customer_score_label.setVisible(False)
            return
        self.customer_score_label.setText(
            f"امتیازِ مشتری: {score_row.emoji} {score_row.score} ({score_row.tier_label})"
        )
        self.customer_score_label.setVisible(True)

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
        self.copy_from_widget.setVisible(True)
        self.copy_from_combo.blockSignals(True)
        self.copy_from_combo.setCurrentIndex(0)
        self.copy_from_combo.blockSignals(False)
        self.account_status_label.setText("")
        self.account_code_field.clear()
        self.account_name_field.clear()
        self.account_active_checkbox.setChecked(True)
        self.parent_combo.setEnabled(True)
        if self.parent_combo.count():
            self.parent_combo.setCurrentIndex(0)
        self._render_person_fields()
        self._render_extra_fields()
        self._render_item_panel()
        self._refresh_pay_components_section(None)
        self._suggest_code_for_current_parent()
        self.accounts_table.clearSelection()
        self.delete_button.setVisible(False)
        self.terminate_employee_button.setVisible(False)
        self.partner_status_label.setVisible(False)
        self.approve_partner_button.setVisible(False)
        self.customer_score_label.setVisible(False)
        self._refresh_files_tab()
        self._refresh_addresses_tab()
        self._refresh_guarantees_tab()
        self._refresh_contracts_tab()

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
        if self._is_inventory_item_group() and self._editing_account_id is not None:
            existing = catalog_service.get_item_row_by_detail_account_id(company_id, self._editing_account_id)
            if existing is not None and existing.variant_parent_item_id is not None:
                self.account_status_label.setText(
                    "این یک متغیر است؛ فقط از تبِ «ویژگی‌ها و متغیرها»یِ کالایِ اصلی قابلِ‌ویرایش است."
                )
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
            elif self._is_inventory_item_group() and self._current_level_no() >= self._current_max_level_no:
                # طبقِ طراحیِ ادغام: create_item/update_item فقط برایِ
                # سطحِ‌آخر صدا زده می‌شوند؛ گره‌هایِ میانیِ گروه‌بندیِ کالا
                # از همان مسیرِ عمومیِ زیر (elif/else بعدی) رد می‌شوند.
                item_fields = self.item_detail_panel.collect_fields()
                if self._editing_account_id is not None:
                    item = catalog_service.get_item_row_by_detail_account_id(company_id, self._editing_account_id)
                    if item is None:
                        raise ValueError("کالا یافت نشد.")
                    catalog_service.update_item(
                        item.item_id, company_id, code, name or "", self.account_active_checkbox.isChecked(),
                        self.item_detail_panel.lifecycle_status_code(), item_fields,
                    )
                else:
                    catalog_service.create_item(
                        company_id, code, name or "", item_fields,
                        parent_detail_account_id=self.parent_combo.currentData(),
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
        if self._is_inventory_item_group():
            existing = catalog_service.get_item_row_by_detail_account_id(company_id, self._editing_account_id)
            if existing is not None and existing.variant_parent_item_id is not None:
                self.account_status_label.setText(
                    "این یک متغیر است؛ فقط از تبِ «ویژگی‌ها و متغیرها»یِ کالایِ اصلی قابلِ‌حذف است."
                )
                return
        confirm = QMessageBox.question(
            self, "حذف", "این حساب حذف شود؟ این کار قابلِ بازگشت نیست.", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            if self._is_person():
                self._person_meta()["delete_fn"](self._editing_account_id, company_id)
            elif self._is_inventory_item_group():
                item = catalog_service.get_item_row_by_detail_account_id(company_id, self._editing_account_id)
                if item is not None:
                    catalog_service.delete_item(item.item_id, company_id)
                else:
                    dimensions_service.delete_detail_account(self._editing_account_id, company_id)
            else:
                dimensions_service.delete_detail_account(self._editing_account_id, company_id)
        except ValueError as exc:
            self.account_status_label.setText(str(exc))
            return
        except Exception:
            # طبقِ رفعِ باگِ واقعیِ کشف‌شده («حذف نمی‌شود و هیچ پیامی هم
            # نشان داده نمی‌شود»): اگر سرویس به هر دلیلِ پیش‌بینی‌نشده‌ای
            # (مثلاً نقضِ کلیدِ خارجیِ یک زیرجدولِ فراموش‌شده) یک استثنایِ
            # غیرِ ValueError پرتاب کند، این استثنا در یک اسلاتِ Qt هیچ‌گاه
            # نباید بی‌صدا بلعیده شود -- حداقل یک پیامِ عمومی به کاربر
            # نشان داده می‌شود تا بداند حذف انجام نشده.
            self.account_status_label.setText(
                "حذف با خطا مواجه شد؛ احتمالاً این حساب در جایِ دیگری استفاده شده است."
            )
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
        try:
            self.edit_detail_account(detail_account_id)
        except Exception:
            # طبقِ رفعِ باگِ گزارش‌شده («کرش می‌کند»): این متد از مسیرِ
            # ناوبریِ فهرستِ واحدِ تفصیلی‌ها (جستجو -> کلیکِ ردیف) صدا زده
            # می‌شود -- همان گاردِ _on_account_item_clicked این‌جا هم لازم
            # است تا یک استثنایِ پیش‌بینی‌نشده کلِ برنامه را کرش نکند.
            traceback.print_exc()
            self.account_status_label.setText(
                "بارگذاریِ این حساب با خطا مواجه شد؛ لطفاً دوباره تلاش کنید."
            )

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
