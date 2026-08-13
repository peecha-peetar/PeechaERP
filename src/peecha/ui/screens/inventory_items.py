"""کاتالوگِ کالا/خدمت — کالا موجودیتِ تازه‌ای نیست، تفصیلیِ سطحِ‌آخرِ گروهِ
INVENTORY_ITEM است؛ این فرم فقط رویِ inv.items (جدولِ اقماری) + تفصیلیِ
همان کالا کار می‌کند.

طبقِ طراحیِ ماژولار: فرم در تب‌ها سازمان‌دهی شده و هر تب بر اساسِ نوعِ کالا
(item_kind_code) و قابلیت‌هایِ فعالِ شرکت (Feature Toggle) نمایان/مخفی
می‌شود. کمبوهایی که از جدولِ دیگری می‌خوانند یک دکمهٔ «+» کنارشان دارند."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_engine as engine_service
from peecha.services import inventory_extended as extended_service
from peecha.services import inventory_locations as locations_service
from peecha.ui.widgets import FieldHelpMixin

_COLUMNS = ["فعال", "وضعیت", "واحد", "نام", "کد"]
_KIND_LABELS = {
    "GOOD": "کالا", "SERVICE": "خدمت", "RAW_MATERIAL": "مادهٔ اولیه", "SEMI_FINISHED": "نیمه‌ساخته",
    "FINISHED_GOOD": "ساخته‌شده", "ASSET": "دارایی", "BUNDLE": "بسته", "KIT": "کیت",
}
_LIFECYCLE_LABELS = {"DRAFT": "پیش‌نویس", "ACTIVE": "فعال", "DISCONTINUED": "متوقف‌شده"}
_COSTING_LABELS = {"": "(پیش‌فرضِ شرکت)", "FIFO": "FIFO", "WEIGHTED_AVERAGE": "میانگینِ موزون", "STANDARD": "بهایِ استاندارد"}
_UOM_TYPE_LABELS = {"COUNT": "شمارشی", "WEIGHT": "وزن", "VOLUME": "حجم", "LENGTH": "طول", "AREA": "مساحت", "TIME": "زمان"}
_RELATION_LABELS = {"SUBSTITUTE": "جایگزین", "COMPLEMENTARY": "مکمل"}
_DEPRECIATION_LABELS = {"STRAIGHT_LINE": "خطِ‌مستقیم", "DECLINING_BALANCE": "نزولی"}
_CONSUMER_FACING_KINDS = ("GOOD", "FINISHED_GOOD", "BUNDLE", "KIT")


def _decimal_or_none(text: str) -> decimal.Decimal | None:
    text = text.strip()
    if not text:
        return None
    try:
        return decimal.Decimal(text)
    except decimal.InvalidOperation:
        return None


def _int_or_none(text: str) -> int | None:
    text = text.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _wrap_scrollable(content: QWidget) -> QWidget:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidget(content)
    wrapper = QWidget()
    wrapper.setObjectName("card")
    wrapper_layout = QVBoxLayout(wrapper)
    wrapper_layout.setContentsMargins(0, 0, 0, 0)
    wrapper_layout.setSpacing(0)
    wrapper_layout.addWidget(scroll)
    return wrapper


class InventoryItemsScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[catalog_service.ItemRow] = []
        self._categories: list[catalog_service.ItemCategoryRow] = []
        self._editing_id: int | None = None
        self._enabled_features: set[str] = set()
        self._current_bom_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)

        self.set_field_help([
            (self.code_field, "کدِ یکتایِ این کالا/خدمت در سطحِ شرکت."),
            (self.name_field, "نامِ نمایشیِ کالا/خدمت."),
            (self.kind_combo, "نوعِ کالا؛ تب‌هایِ مرتبط بر اساسِ همین انتخاب نمایان می‌شوند."),
            (self.uom_combo, "واحدِ پایه — پس از اولین حرکتِ انبار دیگر قابلِ‌تغییر نیست."),
            (self.costing_combo, "روشِ قیمت‌گذاریِ اختصاصیِ این کالا؛ خالی یعنی از تنظیماتِ شرکت پیروی می‌کند."),
            (self.is_stock_tracked_checkbox, "خدمت نمی‌تواند موجودی‌محور باشد."),
            (self.track_expiry_checkbox, "ردیابیِ انقضا نیازمندِ فعال‌بودنِ ردیابیِ بچ است."),
        ])

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("کاتالوگِ کالا و خدمت")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        new_button = QPushButton("+ کالایِ جدید")
        new_button.setObjectName("primaryButton")
        new_button.clicked.connect(self._reset_form)
        layout.addWidget(new_button, alignment=Qt.AlignLeft)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)
        return _wrap_scrollable(panel)

    # --- ساختارِ کلیِ فرم: تب‌بندی‌شده ---------------------------------------
    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)

        self.form_title = QLabel("کالایِ جدید")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        self.tabs = QTabWidget()
        self.tab_indexes: dict[str, int] = {}
        tab_defs = [
            ("basic", self._build_basic_info_tab(), "اطلاعاتِ پایه"),
            ("tracking", self._build_sales_tracking_tab(), "فروش/خرید و ردیابی"),
            ("grouping", self._build_grouping_tab(), "گروه‌بندی و شناسه"),
            ("purchasing", self._build_purchasing_tab(), "خرید"),
            ("sales_extra", self._build_sales_extra_tab(), "فروشِ تکمیلی"),
            ("production", self._build_production_tab(), "تولید (BOM)"),
            ("ecommerce", self._build_ecommerce_tab(), "فروشگاهِ اینترنتی"),
            ("pos", self._build_pos_tab(), "POS"),
            ("shipping", self._build_shipping_tab(), "حمل‌ونقل"),
            ("qc", self._build_qc_tab(), "کنترلِ کیفیت"),
            ("asset", self._build_asset_tab(), "دارایی"),
        ]
        for key, widget, label in tab_defs:
            self.tab_indexes[key] = self.tabs.addTab(widget, label)
        layout.addWidget(self.tabs, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        save_button = QPushButton("ذخیره")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._save)
        buttons.addWidget(save_button)

        cancel_button = QPushButton("انصراف")
        cancel_button.setObjectName("flatButton")
        cancel_button.clicked.connect(self._reset_form)
        buttons.addWidget(cancel_button)

        self.delete_button = QPushButton("حذف")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self._delete)
        self.delete_button.setVisible(False)
        buttons.addWidget(self.delete_button)

        layout.addLayout(buttons)
        return _wrap_scrollable(panel)

    # --- تبِ اطلاعاتِ پایه ---------------------------------------------------
    def _build_basic_info_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        layout.addWidget(QLabel("کد"))
        self.code_field = QLineEdit()
        layout.addWidget(self.code_field)

        layout.addWidget(QLabel("نام"))
        self.name_field = QLineEdit()
        layout.addWidget(self.name_field)

        layout.addWidget(QLabel("نامِ لاتین"))
        self.latin_name_field = QLineEdit()
        layout.addWidget(self.latin_name_field)

        layout.addWidget(QLabel("نامِ کوتاه"))
        self.short_name_field = QLineEdit()
        layout.addWidget(self.short_name_field)

        layout.addWidget(QLabel("نوع"))
        self.kind_combo = QComboBox()
        for code, label in _KIND_LABELS.items():
            self.kind_combo.addItem(label, code)
        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        layout.addWidget(self.kind_combo)

        self.uom_combo = QComboBox()
        layout.addWidget(self._make_combo_with_add_row("واحدِ پایه", self.uom_combo, self._quick_add_uom))

        self.brand_combo = QComboBox()
        layout.addWidget(self._make_combo_with_add_row("برند", self.brand_combo, self._quick_add_brand))

        self.manufacturer_combo = QComboBox()
        layout.addWidget(self._make_combo_with_add_row("تولیدکننده", self.manufacturer_combo, self._quick_add_manufacturer))

        layout.addWidget(QLabel("کشورِ سازنده"))
        self.country_of_origin_field = QLineEdit()
        layout.addWidget(self.country_of_origin_field)

        layout.addWidget(QLabel("روشِ قیمت‌گذاری"))
        self.costing_combo = QComboBox()
        for code, label in _COSTING_LABELS.items():
            self.costing_combo.addItem(label, code or None)
        layout.addWidget(self.costing_combo)

        self.lifecycle_row = QWidget()
        lifecycle_layout = QVBoxLayout(self.lifecycle_row)
        lifecycle_layout.setContentsMargins(0, 0, 0, 0)
        lifecycle_layout.addWidget(QLabel("وضعیتِ چرخهٔ‌عمر"))
        self.lifecycle_combo = QComboBox()
        for code, label in _LIFECYCLE_LABELS.items():
            self.lifecycle_combo.addItem(label, code)
        lifecycle_layout.addWidget(self.lifecycle_combo)
        layout.addWidget(self.lifecycle_row)

        layout.addWidget(QLabel("یادداشت"))
        self.notes_field = QTextEdit()
        self.notes_field.setMaximumHeight(60)
        layout.addWidget(self.notes_field)

        self.is_active_checkbox = QCheckBox("فعال")
        self.is_active_checkbox.setChecked(True)
        layout.addWidget(self.is_active_checkbox)
        layout.addStretch(1)
        return tab

    # --- تبِ فروش/خرید و ردیابی ------------------------------------------
    def _build_sales_tracking_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        self.is_sellable_checkbox = QCheckBox("قابلِ‌فروش")
        self.is_sellable_checkbox.setChecked(True)
        layout.addWidget(self.is_sellable_checkbox)

        self.is_purchasable_checkbox = QCheckBox("قابلِ‌خرید")
        self.is_purchasable_checkbox.setChecked(True)
        layout.addWidget(self.is_purchasable_checkbox)

        self.is_stock_tracked_checkbox = QCheckBox("موجودی‌محور")
        self.is_stock_tracked_checkbox.setChecked(True)
        layout.addWidget(self.is_stock_tracked_checkbox)

        self.track_batch_checkbox = QCheckBox("ردیابیِ بچ")
        self.track_batch_row = self.track_batch_checkbox
        layout.addWidget(self.track_batch_checkbox)

        self.track_expiry_checkbox = QCheckBox("ردیابیِ انقضا")
        self.track_expiry_row = self.track_expiry_checkbox
        layout.addWidget(self.track_expiry_checkbox)

        self.track_serial_checkbox = QCheckBox("ردیابیِ سریال")
        self.track_serial_row = self.track_serial_checkbox
        layout.addWidget(self.track_serial_checkbox)

        layout.addStretch(1)
        return tab

    # --- تبِ گروه‌بندی و شناسه -----------------------------------------------
    def _build_grouping_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        self.category_combo = QComboBox()
        layout.addWidget(self._make_combo_with_add_row("دسته‌بندی", self.category_combo, self._quick_add_category))

        self.default_warehouse_combo = QComboBox()
        layout.addWidget(QLabel("انبارِ پیش‌فرض"))
        layout.addWidget(self.default_warehouse_combo)

        layout.addWidget(QLabel("بارکد"))
        self.barcode_field = QLineEdit()
        layout.addWidget(self.barcode_field)

        layout.addWidget(QLabel("محتوایِ QR"))
        self.qr_code_field = QLineEdit()
        layout.addWidget(self.qr_code_field)

        layout.addWidget(QLabel("SKU"))
        self.sku_field = QLineEdit()
        layout.addWidget(self.sku_field)

        layout.addWidget(QLabel("کالاهایِ مرتبط (جایگزین/مکمل)"))
        self.related_item_combo = QComboBox()
        self.relation_type_combo = QComboBox()
        for code, label in _RELATION_LABELS.items():
            self.relation_type_combo.addItem(label, code)
        related_row = QHBoxLayout()
        related_row.addWidget(self.related_item_combo, stretch=2)
        related_row.addWidget(self.relation_type_combo, stretch=1)
        add_related_button = QPushButton("+")
        add_related_button.setFixedWidth(28)
        add_related_button.clicked.connect(self._add_related_item)
        related_row.addWidget(add_related_button)
        layout.addLayout(related_row)
        self.related_table = QTableWidget(0, 2)
        self.related_table.setHorizontalHeaderLabels(["نوع", "کالا"])
        self.related_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.related_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.related_table.verticalHeader().setVisible(False)
        self.related_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.related_table.setMaximumHeight(120)
        layout.addWidget(self.related_table)
        remove_related_button = QPushButton("حذفِ ردیفِ انتخاب‌شده")
        remove_related_button.setObjectName("dangerButton")
        remove_related_button.clicked.connect(self._remove_related_item)
        layout.addWidget(remove_related_button)

        layout.addStretch(1)
        return tab

    # --- تبِ خرید -------------------------------------------------------------
    def _build_purchasing_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        layout.addWidget(QLabel("زمانِ تامین (روز)"))
        self.purchase_lead_time_field = QLineEdit()
        layout.addWidget(self.purchase_lead_time_field)

        layout.addWidget(QLabel("حداقلِ سفارش"))
        self.purchase_min_order_field = QLineEdit()
        layout.addWidget(self.purchase_min_order_field)

        layout.addWidget(QLabel("تعدادِ بسته‌بندیِ خرید"))
        self.purchase_package_qty_field = QLineEdit()
        layout.addWidget(self.purchase_package_qty_field)

        layout.addWidget(QLabel("تامین‌کنندگان"))
        self.supplier_combo = QComboBox()
        supplier_row = QHBoxLayout()
        supplier_row.addWidget(self.supplier_combo, stretch=1)
        add_supplier_button = QPushButton("+")
        add_supplier_button.setFixedWidth(28)
        add_supplier_button.clicked.connect(self._add_supplier)
        supplier_row.addWidget(add_supplier_button)
        layout.addLayout(supplier_row)
        self.supplier_table = QTableWidget(0, 3)
        self.supplier_table.setHorizontalHeaderLabels(["ترجیحی", "زمانِ تامین", "تامین‌کننده"])
        self.supplier_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.supplier_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.supplier_table.verticalHeader().setVisible(False)
        self.supplier_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.supplier_table.setMaximumHeight(140)
        layout.addWidget(self.supplier_table)
        remove_supplier_button = QPushButton("حذفِ ردیفِ انتخاب‌شده")
        remove_supplier_button.setObjectName("dangerButton")
        remove_supplier_button.clicked.connect(self._remove_supplier)
        layout.addWidget(remove_supplier_button)

        layout.addStretch(1)
        return tab

    # --- تبِ فروشِ تکمیلی -------------------------------------------------------
    def _build_sales_extra_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        layout.addWidget(QLabel("حداکثرِ درصدِ تخفیف"))
        self.max_discount_field = QLineEdit()
        layout.addWidget(self.max_discount_field)

        layout.addWidget(QLabel("درصدِ کمیسیونِ فروش"))
        self.sales_commission_field = QLineEdit()
        layout.addWidget(self.sales_commission_field)

        layout.addWidget(QLabel("مدتِ گارانتی (ماه)"))
        self.warranty_months_field = QLineEdit()
        layout.addWidget(self.warranty_months_field)

        layout.addStretch(1)
        return tab

    # --- تبِ تولید (BOM) — فقط برایِ FINISHED_GOOD --------------------------
    def _build_production_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        self.bom_status_label = QLabel("ابتدا کالا را ذخیره کنید.")
        layout.addWidget(self.bom_status_label)

        create_bom_button = QPushButton("+ نسخهٔ تازهٔ فهرستِ موادِ اولیه")
        create_bom_button.setObjectName("primaryButton")
        create_bom_button.clicked.connect(self._create_bom)
        layout.addWidget(create_bom_button, alignment=Qt.AlignLeft)

        self.bom_component_combo = QComboBox()
        self.bom_qty_field = QLineEdit()
        self.bom_qty_field.setPlaceholderText("مقدارِ مصرفی")
        bom_row = QHBoxLayout()
        bom_row.addWidget(self.bom_component_combo, stretch=2)
        bom_row.addWidget(self.bom_qty_field, stretch=1)
        add_bom_line_button = QPushButton("+")
        add_bom_line_button.setFixedWidth(28)
        add_bom_line_button.clicked.connect(self._add_bom_line)
        bom_row.addWidget(add_bom_line_button)
        layout.addLayout(bom_row)

        self.bom_lines_table = QTableWidget(0, 2)
        self.bom_lines_table.setHorizontalHeaderLabels(["مقدارِ مصرفی", "کالایِ مصرفی"])
        self.bom_lines_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.bom_lines_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.bom_lines_table.verticalHeader().setVisible(False)
        self.bom_lines_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.bom_lines_table)
        remove_bom_line_button = QPushButton("حذفِ ردیفِ انتخاب‌شده")
        remove_bom_line_button.setObjectName("dangerButton")
        remove_bom_line_button.clicked.connect(self._remove_bom_line)
        layout.addWidget(remove_bom_line_button)

        return tab

    # --- تبِ فروشگاهِ اینترنتی --------------------------------------------------
    def _build_ecommerce_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        layout.addWidget(QLabel("عنوانِ سئو"))
        self.seo_title_field = QLineEdit()
        layout.addWidget(self.seo_title_field)

        layout.addWidget(QLabel("نامکِ آدرس (Slug)"))
        self.seo_slug_field = QLineEdit()
        layout.addWidget(self.seo_slug_field)

        layout.addWidget(QLabel("توضیحاتِ متا"))
        self.seo_description_field = QLineEdit()
        layout.addWidget(self.seo_description_field)

        layout.addWidget(QLabel("کلیدواژه‌هایِ متا"))
        self.seo_keywords_field = QLineEdit()
        layout.addWidget(self.seo_keywords_field)

        layout.addWidget(QLabel("دستهٔ فروشگاهی"))
        self.website_category_field = QLineEdit()
        layout.addWidget(self.website_category_field)

        layout.addWidget(QLabel("برچسب‌ها"))
        self.website_tags_field = QLineEdit()
        layout.addWidget(self.website_tags_field)

        layout.addStretch(1)
        return tab

    # --- تبِ POS ---------------------------------------------------------------
    def _build_pos_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        layout.addWidget(QLabel("کلیدِ میان‌بر"))
        self.pos_shortcut_field = QLineEdit()
        layout.addWidget(self.pos_shortcut_field)

        layout.addWidget(QLabel("رنگِ دکمه"))
        self.pos_color_field = QLineEdit()
        self.pos_color_field.setPlaceholderText("#RRGGBB")
        layout.addWidget(self.pos_color_field)

        self.pos_requires_weight_checkbox = QCheckBox("نیازمندِ توزین")
        layout.addWidget(self.pos_requires_weight_checkbox)

        self.pos_requires_serial_checkbox = QCheckBox("نیازمندِ سریال")
        layout.addWidget(self.pos_requires_serial_checkbox)

        layout.addStretch(1)
        return tab

    # --- تبِ حمل‌ونقل ------------------------------------------------------------
    def _build_shipping_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        layout.addWidget(QLabel("طول (سانتی‌متر)"))
        self.length_field = QLineEdit()
        layout.addWidget(self.length_field)

        layout.addWidget(QLabel("عرض (سانتی‌متر)"))
        self.width_field = QLineEdit()
        layout.addWidget(self.width_field)

        layout.addWidget(QLabel("ارتفاع (سانتی‌متر)"))
        self.height_field = QLineEdit()
        layout.addWidget(self.height_field)

        layout.addWidget(QLabel("نوعِ بسته‌بندی"))
        self.package_type_field = QLineEdit()
        layout.addWidget(self.package_type_field)

        layout.addWidget(QLabel("کلاسِ حمل"))
        self.freight_class_field = QLineEdit()
        layout.addWidget(self.freight_class_field)

        layout.addStretch(1)
        return tab

    # --- تبِ کنترلِ کیفیت -----------------------------------------------------
    def _build_qc_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        self.requires_qc_checkbox = QCheckBox("نیازمندِ کنترلِ کیفیت")
        layout.addWidget(self.requires_qc_checkbox)

        layout.addWidget(QLabel("استانداردِ کیفیت"))
        self.qc_standard_field = QLineEdit()
        layout.addWidget(self.qc_standard_field)

        layout.addWidget(QLabel("مشخصاتِ آزمون"))
        self.qc_test_spec_field = QTextEdit()
        self.qc_test_spec_field.setMaximumHeight(60)
        layout.addWidget(self.qc_test_spec_field)

        layout.addWidget(QLabel("فاصلهٔ بازرسی (روز)"))
        self.qc_interval_field = QLineEdit()
        layout.addWidget(self.qc_interval_field)

        layout.addStretch(1)
        return tab

    # --- تبِ دارایی — فقط برایِ ASSET ------------------------------------------
    def _build_asset_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        layout.addWidget(QLabel("شمارهٔ اموال"))
        self.asset_tag_field = QLineEdit()
        layout.addWidget(self.asset_tag_field)

        layout.addWidget(QLabel("گروهِ استهلاک"))
        self.depreciation_group_field = QLineEdit()
        layout.addWidget(self.depreciation_group_field)

        layout.addWidget(QLabel("عمرِ مفید (ماه)"))
        self.useful_life_field = QLineEdit()
        layout.addWidget(self.useful_life_field)

        layout.addWidget(QLabel("روشِ استهلاک"))
        self.depreciation_method_combo = QComboBox()
        for code, label in _DEPRECIATION_LABELS.items():
            self.depreciation_method_combo.addItem(label, code)
        layout.addWidget(self.depreciation_method_combo)

        layout.addWidget(QLabel("تاریخِ تحصیل"))
        self.acquisition_date_field = QDateEdit()
        self.acquisition_date_field.setCalendarPopup(True)
        self.acquisition_date_field.setDate(datetime.date.today())
        layout.addWidget(self.acquisition_date_field)

        layout.addWidget(QLabel("بهایِ تحصیل"))
        self.acquisition_cost_field = QLineEdit()
        layout.addWidget(self.acquisition_cost_field)

        layout.addWidget(QLabel("ارزشِ اسقاط"))
        self.salvage_value_field = QLineEdit()
        layout.addWidget(self.salvage_value_field)

        save_asset_button = QPushButton("ذخیرهٔ اطلاعاتِ دارایی")
        save_asset_button.setObjectName("primaryButton")
        save_asset_button.clicked.connect(self._save_asset_detail)
        layout.addWidget(save_asset_button, alignment=Qt.AlignLeft)

        layout.addStretch(1)
        return tab

    # --- الگویِ کمبو + دکمهٔ «+» --------------------------------------------
    def _make_combo_with_add_row(self, label_text: str, combo: QComboBox, quick_add) -> QWidget:
        row = QWidget()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(2)
        row_layout.addWidget(QLabel(label_text))
        combo_row = QHBoxLayout()
        combo_row.addWidget(combo, stretch=1)
        add_button = QPushButton("+")
        add_button.setFixedWidth(28)
        add_button.setToolTip(f"{label_text}ِ تازه")
        add_button.clicked.connect(quick_add)
        combo_row.addWidget(add_button)
        row_layout.addLayout(combo_row)
        return row

    def _quick_add_uom(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("واحدِ تازه")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("کد"))
        code_field = QLineEdit()
        layout.addWidget(code_field)
        layout.addWidget(QLabel("نام"))
        name_field = QLineEdit()
        layout.addWidget(name_field)
        layout.addWidget(QLabel("نوع"))
        type_combo = QComboBox()
        for code, label in _UOM_TYPE_LABELS.items():
            type_combo.addItem(label, code)
        layout.addWidget(type_combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted or not code_field.text().strip() or not name_field.text().strip():
            return
        try:
            new_id = catalog_service.create_uom(company_id, code_field.text().strip(), name_field.text().strip(), type_combo.currentData())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._reload_uoms(company_id)
        self.uom_combo.setCurrentIndex(max(0, self.uom_combo.findData(new_id)))

    def _quick_add_brand(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        new_id = self._quick_add_code_name_dialog("برندِ تازه", lambda code, name: catalog_service.create_brand(company_id, code, name))
        if new_id is None:
            return
        self._reload_brands(company_id)
        self.brand_combo.setCurrentIndex(max(0, self.brand_combo.findData(new_id)))

    def _quick_add_manufacturer(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        new_id = self._quick_add_code_name_dialog(
            "تولیدکنندهٔ تازه", lambda code, name: catalog_service.create_manufacturer(company_id, code, name)
        )
        if new_id is None:
            return
        self._reload_manufacturers(company_id)
        self.manufacturer_combo.setCurrentIndex(max(0, self.manufacturer_combo.findData(new_id)))

    def _quick_add_category(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        new_id = self._quick_add_code_name_dialog(
            "دسته‌بندیِ تازه", lambda code, name: catalog_service.create_category(company_id, code, name)
        )
        if new_id is None:
            return
        self._reload_categories(company_id)
        self.category_combo.setCurrentIndex(max(0, self.category_combo.findData(new_id)))

    def _quick_add_code_name_dialog(self, title: str, create_fn) -> int | None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("کد"))
        code_field = QLineEdit()
        layout.addWidget(code_field)
        layout.addWidget(QLabel("نام"))
        name_field = QLineEdit()
        layout.addWidget(name_field)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return None
        code = code_field.text().strip()
        name = name_field.text().strip()
        if not code or not name:
            return None
        try:
            return create_fn(code, name)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return None

    def _reload_uoms(self, company_id: int) -> None:
        self.uom_combo.blockSignals(True)
        self.uom_combo.clear()
        for u in catalog_service.list_uoms(company_id, active_only=True):
            self.uom_combo.addItem(f"{u.code} — {u.name}", u.uom_id)
        self.uom_combo.blockSignals(False)

    def _reload_brands(self, company_id: int) -> None:
        self.brand_combo.blockSignals(True)
        self.brand_combo.clear()
        self.brand_combo.addItem("(بدونِ برند)", None)
        for b in catalog_service.list_brands(company_id, active_only=True):
            self.brand_combo.addItem(f"{b.code} — {b.name}", b.brand_id)
        self.brand_combo.blockSignals(False)

    def _reload_manufacturers(self, company_id: int) -> None:
        self.manufacturer_combo.blockSignals(True)
        self.manufacturer_combo.clear()
        self.manufacturer_combo.addItem("(بدونِ تولیدکننده)", None)
        for m in catalog_service.list_manufacturers(company_id, active_only=True):
            self.manufacturer_combo.addItem(f"{m.code} — {m.name}", m.manufacturer_id)
        self.manufacturer_combo.blockSignals(False)

    def _reload_categories(self, company_id: int) -> None:
        self._categories = catalog_service.list_categories(company_id, active_only=True)
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("(بدونِ دسته)", None)
        for c in self._categories:
            self.category_combo.addItem(f"{c.code} — {c.name}", c.category_id)
        self.category_combo.blockSignals(False)

    # --- نمایش/مخفی‌کردنِ بخش‌ها بر اساسِ نوعِ کالا و Feature Toggle ---------
    def _on_kind_changed(self) -> None:
        is_service = self.kind_combo.currentData() == "SERVICE"
        if is_service:
            self.is_stock_tracked_checkbox.setChecked(False)
        self.is_stock_tracked_checkbox.setEnabled(not is_service)
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        is_service = self.kind_combo.currentData() == "SERVICE"
        kind = self.kind_combo.currentData()
        self.track_batch_row.setVisible(not is_service and "BATCH_TRACKING" in self._enabled_features)
        self.track_expiry_row.setVisible(not is_service and "EXPIRY_TRACKING" in self._enabled_features)
        self.track_serial_row.setVisible(not is_service and "SERIAL_TRACKING" in self._enabled_features)

        self.tabs.setTabVisible(self.tab_indexes["purchasing"], kind != "SERVICE")
        self.tabs.setTabVisible(self.tab_indexes["sales_extra"], kind in _CONSUMER_FACING_KINDS)
        self.tabs.setTabVisible(self.tab_indexes["production"], kind == "FINISHED_GOOD")
        self.tabs.setTabVisible(self.tab_indexes["ecommerce"], kind in _CONSUMER_FACING_KINDS)
        self.tabs.setTabVisible(self.tab_indexes["pos"], kind in _CONSUMER_FACING_KINDS)
        self.tabs.setTabVisible(
            self.tab_indexes["shipping"], kind != "SERVICE" and "LOGISTICS_DIMENSIONS" in self._enabled_features
        )
        self.tabs.setTabVisible(
            self.tab_indexes["qc"], kind != "SERVICE" and "QUALITY_CONTROL" in self._enabled_features
        )
        self.tabs.setTabVisible(self.tab_indexes["asset"], kind == "ASSET")

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        self._reset_form()
        company_id = self._company_id()
        if company_id is None:
            return
        self._rows = catalog_service.list_items(company_id)
        self._enabled_features = {f.feature_code for f in engine_service.list_features(company_id) if f.is_enabled}

        self._reload_uoms(company_id)
        self._reload_brands(company_id)
        self._reload_manufacturers(company_id)
        self._reload_categories(company_id)

        self.default_warehouse_combo.blockSignals(True)
        self.default_warehouse_combo.clear()
        self.default_warehouse_combo.addItem("(بدونِ انبارِ پیش‌فرض)", None)
        for w in locations_service.list_warehouses(company_id, active_only=True):
            self.default_warehouse_combo.addItem(f"{w.code} — {w.name}", w.warehouse_id)
        self.default_warehouse_combo.blockSignals(False)

        self.supplier_combo.clear()
        for s in dimensions_service.list_suppliers(company_id):
            self.supplier_combo.addItem(f"{s['code']} — {s['name']}", s["detail_account_id"])

        self.related_item_combo.clear()
        self.bom_component_combo.clear()
        for r in self._rows:
            label = f"{r.code} — {r.name or ''}"
            self.related_item_combo.addItem(label, r.item_id)
            self.bom_component_combo.addItem(label, r.item_id)

        self._apply_visibility()

        self.table.setRowCount(len(self._rows))
        for row_index, it in enumerate(self._rows):
            values = [
                "بله" if it.is_active else "خیر",
                _LIFECYCLE_LABELS.get(it.lifecycle_status_code, it.lifecycle_status_code),
                it.base_uom_code,
                it.name or "",
                it.code,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, it.item_id)
                self.table.setItem(row_index, col_index, item)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        item_id = self.table.item(row, 0).data(Qt.UserRole)
        it = next((r for r in self._rows if r.item_id == item_id), None)
        if it is not None:
            self._load_into_form(it)

    def _load_into_form(self, it: catalog_service.ItemRow) -> None:
        self._editing_id = it.item_id
        self.form_title.setText(f"ویرایشِ کالا — {it.name or it.code}")
        self.status_label.setText("")
        self.code_field.setText(it.code)
        self.code_field.setEnabled(True)
        self.name_field.setText(it.name or "")
        self.latin_name_field.setText(it.latin_name or "")
        self.short_name_field.setText(it.short_name or "")
        self.kind_combo.setCurrentIndex(self.kind_combo.findData(it.item_kind_code))
        self.uom_combo.setCurrentIndex(max(0, self.uom_combo.findData(it.base_uom_id)))
        self.brand_combo.setCurrentIndex(max(0, self.brand_combo.findData(it.brand_id)))
        self.manufacturer_combo.setCurrentIndex(max(0, self.manufacturer_combo.findData(it.manufacturer_id)))
        self.country_of_origin_field.setText(it.country_of_origin or "")
        self.costing_combo.setCurrentIndex(max(0, self.costing_combo.findData(it.costing_method_code)))
        self.lifecycle_row.setVisible(True)
        self.lifecycle_combo.setCurrentIndex(max(0, self.lifecycle_combo.findData(it.lifecycle_status_code)))
        self.is_sellable_checkbox.setChecked(it.is_sellable)
        self.is_purchasable_checkbox.setChecked(it.is_purchasable)
        self.is_stock_tracked_checkbox.setChecked(it.is_stock_tracked)
        self.track_batch_checkbox.setChecked(it.track_batch)
        self.track_expiry_checkbox.setChecked(it.track_expiry)
        self.track_serial_checkbox.setChecked(it.track_serial)
        self.notes_field.setPlainText(it.notes or "")
        self.is_active_checkbox.setChecked(it.is_active)

        self.category_combo.setCurrentIndex(max(0, self.category_combo.findData(it.category_id)))
        self.default_warehouse_combo.setCurrentIndex(max(0, self.default_warehouse_combo.findData(it.default_warehouse_id)))
        self.barcode_field.setText(it.barcode or "")
        self.qr_code_field.setText(it.qr_code_data or "")
        self.sku_field.setText(it.sku or "")

        self.purchase_lead_time_field.setText(str(it.purchase_lead_time_days) if it.purchase_lead_time_days is not None else "")
        self.purchase_min_order_field.setText(str(it.purchase_min_order_qty) if it.purchase_min_order_qty is not None else "")
        self.purchase_package_qty_field.setText(str(it.purchase_package_qty) if it.purchase_package_qty is not None else "")

        self.max_discount_field.setText(str(it.max_discount_percent) if it.max_discount_percent is not None else "")
        self.sales_commission_field.setText(str(it.sales_commission_percent) if it.sales_commission_percent is not None else "")
        self.warranty_months_field.setText(str(it.warranty_months) if it.warranty_months is not None else "")

        self.seo_title_field.setText(it.seo_title or "")
        self.seo_slug_field.setText(it.seo_url_slug or "")
        self.seo_description_field.setText(it.seo_meta_description or "")
        self.seo_keywords_field.setText(it.seo_meta_keywords or "")
        self.website_category_field.setText(it.website_category or "")
        self.website_tags_field.setText(it.website_tags or "")

        self.pos_shortcut_field.setText(it.pos_shortcut_key or "")
        self.pos_color_field.setText(it.pos_button_color or "")
        self.pos_requires_weight_checkbox.setChecked(it.pos_requires_weight)
        self.pos_requires_serial_checkbox.setChecked(it.pos_requires_serial)

        self.length_field.setText(str(it.length_cm) if it.length_cm is not None else "")
        self.width_field.setText(str(it.width_cm) if it.width_cm is not None else "")
        self.height_field.setText(str(it.height_cm) if it.height_cm is not None else "")
        self.package_type_field.setText(it.package_type_code or "")
        self.freight_class_field.setText(it.freight_class_code or "")

        self.requires_qc_checkbox.setChecked(it.requires_qc)
        self.qc_standard_field.setText(it.qc_standard or "")
        self.qc_test_spec_field.setPlainText(it.qc_test_spec or "")
        self.qc_interval_field.setText(str(it.qc_inspection_interval_days) if it.qc_inspection_interval_days is not None else "")

        asset_detail = extended_service.get_asset_detail(it.item_id)
        if asset_detail is not None:
            self.asset_tag_field.setText(asset_detail.asset_tag_no or "")
            self.depreciation_group_field.setText(asset_detail.depreciation_group_code or "")
            self.useful_life_field.setText(str(asset_detail.useful_life_months))
            self.depreciation_method_combo.setCurrentIndex(
                max(0, self.depreciation_method_combo.findData(asset_detail.depreciation_method_code))
            )
            self.acquisition_date_field.setDate(asset_detail.acquisition_date)
            self.acquisition_cost_field.setText(str(asset_detail.acquisition_cost))
            self.salvage_value_field.setText(str(asset_detail.salvage_value))
        else:
            self.asset_tag_field.clear()
            self.depreciation_group_field.clear()
            self.useful_life_field.clear()
            self.acquisition_date_field.setDate(datetime.date.today())
            self.acquisition_cost_field.clear()
            self.salvage_value_field.clear()

        self.delete_button.setVisible(True)
        self._apply_visibility()
        self._refresh_suppliers_table()
        self._refresh_related_table()
        self._refresh_bom_lines()

    def _reset_form(self) -> None:
        self._editing_id = None
        self._current_bom_id = None
        self.form_title.setText("کالایِ جدید")
        self.status_label.setText("")
        self.code_field.clear()
        self.code_field.setEnabled(True)
        self.name_field.clear()
        self.latin_name_field.clear()
        self.short_name_field.clear()
        self.kind_combo.setCurrentIndex(0)
        if self.uom_combo.count():
            self.uom_combo.setCurrentIndex(0)
        self.brand_combo.setCurrentIndex(0)
        self.manufacturer_combo.setCurrentIndex(0)
        self.country_of_origin_field.clear()
        self.costing_combo.setCurrentIndex(0)
        self.lifecycle_row.setVisible(False)
        self.is_sellable_checkbox.setChecked(True)
        self.is_purchasable_checkbox.setChecked(True)
        self.is_stock_tracked_checkbox.setChecked(True)
        self.track_batch_checkbox.setChecked(False)
        self.track_expiry_checkbox.setChecked(False)
        self.track_serial_checkbox.setChecked(False)
        self.notes_field.clear()
        self.is_active_checkbox.setChecked(True)

        self.category_combo.setCurrentIndex(0)
        self.default_warehouse_combo.setCurrentIndex(0)
        self.barcode_field.clear()
        self.qr_code_field.clear()
        self.sku_field.clear()

        self.purchase_lead_time_field.clear()
        self.purchase_min_order_field.clear()
        self.purchase_package_qty_field.clear()

        self.max_discount_field.clear()
        self.sales_commission_field.clear()
        self.warranty_months_field.clear()

        self.seo_title_field.clear()
        self.seo_slug_field.clear()
        self.seo_description_field.clear()
        self.seo_keywords_field.clear()
        self.website_category_field.clear()
        self.website_tags_field.clear()

        self.pos_shortcut_field.clear()
        self.pos_color_field.clear()
        self.pos_requires_weight_checkbox.setChecked(False)
        self.pos_requires_serial_checkbox.setChecked(False)

        self.length_field.clear()
        self.width_field.clear()
        self.height_field.clear()
        self.package_type_field.clear()
        self.freight_class_field.clear()

        self.requires_qc_checkbox.setChecked(False)
        self.qc_standard_field.clear()
        self.qc_test_spec_field.clear()
        self.qc_interval_field.clear()

        self.asset_tag_field.clear()
        self.depreciation_group_field.clear()
        self.useful_life_field.clear()
        self.acquisition_date_field.setDate(datetime.date.today())
        self.acquisition_cost_field.clear()
        self.salvage_value_field.clear()

        self.delete_button.setVisible(False)
        self.table.clearSelection()
        self.supplier_table.setRowCount(0)
        self.related_table.setRowCount(0)
        self.bom_lines_table.setRowCount(0)
        self.bom_status_label.setText("ابتدا کالا را ذخیره کنید.")
        self._apply_visibility()

    def _collect_fields(self) -> catalog_service.ItemFields | None:
        if self.uom_combo.currentData() is None:
            self.status_label.setText("ابتدا یک واحدِ اندازه‌گیری تعریف کنید.")
            return None
        return catalog_service.ItemFields(
            item_kind_code=self.kind_combo.currentData(),
            base_uom_id=self.uom_combo.currentData(),
            brand_id=self.brand_combo.currentData(),
            manufacturer_id=self.manufacturer_combo.currentData(),
            costing_method_code=self.costing_combo.currentData(),
            is_sellable=self.is_sellable_checkbox.isChecked(),
            is_purchasable=self.is_purchasable_checkbox.isChecked(),
            is_stock_tracked=self.is_stock_tracked_checkbox.isChecked(),
            track_serial=self.track_serial_checkbox.isChecked(),
            track_batch=self.track_batch_checkbox.isChecked(),
            track_expiry=self.track_expiry_checkbox.isChecked(),
            notes=self.notes_field.toPlainText().strip() or None,
            latin_name=self.latin_name_field.text().strip() or None,
            short_name=self.short_name_field.text().strip() or None,
            country_of_origin=self.country_of_origin_field.text().strip() or None,
            category_id=self.category_combo.currentData(),
            default_warehouse_id=self.default_warehouse_combo.currentData(),
            barcode=self.barcode_field.text().strip() or None,
            qr_code_data=self.qr_code_field.text().strip() or None,
            sku=self.sku_field.text().strip() or None,
            purchase_lead_time_days=_int_or_none(self.purchase_lead_time_field.text()),
            purchase_min_order_qty=_decimal_or_none(self.purchase_min_order_field.text()),
            purchase_package_qty=_decimal_or_none(self.purchase_package_qty_field.text()),
            max_discount_percent=_decimal_or_none(self.max_discount_field.text()),
            sales_commission_percent=_decimal_or_none(self.sales_commission_field.text()),
            warranty_months=_int_or_none(self.warranty_months_field.text()),
            seo_title=self.seo_title_field.text().strip() or None,
            seo_url_slug=self.seo_slug_field.text().strip() or None,
            seo_meta_description=self.seo_description_field.text().strip() or None,
            seo_meta_keywords=self.seo_keywords_field.text().strip() or None,
            website_category=self.website_category_field.text().strip() or None,
            website_tags=self.website_tags_field.text().strip() or None,
            pos_shortcut_key=self.pos_shortcut_field.text().strip() or None,
            pos_button_color=self.pos_color_field.text().strip() or None,
            pos_requires_weight=self.pos_requires_weight_checkbox.isChecked(),
            pos_requires_serial=self.pos_requires_serial_checkbox.isChecked(),
            length_cm=_decimal_or_none(self.length_field.text()),
            width_cm=_decimal_or_none(self.width_field.text()),
            height_cm=_decimal_or_none(self.height_field.text()),
            package_type_code=self.package_type_field.text().strip() or None,
            freight_class_code=self.freight_class_field.text().strip() or None,
            requires_qc=self.requires_qc_checkbox.isChecked(),
            qc_standard=self.qc_standard_field.text().strip() or None,
            qc_test_spec=self.qc_test_spec_field.toPlainText().strip() or None,
            qc_inspection_interval_days=_int_or_none(self.qc_interval_field.text()),
        )

    def _save(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        name = self.name_field.text().strip()
        code = self.code_field.text().strip()
        if not code:
            self.status_label.setText("کد را وارد کنید.")
            return
        if not name:
            self.status_label.setText("نام را وارد کنید.")
            return
        fields = self._collect_fields()
        if fields is None:
            return

        try:
            if self._editing_id is not None:
                lifecycle_code = self.lifecycle_combo.currentData()
                catalog_service.update_item(
                    self._editing_id, company_id, code, name, self.is_active_checkbox.isChecked(), lifecycle_code, fields
                )
                saved_id = self._editing_id
            else:
                saved_id = catalog_service.create_item(company_id, code, name, fields)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return

        self.refresh()
        saved = next((r for r in self._rows if r.item_id == saved_id), None)
        if saved is not None:
            self._load_into_form(saved)

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        confirm = QMessageBox.question(self, "حذفِ کالا", "این کالا حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        company_id = self._company_id()
        try:
            catalog_service.delete_item(self._editing_id, company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()

    # --- تامین‌کنندگان -----------------------------------------------------
    def _refresh_suppliers_table(self) -> None:
        self.supplier_table.setRowCount(0)
        if self._editing_id is None:
            return
        rows = extended_service.list_item_suppliers(self._editing_id)
        self.supplier_table.setRowCount(len(rows))
        for row_index, r in enumerate(rows):
            label = self.supplier_combo.itemText(self.supplier_combo.findData(r.supplier_detail_account_id))
            values = ["بله" if r.is_preferred else "خیر", str(r.lead_time_days or ""), label or str(r.supplier_detail_account_id)]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, r.item_supplier_id)
                self.supplier_table.setItem(row_index, col_index, item)

    def _add_supplier(self) -> None:
        if self._editing_id is None:
            self.status_label.setText("ابتدا کالا را ذخیره کنید.")
            return
        supplier_id = self.supplier_combo.currentData()
        if supplier_id is None:
            return
        try:
            extended_service.add_item_supplier(self._editing_id, supplier_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh_suppliers_table()

    def _remove_supplier(self) -> None:
        if self._editing_id is None:
            return
        selected = self.supplier_table.selectedItems()
        if not selected:
            return
        try:
            extended_service.remove_item_supplier(selected[0].data(Qt.UserRole), self._editing_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh_suppliers_table()

    # --- کالاهایِ مرتبط ------------------------------------------------------
    def _refresh_related_table(self) -> None:
        self.related_table.setRowCount(0)
        if self._editing_id is None:
            return
        rows = catalog_service.list_related_items(self._editing_id)
        self.related_table.setRowCount(len(rows))
        for row_index, (related_item_id, relation_type_code) in enumerate(rows):
            other = next((r for r in self._rows if r.item_id == related_item_id), None)
            label = f"{other.code} — {other.name or ''}" if other is not None else str(related_item_id)
            values = [_RELATION_LABELS.get(relation_type_code, relation_type_code), label]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, related_item_id)
                self.related_table.setItem(row_index, col_index, item)

    def _add_related_item(self) -> None:
        if self._editing_id is None:
            self.status_label.setText("ابتدا کالا را ذخیره کنید.")
            return
        related_item_id = self.related_item_combo.currentData()
        relation_type_code = self.relation_type_combo.currentData()
        if related_item_id is None:
            return
        try:
            catalog_service.add_related_item(self._editing_id, related_item_id, relation_type_code)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh_related_table()

    def _remove_related_item(self) -> None:
        selected = self.related_table.selectedItems()
        if not selected:
            return
        catalog_service.remove_related_item(selected[0].data(Qt.UserRole))
        self._refresh_related_table()

    # --- BOM -----------------------------------------------------------------
    def _refresh_bom_lines(self) -> None:
        self.bom_lines_table.setRowCount(0)
        self._current_bom_id = None
        if self._editing_id is None:
            self.bom_status_label.setText("ابتدا کالا را ذخیره کنید.")
            return
        boms = extended_service.list_boms(self._editing_id)
        if not boms:
            self.bom_status_label.setText("هنوز فهرستِ موادِ اولیه‌ای ثبت نشده است.")
            return
        latest = boms[-1]
        self._current_bom_id = latest.bom_id
        self.bom_status_label.setText(f"نسخهٔ {latest.version_no} — اندازهٔ دسته: {latest.batch_size_qty}")
        lines = extended_service.list_bom_lines(latest.bom_id)
        self.bom_lines_table.setRowCount(len(lines))
        for row_index, line in enumerate(lines):
            other = next((r for r in self._rows if r.item_id == line.component_item_id), None)
            label = f"{other.code} — {other.name or ''}" if other is not None else str(line.component_item_id)
            values = [str(line.quantity_per), label]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, line.bom_line_id)
                self.bom_lines_table.setItem(row_index, col_index, item)

    def _create_bom(self) -> None:
        if self._editing_id is None:
            self.status_label.setText("ابتدا کالا را ذخیره کنید.")
            return
        try:
            extended_service.create_bom(self._editing_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh_bom_lines()

    def _add_bom_line(self) -> None:
        if self._current_bom_id is None:
            self.status_label.setText("ابتدا یک نسخهٔ فهرستِ موادِ اولیه بسازید.")
            return
        component_id = self.bom_component_combo.currentData()
        qty = _decimal_or_none(self.bom_qty_field.text())
        if component_id is None or qty is None:
            return
        try:
            extended_service.add_bom_line(self._current_bom_id, component_id, qty)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.bom_qty_field.clear()
        self._refresh_bom_lines()

    def _remove_bom_line(self) -> None:
        if self._current_bom_id is None:
            return
        selected = self.bom_lines_table.selectedItems()
        if not selected:
            return
        try:
            extended_service.remove_bom_line(selected[0].data(Qt.UserRole), self._current_bom_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh_bom_lines()

    # --- دارایی ----------------------------------------------------------------
    def _save_asset_detail(self) -> None:
        if self._editing_id is None:
            self.status_label.setText("ابتدا کالا را ذخیره کنید.")
            return
        useful_life = _int_or_none(self.useful_life_field.text())
        cost = _decimal_or_none(self.acquisition_cost_field.text())
        if useful_life is None or cost is None:
            self.status_label.setText("عمرِ مفید و بهایِ تحصیل را وارد کنید.")
            return
        try:
            extended_service.set_asset_detail(
                self._editing_id,
                useful_life_months=useful_life,
                acquisition_date=self.acquisition_date_field.date().toPython(),
                acquisition_cost=cost,
                depreciation_method_code=self.depreciation_method_combo.currentData(),
                asset_tag_no=self.asset_tag_field.text().strip() or None,
                depreciation_group_code=self.depreciation_group_field.text().strip() or None,
                salvage_value=_decimal_or_none(self.salvage_value_field.text()) or decimal.Decimal(0),
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setObjectName("statusSuccess")
        self.status_label.setText("اطلاعاتِ دارایی ذخیره شد.")
