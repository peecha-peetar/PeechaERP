"""R344: تغییر رمز عبور کاربر واردشده؛ پس از ساخت کاربر یا بازنشانی رمز از سوی مدیر، اجباری است."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout

from peecha.services import auth


class ChangePasswordDialog(QDialog):
    def __init__(self, parent, user_id: int, *, forced: bool = False) -> None:
        super().__init__(parent)
        self.user_id, self.forced = user_id, forced
        self.setWindowTitle("تغییر رمز عبور")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        if forced:
            note = QLabel("رمز فعلی شما موقت است. برای ادامه، رمز جدیدی انتخاب کنید.")
            note.setWordWrap(True)
            layout.addWidget(note)
        form = QFormLayout()
        self.current = self._field()
        self.new = self._field()
        self.confirm = self._field()
        if not forced:
            form.addRow("رمز فعلی", self.current)
        form.addRow("رمز جدید", self.new)
        form.addRow("تکرار رمز جدید", self.confirm)
        layout.addLayout(form)
        rule = QLabel("دست‌کم ۸ نویسه، شامل حرف و عدد.")
        rule.setObjectName("sectionHint")
        layout.addWidget(rule)
        self.error = QLabel("")
        self.error.setObjectName("statusError")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("ذخیره")
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _field() -> QLineEdit:
        field = QLineEdit()
        field.setEchoMode(QLineEdit.Password)
        return field

    def accept(self) -> None:
        if self.new.text() != self.confirm.text():
            self.error.setText("تکرار رمز جدید با خودش یکی نیست.")
            return
        try:
            auth.change_password(self.user_id, self.new.text(), None if self.forced else self.current.text())
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        super().accept()
