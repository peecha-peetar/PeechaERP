"""صفحه‌های بودجه‌ریزی و کنترل بودجه (R313) — هم‌شکل بقیهٔ ماژول‌ها: دکمه‌های آیکونی، کارت خلاصه، جدول و فرم کوچک عملیات.

داشبورد کنترل (مانده و ریز مصرف تا سند منبع)، بودجه‌ها و پروندهٔ نسخه (ردیف، توزیع دوره‌ای، گردش تأیید، اصلاحیه)،
مجوزهای تجاوز، بستن تعهد سفارش و تنظیمات (چرخ‌دندهٔ کنار منو). همهٔ منطق در services/budgeting است.
"""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services import stock_controls
from peecha.services.budgeting import approval as bap
from peecha.services.budgeting import budgets as bud
from peecha.services.budgeting import common as c
from peecha.services.budgeting import exceptions as bex
from peecha.services.budgeting import ledger as bl
from peecha.services.budgeting import reports as brep
from peecha.ui import theme
from peecha.ui.screens import module_style as ms
from peecha.ui.screens.costing import can
from peecha.ui.screens.fixed_assets import P, combo, company_id, fill, num_field, set_combo, table, user_id
from peecha.ui.screens.purchase_reports import _TYPE_TO_NAV_CODE
from peecha.ui.screens.quality import _ask, _buttons as _btns, _confirm, _fill_result, _hint, _run, _selected, _text, _title, _warn
from peecha.ui.widgets import FieldHelpMixin, JalaliDateEdit

ms.ICONS.update({
    # بودجه و نسخه
    "بودجهٔ جدید": ("🆕", "primary"), "ویرایش بودجه": ("✏️", ""), "ردیف جدید": ("➕", "primary"), "ویرایش ردیف": ("✏️", ""),
    "حذف ردیف": ("🗑️", "danger"), "توزیع دوره‌ای": ("🗓️", ""), "مبلغ مصوب": ("💰", ""), "ارسال برای بررسی": ("📨", "primary"),
    "بررسی مسئول بودجه": ("🔍", "primary"), "تأیید مدیر": ("✅", "primary"), "انتشار نسخهٔ مصوب": ("📢", "primary"),
    "رد نسخه": ("❌", "danger"), "بازگشت به پیش‌نویس": ("↩️", ""), "لغو نسخه": ("🚫", "danger"), "اصلاحیهٔ جدید": ("📝", ""),
    "بودجهٔ تکمیلی": ("➕", ""), "انتقال بودجهٔ سادهٔ خرید": ("📥", ""), "بستن دوره": ("🔒", ""), "بازگشایی دوره": ("🔓", ""),
    # داشبورد و مجوز
    "ریز مصرف": ("🔎", ""), "تطبیق دوباره با اسناد": ("🔄", ""), "تأیید مجوز": ("✅", "primary"), "رد مجوز": ("❌", "danger"),
    "لغو درخواست مجوز": ("🗑️", "danger"), "باز کردن سند": ("📂", ""), "بستن تعهد باقی‌مانده": ("🔒", "primary"),
    "بازگشایی تعهد": ("🔓", ""), "ذخیرهٔ سیاست کنترل": ("💾", "primary"), "ساخت نقش‌های آمادهٔ بودجه": ("👥", "primary"),
})

_RED, _AMBER, _GREEN, _GREY = QColor("#EF4444"), QColor("#F59E0B"), QColor("#10B981"), QColor("#94A3B8")
_STATE_TONE = {"عبور از بودجه": _RED, "نزدیک به سقف": _AMBER, "بدون مصرف": _GREY}


def _tone(t, row: int, color: QColor | None) -> None:
    if color is None:
        return
    for col in range(t.columnCount()):
        item = t.item(row, col)
        if item is not None:
            item.setForeground(color)


def _money(v) -> str:
    return numerals.format_money(c.dec(v), 0, None) if v is not None else "—"


def _labels(mapping: dict) -> list[tuple[str, str]]:
    return [(v, k) for k, v in mapping.items()]


def _open_doc(main_window, document_id: int, doc_type: str) -> None:
    if main_window is None:
        return
    if doc_type == "JOURNAL_ENTRY":
        main_window.open_screen("GL_JE", then=lambda s: s.edit_journal_entry(document_id))
        return
    nav = _TYPE_TO_NAV_CODE.get(doc_type)
    if nav:
        main_window.open_screen(nav, then=lambda s: s.edit_document(document_id))


def _open_report(main_window, code: str, date_from=None, date_to=None) -> None:
    if main_window is not None:
        main_window.open_screen(f"BUD_RPT_{code}", then=lambda s: s.apply_preset(date_from, date_to, {}))


def _fiscal_bounds() -> tuple[datetime.date, datetime.date]:
    today = datetime.date.today()
    cid = company_id()
    if cid is not None:
        from peecha.services import fiscal_years

        fy = fiscal_years.pick_current(cid, today)
        if fy is not None:
            return fy.start_date, fy.end_date
    return today.replace(month=1, day=1), today


class _Lookups:
    def __init__(self, cid: int) -> None:
        from peecha.services import chart_of_accounts as coa
        from peecha.services import detail_dimensions as dims
        from peecha.services import fiscal_years
        from peecha.services import inventory_catalog as catalog
        from peecha.services import procurement_masters as masters
        from peecha.services.crm.common import list_company_users

        cc_type = dims.get_specialized_dimension_type_id(cid, dims.COST_CENTER_CODE)
        pj_type = dims.get_specialized_dimension_type_id(cid, dims.PROJECT_CODE)
        self.cost_centers = [(f"{d.code} — {d.name or ''}", d.detail_account_id) for d in dims.list_leaf_detail_accounts(cid, cc_type)]
        self.projects = [(f"{d.code} — {d.name or ''}", d.detail_account_id) for d in dims.list_leaf_detail_accounts(cid, pj_type)]
        self.accounts = [(f"{a.full_code} — {a.name}", a.account_id) for a in coa.list_accounts(cid)]
        self.branches = [(b.name, b.branch_id) for b in masters.list_branches(cid)]
        self.departments = [(d.name, d.org_unit_id) for d in masters.list_departments(cid)]
        self.categories = [(f"{g.code} — {g.name}", g.category_id) for g in catalog.list_categories(cid)]
        self.purchase_types = [(t.name, t.purchase_type_id) for t in masters.list_purchase_types(cid)]
        self.users = [(name, uid) for uid, name in list_company_users(cid)]
        self.fiscal_years = [(f.code, f.fiscal_year_id) for f in fiscal_years.list_fiscal_years(cid)]


# =========================================================================================================
# داشبورد کنترل بودجه
# =========================================================================================================
@ms.styled
class BudgetCenterScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.rows: list = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        self.budget = combo([], "همهٔ بودجه‌ها")
        self.date_from, self.date_to = JalaliDateEdit(), JalaliDateEdit()
        for w in (self.budget,):
            w.currentIndexChanged.connect(lambda _i: self.reload())
        outer.addWidget(ms.header_card(_title("داشبورد کنترل بودجه"), QLabel("بودجه:"), self.budget, QLabel("از:"), self.date_from,
                                       QLabel("تا:"), self.date_to))
        cards, self.cards = ms.summary([("budget", "بودجهٔ بازه", "info", "💰"), ("actual", "هزینهٔ واقعی", "success", "🧾"),
                                        ("commit", "تعهد باز", "warning", "📌"), ("pre", "پیش‌تعهد", "info", "📝"),
                                        ("available", "ماندهٔ قابل تعهد", "success", "✅"), ("used", "درصد مصرف", "info", "📊"),
                                        ("over", "ردیف عبورکرده", "danger", "⛔"), ("pending", "مجوز منتظر", "warning", "🛂")])
        outer.addWidget(cards)
        split = QSplitter(Qt.Vertical)
        self.t = table(["بودجه", "ردیف بودجه", "مبنا", "مسئول", "بودجهٔ بازه", "پیش‌تعهد", "تعهد", "واقعی", "ماندهٔ قابل تعهد",
                        "درصد مصرف", "وضعیت"])
        self.t.itemSelectionChanged.connect(self._show_detail)
        split.addWidget(self.t)
        box = QWidget()
        bl_ = QVBoxLayout(box)
        bl_.setContentsMargins(0, 0, 0, 0)
        bl_.addWidget(_hint("ریز مصرف ردیف انتخاب‌شده تا سند منبع، با وضعیت فعلی سند؛ دوبار کلیک سند را باز می‌کند."))
        self.t_detail = table([])
        self.t_detail.cellDoubleClicked.connect(self._open_detail)
        bl_.addWidget(self.t_detail)
        split.addWidget(box)
        outer.addWidget(split, stretch=1)
        b = _btns(self, [("refresh", "به‌روزرسانی", self.refresh), ("detail", "ریز مصرف", self.open_detail_report),
                         ("report", "گزارش کامل", lambda: _open_report(self._main_window, "BUD_VS_ACTUAL", self.date_from.date(),
                                                                         self.date_to.date())),
                         ("resync", "تطبیق دوباره با اسناد", self.resync)])
        outer.addWidget(ms.footer([[b["refresh"], b["detail"], b["report"]], [b["resync"]]]))
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)
        self._detail_refs: list = []
        d0, d1 = _fiscal_bounds()
        self.date_from.setDate(d0)
        self.date_to.setDate(d1)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        current = self.budget.currentData()
        self.budget.blockSignals(True)
        self.budget.clear()
        self.budget.addItem("همهٔ بودجه‌ها", None)
        for b in bud.list_budgets(cid):
            self.budget.addItem(P(f"{b.code} — {b.name}"), b.budget_id)
        set_combo(self.budget, current)
        self.budget.blockSignals(False)
        self.buttons["resync"].setEnabled(c.can(cid, user_id(), c.FORM_PUBLISH))
        self.reload()

    def _filters(self):
        from peecha.services import purchase_reports as pr

        return pr.PurchaseFilters(self.date_from.date(), self.date_to.date(), budget_id=self.budget.currentData())

    def reload(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.rows, _l = brep._data(cid, self._filters())
        fill(self.t, [[f"{s.budget.code} — {s.budget.name}", s.label, c.BASIS_LABELS[s.key.basis_code], s.responsible, s.budget_amount,
                       s.pre, s.commit, s.actual, s.available,
                       P(f"{numerals.format_money(s.consumed * 100 / s.budget_amount, 1, None)}٪") if s.budget_amount else "—", s.state]
                      for s in self.rows], [s.key.key_id for s in self.rows])
        for i, s in enumerate(self.rows):
            _tone(self.t, i, _STATE_TONE.get(s.state))
        tot = lambda attr: sum((getattr(s, attr) for s in self.rows), c.ZERO)  # noqa: E731
        self.cards["budget"].setText(P(_money(tot("budget_amount"))))
        self.cards["actual"].setText(P(_money(tot("actual"))))
        self.cards["commit"].setText(P(_money(tot("commit"))))
        self.cards["pre"].setText(P(_money(tot("pre"))))
        self.cards["available"].setText(P(_money(tot("available"))))
        self.cards["used"].setText(P(f"{numerals.format_money(tot('consumed') * 100 / tot('budget_amount'), 1, None)}٪")
                                   if tot("budget_amount") else "—")
        self.cards["over"].setText(P(sum(1 for s in self.rows if s.state == "عبور از بودجه")))
        self.cards["pending"].setText(P(len(bex.list_exceptions(cid, "PENDING"))))
        self._show_detail()

    def _show_detail(self) -> None:
        cid = company_id()
        key_id = _selected(self.t)
        if cid is None or key_id is None:
            self.t_detail.setRowCount(0)
            self._detail_refs = []
            return
        f = self._filters()
        f.options = {"key": key_id, "view": "NET"}
        result = brep.detail(cid, f)
        _fill_result(self.t_detail, result)
        self._detail_refs = list(result.refs)

    def _open_detail(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._detail_refs) and self._detail_refs[row]:
            doc_id, doc_type = self._detail_refs[row]
            _open_doc(self._main_window, doc_id, doc_type)

    def open_detail_report(self) -> None:
        key_id = _selected(self.t)
        if self._main_window is None:
            return
        d0, d1 = self.date_from.date(), self.date_to.date()
        if key_id is None:
            _open_report(self._main_window, "BUD_DETAIL", d0, d1)
        else:
            self._main_window.open_screen("BUD_RPT_BUD_DETAIL", then=lambda s: s.apply_budget_key(key_id, d0, d1))

    def resync(self) -> int | None:
        if not _confirm(self, "تطبیق دوباره", "همهٔ اسناد خرید با نسخه‌های منتشرشده تطبیق داده شوند؟ اختلاف‌ها با برچسب «تطبیق» ثبت می‌شوند."):
            return None
        n, ok = _run(self, "تطبیق دوباره", bl.resync, company_id(), user_id())
        if ok:
            theme.set_status_label(self.status_label, P(f"تطبیق انجام شد؛ {n} اختلاف ثبت شد."), ok=True)
            self.reload()
        return n if ok else None


# =========================================================================================================
# بودجه‌ها و پروندهٔ نسخه
# =========================================================================================================
@ms.styled
class BudgetsScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.confirm = None
        self.budgets: list = []
        self.budget = None
        self.version = None
        self.lk: _Lookups | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        self.version_box = QComboBox()
        self.version_box.currentIndexChanged.connect(lambda _i: self._load_version())
        outer.addWidget(ms.header_card(_title("بودجه‌ها و نسخه‌ها"), QLabel("نسخه:"), self.version_box))
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.t_budgets = table(["کد", "نام", "سال مالی", "دوره", "نسخهٔ منتشرشده", "نسخهٔ در جریان"])
        self.t_budgets.itemSelectionChanged.connect(self._load_budget)
        ll.addWidget(self.t_budgets)
        split.addWidget(left)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.head = _hint("")
        rl.addWidget(self.head)
        cards, self.cards = ms.summary([("status", "وضعیت", "info", "📌"), ("total", "جمع مصوب/پیشنهادی", "success", "💰"),
                                        ("change", "تغییر نسبت به نسخهٔ قبل", "warning", "↕️"), ("lines", "تعداد ردیف", "info", "🧮")])
        rl.addWidget(cards)
        self.problems = _hint("")
        rl.addWidget(self.problems)
        self.tabs = QTabWidget()
        self.t_lines = table([])
        self.t_lines.cellDoubleClicked.connect(lambda _r, _c: self.edit_line())
        self.tabs.addTab(self.t_lines, "ردیف‌ها و توزیع دوره‌ای")
        self.t_hist = table(["زمان", "گام", "وضعیت جدید", "کاربر", "نظر"])
        self.tabs.addTab(self.t_hist, "تاریخچهٔ تصمیم")
        self.t_periods = table(["دوره", "از", "تا", "وضعیت", "بسته‌شده توسط", "یادداشت"])
        self.tabs.addTab(self.t_periods, "دوره‌ها")
        rl.addWidget(self.tabs, stretch=1)
        split.addWidget(right)
        split.setStretchFactor(1, 3)
        outer.addWidget(split, stretch=1)
        b = _btns(self, [
            ("new_budget", "بودجهٔ جدید", self.new_budget), ("edit_budget", "ویرایش بودجه", self.edit_budget),
            ("add_line", "ردیف جدید", self.add_line), ("edit_line", "ویرایش ردیف", self.edit_line), ("del_line", "حذف ردیف", self.delete_line),
            ("periods", "توزیع دوره‌ای", self.distribute), ("approved", "مبلغ مصوب", self.set_approved),
            ("submit", "ارسال برای بررسی", self.submit), ("review", "بررسی مسئول بودجه", self.review), ("approve", "تأیید مدیر", self.approve),
            ("publish", "انتشار نسخهٔ مصوب", self.publish), ("reject", "رد نسخه", self.reject), ("reopen", "بازگشت به پیش‌نویس", self.reopen),
            ("cancel", "لغو نسخه", self.cancel), ("amend", "اصلاحیهٔ جدید", lambda: self.revision("AMENDMENT")),
            ("supplement", "بودجهٔ تکمیلی", lambda: self.revision("SUPPLEMENT")), ("import", "انتقال بودجهٔ سادهٔ خرید", self.import_simple),
            ("close_p", "بستن دوره", lambda: self.period(True)), ("open_p", "بازگشایی دوره", lambda: self.period(False)),
            ("refresh", "به‌روزرسانی", self.refresh)])
        outer.addWidget(ms.footer([[b["new_budget"], b["edit_budget"]], [b["add_line"], b["edit_line"], b["del_line"], b["periods"], b["import"]],
                                   [b["submit"], b["approved"], b["review"], b["approve"], b["publish"], b["reject"], b["reopen"], b["cancel"]],
                                   [b["amend"], b["supplement"], b["close_p"], b["open_p"], b["refresh"]]]))
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)

    # --- بارگذاری ---------------------------------------------------------------------------------------
    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.lk = _Lookups(cid)
        keep = self.budget.budget_id if self.budget else None
        self.budgets = bud.list_budgets(cid)
        fill(self.t_budgets, [[b.code, b.name, b.fiscal_year, b.period_label,
                               P(f"نسخهٔ {b.published_no}") if b.published_no else "ندارد", b.open_status_label] for b in self.budgets],
             [b.budget_id for b in self.budgets])
        if keep:
            self.select_budget(keep)
        elif self.budgets:
            self.t_budgets.selectRow(0)
        self._update_buttons()

    def select_budget(self, budget_id: int) -> None:
        for r in range(self.t_budgets.rowCount()):
            if self.t_budgets.item(r, 0).data(Qt.UserRole) == budget_id:
                self.t_budgets.setCurrentCell(r, 0)
                self._load_budget()
                return

    def open_version(self, version_id: int) -> None:
        """از کارتابل یا گردش کار: پروندهٔ همین نسخه."""
        cid = company_id()
        if cid is None:
            return
        v = bud.get_version(cid, version_id)
        self.select_budget(v.budget_id)
        set_combo(self.version_box, version_id)
        self._load_version()

    def _load_budget(self) -> None:
        cid = company_id()
        bid = _selected(self.t_budgets)
        if cid is None or bid is None:
            return
        self.budget = bud.get_budget(cid, bid)
        b = next((x for x in self.budgets if x.budget_id == bid), None)
        prefer = (b.open_version_id or b.published_version_id) if b else None
        self.version_box.blockSignals(True)
        self.version_box.clear()
        for v in reversed(self.budget.versions):
            self.version_box.addItem(P(f"{v.kind_label} {v.version_no} — {v.status_label}"), v.version_id)
        set_combo(self.version_box, prefer)
        self.version_box.blockSignals(False)
        fill(self.t_periods, [[p.label, p.date_from, p.date_to, "بسته" if p.is_closed else "باز", p.closed_by, p.close_note or ""]
                              for p in self.budget.periods], [p.period_no for p in self.budget.periods])
        self._load_version()

    def _load_version(self) -> None:
        cid = company_id()
        vid = self.version_box.currentData()
        if cid is None or vid is None or self.budget is None:
            self.version = None
            self._update_buttons()
            return
        self.version = v = bud.get_version(cid, vid)
        self.head.setText(P(f"{v.budget_code} — {v.budget_name} | {v.kind_label} {v.version_no}: {v.title} | اعتبار "
                            f"{numerals.format_jalali_date(v.valid_from)} تا {numerals.format_jalali_date(v.valid_to)} | "
                            f"تهیه‌کننده: {v.prepared_by or '—'}"))
        self.cards["status"].setText(v.status_label)
        self.cards["total"].setText(P(_money(v.total_amount)))
        self.cards["change"].setText(P(_money(v.total_amount - v.total_previous)) if v.based_on_version_id else "—")
        self.cards["lines"].setText(P(len(v.lines)))
        self.problems.setText(P("کامل نیست: " + " ".join(v.problems)) if v.problems and v.status_code == "DRAFT" else "")
        periods = self.budget.periods
        headers = ["ردیف", "مبنا", "ابعاد", "مسئول", "مبلغ قبلی", "پیشنهادی", "مصوب", "تغییر", "سیاست"] + [p.label for p in periods]
        self.t_lines.setColumnCount(len(headers))
        self.t_lines.setHorizontalHeaderLabels(headers)
        fill(self.t_lines, [[ln.line_no, ln.basis_label, ln.label, ln.responsible, ln.previous_amount, ln.proposed_amount, ln.approved_amount,
                             ln.change, ln.policy_label] + [ln.periods.get(p.period_no, c.ZERO) for p in periods] for ln in v.lines],
             [ln.line_id for ln in v.lines])
        fill(self.t_hist, [[numerals.format_jalali_datetime(d.at), d.action_label, d.to_label, d.user, d.comment or ""] for d in v.decisions])
        self._update_buttons()

    def _update_buttons(self) -> None:
        cid, uid = company_id(), user_id()
        if cid is None:
            return
        v = self.version
        acts = bap.allowed_actions(cid, uid, v) if v is not None else {}
        prepare = c.can(cid, uid, c.FORM_PREPARE) and can("bud_budgets", "EDIT")
        self.buttons["new_budget"].setEnabled(prepare)
        self.buttons["edit_budget"].setEnabled(prepare and self.budget is not None)
        for key in ("add_line", "edit_line", "del_line", "import"):
            self.buttons[key].setEnabled(bool(acts.get("edit")))
        self.buttons["periods"].setEnabled(bool(acts.get("edit") or acts.get("adjust")))
        self.buttons["approved"].setEnabled(bool(acts.get("adjust")))
        for key in ("submit", "review", "approve", "publish", "reject", "reopen", "cancel"):
            self.buttons[key].setEnabled(bool(acts.get(key)))
        published = self.budget is not None and any(x.status_code == "PUBLISHED" for x in self.budget.versions)
        open_v = self.budget is not None and any(x.status_code in c.OPEN_VERSION for x in self.budget.versions)
        self.buttons["amend"].setEnabled(prepare and published and not open_v)
        self.buttons["supplement"].setEnabled(prepare and published and not open_v)
        period_ok = c.can(cid, uid, c.FORM_PERIOD) and self.budget is not None
        self.buttons["close_p"].setEnabled(period_ok)
        self.buttons["open_p"].setEnabled(period_ok)

    def _done(self, text: str) -> None:
        theme.set_status_label(self.status_label, text, ok=True)
        keep = self.version.version_id if self.version else None
        self.refresh()
        if keep:
            set_combo(self.version_box, keep)
            self._load_version()

    def _line(self):
        lid = _selected(self.t_lines)
        if lid is None or self.version is None:
            _warn(self, "ردیف بودجه", "یک ردیف را انتخاب کنید.")
            return None
        return next((ln for ln in self.version.lines if ln.line_id == lid), None)

    # --- بودجه ------------------------------------------------------------------------------------------
    def new_budget(self) -> int | None:
        lk = self.lk or _Lookups(company_id())
        v = _ask(self, "بودجهٔ جدید", [
            ("fy", "سال مالی", combo(lk.fiscal_years)), ("code", "کد", QLineEdit()), ("name", "نام", QLineEdit()),
            ("period", "نوع دوره", combo(_labels(c.PERIOD_TYPE_LABELS))), ("owner", "مسئول بودجه", combo(lk.users, "—")),
            ("desc", "توضیح", _text())], "دوره‌ها از روی سال مالی ساخته می‌شوند و بعداً تغییر نمی‌کنند. نسخهٔ اولیه هم‌زمان ساخته می‌شود.")
        if v is None:
            return None
        bid, ok = _run(self, "بودجهٔ جدید", bud.create_budget, company_id(), user_id(), v["fy"], v["code"] or "", v["name"] or "",
                       v["period"], v["owner"], v["desc"])
        if ok:
            self._done("بودجه و نسخهٔ اولیه ساخته شد.")
            self.select_budget(bid)
        return bid if ok else None

    def edit_budget(self) -> bool:
        if self.budget is None:
            return False
        lk = self.lk or _Lookups(company_id())
        owner = combo(lk.users, "—")
        set_combo(owner, self.budget.owner_user_id)
        active = QCheckBox("فعال")
        active.setChecked(self.budget.is_active)
        name = QLineEdit(self.budget.name)
        v = _ask(self, "ویرایش بودجه", [("name", "نام", name), ("owner", "مسئول بودجه", owner), ("desc", "توضیح", _text(self.budget.description)),
                                       ("active", "", active)])
        if v is None:
            return False
        _r, ok = _run(self, "ویرایش بودجه", bud.update_budget, company_id(), user_id(), self.budget.budget_id, v["name"] or "", v["owner"],
                      v["desc"], v["active"])
        if ok:
            self._done("بودجه ذخیره شد.")
        return ok

    # --- ردیف -------------------------------------------------------------------------------------------
    def _line_fields(self, line=None) -> list:
        lk = self.lk or _Lookups(company_id())
        k = line.key if line else None

        def box(items, value, none="— همه —"):
            b = combo(items, none)
            set_combo(b, value)
            return b
        basis = combo(_labels(c.BASIS_LABELS))
        set_combo(basis, k.basis_code if k else "PURCHASE")
        policy = combo(_labels(c.POLICY_LABELS), "طبق سیاست شرکت")
        set_combo(policy, line.policy_code if line else None)
        dist = combo([("مساوی میان دوره‌ها", "EQUAL"), ("بر اساس وزن‌ها", "WEIGHTS")])
        return [("basis", "مبنا", basis), ("account", "حساب (فقط مبنای دفتر کل)", box(lk.accounts, k.account_id if k else None, "—")),
                ("cc", "مرکز هزینه", box(lk.cost_centers, k.cost_center_detail_account_id if k else None)),
                ("pj", "پروژه", box(lk.projects, k.project_detail_account_id if k else None)),
                ("branch", "شعبه", box(lk.branches, k.branch_id if k else None)),
                ("dept", "دپارتمان", box(lk.departments, k.org_unit_id if k else None)),
                ("cat", "گروه کالا", box(lk.categories, k.category_id if k else None)),
                ("ptype", "نوع خرید", box(lk.purchase_types, k.purchase_type_id if k else None)),
                ("amount", "مبلغ پیشنهادی", num_field(line.proposed_amount if line else None)),
                ("resp", "مسئول ردیف", box(lk.users, line.responsible_user_id if line else None, "—")),
                ("policy", "سیاست تجاوز این ردیف", policy), ("warn", "درصد هشدار این ردیف", num_field(line.warn_percent if line else None)),
                ("dist", "توزیع دوره‌ای", dist), ("weights", "وزن دوره‌ها (مثلاً ۱،۱،۲،...)", QLineEdit()),
                ("note", "توضیح", _text(line.note if line else None))]

    def _weights(self, text: str | None) -> tuple[list | None, bool]:
        if not text:
            return None, True
        try:
            return [decimal.Decimal(numerals.to_ascii_digits(x).strip()) for x in text.replace("،", ",").split(",") if x.strip()], True
        except decimal.InvalidOperation:
            _warn(self, "وزن دوره‌ها", "وزن‌ها را فقط با عدد و جداشده با ویرگول بنویسید.")
            return None, False

    def add_line(self) -> int | None:
        if self.version is None:
            return None
        v = _ask(self, "ردیف جدید بودجه", self._line_fields(),
                 "هر سند خرید فقط به دقیق‌ترین ردیف منطبق می‌خورد. بُعد خالی یعنی «همه». مبنای «حساب دفتر کل» فقط برای پایش هزینهٔ ثبت‌شده است.")
        if v is None:
            return None
        weights, ok = self._weights(v["weights"])
        if not ok:
            return None
        dims = bud.Dims(v["basis"], v["account"] if v["basis"] == "ACCOUNT" else None, v["cc"], v["pj"], v["branch"], v["dept"],
                        v["cat"], v["ptype"])
        lid, ok = _run(self, "ردیف جدید", bud.add_line, company_id(), user_id(), self.version.version_id, dims, v["amount"] or c.ZERO,
                       responsible_user_id=v["resp"], policy_code=v["policy"], warn_percent=v["warn"], note=v["note"],
                       method="WEIGHTS" if weights else v["dist"], weights=weights)
        if ok:
            self._done("ردیف اضافه شد.")
        return lid if ok else None

    def edit_line(self) -> bool:
        line = self._line()
        if line is None:
            return False
        fields = [f for f in self._line_fields(line) if f[0] not in ("basis", "account", "cc", "pj", "branch", "dept", "cat", "ptype")]
        v = _ask(self, "ویرایش ردیف بودجه", fields, f"ابعاد ردیف: {line.label} (برای تغییر ابعاد، ردیف جدید بسازید).")
        if v is None:
            return False
        weights, ok = self._weights(v["weights"])
        if not ok:
            return False
        _r, ok = _run(self, "ویرایش ردیف", bud.update_line, company_id(), user_id(), line.line_id, v["amount"] or c.ZERO,
                      responsible_user_id=v["resp"], policy_code=v["policy"], warn_percent=v["warn"], note=v["note"],
                      method="WEIGHTS" if weights else v["dist"], weights=weights)
        if ok:
            self._done("ردیف ذخیره شد.")
        return ok

    def delete_line(self) -> bool:
        line = self._line()
        if line is None or not _confirm(self, "حذف ردیف", "این ردیف از نسخهٔ پیش‌نویس حذف شود؟"):
            return False
        _r, ok = _run(self, "حذف ردیف", bud.delete_line, company_id(), user_id(), line.line_id)
        if ok:
            self._done("ردیف حذف شد.")
        return ok

    def distribute(self) -> bool:
        line = self._line()
        if line is None:
            return False
        fields = [(f"p{p.period_no}", p.label + (" (بسته)" if p.is_closed else ""), num_field(line.periods.get(p.period_no, c.ZERO)))
                  for p in self.budget.periods]
        v = _ask(self, "توزیع دوره‌ای", fields, P(f"جمع دوره‌ها باید دقیقاً {_money(line.amount)} شود؛ مبلغ دورهٔ بسته تغییر نمی‌کند."))
        if v is None:
            return False
        amounts = {p.period_no: v[f"p{p.period_no}"] or c.ZERO for p in self.budget.periods}
        _r, ok = _run(self, "توزیع دوره‌ای", bud.set_period_amounts, company_id(), user_id(), line.line_id, amounts)
        if ok:
            self._done("توزیع ذخیره شد.")
        return ok

    def set_approved(self) -> bool:
        line = self._line()
        if line is None:
            return False
        v = _ask(self, "مبلغ مصوب", [("amount", "مبلغ مصوب", num_field(line.approved_amount if line.approved_amount is not None
                                                                         else line.proposed_amount)), ("note", "دلیل", _text())],
                 "توزیع دوره‌ای به همان نسبت قبلی تغییر می‌کند و در تاریخچه ثبت می‌شود.")
        if v is None:
            return False
        _r, ok = _run(self, "مبلغ مصوب", bud.set_approved_amount, company_id(), user_id(), line.line_id, v["amount"] or c.ZERO, v["note"])
        if ok:
            self._done("مبلغ مصوب ثبت شد.")
        return ok

    # --- گردش تأیید --------------------------------------------------------------------------------------
    def _step(self, title: str, fn, needs_reason: bool = False, done: str = "انجام شد.") -> bool:
        if self.version is None:
            return False
        v = _ask(self, title, [("note", "دلیل" if needs_reason else "نظر", _text())])
        if v is None:
            return False
        _r, ok = _run(self, title, fn, company_id(), user_id(), self.version.version_id, v["note"] or ("" if needs_reason else None))
        if ok:
            self._done(done)
        return ok

    def submit(self) -> bool:
        return self._step("ارسال برای بررسی", bap.submit, done="نسخه برای بررسی فرستاده شد.")

    def review(self) -> bool:
        return self._step("بررسی مسئول بودجه", bap.review, done="بررسی ثبت شد؛ منتظر تأیید مدیر.")

    def approve(self) -> bool:
        return self._step("تأیید مدیر", bap.approve, done="نسخه تأیید شد؛ منتظر انتشار.")

    def publish(self) -> bool:
        return self._step("انتشار نسخهٔ مصوب", bap.publish, done="نسخه منتشر شد و مصرف اسناد با آن تطبیق داده شد.")

    def reject(self) -> bool:
        return self._step("رد نسخه", bap.reject, needs_reason=True, done="نسخه رد شد.")

    def reopen(self) -> bool:
        return self._step("بازگشت به پیش‌نویس", bap.reopen, done="نسخه به پیش‌نویس برگشت.")

    def cancel(self) -> bool:
        return self._step("لغو نسخه", bap.cancel, needs_reason=True, done="نسخه لغو شد.")

    def revision(self, kind: str) -> int | None:
        if self.budget is None:
            return None
        v = _ask(self, c.KIND_LABELS[kind], [("title", "عنوان", QLineEdit()), ("desc", "توضیح و دلیل", _text())],
                 "ردیف‌ها از نسخهٔ منتشرشده کپی می‌شوند و مبلغ قبلی هر ردیف نگه داشته می‌شود." +
                 (" بودجهٔ تکمیلی فقط مبلغ را افزایش می‌دهد." if kind == "SUPPLEMENT" else ""))
        if v is None:
            return None
        vid, ok = _run(self, c.KIND_LABELS[kind], bud.create_revision, company_id(), user_id(), self.budget.budget_id, kind, v["title"],
                       v["desc"])
        if ok:
            self._done(f"{c.KIND_LABELS[kind]} ساخته شد.")
            set_combo(self.version_box, vid)
            self._load_version()
        return vid if ok else None

    def import_simple(self) -> int | None:
        if self.version is None:
            return None
        n, ok = _run(self, "انتقال بودجهٔ ساده", bud.import_simple_budgets, company_id(), user_id(), self.version.version_id)
        if ok:
            self._done(P(f"{n} ردیف از بودجه‌های سادهٔ خرید اضافه شد."))
        return n if ok else None

    def period(self, closed: bool) -> bool:
        if self.budget is None:
            return False
        pno = _selected(self.t_periods)
        if pno is None:
            self.tabs.setCurrentWidget(self.t_periods)
            _warn(self, "دورهٔ بودجه", "در تب «دوره‌ها» یک دوره را انتخاب کنید.")
            return False
        v = _ask(self, "بستن دوره" if closed else "بازگشایی دوره", [("note", "یادداشت" if closed else "علت بازگشایی", _text())])
        if v is None:
            return False
        _r, ok = _run(self, "دورهٔ بودجه", bud.set_period_closed, company_id(), user_id(), self.budget.budget_id, pno, closed, v["note"])
        if ok:
            self._done("دوره بسته شد." if closed else "دوره باز شد.")
        return ok


# =========================================================================================================
# مجوزهای تجاوز از بودجه
# =========================================================================================================
@ms.styled
class ExceptionsScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.rows: list = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        self.status = combo(_labels(c.EXCEPTION_STATUS_LABELS), "همه")
        set_combo(self.status, "PENDING")
        self.status.currentIndexChanged.connect(lambda _i: self.reload())
        outer.addWidget(ms.header_card(_title("مجوزهای تجاوز از بودجه"), QLabel("وضعیت:"), self.status))
        outer.addWidget(_hint("درخواست مجوز وقتی ساخته می‌شود که سندی بیش از ماندهٔ بودجه مصرف کند (یا در دورهٔ بسته یا خارج از بودجه باشد). "
                              "پس از تأیید، تایید دوبارهٔ همان سند مجوز را مصرف می‌کند. درخواست‌کننده خودش تأیید نمی‌کند."))
        self.t = table(["تاریخ", "سند", "ردیف بودجه", "نوع مجوز", "مبلغ تجاوز", "وضعیت", "درخواست‌کننده", "تصمیم‌گیرنده", "نظر", "شرح"])
        self.t.itemSelectionChanged.connect(self._update_buttons)
        self.t.cellDoubleClicked.connect(lambda _r, _c: self.open_source())
        outer.addWidget(self.t, stretch=1)
        b = _btns(self, [("approve", "تأیید مجوز", lambda: self.decide(True)), ("reject", "رد مجوز", lambda: self.decide(False)),
                         ("cancel", "لغو درخواست مجوز", self.cancel), ("open", "باز کردن سند", self.open_source),
                         ("refresh", "به‌روزرسانی", self.reload),
                         ("report", "گزارش کامل", lambda: _open_report(self._main_window, "BUD_EXCEPTIONS"))])
        outer.addWidget(ms.footer([[b["approve"], b["reject"], b["cancel"]], [b["open"], b["refresh"], b["report"]]]))
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        self.reload()

    def reload(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.rows = bex.list_exceptions(cid, self.status.currentData(), user_id())
        fill(self.t, [[e.requested_at.date(), e.source_label, e.key_label, e.level_label, e.excess_amount, e.status_label, e.requested_by,
                       e.decided_by, e.decision_note or "", e.reason or ""] for e in self.rows], [e.exception_id for e in self.rows])
        self._update_buttons()

    def _update_buttons(self) -> None:
        eid = _selected(self.t)
        e = next((x for x in self.rows if x.exception_id == eid), None)
        self.buttons["approve"].setEnabled(bool(e and e.can_decide))
        self.buttons["reject"].setEnabled(bool(e and e.can_decide))
        self.buttons["cancel"].setEnabled(bool(e and e.status_code in ("PENDING", "APPROVED")))
        self.buttons["open"].setEnabled(e is not None)

    def open_exception(self, exception_id: int) -> None:
        set_combo(self.status, None)
        self.reload()
        for r in range(self.t.rowCount()):
            if self.t.item(r, 0).data(Qt.UserRole) == exception_id:
                self.t.setCurrentCell(r, 0)
                return

    def _current(self):
        eid = _selected(self.t)
        e = next((x for x in self.rows if x.exception_id == eid), None)
        if e is None:
            _warn(self, "مجوز", "یک درخواست را انتخاب کنید.")
        return e

    def decide(self, approve: bool) -> bool:
        e = self._current()
        if e is None:
            return False
        v = _ask(self, "تأیید مجوز" if approve else "رد مجوز", [("note", "نظر" if approve else "دلیل رد", _text())],
                 P(f"{e.source_label} — {e.key_label}: {_money(e.excess_amount)} بیشتر از بودجه ({e.level_label})."))
        if v is None:
            return False
        _r, ok = _run(self, "مجوز", bex.decide, company_id(), user_id(), e.exception_id, approve, v["note"])
        if ok:
            theme.set_status_label(self.status_label, "مجوز تأیید شد؛ سند را دوباره تایید کنید." if approve else "مجوز رد شد.", ok=True)
            self.reload()
        return ok

    def cancel(self) -> bool:
        e = self._current()
        if e is None or not _confirm(self, "لغو درخواست", "این درخواست مجوز لغو شود؟"):
            return False
        _r, ok = _run(self, "مجوز", bex.cancel, company_id(), user_id(), e.exception_id, None)
        if ok:
            self.reload()
        return ok

    def open_source(self) -> None:
        e = self._current()
        if e is not None:
            _open_doc(self._main_window, e.document_id, e.source_type)


# =========================================================================================================
# بستن تعهد سفارش
# =========================================================================================================
@ms.styled
class CommitmentsScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.rows: list = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.addWidget(ms.header_card(_title("بستن تعهد سفارش")))
        outer.addWidget(_hint("ماندهٔ فاکتورنشدهٔ سفارشی که دیگر تحویل نمی‌شود از تعهد بودجه آزاد می‌شود. وضعیت خود سفارش خرید تغییر نمی‌کند؛ "
                              "فاکتور بعدی همان سفارش همچنان «واقعی» ثبت می‌شود. بازگشایی تعهد دوباره با بودجه سنجیده می‌شود."))
        split = QSplitter(Qt.Vertical)
        self.t = table(["شمارهٔ سفارش", "تاریخ", "تامین‌کننده", "وضعیت سفارش", "تعهد باز", "ردیف بسته‌شده", "علت بستن"])
        self.t.itemSelectionChanged.connect(self._show_lines)
        split.addWidget(self.t)
        self.t_lines = table(["ردیف", "کالا", "مقدار", "مقدار باز", "بسته‌شده", "تعهد باز"])
        split.addWidget(self.t_lines)
        outer.addWidget(split, stretch=1)
        b = _btns(self, [("close", "بستن تعهد باقی‌مانده", self.close_commitment), ("reopen", "بازگشایی تعهد", self.reopen),
                         ("open", "باز کردن سند", self.open_order), ("refresh", "به‌روزرسانی", self.reload)])
        outer.addWidget(ms.footer([[b["close"], b["reopen"]], [b["open"], b["refresh"]]]))
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        allowed = c.can(cid, user_id(), c.FORM_COMMITMENT) and can("bud_commitments", "EDIT")
        self.buttons["close"].setEnabled(allowed)
        self.buttons["reopen"].setEnabled(allowed)
        self.reload()

    def reload(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.rows = bex.open_commitments(cid)
        fill(self.t, [[r.document_no, r.document_date, r.supplier, r.status_label, r.open_amount, r.closed_lines, r.closed_reason]
                      for r in self.rows], [r.document_id for r in self.rows])
        self._show_lines()

    def _show_lines(self) -> None:
        did = _selected(self.t)
        if did is None:
            self.t_lines.setRowCount(0)
            return
        lines, ok = _run(self, "سفارش", bex.open_order_lines, company_id(), did)
        if ok:
            fill(self.t_lines, [[ln.line_no, ln.item, ln.quantity, ln.open_qty, ln.closed_qty, ln.open_amount] for ln in lines])

    def close_commitment(self) -> bool:
        did = _selected(self.t)
        if did is None:
            _warn(self, "بستن تعهد", "یک سفارش را انتخاب کنید.")
            return False
        v = _ask(self, "بستن تعهد باقی‌مانده", [("reason", "علت", _text())])
        if v is None:
            return False
        n, ok = _run(self, "بستن تعهد", bex.close_commitment, company_id(), user_id(), did, v["reason"] or "")
        if ok:
            theme.set_status_label(self.status_label, P(f"تعهد {n} ردیف آزاد شد."), ok=True)
            self.reload()
        return ok

    def reopen(self) -> bool:
        did = _selected(self.t)
        if did is None:
            return False
        v = _ask(self, "بازگشایی تعهد", [("note", "علت", _text())])
        if v is None:
            return False
        _n, ok = _run(self, "بازگشایی تعهد", bex.reopen_commitment, company_id(), user_id(), did, v["note"] or "")
        if ok:
            theme.set_status_label(self.status_label, "تعهد دوباره باز شد.", ok=True)
            self.reload()
        return ok

    def open_order(self) -> None:
        did = _selected(self.t)
        if did is not None:
            _open_doc(self._main_window, did, "PURCHASE_ORDER")


# =========================================================================================================
# تنظیمات بودجه (چرخ‌دندهٔ کنار منو)
# =========================================================================================================
class BudSettingsScreen(FieldHelpMixin, QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.confirm = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.addWidget(_title("تنظیمات بودجه‌ریزی و کنترل بودجه"))
        outer.addWidget(_hint("سیاست تجاوز در سرویس سند اجرا می‌شود، نه فقط با پیام در فرم. هر ردیف بودجه می‌تواند سیاست و درصد هشدار خودش را "
                              "داشته باشد. هر تغییر سیاست و کلید با نام کاربر و زمان ثبت می‌شود."))
        self.policy = combo(_labels(c.POLICY_LABELS))
        self.warn_box = num_field(90)
        self.level = combo(_labels(c.CONTROL_LEVEL_LABELS))
        self.unbudgeted = combo(_labels(c.UNBUDGETED_LABELS))
        form = QWidget()
        fl = QVBoxLayout(form)
        fl.setContentsMargins(0, 0, 0, 0)
        for label, w in (("سیاست تجاوز از بودجه:", self.policy), ("درصد هشدار نزدیک به سقف:", self.warn_box),
                         ("سطح کنترل:", self.level), ("خرید خارج از همهٔ ردیف‌های بودجه:", self.unbudgeted)):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(w, stretch=1)
            fl.addLayout(row)
        outer.addWidget(form)
        self.save_btn = QPushButton("ذخیرهٔ سیاست کنترل")
        self.save_btn.clicked.connect(lambda _c=False: self.save())
        outer.addWidget(ms.footer([[self.save_btn]]))
        sep = QLabel("کلیدها")
        sep.setObjectName("sectionTitle")
        outer.addWidget(sep)
        self.toggles: dict[str, QCheckBox] = {}
        self.toggle_box = QWidget()
        self.toggle_layout = QVBoxLayout(self.toggle_box)
        self.toggle_layout.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.toggle_box)
        sep2 = QLabel("نقش‌ها و تطبیق")
        sep2.setObjectName("sectionTitle")
        outer.addWidget(sep2)
        outer.addWidget(_hint("شش نقش آماده: تهیه‌کننده، مسئول بودجه، تأییدکننده (مدیر مجاز)، کنترل‌کنندهٔ ارشد، کارشناس خرید و ناظر. "
                              "«تطبیق دوباره» دفتر مصرف را با اسناد فعلی مقایسه و اختلاف را با برچسب «تطبیق» ثبت می‌کند."))
        self.roles_btn = QPushButton("ساخت نقش‌های آمادهٔ بودجه")
        self.roles_btn.clicked.connect(lambda _c=False: self.make_roles())
        self.resync_btn = QPushButton("تطبیق دوباره با اسناد")
        self.resync_btn.clicked.connect(lambda _c=False: self.resync())
        outer.addWidget(ms.footer([[self.roles_btn, self.resync_btn]]))
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)
        outer.addStretch(1)
        self.set_field_help([
            (self.policy, "فقط هشدار: سند تایید می‌شود. تأیید سطح بالاتر: سند تا تأیید مجوز تایید نمی‌شود. جلوگیری: فقط با اصلاح بودجه یا "
                          "مجوز استثنای ویژه."),
            (self.warn_box, "وقتی مصرف یک ردیف به این درصد از بودجه برسد، هشدار «نزدیک به سقف» داده می‌شود."),
            (self.level, "کل دورهٔ بودجه: مانده = بودجهٔ کل سال − مصرف. تجمعی: مانده = جمع بودجهٔ دوره‌ها تا پایان دورهٔ سند − مصرف تا همان تاریخ."),
            (self.unbudgeted, "سندی که به هیچ ردیف بودجه‌ای نمی‌خورد: مجاز، فقط هشدار، یا جلوگیری تا مجوز استثنای ویژه."),
            (self.save_btn, "سیاست را برای همهٔ اسنادی که از این پس تایید می‌شوند ذخیره می‌کند."),
            (self.roles_btn, "نقش‌های آماده را روی همان جدول نقش‌ها می‌سازد؛ کاربران را از «مدیریت سیستم › نقش‌ها» وصل کنید."),
            (self.resync_btn, "اسناد خرید و درخواست‌ها را با نسخه‌های منتشرشده تطبیق می‌دهد (مثلاً پس از خطای شبکه)."),
        ])

    def refresh(self) -> None:
        from peecha.services import inventory_engine as engine

        cid, uid = company_id(), user_id()
        if cid is None:
            return
        s = c.settings(cid)
        set_combo(self.policy, s.policy_code)
        self.warn_box.setText(P(format(c.dec(s.warn_percent).normalize(), "f")))
        set_combo(self.level, s.control_level)
        set_combo(self.unbudgeted, s.unbudgeted_policy)
        allowed = c.can(cid, uid, c.FORM_SETTINGS)
        for w in (self.policy, self.warn_box, self.level, self.unbudgeted, self.save_btn, self.roles_btn):
            w.setEnabled(allowed)
        self.resync_btn.setEnabled(c.can(cid, uid, c.FORM_PUBLISH))
        features = {f.feature_code: f for f in engine.list_features(cid)}
        if not self.toggles:   # کلیدها یک بار ساخته می‌شوند
            descriptions = engine.feature_descriptions()
            helps = []
            for code in stock_controls.BUD_ALL:
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

    def save(self) -> bool:
        _r, ok = _run(self, "سیاست کنترل", c.save_settings, company_id(), user_id(), self.policy.currentData(),
                      numerals.to_ascii_digits(self.warn_box.text()) or "90", self.level.currentData(), self.unbudgeted.currentData())
        if ok:
            theme.set_status_label(self.status_label, "سیاست کنترل ذخیره شد.", ok=True)
        return ok

    def _toggle(self, code: str, checked: bool) -> None:
        _r, ok = _run(self, "تنظیمات بودجه", c.set_toggle, company_id(), user_id(), code, checked)
        if not ok:
            box = self.toggles[code]
            box.blockSignals(True)
            box.setChecked(not checked)
            box.blockSignals(False)

    def make_roles(self) -> dict | None:
        from peecha.services.budgeting import roles_setup

        roles, ok = _run(self, "نقش‌ها", roles_setup.ensure_role_templates, company_id())
        if ok:
            theme.set_status_label(self.status_label, P(f"{len(roles)} نقش آماده است."), ok=True)
        return roles if ok else None

    def resync(self) -> int | None:
        n, ok = _run(self, "تطبیق دوباره", bl.resync, company_id(), user_id())
        if ok:
            theme.set_status_label(self.status_label, P(f"تطبیق انجام شد؛ {n} اختلاف ثبت شد."), ok=True)
        return n if ok else None
