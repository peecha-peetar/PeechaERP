"""بهایِ تمام‌شدهٔ وارداتی و ریبیتِ تامین‌کننده (مرحلهٔ ۴) — تسهیمِ
هزینه‌هایِ جانبیِ خرید رویِ ردیف‌هایِ فاکتور، و قراردادها/تعهداتِ ریبیتِ
تامین‌کننده."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_purchasing as purchasing_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service

_COST_TYPE_LABELS = {"FREIGHT": "حمل‌ونقل", "CUSTOMS": "حقوقِ گمرکی", "INSURANCE": "بیمه", "HANDLING": "بارگیری/تخلیه", "OTHER": "سایر"}
_ALLOCATION_METHOD_LABELS = {"BY_VALUE": "به‌نسبتِ ارزش", "BY_QUANTITY": "به‌نسبتِ تعداد", "BY_WEIGHT": "به‌نسبتِ وزن"}
_REBATE_BASIS_LABELS = {"FLAT_PERCENT": "درصدِ ثابت", "VOLUME_TIER": "پلکانیِ حجمی"}
_ACCRUAL_STATUS_LABELS = {"ACCRUING": "درحالِ تجمیع", "SETTLED": "تسویه‌شده"}


class CommercialPurchasingExtrasScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._suppliers: list[dict] = []
        self._items: list[catalog_service.ItemRow] = []
        self._selected_agreement_id: int | None = None
        self._selected_accrual_id: int | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(12)

        title = QLabel("بهایِ تمام‌شدهٔ وارداتی و ریبیتِ تامین‌کننده")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._build_landed_cost_tab(), "بهایِ تمام‌شدهٔ وارداتی")
        tabs.addTab(self._build_rebate_tab(), "ریبیتِ تامین‌کننده")
        outer.addWidget(tabs, stretch=1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    # --- بهایِ تمام‌شدهٔ وارداتی ---------------------------------------------
    def _build_landed_cost_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)

        self.landed_invoice_combo = QComboBox()
        self.landed_invoice_combo.currentIndexChanged.connect(self._refresh_landed_costs)
        outer.addWidget(self.landed_invoice_combo)

        self.landed_cost_table = QTableWidget(0, 4)
        self.landed_cost_table.setHorizontalHeaderLabels(["نوعِ هزینه", "مبلغ", "روشِ تسهیم", "توضیحات"])
        self.landed_cost_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.landed_cost_table.verticalHeader().setVisible(False)
        self.landed_cost_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        outer.addWidget(self.landed_cost_table, stretch=1)

        form = QHBoxLayout()
        self.landed_cost_type_combo = QComboBox()
        for code, label in _COST_TYPE_LABELS.items():
            self.landed_cost_type_combo.addItem(label, code)
        form.addWidget(self.landed_cost_type_combo)
        self.landed_amount_field = QLineEdit()
        self.landed_amount_field.setPlaceholderText("مبلغ")
        form.addWidget(self.landed_amount_field)
        self.landed_method_combo = QComboBox()
        for code, label in _ALLOCATION_METHOD_LABELS.items():
            self.landed_method_combo.addItem(label, code)
        form.addWidget(self.landed_method_combo)
        self.landed_notes_field = QLineEdit()
        self.landed_notes_field.setPlaceholderText("توضیحات (اختیاری)")
        form.addWidget(self.landed_notes_field, stretch=1)
        add_button = QPushButton("+ هزینهٔ تازه")
        add_button.setObjectName("primaryButton")
        add_button.clicked.connect(self._add_landed_cost)
        form.addWidget(add_button)
        outer.addLayout(form)

        apply_row = QHBoxLayout()
        apply_button = QPushButton("اعمالِ هزینه‌هایِ تمام‌شده رویِ ردیف‌هایِ فاکتور")
        apply_button.setObjectName("primaryButton")
        apply_button.clicked.connect(self._apply_landed_costs)
        apply_row.addWidget(apply_button)
        apply_row.addStretch(1)
        outer.addLayout(apply_row)

        self.landed_status_label = QLabel("")
        self.landed_status_label.setObjectName("statusError")
        outer.addWidget(self.landed_status_label)
        return page

    def _refresh_landed_costs(self) -> None:
        self.landed_cost_table.setRowCount(0)
        document_id = self.landed_invoice_combo.currentData()
        if document_id is None:
            return
        allocations = purchasing_service.list_landed_cost_allocations(document_id)
        self.landed_cost_table.setRowCount(len(allocations))
        for row_index, a in enumerate(allocations):
            values = [
                _COST_TYPE_LABELS.get(a.cost_type_code, a.cost_type_code), str(a.amount),
                _ALLOCATION_METHOD_LABELS.get(a.allocation_method_code, a.allocation_method_code), a.notes or "",
            ]
            for col_index, value in enumerate(values):
                self.landed_cost_table.setItem(row_index, col_index, QTableWidgetItem(value))

    def _add_landed_cost(self) -> None:
        document_id = self.landed_invoice_combo.currentData()
        if document_id is None:
            self.landed_status_label.setText("ابتدا یک فاکتورِ خریدِ پیش‌نویس را انتخاب کنید.")
            return
        try:
            amount = decimal.Decimal(self.landed_amount_field.text().strip() or "0")
        except decimal.InvalidOperation:
            self.landed_status_label.setText("مبلغ نامعتبر است.")
            return
        if amount <= 0:
            self.landed_status_label.setText("مبلغ باید بزرگ‌تر از صفر باشد.")
            return
        try:
            purchasing_service.add_landed_cost_allocation(
                document_id, self.landed_cost_type_combo.currentData(), amount, self.landed_method_combo.currentData(),
                notes=self.landed_notes_field.text().strip() or None,
            )
        except ValueError as exc:
            self.landed_status_label.setText(str(exc))
            return
        self.landed_amount_field.clear()
        self.landed_notes_field.clear()
        self.landed_status_label.setText("")
        self._refresh_landed_costs()

    def _apply_landed_costs(self) -> None:
        company_id = self._company_id()
        document_id = self.landed_invoice_combo.currentData()
        if company_id is None or document_id is None:
            self.landed_status_label.setText("ابتدا یک فاکتورِ خریدِ پیش‌نویس را انتخاب کنید.")
            return
        try:
            purchasing_service.apply_landed_costs(document_id, company_id)
        except ValueError as exc:
            self.landed_status_label.setText(str(exc))
            return
        self.landed_status_label.setText("هزینه‌هایِ تمام‌شده رویِ بهایِ واحدِ ردیف‌ها اعمال شد.")

    # --- ریبیتِ تامین‌کننده -----------------------------------------------
    def _build_rebate_tab(self) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)

        left = QVBoxLayout()
        left.addWidget(QLabel("قراردادهایِ ریبیت"))
        self.agreement_table = QTableWidget(0, 4)
        self.agreement_table.setHorizontalHeaderLabels(["تامین‌کننده", "مبنا", "ازتاریخ", "تاتاریخ"])
        self.agreement_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.agreement_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.agreement_table.verticalHeader().setVisible(False)
        self.agreement_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.agreement_table.cellClicked.connect(self._on_agreement_selected)
        left.addWidget(self.agreement_table, stretch=1)

        agreement_form = QVBoxLayout()
        self.rebate_supplier_combo = QComboBox()
        agreement_form.addWidget(self.rebate_supplier_combo)
        self.rebate_item_combo = QComboBox()
        self.rebate_item_combo.addItem("(همهٔ کالاها)", None)
        agreement_form.addWidget(self.rebate_item_combo)
        self.rebate_basis_combo = QComboBox()
        for code, label in _REBATE_BASIS_LABELS.items():
            self.rebate_basis_combo.addItem(label, code)
        agreement_form.addWidget(self.rebate_basis_combo)
        self.rebate_valid_from_field = QDateEdit()
        self.rebate_valid_from_field.setCalendarPopup(True)
        self.rebate_valid_from_field.setDate(datetime.date.today())
        agreement_form.addWidget(self.rebate_valid_from_field)
        add_agreement_button = QPushButton("+ قراردادِ تازه")
        add_agreement_button.setObjectName("primaryButton")
        add_agreement_button.clicked.connect(self._add_agreement)
        agreement_form.addWidget(add_agreement_button)
        left.addLayout(agreement_form)

        left.addWidget(QLabel("پله‌هایِ قراردادِ انتخاب‌شده"))
        self.tier_table = QTableWidget(0, 2)
        self.tier_table.setHorizontalHeaderLabels(["حداقلِ خرید", "درصدِ ریبیت"])
        self.tier_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tier_table.verticalHeader().setVisible(False)
        self.tier_table.setMaximumHeight(120)
        left.addWidget(self.tier_table)
        tier_form = QHBoxLayout()
        self.tier_min_field = QLineEdit()
        self.tier_min_field.setPlaceholderText("حداقلِ مبلغِ خرید")
        tier_form.addWidget(self.tier_min_field)
        self.tier_percent_field = QLineEdit()
        self.tier_percent_field.setPlaceholderText("درصدِ ریبیت")
        tier_form.addWidget(self.tier_percent_field)
        add_tier_button = QPushButton("+ پله")
        add_tier_button.clicked.connect(self._add_tier)
        tier_form.addWidget(add_tier_button)
        left.addLayout(tier_form)
        outer.addLayout(left, stretch=3)

        right = QVBoxLayout()
        right.addWidget(QLabel("محاسبهٔ ریبیت برایِ فاکتورِ Postشده"))
        self.rebate_invoice_combo = QComboBox()
        right.addWidget(self.rebate_invoice_combo)
        period_row = QHBoxLayout()
        self.rebate_period_from_field = QDateEdit()
        self.rebate_period_from_field.setCalendarPopup(True)
        self.rebate_period_from_field.setDate(datetime.date.today().replace(day=1))
        period_row.addWidget(self.rebate_period_from_field)
        self.rebate_period_to_field = QDateEdit()
        self.rebate_period_to_field.setCalendarPopup(True)
        self.rebate_period_to_field.setDate(datetime.date.today())
        period_row.addWidget(self.rebate_period_to_field)
        right.addLayout(period_row)
        accrue_button = QPushButton("محاسبهٔ تعهدِ ریبیت")
        accrue_button.clicked.connect(self._accrue_rebate)
        right.addWidget(accrue_button)

        right.addWidget(QLabel("تعهداتِ ریبیتِ درحالِ‌تجمیع/تسویه‌شده"))
        self.accrual_table = QTableWidget(0, 3)
        self.accrual_table.setHorizontalHeaderLabels(["دوره", "مبلغِ تعهد", "وضعیت"])
        self.accrual_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.accrual_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.accrual_table.verticalHeader().setVisible(False)
        self.accrual_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.accrual_table.cellClicked.connect(self._on_accrual_selected)
        right.addWidget(self.accrual_table, stretch=1)

        right.addWidget(QLabel("تسویهٔ تعهدِ انتخاب‌شده"))
        self.rebate_receivable_combo = QComboBox()
        right.addWidget(self.rebate_receivable_combo)
        self.purchase_discount_combo = QComboBox()
        right.addWidget(self.purchase_discount_combo)
        settle_button = QPushButton("تسویه (صدورِ سندِ حسابداری)")
        settle_button.setObjectName("primaryButton")
        settle_button.clicked.connect(self._settle_accrual)
        right.addWidget(settle_button)

        self.rebate_status_label = QLabel("")
        self.rebate_status_label.setObjectName("statusError")
        right.addWidget(self.rebate_status_label)
        right.addStretch(1)
        outer.addLayout(right, stretch=2)
        return page

    def _on_agreement_selected(self, row: int, _column: int) -> None:
        self._selected_agreement_id = self.agreement_table.item(row, 0).data(Qt.UserRole)
        self._refresh_tiers()
        self._refresh_accruals()

    def _add_agreement(self) -> None:
        supplier_id = self.rebate_supplier_combo.currentData()
        if supplier_id is None:
            self.rebate_status_label.setText("تامین‌کننده را انتخاب کنید.")
            return
        try:
            purchasing_service.create_rebate_agreement(
                supplier_id, self.rebate_basis_combo.currentData(), self.rebate_valid_from_field.date().toPython(),
                item_id=self.rebate_item_combo.currentData(),
            )
        except ValueError as exc:
            self.rebate_status_label.setText(str(exc))
            return
        self.rebate_status_label.setText("")
        self.refresh()

    def _refresh_tiers(self) -> None:
        self.tier_table.setRowCount(0)
        if self._selected_agreement_id is None:
            return
        tiers = purchasing_service.list_rebate_tiers(self._selected_agreement_id)
        self.tier_table.setRowCount(len(tiers))
        for row_index, t in enumerate(tiers):
            self.tier_table.setItem(row_index, 0, QTableWidgetItem(str(t.min_purchase_amount)))
            self.tier_table.setItem(row_index, 1, QTableWidgetItem(str(t.rebate_percent)))

    def _add_tier(self) -> None:
        if self._selected_agreement_id is None:
            self.rebate_status_label.setText("ابتدا یک قرارداد را از فهرست انتخاب کنید.")
            return
        try:
            min_amount = decimal.Decimal(self.tier_min_field.text().strip() or "0")
            percent = decimal.Decimal(self.tier_percent_field.text().strip() or "0")
        except decimal.InvalidOperation:
            self.rebate_status_label.setText("مقادیر نامعتبرند.")
            return
        if percent <= 0:
            self.rebate_status_label.setText("درصدِ ریبیت باید بزرگ‌تر از صفر باشد.")
            return
        purchasing_service.add_rebate_tier(self._selected_agreement_id, min_amount, percent)
        self.tier_min_field.clear()
        self.tier_percent_field.clear()
        self.rebate_status_label.setText("")
        self._refresh_tiers()

    def _on_accrual_selected(self, row: int, _column: int) -> None:
        self._selected_accrual_id = self.accrual_table.item(row, 0).data(Qt.UserRole)

    def _refresh_accruals(self) -> None:
        self.accrual_table.setRowCount(0)
        if self._selected_agreement_id is None:
            return
        accruals = purchasing_service.list_rebate_accruals(agreement_id=self._selected_agreement_id)
        self.accrual_table.setRowCount(len(accruals))
        for row_index, a in enumerate(accruals):
            values = [f"{a.period_from} تا {a.period_to}", str(a.accrued_amount), _ACCRUAL_STATUS_LABELS.get(a.status_code, a.status_code)]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, a.accrual_id)
                self.accrual_table.setItem(row_index, col_index, cell)

    def _accrue_rebate(self) -> None:
        company_id = self._company_id()
        document_id = self.rebate_invoice_combo.currentData()
        if company_id is None or document_id is None:
            self.rebate_status_label.setText("یک فاکتورِ Postشده را انتخاب کنید.")
            return
        period_from = self.rebate_period_from_field.date().toPython()
        period_to = self.rebate_period_to_field.date().toPython()
        try:
            purchasing_service.accrue_rebate_for_invoice(document_id, company_id, period_from, period_to)
        except ValueError as exc:
            self.rebate_status_label.setText(str(exc))
            return
        self.rebate_status_label.setText("")
        self._refresh_agreements()

    def _settle_accrual(self) -> None:
        company_id = self._company_id()
        receivable_id = self.rebate_receivable_combo.currentData()
        discount_id = self.purchase_discount_combo.currentData()
        if self._selected_accrual_id is None:
            self.rebate_status_label.setText("ابتدا یک تعهد را از فهرست انتخاب کنید.")
            return
        if company_id is None or receivable_id is None or discount_id is None:
            self.rebate_status_label.setText("حساب‌هایِ طرفینِ سند را انتخاب کنید.")
            return
        try:
            purchasing_service.settle_rebate_accrual(
                self._selected_accrual_id, company_id, app_session.current_user.user_id, receivable_id, discount_id,
            )
        except ValueError as exc:
            self.rebate_status_label.setText(str(exc))
            return
        self.rebate_status_label.setText("")
        self._refresh_accruals()

    # --- بارگذاریِ کلی -------------------------------------------------------
    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._suppliers = dimensions_service.list_suppliers(company_id)
        self._items = catalog_service.list_items(company_id, active_only=True)

        self.landed_invoice_combo.blockSignals(True)
        self.landed_invoice_combo.clear()
        for d in documents_service.list_documents(company_id, document_type_code="PURCHASE_INVOICE", status_code="DRAFT"):
            self.landed_invoice_combo.addItem(f"فاکتورِ شمارهٔ {d.document_no}", d.document_id)
        self.landed_invoice_combo.blockSignals(False)
        self._refresh_landed_costs()

        self.rebate_invoice_combo.clear()
        for d in documents_service.list_documents(company_id, document_type_code="PURCHASE_INVOICE", status_code="POSTED"):
            self.rebate_invoice_combo.addItem(f"فاکتورِ شمارهٔ {d.document_no}", d.document_id)

        self.rebate_supplier_combo.clear()
        for s in self._suppliers:
            self.rebate_supplier_combo.addItem(f"{s['code']} — {s['name'] or ''}", s["detail_account_id"])

        self.rebate_item_combo.clear()
        self.rebate_item_combo.addItem("(همهٔ کالاها)", None)
        for it in self._items:
            self.rebate_item_combo.addItem(f"{it.code} — {it.name or ''}", it.item_id)

        postable_accounts = [(a.account_id, f"{a.full_code} — {a.name}") for a in coa_service.list_accounts(company_id) if a.is_postable]
        self.rebate_receivable_combo.clear()
        self.purchase_discount_combo.clear()
        for account_id, label in postable_accounts:
            self.rebate_receivable_combo.addItem(label, account_id)
            self.purchase_discount_combo.addItem(label, account_id)

        self._refresh_agreements()

    def _refresh_agreements(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        suppliers_by_id = {s["detail_account_id"]: s for s in self._suppliers}
        agreements = purchasing_service.list_rebate_agreements(company_id)
        self.agreement_table.setRowCount(len(agreements))
        for row_index, a in enumerate(agreements):
            supplier = suppliers_by_id.get(a.supplier_detail_account_id)
            values = [
                f"{supplier['code']} — {supplier['name'] or ''}" if supplier else str(a.supplier_detail_account_id),
                _REBATE_BASIS_LABELS.get(a.rebate_basis_code, a.rebate_basis_code), str(a.valid_from), str(a.valid_to or ""),
            ]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, a.agreement_id)
                self.agreement_table.setItem(row_index, col_index, cell)
        self._refresh_tiers()
        self._refresh_accruals()
