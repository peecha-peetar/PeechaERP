"""تاییدِ انبار و توزین -- طبقِ درخواستِ صریحِ کاربر (روالِ کاملِ پخشِ سرد):
سفارشِ تصویب‌شده (کانالِ پخشِ سرد) باید پیش از تبدیل به فاکتورِ فروش، هم
تاییدِ انبار بگیرد و هم -- اگر کالایِ توزینی داشت -- تاییدِ توزین. این
صفحه صرفاً دو صفِ انتظار (انبار/توزین) با یک دکمهٔ تاییدِ ساده است --
خودِ «تبدیل به فاکتور» همچنان از فهرستِ اسنادِ همان تب (پخشِ سرد) با
دکمهٔ همیشگی انجام می‌شود؛ آن دکمه فقط بعدِ عبور از این دو تایید فعال
واقعاً کار می‌کند (commercial_documents.convert_to_invoice خودش هم این
دو گیت را دوباره بررسی می‌کند)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
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
from peecha.ui.widgets import FieldHelpMixin

_COLUMNS = ["شماره", "تاریخ", "طرفِ‌حساب", "جمعِ کل", "عملیات"]


class PreSalesFulfillmentScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._warehouse_pending: list = []
        self._weighing_pending: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(14)

        title = QLabel("تاییدِ انبار و توزین -- سفارش‌هایِ پخشِ سرد")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        hint = QLabel(
            "فقط سفارش‌هایِ تصویب‌شده‌یِ کانالِ «پخشِ سرد» این‌جا می‌آیند. سفارش ابتدا باید از انبار تایید شود؛ "
            "اگر حداقل یک کالایِ توزینی (ترازویی) داشته باشد، بعد از تاییدِ انبار باید توزین/تایید هم بشود -- "
            "تازه بعدِ آن «تبدیل به فاکتور» (از فهرستِ اسنادِ همین تب) قابلِ‌انجام است."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        warehouse_title = QLabel("در انتظارِ تاییدِ انبار")
        warehouse_title.setObjectName("sectionTitle")
        layout.addWidget(warehouse_title)
        self.warehouse_table = self._build_table()
        layout.addWidget(self.warehouse_table, stretch=1)

        weighing_title = QLabel("در انتظارِ توزین (کالایِ ترازویی دارند)")
        weighing_title.setObjectName("sectionTitle")
        layout.addWidget(weighing_title)
        self.weighing_table = self._build_table()
        layout.addWidget(self.weighing_table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.set_field_help([
            (self.warehouse_table, "سفارش‌هایِ پخشِ سردِ تصویب‌شده‌ای که هنوز واحدِ انبار آماده‌بودنِ کالا را تایید نکرده."),
            (self.weighing_table, "سفارش‌هایِ تاییدشده‌یِ انبار که حداقل یک کالایِ ترازویی دارند و هنوز توزین/تایید نشده‌اند."),
        ])

    def _build_table(self) -> QTableWidget:
        table = QTableWidget(0, len(_COLUMNS))
        table.setHorizontalHeaderLabels(_COLUMNS)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.setMinimumHeight(120)
        return table

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self.status_label.setText("")
        self._warehouse_pending = documents_service.list_pre_sales_pending_warehouse_approval(company_id)
        self._weighing_pending = documents_service.list_pre_sales_pending_weighing_approval(company_id)
        self._fill_table(self.warehouse_table, self._warehouse_pending, self._approve_warehouse)
        self._fill_table(self.weighing_table, self._weighing_pending, self._approve_weighing)

    def _fill_table(self, table: QTableWidget, docs: list, action) -> None:
        table.setRowCount(len(docs))
        for row_index, doc in enumerate(docs):
            values = [
                numerals.to_persian_digits(str(doc.document_no)),
                numerals.format_jalali_date(doc.document_date),
                dimensions_service.get_detail_account_label(doc.counterparty_detail_account_id),
                numerals.format_money(doc.total_amount, 0),
            ]
            for col_index, value in enumerate(values):
                table.setItem(row_index, col_index, QTableWidgetItem(value))
            button = QPushButton("✅ تایید")
            button.setObjectName("primaryButton")
            button.clicked.connect(lambda _checked=False, document_id=doc.document_id: action(document_id))
            table.setCellWidget(row_index, len(_COLUMNS) - 1, button)
        table.resizeRowsToContents()

    def _approve_warehouse(self, document_id: int) -> None:
        company_id = self._company_id()
        try:
            documents_service.approve_warehouse(document_id, company_id, app_session.current_user.user_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()

    def _approve_weighing(self, document_id: int) -> None:
        company_id = self._company_id()
        try:
            documents_service.approve_weighing(document_id, company_id, app_session.current_user.user_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
