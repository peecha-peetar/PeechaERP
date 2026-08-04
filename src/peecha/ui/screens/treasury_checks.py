"""مدیریتِ چک‌هایِ دریافتی و پرداختی — طبقِ الگویِ نمونه‌یِ ارائه‌شده: فهرستی
از مراحلِ چرخه‌یِ چک (رادیو)، جدولی چندانتخابی (چک‌باکس) از چک‌هایِ
واجدِ شرایطِ همان مرحله، و یک دکمه‌یِ تاییدِ نهایی که همه‌یِ چک‌هایِ
تیک‌خورده را یک‌جا پردازش می‌کند (services/treasury.py: توابعِ bulk)."""

from __future__ import annotations

import dataclasses

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import treasury as treasury_service
from peecha.ui.screens.journal_entry import _make_searchable_combo
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


@dataclasses.dataclass
class _StageConfig:
    key: str
    label: str
    eligible_status_codes: tuple[str, ...]
    target_dimension_code: str | None  # CASH_BOX_CODE / BANK_ACCOUNT_CODE / None
    target_label: str = ""
    confirm_message: str = ""


_RECEIVED_STAGES: list[_StageConfig] = [
    _StageConfig(
        "TRANSFER", "چک‌هایِ دریافتی جهتِ انتقال بینِ صندوق‌ها", ("IN_HAND",),
        dimensions_service.CASH_BOX_CODE, "صندوقِ مقصد",
    ),
    _StageConfig(
        "CASH_COLLECT", "چک‌هایِ نزدِ صندوق جهتِ وصولِ نقدی", ("IN_HAND",),
        dimensions_service.CASH_BOX_CODE, "صندوقِ نقدیِ مقصد",
    ),
    _StageConfig(
        "BANK_DEPOSIT", "چک‌هایِ نزدِ صندوق جهتِ واگذاری به بانک", ("IN_HAND",),
        dimensions_service.BANK_ACCOUNT_CODE, "بانکِ مقصد",
    ),
    _StageConfig(
        "BANK_CLEAR", "چک‌هایِ دریافتیِ نزدِ بانک جهتِ اعلامِ وصول", ("DEPOSITED",),
        None,
    ),
    _StageConfig(
        "BANK_RETURN", "چک‌هایِ دریافتیِ نزدِ بانک جهتِ برگشت به صندوق", ("DEPOSITED",),
        dimensions_service.CASH_BOX_CODE, "صندوقِ مقصد",
    ),
    _StageConfig(
        "CUSTOMER_RETURN", "چک‌هایِ نزدِ صندوق جهتِ برگشت به طرفِ‌حساب", ("IN_HAND",),
        None, confirm_message="این چک(ها) برگشت خورده‌اند؟ بدهیِ طرفِ‌حساب دوباره ثبت می‌شود.",
    ),
    _StageConfig(
        "ENDORSED_RETURN", "چک‌هایِ خرجی جهتِ برگشت به صندوق", ("ENDORSED",),
        dimensions_service.CASH_BOX_CODE, "صندوقِ مقصد",
    ),
]

_ISSUED_STAGES: list[_StageConfig] = [
    _StageConfig(
        "BANK_CLEAR", "چک‌هایِ پرداختی جهتِ وصول از بانک", ("ISSUED",),
        None,
    ),
    _StageConfig(
        "RETURN_TO_FUND", "چک‌هایِ پرداختیِ وصول‌نشده جهتِ برگشت به صندوق", ("ISSUED", "BOUNCED"),
        None, confirm_message="این چک(ها) به صندوق برگردانده شوند؟ بدهیِ ما به طرفِ‌حساب دوباره ثبت می‌شود.",
    ),
]


class ReceivedChecksScreen(FieldHelpMixin, QWidget):
    _COLUMNS = ["شماره‌یِ چک", "بانکِ صادرکننده", "نامِ صادرکننده", "مبلغ", "سررسید", "تاریخِ دریافت", "محلِ فعلی"]

    def __init__(self) -> None:
        super().__init__()
        self._checks: list[treasury_service.ReceivedCheckRow] = []
        self._stage: _StageConfig = _RECEIVED_STAGES[0]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("چک‌هایِ دریافتی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self._stage_group = QButtonGroup(self)
        stage_box = QVBoxLayout()
        for index, stage in enumerate(_RECEIVED_STAGES):
            radio = QRadioButton(stage.label)
            radio.setChecked(index == 0)
            radio.toggled.connect(lambda checked, s=stage: self._on_stage_selected(s) if checked else None)
            self._stage_group.addButton(radio)
            stage_box.addWidget(radio)
        layout.addLayout(stage_box)

        self.table = QTableWidget(0, len(self._COLUMNS) + 1)
        self.table.setHorizontalHeaderLabels([""] + self._COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 32)
        layout.addWidget(self.table, stretch=1)

        self._action_row = QHBoxLayout()
        self.target_label = QLabel("")
        self.target_combo = QComboBox()
        self._action_row.addWidget(self.target_label)
        self._action_row.addWidget(self.target_combo)
        self._action_row.addStretch(1)
        self.confirm_button = QPushButton("تاییدِ عملیات")
        self.confirm_button.setObjectName("flatButton")
        self.confirm_button.clicked.connect(self._apply_stage)
        self._action_row.addWidget(self.confirm_button)
        layout.addLayout(self._action_row)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.set_field_help([
            (
                self.table,
                "بالا مرحله‌یِ موردِنظر را انتخاب کنید — فهرست به چک‌هایِ واجدِ شرایطِ همان مرحله به‌روز می‌شود؛ "
                "چک(ها) را تیک بزنید و «تاییدِ عملیات» را بزنید تا همه‌یِ چک‌هایِ تیک‌خورده یک‌جا پردازش شوند.",
            ),
        ])

        self._on_stage_selected(self._stage)

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def _on_stage_selected(self, stage: _StageConfig) -> None:
        self._stage = stage
        # طبقِ الگویِ موجود: کمبویِ مقصد باید جست‌وجوپذیر باشد (هم‌الگو با
        # بقیه‌ی فرمِ خزانه‌داری) — چون _make_searchable_combo هربار یک
        # ویجتِ تازه می‌سازد، جایگزینیِ آن در چیدمان لازم است.
        old_index = self._action_row.indexOf(self.target_combo)
        self._action_row.removeWidget(self.target_combo)
        self.target_combo.deleteLater()
        if stage.target_dimension_code is None:
            options: list[tuple[int, str]] = []
        else:
            company_id = self._company_id()
            options = []
            if company_id is not None:
                type_id = dimensions_service.get_specialized_dimension_type_id(company_id, stage.target_dimension_code)
                options = [
                    (o.detail_account_id, o.name or o.code)
                    for o in dimensions_service.list_leaf_detail_accounts(company_id, type_id)
                ]
        self.target_combo = _make_searchable_combo(options)
        self._action_row.insertWidget(old_index, self.target_combo)
        has_target = stage.target_dimension_code is not None
        self.target_label.setVisible(has_target)
        self.target_combo.setVisible(has_target)
        self.target_label.setText(stage.target_label)
        self.refresh()

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            self._checks = []
            self.table.setRowCount(0)
            return
        self._checks = treasury_service.list_received_checks(company_id, status_codes=list(self._stage.eligible_status_codes))
        self.table.setRowCount(len(self._checks))
        for row_index, c in enumerate(self._checks):
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check_item.setCheckState(Qt.Unchecked)
            check_item.setData(Qt.UserRole, c.received_check_id)
            self.table.setItem(row_index, 0, check_item)
            values = [
                c.check_no,
                c.drawee_bank_name or "—",
                c.drawer_name or "—",
                numerals.format_money(c.amount, 0, None),
                numerals.format_jalali_date(c.due_date),
                numerals.format_jalali_date(c.received_date),
                c.current_location_label or "—",
            ]
            for col_index, value in enumerate(values, start=1):
                self.table.setItem(row_index, col_index, QTableWidgetItem(value))

    def _checked_check_ids(self) -> list[int]:
        ids = []
        for row_index in range(self.table.rowCount()):
            item = self.table.item(row_index, 0)
            if item is not None and item.checkState() == Qt.Checked:
                ids.append(item.data(Qt.UserRole))
        return ids

    def _apply_stage(self) -> None:
        company_id = self._company_id()
        check_ids = self._checked_check_ids()
        if company_id is None or session.current_user is None or not check_ids:
            return
        stage = self._stage
        target_detail_id = self.target_combo.currentData() if stage.target_dimension_code is not None else None
        if stage.target_dimension_code is not None and target_detail_id is None:
            QMessageBox.warning(self, "خطا", f"ابتدا {stage.target_label or 'مقصد'} را انتخاب کنید.")
            return
        if stage.confirm_message:
            confirm = QMessageBox.question(self, "تاییدِ عملیات", stage.confirm_message, QMessageBox.Yes | QMessageBox.No)
            if confirm != QMessageBox.Yes:
                return
        user_id = session.current_user.user_id
        try:
            if stage.key == "TRANSFER":
                treasury_service.transfer_received_checks_between_funds(check_ids, company_id, user_id, target_detail_id)
            elif stage.key == "CASH_COLLECT":
                treasury_service.collect_received_checks_cash(check_ids, company_id, user_id, target_detail_id)
            elif stage.key == "BANK_DEPOSIT":
                treasury_service.deposit_received_checks_to_bank(check_ids, company_id, user_id, target_detail_id)
            elif stage.key == "BANK_CLEAR":
                treasury_service.clear_deposited_received_checks(check_ids, company_id, user_id)
            elif stage.key == "BANK_RETURN":
                treasury_service.return_deposited_received_checks_to_fund(check_ids, company_id, user_id, target_detail_id)
            elif stage.key == "CUSTOMER_RETURN":
                treasury_service.bounce_received_checks(check_ids, company_id, user_id)
            elif stage.key == "ENDORSED_RETURN":
                treasury_service.unendorse_received_checks_to_fund(check_ids, company_id, target_detail_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()


class IssuedChecksScreen(FieldHelpMixin, QWidget):
    _COLUMNS = ["شماره‌یِ چک", "حسابِ بانکی", "گیرنده", "مبلغ", "سررسید"]

    def __init__(self) -> None:
        super().__init__()
        self._checks: list[treasury_service.IssuedCheckRow] = []
        self._stage: _StageConfig = _ISSUED_STAGES[0]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("چک‌هایِ پرداختی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self._stage_group = QButtonGroup(self)
        stage_box = QVBoxLayout()
        for index, stage in enumerate(_ISSUED_STAGES):
            radio = QRadioButton(stage.label)
            radio.setChecked(index == 0)
            radio.toggled.connect(lambda checked, s=stage: self._on_stage_selected(s) if checked else None)
            self._stage_group.addButton(radio)
            stage_box.addWidget(radio)
        layout.addLayout(stage_box)

        self.table = QTableWidget(0, len(self._COLUMNS) + 1)
        self.table.setHorizontalHeaderLabels([""] + self._COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 32)
        layout.addWidget(self.table, stretch=1)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self.confirm_button = QPushButton("تاییدِ عملیات")
        self.confirm_button.setObjectName("flatButton")
        self.confirm_button.clicked.connect(self._apply_stage)
        action_row.addWidget(self.confirm_button)
        layout.addLayout(action_row)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.set_field_help([
            (
                self.table,
                "بالا مرحله‌یِ موردِنظر را انتخاب کنید — فهرست به چک‌هایِ واجدِ شرایطِ همان مرحله به‌روز می‌شود؛ "
                "چک(ها) را تیک بزنید و «تاییدِ عملیات» را بزنید تا همه‌یِ چک‌هایِ تیک‌خورده یک‌جا پردازش شوند.",
            ),
        ])

        self._on_stage_selected(self._stage)

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def _on_stage_selected(self, stage: _StageConfig) -> None:
        self._stage = stage
        self.refresh()

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            self._checks = []
            self.table.setRowCount(0)
            return
        self._checks = treasury_service.list_issued_checks(company_id, status_codes=list(self._stage.eligible_status_codes))
        self.table.setRowCount(len(self._checks))
        for row_index, c in enumerate(self._checks):
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check_item.setCheckState(Qt.Unchecked)
            check_item.setData(Qt.UserRole, c.issued_check_id)
            self.table.setItem(row_index, 0, check_item)
            values = [
                c.check_no,
                c.bank_account_label or "—",
                c.payee_name or "—",
                numerals.format_money(c.amount, 0, None),
                numerals.format_jalali_date(c.due_date),
            ]
            for col_index, value in enumerate(values, start=1):
                self.table.setItem(row_index, col_index, QTableWidgetItem(value))

    def _checked_check_ids(self) -> list[int]:
        ids = []
        for row_index in range(self.table.rowCount()):
            item = self.table.item(row_index, 0)
            if item is not None and item.checkState() == Qt.Checked:
                ids.append(item.data(Qt.UserRole))
        return ids

    def _apply_stage(self) -> None:
        company_id = self._company_id()
        check_ids = self._checked_check_ids()
        if company_id is None or session.current_user is None or not check_ids:
            return
        stage = self._stage
        if stage.confirm_message:
            confirm = QMessageBox.question(self, "تاییدِ عملیات", stage.confirm_message, QMessageBox.Yes | QMessageBox.No)
            if confirm != QMessageBox.Yes:
                return
        user_id = session.current_user.user_id
        try:
            if stage.key == "BANK_CLEAR":
                treasury_service.clear_issued_checks(check_ids, company_id, user_id)
            elif stage.key == "RETURN_TO_FUND":
                treasury_service.return_issued_checks_to_fund(check_ids, company_id, user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()
