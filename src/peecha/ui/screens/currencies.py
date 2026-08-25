"""مدیریتِ ارزها — معادلِ Qt برایِ currencies.py/.kv در Kivy.

طبقِ درخواستِ صریح («در جدولِ ارزها بتوان نرخِ تبدیل را هم دستی وارد کرد
و هم اتوماتیک از صرافی/بانکِ مرکزی گرفت»)، علاوه‌بر فهرستِ سراسریِ ارزها
(core.currencies)، برایِ ارزهایِ غیرِپایه یک بخشِ «فعال‌سازی برایِ این
شرکت + تاریخچه‌یِ نرخِ روزانه» هم اضافه شده — چون نرخِ تبدیل، مفهومی
مخصوصِ هر شرکت است (نه سراسری)."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.services import currencies as currencies_service
from peecha.ui.widgets import FieldGrid, FieldHelpMixin, FieldSpec, LayoutEditMixin, JalaliDateEdit, wrap_scrollable_with_footer

_COLUMNS = ["فعال", "رقمِ اعشار", "نماد", "کدِ ارز"]
_RATE_COLUMNS = ["تاریخ", "نرخ به ارزِ پایه"]

# طبقِ درخواستِ صریح («نرخِ بازارِ آزاد یا دولتی انتخابی باشه»): navasan.tech
# بینِ نرخِ بازارِ آزاد و دولتی/نیمایی تفکیک دارد؛ این دو گزینه فقط برایِ
# دلار (پرکاربردترین حالت) حدسِ اولیه‌اند — نام‌گذاریِ آیتم‌ها بینِ پلن‌هایِ
# navasan.tech فرق دارد، پس گزینه‌ی «سفارشی» هم هست تا کاربر خودش کلیدِ
# دقیق را از داشبوردِ حسابش وارد کند.
_NAVASAN_RATE_TYPES = [
    ("usd_sell", "بازارِ آزاد (پیش‌فرضِ حدسی: usd_sell)"),
    ("usd_harat_naghdi", "دولتی/نیمایی (پیش‌فرضِ حدسی: usd_harat_naghdi)"),
    ("", "سفارشی — کلیدِ آیتم را خودم وارد می‌کنم"),
]
_RATE_SOURCE_GLOBAL = "GLOBAL"
_RATE_SOURCE_NAVASAN = "NAVASAN"


class CurrenciesScreen(FieldHelpMixin, LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[currencies_service.CurrencyRow] = []
        self._editing_id: int | None = None

        self._selected_currency: currencies_service.CurrencyRow | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=1)
        outer.addWidget(self._build_rate_panel(), stretch=2)

        self.set_field_help([
            (
                self.iso_code_field,
                "کدِ استانداردِ سه‌حرفیِ ارز — مثلاً IRR برایِ ریال یا USD برایِ دلار. "
                "همین کد در فهرستِ «ارزِ پایه»یِ هر شرکت و همه‌جایِ برنامه استفاده می‌شود.",
            ),
            (self.symbol_field, "نمادِ نمایشیِ ارز، مثلاً ﷼ یا $. فقط ظاهری است و در محاسبات اثر ندارد."),
            (
                self.decimal_places_field,
                "چند رقمِ اعشار برایِ مبالغِ این ارز نشان داده شود. برایِ ریال معمولاً صفر است. "
                "برایِ دلار معمولاً ۲. تغییرِ این عدد فقط نمایش را عوض می‌کند، نه مبالغِ ذخیره‌شده را.",
            ),
            (
                self.is_active_checkbox,
                "ارزهایِ غیرِفعال دیگر در فهرستِ «ارزِ پایه» هنگامِ ساختنِ شرکتِ تازه نشان داده نمی‌شوند. "
                "شرکت‌هایی که از قبل با این ارز کار می‌کنند مشکلی پیدا نمی‌کنند.",
            ),
        ])

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("ارزها")
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
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.form_title = QLabel("ارزِ جدید")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        self.iso_code_field = QLineEdit()

        self.symbol_field = QLineEdit()

        self.decimal_places_field = QSpinBox()
        self.decimal_places_field.setRange(0, 6)

        self.is_active_checkbox = QCheckBox("فعال")
        self.is_active_checkbox.setChecked(True)

        self.basic_grid = FieldGrid([
            FieldSpec("iso_code", "کدِ ارز (مثلاً IRR)", self.iso_code_field, span=1),
            FieldSpec("symbol", "نماد", self.symbol_field, span=1),
            FieldSpec("decimal_places", "رقمِ اعشار", self.decimal_places_field, span=1),
            FieldSpec("is_active", "", self.is_active_checkbox, span=3),
        ])
        layout.addWidget(self.basic_grid)
        self.register_field_grids("currencies", [self.basic_grid])

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

        self.delete_button = QPushButton("🗑️")
        self.delete_button.setObjectName("dangerIconButton")
        self.delete_button.setFixedWidth(44)
        self.delete_button.setToolTip("حذف")
        self.delete_button.clicked.connect(self._delete)
        self.delete_button.setVisible(False)

        layout.addStretch(1)
        return wrap_scrollable_with_footer(panel, [save_button, cancel_button, self.delete_button])

    def _build_rate_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.rate_panel_title = QLabel("نرخِ ارز")
        self.rate_panel_title.setObjectName("pageTitle")
        layout.addWidget(self.rate_panel_title)

        self.rate_panel_hint = QLabel("یک ارزِ غیرِپایه از فهرستِ سمتِ راست انتخاب کنید.")
        self.rate_panel_hint.setObjectName("sectionHint")
        self.rate_panel_hint.setWordWrap(True)
        layout.addWidget(self.rate_panel_hint)

        self.rate_panel_content = QWidget()
        content_layout = QVBoxLayout(self.rate_panel_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)

        self.enable_for_company_checkbox = QCheckBox("فعال برایِ شرکتِ جاری")
        self.enable_for_company_checkbox.toggled.connect(self._on_enable_for_company_toggled)
        content_layout.addWidget(self.enable_for_company_checkbox)

        self.rate_table = QTableWidget(0, len(_RATE_COLUMNS))
        self.rate_table.setHorizontalHeaderLabels(_RATE_COLUMNS)
        self.rate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rate_table.verticalHeader().setVisible(False)
        self.rate_table.horizontalHeader().setStretchLastSection(True)
        self.rate_table.setMaximumHeight(160)
        content_layout.addWidget(self.rate_table)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        content_layout.addWidget(divider)

        new_rate_row = QHBoxLayout()
        new_rate_row.addWidget(QLabel("تاریخ:"))
        self.rate_date_field = JalaliDateEdit()
        new_rate_row.addWidget(self.rate_date_field)
        new_rate_row.addWidget(QLabel("نرخ:"))
        self.rate_value_field = QLineEdit()
        new_rate_row.addWidget(self.rate_value_field, stretch=1)
        content_layout.addLayout(new_rate_row)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("منبعِ نرخِ خودکار:"))
        self.rate_source_combo = QComboBox()
        self.rate_source_combo.addItem("سرویسِ عمومیِ جهانی (بدونِ کلید)", _RATE_SOURCE_GLOBAL)
        self.rate_source_combo.addItem("navasan.tech (اختصاصیِ ریال — بازارِ آزاد/دولتی)", _RATE_SOURCE_NAVASAN)
        self.rate_source_combo.currentIndexChanged.connect(self._on_rate_source_changed)
        source_row.addWidget(self.rate_source_combo, stretch=1)
        content_layout.addLayout(source_row)

        self.navasan_panel = QWidget()
        navasan_layout = QVBoxLayout(self.navasan_panel)
        navasan_layout.setContentsMargins(0, 0, 0, 0)
        navasan_layout.setSpacing(6)

        navasan_key_row = QHBoxLayout()
        navasan_key_row.addWidget(QLabel("کلیدِ API:"))
        self.navasan_api_key_field = QLineEdit()
        self.navasan_api_key_field.setEchoMode(QLineEdit.Password)
        self.navasan_api_key_field.editingFinished.connect(self._on_navasan_api_key_changed)
        navasan_key_row.addWidget(self.navasan_api_key_field, stretch=1)
        navasan_layout.addLayout(navasan_key_row)

        navasan_type_row = QHBoxLayout()
        navasan_type_row.addWidget(QLabel("نوعِ نرخ:"))
        self.navasan_rate_type_combo = QComboBox()
        for item_key, label in _NAVASAN_RATE_TYPES:
            self.navasan_rate_type_combo.addItem(label, item_key)
        self.navasan_rate_type_combo.currentIndexChanged.connect(self._on_navasan_rate_type_changed)
        navasan_type_row.addWidget(self.navasan_rate_type_combo, stretch=1)
        navasan_layout.addLayout(navasan_type_row)

        self.navasan_custom_item_field = QLineEdit()
        self.navasan_custom_item_field.setPlaceholderText("کلیدِ آیتمِ navasan.tech، مثلاً usd_sell")
        self.navasan_custom_item_field.editingFinished.connect(
            lambda: QSettings("Peecha", "PeechaERP").setValue(
                "fx/navasan_custom_item", self.navasan_custom_item_field.text().strip()
            )
        )
        navasan_layout.addWidget(self.navasan_custom_item_field)

        navasan_hint = QLabel(
            "نام‌هایِ پیش‌فرضِ «بازارِ آزاد»/«دولتی» حدسی‌اند (فقط برایِ دلار). اگر جواب نداد یا ارزِ دیگری "
            "می‌خواهید، کلیدِ دقیقِ آیتم را از داشبوردِ حسابِ خودتان در navasan.tech بردارید و این‌جا "
            "(«سفارشی») وارد کنید."
        )
        navasan_hint.setObjectName("sectionHint")
        navasan_hint.setWordWrap(True)
        navasan_layout.addWidget(navasan_hint)

        content_layout.addWidget(self.navasan_panel)
        self.navasan_panel.setVisible(False)

        fetch_row = QHBoxLayout()
        fetch_button = QPushButton("🌐 دریافتِ خودکار")
        fetch_button.setObjectName("flatButton")
        fetch_button.clicked.connect(self._on_fetch_live_rate)
        fetch_row.addWidget(fetch_button)
        fetch_row.addStretch(1)
        content_layout.addLayout(fetch_row)

        self.fetch_hint = QLabel("")
        self.fetch_hint.setObjectName("sectionHint")
        self.fetch_hint.setWordWrap(True)
        content_layout.addWidget(self.fetch_hint)
        self._update_fetch_hint()

        self.rate_status_label = QLabel("")
        self.rate_status_label.setObjectName("statusError")
        self.rate_status_label.setWordWrap(True)
        content_layout.addWidget(self.rate_status_label)

        save_rate_button = QPushButton("➕")
        save_rate_button.setObjectName("primaryIconButton")
        save_rate_button.setFixedWidth(48)
        save_rate_button.setToolTip("ثبتِ نرخ")
        save_rate_button.clicked.connect(self._on_save_rate)
        content_layout.addWidget(save_rate_button)

        content_layout.addStretch(1)
        layout.addWidget(self.rate_panel_content)
        self.rate_panel_content.setVisible(False)
        return panel

    def refresh(self) -> None:
        self._reset_form()
        self._rows = currencies_service.list_all_currencies()
        self.table.setRowCount(len(self._rows))
        for row_index, currency in enumerate(self._rows):
            values = [
                "بله" if currency.is_active else "خیر",
                str(currency.decimal_places),
                currency.symbol or "—",
                currency.iso_code,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, currency.currency_id)
                self.table.setItem(row_index, col_index, item)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        currency_id = self.table.item(row, 0).data(Qt.UserRole)
        currency = next((r for r in self._rows if r.currency_id == currency_id), None)
        if currency is not None:
            self._load_into_form(currency)

    def _load_into_form(self, currency: currencies_service.CurrencyRow) -> None:
        self._editing_id = currency.currency_id
        self.form_title.setText(f"ویرایشِ ارز — {currency.iso_code}")
        self.status_label.setText("")
        self.iso_code_field.setText(currency.iso_code)
        self.symbol_field.setText(currency.symbol or "")
        self.decimal_places_field.setValue(currency.decimal_places)
        self.is_active_checkbox.setChecked(currency.is_active)
        self.delete_button.setVisible(True)
        self._selected_currency = currency
        self._refresh_rate_panel()

    def _reset_form(self) -> None:
        self._editing_id = None
        self.form_title.setText("ارزِ جدید")
        self.status_label.setText("")
        self.iso_code_field.clear()
        self.symbol_field.clear()
        self.decimal_places_field.setValue(0)
        self.is_active_checkbox.setChecked(True)
        self.delete_button.setVisible(False)
        self.table.clearSelection()
        self._selected_currency = None
        self._refresh_rate_panel()

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def _refresh_rate_panel(self) -> None:
        company_id = self._company_id()
        currency = self._selected_currency
        is_base = (
            currency is not None
            and session.current_company is not None
            and currency.currency_id == session.current_company.base_currency_id
        )
        if currency is None or company_id is None:
            self.rate_panel_content.setVisible(False)
            self.rate_panel_hint.setVisible(True)
            self.rate_panel_hint.setText("یک ارزِ غیرِپایه از فهرستِ سمتِ راست انتخاب کنید.")
            return
        if is_base:
            self.rate_panel_content.setVisible(False)
            self.rate_panel_hint.setVisible(True)
            self.rate_panel_hint.setText(f"«{currency.iso_code}» ارزِ پایه‌یِ شرکتِ جاری است — نرخ همیشه ۱ است.")
            return

        self.rate_panel_hint.setVisible(False)
        self.rate_panel_content.setVisible(True)
        self.rate_panel_title.setText(f"نرخِ ارز — {currency.iso_code}")
        self.rate_status_label.setText("")

        company_currencies = currencies_service.list_company_currencies(company_id)
        row = next((r for r in company_currencies if r.currency_id == currency.currency_id), None)
        self.enable_for_company_checkbox.blockSignals(True)
        self.enable_for_company_checkbox.setChecked(bool(row and row.is_enabled))
        self.enable_for_company_checkbox.blockSignals(False)

        self._reload_rate_table()
        self.rate_date_field.setDate(datetime.date.today())
        self.rate_value_field.clear()

        settings = QSettings("Peecha", "PeechaERP")
        self.rate_source_combo.blockSignals(True)
        source_index = self.rate_source_combo.findData(settings.value("fx/source", _RATE_SOURCE_GLOBAL))
        self.rate_source_combo.setCurrentIndex(max(source_index, 0))
        self.rate_source_combo.blockSignals(False)
        self.navasan_api_key_field.setText(settings.value("fx/navasan_api_key", ""))
        self.navasan_rate_type_combo.blockSignals(True)
        type_index = self.navasan_rate_type_combo.findData(settings.value("fx/navasan_item_key", "usd_sell"))
        self.navasan_rate_type_combo.setCurrentIndex(max(type_index, 0))
        self.navasan_rate_type_combo.blockSignals(False)
        self.navasan_custom_item_field.setText(settings.value("fx/navasan_custom_item", ""))
        self._on_navasan_rate_type_changed()
        self.navasan_panel.setVisible(self.rate_source_combo.currentData() == _RATE_SOURCE_NAVASAN)
        self._update_fetch_hint()

    def _reload_rate_table(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_currency is None:
            return
        rates = currencies_service.list_exchange_rates(company_id, self._selected_currency.currency_id)
        self.rate_table.setRowCount(len(rates))
        for row_index, rate in enumerate(rates):
            date_item = QTableWidgetItem(numerals.format_jalali_date(rate.rate_date))
            rate_item = QTableWidgetItem(numerals.format_amount(rate.rate_to_base))
            self.rate_table.setItem(row_index, 0, date_item)
            self.rate_table.setItem(row_index, 1, rate_item)

    def _on_enable_for_company_toggled(self, checked: bool) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_currency is None:
            return
        currencies_service.set_company_currency(company_id, self._selected_currency.currency_id, checked)

    def _update_fetch_hint(self) -> None:
        if self.rate_source_combo.currentData() == _RATE_SOURCE_NAVASAN:
            self.fetch_hint.setText(
                "navasan.tech نرخِ اختصاصیِ ریال می‌دهد و بینِ بازارِ آزاد/دولتی تفکیک دارد — نیازمندِ کلیدِ API "
                "است (رایگان از سایتِ خودشان بگیرید). این یک عددِ پیشنهادی است؛ قبل از ثبت بررسی کنید."
            )
        else:
            self.fetch_hint.setText(
                "نرخِ خودکار از یک سرویسِ عمومیِ نرخِ ارز گرفته می‌شود؛ برایِ ریال ممکن است در دسترس نباشد یا "
                "با نرخِ بازارِ آزاد فرق داشته باشد — قبل از ثبت آن را بررسی کنید."
            )

    def _on_rate_source_changed(self) -> None:
        is_navasan = self.rate_source_combo.currentData() == _RATE_SOURCE_NAVASAN
        self.navasan_panel.setVisible(is_navasan)
        self._update_fetch_hint()
        QSettings("Peecha", "PeechaERP").setValue("fx/source", self.rate_source_combo.currentData())

    def _on_navasan_api_key_changed(self) -> None:
        QSettings("Peecha", "PeechaERP").setValue("fx/navasan_api_key", self.navasan_api_key_field.text().strip())

    def _on_navasan_rate_type_changed(self) -> None:
        is_custom = self.navasan_rate_type_combo.currentData() == ""
        self.navasan_custom_item_field.setEnabled(is_custom)
        QSettings("Peecha", "PeechaERP").setValue("fx/navasan_item_key", self.navasan_rate_type_combo.currentData())

    def _navasan_item_key(self) -> str:
        preset = self.navasan_rate_type_combo.currentData()
        if preset:
            return preset
        item_key = self.navasan_custom_item_field.text().strip()
        QSettings("Peecha", "PeechaERP").setValue("fx/navasan_custom_item", item_key)
        return item_key

    def _on_fetch_live_rate(self) -> None:
        company = session.current_company
        if company is None or self._selected_currency is None:
            return
        self.rate_status_label.setText("")
        if self.rate_source_combo.currentData() == _RATE_SOURCE_NAVASAN:
            try:
                rate = currencies_service.fetch_navasan_rate(
                    self.navasan_api_key_field.text().strip(), self._navasan_item_key()
                )
            except ValueError as exc:
                self.rate_status_label.setText(str(exc))
                return
            self.rate_value_field.setText(numerals.format_amount(rate))
            return

        base_currency = next(
            (c for c in currencies_service.list_all_currencies() if c.currency_id == company.base_currency_id), None
        )
        if base_currency is None:
            return
        try:
            rate = currencies_service.fetch_live_rate(base_currency.iso_code, self._selected_currency.iso_code)
        except ValueError as exc:
            self.rate_status_label.setText(str(exc))
            return
        self.rate_status_label.setText("")
        self.rate_value_field.setText(numerals.format_amount(rate))

    def _on_save_rate(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_currency is None:
            return
        try:
            rate_value = numerals.parse_decimal(self.rate_value_field.text())
            currencies_service.set_exchange_rate(
                company_id, self._selected_currency.currency_id, self.rate_date_field.date(), rate_value
            )
        except ValueError as exc:
            self.rate_status_label.setText(str(exc))
            return
        self.rate_status_label.setText("")
        self.rate_value_field.clear()
        self._reload_rate_table()

    def _save(self) -> None:
        iso_code = self.iso_code_field.text().strip()
        if not iso_code:
            self.status_label.setText("کدِ ارز را وارد کنید.")
            return
        symbol = self.symbol_field.text().strip() or None
        decimal_places = self.decimal_places_field.value()

        created_currency = None
        try:
            if self._editing_id is not None:
                currencies_service.update_currency(
                    self._editing_id, iso_code, symbol, decimal_places, self.is_active_checkbox.isChecked()
                )
            else:
                created_currency = currencies_service.create_currency(iso_code, symbol, decimal_places)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return

        # طبقِ گزارشِ صریح («ارزهایی که تعریف کردیم در بالای سند نمی‌آید»):
        # ارزِ تازه‌ساخته باید بلافاصله برایِ شرکتِ جاری هم فعال شود، وگرنه
        # فقط سراسری تعریف شده و تا وقتی کسی جداگانه رویِ ردیفش کلیک و
        # تیکِ «فعال برایِ شرکتِ جاری» را نزند، در فرمِ سند نمی‌آید.
        company_id = self._company_id()
        if created_currency is not None and company_id is not None:
            try:
                currencies_service.set_company_currency(company_id, created_currency.currency_id, True)
            except ValueError:
                pass

        self.refresh()

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        confirm = QMessageBox.question(
            self, "حذفِ ارز", "این ارز حذف شود؟", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            currencies_service.delete_currency(self._editing_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
