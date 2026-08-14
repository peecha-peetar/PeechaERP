"""فرمِ اسنادِ عملیاتیِ انبار — رسید/حواله/انتقال/برگشت/اصلاح، همه رویِ
همان اسکلتِ سرِسند+ردیفِ inv.stock_documents/stock_document_lines
(services/inventory_documents.py) و موتورِ Postِ services/inventory_engine.py.

طبقِ اسکوپِ آگاهانهٔ این دور: تبدیلِ واحد (UOM conversion)، بچ/سریال/QC،
و ارجاعِ صریحِ برگشت به ردیفِ سندِ اصلی، به دورِ بعدی موکول شده‌اند — هر
ردیف با واحدِ پایهٔ خودِ کالا ثبت می‌شود (quantity_base = quantity)."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_documents as documents_service
from peecha.services import inventory_locations as locations_service
from peecha.ui.screens.journal_entry import _fill_options, _make_searchable_combo
from peecha import numerals
from peecha.ui.widgets import FieldHelpMixin, FormScreenBase, JalaliDateEdit, SectionStepper, SummaryCard, SummaryCardBar

DOC_TYPE_TITLES = {
    "RECEIPT": "رسید",
    "ISSUE": "حواله",
    "TRANSFER": "انتقال",
    "RETURN_IN": "برگشت از فروش",
    "RETURN_OUT": "برگشت به تامین‌کننده",
    "ADJUSTMENT": "اصلاحِ موجودی",
}
STATUS_LABELS = {"DRAFT": "پیش‌نویس", "CONFIRMED": "تاییدشده", "POSTED": "ثبتِ‌نهایی‌شده", "CANCELLED": "لغوشده"}
_LINE_COLUMNS = ["کالا", "مقدار", "مکان", "مکانِ مقصد", "بهایِ واحد", "بهایِ کل", "دلیل", "توضیح"]


class _LineDialog(QDialog):
    def __init__(
        self, parent: QWidget, document_type_code: str, items: list[catalog_service.ItemRow],
        source_bins: list[locations_service.BinLocationRow], destination_bins: list[locations_service.BinLocationRow],
        reasons: list[documents_service.ReasonCodeRow], initial: documents_service.LineFields | None = None,
    ) -> None:
        super().__init__(parent)
        self.document_type_code = document_type_code
        self.setWindowTitle("ردیفِ سند")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("کالا"))
        item_options = [(it.item_id, f"{it.code} — {it.name or ''}") for it in items]
        self.item_combo = _make_searchable_combo(item_options)
        layout.addWidget(self.item_combo)
        self._items_by_id = {it.item_id: it for it in items}

        layout.addWidget(QLabel("مقدار (واحدِ پایهٔ کالا)"))
        self.quantity_field = QDoubleSpinBox()
        self.quantity_field.setDecimals(6)
        self.quantity_field.setRange(0.000001, 999999999)
        layout.addWidget(self.quantity_field)

        self.bin_row = QWidget()
        bin_layout = QVBoxLayout(self.bin_row)
        bin_layout.setContentsMargins(0, 0, 0, 0)
        bin_layout.addWidget(QLabel("مکان"))
        self.bin_combo = QComboBox()
        self.bin_combo.addItem("(پیش‌فرضِ انبار)", None)
        for b in source_bins:
            self.bin_combo.addItem(f"{b.code} — {b.name or ''}", b.bin_location_id)
        bin_layout.addWidget(self.bin_combo)
        layout.addWidget(self.bin_row)

        self.destination_bin_row = QWidget()
        dest_bin_layout = QVBoxLayout(self.destination_bin_row)
        dest_bin_layout.setContentsMargins(0, 0, 0, 0)
        dest_bin_layout.addWidget(QLabel("مکانِ مقصد"))
        self.destination_bin_combo = QComboBox()
        self.destination_bin_combo.addItem("(پیش‌فرضِ انبار)", None)
        for b in destination_bins:
            self.destination_bin_combo.addItem(f"{b.code} — {b.name or ''}", b.bin_location_id)
        dest_bin_layout.addWidget(self.destination_bin_combo)
        layout.addWidget(self.destination_bin_row)
        self.destination_bin_row.setVisible(document_type_code == "TRANSFER")

        self.unit_cost_row = QWidget()
        cost_layout = QVBoxLayout(self.unit_cost_row)
        cost_layout.setContentsMargins(0, 0, 0, 0)
        cost_layout.addWidget(QLabel("بهایِ واحد"))
        self.unit_cost_field = QDoubleSpinBox()
        self.unit_cost_field.setDecimals(2)
        self.unit_cost_field.setRange(0, 999999999999)
        cost_layout.addWidget(self.unit_cost_field)
        layout.addWidget(self.unit_cost_row)
        self.unit_cost_row.setVisible(document_type_code in ("RECEIPT", "RETURN_IN", "ADJUSTMENT"))

        self.reason_row = QWidget()
        reason_layout = QVBoxLayout(self.reason_row)
        reason_layout.setContentsMargins(0, 0, 0, 0)
        reason_layout.addWidget(QLabel("دلیل"))
        self.reason_combo = QComboBox()
        self.reason_combo.addItem("(انتخاب کنید)", None)
        for r in reasons:
            self.reason_combo.addItem(r.name, r.reason_code_id)
        reason_layout.addWidget(self.reason_combo)
        layout.addWidget(self.reason_row)
        self.reason_row.setVisible(document_type_code in ("ADJUSTMENT", "RETURN_IN", "RETURN_OUT"))

        layout.addWidget(QLabel("توضیح"))
        self.description_field = QLineEdit()
        layout.addWidget(self.description_field)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if initial is not None:
            index = self.item_combo.findData(initial.item_id)
            if index >= 0:
                self.item_combo.setCurrentIndex(index)
            self.quantity_field.setValue(float(initial.quantity))
            if initial.bin_location_id is not None:
                self.bin_combo.setCurrentIndex(max(0, self.bin_combo.findData(initial.bin_location_id)))
            if initial.destination_bin_location_id is not None:
                self.destination_bin_combo.setCurrentIndex(max(0, self.destination_bin_combo.findData(initial.destination_bin_location_id)))
            if initial.unit_cost is not None:
                self.unit_cost_field.setValue(float(initial.unit_cost))
            if initial.reason_code_id is not None:
                self.reason_combo.setCurrentIndex(max(0, self.reason_combo.findData(initial.reason_code_id)))
            self.description_field.setText(initial.description or "")

    def _on_accept(self) -> None:
        if self.item_combo.currentData() is None:
            self.status_label.setText("کالا را انتخاب کنید.")
            return
        if self.reason_row.isVisible() and self.reason_combo.currentData() is None:
            self.status_label.setText("انتخابِ دلیل الزامی است.")
            return
        self.accept()

    def result_fields(self) -> documents_service.LineFields:
        item_id = self.item_combo.currentData()
        item = self._items_by_id.get(item_id)
        quantity = decimal.Decimal(str(self.quantity_field.value()))
        unit_cost = decimal.Decimal(str(self.unit_cost_field.value())) if self.unit_cost_row.isVisible() and self.unit_cost_field.value() > 0 else None
        return documents_service.LineFields(
            item_id=item_id, uom_id=item.base_uom_id if item else 0, quantity=quantity, quantity_base=quantity,
            bin_location_id=self.bin_combo.currentData(),
            destination_bin_location_id=self.destination_bin_combo.currentData() if self.destination_bin_row.isVisible() else None,
            unit_cost=unit_cost,
            reason_code_id=self.reason_combo.currentData() if self.reason_row.isVisible() else None,
            description=self.description_field.text().strip() or None,
        )


class InventoryDocumentScreen(FieldHelpMixin, FormScreenBase):
    def __init__(self, document_type_code: str, main_window) -> None:
        super().__init__()
        self.document_type_code = document_type_code
        self._main_window = main_window
        self._document_id: int | None = None
        self._status_code = "DRAFT"
        self._lines: list[documents_service.StockDocumentLineRow] = []
        self._items: list[catalog_service.ItemRow] = []
        self._warehouses: list[locations_service.WarehouseRow] = []

        title = DOC_TYPE_TITLES[document_type_code]
        self.page_title = QLabel(f"سندِ {title}")
        self.page_title.setObjectName("pageTitle")
        self.body_layout.addWidget(self.page_title)

        # طبقِ نمونه‌طراحیِ استپردار/کارت‌رنگیِ ارسالیِ کاربر — هم‌الگو با
        # treasury_voucher.py/journal_entry.py/commercial_document.py: صرفاً
        # لایه‌یِ بصری/ناوبری. این سند مبلغ ندارد (فقط مقدار)، پس کارت‌ها
        # تعدادِ ردیف‌ها/جمعِ مقدار/جمعِ بهایِ ردیف‌ها را نشان می‌دهند.
        self.step_stepper = SectionStepper(["اطلاعاتِ سند", "ردیف‌ها"])
        self.body_layout.addWidget(self.step_stepper)

        self.summary_cards = SummaryCardBar({
            "line_count": SummaryCard("تعدادِ ردیف‌ها", role="neutral"),
            "total_quantity": SummaryCard("جمعِ مقدار", role="info"),
            "total_cost": SummaryCard("جمعِ بهایِ ردیف‌ها", role="success"),
        })
        self.body_layout.addWidget(self.summary_cards)

        header_row1 = QHBoxLayout()
        date_box = QVBoxLayout()
        date_box.addWidget(QLabel("تاریخ"))
        self.date_field = JalaliDateEdit()
        date_box.addWidget(self.date_field)
        header_row1.addLayout(date_box)

        self.source_wh_box = QWidget()
        source_wh_layout = QVBoxLayout(self.source_wh_box)
        source_wh_layout.setContentsMargins(0, 0, 0, 0)
        source_wh_layout.addWidget(QLabel("انبارِ مبدا"))
        self.source_wh_combo = QComboBox()
        self.source_wh_combo.currentIndexChanged.connect(self._on_warehouse_changed)
        source_wh_layout.addWidget(self.source_wh_combo)
        header_row1.addWidget(self.source_wh_box)

        self.destination_wh_box = QWidget()
        dest_wh_layout = QVBoxLayout(self.destination_wh_box)
        dest_wh_layout.setContentsMargins(0, 0, 0, 0)
        dest_wh_layout.addWidget(QLabel("انبارِ مقصد"))
        self.destination_wh_combo = QComboBox()
        self.destination_wh_combo.currentIndexChanged.connect(self._on_warehouse_changed)
        dest_wh_layout.addWidget(self.destination_wh_combo)
        header_row1.addWidget(self.destination_wh_box)

        self.adjustment_direction_box = QWidget()
        adj_dir_layout = QVBoxLayout(self.adjustment_direction_box)
        adj_dir_layout.setContentsMargins(0, 0, 0, 0)
        adj_dir_layout.addWidget(QLabel("جهت"))
        self.adjustment_direction_combo = QComboBox()
        self.adjustment_direction_combo.addItem("مازاد (افزایش)", "IN")
        self.adjustment_direction_combo.addItem("کسری (کاهش)", "OUT")
        self.adjustment_direction_combo.currentIndexChanged.connect(self._on_warehouse_changed)
        adj_dir_layout.addWidget(self.adjustment_direction_combo)
        header_row1.addWidget(self.adjustment_direction_box)

        self.body_layout.addLayout(header_row1)

        header_row2 = QHBoxLayout()
        self.counterparty_box = QWidget()
        counterparty_layout = QVBoxLayout(self.counterparty_box)
        counterparty_layout.setContentsMargins(0, 0, 0, 0)
        self.counterparty_label = QLabel("طرفِ‌حساب")
        counterparty_layout.addWidget(self.counterparty_label)
        self.counterparty_combo = _make_searchable_combo([])
        counterparty_layout.addWidget(self.counterparty_combo)
        header_row2.addWidget(self.counterparty_box)

        reference_box = QVBoxLayout()
        reference_box.addWidget(QLabel("شمارهٔ مرجع"))
        self.reference_field = QLineEdit()
        reference_box.addWidget(self.reference_field)
        header_row2.addLayout(reference_box)

        description_box = QVBoxLayout()
        description_box.addWidget(QLabel("توضیح"))
        self.description_field = QLineEdit()
        description_box.addWidget(self.description_field)
        header_row2.addLayout(description_box)

        self.body_layout.addLayout(header_row2)

        self.status_badge = QLabel("")
        self.status_badge.setObjectName("statusBadge")
        self.body_layout.addWidget(self.status_badge)

        lines_title = QLabel("ردیف‌ها")
        lines_title.setObjectName("sectionTitle")
        self.body_layout.addWidget(lines_title)

        add_line_button = QPushButton("➕")
        add_line_button.setObjectName("primaryIconButton")
        add_line_button.setFixedWidth(48)
        add_line_button.setToolTip("افزودنِ ردیف")
        add_line_button.clicked.connect(self._add_line)
        self.body_layout.addWidget(add_line_button, alignment=Qt.AlignLeft)

        self.lines_table = QTableWidget(0, len(_LINE_COLUMNS))
        self.lines_table.setHorizontalHeaderLabels(_LINE_COLUMNS)
        self.lines_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lines_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.lines_table.verticalHeader().setVisible(False)
        self.lines_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.lines_table.setMinimumHeight(220)
        self.lines_table.cellDoubleClicked.connect(self._edit_line)
        self.body_layout.addWidget(self.lines_table)

        self.step_stepper.register_sections(self._scroll, [self.page_title, self.lines_table])

        line_buttons = QHBoxLayout()
        edit_line_button = QPushButton("✏️")
        edit_line_button.setObjectName("iconButton")
        edit_line_button.setFixedWidth(44)
        edit_line_button.setToolTip("ویرایشِ ردیف")
        edit_line_button.clicked.connect(self._edit_line)
        line_buttons.addWidget(edit_line_button)
        delete_line_button = QPushButton("🗑️")
        delete_line_button.setObjectName("dangerIconButton")
        delete_line_button.setFixedWidth(44)
        delete_line_button.setToolTip("حذفِ ردیف")
        delete_line_button.clicked.connect(self._delete_line)
        line_buttons.addWidget(delete_line_button)
        self.body_layout.addLayout(line_buttons)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        self.body_layout.addWidget(self.status_label)
        self.body_layout.addStretch(1)

        # طبقِ گزارشِ صریح («بعضی فرم‌ها روی دکمه‌هاش نوشته داره و نصف
        # نوشته‌هاست»): این فوتر ۵ دکمه‌یِ متنیِ کنارِ هم داشت — دقیقاً
        # الگویِ فشرده‌شدنی که باعثِ بریده‌شدنِ متن می‌شود. همه آیکنی
        # شدند؛ توضیح از طریقِ تول‌تیپ.
        self.new_button = QPushButton("🆕")
        self.new_button.setObjectName("iconButton")
        self.new_button.setFixedWidth(44)
        self.new_button.setToolTip("سندِ جدید")
        self.new_button.clicked.connect(self._reset_form)
        self.footer_layout.addWidget(self.new_button)

        self.save_button = QPushButton("💾")
        self.save_button.setObjectName("primaryIconButton")
        self.save_button.setFixedWidth(48)
        self.save_button.setToolTip("ذخیرهٔ پیش‌نویس")
        self.save_button.clicked.connect(self._save_header)
        self.footer_layout.addWidget(self.save_button)

        self.confirm_button = QPushButton("✅")
        self.confirm_button.setObjectName("iconButton")
        self.confirm_button.setFixedWidth(44)
        self.confirm_button.setToolTip("تاییدِ سند")
        self.confirm_button.clicked.connect(self._confirm)
        self.footer_layout.addWidget(self.confirm_button)

        self.revert_button = QPushButton("↩️")
        self.revert_button.setObjectName("iconButton")
        self.revert_button.setFixedWidth(44)
        self.revert_button.setToolTip("بازگشت به پیش‌نویس")
        self.revert_button.clicked.connect(self._revert_to_draft)
        self.footer_layout.addWidget(self.revert_button)

        self.post_button = QPushButton("🔒")
        self.post_button.setObjectName("primaryIconButton")
        self.post_button.setFixedWidth(48)
        self.post_button.setToolTip("ثبتِ نهایی")
        self.post_button.clicked.connect(self._post)
        self.footer_layout.addWidget(self.post_button)

        self.cancel_button = QPushButton("🚫")
        self.cancel_button.setObjectName("dangerIconButton")
        self.cancel_button.setFixedWidth(44)
        self.cancel_button.setToolTip("لغوِ سند")
        self.cancel_button.clicked.connect(self._cancel)
        self.footer_layout.addWidget(self.cancel_button)

        self._apply_type_visibility()
        self.set_field_help([
            (self.date_field, "تاریخِ سند — پایهٔ تعیینِ سالِ مالی و ترتیبِ حرکاتِ موجودی."),
            (self.reference_field, "مثلاً شمارهٔ فاکتورِ خرید یا سندِ اصلیِ برگشت."),
        ])

    def _apply_type_visibility(self) -> None:
        t = self.document_type_code
        if t == "ADJUSTMENT":
            # طبقِ تصمیمِ طراحی: به‌جایِ ستِ هم‌زمانِ مبدا و مقصد (که یک
            # موتورِ ADJUSTMENT را وادار به IN+OUTِ هم‌زمانِ روی همان ردیف
            # می‌کند)، این‌جا فقط یک انبار + یک «جهت» گرفته می‌شود.
            self.source_wh_box.setVisible(True)
            self.destination_wh_box.setVisible(False)
        else:
            req = documents_service.WAREHOUSE_REQUIREMENTS[t]
            self.source_wh_box.setVisible(req["source"])
            self.destination_wh_box.setVisible(req["destination"])
        self.adjustment_direction_box.setVisible(t == "ADJUSTMENT")
        self.counterparty_box.setVisible(t in ("RECEIPT", "ISSUE", "RETURN_IN", "RETURN_OUT"))
        if t == "RECEIPT":
            self.counterparty_label.setText("طرفِ‌حساب (تامین‌کننده)")
        elif t == "RETURN_OUT":
            self.counterparty_label.setText("طرفِ‌حساب (تامین‌کننده) — الزامی")
        elif t == "RETURN_IN":
            self.counterparty_label.setText("طرفِ‌حساب (مشتری) — الزامی")
        elif t == "ISSUE":
            self.counterparty_label.setText("طرفِ‌حساب (مشتری)")

    def _on_warehouse_changed(self) -> None:
        # طبقِ گزارشِ صریح: عوضِ‌شدنِ انبار ردیف‌هایِ ثبت‌شده را بی‌معنا
        # می‌کند — فقط برایِ سندِ پیش‌نویسِ هنوز بدونِ ردیف مجاز است.
        pass

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def _current_warehouse_ids(self) -> tuple[int | None, int | None]:
        t = self.document_type_code
        if t == "ADJUSTMENT":
            warehouse_id = self.source_wh_combo.currentData()
            if self.adjustment_direction_combo.currentData() == "OUT":
                return warehouse_id, None
            return None, warehouse_id
        return self.source_wh_combo.currentData(), self.destination_wh_combo.currentData()

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._items = catalog_service.list_items(company_id, active_only=True)
        self._warehouses = locations_service.list_warehouses(company_id, active_only=True)

        for combo in (self.source_wh_combo, self.destination_wh_combo):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("(انتخاب کنید)", None)
            for w in self._warehouses:
                combo.addItem(f"{w.code} — {w.name}", w.warehouse_id)
            if current is not None:
                combo.setCurrentIndex(max(0, combo.findData(current)))
            combo.blockSignals(False)

        counterparty_options: list[tuple[int, str]] = []
        if self.document_type_code in ("RECEIPT", "RETURN_OUT"):
            counterparty_options = [(c["detail_account_id"], f"{c['code']} — {c['name'] or ''}") for c in dimensions_service.list_suppliers(company_id)]
        elif self.document_type_code in ("ISSUE", "RETURN_IN"):
            counterparty_options = [(c["detail_account_id"], f"{c['code']} — {c['name'] or ''}") for c in dimensions_service.list_customers(company_id)]
        current_counterparty = self.counterparty_combo.currentData()
        _fill_options(self.counterparty_combo, counterparty_options)
        if current_counterparty is not None:
            index = self.counterparty_combo.findData(current_counterparty)
            if index >= 0:
                self.counterparty_combo.setCurrentIndex(index)

        if self._document_id is not None:
            self._load_document()
        else:
            self._reset_form(clear_only=True)

    def _load_document(self) -> None:
        company_id = self._company_id()
        try:
            doc, lines = documents_service.get_stock_document(self._document_id, company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._status_code = doc.status_code
        self.page_title.setText(f"سندِ {DOC_TYPE_TITLES[self.document_type_code]} #{doc.document_no}")
        self.date_field.setDate(doc.document_date)
        if self.document_type_code == "ADJUSTMENT":
            if doc.source_warehouse_id is not None:
                self.source_wh_combo.setCurrentIndex(max(0, self.source_wh_combo.findData(doc.source_warehouse_id)))
                self.adjustment_direction_combo.setCurrentIndex(self.adjustment_direction_combo.findData("OUT"))
            else:
                self.source_wh_combo.setCurrentIndex(max(0, self.source_wh_combo.findData(doc.destination_warehouse_id)))
                self.adjustment_direction_combo.setCurrentIndex(self.adjustment_direction_combo.findData("IN"))
        else:
            if doc.source_warehouse_id is not None:
                self.source_wh_combo.setCurrentIndex(max(0, self.source_wh_combo.findData(doc.source_warehouse_id)))
            if doc.destination_warehouse_id is not None:
                self.destination_wh_combo.setCurrentIndex(max(0, self.destination_wh_combo.findData(doc.destination_warehouse_id)))
        if doc.counterparty_detail_account_id is not None:
            index = self.counterparty_combo.findData(doc.counterparty_detail_account_id)
            if index >= 0:
                self.counterparty_combo.setCurrentIndex(index)
        self.reference_field.setText(doc.reference_no or "")
        self.description_field.setText(doc.description or "")
        self._lines = lines
        self._refresh_lines_table()
        self._apply_status_state()

    def _refresh_lines_table(self) -> None:
        items_by_id = {it.item_id: it for it in self._items}
        all_bins = {}
        for w in self._warehouses:
            for b in locations_service.list_bin_locations(w.warehouse_id):
                all_bins[b.bin_location_id] = b
        reasons_by_id: dict[int, str] = {}
        company_id = self._company_id()
        if company_id is not None:
            for applies_to in ("ADJUSTMENT", "RETURN_IN", "RETURN_OUT"):
                for r in documents_service.list_reason_codes(company_id, applies_to, active_only=False):
                    reasons_by_id[r.reason_code_id] = r.name

        self.lines_table.setRowCount(len(self._lines))
        for row_index, ln in enumerate(self._lines):
            item = items_by_id.get(ln.item_id)
            values = [
                f"{item.code} — {item.name or ''}" if item else str(ln.item_id),
                str(ln.quantity),
                all_bins.get(ln.bin_location_id).code if ln.bin_location_id in all_bins else "پیش‌فرض",
                all_bins.get(ln.destination_bin_location_id).code if ln.destination_bin_location_id in all_bins else "",
                str(ln.unit_cost) if ln.unit_cost is not None else "",
                str(ln.line_total_cost) if ln.line_total_cost is not None else "",
                reasons_by_id.get(ln.reason_code_id, ""),
                ln.description or "",
            ]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, ln.line_id)
                self.lines_table.setItem(row_index, col_index, cell)

        total_quantity = sum((ln.quantity for ln in self._lines), decimal.Decimal(0))
        total_cost = sum((ln.line_total_cost or decimal.Decimal(0) for ln in self._lines), decimal.Decimal(0))
        self.summary_cards.set_value("line_count", numerals.to_persian_digits(str(len(self._lines))))
        self.summary_cards.set_value("total_quantity", numerals.format_amount(total_quantity))
        self.summary_cards.set_value("total_cost", numerals.format_amount(total_cost))

    def _apply_status_state(self) -> None:
        self.status_badge.setText(STATUS_LABELS.get(self._status_code, self._status_code))
        is_draft = self._status_code == "DRAFT"
        is_confirmed = self._status_code == "CONFIRMED"
        editable = is_draft and self._document_id is not None
        for widget in (self.date_field, self.source_wh_combo, self.destination_wh_combo, self.adjustment_direction_combo, self.counterparty_combo, self.reference_field, self.description_field):
            widget.setEnabled(is_draft)
        self.save_button.setEnabled(is_draft)
        self.confirm_button.setEnabled(editable)
        self.revert_button.setEnabled(is_confirmed)
        self.post_button.setEnabled(is_confirmed)
        self.cancel_button.setEnabled(is_draft or is_confirmed)
        self.lines_table.setEnabled(True)

    def _reset_form(self, clear_only: bool = False) -> None:
        self._document_id = None
        self._status_code = "DRAFT"
        self._lines = []
        self.page_title.setText(f"سندِ {DOC_TYPE_TITLES[self.document_type_code]}ِ جدید")
        self.status_label.setText("")
        self.date_field.setDate(datetime.date.today())
        self.source_wh_combo.setCurrentIndex(0)
        self.destination_wh_combo.setCurrentIndex(0)
        self.adjustment_direction_combo.setCurrentIndex(0)
        self.counterparty_combo.setCurrentIndex(0)
        self.reference_field.clear()
        self.description_field.clear()
        self._refresh_lines_table()
        self._apply_status_state()
        if not clear_only:
            self.refresh()

    def edit_document(self, stock_document_id: int) -> None:
        self._document_id = stock_document_id
        self.refresh()

    def _header_fields(self) -> documents_service.DocumentHeaderFields | None:
        source_wh, destination_wh = self._current_warehouse_ids()
        counterparty_id = self.counterparty_combo.currentData() if self.counterparty_box.isVisible() else None
        if self.document_type_code in ("RETURN_IN", "RETURN_OUT") and counterparty_id is None:
            self.status_label.setText("انتخابِ طرفِ‌حساب برایِ این نوعِ سند الزامی است.")
            return None
        return documents_service.DocumentHeaderFields(
            source_warehouse_id=source_wh, destination_warehouse_id=destination_wh,
            counterparty_detail_account_id=counterparty_id, reference_no=self.reference_field.text().strip() or None,
            description=self.description_field.text().strip() or None,
        )

    def _save_header(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        fields = self._header_fields()
        if fields is None:
            return
        try:
            if self._document_id is None:
                self._document_id = documents_service.create_stock_document(
                    company_id, app_session.current_user.user_id, self.document_type_code, self.date_field.date(), fields
                )
            else:
                documents_service.update_stock_document_header(self._document_id, company_id, self.date_field.date(), fields)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("")
        self._load_document()

    def _ensure_saved(self) -> bool:
        if self._document_id is None:
            self._save_header()
        return self._document_id is not None

    def _primary_line_warehouse_id(self, source_wh_id: int | None, destination_wh_id: int | None) -> int | None:
        """انبارِ مرجعِ ردیف — همان انباری که فهرستِ مکان‌هایِ «مکان» از
        رویِ آن پر می‌شود (برایِ TRANSFER همیشه مبدا؛ «مکانِ مقصد» از رویِ
        destination_wh_id جداگانه پر می‌شود)."""
        if self.document_type_code in ("RECEIPT", "RETURN_IN"):
            return destination_wh_id
        if self.document_type_code == "TRANSFER":
            return source_wh_id
        return source_wh_id if source_wh_id is not None else destination_wh_id

    def _add_line(self) -> None:
        if not self._ensure_saved():
            return
        source_wh_id, destination_wh_id = self._current_warehouse_ids()
        line_wh_id = self._primary_line_warehouse_id(source_wh_id, destination_wh_id)
        if line_wh_id is None:
            self.status_label.setText("ابتدا انبار را انتخاب کنید.")
            return
        source_bins = locations_service.list_bin_locations(line_wh_id, active_only=True)
        destination_bins = locations_service.list_bin_locations(destination_wh_id, active_only=True) if self.document_type_code == "TRANSFER" and destination_wh_id else []
        company_id = self._company_id()
        reasons: list[documents_service.ReasonCodeRow] = []
        if self.document_type_code in ("ADJUSTMENT", "RETURN_IN", "RETURN_OUT"):
            reasons = documents_service.list_reason_codes(company_id, self.document_type_code)
        dialog = _LineDialog(self, self.document_type_code, self._items, source_bins, destination_bins, reasons)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            documents_service.add_line(self._document_id, company_id, dialog.result_fields())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._load_document()

    def _selected_line(self) -> documents_service.StockDocumentLineRow | None:
        selected = self.lines_table.selectedItems()
        if not selected:
            return None
        line_id = selected[0].data(Qt.UserRole)
        return next((ln for ln in self._lines if ln.line_id == line_id), None)

    def _edit_line(self, *_args) -> None:
        line = self._selected_line()
        if line is None or self._document_id is None:
            return
        source_wh_id, destination_wh_id = self._current_warehouse_ids()
        line_wh_id = self._primary_line_warehouse_id(source_wh_id, destination_wh_id)
        source_bins = locations_service.list_bin_locations(line_wh_id, active_only=True) if line_wh_id else []
        destination_bins = locations_service.list_bin_locations(destination_wh_id, active_only=True) if self.document_type_code == "TRANSFER" and destination_wh_id else []
        company_id = self._company_id()
        reasons: list[documents_service.ReasonCodeRow] = []
        if self.document_type_code in ("ADJUSTMENT", "RETURN_IN", "RETURN_OUT"):
            reasons = documents_service.list_reason_codes(company_id, self.document_type_code)
        initial = documents_service.LineFields(
            item_id=line.item_id, uom_id=line.uom_id, quantity=line.quantity, quantity_base=line.quantity_base,
            bin_location_id=line.bin_location_id, destination_bin_location_id=line.destination_bin_location_id,
            unit_cost=line.unit_cost, reason_code_id=line.reason_code_id, description=line.description,
        )
        dialog = _LineDialog(self, self.document_type_code, self._items, source_bins, destination_bins, reasons, initial)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            documents_service.update_line(line.line_id, self._document_id, company_id, dialog.result_fields())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._load_document()

    def _delete_line(self) -> None:
        line = self._selected_line()
        if line is None or self._document_id is None:
            return
        confirm = QMessageBox.question(self, "حذفِ ردیف", "این ردیف حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            documents_service.delete_line(line.line_id, self._document_id, self._company_id())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._load_document()

    def _confirm(self) -> None:
        if self._document_id is None:
            return
        try:
            documents_service.confirm_stock_document(self._document_id, self._company_id())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("")
        self._load_document()

    def _revert_to_draft(self) -> None:
        if self._document_id is None:
            return
        try:
            documents_service.revert_to_draft(self._document_id, self._company_id())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._load_document()

    def _post(self) -> None:
        if self._document_id is None:
            return
        confirm = QMessageBox.question(
            self, "ثبتِ نهایی", "این سند ثبتِ نهایی شود؟ پسِ این کار، سند دیگر قابلِ‌ویرایش/حذف نیست.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            documents_service.post_stock_document(self._document_id, self._company_id(), app_session.current_user.user_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("")
        self._load_document()

    def _cancel(self) -> None:
        if self._document_id is None:
            return
        confirm = QMessageBox.question(self, "لغوِ سند", "این سند لغو شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            documents_service.cancel_stock_document(self._document_id, self._company_id())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._load_document()
