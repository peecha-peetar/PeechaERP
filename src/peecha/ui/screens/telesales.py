"""فروشِ تلفنی -- طبقِ درخواستِ صریحِ کاربر: پخشِ سرد از ۳ مسیر سفارش
می‌گیرد (سفارشِ عمده، سفارشِ موبایلی، و این‌جا سفارشِ تلفنی). این صفحه
فهرستِ مشتریانِ ویزیتورِ واردشده (چه ویزیتورِ مقیمِ شرکت، چه ویزیتورِ
تلفنی -- هردو از همان assigned_visitor_user_id در برنامهٔ مراجعه
استفاده می‌کنند) را نشان می‌دهد و برایِ هر مشتری امکانِ یادداشت، دیدنِ
مانده‌حساب، بازکردنِ معینِ حساب، و ثبتِ سفارش/صدورِ فاکتور (با
توضیحِ پیش‌فرضِ «سفارشِ تلفنی») را در همان صفحه فراهم می‌کند."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
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
from peecha.services import customer_dashboard as customer_dashboard_service
from peecha.services import telesales as telesales_service
from peecha.services import treasury as treasury_service
from peecha.services import users as users_service
from peecha.services import voip_ami
from peecha.services import voip_settings as voip_settings_service
from peecha.ui.screens.dashboard import build_chart_card, render_bar_chart, render_donut_chart

_COLUMNS = ["کد", "نام", "ماندهٔ حساب", "آخرین یادداشت", "اقدامات"]


class _OriginateWorker(QObject):
    """اجرایِ originate_call در یک QThreadِ جدا -- طبقِ اصلِ «اتصال به
    سیستمِ بیرونی نباید UI را قفل کند» (سوکتِ AMI می‌تواند تا چند ثانیه
    طول بکشد یا timeout بخورد)."""

    finished = Signal(bool, str)

    def __init__(self, host: str, port: int, ami_username: str, ami_secret: str, dial_context: str,
                 channel_tech_prefix: str, agent_extension: str, customer_phone_number: str) -> None:
        super().__init__()
        self._args = (host, port, ami_username, ami_secret, dial_context, channel_tech_prefix, agent_extension, customer_phone_number)

    def run(self) -> None:
        result = voip_ami.originate_call(*self._args)
        self.finished.emit(result.success, result.message)


class Customer360Dialog(QDialog):
    """داشبوردِ معلقِ مشتری -- طبقِ درخواستِ صریحِ کاربر: «با زدنِ اطلاعاتِ
    مشتری خلاصه‌اطلاعات و یک داشبوردِ معلق از مشتری نشان بده... گزارشِ
    آماری از فروش و چک‌ها و فروش بر اساسِ کالا و ماه به‌صورتِ نموداری و
    شماره‌تماس». مودال نیست (exec نمی‌شود، show می‌شود) تا واقعاً «معلق»
    باشد و کارِ فروشِ تلفنی را قطع نکند."""

    def __init__(self, company_id: int, customer_id: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.Window, True)
        self.resize(760, 620)
        self._company_id = company_id
        self._customer_id = customer_id

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(12)

        self._header_layout = QGridLayout()
        outer.addLayout(self._header_layout)

        self._call_status_label = QLabel("")
        self._call_status_label.setObjectName("sectionHint")
        self._call_status_label.setWordWrap(True)
        outer.addWidget(self._call_status_label)

        # طبقِ رفعِ دو باگِ واقعیِ کشف‌شده در تست:
        # ۱) «QThread: Destroyed while thread is still running» -- اگر
        #    رفرنسِ threadِ تماسِ قبلی با یک ویژگیِ تکی جایگزین شود، درست
        #    همان لحظه‌ای که worker.finished شلیک شده ولی خودِ QThread
        #    هنوز کاملاً exit نکرده (quit فقط درخواستِ خروج است، نه
        #    تضمینِ فوری)، رفرنسِ پایتونی از دست می‌رود و GC آن را
        #    درحینِ اجرا نابود می‌کند.
        # ۲) اگر worker فقط یک متغیرِ محلیِ تابعِ _call باشد (بدونِ نگه‌
        #    داشتنِ رفرنس)، به‌محضِ خروج از _call ممکن است پایتون آن را
        #    GC کند -- و چون PySide مالکیتِ آبجکتِ ++C را به رفرنسِ
        #    پایتونی گره می‌زند (نه فقط به کانکشن‌هایِ سیگنال/اسلات)،
        #    QThreadِ پس‌زمینه با یک workerِ حذف‌شده کار می‌کند و رفتارش
        #    غیرِقابلِ‌پیش‌بینی می‌شود.
        # برایِ همین، هر جفتِ (thread, worker) با هم تا لحظه‌یِ شلیکِ
        # signalِ finishedِ *خودِ QThread* (که یعنی واقعاً کاملاً متوقف
        # شده) در این فهرست نگه داشته می‌شوند.
        self._pending_calls: list[tuple[QThread, "_OriginateWorker"]] = []

        charts_row = QHBoxLayout()
        month_card, self._month_chart_view = build_chart_card("فروشِ ماهانه")
        item_card, self._item_chart_view = build_chart_card("فروش به تفکیکِ کالا (۱۰ کالایِ برتر)")
        charts_row.addWidget(month_card, stretch=1)
        charts_row.addWidget(item_card, stretch=1)
        outer.addLayout(charts_row, stretch=1)

        outer.addWidget(QLabel("چک‌هایِ مرتبط:"))
        self._cheques_table = QTableWidget(0, 5)
        self._cheques_table.setHorizontalHeaderLabels(["نوع", "شماره", "مبلغ", "سررسید", "وضعیت"])
        self._cheques_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._cheques_table.verticalHeader().setVisible(False)
        self._cheques_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        outer.addWidget(self._cheques_table)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        buttons.accepted.connect(self.close)
        outer.addWidget(buttons)

        self._load()

    def _load(self) -> None:
        contact = customer_dashboard_service.get_contact_info(self._company_id, self._customer_id)
        if contact is None:
            return
        self.setWindowTitle(f"داشبوردِ مشتری -- {contact.name}")
        decimal_places = companies_service.get_base_currency_decimal_places(self._company_id)

        self._clear_layout(self._header_layout)
        name_label = QLabel(f"{contact.name} ({contact.code})")
        name_label.setObjectName("cardTitle")
        self._header_layout.addWidget(name_label, 0, 0, 1, 3)

        balance_label = QLabel(
            f"ماندهٔ حساب: {numerals.format_money(contact.balance_amount, decimal_places)} ({contact.balance_nature})"
        )
        self._header_layout.addWidget(balance_label, 1, 0, 1, 3)

        row = 2
        for label, number in (("تلفن", contact.phone), ("همراه", contact.mobile)):
            if not number:
                continue
            self._header_layout.addWidget(QLabel(f"{label}: {number}"), row, 0)
            call_button = QPushButton("📞 تماس")
            call_button.setToolTip(f"تماس با {number}")
            call_button.clicked.connect(lambda _checked=False, n=number: self._call(n))
            self._header_layout.addWidget(call_button, row, 1)
            row += 1

        labels, values = customer_dashboard_service.sales_by_month(self._company_id, self._customer_id)
        render_bar_chart(self._month_chart_view, labels, values, series_name="فروش")

        item_rows = customer_dashboard_service.sales_by_item(self._company_id, self._customer_id)
        render_donut_chart(self._item_chart_view, [(r.item_name, r.total_amount) for r in item_rows])

        cheques = customer_dashboard_service.get_cheques(self._company_id, self._customer_id)
        all_rows = [("دریافتی", c) for c in cheques.received] + [("پرداختی", c) for c in cheques.issued]
        self._cheques_table.setRowCount(len(all_rows))
        for row_index, (kind, c) in enumerate(all_rows):
            values_row = [
                kind, c.check_no, numerals.format_money(c.amount, decimal_places),
                numerals.format_jalali_date(c.due_date), c.status_code,
            ]
            for col_index, value in enumerate(values_row):
                self._cheques_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))

    def _call(self, phone_number: str) -> None:
        # طبقِ درخواستِ صریح («وصل بشه به سیستمِ سانترال یا وویپ... با
        # کلیک کردن روی اون تماس گرفت»): اول تلاش برایِ Originateِ واقعی
        # از طریقِ AMI (اگر سانترال تنظیم شده و کاربرِ جاری داخلی دارد)؛
        # در غیرِ این صورت (یا هرگونه شکست) fallback به tel: عمومی که
        # با هر سافت‌فونِ نصب‌شده روی سیستم (از جمله متصل به ایزابل) کار
        # می‌کند.
        conn = voip_settings_service.get_voip_connection(self._company_id) if self._company_id else None
        user = app_session.current_user
        extension = users_service.get_voip_extension(user.user_id, self._company_id) if user else None
        if conn is None or not conn.is_active or not extension:
            self._open_tel_fallback(phone_number)
            return
        self._call_status_label.setText("درحالِ برقراریِ تماس از طریقِ سانترال...")
        worker = _OriginateWorker(
            conn.host, conn.port, conn.ami_username, conn.ami_secret, conn.dial_context,
            conn.channel_tech_prefix, extension, phone_number,
        )
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda success, message, n=phone_number: self._on_call_finished(success, message, n))
        worker.finished.connect(thread.quit)
        # طبقِ توضیحِ بالا، deleteLaterِ صریح رویِ worker عمداً صدا زده
        # نمی‌شود -- threadِ آن دیگر در حالِ اجرا نیست تا رویدادِ حذفِ
        # به‌تعویق‌افتاده را پردازش کند؛ به‌جایش، حذفِ این جفت از فهرست
        # (که تنها رفرنسِ پایتونیِ نگه‌دارنده است) به GCِ معمولی اجازه
        # می‌دهد آبجکت را جمع کند -- در این لحظه، چون threadش واقعاً
        # متوقف شده، این کار امن است.
        thread.finished.connect(lambda pair=(thread, worker): self._pending_calls.remove(pair) if pair in self._pending_calls else None)
        thread.finished.connect(thread.deleteLater)
        self._pending_calls.append((thread, worker))
        thread.start()

    def _on_call_finished(self, success: bool, message: str, phone_number: str) -> None:
        voip_settings_service.record_connection_result(self._company_id, success, None if success else message)
        self._call_status_label.setText(message)
        if not success:
            self._open_tel_fallback(phone_number)

    @staticmethod
    def _open_tel_fallback(phone_number: str) -> None:
        QDesktopServices.openUrl(QUrl(f"tel:{phone_number}"))

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


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
        # طبقِ درخواستِ صریح («با زدنِ اطلاعاتِ مشتری ... داشبوردِ معلق»):
        # دابل‌کلیک رویِ هر ردیف (نه فقط دکمه‌یِ اقدامات) داشبوردِ معلقِ
        # همان مشتری را باز می‌کند.
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        outer.addWidget(self.table, stretch=1)
        self._open_dialogs: list[Customer360Dialog] = []
        self._rows: list = []

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        user = app_session.current_user
        if company_id is None or user is None:
            return
        rows = telesales_service.list_assigned_customers(company_id, user.user_id)
        self._rows = rows
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

        dashboard_button = QPushButton("📊")
        dashboard_button.setObjectName("iconButton")
        dashboard_button.setToolTip("بازکردنِ داشبوردِ معلقِ این مشتری")
        dashboard_button.clicked.connect(lambda _checked=False, c=customer: self._open_customer_dashboard(company_id, c.customer_detail_account_id))
        layout.addWidget(dashboard_button)

        return actions

    def _on_row_double_clicked(self, row: int, _column: int) -> None:
        company_id = self._company_id()
        if company_id is None or row >= len(self._rows):
            return
        self._open_customer_dashboard(company_id, self._rows[row].customer_detail_account_id)

    def _open_customer_dashboard(self, company_id: int, customer_id: int) -> None:
        # طبقِ درخواستِ صریح («داشبوردِ معلق») غیرِمودال است (show، نه
        # exec) -- پس باید ریفرنسش نگه داشته شود، وگرنه GC آن را قبل از
        # نمایشِ کامل جمع می‌کند.
        dialog = Customer360Dialog(company_id, customer_id, self)
        self._open_dialogs.append(dialog)
        dialog.destroyed.connect(lambda: self._open_dialogs.remove(dialog) if dialog in self._open_dialogs else None)
        dialog.show()

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
