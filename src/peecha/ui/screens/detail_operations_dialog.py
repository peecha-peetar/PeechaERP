"""R318: دیالوگ «انتقال مانده و ادغام» برای تفصیلی درحال‌ویرایش در فرم تعریف تفصیلی.

سه زبانه: انتقال مانده با سند، ادغام کامل گردش، و سابقه (با برگشت). هر زبانه با کلید و دسترسی خودش فعال می‌شود."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from peecha.services import detail_operations as ops
from peecha.ui import theme
from peecha.ui.screens import module_style as ms
from peecha.ui.screens.fixed_assets import P, combo, date_field, fill, money, selected_data, table


def _icon_button(glyph: str, tip: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setObjectName(ms._OBJECT_NAMES[kind])
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setToolTip(tip)
    button.setAccessibleName(tip)
    return button


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionHint")
    label.setWordWrap(True)
    return label


class DetailOperationsDialog(QDialog):
    def __init__(self, company_id: int, user_id: int | None, detail_account_id: int, label: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("انتقال مانده و ادغام تفصیلی")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(860, 600)
        self.cid, self.uid, self.detail_id, self.label = company_id, user_id, detail_account_id, label
        self.confirm = lambda text: QMessageBox.question(self, "تفصیلی", text) == QMessageBox.Yes
        self.changed = False
        outer = QVBoxLayout(self)
        title = QLabel(P(f"تفصیلی مبدأ: {label}"))
        title.setObjectName("sectionTitle")
        outer.addWidget(title)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, stretch=1)
        targets = ops.candidates(company_id, detail_account_id)
        self.tabs.addTab(self._build_transfer_tab(targets), "انتقال مانده با سند")
        self.tabs.addTab(self._build_merge_tab(targets), "ادغام کامل")
        self.tabs.addTab(self._build_history_tab(), "سابقه")
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)
        self.reload_balances()
        self.reload_history()

    # --- انتقال مانده -------------------------------------------------------------------------------
    def _build_transfer_tab(self, targets) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        on = ops.is_on(self.cid, ops.FEATURE_TRANSFER)
        allowed = ops.can(self.cid, self.uid, ops.FORM_TRANSFER)
        lay.addWidget(_hint("ماندهٔ این تفصیلی تا تاریخ سند، به تفکیک حساب، ارز و تفصیلی‌های همراه، با یک سند حسابداری به "
                            "تفصیلی مقصد می‌رود. سوابق قبلی دست نمی‌خورد و از زبانهٔ «سابقه» قابل برگشت است."))
        self.transfer_target = combo(targets, "— تفصیلی مقصد —")
        self.transfer_date = date_field()
        self.transfer_date.editingFinished.connect(self.reload_balances)
        self.transfer_memo = QLineEdit()
        self.transfer_memo.setPlaceholderText("خالی = شرح خودکار")
        self.transfer_button = _icon_button("🔀", "صدور سند انتقال مانده", "primary")
        self.transfer_button.clicked.connect(self.do_transfer)
        lay.addWidget(ms.field_grid([("تفصیلی مقصد", self.transfer_target), ("تاریخ سند", self.transfer_date),
                                     ("شرح سند", self.transfer_memo)], columns=3, tail=[self.transfer_button]))
        self.balance_table = table(["حساب", "ارز", "تفصیلی‌های همراه", "بدهکار", "بستانکار"])
        lay.addWidget(self.balance_table, stretch=1)
        if not (on and allowed):
            lay.addWidget(_hint("این قابلیت در «تنظیمات › کدینگ حسابداری › قابلیت‌های تفصیلی» خاموش است." if not on else
                                f"دسترسی «{ops.FORM_LABELS[ops.FORM_TRANSFER]}» را ندارید."))
        for w in (self.transfer_target, self.transfer_date, self.transfer_memo, self.transfer_button):
            w.setEnabled(on and allowed)
        return page

    def reload_balances(self) -> None:
        try:
            rows = ops.balances(self.cid, self.detail_id, self.transfer_date.date())
        except ValueError:
            rows = []
        fill(self.balance_table, [[r.account_label, r.currency_code, r.others_label or "—",
                                   r.balance_base if r.balance_base > 0 else "",
                                   -r.balance_base if r.balance_base < 0 else ""] for r in rows])
        self.balance_table.resizeColumnsToContents()
        self.transfer_rows = rows

    def do_transfer(self) -> int | None:
        target = self.transfer_target.currentData()
        if target is None:
            self._status("تفصیلی مقصد را انتخاب کنید.", ok=False)
            return None
        text = P(f"ماندهٔ «{self.label}» با سند به «{self.transfer_target.currentText()}» منتقل شود؟")
        if not self.confirm(text):
            return None
        try:
            res = ops.transfer_balance(self.cid, self.uid, self.detail_id, target, self.transfer_date.date(),
                                       self.transfer_memo.text())
        except ValueError as exc:
            self._status(str(exc), ok=False)
            return None
        self.changed = True
        self._status(P(f"سند انتقال مانده صادر شد ({res.line_count} ردیف)."), ok=True)
        self.reload_balances()
        self.reload_history()
        return res.operation_id

    # --- ادغام ---------------------------------------------------------------------------------------
    def _build_merge_tab(self, targets) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        on = ops.is_on(self.cid, ops.FEATURE_MERGE)
        allowed = ops.can(self.cid, self.uid, ops.FORM_MERGE)
        lay.addWidget(_hint("همهٔ گردش و سوابق این تفصیلی (ردیف‌های سند، اسناد خرید و فروش، چک‌ها، آدرس‌ها و ...) به مقصد "
                            "می‌رود و این تفصیلی غیرفعال می‌شود. اطلاعات یک‌به‌یکی که مقصد هم دارد (مثل پروندهٔ مشتری) "
                            "روی همین تفصیلی می‌ماند. ادغام از زبانهٔ «سابقه» کاملاً قابل برگشت است."))
        self.merge_target = combo(targets, "— تفصیلی مقصد —")
        self.merge_reason = QLineEdit()
        self.merge_reason.setPlaceholderText("مثلاً: مشتری تکراری")
        self.preview_button = _icon_button("👁️", "پیش‌نمایش آنچه جابه‌جا می‌شود")
        self.preview_button.clicked.connect(self.preview_merge)
        self.merge_button = _icon_button("🧬", "ادغام کامل", "danger")
        self.merge_button.clicked.connect(self.do_merge)
        lay.addWidget(ms.field_grid([("تفصیلی مقصد", self.merge_target), ("علت ادغام", self.merge_reason)], columns=2,
                                    tail=[self.preview_button, self.merge_button]))
        self.preview_table = table(["بخش", "تعداد ردیف"])
        lay.addWidget(self.preview_table, stretch=1)
        self.preview_note = _hint("")
        lay.addWidget(self.preview_note)
        if not (on and allowed):
            lay.addWidget(_hint("این قابلیت در «تنظیمات › کدینگ حسابداری › قابلیت‌های تفصیلی» خاموش است." if not on else
                                f"دسترسی «{ops.FORM_LABELS[ops.FORM_MERGE]}» را ندارید."))
        for w in (self.merge_target, self.merge_reason, self.preview_button, self.merge_button):
            w.setEnabled(on and allowed)
        return page

    def preview_merge(self):
        target = self.merge_target.currentData()
        if target is None:
            self._status("تفصیلی مقصد را انتخاب کنید.", ok=False)
            return None
        try:
            pv = ops.merge_preview(self.cid, self.detail_id, target)
        except ValueError as exc:
            self._status(str(exc), ok=False)
            return None
        fill(self.preview_table, [[label, n] for label, n in pv.counts])
        self.preview_table.resizeColumnsToContents()
        note = P(f"جمعاً {pv.total} ردیف؛ {pv.balance_rows} ماندهٔ حساب.")
        if pv.one_to_one:
            note += " اگر مقصد هم داشته باشد، روی مبدأ می‌ماند: " + "، ".join(pv.one_to_one) + "."
        self.preview_note.setText(note)
        return pv

    def do_merge(self) -> int | None:
        target = self.merge_target.currentData()
        if target is None:
            self._status("تفصیلی مقصد را انتخاب کنید.", ok=False)
            return None
        pv = self.preview_merge()
        if pv is None:
            return None
        text = P(f"همهٔ گردش «{self.label}» ({pv.total} ردیف) به «{self.merge_target.currentText()}» منتقل و "
                 "این تفصیلی غیرفعال شود؟ (از «سابقه» قابل برگشت است)")
        if not self.confirm(text):
            return None
        try:
            res = ops.merge(self.cid, self.uid, self.detail_id, target, self.merge_reason.text())
        except ValueError as exc:
            self._status(str(exc), ok=False)
            return None
        self.changed = True
        self._status(P(f"ادغام انجام شد: {res.moved} ردیف منتقل شد، {res.kept_on_source} ردیف یک‌به‌یک روی مبدأ ماند."), ok=True)
        self.reload_balances()
        self.reload_history()
        return res.operation_id

    # --- سابقه و برگشت ----------------------------------------------------------------------------------
    def _build_history_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        self.history_table = table(["نوع", "وضعیت", "مبدأ", "مقصد", "تاریخ", "شرح", "خلاصه"])
        lay.addWidget(self.history_table, stretch=1)
        row = QHBoxLayout()
        self.reverse_button = _icon_button("⏪", "برگشت عملیات انتخاب‌شده", "danger")
        self.reverse_button.clicked.connect(self.reverse_selected)
        row.addWidget(self.reverse_button)
        row.addStretch(1)
        lay.addLayout(row)
        return page

    def reload_history(self) -> None:
        self.history = ops.list_operations(self.cid, self.detail_id)

        def summary(o) -> str:
            s = o.summary
            if o.operation_type == "TRANSFER":
                return f"{s.get('rows', 0)} مانده، جمع {money(decimals_value(s.get('total')))}"
            return f"{s.get('moved', 0)} ردیف منتقل، {s.get('kept_on_source', 0)} ردیف روی مبدأ"

        fill(self.history_table, [[o.type_label, o.status_label, o.source_label, o.target_label, o.operation_date,
                                   o.description, summary(o)] for o in self.history], [o.operation_id for o in self.history])
        self.history_table.resizeColumnsToContents()

    def reverse_selected(self):
        operation_id = selected_data(self.history_table)
        op = next((o for o in self.history if o.operation_id == operation_id), None)
        if op is None:
            self._status("یک عملیات را از فهرست انتخاب کنید.", ok=False)
            return None
        if not self.confirm(P(f"«{op.type_label}» از «{op.source_label}» به «{op.target_label}» برگشت بخورد؟")):
            return None
        try:
            res = ops.reverse(self.cid, self.uid, operation_id)
        except ValueError as exc:
            self._status(str(exc), ok=False)
            return None
        self.changed = True
        if op.operation_type == "TRANSFER":
            self._status("سند برگشتی صادر شد.", ok=True)
        else:
            self._status(P(f"برگشت ادغام: {res.restored} ردیف برگشت؛ {res.not_restored} ردیف که بعداً تغییر کرده بود ماند."),
                         ok=True)
        self.reload_balances()
        self.reload_history()
        return res

    def _status(self, text: str, ok: bool) -> None:
        theme.set_status_label(self.status_label, text, ok=ok)


def decimals_value(text) -> decimal.Decimal:
    try:
        return decimal.Decimal(text or "0")
    except decimal.InvalidOperation:
        return decimal.Decimal("0")
