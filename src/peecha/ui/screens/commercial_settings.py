"""تنظیماتِ دامنهٔ مدیریتِ بازرگانی — نگاشتِ حساب‌ها، Feature Toggle،
نمایه‌هایِ صنعتی، شماره‌گذاریِ اسناد، کانال‌ها (مرحلهٔ ۱۱)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import commercial_settings as settings_service
from peecha.ui.widgets import FieldGrid, FieldSpec, LayoutEditMixin


def _company_id() -> int | None:
    return app_session.current_company.company_id if app_session.current_company else None


class _AccountMappingsTab(LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._combos: dict[str, QComboBox] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        title = QLabel("نگاشتِ حساب‌هایِ بازرگانی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("حساب‌هایِ دریافتنیِ مشتریان/پرداختنیِ تامین‌کنندگان از تنظیماتِ انبار می‌آیند و این‌جا تکرار نمی‌شوند."))

        for key in settings_service.MAPPING_LABELS:
            combo = QComboBox()
            combo.setMinimumWidth(280)
            self._combos[key] = combo
        self.mappings_grid = FieldGrid(
            [FieldSpec(key, label, self._combos[key], span=2) for key, label in settings_service.MAPPING_LABELS.items()]
        )
        layout.addWidget(self.mappings_grid)
        self.register_field_grids("commercial_settings_account_mappings", [self.mappings_grid])

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

        save_button = QPushButton("💾")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(40)
        save_button.setToolTip("ذخیره")
        save_button.clicked.connect(self._save)
        layout.addWidget(save_button, alignment=Qt.AlignLeft)
        layout.addStretch(1)

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        accounts = [(a.account_id, f"{a.full_code} — {a.name}") for a in coa_service.list_accounts(company_id) if a.is_postable]
        current_by_key = {row.mapping_key: row.account_id for row in settings_service.list_account_mappings(company_id)}
        for key, combo in self._combos.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("(تعیین‌نشده)", None)
            for account_id, label in accounts:
                combo.addItem(label, account_id)
            combo.setCurrentIndex(max(0, combo.findData(current_by_key.get(key))))
            combo.blockSignals(False)
        self.status_label.setText("")

    def _save(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        for key, combo in self._combos.items():
            account_id = combo.currentData()
            if account_id is not None:
                settings_service.set_account_mapping(company_id, key, account_id)
        self.status_label.setObjectName("statusSuccess")
        self.status_label.setText("ذخیره شد.")


class _FeatureToggleTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._checkboxes: dict[str, QCheckBox] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        title = QLabel("قابلیت‌هایِ فعال (Feature Toggle)")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("فعال‌سازیِ هر قابلیت ممکن است به قابلیتِ دیگری وابسته باشد."))

        self.rows_layout = QVBoxLayout()
        layout.addLayout(self.rows_layout)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

    def refresh(self) -> None:
        company_id = _company_id()
        while self.rows_layout.count():
            child = self.rows_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._checkboxes = {}
        if company_id is None:
            return
        for feature in settings_service.list_features(company_id):
            checkbox = QCheckBox(feature.name)
            checkbox.setChecked(feature.is_enabled)
            checkbox.toggled.connect(lambda checked, code=feature.feature_code: self._toggle(code, checked))
            self._checkboxes[feature.feature_code] = checkbox
            self.rows_layout.addWidget(checkbox)
        self.status_label.setText("")

    def _toggle(self, feature_code: str, checked: bool) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        try:
            settings_service.set_feature_enabled(company_id, feature_code, checked)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            self._checkboxes[feature_code].blockSignals(True)
            self._checkboxes[feature_code].setChecked(not checked)
            self._checkboxes[feature_code].blockSignals(False)
            return
        self.status_label.setText("")


class _IndustryProfileTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        title = QLabel("نمایهٔ صنعتی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("اعمالِ نمایه، فقط قابلیت‌هایِ هنوز-تنظیم‌نشده را پر می‌کند — تنظیماتِ دستیِ قبلی دست‌نخورده می‌ماند."))

        row = QHBoxLayout()
        self.profile_combo = QComboBox()
        row.addWidget(self.profile_combo, stretch=1)
        apply_button = QPushButton("✔️")
        apply_button.setObjectName("primaryIconButton")
        apply_button.setFixedWidth(40)
        apply_button.setToolTip("اعمالِ نمایه")
        apply_button.clicked.connect(self._apply)
        row.addWidget(apply_button)
        layout.addLayout(row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusSuccess")
        layout.addWidget(self.status_label)
        layout.addStretch(1)

    def refresh(self) -> None:
        self.profile_combo.clear()
        for profile in settings_service.list_industry_profiles():
            self.profile_combo.addItem(profile.name, profile.profile_code)
        self.status_label.setText("")

    def _apply(self) -> None:
        company_id = _company_id()
        profile_code = self.profile_combo.currentData()
        if company_id is None or profile_code is None:
            return
        settings_service.apply_industry_profile(company_id, profile_code)
        self.status_label.setText("نمایه اعمال شد.")


class _NumberingSequencesTab(LayoutEditMixin, QWidget):
    _RESET_LABELS = {"YEARLY": "سالانه", "NEVER": "هرگز"}

    def __init__(self) -> None:
        super().__init__()
        self._prefix_fields: dict[str, QLineEdit] = {}
        self._reset_combos: dict[str, QComboBox] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        title = QLabel("شماره‌گذاریِ اسناد")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        from peecha.ui.screens.commercial_document import DOC_TYPE_TITLES

        specs: list[FieldSpec] = []
        for code, label in DOC_TYPE_TITLES.items():
            prefix_field = QLineEdit()
            prefix_field.setPlaceholderText("پیشوند (مثلاً SO-)")
            self._prefix_fields[code] = prefix_field
            reset_combo = QComboBox()
            for reset_code, reset_label in self._RESET_LABELS.items():
                reset_combo.addItem(reset_label, reset_code)
            self._reset_combos[code] = reset_combo
            specs.append(FieldSpec(f"{code}_prefix", f"پیشوندِ {label}", prefix_field, span=1))
            specs.append(FieldSpec(f"{code}_reset", f"سیاستِ بازنشانیِ {label}", reset_combo, span=1))
        self.numbering_grid = FieldGrid(specs, columns=2)
        layout.addWidget(self.numbering_grid)
        self.register_field_grids("commercial_settings_numbering", [self.numbering_grid])

        save_button = QPushButton("💾")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(40)
        save_button.setToolTip("ذخیره")
        save_button.clicked.connect(self._save)
        layout.addWidget(save_button, alignment=Qt.AlignLeft)
        self.status_label = QLabel("")
        self.status_label.setObjectName("statusSuccess")
        layout.addWidget(self.status_label)
        layout.addStretch(1)

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        for code in self._prefix_fields:
            existing = settings_service.get_numbering_sequence(company_id, code)
            self._prefix_fields[code].setText(existing.prefix if existing else "")
            reset_code = existing.reset_policy_code if existing else "YEARLY"
            self._reset_combos[code].setCurrentIndex(max(0, self._reset_combos[code].findData(reset_code)))
        self.status_label.setText("")

    def _save(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        for code in self._prefix_fields:
            settings_service.set_numbering_sequence(
                company_id, code, self._prefix_fields[code].text().strip(), self._reset_combos[code].currentData()
            )
        self.status_label.setText("ذخیره شد.")


class _ChannelsTab(QWidget):
    _CHANNEL_TYPES = {
        "POS": "فروشگاهِ حضوری", "WHOLESALE": "عمده‌فروشی", "ONLINE": "اینترنتی", "AGENT": "نمایندگی",
        "MARKETPLACE": "بازارگاهِ آنلاین",
    }

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        title = QLabel("کانال‌هایِ فروش")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        form = QHBoxLayout()
        self.code_field = QLineEdit()
        self.code_field.setPlaceholderText("کد (مثلاً WEB)")
        form.addWidget(self.code_field)
        self.name_field = QLineEdit()
        self.name_field.setPlaceholderText("نام")
        form.addWidget(self.name_field)
        self.type_combo = QComboBox()
        for code, label in self._CHANNEL_TYPES.items():
            self.type_combo.addItem(label, code)
        form.addWidget(self.type_combo)
        add_button = QPushButton("➕")
        add_button.setObjectName("primaryIconButton")
        add_button.setFixedWidth(40)
        add_button.setToolTip("افزودن")
        add_button.clicked.connect(self._add)
        form.addWidget(add_button)
        layout.addLayout(form)

        self.list_label = QLabel("")
        self.list_label.setWordWrap(True)
        layout.addWidget(self.list_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)
        layout.addStretch(1)

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        channels = pricing_service.list_channels(company_id)
        self.list_label.setText(
            "\n".join(f"{ch.channel_code} — {ch.name} ({self._CHANNEL_TYPES.get(ch.channel_type_code, ch.channel_type_code)})" for ch in channels)
            or "هنوز کانالی تعریف نشده است."
        )
        self.status_label.setText("")

    def _add(self) -> None:
        company_id = _company_id()
        code = self.code_field.text().strip().upper()
        name = self.name_field.text().strip()
        if company_id is None or not code or not name:
            self.status_label.setText("کد و نام را وارد کنید.")
            return
        if any(ch.channel_code == code for ch in pricing_service.list_channels(company_id)):
            self.status_label.setText("این کد قبلاً استفاده شده است.")
            return
        try:
            pricing_service.create_channel(company_id, code, name, self.type_combo.currentData())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.code_field.clear()
        self.name_field.clear()
        self.status_label.setText("")
        self.refresh()
