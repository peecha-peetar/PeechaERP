"""پنجره‌ی ورود + تنظیماتِ اتصال به دیتابیس + راه‌اندازیِ اولیه‌ی سیستم.

سه صفحه‌ی این فایل معادلِ Qt برایِ login.py/connection_settings.py/
admin_bootstrap.py در نسخه‌ی Kivی هستند — که در حذفِ کاملِ Kivی
(commit 3afe0bb) پاک شدند ولی هرگز به Qt6 منتقل نشدند؛ نبودشان یعنی وقتی
دیتابیس وجود ندارد/خالی است، کاربر هیچ راهی برایِ تنظیمِ اتصال یا ساختِ
اولین کاربر/شرکت نداشت (فقط یک فرمِ ورودِ ساده که در نبودِ دیتابیس، بدونِ
هیچ پیغامی شکست می‌خورد).

هیچ shape()/reshape/bidi دستی لازم نیست: Qt خودش موتورِ متنِ کاملِ
bidi/شکل‌دهیِ عربی/فارسی دارد (بر خلافِ Kivی)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from peecha import session
from peecha.config import (
    DatabaseConfig,
    create_database_if_missing,
    load_database_config,
    save_database_config,
    test_connection,
)
from peecha.db.base import get_engine, new_session, reset_engine
from peecha.db.models.core import Company
from peecha.db.models.security import UserCompany
from peecha.db.schema_bootstrap import apply_pending_schema_files
from peecha.services.auth import authenticate, has_any_user
from peecha.services.bootstrap import bootstrap_system
from peecha.ui import theme

# استایلِ محلی فقط برایِ عناصرِ اختصاصیِ این صفحه (برند/عنوان)؛ کارت،
# فیلدها و دکمه با objectNameهایِ شناخته‌شده از QSS سراسری (theme.GLOBAL_QSS)
# استفاده می‌کنند تا هم‌شکلِ بقیه‌ی برنامه باشند.
def _build_style() -> str:
    """طبقِ باگِ واقعیِ کشف‌شده (سوییچِ روشن/تیره): این قبلاً یک ثابتِ
    سطحِ ماژول بود که فقط یک‌بار، در لحظه‌یِ importِ فایل، رنگ‌هایِ
    theme.* را می‌خواند — یعنی بعدِ سوییچِ تم و logout (که یک
    LoginWindowِ تازه می‌سازد)، همچنان رنگِ همانِ تمی را نشان می‌داد که
    برنامه اولین‌بار با آن اجرا شده بود. حالا در هر بارِ ساختِ پنجره
    (`__init__`) دوباره صدا زده می‌شود تا رنگِ تازه‌یِ تم را بخواند."""
    return f"""
QLabel#brandTitle {{
    font-size: 26px;
    font-weight: 800;
    color: {theme.ACCENT};
}}
QLabel#heading {{
    font-size: 18px;
    font-weight: 700;
    color: {theme.TEXT_PRIMARY};
}}
"""


def _card(inner_layout: QVBoxLayout) -> QWidget:
    card = QWidget()
    card.setObjectName("card")
    inner_layout.setContentsMargins(28, 32, 28, 32)
    inner_layout.setSpacing(16)
    card.setLayout(inner_layout)
    return card


class LoginWindow(QStackedWidget):
    def __init__(self, font_family: str) -> None:
        super().__init__()
        self.setWindowTitle("پیچا")
        self.resize(460, 680)
        self.setStyleSheet(_build_style())
        self._font_family = font_family
        self._main_window = None

        self._login_page = self._build_login_page()
        self._connection_page = self._build_connection_page()
        self._bootstrap_page = self._build_bootstrap_page()
        self.addWidget(self._login_page)
        self.addWidget(self._connection_page)
        self.addWidget(self._bootstrap_page)

        self._refresh_login_state()

    # --- صفحه‌ی ورود ---------------------------------------------------------
    def _build_login_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.setSpacing(24)
        outer.setAlignment(Qt.AlignTop)

        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(64, theme.ACCENT))
        logo.setAlignment(Qt.AlignCenter)
        outer.addWidget(logo)

        title = QLabel("پیچا")
        title.setObjectName("brandTitle")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        card_layout = QVBoxLayout()
        card = _card(card_layout)

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

        # طبقِ رفتارِ نسخه‌ی Kivی: فقط وقتی sec.users خالی است نمایان می‌شود.
        self.bootstrap_button = QPushButton("راه‌اندازیِ اولیه‌ی سیستم")
        self.bootstrap_button.setObjectName("flatButton")
        self.bootstrap_button.setCursor(Qt.PointingHandCursor)
        self.bootstrap_button.clicked.connect(self._open_bootstrap)
        self.bootstrap_button.setVisible(False)
        card_layout.addWidget(self.bootstrap_button)

        # همیشه در دسترس (نه فقط وقتی اتصال شکست می‌خورد) — تا کاربر هر
        # وقت لازم شد بتواند دیتابیسِ دیگری را هدف بگیرد.
        connection_button = QPushButton("تنظیماتِ اتصال به دیتابیس")
        connection_button.setObjectName("flatButton")
        connection_button.setCursor(Qt.PointingHandCursor)
        connection_button.clicked.connect(self._open_connection_settings)
        card_layout.addWidget(connection_button)

        outer.addWidget(card)
        theme.apply_card_shadows(page)

        self.password_field.returnPressed.connect(self._attempt_login)
        return page

    def _refresh_login_state(self) -> None:
        self.status_label.setObjectName("statusError")
        self.status_label.setStyleSheet("")
        self.status_label.setText("")
        self.bootstrap_button.setVisible(False)
        try:
            apply_pending_schema_files(get_engine())
            no_users = not has_any_user()
        except SQLAlchemyError as exc:
            detail = str(exc.__cause__ or exc)
            self.status_label.setText(f"اتصال به دیتابیس برقرار نشد: {detail}")
            self.username_field.setFocus()
            return

        if no_users:
            self.bootstrap_button.setVisible(True)
            self.status_label.setObjectName("sectionHint")
            self.status_label.setStyleSheet("")
            self.status_label.setText("هنوز کاربری ثبت نشده — از دکمه‌ی زیر شروع کنید.")
        self.username_field.setFocus()

    def _attempt_login(self) -> None:
        username = self.username_field.text().strip()
        password = self.password_field.text()
        if not username or not password:
            self.status_label.setObjectName("statusError")
            self.status_label.setStyleSheet("")
            self.status_label.setText("نام کاربری و رمز عبور را وارد کنید.")
            return

        try:
            user = authenticate(username, password)
        except SQLAlchemyError as exc:
            detail = str(exc.__cause__ or exc)
            self.status_label.setObjectName("statusError")
            self.status_label.setStyleSheet("")
            self.status_label.setText(f"اتصال به دیتابیس برقرار نشد: {detail}")
            return
        if user is None:
            self.status_label.setObjectName("statusError")
            self.status_label.setStyleSheet("")
            self.status_label.setText("نام کاربری یا رمز عبور نادرست است.")
            return

        session.current_user = user
        self._load_default_company(user.user_id)
        self._open_shell()

    def _load_default_company(self, user_id: int) -> None:
        with new_session() as db_session:
            user_company = db_session.scalar(
                select(UserCompany).where(UserCompany.user_id == user_id).order_by(UserCompany.is_default.desc())
            )
            session.current_company = (
                db_session.get(Company, user_company.company_id) if user_company is not None else None
            )

    def _open_shell(self) -> None:
        from peecha.ui.shell_window import MainWindow  # noqa: PLC0415

        self._main_window = MainWindow()
        self._main_window.load_context_switcher()
        # طبقِ گزارشِ تکرارشوندهٔ کاربر («هنوز هم زیرِ تسک‌بار می‌رود»):
        # فراخوانیِ showMaximized() رویِ پنجره‌ای که هنوز هیچ‌وقت show()
        # نشده، در بعضی پیکربندی‌هایِ ویندوز باعث می‌شود maximizeِ بومی
        # کاملِ صفحه (زیرِ تسک‌بار را هم بگیرد) اجرا شود، نه فقط
        # availableGeometry — چون Qt هنوز handle/screenِ واقعیِ پنجره را
        # نساخته. اول show() عادی (که geometryِ واقعی و screen() را
        # برقرار می‌کند)، بعد maximize.
        self._main_window.show()
        self._main_window.showMaximized()
        self.close()

    # --- صفحه‌ی تنظیماتِ اتصال ------------------------------------------------
    def _build_connection_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.setSpacing(24)
        outer.setAlignment(Qt.AlignTop)

        card_layout = QVBoxLayout()
        card = _card(card_layout)

        heading = QLabel("تنظیماتِ اتصال به دیتابیس")
        heading.setObjectName("heading")
        card_layout.addWidget(heading)

        grid = QGridLayout()
        grid.setSpacing(8)

        grid.addWidget(QLabel("میزبان"), 0, 0)
        self.conn_host_field = QLineEdit()
        grid.addWidget(self.conn_host_field, 0, 1)

        grid.addWidget(QLabel("درگاه"), 1, 0)
        self.conn_port_field = QSpinBox()
        self.conn_port_field.setRange(1, 65535)
        grid.addWidget(self.conn_port_field, 1, 1)

        grid.addWidget(QLabel("نامِ دیتابیس"), 2, 0)
        self.conn_name_field = QLineEdit()
        grid.addWidget(self.conn_name_field, 2, 1)

        grid.addWidget(QLabel("کاربر"), 3, 0)
        self.conn_user_field = QLineEdit()
        grid.addWidget(self.conn_user_field, 3, 1)

        grid.addWidget(QLabel("رمزِ عبور"), 4, 0)
        self.conn_password_field = QLineEdit()
        self.conn_password_field.setEchoMode(QLineEdit.Password)
        grid.addWidget(self.conn_password_field, 4, 1)

        card_layout.addLayout(grid)

        self.connection_status_label = QLabel("")
        self.connection_status_label.setObjectName("statusError")
        self.connection_status_label.setWordWrap(True)
        card_layout.addWidget(self.connection_status_label)

        test_button = QPushButton("تستِ اتصال")
        test_button.setObjectName("flatButton")
        test_button.clicked.connect(self._test_connection)
        card_layout.addWidget(test_button)

        # طبقِ گزارشِ کاربر که کلِ دیتابیس (نه فقط جدول‌هایش) را حذف کرده
        # بود: «ساختِ جدول‌ها» فقط داخلِ یک دیتابیسِ از-قبل-موجود کار
        # می‌کند؛ این دکمه خودِ دیتابیس را (اگر نبود) با اتصال به دیتابیسِ
        # نگهداریِ postgres می‌سازد.
        create_database_button = QPushButton("ساختِ دیتابیس (اگر وجود ندارد)")
        create_database_button.setObjectName("flatButton")
        create_database_button.clicked.connect(self._create_database)
        card_layout.addWidget(create_database_button)

        create_tables_button = QPushButton("ساخت/به‌روزرسانیِ جدول‌های دیتابیس")
        create_tables_button.setObjectName("flatButton")
        create_tables_button.clicked.connect(self._create_tables)
        card_layout.addWidget(create_tables_button)

        save_button = QPushButton("ذخیره و بازگشت")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._save_connection_and_return)
        card_layout.addWidget(save_button)

        cancel_button = QPushButton("انصراف")
        cancel_button.setObjectName("flatButton")
        cancel_button.clicked.connect(self._cancel_connection_settings)
        card_layout.addWidget(cancel_button)

        outer.addWidget(card)
        theme.apply_card_shadows(page)
        return page

    def _current_connection_config(self) -> DatabaseConfig:
        return DatabaseConfig(
            host=self.conn_host_field.text().strip(),
            port=self.conn_port_field.value(),
            name=self.conn_name_field.text().strip(),
            user=self.conn_user_field.text().strip(),
            password=self.conn_password_field.text(),
        )

    def _open_connection_settings(self) -> None:
        config = load_database_config()
        self.conn_host_field.setText(config.host)
        self.conn_port_field.setValue(config.port)
        self.conn_name_field.setText(config.name)
        self.conn_user_field.setText(config.user)
        self.conn_password_field.setText(config.password)
        self.connection_status_label.setObjectName("statusError")
        self.connection_status_label.setStyleSheet("")
        self.connection_status_label.setText("")
        self.setCurrentWidget(self._connection_page)
        self.conn_host_field.setFocus()

    def _set_connection_status(self, message: str, ok: bool) -> None:
        self.connection_status_label.setObjectName("statusOk" if ok else "statusError")
        self.connection_status_label.setStyleSheet("")
        self.connection_status_label.setText(message)

    def _test_connection(self) -> None:
        self._set_connection_status("در حالِ بررسیِ اتصال...", ok=True)
        ok, message = test_connection(self._current_connection_config())
        self._set_connection_status("اتصال موفق بود." if ok else f"اتصال ناموفق: {message}", ok=ok)

    def _create_database(self) -> None:
        self._set_connection_status("در حالِ بررسی/ساختِ دیتابیس...", ok=True)
        ok, message = create_database_if_missing(self._current_connection_config())
        self._set_connection_status(message, ok=ok)

    def _create_tables(self) -> None:
        from sqlalchemy import create_engine

        self._set_connection_status("در حالِ بررسی/ساختِ جدول‌ها...", ok=True)
        config = self._current_connection_config()
        engine = create_engine(config.sqlalchemy_url, future=True)
        try:
            applied = apply_pending_schema_files(engine)
            if applied:
                self._set_connection_status("جدول‌هایِ دیتابیس با موفقیت ساخته/به‌روزرسانی شدند.", ok=True)
            else:
                self._set_connection_status("جدول‌ها از قبل ساخته شده‌اند؛ کاری لازم نبود.", ok=True)
        except SQLAlchemyError as exc:
            self._set_connection_status(f"ساختِ جدول‌ها ناموفق بود: {exc.__cause__ or exc}", ok=False)
        finally:
            engine.dispose()

    def _save_connection_and_return(self) -> None:
        save_database_config(self._current_connection_config())
        reset_engine()
        self.setCurrentWidget(self._login_page)
        self._refresh_login_state()

    def _cancel_connection_settings(self) -> None:
        self.setCurrentWidget(self._login_page)

    # --- صفحه‌ی راه‌اندازیِ اولیه ----------------------------------------------
    def _build_bootstrap_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.setSpacing(24)
        outer.setAlignment(Qt.AlignTop)

        card_layout = QVBoxLayout()
        card = _card(card_layout)

        heading = QLabel("راه‌اندازیِ اولیه‌ی سیستم")
        heading.setObjectName("heading")
        card_layout.addWidget(heading)

        hint = QLabel("اولین شرکت و اولین کاربرِ مدیرِ سیستم را یک‌جا بسازید.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        card_layout.addWidget(hint)

        self.bootstrap_company_field = QLineEdit()
        self.bootstrap_company_field.setPlaceholderText("نامِ شرکت")
        card_layout.addWidget(self.bootstrap_company_field)

        self.bootstrap_username_field = QLineEdit()
        self.bootstrap_username_field.setPlaceholderText("نامِ کاربری")
        card_layout.addWidget(self.bootstrap_username_field)

        self.bootstrap_full_name_field = QLineEdit()
        self.bootstrap_full_name_field.setPlaceholderText("نامِ کامل")
        card_layout.addWidget(self.bootstrap_full_name_field)

        self.bootstrap_password_field = QLineEdit()
        self.bootstrap_password_field.setPlaceholderText("رمزِ عبور (حداقل ۶ کاراکتر)")
        self.bootstrap_password_field.setEchoMode(QLineEdit.Password)
        card_layout.addWidget(self.bootstrap_password_field)

        self.bootstrap_confirm_password_field = QLineEdit()
        self.bootstrap_confirm_password_field.setPlaceholderText("تکرارِ رمزِ عبور")
        self.bootstrap_confirm_password_field.setEchoMode(QLineEdit.Password)
        card_layout.addWidget(self.bootstrap_confirm_password_field)

        self.bootstrap_status_label = QLabel("")
        self.bootstrap_status_label.setObjectName("statusError")
        self.bootstrap_status_label.setWordWrap(True)
        card_layout.addWidget(self.bootstrap_status_label)

        create_button = QPushButton("ایجاد")
        create_button.setObjectName("primaryButton")
        create_button.clicked.connect(self._create_admin)
        card_layout.addWidget(create_button)

        cancel_button = QPushButton("انصراف")
        cancel_button.setObjectName("flatButton")
        cancel_button.clicked.connect(self._cancel_bootstrap)
        card_layout.addWidget(cancel_button)

        outer.addWidget(card)
        theme.apply_card_shadows(page)
        return page

    def _open_bootstrap(self) -> None:
        self.bootstrap_status_label.setText("")
        self.setCurrentWidget(self._bootstrap_page)
        self.bootstrap_company_field.setFocus()

    def _create_admin(self) -> None:
        username = self.bootstrap_username_field.text().strip()
        full_name = self.bootstrap_full_name_field.text().strip()
        company_name = self.bootstrap_company_field.text().strip()
        password = self.bootstrap_password_field.text()
        confirm = self.bootstrap_confirm_password_field.text()

        if not username or not full_name or not company_name:
            self.bootstrap_status_label.setText("همه‌ی فیلدها را پر کنید.")
            return
        if len(password) < 6:
            self.bootstrap_status_label.setText("رمزِ عبور باید حداقل ۶ کاراکتر باشد.")
            return
        if password != confirm:
            self.bootstrap_status_label.setText("تکرارِ رمزِ عبور مطابقت ندارد.")
            return

        try:
            user = bootstrap_system(username, full_name, password, company_name)
        except Exception as exc:  # noqa: BLE001 - نمایشِ هر خطایِ دیتابیس به کاربر
            self.bootstrap_status_label.setText(f"خطا در راه‌اندازی: {exc}")
            return

        session.current_user = user
        self._load_default_company(user.user_id)
        self._open_shell()

    def _cancel_bootstrap(self) -> None:
        self.setCurrentWidget(self._login_page)
        self._refresh_login_state()
