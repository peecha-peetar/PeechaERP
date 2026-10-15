"""صفحه‌های افتتاحیه و انتقال اطلاعات (R314) — هم‌شکل بقیهٔ ماژول‌ها: دکمه‌های آیکونی، کارت خلاصه، جدول و فرم کوچک.

مرکز افتتاحیه (فرایند، ماژول‌ها، مسئولان، گردش ورود/تأیید/ثبت/قفل، تاریخچه)، ورود و بارگذاری اطلاعات (قالب، فایل،
پیش‌نمایش خطا، ورود دستی)، تطبیق با تراز و تنظیمات (چرخ‌دندهٔ کنار منو). همهٔ منطق در services/opening است.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services.opening import common as c
from peecha.services.opening import finalize as ofin
from peecha.services.opening import importer as oim
from peecha.services.opening import modules as omod
from peecha.services.opening import posting as opost
from peecha.services.opening import reconcile as orec
from peecha.services.opening import runs as orun
from peecha.ui import theme
from peecha.ui.screens import module_style as ms
from peecha.ui.screens.fixed_assets import P, combo, company_id, fill, set_combo, table, user_id
from peecha.ui.screens.quality import _ask, _buttons as _btns, _confirm, _fill_result, _hint, _run, _selected, _text, _title, _warn
from peecha.ui.widgets import FieldHelpMixin, JalaliDateEdit

ms.ICONS.update({
    "فرایند جدید": ("🆕", "primary"), "ویرایش فرایند": ("✏️", ""), "ماژول‌ها": ("🧩", ""), "مسئولان ماژول": ("👥", ""),
    "لغو فرایند": ("🚫", "danger"), "ارسال برای بررسی": ("📨", "primary"), "تأیید اطلاعات": ("✅", "primary"),
    "رد اطلاعات": ("❌", "danger"), "ثبت قطعی ماژول": ("📌", "primary"), "برگرداندن ردیف‌های ناموفق": ("↩️", ""),
    "قفل نهایی": ("🔒", "primary"), "افتتاحیهٔ اصلاحی": ("📝", ""), "برگشت سند باز": ("↩️", "danger"),
    "ورود اطلاعات ماژول": ("📥", ""), "تطبیق با تراز": ("⚖️", ""), "گزارش کامل": ("📈", ""),
    "دریافت قالب اکسل": ("📗", ""), "دریافت قالب متنی": ("📄", ""), "بارگذاری فایل": ("📤", "primary"),
    "ردیف جدید": ("➕", "primary"), "ویرایش ردیف": ("✏️", ""), "حذف ردیف": ("🗑️", "danger"),
    "اعتبارسنجی دوباره": ("🔁", ""), "خروجی ردیف‌ها و خطاها": ("💾", ""), "ذخیرهٔ تنظیمات افتتاحیه": ("💾", "primary"),
    "ساخت نقش‌های آمادهٔ افتتاحیه": ("👥", "primary"),
})

_RED, _AMBER, _GREEN, _GREY = QColor("#EF4444"), QColor("#F59E0B"), QColor("#10B981"), QColor("#94A3B8")
_ROW_TONE = {"INVALID": _RED, "FAILED": _RED, "POSTED": _GREEN, "REVERSED": _GREY}
_MODULE_TONE = {"HAS_ERRORS": _RED, "READY": _AMBER, "APPROVED": _AMBER, "POSTING": _AMBER, "POSTED": _GREEN, "LOCKED": _GREEN,
                "NOT_STARTED": _GREY}


def _tone(t, row: int, color: QColor | None) -> None:
    if color is None:
        return
    for col in range(t.columnCount()):
        item = t.item(row, col)
        if item is not None:
            item.setForeground(color)


def _money(v) -> str:
    return numerals.format_money(c.dec(v), 0, None) if v is not None else "—"


def _done(screen, text: str) -> None:
    theme.set_status_label(screen.status_label, P(text), ok=True)


def _users(cid: int) -> list[tuple[str, int]]:
    from peecha.services.crm.common import list_company_users

    return [(name, uid) for uid, name in list_company_users(cid)]


def _runs_combo(box: QComboBox, cid: int, keep=None, include_cancelled: bool = False) -> None:
    box.blockSignals(True)
    box.clear()
    for r in orun.list_runs(cid, include_cancelled=include_cancelled):
        box.addItem(P(f"{r.code} — {r.title} ({r.status_label})"), r.run_id)
    set_combo(box, keep)
    box.blockSignals(False)


# =========================================================================================================
# مرکز افتتاحیه
# =========================================================================================================
@ms.styled
class OpeningCenterScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.confirm = None
        self.run = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.addWidget(ms.header_card(_title("مرکز افتتاحیه و انتقال اطلاعات")))
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.t_runs = table(["کد", "عنوان", "نوع", "سال مالی", "تاریخ مانده‌ها", "شروع عملیات", "وضعیت", "پیشرفت"])
        self.t_runs.itemSelectionChanged.connect(self._load_run)
        ll.addWidget(self.t_runs)
        split.addWidget(left)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.head = _hint("")
        rl.addWidget(self.head)
        cards, self.cards = ms.summary([("status", "وضعیت فرایند", "info", "📌"), ("progress", "پیشرفت", "success", "📊"),
                                        ("posted", "ماژول ثبت‌شده", "success", "✅"), ("problems", "موارد ناقص", "danger", "⚠️")])
        rl.addWidget(cards)
        self.tabs = QTabWidget()
        self.t_mods = table(["ماژول", "وضعیت", "پیشرفت", "مسئول ورود", "تأییدکننده", "ردیف", "معتبر", "دارای خطا", "ثبت‌شده",
                             "مبلغ", "موارد ناقص"])
        self.t_mods.cellDoubleClicked.connect(lambda _r, _c: self.open_data())
        self.tabs.addTab(self.t_mods, "ماژول‌ها")
        self.t_events = table(["زمان", "رویداد", "ماژول", "کاربر", "توضیح"])
        self.tabs.addTab(self.t_events, "تاریخچه")
        self.t_files = table(["ماژول", "نسخه", "نام فایل", "ردیف", "معتبر", "دارای خطا", "کاربر", "زمان"])
        self.tabs.addTab(self.t_files, "فایل‌های بارگذاری‌شده")
        self.t_docs = table([])
        self.tabs.addTab(self.t_docs, "اسناد ساخته‌شده")
        rl.addWidget(self.tabs, stretch=1)
        split.addWidget(right)
        split.setStretchFactor(1, 3)
        outer.addWidget(split, stretch=1)
        b = _btns(self, [
            ("new", "فرایند جدید", self.new_run), ("edit", "ویرایش فرایند", self.edit_run), ("modules", "ماژول‌ها", self.edit_modules),
            ("people", "مسئولان ماژول", self.set_people), ("cancel", "لغو فرایند", self.cancel_run),
            ("data", "ورود اطلاعات ماژول", self.open_data), ("submit", "ارسال برای بررسی", self.submit),
            ("approve", "تأیید اطلاعات", self.approve), ("reject", "رد اطلاعات", self.reject),
            ("post", "ثبت قطعی ماژول", self.post), ("back", "برگرداندن ردیف‌های ناموفق", self.return_failed),
            ("lock", "قفل نهایی", self.lock), ("correction", "افتتاحیهٔ اصلاحی", self.new_correction),
            ("reverse", "برگشت سند باز", self.reverse_item), ("reconcile", "تطبیق با تراز", self.open_reconcile),
            ("refresh", "به‌روزرسانی", self.refresh)])
        outer.addWidget(ms.footer([[b["new"], b["edit"], b["modules"], b["people"], b["cancel"]],
                                   [b["data"], b["submit"], b["approve"], b["reject"]],
                                   [b["post"], b["back"], b["reconcile"], b["lock"]], [b["correction"], b["reverse"], b["refresh"]]]))
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)

    # --- بارگذاری ---------------------------------------------------------------------------------------
    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        keep = self.run.run_id if self.run else None
        self.runs = orun.list_runs(cid)
        fill(self.t_runs, [[r.code, r.title, r.kind_label, r.fiscal_year, r.balance_date, r.go_live_date, r.status_label,
                            P(f"{r.progress}٪")] for r in self.runs], [r.run_id for r in self.runs])
        for i, r in enumerate(self.runs):
            _tone(self.t_runs, i, _GREY if r.status_code == "CANCELLED" else (_GREEN if r.status_code == "LOCKED" else None))
        if keep:
            self.open_run(keep)
        elif self.runs:
            self.t_runs.selectRow(0)
        self._apply_buttons()

    def open_run(self, run_id: int) -> None:
        for row in range(self.t_runs.rowCount()):
            if self.t_runs.item(row, 0).data(Qt.UserRole) == run_id:
                self.t_runs.selectRow(row)
                self._load_run()
                return

    def _load_run(self) -> None:
        cid, run_id = company_id(), _selected(self.t_runs)
        if cid is None or run_id is None:
            self.run = None
            self._apply_buttons()
            return
        self.run = r = orun.get_run(cid, run_id)
        kind = f" — اصلاح فرایند #{r.corrects_run_id}" if r.corrects_run_id else ""
        self.head.setText(P(f"{r.code} — {r.title}{kind} | سال مالی {r.fiscal_year} | مانده‌ها تا {numerals.format_jalali_date(r.balance_date)}"
                            f" | شروع کار با سیستم {numerals.format_jalali_date(r.go_live_date)} | ایجاد: {r.created_by}"))
        self.cards["status"].setText(r.status_label)
        self.cards["progress"].setText(P(f"{r.progress}٪"))
        self.cards["posted"].setText(P(f"{sum(1 for m in r.modules if m.status_code in ('POSTED', 'LOCKED'))} از {len(r.modules)}"))
        self.cards["problems"].setText(P(sum(len(m.problems) for m in r.modules)))
        fill(self.t_mods, [[m.label, m.status_label, P(f"{m.progress}٪"), m.owner or "—", m.approver or "—", m.total, m.valid,
                            m.invalid, m.posted, m.amount, "؛ ".join(m.problems + ([f"رد: {m.reject_reason}"] if m.reject_reason else []))]
                           for m in r.modules], [m.module_code for m in r.modules])
        for i, m in enumerate(r.modules):
            _tone(self.t_mods, i, _MODULE_TONE.get(m.status_code))
        fill(self.t_events, [[numerals.format_jalali_date(e.at.date()) + " " + e.at.strftime("%H:%M"), e.label, e.module, e.user,
                              e.comment] for e in r.events])
        fill(self.t_files, [[b.module_label, b.version_no, b.file_name, b.rows, b.valid, b.invalid, b.user,
                             numerals.format_jalali_date(b.at.date())] for b in oim.list_batches(cid, r.run_id)])
        from peecha.services import purchase_reports as pr
        from peecha.services.opening import reports as orep

        result = orep.documents_report(cid, pr.PurchaseFilters(r.go_live_date, r.go_live_date, options={"cancelled": "SHOW"}))
        result.rows = [row for row in result.rows if row[0] == r.code]
        _fill_result(self.t_docs, result)
        self._apply_buttons()

    def _module(self) -> str | None:
        return _selected(self.t_mods)

    def _apply_buttons(self) -> None:
        cid, uid = company_id(), user_id()
        r = self.run
        has = r is not None
        can = (lambda form: cid is not None and c.can(cid, uid, form))  # noqa: E731
        st = r.status_code if has else ""
        correction = has and r.kind_code == "CORRECTION"
        setup = c.FORM_CORRECT if correction else c.FORM_SETUP
        self.buttons["new"].setEnabled(can(c.FORM_SETUP))
        for key in ("edit", "modules", "people", "cancel"):
            self.buttons[key].setEnabled(has and st in ("DRAFT", "IN_PROGRESS") and can(setup))
        self.buttons["people"].setEnabled(has and st in orun.ENTRY_RUN and can(setup))
        for key in ("data", "submit"):
            self.buttons[key].setEnabled(has and st in orun.ENTRY_RUN and can(c.FORM_ENTER))
        for key in ("approve", "reject"):
            self.buttons[key].setEnabled(has and st in orun.ENTRY_RUN and can(c.FORM_APPROVE))
        for key in ("post", "back"):
            self.buttons[key].setEnabled(has and st in ("IN_PROGRESS", "POSTING") and can(c.FORM_POST))
        self.buttons["lock"].setEnabled(has and st == "POSTED" and can(c.FORM_POST))
        self.buttons["correction"].setEnabled(has and st == "LOCKED" and not correction and can(c.FORM_CORRECT))
        self.buttons["reverse"].setEnabled(correction and st in orun.ENTRY_RUN and can(c.FORM_CORRECT))
        self.buttons["reconcile"].setEnabled(has)

    # --- تعریف فرایند --------------------------------------------------------------------------------------
    def _module_boxes(self, selected=()) -> list:
        out = []
        for code, label in c.MODULE_LABELS.items():
            box = QCheckBox(label)
            box.setChecked(code in selected)
            out.append((f"m_{code}", "", box))
        return out

    def new_run(self, corrects: int | None = None) -> int | None:
        from peecha.services import fiscal_years

        cid = company_id()
        fys = combo([(f.code, f.fiscal_year_id) for f in fiscal_years.list_fiscal_years(cid)])
        balance, go_live = JalaliDateEdit(), JalaliDateEdit()
        default = ("GL", "INVENTORY", "RECEIVABLES", "PAYABLES") if corrects is None else ()
        title = "افتتاحیهٔ اصلاحی" if corrects else "فرایند جدید"
        fields = [("code", "کد", QLineEdit()), ("title", "عنوان", QLineEdit())]
        if corrects is None:
            fields += [("fy", "سال مالی", fys), ("balance", "تاریخ مانده‌ها (روز برش)", balance),
                       ("go_live", "شروع کار با سیستم (تاریخ اسناد)", go_live)]
        fields += self._module_boxes(default) + [("notes", "توضیح", _text())]
        hint = ("تاریخ اسناد افتتاحیه همان «شروع کار با سیستم» است و باید در سال مالی باشد؛ مانده‌ها تا «روز برش» از سیستم قبلی "
                "منتقل می‌شوند. برای هر شرکت و سال مالی فقط یک افتتاحیهٔ اصلی ساخته می‌شود.") if corrects is None else (
                "ردیف‌های تازه مثل افتتاحیهٔ اصلی ثبت می‌شوند، تراز این فرایند «تفاوت» است و سند باز اشتباه با «برگشت سند باز» "
                "کنار می‌رود.")
        v = _ask(self, title, fields, hint)
        if v is None:
            return None
        modules = [code for code in c.MODULE_LABELS if v.get(f"m_{code}")]
        if corrects is None:
            rid, ok = _run(self, title, orun.create_run, cid, user_id(), v["code"] or "", v["title"] or "", v["fy"], v["balance"],
                           modules, go_live_date=v["go_live"], notes=v["notes"])
        else:
            rid, ok = _run(self, title, orun.create_run, cid, user_id(), v["code"] or "", v["title"] or "", self.run.fiscal_year_id,
                           self.run.balance_date, modules, go_live_date=self.run.go_live_date, notes=v["notes"], corrects_run_id=corrects)
        if ok:
            _done(self, "فرایند ساخته شد؛ مسئول ورود و تأییدکنندهٔ هر ماژول را تعیین کنید.")
            self.refresh()
            self.open_run(rid)
        return rid if ok else None

    def new_correction(self) -> int | None:
        return self.new_run(corrects=self.run.run_id) if self.run else None

    def edit_run(self) -> bool:
        r = self.run
        if r is None:
            return False
        balance, go_live = JalaliDateEdit(), JalaliDateEdit()
        balance.setDate(r.balance_date)
        go_live.setDate(r.go_live_date)
        v = _ask(self, "ویرایش فرایند", [("title", "عنوان", QLineEdit(r.title)), ("balance", "تاریخ مانده‌ها (روز برش)", balance),
                                         ("go_live", "شروع کار با سیستم", go_live), ("notes", "توضیح", _text(r.notes))])
        if v is None:
            return False
        _r, ok = _run(self, "ویرایش فرایند", orun.update_run, company_id(), user_id(), r.run_id, v["title"] or "", v["balance"],
                      v["go_live"], v["notes"])
        if ok:
            _done(self, "مشخصات فرایند ذخیره شد.")
            self.refresh()
        return ok

    def edit_modules(self) -> bool:
        r = self.run
        if r is None:
            return False
        v = _ask(self, "ماژول‌های فرایند", self._module_boxes([m.module_code for m in r.modules]),
                 "ماژولی که اطلاعات واردشده دارد حذف نمی‌شود.")
        if v is None:
            return False
        _r, ok = _run(self, "ماژول‌ها", orun.set_modules, company_id(), user_id(), r.run_id,
                      [code for code in c.MODULE_LABELS if v.get(f"m_{code}")])
        if ok:
            _done(self, "ماژول‌های فرایند به‌روز شد.")
            self.refresh()
        return ok

    def set_people(self) -> bool:
        r, module = self.run, self._module()
        if r is None or module is None:
            _warn(self, "مسئولان ماژول", "ابتدا یک ماژول را انتخاب کنید.")
            return False
        m = next(x for x in r.modules if x.module_code == module)
        users = _users(company_id())
        owner, approver = combo(users, "—"), combo(users, "—")
        set_combo(owner, m.owner_user_id)
        set_combo(approver, m.approver_user_id)
        v = _ask(self, f"مسئولان «{m.label}»", [("owner", "مسئول ورود اطلاعات", owner), ("approver", "تأییدکننده", approver)],
                 "مسئول ورود و تأییدکننده دو نفر متفاوت‌اند (مگر کلید «تأیید توسط واردکننده» روشن باشد).")
        if v is None:
            return False
        _r, ok = _run(self, "مسئولان ماژول", orun.set_people, company_id(), user_id(), r.run_id, module, v["owner"], v["approver"])
        if ok:
            _done(self, "مسئولان ماژول ذخیره شد.")
            self.refresh()
        return ok

    def cancel_run(self) -> bool:
        r = self.run
        if r is None:
            return False
        v = _ask(self, "لغو فرایند", [("reason", "دلیل", _text())], "فقط فرایندی که هیچ بخشش ثبت قطعی نشده لغو می‌شود.")
        if v is None:
            return False
        _r, ok = _run(self, "لغو فرایند", orun.cancel_run, company_id(), user_id(), r.run_id, v["reason"] or "")
        if ok:
            _done(self, "فرایند لغو شد.")
            self.refresh()
        return ok

    # --- گردش ماژول ---------------------------------------------------------------------------------------
    def _module_action(self, title: str, fn, *extra, ask_comment: str | None = None, required: bool = False) -> bool:
        r, module = self.run, self._module()
        if r is None or module is None:
            _warn(self, title, "ابتدا یک ماژول را انتخاب کنید.")
            return False
        comment = None
        if ask_comment is not None:
            v = _ask(self, title, [("comment", ask_comment, _text())])
            if v is None:
                return False
            comment = v["comment"] or ("" if required else None)
        _r, ok = _run(self, title, fn, company_id(), user_id(), r.run_id, module, *extra,
                      *((comment,) if ask_comment is not None else ()))
        if ok:
            _done(self, f"{title} انجام شد.")
            self.refresh()
        return ok

    def submit(self) -> bool:
        return self._module_action("ارسال برای بررسی", orun.submit, ask_comment="توضیح (اختیاری)")

    def approve(self) -> bool:
        return self._module_action("تأیید اطلاعات", orun.approve, ask_comment="نظر (اختیاری)")

    def reject(self) -> bool:
        return self._module_action("رد اطلاعات", orun.reject, ask_comment="دلیل رد", required=True)

    def return_failed(self) -> bool:
        return self._module_action("برگرداندن ردیف‌های ناموفق", opost.return_failed_to_entry, ask_comment="توضیح (اختیاری)")

    def post(self) -> bool:
        r, module = self.run, self._module()
        if r is None or module is None:
            _warn(self, "ثبت قطعی", "ابتدا یک ماژول را انتخاب کنید.")
            return False
        reason = None
        if module == "GL":
            rec = orec.report(company_id(), r.run_id)
            if rec.projected_clearing and c.settings(company_id()).difference_policy == "APPROVAL":
                v = _ask(self, "ثبت با اختلاف", [("reason", "دلیل ثبت با اختلاف", _text())],
                         P(f"زیرسیستم‌ها با تراز {_money(rec.projected_clearing)} اختلاف دارند؛ این مبلغ به «حساب اختلاف افتتاحیه» "
                           "می‌رود و با نام شما ثبت می‌شود."))
                if v is None:
                    return False
                reason = v["reason"]
        elif not _confirm(self, "ثبت قطعی", f"«{c.MODULE_LABELS[module]}» با سرویس رسمی ثبت شود؟ پس از ثبت، تغییر فقط با افتتاحیهٔ اصلاحی است."):
            return False
        res, ok = _run(self, "ثبت قطعی", opost.post_module, company_id(), user_id(), r.run_id, module, reason)
        if ok:
            if res.failed:
                _warn(self, "ثبت قطعی", P(f"{res.done} گام ثبت شد و {len(res.failed)} گام ناموفق ماند:\n" + "\n".join(res.failed[:5])))
            else:
                _done(self, f"«{c.MODULE_LABELS[module]}» ثبت قطعی شد.")
            self.refresh()
        return ok

    def lock(self) -> bool:
        r = self.run
        if r is None or not _confirm(self, "قفل نهایی", "همهٔ اسناد افتتاحیه دائم می‌شوند و فرایند قفل می‌شود. ادامه می‌دهید؟"):
            return False
        res, ok = _run(self, "قفل نهایی", ofin.lock_run, company_id(), user_id(), r.run_id)
        if ok:
            _done(self, f"فرایند قفل شد؛ {res.approved_now} سند حسابداری دائم شد.")
            self.refresh()
        return ok

    def reverse_item(self) -> bool:
        r = self.run
        if r is None:
            return False
        items = ofin.reversible_rows(company_id(), r.run_id)
        if not items:
            _warn(self, "برگشت سند باز", "سند بازی برای برگشت در افتتاحیهٔ اصلی نیست.")
            return False
        v = _ask(self, "برگشت سند باز", [
            ("row", "سند باز منتقل‌شده", combo([(f"{x.module} — {x.key} — {_money(x.amount)}", x.row_id) for x in items])),
            ("reason", "دلیل", _text())], "سند برگشتی با حساب واسط ثبت می‌شود و سند باز باطل می‌شود؛ تراز همین فرایند باید تفاوت را بیاورد.")
        if v is None:
            return False
        _r, ok = _run(self, "برگشت سند باز", ofin.reverse_open_item, company_id(), user_id(), r.run_id, v["row"], v["reason"] or "")
        if ok:
            _done(self, "سند باز برگشت خورد.")
            self.refresh()
        return ok

    def open_data(self) -> None:
        r, module = self.run, self._module()
        if self._main_window is not None and r is not None:
            self._main_window.open_screen("OPN_DATA", then=lambda s: s.select(r.run_id, module))

    def open_reconcile(self) -> None:
        r = self.run
        if self._main_window is not None and r is not None:
            self._main_window.open_screen("OPN_RECONCILE", then=lambda s: s.select(r.run_id))


# =========================================================================================================
# ورود و بارگذاری اطلاعات
# =========================================================================================================
_STATUS_FILTER = [("همهٔ ردیف‌ها", None), ("دارای خطا", "INVALID"), ("ثبت ناموفق", "FAILED"), ("معتبر", "VALID"),
                  ("ثبت‌شده", "POSTED"), ("برگشت‌خورده", "REVERSED")]


@ms.styled
class OpeningDataScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.confirm = None
        self.open_file_picker = None   # آزمون: مسیر فایل ورودی
        self.save_file_picker = None   # آزمون: مسیر فایل خروجی
        self.rows: list = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        self.run_box, self.module_box = QComboBox(), QComboBox()
        for code, label in c.MODULE_LABELS.items():
            self.module_box.addItem(label, code)
        self.status_box = combo(_STATUS_FILTER)
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو در ردیف‌ها")
        for w in (self.run_box, self.module_box, self.status_box):
            w.currentIndexChanged.connect(lambda _i: self.reload())
        self.search.returnPressed.connect(self.reload)
        outer.addWidget(ms.header_card(_title("ورود و بارگذاری اطلاعات افتتاحیه"), QLabel("فرایند:"), self.run_box, QLabel("ماژول:"),
                                       self.module_box, QLabel("نمایش:"), self.status_box, self.search))
        cards, self.cards = ms.summary([("status", "وضعیت ماژول", "info", "📌"), ("total", "ردیف‌ها", "info", "🧮"),
                                        ("invalid", "دارای خطا", "danger", "⚠️"), ("amount", "جمع مبلغ", "success", "💰")])
        outer.addWidget(cards)
        self.hint = _hint("")
        outer.addWidget(self.hint)
        self.t = table([])
        self.t.cellDoubleClicked.connect(lambda _r, _c: self.edit_row())
        outer.addWidget(self.t, stretch=1)
        b = _btns(self, [
            ("tpl_x", "دریافت قالب اکسل", lambda: self.template(".xlsx")), ("tpl_c", "دریافت قالب متنی", lambda: self.template(".csv")),
            ("upload", "بارگذاری فایل", self.upload), ("add", "ردیف جدید", self.add_row), ("edit", "ویرایش ردیف", self.edit_row),
            ("delete", "حذف ردیف", self.delete_row), ("revalidate", "اعتبارسنجی دوباره", self.revalidate),
            ("export", "خروجی ردیف‌ها و خطاها", self.export), ("refresh", "به‌روزرسانی", self.refresh)])
        outer.addWidget(ms.footer([[b["tpl_x"], b["tpl_c"], b["upload"]], [b["add"], b["edit"], b["delete"], b["revalidate"]],
                                   [b["export"], b["refresh"]]]))
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        _runs_combo(self.run_box, cid, self.run_box.currentData())
        self.reload()

    def select(self, run_id: int, module_code: str | None = None) -> None:
        cid = company_id()
        _runs_combo(self.run_box, cid, run_id)
        if module_code:
            self.module_box.blockSignals(True)
            set_combo(self.module_box, module_code)
            self.module_box.blockSignals(False)
        self.reload()

    def _ctx(self):
        return company_id(), self.run_box.currentData(), self.module_box.currentData()

    def reload(self) -> None:
        cid, run_id, module = self._ctx()
        h = omod.handler(module)
        headers = ["ردیف فایل", "وضعیت"] + [col.label for col in h.columns] + ["مبلغ", "خطا", "هشدار"]
        self.t.setColumnCount(len(headers))
        self.t.setHorizontalHeaderLabels(headers)
        if cid is None or run_id is None:
            self.t.setRowCount(0)
            self._apply_buttons(None)
            return
        self.rows = oim.list_rows(cid, run_id, module, self.status_box.currentData(), self.search.text() or None)
        fill(self.t, [[r.row_no or "فرم", r.status_label] + [r.payload.get(col.key, "") for col in h.columns]
                      + [r.amount, r.problem_text, r.warning_text] for r in self.rows], [r.row_id for r in self.rows])
        for i, r in enumerate(self.rows):
            _tone(self.t, i, _ROW_TONE.get(r.status) or (_AMBER if r.warnings else None))
        run = orun.get_run(cid, run_id)
        m = next((x for x in run.modules if x.module_code == module), None)
        self.cards["status"].setText(m.status_label if m else "در این فرایند نیست")
        self.cards["total"].setText(P(m.total if m else 0))
        self.cards["invalid"].setText(P((m.invalid + m.failed) if m else 0))
        self.cards["amount"].setText(P(_money(m.amount if m else 0)))
        required = "، ".join(col.label for col in h.columns if col.required)
        self.hint.setText(P(f"{h.__doc__.strip() if h.__doc__ else ''} ستون‌های الزامی: {required}. کلید یکتای هر ردیف از همین ستون‌ها "
                            "ساخته می‌شود؛ بارگذاری دوباره ردیف هم‌کلید را به‌روز می‌کند و ردیف ثبت‌شده را دست نمی‌زند."))
        self._apply_buttons(m, run)

    def _apply_buttons(self, m, run=None) -> None:
        cid, uid = company_id(), user_id()
        can_enter = cid is not None and c.can(cid, uid, c.FORM_ENTER)
        editable = bool(m and run and run.status_code in orun.ENTRY_RUN and m.status_code not in orun.LOCKED_MODULE and can_enter)
        for key in ("upload", "add", "edit", "delete", "revalidate"):
            self.buttons[key].setEnabled(editable)

    def _pick_open(self) -> str | None:
        if self.open_file_picker is not None:
            return self.open_file_picker()
        path, _f = QFileDialog.getOpenFileName(self, "بارگذاری فایل", "", "اکسل یا متنی (*.xlsx *.csv)")
        return path or None

    def _pick_save(self, name: str, flt: str) -> str | None:
        if self.save_file_picker is not None:
            return self.save_file_picker(name)
        path, _f = QFileDialog.getSaveFileName(self, "ذخیره", name, flt)
        return path or None

    def template(self, ext: str) -> str | None:
        module = self.module_box.currentData()
        path = self._pick_save(f"قالب {c.MODULE_LABELS[module]}{ext}", "اکسل (*.xlsx)" if ext == ".xlsx" else "متنی (*.csv)")
        if not path:
            return None
        if not path.lower().endswith(ext):
            path += ext
        out, ok = _run(self, "قالب", oim.write_template, module, path)
        if ok:
            _done(self, f"قالب ذخیره شد: {os.path.basename(out)}")
        return out if ok else None

    def upload(self):
        cid, run_id, module = self._ctx()
        path = self._pick_open()
        if not path:
            return None
        replace = _confirm(self, "بارگذاری فایل", "ردیف‌های ثبت‌نشده‌ای که در این فایل نیستند حذف شوند؟ (خیر = فقط افزودن و به‌روزرسانی)")
        res, ok = _run(self, "بارگذاری فایل", oim.import_file, cid, user_id(), run_id, module, path, replace)
        if ok:
            parts = [f"نسخهٔ {res.version_no}: {res.row_count} ردیف، {res.valid} معتبر، {res.invalid} دارای خطا"]
            if res.duplicates:
                parts.append(f"{len(res.duplicates)} ردیف تکراری در فایل")
            if res.posted_skipped:
                parts.append(f"{len(res.posted_skipped)} ردیف ثبت‌شده دست نخورد")
            if res.removed:
                parts.append(f"{res.removed} ردیف قدیمی حذف شد")
            _done(self, "؛ ".join(parts + res.notes))
            self.reload()
        return res if ok else None

    def _row_fields(self, payload: dict | None = None) -> list:
        h = omod.handler(self.module_box.currentData())
        fields = []
        for col in h.columns:
            value = (payload or {}).get(col.key, "")
            if col.kind == "choice":
                box = combo([(k, k) for k in col.choices if not k.isascii()], "—")
                if value:
                    idx = box.findText(P(value))
                    box.setCurrentIndex(idx if idx >= 0 else 0)
                w = box
            else:
                w = QLineEdit(P(value) if value else "")
                if col.kind == "date":
                    w.setPlaceholderText("۱۴۰۳/۰۱/۱۵")
            fields.append((col.key, col.label + (" *" if col.required else ""), w))
        return fields

    def _save(self, row_id: int | None, payload: dict | None) -> bool:
        cid, run_id, module = self._ctx()
        v = _ask(self, "ویرایش ردیف" if row_id else "ردیف جدید", self._row_fields(payload),
                 omod.handler(module).__doc__ or "")
        if v is None:
            return False
        values = {k: ("" if val is None else val) for k, val in v.items()}
        res, ok = _run(self, "ذخیرهٔ ردیف", oim.save_row, cid, user_id(), run_id, module, values, row_id)
        if ok:
            msg = "ردیف ذخیره شد." if not res.errors else "ردیف با خطا ذخیره شد: " + "؛ ".join(f"{e['label']}: {e['msg']}" for e in res.errors)
            (_done if not res.errors else lambda s, t: theme.set_status_label(s.status_label, P(t), ok=False))(self, msg)
            self.reload()
        return ok

    def add_row(self) -> bool:
        return self._save(None, None)

    def edit_row(self) -> bool:
        row_id = _selected(self.t)
        row = next((r for r in self.rows if r.row_id == row_id), None)
        if row is None:
            return False
        return self._save(row.row_id, row.payload)

    def delete_row(self) -> bool:
        cid, run_id, module = self._ctx()
        row_id = _selected(self.t)
        if row_id is None or not _confirm(self, "حذف ردیف", "ردیف انتخاب‌شده حذف شود؟"):
            return False
        _r, ok = _run(self, "حذف ردیف", oim.delete_row, cid, user_id(), run_id, module, row_id)
        if ok:
            _done(self, "ردیف حذف شد.")
            self.reload()
        return ok

    def revalidate(self):
        cid, run_id, module = self._ctx()
        res, ok = _run(self, "اعتبارسنجی دوباره", oim.revalidate, cid, user_id(), run_id, module)
        if ok:
            _done(self, f"{res.valid} ردیف معتبر و {res.invalid} ردیف دارای خطا.")
            self.reload()
        return res if ok else None

    def export(self) -> str | None:
        cid, run_id, module = self._ctx()
        path = self._pick_save(f"ردیف‌های {c.MODULE_LABELS[module]}.xlsx", "اکسل (*.xlsx)")
        if not path:
            return None
        out, ok = _run(self, "خروجی", oim.export_rows, cid, run_id, module, path if path.endswith(".xlsx") else path + ".xlsx")
        if ok:
            _done(self, "ردیف‌ها با ستون خطا ذخیره شد؛ پس از اصلاح، همین فایل را دوباره بارگذاری کنید.")
        return out if ok else None


# =========================================================================================================
# تطبیق با تراز افتتاحیه
# =========================================================================================================
@ms.styled
class OpeningReconcileScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        self.run_box = QComboBox()
        self.run_box.currentIndexChanged.connect(lambda _i: self.reload())
        outer.addWidget(ms.header_card(_title("تطبیق زیرسیستم‌ها با تراز افتتاحیه"), QLabel("فرایند:"), self.run_box))
        cards, self.cards = ms.summary([("debit", "جمع بدهکار تراز", "info", "➕"), ("credit", "جمع بستانکار تراز", "info", "➖"),
                                        ("clearing", "ماندهٔ حساب واسط", "warning", "⚖️"), ("diffs", "حساب‌های دارای اختلاف", "danger", "⚠️")])
        outer.addWidget(cards)
        outer.addWidget(_hint("برای هر حساب کنترل: اختلاف = ماندهٔ تراز − جمع زیرسیستم (دریافتنی و پرداختنی به تفکیک طرف‌حساب). "
                              "ماندهٔ حساب واسط پس از ثبت همهٔ ماژول‌ها باید صفر شود."))
        self.problems = _hint("")
        outer.addWidget(self.problems)
        self.t = table(["ماژول", "حساب کنترل", "طرف‌حساب", "ماندهٔ تراز", "جمع زیرسیستم", "اختلاف", "منبع", "راه رفع"])
        outer.addWidget(self.t, stretch=1)
        b = _btns(self, [("refresh", "به‌روزرسانی", self.refresh), ("report", "گزارش کامل", self.open_report)])
        outer.addWidget(ms.footer([[b["refresh"], b["report"]]]))
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        _runs_combo(self.run_box, cid, self.run_box.currentData())
        self.reload()

    def select(self, run_id: int) -> None:
        _runs_combo(self.run_box, company_id(), run_id)
        self.reload()

    def reload(self) -> None:
        cid, run_id = company_id(), self.run_box.currentData()
        if cid is None or run_id is None:
            self.t.setRowCount(0)
            return
        rec = orec.report(cid, run_id)
        fill(self.t, [[x.module, x.account, x.counterparty or "—", x.tb, x.sub, x.difference, x.source, x.fix] for x in rec.rows])
        for i, x in enumerate(rec.rows):
            _tone(self.t, i, _RED if x.difference else _GREEN)
        self.cards["debit"].setText(P(_money(rec.tb_debit)))
        self.cards["credit"].setText(P(_money(rec.tb_credit)))
        self.cards["clearing"].setText(P(_money(rec.clearing_posted if rec.gl_posted else rec.projected_clearing)))
        self.cards["diffs"].setText(P(sum(1 for x in rec.rows if x.difference)))
        self.problems.setText(P("؛ ".join(rec.problems)) if rec.problems else "تطبیق کامل است؛ اختلافی نیست.")

    def open_report(self) -> None:
        if self._main_window is not None:
            self._main_window.open_screen("OPN_RPT_OPN_RECONCILE")


# =========================================================================================================
# تنظیمات افتتاحیه
# =========================================================================================================
@ms.styled
class OpeningSettingsScreen(FieldHelpMixin, QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.addWidget(_hint("طرف مقابل همهٔ ثبت‌های افتتاحیه «حساب واسط افتتاحیه» است و پس از ثبت همهٔ ماژول‌ها باید صفر شود. "
                              "سیاست اختلاف تعیین می‌کند اگر زیرسیستم‌ها با تراز نخوانند چه شود."))
        self.clearing = combo([], "—")
        self.policy = combo([(v, k) for k, v in c.POLICY_LABELS.items()])
        self.diff_account = combo([], "—")
        form = QWidget()
        fl = QVBoxLayout(form)
        fl.setContentsMargins(0, 0, 0, 0)
        for label, w in (("حساب واسط افتتاحیه:", self.clearing), ("سیاست اختلاف:", self.policy),
                         ("حساب اختلاف افتتاحیه:", self.diff_account)):
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.addWidget(QLabel(label))
            rl.addWidget(w, stretch=1)
            fl.addWidget(row)
        outer.addWidget(form)
        self.save_btn = QPushButton("ذخیرهٔ تنظیمات افتتاحیه")
        self.save_btn.clicked.connect(lambda _c=False: self.save())
        outer.addWidget(ms.footer([[self.save_btn]]))
        self.self_approval = QCheckBox("اجازهٔ تأیید اطلاعات توسط همان واردکننده")
        self.self_approval.toggled.connect(self._toggle)
        outer.addWidget(self.self_approval)
        outer.addWidget(_hint("پیش‌فرض خاموش: کسی که اطلاعات ماژول را ارسال کرده خودش آن را تأیید نمی‌کند (تفکیک وظایف)."))
        self.roles_btn = QPushButton("ساخت نقش‌های آمادهٔ افتتاحیه")
        self.roles_btn.clicked.connect(lambda _c=False: self.make_roles())
        outer.addWidget(_hint("نقش‌های آماده: کارشناس ورود اطلاعات، بررسی‌کننده و تأییدکننده، مدیر پروژهٔ افتتاحیه، مدیر مالی "
                              "(مجوز اختلاف و اصلاح) و ناظر."))
        outer.addWidget(ms.footer([[self.roles_btn]]))
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)
        outer.addStretch(1)
        self.set_field_help([
            (self.clearing, "حساب معین موقت (معمولاً زیر حقوق صاحبان سهام یا حساب‌های انتظامی) که فقط برای افتتاحیه به کار می‌رود."),
            (self.policy, "قفل نهایی فقط بدون اختلاف: سند تراز تا رفع اختلاف ثبت نمی‌شود. ادامه با مجوز: فقط کسی که دسترسی «مجوز قفل با "
                          "اختلاف» دارد، با نوشتن دلیل، اختلاف را به حساب اختلاف می‌برد."),
            (self.diff_account, "حساب صریحی که اختلاف تأییدشده به آن می‌رود؛ با حساب واسط یکی نباشد."),
            (self.save_btn, "تنظیمات را برای همهٔ فرایندهای این شرکت ذخیره می‌کند."),
        ])

    def refresh(self) -> None:
        from peecha.services import chart_of_accounts as coa

        cid, uid = company_id(), user_id()
        if cid is None:
            return
        accounts = [(f"{a.full_code} — {a.name}", a.account_id) for a in coa.list_accounts(cid) if a.is_postable]
        for box in (self.clearing, self.diff_account):
            box.blockSignals(True)
            box.clear()
            box.addItem("—", None)
            for label, data in accounts:
                box.addItem(P(label), data)
            box.blockSignals(False)
        s = c.settings(cid)
        set_combo(self.clearing, c.clearing_account_id(cid))
        set_combo(self.policy, s.difference_policy)
        set_combo(self.diff_account, s.difference_account_id)
        allowed = c.can(cid, uid, c.FORM_SETTINGS)
        for w in (self.clearing, self.policy, self.diff_account, self.save_btn, self.self_approval, self.roles_btn):
            w.setEnabled(allowed)
        self.self_approval.blockSignals(True)
        self.self_approval.setChecked(c.is_on(cid, c.OPN_SELF_APPROVAL))
        self.self_approval.blockSignals(False)

    def save(self) -> bool:
        _r, ok = _run(self, "تنظیمات افتتاحیه", c.save_settings, company_id(), user_id(), self.clearing.currentData(),
                      self.policy.currentData(), self.diff_account.currentData())
        if ok:
            _done(self, "تنظیمات افتتاحیه ذخیره شد.")
        return ok

    def _toggle(self, checked: bool) -> None:
        _r, ok = _run(self, "تنظیمات افتتاحیه", c.set_toggle, company_id(), user_id(), c.OPN_SELF_APPROVAL, checked)
        if not ok:
            self.self_approval.blockSignals(True)
            self.self_approval.setChecked(not checked)
            self.self_approval.blockSignals(False)

    def make_roles(self) -> dict | None:
        from peecha.services.opening import roles_setup

        roles, ok = _run(self, "نقش‌ها", roles_setup.ensure_role_templates, company_id())
        if ok:
            _done(self, f"{len(roles)} نقش آماده است.")
        return roles if ok else None
