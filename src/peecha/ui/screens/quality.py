"""صفحه‌های کنترل کیفیت — R311.

صف بازرسی و تأیید، فرم ثبت نتیجه با پارامترهای طرح، قرنطینه، عدم‌انطباق، اقدام اصلاحی، طرح‌های کیفیت، کارت کیفیت و
داشبورد. همهٔ منطق در services/quality_control.py و services/qms است؛ اینجا فقط نمایش و فراخوانی.
"""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit,
    QVBoxLayout, QWidget,
)

from peecha import decimals, numerals
from peecha.services import quality_control as qc
from peecha.services import stock_controls
from peecha.services.qms import common as c
from peecha.services.qms import ncr as ncr_service
from peecha.services.qms import plans as plan_service
from peecha.services.qms import queries
from peecha.ui import theme
from peecha.ui.screens import module_style as ms
from peecha.ui.screens.costing import can
from peecha.ui.screens.fixed_assets import (
    FormDialog, P, combo, company_id, date_field, dec, fill, num_field, scrolled, set_combo, table, user_id,
)
from peecha.ui.widgets import FieldHelpMixin, JalaliDateEdit

ms.ICONS.update({
    "تأیید نهایی": ("🛡️", "primary"), "لغو نتیجه": ("🚫", "danger"), "ریز بازرسی": ("🧾", ""),
    "ثبت نتیجهٔ حین تولید": ("🏭", ""), "آزادسازی از قرنطینه": ("🔓", "primary"), "برگشت به تامین‌کننده": ("↩️", ""),
    "عدم‌انطباق جدید": ("⚠️", "primary"), "ویرایش پرونده": ("✏️", ""), "شروع بررسی": ("🔍", ""), "در حال اقدام": ("🛠️", ""),
    "بستن پرونده": ("🔒", ""), "لغو پرونده": ("🚫", "danger"), "اقدام جدید": ("➕", ""), "ثبت انجام اقدام": ("✅", ""),
    "بررسی اثربخشی": ("🎯", "primary"), "لغو اقدام": ("🗑️", "danger"), "پروندهٔ عدم‌انطباق": ("📂", ""),
    "طرح جدید": ("🆕", "primary"), "ویرایش طرح": ("✏️", ""), "فعال‌سازی طرح": ("▶️", ""), "غیرفعال‌سازی طرح": ("⏸️", "danger"),
    "افزودن پارامتر": ("➕", ""), "حذف پارامتر": ("🗑️", "danger"), "گزارش کامل": ("📄", ""),
    "ذخیرهٔ تنظیمات کیفیت": ("💾", "primary"),
})

_ZERO = decimal.Decimal(0)
_RED, _AMBER, _GREEN = QColor("#EF4444"), QColor("#F59E0B"), QColor("#10B981")
_SEVERITY_TONE = {"CRITICAL": _RED, "MAJOR": _AMBER}


# --- کمکی‌ها ---------------------------------------------------------------------------------------
def _warn(parent, title: str, text: str) -> None:
    hook = getattr(parent, "warn", None)
    if hook is not None:
        hook(text)
        return
    QMessageBox.warning(parent, title, text)


def _run(parent, title: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs), True
    except ValueError as exc:
        _warn(parent, title, str(exc))
        return None, False


def _exec(parent, dlg: QDialog) -> bool:
    runner = getattr(parent, "dialog_runner", None)
    return bool(runner(dlg)) if runner is not None else dlg.exec() == QDialog.Accepted


def _ask(parent, title: str, fields, hint: str = "") -> dict | None:
    dlg = FormDialog(title, fields, hint, parent)
    return dlg.values() if _exec(parent, dlg) else None


def _confirm(parent, title: str, text: str) -> bool:
    runner = getattr(parent, "confirm", None)
    if runner is not None:
        return runner(text)
    return QMessageBox.question(parent, title, text) == QMessageBox.Yes


def _selected(t: QTableWidget):
    items = t.selectedItems()
    return t.item(items[0].row(), 0).data(Qt.UserRole) if items else None


def _qty(value) -> str:
    return decimals.format_qty(value) if value is not None else "—"


def _date(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime.datetime):
        return f"{numerals.format_jalali_date(value.date())} {value.astimezone().strftime('%H:%M')}"
    return numerals.format_jalali_date(value)


def _text(value=None, height: int = 80) -> QTextEdit:
    w = QTextEdit()
    w.setPlainText(value or "")
    w.setMaximumHeight(height)
    return w


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionHint")
    label.setWordWrap(True)
    return label


def _title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("pageTitle")
    return label


def _buttons(owner, specs: list[tuple[str, str, "callable"]]) -> dict[str, QPushButton]:
    out = {}
    for key, text, slot in specs:
        b = QPushButton(text)
        b.clicked.connect(lambda _c=False, f=slot: f())
        out[key] = b
    owner.buttons = {**getattr(owner, "buttons", {}), **out}
    return out


def _fill_result(t: QTableWidget, result) -> None:
    """جدول از خروجی موتور گزارش (همان ستون‌ها و قالب گزارش)."""
    from peecha.services import purchase_reports as rs

    t.setColumnCount(len(result.columns))
    t.setHorizontalHeaderLabels([h for h, _k in result.columns])
    t.setRowCount(len(result.rows))
    for r, row in enumerate(result.rows):
        for col, ((_h, kind), value) in enumerate(zip(result.columns, row)):
            if value is None or value == "":
                text = "—" if kind != rs.TEXT else ""
            elif kind == rs.DATE:
                text = numerals.format_jalali_date(value)
            elif kind == rs.PERCENT:
                text = P(f"{value}٪")
            elif kind == rs.MONEY:
                text = numerals.format_money(decimal.Decimal(value), decimals.money_decimals(), None)
            elif kind == rs.QTY:
                text = decimals.format_qty(value)
            else:
                text = P(value)
            t.setItem(r, col, QTableWidgetItem(text))


def _open_report(main_window, code: str, date_from=None, date_to=None, options: dict | None = None, **filters) -> None:
    if main_window is not None:
        main_window.open_screen(f"INV_RPT_{code}",
                                then=lambda s: s.apply_preset(date_from, date_to, options or {}, **filters))


class _Lookups:
    """فهرست‌های مشترک (یک بار در هر refresh)."""

    def __init__(self, cid: int) -> None:
        from peecha.services import detail_dimensions as dims
        from peecha.services import inventory_catalog as catalog
        from peecha.services import inventory_locations as locations
        from peecha.services.crm.common import list_company_users

        self.items = [(f"{i.code} — {i.name or ''}", i.item_id) for i in catalog.list_items(cid, transactable_only=True)]
        self.categories = [(f"{x.code} — {x.name}", x.category_id) for x in catalog.list_categories(cid)]
        self.suppliers = [(f"{s['code']} — {s['name'] or ''}", s["detail_account_id"]) for s in dims.list_suppliers(cid)]
        self.customers = [(f"{s['code']} — {s['name'] or ''}", s["detail_account_id"]) for s in dims.list_customers(cid)]
        self.users = [(name, uid) for uid, name in list_company_users(cid)]
        whs = locations.list_warehouses(cid, active_only=True)
        self.warehouses = [(f"{w.code} — {w.name}", w.warehouse_id) for w in whs]
        disposal = set(stock_controls.DISPOSAL_WAREHOUSE_TYPES)
        self.usable_warehouses = [(f"{w.code} — {w.name}", w.warehouse_id) for w in whs
                                  if getattr(w, "warehouse_type_code", None) not in disposal]
        self.reject_warehouses = [(f"{w.code} — {w.name}", w.warehouse_id) for w in qc.reject_warehouses(cid)]


# =========================================================================================================
# فرم ثبت نتیجه
# =========================================================================================================
class ResultDialog(QDialog):
    """ثبت نتیجهٔ بازرسی یک ردیف نگه‌داشته یا یک عملیات تولید، با پارامترهای طرح و چند نمونه."""

    def __init__(self, title: str, lot, plan, plan_choices, plan_loader, reject_warehouses=None, mode: str = "LINE",
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(820, 600)
        self.mode = mode
        self.lot = decimal.Decimal(lot) if lot is not None else None
        self._plan_loader = plan_loader
        self.plan = plan
        self._rows: list[tuple] = []
        outer = QVBoxLayout(self)
        self.info = _hint("")
        outer.addWidget(self.info)
        body = QWidget()
        form = QFormLayout(body)
        form.setContentsMargins(0, 0, 0, 0)
        self.plan_box = combo(plan_choices, "— بدون طرح (پارامتر آزاد) —")
        set_combo(self.plan_box, plan.plan_id if plan else None)
        self.plan_box.currentIndexChanged.connect(self._plan_changed)
        form.addRow("طرح کیفیت", self.plan_box)
        self.samples = QSpinBox()
        self.samples.setRange(1, 50)
        self.samples.valueChanged.connect(lambda _v: self._build_rows())
        form.addRow("تعداد نمونهٔ اندازه‌گیری", self.samples)
        self.sampled = num_field(plan.suggested_sample if plan and plan.suggested_sample is not None else None)
        form.addRow("مقدار نمونه‌برداری‌شده", self.sampled)
        self.accepted = num_field(self.lot if self.lot is not None else None)
        self.rejected = num_field(_ZERO)
        self.pending = num_field(_ZERO)
        form.addRow("مقدار پذیرفته", self.accepted)
        form.addRow("مقدار مردود", self.rejected)
        form.addRow("مقدار دوباره‌کاری" if mode == "OPERATION" else "مقدار در انتظار تصمیم یا دوباره‌کاری", self.pending)
        self.disposition = combo([("پذیرش، رد یا پذیرش بخشی (طبق مقدارها)", None), ("مصرف مشروط", "CONCESSION"),
                                  ("دوباره‌کاری", "REWORK"), ("در انتظار تصمیم", "PENDING")])
        if mode == "LINE":
            form.addRow("تصمیم", self.disposition)
        self.reject_wh = combo(reject_warehouses or [], "— انبار قرنطینهٔ پیش‌فرض —")
        if mode == "LINE":
            form.addRow("انبار مقدار مردود", self.reject_wh)
        self.notes = _text()
        form.addRow("توضیح", self.notes)
        outer.addWidget(scrolled(body, 300))
        outer.addWidget(_hint("مقدار هر پارامتر را وارد کنید؛ ستون «انطباق» با حدود همان طرح محاسبه می‌شود و حدود در خود بازرسی "
                              "ثابت ذخیره می‌شود. نتیجهٔ تأییدشده دیگر قابل تغییر نیست."))
        self.params = QTableWidget(0, 6)
        self.params.setHorizontalHeaderLabels(["نمونه", "پارامتر", "حدود مجاز", "مقدار", "واحد", "انطباق"])
        self.params.verticalHeader().setVisible(False)
        self.params.setSelectionMode(QAbstractItemView.NoSelection)
        self.params.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.params, stretch=1)
        self.verdict = QLabel("")
        outer.addWidget(self.verdict)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        outer.addWidget(box)
        self._show_info()
        self._build_rows()

    def _show_info(self) -> None:
        p = self.plan
        parts = []
        if self.lot is not None:
            parts.append(f"مقدار تحت کنترل: {_qty(self.lot)}")
        if p is not None:
            parts.append(f"طرح {p.code} نسخهٔ {p.version_no} — {p.sampling_label}، عدد پذیرش {p.acceptance_number}")
            if p.suggested_sample is not None:
                parts.append(f"نمونهٔ پیشنهادی: {_qty(p.suggested_sample)}")
        else:
            parts.append("طرح کیفیتی برای این مورد پیدا نشد؛ نتیجه بدون پارامتر یا با پارامتر آزاد ثبت می‌شود.")
        self.info.setText(P("  •  ".join(parts)))

    def _plan_changed(self) -> None:
        plan_id = self.plan_box.currentData()
        try:
            self.plan = self._plan_loader(plan_id) if plan_id else None
        except ValueError as exc:
            _warn(self, self.windowTitle(), str(exc))
            self.plan = None
        if self.plan is not None and self.plan.suggested_sample is not None:
            self.sampled.setText(decimals.plain(self.plan.suggested_sample))
        self._show_info()
        self._build_rows()

    def _build_rows(self) -> None:
        params = self.plan.parameters if self.plan else []
        self.params.setRowCount(len(params) * self.samples.value())
        self._rows = []
        r = 0
        for sample in range(1, self.samples.value() + 1):
            for p in params:
                limits = []
                if p.data_type == "NUMERIC":
                    if p.min_value is not None:
                        limits.append(f"حداقل {decimals.plain(p.min_value)}")
                    if p.target_value is not None:
                        limits.append(f"هدف {decimals.plain(p.target_value)}")
                    if p.max_value is not None:
                        limits.append(f"حداکثر {decimals.plain(p.max_value)}")
                elif p.data_type == "OPTION":
                    limits.append("، ".join(o["value"] + ("" if o.get("ok", True) else " (نامنطبق)") for o in p.options))
                for col, text in ((0, str(sample)), (1, p.name + (" *" if p.is_mandatory else "")), (2, "  ".join(limits)),
                                  (4, p.uom_label)):
                    item = QTableWidgetItem(P(text))
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.params.setItem(r, col, item)
                if p.data_type == "PASS_FAIL":
                    editor = combo([("قبول", True), ("رد", False)], "—")
                    editor.currentIndexChanged.connect(lambda _i, row=r: self._evaluate(row))
                elif p.data_type == "OPTION":
                    editor = combo([(o["value"], o["value"]) for o in p.options], "—")
                    editor.currentIndexChanged.connect(lambda _i, row=r: self._evaluate(row))
                else:
                    editor = QLineEdit()
                    if p.data_type == "NUMERIC":
                        editor.setProperty("numeric", True)
                    editor.textChanged.connect(lambda _t, row=r: self._evaluate(row))
                if p.test_method:
                    editor.setToolTip(f"روش آزمون: {p.test_method}")
                self.params.setCellWidget(r, 3, editor)
                self.params.setItem(r, 5, QTableWidgetItem(""))
                self._rows.append((sample, p, editor))
                r += 1
        self._refresh_verdict()

    def _value(self, p, editor):
        if isinstance(editor, QComboBox):
            return editor.currentData()
        text = numerals.to_ascii_digits(editor.text().strip())
        if p.data_type == "NUMERIC" and text:
            try:
                return decimal.Decimal(text.replace(",", "").replace("٬", ""))
            except decimal.InvalidOperation:
                return "?"
        return text or None

    def _evaluate(self, row: int) -> None:
        _sample, p, editor = self._rows[row]
        value = self._value(p, editor)
        try:
            ok = None if value == "?" else plan_service.evaluate(p.data_type, value, p.min_value, p.max_value, p.options)
        except (ValueError, decimal.InvalidOperation):
            ok = False
        item = self.params.item(row, 5)
        item.setText("نامعتبر" if value == "?" else ("" if ok is None else ("منطبق" if ok else "نامنطبق")))
        item.setForeground(_GREEN if ok else _RED)
        self._refresh_verdict()

    def defective_samples(self) -> int:
        bad = set()
        for sample, p, editor in self._rows:
            value = self._value(p, editor)
            if value in (None, "", "?"):
                continue
            try:
                if plan_service.evaluate(p.data_type, value, p.min_value, p.max_value, p.options) is False:
                    bad.add(sample)
            except ValueError:
                bad.add(sample)
        return len(bad)

    def _refresh_verdict(self) -> None:
        if self.plan is None:
            self.verdict.setText("")
            return
        bad = self.defective_samples()
        verdict = plan_service.verdict(SimpleNs(acceptance_number=self.plan.acceptance_number), bad)
        theme.set_status_label(self.verdict, P(f"نمونهٔ نامنطبق: {bad} — پیشنهاد طرح: {'رد محموله' if verdict == 'REJECT' else 'پذیرش'}"),
                               ok=verdict != "REJECT")

    def set_value(self, row: int, value) -> None:
        """برای آزمون و ورود سریع: مقدار ردیف پارامتر."""
        editor = self._rows[row][2]
        if isinstance(editor, QComboBox):
            set_combo(editor, value)
        else:
            editor.setText(str(value))

    def accept(self) -> None:
        if self.lot is not None:
            total = dec(self.accepted.text()) + dec(self.rejected.text()) + dec(self.pending.text())
            if total != self.lot:
                _warn(self, self.windowTitle(), P(f"جمع پذیرفته، مردود و در انتظار ({_qty(total)}) باید برابر مقدار تحت کنترل "
                                                  f"({_qty(self.lot)}) باشد."))
                return
        if any(self._value(p, e) == "?" for _s, p, e in self._rows):
            _warn(self, self.windowTitle(), "مقدار عددی نامعتبر وارد شده است.")
            return
        super().accept()

    def values(self) -> dict:
        results = [qc.ResultInput(value=self._value(p, editor), parameter_id=p.parameter_id, sample_no=sample)
                   for sample, p, editor in self._rows if self._value(p, editor) not in (None, "")]
        sampled = self.sampled.text().strip()
        return {"plan_id": self.plan.plan_id if self.plan else None, "sampled": dec(sampled) if sampled else None,
                "accepted": dec(self.accepted.text()), "rejected": dec(self.rejected.text()), "pending": dec(self.pending.text()),
                "disposition": self.disposition.currentData() if self.mode == "LINE" else None,
                "reject_warehouse_id": self.reject_wh.currentData(), "notes": self.notes.toPlainText().strip() or None,
                "results": results}


class SimpleNs:
    def __init__(self, **kw) -> None:
        self.__dict__.update(kw)


class InspectionDetailDialog(QDialog):
    def __init__(self, detail, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"بازرسی {P(detail.header.inspection_id)}")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(780, 560)
        h = detail.header
        layout = QVBoxLayout(self)
        lines = [f"{h.stage_label} — {h.item_label}", f"وضعیت: {h.status_label} — نتیجه: {h.result_label} — تصمیم: {h.disposition_label}",
                 f"تحت کنترل {_qty(h.lot)} • پذیرفته {_qty(h.accepted)} • مردود {_qty(h.rejected)} • در انتظار {_qty(h.pending)}",
                 f"بازرس: {h.inspector or '—'} در {_date(h.inspected_at)} • تأییدکننده: {h.approver or '—'} در {_date(h.approved_at)}"]
        if h.document_no:
            lines.append(f"سند منبع: {h.document_no} — طرف‌حساب: {h.party_label or '—'}")
        if h.order_code:
            lines.append(f"دستور تولید: {h.order_code} {('— عملیات ' + h.operation_name) if h.operation_name else ''}")
        if h.plan_label:
            lines.append(f"طرح کیفیت: {h.plan_label}")
        if h.reinspection_of_id:
            lines.append(f"بازرسی مجدد پس از بازرسی {h.reinspection_of_id}")
        if h.notes:
            lines.append(f"توضیح بازرس: {h.notes}")
        if h.decision_notes:
            lines.append(f"توضیح تصمیم: {h.decision_notes}")
        info = _hint(P("\n".join(lines)))
        layout.addWidget(info)
        self.results = table(["نمونه", "پارامتر", "نوع", "حداقل", "هدف", "حداکثر", "مقدار", "واحد", "انطباق"])
        fill(self.results, [[r.sample_no, r.name, r.data_type_label, decimals.plain(r.min_value) if r.min_value is not None else "",
                             decimals.plain(r.target_value) if r.target_value is not None else "",
                             decimals.plain(r.max_value) if r.max_value is not None else "",
                             decimals.plain(r.value) if isinstance(r.value, decimal.Decimal) else (r.value or ""), r.unit,
                             "" if r.conforming is None else ("منطبق" if r.conforming else "نامنطبق")] for r in detail.results])
        layout.addWidget(QLabel("نتایج پارامترها"))
        layout.addWidget(self.results, stretch=2)
        self.history = table(["زمان", "کاربر", "رویداد", "جزئیات"])
        fill(self.history, [[_date(x.at), x.user, _ACTION_LABELS.get(x.action, x.action), _changes_text(x.changes)]
                            for x in detail.history])
        layout.addWidget(QLabel("تاریخچهٔ تصمیم"))
        layout.addWidget(self.history, stretch=1)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        box.accepted.connect(self.accept)
        layout.addWidget(box)


_ACTION_LABELS = {"CREATE": "ثبت", "UPDATE": "ویرایش", "APPROVE": "تأیید", "CANCEL": "لغو", "RESOLVE": "بستن", "EXECUTE": "اجرا",
                  "COMPLETE": "انجام", "REJECT": "رد", "SUBMIT": "ارسال"}
_CHANGE_LABELS = {"operation": "عملیات", "stage": "مرحله", "accepted": "پذیرفته", "rejected": "مردود", "pending": "در انتظار",
                  "rework": "دوباره‌کاری", "status": "وضعیت", "note": "توضیح", "disposition": "تصمیم", "reason": "علت",
                  "quantity": "مقدار", "evidence": "شواهد", "effective": "اثربخش"}
_OPERATION_LABELS = {"QC_RECORD": "ثبت نتیجه", "QC_APPROVE": "تأیید نهایی", "QC_INSPECT": "بازرسی یک‌مرحله‌ای", "QC_CANCEL": "لغو نتیجه",
                     "QC_RELEASE": "آزادسازی قرنطینه", "QC_RETURN": "برگشت به تامین‌کننده"}


_VALUE_LABELS = {**c.CAPA_STATUS_LABELS, **c.NCR_STATUS_LABELS, **c.STATUS_LABELS, **c.DISPOSITION_LABELS,
                 **c.NCR_DISPOSITION_LABELS}


def _changes_text(changes: dict) -> str:
    parts = []
    for k, v in (changes or {}).items():
        if k not in _CHANGE_LABELS or v in (None, "", []):
            continue
        if k == "operation":
            v = _OPERATION_LABELS.get(v, v)
        elif isinstance(v, list) and len(v) == 2:
            v = f"{_VALUE_LABELS.get(v[0], v[0]) or '—'} ← {_VALUE_LABELS.get(v[1], v[1]) or '—'}"
        elif isinstance(v, str):
            v = _VALUE_LABELS.get(v, v)
        parts.append(f"{_CHANGE_LABELS[k]}: {v}")
    return P("، ".join(parts))


# =========================================================================================================
# صف بازرسی و تأیید
# =========================================================================================================
@ms.styled
class InspectionQueueScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.pending_rows: list = []
        self.recorded_rows: list = []
        self.history_rows: list = []
        self.ops: list = []
        self.lk: _Lookups | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        self.stage = combo([(v, k) for k, v in c.STAGE_LABELS.items()], "همهٔ مرحله‌ها")
        self.stage.currentIndexChanged.connect(lambda _i: self.reload())
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو: کالا، سند، طرف‌حساب")
        self.search.returnPressed.connect(self.reload)
        outer.addWidget(ms.header_card(_title("صف بازرسی و تأیید"), self.stage, self.search))
        cards, self.cards = ms.summary([("waiting", "منتظر بازرسی", "warning", "🧪"), ("awaiting", "منتظر تأیید نهایی", "info", "🛡️"),
                                        ("late", "بیش از مهلت رسیدگی", "danger", "⏰"), ("today", "تأییدشدهٔ امروز", "success", "✅")])
        outer.addWidget(cards)
        self.mode_hint = _hint("")
        outer.addWidget(self.mode_hint)
        self.tabs = QTabWidget()
        # منتظر بازرسی
        w = QWidget()
        lay = QVBoxLayout(w)
        self.t_pending = table(["سند", "تاریخ", "مرحله", "طرف‌حساب یا دستور", "انبار", "کالا", "بچ", "مقدار تحت کنترل", "وضعیت"])
        self.t_pending.cellDoubleClicked.connect(lambda _r, _c: self.record_selected())
        lay.addWidget(self.t_pending, stretch=1)
        self.spec = _hint("")
        self.t_pending.itemSelectionChanged.connect(self._show_spec)
        lay.addWidget(self.spec)
        b = _buttons(self, [("record", "ثبت نتیجهٔ بازرسی", self.record_selected), ("accept_all", "پذیرش کامل", self.accept_all),
                            ("refresh", "به‌روزرسانی", self.refresh)])
        lay.addWidget(ms.footer([[b["record"], b["accept_all"]], [b["refresh"]]]))
        self.tabs.addTab(w, "منتظر بازرسی")
        # منتظر تأیید
        w = QWidget()
        lay = QVBoxLayout(w)
        self.t_recorded = table(["شماره", "ثبت", "مرحله", "کالا", "سند یا دستور", "تحت کنترل", "پذیرفته", "مردود", "در انتظار", "تصمیم",
                                 "بازرس"])
        self.t_recorded.cellDoubleClicked.connect(lambda _r, _c: self.show_detail(self.t_recorded))
        lay.addWidget(self.t_recorded, stretch=1)
        b = _buttons(self, [("approve", "تأیید نهایی", self.approve_selected), ("cancel", "لغو نتیجه", self.cancel_selected),
                            ("detail_r", "ریز بازرسی", lambda: self.show_detail(self.t_recorded))])
        lay.addWidget(ms.footer([[b["approve"], b["cancel"]], [b["detail_r"]]]))
        self.tabs.addTab(w, "منتظر تأیید نهایی")
        # حین تولید
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel("دستور تولید:"))
        self.order_box = combo([], "— انتخاب دستور —")
        self.order_box.currentIndexChanged.connect(lambda _i: self.load_operations())
        row.addWidget(self.order_box, stretch=1)
        lay.addLayout(row)
        self.t_ops = table(["ردیف", "عملیات", "وضعیت عملیات", "کنترل اجباری", "طرح کیفیت", "آخرین بازرسی", "وضعیت بازرسی", "نتیجه"])
        self.t_ops.cellDoubleClicked.connect(lambda _r, _c: self.record_operation())
        lay.addWidget(self.t_ops, stretch=1)
        b = _buttons(self, [("record_op", "ثبت نتیجهٔ حین تولید", self.record_operation)])
        lay.addWidget(ms.footer([[b["record_op"]]]))
        self.tabs.addTab(w, "بازرسی حین تولید")
        # سوابق
        w = QWidget()
        lay = QVBoxLayout(w)
        self.t_history = table(["شماره", "ثبت", "مرحله", "وضعیت", "نتیجه", "تصمیم", "کالا", "سند یا دستور", "پذیرفته", "مردود",
                                "در انتظار", "بازرس", "تأییدکننده"])
        self.t_history.cellDoubleClicked.connect(lambda _r, _c: self.show_detail(self.t_history))
        lay.addWidget(self.t_history, stretch=1)
        b = _buttons(self, [("detail_h", "ریز بازرسی", lambda: self.show_detail(self.t_history)),
                            ("ncr", "عدم‌انطباق جدید", self.ncr_from_inspection),
                            ("report", "گزارش کامل", lambda: _open_report(self._main_window, "QC_INSPECTION_LOG"))])
        lay.addWidget(ms.footer([[b["detail_h"], b["ncr"]], [b["report"]]]))
        self.tabs.addTab(w, "سوابق بازرسی")
        outer.addWidget(self.tabs, stretch=1)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.lk = _Lookups(cid)
        uid = user_id()
        self.buttons["record"].setEnabled(c.can(cid, uid, c.FORM_INSPECT, "CREATE"))
        self.buttons["accept_all"].setEnabled(c.can(cid, uid, c.FORM_INSPECT, "CREATE"))
        self.buttons["record_op"].setEnabled(c.can(cid, uid, c.FORM_INSPECT, "CREATE"))
        self.buttons["approve"].setEnabled(c.can(cid, uid, c.FORM_APPROVE))
        self.buttons["cancel"].setEnabled(c.can(cid, uid, c.FORM_INSPECT, "CREATE") or c.can(cid, uid, c.FORM_APPROVE))
        self.buttons["ncr"].setEnabled(c.can(cid, uid, c.FORM_NCR, "CREATE"))
        current = self.order_box.currentData()
        self.order_box.blockSignals(True)
        self.order_box.clear()
        self.order_box.addItem("— انتخاب دستور —", None)
        for label, oid in queries.open_orders(cid):
            self.order_box.addItem(P(label), oid)
        set_combo(self.order_box, current)
        self.order_box.blockSignals(False)
        separate = c.is_on(cid, stock_controls.QC_SEPARATE_APPROVAL)
        on = c.is_on(cid, stock_controls.QC_HOLD)
        self.mode_hint.setText(
            ("نگه‌داشت رسید تا تأیید کیفیت خاموش است؛ رسیدها بدون کنترل آزادند. " if not on else "")
            + ("ثبت نتیجه و تأیید نهایی جداست: بازرس ثبت می‌کند و کاربر دیگری تأیید می‌کند؛ موجودی تا تأیید نگه داشته می‌ماند."
               if separate else "با ثبت نتیجه، موجودی بی‌درنگ تعیین تکلیف می‌شود (پذیرفته آزاد، مردود به قرنطینه یا ضایعات)."))
        self.reload()

    def _match(self, *texts) -> bool:
        needle = numerals.to_ascii_digits(self.search.text().strip())
        return not needle or any(needle in numerals.to_ascii_digits(str(t or "")) for t in texts)

    def reload(self) -> None:
        cid = company_id()
        if cid is None or self.lk is None:
            return
        stage = self.stage.currentData()
        whs = dict((v, k) for k, v in self.lk.warehouses)
        st = c.settings(cid)
        today = datetime.date.today()
        pending = [r for r in qc.list_pending(cid) if (stage is None or r.stage_code == stage)
                   and self._match(r.document_no, r.item_code, r.item_name, r.party_name)]
        self.pending_rows = pending
        fill(self.t_pending, [[r.document_no, r.document_date, c.STAGE_LABELS[r.stage_code], r.party_name,
                               whs.get(r.warehouse_id, ""), f"{r.item_code} — {r.item_name}", "، ".join(r.batch_nos), _qty(r.quantity),
                               "نتیجهٔ منتظر تأیید" if r.open_inspection_id else "منتظر بازرسی"] for r in pending],
             [r.line_id for r in pending])
        late = 0
        for i, r in enumerate(pending):
            if r.document_date and (today - r.document_date).days > int(decimal.Decimal(st.target_handling_days)):
                late += 1
                self.t_pending.item(i, 1).setForeground(_RED)
        recorded = [r for r in queries.list_inspections(cid, status="RECORDED", stage=stage)
                    if self._match(r.item_label, r.document_no, r.order_code, r.party_label)]
        self.recorded_rows = recorded
        fill(self.t_recorded, [[r.inspection_id, _date(r.inspected_at), r.stage_label, r.item_label,
                                r.document_no or r.order_code, _qty(r.lot), _qty(r.accepted), _qty(r.rejected), _qty(r.pending),
                                r.disposition_label, r.inspector] for r in recorded], [r.inspection_id for r in recorded])
        history = [r for r in queries.list_inspections(cid, stage=stage, limit=500)
                   if self._match(r.item_label, r.document_no, r.order_code, r.party_label)]
        self.history_rows = history
        fill(self.t_history, [[r.inspection_id, _date(r.inspected_at), r.stage_label, r.status_label, r.result_label,
                               r.disposition_label, r.item_label, r.document_no or r.order_code, _qty(r.accepted), _qty(r.rejected),
                               _qty(r.pending), r.inspector, r.approver] for r in history], [r.inspection_id for r in history])
        self.cards["waiting"].setText(P(len([r for r in pending if not r.open_inspection_id])))
        self.cards["awaiting"].setText(P(len(recorded)))
        self.cards["late"].setText(P(late))
        self.cards["today"].setText(P(sum(1 for r in history if r.status_code == "APPROVED" and r.approved_at
                                          and r.approved_at.astimezone().date() == today)))
        self.load_operations()
        self._show_spec()

    def _show_spec(self) -> None:
        r = self._pending()
        parts = [p for p in ((f"استاندارد: {r.qc_standard}" if r and r.qc_standard else ""),
                             (f"آزمون: {r.qc_test_spec}" if r and r.qc_test_spec else "")) if p]
        self.spec.setText(P("  •  ".join(parts)))

    def _pending(self):
        line_id = _selected(self.t_pending)
        return next((r for r in self.pending_rows if r.line_id == line_id), None)

    def _need_pending(self):
        r = self._pending()
        if r is None:
            _warn(self, "بازرسی", "یک ردیف منتظر بازرسی را انتخاب کنید.")
        elif r.open_inspection_id:
            _warn(self, "بازرسی", "برای این ردیف نتیجهٔ منتظر تأیید ثبت شده است؛ آن را در تب «منتظر تأیید نهایی» تأیید یا لغو کنید.")
            return None
        return r

    def _after_record(self, cid: int, inspection_id: int, reject_wh) -> None:
        if c.is_on(cid, stock_controls.QC_SEPARATE_APPROVAL):
            self._status(f"نتیجه ثبت شد (شمارهٔ {inspection_id}) و منتظر تأیید نهایی است.")
            return
        result, ok = _run(self, "تأیید نهایی", qc.approve, cid, inspection_id, user_id(), reject_wh)
        if ok:
            self._status(f"نتیجه ثبت و تأیید شد: {c.RESULT_LABELS.get(result.result_code, '')}")

    def _status(self, text: str) -> None:
        if self._main_window is not None and hasattr(self._main_window, "statusBar"):
            self._main_window.statusBar().showMessage(P(text), 6000)
        self.last_status = text

    def record_selected(self) -> int | None:
        r = self._need_pending()
        if r is None:
            return None
        cid = company_id()
        plan, ok = _run(self, "بازرسی", queries.plan_for_line, cid, r.line_id, None, r.quantity)
        if not ok:
            return None
        dlg = ResultDialog(f"ثبت نتیجهٔ بازرسی — {r.item_code} {r.item_name}", r.quantity, plan,
                           queries.active_plans(cid, r.stage_code),
                           lambda pid: queries.plan_for_line(cid, r.line_id, pid, r.quantity), self.lk.reject_warehouses, "LINE", self)
        if not _exec(self, dlg):
            return None
        v = dlg.values()
        inspection_id, ok = _run(self, "بازرسی", qc.record_result, cid, r.line_id, user_id(), accepted=v["accepted"],
                                 rejected=v["rejected"], pending=v["pending"], sampled=v["sampled"], results=v["results"],
                                 notes=v["notes"], plan_id=v["plan_id"], disposition=v["disposition"])
        if not ok:
            return None
        self._after_record(cid, inspection_id, v["reject_warehouse_id"])
        self.reload()
        return inspection_id

    def accept_all(self) -> int | None:
        r = self._need_pending()
        if r is None:
            return None
        if not _confirm(self, "پذیرش کامل", P(f"تمام {_qty(r.quantity)} واحد «{r.item_name}» پذیرفته شود؟")):
            return None
        cid = company_id()
        inspection_id, ok = _run(self, "پذیرش کامل", qc.record_result, cid, r.line_id, user_id(), accepted=r.quantity)
        if not ok:
            return None
        self._after_record(cid, inspection_id, None)
        self.reload()
        return inspection_id

    def _recorded(self):
        iid = _selected(self.t_recorded)
        return next((r for r in self.recorded_rows if r.inspection_id == iid), None)

    def approve_selected(self) -> bool:
        r = self._recorded()
        if r is None:
            _warn(self, "تأیید نهایی", "یک نتیجهٔ منتظر تأیید را انتخاب کنید.")
            return False
        fields = [("notes", "توضیح تصمیم", _text())]
        if r.line_id and r.rejected:
            fields.insert(0, ("reject_warehouse_id", "انبار مقدار مردود", combo(self.lk.reject_warehouses, "— انبار قرنطینهٔ پیش‌فرض —")))
        hint = P(f"{r.item_label}: پذیرفته {_qty(r.accepted)}، مردود {_qty(r.rejected)}، در انتظار {_qty(r.pending)} — "
                 f"{r.disposition_label}. با تأیید، موجودی تعیین تکلیف می‌شود و نتیجه دیگر قابل تغییر نیست.")
        values = _ask(self, "تأیید نهایی کیفیت", fields, hint)
        if values is None:
            return False
        _result, ok = _run(self, "تأیید نهایی", qc.approve, company_id(), r.inspection_id, user_id(),
                           values.get("reject_warehouse_id"), values.get("notes"))
        if ok:
            self._status("نتیجهٔ بازرسی تأیید شد.")
            self.reload()
        return ok

    def cancel_selected(self) -> bool:
        r = self._recorded()
        if r is None:
            _warn(self, "لغو نتیجه", "یک نتیجهٔ منتظر تأیید را انتخاب کنید.")
            return False
        values = _ask(self, "لغو نتیجهٔ بازرسی", [("reason", "علت لغو", _text())],
                      "نتیجهٔ تأییدنشده لغو می‌شود تا دوباره ثبت شود؛ سابقه‌اش در تاریخچه می‌ماند.")
        if values is None:
            return False
        _r, ok = _run(self, "لغو نتیجه", qc.cancel, company_id(), r.inspection_id, user_id(), values.get("reason") or "")
        if ok:
            self.reload()
        return ok

    def show_detail(self, t: QTableWidget) -> None:
        iid = _selected(t)
        if iid is None:
            _warn(self, "ریز بازرسی", "یک بازرسی را انتخاب کنید.")
            return
        detail, ok = _run(self, "ریز بازرسی", queries.inspection_detail, company_id(), iid)
        if ok:
            dlg = InspectionDetailDialog(detail, self)
            self.last_detail = dlg
            _exec(self, dlg)

    def ncr_from_inspection(self) -> int | None:
        iid = _selected(self.t_history)
        r = next((x for x in self.history_rows if x.inspection_id == iid), None)
        if r is None:
            _warn(self, "عدم‌انطباق", "یک بازرسی را انتخاب کنید.")
            return None
        source = {"RECEIPT": "RECEIPT", "SALES_RETURN": "SALES_RETURN", "IN_PROCESS": "IN_PROCESS", "FINAL": "FINAL"}[r.stage_code]
        prefill = SimpleNs(title=f"عدم‌انطباق {r.item_label}", source_code=source, item_id=r.item_id,
                           supplier_detail_account_id=r.party_id if r.stage_code == "RECEIPT" else None,
                           customer_detail_account_id=r.party_id if r.stage_code == "SALES_RETURN" else None,
                           quantity=r.rejected or r.pending or _ZERO, production_order_id=r.order_id)
        return NcrScreen.create_from(self, self.lk, prefill, qc_inspection_id=r.inspection_id)

    # --- حین تولید --------------------------------------------------------------------------------
    def load_operations(self) -> None:
        from peecha.services.qms import production

        oid = self.order_box.currentData()
        self.ops = []
        if oid is not None:
            rows, ok = _run(self, "بازرسی حین تولید", production.operations_for_order, company_id(), oid)
            self.ops = rows if ok else []
        fill(self.t_ops, [[o.seq, o.name, o.status_code, "بله" if o.required else "خیر", o.plan_name,
                           o.last_inspection_id or "", o.last_status, o.last_result] for o in self.ops],
             [o.order_operation_id for o in self.ops])
        for i, o in enumerate(self.ops):
            if o.required and o.last_status != c.STATUS_LABELS["APPROVED"]:
                self.t_ops.item(i, 3).setForeground(_RED)

    def record_operation(self) -> int | None:
        from peecha.services.qms import production

        op_id = _selected(self.t_ops)
        op = next((o for o in self.ops if o.order_operation_id == op_id), None)
        if op is None:
            _warn(self, "بازرسی حین تولید", "یک عملیات را انتخاب کنید.")
            return None
        cid = company_id()
        plan, ok = _run(self, "بازرسی حین تولید", queries.plan_for_operation, cid, op.order_operation_id)
        if not ok:
            return None
        dlg = ResultDialog(f"بازرسی حین تولید — {op.name}", None, plan, queries.active_plans(cid, "IN_PROCESS"),
                           lambda pid: queries.plan_for_operation(cid, op.order_operation_id, pid), None, "OPERATION", self)
        if not _exec(self, dlg):
            return None
        v = dlg.values()
        inspection_id, ok = _run(self, "بازرسی حین تولید", production.record_operation_result, cid, op.order_operation_id, user_id(),
                                 accepted=v["accepted"], rejected=v["rejected"], rework=v["pending"], sampled=v["sampled"],
                                 results=v["results"], notes=v["notes"], plan_id=v["plan_id"])
        if not ok:
            return None
        self._after_record(cid, inspection_id, None)
        self.reload()
        return inspection_id


# =========================================================================================================
# قرنطینه
# =========================================================================================================
@ms.styled
class QuarantineScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.rows: list = []
        self.lk: _Lookups | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        self.warehouse = combo([], "همهٔ انبارهای قرنطینه و ضایعات")
        self.warehouse.currentIndexChanged.connect(lambda _i: self.reload())
        outer.addWidget(ms.header_card(_title("قرنطینه و کالای مردود"), self.warehouse))
        cards, self.cards = ms.summary([("items", "ردیف کالا", "info", "📦"), ("value", "ارزش موجودی قرنطینه", "warning", "💰"),
                                        ("scrap", "ارزش ضایعات", "danger", "♻️"), ("oldest", "قدیمی‌ترین (روز)", "danger", "⏳")])
        outer.addWidget(cards)
        self.lock_hint = _hint("")
        outer.addWidget(self.lock_hint)
        self.t = table(["انبار", "نوع", "کالا", "مقدار", "آزاد برای تصمیم", "ارزش", "آخرین ورود", "روز ماندگاری"])
        outer.addWidget(self.t, stretch=1)
        b = _buttons(self, [("release", "آزادسازی از قرنطینه", self.release), ("return", "برگشت به تامین‌کننده", self.return_supplier),
                            ("ncr", "عدم‌انطباق جدید", self.new_ncr), ("refresh", "به‌روزرسانی", self.refresh),
                            ("report", "گزارش کامل", lambda: _open_report(self._main_window, "QC_QUARANTINE"))])
        outer.addWidget(ms.footer([[b["release"], b["return"], b["ncr"]], [b["refresh"], b["report"]]]))

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.lk = _Lookups(cid)
        uid = user_id()
        self.buttons["release"].setEnabled(c.can(cid, uid, c.FORM_RELEASE))
        self.buttons["return"].setEnabled(c.can(cid, uid, c.FORM_RELEASE))
        self.buttons["ncr"].setEnabled(c.can(cid, uid, c.FORM_NCR, "CREATE"))
        current = self.warehouse.currentData()
        self.warehouse.blockSignals(True)
        self.warehouse.clear()
        self.warehouse.addItem("همهٔ انبارهای قرنطینه و ضایعات", None)
        for label, wid in self.lk.reject_warehouses:
            self.warehouse.addItem(P(label), wid)
        set_combo(self.warehouse, current)
        self.warehouse.blockSignals(False)
        self.lock_hint.setText(
            "قفل انبار قرنطینه روشن است: کالای این انبارها فقط از همین صفحه آزاد، به ضایعات منتقل یا به تامین‌کننده برگشت داده می‌شود."
            if c.is_on(cid, stock_controls.QC_QUARANTINE_LOCK) else
            "قفل انبار قرنطینه خاموش است؛ با روشن‌کردن آن (تنظیمات کنترل کیفیت) خروج عادی از قرنطینه بسته می‌شود.")
        self.reload()

    def reload(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.rows = qc.quarantine_stock(cid, self.warehouse.currentData())
        fill(self.t, [[r.warehouse_name, "قرنطینه" if r.warehouse_type == "QUARANTINE" else "ضایعات", r.item_label, _qty(r.quantity),
                       _qty(r.free), r.value, r.last_in, r.age_days if r.age_days is not None else ""] for r in self.rows],
             list(range(len(self.rows))))
        self.cards["items"].setText(P(len(self.rows)))
        self.cards["value"].setText(numerals.format_money(sum((r.value for r in self.rows if r.warehouse_type == "QUARANTINE"), _ZERO),
                                                          decimals.money_decimals(), None))
        self.cards["scrap"].setText(numerals.format_money(sum((r.value for r in self.rows if r.warehouse_type != "QUARANTINE"), _ZERO),
                                                          decimals.money_decimals(), None))
        ages = [r.age_days for r in self.rows if r.age_days is not None]
        self.cards["oldest"].setText(P(max(ages)) if ages else "—")

    def _row(self):
        idx = _selected(self.t)
        if idx is None or idx >= len(self.rows):
            _warn(self, "قرنطینه", "یک ردیف را انتخاب کنید.")
            return None
        return self.rows[idx]

    def _ncr_choices(self, item_id: int) -> list:
        return [(f"{n.ncr_no} — {n.title}", n.ncr_id) for n in ncr_service.list_ncrs(company_id(), open_only=True)]

    def release(self) -> int | None:
        r = self._row()
        if r is None:
            return None
        values = _ask(self, "آزادسازی از قرنطینه", [
            ("quantity", "مقدار", num_field(r.free)),
            ("target", "انبار مقصد", combo(self.lk.usable_warehouses)),
            ("reason", "علت آزادسازی", _text()),
            ("ncr_id", "پروندهٔ عدم‌انطباق", combo(self._ncr_choices(r.item_id), "—")),
        ], P(f"{r.item_label} — موجود در «{r.warehouse_name}»: {_qty(r.quantity)}. سند انتقال عادی ثبت می‌شود و در تاریخچه می‌ماند."))
        if values is None:
            return None
        doc_id, ok = _run(self, "آزادسازی", qc.release_from_quarantine, company_id(), user_id(), r.warehouse_id, r.item_id,
                          values["quantity"], values["target"], values.get("reason") or "", values.get("ncr_id"))
        if ok:
            self.reload()
        return doc_id

    def return_supplier(self) -> int | None:
        r = self._row()
        if r is None:
            return None
        values = _ask(self, "برگشت به تامین‌کننده", [
            ("quantity", "مقدار", num_field(r.free)),
            ("supplier", "تامین‌کننده", combo(self.lk.suppliers)),
            ("price", "مبلغ واحد (خالی = بهای موجودی)", num_field()),
            ("ncr_id", "پروندهٔ عدم‌انطباق", combo(self._ncr_choices(r.item_id), "—")),
        ], "پیش‌نویس «برگشت از خرید» ساخته می‌شود؛ ثبت آن و سند مالی از همان فرم برگشت به تامین‌کننده انجام می‌شود.")
        if values is None:
            return None
        price = values.get("price") or None
        doc_id, ok = _run(self, "برگشت به تامین‌کننده", qc.return_to_supplier, company_id(), user_id(), r.warehouse_id, r.item_id,
                          values["quantity"], values["supplier"], price, values.get("ncr_id"))
        if ok:
            self.last_status = f"پیش‌نویس برگشت از خرید ساخته شد (سند {doc_id})."
            if self._main_window is not None:
                self._main_window.open_screen("PURCH_RETURN", then=lambda s: hasattr(s, "edit_document") and s.edit_document(doc_id))
        return doc_id

    def new_ncr(self) -> int | None:
        r = self._row()
        if r is None:
            return None
        prefill = SimpleNs(title=f"کالای مردود {r.item_label}", source_code="INTERNAL", item_id=r.item_id, quantity=r.quantity,
                           supplier_detail_account_id=None, customer_detail_account_id=None, production_order_id=None)
        return NcrScreen.create_from(self, self.lk, prefill)


# =========================================================================================================
# عدم‌انطباق
# =========================================================================================================
def _ncr_form(lk: _Lookups, r=None, edit: bool = False) -> list:
    g = (lambda name, default=None: getattr(r, name, default)) if r else (lambda name, default=None: default)

    def pick(items, value, none="—"):
        box = combo(items, none)
        set_combo(box, value)
        return box

    fields = [("title", "عنوان", QLineEdit(g("title", "") or ""))]
    if not edit:
        fields.append(("source_code", "منبع", pick([(v, k) for k, v in c.NCR_SOURCE_LABELS.items()], g("source_code", "INTERNAL"), None)))
    fields += [
        ("severity_code", "شدت", pick([(v, k) for k, v in c.SEVERITY_LABELS.items()], g("severity_code", "MINOR"), None)),
        ("item_id", "کالا", pick(lk.items, g("item_id"))),
    ]
    if not edit:
        fields += [("supplier_detail_account_id", "تامین‌کننده", pick(lk.suppliers, g("supplier_detail_account_id"))),
                   ("customer_detail_account_id", "مشتری", pick(lk.customers, g("customer_detail_account_id")))]
    else:
        fields = [f for f in fields if f[0] != "item_id"]
    fields += [
        ("quantity", "مقدار نامنطبق", num_field(g("quantity", _ZERO))),
        ("cost_amount", "هزینهٔ برآوردی", num_field(g("cost_amount", _ZERO))),
        ("cause_code", "دستهٔ علت", pick([(v, k) for k, v in c.CAUSE_LABELS.items()], g("cause_code"))),
        ("responsible_user_id", "مسئول رسیدگی", pick(lk.users, g("responsible_user_id"))),
        ("disposition_code", "تعیین تکلیف کالا", pick([(v, k) for k, v in c.NCR_DISPOSITION_LABELS.items()], g("disposition_code"))),
        ("due_date", "مهلت رسیدگی", date_field(g("due_date") or datetime.date.today() + datetime.timedelta(days=7))),
        ("description", "شرح", _text(g("description"))),
    ]
    if edit:
        details = g("root_cause_details")
        if isinstance(details, list):
            details_text = "\n".join(details)
        elif isinstance(details, dict):
            details_text = "\n".join(f"{c.CAUSE_LABELS.get(k, k)}: {v}" for k, v in details.items())
        else:
            details_text = ""
        fields += [
            ("root_cause_method", "روش تحلیل علت ریشه‌ای",
             pick([(v, k) for k, v in c.ROOT_CAUSE_METHOD_LABELS.items()], g("root_cause_method"))),
            ("root_cause_details", "مراحل تحلیل (هر خط یک چرا، یا «عامل: توضیح»)", _text(details_text, 110)),
            ("root_cause", "علت ریشه‌ای", _text(g("root_cause"))),
        ]
    return fields


def _parse_details(method: str | None, text: str | None):
    if not text:
        return None
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if method == "FIVE_WHY":
        return lines[:5] if len(lines) <= 5 else lines
    if method == "FISHBONE":
        by_label = {v: k for k, v in c.CAUSE_LABELS.items()}
        out = {}
        for line in lines:
            label, _sep, note = line.partition(":")
            key = by_label.get(label.strip(), label.strip().upper())
            out[key] = note.strip()
        return out
    return None


@ms.styled
class NcrScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.rows: list = []
        self.detail = None
        self.lk: _Lookups | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        self.status = combo([(v, k) for k, v in c.NCR_STATUS_LABELS.items()], "همهٔ وضعیت‌ها")
        self.severity = combo([(v, k) for k, v in c.SEVERITY_LABELS.items()], "همهٔ شدت‌ها")
        self.open_only = QCheckBox("فقط باز")
        self.open_only.setChecked(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو: عنوان، کالا، طرف‌حساب")
        self.search.returnPressed.connect(self.reload)
        for w in (self.status, self.severity):
            w.currentIndexChanged.connect(lambda _i: self.reload())
        self.open_only.toggled.connect(lambda _c: self.reload())
        outer.addWidget(ms.header_card(_title("عدم‌انطباق‌ها"), self.search, self.status, self.severity, self.open_only))
        cards, self.cards = ms.summary([("open", "پروندهٔ باز", "info", "📂"), ("critical", "بحرانی و عمده", "danger", "⚠️"),
                                        ("overdue", "گذشته از مهلت", "warning", "⏰"), ("cost", "هزینهٔ پرونده‌های باز", "danger", "💸")])
        outer.addWidget(cards)
        split = QSplitter(Qt.Horizontal)
        self.t = table(["شماره", "تاریخ", "عنوان", "منبع", "شدت", "وضعیت", "کالا", "طرف‌حساب", "مقدار", "هزینه", "مسئول", "مهلت",
                        "اقدام باز"])
        self.t.itemSelectionChanged.connect(self._selected_changed)
        self.t.cellDoubleClicked.connect(lambda _r, _c: self.edit_ncr())
        split.addWidget(self.t)
        side = QWidget()
        sl = QVBoxLayout(side)
        self.info = _hint("")
        sl.addWidget(self.info)
        sl.addWidget(QLabel("اقدام‌های اصلاحی و پیشگیرانه"))
        self.t_actions = table(["نوع", "شرح", "مسئول", "مهلت", "وضعیت", "شواهد", "نتیجهٔ بررسی"])
        sl.addWidget(self.t_actions, stretch=1)
        sl.addWidget(QLabel("تاریخچهٔ تصمیم‌ها"))
        self.t_history = table(["زمان", "کاربر", "رویداد", "جزئیات"])
        sl.addWidget(self.t_history, stretch=1)
        split.addWidget(side)
        split.setSizes([820, 460])
        outer.addWidget(split, stretch=1)
        b = _buttons(self, [
            ("new", "عدم‌انطباق جدید", self.new_ncr), ("edit", "ویرایش پرونده", self.edit_ncr),
            ("investigate", "شروع بررسی", lambda: self.set_status("INVESTIGATING")),
            ("acting", "در حال اقدام", lambda: self.set_status("ACTION")), ("close", "بستن پرونده", lambda: self.set_status("CLOSED")),
            ("cancel", "لغو پرونده", lambda: self.set_status("CANCELLED")),
            ("add_action", "اقدام جدید", self.add_action), ("complete", "ثبت انجام اقدام", self.complete_action),
            ("verify", "بررسی اثربخشی", self.verify_action), ("cancel_action", "لغو اقدام", self.cancel_action),
            ("report", "گزارش کامل", lambda: _open_report(self._main_window, "QC_NCR")),
        ])
        outer.addWidget(ms.footer([[b["new"], b["edit"]], [b["investigate"], b["acting"], b["close"], b["cancel"]],
                                   [b["add_action"], b["complete"], b["verify"], b["cancel_action"]], [b["report"]]]))

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.lk = _Lookups(cid)
        uid = user_id()
        self.buttons["new"].setEnabled(c.can(cid, uid, c.FORM_NCR, "CREATE") and can("qc_ncr", "CREATE"))
        self.buttons["add_action"].setEnabled(c.can(cid, uid, c.FORM_NCR, "CREATE") and can("qc_ncr", "CREATE"))
        for k in ("edit", "investigate", "acting", "close", "cancel", "verify", "cancel_action"):
            self.buttons[k].setEnabled(c.can(cid, uid, c.FORM_NCR) and can("qc_ncr", "EDIT"))
        self.reload()

    def reload(self) -> None:
        cid = company_id()
        if cid is None:
            return
        needle = numerals.to_ascii_digits(self.search.text().strip())
        rows = ncr_service.list_ncrs(cid, status=self.status.currentData(), open_only=self.open_only.isChecked())
        sev = self.severity.currentData()
        self.rows = [r for r in rows if (sev is None or r.severity_code == sev)
                     and (not needle or any(needle in numerals.to_ascii_digits(str(t or ""))
                                            for t in (r.ncr_no, r.title, r.item_label, r.party_label)))]
        fill(self.t, [[r.ncr_no, r.detected_at.date() if r.detected_at else None, r.title, r.source_label, r.severity_label,
                       r.status_label, r.item_label, r.party_label, _qty(r.quantity), r.cost_amount, r.responsible, r.due_date,
                       r.open_actions] for r in self.rows], [r.ncr_id for r in self.rows])
        for i, r in enumerate(self.rows):
            tone = _SEVERITY_TONE.get(r.severity_code)
            if tone is not None:
                self.t.item(i, 4).setForeground(tone)
            if r.overdue:
                self.t.item(i, 11).setForeground(_RED)
        all_open = ncr_service.list_ncrs(cid, open_only=True)
        self.cards["open"].setText(P(len(all_open)))
        self.cards["critical"].setText(P(sum(1 for r in all_open if r.severity_code in ("MAJOR", "CRITICAL"))))
        self.cards["overdue"].setText(P(sum(1 for r in all_open if r.overdue)))
        self.cards["cost"].setText(numerals.format_money(sum((decimal.Decimal(r.cost_amount or 0) for r in all_open), _ZERO),
                                                         decimals.money_decimals(), None))
        self._selected_changed()

    def select(self, ncr_id: int) -> None:
        for i in range(self.t.rowCount()):
            if self.t.item(i, 0).data(Qt.UserRole) == ncr_id:
                self.t.selectRow(i)
                return

    def _row(self):
        nid = _selected(self.t)
        return next((r for r in self.rows if r.ncr_id == nid), None)

    def _need(self):
        r = self._row()
        if r is None:
            _warn(self, "عدم‌انطباق", "یک پرونده را انتخاب کنید.")
        return r

    def _selected_changed(self) -> None:
        r = self._row()
        if r is None:
            self.detail = None
            self.info.setText("")
            fill(self.t_actions, [])
            fill(self.t_history, [])
            return
        self.detail = ncr_service.get_ncr(company_id(), r.ncr_id)
        n = self.detail.ncr
        lines = [f"پرونده {n.ncr_no} — {n.title} ({c.SEVERITY_LABELS[n.severity_code]}، {c.NCR_STATUS_LABELS[n.status_code]})"]
        if n.description:
            lines.append(f"شرح: {n.description}")
        if n.root_cause_method:
            lines.append(f"روش تحلیل: {c.ROOT_CAUSE_METHOD_LABELS[n.root_cause_method]}")
        if isinstance(n.root_cause_details, list) and n.root_cause_details:
            lines += [f"چرای {i}: {x}" for i, x in enumerate(n.root_cause_details, start=1)]
        elif isinstance(n.root_cause_details, dict) and n.root_cause_details:
            lines += [f"{c.CAUSE_LABELS.get(k, k)}: {v}" for k, v in n.root_cause_details.items()]
        lines.append(f"علت ریشه‌ای: {n.root_cause or '— ثبت نشده'}")
        lines.append(f"تعیین تکلیف: {c.NCR_DISPOSITION_LABELS.get(n.disposition_code or '', '— تعیین نشده')}")
        if n.qc_inspection_id:
            lines.append(f"بازرسی مرتبط: {n.qc_inspection_id}")
        self.info.setText(P("\n".join(lines)))
        users = dict((uid, name) for name, uid in self.lk.users)
        fill(self.t_actions, [[c.CAPA_TYPE_LABELS[a.action_type], a.description, users.get(a.owner_user_id, ""), a.due_date,
                               c.CAPA_STATUS_LABELS[a.status_code], a.evidence or "", a.effectiveness_note or ""]
                              for a in self.detail.actions], [a.action_id for a in self.detail.actions])
        hist = sorted(self.detail.history, key=lambda x: x.at)
        fill(self.t_history, [[_date(x.at), x.user, _ACTION_LABELS.get(x.action, x.action),
                               ("اقدام: " if x.entity_type == "CapaAction" else "") + _changes_text(x.changes)] for x in hist])

    @staticmethod
    def create_from(parent, lk: _Lookups, prefill=None, qc_inspection_id: int | None = None) -> int | None:
        values = _ask(parent, "عدم‌انطباق جدید", _ncr_form(lk, prefill),
                      "پرونده با شمارهٔ پیاپی ثبت می‌شود؛ تغییر وضعیت، علت و اقدام‌ها در تاریخچه می‌ماند.")
        if values is None:
            return None
        if not values.get("title"):
            _warn(parent, "عدم‌انطباق", "عنوان پرونده را وارد کنید.")
            return None
        fields = ncr_service.NcrFields(
            title=values["title"], source_code=values.get("source_code") or "INTERNAL", severity_code=values.get("severity_code") or "MINOR",
            description=values.get("description"), item_id=values.get("item_id"),
            supplier_detail_account_id=values.get("supplier_detail_account_id"),
            customer_detail_account_id=values.get("customer_detail_account_id"),
            production_order_id=getattr(prefill, "production_order_id", None) if prefill else None,
            quantity=values.get("quantity") or _ZERO, cause_code=values.get("cause_code"),
            responsible_user_id=values.get("responsible_user_id"), cost_amount=values.get("cost_amount") or _ZERO,
            disposition_code=values.get("disposition_code"), due_date=values.get("due_date"))
        ncr_id, ok = _run(parent, "عدم‌انطباق", ncr_service.create_ncr, company_id(), user_id(), fields,
                          qc_inspection_id=qc_inspection_id)
        return ncr_id if ok else None

    def new_ncr(self) -> int | None:
        ncr_id = NcrScreen.create_from(self, self.lk)
        if ncr_id:
            self.reload()
            self.select(ncr_id)
        return ncr_id

    def edit_ncr(self) -> bool:
        r = self._need()
        if r is None or self.detail is None:
            return False
        n = self.detail.ncr
        values = _ask(self, f"پروندهٔ {P(n.ncr_no)}", _ncr_form(self.lk, n, edit=True),
                      "پروندهٔ بسته یا لغوشده قابل ویرایش نیست. برای پنج چرا هر خط یک پاسخ؛ برای استخوان ماهی هر خط «عامل: توضیح» "
                      "(عامل‌ها: " + "، ".join(c.CAUSE_LABELS.values()) + ").")
        if values is None:
            return False
        method = values.get("root_cause_method")
        values["root_cause_details"] = _parse_details(method, values.get("root_cause_details"))
        if values["root_cause_details"] is None:
            values.pop("root_cause_details")
        values = {k: v for k, v in values.items() if k in ncr_service._UPDATABLE}
        _r, ok = _run(self, "عدم‌انطباق", ncr_service.update_ncr, company_id(), user_id(), r.ncr_id, **values)
        if ok:
            self.reload()
            self.select(r.ncr_id)
        return ok

    def set_status(self, status: str) -> bool:
        r = self._need()
        if r is None:
            return False
        note = None
        if status == "CANCELLED":
            values = _ask(self, "لغو پرونده", [("note", "علت لغو", _text())])
            if values is None:
                return False
            note = values.get("note")
        elif status == "CLOSED" and not _confirm(self, "بستن پرونده", "پرونده بسته شود؟ پروندهٔ بسته دیگر قابل ویرایش نیست."):
            return False
        _r, ok = _run(self, "عدم‌انطباق", ncr_service.set_status, company_id(), user_id(), r.ncr_id, status, note)
        if ok:
            self.reload()
            self.select(r.ncr_id)
        return ok

    def add_action(self) -> int | None:
        r = self._need()
        if r is None:
            return None
        values = _ask(self, "اقدام جدید", [
            ("action_type", "نوع", combo([(v, k) for k, v in c.CAPA_TYPE_LABELS.items()])),
            ("description", "شرح اقدام", _text()),
            ("owner", "مسئول", combo(self.lk.users, "—")),
            ("due_date", "مهلت", date_field(datetime.date.today() + datetime.timedelta(days=14))),
        ])
        if values is None:
            return None
        action_id, ok = _run(self, "اقدام", ncr_service.add_action, company_id(), user_id(), r.ncr_id, values["action_type"],
                             values.get("description") or "", values.get("owner"), values.get("due_date"))
        if ok:
            self.reload()
            self.select(r.ncr_id)
        return action_id

    def _action(self):
        aid = _selected(self.t_actions)
        if aid is None:
            _warn(self, "اقدام", "یک اقدام را در فهرست اقدام‌های پرونده انتخاب کنید.")
        return aid

    def complete_action(self) -> bool:
        return _complete_action(self, self._action())

    def verify_action(self) -> bool:
        return _verify_action(self, self._action())

    def cancel_action(self) -> bool:
        return _cancel_action(self, self._action())


def _after_action(owner) -> None:
    owner.reload()
    if isinstance(owner, NcrScreen) and owner.detail is not None:
        owner.select(owner.detail.ncr.ncr_id)


def _complete_action(owner, action_id) -> bool:
    if action_id is None:
        return False
    values = _ask(owner, "ثبت انجام اقدام", [("evidence", "شواهد انجام (مدرک، شماره سند، نتیجهٔ آزمون)", _text(height=110))],
                  "اثربخشی را کاربر دیگری بررسی می‌کند (با کلید جداسازی ثبت و تأیید).")
    if values is None:
        return False
    _r, ok = _run(owner, "اقدام", ncr_service.complete_action, company_id(), user_id(), action_id, values.get("evidence") or "")
    if ok:
        _after_action(owner)
    return ok


def _verify_action(owner, action_id) -> bool:
    if action_id is None:
        return False
    values = _ask(owner, "بررسی اثربخشی", [
        ("effective", "نتیجه", combo([("اثربخش بود", True), ("اثربخش نبود", False)])),
        ("note", "توضیح بررسی", _text()),
    ], "اقدام بی‌اثر توضیح لازم دارد و پرونده تا اقدام اثربخش بسته نمی‌شود.")
    if values is None:
        return False
    _r, ok = _run(owner, "اقدام", ncr_service.verify_action, company_id(), user_id(), action_id, bool(values["effective"]),
                  values.get("note"))
    if ok:
        _after_action(owner)
    return ok


def _cancel_action(owner, action_id) -> bool:
    if action_id is None:
        return False
    values = _ask(owner, "لغو اقدام", [("reason", "علت لغو", _text())])
    if values is None:
        return False
    _r, ok = _run(owner, "اقدام", ncr_service.cancel_action, company_id(), user_id(), action_id, values.get("reason") or "")
    if ok:
        _after_action(owner)
    return ok


# =========================================================================================================
# اقدام اصلاحی و پیشگیرانه
# =========================================================================================================
@ms.styled
class CapaScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.rows: list = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        self.open_only = QCheckBox("فقط باز و منتظر بررسی")
        self.open_only.setChecked(True)
        self.mine = QCheckBox("فقط اقدام‌های من")
        for w in (self.open_only, self.mine):
            w.toggled.connect(lambda _c: self.reload())
        outer.addWidget(ms.header_card(_title("اقدام‌های اصلاحی و پیشگیرانه"), self.open_only, self.mine))
        cards, self.cards = ms.summary([("open", "اقدام باز", "info", "🛠️"), ("overdue", "گذشته از مهلت", "danger", "⏰"),
                                        ("done", "منتظر بررسی اثربخشی", "warning", "🎯"), ("verified", "اثربخش", "success", "✅")])
        outer.addWidget(cards)
        self.t = table(["پرونده", "عنوان پرونده", "نوع", "شرح", "مسئول", "مهلت", "وضعیت", "روز تأخیر", "شواهد"])
        outer.addWidget(self.t, stretch=1)
        b = _buttons(self, [("complete", "ثبت انجام اقدام", lambda: _complete_action(self, self._action())),
                            ("verify", "بررسی اثربخشی", lambda: _verify_action(self, self._action())),
                            ("cancel", "لغو اقدام", lambda: _cancel_action(self, self._action())),
                            ("ncr", "پروندهٔ عدم‌انطباق", self.open_ncr),
                            ("report", "گزارش کامل", lambda: _open_report(self._main_window, "QC_CAPA"))])
        outer.addWidget(ms.footer([[b["complete"], b["verify"], b["cancel"]], [b["ncr"], b["report"]]]))

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        uid = user_id()
        self.buttons["verify"].setEnabled(c.can(cid, uid, c.FORM_NCR))
        self.buttons["cancel"].setEnabled(c.can(cid, uid, c.FORM_NCR))
        self.reload()

    def reload(self) -> None:
        cid = company_id()
        if cid is None:
            return
        rows = ncr_service.list_actions(cid, open_only=self.open_only.isChecked())
        if self.mine.isChecked():
            rows = [a for a in rows if a.owner_user_id == user_id()]
        self.rows = rows
        fill(self.t, [[a.ncr_no, a.ncr_title, a.type_label, a.description, a.owner, a.due_date, a.status_label,
                       a.overdue_days or "", a.evidence or ""] for a in rows], [a.action_id for a in rows])
        for i, a in enumerate(rows):
            if a.overdue_days:
                self.t.item(i, 7).setForeground(_RED)
        every = ncr_service.list_actions(cid, open_only=False)
        self.cards["open"].setText(P(sum(1 for a in every if a.status_code == "OPEN")))
        self.cards["overdue"].setText(P(sum(1 for a in every if a.overdue_days)))
        self.cards["done"].setText(P(sum(1 for a in every if a.status_code == "DONE")))
        self.cards["verified"].setText(P(sum(1 for a in every if a.status_code == "VERIFIED")))

    def _action(self):
        aid = _selected(self.t)
        if aid is None:
            _warn(self, "اقدام", "یک اقدام را انتخاب کنید.")
        return aid

    def open_ncr(self) -> None:
        aid = _selected(self.t)
        a = next((x for x in self.rows if x.action_id == aid), None)
        if a is not None and self._main_window is not None:
            self._main_window.open_screen("QC_NCR", then=lambda s: (s.open_only.setChecked(False), s.select(a.ncr_id)))


# =========================================================================================================
# طرح‌های کیفیت
# =========================================================================================================
class PlanDialog(QDialog):
    """تعریف طرح کیفیت: دامنه (مرحله، کالا/گروه، تامین‌کننده، مرکز کاری/عملیات)، نمونه‌برداری، پذیرش و پارامترها."""

    _PARAM_HEADERS = ["نام پارامتر", "نوع", "واحد", "حداقل", "هدف", "حداکثر", "گزینه‌ها", "روش آزمون", "اجباری"]

    def __init__(self, lk: _Lookups, plan=None, params=(), parent=None) -> None:
        super().__init__(parent)
        from peecha.services.production import master as prd_master

        cid = company_id()
        self.setWindowTitle("طرح کیفیت" if plan is None else f"طرح {plan.code} — نسخهٔ {P(plan.version_no)}")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(900, 680)
        g = (lambda name, default=None: getattr(plan, name)) if plan else (lambda name, default=None: default)
        outer = QVBoxLayout(self)
        body = QWidget()
        form = QGridLayout(body)
        self.code = QLineEdit(g("code", "") or "")
        self.code.setEnabled(plan is None)
        self.name = QLineEdit(g("name", "") or "")
        self.stage = combo([(v, k) for k, v in c.STAGE_LABELS.items()])
        set_combo(self.stage, g("stage_code", "RECEIPT"))
        self.item = combo(lk.items, "— همهٔ کالاها —")
        set_combo(self.item, g("item_id"))
        self.category = combo(lk.categories, "— همهٔ گروه‌ها —")
        set_combo(self.category, g("category_id"))
        self.supplier = combo(lk.suppliers, "— همهٔ تامین‌کنندگان —")
        set_combo(self.supplier, g("supplier_detail_account_id"))
        self.work_center = combo([(f"{w.code} — {w.name}", w.work_center_id) for w in prd_master.list_work_centers(cid)], "—")
        set_combo(self.work_center, g("work_center_id"))
        self.operation = combo([(f"{o.code} — {o.name}", o.operation_id) for o in prd_master.list_operations(cid)], "—")
        set_combo(self.operation, g("operation_id"))
        self.sampling = combo([(v, k) for k, v in c.SAMPLING_LABELS.items()])
        set_combo(self.sampling, g("sampling_method", "FULL"))
        self.sample_size = num_field(g("sample_size"))
        self.sample_percent = num_field(g("sample_percent"))
        self.acceptance = QSpinBox()
        self.acceptance.setRange(0, 100000)
        self.acceptance.setValue(int(g("acceptance_number", 0) or 0))
        self.mandatory = QCheckBox("بازرسی اجباری است")
        self.mandatory.setChecked(bool(g("is_mandatory", True)))
        self.valid_from = JalaliDateEdit()
        self.valid_from.setDate(g("valid_from") or datetime.date.today())
        self.has_end = QCheckBox("تاریخ پایان دارد")
        self.valid_to = JalaliDateEdit()
        self.valid_to.setDate(g("valid_to") or datetime.date.today() + datetime.timedelta(days=365))
        self.has_end.setChecked(g("valid_to") is not None)
        self.notes = _text(g("notes"), 60)
        cells = [("کد", self.code), ("نام", self.name), ("مرحله", self.stage), ("کالا", self.item), ("گروه کالا", self.category),
                 ("تامین‌کننده", self.supplier), ("مرکز کاری", self.work_center), ("عملیات", self.operation),
                 ("روش نمونه‌برداری", self.sampling), ("تعداد نمونه", self.sample_size), ("درصد نمونه", self.sample_percent),
                 ("عدد پذیرش (حداکثر نمونهٔ معیوب)", self.acceptance), ("اعتبار از", self.valid_from), ("اعتبار تا", self.valid_to)]
        for i, (label, w) in enumerate(cells):
            form.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            form.addWidget(w, i // 2, (i % 2) * 2 + 1)
        row = len(cells) // 2 + 1
        form.addWidget(self.mandatory, row, 1)
        form.addWidget(self.has_end, row, 3)
        form.addWidget(QLabel("توضیح"), row + 1, 0)
        form.addWidget(self.notes, row + 1, 1, 1, 3)
        outer.addWidget(scrolled(body, 330))
        outer.addWidget(_hint("گزینه‌ها برای پارامتر گزینه‌ای با «،» جدا می‌شوند؛ گزینهٔ نامنطبق را با «رد:» شروع کنید "
                              "(مثلاً «سالم، خراش جزئی، رد: شکسته»). حدود بازرسی‌های قبلی با ویرایش طرح تغییر نمی‌کند."))
        self.params = QTableWidget(0, len(self._PARAM_HEADERS))
        self.params.setHorizontalHeaderLabels(self._PARAM_HEADERS)
        self.params.verticalHeader().setVisible(False)
        self.params.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.params, stretch=1)
        for p in params:
            self.add_param(p)
        bar = QHBoxLayout()
        for text, slot in (("افزودن پارامتر", self.add_param), ("حذف پارامتر", self.remove_param)):
            b = ms.style_button(QPushButton(text))
            b.clicked.connect(lambda _c=False, f=slot: f())
            bar.addWidget(b)
        bar.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        bar.addWidget(box)
        outer.addLayout(bar)

    def add_param(self, p=None) -> int:
        r = self.params.rowCount()
        self.params.insertRow(r)
        g = (lambda name, default=None: getattr(p, name, default)) if p else (lambda name, default=None: default)
        kind = combo([(v, k) for k, v in c.DATA_TYPE_LABELS.items()])
        set_combo(kind, g("data_type", "NUMERIC"))
        self.params.setCellWidget(r, 1, kind)
        opts = g("options") or []
        opt_text = "، ".join((o["value"] if o.get("ok", True) else f"رد: {o['value']}") if isinstance(o, dict) else str(o) for o in opts)
        for col, value in ((0, g("name", "")), (2, g("uom_label", "")), (3, g("min_value")), (4, g("target_value")),
                           (5, g("max_value")), (6, opt_text), (7, g("test_method", ""))):
            text = decimals.plain(value) if isinstance(value, decimal.Decimal) else ("" if value is None else str(value))
            self.params.setItem(r, col, QTableWidgetItem(P(text) if col in (3, 4, 5) else text))
        check = QTableWidgetItem("")
        check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        check.setCheckState(Qt.Checked if g("is_mandatory", True) else Qt.Unchecked)
        self.params.setItem(r, 8, check)
        return r

    def remove_param(self) -> None:
        r = self.params.currentRow()
        if r >= 0:
            self.params.removeRow(r)

    def set_param(self, row: int, **values) -> None:
        """برای آزمون: مقدار ستون‌های پارامتر."""
        cols = {"name": 0, "uom_label": 2, "min_value": 3, "target_value": 4, "max_value": 5, "options": 6, "test_method": 7}
        for key, value in values.items():
            if key == "data_type":
                set_combo(self.params.cellWidget(row, 1), value)
            elif key == "is_mandatory":
                self.params.item(row, 8).setCheckState(Qt.Checked if value else Qt.Unchecked)
            else:
                self.params.item(row, cols[key]).setText(str(value))

    def _cell(self, r: int, col: int) -> str:
        item = self.params.item(r, col)
        return item.text().strip() if item else ""

    def fields(self) -> tuple[plan_service.PlanFields, list[plan_service.ParameterFields]]:
        def num(text):
            text = numerals.to_ascii_digits((text or "").replace(",", "").replace("٬", "").strip())
            return decimal.Decimal(text) if text else None

        f = plan_service.PlanFields(
            code=self.code.text().strip(), name=self.name.text().strip(), stage_code=self.stage.currentData(),
            item_id=self.item.currentData(), category_id=self.category.currentData(),
            supplier_detail_account_id=self.supplier.currentData(), work_center_id=self.work_center.currentData(),
            operation_id=self.operation.currentData(), sampling_method=self.sampling.currentData(),
            sample_size=dec(self.sample_size.text()) if self.sample_size.text().strip() else None,
            sample_percent=dec(self.sample_percent.text()) if self.sample_percent.text().strip() else None,
            acceptance_number=self.acceptance.value(), is_mandatory=self.mandatory.isChecked(), valid_from=self.valid_from.date(),
            valid_to=self.valid_to.date() if self.has_end.isChecked() else None, notes=self.notes.toPlainText().strip() or None)
        params = []
        for r in range(self.params.rowCount()):
            options = []
            for raw in self._cell(r, 6).replace(",", "،").split("،"):
                raw = raw.strip()
                if not raw:
                    continue
                if raw.startswith("رد:"):
                    options.append({"value": raw[3:].strip(), "ok": False})
                else:
                    options.append({"value": raw, "ok": True})
            params.append(plan_service.ParameterFields(
                name=self._cell(r, 0), data_type=self.params.cellWidget(r, 1).currentData(), uom_label=self._cell(r, 2) or None,
                min_value=num(self._cell(r, 3)), target_value=num(self._cell(r, 4)), max_value=num(self._cell(r, 5)),
                options=options, test_method=self._cell(r, 7) or None,
                is_mandatory=self.params.item(r, 8).checkState() == Qt.Checked))
        return f, params


@ms.styled
class PlansScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.rows: list = []
        self.lk: _Lookups | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        self.stage = combo([(v, k) for k, v in c.STAGE_LABELS.items()], "همهٔ مرحله‌ها")
        self.status = combo([(v, k) for k, v in c.PLAN_STATUS_LABELS.items()], "همهٔ وضعیت‌ها")
        for w in (self.stage, self.status):
            w.currentIndexChanged.connect(lambda _i: self.reload())
        outer.addWidget(ms.header_card(_title("طرح‌های کنترل کیفیت"), self.stage, self.status))
        outer.addWidget(_hint("هر طرح نسخه دارد: طرح فعال ویرایش نمی‌شود؛ «نسخهٔ جدید» پیش‌نویس می‌سازد و با فعال‌سازی، نسخهٔ قبلی "
                              "بایگانی می‌شود. هنگام بازرسی دقیق‌ترین طرح فعال (کالا، گروه، تامین‌کننده، مرکز کاری) انتخاب می‌شود."))
        split = QSplitter(Qt.Horizontal)
        self.t = table(["کد", "نسخه", "نام", "مرحله", "وضعیت", "دامنه", "نمونه‌برداری", "پارامتر", "اجباری", "از", "تا"])
        self.t.itemSelectionChanged.connect(self._selected_changed)
        self.t.cellDoubleClicked.connect(lambda _r, _c: self.edit_plan())
        split.addWidget(self.t)
        self.t_params = table(["ردیف", "پارامتر", "نوع", "واحد", "حداقل", "هدف", "حداکثر", "گزینه‌ها", "روش آزمون", "اجباری"])
        split.addWidget(self.t_params)
        split.setSizes([700, 560])
        outer.addWidget(split, stretch=1)
        b = _buttons(self, [("new", "طرح جدید", self.new_plan), ("edit", "ویرایش طرح", self.edit_plan),
                            ("version", "نسخهٔ جدید", self.new_version), ("activate", "فعال‌سازی طرح", self.activate),
                            ("deactivate", "غیرفعال‌سازی طرح", self.deactivate)])
        outer.addWidget(ms.footer([[b["new"], b["edit"], b["version"]], [b["activate"], b["deactivate"]]]))

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.lk = _Lookups(cid)
        allowed = c.can(cid, user_id(), c.FORM_MANAGE) and can("qc_plans", "EDIT")
        for b in self.buttons.values():
            b.setEnabled(allowed)
        self.reload()

    def reload(self) -> None:
        cid = company_id()
        if cid is None or self.lk is None:
            return
        items = dict((v, k) for k, v in self.lk.items)
        cats = dict((v, k) for k, v in self.lk.categories)
        sups = dict((v, k) for k, v in self.lk.suppliers)
        stage = self.stage.currentData()
        self.rows = [p for p in plan_service.list_plans(cid, self.status.currentData()) if stage is None or p.stage_code == stage]

        def scope(p) -> str:
            parts = [items.get(p.item_id, ""), cats.get(p.category_id, ""), sups.get(p.supplier_id, "")]
            if p.work_center_id:
                parts.append("مرکز کاری")
            if p.operation_id:
                parts.append("عملیات")
            return "، ".join(x for x in parts if x) or "همه"

        fill(self.t, [[p.code, p.version_no, p.name, p.stage_label, p.status_label, scope(p), p.sampling_label, p.parameters,
                       "بله" if p.is_mandatory else "خیر", p.valid_from, p.valid_to] for p in self.rows],
             [p.plan_id for p in self.rows])
        for i, p in enumerate(self.rows):
            if p.status_code == "ACTIVE":
                self.t.item(i, 4).setForeground(_GREEN)
        self._selected_changed()

    def select(self, plan_id: int) -> None:
        for i in range(self.t.rowCount()):
            if self.t.item(i, 0).data(Qt.UserRole) == plan_id:
                self.t.selectRow(i)
                return

    def _selected_changed(self) -> None:
        pid = _selected(self.t)
        if pid is None:
            fill(self.t_params, [])
            return
        got = plan_service.get_plan(company_id(), pid)

        def opts(p):
            return "، ".join(o["value"] + ("" if o.get("ok", True) else " (نامنطبق)") for o in (p.options or []))

        fill(self.t_params, [[p.seq, p.name, c.DATA_TYPE_LABELS[p.data_type], p.uom_label or "",
                              decimals.plain(p.min_value) if p.min_value is not None else "",
                              decimals.plain(p.target_value) if p.target_value is not None else "",
                              decimals.plain(p.max_value) if p.max_value is not None else "", opts(p), p.test_method or "",
                              "بله" if p.is_mandatory else "خیر"] for p in got.parameters])

    def _dialog(self, plan=None, params=()) -> PlanDialog | None:
        dlg = PlanDialog(self.lk, plan, params, self)
        return dlg if _exec(self, dlg) else None

    def new_plan(self) -> int | None:
        dlg = self._dialog()
        if dlg is None:
            return None
        f, params = dlg.fields()
        plan_id, ok = _run(self, "طرح کیفیت", plan_service.create_plan, company_id(), user_id(), f, params)
        if ok:
            self.reload()
            self.select(plan_id)
        return plan_id

    def edit_plan(self) -> bool:
        pid = _selected(self.t)
        if pid is None:
            _warn(self, "طرح کیفیت", "یک طرح را انتخاب کنید.")
            return False
        got = plan_service.get_plan(company_id(), pid)
        if got.plan.status_code != "DRAFT":
            _warn(self, "طرح کیفیت", "فقط پیش‌نویس ویرایش می‌شود؛ برای تغییر طرح فعال «نسخهٔ جدید» بسازید.")
            return False
        dlg = self._dialog(got.plan, got.parameters)
        if dlg is None:
            return False
        f, params = dlg.fields()
        _r, ok = _run(self, "طرح کیفیت", plan_service.update_plan, company_id(), user_id(), pid, f, params)
        if ok:
            self.reload()
            self.select(pid)
        return ok

    def _act(self, fn, title: str):
        pid = _selected(self.t)
        if pid is None:
            _warn(self, title, "یک طرح را انتخاب کنید.")
            return None, False
        result, ok = _run(self, title, fn, company_id(), user_id(), pid)
        if ok:
            self.reload()
            self.select(result if isinstance(result, int) else pid)
        return result, ok

    def new_version(self) -> int | None:
        result, ok = self._act(plan_service.new_version, "نسخهٔ جدید")
        return result if ok else None

    def activate(self) -> bool:
        return self._act(plan_service.activate_plan, "فعال‌سازی طرح")[1]

    def deactivate(self) -> bool:
        return self._act(plan_service.deactivate_plan, "غیرفعال‌سازی طرح")[1]


# =========================================================================================================
# کارت کیفیت کالا و تامین‌کننده
# =========================================================================================================
@ms.styled
class QualityCardsScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.scores: list = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        self.as_of = JalaliDateEdit()
        self.as_of.setDate(datetime.date.today())
        self.supplier = combo([], "همهٔ تامین‌کنندگان")
        refresh = ms.style_button(QPushButton("به‌روزرسانی"))
        refresh.clicked.connect(lambda _c=False: self.reload())
        outer.addWidget(ms.header_card(_title("کارت کیفیت کالا و تامین‌کننده"), QLabel("تا تاریخ:"), self.as_of, self.supplier, refresh))
        self.formula = _hint("")
        outer.addWidget(self.formula)
        self.tabs = QTabWidget()
        w = QWidget()
        lay = QVBoxLayout(w)
        self.t_supplier = table([])
        self.t_supplier.itemSelectionChanged.connect(self._explain)
        lay.addWidget(self.t_supplier, stretch=2)
        self.explain = _hint("")
        lay.addWidget(self.explain)
        b = _buttons(self, [("supplier_report", "گزارش کامل",
                             lambda: _open_report(self._main_window, "QC_SUPPLIER_CARD", None, self.as_of.date()))])
        lay.addWidget(ms.footer([[b["supplier_report"]]]))
        self.tabs.addTab(w, "کارت تامین‌کننده")
        w = QWidget()
        lay = QVBoxLayout(w)
        self.t_item = table([])
        lay.addWidget(self.t_item, stretch=1)
        item_report = QPushButton("گزارش کامل")
        item_report.clicked.connect(lambda _c=False: _open_report(self._main_window, "QC_ITEM_CARD", *self._range()))
        self.buttons["item_report"] = item_report
        lay.addWidget(ms.footer([[item_report]]))
        self.tabs.addTab(w, "کارت کالا")
        outer.addWidget(self.tabs, stretch=1)

    def _range(self):
        cid = company_id()
        days = int(c.settings(cid).score_window_days) if cid else 365
        return self.as_of.date() - datetime.timedelta(days=days), self.as_of.date()

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        from peecha.services import detail_dimensions as dims

        current = self.supplier.currentData()
        self.supplier.blockSignals(True)
        self.supplier.clear()
        self.supplier.addItem("همهٔ تامین‌کنندگان", None)
        for s in dims.list_suppliers(cid):
            self.supplier.addItem(P(f"{s['code']} — {s['name'] or ''}"), s["detail_account_id"])
        set_combo(self.supplier, current)
        self.supplier.blockSignals(False)
        self.reload()

    def reload(self) -> None:
        from peecha.services.purchase_reports import PurchaseFilters
        from peecha.services.qms import reports, scoring

        cid = company_id()
        if cid is None:
            return
        st = c.settings(cid)
        self.formula.setText(P(scoring.formula_text(st)))
        date_from, date_to = self._range()
        f = PurchaseFilters(date_from, date_to, supplier_id=self.supplier.currentData(), side="INVENTORY")
        self.supplier_result = reports.supplier_card(cid, f)
        _fill_result(self.t_supplier, self.supplier_result)
        self.scores = scoring.supplier_scores(cid, as_of=date_to, supplier_id=self.supplier.currentData())
        for i, s in enumerate(self.scores):
            self.t_supplier.item(i, 0).setData(Qt.UserRole, s.supplier_id)
        self.item_result = reports.item_card(cid, PurchaseFilters(date_from, date_to, side="INVENTORY", options={"stage": "ALL"}))
        _fill_result(self.t_item, self.item_result)
        self._explain()

    def _explain(self) -> None:
        sid = _selected(self.t_supplier)
        s = next((x for x in self.scores if x.supplier_id == sid), None)
        if s is None:
            self.explain.setText("یک تامین‌کننده را انتخاب کنید تا امتیاز هر شاخص و منبع آن دیده شود.")
            return
        names = {"reject": "مردودی بازرسی", "return": "برگشت خرید", "ncr": "عدم‌انطباق", "delay": "تأخیر رسیدگی", "trend": "روند مردودی"}
        st = c.settings(company_id())
        weights = {"reject": st.weight_reject, "return": st.weight_return, "ncr": st.weight_ncr, "delay": st.weight_delay,
                   "trend": st.weight_trend}
        parts = [f"{names[k]}: {('بدون داده' if v is None else decimals.plain(v.quantize(decimal.Decimal('0.1'))))} "
                 f"(وزن {decimals.plain(weights[k])})" for k, v in s.sub_scores.items()]
        source = (f"منبع: {s.inspections} بازرسی تأییدشده با {_qty(s.inspected_qty)} واحد (مردود {_qty(s.rejected_qty)})، "
                  f"خرید {_qty(s.purchased_qty)} و برگشت {_qty(s.returned_qty)}، {s.ncr_count} پروندهٔ عدم‌انطباق — "
                  f"بازه {numerals.format_jalali_date(s.date_from)} تا {numerals.format_jalali_date(s.date_to)}.")
        self.explain.setText(P(f"{s.supplier_label}: " + " • ".join(parts) + "\n" + source + ("\n" + s.note if s.note else "")))


# =========================================================================================================
# داشبورد
# =========================================================================================================
def _dashboard_base():
    from peecha.ui.screens.purchase_dashboards import _ProcurementDashboardBase

    return _ProcurementDashboardBase


class QcDashboardScreen(_dashboard_base()):
    TITLE = "داشبورد کیفیت"
    _KPI_STYLE = {"WAITING": ("🧪", "WARNING"), "AWAITING": ("🛡", "ACCENT"), "INSPECTIONS": ("📋", "ACCENT"),
                  "ACCEPT_RATE": ("✔", "SUCCESS"), "REJECT_RATE": ("✖", "DANGER"), "REWORK": ("🔁", "CHART_ORANGE"),
                  "CONCESSION": ("⚖", "CHART_PURPLE"), "NCR_OPEN": ("📂", "WARNING"), "NCR_CRITICAL": ("⚠", "DANGER"),
                  "CAPA_OVERDUE": ("⏰", "DANGER"), "QUARANTINE": ("🚧", "CHART_TEAL"), "NCR_COST": ("💸", "CHART_ORANGE"),
                  "DELAY": ("⏱", "ACCENT")}

    def __init__(self, main_window=None) -> None:
        super().__init__(main_window)
        from peecha.ui.screens.dashboard import build_chart_card
        from peecha.ui.screens.purchase_dashboards import _ClickableKpiCard
        from peecha.services.qms import dashboard as qdash

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
        for i, (key, chart_title, _report, _options) in enumerate(qdash.CHART_TITLES):
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

    def open_report(self, report_code: str, options: dict | None = None) -> None:
        _open_report(self._main_window, report_code, self.date_from.date(), self.date_to.date(), options)

    def _open_kpi(self, code: str) -> None:
        kpi = self._kpis.get(code)
        if kpi is not None:
            self.open_report(kpi.report_code, kpi.options)

    def _open_alert(self, row: int, _col: int) -> None:
        if self._main_window is None or row >= len(self._alerts):
            return
        kind = self._alerts[row].ref[0]
        target = {"NCR": "QC_NCR", "LINE": "QC_QUEUE", "QUEUE": "QC_QUEUE", "WH": "QC_QUARANTINE_STOCK"}[kind]
        self._main_window.open_screen(target)

    def reload(self) -> None:
        from peecha.services.qms import dashboard as qdash
        from peecha.ui.screens.dashboard import render_donut_chart
        from peecha.ui.screens.purchase_dashboards import format_kpi
        from peecha.ui.screens.warehouse_dashboard import render_series_chart

        cid = self._company_id()
        if cid is None:
            return
        kpis, charts, alerts = qdash.dashboard(cid, self.date_from.date(), self.date_to.date())
        self._kpis = {k.code: k for k in kpis}
        for code, kpi in self._kpis.items():
            card = self.cards[code]
            card._title_label.setText(kpi.title)
            card.set_value(format_kpi(kpi.value, kpi.kind, decimals.money_decimals()))
            card.setToolTip(f"فرمول: {kpi.formula}\nکلیک: گزارش مبدا")
        self._alerts = alerts
        level = {"RED": "🔴", "YELLOW": "🟡", "ORANGE": "🟠"}
        fill(self.alerts_table, [[level[qdash.ALERT_LEVEL[a.kind]] + " " + qdash.ALERT_LABELS[a.kind], qdash.ALERT_LABELS[a.kind], a.text]
                                 for a in alerts])
        for key, data in charts.items():
            if data["kind"] == "donut":
                render_donut_chart(self.chart_views[key], [(P(lb), v) for lb, v in zip(data["labels"], data["series"]["تعداد"]) if v])
            else:
                render_series_chart(self.chart_views[key], [P(x) for x in data["labels"]], data["series"])


# =========================================================================================================
# تنظیمات
# =========================================================================================================
_QC_TOGGLES = (stock_controls.QC_HOLD, stock_controls.QC_SEPARATE_APPROVAL, stock_controls.QC_QUARANTINE_LOCK,
               stock_controls.QC_PRODUCTION, stock_controls.QC_SALES_RETURN, stock_controls.QC_ROLE_PERMISSIONS)


@ms.styled
class QcSettingsScreen(FieldHelpMixin, QWidget):
    """کلیدهای کیفیت (همان قابلیت‌های فعال انبار) + وزن‌ها و حداقل نمونهٔ امتیاز تامین‌کننده."""

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.addWidget(_title("تنظیمات کنترل کیفیت"))
        outer.addWidget(_hint("همهٔ امکانات کیفیت پیش‌فرض خاموش‌اند؛ تا روشن نشوند رفتار رسید و تولید مثل قبل است. "
                              "این کلیدها همان «قابلیت‌های فعال › کیفیت» در تنظیمات انبار هستند."))
        self.toggles: dict[str, QCheckBox] = {}
        self.toggle_box = QWidget()
        self.toggle_layout = QVBoxLayout(self.toggle_box)
        self.toggle_layout.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.toggle_box)
        sep = QLabel("امتیاز کیفیت تامین‌کننده")
        sep.setObjectName("sectionTitle")
        outer.addWidget(sep)
        form = QFormLayout()
        self.window_days = QSpinBox()
        self.window_days.setRange(1, 3650)
        self.min_samples = QSpinBox()
        self.min_samples.setRange(1, 10000)
        self.weights = {k: num_field() for k in ("weight_reject", "weight_return", "weight_ncr", "weight_delay", "weight_trend")}
        self.target_days = num_field()
        self.auto_ncr = QCheckBox("برای هر بازرسی دارای مقدار مردود، پروندهٔ عدم‌انطباق خودکار ساخته شود")
        form.addRow("بازهٔ محاسبه (روز)", self.window_days)
        form.addRow("حداقل تعداد بازرسی برای امتیاز", self.min_samples)
        for key, label in (("weight_reject", "وزن نرخ مردودی"), ("weight_return", "وزن نرخ برگشت خرید"),
                           ("weight_ncr", "وزن عدم‌انطباق"), ("weight_delay", "وزن تأخیر رسیدگی"), ("weight_trend", "وزن روند مردودی")):
            form.addRow(label, self.weights[key])
        form.addRow("مهلت هدف رسیدگی (روز)", self.target_days)
        form.addRow("", self.auto_ncr)
        outer.addLayout(form)
        self.formula = _hint("")
        outer.addWidget(self.formula)
        self.set_field_help([
            (self.window_days, "امتیاز فقط از بازرسی‌ها، برگشت‌های خرید و عدم‌انطباق‌های همین تعداد روز اخیر حساب می‌شود."),
            (self.min_samples, "تامین‌کننده‌ای که کمتر از این تعداد بازرسی تأییدشده دارد امتیاز نمی‌گیرد و «داده ناکافی» نشان داده می‌شود."),
            (self.weights["weight_reject"], "سهم نرخ مردودی بازرسی رسید در امتیاز. صفر یعنی این شاخص حساب نشود."),
            (self.weights["weight_return"], "سهم نرخ برگشت خرید (مقدار برگشتی ÷ مقدار خرید) در امتیاز."),
            (self.weights["weight_ncr"], "سهم تعداد عدم‌انطباق به ازای هر بازرسی در امتیاز."),
            (self.weights["weight_delay"], "سهم فاصلهٔ ثبت رسید تا تأیید بازرسی در امتیاز؛ تا مهلت هدف امتیاز کامل است."),
            (self.weights["weight_trend"], "سهم بهتر یا بدتر شدن نرخ مردودی نیمهٔ دوم بازه نسبت به نیمهٔ اول."),
            (self.target_days, "رسیدگی تا این تعداد روز امتیاز کامل تأخیر را می‌گیرد؛ بعد از آن کم‌کم کم می‌شود."),
            (self.auto_ncr, "با هر تأیید بازرسی که مقدار مردود دارد، یک پروندهٔ عدم‌انطباق با مقدار و هزینهٔ برآوردی ساخته می‌شود."),
        ])
        self.save_btn = QPushButton("ذخیرهٔ تنظیمات کیفیت")
        self.save_btn.clicked.connect(lambda _c=False: self.save())
        outer.addWidget(ms.footer([[self.save_btn]]))
        outer.addStretch(1)

    def refresh(self) -> None:
        from peecha.services import inventory_engine as engine
        from peecha.services.qms import scoring

        cid = company_id()
        if cid is None:
            return
        st = c.settings(cid)
        self.window_days.setValue(int(st.score_window_days))
        self.min_samples.setValue(int(st.score_min_samples))
        for key, w in self.weights.items():
            w.setText(decimals.plain(decimal.Decimal(getattr(st, key))))
        self.target_days.setText(decimals.plain(decimal.Decimal(st.target_handling_days)))
        self.auto_ncr.setChecked(bool(st.auto_ncr_on_reject))
        self.formula.setText(P(scoring.formula_text(st)))
        allowed = c.can(cid, user_id(), c.FORM_MANAGE) and can("qc_settings", "EDIT")
        self.save_btn.setEnabled(allowed)
        features = {f.feature_code: f for f in engine.list_features(cid)}
        descriptions = engine.feature_descriptions()
        while self.toggle_layout.count():
            w = self.toggle_layout.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.toggles = {}
        for code in _QC_TOGGLES:
            f = features.get(code)
            if f is None:
                continue
            box = QCheckBox(f.name)
            box.setChecked(f.is_enabled)
            box.setEnabled(allowed)
            box.toggled.connect(lambda checked, k=code: self._toggle(k, checked))
            self.toggles[code] = box
            self.toggle_layout.addWidget(box)
            note = _hint(descriptions.get(code, ""))
            self.toggle_layout.addWidget(note)

    def _toggle(self, code: str, checked: bool) -> None:
        from peecha.services import inventory_engine as engine

        _r, ok = _run(self, "تنظیمات کیفیت", engine.set_feature_enabled, company_id(), code, checked)
        if not ok:
            box = self.toggles[code]
            box.blockSignals(True)
            box.setChecked(not checked)
            box.blockSignals(False)

    def save(self) -> bool:
        values = {"score_window_days": self.window_days.value(), "score_min_samples": self.min_samples.value(),
                  "target_handling_days": dec(self.target_days.text()), "auto_ncr_on_reject": self.auto_ncr.isChecked()}
        values.update({k: dec(w.text()) for k, w in self.weights.items()})
        _r, ok = _run(self, "تنظیمات کیفیت", c.save_settings, company_id(), user_id(), **values)
        if ok:
            self.refresh()
        return ok
