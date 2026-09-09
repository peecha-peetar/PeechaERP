"""فروشِ تلفنی -- طبقِ درخواستِ صریحِ کاربر: پخشِ سرد از ۳ مسیر سفارش
می‌گیرد (سفارشِ عمده، سفارشِ موبایلی، و این‌جا سفارشِ تلفنی). این صفحه
فهرستِ مشتریانِ ویزیتورِ واردشده (چه ویزیتورِ مقیمِ شرکت، چه ویزیتورِ
تلفنی -- هردو از همان assigned_visitor_user_id در برنامهٔ مراجعه
استفاده می‌کنند) را نشان می‌دهد و برایِ هر مشتری امکانِ یادداشت، دیدنِ
مانده‌حساب، بازکردنِ معینِ حساب، و ثبتِ سفارش/صدورِ فاکتور (با
توضیحِ پیش‌فرضِ «سفارشِ تلفنی») را در همان صفحه فراهم می‌کند."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session as app_session
from peecha.services import companies as companies_service
from peecha.services import telesales as telesales_service
from peecha.services import treasury as treasury_service

_COLUMNS = ["کد", "نام", "ماندهٔ حساب", "آخرین یادداشت", "اقدامات"]


class _CustomerNoteDialog(QDialog):
    def __init__(self, company_id: int, customer_id: int, customer_name: str, user_id: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"یادداشت‌هایِ {customer_name}")
        self.resize(420, 420)
        self._company_id = company_id
        self._customer_id = customer_id
        self._user_id = user_id

        layout = QVBoxLayout(self)
        self.history_list = QListWidget()
        layout.addWidget(self.history_list, stretch=1)

        layout.addWidget(QLabel("یادداشتِ تازه:"))
        self.text_edit = QTextEdit()
        self.text_edit.setFixedHeight(80)
        layout.addWidget(self.text_edit)

        add_button = QPushButton("افزودنِ یادداشت")
        add_button.clicked.connect(self._add_note)
        layout.addWidget(add_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self._reload_history()

    def _reload_history(self) -> None:
        self.history_list.clear()
        for note in telesales_service.list_customer_notes(self._company_id, self._customer_id):
            text = f"{note.created_at.strftime('%Y-%m-%d %H:%M')} — {note.note_text}"
            self.history_list.addItem(QListWidgetItem(text))

    def _add_note(self) -> None:
        text = self.text_edit.toPlainText().strip()
        if not text:
            return
        telesales_service.add_customer_note(self._company_id, self._customer_id, self._user_id, text)
        self.text_edit.clear()
        self._reload_history()


class TelesalesScreen(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__()
        self._main_window = main_window
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("فروشِ تلفنی")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        hint = QLabel("فهرستِ مشتریانِ اختصاص‌یافته به شما (طبقِ برنامهٔ مراجعه) -- برایِ ویزیتورِ مقیم یا تلفنی.")
        hint.setObjectName("sectionHint")
        outer.addWidget(hint)

        header_row = QHBoxLayout()
        header_row.addStretch(1)
        refresh_button = QPushButton("🔄")
        refresh_button.setObjectName("iconButton")
        refresh_button.setFixedWidth(44)
        refresh_button.setToolTip("به‌روزرسانی")
        refresh_button.clicked.connect(self.refresh)
        header_row.addWidget(refresh_button)
        outer.addLayout(header_row)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        outer.addWidget(self.table, stretch=1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        user = app_session.current_user
        if company_id is None or user is None:
            return
        rows = telesales_service.list_assigned_customers(company_id, user.user_id)
        decimal_places = companies_service.get_base_currency_decimal_places(company_id)
        self.table.setRowCount(len(rows))
        for row_index, r in enumerate(rows):
            balance, nature = treasury_service.get_counterparty_balance(company_id, r.customer_detail_account_id)
            latest_note = telesales_service.get_latest_customer_note(company_id, r.customer_detail_account_id)
            values = [
                r.code, r.name, f"{numerals.format_money(balance, decimal_places)} ({nature})",
                latest_note.note_text if latest_note else "—",
            ]
            for col_index, value in enumerate(values):
                self.table.setItem(row_index, col_index, QTableWidgetItem(value))
            self.table.setCellWidget(row_index, len(_COLUMNS) - 1, self._build_row_actions(r, company_id, user.user_id))
        self.table.resizeColumnToContents(len(_COLUMNS) - 1)
        self.table.resizeRowsToContents()

    def _build_row_actions(self, customer, company_id: int, user_id: int) -> QWidget:
        actions = QWidget()
        layout = QHBoxLayout(actions)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        note_button = QPushButton("یادداشت")
        note_button.setToolTip("دیدن/افزودنِ یادداشت برایِ این مشتری")
        note_button.clicked.connect(
            lambda _checked=False, c=customer: self._open_notes(company_id, c.customer_detail_account_id, c.name, user_id)
        )
        layout.addWidget(note_button)

        ledger_button = QPushButton("معین")
        ledger_button.setToolTip("بازکردنِ معینِ حسابِ این مشتری")
        ledger_button.clicked.connect(lambda _checked=False, c=customer: self._open_ledger(c.customer_detail_account_id, c.name))
        layout.addWidget(ledger_button)

        order_button = QPushButton("سفارش")
        order_button.setToolTip("ثبتِ سفارشِ تلفنی برایِ این مشتری")
        order_button.clicked.connect(lambda _checked=False, c=customer: self._open_new_document("SALES_ORDER", c.customer_detail_account_id))
        layout.addWidget(order_button)

        invoice_button = QPushButton("فاکتور")
        invoice_button.setToolTip("صدورِ فاکتورِ فروش برایِ این مشتری")
        invoice_button.clicked.connect(lambda _checked=False, c=customer: self._open_new_document("SALES_INVOICE", c.customer_detail_account_id))
        layout.addWidget(invoice_button)

        return actions

    def _open_notes(self, company_id: int, customer_id: int, customer_name: str, user_id: int) -> None:
        dialog = _CustomerNoteDialog(company_id, customer_id, customer_name, user_id, self)
        dialog.exec()
        self.refresh()

    def _open_ledger(self, customer_id: int, customer_name: str) -> None:
        self._main_window.open_screen(
            "REPORTS_ACCOUNT_LEDGER", then=lambda screen: screen.show_ledger_for_detail(customer_id, customer_name),
        )

    def _open_new_document(self, nav_code: str, customer_id: int) -> None:
        # طبقِ درخواستِ صریحِ کاربر: عنوانِ پیش‌فرضِ توضیحات «سفارشِ
        # تلفنی» است تا در فهرستِ اسناد/گزارش‌ها از سفارشِ عمده یا
        # موبایلی متمایز باشد -- کاربر همچنان می‌تواند آن را ویرایش کند.
        self._main_window.open_screen(
            nav_code, then=lambda screen: screen.prefill_for_new(customer_id, description="سفارشِ تلفنی"),
        )
