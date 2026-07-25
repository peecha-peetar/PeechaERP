"""مشتریان/تامین‌کنندگان/پرسنل — معادلِ Qt برایِ person_group_screens.py/.kv در Kivy.

یک کلاسِ پایه (فهرست + فرمِ ساخت/ویرایش/حذف) + سه زیرکلاسِ نازک که فقط
FIELD_SPECS و متدهایِ سرویسِ خودشان را مشخص می‌کنند — دقیقاً همان الگویِ
Kivy (PersonGroupScreenBase).

طبقِ درخواستِ صریح: «همه گروه‌های تفصیلی حتی مشتری/تامین‌کننده/پرسنل هم
بتوان فیلدهای اختصاصیِ خودشان را داشت» — فیلدهایِ هاردکدِ بالا (FIELD_SPECS،
customer_details/...) دست‌نخورده می‌مانند؛ یک بخشِ فیلدهایِ اختصاصیِ
عمومی/قابل‌پیکربندی (همان مکانیزمِ acc.detail_group_fields که کالا/بانک/...
دارند، حالا با person_group_id مربوط به هرکدام از این سه گروه) به‌عنوانِ
لایه‌ی افزودنی زیرِ فرم اضافه شده — مقدارشان در DetailAccount.extra_fields
ذخیره می‌شود.

طبقِ درخواستِ صریحِ بعدی: «مشتریان دو تا سطح داره» — این سه گروه هم مثلِ
کالا/بانک/... تا سقفِ person_groups.max_level_no سلسله‌مراتب (والد/فرزند)
دارند؛ انتخابگرِ والد + پیشنهادِ خودکارِ کدِ بعدی (suggest_next_code) به
فرمِ مشترک اضافه شده — دقیقاً هم‌الگو با specialized_dimensions.py."""

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

_FIELD_LABELS = {
    "economic_code": "کدِ اقتصادی",
    "national_id": "شناسه/کدِ ملی",
    "phone": "تلفن",
    "mobile": "موبایل",
    "address": "آدرس",
    "credit_limit": "سقفِ اعتبار",
    "notes": "یادداشت",
    "bank_account_no": "شماره‌حسابِ بانکی",
    "personnel_no": "شماره‌ی پرسنلی",
    "position_title": "سمت",
    "hire_date": "تاریخِ استخدام",
}

# طبقِ درخواستِ صریح برایِ راهنمایِ آموزشیِ فیلدها: چون فیلدهایِ اختصاصی
# (FIELD_SPECS) با یک حلقه ساخته می‌شوند نه تک‌تک، متنِ راهنمایِ هرکدام
# این‌جا با field_key نگه‌داشته شده تا در __init__ به‌طورِ خودکار به
# ویجتِ متناظرش وصل شود.
_FIELD_HELP_TEXTS = {
    "economic_code": "کدِ اقتصادی که سازمانِ امور مالیاتی به این طرفِ حساب داده. برایِ صدورِ فاکتورِ رسمی لازم است.",
    "national_id": "شناسه یا کدِ ملیِ این طرفِ حساب — شناسه‌یِ یکتایِ او برایِ اسنادِ رسمی.",
    "phone": "شماره‌ی تلفنِ ثابت.",
    "mobile": "شماره‌ی موبایل.",
    "address": "آدرسِ پستی.",
    "credit_limit": "سقفِ اعتباری که به این مشتری داده می‌شود. این عدد فقط اطلاعاتی است و در حالِ حاضر جلویِ فروشِ بیشتر را نمی‌گیرد.",
    "notes": "یادداشتِ آزاد برایِ هر توضیحِ اضافه.",
    "bank_account_no": "شماره‌حسابِ بانکیِ این طرفِ حساب — برایِ پرداخت/دریافتِ وجه.",
    "personnel_no": "شماره‌ی پرسنلیِ این کارمند در سیستمِ حقوق و دستمزد.",
    "position_title": "سمتِ شغلیِ این کارمند.",
    "hire_date": "تاریخِ استخدامِ این کارمند.",
}

_COLUMNS = ["وضعیت", "نام", "کد", "سطح"]


class PersonGroupScreenBase(FieldHelpMixin, QWidget):
    FIELD_SPECS: tuple[tuple[str, str], ...] = ()  # (field_key, kind) — kind: text/decimal/date
    GROUP_CODE: str = ""  # CUSTOMER/SUPPLIER/PERSONNEL — برایِ حلِ person_group_id
    EMPTY_TEXT = ""

    def __init__(self) -> None:
        super().__init__()
        self._rows_by_id: dict[int, dict] = {}
        self._editing_id: int | None = None
        self._extra_widgets: dict[str, QWidget] = {}
        self._dimension_type_id: int | None = None
        self._person_group_id: int | None = None
        self._custom_field_widgets: dict[str, tuple[QWidget, str]] = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)

        extra_help = [
            (self._extra_widgets[field_key], _FIELD_HELP_TEXTS.get(field_key, _FIELD_LABELS.get(field_key, field_key)))
            for field_key, _kind in self.FIELD_SPECS
        ]
        self.set_field_help([
            (
                self.parent_combo,
                "اگر این مورد زیرمجموعه‌یِ یک موردِ دیگر است، آن را این‌جا انتخاب کنید. "
                "بدونِ والد یعنی این مورد در سطحِ اول قرار می‌گیرد.",
            ),
            (
                self.code_field,
                "کدِ این مورد. برنامه بعدِ انتخابِ والد یک کدِ پیشنهادی خودش پر می‌کند، ولی می‌توانید تغییرش دهید.",
            ),
            (self.name_field, "نامی که در فهرست‌ها و سندها نمایش داده می‌شود."),
            *extra_help,
            (
                self.active_checkbox,
                "موارد غیرِفعال از فهرستِ انتخاب در سندهایِ تازه کنار گذاشته می‌شوند، ولی سوابقِ قبلی‌شان می‌ماند.",
            ),
        ])

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        self.list_title = QLabel("")
        self.list_title.setObjectName("pageTitle")
        layout.addWidget(self.list_title)

        # طبقِ درخواستِ صریح: نمایِ درختی + رنگِ گروه — به‌طورِ پیش‌فرض فقط
        # سطوحِ آخر (برگ‌ها) نشان داده می‌شوند؛ چک‌باکسِ «نمایشِ همه‌یِ سطوح»
        # کلِ سلسله‌مراتبِ والد/فرزند را نشان می‌دهد.
        self.show_all_levels_checkbox = QCheckBox("نمایشِ همه‌یِ سطوح")
        self.show_all_levels_checkbox.toggled.connect(lambda _checked: self._rebuild_tree())
        layout.addWidget(self.show_all_levels_checkbox)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(_COLUMNS))
        self.tree.setHeaderLabels(_COLUMNS)
        self.tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.tree)
        return panel

    def _build_form_panel(self) -> QWidget:
        # طبقِ گزارشِ صریح: این فرم فیلدهایِ زیادی دارد (اختصاصیِ گروه +
        # فیلدهایِ هاردکدِ مشتری/تامین‌کننده/پرسنل) و هیچ اسکرولی نداشت.
        scroll = QScrollArea()
        scroll.setObjectName("card")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)

        self.form_title = QLabel("افزودنِ موردِ تازه")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        grid = QGridLayout()
        grid.setSpacing(8)
        row = 0

        grid.addWidget(QLabel("والد"), row, 0)
        self.parent_combo = QComboBox()
        self.parent_combo.currentIndexChanged.connect(self._on_parent_combo_changed)
        grid.addWidget(self.parent_combo, row, 1)
        row += 1

        grid.addWidget(QLabel("کد"), row, 0)
        self.code_field = QLineEdit()
        grid.addWidget(self.code_field, row, 1)
        row += 1

        grid.addWidget(QLabel("نام"), row, 0)
        self.name_field = QLineEdit()
        grid.addWidget(self.name_field, row, 1)
        row += 1

        for field_key, kind in self.FIELD_SPECS:
            grid.addWidget(QLabel(_FIELD_LABELS.get(field_key, field_key)), row, 0)
            widget: QWidget
            if kind == "decimal":
                widget = QDoubleSpinBox()
                widget.setRange(0, 10_000_000_000)
                widget.setDecimals(2)
            elif kind == "date":
                widget = QDateEdit()
                widget.setCalendarPopup(True)
                widget.setSpecialValueText(" ")
                widget.setDate(widget.minimumDate())
            else:
                widget = QLineEdit()
            grid.addWidget(widget, row, 1)
            self._extra_widgets[field_key] = widget
            row += 1

        self.active_checkbox = QCheckBox("فعال")
        self.active_checkbox.setChecked(True)
        grid.addWidget(self.active_checkbox, row, 1)
        row += 1

        layout.addLayout(grid)

        layout.addWidget(QLabel("فیلدهایِ اختصاصیِ تعریف‌شده"))
        self.custom_fields_container = QVBoxLayout()
        custom_fields_widget = QWidget()
        custom_fields_widget.setLayout(self.custom_fields_container)
        layout.addWidget(custom_fields_widget)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.save_button = QPushButton("افزودن")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.save_button)

        self.cancel_button = QPushButton("انصراف")
        self.cancel_button.setObjectName("flatButton")
        self.cancel_button.clicked.connect(self._reset_form)
        self.cancel_button.setVisible(False)
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

    # --- هوک‌های زیرکلاس ---------------------------------------------------
    def _list_rows(self, company_id: int) -> list[dict]:
        raise NotImplementedError

    def _create(
        self,
        company_id: int,
        code: str,
        name: str,
        extra: dict,
        custom_fields: dict,
        parent_detail_account_id: int | None,
    ) -> None:
        raise NotImplementedError

    def _update(
        self, detail_account_id: int, company_id: int, code: str, name: str, is_active: bool, extra: dict, custom_fields: dict
    ) -> None:
        raise NotImplementedError

    def _delete_row(self, detail_account_id: int, company_id: int) -> None:
        raise NotImplementedError

    # --- منطقِ مشترک --------------------------------------------------------
    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        self.status_label.setText("")
        company_id = self._company_id()
        if company_id is not None:
            self._dimension_type_id = dimensions_service.get_person_dimension_type_id(company_id)
            self._person_group_id = dimensions_service.get_person_group_id(company_id, self.GROUP_CODE)
            # طبقِ گزارشِ صریح: بعدِ تغییرِ نامِ گروه (در پیکربندیِ
            # گروه‌هایِ تفصیلی)، عنوانِ همین صفحه هم باید همان نامِ تازه را
            # نشان دهد — نه برچسبِ ثابتِ تعیین‌شده در __init__ زیرکلاس.
            group = next(
                (g for g in dimensions_service.list_person_groups(company_id) if g.person_group_id == self._person_group_id),
                None,
            )
            if group is not None:
                self.list_title.setText(group.name)
        else:
            self._dimension_type_id = None
            self._person_group_id = None
        rows = self._list_rows(company_id) if company_id is not None else []
        self._rows_by_id = {r["detail_account_id"]: r for r in rows}

        self._rebuild_tree()
        self._reset_form(keep_status=True)

    def _make_tree_item(self, row: dict, color: str | None) -> QTreeWidgetItem:
        item = QTreeWidgetItem(
            ["فعال" if row["is_active"] else "غیرفعال", row["name"] or "—", row["full_code"], str(row["level_no"])]
        )
        item.setData(0, Qt.UserRole, row["detail_account_id"])
        if color:
            for col in range(len(_COLUMNS)):
                item.setForeground(col, QBrush(QColor(color)))
        return item

    def _rebuild_tree(self) -> None:
        """طبقِ درخواستِ صریح: نمایِ درختی + رنگِ گروه — به‌طورِ پیش‌فرض فقط
        برگ‌ها (سطحِ آخر) نشان داده می‌شوند؛ چک‌باکسِ «نمایشِ همه‌یِ سطوح»
        سلسله‌مراتبِ کاملِ والد/فرزند را می‌سازد."""
        self.tree.clear()
        color = (
            dimensions_service.get_group_color(0, self._person_group_id) if self._person_group_id else None
        )
        rows = list(self._rows_by_id.values())

        if self.show_all_levels_checkbox.isChecked():
            children_by_parent: dict[int | None, list[dict]] = {}
            for r in rows:
                children_by_parent.setdefault(r.get("parent_detail_account_id"), []).append(r)
            for siblings in children_by_parent.values():
                siblings.sort(key=lambda row: row["full_code"])

            def add_children(parent_item: QTreeWidgetItem | None, parent_id: int | None) -> None:
                for r in children_by_parent.get(parent_id, []):
                    item = self._make_tree_item(r, color)
                    if parent_item is None:
                        self.tree.addTopLevelItem(item)
                    else:
                        parent_item.addChild(item)
                    add_children(item, r["detail_account_id"])

            add_children(None, None)
            self.tree.expandAll()
        else:
            parent_ids = {r.get("parent_detail_account_id") for r in rows if r.get("parent_detail_account_id") is not None}
            leaves = [r for r in rows if r["detail_account_id"] not in parent_ids]
            for r in sorted(leaves, key=lambda row: row["full_code"]):
                self.tree.addTopLevelItem(self._make_tree_item(r, color))

        for col in range(len(_COLUMNS)):
            self.tree.resizeColumnToContents(col)

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        detail_account_id = item.data(0, Qt.UserRole)
        if detail_account_id is None:
            return
        self._load_into_form(detail_account_id)

    def _rebuild_parent_combo(self) -> None:
        max_level_no = (
            dimensions_service.get_group_max_level_no(self._dimension_type_id, self._person_group_id)
            if self._dimension_type_id is not None and self._person_group_id is not None
            else 1
        )
        self.parent_combo.blockSignals(True)
        self.parent_combo.clear()
        self.parent_combo.addItem("— بدونِ والد (سطحِ ۱) —", None)
        for r in self._rows_by_id.values():
            if r["level_no"] < max_level_no and r["detail_account_id"] != self._editing_id:
                self.parent_combo.addItem(f"{r['full_code']} — {r['name'] or ''}", r["detail_account_id"])
        self.parent_combo.blockSignals(False)

    def _on_parent_combo_changed(self, _index: int) -> None:
        if self._editing_id is not None:
            return
        self._suggest_code_for_current_parent()

    def _suggest_code_for_current_parent(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._dimension_type_id is None or self._person_group_id is None:
            return
        parent_id = self.parent_combo.currentData()
        level_no = 1
        if parent_id is not None:
            parent = self._rows_by_id.get(parent_id)
            if parent is None:
                return
            level_no = parent["level_no"] + 1
        self.code_field.setText(
            dimensions_service.suggest_next_code(company_id, self._dimension_type_id, level_no, self._person_group_id)
        )

    def _load_into_form(self, detail_account_id: int) -> None:
        row = self._rows_by_id.get(detail_account_id)
        if row is None:
            return
        self._editing_id = detail_account_id
        self._rebuild_parent_combo()  # برایِ به‌روزکردنِ فهرستِ والدهایِ مجاز (بدونِ خودش)
        self.form_title.setText(f"ویرایشِ «{row['name'] or row['code']}»")
        self.code_field.setText(row["code"])
        self.name_field.setText(row["name"] or "")
        self.active_checkbox.setChecked(row["is_active"])
        if row.get("parent_detail_account_id") is not None:
            index = self.parent_combo.findData(row["parent_detail_account_id"])
            self.parent_combo.setCurrentIndex(index if index >= 0 else 0)
        else:
            self.parent_combo.setCurrentIndex(0)
        self.parent_combo.setEnabled(False)
        for field_key, kind in self.FIELD_SPECS:
            widget = self._extra_widgets[field_key]
            value = row.get(field_key)
            if kind == "decimal":
                widget.setValue(float(value) if value is not None else 0)
            elif kind == "date":
                if value:
                    widget.setDate(value)
                else:
                    widget.setDate(widget.minimumDate())
            else:
                widget.setText(str(value) if value is not None else "")
        self._render_custom_fields(row.get("custom_fields"))
        self.save_button.setText("ذخیره‌ی تغییرات")
        self.cancel_button.setVisible(True)
        self.delete_button.setVisible(True)
        self.status_label.setText(f"در حالِ ویرایشِ «{row['name'] or row['code']}»")

    def _reset_form(self, *, keep_status: bool = False) -> None:
        self._editing_id = None
        self.form_title.setText("افزودنِ موردِ تازه")
        if not keep_status:
            self.status_label.setText("")
        self._rebuild_parent_combo()
        self.parent_combo.setEnabled(True)
        if self.parent_combo.count():
            self.parent_combo.setCurrentIndex(0)
        self.code_field.clear()
        self.name_field.clear()
        self.active_checkbox.setChecked(True)
        for field_key, kind in self.FIELD_SPECS:
            widget = self._extra_widgets[field_key]
            if kind == "decimal":
                widget.setValue(0)
            elif kind == "date":
                widget.setDate(widget.minimumDate())
            else:
                widget.clear()
        self._render_custom_fields()
        self._suggest_code_for_current_parent()
        self.save_button.setText("افزودن")
        self.cancel_button.setVisible(False)
        self.delete_button.setVisible(False)
        self.tree.clearSelection()

    def _render_custom_fields(self, values: dict | None = None) -> None:
        while self.custom_fields_container.count():
            child = self.custom_fields_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._custom_field_widgets = {}
        if self._dimension_type_id is None or self._person_group_id is None:
            return
        for field_def in dimensions_service.list_group_fields(self._dimension_type_id, self._person_group_id):
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
            self.custom_fields_container.addWidget(row)
            self._custom_field_widgets[field_def.field_key] = (widget, field_def.kind)

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

    def _collect_custom_fields(self) -> dict:
        result: dict = {}
        for key, (widget, kind) in self._custom_field_widgets.items():
            if kind == "boolean":
                result[key] = widget.isChecked()
            elif kind == "decimal":
                result[key] = float(widget.value()) if widget.value() else None
            elif kind == "date":
                qdate = widget.date()
                result[key] = None if qdate == widget.minimumDate() else datetime.date(qdate.year(), qdate.month(), qdate.day())
            else:
                text = widget.text().strip()
                result[key] = text or None
        return result

    def _collect_extra_fields(self) -> dict:
        extra: dict = {}
        for field_key, kind in self.FIELD_SPECS:
            widget = self._extra_widgets[field_key]
            if kind == "decimal":
                value = widget.value()
                extra[field_key] = decimal.Decimal(str(value)) if value else None
            elif kind == "date":
                qdate = widget.date()
                if qdate == widget.minimumDate():
                    extra[field_key] = None
                else:
                    extra[field_key] = datetime.date(qdate.year(), qdate.month(), qdate.day())
            else:
                text = widget.text().strip()
                extra[field_key] = text or None
        return extra

    def _save(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            self.status_label.setText("هیچ شرکتی انتخاب نشده است.")
            return
        code = self.code_field.text().strip()
        name = self.name_field.text().strip()
        if not code or not name:
            self.status_label.setText("کد و نام را وارد کنید.")
            return

        extra = self._collect_extra_fields()
        custom_fields = self._collect_custom_fields()
        try:
            if self._editing_id is not None:
                self._update(
                    self._editing_id, company_id, code, name, self.active_checkbox.isChecked(), extra, custom_fields
                )
            else:
                self._create(company_id, code, name, extra, custom_fields, self.parent_combo.currentData())
        except Exception as exc:  # noqa: BLE001 - نمایش هر خطای دیتابیس به کاربر
            self.status_label.setText(f"خطا: {exc}")
            return

        self.refresh()

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        company_id = self._company_id()
        if company_id is None:
            return
        row = self._rows_by_id.get(self._editing_id)
        confirm = QMessageBox.question(
            self,
            "حذف",
            f"«{row['name'] or row['code']}» حذف شود؟ این کار قابلِ بازگشت نیست.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            self._delete_row(self._editing_id, company_id)
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(f"خطا: {exc}")
            return
        self.refresh()


_CUSTOMER_FIELD_SPECS = (
    ("economic_code", "text"), ("national_id", "text"), ("phone", "text"), ("mobile", "text"),
    ("address", "text"), ("credit_limit", "decimal"), ("notes", "text"),
)
_SUPPLIER_FIELD_SPECS = (
    ("economic_code", "text"), ("national_id", "text"), ("phone", "text"), ("mobile", "text"),
    ("address", "text"), ("bank_account_no", "text"), ("notes", "text"),
)
_PERSONNEL_FIELD_SPECS = (
    ("national_id", "text"), ("personnel_no", "text"), ("position_title", "text"), ("phone", "text"),
    ("mobile", "text"), ("hire_date", "date"), ("bank_account_no", "text"), ("notes", "text"),
)


class CustomersScreen(PersonGroupScreenBase):
    FIELD_SPECS = _CUSTOMER_FIELD_SPECS
    GROUP_CODE = dimensions_service.CUSTOMER_GROUP_CODE
    EMPTY_TEXT = "هنوز مشتری‌ای تعریف نشده است."

    def __init__(self) -> None:
        super().__init__()
        self.list_title.setText("مشتریان")

    def _list_rows(self, company_id: int) -> list[dict]:
        return dimensions_service.list_customers(company_id)

    def _create(self, company_id, code, name, extra, custom_fields, parent_detail_account_id) -> None:
        dimensions_service.create_customer(
            company_id=company_id, code=code, name=name, custom_fields=custom_fields,
            parent_detail_account_id=parent_detail_account_id, **extra,
        )

    def _update(self, detail_account_id, company_id, code, name, is_active, extra, custom_fields) -> None:
        dimensions_service.update_customer(
            detail_account_id=detail_account_id, company_id=company_id, code=code, name=name,
            is_active=is_active, custom_fields=custom_fields, **extra,
        )

    def _delete_row(self, detail_account_id: int, company_id: int) -> None:
        dimensions_service.delete_customer(detail_account_id, company_id)

    # معادلِ edit_person در Kivy — برای مسیرِ فهرستِ واحدِ تفصیلی‌ها
    def edit_person(self, detail_account_id: int) -> None:
        self._load_into_form(detail_account_id)


class SuppliersScreen(PersonGroupScreenBase):
    FIELD_SPECS = _SUPPLIER_FIELD_SPECS
    GROUP_CODE = dimensions_service.SUPPLIER_GROUP_CODE
    EMPTY_TEXT = "هنوز تامین‌کننده‌ای تعریف نشده است."

    def __init__(self) -> None:
        super().__init__()
        self.list_title.setText("تامین‌کنندگان")

    def _list_rows(self, company_id: int) -> list[dict]:
        return dimensions_service.list_suppliers(company_id)

    def _create(self, company_id, code, name, extra, custom_fields, parent_detail_account_id) -> None:
        dimensions_service.create_supplier(
            company_id=company_id, code=code, name=name, custom_fields=custom_fields,
            parent_detail_account_id=parent_detail_account_id, **extra,
        )

    def _update(self, detail_account_id, company_id, code, name, is_active, extra, custom_fields) -> None:
        dimensions_service.update_supplier(
            detail_account_id=detail_account_id, company_id=company_id, code=code, name=name,
            is_active=is_active, custom_fields=custom_fields, **extra,
        )

    def _delete_row(self, detail_account_id: int, company_id: int) -> None:
        dimensions_service.delete_supplier(detail_account_id, company_id)

    def edit_person(self, detail_account_id: int) -> None:
        self._load_into_form(detail_account_id)


class PersonnelScreen(PersonGroupScreenBase):
    FIELD_SPECS = _PERSONNEL_FIELD_SPECS
    GROUP_CODE = dimensions_service.PERSONNEL_GROUP_CODE
    EMPTY_TEXT = "هنوز پرسنلی تعریف نشده است."

    def __init__(self) -> None:
        super().__init__()
        self.list_title.setText("پرسنل")

    def _list_rows(self, company_id: int) -> list[dict]:
        return dimensions_service.list_personnel(company_id)

    def _create(self, company_id, code, name, extra, custom_fields, parent_detail_account_id) -> None:
        dimensions_service.create_personnel(
            company_id=company_id, code=code, name=name, custom_fields=custom_fields,
            parent_detail_account_id=parent_detail_account_id, **extra,
        )

    def _update(self, detail_account_id, company_id, code, name, is_active, extra, custom_fields) -> None:
        dimensions_service.update_personnel(
            detail_account_id=detail_account_id, company_id=company_id, code=code, name=name,
            is_active=is_active, custom_fields=custom_fields, **extra,
        )

    def _delete_row(self, detail_account_id: int, company_id: int) -> None:
        dimensions_service.delete_personnel(detail_account_id, company_id)

    def edit_person(self, detail_account_id: int) -> None:
        self._load_into_form(detail_account_id)
