"""تاییدِ سرپرست برایِ فروش‌هایِ حضوری (POS، مرحلهٔ ۸) — فاکتورهایی که
کاریر فقط confirm کرده‌اند (پرداختِ واقعی/سندِ حسابداری هنوز ثبت نشده)
اینجا approve+post می‌شوند و پرداخت واقعاً ثبت می‌شود.

طبقِ رفعِ باگِ واقعیِ گزارش‌شده («فروشِ نقدیِ تسویه‌شده، در تاییدِ
سرپرست نسیه در نظر گرفته می‌شود») و درخواستِ صریحِ همراهش («هر فاکتور
طبقِ خودش تسویه بشه، نه یک روشِ واحد برایِ کلِ دسته»): این صفحه دیگر
یک کمبویِ سراسریِ «روشِ پرداخت» ندارد که رویِ همه‌یِ فاکتورهایِ
بدونِ‌نقشه اعمال شود -- چنین کمبویی پیش‌فرضش «بدونِ پرداخت (نسیه)» بود
و اگر سرپرست فراموش می‌کرد آن را عوض کند، حتی فروشِ نقدیِ واقعی هم
نسیه ثبت می‌شد. حالا هر فاکتورِ بدونِ‌نقشه دقیقاً طبقِ چیزی که خودِ
صندوق‌دار در فروشِ حضوری زده (pos_intended_payment_type: نقدی یا
نسیه) خودکار تسویه می‌شود -- بدونِ نیاز به هیچ انتخابِ دستی.

طبقِ تصمیمِ صریح («ادغام فقط رویِ سندِ حسابداری باشد، نه خودِ فاکتور»):
وقتی چند فاکتورِ هم‌طرفِ‌حساب با هم انتخاب شوند و تیکِ «ادغام» فعال
باشد، فقط یک سندِ حسابداریِ واحد برایِ مجموع ساخته می‌شود -- چه فاکتور
از پیش پلنِ تسویهٔ چندروشیِ خودش را داشته باشد (از دیالوگِ «نحوهٔ
تسویه»/اصلاحِ سند)، چه فقط نقدیِ ساده باشد؛ خودِ فاکتورها دست‌نخورده و
جدا می‌مانند، هرکدام فقط یک ردیفِ تسویه به همان یک سندِ حسابداری
می‌گیرد."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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
from peecha.ui import theme
from peecha.ui.widgets import FieldHelpMixin, wrap_scrollable

# طبقِ درخواستِ صریح («صندوق‌دار فقط نقد می‌تونه بزنه...»): فروشِ ثبت‌شده
# با دیالوگِ «نحوهٔ تسویه» (چندروشی: نقد/بانک/تخفیف/کالابرگ/بن) برچسبِ
# «ترکیبی» می‌گیرد؛ نیازی به انتخابِ روش در همین منویِ سرپرست ندارد
# (پایین‌تر، پیشِ خواندنِ نقشهٔ تسویه‌یِ خودِ سند تشخیص داده می‌شود).
_PAYMENT_TYPE_LABELS = {"CASH": "نقدی", "CREDIT": "نسیه", "MIXED": "ترکیبی"}


class CommercialPosApprovalScreen(FieldHelpMixin, QWidget):
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
        action_row.addWidget(QLabel("مرجع/توضیح"))
        self.reference_field = QLineEdit()
        self.reference_field.setToolTip("اختیاری -- مثلاً شمارهٔ پیگیریِ بانک؛ رویِ همه‌یِ فاکتورهایِ تسویه‌شده در همین دسته اعمال می‌شود.")
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

        self.set_field_help([
            (self.reference_field, "اختیاری -- مثلاً شمارهٔ پیگیریِ بانک؛ رویِ همه‌یِ فاکتورهایِ تسویه‌شده در همین دسته اعمال می‌شود."),
            (
                self.merge_checkbox,
                "وقتی روشن است و چند فاکتورِ هم‌طرفِ‌حساب انتخاب شده باشند، فقط یک سندِ حسابداریِ واحد برایِ مجموع ساخته می‌شود -- خودِ فاکتورها جدا می‌مانند.",
            ),
        ])

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
        company_id = self._company_id()
        user_id = app_session.current_user.user_id

        # طبقِ درخواستِ صریح («وقتی هنگامِ تاییدِ سرپرست انبار موجودی
        # ندارد، اتوماتیک انتقالِ انبار صادر کند تا انباردار تاییدش
        # کند»): پیش از هرگونه approve/post، هر فاکتورِ انتخاب‌شده از
        # نظرِ کمبودِ موجودی بررسی می‌شود. فاکتورِ کم‌موجود این‌جا approve/
        # post نمی‌شود (تا در post_document با شکستِ گنگ بن‌بست نشود) --
        # فقط سندِ انتقالِ جبرانی (اگر انبارِ دیگری موجودیِ کافی داشت)
        # صادر می‌شود و فاکتور همچنان CONFIRMED می‌ماند تا بعد از تاییدِ
        # انباردار، سرپرست دوباره همین دکمه را برایِ آن بزند.
        shortage_messages: list[str] = []
        ready_for_approval = []
        for doc in selected:
            shortages = documents_service.get_stock_shortages(doc.document_id, company_id)
            if not shortages:
                ready_for_approval.append(doc)
                continue
            doc_label = doc.document_no or doc.document_id
            for shortage in shortages:
                transfer_doc_id = documents_service.create_compensating_transfer(company_id, user_id, shortage)
                if transfer_doc_id is not None:
                    shortage_messages.append(
                        f"فاکتور #{doc_label}: کمبودِ «{shortage.item_label}» در انبارِ «{shortage.warehouse_label}» -- "
                        f"سندِ انتقالِ انبار #{transfer_doc_id} صادر شد؛ پس از تاییدِ انباردار، دوباره تایید کنید."
                    )
                else:
                    shortage_messages.append(
                        f"فاکتور #{doc_label}: کمبودِ «{shortage.item_label}» در انبارِ «{shortage.warehouse_label}» -- "
                        "هیچ انبارِ دیگری هم موجودیِ کافی ندارد؛ ابتدا موجودی را (رسید/تعدیل) تامین کنید."
                    )
        selected = ready_for_approval
        if not selected:
            theme.set_status_label(self.status_label, " | ".join(shortage_messages), ok=False)
            return

        # فاکتورهایی که صندوق‌دار از دیالوگِ «نحوهٔ تسویه» (نه دو دکمهٔ
        # نقدی/نسیه) استفاده کرده، از پیش یک نقشهٔ تسویهٔ چندروشی
        # دارند -- دقیقاً همان ترکیبِ ازپیش‌تعیین‌شده ثبت می‌شود.
        with_plan = []
        without_plan = []
        for doc in selected:
            plan = settlements_service.get_settlement_plan(doc.document_id, company_id)
            if plan is not None and plan.lines:
                with_plan.append((doc, plan))
            else:
                without_plan.append(doc)

        # طبقِ رفعِ باگِ واقعیِ گزارش‌شده («فروشِ نقدیِ تسویه‌شده در تاییدِ
        # سرپرست نسیه در نظر گرفته می‌شود») + درخواستِ صریح («هر فاکتور
        # طبقِ خودش تسویه بشه»): دیگر هیچ روشِ واحدِ دستی‌انتخاب‌شده‌ای
        # رویِ این فاکتورها اعمال نمی‌شود -- هرکدام دقیقاً طبقِ همان
        # چیزی که خودِ صندوق‌دار در فروشِ حضوری زده (pos_intended_
        # payment_type) گروه‌بندی می‌شود: نقدی خودکار تسویه می‌شود،
        # نسیه (یا نامشخص/قدیمی) بدونِ هیچ تسویه‌ای فقط approve/post
        # می‌شود -- که دقیقاً همان انتخابِ عمدیِ صندوق‌دار است.
        cash_docs = [d for d in without_plan if d.pos_intended_payment_type == "CASH"]
        credit_docs = [d for d in without_plan if d.pos_intended_payment_type != "CASH"]

        # طبقِ رفعِ باگِ گزارش‌شده («وقتی ادغامِ سند تیک می‌خورد همه‌یِ
        # اسناد باز هم جدا ثبت می‌شود»): with_plan (فاکتورهایی که از
        # دیالوگِ «نحوهٔ تسویه»/بازکردنِ اصلاحی پلنِ تسویهٔ واقعی دارند)
        # و cash_docsِ ساده -- اگر طرفِ‌حسابشان یکی باشد -- با هم در یک
        # سندِ حسابداریِ واحد ثبت می‌شوند.
        merge_checked = self.merge_checkbox.isChecked()
        merge_plan_entries: list[tuple[int, list[tuple]]] = []
        flat_batch_group: list = []
        standalone_with_plan = with_plan
        standalone_cash_docs = cash_docs

        if merge_checked and len(with_plan) > 1:
            # with_plan خودش وارد ادغام می‌شود -- در این حالت هر سند (چه
            # پلن‌دار، چه نقدیِ سادهٔ بدونِ پلن) یک ردیفِ جدا در همان یک
            # سندِ حسابداریِ مشترک می‌گیرد.
            merge_plan_entries = [
                (doc.document_id, [(ln.method_code, ln.amount, ln.note, ln.detail_account_id) for ln in plan.lines])
                for doc, plan in with_plan
            ]
            standalone_with_plan = []
            merge_plan_entries.extend((doc.document_id, [("CASH", doc.total_amount)]) for doc in cash_docs)
            standalone_cash_docs = []
        elif merge_checked and len(cash_docs) > 1:
            # طبقِ رفتارِ ازپیش‌موجود (بدونِ هیچ with_planِ ادغام‌شونده):
            # یک سندِ حسابداری با یک ردیفِ واحد برایِ مجموعِ همه ساخته
            # می‌شود -- نه یک ردیفِ جدا به‌ازایِ هر فاکتور.
            flat_batch_group = cash_docs
            standalone_cash_docs = []

        merge_doc_ids = {doc_id for doc_id, _lines in merge_plan_entries} | {d.document_id for d in flat_batch_group}
        if len(merge_doc_ids) > 1:
            merge_docs = [doc for doc in selected if doc.document_id in merge_doc_ids]
            if len({d.counterparty_detail_account_id for d in merge_docs}) > 1:
                self.status_label.setText(
                    "ادغامِ سندِ حسابداری فقط برایِ فاکتورهایِ یک طرفِ‌حساب ممکن است -- "
                    "یا ادغام را خاموش کنید، یا فقط فاکتورهایِ یک طرفِ‌حساب را انتخاب کنید."
                )
                return

        reference = self.reference_field.text().strip() or None
        try:
            for doc in selected:
                documents_service.approve_document(doc.document_id, company_id)
                documents_service.post_document(doc.document_id, company_id, user_id)

            if merge_plan_entries:
                pos_service.record_combined_settlement(
                    company_id, user_id, merge_plan_entries, reference_no=reference,
                )

            if flat_batch_group:
                pos_service.record_payment_and_settle_batch(
                    company_id, user_id, [d.document_id for d in flat_batch_group], "CASH",
                    reference_no=reference,
                )

            for doc, plan in standalone_with_plan:
                pos_service.record_mixed_payment_and_settle(
                    company_id, user_id, doc.document_id,
                    [(ln.method_code, ln.amount, ln.note, ln.detail_account_id) for ln in plan.lines],
                    reference_no=reference,
                )

            for doc in standalone_cash_docs:
                pos_service.record_payment_and_settle(
                    company_id, user_id, doc.document_id, "CASH", doc.total_amount, reference_no=reference,
                )

            # credit_docs عمداً بدونِ هیچ فراخوانِ تسویه می‌مانند (approve/
            # post شان از قبل، در حلقهٔ بالا رویِ selected، انجام شده) --
            # دقیقاً همان نسیه‌یِ عمدیِ صندوق‌دار.
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        if shortage_messages:
            theme.set_status_label(self.status_label, " | ".join(shortage_messages), ok=False)
        else:
            self.status_label.setText("")
        self.reference_field.clear()
        self.refresh()
