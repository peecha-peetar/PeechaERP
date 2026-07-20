"""ویجت‌های پایتونی پیچا — برای رفتاری که فقط با خواص KV قابل‌تنظیم نیست.

KivyMD 1.2 برای MDTextField دو لیبل داخلی (hint/helper شناور بالای فیلد)
می‌سازد که halign‌شان مستقیم در کد پایتونِ خودِ KivyMD با "left" هاردکد
شده (`set_objects_labels()` در textfield.py) — هیچ property عمومی برای
override کردنش در KV نیست (فقط فونتشان از طریق font_name_hint_text/
font_name_helper_text قابل‌تنظیم است، نه جهتشان). برای همین این‌جا این دو
لیبل را بعد از ساخته‌شدن مستقیم در پایتون راست‌چین می‌کنیم.
"""

from __future__ import annotations

from kivy.animation import Animation
from kivy.factory import Factory
from kivy.graphics import Color, Line
from kivy.graphics import RoundedRectangle
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior, FocusBehavior
from kivy.uix.widget import Widget
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.menu.menu import BaseDropdownItem  # فقط از menu/__init__.py صادر نمی‌شود
from kivymd.uix.textfield import MDTextField

from peecha.ui import theme

_ACTIVATE_KEYCODES = (13, 32, 271)  # enter, spacebar, numpadenter


class KeyboardActivatedButtonBehavior(FocusBehavior):
    """برای دکمه‌هایی که جایگزینِ TextInput در فرم‌ها هستند (فیلدهای انتخابی،
    تب‌ها، دکمه‌ها): FocusBehavior فقط رسیدن با Tab را می‌دهد؛ فعال‌سازی با
    Enter/Space (مثل کلیک) را خودمان اضافه می‌کنیم — طبق درخواستِ صریح
    که کارِ فرم‌ها باید بدون ماوس هم ممکن باشد."""

    def keyboard_on_key_down(self, window, keycode, text, modifiers):
        if keycode[0] in _ACTIVATE_KEYCODES:
            self.dispatch("on_release")
            return True
        return super().keyboard_on_key_down(window, keycode, text, modifiers)


class PressFeedbackBehavior:
    """میکرو-تعاملِ لمس/کلیک — طبق درخواستِ مدرن‌سازیِ ظاهر: یک افتِ کوتاهِ
    opacity هنگامِ فشردن و بازگشتِ نرم بعدِ رهاشدن، تا دکمه‌ها/آیتم‌های
    منو «زنده» به‌نظر برسند (نه تغییرِ آنیِ حالت). عمداً روی opacity کار
    می‌کند نه رنگ، چون این‌طوری با بایندینگ‌های KV دیگر (مثلِ md_bg_color
    بر اساسِ selected) تداخل نمی‌کند — آن‌ها همچنان جدا و آنی کار می‌کنند."""

    def on_press(self):
        super().on_press()
        Animation.cancel_all(self, "opacity")
        Animation(opacity=0.7, duration=0.05).start(self)

    def on_release(self):
        super().on_release()
        Animation.cancel_all(self, "opacity")
        Animation(opacity=1, duration=0.15).start(self)


# سه لایه‌ی نیمه‌شفاف با پخش/افست/شفافیتِ افزایشی، برای تقریب دستیِ یک
# box-shadow نرم (طبق جدول Elevation در docs/ui-ux-guidelines.md بخش ۴).
_SHADOW_LAYERS = [
    (dp(12), dp(16), 0.035),
    (dp(6), dp(9), 0.05),
    (dp(2), dp(3), 0.07),
]


class SoftShadowBehavior:
    """سایه‌ی نرم چندلایه روی canvas.before، جایگزین elevation خودِ MDCard.

    در KivyMD 1.2.0 (نسخه‌ی نصب‌شده)، elevation>0 یک هاله‌ی تیره و سخت
    تولید می‌کند، نه سایه‌ی ملایمِ Material — با آزمایش مستقیم تایید شد.
    این mixin به‌جایش چند RoundedRectangle نیمه‌شفاف با پخش/افست افزایشی
    زیر کارت می‌کشد که به یک سایه‌ی نرم نزدیک‌تر است، به‌علاوه یک حاشیه‌ی
    ۱px ظریف طبق پالت. هر ویجتی که این mixin را دارد باید `radius` و
    `md_bg_color` را داشته باشد (مثل MDBoxLayout/MDCard).
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._shadow_rects: list[tuple[RoundedRectangle, float, float]] = []
        with self.canvas.before:
            for spread, offset, alpha in _SHADOW_LAYERS:
                Color(0, 0, 0, alpha)
                self._shadow_rects.append((RoundedRectangle(), spread, offset))
            self._face_color_instr = Color(rgba=self.md_bg_color)
            self._face_rect = RoundedRectangle()
            Color(rgba=theme.BORDER)
            self._border_line = Line(width=1)
        self.bind(pos=self._redraw, size=self._redraw, radius=self._redraw, md_bg_color=self._redraw)
        self._redraw()

    def _redraw(self, *_args) -> None:
        radius_value = self.radius[0] if isinstance(self.radius, (list, tuple)) else self.radius
        for rect, spread, offset in self._shadow_rects:
            rect.pos = (self.x - spread, self.y - offset - spread)
            rect.size = (self.width + spread * 2, self.height + spread * 2)
            rect.radius = [radius_value + spread] * 4
        self._face_color_instr.rgba = self.md_bg_color
        self._face_rect.pos = self.pos
        self._face_rect.size = self.size
        self._face_rect.radius = self.radius if isinstance(self.radius, (list, tuple)) else [self.radius] * 4
        self._border_line.rounded_rectangle = (self.x, self.y, self.width, self.height, radius_value)


class PCard(SoftShadowBehavior, MDBoxLayout):
    """کارتِ عمومیِ برنامه (پنل‌های داشبورد/کدینگ حسابداری/صدور سند و…)."""


class PStatCard(SoftShadowBehavior, MDBoxLayout):
    """کارت آماری (KPI) — طبق docs/ui-ux-guidelines.md بخش ۱۰."""

    icon = StringProperty("chart-box-outline")
    icon_bg_color = ListProperty([0.145, 0.388, 0.922, 1])
    title = StringProperty("")
    value = StringProperty("")
    subtitle = StringProperty("")
    trend_text = StringProperty("")
    trend_positive = BooleanProperty(True)


class PTextField(MDTextField):
    """persian_digits=True یعنی هر رقمِ ASCII/عربی‌ای که کاربر تایپ کند
    بلافاصله به رقم فارسی تبدیل می‌شود — طبق درخواستِ صریح کاربر که ارقامِ
    همه‌ی فیلدها فارسی دیده شود، نه فقط در نمایشِ نهایی.

    محدودیتِ واقعیِ Kivy (توضیح کامل در rtl.py): TextInput هم مثلِ Label
    هیچ bidi/شکل‌دهیِ بومی ندارد؛ اگر متنِ فارسیِ چندکلمه‌ای مستقیم و بدونِ
    shape() در .text گذاشته شود (مثلاً پرکردنِ فیلد برای حالتِ ویرایش)،
    کاملاً برعکس/درهم نمایش داده می‌شود (با تست مستقیم پیدا شد). چون
    shape() رشته را بازچینیِ بصری می‌کند (نه چیزی که بشود دوباره تایپ روی
    آن ادامه داد)، این‌جا دو حالت را جدا نگه می‌داریم:
      - set_value(raw)/`.value`: مقدارِ منطقی (خام) — همیشه همین باید
        خوانده/نوشته شود، نه `.text` مستقیم.
      - `.text`: مقدارِ نمایشی — وقتی فیلد فوکوس ندارد (کاربر در حالِ
        تایپ نیست) shape شده نمایش داده می‌شود تا خوانا باشد؛ به‌محضِ
        گرفتنِ فوکوس، فوراً به‌متنِ خام برمی‌گردد تا خودِ تایپ/مکان‌نمای
        کاربر با متنِ منطقی کار کند، نه رشته‌ی بازچینی‌شده."""

    persian_digits = BooleanProperty(False)
    # کلاس‌های فرزند که خودشان چرخه‌ی کاملِ shape‌کردنِ `.text` را مدیریت
    # می‌کنند (مثلاً AccountSearchField، که با انتخاب یک نتیجه مستقیم
    # `self.text = shape(...)` می‌کند) باید این را False کنند؛ وگرنه این
    # کلاس دوباره روی متنِ از قبل shape‌شده shape() صدا می‌زند و خرابش
    # می‌کند (shape کردنِ متنِ shape‌شده، نه چیزِ دیگر، تضمین‌شده خراب است).
    auto_shape_display = BooleanProperty(True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        for label_attr in ("_hint_text_label", "_helper_text_label", "_max_length_label"):
            label = getattr(self, label_attr, None)
            if label is not None:
                label.halign = "right"
        self._raw_value = self.text
        self._showing_shaped = False
        self._suppress_raw_tracking = False
        self.bind(text=self._persianize_on_text)
        self.bind(text=self._track_raw_value)
        self.bind(focus=self._on_focus_toggle_shape)

    def _persianize_on_text(self, _instance, value: str) -> None:
        if not self.persian_digits:
            return
        from peecha.ui.numerals import to_persian_digits  # noqa: PLC0415 - جلوگیری از وابستگیِ چرخه‌ای در import سطح‌ماژول

        converted = to_persian_digits(value)
        if converted != value:
            cursor = self.cursor
            self.text = converted
            self.cursor = cursor

    def _track_raw_value(self, _instance, value: str) -> None:
        # فقط وقتی *خودمان* داریم نسخه‌ی shape‌شده را موقتاً نمایش می‌دهیم
        # (_suppress_raw_tracking) این تغییر نادیده گرفته می‌شود؛ هر تغییرِ
        # دیگری — چه تایپِ کاربر، چه `.text = ...` مستقیم از جای دیگرِ کد
        # (مثلاً پاک‌کردنِ فرم) — باید بلافاصله مقدارِ منطقیِ تازه در نظر
        # گرفته شود، وگرنه set_value/`.value` با مقدارِ کهنه از هم‌گام
        # خارج می‌شوند (با تست مستقیم پیدا شد: پاک‌کردنِ فرم بعد از یک بار
        # blur-شدنِ فیلد، مقدارِ رشته‌ی shape‌شده‌ی قبلی را نگه می‌داشت).
        if self._suppress_raw_tracking:
            return
        self._raw_value = value
        self._showing_shaped = False

    def _on_focus_toggle_shape(self, _instance, focused: bool) -> None:
        if not self.auto_shape_display:
            return
        if focused:
            if self._showing_shaped:
                self._set_text_silently(self._raw_value)
                self._showing_shaped = False
                self.cursor = (len(self._raw_value), 0)
        else:
            self._apply_shaped_display()

    def insert_text(self, substring: str, from_undo: bool = False) -> None:
        # قبل از این‌که خودِ Kivy متن را داخلِ .text وارد کند، اگر همین الان
        # نسخه‌ی shape‌شده (از تایپِ کاراکترِ قبلی) نمایش داده می‌شود، باید
        # اول به متنِ خام برگردیم — وگرنه Kivy کاراکترِ تازه را داخلِ رشته‌ی
        # بازچینی‌شده وارد می‌کند که با موقعیتِ منطقی هیچ تناظرِ درستی ندارد.
        self._revert_to_raw_for_edit()
        super().insert_text(substring, from_undo=from_undo)
        self._live_shape_after_edit()

    def do_backspace(self, from_undo: bool = False, mode: str = "bkspc") -> None:
        self._revert_to_raw_for_edit()
        super().do_backspace(from_undo=from_undo, mode=mode)
        self._live_shape_after_edit()

    def _revert_to_raw_for_edit(self) -> None:
        if not self.auto_shape_display or not self._showing_shaped:
            return
        self._set_text_silently(self._raw_value)
        self._showing_shaped = False
        # موقعیتِ مکان‌نما در رشته‌ی shape‌شده (بازچینی‌شده) هیچ تناظرِ
        # ساده‌ای با موقعیتِ منطقی ندارد؛ چون فیلدهای این‌جا (شرح/نام) معمولاً
        # پشتِ‌سرهم تایپ می‌شوند نه ویرایشِ میان‌متن، فرض می‌کنیم ادامه‌ی تایپ
        # از انتهای متنِ خام است.
        self.cursor = (len(self._raw_value), 0)

    def _live_shape_after_edit(self) -> None:
        # برخلافِ _apply_shaped_display (که فقط هنگامِ از‌دست‌دادنِ فوکوس صدا
        # زده می‌شود)، این تابع بعدِ *هر* کلیدِ تایپ‌شده هم صدا زده می‌شود —
        # چون بدونِ آن، درحینِ تایپ متنِ فارسی کاملاً وارونه/نامرتب دیده
        # می‌شد (نه فقط در حالتِ پرشده‌ی برنامه‌ای)؛ طبق گزارشِ مستقیمِ کاربر.
        if not self.auto_shape_display:
            return
        from peecha.ui.rtl import shape  # noqa: PLC0415

        raw = self.text
        shaped = shape(raw)
        if shaped != raw:
            self._set_text_silently(shaped)
            self._raw_value = raw
            self._showing_shaped = True
            # بعدِ بازچینیِ بصری، کاراکترِ تازه‌تایپ‌شده اولِ رشته (سمتِ چپِ
            # صفحه) قرار می‌گیرد؛ مکان‌نما را همان‌جا می‌گذاریم تا تایپِ بعدی
            # (که دوباره به انتهای متنِ خام می‌چسبد) از نظرِ بصری پشتِ‌سرهم
            # به‌نظر برسد.
            self.cursor = (0, 0)

    def _apply_shaped_display(self) -> None:
        if not self.auto_shape_display or self._showing_shaped or not self.text:
            return
        from peecha.ui.rtl import shape  # noqa: PLC0415 - جلوگیریِ وابستگیِ چرخه‌ای در import سطح‌ماژول

        shaped = shape(self.text)
        if shaped != self.text:
            raw = self.text
            self._set_text_silently(shaped)
            self._raw_value = raw
            self._showing_shaped = True

    def _set_text_silently(self, value: str) -> None:
        """`.text` را عوض می‌کند بدونِ این‌که _track_raw_value آن را به‌عنوانِ
        مقدارِ منطقیِ تازه ثبت کند (چون این تغییر خودِ ما هستیم، نه ورودیِ
        بیرونی/کاربر)."""
        self._suppress_raw_tracking = True
        self.text = value
        self._suppress_raw_tracking = False

    @property
    def value(self) -> str:
        """مقدارِ منطقی (بدونِ شکل‌دهیِ نمایشی) — همیشه این باید برای
        ذخیره‌سازی/پردازش خوانده شود، نه `.text`."""
        return self._raw_value

    def set_value(self, raw_value: str) -> None:
        """پرکردنِ برنامه‌ایِ فیلد با یک مقدارِ منطقیِ از پیش‌آماده (مثلاً
        حالتِ ویرایش) — برخلافِ `self.text = raw_value` مستقیم، اگر فیلد
        همین الان فوکوس نداشته باشد بلافاصله نسخه‌ی shape‌شده (خوانا) نمایش
        داده می‌شود."""
        self._raw_value = raw_value
        self._showing_shaped = False
        self.text = raw_value
        if not self.focus:
            self._apply_shaped_display()


class PNavItem(PressFeedbackBehavior, ButtonBehavior, MDBoxLayout):
    """آیتم منوی نوار کناری — طبق docs/ui-ux-guidelines.md بخش ۵/۱۰.

    sub=True یعنی این یک زیرآیتمِ تورفته‌ی یک گروه است (مثل «کدینگ
    حسابداری» زیر «مالی و حسابداری»)، نه یک ماژول سطح‌بالا."""

    icon = StringProperty("circle-outline")
    text = StringProperty("")
    selected = BooleanProperty(False)
    sub = BooleanProperty(False)


class PNavGroupLabel(PressFeedbackBehavior, ButtonBehavior, MDBoxLayout):
    """سرآیتمِ یک گروه در نوار کناری (مثل «مالی و حسابداری») — قابل‌کلیک
    برای جمع‌کردن/بازکردنِ زیرآیتم‌هایش (طبق درخواستِ صریح: زیرمجموعه‌ی هر
    گروه وقتی باز نیست باید جمع‌شونده باشد، نه همیشه نمایان)."""

    icon = StringProperty("circle-outline")
    text = StringProperty("")
    expanded = BooleanProperty(False)


class PSelectField(PressFeedbackBehavior, KeyboardActivatedButtonBehavior, ButtonBehavior, MDBoxLayout):
    """فیلدِ انتخابی (بازکننده‌ی منوی کشویی) — با Tab قابل‌رسیدن و با
    Enter/Space قابل‌بازشدن، تا انتخاب از منو هم بدون ماوس ممکن باشد."""

    text = StringProperty("")


class PRaisedButton(PressFeedbackBehavior, KeyboardActivatedButtonBehavior, MDRaisedButton):
    """دکمه‌ی اصلیِ فرم‌ها — MDRaisedButton خودش FocusBehavior ندارد (تست
    مستقیم تایید کرد)، پس با Tab قابل‌رسیدن نبود و نمی‌شد focus_next یک
    فیلد دیگر را به آن وصل کرد؛ این mixin هم قابل‌فوکوس‌شدن و هم فعال‌سازی
    با Enter/Space را اضافه می‌کند."""


class PFlatButton(PressFeedbackBehavior, KeyboardActivatedButtonBehavior, MDFlatButton):
    """دکمه‌ی ثانویه — همان قابلیتِ کیبوردِ PRaisedButton."""


class PLabelListRow(MDBoxLayout):
    """یک ردیف ساده‌ی متنی راست‌چین برای فهرست‌ها (مثلاً کدینگ حسابداری)."""

    text = StringProperty("")
    zebra = BooleanProperty(False)


class PEmptyState(MDBoxLayout):
    """حالت خالیِ یک لیست/گرید: آیکون بزرگِ کم‌رنگ + یک خط توضیح."""

    icon = StringProperty("information-outline")
    text = StringProperty("")


class PBadge(MDBoxLayout):
    """نشانِ کوچکِ رنگی (سطح/وضعیت/...) — طبق docs/ui-ux-guidelines.md بخش ۲۰."""

    text = StringProperty("")
    badge_color = ListProperty([0.145, 0.388, 0.922, 1])


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


class PDropdownItem(BaseDropdownItem):
    """آیتمِ منوی کشویی با متنِ راست‌چین. MDDropdownTextItem خودِ KivyMD
    همیشه چپ‌چین است (با خواندنِ مستقیمِ menu.kv پیدا شد: MDLabelِ داخلی‌اش
    هیچ‌وقت halign نمی‌گیرد و هیچ property عمومی برای override هم ندارد).
    این‌جا مستقیم از BaseDropdownItem (بدونِ فرزند) ارث می‌بریم، نه از
    MDDropdownTextItem — وگرنه چون خودِ MDDropdownTextItem هم یک KV rule
    با یک MDLabelِ مستقلِ دیگر دارد، دو لیبل روی هم می‌افتند (تستِ مستقیم
    این را تایید کرد)."""


def open_rtl_dropdown(caller, items: list[dict], width_mult: int = 3) -> MDDropdownMenu:
    """جایگزینِ ساختِ مستقیمِ MDDropdownMenu در همه‌جای برنامه — همان
    فرمتِ همیشگیِ items (دیکشنری‌های {"text":..., "on_release":...}) را
    می‌گیرد، فقط viewclass را به PDropdownItem (راست‌چین) تنظیم می‌کند."""
    for item in items:
        item.setdefault("viewclass", "PDropdownItem")
    menu = MDDropdownMenu(caller=caller, items=items, width_mult=width_mult)
    menu.open()
    return menu


Factory.register("PCard", cls=PCard)
Factory.register("PDropdownItem", cls=PDropdownItem)
Factory.register("PTextField", cls=PTextField)
Factory.register("PNavItem", cls=PNavItem)
Factory.register("PNavGroupLabel", cls=PNavGroupLabel)
Factory.register("PSelectField", cls=PSelectField)
Factory.register("PRaisedButton", cls=PRaisedButton)
Factory.register("PFlatButton", cls=PFlatButton)
Factory.register("PLabelListRow", cls=PLabelListRow)
Factory.register("PEmptyState", cls=PEmptyState)
Factory.register("PBadge", cls=PBadge)
Factory.register("PStatCard", cls=PStatCard)
Factory.register("LineAreaChart", cls=LineAreaChart)
Factory.register("DonutChart", cls=DonutChart)
