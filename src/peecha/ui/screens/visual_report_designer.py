"""طراحِ بصریِ گزارشِ چاپی (WYSIWYG، مثلِ FastReport) — بومِ گرافیکی که
رویش با ماوس متن/فیلد/خط/مستطیل/تصویر را در باندهایِ هدر/جزئیات/فوتر
جابجا و اندازه‌دهی می‌کنید. رویِ منبعِ داده‌یِ گزارش‌سازِ کامل
(report_designer.py) سوار می‌شود — این صفحه فقط چیدمانِ بصری را می‌سازد."""

from __future__ import annotations

import datetime

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import report_designer as report_designer_service
from peecha.services import visual_reports as visual_reports_service
from peecha.ui import theme, visual_report_render
from peecha.ui.widgets import FieldHelpMixin

_BAND_LABELS = {
    "REPORT_HEADER": "سرتیترِ گزارش (یک‌بار، بالایِ صفحه‌یِ اول)",
    "PAGE_HEADER": "سرصفحه (هر صفحه)",
    "GROUP_HEADER": "سرگروه (هر گروه)",
    "DETAIL": "جزئیات (هر ردیف)",
    "GROUP_FOOTER": "پاگروه (هر گروه)",
    "PAGE_FOOTER": "پاصفحه (هر صفحه)",
    "REPORT_FOOTER": "پایانِ گزارش (یک‌بار، انتهایِ آخرین صفحه)",
}

_OBJECT_TYPE_OPTIONS = [
    ("TEXT", "متنِ ثابت"),
    ("FIELD", "فیلدِ داده"),
    ("LINE", "خط"),
    ("RECTANGLE", "مستطیل"),
    ("IMAGE", "تصویر"),
]

_ALIGN_OPTIONS = [("RIGHT", "راست"), ("CENTER", "وسط"), ("LEFT", "چپ")]
_BORDER_OPTIONS = [("NONE", "بدون خط دور"), ("ALL", "دورِ کامل"), ("BOTTOM", "فقط زیر"), ("TOP", "فقط بالا")]
_PAGE_SIZE_OPTIONS = [("A4", "A4"), ("A5", "A5"), ("LETTER", "لتر")]
_ORIENTATION_OPTIONS = [("PORTRAIT", "عمودی"), ("LANDSCAPE", "افقی")]

_GLOBAL_FIELD_OPTIONS = [
    ("COMPANY_NAME", "نامِ شرکت"),
    ("REPORT_TITLE", "عنوانِ گزارش"),
    ("PRINT_DATE", "تاریخِ چاپ"),
    ("PAGE_NUMBER", "شماره‌یِ صفحه"),
    ("PAGE_COUNT", "تعدادِ کلِ صفحات"),
    ("GRAND_TOTAL_DEBIT", "جمعِ کلِ بدهکار"),
    ("GRAND_TOTAL_CREDIT", "جمعِ کلِ بستانکار"),
]

_PX_PER_MM = 3.0  # مقیاسِ بومِ طراحی (فقط نمایش؛ در چاپِ واقعی از resolution چاپگر استفاده می‌شود)
_HANDLE_PX = 10


class _ReportObjectItem(QGraphicsRectItem):
    """یک شیءِ قابلِ‌جابجایی/اندازه‌دهی رویِ بوم — گوشه‌یِ پایین‌راست
    (طبقِ راست‌به‌چپ‌بودنِ صفحه، همان گوشه‌ای که معمولاً دست‌گیرِ اندازه‌دهی
    آن‌جاست) دستگیره‌یِ اندازه‌دهی است."""

    def __init__(self, obj_row: visual_reports_service.VisualObjectRow, band_top_y_px: float, on_change) -> None:
        w = float(obj_row.width_mm) * _PX_PER_MM
        h = float(obj_row.height_mm) * _PX_PER_MM
        super().__init__(0, 0, w, h)
        self.obj_row = obj_row
        self.band_top_y_px = band_top_y_px
        self._on_change = on_change
        self._resizing = False
        self._resize_start = QPointF()
        self._orig_rect = QRectF()

        self.setFlags(
            QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setPos(float(obj_row.x_mm) * _PX_PER_MM, band_top_y_px + float(obj_row.y_mm) * _PX_PER_MM)
        self._apply_style()

        self.label = QGraphicsSimpleTextItem(self._preview_text(), self)
        self.label.setPos(4, 2)

    def _apply_style(self) -> None:
        colors = {
            "TEXT": QColor("#e8f0fe"),
            "FIELD": QColor("#fff3cd"),
            "LINE": QColor("#f0f0f0"),
            "RECTANGLE": QColor("#f0f0f0"),
            "IMAGE": QColor("#e0e0e0"),
        }
        self.setBrush(QBrush(colors.get(self.obj_row.object_type, QColor("#f0f0f0"))))
        self.setPen(QPen(QColor("#888888"), 1))

    def _preview_text(self) -> str:
        if self.obj_row.object_type == "TEXT":
            return self.obj_row.text_content or "(متنِ خالی)"
        if self.obj_row.object_type == "FIELD":
            return f"«{self.obj_row.field_code or '؟'}»"
        return {"LINE": "خط", "RECTANGLE": "مستطیل", "IMAGE": "تصویر"}.get(self.obj_row.object_type, "")

    def refresh_preview(self) -> None:
        self.label.setText(self._preview_text())
        self._apply_style()

    def _is_on_handle(self, pos: QPointF) -> bool:
        r = self.rect()
        return pos.x() >= r.width() - _HANDLE_PX and pos.y() >= r.height() - _HANDLE_PX

    def hoverMoveEvent(self, event) -> None:
        cursor = Qt.SizeFDiagCursor if self._is_on_handle(event.pos()) else Qt.SizeAllCursor
        self.setCursor(cursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if self._is_on_handle(event.pos()):
            self._resizing = True
            self._resize_start = event.scenePos()
            self._orig_rect = self.rect()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._resizing:
            delta = event.scenePos() - self._resize_start
            new_w = max(15.0, self._orig_rect.width() + delta.x())
            new_h = max(10.0, self._orig_rect.height() + delta.y())
            self.setRect(0, 0, new_w, new_h)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._resizing:
            self._resizing = False
            self._on_change(self)
        else:
            super().mouseReleaseEvent(event)
            self._on_change(self)

    def mm_geometry(self) -> tuple[float, float, float, float]:
        x_mm = self.pos().x() / _PX_PER_MM
        y_mm = max(0.0, (self.pos().y() - self.band_top_y_px) / _PX_PER_MM)
        w_mm = self.rect().width() / _PX_PER_MM
        h_mm = self.rect().height() / _PX_PER_MM
        return x_mm, y_mm, w_mm, h_mm


class _CanvasView(QGraphicsView):
    """QGraphicsView با overrideِ واقعیِ mousePressEvent (نه monkey-patch
    رویِ نمونه، که در PySide6 برایِ متدهایِ مجازی قابلِ‌اتکا نیست) — کلیک
    رویِ بوم را، وقتی حالتِ «افزودن» فعال است، به تابعِ صاحبِ صفحه پاس می‌دهد."""

    def __init__(self, scene: QGraphicsScene, on_place, is_placing) -> None:
        super().__init__(scene)
        self._on_place = on_place
        self._is_placing = is_placing

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if self._is_placing():
            self._on_place(self.mapToScene(event.pos()))


class VisualReportDesignerScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._templates: list[visual_reports_service.VisualTemplateRow] = []
        self._selected_template_id: int | None = None
        self._bands: list[visual_reports_service.VisualBandRow] = []
        self._band_top_offsets: dict[int, float] = {}
        self._items_by_object_id: dict[int, _ReportObjectItem] = {}
        self._selected_item: _ReportObjectItem | None = None
        self._place_mode: str | None = None
        self._underlying_kind: str | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)
        outer.addWidget(self._build_templates_panel())
        outer.addWidget(self._build_canvas_panel(), stretch=1)
        outer.addWidget(self._build_side_panel())

        self.set_field_help([
            (self.new_name_field, "نامِ گزارشِ بصریِ تازه‌ای که می‌خواهید طراحی کنید."),
            (
                self.new_report_combo,
                "کدام گزارشِ گزارش‌سازِ کامل (تراکنشی/خلاصه) منبعِ داده‌یِ این طراحیِ بصری باشد.",
            ),
            (self.templates_list, "فهرستِ طراحی‌هایِ بصریِ ساخته‌شده."),
            (
                self.canvas_view,
                "بومِ طراحی. برایِ افزودنِ شیء، از جعبه‌ابزار یک نوع را انتخاب کنید و رویِ باندِ موردِنظر کلیک کنید؛ "
                "برایِ جابجایی بکشید، برایِ اندازه‌دهی گوشه‌ی پایین‌راستِ شیء را بکشید.",
            ),
        ])

    # ------------------------------------------------------------------
    def _build_templates_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(260)
        layout = QVBoxLayout(panel)

        title = QLabel("طراحیِ بصریِ گزارش")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.new_name_field = QLineEdit()
        self.new_name_field.setPlaceholderText("نامِ گزارشِ بصریِ تازه...")
        layout.addWidget(self.new_name_field)

        self.new_report_combo = QComboBox()
        layout.addWidget(self.new_report_combo)

        self.new_page_size_combo = QComboBox()
        for code, label in _PAGE_SIZE_OPTIONS:
            self.new_page_size_combo.addItem(label, code)
        layout.addWidget(self.new_page_size_combo)

        self.new_orientation_combo = QComboBox()
        for code, label in _ORIENTATION_OPTIONS:
            self.new_orientation_combo.addItem(label, code)
        layout.addWidget(self.new_orientation_combo)

        add_button = QPushButton("افزودنِ طراحیِ بصری")
        add_button.setObjectName("primaryButton")
        add_button.clicked.connect(self._on_add_template)
        layout.addWidget(add_button)

        self.templates_list = QListWidget()
        self.templates_list.currentRowChanged.connect(self._on_template_selected)
        layout.addWidget(self.templates_list, stretch=1)

        rename_row = QHBoxLayout()
        self.rename_field = QLineEdit()
        rename_row.addWidget(self.rename_field, stretch=1)
        rename_button = QPushButton("تغییرِ نام")
        rename_button.setObjectName("flatButton")
        rename_button.clicked.connect(self._on_rename_template)
        rename_row.addWidget(rename_button)
        layout.addLayout(rename_row)

        delete_button = QPushButton("حذفِ طراحی")
        delete_button.setObjectName("dangerButton")
        delete_button.clicked.connect(self._on_delete_template)
        layout.addWidget(delete_button)

        self.use_grouping_checkbox = QCheckBox("گروه‌بندی (سرگروه/پاگروه) فعال باشد")
        self.use_grouping_checkbox.toggled.connect(self._on_use_grouping_toggled)
        layout.addWidget(self.use_grouping_checkbox)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        return panel

    def _build_canvas_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        toolbox_row = QHBoxLayout()
        toolbox_row.addWidget(QLabel("افزودن:"))
        self._tool_buttons: dict[str, QPushButton] = {}
        for code, label in _OBJECT_TYPE_OPTIONS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setObjectName("flatButton")
            btn.clicked.connect(lambda _checked=False, c=code: self._on_tool_selected(c))
            toolbox_row.addWidget(btn)
            self._tool_buttons[code] = btn
        toolbox_row.addStretch(1)

        delete_obj_button = QPushButton("حذفِ شیءِ انتخاب‌شده")
        delete_obj_button.setObjectName("dangerButton")
        delete_obj_button.clicked.connect(self._on_delete_object)
        toolbox_row.addWidget(delete_obj_button)

        preview_button = QPushButton("👁 پیش‌نمایشِ چاپ")
        preview_button.setObjectName("flatButton")
        preview_button.clicked.connect(self._on_print_preview)
        toolbox_row.addWidget(preview_button)

        pdf_button = QPushButton("📄 خروجیِ PDF")
        pdf_button.setObjectName("flatButton")
        pdf_button.clicked.connect(self._on_export_pdf)
        toolbox_row.addWidget(pdf_button)
        layout.addLayout(toolbox_row)

        self.scene = QGraphicsScene()
        self.scene.selectionChanged.connect(self._on_selection_changed)
        self.canvas_view = _CanvasView(self.scene, self._place_object_at, lambda: self._place_mode is not None)
        self.canvas_view.setBackgroundBrush(QBrush(QColor("#dddddd")))
        layout.addWidget(self.canvas_view, stretch=1)

        return panel

    def _build_side_panel(self) -> QWidget:
        outer_panel = QScrollArea()
        outer_panel.setWidgetResizable(True)
        outer_panel.setFixedWidth(320)
        panel = QWidget()
        layout = QVBoxLayout(panel)

        layout.addWidget(QLabel("ارتفاعِ باندها (میلی‌متر):"))
        self.bands_table = QTableWidget(0, 2)
        self.bands_table.setHorizontalHeaderLabels(["باند", "ارتفاع"])
        self.bands_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.bands_table.verticalHeader().setVisible(False)
        self.bands_table.setMaximumHeight(180)
        layout.addWidget(self.bands_table)

        layout.addWidget(QLabel("ویژگی‌هایِ شیءِ انتخاب‌شده:"))
        self.no_selection_label = QLabel("چیزی انتخاب نشده.")
        self.no_selection_label.setObjectName("sectionHint")
        layout.addWidget(self.no_selection_label)

        self.props_widget = QWidget()
        props_layout = QVBoxLayout(self.props_widget)
        props_layout.setContentsMargins(0, 0, 0, 0)

        geom_row = QHBoxLayout()
        self.x_spin = self._mm_spin()
        self.y_spin = self._mm_spin()
        self.w_spin = self._mm_spin()
        self.h_spin = self._mm_spin()
        for lbl, spin in (("X", self.x_spin), ("Y", self.y_spin), ("عرض", self.w_spin), ("ارتفاع", self.h_spin)):
            geom_row.addWidget(QLabel(lbl))
            geom_row.addWidget(spin)
        props_layout.addLayout(geom_row)
        apply_geom_button = QPushButton("اعمالِ اندازه/موقعیت")
        apply_geom_button.setObjectName("flatButton")
        apply_geom_button.clicked.connect(self._on_apply_geometry)
        props_layout.addWidget(apply_geom_button)

        self.text_content_field = QLineEdit()
        self.text_content_field.setPlaceholderText("متنِ ثابت...")
        props_layout.addWidget(self.text_content_field)

        self.field_combo = QComboBox()
        props_layout.addWidget(self.field_combo)

        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("اندازه‌یِ فونت:"))
        self.font_size_spin = QDoubleSpinBox()
        self.font_size_spin.setRange(6, 48)
        self.font_size_spin.setDecimals(0)
        self.font_size_spin.setValue(10)
        font_row.addWidget(self.font_size_spin)
        self.bold_checkbox = QCheckBox("درشت")
        font_row.addWidget(self.bold_checkbox)
        props_layout.addLayout(font_row)

        self.align_combo = QComboBox()
        for code, label in _ALIGN_OPTIONS:
            self.align_combo.addItem(label, code)
        props_layout.addWidget(self.align_combo)

        self.border_combo = QComboBox()
        for code, label in _BORDER_OPTIONS:
            self.border_combo.addItem(label, code)
        props_layout.addWidget(self.border_combo)

        image_button = QPushButton("بارگذاریِ تصویر...")
        image_button.setObjectName("flatButton")
        image_button.clicked.connect(self._on_load_image)
        props_layout.addWidget(image_button)

        save_props_button = QPushButton("ذخیره‌یِ ویژگی‌ها")
        save_props_button.setObjectName("primaryButton")
        save_props_button.clicked.connect(self._on_save_properties)
        props_layout.addWidget(save_props_button)

        layout.addWidget(self.props_widget)
        self.props_widget.setVisible(False)
        layout.addStretch(1)

        outer_panel.setWidget(panel)
        return outer_panel

    def _mm_spin(self) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0, 400)
        spin.setDecimals(1)
        return spin

    # ------------------------------------------------------------------
    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        theme.set_status_label(self.status_label, "", ok=True)
        company_id = self._company_id()

        self.new_report_combo.clear()
        if company_id is not None:
            for t in report_designer_service.list_templates(company_id):
                kind_label = "تراکنشی" if t.report_kind == "DETAIL" else "خلاصه"
                self.new_report_combo.addItem(f"{t.name} ({kind_label})", t.report_template_id)

        self._templates = visual_reports_service.list_templates(company_id) if company_id is not None else []
        self.templates_list.blockSignals(True)
        self.templates_list.clear()
        for t in self._templates:
            self.templates_list.addItem(t.name)
        self.templates_list.blockSignals(False)
        if self._templates:
            keep_index = next(
                (i for i, t in enumerate(self._templates) if t.visual_template_id == self._selected_template_id), 0
            )
            self.templates_list.setCurrentRow(keep_index)
            self._on_template_selected(keep_index)
        else:
            self._selected_template_id = None
            self.rename_field.setText("")
            self._reload_canvas()

    def _selected_template(self) -> visual_reports_service.VisualTemplateRow | None:
        return next((t for t in self._templates if t.visual_template_id == self._selected_template_id), None)

    def _on_template_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._templates):
            self._selected_template_id = None
            self.rename_field.setText("")
        else:
            self._selected_template_id = self._templates[row].visual_template_id
            self.rename_field.setText(self._templates[row].name)
        self._reload_canvas()

    def _on_add_template(self) -> None:
        company_id = self._company_id()
        name = self.new_name_field.text().strip()
        report_template_id = self.new_report_combo.currentData()
        if company_id is None or not name or report_template_id is None:
            theme.set_status_label(self.status_label, "نام و منبعِ داده را مشخص کنید.", ok=False)
            return
        visual_reports_service.create_template(
            company_id,
            name,
            report_template_id,
            page_size=self.new_page_size_combo.currentData(),
            orientation=self.new_orientation_combo.currentData(),
        )
        self.new_name_field.clear()
        self.refresh()

    def _on_rename_template(self) -> None:
        if self._selected_template_id is None:
            return
        name = self.rename_field.text().strip()
        if not name:
            return
        visual_reports_service.rename_template(self._selected_template_id, name)
        self.refresh()

    def _on_delete_template(self) -> None:
        if self._selected_template_id is None:
            return
        visual_reports_service.delete_template(self._selected_template_id)
        self._selected_template_id = None
        self.refresh()

    def _on_use_grouping_toggled(self, checked: bool) -> None:
        if self._selected_template_id is None:
            return
        visual_reports_service.update_template_settings(self._selected_template_id, use_grouping=checked)
        self._reload_canvas()

    # ------------------------------------------------------------------
    def _reload_canvas(self) -> None:
        self.scene.clear()
        self._items_by_object_id = {}
        self._selected_item = None
        self.bands_table.setRowCount(0)
        self._set_props_visible(False)

        template = self._selected_template()
        if template is None:
            self.use_grouping_checkbox.setEnabled(False)
            return

        company_id = self._company_id()
        report_templates = {t.report_template_id: t for t in report_designer_service.list_templates(company_id)} if company_id else {}
        underlying = report_templates.get(template.report_template_id)
        self._underlying_kind = underlying.report_kind if underlying else "DETAIL"

        self.use_grouping_checkbox.blockSignals(True)
        self.use_grouping_checkbox.setChecked(template.use_grouping)
        self.use_grouping_checkbox.setEnabled(self._underlying_kind == "DETAIL")
        self.use_grouping_checkbox.blockSignals(False)

        self._bands = visual_reports_service.list_bands(template.visual_template_id)
        objects_by_band = visual_reports_service.list_objects_by_band(template.visual_template_id)

        self.bands_table.setRowCount(len(self._bands))
        offset = 0.0
        self._band_top_offsets = {}
        page_w_mm, _h = visual_report_render.page_size_mm(template.page_size, template.orientation)
        # عرضِ بومِ طراحی باید دقیقاً همان عرضِ ناحیه‌یِ قابلِ‌چاپ باشد (نه
        # کلِ عرضِ کاغذ)، وگرنه شیءِ نزدیکِ لبه‌یِ راستِ بوم در چاپِ واقعی از
        # حاشیه‌یِ راست رد می‌شود — طبقِ گزارشِ عکسِ آزمایشی که همین اتفاق
        # را نشان داد.
        content_w_mm = float(page_w_mm) - float(template.margin_left_mm) - float(template.margin_right_mm)
        content_w_px = content_w_mm * _PX_PER_MM

        for row_index, band in enumerate(self._bands):
            self._band_top_offsets[band.band_id] = offset
            height_px = float(band.height_mm) * _PX_PER_MM

            band_rect = self.scene.addRect(0, offset, content_w_px, height_px, QPen(QColor("#4a5a8a")), QBrush(Qt.white))
            band_rect.setZValue(-10)
            band_label = self.scene.addSimpleText(_BAND_LABELS.get(band.band_type, band.band_type))
            band_label.setPos(content_w_px + 6, offset)
            band_label.setBrush(QBrush(QColor("#4a5a8a")))

            self.bands_table.setItem(row_index, 0, QTableWidgetItem(_BAND_LABELS.get(band.band_type, band.band_type)))
            height_spin = self._mm_spin()
            height_spin.setValue(float(band.height_mm))
            height_spin.editingFinished.connect(lambda b=band, s=height_spin: self._on_band_height_changed(b, s))
            self.bands_table.setCellWidget(row_index, 1, height_spin)

            for obj_row in objects_by_band.get(band.band_id, []):
                item = _ReportObjectItem(obj_row, offset, self._on_object_geometry_changed)
                self.scene.addItem(item)
                self._items_by_object_id[obj_row.object_id] = item

            offset += height_px

        self.scene.setSceneRect(0, 0, content_w_px + 220, offset + 20)
        self._refresh_field_options()

    def _on_band_height_changed(self, band: visual_reports_service.VisualBandRow, spin: QDoubleSpinBox) -> None:
        visual_reports_service.set_band_height(band.band_id, spin.value())
        self._reload_canvas()

    def _refresh_field_options(self) -> None:
        self.field_combo.clear()
        template = self._selected_template()
        if template is None:
            return
        if self._underlying_kind == "SUMMARY":
            self.field_combo.addItem("ردیف (برچسب)", "ROW_LABEL")
            columns = report_designer_service.list_columns(template.report_template_id)
            for i, col in enumerate(columns, start=1):
                self.field_combo.addItem(col.label, f"COL_{i}")
        else:
            columns = report_designer_service.list_columns(template.report_template_id)
            for col in columns:
                self.field_combo.addItem(col.label, col.field_code)
        for code, label in _GLOBAL_FIELD_OPTIONS:
            self.field_combo.addItem(f"[سراسری] {label}", code)

    # ------------------------------------------------------------------
    def _on_tool_selected(self, code: str) -> None:
        for c, btn in self._tool_buttons.items():
            btn.setChecked(c == code)
        self._place_mode = code

    def _band_at_scene_pos(self, pos: QPointF) -> visual_reports_service.VisualBandRow | None:
        y = pos.y()
        for band in self._bands:
            top = self._band_top_offsets.get(band.band_id, 0.0)
            bottom = top + float(band.height_mm) * _PX_PER_MM
            if top <= y <= bottom:
                return band
        return None

    def _place_object_at(self, scene_pos: QPointF) -> None:
        if self._place_mode is None or self._selected_template_id is None:
            return
        band = self._band_at_scene_pos(scene_pos)
        if band is None:
            return
        top = self._band_top_offsets.get(band.band_id, 0.0)
        x_mm = max(0.0, scene_pos.x() / _PX_PER_MM)
        y_mm = max(0.0, (scene_pos.y() - top) / _PX_PER_MM)
        default_w, default_h = (30.0, 6.0) if self._place_mode in ("TEXT", "FIELD") else (30.0, 15.0)

        object_id = visual_reports_service.create_object(
            band.band_id,
            self._place_mode,
            x_mm,
            y_mm,
            default_w,
            default_h,
            text_content="متنِ نمونه" if self._place_mode == "TEXT" else None,
            field_code=self.field_combo.currentData() if self._place_mode == "FIELD" else None,
        )
        self._place_mode = None
        for btn in self._tool_buttons.values():
            btn.setChecked(False)
        self._reload_canvas()
        if object_id in self._items_by_object_id:
            self._items_by_object_id[object_id].setSelected(True)

    def _on_object_geometry_changed(self, item: _ReportObjectItem) -> None:
        x_mm, y_mm, w_mm, h_mm = item.mm_geometry()
        visual_reports_service.update_object(item.obj_row.object_id, x_mm=x_mm, y_mm=y_mm, width_mm=w_mm, height_mm=h_mm)
        item.obj_row.x_mm = x_mm
        item.obj_row.y_mm = y_mm
        item.obj_row.width_mm = w_mm
        item.obj_row.height_mm = h_mm

    def _on_delete_object(self) -> None:
        if self._selected_item is None:
            return
        visual_reports_service.delete_object(self._selected_item.obj_row.object_id)
        self._reload_canvas()

    # ------------------------------------------------------------------
    def _set_props_visible(self, visible: bool) -> None:
        self.props_widget.setVisible(visible)
        self.no_selection_label.setVisible(not visible)

    def _on_selection_changed(self) -> None:
        selected = self.scene.selectedItems()
        if not selected or not isinstance(selected[0], _ReportObjectItem):
            self._selected_item = None
            self._set_props_visible(False)
            return
        item = selected[0]
        self._selected_item = item
        self._set_props_visible(True)
        obj = item.obj_row

        self.x_spin.setValue(float(obj.x_mm))
        self.y_spin.setValue(float(obj.y_mm))
        self.w_spin.setValue(float(obj.width_mm))
        self.h_spin.setValue(float(obj.height_mm))
        self.text_content_field.setVisible(obj.object_type == "TEXT")
        self.text_content_field.setText(obj.text_content or "")
        self.field_combo.setVisible(obj.object_type == "FIELD")
        if obj.object_type == "FIELD" and obj.field_code:
            idx = self.field_combo.findData(obj.field_code)
            if idx >= 0:
                self.field_combo.setCurrentIndex(idx)
        show_text_style = obj.object_type in ("TEXT", "FIELD")
        self.font_size_spin.setVisible(show_text_style)
        self.bold_checkbox.setVisible(show_text_style)
        self.align_combo.setVisible(show_text_style)
        self.border_combo.setVisible(show_text_style)
        if show_text_style:
            self.font_size_spin.setValue(obj.font_size)
            self.bold_checkbox.setChecked(obj.font_bold)
            align_idx = self.align_combo.findData(obj.text_align)
            if align_idx >= 0:
                self.align_combo.setCurrentIndex(align_idx)
            border_idx = self.border_combo.findData(obj.border_style)
            if border_idx >= 0:
                self.border_combo.setCurrentIndex(border_idx)
        image_button_visible = obj.object_type == "IMAGE"
        for child in self.props_widget.findChildren(QPushButton):
            if child.text().startswith("بارگذاریِ"):
                child.setVisible(image_button_visible)

    def _on_apply_geometry(self) -> None:
        if self._selected_item is None:
            return
        item = self._selected_item
        item.setPos(self.x_spin.value() * _PX_PER_MM, item.band_top_y_px + self.y_spin.value() * _PX_PER_MM)
        item.setRect(0, 0, self.w_spin.value() * _PX_PER_MM, self.h_spin.value() * _PX_PER_MM)
        self._on_object_geometry_changed(item)

    def _on_save_properties(self) -> None:
        if self._selected_item is None:
            return
        obj = self._selected_item.obj_row
        kwargs: dict = {}
        if obj.object_type == "TEXT":
            kwargs["text_content"] = self.text_content_field.text()
        if obj.object_type == "FIELD":
            kwargs["field_code"] = self.field_combo.currentData()
        if obj.object_type in ("TEXT", "FIELD"):
            kwargs["font_size"] = int(self.font_size_spin.value())
            kwargs["font_bold"] = self.bold_checkbox.isChecked()
            kwargs["text_align"] = self.align_combo.currentData()
            kwargs["border_style"] = self.border_combo.currentData()
        visual_reports_service.update_object(obj.object_id, **kwargs)
        theme.set_status_label(self.status_label, "ذخیره شد.", ok=True)
        self._reload_canvas_keep_selection(obj.object_id)

    def _on_load_image(self) -> None:
        if self._selected_item is None or self._selected_item.obj_row.object_type != "IMAGE":
            return
        path, _filter = QFileDialog.getOpenFileName(self, "انتخابِ تصویر", "", "تصویر (*.png *.jpg *.jpeg)")
        if not path:
            return
        object_id = self._selected_item.obj_row.object_id
        with open(path, "rb") as f:
            data = f.read()
        visual_reports_service.update_object(object_id, image_data=data)
        theme.set_status_label(self.status_label, "تصویر بارگذاری شد.", ok=True)
        self._reload_canvas_keep_selection(object_id)

    def _reload_canvas_keep_selection(self, object_id: int) -> None:
        # _reload_canvas بومِ گرافیکی را کامل می‌سازد (برایِ نمایشِ درستِ
        # پیش‌نمایشِ متنِ تازه رویِ شیء) که باعث می‌شود انتخابِ فعلی از دست
        # برود — اگر بلافاصله بعدِ ذخیره کاربر بخواهد همان شیء را حذف یا
        # دوباره ویرایش کند، بدونِ این خط بی‌سروصدا هیچ اتفاقی نمی‌افتاد.
        self._reload_canvas()
        item = self._items_by_object_id.get(object_id)
        if item is not None:
            item.setSelected(True)

    # ------------------------------------------------------------------
    def _on_print_preview(self) -> None:
        template = self._selected_template()
        company = session.current_company
        if template is None or company is None:
            return
        fiscal_year = session.current_fiscal_year
        today = datetime.date.today()
        date_from = fiscal_year.start_date if fiscal_year is not None else today.replace(month=1, day=1)
        try:
            visual_report_render.print_visual_report(
                self, template.visual_template_id, company.company_id, company.display_name, date_from, today
            )
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)

    def _on_export_pdf(self) -> None:
        template = self._selected_template()
        company = session.current_company
        if template is None or company is None:
            return
        fiscal_year = session.current_fiscal_year
        today = datetime.date.today()
        date_from = fiscal_year.start_date if fiscal_year is not None else today.replace(month=1, day=1)
        try:
            visual_report_render.export_visual_report_pdf(
                self, template.visual_template_id, company.company_id, company.display_name, date_from, today
            )
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
