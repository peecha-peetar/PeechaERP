"""فهرستِ اسنادِ عملیاتیِ انبار — فیلترِ نوع/وضعیت، بازکردنِ سندِ انتخاب‌شده
در فرمِ مخصوصِ همان نوع (inventory_document.py)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
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
from peecha.services import inventory_documents as documents_service
from peecha.services import inventory_locations as locations_service
from peecha.ui.screens.inventory_document import DOC_TYPE_TITLES, STATUS_LABELS

_COLUMNS = ["ردیف", "نوع", "شماره", "تاریخ", "انبارِ مبدا", "انبارِ مقصد", "وضعیت", "شمارهٔ مرجع", "عملیات"]

_TYPE_TO_SCREEN = {
    "RECEIPT": "inventory_document_receipt",
    "ISSUE": "inventory_document_issue",
    "TRANSFER": "inventory_document_transfer",
    "RETURN_IN": "inventory_document_return_in",
    "RETURN_OUT": "inventory_document_return_out",
    "ADJUSTMENT": "inventory_document_adjustment",
}


class InventoryDocumentsListScreen(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__()
        self._main_window = main_window
        self._rows: list[documents_service.StockDocumentRow] = []
        self._warehouses_by_id: dict[int, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)

        title = QLabel("اسنادِ انبار")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("نوع"))
        self.type_filter = QComboBox()
        self.type_filter.addItem("(همه)", None)
        for code, label in DOC_TYPE_TITLES.items():
            self.type_filter.addItem(label, code)
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
        for code, label in DOC_TYPE_TITLES.items():
            button = QPushButton(f"➕ {label}")
            button.setObjectName("primaryButton")
            button.setToolTip(f"سندِ {label}یِ تازه")
            button.clicked.connect(lambda _checked=False, c=code: self._open_new(c))
            new_buttons.addWidget(button)
        layout.addLayout(new_buttons)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
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
        self._warehouses_by_id = {w.warehouse_id: w.name for w in locations_service.list_warehouses(company_id)}
        self._rows = documents_service.list_stock_documents(
            company_id, document_type_code=self.type_filter.currentData(), status_code=self.status_filter.currentData()
        )
        self.table.setRowCount(len(self._rows))
        for row_index, d in enumerate(self._rows):
            values = [
                str(row_index + 1),
                DOC_TYPE_TITLES.get(d.document_type_code, d.document_type_code),
                numerals.to_persian_digits(str(d.document_no)),
                numerals.format_jalali_date(d.document_date),
                self._warehouses_by_id.get(d.source_warehouse_id, "—"),
                self._warehouses_by_id.get(d.destination_warehouse_id, "—"),
                STATUS_LABELS.get(d.status_code, d.status_code),
                d.reference_no or "—",
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, d.stock_document_id)
                self.table.setItem(row_index, col_index, item)
            self.table.setCellWidget(row_index, len(_COLUMNS) - 1, self._build_row_actions(d))

    def _build_row_actions(self, d: documents_service.StockDocumentRow) -> QWidget:
        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(4, 2, 4, 2)
        actions_layout.setSpacing(4)

        edit_button = QPushButton("✏️")
        edit_button.setObjectName("iconButton")
        edit_button.setFixedWidth(36)
        edit_button.setToolTip("اصلاح" if d.status_code == "DRAFT" else "مشاهده")
        edit_button.clicked.connect(lambda _checked=False, doc_id=d.stock_document_id: self._open_existing(doc_id))
        actions_layout.addWidget(edit_button)

        delete_button = QPushButton("🗑️")
        delete_button.setObjectName("dangerIconButton")
        delete_button.setFixedWidth(36)
        is_admin = bool(app_session.current_user and app_session.current_user.is_super_admin)
        if d.posted_at is None:
            # هرگز ثبتِ‌نهایی نشده (DRAFT/CONFIRMED/لغوشدهٔ پیش از ثبت) —
            # هیچ ردیفی در دفترِ انبار ندارد، پس حذفِ مستقیم بی‌خطر است.
            delete_button.setToolTip("حذفِ سند")
            delete_button.clicked.connect(lambda _checked=False, doc_id=d.stock_document_id: self._delete_document(doc_id))
        elif d.status_code == "POSTED" and is_admin:
            delete_button.setToolTip(
                "حذفِ سندِ ثبت‌شده (مدیر): یک سندِ برگشتیِ خودکار ساخته می‌شود تا اثرش را خنثی کند، "
                "سپس خودِ این سند «لغوشده» علامت می‌خورد."
            )
            delete_button.clicked.connect(lambda _checked=False, doc_id=d.stock_document_id: self._reverse_and_delete_document(doc_id))
        elif d.status_code == "POSTED":
            delete_button.setEnabled(False)
            delete_button.setToolTip(
                "این سند ثبتِ‌نهایی شده و اثری در دفترِ انبار/حسابداری دارد — فقط مدیرِ سیستم می‌تواند "
                "آن را (با ساختِ خودکارِ سندِ برگشتی) حذف کند."
            )
        else:
            delete_button.setEnabled(False)
            delete_button.setToolTip("اثرِ این سند قبلاً با یک سندِ برگشتیِ خودکار خنثی و خودش لغو شده است.")
        actions_layout.addWidget(delete_button)
        actions_layout.addStretch(1)
        return actions

    def _open_new(self, document_type_code: str) -> None:
        screen_code = _TYPE_TO_SCREEN[document_type_code]
        self._main_window.open_screen(screen_code, then=lambda screen: screen._reset_form())

    def _open_existing(self, stock_document_id: int) -> None:
        doc = next((d for d in self._rows if d.stock_document_id == stock_document_id), None)
        if doc is None:
            return
        screen_code = _TYPE_TO_SCREEN[doc.document_type_code]
        self._main_window.open_screen(screen_code, then=lambda screen: screen.edit_document(stock_document_id))

    def _delete_document(self, stock_document_id: int) -> None:
        confirm = QMessageBox.question(
            self, "حذف", "این سندِ پیش‌نویس حذف شود؟ این کار قابلِ‌بازگشت نیست.", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        company_id = self._company_id()
        if company_id is None:
            return
        try:
            documents_service.delete_stock_document(stock_document_id, company_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _reverse_and_delete_document(self, stock_document_id: int) -> None:
        confirm = QMessageBox.question(
            self, "حذفِ سندِ ثبت‌شده",
            "این سند قبلاً در دفترِ انبار و حسابداری اثر گذاشته — حذفِ مستقیمِ آن ممکن نیست.\n"
            "به‌جایش یک سندِ برگشتیِ خودکار ساخته و ثبتِ‌نهایی می‌شود تا اثرش خنثی شود، سپس خودِ این سند "
            "«لغوشده» علامت می‌خورد.\n\nادامه می‌دهید؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        company_id = self._company_id()
        if company_id is None or app_session.current_user is None:
            return
        try:
            documents_service.reverse_and_cancel_stock_document(
                stock_document_id, company_id, app_session.current_user.user_id
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _on_row_double_clicked(self, row: int, _column: int) -> None:
        stock_document_id = self.table.item(row, 0).data(Qt.UserRole)
        self._open_existing(stock_document_id)
