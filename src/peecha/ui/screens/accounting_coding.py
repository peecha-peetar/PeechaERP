"""تنظیماتِ کدینگِ حسابداری — تعدادِ رقم + بازه‌یِ از-تا برایِ هر سطحِ کدینگِ
حساب‌ها (گروه/کل/معین). طبقِ درخواستِ صریح، این تنظیمات باید پیش از هر
کارِ دیگری در حسابداری انجام شود و بعدِ اولین سندِ شرکت دیگر قابلِ‌تغییر
نیست — چون کدهایِ ثبت‌شده‌ی موجود با تغییرِ طول/بازه ناسازگار می‌شوند."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget

from peecha import session as app_session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import journal_entries as je_service

_LEVEL_LABELS = {1: "گروه", 2: "کل", 3: "معین"}


class AccountingCodingSettingsScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._level_widgets: dict[int, tuple[QSpinBox, QSpinBox, QSpinBox]] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(12)

        title = QLabel("کدینگِ حسابداری")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        hint = QLabel(
            "تعدادِ رقم و بازه‌ی از-تا برایِ هر سطحِ کدینگِ حساب‌ها — این تنظیمات باید پیش از شروعِ "
            "کدینگ انجام شود؛ بعدِ ثبتِ اولین سندِ شرکت دیگر قابلِ‌تغییر نیست. مقدارِ صفر یعنی بدونِ محدودیت."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        card = QWidget()
        card.setObjectName("card")
        grid = QGridLayout(card)
        grid.setContentsMargins(18, 18, 18, 18)
        grid.setSpacing(10)

        grid.addWidget(QLabel("سطح"), 0, 0)
        grid.addWidget(QLabel("تعدادِ رقم"), 0, 1)
        grid.addWidget(QLabel("از"), 0, 2)
        grid.addWidget(QLabel("تا"), 0, 3)

        for row, level in enumerate(sorted(_LEVEL_LABELS), start=1):
            grid.addWidget(QLabel(_LEVEL_LABELS[level]), row, 0)
            code_length = QSpinBox()
            code_length.setRange(0, 10)
            range_from = QSpinBox()
            range_from.setRange(0, 999_999_999)
            range_to = QSpinBox()
            range_to.setRange(0, 999_999_999)
            grid.addWidget(code_length, row, 1)
            grid.addWidget(range_from, row, 2)
            grid.addWidget(range_to, row, 3)
            self._level_widgets[level] = (code_length, range_from, range_to)

        outer.addWidget(card)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        self.save_button = QPushButton("ذخیره‌ی تنظیماتِ کدینگ")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save)
        outer.addWidget(self.save_button)

        outer.addStretch(1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        self.status_label.setText("")
        company_id = self._company_id()
        if company_id is None:
            return

        rows_by_level = {r.account_level: r for r in coa_service.list_account_level_config(company_id)}
        for level, (code_length, range_from, range_to) in self._level_widgets.items():
            row = rows_by_level.get(level)
            code_length.setValue(row.code_length if row and row.code_length is not None else 0)
            range_from.setValue(row.range_from if row and row.range_from is not None else 0)
            range_to.setValue(row.range_to if row and row.range_to is not None else 0)

        locked = je_service.company_has_any_entries(company_id)
        for code_length, range_from, range_to in self._level_widgets.values():
            code_length.setEnabled(not locked)
            range_from.setEnabled(not locked)
            range_to.setEnabled(not locked)
        self.save_button.setEnabled(not locked)
        if locked:
            self.status_label.setObjectName("sectionHint")
            self.status_label.setStyleSheet("")
            self.status_label.setText("این شرکت سند دارد؛ تنظیماتِ کدینگِ حساب‌ها دیگر قابلِ‌تغییر نیست.")

    def _save(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        levels: dict[int, dict] = {}
        for level, (code_length, range_from, range_to) in self._level_widgets.items():
            levels[level] = {
                "code_length": code_length.value() or None,
                "range_from": range_from.value() or None,
                "range_to": range_to.value() or None,
            }
        try:
            coa_service.set_account_level_config(company_id, levels)
        except ValueError as exc:
            self.status_label.setObjectName("statusError")
            self.status_label.setStyleSheet("")
            self.status_label.setText(str(exc))
            return
        self.refresh()
        self.status_label.setObjectName("statusOk")
        self.status_label.setStyleSheet("")
        self.status_label.setText("تنظیماتِ کدینگ ذخیره شد.")
