"""تاییدِ سرپرست برایِ فروش‌هایِ حضوری (POS، مرحلهٔ ۸) — فاکتورهایی که
کاریر فقط confirm کرده‌اند (پرداختِ واقعی/سندِ حسابداری هنوز ثبت نشده)
اینجا approve+post می‌شوند و پرداخت (نقدی/کارت‌خوان/کیفِ‌پول/کارتِ‌هدیه،
یا بدونِ پرداخت برایِ نسیه) واقعاً ثبت می‌شود.

طبقِ تصمیمِ صریح («ادغام فقط رویِ سندِ حسابداری باشد، نه خودِ فاکتور»):
وقتی چند فاکتورِ هم‌طرفِ‌حساب با هم انتخاب و نقد/کارت‌خوان پرداخت شوند،
فقط یک سندِ حسابداریِ واحد برایِ مجموع ساخته می‌شود (سوییچِ «ادغام»)."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
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
from peecha.ui.widgets import wrap_scrollable

_PAYMENT_OPTIONS = [
    ("NONE", "بدونِ پرداخت (نسیه)"),
    ("CASH", "نقد"),
    ("CARD", "کارت‌خوان"),
    ("WALLET", "کیفِ‌پول"),
    ("GIFT_CARD", "کارتِ‌هدیه"),
]
# طبقِ درخواستِ صریح («صندوق‌دار فقط نقد می‌تونه بزنه...»): فروشِ ثبت‌شده
# با دیالوگِ «نحوهٔ تسویه» (چندروشی: نقد/بانک/تخفیف/کالابرگ/بن) برچسبِ
# «ترکیبی» می‌گیرد؛ نیازی به انتخابِ روش در همین منویِ سرپرست ندارد
# (پایین‌تر، پیشِ خواندنِ نقشهٔ تسویه‌یِ خودِ سند تشخیص داده می‌شود).
_PAYMENT_TYPE_LABELS = {"CASH": "نقدی", "CREDIT": "نسیه", "MIXED": "ترکیبی"}
_MERGEABLE_METHODS = ("CASH", "CARD")


class CommercialPosApprovalScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._documents: list = []

        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(10)

        title = QLabel("تاییدِ سرپرست — فروش‌هایِ حضوری")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        hint = QLabel("فاکتورهایی که صندوق‌دار تایید کرده و منتظرِ تاییدِ نهایی/ثبتِ سندِ حسابداری‌اند.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        header_row = QHBoxLayout()
        refresh_button = QPushButton("🔄")
        refresh_button.setObjectName("iconButton")
        refresh_button.setFixedWidth(44)
        refresh_button.setToolTip("به‌روزرسانیِ فهرست")
        refresh_button.clicked.connect(self.refresh)
        header_row.addWidget(refresh_button)
        select_all_button = QPushButton("انتخابِ همه")
        select_all_button.setObjectName("flatButton")
        select_all_button.clicked.connect(lambda: self._set_all_checked(True))
        header_row.addWidget(select_all_button)
        clear_selection_button = QPushButton("لغوِ انتخاب")
        clear_selection_button.setObjectName("flatButton")
        clear_selection_button.clicked.connect(lambda: self._set_all_checked(False))
        header_row.addWidget(clear_selection_button)
        header_row.addStretch(1)
        outer.addLayout(header_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["انتخاب", "شمارهٔ سند", "طرفِ‌حساب", "تاریخ", "مبلغ", "نوعِ اعلامی"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        outer.addWidget(self.table, stretch=1)

        action_row = QHBoxLayout()
        action_row.addWidget(QLabel("روشِ پرداخت"))
        self.method_combo = QComboBox()
        for code, label in _PAYMENT_OPTIONS:
            self.method_combo.addItem(label, code)
        action_row.addWidget(self.method_combo)
        action_row.addWidget(QLabel("مرجع/کدِ کارتِ‌هدیه"))
        self.reference_field = QLineEdit()
        action_row.addWidget(self.reference_field, stretch=1)
        self.merge_checkbox = QCheckBox("ادغامِ سندِ حسابداری (یک سند برایِ همه‌یِ انتخاب‌شده‌ها)")
        self.merge_checkbox.setChecked(True)
        action_row.addWidget(self.merge_checkbox)
        outer.addLayout(action_row)

        self.selected_total_label = QLabel("جمعِ انتخاب‌شده‌ها: ۰")
        self.selected_total_label.setObjectName("sectionTitle")
        outer.addWidget(self.selected_total_label)

        approve_button = QPushButton("✅ تاییدِ نهایی و ثبتِ انتخاب‌شده‌ها")
        approve_button.setObjectName("primaryIconButton")
        approve_button.clicked.connect(self._approve_selected)
        outer.addWidget(approve_button, alignment=Qt.AlignLeft)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(wrap_scrollable(page))

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self.status_label.setText("")
        confirmed_docs = documents_service.list_documents(company_id, "SALES_INVOICE", "CONFIRMED")
        # فقط اسنادِ واقعاً POS-محور (pos_session_id دارند) اینجا نشان
        # داده می‌شوند -- سندهایِ CONFIRMEDِ دستیِ غیرِ POS ربطی به این
        # صفِ تاییدِ سرپرست ندارند.
        self._documents = [d for d in confirmed_docs if d.pos_session_id is not None]
        self.table.setRowCount(len(self._documents))
        for row_index, doc in enumerate(self._documents):
            checkbox = QCheckBox()
            checkbox.stateChanged.connect(self._update_selected_total)
            checkbox_holder = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_holder)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            checkbox_layout.setAlignment(Qt.AlignCenter)
            checkbox_layout.addWidget(checkbox)
            self.table.setCellWidget(row_index, 0, checkbox_holder)
            counterparty_label = dimensions_service.get_detail_account_label(doc.counterparty_detail_account_id)
            payment_type_label = _PAYMENT_TYPE_LABELS.get(doc.pos_intended_payment_type, "—")
            values = [
                str(doc.document_no or doc.document_id), counterparty_label,
                numerals.format_jalali_date(doc.document_date), numerals.format_company_amount(doc.total_amount),
                payment_type_label,
            ]
            for value_index, value in enumerate(values):
                self.table.setItem(row_index, value_index + 1, QTableWidgetItem(value))
        self._update_selected_total()

    def _row_checkbox(self, row_index: int) -> QCheckBox | None:
        holder = self.table.cellWidget(row_index, 0)
        if holder is None:
            return None
        return holder.findChild(QCheckBox)

    def _set_all_checked(self, checked: bool) -> None:
        for row_index in range(self.table.rowCount()):
            checkbox = self._row_checkbox(row_index)
            if checkbox is not None:
                checkbox.setChecked(checked)

    def _selected_documents(self) -> list:
        selected = []
        for row_index, doc in enumerate(self._documents):
            checkbox = self._row_checkbox(row_index)
            if checkbox is not None and checkbox.isChecked():
                selected.append(doc)
        return selected

    def _update_selected_total(self, *_args) -> None:
        selected = self._selected_documents()
        total = sum((d.total_amount for d in selected), decimal.Decimal("0"))
        self.selected_total_label.setText(f"جمعِ انتخاب‌شده‌ها: {numerals.format_company_amount(total)}")

    def _approve_selected(self) -> None:
        selected = self._selected_documents()
        if not selected:
            self.status_label.setText("حداقل یک فاکتور انتخاب کنید.")
            return
        method_code = self.method_combo.currentData()
        company_id = self._company_id()

        # طبقِ درخواستِ صریح («صندوق‌دار فقط نقد می‌تونه بزنه، بانکی/سایرِ
        # روش‌ها را نمی‌تونه ثبت کنه»): فاکتورهایی که صندوق‌دار از دیالوگِ
        # «نحوهٔ تسویه» (نه دو دکمهٔ نقدی/نسیه) استفاده کرده، از پیش یک
        # نقشهٔ تسویهٔ چندروشی دارند -- این‌ها دیگر از منویِ تک‌روشیِ
        # سرپرست (نقد/کارت/کیف‌پول/...) پیروی نمی‌کنند، بلکه دقیقاً همان
        # ترکیبِ ازپیش‌تعیین‌شده ثبت می‌شود؛ پس هم از بررسیِ ادغام و هم از
        # منطقِ متدِ تکی زیر جدا و پیشاپیش کنار گذاشته می‌شوند.
        with_plan = []
        without_plan = []
        for doc in selected:
            plan = settlements_service.get_settlement_plan(doc.document_id, company_id)
            if plan is not None and plan.lines:
                with_plan.append((doc, plan))
            else:
                without_plan.append(doc)

        distinct_counterparties = {d.counterparty_detail_account_id for d in without_plan}
        if method_code in _MERGEABLE_METHODS and self.merge_checkbox.isChecked() and len(distinct_counterparties) > 1:
            self.status_label.setText(
                "ادغامِ سندِ حسابداری فقط برایِ فاکتورهایِ یک طرفِ‌حساب ممکن است -- "
                "یا ادغام را خاموش کنید، یا فقط فاکتورهایِ یک طرفِ‌حساب را انتخاب کنید."
            )
            return
        if method_code == "GIFT_CARD" and without_plan and not self.reference_field.text().strip():
            self.status_label.setText("کدِ کارتِ‌هدیه را وارد کنید.")
            return

        user_id = app_session.current_user.user_id
        reference = self.reference_field.text().strip() or None
        try:
            for doc in selected:
                documents_service.approve_document(doc.document_id, company_id)
                documents_service.post_document(doc.document_id, company_id, user_id)

            for doc, plan in with_plan:
                pos_service.record_mixed_payment_and_settle(
                    company_id, user_id, doc.document_id,
                    [(ln.method_code, ln.amount, ln.note) for ln in plan.lines], reference_no=reference,
                )

            if method_code != "NONE" and without_plan:
                if method_code in _MERGEABLE_METHODS and self.merge_checkbox.isChecked() and len(without_plan) > 1:
                    pos_service.record_payment_and_settle_batch(
                        company_id, user_id, [d.document_id for d in without_plan], method_code, reference_no=reference,
                    )
                else:
                    for doc in without_plan:
                        pos_service.record_payment_and_settle(
                            company_id, user_id, doc.document_id, method_code, doc.total_amount, reference_no=reference,
                        )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("")
        self.reference_field.clear()
        self.refresh()
