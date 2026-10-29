"""R363: نمودار گانت پروژه (راست به چپ): زمان از راست به چپ جلو می‌رود، فعالیت بحرانی قرمز، فاز نوار تیره، نقطهٔ عطف
لوزی، خط مبنا نوار خاکستری زیر هر فعالیت، روزهای تعطیل سایه‌دار و امروز خط عمودی."""

from __future__ import annotations

import datetime

import jdatetime
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtWidgets import QToolTip, QWidget

from peecha import numerals
from peecha.ui import theme

_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
ZOOMS = {"DAY": ("روزانه", 22), "WEEK": ("هفتگی", 9), "MONTH": ("ماهانه", 3)}


def _c(token: str) -> QColor:
    return QColor(getattr(theme, token))


class GanttChart(QWidget):
    NAMES_W = 260
    ROW_H = 26
    HEADER_H = 46

    def __init__(self) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.schedule = None
        self.px = ZOOMS["DAY"][1]
        self.today = datetime.date.today()
        self.origin = self.today
        self.days = 1
        self.setMouseTracking(True)

    def set_zoom(self, code: str) -> None:
        self.px = ZOOMS[code][1]
        self._layout()

    def set_schedule(self, schedule, today: datetime.date | None = None) -> None:
        self.schedule = schedule
        self.today = today or datetime.date.today()
        self._layout()

    def _layout(self) -> None:
        s = self.schedule
        if s is None or not s.tasks:
            self.setMinimumSize(400, 120)
            self.update()
            return
        firsts = [s.start] + [t.baseline_start for t in s.tasks if t.baseline_start]
        lasts = [s.finish, self.today] + [t.baseline_finish for t in s.tasks if t.baseline_finish]
        self.origin = min(firsts) - datetime.timedelta(days=3)
        self.days = (max(lasts) - self.origin).days + 8
        self.setMinimumSize(self.NAMES_W + self.days * self.px + 16, self.HEADER_H + len(s.tasks) * self.ROW_H + 8)
        self.update()

    def x_of(self, d: datetime.date) -> float:
        """لبهٔ راست خانهٔ روز d."""
        return self.width() - self.NAMES_W - (d - self.origin).days * self.px

    def row_at(self, y: float):
        if self.schedule is None or y < self.HEADER_H:
            return None
        i = int((y - self.HEADER_H) // self.ROW_H)
        return self.schedule.tasks[i] if 0 <= i < len(self.schedule.tasks) else None

    def event(self, ev) -> bool:  # noqa: D401
        if ev.type() == QEvent.ToolTip:
            t = self.row_at(ev.pos().y())
            if t is not None:
                text = (f"{t.wbs} {t.name}\nشروع: {numerals.format_jalali_date(t.start)}   پایان: {numerals.format_jalali_date(t.finish)}\n"
                        f"پیشرفت: {t.percent.normalize():f}٪   شناوری: {t.total_float} روز" + ("   (بحرانی)" if t.critical else ""))
                QToolTip.showText(ev.globalPos(), numerals.to_persian_digits(text), self)
            else:
                QToolTip.hideText()
            return True
        return super().event(ev)

    def _text_right(self, p: QPainter, right: float, baseline: float, text: str) -> None:
        p.drawText(QPointF(right - p.fontMetrics().horizontalAdvance(text), baseline), text)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), _c("SURFACE"))
        s = self.schedule
        if s is None or not s.tasks:
            p.setPen(_c("TEXT_SECONDARY"))
            self._text_right(p, self.width() - 16, 40, "فعالیتی برای نمایش نیست.")
            p.end()
            return
        w, rh, top = self.width(), self.ROW_H, self.HEADER_H
        chart_right = w - self.NAMES_W
        height = top + len(s.tasks) * rh
        cal = s.calendar
        # روزهای تعطیل و سرستون ماه و روز
        p.setPen(Qt.NoPen)
        for k in range(self.days):
            d = self.origin + datetime.timedelta(days=k)
            x = self.x_of(d)
            if cal is not None and not cal.is_working(d):
                p.fillRect(QRectF(x - self.px, top, self.px, height - top), _c("GRID_ROW_ALT"))
        for i in range(len(s.tasks)):
            if i % 2:
                p.fillRect(QRectF(0, top + i * rh, w, rh), _c("GRID_ROW_ALT"))
        p.fillRect(QRectF(0, 0, w, top), _c("GRID_HEADER_BG"))
        for k in range(self.days):
            d = self.origin + datetime.timedelta(days=k)
            j = jdatetime.date.fromgregorian(date=d)
            x = self.x_of(d)
            if j.day == 1 or k == 0:
                p.setPen(_c("BORDER"))
                p.drawLine(QPointF(x, 0), QPointF(x, height))
                p.setPen(_c("TEXT_PRIMARY"))
                self._text_right(p, x - 4, 17, numerals.to_persian_digits(f"{_MONTHS[j.month - 1]} {j.year}"))
            if self.px >= 14:
                p.setPen(_c("TEXT_SECONDARY"))
                label = numerals.to_persian_digits(str(j.day))
                p.drawText(QPointF(x - self.px / 2 - p.fontMetrics().horizontalAdvance(label) / 2, 39), label)
            elif self.px >= 6 and d.weekday() == 5:
                p.setPen(_c("DIVIDER"))
                p.drawLine(QPointF(x, top), QPointF(x, height))
        p.setPen(_c("BORDER"))
        p.drawLine(QPointF(0, top), QPointF(w, top))
        p.drawLine(QPointF(chart_right, 0), QPointF(chart_right, height))
        # امروز
        tx = self.x_of(self.today) - self.px / 2
        p.setPen(_c("WARNING"))
        p.drawLine(QPointF(tx, top), QPointF(tx, height))
        for i, t in enumerate(s.tasks):
            y = top + i * rh
            p.setPen(_c("DANGER") if t.critical and not t.is_summary else _c("TEXT_PRIMARY"))
            name = numerals.to_persian_digits(f"{t.wbs}  {t.name}")
            font = p.font()
            font.setBold(t.is_summary)
            p.setFont(font)
            right = w - 8 - t.level * 14
            name = p.fontMetrics().elidedText(name, Qt.ElideLeft, int(right - chart_right - 8))
            self._text_right(p, right, y + rh * 0.68, name)
            font.setBold(False)
            p.setFont(font)
            if t.baseline_start and t.baseline_finish and not t.is_summary:
                bx0, bx1 = self.x_of(t.baseline_finish) - self.px, self.x_of(t.baseline_start)
                p.fillRect(QRectF(bx0, y + rh - 7, max(bx1 - bx0, 2), 3), _c("TEXT_DISABLED"))
            x0, x1 = self.x_of(t.finish) - self.px, self.x_of(t.start)
            if t.is_summary:
                p.setPen(Qt.NoPen)
                p.setBrush(_c("TEXT_PRIMARY"))
                p.drawRect(QRectF(x0, y + 8, x1 - x0, 6))
                for edge in (x0, x1 - 5):
                    p.drawPolygon(QPolygonF([QPointF(edge, y + 14), QPointF(edge + 5, y + 14), QPointF(edge + 2.5, y + 19)]))
            elif t.is_milestone:
                cx, cy = x1 - self.px / 2, y + rh / 2 - 1
                p.setPen(Qt.NoPen)
                p.setBrush(_c("DANGER") if t.critical else _c("INFO"))
                p.drawPolygon(QPolygonF([QPointF(cx, cy - 7), QPointF(cx + 7, cy), QPointF(cx, cy + 7), QPointF(cx - 7, cy)]))
            else:
                bar = QRectF(x0, y + 6, max(x1 - x0, 3), 12)
                color = _c("DANGER") if t.critical else _c("ACCENT")
                faded = QColor(color)
                faded.setAlpha(110)
                p.setPen(Qt.NoPen)
                p.setBrush(faded)
                p.drawRoundedRect(bar, 3, 3)
                done = bar.width() * float(t.percent) / 100
                if done > 0:
                    p.setBrush(color)
                    p.drawRoundedRect(QRectF(bar.right() - done, bar.top(), done, bar.height()), 3, 3)
        p.end()
