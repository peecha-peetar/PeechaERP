"""فهرستِ قیمت و تخفیف (مرحلهٔ ۶) — فهرستِ قیمتِ پلکانی + قواعدِ تخفیف.
طبقِ اسکوپِ آگاهانهٔ این دور: قاعدهٔ تخفیف فقط با scope_type_code='ALL'
ساخته می‌شود (تنها حالتی که commercial_pricing.resolve_price واقعاً
اعمال می‌کند) — کوپن/پروموشن/باندل به دورِ بعدی موکول شده‌اند."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
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
from peecha.services import inventory_catalog as catalog_service
from peecha.services import commercial_pricing as pricing_service
from peecha.ui.widgets import JalaliDateEdit

_DISCOUNT_TYPE_LABELS = {"PERCENT": "درصدی", "AMOUNT": "مبلغِ ثابت", "TIERED": "پلکانی"}


class CommercialPricingScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._price_lists: list = []
        self._selected_price_list_id: int | None = None
        self._items: list[catalog_service.ItemRow] = []
        self._uoms: list = []
        self._discount_rules: list = []
        self._selected_rule_id: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("فهرستِ قیمت و تخفیف")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_price_lists_tab(), "فهرستِ قیمت")
        self.tabs.addTab(self._build_discount_rules_tab(), "قواعدِ تخفیف")
        layout.addWidget(self.tabs, stretch=1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

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
        new_pl_box.addWidget(self.pl_code_field)
        self.pl_name_field = QLineEdit()
        self.pl_name_field.setPlaceholderText("نام")
        new_pl_box.addWidget(self.pl_name_field)
        self.pl_type_combo = QComboBox()
        self.pl_type_combo.addItem("فروش", "SALES")
        self.pl_type_combo.addItem("خرید", "PURCHASE")
        new_pl_box.addWidget(self.pl_type_combo)
        add_pl_button = QPushButton("➕")
        add_pl_button.setObjectName("primaryIconButton")
        add_pl_button.setFixedWidth(40)
        add_pl_button.setToolTip("فهرستِ قیمتِ تازه")
        add_pl_button.clicked.connect(self._add_price_list)
        new_pl_box.addWidget(add_pl_button)
        left.addLayout(new_pl_box)
        outer.addLayout(left, stretch=2)

        right = QVBoxLayout()
        self.pl_items_label = QLabel("ردیف‌هایِ فهرستِ قیمتِ انتخاب‌شده")
        self.pl_items_label.setObjectName("sectionTitle")
        right.addWidget(self.pl_items_label)
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
        item_form.addWidget(self.pl_min_qty_field)
        self.pl_unit_price_field = QDoubleSpinBox()
        self.pl_unit_price_field.setDecimals(2)
        self.pl_unit_price_field.setRange(0, 999999999999)
        item_form.addWidget(self.pl_unit_price_field)
        add_item_button = QPushButton("➕")
        add_item_button.setObjectName("iconButton")
        add_item_button.setFixedWidth(34)
        add_item_button.setToolTip("ثبتِ قیمت")
        add_item_button.clicked.connect(self._add_price_list_item)
        item_form.addWidget(add_item_button)
        right.addLayout(item_form)

        self.pl_status_label = QLabel("")
        self.pl_status_label.setObjectName("statusError")
        right.addWidget(self.pl_status_label)
        outer.addLayout(right, stretch=3)
        return page

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

        self._discount_rules = pricing_service.list_discount_rules(company_id, active_only=False)
        self._refresh_discount_rules_table()
        self._refresh_price_list_items()

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
                numerals.format_amount(r.unit_price),
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
        )
        self.pl_status_label.setText("")
        self._refresh_price_list_items()

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
        form.addWidget(self.rule_code_field)
        self.rule_name_field = QLineEdit()
        self.rule_name_field.setPlaceholderText("نام")
        form.addWidget(self.rule_name_field)
        self.rule_type_combo = QComboBox()
        for code, label in _DISCOUNT_TYPE_LABELS.items():
            self.rule_type_combo.addItem(label, code)
        self.rule_type_combo.currentIndexChanged.connect(self._on_rule_type_changed)
        form.addWidget(self.rule_type_combo)
        self.rule_value_field = QDoubleSpinBox()
        self.rule_value_field.setDecimals(2)
        self.rule_value_field.setRange(0, 999999999)
        form.addWidget(self.rule_value_field)
        self.rule_priority_field = QSpinBox()
        self.rule_priority_field.setRange(1, 9999)
        self.rule_priority_field.setValue(100)
        form.addWidget(self.rule_priority_field)
        self.rule_stackable_checkbox = QCheckBox("قابلِ‌ترکیب")
        form.addWidget(self.rule_stackable_checkbox)
        add_rule_button = QPushButton("📐")
        add_rule_button.setObjectName("primaryIconButton")
        add_rule_button.setFixedWidth(40)
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
        tier_form.addWidget(self.tier_min_qty_field)
        self.tier_discount_field = QDoubleSpinBox()
        self.tier_discount_field.setDecimals(2)
        self.tier_discount_field.setRange(0, 100)
        self.tier_discount_field.setPrefix("درصدِ تخفیف: ")
        tier_form.addWidget(self.tier_discount_field)
        add_tier_button = QPushButton("➕")
        add_tier_button.setObjectName("iconButton")
        add_tier_button.setFixedWidth(34)
        add_tier_button.setToolTip("افزودنِ پله")
        add_tier_button.clicked.connect(self._add_tier)
        tier_form.addWidget(add_tier_button)
        outer.addLayout(tier_form)

        self.rule_status_label = QLabel("")
        self.rule_status_label.setObjectName("statusError")
        outer.addWidget(self.rule_status_label)
        return page

    def _on_rule_type_changed(self) -> None:
        is_tiered = self.rule_type_combo.currentData() == "TIERED"
        self.rule_value_field.setVisible(not is_tiered)

    def _refresh_discount_rules_table(self) -> None:
        self.rules_table.setRowCount(len(self._discount_rules))
        for row_index, r in enumerate(self._discount_rules):
            value_text = "پلکانی" if r.discount_type_code == "TIERED" else (
                f"{r.discount_value}٪" if r.discount_type_code == "PERCENT" else numerals.format_amount(r.discount_value)
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
