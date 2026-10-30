"""R370: اثربخشی کلی تجهیزات — گزارش تولید شیفت ایستگاه‌ها و داشبورد دسترس‌پذیری، عملکرد، کیفیت و زیان‌ها."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget
from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.production import ProductionOrder, WorkCenter
from peecha.services.production import oee
from peecha.ui import report_export, theme
from peecha.ui.screens.fixed_assets import P, combo, company_id, dec, fill, selected_data, set_combo, table, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec, JalaliDateEdit, KpiCard, build_page_header

_LOG_HEADERS = ["تاریخ", "ایستگاه", "شیفت", "برنامه‌ای (دقیقه)", "توقف (دقیقه)", "تولید کل", "مردود", "دسترس‌پذیری", "عملکرد", "کیفیت", "اثربخشی"]


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


def _bar(*buttons) -> QHBoxLayout:
    row = QHBoxLayout()
    for label, glyph, kind, slot in buttons:
        button = _btn(label, glyph, kind)
        button.clicked.connect(slot)
        row.addWidget(button)
    row.addStretch(1)
    return row


def _pct(value) -> str:
    return P(f"{value:f}٪") if value is not None else "—"


def _q(value) -> str:
    return P(f"{decimal.Decimal(value).normalize():f}")


def _oee_color(value) -> str:
    if value is None:
        return "TEXT_SECONDARY"
    return "SUCCESS" if value >= oee.WORLD_CLASS else ("WARNING" if value >= 60 else "DANGER")


class ProductionOeeScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.logs: list = []
        self.stops: list[oee.Stop] = []
        self.centers: list = []
        self._log_id: int | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "اثربخشی کلی تجهیزات", "برای هر شیفت ایستگاه زمان برنامه‌ای، توقف‌ها با علت، نرخ ایده‌آل، تولید کل و مردود را ثبت کنید "
            "(پیشنهاد خودکار از توقف‌های نگهداری و عملیات دستورهای تولید). اثربخشی = دسترس‌پذیری × عملکرد × کیفیت؛ معیار جهانی ۸۵٪."))
        self.tabs = QTabWidget()
        self.tabs.addTab(self._entry_tab(), "گزارش شیفت")
        self.dashboard_tab = self._dashboard_tab()
        self.tabs.addTab(self.dashboard_tab, "داشبورد اثربخشی")
        layout.addWidget(self.tabs, 1)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def _status(self, text: str, ok: bool) -> None:
        theme.set_status_label(self.status_label, text, ok=ok)

    # --- گزارش شیفت ---------------------------------------------------------------------------------------------------
    def _entry_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.wc_combo = combo([], "—")
        self.day_field = JalaliDateEdit()
        self.shift_field = QSpinBox()
        self.shift_field.setRange(1, 3)
        self.planned_field = QSpinBox()
        self.planned_field.setRange(0, 1440)
        self.rate_field, self.total_field, self.reject_field, self.notes_field = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.order_combo = combo([], "—")
        v.addWidget(FieldGrid([
            FieldSpec("oee_wc", "ایستگاه (مرکز کاری)", self.wc_combo, span=1), FieldSpec("oee_day", "روز", self.day_field, span=1),
            FieldSpec("oee_shift", "شیفت", self.shift_field, span=1), FieldSpec("oee_planned", "زمان برنامه‌ای (دقیقه)", self.planned_field, span=1),
            FieldSpec("oee_rate", "نرخ ایده‌آل (واحد در ساعت)", self.rate_field, span=1), FieldSpec("oee_order", "دستور تولید (اختیاری)", self.order_combo, span=1),
            FieldSpec("oee_total", "تولید کل", self.total_field, span=1), FieldSpec("oee_reject", "مردود", self.reject_field, span=1),
            FieldSpec("oee_notes", "یادداشت", self.notes_field, span=1)]))
        stop_row = QHBoxLayout()
        self.reason_combo = QComboBox()
        for code, label in oee.REASONS.items():
            self.reason_combo.addItem(label, code)
        self.stop_minutes = QSpinBox()
        self.stop_minutes.setRange(1, 1440)
        self.stop_note = QLineEdit()
        stop_row.addWidget(FieldGrid([FieldSpec("st_reason", "علت توقف", self.reason_combo, span=1),
                                      FieldSpec("st_minutes", "دقیقه", self.stop_minutes, span=1),
                                      FieldSpec("st_note", "توضیح", self.stop_note, span=1)]), 1)
        for label, glyph, kind, slot in (("افزودن توقف", "➕", "", self.add_stop), ("برداشتن توقف انتخاب‌شده", "➖", "danger", self.remove_stop)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            stop_row.addWidget(button)
        v.addLayout(stop_row)
        self.stop_table = table(["علت", "دقیقه", "توضیح"])
        self.stop_table.setMaximumHeight(130)
        v.addWidget(self.stop_table)
        self.preview_label = QLabel("")
        v.addWidget(self.preview_label)
        v.addLayout(_bar(("پیشنهاد از توقف‌های نگهداری و عملیات تولید", "🪄", "", self.suggest),
                         ("ذخیرهٔ گزارش شیفت", "💾", "primary", self.save_log), ("گزارش جدید", "🆕", "", self.new_log),
                         ("حذف گزارش", "🗑️", "danger", self.delete_log), ("به‌روزرسانی", "🔄", "", self.refresh)))
        self.log_table = table(_LOG_HEADERS)
        self.log_table.itemSelectionChanged.connect(self._load_log)
        v.addWidget(self.log_table, 1)
        return w

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        with new_session() as session:
            centers = [(f"{w.code} — {w.name}", w.work_center_id) for w in session.scalars(select(WorkCenter).where(
                WorkCenter.company_id == cid, WorkCenter.is_active.is_(True)).order_by(WorkCenter.code))]
            orders = [(o.order_code, o.order_id) for o in session.scalars(select(ProductionOrder).where(
                ProductionOrder.company_id == cid, ProductionOrder.status_code.in_(("RELEASED", "IN_PROGRESS", "ON_HOLD", "COMPLETED")))
                .order_by(ProductionOrder.order_id.desc()).limit(300))]
        for box, items in ((self.wc_combo, centers), (self.order_combo, orders)):
            current = box.currentData()
            box.clear()
            box.addItem("—", None)
            for label, data in items:
                box.addItem(P(label), data)
            set_combo(box, current)
        today = datetime.date.today()
        self.logs = oee.list_logs(cid, today - datetime.timedelta(days=60), today)
        fill(self.log_table, [self._log_row(r) for r in self.logs], [r.log_id for r in self.logs])
        for i, r in enumerate(self.logs):
            self.log_table.item(i, 10).setForeground(QColor(getattr(theme, _oee_color(r.metrics.oee))))
        self.refresh_dashboard()

    @staticmethod
    def _log_row(r) -> list:
        m = r.metrics
        return [r.log_date, r.work_center, r.shift_no, _q(m.planned_minutes), _q(m.downtime_minutes), _q(m.total_qty), _q(m.reject_qty),
                _pct(m.availability), _pct(m.performance), _pct(m.quality), _pct(m.oee)]

    def _show_stops(self) -> None:
        fill(self.stop_table, [[oee.REASONS[s.reason_code], s.minutes, s.note] for s in self.stops], list(range(len(self.stops))))
        down = sum(s.minutes for s in self.stops)
        self.preview_label.setText(f"جمع توقف: {P(down)} دقیقه")

    def add_stop(self) -> None:
        self.stops.append(oee.Stop(self.reason_combo.currentData(), self.stop_minutes.value(), self.stop_note.text()))
        self.stop_note.clear()
        self._show_stops()

    def remove_stop(self) -> None:
        index = selected_data(self.stop_table)
        if index is not None:
            del self.stops[index]
            self._show_stops()

    def _fill_fields(self, f: oee.LogFields) -> None:
        set_combo(self.wc_combo, f.work_center_id)
        self.day_field.setDate(f.log_date)
        self.shift_field.setValue(f.shift_no)
        self.planned_field.setValue(int(f.planned_minutes))
        self.rate_field.setText(_q(f.ideal_rate_per_hour) if f.ideal_rate_per_hour else "")
        self.total_field.setText(_q(f.total_qty))
        self.reject_field.setText(_q(f.reject_qty))
        set_combo(self.order_combo, f.order_id)
        self.notes_field.setText(f.notes or "")
        self.stops = list(f.stops)
        self._show_stops()

    def suggest(self) -> bool:
        if self.wc_combo.currentData() is None:
            self._status("ایستگاه را انتخاب کنید.", False)
            return False
        try:
            f = oee.suggest(company_id(), self.wc_combo.currentData(), self.day_field.date(), self.shift_field.value())
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self._fill_fields(f)
        self._status("مقدارهای پیشنهادی آمد؛ بررسی و در صورت نیاز اصلاح کنید و ذخیره کنید." if f.planned_minutes
                     else "این روز برای این ایستگاه روز کاری نیست.", True)
        return True

    def _load_log(self) -> None:
        r = next((x for x in self.logs if x.log_id == selected_data(self.log_table)), None)
        if r is None:
            return
        self._log_id = r.log_id
        m = r.metrics
        self._fill_fields(oee.LogFields(r.work_center_id, r.log_date, int(m.planned_minutes), r.ideal_rate_per_hour, m.total_qty,
                                        m.reject_qty, r.shift_no, r.order_id, r.notes, r.stops))

    def new_log(self) -> None:
        self._log_id = None
        self.log_table.clearSelection()
        for f in (self.rate_field, self.total_field, self.reject_field, self.notes_field):
            f.clear()
        self.planned_field.setValue(0)
        self.stops = []
        self._show_stops()

    def save_log(self) -> int | None:
        if self.wc_combo.currentData() is None:
            self._status("ایستگاه را انتخاب کنید.", False)
            return None
        try:
            fields = oee.LogFields(self.wc_combo.currentData(), self.day_field.date(), self.planned_field.value(),
                                   dec(self.rate_field.text()) if self.rate_field.text().strip() else None, dec(self.total_field.text()),
                                   dec(self.reject_field.text()), self.shift_field.value(), self.order_combo.currentData(),
                                   self.notes_field.text(), list(self.stops))
            log_id = oee.save_log(company_id(), user_id(), fields, self._log_id)
        except (ValueError, decimal.InvalidOperation) as exc:
            self._status(str(exc) if isinstance(exc, ValueError) else "عدد واردشده نامعتبر است.", False)
            return None
        self.new_log()
        self.refresh()
        saved = next((r for r in self.logs if r.log_id == log_id), None)
        self._status(f"گزارش ذخیره شد؛ اثربخشی این شیفت {_pct(saved.metrics.oee) if saved else '—'}.", True)
        return log_id

    def delete_log(self) -> bool:
        if self._log_id is None:
            self._status("یک گزارش را از جدول انتخاب کنید.", False)
            return False
        oee.delete_log(company_id(), self._log_id)
        self.new_log()
        self.refresh()
        self._status("گزارش حذف شد.", True)
        return True

    # --- داشبورد ------------------------------------------------------------------------------------------------------
    def _dashboard_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.from_field, self.to_field = JalaliDateEdit(), JalaliDateEdit()
        self.from_field.setDate(datetime.date.today() - datetime.timedelta(days=30))
        row.addWidget(FieldGrid([FieldSpec("d_from", "از تاریخ", self.from_field, span=1), FieldSpec("d_to", "تا تاریخ", self.to_field, span=1)],
                                columns=2), 1)
        for label, glyph, slot in (("نمایش", "🔎", self.refresh_dashboard), ("خروجی Excel", "📊", self.export_dashboard)):
            button = _btn(label, glyph)
            button.clicked.connect(slot)
            row.addWidget(button)
        v.addLayout(row)
        cards = QHBoxLayout()
        self.cards = {"oee": KpiCard("اثربخشی کل", "🏭", theme.ACCENT), "availability": KpiCard("دسترس‌پذیری", "⏱️", theme.INFO),
                      "performance": KpiCard("عملکرد", "⚡", theme.CHART_PURPLE), "quality": KpiCard("کیفیت", "✅", theme.SUCCESS)}
        for card in self.cards.values():
            cards.addWidget(card)
        v.addLayout(cards)
        self.center_table = table(["ایستگاه", "گزارش‌ها", "دسترس‌پذیری", "عملکرد", "کیفیت", "اثربخشی", "تولید سالم", "بیشترین توقف"])
        v.addWidget(self.center_table, 1)
        v.addWidget(QLabel("زیان‌های زمانی (دقیقه)"))
        self.loss_table = table(["زیان", "دقیقه"])
        self.loss_table.setMaximumHeight(220)
        v.addWidget(self.loss_table)
        return w

    def refresh_dashboard(self) -> None:
        cid = company_id()
        if cid is None:
            return
        total, self.centers = oee.summary(cid, self.from_field.date(), self.to_field.date())
        for key in ("oee", "availability", "performance", "quality"):
            self.cards[key].set_value(_pct(getattr(total, key)))
        rows = []
        for c in self.centers:
            top = max(c.losses.items(), key=lambda kv: kv[1], default=None)
            rows.append([c.work_center, c.logs, _pct(c.metrics.availability), _pct(c.metrics.performance), _pct(c.metrics.quality),
                         _pct(c.metrics.oee), _q(c.metrics.good_qty), f"{oee.REASONS[top[0]]} ({_q(top[1])})" if top else "—"])
        fill(self.center_table, rows, [c.work_center_id for c in self.centers])
        for i, c in enumerate(self.centers):
            self.center_table.item(i, 5).setForeground(QColor(getattr(theme, _oee_color(c.metrics.oee))))
        fill(self.loss_table, [[name, _q(minutes)] for name, minutes in oee.losses(cid, self.from_field.date(), self.to_field.date())])

    def export_dashboard(self) -> bool:
        if not self.centers:
            return False
        headers = ["ایستگاه", "گزارش‌ها", "دسترس‌پذیری", "عملکرد", "کیفیت", "اثربخشی", "تولید سالم"]
        rows = [[c.work_center, c.logs, _pct(c.metrics.availability), _pct(c.metrics.performance), _pct(c.metrics.quality),
                 _pct(c.metrics.oee), _q(c.metrics.good_qty)] for c in self.centers]
        report_export.export_report_excel(self, "اثربخشی کلی تجهیزات", headers, rows)
        return True
