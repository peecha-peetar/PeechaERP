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
from peecha.services import commercial_settings as settings_service
from peecha.services import roles as roles_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.ui.screens.commercial_document import (
    DOC_TYPE_TITLES,
    STATUS_LABELS,
    _CONVERTIBLE_TO_INVOICE_TYPES,
    _CONVERTS_TO_SALES_INVOICE,
    _ConvertToInvoiceDialog,
    _show_invoice_print,
    convert_warehouse_context,
)
from peecha.ui.widgets import FieldHelpMixin, persist_column_widths

_COLUMNS = ["ردیف", "نوع", "شماره", "تاریخ", "طرفِ‌حساب", "جمعِ کل", "وضعیت", "شمارهٔ مرجع", "وضعیتِ تبدیل", "عملیات"]

# طبقِ رفعِ باگِ واقعیِ گزارش‌شده («سفارشات و فاکتورهایِ تاییدشده در
# پخشِ سرد نمایش داده نمی‌شود»): علتِ ریشه‌ای این بود که این فهرست وقتی
# channel_type_code دارد (پخشِ سرد/گرم)، دکمه‌یِ «➕ سندِ تازه» را -- طبقِ
# منطقِ درست‌ولی‌فقط‌برایِ‌ONLINEِ زیر -- اصلاً نشان نمی‌داد، چون آن منطق
# فرض کرده بود هر لیستِ کانال‌محور مثلِ فروشِ اینترنتی «فقط نمایشی» است
# (سفارش از طریقِ سینکِ خودکار می‌آید). برخلافِ ONLINE، کانال‌هایِ
# PRE_SALES/VAN_SALES هیچ سینکِ خودکاری ندارند -- کاربر باید سفارش/فاکتور
# را دستی بسازد؛ بدونِ این دکمه، تنها راهِ رسیدنِ یک سند به این تب،
# ساختنش از فرمِ عمومیِ «سفارشِ فروش» و به‌یادداشتنِ دستیِ انتخابِ همان
# کانال از کمبویِ «کانالِ فروش» بود -- که عملاً هیچ‌وقت یادآوری نمی‌شد.
_SYNC_ONLY_CHANNEL_TYPES = {"ONLINE"}

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


class CommercialDocumentsListScreen(FieldHelpMixin, QWidget):
    def __init__(
        self, main_window, type_filter_codes: tuple[str, ...] | None = None,
        channel_type_code: str | None = None, title_override: str | None = None,
    ) -> None:
        super().__init__()
        self._main_window = main_window
        self._type_filter_codes = type_filter_codes
        # طبقِ درخواستِ صریح («در منویِ فروشِ اینترنتی فقط سفارش‌هایِ فروشِ
        # مشتری بیاید»): وقتی این مقدار تنظیم شده باشد (مثلاً "ONLINE")،
        # فهرست فقط سندهایی را نشان می‌دهد که کانالشان از همان نوع است --
        # ثابت است، فیلترِ قابلِ‌تغییر توسطِ کاربر نیست.
        self._channel_type_code = channel_type_code
        self._rows: list = []
        self._parties_by_id: dict[int, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)

        title = QLabel(
            title_override
            or ("اسنادِ فروش" if type_filter_codes and type_filter_codes[0].startswith("SALES") else "اسنادِ خرید" if type_filter_codes else "اسنادِ بازرگانی")
        )
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

        # طبقِ درخواستِ صریح («چون تعدادِ فاکتورهایِ تک‌فروشی زیاده باید
        # فیلتری رویِ اسنادِ فروش باشه»): فیلترِ منبعِ سند -- عمومی/
        # تک‌فروشی (POS) -- بر اساسِ pos_session_id.
        filters.addWidget(QLabel("منبع"))
        self.source_filter = QComboBox()
        self.source_filter.addItem("(همه)", None)
        self.source_filter.addItem("عمومی", "GENERAL")
        self.source_filter.addItem("تک‌فروشی (POS)", "POS")
        self.source_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.source_filter)

        # طبقِ درخواستِ صریح («فیلترِ تاییدِ انبار رویِ تبِ سفارش‌ها هم
        # باشد»): فقط برایِ تبِ پخشِ سرد نمایش داده می‌شود -- برایِ بقیه‌یِ
        # کانال‌ها/فهرست‌هایِ عمومی، این گیت اصلاً معنا ندارد.
        self.warehouse_status_filter = QComboBox()
        if channel_type_code == "PRE_SALES":
            filters.addWidget(QLabel("وضعیتِ انبار/توزین"))
            self.warehouse_status_filter.addItem("(همه)", None)
            self.warehouse_status_filter.addItem("در انتظارِ تاییدِ انبار", "در انتظارِ تاییدِ انبار")
            self.warehouse_status_filter.addItem("در انتظارِ توزین", "در انتظارِ توزین")
            self.warehouse_status_filter.addItem("آمادهٔ تبدیل به فاکتور", "آمادهٔ تبدیل به فاکتور")
            self.warehouse_status_filter.currentIndexChanged.connect(self.refresh)
            filters.addWidget(self.warehouse_status_filter)
        filters.addStretch(1)
        layout.addLayout(filters)

        new_buttons = QHBoxLayout()
        if channel_type_code not in _SYNC_ONLY_CHANNEL_TYPES:
            for code in visible_types:
                button = QPushButton(f"➕ {DOC_TYPE_TITLES[code]}")
                button.setObjectName("primaryButton")
                button.setToolTip(f"سندِ {DOC_TYPE_TITLES[code]}یِ تازه")
                button.clicked.connect(lambda _checked=False, c=code: self._open_new(c))
                new_buttons.addWidget(button)
        layout.addLayout(new_buttons)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        persist_column_widths(self.table, "commercialDocumentsList")
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

        self.set_field_help([
            (self.type_filter, "فقط اسنادِ همین نوع نشان داده شوند."),
            (self.status_filter, "فقط اسنادِ همین وضعیت نشان داده شوند."),
            (self.source_filter, "فقط اسنادِ ثبت‌شده از فرمِ عمومی یا فقط فروشِ حضوری (POS) نشان داده شوند."),
            (self.warehouse_status_filter, "فقط سفارش‌هایی که در همین مرحله از تاییدِ انبار/توزین هستند نشان داده شوند."),
        ])

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
                self._rows.extend(
                    documents_service.list_documents(
                        company_id, document_type_code=code, status_code=self.status_filter.currentData(),
                        channel_type_code=self._channel_type_code,
                    )
                )
            self._rows.sort(key=lambda d: d.document_id, reverse=True)
        else:
            self._rows = documents_service.list_documents(
                company_id, document_type_code=type_code, status_code=self.status_filter.currentData(),
                channel_type_code=self._channel_type_code,
            )

        source = self.source_filter.currentData()
        if source == "POS":
            self._rows = [d for d in self._rows if d.pos_session_id is not None]
        elif source == "GENERAL":
            self._rows = [d for d in self._rows if d.pos_session_id is None]

        pre_sales_statuses = {
            d.document_id: documents_service.describe_pre_sales_fulfillment_status(d.document_id, company_id)
            for d in self._rows
        }
        warehouse_status = self.warehouse_status_filter.currentData() if self._channel_type_code == "PRE_SALES" else None
        if warehouse_status is not None:
            self._rows = [d for d in self._rows if pre_sales_statuses.get(d.document_id) == warehouse_status]

        self.table.setRowCount(len(self._rows))
        for row_index, d in enumerate(self._rows):
            fulfillment = self._fulfillment_summary(d, company_id)
            pre_sales_status = pre_sales_statuses.get(d.document_id)
            type_label = DOC_TYPE_TITLES.get(d.document_type_code, d.document_type_code)
            if d.pos_session_id is not None:
                type_label += " (تک‌فروشی)"
            values = [
                str(row_index + 1),
                type_label,
                numerals.to_persian_digits(str(d.document_no)),
                numerals.format_jalali_date(d.document_date),
                self._parties_by_id.get(d.counterparty_detail_account_id, "—"),
                numerals.format_company_amount(d.total_amount),
                STATUS_LABELS.get(d.status_code, d.status_code),
                d.reference_no or "—",
                pre_sales_status or self._fulfillment_text(fulfillment),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, d.document_id)
                self.table.setItem(row_index, col_index, item)
            self.table.setCellWidget(row_index, len(_COLUMNS) - 1, self._build_row_actions(d, fulfillment, pre_sales_status))
        # طبقِ رفعِ باگِ واقعیِ هم‌پوشانیِ دکمه‌ها: در این نسخه‌یِ Qt،
        # ResizeToContents فقط یک‌بار (بر مبنایِ متنِ هدر) اندازه‌گیری
        # می‌شود و بعدِ setCellWidget دوباره محاسبه نمی‌شود -- باید صریحاً
        # این ستون را با اندازه‌یِ واقعیِ ویجت‌هایِ داخلش (که بسته به
        # سه‌دکمه‌ای/دودکمه‌ای بودنِ سند فرق می‌کند) دوباره اندازه‌گیری کرد.
        self.table.resizeColumnToContents(len(_COLUMNS) - 1)
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

    def _build_row_actions(self, d, fulfillment=None, pre_sales_status: str | None = None) -> QWidget:
        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(4, 4, 4, 4)
        actions_layout.setSpacing(6)

        # طبقِ رفعِ باگِ واقعی («سفارشات ویرایش نمیشه»): سفارش/پیش‌فاکتور
        # برخلافِ فاکتور/برگشت، بعدِ تاییدشدن هم قابلِ‌ویرایش می‌مانند
        # (services/commercial_documents.py:_get_editable_document).
        is_order_type = d.document_type_code in _CONVERTIBLE_TO_INVOICE_TYPES
        # طبقِ R100: فاکتورِ فروشِ تک‌فروشی هم -- تا پیش از تاییدِ سرپرست
        # (CONFIRMED) -- قابلِ‌اصلاح است (از فرمِ تک‌فروشیِ خودش، طبقِ
        # _open_existing بالا).
        is_pos_pre_approval = (
            d.document_type_code == "SALES_INVOICE" and d.pos_session_id is not None and d.status_code == "CONFIRMED"
        )
        # R224/R226: سفارشِ تاییدشده هم فقط پس از «بازگشت به پیش‌نویس» ویرایش می‌شود.
        is_editable = d.status_code == "DRAFT" or is_pos_pre_approval
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
        # R226: سندِ لغوشده دکمهٔ ویرایش ندارد (فقط نمایشِ چاپی).
        if d.status_code != "CANCELLED":
            actions_layout.addWidget(edit_button)
        else:
            edit_button.deleteLater()

        # R226: نمایشِ چاپیِ سند بدونِ بازکردنِ فرمِ ویرایش.
        print_button = QPushButton("⎙")
        print_button.setObjectName("iconButton")
        print_button.setFixedSize(44, 32)
        print_button.setToolTip("نمایشِ چاپی")
        print_button.clicked.connect(lambda _checked=False, doc_id=d.document_id: self._print_document(doc_id))
        actions_layout.addWidget(print_button)

        # R226: دکمهٔ حذف فقط وقتی حذف واقعاً ممکن است (فاکتورِ تاییدشده فقط لغو
        # می‌شود؛ سندِ لغوشده/ثبت‌شده/اصلاح‌شده هم دکمهٔ حذف ندارد).
        if d.status_code != "CANCELLED" and documents_service.can_delete_document(d):
            delete_button = QPushButton("✕")
            delete_button.setObjectName("dangerIconButton")
            delete_button.setFixedSize(44, 32)
            delete_button.setToolTip("حذفِ سند")
            delete_button.clicked.connect(lambda _checked=False, doc_id=d.document_id: self._delete_document(doc_id))
            actions_layout.addWidget(delete_button)

        next_step = self._next_step(d, fulfillment, pre_sales_status)
        if next_step is not None:
            label, tooltip, action = next_step
            next_button = QPushButton(label)
            next_button.setObjectName("primaryButton")
            next_button.setFixedHeight(32)
            next_button.setToolTip(tooltip)
            next_button.clicked.connect(lambda _checked=False, fn=action: fn())
            actions_layout.addWidget(next_button)

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
            elif pre_sales_status is not None and pre_sales_status != "آمادهٔ تبدیل به فاکتور":
                # طبقِ درخواستِ صریح («وقتی انبار تایید کرد، در لیستِ
                # سفارش‌ها معلوم کند که آمادهٔ تبدیل است و عملیاتِ تبدیل
                # برایش فعال شود»): پیش از این، دکمه همیشه فعال بود و
                # فقط در لحظه‌یِ کلیک با خطا رد می‌شد -- حالا از همین‌جا
                # غیرِفعال است، با دلیلِ روشن.
                convert_button.setEnabled(False)
                convert_button.setToolTip(f"{pre_sales_status} -- ابتدا از تبِ «تاییدِ انبار و توزین» تایید کنید.")
            elif (
                pre_sales_status is None and d.warehouse_approved_at is None
                and documents_service.order_warehouse_step_enabled(self._company_id(), d.document_type_code)
            ):
                # R232: سفارشِ خرید/فروش تا تاییدِ رسید/حوالهٔ انبار تبدیل نمی‌شود
                convert_button.setEnabled(False)
                convert_button.setToolTip(
                    "ابتدا حوالهٔ انبارِ این سفارش باید توسطِ انباردار تایید شود."
                    if d.document_type_code == "SALES_ORDER" else "ابتدا رسیدِ کالایِ این سفارش باید توسطِ انباردار تایید شود."
                )
            else:
                convert_button.setToolTip("تبدیل به فاکتور")
                convert_button.clicked.connect(lambda _checked=False, doc_id=d.document_id: self._convert_document(doc_id))
            actions_layout.addWidget(convert_button)
        actions_layout.addStretch(1)
        return actions

    def _default_channel_code(self) -> str | None:
        if self._channel_type_code is None:
            return None
        company_id = self._company_id()
        if company_id is None:
            return None
        matching = [
            ch for ch in pricing_service.list_channels(company_id) if ch.channel_type_code == self._channel_type_code
        ]
        return matching[0].channel_code if matching else None

    def _open_new(self, document_type_code: str) -> None:
        nav_code = _TYPE_TO_NAV_CODE[document_type_code]
        channel_code = self._default_channel_code()
        if self._channel_type_code is not None and channel_code is None:
            # طبقِ رفعِ باگِ واقعی: بدونِ این هشدار، سندِ تازه بدونِ کانال
            # ساخته می‌شد و دوباره در همین تب هرگز ظاهر نمی‌شد -- بدونِ
            # اینکه کاربر متوجهٔ علتش بشود.
            QMessageBox.warning(
                self, "کانال تعریف نشده است",
                "برایِ این تب هنوز هیچ «کانالِ فروش»یی از همین نوع تعریف نشده -- سندِ تازه بدونِ کانال ساخته می‌شود "
                "و در این فهرست نمایش داده نخواهد شد. ابتدا از «تنظیماتِ سیستم ‹ مدیریتِ بازرگانی ‹ کانال‌هایِ فروش» "
                "یک کانال از همین نوع تعریف کنید.",
            )

        def _prepare(screen) -> None:
            screen._reset_form()
            if channel_code is not None:
                index = screen.channel_combo.findData(channel_code)
                if index >= 0:
                    screen.channel_combo.setCurrentIndex(index)

        self._main_window.open_screen(nav_code, then=_prepare)

    def _open_existing(self, document_id: int) -> None:
        doc = next((d for d in self._rows if d.document_id == document_id), None)
        if doc is None:
            return
        # طبقِ درخواستِ صریح («اصلاحِ فاکتورِ تک‌فروشی جدا از اصلاحِ
        # فاکتور باشه... اگر فاکتور تک‌فروشی اصلاح بشه در همان فرمِ
        # تک‌فروشی باز بشه»): فاکتورِ فروشِ تک‌فروشی (pos_session_id
        # دارد) که هنوز پیش‌از‌تاییدِ‌سرپرست است (DRAFT/CONFIRMED -- طبقِ
        # R100، همان بازه‌ای که اصلاً قابلِ‌اصلاح است)، در فرمِ تک‌فروشیِ
        # خودش باز می‌شود -- نه فرمِ عمومیِ فاکتور. برایِ فاکتورِ
        # POSTEDِ تک‌فروشی (مسیرِ جداگانه‌یِ «اصلاحِ فاکتورِ ثبت‌نهایی‌شده»)
        # همچنان همان فرمِ عمومی باز می‌شود -- طبقِ تصمیمِ صریح، این دو
        # مسیر قاطی نمی‌شوند.
        if (
            doc.document_type_code == "SALES_INVOICE" and doc.pos_session_id is not None
            and doc.status_code in ("DRAFT", "CONFIRMED")
        ):
            self._main_window.open_screen("SALES_POS_SALE", then=lambda screen: screen.open_document_for_edit(document_id))
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
        dialog = _ConvertToInvoiceDialog(
            self, fulfillment, items_by_id,
            quantity_locked=documents_service.receipt_locks_quantity(document_id, company_id),
            warehouse_context=convert_warehouse_context(document_id, company_id),
        )
        if dialog.exec() != QDialog.Accepted:
            return
        converts_to_sales = doc.document_type_code in _CONVERTS_TO_SALES_INVOICE
        target_title = "فاکتورِ فروش" if converts_to_sales else "فاکتورِ خرید"
        try:
            new_document_id = documents_service.convert_to_invoice(
                document_id, company_id, app_session.current_user.user_id, datetime.date.today(),
                line_quantities=dialog.result_quantities(), line_warehouses=dialog.result_warehouses(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا در تبدیل به فاکتور", str(exc))
            return
        QMessageBox.information(
            self, "تبدیل به فاکتور", f"{target_title} #{numerals.to_persian_digits(str(new_document_id))} از رویِ این سند ساخته شد."
        )
        self.refresh()

    def _print_document(self, document_id: int) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        try:
            _show_invoice_print(self, company_id, document_id)
        except ValueError as exc:
            QMessageBox.warning(self, "نمایشِ چاپی", str(exc))

    def _next_step(self, d, fulfillment, pre_sales_status):
        """R226: مرحلهٔ بعدیِ گردشِ کار همین‌جا در ردیف -- (برچسب، راهنما، اقدام) یا None."""
        company_id = self._company_id()
        user = app_session.current_user
        if company_id is None or user is None:
            return None
        is_order = d.document_type_code in _CONVERTIBLE_TO_INVOICE_TYPES
        if d.status_code not in ("CONFIRMED", "APPROVED") and not (is_order and d.status_code == "POSTED"):
            return None
        doc_id = d.document_id
        doc_type = d.document_type_code
        # R232: تصویبِ مدیر برایِ خرید و فروش با همان قاعدهٔ تنظیمی
        needs_approval = d.status_code == "CONFIRMED" and documents_service.requires_manager_approval(company_id, doc_type)
        if needs_approval:
            if not roles_service.is_manager(user.user_id, company_id):
                return None
            return ("تصویب", "مرحلهٔ بعد: تصویبِ مدیر", lambda: self._approve_document(doc_id))
        if doc_type in ("PURCHASE_ORDER", "SALES_ORDER") and pre_sales_status is None:
            is_sale = doc_type == "SALES_ORDER"
            step = "حوالهٔ انبار" if is_sale else "رسیدِ کالا"
            needs_receipt = documents_service.order_warehouse_step_enabled(company_id, doc_type) and d.warehouse_approved_at is None
            if needs_receipt and d.status_code not in documents_service.receipt_eligible_statuses(company_id, doc_type):
                # R230/R232: سفارش ابتدا ثبتِ نهایی می‌شود، بعد به تاییدِ انبار می‌رسد
                if not roles_service.is_manager(user.user_id, company_id):
                    return None
                nav_code = _TYPE_TO_NAV_CODE[doc_type]
                return ("ثبتِ نهایی", f"مرحلهٔ بعد: ثبتِ نهاییِ سفارش (سپس تاییدِ {step})",
                        lambda: self._main_window.open_screen(nav_code, then=lambda screen: (screen.edit_document(doc_id), screen._post())))
            if needs_receipt:
                return (step, f"مرحلهٔ بعد: تاییدِ {step} توسطِ انباردار",
                        lambda: self._main_window.open_screen("SALES_WAREHOUSE_ISSUE" if is_sale else "PURCH_GOODS_RECEIPT"))
        if doc_type in ("CONSIGNMENT_IN", "CONSIGNMENT_OUT") and d.status_code in ("CONFIRMED", "APPROVED"):
            if documents_service.consignment_requires_warehouse_approval(company_id, doc_type) and d.warehouse_approved_at is None:
                return ("تاییدِ انبار", "مرحلهٔ بعد: تاییدِ انباردار", lambda: self._main_window.open_screen("PURCH_GOODS_RECEIPT"))
            if roles_service.is_manager(user.user_id, company_id):
                nav_code = _TYPE_TO_NAV_CODE[doc_type]
                return ("ثبتِ نهایی", "مرحلهٔ بعد: ثبتِ نهاییِ امانی (جابه‌جاییِ کالا)",
                        lambda: self._main_window.open_screen(nav_code, then=lambda screen: (screen.edit_document(doc_id), screen._post())))
        if doc_type in _CONVERTIBLE_TO_INVOICE_TYPES:
            ready = fulfillment is not None and fulfillment[1] < fulfillment[0] and (
                pre_sales_status is None or pre_sales_status == "آمادهٔ تبدیل به فاکتور"
            )
            if ready:
                return ("تبدیل به فاکتور", "مرحلهٔ بعد: تبدیل به فاکتور", lambda: self._convert_document(doc_id))
            return None
        if doc_type in ("SALES_INVOICE", "PURCHASE_INVOICE", "SALES_RETURN", "PURCHASE_RETURN"):
            if not roles_service.is_manager(user.user_id, company_id):
                return None
            nav_code = _TYPE_TO_NAV_CODE[doc_type]
            return ("ثبتِ نهایی", "مرحلهٔ بعد: ثبتِ نهایی (فرمِ سند باز می‌شود)",
                    lambda: self._main_window.open_screen(nav_code, then=lambda screen: (screen.edit_document(doc_id), screen._post())))
        return None

    def _approve_document(self, document_id: int) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        try:
            documents_service.approve_document(document_id, company_id)
        except ValueError as exc:
            QMessageBox.warning(self, "تصویب", str(exc))
            return
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
