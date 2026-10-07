"""تایید رسید کالا — طبق گزارش صریح کاربر: «بعد تایید سفارش خرید
انباردار کجا باید رسیدن کالا را تایید کند؟ و دسترسی هم نداشته باشد
قیمت کالا را ببیند — و این تنظیمی باشد.»

هم‌الگو با pre_sales_fulfillment.py (همان زیرساخت warehouse_approved_at/
warehouse_delivered_quantی ازپیش‌موجود)، با دو تفاوت عمده:
۱) این‌جا برای PURCHASE_ORDER است، نه SALES_ORDER کانال پخش سرد --
   و فقط وقتی Toggle PURCHASE_ORDER_GOODS_RECEIPT (تنظیمات بازرگانی)
   برای شرکت روشن باشد چیزی نشان می‌دهد.
۲) جدول ردیف‌ها عمداً هیچ ستون قیمتی ندارد — و چون این یک آیتم
   ناوبری مستقل است (نه تبی درون فرم کامل سفارش خرید)، می‌توان به
   نقش انباردار فقط دسترسی همین فرم را داد، نه فرم سفارش خرید که
   قیمت دارد؛ یعنی «پنهان‌کردن قیمت» از طریق همان مدل استاندارد
   دسترسی فرم‌ها (roles.py) انجام می‌شود، نه یک مکانیزم تازه.
۳) بدون مفهوم توزین (آن فقط برای کالای وزنی فروش حضوری معنا دارد).
"""

from __future__ import annotations

import decimal

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session as app_session
from peecha.services import commercial_documents as documents_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.ui.screens.journal_entry import _AmountField
from peecha.ui.widgets import FieldHelpMixin, persist_column_widths

_COLUMNS = ["شماره", "تاریخ", "طرف حساب", "وضعیت", "عملیات"]
_LINE_COLUMNS = ["کالا", "واحد", "مقدار سفارش", "مقدار دریافتی/تحویلی", "انبار", "مکان", "بچ/سریال/انقضا"]
_BIN_COL, _TRACK_COL = 5, 6


_DOC_TITLES = {
    "PURCHASE_ORDER": "سفارش خرید", "SALES_ORDER": "سفارش فروش",
    "CONSIGNMENT_IN": "امانی ورودی", "CONSIGNMENT_OUT": "امانی خروجی",
    "PURCHASE_INVOICE": "فاکتور خرید",
}
_ORDER_TYPES = ("PURCHASE_ORDER", "SALES_ORDER")
# خروجِ کالا: بچ/سریال از موجودیِ همان انبار انتخاب می‌شود
_OUT_TYPES = ("SALES_ORDER", "CONSIGNMENT_OUT")
# R254: مکانِ ورود فقط در رسید (خروج را موتورِ انبار خودکار تعیین می‌کند)
_IN_TYPES = ("PURCHASE_ORDER", "CONSIGNMENT_IN", "PURCHASE_INVOICE")


def _status_label(doc) -> str:
    title = _DOC_TITLES.get(doc.document_type_code, "")
    if doc.warehouse_approved_at is None:
        return f"{title} -- در انتظار تایید انباردار"
    if doc.document_type_code not in _ORDER_TYPES:
        return f"{title} -- تایید انبار شد، آمادهٔ ثبت نهایی"
    if doc.document_type_code == "SALES_ORDER":
        return f"{title} -- حواله تایید شده، آمادهٔ تبدیل به فاکتور"
    return f"{title} -- رسید تایید شده، آمادهٔ تبدیل به فاکتور"


class _GoodsReceiptDialog(QDialog):
    def __init__(self, parent: QWidget, document_id: int, company_id: int) -> None:
        super().__init__(parent)
        self.setWindowTitle("بازکردن سند — تایید انبار (رسید/حواله)")
        self.setMinimumWidth(900)
        self._document_id = document_id
        self._company_id = company_id
        self._qty_fields: dict[int, _AmountField] = {}
        self._line_warehouse_combos: dict[int, QComboBox] = {}
        self._line_bin_combos: dict[int, QComboBox] = {}
        self._bin_cache: dict[int, list[tuple[int, str]]] = {}
        self.changed = False

        layout = QVBoxLayout(self)
        self.header_label = QLabel("")
        self.header_label.setWordWrap(True)
        layout.addWidget(self.header_label)

        hint = QLabel(
            "مقدار واقعاً دریافت‌شده (خرید) یا تحویل‌شده (فروش) هر ردیف را وارد/ویرایش کنید — اگر برابر مقدار سفارش بماند، "
            "همان مقدار سفارش لحاظ می‌شود. برای کالای بچ/سریال‌دار، از «🏷 ردیابی» وارد/انتخاب کنید."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.lines_table = QTableWidget(0, len(_LINE_COLUMNS))
        self.lines_table.setHorizontalHeaderLabels(_LINE_COLUMNS)
        self.lines_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lines_table.verticalHeader().setVisible(False)
        self.lines_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        # R228: ردیف‌ها بلندتر (کمبویِ انبار/دکمهٔ ردیابی داخلِ سلول)
        self.lines_table.verticalHeader().setDefaultSectionSize(46)
        self.lines_table.setMinimumHeight(260)
        persist_column_widths(self.lines_table, "goodsReceiptLines")
        layout.addWidget(self.lines_table, stretch=1)

        # طبقِ گزارشِ صریحِ کاربر: در سفارش انبار لازم نیست -- انباردار
        # هنگامِ رسید مشخص می‌کند کالا به کدام انبار وارد شد؛ فقط
        # انبارهایی که خودش انباردارشان است (فیلدِ «مسئولِ انبار») -- مدیر همه را.
        warehouse_row = QHBoxLayout()
        warehouse_row.addWidget(QLabel("انبار پیش‌فرض همهٔ ردیف‌ها"))
        self.warehouse_combo = QComboBox()
        # R226: انتخابِ انبارِ پیش‌فرض، انبارِ همهٔ ردیف‌ها را هم عوض می‌کند؛
        # هر ردیف می‌تواند جداگانه انبارِ دیگری داشته باشد.
        self.warehouse_combo.activated.connect(self._apply_default_warehouse)
        warehouse_row.addWidget(self.warehouse_combo, stretch=1)
        layout.addLayout(warehouse_row)

        self.save_button = QPushButton("💾 ذخیرهٔ مقادیر دریافتی/تحویلی")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save_quantities)
        layout.addWidget(self.save_button)

        self.receipt_button = QPushButton("")
        self.receipt_button.clicked.connect(self._toggle_receipt)
        layout.addWidget(self.receipt_button)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        layout.addWidget(buttons)

        self._reload()

    def _reload(self) -> None:
        self.status_label.setText("")
        try:
            doc, lines = documents_service.get_document(self._document_id, self._company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._doc = doc
        converted = documents_service.document_has_been_converted(self._document_id, self._company_id)
        allowed = documents_service.receivable_warehouse_ids(self._company_id, app_session.current_user.user_id)
        self.warehouse_combo.clear()
        line_warehouse_ids = {ln.warehouse_id for ln in lines if ln.warehouse_id is not None}
        self._warehouse_options = [
            (f"{w.code} — {w.name}", w.warehouse_id)
            for w in locations_service.list_warehouses(self._company_id, active_only=True)
            if allowed is None or w.warehouse_id in allowed or w.warehouse_id == doc.warehouse_id or w.warehouse_id in line_warehouse_ids
        ]
        for label, wid in self._warehouse_options:
            self.warehouse_combo.addItem(label, wid)
        if doc.warehouse_id is not None:
            self.warehouse_combo.setCurrentIndex(max(0, self.warehouse_combo.findData(doc.warehouse_id)))
        self.warehouse_combo.setEnabled(doc.warehouse_approved_at is None and not converted)

        self.header_label.setText(
            f"{_DOC_TITLES.get(doc.document_type_code, 'سند')} شمارهٔ {numerals.to_persian_digits(str(doc.document_no))} -- "
            f"{dimensions_service.get_detail_account_label(doc.counterparty_detail_account_id)} -- "
            f"{numerals.format_jalali_date(doc.document_date)}"
        )

        items_by_id = {it.item_id: it for it in catalog_service.list_items(self._company_id)}
        uoms = catalog_service.list_uoms(self._company_id)
        uom_decimal_places = {u.uom_id: u.decimal_places for u in uoms}
        uom_names = {u.uom_id: u.name or u.code for u in uoms}
        self._qty_fields = {}
        self._line_warehouse_combos = {}
        self._line_bin_combos = {}
        self._bin_cache = {}
        is_inbound = doc.document_type_code in _IN_TYPES
        self.lines_table.setColumnHidden(_BIN_COL, not is_inbound)
        editable = doc.warehouse_approved_at is None and not converted
        # R230: در امانی (و R255: فاکتورِ خریدِ مستقیم)، انبار و مقدار همان سند است -- انباردار فقط تایید می‌کند
        is_consignment = doc.document_type_code not in _ORDER_TYPES
        self.lines_table.setRowCount(len(lines))
        for row_index, ln in enumerate(lines):
            item = items_by_id.get(ln.item_id)
            dp = uom_decimal_places.get(ln.uom_id, 3)
            self.lines_table.setItem(row_index, 0, QTableWidgetItem(f"{item.code} — {item.name or ''}" if item else str(ln.item_id)))
            self.lines_table.setItem(row_index, 1, QTableWidgetItem(uom_names.get(ln.uom_id, "")))
            self.lines_table.setItem(row_index, 2, QTableWidgetItem(numerals.format_money(ln.quantity, dp)))
            qty_field = _AmountField()
            qty_field.setDecimals(dp)
            qty_field.setValue(float(ln.warehouse_delivered_quantity if ln.warehouse_delivered_quantity is not None else ln.quantity))
            qty_field.setEnabled(not converted and not is_consignment)
            self._qty_fields[ln.line_id] = qty_field
            self.lines_table.setCellWidget(row_index, 3, qty_field)
            wh_combo = QComboBox()
            for label, wid in self._warehouse_options:
                wh_combo.addItem(label, wid)
            current = ln.warehouse_id or self.warehouse_combo.currentData()
            wh_combo.setCurrentIndex(max(0, wh_combo.findData(current)))
            wh_combo.setEnabled(editable and not is_consignment)
            self._line_warehouse_combos[ln.line_id] = wh_combo
            self.lines_table.setCellWidget(row_index, 4, wh_combo)
            if is_inbound:
                self.lines_table.setCellWidget(row_index, _BIN_COL, self._make_bin_cell(ln, item, wh_combo, editable))
            if item is not None and (item.track_batch or item.track_serial):
                # R227: ورودِ بچ/سریال/انقضا هنگامِ تاییدِ رسید
                track_button = QPushButton("🏷 ردیابی")
                track_button.clicked.connect(
                    lambda _c=False, line=ln, it=item, ro=not editable: self._open_lot_tracking(line, it, ro)
                )
                self.lines_table.setCellWidget(row_index, _TRACK_COL, track_button)

        word = "حوالهٔ انبار" if doc.document_type_code in _OUT_TYPES else "رسید کالا"
        self.save_button.setEnabled(not converted and not is_consignment)
        if is_consignment:
            self.warehouse_combo.setEnabled(False)

        if converted:
            self.receipt_button.setText(f"✅ تایید {word} (قطعی — به فاکتور تبدیل شده)")
            self.receipt_button.setEnabled(False)
            return

        if doc.warehouse_approved_at is None:
            self.receipt_button.setText(f"✅ تایید {word}")
            self.receipt_button.setObjectName("primaryButton")
        else:
            self.receipt_button.setText(f"↩️ بازگشت تایید {word}")
            self.receipt_button.setObjectName("dangerButton")
        self.receipt_button.setEnabled(True)
        self.receipt_button.setStyleSheet("")
        self.receipt_button.style().unpolish(self.receipt_button)
        self.receipt_button.style().polish(self.receipt_button)

    def _bins_of(self, warehouse_id) -> list[tuple[int, str]]:
        """محل‌های برگ فعال انبار (کد کامل)."""
        if warehouse_id is None:
            return []
        if warehouse_id not in self._bin_cache:
            from peecha.services import warehouse_locations as wl

            nodes = wl.tree(self._company_id, warehouse_id)
            parents = {n.parent_id for n in nodes}
            self._bin_cache[warehouse_id] = sorted(
                ((n.location_id, n.full_code) for n in nodes if n.is_active and n.location_id not in parents), key=lambda t: t[1])
        return self._bin_cache[warehouse_id]

    def _fill_bin_combo(self, combo: QComboBox, warehouse_id, current) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("— انتخاب کنید —", None)
        for location_id, code in self._bins_of(warehouse_id):
            combo.addItem(code, location_id)
        combo.setCurrentIndex(max(0, combo.findData(current)) if current is not None else 0)
        combo.blockSignals(False)

    def _make_bin_cell(self, ln, item, wh_combo: QComboBox, editable: bool) -> QWidget:
        cell = QWidget()
        row = QHBoxLayout(cell)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(4)
        combo = QComboBox()
        combo.setMinimumWidth(150)
        self._fill_bin_combo(combo, wh_combo.currentData(), ln.bin_location_id)
        combo.setEnabled(editable)
        combo.setToolTip("مکان قرارگیری کالا در انبار — برای انبار دارای مکان‌بندی الزامی است.")
        wh_combo.currentIndexChanged.connect(lambda _i, c=combo, w=wh_combo: self._fill_bin_combo(c, w.currentData(), None))
        map_button = QPushButton("نقشه")
        map_button.setToolTip("انتخاب مکان روی نقشهٔ انبار (با پیشنهاد جانمایی)")
        map_button.setEnabled(editable)
        map_button.clicked.connect(lambda _c=False, line=ln, it=item, c=combo, w=wh_combo: self._pick_on_map(line, it, c, w))
        row.addWidget(combo, stretch=1)
        row.addWidget(map_button)
        self._line_bin_combos[ln.line_id] = combo
        return cell

    def _pick_on_map(self, line, item, combo: QComboBox, wh_combo: QComboBox) -> None:
        from peecha.ui.screens.warehouse_map import LocationPickerDialog

        warehouse_id = wh_combo.currentData()
        if warehouse_id is None:
            self.status_label.setText("ابتدا انبار ردیف را انتخاب کنید.")
            return
        field = self._qty_fields.get(line.line_id)
        qty = decimal.Decimal(str(field.value())) if field is not None else line.quantity
        dialog = LocationPickerDialog(self, warehouse_id, combo.currentData(), line.item_id, qty * (line.conversion_factor or 1),
                                      f"{item.code} — {item.name or ''}" if item else "")
        if dialog.exec() == QDialog.Accepted and dialog.selected_location_id is not None:
            self._bin_cache.pop(warehouse_id, None)
            self._fill_bin_combo(combo, warehouse_id, dialog.selected_location_id)

    def _open_lot_tracking(self, line, item, read_only: bool) -> None:
        from peecha.ui.screens.lot_tracking_dialog import LotTrackingDialog

        field = self._qty_fields.get(line.line_id)
        delivered = decimal.Decimal(str(field.value())) if field is not None else line.quantity
        is_out = self._doc.document_type_code in _OUT_TYPES
        combo = self._line_warehouse_combos.get(line.line_id)
        LotTrackingDialog(
            self, self._company_id, item.item_id, f"{item.code} — {item.name or ''}",
            delivered * (line.conversion_factor or 1), commercial_line_id=line.line_id, read_only=read_only,
            direction="OUT" if is_out else "IN",
            warehouse_id=(combo.currentData() if combo is not None else None) or line.warehouse_id or self._doc.warehouse_id,
        ).exec()

    def _apply_default_warehouse(self, *_args) -> None:
        wid = self.warehouse_combo.currentData()
        for combo in self._line_warehouse_combos.values():
            if combo.isEnabled():
                combo.setCurrentIndex(max(0, combo.findData(wid)))

    def _save_quantities(self) -> None:
        quantities = {line_id: decimal.Decimal(str(field.value())) for line_id, field in self._qty_fields.items()}
        try:
            documents_service.set_warehouse_delivered_quantities(self._document_id, self._company_id, quantities)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.changed = True
        self._reload()

    def _toggle_receipt(self) -> None:
        user_id = app_session.current_user.user_id
        try:
            if self._doc.warehouse_approved_at is None:
                documents_service.approve_warehouse(
                    self._document_id, self._company_id, user_id, warehouse_id=self.warehouse_combo.currentData(),
                    line_warehouses={
                        line_id: combo.currentData() for line_id, combo in self._line_warehouse_combos.items()
                        if combo.currentData() is not None
                    },
                    line_bins={line_id: combo.currentData() for line_id, combo in self._line_bin_combos.items()} or None,
                )
            else:
                documents_service.revert_warehouse_approval(self._document_id, self._company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.changed = True
        self._reload()


class PurchaseGoodsReceiptScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._queue: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(14)

        title = QLabel("تایید انبار — رسید/حوالهٔ سفارش‌های خرید و فروش و امانی ورودی/خروجی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        hint = QLabel(
            "سفارش‌های خرید (رسید) و فروش (حواله) که آمادهٔ تایید انبار هستند و هنوز به فاکتور تبدیل نشده‌اند، "
            "به‌همراه امانی‌ها — بدون قیمت، فقط مقدار. با «📂 بازکردن» مقدار، انبار و بچ/سریال هر ردیف را ثبت و تایید کنید."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setMinimumHeight(300)
        layout.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.set_field_help([
            (self.table, "سفارش‌های خرید تاییدشده/تصویب‌شده‌ای که هنوز به فاکتور تبدیل نشده‌اند — با «بازکردن»، مقدار دریافتی و تایید رسید انجام می‌شود."),
        ])

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self.status_label.setText("")
        user = app_session.current_user
        self._queue = documents_service.list_purchase_order_goods_receipt_queue(
            company_id, user.user_id if user is not None else None,
        )
        if not self._queue:
            self.status_label.setObjectName("sectionHint")
            self.status_label.setText(
                "موردی نیست — یا سند در انتظار وجود ندارد، یا «تایید رسید کالا»/«تایید حوالهٔ انبار» "
                "در تنظیمات بازرگانی روشن نیست، یا شما انباردار (مسئول) هیچ انباری نیستید."
            )
        self.table.setRowCount(len(self._queue))
        for row_index, doc in enumerate(self._queue):
            values = [
                numerals.to_persian_digits(str(doc.document_no)),
                numerals.format_jalali_date(doc.document_date),
                dimensions_service.get_detail_account_label(doc.counterparty_detail_account_id),
                _status_label(doc),
            ]
            for col_index, value in enumerate(values):
                self.table.setItem(row_index, col_index, QTableWidgetItem(value))
            button = QPushButton("📂 بازکردن")
            button.clicked.connect(lambda _checked=False, document_id=doc.document_id: self._open_document(document_id))
            self.table.setCellWidget(row_index, len(_COLUMNS) - 1, button)
        self.table.resizeRowsToContents()

    def _open_document(self, document_id: int) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        dialog = _GoodsReceiptDialog(self, document_id, company_id)
        dialog.exec()
        if dialog.changed:
            self.refresh()
