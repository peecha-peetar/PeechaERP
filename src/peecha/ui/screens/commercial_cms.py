"""سینکِ مقاله با CMS (وردپرس) -- طبقِ ادامه‌یِ اولویتِ بخشِ محتوا/
بازاریابی. معماری هم‌الگو با commercial_social.py."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.services import commercial_cms as cms_service
from peecha.ui import theme
from peecha.ui.widgets import LayoutEditMixin, wrap_scrollable

_PLATFORM_LABELS = {"WORDPRESS": "وردپرس"}
_ARTICLE_STATUS_LABELS = {"DRAFT": "پیش‌نویس", "PUBLISHED": "منتشرشده", "FAILED": "ناموفق"}


class CommercialCmsScreen(LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._connections: list = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("سینکِ محتوا با CMS")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._build_connections_tab(), "اتصالاتِ وردپرس")
        tabs.addTab(self._build_articles_tab(), "مقالات")
        outer.addWidget(tabs, stretch=1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    # --- اتصالات -----------------------------------------------------------
    def _build_connections_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)

        self.connections_table = QTableWidget(0, 3)
        self.connections_table.setHorizontalHeaderLabels(["پلتفرم", "نام", "آدرسِ سایت"])
        self.connections_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.connections_table.verticalHeader().setVisible(False)
        self.connections_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.connections_table.cellClicked.connect(self._on_connection_selected)
        outer.addWidget(self.connections_table, stretch=1)

        form = QHBoxLayout()
        self.cms_platform_combo = QComboBox()
        for code, label in _PLATFORM_LABELS.items():
            self.cms_platform_combo.addItem(label, code)
        form.addWidget(self.cms_platform_combo)
        self.cms_name_field = QLineEdit()
        self.cms_name_field.setPlaceholderText("نامِ نمایشی (مثلاً «وبلاگِ فروشگاه»)")
        form.addWidget(self.cms_name_field, stretch=1)
        self.cms_site_url_field = QLineEdit()
        self.cms_site_url_field.setPlaceholderText("آدرسِ سایت (مثلاً https://example.com)")
        form.addWidget(self.cms_site_url_field, stretch=1)
        self.cms_username_field = QLineEdit()
        self.cms_username_field.setPlaceholderText("نامِ‌کاربری")
        form.addWidget(self.cms_username_field)
        self.cms_app_password_field = QLineEdit()
        self.cms_app_password_field.setPlaceholderText("رمزِ‌کاره (Application Password)")
        self.cms_app_password_field.setEchoMode(QLineEdit.Password)
        form.addWidget(self.cms_app_password_field)
        add_connection_button = QPushButton("➕")
        add_connection_button.setObjectName("primaryIconButton")
        add_connection_button.setFixedWidth(44)
        add_connection_button.setToolTip("افزودنِ اتصال")
        add_connection_button.clicked.connect(self._add_connection)
        form.addWidget(add_connection_button)
        test_connection_button = QPushButton("🔎")
        test_connection_button.setObjectName("iconButton")
        test_connection_button.setFixedWidth(44)
        test_connection_button.setToolTip("آزمایشِ اتصالِ انتخاب‌شده")
        test_connection_button.clicked.connect(self._test_connection)
        form.addWidget(test_connection_button)
        outer.addLayout(form)

        self.cms_status_label = QLabel("")
        self.cms_status_label.setObjectName("statusError")
        outer.addWidget(self.cms_status_label)
        return wrap_scrollable(page)

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._connections = cms_service.list_connections(company_id)
        self.connections_table.setRowCount(len(self._connections))
        for row_index, c in enumerate(self._connections):
            values = [_PLATFORM_LABELS.get(c.platform_code, c.platform_code), c.display_name, c.site_url]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, c.connection_id)
                self.connections_table.setItem(row_index, col_index, cell)

        self.article_connection_combo.clear()
        for c in self._connections:
            self.article_connection_combo.addItem(f"{_PLATFORM_LABELS.get(c.platform_code, c.platform_code)} — {c.display_name}", c.connection_id)

        self._refresh_articles()

    def _on_connection_selected(self, row: int, _column: int) -> None:
        self._selected_connection_id = self.connections_table.item(row, 0).data(Qt.UserRole)

    def _add_connection(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        try:
            cms_service.create_connection(
                company_id, self.cms_platform_combo.currentData(), self.cms_name_field.text(),
                self.cms_site_url_field.text(), self.cms_username_field.text(), self.cms_app_password_field.text(),
            )
        except ValueError as exc:
            self.cms_status_label.setText(str(exc))
            return
        self.cms_name_field.clear()
        self.cms_site_url_field.clear()
        self.cms_username_field.clear()
        self.cms_app_password_field.clear()
        self.cms_status_label.setText("")
        self.refresh()

    def _test_connection(self) -> None:
        connection_id = getattr(self, "_selected_connection_id", None)
        if connection_id is None:
            self.cms_status_label.setText("ابتدا یک اتصال را از فهرست انتخاب کنید.")
            return
        try:
            ok, message = cms_service.test_connection(connection_id)
        except ValueError as exc:
            self.cms_status_label.setText(str(exc))
            return
        theme.set_status_label(self.cms_status_label, message, ok=ok)

    # --- مقالات -----------------------------------------------------------
    def _build_articles_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)

        self.articles_table = QTableWidget(0, 5)
        self.articles_table.setHorizontalHeaderLabels(["اتصال", "عنوان", "وضعیت", "خطا", ""])
        self.articles_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.articles_table.verticalHeader().setVisible(False)
        self.articles_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        outer.addWidget(self.articles_table, stretch=1)

        form = QHBoxLayout()
        self.article_connection_combo = QComboBox()
        form.addWidget(self.article_connection_combo)
        self.article_title_field = QLineEdit()
        self.article_title_field.setPlaceholderText("عنوانِ مقاله")
        form.addWidget(self.article_title_field, stretch=1)
        add_article_button = QPushButton("➕")
        add_article_button.setObjectName("primaryIconButton")
        add_article_button.setFixedWidth(44)
        add_article_button.setToolTip("افزودنِ مقاله به‌عنوانِ پیش‌نویس")
        add_article_button.clicked.connect(self._add_article)
        form.addWidget(add_article_button)
        outer.addLayout(form)

        self.article_body_field = QPlainTextEdit()
        self.article_body_field.setPlaceholderText("متنِ مقاله (HTML مجاز است)")
        self.article_body_field.setFixedHeight(120)
        outer.addWidget(self.article_body_field)

        self.articles_status_label = QLabel("")
        self.articles_status_label.setObjectName("statusError")
        outer.addWidget(self.articles_status_label)
        return wrap_scrollable(page)

    def _refresh_articles(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        connections_by_id = {c.connection_id: c for c in self._connections}
        articles = cms_service.list_articles(company_id)
        self.articles_table.setRowCount(len(articles))
        for row_index, article in enumerate(articles):
            connection = connections_by_id.get(article.connection_id)
            connection_label = f"{_PLATFORM_LABELS.get(connection.platform_code, connection.platform_code)} — {connection.display_name}" if connection else str(article.connection_id)
            values = [connection_label, article.title, _ARTICLE_STATUS_LABELS.get(article.status_code, article.status_code), article.error_message or ""]
            for col_index, value in enumerate(values):
                self.articles_table.setItem(row_index, col_index, QTableWidgetItem(value))
            if article.status_code != "PUBLISHED":
                publish_button = QPushButton("📤")
            else:
                publish_button = QPushButton("🔄")
            publish_button.setObjectName("primaryIconButton")
            publish_button.setToolTip("انتشار" if article.status_code != "PUBLISHED" else "به‌روزرسانیِ پستِ منتشرشده")
            publish_button.clicked.connect(lambda _checked=False, article_id=article.article_id: self._publish_article(article_id))
            self.articles_table.setCellWidget(row_index, 4, publish_button)

    def _add_article(self) -> None:
        company_id = self._company_id()
        connection_id = self.article_connection_combo.currentData()
        if company_id is None or connection_id is None:
            self.articles_status_label.setText("ابتدا یک اتصال انتخاب کنید.")
            return
        try:
            cms_service.create_article(company_id, connection_id, self.article_title_field.text(), self.article_body_field.toPlainText())
        except ValueError as exc:
            self.articles_status_label.setText(str(exc))
            return
        self.article_title_field.clear()
        self.article_body_field.clear()
        self.articles_status_label.setText("")
        self._refresh_articles()

    def _publish_article(self, article_id: int) -> None:
        try:
            cms_service.publish_article(article_id)
        except Exception as exc:  # noqa: BLE001
            self.articles_status_label.setText(str(exc))
            self._refresh_articles()
            return
        theme.set_status_label(self.articles_status_label, "مقاله با موفقیت در وردپرس منتشر شد.", ok=True)
        self._refresh_articles()
