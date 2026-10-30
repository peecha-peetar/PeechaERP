"""R373: تعهد تحویل (ATP) و سناریوی تقاضا — زودترین تاریخ قابل تعهد، موجودی پیش‌بینی روزانه، برآورد با تولید و اثر سناریو."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services.production import atp
from peecha.ui import report_export, theme
from peecha.ui.screens.fixed_assets import P, combo, company_id, dec, fill, selected_data, table, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec, JalaliDateEdit, build_page_header

_OUTCOME_HEADERS = ["کالا", "کمترین موجودی (بدون سناریو)", "کمترین موجودی (با سناریو)", "اولین کسری (بدون سناریو)",
                    "اولین کسری (با سناریو)", "کسری اضافه"]


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


def _q(value) -> str:
    return P(f"{decimal.Decimal(value).quantize(decimal.Decimal('0.001')).normalize():f}") if value is not None else "—"


def _date(value) -> str:
    return numerals.format_jalali_date(value) if value else "—"


class ProductionAtpScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.result: atp.Promise | None = None
        self.scenarios: list[atp.ScenarioRow] = []
        self.scenario_id: int | None = None
        self.lines: list[atp.ScenarioLineFields] = []
        self.evaluation: atp.ScenarioResult | None = None
        self._loaded_for = None
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "تعهد تحویل و سناریو", "زودترین تاریخی که می‌توان مقدار درخواستی یک کالا را به مشتری قول داد، از موجودی آزاد، سفارش‌های "
            "خرید و دستورهای تولید باز و با کنار گذاشتن سفارش‌های فروش و نیاز مواد دستورهای باز؛ برای کالای ساختنی برآورد با تولید هم "
            "نشان داده می‌شود. در سناریو، تقاضا یا تامین فرضی اضافه کنید و اثرش را ببینید. چیزی در سفارش‌ها و دستورها ثبت نمی‌شود."))
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_promise(), "تعهد تحویل")
        self.tabs.addTab(self._build_scenarios(), "سناریو")
        layout.addWidget(self.tabs, 1)

    # --- تعهد تحویل ------------------------------------------------------------------------------------------
    def _build_promise(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        row = QHBoxLayout()
        self.item_combo = combo([])
        self.qty_field = QLineEdit()
        self.wanted_field = JalaliDateEdit()
        self.horizon_field = QSpinBox()
        self.horizon_field.setRange(1, atp.MAX_HORIZON)
        self.horizon_field.setValue(90)
        row.addWidget(FieldGrid([
            FieldSpec("atp_item", "کالا", self.item_combo, span=2), FieldSpec("atp_qty", "مقدار", self.qty_field, span=1),
            FieldSpec("atp_wanted", "تاریخ درخواست مشتری", self.wanted_field, span=1),
            FieldSpec("atp_horizon", "افق بررسی (روز)", self.horizon_field, span=1)]), 1)
        for label, glyph, kind, slot in (("بررسی تعهد تحویل", "▶️", "primary", self.check), ("چاپ موجودی پیش‌بینی", "🖨️", "", self.print_timeline)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            row.addWidget(button)
        v.addLayout(row)
        self.answer_label = QLabel("کالا و مقدار را وارد کنید.")
        self.answer_label.setWordWrap(True)
        v.addWidget(self.answer_label)
        tabs = QTabWidget()
        self.day_table = table(["تاریخ", "ورودی", "خروجی", "موجودی پیش‌بینی", "قابل تعهد"])
        self.event_table = table(["تاریخ", "نوع", "منبع", "مقدار"])
        self.component_table = table(["جزء", "نیاز", "قابل تعهد در زمان شروع تولید", "کسری"])
        tabs.addTab(self.day_table, "موجودی پیش‌بینی روزانه")
        tabs.addTab(self.event_table, "ورودی‌ها و خروجی‌ها")
        tabs.addTab(self.component_table, "مواد برای تولید")
        v.addWidget(tabs, 1)
        return page

    def _status(self, text: str, ok: bool) -> None:
        theme.set_status_label(self.status_label, text, ok=ok)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        if self._loaded_for != cid:
            from peecha.services import inventory_catalog as catalog

            self._loaded_for = cid
            items = catalog.list_items(cid, active_only=True, transactable_only=True)
            options = [(f"{i.code} — {i.name or ''}", i.item_id) for i in items if i.is_stock_tracked]
            for box in (self.item_combo, self.line_item_combo):
                box.clear()
                box.addItem("— انتخاب کنید —", None)
                for label, data in options:
                    box.addItem(P(label), data)
        self._load_scenarios()

    def check(self) -> bool:
        cid, item_id = company_id(), self.item_combo.currentData()
        if cid is None or not item_id:
            self._status("کالا را انتخاب کنید.", False)
            return False
        try:
            r = self.result = atp.promise(cid, item_id, dec(self.qty_field.text()), self.wanted_field.date(), self.horizon_field.value())
        except (ValueError, decimal.InvalidOperation) as exc:
            self._status(str(exc) if isinstance(exc, ValueError) else "مقدار نامعتبر است.", False)
            return False
        parts = [f"قابل تعهد در تاریخ درخواست: {_q(r.atp_at_wanted)}"]
        if r.atp_date == r.wanted:
            parts.append("مقدار درخواستی در همان تاریخ قابل تعهد است.")
        elif r.atp_date:
            parts.append(f"زودترین تاریخ تعهد از موجودی و تامین‌های باز: {_date(r.atp_date)} "
                         f"({P((r.atp_date - r.wanted).days)} روز بعد از درخواست)")
        else:
            parts.append("در افق بررسی از موجودی و تامین‌های باز قابل تعهد نیست.")
        if r.made and r.atp_date != r.wanted:
            parts.append(f"با تولید (زمان تولید {P(r.lead_days)} روز، بدون بررسی ظرفیت): " +
                         (_date(r.ctp_date) if r.ctp_date else "مواد کافی در افق نیست"))
        self.answer_label.setText(" | ".join(parts))
        tl = r.timeline
        fill(self.day_table, [[d.date, _q(d.supply), _q(d.demand), _q(d.balance), _q(d.atp)] for d in tl.active_days])
        danger = QColor(theme.DANGER)
        for i, d in enumerate(tl.active_days):
            if d.balance < 0:
                self.day_table.item(i, 3).setForeground(danger)
        fill(self.event_table, [[e.date, "ورودی" if e.kind == "SUPPLY" else "خروجی", e.source, _q(e.quantity)] for e in tl.events])
        fill(self.component_table, [[ch.item_label, _q(ch.required), _q(ch.available), _q(ch.short)] for ch in r.components])
        self._status("بررسی انجام شد.", True)
        return True

    def print_timeline(self) -> bool:
        r = self.result
        if r is None:
            self._status("اول تعهد تحویل را بررسی کنید.", False)
            return False
        rows = [[_date(d.date), _q(d.supply), _q(d.demand), _q(d.balance), _q(d.atp)] for d in r.timeline.active_days]
        head = [("کالا", r.item_label), ("مقدار", _q(r.quantity)), ("تاریخ درخواست", _date(r.wanted)),
                ("زودترین تاریخ تعهد", _date(r.atp_date)), ("با تولید", _date(r.ctp_date))]
        report_export.print_report(self, "تعهد تحویل و موجودی پیش‌بینی", ["تاریخ", "ورودی", "خروجی", "موجودی پیش‌بینی", "قابل تعهد"],
                                   rows, filters=head)
        return True

    # --- سناریو ---------------------------------------------------------------------------------------------
    def _build_scenarios(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        top = QHBoxLayout()
        self.scenario_table = table(["نام سناریو", "توضیح", "ردیف‌ها"])
        self.scenario_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.scenario_table.setMaximumHeight(150)
        self.scenario_table.itemSelectionChanged.connect(self._load_scenario)
        top.addWidget(self.scenario_table, 1)
        v.addLayout(top)
        self.name_field, self.description_field = QLineEdit(), QLineEdit()
        v.addWidget(FieldGrid([FieldSpec("scn_name", "نام سناریو", self.name_field, span=1),
                               FieldSpec("scn_description", "توضیح", self.description_field, span=3)]))
        row = QHBoxLayout()
        self.line_item_combo = combo([])
        self.kind_combo = QComboBox()
        for code, label in atp.KINDS.items():
            self.kind_combo.addItem(label, code)
        self.line_date_field = JalaliDateEdit()
        self.line_qty_field, self.line_note_field = QLineEdit(), QLineEdit()
        row.addWidget(FieldGrid([
            FieldSpec("scn_item", "کالا", self.line_item_combo, span=2), FieldSpec("scn_kind", "نوع", self.kind_combo, span=1),
            FieldSpec("scn_date", "تاریخ", self.line_date_field, span=1), FieldSpec("scn_qty", "مقدار", self.line_qty_field, span=1),
            FieldSpec("scn_note", "توضیح ردیف", self.line_note_field, span=2)]), 1)
        for label, glyph, kind, slot in (("افزودن ردیف", "➕", "", self.add_line), ("برداشتن ردیف انتخاب‌شده", "➖", "danger", self.remove_line)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            row.addWidget(button)
        v.addLayout(row)
        self.line_table = table(["کالا", "نوع", "تاریخ", "مقدار", "توضیح"])
        self.line_table.setMaximumHeight(150)
        v.addWidget(self.line_table)
        bar = QHBoxLayout()
        for label, glyph, kind, slot in (("ذخیرهٔ سناریو", "💾", "primary", self.save_scenario), ("سناریوی جدید", "🆕", "", self.new_scenario),
                                         ("حذف سناریو", "🗑️", "danger", self.delete_scenario), ("اجرای سناریو", "▶️", "", self.run_scenario),
                                         ("چاپ نتیجهٔ سناریو", "🖨️", "", self.print_outcome)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            bar.addWidget(button)
        bar.addStretch(1)
        v.addLayout(bar)
        self.outcome_label = QLabel("")
        self.outcome_label.setWordWrap(True)
        v.addWidget(self.outcome_label)
        tabs = QTabWidget()
        self.promise_table = table(["کالا", "تاریخ درخواست", "مقدار", "تاریخ قابل تعهد", "تاخیر (روز)", "کسری در تاریخ درخواست"])
        self.outcome_table = table(_OUTCOME_HEADERS)
        tabs.addTab(self.promise_table, "تعهد تقاضاهای سناریو")
        tabs.addTab(self.outcome_table, "اثر روی موجودی کالاها")
        v.addWidget(tabs, 1)
        return page

    def _load_scenarios(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.scenarios = atp.list_scenarios(cid)
        fill(self.scenario_table, [[s.name, s.description, len(s.lines)] for s in self.scenarios], [s.scenario_id for s in self.scenarios])
        row = next((i for i, s in enumerate(self.scenarios) if s.scenario_id == self.scenario_id), None)
        if row is not None:
            self.scenario_table.blockSignals(True)
            self.scenario_table.setCurrentCell(row, 0)
            self.scenario_table.blockSignals(False)

    def _label(self, item_id: int) -> str:
        index = self.line_item_combo.findData(item_id)
        return self.line_item_combo.itemText(index) if index >= 0 else ""

    def _show_lines(self) -> None:
        fill(self.line_table, [[self._label(ln.item_id), atp.KINDS[ln.kind_code], ln.line_date, _q(ln.quantity), ln.note] for ln in self.lines],
             list(range(len(self.lines))))

    def _load_scenario(self) -> None:
        sid = selected_data(self.scenario_table)
        s = next((x for x in self.scenarios if x.scenario_id == sid), None)
        if s is None:
            return
        self.scenario_id = s.scenario_id
        self.name_field.setText(s.name)
        self.description_field.setText(s.description)
        self.lines = list(s.lines)
        self._show_lines()

    def new_scenario(self) -> None:
        self.scenario_id = None
        self.scenario_table.clearSelection()
        for f in (self.name_field, self.description_field, self.line_qty_field, self.line_note_field):
            f.clear()
        self.lines = []
        self._show_lines()

    def add_line(self) -> bool:
        item_id = self.line_item_combo.currentData()
        try:
            quantity = dec(self.line_qty_field.text())
        except decimal.InvalidOperation:
            quantity = decimal.Decimal(0)
        if not item_id or quantity <= 0:
            self._status("کالا و مقدار بزرگ‌تر از صفر را وارد کنید.", False)
            return False
        self.lines.append(atp.ScenarioLineFields(item_id, self.kind_combo.currentData(), self.line_date_field.date(), quantity,
                                                 self.line_note_field.text().strip()))
        self.line_qty_field.clear()
        self.line_note_field.clear()
        self._show_lines()
        return True

    def remove_line(self) -> None:
        index = selected_data(self.line_table)
        if index is not None:
            del self.lines[index]
            self._show_lines()

    def save_scenario(self) -> int | None:
        cid = company_id()
        if cid is None:
            return None
        try:
            self.scenario_id = atp.save_scenario(cid, user_id(), self.name_field.text(), self.description_field.text(), list(self.lines),
                                                 self.scenario_id)
        except ValueError as exc:
            self._status(str(exc), False)
            return None
        self._load_scenarios()
        self._status("سناریو ذخیره شد.", True)
        return self.scenario_id

    def delete_scenario(self) -> bool:
        if self.scenario_id is None:
            self._status("یک سناریو را انتخاب کنید.", False)
            return False
        try:
            atp.delete_scenario(company_id(), self.scenario_id)
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self.new_scenario()
        self._load_scenarios()
        self._status("سناریو حذف شد.", True)
        return True

    def run_scenario(self) -> bool:
        if self.scenario_id is None:
            self._status("اول سناریو را ذخیره یا از فهرست انتخاب کنید.", False)
            return False
        try:
            r = self.evaluation = atp.evaluate(company_id(), self.scenario_id, self.horizon_field.value())
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        late = [p for p in r.promises if p.delay_days is None or p.delay_days > 0]
        short_items = [o for o in r.outcomes if o.extra_shortage > 0]
        self.outcome_label.setText(f"از {_date(r.start)} تا {_date(r.end)} | تقاضاهای دیرتر از درخواست یا بی‌تعهد: {P(len(late))} | "
                                   f"کالاهایی که با این سناریو کسری جدید پیدا می‌کنند: {P(len(short_items))}")
        fill(self.promise_table, [[p.item_label, p.wanted, _q(p.quantity), p.promise_date or "در افق نیست",
                                   "—" if p.delay_days is None else P(p.delay_days), _q(p.short_at_wanted)] for p in r.promises])
        fill(self.outcome_table, [[o.item_label, _q(o.base.min_balance), _q(o.scenario.min_balance), _date(o.base.shortage_date),
                                   _date(o.scenario.shortage_date), _q(o.extra_shortage)] for o in r.outcomes])
        danger = QColor(theme.DANGER)
        for i, o in enumerate(r.outcomes):
            if o.extra_shortage > 0:
                self.outcome_table.item(i, 5).setForeground(danger)
        for i, p in enumerate(r.promises):
            if p.delay_days is None or p.delay_days > 0:
                self.promise_table.item(i, 3).setForeground(danger)
        self._status("سناریو اجرا شد.", True)
        return True

    def print_outcome(self) -> bool:
        r = self.evaluation
        if r is None:
            self._status("اول سناریو را اجرا کنید.", False)
            return False
        name = next((s.name for s in self.scenarios if s.scenario_id == self.scenario_id), "")
        rows = [[o.item_label, _q(o.base.min_balance), _q(o.scenario.min_balance), _date(o.base.shortage_date),
                 _date(o.scenario.shortage_date), _q(o.extra_shortage)] for o in r.outcomes]
        report_export.print_report(self, f"اثر سناریوی «{name}»", _OUTCOME_HEADERS, rows,
                                   filters=[("از", _date(r.start)), ("تا", _date(r.end))])
        return True
