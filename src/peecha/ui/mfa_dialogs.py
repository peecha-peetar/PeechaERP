"""R377: دیالوگ‌های ورود دومرحله‌ای — پرسیدن کد هنگام ورود، فعال‌سازی با QR و نمایش کدهای بازیابی، و تنظیم حساب خود کاربر."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services import auth, mfa


def _code_field() -> QLineEdit:
    field = QLineEdit()
    field.setPlaceholderText("کد شش‌رقمی")
    field.setAlignment(Qt.AlignCenter)
    field.setMaxLength(12)
    return field


def _error_label() -> QLabel:
    label = QLabel("")
    label.setObjectName("statusError")
    label.setWordWrap(True)
    return label


def _icon_button(glyph: str, tip: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(tip)
    button.setAccessibleName(tip)
    button.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


class MfaCodeDialog(QDialog):
    """هنگام ورود: کد برنامهٔ احراز هویت یا یکی از کدهای بازیابی."""

    def __init__(self, parent, user_id: int) -> None:
        super().__init__(parent)
        self.user_id = user_id
        self.setWindowTitle("ورود دومرحله‌ای")
        self.setMinimumWidth(360)
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(self)
        note = QLabel("کد شش‌رقمی برنامهٔ احراز هویت گوشی را وارد کنید. اگر گوشی در دسترس نیست، یکی از کدهای بازیابی را بنویسید.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.code = _code_field()
        self.code.returnPressed.connect(self.accept)
        layout.addWidget(self.code)
        self.error = _error_label()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("ورود")
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        try:
            self.kind = auth.verify_second_factor(self.user_id, self.code.text())
        except ValueError as exc:  # AccountLockedError هم از ValueError است
            self.error.setText(str(exc))
            self.code.clear()
            return
        super().accept()


class MfaEnrollDialog(QDialog):
    """فعال‌سازی: QR و کلید دستی، تایید با یک کد، سپس نمایش یک‌بارهٔ کدهای بازیابی."""

    def __init__(self, parent, user_id: int, *, forced: bool = False) -> None:
        super().__init__(parent)
        self.user_id, self.forced = user_id, forced
        self.recovery_codes: list[str] = []
        self.setWindowTitle("فعال‌سازی ورود دومرحله‌ای")
        self.setMinimumWidth(420)
        self.setLayoutDirection(Qt.RightToLeft)
        self.secret, self.uri = mfa.start_enrollment(user_id)
        layout = QVBoxLayout(self)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages)

        first = QWidget()
        f = QVBoxLayout(first)
        intro = ("ورود دومرحله‌ای برای حساب شما الزامی است. " if forced else "") + (
            "برنامهٔ احراز هویت گوشی (مثل Google Authenticator یا Microsoft Authenticator) را باز کنید، این QR را اسکن کنید "
            "و کد شش‌رقمی‌ای را که نشان می‌دهد این‌جا بنویسید.")
        note = QLabel(intro)
        note.setWordWrap(True)
        f.addWidget(note)
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap()
        pixmap.loadFromData(mfa.qr_png(self.uri))
        self.qr.setPixmap(pixmap)
        f.addWidget(self.qr)
        key = QLabel("کلید برای ورود دستی: " + " ".join(self.secret[i:i + 4] for i in range(0, len(self.secret), 4)))
        key.setTextInteractionFlags(Qt.TextSelectableByMouse)
        key.setLayoutDirection(Qt.LeftToRight)
        key.setWordWrap(True)
        f.addWidget(key)
        self.code = _code_field()
        self.code.returnPressed.connect(self.confirm)
        f.addWidget(self.code)
        self.error = _error_label()
        f.addWidget(self.error)
        self.pages.addWidget(first)

        second = QWidget()
        s = QVBoxLayout(second)
        done = QLabel("ورود دومرحله‌ای فعال شد. این کدهای بازیابی را جایی امن (نه روی همین گوشی) یادداشت کنید؛ هر کد فقط یک بار، "
                      "وقتی گوشی در دسترس نیست، به‌جای کد شش‌رقمی کار می‌کند. این کدها دیگر نمایش داده نمی‌شوند.")
        done.setWordWrap(True)
        s.addWidget(done)
        self.codes_view = QPlainTextEdit()
        self.codes_view.setReadOnly(True)
        self.codes_view.setLayoutDirection(Qt.LeftToRight)
        s.addWidget(self.codes_view)
        self.pages.addWidget(second)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("تایید کد")
        self.buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        self.buttons.accepted.connect(self.confirm)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def confirm(self) -> bool:
        if self.pages.currentIndex() == 1:
            super().accept()
            return True
        try:
            self.recovery_codes = mfa.confirm_enrollment(self.user_id, self.code.text())
        except ValueError as exc:
            self.error.setText(str(exc))
            return False
        if self.forced:
            auth.finish_login(self.user_id)
        self.codes_view.setPlainText("\n".join(self.recovery_codes))
        self.pages.setCurrentIndex(1)
        self.buttons.button(QDialogButtonBox.Ok).setText("یادداشت کردم")
        self.buttons.button(QDialogButtonBox.Cancel).hide()
        return True


class MfaSettingsDialog(QDialog):
    """حساب من: وضعیت، فعال‌سازی، کدهای بازیابی جدید و خاموش کردن (اگر الزامی نباشد)."""

    def __init__(self, parent, user_id: int) -> None:
        super().__init__(parent)
        self.user_id = user_id
        self.setWindowTitle("ورود دومرحله‌ای")
        self.setMinimumWidth(400)
        self.setLayoutDirection(Qt.RightToLeft)
        self.enroll_runner = None  # برای آزمون: اجرای دیالوگ فعال‌سازی
        layout = QVBoxLayout(self)
        self.state_label = QLabel("")
        self.state_label.setWordWrap(True)
        layout.addWidget(self.state_label)
        self.code = _code_field()
        layout.addWidget(self.code)
        row = QHBoxLayout()
        self.enable_button = _icon_button("🔐", "فعال‌سازی ورود دومرحله‌ای", "primary")
        self.enable_button.clicked.connect(self.enable)
        self.recovery_button = _icon_button("♻️", "ساخت کدهای بازیابی جدید (کد فعلی برنامه لازم است)")
        self.recovery_button.clicked.connect(self.new_recovery_codes)
        self.disable_button = _icon_button("🚫", "خاموش کردن ورود دومرحله‌ای (کد فعلی برنامه لازم است)", "danger")
        self.disable_button.clicked.connect(self.disable)
        for b in (self.enable_button, self.recovery_button, self.disable_button):
            row.addWidget(b)
        row.addStretch(1)
        layout.addLayout(row)
        self.message = _error_label()
        layout.addWidget(self.message)
        self.codes_view = QPlainTextEdit()
        self.codes_view.setReadOnly(True)
        self.codes_view.setLayoutDirection(Qt.LeftToRight)
        self.codes_view.hide()
        layout.addWidget(self.codes_view)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("بستن")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self) -> None:
        st = mfa.status(self.user_id)
        if st.enabled:
            text = (f"ورود دومرحله‌ای فعال است؛ {numerals.to_persian_digits(str(st.recovery_left))} کد بازیابی باقی مانده است."
                    + (" در شرکت شما الزامی است و خاموش نمی‌شود." if st.required else ""))
        else:
            text = "ورود دومرحله‌ای فعال نیست. با فعال‌سازی، پس از رمز عبور کد شش‌رقمی برنامهٔ گوشی هم پرسیده می‌شود."
        self.state_label.setText(text)
        self.enable_button.setVisible(not st.enabled)
        self.code.setVisible(st.enabled)
        self.recovery_button.setVisible(st.enabled)
        self.disable_button.setVisible(st.enabled)
        self.disable_button.setEnabled(not st.required)

    def _ok(self, text: str) -> None:
        self.message.setObjectName("statusOk")
        self.message.setStyleSheet("color: green;")
        self.message.setText(text)

    def _fail(self, text: str) -> None:
        self.message.setStyleSheet("")
        self.message.setText(text)

    def enable(self) -> bool:
        try:
            dialog = MfaEnrollDialog(self, self.user_id)
        except ValueError as exc:
            self._fail(str(exc))
            return False
        accepted = self.enroll_runner(dialog) if self.enroll_runner else dialog.exec() == QDialog.Accepted
        self.refresh()
        if accepted and mfa.status(self.user_id).enabled:
            self._ok("ورود دومرحله‌ای فعال شد.")
            return True
        return False

    def new_recovery_codes(self) -> bool:
        try:
            codes = mfa.regenerate_recovery(self.user_id, self.code.text())
        except ValueError as exc:
            self._fail(str(exc))
            return False
        self.code.clear()
        self.codes_view.setPlainText("\n".join(codes))
        self.codes_view.show()
        self.refresh()
        self._ok("کدهای بازیابی قبلی باطل شد؛ این کدها را جایی امن یادداشت کنید.")
        return True

    def disable(self) -> bool:
        try:
            mfa.disable(self.user_id, self.code.text())
        except ValueError as exc:
            self._fail(str(exc))
            return False
        self.code.clear()
        self.codes_view.hide()
        self.refresh()
        self._ok("ورود دومرحله‌ای خاموش شد.")
        return True
