"""R372: تغییر مهندسی محصول — درخواست تغییر روی نسخهٔ فهرست مواد، اثر تغییر، تایید و اجرا، مقایسهٔ نسخه‌ها و تاریخچهٔ محصول."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services.production import eco
from peecha.services.production import master as pm
from peecha.ui import report_export, theme
from peecha.ui.screens.dms_related import related_documents_button
from peecha.ui.screens.fixed_assets import P, combo, company_id, dec, fill, money, selected_data, set_combo, table, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec, JalaliDateEdit, build_page_header

_LINE_HEADERS = ["ردیف", "نوع تغییر", "جزء", "کالای جایگزین", "مقدار قبلی", "مقدار جدید", "ضایعات جدید", "توضیح"]


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


def _q(value) -> str:
    return P(f"{decimal.Decimal(value).normalize():f}") if value is not None else "—"


def _pct(value) -> str:
    return P(f"{decimal.Decimal(value).normalize():f}٪") if value is not None else "—"


class ProductionEcoScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.ecos: list[eco.EcoRow] = []
        self.lines: list[eco.LineFields] = []
        self.eco_id: int | None = None
        self.ask_reason = None  # برای آزمون: تابعی که دلیل رد یا لغو را برمی‌گرداند
        self._base_lines: dict[int, object] = {}
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "تغییر مهندسی محصول", "هر تغییر در مواد یک محصول (افزودن، تغییر مقدار، جایگزینی یا حذف جزء) با درخواست ثبت می‌شود، "
            "اثرش روی دستورهای باز، موجودی و بهای مواد دیده می‌شود و پس از تایید با اجرای آن نسخهٔ جدید فهرست مواد از تاریخ "
            "اجرا ساخته می‌شود. نسخهٔ قبلی و دستورهای تولید موجود دست نمی‌خورند."))
        top = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItem("همهٔ وضعیت‌ها", None)
        for code, label in eco.STATUSES.items():
            self.status_filter.addItem(label, code)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        top.addWidget(FieldGrid([FieldSpec("eco_status_filter", "وضعیت", self.status_filter, span=1)]), 1)
        for label, glyph, kind, slot in (("درخواست جدید", "🆕", "", self.new_eco), ("به‌روزرسانی فهرست", "🔄", "", self.refresh)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            top.addWidget(button)
        layout.addLayout(top)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        splitter = QSplitter(Qt.Vertical)
        self.eco_table = table(["شماره", "محصول", "عنوان", "نسخهٔ مبنا", "نسخهٔ جدید", "تاریخ اجرا", "علت", "وضعیت", "توضیح تصمیم"])
        self.eco_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.eco_table.itemSelectionChanged.connect(self._load_selected)
        splitter.addWidget(self.eco_table)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_form(), "درخواست")
        self.tabs.addTab(self._build_impact(), "اثر تغییر")
        self.tabs.addTab(self._build_compare(), "مقایسهٔ نسخه‌ها")
        self.tabs.addTab(self._build_history(), "تاریخچهٔ محصول")
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)
        self.tabs.currentChanged.connect(self._tab_changed)
        self._lookups_loaded_for = None

    # --- ساخت زبانه‌ها -----------------------------------------------------------------------------------
    def _build_form(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        self.title_field, self.description_field = QLineEdit(), QLineEdit()
        self.item_combo = combo([])
        self.item_combo.currentIndexChanged.connect(self._item_changed)
        self.base_combo = QComboBox()
        self.base_combo.currentIndexChanged.connect(self._base_changed)
        self.reason_combo, self.disposition_combo = QComboBox(), QComboBox()
        for code, label in eco.REASONS.items():
            self.reason_combo.addItem(label, code)
        for code, label in eco.DISPOSITIONS.items():
            self.disposition_combo.addItem(label, code)
        self.effective_field = JalaliDateEdit()
        v.addWidget(FieldGrid([
            FieldSpec("eco_title", "عنوان", self.title_field, span=2), FieldSpec("eco_item", "محصول", self.item_combo, span=2),
            FieldSpec("eco_base", "نسخهٔ مبنای فهرست مواد", self.base_combo, span=1),
            FieldSpec("eco_effective", "تاریخ اجرا", self.effective_field, span=1),
            FieldSpec("eco_reason", "علت تغییر", self.reason_combo, span=1),
            FieldSpec("eco_disposition", "تکلیف موجودی قدیمی", self.disposition_combo, span=1),
            FieldSpec("eco_description", "شرح تغییر", self.description_field, span=4)]))
        self.action_combo = QComboBox()
        for code, label in eco.ACTIONS.items():
            self.action_combo.addItem(label, code)
        self.action_combo.currentIndexChanged.connect(self._action_changed)
        self.base_line_combo = QComboBox()
        self.component_combo, self.new_item_combo = combo([]), combo([])
        self.qty_field, self.scrap_field, self.line_note_field = QLineEdit(), QLineEdit(), QLineEdit()
        self.scrap_field.setPlaceholderText("بدون تغییر")
        row = QHBoxLayout()
        row.addWidget(FieldGrid([
            FieldSpec("eco_action", "نوع تغییر", self.action_combo, span=1), FieldSpec("eco_base_line", "ردیف فهرست مواد", self.base_line_combo, span=2),
            FieldSpec("eco_component", "جزء جدید", self.component_combo, span=2), FieldSpec("eco_new_item", "کالای جایگزین", self.new_item_combo, span=2),
            FieldSpec("eco_qty", "مقدار جدید", self.qty_field, span=1), FieldSpec("eco_scrap", "درصد ضایعات جدید", self.scrap_field, span=1),
            FieldSpec("eco_line_note", "توضیح ردیف", self.line_note_field, span=2)]), 1)
        for label, glyph, kind, slot in (("افزودن ردیف تغییر", "➕", "", self.add_line), ("برداشتن ردیف انتخاب‌شده", "➖", "danger", self.remove_line)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            row.addWidget(button)
        v.addLayout(row)
        self.line_table = table(_LINE_HEADERS)
        v.addWidget(self.line_table, 1)
        bar = QHBoxLayout()
        for label, glyph, kind, slot in (
                ("ذخیره و ارسال برای تایید", "📤", "primary", lambda: self.save(True)), ("ذخیرهٔ پیش‌نویس", "💾", "", lambda: self.save(False)),
                ("تایید درخواست", "✅", "", self.approve), ("رد درخواست", "❌", "danger", self.reject),
                ("اجرا و ساخت نسخهٔ جدید فهرست مواد", "🚀", "primary", self.implement), ("لغو درخواست", "🚫", "danger", self.cancel),
                ("حذف درخواست", "🗑️", "danger", self.delete), ("چاپ درخواست", "🖨️", "", self.print_eco)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            bar.addWidget(button)
        bar.addWidget(related_documents_button(self, "eco", lambda: self.eco_id))
        bar.addStretch(1)
        v.addLayout(bar)
        self._action_changed()
        return page

    def _build_impact(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        self.impact_label = QLabel("یک درخواست را انتخاب کنید.")
        self.impact_label.setWordWrap(True)
        v.addWidget(self.impact_label)
        tabs = QTabWidget()
        self.impact_orders = table(["دستور تولید", "وضعیت", "مقدار مانده", "موعد"])
        self.impact_components = table(["ردیف", "نوع تغییر", "جزء", "کالای جایگزین", "موجودی فعلی", "مصرف در فهرست‌های دیگر", "هشدار"])
        self.impact_parents = table(["محصول بالادستی", "نسخه", "مقدار مصرف"])
        tabs.addTab(self.impact_orders, "دستورهای باز روی نسخهٔ مبنا")
        tabs.addTab(self.impact_components, "جزءها و موجودی")
        tabs.addTab(self.impact_parents, "محصولات بالادستی")
        v.addWidget(tabs, 1)
        return page

    def _build_compare(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        row = QHBoxLayout()
        self.compare_a, self.compare_b = QComboBox(), QComboBox()
        row.addWidget(FieldGrid([FieldSpec("eco_cmp_a", "نسخهٔ اول", self.compare_a, span=1),
                                 FieldSpec("eco_cmp_b", "نسخهٔ دوم", self.compare_b, span=1)]), 1)
        button = _btn("مقایسه", "⚖️")
        button.clicked.connect(self.compare)
        row.addWidget(button)
        v.addLayout(row)
        self.compare_table = table(["جزء", "مقدار در نسخهٔ اول", "مقدار در نسخهٔ دوم", "ضایعات اول", "ضایعات دوم", "وضعیت"])
        v.addWidget(self.compare_table, 1)
        return page

    def _build_history(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        self.history_table = table(["نسخه", "وضعیت", "پیش‌فرض", "معتبر از", "معتبر تا", "تعداد جزء", "درخواست تغییر", "عنوان تغییر"])
        v.addWidget(self.history_table, 1)
        return page

    # --- داده‌های پایه ---------------------------------------------------------------------------------------
    def _status(self, text: str, ok: bool) -> None:
        theme.set_status_label(self.status_label, text, ok=ok)

    def _load_lookups(self) -> None:
        from peecha.services import inventory_catalog as catalog

        cid = company_id()
        if cid is None or self._lookups_loaded_for == cid:
            return
        self._lookups_loaded_for = cid
        items = catalog.list_items(cid, active_only=True, transactable_only=True)
        options = [(f"{i.code} — {i.name or ''}", i.item_id) for i in items]
        made = set(eco.item_ids_with_bom(cid))
        for box, rows in ((self.item_combo, [o for o in options if o[1] in made]), (self.component_combo, options),
                          (self.new_item_combo, options)):
            box.blockSignals(True)
            box.clear()
            box.addItem("— انتخاب کنید —", None)
            for label, data in rows:
                box.addItem(P(label), data)
            box.blockSignals(False)
        self._item_changed()

    def _item_changed(self) -> None:
        cid, item_id = company_id(), self.item_combo.currentData()
        versions = pm.list_bom_versions(cid, item_id) if cid is not None and item_id else []
        for box in (self.base_combo, self.compare_a, self.compare_b):
            box.blockSignals(True)
            box.clear()
        for v in versions:
            label = P(f"نسخهٔ {v.version_no}") + (" (پیش‌فرض)" if v.is_default else "") + ("" if v.status_code == "ACTIVE" else " (غیرفعال)")
            if v.status_code == "ACTIVE":
                self.base_combo.addItem(label, v.bom_id)
            self.compare_a.addItem(label, v.bom_id)
            self.compare_b.addItem(label, v.bom_id)
        default = next((v.bom_id for v in versions if v.is_default), None)
        if default is not None:
            set_combo(self.base_combo, default)
        if self.compare_b.count() > 1:
            self.compare_a.setCurrentIndex(self.compare_b.count() - 2)
            self.compare_b.setCurrentIndex(self.compare_b.count() - 1)
        for box in (self.base_combo, self.compare_a, self.compare_b):
            box.blockSignals(False)
        self._base_changed()
        self._fill_history()

    def _base_changed(self) -> None:
        cid, bom_id = company_id(), self.base_combo.currentData()
        rows = pm.bom_components(cid, bom_id) if cid is not None and bom_id else []
        self._base_lines = {r.line_no: r for r in rows}
        self.base_line_combo.clear()
        for r in rows:
            self.base_line_combo.addItem(P(f"{r.line_no} — {r.item_label} ({_q(r.quantity)})"), r.line_no)

    def _action_changed(self) -> None:
        action = self.action_combo.currentData()
        self.base_line_combo.setEnabled(action != "ADD")
        self.component_combo.setEnabled(action == "ADD")
        self.new_item_combo.setEnabled(action == "REPLACE")
        self.qty_field.setEnabled(action != "REMOVE")
        self.scrap_field.setEnabled(action != "REMOVE")

    # --- فهرست ---------------------------------------------------------------------------------------------
    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self._load_lookups()
        self.ecos = eco.list_ecos(cid, status=self.status_filter.currentData())
        fill(self.eco_table, [[e.code, e.item_label, e.title, P(e.base_version), P(e.new_version) if e.new_version else "—",
                               e.effective_date, e.reason_label, e.status_label, e.decision_note] for e in self.ecos],
             [e.eco_id for e in self.ecos])
        if self.eco_id is not None:
            row = next((i for i, e in enumerate(self.ecos) if e.eco_id == self.eco_id), None)
            if row is not None:
                self.eco_table.blockSignals(True)
                self.eco_table.setCurrentCell(row, 0)
                self.eco_table.blockSignals(False)

    def open_eco(self, eco_id: int) -> None:
        """از کارتابل: همان درخواست با زبانهٔ اثر تغییر."""
        self.status_filter.setCurrentIndex(0)
        self.refresh()
        row = next((i for i, e in enumerate(self.ecos) if e.eco_id == eco_id), None)
        if row is None:
            return
        self.eco_table.setCurrentCell(row, 0)
        self.tabs.setCurrentIndex(1)

    def _current(self) -> eco.EcoRow | None:
        return next((e for e in self.ecos if e.eco_id == self.eco_id), None)

    def _load_selected(self) -> None:
        eco_id = selected_data(self.eco_table)
        e = next((x for x in self.ecos if x.eco_id == eco_id), None)
        if e is None:
            return
        self.eco_id = e.eco_id
        self.title_field.setText(e.title)
        self.description_field.setText(e.description)
        set_combo(self.item_combo, e.item_id)
        set_combo(self.base_combo, e.base_bom_id)
        set_combo(self.reason_combo, e.reason_code)
        set_combo(self.disposition_combo, e.stock_disposition)
        self.effective_field.setDate(e.effective_date)
        self.lines = [eco.LineFields(ln.action_code, ln.component_item_id if ln.action_code == "ADD" else None, ln.base_line_no,
                                     ln.new_item_id, ln.new_quantity, ln.new_scrap_percent, ln.notes) for ln in e.lines]
        self._show_lines()
        if e.new_bom_id:
            set_combo(self.compare_a, e.base_bom_id)
            set_combo(self.compare_b, e.new_bom_id)
            self.compare()
        self._tab_changed()

    def new_eco(self) -> None:
        self.eco_id = None
        self.eco_table.clearSelection()
        for f in (self.title_field, self.description_field, self.qty_field, self.scrap_field, self.line_note_field):
            f.clear()
        self.reason_combo.setCurrentIndex(0)
        self.disposition_combo.setCurrentIndex(0)
        self.effective_field.setDate(datetime.date.today())
        self.lines = []
        self._show_lines()
        self.impact_label.setText("یک درخواست را انتخاب کنید.")

    # --- ردیف‌ها -------------------------------------------------------------------------------------------
    def _line_view(self, ln: eco.LineFields) -> list:
        base = self._base_lines.get(ln.base_line_no)
        comp = base.item_label if base is not None else self.component_combo.itemText(max(0, self.component_combo.findData(ln.component_item_id)))
        new_item = self.new_item_combo.itemText(self.new_item_combo.findData(ln.new_item_id)) if ln.new_item_id else ""
        return [P(ln.base_line_no) if ln.base_line_no else "جدید", eco.ACTIONS[ln.action_code], comp, new_item,
                _q(base.quantity) if base is not None else "—", _q(ln.new_quantity), _pct(ln.new_scrap_percent), ln.notes]

    def _show_lines(self) -> None:
        fill(self.line_table, [self._line_view(ln) for ln in self.lines], list(range(len(self.lines))))

    def add_line(self) -> bool:
        action = self.action_combo.currentData()
        try:
            quantity = dec(self.qty_field.text()) if self.qty_field.text().strip() and action != "REMOVE" else None
            scrap = dec(self.scrap_field.text()) if self.scrap_field.text().strip() and action != "REMOVE" else None
        except decimal.InvalidOperation:
            self._status("مقدار یا درصد ضایعات نامعتبر است.", False)
            return False
        line = eco.LineFields(action, self.component_combo.currentData() if action == "ADD" else None,
                              self.base_line_combo.currentData() if action != "ADD" else None,
                              self.new_item_combo.currentData() if action == "REPLACE" else None, quantity, scrap,
                              self.line_note_field.text().strip())
        problem = self._line_problem(line)
        if problem:
            self._status(problem, False)
            return False
        self.lines.append(line)
        for f in (self.qty_field, self.scrap_field, self.line_note_field):
            f.clear()
        self._show_lines()
        return True

    def _line_problem(self, line: eco.LineFields) -> str:
        if line.action_code == "ADD" and not line.component_item_id:
            return "کالای جزء جدید را انتخاب کنید."
        if line.action_code != "ADD" and line.base_line_no is None:
            return "ردیف نسخهٔ مبنا را انتخاب کنید."
        if line.action_code == "REPLACE" and not line.new_item_id:
            return "کالای جایگزین را انتخاب کنید."
        if line.action_code == "ADD" and line.new_quantity is None:
            return "مقدار جزء جدید را وارد کنید."
        if line.action_code == "CHANGE" and line.new_quantity is None and line.new_scrap_percent is None:
            return "برای تغییر، مقدار یا درصد ضایعات جدید را وارد کنید."
        if line.base_line_no is not None and any(x.base_line_no == line.base_line_no for x in self.lines):
            return "این ردیف فهرست مواد پیش‌تر در درخواست آمده است."
        return ""

    def remove_line(self) -> None:
        index = selected_data(self.line_table)
        if index is not None:
            del self.lines[index]
            self._show_lines()

    # --- عملیات ---------------------------------------------------------------------------------------------
    def save(self, submit: bool) -> int | None:
        cid = company_id()
        if cid is None:
            return None
        fields = eco.EcoFields(self.title_field.text(), self.item_combo.currentData(), self.base_combo.currentData(),
                               self.effective_field.date(), self.reason_combo.currentData(), self.description_field.text(),
                               self.disposition_combo.currentData(), list(self.lines))
        if not fields.item_id or not fields.base_bom_id:
            self._status("محصول و نسخهٔ مبنای فهرست مواد را انتخاب کنید.", False)
            return None
        try:
            self.eco_id = eco.save_eco(cid, user_id(), fields, self.eco_id, submit=submit)
        except ValueError as exc:
            self._status(str(exc), False)
            return None
        self.refresh()
        self._status("درخواست برای تایید فرستاده شد." if submit else "درخواست ذخیره شد.", True)
        return self.eco_id

    def _selected(self) -> int | None:
        if self.eco_id is None:
            self._status("یک درخواست را از فهرست انتخاب کنید.", False)
        return self.eco_id

    def _ask(self, title: str) -> str | None:
        if self.ask_reason is not None:
            return self.ask_reason()
        text, ok = QInputDialog.getText(self, title, "دلیل:")
        return text if ok else None

    def _do(self, fn, done: str) -> bool:
        eco_id = self._selected()
        if eco_id is None:
            return False
        try:
            result = fn(eco_id)
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self.refresh()
        self._load_selected()
        self._status(done(result) if callable(done) else done, True)
        return True

    def approve(self) -> bool:
        return self._do(lambda i: eco.approve(company_id(), user_id(), i), "درخواست تایید شد؛ اکنون می‌توانید آن را اجرا کنید.")

    def reject(self) -> bool:
        if self._selected() is None:
            return False
        reason = self._ask("رد درخواست")
        return reason is not None and self._do(lambda i: eco.reject(company_id(), user_id(), i, reason), "درخواست رد شد.")

    def cancel(self) -> bool:
        if self._selected() is None:
            return False
        reason = self._ask("لغو درخواست")
        return reason is not None and self._do(lambda i: eco.cancel(company_id(), user_id(), i, reason), "درخواست لغو شد.")

    def implement(self) -> bool:
        ok = self._do(lambda i: eco.implement(company_id(), user_id(), i),
                      lambda _bom: f"نسخهٔ جدید فهرست مواد (نسخهٔ {P(self._current().new_version)}) ساخته شد و از "
                                   f"{numerals.format_jalali_date(max(self._current().effective_date, datetime.date.today()))} معتبر است.")
        if ok:
            self._item_changed()
            current = self._current()
            if current is not None:
                set_combo(self.item_combo, current.item_id)
                set_combo(self.compare_a, current.base_bom_id)
                set_combo(self.compare_b, current.new_bom_id)
                self.compare()
        return ok

    def delete(self) -> bool:
        eco_id = self._selected()
        if eco_id is None:
            return False
        try:
            eco.delete_eco(company_id(), user_id(), eco_id)
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self.new_eco()
        self.refresh()
        self._status("درخواست حذف شد.", True)
        return True

    # --- اثر، مقایسه و تاریخچه ---------------------------------------------------------------------------------
    def _tab_changed(self) -> None:
        if self.tabs.currentIndex() == 1:
            self.show_impact()

    def show_impact(self) -> bool:
        if self.eco_id is None or company_id() is None:
            return False
        r = eco.impact(company_id(), self.eco_id)
        sign = "+" if r.cost_delta > 0 else ""
        self.impact_label.setText(
            f"بهای مواد هر واحد (با میانگین بهای موجودی): پیش از تغییر {money(r.cost_before)} و پس از تغییر {money(r.cost_after)} "
            f"({sign}{money(r.cost_delta)}) | دستورهای باز روی نسخهٔ مبنا: {P(len(r.orders))} | "
            f"جزءهایی که بی‌مصرف می‌مانند: {P(sum(1 for x in r.components if x.obsolete))}")
        fill(self.impact_orders, [[o.order_code, o.status_label, _q(o.remaining_qty), o.due_date] for o in r.orders])
        fill(self.impact_components, [[x.line_no, x.action_label, x.item_label, x.new_item_label, _q(x.on_hand),
                                       "—" if x.used_elsewhere is None else P(x.used_elsewhere),
                                       "موجودی بی‌مصرف می‌ماند" if x.obsolete else ""] for x in r.components])
        fill(self.impact_parents, [[p.item_label, P(p.version_no), _q(p.quantity_per)] for p in r.parents])
        return True

    def compare(self) -> bool:
        a, b = self.compare_a.currentData(), self.compare_b.currentData()
        if company_id() is None or not a or not b:
            return False
        rows = eco.compare_boms(company_id(), a, b)
        fill(self.compare_table, [[r.item_label, _q(r.qty_a), _q(r.qty_b), _pct(r.scrap_a), _pct(r.scrap_b), r.status_label]
                                  for r in rows])
        theme_colors = {"ADDED": theme.SUCCESS, "REMOVED": theme.DANGER, "CHANGED": theme.WARNING}
        for i, r in enumerate(rows):
            if r.status_code in theme_colors:
                self.compare_table.item(i, 5).setForeground(QColor(theme_colors[r.status_code]))
        return True

    def _fill_history(self) -> None:
        cid, item_id = company_id(), self.item_combo.currentData()
        rows = eco.history(cid, item_id) if cid is not None and item_id else []
        fill(self.history_table, [[P(r.version_no), "فعال" if r.status_code == "ACTIVE" else "غیرفعال", "بله" if r.is_default else "",
                                   r.valid_from or "—", r.valid_to or "—", r.component_count, r.eco_code, r.eco_title] for r in rows])

    def print_eco(self) -> bool:
        e = self._current()
        if e is None:
            self._status("یک درخواست را از فهرست انتخاب کنید.", False)
            return False
        rows = [[P(ln.base_line_no) if ln.base_line_no else "جدید", ln.action_label, ln.component_label, ln.new_item_label,
                 _q(ln.old_quantity), _q(ln.new_quantity), _pct(ln.new_scrap_percent), ln.notes] for ln in e.lines]
        head = [("شماره", e.code), ("محصول", e.item_label), ("عنوان", e.title), ("نسخهٔ مبنا", P(e.base_version)),
                ("تاریخ اجرا", numerals.format_jalali_date(e.effective_date)), ("علت", e.reason_label),
                ("تکلیف موجودی قدیمی", eco.DISPOSITIONS[e.stock_disposition]), ("وضعیت", e.status_label)]
        report_export.print_report(self, f"درخواست تغییر مهندسی {e.code}", _LINE_HEADERS, rows, filters=head)
        return True
