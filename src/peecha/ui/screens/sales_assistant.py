"""دستیارِ فروشِ پیچا -- طبقِ درخواستِ صریحِ کاربر («یک پنلِ دائمی...
دستیارِ فروش پیچا... ۵ اقدامِ مهمِ امروز»). این نسخه یک صفحه‌یِ قابلِ‌
ناوبریِ معمولی است (نه یک پنلِ شناورِ همیشه‌-نمایان)، چون در کلِ این
پروژه هیچ زیرساختِ dock-widget/پنلِ کناریِ سراسری وجود ندارد و همه‌یِ
ماژول‌ها با همین الگویِ «صفحه‌یِ قابلِ‌بازشدن از منو» ساخته شده‌اند."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import commercial_partners as partners_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import sales_assistant as assistant_service
from peecha.ui import theme
from peecha.ui.screens.commercial_document import _CounterpartyHistoryDialog

_SEVERITY_META = {
    "danger": ("🔴", "DANGER"),
    "warning": ("🟡", "WARNING"),
    "success": ("🟢", "SUCCESS"),
}
_ACTIONS_LIMIT = 5


class _ActionCard(QFrame):
    def __init__(self, item: assistant_service.ActionItem, screen: "SalesAssistantScreen", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._item = item
        self._screen = screen

        emoji, color_attr = _SEVERITY_META[item.severity]
        color = getattr(theme, color_attr)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        title_row = QHBoxLayout()
        title_label = QLabel(f"{emoji} {item.title}")
        title_label.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: 800;")
        title_row.addWidget(title_label)
        title_row.addStretch(1)
        if item.metric_percent is not None:
            metric_label = QLabel(f"{item.metric_percent:.0f}٪")
            metric_label.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: 800;")
            title_row.addWidget(metric_label)
        layout.addLayout(title_row)

        for line in item.detail_lines:
            detail_label = QLabel(line)
            detail_label.setWordWrap(True)
            detail_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
            layout.addWidget(detail_label)

        bottom_row = QHBoxLayout()
        suggestion_label = QLabel(f"پیشنهاد: {item.suggested_action}")
        suggestion_label.setWordWrap(True)
        suggestion_label.setStyleSheet("font-size: 12.5px; font-weight: 600;")
        bottom_row.addWidget(suggestion_label, stretch=1)

        action_button = QPushButton()
        if item.category == "growth":
            action_button.setText("💳 افزایشِ سقفِ اعتبار")
            action_button.clicked.connect(lambda: self._screen.raise_credit_limit(item))
        else:
            action_button.setText("👤 بازکردنِ فرمِ مشتری")
            action_button.clicked.connect(lambda: self._screen.open_customer_form(item.customer_id))
        bottom_row.addWidget(action_button)

        # طبقِ درخواستِ صریح («ریسکِ ریزش... چرا؟»): این دکمه سابقهٔ
        # واقعیِ اسنادِ همین طرفِ‌حساب را نشان می‌دهد -- همان دیالوگی که
        # از قبل در فرمِ سندِ بازرگانی ساخته شده بود (R37-3) -- تا
        # فروشنده به‌جایِ اعتماد به یک عددِ محاسبه‌شده، خودِ روندِ
        # خریدهای گذشته را ببیند.
        history_button = QPushButton("🕘 سابقهٔ خرید")
        history_button.clicked.connect(lambda: self._screen.open_purchase_history(item))
        bottom_row.addWidget(history_button)
        layout.addLayout(bottom_row)

        self.setStyleSheet(
            f"QFrame#card {{ border: 1px solid {theme.rgba(color, 0.28)}; "
            f"background-color: {theme.rgba(color, 0.08)}; border-radius: 12px; }}"
        )


class SalesAssistantScreen(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__()
        self._main_window = main_window

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        header_row = QHBoxLayout()
        title = QLabel("🧠 دستیارِ فروشِ پیچا")
        title.setObjectName("pageTitle")
        header_row.addWidget(title)
        header_row.addStretch(1)
        refresh_button = QPushButton("🔄 به‌روزرسانی")
        refresh_button.clicked.connect(self.refresh)
        header_row.addWidget(refresh_button)
        outer.addLayout(header_row)

        hint = QLabel(
            "طبقِ سابقه‌یِ فروش، مهم‌ترین اقداماتِ امروز -- ریسکِ ریزشِ مشتری، فرصتِ فروشِ مکمل، "
            "و مشتریانِ روبه‌رشد -- این‌جا رتبه‌بندی می‌شوند."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        self._empty_label = QLabel("امروز هیچ اقدامِ ویژه‌ای برایِ پیشنهاد نیست.")
        self._empty_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self._empty_label)

        self._cards_container = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(10)
        self._cards_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self._cards_container)
        outer.addWidget(scroll, stretch=1)

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        while self._cards_layout.count() > 1:
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        company_id = self._company_id()
        actions = assistant_service.get_daily_actions(company_id, limit=_ACTIONS_LIMIT) if company_id else []
        self._empty_label.setVisible(not actions)
        for action_item in actions:
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, _ActionCard(action_item, self))

    def open_purchase_history(self, item: assistant_service.ActionItem) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        dialog = _CounterpartyHistoryDialog(self, company_id, item.customer_id, item.customer_name)
        dialog.exec()

    def open_customer_form(self, customer_id: int) -> None:
        self._main_window.open_screen(
            "GL_DIM",
            then=lambda screen: screen.select_type_and_edit(
                ("person", dimensions_service.CUSTOMER_GROUP_CODE), customer_id
            ),
        )

    def raise_credit_limit(self, item: assistant_service.ActionItem) -> None:
        profile = partners_service.get_customer_profile(item.customer_id)
        current_limit = float(profile.credit_limit_amount) if profile is not None and profile.credit_limit_amount else 0.0
        new_limit, accepted = QInputDialog.getDouble(
            self, "افزایشِ سقفِ اعتبار", f"سقفِ اعتبارِ تازه برایِ «{item.customer_name}»:",
            value=current_limit, minValue=0, maxValue=1_000_000_000_000, decimals=0,
        )
        if not accepted:
            return
        try:
            partners_service.set_customer_credit_limit(item.customer_id, decimal.Decimal(new_limit))
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()
