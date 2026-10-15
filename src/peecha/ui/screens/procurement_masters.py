"""اطلاعات پایهٔ تدارکات — R240: انواع خرید، علت‌های لغو، سیاست سفارش کالا."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QCompleter, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from peecha import decimals, numerals, session
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.db.models.commercial import Branch, CancellationReason, PurchaseType
from peecha.services import procurement_masters as masters_service
from peecha.ui.screens import module_style as ms
from peecha.ui.widgets import confirm_and_delete, delete_button


def _company_id() -> int | None:
    return session.current_company.company_id if session.current_company else None


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    return table


def _fill_table(table: QTableWidget, rows: list[list]) -> None:
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.setItem(r, c, QTableWidgetItem(numerals.to_persian_digits("" if value is None else str(value))))


def _qty(value) -> str:
    return "" if value is None else decimals.format_qty(value)


class _CodeNameTab(QWidget):
    """جدول + فرم کد/عنوان/فعال (و در صورت نیاز «اضطراری»)."""

    def __init__(self, headers: list[str], with_emergency: bool) -> None:
        super().__init__()
        self._with_emergency = with_emergency
        self._rows: list = []
        self._editing_id: int | None = None
        layout = QVBoxLayout(self)
        self.table = _table(headers)
        self.table.itemSelectionChanged.connect(self._load_selected)
        layout.addWidget(self.table, stretch=1)
        form = QHBoxLayout()
        self.code_field, self.name_field = QLineEdit(), QLineEdit()
        self.code_field.setMaximumWidth(140)
        self.emergency_check = QCheckBox("اضطراری")
        self.active_check = QCheckBox("فعال")
        self.active_check.setChecked(True)
        for text, widget in (("کد:", self.code_field), ("عنوان:", self.name_field)):
            form.addWidget(QLabel(text))
            form.addWidget(widget)
        if with_emergency:
            form.addWidget(self.emergency_check)
        form.addWidget(self.active_check)
        form.addStretch(1)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        save_button, new_button = ms.style_button(QPushButton("ذخیره")), ms.style_button(QPushButton("جدید"))
        new_button.clicked.connect(self.clear_form)
        save_button.clicked.connect(self.save)
        buttons.addWidget(save_button)
        buttons.addWidget(new_button)
        # R276: حذفِ ردیفِ انتخاب‌شده (اگر استفاده شده باشد غیرفعال می‌شود)
        remove = delete_button()
        remove.clicked.connect(self.delete)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    MODEL = None

    def delete(self) -> None:
        if confirm_and_delete(self, "حذف", self.name_field.text(), self.MODEL, self._editing_id, _company_id()):
            self.clear_form()
            self.refresh()

    def clear_form(self) -> None:
        self._editing_id = None
        self.code_field.clear()
        self.name_field.clear()
        self.emergency_check.setChecked(False)
        self.active_check.setChecked(True)
        self.table.clearSelection()

    def _load_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(self._rows):
            return
        row = self._rows[rows[0].row()]
        self._editing_id = self.row_id(row)
        self.code_field.setText(row.code)
        self.name_field.setText(row.name)
        self.emergency_check.setChecked(bool(getattr(row, "is_emergency", False)))
        self.active_check.setChecked(row.is_active)

    def save(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        try:
            self.persist(company_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.clear_form()
        self.refresh()

    def row_id(self, row) -> int:
        raise NotImplementedError

    def persist(self, company_id: int) -> None:
        raise NotImplementedError

    def refresh(self) -> None:
        raise NotImplementedError


class _PurchaseTypesTab(_CodeNameTab):
    MODEL = PurchaseType

    def __init__(self) -> None:
        super().__init__(["کد", "عنوان", "اضطراری", "فعال"], with_emergency=True)

    def row_id(self, row) -> int:
        return row.purchase_type_id

    def persist(self, company_id: int) -> None:
        masters_service.save_purchase_type(company_id, self.code_field.text(), self.name_field.text(),
                                           self.emergency_check.isChecked(), self.active_check.isChecked(), self._editing_id)

    def refresh(self) -> None:
        company_id = _company_id()
        self._rows = masters_service.list_purchase_types(company_id) if company_id else []
        _fill_table(self.table, [[r.code, r.name, "بله" if r.is_emergency else "خیر", "بله" if r.is_active else "خیر"]
                                 for r in self._rows])


class _CancelReasonsTab(_CodeNameTab):
    MODEL = CancellationReason

    def __init__(self) -> None:
        super().__init__(["کد", "عنوان", "فعال"], with_emergency=False)

    def row_id(self, row) -> int:
        return row.reason_id

    def persist(self, company_id: int) -> None:
        masters_service.save_cancellation_reason(company_id, self.code_field.text(), self.name_field.text(),
                                                 self.active_check.isChecked(), self._editing_id)

    def refresh(self) -> None:
        company_id = _company_id()
        self._rows = masters_service.list_cancellation_reasons(company_id) if company_id else []
        _fill_table(self.table, [[r.code, r.name, "بله" if r.is_active else "خیر"] for r in self._rows])


class _BranchesTab(_CodeNameTab):
    """R244: شعبه‌ها و اختصاص انبارها به شعبه (سند بدون شعبه، شعبهٔ انبارش را می‌گیرد)."""

    MODEL = Branch

    def __init__(self) -> None:
        super().__init__(["کد", "نام", "فعال", "انبارها"], with_emergency=False)
        box = QHBoxLayout()
        box.addWidget(QLabel("انبار:"))
        self.warehouse_combo = QComboBox()
        box.addWidget(self.warehouse_combo)
        box.addWidget(QLabel("شعبه:"))
        self.assign_branch_combo = QComboBox()
        box.addWidget(self.assign_branch_combo)
        assign = QPushButton("اختصاص انبار به شعبه")
        assign.clicked.connect(self.assign_warehouse)
        box.addWidget(assign)
        box.addStretch(1)
        self.layout().addLayout(box)

    def row_id(self, row) -> int:
        return row.branch_id

    def persist(self, company_id: int) -> None:
        masters_service.save_branch(company_id, self.code_field.text(), self.name_field.text(), None, self.active_check.isChecked(),
                                    self._editing_id)

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        self._rows = masters_service.list_branches(company_id)
        self._warehouses = locations_service.list_warehouses(company_id)
        from peecha.db.base import new_session
        from peecha.db.models.inventory import Warehouse

        with new_session() as session:
            branch_of = {w.warehouse_id: session.get(Warehouse, w.warehouse_id).branch_id for w in self._warehouses}
        self._branch_of = branch_of
        _fill_table(self.table, [[r.code, r.name, "بله" if r.is_active else "خیر",
                                  "، ".join(w.name for w in self._warehouses if branch_of.get(w.warehouse_id) == r.branch_id)]
                                 for r in self._rows])
        self.warehouse_combo.clear()
        for w in self._warehouses:
            self.warehouse_combo.addItem(w.name, w.warehouse_id)
        self.assign_branch_combo.clear()
        self.assign_branch_combo.addItem("— بدون شعبه —", None)
        for r in self._rows:
            self.assign_branch_combo.addItem(r.name, r.branch_id)

    def assign_warehouse(self) -> None:
        company_id = _company_id()
        if company_id is None or self.warehouse_combo.currentData() is None:
            return
        masters_service.set_warehouse_branch(company_id, self.warehouse_combo.currentData(), self.assign_branch_combo.currentData())
        self.refresh()


class _ReorderPoliciesTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list = []
        self._editing_id: int | None = None
        self._items: dict[int, str] = {}
        self._warehouses: dict[int, str] = {}
        layout = QVBoxLayout(self)
        hint = QLabel("حداقل ≤ نقطهٔ سفارش < حداکثر. این مقادیر در گزارش‌های «وضعیت موجودی»، «پیشنهاد خرید» و "
                      "«تحلیل نقطهٔ سفارش» استفاده می‌شوند؛ کالای بدون سیاست از پیش‌فرض انبار پیروی می‌کند.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = _table(["کالا", "انبار", "حداقل", "نقطهٔ سفارش", "حداکثر", "مقدار سفارش", "زمان تحویل (روز)", "فعال"])
        self.table.itemSelectionChanged.connect(self._load_selected)
        layout.addWidget(self.table, stretch=1)
        form = QHBoxLayout()
        self.item_combo = QComboBox()
        self.item_combo.setEditable(True)
        self.item_combo.setInsertPolicy(QComboBox.NoInsert)
        self.item_combo.setMinimumWidth(220)
        self.warehouse_combo = QComboBox()
        self.min_field, self.rop_field, self.max_field, self.qty_field = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        for field in (self.min_field, self.rop_field, self.max_field, self.qty_field):
            field.setMaximumWidth(90)
        self.lead_spin = QSpinBox()
        self.lead_spin.setRange(0, 365)
        self.active_check = QCheckBox("فعال")
        self.active_check.setChecked(True)
        for text, widget in (("کالا:", self.item_combo), ("انبار:", self.warehouse_combo), ("حداقل:", self.min_field),
                             ("نقطهٔ سفارش:", self.rop_field), ("حداکثر:", self.max_field), ("مقدار سفارش:", self.qty_field),
                             ("زمان تحویل:", self.lead_spin)):
            form.addWidget(QLabel(text))
            form.addWidget(widget)
        form.addWidget(self.active_check)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        for text, slot in (("ذخیره", self.save), ("جدید", self.clear_form), ("حذف", self.delete)):
            button = ms.style_button(QPushButton(text))
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        self._items = {i.item_id: f"{i.code} — {i.name or ''}" for i in catalog_service.list_items(company_id, transactable_only=True)
                       if i.is_stock_tracked}
        self._warehouses = {w.warehouse_id: f"{w.code} — {w.name}" for w in locations_service.list_warehouses(company_id)}
        self.item_combo.clear()
        for item_id, label in self._items.items():
            self.item_combo.addItem(numerals.to_persian_digits(label), item_id)
        completer = QCompleter([self.item_combo.itemText(i) for i in range(self.item_combo.count())])
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.item_combo.setCompleter(completer)
        self.warehouse_combo.clear()
        self.warehouse_combo.addItem("همهٔ انبارها", None)
        for warehouse_id, label in self._warehouses.items():
            self.warehouse_combo.addItem(numerals.to_persian_digits(label), warehouse_id)
        self._rows = masters_service.list_reorder_policies(company_id)
        _fill_table(self.table, [[
            self._items.get(p.item_id, p.item_id), self._warehouses.get(p.warehouse_id, "همهٔ انبارها") if p.warehouse_id else "همهٔ انبارها",
            _qty(p.min_qty), _qty(p.reorder_point_qty), _qty(p.max_qty), _qty(p.reorder_qty), p.lead_time_days or "",
            "بله" if p.is_active else "خیر",
        ] for p in self._rows])

    def clear_form(self) -> None:
        self._editing_id = None
        for field in (self.min_field, self.rop_field, self.max_field, self.qty_field):
            field.clear()
        self.lead_spin.setValue(0)
        self.active_check.setChecked(True)
        self.warehouse_combo.setCurrentIndex(0)
        self.table.clearSelection()

    def _load_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(self._rows):
            return
        p = self._rows[rows[0].row()]
        self._editing_id = p.policy_id
        self.item_combo.setCurrentIndex(max(0, self.item_combo.findData(p.item_id)))
        self.warehouse_combo.setCurrentIndex(max(0, self.warehouse_combo.findData(p.warehouse_id)))
        for field, value in ((self.min_field, p.min_qty), (self.rop_field, p.reorder_point_qty), (self.max_field, p.max_qty),
                             (self.qty_field, p.reorder_qty)):
            field.setText(numerals.to_persian_digits(format(value.normalize(), "f")) if value is not None else "")
        self.lead_spin.setValue(p.lead_time_days or 0)
        self.active_check.setChecked(p.is_active)

    def fields(self) -> masters_service.PolicyFields:
        def number(field: QLineEdit):
            return numerals.parse_decimal(field.text()) if field.text().strip() else None

        return masters_service.PolicyFields(
            item_id=self.item_combo.currentData(), warehouse_id=self.warehouse_combo.currentData(),
            min_qty=number(self.min_field), max_qty=number(self.max_field), reorder_point_qty=number(self.rop_field),
            reorder_qty=number(self.qty_field), lead_time_days=self.lead_spin.value() or None, is_active=self.active_check.isChecked(),
        )

    def save(self) -> None:
        company_id = _company_id()
        if company_id is None or self.item_combo.currentData() is None:
            return
        try:
            masters_service.save_reorder_policy(company_id, self.fields(), self._editing_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.clear_form()
        self.refresh()

    def delete(self) -> None:
        company_id = _company_id()
        if company_id is None or self._editing_id is None:
            return
        if QMessageBox.question(self, "حذف", "این سیاست سفارش حذف شود؟") != QMessageBox.Yes:
            return
        masters_service.delete_reorder_policy(company_id, self._editing_id)
        self.clear_form()
        self.refresh()


class _BudgetsTab(QWidget):
    """R243: بودجهٔ خرید — مبلغ برای یک دوره و ترکیبی از مرکز هزینه/پروژه/گروه کالا (خالی = همه)."""

    def __init__(self) -> None:
        super().__init__()
        from peecha.ui.widgets import JalaliDateEdit

        self._rows: list = []
        self._editing_id: int | None = None
        layout = QVBoxLayout(self)
        hint = QLabel("مصرف = فاکتور ثبت‌شده − برگشت + ماندهٔ سفارش‌های باز. با رسیدن به درصد هشدار، پس از تایید سند خرید "
                      "پیام هشدار نمایش داده می‌شود (جلوی ثبت گرفته نمی‌شود).")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = _table(["کد", "نام", "از", "تا", "مرکز هزینه", "پروژه", "گروه کالا", "مبلغ", "مصرف‌شده", "درصد مصرف", "فعال"])
        self.table.itemSelectionChanged.connect(self._load_selected)
        layout.addWidget(self.table, stretch=1)
        form = QHBoxLayout()
        self.code_field, self.name_field, self.amount_field = QLineEdit(), QLineEdit(), QLineEdit()
        self.code_field.setMaximumWidth(100)
        self.from_field, self.to_field = JalaliDateEdit(), JalaliDateEdit()
        self.cost_center_combo, self.project_combo, self.category_combo = QComboBox(), QComboBox(), QComboBox()
        self.branch_combo, self.department_combo = QComboBox(), QComboBox()
        self.warn_spin = QSpinBox()
        self.warn_spin.setRange(1, 100)
        self.warn_spin.setValue(90)
        self.active_check = QCheckBox("فعال")
        self.active_check.setChecked(True)
        for text, widget in (("کد:", self.code_field), ("نام:", self.name_field), ("از:", self.from_field), ("تا:", self.to_field),
                             ("مرکز هزینه:", self.cost_center_combo), ("پروژه:", self.project_combo),
                             ("گروه کالا:", self.category_combo), ("شعبه:", self.branch_combo), ("دپارتمان:", self.department_combo),
                             ("مبلغ:", self.amount_field), ("هشدار٪:", self.warn_spin)):
            form.addWidget(QLabel(text))
            form.addWidget(widget)
        form.addWidget(self.active_check)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        for text, slot in (("ذخیره", self.save), ("جدید", self.clear_form), ("حذف", self.delete)):
            button = ms.style_button(QPushButton(text))
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def refresh(self) -> None:
        from peecha.services import detail_dimensions as dimensions_service
        from peecha.services import purchase_budgets as budgets_service

        company_id = _company_id()
        if company_id is None:
            return
        cc_type = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.COST_CENTER_CODE)
        pj_type = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.PROJECT_CODE)
        details = dimensions_service.list_all_detail_accounts(company_id)
        self._names = {d.detail_account_id: f"{d.full_code} — {d.name or ''}" for d in details}
        self._categories = {c.category_id: f"{c.code} — {c.name}" for c in catalog_service.list_categories(company_id)}
        for combo, options in ((self.cost_center_combo, [(d.detail_account_id, self._names[d.detail_account_id]) for d in details
                                                         if d.dimension_type_id == cc_type]),
                               (self.project_combo, [(d.detail_account_id, self._names[d.detail_account_id]) for d in details
                                                     if d.dimension_type_id == pj_type]),
                               (self.category_combo, list(self._categories.items())),
                               (self.branch_combo, [(b.branch_id, b.name) for b in masters_service.list_branches(company_id)]),
                               (self.department_combo, [(d.org_unit_id, d.name) for d in masters_service.list_departments(company_id)])):
            current = combo.currentData()
            combo.clear()
            combo.addItem("— همه —", None)
            for value, label in options:
                combo.addItem(numerals.to_persian_digits(label), value)
            combo.setCurrentIndex(max(0, combo.findData(current)))
        self._rows = budgets_service.list_budgets(company_id)
        usage = {u.budget.budget_id: u for u in budgets_service.usages(company_id, self._rows)}
        _fill_table(self.table, [[
            b.code, b.name, numerals.format_jalali_date(b.period_from), numerals.format_jalali_date(b.period_to),
            self._names.get(b.cost_center_detail_account_id, "همه"), self._names.get(b.project_detail_account_id, "همه"),
            self._categories.get(b.category_id, "همه"), decimals.format_amount(b.amount),
            decimals.format_amount(usage[b.budget_id].consumed), f"{numerals.format_money(usage[b.budget_id].used_percent, 1, None)}٪",
            "بله" if b.is_active else "خیر",
        ] for b in self._rows])

    def clear_form(self) -> None:
        import datetime

        self._editing_id = None
        for field in (self.code_field, self.name_field, self.amount_field):
            field.clear()
        today = datetime.date.today()
        self.from_field.setDate(today.replace(day=1))
        self.to_field.setDate(today + datetime.timedelta(days=365))
        for combo in (self.cost_center_combo, self.project_combo, self.category_combo, self.branch_combo, self.department_combo):
            combo.setCurrentIndex(0)
        self.warn_spin.setValue(90)
        self.active_check.setChecked(True)
        self.table.clearSelection()

    def _load_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(self._rows):
            return
        b = self._rows[rows[0].row()]
        self._editing_id = b.budget_id
        self.code_field.setText(b.code)
        self.name_field.setText(b.name)
        self.from_field.setDate(b.period_from)
        self.to_field.setDate(b.period_to)
        self.amount_field.setText(numerals.to_persian_digits(format(b.amount.normalize(), "f")))
        for combo, value in ((self.cost_center_combo, b.cost_center_detail_account_id), (self.project_combo, b.project_detail_account_id),
                             (self.category_combo, b.category_id), (self.branch_combo, b.branch_id),
                             (self.department_combo, b.org_unit_id)):
            combo.setCurrentIndex(max(0, combo.findData(value)))
        self.warn_spin.setValue(int(b.warn_percent))
        self.active_check.setChecked(b.is_active)

    def fields(self):
        import decimal

        from peecha.services import purchase_budgets as budgets_service

        return budgets_service.BudgetFields(
            code=self.code_field.text(), name=self.name_field.text(), period_from=self.from_field.date(), period_to=self.to_field.date(),
            amount=numerals.parse_decimal(self.amount_field.text()) if self.amount_field.text().strip() else decimal.Decimal(-1),
            cost_center_detail_account_id=self.cost_center_combo.currentData(), project_detail_account_id=self.project_combo.currentData(),
            category_id=self.category_combo.currentData(), warn_percent=decimal.Decimal(self.warn_spin.value()),
            branch_id=self.branch_combo.currentData(), org_unit_id=self.department_combo.currentData(),
            is_active=self.active_check.isChecked(),
        )

    def save(self) -> None:
        from peecha.services import purchase_budgets as budgets_service

        company_id = _company_id()
        if company_id is None:
            return
        try:
            budgets_service.save_budget(company_id, self.fields(), self._editing_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.clear_form()
        self.refresh()

    def delete(self) -> None:
        from peecha.services import purchase_budgets as budgets_service

        company_id = _company_id()
        if company_id is None or self._editing_id is None:
            return
        if QMessageBox.question(self, "حذف", "این بودجه حذف شود؟") != QMessageBox.Yes:
            return
        budgets_service.delete_budget(company_id, self._editing_id)
        self.clear_form()
        self.refresh()


class ProcurementMastersScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        title = QLabel("اطلاعات پایهٔ تدارکات")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.tabs = QTabWidget()
        self.purchase_types_tab = _PurchaseTypesTab()
        self.cancel_reasons_tab = _CancelReasonsTab()
        self.policies_tab = _ReorderPoliciesTab()
        self.tabs.addTab(self.purchase_types_tab, "انواع خرید")
        self.tabs.addTab(self.cancel_reasons_tab, "علت‌های لغو")
        self.tabs.addTab(self.policies_tab, "سیاست سفارش کالا")
        self.budgets_tab = _BudgetsTab()
        self.tabs.addTab(self.budgets_tab, "بودجهٔ خرید")
        self.branches_tab = _BranchesTab()
        self.tabs.addTab(self.branches_tab, "شعبه‌ها")
        layout.addWidget(self.tabs, stretch=1)

    def refresh(self) -> None:
        for tab in (self.purchase_types_tab, self.cancel_reasons_tab, self.policies_tab, self.budgets_tab, self.branches_tab):
            tab.refresh()
