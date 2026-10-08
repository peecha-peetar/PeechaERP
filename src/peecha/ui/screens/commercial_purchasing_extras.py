"""تخفیف حجمی تامین‌کننده — قراردادها/پله‌ها/تعهدات تخفیف حجمی تامین‌کننده
(مرحلهٔ ۴). طبق درخواست صریح («فرم تسهیم هزینه روی خود فاکتور
خرید»)، هزینه‌های جانبی خرید دیگر این‌جا مدیریت نمی‌شوند — از دکمهٔ
«🧮 هزینه‌های جانبی» روی خود فرم فاکتور خرید (commercial_document.py)
قابل‌دسترسی است."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals
from peecha import session as app_session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_purchasing as purchasing_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.db.models.commercial import VendorRebateAgreement, VendorRebateTier
from peecha.ui.widgets import (
    FieldGrid, FieldHelpMixin, FieldSpec, JalaliDateEdit, LayoutEditMixin, confirm_and_delete, delete_button, wrap_scrollable,
)

_REBATE_BASIS_LABELS = {"FLAT_PERCENT": "درصد ثابت", "VOLUME_TIER": "پلکانی حجمی"}
_ACCRUAL_STATUS_LABELS = {"ACCRUING": "درحال تجمیع", "SETTLED": "تسویه‌شده"}


class CommercialPurchasingExtrasScreen(FieldHelpMixin, LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._suppliers: list[dict] = []
        self._items: list[catalog_service.ItemRow] = []
        self._selected_agreement_id: int | None = None
        self._selected_accrual_id: int | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("تخفیف حجمی تامین‌کننده")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        outer.addWidget(self._build_rebate_tab(), stretch=1)

        self.set_field_help([
            (self.rebate_supplier_combo, "تامین‌کننده‌ای که این قرارداد تخفیف حجمی با اوست."),
            (self.rebate_item_combo, "این قرارداد فقط روی یک کالای خاص اعمال شود — خالی یعنی روی همهٔ خریدها از این تامین‌کننده."),
            (self.rebate_basis_combo, "نحوهٔ محاسبهٔ تخفیف حجمی — درصد ثابت، یا پلکانی بر اساس حجم خرید."),
            (self.rebate_valid_from_field, "تاریخ شروع اعتبار این قرارداد."),
            (self.tier_min_field, "حداقل مبلغ خرید دوره که این پله از آن به بعد اعمال می‌شود."),
            (self.tier_percent_field, "درصد تخفیف حجمی همین پله."),
            (self.rebate_invoice_combo, "فاکتور خرید ثبت‌نهایی‌شده‌ای که تعهد تخفیف حجمیش محاسبه می‌شود."),
            (self.rebate_period_from_field, "ابتدای دورهٔ محاسبهٔ تخفیف حجمی."),
            (self.rebate_period_to_field, "انتهای دورهٔ محاسبهٔ تخفیف حجمی."),
            (self.rebate_receivable_combo, "حساب طلب تخفیف حجمی که در سند تسویه بدهکار می‌شود."),
            (self.purchase_discount_combo, "حساب تخفیف خرید که در سند تسویه بستانکار می‌شود."),
        ])

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    # --- ریبیتِ تامین‌کننده -----------------------------------------------
    def _build_rebate_tab(self) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)

        left = QVBoxLayout()
        left.addWidget(QLabel("قراردادهای تخفیف حجمی"))
        self.agreement_table = QTableWidget(0, 4)
        self.agreement_table.setHorizontalHeaderLabels(["تامین‌کننده", "مبنا", "ازتاریخ", "تاتاریخ"])
        self.agreement_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.agreement_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.agreement_table.verticalHeader().setVisible(False)
        self.agreement_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.agreement_table.cellClicked.connect(self._on_agreement_selected)
        left.addWidget(self.agreement_table, stretch=1)

        self.rebate_supplier_combo = QComboBox()
        self.rebate_item_combo = QComboBox()
        self.rebate_item_combo.addItem("(همهٔ کالاها)", None)
        self.rebate_basis_combo = QComboBox()
        for code, label in _REBATE_BASIS_LABELS.items():
            self.rebate_basis_combo.addItem(label, code)
        self.rebate_valid_from_field = JalaliDateEdit()
        self.rebate_valid_from_field.setDate(datetime.date.today())
        self.agreement_form_grid = FieldGrid([
            FieldSpec("supplier", "تامین‌کننده", self.rebate_supplier_combo, span=2),
            FieldSpec("item", "کالا", self.rebate_item_combo, span=2),
            FieldSpec("basis", "مبنا", self.rebate_basis_combo, span=1),
            FieldSpec("valid_from", "ازتاریخ", self.rebate_valid_from_field, span=1),
        ])
        self.register_field_grids("commercial_purchasing_rebate_agreement", [self.agreement_form_grid])
        agreement_form = QVBoxLayout()
        agreement_form.addWidget(self.agreement_form_grid)
        add_agreement_button = QPushButton("➕")
        add_agreement_button.setObjectName("primaryIconButton")
        add_agreement_button.setFixedWidth(48)
        add_agreement_button.setToolTip("قرارداد تازه")
        add_agreement_button.clicked.connect(self._add_agreement)
        # R276: ویرایش/حذفِ قراردادِ انتخاب‌شده
        agreement_buttons = QHBoxLayout()
        agreement_buttons.addWidget(add_agreement_button)
        save_agreement_button = QPushButton("💾")
        save_agreement_button.setObjectName("iconButton")
        save_agreement_button.setFixedWidth(44)
        save_agreement_button.setToolTip("ذخیرهٔ تغییرات قرارداد انتخاب‌شده")
        save_agreement_button.clicked.connect(self._update_agreement)
        agreement_buttons.addWidget(save_agreement_button)
        delete_agreement_button = delete_button("حذف قرارداد انتخاب‌شده (با پله‌هایش)")
        delete_agreement_button.clicked.connect(self._delete_agreement)
        agreement_buttons.addWidget(delete_agreement_button)
        agreement_buttons.addStretch(1)
        agreement_form.addLayout(agreement_buttons)
        left.addLayout(agreement_form)

        left.addWidget(QLabel("پله‌های قرارداد انتخاب‌شده"))
        self.tier_table = QTableWidget(0, 2)
        self.tier_table.setHorizontalHeaderLabels(["حداقل خرید", "درصد تخفیف حجمی"])
        self.tier_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tier_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tier_table.verticalHeader().setVisible(False)
        self.tier_table.setMaximumHeight(120)
        left.addWidget(self.tier_table)
        tier_form = QHBoxLayout()
        self.tier_min_field = QLineEdit()
        self.tier_min_field.setPlaceholderText("حداقل مبلغ خرید")
        tier_form.addWidget(self.tier_min_field)
        self.tier_percent_field = QLineEdit()
        self.tier_percent_field.setPlaceholderText("درصد تخفیف حجمی")
        tier_form.addWidget(self.tier_percent_field)
        add_tier_button = QPushButton("➕")
        add_tier_button.setObjectName("iconButton")
        add_tier_button.setFixedWidth(44)
        add_tier_button.setToolTip("پله")
        add_tier_button.clicked.connect(self._add_tier)
        tier_form.addWidget(add_tier_button)
        delete_tier_button = delete_button("حذف پلهٔ انتخاب‌شده")
        delete_tier_button.clicked.connect(self._delete_tier)
        tier_form.addWidget(delete_tier_button)
        left.addLayout(tier_form)
        outer.addLayout(left, stretch=3)

        right = QVBoxLayout()
        right.addWidget(QLabel("محاسبهٔ تخفیف حجمی برای فاکتور Postشده"))
        self.rebate_invoice_combo = QComboBox()
        right.addWidget(self.rebate_invoice_combo)
        period_row = QHBoxLayout()
        self.rebate_period_from_field = JalaliDateEdit()
        self.rebate_period_from_field.setDate(datetime.date.today().replace(day=1))
        period_row.addWidget(self.rebate_period_from_field)
        self.rebate_period_to_field = JalaliDateEdit()
        self.rebate_period_to_field.setDate(datetime.date.today())
        period_row.addWidget(self.rebate_period_to_field)
        right.addLayout(period_row)
        accrue_button = QPushButton("🧮")
        accrue_button.setObjectName("iconButton")
        accrue_button.setFixedWidth(44)
        accrue_button.setToolTip("محاسبهٔ تعهد تخفیف حجمی")
        accrue_button.clicked.connect(self._accrue_rebate)
        right.addWidget(accrue_button)

        right.addWidget(QLabel("تعهدات تخفیف حجمی درحال‌تجمیع/تسویه‌شده"))
        self.accrual_table = QTableWidget(0, 3)
        self.accrual_table.setHorizontalHeaderLabels(["دوره", "مبلغ تعهد", "وضعیت"])
        self.accrual_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.accrual_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.accrual_table.verticalHeader().setVisible(False)
        self.accrual_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.accrual_table.cellClicked.connect(self._on_accrual_selected)
        right.addWidget(self.accrual_table, stretch=1)

        right.addWidget(QLabel("تسویهٔ تعهد انتخاب‌شده"))
        self.rebate_receivable_combo = QComboBox()
        right.addWidget(self.rebate_receivable_combo)
        self.purchase_discount_combo = QComboBox()
        right.addWidget(self.purchase_discount_combo)
        settle_button = QPushButton("💳")
        settle_button.setObjectName("primaryIconButton")
        settle_button.setFixedWidth(48)
        settle_button.setToolTip("تسویه (صدور سند حسابداری)")
        settle_button.clicked.connect(self._settle_accrual)
        right.addWidget(settle_button)

        self.rebate_status_label = QLabel("")
        self.rebate_status_label.setObjectName("statusError")
        right.addWidget(self.rebate_status_label)
        right.addStretch(1)
        outer.addLayout(right, stretch=2)
        return wrap_scrollable(page)

    def _on_agreement_selected(self, row: int, _column: int) -> None:
        self._selected_agreement_id = self.agreement_table.item(row, 0).data(Qt.UserRole)
        agreement = next((a for a in getattr(self, "_agreements", []) if a.agreement_id == self._selected_agreement_id), None)
        if agreement is not None:
            for combo, value in ((self.rebate_supplier_combo, agreement.supplier_detail_account_id),
                                 (self.rebate_item_combo, agreement.item_id), (self.rebate_basis_combo, agreement.rebate_basis_code)):
                combo.setCurrentIndex(max(0, combo.findData(value)))
            self.rebate_valid_from_field.setDate(agreement.valid_from)
        self._refresh_tiers()
        self._refresh_accruals()

    def _add_agreement(self) -> None:
        supplier_id = self.rebate_supplier_combo.currentData()
        if supplier_id is None:
            self.rebate_status_label.setText("تامین‌کننده را انتخاب کنید.")
            return
        try:
            purchasing_service.create_rebate_agreement(
                supplier_id, self.rebate_basis_combo.currentData(), self.rebate_valid_from_field.date(),
                item_id=self.rebate_item_combo.currentData(),
            )
        except ValueError as exc:
            self.rebate_status_label.setText(str(exc))
            return
        self.rebate_status_label.setText("")
        self.refresh()

    def _update_agreement(self) -> None:
        if self._selected_agreement_id is None:
            self.rebate_status_label.setText("ابتدا یک قرارداد را از فهرست انتخاب کنید.")
            return
        try:
            purchasing_service.update_rebate_agreement(
                self._selected_agreement_id, self.rebate_basis_combo.currentData(), self.rebate_valid_from_field.date(),
                item_id=self.rebate_item_combo.currentData())
        except ValueError as exc:
            self.rebate_status_label.setText(str(exc))
            return
        self.rebate_status_label.setText("قرارداد ذخیره شد.")
        self.refresh()

    def _delete_agreement(self) -> None:
        if confirm_and_delete(self, "قرارداد تخفیف حجمی", "قرارداد انتخاب‌شده", VendorRebateAgreement, self._selected_agreement_id,
                              None, children=((VendorRebateTier, "agreement_id"),)):
            self._selected_agreement_id = None
            self.refresh()
            self._refresh_tiers()

    def _delete_tier(self) -> None:
        row = self.tier_table.currentRow()
        tier_id = self.tier_table.item(row, 0).data(Qt.UserRole) if row >= 0 and self.tier_table.item(row, 0) else None
        confirm_and_delete(self, "پلهٔ تخفیف حجمی", "پلهٔ انتخاب‌شده", VendorRebateTier, tier_id, None, self._refresh_tiers)

    def _refresh_tiers(self) -> None:
        self.tier_table.setRowCount(0)
        if self._selected_agreement_id is None:
            return
        tiers = purchasing_service.list_rebate_tiers(self._selected_agreement_id)
        self.tier_table.setRowCount(len(tiers))
        for row_index, t in enumerate(tiers):
            first = QTableWidgetItem(str(t.min_purchase_amount))
            first.setData(Qt.UserRole, t.tier_id)
            self.tier_table.setItem(row_index, 0, first)
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
            self.rebate_status_label.setText("درصد تخفیف حجمی باید بزرگ‌تر از صفر باشد.")
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
            self.rebate_status_label.setText("یک فاکتور Postشده را انتخاب کنید.")
            return
        period_from = self.rebate_period_from_field.date()
        period_to = self.rebate_period_to_field.date()
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
            self.rebate_status_label.setText("حساب‌های طرفین سند را انتخاب کنید.")
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

        self.rebate_invoice_combo.clear()
        for d in documents_service.list_documents(company_id, document_type_code="PURCHASE_INVOICE", status_code="POSTED"):
            self.rebate_invoice_combo.addItem(f"فاکتور شمارهٔ {d.document_no}", d.document_id)

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
        self._agreements = agreements
        self.agreement_table.setRowCount(len(agreements))
        for row_index, a in enumerate(agreements):
            supplier = suppliers_by_id.get(a.supplier_detail_account_id)
            values = [
                f"{supplier['code']} — {supplier['name'] or ''}" if supplier else str(a.supplier_detail_account_id),
                _REBATE_BASIS_LABELS.get(a.rebate_basis_code, a.rebate_basis_code),
                numerals.format_jalali_date(a.valid_from), numerals.format_jalali_date(a.valid_to) if a.valid_to else "",
            ]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, a.agreement_id)
                self.agreement_table.setItem(row_index, col_index, cell)
        self._refresh_tiers()
        self._refresh_accruals()
