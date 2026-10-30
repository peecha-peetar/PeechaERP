"""R381: حق مأموریت و هزینهٔ مأموریت — صورت‌حساب روی مأموریت تاییدشده، تایید، صدور سند و تنظیم نرخ و حساب‌ها."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import hr_missions as hm
from peecha.ui import theme
from peecha.ui.screens.fixed_assets import P, combo, company_id, dec, fill, money, selected_data, set_combo, table, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec, build_page_header, set_widget_help


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


def _num(value) -> str:
    return P(f"{value.normalize():f}") if value is not None else ""


class HrMissionsScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.claims: list[hm.ClaimRow] = []
        self.expenses: list[hm.ExpenseRow] = []
        self._claim_id: int | None = None
        self.ask_reason = None  # برای آزمون
        self.confirm_runner = None  # برای آزمون
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "حق مأموریت", "برای هر مأموریت تاییدشده صورت‌حساب بسازید: حق مأموریت روزانه طبق تنظیمات حساب می‌شود و هزینه‌های "
            "سفر با شمارهٔ رسید اضافه می‌شوند. پس از تایید، سند حسابداری صادر می‌شود و مبلغ با فرم پرداخت به کارمند پرداخت "
            "می‌شود. این مبلغ به فیش حقوق، بیمه و مالیات حقوق افزوده نمی‌شود."))
        self.tabs = QTabWidget()
        self.tabs.addTab(self._claims_tab(), "صورت‌حساب‌ها")
        self.tabs.addTab(self._settings_tab(), "نرخ و حساب‌ها")
        layout.addWidget(self.tabs, 1)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def _status(self, text: str, ok: bool) -> None:
        theme.set_status_label(self.status_label, text, ok=ok)

    # --- صورت‌حساب‌ها --------------------------------------------------------------------------------------------------
    def _claims_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        top = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItem("همهٔ وضعیت‌ها", None)
        for code, label in hm.STATUSES.items():
            self.status_filter.addItem(label, code)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        top.addWidget(QLabel("وضعیت:"))
        top.addWidget(self.status_filter)
        top.addLayout(_bar(
            ("صورت‌حساب جدید برای یک مأموریت تاییدشده", "➕", "primary", self.new_claim),
            ("ارسال برای تایید", "📤", "", self.submit_claim),
            ("تایید صورت‌حساب", "✅", "", self.approve_claim),
            ("رد صورت‌حساب با ذکر دلیل", "↩️", "", self.reject_claim),
            ("صدور سند حسابداری", "📒", "", self.post_claim),
            ("حذف صورت‌حساب پیش‌نویس", "🗑️", "danger", self.delete_claim),
            ("به‌روزرسانی", "🔄", "", self.refresh)), 1)
        lay.addLayout(top)
        self.claims_table = table(["شماره", "کارمند", "از تاریخ", "تا تاریخ", "مقصد", "روز", "حق روزانه", "حق مأموریت", "هزینه‌ها",
                                   "جمع", "وضعیت", "توضیح تایید/رد"])
        self.claims_table.itemSelectionChanged.connect(self._on_select)
        lay.addWidget(self.claims_table, 2)

        self.editor_title = QLabel("")
        lay.addWidget(self.editor_title)
        self.mission_combo = combo([])
        self.destination_field, self.purpose_field, self.days_field = QLineEdit(), QLineEdit(), QLineEdit()
        self.amounts_label = QLabel("")
        row = QHBoxLayout()
        row.addWidget(FieldGrid([
            FieldSpec("hm_mission", "مأموریت تاییدشده", self.mission_combo, span=3),
            FieldSpec("hm_destination", "مقصد", self.destination_field, span=2),
            FieldSpec("hm_days", "روزهای مأموریت", self.days_field, span=1),
            FieldSpec("hm_purpose", "شرح مأموریت", self.purpose_field, span=3)]), 1)
        save = _btn("ذخیرهٔ صورت‌حساب", "💾", "primary")
        save.clicked.connect(self.save_claim)
        row.addWidget(save)
        lay.addLayout(row)
        lay.addWidget(self.amounts_label)
        for widget, text in (
                (self.mission_combo, "مرخصی‌های نوع «مأموریت» که تایید شده‌اند و هنوز صورت‌حساب ندارند."),
                (self.days_field, "خالی یعنی همان روزهای ثبت‌شده در مأموریت؛ حداکثر تا فاصلهٔ تاریخ شروع و پایان."),
                (self.destination_field, "شهر یا محل مأموریت.")):
            set_widget_help(widget, text)

        exp_row = QHBoxLayout()
        self.expense_type_combo = QComboBox()
        for code, label in hm.EXPENSE_TYPES.items():
            self.expense_type_combo.addItem(label, code)
        self.expense_amount_field, self.expense_receipt_field, self.expense_desc_field = QLineEdit(), QLineEdit(), QLineEdit()
        exp_row.addWidget(FieldGrid([
            FieldSpec("hm_exp_type", "نوع هزینه", self.expense_type_combo, span=1),
            FieldSpec("hm_exp_amount", "مبلغ", self.expense_amount_field, span=1),
            FieldSpec("hm_exp_receipt", "شمارهٔ رسید", self.expense_receipt_field, span=1),
            FieldSpec("hm_exp_desc", "شرح هزینه", self.expense_desc_field, span=3)]), 1)
        exp_row.addLayout(_bar(("افزودن هزینه", "➕", "", self.add_expense),
                               ("حذف هزینهٔ انتخاب‌شده", "🗑️", "danger", self.delete_expense)))
        lay.addLayout(exp_row)
        self.expenses_table = table(["نوع", "شرح", "شمارهٔ رسید", "مبلغ"])
        lay.addWidget(self.expenses_table, 1)
        return w

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.claims = hm.list_claims(cid, status=self.status_filter.currentData())
        fill(self.claims_table, [[P(c.claim_no), c.employee_name, c.from_date, c.to_date, c.destination, _num(c.days), c.daily_rate,
                                  c.per_diem_amount, c.expenses_amount, c.total_amount, c.status_label, c.decision_note]
                                 for c in self.claims], [c.claim_id for c in self.claims])
        self._load_settings()
        if self._claim_id is not None and any(c.claim_id == self._claim_id for c in self.claims):
            self.open_claim(self._claim_id)
        else:
            self.new_claim()

    def show_status(self, status: str | None) -> None:
        """از کارتابل: فهرست با یک وضعیت."""
        self.tabs.setCurrentIndex(0)
        idx = self.status_filter.findData(status)
        self.status_filter.setCurrentIndex(max(idx, 0))
        self.refresh()

    def _on_select(self) -> None:
        claim_id = selected_data(self.claims_table)
        if claim_id is not None and claim_id != self._claim_id:
            self.open_claim(claim_id)

    def new_claim(self) -> None:
        self._claim_id = None
        self.editor_title.setText("صورت‌حساب جدید")
        self.mission_combo.setEnabled(True)
        self.mission_combo.clear()
        cid = company_id()
        for m in (hm.eligible_missions(cid) if cid else []):
            dates = f"{numerals.format_jalali_date(m.from_date)} تا {numerals.format_jalali_date(m.to_date)}"
            self.mission_combo.addItem(f"{m.employee_name} — {dates} ({_num(m.days)} روز) {m.reason}".strip(), m.leave_request_id)
        for f in (self.destination_field, self.purpose_field, self.days_field):
            f.clear()
        self.amounts_label.setText("")
        self.expenses = []
        fill(self.expenses_table, [])

    def open_claim(self, claim_id: int) -> None:
        cid = company_id()
        c = hm.get_claim(cid, claim_id)
        self._claim_id = claim_id
        self.editor_title.setText(f"صورت‌حساب مأموریت {P(c.claim_no)} — {c.status_label}")
        self.mission_combo.clear()
        self.mission_combo.addItem(f"{c.employee_name} — {numerals.format_jalali_date(c.from_date)} تا "
                                   f"{numerals.format_jalali_date(c.to_date)}", c.leave_request_id)
        self.mission_combo.setEnabled(False)
        self.destination_field.setText(c.destination)
        self.purpose_field.setText(c.purpose)
        self.days_field.setText(_num(c.days))
        self.amounts_label.setText(f"حق مأموریت: {_num(c.days)} روز × {money(c.daily_rate)} = {money(c.per_diem_amount)}   ·   "
                                   f"هزینه‌ها: {money(c.expenses_amount)}   ·   جمع: {money(c.total_amount)}")
        self.expenses = hm.list_expenses(claim_id)
        fill(self.expenses_table, [[x.type_label, x.description, x.receipt_no, x.amount] for x in self.expenses],
             [x.expense_id for x in self.expenses])

    def _days(self):
        text = self.days_field.text().strip()
        return dec(text) if text else None

    def _run(self, action, ok_text: str) -> bool:
        try:
            action()
        except (ValueError, decimal.InvalidOperation) as exc:
            self._status(str(exc) if isinstance(exc, ValueError) else "عدد نامعتبر است.", False)
            return False
        self.refresh()
        self._status(ok_text, True)
        return True

    def save_claim(self) -> bool:
        cid, uid = company_id(), user_id()
        if self._claim_id is None:
            leave_id = self.mission_combo.currentData()
            if leave_id is None:
                self._status("مأموریت تاییدشده‌ای برای صورت‌حساب انتخاب نشده است.", False)
                return False

            def create():
                self._claim_id = hm.create_claim(cid, uid, leave_id, self.destination_field.text(), self.purpose_field.text(),
                                                 self._days())
            return self._run(create, "صورت‌حساب مأموریت ساخته شد.")
        claim_id = self._claim_id
        return self._run(lambda: hm.update_claim(cid, uid, claim_id, self.destination_field.text(), self.purpose_field.text(),
                                                 self._days()), "صورت‌حساب ذخیره شد.")

    def _need_claim(self) -> int | None:
        if self._claim_id is None:
            self._status("یک صورت‌حساب را انتخاب کنید.", False)
        return self._claim_id

    def add_expense(self) -> bool:
        claim_id = self._need_claim()
        if claim_id is None:
            return False

        def add():
            hm.add_expense(company_id(), user_id(), claim_id, self.expense_type_combo.currentData(), dec(self.expense_amount_field.text()),
                           self.expense_desc_field.text(), self.expense_receipt_field.text())
            for f in (self.expense_amount_field, self.expense_receipt_field, self.expense_desc_field):
                f.clear()
        return self._run(add, "هزینه اضافه شد.")

    def delete_expense(self) -> bool:
        expense_id = selected_data(self.expenses_table)
        if expense_id is None:
            self._status("یک هزینه را انتخاب کنید.", False)
            return False
        return self._run(lambda: hm.delete_expense(company_id(), user_id(), expense_id), "هزینه حذف شد.")

    def submit_claim(self) -> bool:
        claim_id = self._need_claim()
        return claim_id is not None and self._run(lambda: hm.submit(company_id(), user_id(), claim_id), "برای تایید ارسال شد.")

    def approve_claim(self) -> bool:
        claim_id = self._need_claim()
        return claim_id is not None and self._run(lambda: hm.approve(company_id(), user_id(), claim_id), "صورت‌حساب تایید شد.")

    def reject_claim(self) -> bool:
        claim_id = self._need_claim()
        if claim_id is None:
            return False
        if self.ask_reason is not None:
            reason, ok = self.ask_reason(), True
        else:
            reason, ok = QInputDialog.getText(self, "رد صورت‌حساب", "دلیل رد:")
        return ok and self._run(lambda: hm.reject(company_id(), user_id(), claim_id, reason), "صورت‌حساب رد شد.")

    def post_claim(self) -> bool:
        claim_id = self._need_claim()
        if claim_id is None:
            return False
        result = {}

        def post():
            result["je"] = hm.post(company_id(), user_id(), claim_id)
        if not self._run(post, "سند حسابداری صادر شد."):
            return False
        self._status(f"سند حسابداری موقت (شناسهٔ {P(result['je'])}) صادر شد؛ پس از تایید سند، مبلغ را با فرم پرداخت به کارمند بپردازید.",
                     True)
        return True

    def delete_claim(self) -> bool:
        claim_id = self._need_claim()
        if claim_id is None:
            return False
        ask = self.confirm_runner or (lambda: QMessageBox.question(self, "حذف صورت‌حساب", "این صورت‌حساب مأموریت حذف شود؟")
                                      == QMessageBox.Yes)
        if not ask():
            return False
        self._claim_id = None
        return self._run(lambda: hm.delete_claim(company_id(), user_id(), claim_id), "صورت‌حساب حذف شد.")

    # --- تنظیمات --------------------------------------------------------------------------------------------------------
    def _settings_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.method_combo = QComboBox()
        for code, label in hm.METHODS.items():
            self.method_combo.addItem(label, code)
        self.daily_amount_field, self.daily_percent_field = QLineEdit(), QLineEdit()
        self.expense_account_combo, self.expense_detail_combo, self.payable_account_combo = combo([]), combo([]), combo([])
        lay.addWidget(FieldGrid([
            FieldSpec("hm_method", "روش حق مأموریت", self.method_combo, span=2),
            FieldSpec("hm_daily_amount", "مبلغ روزانه", self.daily_amount_field, span=2),
            FieldSpec("hm_daily_percent", "درصد حقوق پایهٔ روزانه", self.daily_percent_field, span=2),
            FieldSpec("hm_expense_account", "حساب هزینهٔ مأموریت", self.expense_account_combo, span=3),
            FieldSpec("hm_expense_detail", "تفصیلی حساب هزینه (اختیاری)", self.expense_detail_combo, span=3),
            FieldSpec("hm_payable_account", "حساب پرداختنی به کارکنان", self.payable_account_combo, span=3)]))
        for widget, text in (
                (self.method_combo, "مبلغ ثابت برای هر روز، یا درصدی از حقوق پایهٔ یک روز قرارداد فعال کارمند."),
                (self.daily_amount_field, "حق مأموریت هر روز وقتی روش «مبلغ ثابت روزانه» است."),
                (self.daily_percent_field, "مثلاً ۵۰ یعنی نصف حقوق پایهٔ یک روز؛ حقوق ماهانه بر روزهای استاندارد ماه تقسیم می‌شود."),
                (self.expense_account_combo, "حسابی که حق و هزینه‌های مأموریت در سند به آن بدهکار می‌شود."),
                (self.expense_detail_combo, "تفصیلی اختیاری ردیف هزینه، مثلاً مرکز هزینه."),
                (self.payable_account_combo, "حسابی که با تفصیلی پرسنلی همان کارمند بستانکار می‌شود تا بعداً پرداخت شود.")):
            set_widget_help(widget, text)
        lay.addLayout(_bar(("ذخیرهٔ نرخ و حساب‌ها", "💾", "primary", self.save_settings)))
        lay.addStretch(1)
        return w

    def _load_settings(self) -> None:
        cid = company_id()
        accounts = coa_service.list_postable_accounts(cid)
        for box in (self.expense_account_combo, self.payable_account_combo):
            box.blockSignals(True)
            box.clear()
            box.addItem("", None)
            for a in accounts:
                box.addItem(P(f"{a.full_code} — {a.name}"), a.account_id)
            box.blockSignals(False)
        self.expense_detail_combo.clear()
        self.expense_detail_combo.addItem("", None)
        for d in dimensions_service.list_all_leaf_detail_accounts(cid):
            self.expense_detail_combo.addItem(P(f"{d.full_code} — {d.name}" if d.name else d.full_code), d.detail_account_id)
        st = hm.get_settings(cid)
        set_combo(self.method_combo, st.per_diem_method)
        self.daily_amount_field.setText(_num(st.daily_amount))
        self.daily_percent_field.setText(_num(st.daily_percent))
        set_combo(self.expense_account_combo, st.expense_gl_account_id)
        set_combo(self.expense_detail_combo, st.expense_detail_account_id)
        set_combo(self.payable_account_combo, st.payable_gl_account_id)

    def save_settings(self) -> bool:
        def save():
            hm.save_settings(company_id(), user_id(), hm.Settings(
                self.method_combo.currentData(), dec(self.daily_amount_field.text()), dec(self.daily_percent_field.text()),
                self.expense_account_combo.currentData(), self.expense_detail_combo.currentData(), self.payable_account_combo.currentData()))
        return self._run(save, "نرخ و حساب‌های مأموریت ذخیره شد.")
