"""فهرستِ اسنادِ بازرگانی — فیلترِ نوع/وضعیت، بازکردنِ سندِ انتخاب‌شده در
فرمِ مخصوصِ همان نوع (commercial_document.py)."""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
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
from peecha.ui.screens.commercial_document import (
    DOC_TYPE_TITLES,
    STATUS_LABELS,
    _CONVERTIBLE_TO_INVOICE_TYPES,
    _CONVERTS_TO_SALES_INVOICE,
    _ConvertToInvoiceDialog,
)

_COLUMNS = ["ردیف", "نوع", "شماره", "تاریخ", "طرفِ‌حساب", "جمعِ کل", "وضعیت", "شمارهٔ مرجع", "وضعیتِ تبدیل", "عملیات"]

# طبقِ رفعِ باگِ واقعی: این‌جا باید کدهایِ ناوبریِ nav_catalog.py (همان‌ها
# که MainWindow.open_screen ازشان می‌خواند) باشد، نه نامِ داخلیِ ویجتِ
# ثبت‌شده با register_screen — قبلاً این دو با هم اشتباه شده بود، پس
# open_screen هیچ‌وقت آیتمی پیدا نمی‌کرد و دکمه‌هایِ «+» و ویرایش/دابل‌کلیک
# در این لیست همیشه در سکوت هیچ کاری نمی‌کردند.
_TYPE_TO_NAV_CODE = {
    "SALES_ORDER": "SALES_ORDER",
    "SALES_PROFORMA": "SALES_PROFORMA",
    "SALES_INVOICE": "SALES_INVOICE",
    "SALES_RETURN": "SALES_RETURN",
    "PURCHASE_ORDER": "PURCH_ORDER",
    "PURCHASE_PROFORMA": "PURCH_PROFORMA",
    "PURCHASE_INVOICE": "PURCH_INVOICE",
    "PURCHASE_RETURN": "PURCH_RETURN",
    "CONSIGNMENT_OUT": "SALES_CONSIGNMENT_OUT",
    "CONSIGNMENT_IN": "PURCH_CONSIGNMENT_IN",
}


class CommercialDocumentsListScreen(QWidget):
    def __init__(self, main_window, type_filter_codes: tuple[str, ...] | None = None) -> None:
        super().__init__()
        self._main_window = main_window
        self._type_filter_codes = type_filter_codes
        self._rows: list = []
        self._parties_by_id: dict[int, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)

        title = QLabel("اسنادِ فروش" if type_filter_codes and type_filter_codes[0].startswith("SALES") else "اسنادِ خرید" if type_filter_codes else "اسنادِ بازرگانی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        visible_types = type_filter_codes or tuple(DOC_TYPE_TITLES.keys())

        filters = QHBoxLayout()
        filters.addWidget(QLabel("نوع"))
        self.type_filter = QComboBox()
        self.type_filter.addItem("(همه)", None)
        for code in visible_types:
            self.type_filter.addItem(DOC_TYPE_TITLES[code], code)
        self.type_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.type_filter)

        filters.addWidget(QLabel("وضعیت"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("(همه)", None)
        for code, label in STATUS_LABELS.items():
            self.status_filter.addItem(label, code)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.status_filter)
        filters.addStretch(1)
        layout.addLayout(filters)

        new_buttons = QHBoxLayout()
        for code in visible_types:
            button = QPushButton(f"➕ {DOC_TYPE_TITLES[code]}")
            button.setObjectName("primaryButton")
            button.setToolTip(f"سندِ {DOC_TYPE_TITLES[code]}یِ تازه")
            button.clicked.connect(lambda _checked=False, c=code: self._open_new(c))
            new_buttons.addWidget(button)
        layout.addLayout(new_buttons)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        # طبقِ رفعِ باگِ واقعی («عرضِ ردیف‌ها کمه، اصلا نمادها معلوم
        # نیست»): ارتفاعِ پیش‌فرضِ ردیف (بر مبنایِ فقط متنِ ستون‌هایِ
        # دیگر) برایِ جا دادنِ دکمه‌هایِ آیکونی کافی نبود و آیکون‌ها
        # نصفه/فشرده دیده می‌شدند.
        self.table.verticalHeader().setMinimumSectionSize(40)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(len(_COLUMNS) - 1, QHeaderView.ResizeToContents)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self.table, stretch=1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._parties_by_id = {}
        for c in dimensions_service.list_customers(company_id):
            self._parties_by_id[c["detail_account_id"]] = f"{c['code']} — {c['name'] or ''}"
        for s in dimensions_service.list_suppliers(company_id):
            self._parties_by_id[s["detail_account_id"]] = f"{s['code']} — {s['name'] or ''}"

        type_code = self.type_filter.currentData()
        if type_code is None and self._type_filter_codes is not None:
            self._rows = []
            for code in self._type_filter_codes:
                self._rows.extend(documents_service.list_documents(company_id, document_type_code=code, status_code=self.status_filter.currentData()))
            self._rows.sort(key=lambda d: d.document_id, reverse=True)
        else:
            self._rows = documents_service.list_documents(company_id, document_type_code=type_code, status_code=self.status_filter.currentData())

        self.table.setRowCount(len(self._rows))
        for row_index, d in enumerate(self._rows):
            fulfillment = self._fulfillment_summary(d, company_id)
            values = [
                str(row_index + 1),
                DOC_TYPE_TITLES.get(d.document_type_code, d.document_type_code),
                numerals.to_persian_digits(str(d.document_no)),
                numerals.format_jalali_date(d.document_date),
                self._parties_by_id.get(d.counterparty_detail_account_id, "—"),
                numerals.format_amount(d.total_amount),
                STATUS_LABELS.get(d.status_code, d.status_code),
                d.reference_no or "—",
                self._fulfillment_text(fulfillment),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, d.document_id)
                self.table.setItem(row_index, col_index, item)
            self.table.setCellWidget(row_index, len(_COLUMNS) - 1, self._build_row_actions(d, fulfillment))
        self.table.resizeRowsToContents()

    def _fulfillment_summary(self, d, company_id: int) -> tuple[decimal.Decimal, decimal.Decimal] | None:
        # طبقِ درخواستِ صریح («مدیریتِ سفارشات داشته باشیم»): فقط برایِ
        # سفارش/پیش‌فاکتورِ تاییدشده/تصویب‌شده/ثبت‌شده معنا دارد.
        if d.document_type_code not in _CONVERTIBLE_TO_INVOICE_TYPES or d.status_code not in ("CONFIRMED", "APPROVED", "POSTED"):
            return None
        return documents_service.get_order_fulfillment_summary(d.document_id, company_id)

    def _fulfillment_text(self, fulfillment) -> str:
        if fulfillment is None:
            return "—"
        ordered, invoiced = fulfillment
        if invoiced <= 0:
            return "تبدیل‌نشده"
        if invoiced >= ordered:
            return "کامل"
        return f"جزئی ({numerals.format_money(invoiced, 3)} از {numerals.format_money(ordered, 3)})"

    def _build_row_actions(self, d, fulfillment=None) -> QWidget:
        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(4, 4, 4, 4)
        actions_layout.setSpacing(6)

        # طبقِ رفعِ باگِ واقعی («سفارشات ویرایش نمیشه»): سفارش/پیش‌فاکتور
        # برخلافِ فاکتور/برگشت، بعدِ تاییدشدن هم قابلِ‌ویرایش می‌مانند
        # (services/commercial_documents.py:_get_editable_document).
        is_order_type = d.document_type_code in _CONVERTIBLE_TO_INVOICE_TYPES
        is_editable = d.status_code == "DRAFT" or (is_order_type and d.status_code in ("CONFIRMED", "APPROVED"))
        # طبقِ رفعِ باگِ واقعی («علامتهایِ حذف و ویرایش و تبدیل در ردیف
        # معلوم نیست»): ✏️/🗑️/🧾 ایموجی‌هایِ نسبتاً تازه‌اند (یونیکدِ ۹ به
        # بعد) و روی فونت/سیستمِ کاربر بدونِ گلیفِ رنگی به‌صورتِ جعبه‌یِ
        # خالی نمایش داده می‌شدند؛ این نمادها با نمادهایِ سادهٔ متنیِ
        # عمومی (همان‌هایی که خودِ دکمهٔ بستنِ پنجرهٔ اصلی هم استفاده
        # می‌کند و مطمئناً درست دیده می‌شود) جایگزین شدند.
        edit_button = QPushButton("✎")
        edit_button.setObjectName("iconButton")
        edit_button.setFixedSize(44, 32)
        edit_button.setToolTip("اصلاح" if is_editable else "مشاهده")
        edit_button.clicked.connect(lambda _checked=False, doc_id=d.document_id: self._open_existing(doc_id))
        actions_layout.addWidget(edit_button)

        delete_button = QPushButton("✕")
        delete_button.setObjectName("dangerIconButton")
        delete_button.setFixedSize(44, 32)
        if d.status_code not in ("POSTED", "CORRECTED"):
            # طبقِ services/commercial_documents.py:delete_document —
            # DRAFT/CONFIRMED/APPROVED/CANCELLED هرگز اثری در انبار یا
            # حسابداری نگذاشته‌اند، پس حذفِ مستقیم همیشه بی‌خطر است.
            delete_button.setToolTip("حذفِ سند")
            delete_button.clicked.connect(lambda _checked=False, doc_id=d.document_id: self._delete_document(doc_id))
        else:
            delete_button.setEnabled(False)
            delete_button.setToolTip(
                "این سند اصلاح شده و تاریخچه‌اش باید دست‌نخورده بماند — حذفِ مستقیم ممکن نیست."
                if d.status_code == "CORRECTED" else
                "این سند ثبتِ‌نهایی شده و در انبار/حسابداری اثر دارد — حذفِ مستقیم ممکن نیست."
            )
        actions_layout.addWidget(delete_button)

        # طبقِ درخواستِ صریح («تبدیل باید همین‌جا در صفحه‌یِ اسناد انجام
        # شود، نه با بازکردنِ سفارش و رفتن به فرمِ آن»): دکمه‌یِ تبدیل به
        # فاکتور مستقیماً در همین ردیف — بدونِ نیاز به بازکردنِ فرمِ سند.
        if is_order_type:
            convert_button = QPushButton("→")
            convert_button.setObjectName("primaryIconButton")
            convert_button.setFixedSize(44, 32)
            if fulfillment is None:
                convert_button.setEnabled(False)
                convert_button.setToolTip("فقط سندِ تاییدشده/تصویب‌شده/ثبت‌شده قابلِ‌تبدیل به فاکتور است.")
            elif fulfillment[1] >= fulfillment[0]:
                convert_button.setEnabled(False)
                convert_button.setToolTip("کل این سند قبلاً به فاکتور تبدیل شده است.")
            else:
                convert_button.setToolTip("تبدیل به فاکتور")
                convert_button.clicked.connect(lambda _checked=False, doc_id=d.document_id: self._convert_document(doc_id))
            actions_layout.addWidget(convert_button)
        actions_layout.addStretch(1)
        return actions

    def _open_new(self, document_type_code: str) -> None:
        nav_code = _TYPE_TO_NAV_CODE[document_type_code]
        self._main_window.open_screen(nav_code, then=lambda screen: screen._reset_form())

    def _open_existing(self, document_id: int) -> None:
        doc = next((d for d in self._rows if d.document_id == document_id), None)
        if doc is None:
            return
        nav_code = _TYPE_TO_NAV_CODE[doc.document_type_code]
        self._main_window.open_screen(nav_code, then=lambda screen: screen.edit_document(document_id))

    def _convert_document(self, document_id: int) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        doc = next((d for d in self._rows if d.document_id == document_id), None)
        if doc is None:
            return
        try:
            fulfillment = documents_service.get_line_fulfillment(document_id, company_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا در تبدیل به فاکتور", str(exc))
            return
        if not any(f.remaining_quantity > 0 for f in fulfillment):
            QMessageBox.information(self, "تبدیل به فاکتور", "چیزی برایِ تبدیل به فاکتور باقی نمانده است — کل این سند قبلاً فاکتور شده.")
            return
        items_by_id = {it.item_id: it for it in catalog_service.list_items(company_id, active_only=True)}
        dialog = _ConvertToInvoiceDialog(self, fulfillment, items_by_id)
        if dialog.exec() != QDialog.Accepted:
            return
        converts_to_sales = doc.document_type_code in _CONVERTS_TO_SALES_INVOICE
        target_title = "فاکتورِ فروش" if converts_to_sales else "فاکتورِ خرید"
        try:
            new_document_id = documents_service.convert_to_invoice(
                document_id, company_id, app_session.current_user.user_id, datetime.date.today(),
                line_quantities=dialog.result_quantities(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا در تبدیل به فاکتور", str(exc))
            return
        QMessageBox.information(
            self, "تبدیل به فاکتور", f"{target_title} #{numerals.to_persian_digits(str(new_document_id))} از رویِ این سند ساخته شد."
        )
        self.refresh()

    def _delete_document(self, document_id: int) -> None:
        confirm = QMessageBox.question(
            self, "حذف", "این سند حذف شود؟ این کار قابلِ‌بازگشت نیست.", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        company_id = self._company_id()
        if company_id is None:
            return
        try:
            documents_service.delete_document(document_id, company_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _on_row_double_clicked(self, row: int, _column: int) -> None:
        document_id = self.table.item(row, 0).data(Qt.UserRole)
        self._open_existing(document_id)
