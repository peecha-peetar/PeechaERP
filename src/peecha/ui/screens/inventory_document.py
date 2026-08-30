"""فرمِ اسنادِ عملیاتیِ انبار — رسید/حواله/انتقال/برگشت/اصلاح، همه رویِ
همان اسکلتِ سرِسند+ردیفِ inv.stock_documents/stock_document_lines
(services/inventory_documents.py) و موتورِ Postِ services/inventory_engine.py.

طبقِ اسکوپِ آگاهانهٔ این دور: تبدیلِ واحد (UOM conversion)، بچ/سریال/QC،
و ارجاعِ صریحِ برگشت به ردیفِ سندِ اصلی، به دورِ بعدی موکول شده‌اند — هر
ردیف با واحدِ پایهٔ خودِ کالا ثبت می‌شود (quantity_base = quantity)."""

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
from peecha.services import companies as companies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_documents as documents_service
from peecha.services import inventory_engine as engine_service
from peecha.services import inventory_locations as locations_service
from peecha.ui import theme
from peecha.ui.screens.journal_entry import _AmountField, _fill_options, _make_searchable_combo
from peecha.ui.screens.treasury_voucher import _EnterComboBox
from peecha.ui.widgets import FieldHelpMixin, FormScreenBase, JalaliDateEdit, SectionStepper, add_quick_add_button

DOC_TYPE_TITLES = {
    "RECEIPT": "رسید",
    "ISSUE": "حواله",
    "TRANSFER": "انتقال",
    "RETURN_IN": "برگشت از فروش",
    "RETURN_OUT": "برگشت به تامین‌کننده",
    "ADJUSTMENT": "اصلاحِ موجودی",
}
STATUS_LABELS = {"DRAFT": "پیش‌نویس", "CONFIRMED": "تاییدشده", "POSTED": "ثبتِ‌نهایی‌شده", "CANCELLED": "لغوشده"}
_LINE_COLUMNS = ["کالا", "مقدار", "مکان", "مکانِ مقصد", "بهایِ واحد", "بهایِ کل", "دلیل", "توضیح"]


def _enter_signal(widget: QWidget):
    """سیگنالِ Enterِ درستِ هر نوع فیلد — برایِ ساختِ زنجیره‌هایِ ناوبریِ
    کیبوردی، هم در هدرِ فرم و هم در دیالوگِ ردیف."""
    if isinstance(widget, _EnterComboBox):
        return widget.enterPressed
    if isinstance(widget, (QComboBox, QDoubleSpinBox)):
        return widget.lineEdit().returnPressed
    return widget.returnPressed


_COST_HISTORY_COLUMNS = ["نوع", "شماره", "تاریخ", "بهایِ واحد"]


class _ItemCostHistoryDialog(QDialog):
    """طبقِ درخواستِ صریح: ۱۰ بهایِ آخرِ این کالا از همین طرفِ‌حساب --
    با دابل‌کلیک رویِ هر ردیف، خلاصهٔ همان سندِ انبار نمایش داده می‌شود."""

    def __init__(self, parent: QWidget, company_id: int, item_id: int, counterparty_id: int, item_label: str) -> None:
        super().__init__(parent)
        self._company_id = company_id
        self.setWindowTitle(f"بهایِ قبلیِ «{item_label}»")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)

        self._rows = engine_service.list_item_cost_history(company_id, item_id, counterparty_id)
        if not self._rows:
            layout.addWidget(QLabel("برایِ این کالا و این طرفِ‌حساب هنوز سابقه‌یِ بهایی ثبت نشده است."))

        self.table = QTableWidget(0, len(_COST_HISTORY_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COST_HISTORY_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.cellDoubleClicked.connect(self._show_summary)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(QLabel("برایِ دیدنِ خلاصهٔ سند، رویِ ردیفِ موردِنظر دابل‌کلیک کنید."))

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.table.setRowCount(len(self._rows))
        for row_index, row in enumerate(self._rows):
            values = [
                DOC_TYPE_TITLES.get(row.document_type_code, row.document_type_code),
                numerals.to_persian_digits(str(row.document_no)),
                numerals.format_jalali_date(row.document_date),
                numerals.format_amount(row.unit_cost),
            ]
            for col_index, value in enumerate(values):
                self.table.setItem(row_index, col_index, QTableWidgetItem(value))
        self.table.resizeRowsToContents()

    def _show_summary(self, row: int, _column: int) -> None:
        history_row = self._rows[row]
        doc, lines = documents_service.get_stock_document(history_row.stock_document_id, self._company_id)
        lines_text = "\n".join(
            f"— کالا #{ln.item_id}: {numerals.format_amount(ln.quantity)} × {numerals.format_amount(ln.unit_cost or 0)}"
            for ln in lines
        )
        QMessageBox.information(
            self, "خلاصهٔ سند",
            f"{DOC_TYPE_TITLES.get(doc.document_type_code, doc.document_type_code)} — شماره‌یِ {numerals.to_persian_digits(str(doc.document_no))}\n"
            f"تاریخ: {numerals.format_jalali_date(doc.document_date)}\n\n{lines_text}",
        )


class _LineDialog(QDialog):
    def __init__(
        self, parent: QWidget, document_type_code: str, items: list[catalog_service.ItemRow],
        source_bins: list[locations_service.BinLocationRow], destination_bins: list[locations_service.BinLocationRow],
        reasons: list[documents_service.ReasonCodeRow], initial: documents_service.LineFields | None = None,
        uom_decimal_places: dict[int, int] | None = None, unit_cost_decimal_places: int = 2,
        main_window=None, counterparty_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.document_type_code = document_type_code
        self._uom_decimal_places = uom_decimal_places or {}
        self._main_window = main_window
        self._counterparty_id = counterparty_id
        self.setWindowTitle("ردیفِ سند")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("کالا"))
        item_row = QHBoxLayout()
        item_row.setContentsMargins(0, 0, 0, 0)
        item_row.setSpacing(3)
        item_options = [(it.item_id, f"{it.code} — {it.name or ''}") for it in items]
        self.item_combo = _make_searchable_combo(item_options)
        item_row.addWidget(self.item_combo, stretch=1)
        add_quick_add_button(item_row, self.item_combo, main_window, "GL_DIM", "تعریفِ کالایِ تازه")
        layout.addLayout(item_row)
        self._items_by_id = {it.item_id: it for it in items}

        stock_row = QHBoxLayout()
        stock_row.setContentsMargins(0, 0, 0, 0)
        self.stock_info_label = QLabel("")
        self.stock_info_label.setWordWrap(True)
        stock_row.addWidget(self.stock_info_label, stretch=1)
        self.kardex_button = QPushButton("📇 کاردکس")
        self.kardex_button.setObjectName("flatButton")
        self.kardex_button.setEnabled(False)
        self.kardex_button.clicked.connect(self._open_kardex)
        stock_row.addWidget(self.kardex_button)
        self.price_history_button = QPushButton("🕘 قیمت‌هایِ قبلی")
        self.price_history_button.setObjectName("flatButton")
        self.price_history_button.setEnabled(False)
        self.price_history_button.setToolTip("۱۰ بهایِ آخرِ این کالا از همین طرفِ‌حساب")
        self.price_history_button.clicked.connect(self._open_price_history)
        stock_row.addWidget(self.price_history_button)
        layout.addLayout(stock_row)

        layout.addWidget(QLabel("مقدار (واحدِ پایهٔ کالا)"))
        # طبقِ سندِ راهنمایِ UI/UX (بخشِ ۶.۲/۶.۳): _AmountField به‌جایِ
        # QDoubleSpinBoxِ خام — گروه‌بندیِ سه‌رقمیِ زنده + ارقامِ فارسی حینِ
        # تایپ، دقیقاً هم‌الگو با journal_entry.py/treasury_voucher.py.
        self.quantity_field = _AmountField()
        self.quantity_field.setDecimals(6)
        layout.addWidget(self.quantity_field)
        self.item_combo.currentIndexChanged.connect(self._on_item_changed)

        self.bin_row = QWidget()
        bin_layout = QVBoxLayout(self.bin_row)
        bin_layout.setContentsMargins(0, 0, 0, 0)
        bin_layout.addWidget(QLabel("مکان"))
        self.bin_combo = _EnterComboBox()
        self.bin_combo.addItem("(پیش‌فرضِ انبار)", None)
        for b in source_bins:
            self.bin_combo.addItem(f"{b.code} — {b.name or ''}", b.bin_location_id)
        bin_layout.addWidget(self.bin_combo)
        layout.addWidget(self.bin_row)

        self.destination_bin_row = QWidget()
        dest_bin_layout = QVBoxLayout(self.destination_bin_row)
        dest_bin_layout.setContentsMargins(0, 0, 0, 0)
        dest_bin_layout.addWidget(QLabel("مکانِ مقصد"))
        self.destination_bin_combo = _EnterComboBox()
        self.destination_bin_combo.addItem("(پیش‌فرضِ انبار)", None)
        for b in destination_bins:
            self.destination_bin_combo.addItem(f"{b.code} — {b.name or ''}", b.bin_location_id)
        dest_bin_layout.addWidget(self.destination_bin_combo)
        layout.addWidget(self.destination_bin_row)
        self.destination_bin_row.setVisible(document_type_code == "TRANSFER")

        self.unit_cost_row = QWidget()
        cost_layout = QVBoxLayout(self.unit_cost_row)
        cost_layout.setContentsMargins(0, 0, 0, 0)
        cost_layout.addWidget(QLabel("بهایِ واحد (اختیاری)"))
        self.unit_cost_field = _AmountField()
        self.unit_cost_field.setDecimals(unit_cost_decimal_places)
        cost_layout.addWidget(self.unit_cost_field)
        layout.addWidget(self.unit_cost_row)
        self.unit_cost_row.setVisible(document_type_code in ("RECEIPT", "RETURN_IN", "ADJUSTMENT"))

        self.reason_row = QWidget()
        reason_layout = QVBoxLayout(self.reason_row)
        reason_layout.setContentsMargins(0, 0, 0, 0)
        reason_layout.addWidget(QLabel("دلیل"))
        self.reason_combo = _EnterComboBox()
        self.reason_combo.addItem("(انتخاب کنید)", None)
        for r in reasons:
            self.reason_combo.addItem(r.name, r.reason_code_id)
        reason_layout.addWidget(self.reason_combo)
        layout.addWidget(self.reason_row)
        self.reason_row.setVisible(document_type_code in ("ADJUSTMENT", "RETURN_IN", "RETURN_OUT"))

        layout.addWidget(QLabel("توضیح"))
        self.description_field = QLineEdit()
        layout.addWidget(self.description_field)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        # طبقِ الگویِ ثابت‌شده در treasury_voucher.py (رفعِ RcptBug3-1):
        # وقتی autoDefault فعال باشد، همان اولین Enterِ زده‌شده در *هر*
        # فیلدی زودتر از زنجیره‌یِ صریحِ زیر به این دکمه می‌رسد و دیالوگ را
        # زودهنگام می‌بندد.
        buttons.button(QDialogButtonBox.Ok).setAutoDefault(False)
        buttons.button(QDialogButtonBox.Cancel).setAutoDefault(False)
        layout.addWidget(buttons)
        # طبقِ رفعِ باگِ واقعیِ کشف‌شده با تستِ زنده (QTest): برخلافِ آنچه
        # کامنتِ بالا فرض کرده بود، همان setAutoDefault(False) به‌تنهایی
        # کافی نبود — QDialogButtonBox با هر show() دوباره دکمه‌یِ
        # AcceptRole را default (isDefault=True) می‌کند؛ نتیجه این بود که
        # هر Enterِ زده‌شده در هر فیلدی، حتی بعدِ جابه‌جاکردنِ فوکوسِ درست
        # توسطِ enter_chain زیر، بلافاصله خودِ دیالوگ را می‌بست (زنجیره‌یِ
        # Enter عملاً هیچ‌وقت به فیلدِ دوم نمی‌رسید). جلوگیریِ واقعی، هم‌الگو
        # با treasury_voucher._MethodDetailsDialog، در keyPressEventِ
        # پایین‌ترِ همین کلاس انجام شده.

        # طبقِ درخواستِ صریح («ادامهٔ ثبتِ رسید»): زنجیره‌یِ Enter از کالا
        # تا توضیح، و در پایان معادلِ کلیکِ روی «تایید» — تا کاربر بتواند
        # ردیف‌ها را پشتِ‌سرِهم فقط با کیبورد وارد کند.
        enter_chain: list[QWidget] = [self.item_combo, self.quantity_field, self.bin_combo]
        if self.destination_bin_row.isVisibleTo(self):
            enter_chain.append(self.destination_bin_combo)
        if self.unit_cost_row.isVisibleTo(self):
            enter_chain.append(self.unit_cost_field)
        if self.reason_row.isVisibleTo(self):
            enter_chain.append(self.reason_combo)
        enter_chain.append(self.description_field)

        for widget, next_widget in zip(enter_chain, enter_chain[1:]):
            _enter_signal(widget).connect(next_widget.setFocus)
        _enter_signal(enter_chain[-1]).connect(self._on_accept)

        self.item_combo.setFocus()
        self._on_item_changed()

        if initial is not None:
            index = self.item_combo.findData(initial.item_id)
            if index >= 0:
                self.item_combo.setCurrentIndex(index)
            self.quantity_field.setValue(float(initial.quantity))
            if initial.bin_location_id is not None:
                self.bin_combo.setCurrentIndex(max(0, self.bin_combo.findData(initial.bin_location_id)))
            if initial.destination_bin_location_id is not None:
                self.destination_bin_combo.setCurrentIndex(max(0, self.destination_bin_combo.findData(initial.destination_bin_location_id)))
            if initial.unit_cost is not None:
                self.unit_cost_field.setValue(float(initial.unit_cost))
            if initial.reason_code_id is not None:
                self.reason_combo.setCurrentIndex(max(0, self.reason_combo.findData(initial.reason_code_id)))
            self.description_field.setText(initial.description or "")

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
        # طبقِ گزارشِ صریح: تعدادِ اعشارِ «مقدار» باید از تعریفِ واحدِ
        # پایهٔ همان کالا ارث ببرد (مثلاً واحدِ شمارشی «عدد» = عددِ صحیح)،
        # نه همیشه ۶ رقمِ ثابتِ اعشار.
        item = self._items_by_id.get(self.item_combo.currentData())
        decimals = self._uom_decimal_places.get(item.base_uom_id, 2) if item else 6
        self.quantity_field.setDecimals(decimals)
        self._refresh_stock_info()

    def _refresh_stock_info(self) -> None:
        item_id = self.item_combo.currentData()
        company_id = app_session.current_company.company_id if app_session.current_company else None
        if item_id is None or company_id is None:
            self.stock_info_label.setText("")
            self.kardex_button.setEnabled(False)
            self.price_history_button.setEnabled(False)
            return
        rows = engine_service.get_item_stock_by_warehouse(company_id, item_id)
        nonzero = [r for r in rows if r.quantity_on_hand]
        if not nonzero:
            self.stock_info_label.setText("موجودی: صفر")
        else:
            total = sum((r.quantity_on_hand for r in nonzero), decimal.Decimal(0))
            per_warehouse = " | ".join(f"{r.warehouse_name}: {numerals.format_amount(r.quantity_on_hand)}" for r in nonzero)
            self.stock_info_label.setText(f"موجودیِ کل: {numerals.format_amount(total)} ({per_warehouse})")
        self.kardex_button.setEnabled(True)
        self.price_history_button.setEnabled(self._counterparty_id is not None)

    def _open_kardex(self) -> None:
        item_id = self.item_combo.currentData()
        if item_id is None or self._main_window is None:
            return
        self._main_window.open_screen("REPORTS_ITEM_LEDGER", then=lambda screen: screen.show_ledger_for_item(item_id))

    def _open_price_history(self) -> None:
        item_id = self.item_combo.currentData()
        company_id = app_session.current_company.company_id if app_session.current_company else None
        if item_id is None or company_id is None or self._counterparty_id is None:
            return
        item = self._items_by_id.get(item_id)
        item_label = f"{item.code} — {item.name or ''}" if item else str(item_id)
        dialog = _ItemCostHistoryDialog(self, company_id, item_id, self._counterparty_id, item_label)
        dialog.exec()

    def _on_accept(self) -> None:
        if self.item_combo.currentData() is None:
            self.status_label.setText("کالا را انتخاب کنید.")
            return
        if self.reason_row.isVisibleTo(self) and self.reason_combo.currentData() is None:
            self.status_label.setText("انتخابِ دلیل الزامی است.")
            return
        self.accept()

    def result_fields(self) -> documents_service.LineFields:
        # طبقِ رفعِ باگِ واقعیِ کشف‌شده: این تابع همیشه *بعدِ* بستنِ دیالوگ
        # (دیگر self.exec() برگشته) صدا زده می‌شود — یعنی خودِ دیالوگ دیگر
        # isVisible() نیست، پس widget.isVisible() برایِ هر ردیف/فیلدِ
        # داخلش هم همیشه False برمی‌گشت (چون isVisible وابسته به نمایانیِ
        # واقعیِ رویِ صفحه است، نه صرفاً تنظیم‌شدنِ صریحِ setVisible). نتیجه
        # این بود که دلیل/بهایِ واحد/مکانِ مقصد — حتی وقتی واقعاً پر شده
        # بودند — همیشه None ثبت می‌شدند، و بعداً هنگامِ تاییدِ سند دوباره
        # با «انتخابِ دلیل الزامی است» رد می‌شد. isVisibleTo(self) وضعیتِ
        # واقعیِ تنظیم‌شده (مستقل از نمایانیِ خودِ دیالوگ) را می‌دهد.
        item_id = self.item_combo.currentData()
        item = self._items_by_id.get(item_id)
        quantity = decimal.Decimal(str(self.quantity_field.value()))
        unit_cost = (
            decimal.Decimal(str(self.unit_cost_field.value()))
            if self.unit_cost_row.isVisibleTo(self) and self.unit_cost_field.value() > 0
            else None
        )
        return documents_service.LineFields(
            item_id=item_id, uom_id=item.base_uom_id if item else 0, quantity=quantity, quantity_base=quantity,
            bin_location_id=self.bin_combo.currentData(),
            destination_bin_location_id=(
                self.destination_bin_combo.currentData() if self.destination_bin_row.isVisibleTo(self) else None
            ),
            unit_cost=unit_cost,
            reason_code_id=self.reason_combo.currentData() if self.reason_row.isVisibleTo(self) else None,
            description=self.description_field.text().strip() or None,
        )


class InventoryDocumentScreen(FieldHelpMixin, FormScreenBase):
    def __init__(self, document_type_code: str, main_window) -> None:
        super().__init__()
        self.document_type_code = document_type_code
        self._main_window = main_window
        self._document_id: int | None = None
        self._status_code = "DRAFT"
        self._lines: list[documents_service.StockDocumentLineRow] = []
        self._items: list[catalog_service.ItemRow] = []
        self._warehouses: list[locations_service.WarehouseRow] = []
        self._uom_decimal_places: dict[int, int] = {}
        self._unit_cost_decimal_places: int = 2
        self._cost_center_required = False
        self._project_required = False

        title = DOC_TYPE_TITLES[document_type_code]
        title_row = QHBoxLayout()
        self.page_title = QLabel(f"سندِ {title}")
        self.page_title.setObjectName("pageTitle")
        title_row.addWidget(self.page_title)
        self.status_badge = QLabel("")
        self.status_badge.setObjectName("statusBadge")
        title_row.addWidget(self.status_badge)
        title_row.addStretch(1)
        self.body_layout.addLayout(title_row)

        self.step_stepper = SectionStepper(["اطلاعاتِ سند", "ردیف‌ها"])
        self.body_layout.addWidget(self.step_stepper)

        # طبقِ درخواستِ صریح: همه‌یِ فیلدهایِ هدر در یک ردیفِ واحد و فشرده —
        # تاریخ/انبار(ها)/جهت هرکدام فقط به‌اندازه‌یِ متنِ خودشان (نه بیشتر)
        # جا می‌گیرند، طرفِ‌حساب نصفِ حالتِ قبل، و بقیه‌یِ عرض خالی می‌ماند
        # (نه صرفِ کشیده‌شدنِ فیلدها) — این تابعِ کمکی همان الگویِ
        # «حداکثرعرضِ ثابت + stretchِ انتهایی» را برایِ هر فیلد اعمال می‌کند.
        def _compact_box(widget: QWidget, max_width: int) -> None:
            widget.setMaximumWidth(max_width)

        def _growable_box(widget: QWidget, min_width: int) -> None:
            # طبقِ درخواستِ صریح: این فیلدها به‌جایِ عرضِ ثابتِ کوچک،
            # فضایِ خالیِ باقی‌ماندهٔ ردیفِ هدر را (به‌جایِ stretchِ انتهاییِ
            # بلااستفاده) بینِ خودشان تقسیم کنند.
            widget.setMinimumWidth(min_width)

        # طبقِ گزارشِ تکراریِ کاربر («هدرِ فرم‌هایِ انبار/فروش/خرید هنوز
        # نامرتب است»): این هدر هم اکنون درونِ یک کارتِ واحد قرار می‌گیرد —
        # هم‌الگو با journal_entry.py/treasury_voucher.py — به‌جایِ نشستنِ
        # مستقیمِ QHBoxLayout رویِ بدنه‌یِ صفحه.
        header_card = QWidget()
        header_card.setObjectName("card")
        header_card_layout = QVBoxLayout(header_card)
        header_card_layout.setContentsMargins(8, 5, 8, 5)
        header_card_layout.setSpacing(2)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)
        header_card_layout.addLayout(header_row)
        date_box = QVBoxLayout()
        date_box.addWidget(QLabel("تاریخ"))
        self.date_field = JalaliDateEdit()
        date_box.addWidget(self.date_field)
        header_row.addLayout(date_box, 0)

        self.source_wh_box = QWidget()
        _growable_box(self.source_wh_box, 150)
        source_wh_layout = QVBoxLayout(self.source_wh_box)
        source_wh_layout.setContentsMargins(0, 0, 0, 0)
        source_wh_layout.addWidget(QLabel("انبارِ مبدا"))
        source_wh_row = QHBoxLayout()
        source_wh_row.setContentsMargins(0, 0, 0, 0)
        source_wh_row.setSpacing(3)
        self.source_wh_combo = _EnterComboBox()
        self.source_wh_combo.currentIndexChanged.connect(self._on_warehouse_changed)
        source_wh_row.addWidget(self.source_wh_combo, stretch=1)
        add_quick_add_button(source_wh_row, self.source_wh_combo, main_window, "INV_WAREHOUSES", "تعریفِ انبارِ تازه")
        source_wh_layout.addLayout(source_wh_row)
        header_row.addWidget(self.source_wh_box, 1)

        self.destination_wh_box = QWidget()
        _growable_box(self.destination_wh_box, 150)
        dest_wh_layout = QVBoxLayout(self.destination_wh_box)
        dest_wh_layout.setContentsMargins(0, 0, 0, 0)
        dest_wh_layout.addWidget(QLabel("انبارِ مقصد"))
        dest_wh_row = QHBoxLayout()
        dest_wh_row.setContentsMargins(0, 0, 0, 0)
        dest_wh_row.setSpacing(3)
        self.destination_wh_combo = _EnterComboBox()
        self.destination_wh_combo.currentIndexChanged.connect(self._on_warehouse_changed)
        dest_wh_row.addWidget(self.destination_wh_combo, stretch=1)
        add_quick_add_button(dest_wh_row, self.destination_wh_combo, main_window, "INV_WAREHOUSES", "تعریفِ انبارِ تازه")
        dest_wh_layout.addLayout(dest_wh_row)
        header_row.addWidget(self.destination_wh_box, 1)

        self.adjustment_direction_box = QWidget()
        _compact_box(self.adjustment_direction_box, 180)
        adj_dir_layout = QVBoxLayout(self.adjustment_direction_box)
        adj_dir_layout.setContentsMargins(0, 0, 0, 0)
        adj_dir_layout.addWidget(QLabel("جهت"))
        self.adjustment_direction_combo = _EnterComboBox()
        self.adjustment_direction_combo.addItem("مازاد (افزایش)", "IN")
        self.adjustment_direction_combo.addItem("کسری (کاهش)", "OUT")
        self.adjustment_direction_combo.currentIndexChanged.connect(self._on_warehouse_changed)
        adj_dir_layout.addWidget(self.adjustment_direction_combo)
        header_row.addWidget(self.adjustment_direction_box, 0)

        self.counterparty_box = QWidget()
        _growable_box(self.counterparty_box, 220)
        counterparty_layout = QVBoxLayout(self.counterparty_box)
        counterparty_layout.setContentsMargins(0, 0, 0, 0)
        self.counterparty_label = QLabel("طرفِ‌حساب")
        counterparty_layout.addWidget(self.counterparty_label)
        counterparty_row = QHBoxLayout()
        counterparty_row.setContentsMargins(0, 0, 0, 0)
        counterparty_row.setSpacing(3)
        self.counterparty_combo = _make_searchable_combo([])
        counterparty_row.addWidget(self.counterparty_combo, stretch=1)
        add_quick_add_button(counterparty_row, self.counterparty_combo, main_window, "GL_DIM", "تعریفِ طرفِ‌حسابِ تازه")
        counterparty_layout.addLayout(counterparty_row)
        header_row.addWidget(self.counterparty_box, 1)

        reference_box = QVBoxLayout()
        reference_box.addWidget(QLabel("شمارهٔ مرجع"))
        self.reference_field = QLineEdit()
        self.reference_field.setMaximumWidth(160)
        reference_box.addWidget(self.reference_field)
        header_row.addLayout(reference_box, 0)

        # طبقِ گزارشِ صریح («در فرمِ رسیدِ اصلاح جایی برایِ ورودِ مرکزِ
        # هزینه نیست، اگر معینِ نقش‌محورِ سند آن را الزامی کرده باشد، مثلِ
        # فرم‌هایِ فروش/خرید نیست»): همان الگویِ commercial_document.py —
        # مرکزِ هزینه/پروژه فیلدهایِ همیشه‌حاضرِ هدرِ همه‌یِ اسنادِ انبارند
        # (backendِ inventory_engine.post_stock_document از قبل، طبقِ
        # R8-2، همین دو مقدار را از سرِسند می‌خواند)؛ فقط بر اساسِ نگاشتِ
        # حساب‌هایِ نقش‌محورِ همین نوعِ سند enable/الزامی می‌شوند. هم‌الگو
        # با هدرِ ۲‌ردیفه‌یِ commercial_document.py (R11)، در ردیفِ دومِ
        # همین کارت جا می‌گیرند — نه در ردیفِ اولِ همین‌الان شلوغ.
        header_row2 = QHBoxLayout()
        header_row2.setContentsMargins(0, 0, 0, 0)
        header_row2.setSpacing(6)

        self.cost_center_box = QWidget()
        _growable_box(self.cost_center_box, 200)
        cost_center_layout = QVBoxLayout(self.cost_center_box)
        cost_center_layout.setContentsMargins(0, 0, 0, 0)
        self.cost_center_label = QLabel("مرکزِ هزینه")
        cost_center_layout.addWidget(self.cost_center_label)
        cost_center_row = QHBoxLayout()
        cost_center_row.setContentsMargins(0, 0, 0, 0)
        cost_center_row.setSpacing(3)
        self.cost_center_combo = _EnterComboBox()
        cost_center_row.addWidget(self.cost_center_combo, stretch=1)
        add_quick_add_button(cost_center_row, self.cost_center_combo, main_window, "GL_DIM", "تعریفِ مرکزِ هزینه‌یِ تازه")
        cost_center_layout.addLayout(cost_center_row)
        header_row2.addWidget(self.cost_center_box, 1)

        self.project_box = QWidget()
        _growable_box(self.project_box, 200)
        project_layout = QVBoxLayout(self.project_box)
        project_layout.setContentsMargins(0, 0, 0, 0)
        self.project_label = QLabel("پروژه")
        project_layout.addWidget(self.project_label)
        project_row = QHBoxLayout()
        project_row.setContentsMargins(0, 0, 0, 0)
        project_row.setSpacing(3)
        self.project_combo = _EnterComboBox()
        project_row.addWidget(self.project_combo, stretch=1)
        add_quick_add_button(project_row, self.project_combo, main_window, "GL_DIM", "تعریفِ پروژه‌یِ تازه")
        project_layout.addLayout(project_row)
        header_row2.addWidget(self.project_box, 1)
        header_row2.addStretch(1)

        header_card_layout.addLayout(header_row2)
        self.body_layout.addWidget(header_card)

        # طبقِ رفعِ باگِ واقعی («هدر هنوز فضایِ زیادی اشغال کرده»): عنوانِ
        # بخشِ «ردیف‌ها» و دکمهٔ افزودن قبلاً دو ردیفِ کاملِ جدا بودند،
        # بدونِ نیازِ واقعی — حالا کنارِ هم، یک ردیف.
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
        # نوشته‌هاست»): این فوتر ۵ دکمه‌یِ متنیِ کنارِ هم داشت — دقیقاً
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
        self.confirm_button.setToolTip("۲) تاییدِ سند — پیش از ثبتِ نهایی؛ اگر لازم بود می‌توان به پیش‌نویس برگرداند")
        self.confirm_button.clicked.connect(self._confirm)
        self.footer_layout.addWidget(self.confirm_button)

        self.revert_button = QPushButton("↩️")
        self.revert_button.setObjectName("iconButton")
        self.revert_button.setFixedWidth(44)
        self.revert_button.setToolTip("بازگشت به پیش‌نویس — سندِ تاییدشده دوباره قابلِ‌ویرایش می‌شود")
        self.revert_button.clicked.connect(self._revert_to_draft)
        self.footer_layout.addWidget(self.revert_button)

        self.post_button = QPushButton("🔒")
        self.post_button.setObjectName("primaryIconButton")
        self.post_button.setFixedWidth(48)
        self.post_button.setToolTip("۳) ثبتِ نهایی — قطعی و برگشت‌ناپذیر؛ سندِ حسابداریِ واقعی همین‌جا ساخته می‌شود")
        self.post_button.clicked.connect(self._post)
        self.footer_layout.addWidget(self.post_button)

        self.cancel_button = QPushButton("🚫")
        self.cancel_button.setObjectName("dangerIconButton")
        self.cancel_button.setFixedWidth(44)
        self.cancel_button.setToolTip("لغوِ سند — سند باطل می‌شود (فقط پیش از ثبتِ نهایی ممکن است)")
        self.cancel_button.clicked.connect(self._cancel)
        self.footer_layout.addWidget(self.cancel_button)

        # طبقِ درخواستِ صریح: توضیحِ سند به‌جایِ اشغالِ یک ردیفِ کاملِ هدر،
        # کنارِ دکمه‌ها در همین فوترِ ثابت جا می‌گیرد — دکمه‌ها هنوز کنارِ
        # هم و سمتِ چپ می‌مانند، توضیح باقیِ فضایِ فوتر را پر می‌کند.
        description_label = QLabel("شرح:")
        self.footer_layout.addWidget(description_label)
        self.description_field = QLineEdit()
        self.footer_layout.addWidget(self.description_field, 1)

        self._apply_type_visibility()
        self.set_field_help([
            (self.date_field, "تاریخِ سند — پایهٔ تعیینِ سالِ مالی و ترتیبِ حرکاتِ موجودی."),
            (self.reference_field, "مثلاً شمارهٔ فاکتورِ خرید یا سندِ اصلیِ برگشت."),
        ])

    def _apply_type_visibility(self) -> None:
        t = self.document_type_code
        if t == "ADJUSTMENT":
            # طبقِ تصمیمِ طراحی: به‌جایِ ستِ هم‌زمانِ مبدا و مقصد (که یک
            # موتورِ ADJUSTMENT را وادار به IN+OUTِ هم‌زمانِ روی همان ردیف
            # می‌کند)، این‌جا فقط یک انبار + یک «جهت» گرفته می‌شود.
            self.source_wh_box.setVisible(True)
            self.destination_wh_box.setVisible(False)
        else:
            req = documents_service.WAREHOUSE_REQUIREMENTS[t]
            self.source_wh_box.setVisible(req["source"])
            self.destination_wh_box.setVisible(req["destination"])
        self.adjustment_direction_box.setVisible(t == "ADJUSTMENT")
        self.counterparty_box.setVisible(t in ("RECEIPT", "ISSUE", "RETURN_IN", "RETURN_OUT"))
        if t == "RECEIPT":
            self.counterparty_label.setText("طرفِ‌حساب (تامین‌کننده)")
        elif t == "RETURN_OUT":
            self.counterparty_label.setText("طرفِ‌حساب (تامین‌کننده) — الزامی")
        elif t == "RETURN_IN":
            self.counterparty_label.setText("طرفِ‌حساب (مشتری) — الزامی")
        elif t == "ISSUE":
            self.counterparty_label.setText("طرفِ‌حساب (مشتری)")
        self._wire_header_enter_chain()

    def _wire_header_enter_chain(self) -> None:
        """طبقِ درخواستِ صریح («مثلِ فرمِ دریافت»): زنجیره‌یِ Enter از
        تاریخ تا آخرین فیلدِ هدر، و در پایان به بازکردنِ دیالوگِ افزودنِ
        ردیف می‌رسد — دقیقاً هم‌الگو با treasury_voucher.py. چون
        visibilityِ فیلدهایِ هدر فقط یک‌بار (برایِ نوعِ سندِ ثابتِ همین
        نمونه) در _apply_type_visibility تعیین می‌شود، این‌جا هم فقط
        همان یک‌بار زنجیره ساخته می‌شود — نه در هر refresh."""
        # طبقِ باگِ واقعیِ کشف‌شده: این تابع در __init__ (پیش از نمایشِ
        # واقعیِ صفحه) صدا زده می‌شود، جایی که isVisible() همیشه False
        # برمی‌گرداند (چون کلِ زنجیره‌یِ اجداد هنوز show نشده) — حتی برایِ
        # فیلدهایی که setVisible(True) رویشان صدا زده شده. isVisibleTo(self)
        # وضعیتِ واقعیِ تنظیم‌شده را مستقل از نمایانیِ خودِ صفحه برمی‌گرداند.
        chain: list[QWidget] = [self.date_field]
        if self.source_wh_box.isVisibleTo(self):
            chain.append(self.source_wh_combo)
        if self.destination_wh_box.isVisibleTo(self):
            chain.append(self.destination_wh_combo)
        if self.adjustment_direction_box.isVisibleTo(self):
            chain.append(self.adjustment_direction_combo)
        if self.counterparty_box.isVisibleTo(self):
            chain.append(self.counterparty_combo)
        chain.append(self.reference_field)
        chain.append(self.cost_center_combo)
        chain.append(self.project_combo)

        for widget, next_widget in zip(chain, chain[1:]):
            _enter_signal(widget).connect(next_widget.setFocus)
        _enter_signal(chain[-1]).connect(self._add_line)

    def _on_warehouse_changed(self) -> None:
        # طبقِ گزارشِ صریح: عوضِ‌شدنِ انبار ردیف‌هایِ ثبت‌شده را بی‌معنا
        # می‌کند — فقط برایِ سندِ پیش‌نویسِ هنوز بدونِ ردیف مجاز است.
        pass

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def _current_warehouse_ids(self) -> tuple[int | None, int | None]:
        t = self.document_type_code
        if t == "ADJUSTMENT":
            warehouse_id = self.source_wh_combo.currentData()
            if self.adjustment_direction_combo.currentData() == "OUT":
                return warehouse_id, None
            return None, warehouse_id
        return self.source_wh_combo.currentData(), self.destination_wh_combo.currentData()

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._items = catalog_service.list_items(company_id, active_only=True)
        self._warehouses = locations_service.list_warehouses(company_id, active_only=True)
        self._uom_decimal_places = {u.uom_id: u.decimal_places for u in catalog_service.list_uoms(company_id)}
        self._unit_cost_decimal_places = companies_service.get_base_currency_decimal_places(company_id)

        for combo in (self.source_wh_combo, self.destination_wh_combo):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("(انتخاب کنید)", None)
            for w in self._warehouses:
                combo.addItem(f"{w.code} — {w.name}", w.warehouse_id)
            if current is not None:
                combo.setCurrentIndex(max(0, combo.findData(current)))
            combo.blockSignals(False)

        counterparty_options: list[tuple[int, str]] = []
        if self.document_type_code in ("RECEIPT", "RETURN_OUT"):
            counterparty_options = [(c["detail_account_id"], f"{c['code']} — {c['name'] or ''}") for c in dimensions_service.list_suppliers(company_id)]
        elif self.document_type_code in ("ISSUE", "RETURN_IN"):
            counterparty_options = [(c["detail_account_id"], f"{c['code']} — {c['name'] or ''}") for c in dimensions_service.list_customers(company_id)]
        current_counterparty = self.counterparty_combo.currentData()
        _fill_options(self.counterparty_combo, counterparty_options)
        if current_counterparty is not None:
            index = self.counterparty_combo.findData(current_counterparty)
            if index >= 0:
                self.counterparty_combo.setCurrentIndex(index)

        self._cost_center_required, cost_center_options = documents_service.get_header_dimension_requirement(
            company_id, self.document_type_code, dimensions_service.COST_CENTER_CODE
        )
        current_cc = self.cost_center_combo.currentData()
        self.cost_center_combo.clear()
        self.cost_center_combo.addItem("(بدونِ مرکزِ هزینه)", None)
        for opt in cost_center_options:
            self.cost_center_combo.addItem(f"{opt.code} — {opt.name or ''}", opt.detail_account_id)
        if current_cc is not None:
            index = self.cost_center_combo.findData(current_cc)
            if index >= 0:
                self.cost_center_combo.setCurrentIndex(index)
        self.cost_center_label.setText("مرکزِ هزینه *" if self._cost_center_required else "مرکزِ هزینه")

        self._project_required, project_options = documents_service.get_header_dimension_requirement(
            company_id, self.document_type_code, dimensions_service.PROJECT_CODE
        )
        current_project = self.project_combo.currentData()
        self.project_combo.clear()
        self.project_combo.addItem("(بدونِ پروژه)", None)
        for opt in project_options:
            self.project_combo.addItem(f"{opt.code} — {opt.name or ''}", opt.detail_account_id)
        if current_project is not None:
            index = self.project_combo.findData(current_project)
            if index >= 0:
                self.project_combo.setCurrentIndex(index)
        self.project_label.setText("پروژه *" if self._project_required else "پروژه")

        if self._document_id is not None:
            self._load_document()
        else:
            self._reset_form(clear_only=True)

        # طبقِ درخواستِ صریح: هر بار این صفحه باز می‌شود، فوکوس مستقیم
        # رویِ تاریخ می‌رود — هم‌الگو با فرمِ دریافت/سندِ حسابداری — تا
        # زنجیره‌یِ Enterِ هدر بتواند بدونِ کلیکِ اضافه شروع شود.
        self.date_field.setFocus()
        self.date_field.selectAll()

    def _load_document(self) -> None:
        company_id = self._company_id()
        try:
            doc, lines = documents_service.get_stock_document(self._document_id, company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._status_code = doc.status_code
        self.page_title.setText(f"سندِ {DOC_TYPE_TITLES[self.document_type_code]} #{doc.document_no}")
        self.date_field.setDate(doc.document_date)
        if self.document_type_code == "ADJUSTMENT":
            if doc.source_warehouse_id is not None:
                self.source_wh_combo.setCurrentIndex(max(0, self.source_wh_combo.findData(doc.source_warehouse_id)))
                self.adjustment_direction_combo.setCurrentIndex(self.adjustment_direction_combo.findData("OUT"))
            else:
                self.source_wh_combo.setCurrentIndex(max(0, self.source_wh_combo.findData(doc.destination_warehouse_id)))
                self.adjustment_direction_combo.setCurrentIndex(self.adjustment_direction_combo.findData("IN"))
        else:
            if doc.source_warehouse_id is not None:
                self.source_wh_combo.setCurrentIndex(max(0, self.source_wh_combo.findData(doc.source_warehouse_id)))
            if doc.destination_warehouse_id is not None:
                self.destination_wh_combo.setCurrentIndex(max(0, self.destination_wh_combo.findData(doc.destination_warehouse_id)))
        if doc.counterparty_detail_account_id is not None:
            index = self.counterparty_combo.findData(doc.counterparty_detail_account_id)
            if index >= 0:
                self.counterparty_combo.setCurrentIndex(index)
        if doc.cost_center_detail_account_id is not None:
            self.cost_center_combo.setCurrentIndex(max(0, self.cost_center_combo.findData(doc.cost_center_detail_account_id)))
        if doc.project_detail_account_id is not None:
            self.project_combo.setCurrentIndex(max(0, self.project_combo.findData(doc.project_detail_account_id)))
        self.reference_field.setText(doc.reference_no or "")
        self.description_field.setText(doc.description or "")
        self._lines = lines
        self._refresh_lines_table()
        self._apply_status_state()

    def _refresh_lines_table(self) -> None:
        items_by_id = {it.item_id: it for it in self._items}
        all_bins = {}
        for w in self._warehouses:
            for b in locations_service.list_bin_locations(w.warehouse_id):
                all_bins[b.bin_location_id] = b
        reasons_by_id: dict[int, str] = {}
        company_id = self._company_id()
        if company_id is not None:
            for applies_to in ("ADJUSTMENT", "RETURN_IN", "RETURN_OUT"):
                for r in documents_service.list_reason_codes(company_id, applies_to, active_only=False):
                    reasons_by_id[r.reason_code_id] = r.name

        self.lines_table.setRowCount(len(self._lines))
        for row_index, ln in enumerate(self._lines):
            item = items_by_id.get(ln.item_id)
            qty_decimals = self._uom_decimal_places.get(item.base_uom_id, 2) if item else 2
            values = [
                f"{item.code} — {item.name or ''}" if item else str(ln.item_id),
                numerals.format_money(ln.quantity, qty_decimals),
                all_bins.get(ln.bin_location_id).code if ln.bin_location_id in all_bins else "پیش‌فرض",
                all_bins.get(ln.destination_bin_location_id).code if ln.destination_bin_location_id in all_bins else "",
                numerals.format_money(ln.unit_cost, self._unit_cost_decimal_places) if ln.unit_cost is not None else "",
                numerals.format_money(ln.line_total_cost, self._unit_cost_decimal_places) if ln.line_total_cost is not None else "",
                reasons_by_id.get(ln.reason_code_id, ""),
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
        editable = is_draft and self._document_id is not None
        for widget in (self.date_field, self.source_wh_combo, self.destination_wh_combo, self.adjustment_direction_combo, self.counterparty_combo, self.cost_center_combo, self.project_combo, self.reference_field, self.description_field):
            widget.setEnabled(is_draft)
        self.save_button.setEnabled(is_draft)
        self.confirm_button.setEnabled(editable)
        self.revert_button.setEnabled(is_confirmed)
        self.post_button.setEnabled(is_confirmed)
        self.cancel_button.setEnabled(is_draft or is_confirmed)
        self.lines_table.setEnabled(True)

    def _reset_form(self, clear_only: bool = False) -> None:
        self._document_id = None
        self._status_code = "DRAFT"
        self._lines = []
        self.page_title.setText(f"سندِ {DOC_TYPE_TITLES[self.document_type_code]}ِ جدید")
        self.status_label.setText("")
        self.date_field.setDate(datetime.date.today())
        self.source_wh_combo.setCurrentIndex(0)
        self.destination_wh_combo.setCurrentIndex(0)
        self.adjustment_direction_combo.setCurrentIndex(0)
        self.counterparty_combo.setCurrentIndex(0)
        self.cost_center_combo.setCurrentIndex(0)
        self.project_combo.setCurrentIndex(0)
        self.reference_field.clear()
        self.description_field.clear()
        self._refresh_lines_table()
        self._apply_status_state()
        if not clear_only:
            self.refresh()

    def edit_document(self, stock_document_id: int) -> None:
        self._document_id = stock_document_id
        self.refresh()

    def _header_fields(self) -> documents_service.DocumentHeaderFields | None:
        source_wh, destination_wh = self._current_warehouse_ids()
        counterparty_id = self.counterparty_combo.currentData() if self.counterparty_box.isVisible() else None
        if self.document_type_code in ("RETURN_IN", "RETURN_OUT") and counterparty_id is None:
            self.status_label.setText("انتخابِ طرفِ‌حساب برایِ این نوعِ سند الزامی است.")
            return None
        # طبقِ رفعِ باگِ واقعی («در فرمِ رسیدِ اصلاح جایی برایِ ورودِ مرکزِ
        # هزینه نیست»): هم‌الگو با commercial_document.py — اگر حسابِ
        # نقش‌محورِ این نوعِ سند به مرکزِ هزینه/پروژه نیاز داشته باشد،
        # همین‌جا (پیش از تلاشِ ذخیره) با یک پیامِ روشن جلوگیری می‌شود.
        cost_center_id = self.cost_center_combo.currentData()
        if cost_center_id is None and self._cost_center_required:
            self.status_label.setText("انتخابِ «مرکزِ هزینه» برایِ این نوعِ سند الزامی است.")
            return None
        project_id = self.project_combo.currentData()
        if project_id is None and self._project_required:
            self.status_label.setText("انتخابِ «پروژه» برایِ این نوعِ سند الزامی است.")
            return None
        return documents_service.DocumentHeaderFields(
            source_warehouse_id=source_wh, destination_warehouse_id=destination_wh,
            counterparty_detail_account_id=counterparty_id,
            cost_center_detail_account_id=cost_center_id, project_detail_account_id=project_id,
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
                self._document_id = documents_service.create_stock_document(
                    company_id, app_session.current_user.user_id, self.document_type_code, self.date_field.date(), fields
                )
            else:
                documents_service.update_stock_document_header(self._document_id, company_id, self.date_field.date(), fields)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            QMessageBox.warning(self, "خطا در ذخیره", str(exc))
            return
        self._load_document()
        # طبقِ رفعِ باگِ واقعی («بعدِ ذخیره هیچ پیامی نمی‌دهد»): قبلاً این
        # مسیرِ موفقیت فقط status_label را خالی می‌کرد.
        theme.set_status_label(
            self.status_label, "سند به‌عنوانِ پیش‌نویس ذخیره شد." if is_new else "تغییراتِ سند ذخیره شد.", ok=True,
        )

    def _ensure_saved(self) -> bool:
        if self._document_id is None:
            self._save_header()
        return self._document_id is not None

    def _primary_line_warehouse_id(self, source_wh_id: int | None, destination_wh_id: int | None) -> int | None:
        """انبارِ مرجعِ ردیف — همان انباری که فهرستِ مکان‌هایِ «مکان» از
        رویِ آن پر می‌شود (برایِ TRANSFER همیشه مبدا؛ «مکانِ مقصد» از رویِ
        destination_wh_id جداگانه پر می‌شود)."""
        if self.document_type_code in ("RECEIPT", "RETURN_IN"):
            return destination_wh_id
        if self.document_type_code == "TRANSFER":
            return source_wh_id
        return source_wh_id if source_wh_id is not None else destination_wh_id

    def _add_line(self) -> None:
        if not self._ensure_saved():
            return
        source_wh_id, destination_wh_id = self._current_warehouse_ids()
        line_wh_id = self._primary_line_warehouse_id(source_wh_id, destination_wh_id)
        if line_wh_id is None:
            self.status_label.setText("ابتدا انبار را انتخاب کنید.")
            return
        source_bins = locations_service.list_bin_locations(line_wh_id, active_only=True)
        destination_bins = locations_service.list_bin_locations(destination_wh_id, active_only=True) if self.document_type_code == "TRANSFER" and destination_wh_id else []
        company_id = self._company_id()
        reasons: list[documents_service.ReasonCodeRow] = []
        if self.document_type_code in ("ADJUSTMENT", "RETURN_IN", "RETURN_OUT"):
            reasons = documents_service.list_reason_codes(company_id, self.document_type_code)
        # طبقِ درخواستِ صریح («ادامهٔ ثبتِ رسید»): بعدِ ثبتِ موفقِ هر ردیف،
        # بلافاصله دیالوگِ تازه‌ای برایِ ردیفِ بعدی باز می‌شود — تا کاربر
        # با زنجیره‌یِ Enterِ داخلِ دیالوگ بتواند پشتِ‌سرِهم ردیف واردکند،
        # بدونِ نیازِ به کلیکِ دوباره‌یِ «افزودنِ ردیف». فقط با لغوِ دیالوگ
        # (Escape/Cancel) این چرخه متوقف می‌شود.
        while True:
            dialog = _LineDialog(
                self, self.document_type_code, self._items, source_bins, destination_bins, reasons,
                uom_decimal_places=self._uom_decimal_places, unit_cost_decimal_places=self._unit_cost_decimal_places,
                main_window=self._main_window,
                counterparty_id=self.counterparty_combo.currentData() if self.counterparty_box.isVisible() else None,
            )
            if dialog.exec() != QDialog.Accepted:
                break
            try:
                documents_service.add_line(self._document_id, company_id, dialog.result_fields())
            except ValueError as exc:
                QMessageBox.warning(self, "خطا", str(exc))
                break
            self._load_document()

    def _selected_line(self) -> documents_service.StockDocumentLineRow | None:
        selected = self.lines_table.selectedItems()
        if not selected:
            return None
        line_id = selected[0].data(Qt.UserRole)
        return next((ln for ln in self._lines if ln.line_id == line_id), None)

    def _edit_line(self, *_args) -> None:
        line = self._selected_line()
        if line is None or self._document_id is None:
            return
        source_wh_id, destination_wh_id = self._current_warehouse_ids()
        line_wh_id = self._primary_line_warehouse_id(source_wh_id, destination_wh_id)
        source_bins = locations_service.list_bin_locations(line_wh_id, active_only=True) if line_wh_id else []
        destination_bins = locations_service.list_bin_locations(destination_wh_id, active_only=True) if self.document_type_code == "TRANSFER" and destination_wh_id else []
        company_id = self._company_id()
        reasons: list[documents_service.ReasonCodeRow] = []
        if self.document_type_code in ("ADJUSTMENT", "RETURN_IN", "RETURN_OUT"):
            reasons = documents_service.list_reason_codes(company_id, self.document_type_code)
        initial = documents_service.LineFields(
            item_id=line.item_id, uom_id=line.uom_id, quantity=line.quantity, quantity_base=line.quantity_base,
            bin_location_id=line.bin_location_id, destination_bin_location_id=line.destination_bin_location_id,
            unit_cost=line.unit_cost, reason_code_id=line.reason_code_id, description=line.description,
        )
        dialog = _LineDialog(
            self, self.document_type_code, self._items, source_bins, destination_bins, reasons, initial,
            uom_decimal_places=self._uom_decimal_places, unit_cost_decimal_places=self._unit_cost_decimal_places,
            main_window=self._main_window,
            counterparty_id=self.counterparty_combo.currentData() if self.counterparty_box.isVisible() else None,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            documents_service.update_line(line.line_id, self._document_id, company_id, dialog.result_fields())
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
            documents_service.confirm_stock_document(self._document_id, self._company_id())
        except ValueError as exc:
            # طبقِ رفعِ باگِ واقعی: قبلاً این خطا فقط در یک برچسبِ ساکت
            # نمایش داده می‌شد — کاربر به‌راحتی آن را نمی‌دید و فکر می‌کرد
            # هیچ اتفاقی نیفتاده. حالا هم‌الگو با خطاهایِ ردیف، یک
            # دیالوگِ مسدودکننده هم نمایش می‌دهد.
            self.status_label.setText(str(exc))
            QMessageBox.warning(self, "خطا در تاییدِ سند", str(exc))
            return
        self._load_document()
        theme.set_status_label(self.status_label, "سند تایید شد.", ok=True)

    def _revert_to_draft(self) -> None:
        if self._document_id is None:
            return
        try:
            documents_service.revert_to_draft(self._document_id, self._company_id())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            QMessageBox.warning(self, "خطا در بازگردانیِ سند به پیش‌نویس", str(exc))
            return
        self._load_document()
        theme.set_status_label(self.status_label, "سند به پیش‌نویس بازگشت.", ok=True)

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
            result = documents_service.post_stock_document(self._document_id, self._company_id(), app_session.current_user.user_id)
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
        self._reset_form()
        theme.set_status_label(self.status_label, f"سند ثبتِ نهایی شد.{je_note}", ok=True)

    def _cancel(self) -> None:
        if self._document_id is None:
            return
        confirm = QMessageBox.question(self, "لغوِ سند", "این سند لغو شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            documents_service.cancel_stock_document(self._document_id, self._company_id())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            QMessageBox.warning(self, "خطا در لغوِ سند", str(exc))
            return
        # لغو هم مثلِ ثبتِ نهایی یک وضعیتِ نهایی‌ست — سند دیگر رویِ همین
        # فرم قابلِ‌ادامه‌کاری نیست، پس فرم برایِ سندِ بعدی ریست می‌شود.
        self._reset_form()
        theme.set_status_label(self.status_label, "سند لغو شد.", ok=True)
