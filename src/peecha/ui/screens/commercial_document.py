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
    QDialog,
    QDialogButtonBox,
    QGridLayout,
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
from peecha.services import companies as companies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.ui import theme
from peecha.ui.screens.inventory_document import _enter_signal
from peecha.ui.screens.journal_entry import _AmountField, _fill_options, _make_searchable_combo
from peecha.ui.screens.treasury_voucher import _EnterComboBox
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
    add_quick_add_button,
)

DOC_TYPE_TITLES = {
    "SALES_ORDER": "سفارشِ فروش",
    "SALES_PROFORMA": "پیش‌فاکتورِ فروش",
    "SALES_INVOICE": "فاکتورِ فروش",
    "SALES_RETURN": "برگشت از فروش",
    "PURCHASE_ORDER": "سفارشِ خرید",
    "PURCHASE_PROFORMA": "پیش‌فاکتورِ خرید",
    "PURCHASE_INVOICE": "فاکتورِ خرید",
    "PURCHASE_RETURN": "برگشت به تامین‌کننده",
}
STATUS_LABELS = {"DRAFT": "پیش‌نویس", "CONFIRMED": "تاییدشده", "APPROVED": "تصویب‌شده", "POSTED": "ثبتِ‌نهایی‌شده", "CANCELLED": "لغوشده"}
_SALES_TYPES = ("SALES_ORDER", "SALES_PROFORMA", "SALES_INVOICE", "SALES_RETURN")
# طبقِ درخواستِ صریح («سفارش/پیش‌فاکتور بتواند به فاکتور تبدیل شود»).
_CONVERTIBLE_TO_INVOICE_TYPES = ("SALES_ORDER", "SALES_PROFORMA", "PURCHASE_ORDER", "PURCHASE_PROFORMA")
_LINE_COLUMNS = ["کالا", "مقدار", "بهایِ واحد", "تخفیف", "درصدِ مالیات", "مالیات", "جمعِ ردیف", "توضیح"]


class _LineDialog(LayoutEditMixin, QDialog):
    def __init__(
        self, parent: QWidget, items: list[catalog_service.ItemRow], company_id: int, main_window,
        decimal_places: int, initial: dict | None = None, *, counterparty_id: int | None = None,
        price_list_id: int | None = None, document_type_code: str | None = None,
        document_date: datetime.date | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ردیفِ سند")
        self.setMinimumWidth(380)
        self._company_id = company_id
        self._counterparty_id = counterparty_id
        self._price_list_id = price_list_id
        self._document_type_code = document_type_code
        self._document_date = document_date
        layout = QVBoxLayout(self)
        self._items_by_id = {it.item_id: it for it in items}

        item_options = [(it.item_id, f"{it.code} — {it.name or ''}") for it in items]
        item_row_widget = QWidget()
        item_row_layout = QHBoxLayout(item_row_widget)
        item_row_layout.setContentsMargins(0, 0, 0, 0)
        item_row_layout.setSpacing(3)
        self.item_combo = _make_searchable_combo(item_options)
        item_row_layout.addWidget(self.item_combo, stretch=1)
        add_quick_add_button(item_row_layout, self.item_combo, main_window, "GL_DIM", "تعریفِ کالایِ تازه")

        # طبقِ سندِ راهنمایِ UI/UX (بخشِ ۶.۲/۶.۳): فیلدهایِ مبلغ/عدد باید
        # _AmountField باشند (گروه‌بندیِ سه‌رقمیِ زنده + ارقامِ فارسی)، نه
        # QDoubleSpinBoxِ خام — دقیقاً هم‌الگو با journal_entry.py/
        # treasury_voucher.py/treasury_petty_cash.py.
        self.quantity_field = _AmountField()
        self.quantity_field.setDecimals(3)

        self.unit_price_field = _AmountField()
        self.unit_price_field.setDecimals(decimal_places)

        self.discount_field = _AmountField()
        self.discount_field.setDecimals(decimal_places)

        self.tax_percent_field = _AmountField()
        self.tax_percent_field.setDecimals(2)

        self.description_field = QLineEdit()

        self.fields_grid = FieldGrid([
            FieldSpec("item", "کالا", item_row_widget, span=2),
            FieldSpec("quantity", "مقدار (واحدِ پایهٔ کالا)", self.quantity_field, span=1),
            FieldSpec("unit_price", "بهایِ واحد (پیشنهادی از فهرستِ قیمت — قابلِ‌ویرایش)", self.unit_price_field, span=1),
            FieldSpec("discount", "تخفیفِ مبلغی", self.discount_field, span=1),
            FieldSpec("tax_percent", "درصدِ مالیات (بعدِ تخفیف)", self.tax_percent_field, span=1),
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
        # طبقِ بررسیِ عملی (هم‌الگو با treasury_voucher.py — این‌جا با
        # QTestِ واقعی دوباره تاییدشد): setAutoDefault(False) به‌تنهایی
        # کافی نیست، چون QDialogButtonBox با هر show() دوباره دکمه‌یِ
        # نقشِ AcceptRole را default (isDefault=True) می‌کند، جدا از
        # پرچمِ autoDefault؛ جلوگیریِ واقعی در keyPressEvent پایین‌تر است.
        buttons.button(QDialogButtonBox.Ok).setAutoDefault(False)
        buttons.button(QDialogButtonBox.Cancel).setAutoDefault(False)
        layout.addWidget(buttons)

        # طبقِ سندِ راهنما (زنجیره‌یِ کاملِ Enter، بدونِ استثنا).
        enter_chain = [
            self.item_combo, self.quantity_field, self.unit_price_field,
            self.discount_field, self.tax_percent_field, self.description_field,
        ]
        for widget, next_widget in zip(enter_chain, enter_chain[1:]):
            _enter_signal(widget).connect(next_widget.setFocus)
        _enter_signal(enter_chain[-1]).connect(self._on_accept)

        self._is_new_row = initial is None
        self._price_manually_edited = False
        self.unit_price_field.textEdited.connect(self._on_price_edited_manually)
        self.item_combo.currentIndexChanged.connect(self._on_item_changed)
        self.quantity_field.valueChanged.connect(self._suggest_price)

        if initial is not None:
            index = self.item_combo.findData(initial["item_id"])
            if index >= 0:
                self.item_combo.setCurrentIndex(index)
            self.quantity_field.setValue(float(initial["quantity"]))
            self.unit_price_field.setValue(float(initial["unit_price"]))
            self.discount_field.setValue(float(initial["discount_amount"]))
            self.tax_percent_field.setValue(float(initial["tax_percent"]))
            self.description_field.setText(initial["description"] or "")
        else:
            self._on_item_changed()

    def keyPressEvent(self, event) -> None:
        # جلوگیریِ واقعی از باگِ autoDefault (هم‌الگو با
        # treasury_voucher._MethodDetailsDialog): چون همه‌یِ فیلدهایِ این
        # دیالوگ زنجیره‌یِ Enterِ خودشان را دارند، دیگر نیازی نیست QDialog
        # با دیدنِ Enter دوباره دکمه‌یِ پیش‌فرض را کلیک کند.
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_item_changed(self) -> None:
        """طبقِ درخواستِ صریح: درصدِ مالیات با اولویتِ کالا -> تنظیماتِ
        کلیِ شرکت پیش‌پر می‌شود — فقط برایِ ردیفِ *تازه* (initial=None)،
        نه هنگامِ ویرایشِ ردیفِ ازپیش‌ذخیره‌شده که مقدارِ ثبت‌شده‌اش را
        نباید بازنویسی کند."""
        item_id = self.item_combo.currentData()
        if item_id is None:
            return
        default_tax = catalog_service.resolve_default_tax_percent(self._company_id, item_id)
        self.tax_percent_field.setValue(float(default_tax))
        self._price_manually_edited = False
        self._suggest_price()

    def _on_price_edited_manually(self) -> None:
        self._price_manually_edited = True

    def _suggest_price(self) -> None:
        """طبقِ رفعِ باگِ واقعی («قیمتِ کالا از لیستِ قیمت پیشنهاد
        نمی‌شود»): قبلاً این مقدار فقط داخلِ سرویس (add_line) و در
        سکوت محاسبه می‌شد — کاربر پیش از ذخیره هرگز آن را نمی‌دید. حالا
        همان منطق (commercial_pricing.resolve_price) این‌جا هم صدا زده
        می‌شود تا بهایِ واحد، همین که کالا/مقدار مشخص شد، در فیلد نمایش
        داده شود — هنوز کاملاً قابلِ‌ویرایشِ دستی."""
        if not self._is_new_row or self._price_manually_edited:
            return
        item_id = self.item_combo.currentData()
        if item_id is None or self._counterparty_id is None or self._document_type_code is None:
            return
        item = self._items_by_id.get(item_id)
        if item is None:
            return
        quantity = decimal.Decimal(str(self.quantity_field.value())) if self.quantity_field.value() > 0 else decimal.Decimal(1)
        try:
            resolved = pricing_service.resolve_price(
                self._company_id, self._counterparty_id, item_id, item.base_uom_id, quantity,
                self._price_list_id, self._document_type_code, self._document_date,
            )
        except ValueError:
            return
        self.unit_price_field.setValue(float(resolved.unit_price))
        if resolved.discount_amount and self.discount_field.value() == 0:
            self.discount_field.setValue(float(resolved.discount_amount))

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
        quantity = decimal.Decimal(str(self.quantity_field.value()))
        return {
            "item_id": item_id,
            "uom_id": item.base_uom_id if item else 0,
            "quantity": quantity,
            # طبقِ رفعِ باگِ واقعی («ردیف بعدِ ثبت نمایش داده نمی‌شود»):
            # این فیلد قبلاً اصلاً در این دیکشنری نبود — چون
            # documents_service.add_line آن را الزامی (بدونِ مقدارِ
            # پیش‌فرض) می‌خواهد، هر افزودنِ ردیف با TypeErrorِ خاموش
            # (فقط رویِ کنسول، نه در UI) رد می‌شد و کاربر فقط می‌دید که
            # هیچ ردیفی اضافه نشد. چون این فرم هنوز تبدیلِ واحد ندارد
            # (طبقِ داکیومنتِ بالایِ فایل)، quantity_base همیشه با
            # quantity برابر است — هم‌الگو با inventory_document.py.
            "quantity_base": quantity,
            "unit_price": decimal.Decimal(str(self.unit_price_field.value())) if self.unit_price_field.value() > 0 else None,
            "discount_amount": decimal.Decimal(str(self.discount_field.value())),
            "tax_percent": decimal.Decimal(str(self.tax_percent_field.value())),
            "description": self.description_field.text().strip() or None,
        }


class _ConvertToInvoiceDialog(LayoutEditMixin, QDialog):
    """طبقِ درخواستِ صریح («صرفِ دکمه‌یِ تبدیلِ یک‌باره خیلی ساده است»):
    به‌جایِ تبدیلِ کاملِ خودکارِ همه‌یِ ردیف‌ها با یک کلیک، این دیالوگ
    مقدارِ سفارش‌شده/فاکتورشده/مانده‌یِ هر ردیف را نشان می‌دهد و اجازه
    می‌دهد کاربر برایِ همین‌بار مقدارِ کمتری (تبدیلِ مرحله‌ای) وارد کند —
    پیش‌فرضِ هر ردیف، کلِ مانده‌اش است."""

    _COLUMNS = ["کالا", "سفارش‌شده", "فاکتورشده", "مانده", "مقدارِ این‌بار"]

    def __init__(self, parent: QWidget, fulfillment: list, items_by_id: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle("تبدیل به فاکتور")
        self.setMinimumWidth(520)
        self._fulfillment = [f for f in fulfillment if f.remaining_quantity > 0]
        self._qty_fields: dict[int, _AmountField] = {}

        layout = QVBoxLayout(self)
        info = QLabel("مقدارِ این‌بار برایِ هر ردیف را مشخص کنید (پیش‌فرض: کلِ مانده).")
        layout.addWidget(info)

        table = QTableWidget(len(self._fulfillment), len(self._COLUMNS))
        table.setHorizontalHeaderLabels(self._COLUMNS)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for row_index, f in enumerate(self._fulfillment):
            item = items_by_id.get(f.item_id)
            table.setItem(row_index, 0, QTableWidgetItem(f"{item.code} — {item.name or ''}" if item else str(f.item_id)))
            table.setItem(row_index, 1, QTableWidgetItem(numerals.format_money(f.quantity, 3)))
            table.setItem(row_index, 2, QTableWidgetItem(numerals.format_money(f.invoiced_quantity, 3)))
            table.setItem(row_index, 3, QTableWidgetItem(numerals.format_money(f.remaining_quantity, 3)))
            qty_field = _AmountField()
            qty_field.setDecimals(3)
            qty_field.setValue(float(f.remaining_quantity))
            self._qty_fields[f.line_id] = qty_field
            table.setCellWidget(row_index, 4, qty_field)
        table.resizeRowsToContents()
        layout.addWidget(table)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("تبدیل")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Ok).setAutoDefault(False)
        buttons.button(QDialogButtonBox.Cancel).setAutoDefault(False)
        layout.addWidget(buttons)

    def keyPressEvent(self, event) -> None:
        # هم‌الگو با _LineDialog — جلوگیریِ واقعی از باگِ autoDefaultِ
        # QDialogButtonBox (طبقِ سندِ راهنما، بخشِ ۶.۳-ت).
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_accept(self) -> None:
        quantities = {line_id: decimal.Decimal(str(field.value())) for line_id, field in self._qty_fields.items()}
        if all(q <= 0 for q in quantities.values()):
            self.status_label.setText("حداقل برایِ یک ردیف مقداری وارد کنید.")
            return
        for f in self._fulfillment:
            if quantities[f.line_id] > f.remaining_quantity:
                self.status_label.setText("مقدارِ واردشده برایِ یک ردیف از مانده‌اش بیشتر است.")
                return
        self.accept()

    def result_quantities(self) -> dict[int, decimal.Decimal]:
        return {line_id: decimal.Decimal(str(field.value())) for line_id, field in self._qty_fields.items() if field.value() > 0}


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
        self._decimal_places = 0

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

        # طبقِ گزارشِ تکراریِ کاربر («هدرِ فرم‌هایِ انبار/فروش/خرید هنوز
        # نامرتب است — فقط یک فرم درست شد»): این هدر هم اکنون هم‌الگو با
        # journal_entry.py/treasury_voucher.py یک کارتِ واحد با
        # QGridLayoutِ فشرده است، نه چند QHBoxLayoutِ خامِ پشتِ سرهم.
        header_card = QWidget()
        header_card.setObjectName("card")
        header_grid = QGridLayout(header_card)
        header_grid.setContentsMargins(8, 5, 8, 5)
        header_grid.setSpacing(3)

        header_grid.addWidget(QLabel("تاریخ"), 0, 0)
        self.date_field = JalaliDateEdit()
        header_grid.addWidget(self.date_field, 1, 0)

        header_grid.addWidget(QLabel("مشتری" if self._is_sales else "تامین‌کننده"), 0, 1)
        counterparty_row = QHBoxLayout()
        counterparty_row.setContentsMargins(0, 0, 0, 0)
        counterparty_row.setSpacing(3)
        self.counterparty_combo = _make_searchable_combo([])
        counterparty_row.addWidget(self.counterparty_combo, stretch=1)
        add_quick_add_button(
            counterparty_row, self.counterparty_combo, main_window, "GL_DIM",
            "تعریفِ مشتریِ تازه" if self._is_sales else "تعریفِ تامین‌کننده‌یِ تازه",
        )
        header_grid.addLayout(counterparty_row, 1, 1)

        header_grid.addWidget(QLabel("انبار"), 0, 2)
        warehouse_row = QHBoxLayout()
        warehouse_row.setContentsMargins(0, 0, 0, 0)
        warehouse_row.setSpacing(3)
        self.warehouse_combo = _EnterComboBox()
        warehouse_row.addWidget(self.warehouse_combo, stretch=1)
        add_quick_add_button(warehouse_row, self.warehouse_combo, main_window, "INV_WAREHOUSES", "تعریفِ انبارِ تازه")
        header_grid.addLayout(warehouse_row, 1, 2)

        # طبقِ درخواستِ صریح («فیلدِ شماره‌یِ سفارش روی هدر باز بشه»):
        # قبلاً شماره‌یِ سند فقط داخلِ عنوانِ صفحه («سفارشِ فروش #۵»، فقط
        # بعدِ ذخیره) دیده می‌شد؛ حالا یک فیلدِ صریح و همیشه‌حاضر در هدر
        # هم دارد (پیش از ذخیره: «—»).
        header_grid.addWidget(QLabel("شمارهٔ سند"), 0, 3)
        self.document_no_field = QLineEdit()
        self.document_no_field.setReadOnly(True)
        self.document_no_field.setFocusPolicy(Qt.NoFocus)
        self.document_no_field.setAlignment(Qt.AlignCenter)
        self.document_no_field.setText("—")
        header_grid.addWidget(self.document_no_field, 1, 3)

        header_grid.addWidget(QLabel("شمارهٔ مرجع"), 0, 4)
        self.reference_field = QLineEdit()
        header_grid.addWidget(self.reference_field, 1, 4)

        # طبقِ رفعِ باگِ واقعی («عرضِ فیلدِ فهرستِ قیمت کمه، عرضِ کانال
        # کم بشه اضافه شود به فهرستِ قیمت»): فهرستِ قیمت حالا هم‌عرضِ
        # دو ستون (به‌اندازه‌یِ ستونِ مشتری/تامین‌کننده که پهن‌تر است) و
        # کانال فقط یک ستون است.
        header_grid.addWidget(QLabel("فهرستِ قیمت"), 2, 0, 1, 2)
        self.price_list_combo = _EnterComboBox()
        header_grid.addWidget(self.price_list_combo, 3, 0, 1, 2)

        self.channel_box = QWidget()
        channel_layout = QVBoxLayout(self.channel_box)
        channel_layout.setContentsMargins(0, 0, 0, 0)
        channel_layout.setSpacing(3)
        channel_layout.addWidget(QLabel("کانال"))
        self.channel_combo = _EnterComboBox()
        channel_layout.addWidget(self.channel_combo)
        header_grid.addWidget(self.channel_box, 2, 2, 2, 1)
        self.channel_box.setVisible(self._is_sales)

        header_grid.addWidget(QLabel("توضیح"), 2, 3, 1, 2)
        self.description_field = QLineEdit()
        header_grid.addWidget(self.description_field, 3, 3, 1, 2)

        header_grid.setColumnStretch(0, 1)
        header_grid.setColumnStretch(1, 2)
        header_grid.setColumnStretch(2, 1)
        header_grid.setColumnStretch(3, 1)
        header_grid.setColumnStretch(4, 1)
        self.body_layout.addWidget(header_card)

        # زنجیره‌ی کاملِ Enter رویِ هدر — بدونِ استثنا (طبقِ سندِ راهنما).
        header_chain = [
            self.date_field, self.counterparty_combo, self.warehouse_combo, self.reference_field,
            self.price_list_combo, self.channel_combo, self.description_field,
        ]
        for widget, next_widget in zip(header_chain, header_chain[1:]):
            _enter_signal(widget).connect(next_widget.setFocus)
        # طبقِ درخواستِ صریح («بعدِ اینترِ فیلدِ آخرِ هدر خودکار برود به
        # اولین ردیف»): زنجیره‌یِ Enterِ هدر حالا مستقیم به افزودنِ اولین
        # ردیف می‌رسد، به‌جایِ متوقف‌شدن روی توضیح.
        _enter_signal(header_chain[-1]).connect(self._add_line)

        # طبقِ رفعِ باگِ واقعی («هدر هنوز فضایِ زیادی اشغال کرده»): وضعیت و
        # پیوندهایِ سند هردو متنِ کوتاهِ اطلاعاتی‌اند — قبلاً هرکدام یک
        # ردیفِ کاملِ جدا بودند؛ حالا کنارِ هم، یک ردیف.
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(8)
        self.status_badge = QLabel("")
        self.status_badge.setObjectName("statusBadge")
        status_row.addWidget(self.status_badge)
        self.links_label = QLabel("")
        status_row.addWidget(self.links_label)
        status_row.addStretch(1)
        self.body_layout.addLayout(status_row)

        # همان‌طور: عنوانِ بخشِ «ردیف‌ها» و دکمهٔ افزودن هرکدام یک ردیفِ
        # کاملِ جدا بودند، بدونِ نیازِ واقعی — حالا کنارِ هم.
        lines_header_row = QHBoxLayout()
        lines_header_row.setContentsMargins(0, 0, 0, 0)
        lines_header_row.setSpacing(8)
        lines_title = QLabel("ردیف‌ها")
        lines_title.setObjectName("sectionTitle")
        lines_header_row.addWidget(lines_title)
        add_line_button = QPushButton("➕")
        add_line_button.setObjectName("primaryIconButton")
        add_line_button.setFixedWidth(48)
        add_line_button.setToolTip("افزودنِ ردیف")
        add_line_button.clicked.connect(self._add_line)
        lines_header_row.addWidget(add_line_button)
        lines_header_row.addStretch(1)
        self.body_layout.addLayout(lines_header_row)

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
        self.new_button.setToolTip("سندِ جدید — فرم را برایِ ثبتِ سندِ بعدی خالی می‌کند")
        self.new_button.clicked.connect(self._reset_form)
        self.footer_layout.addWidget(self.new_button)

        self.save_button = QPushButton("💾")
        self.save_button.setObjectName("primaryIconButton")
        self.save_button.setFixedWidth(48)
        self.save_button.setToolTip("۱) ذخیرهٔ پیش‌نویس — سند ثبت می‌شود ولی هنوز قطعی نیست؛ سرِسند و ردیف‌ها بعداً قابلِ‌ویرایش/حذف‌اند")
        self.save_button.clicked.connect(self._save_header)
        self.footer_layout.addWidget(self.save_button)

        self.confirm_button = QPushButton("✅")
        self.confirm_button.setObjectName("iconButton")
        self.confirm_button.setFixedWidth(44)
        self.confirm_button.setToolTip("۲) تاییدِ سند — گامِ اولِ گردشِ کار پس از پیش‌نویس؛ سند برایِ تصویب/ثبتِ نهایی آماده می‌شود")
        self.confirm_button.clicked.connect(self._confirm)
        self.footer_layout.addWidget(self.confirm_button)

        self.approve_button = QPushButton("👍")
        self.approve_button.setObjectName("iconButton")
        self.approve_button.setFixedWidth(44)
        self.approve_button.setToolTip("۳) تصویبِ سند — تاییدِ مدیریتیِ اضافه پیش از ثبتِ نهایی (اختیاری، پیش از ثبتِ نهایی انجام می‌شود)")
        self.approve_button.clicked.connect(self._approve)
        self.footer_layout.addWidget(self.approve_button)

        self.post_button = QPushButton("🔒")
        self.post_button.setObjectName("primaryIconButton")
        self.post_button.setFixedWidth(48)
        self.post_button.setToolTip("۴) ثبتِ نهایی — قطعی و برگشت‌ناپذیر؛ سندِ انبار/حسابداریِ واقعی همین‌جا ساخته می‌شود")
        self.post_button.clicked.connect(self._post)
        self.footer_layout.addWidget(self.post_button)

        self.cancel_button = QPushButton("🚫")
        self.cancel_button.setObjectName("dangerIconButton")
        self.cancel_button.setFixedWidth(44)
        self.cancel_button.setToolTip("لغوِ سند — سند باطل می‌شود (فقط پیش از ثبتِ نهایی ممکن است)")
        self.cancel_button.clicked.connect(self._cancel)
        self.footer_layout.addWidget(self.cancel_button)

        # طبقِ درخواستِ صریح («سفارش/پیش‌فاکتور بتواند به فاکتور تبدیل
        # شود»): فقط برایِ انواعِ سفارش/پیش‌فاکتور نمایش داده می‌شود.
        self.convert_button = QPushButton("→")
        self.convert_button.setObjectName("primaryIconButton")
        self.convert_button.setFixedWidth(48)
        self.convert_button.setToolTip("تبدیل به فاکتور — از مقدارِ باقی‌ماندهٔ این سند، فاکتورِ تازه می‌سازد")
        self.convert_button.clicked.connect(self._convert_to_invoice)
        self.convert_button.setVisible(document_type_code in _CONVERTIBLE_TO_INVOICE_TYPES)
        self.footer_layout.addWidget(self.convert_button)
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
        self._decimal_places = companies_service.get_base_currency_decimal_places(company_id)
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
            # طبقِ درخواستِ صریح: فقط نامِ فهرستِ قیمت نمایش داده شود،
            # نه «کد — نام» (که با عرضِ محدودِ فیلد بریده می‌شد).
            self.price_list_combo.addItem(pl.name, pl.price_list_id)
        if current_price_list is not None:
            index = self.price_list_combo.findData(current_price_list)
            if index >= 0:
                self.price_list_combo.setCurrentIndex(index)

        if self._document_id is not None:
            self._load_document()
        else:
            self._reset_form(clear_only=True)

        # طبقِ درخواستِ صریح: هر بار این فرم باز می‌شود، فوکوس مستقیم
        # رویِ تاریخ می‌رود — هم‌الگو با inventory_document.py.
        self.date_field.setFocus()
        self.date_field.selectAll()

    def _load_document(self) -> None:
        company_id = self._company_id()
        try:
            doc, lines = documents_service.get_document(self._document_id, company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._status_code = doc.status_code
        self.page_title.setText(f"{DOC_TYPE_TITLES[self.document_type_code]} #{numerals.to_persian_digits(str(doc.document_no))}")
        self.document_no_field.setText(numerals.to_persian_digits(str(doc.document_no)))
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
        dp = self._decimal_places
        self.summary_cards.set_value("subtotal", numerals.format_money(doc.subtotal_amount, dp))
        self.summary_cards.set_value(
            "discount_tax", numerals.format_money(doc.discount_amount + doc.tax_amount, dp)
        )
        self.summary_cards.set_value("grand_total", numerals.format_money(doc.total_amount, dp))
        self._apply_status_state()

    def _refresh_lines_table(self) -> None:
        # طبقِ سندِ راهنمایِ UI/UX (بخشِ ۶.۳ — نمایشِ مبلغ‌ها طبقِ تنظیماتِ
        # واحدِ پولی): قبلاً این جدول با str() خامِ Decimal پر می‌شد —
        # نه گروه‌بندیِ سه‌رقمی، نه ارقامِ فارسی، نه تعدادِ اعشارِ درستِ
        # واحدِ پول.
        dp = self._decimal_places
        items_by_id = {it.item_id: it for it in self._items}
        self.lines_table.setRowCount(len(self._lines))
        for row_index, ln in enumerate(self._lines):
            item = items_by_id.get(ln.item_id)
            values = [
                f"{item.code} — {item.name or ''}" if item else str(ln.item_id),
                numerals.format_money(ln.quantity, 3),
                numerals.format_money(ln.unit_price, dp),
                numerals.format_money(ln.discount_amount, dp),
                numerals.format_money(ln.tax_percent, 2),
                numerals.format_money(ln.tax_amount, dp),
                numerals.format_money(ln.line_total, dp),
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
        # طبقِ رفعِ باگِ واقعی («سفارشات در حال حاضر ویرایش نمیشه»):
        # برخلافِ فاکتور/برگشت که بعدِ تاییدشدن برایِ همیشه قفل می‌ماند،
        # سفارش/پیش‌فاکتور تا وقتی ثبتِ‌نهایی/لغو نشده قابلِ‌ویرایش است
        # (هم‌الگو با services/commercial_documents.py:_get_editable_document).
        is_order_type = self.document_type_code in _CONVERTIBLE_TO_INVOICE_TYPES
        is_editable = is_draft or (is_order_type and (is_confirmed or is_approved))
        for widget in (self.date_field, self.counterparty_combo, self.warehouse_combo, self.price_list_combo, self.channel_combo, self.reference_field, self.description_field):
            widget.setEnabled(is_editable)
        self.save_button.setEnabled(is_editable)
        self.confirm_button.setEnabled(is_draft and self._document_id is not None)
        self.approve_button.setEnabled(is_confirmed)
        self.post_button.setEnabled(is_confirmed or is_approved)
        self.cancel_button.setEnabled(is_draft or is_confirmed or is_approved)
        is_posted = self._status_code == "POSTED"
        self.convert_button.setEnabled(is_confirmed or is_approved or is_posted)

    def _reset_form(self, clear_only: bool = False) -> None:
        self._document_id = None
        self._status_code = "DRAFT"
        self._lines = []
        self.page_title.setText(f"{DOC_TYPE_TITLES[self.document_type_code]}ِ جدید")
        self.document_no_field.setText("—")
        self.status_label.setText("")
        self.links_label.setText("")
        self.date_field.setDate(datetime.date.today())
        self.counterparty_combo.setCurrentIndex(0)
        self.warehouse_combo.setCurrentIndex(0)
        self.price_list_combo.setCurrentIndex(0)
        self.channel_combo.setCurrentIndex(0)
        self.reference_field.clear()
        self.description_field.clear()
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
        is_new = self._document_id is None
        try:
            if is_new:
                self._document_id = documents_service.create_document(
                    company_id, app_session.current_user.user_id, self.document_type_code, self.date_field.date(), fields
                )
            else:
                # طبقِ رفعِ باگِ واقعی: قبلاً ذخیره‌یِ هدرِ سندِ ازپیش‌موجود
                # اصلاً هیچ صدازدنی به سرویس نداشت — تغییراتِ فیلدهایِ هدر
                # (برایِ سفارش/پیش‌فاکتورِ تاییدشده، که حالا قابلِ‌ویرایش
                # است) در سکوت گم می‌شد.
                documents_service.update_document_header(self._document_id, company_id, self.date_field.date(), fields)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            QMessageBox.warning(self, "خطا در ذخیره", str(exc))
            return
        self._load_document()
        # طبقِ رفعِ باگِ واقعی («بعدِ ذخیره هیچ پیامی نمی‌دهد»): قبلاً این
        # مسیرِ موفقیت فقط status_label را خالی می‌کرد — بدونِ هیچ
        # تاییدِ مثبتی، کاربر نمی‌فهمید سند واقعاً ذخیره شده یا نه.
        theme.set_status_label(
            self.status_label, "سند به‌عنوانِ پیش‌نویس ذخیره شد." if is_new else "تغییراتِ سند ذخیره شد.", ok=True,
        )

    def _ensure_saved(self) -> bool:
        if self._document_id is None:
            self._save_header()
        return self._document_id is not None

    def _add_line(self) -> None:
        if not self._ensure_saved():
            return
        dialog = _LineDialog(
            self, self._items, self._company_id(), self._main_window, self._decimal_places,
            counterparty_id=self.counterparty_combo.currentData(), price_list_id=self.price_list_combo.currentData(),
            document_type_code=self.document_type_code, document_date=self.date_field.date(),
        )
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
        dialog = _LineDialog(self, self._items, self._company_id(), self._main_window, self._decimal_places, initial)
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
            # طبقِ رفعِ باگِ واقعی: قبلاً این خطا فقط در یک برچسبِ ساکت
            # نمایش داده می‌شد — کاربر (به‌خصوص خطایِ «حساب هنوز در
            # تنظیمات مشخص نشده») به‌راحتی آن را نمی‌دید و فکر می‌کرد
            # هیچ اتفاقی نیفتاده. حالا هم‌الگو با خطاهایِ ردیف، یک
            # دیالوگِ مسدودکننده هم نمایش می‌دهد.
            self.status_label.setText(str(exc))
            QMessageBox.warning(self, "خطا در تاییدِ سند", str(exc))
            return
        self._load_document()
        theme.set_status_label(self.status_label, "سند تایید شد.", ok=True)

    def _approve(self) -> None:
        if self._document_id is None:
            return
        try:
            documents_service.approve_document(self._document_id, self._company_id())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            QMessageBox.warning(self, "خطا در تصویبِ سند", str(exc))
            return
        self._load_document()
        theme.set_status_label(self.status_label, "سند تصویب شد.", ok=True)

    def _post(self) -> None:
        if self._document_id is None:
            return
        confirm = QMessageBox.question(
            self, "ثبتِ نهایی", "این سند ثبتِ نهایی شود؟ پسِ این کار، سند دیگر قابلِ‌ویرایش/حذف نیست.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        company_id = self._company_id()
        try:
            result = documents_service.post_document(self._document_id, company_id, app_session.current_user.user_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            QMessageBox.warning(self, "خطا در ثبتِ نهایی", str(exc))
            return
        # طبقِ رفعِ باگِ واقعی («بعدِ تایید، فرم ریست نمی‌شود»): بعدِ ثبتِ
        # نهایی، سند برایِ همیشه قفل است — دیگر کاری رویِ همین رکورد از
        # این فرم ممکن نیست، پس فرم برایِ سندِ بعدی ریست می‌شود، به‌جایِ
        # نگه‌داشتنِ سندِ بسته‌شده روی صفحه.
        je_note = (
            f" (سندِ حسابداریِ #{numerals.to_persian_digits(str(result.journal_entry_id))} ساخته شد.)"
            if result.journal_entry_id is not None else ""
        )
        # طبقِ درخواستِ صریح («بعدِ تاییدِ فاکتورِ فروش فرمِ دریافت باز
        # بشه ... همین‌طور برایِ فاکتورِ خرید فرمِ پرداخت»): پیش از ریست،
        # اطلاعاتِ لازم برایِ فرمِ دریافت/پرداخت را نگه می‌داریم.
        posted_doc, _ = documents_service.get_document(self._document_id, company_id)
        posted_type = self.document_type_code
        posted_counterparty_id = posted_doc.counterparty_detail_account_id
        posted_total = posted_doc.total_amount
        posted_no = posted_doc.document_no
        self._reset_form()
        theme.set_status_label(self.status_label, f"سند ثبتِ نهایی شد.{je_note}", ok=True)

        if posted_type in ("SALES_INVOICE", "PURCHASE_INVOICE") and self._main_window is not None:
            is_sales = posted_type == "SALES_INVOICE"
            noun = "دریافتِ وجه" if is_sales else "پرداختِ وجه"
            confirm_payment = QMessageBox.question(
                self, noun,
                f"آیا برایِ این فاکتور {noun} ثبت می‌شود؟\n(اگر نسیه است و هنوز پرداختی صورت نگرفته، «خیر» را انتخاب کنید.)",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm_payment == QMessageBox.Yes:
                nav_code = "TREASURY_RECEIPT" if is_sales else "TREASURY_PAYMENT"
                description = f"بابتِ {DOC_TYPE_TITLES[posted_type]}ِ #{numerals.to_persian_digits(str(posted_no))}"
                self._main_window.open_screen(
                    nav_code,
                    then=lambda screen: screen.prefill_for_invoice(posted_counterparty_id, posted_total, description),
                )

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
            QMessageBox.warning(self, "خطا در لغوِ سند", str(exc))
            return
        # لغو هم مثلِ ثبتِ نهایی یک وضعیتِ نهایی‌ست — سند دیگر رویِ همین
        # فرم قابلِ‌ادامه‌کاری نیست، پس فرم برایِ سندِ بعدی ریست می‌شود.
        self._reset_form()
        theme.set_status_label(self.status_label, "سند لغو شد.", ok=True)

    def _convert_to_invoice(self) -> None:
        if self._document_id is None:
            return
        company_id = self._company_id()
        try:
            fulfillment = documents_service.get_line_fulfillment(self._document_id, company_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا در تبدیل به فاکتور", str(exc))
            return
        if not any(f.remaining_quantity > 0 for f in fulfillment):
            QMessageBox.information(self, "تبدیل به فاکتور", "چیزی برایِ تبدیل به فاکتور باقی نمانده است — کل این سند قبلاً فاکتور شده.")
            return
        items_by_id = {it.item_id: it for it in self._items}
        dialog = _ConvertToInvoiceDialog(self, fulfillment, items_by_id)
        if dialog.exec() != QDialog.Accepted:
            return
        is_sales = self.document_type_code.startswith("SALES")
        target_title = "فاکتورِ فروش" if is_sales else "فاکتورِ خرید"
        try:
            new_document_id = documents_service.convert_to_invoice(
                self._document_id, company_id, app_session.current_user.user_id, datetime.date.today(),
                line_quantities=dialog.result_quantities(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا در تبدیل به فاکتور", str(exc))
            return
        # طبقِ درخواستِ صریح («مانده‌یِ هر سفارش را بتوان دید و دوباره به
        # فاکتور تبدیل کرد»): برخلافِ نسخه‌یِ قبلی که به فاکتورِ تازه
        # می‌پرید، این‌جا رویِ همان سفارش می‌مانیم و دوباره بارگذاری
        # می‌کنیم تا مانده‌یِ به‌روزشده بلافاصله دیده شود.
        self._load_document()
        theme.set_status_label(
            self.status_label,
            f"{target_title} #{numerals.to_persian_digits(str(new_document_id))} از رویِ این سند ساخته شد.",
            ok=True,
        )
