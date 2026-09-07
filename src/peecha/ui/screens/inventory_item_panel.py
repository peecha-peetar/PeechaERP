"""پنلِ اختصاصیِ «کالا» — طبقِ ادغامِ فرمِ مستقلِ کالا/خدمت در گروهِ تفصیلیِ
INVENTORY_ITEM (هم‌الگو با یکپارچه‌سازیِ HR/PERSONNEL): این ویجت فقط
تب‌هایِ اختصاصیِ کالا را می‌سازد (کد/نام/فعال/والد و دکمه‌هایِ ذخیره/حذف
در فرمِ میزبان — detail_dimensions.py — هستند) و توسطِ آن فرم، فقط در
سطحِ‌آخرِ گروهِ کالا embed و نمایان می‌شود."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.services import commercial_pos as pos_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_engine as engine_service
from peecha.services import inventory_extended as extended_service
from peecha.services import inventory_locations as locations_service
from peecha.services import item_variants as variants_service
from peecha.services import supplier_price_import as spi_service
from peecha.ui.barcode_print import print_barcode_labels
from peecha.ui.widgets import FieldGrid, FieldHelpMixin, FieldSpec, LayoutEditMixin

_SUPPLIER_CODE_TYPE_LABELS = {"CODE": "کد", "NAME": "نام"}

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


class ItemDetailPanel(FieldHelpMixin, LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._company_id: int | None = None
        self._item_id: int | None = None
        self._rows: list[catalog_service.ItemRow] = []
        self._categories: list[catalog_service.ItemCategoryRow] = []
        self._enabled_features: set[str] = set()
        self._current_bom_id: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.tabs = QTabWidget()
        self.tab_indexes: dict[str, int] = {}
        tab_defs = [
            ("basic", self._build_basic_info_tab(), "اطلاعاتِ پایه"),
            ("tracking", self._build_sales_tracking_tab(), "فروش/خرید و ردیابی"),
            ("grouping", self._build_grouping_tab(), "گروه‌بندی و شناسه"),
            ("purchasing", self._build_purchasing_tab(), "خرید"),
            ("variants", self._build_variants_tab(), "ویژگی‌ها و متغیرها"),
            ("sales_extra", self._build_sales_extra_tab(), "فروشِ تکمیلی"),
            ("production", self._build_production_tab(), "تولید (BOM)"),
            ("ecommerce", self._build_ecommerce_tab(), "فروشگاهِ اینترنتی"),
            ("pos", self._build_pos_tab(), "فروشِ حضوری (POS)"),
            ("shipping", self._build_shipping_tab(), "حمل‌ونقل"),
            ("qc", self._build_qc_tab(), "کنترلِ کیفیت"),
            ("asset", self._build_asset_tab(), "دارایی"),
        ]
        for key, widget, label in tab_defs:
            self.tab_indexes[key] = self.tabs.addTab(widget, label)
        layout.addWidget(self.tabs)

        self.set_field_help([
            (self.kind_combo, "نوعِ کالا؛ تب‌هایِ مرتبط بر اساسِ همین انتخاب نمایان می‌شوند."),
            (self.uom_combo, "واحدِ پایه — پس از اولین حرکتِ انبار دیگر قابلِ‌تغییر نیست."),
            (self.costing_combo, "روشِ قیمت‌گذاریِ اختصاصیِ این کالا؛ خالی یعنی از تنظیماتِ شرکت پیروی می‌کند."),
            (self.is_stock_tracked_checkbox, "خدمت نمی‌تواند موجودی‌محور باشد."),
            (self.track_expiry_checkbox, "ردیابیِ انقضا نیازمندِ فعال‌بودنِ ردیابیِ بچ است."),
        ])
        self.register_field_grids("inventory_item_panel", [
            self.basic_info_grid, self.sales_tracking_grid, self.grouping_grid, self.purchasing_grid,
            self.sales_extra_grid, self.ecommerce_grid, self.pos_grid, self.shipping_grid,
            self.qc_grid, self.asset_grid,
        ])
        self.reset()

    # --- تبِ اطلاعاتِ پایه (بدونِ کد/نام/فعال — این‌ها در فرمِ میزبان‌اند) ------
    def _build_basic_info_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        self.latin_name_field = QLineEdit()
        self.short_name_field = QLineEdit()

        self.kind_combo = QComboBox()
        for code, label in _KIND_LABELS.items():
            self.kind_combo.addItem(label, code)
        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)

        self.uom_combo = QComboBox()
        uom_row = self._make_combo_with_add_row("واحدِ پایه", self.uom_combo, self._quick_add_uom)

        self.brand_combo = QComboBox()
        brand_row = self._make_combo_with_add_row("برند", self.brand_combo, self._quick_add_brand)

        self.manufacturer_combo = QComboBox()
        manufacturer_row = self._make_combo_with_add_row("تولیدکننده", self.manufacturer_combo, self._quick_add_manufacturer)

        self.country_of_origin_field = QLineEdit()

        self.costing_combo = QComboBox()
        for code, label in _COSTING_LABELS.items():
            self.costing_combo.addItem(label, code or None)

        self.lifecycle_combo = QComboBox()
        for code, label in _LIFECYCLE_LABELS.items():
            self.lifecycle_combo.addItem(label, code)

        self.notes_field = QTextEdit()
        self.notes_field.setMaximumHeight(60)

        self.basic_info_grid = FieldGrid([
            FieldSpec("latin_name", "نامِ لاتین", self.latin_name_field, span=1),
            FieldSpec("short_name", "نامِ کوتاه", self.short_name_field, span=1),
            FieldSpec("kind", "نوع", self.kind_combo, span=1),
            FieldSpec("uom", "", uom_row, span=1),
            FieldSpec("brand", "", brand_row, span=1),
            FieldSpec("manufacturer", "", manufacturer_row, span=1),
            FieldSpec("country_of_origin", "کشورِ سازنده", self.country_of_origin_field, span=1),
            FieldSpec("costing", "روشِ قیمت‌گذاری", self.costing_combo, span=1),
            FieldSpec("lifecycle", "وضعیتِ چرخهٔ‌عمر", self.lifecycle_combo, span=1),
            FieldSpec("notes", "یادداشت", self.notes_field, span=3),
        ])
        layout.addWidget(self.basic_info_grid)

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
        self.is_sellable_checkbox.toggled.connect(self._apply_visibility)

        self.is_purchasable_checkbox = QCheckBox("قابلِ‌خرید")
        self.is_purchasable_checkbox.setChecked(True)

        self.is_stock_tracked_checkbox = QCheckBox("موجودی‌محور")
        self.is_stock_tracked_checkbox.setChecked(True)

        self.track_batch_checkbox = QCheckBox("ردیابیِ بچ")
        self.track_expiry_checkbox = QCheckBox("ردیابیِ انقضا")
        self.track_serial_checkbox = QCheckBox("ردیابیِ سریال")

        self.sales_tracking_grid = FieldGrid([
            FieldSpec("is_sellable", "", self.is_sellable_checkbox, span=1),
            FieldSpec("is_purchasable", "", self.is_purchasable_checkbox, span=1),
            FieldSpec("is_stock_tracked", "", self.is_stock_tracked_checkbox, span=1),
            FieldSpec("track_batch", "", self.track_batch_checkbox, span=1),
            FieldSpec("track_expiry", "", self.track_expiry_checkbox, span=1),
            FieldSpec("track_serial", "", self.track_serial_checkbox, span=1),
        ])
        layout.addWidget(self.sales_tracking_grid)

        layout.addStretch(1)
        return tab

    # --- تبِ گروه‌بندی و شناسه -----------------------------------------------
    def _build_grouping_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        self.category_combo = QComboBox()
        category_row = self._make_combo_with_add_row("دسته‌بندی", self.category_combo, self._quick_add_category)

        self.default_warehouse_combo = QComboBox()
        self.barcode_field = QLineEdit()
        self.qr_code_field = QLineEdit()
        self.sku_field = QLineEdit()

        self.grouping_grid = FieldGrid([
            FieldSpec("category", "", category_row, span=1),
            FieldSpec("default_warehouse", "انبارِ پیش‌فرض", self.default_warehouse_combo, span=1),
            FieldSpec("barcode", "بارکد", self.barcode_field, span=1),
            FieldSpec("qr_code", "محتوایِ QR", self.qr_code_field, span=1),
            FieldSpec("sku", "SKU", self.sku_field, span=1),
        ])
        layout.addWidget(self.grouping_grid)

        layout.addWidget(QLabel("کالاهایِ مرتبط (جایگزین/مکمل)"))
        self.related_item_combo = QComboBox()
        self.relation_type_combo = QComboBox()
        for code, label in _RELATION_LABELS.items():
            self.relation_type_combo.addItem(label, code)
        related_row = QHBoxLayout()
        related_row.addWidget(self.related_item_combo, stretch=2)
        related_row.addWidget(self.relation_type_combo, stretch=1)
        add_related_button = QPushButton("+")
        add_related_button.setObjectName("iconButton")
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
        remove_related_button = QPushButton("🗑️")
        remove_related_button.setObjectName("dangerIconButton")
        remove_related_button.setFixedWidth(44)
        remove_related_button.setToolTip("حذفِ ردیفِ انتخاب‌شده")
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

        self.purchase_lead_time_field = QLineEdit()
        self.purchase_min_order_field = QLineEdit()
        self.purchase_package_qty_field = QLineEdit()

        self.purchasing_grid = FieldGrid([
            FieldSpec("lead_time", "زمانِ تامین (روز)", self.purchase_lead_time_field, span=1),
            FieldSpec("min_order", "حداقلِ سفارش", self.purchase_min_order_field, span=1),
            FieldSpec("package_qty", "تعدادِ بسته‌بندیِ خرید", self.purchase_package_qty_field, span=1),
        ])
        layout.addWidget(self.purchasing_grid)

        layout.addWidget(QLabel("تامین‌کنندگان"))
        self.supplier_combo = QComboBox()
        supplier_row = QHBoxLayout()
        supplier_row.addWidget(self.supplier_combo, stretch=1)
        add_supplier_button = QPushButton("+")
        add_supplier_button.setObjectName("iconButton")
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
        self.supplier_table.setMinimumHeight(160)
        self.supplier_table.setMaximumHeight(220)
        layout.addWidget(self.supplier_table)
        remove_supplier_button = QPushButton("🗑️")
        remove_supplier_button.setObjectName("dangerIconButton")
        remove_supplier_button.setFixedWidth(44)
        remove_supplier_button.setToolTip("حذفِ ردیفِ انتخاب‌شده")
        remove_supplier_button.clicked.connect(self._remove_supplier)
        layout.addWidget(remove_supplier_button)

        # طبقِ درخواستِ صریح («چندین کد کالایِ تامین‌کننده و حتی نامِ کالا
        # ... تشخیص باید ترکیبی باشد»): این بخش مستقل از جدولِ بالاست --
        # آن یکی «کدامین تامین‌کننده‌ها این کالا را می‌فروشند» را نگه
        # می‌دارد، این یکی «آن تامین‌کننده این کالا را با چه کد/نامی در
        # فایلِ قیمتِ خودش صدا می‌زند» را -- برایِ شناساییِ خودکار در
        # وارداتِ قیمتِ تامین‌کننده.
        layout.addWidget(QLabel("کد/نامِ کالا نزدِ تامین‌کننده (برایِ شناساییِ خودکار در وارداتِ قیمت)"))
        code_form = QHBoxLayout()
        self.item_code_type_combo = QComboBox()
        self.item_code_type_combo.addItem(_SUPPLIER_CODE_TYPE_LABELS["CODE"], "CODE")
        self.item_code_type_combo.addItem(_SUPPLIER_CODE_TYPE_LABELS["NAME"], "NAME")
        code_form.addWidget(self.item_code_type_combo)
        self.item_code_supplier_combo = QComboBox()
        code_form.addWidget(self.item_code_supplier_combo, stretch=1)
        self.item_code_value_field = QLineEdit()
        self.item_code_value_field.setPlaceholderText("کد یا نامِ کالا نزدِ این تامین‌کننده")
        code_form.addWidget(self.item_code_value_field, stretch=1)
        add_code_button = QPushButton("➕")
        add_code_button.setObjectName("iconButton")
        add_code_button.setFixedWidth(44)
        add_code_button.setToolTip("افزودن")
        add_code_button.clicked.connect(self._add_item_supplier_code)
        code_form.addWidget(add_code_button)
        layout.addLayout(code_form)

        self.item_codes_table = QTableWidget(0, 3)
        self.item_codes_table.setHorizontalHeaderLabels(["نوع", "تامین‌کننده", "مقدار"])
        self.item_codes_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.item_codes_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.item_codes_table.verticalHeader().setVisible(False)
        self.item_codes_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.item_codes_table.setMinimumHeight(180)
        self.item_codes_table.setMaximumHeight(260)
        self.item_codes_table.setToolTip("برایِ ویرایش، رویِ ردیف دوبار کلیک کنید.")
        self.item_codes_table.cellDoubleClicked.connect(self._edit_item_supplier_code)
        layout.addWidget(self.item_codes_table)
        remove_code_button = QPushButton("🗑️")
        remove_code_button.setObjectName("dangerIconButton")
        remove_code_button.setFixedWidth(44)
        remove_code_button.setToolTip("حذفِ ردیفِ انتخاب‌شده")
        remove_code_button.clicked.connect(self._remove_item_supplier_code)
        layout.addWidget(remove_code_button)

        layout.addStretch(1)
        return tab

    # --- تبِ ویژگی‌ها و متغیرها --------------------------------------------------
    def _build_variants_tab(self) -> QWidget:
        """طبقِ درخواستِ صریح: ویژگی (سایز/وزن/مدل/...) قابلِ‌تعریف، مقادیرِ
        هر ویژگی، تولیدِ ترکیبی‌ِ متغیرها برایِ این کالا، بارکدِ مجزا برایِ
        خودِ کالا و بارکدِ ترکیبی برایِ هر متغیر + پرینت."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)
        self._variant_selection: dict[int, set[int]] = {}

        layout.addWidget(QLabel("بارکدِ کالایِ اصلی"))
        own_barcode_row = QHBoxLayout()
        self.own_barcode_label = QLabel("(بدونِ بارکد)")
        own_barcode_row.addWidget(self.own_barcode_label, stretch=1)
        make_own_barcode_button = QPushButton("🏷️")
        make_own_barcode_button.setObjectName("iconButton")
        make_own_barcode_button.setToolTip("ساختنِ بارکدِ کالایِ اصلی")
        make_own_barcode_button.clicked.connect(self._make_own_barcode)
        own_barcode_row.addWidget(make_own_barcode_button)
        print_own_barcode_button = QPushButton("🖨️")
        print_own_barcode_button.setObjectName("iconButton")
        print_own_barcode_button.setToolTip("پرینتِ بارکدِ کالایِ اصلی")
        print_own_barcode_button.clicked.connect(self._print_own_barcode)
        own_barcode_row.addWidget(print_own_barcode_button)
        layout.addLayout(own_barcode_row)

        layout.addWidget(
            QLabel("ویژگی‌ها و مقادیرِ قابلِ‌انتخاب برایِ تولیدِ متغیر -- ترتیبِ زیر همان اولویتِ نام‌گذاریِ خودکارِ متغیر است")
        )
        attribute_row = QHBoxLayout()
        self.variant_attribute_combo = QComboBox()
        self.variant_attribute_combo.currentIndexChanged.connect(self._load_attribute_values_list)
        attribute_row.addWidget(self.variant_attribute_combo, stretch=1)
        # طبقِ درخواستِ صریح («چند ویژگی داریم، الویت و ترتیبشون چجوری
        # مشخص میشه؟»): این دو دکمه دقیقاً همان سوال را جواب می‌دهند --
        # اولویتِ ویژگیِ انتخاب‌شده را با همسایه‌اش در فهرست جابه‌جا
        # می‌کنند (که هم ترتیبِ همین کمبو، هم ترتیبِ بخش‌هایِ نامِ
        # خودکارِ متغیر را عوض می‌کند).
        move_up_button = QPushButton("⬆️")
        move_up_button.setObjectName("iconButton")
        move_up_button.setFixedWidth(32)
        move_up_button.setToolTip("افزایشِ اولویتِ این ویژگی (بالاتر/زودتر)")
        move_up_button.clicked.connect(lambda: self._move_item_attribute("UP"))
        attribute_row.addWidget(move_up_button)
        move_down_button = QPushButton("⬇️")
        move_down_button.setObjectName("iconButton")
        move_down_button.setFixedWidth(32)
        move_down_button.setToolTip("کاهشِ اولویتِ این ویژگی (پایین‌تر/دیرتر)")
        move_down_button.clicked.connect(lambda: self._move_item_attribute("DOWN"))
        attribute_row.addWidget(move_down_button)
        add_attribute_button = QPushButton("+")
        add_attribute_button.setObjectName("iconButton")
        add_attribute_button.setFixedWidth(28)
        add_attribute_button.setToolTip("ویژگیِ تازه")
        add_attribute_button.clicked.connect(self._add_item_attribute)
        attribute_row.addWidget(add_attribute_button)
        layout.addLayout(attribute_row)

        value_row = QHBoxLayout()
        self.variant_value_field = QLineEdit()
        self.variant_value_field.setPlaceholderText("مقدارِ تازه (مثلاً M یا قرمز)")
        value_row.addWidget(self.variant_value_field, stretch=1)
        add_value_button = QPushButton("+")
        add_value_button.setObjectName("iconButton")
        add_value_button.setFixedWidth(28)
        add_value_button.setToolTip("افزودنِ مقدار به همین ویژگی")
        add_value_button.clicked.connect(self._add_item_attribute_value)
        value_row.addWidget(add_value_button)
        layout.addLayout(value_row)

        self.variant_values_list = QTableWidget(0, 2)
        self.variant_values_list.setHorizontalHeaderLabels(["انتخاب", "مقدار"])
        self.variant_values_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.variant_values_list.verticalHeader().setVisible(False)
        self.variant_values_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.variant_values_list.setMaximumHeight(140)
        self.variant_values_list.itemChanged.connect(self._on_variant_value_checked)
        layout.addWidget(self.variant_values_list)

        generate_button = QPushButton("⚙️")
        generate_button.setObjectName("iconButton")
        generate_button.setToolTip("تولیدِ متغیرها از ترکیبِ انتخاب‌شده")
        generate_button.clicked.connect(self._generate_variants)
        layout.addWidget(generate_button)

        layout.addWidget(QLabel("متغیرهایِ ساخته‌شده برایِ این کالا"))
        self.variants_table = QTableWidget(0, 4)
        self.variants_table.setHorizontalHeaderLabels(["کد", "نام", "ویژگی‌ها", "بارکد"])
        self.variants_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.variants_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.variants_table.verticalHeader().setVisible(False)
        self.variants_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.variants_table.setMinimumHeight(140)
        self.variants_table.itemSelectionChanged.connect(self._on_variant_selection_changed)
        layout.addWidget(self.variants_table, stretch=1)

        # طبقِ درخواستِ صریح («برایِ هر متغیر بتوان توضیحات و قیمتِ مجزا و
        # عکس هم معرفی کرد»): هرکدام یک ردیفِ فشرده -- عمل رویِ متغیرِ
        # انتخاب‌شده در جدولِ بالا.
        layout.addWidget(QLabel("ویرایشِ متغیرِ انتخاب‌شده"))
        notes_row = QHBoxLayout()
        self.variant_notes_field = QLineEdit()
        self.variant_notes_field.setPlaceholderText("توضیحاتِ این متغیر")
        notes_row.addWidget(self.variant_notes_field, stretch=1)
        save_notes_button = QPushButton("💾")
        save_notes_button.setObjectName("iconButton")
        save_notes_button.setToolTip("ذخیرهٔ توضیحاتِ این متغیر")
        save_notes_button.clicked.connect(self._save_variant_notes)
        notes_row.addWidget(save_notes_button)
        layout.addLayout(notes_row)

        price_row = QHBoxLayout()
        self.variant_price_list_combo = QComboBox()
        self.variant_price_list_combo.currentIndexChanged.connect(self._load_variant_price)
        price_row.addWidget(self.variant_price_list_combo, stretch=1)
        self.variant_price_field = QLineEdit()
        self.variant_price_field.setPlaceholderText("قیمتِ فروش")
        price_row.addWidget(self.variant_price_field, stretch=1)
        save_price_button = QPushButton("💾")
        save_price_button.setObjectName("iconButton")
        save_price_button.setToolTip("ذخیرهٔ قیمتِ این متغیر در همین لیستِ قیمت")
        save_price_button.clicked.connect(self._save_variant_price)
        price_row.addWidget(save_price_button)
        add_photo_button = QPushButton("🖼️")
        add_photo_button.setObjectName("iconButton")
        add_photo_button.setToolTip("افزودنِ عکسِ این متغیر")
        add_photo_button.clicked.connect(self._add_variant_photo)
        price_row.addWidget(add_photo_button)
        layout.addLayout(price_row)

        variants_action_row = QHBoxLayout()
        print_selected_button = QPushButton("🖨️")
        print_selected_button.setObjectName("iconButton")
        print_selected_button.setToolTip("پرینتِ بارکدِ انتخاب‌شده")
        print_selected_button.clicked.connect(self._print_selected_variant_barcode)
        variants_action_row.addWidget(print_selected_button)
        print_all_button = QPushButton("📇")
        print_all_button.setObjectName("iconButton")
        print_all_button.setToolTip("پرینتِ بارکدِ همه‌یِ متغیرها")
        print_all_button.clicked.connect(self._print_all_variant_barcodes)
        variants_action_row.addWidget(print_all_button)
        remove_variant_button = QPushButton("🗑️")
        remove_variant_button.setObjectName("dangerIconButton")
        remove_variant_button.setToolTip("حذفِ متغیرِ انتخاب‌شده")
        remove_variant_button.clicked.connect(self._remove_selected_variant)
        variants_action_row.addWidget(remove_variant_button)
        layout.addLayout(variants_action_row)

        self.variants_status_label = QLabel("")
        self.variants_status_label.setObjectName("statusError")
        self.variants_status_label.setWordWrap(True)
        layout.addWidget(self.variants_status_label)

        return tab

    def _reload_item_attributes(self) -> None:
        if self._company_id is None:
            return
        current = self.variant_attribute_combo.currentData()
        self.variant_attribute_combo.blockSignals(True)
        self.variant_attribute_combo.clear()
        for attribute in variants_service.list_item_attributes(self._company_id, active_only=True):
            self.variant_attribute_combo.addItem(attribute.name, attribute.attribute_id)
        self.variant_attribute_combo.blockSignals(False)
        if current is not None:
            self.variant_attribute_combo.setCurrentIndex(max(0, self.variant_attribute_combo.findData(current)))
        self._load_attribute_values_list()

    def _move_item_attribute(self, direction: str) -> None:
        attribute_id = self.variant_attribute_combo.currentData()
        if attribute_id is None or self._company_id is None:
            return
        try:
            variants_service.swap_item_attribute_order(self._company_id, attribute_id, direction)
        except ValueError as exc:
            self.variants_status_label.setText(str(exc))
            return
        self._reload_item_attributes()
        self.variant_attribute_combo.setCurrentIndex(max(0, self.variant_attribute_combo.findData(attribute_id)))

    def _add_item_attribute(self) -> None:
        if self._company_id is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("ویژگیِ تازه")
        form = QVBoxLayout(dialog)
        code_field = QLineEdit()
        code_field.setPlaceholderText("کد (مثلاً SIZE)")
        form.addWidget(code_field)
        name_field = QLineEdit()
        name_field.setPlaceholderText("نام (مثلاً سایز)")
        form.addWidget(name_field)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            attribute_id = variants_service.create_item_attribute(
                self._company_id, code_field.text(), name_field.text()
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._reload_item_attributes()
        self.variant_attribute_combo.setCurrentIndex(max(0, self.variant_attribute_combo.findData(attribute_id)))

    def _load_attribute_values_list(self) -> None:
        attribute_id = self.variant_attribute_combo.currentData()
        self.variant_values_list.blockSignals(True)
        self.variant_values_list.setRowCount(0)
        if attribute_id is not None:
            selected_values = self._variant_selection.get(attribute_id, set())
            values = variants_service.list_item_attribute_values(attribute_id)
            self.variant_values_list.setRowCount(len(values))
            for row_index, value_row in enumerate(values):
                checkbox_item = QTableWidgetItem()
                checkbox_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                checkbox_item.setCheckState(Qt.Checked if value_row.value_id in selected_values else Qt.Unchecked)
                checkbox_item.setData(Qt.UserRole, value_row.value_id)
                self.variant_values_list.setItem(row_index, 0, checkbox_item)
                self.variant_values_list.setItem(row_index, 1, QTableWidgetItem(value_row.value))
        self.variant_values_list.blockSignals(False)

    def _on_variant_value_checked(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        attribute_id = self.variant_attribute_combo.currentData()
        value_id = item.data(Qt.UserRole)
        if attribute_id is None or value_id is None:
            return
        selected = self._variant_selection.setdefault(attribute_id, set())
        if item.checkState() == Qt.Checked:
            selected.add(value_id)
        else:
            selected.discard(value_id)

    def _add_item_attribute_value(self) -> None:
        attribute_id = self.variant_attribute_combo.currentData()
        if attribute_id is None:
            self.variants_status_label.setText("ابتدا یک ویژگی انتخاب یا اضافه کنید.")
            return
        value_text = self.variant_value_field.text().strip()
        if not value_text:
            return
        try:
            variants_service.add_item_attribute_value(attribute_id, value_text, value_text)
        except ValueError as exc:
            self.variants_status_label.setText(str(exc))
            return
        self.variants_status_label.setText("")
        self.variant_value_field.clear()
        self._load_attribute_values_list()

    def _make_own_barcode(self) -> None:
        if self._item_id is None or self._company_id is None:
            self.variants_status_label.setText("ابتدا کالا را ذخیره کنید.")
            return
        try:
            barcode = variants_service.ensure_item_barcode(self._company_id, self._item_id)
        except ValueError as exc:
            self.variants_status_label.setText(str(exc))
            return
        self.own_barcode_label.setText(barcode)
        self.barcode_field.setText(barcode)
        self.variants_status_label.setText("")

    def _print_own_barcode(self) -> None:
        barcode = self.own_barcode_label.text().strip()
        if not barcode or not barcode.isdigit():
            self.variants_status_label.setText("ابتدا بارکدِ کالا را بسازید.")
            return
        title = f"{self.latin_name_field.text().strip() or ''}".strip() or "کالا"
        print_barcode_labels(self, [(title, "", barcode)])

    def _generate_variants(self) -> None:
        if self._item_id is None or self._company_id is None:
            self.variants_status_label.setText("ابتدا کالا را ذخیره کنید.")
            return
        selection = {aid: sorted(vals) for aid, vals in self._variant_selection.items() if vals}
        try:
            created_ids = variants_service.generate_item_variants(self._company_id, self._item_id, selection)
        except ValueError as exc:
            self.variants_status_label.setText(str(exc))
            return
        self.variants_status_label.setText(
            f"{len(created_ids)} متغیرِ تازه ساخته شد." if created_ids else "همه‌یِ ترکیب‌ها از قبل موجود بودند."
        )
        self._refresh_variants_table()
        self._sync_transactability_checkboxes()

    def _refresh_variants_table(self) -> None:
        self.variants_table.setRowCount(0)
        if self._item_id is None or self._company_id is None:
            return
        rows = variants_service.list_item_variants(self._company_id, self._item_id)
        self.variants_table.setRowCount(len(rows))
        for row_index, r in enumerate(rows):
            values = [r.code, r.name or "", r.attribute_labels, r.barcode or ""]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, r.variant_item_id)
                self.variants_table.setItem(row_index, col_index, cell)

    def _print_selected_variant_barcode(self) -> None:
        selected = self.variants_table.selectedItems()
        if not selected:
            self.variants_status_label.setText("یک متغیر از جدول انتخاب کنید.")
            return
        row = selected[0].row()
        name = self.variants_table.item(row, 1).text()
        attrs = self.variants_table.item(row, 2).text()
        barcode = self.variants_table.item(row, 3).text()
        if not barcode:
            self.variants_status_label.setText("این متغیر هنوز بارکد ندارد.")
            return
        print_barcode_labels(self, [(name, attrs, barcode)])

    def _print_all_variant_barcodes(self) -> None:
        if self._item_id is None or self._company_id is None:
            return
        rows = variants_service.list_item_variants(self._company_id, self._item_id)
        labels = [(r.name or r.code, r.attribute_labels, r.barcode) for r in rows if r.barcode]
        if not labels:
            self.variants_status_label.setText("هیچ متغیرِ بارکددار‌ی برایِ چاپ وجود ندارد.")
            return
        print_barcode_labels(self, labels)

    def _remove_selected_variant(self) -> None:
        selected = self.variants_table.selectedItems()
        if not selected or self._company_id is None or self._item_id is None:
            return
        variant_item_id = selected[0].data(Qt.UserRole)
        try:
            variants_service.delete_item_variant(self._company_id, self._item_id, variant_item_id)
        except ValueError as exc:
            self.variants_status_label.setText(str(exc))
            return
        self.variants_status_label.setText("")
        self._refresh_variants_table()
        self._sync_transactability_checkboxes()

    def _sync_transactability_checkboxes(self) -> None:
        """طبقِ تصمیمِ صریح («کالایِ اصلیِ دارایِ متغیر، غیرِقابلِ‌فروش/
        غیرِموجودی‌محور شود»): تولید/حذفِ متغیر می‌تواند این سه پرچمِ کالایِ
        اصلی را در دیتابیس مستقیماً عوض کند -- اگر تیک‌هایِ همین فرم
        رفرش نشوند، دکمهٔ ذخیرهٔ فرمِ میزبان با مقدارِ باسیاتِ چک‌باکس‌ها
        همان تغییرِ خودکار را بازنویسی می‌کند."""
        if self._item_id is None:
            return
        item = catalog_service.get_item(self._item_id)
        if item is None:
            return
        self.is_sellable_checkbox.setChecked(item.is_sellable)
        self.is_purchasable_checkbox.setChecked(item.is_purchasable)
        self.is_stock_tracked_checkbox.setChecked(item.is_stock_tracked)
        self._apply_visibility()

    def _selected_variant_item_id(self) -> int | None:
        selected = self.variants_table.selectedItems()
        if not selected:
            return None
        return self.variants_table.item(selected[0].row(), 0).data(Qt.UserRole)

    def _on_variant_selection_changed(self) -> None:
        variant_item_id = self._selected_variant_item_id()
        if variant_item_id is None:
            self.variant_notes_field.clear()
            self.variant_price_field.clear()
            return
        item = catalog_service.get_item(variant_item_id)
        self.variant_notes_field.setText((item.notes or "") if item is not None else "")
        self._load_variant_price()

    def _save_variant_notes(self) -> None:
        variant_item_id = self._selected_variant_item_id()
        if variant_item_id is None or self._company_id is None:
            self.variants_status_label.setText("یک متغیر از جدول انتخاب کنید.")
            return
        try:
            variants_service.set_variant_notes(
                self._company_id, variant_item_id, self.variant_notes_field.text().strip() or None
            )
        except ValueError as exc:
            self.variants_status_label.setText(str(exc))
            return
        self.variants_status_label.setText("توضیحاتِ متغیر ذخیره شد.")

    def _reload_variant_price_lists(self) -> None:
        if self._company_id is None:
            return
        current = self.variant_price_list_combo.currentData()
        self.variant_price_list_combo.blockSignals(True)
        self.variant_price_list_combo.clear()
        for price_list in pricing_service.list_price_lists(self._company_id, "SALES"):
            self.variant_price_list_combo.addItem(f"{price_list.code} — {price_list.name}", price_list.price_list_id)
        self.variant_price_list_combo.blockSignals(False)
        if current is not None:
            self.variant_price_list_combo.setCurrentIndex(max(0, self.variant_price_list_combo.findData(current)))
        self._load_variant_price()

    def _load_variant_price(self) -> None:
        variant_item_id = self._selected_variant_item_id()
        price_list_id = self.variant_price_list_combo.currentData()
        if variant_item_id is None or price_list_id is None:
            self.variant_price_field.clear()
            return
        existing = next(
            (
                p for p in pricing_service.list_price_list_items(price_list_id)
                if p.item_id == variant_item_id and p.min_quantity == decimal.Decimal(1)
            ),
            None,
        )
        self.variant_price_field.setText(str(existing.unit_price) if existing is not None else "")

    def _save_variant_price(self) -> None:
        variant_item_id = self._selected_variant_item_id()
        price_list_id = self.variant_price_list_combo.currentData()
        if variant_item_id is None or price_list_id is None:
            self.variants_status_label.setText("یک متغیر و یک لیستِ قیمت انتخاب کنید.")
            return
        price = _decimal_or_none(self.variant_price_field.text())
        if price is None:
            self.variants_status_label.setText("قیمتِ معتبر وارد کنید.")
            return
        item = catalog_service.get_item(variant_item_id)
        if item is None:
            return
        pricing_service.set_price_list_item(
            price_list_id, variant_item_id, item.base_uom_id, price,
            changed_by_user_id=app_session.current_user.user_id if app_session.current_user else None,
        )
        self.variants_status_label.setText("قیمتِ متغیر ذخیره شد.")

    def _add_variant_photo(self) -> None:
        variant_item_id = self._selected_variant_item_id()
        if variant_item_id is None or self._company_id is None or self._item_id is None:
            self.variants_status_label.setText("یک متغیر از جدول انتخاب کنید.")
            return
        row = next(
            (
                r for r in variants_service.list_item_variants(self._company_id, self._item_id)
                if r.variant_item_id == variant_item_id
            ),
            None,
        )
        if row is None:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "انتخابِ عکس", "", "تصاویر (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"
        )
        if not path:
            return
        try:
            attachment_id = dimensions_service.attach_detail_account_file(
                self._company_id, row.item_detail_account_id, app_session.current_user.user_id, path
            )
            dimensions_service.set_primary_detail_account_photo(attachment_id, self._company_id)
        except ValueError as exc:
            self.variants_status_label.setText(str(exc))
            return
        self.variants_status_label.setText("عکسِ متغیر ذخیره شد.")

    # --- تبِ فروشِ تکمیلی -------------------------------------------------------
    def _build_sales_extra_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        self.max_discount_field = QLineEdit()
        self.sales_commission_field = QLineEdit()
        self.warranty_months_field = QLineEdit()
        # طبقِ درخواستِ صریح: درصدِ مالیاتِ این کالا (بعدِ تخفیف) — اگر
        # خالی بماند، هنگامِ صدورِ سند از تنظیماتِ کلیِ شرکت خوانده می‌شود.
        self.default_tax_percent_field = QLineEdit()

        self.sales_extra_grid = FieldGrid([
            FieldSpec("max_discount", "حداکثرِ درصدِ تخفیف", self.max_discount_field, span=1),
            FieldSpec("sales_commission", "درصدِ کمیسیونِ فروش", self.sales_commission_field, span=1),
            FieldSpec("warranty_months", "مدتِ گارانتی (ماه)", self.warranty_months_field, span=1),
            FieldSpec("default_tax_percent", "درصدِ مالیات (خالی = تنظیماتِ کلیِ شرکت)", self.default_tax_percent_field, span=1),
        ])
        layout.addWidget(self.sales_extra_grid)

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

        create_bom_button = QPushButton("➕")
        create_bom_button.setObjectName("primaryIconButton")
        create_bom_button.setFixedWidth(48)
        create_bom_button.setToolTip("نسخهٔ تازهٔ فهرستِ موادِ اولیه")
        create_bom_button.clicked.connect(self._create_bom)
        layout.addWidget(create_bom_button, alignment=Qt.AlignLeft)

        self.bom_component_combo = QComboBox()
        self.bom_qty_field = QLineEdit()
        self.bom_qty_field.setPlaceholderText("مقدارِ مصرفی")
        bom_row = QHBoxLayout()
        bom_row.addWidget(self.bom_component_combo, stretch=2)
        bom_row.addWidget(self.bom_qty_field, stretch=1)
        add_bom_line_button = QPushButton("+")
        add_bom_line_button.setObjectName("iconButton")
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
        remove_bom_line_button = QPushButton("🗑️")
        remove_bom_line_button.setObjectName("dangerIconButton")
        remove_bom_line_button.setFixedWidth(44)
        remove_bom_line_button.setToolTip("حذفِ ردیفِ انتخاب‌شده")
        remove_bom_line_button.clicked.connect(self._remove_bom_line)
        layout.addWidget(remove_bom_line_button)

        return tab

    # --- تبِ فروشگاهِ اینترنتی --------------------------------------------------
    def _build_ecommerce_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        self.seo_title_field = QLineEdit()
        self.seo_slug_field = QLineEdit()
        self.seo_description_field = QLineEdit()
        self.seo_keywords_field = QLineEdit()
        self.website_category_field = QLineEdit()
        self.website_tags_field = QLineEdit()

        self.ecommerce_grid = FieldGrid([
            FieldSpec("seo_title", "عنوانِ سئو", self.seo_title_field, span=1),
            FieldSpec("seo_slug", "نامکِ آدرس (Slug)", self.seo_slug_field, span=1),
            FieldSpec("seo_description", "توضیحاتِ متا", self.seo_description_field, span=1),
            FieldSpec("seo_keywords", "کلیدواژه‌هایِ متا", self.seo_keywords_field, span=1),
            FieldSpec("website_category", "دستهٔ فروشگاهی", self.website_category_field, span=1),
            FieldSpec("website_tags", "برچسب‌ها", self.website_tags_field, span=1),
        ])
        layout.addWidget(self.ecommerce_grid)

        layout.addStretch(1)
        return tab

    # --- تبِ POS ---------------------------------------------------------------
    def _build_pos_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        self.pos_shortcut_field = QLineEdit()
        # طبقِ درخواستِ صریح («رنگِ دکمه با پالتِ رنگی انتخاب بشه»): فیلدِ
        # متنیِ هگز فقط برایِ نمایش/ذخیره‌سازی باقی می‌ماند (read-only)؛
        # انتخابِ واقعیِ رنگ از طریقِ QColorDialog انجام می‌شود.
        self.pos_color_field = QLineEdit()
        self.pos_color_field.setPlaceholderText("#RRGGBB")
        self.pos_color_field.setReadOnly(True)
        pos_color_button = QPushButton("🎨")
        pos_color_button.setObjectName("iconButton")
        pos_color_button.setFixedWidth(32)
        pos_color_button.setToolTip("انتخابِ رنگ از پالت")
        pos_color_button.clicked.connect(self._pick_pos_color)
        pos_color_row = QWidget()
        pos_color_row_layout = QHBoxLayout(pos_color_row)
        pos_color_row_layout.setContentsMargins(0, 0, 0, 0)
        pos_color_row_layout.setSpacing(3)
        pos_color_row_layout.addWidget(self.pos_color_field, stretch=1)
        pos_color_row_layout.addWidget(pos_color_button)
        self.pos_requires_weight_checkbox = QCheckBox("نیازمندِ توزین")
        self.pos_requires_serial_checkbox = QCheckBox("نیازمندِ سریال")
        # طبقِ بازخوردِ صریح («دسته‌بندیِ مخصوصِ POS، جدا از دسته‌بندیِ
        # عمومیِ کالا»): این گروه فقط تعیین می‌کند این کالا در کدام تبِ
        # دسترسیِ‌سریعِ صفحه‌یِ فروشِ حضوری نمایش داده شود.
        self.pos_menu_group_combo = QComboBox()
        pos_menu_group_row = self._make_combo_with_add_row(
            "گروهِ POS (تبِ دسترسیِ‌سریع)", self.pos_menu_group_combo, self._quick_add_pos_menu_group,
        )

        self.pos_grid = FieldGrid([
            FieldSpec("shortcut", "کلیدِ میان‌بر", self.pos_shortcut_field, span=1),
            FieldSpec("color", "رنگِ دکمه", pos_color_row, span=1),
            FieldSpec("menu_group", "", pos_menu_group_row, span=1),
            FieldSpec("requires_weight", "", self.pos_requires_weight_checkbox, span=1),
            FieldSpec("requires_serial", "", self.pos_requires_serial_checkbox, span=1),
        ])
        layout.addWidget(self.pos_grid)

        layout.addStretch(1)
        return tab

    # --- تبِ حمل‌ونقل ------------------------------------------------------------
    def _build_shipping_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        self.length_field = QLineEdit()
        self.width_field = QLineEdit()
        self.height_field = QLineEdit()
        self.package_type_field = QLineEdit()
        self.freight_class_field = QLineEdit()

        self.shipping_grid = FieldGrid([
            FieldSpec("length", "طول (سانتی‌متر)", self.length_field, span=1),
            FieldSpec("width", "عرض (سانتی‌متر)", self.width_field, span=1),
            FieldSpec("height", "ارتفاع (سانتی‌متر)", self.height_field, span=1),
            FieldSpec("package_type", "نوعِ بسته‌بندی", self.package_type_field, span=1),
            FieldSpec("freight_class", "کلاسِ حمل", self.freight_class_field, span=1),
        ])
        layout.addWidget(self.shipping_grid)

        layout.addStretch(1)
        return tab

    # --- تبِ کنترلِ کیفیت -----------------------------------------------------
    def _build_qc_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        self.requires_qc_checkbox = QCheckBox("نیازمندِ کنترلِ کیفیت")
        self.qc_standard_field = QLineEdit()
        self.qc_test_spec_field = QTextEdit()
        self.qc_test_spec_field.setMaximumHeight(60)
        self.qc_interval_field = QLineEdit()

        self.qc_grid = FieldGrid([
            FieldSpec("requires_qc", "", self.requires_qc_checkbox, span=1),
            FieldSpec("qc_standard", "استانداردِ کیفیت", self.qc_standard_field, span=1),
            FieldSpec("qc_interval", "فاصلهٔ بازرسی (روز)", self.qc_interval_field, span=1),
            FieldSpec("qc_test_spec", "مشخصاتِ آزمون", self.qc_test_spec_field, span=3),
        ])
        layout.addWidget(self.qc_grid)

        layout.addStretch(1)
        return tab

    # --- تبِ دارایی — فقط برایِ ASSET ------------------------------------------
    def _build_asset_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        self.asset_tag_field = QLineEdit()
        self.depreciation_group_field = QLineEdit()
        self.useful_life_field = QLineEdit()

        self.depreciation_method_combo = QComboBox()
        for code, label in _DEPRECIATION_LABELS.items():
            self.depreciation_method_combo.addItem(label, code)

        self.acquisition_date_field = QDateEdit()
        self.acquisition_date_field.setCalendarPopup(True)
        self.acquisition_date_field.setDate(datetime.date.today())

        self.acquisition_cost_field = QLineEdit()
        self.salvage_value_field = QLineEdit()

        self.asset_grid = FieldGrid([
            FieldSpec("asset_tag", "شمارهٔ اموال", self.asset_tag_field, span=1),
            FieldSpec("depreciation_group", "گروهِ استهلاک", self.depreciation_group_field, span=1),
            FieldSpec("useful_life", "عمرِ مفید (ماه)", self.useful_life_field, span=1),
            FieldSpec("depreciation_method", "روشِ استهلاک", self.depreciation_method_combo, span=1),
            FieldSpec("acquisition_date", "تاریخِ تحصیل", self.acquisition_date_field, span=1),
            FieldSpec("acquisition_cost", "بهایِ تحصیل", self.acquisition_cost_field, span=1),
            FieldSpec("salvage_value", "ارزشِ اسقاط", self.salvage_value_field, span=1),
        ])
        layout.addWidget(self.asset_grid)

        save_asset_button = QPushButton("💾")
        save_asset_button.setObjectName("primaryIconButton")
        save_asset_button.setFixedWidth(48)
        save_asset_button.setToolTip("ذخیرهٔ اطلاعاتِ دارایی")
        save_asset_button.clicked.connect(self._save_asset_detail)
        layout.addWidget(save_asset_button, alignment=Qt.AlignLeft)

        self.asset_status_label = QLabel("")
        layout.addWidget(self.asset_status_label)

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
        add_button.setObjectName("iconButton")
        add_button.setFixedWidth(28)
        add_button.setToolTip(f"{label_text}ِ تازه")
        add_button.clicked.connect(quick_add)
        combo_row.addWidget(add_button)
        row_layout.addLayout(combo_row)
        return row

    def _quick_add_uom(self) -> None:
        if self._company_id is None:
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
            new_id = catalog_service.create_uom(
                self._company_id, code_field.text().strip(), name_field.text().strip(), type_combo.currentData()
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._reload_uoms()
        self.uom_combo.setCurrentIndex(max(0, self.uom_combo.findData(new_id)))

    def _quick_add_brand(self) -> None:
        if self._company_id is None:
            return
        new_id = self._quick_add_code_name_dialog(
            "برندِ تازه", lambda code, name: catalog_service.create_brand(self._company_id, code, name)
        )
        if new_id is None:
            return
        self._reload_brands()
        self.brand_combo.setCurrentIndex(max(0, self.brand_combo.findData(new_id)))

    def _quick_add_manufacturer(self) -> None:
        if self._company_id is None:
            return
        new_id = self._quick_add_code_name_dialog(
            "تولیدکنندهٔ تازه", lambda code, name: catalog_service.create_manufacturer(self._company_id, code, name)
        )
        if new_id is None:
            return
        self._reload_manufacturers()
        self.manufacturer_combo.setCurrentIndex(max(0, self.manufacturer_combo.findData(new_id)))

    def _quick_add_category(self) -> None:
        if self._company_id is None:
            return
        new_id = self._quick_add_code_name_dialog(
            "دسته‌بندیِ تازه", lambda code, name: catalog_service.create_category(self._company_id, code, name)
        )
        if new_id is None:
            return
        self._reload_categories()
        self.category_combo.setCurrentIndex(max(0, self.category_combo.findData(new_id)))

    def _pick_pos_color(self) -> None:
        current = QColor(self.pos_color_field.text().strip()) if self.pos_color_field.text().strip() else QColor("#4A90D9")
        if not current.isValid():
            current = QColor("#4A90D9")
        color = QColorDialog.getColor(current, self, "رنگِ دکمهٔ کالا در POS")
        if not color.isValid():
            return
        self.pos_color_field.setText(color.name())
        self._apply_pos_color_swatch(color.name())

    def _apply_pos_color_swatch(self, color_text: str) -> None:
        color = QColor(color_text) if color_text else None
        if color is not None and color.isValid():
            self.pos_color_field.setStyleSheet(f"background-color: {color.name()}; color: #ffffff;")
        else:
            self.pos_color_field.setStyleSheet("")

    def _quick_add_pos_menu_group(self) -> None:
        # طبقِ درخواستِ صریح («تعریفِ گروه‌ها از طریقِ کالا و تبِ POS هم
        # امکان‌پذیر باشد»): دیگر نیازی نیست کاربر برایِ ساختنِ یک گروهِ
        # تازه از فرمِ کالا خارج شود و به تنظیماتِ تک‌فروشی برود.
        if self._company_id is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("گروهِ POSِ تازه")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("نام"))
        name_field = QLineEdit()
        layout.addWidget(name_field)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted or not name_field.text().strip():
            return
        try:
            new_id = pos_service.create_menu_group(self._company_id, name_field.text().strip())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._reload_menu_groups()
        self.pos_menu_group_combo.setCurrentIndex(max(0, self.pos_menu_group_combo.findData(new_id)))

    def _reload_menu_groups(self) -> None:
        self.pos_menu_group_combo.blockSignals(True)
        self.pos_menu_group_combo.clear()
        self.pos_menu_group_combo.addItem("(بدونِ گروه)", None)
        for g in pos_service.list_menu_groups(self._company_id):
            self.pos_menu_group_combo.addItem(g.name, g.group_id)
        self.pos_menu_group_combo.blockSignals(False)

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

    def _reload_uoms(self) -> None:
        self.uom_combo.blockSignals(True)
        self.uom_combo.clear()
        for u in catalog_service.list_uoms(self._company_id, active_only=True):
            self.uom_combo.addItem(f"{u.code} — {u.name}", u.uom_id)
        self.uom_combo.blockSignals(False)

    def _reload_brands(self) -> None:
        self.brand_combo.blockSignals(True)
        self.brand_combo.clear()
        self.brand_combo.addItem("(بدونِ برند)", None)
        for b in catalog_service.list_brands(self._company_id, active_only=True):
            self.brand_combo.addItem(f"{b.code} — {b.name}", b.brand_id)
        self.brand_combo.blockSignals(False)

    def _reload_manufacturers(self) -> None:
        self.manufacturer_combo.blockSignals(True)
        self.manufacturer_combo.clear()
        self.manufacturer_combo.addItem("(بدونِ تولیدکننده)", None)
        for m in catalog_service.list_manufacturers(self._company_id, active_only=True):
            self.manufacturer_combo.addItem(f"{m.code} — {m.name}", m.manufacturer_id)
        self.manufacturer_combo.blockSignals(False)

    def _reload_categories(self) -> None:
        self._categories = catalog_service.list_categories(self._company_id, active_only=True)
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
        self.sales_tracking_grid.set_field_visible(
            "track_batch", not is_service and "BATCH_TRACKING" in self._enabled_features
        )
        self.sales_tracking_grid.set_field_visible(
            "track_expiry", not is_service and "EXPIRY_TRACKING" in self._enabled_features
        )
        self.sales_tracking_grid.set_field_visible(
            "track_serial", not is_service and "SERIAL_TRACKING" in self._enabled_features
        )

        self.tabs.setTabVisible(self.tab_indexes["purchasing"], kind != "SERVICE")
        self.tabs.setTabVisible(self.tab_indexes["sales_extra"], kind in _CONSUMER_FACING_KINDS)
        self.tabs.setTabVisible(self.tab_indexes["production"], kind == "FINISHED_GOOD")
        self.tabs.setTabVisible(self.tab_indexes["ecommerce"], kind in _CONSUMER_FACING_KINDS)
        self.tabs.setTabVisible(self.tab_indexes["pos"], self.is_sellable_checkbox.isChecked())
        self.tabs.setTabVisible(
            self.tab_indexes["shipping"], kind != "SERVICE" and "LOGISTICS_DIMENSIONS" in self._enabled_features
        )
        self.tabs.setTabVisible(
            self.tab_indexes["qc"], kind != "SERVICE" and "QUALITY_CONTROL" in self._enabled_features
        )
        self.tabs.setTabVisible(self.tab_indexes["asset"], kind == "ASSET")

    # --- API عمومی برایِ فرمِ میزبان (detail_dimensions.py) -------------------
    def refresh(self, company_id: int) -> None:
        """بارگذاریِ همه‌یِ کمبوهایِ وابسته به داده — باید هر بار که فرمِ
        میزبان تفصیلی‌ها را رفرش می‌کند (تغییرِ گروه/شرکت) صدا زده شود."""
        self._company_id = company_id
        self._rows = catalog_service.list_items(company_id)
        self._enabled_features = {f.feature_code for f in engine_service.list_features(company_id) if f.is_enabled}

        self._reload_uoms()
        self._reload_brands()
        self._reload_manufacturers()
        self._reload_categories()

        self.default_warehouse_combo.blockSignals(True)
        self.default_warehouse_combo.clear()
        self.default_warehouse_combo.addItem("(بدونِ انبارِ پیش‌فرض)", None)
        for w in locations_service.list_warehouses(company_id, active_only=True):
            self.default_warehouse_combo.addItem(f"{w.code} — {w.name}", w.warehouse_id)
        self.default_warehouse_combo.blockSignals(False)

        self._reload_menu_groups()

        self.supplier_combo.clear()
        for s in dimensions_service.list_suppliers(company_id):
            self.supplier_combo.addItem(f"{s['code']} — {s['name']}", s["detail_account_id"])

        self.item_code_supplier_combo.clear()
        self.item_code_supplier_combo.addItem("(همهٔ تامین‌کنندگان)", None)
        for s in dimensions_service.list_suppliers(company_id):
            self.item_code_supplier_combo.addItem(f"{s['code']} — {s['name']}", s["detail_account_id"])

        self._rebuild_related_item_combo()
        self._reload_item_attributes()
        self._reload_variant_price_lists()

        self._apply_visibility()

    def _rebuild_related_item_combo(self) -> None:
        """طبقِ رفعِ باگِ واقعی: قبلاً این کمبو خودِ کالایِ در حالِ ویرایش
        را هم به‌عنوانِ گزینه‌یِ «جایگزین/مکملِ خودش» نشان می‌داد (فقط در
        لایه‌ی سرویس رد می‌شد، نه در UI) — این‌جا حذف می‌شود. چون هنگامِ
        refresh (تعویضِ گروه/شرکت) هنوز self._item_id معلوم نیست، این
        تابع دوباره در load() هم صدا زده می‌شود تا با شناخته‌شدنِ کالایِ
        در حالِ ویرایش، خودش از فهرست حذف شود."""
        self.related_item_combo.clear()
        self.bom_component_combo.clear()
        for r in self._rows:
            if r.item_id == self._item_id:
                continue
            label = f"{r.code} — {r.name or ''}"
            self.related_item_combo.addItem(label, r.item_id)
            self.bom_component_combo.addItem(label, r.item_id)

    def load(self, item_row: catalog_service.ItemRow | None) -> None:
        """پرکردنِ فرم از رویِ یک کالایِ سطحِ‌آخرِ ازپیش‌ذخیره‌شده؛ با
        None یعنی رکوردِ تازه (reset کاملِ فیلدها)."""
        if item_row is None:
            self.reset()
            return
        it = item_row
        self._item_id = it.item_id
        self._rebuild_related_item_combo()
        self.latin_name_field.setText(it.latin_name or "")
        self.short_name_field.setText(it.short_name or "")
        self.kind_combo.setCurrentIndex(self.kind_combo.findData(it.item_kind_code))
        self.uom_combo.setCurrentIndex(max(0, self.uom_combo.findData(it.base_uom_id)))
        self.brand_combo.setCurrentIndex(max(0, self.brand_combo.findData(it.brand_id)))
        self.manufacturer_combo.setCurrentIndex(max(0, self.manufacturer_combo.findData(it.manufacturer_id)))
        self.country_of_origin_field.setText(it.country_of_origin or "")
        self.costing_combo.setCurrentIndex(max(0, self.costing_combo.findData(it.costing_method_code)))
        self.lifecycle_combo.setCurrentIndex(max(0, self.lifecycle_combo.findData(it.lifecycle_status_code)))
        self.is_sellable_checkbox.setChecked(it.is_sellable)
        self.is_purchasable_checkbox.setChecked(it.is_purchasable)
        self.is_stock_tracked_checkbox.setChecked(it.is_stock_tracked)
        self.track_batch_checkbox.setChecked(it.track_batch)
        self.track_expiry_checkbox.setChecked(it.track_expiry)
        self.track_serial_checkbox.setChecked(it.track_serial)
        self.notes_field.setPlainText(it.notes or "")

        self.category_combo.setCurrentIndex(max(0, self.category_combo.findData(it.category_id)))
        self.default_warehouse_combo.setCurrentIndex(max(0, self.default_warehouse_combo.findData(it.default_warehouse_id)))
        self.barcode_field.setText(it.barcode or "")
        self.qr_code_field.setText(it.qr_code_data or "")
        self.sku_field.setText(it.sku or "")
        self.own_barcode_label.setText(it.barcode or "(بدونِ بارکد)")

        self.purchase_lead_time_field.setText(str(it.purchase_lead_time_days) if it.purchase_lead_time_days is not None else "")
        self.purchase_min_order_field.setText(str(it.purchase_min_order_qty) if it.purchase_min_order_qty is not None else "")
        self.purchase_package_qty_field.setText(str(it.purchase_package_qty) if it.purchase_package_qty is not None else "")

        self.max_discount_field.setText(str(it.max_discount_percent) if it.max_discount_percent is not None else "")
        self.sales_commission_field.setText(str(it.sales_commission_percent) if it.sales_commission_percent is not None else "")
        self.warranty_months_field.setText(str(it.warranty_months) if it.warranty_months is not None else "")
        self.default_tax_percent_field.setText(str(it.default_tax_percent) if it.default_tax_percent is not None else "")

        self.seo_title_field.setText(it.seo_title or "")
        self.seo_slug_field.setText(it.seo_url_slug or "")
        self.seo_description_field.setText(it.seo_meta_description or "")
        self.seo_keywords_field.setText(it.seo_meta_keywords or "")
        self.website_category_field.setText(it.website_category or "")
        self.website_tags_field.setText(it.website_tags or "")

        self.pos_shortcut_field.setText(it.pos_shortcut_key or "")
        self.pos_color_field.setText(it.pos_button_color or "")
        self._apply_pos_color_swatch(it.pos_button_color or "")
        self.pos_menu_group_combo.setCurrentIndex(max(0, self.pos_menu_group_combo.findData(it.pos_menu_group_id)))
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

        self.asset_status_label.setText("")
        self._apply_visibility()
        self._refresh_suppliers_table()
        self._refresh_item_codes_table()
        self._refresh_related_table()
        self._refresh_bom_lines()
        self._refresh_variants_table()

    def reset(self) -> None:
        self._item_id = None
        self._current_bom_id = None
        self.latin_name_field.clear()
        self.short_name_field.clear()
        self.kind_combo.setCurrentIndex(0)
        if self.uom_combo.count():
            self.uom_combo.setCurrentIndex(0)
        self.brand_combo.setCurrentIndex(0)
        self.manufacturer_combo.setCurrentIndex(0)
        self.country_of_origin_field.clear()
        self.costing_combo.setCurrentIndex(0)
        self.lifecycle_combo.setCurrentIndex(max(0, self.lifecycle_combo.findData("ACTIVE")))
        self.is_sellable_checkbox.setChecked(True)
        self.is_purchasable_checkbox.setChecked(True)
        self.is_stock_tracked_checkbox.setChecked(True)
        self.track_batch_checkbox.setChecked(False)
        self.track_expiry_checkbox.setChecked(False)
        self.track_serial_checkbox.setChecked(False)
        self.notes_field.clear()

        self.category_combo.setCurrentIndex(0)
        self.default_warehouse_combo.setCurrentIndex(0)
        self.barcode_field.clear()
        self.qr_code_field.clear()
        self.sku_field.clear()
        self.own_barcode_label.setText("(بدونِ بارکد)")
        self.variants_table.setRowCount(0)
        self.variant_notes_field.clear()
        self.variant_price_field.clear()
        self._variant_selection = {}
        self._load_attribute_values_list()

        self.purchase_lead_time_field.clear()
        self.purchase_min_order_field.clear()
        self.purchase_package_qty_field.clear()

        self.max_discount_field.clear()
        self.sales_commission_field.clear()
        self.warranty_months_field.clear()
        self.default_tax_percent_field.clear()

        self.seo_title_field.clear()
        self.seo_slug_field.clear()
        self.seo_description_field.clear()
        self.seo_keywords_field.clear()
        self.website_category_field.clear()
        self.website_tags_field.clear()

        self.pos_shortcut_field.clear()
        self.pos_color_field.clear()
        self._apply_pos_color_swatch("")
        self.pos_menu_group_combo.setCurrentIndex(0)
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
        self.asset_status_label.setText("")

        self.supplier_table.setRowCount(0)
        self.item_codes_table.setRowCount(0)
        self.related_table.setRowCount(0)
        self.bom_lines_table.setRowCount(0)
        self.bom_status_label.setText("ابتدا کالا را ذخیره کنید.")
        self._apply_visibility()

    def lifecycle_status_code(self) -> str:
        return self.lifecycle_combo.currentData() or "ACTIVE"

    def collect_fields(self) -> catalog_service.ItemFields:
        if self.uom_combo.currentData() is None:
            raise ValueError("ابتدا یک واحدِ اندازه‌گیری تعریف کنید.")
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
            default_tax_percent=_decimal_or_none(self.default_tax_percent_field.text()),
            warranty_months=_int_or_none(self.warranty_months_field.text()),
            seo_title=self.seo_title_field.text().strip() or None,
            seo_url_slug=self.seo_slug_field.text().strip() or None,
            seo_meta_description=self.seo_description_field.text().strip() or None,
            seo_meta_keywords=self.seo_keywords_field.text().strip() or None,
            website_category=self.website_category_field.text().strip() or None,
            website_tags=self.website_tags_field.text().strip() or None,
            pos_shortcut_key=self.pos_shortcut_field.text().strip() or None,
            pos_button_color=self.pos_color_field.text().strip() or None,
            pos_menu_group_id=self.pos_menu_group_combo.currentData(),
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

    # --- تامین‌کنندگان -----------------------------------------------------
    def _refresh_suppliers_table(self) -> None:
        self.supplier_table.setRowCount(0)
        if self._item_id is None:
            return
        rows = extended_service.list_item_suppliers(self._item_id)
        self.supplier_table.setRowCount(len(rows))
        for row_index, r in enumerate(rows):
            label = self.supplier_combo.itemText(self.supplier_combo.findData(r.supplier_detail_account_id))
            values = ["بله" if r.is_preferred else "خیر", str(r.lead_time_days or ""), label or str(r.supplier_detail_account_id)]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, r.item_supplier_id)
                self.supplier_table.setItem(row_index, col_index, item)

    def _add_supplier(self) -> None:
        if self._item_id is None:
            QMessageBox.information(self, "توجه", "ابتدا کالا را ذخیره کنید، سپس تامین‌کننده اضافه کنید.")
            return
        supplier_id = self.supplier_combo.currentData()
        if supplier_id is None:
            return
        try:
            extended_service.add_item_supplier(self._item_id, supplier_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh_suppliers_table()

    def _remove_supplier(self) -> None:
        if self._item_id is None:
            return
        selected = self.supplier_table.selectedItems()
        if not selected:
            return
        try:
            extended_service.remove_item_supplier(selected[0].data(Qt.UserRole), self._item_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh_suppliers_table()

    # --- کد/نامِ کالا نزدِ تامین‌کننده -----------------------------------------
    def _refresh_item_codes_table(self) -> None:
        self.item_codes_table.setRowCount(0)
        if self._item_id is None:
            return
        rows = spi_service.list_item_supplier_codes(self._item_id)
        self.item_codes_table.setRowCount(len(rows))
        for row_index, r in enumerate(rows):
            if r.supplier_detail_account_id is None:
                supplier_label = "(همهٔ تامین‌کنندگان)"
            else:
                idx = self.item_code_supplier_combo.findData(r.supplier_detail_account_id)
                supplier_label = self.item_code_supplier_combo.itemText(idx) if idx >= 0 else str(r.supplier_detail_account_id)
            values = [_SUPPLIER_CODE_TYPE_LABELS.get(r.value_type, r.value_type), supplier_label, r.supplier_code]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, r.item_supplier_code_id)
                self.item_codes_table.setItem(row_index, col_index, item)

    def _add_item_supplier_code(self) -> None:
        if self._item_id is None:
            QMessageBox.information(self, "توجه", "ابتدا کالا را ذخیره کنید، سپس کد/نامِ تامین‌کننده اضافه کنید.")
            return
        value = self.item_code_value_field.text().strip()
        if not value:
            return
        try:
            spi_service.add_item_supplier_code(
                self._item_id, value, self.item_code_supplier_combo.currentData(), self.item_code_type_combo.currentData(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.item_code_value_field.clear()
        self._refresh_item_codes_table()

    def _edit_item_supplier_code(self, row: int, _column: int) -> None:
        item_supplier_code_id = self.item_codes_table.item(row, 0).data(Qt.UserRole)
        current = next(
            (r for r in spi_service.list_item_supplier_codes(self._item_id) if r.item_supplier_code_id == item_supplier_code_id),
            None,
        )
        if current is None:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("ویرایشِ کد/نامِ تامین‌کننده")
        form = QVBoxLayout(dialog)
        type_combo = QComboBox()
        type_combo.addItem(_SUPPLIER_CODE_TYPE_LABELS["CODE"], "CODE")
        type_combo.addItem(_SUPPLIER_CODE_TYPE_LABELS["NAME"], "NAME")
        type_combo.setCurrentIndex(max(0, type_combo.findData(current.value_type)))
        form.addWidget(type_combo)
        supplier_combo = QComboBox()
        for i in range(self.item_code_supplier_combo.count()):
            supplier_combo.addItem(self.item_code_supplier_combo.itemText(i), self.item_code_supplier_combo.itemData(i))
        supplier_combo.setCurrentIndex(max(0, supplier_combo.findData(current.supplier_detail_account_id)))
        form.addWidget(supplier_combo)
        value_field = QLineEdit(current.supplier_code)
        form.addWidget(value_field)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return
        try:
            spi_service.update_item_supplier_code(
                item_supplier_code_id, value_field.text(), supplier_combo.currentData(), type_combo.currentData(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh_item_codes_table()

    def _remove_item_supplier_code(self) -> None:
        selected = self.item_codes_table.selectedItems()
        if not selected:
            return
        try:
            spi_service.delete_item_supplier_code(selected[0].data(Qt.UserRole))
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh_item_codes_table()

    # --- کالاهایِ مرتبط ------------------------------------------------------
    def _refresh_related_table(self) -> None:
        self.related_table.setRowCount(0)
        if self._item_id is None:
            return
        rows = catalog_service.list_related_items(self._item_id)
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
        if self._item_id is None:
            QMessageBox.information(self, "توجه", "ابتدا کالا را ذخیره کنید، سپس کالایِ جایگزین/مکمل اضافه کنید.")
            return
        related_item_id = self.related_item_combo.currentData()
        relation_type_code = self.relation_type_combo.currentData()
        if related_item_id is None:
            return
        try:
            catalog_service.add_related_item(self._item_id, related_item_id, relation_type_code)
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
        if self._item_id is None:
            self.bom_status_label.setText("ابتدا کالا را ذخیره کنید.")
            return
        boms = extended_service.list_boms(self._item_id)
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
        if self._item_id is None:
            return
        try:
            extended_service.create_bom(self._item_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh_bom_lines()

    def _add_bom_line(self) -> None:
        if self._current_bom_id is None:
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
        if self._item_id is None:
            self.asset_status_label.setText("ابتدا کالا را ذخیره کنید.")
            return
        useful_life = _int_or_none(self.useful_life_field.text())
        cost = _decimal_or_none(self.acquisition_cost_field.text())
        if useful_life is None or cost is None:
            self.asset_status_label.setText("عمرِ مفید و بهایِ تحصیل را وارد کنید.")
            return
        try:
            extended_service.set_asset_detail(
                self._item_id,
                useful_life_months=useful_life,
                acquisition_date=self.acquisition_date_field.date().toPython(),
                acquisition_cost=cost,
                depreciation_method_code=self.depreciation_method_combo.currentData(),
                asset_tag_no=self.asset_tag_field.text().strip() or None,
                depreciation_group_code=self.depreciation_group_field.text().strip() or None,
                salvage_value=_decimal_or_none(self.salvage_value_field.text()) or decimal.Decimal(0),
            )
        except ValueError as exc:
            self.asset_status_label.setText(str(exc))
            return
        self.asset_status_label.setText("اطلاعاتِ دارایی ذخیره شد.")
