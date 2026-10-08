"""درخواست مرخصی (R295): ثبت، ارسال برای تایید، تایید/رد مدیر و مسیر گردش کار.

اگر فرایند «تایید مرخصی» فعال باشد، تایید فقط از «مرکز تایید» انجام می‌شود (مدیر مستقیم، سپس منابع انسانی)؛
بدون فرایند، مدیر مثل قبل مستقیم از همین صفحه تایید یا رد می‌کند.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget

from peecha import numerals
from peecha.services import hr as hr_service, hr_leave, roles as roles_service
from peecha.ui.screens import module_style as ms
from peecha.ui.screens.costing import can
from peecha.ui.screens.fixed_assets import FormDialog, P, combo, company_id, date_field, fill, num_field, selected_data, set_combo, \
    table, user_id
from peecha.ui.screens.workflow_bar import WorkflowBar

ms.ICONS.update({"درخواست مرخصی جدید": ("🆕", "primary"), "ارسال درخواست": ("📨", ""), "تایید مرخصی": ("✅", "primary"),
                 "رد مرخصی": ("❌", "danger"), "لغو درخواست": ("🚫", "danger")})


class LeaveRequestsScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self.main_window = main_window
        self.dialog_runner = None  # برای تست
        self._rows: list[hr_leave.LeaveRow] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)
        title = QLabel("درخواست مرخصی")
        title.setObjectName("pageTitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجوی نام کارمند")
        self.search.textChanged.connect(self.refresh)
        self.status_filter = combo([(label, code) for code, label in hr_leave.STATUSES.items()], "همهٔ وضعیت‌ها")
        self.status_filter.currentIndexChanged.connect(self.refresh)
        layout.addWidget(ms.header_card(title, self.search, self.status_filter))
        cards, self.cards = ms.summary([("SUBMITTED", "در انتظار تایید", "warning", "⏳"), ("APPROVED", "تاییدشده", "success", "✅"),
                                        ("REJECTED", "ردشده", "danger", "❌"), ("days", "روزهای تاییدشده", "info", "📅")])
        layout.addWidget(cards)
        self.table = table(["کارمند", "نوع مرخصی", "از تاریخ", "تا تاریخ", "مدت", "دلیل", "وضعیت", "نظر تاییدکننده"])
        self.table.itemSelectionChanged.connect(self._selected)
        layout.addWidget(self.table, stretch=1)
        self.workflow_bar = WorkflowBar("LEAVE_REQUEST")
        self.workflow_bar.on_started = self.refresh
        layout.addWidget(self.workflow_bar)
        self.buttons = {key: QPushButton(label) for key, label in (
            ("new", "درخواست مرخصی جدید"), ("submit", "ارسال درخواست"), ("approve", "تایید مرخصی"), ("reject", "رد مرخصی"),
            ("cancel", "لغو درخواست"))}
        for key, slot in (("new", self.new_request), ("submit", self.submit), ("approve", self.approve), ("reject", self.reject),
                          ("cancel", self.cancel)):
            self.buttons[key].clicked.connect(slot)
        layout.addWidget(ms.footer([[self.buttons["new"], self.buttons["submit"], self.buttons["cancel"]],
                                    [self.buttons["approve"], self.buttons["reject"]]]))
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    # --- داده ---------------------------------------------------------------------------------------------------
    def _is_approver(self) -> bool:
        cid, uid = company_id(), user_id()
        return bool(cid and uid) and (roles_service.is_manager(uid, cid) or can("hr_leave_requests", "APPROVE"))

    def refresh(self) -> None:
        cid = company_id()
        if not cid:
            return
        rows = hr_leave.list_requests(cid)
        counts = {k: sum(1 for r in rows if r.status_code == k) for k in ("SUBMITTED", "APPROVED", "REJECTED")}
        for key, value in counts.items():
            self.cards[key].setText(P(str(value)))
        self.cards["days"].setText(P(str(sum((r.days for r in rows if r.status_code == "APPROVED"), 0))))
        text, status = self.search.text().strip(), self.status_filter.currentData()
        self._rows = [r for r in rows if (not status or r.status_code == status) and (not text or text in r.employee_name)]
        fill(self.table, [[r.employee_name, r.leave_type_label, r.from_date, r.to_date,
                           f"{numerals.to_persian_digits(str(r.hours))} ساعت" if r.hours else f"{P(str(r.days))} روز",
                           r.reason, r.status_label, r.decision_note] for r in self._rows],
             [r.leave_request_id for r in self._rows])
        self._selected()

    def _current(self) -> hr_leave.LeaveRow | None:
        rid = selected_data(self.table)
        return next((r for r in self._rows if r.leave_request_id == rid), None)

    def _selected(self) -> None:
        row = self._current()
        self.workflow_bar.set_entity("LEAVE_REQUEST", row.leave_request_id if row else None)
        approver = self._is_approver()
        self.buttons["submit"].setEnabled(bool(row) and row.status_code == "DRAFT")
        self.buttons["cancel"].setEnabled(bool(row) and row.status_code in ("DRAFT", "SUBMITTED"))
        self.buttons["approve"].setEnabled(bool(row) and row.status_code == "SUBMITTED" and approver)
        self.buttons["reject"].setEnabled(bool(row) and row.status_code == "SUBMITTED" and approver)

    def open_request(self, leave_request_id: int) -> None:
        self.status_filter.setCurrentIndex(0)
        self.search.clear()
        self.refresh()
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole) == leave_request_id:
                self.table.setCurrentCell(r, 0)  # در چیدمان راست‌به‌چپ selectRow چیزی انتخاب نمی‌کند
                break

    # --- کارها --------------------------------------------------------------------------------------------------
    def _ask(self, title: str, fields, hint: str = "") -> dict | None:
        dlg = FormDialog(title, fields, hint, self)
        ok = self.dialog_runner(dlg) if self.dialog_runner else dlg.exec() == FormDialog.Accepted
        return dlg.values() if ok else None

    def _do(self, title: str, fn, *args, **kwargs) -> bool:
        try:
            fn(*args, **kwargs)
        except ValueError as exc:
            QMessageBox.warning(self, title, str(exc))
            return False
        self.refresh()
        return True

    def new_request(self) -> None:
        cid = company_id()
        if not cid:
            return
        employees = [(f"{e.employee_code} — {e.full_name}", e.employee_id) for e in hr_service.list_employees(cid)]
        employee = combo(employees)
        mine = hr_leave.employee_of_user(cid, user_id()) if user_id() else None
        if mine:
            set_combo(employee, mine)
        kind = combo([(label, code) for code, label in hr_leave.LEAVE_TYPES.items()])
        hours = num_field()
        hours.setPlaceholderText("فقط برای مرخصی ساعتی")
        reason = QLineEdit()
        values = self._ask("درخواست مرخصی جدید", [
            ("employee", "کارمند", employee), ("leave_type", "نوع مرخصی", kind), ("from_date", "از تاریخ", date_field()),
            ("to_date", "تا تاریخ", date_field()), ("hours", "تعداد ساعت", hours), ("reason", "دلیل", reason)],
            "درخواست پس از ثبت برای تایید فرستاده می‌شود.")
        if values is None:
            return
        if not values.get("employee"):
            QMessageBox.warning(self, "درخواست مرخصی", "کارمند را انتخاب کنید.")
            return
        self._do("درخواست مرخصی", hr_leave.create_request, cid, user_id(), values["employee"], values["leave_type"],
                 values["from_date"], values["to_date"], hours=values.get("hours"), reason=values.get("reason") or "", submit=True)
        self.status_label.setText("درخواست ثبت و برای تایید فرستاده شد.")

    def submit(self) -> None:
        row = self._current()
        if row is not None:
            self._do("ارسال درخواست", hr_leave.submit, company_id(), row.leave_request_id)

    def approve(self) -> None:
        row = self._current()
        if row is not None:
            self._do("تایید مرخصی", hr_leave.approve, company_id(), row.leave_request_id, user_id())

    def reject(self) -> None:
        row = self._current()
        if row is None:
            return
        note = QLineEdit()
        values = self._ask("رد مرخصی", [("note", "دلیل رد", note)])
        if values is None:
            return
        if not values.get("note"):
            QMessageBox.warning(self, "رد مرخصی", "دلیل رد را بنویسید.")
            return
        self._do("رد مرخصی", hr_leave.reject, company_id(), row.leave_request_id, user_id(), values["note"])

    def cancel(self) -> None:
        row = self._current()
        if row is not None:
            self._do("لغو درخواست", hr_leave.cancel, company_id(), row.leave_request_id)
