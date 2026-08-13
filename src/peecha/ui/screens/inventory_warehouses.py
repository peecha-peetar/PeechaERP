"""انبارها و مکان‌هایِ انبار (inv.warehouses/bin_locations) — فرمِ تب‌دار
پوشش‌دهندهٔ انبارِ ساده تا چندشعبه‌ای (پایه/مکانی/عملیاتی/کنترلِ‌موجودی/
کیفیت/امنیت/تجهیزات/POS/تولید/مالی/توضیحات) + درختِ Bin Location."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
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
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import commercial_pos as pos_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import hr as hr_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_engine as engine_service
from peecha.services import inventory_locations as locations_service
from peecha.services import users as users_service
from peecha.ui.widgets import FieldHelpMixin

_COLUMNS = ["فعال", "پیش‌فرض", "نوع", "نام", "کد"]
_BIN_COLUMNS = ["فعال", "قابلِ‌برداشت", "نوع", "بارکد", "نام", "کد"]

_TYPE_LABELS: dict[str, str] = {
    "GENERAL": "عمومی", "PROJECT": "پروژه‌ای", "PRODUCTION_LINE": "خطِ تولید",
    "QUARANTINE": "قرنطینه", "TRANSIT": "درِراه/ترانزیت",
    "CENTRAL": "مرکزی", "BRANCH": "شعبه", "STORE": "فروشگاه", "RAW_MATERIAL": "موادِ اولیه",
    "FINISHED_GOODS": "کالایِ ساخته‌شده", "SEMI_FINISHED": "نیمه‌ساخته", "SCRAP": "ضایعات",
    "CONSIGNMENT": "امانی", "VEHICLE": "خودرو (سیار)", "RETURNED": "مرجوعی",
}
_WITHDRAWAL_POLICY_LABELS: dict[str, str] = {
    "FIFO": "اول‌وارد اول‌خارج (FIFO)", "LIFO": "آخر‌وارد اول‌خارج (LIFO)",
    "FEFO": "زودانقضاتر اول‌خارج (FEFO)", "MANUAL": "دستی",
}
_ACCESS_LEVEL_LABELS: dict[str, str] = {"PUBLIC": "عمومی", "RESTRICTED": "محدود (فقط کاربرانِ مجاز)"}
_COSTING_METHOD_LABELS: dict[str, str] = {"FIFO": "FIFO", "WEIGHTED_AVERAGE": "میانگینِ موزون", "STANDARD": "بهایِ استاندارد"}
_FINANCIAL_MAPPING_KEYS = ("INVENTORY_ASSET", "INVENTORY_ADJUSTMENT_GAIN", "INVENTORY_ADJUSTMENT_LOSS")


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


def _set_combo(combo: QComboBox, value) -> None:
    combo.setCurrentIndex(max(0, combo.findData(value)))


class _BinLocationDialog(QDialog):
    def __init__(self, parent: QWidget, existing_bins: list[locations_service.BinLocationRow]) -> None:
        super().__init__(parent)
        self.setWindowTitle("مکانِ انبارِ جدید")
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("کد"))
        self.code_field = QLineEdit()
        layout.addWidget(self.code_field)

        layout.addWidget(QLabel("نام"))
        self.name_field = QLineEdit()
        layout.addWidget(self.name_field)

        layout.addWidget(QLabel("نوع"))
        self.type_combo = QComboBox()
        self.type_combo.addItem("(بدونِ نوع)", None)
        for code, label in locations_service.BIN_TYPE_LABELS.items():
            self.type_combo.addItem(label, code)
        layout.addWidget(self.type_combo)

        layout.addWidget(QLabel("بارکد (اختیاری)"))
        self.barcode_field = QLineEdit()
        layout.addWidget(self.barcode_field)

        layout.addWidget(QLabel("والد (اختیاری)"))
        self.parent_combo = QComboBox()
        self.parent_combo.addItem("(بدونِ والد)", None)
        for b in existing_bins:
            self.parent_combo.addItem(f"{b.code} — {b.name or ''}", b.bin_location_id)
        layout.addWidget(self.parent_combo)

        self.pickable_checkbox = QCheckBox("قابلِ‌برداشت")
        self.pickable_checkbox.setChecked(True)
        layout.addWidget(self.pickable_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str, str | None, str, int | None, bool]:
        return (
            self.code_field.text().strip(), self.name_field.text().strip(), self.type_combo.currentData(),
            self.barcode_field.text().strip(), self.parent_combo.currentData(), self.pickable_checkbox.isChecked(),
        )


class InventoryWarehousesScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[locations_service.WarehouseRow] = []
        self._bin_rows: list[locations_service.BinLocationRow] = []
        self._user_access_rows: list[locations_service.WarehouseUserAccessRow] = []
        self._mapping_combos: dict[str, QComboBox] = {}
        self._editing_id: int | None = None
        self._enabled_features: set[str] = set()

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=3)
        self.bins_panel = self._build_bins_panel()
        outer.addWidget(self.bins_panel, stretch=2)

        self.set_field_help([
            (self.type_combo, "انبارِ پروژه‌ای باید به یک پروژهٔ تفصیلیِ حسابداری وصل شود."),
            (self.allow_negative_checkbox, "اگر روشن باشد، حواله/خروجی حتی با موجودیِ ناکافی نیز Post می‌شود."),
            (self.access_level_combo, "سطحِ محدود یعنی فقط کاربرانِ فهرست‌شده در تبِ امنیت به این انبار دسترسی دارند."),
        ])

    # ------------------------------------------------------------------
    # لیستِ انبارها
    # ------------------------------------------------------------------
    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("انبارها")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        new_button = QPushButton("+ انبارِ جدید")
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

    # ------------------------------------------------------------------
    # فرمِ تب‌دار
    # ------------------------------------------------------------------
    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)

        self.form_title = QLabel("انبارِ جدید")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        self.tabs = QTabWidget()
        self.tab_indexes: dict[str, int] = {}
        tab_defs = [
            ("basic", self._build_basic_tab(), "اطلاعاتِ پایه"),
            ("location", self._build_location_tab(), "اطلاعاتِ مکانی"),
            ("operational", self._build_operational_tab(), "تنظیماتِ عملیاتی"),
            ("stock_control", self._build_stock_control_tab(), "کنترلِ موجودی"),
            ("quality", self._build_quality_tab(), "کنترلِ کیفیت"),
            ("security", self._build_security_tab(), "امنیت"),
            ("equipment", self._build_equipment_tab(), "تجهیزات"),
            ("pos", self._build_pos_tab(), "فروشگاه (POS)"),
            ("production", self._build_production_tab(), "تولید"),
            ("financial", self._build_financial_tab(), "مالی"),
            ("notes", self._build_notes_tab(), "توضیحات"),
        ]
        for key, widget, label in tab_defs:
            self.tab_indexes[key] = self.tabs.addTab(_wrap_scrollable(widget), label)
        layout.addWidget(self.tabs)

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
        return panel

    def _build_basic_tab(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(8)

        layout.addWidget(QLabel("کد"))
        self.code_field = QLineEdit()
        layout.addWidget(self.code_field)

        layout.addWidget(QLabel("نام"))
        self.name_field = QLineEdit()
        layout.addWidget(self.name_field)

        layout.addWidget(QLabel("نامِ انگلیسی"))
        self.english_name_field = QLineEdit()
        layout.addWidget(self.english_name_field)

        layout.addWidget(QLabel("نوعِ انبار"))
        self.type_combo = QComboBox()
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        layout.addWidget(self.type_combo)

        self.project_row = QWidget()
        project_layout = QVBoxLayout(self.project_row)
        project_layout.setContentsMargins(0, 0, 0, 0)
        project_layout.addWidget(QLabel("پروژه"))
        self.project_combo = QComboBox()
        project_layout.addWidget(self.project_combo)
        layout.addWidget(self.project_row)

        layout.addWidget(QLabel("واحدِ سازمانی"))
        self.org_unit_combo = QComboBox()
        layout.addWidget(self.org_unit_combo)

        layout.addWidget(QLabel("مرکزِ هزینه"))
        self.cost_center_combo = QComboBox()
        layout.addWidget(self.cost_center_combo)

        self.is_default_checkbox = QCheckBox("انبارِ پیش‌فرض")
        layout.addWidget(self.is_default_checkbox)

        self.is_active_checkbox = QCheckBox("فعال")
        self.is_active_checkbox.setChecked(True)
        layout.addWidget(self.is_active_checkbox)

        layout.addStretch(1)
        return panel

    def _build_location_tab(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(8)

        layout.addWidget(QLabel("کشور"))
        self.country_field = QLineEdit()
        layout.addWidget(self.country_field)

        layout.addWidget(QLabel("استان"))
        self.province_field = QLineEdit()
        layout.addWidget(self.province_field)

        layout.addWidget(QLabel("شهر"))
        self.city_field = QLineEdit()
        layout.addWidget(self.city_field)

        layout.addWidget(QLabel("آدرس"))
        self.address_field = QLineEdit()
        layout.addWidget(self.address_field)

        layout.addWidget(QLabel("کدپستی"))
        self.postal_code_field = QLineEdit()
        layout.addWidget(self.postal_code_field)

        layout.addWidget(QLabel("تلفن"))
        self.phone_field = QLineEdit()
        layout.addWidget(self.phone_field)

        layout.addWidget(QLabel("مختصاتِ GPS"))
        self.gps_field = QLineEdit()
        layout.addWidget(self.gps_field)

        layout.addWidget(QLabel("مسئول/مدیرِ انبار"))
        self.manager_combo = QComboBox()
        layout.addWidget(self.manager_combo)

        layout.addStretch(1)
        return panel

    def _build_operational_tab(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(8)

        self.allow_purchase_checkbox = QCheckBox("مجازِ خرید")
        self.allow_purchase_checkbox.setChecked(True)
        layout.addWidget(self.allow_purchase_checkbox)

        self.allow_sale_checkbox = QCheckBox("مجازِ فروش")
        self.allow_sale_checkbox.setChecked(True)
        layout.addWidget(self.allow_sale_checkbox)

        self.allow_production_checkbox = QCheckBox("مجازِ تولید")
        layout.addWidget(self.allow_production_checkbox)

        self.allow_transfer_checkbox = QCheckBox("مجازِ انتقال")
        self.allow_transfer_checkbox.setChecked(True)
        layout.addWidget(self.allow_transfer_checkbox)

        self.allow_cycle_count_checkbox = QCheckBox("مجازِ انبارگردانی")
        self.allow_cycle_count_checkbox.setChecked(True)
        layout.addWidget(self.allow_cycle_count_checkbox)

        self.allow_reservation_checkbox = QCheckBox("مجازِ رزرو")
        self.allow_reservation_checkbox.setChecked(True)
        layout.addWidget(self.allow_reservation_checkbox)

        self.allow_direct_sale_checkbox = QCheckBox("مجازِ فروشِ مستقیم")
        layout.addWidget(self.allow_direct_sale_checkbox)

        self.allow_negative_checkbox = QCheckBox("اجازهٔ موجودیِ منفی")
        layout.addWidget(self.allow_negative_checkbox)

        self.requires_receipt_approval_checkbox = QCheckBox("نیازمندِ تاییدِ رسید")
        layout.addWidget(self.requires_receipt_approval_checkbox)

        self.requires_issue_approval_checkbox = QCheckBox("نیازمندِ تاییدِ حواله")
        layout.addWidget(self.requires_issue_approval_checkbox)

        self.temp_controlled_checkbox = QCheckBox("کنترلِ دما")
        self.temp_controlled_checkbox.toggled.connect(self._on_temp_toggled)
        layout.addWidget(self.temp_controlled_checkbox)

        self.temp_row = QWidget()
        temp_layout = QHBoxLayout(self.temp_row)
        temp_layout.setContentsMargins(0, 0, 0, 0)
        temp_layout.addWidget(QLabel("حداقل"))
        self.min_temp_field = QDoubleSpinBox()
        self.min_temp_field.setRange(-100, 100)
        temp_layout.addWidget(self.min_temp_field)
        temp_layout.addWidget(QLabel("حداکثر"))
        self.max_temp_field = QDoubleSpinBox()
        self.max_temp_field.setRange(-100, 100)
        temp_layout.addWidget(self.max_temp_field)
        layout.addWidget(self.temp_row)
        self.temp_row.setVisible(False)

        layout.addStretch(1)
        return panel

    def _build_stock_control_tab(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(8)

        layout.addWidget(QLabel("روشِ قیمت‌گذاری"))
        self.costing_method_combo = QComboBox()
        self.costing_method_combo.addItem("(پیش‌فرضِ شرکت)", None)
        for m in catalog_service.list_costing_methods():
            self.costing_method_combo.addItem(_COSTING_METHOD_LABELS.get(m.code, m.code), m.costing_method_id)
        layout.addWidget(self.costing_method_combo)

        layout.addWidget(QLabel("حداقلِ موجودی (پیش‌فرض)"))
        self.min_qty_field = QDoubleSpinBox()
        self.min_qty_field.setRange(0, 999_999_999)
        self.min_qty_field.setDecimals(2)
        layout.addWidget(self.min_qty_field)

        layout.addWidget(QLabel("حداکثرِ موجودی (پیش‌فرض)"))
        self.max_qty_field = QDoubleSpinBox()
        self.max_qty_field.setRange(0, 999_999_999)
        self.max_qty_field.setDecimals(2)
        layout.addWidget(self.max_qty_field)

        layout.addWidget(QLabel("نقطهٔ‌سفارش (پیش‌فرض)"))
        self.reorder_point_field = QDoubleSpinBox()
        self.reorder_point_field.setRange(0, 999_999_999)
        self.reorder_point_field.setDecimals(2)
        layout.addWidget(self.reorder_point_field)

        layout.addWidget(QLabel("سیاستِ برداشت"))
        self.withdrawal_policy_combo = QComboBox()
        self.withdrawal_policy_combo.addItem("(تعیین‌نشده)", None)
        for code, label in _WITHDRAWAL_POLICY_LABELS.items():
            self.withdrawal_policy_combo.addItem(label, code)
        layout.addWidget(self.withdrawal_policy_combo)

        layout.addStretch(1)
        return panel

    def _build_quality_tab(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(8)

        self.requires_qc_checkbox = QCheckBox("نیازمندِ کنترلِ کیفیت (QC)")
        layout.addWidget(self.requires_qc_checkbox)

        self.requires_quarantine_checkbox = QCheckBox("نیازمندِ قرنطینه")
        layout.addWidget(self.requires_quarantine_checkbox)

        layout.addWidget(QLabel("انبارِ قرنطینهٔ پیش‌فرض"))
        self.quarantine_warehouse_combo = QComboBox()
        layout.addWidget(self.quarantine_warehouse_combo)

        layout.addStretch(1)
        return panel

    def _build_security_tab(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(8)

        layout.addWidget(QLabel("سطحِ دسترسی"))
        self.access_level_combo = QComboBox()
        for code, label in _ACCESS_LEVEL_LABELS.items():
            self.access_level_combo.addItem(label, code)
        layout.addWidget(self.access_level_combo)

        layout.addWidget(QLabel("کاربرانِ مجاز"))
        add_row = QHBoxLayout()
        self.access_user_combo = QComboBox()
        add_row.addWidget(self.access_user_combo, stretch=2)
        self.access_view_checkbox = QCheckBox("مشاهدهٔ موجودی")
        self.access_view_checkbox.setChecked(True)
        add_row.addWidget(self.access_view_checkbox)
        self.access_receipt_checkbox = QCheckBox("ثبتِ رسید")
        self.access_receipt_checkbox.setChecked(True)
        add_row.addWidget(self.access_receipt_checkbox)
        self.access_issue_checkbox = QCheckBox("ثبتِ حواله")
        self.access_issue_checkbox.setChecked(True)
        add_row.addWidget(self.access_issue_checkbox)
        self.access_adjust_checkbox = QCheckBox("اصلاحِ موجودی")
        self.access_adjust_checkbox.setChecked(True)
        add_row.addWidget(self.access_adjust_checkbox)
        add_access_button = QPushButton("+ افزودن")
        add_access_button.clicked.connect(self._add_access)
        add_row.addWidget(add_access_button)
        layout.addLayout(add_row)

        self.access_table = QTableWidget(0, 5)
        self.access_table.setHorizontalHeaderLabels(["کاربر", "مشاهده", "رسید", "حواله", "اصلاح"])
        self.access_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.access_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.access_table.verticalHeader().setVisible(False)
        self.access_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.access_table)

        remove_access_button = QPushButton("حذفِ ردیفِ انتخاب‌شده")
        remove_access_button.setObjectName("dangerButton")
        remove_access_button.clicked.connect(self._remove_access)
        layout.addWidget(remove_access_button)

        return panel

    def _build_equipment_tab(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(8)

        self.has_barcode_checkbox = QCheckBox("بارکدخوان")
        layout.addWidget(self.has_barcode_checkbox)
        self.has_qr_checkbox = QCheckBox("QR")
        layout.addWidget(self.has_qr_checkbox)
        self.has_rfid_checkbox = QCheckBox("RFID")
        layout.addWidget(self.has_rfid_checkbox)
        self.has_pda_checkbox = QCheckBox("PDA")
        layout.addWidget(self.has_pda_checkbox)
        self.has_scanner_checkbox = QCheckBox("اسکنر")
        layout.addWidget(self.has_scanner_checkbox)
        self.has_scale_checkbox = QCheckBox("باسکول/ترازو")
        layout.addWidget(self.has_scale_checkbox)

        layout.addStretch(1)
        return panel

    def _build_pos_tab(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(8)

        self.pos_enabled_checkbox = QCheckBox("فعال برایِ فروشگاه/POS")
        layout.addWidget(self.pos_enabled_checkbox)

        layout.addWidget(QLabel("اولویتِ برداشت"))
        self.pos_priority_field = QSpinBox()
        self.pos_priority_field.setRange(0, 999)
        layout.addWidget(self.pos_priority_field)

        layout.addWidget(QLabel("صندوق‌هایِ متصل"))
        self.pos_terminals_table = QTableWidget(0, 2)
        self.pos_terminals_table.setHorizontalHeaderLabels(["نام", "کد"])
        self.pos_terminals_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pos_terminals_table.verticalHeader().setVisible(False)
        self.pos_terminals_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.pos_terminals_table)

        return panel

    def _build_production_tab(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(8)

        layout.addWidget(QLabel("زیرانبارِ موادِ اولیه"))
        self.raw_material_wh_combo = QComboBox()
        layout.addWidget(self.raw_material_wh_combo)

        layout.addWidget(QLabel("زیرانبارِ خطِ تولید"))
        self.production_line_wh_combo = QComboBox()
        layout.addWidget(self.production_line_wh_combo)

        layout.addWidget(QLabel("زیرانبارِ کالایِ ساخته‌شده"))
        self.finished_goods_wh_combo = QComboBox()
        layout.addWidget(self.finished_goods_wh_combo)

        layout.addWidget(QLabel("زیرانبارِ ضایعات"))
        self.scrap_wh_combo = QComboBox()
        layout.addWidget(self.scrap_wh_combo)

        layout.addStretch(1)
        return panel

    def _build_financial_tab(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(8)

        layout.addWidget(QLabel("مرکزِ سود"))
        self.profit_center_combo = QComboBox()
        layout.addWidget(self.profit_center_combo)

        layout.addWidget(QLabel("نگاشتِ حسابِ این انبار (override بر نگاشتِ سراسری)"))
        for key in _FINANCIAL_MAPPING_KEYS:
            row = QHBoxLayout()
            row.addWidget(QLabel(engine_service.MAPPING_LABELS[key]), stretch=1)
            combo = QComboBox()
            combo.setMinimumWidth(220)
            self._mapping_combos[key] = combo
            row.addWidget(combo, stretch=2)
            layout.addLayout(row)

        layout.addStretch(1)
        return panel

    def _build_notes_tab(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("توضیحات/یادداشت"))
        self.notes_field = QTextEdit()
        layout.addWidget(self.notes_field)
        return panel

    # ------------------------------------------------------------------
    # مکان‌هایِ انبار (Bin Location — درختی)
    # ------------------------------------------------------------------
    def _build_bins_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("مکان‌هایِ انبار")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.add_bin_button = QPushButton("+ مکانِ جدید")
        self.add_bin_button.setObjectName("primaryButton")
        self.add_bin_button.clicked.connect(self._add_bin)
        self.add_bin_button.setEnabled(False)
        layout.addWidget(self.add_bin_button, alignment=Qt.AlignLeft)

        self.bin_tree = QTreeWidget()
        self.bin_tree.setColumnCount(len(_BIN_COLUMNS))
        self.bin_tree.setHeaderLabels(_BIN_COLUMNS)
        self.bin_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.bin_tree.header().setSectionResizeMode(4, QHeaderView.Stretch)
        layout.addWidget(self.bin_tree)

        self.delete_bin_button = QPushButton("حذفِ مکانِ انتخاب‌شده")
        self.delete_bin_button.setObjectName("dangerButton")
        self.delete_bin_button.clicked.connect(self._delete_bin)
        layout.addWidget(self.delete_bin_button)
        return _wrap_scrollable(panel)

    def _refresh_bins(self) -> None:
        self.bin_tree.clear()
        if self._editing_id is None:
            self._bin_rows = []
            return
        self._bin_rows = locations_service.list_bin_locations(self._editing_id)
        items_by_id: dict[int, QTreeWidgetItem] = {}
        for b in self._bin_rows:
            values = [
                "بله" if b.is_active else "خیر", "بله" if b.is_pickable else "خیر",
                locations_service.BIN_TYPE_LABELS.get(b.bin_type_code, b.bin_type_code or ""),
                b.barcode or "", b.name or "", b.code,
            ]
            item = QTreeWidgetItem(values)
            item.setData(0, Qt.UserRole, b.bin_location_id)
            items_by_id[b.bin_location_id] = item
        for b in self._bin_rows:
            item = items_by_id[b.bin_location_id]
            parent_item = items_by_id.get(b.parent_bin_location_id) if b.parent_bin_location_id else None
            if parent_item is not None:
                parent_item.addChild(item)
            else:
                self.bin_tree.addTopLevelItem(item)
        self.bin_tree.expandAll()

    def _add_bin(self) -> None:
        if self._editing_id is None:
            return
        dialog = _BinLocationDialog(self, self._bin_rows)
        if dialog.exec() != QDialog.Accepted:
            return
        code, name, bin_type_code, barcode, parent_id, pickable = dialog.values()
        if not code:
            return
        try:
            locations_service.create_bin_location(
                self._editing_id, code, name or None, parent_bin_location_id=parent_id,
                bin_type_code=bin_type_code, barcode=barcode or None, is_pickable=pickable,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh_bins()

    def _delete_bin(self) -> None:
        selected = self.bin_tree.selectedItems()
        if not selected or self._editing_id is None:
            return
        bin_location_id = selected[0].data(0, Qt.UserRole)
        confirm = QMessageBox.question(self, "حذفِ مکان", "این مکانِ انبار حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            locations_service.delete_bin_location(bin_location_id, self._editing_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh_bins()

    # ------------------------------------------------------------------
    # کاربرانِ مجاز
    # ------------------------------------------------------------------
    def _refresh_access(self) -> None:
        self.access_table.setRowCount(0)
        if self._editing_id is None:
            self._user_access_rows = []
            return
        self._user_access_rows = locations_service.list_warehouse_user_access(self._editing_id)
        users_by_id = {u.user_id: u.full_name for u in users_service.list_users()}
        self.access_table.setRowCount(len(self._user_access_rows))
        for row_index, a in enumerate(self._user_access_rows):
            values = [
                users_by_id.get(a.user_id, str(a.user_id)),
                "بله" if a.can_view_balance else "خیر",
                "بله" if a.can_post_receipt else "خیر",
                "بله" if a.can_post_issue else "خیر",
                "بله" if a.can_adjust else "خیر",
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, a.user_id)
                self.access_table.setItem(row_index, col_index, item)

    def _add_access(self) -> None:
        if self._editing_id is None:
            return
        user_id = self.access_user_combo.currentData()
        if user_id is None:
            return
        locations_service.set_warehouse_user_access(
            self._editing_id, user_id,
            can_view_balance=self.access_view_checkbox.isChecked(),
            can_post_receipt=self.access_receipt_checkbox.isChecked(),
            can_post_issue=self.access_issue_checkbox.isChecked(),
            can_adjust=self.access_adjust_checkbox.isChecked(),
        )
        self._refresh_access()

    def _remove_access(self) -> None:
        selected = self.access_table.selectedItems()
        if not selected or self._editing_id is None:
            return
        user_id = selected[0].data(Qt.UserRole)
        locations_service.remove_warehouse_user_access(self._editing_id, user_id)
        self._refresh_access()

    # ------------------------------------------------------------------
    # رفتار
    # ------------------------------------------------------------------
    def _on_type_changed(self) -> None:
        self.project_row.setVisible(self.type_combo.currentData() == "PROJECT")

    def _on_temp_toggled(self, checked: bool) -> None:
        self.temp_row.setVisible(checked)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        self._reset_form()
        company_id = self._company_id()
        if company_id is None:
            return
        self._enabled_features = {
            code for code in (
                "TEMPERATURE_CONTROL", "PROJECT_WAREHOUSES", "QUALITY_CONTROL",
                "BIN_LOCATIONS", "WAREHOUSE_ACCESS_CONTROL",
            )
            if engine_service.is_feature_enabled(company_id, code)
        }
        self._rows = locations_service.list_warehouses(company_id)

        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        for code in locations_service.WAREHOUSE_TYPE_CODES:
            if code == "PROJECT" and "PROJECT_WAREHOUSES" not in self._enabled_features:
                continue
            self.type_combo.addItem(_TYPE_LABELS.get(code, code), code)
        self.type_combo.blockSignals(False)

        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItem("(انتخاب کنید)", None)
        project_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.PROJECT_CODE)
        for p in dimensions_service.list_leaf_detail_accounts(company_id, project_type_id):
            self.project_combo.addItem(f"{p.code} — {p.name or ''}", p.detail_account_id)
        self.project_combo.blockSignals(False)

        self.org_unit_combo.clear()
        self.org_unit_combo.addItem("(بدون)", None)
        for o in hr_service.list_org_units(company_id):
            self.org_unit_combo.addItem(f"{o.code} — {o.name}", o.org_unit_id)

        cost_center_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.COST_CENTER_CODE)
        self.cost_center_combo.clear()
        self.cost_center_combo.addItem("(بدون)", None)
        for c in dimensions_service.list_leaf_detail_accounts(company_id, cost_center_type_id):
            self.cost_center_combo.addItem(f"{c.code} — {c.name or ''}", c.detail_account_id)

        profit_center_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.PROFIT_CENTER_CODE)
        self.profit_center_combo.clear()
        self.profit_center_combo.addItem("(بدون)", None)
        for c in dimensions_service.list_leaf_detail_accounts(company_id, profit_center_type_id):
            self.profit_center_combo.addItem(f"{c.code} — {c.name or ''}", c.detail_account_id)

        self.manager_combo.clear()
        self.manager_combo.addItem("(بدون)", None)
        self.access_user_combo.clear()
        for u in users_service.list_users():
            self.manager_combo.addItem(u.full_name, u.user_id)
            self.access_user_combo.addItem(u.full_name, u.user_id)

        accounts = [(a.account_id, f"{a.full_code} — {a.name}") for a in coa_service.list_accounts(company_id) if a.is_postable]
        for combo in self._mapping_combos.values():
            combo.clear()
            combo.addItem("(از نگاشتِ سراسری پیروی کند)", None)
            for account_id, label in accounts:
                combo.addItem(label, account_id)

        for wh_combo in (
            self.quarantine_warehouse_combo, self.raw_material_wh_combo, self.production_line_wh_combo,
            self.finished_goods_wh_combo, self.scrap_wh_combo,
        ):
            wh_combo.clear()
            wh_combo.addItem("(بدون)", None)
            for w in self._rows:
                if w.warehouse_id != self._editing_id:
                    wh_combo.addItem(f"{w.code} — {w.name}", w.warehouse_id)

        self.temp_controlled_checkbox.setEnabled("TEMPERATURE_CONTROL" in self._enabled_features)
        self.tabs.setTabVisible(self.tab_indexes["quality"], "QUALITY_CONTROL" in self._enabled_features)
        self.tabs.setTabVisible(self.tab_indexes["security"], "WAREHOUSE_ACCESS_CONTROL" in self._enabled_features)
        self.bins_panel.setVisible("BIN_LOCATIONS" in self._enabled_features)

        self.table.setRowCount(len(self._rows))
        for row_index, w in enumerate(self._rows):
            values = [
                "بله" if w.is_active else "خیر",
                "بله" if w.fields.is_default else "خیر",
                _TYPE_LABELS.get(w.fields.warehouse_type_code, w.fields.warehouse_type_code),
                w.name,
                w.code,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, w.warehouse_id)
                self.table.setItem(row_index, col_index, item)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        warehouse_id = self.table.item(row, 0).data(Qt.UserRole)
        w = next((r for r in self._rows if r.warehouse_id == warehouse_id), None)
        if w is not None:
            self._load_into_form(w)

    def _load_into_form(self, w: locations_service.WarehouseRow) -> None:
        self._editing_id = w.warehouse_id
        f = w.fields
        self.form_title.setText(f"ویرایشِ انبار — {w.name}")
        self.status_label.setText("")

        # پایه
        self.code_field.setText(w.code)
        self.code_field.setEnabled(False)
        self.name_field.setText(w.name)
        self.english_name_field.setText(f.english_name or "")
        _set_combo(self.type_combo, f.warehouse_type_code)
        _set_combo(self.project_combo, f.project_detail_account_id)
        _set_combo(self.org_unit_combo, f.org_unit_id)
        _set_combo(self.cost_center_combo, f.cost_center_detail_account_id)
        self.is_default_checkbox.setChecked(f.is_default)
        self.is_active_checkbox.setChecked(w.is_active)

        # مکانی
        self.country_field.setText(f.country or "")
        self.province_field.setText(f.province or "")
        self.city_field.setText(f.city or "")
        self.address_field.setText(f.address or "")
        self.postal_code_field.setText(f.postal_code or "")
        self.phone_field.setText(f.phone or "")
        self.gps_field.setText(f.gps_coordinates or "")
        _set_combo(self.manager_combo, f.manager_user_id)

        # عملیاتی
        self.allow_purchase_checkbox.setChecked(f.allow_purchase)
        self.allow_sale_checkbox.setChecked(f.allow_sale)
        self.allow_production_checkbox.setChecked(f.allow_production)
        self.allow_transfer_checkbox.setChecked(f.allow_transfer)
        self.allow_cycle_count_checkbox.setChecked(f.allow_cycle_count)
        self.allow_reservation_checkbox.setChecked(f.allow_reservation)
        self.allow_direct_sale_checkbox.setChecked(f.allow_direct_sale)
        self.allow_negative_checkbox.setChecked(f.allow_negative_stock)
        self.requires_receipt_approval_checkbox.setChecked(f.requires_receipt_approval)
        self.requires_issue_approval_checkbox.setChecked(f.requires_issue_approval)
        self.temp_controlled_checkbox.setChecked(f.is_temperature_controlled)
        self.min_temp_field.setValue(float(f.min_temp_c or 0))
        self.max_temp_field.setValue(float(f.max_temp_c or 0))

        # کنترلِ موجودی
        _set_combo(self.costing_method_combo, f.costing_method_id)
        self.min_qty_field.setValue(float(f.default_min_qty or 0))
        self.max_qty_field.setValue(float(f.default_max_qty or 0))
        self.reorder_point_field.setValue(float(f.default_reorder_point_qty or 0))
        _set_combo(self.withdrawal_policy_combo, f.withdrawal_policy_code)

        # کیفیت
        self.requires_qc_checkbox.setChecked(f.requires_qc)
        self.requires_quarantine_checkbox.setChecked(f.requires_quarantine)
        _set_combo(self.quarantine_warehouse_combo, f.default_quarantine_warehouse_id)

        # امنیت
        _set_combo(self.access_level_combo, f.access_level_code)

        # تجهیزات
        self.has_barcode_checkbox.setChecked(f.has_barcode_equipment)
        self.has_qr_checkbox.setChecked(f.has_qr_equipment)
        self.has_rfid_checkbox.setChecked(f.has_rfid_equipment)
        self.has_pda_checkbox.setChecked(f.has_pda_equipment)
        self.has_scanner_checkbox.setChecked(f.has_scanner_equipment)
        self.has_scale_checkbox.setChecked(f.has_scale_equipment)

        # POS
        self.pos_enabled_checkbox.setChecked(f.pos_enabled)
        self.pos_priority_field.setValue(f.pos_pick_priority or 0)
        company_id = self._company_id()
        terminals = [t for t in pos_service.list_terminals(company_id) if t.warehouse_id == w.warehouse_id] if company_id else []
        self.pos_terminals_table.setRowCount(len(terminals))
        for row_index, t in enumerate(terminals):
            self.pos_terminals_table.setItem(row_index, 0, QTableWidgetItem(t.name))
            self.pos_terminals_table.setItem(row_index, 1, QTableWidgetItem(t.code))

        # تولید
        _set_combo(self.raw_material_wh_combo, f.raw_material_warehouse_id)
        _set_combo(self.production_line_wh_combo, f.production_line_warehouse_id)
        _set_combo(self.finished_goods_wh_combo, f.finished_goods_warehouse_id)
        _set_combo(self.scrap_wh_combo, f.scrap_warehouse_id)

        # مالی
        _set_combo(self.profit_center_combo, f.profit_center_detail_account_id)
        mapping_by_key = {m.mapping_key: m.account_id for m in engine_service.list_warehouse_account_mappings(w.warehouse_id)}
        for key, combo in self._mapping_combos.items():
            _set_combo(combo, mapping_by_key.get(key))

        # توضیحات
        self.notes_field.setPlainText(f.notes or "")

        self.delete_button.setVisible(True)
        self.add_bin_button.setEnabled(True)
        self._refresh_bins()
        self._refresh_access()

    def _reset_form(self) -> None:
        self._editing_id = None
        self.form_title.setText("انبارِ جدید")
        self.status_label.setText("")

        self.code_field.clear()
        self.code_field.setEnabled(True)
        self.name_field.clear()
        self.english_name_field.clear()
        self.type_combo.setCurrentIndex(0)
        self.project_combo.setCurrentIndex(0)
        self.org_unit_combo.setCurrentIndex(0)
        self.cost_center_combo.setCurrentIndex(0)
        self.is_default_checkbox.setChecked(False)
        self.is_active_checkbox.setChecked(True)

        self.country_field.clear()
        self.province_field.clear()
        self.city_field.clear()
        self.address_field.clear()
        self.postal_code_field.clear()
        self.phone_field.clear()
        self.gps_field.clear()
        self.manager_combo.setCurrentIndex(0)

        self.allow_purchase_checkbox.setChecked(True)
        self.allow_sale_checkbox.setChecked(True)
        self.allow_production_checkbox.setChecked(False)
        self.allow_transfer_checkbox.setChecked(True)
        self.allow_cycle_count_checkbox.setChecked(True)
        self.allow_reservation_checkbox.setChecked(True)
        self.allow_direct_sale_checkbox.setChecked(False)
        self.allow_negative_checkbox.setChecked(False)
        self.requires_receipt_approval_checkbox.setChecked(False)
        self.requires_issue_approval_checkbox.setChecked(False)
        self.temp_controlled_checkbox.setChecked(False)
        self.min_temp_field.setValue(0)
        self.max_temp_field.setValue(0)

        self.costing_method_combo.setCurrentIndex(0)
        self.min_qty_field.setValue(0)
        self.max_qty_field.setValue(0)
        self.reorder_point_field.setValue(0)
        self.withdrawal_policy_combo.setCurrentIndex(0)

        self.requires_qc_checkbox.setChecked(False)
        self.requires_quarantine_checkbox.setChecked(False)
        self.quarantine_warehouse_combo.setCurrentIndex(0)

        self.access_level_combo.setCurrentIndex(0)

        self.has_barcode_checkbox.setChecked(False)
        self.has_qr_checkbox.setChecked(False)
        self.has_rfid_checkbox.setChecked(False)
        self.has_pda_checkbox.setChecked(False)
        self.has_scanner_checkbox.setChecked(False)
        self.has_scale_checkbox.setChecked(False)

        self.pos_enabled_checkbox.setChecked(False)
        self.pos_priority_field.setValue(0)
        self.pos_terminals_table.setRowCount(0)

        self.raw_material_wh_combo.setCurrentIndex(0)
        self.production_line_wh_combo.setCurrentIndex(0)
        self.finished_goods_wh_combo.setCurrentIndex(0)
        self.scrap_wh_combo.setCurrentIndex(0)

        self.profit_center_combo.setCurrentIndex(0)
        for combo in self._mapping_combos.values():
            combo.setCurrentIndex(0)

        self.notes_field.clear()

        self.delete_button.setVisible(False)
        self.add_bin_button.setEnabled(False)
        self.table.clearSelection()
        self._refresh_bins()
        self._refresh_access()

    def _collect_fields(self) -> locations_service.WarehouseFields:
        temp_controlled = self.temp_controlled_checkbox.isChecked()
        warehouse_type_code = self.type_combo.currentData()
        return locations_service.WarehouseFields(
            warehouse_type_code=warehouse_type_code,
            project_detail_account_id=self.project_combo.currentData() if warehouse_type_code == "PROJECT" else None,
            allow_negative_stock=self.allow_negative_checkbox.isChecked(),
            is_temperature_controlled=temp_controlled,
            min_temp_c=decimal.Decimal(str(self.min_temp_field.value())) if temp_controlled else None,
            max_temp_c=decimal.Decimal(str(self.max_temp_field.value())) if temp_controlled else None,
            address=self.address_field.text().strip() or None,
            is_default=self.is_default_checkbox.isChecked(),
            english_name=self.english_name_field.text().strip() or None,
            org_unit_id=self.org_unit_combo.currentData(),
            cost_center_detail_account_id=self.cost_center_combo.currentData(),
            country=self.country_field.text().strip() or None,
            province=self.province_field.text().strip() or None,
            city=self.city_field.text().strip() or None,
            postal_code=self.postal_code_field.text().strip() or None,
            phone=self.phone_field.text().strip() or None,
            gps_coordinates=self.gps_field.text().strip() or None,
            manager_user_id=self.manager_combo.currentData(),
            allow_purchase=self.allow_purchase_checkbox.isChecked(),
            allow_sale=self.allow_sale_checkbox.isChecked(),
            allow_production=self.allow_production_checkbox.isChecked(),
            allow_transfer=self.allow_transfer_checkbox.isChecked(),
            allow_cycle_count=self.allow_cycle_count_checkbox.isChecked(),
            allow_reservation=self.allow_reservation_checkbox.isChecked(),
            allow_direct_sale=self.allow_direct_sale_checkbox.isChecked(),
            requires_receipt_approval=self.requires_receipt_approval_checkbox.isChecked(),
            requires_issue_approval=self.requires_issue_approval_checkbox.isChecked(),
            costing_method_id=self.costing_method_combo.currentData(),
            default_min_qty=decimal.Decimal(str(self.min_qty_field.value())) if self.min_qty_field.value() else None,
            default_max_qty=decimal.Decimal(str(self.max_qty_field.value())) if self.max_qty_field.value() else None,
            default_reorder_point_qty=(
                decimal.Decimal(str(self.reorder_point_field.value())) if self.reorder_point_field.value() else None
            ),
            withdrawal_policy_code=self.withdrawal_policy_combo.currentData(),
            requires_qc=self.requires_qc_checkbox.isChecked(),
            requires_quarantine=self.requires_quarantine_checkbox.isChecked(),
            default_quarantine_warehouse_id=self.quarantine_warehouse_combo.currentData(),
            access_level_code=self.access_level_combo.currentData(),
            has_barcode_equipment=self.has_barcode_checkbox.isChecked(),
            has_qr_equipment=self.has_qr_checkbox.isChecked(),
            has_rfid_equipment=self.has_rfid_checkbox.isChecked(),
            has_pda_equipment=self.has_pda_checkbox.isChecked(),
            has_scanner_equipment=self.has_scanner_checkbox.isChecked(),
            has_scale_equipment=self.has_scale_checkbox.isChecked(),
            pos_enabled=self.pos_enabled_checkbox.isChecked(),
            pos_pick_priority=self.pos_priority_field.value() or None,
            raw_material_warehouse_id=self.raw_material_wh_combo.currentData(),
            production_line_warehouse_id=self.production_line_wh_combo.currentData(),
            finished_goods_warehouse_id=self.finished_goods_wh_combo.currentData(),
            scrap_warehouse_id=self.scrap_wh_combo.currentData(),
            profit_center_detail_account_id=self.profit_center_combo.currentData(),
            notes=self.notes_field.toPlainText().strip() or None,
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
        try:
            if self._editing_id is not None:
                locations_service.update_warehouse(
                    self._editing_id, company_id, code, name, self.is_active_checkbox.isChecked(), fields
                )
                warehouse_id = self._editing_id
            else:
                warehouse_id = locations_service.create_warehouse(company_id, code, name, fields)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return

        for key, combo in self._mapping_combos.items():
            account_id = combo.currentData()
            if account_id is not None:
                engine_service.set_warehouse_account_mapping(warehouse_id, key, account_id)
            else:
                engine_service.delete_warehouse_account_mapping(warehouse_id, key)

        self.refresh()

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        confirm = QMessageBox.question(self, "حذفِ انبار", "این انبار حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        company_id = self._company_id()
        try:
            locations_service.delete_warehouse(self._editing_id, company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
