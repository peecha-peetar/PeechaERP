"""تنظیماتِ ماژولِ انبار — واحد/برند/تولیدکننده، روشِ قیمت‌گذاری، نگاشتِ
حساب‌هایِ حسابداری، و دلیل‌هایِ ساختاریافتهٔ اصلاح/برگشت."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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
from peecha.services import chart_of_accounts as coa_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_documents as documents_service
from peecha.services import inventory_engine as engine_service
from peecha.ui.widgets import FieldGrid, FieldSpec, LayoutEditMixin

_UOM_TYPE_LABELS = {"COUNT": "شمارشی", "WEIGHT": "وزن", "VOLUME": "حجم", "LENGTH": "طول", "AREA": "مساحت", "TIME": "زمان"}
_COSTING_METHOD_LABELS = {"FIFO": "FIFO", "WEIGHTED_AVERAGE": "میانگینِ موزون", "STANDARD": "بهایِ استاندارد"}


def _company_id() -> int | None:
    return app_session.current_company.company_id if app_session.current_company else None


class _UomTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[catalog_service.UomRow] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        _title_label = QLabel("واحدهایِ اندازه‌گیری")
        _title_label.setObjectName("pageTitle")
        layout.addWidget(_title_label)

        add_button = QPushButton("➕")
        add_button.setObjectName("primaryIconButton")
        add_button.setFixedWidth(48)
        add_button.setToolTip("واحدِ جدید")
        add_button.clicked.connect(self._add)
        layout.addWidget(add_button, alignment=Qt.AlignLeft)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["فعال", "نوع", "نام", "کد"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self._edit_selected)
        layout.addWidget(self.table)

        button_cluster = QWidget()
        button_cluster.setLayoutDirection(Qt.LeftToRight)
        buttons = QHBoxLayout(button_cluster)
        buttons.setContentsMargins(0, 0, 0, 0)
        edit_button = QPushButton("✏️")
        edit_button.setObjectName("iconButton")
        edit_button.setFixedWidth(44)
        edit_button.setToolTip("ویرایش")
        edit_button.clicked.connect(self._edit_selected)
        buttons.addWidget(edit_button)
        delete_button = QPushButton("🗑️")
        delete_button.setObjectName("dangerIconButton")
        delete_button.setFixedWidth(44)
        delete_button.setToolTip("حذف")
        delete_button.clicked.connect(self._delete_selected)
        buttons.addWidget(delete_button)
        layout.addWidget(button_cluster, alignment=Qt.AlignLeft)

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        self._rows = catalog_service.list_uoms(company_id)
        self.table.setRowCount(len(self._rows))
        for row_index, u in enumerate(self._rows):
            values = ["بله" if u.is_active else "خیر", _UOM_TYPE_LABELS.get(u.uom_type_code, u.uom_type_code), u.name, u.code]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, u.uom_id)
                self.table.setItem(row_index, col_index, item)

    def _selected_row(self) -> catalog_service.UomRow | None:
        selected = self.table.selectedItems()
        if not selected:
            return None
        uom_id = selected[0].data(Qt.UserRole)
        return next((r for r in self._rows if r.uom_id == uom_id), None)

    def _add(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("واحدِ جدید")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("کد"))
        code_field = QLineEdit()
        layout.addWidget(code_field)
        layout.addWidget(QLabel("نام"))
        name_field = QLineEdit()
        layout.addWidget(name_field)
        layout.addWidget(QLabel("نوع"))
        type_combo = QComboBox()
        for code, label in _UOM_TYPE_LABELS.items():
            type_combo.addItem(label, code)
        layout.addWidget(type_combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        company_id = _company_id()
        if company_id is None or not code_field.text().strip() or not name_field.text().strip():
            return
        try:
            catalog_service.create_uom(company_id, code_field.text().strip(), name_field.text().strip(), type_combo.currentData())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _edit_selected(self, *_args) -> None:
        row = self._selected_row()
        if row is None or row.is_global:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("ویرایشِ واحد")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("نام"))
        name_field = QLineEdit(row.name)
        layout.addWidget(name_field)
        active_checkbox = QCheckBox("فعال")
        active_checkbox.setChecked(row.is_active)
        layout.addWidget(active_checkbox)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        company_id = _company_id()
        try:
            catalog_service.update_uom(row.uom_id, company_id, row.code, name_field.text().strip(), row.uom_type_code, active_checkbox.isChecked())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _delete_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        confirm = QMessageBox.question(self, "حذف", "این واحد حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            catalog_service.delete_uom(row.uom_id, _company_id())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()


class _BrandManufacturerTab(QWidget):
    """هم‌الگو با _UomTab برایِ برند و تولیدکننده — چون هردو ساختاری
    مشابه دارند (کد/نام/فعال)، هر دو در همین تب کنارِ هم می‌آیند."""

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)
        layout.addWidget(self._build_section("برندها", is_brand=True), stretch=1)
        layout.addWidget(self._build_section("تولیدکنندگان", is_brand=False), stretch=1)

    def _build_section(self, title: str, is_brand: bool) -> QWidget:
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        _title_label = QLabel(title)
        _title_label.setObjectName("pageTitle")
        panel_layout.addWidget(_title_label)
        add_button = QPushButton("➕")
        add_button.setObjectName("primaryIconButton")
        add_button.setFixedWidth(48)
        add_button.setToolTip("افزودن")
        add_button.clicked.connect(lambda: self._add(is_brand))
        panel_layout.addWidget(add_button, alignment=Qt.AlignLeft)
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["فعال", "نام", "کد"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        panel_layout.addWidget(table)
        delete_button = QPushButton("🗑️")
        delete_button.setObjectName("dangerIconButton")
        delete_button.setFixedWidth(44)
        delete_button.setToolTip("حذفِ ردیفِ انتخاب‌شده")
        delete_button.clicked.connect(lambda: self._delete(is_brand))
        panel_layout.addWidget(delete_button)
        if is_brand:
            self.brand_table = table
        else:
            self.manufacturer_table = table
        return panel

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        self._brand_rows = catalog_service.list_brands(company_id)
        self.brand_table.setRowCount(len(self._brand_rows))
        for row_index, b in enumerate(self._brand_rows):
            for col_index, value in enumerate(["بله" if b.is_active else "خیر", b.name, b.code]):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, b.brand_id)
                self.brand_table.setItem(row_index, col_index, item)

        self._manufacturer_rows = catalog_service.list_manufacturers(company_id)
        self.manufacturer_table.setRowCount(len(self._manufacturer_rows))
        for row_index, m in enumerate(self._manufacturer_rows):
            for col_index, value in enumerate(["بله" if m.is_active else "خیر", m.name, m.code]):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, m.manufacturer_id)
                self.manufacturer_table.setItem(row_index, col_index, item)

    def _add(self, is_brand: bool) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("افزودن")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("کد"))
        code_field = QLineEdit()
        layout.addWidget(code_field)
        layout.addWidget(QLabel("نام"))
        name_field = QLineEdit()
        layout.addWidget(name_field)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        company_id = _company_id()
        if company_id is None or not code_field.text().strip() or not name_field.text().strip():
            return
        try:
            if is_brand:
                catalog_service.create_brand(company_id, code_field.text().strip(), name_field.text().strip())
            else:
                catalog_service.create_manufacturer(company_id, code_field.text().strip(), name_field.text().strip())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _delete(self, is_brand: bool) -> None:
        table = self.brand_table if is_brand else self.manufacturer_table
        selected = table.selectedItems()
        if not selected:
            return
        row_id = selected[0].data(Qt.UserRole)
        confirm = QMessageBox.question(self, "حذف", "این ردیف حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            if is_brand:
                catalog_service.delete_brand(row_id, _company_id())
            else:
                catalog_service.delete_manufacturer(row_id, _company_id())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()


class _CostingSettingsTab(LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        _title_label = QLabel("تنظیماتِ قیمت‌گذاریِ شرکت")
        _title_label.setObjectName("pageTitle")
        layout.addWidget(_title_label)

        self.method_combo = QComboBox()
        for code, label in _COSTING_METHOD_LABELS.items():
            self.method_combo.addItem(label, code)

        self.allow_override_checkbox = QCheckBox("اجازهٔ override در سطحِ کالا")
        self.allow_override_checkbox.setChecked(True)

        self.costing_grid = FieldGrid([
            FieldSpec("method", "روشِ پیش‌فرضِ قیمت‌گذاری", self.method_combo, span=1),
            FieldSpec("allow_override", "", self.allow_override_checkbox, span=1),
        ])
        layout.addWidget(self.costing_grid)
        self.register_field_grids("inventory_settings_costing", [self.costing_grid])

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

        save_button = QPushButton("💾")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(48)
        save_button.setToolTip("ذخیره")
        save_button.clicked.connect(self._save)
        layout.addWidget(save_button, alignment=Qt.AlignLeft)
        layout.addStretch(1)

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        method_code, allow_override = engine_service.get_costing_settings(company_id)
        if method_code:
            self.method_combo.setCurrentIndex(max(0, self.method_combo.findData(method_code)))
        self.allow_override_checkbox.setChecked(allow_override)
        self.status_label.setText("")

    def _save(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        try:
            engine_service.set_costing_settings(company_id, self.method_combo.currentData(), self.allow_override_checkbox.isChecked())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setObjectName("statusSuccess")
        self.status_label.setText("ذخیره شد.")


class _AccountMappingsTab(LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._combos: dict[str, QComboBox] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        _title_label = QLabel("نگاشتِ حساب‌هایِ حسابداری")
        _title_label.setObjectName("pageTitle")
        layout.addWidget(_title_label)
        layout.addWidget(QLabel("هر عملیاتِ انبار به یک حساب (معین) نگاشت می‌شود؛ بدونِ نگاشت، ثبتِ سندِ خودکار متوقف می‌شود."))

        mapping_fields = []
        for key, label in engine_service.MAPPING_LABELS.items():
            combo = QComboBox()
            combo.setMinimumWidth(280)
            self._combos[key] = combo
            mapping_fields.append(FieldSpec(key, label, combo, span=3))
        self.mapping_grid = FieldGrid(mapping_fields, columns=3)
        layout.addWidget(self.mapping_grid)
        self.register_field_grids("inventory_settings_account_mappings", [self.mapping_grid])

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

        save_button = QPushButton("💾")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(48)
        save_button.setToolTip("ذخیره")
        save_button.clicked.connect(self._save)
        layout.addWidget(save_button, alignment=Qt.AlignLeft)
        layout.addStretch(1)

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        accounts = [(a.account_id, f"{a.full_code} — {a.name}") for a in coa_service.list_accounts(company_id) if a.is_postable]
        current = engine_service.list_account_mappings(company_id)
        current_by_key = {c.mapping_key: c.account_id for c in current}
        for key, combo in self._combos.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("(تعیین‌نشده)", None)
            for account_id, label in accounts:
                combo.addItem(label, account_id)
            combo.setCurrentIndex(max(0, combo.findData(current_by_key.get(key))))
            combo.blockSignals(False)
        self.status_label.setText("")

    def _save(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        for key, combo in self._combos.items():
            account_id = combo.currentData()
            if account_id is not None:
                engine_service.set_account_mapping(company_id, key, account_id)
        self.status_label.setObjectName("statusSuccess")
        self.status_label.setText("ذخیره شد.")


class _FeatureToggleTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._checkboxes: dict[str, QCheckBox] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        title = QLabel("قابلیت‌هایِ فعال (Feature Toggle)")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("فعال‌سازیِ هر قابلیت ممکن است به قابلیتِ دیگری وابسته باشد."))

        self.rows_layout = QVBoxLayout()
        layout.addLayout(self.rows_layout)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

    def refresh(self) -> None:
        company_id = _company_id()
        while self.rows_layout.count():
            child = self.rows_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._checkboxes = {}
        if company_id is None:
            return
        for feature in engine_service.list_features(company_id):
            checkbox = QCheckBox(feature.name)
            checkbox.setChecked(feature.is_enabled)
            checkbox.toggled.connect(lambda checked, code=feature.feature_code: self._toggle(code, checked))
            self._checkboxes[feature.feature_code] = checkbox
            self.rows_layout.addWidget(checkbox)
        self.status_label.setText("")

    def _toggle(self, feature_code: str, checked: bool) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        try:
            engine_service.set_feature_enabled(company_id, feature_code, checked)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            self._checkboxes[feature_code].blockSignals(True)
            self._checkboxes[feature_code].setChecked(not checked)
            self._checkboxes[feature_code].blockSignals(False)
            return
        self.status_label.setText("")


class _ReasonCodesTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._tables: dict[str, QTableWidget] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)
        layout.addWidget(self._build_section("دلیل‌هایِ اصلاح", "ADJUSTMENT"), stretch=1)
        layout.addWidget(self._build_section("دلیل‌هایِ برگشت از فروش", "RETURN_IN"), stretch=1)
        layout.addWidget(self._build_section("دلیل‌هایِ برگشت به تامین‌کننده", "RETURN_OUT"), stretch=1)

    def _build_section(self, title: str, applies_to: str) -> QWidget:
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        _title_label = QLabel(title)
        _title_label.setObjectName("pageTitle")
        panel_layout.addWidget(_title_label)
        add_button = QPushButton("➕")
        add_button.setObjectName("primaryIconButton")
        add_button.setFixedWidth(48)
        add_button.setToolTip("افزودن")
        add_button.clicked.connect(lambda: self._add(applies_to))
        panel_layout.addWidget(add_button, alignment=Qt.AlignLeft)
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["نام", "کد"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        panel_layout.addWidget(table)
        delete_button = QPushButton("🗑️")
        delete_button.setObjectName("dangerIconButton")
        delete_button.setFixedWidth(44)
        delete_button.setToolTip("حذفِ ردیفِ انتخاب‌شده")
        delete_button.clicked.connect(lambda: self._delete(applies_to))
        panel_layout.addWidget(delete_button)
        self._tables[applies_to] = table
        return panel

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        for applies_to, table in self._tables.items():
            rows = documents_service.list_reason_codes(company_id, applies_to, active_only=False)
            table.setRowCount(len(rows))
            for row_index, r in enumerate(rows):
                for col_index, value in enumerate([r.name, r.code]):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.UserRole, r.reason_code_id)
                    table.setItem(row_index, col_index, item)

    def _add(self, applies_to: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("افزودنِ دلیل")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("کد"))
        code_field = QLineEdit()
        layout.addWidget(code_field)
        layout.addWidget(QLabel("نام"))
        name_field = QLineEdit()
        layout.addWidget(name_field)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        company_id = _company_id()
        if company_id is None or not code_field.text().strip() or not name_field.text().strip():
            return
        try:
            documents_service.create_reason_code(company_id, applies_to, code_field.text().strip(), name_field.text().strip())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _delete(self, applies_to: str) -> None:
        table = self._tables[applies_to]
        selected = table.selectedItems()
        if not selected:
            return
        reason_id = selected[0].data(Qt.UserRole)
        confirm = QMessageBox.question(self, "حذف", "این دلیل حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            documents_service.delete_reason_code(reason_id, _company_id())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()


class _CategoriesTab(LayoutEditMixin, QWidget):
    """دسته‌بندیِ کالا (بخشِ ۱) + نگاشتِ حسابِ حسابداری در سطحِ دسته (بخشِ ۱۴،
    override رویِ نگاشتِ سراسری — فعلاً فقط تنظیم؛ اتصال به موتورِ ثبت در
    دورِ بعدی)."""

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[catalog_service.ItemCategoryRow] = []
        self._selected_category_id: int | None = None
        self._mapping_combos: dict[str, QComboBox] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)
        layout.addWidget(self._build_list_panel(), stretch=1)
        layout.addWidget(self._build_mapping_panel(), stretch=1)

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        title = QLabel("دسته‌بندیِ کالا")
        title.setObjectName("pageTitle")
        panel_layout.addWidget(title)

        add_button = QPushButton("➕")
        add_button.setObjectName("primaryIconButton")
        add_button.setFixedWidth(48)
        add_button.setToolTip("دستهٔ جدید")
        add_button.clicked.connect(self._add)
        panel_layout.addWidget(add_button, alignment=Qt.AlignLeft)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["فعال", "نام", "کد"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        panel_layout.addWidget(self.table)

        button_cluster = QWidget()
        button_cluster.setLayoutDirection(Qt.LeftToRight)
        buttons = QHBoxLayout(button_cluster)
        buttons.setContentsMargins(0, 0, 0, 0)
        edit_button = QPushButton("✏️")
        edit_button.setObjectName("iconButton")
        edit_button.setFixedWidth(44)
        edit_button.setToolTip("ویرایش")
        edit_button.clicked.connect(self._edit_selected)
        buttons.addWidget(edit_button)
        delete_button = QPushButton("🗑️")
        delete_button.setObjectName("dangerIconButton")
        delete_button.setFixedWidth(44)
        delete_button.setToolTip("حذف")
        delete_button.clicked.connect(self._delete_selected)
        buttons.addWidget(delete_button)
        panel_layout.addWidget(button_cluster, alignment=Qt.AlignLeft)
        return panel

    def _build_mapping_panel(self) -> QWidget:
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        title = QLabel("نگاشتِ حسابِ این دسته (override)")
        title.setObjectName("pageTitle")
        panel_layout.addWidget(title)
        panel_layout.addWidget(QLabel("اگر دسته‌ای انتخاب نشده باشد یا برایِ کلیدی مقداری تعیین نشود، نگاشتِ سراسریِ شرکت استفاده می‌شود."))

        mapping_fields = []
        for key, label in engine_service.MAPPING_LABELS.items():
            combo = QComboBox()
            combo.setMinimumWidth(240)
            self._mapping_combos[key] = combo
            mapping_fields.append(FieldSpec(key, label, combo, span=3))
        self.mapping_grid = FieldGrid(mapping_fields, columns=3)
        panel_layout.addWidget(self.mapping_grid)
        self.register_field_grids("inventory_settings_category_mappings", [self.mapping_grid])

        self.mapping_status_label = QLabel("")
        self.mapping_status_label.setObjectName("statusError")
        panel_layout.addWidget(self.mapping_status_label)

        save_button = QPushButton("🗺️")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(48)
        save_button.setToolTip("ذخیرهٔ نگاشت")
        save_button.clicked.connect(self._save_mapping)
        panel_layout.addWidget(save_button, alignment=Qt.AlignLeft)
        panel_layout.addStretch(1)
        return panel

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._rows = catalog_service.list_categories(company_id)
        self.table.setRowCount(len(self._rows))
        for row_index, c in enumerate(self._rows):
            values = ["بله" if c.is_active else "خیر", c.name, c.code]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, c.category_id)
                self.table.setItem(row_index, col_index, item)
        self._refresh_mapping_accounts()

    def _refresh_mapping_accounts(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        accounts = [(a.account_id, f"{a.full_code} — {a.name}") for a in coa_service.list_accounts(company_id) if a.is_postable]
        current_by_key: dict[str, int] = {}
        if self._selected_category_id is not None:
            current_by_key = {
                m.mapping_key: m.account_id
                for m in engine_service.list_category_account_mappings(self._selected_category_id)
            }
        for key, combo in self._mapping_combos.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("(از نگاشتِ سراسری پیروی کند)", None)
            for account_id, label in accounts:
                combo.addItem(label, account_id)
            combo.setCurrentIndex(max(0, combo.findData(current_by_key.get(key))))
            combo.blockSignals(False)
        self.mapping_status_label.setText("")

    def _selected_row(self) -> catalog_service.ItemCategoryRow | None:
        selected = self.table.selectedItems()
        if not selected:
            return None
        category_id = selected[0].data(Qt.UserRole)
        return next((r for r in self._rows if r.category_id == category_id), None)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        self._selected_category_id = item.data(Qt.UserRole) if item is not None else None
        self._refresh_mapping_accounts()

    def _add(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("دستهٔ جدید")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("کد"))
        code_field = QLineEdit()
        layout.addWidget(code_field)
        layout.addWidget(QLabel("نام"))
        name_field = QLineEdit()
        layout.addWidget(name_field)
        layout.addWidget(QLabel("دستهٔ والد (اختیاری)"))
        parent_combo = QComboBox()
        parent_combo.addItem("(بدونِ والد)", None)
        for c in self._rows:
            parent_combo.addItem(f"{c.code} — {c.name}", c.category_id)
        layout.addWidget(parent_combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        company_id = self._company_id()
        if company_id is None or not code_field.text().strip() or not name_field.text().strip():
            return
        try:
            catalog_service.create_category(company_id, code_field.text().strip(), name_field.text().strip(), parent_combo.currentData())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _edit_selected(self, *_args) -> None:
        row = self._selected_row()
        if row is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("ویرایشِ دسته")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("نام"))
        name_field = QLineEdit(row.name)
        layout.addWidget(name_field)
        active_checkbox = QCheckBox("فعال")
        active_checkbox.setChecked(row.is_active)
        layout.addWidget(active_checkbox)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            catalog_service.update_category(row.category_id, self._company_id(), name_field.text().strip(), active_checkbox.isChecked())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _delete_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        confirm = QMessageBox.question(self, "حذف", "این دسته حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            catalog_service.delete_category(row.category_id, self._company_id())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        if self._selected_category_id == row.category_id:
            self._selected_category_id = None
        self.refresh()

    def _save_mapping(self) -> None:
        if self._selected_category_id is None:
            self.mapping_status_label.setText("ابتدا یک دسته را از فهرست انتخاب کنید.")
            return
        for key, combo in self._mapping_combos.items():
            account_id = combo.currentData()
            if account_id is not None:
                engine_service.set_category_account_mapping(self._selected_category_id, key, account_id)
            else:
                engine_service.delete_category_account_mapping(self._selected_category_id, key)
        self.mapping_status_label.setObjectName("statusSuccess")
        self.mapping_status_label.setText("ذخیره شد.")
