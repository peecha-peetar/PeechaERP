"""کاتالوگِ کالا/خدمت — کالا موجودیتِ تازه‌ای نیست، تفصیلیِ سطحِ‌آخرِ گروهِ
INVENTORY_ITEM است؛ این فرم فقط رویِ inv.items (جدولِ اقماری) + تفصیلیِ
همان کالا کار می‌کند.

طبقِ طراحیِ ماژولار (فازِ ۰): فرم به‌جایِ یک بلوکِ تختِ همه‌فیلده، در تب‌ها
سازمان‌دهی شده و ردیف‌هایِ ردیابی/موجودی بر اساسِ نوعِ کالا (کالا/خدمت) و
قابلیت‌هایِ فعالِ شرکت (Feature Toggle، از تنظیماتِ انبار) نمایان/مخفی
می‌شوند. کمبوهایی که از جدولِ دیگری می‌خوانند (واحد/برند/تولیدکننده) یک
دکمهٔ «+» کنارشان دارند تا بدونِ ترکِ فرم، ردیفِ تازه ساخته شود."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_engine as engine_service
from peecha.ui.widgets import FieldHelpMixin

_COLUMNS = ["فعال", "وضعیت", "واحد", "نام", "کد"]
_KIND_LABELS = {"GOOD": "کالا", "SERVICE": "خدمت"}
_LIFECYCLE_LABELS = {"DRAFT": "پیش‌نویس", "ACTIVE": "فعال", "DISCONTINUED": "متوقف‌شده"}
_COSTING_LABELS = {"": "(پیش‌فرضِ شرکت)", "FIFO": "FIFO", "WEIGHTED_AVERAGE": "میانگینِ موزون", "STANDARD": "بهایِ استاندارد"}
_UOM_TYPE_LABELS = {"COUNT": "شمارشی", "WEIGHT": "وزن", "VOLUME": "حجم", "LENGTH": "طول", "AREA": "مساحت", "TIME": "زمان"}


def _wrap_scrollable(content: QWidget) -> QWidget:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidget(content)
    wrapper = QWidget()
    wrapper.setObjectName("card")
    wrapper_layout = QVBoxLayout(wrapper)
    wrapper_layout.setContentsMargins(0, 0, 0, 0)
    wrapper_layout.setSpacing(0)
    wrapper_layout.addWidget(scroll)
    return wrapper


class InventoryItemsScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[catalog_service.ItemRow] = []
        self._editing_id: int | None = None
        self._enabled_features: set[str] = set()

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)

        self.set_field_help([
            (self.code_field, "کدِ یکتایِ این کالا/خدمت در سطحِ شرکت."),
            (self.name_field, "نامِ نمایشیِ کالا/خدمت."),
            (self.kind_combo, "کالایِ فیزیکی موجودی‌محور است؛ خدمت هرگز موجودی ندارد."),
            (self.uom_combo, "واحدِ پایه — پس از اولین حرکتِ انبار دیگر قابلِ‌تغییر نیست."),
            (self.costing_combo, "روشِ قیمت‌گذاریِ اختصاصیِ این کالا؛ خالی یعنی از تنظیماتِ شرکت پیروی می‌کند."),
            (self.is_stock_tracked_checkbox, "خدمت نمی‌تواند موجودی‌محور باشد."),
            (self.track_expiry_checkbox, "ردیابیِ انقضا نیازمندِ فعال‌بودنِ ردیابیِ بچ است."),
        ])

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("کاتالوگِ کالا و خدمت")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        new_button = QPushButton("+ کالایِ جدید")
        new_button.setObjectName("primaryButton")
        new_button.clicked.connect(self._reset_form)
        layout.addWidget(new_button, alignment=Qt.AlignLeft)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)
        return _wrap_scrollable(panel)

    # --- ساختارِ کلیِ فرم: تب‌بندی‌شده ---------------------------------------
    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)

        self.form_title = QLabel("کالایِ جدید")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_basic_info_tab(), "اطلاعاتِ پایه")
        self.tabs.addTab(self._build_sales_tracking_tab(), "فروش/خرید و ردیابی")
        layout.addWidget(self.tabs, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        save_button = QPushButton("ذخیره")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._save)
        buttons.addWidget(save_button)

        cancel_button = QPushButton("انصراف")
        cancel_button.setObjectName("flatButton")
        cancel_button.clicked.connect(self._reset_form)
        buttons.addWidget(cancel_button)

        self.delete_button = QPushButton("حذف")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self._delete)
        self.delete_button.setVisible(False)
        buttons.addWidget(self.delete_button)

        layout.addLayout(buttons)
        return _wrap_scrollable(panel)

    # --- تبِ اطلاعاتِ پایه ---------------------------------------------------
    def _build_basic_info_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        layout.addWidget(QLabel("کد"))
        self.code_field = QLineEdit()
        layout.addWidget(self.code_field)

        layout.addWidget(QLabel("نام"))
        self.name_field = QLineEdit()
        layout.addWidget(self.name_field)

        layout.addWidget(QLabel("نوع"))
        self.kind_combo = QComboBox()
        for code, label in _KIND_LABELS.items():
            self.kind_combo.addItem(label, code)
        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        layout.addWidget(self.kind_combo)

        self.uom_combo = QComboBox()
        layout.addWidget(self._make_combo_with_add_row("واحدِ پایه", self.uom_combo, self._quick_add_uom))

        self.brand_combo = QComboBox()
        layout.addWidget(self._make_combo_with_add_row("برند", self.brand_combo, self._quick_add_brand))

        self.manufacturer_combo = QComboBox()
        layout.addWidget(self._make_combo_with_add_row("تولیدکننده", self.manufacturer_combo, self._quick_add_manufacturer))

        layout.addWidget(QLabel("روشِ قیمت‌گذاری"))
        self.costing_combo = QComboBox()
        for code, label in _COSTING_LABELS.items():
            self.costing_combo.addItem(label, code or None)
        layout.addWidget(self.costing_combo)

        self.lifecycle_row = QWidget()
        lifecycle_layout = QVBoxLayout(self.lifecycle_row)
        lifecycle_layout.setContentsMargins(0, 0, 0, 0)
        lifecycle_layout.addWidget(QLabel("وضعیتِ چرخهٔ‌عمر"))
        self.lifecycle_combo = QComboBox()
        for code, label in _LIFECYCLE_LABELS.items():
            self.lifecycle_combo.addItem(label, code)
        lifecycle_layout.addWidget(self.lifecycle_combo)
        layout.addWidget(self.lifecycle_row)

        layout.addWidget(QLabel("یادداشت"))
        self.notes_field = QTextEdit()
        self.notes_field.setMaximumHeight(60)
        layout.addWidget(self.notes_field)

        self.is_active_checkbox = QCheckBox("فعال")
        self.is_active_checkbox.setChecked(True)
        layout.addWidget(self.is_active_checkbox)
        layout.addStretch(1)
        return tab

    # --- تبِ فروش/خرید و ردیابی ------------------------------------------
    def _build_sales_tracking_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        self.is_sellable_checkbox = QCheckBox("قابلِ‌فروش")
        self.is_sellable_checkbox.setChecked(True)
        layout.addWidget(self.is_sellable_checkbox)

        self.is_purchasable_checkbox = QCheckBox("قابلِ‌خرید")
        self.is_purchasable_checkbox.setChecked(True)
        layout.addWidget(self.is_purchasable_checkbox)

        self.is_stock_tracked_checkbox = QCheckBox("موجودی‌محور")
        self.is_stock_tracked_checkbox.setChecked(True)
        layout.addWidget(self.is_stock_tracked_checkbox)

        self.track_batch_checkbox = QCheckBox("ردیابیِ بچ")
        self.track_batch_row = self.track_batch_checkbox
        layout.addWidget(self.track_batch_checkbox)

        self.track_expiry_checkbox = QCheckBox("ردیابیِ انقضا")
        self.track_expiry_row = self.track_expiry_checkbox
        layout.addWidget(self.track_expiry_checkbox)

        self.track_serial_checkbox = QCheckBox("ردیابیِ سریال")
        self.track_serial_row = self.track_serial_checkbox
        layout.addWidget(self.track_serial_checkbox)

        layout.addStretch(1)
        return tab

    # --- الگویِ کمبو + دکمهٔ «+» --------------------------------------------
    def _make_combo_with_add_row(self, label_text: str, combo: QComboBox, quick_add) -> QWidget:
        row = QWidget()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(2)
        row_layout.addWidget(QLabel(label_text))
        combo_row = QHBoxLayout()
        combo_row.addWidget(combo, stretch=1)
        add_button = QPushButton("+")
        add_button.setFixedWidth(28)
        add_button.setToolTip(f"{label_text}ِ تازه")
        add_button.clicked.connect(quick_add)
        combo_row.addWidget(add_button)
        row_layout.addLayout(combo_row)
        return row

    def _quick_add_uom(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("واحدِ تازه")
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
        if dialog.exec() != QDialog.Accepted or not code_field.text().strip() or not name_field.text().strip():
            return
        try:
            new_id = catalog_service.create_uom(company_id, code_field.text().strip(), name_field.text().strip(), type_combo.currentData())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._reload_uoms(company_id)
        self.uom_combo.setCurrentIndex(max(0, self.uom_combo.findData(new_id)))

    def _quick_add_brand(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        new_id = self._quick_add_code_name_dialog("برندِ تازه", lambda code, name: catalog_service.create_brand(company_id, code, name))
        if new_id is None:
            return
        self._reload_brands(company_id)
        self.brand_combo.setCurrentIndex(max(0, self.brand_combo.findData(new_id)))

    def _quick_add_manufacturer(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        new_id = self._quick_add_code_name_dialog(
            "تولیدکنندهٔ تازه", lambda code, name: catalog_service.create_manufacturer(company_id, code, name)
        )
        if new_id is None:
            return
        self._reload_manufacturers(company_id)
        self.manufacturer_combo.setCurrentIndex(max(0, self.manufacturer_combo.findData(new_id)))

    def _quick_add_code_name_dialog(self, title: str, create_fn) -> int | None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
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
            return None
        code = code_field.text().strip()
        name = name_field.text().strip()
        if not code or not name:
            return None
        try:
            return create_fn(code, name)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return None

    def _reload_uoms(self, company_id: int) -> None:
        self.uom_combo.blockSignals(True)
        self.uom_combo.clear()
        for u in catalog_service.list_uoms(company_id, active_only=True):
            self.uom_combo.addItem(f"{u.code} — {u.name}", u.uom_id)
        self.uom_combo.blockSignals(False)

    def _reload_brands(self, company_id: int) -> None:
        self.brand_combo.blockSignals(True)
        self.brand_combo.clear()
        self.brand_combo.addItem("(بدونِ برند)", None)
        for b in catalog_service.list_brands(company_id, active_only=True):
            self.brand_combo.addItem(f"{b.code} — {b.name}", b.brand_id)
        self.brand_combo.blockSignals(False)

    def _reload_manufacturers(self, company_id: int) -> None:
        self.manufacturer_combo.blockSignals(True)
        self.manufacturer_combo.clear()
        self.manufacturer_combo.addItem("(بدونِ تولیدکننده)", None)
        for m in catalog_service.list_manufacturers(company_id, active_only=True):
            self.manufacturer_combo.addItem(f"{m.code} — {m.name}", m.manufacturer_id)
        self.manufacturer_combo.blockSignals(False)

    # --- نمایش/مخفی‌کردنِ بخش‌ها بر اساسِ نوعِ کالا و Feature Toggle ---------
    def _on_kind_changed(self) -> None:
        is_service = self.kind_combo.currentData() == "SERVICE"
        if is_service:
            self.is_stock_tracked_checkbox.setChecked(False)
        self.is_stock_tracked_checkbox.setEnabled(not is_service)
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        """طبقِ خواستهٔ ماژولاربودنِ فرم: بخش‌هایی که به کالایِ خدمت یا
        قابلیتِ غیرفعال مربوطند، به‌جایِ نمایشِ همیشگی، مخفی می‌شوند."""
        is_service = self.kind_combo.currentData() == "SERVICE"
        self.track_batch_row.setVisible(not is_service and "BATCH_TRACKING" in self._enabled_features)
        self.track_expiry_row.setVisible(not is_service and "EXPIRY_TRACKING" in self._enabled_features)
        self.track_serial_row.setVisible(not is_service and "SERIAL_TRACKING" in self._enabled_features)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        self._reset_form()
        company_id = self._company_id()
        if company_id is None:
            return
        self._rows = catalog_service.list_items(company_id)
        self._enabled_features = {f.feature_code for f in engine_service.list_features(company_id) if f.is_enabled}

        self._reload_uoms(company_id)
        self._reload_brands(company_id)
        self._reload_manufacturers(company_id)
        self._apply_visibility()

        self.table.setRowCount(len(self._rows))
        for row_index, it in enumerate(self._rows):
            values = [
                "بله" if it.is_active else "خیر",
                _LIFECYCLE_LABELS.get(it.lifecycle_status_code, it.lifecycle_status_code),
                it.base_uom_code,
                it.name or "",
                it.code,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, it.item_id)
                self.table.setItem(row_index, col_index, item)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        item_id = self.table.item(row, 0).data(Qt.UserRole)
        it = next((r for r in self._rows if r.item_id == item_id), None)
        if it is not None:
            self._load_into_form(it)

    def _load_into_form(self, it: catalog_service.ItemRow) -> None:
        self._editing_id = it.item_id
        self.form_title.setText(f"ویرایشِ کالا — {it.name or it.code}")
        self.status_label.setText("")
        self.code_field.setText(it.code)
        self.code_field.setEnabled(True)
        self.name_field.setText(it.name or "")
        self.kind_combo.setCurrentIndex(self.kind_combo.findData(it.item_kind_code))
        self.uom_combo.setCurrentIndex(max(0, self.uom_combo.findData(it.base_uom_id)))
        self.brand_combo.setCurrentIndex(max(0, self.brand_combo.findData(it.brand_id)))
        self.manufacturer_combo.setCurrentIndex(max(0, self.manufacturer_combo.findData(it.manufacturer_id)))
        self.costing_combo.setCurrentIndex(max(0, self.costing_combo.findData(it.costing_method_code)))
        self.lifecycle_row.setVisible(True)
        self.lifecycle_combo.setCurrentIndex(max(0, self.lifecycle_combo.findData(it.lifecycle_status_code)))
        self.is_sellable_checkbox.setChecked(it.is_sellable)
        self.is_purchasable_checkbox.setChecked(it.is_purchasable)
        self.is_stock_tracked_checkbox.setChecked(it.is_stock_tracked)
        self.track_batch_checkbox.setChecked(it.track_batch)
        self.track_expiry_checkbox.setChecked(it.track_expiry)
        self.track_serial_checkbox.setChecked(it.track_serial)
        self.notes_field.setPlainText(it.notes or "")
        self.is_active_checkbox.setChecked(it.is_active)
        self.delete_button.setVisible(True)
        self._apply_visibility()

    def _reset_form(self) -> None:
        self._editing_id = None
        self.form_title.setText("کالایِ جدید")
        self.status_label.setText("")
        self.code_field.clear()
        self.code_field.setEnabled(True)
        self.name_field.clear()
        self.kind_combo.setCurrentIndex(0)
        if self.uom_combo.count():
            self.uom_combo.setCurrentIndex(0)
        self.brand_combo.setCurrentIndex(0)
        self.manufacturer_combo.setCurrentIndex(0)
        self.costing_combo.setCurrentIndex(0)
        self.lifecycle_row.setVisible(False)
        self.is_sellable_checkbox.setChecked(True)
        self.is_purchasable_checkbox.setChecked(True)
        self.is_stock_tracked_checkbox.setChecked(True)
        self.track_batch_checkbox.setChecked(False)
        self.track_expiry_checkbox.setChecked(False)
        self.track_serial_checkbox.setChecked(False)
        self.notes_field.clear()
        self.is_active_checkbox.setChecked(True)
        self.delete_button.setVisible(False)
        self.table.clearSelection()
        self._apply_visibility()

    def _collect_fields(self) -> catalog_service.ItemFields | None:
        if self.uom_combo.currentData() is None:
            self.status_label.setText("ابتدا یک واحدِ اندازه‌گیری تعریف کنید.")
            return None
        return catalog_service.ItemFields(
            item_kind_code=self.kind_combo.currentData(),
            base_uom_id=self.uom_combo.currentData(),
            brand_id=self.brand_combo.currentData(),
            manufacturer_id=self.manufacturer_combo.currentData(),
            costing_method_code=self.costing_combo.currentData(),
            is_sellable=self.is_sellable_checkbox.isChecked(),
            is_purchasable=self.is_purchasable_checkbox.isChecked(),
            is_stock_tracked=self.is_stock_tracked_checkbox.isChecked(),
            track_serial=self.track_serial_checkbox.isChecked(),
            track_batch=self.track_batch_checkbox.isChecked(),
            track_expiry=self.track_expiry_checkbox.isChecked(),
            notes=self.notes_field.toPlainText().strip() or None,
        )

    def _save(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        name = self.name_field.text().strip()
        code = self.code_field.text().strip()
        if not code:
            self.status_label.setText("کد را وارد کنید.")
            return
        if not name:
            self.status_label.setText("نام را وارد کنید.")
            return
        fields = self._collect_fields()
        if fields is None:
            return

        try:
            if self._editing_id is not None:
                lifecycle_code = self.lifecycle_combo.currentData()
                catalog_service.update_item(
                    self._editing_id, company_id, code, name, self.is_active_checkbox.isChecked(), lifecycle_code, fields
                )
            else:
                catalog_service.create_item(company_id, code, name, fields)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return

        self.refresh()

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        confirm = QMessageBox.question(self, "حذفِ کالا", "این کالا حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        company_id = self._company_id()
        try:
            catalog_service.delete_item(self._editing_id, company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
