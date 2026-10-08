"""کارتابل من — تنها جای دیدن و انجام کارهای کاربر (یکپارچه در R300).

همهٔ منابع کنار هم: تاییدها و کارهای گردش کار، کارتابل اسناد قبلی، مراحل منتظر اسناد خرید/فروش/انبار، پیگیری‌های
مشتری، مشتریان تازهٔ منتظر تایید و درخواست‌های در جریان خود کاربر. هر کار یک کارت گرافیکی است: آیکن و رنگ نوع کار،
جملهٔ «چه باید کرد»، نشان فوریت و مهلت، و نقطه‌های مرحله. منطق هر منبع در سرویس خودش است (services/workflow/inbox).

بازکردن سند مبدأ کارتابل اسناد: هر ماژول با register_open_handler یک ورودی این‌جا ثبت می‌کند.
"""

from __future__ import annotations

import datetime

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSplitter, QTextEdit,
    QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services.workflow import inbox, tasks
from peecha.ui import theme
from peecha.ui.screens import module_style as ms
from peecha.ui.screens.fixed_assets import P, combo, company_id, fill, table, user_id
from peecha.ui.screens.workflow_center import (
    _ask, _field_widget, _run, _warn, company_user_choices, open_work_item, path_html,
)

# طبقِ همان الگویِ registerِ سرویس — هر ماژولی که کارتابل برایش فعال
# می‌شود، فقط یک ورودی این‌جا اضافه می‌کند (form_code -> بازکردنِ سندِ
# مبدا در main_window، با همان الگویِ open_screen موجود).
_OPEN_HANDLERS: dict[str, callable] = {}


def register_open_handler(form_code: str, opener) -> None:
    """opener(main_window, source_record_id) -> None"""
    _OPEN_HANDLERS[form_code] = opener


# R226: نوعِ سند -> کدِ منو برایِ بازکردنِ خودِ سند
_TYPE_TO_NAV_CODE = {
    "SALES_ORDER": "SALES_ORDER", "SALES_PROFORMA": "SALES_PROFORMA", "SALES_INVOICE": "SALES_INVOICE",
    "SALES_RETURN": "SALES_RETURN", "PURCHASE_ORDER": "PURCH_ORDER", "PURCHASE_PROFORMA": "PURCH_PROFORMA",
    "PURCHASE_INVOICE": "PURCH_INVOICE", "PURCHASE_RETURN": "PURCH_RETURN",
    "CONSIGNMENT_IN": "PURCH_CONSIGNMENT_IN", "CONSIGNMENT_OUT": "SALES_CONSIGNMENT_OUT",
}


def open_cartable_source(main_window, form_code: str, source_record_id: int) -> bool:
    """R293: همان بازکردن سند مبدا کارتابل، قابل استفاده از «کارهای من»."""
    opener = _OPEN_HANDLERS.get(form_code)
    if opener is None or main_window is None:
        return False
    opener(main_window, source_record_id)
    return True


def open_operational_task(main_window, kind: str, document_type_code: str, document_id: int) -> bool:
    if main_window is None:
        return False
    if kind == "GOODS_RECEIPT":
        main_window.open_screen("PURCH_GOODS_RECEIPT")
        return True
    if kind == "INVENTORY_RESIDUAL":
        main_window.open_screen("INV_RESIDUAL_ADJUST")
        return True
    nav_code = _TYPE_TO_NAV_CODE.get(document_type_code)
    if nav_code is None:
        return False
    main_window.open_screen(nav_code, then=lambda screen: screen.edit_document(document_id))
    return True


# --- ظاهر کارت‌ها -------------------------------------------------------------------------------------------------
ms.ICONS.update({
    "تایید درخواست": ("✅", "primary"), "رد درخواست": ("❌", "danger"), "برگشت برای اصلاح": ("↩️", ""),
    "واگذاری به همکار": ("👥", ""), "یادداشت": ("💬", ""), "بازکردن سند": ("📂", ""), "تایید گروهی": ("☑️", ""),
    "تازه‌سازی": ("🔄", ""), "یادآوری به گیرنده": ("🔔", ""), "پس‌گرفتن درخواست": ("🚫", "danger"),
    "انجام کار": ("✔️", "primary"), "بازکردن پروندهٔ مشتری": ("👤", ""),
})

# نوع کار ← (آیکن، رنگ تم)
TONES = {"approve": ("🖊️", "INFO"), "task": ("📋", "CHART_TEAL"), "doc": ("📦", "CHART_PURPLE"),
         "followup": ("📞", "CHART_ORANGE"), "customer": ("👤", "SUCCESS"), "mine": ("📨", "ACCENT")}
DOC_GLYPHS = {"MANAGER_APPROVAL": "🖊️", "GOODS_RECEIPT": "📦", "PRE_SALES_WAREHOUSE": "🏬", "SETTLEMENT_APPROVAL": "💰",
              "CONVERT_TO_INVOICE": "🔁", "POST_ORDER": "📌", "INVENTORY_RESIDUAL": "🧮"}
_STEP_COLORS = {"done": "SUCCESS", "current": "INFO", "pending": "TEXT_DISABLED", "failed": "DANGER"}
VIEWS = [("همهٔ کارهای من", "ALL"), ("منتظر تایید من", "APPROVAL"), ("کارهای انجام‌دادنی", "TASK"), ("مراحل اسناد", "STEP"),
         ("پیگیری مشتری", "FOLLOWUP"), ("درخواست‌های من", "MINE")]
MAX_CARDS = 200


def _c(name: str) -> str:
    return getattr(theme, name, theme.ACCENT)


def _dt(value) -> str:
    return numerals.format_jalali_datetime(value) if value else ""


def urgency(item: inbox.WorkItem) -> str:
    """overdue | today | high | normal — رنگ نوار کنار کارت."""
    if item.is_overdue:
        return "overdue"
    if item.due_at and item.due_at.astimezone().date() <= datetime.date.today():
        return "today"
    if item.priority_code in ("HIGH", "CRITICAL"):
        return "high"
    return "normal"


_URGENCY_COLORS = {"overdue": "DANGER", "today": "WARNING", "high": "WARNING", "normal": "ACCENT"}


def due_text(item: inbox.WorkItem) -> str:
    if not item.due_at:
        return ""
    due = item.due_at.astimezone()
    if item.is_overdue:
        days = (datetime.datetime.now().astimezone() - due).days
        return f"⏰ {P(days)} روز گذشته" if days >= 1 else "⏰ گذشته از مهلت"
    if due.date() == datetime.date.today():
        return f"📌 موعد امروز {P(due.strftime('%H:%M'))}"
    return f"📅 موعد {numerals.format_jalali_date(due.date())}"


def _pill(text: str, color: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"QLabel {{ color: {color}; background-color: {theme.rgba(color, 0.12)}; border: 1px solid "
                        f"{theme.rgba(color, 0.35)}; border-radius: 9px; padding: 1px 8px; font-size: 11px; font-weight: 700; }}")
    return label


def _dots(path: list[tuple[str, str]]) -> QLabel:
    """نقطه‌های مرحله: ● انجام‌شده سبز، ● جاری آبی، ○ مانده خاکستری (برچسب‌ها در راهنمای کوتاه)."""
    parts = [f"<span style='color:{_c(_STEP_COLORS.get(state, 'TEXT_DISABLED'))}; font-size:14px'>"
             f"{'○' if state == 'pending' else '●'}</span>" for _label, state in path]
    label = QLabel(" ".join(parts))
    label.setTextFormat(Qt.RichText)
    label.setToolTip(" ← ".join(lbl for lbl, _s in path))
    return label


class WorkCard(QFrame):
    """یک کار در کارتابل: آیکن نوع کار، «چه باید کرد»، عنوان، فوریت و دکمه‌های همان کار."""

    def __init__(self, item: inbox.WorkItem, screen: "MyTasksScreen") -> None:
        super().__init__()
        self.item = item
        self.screen = screen
        self.setObjectName("workCard")
        self.setCursor(Qt.PointingHandCursor)
        glyph, tone_color = TONES.get(item.tone, ("📥", "ACCENT"))
        if item.tone == "doc":
            glyph = DOC_GLYPHS.get(item.extra.get("kind"), glyph)
        self.tone_color = _c(tone_color)
        self.edge_color = _c(_URGENCY_COLORS[urgency(item)])
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)

        self.check = QCheckBox()
        self.check.setToolTip("انتخاب برای تایید گروهی")
        self.check.setVisible(item.can_quick_decide and item.kind == "APPROVAL")
        row.addWidget(self.check, 0, Qt.AlignTop)

        icon = QLabel(glyph)
        icon.setFixedSize(44, 44)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(f"QLabel {{ font-size: 20px; border-radius: 22px; background-color: {theme.rgba(self.tone_color, 0.15)}; "
                           f"border: 1px solid {theme.rgba(self.tone_color, 0.4)}; }}")
        row.addWidget(icon, 0, Qt.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(2)
        self.action_label = QLabel(item.action or item.kind_label)
        self.action_label.setStyleSheet(f"color: {self.tone_color}; font-size: 13.5px; font-weight: 800;")
        body.addWidget(self.action_label)
        title = QLabel(P(item.title))
        title.setWordWrap(True)
        title.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;")
        body.addWidget(title)
        who = {"doc": "طرف حساب", "followup": "مشتری"}.get(item.tone, "درخواست‌کننده")
        meta = [f"{who}: {item.subtitle}" if item.subtitle and item.tone != "mine" else item.subtitle,
                item.extra.get("definition") or item.source_label, _dt(item.created_at)]
        meta_label = QLabel(P(" · ".join(m for m in meta if m)))
        meta_label.setWordWrap(True)
        meta_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11.5px;")
        body.addWidget(meta_label)
        if item.path or item.status_note:
            steps = QHBoxLayout()
            steps.setSpacing(6)
            if item.path:
                steps.addWidget(_dots(item.path))
            if item.step_no and item.step_total:
                steps.addWidget(QLabel(f"مرحلهٔ {P(item.step_no)} از {P(item.step_total)}"))
            if item.status_note:
                note = QLabel(P(item.status_note))
                note.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11.5px;")
                steps.addWidget(note)
            steps.addStretch(1)
            body.addLayout(steps)
        row.addLayout(body, 1)

        side = QVBoxLayout()
        side.setSpacing(4)
        badges = QHBoxLayout()
        badges.setSpacing(4)
        badges.addStretch(1)
        if item.priority_code in ("HIGH", "CRITICAL"):
            badges.addWidget(_pill(f"🔥 {item.priority_label}", _c("DANGER" if item.priority_code == "CRITICAL" else "WARNING")))
        due = due_text(item)
        if due:
            badges.addWidget(_pill(due, _c(_URGENCY_COLORS[urgency(item)] if urgency(item) != "normal" else "TEXT_SECONDARY")))
        badges.addWidget(_pill(item.kind_label, self.tone_color))
        side.addLayout(badges)
        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        buttons.addStretch(1)
        for label, slot in self._actions():
            b = ms.style_button(QPushButton(label))
            b.setFixedSize(34, 30)
            b.clicked.connect(lambda _c=False, s=slot: (self.screen.select_key(self.item.key), s()))
            buttons.addWidget(b)
        side.addLayout(buttons)
        row.addLayout(side)
        self.set_selected(False)

    def _actions(self) -> list[tuple[str, callable]]:
        s, it = self.screen, self.item
        if it.tone == "mine":
            return [("یادآوری به گیرنده", lambda: s.remind()), ("پس‌گرفتن درخواست", lambda: s.withdraw())]
        if it.kind == "APPROVAL" and it.can_quick_decide:
            return [("تایید درخواست", lambda: s.decide("APPROVE")), ("رد درخواست", lambda: s.reject_selected()),
                    ("بازکردن سند", lambda: s.open_selected())]
        if it.source == "WF" and it.kind == "TASK":
            return [("انجام کار", lambda: s.approve_selected()), ("بازکردن سند", lambda: s.open_selected())]
        if it.source == "CRM":
            return [("بازکردن پروندهٔ مشتری", lambda: s.open_selected())]
        return [("انجام کار", lambda: s.open_selected())]

    def set_selected(self, on: bool) -> None:
        border = _c("ACCENT") if on else theme.BORDER
        bg = theme.rgba(_c("ACCENT"), 0.07) if on else theme.SURFACE
        self.setStyleSheet(f"QFrame#workCard {{ background-color: {bg}; border: 1px solid {border}; "
                           f"border-right: 5px solid {self.edge_color}; border-radius: 10px; }}")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.screen.select_key(self.item.key)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.screen.select_key(self.item.key)
        self.screen.open_selected()
        super().mouseDoubleClickEvent(event)


class _CardClick(QObject):
    def __init__(self, parent, callback) -> None:
        super().__init__(parent)
        self.callback = callback

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.MouseButtonRelease:
            self.callback()
            return True
        return False


@ms.styled
class MyTasksScreen(QWidget):
    """کارتابل یکپارچه با کارت‌های گرافیکی و پنل جزئیات و تصمیم."""

    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None  # برای تست
        self.items: list[inbox.WorkItem] = []
        self.requests: list[inbox.WorkItem] = []
        self.shown: list[inbox.WorkItem] = []
        self.cards_by_key: dict[str, WorkCard] = {}
        self.current: dict | None = None
        self.last_message = ""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)

        title = QLabel("کارتابل من")
        title.setObjectName("pageTitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو در عنوان یا نام…")
        self.search.textChanged.connect(lambda _t: self.apply_filter())
        self.view = QComboBox()
        for label, code in VIEWS:
            self.view.addItem(label, code)
        self.view.currentIndexChanged.connect(lambda _i: self.apply_filter())
        self.source = combo([(label, code) for code, label in inbox.SOURCES.items() if code != "MINE"], "همهٔ بخش‌ها")
        self.source.currentIndexChanged.connect(lambda _i: self.apply_filter())
        self.overdue_only = QCheckBox("فقط عقب‌افتاده‌ها")
        self.overdue_only.toggled.connect(lambda _c: self.apply_filter())
        outer.addWidget(ms.header_card(title, self.search, self.view, self.source, self.overdue_only))

        cards, self.cards = ms.summary([
            ("total", "همهٔ کارهای من", "info", "📥"), ("approvals", "منتظر تایید من", "warning", "🖊️"),
            ("overdue", "عقب‌افتاده", "danger", "⏰"), ("today", "موعد امروز", "neutral", "📌"),
            ("behalf", "به جای همکار", "neutral", "🤝"), ("mine", "درخواست‌های در جریان من", "info", "📨")], per_row=6)
        outer.addWidget(cards)
        for key, action in (("total", lambda: self._quick_view("ALL")), ("approvals", lambda: self._quick_view("APPROVAL")),
                            ("overdue", lambda: self._quick_view("ALL", overdue=True)), ("mine", lambda: self._quick_view("MINE"))):
            card = self.cards[key].parent()
            card.setCursor(Qt.PointingHandCursor)
            card.setToolTip("برای دیدن همین کارها بزنید")
            card.installEventFilter(_CardClick(card, action))

        legend = QLabel(f"<span style='color:{_c('DANGER')}'>▌</span> عقب‌افتاده   "
                        f"<span style='color:{_c('WARNING')}'>▌</span> موعد امروز یا فوری   "
                        f"<span style='color:{_c('ACCENT')}'>▌</span> عادی   —   "
                        "روی هر کارت بزنید تا جزئیات و دکمه‌های تصمیم کنارش بیاید؛ دوبار زدن، خود سند را باز می‌کند.")
        legend.setTextFormat(Qt.RichText)
        legend.setObjectName("sectionHint")
        legend.setWordWrap(True)
        outer.addWidget(legend)

        split = QSplitter(Qt.Horizontal)
        self.list_area = QScrollArea()
        self.list_area.setWidgetResizable(True)
        self.list_area.setFrameShape(QFrame.NoFrame)
        self.list_box = QWidget()
        self.list_layout = QVBoxLayout(self.list_box)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(8)
        self.list_area.setWidget(self.list_box)
        split.addWidget(self.list_area)

        side = QWidget()
        side.setObjectName("card")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(10, 8, 10, 8)
        self.d_title = QLabel("یک کار را انتخاب کنید")
        self.d_title.setObjectName("sectionTitle")
        self.d_title.setWordWrap(True)
        self.d_info = QLabel("")
        self.d_info.setWordWrap(True)
        self.d_path = QLabel("")
        self.d_path.setTextFormat(Qt.RichText)
        self.d_path.setWordWrap(True)
        self.d_context = table(["عنوان", "مقدار"])
        self.d_context.setMaximumHeight(230)
        self.d_history = table(["زمان", "کاربر", "اقدام", "توضیح"])
        self.d_history.setMaximumHeight(200)
        self.comment = QTextEdit()
        self.comment.setPlaceholderText("توضیح تصمیم (برای رد و برگشت برای اصلاح الزامی است)")
        self.comment.setMaximumHeight(80)
        for w in (self.d_title, self.d_info, self.d_path, QLabel("اطلاعات کلیدی"), self.d_context, QLabel("تاریخچه"),
                  self.d_history, self.comment):
            sl.addWidget(w)
        sl.addStretch(1)
        split.addWidget(side)
        self.list_area.setMinimumWidth(520)
        side.setMinimumWidth(340)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([860, 480])
        outer.addWidget(split, stretch=1)

        self.buttons = {k: QPushButton(t) for k, t in (
            ("approve", "تایید درخواست"), ("reject", "رد درخواست"), ("changes", "برگشت برای اصلاح"),
            ("delegate", "واگذاری به همکار"), ("note", "یادداشت"), ("open", "بازکردن سند"), ("bulk", "تایید گروهی"),
            ("remind", "یادآوری به گیرنده"), ("withdraw", "پس‌گرفتن درخواست"), ("refresh", "تازه‌سازی"))}
        self.buttons["approve"].clicked.connect(lambda: self.approve_selected())
        self.buttons["reject"].clicked.connect(lambda: self.reject_selected())
        self.buttons["changes"].clicked.connect(lambda: self.decide("CHANGES"))
        self.buttons["delegate"].clicked.connect(lambda: self.delegate())
        self.buttons["note"].clicked.connect(lambda: self.add_note())
        self.buttons["open"].clicked.connect(lambda: self.open_selected())
        self.buttons["bulk"].clicked.connect(lambda: self.bulk_approve())
        self.buttons["remind"].clicked.connect(lambda: self.remind())
        self.buttons["withdraw"].clicked.connect(lambda: self.withdraw())
        self.buttons["refresh"].clicked.connect(lambda: self.reload())
        B = self.buttons
        outer.addWidget(ms.footer([[B["approve"], B["reject"], B["changes"]], [B["delegate"], B["note"], B["open"]],
                                   [B["bulk"]], [B["remind"], B["withdraw"]], [B["refresh"]]]))
        self._update_buttons(None)

    # --- داده ---------------------------------------------------------------------------------------------------
    def refresh(self) -> None:
        self.reload()

    def reload(self) -> None:
        if company_id() is None or user_id() is None:
            return
        self.items = inbox.my_work(company_id(), user_id())
        self.requests = inbox.my_requests(company_id(), user_id())
        s = inbox.summarize(self.items)
        for key, value in (("total", s.total), ("approvals", s.approvals), ("overdue", s.overdue), ("today", s.due_today),
                           ("behalf", s.on_behalf), ("mine", len(self.requests))):
            self.cards[key].setText(P(value))
        self.apply_filter()

    def _quick_view(self, code: str, overdue: bool = False) -> None:
        self.overdue_only.blockSignals(True)
        self.overdue_only.setChecked(overdue)
        self.overdue_only.blockSignals(False)
        self.set_view(code)

    def _reset_filters(self, view: str) -> None:
        for w in (self.search, self.source, self.overdue_only, self.view):
            w.blockSignals(True)
        self.search.clear()
        self.source.setCurrentIndex(0)
        self.overdue_only.setChecked(False)
        self.view.setCurrentIndex(max(0, self.view.findData(view)))
        for w in (self.search, self.source, self.overdue_only, self.view):
            w.blockSignals(False)
        self.apply_filter()

    def set_view(self, code: str) -> None:
        index = self.view.findData(code)
        if index == self.view.currentIndex():
            self.apply_filter()
        else:
            self.view.setCurrentIndex(max(0, index))

    def apply_filter(self) -> None:
        view, src, text = self.view.currentData(), self.source.currentData(), self.search.text().strip()
        pool = self.requests if view == "MINE" else self.items
        self.shown = [w for w in pool if (view in ("ALL", "MINE") or w.kind == view) and (view == "MINE" or not src or w.source == src)
                      and (not self.overdue_only.isChecked() or w.is_overdue)
                      and (not text or text in w.title or text in w.subtitle)]
        self._render()

    def _render(self) -> None:
        keep = self.current["key"] if self.current else None
        while self.list_layout.count():
            child = self.list_layout.takeAt(0)
            if child.widget():
                w = child.widget()
                w.hide()  # تا حذف واقعی، کارت قبلی روی فهرست تازه دیده نشود
                w.setParent(None)
                w.deleteLater()
        self.cards_by_key = {}
        if not self.shown:
            empty = QLabel("درخواست در جریانی ندارید." if self.view.currentData() == "MINE" else "🎉 کاری منتظر شما نیست.")
            empty.setObjectName("sectionHint")
            empty.setAlignment(Qt.AlignCenter)
            self.list_layout.addWidget(empty)
        groups = [("📨 درخواست‌های در جریان من", self.shown)] if self.view.currentData() == "MINE" else [
            ("⏰ عقب‌افتاده", [w for w in self.shown if urgency(w) == "overdue"]),
            ("📌 موعد امروز", [w for w in self.shown if urgency(w) == "today"]),
            ("📥 بقیهٔ کارها", [w for w in self.shown if urgency(w) in ("high", "normal")])]
        count = 0
        for heading, group in groups:
            if not group:
                continue
            label = QLabel(f"{heading} ({P(len(group))})")
            label.setObjectName("sectionTitle")
            self.list_layout.addWidget(label)
            for item in group:
                if count >= MAX_CARDS:
                    break
                card = WorkCard(item, self)
                self.cards_by_key[item.key] = card
                self.list_layout.addWidget(card)
                count += 1
        if len(self.shown) > MAX_CARDS:
            more = QLabel(f"{P(len(self.shown) - MAX_CARDS)} کار دیگر هم هست؛ با جستجو یا فیلتر پیدایش کنید.")
            more.setObjectName("sectionHint")
            self.list_layout.addWidget(more)
        self.list_layout.addStretch(1)
        self.current = None
        if keep and keep in self.cards_by_key:
            self.select_key(keep)
        elif self.shown:
            self.select_key(self.shown[0].key)
        else:
            self._show_detail(None)

    def _item(self, key: str | None) -> inbox.WorkItem | None:
        return next((w for w in self.shown if w.key == key), None) if key else None

    def selected_item(self) -> inbox.WorkItem | None:
        return self._item(self.current["key"]) if self.current else None

    def select_key(self, key: str) -> bool:
        item = self._item(key)
        if item is None:
            # مورد زیر فیلتر دیگری است (مثلاً از اعلان): فیلترها برداشته می‌شود
            in_mine = any(w.key == key for w in self.requests)
            if not in_mine and not any(w.key == key for w in self.items):
                return False
            self._reset_filters("MINE" if in_mine else "ALL")
            item = self._item(key)
        if item is None:
            return False
        for k, card in self.cards_by_key.items():
            card.set_selected(k == key)
        try:
            self.current = {"key": key, **inbox.detail(company_id(), user_id(), key)}
        except ValueError as exc:
            self.current = {"key": key, "title": str(exc), "requester": "", "context": [], "path": [], "history": [],
                            "decisions": [], "due_at": None, "sla": "", "instructions": "", "row_version": None}
        self._show_detail(self.current)
        card = self.cards_by_key.get(key)
        if card is not None:
            self.list_area.ensureWidgetVisible(card)
        return True

    def _show_detail(self, d: dict | None) -> None:
        if d is None:
            self.d_title.setText("یک کار را انتخاب کنید")
            for w in (self.d_info, self.d_path):
                w.setText("")
            fill(self.d_context, [])
            fill(self.d_history, [])
            self._update_buttons(None)
            return
        item = self._item(d["key"])
        self.d_title.setText(P(f"{item.action}: {d['title']}" if item and item.action else d["title"]))
        who = {"doc": "طرف حساب", "followup": "مشتری"}.get(item.tone if item else "", "درخواست‌کننده")
        info = [f"{who}: {d['requester']}"] if d.get("requester") else []
        if d.get("due_at"):
            info.append(f"موعد: {_dt(d['due_at'])}")
        if d.get("sla"):
            info.append(d["sla"])
        if d.get("instructions"):
            info.append(d["instructions"])
        self.d_info.setText(P(" — ".join(info)))
        self.d_path.setText(path_html(d.get("path") or []))
        fill(self.d_context, [[k, v] for k, v in d.get("context") or []])
        fill(self.d_history, [[_dt(at), who, what, note] for at, who, what, note in d.get("history") or []])
        self._update_buttons(item, {code for code, _l in d.get("decisions") or []})

    def _update_buttons(self, item: inbox.WorkItem | None, allowed: set[str] | None = None) -> None:
        allowed = allowed or set()
        decidable = bool(item) and item.can_quick_decide
        task = bool(item) and item.source == "WF" and item.kind == "TASK"
        mine = bool(item) and item.source == "MINE"
        self.buttons["approve"].setEnabled(decidable or task)
        self.buttons["reject"].setEnabled(decidable)
        self.buttons["changes"].setEnabled(decidable and "CHANGES" in allowed)
        self.buttons["delegate"].setEnabled(bool(item) and item.source == "WF")
        self.buttons["note"].setEnabled(bool(item) and item.source == "WF")
        self.buttons["open"].setEnabled(bool(item))
        self.buttons["bulk"].setEnabled(any(w.can_quick_decide and w.kind == "APPROVAL" for w in self.shown))
        self.buttons["remind"].setEnabled(mine and bool(item.extra.get("open_task_ids")))
        self.buttons["withdraw"].setEnabled(mine)

    def _require(self) -> inbox.WorkItem | None:
        item = self.selected_item()
        if item is None:
            _warn(self, "کارتابل من", "یک کار را انتخاب کنید.")
        return item

    # --- کارها --------------------------------------------------------------------------------------------------
    def open_selected(self) -> bool:
        item = self._require()
        if item is None:
            return False
        if item.source == "MINE":
            from peecha.ui.screens.workflow_center import open_entity

            return open_entity(self._main_window, item.extra.get("entity_type"), item.extra.get("entity_id"))
        if item.source == "CUSTOMER":
            from peecha.ui.screens.workflow_center import open_entity

            return open_entity(self._main_window, "CUSTOMER", item.ref_id)
        return open_work_item(self._main_window, item)

    def approve_selected(self, comment: str | None = None) -> bool:
        item = self._require()
        if item is None:
            return False
        if item.source == "WF" and item.kind == "TASK":
            return self.complete_task(item)
        if not item.can_quick_decide:
            return self.open_selected()
        return self.decide("APPROVE", comment)

    def reject_selected(self, comment: str | None = None) -> bool:
        item = self._require()
        if item is None:
            return False
        if not item.can_quick_decide:
            _warn(self, "رد", "این مورد تصمیم سریع ندارد؛ سند را باز کنید.")
            return False
        if comment is None:
            comment = self.comment.toPlainText().strip()
        if not comment:
            values = _ask(self, "رد درخواست", [("comment", "علت رد", QTextEdit())], "علت رد برای درخواست‌کننده فرستاده می‌شود.")
            if values is None:
                return False
            comment = values.get("comment") or ""
        return self.decide("REJECT", comment)

    def decide(self, decision: str, comment: str | None = None) -> bool:
        item = self._require()
        if item is None:
            return False
        comment = self.comment.toPlainText().strip() if comment is None else comment
        msg, ok = _run(self, "کارتابل من", inbox.quick_decide, company_id(), user_id(), item.key, decision, comment,
                       row_version=(self.current or {}).get("row_version"))
        if ok:
            self.comment.clear()
            self.last_message = msg
            self.current = None
            self.reload()
        return ok

    def complete_task(self, item: inbox.WorkItem, values: dict | None = None) -> bool:
        detail = tasks.task_detail(company_id(), item.ref_id, user_id())
        if values is None:
            fields = [(f["key"], f.get("label") or f["key"], _field_widget(f)) for f in detail.form_fields]
            fields.append(("__comment", "توضیح", QTextEdit()))
            values = _ask(self, f"انجام کار: {detail.row.title}", fields, detail.row.instructions)
            if values is None:
                return False
        comment = values.pop("__comment", "") or ""
        _r, ok = _run(self, "انجام کار", tasks.decide, company_id(), item.ref_id, user_id(), "DONE", comment,
                      data=values, row_version=detail.row.row_version)
        if ok:
            self.current = None
            self.reload()
        return ok

    def checked_keys(self) -> list[str]:
        return [k for k, card in self.cards_by_key.items() if not card.check.isHidden() and card.check.isChecked()]

    def bulk_approve(self, keys: list[str] | None = None) -> list:
        keys = keys or self.checked_keys()
        if not keys:
            _warn(self, "تایید گروهی", "تیک کارهایی را که می‌خواهید با هم تایید شوند بزنید.")
            return []
        results = inbox.bulk_approve(company_id(), user_id(), keys, self.comment.toPlainText().strip())
        failed = [m for _k, ok, m in results if not ok]
        if failed:
            _warn(self, "تایید گروهی", f"{P(len(results) - len(failed))} مورد تایید شد؛ این موارد انجام نشد:\n" + "\n".join(failed))
        self.comment.clear()
        self.current = None
        self.reload()
        return results

    def delegate(self, to_user_id: int | None = None) -> bool:
        item = self._require()
        if item is None or item.source != "WF":
            return False
        if to_user_id is None:
            values = _ask(self, "واگذاری به همکار", [("to", "همکار", combo(company_user_choices()))],
                          "سهم شما از این کار به همکار انتخاب‌شده سپرده می‌شود.")
            if values is None:
                return False
            to_user_id = values["to"]
        _r, ok = _run(self, "واگذاری", tasks.delegate_task, company_id(), item.ref_id, user_id(), to_user_id,
                      self.comment.toPlainText().strip())
        if ok:
            self.comment.clear()
            self.current = None
            self.reload()
        return ok

    def add_note(self, text: str | None = None) -> bool:
        item = self._require()
        if item is None or item.source != "WF":
            return False
        text = self.comment.toPlainText().strip() if text is None else text
        _r, ok = _run(self, "یادداشت", tasks.add_comment, company_id(), item.ref_id, user_id(), text)
        if ok:
            self.comment.clear()
            self.select_key(item.key)
        return ok

    def remind(self, note: str | None = None) -> int:
        item = self._require()
        if item is None or item.source != "MINE":
            return 0
        note = self.comment.toPlainText().strip() if note is None else note
        n, ok = _run(self, "یادآوری", inbox.remind, company_id(), user_id(), item.key, note)
        if ok:
            self.comment.clear()
            self.last_message = f"یادآوری برای {P(n)} نفر فرستاده شد."
        return n or 0

    def withdraw(self, reason: str | None = None) -> bool:
        item = self._require()
        if item is None or item.source != "MINE":
            return False
        if reason is None:
            values = _ask(self, "پس‌گرفتن درخواست", [("reason", "دلیل", QLineEdit())],
                          "کارهای باز این درخواست بسته می‌شوند؛ خود سند تغییری نمی‌کند.")
            if values is None:
                return False
            reason = values.get("reason") or ""
        _r, ok = _run(self, "پس‌گرفتن درخواست", inbox.withdraw, company_id(), user_id(), item.key, reason)
        if ok:
            self.current = None
            self.reload()
        return ok


CartableScreen = MyTasksScreen
