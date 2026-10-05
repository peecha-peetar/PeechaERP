"""نمایِ سه‌بعدیِ انبار -- R249: تصویرِ ایزومتریک از همان مختصاتِ نقشه + ارتفاع/Z (services.warehouse_locations.scene_3d).

بدونِ OpenGL (رسم با QGraphicsScene) تا رویِ همهٔ سیستم‌ها و حالتِ offscreen کار کند؛ چرخش و زاویهٔ دید
قابلِ‌تنظیم است و ترتیبِ رسم با الگوریتمِ نقاش (دورتر اول) است.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsPolygonItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget,
)

from peecha.ui import theme

_BASE = {"AREA": "#E7EEF7", "AISLE": "#F4F6F8", "RACK": "#9AA7B4", "SHELF": "#C9D3DD", "BIN": "#DCE5EE"}
_BLOCKED = "#8C8C8C"


class _View(QGraphicsView):
    def __init__(self, scene, owner) -> None:
        super().__init__(scene)
        self.owner = owner
        self.setLayoutDirection(Qt.LeftToRight)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setStyleSheet(f"background: {theme.BACKGROUND}; border: 1px solid {theme.BORDER}; border-radius: 8px;")

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
        layout.addLayout(controls)
        self.scene = QGraphicsScene(self)
        self.view = _View(self.scene, self)
        layout.addWidget(self.view, stretch=1)
        self.boxes: list = []
        self.colors: dict[int, QColor | None] = {}
        self.highlighted: set[int] = set()
        self.dimmed: set[int] = set()
        self.polygons: dict[int, list[QGraphicsPolygonItem]] = {}

    def set_data(self, boxes: list, colors: dict | None = None, highlighted=None, dimmed=None) -> None:
        self.boxes = boxes
        self.colors = colors or {}
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
        item.setToolTip(b.code)
        self.scene.addItem(item)
        return item
