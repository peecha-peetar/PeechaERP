"""۷ صفحه‌ی اختصاصیِ «فرمِ خاص»یِ تفصیلی — کالا/دارایی‌ثابت/بانک/صندوق/
تنخواه/مرکزِ هزینه/پروژه — طبقِ درخواستِ صریح، مثلِ مشتری/تامین‌کننده/
پرسنل (person_group_screens.py) هرکدام صفحه‌ی اختصاصیِ خودشان را دارند.

برخلافِ مشتری/تامین‌کننده/پرسنل (که هرکدام جدولِ SQLِ ستون‌دارِ اختصاصیِ
خودشان را دارند — customer_details/...)، این ۷ تا نوع‌بُعدِ مستقلِ خودشان
هستند (نه زیرگروهِ PERSON) و فیلدهایِ اختصاصی‌شان (اگر لازم شد) از همان
مکانیزمِ عمومیِ acc.detail_group_fields/extra_fields JSONB می‌آید — دقیقاً
همان چیزی که «تنظیماتِ گروه» در DetailDimensionsScreen (پنلِ ۲) از قبل
برایش UI دارد؛ این صفحه فقط CRUDِ خودِ حساب‌هایِ تفصیلیِ همان نوع را انجام
می‌دهد (فهرست + فرم + سلسله‌مراتبِ تا ۴ سطح — از همان
create_detail_account/update_detail_account/delete_detail_account عمومی
استفاده می‌کند، بدونِ جدولِ SQLِ تازه)."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import detail_dimensions as dimensions_service
from peecha.ui.widgets import FieldHelpMixin

_COLUMNS = ["وضعیت", "نام", "کدِ کامل", "سطح"]


class SpecializedDimensionScreenBase(FieldHelpMixin, QWidget):
    DIMENSION_CODE: str = ""
    TITLE: str = ""

    def __init__(self) -> None:
        super().__init__()
        self._dimension_type_id: int | None = None
        self._rows_by_id: dict[int, dimensions_service.DetailAccountRow] = {}
        self._editing_id: int | None = None
        self._extra_widgets: dict[str, tuple[QWidget, str]] = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)

        self.set_field_help([
            (
                self.show_all_levels_checkbox,
                "به‌طورِ پیش‌فرض فقط آخرین سطح (برگ‌ها) نشان داده می‌شود. با این تیک، کلِ درختِ والد و فرزند را می‌بینید.",
            ),
            (
                self.parent_combo,
                f"اگر این «{self.TITLE}» زیرمجموعه‌یِ یک موردِ دیگر است، آن را این‌جا انتخاب کنید. "
                "بدونِ والد یعنی این مورد در سطحِ اول قرار می‌گیرد.",
            ),
            (
                self.code_field,
                "کدِ این مورد. برنامه بعدِ انتخابِ والد یک کدِ پیشنهادی خودش پر می‌کند، ولی می‌توانید تغییرش دهید.",
            ),
            (self.name_field, "نامی که در فهرست‌ها و سندها نمایش داده می‌شود."),
            (
                self.active_checkbox,
                "مواردِ غیرِفعال از فهرستِ انتخاب در سندهایِ تازه کنار گذاشته می‌شوند، ولی سوابقِ قبلی‌شان می‌ماند.",
            ),
        ])

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        self.list_title = QLabel(self.TITLE)
        self.list_title.setObjectName("pageTitle")
        layout.addWidget(self.list_title)

        # طبقِ درخواستِ صریح: نمایِ درختی + رنگِ گروه — به‌طورِ پیش‌فرض فقط
        # سطوحِ آخر (برگ‌ها) نشان داده می‌شوند؛ چک‌باکسِ «نمایشِ همه‌یِ سطوح»
        # کلِ سلسله‌مراتبِ والد/فرزند را نشان می‌دهد.
        self.show_all_levels_checkbox = QCheckBox("نمایشِ همه‌یِ سطوح")
        self.show_all_levels_checkbox.toggled.connect(lambda _checked: self._reload())
        layout.addWidget(self.show_all_levels_checkbox)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(_COLUMNS))
        self.tree.setHeaderLabels(_COLUMNS)
        self.tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.tree)
        return panel

    def _build_form_panel(self) -> QWidget:
        # طبقِ گزارشِ صریح: فیلدهایِ اختصاصی می‌توانند زیاد باشند و این
        # پنل هیچ اسکرولی نداشت.
        scroll = QScrollArea()
        scroll.setObjectName("card")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)

        self.form_title = QLabel("موردِ تازه")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        grid = QGridLayout()
        grid.setSpacing(8)

        grid.addWidget(QLabel("والد"), 0, 0)
        self.parent_combo = QComboBox()
        self.parent_combo.currentIndexChanged.connect(self._on_parent_combo_changed)
        grid.addWidget(self.parent_combo, 0, 1)

        grid.addWidget(QLabel("کد"), 1, 0)
        self.code_field = QLineEdit()
        grid.addWidget(self.code_field, 1, 1)

        grid.addWidget(QLabel("نام"), 2, 0)
        self.name_field = QLineEdit()
        grid.addWidget(self.name_field, 2, 1)

        self.active_checkbox = QCheckBox("فعال")
        self.active_checkbox.setChecked(True)
        grid.addWidget(self.active_checkbox, 3, 1)
        layout.addLayout(grid)

        layout.addWidget(QLabel("فیلدهایِ اختصاصی"))
        self.extra_fields_container = QVBoxLayout()
        extra_widget = QWidget()
        extra_widget.setLayout(self.extra_fields_container)
        layout.addWidget(extra_widget)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.save_button = QPushButton("ذخیره")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.save_button)

        self.cancel_button = QPushButton("انصراف")
        self.cancel_button.setObjectName("flatButton")
        self.cancel_button.clicked.connect(self._reset_form)
        buttons.addWidget(self.cancel_button)

        self.delete_button = QPushButton("حذف")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self._delete)
        self.delete_button.setVisible(False)
        buttons.addWidget(self.delete_button)

        layout.addLayout(buttons)
        layout.addStretch(1)
        scroll.setWidget(panel)
        return scroll

    # --- بارگذاری ----------------------------------------------------------
    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        self.status_label.setText("")
        company_id = self._company_id()
        if company_id is None:
            self._dimension_type_id = None
            self.tree.clear()
            return
        self._dimension_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, self.DIMENSION_CODE)
        self._reload()
        # هر بار که این صفحه باز می‌شود (چه از ساید‌بار، چه از دکمه‌ی
        # «تفصیلیِ جدید» در فهرستِ واحدِ تفصیلی‌ها)، فرم به‌طورِ پیش‌فرض در
        # حالتِ «رکوردِ تازه» باشد، نه اینکه ویرایشِ قبلی را نگه دارد.
        self._reset_form()

    def _reload(self) -> None:
        rows = dimensions_service.list_detail_accounts(self._company_id(), self._dimension_type_id)
        self._rows_by_id = {r.detail_account_id: r for r in rows}
        max_level_no = dimensions_service.get_group_max_level_no(self._dimension_type_id)

        self.parent_combo.blockSignals(True)
        self.parent_combo.clear()
        self.parent_combo.addItem("— بدونِ والد (سطحِ ۱) —", None)
        for r in rows:
            if r.level_no < max_level_no and r.detail_account_id != self._editing_id:
                self.parent_combo.addItem(f"{r.full_code} — {r.name or ''}", r.detail_account_id)
        self.parent_combo.blockSignals(False)

        self._rebuild_tree(rows)

        self._render_extra_fields()
        if self._editing_id is None:
            self._suggest_code_for_current_parent()

    def _make_tree_item(self, r: dimensions_service.DetailAccountRow, color: str | None) -> QTreeWidgetItem:
        item = QTreeWidgetItem(["فعال" if r.is_active else "غیرفعال", r.name or "—", r.full_code, str(r.level_no)])
        item.setData(0, Qt.UserRole, r.detail_account_id)
        if color:
            for col in range(len(_COLUMNS)):
                item.setForeground(col, QBrush(QColor(color)))
        return item

    def _rebuild_tree(self, rows: list[dimensions_service.DetailAccountRow]) -> None:
        """طبقِ درخواستِ صریح: نمایِ درختی + رنگِ گروه — به‌طورِ پیش‌فرض فقط
        برگ‌ها (سطحِ آخر) نشان داده می‌شوند؛ چک‌باکسِ «نمایشِ همه‌یِ سطوح»
        سلسله‌مراتبِ کاملِ والد/فرزند را می‌سازد."""
        self.tree.clear()
        color = dimensions_service.get_group_color(self._dimension_type_id) if self._dimension_type_id else None

        if self.show_all_levels_checkbox.isChecked():
            children_by_parent: dict[int | None, list[dimensions_service.DetailAccountRow]] = {}
            for r in rows:
                children_by_parent.setdefault(r.parent_detail_account_id, []).append(r)
            for siblings in children_by_parent.values():
                siblings.sort(key=lambda row: row.full_code)

            def add_children(parent_item: QTreeWidgetItem | None, parent_id: int | None) -> None:
                for r in children_by_parent.get(parent_id, []):
                    item = self._make_tree_item(r, color)
                    if parent_item is None:
                        self.tree.addTopLevelItem(item)
                    else:
                        parent_item.addChild(item)
                    add_children(item, r.detail_account_id)

            add_children(None, None)
            self.tree.expandAll()
        else:
            parent_ids = {r.parent_detail_account_id for r in rows if r.parent_detail_account_id is not None}
            leaves = [r for r in rows if r.detail_account_id not in parent_ids]
            for r in sorted(leaves, key=lambda row: row.full_code):
                self.tree.addTopLevelItem(self._make_tree_item(r, color))

        for col in range(len(_COLUMNS)):
            self.tree.resizeColumnToContents(col)

    def _on_parent_combo_changed(self, _index: int) -> None:
        if self._editing_id is not None:
            return
        self._suggest_code_for_current_parent()

    def _suggest_code_for_current_parent(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._dimension_type_id is None:
            return
        parent_id = self.parent_combo.currentData()
        level_no = 1
        if parent_id is not None:
            parent = self._rows_by_id.get(parent_id)
            if parent is None:
                return
            level_no = parent.level_no + 1
        self.code_field.setText(dimensions_service.suggest_next_code(company_id, self._dimension_type_id, level_no))

    def _render_extra_fields(self, values: dict | None = None) -> None:
        while self.extra_fields_container.count():
            child = self.extra_fields_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._extra_widgets = {}
        if self._dimension_type_id is None:
            return
        for field_def in dimensions_service.list_group_fields(self._dimension_type_id):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(QLabel(field_def.label))
            widget: QWidget
            if field_def.kind == "boolean":
                widget = QCheckBox()
            elif field_def.kind == "decimal":
                widget = QDoubleSpinBox()
                widget.setRange(0, 10_000_000_000)
                widget.setDecimals(2)
            elif field_def.kind == "date":
                widget = QDateEdit()
                widget.setCalendarPopup(True)
                widget.setSpecialValueText(" ")
                widget.setDate(widget.minimumDate())
            else:
                widget = QLineEdit()
            row_layout.addWidget(widget)
            self.extra_fields_container.addWidget(row)
            self._extra_widgets[field_def.field_key] = (widget, field_def.kind)

            if values is not None and field_def.field_key in values and values[field_def.field_key] is not None:
                value = values[field_def.field_key]
                if field_def.kind == "boolean":
                    widget.setChecked(bool(value))
                elif field_def.kind == "decimal":
                    widget.setValue(float(value))
                elif field_def.kind == "date" and isinstance(value, datetime.date):
                    widget.setDate(value)
                else:
                    widget.setText(str(value))

    def _collect_extra_fields(self) -> dict:
        result = {}
        for key, (widget, kind) in self._extra_widgets.items():
            if kind == "boolean":
                result[key] = widget.isChecked()
            elif kind == "decimal":
                result[key] = decimal.Decimal(str(widget.value())) if widget.value() else None
            elif kind == "date":
                qdate = widget.date()
                result[key] = None if qdate == widget.minimumDate() else datetime.date(qdate.year(), qdate.month(), qdate.day())
            else:
                text = widget.text().strip()
                result[key] = text or None
        return result

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        detail_account_id = item.data(0, Qt.UserRole)
        if detail_account_id is None:
            return
        self._load_into_form(detail_account_id)

    # --- برایِ ناوبری از فهرستِ واحدِ تفصیلی‌ها -----------------------------
    def edit_detail_account(self, detail_account_id: int) -> None:
        self.refresh()
        self._load_into_form(detail_account_id)

    def _load_into_form(self, detail_account_id: int) -> None:
        account = self._rows_by_id.get(detail_account_id)
        if account is None:
            return
        self._editing_id = detail_account_id
        self._reload()  # برایِ به‌روزکردنِ فهرستِ والدهایِ مجاز (بدونِ خودش)
        self.form_title.setText(f"ویرایشِ «{account.full_code}»")
        self.code_field.setText(account.code)
        self.name_field.setText(account.name or "")
        self.active_checkbox.setChecked(account.is_active)
        if account.parent_detail_account_id is not None:
            index = self.parent_combo.findData(account.parent_detail_account_id)
            self.parent_combo.setCurrentIndex(index if index >= 0 else 0)
        else:
            self.parent_combo.setCurrentIndex(0)
        self.parent_combo.setEnabled(False)
        self._render_extra_fields(account.extra_fields)
        self.delete_button.setVisible(True)

    def _reset_form(self) -> None:
        self._editing_id = None
        self.form_title.setText("موردِ تازه")
        self.status_label.setText("")
        self.code_field.clear()
        self.name_field.clear()
        self.active_checkbox.setChecked(True)
        self.parent_combo.setEnabled(True)
        if self.parent_combo.count():
            self.parent_combo.setCurrentIndex(0)
        self._render_extra_fields()
        self._suggest_code_for_current_parent()
        self.delete_button.setVisible(False)
        self.tree.clearSelection()

    def _save(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._dimension_type_id is None:
            self.status_label.setText("ابتدا یک شرکت را انتخاب کنید.")
            return
        code = self.code_field.text().strip()
        if not code:
            self.status_label.setText("کد را وارد کنید.")
            return
        name = self.name_field.text().strip() or None
        extra_fields = self._collect_extra_fields()

        try:
            if self._editing_id is not None:
                dimensions_service.update_detail_account(
                    self._editing_id, company_id, code, self.active_checkbox.isChecked(),
                    name=name, extra_fields=extra_fields,
                )
            else:
                dimensions_service.create_detail_account(
                    company_id, self._dimension_type_id, code, name=name,
                    parent_detail_account_id=self.parent_combo.currentData(), extra_fields=extra_fields,
                )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return

        self._reset_form()
        self._reload()

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        company_id = self._company_id()
        if company_id is None:
            return
        account = self._rows_by_id.get(self._editing_id)
        confirm = QMessageBox.question(
            self,
            "حذف",
            f"«{account.name or account.code}» حذف شود؟ این کار قابلِ بازگشت نیست.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            dimensions_service.delete_detail_account(self._editing_id, company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._reset_form()
        self._reload()


class InventoryItemsScreen(SpecializedDimensionScreenBase):
    DIMENSION_CODE = dimensions_service.INVENTORY_ITEM_CODE
    TITLE = "کالا"


class FixedAssetsScreen(SpecializedDimensionScreenBase):
    DIMENSION_CODE = dimensions_service.FIXED_ASSET_CODE
    TITLE = "دارایی ثابت"


class BankAccountsScreen(SpecializedDimensionScreenBase):
    DIMENSION_CODE = dimensions_service.BANK_ACCOUNT_CODE
    TITLE = "بانک"


class CashBoxesScreen(SpecializedDimensionScreenBase):
    DIMENSION_CODE = dimensions_service.CASH_BOX_CODE
    TITLE = "صندوق"


class PettyCashesScreen(SpecializedDimensionScreenBase):
    DIMENSION_CODE = dimensions_service.PETTY_CASH_CODE
    TITLE = "تنخواه"


class CostCentersScreen(SpecializedDimensionScreenBase):
    DIMENSION_CODE = dimensions_service.COST_CENTER_CODE
    TITLE = "مرکز هزینه"


class ProjectsScreen(SpecializedDimensionScreenBase):
    DIMENSION_CODE = dimensions_service.PROJECT_CODE
    TITLE = "پروژه"
