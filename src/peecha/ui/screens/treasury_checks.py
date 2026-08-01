"""مدیریتِ چک‌هایِ دریافتی و پرداختی — دو صفحه‌یِ فهرست+اقدام رویِ چرخه‌یِ
عمرِ چک (services/treasury.py: deposit/clear/bounce/endorse/void)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import treasury as treasury_service
from peecha.ui.widgets import FieldHelpMixin

_RECEIVED_STATUS_LABELS = {
    "IN_HAND": "نزدِ صندوق",
    "DEPOSITED": "واگذارشده به بانک",
    "CLEARED": "وصول‌شده",
    "BOUNCED": "برگشت‌خورده",
    "ENDORSED": "خرج‌شده نزدِ شخصِ ثالث",
}
_ISSUED_STATUS_LABELS = {
    "ISSUED": "صادر/نزدِ گیرنده",
    "CLEARED": "وصول‌شده",
    "BOUNCED": "برگشت‌خورده",
    "VOIDED": "ابطال‌شده",
}


class _PickBankAccountDialog(QDialog):
    def __init__(self, company_id: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("انتخابِ حسابِ بانکی")
        layout = QFormLayout(self)
        bank_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.BANK_ACCOUNT_CODE)
        self.combo = QComboBox()
        for account in dimensions_service.list_detail_accounts(company_id, bank_type_id):
            self.combo.addItem(account.name or account.code, account.detail_account_id)
        layout.addRow("چک به کدام حسابِ بانکی واریز شود؟", self.combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def selected_bank_detail_id(self) -> int | None:
        return self.combo.currentData()


class ReceivedChecksScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._checks: list[treasury_service.ReceivedCheckRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("چک‌هایِ دریافتی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("وضعیت"))
        self.status_combo = QComboBox()
        self.status_combo.addItem("همه", None)
        for code, label in _RECEIVED_STATUS_LABELS.items():
            self.status_combo.addItem(label, code)
        self.status_combo.currentIndexChanged.connect(self.refresh)
        filter_row.addWidget(self.status_combo)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["شماره‌یِ چک", "بانکِ صادرکننده", "نامِ صادرکننده", "مبلغ", "سررسید", "تاریخِ دریافت", "وضعیت"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

        buttons = QHBoxLayout()
        deposit_button = QPushButton("واگذاری به بانک")
        deposit_button.setObjectName("flatButton")
        deposit_button.clicked.connect(self._deposit_selected)
        buttons.addWidget(deposit_button)

        clear_button = QPushButton("وصول شد")
        clear_button.setObjectName("flatButton")
        clear_button.clicked.connect(self._clear_selected)
        buttons.addWidget(clear_button)

        endorse_button = QPushButton("خرج شد نزدِ شخصِ ثالث")
        endorse_button.setObjectName("flatButton")
        endorse_button.clicked.connect(self._endorse_selected)
        buttons.addWidget(endorse_button)

        buttons.addStretch(1)

        bounce_button = QPushButton("برگشت خورد")
        bounce_button.setObjectName("dangerButton")
        bounce_button.clicked.connect(self._bounce_selected)
        buttons.addWidget(bounce_button)

        layout.addLayout(buttons)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.set_field_help([
            (
                self.table,
                "چکِ دریافتی از «نزدِ صندوق» شروع می‌شود؛ می‌توانید آن را به بانک واگذار کنید، وصول یا برگشتِ آن را ثبت کنید، "
                "یا به‌عنوانِ چکِ پرداختیِ سندی دیگر خرج کنید.",
            ),
        ])

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            self._checks = []
            self.table.setRowCount(0)
            return
        status_code = self.status_combo.currentData()
        self._checks = treasury_service.list_received_checks(company_id, status_codes=[status_code] if status_code else None)
        self.table.setRowCount(len(self._checks))
        for row_index, c in enumerate(self._checks):
            values = [
                c.check_no,
                c.drawee_bank_name or "—",
                c.drawer_name or "—",
                numerals.format_money(c.amount, 0, None),
                numerals.format_jalali_date(c.due_date),
                numerals.format_jalali_date(c.received_date),
                _RECEIVED_STATUS_LABELS.get(c.status_code, c.status_code),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, c.received_check_id)
                self.table.setItem(row_index, col_index, item)

    def _selected_check_id(self) -> int | None:
        selected = self.table.selectedItems()
        if not selected:
            return None
        return selected[0].data(Qt.UserRole)

    def _deposit_selected(self) -> None:
        company_id = self._company_id()
        check_id = self._selected_check_id()
        if company_id is None or check_id is None:
            return
        try:
            treasury_service.deposit_received_check(check_id, company_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _clear_selected(self) -> None:
        company_id = self._company_id()
        check_id = self._selected_check_id()
        if company_id is None or check_id is None or session.current_user is None:
            return
        dialog = _PickBankAccountDialog(company_id, self)
        if dialog.exec() != QDialog.Accepted:
            return
        bank_detail_id = dialog.selected_bank_detail_id()
        if bank_detail_id is None:
            return
        try:
            treasury_service.clear_received_check(check_id, company_id, session.current_user.user_id, bank_detail_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _bounce_selected(self) -> None:
        company_id = self._company_id()
        check_id = self._selected_check_id()
        if company_id is None or check_id is None or session.current_user is None:
            return
        confirm = QMessageBox.question(
            self, "برگشت‌زدنِ چک", "این چک برگشت خورده است؟ بدهیِ طرف‌حساب دوباره ثبت می‌شود.", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            treasury_service.bounce_received_check(check_id, company_id, session.current_user.user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _endorse_selected(self) -> None:
        company_id = self._company_id()
        check_id = self._selected_check_id()
        if company_id is None or check_id is None:
            return
        try:
            treasury_service.endorse_received_check(check_id, company_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()


class IssuedChecksScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._checks: list[treasury_service.IssuedCheckRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("چک‌هایِ پرداختی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("وضعیت"))
        self.status_combo = QComboBox()
        self.status_combo.addItem("همه", None)
        for code, label in _ISSUED_STATUS_LABELS.items():
            self.status_combo.addItem(label, code)
        self.status_combo.currentIndexChanged.connect(self.refresh)
        filter_row.addWidget(self.status_combo)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["شماره‌یِ چک", "حسابِ بانکی", "گیرنده", "مبلغ", "سررسید", "وضعیت"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

        buttons = QHBoxLayout()
        clear_button = QPushButton("وصول شد")
        clear_button.setObjectName("flatButton")
        clear_button.clicked.connect(self._clear_selected)
        buttons.addWidget(clear_button)

        buttons.addStretch(1)

        bounce_button = QPushButton("برگشت خورد")
        bounce_button.setObjectName("dangerButton")
        bounce_button.clicked.connect(self._bounce_selected)
        buttons.addWidget(bounce_button)

        void_button = QPushButton("ابطال")
        void_button.setObjectName("dangerButton")
        void_button.clicked.connect(self._void_selected)
        buttons.addWidget(void_button)

        layout.addLayout(buttons)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.set_field_help([
            (
                self.table,
                "چکِ پرداختی از «صادر/نزدِ گیرنده» شروع می‌شود؛ وصول‌شدنش توسطِ بانکِ ما را ثبت کنید، یا اگر برگشت خورد/هرگز "
                "وصول نشد و باطل شد، وضعیتش را به‌روز کنید.",
            ),
        ])

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            self._checks = []
            self.table.setRowCount(0)
            return
        status_code = self.status_combo.currentData()
        self._checks = treasury_service.list_issued_checks(company_id, status_codes=[status_code] if status_code else None)
        self.table.setRowCount(len(self._checks))
        for row_index, c in enumerate(self._checks):
            values = [
                c.check_no,
                c.bank_account_label or "—",
                c.payee_name or "—",
                numerals.format_money(c.amount, 0, None),
                numerals.format_jalali_date(c.due_date),
                _ISSUED_STATUS_LABELS.get(c.status_code, c.status_code),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, c.issued_check_id)
                self.table.setItem(row_index, col_index, item)

    def _selected_check_id(self) -> int | None:
        selected = self.table.selectedItems()
        if not selected:
            return None
        return selected[0].data(Qt.UserRole)

    def _clear_selected(self) -> None:
        company_id = self._company_id()
        check_id = self._selected_check_id()
        if company_id is None or check_id is None or session.current_user is None:
            return
        try:
            treasury_service.clear_issued_check(check_id, company_id, session.current_user.user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _bounce_selected(self) -> None:
        company_id = self._company_id()
        check_id = self._selected_check_id()
        if company_id is None or check_id is None:
            return
        confirm = QMessageBox.question(self, "برگشت‌خوردنِ چک", "این چک توسطِ بانک برگشت خورده است؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            treasury_service.bounce_issued_check(check_id, company_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _void_selected(self) -> None:
        company_id = self._company_id()
        check_id = self._selected_check_id()
        if company_id is None or check_id is None or session.current_user is None:
            return
        confirm = QMessageBox.question(
            self, "ابطالِ چک", "این چک باطل شود؟ بدهیِ ما به طرف‌حساب دوباره ثبت می‌شود.", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            treasury_service.void_issued_check(check_id, company_id, session.current_user.user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()
