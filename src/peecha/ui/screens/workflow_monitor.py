"""پایش فرایندها (R296): اجراهای در جریان و پایان‌یافته، ریز هر اجرا، گلوگاه‌ها و رسیدگی (لغو، تلاش دوباره)."""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget

from peecha import numerals
from peecha.services import roles as roles_service
from peecha.services.workflow import definitions as defs, exceptions as wf_exc, monitor, runtime
from peecha.ui.screens import module_style as ms
from peecha.ui.screens.fixed_assets import P, combo, company_id, date_field, fill, selected_data, table, user_id
from peecha.ui.screens.workflow_center import _ask, _run, _warn, open_entity

ms.ICONS.update({"ریز اجرا": ("🧾", ""), "لغو اجرا": ("🛑", "danger"), "تلاش دوباره": ("🔁", "primary"),
                 "اعمال فیلتر": ("🔍", "")})
_COLORS = {"FAILED": QColor("#EF4444"), "CANCELLED": QColor("#94A3B8"), "COMPLETED": QColor("#10B981")}


def _dt(value) -> str:
    return numerals.format_jalali_datetime(value) if value else "—"


class WorkflowMonitorScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None  # برای تست
        self.rows: list[monitor.RunRow] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)
        title = QLabel("پایش فرایندها")
        title.setObjectName("pageTitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو در عنوان، فرایند یا شروع‌کننده…")
        self.search.returnPressed.connect(self.reload)
        self.status_filter = combo([(label, code) for code, label in monitor.STATUS_FILTERS.items()], "همهٔ وضعیت‌ها")
        self.definition_filter = combo([], "همهٔ فرایندها")
        today = datetime.date.today()
        self.date_from = date_field(today - datetime.timedelta(days=30))
        self.date_to = date_field(today)
        apply_button = ms.style_button(QPushButton("اعمال فیلتر"))
        apply_button.clicked.connect(self.reload)
        outer.addWidget(ms.header_card(title, self.search, self.status_filter, self.definition_filter, QLabel("از"),
                                       self.date_from, QLabel("تا"), self.date_to, apply_button))
        cards, self.cards = ms.summary([
            ("running", "در جریان", "info", "⚙️"), ("waiting", "منتظر اقدام", "warning", "⏳"),
            ("completed", "پایان‌یافته", "success", "✅"), ("failed", "ناموفق", "danger", "❌"),
            ("escalated", "ارجاع‌شده", "warning", "📣"), ("exceptions", "نیازمند بررسی", "danger", "🛠️"),
            ("avg", "میانگین مدت (ساعت)", "neutral", "⏱️"), ("on_time", "پایبندی به مهلت", "success", "🎯")])
        outer.addWidget(cards)
        self.tabs = QTabWidget()
        self.table = table(["فرایند", "سند", "عنوان", "شروع‌کننده", "وضعیت", "نتیجه", "شروع", "مدت (ساعت)", "منتظر"])
        self.table.itemSelectionChanged.connect(self._selected)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self.show_log())
        self.tabs.addTab(self.table, "اجراها")
        self.bottlenecks = table(["فرایند", "مرحله", "تعداد کار", "باز", "میانگین انتظار (ساعت)", "بیشترین انتظار (ساعت)",
                                  "گذشته از مهلت", "ارجاع‌شده"])
        self.tabs.addTab(self.bottlenecks, "گلوگاه‌ها")
        log_box = QWidget()
        log_layout = QVBoxLayout(log_box)
        log_layout.setContentsMargins(0, 0, 0, 0)
        self.log_title = QLabel("یک اجرا را انتخاب کنید.")
        self.log_title.setObjectName("sectionHint")
        self.log = table(["زمان", "گام", "نوع", "وضعیت", "مدت (ساعت)", "انجام‌دهنده", "توضیح"])
        log_layout.addWidget(self.log_title)
        log_layout.addWidget(self.log)
        self.tabs.addTab(log_box, "ریز اجرا")
        outer.addWidget(self.tabs, stretch=1)
        self.buttons = {k: QPushButton(t) for k, t in (
            ("log", "ریز اجرا"), ("open", "بازکردن سند"), ("retry", "تلاش دوباره"), ("cancel", "لغو اجرا"),
            ("refresh", "تازه‌سازی"))}
        self.buttons["log"].clicked.connect(lambda: self.show_log())
        self.buttons["open"].clicked.connect(lambda: self.open_document())
        self.buttons["retry"].clicked.connect(lambda: self.retry())
        self.buttons["cancel"].clicked.connect(lambda: self.cancel())
        self.buttons["refresh"].clicked.connect(lambda: self.reload())
        B = self.buttons
        outer.addWidget(ms.footer([[B["log"], B["open"]], [B["retry"], B["cancel"]], [B["refresh"]]]))

    # --- داده ---------------------------------------------------------------------------------------------------
    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        current = self.definition_filter.currentData()
        self.definition_filter.blockSignals(True)
        self.definition_filter.clear()
        self.definition_filter.addItem("همهٔ فرایندها", None)
        for d in defs.list_definitions(cid):
            self.definition_filter.addItem(d.name, d.definition_id)
        index = self.definition_filter.findData(current)
        self.definition_filter.setCurrentIndex(max(0, index))
        self.definition_filter.blockSignals(False)
        self.reload()

    def reload(self) -> None:
        cid = company_id()
        if cid is None:
            return
        did, d0, d1 = self.definition_filter.currentData(), self.date_from.date(), self.date_to.date()
        o = monitor.overview(cid, d0, d1, did)
        for key, value in (("running", o.running), ("waiting", o.waiting), ("completed", o.completed), ("failed", o.failed),
                           ("escalated", o.escalated), ("exceptions", o.open_exceptions)):
            self.cards[key].setText(P(str(value)))
        self.cards["avg"].setText(P(str(o.avg_hours)) if o.avg_hours is not None else "—")
        self.cards["on_time"].setText(P(f"{o.on_time_rate}٪") if o.on_time_rate is not None else "—")
        self.rows = monitor.runs(cid, status=self.status_filter.currentData(), definition_id=did, date_from=d0, date_to=d1,
                                 search=self.search.text().strip())
        fill(self.table, [[r.definition_name, r.entity_label, r.title, r.started_by,
                           r.status_label + (" — ارجاع‌شده" if r.escalated else "") + (" — نیازمند بررسی" if r.open_exception else ""),
                           r.outcome_label, _dt(r.started_at), P(str(r.hours)) if r.hours is not None else "—", r.waiting_on]
                          for r in self.rows], [r.instance_id for r in self.rows])
        for i, r in enumerate(self.rows):
            color = QColor("#F59E0B") if (r.escalated or r.open_exception) else _COLORS.get(r.status_code)
            if color is not None:
                for col in range(self.table.columnCount()):
                    self.table.item(i, col).setForeground(color)
        rows = monitor.bottleneck_rows(cid, d0, d1)
        fill(self.bottlenecks, [[b["definition"], b["step"], b["tasks"], b["open"],
                                 P(str(b["avg_hours"])) if b["avg_hours"] is not None else "—",
                                 P(str(b["max_hours"])) if b["max_hours"] is not None else "—", b["overdue"], b["escalated"]]
                                for b in rows])
        self._selected()

    def _current(self) -> monitor.RunRow | None:
        iid = selected_data(self.table)
        return next((r for r in self.rows if r.instance_id == iid), None)

    def _selected(self) -> None:
        row = self._current()
        running = bool(row) and row.status_code in ("RUNNING", "WAITING")
        manager = bool(company_id() and user_id()) and roles_service.is_manager(user_id(), company_id())
        self.buttons["log"].setEnabled(row is not None)
        self.buttons["open"].setEnabled(bool(row) and bool(row.entity_id))
        self.buttons["cancel"].setEnabled(running and manager)
        self.buttons["retry"].setEnabled(bool(row) and row.open_exception and manager)

    def open_instance(self, instance_id: int) -> bool:
        """از گزارش‌ها: همان اجرا انتخاب و ریزش نمایش داده می‌شود (حتی اگر بیرون از بازهٔ فیلتر باشد)."""
        self.status_filter.setCurrentIndex(0)
        self.definition_filter.setCurrentIndex(0)
        self.search.clear()
        if company_id() is not None:
            try:
                started = runtime.get_instance(company_id(), instance_id).started_at.astimezone().date()
                if started < self.date_from.date():
                    self.date_from.setDate(started)
            except ValueError:
                return False
        self.reload()
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole) == instance_id:
                self.table.setCurrentCell(r, 0)  # در چیدمان راست‌به‌چپ selectRow چیزی انتخاب نمی‌کند
                self.show_log()
                return True
        return False

    # --- کارها --------------------------------------------------------------------------------------------------
    def show_log(self) -> None:
        row = self._current()
        if row is None:
            return
        self.log_title.setText(f"{row.definition_name} — {row.title}  ({row.status_label})")
        fill(self.log, [[_dt(x.at), x.step, x.kind, x.status, P(str(x.hours)) if x.hours is not None else "", x.actor, x.detail]
                        for x in monitor.execution_log(company_id(), row.instance_id)])
        self.tabs.setCurrentIndex(2)

    def open_document(self) -> None:
        row = self._current()
        if row is not None and not open_entity(self._main_window, row.entity_type, row.entity_id):
            _warn(self, "بازکردن سند", "این اجرا سند قابل بازکردنی ندارد.")

    def cancel(self, reason: str | None = None) -> bool:
        row = self._current()
        if row is None:
            return False
        if reason is None:
            values = _ask(self, "لغو اجرا", [("reason", "دلیل لغو", QLineEdit())],
                          "کارهای باز این اجرا بسته می‌شوند؛ خود سند تغییری نمی‌کند.")
            if values is None:
                return False
            reason = values.get("reason") or ""
        if not reason.strip():
            _warn(self, "لغو اجرا", "دلیل لغو را بنویسید.")
            return False
        _r, ok = _run(self, "لغو اجرا", runtime.cancel_instance, company_id(), row.instance_id, user_id(), reason)
        if ok:
            self.reload()
        return ok

    def retry(self) -> bool:
        row = self._current()
        if row is None:
            return False
        open_ex = [e for e in wf_exc.list_exceptions(company_id()) if e.instance_id == row.instance_id]
        if not open_ex:
            _warn(self, "تلاش دوباره", "این اجرا مورد باز نیازمند بررسی ندارد.")
            return False
        _r, ok = _run(self, "تلاش دوباره", wf_exc.retry, company_id(), open_ex[0].exception_id, user_id(), "تلاش دوباره از پایش")
        if ok:
            self.reload()
        return ok
