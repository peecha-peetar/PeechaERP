"""فهرستِ قیمت و تخفیف (مرحلهٔ ۶) — فهرستِ قیمتِ پلکانی + قواعدِ تخفیف.
طبقِ اسکوپِ آگاهانهٔ این دور: قاعدهٔ تخفیف فقط با scope_type_code='ALL'
ساخته می‌شود (تنها حالتی که commercial_pricing.resolve_price واقعاً
اعمال می‌کند) — کوپن/پروموشن/باندل به دورِ بعدی موکول شده‌اند.

طبقِ درخواستِ صریح («لیستِ قیمتِ تامین‌کننده از اکسل/PDF/عکس»): یک تبِ
سوم، فایلِ قیمتِ تامین‌کننده را می‌خواند، با کدها/نام‌هایِ تامین‌کننده‌یِ
ثبت‌شده‌یِ هر کالا (تشخیصِ ترکیبی) تطبیق می‌دهد، چند ستونِ افزایشیِ
درصدی/مبلغی رویِ قیمتِ تامین‌کننده اعمال می‌کند، و نتیجه را در یک فهرستِ
قیمتِ موجود ثبت می‌کند. طبقِ دورِ سومِ بازخورد: (۱) ستون‌بندی حالا با
کلیک رویِ سرستونِ یک پیش‌نمایشِ واقعیِ فایل مشخص می‌شود، نه با تایپِ
شمارهٔ ستون؛ (۲) رویِ نتیجهٔ تطبیق‌یافته می‌توان با گروه/برند فیلتر زد و
فقط بخشِ فیلترشده را ثبت کرد؛ (۳) هر تغییرِ قیمت (از این‌جا یا از تبِ
فهرستِ قیمت) در تاریخچه ثبت می‌شود و قابلِ‌بازگشت است."""

from __future__ import annotations

import datetime
import decimal
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session as app_session
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import supplier_price_import as spi_service
from peecha.ui import theme
from peecha.ui.screens.journal_entry import _fill_options, _make_searchable_combo
from peecha.ui.widgets import JalaliDateEdit, wrap_scrollable

_DISCOUNT_TYPE_LABELS = {"PERCENT": "درصدی", "AMOUNT": "مبلغِ ثابت", "TIERED": "پلکانی"}
_PREVIEW_FIXED_COLUMNS = ["ردیف", "کدِ تامین‌کننده", "کالایِ شناسایی‌شده", "قیمتِ تامین‌کننده"]
_HISTORY_SOURCE_LABELS = {"MANUAL": "دستی", "SUPPLIER_IMPORT": "وارداتِ قیمتِ تامین‌کننده", "REVERT": "بازگشت"}
_RAW_GRID_PREVIEW_ROWS = 30


class CommercialPricingScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._price_lists: list = []
        self._selected_price_list_id: int | None = None
        self._items: list[catalog_service.ItemRow] = []
        self._uoms: list = []
        self._discount_rules: list = []
        self._selected_rule_id: int | None = None

        self._suppliers: list[dict] = []
        self._categories: list = []
        self._brands: list = []
        self._spi_file_path: str | None = None
        self._spi_file_kind: str | None = None
        self._spi_raw_grid: list[list[str]] = []
        self._spi_column_roles: dict[int, str] = {}  # col_index -> "CODE" | "PRICE"
        self._spi_pending_template = None
        self._matched_rows: list[spi_service.MatchedPriceRow] = []
        self._spi_visible_row_indices: list[int] = []
        self._adjustment_steps: list[spi_service.PriceAdjustmentStep] = []
        self._sales_price_lists: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)

        title = QLabel("فهرستِ قیمت و تخفیف")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_price_lists_tab(), "فهرستِ قیمت")
        self.tabs.addTab(self._build_discount_rules_tab(), "قواعدِ تخفیف")
        self.tabs.addTab(self._build_supplier_import_tab(), "واردکردنِ لیستِ قیمتِ تامین‌کننده")
        layout.addWidget(self.tabs, stretch=1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def _user_id(self) -> int | None:
        return app_session.current_user.user_id if app_session.current_user else None

    # --- فهرستِ قیمت ---------------------------------------------------
    def _build_price_lists_tab(self) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)

        left = QVBoxLayout()
        self.price_lists_table = QTableWidget(0, 3)
        self.price_lists_table.setHorizontalHeaderLabels(["کد", "نام", "نوع"])
        self.price_lists_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.price_lists_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.price_lists_table.verticalHeader().setVisible(False)
        self.price_lists_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.price_lists_table.cellClicked.connect(self._on_price_list_selected)
        left.addWidget(self.price_lists_table, stretch=1)

        new_pl_box = QHBoxLayout()
        self.pl_code_field = QLineEdit()
        self.pl_code_field.setPlaceholderText("کد")
        self.pl_code_field.setMaximumWidth(100)
        new_pl_box.addWidget(self.pl_code_field)
        self.pl_name_field = QLineEdit()
        self.pl_name_field.setPlaceholderText("نام")
        new_pl_box.addWidget(self.pl_name_field, stretch=1)
        self.pl_type_combo = QComboBox()
        self.pl_type_combo.addItem("فروش", "SALES")
        self.pl_type_combo.addItem("خرید", "PURCHASE")
        self.pl_type_combo.setMaximumWidth(90)
        new_pl_box.addWidget(self.pl_type_combo)
        add_pl_button = QPushButton("➕")
        add_pl_button.setObjectName("primaryIconButton")
        add_pl_button.setFixedWidth(44)
        add_pl_button.setToolTip("فهرستِ قیمتِ تازه")
        add_pl_button.clicked.connect(self._add_price_list)
        new_pl_box.addWidget(add_pl_button)
        left.addLayout(new_pl_box)
        outer.addLayout(left, stretch=2)

        right = QVBoxLayout()
        items_header = QHBoxLayout()
        self.pl_items_label = QLabel("ردیف‌هایِ فهرستِ قیمتِ انتخاب‌شده")
        self.pl_items_label.setObjectName("sectionTitle")
        items_header.addWidget(self.pl_items_label, stretch=1)
        history_button = QPushButton("🕒")
        history_button.setObjectName("iconButton")
        history_button.setFixedWidth(36)
        history_button.setToolTip("تاریخچهٔ قیمت‌هایِ این فهرست (و بازگشت به قیمتِ قبلی)")
        history_button.clicked.connect(self._open_price_history_dialog)
        items_header.addWidget(history_button)
        right.addLayout(items_header)
        self.pl_items_table = QTableWidget(0, 4)
        self.pl_items_table.setHorizontalHeaderLabels(["کالا", "واحد", "حداقلِ مقدار", "بهایِ واحد"])
        self.pl_items_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pl_items_table.verticalHeader().setVisible(False)
        self.pl_items_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        right.addWidget(self.pl_items_table, stretch=1)

        item_form = QHBoxLayout()
        self.pl_item_combo = QComboBox()
        item_form.addWidget(self.pl_item_combo, stretch=2)
        self.pl_min_qty_field = QDoubleSpinBox()
        self.pl_min_qty_field.setDecimals(2)
        self.pl_min_qty_field.setRange(1, 999999999)
        self.pl_min_qty_field.setValue(1)
        self.pl_min_qty_field.setMaximumWidth(110)
        item_form.addWidget(self.pl_min_qty_field)
        self.pl_unit_price_field = QDoubleSpinBox()
        self.pl_unit_price_field.setDecimals(2)
        self.pl_unit_price_field.setRange(0, 999999999999)
        self.pl_unit_price_field.setMaximumWidth(150)
        item_form.addWidget(self.pl_unit_price_field)
        add_item_button = QPushButton("➕")
        add_item_button.setObjectName("iconButton")
        add_item_button.setFixedWidth(44)
        add_item_button.setToolTip("ثبتِ قیمت")
        add_item_button.clicked.connect(self._add_price_list_item)
        item_form.addWidget(add_item_button)
        right.addLayout(item_form)

        self.pl_status_label = QLabel("")
        self.pl_status_label.setObjectName("statusError")
        right.addWidget(self.pl_status_label)
        outer.addLayout(right, stretch=3)
        return wrap_scrollable(page)

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._price_lists = pricing_service.list_price_lists(company_id)
        self.price_lists_table.setRowCount(len(self._price_lists))
        for row_index, pl in enumerate(self._price_lists):
            for col_index, value in enumerate([pl.code, pl.name, "فروش" if pl.price_list_type_code == "SALES" else "خرید"]):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, pl.price_list_id)
                self.price_lists_table.setItem(row_index, col_index, cell)

        self._items = catalog_service.list_items(company_id, active_only=True)
        self.pl_item_combo.clear()
        for it in self._items:
            self.pl_item_combo.addItem(f"{it.code} — {it.name or ''}", it.item_id)

        self._categories = catalog_service.list_categories(company_id)
        self._brands = catalog_service.list_brands(company_id)

        self._discount_rules = pricing_service.list_discount_rules(company_id, active_only=False)
        self._refresh_discount_rules_table()
        self._refresh_price_list_items()

        self._suppliers = dimensions_service.list_suppliers(company_id)
        supplier_options = [(s["detail_account_id"], f"{s['code']} — {s['name'] or ''}") for s in self._suppliers]
        current_supplier = self.spi_supplier_combo.currentData()
        _fill_options(self.spi_supplier_combo, supplier_options)
        if current_supplier is not None and self.spi_supplier_combo.findData(current_supplier) >= 0:
            self.spi_supplier_combo.setCurrentIndex(self.spi_supplier_combo.findData(current_supplier))

        self._sales_price_lists = [pl for pl in self._price_lists if pl.price_list_type_code == "SALES"]
        current_target = self.spi_target_price_list_combo.currentData()
        self.spi_target_price_list_combo.clear()
        for pl in self._sales_price_lists:
            self.spi_target_price_list_combo.addItem(f"{pl.code} — {pl.name}", pl.price_list_id)
        if current_target is not None:
            index = self.spi_target_price_list_combo.findData(current_target)
            if index >= 0:
                self.spi_target_price_list_combo.setCurrentIndex(index)

        current_category_filter = self.spi_filter_category_combo.currentData()
        self.spi_filter_category_combo.clear()
        self.spi_filter_category_combo.addItem("همهٔ گروه‌ها", None)
        for c in self._categories:
            self.spi_filter_category_combo.addItem(c.name, c.category_id)
        index = self.spi_filter_category_combo.findData(current_category_filter)
        self.spi_filter_category_combo.setCurrentIndex(max(0, index))

        current_brand_filter = self.spi_filter_brand_combo.currentData()
        self.spi_filter_brand_combo.clear()
        self.spi_filter_brand_combo.addItem("همهٔ برندها", None)
        for b in self._brands:
            self.spi_filter_brand_combo.addItem(b.name, b.brand_id)
        index = self.spi_filter_brand_combo.findData(current_brand_filter)
        self.spi_filter_brand_combo.setCurrentIndex(max(0, index))

    def _on_price_list_selected(self, row: int, _column: int) -> None:
        self._selected_price_list_id = self.price_lists_table.item(row, 0).data(Qt.UserRole)
        self._refresh_price_list_items()

    def _refresh_price_list_items(self) -> None:
        self.pl_items_table.setRowCount(0)
        if self._selected_price_list_id is None:
            return
        items_by_id = {it.item_id: it for it in self._items}
        rows = pricing_service.list_price_list_items(self._selected_price_list_id)
        self.pl_items_table.setRowCount(len(rows))
        for row_index, r in enumerate(rows):
            item = items_by_id.get(r.item_id)
            values = [
                f"{item.code} — {item.name or ''}" if item else str(r.item_id),
                "",
                numerals.to_persian_digits(str(r.min_quantity)),
                numerals.format_company_amount(r.unit_price),
            ]
            for col_index, value in enumerate(values):
                self.pl_items_table.setItem(row_index, col_index, QTableWidgetItem(value))

    def _add_price_list(self) -> None:
        company_id = self._company_id()
        code = self.pl_code_field.text().strip()
        name = self.pl_name_field.text().strip()
        if company_id is None or not code or not name:
            self.pl_status_label.setText("کد و نام را وارد کنید.")
            return
        pricing_service.create_price_list(
            company_id, code, name, self.pl_type_combo.currentData(), app_session.current_company.base_currency_id,
            datetime.date.today(),
        )
        self.pl_code_field.clear()
        self.pl_name_field.clear()
        self.pl_status_label.setText("")
        self.refresh()

    def _add_price_list_item(self) -> None:
        if self._selected_price_list_id is None:
            self.pl_status_label.setText("ابتدا یک فهرستِ قیمت را از فهرست انتخاب کنید.")
            return
        item_id = self.pl_item_combo.currentData()
        if item_id is None:
            return
        item = next((it for it in self._items if it.item_id == item_id), None)
        if item is None:
            return
        pricing_service.set_price_list_item(
            self._selected_price_list_id, item_id, item.base_uom_id,
            decimal.Decimal(str(self.pl_unit_price_field.value())), min_quantity=decimal.Decimal(str(self.pl_min_qty_field.value())),
            changed_by_user_id=self._user_id(), source_code="MANUAL",
        )
        self.pl_status_label.setText("")
        self._refresh_price_list_items()

    # --- تاریخچهٔ قیمت -----------------------------------------------------
    def _open_price_history_dialog(self) -> None:
        if self._selected_price_list_id is None:
            self.pl_status_label.setText("ابتدا یک فهرستِ قیمت را از فهرست انتخاب کنید.")
            return
        price_list_id = self._selected_price_list_id
        items_by_id = {it.item_id: it for it in self._items}

        dialog = QDialog(self)
        dialog.setWindowTitle("تاریخچهٔ قیمت")
        dialog.resize(760, 440)
        layout = QVBoxLayout(dialog)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("کالا:"))
        item_filter_combo = _make_searchable_combo([(it.item_id, f"{it.code} — {it.name or ''}") for it in self._items])
        filter_row.addWidget(item_filter_combo, stretch=1)
        layout.addLayout(filter_row)

        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(["تاریخ", "کالا", "قیمتِ قبلی", "قیمتِ تازه", "منبع", ""])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(table, stretch=1)

        def render() -> None:
            item_id = item_filter_combo.currentData()
            rows = pricing_service.list_price_history(price_list_id, item_id=item_id)
            table.setRowCount(len(rows))
            for row_index, r in enumerate(rows):
                item = items_by_id.get(r.item_id)
                values = [
                    numerals.format_jalali_datetime(r.changed_at),
                    f"{item.code} — {item.name or ''}" if item else str(r.item_id),
                    numerals.format_company_amount(r.old_price) if r.old_price is not None else "—",
                    numerals.format_company_amount(r.new_price),
                    _HISTORY_SOURCE_LABELS.get(r.source_code, r.source_code),
                ]
                for col_index, value in enumerate(values):
                    table.setItem(row_index, col_index, QTableWidgetItem(value))
                if r.old_price is not None:
                    revert_button = QPushButton("↩")
                    revert_button.setObjectName("iconButton")
                    revert_button.setFixedWidth(36)
                    revert_button.setToolTip(f"بازگشت به {numerals.format_company_amount(r.old_price)}")
                    revert_button.clicked.connect(lambda _checked=False, hid=r.history_id: do_revert(hid))
                    table.setCellWidget(row_index, 5, revert_button)

        def do_revert(history_id: int) -> None:
            try:
                pricing_service.revert_price_history(history_id, self._user_id())
            except ValueError as exc:
                QMessageBox.warning(dialog, "خطا", str(exc))
                return
            render()
            self._refresh_price_list_items()

        item_filter_combo.currentIndexChanged.connect(lambda _i: render())
        render()

        close_buttons = QDialogButtonBox(QDialogButtonBox.Close)
        close_buttons.rejected.connect(dialog.reject)
        close_buttons.accepted.connect(dialog.accept)
        layout.addWidget(close_buttons)
        dialog.exec()

    # --- قواعدِ تخفیف ----------------------------------------------------
    def _build_discount_rules_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.addWidget(QLabel("قاعده‌هایِ عمومی (اعمال روی همهٔ کالاها) — به ترتیبِ اولویت اجرا می‌شوند."))

        self.rules_table = QTableWidget(0, 5)
        self.rules_table.setHorizontalHeaderLabels(["کد", "نام", "نوع", "مقدار/درصد", "اولویت"])
        self.rules_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rules_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rules_table.verticalHeader().setVisible(False)
        self.rules_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.rules_table.cellClicked.connect(self._on_rule_selected)
        outer.addWidget(self.rules_table, stretch=1)

        form = QHBoxLayout()
        self.rule_code_field = QLineEdit()
        self.rule_code_field.setPlaceholderText("کد")
        self.rule_code_field.setMaximumWidth(100)
        form.addWidget(self.rule_code_field)
        self.rule_name_field = QLineEdit()
        self.rule_name_field.setPlaceholderText("نام")
        form.addWidget(self.rule_name_field, stretch=1)
        self.rule_type_combo = QComboBox()
        for code, label in _DISCOUNT_TYPE_LABELS.items():
            self.rule_type_combo.addItem(label, code)
        self.rule_type_combo.setMaximumWidth(110)
        self.rule_type_combo.currentIndexChanged.connect(self._on_rule_type_changed)
        form.addWidget(self.rule_type_combo)
        self.rule_value_field = QDoubleSpinBox()
        self.rule_value_field.setDecimals(2)
        self.rule_value_field.setRange(0, 999999999)
        self.rule_value_field.setMaximumWidth(120)
        form.addWidget(self.rule_value_field)
        self.rule_priority_field = QSpinBox()
        self.rule_priority_field.setRange(1, 9999)
        self.rule_priority_field.setValue(100)
        self.rule_priority_field.setMaximumWidth(90)
        self.rule_priority_field.setToolTip("اولویتِ اجرا (عددِ کوچک‌تر زودتر اجرا می‌شود)")
        form.addWidget(self.rule_priority_field)
        self.rule_stackable_checkbox = QCheckBox("قابلِ‌ترکیب")
        form.addWidget(self.rule_stackable_checkbox)
        add_rule_button = QPushButton("📐")
        add_rule_button.setObjectName("primaryIconButton")
        add_rule_button.setFixedWidth(44)
        add_rule_button.setToolTip("قاعدهٔ تازه")
        add_rule_button.clicked.connect(self._add_discount_rule)
        form.addWidget(add_rule_button)
        outer.addLayout(form)
        self._on_rule_type_changed()

        tiers_title = QLabel("پله‌هایِ قاعدهٔ پلکانیِ انتخاب‌شده")
        tiers_title.setObjectName("sectionTitle")
        outer.addWidget(tiers_title)
        tier_form = QHBoxLayout()
        self.tier_min_qty_field = QDoubleSpinBox()
        self.tier_min_qty_field.setDecimals(2)
        self.tier_min_qty_field.setRange(0, 999999999)
        self.tier_min_qty_field.setPrefix("حداقلِ مقدار: ")
        self.tier_min_qty_field.setMaximumWidth(200)
        tier_form.addWidget(self.tier_min_qty_field)
        self.tier_discount_field = QDoubleSpinBox()
        self.tier_discount_field.setDecimals(2)
        self.tier_discount_field.setRange(0, 100)
        self.tier_discount_field.setPrefix("درصدِ تخفیف: ")
        self.tier_discount_field.setMaximumWidth(200)
        tier_form.addWidget(self.tier_discount_field)
        add_tier_button = QPushButton("➕")
        add_tier_button.setObjectName("iconButton")
        add_tier_button.setFixedWidth(44)
        add_tier_button.setToolTip("افزودنِ پله")
        add_tier_button.clicked.connect(self._add_tier)
        tier_form.addWidget(add_tier_button)
        tier_form.addStretch(1)
        outer.addLayout(tier_form)

        self.rule_status_label = QLabel("")
        self.rule_status_label.setObjectName("statusError")
        outer.addWidget(self.rule_status_label)
        return wrap_scrollable(page)

    def _on_rule_type_changed(self) -> None:
        is_tiered = self.rule_type_combo.currentData() == "TIERED"
        self.rule_value_field.setVisible(not is_tiered)

    def _refresh_discount_rules_table(self) -> None:
        self.rules_table.setRowCount(len(self._discount_rules))
        for row_index, r in enumerate(self._discount_rules):
            value_text = "پلکانی" if r.discount_type_code == "TIERED" else (
                f"{r.discount_value}٪" if r.discount_type_code == "PERCENT" else numerals.format_company_amount(r.discount_value)
            )
            values = [r.code, r.name, _DISCOUNT_TYPE_LABELS.get(r.discount_type_code, r.discount_type_code), value_text, str(r.priority)]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, r.rule_id)
                self.rules_table.setItem(row_index, col_index, cell)

    def _on_rule_selected(self, row: int, _column: int) -> None:
        self._selected_rule_id = self.rules_table.item(row, 0).data(Qt.UserRole)

    def _add_discount_rule(self) -> None:
        company_id = self._company_id()
        code = self.rule_code_field.text().strip()
        name = self.rule_name_field.text().strip()
        if company_id is None or not code or not name:
            self.rule_status_label.setText("کد و نام را وارد کنید.")
            return
        discount_type = self.rule_type_combo.currentData()
        pricing_service.create_discount_rule(
            company_id, code, name, discount_type, "ALL", priority=self.rule_priority_field.value(),
            is_stackable=self.rule_stackable_checkbox.isChecked(),
            discount_value=None if discount_type == "TIERED" else decimal.Decimal(str(self.rule_value_field.value())),
        )
        self.rule_code_field.clear()
        self.rule_name_field.clear()
        self.rule_status_label.setText("")
        self.refresh()

    def _add_tier(self) -> None:
        if self._selected_rule_id is None:
            self.rule_status_label.setText("ابتدا یک قاعدهٔ پلکانی را از فهرست انتخاب کنید.")
            return
        rule = next((r for r in self._discount_rules if r.rule_id == self._selected_rule_id), None)
        if rule is None or rule.discount_type_code != "TIERED":
            self.rule_status_label.setText("پله فقط برایِ قاعدهٔ نوعِ «پلکانی» قابلِ‌افزودن است.")
            return
        pricing_service.add_discount_rule_tier(
            self._selected_rule_id, decimal.Decimal(str(self.tier_discount_field.value())),
            min_quantity=decimal.Decimal(str(self.tier_min_qty_field.value())),
        )
        self.rule_status_label.setText("پله افزوده شد.")

    # --- واردکردنِ لیستِ قیمتِ تامین‌کننده --------------------------------
    def _build_supplier_import_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        intro_label = QLabel(
            "فایلِ اکسل، PDF یا عکسِ لیستِ قیمتِ تامین‌کننده را انتخاب کنید. سپس رویِ سرستون‌هایِ "
            "پیش‌نمایشِ زیر کلیک کنید تا ستونِ «کد/نامِ کالا» و ستونِ «قیمت» مشخص شود (تشخیص ترکیبی "
            "است: هم کد و هم نام امتحان می‌شود). عکس/PDFِ اسکن‌شده با OCR خوانده می‌شود -- چون OCR "
            "همیشه ۱۰۰٪ دقیق نیست، پیش از ثبت حتماً پیش‌نمایشِ نتیجه را بازبینی کنید."
        )
        intro_label.setWordWrap(True)
        outer.addWidget(intro_label)

        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("تامین‌کننده:"))
        self.spi_supplier_combo = _make_searchable_combo([])
        self.spi_supplier_combo.setMaximumWidth(280)
        self.spi_supplier_combo.currentIndexChanged.connect(self._on_spi_supplier_changed)
        file_row.addWidget(self.spi_supplier_combo)
        choose_file_button = QPushButton("📂")
        choose_file_button.setObjectName("iconButton")
        choose_file_button.setFixedWidth(44)
        choose_file_button.setToolTip("انتخابِ فایلِ قیمتِ تامین‌کننده (اکسل/PDF/عکس)")
        choose_file_button.clicked.connect(self._spi_choose_file)
        file_row.addWidget(choose_file_button)
        self.spi_file_label = QLabel("فایلی انتخاب نشده.")
        self.spi_file_label.setObjectName("statusHint")
        file_row.addWidget(self.spi_file_label, stretch=1)
        self.spi_sheet_combo = QComboBox()
        self.spi_sheet_combo.setMaximumWidth(160)
        self.spi_sheet_combo.setVisible(False)
        self.spi_sheet_combo.currentIndexChanged.connect(lambda _i: self._spi_extract_raw_grid())
        file_row.addWidget(self.spi_sheet_combo)
        outer.addLayout(file_row)

        ocr_row = QHBoxLayout()
        self.spi_ocr_checkbox = QCheckBox("OCR")
        self.spi_ocr_checkbox.setToolTip("خواندن با تشخیصِ نوریِ کاراکتر -- برایِ عکس/PDFِ اسکن‌شده")
        self.spi_ocr_checkbox.setVisible(False)
        ocr_row.addWidget(self.spi_ocr_checkbox)
        self.spi_ocr_lang_combo = QComboBox()
        self.spi_ocr_lang_combo.addItem("لاتین (دقیق‌ترِ کد/قیمت)", "eng")
        self.spi_ocr_lang_combo.addItem("فارسی + لاتین", "fas+eng")
        self.spi_ocr_lang_combo.setMaximumWidth(180)
        self.spi_ocr_lang_combo.setVisible(False)
        ocr_row.addWidget(self.spi_ocr_lang_combo)
        reload_button = QPushButton("🔄")
        reload_button.setObjectName("iconButton")
        reload_button.setFixedWidth(36)
        reload_button.setToolTip("بازخوانیِ فایل (پس از تغییرِ OCR/زبان/شیت)")
        reload_button.clicked.connect(self._spi_extract_raw_grid)
        ocr_row.addWidget(reload_button)
        self.spi_ocr_status_label = QLabel("")
        self.spi_ocr_status_label.setObjectName("statusHint")
        self.spi_ocr_status_label.setWordWrap(True)
        ocr_row.addWidget(self.spi_ocr_status_label, stretch=1)
        outer.addLayout(ocr_row)

        outer.addWidget(QLabel(
            "پیش‌نمایشِ فایل — رویِ سرستون کلیک کنید: بار اول = ستونِ «کد/نام»، بار دوم = ستونِ «قیمت»، "
            "بار سوم = بی‌اثر. رویِ شمارهٔ ردیف (سمتِ راست) کلیک کنید تا آخرین سطرِ سربرگ مشخص شود."
        ))
        self.spi_raw_grid_table = QTableWidget(0, 0)
        self.spi_raw_grid_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.spi_raw_grid_table.setMaximumHeight(220)
        self.spi_raw_grid_table.horizontalHeader().setSectionsClickable(True)
        self.spi_raw_grid_table.horizontalHeader().sectionClicked.connect(self._spi_on_raw_column_clicked)
        self.spi_raw_grid_table.verticalHeader().setSectionsClickable(True)
        self.spi_raw_grid_table.verticalHeader().sectionClicked.connect(self._spi_on_raw_row_clicked)
        outer.addWidget(self.spi_raw_grid_table)

        mapping_row = QHBoxLayout()
        self.spi_mapping_hint_label = QLabel("")
        self.spi_mapping_hint_label.setObjectName("statusHint")
        mapping_row.addWidget(self.spi_mapping_hint_label, stretch=1)
        self.spi_header_row_spin = QSpinBox()
        self.spi_header_row_spin.setRange(0, 50)
        self.spi_header_row_spin.setValue(1)
        self.spi_header_row_spin.setMaximumWidth(70)
        self.spi_header_row_spin.setToolTip("تعدادِ سطرهایِ سربرگ برایِ رد کردن")
        self.spi_header_row_spin.valueChanged.connect(lambda _v: self._spi_refresh_raw_grid_headers())
        mapping_row.addWidget(self.spi_header_row_spin)
        self.spi_save_template_checkbox = QCheckBox("ذخیرهٔ تنظیم")
        self.spi_save_template_checkbox.setToolTip("این ستون‌بندی را برایِ دفعاتِ بعدِ همین تامین‌کننده ذخیره کن")
        self.spi_save_template_checkbox.setChecked(True)
        mapping_row.addWidget(self.spi_save_template_checkbox)
        match_button = QPushButton("🔎")
        match_button.setObjectName("primaryIconButton")
        match_button.setFixedWidth(44)
        match_button.setToolTip("تطبیقِ ردیف‌ها با کالاها")
        match_button.clicked.connect(self._spi_match_file)
        mapping_row.addWidget(match_button)
        outer.addLayout(mapping_row)

        steps_row = QHBoxLayout()
        steps_row.addWidget(QLabel("ستونِ افزایشیِ تازه:"))
        self.spi_step_kind_combo = QComboBox()
        self.spi_step_kind_combo.addItem("درصدی", "PERCENT")
        self.spi_step_kind_combo.addItem("مبلغِ ثابت", "AMOUNT")
        self.spi_step_kind_combo.setMaximumWidth(110)
        steps_row.addWidget(self.spi_step_kind_combo)
        self.spi_step_value_field = QDoubleSpinBox()
        self.spi_step_value_field.setDecimals(2)
        self.spi_step_value_field.setRange(-999999999, 999999999)
        self.spi_step_value_field.setMaximumWidth(130)
        steps_row.addWidget(self.spi_step_value_field)
        self.spi_step_label_field = QLineEdit()
        self.spi_step_label_field.setPlaceholderText("عنوانِ ستون (اختیاری)")
        steps_row.addWidget(self.spi_step_label_field, stretch=1)
        add_step_button = QPushButton("➕")
        add_step_button.setObjectName("iconButton")
        add_step_button.setFixedWidth(44)
        add_step_button.setToolTip("افزودنِ ستونِ افزایشی")
        add_step_button.clicked.connect(self._spi_add_adjustment_step)
        steps_row.addWidget(add_step_button)
        remove_step_button = QPushButton("➖")
        remove_step_button.setObjectName("iconButton")
        remove_step_button.setFixedWidth(44)
        remove_step_button.setToolTip("حذفِ ستونِ انتخاب‌شده")
        remove_step_button.clicked.connect(self._spi_remove_selected_step)
        steps_row.addWidget(remove_step_button)
        outer.addLayout(steps_row)

        self.spi_steps_list = QListWidget()
        self.spi_steps_list.setMaximumHeight(70)
        outer.addWidget(self.spi_steps_list)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("فیلترِ نتیجه:"))
        self.spi_filter_category_combo = QComboBox()
        self.spi_filter_category_combo.setMaximumWidth(200)
        self.spi_filter_category_combo.currentIndexChanged.connect(lambda _i: self._spi_rebuild_preview_table())
        filter_row.addWidget(self.spi_filter_category_combo)
        self.spi_filter_brand_combo = QComboBox()
        self.spi_filter_brand_combo.setMaximumWidth(200)
        self.spi_filter_brand_combo.currentIndexChanged.connect(lambda _i: self._spi_rebuild_preview_table())
        filter_row.addWidget(self.spi_filter_brand_combo)
        self.spi_filter_summary_label = QLabel("")
        self.spi_filter_summary_label.setObjectName("statusHint")
        filter_row.addWidget(self.spi_filter_summary_label, stretch=1)
        outer.addLayout(filter_row)

        self.spi_preview_table = QTableWidget(0, len(_PREVIEW_FIXED_COLUMNS) + 1)
        self.spi_preview_table.setHorizontalHeaderLabels(_PREVIEW_FIXED_COLUMNS + ["قیمتِ نهایی"])
        self.spi_preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.spi_preview_table.verticalHeader().setVisible(False)
        self.spi_preview_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        outer.addWidget(self.spi_preview_table, stretch=1)

        commit_row = QHBoxLayout()
        commit_row.addWidget(QLabel("ثبت در فهرستِ قیمت:"))
        self.spi_target_price_list_combo = QComboBox()
        self.spi_target_price_list_combo.setMaximumWidth(280)
        commit_row.addWidget(self.spi_target_price_list_combo)
        commit_row.addStretch(1)
        commit_button = QPushButton("✅")
        commit_button.setObjectName("primaryIconButton")
        commit_button.setFixedWidth(44)
        commit_button.setToolTip("ثبتِ قیمت‌هایِ نمایش‌داده‌شده (طبقِ فیلترِ فعلی) در فهرستِ قیمت")
        commit_button.clicked.connect(self._spi_commit_to_price_list)
        commit_row.addWidget(commit_button)
        outer.addLayout(commit_row)

        self.spi_status_label = QLabel("")
        self.spi_status_label.setObjectName("statusError")
        self.spi_status_label.setWordWrap(True)
        outer.addWidget(self.spi_status_label)
        return wrap_scrollable(page)

    def _on_spi_supplier_changed(self) -> None:
        company_id = self._company_id()
        supplier_id = self.spi_supplier_combo.currentData()
        self._spi_pending_template = None
        if company_id is None or supplier_id is None:
            return
        template = spi_service.get_import_template(company_id, supplier_id)
        if template is None:
            return
        self.spi_header_row_spin.setValue(template.header_row_index + 1)
        if template.sheet_name:
            index = self.spi_sheet_combo.findText(template.sheet_name)
            if index >= 0:
                self.spi_sheet_combo.setCurrentIndex(index)
        self._spi_pending_template = template
        self._spi_apply_pending_template_roles()

    def _spi_apply_pending_template_roles(self) -> None:
        template = self._spi_pending_template
        if template is None or not self._spi_raw_grid:
            return
        max_cols = max((len(r) for r in self._spi_raw_grid), default=0)
        roles: dict[int, str] = {}
        if 0 <= template.code_column_index < max_cols:
            roles[template.code_column_index] = "CODE"
        if 0 <= template.price_column_index < max_cols:
            roles[template.price_column_index] = "PRICE"
        self._spi_column_roles = roles
        self._spi_pending_template = None
        self._spi_refresh_raw_grid_headers()

    def _spi_choose_file(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "انتخابِ فایلِ قیمتِ تامین‌کننده", "",
            "فایل‌هایِ پشتیبانی‌شده (*.xlsx *.xls *.pdf *.png *.jpg *.jpeg)",
        )
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext in (".xlsx", ".xls"):
            file_kind = "excel"
        elif ext == ".pdf":
            file_kind = "pdf"
        elif ext in (".png", ".jpg", ".jpeg"):
            file_kind = "image"
        else:
            self.spi_status_label.setText("فرمتِ این فایل پشتیبانی نمی‌شود.")
            return
        self._spi_file_path = path
        self._spi_file_kind = file_kind
        self.spi_file_label.setText(os.path.basename(path))
        self.spi_file_label.setToolTip(path)
        self.spi_status_label.setText("")
        self.spi_ocr_status_label.setText("")
        self._spi_column_roles = {}
        self.spi_sheet_combo.blockSignals(True)
        self.spi_sheet_combo.clear()
        self.spi_sheet_combo.setVisible(False)
        self.spi_sheet_combo.blockSignals(False)
        self.spi_ocr_checkbox.setVisible(False)
        self.spi_ocr_checkbox.setChecked(False)
        self.spi_ocr_lang_combo.setVisible(False)
        if file_kind == "excel":
            try:
                sheets = spi_service.list_excel_sheet_names(path)
            except Exception as exc:  # noqa: BLE001 -- فایلِ کاربر، خطایِ فرمت متغیر است
                self.spi_status_label.setText(f"خطا در خواندنِ فایل: {exc}")
                return
            if len(sheets) > 1:
                self.spi_sheet_combo.blockSignals(True)
                self.spi_sheet_combo.addItems(sheets)
                self.spi_sheet_combo.setVisible(True)
                self.spi_sheet_combo.blockSignals(False)
        elif file_kind == "pdf":
            try:
                text_based = spi_service.is_pdf_text_based(path)
            except Exception as exc:  # noqa: BLE001 -- فایلِ کاربر، خطایِ فرمت متغیر است
                self.spi_status_label.setText(f"خطا در خواندنِ فایل: {exc}")
                return
            if not text_based:
                self._spi_show_ocr_controls(required=False)
        elif file_kind == "image":
            self._spi_show_ocr_controls(required=True)
        self._on_spi_supplier_changed()
        self._spi_extract_raw_grid()

    def _spi_show_ocr_controls(self, required: bool) -> None:
        """required=True یعنی این فایل (عکس) بدونِ OCR اصلاً قابلِ‌خواندن
        نیست؛ required=False یعنی PDFِ اسکن‌شده است و OCR راهِ پیشنهادی
        است ولی کاربر می‌تواند تیک را بردارد (مثلاً اگر فایل را اشتباه
        انتخاب کرده)."""
        self.spi_ocr_checkbox.setVisible(True)
        self.spi_ocr_lang_combo.setVisible(True)
        if spi_service.is_ocr_available():
            self.spi_ocr_checkbox.setChecked(True)
            self.spi_ocr_checkbox.setEnabled(not required)
            self.spi_ocr_lang_combo.setEnabled(True)
            self.spi_ocr_status_label.setText(
                "⚠️ این فایل نیازمندِ OCR است -- دقتِ آن ۱۰۰٪ نیست، پیش از ثبت، پیش‌نمایش را بازبینی کنید."
            )
        else:
            self.spi_ocr_checkbox.setChecked(False)
            self.spi_ocr_checkbox.setEnabled(False)
            self.spi_ocr_lang_combo.setEnabled(False)
            self.spi_ocr_status_label.setText(
                "این فایل نیازمندِ OCR است ولی Tesseract OCR روی این سیستم نصب نیست. "
                "Tesseract را (با بستهٔ زبانِ لاتین حداقل) نصب کنید و برنامه را دوباره باز کنید."
            )

    def _spi_extract_raw_grid(self) -> None:
        file_path = self._spi_file_path
        if not file_path:
            return
        used_ocr = self._spi_file_kind == "image" or (self._spi_file_kind == "pdf" and self.spi_ocr_checkbox.isChecked())
        if used_ocr and not spi_service.is_ocr_available():
            self.spi_status_label.setText("Tesseract OCR روی این سیستم نصب نیست؛ نمی‌توان این فایل را خواند.")
            return
        try:
            if self._spi_file_kind == "excel":
                sheet_name = self.spi_sheet_combo.currentText() if self.spi_sheet_combo.isVisible() else None
                grid = spi_service.extract_excel_grid(file_path, sheet_name)
            elif self._spi_file_kind == "pdf":
                if used_ocr:
                    grid = spi_service.extract_pdf_grid_ocr(file_path, lang=self.spi_ocr_lang_combo.currentData())
                else:
                    grid = spi_service.extract_pdf_grid(file_path)
            else:
                grid = spi_service.extract_image_grid(file_path, lang=self.spi_ocr_lang_combo.currentData())
        except Exception as exc:  # noqa: BLE001 -- فایلِ کاربر، خطایِ فرمت متغیر است
            self.spi_status_label.setText(f"خطا در خواندنِ فایل: {exc}")
            return
        self._spi_raw_grid = grid
        self._matched_rows = []
        self._spi_visible_row_indices = []
        self._spi_set_raw_grid_table(grid)
        self._spi_rebuild_preview_table()
        if not grid:
            self.spi_status_label.setText(
                "هیچ داده‌ای از فایل استخراج نشد."
                + (" اگر این عکس/PDF کیفیتِ پایینی دارد، OCR ممکن است چیزی تشخیص ندهد." if used_ocr else "")
            )
            return
        self.spi_status_label.setText(
            f"{numerals.to_persian_digits(str(len(grid)))} سطر از فایل خوانده شد. رویِ سرستون‌ها کلیک کنید تا ستونِ کد/نام و قیمت مشخص شود."
        )
        self._spi_apply_pending_template_roles()

    def _spi_set_raw_grid_table(self, grid: list[list[str]]) -> None:
        preview_rows = grid[:_RAW_GRID_PREVIEW_ROWS]
        max_cols = max((len(r) for r in preview_rows), default=0)
        self.spi_raw_grid_table.setRowCount(len(preview_rows))
        self.spi_raw_grid_table.setColumnCount(max_cols)
        for row_index, row in enumerate(preview_rows):
            for col_index in range(max_cols):
                text = row[col_index] if col_index < len(row) else ""
                self.spi_raw_grid_table.setItem(row_index, col_index, QTableWidgetItem(text))
        self._spi_refresh_raw_grid_headers()

    def _spi_refresh_raw_grid_headers(self) -> None:
        header_row_count = self.spi_header_row_spin.value()
        max_cols = self.spi_raw_grid_table.columnCount()
        labels = []
        for col_index in range(max_cols):
            role = self._spi_column_roles.get(col_index)
            base = numerals.to_persian_digits(str(col_index + 1))
            if role == "CODE":
                labels.append(f"🔎 {base}")
            elif role == "PRICE":
                labels.append(f"💰 {base}")
            else:
                labels.append(base)
        self.spi_raw_grid_table.setHorizontalHeaderLabels(labels)

        code_tint = QColor(theme.ACCENT)
        code_tint.setAlpha(55)
        price_tint = QColor(theme.SUCCESS)
        price_tint.setAlpha(55)
        header_tint = QColor(theme.TEXT_DISABLED)
        header_tint.setAlpha(55)
        default_bg = QColor(theme.SURFACE)
        for row_index in range(self.spi_raw_grid_table.rowCount()):
            for col_index in range(max_cols):
                item = self.spi_raw_grid_table.item(row_index, col_index)
                if item is None:
                    continue
                role = self._spi_column_roles.get(col_index)
                if row_index < header_row_count:
                    item.setBackground(header_tint)
                elif role == "CODE":
                    item.setBackground(code_tint)
                elif role == "PRICE":
                    item.setBackground(price_tint)
                else:
                    item.setBackground(default_bg)

        code_col = next((c for c, r in self._spi_column_roles.items() if r == "CODE"), None)
        price_col = next((c for c, r in self._spi_column_roles.items() if r == "PRICE"), None)
        code_text = numerals.to_persian_digits(str(code_col + 1)) if code_col is not None else "—"
        price_text = numerals.to_persian_digits(str(price_col + 1)) if price_col is not None else "—"
        self.spi_mapping_hint_label.setText(
            f"ستونِ کد/نام: {code_text}   |   ستونِ قیمت: {price_text}"
        )

    def _spi_on_raw_column_clicked(self, col_index: int) -> None:
        current = self._spi_column_roles.get(col_index)
        if current is None:
            new_role = "CODE"
        elif current == "CODE":
            new_role = "PRICE"
        else:
            new_role = None
        if new_role is not None:
            for c, r in list(self._spi_column_roles.items()):
                if r == new_role:
                    del self._spi_column_roles[c]
        if new_role is None:
            self._spi_column_roles.pop(col_index, None)
        else:
            self._spi_column_roles[col_index] = new_role
        self._spi_refresh_raw_grid_headers()

    def _spi_on_raw_row_clicked(self, row_index: int) -> None:
        self.spi_header_row_spin.setValue(row_index + 1)

    def _spi_match_file(self) -> None:
        company_id = self._company_id()
        supplier_id = self.spi_supplier_combo.currentData()
        if company_id is None or supplier_id is None:
            self.spi_status_label.setText("ابتدا تامین‌کننده را انتخاب کنید.")
            return
        if not self._spi_raw_grid:
            self.spi_status_label.setText("ابتدا فایل را انتخاب کنید.")
            return
        code_column = next((c for c, r in self._spi_column_roles.items() if r == "CODE"), None)
        price_column = next((c for c, r in self._spi_column_roles.items() if r == "PRICE"), None)
        if code_column is None or price_column is None:
            self.spi_status_label.setText("ابتدا با کلیک رویِ سرستون‌ها، ستونِ کد/نام و ستونِ قیمت را مشخص کنید.")
            return
        header_row_index = self.spi_header_row_spin.value() - 1
        self._matched_rows = spi_service.match_grid_rows(
            company_id, self._spi_raw_grid, code_column, price_column, header_row_index, supplier_id
        )
        if self.spi_save_template_checkbox.isChecked():
            spi_service.save_import_template(
                company_id, supplier_id, code_column, price_column, header_row_index,
                sheet_name=self.spi_sheet_combo.currentText() if self.spi_sheet_combo.isVisible() else None,
            )
        matched_count = sum(1 for r in self._matched_rows if r.item_id is not None)
        used_ocr = self._spi_file_kind == "image" or (self._spi_file_kind == "pdf" and self.spi_ocr_checkbox.isChecked())
        message = f"{len(self._matched_rows)} ردیف خوانده شد؛ {matched_count} ردیف با کالا تطبیق یافت."
        if used_ocr:
            message += " ⚠️ این داده‌ها با OCR استخراج شده‌اند -- دقتِ ۱۰۰٪ ندارند؛ پیش از ثبت بازبینی کنید."
        self.spi_status_label.setText(message)
        self._spi_rebuild_preview_table()

    def _spi_add_adjustment_step(self) -> None:
        kind = self.spi_step_kind_combo.currentData()
        value = decimal.Decimal(str(self.spi_step_value_field.value()))
        label = self.spi_step_label_field.text().strip()
        if not label:
            label = f"{numerals.to_persian_digits(str(value))}٪" if kind == "PERCENT" else numerals.format_company_amount(value)
        self._adjustment_steps.append(spi_service.PriceAdjustmentStep(kind=kind, value=value, label=label))
        self.spi_step_label_field.clear()
        self._spi_refresh_steps_list()
        self._spi_rebuild_preview_table()

    def _spi_remove_selected_step(self) -> None:
        row = self.spi_steps_list.currentRow()
        if row < 0:
            return
        del self._adjustment_steps[row]
        self._spi_refresh_steps_list()
        self._spi_rebuild_preview_table()

    def _spi_refresh_steps_list(self) -> None:
        self.spi_steps_list.clear()
        for step in self._adjustment_steps:
            sign = "+" if step.value >= 0 else ""
            unit = "٪" if step.kind == "PERCENT" else ""
            self.spi_steps_list.addItem(f"{step.label} ({sign}{step.value}{unit})")

    def _spi_rebuild_preview_table(self) -> None:
        items_by_id = {it.item_id: it for it in self._items}
        category_filter = self.spi_filter_category_combo.currentData() if hasattr(self, "spi_filter_category_combo") else None
        brand_filter = self.spi_filter_brand_combo.currentData() if hasattr(self, "spi_filter_brand_combo") else None

        visible_indices = []
        for i, r in enumerate(self._matched_rows):
            if category_filter is not None or brand_filter is not None:
                item = items_by_id.get(r.item_id) if r.item_id is not None else None
                if item is None:
                    continue
                if category_filter is not None and item.category_id != category_filter:
                    continue
                if brand_filter is not None and item.brand_id != brand_filter:
                    continue
            visible_indices.append(i)
        self._spi_visible_row_indices = visible_indices

        step_headers = [step.label or f"مرحلهٔ {i + 1}" for i, step in enumerate(self._adjustment_steps)]
        headers = _PREVIEW_FIXED_COLUMNS + step_headers + ["قیمتِ نهایی", "عملیات"]
        self.spi_preview_table.setColumnCount(len(headers))
        self.spi_preview_table.setHorizontalHeaderLabels(headers)
        self.spi_preview_table.setRowCount(len(visible_indices))
        for display_row, original_index in enumerate(visible_indices):
            r = self._matched_rows[original_index]
            col = 0
            self.spi_preview_table.setItem(display_row, col, QTableWidgetItem(numerals.to_persian_digits(str(r.row_no + 1))))
            col += 1
            self.spi_preview_table.setItem(display_row, col, QTableWidgetItem(r.raw_code))
            col += 1
            item_cell = QTableWidgetItem(r.item_label or "— تطبیق‌نیافته —")
            if r.item_id is None:
                item_cell.setForeground(QColor(theme.DANGER))
            self.spi_preview_table.setItem(display_row, col, item_cell)
            col += 1
            running = r.supplier_price
            self.spi_preview_table.setItem(
                display_row, col, QTableWidgetItem(numerals.format_company_amount(running) if running is not None else "—")
            )
            col += 1
            for step in self._adjustment_steps:
                if running is not None:
                    running = spi_service.apply_adjustments(running, [step])
                self.spi_preview_table.setItem(
                    display_row, col, QTableWidgetItem(numerals.format_company_amount(running) if running is not None else "—")
                )
                col += 1
            self.spi_preview_table.setItem(
                display_row, col, QTableWidgetItem(numerals.format_company_amount(running) if running is not None else "—")
            )
            col += 1
            if r.item_id is None:
                link_button = QPushButton("🔗")
                link_button.setObjectName("iconButton")
                link_button.setFixedWidth(36)
                link_button.setToolTip("اتصالِ دستی به کالا")
                link_button.clicked.connect(lambda _checked=False, idx=original_index: self._spi_link_unmatched_row(idx))
                self.spi_preview_table.setCellWidget(display_row, col, link_button)

        total = len(self._matched_rows)
        shown = len(visible_indices)
        if total:
            self.spi_filter_summary_label.setText(
                f"{numerals.to_persian_digits(str(shown))} از {numerals.to_persian_digits(str(total))} ردیف نمایش داده می‌شود."
            )
        else:
            self.spi_filter_summary_label.setText("")

    def _spi_link_unmatched_row(self, row_index: int) -> None:
        company_id = self._company_id()
        supplier_id = self.spi_supplier_combo.currentData()
        if company_id is None or row_index >= len(self._matched_rows):
            return
        row = self._matched_rows[row_index]

        dialog = QDialog(self)
        dialog.setWindowTitle("اتصالِ کد/نامِ تامین‌کننده به کالا")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"مقدارِ خوانده‌شده از فایل: {row.raw_code}"))
        item_combo = _make_searchable_combo(
            [(it.item_id, f"{it.code} — {it.name or ''}") for it in self._items]
        )
        layout.addWidget(item_combo)
        value_type_combo = QComboBox()
        value_type_combo.addItem("این کد است", "CODE")
        value_type_combo.addItem("این نامِ کالاست", "NAME")
        layout.addWidget(value_type_combo)
        remember_checkbox = QCheckBox("ذخیره برایِ دفعاتِ بعد (نزدِ همین تامین‌کننده)")
        remember_checkbox.setChecked(True)
        layout.addWidget(remember_checkbox)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return
        item_id = item_combo.currentData()
        if item_id is None:
            return
        if remember_checkbox.isChecked() and row.raw_code:
            try:
                spi_service.add_item_supplier_code(item_id, row.raw_code, supplier_id, value_type_combo.currentData())
            except ValueError:
                pass  # مقدار از قبل برایِ همین کالا/تامین‌کننده ثبت شده — مشکلی نیست
        item = next((it for it in self._items if it.item_id == item_id), None)
        row.item_id = item_id
        row.item_label = f"{item.code} — {item.name or ''}" if item else ""
        self._spi_rebuild_preview_table()

    def _spi_commit_to_price_list(self) -> None:
        price_list_id = self.spi_target_price_list_combo.currentData()
        if price_list_id is None:
            self.spi_status_label.setText("ابتدا فهرستِ قیمتِ مقصد را انتخاب کنید.")
            return
        if not self._spi_visible_row_indices:
            self.spi_status_label.setText("ردیفی برایِ ثبت وجود ندارد (طبقِ فیلترِ فعلی چیزی نمایش داده نمی‌شود).")
            return
        items_by_id = {it.item_id: it for it in self._items}
        user_id = self._user_id()
        written = 0
        skipped = 0
        for original_index in self._spi_visible_row_indices:
            row = self._matched_rows[original_index]
            if row.item_id is None or row.supplier_price is None:
                skipped += 1
                continue
            item = items_by_id.get(row.item_id)
            if item is None:
                skipped += 1
                continue
            final_price = spi_service.apply_adjustments(row.supplier_price, self._adjustment_steps)
            pricing_service.set_price_list_item(
                price_list_id, row.item_id, item.base_uom_id, final_price,
                changed_by_user_id=user_id, source_code="SUPPLIER_IMPORT",
                note=f"وارداتِ قیمتِ تامین‌کننده (مقدارِ خام: {row.raw_code})",
            )
            written += 1
        self.spi_status_label.setText(f"{written} قیمت ثبت شد؛ {skipped} ردیف (بدونِ تطبیق یا بدونِ قیمت) نادیده گرفته شد.")
        self.refresh()
