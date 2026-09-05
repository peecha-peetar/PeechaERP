"""فروشِ حضوری (POS، مرحلهٔ ۷) — سبدِ خرید روی یک SALES_INVOICEِ معمولی
با channel نداشته و pos_session_id.

طبقِ بازطراحیِ صریحِ کاربر: کاریر دیگر مستقیماً پرداخت/سندِ حسابداری
ثبت نمی‌کند -- فقط فروش را تایید می‌کند (نقدی/نسیه، با/بدونِ پرینت) و
نوعِ پرداختِ موردنظرش را یادداشت می‌کند؛ ثبتِ واقعیِ پرداخت/سندِ
حسابداری با تاییدِ سرپرست، در صفحه‌یِ جداگانه‌ای انجام می‌شود."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session as app_session
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_pos as pos_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import companies as companies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.ui.screens.commercial_document import _LineDialog, _show_invoice_print
from peecha.ui.screens.journal_entry import _fill_options, _make_searchable_combo
from peecha.ui.widgets import wrap_scrollable


class CommercialPosSaleScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self._items: list[catalog_service.ItemRow] = []
        self._document_id: int | None = None
        self._lines: list = []
        self._is_confirmed = False
        self._cashier_settings: pos_service.PosCashierSettings | None = None
        self._quick_button_settings: tuple[int, int, int, int] = (110, 64, 10, 6)

        page = QWidget()
        page_row = QHBoxLayout(page)
        page_row.setContentsMargins(20, 14, 20, 14)
        page_row.setSpacing(14)

        # طبقِ درخواستِ صریح («دکمه‌ها به‌صورتِ عمودی و بدونِ متن باشه»):
        # ستونِ کلیدهایِ فوری، فقط آیکن با tooltip -- دقیقاً هم‌الگو با
        # سایرِ iconButtonهایِ برنامه. چون برنامه RTL است (main.py)،
        # ستونی که اول به QHBoxLayout اضافه می‌شود در سمتِ راست می‌نشیند
        # -- هم‌جهت با عکسِ مرجعِ کاربر.
        quick_keys_column = QVBoxLayout()
        quick_keys_column.setSpacing(6)
        page_row.addLayout(quick_keys_column)

        outer = QVBoxLayout()
        outer.setSpacing(10)
        page_row.addLayout(outer, stretch=1)

        title = QLabel("فروشِ حضوری (صندوق)")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        # طبقِ درخواستِ صریح («کاریر با حسابِ خودش تنظیمات هم داره،
        # نیازی نیست دیگه اون بالای هدر نشون بده»): این هدرِ کامل فقط
        # وقتی نشان داده می‌شود که کاربرِ جاری تنظیماتِ صندوق‌داری
        # (ترمینالِ پیش‌فرض) نداشته باشد -- وگرنه فقط یک خطِ خلاصه.
        self.header_widget = QWidget()
        header_row = QHBoxLayout(self.header_widget)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.addWidget(QLabel("ترمینال"))
        self.terminal_combo = QComboBox()
        self.terminal_combo.currentIndexChanged.connect(self._on_terminal_changed)
        header_row.addWidget(self.terminal_combo)
        header_row.addWidget(QLabel("مشتری"))
        self.customer_combo = _make_searchable_combo([])
        header_row.addWidget(self.customer_combo)
        header_row.addWidget(QLabel("فهرستِ قیمت"))
        self.price_list_combo = QComboBox()
        header_row.addWidget(self.price_list_combo)
        outer.addWidget(self.header_widget)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("sectionHint")
        outer.addWidget(self.summary_label)

        self.session_label = QLabel("")
        outer.addWidget(self.session_label)

        # طبقِ درخواستِ صریح («دکمه‌یِ نیو، فیلدِ جستجو در یک ردیف باشه»)
        scan_row = QHBoxLayout()
        new_sale_button = QPushButton("🆕")
        new_sale_button.setObjectName("iconButton")
        new_sale_button.setFixedWidth(44)
        new_sale_button.setToolTip("فروشِ تازه")
        new_sale_button.clicked.connect(self._reset_sale)
        scan_row.addWidget(new_sale_button)
        self.scan_field = QLineEdit()
        self.scan_field.setObjectName("posScanField")
        self.scan_field.setPlaceholderText("🔍 بارکد را اسکن کنید یا کد/نامِ کالا را تایپ کنید و Enter بزنید")
        self.scan_field.setStyleSheet("font-size: 15pt; padding: 8px;")
        self.scan_field.returnPressed.connect(self._scan_or_search)
        # طبقِ درخواستِ صریح («جستجو پیشنهاد نمی‌دهد و برایِ چندتایی فقط
        # پیامِ خطا می‌دهد؛ وقت‌گیر است»): حالا همان‌طور که تایپ می‌شود
        # فهرستِ کالاهایِ مطابق پیشنهاد داده می‌شود -- انتخابِ یک پیشنهاد
        # همان کالا را مستقیماً به سبد اضافه می‌کند؛ اسکنِ بارکد (Enter با
        # تطبیقِ دقیق) دست‌نخورده باقی می‌ماند.
        self._scan_completer = QCompleter([])
        self._scan_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._scan_completer.setFilterMode(Qt.MatchContains)
        self._scan_completer.activated.connect(self._on_scan_suggestion_selected)
        self.scan_field.setCompleter(self._scan_completer)
        self._scan_label_to_item_id: dict[str, int] = {}
        scan_row.addWidget(self.scan_field, stretch=1)
        outer.addLayout(scan_row)

        # طبقِ درخواستِ صریح («ردیفِ کالا/تعداد/قیمتِ دستی لازم نیست؛
        # جستجو/اسکن مستقیماً با ۱ عدد و قیمتِ لیست به جدول اضافه کند؛
        # اصلاح فقط با کلیک روی خودِ ردیف»): دیگر کمبویِ دستیِ افزودن
        # نداریم -- ویرایش با دوبار-کلیک روی ردیف انجام می‌شود.
        self.lines_table = QTableWidget(0, 4)
        self.lines_table.setHorizontalHeaderLabels(["کالا", "مقدار", "بهایِ واحد", "جمعِ ردیف"])
        self.lines_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lines_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.lines_table.verticalHeader().setVisible(False)
        self.lines_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.lines_table.cellDoubleClicked.connect(self._edit_line)
        outer.addWidget(self.lines_table)

        self.total_label = QLabel("جمعِ کل: ۰")
        self.total_label.setObjectName("sectionTitle")
        outer.addWidget(self.total_label)

        # طبقِ چرخه‌یِ بازطراحی‌شده: کاریر فقط تایید می‌کند (نقدی/نسیه،
        # با/بدونِ پرینت)؛ ثبتِ واقعیِ پرداخت/سندِ حسابداری با approve/
        # postِ سرپرست در صفحه‌یِ جداگانه انجام می‌شود. طبقِ درخواستِ
        # صریح، این کلیدهایِ فوری عمودی و بدونِ متن (فقط آیکن+tooltip) اند.
        def _quick_key(icon: str, tooltip: str, object_name: str, handler) -> QPushButton:
            button = QPushButton(icon)
            button.setObjectName(object_name)
            button.setFixedWidth(48)
            button.setToolTip(tooltip)
            button.clicked.connect(handler)
            quick_keys_column.addWidget(button)
            return button

        _quick_key("💵🖨️", "نقدی + پرینت", "primaryIconButton", lambda: self._confirm_sale("CASH", print_receipt=True))
        _quick_key("💵", "نقدی (بدونِ پرینت)", "iconButton", lambda: self._confirm_sale("CASH", print_receipt=False))
        _quick_key("📒🖨️", "نسیه + پرینت", "primaryIconButton", lambda: self._confirm_sale("CREDIT", print_receipt=True))
        _quick_key("📒", "نسیه (بدونِ پرینت)", "iconButton", lambda: self._confirm_sale("CREDIT", print_receipt=False))
        _quick_key(
            "📌", "رزرو -- این فروش را نگه دار و سراغِ مشتریِ بعدی برو؛ بعداً از «نمایشِ رزروها» بازش کن.",
            "iconButton", self._suspend_sale,
        )
        _quick_key("👁️", "نمایشِ رزروها", "iconButton", self._show_suspended_dialog)
        _quick_key("🛠️", "تعریف/اصلاحِ کالا", "iconButton", self._open_item_form)
        quick_keys_column.addStretch(1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        # طبقِ درخواستِ صریح («پایینِ صفحه جایِ خالیِ زیادی دارد؛ آنجا
        # شورت‌کاتِ کالاهایِ پرمصرف را در تب‌هایِ مختلف بگذار»): جایِ
        # خالیِ پایینِ صفحه به یک تب‌ویجتِ دسترسیِ‌سریع اختصاص یافت --
        # هر تب یک دسته‌یِ کالاست (از رویِ همان دسته‌بندیِ ازپیش‌موجودِ
        # کالا)، به‌علاوهٔ یک تبِ «همه» در ابتدا.
        self.quick_access_tabs = QTabWidget()
        outer.addWidget(self.quick_access_tabs, stretch=1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(wrap_scrollable(page))

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._items = catalog_service.list_items(company_id, active_only=True)
        self._rebuild_quick_access()
        self._scan_label_to_item_id = {
            f"{it.code} — {it.name or ''}": it.item_id for it in self._items
        }
        self._scan_completer.model().setStringList(list(self._scan_label_to_item_id.keys()))
        self.scan_field.setFocus()

        self._cashier_settings = (
            pos_service.get_cashier_settings(app_session.current_user.user_id, company_id)
            if app_session.current_user else None
        )

        current_terminal = self.terminal_combo.currentData()
        self.terminal_combo.blockSignals(True)
        self.terminal_combo.clear()
        for t in pos_service.list_terminals(company_id):
            self.terminal_combo.addItem(f"{t.code} — {t.name}", t.terminal_id)
        preferred_terminal = self._cashier_settings.default_terminal_id if self._cashier_settings else None
        target_terminal = preferred_terminal if preferred_terminal is not None else current_terminal
        if target_terminal is not None:
            index = self.terminal_combo.findData(target_terminal)
            if index >= 0:
                self.terminal_combo.setCurrentIndex(index)
        self.terminal_combo.blockSignals(False)

        pos_settings = pos_service.get_pos_settings(company_id)
        current_customer = self.customer_combo.currentData()
        customer_options = [(c["detail_account_id"], f"{c['code']} — {c['name'] or ''}") for c in dimensions_service.list_customers(company_id)]
        _fill_options(self.customer_combo, customer_options)
        preferred_customer = current_customer
        if self._cashier_settings is not None and self._cashier_settings.default_customer_detail_account_id is not None:
            preferred_customer = self._cashier_settings.default_customer_detail_account_id
        elif pos_settings is not None and pos_settings.default_guest_customer_detail_account_id is not None:
            preferred_customer = pos_settings.default_guest_customer_detail_account_id
        if preferred_customer is not None:
            index = self.customer_combo.findData(preferred_customer)
            if index >= 0:
                self.customer_combo.setCurrentIndex(index)

        current_price_list = self.price_list_combo.currentData()
        self.price_list_combo.clear()
        self.price_list_combo.addItem("(بدونِ فهرستِ قیمت)", None)
        for pl in pricing_service.list_price_lists(company_id, "SALES"):
            self.price_list_combo.addItem(f"{pl.code} — {pl.name}", pl.price_list_id)
        preferred_price_list = self._cashier_settings.default_price_list_id if self._cashier_settings is not None and self._cashier_settings.default_price_list_id is not None else current_price_list
        if preferred_price_list is not None:
            index = self.price_list_combo.findData(preferred_price_list)
            if index >= 0:
                self.price_list_combo.setCurrentIndex(index)

        self._apply_header_visibility()
        self._update_session_label()

    def _apply_header_visibility(self) -> None:
        has_defaults = self._cashier_settings is not None and self._cashier_settings.default_terminal_id is not None
        self.header_widget.setVisible(not has_defaults)
        self.summary_label.setVisible(has_defaults)
        if has_defaults:
            self.summary_label.setText(
                f"ترمینال: {self.terminal_combo.currentText()} | "
                f"مشتری: {self.customer_combo.currentText()} | "
                f"فهرستِ قیمت: {self.price_list_combo.currentText()}"
            )

    def _current_open_session_id(self) -> int | None:
        terminal_id = self.terminal_combo.currentData()
        if terminal_id is None:
            return None
        session = pos_service.get_open_session(terminal_id)
        return session.session_id if session is not None else None

    def _on_terminal_changed(self) -> None:
        self._update_session_label()

    def _update_session_label(self) -> None:
        session_id = self._current_open_session_id()
        if session_id is None:
            self.session_label.setText("این ترمینال شیفتِ بازی ندارد — ابتدا از صفحهٔ «ترمینال‌ها و شیفت‌هایِ صندوق» یک شیفت باز کنید.")
            self.session_label.setObjectName("statusError")
        else:
            self.session_label.setText(f"شیفتِ باز — شناسه: {numerals.to_persian_digits(str(session_id))}")
            self.session_label.setObjectName("")
        self.session_label.style().unpolish(self.session_label)
        self.session_label.style().polish(self.session_label)

    def _build_quick_grid(self, items: list[catalog_service.ItemRow]) -> QWidget:
        settings = self._quick_button_settings
        width, height, font_size, columns = settings
        page = QWidget()
        grid = QGridLayout(page)
        grid.setSpacing(6)
        for index, item in enumerate(items):
            button = QPushButton(item.short_name or item.name or item.code)
            button.setFixedSize(width, height)
            button.setStyleSheet(
                f"background-color: {item.pos_button_color}; color: #ffffff; font-weight: 600; "
                f"font-size: {font_size}pt; padding: 4px; border-radius: 6px;"
            )
            tooltip = f"{item.code} — {item.name or ''}"
            if item.pos_shortcut_key:
                tooltip += f" ({item.pos_shortcut_key})"
            button.setToolTip(tooltip)
            button.clicked.connect(lambda _checked=False, it=item: self._add_item_to_cart(it, decimal.Decimal("1")))
            grid.addWidget(button, index // columns, index % columns)
        grid.setRowStretch((len(items) - 1) // columns + 1 if items else 0, 1)
        return page

    def _rebuild_quick_access(self) -> None:
        current_tab_text = self.quick_access_tabs.tabText(self.quick_access_tabs.currentIndex())
        self.quick_access_tabs.clear()
        company_id = self._company_id()
        pos_settings = pos_service.get_pos_settings(company_id) if company_id else None
        self._quick_button_settings = (
            pos_settings.quick_button_width if pos_settings else 110,
            pos_settings.quick_button_height if pos_settings else 64,
            pos_settings.quick_button_font_size if pos_settings else 10,
            pos_settings.quick_grid_columns if pos_settings else 6,
        )

        quick_items = [it for it in self._items if it.pos_button_color]
        if not quick_items:
            return

        self.quick_access_tabs.addTab(self._build_quick_grid(quick_items), "همه")

        groups: dict[int | None, list] = {}
        for item in quick_items:
            groups.setdefault(item.pos_menu_group_id, []).append(item)
        menu_groups = pos_service.list_menu_groups(company_id, active_only=True) if company_id else []
        for menu_group in sorted(menu_groups, key=lambda g: g.display_order):
            items_in_group = groups.pop(menu_group.group_id, None)
            if items_in_group:
                self.quick_access_tabs.addTab(self._build_quick_grid(items_in_group), menu_group.name)
        ungrouped = groups.pop(None, [])
        for leftover_items in groups.values():
            ungrouped.extend(leftover_items)
        if ungrouped:
            self.quick_access_tabs.addTab(self._build_quick_grid(ungrouped), "سایر")

        for tab_index in range(self.quick_access_tabs.count()):
            if self.quick_access_tabs.tabText(tab_index) == current_tab_text:
                self.quick_access_tabs.setCurrentIndex(tab_index)
                break

    def _resolve_scanned_item(self, query: str) -> catalog_service.ItemRow | None:
        needle = query.strip().lower()
        if not needle:
            return None
        barcode_matches = [it for it in self._items if it.barcode and it.barcode.strip().lower() == needle]
        if len(barcode_matches) == 1:
            return barcode_matches[0]
        code_matches = [it for it in self._items if it.code.strip().lower() == needle]
        if len(code_matches) == 1:
            return code_matches[0]
        name_matches = [it for it in self._items if it.name and needle in it.name.lower()]
        if len(name_matches) == 1:
            return name_matches[0]
        if not (name_matches or barcode_matches or code_matches):
            self.status_label.setText(f"کالایی با «{query}» یافت نشد.")
        return None

    def _scan_or_search(self) -> None:
        query = self.scan_field.text().strip()
        item = self._resolve_scanned_item(query)
        if item is None:
            # طبقِ درخواستِ صریح: به‌جایِ فقط پیامِ خطا برایِ چندتایی،
            # کادر را خالی نمی‌کنیم -- کاربر پیشنهادهایِ زنده‌یِ همین‌الان
            # (کامل‌کنندهٔ متصل به کادر) را می‌بیند و می‌تواند از همان‌جا
            # انتخاب کند، به‌جایِ تایپِ دوباره.
            return
        self.scan_field.clear()
        self._add_item_to_cart(item, decimal.Decimal("1"))
        self.scan_field.setFocus()

    def _on_scan_suggestion_selected(self, label: str) -> None:
        item_id = self._scan_label_to_item_id.get(label)
        item = next((it for it in self._items if it.item_id == item_id), None)
        self.scan_field.clear()
        if item is None:
            return
        self._add_item_to_cart(item, decimal.Decimal("1"))
        self.scan_field.setFocus()

    def _clear_cart_view(self) -> None:
        self._document_id = None
        self._lines = []
        self._is_confirmed = False
        self._refresh_lines_table()
        self.total_label.setText("جمعِ کل: ۰")

    def _reset_sale(self) -> None:
        self._clear_cart_view()
        self.status_label.setText("")
        self.refresh()

    def _suspend_sale(self) -> None:
        if self._document_id is None or not self._lines:
            self.status_label.setText("سبدِ خالی رزرو نمی‌شود.")
            return
        self._clear_cart_view()
        self.status_label.setText("این فروش رزرو شد -- از «نمایشِ رزروها» می‌توانید بازش کنید.")
        self.scan_field.setFocus()

    def _show_suspended_dialog(self) -> None:
        company_id = self._company_id()
        session_id = self._current_open_session_id()
        if company_id is None or session_id is None:
            self.status_label.setText("ابتدا یک شیفتِ باز انتخاب کنید.")
            return
        pending = pos_service.list_pending_pos_documents(company_id, session_id)
        if not pending:
            self.status_label.setText("در این شیفت فروشِ رزروشده‌ای وجود ندارد.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("فروش‌هایِ رزروشده/درجریانِ این شیفت")
        dialog.setMinimumWidth(380)
        layout = QVBoxLayout(dialog)
        list_widget = QListWidget()
        for doc in pending:
            label = f"سند #{doc.document_id} — {numerals.format_company_amount(doc.total_amount)}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, doc.document_id)
            list_widget.addItem(item)
        layout.addWidget(list_widget)

        def _resume() -> None:
            current = list_widget.currentItem()
            if current is None:
                return
            self._document_id = current.data(Qt.UserRole)
            self._load_document()
            dialog.accept()

        list_widget.itemDoubleClicked.connect(lambda _item: _resume())
        resume_button = QPushButton("بازکردنِ این فروش")
        resume_button.setObjectName("primaryIconButton")
        resume_button.clicked.connect(_resume)
        layout.addWidget(resume_button)
        dialog.exec()

    def _open_item_form(self) -> None:
        if self._main_window is not None:
            self._main_window.open_screen("GL_DIM")

    def _ensure_document(self) -> bool:
        if self._document_id is not None:
            return True
        company_id = self._company_id()
        session_id = self._current_open_session_id()
        customer_id = self.customer_combo.currentData()
        if company_id is None or session_id is None or customer_id is None:
            self.status_label.setText("ترمینال با شیفتِ باز و مشتری را انتخاب کنید.")
            return False
        terminal_id = self.terminal_combo.currentData()
        terminal = next((t for t in pos_service.list_terminals(company_id) if t.terminal_id == terminal_id), None)
        try:
            self._document_id = documents_service.create_document(
                company_id, app_session.current_user.user_id, "SALES_INVOICE", datetime.date.today(),
                documents_service.DocumentHeaderFields(
                    counterparty_detail_account_id=customer_id, currency_id=app_session.current_company.base_currency_id,
                    warehouse_id=terminal.warehouse_id if terminal else None,
                    price_list_id=self.price_list_combo.currentData(), pos_session_id=session_id,
                ),
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return False
        return True

    def _add_item_to_cart(
        self, item: catalog_service.ItemRow, quantity: decimal.Decimal, unit_price: decimal.Decimal | None = None,
    ) -> bool:
        if self._is_confirmed:
            self.status_label.setText("این فروش قبلاً تایید شده — برایِ فروشِ تازه، «فروشِ تازه» را بزنید.")
            return False
        if not self._ensure_document():
            return False
        company_id = self._company_id()
        # طبقِ درخواستِ صریح («اگر با بارکد/دستی کالایی جستجو شد که
        # قبلاً در ردیف‌ها بود، فقط به تعدادِ همان ردیف اضافه شود»):
        existing = next((ln for ln in self._lines if ln.item_id == item.item_id), None)
        try:
            if existing is not None:
                documents_service.delete_line(existing.line_id, self._document_id, company_id)
                documents_service.add_line(
                    self._document_id, company_id, item.item_id, item.base_uom_id,
                    existing.quantity + quantity, existing.quantity + quantity, unit_price=existing.unit_price,
                )
            else:
                documents_service.add_line(
                    self._document_id, company_id, item.item_id, item.base_uom_id, quantity, quantity, unit_price=unit_price,
                )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return False
        self.status_label.setText("")
        self._load_document()
        return True

    def _load_document(self) -> None:
        if self._document_id is None:
            return
        doc, lines = documents_service.get_document(self._document_id, self._company_id())
        self._lines = lines
        self._is_confirmed = doc.status_code != "DRAFT"
        self._refresh_lines_table()
        self.total_label.setText(f"جمعِ کل: {numerals.format_company_amount(doc.total_amount)}")

    def _refresh_lines_table(self) -> None:
        items_by_id = {it.item_id: it for it in self._items}
        self.lines_table.setRowCount(len(self._lines))
        for row_index, ln in enumerate(self._lines):
            item = items_by_id.get(ln.item_id)
            values = [
                f"{item.code} — {item.name or ''}" if item else str(ln.item_id),
                str(ln.quantity), str(ln.unit_price), str(ln.line_total),
            ]
            for col_index, value in enumerate(values):
                self.lines_table.setItem(row_index, col_index, QTableWidgetItem(value))

    def _edit_line(self, row: int, _column: int = 0) -> None:
        if row < 0 or row >= len(self._lines):
            return
        if self._is_confirmed:
            self.status_label.setText("این فروش قبلاً تایید شده — ردیف‌ها قابلِ‌ویرایش نیستند.")
            return
        line = self._lines[row]
        company_id = self._company_id()
        decimal_places = companies_service.get_base_currency_decimal_places(company_id)
        initial = {
            "item_id": line.item_id, "quantity": line.quantity, "unit_price": line.unit_price,
            "discount_amount": line.discount_amount, "discount_percent": line.discount_percent,
            "tax_percent": line.tax_percent, "description": line.description, "warehouse_id": line.warehouse_id,
        }
        dialog = _LineDialog(
            self, self._items, company_id, self._main_window, decimal_places, initial,
            counterparty_id=self.customer_combo.currentData(), price_list_id=self.price_list_combo.currentData(),
            document_type_code="SALES_INVOICE", document_date=datetime.date.today(),
        )
        if dialog.exec() != QDialog.Accepted:
            return
        fields = dialog.result_fields()
        try:
            documents_service.delete_line(line.line_id, self._document_id, company_id)
            documents_service.add_line(self._document_id, company_id, **fields)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("")
        self._load_document()

    def _confirm_sale(self, payment_type: str, print_receipt: bool) -> None:
        if self._document_id is None or not self._lines:
            self.status_label.setText("ابتدا حداقل یک کالا به سبد اضافه کنید.")
            return
        if self._is_confirmed:
            self.status_label.setText("این فروش قبلاً تایید شده است.")
            return
        company_id = self._company_id()
        try:
            documents_service.confirm_document(self._document_id, company_id, app_session.current_user.user_id)
            pos_service.set_intended_payment_type(self._document_id, company_id, payment_type)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        document_id = self._document_id
        if print_receipt:
            _show_invoice_print(self, company_id, document_id)
        self.status_label.setText("فروش تایید شد و برایِ تاییدِ سرپرست به‌صفِ انتظار رفت.")
        self._clear_cart_view()
        self.refresh()
