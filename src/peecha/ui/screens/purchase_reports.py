"""صفحهٔ گزارشاتِ تدارکات -- R233. یک صفحهٔ عمومی برایِ همهٔ گزارش‌هایِ
services/purchase_reports.py (هر آیتمِ منو یک نمونه با کدِ گزارشِ خودش)؛
فیلتر/چاپ/PDF/اکسل/جستجو از ReportScreenBase، و دابل‌کلیک رویِ ردیفِ
سندی، خودِ سند را باز می‌کند."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter, QLabel

from peecha import numerals, session
from peecha.services import companies as companies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import purchase_reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase
from peecha.ui.widgets import persist_column_widths

_TYPE_TO_NAV_CODE = {
    "PURCHASE_ORDER": "PURCH_ORDER", "PURCHASE_PROFORMA": "PURCH_PROFORMA", "PURCHASE_INVOICE": "PURCH_INVOICE",
    "PURCHASE_RETURN": "PURCH_RETURN", "CONSIGNMENT_IN": "PURCH_CONSIGNMENT_IN",
    "SALES_ORDER": "SALES_ORDER", "SALES_PROFORMA": "SALES_PROFORMA", "SALES_INVOICE": "SALES_INVOICE",
    "SALES_RETURN": "SALES_RETURN", "CONSIGNMENT_OUT": "SALES_CONSIGNMENT_OUT",
}


def _searchable_combo() -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    combo.setMinimumWidth(200)
    return combo


def _fill(combo: QComboBox, options: list[tuple[str, int]]) -> None:
    current = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    combo.addItem("— همه —", None)
    for label, value in options:
        combo.addItem(numerals.to_persian_digits(label), value)
    completer = QCompleter([combo.itemText(i) for i in range(combo.count())])
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setFilterMode(Qt.MatchContains)
    combo.setCompleter(completer)
    combo.setCurrentIndex(max(0, combo.findData(current)))
    combo.blockSignals(False)


class PurchaseReportScreen(ReportScreenBase):
    def __init__(self, report_code: str, main_window=None, side: str = "PURCHASE") -> None:
        self._side = side
        self._def = reports_service.report_def(report_code, side)
        super().__init__(self._def.title)
        self._main_window = main_window
        self._decimal_places = 0
        self._note = ""

        # وضعیتِ سندِ حسابداری در این گزارش‌ها معنا ندارد؛ تاریخ طبقِ نوعِ گزارش (بازه/تا تاریخ/بدونِ تاریخ)
        mode = self._def.date_mode
        self.status_combo.setVisible(False)
        for label in self.findChildren(QLabel):
            text = label.text()
            if text == "وضعیتِ سند:" or (mode == "none" and text in ("از تاریخ:", "تا تاریخ:")) \
                    or (mode == "as_of" and text == "از تاریخ:"):
                label.setVisible(False)
        self.date_from.setVisible(mode == "range")
        self.date_to.setVisible(mode != "none")

        self.supplier_combo = _searchable_combo()
        self.item_combo = _searchable_combo()
        self.category_combo = _searchable_combo()
        self.warehouse_combo = _searchable_combo()
        self._filter_widgets = {
            "supplier": ("تامین‌کننده:" if side == "PURCHASE" else "مشتری:", self.supplier_combo),
            "item": ("کالا:", self.item_combo),
            "category": ("گروهِ کالا:", self.category_combo),
            "warehouse": ("انبار:", self.warehouse_combo),
        }
        for key in self._def.filters:
            label, widget = self._filter_widgets[key]
            self.extra_filter_row.addWidget(QLabel(label))
            self.extra_filter_row.addWidget(widget)

        self.hint_label = QLabel(self._def.hint)
        self.hint_label.setObjectName("sectionHint")
        self.hint_label.setWordWrap(True)
        self.layout().insertWidget(1, self.hint_label)

        self.table.cellDoubleClicked.connect(self._open_row)
        self.table.setToolTip("دابل‌کلیک رویِ ردیف، سندِ مربوط را باز می‌کند.")
        persist_column_widths(self.table, f"{'purchase' if side == 'PURCHASE' else 'sales'}Report/{report_code}")
        self.add_field_help([
            (self.supplier_combo, "فقط اسنادِ همین طرفِ حساب. با تایپِ کد/نام جستجو کنید."),
            (self.item_combo, "فقط ردیف‌هایِ همین کالا."),
            (self.category_combo, "فقط کالاهایِ این گروه."),
            (self.warehouse_combo, "فقط ردیف‌هایِ این انبار."),
        ])

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is not None:
            self._decimal_places = companies_service.get_base_currency_decimal_places(company_id)
            parties = dimensions_service.list_suppliers(company_id) if self._side == "PURCHASE" \
                else dimensions_service.list_customers(company_id)
            _fill(self.supplier_combo, [(f"{s['code']} — {s['name'] or ''}", s["detail_account_id"]) for s in parties])
            _fill(self.item_combo, [(f"{i.code} — {i.name or ''}", i.item_id)
                                    for i in catalog_service.list_items(company_id, transactable_only=True)])
            _fill(self.category_combo, [(f"{c.code} — {c.name}", c.category_id) for c in catalog_service.list_categories(company_id)])
            _fill(self.warehouse_combo, [(f"{w.code} — {w.name}", w.warehouse_id) for w in locations_service.list_warehouses(company_id)])
        super().refresh()

    def _filters(self, date_from: datetime.date, date_to: datetime.date) -> reports_service.PurchaseFilters:
        def value(key: str):
            return self._filter_widgets[key][1].currentData() if key in self._def.filters else None

        if self._def.date_mode == "none":
            date_from, date_to = datetime.date(1900, 1, 1), datetime.date.today()
        elif self._def.date_mode == "as_of":
            date_from = datetime.date(1900, 1, 1)
        return reports_service.PurchaseFilters(
            date_from=date_from, date_to=date_to, supplier_id=value("supplier"), item_id=value("item"),
            category_id=value("category"), warehouse_id=value("warehouse"), side=self._side,
        )

    def _fmt(self, value, kind: str) -> str:
        if value is None or value == "":
            return ""
        if kind == reports_service.DATE:
            return numerals.format_jalali_date(value)
        if kind == reports_service.MONEY:
            return numerals.format_money(decimal.Decimal(value), self._decimal_places, None)
        if kind == reports_service.QTY:
            return numerals.format_money(decimal.Decimal(value), 2, None)
        if kind == reports_service.PERCENT:
            return f"{numerals.format_money(decimal.Decimal(value), 1, None)}٪"
        if kind in (reports_service.INT, reports_service.DAYS):
            return numerals.to_persian_digits(str(value))
        return numerals.to_persian_digits(str(value))

    def load_report(self, company_id: int, date_from: datetime.date, date_to: datetime.date):
        try:
            result = reports_service.run_report(company_id, self._def.code, self._filters(date_from, date_to))
        except ValueError as exc:
            self.hint_label.setText(f"{self._def.hint}\n⚠ {exc}")
            return [], [], None
        self.hint_label.setText(f"{self._def.hint}\n{result.note}" if result.note else self._def.hint)
        kinds = [kind for _header, kind in result.columns]
        rows = [[self._fmt(v, kinds[i]) for i, v in enumerate(row)] for row in result.rows]
        footer = result.footer()
        if footer is not None:
            footer = [footer[0]] + [self._fmt(v, kinds[i]) if v != "" else "" for i, v in enumerate(footer) if i > 0]
        self._all_row_ids = list(result.refs)
        return [h for h, _k in result.columns], rows, footer

    def extra_filters_summary(self) -> list[tuple[str, str]]:
        parts = []
        for key in self._def.filters:
            label, widget = self._filter_widgets[key]
            if widget.currentData() is not None:
                parts.append((label.rstrip(":"), widget.currentText()))
        return parts

    def _open_row(self, row: int, _col: int) -> None:
        if self._main_window is None or not (0 <= row < len(self._row_ids)):
            return
        ref = self._row_ids[row]
        if not ref:
            return
        document_id, doc_type = ref
        nav_code = _TYPE_TO_NAV_CODE.get(doc_type)
        if nav_code:
            self._main_window.open_screen(nav_code, then=lambda screen: screen.edit_document(document_id))
