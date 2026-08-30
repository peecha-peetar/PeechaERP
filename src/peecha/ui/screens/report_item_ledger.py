"""کاردکسِ کالا -- گردشِ کاملِ یک کالا (ورود/خروج/مانده‌یِ رواگرد) طبقِ
inv.stock_ledger. طبقِ درخواستِ صریح («دکمه‌ای برایِ نمایشِ کاردکسِ کالا»)،
از فرم‌هایِ ردیفِ کالایِ اسنادِ انبار/بازرگانی هم قابلِ بازشدن است
(show_ledger_for_item)."""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
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
from peecha.reporting import jasper_bridge
from peecha.services import companies as companies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_engine as engine_service
from peecha.services import inventory_locations as locations_service
from peecha.services import report_templates as templates_service
from peecha.ui.screens.journal_entry import _fill_options, _make_searchable_combo
from peecha.ui.screens.report_template_settings import pick_report_template
from peecha.ui.widgets import JalaliDateEdit

# طبقِ درخواستِ صریح («در کاردکسِ کالا نامِ طرفِ‌حساب هم نمایش داده شود» +
# «کاردکسِ ریالی بهایِ ورودی/خروجی داشته باشد و برایِ فاکتورهایِ فروش
# ستونِ قیمتِ فروش هم باشد»): بهایِ واحد/بهایِ کل همیشه بهایِ تمام‌شده
# (COGS) است -- قیمتِ فروش، ستونِ جداگانه‌ای است که فقط برایِ خروجیِ
# آمده از فاکتورِ فروش پر می‌شود، تا بتوان حاشیهٔ سود را هم دید.
_COLUMNS = [
    "تاریخ", "نوعِ سند", "شماره‌یِ سند", "انبار", "طرفِ‌حساب", "ورود", "خروج", "بهایِ واحد",
    "بهایِ کلِ ورود", "بهایِ کلِ خروج", "قیمتِ فروش", "مانده", "مانده‌یِ ریالی",
]


class ItemLedgerScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(10)

        title = QLabel("کاردکسِ کالا")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        filters_row = QHBoxLayout()
        filters_row.addWidget(QLabel("کالا"))
        self.item_combo = _make_searchable_combo([])
        self.item_combo.currentIndexChanged.connect(self._on_filters_changed)
        filters_row.addWidget(self.item_combo, stretch=1)

        filters_row.addWidget(QLabel("انبار"))
        self.warehouse_combo = _make_searchable_combo([])
        self.warehouse_combo.currentIndexChanged.connect(self._on_filters_changed)
        filters_row.addWidget(self.warehouse_combo)

        self.date_filter_checkbox = QCheckBox("فیلترِ تاریخ")
        filters_row.addWidget(self.date_filter_checkbox)
        self.date_from_field = JalaliDateEdit()
        filters_row.addWidget(self.date_from_field)
        filters_row.addWidget(QLabel("تا"))
        self.date_to_field = JalaliDateEdit()
        filters_row.addWidget(self.date_to_field)
        self.date_from_field.setEnabled(False)
        self.date_to_field.setEnabled(False)
        self.date_filter_checkbox.toggled.connect(self._on_date_filter_toggled)

        self.print_professional_button = QPushButton("📄 گزارش")
        self.print_professional_button.setToolTip(
            "اجرایِ یکی از گزارش‌هایِ حرفه‌ایِ تخصیص‌داده‌شده به کاردکس -- "
            "برایِ تعریف/ویرایشِ گزارش‌ها به «تنظیماتِ سیستم ›  گزارش‌هایِ حرفه‌ای» مراجعه کنید."
        )
        self.print_professional_button.clicked.connect(self._print_professional)
        filters_row.addWidget(self.print_professional_button)
        layout.addLayout(filters_row)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.date_from_field.editingFinished.connect(self._on_filters_changed)
        self.date_to_field.editingFinished.connect(self._on_filters_changed)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        current_item_id = self.item_combo.currentData()
        items = catalog_service.list_items(company_id)
        _fill_options(self.item_combo, [(it.item_id, f"{it.code} — {it.name or ''}") for it in items])
        if current_item_id is not None:
            index = self.item_combo.findData(current_item_id)
            if index >= 0:
                self.item_combo.setCurrentIndex(index)

        current_warehouse_id = self.warehouse_combo.currentData()
        warehouses = locations_service.list_warehouses(company_id)
        _fill_options(self.warehouse_combo, [(w.warehouse_id, w.name) for w in warehouses])
        self.warehouse_combo.setItemText(0, "(همه‌یِ انبارها)")
        if current_warehouse_id is not None:
            index = self.warehouse_combo.findData(current_warehouse_id)
            if index >= 0:
                self.warehouse_combo.setCurrentIndex(index)

        self._refresh_table()

    def show_ledger_for_item(self, item_id: int, warehouse_id: int | None = None) -> None:
        self.refresh()
        index = self.item_combo.findData(item_id)
        if index >= 0:
            self.item_combo.setCurrentIndex(index)
        warehouse_index = self.warehouse_combo.findData(warehouse_id)
        self.warehouse_combo.setCurrentIndex(max(0, warehouse_index))
        self._refresh_table()

    def _on_date_filter_toggled(self, checked: bool) -> None:
        self.date_from_field.setEnabled(checked)
        self.date_to_field.setEnabled(checked)
        self._refresh_table()

    def _on_filters_changed(self) -> None:
        self._refresh_table()

    def _load_ledger_context(self):
        """طبقِ اشتراکِ منطق بینِ نمایشِ رویِ صفحه و چاپِ حرفه‌ای -- هردو
        باید دقیقاً همان دیتا/فرمت را ببینند، تا گزارشِ Jasper هیچ‌وقت با
        جدولِ رویِ صفحه فرق نکند."""
        company_id = self._company_id()
        item_id = self.item_combo.currentData()
        if company_id is None or item_id is None:
            return None
        warehouse_id = self.warehouse_combo.currentData()
        use_date_filter = self.date_filter_checkbox.isChecked()
        date_from = self.date_from_field.date() if use_date_filter else None
        date_to = self.date_to_field.date() if use_date_filter else None

        # طبقِ رفعِ باگِ واقعی («ارقامِ اعشار باید از تنظیمات خونده بشه»):
        # مقدار/مانده با تعدادِ رقمِ اعشارِ واحدِ شمارشِ خودِ کالا، و بهایِ
        # واحد با تعدادِ رقمِ اعشارِ ارزِ پایه‌یِ شرکت -- نه رقمِ خامِ
        # ذخیره‌شده در ستونِ Numeric.
        items_by_id = {it.item_id: it for it in catalog_service.list_items(company_id)}
        uom_decimal_places = {u.uom_id: u.decimal_places for u in catalog_service.list_uoms(company_id)}
        item = items_by_id.get(item_id)
        qty_decimals = uom_decimal_places.get(item.base_uom_id, 2) if item else 2
        cost_decimals = companies_service.get_base_currency_decimal_places(company_id)
        parties_by_id = {
            c["detail_account_id"]: f"{c['code']} — {c['name'] or ''}" for c in dimensions_service.list_customers(company_id)
        }
        parties_by_id.update(
            {s["detail_account_id"]: f"{s['code']} — {s['name'] or ''}" for s in dimensions_service.list_suppliers(company_id)}
        )

        rows = engine_service.list_item_ledger(company_id, item_id, warehouse_id, date_from, date_to)
        return {
            "item": item,
            "qty_decimals": qty_decimals,
            "cost_decimals": cost_decimals,
            "parties_by_id": parties_by_id,
            "rows": rows,
            "warehouse_id": warehouse_id,
            "date_from": date_from,
            "date_to": date_to,
        }

    def _refresh_table(self) -> None:
        self.table.setRowCount(0)
        context = self._load_ledger_context()
        if context is None:
            return

        from peecha.ui.screens.inventory_document import DOC_TYPE_TITLES

        qty_decimals = context["qty_decimals"]
        cost_decimals = context["cost_decimals"]
        parties_by_id = context["parties_by_id"]
        rows = context["rows"]
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                numerals.format_jalali_date(row.movement_date),
                DOC_TYPE_TITLES.get(row.document_type_code, row.document_type_code),
                numerals.to_persian_digits(str(row.document_no)),
                row.warehouse_name,
                parties_by_id.get(row.counterparty_detail_account_id, "—"),
                numerals.format_money(row.quantity_in, qty_decimals) if row.quantity_in else "",
                numerals.format_money(row.quantity_out, qty_decimals) if row.quantity_out else "",
                numerals.format_money(row.unit_cost, cost_decimals) if row.unit_cost is not None else "",
                numerals.format_money(row.value_in, cost_decimals) if row.value_in else "",
                numerals.format_money(row.value_out, cost_decimals) if row.value_out else "",
                numerals.format_money(row.sale_unit_price, cost_decimals) if row.sale_unit_price is not None else "",
                numerals.format_money(row.running_balance, qty_decimals),
                numerals.format_money(row.running_value_balance, cost_decimals),
            ]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col_index >= 5:
                    cell.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_index, col_index, cell)
        self.table.resizeRowsToContents()
        self.status_label.setText("" if rows else "برایِ این کالا (با این فیلترها) هیچ حرکتی ثبت نشده است.")

    def _print_professional(self) -> None:
        """طبقِ درخواستِ صریحِ کاربر («بخشِ گزارشات را حرفه‌ای کنیم»):
        همان دیتایِ رویِ صفحه را با موتورِ JasperReports (نه دیگر با
        report_export.py دستی) به PDF/Excel تبدیل می‌کند."""
        context = self._load_ledger_context()
        if context is None:
            QMessageBox.information(self, "چاپِ حرفه‌ای", "ابتدا یک کالا انتخاب کنید.")
            return
        rows = context["rows"]
        if not rows:
            QMessageBox.information(self, "چاپِ حرفه‌ای", "برایِ این کالا (با این فیلترها) هیچ حرکتی ثبت نشده است.")
            return

        company_id = self._company_id()
        template_row = pick_report_template(self, company_id, "ITEM_LEDGER")
        if template_row is None:
            return
        template_path = templates_service.get_template_path(template_row.report_template_id, company_id)

        from peecha.ui.screens.inventory_document import DOC_TYPE_TITLES

        qty_decimals = context["qty_decimals"]
        cost_decimals = context["cost_decimals"]
        parties_by_id = context["parties_by_id"]
        item = context["item"]

        print_rows = [
            {
                "movement_date_display": numerals.format_jalali_date(row.movement_date),
                "document_type_label": DOC_TYPE_TITLES.get(row.document_type_code, row.document_type_code),
                "document_no_display": numerals.to_persian_digits(str(row.document_no)),
                "warehouse_name": row.warehouse_name,
                "counterparty_label": parties_by_id.get(row.counterparty_detail_account_id, "—"),
                "quantity_in_display": numerals.format_money(row.quantity_in, qty_decimals) if row.quantity_in else "",
                "quantity_out_display": numerals.format_money(row.quantity_out, qty_decimals) if row.quantity_out else "",
                "unit_cost_display": numerals.format_money(row.unit_cost, cost_decimals) if row.unit_cost is not None else "",
                "value_in_display": numerals.format_money(row.value_in, cost_decimals) if row.value_in else "",
                "value_out_display": numerals.format_money(row.value_out, cost_decimals) if row.value_out else "",
                "sale_price_display": numerals.format_money(row.sale_unit_price, cost_decimals) if row.sale_unit_price is not None else "",
                "running_balance_display": numerals.format_money(row.running_balance, qty_decimals),
                "running_value_balance_display": numerals.format_money(row.running_value_balance, cost_decimals),
            }
            for row in rows
        ]

        company = app_session.current_company
        date_range_label = ""
        if context["date_from"] is not None and context["date_to"] is not None:
            date_range_label = (
                f"از {numerals.format_jalali_date(context['date_from'])} "
                f"تا {numerals.format_jalali_date(context['date_to'])}"
            )
        warehouse_name = self.warehouse_combo.currentText() if context["warehouse_id"] is not None else ""
        params = {
            "companyName": company.display_name if company else "",
            "itemName": f"{item.code} — {item.name or ''}" if item else "",
            "warehouseName": warehouse_name,
            "dateRangeLabel": date_range_label,
            "generatedAt": numerals.format_jalali_datetime(datetime.datetime.now()),
        }

        path, chosen_filter = QFileDialog.getSaveFileName(
            self, "ذخیره‌یِ کاردکسِ حرفه‌ای", "کاردکس.pdf", "PDF (*.pdf);;Excel (*.xlsx)"
        )
        if not path:
            return
        output_format = "xlsx" if (path.lower().endswith(".xlsx") or "xlsx" in chosen_filter) else "pdf"
        if output_format == "pdf" and not path.lower().endswith(".pdf"):
            path += ".pdf"
        elif output_format == "xlsx" and not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        try:
            jasper_bridge.render_report_at_path(template_path, print_rows, params, path, output_format)
        except jasper_bridge.JasperNotAvailableError as exc:
            QMessageBox.warning(self, "چاپِ حرفه‌ای", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "چاپِ حرفه‌ای", f"تولیدِ گزارش ناموفق بود:\n{exc}")
            return

        QMessageBox.information(self, "چاپِ حرفه‌ای", "گزارش با موفقیت ساخته شد.")
