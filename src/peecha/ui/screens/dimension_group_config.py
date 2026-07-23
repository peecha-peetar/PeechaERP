"""پیکربندیِ گروه‌هایِ تفصیلی — ساختِ گروهِ تازه + تنظیمِ تعدادِ سطح/بازه‌یِ
از-تا/فیلدهایِ اختصاصیِ هر گروه (تا ۴ سطح). طبقِ درخواستِ صریح، تعدادِ رقمِ
هر سطح سراسری شده (تنظیماتِ «کدینگِ حسابداری») و اینجا فقط بازه و سقفِ
تعدادِ سطحِ هر گروه تنظیم می‌شود.

طبقِ درخواستِ صریح: این بخش از صفحه‌ی قدیمیِ سه‌ستونیِ «مراکزِ هزینه و
ابعادِ تفصیلی» جدا شده — آن صفحه فقط به ثبتِ خودِ حساب‌هایِ تفصیلیِ
گروه‌هایِ «ساده» (بدونِ صفحه‌ی اختصاصی) محدود شده، و ساختِ گروه/پیکربندیِ
سطوح این‌جا آمده. گروه‌هایِ «فرمِ خاص» (کالا/دارایی‌ثابت/بانک/صندوق/
تنخواه/مرکزِ هزینه/پروژه) هم این‌جا قابلِ‌پیکربندی‌اند (چون سطوح/فیلدهایِ
اختصاصیِ آن‌ها هم از همین acc.detail_group_levels/detail_group_fields
می‌آید)، فقط ثبتِ خودِ حساب‌هایشان در صفحه‌ی اختصاصیِ خودشان انجام می‌شود.

طبقِ درخواستِ صریحِ بعدی: «همه گروه‌های تفصیلی حتی مشتری/تامین‌کننده/
پرسنل» هم باید این‌جا قابلِ‌پیکربندی باشند. مشکل: این سه، برخلافِ بقیه،
یک نوع‌بُعدِ مستقل نیستند — هرسه زیرِ همان نوع‌بُعدِ سیستمیِ PERSON‌اند و
فقط با person_group_id از هم جدا می‌شوند (acc.person_groups). پس هر
آیتمِ این فهرست حالا یک سه‌تایی نگه می‌دارد: (dimension_type_id,
person_group_id, برچسبِ نمایشی) — برایِ گروه‌هایِ معمولی person_group_id
همیشه ۰ (بدونِ محدودیت) است؛ برایِ مشتری/تامین‌کننده/پرسنل، همه
dimension_type_id یکسان (PERSON) ولی person_group_id واقعیِ خودشان را
دارند تا acc.detail_group_levels/detail_group_fields (که با ستونِ تازه‌ی
person_group_id کلید می‌خورند) مستقل از هم پیکربندی شوند."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import journal_entries as je_service

_FIELD_KIND_OPTIONS = [("text", "متن"), ("decimal", "عدد اعشاری"), ("date", "تاریخ"), ("boolean", "بله/خیر")]
_LEVEL_COUNT = 4

_PERSON_GROUP_LIST_FUNCS = {
    dimensions_service.CUSTOMER_GROUP_CODE: dimensions_service.list_customers,
    dimensions_service.SUPPLIER_GROUP_CODE: dimensions_service.list_suppliers,
    dimensions_service.PERSONNEL_GROUP_CODE: dimensions_service.list_personnel,
}


class _GroupFieldRowWidget(QWidget):
    def __init__(self, on_remove, initial: dimensions_service.GroupFieldRow | None = None) -> None:
        super().__init__()
        self._on_remove = on_remove
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.key_field = QLineEdit()
        self.key_field.setPlaceholderText("کلید (مثلاً account_no)")
        layout.addWidget(self.key_field)

        self.label_field = QLineEdit()
        self.label_field.setPlaceholderText("عنوان")
        layout.addWidget(self.label_field)

        self.kind_combo = QComboBox()
        for code, label in _FIELD_KIND_OPTIONS:
            self.kind_combo.addItem(label, code)
        layout.addWidget(self.kind_combo)

        self.required_checkbox = QCheckBox("اجباری")
        layout.addWidget(self.required_checkbox)

        remove_button = QPushButton("حذف")
        remove_button.setObjectName("dangerButton")
        remove_button.clicked.connect(lambda: self._on_remove(self))
        layout.addWidget(remove_button)

        if initial is not None:
            self.key_field.setText(initial.field_key)
            self.label_field.setText(initial.label)
            index = self.kind_combo.findData(initial.kind)
            self.kind_combo.setCurrentIndex(index if index >= 0 else 0)
            self.required_checkbox.setChecked(initial.is_required)

    def to_field_dict(self, sort_order: int) -> dict:
        return {
            "field_key": self.key_field.text().strip(),
            "label": self.label_field.text().strip(),
            "kind": self.kind_combo.currentData(),
            "is_required": self.required_checkbox.isChecked(),
            "sort_order": sort_order,
        }


class DimensionGroupConfigScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._types: list[dimensions_service.DimensionTypeRow] = []
        self._selected_type_id: int | None = None
        self._selected_person_group_id: int = 0
        self._field_rows: list[_GroupFieldRowWidget] = []

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_types_panel(), stretch=2)
        outer.addWidget(self._build_config_panel(), stretch=3)

    # --- ستونِ ۱: گروه‌ها ---------------------------------------------------
    def _build_types_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("گروه‌هایِ تفصیلی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "کالا/دارایی‌ثابت/بانک/صندوق/تنخواه/مرکزِ هزینه/پروژه + مشتری/تامین‌کننده/پرسنل + گروه‌هایِ ساده‌یِ دلخواه."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.types_list = QListWidget()
        self.types_list.itemClicked.connect(self._on_type_selected)
        layout.addWidget(self.types_list)

        layout.addWidget(QLabel("کدِ گروهِ تازه"))
        self.new_type_code_field = QLineEdit()
        layout.addWidget(self.new_type_code_field)

        self.type_status_label = QLabel("")
        self.type_status_label.setObjectName("statusError")
        self.type_status_label.setWordWrap(True)
        layout.addWidget(self.type_status_label)

        create_button = QPushButton("افزودنِ گروه")
        create_button.setObjectName("primaryButton")
        create_button.clicked.connect(self._create_type)
        layout.addWidget(create_button)

        layout.addStretch(1)
        return panel

    # --- ستونِ ۲: پیکربندیِ سطوح/فیلدها --------------------------------------
    def _build_config_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        self.config_panel = panel
        panel.setEnabled(False)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.config_title = QLabel("پیکربندیِ گروه")
        self.config_title.setObjectName("pageTitle")
        layout.addWidget(self.config_title)

        self.lock_hint_label = QLabel("")
        self.lock_hint_label.setObjectName("sectionHint")
        self.lock_hint_label.setWordWrap(True)
        layout.addWidget(self.lock_hint_label)

        max_level_row = QHBoxLayout()
        max_level_row.addWidget(QLabel("تعدادِ سطحِ این گروه"))
        self.max_level_spin = QSpinBox()
        self.max_level_spin.setRange(1, _LEVEL_COUNT)
        max_level_row.addWidget(self.max_level_spin)
        self.save_max_level_button = QPushButton("ذخیره")
        self.save_max_level_button.setObjectName("flatButton")
        self.save_max_level_button.clicked.connect(self._save_max_level)
        max_level_row.addWidget(self.save_max_level_button)
        max_level_row.addStretch(1)
        layout.addLayout(max_level_row)

        layout.addWidget(
            QLabel(
                "بازه‌ی از-تا برایِ هر سطح (صفر = بدونِ محدودیت) — تعدادِ رقمِ هر سطح سراسری است و در "
                "تنظیماتِ «کدینگِ حسابداری» مشخص می‌شود، این‌جا فقط بازه مخصوصِ همین گروه است."
            )
        )
        levels_grid = QGridLayout()
        levels_grid.setSpacing(6)
        levels_grid.addWidget(QLabel("سطح"), 0, 0)
        levels_grid.addWidget(QLabel("از"), 0, 1)
        levels_grid.addWidget(QLabel("تا"), 0, 2)
        self._level_widgets: dict[int, tuple[QSpinBox, QSpinBox]] = {}
        for row, level_no in enumerate(range(1, _LEVEL_COUNT + 1), start=1):
            levels_grid.addWidget(QLabel(f"سطحِ {level_no}"), row, 0)
            range_from = QSpinBox()
            range_from.setRange(0, 999_999_999)
            range_to = QSpinBox()
            range_to.setRange(0, 999_999_999)
            levels_grid.addWidget(range_from, row, 1)
            levels_grid.addWidget(range_to, row, 2)
            self._level_widgets[level_no] = (range_from, range_to)
        layout.addLayout(levels_grid)

        self.save_levels_button = QPushButton("ذخیره‌ی بازه‌یِ سطوح")
        self.save_levels_button.setObjectName("flatButton")
        self.save_levels_button.clicked.connect(self._save_levels)
        layout.addWidget(self.save_levels_button)

        layout.addWidget(QLabel("فیلدهایِ اختصاصیِ این گروه"))
        self.fields_container = QVBoxLayout()
        fields_widget = QWidget()
        fields_widget.setLayout(self.fields_container)
        layout.addWidget(fields_widget)

        add_field_button = QPushButton("+ افزودنِ فیلد")
        add_field_button.setObjectName("flatButton")
        add_field_button.clicked.connect(lambda: self._add_field_row())
        layout.addWidget(add_field_button)

        save_fields_button = QPushButton("ذخیره‌ی فیلدها")
        save_fields_button.setObjectName("primaryButton")
        save_fields_button.clicked.connect(self._save_fields)
        layout.addWidget(save_fields_button)

        layout.addStretch(1)
        return panel

    # --- بارگذاری ------------------------------------------------------------
    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        self._types = dimensions_service.list_dimension_types(company_id) if company_id is not None else []
        self.types_list.clear()
        for t in self._types:
            label = dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(t.code, t.code)
            item = QListWidgetItem(f"{label} ({t.detail_account_count})")
            item.setData(Qt.UserRole, (t.dimension_type_id, 0, label))
            self.types_list.addItem(item)

        if company_id is not None:
            person_dimension_type_id = dimensions_service.get_person_dimension_type_id(company_id)
            for group in dimensions_service.list_person_groups(company_id):
                list_func = _PERSON_GROUP_LIST_FUNCS.get(group.code)
                count = len(list_func(company_id)) if list_func else 0
                item = QListWidgetItem(f"{group.name} ({count})")
                item.setData(Qt.UserRole, (person_dimension_type_id, group.person_group_id, group.name))
                self.types_list.addItem(item)

        if self._selected_type_id is None:
            self.config_panel.setEnabled(False)

    def _create_type(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        code = self.new_type_code_field.text().strip()
        if not code:
            self.type_status_label.setText("کد را وارد کنید.")
            return
        try:
            new_type = dimensions_service.create_dimension_type(company_id, code)
        except ValueError as exc:
            self.type_status_label.setText(str(exc))
            return
        self.type_status_label.setText("")
        self.new_type_code_field.clear()
        self.refresh()
        label = dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(new_type.code, new_type.code)
        self._select_type(new_type.dimension_type_id, 0, label)

    def _on_type_selected(self, item: QListWidgetItem) -> None:
        dimension_type_id, person_group_id, label = item.data(Qt.UserRole)
        self._select_type(dimension_type_id, person_group_id, label)

    def _select_type(self, dimension_type_id: int, person_group_id: int = 0, label: str | None = None) -> None:
        self._selected_type_id = dimension_type_id
        self._selected_person_group_id = person_group_id
        if label is None:
            dim_type = next((t for t in self._types if t.dimension_type_id == dimension_type_id), None)
            label = (
                dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(dim_type.code, dim_type.code)
                if dim_type is not None
                else str(dimension_type_id)
            )
        self.config_title.setText(f"پیکربندیِ گروهِ «{label}»")
        self.config_panel.setEnabled(True)
        self.max_level_spin.setValue(dimensions_service.get_group_max_level_no(dimension_type_id, person_group_id))
        self._load_levels()
        self._load_fields()

        company_id = self._company_id()
        locked = company_id is not None and je_service.company_has_any_entries(company_id)
        for range_from, range_to in self._level_widgets.values():
            range_from.setEnabled(not locked)
            range_to.setEnabled(not locked)
        self.save_levels_button.setEnabled(not locked)
        self.max_level_spin.setEnabled(not locked)
        self.save_max_level_button.setEnabled(not locked)
        self.lock_hint_label.setText(
            "این شرکت سند دارد؛ تنظیماتِ رقم/بازه/تعدادِ سطح دیگر قابلِ‌تغییر نیست." if locked else ""
        )

    def _save_max_level(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_type_id is None:
            return
        try:
            dimensions_service.set_group_max_level_no(
                self._selected_type_id, company_id, self.max_level_spin.value(), self._selected_person_group_id
            )
        except ValueError as exc:
            self.type_status_label.setText(str(exc))
            return
        self.type_status_label.setText("")

    # --- سطوح ------------------------------------------------------------
    def _load_levels(self) -> None:
        rows = {
            row.level_no: row
            for row in dimensions_service.list_group_levels(self._selected_type_id, self._selected_person_group_id)
        }
        for level_no, (range_from, range_to) in self._level_widgets.items():
            row = rows.get(level_no)
            range_from.setValue(row.range_from if row and row.range_from is not None else 0)
            range_to.setValue(row.range_to if row and row.range_to is not None else 0)

    def _save_levels(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_type_id is None:
            return
        levels = {
            level_no: {
                "range_from": range_from.value() or None,
                "range_to": range_to.value() or None,
            }
            for level_no, (range_from, range_to) in self._level_widgets.items()
            if range_from.value() > 0 or range_to.value() > 0
        }
        try:
            dimensions_service.set_group_levels(
                self._selected_type_id, company_id, levels, self._selected_person_group_id
            )
        except ValueError as exc:
            self.type_status_label.setText(str(exc))
            return
        self.type_status_label.setText("")

    # --- فیلدهایِ اختصاصیِ گروه --------------------------------------------
    def _load_fields(self) -> None:
        while self.fields_container.count():
            child = self.fields_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._field_rows = []
        for field_row in dimensions_service.list_group_fields(self._selected_type_id, self._selected_person_group_id):
            self._add_field_row(field_row)

    def _add_field_row(self, initial: dimensions_service.GroupFieldRow | None = None) -> None:
        row_widget = _GroupFieldRowWidget(self._remove_field_row, initial)
        self.fields_container.addWidget(row_widget)
        self._field_rows.append(row_widget)

    def _remove_field_row(self, row_widget: _GroupFieldRowWidget) -> None:
        self._field_rows.remove(row_widget)
        self.fields_container.removeWidget(row_widget)
        row_widget.deleteLater()

    def _save_fields(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_type_id is None:
            return
        fields = [row.to_field_dict(i) for i, row in enumerate(self._field_rows)]
        for f in fields:
            if not f["field_key"] or not f["label"]:
                self.type_status_label.setText("کلید و عنوانِ همه‌ی فیلدها را پر کنید.")
                return
        try:
            dimensions_service.set_group_fields(
                self._selected_type_id, company_id, fields, self._selected_person_group_id
            )
        except ValueError as exc:
            self.type_status_label.setText(str(exc))
            return
        self.type_status_label.setText("")
        self._load_fields()
