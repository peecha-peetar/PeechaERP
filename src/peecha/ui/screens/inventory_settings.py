"""تنظیمات ماژول انبار — واحد/برند/تولیدکننده، روش قیمت‌گذاری، نگاشت
حساب‌های حسابداری، و دلیل‌های ساختاریافتهٔ اصلاح/برگشت."""

from __future__ import annotations

import decimal

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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import decimals, numerals, session as app_session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_documents as documents_service
from peecha.services import inventory_engine as engine_service
from peecha.services import unit_conversion as uc
from peecha.ui.widgets import FieldGrid, FieldSpec, FormDrawer, LayoutEditMixin, set_widget_help

# طبقِ رفعِ باگِ واقعی («حسابِ مالياتِ خرید تفصیلی می‌خواهد ولی جایی
# برایِ انتخابش نیست»): این بُعدها یا از سرِسند (مرکزِ هزینه/پروژه)، یا
# از انبارِ سند (مرکزِ سود)، یا از خودِ ردیف/طرفِ‌حساب (کالا) به‌طورِ
# خودکار تامین می‌شوند -- پس نباید در فهرستِ «تفصیلیِ ثابت» بیایند؛ هر
# نوع‌بُعدِ دیگری که یک حسابِ نقش‌محور الزامی کند، باقی می‌ماند.
_AUTO_SUPPLIED_DIMENSION_CODES = (
    dimensions_service.COST_CENTER_CODE, dimensions_service.PROJECT_CODE,
    dimensions_service.PROFIT_CENTER_CODE, dimensions_service.INVENTORY_ITEM_CODE,
)

_UOM_TYPE_LABELS = {"COUNT": "شمارشی", "WEIGHT": "وزن", "VOLUME": "حجم", "LENGTH": "طول", "AREA": "مساحت", "TIME": "زمان"}
from peecha.services.costing.engine import NEGATIVE_POLICIES, NOT_YET_AVAILABLE  # noqa: E402
from peecha.services.costing.strategies import METHOD_LABELS as _COSTING_METHOD_LABELS  # noqa: E402


def _company_id() -> int | None:
    return app_session.current_company.company_id if app_session.current_company else None


class _UomDialog(QDialog):
    """فرم تعریف/ویرایش واحد اندازه‌گیری (R225): نام، کد، نماد، نوع، واحد پایه،
    ضریب تبدیل، تعداد اعشار، اعشار مجاز، وضعیت، توضیحات."""

    def __init__(self, parent: QWidget, rows: list, row=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ویرایش واحد" if row is not None else "واحد جدید")
        self.setMinimumWidth(420)
        self.name_field = QLineEdit(row.name if row else "")
        self.code_field = QLineEdit(row.code if row else "")
        self.symbol_field = QLineEdit((row.symbol or "") if row else "")
        self.type_combo = QComboBox()
        for code, label in uc.UOM_TYPE_LABELS.items():
            self.type_combo.addItem(label, code)
        self.base_combo = QComboBox()
        self.base_combo.addItem("(بدون واحد پایه — خودش مبناست)", None)
        for r in rows:
            if row is None or r.uom_id != row.uom_id:
                self.base_combo.addItem(f"{r.name} ({r.code})", r.uom_id)
        self.factor_field = QLineEdit(decimals.plain(row.conversion_factor) if row else "1")
        self.decimal_spin = QSpinBox()
        self.decimal_spin.setRange(0, 6)
        self.allow_decimal_checkbox = QCheckBox("اعشار مجاز است")
        self.active_checkbox = QCheckBox("فعال")
        self.active_checkbox.setChecked(row.is_active if row else True)
        self.description_field = QLineEdit((row.description or "") if row else "")
        if row is not None:
            self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(row.uom_type_code)))
            self.base_combo.setCurrentIndex(max(0, self.base_combo.findData(row.base_uom_id)))
            self.decimal_spin.setValue(row.decimal_places)
            self.allow_decimal_checkbox.setChecked(row.allow_decimal)
            self.code_field.setReadOnly(True)
        else:
            self.type_combo.currentIndexChanged.connect(self._sync_default_decimal_places)
            self._sync_default_decimal_places()
        self.allow_decimal_checkbox.toggled.connect(lambda on: self.decimal_spin.setEnabled(on))
        self.decimal_spin.setEnabled(self.allow_decimal_checkbox.isChecked())

        layout = QVBoxLayout(self)
        grid = FieldGrid([
            FieldSpec("name", "نام واحد", self.name_field, span=1),
            FieldSpec("code", "کد", self.code_field, span=1),
            FieldSpec("symbol", "نماد", self.symbol_field, span=1),
            FieldSpec("type", "نوع", self.type_combo, span=1),
            FieldSpec("base", "واحد پایه", self.base_combo, span=1),
            FieldSpec("factor", "ضریب تبدیل به واحد پایه", self.factor_field, span=1),
            FieldSpec("decimals", "تعداد اعشار", self.decimal_spin, span=1),
            FieldSpec("allow_decimal", "", self.allow_decimal_checkbox, span=1),
            FieldSpec("active", "", self.active_checkbox, span=1),
            FieldSpec("description", "توضیحات", self.description_field, span=3),
        ])
        layout.addWidget(grid)
        hint = QLabel("مثال: کیلوگرم ← واحد پایه «گرم»، ضریب ۱۰۰۰. واحد بسته‌بندی (کارتن/بسته) ضریب واقعی‌اش را در فرم هر کالا می‌گیرد.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _sync_default_decimal_places(self) -> None:
        whole = self.type_combo.currentData() in ("COUNT", "PACKAGING")
        self.allow_decimal_checkbox.setChecked(not whole)
        self.decimal_spin.setValue(0 if whole else (3 if self.type_combo.currentData() in ("WEIGHT", "VOLUME") else 2))

    def values(self) -> dict:
        try:
            factor = decimal.Decimal(numerals.to_ascii_digits(self.factor_field.text().strip() or "1"))
        except decimal.InvalidOperation as exc:
            raise ValueError("ضریب تبدیل باید عدد باشد.") from exc
        return dict(
            code=self.code_field.text().strip(), name=self.name_field.text().strip(),
            uom_type_code=self.type_combo.currentData(), decimal_places=self.decimal_spin.value(),
            symbol=self.symbol_field.text().strip() or None, base_uom_id=self.base_combo.currentData(),
            conversion_factor=factor, allow_decimal=self.allow_decimal_checkbox.isChecked(),
            description=self.description_field.text().strip() or None, is_active=self.active_checkbox.isChecked(),
        )


class _UomTab(QWidget):
    """مدیریت واحدهای اندازه‌گیری (R225): جست‌وجو، فیلتر نوع/وضعیت، افزودن،
    ویرایش، غیرفعال‌سازی. واحد استفاده‌شده هرگز حذف سخت نمی‌شود."""

    _COLUMNS = ["کد", "نام", "نماد", "نوع", "واحد پایه", "ضریب", "اعشار", "وضعیت", "سیستمی"]

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[catalog_service.UomRow] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)
        _title_label = QLabel("مدیریت واحدهای اندازه‌گیری")
        _title_label.setObjectName("pageTitle")
        layout.addWidget(_title_label)

        filter_row = QHBoxLayout()
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("جست‌وجو در کد/نام/نماد")
        self.search_field.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self.search_field, stretch=2)
        self.type_filter = QComboBox()
        self.type_filter.addItem("(همهٔ انواع)", None)
        for code, label in uc.UOM_TYPE_LABELS.items():
            self.type_filter.addItem(label, code)
        self.type_filter.currentIndexChanged.connect(self._apply_filter)
        filter_row.addWidget(self.type_filter, stretch=1)
        self.active_filter = QComboBox()
        self.active_filter.addItem("(فعال و غیرفعال)", None)
        self.active_filter.addItem("فقط فعال", True)
        self.active_filter.addItem("فقط غیرفعال", False)
        self.active_filter.currentIndexChanged.connect(self._apply_filter)
        filter_row.addWidget(self.active_filter, stretch=1)
        add_button = QPushButton("➕")
        add_button.setObjectName("primaryIconButton")
        add_button.setFixedWidth(48)
        add_button.setToolTip("واحد جدید")
        add_button.clicked.connect(self._add)
        filter_row.addWidget(add_button)
        layout.addLayout(filter_row)

        self.table = QTableWidget(0, len(self._COLUMNS))
        self.table.setHorizontalHeaderLabels(self._COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
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
        delete_button = QPushButton("🚫")
        delete_button.setObjectName("dangerIconButton")
        delete_button.setFixedWidth(44)
        delete_button.setToolTip("غیرفعال‌سازی/حذف (واحد استفاده‌شده فقط غیرفعال می‌شود)")
        delete_button.clicked.connect(self._delete_selected)
        buttons.addWidget(delete_button)
        layout.addWidget(button_cluster, alignment=Qt.AlignLeft)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        self._rows = catalog_service.list_uoms(company_id)
        self._apply_filter()

    def _visible_rows(self) -> list:
        needle = self.search_field.text().strip().lower()
        type_code = self.type_filter.currentData()
        active = self.active_filter.currentData()
        rows = []
        for r in self._rows:
            if needle and needle not in f"{r.code} {r.name} {r.symbol or ''}".lower():
                continue
            if type_code is not None and r.uom_type_code != type_code:
                continue
            if active is not None and r.is_active != active:
                continue
            rows.append(r)
        return rows

    def _apply_filter(self) -> None:
        names = {r.uom_id: r.name for r in self._rows}
        rows = self._visible_rows()
        self.table.setRowCount(len(rows))
        for row_index, u in enumerate(rows):
            values = [
                u.code, u.name, u.symbol or "", uc.UOM_TYPE_LABELS.get(u.uom_type_code, u.uom_type_code),
                names.get(u.base_uom_id, "") if u.base_uom_id else "",
                numerals.to_persian_digits(format(u.conversion_factor.normalize(), "f")) if u.base_uom_id else "",
                numerals.to_persian_digits(str(u.decimal_places)) if u.allow_decimal else "بدون اعشار",
                "فعال" if u.is_active else "غیرفعال", "بله" if u.is_global else "",
            ]
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
        dialog = _UomDialog(self, self._rows)
        if dialog.exec() != QDialog.Accepted:
            return
        company_id = _company_id()
        if company_id is None:
            return
        try:
            v = dialog.values()
            catalog_service.create_uom(
                company_id, v["code"], v["name"], v["uom_type_code"], v["decimal_places"], symbol=v["symbol"],
                base_uom_id=v["base_uom_id"], conversion_factor=v["conversion_factor"],
                allow_decimal=v["allow_decimal"], description=v["description"],
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _edit_selected(self, *_args) -> None:
        row = self._selected_row()
        if row is None:
            return
        if row.is_global:
            QMessageBox.information(self, "واحد سیستمی", "واحدهای سیستمی (استاندارد) قابل‌ویرایش نیستند؛ برای نیاز خاص، واحد اختصاصی بسازید.")
            return
        dialog = _UomDialog(self, self._rows, row)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            v = dialog.values()
            catalog_service.update_uom(
                row.uom_id, _company_id(), row.code, v["name"], v["uom_type_code"], v["is_active"], v["decimal_places"],
                symbol=v["symbol"], base_uom_id=v["base_uom_id"], conversion_factor=v["conversion_factor"],
                allow_decimal=v["allow_decimal"], description=v["description"],
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _delete_selected(self) -> None:
        row = self._selected_row()
        if row is None or row.is_global:
            return
        confirm = QMessageBox.question(
            self, "حذف/غیرفعال‌سازی",
            "این واحد حذف شود؟ (اگر در کالا/سند/فهرست قیمت استفاده شده باشد، فقط غیرفعال می‌شود.)",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            outcome = catalog_service.delete_uom(row.uom_id, _company_id())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.status_label.setText("واحد حذف شد." if outcome == "DELETED" else "این واحد در اسناد/کالاها استفاده شده بود و غیرفعال شد.")
        self.refresh()


class _BarcodeManagerTab(QWidget):
    """Barcode Manager (R225): جست‌وجوی مرکزی بارکد، نمایش کالا/واحد هر بارکد،
    و کنترل تکراری‌ها (شامل بارکدهای قدیمی پیش از سیستم واحد)."""

    _COLUMNS = ["بارکد", "نوع", "کالا", "واحد", "ضریب", "اصلی", "وضعیت"]

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)
        title = QLabel("مدیریت بارکد")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        row = QHBoxLayout()
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("بارکد را وارد/اسکن کنید")
        self.search_field.returnPressed.connect(self.refresh)
        row.addWidget(self.search_field, stretch=1)
        search_button = QPushButton("🔎")
        search_button.setObjectName("iconButton")
        search_button.setFixedWidth(44)
        search_button.clicked.connect(self.refresh)
        row.addWidget(search_button)
        layout.addLayout(row)
        self.resolve_label = QLabel("")
        self.resolve_label.setWordWrap(True)
        layout.addWidget(self.resolve_label)
        self.table = QTableWidget(0, len(self._COLUMNS))
        self.table.setHorizontalHeaderLabels(self._COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=2)
        layout.addWidget(QLabel("بارکدهای تکراری بین کالاها"))
        self.duplicates_table = QTableWidget(0, 2)
        self.duplicates_table.setHorizontalHeaderLabels(["بارکد", "کالاها"])
        self.duplicates_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.duplicates_table.verticalHeader().setVisible(False)
        self.duplicates_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.duplicates_table, stretch=1)

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        search = self.search_field.text().strip() or None
        rows = uc.list_barcodes(company_id, search=search)
        self.table.setRowCount(len(rows))
        for i, b in enumerate(rows):
            values = [
                b.barcode, uc.BARCODE_TYPE_LABELS.get(b.barcode_type, b.barcode_type), f"{b.item_code} — {b.item_name}",
                b.unit_name, numerals.to_persian_digits(format(b.factor.normalize(), "f")),
                "✓" if b.is_primary else "", "فعال" if b.is_active else "غیرفعال",
            ]
            for j, v in enumerate(values):
                self.table.setItem(i, j, QTableWidgetItem(v))
        if search:
            match = uc.resolve_barcode(company_id, search, with_price=False)
            self.resolve_label.setText(
                f"اسکن: {match.item_code} — {match.item_name} | واحد: {match.unit_name} | ضریب: "
                f"{numerals.to_persian_digits(format(match.factor.normalize(), 'f'))}" if match else "این بارکد به هیچ کالای فعالی وصل نیست."
            )
        else:
            self.resolve_label.setText("")
        items = {it.item_id: f"{it.code} — {it.name}" for it in catalog_service.list_items(company_id)}
        duplicates = uc.find_duplicate_barcodes(company_id)
        self.duplicates_table.setRowCount(len(duplicates))
        for i, (code, item_ids) in enumerate(duplicates):
            self.duplicates_table.setItem(i, 0, QTableWidgetItem(code))
            self.duplicates_table.setItem(i, 1, QTableWidgetItem("، ".join(items.get(x, str(x)) for x in item_ids)))


class _BrandManufacturerTab(QWidget):
    """هم‌الگو با _UomTab برای برند و تولیدکننده — چون هردو ساختاری
    مشابه دارند (کد/نام/فعال)، هر دو در همین تب کنار هم می‌آیند."""

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
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
        delete_button.setToolTip("حذف ردیف انتخاب‌شده")
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
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)
        _title_label = QLabel("تنظیمات قیمت‌گذاری شرکت")
        _title_label.setObjectName("pageTitle")
        layout.addWidget(_title_label)

        self.method_combo = QComboBox()
        for code, label in _COSTING_METHOD_LABELS.items():
            if code not in NOT_YET_AVAILABLE:
                self.method_combo.addItem(label, code)

        self.allow_override_checkbox = QCheckBox("اجازهٔ override در سطح کالا")
        self.allow_override_checkbox.setChecked(True)
        # R257: رفتارِ موجودیِ منفی
        self.negative_combo = QComboBox()
        for code, label in NEGATIVE_POLICIES.items():
            self.negative_combo.addItem(label, code)
        self.reason_field = QLineEdit()
        self.reason_field.setPlaceholderText("علت تغییر (برای سابقهٔ تغییرات)")

        self.costing_grid = FieldGrid([
            FieldSpec("method", "روش ارزش‌گذاری موجودی", self.method_combo, span=1),
            FieldSpec("allow_override", "", self.allow_override_checkbox, span=1),
            FieldSpec("negative", "رفتار موجودی منفی", self.negative_combo, span=2),
            FieldSpec("reason", "علت تغییر", self.reason_field, span=2),
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
        self._loaded_method = method_code or "WEIGHTED_AVERAGE"
        self.method_combo.setCurrentIndex(max(0, self.method_combo.findData(self._loaded_method)))
        self.allow_override_checkbox.setChecked(allow_override)
        self.negative_combo.setCurrentIndex(max(0, self.negative_combo.findData(engine_service.get_negative_stock_policy(company_id))))
        self.reason_field.clear()
        self.status_label.setText("")

    def _save(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        if self.method_combo.currentData() != getattr(self, "_loaded_method", None) and QMessageBox.question(
                self, "تغییر روش ارزش‌گذاری",
                "تغییر روش بر بهای تمام‌شدهٔ خروج‌های بعدی اثر می‌گذارد. برای موجودی فعلی کالاهایی که لایه ندارند، "
                "در نخستین خروج یک «لایهٔ آغازین» با میانگین فعلی ساخته می‌شود. ادامه می‌دهید؟",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        user = app_session.current_user
        try:
            engine_service.set_costing_settings(
                company_id, self.method_combo.currentData(), self.allow_override_checkbox.isChecked(),
                negative_stock_policy=self.negative_combo.currentData(), user_id=user.user_id if user else None,
                reason=self.reason_field.text().strip() or None)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setObjectName("statusSuccess")
        self.status_label.setText("ذخیره شد.")


class _AccountMappingsTab(LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._combos: dict[str, QComboBox] = {}
        # طبقِ رفعِ باگِ واقعی («حسابِ مالياتِ خرید تفصیلی می‌خواهد ولی
        # جایی برایِ انتخابش نیست»): کنارِ هر معینِ نقش‌محور، یک کمبویِ
        # «تفصیلیِ ثابت» -- فقط وقتی آن معین واقعاً یک بُعدِ تفصیلیِ
        # دیگر (غیر از مرکزِ هزینه/پروژه/مرکزِ سود/کالا که خودکار تامین
        # می‌شوند) را الزامی کرده باشد، فعال/پرشده نمایش داده می‌شود.
        self._detail_combos: dict[str, QComboBox] = {}
        self._detail_required: dict[str, bool] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)
        _title_label = QLabel("نگاشت حساب‌های حسابداری")
        _title_label.setObjectName("pageTitle")
        layout.addWidget(_title_label)
        layout.addWidget(QLabel("هر عملیات انبار به یک حساب (معین) نگاشت می‌شود؛ بدون نگاشت، ثبت سند خودکار متوقف می‌شود."))

        mapping_fields = []
        for key, label in engine_service.MAPPING_LABELS.items():
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            combo = QComboBox()
            combo.setMinimumWidth(220)
            row_layout.addWidget(combo, stretch=2)
            detail_combo = QComboBox()
            detail_combo.setMinimumWidth(160)
            detail_combo.setEnabled(False)
            row_layout.addWidget(detail_combo, stretch=1)
            combo.currentIndexChanged.connect(lambda _index, k=key: self._on_account_changed(k))
            self._combos[key] = combo
            self._detail_combos[key] = detail_combo
            set_widget_help(combo, f"حساب معینی که «{label}» در اسناد خودکار انبار به آن ثبت می‌شود.")
            set_widget_help(detail_combo, "اگر این حساب معین، تفصیلی الزامی دارد، تفصیلی ثابتی که همیشه همراه آن ثبت می‌شود.")
            mapping_fields.append(FieldSpec(key, label, row_widget, span=3))
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

    def _on_account_changed(self, key: str, preselect_detail_id: int | None = None) -> None:
        detail_combo = self._detail_combos[key]
        account_id = self._combos[key].currentData()
        company_id = _company_id()
        detail_combo.blockSignals(True)
        detail_combo.clear()
        if account_id is None or company_id is None:
            detail_combo.setEnabled(False)
            self._detail_required[key] = False
            detail_combo.blockSignals(False)
            return
        required = dimensions_service.get_required_dimensions_for_account(account_id)
        other_dims = [d for d in required if d.code not in _AUTO_SUPPLIED_DIMENSION_CODES]
        options = []
        for dim in other_dims:
            label_prefix = dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(dim.code, dim.code)
            for d in dim.detail_accounts:
                options.append((d.detail_account_id, f"{label_prefix}: {d.full_code} — {d.name or ''}"))
        # طبقِ رفعِ باگِ واقعی («فیلدِ تفصیلیِ حسابِ ماليات غیرفعاله در
        # صورتیکه معین به گروهِ مشتری/تامین‌کننده/پرسنل وصله»): محدودیتِ
        # گروهِ اشخاص (AccountPersonGroup) یک سامانه‌یِ کاملاً جدا از
        # AccountDetailDimension است -- قبلاً این‌جا اصلاً بررسی نمی‌شد.
        # فقط برایِ SUPPLIER_PAYABLE/CUSTOMER_RECEIVABLE این تفصیلی از
        # خودِ سند (طرفِ‌حساب) تامین می‌شود؛ برایِ هر نقشِ دیگری (مثلِ
        # مالیات) که به یکی از این گروه‌ها محدود شده باشد، یک تفصیلیِ
        # ثابت (یک شخصِ واحد، مثلاً «سازمانِ امورِ مالياتی» به‌عنوانِ
        # تامین‌کننده) لازم است.
        if key not in ("SUPPLIER_PAYABLE", "CUSTOMER_RECEIVABLE"):
            required_groups = dimensions_service.get_required_person_groups_for_account(account_id)
            if required_groups:
                group_ids = {g.person_group_id for g in required_groups}
                persons = [p for p in dimensions_service.list_active_persons(company_id) if p.person_group_id in group_ids]
                group_names = {g.person_group_id: g.name for g in required_groups}
                for p in persons:
                    prefix = group_names.get(p.person_group_id, "")
                    options.append((p.detail_account_id, f"{prefix}: {p.full_code} — {p.name or ''}"))
        self._detail_required[key] = bool(options)
        if not options:
            detail_combo.setEnabled(False)
            detail_combo.blockSignals(False)
            return
        detail_combo.addItem("(تعیین‌نشده — الزامی)", None)
        for detail_id, label in options:
            detail_combo.addItem(label, detail_id)
        if preselect_detail_id is not None:
            detail_combo.setCurrentIndex(max(0, detail_combo.findData(preselect_detail_id)))
        detail_combo.setEnabled(True)
        detail_combo.blockSignals(False)

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        accounts = [(a.account_id, f"{a.full_code} — {a.name}") for a in coa_service.list_accounts(company_id) if a.is_postable]
        current = engine_service.list_account_mappings(company_id)
        current_by_key = {c.mapping_key: (c.account_id, c.detail_account_id) for c in current}
        for key, combo in self._combos.items():
            account_id, detail_account_id = current_by_key.get(key, (None, None))
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("(تعیین‌نشده)", None)
            for acc_id, label in accounts:
                combo.addItem(label, acc_id)
            combo.setCurrentIndex(max(0, combo.findData(account_id)))
            combo.blockSignals(False)
            self._on_account_changed(key, preselect_detail_id=detail_account_id)
        self.status_label.setText("")

    def _save(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        for key, combo in self._combos.items():
            account_id = combo.currentData()
            if account_id is None:
                continue
            if self._detail_required.get(key) and self._detail_combos[key].currentData() is None:
                self.status_label.setObjectName("statusError")
                self.status_label.setText(f"حساب «{engine_service.MAPPING_LABELS[key]}» یک تفصیلی ثابت هم لازم دارد.")
                return
            engine_service.set_account_mapping(company_id, key, account_id, self._detail_combos[key].currentData())
        self.status_label.setObjectName("statusSuccess")
        self.status_label.setText("ذخیره شد.")


class _FeatureToggleTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._checkboxes: dict[str, QCheckBox] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)
        title = QLabel("قابلیت‌های فعال")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("فعال‌سازی هر قابلیت ممکن است به قابلیت دیگری وابسته باشد."))

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
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(16)
        layout.addWidget(self._build_section("دلیل‌های اصلاح", "ADJUSTMENT"), stretch=1)
        layout.addWidget(self._build_section("دلیل‌های برگشت از فروش", "RETURN_IN"), stretch=1)
        layout.addWidget(self._build_section("دلیل‌های برگشت به تامین‌کننده", "RETURN_OUT"), stretch=1)

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
        delete_button.setToolTip("حذف ردیف انتخاب‌شده")
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
        dialog.setWindowTitle("افزودن دلیل")
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
    """دسته‌بندی کالا (بخش ۱) + نگاشت حساب حسابداری در سطح دسته (بخش ۱۴،
    override روی نگاشت سراسری — فعلاً فقط تنظیم؛ اتصال به موتور ثبت در
    دور بعدی)."""

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[catalog_service.ItemCategoryRow] = []
        self._selected_category_id: int | None = None
        self._mapping_combos: dict[str, QComboBox] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(16)
        layout.addWidget(self._build_list_panel(), stretch=1)
        mapping_panel = self._build_mapping_panel()
        layout.addWidget(mapping_panel, stretch=1)
        # R275: نگاشتِ حسابِ دسته کنارِ فهرست فقط با کلیکِ یک دسته باز می‌شود
        self.form_drawer = FormDrawer(layout, mapping_panel, open_signals=[self.table.clicked])

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        title = QLabel("دسته‌بندی کالا")
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
        title = QLabel("نگاشت حساب این دسته (override)")
        title.setObjectName("pageTitle")
        panel_layout.addWidget(title)
        panel_layout.addWidget(QLabel("اگر دسته‌ای انتخاب نشده باشد یا برای کلیدی مقداری تعیین نشود، نگاشت سراسری شرکت استفاده می‌شود."))

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
            combo.addItem("(از نگاشت سراسری پیروی کند)", None)
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
        parent_combo.addItem("(بدون والد)", None)
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
        dialog.setWindowTitle("ویرایش دسته")
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
