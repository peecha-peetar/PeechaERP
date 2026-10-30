"""R371: زمان‌بندی تولید با ظرفیت محدود — دستورها با پایان پیش‌بینی‌شده و دیرکرد، عملیات، بار روزانهٔ مراکز کاری و نمودار گانت."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSpinBox, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services.production import scheduling as sch
from peecha.ui import report_export, theme
from peecha.ui.project_gantt import ZOOMS, GanttChart
from peecha.ui.screens.fixed_assets import P, company_id, fill, table
from peecha.ui.widgets import FieldGrid, FieldSpec, JalaliDateEdit, build_page_header

_ORDER_HEADERS = ["دستور", "کالا", "مقدار مانده", "اولویت", "شروع", "موعد", "پایان پیش‌بینی", "دیرکرد (روز)"]


def _btn(label: str, glyph: str) -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName("iconButton")
    button.setFixedWidth(44)
    button.setCursor(Qt.PointingHandCursor)
    return button


def _hours(value) -> str:
    return P(f"{value.quantize(decimal.Decimal('0.1')).normalize():f}")


class ProductionSchedulingScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.result = None
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "زمان‌بندی با ظرفیت محدود", "عملیات دستورهای باز به‌ترتیب اولویت و موعد روی ظرفیت روزانهٔ هر مرکز کاری (با روزهای کاری، "
            "ماشین‌های خارج از دسترس و توقف‌های برنامه‌ریزی‌شده) چیده می‌شود تا پایان واقعی هر دستور و دیرکردها پیش از وقوع دیده شود. "
            "این فقط شبیه‌سازی است و در دستورها چیزی تغییر نمی‌کند."))
        row = QHBoxLayout()
        self.start_field = JalaliDateEdit()
        self.horizon_field = QSpinBox()
        self.horizon_field.setRange(1, 366)
        self.horizon_field.setValue(30)
        self.rule_combo = QComboBox()
        for code, label in sch.RULES.items():
            self.rule_combo.addItem(label, code)
        row.addWidget(FieldGrid([FieldSpec("sc_start", "از روز", self.start_field, span=1), FieldSpec("sc_days", "افق (روز)", self.horizon_field, span=1),
                                 FieldSpec("sc_rule", "ترتیب دستورها", self.rule_combo, span=1)]), 1)
        for label, glyph, slot in (("اجرای زمان‌بندی", "▶️", self.refresh), ("خروجی Excel دستورها", "📊", self.export_orders),
                                   ("چاپ دستورها", "🖨️", self.print_orders)):
            button = _btn(label, glyph)
            button.clicked.connect(slot)
            row.addWidget(button)
        layout.addLayout(row)
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        self.tabs = QTabWidget()
        self.order_table = table(_ORDER_HEADERS)
        self.tabs.addTab(self.order_table, "دستورها")
        self.op_table = table(["دستور", "ردیف", "عملیات", "مرکز کاری", "ساعت", "شروع", "پایان"])
        self.tabs.addTab(self.op_table, "عملیات")
        self.load_table = table(["مرکز کاری"])
        self.tabs.addTab(self.load_table, "بار روزانهٔ مراکز")
        gantt_page = QWidget()
        g = QVBoxLayout(gantt_page)
        zoom = QHBoxLayout()
        zoom.addWidget(QLabel("مقیاس:"))
        self.zoom_combo = QComboBox()
        for code, (label, _px) in ZOOMS.items():
            self.zoom_combo.addItem(label, code)
        self.zoom_combo.currentIndexChanged.connect(lambda: self.gantt.set_zoom(self.zoom_combo.currentData()))
        zoom.addWidget(self.zoom_combo)
        zoom.addStretch(1)
        g.addLayout(zoom)
        self.gantt = GanttChart()
        scroll = QScrollArea()
        scroll.setWidget(self.gantt)
        scroll.setWidgetResizable(True)
        g.addWidget(scroll, 1)
        self.tabs.addTab(gantt_page, "نمودار گانت")
        layout.addWidget(self.tabs, 1)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        try:
            r = self.result = sch.schedule(cid, self.start_field.date(), self.horizon_field.value(), self.rule_combo.currentData())
        except ValueError as exc:
            theme.set_status_label(self.summary_label, str(exc), ok=False)
            return
        danger = QColor(theme.DANGER)
        fill(self.order_table, [[o.order_code, o.item_label, P(f"{o.quantity.normalize():f}"), o.priority, o.start_date, o.due_date,
                                 o.finish or "خارج از افق", o.late_days if o.late_days is not None else "—"] for o in r.orders],
             [o.order_id for o in r.orders])
        for i, o in enumerate(r.orders):
            if o.finish is None or (o.late_days or 0) > 0:
                for col in (6, 7):
                    self.order_table.item(i, col).setForeground(danger)
        ops = [op for o in r.orders for op in o.ops]
        fill(self.op_table, [[op.order_code, op.seq, op.name, op.work_center or "—", _hours(op.hours), op.start or "—",
                              op.finish or "خارج از افق"] for op in ops])
        self._fill_load(r)
        self.gantt.set_schedule(sch.gantt_rows(r))
        late = r.late
        text = (f"{P(len(r.orders))} دستور باز | {P(len(late))} دستور دیر یا خارج از افق | "
                + " | ".join(f"{name}: {P(r.utilization(wc)) if r.utilization(wc) is not None else '—'}٪"
                             for wc, name in r.centers.items()))
        self.summary_label.setText(text)

    def _fill_load(self, r) -> None:
        days = [r.start + datetime.timedelta(days=i) for i in range((r.end - r.start).days + 1)]
        self.load_table.clear()
        self.load_table.setColumnCount(len(days) + 1)
        self.load_table.setHorizontalHeaderLabels(["مرکز کاری"] + [numerals.format_jalali_date(d)[5:] for d in days])
        self.load_table.setRowCount(len(r.centers))
        danger = QColor(theme.DANGER)
        for row, (wc, name) in enumerate(r.centers.items()):
            self.load_table.setItem(row, 0, QTableWidgetItem(name))
            for col, d in enumerate(days, start=1):
                slot = r.load[wc][d]
                text = "—" if slot.capacity <= 0 else f"{_hours(slot.used)}/{_hours(slot.capacity)}"
                item = QTableWidgetItem(text)
                if slot.capacity > 0 and slot.used >= slot.capacity:
                    item.setForeground(danger)
                self.load_table.setItem(row, col, item)

    def _report(self):
        r = self.result
        rows = [[o.order_code, o.item_label, o.quantity, o.priority, o.start_date, o.due_date, o.finish or "خارج از افق",
                 o.late_days if o.late_days is not None else "—"] for o in r.orders]
        head = [("از روز", numerals.format_jalali_date(r.start)), ("تا روز", numerals.format_jalali_date(r.end)), ("ترتیب", sch.RULES[r.rule])]
        return "زمان‌بندی تولید با ظرفیت محدود", _ORDER_HEADERS, rows, head

    def export_orders(self) -> bool:
        if self.result is None or not self.result.orders:
            return False
        title, headers, rows, head = self._report()
        report_export.export_report_excel(self, title, headers, rows, filters=head)
        return True

    def print_orders(self) -> bool:
        if self.result is None or not self.result.orders:
            return False
        title, headers, rows, head = self._report()
        report_export.print_report(self, title, headers, rows, filters=head)
        return True
