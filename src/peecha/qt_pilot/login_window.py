"""پنجره‌ی ورود — نمونه‌ی آزمایشیِ Qt6.

هیچ shape()/reshape/bidi دستی لازم نیست: Qt خودش موتورِ متنِ کاملِ
bidi/شکل‌دهیِ عربی/فارسی دارد (بر خلافِ Kivy) — همین یکی از دلایلِ اصلیِ
این آزمایش است."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sqlalchemy import select

from peecha import session
from peecha.db.base import new_session
from peecha.db.models.core import Company
from peecha.db.models.security import UserCompany
from peecha.services.auth import authenticate

_STYLE = """
QWidget#root {
    background-color: #F6F5FB;
}
QWidget#card {
    background-color: #FFFFFF;
    border-radius: 16px;
}
QLabel#title {
    font-size: 28px;
    font-weight: bold;
    color: #14173A;
}
QLabel#heading {
    font-size: 20px;
    font-weight: bold;
    color: #14173A;
}
QLabel#status {
    color: #E5484D;
}
QLineEdit {
    background-color: #F4F3FA;
    border: 1px solid #E4E1F5;
    border-radius: 10px;
    padding: 10px 14px;
    font-size: 14px;
    color: #14173A;
}
QLineEdit:focus {
    border: 1px solid #6D5CE6;
}
QPushButton#loginButton {
    background-color: #6D5CE6;
    color: white;
    border-radius: 20px;
    padding: 10px 0px;
    font-size: 15px;
}
QPushButton#loginButton:hover {
    background-color: #5b4cd6;
}
"""


class LoginWindow(QWidget):
    def __init__(self, font_family: str) -> None:
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle("پیچا — نمونه‌ی Qt6")
        self.resize(420, 620)
        self.setStyleSheet(_STYLE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.setSpacing(24)
        outer.setAlignment(Qt.AlignTop)

        title = QLabel("پیچا")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        card = QWidget()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 28, 28, 28)
        card_layout.setSpacing(16)

        heading = QLabel("ورود به سیستم")
        heading.setObjectName("heading")
        card_layout.addWidget(heading)

        self.username_field = QLineEdit()
        self.username_field.setPlaceholderText("نام کاربری")
        card_layout.addWidget(self.username_field)

        self.password_field = QLineEdit()
        self.password_field.setPlaceholderText("رمز عبور")
        self.password_field.setEchoMode(QLineEdit.Password)
        card_layout.addWidget(self.password_field)

        self.status_label = QLabel("")
        self.status_label.setObjectName("status")
        self.status_label.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(self.status_label)

        login_button = QPushButton("ورود")
        login_button.setObjectName("loginButton")
        login_button.clicked.connect(self._attempt_login)
        card_layout.addWidget(login_button)

        outer.addWidget(card)

        self.password_field.returnPressed.connect(self._attempt_login)
        self.username_field.setFocus()

    def _attempt_login(self) -> None:
        username = self.username_field.text().strip()
        password = self.password_field.text()
        if not username or not password:
            self.status_label.setText("نام کاربری و رمز عبور را وارد کنید.")
            return

        user = authenticate(username, password)
        if user is None:
            self.status_label.setText("نام کاربری یا رمز عبور نادرست است.")
            return

        session.current_user = user
        self._load_default_company(user.user_id)
        from peecha.qt_pilot.accounts_window import AccountsWindow  # noqa: PLC0415

        self._accounts_window = AccountsWindow()
        self._accounts_window.show()
        self.close()

    def _load_default_company(self, user_id: int) -> None:
        with new_session() as db_session:
            user_company = db_session.scalar(
                select(UserCompany).where(UserCompany.user_id == user_id).order_by(UserCompany.is_default.desc())
            )
            session.current_company = (
                db_session.get(Company, user_company.company_id) if user_company is not None else None
            )
