"""تسعیر/اصلاحِ ماندهٔ ریالیِ موجودیِ صفر -- R230.

کالاهایی که موجودیِ تعدادیشان صفر است ولی حسابِ موجودی (به تفکیکِ تفصیلیِ
کالا) هنوز مانده دارد فهرست می‌شوند؛ با انتخاب، یک سندِ اصلاحی به حسابِ
«تسعیر/اصلاحِ ماندهٔ ریالی» (تنظیماتِ انبار ‹ نگاشتِ حساب‌ها) صادر می‌شود.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from peecha import numerals, session as app_session
from peecha.services import inventory_engine as engine_service
from peecha.services import inventory_residual as residual_service
from peecha.ui.widgets import persist_column_widths

_COLUMNS = ["کالا", "موجودیِ تعدادی", "ارزشِ موجودی (انبار)", "ماندهٔ دفترِ کل", "انحراف"]


class InventoryResidualScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[residual_service.ResidualRow] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)
        title = QLabel("تسعیر/اصلاحِ ماندهٔ ریالیِ موجودیِ صفر")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        hint = QLabel(
            "کالاهایی که تعدادشان صفر است ولی حسابِ موجودی در دفترِ کل هنوز مانده دارد. "
            "انحراف با سندِ اصلاحی به حسابِ «تسعیر/اصلاحِ ماندهٔ ریالی» بسته می‌شود."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.account_label = QLabel()
        layout.addWidget(self.account_label)
        # R231: ابعادِ الزامیِ دیگرِ حساب‌ها (مرکزِ هزینه/پروژه...) برایِ سندِ تسعیر
        self.dims_layout = QHBoxLayout()
        layout.addLayout(self.dims_layout)
        self._dim_combos: dict[int, QComboBox] = {}

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        persist_column_widths(self.table, "inventoryResidual", skip_columns=(0,))
        layout.addWidget(self.table, stretch=1)

        buttons = QHBoxLayout()
        self.post_button = QPushButton("صدورِ سندِ اصلاحی برایِ ردیف‌هایِ انتخاب‌شده")
        self.post_button.setObjectName("primaryButton")
        self.post_button.clicked.connect(self._post_selected)
        select_all = QPushButton("انتخابِ همه")
        select_all.clicked.connect(self.table.selectAll)
        reload_button = QPushButton("بازخوانی")
        reload_button.clicked.connect(self.refresh)
        buttons.addWidget(self.post_button)
        buttons.addWidget(select_all)
        buttons.addWidget(reload_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        counter_id, key = residual_service.counter_account_id(company_id)
        if counter_id is None:
            self.account_label.setText("⚠ حسابِ مقابل تعریف نشده -- تنظیماتِ انبار ‹ نگاشتِ حساب‌ها ‹ «تسعیر/اصلاحِ ماندهٔ ریالیِ موجودیِ صفر».")
        else:
            self.account_label.setText(f"حسابِ مقابل: {engine_service.MAPPING_LABELS.get(key, key)}")
        if not residual_service.inventory_account_tracks_items(company_id):
            self.account_label.setText(
                self.account_label.text() + "\n⚠ تفصیلیِ «کالا» رویِ معینِ موجودیِ کالا الزامی نیست؛ "
                "ماندهٔ ریالی به تفکیکِ کالا قابلِ‌تشخیص نیست (ساختارِ حساب‌ها ‹ معینِ موجودی ‹ تفصیلی‌ها)."
            )
        self._build_dimension_pickers(company_id)
        self._rows = residual_service.list_residuals(company_id)
        self.table.setRowCount(len(self._rows))
        for r, row in enumerate(self._rows):
            values = [
                numerals.to_persian_digits(row.item_label), numerals.format_money(row.quantity_on_hand, 3),
                numerals.format_money(row.stock_value), numerals.format_money(row.ledger_balance),
                numerals.format_money(row.residual),
            ]
            for c, v in enumerate(values):
                cell = QTableWidgetItem(v)
                cell.setData(Qt.UserRole, row.item_id)
                self.table.setItem(r, c, cell)
        self.post_button.setEnabled(bool(self._rows))

    def _build_dimension_pickers(self, company_id: int) -> None:
        previous = {k: c.currentData() for k, c in self._dim_combos.items()}
        while self.dims_layout.count():
            widget = self.dims_layout.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        self._dim_combos = {}
        from peecha.services import detail_dimensions as dimensions_service

        for dim in residual_service.required_extra_dimensions(company_id):
            label = dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(dim.code, dim.code)
            self.dims_layout.addWidget(QLabel(label))
            combo = QComboBox()
            combo.addItem("(انتخاب کنید)", None)
            for row in dim.detail_accounts:
                combo.addItem(numerals.to_persian_digits(f"{row.full_code or row.code} — {row.name or ''}"), row.detail_account_id)
            combo.setCurrentIndex(max(0, combo.findData(previous.get(dim.dimension_type_id))))
            self.dims_layout.addWidget(combo, stretch=1)
            self._dim_combos[dim.dimension_type_id] = combo

    def _post_selected(self) -> None:
        company_id = self._company_id()
        if company_id is None or app_session.current_user is None:
            return
        item_ids = sorted({self._rows[i.row()].item_id for i in self.table.selectionModel().selectedRows()})
        if not item_ids:
            QMessageBox.information(self, "تسعیر", "ابتدا ردیف‌ها را انتخاب کنید.")
            return
        missing = [i for i, c in self._dim_combos.items() if c.currentData() is None]
        if missing:
            QMessageBox.warning(self, "تسعیر", "تفصیلی‌هایِ الزامیِ بالایِ جدول (مثلاً مرکزِ هزینه/پروژه) را انتخاب کنید.")
            return
        try:
            je_id = residual_service.post_residual_adjustment(
                company_id, app_session.current_user.user_id, item_ids,
                extra_details={i: c.currentData() for i, c in self._dim_combos.items()},
            )
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        QMessageBox.information(self, "تسعیر", f"سندِ اصلاحی صادر شد (شناسهٔ سند {numerals.to_persian_digits(str(je_id))}).")
        self.refresh()
