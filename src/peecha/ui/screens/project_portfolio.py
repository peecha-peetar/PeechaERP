"""R366: سبد پروژه‌ها — پیشرفت، شاخص‌های ارزش کسب‌شده، هزینه، صورت‌وضعیت و درخواست تغییر همهٔ پروژه‌ها در یک جدول."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from peecha.services.projects import portfolio as pf
from peecha.ui import report_export, theme
from peecha.ui.screens.fixed_assets import P, company_id, fill, money, selected_data, table
from peecha.ui.widgets import KpiCard, build_page_header

_HEADERS = ["کد", "پروژه", "مدیر", "وضعیت", "سلامت", "پیشرفت", "برنامه", "شاخص زمان", "شاخص هزینه", "پایان برنامه", "پایان هدف",
            "مبلغ قرارداد", "بودجه", "ارزش کسب‌شده", "هزینهٔ واقعی", "برآورد تکمیل", "صورت‌وضعیت", "درخواست باز"]
_FILTERS = {"OPEN": ("پروژه‌های باز", ("PLANNING", "ACTIVE", "ON_HOLD")), "ALL": ("همهٔ پروژه‌ها", None)}
_HEALTH_COLOR = {"GREEN": "SUCCESS", "AMBER": "WARNING", "RED": "DANGER"}


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


def _pct(value) -> str:
    return P(f"{value.normalize():f}٪")


def _ratio(value) -> str:
    return P(f"{value:f}") if value is not None else "—"


class ProjectPortfolioScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.main_window = main_window
        self.rows: list = []
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "سبد پروژه‌ها", "وضعیت همهٔ پروژه‌ها در یک نگاه: پیشرفت واقعی در برابر برنامه، شاخص زمان و هزینه (ارزش کسب‌شده ÷ برنامه "
            "و ÷ هزینهٔ واقعی)، برآورد هزینهٔ تکمیل، صورت‌وضعیت و درخواست‌های تغییر باز. برای دیدن جزئیات روی پروژه دوبار کلیک کنید."))
        cards = QHBoxLayout()
        self.cards = {"count": KpiCard("پروژه‌ها", "📐", theme.ACCENT), "contract": KpiCard("جمع قرارداد", "📜", theme.CHART_PURPLE),
                      "ev": KpiCard("ارزش کسب‌شده", "📈", theme.SUCCESS), "ac": KpiCard("هزینهٔ واقعی", "💸", theme.WARNING),
                      "red": KpiCard("در خطر", "🚨", theme.DANGER)}
        for card in self.cards.values():
            cards.addWidget(card)
        layout.addLayout(cards)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("نمایش:"))
        self.filter_combo = QComboBox()
        for code, (label, _s) in _FILTERS.items():
            self.filter_combo.addItem(label, code)
        self.filter_combo.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.filter_combo)
        for label, glyph, slot in (("به‌روزرسانی", "🔄", self.refresh), ("چاپ سبد پروژه‌ها", "🖨️", self.print_portfolio),
                                   ("خروجی Excel سبد پروژه‌ها", "📊", self.export_portfolio),
                                   ("باز کردن پروژهٔ انتخاب‌شده", "📂", self.open_selected)):
            button = _btn(label, glyph)
            button.clicked.connect(slot)
            bar.addWidget(button)
        bar.addStretch(1)
        layout.addLayout(bar)
        self.table = table(_HEADERS)
        self.table.itemDoubleClicked.connect(lambda _item: self.open_selected())
        layout.addWidget(self.table, 1)
        note = QLabel("شاخص زیر ۱ یعنی عقب‌تر از برنامه یا پرهزینه‌تر از ارزش کار انجام‌شده. «در خطر»: پایان برنامه از پایان هدف "
                      "گذشته یا یکی از شاخص‌ها زیر ۰٫۹ است.")
        note.setWordWrap(True)
        note.setObjectName("mutedLabel")
        layout.addWidget(note)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.rows = pf.portfolio(cid, _FILTERS[self.filter_combo.currentData()][1])
        fill(self.table, [[r.code, r.name, r.manager or "—", r.status_label, pf.HEALTH[r.health], _pct(r.percent), _pct(r.planned_percent),
                           _ratio(r.spi), _ratio(r.cpi), r.finish or "—", r.target_end_date or "—", r.contract_amount, r.bac, r.ev, r.ac,
                           r.eac, r.billed, r.open_changes] for r in self.rows], [r.project_id for r in self.rows])
        for i, r in enumerate(self.rows):
            self.table.item(i, 4).setForeground(QColor(getattr(theme, _HEALTH_COLOR[r.health])))
        t = pf.totals(self.rows)
        self.cards["count"].set_value(P(t["count"]))
        self.cards["contract"].set_value(money(t["contract"]))
        self.cards["ev"].set_value(money(t["ev"]))
        self.cards["ac"].set_value(money(t["ac"]))
        self.cards["red"].set_value(P(t["red"]))

    def open_selected(self) -> bool:
        pid = selected_data(self.table)
        if pid is None or self.main_window is None:
            return False
        self.main_window.open_screen("PRJ_PROJECTS", then=lambda screen: screen.open_project(pid))
        return True

    def _report(self):
        rows = [[r.code, r.name, r.manager, r.status_label, pf.HEALTH[r.health], _pct(r.percent), _pct(r.planned_percent), _ratio(r.spi),
                 _ratio(r.cpi), r.finish or "—", r.target_end_date or "—", r.contract_amount, r.bac, r.ev, r.ac, r.eac, r.billed,
                 r.open_changes] for r in self.rows]
        return "سبد پروژه‌ها", _HEADERS, rows

    def print_portfolio(self) -> bool:
        if not self.rows:
            return False
        report_export.print_report(self, *self._report())
        return True

    def export_portfolio(self) -> bool:
        if not self.rows:
            return False
        report_export.export_report_excel(self, *self._report())
        return True
