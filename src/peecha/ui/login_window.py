"""پنجره‌ی ورود.

هیچ shape()/reshape/bidi دستی لازم نیست: Qt خودش موتورِ متنِ کاملِ
bidi/شکل‌دهیِ عربی/فارسی دارد (بر خلافِ Kivy)."""

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
from peecha.ui import theme
from peecha.services.auth import authenticate

# استایلِ محلی فقط برایِ عناصرِ اختصاصیِ این صفحه (برند/عنوان)؛ کارت،
# فیلدها و دکمه با objectNameهایِ شناخته‌شده از QSS سراسری (theme.GLOBAL_QSS)
# استفاده می‌کنند تا هم‌شکلِ بقیه‌ی برنامه باشند.
_STYLE = f"""
QLabel#brandTitle {{
    font-size: 30px;
    font-weight: 800;
    color: {theme.ACCENT};
}}
QLabel#heading {{
    font-size: 18px;
    font-weight: 700;
    color: {theme.TEXT_PRIMARY};
}}
"""


class LoginWindow(QWidget):
    def __init__(self, font_family: str) -> None:
        super().__init__()
        self.setWindowTitle("پیچا")
        self.resize(420, 620)
        self.setStyleSheet(_STYLE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.setSpacing(24)
        outer.setAlignment(Qt.AlignTop)

        title = QLabel("پیچا")
        title.setObjectName("brandTitle")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        card = QWidget()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 32, 28, 32)
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
        self.status_label.setObjectName("statusError")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        card_layout.addWidget(self.status_label)

        login_button = QPushButton("ورود")
        login_button.setObjectName("primaryButton")
        login_button.setMinimumHeight(42)
        login_button.setCursor(Qt.PointingHandCursor)
        login_button.clicked.connect(self._attempt_login)
        card_layout.addWidget(login_button)

        outer.addWidget(card)
        theme.apply_card_shadows(self)

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
        from peecha.ui.shell_window import MainWindow  # noqa: PLC0415

        self._main_window = MainWindow()
        self._main_window.load_context_switcher()
        self._main_window.show()
        self.close()

    def _load_default_company(self, user_id: int) -> None:
        with new_session() as db_session:
            user_company = db_session.scalar(
                select(UserCompany).where(UserCompany.user_id == user_id).order_by(UserCompany.is_default.desc())
            )
            session.current_company = (
                db_session.get(Company, user_company.company_id) if user_company is not None else None
            )
