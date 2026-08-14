"""فروشِ اینترنتی و Omnichannel (مرحلهٔ ۸) — اتصالات، نگاشتِ کالا/مشتری،
گزارشِ همگام‌سازی، و مسیریابیِ توزیع‌شدهٔ سفارش (DOM)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.services import commercial_ecommerce as ecommerce_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.ui.widgets import FieldGrid, FieldSpec, LayoutEditMixin

_PLATFORM_LABELS = {"WOOCOMMERCE": "ووکامرس", "PRESTASHOP": "پرستاشاپ", "OTHER": "سایر"}
_SYNC_STATUS_LABELS = {"IMPORTED": "ایمپورت‌شده", "FAILED": "ناموفق", "DUPLICATE": "تکراری"}
_STRATEGY_LABELS = {"MOST_STOCK": "بیشترین موجودی", "REGION_MATCH": "تطبیقِ منطقه", "LOWEST_COST": "کمترین هزینه", "FIXED_WAREHOUSE": "انبارِ ثابت"}


class CommercialEcommerceScreen(LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._connections: list = []
        self._selected_connection_id: int | None = None
        self._items: list[catalog_service.ItemRow] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(12)

        title = QLabel("فروشِ اینترنتی و Omnichannel")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._build_connections_tab(), "اتصالات و نگاشت‌ها")
        tabs.addTab(self._build_routing_tab(), "مسیریابیِ سفارش")
        outer.addWidget(tabs, stretch=1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    # --- اتصالات و نگاشت‌ها ---------------------------------------------
    def _build_connections_tab(self) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)

        left = QVBoxLayout()
        self.connections_table = QTableWidget(0, 3)
        self.connections_table.setHorizontalHeaderLabels(["پلتفرم", "آدرسِ فروشگاه", "وضعیت"])
        self.connections_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.connections_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.connections_table.verticalHeader().setVisible(False)
        self.connections_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.connections_table.cellClicked.connect(self._on_connection_selected)
        left.addWidget(self.connections_table, stretch=1)

        self.platform_combo = QComboBox()
        for code, label in _PLATFORM_LABELS.items():
            self.platform_combo.addItem(label, code)
        self.store_url_field = QLineEdit()
        self.store_url_field.setPlaceholderText("آدرسِ فروشگاه (URL)")
        self.channel_combo = QComboBox()
        self.warehouse_combo = QComboBox()
        self.conn_form_grid = FieldGrid([
            FieldSpec("platform", "پلتفرم", self.platform_combo, span=1),
            FieldSpec("store_url", "آدرسِ فروشگاه (URL)", self.store_url_field, span=3),
            FieldSpec("channel", "کانالِ فروش", self.channel_combo, span=1),
            FieldSpec("warehouse", "انبار", self.warehouse_combo, span=2),
        ])
        self.register_field_grids("commercial_ecommerce_connections", [self.conn_form_grid])
        conn_form = QVBoxLayout()
        conn_form.addWidget(self.conn_form_grid)
        add_conn_button = QPushButton("🔗")
        add_conn_button.setObjectName("primaryIconButton")
        add_conn_button.setFixedWidth(40)
        add_conn_button.setToolTip("اتصالِ تازه")
        add_conn_button.clicked.connect(self._add_connection)
        conn_form.addWidget(add_conn_button)
        disconnect_button = QPushButton("🔌")
        disconnect_button.setObjectName("dangerIconButton")
        disconnect_button.setFixedWidth(34)
        disconnect_button.setToolTip("قطعِ اتصالِ انتخاب‌شده")
        disconnect_button.clicked.connect(self._disconnect)
        conn_form.addWidget(disconnect_button)
        left.addLayout(conn_form)
        outer.addLayout(left, stretch=2)

        right = QVBoxLayout()
        right.addWidget(QLabel("نگاشتِ کالا (SKUِ خارجی ↔ کالایِ داخلی)"))
        self.item_mappings_table = QTableWidget(0, 2)
        self.item_mappings_table.setHorizontalHeaderLabels(["SKUِ خارجی", "کالایِ داخلی"])
        self.item_mappings_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.item_mappings_table.verticalHeader().setVisible(False)
        self.item_mappings_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.item_mappings_table.setMaximumHeight(120)
        right.addWidget(self.item_mappings_table)
        item_map_form = QHBoxLayout()
        self.sku_field = QLineEdit()
        self.sku_field.setPlaceholderText("SKUِ خارجی")
        item_map_form.addWidget(self.sku_field)
        self.map_item_combo = QComboBox()
        item_map_form.addWidget(self.map_item_combo, stretch=1)
        add_item_map_button = QPushButton("🗺️")
        add_item_map_button.setObjectName("iconButton")
        add_item_map_button.setFixedWidth(34)
        add_item_map_button.setToolTip("نگاشت")
        add_item_map_button.clicked.connect(self._add_item_mapping)
        item_map_form.addWidget(add_item_map_button)
        right.addLayout(item_map_form)

        right.addWidget(QLabel("نگاشتِ مشتری (شناسهٔ خارجی ↔ مشتریِ داخلی)"))
        self.customer_mappings_table = QTableWidget(0, 2)
        self.customer_mappings_table.setHorizontalHeaderLabels(["شناسهٔ خارجی", "مشتریِ داخلی"])
        self.customer_mappings_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.customer_mappings_table.verticalHeader().setVisible(False)
        self.customer_mappings_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.customer_mappings_table.setMaximumHeight(120)
        right.addWidget(self.customer_mappings_table)
        customer_map_form = QHBoxLayout()
        self.external_customer_field = QLineEdit()
        self.external_customer_field.setPlaceholderText("شناسهٔ خارجیِ مشتری")
        customer_map_form.addWidget(self.external_customer_field)
        self.map_customer_combo = QComboBox()
        customer_map_form.addWidget(self.map_customer_combo, stretch=1)
        add_customer_map_button = QPushButton("🗺️")
        add_customer_map_button.setObjectName("iconButton")
        add_customer_map_button.setFixedWidth(34)
        add_customer_map_button.setToolTip("نگاشت")
        add_customer_map_button.clicked.connect(self._add_customer_mapping)
        customer_map_form.addWidget(add_customer_map_button)
        right.addLayout(customer_map_form)

        right.addWidget(QLabel("گزارشِ همگام‌سازیِ سفارش‌ها"))
        self.sync_log_table = QTableWidget(0, 3)
        self.sync_log_table.setHorizontalHeaderLabels(["شمارهٔ سفارشِ خارجی", "وضعیت", "پیامِ خطا"])
        self.sync_log_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sync_log_table.verticalHeader().setVisible(False)
        self.sync_log_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        right.addWidget(self.sync_log_table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        right.addWidget(self.status_label)
        outer.addLayout(right, stretch=3)
        return page

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._connections = ecommerce_service.list_connections(company_id)
        self.connections_table.setRowCount(len(self._connections))
        for row_index, c in enumerate(self._connections):
            values = [_PLATFORM_LABELS.get(c.platform_code, c.platform_code), c.store_url, "متصل" if c.sync_status == "ACTIVE" else "قطع‌شده"]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, c.connection_id)
                self.connections_table.setItem(row_index, col_index, cell)

        self.channel_combo.clear()
        for ch in pricing_service.list_channels(company_id):
            self.channel_combo.addItem(f"{ch.channel_code} — {ch.name}", ch.channel_code)

        warehouses = locations_service.list_warehouses(company_id, active_only=True)
        self.warehouse_combo.clear()
        self.warehouse_combo.addItem("(تعیین‌نشده)", None)
        for w in warehouses:
            self.warehouse_combo.addItem(f"{w.code} — {w.name}", w.warehouse_id)
        self.routing_fallback_combo.clear()
        for w in warehouses:
            self.routing_fallback_combo.addItem(f"{w.code} — {w.name}", w.warehouse_id)

        self._items = catalog_service.list_items(company_id, active_only=True)
        self.map_item_combo.clear()
        for it in self._items:
            self.map_item_combo.addItem(f"{it.code} — {it.name or ''}", it.item_id)

        self.map_customer_combo.clear()
        for c in dimensions_service.list_customers(company_id):
            self.map_customer_combo.addItem(f"{c['code']} — {c['name'] or ''}", c["detail_account_id"])

        self.routing_channel_combo.clear()
        self.routing_channel_combo.addItem("(همهٔ کانال‌ها)", None)
        for ch in pricing_service.list_channels(company_id):
            self.routing_channel_combo.addItem(f"{ch.channel_code} — {ch.name}", ch.channel_code)

        self._refresh_connection_detail()
        self._refresh_routing_rules()

    def _on_connection_selected(self, row: int, _column: int) -> None:
        self._selected_connection_id = self.connections_table.item(row, 0).data(Qt.UserRole)
        self._refresh_connection_detail()

    def _refresh_connection_detail(self) -> None:
        self.item_mappings_table.setRowCount(0)
        self.customer_mappings_table.setRowCount(0)
        self.sync_log_table.setRowCount(0)
        if self._selected_connection_id is None:
            return
        items_by_id = {it.item_id: it for it in self._items}
        item_mappings = ecommerce_service.list_item_mappings(self._selected_connection_id)
        self.item_mappings_table.setRowCount(len(item_mappings))
        for row_index, m in enumerate(item_mappings):
            item = items_by_id.get(m.item_id)
            self.item_mappings_table.setItem(row_index, 0, QTableWidgetItem(m.external_sku))
            self.item_mappings_table.setItem(row_index, 1, QTableWidgetItem(f"{item.code} — {item.name or ''}" if item else str(m.item_id)))

        customers_by_id = {c["detail_account_id"]: c for c in dimensions_service.list_customers(self._company_id())}
        customer_mappings = ecommerce_service.list_customer_mappings(self._selected_connection_id)
        self.customer_mappings_table.setRowCount(len(customer_mappings))
        for row_index, m in enumerate(customer_mappings):
            customer = customers_by_id.get(m.customer_detail_account_id)
            self.customer_mappings_table.setItem(row_index, 0, QTableWidgetItem(m.external_customer_id))
            self.customer_mappings_table.setItem(row_index, 1, QTableWidgetItem(f"{customer['code']} — {customer['name'] or ''}" if customer else str(m.customer_detail_account_id)))

        logs = ecommerce_service.list_sync_log(self._selected_connection_id)
        self.sync_log_table.setRowCount(len(logs))
        for row_index, log in enumerate(logs):
            values = [log.external_order_id, _SYNC_STATUS_LABELS.get(log.sync_status, log.sync_status), log.error_message or ""]
            for col_index, value in enumerate(values):
                self.sync_log_table.setItem(row_index, col_index, QTableWidgetItem(value))

    def _add_connection(self) -> None:
        company_id = self._company_id()
        store_url = self.store_url_field.text().strip()
        channel_code = self.channel_combo.currentData()
        if company_id is None or not store_url or channel_code is None:
            self.status_label.setText("آدرسِ فروشگاه و کانال را وارد کنید.")
            return
        try:
            ecommerce_service.create_connection(company_id, self.platform_combo.currentData(), store_url, channel_code, warehouse_id=self.warehouse_combo.currentData())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.store_url_field.clear()
        self.status_label.setText("")
        self.refresh()

    def _disconnect(self) -> None:
        if self._selected_connection_id is None:
            return
        ecommerce_service.disconnect(self._selected_connection_id)
        self.refresh()

    def _add_item_mapping(self) -> None:
        if self._selected_connection_id is None:
            self.status_label.setText("ابتدا یک اتصال را از فهرست انتخاب کنید.")
            return
        sku = self.sku_field.text().strip()
        item_id = self.map_item_combo.currentData()
        if not sku or item_id is None:
            self.status_label.setText("SKU و کالا را وارد کنید.")
            return
        ecommerce_service.map_item(self._selected_connection_id, sku, item_id)
        self.sku_field.clear()
        self.status_label.setText("")
        self._refresh_connection_detail()

    def _add_customer_mapping(self) -> None:
        if self._selected_connection_id is None:
            self.status_label.setText("ابتدا یک اتصال را از فهرست انتخاب کنید.")
            return
        external_id = self.external_customer_field.text().strip()
        customer_id = self.map_customer_combo.currentData()
        if not external_id or customer_id is None:
            self.status_label.setText("شناسهٔ خارجی و مشتری را وارد کنید.")
            return
        ecommerce_service.map_customer(self._selected_connection_id, external_id, customer_id)
        self.external_customer_field.clear()
        self.status_label.setText("")
        self._refresh_connection_detail()

    # --- مسیریابیِ سفارش (DOM) --------------------------------------------
    def _build_routing_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.addWidget(QLabel("هنگامِ ایمپورتِ سفارش، اولین قاعدهٔ منطبق (به‌ترتیبِ اولویت) اجرا می‌شود."))

        self.routing_table = QTableWidget(0, 4)
        self.routing_table.setHorizontalHeaderLabels(["کانال", "استراتژی", "انبارِ پیش‌فرض", "اولویت"])
        self.routing_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.routing_table.verticalHeader().setVisible(False)
        outer.addWidget(self.routing_table, stretch=1)

        form = QHBoxLayout()
        self.routing_channel_combo = QComboBox()
        form.addWidget(self.routing_channel_combo)
        self.routing_strategy_combo = QComboBox()
        for code, label in _STRATEGY_LABELS.items():
            self.routing_strategy_combo.addItem(label, code)
        form.addWidget(self.routing_strategy_combo)
        self.routing_fallback_combo = QComboBox()
        form.addWidget(self.routing_fallback_combo)
        self.routing_priority_field = QSpinBox()
        self.routing_priority_field.setRange(1, 9999)
        self.routing_priority_field.setValue(100)
        form.addWidget(self.routing_priority_field)
        add_rule_button = QPushButton("📐")
        add_rule_button.setObjectName("primaryIconButton")
        add_rule_button.setFixedWidth(40)
        add_rule_button.setToolTip("قاعدهٔ تازه")
        add_rule_button.clicked.connect(self._add_routing_rule)
        form.addWidget(add_rule_button)
        outer.addLayout(form)

        self.routing_status_label = QLabel("")
        self.routing_status_label.setObjectName("statusError")
        outer.addWidget(self.routing_status_label)
        return page

    def _refresh_routing_rules(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        rules = ecommerce_service.list_routing_rules(company_id)
        warehouses_by_id = {w.warehouse_id: w for w in locations_service.list_warehouses(company_id)}
        self.routing_table.setRowCount(len(rules))
        for row_index, r in enumerate(rules):
            warehouse = warehouses_by_id.get(r.fallback_warehouse_id)
            values = [
                r.channel_code or "(همهٔ کانال‌ها)", _STRATEGY_LABELS.get(r.strategy_code, r.strategy_code),
                f"{warehouse.code} — {warehouse.name}" if warehouse else str(r.fallback_warehouse_id), str(r.priority),
            ]
            for col_index, value in enumerate(values):
                self.routing_table.setItem(row_index, col_index, QTableWidgetItem(value))

    def _add_routing_rule(self) -> None:
        company_id = self._company_id()
        fallback_warehouse_id = self.routing_fallback_combo.currentData()
        if company_id is None or fallback_warehouse_id is None:
            self.routing_status_label.setText("انبارِ پیش‌فرض را انتخاب کنید.")
            return
        try:
            ecommerce_service.create_routing_rule(
                company_id, self.routing_strategy_combo.currentData(), fallback_warehouse_id,
                channel_code=self.routing_channel_combo.currentData(), priority=self.routing_priority_field.value(),
            )
        except ValueError as exc:
            self.routing_status_label.setText(str(exc))
            return
        self.routing_status_label.setText("")
        self._refresh_routing_rules()
