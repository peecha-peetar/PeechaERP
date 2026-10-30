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
                "ردیف‌های جدید مثل افتتاحیهٔ اصلی ثبت می‌شوند، تراز این فرایند «تفاوت» است و سند باز اشتباه با «برگشت سند باز» "
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


# =========================================================================================================
# فرم سند افتتاحیه (R315): کدینگ حساب‌ها، مانده هر حساب، تفصیلی، کالا و اشخاص؛ بستن با حساب افتتاحیه
# =========================================================================================================
ms.ICONS.update({
    "سند افتتاحیهٔ جدید": ("🆕", "primary"), "ورود مانده": ("✏️", "primary"), "ثبت قطعی سند افتتاحیه": ("📌", "primary"),
    "مرکز افتتاحیه": ("🧭", ""), "ردیف دیگر همین کالا": ("➕", ""),
})
_SHEET_HINT = ("روی هر حساب معین دو بار بزنید (یا «ورود مانده»): مانده خود حساب، یا اگر تفصیلی دارد مانده هر تفصیلی؛ "
               "برای حساب موجودی کالا مقدار و مبلغ هر کالا؛ برای حساب مشتریان و تامین‌کنندگان مانده هر شخص. "
               "سند با «حساب افتتاحیه» بسته می‌شود: جمع بدهکار و بستانکار باید برابر باشد تا مانده آن صفر شود.")


def _plain_text(value) -> str:
    from peecha.services.opening import sheet as osh

    return P(osh._plain(value)) if value not in (None, "") and c.dec(value) else ""


def _cell(text, editable: bool = True, data=None) -> "QTableWidgetItem":
    from PySide6.QtWidgets import QTableWidgetItem

    item = QTableWidgetItem(P(text) if text not in (None, "") else "")
    if not editable:
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    if data is not None:
        item.setData(Qt.UserRole, data)
    return item


def _num(t, row: int, col: int):
    item = t.item(row, col)
    try:
        return c.parse_decimal(item.text() if item else "") or c.ZERO
    except ValueError:
        return None


class _GridDialog:
    """دیالوگ جدول قابل ویرایش با جستجو، «فقط دارای مانده» و جمع زنده؛ زیرکلاس‌ها ستون‌ها و خروجی را می‌دهند."""

    def __init__(self, title: str, hint: str, headers: list[str], parent=None, readonly: bool = False) -> None:
        from PySide6.QtWidgets import QAbstractItemView, QDialog, QDialogButtonBox, QTableWidget

        self.dlg = d = QDialog(parent)
        d.setWindowTitle(title)
        d.setLayoutDirection(Qt.RightToLeft)
        d.resize(1100, 640)
        self.readonly = readonly
        lay = QVBoxLayout(d)
        if hint:
            lay.addWidget(_hint(hint))
        self.top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجوی کد یا نام")
        self.only = QCheckBox("فقط دارای مانده")
        self.top.addWidget(self.search, stretch=1)
        self.top.addWidget(self.only)
        lay.addLayout(self.top)
        self.t = QTableWidget(0, len(headers))
        self.t.setHorizontalHeaderLabels(headers)
        self.t.verticalHeader().setVisible(False)
        self.t.horizontalHeader().setStretchLastSection(True)
        self.t.setEditTriggers(QAbstractItemView.NoEditTriggers if readonly else QAbstractItemView.AllEditTriggers)
        lay.addWidget(self.t, stretch=1)
        self.total = QLabel("")
        lay.addWidget(self.total)
        self.tools = QHBoxLayout()
        lay.addLayout(self.tools)
        self.box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.box.accepted.connect(d.accept)
        self.box.rejected.connect(d.reject)
        if readonly:
            self.box.button(QDialogButtonBox.Ok).setVisible(False)
        lay.addWidget(self.box)
        self.search.textChanged.connect(lambda _t: self.apply_filter())
        self.only.toggled.connect(lambda _b: self.apply_filter())
        self.t.itemChanged.connect(lambda _i: self.on_change())

    def tool(self, text: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.clicked.connect(lambda _c=False: slot())
        b.setEnabled(not self.readonly)
        ms.style_button(b)
        self.tools.addWidget(b)
        return b

    def has_amount(self, row: int) -> bool:
        return False

    def on_change(self) -> None:
        pass

    def apply_filter(self) -> None:
        needle = numerals.to_ascii_digits(self.search.text().strip()).lower()
        for r in range(self.t.rowCount()):
            text = " ".join(numerals.to_ascii_digits(self.t.item(r, col).text()).lower() for col in range(self.t.columnCount())
                            if self.t.item(r, col) is not None)
            hide = (needle and needle not in text) or (self.only.isChecked() and not self.has_amount(r))
            self.t.setRowHidden(r, bool(hide))

    def row_of(self, code: str, start: int = 0) -> int:
        """ردیف کد (برای آزمون و جستجو)؛ -۱ اگر نیست."""
        for r in range(start, self.t.rowCount()):
            data = self.t.item(r, 0).data(Qt.UserRole + 1)
            if data == code:
                return r
        return -1

    def set_text(self, row: int, col: int, text) -> None:
        self.t.item(row, col).setText(P(text))


class _LinesDialog(_GridDialog):
    """مانده یک حساب: یک ردیف برای حساب بدون تفصیلی، یا یک ردیف برای هر تفصیلی (مثلاً همهٔ اشخاص یا مراکز هزینهٔ مجاز)."""

    def __init__(self, detail, parent=None, readonly: bool = False) -> None:
        self.detail = detail
        self.dims = list(detail.dims)
        heads = [d.label for d in self.dims] or ["مانده حساب"]
        self.amount_col = len(heads)
        super().__init__(f"مانده {detail.label}", "مانده بدهکار یا بستانکار هر ردیف را وارد کنید؛ ردیف بی‌مبلغ ذخیره نمی‌شود."
                         + (" تفصیلی‌های دیگر را با کد وارد کنید." if len(self.dims) > 1 else ""),
                         heads + ["بدهکار", "بستانکار", "ارز", "نرخ تبدیل", "شرح", "ایراد"], parent, readonly)
        self.tool("افزودن ردیف", self.add_line)
        names = dict(detail.candidates)
        rows = []
        used = set()
        for ln in detail.lines:
            primary = ln.details.get(self.dims[0].field, "") if self.dims else ""
            used.add(primary)
            rows.append((ln.row_id, primary, ln))
        for code, _name in detail.candidates:
            if code not in used:
                rows.append((None, code, None))
        if not self.dims and not rows:
            rows.append((None, "", None))
        self.t.blockSignals(True)
        for row_id, primary, ln in rows:
            self._append(row_id, primary, names.get(primary, ""), ln)
        self.t.blockSignals(False)
        self.on_change()

    def _append(self, row_id, primary: str, name: str, ln=None) -> int:
        r = self.t.rowCount()
        self.t.insertRow(r)
        locked = bool(ln and ln.posted)
        if self.dims:
            label = f"{primary} — {name}" if name else primary
            first = _cell(label, editable=not primary, data=row_id)
            first.setData(Qt.UserRole + 1, primary)
            self.t.setItem(r, 0, first)
            for i, d in enumerate(self.dims[1:], start=1):
                self.t.setItem(r, i, _cell((ln.details.get(d.field, "") if ln else ""), not locked))
        else:
            first = _cell("مانده", editable=False, data=row_id)
            first.setData(Qt.UserRole + 1, "")
            self.t.setItem(r, 0, first)
        a = self.amount_col
        self.t.setItem(r, a, _cell(_plain_text(ln.debit) if ln else "", not locked))
        self.t.setItem(r, a + 1, _cell(_plain_text(ln.credit) if ln else "", not locked))
        self.t.setItem(r, a + 2, _cell(ln.currency_code if ln else "", not locked))
        self.t.setItem(r, a + 3, _cell(ln.exchange_rate if ln else "", not locked))
        self.t.setItem(r, a + 4, _cell(ln.description if ln else "", not locked))
        problem = _cell(ln.problem if ln else "", editable=False)
        if ln and ln.problem:
            problem.setForeground(_RED)
        self.t.setItem(r, a + 5, problem)
        return r

    def add_line(self) -> int:
        self.t.blockSignals(True)
        r = self._append(None, "", "")
        self.t.blockSignals(False)
        self.t.scrollToBottom()
        return r

    def has_amount(self, row: int) -> bool:
        return bool(_num(self.t, row, self.amount_col) or _num(self.t, row, self.amount_col + 1))

    def on_change(self) -> None:
        d = cr = c.ZERO
        for r in range(self.t.rowCount()):
            d += _num(self.t, r, self.amount_col) or c.ZERO
            cr += _num(self.t, r, self.amount_col + 1) or c.ZERO
        self.total.setText(P(f"جمع بدهکار {_money(d)} — جمع بستانکار {_money(cr)}"))

    def lines(self) -> list[dict]:
        out = []
        a = self.amount_col
        for r in range(self.t.rowCount()):
            first = self.t.item(r, 0)
            row_id = first.data(Qt.UserRole)
            debit, credit = _num(self.t, r, a), _num(self.t, r, a + 1)
            if debit is None or credit is None:
                raise ValueError(f"مبلغ ردیف {P(r + 1)} عدد نیست.")
            if not row_id and not debit and not credit:
                continue
            details = {}
            if self.dims:
                code = first.data(Qt.UserRole + 1) or numerals.to_ascii_digits(first.text().split(" — ")[0].strip())
                details[self.dims[0].field] = code
                for i, dm in enumerate(self.dims[1:], start=1):
                    value = numerals.to_ascii_digits(self.t.item(r, i).text().strip())
                    if value:
                        details[dm.field] = value
            out.append({"row_id": row_id, "details": details, "debit": debit, "credit": credit,
                        "currency_code": self.t.item(r, a + 2).text().strip().upper(),
                        "exchange_rate": numerals.to_ascii_digits(self.t.item(r, a + 3).text().strip()),
                        "description": self.t.item(r, a + 4).text().strip()})
        return out


_ITEM_COLS = [("item_code", "کد کالا"), ("item_name", "نام کالا"), ("quantity", "مقدار"), ("amount", "مبلغ کل"),
              ("unit", "بهای واحد"), ("uom_code", "واحد"), ("bin_code", "کد محل"), ("batch_no", "شمارهٔ بچ"),
              ("serial_no", "شمارهٔ سریال"), ("expiry_date", "تاریخ انقضا"), ("manufacture_date", "تاریخ تولید"),
              ("quality_status", "وضعیت کیفیت"), ("currency_code", "ارز بها"), ("exchange_rate", "نرخ تبدیل"),
              ("description", "شرح"), ("problem", "ایراد")]
_ICOL = {k: i for i, (k, _l) in enumerate(_ITEM_COLS)}


class _ItemsDialog(_GridDialog):
    """کالاهای یک انبار: مقدار و مبلغ کل (بهای واحد خودکار) و فیلدهای ردیابی؛ تغییر انبار، انبار قبلی را ذخیره می‌کند."""

    def __init__(self, warehouses: list, load, save, parent=None, readonly: bool = False) -> None:
        super().__init__("موجودی اول دوره کالاها", "برای هر کالا مقدار و مبلغ کل اول دوره را وارد کنید. کالای بچ‌دار، "
                         "انقضادار یا سریالی شمارهٔ بچ/تاریخ انقضا/سریال لازم دارد؛ برای چند بچ یا سریال «ردیف دیگر همین کالا».",
                         [label for _k, label in _ITEM_COLS], parent, readonly)
        self.load_cb, self.save_cb = load, save
        self.saved_results: list = []
        self.wh = combo([(f"{w.code} — {w.name}", w.code) for w in warehouses])
        self.top.insertWidget(0, QLabel("انبار:"))
        self.top.insertWidget(1, self.wh)
        self.tool("ردیف دیگر همین کالا", self.add_same_item)
        self._wh_code = self.wh.currentData()
        self.dirty = False
        self.wh.currentIndexChanged.connect(lambda _i: self.switch_warehouse())
        self.reload()

    def reload(self) -> None:
        detail = self.load_cb(self._wh_code) if self._wh_code else None
        self.t.blockSignals(True)
        self.t.setRowCount(0)
        for ln in (detail.lines if detail else []):
            self._append(ln)
        self.t.blockSignals(False)
        self.on_change()
        self.dirty = False
        self.apply_filter()

    def _append(self, ln, row: int | None = None) -> int:
        r = self.t.rowCount() if row is None else row
        self.t.insertRow(r)
        locked = bool(getattr(ln, "posted", False))
        p = getattr(ln, "payload", {}) or {}
        values = {"item_code": ln.item_code, "item_name": ln.item_name, "quantity": _plain_text(ln.quantity),
                  "amount": _plain_text(ln.amount), "unit": "", "uom_code": p.get("uom_code") or "", "problem": ln.problem or ""}
        for key in ("bin_code", "batch_no", "serial_no", "expiry_date", "manufacture_date", "quality_status", "currency_code",
                    "exchange_rate", "description"):
            values[key] = p.get(key) or ""
        for key, col in _ICOL.items():
            editable = not locked and key not in ("item_code", "item_name", "unit", "problem")
            item = _cell(values[key], editable, data=ln.row_id if col == 0 else None)
            if col == 0:
                item.setData(Qt.UserRole + 1, ln.item_code)
                item.setData(Qt.UserRole + 2, ln.item_name)
            if key == "problem" and ln.problem:
                item.setForeground(_RED)
            self.t.setItem(r, col, item)
        self._unit(r)
        return r

    def _unit(self, r: int) -> None:
        qty, amount = _num(self.t, r, _ICOL["quantity"]), _num(self.t, r, _ICOL["amount"])
        text = _money(amount / qty) if qty and amount is not None and self.t.item(r, _ICOL["amount"]).text().strip() else ""
        self.t.blockSignals(True)
        self.t.item(r, _ICOL["unit"]).setText(P(text))
        self.t.blockSignals(False)

    def add_same_item(self) -> int:
        r = self.t.currentRow()
        if r < 0:
            return -1
        first = self.t.item(r, 0)
        from types import SimpleNamespace

        ln = SimpleNamespace(row_id=None, item_code=first.data(Qt.UserRole + 1), item_name=first.data(Qt.UserRole + 2), quantity=None,
                             amount=None, payload={}, problem="", posted=False)
        self.t.blockSignals(True)
        new = self._append(ln, r + 1)
        self.t.blockSignals(False)
        return new

    def has_amount(self, row: int) -> bool:
        return bool(_num(self.t, row, _ICOL["quantity"]))

    def on_change(self) -> None:
        self.dirty = True
        total, count = c.ZERO, 0
        for r in range(self.t.rowCount()):
            if self.t.item(r, _ICOL["unit"]) is not None:
                self._unit(r)
            if _num(self.t, r, _ICOL["quantity"]):
                total += _num(self.t, r, _ICOL["amount"]) or c.ZERO
                count += 1
        self.total.setText(P(f"{count} ردیف کالا — جمع مبلغ {_money(total)}"))

    def lines(self) -> list[dict]:
        out = []
        for r in range(self.t.rowCount()):
            first = self.t.item(r, 0)
            qty, amount = _num(self.t, r, _ICOL["quantity"]), _num(self.t, r, _ICOL["amount"])
            if qty is None or amount is None:
                raise ValueError(f"مقدار یا مبلغ ردیف {P(r + 1)} عدد نیست.")
            if not first.data(Qt.UserRole) and not qty:
                continue
            line = {"row_id": first.data(Qt.UserRole), "item_code": first.data(Qt.UserRole + 1), "quantity": qty,
                    "amount": amount if self.t.item(r, _ICOL["amount"]).text().strip() else None}
            for key in ("uom_code", "bin_code", "batch_no", "serial_no", "expiry_date", "manufacture_date", "quality_status",
                        "currency_code", "exchange_rate", "description"):
                line[key] = self.t.item(r, _ICOL[key]).text().strip()
            out.append(line)
        return out

    def switch_warehouse(self) -> None:
        if self.dirty and not self.readonly and self._wh_code:
            self.saved_results.append(self.save_cb(self._wh_code, self.lines()))
        self._wh_code = self.wh.currentData()
        self.reload()


class _PartiesDialog(_GridDialog):
    """مانده هر شخص حساب مشتریان/تامین‌کنندگان؛ مانده هم‌جهت سند باز افتتاحیه می‌شود و خلاف جهت پیش‌دریافت/پیش‌پرداخت."""

    def __init__(self, detail, title: str, parent=None, readonly: bool = False) -> None:
        kind = "مشتری" if detail.receivable else "تامین‌کننده"
        side = "بدهکار" if detail.receivable else "بستانکار"
        super().__init__(title, f"مانده هر {kind} را وارد کنید. مانده {side} یک سند باز افتتاحیه می‌شود که در تسویه و گزارش سنی "
                         f"دیده می‌شود (سررسید اختیاری)؛ مانده خلاف آن {'پیش‌دریافت' if detail.receivable else 'پیش‌پرداخت'} ثبت می‌شود.",
                         ["کد", "نام", "بدهکار", "بستانکار", "سررسید", "سایر اسناد باز", "ایراد"], parent, readonly)
        self.t.blockSignals(True)
        for ln in detail.lines:
            r = self.t.rowCount()
            self.t.insertRow(r)
            first = _cell(ln.person_code, False, data=ln.row_id)
            first.setData(Qt.UserRole + 1, ln.person_code)
            self.t.setItem(r, 0, first)
            self.t.setItem(r, 1, _cell(ln.name, False))
            self.t.setItem(r, 2, _cell(_plain_text(ln.debit), not ln.posted))
            self.t.setItem(r, 3, _cell(_plain_text(ln.credit), not ln.posted))
            self.t.setItem(r, 4, _cell(ln.due_date, not ln.posted))
            other = f"{_money(ln.other_amount)} ({P(ln.other_count)} سند)" if ln.other_count else ""
            self.t.setItem(r, 5, _cell(other, False))
            problem = _cell(ln.problem, False)
            if ln.problem:
                problem.setForeground(_RED)
            self.t.setItem(r, 6, problem)
        self.t.blockSignals(False)
        self.on_change()

    def has_amount(self, row: int) -> bool:
        return bool(_num(self.t, row, 2) or _num(self.t, row, 3) or self.t.item(row, 5).text())

    def on_change(self) -> None:
        d = cr = c.ZERO
        for r in range(self.t.rowCount()):
            d += _num(self.t, r, 2) or c.ZERO
            cr += _num(self.t, r, 3) or c.ZERO
        self.total.setText(P(f"جمع بدهکار {_money(d)} — جمع بستانکار {_money(cr)}"))

    def lines(self) -> list[dict]:
        out = []
        for r in range(self.t.rowCount()):
            first = self.t.item(r, 0)
            debit, credit = _num(self.t, r, 2), _num(self.t, r, 3)
            if debit is None or credit is None:
                raise ValueError(f"مبلغ ردیف {P(r + 1)} عدد نیست.")
            if not first.data(Qt.UserRole) and not debit and not credit:
                continue
            out.append({"row_id": first.data(Qt.UserRole), "person_code": first.data(Qt.UserRole + 1), "debit": debit,
                        "credit": credit, "due_date": self.t.item(r, 4).text().strip()})
        return out


@ms.styled
class OpeningSheetScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        from PySide6.QtWidgets import QTreeWidget

        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.confirm = None
        self.sheet = None
        self._rows: dict[int, object] = {}
        self._items: dict[int, object] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        self.run_box = QComboBox()
        self.run_box.currentIndexChanged.connect(lambda _i: self.reload())
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجوی کد یا نام حساب")
        self.search.textChanged.connect(lambda _t: self.apply_filter())
        self.only = QCheckBox("فقط حساب‌های دارای مانده")
        self.only.toggled.connect(lambda _b: self.apply_filter())
        outer.addWidget(ms.header_card(_title("سند افتتاحیه"), QLabel("فرایند:"), self.run_box, self.search, self.only))
        cards, self.cards = ms.summary([("debit", "جمع بدهکار", "info", "➕"), ("credit", "جمع بستانکار", "info", "➖"),
                                        ("closing", "حساب افتتاحیه", "success", "⚖️"), ("status", "وضعیت", "info", "📌")])
        outer.addWidget(cards)
        self.hint = _hint(_SHEET_HINT)
        outer.addWidget(self.hint)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["کد حساب", "نام حساب", "نحوهٔ ورود", "بدهکار", "بستانکار", "وضعیت"])
        self.tree.setColumnWidth(0, 150)
        self.tree.setColumnWidth(1, 260)
        self.tree.setColumnWidth(2, 220)
        self.tree.itemDoubleClicked.connect(lambda _i, _c: self.edit_account())
        outer.addWidget(self.tree, stretch=1)
        b = _btns(self, [
            ("new", "سند افتتاحیهٔ جدید", self.new_run), ("edit", "ورود مانده", self.edit_account),
            ("submit", "ارسال برای بررسی", self.submit), ("approve", "تأیید اطلاعات", self.approve),
            ("reject", "رد اطلاعات", self.reject), ("post", "ثبت قطعی سند افتتاحیه", self.post), ("lock", "قفل نهایی", self.lock),
            ("reconcile", "تطبیق با تراز", self.open_reconcile), ("hub", "مرکز افتتاحیه", self.open_hub),
            ("refresh", "به‌روزرسانی", self.refresh)])
        outer.addWidget(ms.footer([[b["new"], b["edit"]], [b["submit"], b["approve"], b["reject"]], [b["post"], b["lock"]],
                                   [b["reconcile"], b["hub"], b["refresh"]]]))
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)

    # --- بارگذاری ---------------------------------------------------------------------------------------
    def refresh(self) -> None:
        from peecha.services.opening import sheet as osh

        cid = company_id()
        if cid is None:
            return
        keep = self.run_box.currentData() or osh.default_run(cid)
        _runs_combo(self.run_box, cid, keep)
        self.reload()

    def select_run(self, run_id: int) -> None:
        _runs_combo(self.run_box, company_id(), run_id)
        self.reload()

    def reload(self) -> None:
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QTreeWidgetItem
        from peecha.services.opening import sheet as osh

        cid, uid, run_id = company_id(), user_id(), self.run_box.currentData()
        self.tree.clear()
        self._rows, self._items = {}, {}
        if cid is None or run_id is None:
            self.sheet = None
            for card in self.cards.values():
                card.setText("—")
            self.hint.setText(_SHEET_HINT + " برای شروع «سند افتتاحیهٔ جدید» را بزنید.")
            self._apply_buttons()
            return
        warning = None
        if c.can(cid, uid, c.FORM_ENTER):
            try:
                osh.sync_control_rows(cid, uid, run_id)
            except ValueError as exc:
                warning = str(exc)
        self.sheet = sh = osh.sheet(cid, run_id)
        bold = QFont()
        bold.setBold(True)
        for row in sh.rows:
            item = QTreeWidgetItem([P(row.code), row.name, row.kind_label, _money(row.debit) if row.debit else "",
                                    _money(row.credit) if row.credit else "",
                                    P(f"{row.problems} ایراد") if row.problems else ("" if not row.lines else P(f"{row.lines} ردیف"))])
            item.setData(0, Qt.UserRole, row.account_id)
            for col in (3, 4):
                item.setTextAlignment(col, Qt.AlignLeft | Qt.AlignVCenter)
            if not row.postable:
                for col in range(6):
                    item.setFont(col, bold)
            if row.problems:
                for col in range(6):
                    item.setForeground(col, _RED)
            elif row.kind == "CLEARING":
                for col in range(6):
                    item.setForeground(col, _GREEN if sh.closed else _AMBER)
            parent = self._items.get(row.parent_id)
            (parent.addChild(item) if parent is not None else self.tree.addTopLevelItem(item))
            self._items[row.account_id], self._rows[row.account_id] = item, row
        self.tree.expandAll()
        self.cards["debit"].setText(P(_money(sh.debit)))
        self.cards["credit"].setText(P(_money(sh.credit)))
        if sh.closed:
            self.cards["closing"].setText("صفر؛ سند بسته است")
        else:
            side = "بستانکار" if sh.difference > 0 else "بدهکار"
            self.cards["closing"].setText(P(f"{_money(abs(sh.difference))} {side}؛ سند بسته نیست"))
        self.cards["status"].setText(sh.run.status_label)
        head = (f"{sh.run.code} — {sh.run.title} | مانده‌ها تا {numerals.format_jalali_date(sh.run.balance_date)} | "
                f"تاریخ سند {numerals.format_jalali_date(sh.run.go_live_date)} | حساب افتتاحیه: {sh.clearing or 'تعیین نشده'}")
        notes = sh.problems + ([warning] if warning else [])
        self.hint.setText(P(head + "\n" + _SHEET_HINT + ("\n" + "؛ ".join(notes) if notes else "")))
        self.apply_filter()
        self._apply_buttons()

    def apply_filter(self) -> None:
        needle = numerals.to_ascii_digits(self.search.text().strip()).lower()
        only = self.only.isChecked()

        def visit(item) -> bool:
            row = self._rows.get(item.data(0, Qt.UserRole))
            child_visible = False
            for i in range(item.childCount()):
                child_visible = visit(item.child(i)) or child_visible
            text = numerals.to_ascii_digits(f"{row.code} {row.name}").lower() if row else ""
            match = (not needle or needle in text) and (not only or bool(row and (row.debit or row.credit)))
            show = match or child_visible
            item.setHidden(not show)
            return show
        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))

    def _apply_buttons(self) -> None:
        cid, uid = company_id(), user_id()
        sh = self.sheet
        can = (lambda form: cid is not None and c.can(cid, uid, form))  # noqa: E731
        st = sh.run.status_code if sh else ""
        mods = sh.modules if sh else {}
        self.buttons["new"].setEnabled(can(c.FORM_SETUP))
        self.buttons["edit"].setEnabled(bool(sh))
        self.buttons["submit"].setEnabled(st in orun.ENTRY_RUN and can(c.FORM_ENTER) and "ENTERING" in mods.values())
        for key in ("approve", "reject"):
            self.buttons[key].setEnabled(st in orun.ENTRY_RUN and can(c.FORM_APPROVE)
                                         and any(s in ("READY", "APPROVED") for s in mods.values()))
        self.buttons["post"].setEnabled(st in ("IN_PROGRESS", "POSTING") and can(c.FORM_POST)
                                        and any(s in ("APPROVED", "POSTING") for s in mods.values()))
        self.buttons["lock"].setEnabled(st == "POSTED" and can(c.FORM_POST))
        self.buttons["reconcile"].setEnabled(bool(sh))
        self.buttons["hub"].setEnabled(bool(sh))

    def select_account(self, code: str) -> bool:
        """انتخاب حساب با کد کامل یا آخرین بخش کد (برای جستجو و آزمون)."""
        for acc_id, row in self._rows.items():
            if row.code == code or row.code.split("-")[-1] == code:
                self.tree.setCurrentItem(self._items[acc_id])
                return True
        return False

    def _selected(self):
        item = self.tree.currentItem()
        return self._rows.get(item.data(0, Qt.UserRole)) if item is not None else None

    # --- ورود مانده ---------------------------------------------------------------------------------------
    def _exec(self, dlg) -> bool:
        from PySide6.QtWidgets import QDialog

        ms.apply(dlg.dlg)
        return bool(self.dialog_runner(dlg)) if self.dialog_runner is not None else dlg.dlg.exec() == QDialog.Accepted

    def _saved(self, res) -> None:
        results = res if isinstance(res, list) else [res]
        bad = sum(r.invalid for r in results)
        saved = sum(len(r.saved) for r in results)
        if bad:
            theme.set_status_label(self.status_label, P(f"{saved} ردیف ذخیره شد؛ {bad} ردیف ایراد دارد (ستون «ایراد»)."), ok=False)
        else:
            _done(self, f"{saved} ردیف ذخیره شد.")

    def edit_account(self) -> bool:
        from peecha.services.opening import sheet as osh

        row, sh = self._selected(), self.sheet
        if sh is None:
            _warn(self, "ورود مانده", "ابتدا سند افتتاحیه را بسازید یا انتخاب کنید.")
            return False
        if row is None:
            _warn(self, "ورود مانده", "یک حساب را انتخاب کنید.")
            return False
        if not row.postable:
            _warn(self, "ورود مانده", "مانده فقط روی حساب معین وارد می‌شود؛ زیرمجموعهٔ این گروه را انتخاب کنید.")
            return False
        if row.kind == "CLEARING":
            _warn(self, "ورود مانده", "حساب افتتاحیه خودکار بسته می‌شود؛ مانده آن جمع بدهکار منهای جمع بستانکار است و باید صفر شود.")
            return False
        cid, uid, run_id = company_id(), user_id(), sh.run.run_id
        readonly = not row.editable or not c.can(cid, uid, c.FORM_ENTER)
        if row.kind in ("CHEQUES", "FIXED_ASSETS", "WIP"):
            if self._main_window is not None:
                self._main_window.open_screen("OPN_DATA", then=lambda s: s.select(run_id, row.kind))
            _done(self, f"ریز «{c.MODULE_LABELS[row.kind]}» در صفحهٔ ورود اطلاعات وارد می‌شود؛ مانده این حساب از همان ساخته می‌شود.")
            return True
        if row.kind == "INVENTORY":
            dlg = _ItemsDialog(osh.warehouses(cid), lambda wh: osh.inventory_detail(cid, run_id, wh),
                               lambda wh, lines: osh.save_inventory(cid, uid, run_id, wh, lines), self, readonly)
            ok = self._exec(dlg)
            results = list(dlg.saved_results)
            if ok and not readonly:
                res, done = _run(self, "موجودی کالا", lambda: osh.save_inventory(cid, uid, run_id, dlg._wh_code, dlg.lines()))
                if done:
                    results.append(res)
            if results:
                self._saved(results)
                self.reload()
            return ok
        if row.kind in ("RECEIVABLES", "PAYABLES"):
            detail = osh.party_detail(cid, run_id, row.kind)
            dlg = _PartiesDialog(detail, f"مانده اشخاص — {row.code} {row.name}", self, readonly)
            if not self._exec(dlg) or readonly:
                return False
            res, ok = _run(self, "مانده اشخاص", lambda: osh.save_parties(cid, uid, run_id, row.kind, dlg.lines()))
        else:
            detail = osh.account_detail(cid, run_id, row.account_id)
            dlg = _LinesDialog(detail, self, readonly)
            if not self._exec(dlg) or readonly:
                return False
            res, ok = _run(self, "مانده حساب", lambda: osh.save_account_detail(cid, uid, run_id, row.account_id, dlg.lines()))
        if ok:
            self._saved(res)
            self.reload()
        return ok

    # --- فرایند و گردش ----------------------------------------------------------------------------------
    def new_run(self) -> int | None:
        from peecha.services import fiscal_years
        from peecha.services.opening import sheet as osh

        cid = company_id()
        fys = combo([(f.code, f.fiscal_year_id) for f in fiscal_years.list_fiscal_years(cid)])
        balance, go_live = JalaliDateEdit(), JalaliDateEdit()
        v = _ask(self, "سند افتتاحیهٔ جدید", [("fy", "سال مالی", fys), ("balance", "تاریخ مانده‌ها (روز برش در سیستم قبلی)", balance),
                                             ("go_live", "شروع کار با سیستم (تاریخ سند)", go_live), ("title", "عنوان (اختیاری)", QLineEdit())],
                 "تاریخ سند افتتاحیه همان «شروع کار با سیستم» است و باید در سال مالی باشد. برای هر سال مالی یک سند افتتاحیه ساخته می‌شود؛ "
                 "تغییر بعد از قفل فقط با افتتاحیهٔ اصلاحی است.")
        if v is None:
            return None
        rid, ok = _run(self, "سند افتتاحیهٔ جدید", osh.create_run, cid, user_id(), v["fy"], v["balance"], v["go_live"], v["title"])
        if ok:
            _done(self, "سند افتتاحیه ساخته شد؛ مانده حساب‌ها را وارد کنید.")
            self.select_run(rid)
        return rid if ok else None

    def _flow(self, title: str, fn, *extra) -> bool:
        res, ok = _run(self, title, fn, company_id(), user_id(), self.sheet.run.run_id, *extra)
        if ok:
            text = f"{title}: " + "، ".join(res.done)
            if res.problems:
                text += " | " + "؛ ".join(res.problems)
            (_done if not res.problems else lambda s, t: theme.set_status_label(s.status_label, P(t), ok=False))(self, text)
            self.reload()
        return ok

    def submit(self) -> bool:
        from peecha.services.opening import sheet as osh

        if self.sheet is None:
            return False
        if not self.sheet.closed and not _confirm(self, "ارسال برای بررسی", P(
                f"سند هنوز بسته نیست (حساب افتتاحیه {_money(abs(self.sheet.difference))}). با این حال برای بررسی ارسال شود؟")):
            return False
        return self._flow("ارسال برای بررسی", osh.submit_all, None)

    def approve(self) -> bool:
        from peecha.services.opening import sheet as osh

        return self.sheet is not None and self._flow("تأیید اطلاعات", osh.approve_all, None)

    def reject(self) -> bool:
        from peecha.services.opening import sheet as osh

        if self.sheet is None:
            return False
        v = _ask(self, "رد اطلاعات", [("reason", "دلیل رد", _text())])
        return v is not None and self._flow("رد اطلاعات", osh.reject_all, v["reason"] or "")

    def post(self) -> bool:
        from peecha.services.opening import sheet as osh

        sh = self.sheet
        if sh is None:
            return False
        reason = None
        rec = orec.report(company_id(), sh.run.run_id)
        if rec.projected_clearing and c.settings(company_id()).difference_policy == "APPROVAL":
            v = _ask(self, "ثبت با اختلاف", [("reason", "دلیل ثبت با اختلاف", _text())],
                     P(f"جزئیات زیرسیستم‌ها با حساب‌های کنترل {_money(rec.projected_clearing)} اختلاف دارد؛ این مبلغ به «حساب اختلاف "
                       "افتتاحیه» می‌رود و با نام شما ثبت می‌شود."))
            if v is None:
                return False
            reason = v["reason"]
        elif not _confirm(self, "ثبت قطعی", "سند افتتاحیه با اسناد رسمی هر بخش ثبت شود؟ پس از ثبت، تغییر فقط با افتتاحیهٔ اصلاحی است."):
            return False
        res, ok = _run(self, "ثبت قطعی", osh.post_all, company_id(), user_id(), sh.run.run_id, reason)
        if ok:
            if res.failed:
                _warn(self, "ثبت قطعی", P("بخشی از ثبت انجام نشد؛ پس از رفع، دوباره «ثبت قطعی» بزنید تا از همان‌جا ادامه دهد:\n"
                                          + "\n".join(res.failed[:5])))
            else:
                _done(self, "سند افتتاحیه ثبت قطعی شد: " + "، ".join(res.posted))
            self.reload()
        return ok

    def lock(self) -> bool:
        sh = self.sheet
        if sh is None or not _confirm(self, "قفل نهایی", "همهٔ اسناد افتتاحیه دائم می‌شوند و سند قفل می‌شود. ادامه می‌دهید؟"):
            return False
        res, ok = _run(self, "قفل نهایی", ofin.lock_run, company_id(), user_id(), sh.run.run_id)
        if ok:
            _done(self, f"سند افتتاحیه قفل شد؛ {res.approved_now} سند حسابداری دائم شد.")
            self.reload()
        return ok

    def open_reconcile(self) -> None:
        sh = self.sheet
        if self._main_window is not None and sh is not None:
            self._main_window.open_screen("OPN_RECONCILE", then=lambda s: s.select(sh.run.run_id))

    def open_hub(self) -> None:
        sh = self.sheet
        if self._main_window is not None and sh is not None:
            self._main_window.open_screen("OPN_CENTER", then=lambda s: s.open_run(sh.run.run_id))
