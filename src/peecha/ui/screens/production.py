"""صفحه‌های تولید — R270.

«دستورهای تولید» صفحهٔ مرکزی است: فهرست + صفحهٔ هر دستور (پیشرفت، مواد، عملیات، هزینه‌ها، خروجی‌ها، تراکنش‌ها،
انحراف‌ها) و دکمه‌های عملیات (شروع، ثبت مصرف، ثبت تولید، ضایعات، توقف، اتمام، بستن). کاربر ساده با ویزارد
۱۰ مرحله‌ای تولید می‌کند. اطلاعات پایه (فهرست مواد، مسیر، مرکز کاری)، برنامه‌ریزی/MRP، بها و تنظیمات صفحه‌های جدا دارند.
همهٔ منطق در services/production است؛ این‌جا فقط نمایش و فراخوانی.
"""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar,
    QPushButton, QSplitter, QStackedWidget, QTableWidget, QTabWidget, QVBoxLayout, QWidget,
)

from peecha import decimals, numerals
from peecha.services.production import common as pc
from peecha.services.production import costing as pcost
from peecha.services.production import dashboard as pdash
from peecha.services.production import master as pm
from peecha.services.production import orders as po
from peecha.services.production import planning as pp
from peecha.ui import theme
from peecha.ui.screens import module_style as ms
from peecha.ui.screens.costing import can
from peecha.ui.screens.fixed_assets import (
    FormDialog, P, combo, scrolled, company_id, date_field, dec, fill, money, num_field, qty_field, qty_precision_problem,
    set_combo, table, user_id,
)
from peecha.ui.screens.purchase_dashboards import _ClickableKpiCard, _ProcurementDashboardBase, format_kpi
from peecha.ui.widgets import FormDrawer, confirm_and_delete
from peecha.db.models import production as prm

ZERO = decimal.Decimal(0)
AVAIL_ICON = {"GREEN": "● موجود", "YELLOW": "◐ بخشی موجود", "RED": "○ کمبود"}
OP_ICON = {"DONE": "✓", "IN_PROGRESS": "●", "PENDING": "○", "SKIPPED": "–"}


def qty(value, item_id: int | None = None, uom_id: int | None = None) -> str:
    """مقدار با اعشار واحد کالا (R280)؛ بدون کالا، بدون صفرهای اضافه."""
    return decimals.format_qty(value, uom_id=uom_id, item_id=item_id) if value is not None else "—"


class PrdLookups:
    def __init__(self, cid: int) -> None:
        from peecha.services import detail_dimensions as dims
        from peecha.services import hr as hr_service
        from peecha.services import inventory_catalog as catalog
        from peecha.services import inventory_locations as locations
        from peecha.services import procurement_masters as masters

        items = catalog.list_items(cid, active_only=True, transactable_only=True)
        self.items = [(f"{i.code} — {i.name or ''}", i.item_id) for i in items]
        self.made = [(f"{i.code} — {i.name or ''}", i.item_id) for i in items
                     if i.item_kind_code in ("FINISHED_GOOD", "SEMI_FINISHED", "GOOD")]
        self.uoms = {i.item_id: i.base_uom_id for i in items}
        self.warehouses = [(f"{w.code} — {w.name}", w.warehouse_id) for w in locations.list_warehouses(cid, active_only=True)]
        cc_type = dims.get_specialized_dimension_type_id(cid, dims.COST_CENTER_CODE)
        self.cost_centers = [(f"{d.code} — {d.name or ''}", d.detail_account_id) for d in dims.list_detail_accounts(cid, cc_type)]
        self.branches = [(b.name, b.branch_id) for b in masters.list_branches(cid)]
        self.employees = [(f"{e.employee_code} — {e.full_name}", e.employee_id) for e in hr_service.list_employees(cid)]
        self.work_centers = [(f"{w.code} — {w.name}", w.work_center_id) for w in pm.list_work_centers(cid, active_only=True)]


def _ask(parent, title: str, fields, hint: str = "") -> dict | None:
    dlg = FormDialog(title, fields, hint, parent)
    if getattr(parent, "dialog_runner", None):
        return dlg.values() if parent.dialog_runner(dlg) else None
    return dlg.values() if dlg.exec() == QDialog.Accepted else None


def selected_or_none(t: QTableWidget):
    row = t.currentRow()
    item = t.item(row, 0) if row >= 0 else None
    return item.data(Qt.UserRole) if item is not None and t.selectedItems() else None


def _checked(value: bool) -> QCheckBox:
    box = QCheckBox()
    box.setChecked(bool(value))
    return box


def _combo_at(box: QComboBox, value) -> QComboBox:
    """R276: فهرست فرم ویرایش روی مقدار فعلی ردیف."""
    set_combo(box, value)
    return box


def _run(parent, title: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs), True
    except ValueError as exc:
        QMessageBox.warning(parent, title, str(exc))
        return None, False


# =========================================================================================================
class PrdDashboard(_ProcurementDashboardBase):
    TITLE = "داشبورد تولید"
    _KPI_STYLE = {"ORDERS": ("🏭", "ACCENT"), "IN_PROGRESS": ("⚙", "CHART_TEAL"), "COMPLETED": ("✔", "SUCCESS"),
                  "DELAYED": ("⏱", "WARNING"), "SHORTAGE": ("⚠", "DANGER"), "QTY": ("📦", "ACCENT"), "VALUE": ("💰", "CHART_TEAL"),
                  "ACTUAL": ("🧮", "CHART_ORANGE"), "STANDARD": ("📐", "CHART_PURPLE"), "VARIANCE": ("±", "WARNING"),
                  "SCRAP": ("♻", "DANGER"), "MAT_EFF": ("🧪", "SUCCESS"), "LAB_EFF": ("👷", "SUCCESS")}

    def __init__(self, main_window=None) -> None:
        super().__init__(main_window)
        from peecha.ui.screens.dashboard import build_chart_card

        self.date_from.setDate(datetime.date.today().replace(day=1))
        self.cards, self._kpis = {}, {}
        grid = QGridLayout()
        grid.setSpacing(14)
        for i, (code, (icon, color)) in enumerate(self._KPI_STYLE.items()):
            card = _ClickableKpiCard("", icon, getattr(theme, color), lambda c=code: self._open_kpi(c))
            self.cards[code] = card
            grid.addWidget(card, i // 5, i % 5)
        self.body_layout.addLayout(grid)
        title = QLabel("هشدارها")
        title.setObjectName("cardTitle")
        self.body_layout.addWidget(title)
        self.alerts_table = table(["سطح", "هشدار", "دستور"])
        self.alerts_table.setMaximumHeight(200)
        self.alerts_table.cellDoubleClicked.connect(self._open_alert)
        self.body_layout.addWidget(self.alerts_table)
        charts = QGridLayout()
        self.chart_views = {}
        for i, (key, chart_title, report_code, options) in enumerate(pdash.CHART_TITLES):
            card, view = build_chart_card(chart_title)
            view.setMinimumHeight(240)
            link = QPushButton("گزارش ←")
            link.setObjectName("flatButton")
            link.clicked.connect(lambda _c=False, r=report_code, o=options: self.open_report(r, o))
            card.layout().addWidget(link, alignment=Qt.AlignLeft)
            self.chart_views[key] = view
            charts.addWidget(card, i // 2, i % 2)
        self.body_layout.addLayout(charts)
        self._alerts = []

    def open_report(self, report_code: str, options: dict | None = None) -> None:
        if self._main_window is None:
            return
        date_from, date_to = self.date_from.date(), self.date_to.date()
        self._main_window.open_screen(f"INV_RPT_{report_code}", then=lambda s: s.apply_preset(date_from, date_to, options or {}))

    def _open_kpi(self, code: str) -> None:
        kpi = self._kpis.get(code)
        if kpi is not None:
            self.open_report(kpi.report_code, kpi.options)

    def _open_alert(self, row: int, _col: int) -> None:
        if self._main_window is not None and row < len(self._alerts):
            oid = self._alerts[row].order_id
            self._main_window.open_screen("PRD_ORDERS", then=lambda s: s.open_order(oid))

    def reload(self) -> None:
        from peecha.ui.screens.dashboard import render_donut_chart
        from peecha.ui.screens.warehouse_dashboard import render_series_chart

        cid = company_id()
        if cid is None:
            return
        kpis, charts, _rows, alerts = pdash.dashboard(cid, self.date_from.date(), self.date_to.date())
        self._kpis = {k.code: k for k in kpis}
        show_cost = can("prd_cost_view", "VIEW")
        for code, kpi in self._kpis.items():
            card = self.cards[code]
            card._title_label.setText(kpi.title)
            card.set_value("—" if kpi.kind == "MONEY" and not show_cost else format_kpi(kpi.value, kpi.kind, decimals.money_decimals()))
            card.setToolTip(f"فرمول: {kpi.formula}\nکلیک: گزارش مبدا")
        self._alerts = alerts
        level = {"RED": "🔴", "YELLOW": "🟡", "ORANGE": "🟠"}
        fill(self.alerts_table, [[level[pdash.ALERT_LEVEL[a.kind]] + " " + pdash.ALERT_LABELS[a.kind], a.text, a.order_code]
                                 for a in alerts])
        for key, data in charts.items():
            if key in ("elements", "variance") and not show_cost:
                continue
            if data["kind"] == "donut":
                render_donut_chart(self.chart_views[key], [(P(lb), v) for lb, v in zip(data["labels"], data["series"]["تعداد"]) if v])
            else:
                render_series_chart(self.chart_views[key], data["labels"], data["series"])


# =========================================================================================================
class ProductionWizard(QDialog):
    """«می‌خواهم ۵۰۰ عدد محصول A تولید کنم» در ۱۰ مرحله؛ هر مرحله همان سرویس دستور تولید را صدا می‌زند."""

    STEPS = ("انتخاب محصول", "انتخاب فهرست مواد", "تعداد تولید", "بررسی مواد", "رزرو مواد", "شروع تولید", "ثبت مصرف",
             "ثبت تولید", "محاسبهٔ بهای تمام‌شده", "بستن دستور")

    def __init__(self, lookups: PrdLookups, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ویزارد تولید")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(720, 520)
        self.lk = lookups
        self.order_id: int | None = None
        outer = QVBoxLayout(self)
        self.step_label = QLabel("")
        self.step_label.setObjectName("pageTitle")
        outer.addWidget(self.step_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, len(self.STEPS))
        outer.addWidget(self.progress)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, stretch=1)
        self.item_box = combo(lookups.made)
        self.item_box.currentIndexChanged.connect(self._item_changed)
        self._page("کالای تولیدی را انتخاب کنید (نوشتن بخشی از نام کافی است).", [("محصول", self.item_box)])
        self.bom_box = QComboBox()
        self._page("نسخهٔ معتبر فهرست مواد پیش‌فرض انتخاب شده است.", [("فهرست مواد", self.bom_box)])
        self.qty_edit = qty_field(100, item_combo=self.item_box)
        self.due_edit = date_field()
        self._page("مقدار و تاریخ تحویل.", [("مقدار تولید", self.qty_edit), ("تاریخ پایان", self.due_edit)])
        self.avail_table = table(["ماده", "نیاز", "موجود", "کمبود", "وضعیت"])
        self._page_widget("موجودی مواد (🟢 موجود، 🟡 بخشی، 🔴 کمبود). در این مرحله دستور ساخته و صادر می‌شود.", self.avail_table)
        self.reserve_label = QLabel("")
        self._page_widget("رزرو مواد از انبار برای این دستور.", self.reserve_label)
        self.start_label = QLabel("با «بعدی» تولید شروع می‌شود.")
        self._page_widget("شروع تولید.", self.start_label)
        self.consume_table = table(["ماده", "نیاز", "مصرف واقعی"])
        self._page_widget("مصرف واقعی (پیش‌فرض = استاندارد؛ می‌توانید مقدار را تغییر دهید).", self.consume_table)
        self.consume_table.setEditTriggers(QTableWidget.AllEditTriggers)
        self.produced_edit = qty_field(item_combo=self.item_box)
        self.scrap_edit = qty_field(0, item_combo=self.item_box)
        self._page("مقدار تولید سالم و ضایعات.", [("تولید سالم", self.produced_edit), ("ضایعات", self.scrap_edit)])
        self.cost_label = QLabel("")
        self.cost_label.setWordWrap(True)
        self._page_widget("بهای تمام‌شده (واقعی در برابر استاندارد).", self.cost_label)
        self.close_label = QLabel("")
        self.close_label.setWordWrap(True)
        self._page_widget("کنترل‌های پیش از بستن.", self.close_label)
        nav = QHBoxLayout()
        self.next_button = QPushButton("بعدی")
        self.next_button.setObjectName("primaryButton")
        self.next_button.clicked.connect(self.next)
        close = QPushButton("بستن ویزارد")
        close.clicked.connect(self.reject)
        nav.addWidget(close)
        nav.addStretch(1)
        nav.addWidget(self.next_button)
        outer.addLayout(nav)
        self._item_changed()
        self.go(0)

    def _page(self, hint: str, rows) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel(hint)
        note.setObjectName("sectionHint")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        for label, w in rows:
            form.addRow(label, w)
        layout.addLayout(form)
        layout.addStretch(1)
        self.stack.addWidget(scrolled(page))

    def _page_widget(self, hint: str, widget: QWidget) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel(hint)
        note.setObjectName("sectionHint")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(widget, stretch=1)
        self.stack.addWidget(page)

    def _item_changed(self) -> None:
        self.bom_box.clear()
        item_id = self.item_box.currentData()
        if item_id is None:
            return
        cid = company_id()
        default = pm.get_effective_bom_id(cid, item_id)
        for v in pm.list_bom_versions(cid, item_id):
            if v.status_code == "ACTIVE":
                self.bom_box.addItem(P(f"{v.code} {v.name or ''}" + (" (پیش‌فرض)" if v.is_default else "")), v.bom_id)
        set_combo(self.bom_box, default)

    def go(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.progress.setValue(index + 1)
        self.step_label.setText(P(f"مرحلهٔ {index + 1} از ۱۰ -- {self.STEPS[index]}"))
        self.next_button.setText("پایان" if index == 9 else "بعدی")

    def next(self) -> bool:
        cid, uid = company_id(), user_id()
        i = self.stack.currentIndex()
        try:
            if i == 0 and self.item_box.currentData() is None:
                raise ValueError("محصول را انتخاب کنید.")
            if i == 1 and self.bom_box.currentData() is None:
                raise ValueError("برای این محصول فهرست مواد فعالی تعریف نشده است — از «اطلاعات پایهٔ تولید» یک فهرست مواد بسازید.")
            for w, label, step in ((self.qty_edit, "مقدار تولید", 2), (self.produced_edit, "تولید سالم", 7),
                                   (self.scrap_edit, "ضایعات", 7)):
                problem = qty_precision_problem(w, label) if i == step else None
                if problem:
                    raise ValueError(problem)
            if i == 2:
                rows = po.availability(cid, item_id=self.item_box.currentData(), quantity=dec(self.qty_edit.text()),
                                       bom_id=self.bom_box.currentData())
                fill(self.avail_table, [[a.item_label, qty(a.required, a.item_id), qty(a.available, a.item_id), qty(a.shortage, a.item_id), AVAIL_ICON[a.status]]
                                        for a in rows])
            if i == 3:
                if self.order_id is None:
                    self.order_id = po.create_order(cid, uid, po.OrderFields(
                        item_id=self.item_box.currentData(), planned_qty=dec(self.qty_edit.text()), bom_id=self.bom_box.currentData(),
                        due_date=max(self.due_edit.date(), datetime.date.today())))
                    po.release_order(cid, uid, self.order_id, reserve=False)
                self.reserve_label.setText(P("دستور " + po.get_order(cid, self.order_id).order_code + " صادر شد."))
            if i == 4:
                n = po.reserve_materials(cid, uid, self.order_id)
                self.reserve_label.setText(P(f"{qty(n)} واحد مواد رزرو شد."))
            if i == 5:
                po.start_order(cid, uid, self.order_id)
                view = po.order_view(cid, self.order_id)
                fill(self.consume_table, [[m.item_label, qty(m.required, m.item_id), qty(m.remaining, m.item_id)]
                                          for m in view.materials if not m.is_optional],
                     [m.material_id for m in view.materials if not m.is_optional])
                self._consume_items = [m.item_id for m in view.materials if not m.is_optional]
                self.produced_edit.setText(decimals.plain(po.get_order(cid, self.order_id).planned_qty))
                self.produced_edit.setProperty("qty_dp", decimals.qty_decimals(item_id=self.item_box.currentData()))
            if i == 6:
                lines = []
                for r in range(self.consume_table.rowCount()):
                    cell = QLineEdit(self.consume_table.item(r, 2).text())
                    problem = qty_precision_problem(cell, self.consume_table.item(r, 0).text(),
                                                    decimals.qty_decimals(item_id=self._consume_items[r]))
                    if problem:
                        raise ValueError(problem)
                    q = dec(cell.text())
                    if q > 0:
                        lines.append(po.IssueLine(self.consume_table.item(r, 0).data(Qt.UserRole), q))
                if lines:
                    po.issue_materials(cid, uid, self.order_id, lines, idempotency_key=f"wiz-{self.order_id}-issue")
            if i == 7:
                scrap = dec(self.scrap_edit.text())
                if scrap > 0:
                    po.report_scrap(cid, uid, self.order_id, scrap, "ثبت در ویزارد", idempotency_key=f"wiz-{self.order_id}-scrap")
                po.complete_order(cid, uid, self.order_id, po.ReceiptInput(dec(self.produced_edit.text())),
                                  idempotency_key=f"wiz-{self.order_id}-complete")
                k = pcost.get_order_costs(cid, self.order_id)
                self.cost_label.setText(P("\n".join([
                    f"مواد: {money(k.material)}", f"دستمزد: {money(k.labor)}", f"ماشین: {money(k.machine)}",
                    f"سربار: {money(k.overhead)}", f"کسر جانبی/بازیافت: {money(k.byproduct_credit + k.scrap_recovery)}",
                    f"بهای کل: {money(k.total)}", f"بهای واحد واقعی: {money(k.actual_unit_cost)}",
                    f"بهای واحد استاندارد: {money(k.standard_unit_cost)}", f"انحراف: {money(k.variance)}"])))
            if i == 8:
                checks = po.closing_checklist(cid, self.order_id)
                self.close_label.setText(P("\n".join(("✓ " if x.ok else "✗ ") + x.label + (f" ({x.note})" if x.note else "")
                                                     for x in checks)))
            if i == 9:
                po.close_order(cid, uid, self.order_id)
                self.accept()
                return True
        except ValueError as exc:
            QMessageBox.warning(self, "ویزارد تولید", str(exc))
            return False
        self.go(i + 1)
        return True


# =========================================================================================================
@ms.styled
class OrdersScreen(QWidget):
    """صفحهٔ مرکزی دستور تولید."""

    scroll_in_mdi = True

    FORM = "prd_orders"
    ACTIONS = (("release", "صدور", "prd_release"), ("start", "شروع تولید", "prd_consume"), ("issue", "ثبت مصرف", "prd_consume"),
               ("issue_all", "مصرف کامل استاندارد", "prd_consume"), ("return", "برگشت مواد", "prd_consume"),
               ("receipt", "ثبت تولید", "prd_complete"), ("scrap", "ثبت ضایعات", "prd_consume"),
               ("labor", "ثبت دستمزد", "prd_consume"), ("machine", "ثبت ساعت ماشین", "prd_consume"),
               ("hold", "توقف", "prd_orders"), ("resume", "ادامه", "prd_orders"), ("complete", "اتمام تولید", "prd_complete"),
               ("close", "بستن دستور", "prd_close"), ("reopen", "بازگشایی", "prd_cost_adjust"), ("cancel", "لغو", "prd_orders"),
               ("children", "دستور نیمه‌ساخته‌ها", "prd_orders"), ("reserve", "رزرو مواد", "prd_release"),
               ("reverse", "برگشت تولید", "prd_cost_adjust"))
    ALLOWED = {"release": ("DRAFT", "PLANNED"), "start": ("RELEASED",), "issue": ("RELEASED", "IN_PROGRESS"),
               "issue_all": ("RELEASED", "IN_PROGRESS"), "return": ("RELEASED", "IN_PROGRESS", "ON_HOLD", "COMPLETED"),
               "receipt": ("RELEASED", "IN_PROGRESS"), "scrap": ("RELEASED", "IN_PROGRESS"), "labor": ("RELEASED", "IN_PROGRESS", "COMPLETED"),
               "machine": ("RELEASED", "IN_PROGRESS", "COMPLETED"), "hold": ("RELEASED", "IN_PROGRESS"), "resume": ("ON_HOLD",),
               "complete": ("RELEASED", "IN_PROGRESS"), "close": ("COMPLETED",), "reopen": ("CLOSED",),
               "cancel": ("DRAFT", "PLANNED", "RELEASED", "IN_PROGRESS", "ON_HOLD"), "children": ("DRAFT", "PLANNED", "RELEASED"),
               "reserve": ("RELEASED", "IN_PROGRESS"), "reverse": ("IN_PROGRESS", "COMPLETED", "RELEASED")}

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.view = None
        self.lk: PrdLookups | None = None
        self.dialog_runner = None
        self.confirm = lambda text: QMessageBox.question(self, "دستور تولید", text) == QMessageBox.Yes
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("دستورهای تولید")
        title.setObjectName("pageTitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو: کد دستور یا محصول")
        self.search.returnPressed.connect(self.reload_list)
        self.status_filter = QComboBox()
        self.status_filter.addItem("— همه —", None)
        for code, label in po.STATUS_LABELS.items():
            self.status_filter.addItem(label, code)
        self.status_filter.currentIndexChanged.connect(self.reload_list)
        self.new_button = QPushButton("دستور جدید")
        self.new_button.clicked.connect(self.new_order)
        self.edit_button = QPushButton("ویرایش دستور")
        self.edit_button.clicked.connect(lambda: self.edit_order())
        self.delete_button = QPushButton("حذف دستور")
        self.delete_button.clicked.connect(lambda: self.delete_order())
        self.wizard_button = QPushButton("ویزارد تولید")
        self.wizard_button.setObjectName("primaryButton")
        self.wizard_button.clicked.connect(self.open_wizard)
        outer.addWidget(ms.header_card(title, self.search, self.status_filter, self.new_button, self.edit_button,
                                        self.delete_button, self.wizard_button))
        split = QSplitter(Qt.Horizontal)
        self.list_table = table(["دستور", "محصول", "وضعیت", "برنامه", "تولید", "پایان"])
        self.list_table.itemSelectionChanged.connect(self._selected)
        split.addWidget(self.list_table)
        detail = QWidget()
        dl = QVBoxLayout(detail)
        self.header = QLabel("")
        self.header.setObjectName("pageTitle")
        dl.addWidget(self.header)
        cards_box, self.cards = ms.summary([
            ("product", "محصول", "neutral", "🏷️"), ("status", "وضعیت", "info", "📌"), ("planned", "برنامه", "neutral", "🎯"),
            ("produced", "تولیدشده", "success", "✅"), ("scrapped", "ضایعات", "danger", "♻️"), ("dates", "شروع / پایان", "neutral", "📅"),
            ("wip", "کالای در جریان ساخت", "warning", "⏳"), ("unit", "بهای واحد", "info", "💵")])
        dl.addWidget(cards_box)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        dl.addWidget(self.progress)
        self.actions = {}
        for key, label, form in self.ACTIONS:
            b = QPushButton(label)
            b.setProperty("form", form)
            b.clicked.connect(lambda _c=False, k=key: self.action(k))
            self.actions[key] = b
        self.tabs = QTabWidget()
        self.t_materials = table(["ماده", "نوع", "نیاز", "رزرو", "مصرف‌شده", "مانده", "موجودی"])
        self.t_operations = table(["", "ترتیب", "عملیات", "مرکز کاری", "ساعت استاندارد", "ساعت واقعی", "انجام‌شده"])
        self.t_operations.cellDoubleClicked.connect(self._operation_clicked)
        self.t_costs = table(["عنصر", "واقعی", "استاندارد", "انحراف"])
        self.t_outputs = table(["کالا", "نوع", "برنامه", "تولید", "بها"])
        self.t_txns = table(["تاریخ", "عملیات", "کالا", "مقدار", "مبلغ", "اثر بر کالای در جریان ساخت", "علت"])
        self.t_txns.cellDoubleClicked.connect(self._txn_clicked)
        self.t_variances = table(["انحراف", "مبلغ", "مقدار"])
        self.t_checklist = table(["کنترل پیش از بستن", "وضعیت", "توضیح"])
        for w, label in ((self.t_materials, "مواد"), (self.t_operations, "عملیات"), (self.t_costs, "هزینه‌ها"),
                         (self.t_outputs, "خروجی‌ها"), (self.t_txns, "تراکنش‌ها"), (self.t_variances, "انحراف‌ها"),
                         (self.t_checklist, "بستن")):
            self.tabs.addTab(w, label)
        dl.addWidget(self.tabs, stretch=1)
        split.addWidget(detail)
        split.setSizes([380, 900])
        # R275: جزئیاتِ دستور کنارِ فهرست فقط با انتخابِ ردیف باز می‌شود؛ فهرست تمام‌عرض می‌ماند
        self.detail_drawer = FormDrawer(split, detail, open_signals=[self.list_table.clicked])
        outer.addWidget(split, stretch=1)
        A = self.actions
        outer.addWidget(ms.footer([
            [A["release"], A["reserve"], A["start"], A["hold"], A["resume"], A["cancel"]],
            [A["issue"], A["issue_all"], A["return"], A["scrap"]],
            [A["labor"], A["machine"]],
            [A["receipt"], A["reverse"], A["complete"], A["close"], A["reopen"]],
            [A["children"]]]))

    # --- بارگذاری ----------------------------------------------------------------------------
    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.lk = PrdLookups(cid)
        self.new_button.setEnabled(can(self.FORM, "CREATE"))
        self.wizard_button.setEnabled(can(self.FORM, "CREATE"))
        self.reload_list()

    def reload_list(self) -> None:
        cid = company_id()
        if cid is None:
            return
        rows = po.list_orders(cid, status=self.status_filter.currentData(), search=self.search.text().strip() or None)
        fill(self.list_table, [[r.order_code, r.item_label, ("⚠ " if r.is_late else "") + r.status_label, qty(r.planned_qty, r.item_id),
                                qty(r.produced_qty, r.item_id), r.due_date] for r in rows], [r.order_id for r in rows])
        if rows and (self.view is None or self.view.order.order_id not in {r.order_id for r in rows}):
            self.list_table.selectRow(0)

    def _selected(self) -> None:
        items = self.list_table.selectedItems()
        if items:
            self.load_order(self.list_table.item(items[0].row(), 0).data(Qt.UserRole))

    def open_order(self, order_id: int) -> None:
        self.status_filter.blockSignals(True)
        self.status_filter.setCurrentIndex(0)
        self.status_filter.blockSignals(False)
        self.search.clear()
        self.list_table.blockSignals(True)
        self.reload_list()
        for r in range(self.list_table.rowCount()):
            if self.list_table.item(r, 0).data(Qt.UserRole) == order_id:
                self.list_table.selectRow(r)
        self.list_table.blockSignals(False)
        self.load_order(order_id)
        self.detail_drawer.open()

    def load_order(self, order_id: int) -> None:
        cid = company_id()
        self.view = v = po.order_view(cid, order_id)
        o = v.order
        show_cost = can("prd_cost_view", "VIEW")
        self.header.setText(P(f"دستور تولید {o.order_code}"))
        values = {"product": o.item_label, "status": "● " + o.status_label + (f" ({o.hold_reason})" if o.hold_reason else ""),
                  "planned": qty(o.planned_qty, o.item_id), "produced": qty(o.produced_qty, o.item_id),
                  "scrapped": qty(o.scrapped_qty, o.item_id),
                  "dates": f"{numerals.format_jalali_date(o.start_date)} / {numerals.format_jalali_date(o.due_date)}",
                  "wip": money(v.wip) if show_cost else "—", "unit": money(v.costs.actual_unit_cost) if show_cost else "—"}
        for key, text in values.items():
            self.cards[key].setText(P(text))
        self.progress.setValue(int(o.progress))
        self.progress.setFormat(P(f"{int(o.progress)}٪"))
        fill(self.t_materials, [[m.item_label, pc.COMPONENT_TYPES.get(m.component_type, ""), qty(m.required, m.item_id),
                                 qty(m.reserved, m.item_id), qty(m.consumed, m.item_id), qty(m.remaining, m.item_id), AVAIL_ICON[m.availability]] for m in v.materials],
             [m.material_id for m in v.materials])
        fill(self.t_operations, [[OP_ICON[x.status_code], x.seq, x.name, x.work_center, qty(x.std_labor_hours), qty(x.actual_labor_hours),
                                  qty(x.completed_qty, o.item_id)] for x in v.operations], [x.order_operation_id for x in v.operations])
        k = v.costs
        if show_cost:
            fill(self.t_costs, [["مواد", k.material, k.material_std, k.material - k.material_std],
                                ["دستمزد", k.labor, k.labor_std, k.labor - k.labor_std],
                                ["ماشین", k.machine, k.machine_std, k.machine - k.machine_std],
                                ["سربار", k.overhead, k.overhead_std, k.overhead - k.overhead_std],
                                ["کسر جانبی/بازیافت/ضایعات غیرعادی", -(k.byproduct_credit + k.scrap_recovery + k.abnormal_scrap),
                                 -k.byproduct_std, ZERO],
                                ["بهای کل", k.total, k.std_total, k.total - k.std_total],
                                ["بهای واحد", k.actual_unit_cost, k.standard_unit_cost, k.actual_unit_cost - k.standard_unit_cost]])
            fill(self.t_variances, [[x.label, x.amount, qty(x.quantity) if x.quantity is not None else ""]
                                    for x in pcost.get_variances(cid, order_id)])
        else:
            fill(self.t_costs, [["مشاهدهٔ بها نیازمند دسترسی «تولید: مشاهدهٔ بها» است.", "", "", ""]])
            fill(self.t_variances, [])
        fill(self.t_outputs, [[x.item_label, pc.OUTPUT_TYPES[x.output_type], qty(x.planned_qty, x.item_id), qty(x.produced_qty, x.item_id),
                               x.produced_amount if show_cost else "—"] for x in v.outputs])
        fill(self.t_txns, [[t.date, t.label + (" (برگشت‌خورده)" if t.reversed else ""), t.item_label, qty(t.quantity, t.item_id),
                            t.amount if show_cost else "—", t.wip_delta if show_cost else "—", t.reason or ""] for t in v.transactions],
             [t.txn_id for t in v.transactions])
        fill(self.t_checklist, [[x.label, "✓" if x.ok else "✗", x.note] for x in po.closing_checklist(cid, order_id)])
        self._update_actions()

    def _update_actions(self) -> None:
        status = self.view.order.status_code if self.view else None
        open_order = status is not None and status not in ("COMPLETED", "CLOSED")
        self.edit_button.setEnabled(open_order and can(self.FORM, "EDIT"))
        self.delete_button.setEnabled(open_order and can(self.FORM, "DELETE"))
        for key, b in self.actions.items():
            b.setEnabled(status in self.ALLOWED[key] and can(b.property("form"), "EDIT" if b.property("form") == self.FORM else "VIEW"))

    def _operation_clicked(self, row: int, _col: int) -> None:
        op_id = self.t_operations.item(row, 0).data(Qt.UserRole)
        values = _ask(self, "وضعیت عملیات", [("status", "وضعیت", combo([("انجام‌شده", "DONE"), ("در حال انجام", "IN_PROGRESS"),
                                                                       ("رد شد", "SKIPPED"), ("در انتظار", "PENDING")]))])
        if values and _run(self, "عملیات", po.set_operation_status, company_id(), user_id(), op_id, values["status"])[1]:
            self.load_order(self.view.order.order_id)

    def _txn_clicked(self, row: int, _col: int) -> None:
        if self._main_window is None:
            return
        txn = self.view.transactions[row]
        if txn.journal_entry_id:
            self._main_window.open_screen("GL_JE", then=lambda s: s.edit_journal_entry(txn.journal_entry_id))

    # --- عملیات --------------------------------------------------------------------------------
    def new_order(self) -> None:
        values = _ask(self, "دستور تولید جدید", self._order_form(),
                      "فهرست مواد، مسیر و انبارها خودکار از تنظیمات و تعریف کالا پر می‌شوند.")
        if not values:
            return None
        values["priority"] = int(values["priority"] or 3)
        oid, ok = _run(self, "دستور تولید", po.create_order, company_id(), user_id(), po.OrderFields(**values))
        if ok:
            self.open_order(oid)
        return oid

    def _order_form(self, order=None) -> list:
        lk = self.lk
        item_box = _combo_at(combo(lk.made), order.item_id if order else None)
        g = (lambda name: getattr(order, name)) if order is not None else (lambda name: None)
        return [
            ("item_id", "محصول", item_box),
            ("planned_qty", "مقدار", qty_field(g("planned_qty"), item_combo=item_box)),
            ("start_date", "شروع", date_field(g("start_date"))), ("due_date", "پایان", date_field(g("due_date"))),
            ("priority", "اولویت (۱ تا ۵)", num_field(g("priority") or 3)),
            ("material_warehouse_id", "انبار مواد", _combo_at(combo(lk.warehouses, "— پیش‌فرض —"), g("material_warehouse_id"))),
            ("fg_warehouse_id", "انبار محصول", _combo_at(combo(lk.warehouses, "— پیش‌فرض —"), g("fg_warehouse_id"))),
            ("branch_id", "شعبه", _combo_at(combo(lk.branches, "—"), g("branch_id"))),
            ("cost_center_detail_account_id", "مرکز هزینه", _combo_at(combo(lk.cost_centers, "—"), g("cost_center_detail_account_id"))),
            ("notes", "توضیحات", QLineEdit(g("notes") or ""))]

    def edit_order(self, values: dict | None = None) -> bool:
        """R280: ویرایش دستور؛ دستور صادرشدهٔ بدون گردش اول به پیش‌نویس برمی‌گردد."""
        if self.view is None:
            return False
        cid, uid, oid = company_id(), user_id(), self.view.order.order_id
        order = po.get_order(cid, oid)
        if order.status_code not in po.EDITABLE_STATUSES:
            if not self.confirm("برای ویرایش، دستور به «پیش‌نویس» برمی‌گردد و رزرو مواد آزاد می‌شود (فقط اگر هنوز گردشی ندارد). "
                                "پس از ویرایش دوباره «صدور» بزنید. ادامه می‌دهید؟"):
                return False
            if not _run(self, "ویرایش دستور تولید", po.revert_to_draft, cid, uid, oid)[1]:
                return False
            order = po.get_order(cid, oid)
            self.reload_list()
            self.load_order(oid)
        if values is None:
            values = _ask(self, f"ویرایش دستور {order.order_code}", self._order_form(order))
            if values is None:
                return False
        values["priority"] = int(values.get("priority") or 3)
        same_item = values["item_id"] == order.item_id
        fields = po.OrderFields(**values, bom_id=order.bom_id if same_item else None, routing_id=order.routing_id if same_item else None,
                                wip_warehouse_id=order.wip_warehouse_id, scrap_warehouse_id=order.scrap_warehouse_id,
                                project_detail_account_id=order.project_detail_account_id, work_center_id=order.work_center_id if same_item else None,
                                responsible_user_id=order.responsible_user_id, sales_order_line_id=order.sales_order_line_id,
                                parent_order_id=order.parent_order_id, joint_cost_method=order.joint_cost_method)
        _r, ok = _run(self, "ویرایش دستور تولید", po.update_order, cid, uid, oid, fields)
        if ok:
            self.reload_list()
            self.load_order(oid)
        return ok

    def delete_order(self) -> bool:
        if self.view is None:
            return False
        o = self.view.order
        if not self.confirm(f"دستور تولید {o.order_code} حذف شود؟ (فقط دستوری که هیچ گردشی ندارد قابل حذف است.)"):
            return False
        _r, ok = _run(self, "حذف دستور تولید", po.delete_order, company_id(), user_id(), o.order_id)
        if ok:
            self.view = None
            self.reload_list()
            if self.view is None:
                for t in (self.t_materials, self.t_operations, self.t_outputs, self.t_txns, self.t_costs, self.t_variances, self.t_checklist):
                    fill(t, [])
                self.header.setText("")
                self._update_actions()
        return ok

    def open_wizard(self) -> None:
        wiz = ProductionWizard(self.lk or PrdLookups(company_id()), self)
        wiz.exec()
        self.reload_list()
        if wiz.order_id:
            self.open_order(wiz.order_id)

    def action(self, key: str, values: dict | None = None) -> bool:
        """values برای تست/اتوماسیون؛ بدون آن فرم مربوط نمایش داده می‌شود."""
        if self.view is None:
            return False
        cid, uid, oid = company_id(), user_id(), self.view.order.order_id
        mats = [(m.item_label, m.material_id) for m in self.view.materials]
        mat_items = {m.material_id: m.item_id for m in self.view.materials}
        product = self.view.order.item_id
        issue_box, return_box = combo(mats), combo(mats)
        ops = [(f"{x.seq} -- {x.name}", x.order_operation_id) for x in self.view.operations]
        forms = {
            "issue": [("material_id", "ماده", issue_box),
                      ("quantity", "مقدار مصرف", qty_field(item_combo=issue_box, item_of=mat_items.get)), ("reason", "توضیح", QLineEdit())],
            "return": [("material_id", "ماده", return_box),
                       ("quantity", "مقدار برگشت", qty_field(item_combo=return_box, item_of=mat_items.get)), ("reason", "علت", QLineEdit())],
            "receipt": [("quantity", "تولید سالم", qty_field(self.view.order.remaining_qty, item_id=product)),
                        ("batch_no", "شمارهٔ بچ (اختیاری)", QLineEdit())]
            + [(f"out_{o.item_id}", f"{pc.OUTPUT_TYPES[o.output_type]}: {o.item_label}", qty_field(0, item_id=o.item_id))
               for o in self.view.outputs if o.output_type != "MAIN"],
            "scrap": [("quantity", "مقدار ضایعات", qty_field(item_id=product)), ("reason", "علت", QLineEdit()),
                      ("scrap_item_id", "کالای ضایعات قابل فروش", combo(self.lk.items if self.lk else [], "— بدون بازیافت —")),
                      ("recovery", "ارزش بازیافت واحد", num_field(0))],
            "labor": [("order_operation_id", "عملیات", combo(ops, "—")), ("employee_id", "کارمند", combo(self.lk.employees if self.lk else [], "—")),
                      ("hours", "ساعت", num_field()), ("overtime_hours", "اضافه‌کار", num_field(0)), ("rate", "نرخ (خالی = خودکار)", num_field())],
            "machine": [("order_operation_id", "عملیات", combo(ops, "—")), ("hours", "ساعت", num_field()),
                        ("rate", "نرخ (خالی = خودکار)", num_field())],
            "hold": [("reason", "دلیل توقف", QLineEdit())],
            "complete": [("quantity", "رسید نهایی (اختیاری)", qty_field(self.view.order.remaining_qty, item_id=product)),
                         ("joint_method", "روش تخصیص تولید مشترک", combo([(v, k) for k, v in pc.JOINT_METHODS.items()]))],
            "reopen": [("reason", "دلیل بازگشایی", QLineEdit())], "cancel": [("reason", "دلیل لغو", QLineEdit())],
            "reverse": [("txn_id", "رسید", combo([(f"{numerals.format_jalali_date(t.date)} -- {t.item_label} -- {decimals.format_qty(t.quantity, item_id=t.item_id)}", t.txn_id)
                                                   for t in self.view.transactions if t.txn_type in ("RECEIPT", "CO_PRODUCT", "BY_PRODUCT")
                                                   and not t.reversed])),
                        ("reason", "دلیل", QLineEdit())],
        }
        if values is None and key in forms:
            values = _ask(self, dict((k, lb) for k, lb, _f in self.ACTIONS)[key], forms[key])
            if values is None:
                return False
        values = values or {}
        if key in ("close", "cancel", "complete") and not getattr(self, "_skip_confirm", False):
            if not self.confirm("این عملیات قابل بازگشت مستقیم نیست. ادامه می‌دهید؟"):
                return False
        fn = {
            "release": lambda: po.release_order(cid, uid, oid),
            "reserve": lambda: po.reserve_materials(cid, uid, oid),
            "start": lambda: po.start_order(cid, uid, oid),
            "issue": lambda: po.issue_materials(cid, uid, oid, [po.IssueLine(values["material_id"], values["quantity"])],
                                                reason=values.get("reason")),
            "issue_all": lambda: po.issue_all_remaining(cid, uid, oid),
            "return": lambda: po.return_materials(cid, uid, oid, [po.IssueLine(values["material_id"], values["quantity"])],
                                                  reason=values.get("reason")),
            "receipt": lambda: po.report_production(cid, uid, oid, po.ReceiptInput(
                values.get("quantity") or ZERO, {int(k[4:]): v for k, v in values.items() if k.startswith("out_") and v},
                batch_no=values.get("batch_no"))),
            "scrap": lambda: po.report_scrap(cid, uid, oid, values["quantity"], values.get("reason") or "ضایعات",
                                             scrap_item_id=values.get("scrap_item_id"), recovery_value_per_unit=values.get("recovery")),
            "labor": lambda: pcost.record_labor(cid, uid, oid, pcost.LaborInput(
                hours=values["hours"], order_operation_id=values.get("order_operation_id"), employee_id=values.get("employee_id"),
                overtime_hours=values.get("overtime_hours") or ZERO, rate=values.get("rate") or None)),
            "machine": lambda: pcost.record_machine(cid, uid, oid, pcost.MachineInput(
                hours=values["hours"], order_operation_id=values.get("order_operation_id"), rate=values.get("rate") or None)),
            "hold": lambda: po.hold_order(cid, uid, oid, values.get("reason") or ""),
            "resume": lambda: po.resume_order(cid, uid, oid),
            "complete": lambda: po.complete_order(cid, uid, oid, po.ReceiptInput(values.get("quantity") or ZERO,
                                                                                 joint_method=values.get("joint_method"))),
            "close": lambda: po.close_order(cid, uid, oid),
            "reopen": lambda: po.reopen_order(cid, uid, oid, values.get("reason") or ""),
            "cancel": lambda: po.cancel_order(cid, uid, oid, values.get("reason") or ""),
            "children": lambda: po.create_child_orders(cid, uid, oid),
            "reverse": lambda: po.reverse_production(cid, uid, values["txn_id"], values.get("reason") or ""),
        }[key]
        result, ok = _run(self, "دستور تولید", fn)
        if ok:
            if key == "release" and result:
                QMessageBox.information(self, "صدور", "دستور با هشدار کمبود صادر شد: " + "، ".join(a.item_label for a in result))
            self.reload_list()
            self.load_order(oid)
        return ok


# =========================================================================================================
@ms.styled
class MasterDataScreen(QWidget):
    """اطلاعات پایهٔ تولید: فهرست مواد (نسخه‌ها، اجزا، خروجی‌ها، انفجار چندسطحی)، مسیر تولید، مرکز کاری، دستمزد، عملیات."""

    scroll_in_mdi = True

    def __init__(self) -> None:
        super().__init__()
        self.lk: PrdLookups | None = None
        self.dialog_runner = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("اطلاعات پایهٔ تولید")
        title.setObjectName("pageTitle")
        outer.addWidget(title)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, stretch=1)
        # BOM
        bom = QWidget()
        bl = QVBoxLayout(bom)
        row = QHBoxLayout()
        self.bom_item = QComboBox()
        self.bom_item.currentIndexChanged.connect(self.load_boms)
        row.addWidget(QLabel("محصول:"))
        row.addWidget(self.bom_item, stretch=1)
        self.bom_buttons = {}
        for key, label in (("new", "نسخهٔ جدید"), ("edit_version", "ویرایش نسخه"), ("delete_version", "حذف نسخه"),
                           ("copy", "کپی به نسخهٔ جدید"), ("default", "پیش‌فرض"), ("archive", "بایگانی"),
                           ("component", "افزودن جزء"), ("edit_component", "ویرایش جزء"), ("remove", "حذف جزء"),
                           ("output", "جانبی/مشترک"), ("edit_output", "ویرایش خروجی"), ("remove_output", "حذف خروجی"),
                           ("explode", "انفجار چندسطحی"), ("profile", "مشخصات تولیدی کالا")):
            b = QPushButton(label)
            b.setProperty("form", "prd_bom")
            b.clicked.connect(lambda _c=False, k=key: self.bom_action(k))
            row.addWidget(b)
            self.bom_buttons[key] = b
        bl.addLayout(row)
        split = QSplitter(Qt.Horizontal)
        self.t_versions = table(["کد", "نام", "مقدار تولید", "وضعیت", "پیش‌فرض", "قفل", "اجزا"])
        self.t_versions.itemSelectionChanged.connect(self.load_components)
        self.t_components = table(["#", "جزء", "نوع", "مقدار", "پایه", "ضایعات٪", "ثابت/متغیر", "عملیات", "جایگزین", "اختیاری"])
        split.addWidget(self.t_versions)
        split.addWidget(self.t_components)
        bl.addWidget(split, stretch=1)
        self.t_outputs = table(["خروجی", "نوع", "مقدار به ازای دسته", "ارزش بازیافت/فروش"])
        self.t_outputs.setMaximumHeight(130)
        bl.addWidget(self.t_outputs)
        self.tabs.addTab(bom, "فهرست مواد (BOM)")
        # مسیر
        rt = QWidget()
        rl = QVBoxLayout(rt)
        rrow = QHBoxLayout()
        self.rt_item = QComboBox()
        self.rt_item.currentIndexChanged.connect(self.load_routings)
        rrow.addWidget(QLabel("محصول:"))
        rrow.addWidget(self.rt_item, stretch=1)
        for key, label in (("new", "مسیر جدید"), ("edit_routing", "ویرایش مسیر"), ("delete_routing", "حذف مسیر"),
                           ("copy", "کپی به نسخهٔ جدید"), ("default", "پیش‌فرض"), ("op", "افزودن عملیات"),
                           ("edit_op", "ویرایش عملیات"), ("remove", "حذف عملیات")):
            b = QPushButton(label)
            b.setProperty("form", "prd_routing")
            b.clicked.connect(lambda _c=False, k=key: self.routing_action(k))
            rrow.addWidget(b)
        rl.addLayout(rrow)
        split2 = QSplitter(Qt.Horizontal)
        self.t_routings = table(["نسخه", "نام", "پیش‌فرض", "وضعیت"])
        self.t_routings.itemSelectionChanged.connect(self.load_ops)
        self.t_ops = table(["ترتیب", "عملیات", "مرکز کاری", "آماده‌سازی", "اجرا (دقیقه/واحد)", "ماشین", "انتظار", "جابه‌جایی",
                            "نرخ دستمزد", "نرخ ماشین", "نرخ سربار"])
        split2.addWidget(self.t_routings)
        split2.addWidget(self.t_ops)
        rl.addWidget(split2, stretch=1)
        self.tabs.addTab(rt, "مسیر تولید")
        # مرکزِ کاری
        wc = QWidget()
        wl = QVBoxLayout(wc)
        wrow = QHBoxLayout()
        for key, label in (("new", "مرکز کاری جدید"), ("edit", "ویرایش"), ("delete", "حذف مرکز کاری"),
                           ("machine", "اتصال ماشین"), ("unlink", "جداکردن ماشین")):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, k=key: self.wc_action(k))
            wrow.addWidget(b)
        wrow.addStretch(1)
        wl.addLayout(wrow)
        self.t_wcs = table(["کد", "نام", "نوع", "اپراتور", "شیفت × ساعت", "راندمان٪", "نرخ دستمزد", "نرخ ماشین", "نرخ سربار", "ماشین‌ها"])
        wl.addWidget(self.t_wcs)
        self.tabs.addTab(wc, "مراکز کاری و ماشین‌ها")
        # دستمزد و عملیات
        lab = QWidget()
        ll = QVBoxLayout(lab)
        lrow = QHBoxLayout()
        for key, label in (("labor", "نرخ دستمزد جدید"), ("edit_labor", "ویرایش نرخ دستمزد"), ("delete_labor", "حذف نرخ دستمزد"),
                           ("operation", "عملیات استاندارد"), ("edit_operation", "ویرایش عملیات"),
                           ("delete_operation", "حذف عملیات استاندارد")):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, k=key: self.misc_action(k))
            lrow.addWidget(b)
        lrow.addStretch(1)
        ll.addLayout(lrow)
        self.t_labor = table(["کد", "نام", "نرخ ساعتی", "ضریب اضافه‌کار"])
        self.t_operations = table(["کد", "نام", "آماده‌سازی", "اجرا", "کنترل کیفیت"])
        ll.addWidget(self.t_labor)
        ll.addWidget(self.t_operations)
        self.tabs.addTab(lab, "دستمزد و عملیات")

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.lk = PrdLookups(cid)
        for box in (self.bom_item, self.rt_item):
            current = box.currentData()
            box.blockSignals(True)
            box.clear()
            for label, data in self.lk.made:
                box.addItem(P(label), data)
            set_combo(box, current)
            box.blockSignals(False)
        for b in self.bom_buttons.values():
            b.setEnabled(can("prd_bom", "EDIT"))
        self.load_boms()
        self.load_routings()
        self.load_wcs()
        self._labor_rows = pm.list_labor_rates(cid)
        fill(self.t_labor, [[r.code, r.name, r.hourly_rate, r.overtime_multiplier] for r in self._labor_rows],
             [r.labor_rate_id for r in self._labor_rows])
        self._op_rows = pm.list_operations(cid)
        fill(self.t_operations, [[o.code, o.name, o.default_setup_minutes, o.default_run_minutes, "بله" if o.is_qc else ""]
                                 for o in self._op_rows], [o.operation_id for o in self._op_rows])

    # BOM
    def _bom_id(self):
        items = self.t_versions.selectedItems()
        return self.t_versions.item(items[0].row(), 0).data(Qt.UserRole) if items else None

    def load_boms(self) -> None:
        item_id = self.bom_item.currentData()
        rows = pm.list_bom_versions(company_id(), item_id) if item_id else []
        fill(self.t_versions, [[r.code, r.name or "", qty(r.batch_size_qty, r.item_id), pc.BOM_STATUS.get(r.status_code, ""),
                                "✓" if r.is_default else "", "🔒" if r.is_locked else "", r.component_count] for r in rows],
             [r.bom_id for r in rows])
        if rows:
            self.t_versions.selectRow(len(rows) - 1)
            self.load_components()
        else:
            fill(self.t_components, [])
            fill(self.t_outputs, [])

    def load_components(self) -> None:
        bom_id = self._bom_id()
        if bom_id is None:
            return
        cid = company_id()
        rows = pm.bom_components(cid, bom_id)
        fill(self.t_components, [[r.line_no, r.item_label, pc.COMPONENT_TYPES.get(r.component_type, ""), qty(r.quantity, r.item_id, r.uom_id),
                                  qty(r.base_quantity, r.item_id), qty(r.scrap_percent), "ثابت" if r.quantity_type == "FIXED" else "متغیر",
                                  r.operation_seq or "", r.substitute_label, "✓" if r.is_optional else ""] for r in rows],
             [r.bom_line_id for r in rows])
        labels = dict((d, lb) for lb, d in (self.lk.items if self.lk else []))
        outputs = pm.bom_outputs(cid, bom_id)
        fill(self.t_outputs, [[labels.get(o.item_id, o.item_id), pc.OUTPUT_TYPES[o.output_type], qty(o.quantity_per, o.item_id),
                               o.recovery_value_per_unit or o.sales_value_per_unit or ""] for o in outputs],
             [o.bom_output_id for o in outputs])

    def bom_action(self, key: str, values: dict | None = None) -> bool:
        cid, uid, item_id, bom_id = company_id(), user_id(), self.bom_item.currentData(), self._bom_id()
        lk = self.lk
        line = version = None
        if key == "edit_component":
            line_id = selected_or_none(self.t_components)
            line = next((r for r in pm.bom_components(cid, bom_id) if r.bom_line_id == line_id), None) if bom_id else None
            if line is None:
                QMessageBox.warning(self, "BOM", "یک جزء را انتخاب کنید.")
                return False
        if key == "edit_version":
            version = next((v for v in pm.list_bom_versions(cid, item_id) if v.bom_id == bom_id), None) if bom_id else None
            if version is None:
                QMessageBox.warning(self, "BOM", "یک نسخه را انتخاب کنید.")
                return False
        if key == "delete_version" and values is None:
            if bom_id is None:
                QMessageBox.warning(self, "BOM", "یک نسخه را انتخاب کنید.")
                return False
            if QMessageBox.question(self, "BOM", "نسخهٔ انتخاب‌شدهٔ فهرست مواد با همهٔ اجزایش حذف شود؟") != QMessageBox.Yes:
                return False
        output = None
        if key == "edit_output":
            out_id = selected_or_none(self.t_outputs)
            output = next((o for o in pm.bom_outputs(cid, bom_id) if o.bom_output_id == out_id), None) if bom_id and out_id else None
            if output is None:
                QMessageBox.warning(self, "BOM", "یک خروجی جانبی/مشترک را انتخاب کنید.")
                return False
        if key == "remove_output":
            out_id = selected_or_none(self.t_outputs)
            if out_id is None:
                QMessageBox.warning(self, "BOM", "یک خروجی جانبی/مشترک را انتخاب کنید.")
                return False
            if QMessageBox.question(self, "BOM", "خروجی انتخاب‌شده حذف شود؟") != QMessageBox.Yes:
                return False
        if key == "remove" and values is None:
            if QMessageBox.question(self, "BOM", "جزء انتخاب‌شده حذف شود؟") != QMessageBox.Yes:
                return False
        component_box = combo(lk.items)
        edit_box = _combo_at(combo(lk.items), line.item_id) if line is not None else None
        output_box = _combo_at(combo(lk.items), output.item_id if output else None)
        forms = {
            "new": [("batch_size_qty", "مقدار تولید فهرست مواد", qty_field(1, item_id=item_id)), ("scrap_percent", "ضایعات پیش‌فرض٪", num_field(0)),
                    ("name", "نام", QLineEdit()), ("valid_from", "شروع اعتبار", date_field())],
            "edit_version": [] if version is None else [
                ("batch_size_qty", "مقدار تولید فهرست مواد", qty_field(version.batch_size_qty, item_id=item_id)),
                ("scrap_percent", "ضایعات پیش‌فرض٪", num_field(version.scrap_percent)),
                ("name", "نام", QLineEdit(version.name or ""))],
            "edit_component": [] if line is None else [
                ("component_item_id", "جزء", edit_box), ("quantity", "مقدار", qty_field(line.quantity, item_combo=edit_box)),
                ("scrap_percent", "ضایعات٪", num_field(line.scrap_percent)),
                ("component_type", "نوع", _combo_at(combo([(v, k) for k, v in pc.COMPONENT_TYPES.items()]), line.component_type)),
                ("fixed", "مقدار ثابت (مستقل از تعداد)", _checked(line.quantity_type == "FIXED")),
                ("operation_seq", "ترتیب عملیات", num_field(line.operation_seq)),
                ("substitute_item_id", "جایگزین", _combo_at(combo(lk.items, "—"), line.substitute_item_id)),
                ("is_optional", "اختیاری", _checked(line.is_optional))],
            "component": [("component_item_id", "جزء", component_box), ("quantity", "مقدار", qty_field(item_combo=component_box)),
                          ("scrap_percent", "ضایعات٪", num_field(0)),
                          ("component_type", "نوع", combo([(v, k) for k, v in pc.COMPONENT_TYPES.items()])),
                          ("fixed", "مقدار ثابت (مستقل از تعداد)", QCheckBox()), ("operation_seq", "ترتیب عملیات", num_field()),
                          ("substitute_item_id", "جایگزین", combo(lk.items, "—")), ("is_optional", "اختیاری", QCheckBox())],
            "output": [("item_id", "کالا", output_box), ("output_type", "نوع", _combo_at(combo([("محصول جانبی", "BY_PRODUCT"),
                                                                                         ("محصول مشترک", "CO_PRODUCT")]),
                                                                                  output.output_type if output else None)),
                       ("quantity_per", "مقدار به ازای دسته", qty_field(output.quantity_per if output else None, item_combo=output_box)),
                       ("value", "ارزش بازیافت/فروش واحد", num_field(
                           (output.recovery_value_per_unit or output.sales_value_per_unit or 0) if output else 0))],
            "profile": [("make_or_buy", "تامین", combo([("ساخت", "MAKE"), ("خرید", "BUY")])), ("lead_time_days", "زمان تولید (روز)", num_field(0)),
                        ("min_lot_qty", "حداقل تولید", qty_field(item_id=item_id)), ("max_lot_qty", "حداکثر تولید", qty_field(item_id=item_id)),
                        ("standard_scrap_percent", "ضایعات استاندارد٪", num_field(0)), ("backflush", "مصرف خودکار (Backflush)", QCheckBox())],
        }
        forms["edit_output"] = forms["output"]
        if key in forms and values is None:
            values = _ask(self, "BOM", forms[key])
            if values is None:
                return False
        values = values or {}
        def line_fields() -> pm.BomLineFields:
            return pm.BomLineFields(
                component_item_id=values["component_item_id"], quantity=values["quantity"], uom_id=lk.uoms.get(values["component_item_id"]),
                scrap_percent=values.get("scrap_percent") or ZERO, quantity_type="FIXED" if values.get("fixed") else "VARIABLE",
                component_type=values.get("component_type") or "MATERIAL",
                operation_seq=int(values["operation_seq"]) if values.get("operation_seq") else None,
                substitute_item_id=values.get("substitute_item_id"), is_optional=bool(values.get("is_optional")),
                warehouse_id=line.warehouse_id if line else None, notes=line.notes if line else None)

        fn = {
            "edit_version": lambda: pm.update_bom(cid, bom_id, pm.BomFields(
                batch_size_qty=values.get("batch_size_qty") or version.batch_size_qty, scrap_percent=values.get("scrap_percent") or ZERO,
                name=values.get("name"), valid_from=version.valid_from, valid_to=version.valid_to,
                routing_id=version.routing_id, production_time_minutes=version.production_time_minutes, notes=version.notes,
                status_code=version.status_code), uid),
            "edit_component": lambda: pm.update_bom_component(cid, line.bom_line_id, line_fields(), uid),
            "remove_output": lambda: pm.remove_bom_output(cid, selected_or_none(self.t_outputs), uid),
            "delete_version": lambda: pm.delete_bom_version(cid, bom_id, uid),
            "edit_output": lambda: self._save_output(cid, bom_id, values, uid, output),
            "new": lambda: pm.create_bom_version(cid, item_id, pm.BomFields(
                batch_size_qty=values["batch_size_qty"] or decimal.Decimal(1), scrap_percent=values.get("scrap_percent") or ZERO,
                name=values.get("name"), valid_from=values.get("valid_from")), user_id=uid),
            "copy": lambda: pm.create_bom_version(cid, item_id, None, copy_from_bom_id=bom_id, user_id=uid),
            "default": lambda: pm.set_default_bom(cid, bom_id, uid),
            "archive": lambda: pm.update_bom(cid, bom_id, self._fields_of(bom_id, "ARCHIVED"), uid),
            "component": lambda: pm.add_bom_component(cid, bom_id, pm.BomLineFields(
                component_item_id=values["component_item_id"], quantity=values["quantity"], uom_id=lk.uoms.get(values["component_item_id"]),
                scrap_percent=values.get("scrap_percent") or ZERO, quantity_type="FIXED" if values.get("fixed") else "VARIABLE",
                component_type=values.get("component_type") or "MATERIAL", operation_seq=int(values["operation_seq"]) if values.get("operation_seq") else None,
                substitute_item_id=values.get("substitute_item_id"), is_optional=bool(values.get("is_optional"))), uid),
            "remove": lambda: pm.remove_bom_component(cid, self._selected_id(self.t_components), uid),
            "output": lambda: pm.save_bom_output(cid, bom_id, pm.BomOutputFields(
                values["item_id"], values["output_type"], values["quantity_per"],
                recovery_value_per_unit=values.get("value") if values["output_type"] == "BY_PRODUCT" else None,
                sales_value_per_unit=values.get("value") if values["output_type"] == "CO_PRODUCT" else None), uid),
            "explode": lambda: self._show_explosion(cid, item_id),
            "profile": lambda: pm.save_item_profile(cid, item_id, uid, **{k: (int(v) if k == "lead_time_days" else (v or None))
                                                                           for k, v in values.items()}),
        }[key]
        _r, ok = _run(self, "BOM", fn)
        if ok and key not in ("explode",):
            self.load_boms()
        return ok

    @staticmethod
    def _save_output(cid: int, bom_id: int, values: dict, uid, old) -> None:
        if old is not None and old.item_id != values["item_id"]:
            pm.remove_bom_output(cid, old.bom_output_id, uid)
        pm.save_bom_output(cid, bom_id, pm.BomOutputFields(
            values["item_id"], values["output_type"], values["quantity_per"],
            recovery_value_per_unit=values.get("value") if values["output_type"] == "BY_PRODUCT" else None,
            sales_value_per_unit=values.get("value") if values["output_type"] == "CO_PRODUCT" else None), uid)

    def _fields_of(self, bom_id: int, status: str) -> pm.BomFields:
        v = next(x for x in pm.list_bom_versions(company_id()) if x.bom_id == bom_id)
        return pm.BomFields(batch_size_qty=v.batch_size_qty, scrap_percent=v.scrap_percent, name=v.name, valid_from=v.valid_from,
                            valid_to=v.valid_to, routing_id=v.routing_id, production_time_minutes=v.production_time_minutes,
                            notes=v.notes, status_code=status)

    def _show_explosion(self, cid: int, item_id: int) -> None:
        rows = pm.explode(cid, item_id, decimal.Decimal(1))
        text = "\n".join(("  " * (r.level - 1)) + f"{'▸' if r.is_made else '•'} {r.item_label}: {qty(r.gross_qty, r.item_id)}" for r in rows)
        QMessageBox.information(self, "انفجار چندسطحی فهرست مواد (برای یک واحد)", P(text or "فهرست مواد ندارد."))

    @staticmethod
    def _selected_id(t: QTableWidget):
        items = t.selectedItems()
        if not items:
            raise ValueError("یک ردیف انتخاب کنید.")
        return t.item(items[0].row(), 0).data(Qt.UserRole)

    # مسیر
    def load_routings(self) -> None:
        item_id = self.rt_item.currentData()
        rows = pm.list_routings(company_id(), item_id) if item_id else []
        fill(self.t_routings, [[r.version_no, r.name or "", "✓" if r.is_default else "", pc.BOM_STATUS.get(r.status_code, "")] for r in rows],
             [r.routing_id for r in rows])
        if rows:
            self.t_routings.selectRow(len(rows) - 1)
            self.load_ops()
        else:
            fill(self.t_ops, [])

    def load_ops(self) -> None:
        items = self.t_routings.selectedItems()
        if not items:
            return
        rid = self.t_routings.item(items[0].row(), 0).data(Qt.UserRole)
        wcs = dict((d, lb) for lb, d in (self.lk.work_centers if self.lk else []))
        ops = pm.routing_operations(company_id(), rid)
        fill(self.t_ops, [[o.seq, o.name, wcs.get(o.work_center_id, ""), qty(o.setup_minutes), qty(o.run_minutes),
                           qty(o.machine_minutes) if o.machine_minutes is not None else "", qty(o.queue_minutes), qty(o.move_minutes),
                           o.labor_rate if o.labor_rate is not None else "", o.machine_rate if o.machine_rate is not None else "",
                           o.overhead_rate if o.overhead_rate is not None else ""] for o in ops], [o.routing_operation_id for o in ops])

    def routing_action(self, key: str, values: dict | None = None) -> bool:
        cid, uid, item_id = company_id(), user_id(), self.rt_item.currentData()
        items = self.t_routings.selectedItems()
        rid = self.t_routings.item(items[0].row(), 0).data(Qt.UserRole) if items else None
        if key == "new" and values is None:
            values = _ask(self, "مسیر تولید", [("name", "نام", QLineEdit())])
            if values is None:
                return False
        if key in ("edit_routing", "delete_routing") and rid is None:
            QMessageBox.warning(self, "مسیر تولید", "یک مسیر را انتخاب کنید.")
            return False
        if key == "edit_routing" and values is None:
            routing = next(r for r in pm.list_routings(cid, item_id) if r.routing_id == rid)
            values = _ask(self, "ویرایش مسیر تولید", [
                ("name", "نام", QLineEdit(routing.name or "")),
                ("status_code", "وضعیت", _combo_at(combo([(v, k) for k, v in pc.BOM_STATUS.items()]), routing.status_code))])
            if values is None:
                return False
        if key == "delete_routing" and values is None:
            if QMessageBox.question(self, "مسیر تولید", "مسیر انتخاب‌شده با همهٔ عملیاتش حذف شود؟") != QMessageBox.Yes:
                return False
        cur = None
        if key == "edit_op":
            op_id = selected_or_none(self.t_ops)
            cur = next((o for o in pm.routing_operations(cid, rid) if o.routing_operation_id == op_id), None) if rid else None
            if cur is None:
                QMessageBox.warning(self, "مسیر تولید", "یک عملیات را انتخاب کنید.")
                return False
        if key == "remove" and values is None:
            if QMessageBox.question(self, "مسیر تولید", "عملیات انتخاب‌شده حذف شود؟") != QMessageBox.Yes:
                return False
        if key in ("op", "edit_op") and values is None:
            g = (lambda name, default=None: getattr(cur, name)) if cur else (lambda name, default=None: default)
            values = _ask(self, "عملیات مسیر", [
                ("seq", "ترتیب", num_field(g("seq", 10))), ("name", "نام", QLineEdit(g("name", "") or "")),
                ("work_center_id", "مرکز کاری", _combo_at(combo(self.lk.work_centers, "—"), g("work_center_id"))),
                ("setup_minutes", "آماده‌سازی (دقیقه)", num_field(g("setup_minutes", 0))),
                ("run_minutes", "اجرا (دقیقه به ازای واحد)", num_field(g("run_minutes", 0))),
                ("machine_minutes", "ماشین (دقیقه/واحد، خالی = برابر اجرا)", num_field(g("machine_minutes"))),
                ("queue_minutes", "انتظار", num_field(g("queue_minutes", 0))),
                ("move_minutes", "جابه‌جایی", num_field(g("move_minutes", 0))), ("labor_count", "تعداد نیرو", num_field(g("labor_count", 1))),
                ("labor_rate", "نرخ دستمزد (خالی = مرکز کاری)", num_field(g("labor_rate"))),
                ("machine_rate", "نرخ ماشین", num_field(g("machine_rate"))),
                ("overhead_rate", "نرخ سربار", num_field(g("overhead_rate")))])
            if values is None:
                return False
        values = values or {}

        def op_fields() -> pm.RoutingOpFields:
            return pm.RoutingOpFields(
                seq=int(values["seq"]), name=values.get("name") or "", work_center_id=values.get("work_center_id"),
                setup_minutes=values.get("setup_minutes") or ZERO, run_minutes=values.get("run_minutes") or ZERO,
                machine_minutes=values.get("machine_minutes") or None, queue_minutes=values.get("queue_minutes") or ZERO,
                move_minutes=values.get("move_minutes") or ZERO, labor_count=values.get("labor_count") or decimal.Decimal(1),
                labor_rate=values.get("labor_rate") or None, machine_rate=values.get("machine_rate") or None,
                overhead_rate=values.get("overhead_rate") or None)

        fn = {
            "new": lambda: pm.create_routing(cid, item_id, values.get("name"), user_id=uid),
            "copy": lambda: pm.create_routing(cid, item_id, None, copy_from_routing_id=rid, user_id=uid),
            "edit_routing": lambda: pm.update_routing(cid, rid, values.get("name"), values.get("status_code") or "ACTIVE", uid),
            "delete_routing": lambda: pm.delete_routing(cid, rid, uid),
            "default": lambda: pm.set_default_routing(cid, rid),
            "edit_op": lambda: pm.update_routing_operation(cid, cur.routing_operation_id, op_fields(), uid),
            "op": lambda: pm.add_routing_operation(cid, rid, pm.RoutingOpFields(
                seq=int(values["seq"]), name=values.get("name") or "", work_center_id=values.get("work_center_id"),
                setup_minutes=values.get("setup_minutes") or ZERO, run_minutes=values.get("run_minutes") or ZERO,
                machine_minutes=values.get("machine_minutes") or None, queue_minutes=values.get("queue_minutes") or ZERO,
                move_minutes=values.get("move_minutes") or ZERO, labor_count=values.get("labor_count") or decimal.Decimal(1),
                labor_rate=values.get("labor_rate") or None, machine_rate=values.get("machine_rate") or None,
                overhead_rate=values.get("overhead_rate") or None), uid),
            "remove": lambda: pm.remove_routing_operation(cid, self._selected_id(self.t_ops), uid),
        }[key]
        _r, ok = _run(self, "مسیر تولید", fn)
        if ok:
            self.load_routings()
        return ok

    # مرکزِ کاری
    def load_wcs(self) -> None:
        cid = company_id()
        rows = pm.list_work_centers(cid)
        fill(self.t_wcs, [[w.code, w.name, pc.CENTER_TYPES.get(w.center_type, ""), w.operator_count,
                           f"{w.shifts_per_day} × {decimals.plain(w.hours_per_shift)}", qty(w.efficiency_percent), w.labor_rate, w.machine_rate,
                           w.overhead_rate, "، ".join(m.code for m in pm.work_center_machines(cid, w.work_center_id))] for w in rows],
             [w.work_center_id for w in rows])

    def wc_action(self, key: str, values: dict | None = None) -> bool:
        cid, uid = company_id(), user_id()
        wc_id = None
        current = None
        if key in ("edit", "machine", "delete", "unlink"):
            try:
                wc_id = self._selected_id(self.t_wcs)
            except ValueError as exc:
                QMessageBox.warning(self, "مرکز کاری", str(exc))
                return False
            current = pm.get_work_center(cid, wc_id)
        if key == "delete":
            return confirm_and_delete(self, "مرکز کاری", current.name, prm.WorkCenter, wc_id, cid, self.refresh)
        if key == "unlink":
            linked = pm.work_center_machines(cid, wc_id)
            if not linked:
                QMessageBox.information(self, "مرکز کاری", "ماشینی به این مرکز کاری متصل نیست.")
                return False
            if values is None:
                values = _ask(self, "جداکردن ماشین", [("asset_id", "ماشین", combo([(f"{m.code} — {m.name}", m.asset_id) for m in linked]))])
                if values is None:
                    return False
            _r, ok = _run(self, "مرکز کاری", pm.unlink_machine, cid, wc_id, values["asset_id"])
            self.load_wcs()
            return ok
        if key == "machine":
            from peecha.services.fixed_assets import production as fa_prod

            if values is None:
                values = _ask(self, "اتصال ماشین (دارایی ثابت)", [("asset_id", "ماشین", combo(
                    [(f"{m.asset_code} — {m.name}", m.asset_id) for m in fa_prod.machines(cid)]))])
                if values is None:
                    return False
            _r, ok = _run(self, "مرکز کاری", pm.link_machine, cid, wc_id, values["asset_id"], uid)
            self.load_wcs()
            return ok
        if values is None:
            c_ = current
            values = _ask(self, "مرکز کاری", [
                ("code", "کد", QLineEdit(c_.code if c_ else "")), ("name", "نام", QLineEdit(c_.name if c_ else "")),
                ("center_type", "نوع", _combo_at(combo([(v, k) for k, v in pc.CENTER_TYPES.items()]), c_.center_type if c_ else None)),
                ("operator_count", "تعداد اپراتور", num_field(c_.operator_count if c_ else 1)),
                ("shifts_per_day", "شیفت در روز", num_field(c_.shifts_per_day if c_ else 1)),
                ("hours_per_shift", "ساعت هر شیفت", num_field((c_.hours_per_shift if c_ else 8))),
                ("hourly_capacity_qty", "ظرفیت ساعتی (واحد)", num_field(c_.hourly_capacity_qty if c_ else None)),
                ("efficiency_percent", "راندمان٪", num_field(c_.efficiency_percent if c_ else 100)),
                ("labor_rate", "نرخ دستمزد", num_field(c_.labor_rate if c_ else 0)),
                ("machine_rate", "نرخ ماشین", num_field(c_.machine_rate if c_ else 0)),
                ("overhead_rate", "نرخ سربار", num_field(c_.overhead_rate if c_ else 0)),
                ("cost_center_detail_account_id", "مرکز هزینه",
                 _combo_at(combo(self.lk.cost_centers, "—"), c_.cost_center_detail_account_id if c_ else None)),
                ("warehouse_id", "انبار خط", _combo_at(combo(self.lk.warehouses, "—"), c_.warehouse_id if c_ else None)),
                ("branch_id", "شعبه", _combo_at(combo(self.lk.branches, "—"), c_.branch_id if c_ else None))])
            if values is None:
                return False
        for k in ("operator_count", "shifts_per_day"):
            values[k] = int(values.get(k) or 0)
        values["hourly_capacity_qty"] = values.get("hourly_capacity_qty") or None
        _r, ok = _run(self, "مرکز کاری", pm.save_work_center, cid, pm.WorkCenterFields(**values), wc_id, uid)
        if ok:
            self.load_wcs()
            self.lk = PrdLookups(cid)
        return ok

    def misc_action(self, key: str, values: dict | None = None) -> bool:
        cid, uid = company_id(), user_id()
        labor = op = None
        if key in ("edit_labor", "delete_labor"):
            labor_id = selected_or_none(self.t_labor)
            labor = next((r for r in getattr(self, "_labor_rows", []) if r.labor_rate_id == labor_id), None)
            if labor is None:
                QMessageBox.warning(self, "دستمزد", "یک نرخ دستمزد را انتخاب کنید.")
                return False
            if key == "delete_labor":
                return confirm_and_delete(self, "نرخ دستمزد", labor.name, prm.LaborRate, labor_id, cid, self.refresh)
        if key in ("edit_operation", "delete_operation"):
            op_id = selected_or_none(self.t_operations)
            op = next((o for o in getattr(self, "_op_rows", []) if o.operation_id == op_id), None)
            if op is None:
                QMessageBox.warning(self, "عملیات", "یک عملیات استاندارد را انتخاب کنید.")
                return False
            if key == "delete_operation":
                return confirm_and_delete(self, "عملیات استاندارد", op.name, prm.Operation, op_id, cid, self.refresh)
        if key in ("labor", "edit_labor"):
            values = values or _ask(self, "نرخ دستمزد", [
                ("code", "کد", QLineEdit(labor.code if labor else "")), ("name", "نام", QLineEdit(labor.name if labor else "")),
                ("hourly_rate", "نرخ ساعتی", num_field(labor.hourly_rate if labor else None)),
                ("employee_id", "کارمند (اختیاری)", _combo_at(combo(self.lk.employees, "—"), labor.employee_id if labor else None)),
                ("overtime_multiplier", "ضریب اضافه‌کار", num_field(labor.overtime_multiplier if labor else "1.4"))])
            if not values:
                return False
            _r, ok = _run(self, "دستمزد", pm.save_labor_rate, cid, values["code"] or "", values["name"] or "", values["hourly_rate"],
                          values.get("employee_id"), values.get("overtime_multiplier") or decimal.Decimal("1.4"),
                          labor.labor_rate_id if labor else None, labor.is_active if labor else True, user_id=uid)
        else:
            values = values or _ask(self, "عملیات استاندارد", [
                ("code", "کد", QLineEdit(op.code if op else "")), ("name", "نام", QLineEdit(op.name if op else "")),
                ("default_work_center_id", "مرکز کاری", _combo_at(combo(self.lk.work_centers, "—"), op.default_work_center_id if op else None)),
                ("default_setup_minutes", "آماده‌سازی", num_field(op.default_setup_minutes if op else 0)),
                ("default_run_minutes", "اجرا", num_field(op.default_run_minutes if op else 0)),
                ("is_qc", "کنترل کیفیت", _checked(bool(op and op.is_qc)))])
            if not values:
                return False
            _r, ok = _run(self, "عملیات", pm.save_operation, cid, values["code"] or "", values["name"] or "",
                          values.get("default_work_center_id"), values.get("default_setup_minutes") or ZERO,
                          values.get("default_run_minutes") or ZERO, bool(values.get("is_qc")), op.operation_id if op else None)
        if ok:
            self.refresh()
        return ok


# =========================================================================================================
@ms.styled
class PlanningScreen(QWidget):
    """برنامهٔ تولید، MRP، ظرفیت و تقویم تولید."""

    scroll_in_mdi = True

    def __init__(self) -> None:
        super().__init__()
        self.dialog_runner = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("برنامه‌ریزی تولید")
        title.setObjectName("pageTitle")
        outer.addWidget(title)
        range_row = QHBoxLayout()
        self.date_from, self.date_to = date_field(), date_field(datetime.date.today() + datetime.timedelta(days=30))
        range_row.addWidget(QLabel("از:"))
        range_row.addWidget(self.date_from)
        range_row.addWidget(QLabel("تا:"))
        range_row.addWidget(self.date_to)
        apply = QPushButton("به‌روزرسانی")
        apply.clicked.connect(self.refresh)
        range_row.addWidget(apply)
        range_row.addStretch(1)
        outer.addLayout(range_row)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, stretch=1)
        plans = QWidget()
        pl = QVBoxLayout(plans)
        prow = QHBoxLayout()
        for key, label in (("new", "برنامهٔ جدید"), ("edit_plan", "ویرایش برنامه"), ("delete_plan", "حذف برنامه"),
                           ("line", "افزودن ردیف"), ("edit_line", "ویرایش ردیف"), ("delete_line", "حذف ردیف"),
                           ("sales", "از سفارش‌های فروش"), ("min", "از حداقل موجودی"), ("approve", "تایید"),
                           ("convert", "تبدیل به دستور تولید")):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, k=key: self.plan_action(k))
            prow.addWidget(b)
        prow.addStretch(1)
        pl.addLayout(prow)
        split = QSplitter(Qt.Horizontal)
        self.t_plans = table(["کد", "نام", "دوره", "از", "تا", "وضعیت"])
        self.t_plans.itemSelectionChanged.connect(self.load_plan_lines)
        self.t_plan_lines = table(["تاریخ", "محصول", "مقدار", "منبع", "دستور"])
        split.addWidget(self.t_plans)
        split.addWidget(self.t_plan_lines)
        pl.addWidget(split, stretch=1)
        self.tabs.addTab(plans, "برنامهٔ تولید")
        mrp = QWidget()
        ml = QVBoxLayout(mrp)
        mrow = QHBoxLayout()
        run = QPushButton("محاسبهٔ نیاز مواد (MRP)")
        run.setObjectName("primaryButton")
        run.clicked.connect(self.run_mrp)
        convert = QPushButton("تبدیل پیشنهادهای انتخاب‌شده")
        convert.clicked.connect(self.convert_mrp)
        mrow.addWidget(run)
        mrow.addWidget(convert)
        mrow.addStretch(1)
        ml.addLayout(mrow)
        self.t_mrp = table(["سطح", "کالا", "نیاز کل", "موجودی", "رزرو", "آزاد", "در راه", "حداقل", "کمبود", "پیشنهاد", "مقدار",
                            "تاریخ نیاز", "تاریخ اقدام", "تبدیل‌شده"])
        self.t_mrp.setSelectionMode(QTableWidget.MultiSelection)
        ml.addWidget(self.t_mrp)
        self.tabs.addTab(mrp, "MRP و نیاز مواد")
        self.t_capacity = table(["مرکز کاری", "ظرفیت (ساعت)", "بار (ساعت)", "آزاد", "بهره‌برداری٪", "وضعیت", "دستورها"])
        self.tabs.addTab(self.t_capacity, "ظرفیت")
        self.t_calendar = table(["تاریخ", "مرکز کاری", "محصول", "مقدار", "دستور/برنامه", "وضعیت"])
        self.tabs.addTab(self.t_calendar, "تقویم تولید")

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.lk = PrdLookups(cid)
        plans = pp.list_plans(cid)
        fill(self.t_plans, [[p.code, p.name, {"DAY": "روزانه", "WEEK": "هفتگی", "MONTH": "ماهانه"}[p.period_type], p.start_date, p.end_date,
                             pp.PLAN_STATUS[p.status_code]] for p in plans], [p.plan_id for p in plans])
        self.load_mrp()
        df, dt = self.date_from.date(), self.date_to.date()
        fill(self.t_capacity, [[f"{x.code} — {x.name}", qty(x.capacity_hours), qty(x.load_hours), qty(x.free_hours), qty(x.utilization),
                                "🔴 اضافه‌بار" if x.overloaded else "🟢 عادی", "، ".join(x.orders[:6])] for x in pp.capacity_load(cid, df, dt)])
        fill(self.t_calendar, [[e.date, e.work_center, e.item_label, qty(e.quantity, e.item_id), e.ref, ("⚠ " if e.late else "") + e.status]
                               for e in pp.calendar(cid, df, dt)])

    def _plan_id(self):
        items = self.t_plans.selectedItems()
        return self.t_plans.item(items[0].row(), 0).data(Qt.UserRole) if items else None

    def load_plan_lines(self) -> None:
        pid = self._plan_id()
        if pid is None:
            return
        rows = pp.plan_lines(company_id(), pid)
        src = {"MANUAL": "دستی", "SALES_ORDER": "سفارش فروش", "MIN_STOCK": "حداقل موجودی", "MRP": "MRP"}
        self._plan_rows = rows
        fill(self.t_plan_lines, [[r.planned_date, r.item_label, qty(r.quantity, r.item_id), src[r.source_type], r.order_code] for r in rows],
             [r.line_id for r in rows])

    def plan_action(self, key: str, values: dict | None = None) -> bool:
        cid, uid, pid = company_id(), user_id(), self._plan_id()
        if key != "new" and pid is None:
            QMessageBox.warning(self, "برنامهٔ تولید", "یک برنامه را انتخاب کنید.")
            return False
        plan = next((p for p in pp.list_plans(cid) if p.plan_id == pid), None) if key == "edit_plan" else None
        line = None
        if key in ("edit_line", "delete_line"):
            line_id = selected_or_none(self.t_plan_lines)
            line = next((r for r in getattr(self, "_plan_rows", []) if r.line_id == line_id), None)
            if line is None:
                QMessageBox.warning(self, "برنامهٔ تولید", "یک ردیف برنامه را انتخاب کنید.")
                return False
        if key in ("new", "edit_plan") and values is None:
            g = (lambda name, default=None: getattr(plan, name)) if plan else (lambda name, default=None: default)
            values = _ask(self, "برنامهٔ تولید", [
                ("code", "کد", QLineEdit(g("code", ""))), ("name", "نام", QLineEdit(g("name", ""))),
                ("period_type", "دوره", _combo_at(combo([("ماهانه", "MONTH"), ("هفتگی", "WEEK"), ("روزانه", "DAY")]), g("period_type"))),
                ("start_date", "از", date_field(g("start_date"))),
                ("end_date", "تا", date_field(g("end_date", datetime.date.today() + datetime.timedelta(days=30))))])
            if values is None:
                return False
        if key in ("delete_plan", "delete_line") and values is None:
            if QMessageBox.question(self, "برنامهٔ تولید", "برنامه حذف شود؟" if key == "delete_plan" else "ردیف حذف شود؟") != QMessageBox.Yes:
                return False
        if key in ("line", "edit_line") and values is None:
            plan_item = _combo_at(combo(self.lk.made), line.item_id if line else None)
            values = _ask(self, "ردیف برنامه", [("item_id", "محصول", plan_item),
                                                ("planned_date", "تاریخ", date_field(line.planned_date if line else None)),
                                                ("quantity", "مقدار", qty_field(line.quantity if line else None, item_combo=plan_item))])
            if values is None:
                return False
        values = values or {}
        fn = {
            "new": lambda: pp.create_plan(cid, uid, values["code"] or "", values["name"] or "", values["start_date"], values["end_date"],
                                          values["period_type"]),
            "line": lambda: pp.add_plan_line(cid, pid, values["item_id"], values["planned_date"], values["quantity"]),
            "edit_plan": lambda: pp.update_plan(cid, uid, pid, values["code"] or "", values["name"] or "", values["start_date"],
                                                values["end_date"], values["period_type"]),
            "delete_plan": lambda: pp.delete_plan(cid, uid, pid),
            "edit_line": lambda: pp.update_plan_line(cid, line.line_id, values["item_id"], values["planned_date"], values["quantity"]),
            "delete_line": lambda: pp.remove_plan_line(cid, line.line_id),
            "sales": lambda: pp.generate_from_sales_orders(cid, pid),
            "min": lambda: pp.generate_from_min_stock(cid, pid),
            "approve": lambda: pp.approve_plan(cid, uid, pid),
            "convert": lambda: pp.convert_plan_to_orders(cid, uid, pid),
        }[key]
        _r, ok = _run(self, "برنامهٔ تولید", fn)
        if ok:
            self.refresh()
        return ok

    def load_mrp(self) -> None:
        self._mrp = pp.mrp_lines(company_id())
        fill(self.t_mrp, [[r.level, r.item_label, qty(r.gross_requirement, r.item_id), qty(r.on_hand, r.item_id), qty(r.reserved, r.item_id), qty(r.available, r.item_id),
                           qty(r.scheduled_receipts, r.item_id), qty(r.min_stock, r.item_id), qty(r.net_requirement, r.item_id),
                           ("🔨 " if r.suggested_action == "PRODUCE" else "🛒 " if r.suggested_action == "PURCHASE" else "") + r.action_label,
                           qty(r.suggested_qty, r.item_id), r.need_date or "", r.release_date or "", r.converted_ref or ""] for r in self._mrp],
             [r.mrp_line_id for r in self._mrp])

    def run_mrp(self) -> bool:
        _r, ok = _run(self, "MRP", pp.run_mrp, company_id(), user_id(),
                      max(1, (self.date_to.date() - datetime.date.today()).days))
        if ok:
            self.load_mrp()
        return ok

    def convert_mrp(self, line_ids: list[int] | None = None) -> bool:
        if line_ids is None:
            rows = sorted({i.row() for i in self.t_mrp.selectedItems()})
            line_ids = [self.t_mrp.item(r, 0).data(Qt.UserRole) for r in rows]
        if not line_ids:
            QMessageBox.warning(self, "MRP", "ردیف‌های پیشنهاد را انتخاب کنید.")
            return False
        res, ok = _run(self, "MRP", pp.convert_mrp, company_id(), user_id(), line_ids)
        if ok:
            QMessageBox.information(self, "MRP", P(f"{len(res.order_ids)} دستور تولید" +
                                                   (f" و درخواست خرید #{res.purchase_request_id}" if res.purchase_request_id else "") + " ساخته شد."))
            self.load_mrp()
        return ok


# =========================================================================================================
@ms.styled
class PrdCostingScreen(QWidget):
    """مخزن‌های هزینه و سرشکن، بهای استاندارد چندسطحی، بستن دوره‌ای بها."""

    scroll_in_mdi = True

    def __init__(self) -> None:
        super().__init__()
        self.dialog_runner = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("بهای تمام‌شدهٔ تولید")
        title.setObjectName("pageTitle")
        outer.addWidget(title)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, stretch=1)
        pools = QWidget()
        pl = QVBoxLayout(pools)
        row = QHBoxLayout()
        for key, label in (("new", "مخزن هزینهٔ جدید"), ("edit", "ویرایش مخزن"), ("delete", "حذف مخزن"),
                           ("preview", "پیش‌نمایش سرشکن"), ("allocate", "سرشکن")):
            b = QPushButton(label)
            b.setProperty("form", "prd_allocation")
            b.clicked.connect(lambda _c=False, k=key: self.pool_action(k))
            row.addWidget(b)
        row.addStretch(1)
        pl.addLayout(row)
        self.t_pools = table(["دوره", "کد", "نام", "نوع", "مبنا", "مبلغ", "سرشکن‌شده", "وضعیت"])
        self.t_preview = table(["دستور", "مقدار مبنا", "سهم"])
        pl.addWidget(self.t_pools)
        pl.addWidget(self.t_preview)
        self.tabs.addTab(pools, "سربار و سرشکن")
        std = QWidget()
        sl = QVBoxLayout(std)
        srow = QHBoxLayout()
        self.std_item = QComboBox()
        srow.addWidget(QLabel("محصول:"))
        srow.addWidget(self.std_item, stretch=1)
        calc = QPushButton("محاسبه")
        calc.clicked.connect(lambda: self.rollup(False))
        save = QPushButton("ثبت به‌عنوان بهای استاندارد")
        save.setProperty("form", "prd_cost_adjust")
        save.clicked.connect(lambda: self.rollup(True))
        srow.addWidget(calc)
        srow.addWidget(save)
        sl.addLayout(srow)
        self.t_std = table(["سطح", "کالا", "مواد", "دستمزد", "ماشین", "سربار", "کسر جانبی", "جمع واحد"])
        sl.addWidget(self.t_std)
        self.tabs.addTab(std, "بهای استاندارد")
        close = QWidget()
        cl = QVBoxLayout(close)
        crow = QHBoxLayout()
        self.period_edit = QLineEdit()
        self.period_edit.setPlaceholderText("دوره، مثلاً ۱۴۰۵/۰۷")
        crow.addWidget(self.period_edit)
        for key, label in (("preview", "پیش‌نمایش"), ("close", "بستن دوره"), ("reopen", "بازگشایی")):
            b = QPushButton(label)
            b.setProperty("form", "prd_cost_adjust")
            b.clicked.connect(lambda _c=False, k=key: self.period_action(k))
            crow.addWidget(b)
        crow.addStretch(1)
        cl.addLayout(crow)
        self.period_label = QLabel("")
        self.period_label.setWordWrap(True)
        cl.addWidget(self.period_label)
        self.t_closings = table(["دوره", "وضعیت", "دستورها", "WIP", "مواد", "دستمزد", "ماشین", "سربار", "تولید", "انحراف"])
        cl.addWidget(self.t_closings)
        self.tabs.addTab(close, "بستن دوره")

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        from peecha.services.fixed_assets.common import period_of

        self.lk = PrdLookups(cid)
        current = self.std_item.currentData()
        self.std_item.clear()
        for label, data in self.lk.made:
            self.std_item.addItem(P(label), data)
        set_combo(self.std_item, current)
        if not self.period_edit.text():
            self.period_edit.setText(P(period_of(datetime.date.today())[0]))
        pools = pcost.list_pools(cid)
        fill(self.t_pools, [[p.period_code, p.code, p.name, pcost.POOL_CATEGORIES.get(p.category, ""), pc.OVERHEAD_BASES.get(p.basis, ""),
                             p.amount, p.allocated_amount, "سرشکن‌شده" if p.status_code == "ALLOCATED" else "باز"] for p in pools],
             [p.pool_id for p in pools])
        fill(self.t_closings, [[x.period_code, "نهایی" if x.status_code == "FINALIZED" else "بازگشایی‌شده", x.orders_count, x.wip_balance,
                                x.material_total, x.labor_total, x.machine_total, x.overhead_applied, x.output_total, x.variance_total]
                               for x in pcost.list_closings(cid)])

    def _period(self) -> str:
        return numerals.to_ascii_digits(self.period_edit.text().strip())

    def pool_action(self, key: str, values: dict | None = None) -> bool:
        cid, uid = company_id(), user_id()
        pool = None
        if key in ("edit", "delete"):
            pool_id = selected_or_none(self.t_pools)
            pool = next((p for p in pcost.list_pools(cid) if p.pool_id == pool_id), None)
            if pool is None:
                QMessageBox.warning(self, "مخزن هزینه", "یک مخزن را انتخاب کنید.")
                return False
            if pool.status_code == "ALLOCATED" or pool.allocated_amount:
                QMessageBox.warning(self, "مخزن هزینه", "مخزن سرشکن‌شده قابل ویرایش یا حذف نیست.")
                return False
            if key == "delete":
                return confirm_and_delete(self, "مخزن هزینه", pool.name, prm.CostPool, pool.pool_id, cid, self.refresh)
        if key in ("new", "edit"):
            values = values or _ask(self, "مخزن هزینه", [
                ("code", "کد", QLineEdit(pool.code if pool else "")), ("name", "نام", QLineEdit(pool.name if pool else "")),
                ("period_code", "دوره", QLineEdit(P(pool.period_code if pool else self._period()))),
                ("amount", "مبلغ", num_field(pool.amount if pool else None)),
                ("category", "نوع", _combo_at(combo([(v, k) for k, v in pcost.POOL_CATEGORIES.items()]), pool.category if pool else None)),
                ("basis", "مبنای سرشکن", _combo_at(combo([(v, k) for k, v in pc.OVERHEAD_BASES.items()]), pool.basis if pool else None)),
                ("work_center_id", "فقط مرکز کاری", _combo_at(combo(self.lk.work_centers, "— همه —"), pool.work_center_id if pool else None))])
            if not values:
                return False
            _r, ok = _run(self, "مخزن هزینه", pcost.save_pool, cid, values["code"] or "", values["name"] or "",
                          numerals.to_ascii_digits(values["period_code"] or ""), values["amount"], values["basis"],
                          values["category"], values.get("work_center_id"), pool.notes if pool else None, user_id=uid,
                          pool_id=pool.pool_id if pool else None)
        else:
            try:
                pool_id = MasterDataScreen._selected_id(self.t_pools)
            except ValueError as exc:
                QMessageBox.warning(self, "سرشکن", str(exc))
                return False
            if key == "preview":
                rows, ok = _run(self, "سرشکن", pcost.preview_pool, cid, pool_id)
                if ok:
                    fill(self.t_preview, [[r.order_code, qty(r.basis_value), r.amount] for r in rows])
                return ok
            _r, ok = _run(self, "سرشکن", pcost.allocate_pool, cid, uid, pool_id)
        if ok:
            self.refresh()
        return ok

    def rollup(self, write: bool) -> bool:
        rows, ok = _run(self, "بهای استاندارد", pcost.rollup_standard_cost, company_id(), self.std_item.currentData(),
                        write=write, user_id=user_id())
        if ok:
            fill(self.t_std, [[r.level, r.item_label, r.material, r.labor, r.machine, r.overhead, r.byproduct_credit, r.total] for r in rows])
        return ok

    def period_action(self, key: str, reason: str | None = None) -> bool:
        cid, uid, period = company_id(), user_id(), self._period()
        if key == "preview":
            n, ok = _run(self, "بستن دوره", pcost.period_preview, cid, period)
            if ok:
                self.period_label.setText(P("\n".join([
                    f"دوره {n.period_code}: {n.orders_count} دستور — کالای در جریان ساخت پایان دوره {money(n.wip_balance)}",
                    f"مواد {money(n.material_total)} -- دستمزد {money(n.labor_total)} -- ماشین {money(n.machine_total)} -- "
                    f"سربار جذب‌شده {money(n.overhead_applied)} (مخزن‌ها {money(n.overhead_pools)})",
                    f"تولید {money(n.output_total)} -- انحراف {money(n.variance_total)}",
                    ("موانع: " + " | ".join(n.blockers)) if n.blockers else "آمادهٔ بستن"])))
            return ok
        if key == "close":
            _r, ok = _run(self, "بستن دوره", pcost.close_period, cid, uid, period)
        else:
            reason = reason or (_ask(self, "بازگشایی", [("reason", "دلیل", QLineEdit())]) or {}).get("reason")
            _r, ok = _run(self, "بازگشایی", pcost.reopen_period, cid, uid, period, reason or "")
        if ok:
            self.refresh()
        return ok


# =========================================================================================================
@ms.styled
class PrdSettingsScreen(QWidget):
    """تنظیمات تولید (هم‌الگو با تنظیمات ماژول‌های دیگر) + وضعیت نگاشت حساب‌ها."""

    scroll_in_mdi = True

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("تنظیمات تولید")
        title.setObjectName("pageTitle")
        outer.addWidget(title)
        self.form = QFormLayout()
        self.w = {}
        for key in ("default_material_warehouse_id", "default_production_warehouse_id", "default_fg_warehouse_id", "default_scrap_warehouse_id",
                    "default_cost_center_detail_account_id"):
            self.w[key] = QComboBox()
        for key in ("auto_reservation", "auto_consumption", "allow_over_consumption", "allow_under_consumption", "auto_cost_calculation",
                    "require_cost_closing", "allow_negative_material", "require_cost_center"):
            self.w[key] = QCheckBox()
        self.w["shortage_policy"] = combo([("هشدار", "WARN"), ("توقف", "BLOCK")])
        self.w["default_overhead_basis"] = combo([(v, k) for k, v in pc.OVERHEAD_BASES.items()])
        self.w["default_joint_cost_method"] = combo([(v, k) for k, v in pc.JOINT_METHODS.items()])
        self.w["abnormal_scrap_percent"] = num_field()
        self.w["order_prefix"] = QLineEdit()
        labels = {"default_material_warehouse_id": "انبار پیش‌فرض مواد", "default_production_warehouse_id": "انبار تولید (خط)",
                  "default_fg_warehouse_id": "انبار پیش‌فرض محصول", "default_scrap_warehouse_id": "انبار ضایعات",
                  "default_cost_center_detail_account_id": "مرکز هزینهٔ پیش‌فرض", "auto_reservation": "رزرو خودکار هنگام صدور",
                  "auto_consumption": "مصرف خودکار (Backflush)", "allow_over_consumption": "مجاز بودن مصرف بیش از استاندارد",
                  "allow_under_consumption": "مجاز بودن مصرف کمتر از استاندارد", "auto_cost_calculation": "محاسبهٔ خودکار بها",
                  "require_cost_closing": "الزام بستن دستورها پیش از بستن دوره", "allow_negative_material": "مجاز بودن موجودی منفی مواد",
                  "require_cost_center": "الزام مرکز هزینه", "shortage_policy": "رفتار هنگام کمبود مواد",
                  "default_overhead_basis": "مبنای پیش‌فرض سربار", "default_joint_cost_method": "روش پیش‌فرض تخصیص تولید مشترک",
                  "abnormal_scrap_percent": "حد ضایعات عادی٪", "order_prefix": "پیشوند شمارهٔ دستور"}
        for key, w in self.w.items():
            self.form.addRow(labels[key], w)
        outer.addLayout(self.form)
        self.accounts_label = QLabel("")
        self.accounts_label.setWordWrap(True)
        outer.addWidget(self.accounts_label)
        save = QPushButton("ذخیره")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save)
        outer.addWidget(save, alignment=Qt.AlignLeft)
        roles_button = QPushButton("ساخت نقش‌های آماده (کاربر / مدیر تولید / حسابدار بها)")
        roles_button.clicked.connect(self.create_roles)
        outer.addWidget(roles_button, alignment=Qt.AlignLeft)
        outer.addStretch(1)

    def create_roles(self) -> bool:
        from peecha.services.production import roles_setup

        roles, ok = _run(self, "نقش‌ها", roles_setup.ensure_role_templates, company_id())
        if ok:
            QMessageBox.information(self, "نقش‌ها", "نقش‌ها ساخته/به‌روز شد: " + "، ".join(
                roles_setup.TEMPLATES[k][0] for k in roles))
        return ok

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        lk = PrdLookups(cid)
        st = pc.get_settings(cid)
        for key, w in self.w.items():
            value = getattr(st, key)
            if isinstance(w, QCheckBox):
                w.setChecked(bool(value))
            elif isinstance(w, QComboBox):
                if key.endswith("warehouse_id") or key.endswith("account_id"):
                    w.clear()
                    w.addItem("—", None)
                    for label, data in (lk.cost_centers if key.endswith("account_id") else lk.warehouses):
                        w.addItem(P(label), data)
                set_combo(w, value)
            else:
                w.setText(decimals.plain(value) if isinstance(value, decimal.Decimal) else P(value))
        missing = pc.missing_roles(cid, tuple(pc.ROLE_LABELS))
        self.accounts_label.setText("نگاشت حساب‌های تولید (تنظیمات انبار ← نگاشت حساب‌ها): " +
                                    ("کامل است ✓" if not missing else "ناقص: " + "، ".join(missing)))

    def save(self) -> bool:
        values = {}
        for key, w in self.w.items():
            if isinstance(w, QCheckBox):
                values[key] = w.isChecked()
            elif isinstance(w, QComboBox):
                values[key] = w.currentData()
            elif key == "abnormal_scrap_percent":
                values[key] = dec(w.text())
            else:
                values[key] = w.text().strip() or "PO"
        _r, ok = _run(self, "تنظیمات تولید", pc.update_settings, company_id(), user_id(), **values)
        if ok:
            QMessageBox.information(self, "تنظیمات تولید", "ذخیره شد.")
        return ok
