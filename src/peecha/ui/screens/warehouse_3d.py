"""نمایِ سه‌بعدیِ انبار -- R249: تصویرِ ایزومتریک از همان مختصاتِ نقشه + ارتفاع/Z (services.warehouse_locations.scene_3d).

بدونِ OpenGL (رسم با QGraphicsScene) تا رویِ همهٔ سیستم‌ها و حالتِ offscreen کار کند؛ چرخش و زاویهٔ دید
قابلِ‌تنظیم است و ترتیبِ رسم با الگوریتمِ نقاش (دورتر اول) است.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox, QGraphicsItem, QGraphicsPolygonItem, QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView,
    QHBoxLayout, QLabel, QSlider, QToolTip, QVBoxLayout, QWidget,
)

from peecha.ui import theme

_BASE = {"AREA": "#E7EEF7", "AISLE": "#F4F6F8", "RACK": "#9AA7B4", "SHELF": "#C9D3DD", "BIN": "#DCE5EE"}
_BLOCKED = "#8C8C8C"
_LABELED = ("AREA", "AISLE", "RACK")  # R255: برچسبِ ثابت؛ بقیه با نگه‌داشتنِ ماوس


class _View(QGraphicsView):
    def __init__(self, scene, owner) -> None:
        super().__init__(scene)
        self.owner = owner
        self.setLayoutDirection(Qt.LeftToRight)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setStyleSheet(f"QGraphicsView {{ background: {theme.BACKGROUND}; border: 1px solid {theme.BORDER}; border-radius: 8px; }}")
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        item = self.itemAt(event.position().toPoint())
        lid = int(item.data(0)) if item is not None and item.data(0) is not None else None
        self.owner.hover(lid, event.globalPosition().toPoint())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.owner.hover(None, None)
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        item = self.itemAt(event.position().toPoint())
        if item is not None and item.data(0) is not None:
            self.owner.location_clicked.emit(int(item.data(0)))
        super().mousePressEvent(event)


class Warehouse3DView(QWidget):
    """boxes: خروجیِ scene_3d؛ colors: رنگِ حالتِ نقشه برایِ هر محل (یا None)."""

    location_clicked = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("چرخش:"))
        self.azimuth_slider = QSlider(Qt.Horizontal)
        self.azimuth_slider.setRange(0, 359)
        self.azimuth_slider.setValue(30)
        self.azimuth_slider.valueChanged.connect(lambda _v: self.redraw())
        controls.addWidget(self.azimuth_slider, stretch=2)
        controls.addWidget(QLabel("زاویهٔ دید:"))
        self.elevation_slider = QSlider(Qt.Horizontal)
        self.elevation_slider.setRange(15, 85)
        self.elevation_slider.setValue(35)
        self.elevation_slider.valueChanged.connect(lambda _v: self.redraw())
        controls.addWidget(self.elevation_slider, stretch=1)
        controls.addWidget(QLabel("ارتفاع:"))
        self.height_slider = QSlider(Qt.Horizontal)
        self.height_slider.setRange(50, 300)
        self.height_slider.setValue(100)
        self.height_slider.valueChanged.connect(lambda _v: self.redraw())
        controls.addWidget(self.height_slider, stretch=1)
        self.labels_check = QCheckBox("برچسب‌ها")
        self.labels_check.setChecked(True)
        self.labels_check.toggled.connect(lambda _c: self.redraw())
        controls.addWidget(self.labels_check)
        layout.addLayout(controls)
        self.hover_label = QLabel("ماوس را رویِ هر محل نگه دارید تا نام و اطلاعاتش نمایش داده شود.")
        self.hover_label.setObjectName("sectionHint")
        self.hover_label.setWordWrap(True)
        self.hover_label.setTextFormat(Qt.RichText)
        layout.addWidget(self.hover_label)
        self.scene = QGraphicsScene(self)
        self.view = _View(self.scene, self)
        layout.addWidget(self.view, stretch=1)
        self.boxes: list = []
        self.colors: dict[int, QColor | None] = {}
        self.highlighted: set[int] = set()
        self.dimmed: set[int] = set()
        self.polygons: dict[int, list[QGraphicsPolygonItem]] = {}
        self.info: dict[int, str] = {}
        self.names: dict[int, str] = {}
        self._hovered: int | None = None

    def set_data(self, boxes: list, colors: dict | None = None, highlighted=None, dimmed=None,
                 info: dict | None = None, names: dict | None = None) -> None:
        """info: متنِ کاملِ هر محل برایِ نمایش با ماوس؛ names: برچسبِ کوتاهِ رویِ منطقه/راهرو/قفسه."""
        self.boxes = boxes
        self.colors = colors or {}
        self.info = info or {}
        self.names = names or {}
        self.highlighted = set(highlighted or ())
        self.dimmed = set(dimmed or ())
        self.redraw()
        self.fit()

    def fit(self) -> None:
        rect = self.scene.itemsBoundingRect()
        if not rect.isEmpty():
            self.view.fitInView(rect.adjusted(-30, -30, 30, 30), Qt.KeepAspectRatio)

    # --- تصویرکردن -------------------------------------------------------
    def _projector(self):
        if self.boxes:
            cx = (min(b.x for b in self.boxes) + max(b.x + b.w for b in self.boxes)) / 2
            cy = (min(b.y for b in self.boxes) + max(b.y + b.d for b in self.boxes)) / 2
        else:
            cx = cy = 0.0
        a = math.radians(self.azimuth_slider.value())
        cos_a, sin_a = math.cos(a), math.sin(a)
        e = math.radians(self.elevation_slider.value())
        tilt, rise = math.sin(e), math.cos(e) * self.height_slider.value() / 100

        def rotate(x, y):
            dx, dy = x - cx, y - cy
            return dx * cos_a - dy * sin_a, dx * sin_a + dy * cos_a

        def project(x, y, z):
            rx, ry = rotate(x, y)
            return QPointF(rx, ry * tilt - z * rise), ry  # ry = عمق (بزرگ‌تر = نزدیک‌تر)

        return project

    def redraw(self) -> None:
        self.scene.clear()
        self.polygons = {}
        self._hovered = None
        project = self._projector()
        order = []
        for b in self.boxes:
            corners = [(b.x, b.y), (b.x + b.w, b.y), (b.x + b.w, b.y + b.d), (b.x, b.y + b.d)]
            depth = sum(project(x, y, 0)[1] for x, y in corners) / 4
            order.append((b.z, depth, b, corners))
        # کف‌ها اول، سپس دورتر به نزدیک‌تر و پایین به بالا
        order.sort(key=lambda t: (t[2].level not in ("AREA", "AISLE"), t[1], t[0]))
        for z, _depth, b, corners in order:
            self._draw_box(b, corners, project)
        if self.labels_check.isChecked():
            for b in self.boxes:
                if b.level in _LABELED:
                    self._draw_label(b, project)

    def _draw_label(self, b, project) -> None:
        """برچسبِ خوانا با اندازهٔ ثابت (مستقل از زوم) و پس‌زمینه، رویِ مرکزِ سقفِ محل."""
        center, _ = project(b.x + b.w / 2, b.y + b.d / 2, b.z + b.h)
        text = QGraphicsSimpleTextItem(self.names.get(b.location_id) or b.code.split("-")[-1])
        font = QFont(text.font())
        font.setPointSizeF(10 if b.level == "RACK" else 11)
        font.setBold(b.level != "RACK")
        text.setFont(font)
        text.setBrush(QColor("#1A1B2E"))  # رویِ زمینهٔ سفیدِ برچسب، مستقل از تمِ تیره/روشن
        rect = text.boundingRect().adjusted(-4, -2, 4, 2)
        box = QGraphicsRectItem(rect)
        box.setBrush(QColor(255, 255, 255, 215))
        box.setPen(QPen(QColor(0, 0, 0, 90), 0))
        box.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        box.setPos(center - QPointF(rect.width() / 2, rect.height() / 2))
        box.setZValue(10000 + (1 if b.level == "RACK" else 0))
        box.setData(0, b.location_id)
        text.setParentItem(box)
        text.setData(0, b.location_id)
        self.scene.addItem(box)

    def hover(self, location_id: int | None, global_pos) -> None:
        if location_id == self._hovered:
            return
        for lid, width in ((self._hovered, None), (location_id, 2.5)):
            for poly in self.polygons.get(lid, []) if lid is not None else []:
                pen = QPen(poly.pen())
                if width is None:
                    selected = lid in self.highlighted
                    pen.setColor(QColor(theme.ACCENT) if selected else QColor(0, 0, 0, 70))
                    pen.setWidthF(3 if selected else 0.6)
                else:
                    pen.setColor(QColor(theme.ACCENT))
                    pen.setWidthF(width)
                poly.setPen(pen)
        self._hovered = location_id
        if location_id is None:
            QToolTip.hideText()
            return
        text = self.info.get(location_id) or next((b.code for b in self.boxes if b.location_id == location_id), "")
        self.hover_label.setText(text)
        if global_pos is not None:
            QToolTip.showText(global_pos, text, self.view)

    def _fill(self, b) -> QColor:
        color = self.colors.get(b.location_id)
        color = QColor(color) if color is not None else QColor(_BASE.get(b.level, _BASE["BIN"]))
        if not b.active or b.status in ("BLOCKED", "INACTIVE", "MAINTENANCE"):
            color = QColor(_BLOCKED)
        if b.location_id in self.dimmed:
            color.setAlpha(50)
        elif color.alpha() < 255 and b.level not in ("AREA", "AISLE"):
            color.setAlpha(max(color.alpha(), 140))
        return color

    def _draw_box(self, b, corners, project) -> None:
        base = self._fill(b)
        pen = QPen(QColor(theme.ACCENT) if b.location_id in self.highlighted else QColor(0, 0, 0, 70),
                   3 if b.location_id in self.highlighted else 0.6)
        pen.setCosmetic(True)
        bottom = [project(x, y, b.z) for x, y in corners]
        top = [project(x, y, b.z + b.h) for x, y in corners]
        items = []
        faces = []
        for i in range(4):
            j = (i + 1) % 4
            depth = (bottom[i][1] + bottom[j][1]) / 2
            faces.append((depth, [bottom[i][0], bottom[j][0], top[j][0], top[i][0]], i))
        faces.sort(key=lambda f: f[0])
        for _d, points, i in faces[2:] if b.h > 2 else []:  # فقط دو وجهِ رو به بیننده
            shade = QColor(base).darker(125 if i % 2 else 112)
            items.append(self._polygon(points, shade, pen, b))
        items.append(self._polygon([p for p, _ in top], base, pen, b))
        self.polygons[b.location_id] = items

    def _polygon(self, points, color, pen, b) -> QGraphicsPolygonItem:
        item = QGraphicsPolygonItem(QPolygonF(points))
        item.setBrush(QBrush(color))
        item.setPen(pen)
        item.setData(0, b.location_id)
        item.setToolTip(self.info.get(b.location_id) or b.code)
        self.scene.addItem(item)
        return item
