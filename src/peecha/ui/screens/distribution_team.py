"""تیمِ پخش -- طبقِ درخواستِ صریحِ کاربر (روالِ کاملِ پخشِ سرد): فاکتورهایِ
فروشِ ثبت‌نهایی‌شده‌یِ کانالِ «پخشِ سرد» که از تاییدِ انبار/توزین عبور
کرده‌اند، این‌جا به یک خودرو (انبارِ نوعِ VEHICLE -- که پلاک/رانندهٔ خودش
را از قبل دارد) + تاریخ الصاق می‌شوند. بعدِ افزودنِ فاکتورها، ریزِ
اقلامِ هرکدام و جمعِ هر کالا در کلِ تیم نمایش داده می‌شود -- همان چیزی
که به راننده تحویل داده می‌شود."""

from __future__ import annotations

import datetime

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
from peecha.services import commercial_partners as partners_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import distribution_runs as distribution_service
from peecha.services import inventory_locations as locations_service
from peecha.ui import report_export
from peecha.ui.widgets import FieldHelpMixin, JalaliDateEdit, build_action_footer, wrap_scrollable

_LIST_COLUMNS = ["تاریخ", "خودرو", "وضعیت"]
_ELIGIBLE_COLUMNS = ["شماره", "تاریخ", "طرفِ‌حساب", "جمعِ کل", "نوعِ تسویه", "عملیات"]
_ATTACHED_COLUMNS = ["شماره", "تاریخ", "طرفِ‌حساب", "جمعِ کل", "نوعِ تسویه", "عملیات"]
_SUMMARY_COLUMNS = ["کالا", "واحد", "جمعِ مقدار"]
_STATUS_LABELS = {"DRAFT": "پیش‌نویس", "CONFIRMED": "تحویل‌شده به راننده", "CANCELLED": "لغوشده"}


def _fmt_qty(value) -> str:
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


class DistributionTeamScreen(FieldHelpMixin, QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self._runs: list[distribution_service.DistributionRunRow] = []
        self._current_run: distribution_service.DistributionRunRow | None = None
        self._eligible: list[distribution_service.EligibleInvoiceRow] = []
        self._settlement_type_labels: dict[str, str] = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=2)
        outer.addWidget(self._build_detail_panel(), stretch=3)

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        title = QLabel("تیمِ پخش")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        new_button = QPushButton("➕")
        new_button.setObjectName("primaryIconButton")
        new_button.setFixedWidth(48)
        new_button.setToolTip("تیمِ پخشِ تازه")
        new_button.clicked.connect(self._reset_form)
        layout.addWidget(new_button, alignment=Qt.AlignLeft)

        self.runs_table = QTableWidget(0, len(_LIST_COLUMNS))
        self.runs_table.setHorizontalHeaderLabels(_LIST_COLUMNS)
        self.runs_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.runs_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.runs_table.verticalHeader().setVisible(False)
        self.runs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.runs_table.cellClicked.connect(self._on_run_clicked)
        layout.addWidget(self.runs_table)
        return wrap_scrollable(panel)

    def _build_detail_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        self.form_title = QLabel("تیمِ پخشِ تازه")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("خودرو"))
        self.vehicle_combo = QComboBox()
        header_row.addWidget(self.vehicle_combo, stretch=1)
        header_row.addWidget(QLabel("تاریخ"))
        self.date_field = JalaliDateEdit()
        header_row.addWidget(self.date_field)
        self.create_button = QPushButton("💾 ایجادِ تیم")
        self.create_button.setObjectName("primaryButton")
        self.create_button.clicked.connect(self._create_run)
        header_row.addWidget(self.create_button)
        layout.addLayout(header_row)

        # طبقِ سوالِ صریحِ کاربر («خودرو و الصاقِ راننده به خودرو الان کجا
        # باید انجام بشه؟»): تعریفِ خودروهایِ تازه و پلاک/رانندهٔ هرکدام از
        # طریقِ فرمِ عمومیِ «انبارها» (با نوعِ انبار = «خودرو») انجام
        # می‌شود -- این‌جا فقط از میانِ خودروهایِ ازپیش‌تعریف‌شده انتخاب
        # می‌کنید.
        vehicle_hint_row = QHBoxLayout()
        vehicle_hint = QLabel(
            "برایِ تعریفِ خودروی تازه یا تغییرِ پلاک/راننده‌اش، به «انبارها» بروید و یک انبار با نوعِ «خودرو» بسازید/ویرایش کنید."
        )
        vehicle_hint.setObjectName("sectionHint")
        vehicle_hint.setWordWrap(True)
        vehicle_hint_row.addWidget(vehicle_hint, stretch=1)
        if self._main_window is not None:
            manage_vehicles_button = QPushButton("🏬 مدیریتِ خودروها (انبارها)")
            manage_vehicles_button.setObjectName("flatButton")
            manage_vehicles_button.clicked.connect(self._open_warehouses)
            vehicle_hint_row.addWidget(manage_vehicles_button)
        layout.addLayout(vehicle_hint_row)

        eligible_title_row = QHBoxLayout()
        eligible_title_row.addWidget(QLabel("فاکتورهایِ واجدِ شرایط (پخشِ سردِ ثبت‌نهایی‌شده و هنوز الصاق‌نشده)"), stretch=1)
        layout.addLayout(eligible_title_row)

        # طبقِ درخواستِ صریح («فیلترِ منطقه‌بندی و مسیر و گروهِ مشتریان
        # رویِ تبِ تیمِ پخش باشد تا بتوان فاکتورها را فیلتر و به خودرو
        # تخصیص داد»): این دو فیلتر فقط رویِ همین جدولِ «واجدِ شرایط»
        # اثر می‌گذارند.
        eligible_filter_row = QHBoxLayout()
        eligible_filter_row.addWidget(QLabel("گروهِ مشتریان"))
        self.customer_group_filter = QComboBox()
        self.customer_group_filter.addItem("(همه)", None)
        eligible_filter_row.addWidget(self.customer_group_filter)
        eligible_filter_row.addWidget(QLabel("منطقه/مسیرِ توزیع"))
        self.route_filter = QComboBox()
        self.route_filter.addItem("(همه)", None)
        eligible_filter_row.addWidget(self.route_filter)
        # طبقِ درخواستِ صریحِ بعدیِ کاربر («ویزیتور هم به فیلترها اضافه
        # بشه»): ویزیتورِ ثبت‌کننده‌یِ سفارشِ مبدا (نه فاکتور -- چون
        # فاکتور را معمولاً شخصِ دیگری می‌سازد).
        eligible_filter_row.addWidget(QLabel("ویزیتور"))
        self.visitor_filter = QComboBox()
        self.visitor_filter.addItem("(همه)", None)
        eligible_filter_row.addWidget(self.visitor_filter)
        self.customer_group_filter.currentIndexChanged.connect(self._refresh_eligible)
        self.route_filter.currentIndexChanged.connect(self._refresh_eligible)
        self.visitor_filter.currentIndexChanged.connect(self._refresh_eligible)
        eligible_filter_row.addStretch(1)
        layout.addLayout(eligible_filter_row)

        self.eligible_table = QTableWidget(0, len(_ELIGIBLE_COLUMNS))
        self.eligible_table.setHorizontalHeaderLabels(_ELIGIBLE_COLUMNS)
        self.eligible_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.eligible_table.verticalHeader().setVisible(False)
        self.eligible_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.eligible_table, stretch=1)

        attached_title_row = QHBoxLayout()
        attached_title_row.addWidget(QLabel("فاکتورهایِ همین تیم"), stretch=1)
        self.print_invoices_button = QPushButton("🖨 چاپِ لیستِ فاکتورها")
        self.print_invoices_button.setObjectName("flatButton")
        self.print_invoices_button.clicked.connect(self._print_invoice_list)
        attached_title_row.addWidget(self.print_invoices_button)
        layout.addLayout(attached_title_row)
        self.attached_table = QTableWidget(0, len(_ATTACHED_COLUMNS))
        self.attached_table.setHorizontalHeaderLabels(_ATTACHED_COLUMNS)
        self.attached_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.attached_table.verticalHeader().setVisible(False)
        self.attached_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.attached_table, stretch=1)

        summary_title_row = QHBoxLayout()
        summary_title_row.addWidget(QLabel("جمعِ کالاها در کلِ تیم -- همین جدول به راننده تحویل داده می‌شود"), stretch=1)
        self.print_summary_button = QPushButton("🖨 چاپِ گزارشِ کالاها (برایِ راننده)")
        self.print_summary_button.setObjectName("flatButton")
        self.print_summary_button.clicked.connect(self._print_item_summary)
        summary_title_row.addWidget(self.print_summary_button)
        layout.addLayout(summary_title_row)
        self.summary_table = QTableWidget(0, len(_SUMMARY_COLUMNS))
        self.summary_table.setHorizontalHeaderLabels(_SUMMARY_COLUMNS)
        self.summary_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.summary_table, stretch=1)

        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.confirm_button = QPushButton("🚚 تحویل به راننده")
        self.confirm_button.setObjectName("primaryIconButton")
        self.confirm_button.clicked.connect(self._confirm_run)
        self.confirm_button.setVisible(False)

        cancel_button = QPushButton("↩️")
        cancel_button.setObjectName("iconButton")
        cancel_button.setFixedWidth(44)
        cancel_button.setToolTip("انصراف")
        cancel_button.clicked.connect(self._reset_form)
        layout.addWidget(build_action_footer([self.confirm_button, cancel_button]))

        self.set_field_help([
            (self.vehicle_combo, "خودرویی که فاکتورهایِ این تیم به آن الصاق می‌شوند -- پلاک/راننده از تعریفِ خودِ انبارِ خودرو می‌آید."),
            (self.date_field, "تاریخِ این تیمِ پخش."),
            (self.customer_group_filter, "فقط فاکتورهایِ مشتریانِ همین گروه در فهرستِ «واجدِ شرایط» نشان داده شوند."),
            (self.route_filter, "فقط فاکتورهایِ مشتریانِ همین منطقه/مسیرِ توزیع (و زیرمسیرهایش) نشان داده شوند."),
            (self.visitor_filter, "فقط فاکتورهایی که سفارشِ مبدایشان توسطِ همین ویزیتور ثبت شده نشان داده شوند."),
            (self.eligible_table, "فاکتورهایِ فروشِ پخشِ سردِ ثبت‌نهایی‌شده که هنوز به هیچ تیمی الصاق نشده‌اند."),
            (self.attached_table, "فاکتورهایِ الصاق‌شده به همین تیم."),
            (self.print_invoices_button, "چاپِ فهرستِ فاکتورهایِ الصاق‌شده به این خودرو -- برایِ رسیدِ خروج/بایگانی."),
            (self.print_summary_button, "چاپِ جمعِ هر کالا در کلِ فاکتورهایِ این تیم -- برایِ تحویلِ فیزیکیِ بار به راننده."),
        ])
        return wrap_scrollable(panel)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self.vehicle_combo.clear()
        for v in locations_service.list_vehicles(company_id, active_only=True):
            plate = f" — پلاک {v.fields.vehicle_plate_number}" if v.fields.vehicle_plate_number else ""
            self.vehicle_combo.addItem(f"{v.code} — {v.name}{plate}", v.warehouse_id)

        current_group = self.customer_group_filter.currentData()
        self.customer_group_filter.blockSignals(True)
        self.customer_group_filter.clear()
        self.customer_group_filter.addItem("(همه)", None)
        for g in partners_service.list_customer_groups(company_id):
            self.customer_group_filter.addItem(f"{g.code} — {g.name}", g.group_id)
        if current_group is not None:
            self.customer_group_filter.setCurrentIndex(max(0, self.customer_group_filter.findData(current_group)))
        self.customer_group_filter.blockSignals(False)

        current_route = self.route_filter.currentData()
        self.route_filter.blockSignals(True)
        self.route_filter.clear()
        self.route_filter.addItem("(همه)", None)
        route_dimension_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.DISTRIBUTION_ROUTE_CODE)
        for r in dimensions_service.list_detail_accounts(company_id, route_dimension_id):
            self.route_filter.addItem(f"{r.full_code} — {r.name or ''}", r.detail_account_id)
        if current_route is not None:
            self.route_filter.setCurrentIndex(max(0, self.route_filter.findData(current_route)))
        self.route_filter.blockSignals(False)

        current_visitor = self.visitor_filter.currentData()
        self.visitor_filter.blockSignals(True)
        self.visitor_filter.clear()
        self.visitor_filter.addItem("(همه)", None)
        for user_id, full_name in distribution_service.list_order_visitors(company_id):
            self.visitor_filter.addItem(full_name, user_id)
        if current_visitor is not None:
            self.visitor_filter.setCurrentIndex(max(0, self.visitor_filter.findData(current_visitor)))
        self.visitor_filter.blockSignals(False)

        self._settlement_type_labels = {
            t.code: t.name for t in pricing_service.list_distribution_settlement_types(company_id)
        }

        self._runs = distribution_service.list_distribution_runs(company_id)
        self.runs_table.setRowCount(len(self._runs))
        for row_index, run in enumerate(self._runs):
            values = [numerals.format_jalali_date(run.run_date), run.vehicle_warehouse_label, _STATUS_LABELS.get(run.status_code, run.status_code)]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, run.distribution_run_id)
                self.runs_table.setItem(row_index, col_index, item)

        if self._current_run is not None:
            updated = next((r for r in self._runs if r.distribution_run_id == self._current_run.distribution_run_id), None)
            if updated is not None:
                self._load_run(updated.distribution_run_id)
                return
        self._reset_form()

    def _on_run_clicked(self, row: int, _column: int) -> None:
        run_id = self.runs_table.item(row, 0).data(Qt.UserRole)
        self._load_run(run_id)

    def _load_run(self, run_id: int) -> None:
        company_id = self._company_id()
        try:
            run = distribution_service.get_distribution_run(run_id, company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._current_run = run
        self.status_label.setText("")
        self.form_title.setText(f"تیمِ پخشِ {numerals.format_jalali_date(run.run_date)} -- {run.vehicle_warehouse_label}")

        index = self.vehicle_combo.findData(run.vehicle_warehouse_id)
        self.vehicle_combo.setCurrentIndex(max(0, index))
        self.vehicle_combo.setEnabled(False)
        self.date_field.setDate(run.run_date)
        self.date_field.setEnabled(False)
        self.create_button.setVisible(False)

        is_draft = run.status_code == "DRAFT"
        self._refresh_eligible()
        self._fill_attached_table(editable=is_draft)
        self._fill_summary_table(run)
        has_invoices = bool(run.invoices)
        self.print_invoices_button.setEnabled(has_invoices)
        self.print_summary_button.setEnabled(has_invoices)

        if is_draft:
            self.info_label.setText("این تیم هنوز تحویل‌داده‌نشده -- می‌توانید فاکتور اضافه/حذف کنید.")
            self.confirm_button.setVisible(True)
        else:
            self.info_label.setText(
                f"تحویل‌داده‌شده در {numerals.format_jalali_date(run.confirmed_at.date())}" if run.confirmed_at else "تحویل‌داده‌شده."
            )
            self.confirm_button.setVisible(False)

    def _refresh_eligible(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._current_run is None or self._current_run.status_code != "DRAFT":
            self._eligible = []
        else:
            self._eligible = distribution_service.list_eligible_invoices(
                company_id, customer_group_id=self.customer_group_filter.currentData(),
                route_detail_account_id=self.route_filter.currentData(),
                visitor_user_id=self.visitor_filter.currentData(),
            )
        self._fill_eligible_table()

    def _settlement_type_label(self, code: str | None) -> str:
        if code is None:
            return "—"
        return self._settlement_type_labels.get(code, code)

    def _fill_eligible_table(self) -> None:
        self.eligible_table.setRowCount(len(self._eligible))
        for row_index, inv in enumerate(self._eligible):
            values = [
                numerals.to_persian_digits(str(inv.document_no)), numerals.format_jalali_date(inv.document_date),
                _dimensions_label(inv.counterparty_detail_account_id), numerals.format_money(inv.total_amount, 0),
                self._settlement_type_label(inv.settlement_type_code),
            ]
            for col_index, value in enumerate(values):
                self.eligible_table.setItem(row_index, col_index, QTableWidgetItem(value))
            button = QPushButton("➕ افزودن")
            button.clicked.connect(lambda _checked=False, document_id=inv.document_id: self._add_invoice(document_id))
            self.eligible_table.setCellWidget(row_index, len(_ELIGIBLE_COLUMNS) - 1, button)

    def _fill_attached_table(self, editable: bool) -> None:
        invoices = self._current_run.invoices if self._current_run else []
        self.attached_table.setRowCount(len(invoices))
        for row_index, inv in enumerate(invoices):
            values = [
                numerals.to_persian_digits(str(inv.document_no)), numerals.format_jalali_date(inv.document_date),
                _dimensions_label(inv.counterparty_detail_account_id), numerals.format_money(inv.total_amount, 0),
                self._settlement_type_label(inv.settlement_type_code),
            ]
            for col_index, value in enumerate(values):
                self.attached_table.setItem(row_index, col_index, QTableWidgetItem(value))
            if editable:
                button = QPushButton("➖ حذف")
                button.setObjectName("dangerButton")
                button.clicked.connect(lambda _checked=False, document_id=inv.document_id: self._remove_invoice(document_id))
                self.attached_table.setCellWidget(row_index, len(_ATTACHED_COLUMNS) - 1, button)
            else:
                self.attached_table.setItem(row_index, len(_ATTACHED_COLUMNS) - 1, QTableWidgetItem(""))

    def _fill_summary_table(self, run: distribution_service.DistributionRunRow) -> None:
        self.summary_table.setRowCount(len(run.item_summary))
        for row_index, s in enumerate(run.item_summary):
            values = [f"{s.item_code} — {s.item_name or ''}", s.uom_code, _fmt_qty(s.total_quantity)]
            for col_index, value in enumerate(values):
                self.summary_table.setItem(row_index, col_index, QTableWidgetItem(value))

    def _reset_form(self) -> None:
        self._current_run = None
        self._eligible = []
        self.form_title.setText("تیمِ پخشِ تازه")
        self.status_label.setText("")
        self.info_label.setText("")
        self.vehicle_combo.setEnabled(True)
        self.vehicle_combo.setCurrentIndex(0)
        self.date_field.setEnabled(True)
        self.date_field.setDate(datetime.date.today())
        self.create_button.setVisible(True)
        self.confirm_button.setVisible(False)
        self.eligible_table.setRowCount(0)
        self.attached_table.setRowCount(0)
        self.summary_table.setRowCount(0)
        self.print_invoices_button.setEnabled(False)
        self.print_summary_button.setEnabled(False)
        self.runs_table.clearSelection()

    def _create_run(self) -> None:
        company_id = self._company_id()
        vehicle_id = self.vehicle_combo.currentData()
        if company_id is None or vehicle_id is None:
            self.status_label.setText("خودرو را انتخاب کنید.")
            return
        try:
            run_id = distribution_service.create_distribution_run(
                company_id, app_session.current_user.user_id, self.date_field.date(), vehicle_id,
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
        self._load_run(run_id)

    def _add_invoice(self, document_id: int) -> None:
        if self._current_run is None:
            return
        company_id = self._company_id()
        try:
            distribution_service.add_document_to_run(self._current_run.distribution_run_id, company_id, document_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._load_run(self._current_run.distribution_run_id)

    def _remove_invoice(self, document_id: int) -> None:
        if self._current_run is None:
            return
        company_id = self._company_id()
        try:
            distribution_service.remove_document_from_run(self._current_run.distribution_run_id, company_id, document_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._load_run(self._current_run.distribution_run_id)

    def _confirm_run(self) -> None:
        if self._current_run is None:
            return
        confirm = QMessageBox.question(
            self, "تحویل به راننده", "بعدِ تحویل، دیگر نمی‌توان فاکتوری به این تیم اضافه/حذف کرد. ادامه می‌دهید؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        company_id = self._company_id()
        try:
            distribution_service.confirm_distribution_run(self._current_run.distribution_run_id, company_id, app_session.current_user.user_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()

    def _open_warehouses(self) -> None:
        if self._main_window is not None:
            self._main_window.open_screen("inventory_warehouses")

    def _print_invoice_list(self) -> None:
        if self._current_run is None or not self._current_run.invoices:
            return
        # طبقِ درخواستِ صریح: ستونِ «نوعِ تسویه» (موردانتظار، از رویِ خودِ
        # سند) + سه ستونِ خالیِ «نقد/چک/واریزی» که راننده هنگامِ تحویلِ
        # واقعیِ بار، دستی رویِ کاغذ علامت می‌زند (وضعیتِ واقعیِ وصول،
        # نه لزوماً همان نوعِ موردانتظار).
        headers = ["شماره", "تاریخ", "طرفِ‌حساب", "جمعِ کل", "نوعِ تسویه", "نقد", "چک", "واریزی"]
        rows = [
            [
                numerals.to_persian_digits(str(inv.document_no)), numerals.format_jalali_date(inv.document_date),
                _dimensions_label(inv.counterparty_detail_account_id), numerals.format_money(inv.total_amount, 0),
                self._settlement_type_label(inv.settlement_type_code), "", "", "",
            ]
            for inv in self._current_run.invoices
        ]
        title = f"لیستِ فاکتورهایِ الصاق‌شده -- {self._current_run.vehicle_warehouse_label}"
        report_export.print_report(self, title, headers, rows, **self._export_kwargs())

    def _print_item_summary(self) -> None:
        if self._current_run is None or not self._current_run.item_summary:
            return
        headers = ["کالا", "واحد", "جمعِ مقدار"]
        rows = [[f"{s.item_code} — {s.item_name or ''}", s.uom_code, _fmt_qty(s.total_quantity)] for s in self._current_run.item_summary]
        title = f"گزارشِ کالاهایِ تیمِ پخش -- تحویل به راننده -- {self._current_run.vehicle_warehouse_label}"
        report_export.print_report(self, title, headers, rows, **self._export_kwargs())

    def _export_kwargs(self) -> dict:
        return {
            "company_name": app_session.current_company.display_name if app_session.current_company else "",
            "report_date": numerals.format_jalali_date(self._current_run.run_date) if self._current_run else "",
        }


def _dimensions_label(detail_account_id: int) -> str:
    return dimensions_service.get_detail_account_label(detail_account_id)
