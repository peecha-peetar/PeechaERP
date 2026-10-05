"""نقشهٔ تعاملیِ انبار و مدیریتِ محل‌ها -- R248.

موتورِ نقشه: QGraphicsView/QGraphicsScene خودِ Qt (۲بعدی، زوم، سطحِ جزئیات). مختصاتِ هر عنصر
(X/Y/عرض/ارتفاع/چرخش و Z برایِ نسخهٔ سه‌بعدیِ آینده) در inv.bin_locations ذخیره می‌شود.
همهٔ داده‌ها از services/warehouse_locations (موجودی از inv.stock_balance) می‌آید.
"""

from __future__ import annotations

import decimal

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QGraphicsItem,
    QGraphicsPathItem, QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView, QGridLayout,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget,
    QStyleOptionGraphicsItem, QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from peecha import numerals
from peecha import session as app_session
from peecha.services import inventory_locations as locations_service
from peecha.services import warehouse_locations as wl
from peecha.ui import theme
from peecha.ui.screens.warehouse_3d import Warehouse3DView

_Z = {"AREA": 0, "AISLE": 1, "RACK": 2, "SHELF": 2.5, "BIN": 3, None: 3}
_DETAIL_SCALE = 1.4  # زیرِ این زوم Bin/برچسب‌ها رسم نمی‌شوند (Level of Detail)
_MOVABLE = ("AREA", "AISLE", "RACK")


def _p(text) -> str:
    return numerals.to_persian_digits(str(text))


def _m(value) -> str:
    """متر بدونِ صفرهایِ اضافه (۱۰٫۵۰۰ → ۱۰٫۵)."""
    return _p(f"{float(value):g}") if value is not None else ""


def _dims(n) -> str:
    """«عرض × طول × ارتفاع متر» -- فقط ابعادِ واردشده."""
    parts = [(label, v) for label, v in (("عرض", n.width_m), ("طول", n.length_m), ("ارتفاع", n.height_m)) if v]
    return " × ".join(f"{label} {_m(v)}" for label, v in parts) + " متر" if parts else ""


def _dec(value: float | None) -> decimal.Decimal | None:
    return decimal.Decimal(str(round(value, 3))) if value not in (None, 0, 0.0) else None


class LocationItem(QGraphicsRectItem):
    """یک محل رویِ نقشه؛ در حالتِ ویرایش جابه‌جا/تغییرِ اندازه می‌شود و رها کردن، مختصات را ذخیره می‌کند."""

    def __init__(self, node, rect: tuple, screen: "WarehouseMapScreen") -> None:
        x, y, w, h, rot = rect
        super().__init__(0, 0, w, h)
        self.node, self.screen = node, screen
        self.setPos(x, y)
        self.setTransformOriginPoint(w / 2, h / 2)
        self.setRotation(rot)
        self.setZValue(_Z.get(node.level, 3))
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setToolTip(f"{node.full_code}\n{wl.LEVEL_LABELS.get(node.level, 'محل')} -- {wl.STATUSES.get(node.status_code, '')}")
        self.fill: QColor | None = None
        self.highlighted = False
        self.dimmed = False
        self.handle: QGraphicsRectItem | None = None
        self._press_state = None

    def set_editable(self, editable: bool) -> None:
        can_move = editable and self.node.level in _MOVABLE
        self.setFlag(QGraphicsItem.ItemIsMovable, can_move)
        if can_move and self.handle is None:
            self.handle = _ResizeHandle(self)
        if self.handle is not None:
            self.handle.setVisible(can_move)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget=None) -> None:  # noqa: N802
        lod = option.levelOfDetailFromTransform(painter.worldTransform())
        if self.node.level in ("BIN", "SHELF", None) and lod < _DETAIL_SCALE and not self.highlighted:
            return
        if self.node.level == "SHELF":
            return  # طبقه رویِ نقشهٔ افقی هم‌جایِ قفسه است؛ در نمایِ قفسه دیده می‌شود
        rect = self.rect()
        border = QColor(theme.BORDER)
        if self.node.level == "AREA":
            fill = QColor(self.fill or theme.SURFACE)
        elif self.node.level == "AISLE":
            fill = QColor(self.fill or theme.BACKGROUND)
        else:
            fill = QColor(self.fill or theme.ACCENT_LIGHT)
        if not self.node.is_active or self.node.status_code in ("BLOCKED", "INACTIVE", "MAINTENANCE"):
            fill = QColor(theme.TEXT_DISABLED)
            fill.setAlpha(90)
        if self.dimmed:
            fill.setAlpha(45)
        pen = QPen(border, 1)
        if self.node.level == "AISLE":
            pen.setStyle(Qt.DashLine)
        if self.node.is_damaged:
            pen = QPen(QColor(theme.DANGER), 1.5)
        if self.isSelected():
            pen = QPen(QColor(theme.ACCENT), 2.5)
        if self.highlighted:
            pen = QPen(QColor(theme.WARNING), 4)
        painter.setPen(pen)
        painter.setBrush(QBrush(fill))
        painter.drawRoundedRect(rect, 3, 3)
        if lod >= 0.6 or self.node.level == "AREA":
            painter.setPen(QColor(theme.TEXT_PRIMARY if self.node.level != "AREA" else theme.TEXT_SECONDARY))
            label = self.node.code.split("-")[-1]
            if self.node.level == "AREA" and self.node.name:
                label = f"{label}  {self.node.name}"
            if self.node.level in ("AREA", "AISLE", "RACK") and self.node.width_m and self.node.length_m and lod >= 0.4:
                dims = f"{_m(self.node.width_m)}×{_m(self.node.length_m)}م"
                label = f"{label}  ({dims})" if self.node.level == "AREA" else f"{label}\n{dims}"
            align = Qt.AlignTop | Qt.AlignHCenter if self.node.level == "AREA" else Qt.AlignCenter
            # R252: اندازهٔ نوشته متناسب با خودِ محل (در انبارِ کوچک نوشته‌ها از محل بیرون نمی‌زنند)
            lines = label.split("\n")
            longest = max(len(t) for t in lines)
            size = min(9.0 if self.node.level == "AREA" else 7.0,
                       rect.height() / (10 if self.node.level == "AREA" else len(lines) * 1.9), rect.width() / (longest * 0.75 + 1))
            if size < 1.2:
                return
            font = QFont(painter.font())
            font.setPointSizeF(size)
            font.setBold(self.node.level in ("AREA", "RACK"))
            painter.setFont(font)
            painter.drawText(rect.adjusted(1, 1, -1, -1), int(align), _p(label))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._press_state = (self.pos(), self.rect())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        if self._press_state and (self.pos(), self.rect()) != self._press_state:
            self.screen.item_geometry_changed(self)
        self._press_state = None
        self.screen.select_location(self.node.location_id, focus=False)


class _ResizeHandle(QGraphicsRectItem):
    def __init__(self, owner: LocationItem) -> None:
        super().__init__(-5, -5, 10, 10, owner)
        self.owner = owner
        self.setBrush(QBrush(QColor(theme.ACCENT)))
        self.setPen(QPen(Qt.NoPen))
        self.setCursor(Qt.SizeFDiagCursor)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setZValue(10)
        self.setPos(owner.rect().bottomRight())

    def itemChange(self, change, value):  # noqa: N802
        if change == QGraphicsItem.ItemPositionChange:
            point = QPointF(max(10.0, value.x()), max(10.0, value.y()))
            self.owner.prepareGeometryChange()
            self.owner.setRect(0, 0, point.x(), point.y())
            self.owner.setTransformOriginPoint(point.x() / 2, point.y() / 2)
            return point
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        self.owner.screen.item_geometry_changed(self.owner)


class _MapView(QGraphicsView):
    def __init__(self, scene) -> None:
        super().__init__(scene)
        self.setLayoutDirection(Qt.LeftToRight)  # مختصاتِ نقشه آینه نشود
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        # R256: انتخاب‌گرِ صریح -- سبکِ بی‌انتخاب‌گر به تولتیپِ فرزند هم می‌رسید و متنِ روشن رویِ زمینهٔ روشن ناخوانا می‌شد
        self.setStyleSheet(f"QGraphicsView {{ background: {theme.BACKGROUND}; border: 1px solid {theme.BORDER}; border-radius: 8px; }}")

    def wheelEvent(self, event) -> None:  # noqa: N802
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(factor, factor)
        if self.on_zoom is not None:
            self.on_zoom()

    on_zoom = None


class LocationDialog(QDialog):
    """ایجاد/ویرایشِ محل (منطقه، راهرو، قفسه، طبقه، Bin)."""

    def __init__(self, parent, level: str, fields: wl.LocationFields | None = None, creating: bool = True,
                 suggested_code: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{'محلِ تازه' if creating else 'ویرایشِ محل'} -- {wl.LEVEL_LABELS[level] if level in wl.LEVEL_LABELS else 'محل'}")
        f = fields or wl.LocationFields()
        grid = QGridLayout(self)
        self.segment = QLineEdit(suggested_code)
        self.segment.setEnabled(creating)
        self.name = QLineEdit(f.name or "")
        self.type_combo = QComboBox()
        self.type_combo.addItem("—", None)
        for code, label in wl.LOCATION_TYPES.items():
            self.type_combo.addItem(label, code)
        self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(f.location_type_code)))
        self.status_combo = QComboBox()
        for code, label in wl.STATUSES.items():
            self.status_combo.addItem(label, code)
        self.status_combo.setCurrentIndex(max(0, self.status_combo.findData(f.status_code)))
        self.description = QLineEdit(f.description or "")

        def spin(value, maximum=1e7, decimals=3):
            s = QDoubleSpinBox()
            s.setRange(0, maximum)
            s.setDecimals(decimals)
            s.setValue(float(value or 0))
            return s
        self.width_m, self.length_m, self.height_m = spin(f.width_m), spin(f.length_m), spin(f.height_m)
        self.max_weight, self.max_volume = spin(f.max_weight_kg), spin(f.max_volume_m3)
        self.temp_min, self.temp_max = QDoubleSpinBox(), QDoubleSpinBox()
        for s, v in ((self.temp_min, f.temperature_min_c), (self.temp_max, f.temperature_max_c)):
            s.setRange(-80, 80)
            s.setSpecialValueText("—")
            s.setMinimum(-80.01)
            s.setValue(float(v) if v is not None else -80.01)
        self.level_number = QSpinBox()
        self.level_number.setRange(0, 99)
        self.level_number.setValue(f.level_number or 0)
        self.direction = QComboBox()
        self.direction.addItem("—", None)
        for code, label in wl.DIRECTIONS.items():
            self.direction.addItem(label, code)
        self.direction.setCurrentIndex(max(0, self.direction.findData(f.direction)))
        self.pickable, self.putaway = QCheckBox("برداشت مجاز"), QCheckBox("جانمایی مجاز")
        self.replenish, self.damaged = QCheckBox("جایگزینی مجاز"), QCheckBox("آسیب‌دیده")
        self.pickable.setChecked(f.is_pickable)
        self.putaway.setChecked(f.allow_putaway)
        self.replenish.setChecked(f.allow_replenishment)
        self.damaged.setChecked(f.is_damaged)
        self.hazardous = QCheckBox("کالایِ خطرناک مجاز")
        self.hazardous.setChecked(f.allows_hazardous)
        self._fields = f
        rows = [("کدِ بخش", self.segment), ("نام", self.name), ("نوعِ محل", self.type_combo), ("وضعیت", self.status_combo),
                ("عرض (متر)", self.width_m), ("طول (متر)", self.length_m), ("ارتفاع (متر)", self.height_m),
                ("حداکثر وزن (کیلوگرم)", self.max_weight), ("حداکثر حجم (مترمکعب)", self.max_volume),
                ("حداقلِ دما", self.temp_min), ("حداکثرِ دما", self.temp_max)]
        if level == "BIN":
            self.width_m.setToolTip("طولی که Bin در امتدادِ قفسه می‌گیرد؛ خالی = سهمِ مساوی از باقی‌ماندهٔ طولِ قفسه")
            self.length_m.setToolTip("عمقِ Bin؛ خالی = عمقِ قفسه")
        if level == "SHELF":
            self.height_m.setToolTip("ارتفاعِ همین طبقه؛ خالی = سهمِ مساوی از باقی‌ماندهٔ ارتفاعِ قفسه")
            rows.append(("شمارهٔ طبقه", self.level_number))
        if level == "AISLE":
            rows.append(("جهت", self.direction))
        rows.append(("توضیح", self.description))
        for i, (label, widget) in enumerate(rows):
            grid.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            grid.addWidget(widget, i // 2, (i % 2) * 2 + 1)
        flags = QHBoxLayout()
        for w in (self.pickable, self.putaway, self.replenish, self.damaged, self.hazardous):
            flags.addWidget(w)
        grid.addLayout(flags, len(rows) // 2 + 1, 0, 1, 4)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        grid.addWidget(buttons, len(rows) // 2 + 2, 0, 1, 4)

    def result_fields(self) -> wl.LocationFields:
        f = self._fields
        temp = lambda s: decimal.Decimal(str(s.value())) if s.value() > -80 else None  # noqa: E731
        return wl.LocationFields(
            name=self.name.text().strip() or None, location_type_code=self.type_combo.currentData(),
            description=self.description.text().strip() or None, status_code=self.status_combo.currentData(),
            level_number=self.level_number.value() or f.level_number, direction=self.direction.currentData() or f.direction,
            width_m=_dec(self.width_m.value()), length_m=_dec(self.length_m.value()), height_m=_dec(self.height_m.value()),
            max_weight_kg=_dec(self.max_weight.value()), max_volume_m3=_dec(self.max_volume.value()),
            temperature_min_c=temp(self.temp_min), temperature_max_c=temp(self.temp_max), is_pickable=self.pickable.isChecked(),
            allow_putaway=self.putaway.isChecked(), allow_replenishment=self.replenish.isChecked(), is_damaged=self.damaged.isChecked(),
            allows_hazardous=self.hazardous.isChecked(), barcode=f.barcode, map_x=f.map_x, map_y=f.map_y, map_z=f.map_z, map_width=f.map_width, map_height=f.map_height,
            map_rotation=f.map_rotation)


def _table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setStretchLastSection(True)
    return t


class WarehouseMapScreen(QWidget):
    """نقشه + فیلتر + جزئیاتِ محل + درختِ محل‌ها."""

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.warehouse_id: int | None = None
        self.nodes, self.by_id, self.items = [], {}, {}
        self.selected_id: int | None = None
        self.search_item_ids: list[int] = []
        self.presence: dict = {}
        self._item_labels: dict[int, tuple[str, str]] = {}
        self.occ = {}
        self.path_item: QGraphicsPathItem | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        top = QHBoxLayout()
        title = QLabel("نقشه و محل‌هایِ انبار")
        title.setObjectName("pageTitle")
        top.addWidget(title)
        top.addSpacing(12)
        top.addWidget(QLabel("انبار:"))
        self.warehouse_combo = QComboBox()
        self.warehouse_combo.setMinimumWidth(180)
        self.warehouse_combo.currentIndexChanged.connect(lambda _i: self.load_warehouse(self.warehouse_combo.currentData()))
        top.addWidget(self.warehouse_combo)
        top.addWidget(QLabel("حالت:"))
        self.mode_combo = QComboBox()
        for code, label in wl.HEATMAP_MODES.items():
            self.mode_combo.addItem(label, code)
        self.mode_combo.currentIndexChanged.connect(lambda _i: self.apply_mode())
        top.addWidget(self.mode_combo)
        top.addStretch(1)
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("جستجو: کد/نام/بارکدِ کالا یا کد/QRِ محل")
        self.search_field.setMinimumWidth(280)
        self.search_field.returnPressed.connect(lambda: self.search(self.search_field.text()))
        top.addWidget(self.search_field)
        search_button = QPushButton("یافتن")
        search_button.setObjectName("primaryButton")
        search_button.clicked.connect(lambda: self.search(self.search_field.text()))
        top.addWidget(search_button)
        outer.addLayout(top)

        tools = QHBoxLayout()
        for text, slot in (("＋", lambda: self.zoom(1.25)), ("－", lambda: self.zoom(0.8)), ("کلِ نقشه", self.fit)):
            b = QPushButton(text)
            b.setObjectName("flatButton")
            b.clicked.connect(slot)
            tools.addWidget(b)
        self.edit_check = QCheckBox("حالتِ ویرایشِ نقشه")
        self.edit_check.toggled.connect(self.set_edit_mode)
        tools.addSpacing(12)
        tools.addWidget(self.edit_check)
        self.add_buttons = {}
        for level in wl.LEVELS:
            b = QPushButton(f"＋ {wl.LEVEL_LABELS[level].split(' ')[0]}")
            b.setObjectName("flatButton")
            b.clicked.connect(lambda _c=False, lv=level: self.add_location(lv))
            tools.addWidget(b)
            self.add_buttons[level] = b
        tools.addStretch(1)
        self.view3d_check = QCheckBox("نمایِ سه‌بعدی")
        self.view3d_check.toggled.connect(self.set_3d)
        tools.addWidget(self.view3d_check)
        for text, slot in (("مسیرِ برداشت", self.show_picking_path), ("چاپِ برچسب", self.print_labels),
                           ("ابعادِ انبار", self.edit_warehouse_dimensions)):
            b = QPushButton(text)
            b.setObjectName("flatButton")
            b.clicked.connect(slot)
            tools.addWidget(b)
        outer.addLayout(tools)

        splitter = QSplitter(Qt.Horizontal)
        self.scene = QGraphicsScene(self)
        self.scene.setItemIndexMethod(QGraphicsScene.BspTreeIndex)  # رندرِ فقط ناحیهٔ دیدنی برایِ انبارهایِ بزرگ
        self.view = _MapView(self.scene)
        self.view.on_zoom = self.update_lod
        side = QTabWidget()
        side.setMinimumWidth(400)
        side.setMaximumWidth(560)
        # --- جزئیات
        details = QWidget()
        dl = QVBoxLayout(details)
        self.detail_title = QLabel("محلی انتخاب نشده است")
        self.detail_title.setObjectName("cardTitle")
        self.detail_info = QLabel("")
        self.detail_info.setWordWrap(True)
        self.detail_info.setTextFormat(Qt.RichText)
        dl.addWidget(self.detail_title)
        dl.addWidget(self.detail_info)
        ops = QGridLayout()
        self.op_buttons = {}
        for code, text in (("EDIT", "ویرایش"), ("STATUS", "وضعیت"), ("TRANSFER", "انتقال"), ("PUTAWAY", "پیشنهادِ جانمایی"),
                           ("REPLENISH", "حداقل/حداکثرِ تأمین"), ("COUNT", "شمارشِ محل"), ("TASKS", "وظایفِ انبار"),
                           ("DEFAULT", "مکانِ پیش‌فرض"), ("DELETE", "حذف")):
            b = QPushButton(text)
            b.setObjectName("flatButton")
            # R255: دو ستون و ارتفاعِ کافی تا متنِ دکمه‌ها در پنلِ باریک بریده/پنهان نشود
            b.setMinimumHeight(34)
            b.setToolTip(text)
            b.clicked.connect(lambda _c=False, op=code: self.run_operation(op))
            ops.addWidget(b, len(self.op_buttons) // 2, len(self.op_buttons) % 2)
            self.op_buttons[code] = b
        dl.addLayout(ops)
        rot = QHBoxLayout()
        rot.addWidget(QLabel("چرخش:"))
        self.rotation_spin = QSpinBox()
        self.rotation_spin.setRange(0, 359)
        self.rotation_spin.setSuffix("°")
        self.rotation_spin.editingFinished.connect(self.apply_rotation)
        rot.addWidget(self.rotation_spin)
        rot.addStretch(1)
        dl.addLayout(rot)
        self.rack_title = QLabel("نمایِ قفسه (طبقه × محل)")
        self.rack_title.setObjectName("cardTitle")
        dl.addWidget(self.rack_title)
        self.rack_info = QLabel("")
        self.rack_info.setWordWrap(True)
        self.rack_info.setTextFormat(Qt.RichText)
        dl.addWidget(self.rack_info)
        self.elevation_table = QTableWidget(0, 0)
        self.elevation_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.elevation_table.cellClicked.connect(self._elevation_clicked)
        self.elevation_table.setMinimumHeight(200)
        self.elevation_table.verticalHeader().setDefaultSectionSize(44)
        self.elevation_table.horizontalHeader().setDefaultSectionSize(76)
        dl.addWidget(self.elevation_table)
        dl.addWidget(QLabel("محتویات"))
        self.contents_table = _table(["محل", "کالا", "مقدار", "واحد", "بچ", "سریال", "انقضا"])
        self.contents_table.setMinimumHeight(200)
        dl.addWidget(self.contents_table, stretch=1)
        details_scroll = QScrollArea()  # R255: پنلِ جزئیات اسکرول می‌خورد تا هیچ بخشی فشرده/پنهان نشود
        details_scroll.setWidgetResizable(True)
        details_scroll.setFrameShape(QScrollArea.NoFrame)
        details_scroll.setWidget(details)
        side.addTab(details_scroll, "جزئیات")
        # --- درخت
        tree_tab = QWidget()
        tl = QVBoxLayout(tree_tab)
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(["محل", "نوع", "وضعیت", "اشغال"])
        self.tree_widget.itemClicked.connect(lambda item, _c: self.select_location(item.data(0, Qt.UserRole)))
        tl.addWidget(self.tree_widget)
        side.addTab(tree_tab, "درختِ محل‌ها")
        # --- تاریخچه
        self.history_table = _table(["زمان", "رویداد", "شرح", "کالا", "مقدار"])
        side.addTab(self.history_table, "تاریخچه")
        self.side_tabs = side
        self.view3d = Warehouse3DView()
        self.view3d.location_clicked.connect(lambda lid: self.select_location(lid, focus=False))
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.view)
        self.view_stack.addWidget(self.view3d)
        splitter.addWidget(self.view_stack)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([900, 400])
        outer.addWidget(splitter, stretch=1)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("منطقه:"))
        self.zone_filter = QComboBox()
        self.zone_filter.currentIndexChanged.connect(lambda _i: self.apply_filters())
        filters.addWidget(self.zone_filter)
        filters.addWidget(QLabel("وضعیت:"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("— همه —", None)
        for code, label in wl.STATUSES.items():
            self.status_filter.addItem(label, code)
        self.status_filter.currentIndexChanged.connect(lambda _i: self.apply_filters())
        filters.addWidget(self.status_filter)
        filters.addWidget(QLabel("حداقلِ اشغال:"))
        self.occupancy_filter = QSpinBox()
        self.occupancy_filter.setRange(0, 100)
        self.occupancy_filter.setSuffix("٪")
        self.occupancy_filter.valueChanged.connect(lambda _v: self.apply_filters())
        filters.addWidget(self.occupancy_filter)
        self.show_inactive_check = QCheckBox("نمایشِ محل‌هایِ غیرفعال")
        self.show_inactive_check.toggled.connect(lambda _c: self.load_warehouse(self.warehouse_id))
        filters.addWidget(self.show_inactive_check)
        filters.addStretch(1)
        self.status_label = QLabel("")
        filters.addWidget(self.status_label)
        self.legend = QLabel("")
        self.legend.setObjectName("sectionHint")
        filters.addWidget(self.legend)
        outer.addLayout(filters)

    # ------------------------------------------------------------------
    def _company_id(self):
        return app_session.current_company.company_id if app_session.current_company else None

    def _user_id(self):
        return app_session.current_user.user_id if app_session.current_user else None

    def allowed(self, action: str) -> bool:
        user = app_session.current_user
        if user is None or self._company_id() is None:
            return False
        return bool(getattr(user, "is_super_admin", False)) or wl.can(user.user_id, self._company_id(), action)

    def _warn(self, text: str) -> None:
        QMessageBox.warning(self, "نقشهٔ انبار", text)

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        can_view = self.allowed("VIEW")
        self.view.setEnabled(can_view)
        if not can_view:
            self.status_label.setText("دسترسیِ مشاهدهٔ نقشهٔ انبار ندارید.")
            return
        for level, b in self.add_buttons.items():
            b.setEnabled(self.allowed("CREATE"))
        self.edit_check.setEnabled(self.allowed("EDIT"))
        current = self.warehouse_combo.currentData()
        self.warehouse_combo.blockSignals(True)
        self.warehouse_combo.clear()
        for w in locations_service.list_warehouses(company_id, active_only=True):
            self.warehouse_combo.addItem(f"{w.code} — {w.name}", w.warehouse_id)
        self.warehouse_combo.setCurrentIndex(max(0, self.warehouse_combo.findData(current)))
        self.warehouse_combo.blockSignals(False)
        self.load_warehouse(self.warehouse_combo.currentData())

    def load_warehouse(self, warehouse_id: int | None) -> None:
        company_id = self._company_id()
        self.scene.clear()
        self.items, self.path_item = {}, None
        self.warehouse_id = warehouse_id
        if warehouse_id is None or company_id is None:
            return
        if self.warehouse_combo.currentData() != warehouse_id:
            self.warehouse_combo.blockSignals(True)
            self.warehouse_combo.setCurrentIndex(max(0, self.warehouse_combo.findData(warehouse_id)))
            self.warehouse_combo.blockSignals(False)
        self.nodes = wl.tree(company_id, warehouse_id)
        self.by_id = {n.location_id: n for n in self.nodes}
        self.occ = wl.occupancy(company_id, warehouse_id, self.nodes)
        geo = wl.geometry(company_id, warehouse_id, self.nodes)
        wh = locations_service.get_warehouse(warehouse_id, company_id)
        if wh and wh.fields.width_m and wh.fields.length_m:  # مرزِ انبار (۱ متر = ۲۰ واحدِ نقشه)
            outline = self.scene.addRect(0, 0, float(wh.fields.width_m) * 20, float(wh.fields.length_m) * 20,
                                         QPen(QColor(theme.TEXT_SECONDARY), 2, Qt.DashLine))
            outline.setZValue(-1)
            dims = self.scene.addSimpleText(_p(f"{_m(wh.fields.width_m)} × {_m(wh.fields.length_m)} متر"))
            dims.setBrush(QColor(theme.TEXT_SECONDARY))
            dim_font = QFont(dims.font())
            dim_font.setPointSizeF(max(2.0, min(10.0, float(min(wh.fields.width_m, wh.fields.length_m)) * 20 * 0.06)))
            dims.setFont(dim_font)
            dims.setPos(0, -dims.boundingRect().height() - 2)
            dims.setZValue(-1)
        show_inactive = self.show_inactive_check.isChecked()
        for n in self.nodes:
            # R252: طبقه هم‌جایِ قفسه است و لایهٔ نامرئیِ رویِ آن کلیک‌ها را می‌دزدید؛ در «نمایِ قفسه»/درخت انتخاب می‌شود
            if n.location_id in geo and n.level != "SHELF" and (show_inactive or n.is_active):
                item = LocationItem(n, geo[n.location_id], self)
                self.scene.addItem(item)
                self.items[n.location_id] = item
        self.presence = wl.item_presence(company_id, warehouse_id, self.search_item_ids, self.nodes) if self.search_item_ids else {}
        self._apply_tooltips()
        self.set_edit_mode(self.edit_check.isChecked())
        self._fill_tree()
        self._fill_zone_filter()
        self.apply_mode()
        self.fit()
        unplaced = [n for n in self.nodes if n.location_id not in geo and n.level is not None]
        self.status_label.setText(_p(f"{len(self.items)} محل رویِ نقشه") + (f" -- {_p(len(unplaced))} بی‌مختصات" if unplaced else ""))

    def _fill_tree(self) -> None:
        self.tree_widget.clear()
        widgets = {}
        for n in sorted(self.nodes, key=lambda n: n.full_code):
            o = self.occ.get(n.location_id)
            w = QTreeWidgetItem([_p(n.full_code), wl.LEVEL_LABELS.get(n.level, "محلِ قدیمی"), wl.STATUSES.get(n.status_code, ""),
                                 f"{_p(o.percent)}٪" if o and o.percent is not None else ""])
            w.setData(0, Qt.UserRole, n.location_id)
            widgets[n.location_id] = w
        for n in self.nodes:
            parent = widgets.get(n.parent_id)
            (parent.addChild if parent else self.tree_widget.addTopLevelItem)(widgets[n.location_id])
        self.tree_widget.expandToDepth(1)

    def _fill_zone_filter(self) -> None:
        self.zone_filter.blockSignals(True)
        self.zone_filter.clear()
        self.zone_filter.addItem("— همه —", None)
        for n in self.nodes:
            if n.level == "AREA":
                self.zone_filter.addItem(_p(f"{n.code} {n.name or ''}"), n.location_id)
        self.zone_filter.blockSignals(False)

    # --- زوم و ویرایش -----------------------------------------------------
    def zoom(self, factor: float) -> None:
        self.view.scale(factor, factor)
        self.update_lod()

    def fit(self) -> None:
        rect = self.scene.itemsBoundingRect()
        if not rect.isEmpty():
            self.view.fitInView(rect.adjusted(-20, -20, 20, 20), Qt.KeepAspectRatio)
        self.update_lod()

    def update_lod(self) -> None:
        """Binها فقط وقتی دیده و کلیک می‌شوند که زوم کافی است (وگرنه کلیکِ قفسه را می‌گرفتند)."""
        lod = self.view.transform().m11()
        for item in self.items.values():
            if item.node.level in ("BIN", None):
                item.setVisible(lod >= _DETAIL_SCALE or item.highlighted or item.node.location_id == self.selected_id)

    def set_edit_mode(self, editable: bool) -> None:
        editable = editable and self.allowed("EDIT")
        for item in self.items.values():
            item.set_editable(editable)
        self.view.setDragMode(QGraphicsView.RubberBandDrag if editable else QGraphicsView.ScrollHandDrag)

    def item_geometry_changed(self, item: LocationItem) -> None:
        if not self.allowed("EDIT"):
            return
        rect, pos = item.rect(), item.pos()
        try:
            wl.save_geometry(self._company_id(), item.node.location_id, pos.x(), pos.y(), rect.width(), rect.height(),
                             item.rotation(), self._user_id())
        except ValueError as exc:
            self._warn(str(exc))
            return
        theme.set_status_label(self.status_label, f"مختصاتِ «{_p(item.node.full_code)}» ذخیره شد.", ok=True)
        node = item.node
        node.map_x, node.map_y = decimal.Decimal(str(round(pos.x(), 2))), decimal.Decimal(str(round(pos.y(), 2)))
        node.map_width, node.map_height = decimal.Decimal(str(round(rect.width(), 2))), decimal.Decimal(str(round(rect.height(), 2)))

    def apply_rotation(self) -> None:
        item = self.items.get(self.selected_id)
        if item is None or item.node.level not in _MOVABLE or not self.allowed("EDIT"):
            return
        item.setRotation(self.rotation_spin.value())
        self.item_geometry_changed(item)

    # --- حالت‌ها و فیلتر ---------------------------------------------------
    def apply_mode(self) -> None:
        mode = self.mode_combo.currentData() or "NORMAL"
        values = {} if mode == "NORMAL" else wl.heatmap(self._company_id(), self.warehouse_id, mode, self.nodes)
        numeric = [float(v) for v in values.values() if isinstance(v, (int, float, decimal.Decimal))]
        top = max(numeric) if numeric else 0
        for lid, item in self.items.items():
            # منطقه/راهرو زمینه‌اند؛ رنگِ حالت فقط رویِ قفسه و محل (وگرنه همه‌چیز را می‌پوشاند)
            fill = None if item.node.level in ("AREA", "AISLE") else self.color_for(mode, values.get(lid), top)
            if fill is not None and mode == "OCCUPANCY" and not values.get(lid):
                fill.setAlpha(60)
            item.fill = fill
            item.update()
        legends = {
            "OCCUPANCY": "سبز < ۵۰٪ ‹ زرد < ۷۵٪ ‹ نارنجی < ۹۰٪ ‹ قرمز", "ABC": "قرمز=A، نارنجی=B، فیروزه‌ای=C",
            "EXPIRY": "قرمز=منقضی، نارنجی < ۳۰ روز، زرد < ۹۰ روز", "TEMPERATURE": "آبی ≤ ۸°، قرمز ≥ ۲۵°",
        }
        self.legend.setText(legends.get(mode, "پررنگ‌تر = بیشتر" if mode != "NORMAL" else ""))
        self.apply_filters()

    @staticmethod
    def color_for(mode: str, value, top: float) -> QColor | None:
        if value is None or mode == "NORMAL":
            return None
        if mode == "OCCUPANCY":
            v = float(value)
            return QColor(theme.SUCCESS if v < 50 else "#E9C46A" if v < 75 else theme.CHART_ORANGE if v < 90 else theme.DANGER)
        if mode == "ABC":
            return QColor({"A": theme.DANGER, "B": theme.CHART_ORANGE, "C": theme.CHART_TEAL}.get(value, theme.SURFACE))
        if mode == "EXPIRY":
            v = int(value)
            return QColor(theme.DANGER if v < 0 else theme.CHART_ORANGE if v < 30 else "#E9C46A" if v < 90 else theme.SUCCESS)
        if mode == "TEMPERATURE":
            v = float(value)
            return QColor("#4C8DF6" if v <= 8 else theme.DANGER if v >= 25 else theme.SUCCESS)
        color = QColor(theme.ACCENT)
        color.setAlpha(int(40 + 215 * (float(value) / top)) if top else 40)
        return color

    def apply_filters(self) -> None:
        zone = self.zone_filter.currentData()
        status = self.status_filter.currentData()
        min_occ = self.occupancy_filter.value()
        zone_set = wl.descendants(self.nodes, zone) if zone else None
        for lid, item in self.items.items():
            o = self.occ.get(lid)
            visible_match = (zone_set is None or lid in zone_set) and (status is None or item.node.status_code == status) \
                and (min_occ == 0 or (o is not None and o.percent is not None and o.percent >= min_occ))
            item.dimmed = not visible_match
            item.update()
        self.refresh_3d()

    # --- نمایِ سه‌بعدی (R249) ----------------------------------------------
    def set_3d(self, on: bool) -> None:
        self.view_stack.setCurrentWidget(self.view3d if on else self.view)
        self.refresh_3d()

    def refresh_3d(self) -> None:
        if not self.view3d_check.isChecked() or self.warehouse_id is None:
            return
        boxes = wl.scene_3d(self._company_id(), self.warehouse_id, self.nodes)
        colors = {lid: item.fill for lid, item in self.items.items() if item.fill is not None}
        self.view3d.set_data(boxes, colors, highlighted=[lid for lid, i in self.items.items() if i.highlighted],
                             dimmed=[lid for lid, i in self.items.items() if i.dimmed],
                             info={b.location_id: self._hover_text(b.location_id) for b in boxes},
                             names={b.location_id: self._short_name(b.location_id) for b in boxes})

    def _short_name(self, location_id: int) -> str:
        n = self.by_id.get(location_id)
        if n is None:
            return ""
        seg = n.code.split("-")[-1]
        return _p(f"{seg} {n.name}" if n.name and n.level in ("AREA", "AISLE") else seg)

    def _apply_tooltips(self) -> None:
        for lid, item in self.items.items():
            item.setToolTip(self._hover_text(lid))

    def _presence_html(self, location_id: int) -> list[str]:
        """R256: مقدار، سریال‌ها و بچ‌هایِ کالایِ جستجوشده در همین محل (با زیرمحل‌ها)."""
        if not self.search_item_ids:
            return []
        names = "، ".join(f"{c} {n}" for c, n in (self._item_labels.get(i, ("", "", ""))[:2] for i in self.search_item_ids))
        p = self.presence.get(location_id)
        if p is None or not (p.quantity or p.serials):
            return [f"<hr><b>{_p(names)}</b>: در این محل موجودی ندارد"]
        unit = self._item_labels.get(self.search_item_ids[0], ("", "", ""))[2] if len(self.search_item_ids) == 1 else ""
        lines = ["<hr>" + _p(f"<b>{names}</b>"),
                 _p(f"مقدار در این محل: <b>{numerals.format_money(p.quantity, 2, None)}</b> {unit}")]
        if p.serials:
            shown = p.serials[:30]
            more = len(p.serials) - len(shown)
            lines.append(_p(f"سریال‌ها ({len(p.serials)}): ") + "، ".join(shown) + (_p(f" و {more} سریالِ دیگر") if more else ""))
        if p.batches:
            lines.append("بچ‌ها: " + _p("، ".join(
                f"{lt.batch_no} ({numerals.format_money(lt.quantity, 2, None)}"
                + (f"، انقضا {numerals.format_jalali_date(lt.expiry_date)}" if lt.expiry_date else "") + ")"
                for lt in p.batches[:10])))
        return lines

    def _hover_text(self, location_id: int) -> str:
        """R255: متنِ نمایش با ماوس (نقشه، سه‌بعدی، نمایِ قفسه): کد/نام، نوع، ابعاد، اشغال و کالا؛
        R256: + مقدار/سریال/بچِ کالایِ جستجوشده در همان محل."""
        n = self.by_id.get(location_id)
        if n is None:
            return ""
        o = self.occ.get(location_id)
        lines = ["<b>" + _p(n.full_code) + "</b>" + (f" -- {n.name}" if n.name else ""),
                 f"{wl.LEVEL_LABELS.get(n.level, 'محلِ قدیمی')} | {wl.STATUSES.get(n.status_code, '')}"]
        if _dims(n):
            lines.append(_dims(n))
        if n.level == "RACK":
            shelves = [k for k in self.nodes if k.parent_id == location_id and k.level == "SHELF"]
            lines.append(_p(f"{len(shelves)} طبقه، {sum(1 for k in self.nodes if k.parent_id in {s.location_id for s in shelves})} محل"))
        if o and o.quantity:
            lines.append(_p(f"کالا: {len(o.items)} | مقدار: {numerals.format_money(o.quantity, 2, None)}")
                         + (f" | اشغال: {_p(o.percent)}٪" if o.percent is not None else ""))
        lines += self._presence_html(location_id)
        return "<div dir='rtl'>" + "<br>".join(lines) + "</div>"

    # --- انتخاب، جستجو و جزئیات ----------------------------------------------
    def select_location(self, location_id: int | None, focus: bool = True) -> None:
        if location_id is None or location_id not in self.by_id:
            return
        self.selected_id = location_id
        node = self.by_id[location_id]
        item = self.items.get(location_id)
        if item is not None:
            self.scene.clearSelection()
            item.setSelected(True)
            if focus:
                self.view.fitInView(item.sceneBoundingRect().adjusted(-80, -80, 80, 80), Qt.KeepAspectRatio)
                self.view.centerOn(item)
            self.rotation_spin.blockSignals(True)
            self.rotation_spin.setValue(int(item.rotation()))
            self.rotation_spin.blockSignals(False)
        o = self.occ.get(location_id)
        chain = wl.ancestors(self.by_id, location_id)
        path = " ← ".join(_p(c.code.split("-")[-1]) for c in chain)
        cap = lambda v, unit: f"{_p(numerals.format_money(v, 2, None))} {unit}" if v is not None else "—"  # noqa: E731
        info = [f"<b>{_p(node.full_code)}</b> -- {wl.LEVEL_LABELS.get(node.level, 'محلِ قدیمی')}",
                f"مسیر: {path}", f"نوع: {wl.LOCATION_TYPES.get(node.location_type_code, '—')} | وضعیت: {wl.STATUSES.get(node.status_code)}"]
        if _dims(node):
            info.append(f"ابعاد: {_dims(node)}")
        if o:
            info.append(f"وزن: {cap(o.weight, 'kg')} از {cap(o.max_weight, 'kg')} | حجم: {cap(o.volume, 'm³')} از {cap(o.max_volume, 'm³')}")
            info.append(f"اشغال: <b>{_p(o.percent) + '٪' if o.percent is not None else 'ظرفیت تعریف نشده'}</b> | "
                        f"تعدادِ کالا: {_p(len(o.items))} | مقدار: {_p(numerals.format_money(o.quantity, 2, None))}")
            if o.percent is not None and o.percent > 100:
                info.append(f"<span style='color:{theme.DANGER}'>⚠ اشغال بیش از ظرفیت است.</span>")
        flags = [t for t, ok in (("برداشت", node.is_pickable), ("جانمایی", node.allow_putaway),
                                 ("جایگزینی", node.allow_replenishment)) if ok]
        info.append("مجاز: " + ("، ".join(flags) or "—") + (" | آسیب‌دیده" if node.is_damaged else ""))
        from peecha.services import inventory_locations as locations_service

        if locations_service.get_explicit_default_bin_id(self.warehouse_id) == location_id:
            info.append("<b>مکانِ پیش‌فرضِ انبار</b> (ردیف‌هایِ بی‌مکانِ رسید/حواله این‌جا ثبت می‌شوند)")
        info += self._presence_html(location_id)
        self.detail_title.setText(_p(node.full_code))
        self.detail_info.setText("<br>".join(info))
        self._fill_contents(location_id)
        self._fill_elevation(node)
        self._fill_history(location_id)
        for code, button in self.op_buttons.items():
            needed = {"EDIT": "EDIT", "STATUS": "EDIT", "TRANSFER": "EDIT", "DELETE": "DELETE"}.get(code, "VIEW")
            button.setEnabled(self.allowed(needed))

    def _fill_contents(self, location_id: int) -> None:
        rows = wl.contents(self._company_id(), location_id)
        self._contents = rows
        self.contents_table.setRowCount(len(rows))
        for r, c in enumerate(rows):
            cells = [c.location_code, f"{c.item_code} — {c.item_name or ''}", numerals.format_money(c.quantity, 2, None), c.unit,
                     c.batches, c.serials, numerals.format_jalali_date(c.expiry) if c.expiry else ""]
            for col, text in enumerate(cells):
                self.contents_table.setItem(r, col, QTableWidgetItem(_p(text)))

    def _fill_elevation(self, node) -> None:
        rack = node
        while rack is not None and rack.level not in ("RACK",):
            rack = self.by_id.get(rack.parent_id)
        self.elevation_table.clear()
        self._elevation = {}
        if rack is None:
            self.rack_title.setText("نمایِ قفسه (طبقه × محل)")
            self.rack_info.setText("برایِ دیدنِ طبقه‌ها و محل‌ها، یک قفسه، طبقه یا Bin را انتخاب کنید.")
            self.elevation_table.setRowCount(0)
            self.elevation_table.setColumnCount(0)
            return
        shelves = sorted([n for n in self.nodes if n.parent_id == rack.location_id and n.level == "SHELF"],
                         key=lambda n: -(n.level_number or 0))
        bins = {s.location_id: sorted([n for n in self.nodes if n.parent_id == s.location_id], key=lambda n: n.code) for s in shelves}
        cols = max([len(b) for b in bins.values()] + [1])
        # R255: اطلاعاتِ خودِ قفسه (ابعاد، تعدادِ طبقه/محل، اشغال، کالا) بالایِ نمایِ قفسه
        ro = self.occ.get(rack.location_id)
        n_bins = sum(len(b) for b in bins.values())
        lines = [f"ابعاد: {_dims(rack) or 'تعریف نشده'}",
                 f"طبقه: {_p(len(shelves))} | محل (Bin): {_p(n_bins)} | وضعیت: {wl.STATUSES.get(rack.status_code, '')}"]
        if ro:
            lines.append(f"اشغال: <b>{_p(ro.percent) + '٪' if ro.percent is not None else 'ظرفیت تعریف نشده'}</b> | "
                         f"تعدادِ کالا: {_p(len(ro.items))} | مقدار: {_p(numerals.format_money(ro.quantity, 2, None))}")
        self.rack_title.setText(_p(f"قفسهٔ {rack.full_code}" + (f" -- {rack.name}" if rack.name else "")))
        self.rack_info.setText("<br>".join(lines))
        self.elevation_table.setRowCount(len(shelves))
        self.elevation_table.setColumnCount(cols)
        self.elevation_table.setVerticalHeaderLabels(
            [_p(s.code.split("-")[-1]) + (f" ({_m(s.height_m)} م)" if s.height_m else "") for s in shelves])
        for r, s in enumerate(shelves):
            for c, b in enumerate(bins[s.location_id]):
                o = self.occ.get(b.location_id)
                cell = QTableWidgetItem(_p(b.code.split("-")[-1]) + (f"\n{_p(o.percent)}٪" if o and o.percent is not None else ""))
                cell.setToolTip(self._hover_text(b.location_id))
                fill = self.color_for("OCCUPANCY", o.percent, 100) if o and o.percent is not None else None
                if fill is not None:
                    fill.setAlpha(120)
                    cell.setBackground(fill)
                if b.location_id == node.location_id:
                    cell.setBackground(QColor(theme.ACCENT_LIGHT))
                self.elevation_table.setItem(r, c, cell)
                self._elevation[(r, c)] = b.location_id

    def _elevation_clicked(self, row: int, col: int) -> None:
        lid = self._elevation.get((row, col))
        if lid:
            self.select_location(lid)

    def _fill_history(self, location_id: int) -> None:
        rows = wl.history(self._company_id(), location_id, 100)
        self.history_table.setRowCount(len(rows))
        for r, h in enumerate(rows):
            cells = [numerals.format_jalali_datetime(h.at) if h.at else "", h.kind, h.detail, h.item,
                     numerals.format_money(h.quantity, 2, None) if h.quantity is not None else ""]
            for col, text in enumerate(cells):
                self.history_table.setItem(r, col, QTableWidgetItem(_p(text)))

    def highlight(self, location_ids: list[int]) -> None:
        for lid, item in self.items.items():
            item.highlighted = lid in location_ids
            item.update()
        self.update_lod()
        if self.view3d_check.isChecked():
            self.refresh_3d()
        targets = [self.items[i] for i in location_ids if i in self.items]
        on_map = [i for i in location_ids if i in self.items]
        if on_map:
            location_ids = on_map + [i for i in location_ids if i not in self.items]
        if targets:
            rect = targets[0].sceneBoundingRect()
            for t in targets[1:]:
                rect = rect.united(t.sceneBoundingRect())
            self.view.fitInView(rect.adjusted(-60, -60, 60, 60), Qt.KeepAspectRatio)
            self.select_location(location_ids[0], focus=False)

    def search(self, text: str) -> list[int]:
        """کالا/محل/QR → انبارِ محل انتخاب، محل‌ها هایلایت و روی نقشه زوم می‌شود."""
        try:
            result = wl.search(self._company_id(), text)
        except ValueError as exc:
            self._warn(str(exc))
            return []
        self.search_item_ids = list(result.item_ids) if result.kind in ("PRODUCT", "SERIAL") else []
        if self.search_item_ids:
            from peecha.services import inventory_catalog as catalog_service

            self._item_labels = {i.item_id: (i.code, i.name or "", i.base_uom_code or "")
                                 for i in catalog_service.list_items(self._company_id()) if i.item_id in self.search_item_ids}
        if not result.location_ids:
            self.presence = {}
            self._apply_tooltips()
            theme.set_status_label(self.status_label, "چیزی پیدا نشد.", ok=False)
            return []
        from peecha.db.base import new_session
        from peecha.db.models.inventory import BinLocation
        from sqlalchemy import select

        with new_session() as session:
            whs = dict(session.execute(select(BinLocation.bin_location_id, BinLocation.warehouse_id)
                                       .where(BinLocation.bin_location_id.in_(result.location_ids))).all())
        in_current = [lid for lid in result.location_ids if whs.get(lid) == self.warehouse_id]
        if not in_current:
            self.load_warehouse(whs[result.location_ids[0]])
            in_current = [lid for lid in result.location_ids if whs.get(lid) == self.warehouse_id]
        else:
            self.presence = wl.item_presence(self._company_id(), self.warehouse_id, self.search_item_ids, self.nodes) \
                if self.search_item_ids else {}
            self._apply_tooltips()
        self.highlight(in_current)
        others = len(result.location_ids) - len(in_current)
        theme.set_status_label(self.status_label, _p(f"{len(in_current)} محل یافت شد" + (f" (+{others} در انبارهایِ دیگر)" if others else "")),
                               ok=True)
        return in_current

    def focus_item(self, item_id: int) -> list[int]:
        from peecha.services import inventory_catalog as catalog_service

        item = next((i for i in catalog_service.list_items(self._company_id()) if i.item_id == item_id), None)
        return self.search(item.code) if item else []

    def focus_location(self, location_id: int) -> None:
        from peecha.db.base import new_session
        from peecha.db.models.inventory import BinLocation

        with new_session() as session:
            row = session.get(BinLocation, location_id)
            warehouse_id = row.warehouse_id if row else None
        if warehouse_id != self.warehouse_id:
            self.load_warehouse(warehouse_id)
        self.highlight([location_id])

    # --- عملیات --------------------------------------------------------------
    def add_location(self, level: str, segment: str | None = None, fields: wl.LocationFields | None = None) -> int | None:
        """محلِ تازه زیرِ محلِ انتخاب‌شده (برایِ منطقه زیرِ خودِ انبار)."""
        if not self.allowed("CREATE") or self.warehouse_id is None:
            return None
        parent = self.by_id.get(self.selected_id) if level != "AREA" else None
        siblings = [n for n in self.nodes if n.parent_id == (parent.location_id if parent else None) and n.level == level]
        suggested = f"{wl.LEVEL_PREFIX[level]}{len(siblings) + 1:02d}"
        if segment is None:
            dialog = LocationDialog(self, level, suggested_code=suggested)
            if dialog.exec() != QDialog.Accepted:
                return None
            segment, fields = dialog.segment.text(), dialog.result_fields()
        try:
            location_id = wl.create_location(self._company_id(), self.warehouse_id, level, segment,
                                             parent.location_id if parent else None, fields, self._user_id())
        except ValueError as exc:
            self._warn(str(exc))
            return None
        self.load_warehouse(self.warehouse_id)
        self.select_location(location_id, focus=False)
        return location_id

    def run_operation(self, op: str) -> None:
        node = self.by_id.get(self.selected_id)
        if node is None:
            return
        company_id, user_id = self._company_id(), self._user_id()
        try:
            if op == "EDIT":
                dialog = LocationDialog(self, node.level or "BIN", wl.get_fields(company_id, node.location_id), creating=False,
                                        suggested_code=node.code)
                if dialog.exec() == QDialog.Accepted:
                    wl.update_location(company_id, node.location_id, dialog.result_fields(), user_id)
            elif op == "STATUS":
                labels = list(wl.STATUSES.values())
                choice, ok = QInputDialog.getItem(self, "وضعیتِ محل", "وضعیت:", labels, labels.index(wl.STATUSES[node.status_code]), False)
                if ok:
                    wl.set_status(company_id, node.location_id, list(wl.STATUSES)[labels.index(choice)], user_id)
            elif op == "DELETE":
                children = len(wl.descendants(self.nodes, node.location_id)) - 1
                note = f" همراهِ {_p(children)} زیرمحل" if children else ""
                if QMessageBox.question(self, "حذف", f"محلِ «{_p(node.full_code)}»{note} حذف شود؟\n"
                                        "اگر هر کدام موجودی یا سابقه داشته باشد، به‌جایِ حذف غیرفعال و از نقشه پنهان می‌شوند.") \
                        == QMessageBox.Yes:
                    result = wl.delete_location(company_id, node.location_id, user_id)
                    theme.set_status_label(self.status_label, "حذف شد." if result == "DELETED" else "سابقه داشت؛ غیرفعال شد.", ok=True)
            elif op == "TRANSFER":
                self._transfer_dialog(node)
            elif op == "PUTAWAY":
                self._putaway_dialog()
            elif op == "REPLENISH":
                self._replenishment_dialog(node)
            elif op == "COUNT":
                from peecha.services import location_counts as lc

                sid = lc.create_location_count(company_id, self.warehouse_id, [node.location_id], user_id)
                theme.set_status_label(self.status_label, _p(f"شمارشِ محل شروع شد (جلسهٔ {sid})؛ ادامه در «وظایفِ انبار» یا موبایل."), ok=True)
            elif op == "DEFAULT":
                from peecha.services import inventory_locations as locations_service

                current = locations_service.get_explicit_default_bin_id(self.warehouse_id)
                new = None if current == node.location_id else node.location_id
                locations_service.set_default_bin_location(company_id, self.warehouse_id, new, user_id)
                theme.set_status_label(self.status_label, _p(f"مکانِ پیش‌فرضِ انبار: {node.full_code}") if new
                                       else "مکانِ پیش‌فرض برداشته شد (مکانِ عمومی).", ok=True)
            elif op == "TASKS":
                if self._main_window is not None:
                    self._main_window.open_screen("INV_WMS_TASKS")
                return
        except ValueError as exc:
            self._warn(str(exc))
            return
        self.load_warehouse(self.warehouse_id)
        if node.location_id in self.by_id:
            self.select_location(node.location_id, focus=False)

    def _replenishment_dialog(self, node) -> None:
        """R249: حداقل/حداکثرِ یک کالا در این محلِ برداشت."""
        from peecha.services import inventory_catalog as catalog_service
        from peecha.services import warehouse_operations as ops

        items = catalog_service.list_items(self._company_id(), transactable_only=True)
        labels = [_p(f"{i.code} — {i.name or ''}") for i in items]
        if not labels:
            raise ValueError("کالایی تعریف نشده است.")
        choice, ok = QInputDialog.getItem(self, "تأمینِ مجدد", "کالا:", labels, 0, True)
        if not ok or choice not in labels:
            return
        low, ok = QInputDialog.getDouble(self, "تأمینِ مجدد", "حداقل در این محل:", 0, 0, 1e9, 3)
        if not ok:
            return
        high, ok = QInputDialog.getDouble(self, "تأمینِ مجدد", "حداکثر (تا این مقدار پر می‌شود):", low + 1, 0, 1e9, 3)
        if not ok:
            return
        ops.save_rule(self._company_id(), ops.RuleFields(node.location_id, items[labels.index(choice)].item_id,
                                                          decimal.Decimal(str(low)), decimal.Decimal(str(high))))
        theme.set_status_label(self.status_label, "قاعدهٔ تأمینِ مجدد ذخیره شد.", ok=True)

    def _transfer_dialog(self, node) -> None:
        rows = [c for c in getattr(self, "_contents", []) if c.location_id == node.location_id] or getattr(self, "_contents", [])
        if not rows:
            raise ValueError("این محل کالایی ندارد.")
        labels = [_p(f"{c.item_code} — {c.item_name} ({numerals.format_money(c.quantity, 2, None)}) @ {c.location_code}") for c in rows]
        choice, ok = QInputDialog.getItem(self, "انتقال", "کالا:", labels, 0, False)
        if not ok:
            return
        content = rows[labels.index(choice)]
        targets = [n for n in self.nodes if wl.is_operable(n) and n.allow_putaway and n.location_id != content.location_id
                   and not any(m.parent_id == n.location_id for m in self.nodes)]
        target_labels = [_p(n.full_code) for n in targets]
        target, ok = QInputDialog.getItem(self, "انتقال", "محلِ مقصد:", target_labels, 0, False)
        if not ok:
            return
        qty, ok = QInputDialog.getDouble(self, "انتقال", "مقدار:", float(content.quantity), 0.001, float(content.quantity), 3)
        if not ok:
            return
        doc_id = wl.transfer(self._company_id(), self._user_id(), content.item_id, content.location_id,
                             targets[target_labels.index(target)].location_id, decimal.Decimal(str(qty)))
        theme.set_status_label(self.status_label, _p(f"سندِ انتقالِ {doc_id} ثبت شد."), ok=True)

    def _putaway_dialog(self) -> None:
        from peecha.services import inventory_catalog as catalog_service

        items = catalog_service.list_items(self._company_id(), transactable_only=True)
        labels = [_p(f"{i.code} — {i.name or ''}") for i in items]
        choice, ok = QInputDialog.getItem(self, "پیشنهادِ جانمایی", "کالا:", labels, 0, True)
        if not ok or choice not in labels:
            return
        qty, ok = QInputDialog.getDouble(self, "پیشنهادِ جانمایی", "مقدار:", 1, 0.001, 1e9, 3)
        if not ok:
            return
        suggestions = wl.putaway_suggestions(self._company_id(), self.warehouse_id, items[labels.index(choice)].item_id,
                                             decimal.Decimal(str(qty)))
        if not suggestions:
            raise ValueError("محلِ مناسبی (فعال، مجاز و با ظرفیتِ کافی) پیدا نشد.")
        self.highlight([s.location_id for s in suggestions[:1]])
        text = "\n\n".join(f"{i + 1}) {_p(s.location_code)} -- امتیاز {_p(s.score)}\n   " + "، ".join(s.reasons)
                           for i, s in enumerate(suggestions))
        QMessageBox.information(self, "پیشنهادِ جانمایی", f"کلاسِ ABC کالا: {suggestions[0].abc_class}\n\n{text}")

    def show_picking_path(self, location_ids: list[int] | None = None):
        """مسیرِ برداشت: وظایفِ برداشتِ بازِ همین انبار (یا محل‌هایِ داده‌شده) به ترتیبِ نزدیک‌ترین همسایه."""
        from peecha.services import warehouse_operations as ops

        if location_ids is None:
            location_ids = [t.from_bin_location_id for t in ops.list_tasks(self._company_id(), "PICK", warehouse_id=self.warehouse_id)
                            if t.status_code in ("OPEN", "IN_PROGRESS") and t.from_bin_location_id]
        if self.path_item is not None:
            self.scene.removeItem(self.path_item)
            self.path_item = None
        if not location_ids:
            theme.set_status_label(self.status_label, "برداشتِ بازی برایِ مسیریابی نیست.", ok=False)
            return None
        route = wl.picking_path(self._company_id(), self.warehouse_id, location_ids)
        points = [self.items[i].sceneBoundingRect().center() for i in ([route.start] if route.start in self.items else []) + route.order
                  + ([route.end] if route.end in self.items else []) if i in self.items]
        path = QPainterPath(points[0])
        for p in points[1:]:
            path.lineTo(p)
        self.path_item = QGraphicsPathItem(path)
        self.path_item.setPen(QPen(QColor(theme.DANGER), 3, Qt.DashLine))
        self.path_item.setZValue(20)
        self.scene.addItem(self.path_item)
        for i, lid in enumerate(route.order):
            marker = QGraphicsSimpleTextItem(_p(i + 1), self.path_item)
            marker.setBrush(QBrush(QColor(theme.DANGER)))
            marker.setPos(self.items[lid].sceneBoundingRect().center() + QPointF(4, -14))
        theme.set_status_label(self.status_label, _p(f"مسیر: {' ← '.join(c.split('-', 1)[-1] for c in route.codes)} -- طول {route.distance}"),
                               ok=True)
        return route

    def print_labels(self, location_ids: list[int] | None = None, printer=None) -> bool:
        from peecha.ui.location_labels import print_location_labels

        if not self.allowed("PRINT"):
            self._warn("دسترسیِ چاپِ برچسب ندارید.")
            return False
        if location_ids is None:
            if self.selected_id is None:
                self._warn("ابتدا یک محل (یا منطقه/قفسه برایِ چاپِ گروهی) را انتخاب کنید.")
                return False
            location_ids = sorted(wl.descendants(self.nodes, self.selected_id), key=lambda i: self.by_id[i].full_code)
        labels = [(i, self.by_id[i].full_code, self.by_id[i].name or wl.LEVEL_LABELS.get(self.by_id[i].level, "")) for i in location_ids]
        return print_location_labels(self, labels, printer)

    def edit_warehouse_dimensions(self) -> None:
        if not self.allowed("EDIT") or self.warehouse_id is None:
            return
        wh = locations_service.get_warehouse(self.warehouse_id, self._company_id())
        values = []
        for label, current in (("عرض (متر)", wh.fields.width_m), ("طول (متر)", wh.fields.length_m), ("ارتفاع (متر)", wh.fields.height_m),
                               ("حداکثرِ وزن (کیلوگرم)", wh.fields.capacity_weight_kg)):
            v, ok = QInputDialog.getDouble(self, "ابعادِ انبار", label, float(current or 0), 0, 1e9, 2)
            if not ok:
                return
            values.append(_dec(v))
        wl.save_warehouse_dimensions(self._company_id(), self.warehouse_id, *values, description=wh.fields.description)
        self.load_warehouse(self.warehouse_id)


class _PickerMap(WarehouseMapScreen):
    """نقشهٔ فقط‌انتخاب (بدونِ ویرایش) برایِ تعیینِ مکان در تاییدِ رسید."""

    def __init__(self, on_select) -> None:
        super().__init__(None)
        self._on_select = on_select
        self.edit_check.setVisible(False)
        for b in self.add_buttons.values():
            b.setVisible(False)
        self.warehouse_combo.setEnabled(False)
        self.side_tabs.setCurrentIndex(1)

    def select_location(self, location_id: int | None, focus: bool = True) -> None:
        super().select_location(location_id, focus)
        if getattr(self, "_on_select", None) is not None:
            self._on_select(location_id)


class LocationPickerDialog(QDialog):
    """R254: انتخابِ مکانِ ردیف رویِ نقشه؛ فقط محلِ برگِ فعال (Bin/طبقهٔ بی‌زیرمحل) پذیرفته می‌شود."""

    def __init__(self, parent, warehouse_id: int, current_id: int | None = None, item_id: int | None = None,
                 quantity: decimal.Decimal | None = None, title: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(f"انتخابِ مکان رویِ نقشه{' -- ' + title if title else ''}")
        self.resize(1200, 760)
        self.selected_location_id: int | None = None
        layout = QVBoxLayout(self)
        self.map = _PickerMap(self._picked)
        layout.addWidget(self.map, stretch=1)
        bottom = QHBoxLayout()
        self.choice_label = QLabel("رویِ یک Bin یا طبقه کلیک کنید (از نقشه، درختِ محل‌ها یا نمایِ قفسه).")
        bottom.addWidget(self.choice_label, stretch=1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("انتخابِ این مکان")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        bottom.addWidget(self.buttons)
        layout.addLayout(bottom)
        self.map.refresh()
        self.map.load_warehouse(warehouse_id)
        suggested = []
        if item_id is not None and quantity:
            try:
                suggested = [s.location_id for s in wl.putaway_suggestions(self.map._company_id(), warehouse_id, item_id, quantity)]
            except ValueError:
                suggested = []
        if suggested:
            self.map.highlight(suggested[:3])
        if current_id is not None and current_id in self.map.by_id:
            self.map.select_location(current_id, focus=True)
        elif suggested:
            self.choice_label.setText(_p("پیشنهادِ جانمایی: " + "، ".join(self.map.by_id[i].full_code for i in suggested[:3]
                                                                         if i in self.map.by_id)))

    def _picked(self, location_id: int | None) -> None:
        node = self.map.by_id.get(location_id)
        has_children = node is not None and any(n.parent_id == location_id for n in self.map.nodes)
        ok = node is not None and node.is_active and not has_children
        self.selected_location_id = location_id if ok else None
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)
        if node is None:
            return
        if ok:
            self.choice_label.setText(_p(f"مکانِ انتخابی: {node.full_code}"))
        elif has_children:
            self.choice_label.setText(_p(f"«{node.full_code}» زیرمحل دارد؛ یک Bin یا طبقهٔ داخلِ آن را انتخاب کنید."))
        else:
            self.choice_label.setText(_p(f"«{node.full_code}» غیرفعال است."))
