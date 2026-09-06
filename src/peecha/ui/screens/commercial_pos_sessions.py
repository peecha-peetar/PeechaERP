"""ترمینال‌ها و شیفت‌هایِ صندوق (مرحلهٔ ۷) — بازکردن/بستنِ شیفت، آزادسازیِ
مغایرت، و تنظیماتِ فاکتورِ صندوق (تک‌فروشی). طبقِ درخواستِ صریح
(«اصطلاحِ جلسه گنگ است»)، برچسبِ نمایشی «شیفت» است -- شناسه‌هایِ داخلیِ
کد (session_id, PosSession) بدونِ تغییر مانده‌اند.

طبقِ بازخوردِ صریحِ کاربر («منویِ تازه اضافه نکن -- همه‌یِ تنظیماتِ
تک‌فروشی باید همین‌جا، در تب‌هایِ مختلف بیاید»)، هیچ نویِ جداگانه‌ای
برایِ تنظیماتِ POS در ناوبری وجود ندارد -- گروه‌هایِ POS و اندازهٔ
کلیدهایِ فوری هم به‌عنوانِ تب در همین صفحه (بخشِ «تنظیماتِ تک‌فروشی»)
جا گرفته‌اند، نه یک صفحه/منویِ مستقل."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session as app_session
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_pos as pos_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_locations as locations_service
from peecha.ui.screens.commercial_pos_menu_groups import CommercialPosMenuGroupsScreen
from peecha.ui.widgets import wrap_scrollable

_SESSION_STATUS_LABELS = {"OPEN": "باز", "CLOSED": "بسته"}


class CommercialPosSessionsScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._terminals: list = []
        self._selected_terminal_id: int | None = None

        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(16)

        left = QVBoxLayout()
        title = QLabel("ترمینال‌هایِ صندوق")
        title.setObjectName("pageTitle")
        left.addWidget(title)

        self.terminals_table = QTableWidget(0, 2)
        self.terminals_table.setHorizontalHeaderLabels(["کد", "نام"])
        self.terminals_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.terminals_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.terminals_table.verticalHeader().setVisible(False)
        self.terminals_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.terminals_table.cellClicked.connect(self._on_terminal_selected)
        left.addWidget(self.terminals_table, stretch=1)

        new_terminal_box = QHBoxLayout()
        self.terminal_code_field = QLineEdit()
        self.terminal_code_field.setPlaceholderText("کد")
        new_terminal_box.addWidget(self.terminal_code_field)
        self.terminal_name_field = QLineEdit()
        self.terminal_name_field.setPlaceholderText("نام")
        new_terminal_box.addWidget(self.terminal_name_field)
        self.terminal_warehouse_combo = QComboBox()
        new_terminal_box.addWidget(self.terminal_warehouse_combo)
        add_terminal_button = QPushButton("➕")
        add_terminal_button.setObjectName("primaryIconButton")
        add_terminal_button.setFixedWidth(48)
        add_terminal_button.setToolTip("ترمینالِ تازه")
        add_terminal_button.clicked.connect(self._add_terminal)
        new_terminal_box.addWidget(add_terminal_button)
        left.addLayout(new_terminal_box)

        settings_title = QLabel("تنظیماتِ فاکتورِ صندوق (تک‌فروشی)")
        settings_title.setObjectName("sectionTitle")
        left.addWidget(settings_title)

        self.settings_tabs = QTabWidget()

        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        settings_box = QHBoxLayout()
        settings_box.addWidget(QLabel("مشتریِ متفرقهٔ پیش‌فرض"))
        self.guest_customer_combo = QComboBox()
        settings_box.addWidget(self.guest_customer_combo, stretch=1)
        settings_box.addWidget(QLabel("آستانهٔ مغایرت"))
        self.threshold_field = QDoubleSpinBox()
        self.threshold_field.setDecimals(2)
        self.threshold_field.setRange(0, 999999999)
        settings_box.addWidget(self.threshold_field)
        save_settings_button = QPushButton("💾")
        save_settings_button.setObjectName("iconButton")
        save_settings_button.setFixedWidth(44)
        save_settings_button.setToolTip("ذخیره")
        save_settings_button.clicked.connect(self._save_settings)
        settings_box.addWidget(save_settings_button)
        general_layout.addLayout(settings_box)
        general_layout.addStretch(1)
        self.settings_tabs.addTab(general_tab, "عمومی")

        retail_tab = QWidget()
        retail_layout = QVBoxLayout(retail_tab)
        quick_settings_title = QLabel("اندازه/جهتِ کلیدهایِ فوریِ صفحه‌یِ فروش (سراسریِ شرکت -- نه به‌ازایِ هر کاربر)")
        quick_settings_title.setObjectName("sectionHint")
        quick_settings_title.setWordWrap(True)
        retail_layout.addWidget(quick_settings_title)
        quick_settings_box = QHBoxLayout()
        quick_settings_box.addWidget(QLabel("عرض"))
        self.quick_button_width_field = QSpinBox()
        self.quick_button_width_field.setRange(60, 400)
        quick_settings_box.addWidget(self.quick_button_width_field)
        quick_settings_box.addWidget(QLabel("ارتفاع"))
        self.quick_button_height_field = QSpinBox()
        self.quick_button_height_field.setRange(40, 300)
        quick_settings_box.addWidget(self.quick_button_height_field)
        quick_settings_box.addWidget(QLabel("اندازهٔ فونت"))
        self.quick_button_font_size_field = QSpinBox()
        self.quick_button_font_size_field.setRange(6, 32)
        quick_settings_box.addWidget(self.quick_button_font_size_field)
        quick_settings_box.addWidget(QLabel("تعدادِ ستون"))
        self.quick_grid_columns_field = QSpinBox()
        self.quick_grid_columns_field.setRange(2, 12)
        quick_settings_box.addWidget(self.quick_grid_columns_field)
        save_quick_settings_button = QPushButton("💾")
        save_quick_settings_button.setObjectName("iconButton")
        save_quick_settings_button.setFixedWidth(44)
        save_quick_settings_button.setToolTip("ذخیره")
        save_quick_settings_button.clicked.connect(self._save_settings)
        quick_settings_box.addWidget(save_quick_settings_button)
        retail_layout.addLayout(quick_settings_box)

        # طبقِ درخواستِ صریح («دلیلی نداره اندازهٔ عرض/ارتفاعِ کلیدِ فوری در
        # خودِ فرمِ فاکتور باشه -- باید به تنظیمات منتقل بشه»): برخلافِ
        # کنترل‌هایِ بالا (سراسریِ شرکت)، این دو فقط رویِ حسابِ کاربرِ
        # جاری اثر می‌گذارد (PosCashierSettings.quick_button_*_override) --
        # قبلاً این دو اسپین‌باکس مستقیماً در commercial_pos_sale.py بود.
        my_size_title = QLabel("اندازهٔ کلیدهایِ فوریِ من (فقط برایِ حسابِ جاری -- بازنویسیِ اندازهٔ سراسریِ بالا)")
        my_size_title.setObjectName("sectionHint")
        my_size_title.setWordWrap(True)
        retail_layout.addWidget(my_size_title)
        my_size_box = QHBoxLayout()
        my_size_box.addWidget(QLabel("عرض"))
        self.my_quick_button_width_field = QSpinBox()
        self.my_quick_button_width_field.setRange(0, 400)
        self.my_quick_button_width_field.setSpecialValueText("پیش‌فرض")
        my_size_box.addWidget(self.my_quick_button_width_field)
        my_size_box.addWidget(QLabel("ارتفاع"))
        self.my_quick_button_height_field = QSpinBox()
        self.my_quick_button_height_field.setRange(0, 300)
        self.my_quick_button_height_field.setSpecialValueText("پیش‌فرض")
        my_size_box.addWidget(self.my_quick_button_height_field)
        save_my_size_button = QPushButton("💾")
        save_my_size_button.setObjectName("iconButton")
        save_my_size_button.setFixedWidth(44)
        save_my_size_button.setToolTip("ذخیره (فقط برایِ من)")
        save_my_size_button.clicked.connect(self._save_my_quick_button_size)
        my_size_box.addWidget(save_my_size_button)
        my_size_box.addStretch(1)
        retail_layout.addLayout(my_size_box)

        # طبقِ درخواستِ صریح («کلیدهایِ فوری از سمتِ راست/چپ، عمودی/افقی
        # در لوکیشن‌هایِ مختلفِ صفحه و ترازبندی‌هایِ مختلف قرار بگیرد»).
        layout_settings_box = QHBoxLayout()
        layout_settings_box.addWidget(QLabel("جایگاهِ منویِ دسترسیِ‌سریع"))
        self.quick_access_position_combo = QComboBox()
        self.quick_access_position_combo.addItem("چپِ صفحه", "LEFT")
        self.quick_access_position_combo.addItem("راستِ صفحه", "RIGHT")
        layout_settings_box.addWidget(self.quick_access_position_combo)
        layout_settings_box.addWidget(QLabel("جهتِ چیدمانِ کلیدها"))
        self.quick_access_orientation_combo = QComboBox()
        self.quick_access_orientation_combo.addItem("افقی", "HORIZONTAL")
        self.quick_access_orientation_combo.addItem("عمودی", "VERTICAL")
        layout_settings_box.addWidget(self.quick_access_orientation_combo)
        save_layout_settings_button = QPushButton("💾")
        save_layout_settings_button.setObjectName("iconButton")
        save_layout_settings_button.setFixedWidth(44)
        save_layout_settings_button.setToolTip("ذخیره")
        save_layout_settings_button.clicked.connect(self._save_settings)
        layout_settings_box.addWidget(save_layout_settings_button)
        layout_settings_box.addStretch(1)
        retail_layout.addLayout(layout_settings_box)

        # طبقِ بازبینیِ عکس‌هایِ تنظیماتِ نرم‌افزارِ مرجع (تنظیماتِ
        # عمومیِ فاکتور/تنظیماتِ تک‌فروشی) -- فقط مواردِ واقعاً قابلِ‌اجرا
        # و مرتبط با دامنهٔ فعلی، طبقِ لیست/پیشنهادِ ارائه‌شده به کاربر.
        toggles_box = QHBoxLayout()
        self.allow_price_override_checkbox = QCheckBox("اجازهٔ تغییرِ قیمت توسط کاربر")
        toggles_box.addWidget(self.allow_price_override_checkbox)
        self.allow_discount_override_checkbox = QCheckBox("اجازهٔ تغییرِ تخفیف توسط کاربر")
        toggles_box.addWidget(self.allow_discount_override_checkbox)
        self.quick_access_enabled_checkbox = QCheckBox("نمایشِ منویِ دسترسیِ‌سریع")
        toggles_box.addWidget(self.quick_access_enabled_checkbox)
        self.scan_beep_enabled_checkbox = QCheckBox("بوقِ تاییدِ اسکن/افزودن")
        toggles_box.addWidget(self.scan_beep_enabled_checkbox)
        toggles_box.addStretch(1)
        retail_layout.addLayout(toggles_box)

        # طبقِ درخواستِ صریح («جایی باشه که بتوان نمایش یا عدمِ نمایشِ
        # بخش‌هایِ فاکتورِ تک‌فروشی را انتخاب کرد»).
        visibility_box = QHBoxLayout()
        self.show_price_list_field_checkbox = QCheckBox("نمایشِ فیلدِ «فهرستِ قیمت»")
        visibility_box.addWidget(self.show_price_list_field_checkbox)
        self.show_tax_discount_breakdown_checkbox = QCheckBox("نمایشِ ریزِ تخفیف/مالیات در فوتر")
        visibility_box.addWidget(self.show_tax_discount_breakdown_checkbox)
        self.show_customer_credit_warning_checkbox = QCheckBox("نمایشِ هشدارِ سقفِ اعتبار")
        visibility_box.addWidget(self.show_customer_credit_warning_checkbox)
        visibility_box.addWidget(QLabel("تعدادِ فاکتورهایِ اخیر"))
        self.recent_invoices_count_field = QSpinBox()
        self.recent_invoices_count_field.setRange(1, 100)
        visibility_box.addWidget(self.recent_invoices_count_field)
        visibility_box.addStretch(1)
        retail_layout.addLayout(visibility_box)

        # طبقِ رفعِ باگِ واقعیِ گزارش‌شده («دکمهٔ تسویه با پرینت خیلی طول
        # می‌کشد»): چاپِ حرفه‌ایِ Jasper هر بار یک JVMِ تازه بالا می‌آورد.
        print_box = QHBoxLayout()
        self.fast_receipt_printing_checkbox = QCheckBox("چاپِ سریعِ فیش (بدونِ Jasper -- توصیه‌شده برایِ صندوق)")
        print_box.addWidget(self.fast_receipt_printing_checkbox)
        print_box.addStretch(1)
        retail_layout.addLayout(print_box)

        receipt_box = QHBoxLayout()
        receipt_box.addWidget(QLabel("سرتیترِ فیش"))
        self.receipt_header_field = QLineEdit()
        self.receipt_header_field.setPlaceholderText("مثلاً: با تشکر از خریدِ شما")
        receipt_box.addWidget(self.receipt_header_field, stretch=1)
        receipt_box.addWidget(QLabel("توضیحاتِ انتهایِ فیش"))
        self.receipt_footer_field = QLineEdit()
        receipt_box.addWidget(self.receipt_footer_field, stretch=1)
        save_toggles_button = QPushButton("💾")
        save_toggles_button.setObjectName("iconButton")
        save_toggles_button.setFixedWidth(44)
        save_toggles_button.setToolTip("ذخیره")
        save_toggles_button.clicked.connect(self._save_settings)
        receipt_box.addWidget(save_toggles_button)
        retail_layout.addLayout(receipt_box)

        self.menu_groups_panel = CommercialPosMenuGroupsScreen()
        retail_layout.addWidget(self.menu_groups_panel, stretch=1)
        self.settings_tabs.addTab(retail_tab, "تک‌فروشی")

        # طبقِ درخواستِ صریح («اگر تفصیلیِ پیش‌فرضِ روش‌هایِ دریافتِ
        # تفصیلی داشتند از تنظیمات بخواند... اگر مراکزِ هزینه و پروژه
        # داشتند در همان تنظیمات انجام شود»): پیش‌فرضِ تفصیلی/مرکزِ
        # هزینه/پروژهٔ هر روشِ دریافتِ فرمِ نحوهٔ تسویه‌یِ تک‌فروشی --
        # هربار در تنظیمات ذخیره شود، دیگر در فرمِ فروش پرسیده نمی‌شود
        # (ولی صندوق‌دار همچنان می‌تواند همان‌جا عوضش کند).
        self._settlement_default_widgets: list[tuple[str, QComboBox, QComboBox, QComboBox]] = []
        defaults_tab = QWidget()
        defaults_layout = QVBoxLayout(defaults_tab)
        defaults_hint = QLabel(
            "برایِ هر روشِ دریافتِ فرمِ «نحوهٔ تسویه»یِ تک‌فروشی، تفصیلیِ "
            "پیش‌فرض را این‌جا مشخص کنید -- صندوق‌دار دیگر هر بار در لحظهٔ "
            "فروش پرسیده نمی‌شود (ولی همان‌جا هم می‌تواند عوضش کند). "
            "مرکزِ هزینه/پروژه هم فقط وقتی فعال است که معینِ همان روش "
            "این ابعاد را الزامی کرده باشد."
        )
        defaults_hint.setObjectName("sectionHint")
        defaults_hint.setWordWrap(True)
        defaults_layout.addWidget(defaults_hint)
        self.settlement_defaults_table = QTableWidget(0, 4)
        self.settlement_defaults_table.setHorizontalHeaderLabels(["روش", "تفصیلیِ پیش‌فرض", "مرکزِ هزینه", "پروژه"])
        self.settlement_defaults_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.settlement_defaults_table.verticalHeader().setVisible(False)
        # طبقِ رفعِ باگِ واقعیِ گزارش‌شده («ارتفاعِ فیلدها خیلی کمه»):
        # ارتفاعِ پیش‌فرضِ ردیف (بر مبنایِ فقط متنِ سلولِ اول) برایِ جا
        # دادنِ سه QComboBoxِ کاملِ سلول‌هایِ دیگر کافی نبود -- هم‌الگو با
        # رفعِ همین باگ در commercial_documents_list.py.
        self.settlement_defaults_table.verticalHeader().setMinimumSectionSize(40)
        self.settlement_defaults_table.verticalHeader().setDefaultSectionSize(40)
        sd_header = self.settlement_defaults_table.horizontalHeader()
        sd_header.setSectionResizeMode(0, QHeaderView.Interactive)
        self.settlement_defaults_table.setColumnWidth(0, 160)
        for col in (1, 2, 3):
            sd_header.setSectionResizeMode(col, QHeaderView.Stretch)
        defaults_layout.addWidget(self.settlement_defaults_table, stretch=1)
        save_defaults_button = QPushButton("💾")
        save_defaults_button.setObjectName("iconButton")
        save_defaults_button.setFixedWidth(44)
        save_defaults_button.setToolTip("ذخیره")
        save_defaults_button.clicked.connect(self._save_settlement_method_defaults)
        defaults_layout.addWidget(save_defaults_button)
        self.settings_tabs.addTab(defaults_tab, "پیش‌فرضِ تسویه")

        left.addWidget(self.settings_tabs)

        # طبقِ رفعِ باگِ واقعیِ گزارش‌شده («فرم سمتِ راستش خالیه و سمتِ چپ
        # بسیار فشرده است»): این ستون (ترمینال‌ها + سه تبِ تنظیماتِ
        # پرمحتوا) چگالیِ محتوایِ بیشتری از ستونِ کناریِ شیفت/صندوق دارد --
        # قبلاً stretchِ کمتری می‌گرفت (۲ در برابرِ ۳) که باعث می‌شد
        # فیلدهایِ این ستون در عرضِ کم فشرده شوند و ستونِ شیفت با وجودِ
        # محتوایِ اسپارس‌تر، فضایِ خالیِ بیشتری بگیرد.
        outer.addLayout(left, stretch=3)

        right = QVBoxLayout()
        self.session_title = QLabel("یک ترمینال از فهرست انتخاب کنید")
        self.session_title.setObjectName("pageTitle")
        right.addWidget(self.session_title)

        self.session_status_label = QLabel("")
        right.addWidget(self.session_status_label)

        open_box = QHBoxLayout()
        open_box.addWidget(QLabel("وجهِ نقدِ ابتدایِ کار"))
        self.opening_cash_field = QDoubleSpinBox()
        self.opening_cash_field.setDecimals(2)
        self.opening_cash_field.setRange(0, 999999999)
        open_box.addWidget(self.opening_cash_field)
        self.open_session_button = QPushButton("📂")
        self.open_session_button.setObjectName("primaryIconButton")
        self.open_session_button.setFixedWidth(48)
        self.open_session_button.setToolTip("بازکردنِ شیفت")
        self.open_session_button.clicked.connect(self._open_session)
        open_box.addWidget(self.open_session_button)
        right.addLayout(open_box)

        close_box = QHBoxLayout()
        close_box.addWidget(QLabel("وجهِ نقدِ شمارش‌شده"))
        self.closing_cash_field = QDoubleSpinBox()
        self.closing_cash_field.setDecimals(2)
        self.closing_cash_field.setRange(0, 999999999)
        close_box.addWidget(self.closing_cash_field)
        self.close_session_button = QPushButton("🔒")
        self.close_session_button.setObjectName("dangerIconButton")
        self.close_session_button.setFixedWidth(44)
        self.close_session_button.setToolTip("بستنِ شیفت")
        self.close_session_button.clicked.connect(self._close_session)
        close_box.addWidget(self.close_session_button)
        right.addLayout(close_box)

        override_box = QHBoxLayout()
        self.override_reason_field = QLineEdit()
        self.override_reason_field.setPlaceholderText("دلیلِ آزادسازیِ مغایرت")
        override_box.addWidget(self.override_reason_field)
        self.override_button = QPushButton("➕")
        self.override_button.setObjectName("iconButton")
        self.override_button.setFixedWidth(44)
        self.override_button.setToolTip("آزادسازیِ مغایرت")
        self.override_button.clicked.connect(self._override_variance)
        override_box.addWidget(self.override_button)
        right.addLayout(override_box)

        history_title = QLabel("تاریخچهٔ شیفت‌ها")
        history_title.setObjectName("sectionTitle")
        right.addWidget(history_title)
        self.sessions_table = QTableWidget(0, 6)
        self.sessions_table.setHorizontalHeaderLabels(["شناسه", "وضعیت", "نقدِ ابتدا", "نقدِ پایان", "مغایرت", "آزادسازی‌شده"])
        self.sessions_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sessions_table.verticalHeader().setVisible(False)
        right.addWidget(self.sessions_table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        right.addWidget(self.status_label)
        outer.addLayout(right, stretch=2)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(wrap_scrollable(page))

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._terminals = pos_service.list_terminals(company_id)
        self.terminals_table.setRowCount(len(self._terminals))
        for row_index, t in enumerate(self._terminals):
            for col_index, value in enumerate([t.code, t.name]):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, t.terminal_id)
                self.terminals_table.setItem(row_index, col_index, cell)

        warehouses = locations_service.list_warehouses(company_id, active_only=True)
        self.terminal_warehouse_combo.clear()
        for w in warehouses:
            self.terminal_warehouse_combo.addItem(f"{w.code} — {w.name}", w.warehouse_id)

        current_guest = self.guest_customer_combo.currentData()
        self.guest_customer_combo.clear()
        self.guest_customer_combo.addItem("(تعیین‌نشده)", None)
        for c in dimensions_service.list_customers(company_id):
            self.guest_customer_combo.addItem(f"{c['code']} — {c['name'] or ''}", c["detail_account_id"])
        settings = pos_service.get_pos_settings(company_id)
        if settings is not None:
            index = self.guest_customer_combo.findData(settings.default_guest_customer_detail_account_id)
            self.guest_customer_combo.setCurrentIndex(index if index >= 0 else 0)
            self.threshold_field.setValue(float(settings.cash_variance_threshold_amount))
            self.quick_button_width_field.setValue(settings.quick_button_width)
            self.quick_button_height_field.setValue(settings.quick_button_height)
            self.quick_button_font_size_field.setValue(settings.quick_button_font_size)
            self.quick_grid_columns_field.setValue(settings.quick_grid_columns)
            self.allow_price_override_checkbox.setChecked(settings.allow_price_override)
            self.allow_discount_override_checkbox.setChecked(settings.allow_discount_override)
            self.quick_access_enabled_checkbox.setChecked(settings.quick_access_enabled)
            self.scan_beep_enabled_checkbox.setChecked(settings.scan_beep_enabled)
            self.receipt_header_field.setText(settings.receipt_header_text or "")
            self.receipt_footer_field.setText(settings.receipt_footer_text or "")
            index = self.quick_access_position_combo.findData(settings.quick_access_position)
            self.quick_access_position_combo.setCurrentIndex(index if index >= 0 else 0)
            index = self.quick_access_orientation_combo.findData(settings.quick_access_orientation)
            self.quick_access_orientation_combo.setCurrentIndex(index if index >= 0 else 0)
            self.show_price_list_field_checkbox.setChecked(settings.show_price_list_field)
            self.show_tax_discount_breakdown_checkbox.setChecked(settings.show_tax_discount_breakdown)
            self.show_customer_credit_warning_checkbox.setChecked(settings.show_customer_credit_warning)
            self.recent_invoices_count_field.setValue(settings.recent_invoices_count)
            self.fast_receipt_printing_checkbox.setChecked(settings.fast_receipt_printing)
        else:
            if current_guest is not None:
                index = self.guest_customer_combo.findData(current_guest)
                self.guest_customer_combo.setCurrentIndex(index if index >= 0 else 0)
            self.quick_button_width_field.setValue(110)
            self.quick_button_height_field.setValue(64)
            self.quick_button_font_size_field.setValue(10)
            self.quick_grid_columns_field.setValue(6)
            self.allow_price_override_checkbox.setChecked(True)
            self.allow_discount_override_checkbox.setChecked(True)
            self.quick_access_enabled_checkbox.setChecked(True)
            self.scan_beep_enabled_checkbox.setChecked(True)
            self.receipt_header_field.clear()
            self.receipt_footer_field.clear()
            self.quick_access_position_combo.setCurrentIndex(0)
            self.quick_access_orientation_combo.setCurrentIndex(0)
            self.show_price_list_field_checkbox.setChecked(True)
            self.show_tax_discount_breakdown_checkbox.setChecked(True)
            self.show_customer_credit_warning_checkbox.setChecked(True)
            self.recent_invoices_count_field.setValue(10)
            self.fast_receipt_printing_checkbox.setChecked(True)

        cashier_settings = (
            pos_service.get_cashier_settings(app_session.current_user.user_id, company_id)
            if app_session.current_user else None
        )
        self.my_quick_button_width_field.setValue(
            cashier_settings.quick_button_width_override or 0 if cashier_settings else 0
        )
        self.my_quick_button_height_field.setValue(
            cashier_settings.quick_button_height_override or 0 if cashier_settings else 0
        )

        self.menu_groups_panel.refresh()
        self._load_settlement_defaults(company_id)
        self._refresh_session_panel()

    def _save_my_quick_button_size(self) -> None:
        company_id = self._company_id()
        if company_id is None or not app_session.current_user:
            return
        user_id = app_session.current_user.user_id
        existing = pos_service.get_cashier_settings(user_id, company_id)
        order_text = existing.quick_button_order if existing else None
        width_override = self.my_quick_button_width_field.value() or None
        height_override = self.my_quick_button_height_field.value() or None
        pos_service.set_quick_button_layout(user_id, company_id, order_text, width_override, height_override)
        self.status_label.setText("")

    def _load_settlement_defaults(self, company_id: int) -> None:
        method_codes = settlements_service.settlement_plan_method_codes("SALES_INVOICE", company_id)
        defaults = settlements_service.list_pos_settlement_method_defaults(company_id)
        _cc_required, cc_options = documents_service.get_header_dimension_requirement(
            company_id, "SALES_INVOICE", dimensions_service.COST_CENTER_CODE
        )
        _proj_required, proj_options = documents_service.get_header_dimension_requirement(
            company_id, "SALES_INVOICE", dimensions_service.PROJECT_CODE
        )
        self.settlement_defaults_table.setRowCount(len(method_codes))
        self._settlement_default_widgets = []
        for row_index, method_code in enumerate(method_codes):
            default = defaults.get(method_code)

            method_label = QLabel(settlements_service.SETTLEMENT_PLAN_METHOD_LABELS.get(method_code, method_code))
            method_label.setAlignment(Qt.AlignCenter)
            self.settlement_defaults_table.setCellWidget(row_index, 0, method_label)

            account_id, detail_options = settlements_service.resolve_method_detail_options(
                company_id, "RECEIPT", method_code
            )
            detail_combo = QComboBox()
            detail_combo.addItem("(بدونِ پیش‌فرض)", None)
            for option in detail_options:
                detail_combo.addItem(f"{option.code} — {option.name or ''}", option.detail_account_id)
            if default is not None and default.detail_account_id is not None:
                index = detail_combo.findData(default.detail_account_id)
                if index >= 0:
                    detail_combo.setCurrentIndex(index)
            detail_combo.setEnabled(account_id is not None and bool(detail_options))
            self.settlement_defaults_table.setCellWidget(row_index, 1, detail_combo)

            requires_cost_center, requires_project = settlements_service.method_requires_cost_center_or_project(
                company_id, "RECEIPT", method_code
            )

            cc_combo = QComboBox()
            cc_combo.addItem("(بدونِ مرکزِ هزینه)", None)
            for option in cc_options:
                cc_combo.addItem(f"{option.code} — {option.name or ''}", option.detail_account_id)
            if default is not None and default.cost_center_detail_account_id is not None:
                index = cc_combo.findData(default.cost_center_detail_account_id)
                if index >= 0:
                    cc_combo.setCurrentIndex(index)
            cc_combo.setEnabled(requires_cost_center)
            self.settlement_defaults_table.setCellWidget(row_index, 2, cc_combo)

            proj_combo = QComboBox()
            proj_combo.addItem("(بدونِ پروژه)", None)
            for option in proj_options:
                proj_combo.addItem(f"{option.code} — {option.name or ''}", option.detail_account_id)
            if default is not None and default.project_detail_account_id is not None:
                index = proj_combo.findData(default.project_detail_account_id)
                if index >= 0:
                    proj_combo.setCurrentIndex(index)
            proj_combo.setEnabled(requires_project)
            self.settlement_defaults_table.setCellWidget(row_index, 3, proj_combo)

            self._settlement_default_widgets.append((method_code, detail_combo, cc_combo, proj_combo))

    def _save_settlement_method_defaults(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        for method_code, detail_combo, cc_combo, proj_combo in self._settlement_default_widgets:
            settlements_service.set_pos_settlement_method_default(
                company_id, method_code,
                detail_combo.currentData(), cc_combo.currentData(), proj_combo.currentData(),
            )
        self.status_label.setText("")

    def _save_settings(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        pos_service.set_pos_settings(
            company_id,
            self.guest_customer_combo.currentData(),
            decimal.Decimal(str(self.threshold_field.value())),
            quick_button_width=self.quick_button_width_field.value(),
            quick_button_height=self.quick_button_height_field.value(),
            quick_button_font_size=self.quick_button_font_size_field.value(),
            quick_grid_columns=self.quick_grid_columns_field.value(),
            allow_price_override=self.allow_price_override_checkbox.isChecked(),
            allow_discount_override=self.allow_discount_override_checkbox.isChecked(),
            quick_access_enabled=self.quick_access_enabled_checkbox.isChecked(),
            scan_beep_enabled=self.scan_beep_enabled_checkbox.isChecked(),
            receipt_header_text=self.receipt_header_field.text().strip() or None,
            receipt_footer_text=self.receipt_footer_field.text().strip() or None,
            quick_access_position=self.quick_access_position_combo.currentData(),
            quick_access_orientation=self.quick_access_orientation_combo.currentData(),
            show_price_list_field=self.show_price_list_field_checkbox.isChecked(),
            show_tax_discount_breakdown=self.show_tax_discount_breakdown_checkbox.isChecked(),
            show_customer_credit_warning=self.show_customer_credit_warning_checkbox.isChecked(),
            recent_invoices_count=self.recent_invoices_count_field.value(),
            fast_receipt_printing=self.fast_receipt_printing_checkbox.isChecked(),
        )
        self.status_label.setText("")

    def _add_terminal(self) -> None:
        company_id = self._company_id()
        code = self.terminal_code_field.text().strip()
        name = self.terminal_name_field.text().strip()
        warehouse_id = self.terminal_warehouse_combo.currentData()
        if company_id is None or not code or not name or warehouse_id is None:
            self.status_label.setText("کد، نام و انبار را وارد کنید.")
            return
        pos_service.create_terminal(company_id, warehouse_id, code, name)
        self.terminal_code_field.clear()
        self.terminal_name_field.clear()
        self.status_label.setText("")
        self.refresh()

    def _on_terminal_selected(self, row: int, _column: int) -> None:
        self._selected_terminal_id = self.terminals_table.item(row, 0).data(Qt.UserRole)
        self._refresh_session_panel()

    def _refresh_session_panel(self) -> None:
        if self._selected_terminal_id is None:
            self.session_title.setText("یک ترمینال از فهرست انتخاب کنید")
            self.session_status_label.setText("")
            self.sessions_table.setRowCount(0)
            for widget in (self.open_session_button, self.close_session_button, self.override_button):
                widget.setEnabled(False)
            return
        terminal = next((t for t in self._terminals if t.terminal_id == self._selected_terminal_id), None)
        self.session_title.setText(f"شیفت‌هایِ ترمینالِ «{terminal.name}»" if terminal else "")
        open_session = pos_service.get_open_session(self._selected_terminal_id)
        sessions = pos_service.list_sessions(self._selected_terminal_id)

        last_closed = next((s for s in sessions if s.status_code == "CLOSED"), None)
        has_unresolved_variance = (
            last_closed is not None and last_closed.variance_amount is not None
            and last_closed.variance_override_by_user_id is None
            and abs(last_closed.variance_amount) > decimal.Decimal(str(self.threshold_field.value()))
        )

        if open_session is not None:
            self.session_status_label.setText(f"شیفتِ باز — شناسه: {numerals.to_persian_digits(str(open_session.session_id))}")
        elif has_unresolved_variance:
            self.session_status_label.setText("شیفتِ قبلی مغایرتِ آزادنشده دارد — ابتدا آزادسازی کنید.")
        else:
            self.session_status_label.setText("شیفتِ بازی وجود ندارد.")

        self.open_session_button.setEnabled(open_session is None and not has_unresolved_variance)
        self.close_session_button.setEnabled(open_session is not None)
        self.override_button.setEnabled(has_unresolved_variance)
        self._open_session_id = open_session.session_id if open_session is not None else None
        self._last_closed_session_id = last_closed.session_id if last_closed is not None else None

        self.sessions_table.setRowCount(len(sessions))
        for row_index, s in enumerate(sessions):
            values = [
                numerals.to_persian_digits(str(s.session_id)),
                _SESSION_STATUS_LABELS.get(s.status_code, s.status_code),
                numerals.format_company_amount(s.opening_cash_amount),
                numerals.format_company_amount(s.closing_cash_amount) if s.closing_cash_amount is not None else "—",
                numerals.format_company_amount(s.variance_amount) if s.variance_amount is not None else "—",
                "بله" if s.variance_override_by_user_id is not None else ("—" if s.variance_amount is None else "خیر"),
            ]
            for col_index, value in enumerate(values):
                self.sessions_table.setItem(row_index, col_index, QTableWidgetItem(value))

    def _open_session(self) -> None:
        if self._selected_terminal_id is None:
            return
        try:
            pos_service.open_session(self._selected_terminal_id, app_session.current_user.user_id, decimal.Decimal(str(self.opening_cash_field.value())))
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("")
        self.refresh()

    def _close_session(self) -> None:
        if getattr(self, "_open_session_id", None) is None:
            return
        confirm = QMessageBox.question(self, "بستنِ شیفت", "این شیفت بسته شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        session_id = self._open_session_id
        try:
            pos_service.close_session(session_id, app_session.current_user.user_id, decimal.Decimal(str(self.closing_cash_field.value())))
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("")
        # طبقِ درخواستِ صریح («در هنگامِ بستنِ فاکتورهایِ اصلاح‌شده و
        # حذف‌شده به سرپرست را گزارش بده»).
        audit_entries = pos_service.list_session_audit_log(session_id)
        if audit_entries:
            action_labels = {"REOPENED": "بازگشایی/اصلاح‌شده", "DELETED": "حذف‌شده"}
            lines = [
                f"سند #{e.document_id} — {action_labels.get(e.action_code, e.action_code)} — "
                f"{numerals.to_persian_digits(e.performed_at.strftime('%Y-%m-%d %H:%M'))}"
                for e in audit_entries
            ]
            QMessageBox.information(
                self, "گزارشِ اصلاح/حذفِ فاکتورهایِ این شیفت",
                "فاکتورهایِ زیر توسطِ صندوق‌دار، پیش از تاییدِ سرپرست، اصلاح یا حذف شده‌اند:\n\n" + "\n".join(lines),
            )
        self.refresh()

    def _override_variance(self) -> None:
        if getattr(self, "_last_closed_session_id", None) is None:
            return
        reason = self.override_reason_field.text().strip()
        if not reason:
            self.status_label.setText("دلیلِ آزادسازی را وارد کنید.")
            return
        pos_service.override_session_variance(self._last_closed_session_id, app_session.current_user.user_id, reason)
        self.override_reason_field.clear()
        self.status_label.setText("")
        self.refresh()
