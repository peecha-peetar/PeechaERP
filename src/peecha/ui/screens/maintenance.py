"""صفحه‌های نگهداری و تعمیرات — R312.

داشبورد، صف درخواست‌ها، تابلوی دستور کار و پروندهٔ دستور کار، نگهداری پیشگیرانه و تقویم، تجهیزات و کارت تجهیز،
توقف‌ها و ظرفیت ماشین، تنظیمات. همهٔ منطق در services/maintenance است؛ اینجا فقط نمایش و فراخوانی.
"""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt, QTime
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTimeEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from peecha import decimals, numerals
from peecha.services import stock_controls
from peecha.services.maintenance import availability as av
from peecha.services.maintenance import common as c
from peecha.services.maintenance import costs as mcost
from peecha.services.maintenance import documents as mdocs
from peecha.services.maintenance import equipment as eq
from peecha.services.maintenance import parts as mparts
from peecha.services.maintenance import pm as mpm
from peecha.services.maintenance import requests as mreq
from peecha.services.maintenance import work_orders as wos
from peecha.ui import theme
from peecha.ui.screens import module_style as ms
from peecha.ui.screens.costing import can
from peecha.ui.screens.fixed_assets import (
    FormDialog, P, combo, company_id, date_field, fill, num_field, scrolled, set_combo, table, user_id,
)
from peecha.ui.screens.quality import (
    _confirm, _date, _exec, _hint, _open_report, _qty, _run, _selected, _text, _title, _warn,
)
from peecha.ui.widgets import FieldHelpMixin, JalaliDateEdit

ms.ICONS.update({
    # درخواست
    "درخواست جدید": ("📝", "primary"), "بررسی و اولویت": ("🔍", ""), "ارجاع": ("📨", ""), "تأیید درخواست": ("✅", ""),
    "تبدیل به دستور کار": ("🧰", "primary"), "رد درخواست": ("❌", "danger"), "لغو درخواست": ("🚫", "danger"),
    "پیوست": ("📎", ""), "تاریخچه": ("🕘", ""), "آماده‌به‌کاری بدون دستور کار": ("🟢", ""),
    # دستور کار
    "دستور کار جدید": ("🆕", "primary"), "باز کردن دستور کار": ("📂", ""), "ساخت دستورهای پیشگیرانهٔ سررسید": ("🗓️", ""),
    "برنامه‌ریزی": ("📅", ""), "واگذاری به تکنسین": ("👷", ""), "شروع کار": ("▶️", "primary"), "توقف موقت": ("⏸️", ""),
    "ادامهٔ کار": ("⏯️", ""), "ثبت انجام کار": ("🏁", "primary"), "آزمون و تأیید": ("🛡️", "primary"),
    "آماده‌به‌کاری ماشین": ("🟢", "primary"), "بستن دستور کار": ("🔒", ""), "بازگشایی دستور کار": ("🔓", ""),
    "لغو دستور کار": ("🚫", "danger"), "ثبت نتیجهٔ چک‌لیست": ("☑️", ""), "ردیف چک‌لیست جدید": ("➕", ""),
    "ثبت ساعت کار": ("⏱️", ""), "افزودن قطعه": ("➕", ""), "رزرو قطعه": ("📌", ""), "صدور قطعه": ("📤", "primary"),
    "برگشت قطعه": ("↩️", ""), "درخواست خرید کمبود": ("🛒", ""), "هزینهٔ جدید": ("💵", ""),
    "ثبت مالی هزینه": ("🧾", "primary"), "اتصال به فاکتور خرید": ("🔗", ""), "بدون ثبت مالی": ("🚫", ""),
    "لغو هزینه": ("🗑️", "danger"),
    # نگهداری پیشگیرانه
    "برنامهٔ جدید": ("🆕", "primary"), "ویرایش برنامه": ("✏️", ""), "درخواست تعویق": ("⏩", ""),
    "تأیید تعویق": ("✅", ""), "رد تعویق": ("❌", "danger"), "ثبت کارکرد": ("🔢", ""), "افزودن ردیف": ("➕", ""),
    "حذف ردیف": ("🗑️", "danger"), "نمایش تقویم": ("🗓️", ""),
    # تجهیزات
    "مشخصات نگهداری": ("⚙️", "primary"), "درخواست تعمیر این تجهیز": ("📝", ""), "کدهای خرابی": ("🏷️", ""),
    "کد جدید": ("➕", ""), "ذخیرهٔ برچسب QR": ("🔳", ""), "جستجوی کد یا برچسب": ("🔎", ""),
    # دسترس‌پذیری
    "توقف برنامه‌ریزی‌شدهٔ جدید": ("🗓️", "primary"), "تأیید توقف": ("✅", ""), "لغو توقف": ("🚫", "danger"),
    "ظرفیت محدود جدید": ("📉", ""), "تأیید محدودیت": ("✅", ""), "لغو محدودیت": ("🚫", "danger"),
    "پایان محدودیت": ("🏁", ""),
    # تنظیمات
    "ساخت نقش‌های آمادهٔ نگهداری": ("👥", "primary"),
})

_RED, _AMBER, _GREEN, _GREY = QColor("#EF4444"), QColor("#F59E0B"), QColor("#10B981"), QColor("#94A3B8")
_PRIORITY_TONE = {"URGENT": _RED, "HIGH": _AMBER}
_STATE_TONE = {"OVERDUE": _RED, "DUE": _AMBER, "NO_DATA": _GREY}
_MNT_TOGGLES = stock_controls.MNT_ALL


# --- کمکی‌ها ---------------------------------------------------------------------------------------
class DateTimeField(QWidget):
    """تاریخ شمسی + ساعت (زمان وقوع خرابی، شروع و پایان کار)."""

    def __init__(self, value: datetime.datetime | None = None) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        value = (value or datetime.datetime.now()).astimezone()
        self.date = JalaliDateEdit()
        self.date.setDate(value.date())
        self.time = QTimeEdit(QTime(value.hour, value.minute))
        self.time.setDisplayFormat("HH:mm")
        row.addWidget(self.date, stretch=1)
        row.addWidget(self.time)

    def value(self) -> datetime.datetime:
        t = self.time.time()
        return datetime.datetime.combine(self.date.date(), datetime.time(t.hour(), t.minute())).astimezone()


def _ask(parent, title: str, fields, hint: str = "") -> dict | None:
    """همان فرم کوچک عملیات + خواندن فیلد تاریخ و ساعت."""
    dlg = FormDialog(title, fields, hint, parent)
    if not _exec(parent, dlg):
        return None
    values = dlg.values()
    for key, w in dlg.widgets.items():
        if isinstance(w, DateTimeField):
            values[key] = w.value()
    return values


def _btns(owner, specs) -> dict[str, QPushButton]:
    out = {}
    for key, text, slot in specs:
        b = QPushButton(text)
        b.clicked.connect(lambda _c=False, f=slot: f())
        out[key] = b
    owner.buttons = {**getattr(owner, "buttons", {}), **out}
    return out


def _tone(t: QTableWidget, row: int, color: QColor | None) -> None:
    if color is None:
        return
    for col in range(t.columnCount()):
        item = t.item(row, col)
        if item is not None:
            item.setForeground(color)


def _dt(value) -> str:
    if isinstance(value, datetime.datetime):
        return numerals.format_jalali_datetime(value)
    return _date(value) if value is not None else "—"


def _hours(value) -> str:
    return "—" if value is None else f"{decimals.format_qty(value)} ساعت"


class _Lookups:
    """فهرست‌های مشترک صفحه‌های نگهداری (یک بار در هر refresh)."""

    def __init__(self, cid: int) -> None:
        from peecha.services import chart_of_accounts as coa
        from peecha.services import detail_dimensions as dims
        from peecha.services import inventory_catalog as catalog
        from peecha.services import inventory_locations as locations
        from peecha.services.crm.common import list_company_users

        self.equipment = [(e.label, e.asset_id) for e in eq.list_equipment(cid)]
        self.users = [(name, uid) for uid, name in list_company_users(cid)]
        self.items = [(f"{i.code} — {i.name or ''}", i.item_id) for i in catalog.list_items(cid, transactable_only=True)]
        self.warehouses = [(f"{w.code} — {w.name}", w.warehouse_id) for w in locations.list_warehouses(cid, active_only=True)]
        self.suppliers = [(f"{s['code']} — {s['name'] or ''}", s["detail_account_id"]) for s in dims.list_suppliers(cid)]
        self.accounts = [(f"{a.full_code} — {a.name}", a.account_id) for a in coa.list_postable_accounts(cid)]
        codes = eq.list_failure_codes(cid, active_only=True)
        self.codes = {k: [(f.label, f.failure_code_id) for f in codes if f.kind_code == k] for k in c.FAILURE_KIND_LABELS}


def _labels(mapping: dict) -> list[tuple[str, str]]:
    return [(v, k) for k, v in mapping.items()]


# =========================================================================================================
# داشبورد
# =========================================================================================================
def _dashboard_base():
    from peecha.ui.screens.purchase_dashboards import _ProcurementDashboardBase

    return _ProcurementDashboardBase


class MntDashboardScreen(_dashboard_base()):
    TITLE = "داشبورد نگهداری و تعمیرات"
    _KPI_STYLE = {"DOWN_NOW": ("⛔", "DANGER"), "NEW_REQUESTS": ("📝", "WARNING"), "OPEN_WO": ("🧰", "ACCENT"),
                  "AWAITING_TEST": ("🛡", "CHART_PURPLE"), "MTTR": ("⏱", "ACCENT"), "MTBF": ("📈", "SUCCESS"),
                  "AVAILABILITY": ("✔", "SUCCESS"), "DOWNTIME": ("⏸", "DANGER"), "PM_SHARE": ("🗓", "CHART_TEAL"),
                  "PM_COMPLIANCE": ("🎯", "CHART_TEAL"), "ON_TIME": ("⌛", "ACCENT"), "FAILURE_RATE": ("⚠", "CHART_ORANGE"),
                  "COST": ("💸", "CHART_ORANGE"), "PENDING_COST": ("🧾", "WARNING"), "BACKLOG": ("📚", "CHART_PURPLE")}

    def __init__(self, main_window=None) -> None:
        super().__init__(main_window)
        from peecha.services.maintenance import dashboard as mdash
        from peecha.ui.screens.dashboard import build_chart_card
        from peecha.ui.screens.purchase_dashboards import _ClickableKpiCard

        self.cards, self._kpis = {}, {}
        grid = QGridLayout()
        grid.setSpacing(14)
        for i, (code, (icon, color)) in enumerate(self._KPI_STYLE.items()):
            card = _ClickableKpiCard("", icon, getattr(theme, color), lambda k=code: self._open_kpi(k))
            self.cards[code] = card
            grid.addWidget(card, i // 5, i % 5)
        self.body_layout.addLayout(grid)
        title = QLabel("هشدارها")
        title.setObjectName("cardTitle")
        self.body_layout.addWidget(title)
        self.alerts_table = table(["سطح", "هشدار", "شرح"])
        self.alerts_table.setMaximumHeight(220)
        self.alerts_table.cellDoubleClicked.connect(self._open_alert)
        self.body_layout.addWidget(self.alerts_table)
        charts = QGridLayout()
        self.chart_views = {}
        for i, (key, chart_title, _report, _options) in enumerate(mdash.CHART_TITLES):
            card, view = build_chart_card(chart_title)
            view.setMinimumHeight(240)
            self.chart_views[key] = view
            charts.addWidget(card, i // 2, i % 2)
        self.body_layout.addLayout(charts)
        self._alerts = []
        ms.apply(self)

    def refresh(self) -> None:
        today = datetime.date.today()
        self.date_from.setDate(today - datetime.timedelta(days=90))
        self.date_to.setDate(today)
        self.reload()

    def _open_kpi(self, code: str) -> None:
        kpi = self._kpis.get(code)
        if kpi is not None:
            _open_report(self._main_window, kpi.report_code, self.date_from.date(), self.date_to.date(), kpi.options)

    def _open_alert(self, row: int, _col: int) -> None:
        if self._main_window is None or row >= len(self._alerts):
            return
        kind = self._alerts[row].ref[0]
        target = {"EQUIPMENT": "MNT_AVAILABILITY", "REQUEST": "MNT_REQUEST_QUEUE", "PM": "MNT_PM",
                  "AVAILABILITY": "MNT_AVAILABILITY"}[kind]
        self._main_window.open_screen(target)

    def reload(self) -> None:
        from peecha.services.maintenance import dashboard as mdash
        from peecha.ui.screens.dashboard import render_donut_chart
        from peecha.ui.screens.purchase_dashboards import format_kpi
        from peecha.ui.screens.warehouse_dashboard import render_series_chart

        cid = self._company_id()
        if cid is None:
            return
        kpis, charts, alerts = mdash.dashboard(cid, self.date_from.date(), self.date_to.date())
        self._kpis = {k.code: k for k in kpis}
        for code, kpi in self._kpis.items():
            card = self.cards[code]
            card._title_label.setText(kpi.title)
            if kpi.value is None:
                text = "داده ناکافی"
            elif kpi.kind == "HOURS":
                text = P(decimals.format_qty(kpi.value))
            else:
                text = format_kpi(kpi.value, kpi.kind, decimals.money_decimals())
            card.set_value(text)
            card.setToolTip(f"تعریف: {kpi.formula}\nکلیک: گزارش مبدا")
        self._alerts = alerts
        level = {"RED": "🔴", "YELLOW": "🟡", "ORANGE": "🟠"}
        fill(self.alerts_table, [[level[mdash.ALERT_LEVEL[a.kind]], mdash.ALERT_LABELS[a.kind], a.text] for a in alerts])
        for key, data in charts.items():
            if data["kind"] == "donut":
                render_donut_chart(self.chart_views[key], [(P(lb), v) for lb, v in zip(data["labels"], data["series"]["تعداد"]) if v])
            else:
                render_series_chart(self.chart_views[key], [P(x) for x in data["labels"]], data["series"])


# =========================================================================================================
# صف درخواست‌ها
# =========================================================================================================
@ms.styled
class RequestQueueScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.rows: list = []
        self.lk: _Lookups | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        self.status = combo([("باز (جدید، در حال بررسی، تأییدشده)", "OPEN")] + _labels(c.REQUEST_STATUS_LABELS))
        self.status.currentIndexChanged.connect(lambda _i: self.reload())
        self.mine = QCheckBox("فقط ارجاع‌شده به من")
        self.mine.toggled.connect(lambda _v: self.reload())
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو: تجهیز، کد یا شرح خرابی")
        self.search.returnPressed.connect(self.reload)
        outer.addWidget(ms.header_card(_title("درخواست‌های تعمیر"), self.status, self.mine, self.search))
        cards, self.cards = ms.summary([("new", "جدید", "warning", "📝"), ("review", "در حال بررسی", "info", "🔍"),
                                        ("stopped", "ماشین متوقف", "danger", "⛔"), ("approved", "تأییدشده، منتظر دستور کار", "success", "✅")])
        outer.addWidget(cards)
        self.t = table(["شماره", "تاریخ گزارش", "تجهیز", "شرح", "شدت", "اولویت", "ماشین متوقف", "وضعیت", "گزارش‌دهنده",
                        "ارجاع به", "منبع", "دستور کار"])
        self.t.cellDoubleClicked.connect(lambda _r, _c: self.show_history())
        self.t.itemSelectionChanged.connect(self._show_detail)
        outer.addWidget(self.t, stretch=1)
        self.detail = _hint("")
        outer.addWidget(self.detail)
        b = _btns(self, [("new", "درخواست جدید", self.new_request), ("evaluate", "بررسی و اولویت", self.evaluate),
                         ("refer", "ارجاع", self.refer), ("approve", "تأیید درخواست", self.approve),
                         ("convert", "تبدیل به دستور کار", self.convert), ("reject", "رد درخواست", self.reject),
                         ("cancel", "لغو درخواست", self.cancel), ("attach", "پیوست", self.attach),
                         ("history", "تاریخچه", self.show_history), ("release", "آماده‌به‌کاری بدون دستور کار", self.release),
                         ("refresh", "به‌روزرسانی", self.refresh),
                         ("report", "گزارش کامل", lambda: _open_report(self._main_window, "MNT_REQUESTS"))])
        outer.addWidget(ms.footer([[b["new"]], [b["evaluate"], b["refer"], b["approve"], b["convert"]],
                                   [b["reject"], b["cancel"], b["release"]], [b["attach"], b["history"], b["refresh"], b["report"]]]))
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.lk = _Lookups(cid)
        uid = user_id()
        self.buttons["new"].setEnabled(c.can(cid, uid, c.FORM_REQUEST, "CREATE") and can("mnt_requests", "CREATE"))
        for key in ("evaluate", "refer", "approve", "convert", "reject"):
            self.buttons[key].setEnabled(c.can(cid, uid, c.FORM_PLAN))
        self.buttons["release"].setEnabled(c.can(cid, uid, c.FORM_VERIFY))
        self.reload()

    def reload(self) -> None:
        cid = company_id()
        if cid is None:
            return
        st = self.status.currentData()
        statuses = ("NEW", "UNDER_REVIEW", "APPROVED") if st == "OPEN" else (st,)
        self.rows = mreq.queue(cid, statuses=statuses, assigned_to_user_id=user_id() if self.mine.isChecked() else None,
                               search=self.search.text().strip() or None)
        fill(self.t, [[P(r.request_no), _dt(r.reported_at), r.asset_label, r.title, r.severity_label, r.priority_label,
                       "بله — هنوز متوقف" if r.machine_down_now else ("بله" if r.machine_stopped else "خیر"), r.status_label,
                       r.reported_by, r.assigned_to, r.source_label, "دارد" if r.work_order_id else ""] for r in self.rows],
             [r.request_id for r in self.rows])
        for i, r in enumerate(self.rows):
            _tone(self.t, i, _RED if r.machine_down_now else _PRIORITY_TONE.get(r.priority_code))
        allr = mreq.queue(cid)
        self.cards["new"].setText(P(sum(1 for r in allr if r.status_code == "NEW")))
        self.cards["review"].setText(P(sum(1 for r in allr if r.status_code == "UNDER_REVIEW")))
        self.cards["stopped"].setText(P(sum(1 for r in allr if r.machine_down_now)))
        self.cards["approved"].setText(P(sum(1 for r in allr if r.status_code == "APPROVED")))

    def _current(self):
        rid = _selected(self.t)
        return next((r for r in self.rows if r.request_id == rid), None)

    def _show_detail(self) -> None:
        r = self._current()
        if r is None:
            self.detail.setText("")
            return
        parts = [f"زمان وقوع: {_dt(r.failure_at)}", f"علت احتمالی: {r.probable_cause or '—'}"]
        if r.description:
            parts.append(r.description)
        if r.decision_note:
            parts.append(f"نظر بررسی: {r.decision_note}")
        self.detail.setText(P(" | ".join(parts)))

    def _need(self):
        r = self._current()
        if r is None:
            _warn(self, "درخواست تعمیر", "یک درخواست را انتخاب کنید.")
        return r

    def _done(self, text: str) -> None:
        theme.set_status_label(self.status_label, text, ok=True)
        self.reload()

    def new_request(self, asset_id: int | None = None) -> int | None:
        box = combo(self.lk.equipment if self.lk else [])
        set_combo(box, asset_id)
        values = _ask(self, "درخواست تعمیر", [
            ("asset_id", "تجهیز", box), ("title", "شرح کوتاه خرابی", QLineEdit()), ("description", "توضیح", _text()),
            ("failure_at", "زمان وقوع خرابی", DateTimeField()), ("stopped", "ماشین متوقف است", QCheckBox()),
            ("severity", "شدت", combo(_labels(c.SEVERITY_LABELS))), ("cause", "علت احتمالی", QLineEdit()),
            ("work_type", "نوع کار پیشنهادی", combo(_labels(c.WORK_TYPE_LABELS), "— تعیین با برنامه‌ریز —")),
        ], "با «ماشین متوقف است» توقف همین حالا ثبت می‌شود و ماشین از ظرفیت تولید کم می‌شود؛ آماده‌به‌کاری فقط پس از آزمون ثبت می‌شود.")
        if values is None:
            return None
        rid, ok = _run(self, "درخواست تعمیر", mreq.create, company_id(), user_id(), values["asset_id"], values.get("title") or "",
                       values.get("description"), failure_at=values["failure_at"], machine_stopped=values["stopped"],
                       severity_code=values["severity"], probable_cause=values.get("cause"),
                       suggested_work_type=values.get("work_type"))
        if ok:
            self._done(P(f"درخواست ثبت شد."))
        return rid if ok else None

    def evaluate(self) -> bool:
        r = self._need()
        if r is None:
            return False
        pr = combo(_labels(c.PRIORITY_LABELS))
        set_combo(pr, r.priority_code or ("URGENT" if r.severity_code == "CRITICAL" else "NORMAL"))
        sv = combo(_labels(c.SEVERITY_LABELS))
        set_combo(sv, r.severity_code)
        values = _ask(self, "بررسی و اولویت", [("priority", "اولویت", pr), ("severity", "شدت", sv),
                                               ("work_type", "نوع کار", combo(_labels(c.WORK_TYPE_LABELS), "—")),
                                               ("note", "نظر بررسی", _text())])
        if values is None:
            return False
        _r, ok = _run(self, "بررسی", mreq.evaluate, company_id(), user_id(), r.request_id, values["priority"], values["severity"],
                      values.get("work_type"), values.get("note"))
        if ok:
            self._done("بررسی ثبت شد.")
        return ok

    def refer(self) -> bool:
        r = self._need()
        if r is None:
            return False
        values = _ask(self, "ارجاع درخواست", [("to", "ارجاع به", combo(self.lk.users)), ("note", "علت ارجاع", _text())])
        if values is None:
            return False
        _r, ok = _run(self, "ارجاع", mreq.refer, company_id(), user_id(), r.request_id, values["to"], values.get("note") or "")
        if ok:
            self._done("ارجاع شد.")
        return ok

    def approve(self) -> bool:
        r = self._need()
        if r is None:
            return False
        _r, ok = _run(self, "تأیید درخواست", mreq.approve, company_id(), user_id(), r.request_id)
        if ok:
            self._done("درخواست تأیید شد.")
        return ok

    def convert(self) -> int | None:
        r = self._need()
        if r is None:
            return None
        wt = combo(_labels(c.WORK_TYPE_LABELS))
        set_combo(wt, r.suggested_work_type or ("EMERGENCY" if r.machine_down_now else "CORRECTIVE"))
        pr = combo(_labels(c.PRIORITY_LABELS))
        set_combo(pr, r.priority_code or "NORMAL")
        title = QLineEdit(r.title)
        values = _ask(self, "تبدیل به دستور کار", [
            ("work_type", "نوع کار", wt), ("priority", "اولویت", pr), ("title", "عنوان دستور کار", title),
            ("responsible", "مسئول", combo(self.lk.users, "—")), ("hours", "زمان تخمینی (ساعت)", num_field()),
            ("shutdown", "کار نیاز به توقف ماشین دارد", QCheckBox()), ("safety", "دستورالعمل ایمنی", _text()),
        ], "درخواست تأییدنشده با همین اقدام تأیید هم ثبت می‌شود. توقف ثبت‌شدهٔ درخواست به دستور کار منتقل می‌شود.")
        if values is None:
            return None
        data = wos.WorkOrderInput(asset_id=r.asset_id, work_type_code=values["work_type"], title=values.get("title") or r.title,
                                  description=r.description, priority_code=values["priority"],
                                  responsible_user_id=values.get("responsible"),
                                  estimated_hours=values.get("hours") or None, requires_shutdown=values["shutdown"],
                                  safety_instructions=values.get("safety"))
        wo_id, ok = _run(self, "تبدیل به دستور کار", mreq.convert, company_id(), user_id(), r.request_id, data)
        if ok:
            self._done("دستور کار ساخته شد.")
        return wo_id if ok else None

    def _reason(self, title: str, fn, done: str) -> bool:
        r = self._need()
        if r is None:
            return False
        values = _ask(self, title, [("reason", "علت", _text())])
        if values is None:
            return False
        _r, ok = _run(self, title, fn, company_id(), user_id(), r.request_id, values.get("reason") or "")
        if ok:
            self._done(done)
        return ok

    def reject(self) -> bool:
        return self._reason("رد درخواست", mreq.reject, "درخواست رد شد.")

    def cancel(self) -> bool:
        return self._reason("لغو درخواست", mreq.cancel, "درخواست لغو شد.")

    def release(self) -> bool:
        r = self._need()
        if r is None:
            return False
        down = next((d for d in av.list_downtimes(company_id(), open_only=True, asset_id=r.asset_id) if d.request_id == r.request_id),
                    None)
        if down is None:
            _warn(self, "آماده‌به‌کاری", "این درخواست توقف بازی ندارد.")
            return False
        values = _ask(self, "آماده‌به‌کاری بدون دستور کار", [("at", "زمان آماده‌به‌کاری", DateTimeField()), ("note", "علت", _text())],
                      "فقط برای گزارش نادرست یا توقفی که تعمیری نخواست؛ برای خرابی واقعی، دستور کار بسازید.")
        if values is None:
            return False
        _r, ok = _run(self, "آماده‌به‌کاری", av.release_downtime, company_id(), user_id(), down.downtime_id, values["at"],
                      values.get("note"))
        if ok:
            self._done("آماده‌به‌کاری ثبت شد.")
        return ok

    def attach(self, file_path: str | None = None) -> int | None:
        r = self._need()
        if r is None:
            return None
        if file_path is None:
            file_path, _ = QFileDialog.getOpenFileName(self, "انتخاب عکس یا فایل")
        if not file_path:
            return None
        att, ok = _run(self, "پیوست", mdocs.add, company_id(), user_id(), "REQUEST", r.request_id, file_path, "IMAGE")
        if ok:
            self._done("پیوست ذخیره شد.")
        return att if ok else None

    def show_history(self) -> None:
        r = self._current()
        if r is None:
            return
        rows = mreq.history(company_id(), r.request_id)
        files = mdocs.list_for(company_id(), "REQUEST", r.request_id)
        _show_table(self, f"تاریخچهٔ درخواست {P(r.request_no)}", ["زمان", "کاربر", "اقدام", "وضعیت", "توضیح"],
                    [[_dt(h.at), h.user, _OP_LABELS.get(h.operation, h.operation), h.to_status, h.note] for h in rows]
                    + [[_dt(f.uploaded_at), "", "پیوست", "", f.file_name] for f in files])


_OP_LABELS = {"CREATE": "ثبت", "EVALUATE": "بررسی و اولویت", "REFER": "ارجاع", "APPROVE": "تأیید", "REJECT": "رد",
              "CANCEL": "لغو", "CONVERT": "تبدیل به دستور کار", "ATTACH": "پیوست"}


def _show_table(parent, title: str, headers: list[str], rows: list[list]) -> None:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLayoutDirection(Qt.RightToLeft)
    dlg.setMinimumSize(760, 420)
    lay = QVBoxLayout(dlg)
    t = table(headers)
    fill(t, rows)
    lay.addWidget(t)
    _exec(parent, dlg)


# =========================================================================================================
# پروندهٔ دستور کار
# =========================================================================================================
class WorkOrderDialog(QDialog):
    """پروندهٔ کامل یک دستور کار: مشخصات، چک‌لیست، قطعات، نیروی کار، هزینه، توقف و تاریخچه — با دکمهٔ هر گام."""

    def __init__(self, work_order_id: int, lookups: _Lookups, parent=None) -> None:
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(1100, 700)
        self.wo_id = work_order_id
        self.lk = lookups
        self.d = None
        self.dialog_runner = getattr(parent, "dialog_runner", None)
        self.confirm = getattr(parent, "confirm", None)
        self.warn = getattr(parent, "warn", None)
        outer = QVBoxLayout(self)
        self.head = _title("")
        outer.addWidget(self.head)
        cards, self.cards = ms.summary([("status", "وضعیت", "info", "📌"), ("machine", "ماشین", "warning", "⚙️"),
                                        ("cost", "جمع هزینه", "success", "💵"), ("time", "زمان کار", "info", "⏱️")])
        outer.addWidget(cards)
        self.blockers = _hint("")
        outer.addWidget(self.blockers)
        self.tabs = QTabWidget()
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info.setAlignment(Qt.AlignTop | Qt.AlignLeading)
        self.tabs.addTab(scrolled(self.info), "مشخصات")
        self.t_tasks = table(["ردیف", "شرح", "نوع نتیجه", "حدود مجاز", "الزامی", "ایمنی", "انجام", "مقدار یا شرح", "در محدوده",
                              "ثبت‌کننده"])
        self.t_tasks.cellDoubleClicked.connect(lambda _r, _c: self.record_task())
        self.tabs.addTab(self.t_tasks, "چک‌لیست")
        self.t_parts = table(["کالا", "انبار", "برنامه", "صادرشده", "برگشتی", "خالص", "مبلغ خالص", "رزرو", "موجودی آزاد", "کمبود",
                              "درخواست خرید"])
        self.tabs.addTab(self.t_parts, "قطعات")
        self.t_labor = table(["تاریخ", "تکنسین", "ساعت", "نرخ", "مبلغ", "توضیح"])
        self.tabs.addTab(self.t_labor, "نیروی کار")
        self.t_costs = table(["نوع", "شرح", "تامین‌کننده", "مبلغ", "روش ثبت", "وضعیت", "فاکتور"])
        self.tabs.addTab(self.t_costs, "هزینه‌ها")
        self.t_down = table(["نوع توقف", "شروع", "آماده‌به‌کاری", "مدت (ساعت)", "وضعیت"])
        self.tabs.addTab(self.t_down, "توقف ماشین")
        self.t_hist = table(["زمان", "کاربر", "اقدام", "از وضعیت", "به وضعیت", "توضیح"])
        self.tabs.addTab(self.t_hist, "تاریخچه")
        outer.addWidget(self.tabs, stretch=1)
        b = _btns(self, [
            ("plan", "برنامه‌ریزی", self.plan), ("assign", "واگذاری به تکنسین", self.assign), ("refer", "ارجاع", self.refer),
            ("start", "شروع کار", self.start), ("hold", "توقف موقت", self.hold), ("resume", "ادامهٔ کار", self.resume),
            ("task", "ثبت نتیجهٔ چک‌لیست", self.record_task), ("task_new", "ردیف چک‌لیست جدید", self.add_task),
            ("labor", "ثبت ساعت کار", self.add_labor), ("complete", "ثبت انجام کار", self.complete),
            ("verify", "آزمون و تأیید", self.verify), ("release", "آماده‌به‌کاری ماشین", self.release),
            ("close", "بستن دستور کار", self.close_wo), ("reopen", "بازگشایی دستور کار", self.reopen),
            ("cancel", "لغو دستور کار", self.cancel),
            ("part_add", "افزودن قطعه", self.add_part), ("reserve", "رزرو قطعه", self.reserve), ("issue", "صدور قطعه", self.issue),
            ("return", "برگشت قطعه", self.return_part), ("purchase", "درخواست خرید کمبود", self.purchase),
            ("cost_new", "هزینهٔ جدید", self.add_cost), ("cost_post", "ثبت مالی هزینه", self.post_cost),
            ("cost_link", "اتصال به فاکتور خرید", self.link_cost), ("cost_none", "بدون ثبت مالی", self.none_cost),
            ("cost_cancel", "لغو هزینه", self.cancel_cost), ("attach", "پیوست", self.attach)])
        outer.addWidget(ms.footer([[b["plan"], b["assign"], b["refer"]], [b["start"], b["hold"], b["resume"], b["task"], b["task_new"],
                                                                         b["labor"], b["complete"]],
                                   [b["verify"], b["release"], b["close"], b["reopen"], b["cancel"]], [b["attach"]]]))
        outer.addWidget(ms.footer([[b["part_add"], b["reserve"], b["issue"], b["return"], b["purchase"]],
                                   [b["cost_new"], b["cost_post"], b["cost_link"], b["cost_none"], b["cost_cancel"]]]))
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)
        ms.apply(self)
        self.load()

    # ------------------------------------------------------------------
    def load(self) -> None:
        cid = company_id()
        d = self.d = wos.get(cid, self.wo_id)
        self.setWindowTitle(P(f"دستور کار {d.wo_no}"))
        self.head.setText(P(f"دستور کار {d.wo_no} — {d.title}"))
        self.cards["status"].setText(d.status_label)
        down = [x for x in d.downtime if x.is_open]
        self.cards["machine"].setText("متوقف — منتظر آماده‌به‌کاری" if down else "در دسترس")
        self.cards["cost"].setText(decimals.format_amount(d.cost_summary.total))
        self.cards["time"].setText(_hours(d.cost_summary.hours))
        self.blockers.setText(P("برای بستن: " + " ".join(d.blockers)) if d.blockers else "")
        techs = "، ".join(t.name + (" (سرگروه)" if t.is_lead else "") for t in d.technicians) or "—"
        rows = [
            ("تجهیز", d.asset_label), ("نوع کار", d.work_type_label), ("اولویت", d.priority_label), ("مسئول", d.responsible_name or "—"),
            ("تکنسین‌ها", techs), ("درخواست مبدا", P(d.request_no) if d.request_no else "—"),
            ("سررسید پیشگیرانه", _dt(d.pm_due_date)), ("برنامه", f"{_dt(d.planned_start)} تا {_dt(d.planned_end)}"),
            ("واقعی", f"{_dt(d.actual_start)} تا {_dt(d.actual_end)}"), ("زمان تخمینی", _hours(d.estimated_hours)),
            ("نیاز به توقف ماشین", "بله" if d.requires_shutdown else "خیر"), ("دستورالعمل ایمنی", d.safety_instructions or "—"),
            ("مهارت لازم", d.required_skills or "—"), ("توقف موقت", d.hold_reason or "—"),
            ("شرح کار انجام‌شده", d.completion_note or "—"), ("نشانه / علت / اقدام", f"{d.problem_label or '—'} / {d.cause_label or '—'} / "
                                                                                   f"{d.remedy_label or '—'}"),
            ("ریشهٔ خرابی", d.root_cause_note or "—"), ("انجام‌شده توسط", f"{d.completed_by or '—'} {_dt(d.completed_at)}"),
            ("آزمون", f"{d.verification_label or '—'} {d.verified_by} {_dt(d.verified_at)} {d.verification_note or ''}"),
            ("بازگشایی", P(d.reopened_count)), ("نامزد افزایش سرمایه‌ای", "بله" if d.capital_candidate else "خیر"),
            ("شرح", d.description or "—"),
        ]
        self.info.setText(P("<br>".join(f"<b>{k}:</b> {v}" for k, v in rows)))
        fill(self.t_tasks, [[P(t.seq), t.description, t.result_label,
                             P(f"{_qty(t.min_value)} تا {_qty(t.max_value)} {t.uom_label or ''}") if t.result_type == "NUMERIC" else "",
                             "بله" if t.is_mandatory else "", "بله" if t.is_safety else "", "✔" if t.is_done else "",
                             _qty(t.value_numeric) if t.value_numeric is not None else (t.value_text or ""),
                             "" if t.is_ok is None else ("بله" if t.is_ok else "خیر"), t.done_by] for t in d.tasks],
             [t.task_id for t in d.tasks])
        for i, t in enumerate(d.tasks):
            _tone(self.t_tasks, i, _RED if t.is_ok is False else None)
        fill(self.t_parts, [[f"{p.item_code} — {p.item_name}", p.warehouse_name, _qty(p.planned_qty), _qty(p.issued_qty),
                             _qty(p.returned_qty), _qty(p.net_qty), p.net_amount, _qty(p.reserved), _qty(p.free), _qty(p.shortage),
                             P(p.purchase_request_no) if p.purchase_request_no else ""] for p in d.parts], [p.part_id for p in d.parts])
        fill(self.t_labor, [[ln.work_date, ln.name, _qty(ln.hours), ln.hourly_rate, ln.amount, ln.note or ""] for ln in d.labor],
             [ln.labor_id for ln in d.labor])
        fill(self.t_costs, [[x.type_label, x.description, x.supplier_name, x.amount, x.accounting_label, x.status_label,
                             P(x.invoice_no) if x.invoice_no else ""] for x in d.costs], [x.cost_id for x in d.costs])
        fill(self.t_down, [[x.type_label, _dt(x.down_from), _dt(x.available_at), _qty(x.hours), "باز" if x.is_open else "بسته"]
                           for x in d.downtime])
        hist = wos.history(cid, self.wo_id)
        fill(self.t_hist, [[_dt(h.at), h.user, h.operation_label, h.from_status, h.to_status, h.note] for h in hist])
        self._enable()

    def _enable(self) -> None:
        cid, uid, s = company_id(), user_id(), self.d.status_code
        plan, ex, ver = c.can(cid, uid, c.FORM_PLAN), c.can(cid, uid, c.FORM_EXECUTE), c.can(cid, uid, c.FORM_VERIFY)
        active = s in c.OPEN_WO
        rules = {"plan": plan and s in ("OPEN", "PLANNED", "ASSIGNED", "ON_HOLD"),
                 "assign": plan and s in ("OPEN", "PLANNED", "ASSIGNED", "IN_PROGRESS", "ON_HOLD"),
                 "refer": plan and active and s != "VERIFIED", "start": ex and s in ("OPEN", "PLANNED", "ASSIGNED"),
                 "hold": ex and s in ("OPEN", "PLANNED", "ASSIGNED", "IN_PROGRESS"), "resume": ex and s == "ON_HOLD",
                 "task": ex and s == "IN_PROGRESS", "task_new": ex and s in ("OPEN", "PLANNED", "ASSIGNED", "IN_PROGRESS", "ON_HOLD"),
                 "labor": ex and s in ("IN_PROGRESS", "ON_HOLD", "COMPLETED"), "complete": ex and s == "IN_PROGRESS",
                 "verify": ver and s == "COMPLETED", "release": ver and s == "VERIFIED" and any(x.is_open for x in self.d.downtime),
                 "close": ver and s == "VERIFIED", "reopen": ver and s == "CLOSED",
                 "cancel": plan and s in ("OPEN", "PLANNED", "ASSIGNED", "IN_PROGRESS", "ON_HOLD"),
                 "part_add": plan and active, "reserve": plan and active, "purchase": plan and active,
                 "issue": c.can(cid, uid, c.FORM_PARTS) and active, "return": c.can(cid, uid, c.FORM_PARTS) and active,
                 "cost_new": ex and active, "cost_post": c.can(cid, uid, c.FORM_COST), "cost_link": c.can(cid, uid, c.FORM_COST),
                 "cost_none": c.can(cid, uid, c.FORM_COST), "cost_cancel": ex, "attach": True}
        for key, on in rules.items():
            self.buttons[key].setEnabled(bool(on))

    def _after(self, ok: bool, text: str) -> bool:
        if ok:
            theme.set_status_label(self.status_label, text, ok=True)
            self.load()
        return ok

    def _call(self, title: str, fn, *args, done: str = "انجام شد.", **kwargs) -> bool:
        _r, ok = _run(self, title, fn, *args, **kwargs)
        return self._after(ok, done)

    # --- گام‌های گردش ----------------------------------------------------------
    def plan(self) -> bool:
        d = self.d
        pr = combo(_labels(c.PRIORITY_LABELS))
        set_combo(pr, d.priority_code)
        resp = combo(self.lk.users, "—")
        set_combo(resp, d.responsible_user_id)
        shut = QCheckBox()
        shut.setChecked(d.requires_shutdown)
        values = _ask(self, "برنامه‌ریزی دستور کار", [
            ("priority", "اولویت", pr), ("responsible", "مسئول", resp), ("start", "شروع برنامه", DateTimeField(d.planned_start)),
            ("end", "پایان برنامه", DateTimeField(d.planned_end)), ("hours", "زمان تخمینی (ساعت)", num_field(d.estimated_hours)),
            ("shutdown", "نیاز به توقف ماشین", shut), ("safety", "دستورالعمل ایمنی", _text(d.safety_instructions)),
            ("skills", "مهارت لازم", QLineEdit(d.required_skills or "")),
        ])
        if values is None:
            return False
        return self._call("برنامه‌ریزی", wos.update_plan, company_id(), user_id(), self.wo_id, priority_code=values["priority"],
                          responsible_user_id=values.get("responsible"), planned_start=values["start"], planned_end=values["end"],
                          estimated_hours=values.get("hours") or None, requires_shutdown=values["shutdown"],
                          safety_instructions=values.get("safety"), required_skills=values.get("skills"))

    def assign(self) -> bool:
        lst = QListWidget()
        current = {t.user_id for t in self.d.technicians}
        for name, uid in self.lk.users:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, uid)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if uid in current else Qt.Unchecked)
            lst.addItem(item)
        lead = combo(self.lk.users, "— نخستین تکنسین —")
        set_combo(lead, next((t.user_id for t in self.d.technicians if t.is_lead), None))
        dlg = FormDialog("واگذاری به تکنسین", [("lead", "سرگروه", lead)], "تکنسین‌ها را علامت بزنید.", self)
        dlg.layout().insertWidget(1, lst)
        if not _exec(self, dlg):
            return False
        ids = [lst.item(i).data(Qt.UserRole) for i in range(lst.count()) if lst.item(i).checkState() == Qt.Checked]
        return self._call("واگذاری", wos.assign, company_id(), user_id(), self.wo_id, ids, dlg.values().get("lead"))

    def refer(self) -> bool:
        values = _ask(self, "ارجاع دستور کار", [("to", "مسئول تازه", combo(self.lk.users)), ("note", "علت ارجاع", _text())])
        if values is None:
            return False
        return self._call("ارجاع", wos.refer, company_id(), user_id(), self.wo_id, values["to"], values.get("note") or "")

    def start(self) -> bool:
        values = _ask(self, "شروع کار", [("at", "زمان شروع", DateTimeField())],
                      "کاری که نیاز به توقف ماشین دارد، اگر ماشین متوقف نباشد، توقف برنامه‌ریزی‌شده را از همین زمان ثبت می‌کند.")
        if values is None:
            return False
        return self._call("شروع کار", wos.start, company_id(), user_id(), self.wo_id, values["at"])

    def hold(self) -> bool:
        values = _ask(self, "توقف موقت", [("reason", "علت (مثلاً انتظار قطعه)", _text())])
        if values is None:
            return False
        return self._call("توقف موقت", wos.hold, company_id(), user_id(), self.wo_id, values.get("reason") or "")

    def resume(self) -> bool:
        return self._call("ادامهٔ کار", wos.resume, company_id(), user_id(), self.wo_id)

    def record_task(self) -> bool:
        tid = _selected(self.t_tasks)
        task = next((t for t in self.d.tasks if t.task_id == tid), None)
        if task is None:
            _warn(self, "چک‌لیست", "یک ردیف چک‌لیست را انتخاب کنید.")
            return False
        if task.result_type == "NUMERIC":
            fields = [("value", P(f"مقدار ({_qty(task.min_value)} تا {_qty(task.max_value)} {task.uom_label or ''})"), num_field())]
        elif task.result_type == "TEXT":
            fields = [("text", "شرح نتیجه", _text())]
        else:
            done = QCheckBox()
            done.setChecked(True)
            fields = [("done", "انجام شد", done), ("text", "توضیح", QLineEdit())]
        values = _ask(self, P(f"ردیف {task.seq}: {task.description}"), fields)
        if values is None:
            return False
        ok_, ok = _run(self, "چک‌لیست", wos.record_task, company_id(), user_id(), task.task_id, values.get("done", True),
                       values.get("value"), values.get("text"))
        return self._after(ok, "نتیجه ثبت شد." if ok_ is not False else "ثبت شد؛ مقدار خارج از حدود مجاز است.")

    def add_task(self) -> bool:
        values = _ask(self, "ردیف چک‌لیست جدید", [
            ("desc", "شرح", QLineEdit()), ("type", "نوع نتیجه", combo(_labels(c.RESULT_TYPE_LABELS))),
            ("min", "حداقل مجاز", num_field()), ("max", "حداکثر مجاز", num_field()), ("uom", "واحد", QLineEdit()),
            ("mandatory", "الزامی", QCheckBox()), ("safety", "ردیف ایمنی", QCheckBox())])
        if values is None:
            return False
        t = wos.TaskInput(values.get("desc") or "", values["type"], values.get("min") or None, values.get("max") or None,
                          values.get("uom"), values["mandatory"], values["safety"])
        return self._call("چک‌لیست", wos.add_task, company_id(), user_id(), self.wo_id, t)

    def add_labor(self) -> bool:
        who = combo(self.lk.users)
        set_combo(who, user_id())
        values = _ask(self, "ثبت ساعت کار", [("who", "تکنسین", who), ("date", "تاریخ", date_field()),
                                             ("hours", "ساعت", num_field()), ("note", "توضیح", QLineEdit())],
                      "مبلغ از نرخ دستمزد همان کارمند حساب می‌شود و فقط برای گزارش است؛ حقوق در حقوق‌ودستمزد ثبت می‌شود.")
        if values is None:
            return False
        return self._call("ساعت کار", wos.add_labor, company_id(), user_id(), self.wo_id, values["who"], values["date"],
                          values.get("hours") or 0, values.get("note"))

    def complete(self) -> bool:
        values = _ask(self, "ثبت انجام کار", [
            ("at", "زمان پایان کار", DateTimeField()), ("note", "شرح کار انجام‌شده", _text()),
            ("problem", "نشانهٔ خرابی", combo(self.lk.codes["PROBLEM"], "—")), ("cause", "علت", combo(self.lk.codes["CAUSE"], "—")),
            ("remedy", "اقدام انجام‌شده", combo(self.lk.codes["REMEDY"], "—")), ("root", "ریشهٔ خرابی", _text()),
        ], "«انجام‌شده» یعنی کار تکنسین تمام شده؛ ماشین تا آزمون و ثبت آماده‌به‌کاری هنوز در دسترس تولید نیست.")
        if values is None:
            return False
        return self._call("انجام کار", wos.complete, company_id(), user_id(), self.wo_id, values.get("note") or "", at=values["at"],
                          problem_code_id=values.get("problem"), cause_code_id=values.get("cause"),
                          remedy_code_id=values.get("remedy"), root_cause_note=values.get("root"))

    def verify(self) -> bool:
        values = _ask(self, "آزمون و تأیید", [("result", "نتیجه", combo(_labels(c.VERIFY_LABELS))), ("note", "شرح آزمون", _text())],
                      "«قبول» = کار درست انجام شده و ردیف‌های ایمنی تأیید شده‌اند؛ «مردود» کار را به اجرا برمی‌گرداند.")
        if values is None:
            return False
        return self._call("آزمون", wos.verify, company_id(), user_id(), self.wo_id, values["result"], values.get("note"))

    def release(self) -> bool:
        values = _ask(self, "آماده‌به‌کاری ماشین", [("at", "زمان آماده‌به‌کاری", DateTimeField()), ("note", "توضیح", QLineEdit())],
                      "با ثبت آماده‌به‌کاری، توقف بسته و ماشین دوباره در ظرفیت تولید حساب می‌شود.")
        if values is None:
            return False
        return self._call("آماده‌به‌کاری", wos.release_machine, company_id(), user_id(), self.wo_id, values["at"], values.get("note"))

    def close_wo(self) -> bool:
        if not _confirm(self, "بستن دستور کار", "پس از بستن، قطعه و هزینهٔ تازه پذیرفته نمی‌شود. بسته شود؟"):
            return False
        return self._call("بستن", wos.close, company_id(), user_id(), self.wo_id)

    def reopen(self) -> bool:
        values = _ask(self, "بازگشایی دستور کار", [("reason", "علت بازگشایی", _text())])
        if values is None:
            return False
        return self._call("بازگشایی", wos.reopen, company_id(), user_id(), self.wo_id, values.get("reason") or "")

    def cancel(self) -> bool:
        values = _ask(self, "لغو دستور کار", [("reason", "علت لغو", _text())])
        if values is None:
            return False
        return self._call("لغو", wos.cancel, company_id(), user_id(), self.wo_id, values.get("reason") or "")

    # --- قطعه ------------------------------------------------------------------
    def add_part(self) -> bool:
        values = _ask(self, "افزودن قطعه", [("item", "کالا", combo(self.lk.items)), ("wh", "انبار", combo(self.lk.warehouses)),
                                            ("qty", "مقدار برنامه", num_field())])
        if values is None:
            return False
        return self._call("قطعه", mparts.add_part, company_id(), user_id(), self.wo_id, values["item"], values["wh"],
                          values.get("qty") or 0)

    def reserve(self) -> bool:
        qty, ok = _run(self, "رزرو", mparts.reserve, company_id(), user_id(), self.wo_id)
        return self._after(ok, P(f"{decimals.format_qty(qty)} واحد رزرو شد.") if ok else "")

    def _part_qty(self, title: str, hint: str):
        pid = _selected(self.t_parts)
        part = next((p for p in self.d.parts if p.part_id == pid), None)
        if part is None:
            _warn(self, title, "یک ردیف قطعه را انتخاب کنید.")
            return None, None
        values = _ask(self, title, [("qty", "مقدار", num_field())], P(f"{part.item_name} — {hint}"))
        return part, (values or {}).get("qty")

    def issue(self) -> bool:
        part, qty = self._part_qty("صدور قطعه", "حوالهٔ انبار با حساب هزینهٔ قطعات تعمیر و مرکز هزینهٔ تجهیز ثبت می‌شود.")
        if not qty:
            return False
        return self._call("صدور قطعه", mparts.issue, company_id(), user_id(), self.wo_id, [mparts.PartLine(part.part_id, qty)],
                          done="حوالهٔ انبار ثبت شد.")

    def return_part(self) -> bool:
        part, qty = self._part_qty("برگشت قطعه", "با میانگین بهای صادرشدهٔ همین دستور کار به انبار برمی‌گردد.")
        if not qty:
            return False
        return self._call("برگشت قطعه", mparts.return_parts, company_id(), user_id(), self.wo_id, [mparts.PartLine(part.part_id, qty)],
                          done="رسید برگشت ثبت شد.")

    def purchase(self) -> bool:
        pr, ok = _run(self, "درخواست خرید", mparts.request_purchase, company_id(), user_id(), self.wo_id)
        if ok and pr is None:
            _warn(self, "درخواست خرید", "کمبودی نیست یا برای کمبودها درخواست خرید باز ثبت شده است.")
            return False
        return self._after(ok, "درخواست خرید پیش‌نویس ساخته شد؛ ارسال و تصویب از صفحهٔ درخواست خرید انجام می‌شود.")

    # --- هزینه -----------------------------------------------------------------
    def _cost(self):
        cid_ = _selected(self.t_costs)
        cost = next((x for x in self.d.costs if x.cost_id == cid_), None)
        if cost is None:
            _warn(self, "هزینه", "یک ردیف هزینه را انتخاب کنید.")
        return cost

    def add_cost(self) -> bool:
        values = _ask(self, "هزینهٔ جدید", [("type", "نوع", combo(_labels(c.COST_TYPE_LABELS))), ("desc", "شرح", QLineEdit()),
                                            ("amount", "مبلغ", num_field()), ("supplier", "تامین‌کننده یا پیمانکار",
                                                                             combo(self.lk.suppliers, "—"))])
        if values is None:
            return False
        return self._call("هزینه", mcost.add_cost, company_id(), user_id(), self.wo_id, values["type"], values.get("desc") or "",
                          values.get("amount") or 0, values.get("supplier"))

    def post_cost(self) -> bool:
        cost = self._cost()
        if cost is None:
            return False
        cap = combo([("طبق سیاست دارایی (حد سرمایه‌ای‌شدن)", None), ("هزینهٔ تعمیر", False), ("افزایش سرمایه‌ای", True)])
        sup = combo(self.lk.suppliers, "—")
        set_combo(sup, cost.supplier_detail_account_id)
        values = _ask(self, "ثبت مالی هزینه", [("account", "حساب مقابل (بستانکار)", combo(self.lk.accounts)),
                                               ("detail", "تفصیلی مقابل", sup), ("capital", "روش ثبت", cap),
                                               ("date", "تاریخ سند", date_field())],
                      "از همان مسیر «افزایش سرمایه‌ای/تعمیر» دارایی و تأیید مالی آن ثبت می‌شود؛ تکرار این کار سند دوم نمی‌سازد.")
        if values is None:
            return False
        return self._call("ثبت مالی", mcost.post, company_id(), user_id(), cost.cost_id, values["account"], values.get("detail"),
                          values.get("capital"), values["date"], done="ثبت مالی انجام شد یا به کارتابل تأیید رفت.")

    def link_cost(self) -> bool:
        cost = self._cost()
        if cost is None:
            return False
        from peecha.services import commercial_documents as docs

        invoices = [(P(f"{d.document_no} — {_dt(d.document_date)} — {decimals.format_amount(d.total_amount)}"), d.document_id)
                    for d in docs.list_documents(company_id(), "PURCHASE_INVOICE", status_code="POSTED")]
        values = _ask(self, "اتصال به فاکتور خرید", [("doc", "فاکتور خرید ثبت‌شده", combo(invoices))],
                      "هزینه همان‌جا در فاکتور ثبت شده و این‌جا دوباره ثبت نمی‌شود.")
        if values is None:
            return False
        return self._call("اتصال", mcost.link_invoice, company_id(), user_id(), cost.cost_id, values["doc"])

    def none_cost(self) -> bool:
        cost = self._cost()
        if cost is None:
            return False
        values = _ask(self, "بدون ثبت مالی", [("reason", "علت (مثلاً زیر پوشش ضمانت)", _text())])
        if values is None:
            return False
        return self._call("بدون ثبت مالی", mcost.mark_none, company_id(), user_id(), cost.cost_id, values.get("reason") or "")

    def cancel_cost(self) -> bool:
        cost = self._cost()
        if cost is None:
            return False
        values = _ask(self, "لغو هزینه", [("reason", "علت لغو", _text())])
        if values is None:
            return False
        return self._call("لغو هزینه", mcost.cancel_cost, company_id(), user_id(), cost.cost_id, values.get("reason") or "")

    def attach(self, file_path: str | None = None) -> int | None:
        if file_path is None:
            file_path, _ = QFileDialog.getOpenFileName(self, "انتخاب عکس یا فایل")
        if not file_path:
            return None
        att, ok = _run(self, "پیوست", mdocs.add, company_id(), user_id(), "WORK_ORDER", self.wo_id, file_path, "IMAGE")
        self._after(ok, "پیوست ذخیره شد.")
        return att if ok else None


# =========================================================================================================
# تابلوی دستور کار
# =========================================================================================================
_BOARD_COLUMNS = (("باز و برنامه‌ریزی", ("OPEN", "PLANNED")), ("واگذارشده", ("ASSIGNED",)), ("در حال انجام", ("IN_PROGRESS",)),
                  ("متوقف موقت", ("ON_HOLD",)), ("منتظر آزمون", ("COMPLETED",)), ("آزمون‌شده", ("VERIFIED",)))


@ms.styled
class WorkOrderBoardScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.rows: list = []
        self.lk: _Lookups | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        self.work_type = combo(_labels(c.WORK_TYPE_LABELS), "همهٔ نوع‌های کار")
        self.work_type.currentIndexChanged.connect(lambda _i: self.reload())
        self.mine = QCheckBox("فقط کارهای من")
        self.mine.toggled.connect(lambda _v: self.reload())
        self.closed = QCheckBox("بسته و لغوشده هم")
        self.closed.toggled.connect(lambda _v: self.reload())
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو: تجهیز یا عنوان")
        self.search.returnPressed.connect(self.reload)
        outer.addWidget(ms.header_card(_title("دستورهای کار"), self.work_type, self.mine, self.closed, self.search))
        cards, self.cards = ms.summary([("open", "باز", "info", "🧰"), ("progress", "در حال انجام", "warning", "🔧"),
                                        ("test", "منتظر آزمون", "info", "🛡️"), ("urgent", "فوری", "danger", "🚨")])
        outer.addWidget(cards)
        self.tabs = QTabWidget()
        board = QWidget()
        bl = QHBoxLayout(board)
        self.lists: dict[str, QListWidget] = {}
        for title, _codes in _BOARD_COLUMNS:
            col = QVBoxLayout()
            head = QLabel(title)
            head.setObjectName("cardTitle")
            col.addWidget(head)
            lst = QListWidget()
            lst.itemDoubleClicked.connect(lambda item: self.open_order(item.data(Qt.UserRole)))
            col.addWidget(lst, stretch=1)
            self.lists[title] = lst
            bl.addLayout(col)
        self.tabs.addTab(board, "تابلو")
        self.t = table(["شماره", "تجهیز", "خط", "نوع کار", "اولویت", "عنوان", "وضعیت", "مسئول", "شروع برنامه", "پایان برنامه",
                        "سررسید پیشگیرانه"])
        self.t.cellDoubleClicked.connect(lambda _r, _c: self.open_order())
        self.tabs.addTab(self.t, "فهرست")
        outer.addWidget(self.tabs, stretch=1)
        b = _btns(self, [("new", "دستور کار جدید", self.new_order), ("open", "باز کردن دستور کار", self.open_order),
                         ("pm", "ساخت دستورهای پیشگیرانهٔ سررسید", self.generate_pm), ("refresh", "به‌روزرسانی", self.refresh),
                         ("report", "گزارش کامل", lambda: _open_report(self._main_window, "MNT_WORK_ORDERS"))])
        outer.addWidget(ms.footer([[b["new"], b["open"]], [b["pm"]], [b["refresh"], b["report"]]]))
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.lk = _Lookups(cid)
        self.buttons["new"].setEnabled(c.can(cid, user_id(), c.FORM_PLAN, "CREATE") and can("mnt_work_orders", "CREATE"))
        self.buttons["pm"].setEnabled(c.can(cid, user_id(), c.FORM_PLAN, "CREATE"))
        self.reload()

    def reload(self) -> None:
        cid = company_id()
        if cid is None:
            return
        if self.mine.isChecked():
            rows = wos.my_work(cid, user_id())
        else:
            rows = wos.board(cid, work_type_code=self.work_type.currentData(), include_closed=self.closed.isChecked(),
                             search=self.search.text().strip() or None)
        if self.work_type.currentData():
            rows = [r for r in rows if r.work_type_code == self.work_type.currentData()]
        self.rows = rows
        fill(self.t, [[P(r.wo_no), r.asset_label, r.production_line or "", r.work_type_label, r.priority_label, r.title,
                       r.status_label, r.responsible_name, _dt(r.planned_start), _dt(r.planned_end), _dt(r.pm_due_date)] for r in rows],
             [r.work_order_id for r in rows])
        for i, r in enumerate(rows):
            _tone(self.t, i, _PRIORITY_TONE.get(r.priority_code))
        for title, codes in _BOARD_COLUMNS:
            lst = self.lists[title]
            lst.clear()
            for r in rows:
                if r.status_code in codes:
                    item = QListWidgetItem(P(f"{r.wo_no} — {r.asset_code}\n{r.title}\n{r.priority_label} | {r.responsible_name or '—'}"))
                    item.setData(Qt.UserRole, r.work_order_id)
                    if r.priority_code in _PRIORITY_TONE:
                        item.setForeground(_PRIORITY_TONE[r.priority_code])
                    lst.addItem(item)
        open_rows = [r for r in rows if r.status_code in c.OPEN_WO]
        self.cards["open"].setText(P(len(open_rows)))
        self.cards["progress"].setText(P(sum(1 for r in open_rows if r.status_code == "IN_PROGRESS")))
        self.cards["test"].setText(P(sum(1 for r in open_rows if r.status_code == "COMPLETED")))
        self.cards["urgent"].setText(P(sum(1 for r in open_rows if r.priority_code == "URGENT")))

    def open_order(self, work_order_id: int | None = None) -> WorkOrderDialog | None:
        wid = work_order_id or _selected(self.t)
        if wid is None:
            _warn(self, "دستور کار", "یک دستور کار را انتخاب کنید.")
            return None
        dlg = WorkOrderDialog(wid, self.lk or _Lookups(company_id()), self)
        _exec(self, dlg)
        self.reload()
        return dlg

    def new_order(self) -> int | None:
        values = _ask(self, "دستور کار جدید", [
            ("asset", "تجهیز", combo(self.lk.equipment)), ("type", "نوع کار", combo(_labels(c.WORK_TYPE_LABELS))),
            ("title", "عنوان", QLineEdit()), ("priority", "اولویت", combo(_labels(c.PRIORITY_LABELS))),
            ("responsible", "مسئول", combo(self.lk.users, "—")), ("stopped", "ماشین همین حالا متوقف است (خرابی اضطراری)", QCheckBox()),
            ("shutdown", "کار نیاز به توقف ماشین دارد", QCheckBox()), ("hours", "زمان تخمینی (ساعت)", num_field()),
            ("desc", "شرح", _text())])
        if values is None:
            return None
        priority = values["priority"]
        data = wos.WorkOrderInput(asset_id=values["asset"], work_type_code=values["type"], title=values.get("title") or "",
                                  description=values.get("desc"), priority_code=priority,
                                  responsible_user_id=values.get("responsible"), machine_stopped=values["stopped"],
                                  requires_shutdown=values["shutdown"], estimated_hours=values.get("hours") or None)
        wid, ok = _run(self, "دستور کار", wos.create, company_id(), user_id(), data)
        if ok:
            theme.set_status_label(self.status_label, "دستور کار ساخته شد.", ok=True)
            self.reload()
        return wid if ok else None

    def generate_pm(self) -> list[int]:
        ids, ok = _run(self, "نگهداری پیشگیرانه", mpm.generate_due, company_id(), user_id())
        if ok:
            theme.set_status_label(self.status_label, P(f"{len(ids)} دستور کار پیشگیرانه ساخته شد (تکراری ساخته نمی‌شود)."), ok=True)
            self.reload()
        return ids or []


# =========================================================================================================
# نگهداری پیشگیرانه
# =========================================================================================================
class PmPlanDialog(QDialog):
    def __init__(self, lookups: _Lookups, plan=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("برنامهٔ نگهداری پیشگیرانه")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(900, 680)
        self.lk = lookups
        d = plan.data if plan else mpm.PlanInput(code="", asset_id=0, title="")
        outer = QVBoxLayout(self)
        body = QWidget()
        form = QGridLayout(body)
        self.code, self.title = QLineEdit(d.code), QLineEdit(d.title)
        self.asset = combo(lookups.equipment)
        set_combo(self.asset, d.asset_id)
        self.work_type = combo([(c.WORK_TYPE_LABELS[k], k) for k in c.PM_TYPES])
        set_combo(self.work_type, d.work_type_code)
        self.trigger = combo(_labels(c.TRIGGER_LABELS))
        set_combo(self.trigger, d.trigger_code)
        self.interval = num_field(d.interval_days)
        self.meter = num_field(d.meter_interval)
        self.lead = num_field(d.lead_days)
        self.start = date_field(d.start_date)
        self.hours = num_field(d.estimated_hours)
        self.shutdown = QCheckBox("نیاز به توقف ماشین")
        self.shutdown.setChecked(d.requires_shutdown)
        self.active = QCheckBox("فعال")
        self.active.setChecked(d.is_active)
        self.responsible = combo(lookups.users, "—")
        set_combo(self.responsible, d.responsible_user_id)
        self.skills = QLineEdit(d.required_skills or "")
        self.safety = _text(d.safety_instructions)
        pairs = [("کد", self.code), ("عنوان", self.title), ("تجهیز", self.asset), ("نوع کار", self.work_type),
                 ("مبنای سررسید", self.trigger), ("فاصلهٔ تقویمی (روز)", self.interval), ("فاصلهٔ کارکرد", self.meter),
                 ("ساخت دستور چند روز زودتر", self.lead), ("نخستین سررسید", self.start), ("زمان تخمینی (ساعت)", self.hours),
                 ("مسئول", self.responsible), ("مهارت لازم", self.skills)]
        for i, (label, w) in enumerate(pairs):
            form.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            form.addWidget(w, i // 2, (i % 2) * 2 + 1)
        row = len(pairs) // 2 + 1
        form.addWidget(self.shutdown, row, 1)
        form.addWidget(self.active, row, 3)
        form.addWidget(QLabel("دستورالعمل ایمنی"), row + 1, 0)
        form.addWidget(self.safety, row + 1, 1, 1, 3)
        outer.addWidget(scrolled(body, 320))
        outer.addWidget(_hint("چک‌لیست (شرح، نوع نتیجه، حداقل، حداکثر، واحد، الزامی، ایمنی) و قطعه‌های مصرفی هر بار انجام:"))
        self.t_tasks = QTableWidget(0, 7)
        self.t_tasks.setHorizontalHeaderLabels(["شرح", "نوع نتیجه", "حداقل", "حداکثر", "واحد", "الزامی", "ایمنی"])
        self.t_tasks.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.t_tasks, stretch=1)
        self.t_parts = QTableWidget(0, 3)
        self.t_parts.setHorizontalHeaderLabels(["کالا", "انبار", "مقدار"])
        self.t_parts.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.t_parts)
        b = _btns(self, [("task_add", "افزودن ردیف", self.add_task_row), ("task_del", "حذف ردیف", lambda: self._del(self.t_tasks)),
                         ("part_add", "افزودن قطعه", self.add_part_row), ("part_del", "حذف ردیف", lambda: self._del(self.t_parts))])
        outer.addWidget(ms.footer([[b["task_add"], b["task_del"]], [b["part_add"], b["part_del"]]]))
        from PySide6.QtWidgets import QDialogButtonBox

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        outer.addWidget(box)
        for t in d.tasks:
            self.add_task_row(t)
        for p in d.parts:
            self.add_part_row(p)
        ms.apply(self)

    @staticmethod
    def _del(t: QTableWidget) -> None:
        if t.currentRow() >= 0:
            t.removeRow(t.currentRow())

    def add_task_row(self, task=None) -> None:
        r = self.t_tasks.rowCount()
        self.t_tasks.insertRow(r)
        self.t_tasks.setItem(r, 0, QTableWidgetItem(task.description if task else ""))
        kind = combo(_labels(c.RESULT_TYPE_LABELS))
        set_combo(kind, task.result_type if task else "CHECK")
        self.t_tasks.setCellWidget(r, 1, kind)
        for col, v in ((2, task.min_value if task else None), (3, task.max_value if task else None)):
            self.t_tasks.setCellWidget(r, col, num_field(v))
        self.t_tasks.setItem(r, 4, QTableWidgetItem((task.uom_label or "") if task else ""))
        for col, v in ((5, task.is_mandatory if task else True), (6, task.is_safety if task else False)):
            box = QCheckBox()
            box.setChecked(v)
            self.t_tasks.setCellWidget(r, col, box)

    def add_part_row(self, part=None) -> None:
        r = self.t_parts.rowCount()
        self.t_parts.insertRow(r)
        item = combo(self.lk.items)
        wh = combo(self.lk.warehouses)
        if part:
            set_combo(item, part[0])
            set_combo(wh, part[1])
        self.t_parts.setCellWidget(r, 0, item)
        self.t_parts.setCellWidget(r, 1, wh)
        self.t_parts.setCellWidget(r, 2, num_field(part[2] if part else None))

    def data(self) -> mpm.PlanInput:
        from peecha.ui.screens.fixed_assets import dec

        def num(w):
            t = w.text().strip()
            return dec(t) if t else None

        tasks = []
        for r in range(self.t_tasks.rowCount()):
            desc = (self.t_tasks.item(r, 0).text() if self.t_tasks.item(r, 0) else "").strip()
            if not desc:
                continue
            tasks.append(wos.TaskInput(desc, self.t_tasks.cellWidget(r, 1).currentData(), num(self.t_tasks.cellWidget(r, 2)),
                                       num(self.t_tasks.cellWidget(r, 3)),
                                       self.t_tasks.item(r, 4).text() if self.t_tasks.item(r, 4) else None,
                                       self.t_tasks.cellWidget(r, 5).isChecked(), self.t_tasks.cellWidget(r, 6).isChecked()))
        parts = []
        for r in range(self.t_parts.rowCount()):
            q = num(self.t_parts.cellWidget(r, 2))
            if q:
                parts.append((self.t_parts.cellWidget(r, 0).currentData(), self.t_parts.cellWidget(r, 1).currentData(), q))
        interval = num(self.interval)
        return mpm.PlanInput(code=self.code.text().strip(), asset_id=self.asset.currentData(), title=self.title.text().strip(),
                             work_type_code=self.work_type.currentData(), trigger_code=self.trigger.currentData(),
                             interval_days=int(interval) if interval else None, meter_interval=num(self.meter),
                             lead_days=int(num(self.lead) or 0), start_date=self.start.date(), estimated_hours=num(self.hours),
                             safety_instructions=self.safety.toPlainText().strip() or None,
                             required_skills=self.skills.text().strip() or None, requires_shutdown=self.shutdown.isChecked(),
                             responsible_user_id=self.responsible.currentData(), is_active=self.active.isChecked(),
                             tasks=tasks, parts=parts)


@ms.styled
class PmScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.plans: list = []
        self.posts: list = []
        self.lk: _Lookups | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.addWidget(ms.header_card(_title("نگهداری پیشگیرانه")))
        cards, self.cards = ms.summary([("active", "برنامهٔ فعال", "info", "🗓️"), ("due", "سررسید", "warning", "⏰"),
                                        ("overdue", "گذشته از سررسید", "danger", "⛔"), ("nodata", "بدون دادهٔ کارکرد", "info", "❔")])
        outer.addWidget(cards)
        self.tabs = QTabWidget()
        w = QWidget()
        lay = QVBoxLayout(w)
        self.t_plans = table(["کد", "عنوان", "تجهیز", "نوع کار", "مبنا", "فاصله", "آخرین انجام", "سررسید", "کارکرد از آخرین انجام",
                              "وضعیت", "فعال"])
        self.t_plans.cellDoubleClicked.connect(lambda _r, _c: self.edit_plan())
        lay.addWidget(self.t_plans, stretch=1)
        b = _btns(self, [("new", "برنامهٔ جدید", self.new_plan), ("edit", "ویرایش برنامه", self.edit_plan),
                         ("generate", "ساخت دستورهای پیشگیرانهٔ سررسید", self.generate), ("postpone", "درخواست تعویق", self.postpone),
                         ("meter", "ثبت کارکرد", self.record_meter),
                         ("report", "گزارش کامل", lambda: _open_report(self._main_window, "MNT_PM_COMPLIANCE"))])
        lay.addWidget(ms.footer([[b["new"], b["edit"]], [b["generate"], b["postpone"], b["meter"]], [b["report"]]]))
        self.tabs.addTab(w, "برنامه‌ها")
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.cal_from, self.cal_to = date_field(datetime.date.today()), date_field(datetime.date.today() + datetime.timedelta(days=90))
        row.addWidget(QLabel("از تاریخ:"))
        row.addWidget(self.cal_from)
        row.addWidget(QLabel("تا تاریخ:"))
        row.addWidget(self.cal_to)
        show = QPushButton("نمایش تقویم")
        show.clicked.connect(lambda _c=False: self.load_calendar())
        row.addWidget(show)
        row.addStretch(1)
        lay.addLayout(row)
        self.t_cal = table(["تاریخ", "تجهیز", "عنوان", "نوع", "دستور کار", "وضعیت", "توقف ماشین"])
        lay.addWidget(self.t_cal, stretch=1)
        self.tabs.addTab(w, "تقویم")
        w = QWidget()
        lay = QVBoxLayout(w)
        self.t_post = table(["برنامه", "تجهیز", "سررسید فعلی", "سررسید پیشنهادی", "علت", "درخواست‌کننده", "وضعیت"])
        lay.addWidget(self.t_post, stretch=1)
        b = _btns(self, [("approve", "تأیید تعویق", lambda: self.decide(True)), ("reject", "رد تعویق", lambda: self.decide(False))])
        lay.addWidget(ms.footer([[b["approve"], b["reject"]]]))
        self.tabs.addTab(w, "تعویق‌ها")
        outer.addWidget(self.tabs, stretch=1)
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.lk = _Lookups(cid)
        uid = user_id()
        for key in ("new", "edit"):
            self.buttons[key].setEnabled(c.can(cid, uid, c.FORM_MANAGE) and can("mnt_pm", "EDIT"))
        self.buttons["generate"].setEnabled(c.can(cid, uid, c.FORM_PLAN, "CREATE"))
        self.buttons["postpone"].setEnabled(c.can(cid, uid, c.FORM_PLAN))
        for key in ("approve", "reject"):
            self.buttons[key].setEnabled(c.can(cid, uid, c.FORM_APPROVE))
        self.reload()

    def reload(self) -> None:
        cid = company_id()
        self.plans = mpm.list_plans(cid)
        fill(self.t_plans, [[p.code, p.title, p.asset_label, p.work_type_label, p.trigger_label,
                             " / ".join(x for x in (P(f"{p.interval_days} روز") if p.interval_days else "",
                                                     P(f"{decimals.format_qty(p.meter_interval)} واحد") if p.meter_interval else "") if x),
                             _dt(p.last_completed_date), _dt(p.due.due_date),
                             _qty(p.due.meter_used) if p.due.meter_used is not None else ("—" if p.trigger_code == "CALENDAR" else "داده ناکافی"),
                             p.due.state_label, "بله" if p.is_active else "خیر"] for p in self.plans], [p.plan_id for p in self.plans])
        for i, p in enumerate(self.plans):
            _tone(self.t_plans, i, _STATE_TONE.get(p.due.state))
        active = [p for p in self.plans if p.is_active]
        self.cards["active"].setText(P(len(active)))
        self.cards["due"].setText(P(sum(1 for p in active if p.due.state == "DUE")))
        self.cards["overdue"].setText(P(sum(1 for p in active if p.due.state == "OVERDUE")))
        self.cards["nodata"].setText(P(sum(1 for p in active if p.due.state == "NO_DATA" or p.due.meter_state == "NO_DATA")))
        self.posts = mpm.list_postponements(cid)
        fill(self.t_post, [[f"{x.plan_code} — {x.plan_title}", x.asset_label, x.old_due_date, x.new_due_date, x.reason, x.requested_by,
                            x.status_label] for x in self.posts], [x.postponement_id for x in self.posts])
        self.load_calendar()

    def load_calendar(self) -> None:
        rows = mpm.calendar(company_id(), self.cal_from.date(), self.cal_to.date())
        fill(self.t_cal, [[r.date, r.asset_label, r.title, "دستور کار" if r.kind == "WORK_ORDER" else "پیش‌بینی",
                           P(r.wo_no) if r.wo_no else "", r.status_label, "بله" if r.requires_shutdown else ""] for r in rows])
        for i, r in enumerate(rows):
            _tone(self.t_cal, i, _RED if r.overdue else None)

    def _plan(self):
        pid = _selected(self.t_plans)
        if pid is None:
            _warn(self, "برنامهٔ پیشگیرانه", "یک برنامه را انتخاب کنید.")
        return pid

    def new_plan(self) -> int | None:
        dlg = PmPlanDialog(self.lk, None, self)
        if not _exec(self, dlg):
            return None
        pid, ok = _run(self, "برنامهٔ پیشگیرانه", mpm.save_plan, company_id(), user_id(), dlg.data())
        if ok:
            self.reload()
        return pid if ok else None

    def edit_plan(self) -> bool:
        pid = self._plan()
        if pid is None:
            return False
        dlg = PmPlanDialog(self.lk, mpm.get_plan(company_id(), pid), self)
        if not _exec(self, dlg):
            return False
        _r, ok = _run(self, "برنامهٔ پیشگیرانه", mpm.save_plan, company_id(), user_id(), dlg.data(), pid)
        if ok:
            self.reload()
        return ok

    def generate(self) -> list[int]:
        ids, ok = _run(self, "نگهداری پیشگیرانه", mpm.generate_due, company_id(), user_id())
        if ok:
            theme.set_status_label(self.status_label, P(f"{len(ids)} دستور کار ساخته شد؛ اجرای دوباره دستور تکراری نمی‌سازد."), ok=True)
            self.reload()
        return ids or []

    def postpone(self) -> bool:
        pid = self._plan()
        if pid is None:
            return False
        values = _ask(self, "درخواست تعویق", [("date", "سررسید تازه", date_field(datetime.date.today() + datetime.timedelta(days=7))),
                                              ("reason", "علت تعویق", _text())],
                      "تعویق پس از تأیید شخص دیگری اثر می‌گذارد و سررسید دستور کار باز هم جابه‌جا می‌شود.")
        if values is None:
            return False
        _r, ok = _run(self, "تعویق", mpm.request_postponement, company_id(), user_id(), pid, values["date"], values.get("reason") or "")
        if ok:
            self.reload()
        return ok

    def decide(self, approve: bool) -> bool:
        x_id = _selected(self.t_post)
        if x_id is None:
            _warn(self, "تعویق", "یک درخواست تعویق را انتخاب کنید.")
            return False
        note = None
        if not approve:
            values = _ask(self, "رد تعویق", [("note", "علت رد", _text())])
            if values is None:
                return False
            note = values.get("note")
        _r, ok = _run(self, "تعویق", mpm.decide_postponement, company_id(), user_id(), x_id, approve, note)
        if ok:
            self.reload()
        return ok

    def record_meter(self) -> bool:
        values = _ask(self, "ثبت کارکرد", [("asset", "تجهیز", combo(self.lk.equipment)), ("date", "تاریخ", date_field()),
                                           ("units", "کارکرد این دوره (ساعت یا واحد شمارنده)", num_field()),
                                           ("note", "توضیح", QLineEdit())],
                      "در همان «کارکرد دارایی» ثبت می‌شود و مبنای سررسید کارکردی و استهلاک بر اساس تولید است.")
        if values is None:
            return False
        _r, ok = _run(self, "کارکرد", mpm.record_meter, company_id(), user_id(), values["asset"], values["date"],
                      values.get("units") or 0, values.get("note"))
        if ok:
            self.reload()
        return ok


# =========================================================================================================
# تجهیزات و کارت تجهیز
# =========================================================================================================
@ms.styled
class EquipmentScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.lk: _Lookups | None = None
        self.card_data = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        self.find_box = QLineEdit()
        self.find_box.setPlaceholderText("کد، بارکد یا اسکن برچسب QR تجهیز")
        self.find_box.returnPressed.connect(self.find)
        find_btn = QPushButton("جستجوی کد یا برچسب")
        find_btn.clicked.connect(lambda _c=False: self.find())
        outer.addWidget(ms.header_card(_title("تجهیزات"), self.find_box, find_btn))
        split = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["سایت › کارخانه › ناحیه › خط › تجهیز", "وضعیت"])
        self.tree.itemSelectionChanged.connect(self._tree_selected)
        split.addWidget(self.tree)
        right = QWidget()
        rl = QVBoxLayout(right)
        cards, self.cards = ms.summary([("status", "وضعیت", "info", "⚙️"), ("mttr", "میانگین زمان تعمیر", "warning", "⏱️"),
                                        ("mtbf", "میانگین زمان بین خرابی‌ها", "success", "📈"), ("cost", "هزینهٔ یک‌سال", "info", "💵")])
        rl.addWidget(cards)
        self.card_tabs = QTabWidget()
        self.ident = QLabel("")
        self.ident.setWordWrap(True)
        self.ident.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.ident.setAlignment(Qt.AlignTop | Qt.AlignLeading)
        self.card_tabs.addTab(scrolled(self.ident), "شناسنامه")
        self.t_wo = table(["شماره", "نوع کار", "عنوان", "وضعیت", "ایجاد", "بسته‌شده"])
        self.t_wo.cellDoubleClicked.connect(lambda _r, _c: self._open_wo())
        self.card_tabs.addTab(self.t_wo, "سوابق تعمیر")
        self.t_plans = table(["کد", "عنوان", "مبنا", "سررسید", "وضعیت"])
        self.card_tabs.addTab(self.t_plans, "نگهداری پیشگیرانه")
        self.t_down = table(["نوع", "شروع", "آماده‌به‌کاری", "مدت (ساعت)"])
        self.card_tabs.addTab(self.t_down, "توقف‌ها")
        self.t_docs = table(["نوع", "فایل"])
        self.card_tabs.addTab(self.t_docs, "مدارک و دفترچه‌ها")
        rl.addWidget(self.card_tabs, stretch=1)
        split.addWidget(right)
        split.setSizes([380, 820])
        outer.addWidget(split, stretch=1)
        b = _btns(self, [("profile", "مشخصات نگهداری", self.edit_profile), ("request", "درخواست تعمیر این تجهیز", self.new_request),
                         ("codes", "کدهای خرابی", self.manage_codes), ("label", "ذخیرهٔ برچسب QR", self.save_label),
                         ("refresh", "به‌روزرسانی", self.refresh),
                         ("report", "گزارش کامل", lambda: _open_report(self._main_window, "MNT_RELIABILITY"))])
        outer.addWidget(ms.footer([[b["profile"], b["codes"]], [b["request"], b["label"]], [b["refresh"], b["report"]]]))
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.lk = _Lookups(cid)
        uid = user_id()
        self.buttons["profile"].setEnabled(c.can(cid, uid, c.FORM_MANAGE) and can("mnt_equipment", "EDIT"))
        self.buttons["codes"].setEnabled(c.can(cid, uid, c.FORM_MANAGE))
        self.buttons["request"].setEnabled(c.can(cid, uid, c.FORM_REQUEST, "CREATE"))
        self.tree.clear()
        for node in eq.tree(cid):
            self.tree.addTopLevelItem(self._node(node))
        self.tree.expandAll()
        self.tree.resizeColumnToContents(0)

    def _node(self, node) -> QTreeWidgetItem:
        status = ""
        if node.kind == "ASSET":
            e = node.item
            status = ("⛔ متوقف" if e.down_now else e.status_label) + (P(f" — {e.open_work_orders} کار باز") if e.open_work_orders else "")
        item = QTreeWidgetItem([P(node.label), status])
        item.setData(0, Qt.UserRole, node.id if node.kind == "ASSET" else None)
        if node.kind == "ASSET" and node.item.down_now:
            item.setForeground(1, _RED)
        for ch in node.children:
            item.addChild(self._node(ch))
        return item

    def _tree_selected(self) -> None:
        items = self.tree.selectedItems()
        aid = items[0].data(0, Qt.UserRole) if items else None
        if aid:
            self.load_card(aid)

    def select(self, asset_id: int) -> bool:
        def walk(item):
            if item.data(0, Qt.UserRole) == asset_id:
                return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found:
                    return found
            return None

        for i in range(self.tree.topLevelItemCount()):
            found = walk(self.tree.topLevelItem(i))
            if found:
                self.tree.setCurrentItem(found)
                self.load_card(asset_id)
                return True
        self.load_card(asset_id)
        return True

    def find(self) -> int | None:
        aid = eq.find(company_id(), self.find_box.text())
        if aid is None:
            _warn(self, "تجهیزات", "تجهیزی با این کد یا برچسب پیدا نشد.")
            return None
        self.select(aid)
        return aid

    def load_card(self, asset_id: int) -> None:
        k = self.card_data = eq.card(company_id(), asset_id)
        self.cards["status"].setText(("متوقف از " + _dt(k.down_since)) if k.down_now else k.status_label)
        self.cards["mttr"].setText(k.kpi.mttr.display if k.kpi.mttr.insufficient else _hours(k.kpi.mttr.value))
        self.cards["mtbf"].setText(k.kpi.mtbf.display if k.kpi.mtbf.insufficient else _hours(k.kpi.mtbf.value))
        self.cards["cost"].setText(k.kpi.cost.display if k.kpi.cost.insufficient else decimals.format_amount(k.kpi.cost.value))
        specs = "، ".join(f"{n}: {v}" for n, v in k.technical_specs) or "—"
        warr = "، ".join(f"{w.type} تا {_dt(w.end)}" + (" (فعال)" if w.active else "") for w in k.warranties) or "—"
        rows = [("کد", k.code), ("نام", k.name), ("نوع", k.type_label), ("شماره سریال", k.serial_no or "—"),
                ("سازنده", k.manufacturer or "—"), ("مدل", k.model or "—"), ("شمارهٔ قطعه", k.part_no or "—"),
                ("محل نصب", k.location or "—"), ("خط تولید", k.line or "—"), ("تاریخ بهره‌برداری", _dt(k.in_service_date)),
                ("وضعیت", k.status_label), ("اهمیت", k.criticality_label), ("تجهیز والد", k.parent or "—"),
                ("زیرتجهیزها", "، ".join(ch.label for ch in k.children) or "—"), ("ماشین تولیدی", "بله" if k.is_production_machine else "خیر"),
                ("تامین‌کننده", k.supplier or "—"), ("پیمانکار خدمات", k.service_supplier or "—"), ("ضمانت", warr),
                ("مسئول نگهداری", k.responsible or "—"), ("تکنسین پیش‌فرض", k.default_technician or "—"),
                ("واحد شمارنده", k.meter_unit or "—"), ("مشخصات فنی", specs), ("نکات ایمنی", k.safety_notes or "—"),
                ("درخواست باز", P(k.open_requests)), ("برنامهٔ پیشگیرانهٔ فعال", P(k.pm_plans)), ("توضیح", k.notes or "—")]
        self.ident.setText(P("<br>".join(f"<b>{a}:</b> {b}" for a, b in rows)))
        fill(self.t_wo, [[P(w.wo_no), w.work_type_label, w.title, w.status_label, _dt(w.created_at), _dt(w.closed_at)]
                         for w in k.work_orders], [w.work_order_id for w in k.work_orders])
        fill(self.t_plans, [[p.code, p.title, p.trigger_label, _dt(p.due.due_date), p.due.state_label] for p in k.plans])
        fill(self.t_down, [[d.type_label, _dt(d.down_from), _dt(d.available_at), _qty(d.hours)] for d in k.downtimes])
        fill(self.t_docs, [[d.type_label, d.file_name] for d in k.documents])

    def _asset(self):
        if self.card_data is None:
            _warn(self, "تجهیزات", "یک تجهیز را انتخاب کنید.")
        return self.card_data

    def _open_wo(self) -> None:
        wid = _selected(self.t_wo)
        if wid is not None:
            _exec(self, WorkOrderDialog(wid, self.lk, self))

    def edit_profile(self) -> bool:
        k = self._asset()
        if k is None:
            return False
        crit = combo(_labels(c.CRITICALITY_LABELS))
        set_combo(crit, k.criticality_code or "MEDIUM")
        resp, tech, sup = combo(self.lk.users, "—"), combo(self.lk.users, "—"), combo(self.lk.suppliers, "—")
        set_combo(resp, k.responsible_user_id)
        set_combo(tech, k.default_technician_user_id)
        set_combo(sup, k.service_supplier_detail_account_id)
        specs = _text("\n".join(f"{n}: {v}" for n, v in k.technical_specs), 120)
        values = _ask(self, "مشخصات نگهداری", [
            ("crit", "اهمیت", crit), ("resp", "مسئول نگهداری", resp), ("tech", "تکنسین پیش‌فرض", tech),
            ("sup", "پیمانکار خدمات", sup), ("meter", "واحد شمارنده", QLineEdit(k.meter_unit or "")),
            ("specs", "مشخصات فنی (هر خط: عنوان: مقدار)", specs), ("safety", "نکات ایمنی", _text(k.safety_notes)),
            ("notes", "توضیح", _text(k.notes))],
            "نام، کد، سریال، سازنده، مدل، محل و تامین‌کننده از خود دارایی خوانده می‌شود و این‌جا تکرار نمی‌شود.")
        if values is None:
            return False
        pairs = []
        for line in (values.get("specs") or "").splitlines():
            name, _sep, value = line.partition(":")
            if name.strip():
                pairs.append((name.strip(), value.strip()))
        _r, ok = _run(self, "مشخصات نگهداری", eq.save_profile, company_id(), user_id(), k.asset_id, criticality_code=values["crit"],
                      technical_specs=pairs, meter_unit=values.get("meter"), responsible_user_id=values.get("resp"),
                      default_technician_user_id=values.get("tech"), service_supplier_detail_account_id=values.get("sup"),
                      safety_notes=values.get("safety"), notes=values.get("notes"))
        if ok:
            self.load_card(k.asset_id)
        return ok

    def new_request(self) -> int | None:
        k = self._asset()
        if k is None:
            return None
        helper = RequestQueueScreen(self._main_window)
        helper.dialog_runner = self.dialog_runner
        helper.lk = self.lk
        rid = helper.new_request(k.asset_id)
        if rid:
            self.load_card(k.asset_id)
        return rid

    def manage_codes(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("کدهای خرابی")
        dlg.setLayoutDirection(Qt.RightToLeft)
        dlg.setMinimumSize(640, 420)
        lay = QVBoxLayout(dlg)
        t = table(["نوع", "کد", "شرح", "فعال"])
        lay.addWidget(t)

        def load():
            rows = eq.list_failure_codes(company_id())
            fill(t, [[r.kind_label, r.code, r.name, "بله" if r.is_active else "خیر"] for r in rows], [r.failure_code_id for r in rows])

        def add():
            values = _ask(dlg, "کد خرابی", [("kind", "نوع", combo(_labels(c.FAILURE_KIND_LABELS))), ("code", "کد", QLineEdit()),
                                            ("name", "شرح", QLineEdit())])
            if values is not None:
                _r, ok = _run(dlg, "کد خرابی", eq.save_failure_code, company_id(), user_id(), values["kind"], values.get("code") or "",
                              values.get("name") or "")
                if ok:
                    load()

        b = QPushButton("کد جدید")
        b.clicked.connect(lambda _c=False: add())
        lay.addWidget(ms.footer([[b]]))
        ms.apply(dlg)
        load()
        _exec(self, dlg)
        self.lk = _Lookups(company_id())

    def save_label(self):
        k = self._asset()
        if k is None:
            return None
        from peecha.services.fixed_assets import assets as fa
        from peecha.ui.screens.fixed_assets import asset_label_image

        image = asset_label_image(fa.get_asset(company_id(), k.asset_id))
        path, _ = QFileDialog.getSaveFileName(self, "ذخیرهٔ برچسب QR", f"{k.code}.png", "PNG (*.png)") if self.isVisible() else ("", "")
        if path:
            image.save(path)
        return image


# =========================================================================================================
# توقف‌ها و ظرفیت ماشین
# =========================================================================================================
@ms.styled
class AvailabilityScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.lk: _Lookups | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.addWidget(ms.header_card(_title("توقف‌ها و ظرفیت ماشین")))
        outer.addWidget(_hint("ظرفیت تولید از همین وضعیت‌ها خوانده می‌شود: ماشین متوقف ظرفیت ندارد؛ توقف برنامه‌ریزی‌شده و ظرفیت محدود "
                              "پس از تأیید و فقط با کلید مربوط از عدد ظرفیت کم می‌شود، ولی هشدارش همیشه در برنامه‌ریزی تولید دیده می‌شود."))
        cards, self.cards = ms.summary([("down", "ماشین متوقف", "danger", "⛔"), ("windows", "توقف برنامه‌ریزی‌شده", "info", "🗓️"),
                                        ("limits", "ظرفیت محدود", "warning", "📉"), ("pending", "منتظر تأیید", "info", "⏳")])
        outer.addWidget(cards)
        self.tabs = QTabWidget()
        w = QWidget()
        lay = QVBoxLayout(w)
        self.t_open = table(["تجهیز", "نوع توقف", "شروع", "مدت تا اکنون (ساعت)", "درخواست", "دستور کار", "توضیح"])
        lay.addWidget(self.t_open, stretch=1)
        b = _btns(self, [("release", "آماده‌به‌کاری بدون دستور کار", self.release)])
        lay.addWidget(ms.footer([[b["release"]]]))
        self.tabs.addTab(w, "توقف‌های باز")
        w = QWidget()
        lay = QVBoxLayout(w)
        self.t_win = table(["تجهیز", "شروع", "پایان", "ساعت", "وضعیت", "علت"])
        lay.addWidget(self.t_win, stretch=1)
        b = _btns(self, [("win_new", "توقف برنامه‌ریزی‌شدهٔ جدید", self.new_window),
                         ("win_ok", "تأیید توقف", lambda: self.decide_window(True)),
                         ("win_cancel", "لغو توقف", lambda: self.decide_window(False))])
        lay.addWidget(ms.footer([[b["win_new"]], [b["win_ok"], b["win_cancel"]]]))
        self.tabs.addTab(w, "توقف برنامه‌ریزی‌شده")
        w = QWidget()
        lay = QVBoxLayout(w)
        self.t_lim = table(["تجهیز", "ظرفیت در دسترس٪", "از", "تا", "وضعیت", "علت"])
        lay.addWidget(self.t_lim, stretch=1)
        b = _btns(self, [("lim_new", "ظرفیت محدود جدید", self.new_limit), ("lim_ok", "تأیید محدودیت", lambda: self.decide_limit(True)),
                         ("lim_cancel", "لغو محدودیت", lambda: self.decide_limit(False)), ("lim_end", "پایان محدودیت", self.end_limit)])
        lay.addWidget(ms.footer([[b["lim_new"]], [b["lim_ok"], b["lim_cancel"], b["lim_end"]]]))
        self.tabs.addTab(w, "ظرفیت محدود")
        w = QWidget()
        lay = QVBoxLayout(w)
        self.t_hist = table(["تجهیز", "نوع", "شروع", "آماده‌به‌کاری", "مدت (ساعت)", "وضعیت"])
        lay.addWidget(self.t_hist, stretch=1)
        b = _btns(self, [("report", "گزارش کامل", lambda: _open_report(self._main_window, "MNT_DOWNTIME"))])
        lay.addWidget(ms.footer([[b["report"]]]))
        self.tabs.addTab(w, "سوابق توقف")
        outer.addWidget(self.tabs, stretch=1)
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.lk = _Lookups(cid)
        uid = user_id()
        self.buttons["release"].setEnabled(c.can(cid, uid, c.FORM_VERIFY))
        for key in ("win_new", "lim_new"):
            self.buttons[key].setEnabled(c.can(cid, uid, c.FORM_PLAN) and can("mnt_availability", "EDIT"))
        for key in ("win_ok", "win_cancel", "lim_ok", "lim_cancel", "lim_end"):
            self.buttons[key].setEnabled(c.can(cid, uid, c.FORM_APPROVE))
        self.reload()

    def reload(self) -> None:
        cid = company_id()
        self.open_rows = av.list_downtimes(cid, open_only=True)
        fill(self.t_open, [[d.asset_label, d.type_label, _dt(d.down_from), _qty(d.hours), "دارد" if d.request_id else "",
                            "دارد" if d.work_order_id else "", d.note or ""] for d in self.open_rows],
             [d.downtime_id for d in self.open_rows])
        self.windows = av.list_windows(cid)
        fill(self.t_win, [[w.asset_label, _dt(w.start_at), _dt(w.end_at), _qty(w.hours), w.status_label, w.reason or ""]
                          for w in self.windows], [w.window_id for w in self.windows])
        self.limits = av.list_restrictions(cid)
        fill(self.t_lim, [[x.asset_label, P(decimals.format_qty(x.percent)), _dt(x.start_date), _dt(x.end_date), x.status_label, x.reason]
                          for x in self.limits], [x.restriction_id for x in self.limits])
        hist = av.list_downtimes(cid)[:500]
        fill(self.t_hist, [[d.asset_label, d.type_label, _dt(d.down_from), _dt(d.available_at), _qty(d.hours),
                            "باز" if d.is_open else "بسته"] for d in hist])
        self.cards["down"].setText(P(len({d.asset_id for d in self.open_rows})))
        self.cards["windows"].setText(P(sum(1 for w in self.windows if w.status_code == "APPROVED")))
        self.cards["limits"].setText(P(sum(1 for x in self.limits if x.status_code == "APPROVED")))
        self.cards["pending"].setText(P(sum(1 for w in self.windows if w.status_code == "PROPOSED")
                                        + sum(1 for x in self.limits if x.status_code == "PROPOSED")))

    def _done(self, ok: bool, text: str) -> bool:
        if ok:
            theme.set_status_label(self.status_label, text, ok=True)
            self.reload()
        return ok

    def release(self) -> bool:
        did = _selected(self.t_open)
        if did is None:
            _warn(self, "آماده‌به‌کاری", "یک توقف را انتخاب کنید.")
            return False
        values = _ask(self, "آماده‌به‌کاری بدون دستور کار", [("at", "زمان آماده‌به‌کاری", DateTimeField()), ("note", "علت", _text())],
                      "توقفی که دستور کار دارد فقط از همان دستور کار و پس از آزمون آماده‌به‌کار می‌شود.")
        if values is None:
            return False
        _r, ok = _run(self, "آماده‌به‌کاری", av.release_downtime, company_id(), user_id(), did, values["at"], values.get("note"))
        return self._done(ok, "آماده‌به‌کاری ثبت شد.")

    def new_window(self) -> int | None:
        start = datetime.datetime.now().astimezone() + datetime.timedelta(days=1)
        values = _ask(self, "توقف برنامه‌ریزی‌شده", [("asset", "تجهیز", combo(self.lk.equipment)), ("start", "شروع", DateTimeField(start)),
                                                     ("end", "پایان", DateTimeField(start + datetime.timedelta(hours=4))),
                                                     ("reason", "علت", QLineEdit())])
        if values is None:
            return None
        wid, ok = _run(self, "توقف برنامه‌ریزی‌شده", av.propose_window, company_id(), user_id(), values["asset"], values["start"],
                       values["end"], values.get("reason"))
        self._done(ok, "پیشنهاد ثبت شد و منتظر تأیید است.")
        return wid if ok else None

    def decide_window(self, approve: bool) -> bool:
        wid = _selected(self.t_win)
        if wid is None:
            _warn(self, "توقف برنامه‌ریزی‌شده", "یک ردیف را انتخاب کنید.")
            return False
        note = None
        if not approve:
            values = _ask(self, "لغو توقف", [("note", "علت لغو", _text())])
            if values is None:
                return False
            note = values.get("note")
        _r, ok = _run(self, "توقف برنامه‌ریزی‌شده", av.decide_window, company_id(), user_id(), wid, approve, note)
        return self._done(ok, "تأیید شد." if approve else "لغو شد.")

    def new_limit(self) -> int | None:
        values = _ask(self, "ظرفیت محدود", [("asset", "تجهیز", combo(self.lk.equipment)),
                                            ("pct", "ظرفیت در دسترس (درصد)", num_field(50)), ("start", "از تاریخ", date_field()),
                                            ("end", "تا تاریخ", date_field(datetime.date.today() + datetime.timedelta(days=7))),
                                            ("reason", "علت", QLineEdit())],
                      "ماشینی که با سرعت یا ظرفیت کمتر کار می‌کند؛ توقف کامل را با درخواست تعمیر یا توقف ثبت کنید.")
        if values is None:
            return None
        rid, ok = _run(self, "ظرفیت محدود", av.propose_restriction, company_id(), user_id(), values["asset"], values.get("pct") or 0,
                       values["start"], values["end"], values.get("reason") or "")
        self._done(ok, "پیشنهاد ثبت شد و منتظر تأیید است.")
        return rid if ok else None

    def decide_limit(self, approve: bool) -> bool:
        rid = _selected(self.t_lim)
        if rid is None:
            _warn(self, "ظرفیت محدود", "یک ردیف را انتخاب کنید.")
            return False
        note = None
        if not approve:
            values = _ask(self, "لغو محدودیت", [("note", "علت لغو", _text())])
            if values is None:
                return False
            note = values.get("note")
        _r, ok = _run(self, "ظرفیت محدود", av.decide_restriction, company_id(), user_id(), rid, approve, note)
        return self._done(ok, "تأیید شد." if approve else "لغو شد.")

    def end_limit(self) -> bool:
        rid = _selected(self.t_lim)
        if rid is None:
            _warn(self, "ظرفیت محدود", "یک ردیف را انتخاب کنید.")
            return False
        values = _ask(self, "پایان محدودیت", [("end", "آخرین روز محدودیت", date_field())])
        if values is None:
            return False
        _r, ok = _run(self, "ظرفیت محدود", av.end_restriction, company_id(), user_id(), rid, values["end"])
        return self._done(ok, "پایان محدودیت ثبت شد.")


# =========================================================================================================
# تنظیمات
# =========================================================================================================
@ms.styled
class MntSettingsScreen(FieldHelpMixin, QWidget):
    """کلیدهای نگهداری (همان قابلیت‌های فعال انبار) + نقش‌های آماده."""

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.addWidget(_title("تنظیمات نگهداری و تعمیرات"))
        outer.addWidget(_hint("همهٔ کلیدها پیش‌فرض خاموش‌اند؛ تا روشن نشوند ظرفیت تولید، وضعیت دارایی و دسترسی‌ها مثل قبل رفتار می‌کنند. "
                              "حساب «هزینهٔ قطعات تعمیر و نگهداری» در تنظیمات انبار › تنظیم حساب‌ها و حساب «هزینهٔ تعمیر و نگهداری» "
                              "در طبقهٔ دارایی تعیین می‌شود."))
        self.toggles: dict[str, QCheckBox] = {}
        self.toggle_box = QWidget()
        self.toggle_layout = QVBoxLayout(self.toggle_box)
        self.toggle_layout.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.toggle_box)
        sep = QLabel("نقش‌ها")
        sep.setObjectName("sectionTitle")
        outer.addWidget(sep)
        self.roles_hint = _hint("شش نقش آماده: درخواست‌کننده، برنامه‌ریز، تکنسین، سرپرست، انباردار قطعات و تأییدکنندهٔ نگهداری و مالی. "
                                "اجرای دوباره نقش تکراری نمی‌سازد.")
        outer.addWidget(self.roles_hint)
        self.roles_btn = QPushButton("ساخت نقش‌های آمادهٔ نگهداری")
        self.roles_btn.clicked.connect(lambda _c=False: self.make_roles())
        outer.addWidget(ms.footer([[self.roles_btn]]))
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)
        outer.addStretch(1)
        self.set_field_help([(self.roles_btn, "نقش‌های آماده را روی همان جدول نقش‌ها می‌سازد؛ کاربران را از «مدیریت سیستم › نقش‌ها» "
                                              "به هر نقش وصل کنید.")])

    def refresh(self) -> None:
        from peecha.services import inventory_engine as engine

        cid = company_id()
        if cid is None:
            return
        allowed = c.can(cid, user_id(), c.FORM_MANAGE) and can("mnt_settings", "EDIT")
        self.roles_btn.setEnabled(allowed)
        features = {f.feature_code: f for f in engine.list_features(cid)}
        if not self.toggles:   # کلیدها یک بار ساخته می‌شوند؛ بعد فقط وضعیتشان تازه می‌شود
            descriptions = engine.feature_descriptions()
            helps = []
            for code in _MNT_TOGGLES:
                f = features.get(code)
                if f is None:
                    continue
                box = QCheckBox(f.name)
                box.toggled.connect(lambda checked, k=code: self._toggle(k, checked))
                self.toggles[code] = box
                self.toggle_layout.addWidget(box)
                self.toggle_layout.addWidget(_hint(descriptions.get(code, "")))
                helps.append((box, descriptions.get(code, "") or f.name))
            self.set_field_help(helps)
        for code, box in self.toggles.items():
            box.blockSignals(True)
            box.setChecked(features[code].is_enabled)
            box.blockSignals(False)
            box.setEnabled(allowed)

    def _toggle(self, code: str, checked: bool) -> None:
        from peecha.services import inventory_engine as engine

        _r, ok = _run(self, "تنظیمات نگهداری", engine.set_feature_enabled, company_id(), code, checked)
        if not ok:
            box = self.toggles[code]
            box.blockSignals(True)
            box.setChecked(not checked)
            box.blockSignals(False)

    def make_roles(self) -> dict | None:
        from peecha.services.maintenance import roles_setup

        roles, ok = _run(self, "نقش‌ها", roles_setup.ensure_role_templates, company_id())
        if ok:
            theme.set_status_label(self.status_label, P(f"{len(roles)} نقش آماده است."), ok=True)
        return roles if ok else None
