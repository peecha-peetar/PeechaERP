"""R361: بسته‌بندی و کنترل ارسال — اسکن اقلام سند فروش در بسته‌ها، بستن با وزن و ابعاد، فهرست بسته‌بندی و ثبت ارسال."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services import inventory_locations as locations_service
from peecha.services import wms_packing as packing
from peecha.ui import report_export, theme
from peecha.ui.screens.fixed_assets import P, combo, company_id, dec, fill, selected_data, table, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec, build_page_header


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


def _qty(value) -> str:
    return P(numerals.format_amount(value.normalize())) if value is not None else ""


def _spin(maximum: float, decimals: int) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(0, maximum)
    box.setDecimals(decimals)
    return box


class WmsPackingScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.documents: list = []
        self.lines: list = []
        self.packages: list = []
        self._contents: list = []
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "بسته‌بندی و کنترل ارسال", "اقلام سند فروش را اسکن کنید تا در بسته بنشیند؛ کالای خارج از سند یا بیش از مقدار پذیرفته "
            "نمی‌شود. بسته را با وزن و ابعاد ببندید و ارسال را با روش حمل و کد رهگیری ثبت کنید."))
        top = QHBoxLayout()
        self.warehouse_combo = combo([], "همهٔ انبارها")
        self.warehouse_combo.currentIndexChanged.connect(lambda _i: self.load_documents())
        self.shipped_check = QCheckBox("ارسال‌شده‌ها هم دیده شوند")
        self.shipped_check.toggled.connect(lambda _c: self.load_documents())
        top.addWidget(FieldGrid([FieldSpec("pack_warehouse", "انبار", self.warehouse_combo, span=2)]), 1)
        top.addWidget(self.shipped_check)
        refresh = _btn("به‌روزرسانی", "🔄")
        refresh.clicked.connect(self.refresh)
        top.addWidget(refresh)
        layout.addLayout(top)

        split = QSplitter(Qt.Horizontal)
        self.doc_table = table(["نوع", "شماره", "تاریخ", "مشتری", "بسته", "بسته‌بندی‌شده", "وضعیت"])
        self.doc_table.itemSelectionChanged.connect(self.load_document)
        split.addWidget(self.doc_table)
        right = QWidget()
        rv = QVBoxLayout(right)
        scan_row = QHBoxLayout()
        self.scan_field = QLineEdit()
        self.scan_field.setPlaceholderText("بارکد یا کد کالا را اسکن کنید")
        self.scan_field.returnPressed.connect(self.scan)
        self.qty_field = _spin(1_000_000, 3)
        self.qty_field.setValue(1)
        scan_row.addWidget(FieldGrid([FieldSpec("pack_scan", "اسکن کالا", self.scan_field, span=3),
                                      FieldSpec("pack_qty", "تعداد", self.qty_field, span=1)]), 1)
        for label, glyph, kind, slot in (("گذاشتن در بسته", "📥", "primary", self.scan),
                                         ("بستهٔ جدید", "📦", "", self.new_package)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            scan_row.addWidget(button)
        rv.addLayout(scan_row)
        self.line_table = table(["کالا", "مقدار سند", "قابل بسته‌بندی", "بسته‌بندی‌شده", "مانده"])
        rv.addWidget(self.line_table, 1)
        rv.addWidget(QLabel("محتوای بسته‌ها"))
        self.content_table = table(["بسته", "کالا", "مقدار", "وزن (کیلوگرم)", "وضعیت"])
        rv.addWidget(self.content_table, 1)
        self.weight_field, self.length_field = _spin(100_000, 3), _spin(10_000, 1)
        self.width_field, self.height_field = _spin(10_000, 1), _spin(10_000, 1)
        close_row = QHBoxLayout()
        close_row.addWidget(FieldGrid([FieldSpec("pack_weight", "وزن (کیلوگرم)", self.weight_field, span=1),
                                       FieldSpec("pack_length", "طول", self.length_field, span=1),
                                       FieldSpec("pack_width", "عرض", self.width_field, span=1),
                                       FieldSpec("pack_height", "ارتفاع (سانتی‌متر)", self.height_field, span=1)]), 1)
        for label, glyph, kind, slot in (("بستن بستهٔ انتخاب‌شده (یا بستهٔ باز)", "✅", "primary", self.close_package),
                                         ("بازکردن دوبارهٔ بسته", "↩️", "", self.reopen_package),
                                         ("برداشتن ردیف انتخاب‌شده از بستهٔ باز", "🗑️", "danger", self.remove_line)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            close_row.addWidget(button)
        rv.addLayout(close_row)
        self.method_combo = combo([(label, code) for code, label in packing.SHIPPING_METHODS.items()])
        self.carrier_field, self.tracking_field = QLineEdit(), QLineEdit()
        self.cost_field = _spin(1e12, 0)
        self.partial_check = QCheckBox("ارسال ناقص")
        ship_row = QHBoxLayout()
        ship_row.addWidget(FieldGrid([FieldSpec("ship_method", "روش حمل", self.method_combo, span=1),
                                      FieldSpec("ship_carrier", "حمل‌کننده", self.carrier_field, span=1),
                                      FieldSpec("ship_tracking", "کد رهگیری", self.tracking_field, span=1),
                                      FieldSpec("ship_cost", "هزینهٔ حمل", self.cost_field, span=1),
                                      FieldSpec("ship_partial", "", self.partial_check, span=1)]), 1)
        for label, glyph, kind, slot in (("ثبت ارسال", "🚚", "primary", self.ship),
                                         ("چاپ فهرست بسته‌بندی", "🖨️", "", self.print_list),
                                         ("خروجی Excel فهرست بسته‌بندی", "📊", "", self.export_list)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            ship_row.addWidget(button)
        rv.addLayout(ship_row)
        split.addWidget(right)
        split.setSizes([520, 820])
        layout.addWidget(split, 1)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    # --- داده -------------------------------------------------------------------------------------------------
    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        current = self.warehouse_combo.currentData()
        self.warehouse_combo.blockSignals(True)
        self.warehouse_combo.clear()
        self.warehouse_combo.addItem("همهٔ انبارها", None)
        for w in locations_service.list_warehouses(cid, active_only=True):
            self.warehouse_combo.addItem(P(f"{w.code} — {w.name}"), w.warehouse_id)
        index = self.warehouse_combo.findData(current)
        self.warehouse_combo.setCurrentIndex(index if index >= 0 else 0)
        self.warehouse_combo.blockSignals(False)
        self.load_documents()

    def _document_id(self) -> int | None:
        return selected_data(self.doc_table)

    def load_documents(self, keep: int | None = None) -> None:
        keep = keep or self._document_id()
        self.documents = packing.packable_documents(company_id(), self.warehouse_combo.currentData(), self.shipped_check.isChecked())
        fill(self.doc_table, [[d.type_label, P(d.document_no), d.document_date, d.customer, P(d.packages),
                               f"{P(round(d.packed_percent))}٪", d.state_label] for d in self.documents],
             [d.document_id for d in self.documents])
        for i, d in enumerate(self.documents):
            if d.document_id == keep:
                self.doc_table.selectRow(i)
                break
        self.load_document()

    def load_document(self) -> None:
        document_id = self._document_id()
        if document_id is None:
            self.lines, self.packages, self._contents = [], [], []
            fill(self.line_table, [])
            fill(self.content_table, [])
            return
        self.lines = packing.pack_status(company_id(), document_id)
        fill(self.line_table, [[ln.item_label, _qty(ln.ordered), _qty(ln.packable), _qty(ln.packed), _qty(ln.remaining)]
                               for ln in self.lines], [ln.line_id for ln in self.lines])
        self.packages = packing.list_packages(company_id(), document_id)
        self._contents = [(p, ln) for p in self.packages for ln in p.lines]
        fill(self.content_table, [[P(p.package_no), ln.item_label, _qty(ln.quantity),
                                   _qty(p.weight_kg) if p.weight_kg is not None else "", p.status_label]
                                  for p, ln in self._contents], [ln.package_line_id for _p, ln in self._contents])

    def _after(self, message: str, ok: bool = True) -> None:
        theme.set_status_label(self.status_label, message, ok=ok)
        self.load_documents(self._document_id())

    def _need_document(self) -> int | None:
        document_id = self._document_id()
        if document_id is None:
            theme.set_status_label(self.status_label, "اول یک سند فروش را از فهرست انتخاب کنید.", ok=False)
        return document_id

    # --- کارها --------------------------------------------------------------------------------------------------
    def scan(self) -> bool:
        document_id = self._need_document()
        code = self.scan_field.text().strip()
        if document_id is None or not code:
            return False
        try:
            r = packing.pack(company_id(), document_id, user_id(), code, quantity=dec(str(self.qty_field.value())))
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            self.scan_field.selectAll()
            return False
        self.scan_field.clear()
        self.qty_field.setValue(1)
        self._after(f"در بستهٔ {P(r.package_no)} گذاشته شد؛ ماندهٔ این کالا {_qty(r.remaining)}.")
        return True

    def new_package(self) -> int | None:
        document_id = self._need_document()
        if document_id is None:
            return None
        package_id = packing.new_package(company_id(), document_id, user_id())
        self._after("بستهٔ جدید آماده است.")
        return package_id

    def _selected_package(self):
        line_id = selected_data(self.content_table)
        hit = next((p for p, ln in self._contents if ln.package_line_id == line_id), None)
        return hit or next((p for p in self.packages if p.status_code == "OPEN"), None)

    def close_package(self) -> bool:
        p = self._selected_package()
        if p is None:
            theme.set_status_label(self.status_label, "بستهٔ بازی نیست.", ok=False)
            return False
        dims = tuple(dec(str(f.value())) or None for f in (self.length_field, self.width_field, self.height_field))
        try:
            packing.close_package(company_id(), p.package_id, dec(str(self.weight_field.value())) or None,
                                  dims if any(dims) else None)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return False
        for f in (self.weight_field, self.length_field, self.width_field, self.height_field):
            f.setValue(0)
        self._after(f"بستهٔ {P(p.package_no)} بسته شد.")
        return True

    def reopen_package(self) -> bool:
        p = self._selected_package()
        if p is None:
            return False
        try:
            packing.reopen_package(company_id(), p.package_id)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return False
        self._after(f"بستهٔ {P(p.package_no)} دوباره باز شد.")
        return True

    def remove_line(self) -> bool:
        line_id = selected_data(self.content_table)
        if line_id is None:
            theme.set_status_label(self.status_label, "یک ردیف از محتوای بسته را انتخاب کنید.", ok=False)
            return False
        try:
            packing.remove_line(company_id(), line_id)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return False
        self._after("ردیف از بسته برداشته شد.")
        return True

    def ship(self) -> int | None:
        document_id = self._need_document()
        if document_id is None:
            return None
        partial = self.partial_check.isChecked()
        if partial and QMessageBox.question(self, "ارسال ناقص", "همهٔ اقلام بسته‌بندی نشده‌اند؛ همین بسته‌ها ارسال شوند؟") \
                != QMessageBox.Yes:
            return None
        try:
            shipment_id = packing.ship(company_id(), document_id, user_id(), self.method_combo.currentData(), self.carrier_field.text(),
                                       self.tracking_field.text(), dec(str(self.cost_field.value())), allow_partial=partial)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return None
        for f in (self.carrier_field, self.tracking_field):
            f.clear()
        self.cost_field.setValue(0)
        self.partial_check.setChecked(False)
        self._after("ارسال ثبت شد.")
        return shipment_id

    def _list(self):
        document_id = self._need_document()
        if document_id is None:
            return None
        doc = next((d for d in self.documents if d.document_id == document_id), None)
        headers, rows = packing.packing_list(company_id(), document_id)
        if not rows:
            theme.set_status_label(self.status_label, "هنوز چیزی بسته‌بندی نشده است.", ok=False)
            return None
        title = f"فهرست بسته‌بندی {doc.type_label} {P(doc.document_no)}" if doc else "فهرست بسته‌بندی"
        fmt = [[r[0], r[1], _qty(r[2]), _qty(r[3]) if r[3] not in ("", None) else "", r[4], r[5]] for r in rows]
        return title, headers, fmt, doc

    def print_list(self) -> bool:
        data = self._list()
        if data is None:
            return False
        title, headers, rows, doc = data
        report_export.print_report(self, title, headers, rows, filters=[("مشتری", doc.customer)] if doc else None)
        return True

    def export_list(self) -> bool:
        data = self._list()
        if data is None:
            return False
        title, headers, rows, doc = data
        report_export.export_report_excel(self, title, headers, rows, filters=[("مشتری", doc.customer)] if doc else None)
        return True

