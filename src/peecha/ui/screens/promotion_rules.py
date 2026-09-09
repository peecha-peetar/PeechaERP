"""پخشِ سرد/گرم -- R130: مدیریتِ پروموشن‌ها از دسکتاپ («بخر-ببر»/
تخفیفِ پلکانی). طبقِ طرحِ تاییدشده، در این فاز فقط تعریف/CRUD است --
اتصالِ زندهٔ این پروموشن‌ها به محاسبهٔ فاکتور یک گامِ جداگانه‌یِ آینده
است (services/promotions.py، R129)."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.services import inventory_catalog as catalog_service
from peecha.services import promotions as promotions_service
from peecha.ui.widgets import JalaliDateEdit, build_action_footer, wrap_scrollable

_COLUMNS = ["فعال", "کد", "نام", "نوع"]
_TYPE_LABELS = {"BUY_X_GET_Y": "بخر و ببر", "THRESHOLD_DISCOUNT": "تخفیفِ پلکانی"}
_CHANNEL_LABELS = {
    "POS": "حضوری", "WHOLESALE": "عمده", "ONLINE": "اینترنتی", "AGENT": "نماینده", "MARKETPLACE": "مارکت‌پلیس",
    "VAN_SALES": "پخشِ گرم", "PRE_SALES": "پخشِ سرد",
}


class PromotionRulesScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[promotions_service.PromotionRuleRow] = []
        self._items: list = []
        self._editing_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=3)

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        title = QLabel("پروموشن‌ها")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        new_button = QPushButton("➕")
        new_button.setObjectName("primaryIconButton")
        new_button.setFixedWidth(48)
        new_button.setToolTip("پروموشنِ جدید")
        new_button.clicked.connect(self._reset_form)
        layout.addWidget(new_button, alignment=Qt.AlignLeft)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)
        return wrap_scrollable(panel)

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        self.form_title = QLabel("پروموشنِ جدید")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        layout.addWidget(QLabel("کد"))
        self.code_field = QLineEdit()
        layout.addWidget(self.code_field)

        layout.addWidget(QLabel("نام"))
        self.name_field = QLineEdit()
        layout.addWidget(self.name_field)

        layout.addWidget(QLabel("نوع"))
        self.type_combo = QComboBox()
        for code, label in _TYPE_LABELS.items():
            self.type_combo.addItem(label, code)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        layout.addWidget(self.type_combo)

        layout.addWidget(QLabel("کانال (اختیاری -- خالی یعنی همهٔ کانال‌ها)"))
        self.channel_combo = QComboBox()
        self.channel_combo.addItem("(همهٔ کانال‌ها)", None)
        for code, label in _CHANNEL_LABELS.items():
            self.channel_combo.addItem(label, code)
        layout.addWidget(self.channel_combo)

        self.buy_get_row = QWidget()
        buy_get_layout = QVBoxLayout(self.buy_get_row)
        buy_get_layout.setContentsMargins(0, 0, 0, 0)
        buy_get_layout.addWidget(QLabel("کالایِ مشمولِ خرید"))
        self.applies_item_combo = QComboBox()
        buy_get_layout.addWidget(self.applies_item_combo)
        buy_get_layout.addWidget(QLabel("تعدادِ خرید"))
        self.buy_quantity_field = QDoubleSpinBox()
        self.buy_quantity_field.setRange(0.001, 999_999)
        self.buy_quantity_field.setDecimals(3)
        buy_get_layout.addWidget(self.buy_quantity_field)
        buy_get_layout.addWidget(QLabel("تعدادِ هدیه"))
        self.get_quantity_field = QDoubleSpinBox()
        self.get_quantity_field.setRange(0.001, 999_999)
        self.get_quantity_field.setDecimals(3)
        buy_get_layout.addWidget(self.get_quantity_field)
        buy_get_layout.addWidget(QLabel("کالایِ هدیه (اختیاری -- خالی یعنی همان کالا)"))
        self.get_item_combo = QComboBox()
        self.get_item_combo.addItem("(همان کالایِ خرید)", None)
        buy_get_layout.addWidget(self.get_item_combo)
        layout.addWidget(self.buy_get_row)

        self.threshold_row = QWidget()
        threshold_layout = QVBoxLayout(self.threshold_row)
        threshold_layout.setContentsMargins(0, 0, 0, 0)
        threshold_layout.addWidget(QLabel("سقفِ مبلغِ سند"))
        self.threshold_amount_field = QDoubleSpinBox()
        self.threshold_amount_field.setRange(0, 999_999_999_999)
        self.threshold_amount_field.setDecimals(0)
        threshold_layout.addWidget(self.threshold_amount_field)
        threshold_layout.addWidget(QLabel("درصدِ تخفیف"))
        self.discount_percent_field = QDoubleSpinBox()
        self.discount_percent_field.setRange(0.01, 100)
        self.discount_percent_field.setDecimals(2)
        threshold_layout.addWidget(self.discount_percent_field)
        layout.addWidget(self.threshold_row)

        dates_row = QHBoxLayout()
        dates_row.addWidget(QLabel("از تاریخ"))
        self.valid_from_field = JalaliDateEdit()
        dates_row.addWidget(self.valid_from_field)
        dates_row.addWidget(QLabel("تا تاریخ"))
        self.valid_to_field = JalaliDateEdit()
        dates_row.addWidget(self.valid_to_field)
        layout.addLayout(dates_row)

        self.is_active_checkbox = QCheckBox("فعال")
        self.is_active_checkbox.setChecked(True)
        layout.addWidget(self.is_active_checkbox)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

        save_button = QPushButton("💾")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(48)
        save_button.setToolTip("ذخیره")
        save_button.clicked.connect(self._save)

        cancel_button = QPushButton("↩️")
        cancel_button.setObjectName("iconButton")
        cancel_button.setFixedWidth(44)
        cancel_button.setToolTip("انصراف")
        cancel_button.clicked.connect(self._reset_form)

        self.delete_button = QPushButton("🗑️")
        self.delete_button.setObjectName("dangerIconButton")
        self.delete_button.setFixedWidth(44)
        self.delete_button.setToolTip("حذف")
        self.delete_button.clicked.connect(self._delete)
        self.delete_button.setVisible(False)

        layout.addWidget(build_action_footer([save_button, cancel_button, self.delete_button]))
        return wrap_scrollable(panel)

    def _on_type_changed(self) -> None:
        is_buy_get = self.type_combo.currentData() == "BUY_X_GET_Y"
        self.buy_get_row.setVisible(is_buy_get)
        self.threshold_row.setVisible(not is_buy_get)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        self._reset_form()
        company_id = self._company_id()
        if company_id is None:
            return
        self._items = catalog_service.list_items(company_id, active_only=True)
        self.applies_item_combo.clear()
        self.get_item_combo.clear()
        self.get_item_combo.addItem("(همان کالایِ خرید)", None)
        for it in self._items:
            label = f"{it.code} — {it.name or ''}"
            self.applies_item_combo.addItem(label, it.item_id)
            self.get_item_combo.addItem(label, it.item_id)

        self._rows = promotions_service.list_promotion_rules(company_id)
        self.table.setRowCount(len(self._rows))
        for row_index, r in enumerate(self._rows):
            values = ["بله" if r.is_active else "خیر", r.code, r.name, _TYPE_LABELS.get(r.fields.promotion_type_code, r.fields.promotion_type_code)]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, r.promotion_rule_id)
                self.table.setItem(row_index, col_index, item)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        rule_id = self.table.item(row, 0).data(Qt.UserRole)
        rule = next((r for r in self._rows if r.promotion_rule_id == rule_id), None)
        if rule is not None:
            self._load_into_form(rule)

    def _load_into_form(self, rule: promotions_service.PromotionRuleRow) -> None:
        self._editing_id = rule.promotion_rule_id
        f = rule.fields
        self.form_title.setText(f"ویرایشِ {rule.name}")
        self.status_label.setText("")
        self.code_field.setText(rule.code)
        self.code_field.setEnabled(False)
        self.name_field.setText(rule.name)
        self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(f.promotion_type_code)))
        self._on_type_changed()
        self.channel_combo.setCurrentIndex(max(0, self.channel_combo.findData(f.channel_type_code)))
        self.applies_item_combo.setCurrentIndex(max(0, self.applies_item_combo.findData(f.applies_to_item_id)))
        self.buy_quantity_field.setValue(float(f.buy_quantity or 0.001))
        self.get_quantity_field.setValue(float(f.get_quantity or 0.001))
        self.get_item_combo.setCurrentIndex(max(0, self.get_item_combo.findData(f.get_item_id)))
        self.threshold_amount_field.setValue(float(f.threshold_amount or 0))
        self.discount_percent_field.setValue(float(f.discount_percent or 0.01))
        self.valid_from_field.setDate(f.valid_from or datetime.date.today())
        self.valid_to_field.setDate(f.valid_to or datetime.date.today())
        self.is_active_checkbox.setChecked(rule.is_active)
        self.delete_button.setVisible(True)

    def _reset_form(self) -> None:
        self._editing_id = None
        self.form_title.setText("پروموشنِ جدید")
        self.status_label.setText("")
        self.code_field.clear()
        self.code_field.setEnabled(True)
        self.name_field.clear()
        self.type_combo.setCurrentIndex(0)
        self._on_type_changed()
        self.channel_combo.setCurrentIndex(0)
        self.applies_item_combo.setCurrentIndex(0)
        self.buy_quantity_field.setValue(1)
        self.get_quantity_field.setValue(1)
        self.get_item_combo.setCurrentIndex(0)
        self.threshold_amount_field.setValue(0)
        self.discount_percent_field.setValue(1)
        self.valid_from_field.setDate(datetime.date.today())
        self.valid_to_field.setDate(datetime.date.today())
        self.is_active_checkbox.setChecked(True)
        self.delete_button.setVisible(False)
        self.table.clearSelection()

    def _collect_fields(self) -> promotions_service.PromotionRuleFields:
        promotion_type_code = self.type_combo.currentData()
        is_buy_get = promotion_type_code == "BUY_X_GET_Y"
        return promotions_service.PromotionRuleFields(
            promotion_type_code=promotion_type_code,
            channel_type_code=self.channel_combo.currentData(),
            applies_to_item_id=self.applies_item_combo.currentData() if is_buy_get else None,
            buy_quantity=decimal.Decimal(str(self.buy_quantity_field.value())) if is_buy_get else None,
            get_quantity=decimal.Decimal(str(self.get_quantity_field.value())) if is_buy_get else None,
            get_item_id=self.get_item_combo.currentData() if is_buy_get else None,
            threshold_amount=decimal.Decimal(str(self.threshold_amount_field.value())) if not is_buy_get else None,
            discount_percent=decimal.Decimal(str(self.discount_percent_field.value())) if not is_buy_get else None,
            valid_from=self.valid_from_field.date(),
            valid_to=self.valid_to_field.date(),
        )

    def _save(self) -> None:
        company_id = self._company_id()
        code = self.code_field.text().strip().upper()
        name = self.name_field.text().strip()
        if company_id is None or not code or not name:
            self.status_label.setText("کد و نام را وارد کنید.")
            return
        fields = self._collect_fields()
        try:
            if self._editing_id is not None:
                promotions_service.update_promotion_rule(self._editing_id, company_id, name, self.is_active_checkbox.isChecked(), fields)
            else:
                promotions_service.create_promotion_rule(company_id, code, name, fields)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        confirm = QMessageBox.question(self, "حذفِ پروموشن", "این پروموشن حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        company_id = self._company_id()
        try:
            promotions_service.delete_promotion_rule(self._editing_id, company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
