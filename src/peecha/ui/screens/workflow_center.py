"""R293: صفحه‌های گردش کار برای کاربر — کارهای من، مرکز تایید، اعلان‌ها، تفویض اختیار و تنظیمات.

ظاهر هم‌شکل بقیهٔ ماژول‌ها: کارت سر صفحه، کارت‌های خلاصه، جدول، نوار دکمه‌های آیکونی با راهنمای کوتاه.
"""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services import roles as roles_service
from peecha.services.workflow import calendar as wf_calendar, inbox, notify, registry, sla, tasks
from peecha.services.workflow.common import save_settings, settings as wf_settings
from peecha.ui.screens import module_style as ms
from peecha.ui.screens.costing import can
from peecha.ui.screens.fixed_assets import FormDialog, P, combo, company_id, date_field, fill, num_field, set_combo, table, user_id

_RED, _AMBER, _GREEN, _GREY = QColor("#EF4444"), QColor("#F59E0B"), QColor("#10B981"), QColor("#94A3B8")
_PATH_GLYPH = {"done": "✔", "current": "●", "pending": "○", "failed": "✖"}
_PATH_COLOR = {"done": "#10B981", "current": "#3B82F6", "pending": "#94A3B8", "failed": "#EF4444"}

ms.ICONS.update({
    "تایید درخواست": ("✅", "primary"), "رد درخواست": ("❌", "danger"), "برگشت برای اصلاح": ("↩️", ""),
    "واگذاری به همکار": ("👥", ""), "یادداشت": ("💬", ""), "بازکردن سند": ("📂", ""), "تایید گروهی": ("☑️", ""),
    "تازه‌سازی": ("🔄", ""), "یادآوری به گیرنده": ("🔔", ""), "پس‌گرفتن درخواست": ("🚫", "danger"),
    "انجام و تایید سریع": ("✅", "primary"), "علامت خوانده‌شده": ("✔️", ""), "همه خوانده شد": ("📭", ""),
    "تنظیم کانال‌های اعلان": ("⚙️", ""), "تفویض جدید": ("🆕", "primary"), "پایان تفویض": ("🛑", "danger"),
    "ذخیرهٔ قواعد": ("💾", "primary"), "ذخیرهٔ ساعت کاری": ("💾", "primary"), "تعطیلی جدید": ("🆕", ""),
    "حذف تعطیلی": ("🗑️", "danger"), "ذخیرهٔ پیش‌فرض اعلان‌ها": ("💾", "primary"), "ذخیرهٔ کاربران کارکنان": ("💾", "primary"),
    "ذخیرهٔ مدیران واحدها": ("💾", "primary"), "مرکز تایید": ("🖊️", ""),
})


def _dt(value) -> str:
    return numerals.format_jalali_datetime(value) if value else "—"


def _warn(parent, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)


def _run(parent, title: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs), True
    except ValueError as exc:
        _warn(parent, title, str(exc))
        return None, False


def _ask(parent, title: str, fields, hint: str = "") -> dict | None:
    dlg = FormDialog(title, fields, hint, parent)
    runner = getattr(parent, "dialog_runner", None)
    if runner is not None:
        return dlg.values() if runner(dlg) else None
    return dlg.values() if dlg.exec() == QDialog.Accepted else None


def _paint(t: QTableWidget, row: int, color: QColor) -> None:
    for col in range(t.columnCount()):
        item = t.item(row, col)
        if item is not None:
            item.setForeground(color)


def path_html(path: list[tuple[str, str]]) -> str:
    """مسیر فرایند به‌صورت زنجیرهٔ رنگی: ✔ ثبت و ارسال ← ● تایید مالی ← ○ پایان"""
    parts = [f"<span style='color:{_PATH_COLOR.get(state, '#94A3B8')}'>{_PATH_GLYPH.get(state, '○')} {label}</span>"
             for label, state in path]
    return " ← ".join(parts)


def company_user_choices() -> list[tuple[str, int]]:
    from peecha.db.base import new_session
    from peecha.services.workflow import routing
    from peecha.services.workflow.common import user_names

    cid = company_id()
    if cid is None:
        return []
    with new_session() as session:
        ids = routing.company_users(session, cid)
        names = user_names(session, ids)
    return sorted(((names.get(u, str(u)), u) for u in ids), key=lambda x: x[0])


# --- بازکردن مبدأ هر کار -----------------------------------------------------------------------------------
ENTITY_OPENERS: dict[str, callable] = {}  # نوع سند ← opener(main_window, entity_id) -- ماژول‌ها در R295 ثبت می‌کنند


def register_entity_opener(entity_type: str, opener) -> None:
    ENTITY_OPENERS[entity_type] = opener


def open_entity(main_window, entity_type: str | None, entity_id: int | None) -> bool:
    if main_window is None or not entity_type or not entity_id:
        return False
    opener = ENTITY_OPENERS.get(entity_type)
    if opener is not None:
        opener(main_window, entity_id)
        return True
    adapter = registry.get_adapter(entity_type)
    if adapter is None or not adapter.open_nav:
        return False
    main_window.open_screen(adapter.open_nav, then=lambda s: getattr(s, "edit_document", lambda _i: None)(entity_id))
    return True


def open_work_item(main_window, item: inbox.WorkItem) -> bool:
    from peecha.ui.screens import my_tasks

    if item.source == "WF":
        return open_entity(main_window, item.extra.get("entity_type"), item.extra.get("entity_id"))
    if item.source == "CARTABLE":
        return my_tasks.open_cartable_source(main_window, item.extra["form_code"], item.extra["source_record_id"])
    if item.source == "DOC":
        return my_tasks.open_operational_task(main_window, item.extra["kind"], item.extra["document_type_code"],
                                              item.extra["document_id"])
    if item.source == "CRM" and main_window is not None and item.extra.get("customer_id"):
        cid = item.extra["customer_id"]
        main_window.open_screen("CRM_CUSTOMER360", then=lambda s: s.load_customer(cid))
        return True
    return False


# =========================================================================================================
# کارهای من
# =========================================================================================================
@ms.styled
class MyWorkScreen(QWidget):
    """همهٔ کارهای منتظر کاربر از همهٔ ماژول‌ها: تایید، کار، مراحل اسناد و پیگیری مشتری."""

    scroll_in_mdi = True
    COLUMNS = ["نوع", "عنوان", "درخواست‌کننده / طرف حساب", "منبع", "موعد", "اولویت", "وضعیت"]

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.items: list[inbox.WorkItem] = []
        self.shown: list[inbox.WorkItem] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("کارهای من")
        title.setObjectName("pageTitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو در عنوان یا نام…")
        self.search.textChanged.connect(lambda _t: self.apply_filter())
        self.kind = QComboBox()
        for label, data in (("همهٔ کارها", None), ("فقط تاییدها", "APPROVAL"), ("فقط کارها", "TASK"),
                            ("مراحل اسناد", "STEP"), ("پیگیری مشتری", "FOLLOWUP")):
            self.kind.addItem(label, data)
        self.kind.currentIndexChanged.connect(lambda _i: self.apply_filter())
        self.overdue_only = QCheckBox("فقط کارهای عقب‌افتاده")
        self.overdue_only.toggled.connect(lambda _c: self.apply_filter())
        outer.addWidget(ms.header_card(title, self.search, self.kind, self.overdue_only))
        cards, self.cards = ms.summary([("total", "همهٔ کارهای من", "info", "📥"), ("approvals", "منتظر تایید من", "warning", "🖊️"),
                                        ("overdue", "عقب‌افتاده", "danger", "⏰"), ("today", "موعد امروز", "neutral", "📌"),
                                        ("behalf", "به جای همکار", "neutral", "🤝")], per_row=5)
        outer.addWidget(cards)
        self.table = table(self.COLUMNS)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self.open_selected())
        outer.addWidget(self.table, stretch=1)
        self.empty = QLabel("کاری منتظر شما نیست.")
        self.empty.setObjectName("sectionHint")
        outer.addWidget(self.empty)
        self.buttons = {k: QPushButton(t) for k, t in (("approve", "انجام و تایید سریع"), ("reject", "رد درخواست"),
                                                      ("open", "بازکردن سند"), ("center", "مرکز تایید"),
                                                      ("refresh", "تازه‌سازی"))}
        self.buttons["approve"].clicked.connect(lambda: self.approve_selected())
        self.buttons["reject"].clicked.connect(lambda: self.reject_selected())
        self.buttons["open"].clicked.connect(lambda: self.open_selected())
        self.buttons["center"].clicked.connect(lambda: self._main_window and self._main_window.open_screen("WF_APPROVALS"))
        self.buttons["refresh"].clicked.connect(lambda: self.reload())
        outer.addWidget(ms.footer([[self.buttons["approve"], self.buttons["reject"]], [self.buttons["open"], self.buttons["center"]],
                                   [self.buttons["refresh"]]]))

    def refresh(self) -> None:
        self.reload()

    def reload(self) -> None:
        if company_id() is None or user_id() is None:
            return
        self.items = inbox.my_work(company_id(), user_id())
        s = inbox.summarize(self.items)
        for key, value in (("total", s.total), ("approvals", s.approvals), ("overdue", s.overdue), ("today", s.due_today),
                           ("behalf", s.on_behalf)):
            self.cards[key].setText(P(value))
        self.apply_filter()

    def apply_filter(self) -> None:
        text = self.search.text().strip()
        kind = self.kind.currentData()
        shown = [w for w in self.items if (not kind or w.kind == kind) and (not self.overdue_only.isChecked() or w.is_overdue)
                 and (not text or text in w.title or text in w.subtitle)]
        self.shown = shown
        fill(self.table, [[w.kind_label, w.title, w.subtitle, w.source_label, _dt(w.due_at), w.priority_label, w.status_note]
                          for w in shown], [w.key for w in shown])
        for r, w in enumerate(shown):
            if w.is_overdue:
                _paint(self.table, r, _RED)
            elif w.priority_code in ("HIGH", "CRITICAL"):
                _paint(self.table, r, _AMBER)
        self.empty.setVisible(not shown)

    def _selected(self) -> inbox.WorkItem | None:
        items = self.table.selectedItems()
        if not items:
            _warn(self, "کارهای من", "یک ردیف را انتخاب کنید.")
            return None
        key = self.table.item(items[0].row(), 0).data(Qt.UserRole)
        return next((w for w in self.shown if w.key == key), None)

    def select_key(self, key: str) -> bool:
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole) == key:
                self.table.selectRow(r)
                return True
        return False

    def open_selected(self) -> bool:
        item = self._selected()
        if item is None:
            return False
        if item.source == "WF" and item.kind == "TASK":
            return self.complete_task(item)
        if not open_work_item(self._main_window, item) and item.source == "WF" and self._main_window is not None:
            self._main_window.open_screen("WF_APPROVALS", then=lambda s: s.select_key(item.key))
        return True

    def approve_selected(self, comment: str = "") -> bool:
        item = self._selected()
        if item is None:
            return False
        if item.source == "WF" and item.kind == "TASK":
            return self.complete_task(item)
        if not item.can_quick_decide:
            return self.open_selected()
        _msg, ok = _run(self, "تایید", inbox.quick_decide, company_id(), user_id(), item.key, "APPROVE", comment,
                        row_version=item.extra.get("row_version"))
        if ok:
            self.reload()
        return ok

    def reject_selected(self, comment: str | None = None) -> bool:
        item = self._selected()
        if item is None:
            return False
        if not item.can_quick_decide:
            _warn(self, "رد", "این مورد تصمیم سریع ندارد؛ سند را باز کنید.")
            return False
        if comment is None:
            values = _ask(self, "رد درخواست", [("comment", "علت رد", QTextEdit())], "علت رد برای درخواست‌کننده فرستاده می‌شود.")
            if values is None:
                return False
            comment = values.get("comment") or ""
        _msg, ok = _run(self, "رد", inbox.quick_decide, company_id(), user_id(), item.key, "REJECT", comment,
                        row_version=item.extra.get("row_version"))
        if ok:
            self.reload()
        return ok

    def complete_task(self, item: inbox.WorkItem, values: dict | None = None) -> bool:
        detail = tasks.task_detail(company_id(), item.ref_id, user_id())
        if values is None:
            fields = [(f["key"], f.get("label") or f["key"], _field_widget(f)) for f in detail.form_fields]
            fields.append(("__comment", "توضیح", QTextEdit()))
            values = _ask(self, f"انجام کار: {detail.row.title}", fields, detail.row.instructions)
            if values is None:
                return False
        comment = values.pop("__comment", "") or ""
        _r, ok = _run(self, "انجام کار", tasks.decide, company_id(), item.ref_id, user_id(), "DONE", comment,
                      data=values, row_version=detail.row.row_version)
        if ok:
            self.reload()
        return ok


def _field_widget(f: dict) -> QWidget:
    kind = f.get("kind") or "text"
    if kind == "number":
        return num_field()
    if kind == "date":
        return date_field()
    if kind == "bool":
        return QCheckBox()
    if kind == "choice":
        return combo([(c, c) for c in f.get("choices") or []], "—")
    return QLineEdit()


# =========================================================================================================
# مرکز تایید
# =========================================================================================================
@ms.styled
class ApprovalCenterScreen(QWidget):
    """تاییدهای منتظر با اطلاعات کلیدی سند، مسیر و تاریخچه کنار هم؛ تصمیم بدون بازکردن سند."""

    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.items: list[inbox.WorkItem] = []
        self.current: dict | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("مرکز تایید")
        title.setObjectName("pageTitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو…")
        self.search.textChanged.connect(lambda _t: self._fill())
        self.source = QComboBox()
        for label, data in (("همهٔ تاییدها", None), ("گردش کار", "WF"), ("کارتابل اسناد", "CARTABLE")):
            self.source.addItem(label, data)
        self.source.currentIndexChanged.connect(lambda _i: self._fill())
        outer.addWidget(ms.header_card(title, self.search, self.source))
        cards, self.cards = ms.summary([("waiting", "منتظر تصمیم من", "warning", "🖊️"), ("overdue", "گذشته از مهلت", "danger", "⏰"),
                                        ("today", "موعد امروز", "info", "📌"), ("behalf", "به جای همکار", "neutral", "🤝")])
        outer.addWidget(cards)
        split = QSplitter(Qt.Horizontal)
        self.table = table(["عنوان", "درخواست‌کننده", "منبع", "موعد", "وضعیت"])
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self.show_selected)
        split.addWidget(self.table)
        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(8, 0, 8, 0)
        self.d_title = QLabel("یک مورد را انتخاب کنید")
        self.d_title.setObjectName("sectionTitle")
        self.d_title.setWordWrap(True)
        self.d_info = QLabel("")
        self.d_info.setWordWrap(True)
        self.d_path = QLabel("")
        self.d_path.setTextFormat(Qt.RichText)
        self.d_path.setWordWrap(True)
        self.d_context = table(["عنوان", "مقدار"])
        self.d_context.setMaximumHeight(220)
        self.d_history = table(["زمان", "کاربر", "اقدام", "توضیح"])
        self.d_history.setMaximumHeight(200)
        self.comment = QTextEdit()
        self.comment.setPlaceholderText("توضیح تصمیم (برای رد و برگشت برای اصلاح الزامی است)")
        self.comment.setMaximumHeight(80)
        for w in (self.d_title, self.d_info, self.d_path, QLabel("اطلاعات کلیدی"), self.d_context, QLabel("تاریخچه"),
                  self.d_history, self.comment):
            sl.addWidget(w)
        split.addWidget(side)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        outer.addWidget(split, stretch=1)
        self.buttons = {k: QPushButton(t) for k, t in (
            ("approve", "تایید درخواست"), ("reject", "رد درخواست"), ("changes", "برگشت برای اصلاح"),
            ("delegate", "واگذاری به همکار"), ("note", "یادداشت"), ("open", "بازکردن سند"), ("bulk", "تایید گروهی"),
            ("refresh", "تازه‌سازی"))}
        self.buttons["approve"].clicked.connect(lambda: self.decide("APPROVE"))
        self.buttons["reject"].clicked.connect(lambda: self.decide("REJECT"))
        self.buttons["changes"].clicked.connect(lambda: self.decide("CHANGES"))
        self.buttons["delegate"].clicked.connect(lambda: self.delegate())
        self.buttons["note"].clicked.connect(lambda: self.add_note())
        self.buttons["open"].clicked.connect(lambda: self.open_document())
        self.buttons["bulk"].clicked.connect(lambda: self.bulk_approve())
        self.buttons["refresh"].clicked.connect(lambda: self.reload())
        B = self.buttons
        outer.addWidget(ms.footer([[B["approve"], B["reject"], B["changes"]], [B["delegate"], B["note"], B["open"]],
                                   [B["bulk"], B["refresh"]]]))

    def refresh(self) -> None:
        self.reload()

    def reload(self) -> None:
        if company_id() is None or user_id() is None:
            return
        self.items = inbox.approvals(company_id(), user_id())
        s = inbox.summarize(self.items)
        for key, value in (("waiting", s.approvals), ("overdue", s.overdue), ("today", s.due_today), ("behalf", s.on_behalf)):
            self.cards[key].setText(P(value))
        self._fill()

    def _visible(self) -> list[inbox.WorkItem]:
        text, src = self.search.text().strip(), self.source.currentData()
        return [w for w in self.items if (not src or w.source == src) and (not text or text in w.title or text in w.subtitle)]

    def _fill(self) -> None:
        shown = self._visible()
        fill(self.table, [[w.title, w.subtitle, w.source_label, _dt(w.due_at), w.status_note] for w in shown], [w.key for w in shown])
        for r, w in enumerate(shown):
            if w.is_overdue:
                _paint(self.table, r, _RED)
        self.current = None
        self._show_detail(None)
        if shown:
            self.table.selectRow(0)

    def select_key(self, key: str) -> bool:
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole) == key:
                self.table.selectRow(r)
                return True
        return False

    def _selected_keys(self) -> list[str]:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        return [self.table.item(r, 0).data(Qt.UserRole) for r in rows]

    def show_selected(self) -> None:
        keys = self._selected_keys()
        if not keys:
            self._show_detail(None)
            return
        try:
            self.current = {"key": keys[0], **inbox.detail(company_id(), user_id(), keys[0])}
        except ValueError as exc:
            self.current = None
            self.d_title.setText(str(exc))
            return
        self._show_detail(self.current)

    def _show_detail(self, d: dict | None) -> None:
        if d is None:
            self.d_title.setText("یک مورد را انتخاب کنید")
            for w in (self.d_info, self.d_path):
                w.setText("")
            fill(self.d_context, [])
            fill(self.d_history, [])
            return
        self.d_title.setText(P(d["title"]))
        info = [f"درخواست‌کننده: {d['requester']}"]
        if d.get("due_at"):
            info.append(f"موعد: {_dt(d['due_at'])}")
        if d.get("sla"):
            info.append(d["sla"])
        if d.get("instructions"):
            info.append(d["instructions"])
        self.d_info.setText(P(" — ".join(info)))
        self.d_path.setText(path_html(d.get("path") or []))
        fill(self.d_context, [[k, v] for k, v in d.get("context") or []])
        fill(self.d_history, [[_dt(at), who, what, note] for at, who, what, note in d.get("history") or []])
        allowed = {code for code, _l in d.get("decisions") or []}
        self.buttons["changes"].setEnabled("CHANGES" in allowed)
        self.buttons["delegate"].setEnabled(d["key"].startswith("WF:"))
        self.buttons["note"].setEnabled(d["key"].startswith("WF:"))

    def decide(self, decision: str, comment: str | None = None) -> bool:
        if self.current is None:
            _warn(self, "مرکز تایید", "یک مورد را انتخاب کنید.")
            return False
        comment = self.comment.toPlainText().strip() if comment is None else comment
        msg, ok = _run(self, "مرکز تایید", inbox.quick_decide, company_id(), user_id(), self.current["key"], decision, comment,
                       row_version=self.current.get("row_version"))
        if ok:
            self.comment.clear()
            self.last_message = msg
            self.reload()
        return ok

    def bulk_approve(self, keys: list[str] | None = None) -> list:
        keys = keys or self._selected_keys()
        if not keys:
            _warn(self, "تایید گروهی", "ردیف‌های مورد نظر را انتخاب کنید (با کلید Ctrl چند ردیف).")
            return []
        results = inbox.bulk_approve(company_id(), user_id(), keys, self.comment.toPlainText().strip())
        failed = [m for _k, ok, m in results if not ok]
        if failed:
            _warn(self, "تایید گروهی", f"{P(len(results) - len(failed))} مورد تایید شد؛ این موارد انجام نشد:\n" + "\n".join(failed))
        self.comment.clear()
        self.reload()
        return results

    def delegate(self, to_user_id: int | None = None) -> bool:
        if self.current is None or not self.current["key"].startswith("WF:"):
            return False
        if to_user_id is None:
            values = _ask(self, "واگذاری به همکار", [("to", "همکار", combo(company_user_choices()))],
                          "سهم شما از این کار به همکار انتخاب‌شده سپرده می‌شود.")
            if values is None:
                return False
            to_user_id = values["to"]
        _r, ok = _run(self, "واگذاری", tasks.delegate_task, company_id(), int(self.current["key"][3:]), user_id(), to_user_id,
                      self.comment.toPlainText().strip())
        if ok:
            self.comment.clear()
            self.reload()
        return ok

    def add_note(self, text: str | None = None) -> bool:
        if self.current is None or not self.current["key"].startswith("WF:"):
            return False
        text = self.comment.toPlainText().strip() if text is None else text
        _r, ok = _run(self, "یادداشت", tasks.add_comment, company_id(), int(self.current["key"][3:]), user_id(), text)
        if ok:
            self.comment.clear()
            self.show_selected()
        return ok

    def open_document(self) -> bool:
        if self.current is None:
            return False
        item = next((w for w in self.items if w.key == self.current["key"]), None)
        return bool(item) and open_work_item(self._main_window, item)


# =========================================================================================================
# اعلان‌ها
# =========================================================================================================
class NotificationPrefsDialog(QDialog):
    """انتخاب کانال‌های هر نوع اعلان برای کاربر جاری."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("کانال‌های اعلان من")
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(self)
        hint = QLabel("برای هر نوع اعلان مشخص کنید از چه راهی باخبر شوید. پیامک فقط وقتی فرستاده می‌شود که شمارهٔ همراه "
                      "شما در پروندهٔ کارمندی ثبت و درگاه پیامک وصل باشد.")
        hint.setWordWrap(True)
        hint.setObjectName("sectionHint")
        layout.addWidget(hint)
        self.types = list(notify.TYPES.items())
        self.channels = list(notify.CHANNELS.items())
        self.grid = QTableWidget(len(self.types), len(self.channels))
        self.grid.setHorizontalHeaderLabels([label for _c, label in self.channels])
        self.grid.setVerticalHeaderLabels([label for _t, label in self.types])
        layout.addWidget(self.grid)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save_and_close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.load()

    def load(self) -> None:
        prefs = notify.user_preferences(company_id(), user_id())
        for r, (code, _l) in enumerate(self.types):
            eff = notify.effective_channels(company_id(), user_id(), code, _prefs=prefs)
            for c, (ch, _cl) in enumerate(self.channels):
                item = QTableWidgetItem()
                item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                item.setCheckState(Qt.Checked if eff.get(ch) else Qt.Unchecked)
                self.grid.setItem(r, c, item)

    def set_channel(self, type_code: str, channel: str, on: bool) -> None:
        r = [t for t, _l in self.types].index(type_code)
        c = [ch for ch, _l in self.channels].index(channel)
        self.grid.item(r, c).setCheckState(Qt.Checked if on else Qt.Unchecked)

    def save(self) -> None:
        for r, (code, _l) in enumerate(self.types):
            notify.save_preference(company_id(), user_id(), code, **{
                ch: self.grid.item(r, c).checkState() == Qt.Checked for c, (ch, _cl) in enumerate(self.channels)})

    def save_and_close(self) -> None:
        self.save()
        self.accept()


@ms.styled
class NotificationCenterScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.rows: list[notify.NoteRow] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("اعلان‌ها")
        title.setObjectName("pageTitle")
        self.unread_only = QCheckBox("فقط خوانده‌نشده‌ها")
        self.unread_only.setChecked(True)
        self.unread_only.toggled.connect(lambda _c: self.reload())
        self.type_filter = QComboBox()
        self.type_filter.addItem("همهٔ اعلان‌ها", None)
        for code, label in {**notify.TYPES, **notify.OTHER_TYPES}.items():
            self.type_filter.addItem(label, code)
        self.type_filter.currentIndexChanged.connect(lambda _i: self.reload())
        outer.addWidget(ms.header_card(title, self.type_filter, self.unread_only))
        cards, self.cards = ms.summary([("unread", "خوانده‌نشده", "warning", "🔔"), ("today", "امروز", "info", "📅"),
                                        ("urgent", "فوری و مهم", "danger", "⚠️")], per_row=3)
        outer.addWidget(cards)
        self.table = table(["زمان", "نوع", "عنوان", "متن", "ارسال بیرونی"])
        self.table.cellDoubleClicked.connect(lambda _r, _c: self.open_selected())
        outer.addWidget(self.table, stretch=1)
        self.buttons = {k: QPushButton(t) for k, t in (("read", "علامت خوانده‌شده"), ("all", "همه خوانده شد"),
                                                      ("open", "بازکردن سند"), ("prefs", "تنظیم کانال‌های اعلان"),
                                                      ("refresh", "تازه‌سازی"))}
        self.buttons["read"].clicked.connect(lambda: self.mark_selected())
        self.buttons["all"].clicked.connect(lambda: self.mark_all())
        self.buttons["open"].clicked.connect(lambda: self.open_selected())
        self.buttons["prefs"].clicked.connect(lambda: NotificationPrefsDialog(self).exec())
        self.buttons["refresh"].clicked.connect(lambda: self.reload())
        outer.addWidget(ms.footer([[self.buttons["read"], self.buttons["all"], self.buttons["open"]],
                                   [self.buttons["prefs"], self.buttons["refresh"]]]))

    def refresh(self) -> None:
        self.reload()

    def reload(self) -> None:
        if company_id() is None or user_id() is None:
            return
        code = self.type_filter.currentData()
        self.rows = notify.list_notifications(company_id(), user_id(), unread_only=self.unread_only.isChecked(),
                                              type_codes=[code] if code else None)
        fill(self.table, [[_dt(n.created_at), n.type_label, n.title, n.body, n.delivery] for n in self.rows],
             [n.notification_id for n in self.rows])
        for r, n in enumerate(self.rows):
            if n.priority_code in ("HIGH", "CRITICAL"):
                _paint(self.table, r, _RED)
            elif n.is_read:
                _paint(self.table, r, _GREY)
        today = datetime.date.today()
        all_rows = self.rows if not self.unread_only.isChecked() else notify.list_notifications(company_id(), user_id())
        self.cards["unread"].setText(P(notify.unread_count(company_id(), user_id())))
        self.cards["today"].setText(P(sum(1 for n in all_rows if n.created_at.astimezone().date() == today)))
        self.cards["urgent"].setText(P(sum(1 for n in all_rows if not n.is_read and n.priority_code in ("HIGH", "CRITICAL"))))
        if self._main_window is not None and hasattr(self._main_window, "update_notification_badge"):
            self._main_window.update_notification_badge()

    def _selected_ids(self) -> list[int]:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        return [self.table.item(r, 0).data(Qt.UserRole) for r in rows]

    def mark_selected(self) -> int:
        ids = self._selected_ids()
        if not ids:
            _warn(self, "اعلان‌ها", "یک یا چند اعلان را انتخاب کنید.")
            return 0
        n = notify.mark_read(company_id(), user_id(), ids)
        self.reload()
        return n

    def mark_all(self) -> int:
        n = notify.mark_read(company_id(), user_id())
        self.reload()
        return n

    def open_selected(self) -> bool:
        ids = self._selected_ids()
        if not ids:
            return False
        note = next(n for n in self.rows if n.notification_id == ids[0])
        notify.mark_read(company_id(), user_id(), [note.notification_id])
        mw = self._main_window
        if mw is not None and note.entity_type == "WfTask":
            mw.open_screen("WF_APPROVALS", then=lambda s: s.select_key(f"WF:{note.entity_id}"))
        elif mw is not None and note.entity_type in ("WfInstance", "WfException"):
            mw.open_screen("WF_MY_WORK")
        elif note.entity_type and note.entity_id:
            open_entity(mw, note.entity_type, note.entity_id)
        self.reload()
        return True


# =========================================================================================================
# تفویض اختیار
# =========================================================================================================
@ms.styled
class DelegationsScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.rows: list[tasks.DelegationRow] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("تفویض اختیار")
        title.setObjectName("pageTitle")
        self.history = QCheckBox("نمایش تفویض‌های گذشته")
        self.history.toggled.connect(lambda _c: self.reload())
        self.everyone = QCheckBox("همهٔ کاربران")
        self.everyone.toggled.connect(lambda _c: self.reload())
        outer.addWidget(ms.header_card(title, self.history, self.everyone))
        hint = QLabel("وقتی در مرخصی یا مأموریت هستید، کارهای تایید شما در بازهٔ تعیین‌شده به جانشین می‌رسد و در "
                      "تاریخچه «به جای شما» ثبت می‌شود.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)
        cards, self.cards = ms.summary([("mine", "تفویض فعال من", "info", "📤"), ("to_me", "تفویض به من", "success", "📥"),
                                        ("upcoming", "تفویض آینده", "neutral", "🗓️")], per_row=3)
        outer.addWidget(cards)
        self.table = table(["از", "به", "از تاریخ", "تا تاریخ", "دامنه", "علت", "وضعیت"])
        outer.addWidget(self.table, stretch=1)
        self.buttons = {"new": QPushButton("تفویض جدید"), "end": QPushButton("پایان تفویض"), "refresh": QPushButton("تازه‌سازی")}
        self.buttons["new"].clicked.connect(lambda: self.create())
        self.buttons["end"].clicked.connect(lambda: self.end_selected())
        self.buttons["refresh"].clicked.connect(lambda: self.reload())
        outer.addWidget(ms.footer([[self.buttons["new"], self.buttons["end"]], [self.buttons["refresh"]]]))

    def refresh(self) -> None:
        self.everyone.setVisible(roles_service.is_manager(user_id(), company_id()) if user_id() and company_id() else False)
        self.reload()

    def reload(self) -> None:
        if company_id() is None or user_id() is None:
            return
        uid = None if (self.everyone.isVisible() and self.everyone.isChecked()) else user_id()
        self.rows = tasks.list_delegations(company_id(), uid, include_inactive=self.history.isChecked())
        today = datetime.date.today()

        def state(r):
            if not r.is_active or r.ends_on < today:
                return "پایان‌یافته"
            return "فعال" if r.is_current else "آینده"

        fill(self.table, [[r.from_name, r.to_name, r.starts_on, r.ends_on, r.scope, r.reason, state(r)] for r in self.rows],
             [r.delegation_id for r in self.rows])
        me = user_id()
        self.cards["mine"].setText(P(sum(1 for r in self.rows if r.from_user_id == me and r.is_current)))
        self.cards["to_me"].setText(P(sum(1 for r in self.rows if r.to_user_id == me and r.is_current)))
        self.cards["upcoming"].setText(P(sum(1 for r in self.rows if r.is_active and r.starts_on > today)))

    def create(self, values: dict | None = None) -> int | None:
        if values is None:
            users = company_user_choices()
            from_box = combo(users)
            set_combo(from_box, user_id())
            from_box.setEnabled(roles_service.is_manager(user_id(), company_id()))
            from peecha.services.workflow import definitions as wf_defs

            scope = combo([(d.name, d.definition_id) for d in wf_defs.list_definitions(company_id())], "همهٔ کارها")
            move = QCheckBox("کارهای باز فعلی هم به جانشین سپرده شود")
            move.setChecked(True)
            values = _ask(self, "تفویض جدید", [("from", "تفویض‌کننده", from_box), ("to", "جانشین", combo(users)),
                                               ("starts_on", "از تاریخ", date_field()),
                                               ("ends_on", "تا تاریخ", date_field(datetime.date.today() + datetime.timedelta(days=7))),
                                               ("definition_id", "دامنه", scope), ("reason", "علت", QLineEdit()), ("move", "", move)])
            if values is None:
                return None
        did, ok = _run(self, "تفویض اختیار", tasks.create_delegation, company_id(), user_id(), values.get("from") or user_id(),
                       values["to"], values["starts_on"], values["ends_on"], definition_id=values.get("definition_id"),
                       reason=values.get("reason") or "", move_open_tasks=values.get("move", True))
        if ok:
            self.reload()
        return did

    def end_selected(self) -> bool:
        items = self.table.selectedItems()
        if not items:
            _warn(self, "تفویض اختیار", "یک تفویض را انتخاب کنید.")
            return False
        did = self.table.item(items[0].row(), 0).data(Qt.UserRole)
        _r, ok = _run(self, "تفویض اختیار", tasks.end_delegation, company_id(), did, user_id())
        if ok:
            self.reload()
        return ok


# =========================================================================================================
# تنظیمات گردش کار (چرخ‌دندهٔ کنار منو ← تنظیمات سیستم › گردش کار)
# =========================================================================================================
@ms.styled
class WfRulesPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        self.self_approval = QCheckBox("درخواست‌کننده بتواند درخواست خودش را تایید کند (توصیه نمی‌شود)")
        self.notify_end = QCheckBox("پس از پایان هر فرایند به درخواست‌کننده خبر داده شود")
        self.max_steps = num_field()
        self.max_depth = num_field()
        grid = QGridLayout()
        grid.addWidget(QLabel("حداکثر مراحل اجرای هر فرایند"), 0, 0)
        grid.addWidget(self.max_steps, 0, 1)
        grid.addWidget(QLabel("حداکثر زنجیرهٔ رویدادهای پشت‌سرهم"), 1, 0)
        grid.addWidget(self.max_depth, 1, 1)
        for w in (self.self_approval, self.notify_end):
            layout.addWidget(w)
        layout.addLayout(grid)
        hint = QLabel("این سقف‌ها جلوی اجرای بی‌پایان یک فرایند اشتباه را می‌گیرند؛ در حالت عادی نیازی به تغییر نیست.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        self.save_btn = QPushButton("ذخیرهٔ قواعد")
        self.save_btn.clicked.connect(lambda: self.save())
        layout.addWidget(ms.footer([[self.save_btn]]))

    def refresh(self) -> None:
        if company_id() is None:
            return
        s = wf_settings(company_id())
        self.self_approval.setChecked(bool(s.get("allow_self_approval")))
        self.notify_end.setChecked(bool(s.get("notify_starter_on_end", True)))
        self.max_steps.setText(P(s.get("max_steps") or 200))
        self.max_depth.setText(P(s.get("max_event_depth") or 5))

    def save(self) -> bool:
        try:
            steps = int(numerals.to_ascii_digits(self.max_steps.text().strip() or "200"))
            depth = int(numerals.to_ascii_digits(self.max_depth.text().strip() or "5"))
        except ValueError:
            _warn(self, "قواعد گردش کار", "سقف‌ها باید عدد صحیح باشند.")
            return False
        if not 10 <= steps <= 5000 or not 1 <= depth <= 20:
            _warn(self, "قواعد گردش کار", "حداکثر مراحل بین ۱۰ تا ۵۰۰۰ و زنجیرهٔ رویدادها بین ۱ تا ۲۰ باشد.")
            return False
        save_settings(company_id(), user_id(), allow_self_approval=self.self_approval.isChecked(),
                      notify_starter_on_end=self.notify_end.isChecked(), max_steps=steps, max_event_depth=depth)
        return True


@ms.styled
class CalendarPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.dialog_runner = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        title = QLabel("ساعت کاری هفته")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        grid = QGridLayout()
        self.days: dict[int, tuple[QCheckBox, QLineEdit, QLineEdit]] = {}
        for r, day in enumerate(wf_calendar.WEEK_ORDER):
            on = QCheckBox(wf_calendar.WEEKDAYS[day])
            start, end = QLineEdit(), QLineEdit()
            start.setPlaceholderText("۰۸:۰۰")
            end.setPlaceholderText("۱۶:۰۰")
            grid.addWidget(on, r, 0)
            grid.addWidget(QLabel("از"), r, 1)
            grid.addWidget(start, r, 2)
            grid.addWidget(QLabel("تا"), r, 3)
            grid.addWidget(end, r, 4)
            self.days[day] = (on, start, end)
        layout.addLayout(grid)
        self.save_hours_btn = QPushButton("ذخیرهٔ ساعت کاری")
        self.save_hours_btn.clicked.connect(lambda: self.save_hours())
        layout.addWidget(ms.footer([[self.save_hours_btn]]))
        h_title = QLabel("تعطیلات رسمی")
        h_title.setObjectName("sectionTitle")
        layout.addWidget(h_title)
        hint = QLabel("مهلت کارها با ساعت کاری حساب می‌شود؛ روزهای تعطیل و بیرون از ساعت کاری شمرده نمی‌شوند.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.t_holidays = table(["تاریخ", "عنوان"])
        layout.addWidget(self.t_holidays, stretch=1)
        self.add_btn, self.del_btn = QPushButton("تعطیلی جدید"), QPushButton("حذف تعطیلی")
        self.add_btn.clicked.connect(lambda: self.add_holiday())
        self.del_btn.clicked.connect(lambda: self.delete_holiday())
        layout.addWidget(ms.footer([[self.add_btn, self.del_btn]]))

    def refresh(self) -> None:
        if company_id() is None:
            return
        hours = wf_calendar.work_hours(company_id())
        for day, (on, start, end) in self.days.items():
            span = hours.get(day)
            on.setChecked(span is not None)
            start.setText(P(span[0].strftime("%H:%M")) if span else "")
            end.setText(P(span[1].strftime("%H:%M")) if span else "")
        rows = wf_calendar.list_holidays(company_id())
        fill(self.t_holidays, [[h.holiday_date, h.title] for h in rows], [h.holiday_id for h in rows])

    def save_hours(self) -> bool:
        hours = {}
        for day, (on, start, end) in self.days.items():
            if on.isChecked():
                hours[day] = (numerals.to_ascii_digits(start.text().strip() or "08:00"),
                              numerals.to_ascii_digits(end.text().strip() or "16:00"))
        _r, ok = _run(self, "ساعت کاری", wf_calendar.save_work_hours, company_id(), user_id(), hours)
        if ok:
            self.refresh()
        return ok

    def add_holiday(self, values: dict | None = None) -> int | None:
        values = values or _ask(self, "تعطیلی جدید", [("date", "تاریخ", date_field()), ("title", "عنوان", QLineEdit())])
        if values is None:
            return None
        hid, ok = _run(self, "تعطیلات", wf_calendar.add_holiday, company_id(), user_id(), values["date"], values.get("title") or "")
        if ok:
            self.refresh()
        return hid

    def delete_holiday(self) -> bool:
        items = self.t_holidays.selectedItems()
        if not items:
            _warn(self, "تعطیلات", "یک روز را انتخاب کنید.")
            return False
        _r, ok = _run(self, "تعطیلات", wf_calendar.delete_holiday, company_id(), user_id(),
                      self.t_holidays.item(items[0].row(), 0).data(Qt.UserRole))
        if ok:
            self.refresh()
        return ok


def _escalation_choices() -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = [("مدیر مستقیم گیرنده", "[]"), ("مدیران شرکت", '[{"kind": "MANAGERS"}]')]
    for r in roles_service.list_roles(company_id()):
        out.append((f"نقش «{r.code}»", f'[{{"kind": "ROLE", "role_id": {r.role_id}}}]'))
    for name, uid in company_user_choices():
        out.append((name, f'[{{"kind": "USER", "user_id": {uid}}}]'))
    return out


@ms.styled
class SlaPoliciesPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.dialog_runner = None
        self.rows: list[sla.PolicyRow] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        hint = QLabel("برای هر مرحلهٔ تایید یا کار می‌توان یک سیاست انتخاب کرد: مهلت انجام، یادآوری پیش از موعد و ارجاع "
                      "خودکار به سطح بالاتر اگر کار به‌موقع انجام نشود.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.t_policies = table(["کد", "نام", "مهلت (ساعت)", "یادآوری پیش از موعد", "ارجاع پس از مهلت", "ارجاع به",
                                 "ساعت کاری", "فعال"])
        layout.addWidget(self.t_policies, stretch=1)
        self.buttons = {"new": QPushButton("سیاست جدید"), "edit": QPushButton("ویرایش سیاست"), "delete": QPushButton("حذف سیاست")}
        self.buttons["new"].clicked.connect(lambda: self.edit_policy(new=True))
        self.buttons["edit"].clicked.connect(lambda: self.edit_policy())
        self.buttons["delete"].clicked.connect(lambda: self.delete_policy())
        layout.addWidget(ms.footer([list(self.buttons.values())]))

    def refresh(self) -> None:
        if company_id() is None:
            return
        self.rows = sla.list_policies(company_id())
        yes = lambda b: "بله" if b else "خیر"  # noqa: E731
        fill(self.t_policies, [[r.code, r.name, r.due_hours, r.warn_before_hours or "—", r.escalate_after_hours
                                if r.escalate_after_hours is not None else "—", r.escalate_to_text, yes(r.business_hours),
                                yes(r.is_active)] for r in self.rows], [r.policy_id for r in self.rows])

    def edit_policy(self, new: bool = False, values: dict | None = None) -> int | None:
        import json

        row = None
        if not new:
            items = self.t_policies.selectedItems()
            if not items:
                _warn(self, "تعهد زمانی", "یک سیاست را انتخاب کنید.")
                return None
            pid = self.t_policies.item(items[0].row(), 0).data(Qt.UserRole)
            row = next(r for r in self.rows if r.policy_id == pid)
        if values is None:
            target = combo(_escalation_choices())
            set_combo(target, json.dumps(row.escalate_to) if row else "[]")
            business, active = QCheckBox("فقط ساعت کاری شمرده شود"), QCheckBox("فعال")
            business.setChecked(row.business_hours if row else True)
            active.setChecked(row.is_active if row else True)
            code = QLineEdit(row.code if row else "")
            code.setEnabled(row is None)
            values = _ask(self, "سیاست تعهد زمانی", [
                ("code", "کد", code), ("name", "نام", QLineEdit(row.name if row else "")),
                ("due_hours", "مهلت انجام (ساعت)", num_field(row.due_hours if row else 8)),
                ("warn_before_hours", "یادآوری چند ساعت پیش از موعد", num_field(row.warn_before_hours if row else 2)),
                ("escalate_after_hours", "ارجاع چند ساعت پس از مهلت", num_field(row.escalate_after_hours if row else 0)),
                ("escalate_to", "ارجاع به", target),
                ("repeat_every_hours", "تکرار ارجاع هر چند ساعت (خالی یعنی بدون تکرار)",
                 num_field(row.repeat_every_hours if row else None)),
                ("max_escalations", "حداکثر دفعات ارجاع", num_field(row.max_escalations if row else 2)),
                ("business_hours", "", business), ("is_active", "", active)])
            if values is None:
                return None
            values["escalate_to"] = json.loads(values.get("escalate_to") or "[]")
            for key in ("warn_before_hours", "repeat_every_hours"):
                if not values.get(key):
                    values[key] = None
        pid, ok = _run(self, "تعهد زمانی", sla.save_policy, company_id(), user_id(), row.policy_id if row else None,
                       code=values.get("code") or (row.code if row else ""), name=values.get("name") or "",
                       due_hours=values.get("due_hours"), warn_before_hours=values.get("warn_before_hours"),
                       escalate_after_hours=values.get("escalate_after_hours"), escalate_to=values.get("escalate_to") or [],
                       repeat_every_hours=values.get("repeat_every_hours"),
                       max_escalations=int(values.get("max_escalations") or 2),
                       business_hours=values.get("business_hours", True), is_active=values.get("is_active", True))
        if ok:
            self.refresh()
        return pid

    def delete_policy(self) -> str | None:
        items = self.t_policies.selectedItems()
        if not items:
            _warn(self, "تعهد زمانی", "یک سیاست را انتخاب کنید.")
            return None
        result, ok = _run(self, "تعهد زمانی", sla.delete_policy, company_id(), user_id(),
                          self.t_policies.item(items[0].row(), 0).data(Qt.UserRole))
        if ok:
            self.refresh()
        return result


@ms.styled
class NotificationDefaultsPanel(QWidget):
    """پیش‌فرض شرکت برای کانال‌های بیرونی هر نوع اعلان (هر کاربر می‌تواند برای خودش تغییر دهد)."""

    EXTERNAL = [("sms", "پیامک"), ("email", "ایمیل"), ("push", "اعلان گوشی")]

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        hint = QLabel("اعلان داخل برنامه همیشه ثبت می‌شود. این‌جا مشخص کنید برای کدام نوع اعلان، پیامک یا ایمیل یا اعلان "
                      "گوشی هم به‌طور پیش‌فرض فرستاده شود. ایمیل و اعلان گوشی پس از اتصال سرویس فعال می‌شوند.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.types = list(notify.TYPES.items())
        self.grid = QTableWidget(len(self.types), len(self.EXTERNAL))
        self.grid.setHorizontalHeaderLabels([label for _c, label in self.EXTERNAL])
        self.grid.setVerticalHeaderLabels([label for _t, label in self.types])
        layout.addWidget(self.grid, stretch=1)
        self.save_btn = QPushButton("ذخیرهٔ پیش‌فرض اعلان‌ها")
        self.save_btn.clicked.connect(lambda: self.save())
        layout.addWidget(ms.footer([[self.save_btn]]))

    def refresh(self) -> None:
        if company_id() is None:
            return
        defaults = wf_settings(company_id()).get("notification_defaults") or {}
        for r, (code, _l) in enumerate(self.types):
            for c, (ch, _cl) in enumerate(self.EXTERNAL):
                item = QTableWidgetItem()
                item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                item.setCheckState(Qt.Checked if (defaults.get(code) or {}).get(ch) else Qt.Unchecked)
                self.grid.setItem(r, c, item)

    def set_channel(self, type_code: str, channel: str, on: bool) -> None:
        r = [t for t, _l in self.types].index(type_code)
        c = [ch for ch, _l in self.EXTERNAL].index(channel)
        self.grid.item(r, c).setCheckState(Qt.Checked if on else Qt.Unchecked)

    def save(self) -> bool:
        out = {}
        for r, (code, _l) in enumerate(self.types):
            chosen = {ch: True for c, (ch, _cl) in enumerate(self.EXTERNAL) if self.grid.item(r, c).checkState() == Qt.Checked}
            if chosen:
                out[code] = chosen
        save_settings(company_id(), user_id(), notification_defaults=out)
        return True


@ms.styled
class OrgLinksPanel(QWidget):
    """کاربر سامانهٔ هر کارمند و مدیر هر واحد سازمانی — پایهٔ مسیر «مدیر مستقیم» و «مدیر واحد»."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        hint = QLabel("برای اینکه درخواست هر نفر خودکار به مدیرش برسد، کاربر سامانهٔ هر کارمند و مدیر هر واحد سازمانی را "
                      "مشخص کنید.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.t_emp = table(["کد", "نام کارمند", "کاربر سامانه"])
        self.t_unit = table(["واحد سازمانی", "مدیر واحد"])
        tabs = QTabWidget()
        e_box, u_box = QWidget(), QWidget()
        el, ul = QVBoxLayout(e_box), QVBoxLayout(u_box)
        el.addWidget(self.t_emp)
        ul.addWidget(self.t_unit)
        self.save_emp_btn, self.save_unit_btn = QPushButton("ذخیرهٔ کاربران کارکنان"), QPushButton("ذخیرهٔ مدیران واحدها")
        self.save_emp_btn.clicked.connect(lambda: self.save_employees())
        self.save_unit_btn.clicked.connect(lambda: self.save_units())
        el.addWidget(ms.footer([[self.save_emp_btn]]))
        ul.addWidget(ms.footer([[self.save_unit_btn]]))
        tabs.addTab(e_box, "کارکنان و کاربران")
        tabs.addTab(u_box, "مدیر واحدها")
        layout.addWidget(tabs, stretch=1)
        self.emp_ids: list[int] = []
        self.unit_ids: list[int] = []

    def refresh(self) -> None:
        if company_id() is None:
            return
        from peecha.db.base import new_session
        from peecha.db.models.hr import Employee, OrganizationalUnit
        from sqlalchemy import select

        users = company_user_choices()
        with new_session() as session:
            emps = list(session.scalars(select(Employee).where(Employee.company_id == company_id()).order_by(Employee.employee_code)))
            units = list(session.scalars(select(OrganizationalUnit).where(OrganizationalUnit.company_id == company_id())
                                         .order_by(OrganizationalUnit.code)))
        self.emp_ids = [e.employee_id for e in emps]
        self.t_emp.setRowCount(len(emps))
        for r, e in enumerate(emps):
            self.t_emp.setItem(r, 0, QTableWidgetItem(P(e.employee_code)))
            self.t_emp.setItem(r, 1, QTableWidgetItem(f"{e.first_name} {e.last_name}".strip()))
            box = combo(users, "—")
            set_combo(box, e.user_id)
            self.t_emp.setCellWidget(r, 2, box)
        emp_choices = [(f"{e.first_name} {e.last_name}".strip(), e.employee_id) for e in emps]
        self.unit_ids = [u.org_unit_id for u in units]
        self.t_unit.setRowCount(len(units))
        for r, u in enumerate(units):
            self.t_unit.setItem(r, 0, QTableWidgetItem(u.name))
            box = combo(emp_choices, "—")
            set_combo(box, u.manager_employee_id)
            self.t_unit.setCellWidget(r, 1, box)

    def save_employees(self) -> bool:
        from peecha.services import hr as hr_service

        for r, eid in enumerate(self.emp_ids):
            _x, ok = _run(self, "کارکنان و کاربران", hr_service.set_employee_user, company_id(), eid, self.t_emp.cellWidget(r, 2).currentData())
            if not ok:
                return False
        return True

    def save_units(self) -> bool:
        from peecha.services import hr as hr_service

        for r, unit_id in enumerate(self.unit_ids):
            _x, ok = _run(self, "مدیر واحدها", hr_service.set_org_unit_manager, company_id(), unit_id,
                          self.t_unit.cellWidget(r, 1).currentData())
            if not ok:
                return False
        return True


SETTINGS_PANELS = [("قواعد عمومی", WfRulesPanel), ("تقویم کاری و تعطیلات", CalendarPanel),
                   ("تعهد زمانی و ارجاع", SlaPoliciesPanel), ("پیش‌فرض اعلان‌ها", NotificationDefaultsPanel),
                   ("کارکنان و مدیران", OrgLinksPanel)]


class WorkflowSettingsScreen(QWidget):
    """همان زیرتب‌های «تنظیمات سیستم › گردش کار» در یک صفحه."""

    def __init__(self, main_window=None) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        title = QLabel("تنظیمات گردش کار")
        title.setObjectName("pageTitle")
        layout.addWidget(ms.header_card(title))
        self.tabs = QTabWidget()
        self.panels = [cls() for _label, cls in SETTINGS_PANELS]
        for (label, _cls), panel in zip(SETTINGS_PANELS, self.panels):
            self.tabs.addTab(panel, label)
        self.tabs.currentChanged.connect(lambda i: self.panels[i].refresh())
        layout.addWidget(self.tabs, stretch=1)

    def refresh(self) -> None:
        self.panels[self.tabs.currentIndex()].refresh()
