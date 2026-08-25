"""مدیریتِ شرکت‌ها — معادلِ Qt برایِ companies.py/.kv در Kivy."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.services import companies as companies_service
from peecha.services import company_cloning
from peecha.services import languages as languages_service
from peecha.services import users as users_service
from peecha.ui import theme
from peecha.ui.widgets import (
    FieldGrid,
    FieldHelpMixin,
    FieldSpec,
    LayoutEditMixin,
    PersianDigitLineEdit,
    wrap_scrollable_with_footer,
)

_COLUMNS = ["فعال", "زبانِ پیش‌فرض", "ارزِ پایه", "نامِ نمایشی", "کد"]


class CompaniesScreen(FieldHelpMixin, LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[companies_service.CompanyRow] = []
        self._editing_id: int | None = None
        self._currency_options: list[companies_service.CurrencyOption] = []
        self._language_options: list[languages_service.LanguageRow] = []

        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)

        self.set_field_help([
            (
                self.code_field,
                "کدِ یکتایِ این شرکت در کلِ سیستم. بعدِ ساختنِ شرکت دیگر قابلِ‌تغییر نیست. "
                "چون همه‌جایِ برنامه با همین کد این شرکت را می‌شناسد.",
            ),
            (
                self.legal_name_field,
                "نامِ رسمی و ثبتی‌یِ شرکت. در اسنادِ رسمی و صورت‌هایِ مالیِ چاپی به‌کار می‌رود.",
            ),
            (
                self.display_name_field,
                "نامِ کوتاهی که در برنامه نمایش داده می‌شود، مثلاً در انتخابِ شرکت بالایِ صفحه. "
                "لازم نیست با نامِ حقوقی یکی باشد.",
            ),
            (
                self.currency_combo,
                "ارزِ پایه‌یِ این شرکت. همه‌یِ مبالغِ کدینگِ حساب‌ها و اسنادِ حسابداری با این ارز ثبت می‌شوند. "
                "هر شرکت ارزِ پایه‌یِ خودش را دارد. بعدِ ثبتِ چند سند بهتر است آن را تغییر ندهید.",
            ),
            (
                self.language_combo,
                "زبانِ پیش‌فرضِ این شرکت. برایِ نمایشِ نامِ حساب‌ها و فیلدهایِ چندزبانه استفاده می‌شود.",
            ),
            (
                self.fy_month_field,
                "ماهی که سالِ مالیِ این شرکت از آن شروع می‌شود — ۱ یعنی فروردین. "
                "بعضی شرکت‌ها (مثلاً پیمانکاری‌ها) سالِ مالی‌شان با سالِ شمسیِ معمولی فرق دارد. "
                "این عدد پایه‌یِ محاسبه‌یِ بازه‌یِ هر سالِ مالیِ تازه است.",
            ),
            (
                self.fy_day_field,
                "روزِ شروعِ سالِ مالی، در همان ماهِ بالا. "
                "این دو فیلد با هم اولین روزِ سالِ مالیِ شرکت را می‌سازند.",
            ),
            (
                self.economic_code_field,
                "کدِ اقتصادیِ شرکت نزدِ سازمانِ امور مالیاتی. در فاکتورها و گزارش‌هایِ ارزش‌افزوده به‌کار می‌رود. اختیاری است.",
            ),
            (
                self.registration_no_field,
                "شماره‌یِ ثبتِ شرکت نزدِ اداره‌یِ ثبتِ شرکت‌ها. برایِ اسنادِ قانونی لازم است. اختیاری است.",
            ),
            (
                self.national_id_field,
                "شناسه‌یِ ملیِ شرکت — یک کدِ یکتایِ ۱۱رقمی. در قراردادها و مکاتباتِ رسمی به‌کار می‌رود. اختیاری است.",
            ),
            (
                self.is_active_checkbox,
                "شرکت‌هایِ غیرِفعال دیگر در فهرستِ انتخابِ شرکت بالایِ برنامه نشان داده نمی‌شوند. "
                "داده‌هایِ قبلی‌شان (کدینگ، اسناد) پاک نمی‌شود.",
            ),
            (
                self.clone_checkbox,
                "به‌جایِ شروع از صفر، می‌توانید کدینگِ حساب‌ها یا گروه‌هایِ تفصیلیِ یک شرکتِ دیگر را کپی کنید. "
                "خودِ اشخاص (مشتری، تامین‌کننده، پرسنل) و اسنادِ حسابداری کپی نمی‌شوند.",
            ),
            (self.clone_source_combo, "شرکتی که کدینگ و تفصیلی‌هایش الگویِ این شرکتِ تازه می‌شود."),
            (
                self.clone_coa_checkbox,
                "اگر فعال باشد، کدِ حساب‌هایِ شرکتِ مبدأ عیناً برایِ این شرکتِ تازه ساخته می‌شود.",
            ),
            (
                self.clone_dimensions_checkbox,
                "اگر فعال باشد، حساب‌هایِ تفصیلی (کالا، بانک، صندوق، مرکزِ هزینه، پروژه و گروه‌هایِ ساده) "
                "از شرکتِ مبدأ کپی می‌شوند.",
            ),
        ])

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        title = QLabel("شرکت‌ها")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)
        return panel

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        self.form_title = QLabel("شرکتِ جدید")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        self.code_field = QLineEdit()

        self.legal_name_field = QLineEdit()

        self.display_name_field = QLineEdit()

        self.currency_combo = QComboBox()

        self.language_combo = QComboBox()

        self.fy_month_field = QSpinBox()
        self.fy_month_field.setRange(1, 12)
        self.fy_month_field.setValue(1)

        self.fy_day_field = QSpinBox()
        self.fy_day_field.setRange(1, 31)
        self.fy_day_field.setValue(1)

        self.economic_code_field = PersianDigitLineEdit()

        self.registration_no_field = PersianDigitLineEdit()

        self.national_id_field = PersianDigitLineEdit()

        self.is_active_checkbox = QCheckBox("فعال")
        self.is_active_checkbox.setChecked(True)

        self.basic_grid = FieldGrid([
            FieldSpec("code", "کد", self.code_field, span=1),
            FieldSpec("legal_name", "نامِ حقوقی", self.legal_name_field, span=2),
            FieldSpec("display_name", "نامِ نمایشی", self.display_name_field, span=2),
            FieldSpec("currency", "ارزِ پایه", self.currency_combo, span=1),
            FieldSpec("language", "زبانِ پیش‌فرض", self.language_combo, span=1),
            FieldSpec("fy_month", "ماهِ شروعِ سالِ مالی", self.fy_month_field, span=1),
            FieldSpec("fy_day", "روزِ شروعِ سالِ مالی", self.fy_day_field, span=1),
            FieldSpec("economic_code", "کدِ اقتصادی", self.economic_code_field, span=1),
            FieldSpec("registration_no", "شماره‌ی ثبت", self.registration_no_field, span=1),
            FieldSpec("national_id", "شناسه‌ی ملی", self.national_id_field, span=1),
            FieldSpec("is_active", "", self.is_active_checkbox, span=3),
        ])
        layout.addWidget(self.basic_grid)
        self.register_field_grids("companies", [self.basic_grid])

        # طبقِ درخواستِ صریح: امکانِ ساختن شرکتِ تازه بر اساسِ کدینگ/گروه‌هایِ
        # تفصیلیِ یک شرکتِ موجود — فقط در حالتِ «شرکتِ جدید» معنا دارد (نه
        # ویرایش)، پس با ویرایش مخفی می‌شود.
        self.clone_section = QWidget()
        clone_layout = QVBoxLayout(self.clone_section)
        clone_layout.setContentsMargins(0, 0, 0, 0)
        clone_layout.setSpacing(6)

        self.clone_checkbox = QCheckBox("ایجاد بر اساسِ شرکتِ دیگر")
        self.clone_checkbox.toggled.connect(self._on_clone_checkbox_toggled)
        clone_layout.addWidget(self.clone_checkbox)

        clone_grid = QGridLayout()
        clone_grid.setSpacing(8)
        clone_grid.addWidget(QLabel("شرکتِ مبدأ"), 0, 0)
        self.clone_source_combo = QComboBox()
        clone_grid.addWidget(self.clone_source_combo, 0, 1)
        self.clone_coa_checkbox = QCheckBox("کدینگِ حساب‌ها")
        self.clone_coa_checkbox.setChecked(True)
        clone_grid.addWidget(self.clone_coa_checkbox, 1, 1)
        self.clone_dimensions_checkbox = QCheckBox("گروه‌هایِ تفصیلی")
        self.clone_dimensions_checkbox.setChecked(True)
        clone_grid.addWidget(self.clone_dimensions_checkbox, 2, 1)
        clone_layout.addLayout(clone_grid)
        self._set_clone_options_visible(False)

        layout.addWidget(self.clone_section)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        save_button = QPushButton("💾")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(48)
        save_button.setToolTip("ذخیره")
        save_button.clicked.connect(self._save)

        cancel_button = QPushButton("↩️")
        cancel_button.setObjectName("iconButton")
        cancel_button.setFixedWidth(44)
        cancel_button.setToolTip("انصراف")
        cancel_button.clicked.connect(self._reset_form)

        layout.addStretch(1)
        return wrap_scrollable_with_footer(panel, [save_button, cancel_button])

    def refresh(self) -> None:
        self._currency_options = companies_service.list_currencies()
        self._language_options = languages_service.list_languages()
        self._fill_combo(self.currency_combo, [(c.currency_id, c.iso_code) for c in self._currency_options])
        self._fill_combo(self.language_combo, [(l.language_id, l.native_name) for l in self._language_options])

        self._reset_form()
        self._rows = companies_service.list_companies()
        self._fill_combo(self.clone_source_combo, [(c.company_id, c.display_name) for c in self._rows])
        self.table.setRowCount(len(self._rows))
        for row_index, company in enumerate(self._rows):
            values = [
                "بله" if company.is_active else "خیر",
                company.default_language_name,
                company.base_currency_code,
                company.display_name,
                company.code,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, company.company_id)
                self.table.setItem(row_index, col_index, item)

    @staticmethod
    def _fill_combo(combo: QComboBox, options: list[tuple[int, str]]) -> None:
        combo.clear()
        for value, label in options:
            combo.addItem(label, value)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        company_id = self.table.item(row, 0).data(Qt.UserRole)
        company = next((r for r in self._rows if r.company_id == company_id), None)
        if company is not None:
            self._load_into_form(company)

    def _load_into_form(self, company: companies_service.CompanyRow) -> None:
        self._editing_id = company.company_id
        self.form_title.setText(f"ویرایشِ شرکت — {company.display_name}")
        self.status_label.setText("")
        self.code_field.setText(company.code)
        self.code_field.setEnabled(False)
        self.legal_name_field.setText(company.legal_name)
        self.display_name_field.setText(company.display_name)
        self._select_combo(self.currency_combo, company.base_currency_id)
        self._select_combo(self.language_combo, company.default_language_id)
        self.fy_month_field.setValue(company.fiscal_year_start_month)
        self.fy_day_field.setValue(company.fiscal_year_start_day)
        self.economic_code_field.setText(company.economic_code or "")
        self.registration_no_field.setText(company.registration_no or "")
        self.national_id_field.setText(company.national_id or "")
        self.is_active_checkbox.setChecked(company.is_active)
        self.clone_section.setVisible(False)

    @staticmethod
    def _select_combo(combo: QComboBox, value: int) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _set_clone_options_visible(self, visible: bool) -> None:
        self.clone_source_combo.setVisible(visible)
        self.clone_coa_checkbox.setVisible(visible)
        self.clone_dimensions_checkbox.setVisible(visible)

    def _on_clone_checkbox_toggled(self, checked: bool) -> None:
        self._set_clone_options_visible(checked)

    def _reset_form(self) -> None:
        self._editing_id = None
        self.form_title.setText("شرکتِ جدید")
        self.status_label.setText("")
        self.code_field.clear()
        self.code_field.setEnabled(True)
        self.legal_name_field.clear()
        self.display_name_field.clear()
        if self.currency_combo.count():
            self.currency_combo.setCurrentIndex(0)
        if self.language_combo.count():
            self.language_combo.setCurrentIndex(0)
        self.fy_month_field.setValue(1)
        self.fy_day_field.setValue(1)
        self.economic_code_field.clear()
        self.registration_no_field.clear()
        self.national_id_field.clear()
        self.is_active_checkbox.setChecked(True)
        self.table.clearSelection()
        self.clone_section.setVisible(True)
        self.clone_checkbox.setChecked(False)
        if self.clone_source_combo.count():
            self.clone_source_combo.setCurrentIndex(0)

    def _save(self) -> None:
        legal_name = self.legal_name_field.text().strip()
        display_name = self.display_name_field.text().strip()
        if not legal_name or not display_name:
            self.status_label.setText("نامِ حقوقی و نامِ نمایشی را وارد کنید.")
            return

        base_currency_id = self.currency_combo.currentData()
        default_language_id = self.language_combo.currentData()

        try:
            if self._editing_id is not None:
                companies_service.update_company(
                    self._editing_id,
                    legal_name,
                    display_name,
                    base_currency_id,
                    default_language_id,
                    self.fy_month_field.value(),
                    self.fy_day_field.value(),
                    self.is_active_checkbox.isChecked(),
                    economic_code=self.economic_code_field.text().strip() or None,
                    registration_no=self.registration_no_field.text().strip() or None,
                    national_id=self.national_id_field.text().strip() or None,
                )
            else:
                code = self.code_field.text().strip()
                if not code:
                    self.status_label.setText("کد را وارد کنید.")
                    return
                new_company = companies_service.create_company(
                    code,
                    legal_name,
                    display_name,
                    base_currency_id,
                    default_language_id,
                    self.fy_month_field.value(),
                    self.fy_day_field.value(),
                    economic_code=self.economic_code_field.text().strip() or None,
                    registration_no=self.registration_no_field.text().strip() or None,
                    national_id=self.national_id_field.text().strip() or None,
                )
                if app_session.current_user is not None:
                    users_service.grant_company_access(app_session.current_user.user_id, new_company.company_id)
                clone_requested = self.clone_checkbox.isChecked()
                clone_error = None
                if clone_requested:
                    source_company_id = self.clone_source_combo.currentData()
                    if source_company_id is not None:
                        try:
                            company_cloning.clone_company_setup(
                                source_company_id,
                                new_company.company_id,
                                copy_coa=self.clone_coa_checkbox.isChecked(),
                                copy_detail_dimensions=self.clone_dimensions_checkbox.isChecked(),
                            )
                        except ValueError as exc:
                            clone_error = str(exc)
                self.refresh()
                if clone_error is not None:
                    theme.set_status_label(
                        self.status_label, f"شرکت ایجاد شد؛ ولی کپیِ کدینگ/تفصیلی‌ها ناموفق بود: {clone_error}", ok=False
                    )
                elif clone_requested:
                    theme.set_status_label(self.status_label, "شرکت ایجاد شد و کدینگ/گروه‌هایِ تفصیلی از شرکتِ مبدأ کپی شد.", ok=True)
                return
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return

        self.refresh()
