"""پخشِ سرد/گرم -- R130: برنامهٔ مراجعهٔ هفتگیِ هر مشتری (کدام روز، چه
ترتیبی، کدام ویزیتور) -- سرپرست از دسکتاپ تنظیم می‌کند؛ ثبتِ ویزیتِ
واقعی (چک‌این/چک‌اوت) کارِ اپِ موبایل است (R132)، این‌جا فقط رصد می‌شود
(customer_visits.py)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import field_sales as field_sales_service
from peecha.services import users as users_service
from peecha.ui.widgets import build_action_footer, wrap_scrollable

_COLUMNS = ["فعال", "مشتری", "روز", "ترتیب", "ویزیتور"]
_DAY_LABELS = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه")


class VisitPlansScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[field_sales_service.VisitPlanRow] = []
        self._customers: list[dict] = []
        self._editing_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        title = QLabel("برنامهٔ مراجعه")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        new_button = QPushButton("➕")
        new_button.setObjectName("primaryIconButton")
        new_button.setFixedWidth(48)
        new_button.setToolTip("برنامهٔ جدید")
        new_button.clicked.connect(self._reset_form)
        layout.addWidget(new_button, alignment=Qt.AlignLeft)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)
        return wrap_scrollable(panel)

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        self.form_title = QLabel("برنامهٔ جدید")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        layout.addWidget(QLabel("مشتری"))
        self.customer_combo = QComboBox()
        layout.addWidget(self.customer_combo)

        layout.addWidget(QLabel("روزِ هفته"))
        self.day_combo = QComboBox()
        for index, label in enumerate(_DAY_LABELS):
            self.day_combo.addItem(label, index)
        layout.addWidget(self.day_combo)

        layout.addWidget(QLabel("ترتیبِ توقف در مسیر"))
        self.sequence_field = QSpinBox()
        self.sequence_field.setRange(0, 999)
        layout.addWidget(self.sequence_field)

        layout.addWidget(QLabel("ویزیتورِ مسئول"))
        self.visitor_combo = QComboBox()
        layout.addWidget(self.visitor_combo)

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

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        self._reset_form()
        company_id = self._company_id()
        if company_id is None:
            return
        self._customers = dimensions_service.list_customers(company_id)
        self.customer_combo.clear()
        for c in self._customers:
            self.customer_combo.addItem(f"{c['code']} — {c['name'] or ''}", c["detail_account_id"])

        self.visitor_combo.clear()
        self.visitor_combo.addItem("(بدون)", None)
        for u in users_service.list_users():
            self.visitor_combo.addItem(u.full_name, u.user_id)

        self._rows = field_sales_service.list_visit_plans(company_id)
        customers_by_id = {c["detail_account_id"]: c for c in self._customers}
        users_by_id = {u.user_id: u.full_name for u in users_service.list_users()}
        self.table.setRowCount(len(self._rows))
        for row_index, r in enumerate(self._rows):
            customer = customers_by_id.get(r.customer_detail_account_id)
            values = [
                "بله" if r.is_active else "خیر",
                f"{customer['code']} — {customer['name'] or ''}" if customer else str(r.customer_detail_account_id),
                _DAY_LABELS[r.visit_day_of_week],
                str(r.sequence_order),
                users_by_id.get(r.assigned_visitor_user_id, "—") if r.assigned_visitor_user_id else "—",
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, r.visit_plan_id)
                self.table.setItem(row_index, col_index, item)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        plan_id = self.table.item(row, 0).data(Qt.UserRole)
        plan = next((r for r in self._rows if r.visit_plan_id == plan_id), None)
        if plan is not None:
            self._load_into_form(plan)

    def _load_into_form(self, plan: field_sales_service.VisitPlanRow) -> None:
        self._editing_id = plan.visit_plan_id
        self.form_title.setText("ویرایشِ برنامهٔ مراجعه")
        self.status_label.setText("")
        index = self.customer_combo.findData(plan.customer_detail_account_id)
        self.customer_combo.setCurrentIndex(max(0, index))
        self.customer_combo.setEnabled(False)
        self.day_combo.setCurrentIndex(plan.visit_day_of_week)
        self.day_combo.setEnabled(False)
        self.sequence_field.setValue(plan.sequence_order)
        self.visitor_combo.setCurrentIndex(max(0, self.visitor_combo.findData(plan.assigned_visitor_user_id)))
        self.is_active_checkbox.setChecked(plan.is_active)
        self.delete_button.setVisible(True)

    def _reset_form(self) -> None:
        self._editing_id = None
        self.form_title.setText("برنامهٔ جدید")
        self.status_label.setText("")
        self.customer_combo.setCurrentIndex(0)
        self.customer_combo.setEnabled(True)
        self.day_combo.setCurrentIndex(0)
        self.day_combo.setEnabled(True)
        self.sequence_field.setValue(0)
        self.visitor_combo.setCurrentIndex(0)
        self.is_active_checkbox.setChecked(True)
        self.delete_button.setVisible(False)
        self.table.clearSelection()

    def _save(self) -> None:
        company_id = self._company_id()
        if company_id is None or self.customer_combo.currentData() is None:
            return
        try:
            if self._editing_id is not None:
                field_sales_service.update_visit_plan(
                    self._editing_id, company_id, self.sequence_field.value(), self.visitor_combo.currentData(),
                    self.is_active_checkbox.isChecked(),
                )
            else:
                field_sales_service.create_visit_plan(
                    company_id, self.customer_combo.currentData(), self.day_combo.currentData(),
                    self.sequence_field.value(), self.visitor_combo.currentData(),
                )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        confirm = QMessageBox.question(self, "حذفِ برنامه", "این برنامهٔ مراجعه حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        company_id = self._company_id()
        try:
            field_sales_service.delete_visit_plan(self._editing_id, company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
