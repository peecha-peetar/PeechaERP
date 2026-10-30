"""R383: پیمانکاری فرعی تولید — سپردن دستور به پیمانکار، ارسال مواد، رسید محصول با دستمزد پیمانکار."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_locations as locations_service
from peecha.services.production import subcontracting as sc
from peecha.ui import theme
from peecha.ui.screens.fixed_assets import P, combo, company_id, dec, fill, selected_data, table, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec, build_page_header, set_widget_help


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


def _num(value) -> str:
    return P(f"{decimal.Decimal(value).normalize():f}")


class SubcontractingScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.rows: list = []
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "پیمانکاری تولید", "دستور تولید صادرشده را به پیمانکار بسپارید؛ مواد به انبار نزد پیمانکار منتقل می‌شود و هنگام رسید "
            "محصول از همان‌جا مصرف می‌شود. دستمزد پیمانکار (مقدار × نرخ) به بهای محصول اضافه می‌شود. حساب «دستمزد پیمانکاری "
            "جذب‌شدهٔ تولید» را در تنظیم حساب‌ها همان حساب هزینهٔ خدمات پیمانکار بگذارید تا فاکتور پیمانکار با آن خنثی شود."))

        assign_row = QHBoxLayout()
        self.order_combo, self.party_combo, self.warehouse_combo = combo([]), combo([]), combo([])
        self.fee_field, self.notes_field = QLineEdit(), QLineEdit()
        assign_row.addWidget(FieldGrid([
            FieldSpec("sc_order", "دستور تولید صادرشده", self.order_combo, span=2),
            FieldSpec("sc_party", "پیمانکار", self.party_combo, span=2),
            FieldSpec("sc_warehouse", "انبار نزد پیمانکار", self.warehouse_combo, span=2),
            FieldSpec("sc_fee", "دستمزد هر واحد", self.fee_field, span=1),
            FieldSpec("sc_notes", "شرح کار پیمانکار", self.notes_field, span=2)]), 1)
        assign_btn = _btn("سپردن دستور به پیمانکار", "🤝", "primary")
        assign_btn.clicked.connect(self.assign)
        assign_row.addWidget(assign_btn, 0, Qt.AlignTop)
        layout.addLayout(assign_row)

        self.table = table(["دستور", "محصول", "پیمانکار", "انبار نزد پیمانکار", "برنامه", "دریافت‌شده", "مانده", "دستمزد هر واحد",
                            "جمع دستمزد", "وضعیت"])
        self.table.itemSelectionChanged.connect(self._load_materials)
        layout.addWidget(self.table, 2)

        act = QHBoxLayout()
        self.source_combo = combo([])
        self.quantity_field = QLineEdit()
        self.final_box = QCheckBox("رسید نهایی")
        act.addWidget(FieldGrid([
            FieldSpec("sc_source", "ارسال مواد از انبار", self.source_combo, span=2),
            FieldSpec("sc_qty", "مقدار دریافتی از پیمانکار", self.quantity_field, span=1),
            FieldSpec("sc_final", "پایان کار", self.final_box, span=1)]), 1)
        for label, glyph, kind, slot in (("ارسال کمبود مواد به پیمانکار", "📦", "", self.send),
                                         ("رسید محصول از پیمانکار", "📥", "primary", self.receive),
                                         ("به‌روزرسانی", "🔄", "", self.refresh)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            act.addWidget(button, 0, Qt.AlignTop)
        layout.addLayout(act)
        self.materials_table = table(["کالا", "نیاز کل دستور", "مصرف‌شده", "موجودی نزد پیمانکار"])
        layout.addWidget(self.materials_table, 1)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        for widget, text in (
                (self.warehouse_combo, "انباری که موجودی نزد پیمانکار را نشان می‌دهد؛ مواد دستور از این انبار مصرف می‌شود."),
                (self.fee_field, "دستمزد پیمانکار برای هر واحد محصول؛ با هر رسید به بهای محصول اضافه می‌شود."),
                (self.quantity_field, "مقدار محصول سالمی که پیمانکار تحویل داده است.")):
            set_widget_help(widget, text)

    def _status(self, text: str, ok: bool) -> None:
        theme.set_status_label(self.status_label, text, ok=ok)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.order_combo.clear()
        for o in sc.assignable_orders(cid):
            self.order_combo.addItem(P(f"{o.order_code} — {o.item_label} ({_num(o.planned_qty)})"), o.order_id)
        self.party_combo.clear()
        for s in dimensions_service.list_suppliers(cid):
            self.party_combo.addItem(P(f"{s['code']} — {s['name']}"), s["detail_account_id"])
        warehouses = locations_service.list_warehouses(cid)
        for box in (self.warehouse_combo, self.source_combo):
            box.clear()
            for w in warehouses:
                box.addItem(P(f"{w.code} — {w.name}"), w.warehouse_id)
        selected = selected_data(self.table)
        self.rows = sc.list_subcontracts(cid)
        fill(self.table, [[r.order_code, r.item_label, r.subcontractor, r.warehouse, _num(r.planned_qty), _num(r.produced_qty),
                           _num(r.remaining_qty), r.fee_per_unit, r.fee_total, r.status_label] for r in self.rows],
             [r.order_id for r in self.rows])
        for i, r in enumerate(self.rows):
            if r.order_id == selected:
                self.table.setCurrentCell(i, 0)
        self._load_materials()

    def _load_materials(self) -> None:
        order_id = selected_data(self.table)
        rows = sc.materials(company_id(), order_id) if order_id else []
        fill(self.materials_table, [[m.item_label, _num(m.planned_qty), _num(m.consumed_qty), _num(m.at_subcontractor)] for m in rows])

    def _run(self, action, ok_text: str) -> bool:
        try:
            action()
        except (ValueError, decimal.InvalidOperation) as exc:
            self._status(str(exc) if isinstance(exc, ValueError) else "عدد نامعتبر است.", False)
            return False
        self.refresh()
        self._status(ok_text, True)
        return True

    def assign(self) -> bool:
        order_id = self.order_combo.currentData()
        if order_id is None:
            self._status("دستور تولید صادرشده‌ای برای سپردن نیست.", False)
            return False
        ok = self._run(lambda: sc.assign(company_id(), user_id(), order_id, self.party_combo.currentData(),
                                         self.warehouse_combo.currentData(), dec(self.fee_field.text()), self.notes_field.text()),
                       "دستور به پیمانکار سپرده شد.")
        if ok:
            for i, r in enumerate(self.rows):
                if r.order_id == order_id:
                    self.table.setCurrentCell(i, 0)
        return ok

    def _order(self) -> int | None:
        order_id = selected_data(self.table)
        if order_id is None:
            self._status("یک دستور پیمانکاری را انتخاب کنید.", False)
        return order_id

    def send(self) -> bool:
        order_id = self._order()
        return order_id is not None and self._run(
            lambda: sc.send_materials(company_id(), user_id(), order_id, self.source_combo.currentData()), "مواد به پیمانکار ارسال شد.")

    def receive(self) -> bool:
        order_id = self._order()
        if order_id is None:
            return False
        ok = self._run(lambda: sc.receive(company_id(), user_id(), order_id, dec(self.quantity_field.text()),
                                          final=self.final_box.isChecked()), "محصول از پیمانکار دریافت شد.")
        if ok:
            self.quantity_field.clear()
            self.final_box.setChecked(False)
        return ok
