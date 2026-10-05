"""صفحه‌هایِ ماژولِ بهایِ تمام‌شده (انبار ‹ بهایِ تمام‌شده) -- R259.

داشبورد، تنظیمات (همان تبِ تنظیماتِ انبار)، بهایِ جایگزینی. گزارش‌ها همان صفحهٔ عمومیِ گزارش‌هایِ انبار هستند.
دسترسی‌ها از سیستمِ نقش‌ها: هر صفحه یک فرم است (VIEW برایِ مشاهده، EDIT برایِ تغییر).
"""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from peecha import numerals, session as app_session
from peecha.services import roles as roles_service
from peecha.services.costing import dashboard as costing_dashboard
from peecha.services.costing import replacement as costing_replacement
from peecha.ui import theme
from peecha.ui.screens.purchase_dashboards import _ClickableKpiCard, _ProcurementDashboardBase, format_kpi
from peecha.ui.widgets import JalaliDateEdit

_KPI_STYLE = {"VALUE": ("💰", "ACCENT"), "COGS": ("📤", "CHART_ORANGE"), "AVG": ("⚖", "CHART_TEAL"),
              "VARIANCE": ("≠", "DANGER"), "REPLACEMENT": ("🔁", "CHART_PURPLE"), "LAYERS": ("🧱", "ACCENT"),
              "PENDING": ("⏳", "WARNING")}


def can(form_code: str, action: str) -> bool:
    """دسترسیِ کاربرِ جاری به یک صفحهٔ بهایِ تمام‌شده (مدیرِ کل همیشه مجاز)."""
    user = app_session.current_user
    company = app_session.current_company
    if user is None or company is None:
        return False
    return bool(getattr(user, "is_super_admin", False)) or roles_service.user_has_permission(
        user.user_id, company.company_id, form_code, action)


class CostingDashboard(_ProcurementDashboardBase):
    TITLE = "داشبوردِ بهایِ تمام‌شده"

    def __init__(self, main_window=None) -> None:
        super().__init__(main_window)
        from peecha.ui.screens.dashboard import build_chart_card

        self.cards = {}
        self._kpis = {}
        self.chart_data: dict = {}
        grid = QGridLayout()
        grid.setSpacing(14)
        for i, (code, (icon, color)) in enumerate(_KPI_STYLE.items()):
            card = _ClickableKpiCard("", icon, getattr(theme, color), lambda c=code: self._open_kpi(c))
            self.cards[code] = card
            grid.addWidget(card, i // 4, i % 4)
        for col in range(4):
            grid.setColumnStretch(col, 1)
        self.body_layout.addLayout(grid)
        charts = QGridLayout()
        charts.setSpacing(16)
        self.chart_views = {}
        for i, (key, title, report_code, options) in enumerate(costing_dashboard.CHART_TITLES):
            card, view = build_chart_card(title)
            view.setMinimumHeight(240)
            link = QPushButton("گزارش ←")
            link.setObjectName("flatButton")
            link.clicked.connect(lambda _c=False, r=report_code, o=options: self.open_report(r, o))
            card.layout().addWidget(link, alignment=Qt.AlignLeft)
            self.chart_views[key] = view
            charts.addWidget(card, i // 2, i % 2)
        self.body_layout.addLayout(charts)

    def open_report(self, report_code: str, options: dict | None = None) -> None:
        if self._main_window is None:
            return
        date_from, date_to = self.date_from.date(), self.date_to.date()
        self._main_window.open_screen(f"INV_RPT_{report_code}",
                                      then=lambda screen: screen.apply_preset(date_from, date_to, options or {}))

    def _open_kpi(self, code: str) -> None:
        kpi = self._kpis.get(code)
        if kpi is not None:
            self.open_report(kpi.report_code, kpi.options)

    def reload(self) -> None:
        from peecha.services import companies as companies_service

        company_id = self._company_id()
        if company_id is None:
            return
        self._decimal_places = companies_service.get_base_currency_decimal_places(company_id)
        self._apply(*costing_dashboard.dashboard(company_id, self.date_from.date(), self.date_to.date()))

    def _apply(self, kpis, chart_data) -> None:
        from peecha.ui.screens.warehouse_dashboard import render_series_chart

        self.chart_data = chart_data
        self._kpis = {k.code: k for k in kpis}
        for code, kpi in self._kpis.items():
            card = self.cards[code]
            card._title_label.setText(kpi.title)
            card.set_value(format_kpi(kpi.value, kpi.kind, self._decimal_places))
            card.setToolTip(f"فرمول: {kpi.formula}\nکلیک: گزارشِ مبدا")
        for key, data in chart_data.items():
            render_series_chart(self.chart_views[key], data["labels"], data["series"])


class CostingSettingsScreen(QWidget):
    """تنظیماتِ بهایِ تمام‌شده -- همان تبِ «تنظیماتِ قیمت‌گذاری» (یک منبعِ واحد)، با دسترسیِ EDIT."""

    FORM = "costing_settings"

    def __init__(self) -> None:
        super().__init__()
        from peecha.ui.screens.inventory_settings import _CostingSettingsTab

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        self.tab = _CostingSettingsTab()
        layout.addWidget(self.tab)

    def refresh(self) -> None:
        self.tab.refresh()
        allowed = can(self.FORM, "EDIT")
        for w in self.tab.findChildren(QPushButton):
            w.setEnabled(allowed)
        if not allowed:
            self.tab.status_label.setText("برایِ تغییرِ روش و سیاست‌ها دسترسیِ «ویرایش» لازم است.")


class ReplacementCostScreen(QWidget):
    """ثبت و فهرستِ بهایِ جایگزینیِ دستی (منبعِ MANUAL برایِ NIFO و گزارشِ مغایرت)."""

    FORM = "costing_replacement"

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        title = QLabel("بهایِ جایگزینی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        hint = QLabel("بهایِ جایگزینی (قیمتِ روزِ خرید) برایِ روشِ NIFO و گزارشِ «بهایِ جایگزینی». بها به ازایِ واحدِ "
                      "انتخابی وارد و به واحدِ پایه تبدیل می‌شود؛ هر ثبت در Audit می‌ماند.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QHBoxLayout()
        self.item_combo = QComboBox()
        self.item_combo.setEditable(True)
        self.item_combo.setInsertPolicy(QComboBox.NoInsert)
        self.item_combo.setMinimumWidth(240)
        self.item_combo.currentIndexChanged.connect(self._item_changed)
        self.uom_combo = QComboBox()
        self.warehouse_combo = QComboBox()
        self.cost_field = QDoubleSpinBox()
        self.cost_field.setRange(0, 1e13)
        self.cost_field.setDecimals(2)
        self.date_field = JalaliDateEdit()
        self.note_field = QLineEdit()
        self.note_field.setPlaceholderText("علت/منبع")
        for label, w in (("کالا", self.item_combo), ("واحد", self.uom_combo), ("انبار", self.warehouse_combo),
                         ("بها", self.cost_field), ("از تاریخ", self.date_field), ("توضیح", self.note_field)):
            form.addWidget(QLabel(label))
            form.addWidget(w)
        self.save_button = QPushButton("ثبتِ بهایِ جایگزینی")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self.save)
        form.addWidget(self.save_button)
        layout.addLayout(form)
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["کالا", "انبار", "بهایِ واحدِ پایه", "از تاریخ", "منبع", "توضیح"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, stretch=1)
        self._items: dict[int, object] = {}

    def _company_id(self):
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        from peecha.services import inventory_catalog as catalog_service
        from peecha.services import inventory_locations as locations_service

        company_id = self._company_id()
        if company_id is None:
            return
        self.item_combo.blockSignals(True)
        self.item_combo.clear()
        self._items = {i.item_id: i for i in catalog_service.list_items(company_id, transactable_only=True)}
        for i in self._items.values():
            self.item_combo.addItem(numerals.to_persian_digits(f"{i.code} — {i.name or ''}"), i.item_id)
        self.item_combo.blockSignals(False)
        self.warehouse_combo.clear()
        self.warehouse_combo.addItem("— همهٔ انبارها —", None)
        for w in locations_service.list_warehouses(company_id, active_only=True):
            self.warehouse_combo.addItem(f"{w.code} — {w.name}", w.warehouse_id)
        self.date_field.setDate(datetime.date.today())
        self._item_changed()
        self.save_button.setEnabled(can(self.FORM, "EDIT"))
        self._fill_table()

    def _item_changed(self, *_args) -> None:
        from peecha.services import unit_conversion as uc

        self.uom_combo.clear()
        item_id = self.item_combo.currentData()
        if item_id is None:
            return
        for u in uc.get_item_units(item_id):
            self.uom_combo.addItem(f"{u.name or u.code} (×{numerals.to_persian_digits(str(u.factor.normalize()))})", u.uom_id)

    def _fill_table(self) -> None:
        company_id = self._company_id()
        rows = costing_replacement.list_replacement_costs(company_id) if company_id else []
        whs = {self.warehouse_combo.itemData(i): self.warehouse_combo.itemText(i) for i in range(self.warehouse_combo.count())}
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            item = self._items.get(row.item_id)
            cells = [f"{item.code} — {item.name or ''}" if item else str(row.item_id), whs.get(row.warehouse_id, ""),
                     numerals.format_money(row.unit_cost, 2), numerals.format_jalali_date(row.effective_date),
                     costing_replacement.SOURCES.get(row.source_code, row.source_code), row.note or ""]
            for c, text in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(numerals.to_persian_digits(str(text))))

    def save(self) -> bool:
        company_id = self._company_id()
        item_id = self.item_combo.currentData()
        if company_id is None or item_id is None:
            return False
        if not can(self.FORM, "EDIT"):
            QMessageBox.warning(self, "بهایِ جایگزینی", "دسترسیِ ثبتِ بهایِ جایگزینی ندارید.")
            return False
        user = app_session.current_user
        try:
            costing_replacement.set_replacement_cost(
                company_id, item_id, decimal.Decimal(str(self.cost_field.value())), self.date_field.date(),
                warehouse_id=self.warehouse_combo.currentData(), uom_id=self.uom_combo.currentData(),
                note=self.note_field.text().strip() or None, user_id=user.user_id if user else None)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return False
        theme.set_status_label(self.status_label, "ثبت شد.", ok=True)
        self.note_field.clear()
        self._fill_table()
        return True
