"""R346: پنجرهٔ پایان سال مالی — انتخاب حساب سود (زیان) انباشته و خلاصهٔ سود و زیان، پیش‌نمایش و اجرا یا برگرداندن."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from peecha import numerals
from peecha.services import chart_of_accounts as coa_service
from peecha.services import year_end


def _icon(glyph: str, tip: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setObjectName("iconButton")
    button.setFixedWidth(44)
    button.setToolTip(tip)
    button.setAccessibleName(tip)
    button.setCursor(Qt.PointingHandCursor)
    if kind:
        button.setProperty("kind", kind)
    return button


class YearEndDialog(QDialog):
    def __init__(self, parent, company_id: int, fiscal_year_id: int) -> None:
        super().__init__(parent)
        self.company_id, self.fiscal_year_id = company_id, fiscal_year_id
        self.setWindowTitle("پایان سال مالی")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        hint = QLabel("حساب‌های موقت بسته، سود یا زیان به «سود (زیان) انباشته» منتقل، و ماندهٔ هر حساب و تفصیلی با سند "
                      "اختتامیه و افتتاحیه به سال بعد برده می‌شود. اسناد «موقت» ساخته می‌شوند؛ پس از بررسی، قطعی‌شان کنید و "
                      "سال را ببندید.")
        hint.setWordWrap(True)
        hint.setObjectName("sectionHint")
        layout.addWidget(hint)
        form = QFormLayout()
        self.retained = QComboBox()
        self.summary = QComboBox()
        self.summary.addItem("— بدون حساب خلاصه (بستن مستقیم به سود انباشته) —", None)
        for account in coa_service.list_postable_accounts(company_id):
            label = f"{numerals.to_persian_digits(account.full_code)} — {account.name}"
            self.retained.addItem(label, account.account_id)
            self.summary.addItem(label, account.account_id)
        retained_id, summary_id = year_end.get_settings(company_id)
        self.retained.setCurrentIndex(max(0, self.retained.findData(retained_id)))
        self.summary.setCurrentIndex(max(0, self.summary.findData(summary_id)))
        form.addRow("سود (زیان) انباشته", self.retained)
        form.addRow("خلاصهٔ سود و زیان", self.summary)
        layout.addLayout(form)
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        buttons = QHBoxLayout()
        self.run_button = _icon("🏁", "اجرای پایان سال", "primary")
        self.undo_button = _icon("↩️", "برگرداندن پایان سال (فقط پیش از قطعی‌شدن اسناد)")
        close_button = _icon("✖️", "بستن")
        self.run_button.clicked.connect(self.run)
        self.undo_button.clicked.connect(self.undo)
        close_button.clicked.connect(self.reject)
        for button in (self.run_button, self.undo_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self) -> None:
        info = year_end.preview(self.company_id, self.fiscal_year_id)
        result = "سود" if info.net_income >= 0 else "زیان"
        lines = [f"سال {numerals.to_persian_digits(info.fiscal_year_code)}: {result} خالص "
                 f"{numerals.to_persian_digits(f'{abs(info.net_income):,.0f}')} ریال؛ "
                 f"{numerals.to_persian_digits(str(info.temporary_rows))} ماندهٔ موقت و "
                 f"{numerals.to_persian_digits(str(info.permanent_rows))} ماندهٔ دائم (به تفکیک تفصیلی)."]
        if info.already_done:
            lines.append("پایان این سال قبلاً اجرا شده است.")
        lines += [f"• {p}" for p in info.problems if "سود (زیان) انباشته" not in p]
        self.summary_label.setText("\n".join(lines))
        self.run_button.setEnabled(not info.already_done)
        self.undo_button.setEnabled(info.already_done)

    def run(self) -> None:
        try:
            year_end.save_settings(self.company_id, self.retained.currentData(), self.summary.currentData())
            if QMessageBox.question(self, "پایان سال مالی", "اسناد پایان سال ساخته شود؟",
                                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
            result = year_end.close_year(self.company_id, self.fiscal_year_id, self._user_id())
        except ValueError as exc:
            QMessageBox.warning(self, "پایان سال مالی", str(exc))
            return
        QMessageBox.information(self, "پایان سال مالی", "اسناد پایان سال ساخته شد؛ پس از بررسی، قطعی‌شان کنید."
                                + ("" if result.opening_id else " ماندهٔ دائمی برای انتقال نبود."))
        self.refresh()

    def undo(self) -> None:
        if QMessageBox.question(self, "برگرداندن پایان سال", "اسناد پایان سال حذف شود؟",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            year_end.undo_year_end(self.company_id, self.fiscal_year_id)
        except ValueError as exc:
            QMessageBox.warning(self, "برگرداندن پایان سال", str(exc))
            return
        self.refresh()

    @staticmethod
    def _user_id() -> int:
        from peecha import session as app_session

        return app_session.current_user.user_id
