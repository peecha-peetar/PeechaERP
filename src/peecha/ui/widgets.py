"""ویجت‌های پایتونی پیچا — برای رفتاری که فقط با خواص KV قابل‌تنظیم نیست.

KivyMD 1.2 برای MDTextField دو لیبل داخلی (hint/helper شناور بالای فیلد)
می‌سازد که halign‌شان مستقیم در کد پایتونِ خودِ KivyMD با "left" هاردکد
شده (`set_objects_labels()` در textfield.py) — هیچ property عمومی برای
override کردنش در KV نیست (فقط فونتشان از طریق font_name_hint_text/
font_name_helper_text قابل‌تنظیم است، نه جهتشان). برای همین این‌جا این دو
لیبل را بعد از ساخته‌شدن مستقیم در پایتون راست‌چین می‌کنیم.
"""

from __future__ import annotations

from kivy.factory import Factory
from kivy.graphics import Color, Line
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.widget import Widget
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.card import MDCard
from kivymd.uix.textfield import MDTextField


class PTextField(MDTextField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        for label_attr in ("_hint_text_label", "_helper_text_label", "_max_length_label"):
            label = getattr(self, label_attr, None)
            if label is not None:
                label.halign = "right"


class PNavItem(ButtonBehavior, MDBoxLayout):
    """آیتم منوی نوار کناری — طبق docs/ui-ux-guidelines.md بخش ۵/۱۰."""

    icon = StringProperty("circle-outline")
    text = StringProperty("")
    selected = BooleanProperty(False)


class PLabelListRow(MDBoxLayout):
    """یک ردیف ساده‌ی متنی راست‌چین برای فهرست‌ها (مثلاً کدینگ حسابداری)."""

    text = StringProperty("")


class PStatCard(MDCard):
    """کارت آماری (KPI) — طبق docs/ui-ux-guidelines.md بخش ۱۰."""

    icon = StringProperty("chart-box-outline")
    icon_bg_color = ListProperty([0.145, 0.388, 0.922, 1])
    title = StringProperty("")
    value = StringProperty("")
    subtitle = StringProperty("")
    trend_text = StringProperty("")
    trend_positive = BooleanProperty(True)


class LineAreaChart(Widget):
    """نمودار خطی/ناحیه‌ای ساده (رسم دستی روی Canvas) — طبق تصمیم بخش ۱۱ راهنمای UI/UX.

    series: لیستی از دیکشنری {"name": str, "color": (r,g,b,a), "values": [float, ...]}
    (همه باید هم‌طول باشند)؛ labels: برچسب محور افقی (هم‌طول با values).
    """

    series = ListProperty([])
    labels = ListProperty([])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self._redraw, size=self._redraw, series=self._redraw, labels=self._redraw)

    def _redraw(self, *_args) -> None:
        self.canvas.clear()
        if not self.series or not self.labels:
            return

        all_values = [v for s in self.series for v in s["values"]]
        if not all_values:
            return
        max_value = max(all_values) or 1
        min_value = min(0, min(all_values))

        pad_left, pad_right, pad_top, pad_bottom = 8, 8, 8, 24
        plot_x = self.x + pad_left
        plot_y = self.y + pad_bottom
        plot_w = max(self.width - pad_left - pad_right, 1)
        plot_h = max(self.height - pad_top - pad_bottom, 1)
        n = len(self.labels)
        step_x = plot_w / max(n - 1, 1)

        def to_canvas_point(index: int, value: float) -> tuple[float, float]:
            px = plot_x + index * step_x
            ratio = (value - min_value) / (max_value - min_value or 1)
            py = plot_y + ratio * plot_h
            return px, py

        with self.canvas:
            for s in self.series:
                points_xy = [to_canvas_point(i, v) for i, v in enumerate(s["values"])]
                r, g, b, a = s["color"]

                # ناحیه‌ی زیر خط (شفاف) فقط برای اولین سری، شبیه نمونه‌ی طراحی
                if s is self.series[0]:
                    Color(r, g, b, 0.15)
                    area_points: list[float] = [plot_x, plot_y]
                    for px, py in points_xy:
                        area_points += [px, py]
                    area_points += [plot_x + (n - 1) * step_x, plot_y]
                    from kivy.graphics import Mesh
                    from kivy.graphics.tesselator import Tesselator

                    tess = Tesselator()
                    tess.add_contour(area_points)
                    if tess.tesselate():
                        for vertices, indices in tess.meshes:
                            Mesh(vertices=vertices, indices=indices, mode="triangle_fan")

                Color(r, g, b, 1)
                flat_points: list[float] = []
                for px, py in points_xy:
                    flat_points += [px, py]
                Line(points=flat_points, width=2, joint="round", cap="round")


class DonutChart(Widget):
    """نمودار دونات ساده (رسم دستی) — segments: [{"label": str, "value": float, "color": (r,g,b,a)}]."""

    segments = ListProperty([])
    stroke_width = NumericProperty(18)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self._redraw, size=self._redraw, segments=self._redraw)

    def _redraw(self, *_args) -> None:
        self.canvas.clear()
        total = sum(seg["value"] for seg in self.segments)
        if total <= 0:
            return

        cx = self.x + self.width / 2
        cy = self.y + self.height / 2
        radius = max(min(self.width, self.height) / 2 - self.stroke_width, 4)

        start_angle = 90.0  # از بالا شروع می‌شود (ساعت ۱۲)
        with self.canvas:
            for seg in self.segments:
                sweep = 360.0 * (seg["value"] / total)
                end_angle = start_angle - sweep  # جهت ساعتگرد
                r, g, b, a = seg["color"]
                Color(r, g, b, 1)
                Line(
                    circle=(cx, cy, radius, end_angle, start_angle),
                    width=self.stroke_width,
                    cap="none",
                )
                start_angle = end_angle


Factory.register("PTextField", cls=PTextField)
Factory.register("PNavItem", cls=PNavItem)
Factory.register("PLabelListRow", cls=PLabelListRow)
Factory.register("PStatCard", cls=PStatCard)
Factory.register("LineAreaChart", cls=LineAreaChart)
Factory.register("DonutChart", cls=DonutChart)
