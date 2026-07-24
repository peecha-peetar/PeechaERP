"""تنظیماتِ کدینگِ حسابداری — تعدادِ رقم + بازه‌یِ از-تا برایِ هر سطحِ کدینگِ
حساب‌ها (گروه/کل/معین). طبقِ درخواستِ صریح، این تنظیمات باید پیش از هر
کارِ دیگری در حسابداری انجام شود و بعدِ اولین سندِ شرکت دیگر قابلِ‌تغییر
نیست — چون کدهایِ ثبت‌شده‌ی موجود با تغییرِ طول/بازه ناسازگار می‌شوند.

طبقِ درخواستِ صریحِ بعدی: تبِ «کدینگِ حسابداری» در تنظیماتِ سیستم حالا
خودش دو زیرتب دارد — این فایل دو صفحه‌ی مستقل را تعریف می‌کند
(AccountingCodingSettingsScreen برایِ کدینگِ حساب‌ها، و
DetailLevelDigitSettingsScreen برایِ تعدادِ رقمِ سطوحِ تفصیلی) که در
system_settings.py با _sub_tabs کنارِ هم قرار می‌گیرند."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget

from peecha import session as app_session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import journal_entries as je_service
from peecha.ui import theme
from peecha.ui.widgets import ZeroPaddedSpinBox

_LEVEL_LABELS = {1: "گروه", 2: "کل", 3: "معین"}
_DETAIL_LEVEL_LABELS = {1: "سطحِ ۱", 2: "سطحِ ۲", 3: "سطحِ ۳", 4: "سطحِ ۴"}


class AccountingCodingSettingsScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._level_widgets: dict[int, tuple[QSpinBox, QSpinBox, QSpinBox]] = {}

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        outer = QVBoxLayout(content)
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
            range_from = ZeroPaddedSpinBox()
            range_from.setRange(0, 999_999_999)
            range_to = ZeroPaddedSpinBox()
            range_to.setRange(0, 999_999_999)
            # طبقِ بازخوردِ صریح: کدهایی مثلِ «۰۰۱» نباید با تغییرِ تعدادِ
            # رقم به «۱» تبدیل شوند — با هر تغییرِ تعدادِ رقم، نمایشِ بازه هم
            # بی‌درنگ صفر-پَد می‌شود. همچنین طبقِ بازخوردِ بعدی: تا این‌جا
            # فقط نمایش صفر-پَد می‌شد ولی خودِ بازه هنوز می‌توانست از
            # تعدادِ رقمِ انتخاب‌شده بیشتر مقدار بگیرد (مثلاً تعدادِ رقم=۱ ولی
            # بازه‌ای مثلِ ۹۹) — این‌جا سقفِ مجازِ اسپین‌باکس هم هم‌زمان با
            # تعدادِ رقم محدود می‌شود تا اصلاً نتوان چنین مقداری تایپ کرد.
            code_length.valueChanged.connect(
                lambda digits, rf=range_from, rt=range_to: (
                    rf.set_digits(digits),
                    rt.set_digits(digits),
                    rf.setRange(0, 10**digits - 1 if digits > 0 else 999_999_999),
                    rt.setRange(0, 10**digits - 1 if digits > 0 else 999_999_999),
                )
            )
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
        scroll.setWidget(content)
        root_layout.addWidget(scroll)

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
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return
        self.refresh()
        theme.set_status_label(self.status_label, "تنظیماتِ کدینگ ذخیره شد.", ok=True)


class DetailLevelDigitSettingsScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._detail_level_widgets: dict[int, QSpinBox] = {}

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(12)

        detail_title = QLabel("تعدادِ رقمِ سطوحِ تفصیلی")
        detail_title.setObjectName("pageTitle")
        outer.addWidget(detail_title)

        detail_hint = QLabel(
            "طبقِ درخواستِ صریح، تعدادِ رقمِ هر سطحِ تفصیلی (کالا/بانک/مشتری/تامین‌کننده/...) سراسری و "
            "برایِ همه‌ی گروه‌ها یکسان است — فقط بازه‌ی از-تا مخصوصِ هر گروه در صفحه‌ی «پیکربندیِ "
            "گروه‌هایِ تفصیلی» تنظیم می‌شود. مقدارِ صفر یعنی بدونِ محدودیتِ طول."
        )
        detail_hint.setObjectName("sectionHint")
        detail_hint.setWordWrap(True)
        outer.addWidget(detail_hint)

        detail_card = QWidget()
        detail_card.setObjectName("card")
        detail_grid = QGridLayout(detail_card)
        detail_grid.setContentsMargins(18, 18, 18, 18)
        detail_grid.setSpacing(10)

        detail_grid.addWidget(QLabel("سطح"), 0, 0)
        detail_grid.addWidget(QLabel("تعدادِ رقم"), 0, 1)

        for row, level in enumerate(sorted(_DETAIL_LEVEL_LABELS), start=1):
            detail_grid.addWidget(QLabel(_DETAIL_LEVEL_LABELS[level]), row, 0)
            code_length = QSpinBox()
            code_length.setRange(0, 10)
            detail_grid.addWidget(code_length, row, 1)
            self._detail_level_widgets[level] = code_length

        outer.addWidget(detail_card)

        self.detail_status_label = QLabel("")
        self.detail_status_label.setObjectName("statusError")
        self.detail_status_label.setWordWrap(True)
        outer.addWidget(self.detail_status_label)

        self.save_detail_button = QPushButton("ذخیره‌ی تعدادِ رقمِ سطوحِ تفصیلی")
        self.save_detail_button.setObjectName("primaryButton")
        self.save_detail_button.clicked.connect(self._save_detail_digits)
        outer.addWidget(self.save_detail_button)

        outer.addStretch(1)
        scroll.setWidget(content)
        root_layout.addWidget(scroll)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        self.detail_status_label.setText("")
        company_id = self._company_id()
        if company_id is None:
            return

        locked = je_service.company_has_any_entries(company_id)
        detail_rows_by_level = {r.level_no: r for r in dimensions_service.list_level_digit_config(company_id)}
        for level, code_length in self._detail_level_widgets.items():
            row = detail_rows_by_level.get(level)
            code_length.setValue(row.code_length if row and row.code_length is not None else 0)
            code_length.setEnabled(not locked)
        self.save_detail_button.setEnabled(not locked)
        if locked:
            self.detail_status_label.setObjectName("sectionHint")
            self.detail_status_label.setStyleSheet("")
            self.detail_status_label.setText("این شرکت سند دارد؛ تعدادِ رقمِ سطوحِ تفصیلی دیگر قابلِ‌تغییر نیست.")

    def _save_detail_digits(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        config = {level: code_length.value() or None for level, code_length in self._detail_level_widgets.items()}
        try:
            dimensions_service.set_level_digit_config(company_id, config)
        except ValueError as exc:
            theme.set_status_label(self.detail_status_label, str(exc), ok=False)
            return
        self.refresh()
        theme.set_status_label(self.detail_status_label, "تعدادِ رقمِ سطوحِ تفصیلی ذخیره شد.", ok=True)
