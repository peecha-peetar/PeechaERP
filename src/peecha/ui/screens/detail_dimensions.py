"""فرمِ واحدِ ثبتِ همه‌ی حساب‌هایِ تفصیلی — معادلِ Qt برایِ detail_dimensions.py/.kv.

طبقِ درخواستِ صریح: «تعریفِ تفصیلی‌ها همه در یک فرم باشد و از هدرِ فرم
نوعِ تفصیلی انتخاب و تعریف شود، منویِ جداگانه نداشته باشیم» — این صفحه
قبلاً فقط گروه‌هایِ «ساده» (بدونِ صفحه‌ی اختصاصی) را پوشش می‌داد؛ حالا
همان یک فرم، با یک کمبویِ سرستون («گروه»)، هرسه نوعِ زیر را یک‌جا پوشش
می‌دهد:
  ۱) گروه‌هایِ اشخاص (مشتری/تامین‌کننده/پرسنل) — فیلدهایِ هاردکدِ
     اختصاصیِ خودشان (کدِ اقتصادی، شناسه‌یِ ملی، ...) را دارند، چون در
     جدولِ SQLِ جداگانه‌ای (customer_details/...) ذخیره می‌شوند.
  ۲) ۷ نوعِ «فرمِ خاص» (کالا/دارایی‌ثابت/بانک/صندوق/تنخواه/مرکزِهزینه/
     پروژه) که قبلاً صفحه‌ی اختصاصیِ خودشان را داشتند (specialized_dimensions.py) —
     هیچ فیلدِ هاردکدی ندارند، فقط با فیلدهایِ اختصاصیِ پیکربندی‌شده کار می‌کنند.
  ۳) گروه‌هایِ «ساده»یِ تعریف‌شده‌یِ کاربر — مثلِ قبل.

هرسه نوع از یک زیرساختِ مشترک (سلسله‌مراتب/کدِ پیشنهادی/فیلدهایِ
اختصاصیِ پیکربندی‌شده) استفاده می‌کنند؛ فرقشان فقط در این است که
گروه‌هایِ اشخاص یک ردیفِ اضافه از فیلدهایِ هاردکد هم دارند و با
تابع‌هایِ سرویسِ اختصاصیِ خودشان (create_customer/...) ذخیره می‌شوند."""

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

# طبقِ درخواستِ صریح («کد باید اولین ستون از سمتِ راست باشد، در همه‌ی
# فرم‌هایِ این‌شکلی») — هم‌الگو با ترتیبِ ستون‌هایِ کدینگِ حساب‌ها.
_COLUMNS = ["کدِ کامل", "نام", "سطح", "وضعیت"]

_PERSON_FIELD_LABELS = {
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

# طبقِ همان الگویِ قبلی در person_group_screens.py — این سه گروه علاوه بر
# فیلدهایِ اختصاصیِ عمومی/قابلِ‌پیکربندی، یک دسته فیلدِ هاردکدِ ثابت هم
# دارند چون در جدولِ SQLِ جداگانه‌ای ذخیره می‌شوند (نه extra_fields JSONB).
_PERSON_GROUP_META = {
    dimensions_service.CUSTOMER_GROUP_CODE: {
        "field_specs": (
            ("economic_code", "text"), ("national_id", "text"), ("phone", "text"), ("mobile", "text"),
            ("address", "text"), ("credit_limit", "decimal"), ("notes", "text"),
        ),
        "list_fn": dimensions_service.list_customers,
        "create_fn": dimensions_service.create_customer,
        "update_fn": dimensions_service.update_customer,
        "delete_fn": dimensions_service.delete_customer,
    },
    dimensions_service.SUPPLIER_GROUP_CODE: {
        "field_specs": (
            ("economic_code", "text"), ("national_id", "text"), ("phone", "text"), ("mobile", "text"),
            ("address", "text"), ("bank_account_no", "text"), ("notes", "text"),
        ),
        "list_fn": dimensions_service.list_suppliers,
        "create_fn": dimensions_service.create_supplier,
        "update_fn": dimensions_service.update_supplier,
        "delete_fn": dimensions_service.delete_supplier,
    },
    dimensions_service.PERSONNEL_GROUP_CODE: {
        "field_specs": (
            ("national_id", "text"), ("personnel_no", "text"), ("position_title", "text"), ("phone", "text"),
            ("mobile", "text"), ("hire_date", "date"), ("bank_account_no", "text"), ("notes", "text"),
        ),
        "list_fn": dimensions_service.list_personnel,
        "create_fn": dimensions_service.create_personnel,
        "update_fn": dimensions_service.update_personnel,
        "delete_fn": dimensions_service.delete_personnel,
    },
}


def _find_combo_index(combo: QComboBox, data: tuple[str, int | str] | None) -> int:
    """جایگزینِ combo.findData(...) — طبقِ آزمایشِ عملی، findDataیِ Qt برایِ
    داده‌یِ نوعِ tuple (که یک شیءِ خامِ پایتون است، نه نوعِ بومیِ Qt) رفتارِ
    قابلِ‌اتکایی ندارد، هرچند itemData(i) خودش مقدارِ درست/قابلِ‌مقایسه
    برمی‌گرداند؛ پس این‌جا با یک پیمایشِ دستی همان مقایسه را انجام می‌دهیم."""
    for i in range(combo.count()):
        if combo.itemData(i) == data:
            return i
    return -1


def _make_field_widget(kind: str) -> QWidget:
    if kind == "decimal":
        widget = QDoubleSpinBox()
        widget.setRange(0, 10_000_000_000)
        widget.setDecimals(2)
        return widget
    if kind == "date":
        widget = QDateEdit()
        widget.setCalendarPopup(True)
        widget.setSpecialValueText(" ")
        widget.setDate(widget.minimumDate())
        return widget
    return QLineEdit()


class DetailDimensionsScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        # combo_data ذخیره‌شده رویِ هر آیتمِ group_combo یکی از این دو شکل است:
        #   ("dim", dimension_type_id)   -> گروهِ ساده یا یکی از ۷ نوعِ خاص
        #   ("person", group_code)       -> CUSTOMER/SUPPLIER/PERSONNEL
        self._person_groups: list[dimensions_service.PersonGroupRow] = []
        self._types: list[dimensions_service.DimensionTypeRow] = []
        self._selected: tuple[str, int | str] | None = None
        self._accounts_by_id: dict[int, dimensions_service.DetailAccountRow] = {}
        self._person_rows_by_id: dict[int, dict] = {}
        self._editing_account_id: int | None = None
        self._extra_widgets: dict[str, tuple[QWidget, str]] = {}
        self._person_field_widgets: dict[str, QWidget] = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_account_panel(), stretch=2)

        self.set_field_help([
            (
                self.group_combo,
                "نوعِ حسابِ تفصیلی‌ای که می‌خواهید بسازید یا ویرایش کنید — مشتری/تامین‌کننده/پرسنل، "
                "کالا/بانک/صندوق/... یا یک گروهِ سفارشی. ساختنِ گروهِ تازه و تنظیمِ سطح/فیلدهایش در "
                "«پیکربندیِ گروه‌هایِ تفصیلی» انجام می‌شود، نه این‌جا.",
            ),
            (
                self.show_all_levels_checkbox,
                "به‌طورِ پیش‌فرض فقط آخرین سطح (برگ‌ها) نشان داده می‌شود. با این تیک، کلِ درختِ والد و فرزند را می‌بینید.",
            ),
            (
                self.parent_combo,
                "اگر این حساب زیرمجموعه‌یِ یک حسابِ دیگر است، آن را این‌جا انتخاب کنید. "
                "بدونِ والد یعنی این حساب در سطحِ اول قرار می‌گیرد.",
            ),
            (
                self.account_code_field,
                "کدِ این حساب. برنامه بعدِ انتخابِ والد یک کدِ پیشنهادی خودش پر می‌کند، ولی می‌توانید تغییرش دهید.",
            ),
            (self.account_name_field, "نامی که در فهرست‌ها و سندها برایِ این حساب نشان داده می‌شود."),
            (
                self.account_active_checkbox,
                "حساب‌هایِ غیرِفعال از فهرستِ انتخاب در سندها کنار گذاشته می‌شوند، ولی سوابقِ قبلی‌شان می‌ماند.",
            ),
        ])

    # --- ستونِ چپ: انتخابِ گروه + فهرستِ حساب‌ها -----------------------------
    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("تعریفِ حساب‌هایِ تفصیلی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "ساختِ گروهِ تازه و تنظیمِ تعدادِ رقم/بازه/فیلدِ اختصاصی در «پیکربندیِ گروه‌هایِ تفصیلی» انجام می‌شود."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(QLabel("گروه"))
        self.group_combo = QComboBox()
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)
        layout.addWidget(self.group_combo)

        self.show_all_levels_checkbox = QCheckBox("نمایشِ همه‌یِ سطوح")
        self.show_all_levels_checkbox.toggled.connect(lambda _checked: self._rebuild_accounts_tree())
        layout.addWidget(self.show_all_levels_checkbox)

        self.accounts_table = QTreeWidget()
        self.accounts_table.setColumnCount(len(_COLUMNS))
        self.accounts_table.setHeaderLabels(_COLUMNS)
        self.accounts_table.itemClicked.connect(self._on_account_item_clicked)
        layout.addWidget(self.accounts_table, stretch=1)

        return panel

    # --- ستونِ راست: فرمِ حسابِ تفصیلی ---------------------------------------
    def _build_account_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("card")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.account_panel = scroll
        scroll.setEnabled(False)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.account_form_title = QLabel("حسابِ تفصیلیِ جدید")
        self.account_form_title.setObjectName("pageTitle")
        layout.addWidget(self.account_form_title)

        grid = QGridLayout()
        grid.addWidget(QLabel("والد"), 0, 0)
        self.parent_combo = QComboBox()
        self.parent_combo.currentIndexChanged.connect(self._on_parent_combo_changed)
        grid.addWidget(self.parent_combo, 0, 1)

        grid.addWidget(QLabel("کد"), 1, 0)
        self.account_code_field = QLineEdit()
        grid.addWidget(self.account_code_field, 1, 1)

        grid.addWidget(QLabel("نام"), 2, 0)
        self.account_name_field = QLineEdit()
        grid.addWidget(self.account_name_field, 2, 1)

        self.account_active_checkbox = QCheckBox("فعال")
        self.account_active_checkbox.setChecked(True)
        grid.addWidget(self.account_active_checkbox, 3, 1)
        layout.addLayout(grid)

        # طبقِ درخواستِ صریح: گروه‌هایِ اشخاص (مشتری/تامین‌کننده/پرسنل)
        # فیلدهایِ هاردکدِ اختصاصیِ خودشان را هم دارند (چون در جدولِ
        # جداگانه‌یِ SQL ذخیره می‌شوند) — این ردیف فقط وقتی آن گروه‌ها
        # انتخاب شده باشند نمایان می‌شود.
        self.person_fields_label = QLabel("فیلدهایِ اختصاصیِ این گروه")
        layout.addWidget(self.person_fields_label)
        self.person_fields_grid = QGridLayout()
        person_fields_widget = QWidget()
        person_fields_widget.setLayout(self.person_fields_grid)
        layout.addWidget(person_fields_widget)

        layout.addWidget(QLabel("فیلدهایِ اختصاصیِ تعریف‌شده"))
        self.extra_fields_container = QVBoxLayout()
        extra_widget = QWidget()
        extra_widget.setLayout(self.extra_fields_container)
        layout.addWidget(extra_widget)

        self.account_status_label = QLabel("")
        self.account_status_label.setObjectName("statusError")
        self.account_status_label.setWordWrap(True)
        layout.addWidget(self.account_status_label)

        buttons = QHBoxLayout()
        self.save_button = QPushButton("ذخیره")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save_account)
        buttons.addWidget(self.save_button)
        cancel_button = QPushButton("انصراف")
        cancel_button.setObjectName("flatButton")
        cancel_button.clicked.connect(self._cancel_account_edit)
        buttons.addWidget(cancel_button)
        self.delete_button = QPushButton("حذف")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self._delete_account)
        self.delete_button.setVisible(False)
        buttons.addWidget(self.delete_button)
        layout.addLayout(buttons)

        layout.addStretch(1)
        scroll.setWidget(panel)
        return scroll

    # --- بارگذاری --------------------------------------------------------
    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        previous = self._selected

        self._person_groups = dimensions_service.list_person_groups(company_id) if company_id is not None else []
        self._types = dimensions_service.list_dimension_types(company_id) if company_id is not None else []

        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItem("— انتخابِ گروه —", None)
        for g in self._person_groups:
            if g.code in _PERSON_GROUP_META:
                self.group_combo.addItem(g.name, ("person", g.code))
        for t in self._types:
            label = dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(t.code, t.code)
            self.group_combo.addItem(f"{label} ({t.detail_account_count})", ("dim", t.dimension_type_id))
        self.group_combo.blockSignals(False)

        previous_index = _find_combo_index(self.group_combo, previous) if previous is not None else -1
        if previous_index >= 0:
            self.group_combo.setCurrentIndex(previous_index)
        else:
            self._selected = None
            self.account_panel.setEnabled(False)

    def _on_group_changed(self) -> None:
        self._select(self.group_combo.currentData())

    def _select(self, combo_data: tuple[str, int | str] | None) -> None:
        self._selected = combo_data
        if combo_data is None:
            self.account_panel.setEnabled(False)
            return
        self.account_panel.setEnabled(True)
        self._cancel_account_edit()
        self._reload_accounts()

    def _is_person(self) -> bool:
        return self._selected is not None and self._selected[0] == "person"

    def _person_meta(self) -> dict:
        return _PERSON_GROUP_META[self._selected[1]]

    def _dimension_type_id(self) -> int | None:
        """dimension_type_idِ فعلی — برایِ گروه‌هایِ اشخاص، همیشه نوع‌بُعدِ
        سیستمیِ PERSON (سراسری برایِ هرسه‌شان)، برایِ بقیه همان انتخابِ کمبو."""
        if self._selected is None:
            return None
        if self._is_person():
            company_id = self._company_id()
            return dimensions_service.get_person_dimension_type_id(company_id) if company_id is not None else None
        return self._selected[1]

    def _person_group_id(self) -> int:
        if not self._is_person():
            return 0
        company_id = self._company_id()
        return dimensions_service.get_person_group_id(company_id, self._selected[1]) if company_id is not None else 0

    # --- فرمِ حسابِ تفصیلی --------------------------------------------------
    def _reload_accounts(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected is None:
            return
        dimension_type_id = self._dimension_type_id()
        person_group_id = self._person_group_id()

        if self._is_person():
            rows = self._person_meta()["list_fn"](company_id)
            self._person_rows_by_id = {r["detail_account_id"]: r for r in rows}
            self._accounts_by_id = {}
        else:
            rows = dimensions_service.list_detail_accounts(company_id, dimension_type_id)
            self._accounts_by_id = {r.detail_account_id: r for r in rows}
            self._person_rows_by_id = {}

        max_level_no = dimensions_service.get_group_max_level_no(dimension_type_id, person_group_id)

        self.parent_combo.blockSignals(True)
        self.parent_combo.clear()
        self.parent_combo.addItem("— بدونِ والد (سطحِ ۱) —", None)
        if self._is_person():
            for r in rows:
                if r["level_no"] < max_level_no and r["detail_account_id"] != self._editing_account_id:
                    self.parent_combo.addItem(f"{r['full_code']} — {r['name'] or ''}", r["detail_account_id"])
        else:
            for r in rows:
                if r.level_no < max_level_no and r.detail_account_id != self._editing_account_id:
                    self.parent_combo.addItem(f"{r.full_code} — {r.name or ''}", r.detail_account_id)
        self.parent_combo.blockSignals(False)

        self._rebuild_accounts_tree()
        self._render_person_fields()
        self._render_extra_fields()
        if self._editing_account_id is None:
            self._suggest_code_for_current_parent()

    def _rebuild_accounts_tree(self) -> None:
        """طبقِ درخواستِ صریح: نمایِ درختی + رنگِ گروه — به‌طورِ پیش‌فرض فقط
        برگ‌ها (سطحِ آخر) نشان داده می‌شوند؛ چک‌باکسِ «نمایشِ همه‌یِ سطوح»
        سلسله‌مراتبِ کاملِ والد/فرزند را می‌سازد."""
        self.accounts_table.clear()
        if self._selected is None:
            return
        color = dimensions_service.get_group_color(self._dimension_type_id(), self._person_group_id())

        if self._is_person():
            rows = [
                (r["detail_account_id"], r["parent_detail_account_id"], r["full_code"], r["name"], r["level_no"], r["is_active"])
                for r in self._person_rows_by_id.values()
            ]
        else:
            rows = [
                (r.detail_account_id, r.parent_detail_account_id, r.full_code, r.name, r.level_no, r.is_active)
                for r in self._accounts_by_id.values()
            ]

        def make_item(row: tuple) -> QTreeWidgetItem:
            detail_account_id, _parent_id, full_code, name, level_no, is_active = row
            item = QTreeWidgetItem([full_code, name or "—", str(level_no), "فعال" if is_active else "غیرفعال"])
            item.setData(0, Qt.UserRole, detail_account_id)
            if color:
                for col in range(len(_COLUMNS)):
                    item.setForeground(col, QBrush(QColor(color)))
            return item

        if self.show_all_levels_checkbox.isChecked():
            children_by_parent: dict[int | None, list[tuple]] = {}
            for row in rows:
                children_by_parent.setdefault(row[1], []).append(row)
            for siblings in children_by_parent.values():
                siblings.sort(key=lambda row: row[2])

            def add_children(parent_item: QTreeWidgetItem | None, parent_id: int | None) -> None:
                for row in children_by_parent.get(parent_id, []):
                    item = make_item(row)
                    if parent_item is None:
                        self.accounts_table.addTopLevelItem(item)
                    else:
                        parent_item.addChild(item)
                    add_children(item, row[0])

            add_children(None, None)
            self.accounts_table.expandAll()
        else:
            parent_ids = {row[1] for row in rows if row[1] is not None}
            leaves = [row for row in rows if row[0] not in parent_ids]
            for row in sorted(leaves, key=lambda row: row[2]):
                self.accounts_table.addTopLevelItem(make_item(row))

        for col in range(len(_COLUMNS)):
            self.accounts_table.resizeColumnToContents(col)

    def _on_parent_combo_changed(self, _index: int) -> None:
        if self._editing_account_id is not None:
            return
        self._suggest_code_for_current_parent()

    def _suggest_code_for_current_parent(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected is None:
            return
        dimension_type_id = self._dimension_type_id()
        parent_id = self.parent_combo.currentData()
        level_no = 1
        if parent_id is not None:
            if self._is_person():
                parent = self._person_rows_by_id.get(parent_id)
                if parent is None:
                    return
                level_no = parent["level_no"] + 1
            else:
                parent = self._accounts_by_id.get(parent_id)
                if parent is None:
                    return
                level_no = parent.level_no + 1
        self.account_code_field.setText(
            dimensions_service.suggest_next_code(company_id, dimension_type_id, level_no, self._person_group_id())
        )

    # --- فیلدهایِ هاردکدِ گروه‌هایِ اشخاص -------------------------------------
    def _render_person_fields(self, values: dict | None = None) -> None:
        while self.person_fields_grid.count():
            child = self.person_fields_grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._person_field_widgets = {}
        is_person = self._is_person()
        self.person_fields_label.setVisible(is_person)
        if not is_person:
            return
        for row_index, (field_key, kind) in enumerate(self._person_meta()["field_specs"]):
            self.person_fields_grid.addWidget(QLabel(_PERSON_FIELD_LABELS.get(field_key, field_key)), row_index, 0)
            widget = _make_field_widget(kind)
            self.person_fields_grid.addWidget(widget, row_index, 1)
            self._person_field_widgets[field_key] = widget
            if values is not None and values.get(field_key) is not None:
                value = values[field_key]
                if kind == "decimal":
                    widget.setValue(float(value))
                elif kind == "date" and isinstance(value, datetime.date):
                    widget.setDate(value)
                else:
                    widget.setText(str(value))

    def _collect_person_fields(self) -> dict:
        result: dict = {}
        for field_key, kind in self._person_meta()["field_specs"]:
            widget = self._person_field_widgets[field_key]
            if kind == "decimal":
                value = widget.value()
                result[field_key] = decimal.Decimal(str(value)) if value else None
            elif kind == "date":
                qdate = widget.date()
                result[field_key] = None if qdate == widget.minimumDate() else datetime.date(qdate.year(), qdate.month(), qdate.day())
            else:
                text = widget.text().strip()
                result[field_key] = text or None
        return result

    # --- فیلدهایِ اختصاصیِ عمومی/قابلِ‌پیکربندی -------------------------------
    def _render_extra_fields(self, values: dict | None = None) -> None:
        while self.extra_fields_container.count():
            child = self.extra_fields_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._extra_widgets = {}
        if self._selected is None:
            return
        for field_def in dimensions_service.list_group_fields(self._dimension_type_id(), self._person_group_id()):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(QLabel(field_def.label))
            widget = _make_field_widget(field_def.kind) if field_def.kind != "boolean" else QCheckBox()
            row_layout.addWidget(widget)
            self.extra_fields_container.addWidget(row)
            self._extra_widgets[field_def.field_key] = (widget, field_def.kind)

            if values is not None and values.get(field_def.field_key) is not None:
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

    # --- ویرایش/ذخیره/حذف --------------------------------------------------
    def _on_account_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        detail_account_id = item.data(0, Qt.UserRole)
        if detail_account_id is None:
            return
        self.edit_detail_account(detail_account_id)

    def edit_detail_account(self, detail_account_id: int) -> None:
        if self._is_person():
            row = self._person_rows_by_id.get(detail_account_id)
            if row is None:
                return
            self._editing_account_id = detail_account_id
            self._reload_accounts()
            self.account_form_title.setText(f"ویرایشِ «{row['full_code']}»")
            self.account_code_field.setText(row["code"])
            self.account_name_field.setText(row["name"] or "")
            self.account_active_checkbox.setChecked(row["is_active"])
            parent_id = row.get("parent_detail_account_id")
            index = self.parent_combo.findData(parent_id) if parent_id is not None else 0
            self.parent_combo.setCurrentIndex(index if index >= 0 else 0)
            self.parent_combo.setEnabled(False)
            self._render_person_fields(row)
            self._render_extra_fields(row.get("custom_fields"))
            self.delete_button.setVisible(True)
            return

        account = self._accounts_by_id.get(detail_account_id)
        if account is None:
            return
        self._editing_account_id = detail_account_id
        self._reload_accounts()
        self.account_form_title.setText(f"ویرایشِ «{account.full_code}»")
        self.account_code_field.setText(account.code)
        self.account_name_field.setText(account.name or "")
        self.account_active_checkbox.setChecked(account.is_active)
        if account.parent_detail_account_id is not None:
            index = self.parent_combo.findData(account.parent_detail_account_id)
            self.parent_combo.setCurrentIndex(index if index >= 0 else 0)
        else:
            self.parent_combo.setCurrentIndex(0)
        self.parent_combo.setEnabled(False)
        self._render_extra_fields(account.extra_fields)
        self.delete_button.setVisible(True)

    def _cancel_account_edit(self) -> None:
        self._editing_account_id = None
        self.account_form_title.setText("حسابِ تفصیلیِ جدید")
        self.account_status_label.setText("")
        self.account_code_field.clear()
        self.account_name_field.clear()
        self.account_active_checkbox.setChecked(True)
        self.parent_combo.setEnabled(True)
        if self.parent_combo.count():
            self.parent_combo.setCurrentIndex(0)
        self._render_person_fields()
        self._render_extra_fields()
        self._suggest_code_for_current_parent()
        self.accounts_table.clearSelection()
        self.delete_button.setVisible(False)

    def _save_account(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected is None:
            return
        code = self.account_code_field.text().strip()
        if not code:
            self.account_status_label.setText("کد را وارد کنید.")
            return
        name = self.account_name_field.text().strip() or None
        extra_fields = self._collect_extra_fields()

        try:
            if self._is_person():
                meta = self._person_meta()
                person_fields = self._collect_person_fields()
                if self._editing_account_id is not None:
                    meta["update_fn"](
                        detail_account_id=self._editing_account_id, company_id=company_id, code=code,
                        name=name or "", is_active=self.account_active_checkbox.isChecked(),
                        custom_fields=extra_fields, **person_fields,
                    )
                else:
                    meta["create_fn"](
                        company_id=company_id, code=code, name=name or "", custom_fields=extra_fields,
                        parent_detail_account_id=self.parent_combo.currentData(), **person_fields,
                    )
            elif self._editing_account_id is not None:
                dimensions_service.update_detail_account(
                    self._editing_account_id, company_id, code, self.account_active_checkbox.isChecked(),
                    name=name, extra_fields=extra_fields,
                )
            else:
                dimensions_service.create_detail_account(
                    company_id, self._dimension_type_id(), code, name=name,
                    parent_detail_account_id=self.parent_combo.currentData(), extra_fields=extra_fields,
                )
        except ValueError as exc:
            self.account_status_label.setText(str(exc))
            return

        selected = self._selected
        self._cancel_account_edit()
        self.refresh()
        self._select(selected)

    def _delete_account(self) -> None:
        if self._editing_account_id is None or self._selected is None:
            return
        company_id = self._company_id()
        if company_id is None:
            return
        confirm = QMessageBox.question(
            self, "حذف", "این حساب حذف شود؟ این کار قابلِ بازگشت نیست.", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            if self._is_person():
                self._person_meta()["delete_fn"](self._editing_account_id, company_id)
            else:
                dimensions_service.delete_detail_account(self._editing_account_id, company_id)
        except ValueError as exc:
            self.account_status_label.setText(str(exc))
            return

        selected = self._selected
        self._cancel_account_edit()
        self.refresh()
        self._select(selected)

    # --- برایِ ناوبری از فهرستِ واحدِ تفصیلی‌ها -----------------------------
    def select_type_and_edit(self, combo_data: tuple[str, int | str], detail_account_id: int) -> None:
        self.refresh()
        index = _find_combo_index(self.group_combo, combo_data)
        if index >= 0:
            self.group_combo.setCurrentIndex(index)
        self.edit_detail_account(detail_account_id)

    def select_type_for_new_entry(self, combo_data: tuple[str, int | str]) -> None:
        """برایِ دکمه‌ی «تفصیلیِ جدید» در فهرستِ واحد — همان گروه را انتخاب
        می‌کند و فرم را در حالتِ «رکوردِ تازه» نگه می‌دارد. صراحتاً _select
        را هم صدا می‌زند (نه فقط setCurrentIndex) چون اگر همین گروه از قبل
        انتخاب‌شده باشد، تغییرِ ایندکس سیگنال نمی‌دهد و ریست انجام نمی‌شود."""
        self.refresh()
        index = _find_combo_index(self.group_combo, combo_data)
        if index >= 0:
            self.group_combo.setCurrentIndex(index)
        self._select(combo_data)
