"""صفحهٔ گزارشاتِ تدارکات -- R233. یک صفحهٔ عمومی برایِ همهٔ گزارش‌هایِ
services/purchase_reports.py (هر آیتمِ منو یک نمونه با کدِ گزارشِ خودش)؛
فیلتر/چاپ/PDF/اکسل/CSV/کپی/ستون‌ها از ReportScreenBase، و دابل‌کلیک رویِ ردیفِ
سندی، خودِ سند را باز می‌کند.

R239: مرتب‌سازی با کلیک رویِ سرِ ستون، گروه‌بندی با جمعِ هر گروه، نماهایِ
ذخیره‌شده، نمودارِ نتیجه، و Drill-down از ردیفِ تجمیعی (تامین‌کننده/کالا/گروه)."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QCompleter, QDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton, QVBoxLayout,
)

from peecha import numerals
from peecha.services import companies as companies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import purchase_dashboard as dashboard_service
from peecha.services import purchase_reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase
from peecha.ui.widgets import persist_column_widths

# R247: اجرایِ گزارش در رشتهٔ پس‌زمینه -- برنامهٔ اصلی (ui/main.py) روشن می‌کند؛ تست‌ها همگام می‌مانند
BACKGROUND_REPORTS = False
PAGE_SIZES = ((500, "۵۰۰"), (100, "۱۰۰"), (250, "۲۵۰"), (1000, "۱۰۰۰"), (0, "همه"))


class ReportWorker(QThread):
    """گزارش را بیرون از رشتهٔ رابط اجرا می‌کند؛ نتیجه با سیگنال (در رشتهٔ رابط) برمی‌گردد."""

    done = Signal(int, object, object)  # (نسل، نتیجه، خطا)

    # R261: تا پایانِ اجرا نگه داشته می‌شود -- وگرنه با بارگذاریِ دوباره، QThreadِ در حالِ اجرا پاک و برنامه بسته می‌شد
    _live: set = set()

    def __init__(self, generation: int, fn, *args) -> None:
        super().__init__()
        self._generation, self._fn, self._args = generation, fn, args
        ReportWorker._live.add(self)
        self.finished.connect(lambda w=self: ReportWorker._live.discard(w))

    def run(self) -> None:  # noqa: D401
        try:
            self.done.emit(self._generation, self._fn(*self._args), None)
        except Exception as exc:  # noqa: BLE001 -- به رشتهٔ رابط منتقل می‌شود
            self.done.emit(self._generation, None, exc)


_TYPE_TO_NAV_CODE = {
    "PURCHASE_ORDER": "PURCH_ORDER", "PURCHASE_PROFORMA": "PURCH_PROFORMA", "PURCHASE_INVOICE": "PURCH_INVOICE",
    "PURCHASE_RETURN": "PURCH_RETURN", "CONSIGNMENT_IN": "PURCH_CONSIGNMENT_IN",
    "SALES_ORDER": "SALES_ORDER", "SALES_PROFORMA": "SALES_PROFORMA", "SALES_INVOICE": "SALES_INVOICE",
    "SALES_RETURN": "SALES_RETURN", "CONSIGNMENT_OUT": "SALES_CONSIGNMENT_OUT",
    "PURCHASE_REQUEST": "PURCH_REQUESTS",
    "RFQ": "PURCH_RFQ",
}
_RPT_PREFIX = {"PURCHASE": "PURCH_RPT_", "SALES": "SALES_RPT_", "ACCOUNTING": "ACC_RPT_", "INVENTORY": "INV_RPT_"}
_NUMERIC = (reports_service.MONEY, reports_service.QTY, reports_service.INT, reports_service.PERCENT, reports_service.DAYS)
_LABEL_KINDS = (reports_service.TEXT, reports_service.DATE)


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


def _sort_key(value):
    if value is None or value == "":
        return (3, 0)
    if isinstance(value, (int, float, decimal.Decimal)):
        return (0, value)
    if isinstance(value, datetime.date):
        return (1, value.toordinal())
    return (2, str(value))


class ReportChartDialog(QDialog):
    """نمودارِ نتیجهٔ گزارش: یک ستونِ برچسب × یک ستونِ عددی (۱۵ موردِ بزرگ‌تر)."""

    def __init__(self, parent, title: str, result: reports_service.ReportResult) -> None:
        super().__init__(parent)
        from peecha.ui.screens.dashboard import build_chart_card

        self.setWindowTitle(f"نمودار -- {title}")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(900, 560)
        self._result = result
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.label_combo, self.value_combo, self.type_combo = QComboBox(), QComboBox(), QComboBox()
        for i, (header, kind) in enumerate(result.columns):
            if kind in _LABEL_KINDS:
                self.label_combo.addItem(header, i)
            elif kind in _NUMERIC:
                self.value_combo.addItem(header, i)
        self.type_combo.addItem("میله‌ای", "BAR")
        self.type_combo.addItem("دایره‌ای", "PIE")
        for text, combo in (("محور:", self.label_combo), ("مقدار:", self.value_combo), ("نوع:", self.type_combo)):
            row.addWidget(QLabel(text))
            row.addWidget(combo)
        row.addStretch(1)
        layout.addLayout(row)
        card, self.chart_view = build_chart_card(title)
        layout.addWidget(card, stretch=1)
        for combo in (self.label_combo, self.value_combo, self.type_combo):
            combo.currentIndexChanged.connect(self.render)
        self.render()

    def series(self) -> list[tuple[str, decimal.Decimal]]:
        li, vi = self.label_combo.currentData(), self.value_combo.currentData()
        if li is None or vi is None:
            return []
        agg: dict[str, decimal.Decimal] = {}
        for row in self._result.rows:
            label = row[li]
            label = numerals.format_jalali_date(label) if isinstance(label, datetime.date) \
                else numerals.to_persian_digits(str(label or "—"))
            agg[label] = agg.get(label, decimal.Decimal(0)) + decimal.Decimal(row[vi] or 0)
        return sorted(agg.items(), key=lambda kv: -abs(kv[1]))[:15]

    def render(self) -> None:
        from peecha.ui.screens.dashboard import render_bar_chart, render_donut_chart

        data = self.series()
        if self.type_combo.currentData() == "PIE":
            render_donut_chart(self.chart_view, [(k, v) for k, v in data if v > 0])
        else:
            render_bar_chart(self.chart_view, [k for k, _v in data], [v for _k, v in data], self.value_combo.currentText())


class PurchaseReportScreen(ReportScreenBase):
    def __init__(self, report_code: str, main_window=None, side: str = "PURCHASE") -> None:
        self._side = side
        self._def = reports_service.report_def(report_code, side)
        super().__init__(self._def.title)
        self._main_window = main_window
        self._decimal_places = 0
        self._note = ""
        self._result: reports_service.ReportResult | None = None
        self._sort_col: int | None = None
        self._sort_desc = False
        self._row_raw: dict[int, int | None] = {}

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
        self.account_combo = _searchable_combo()
        self.brand_combo = _searchable_combo()
        self.branch_combo = _searchable_combo()
        self.detail_combo = _searchable_combo()
        self._filter_widgets = {
            "account": ("حساب:", self.account_combo),
            "detail": ("تفصیلی:", self.detail_combo),
            "brand": ("برند:", self.brand_combo),
            "branch": ("شعبه:", self.branch_combo),
            "supplier": ("تامین‌کننده:" if side == "PURCHASE" else "مشتری:", self.supplier_combo),
            "item": ("کالا:", self.item_combo),
            "category": ("گروهِ کالا:", self.category_combo),
            "warehouse": ("انبار:", self.warehouse_combo),
        }
        for key in self._def.filters:
            label, widget = self._filter_widgets[key]
            self.extra_filter_row.addWidget(QLabel(label))
            self.extra_filter_row.addWidget(widget)
        # R238: گزینه‌هایِ اختصاصیِ گزارش (مرجعِ قیمت، بُعد، آستانهٔ روز، ...)
        self._option_combos: dict[str, tuple[str, QComboBox]] = {}
        # R245: گزینه‌ها در ردیفِ جدا تا ردیفِ فیلتر شلوغ و فشرده نشود
        self.options_row = QHBoxLayout()
        for key, label, choices in self._def.options:
            combo = QComboBox()
            for value, text in choices:
                combo.addItem(text, value)
            combo.currentIndexChanged.connect(lambda _i: self._reload())
            self.options_row.addWidget(QLabel(f"{label}:"))
            self.options_row.addWidget(combo)
            self.options_row.addSpacing(12)
            self._option_combos[key] = (label, combo)
        self.options_row.addStretch(1)

        self.hint_label = QLabel(self._def.hint)
        self.hint_label.setObjectName("sectionHint")
        self.hint_label.setWordWrap(True)
        self.layout().insertWidget(1, self.hint_label)

        # R239: نوارِ نما -- گروه‌بندی، نمودار، نماهایِ ذخیره‌شده
        tools = QHBoxLayout()
        tools.addWidget(QLabel("گروه‌بندی:"))
        self.group_combo = QComboBox()
        self.group_combo.addItem("— بدونِ گروه‌بندی —", None)
        self.group_combo.currentIndexChanged.connect(lambda _i: self._rebuild())
        tools.addWidget(self.group_combo)
        chart_button = QPushButton("نمودار")
        chart_button.setObjectName("flatButton")
        chart_button.clicked.connect(self.open_chart)
        tools.addWidget(chart_button)
        if side == "INVENTORY":  # R248: اتصال به نقشهٔ انبار
            map_button = QPushButton("نمایش روی نقشه")
            map_button.setObjectName("flatButton")
            map_button.clicked.connect(lambda: self.show_on_map(self.table.currentRow()))
            tools.addWidget(map_button)
        tools.addSpacing(24)
        tools.addWidget(QLabel("نمایِ ذخیره‌شده:"))
        self.view_combo = QComboBox()
        self.view_combo.setMinimumWidth(180)
        self.view_combo.activated.connect(lambda _i: self.load_view(self.view_combo.currentData()))
        tools.addWidget(self.view_combo)
        self.shared_check = QCheckBox("اشتراکی")
        self.shared_check.setToolTip("نما برایِ همهٔ کاربرانِ شرکت هم نمایش داده شود")
        tools.addWidget(self.shared_check)
        save_view = QPushButton("ذخیرهٔ نما")
        save_view.setObjectName("flatButton")
        save_view.clicked.connect(self._on_save_view)
        tools.addWidget(save_view)
        delete_view = QPushButton("حذفِ نما")
        delete_view.setObjectName("flatButton")
        delete_view.clicked.connect(lambda: self.delete_view(self.view_combo.currentData()))
        tools.addWidget(delete_view)
        tools.addStretch(1)
        if self._def.options:
            self.layout().insertLayout(self.layout().indexOf(self.table), self.options_row)
        self.layout().insertLayout(self.layout().indexOf(self.table), tools)

        # R247: صفحه‌بندیِ نمایش (چاپ/خروجی همیشه همهٔ ردیف‌ها را دارد)
        self._page, self._page_offset, self._page_total = 0, 0, -1
        self._generation, self._workers = 0, []
        pager = QHBoxLayout()
        self.busy_label = QLabel("")
        self.busy_label.setObjectName("sectionHint")
        pager.addWidget(self.busy_label)
        pager.addStretch(1)
        pager.addWidget(QLabel("ردیف در صفحه:"))
        self.page_size_combo = QComboBox()
        for size, text in PAGE_SIZES:
            self.page_size_combo.addItem(text, size)
        self.page_size_combo.currentIndexChanged.connect(lambda _i: self._go_page(0))
        pager.addWidget(self.page_size_combo)
        self.prev_page_button = QPushButton("‹ قبلی")
        self.prev_page_button.setObjectName("flatButton")
        self.prev_page_button.clicked.connect(lambda: self._go_page(self._page - 1))
        self.page_label = QLabel("")
        self.next_page_button = QPushButton("بعدی ›")
        self.next_page_button.setObjectName("flatButton")
        self.next_page_button.clicked.connect(lambda: self._go_page(self._page + 1))
        for w in (self.prev_page_button, self.page_label, self.next_page_button):
            pager.addWidget(w)
        self.layout().insertLayout(self.layout().indexOf(self.table) + 1, pager)

        header = self.table.horizontalHeader()
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._on_header_clicked)
        self.table.cellDoubleClicked.connect(self._open_row)
        self.table.setToolTip("دابل‌کلیک: بازکردنِ سند یا ریزِ ردیفِ تجمیعی. کلیک رویِ سرِ ستون: مرتب‌سازی.")
        persist_column_widths(self.table, f"{side.lower() if side in ('ACCOUNTING', 'INVENTORY') else 'purchase' if side == 'PURCHASE' else 'sales'}"
                                          f"Report/{report_code}")
        self.add_field_help([
            (self.supplier_combo, "فقط اسنادِ همین طرفِ حساب. با تایپِ کد/نام جستجو کنید."),
            (self.item_combo, "فقط ردیف‌هایِ همین کالا."),
            (self.category_combo, "فقط کالاهایِ این گروه."),
            (self.warehouse_combo, "فقط ردیف‌هایِ این انبار."),
            (self.account_combo, "فقط این حساب و همهٔ زیرحساب‌هایش."),
            (self.detail_combo, "فقط ردیف‌هایی که این حسابِ تفصیلی را دارند."),
            (self.brand_combo, "فقط کالاهایِ این برند."),
            (self.branch_combo, "فقط انبارهایِ این شعبه."),
            (self.group_combo, "ردیف‌ها بر اساسِ این ستون گروه و برایِ هر گروه جمع زده می‌شوند."),
            (self.view_combo, "فیلترها، گزینه‌ها، مرتب‌سازی، گروه‌بندی و ستون‌هایِ پنهانِ ذخیره‌شده با یک نام."),
        ])

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is not None:
            self._decimal_places = companies_service.get_base_currency_decimal_places(company_id)
        if company_id is not None and self._side == "ACCOUNTING":
            from peecha.services import chart_of_accounts as coa_service

            _fill(self.account_combo, [(f"{a.full_code} — {a.name}", a.account_id) for a in coa_service.list_accounts(company_id)])
            _fill(self.detail_combo, [(f"{d.full_code or d.code} — {d.name or ''}", d.detail_account_id)
                                      for d in dimensions_service.list_all_detail_accounts(company_id)])
        elif company_id is not None:
            if self._side == "INVENTORY":
                from peecha.services import procurement_masters as masters_service

                _fill(self.brand_combo, [(f"{b.code} — {b.name}", b.brand_id) for b in catalog_service.list_brands(company_id)])
                _fill(self.branch_combo, [(f"{b.code} — {b.name}", b.branch_id) for b in masters_service.list_branches(company_id)])
            else:
                parties = dimensions_service.list_suppliers(company_id) if self._side == "PURCHASE" \
                    else dimensions_service.list_customers(company_id)
                _fill(self.supplier_combo, [(f"{s['code']} — {s['name'] or ''}", s["detail_account_id"]) for s in parties])
            _fill(self.item_combo, [(f"{i.code} — {i.name or ''}", i.item_id)
                                    for i in catalog_service.list_items(company_id, transactable_only=True)])
            _fill(self.category_combo, [(f"{c.code} — {c.name}", c.category_id) for c in catalog_service.list_categories(company_id)])
            _fill(self.warehouse_combo, [(f"{w.code} — {w.name}", w.warehouse_id) for w in locations_service.list_warehouses(company_id)])
        super().refresh()
        self._reload_views()

    def apply_preset(self, date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                     options: dict | None = None, **filters) -> None:
        """بازشدن از داشبورد/Drill-down با فیلترهایِ ازپیش‌تعیین‌شده (پس از refresh)."""
        if date_from is not None:
            self.date_from.setDate(date_from)
        if date_to is not None:
            self.date_to.setDate(date_to)
        for key in self._def.filters:
            combo = self._filter_widgets[key][1]
            combo.setCurrentIndex(max(0, combo.findData(filters.get(f"{key}_id"))))
        for key, (_label, combo) in self._option_combos.items():
            combo.blockSignals(True)
            wanted = (options or {}).get(key)
            combo.setCurrentIndex(max(0, combo.findData(wanted)) if wanted is not None else 0)
            combo.blockSignals(False)
        self._reload()

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
            account_id=value("account"), detail_account_id=value("detail"),
            brand_id=value("brand"), branch_id=value("branch"),
            options={key: combo.currentData() for key, (_label, combo) in self._option_combos.items()},
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

    # --- ساختِ جدول: مرتب‌سازی و گروه‌بندی رویِ دادهٔ خام ---------------
    def load_report(self, company_id: int, date_from: datetime.date, date_to: datetime.date):
        try:
            result = reports_service.run_report(company_id, self._def.code, self._filters(date_from, date_to))
        except ValueError as exc:
            return self._apply_result(None, exc)
        return self._apply_result(result, None)

    def _apply_result(self, result, error):
        self._page = 0
        if error is not None:
            # خطایِ غیرمنتظرهٔ اجرایِ پس‌زمینه هم فقط نمایش داده می‌شود (raise در slot برنامه را می‌بست)
            self.hint_label.setText(f"{self._def.hint}\n⚠ {error}")
            self._result = None
            return [], [], None
        self.hint_label.setText(f"{self._def.hint}\n{result.note}" if result.note else self._def.hint)
        columns_changed = self._result is None or self._result.columns != result.columns
        self._result = result
        if columns_changed:
            first_load = self.group_combo.count() <= 1
            self._reload_group_options()
            if first_load and self._def.default_group:
                self.group_combo.blockSignals(True)
                self.group_combo.setCurrentIndex(max(0, self.group_combo.findText(self._def.default_group)))
                self.group_combo.blockSignals(False)
        return self._compose()

    def _reload_group_options(self) -> None:
        current = self.group_combo.currentData()
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItem("— بدونِ گروه‌بندی —", None)
        for i, (header, kind) in enumerate(self._result.columns if self._result else []):
            if kind in _LABEL_KINDS:
                self.group_combo.addItem(header, i)
        self.group_combo.setCurrentIndex(max(0, self.group_combo.findData(current)))
        self.group_combo.blockSignals(False)

    def _compose(self):
        result = self._result
        kinds = [kind for _header, kind in result.columns]
        refs = list(result.refs) + [None] * (len(result.rows) - len(result.refs))
        order = list(range(len(result.rows)))
        if self._sort_col is not None and self._sort_col < len(kinds):
            order.sort(key=lambda i: _sort_key(result.rows[i][self._sort_col]), reverse=self._sort_desc)
        group_col = self.group_combo.currentData()
        rows, ids, bold, raw_index = [], [], [], []

        def emit(i: int) -> None:
            rows.append([self._fmt(v, kinds[c]) for c, v in enumerate(result.rows[i])])
            ids.append(refs[i])
            bold.append(False)
            raw_index.append(i)

        if group_col is None:
            for i in order:
                emit(i)
        else:
            summable = [c for c, k in enumerate(kinds) if k in reports_service._SUMMABLE and c not in result.no_total]
            groups: dict[str, set[int]] = {}
            for i in sorted(order, key=lambda i: _sort_key(result.rows[i][group_col])):
                groups.setdefault(self._fmt(result.rows[i][group_col], kinds[group_col]) or "—", set()).add(i)
            for label, member_set in groups.items():
                members = [i for i in order if i in member_set]
                for i in members:
                    emit(i)
                subtotal = [""] * len(kinds)
                for c in summable:
                    subtotal[c] = self._fmt(sum((result.rows[i][c] or 0 for i in members), decimal.Decimal(0)), kinds[c])
                subtotal[0] = f"جمعِ {label} ({numerals.to_persian_digits(str(len(members)))})"
                rows.append(subtotal)
                ids.append(None)
                bold.append(True)
                raw_index.append(None)
        footer = result.footer()
        if footer is not None:
            footer = [footer[0]] + [self._fmt(v, kinds[i]) if v != "" else "" for i, v in enumerate(footer) if i > 0]
        self._all_row_ids, self._all_row_bold = ids, bold
        self._row_raw = {id(r): i for r, i in zip(rows, raw_index)}
        return [h for h, _k in result.columns], rows, footer

    def _rebuild(self) -> None:
        if self._result is None:
            return
        self._headers, self._all_rows, self._footer = self._compose()
        self._apply_search_filter()
        self._show_sort_indicator()

    def _reload(self) -> None:
        company_id = self._company_id()
        if not BACKGROUND_REPORTS or company_id is None:
            super()._reload()
            self._show_sort_indicator()
            return
        # R247: نسلِ تازه؛ نتیجهٔ اجرایِ قبلی که دیرتر برسد نادیده گرفته می‌شود
        self._generation += 1
        filters = self._filters(self.date_from.date(), self.date_to.date())
        worker = ReportWorker(self._generation, reports_service.run_report, company_id, self._def.code, filters)
        worker.done.connect(self._on_worker_done)
        worker.finished.connect(lambda w=worker: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(worker)
        self.busy_label.setText("در حالِ محاسبهٔ گزارش…")
        worker.start()

    def wait_for_report(self, timeout_ms: int = 60000) -> None:
        """برایِ تست/اسکریپت: صبر تا پایانِ اجرایِ پس‌زمینه و اعمالِ نتیجه."""
        from PySide6.QtCore import QCoreApplication

        for worker in list(self._workers):
            worker.wait(timeout_ms)
        QCoreApplication.processEvents()

    def _on_worker_done(self, generation: int, result, error) -> None:
        if generation != self._generation:
            return
        self.busy_label.setText("")
        self._all_row_ids, self._all_row_bold = [], []
        try:
            self._headers, self._all_rows, self._footer = self._apply_result(result, error)
        except Exception as exc:  # noqa: BLE001
            self.hint_label.setText(f"{self._def.hint}\n⚠ خطا در اجرایِ گزارش: {exc}")
            self._result = None
            self._headers, self._all_rows, self._footer = [], [], None
        self._apply_search_filter()
        self._show_sort_indicator()

    # --- R247: صفحه‌بندی -------------------------------------------------
    def _page_size(self) -> int:
        return self.page_size_combo.currentData() or 0

    def _go_page(self, page: int) -> None:
        self._page = page
        self._set_table(self._headers, self._rows, self._footer)

    def _set_table(self, headers: list[str], rows: list[list], footer: list | None) -> None:
        total, size = len(rows), self._page_size()
        if total != self._page_total:
            self._page_total = total
            self._page = 0
        pages = max(1, -(-total // size)) if size else 1
        self._page = max(0, min(self._page, pages - 1))
        start = self._page * size if size else 0
        shown = rows[start:start + size] if size else rows
        saved_bold = self._row_bold
        if len(saved_bold) == total:
            self._row_bold = saved_bold[start:start + len(shown)]
        self._page_offset = start
        try:
            super()._set_table(headers, shown, footer)
        finally:
            self._row_bold = saved_bold
        self.page_label.setText(numerals.to_persian_digits(
            f"ردیفِ {start + 1 if total else 0}–{start + len(shown)} از {total}" + (f" (صفحهٔ {self._page + 1}/{pages})" if pages > 1 else "")))
        self.prev_page_button.setEnabled(self._page > 0)
        self.next_page_button.setEnabled(self._page < pages - 1)

    def _show_sort_indicator(self) -> None:
        header = self.table.horizontalHeader()
        header.setSortIndicatorShown(self._sort_col is not None)
        if self._sort_col is not None:
            header.setSortIndicator(self._sort_col, Qt.DescendingOrder if self._sort_desc else Qt.AscendingOrder)

    def _on_header_clicked(self, column: int) -> None:
        if self._sort_col == column:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col, self._sort_desc = column, False
        self._rebuild()

    def sort_by(self, column: int | None, descending: bool = False) -> None:
        self._sort_col, self._sort_desc = column, descending
        self._rebuild()

    # --- نمودار ---------------------------------------------------------
    def open_chart(self) -> ReportChartDialog | None:
        if self._result is None or not self._result.rows:
            return None
        dialog = ReportChartDialog(self, self._def.title, self._result)
        dialog.open()
        return dialog

    # --- نماهایِ ذخیره‌شده -- R244: در پایگاه‌داده، شخصی یا اشتراکی بینِ کاربرانِ شرکت ----------
    def _views_key(self) -> str:
        return f"{self._side}/{self._def.code}"

    def _view_rows(self) -> dict[str, object]:
        from peecha import session as app_session
        from peecha.services import report_views as views_service

        company_id = self._company_id()
        user = app_session.current_user
        if company_id is None or user is None:
            return {}
        users = None
        out = {}
        for v in views_service.list_views(company_id, self._views_key(), user.user_id):
            if v.is_mine:
                out[v.name] = v
            else:
                if users is None:
                    from peecha.services.purchase_reports_ext import _users

                    users = _users()
                out[f"{v.name} (اشتراکی: {users.get(v.owner_user_id, '')})"] = v
        return out

    def saved_views(self) -> dict[str, dict]:
        return {label: v.payload for label, v in self._view_rows().items()}

    def _reload_views(self) -> None:
        self.view_combo.clear()
        self.view_combo.addItem("— انتخاب —", None)
        for label, v in sorted(self._view_rows().items()):
            self.view_combo.addItem(label + (" ★" if v.is_mine and v.is_shared else ""), label)

    def current_view(self) -> dict:
        return {
            "filters": {key: self._filter_widgets[key][1].currentData() for key in self._def.filters},
            "options": {key: combo.currentData() for key, (_l, combo) in self._option_combos.items()},
            "sort": [self._sort_col, self._sort_desc],
            "group": self.group_combo.currentData(),
            "hidden": sorted(self.hidden_columns()),
        }

    def save_view(self, name: str, shared: bool | None = None) -> None:
        from peecha import session as app_session
        from peecha.services import report_views as views_service

        company_id = self._company_id()
        if company_id is None or app_session.current_user is None:
            return
        shared = self.shared_check.isChecked() if shared is None else shared
        views_service.save_view(company_id, self._views_key(), app_session.current_user.user_id, name, self.current_view(), shared)
        self._reload_views()
        self.view_combo.setCurrentIndex(self.view_combo.findData(name))

    def _on_save_view(self) -> None:
        name, ok = QInputDialog.getText(self, "ذخیرهٔ نما", "نامِ نما:")
        if ok and name.strip():
            self.save_view(name.strip())

    def delete_view(self, name: str | None) -> None:
        from peecha import session as app_session
        from peecha.services import report_views as views_service

        view = self._view_rows().get(name or "")
        if view is None:
            return
        if not view.is_mine:
            QMessageBox.information(self, "حذفِ نما", "نمایِ اشتراکیِ دیگران فقط توسطِ سازنده‌اش حذف می‌شود.")
            return
        views_service.delete_view(self._company_id(), view.view_id, app_session.current_user.user_id)
        self._reload_views()

    def load_view(self, name: str | None) -> None:
        view = self.saved_views().get(name or "")
        if not view:
            return
        for key, value in (view.get("filters") or {}).items():
            if key in self._filter_widgets:
                combo = self._filter_widgets[key][1]
                combo.setCurrentIndex(max(0, combo.findData(value)))
        for key, value in (view.get("options") or {}).items():
            if key in self._option_combos:
                combo = self._option_combos[key][1]
                combo.blockSignals(True)
                combo.setCurrentIndex(max(0, combo.findData(value)))
                combo.blockSignals(False)
        self._sort_col, self._sort_desc = (list(view.get("sort") or []) + [None, False])[:2]
        self.set_hidden_columns(set(view.get("hidden") or []))
        self._reload()
        self.group_combo.setCurrentIndex(max(0, self.group_combo.findData(view.get("group"))))

    def extra_filters_summary(self) -> list[tuple[str, str]]:
        parts = []
        for key in self._def.filters:
            label, widget = self._filter_widgets[key]
            if widget.currentData() is not None:
                parts.append((label.rstrip(":"), widget.currentText()))
        for label, combo in self._option_combos.values():
            parts.append((label, combo.currentText()))
        if self.group_combo.currentData() is not None:
            parts.append(("گروه‌بندی", self.group_combo.currentText()))
        return parts

    # --- دابل‌کلیک: سند، یا ریزِ ردیفِ تجمیعی -----------------------------
    def _open_row(self, row: int, _col: int) -> None:
        index = row + getattr(self, "_page_offset", 0)
        if self._main_window is None or not (0 <= index < len(self._row_ids)):
            return
        ref = self._row_ids[index]
        if ref:
            document_id, doc_type = ref
            if doc_type == "JOURNAL_ENTRY":
                self._main_window.open_screen("GL_JE", then=lambda screen: screen.edit_journal_entry(document_id))
                return
            if doc_type == "FA_ASSET":  # R265: صفحهٔ دارایی
                self._main_window.open_screen("FA_ASSETS", then=lambda screen: screen.open_asset(document_id))
                return
            if doc_type.startswith("STOCK:"):
                from peecha.ui.screens.inventory_documents_list import _TYPE_TO_NAV_CODE as _STOCK_NAV

                nav_code = _STOCK_NAV.get(doc_type.split(":", 1)[1])
                if nav_code:
                    self._main_window.open_screen(nav_code, then=lambda screen: screen.edit_document(document_id))
                return
            nav_code = _TYPE_TO_NAV_CODE.get(doc_type)
            if nav_code:
                self._main_window.open_screen(nav_code, then=lambda screen: screen.edit_document(document_id))
            return
        raw = self.raw_row(row)
        company_id = self._company_id()
        if raw is None or company_id is None:
            return
        if self._side == "ACCOUNTING":
            target = self._account_drill_target(raw)
        elif self._side == "INVENTORY":
            target = self.inventory_drill_target(raw)
        else:
            target = dashboard_service.drill_target(company_id, self._def.code, self._side, raw)
        if target is None:
            return
        code, filters = target
        prefix = _RPT_PREFIX[self._side]
        date_from = self.date_from.date() if self._def.date_mode == "range" else None
        date_to = self.date_to.date()
        self._main_window.open_screen(
            f"{prefix}{code}", then=lambda screen: screen.apply_preset(date_from, date_to, **filters))

    def _labels_in_row(self, raw: list) -> dict:
        found: dict = {}
        for cell in raw or []:
            if not isinstance(cell, str) or " — " not in cell:
                continue
            text = numerals.to_persian_digits(cell)
            for key, combo in (("item_id", self.item_combo), ("warehouse_id", self.warehouse_combo),
                               ("category_id", self.category_combo), ("brand_id", self.brand_combo)):
                index = combo.findText(text)
                if index > 0 and key not in found:
                    found[key] = combo.itemData(index)
                    break
        return found

    def _location_in_row(self, raw: list | None) -> int | None:
        import re

        from peecha.services import warehouse_locations as wl

        for cell in raw or []:
            if isinstance(cell, str) and re.fullmatch(r"[A-Za-z0-9]+(-[A-Za-z0-9]+)+", cell.strip()):
                try:
                    hit = wl.search(self._company_id(), cell.strip())
                except ValueError:
                    continue
                if hit.kind == "LOCATION" and len(hit.location_ids) == 1:
                    return hit.location_ids[0]
        return None

    def show_on_map(self, row: int) -> bool:
        """R248: کالایِ ردیف → محل‌هایش رویِ نقشه (هایلایت)؛ فقط انبار → نقشهٔ همان انبار."""
        if self._main_window is None:
            return False
        raw = self.raw_row(row) if row >= 0 else None
        location_id = self._location_in_row(raw)
        if location_id is not None:  # R252: ردیفِ دارایِ کدِ محل → همان محل رویِ نقشه
            self._main_window.open_screen("INV_WAREHOUSE_MAP", then=lambda screen: screen.focus_location(location_id))
            return True
        found = self._labels_in_row(raw)
        item_id, warehouse_id = found.get("item_id"), found.get("warehouse_id")
        if item_id is None and warehouse_id is None:
            self._main_window.open_screen("INV_WAREHOUSE_MAP")
            return True

        def focus(screen):
            if warehouse_id is not None:
                screen.load_warehouse(warehouse_id)
            if item_id is not None:
                screen.focus_item(item_id)
        self._main_window.open_screen("INV_WAREHOUSE_MAP", then=focus)
        return True

    def inventory_drill_target(self, raw: list) -> tuple[str, dict] | None:
        """ردیفِ تجمیعیِ گزارشِ انبار: کالا (و انبارِ همان ردیف) → کارتکس؛ فقط انبار/گروه → موجودیِ لحظه‌ای با همان فیلتر."""
        found: dict = {}
        for cell in raw:
            if not isinstance(cell, str) or " — " not in cell:
                continue
            text = numerals.to_persian_digits(cell)
            for key, combo in (("item_id", self.item_combo), ("warehouse_id", self.warehouse_combo),
                               ("category_id", self.category_combo), ("brand_id", self.brand_combo)):
                index = combo.findText(text)
                if index > 0 and key not in found:
                    found[key] = combo.itemData(index)
                    break
        if "item_id" in found and self._def.code != "STOCK_CARD":
            return "STOCK_CARD", {k: v for k, v in found.items() if k in ("item_id", "warehouse_id")}
        if found and self._def.code != "STOCK_ON_HAND":
            return "STOCK_ON_HAND", found
        return None

    def _account_drill_target(self, raw: list) -> tuple[str, dict] | None:
        """ردیفِ تجمیعیِ گزارشِ حسابداری: اولین برچسبِ حساب → گردش و ماندهٔ ماهانهٔ همان حساب."""
        for cell in raw:
            if isinstance(cell, str) and " — " in cell:
                index = self.account_combo.findText(numerals.to_persian_digits(cell))
                if index > 0:
                    return "MONTHLY_BALANCE", {"account_id": self.account_combo.itemData(index)}
        return None

    def raw_row(self, display_row: int) -> list | None:
        display_row += getattr(self, "_page_offset", 0)
        if self._result is None or not (0 <= display_row < len(self._rows)):
            return None
        index = self._row_raw.get(id(self._rows[display_row]))
        return self._result.rows[index] if index is not None else None
