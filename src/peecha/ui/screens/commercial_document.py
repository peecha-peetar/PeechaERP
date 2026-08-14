"""فرمِ اسنادِ بازرگانی — سفارش/فاکتور/برگشت (خرید و فروش)، همه رویِ
همان اسکلتِ سرِسند+ردیفِ واحدِ comm.commercial_documents/commercial_document_lines
(services/commercial_documents.py).

طبقِ اسکوپِ آگاهانهٔ این دور: تبدیلِ واحد (هر ردیف با واحدِ پایهٔ کالا)،
بچ/سریال، نمایندهٔ فروش/کمیسیون، و بُعدِ مرکزِ هزینه/پروژه رویِ سرِسند،
به دورهایِ بعدی موکول شده‌اند."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session as app_session
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.ui.screens.journal_entry import _fill_options, _make_searchable_combo
from peecha.ui.widgets import (
    FieldGrid,
    FieldHelpMixin,
    FieldSpec,
    FormScreenBase,
    JalaliDateEdit,
    LayoutEditMixin,
    SectionStepper,
    SummaryCard,
    SummaryCardBar,
)

DOC_TYPE_TITLES = {
    "SALES_ORDER": "سفارشِ فروش",
    "SALES_INVOICE": "فاکتورِ فروش",
    "SALES_RETURN": "برگشت از فروش",
    "PURCHASE_ORDER": "سفارشِ خرید",
    "PURCHASE_INVOICE": "فاکتورِ خرید",
    "PURCHASE_RETURN": "برگشت به تامین‌کننده",
}
STATUS_LABELS = {"DRAFT": "پیش‌نویس", "CONFIRMED": "تاییدشده", "APPROVED": "تصویب‌شده", "POSTED": "ثبتِ‌نهایی‌شده", "CANCELLED": "لغوشده"}
_SALES_TYPES = ("SALES_ORDER", "SALES_INVOICE", "SALES_RETURN")
_LINE_COLUMNS = ["کالا", "مقدار", "بهایِ واحد", "تخفیف", "درصدِ مالیات", "مالیات", "جمعِ ردیف", "توضیح"]


class _LineDialog(LayoutEditMixin, QDialog):
    def __init__(self, parent: QWidget, items: list[catalog_service.ItemRow], initial: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ردیفِ سند")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        self._items_by_id = {it.item_id: it for it in items}

        item_options = [(it.item_id, f"{it.code} — {it.name or ''}") for it in items]
        self.item_combo = _make_searchable_combo(item_options)

        self.quantity_field = QDoubleSpinBox()
        self.quantity_field.setDecimals(6)
        self.quantity_field.setRange(0.000001, 999999999)

        self.unit_price_field = QDoubleSpinBox()
        self.unit_price_field.setDecimals(2)
        self.unit_price_field.setRange(0, 999999999999)
        self.unit_price_field.setSpecialValueText(" ")

        self.discount_field = QDoubleSpinBox()
        self.discount_field.setDecimals(2)
        self.discount_field.setRange(0, 999999999999)

        self.tax_percent_field = QDoubleSpinBox()
        self.tax_percent_field.setDecimals(2)
        self.tax_percent_field.setRange(0, 100)

        self.description_field = QLineEdit()

        self.fields_grid = FieldGrid([
            FieldSpec("item", "کالا", self.item_combo, span=2),
            FieldSpec("quantity", "مقدار (واحدِ پایهٔ کالا)", self.quantity_field, span=1),
            FieldSpec("unit_price", "بهایِ واحد (خالی = محاسبهٔ خودکار)", self.unit_price_field, span=1),
            FieldSpec("discount", "تخفیفِ مبلغی", self.discount_field, span=1),
            FieldSpec("tax_percent", "درصدِ مالیات", self.tax_percent_field, span=1),
            FieldSpec("description", "توضیح", self.description_field, span=3),
        ])
        layout.addWidget(self.fields_grid)
        self.register_field_grids("commercial_document_line", [self.fields_grid])

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if initial is not None:
            index = self.item_combo.findData(initial["item_id"])
            if index >= 0:
                self.item_combo.setCurrentIndex(index)
            self.quantity_field.setValue(float(initial["quantity"]))
            self.unit_price_field.setValue(float(initial["unit_price"]))
            self.discount_field.setValue(float(initial["discount_amount"]))
            self.tax_percent_field.setValue(float(initial["tax_percent"]))
            self.description_field.setText(initial["description"] or "")

    def _on_accept(self) -> None:
        if self.item_combo.currentData() is None:
            self.status_label.setText("کالا را انتخاب کنید.")
            return
        if self.quantity_field.value() <= 0:
            self.status_label.setText("مقدار باید بزرگ‌تر از صفر باشد.")
            return
        self.accept()

    def result_fields(self) -> dict:
        item_id = self.item_combo.currentData()
        item = self._items_by_id.get(item_id)
        return {
            "item_id": item_id,
            "uom_id": item.base_uom_id if item else 0,
            "quantity": decimal.Decimal(str(self.quantity_field.value())),
            "unit_price": decimal.Decimal(str(self.unit_price_field.value())) if self.unit_price_field.value() > 0 else None,
            "discount_amount": decimal.Decimal(str(self.discount_field.value())),
            "tax_percent": decimal.Decimal(str(self.tax_percent_field.value())),
            "description": self.description_field.text().strip() or None,
        }


class CommercialDocumentScreen(FieldHelpMixin, FormScreenBase):
    def __init__(self, document_type_code: str, main_window) -> None:
        super().__init__()
        self.document_type_code = document_type_code
        self._is_sales = document_type_code in _SALES_TYPES
        self._main_window = main_window
        self._document_id: int | None = None
        self._status_code = "DRAFT"
        self._lines: list = []
        self._items: list[catalog_service.ItemRow] = []

        title = DOC_TYPE_TITLES[document_type_code]
        self.page_title = QLabel(title)
        self.page_title.setObjectName("pageTitle")
        self.body_layout.addWidget(self.page_title)

        # طبقِ نمونه‌طراحیِ استپردار/کارت‌رنگیِ ارسالیِ کاربر — هم‌الگو با
        # treasury_voucher.py/journal_entry.py: صرفاً لایه‌یِ بصری/ناوبری،
        # هیچ ویجتِ موجودی جابه‌جا نمی‌شود. چون این فرم (بر خلافِ آن دو)
        # هدرش را در یک کارتِ جداگانه نمی‌پیچد، از خودِ page_title/
        # lines_table به‌عنوانِ لنگرِ شروعِ هر بخش استفاده می‌شود.
        self.step_stepper = SectionStepper(["اطلاعاتِ سند", "ردیف‌ها"])
        self.body_layout.addWidget(self.step_stepper)

        self.summary_cards = SummaryCardBar({
            "subtotal": SummaryCard("جمعِ ناخالص", role="neutral"),
            "discount_tax": SummaryCard("تخفیف/مالیات", role="warning"),
            "grand_total": SummaryCard("جمعِ کل", role="success"),
        })
        self.body_layout.addWidget(self.summary_cards)

        header_row1 = QHBoxLayout()
        date_box = QVBoxLayout()
        date_box.addWidget(QLabel("تاریخ"))
        self.date_field = JalaliDateEdit()
        date_box.addWidget(self.date_field)
        header_row1.addLayout(date_box)

        counterparty_box = QVBoxLayout()
        counterparty_box.addWidget(QLabel("مشتری" if self._is_sales else "تامین‌کننده"))
        self.counterparty_combo = _make_searchable_combo([])
        counterparty_box.addWidget(self.counterparty_combo)
        header_row1.addLayout(counterparty_box)

        warehouse_box = QVBoxLayout()
        warehouse_box.addWidget(QLabel("انبار"))
        self.warehouse_combo = QComboBox()
        warehouse_box.addWidget(self.warehouse_combo)
        header_row1.addLayout(warehouse_box)
        self.body_layout.addLayout(header_row1)

        header_row2 = QHBoxLayout()
        price_list_box = QVBoxLayout()
        price_list_box.addWidget(QLabel("فهرستِ قیمت"))
        self.price_list_combo = QComboBox()
        price_list_box.addWidget(self.price_list_combo)
        header_row2.addLayout(price_list_box)

        self.channel_box = QWidget()
        channel_layout = QVBoxLayout(self.channel_box)
        channel_layout.setContentsMargins(0, 0, 0, 0)
        channel_layout.addWidget(QLabel("کانال"))
        self.channel_combo = QComboBox()
        channel_layout.addWidget(self.channel_combo)
        header_row2.addWidget(self.channel_box)
        self.channel_box.setVisible(self._is_sales)

        reference_box = QVBoxLayout()
        reference_box.addWidget(QLabel("شمارهٔ مرجع"))
        self.reference_field = QLineEdit()
        reference_box.addWidget(self.reference_field)
        header_row2.addLayout(reference_box)

        description_box = QVBoxLayout()
        description_box.addWidget(QLabel("توضیح"))
        self.description_field = QLineEdit()
        description_box.addWidget(self.description_field)
        header_row2.addLayout(description_box)
        self.body_layout.addLayout(header_row2)

        self.status_badge = QLabel("")
        self.status_badge.setObjectName("statusBadge")
        self.body_layout.addWidget(self.status_badge)

        self.links_label = QLabel("")
        self.body_layout.addWidget(self.links_label)

        lines_title = QLabel("ردیف‌ها")
        lines_title.setObjectName("sectionTitle")
        self.body_layout.addWidget(lines_title)

        add_line_button = QPushButton("➕")
        add_line_button.setObjectName("primaryIconButton")
        add_line_button.setFixedWidth(48)
        add_line_button.setToolTip("افزودنِ ردیف")
        add_line_button.clicked.connect(self._add_line)
        self.body_layout.addWidget(add_line_button, alignment=Qt.AlignLeft)

        self.lines_table = QTableWidget(0, len(_LINE_COLUMNS))
        self.lines_table.setHorizontalHeaderLabels(_LINE_COLUMNS)
        self.lines_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lines_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.lines_table.verticalHeader().setVisible(False)
        self.lines_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.lines_table.setMinimumHeight(220)
        self.lines_table.cellDoubleClicked.connect(self._edit_line)
        self.body_layout.addWidget(self.lines_table)

        self.step_stepper.register_sections(self._scroll, [self.page_title, self.lines_table])

        line_button_cluster = QWidget()
        line_button_cluster.setLayoutDirection(Qt.LeftToRight)
        line_buttons = QHBoxLayout(line_button_cluster)
        line_buttons.setContentsMargins(0, 0, 0, 0)
        edit_line_button = QPushButton("✏️")
        edit_line_button.setObjectName("iconButton")
        edit_line_button.setFixedWidth(44)
        edit_line_button.setToolTip("ویرایشِ ردیف")
        edit_line_button.clicked.connect(self._edit_line)
        line_buttons.addWidget(edit_line_button)
        delete_line_button = QPushButton("🗑️")
        delete_line_button.setObjectName("dangerIconButton")
        delete_line_button.setFixedWidth(44)
        delete_line_button.setToolTip("حذفِ ردیف")
        delete_line_button.clicked.connect(self._delete_line)
        line_buttons.addWidget(delete_line_button)
        self.body_layout.addWidget(line_button_cluster, alignment=Qt.AlignLeft)

        self.totals_label = QLabel("")
        self.totals_label.setObjectName("sectionTitle")
        self.body_layout.addWidget(self.totals_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        self.body_layout.addWidget(self.status_label)
        self.body_layout.addStretch(1)

        # طبقِ گزارشِ صریح («بعضی فرم‌ها روی دکمه‌هاش نوشته داره و نصف
        # نوشته‌هاست»): این فوتر ۶ دکمه‌یِ متنیِ کنارِ هم داشت — دقیقاً
        # الگویِ فشرده‌شدنی که باعثِ بریده‌شدنِ متن می‌شود. همه آیکنی
        # شدند؛ توضیح از طریقِ تول‌تیپ.
        self.new_button = QPushButton("🆕")
        self.new_button.setObjectName("iconButton")
        self.new_button.setFixedWidth(44)
        self.new_button.setToolTip("سندِ جدید")
        self.new_button.clicked.connect(self._reset_form)
        self.footer_layout.addWidget(self.new_button)

        self.save_button = QPushButton("💾")
        self.save_button.setObjectName("primaryIconButton")
        self.save_button.setFixedWidth(48)
        self.save_button.setToolTip("ذخیرهٔ پیش‌نویس")
        self.save_button.clicked.connect(self._save_header)
        self.footer_layout.addWidget(self.save_button)

        self.confirm_button = QPushButton("✅")
        self.confirm_button.setObjectName("iconButton")
        self.confirm_button.setFixedWidth(44)
        self.confirm_button.setToolTip("تاییدِ سند")
        self.confirm_button.clicked.connect(self._confirm)
        self.footer_layout.addWidget(self.confirm_button)

        self.approve_button = QPushButton("👍")
        self.approve_button.setObjectName("iconButton")
        self.approve_button.setFixedWidth(44)
        self.approve_button.setToolTip("تصویبِ سند")
        self.approve_button.clicked.connect(self._approve)
        self.footer_layout.addWidget(self.approve_button)

        self.post_button = QPushButton("🔒")
        self.post_button.setObjectName("primaryIconButton")
        self.post_button.setFixedWidth(48)
        self.post_button.setToolTip("ثبتِ نهایی")
        self.post_button.clicked.connect(self._post)
        self.footer_layout.addWidget(self.post_button)

        self.cancel_button = QPushButton("🚫")
        self.cancel_button.setObjectName("dangerIconButton")
        self.cancel_button.setFixedWidth(44)
        self.cancel_button.setToolTip("لغوِ سند")
        self.cancel_button.clicked.connect(self._cancel)
        self.footer_layout.addWidget(self.cancel_button)
        self.footer_layout.addStretch(1)

        self.set_field_help([
            (self.date_field, "تاریخِ سند — پایهٔ تعیینِ سالِ مالی."),
            (self.price_list_combo, "اگر برایِ ردیفی بهایِ واحد وارد نشود، از همین فهرستِ قیمت (یا قراردادِ فعالِ طرفِ‌حساب) محاسبه می‌شود."),
        ])

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._items = catalog_service.list_items(company_id, active_only=True)
        warehouses = locations_service.list_warehouses(company_id, active_only=True)
        current_wh = self.warehouse_combo.currentData()
        self.warehouse_combo.blockSignals(True)
        self.warehouse_combo.clear()
        self.warehouse_combo.addItem("(انتخاب کنید)", None)
        for w in warehouses:
            self.warehouse_combo.addItem(f"{w.code} — {w.name}", w.warehouse_id)
        if current_wh is not None:
            self.warehouse_combo.setCurrentIndex(max(0, self.warehouse_combo.findData(current_wh)))
        self.warehouse_combo.blockSignals(False)

        if self._is_sales:
            counterparty_options = [(c["detail_account_id"], f"{c['code']} — {c['name'] or ''}") for c in dimensions_service.list_customers(company_id)]
            price_lists = pricing_service.list_price_lists(company_id, "SALES")
            channels = pricing_service.list_channels(company_id)
            current_channel = self.channel_combo.currentData()
            self.channel_combo.clear()
            self.channel_combo.addItem("(بدونِ کانال)", None)
            for ch in channels:
                self.channel_combo.addItem(f"{ch.channel_code} — {ch.name}", ch.channel_code)
            if current_channel is not None:
                self.channel_combo.setCurrentIndex(max(0, self.channel_combo.findData(current_channel)))
        else:
            counterparty_options = [(c["detail_account_id"], f"{c['code']} — {c['name'] or ''}") for c in dimensions_service.list_suppliers(company_id)]
            price_lists = pricing_service.list_price_lists(company_id, "PURCHASE")
        current_counterparty = self.counterparty_combo.currentData()
        _fill_options(self.counterparty_combo, counterparty_options)
        if current_counterparty is not None:
            index = self.counterparty_combo.findData(current_counterparty)
            if index >= 0:
                self.counterparty_combo.setCurrentIndex(index)

        current_price_list = self.price_list_combo.currentData()
        self.price_list_combo.clear()
        self.price_list_combo.addItem("(بدونِ فهرستِ قیمت)", None)
        for pl in price_lists:
            self.price_list_combo.addItem(f"{pl.code} — {pl.name}", pl.price_list_id)
        if current_price_list is not None:
            index = self.price_list_combo.findData(current_price_list)
            if index >= 0:
                self.price_list_combo.setCurrentIndex(index)

        if self._document_id is not None:
            self._load_document()
        else:
            self._reset_form(clear_only=True)

    def _load_document(self) -> None:
        company_id = self._company_id()
        try:
            doc, lines = documents_service.get_document(self._document_id, company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._status_code = doc.status_code
        self.page_title.setText(f"{DOC_TYPE_TITLES[self.document_type_code]} #{numerals.to_persian_digits(str(doc.document_no))}")
        self.date_field.setDate(doc.document_date)
        index = self.counterparty_combo.findData(doc.counterparty_detail_account_id)
        if index >= 0:
            self.counterparty_combo.setCurrentIndex(index)
        if doc.warehouse_id is not None:
            self.warehouse_combo.setCurrentIndex(max(0, self.warehouse_combo.findData(doc.warehouse_id)))
        if doc.price_list_id is not None:
            self.price_list_combo.setCurrentIndex(max(0, self.price_list_combo.findData(doc.price_list_id)))
        if self._is_sales and doc.channel_code is not None:
            self.channel_combo.setCurrentIndex(max(0, self.channel_combo.findData(doc.channel_code)))
        self.reference_field.setText(doc.reference_no or "")
        self.description_field.setText(doc.description or "")
        links = []
        if doc.stock_document_id is not None:
            links.append(f"سندِ انبار: #{numerals.to_persian_digits(str(doc.stock_document_id))}")
        if doc.journal_entry_id is not None:
            links.append(f"سندِ حسابداری: #{numerals.to_persian_digits(str(doc.journal_entry_id))}")
        if doc.source_document_id is not None:
            links.append(f"سندِ مبدا: #{numerals.to_persian_digits(str(doc.source_document_id))}")
        self.links_label.setText("  |  ".join(links))
        self._lines = lines
        self._refresh_lines_table()
        self.totals_label.setText(
            f"جمعِ ناخالص: {numerals.format_amount(doc.subtotal_amount)}    تخفیف: {numerals.format_amount(doc.discount_amount)}    "
            f"مالیات: {numerals.format_amount(doc.tax_amount)}    جمعِ کل: {numerals.format_amount(doc.total_amount)}"
        )
        self.summary_cards.set_value("subtotal", numerals.format_amount(doc.subtotal_amount))
        self.summary_cards.set_value(
            "discount_tax", numerals.format_amount(doc.discount_amount + doc.tax_amount)
        )
        self.summary_cards.set_value("grand_total", numerals.format_amount(doc.total_amount))
        self._apply_status_state()

    def _refresh_lines_table(self) -> None:
        items_by_id = {it.item_id: it for it in self._items}
        self.lines_table.setRowCount(len(self._lines))
        for row_index, ln in enumerate(self._lines):
            item = items_by_id.get(ln.item_id)
            values = [
                f"{item.code} — {item.name or ''}" if item else str(ln.item_id),
                str(ln.quantity),
                str(ln.unit_price),
                str(ln.discount_amount),
                str(ln.tax_percent),
                str(ln.tax_amount),
                str(ln.line_total),
                ln.description or "",
            ]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, ln.line_id)
                self.lines_table.setItem(row_index, col_index, cell)

    def _apply_status_state(self) -> None:
        self.status_badge.setText(STATUS_LABELS.get(self._status_code, self._status_code))
        is_draft = self._status_code == "DRAFT"
        is_confirmed = self._status_code == "CONFIRMED"
        is_approved = self._status_code == "APPROVED"
        for widget in (self.date_field, self.counterparty_combo, self.warehouse_combo, self.price_list_combo, self.channel_combo, self.reference_field, self.description_field):
            widget.setEnabled(is_draft)
        self.save_button.setEnabled(is_draft)
        self.confirm_button.setEnabled(is_draft and self._document_id is not None)
        self.approve_button.setEnabled(is_confirmed)
        self.post_button.setEnabled(is_confirmed or is_approved)
        self.cancel_button.setEnabled(is_draft or is_confirmed or is_approved)

    def _reset_form(self, clear_only: bool = False) -> None:
        self._document_id = None
        self._status_code = "DRAFT"
        self._lines = []
        self.page_title.setText(f"{DOC_TYPE_TITLES[self.document_type_code]}ِ جدید")
        self.status_label.setText("")
        self.links_label.setText("")
        self.date_field.setDate(datetime.date.today())
        self.counterparty_combo.setCurrentIndex(0)
        self.warehouse_combo.setCurrentIndex(0)
        self.price_list_combo.setCurrentIndex(0)
        self.channel_combo.setCurrentIndex(0)
        self.reference_field.clear()
        self.description_field.clear()
        self.totals_label.setText("")
        for key in ("subtotal", "discount_tax", "grand_total"):
            self.summary_cards.set_value(key, "۰")
        self._refresh_lines_table()
        self._apply_status_state()
        if not clear_only:
            self.refresh()

    def edit_document(self, document_id: int) -> None:
        self._document_id = document_id
        self.refresh()

    def _header_fields(self) -> documents_service.DocumentHeaderFields | None:
        counterparty_id = self.counterparty_combo.currentData()
        if counterparty_id is None:
            self.status_label.setText("انتخابِ طرفِ‌حساب الزامی است.")
            return None
        company = app_session.current_company
        return documents_service.DocumentHeaderFields(
            counterparty_detail_account_id=counterparty_id, currency_id=company.base_currency_id,
            warehouse_id=self.warehouse_combo.currentData(),
            channel_code=self.channel_combo.currentData() if self._is_sales else None,
            price_list_id=self.price_list_combo.currentData(),
            reference_no=self.reference_field.text().strip() or None,
            description=self.description_field.text().strip() or None,
        )

    def _save_header(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        fields = self._header_fields()
        if fields is None:
            return
        try:
            if self._document_id is None:
                self._document_id = documents_service.create_document(
                    company_id, app_session.current_user.user_id, self.document_type_code, self.date_field.date(), fields
                )
            else:
                self.status_label.setText("")
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("")
        self._load_document()

    def _ensure_saved(self) -> bool:
        if self._document_id is None:
            self._save_header()
        return self._document_id is not None

    def _add_line(self) -> None:
        if not self._ensure_saved():
            return
        dialog = _LineDialog(self, self._items)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            documents_service.add_line(self._document_id, self._company_id(), **dialog.result_fields())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._load_document()

    def _selected_line(self):
        selected = self.lines_table.selectedItems()
        if not selected:
            return None
        line_id = selected[0].data(Qt.UserRole)
        return next((ln for ln in self._lines if ln.line_id == line_id), None)

    def _edit_line(self, *_args) -> None:
        line = self._selected_line()
        if line is None or self._document_id is None:
            return
        initial = {
            "item_id": line.item_id, "quantity": line.quantity, "unit_price": line.unit_price,
            "discount_amount": line.discount_amount, "tax_percent": line.tax_percent, "description": line.description,
        }
        dialog = _LineDialog(self, self._items, initial)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            documents_service.delete_line(line.line_id, self._document_id, self._company_id())
            documents_service.add_line(self._document_id, self._company_id(), **dialog.result_fields())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._load_document()

    def _delete_line(self) -> None:
        line = self._selected_line()
        if line is None or self._document_id is None:
            return
        confirm = QMessageBox.question(self, "حذفِ ردیف", "این ردیف حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            documents_service.delete_line(line.line_id, self._document_id, self._company_id())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._load_document()

    def _confirm(self) -> None:
        if self._document_id is None:
            return
        try:
            documents_service.confirm_document(self._document_id, self._company_id(), app_session.current_user.user_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("")
        self._load_document()

    def _approve(self) -> None:
        if self._document_id is None:
            return
        try:
            documents_service.approve_document(self._document_id, self._company_id())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("")
        self._load_document()

    def _post(self) -> None:
        if self._document_id is None:
            return
        confirm = QMessageBox.question(
            self, "ثبتِ نهایی", "این سند ثبتِ نهایی شود؟ پسِ این کار، سند دیگر قابلِ‌ویرایش/حذف نیست.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            documents_service.post_document(self._document_id, self._company_id(), app_session.current_user.user_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("")
        self._load_document()

    def _cancel(self) -> None:
        if self._document_id is None:
            return
        confirm = QMessageBox.question(self, "لغوِ سند", "این سند لغو شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            documents_service.cancel_document(self._document_id, self._company_id())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._load_document()
