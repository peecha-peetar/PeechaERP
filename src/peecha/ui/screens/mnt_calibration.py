"""R382: کالیبراسیون ابزار اندازه‌گیری — فهرست ابزار با سررسید، مشخصات، ثبت نتیجه و سابقه."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from peecha.services import detail_dimensions as dimensions_service
from peecha.services.maintenance import calibration as cal
from peecha.ui import theme
from peecha.ui.screens.fixed_assets import P, combo, company_id, dec, fill, selected_data, set_combo, table, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec, JalaliDateEdit, build_page_header, set_widget_help

_STATE_COLOR = {"OVERDUE": "DANGER", "DUE": "WARNING", "OUT_OF_SERVICE": "DANGER", "RETIRED": "TEXT_DISABLED"}


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


def _bar(*buttons) -> QHBoxLayout:
    row = QHBoxLayout()
    for label, glyph, kind, slot in buttons:
        button = _btn(label, glyph, kind)
        button.clicked.connect(slot)
        row.addWidget(button)
    row.addStretch(1)
    return row


class CalibrationScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.rows: list = []
        self.records: list = []
        self._instrument_id: int | None = None
        self.ask_reason = None  # برای آزمون
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "کالیبراسیون", "ابزارهای اندازه‌گیری با دورهٔ کالیبراسیون و سررسید. نتیجهٔ قبول سررسید بعدی را می‌سازد؛ ابزار مردود از "
            "خدمت خارج می‌شود و برای بررسی اندازه‌گیری‌های قبلی یک عدم‌انطباق کیفیت باز می‌شود. ابزارهای سررسید در کارتابل "
            "می‌آیند."))
        top = QHBoxLayout()
        self.retired_box = QCheckBox("نمایش ابزارهای بازنشسته")
        self.retired_box.toggled.connect(self.refresh)
        top.addWidget(self.retired_box)
        top.addLayout(_bar(("ابزار جدید", "➕", "primary", self.new_instrument),
                           ("خارج کردن از خدمت با ذکر دلیل", "⛔", "", lambda: self.change_status("OUT_OF_SERVICE")),
                           ("بازگرداندن به خدمت", "🟢", "", lambda: self.change_status("ACTIVE")),
                           ("بازنشسته کردن ابزار", "🗄️", "danger", lambda: self.change_status("RETIRED")),
                           ("به‌روزرسانی", "🔄", "", self.refresh)), 1)
        layout.addLayout(top)
        self.table = table(["کد", "نام ابزار", "شمارهٔ سریال", "محل", "گستره", "دقت مجاز", "دوره (روز)", "آخرین کالیبراسیون",
                            "سررسید", "وضعیت سررسید", "مسئول"])
        self.table.itemSelectionChanged.connect(self._on_select)
        layout.addWidget(self.table, 2)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._instrument_tab(), "مشخصات ابزار")
        self.tabs.addTab(self._record_tab(), "ثبت نتیجهٔ کالیبراسیون")
        self.records_table = table(["شماره", "تاریخ", "نتیجه", "انجام‌دهنده", "شمارهٔ گواهی", "خطای یافت‌شده", "پس از تنظیم", "هزینه",
                                    "سررسید بعدی", "عدم‌انطباق"])
        self.tabs.addTab(self.records_table, "سابقهٔ کالیبراسیون")
        layout.addWidget(self.tabs, 2)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def _status(self, text: str, ok: bool) -> None:
        theme.set_status_label(self.status_label, text, ok=ok)

    # --- مشخصات --------------------------------------------------------------------------------------------------------
    def _instrument_tab(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        self.code_field, self.name_field, self.serial_field = QLineEdit(), QLineEdit(), QLineEdit()
        self.location_field, self.range_field, self.tolerance_field, self.notes_field = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.interval_field, self.lead_field = QSpinBox(), QSpinBox()
        self.interval_field.setRange(1, 3650)
        self.interval_field.setValue(365)
        self.lead_field.setRange(0, 365)
        self.lead_field.setValue(14)
        self.method_combo = QComboBox()
        for code, label in cal.METHOD_LABELS.items():
            self.method_combo.addItem(label, code)
        self.due_field = JalaliDateEdit()
        self.lab_combo, self.responsible_combo, self.asset_combo = combo([]), combo([]), combo([])
        lay.addWidget(FieldGrid([
            FieldSpec("cal_code", "کد ابزار", self.code_field, span=1), FieldSpec("cal_name", "نام ابزار", self.name_field, span=2),
            FieldSpec("cal_serial", "شمارهٔ سریال", self.serial_field, span=1), FieldSpec("cal_location", "محل", self.location_field, span=2),
            FieldSpec("cal_range", "گسترهٔ اندازه‌گیری", self.range_field, span=1), FieldSpec("cal_tolerance", "دقت مجاز", self.tolerance_field, span=1),
            FieldSpec("cal_interval", "دورهٔ کالیبراسیون (روز)", self.interval_field, span=1),
            FieldSpec("cal_lead", "هشدار پیش از سررسید (روز)", self.lead_field, span=1),
            FieldSpec("cal_due", "سررسید کالیبراسیون", self.due_field, span=1), FieldSpec("cal_method", "روش", self.method_combo, span=1),
            FieldSpec("cal_lab", "آزمایشگاه کالیبراسیون", self.lab_combo, span=2),
            FieldSpec("cal_responsible", "مسئول ابزار", self.responsible_combo, span=2),
            FieldSpec("cal_asset", "تجهیز مرتبط (اختیاری)", self.asset_combo, span=2),
            FieldSpec("cal_notes", "توضیحات", self.notes_field, span=3)]), 1)
        save = _btn("ذخیرهٔ مشخصات ابزار", "💾", "primary")
        save.clicked.connect(self.save_instrument)
        lay.addWidget(save, 0, Qt.AlignTop)
        for widget, text in (
                (self.tolerance_field, "حداکثر خطای پذیرفتنی، مثلاً ±۰٫۰۲ میلی‌متر؛ مبنای قبول یا رد در کالیبراسیون."),
                (self.interval_field, "فاصلهٔ دو کالیبراسیون؛ سررسید بعدی از تاریخ هر کالیبراسیون قبول حساب می‌شود."),
                (self.lead_field, "از چند روز پیش از سررسید، ابزار در کارتابل «نزدیک سررسید» دیده شود."),
                (self.due_field, "سررسید کالیبراسیون بعدی؛ پس از اولین ثبت نتیجه، خودکار حساب می‌شود."),
                (self.lab_combo, "آزمایشگاه یا شرکت کالیبراسیون (از تامین‌کنندگان)."),
                (self.asset_combo, "اگر ابزار جزو تجهیزات ثبت‌شده است، آن را انتخاب کنید.")):
            set_widget_help(widget, text)
        return w

    def _load_lookups(self, cid: int) -> None:
        from sqlalchemy import select

        from peecha.db.base import new_session
        from peecha.db.models.fixed_assets import Asset
        from peecha.services import users as users_service

        self.lab_combo.clear()
        self.lab_combo.addItem("", None)
        for s in dimensions_service.list_suppliers(cid):
            self.lab_combo.addItem(P(f"{s['code']} — {s['name']}"), s["detail_account_id"])
        self.responsible_combo.clear()
        self.responsible_combo.addItem("", None)
        for u in users_service.list_users():
            if u.is_active:
                self.responsible_combo.addItem(u.full_name or u.username, u.user_id)
        self.asset_combo.clear()
        self.asset_combo.addItem("", None)
        with new_session() as session:
            for a in session.scalars(select(Asset).where(Asset.company_id == cid).order_by(Asset.asset_code)):
                self.asset_combo.addItem(P(f"{a.asset_code} — {a.name}"), a.asset_id)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self._load_lookups(cid)
        self.rows = cal.list_instruments(cid, include_retired=self.retired_box.isChecked())
        fill(self.table, [[r.code, r.name, r.serial_no, r.location_text, r.measure_range, r.tolerance, P(r.interval_days),
                           r.last_calibrated_on or "", r.next_due_date, r.state_label, r.responsible] for r in self.rows],
             [r.instrument_id for r in self.rows])
        for i, r in enumerate(self.rows):
            color = _STATE_COLOR.get(r.state)
            if color:
                item = self.table.item(i, 9)
                item.setForeground(QColor(getattr(theme, color)))
        if self._instrument_id is not None and any(r.instrument_id == self._instrument_id for r in self.rows):
            self.open_instrument(self._instrument_id)
        else:
            self.new_instrument()

    def _on_select(self) -> None:
        instrument_id = selected_data(self.table)
        if instrument_id is not None and instrument_id != self._instrument_id:
            self.open_instrument(instrument_id)

    def new_instrument(self) -> None:
        self._instrument_id = None
        for f in (self.code_field, self.name_field, self.serial_field, self.location_field, self.range_field, self.tolerance_field,
                  self.notes_field):
            f.clear()
        self.interval_field.setValue(365)
        self.lead_field.setValue(14)
        self.due_field.setDate(datetime.date.today())
        self.due_field.setEnabled(True)
        for box in (self.lab_combo, self.responsible_combo, self.asset_combo):
            box.setCurrentIndex(0)
        fill(self.records_table, [])
        self.tabs.setCurrentIndex(0)

    def open_instrument(self, instrument_id: int) -> None:
        r = cal.get_instrument(company_id(), instrument_id)
        self._instrument_id = instrument_id
        self.code_field.setText(r.code)
        self.name_field.setText(r.name)
        self.serial_field.setText(r.serial_no)
        self.location_field.setText(r.location_text)
        self.range_field.setText(r.measure_range)
        self.tolerance_field.setText(r.tolerance)
        self.notes_field.setText(r.notes)
        self.interval_field.setValue(r.interval_days)
        self.lead_field.setValue(r.lead_days)
        self.due_field.setDate(r.next_due_date)
        self.due_field.setEnabled(r.last_calibrated_on is None)
        set_combo(self.method_combo, r.method_code)
        set_combo(self.lab_combo, r.lab_detail_account_id)
        set_combo(self.responsible_combo, r.responsible_user_id)
        set_combo(self.asset_combo, r.asset_id)
        self.records = cal.list_records(company_id(), instrument_id)
        fill(self.records_table, [[P(x.record_no), x.calibrated_on, x.result_label, x.performed_by, x.certificate_no, x.as_found, x.as_left,
                                   x.cost_amount, x.next_due_date or "", P(x.ncr_no) if x.ncr_no else ""] for x in self.records],
             [x.record_id for x in self.records])

    def _run(self, action, ok_text: str) -> bool:
        try:
            action()
        except (ValueError, decimal.InvalidOperation) as exc:
            self._status(str(exc) if isinstance(exc, ValueError) else "عدد نامعتبر است.", False)
            return False
        self.refresh()
        self._status(ok_text, True)
        return True

    def save_instrument(self) -> bool:
        data = cal.InstrumentInput(
            self.code_field.text(), self.name_field.text(), self.interval_field.value(), self.due_field.date(), self.lead_field.value(),
            self.method_combo.currentData(), self.asset_combo.currentData(), self.serial_field.text(), self.location_field.text(),
            self.range_field.text(), self.tolerance_field.text(), self.lab_combo.currentData(), self.responsible_combo.currentData(),
            self.notes_field.text())
        instrument_id = self._instrument_id

        def save():
            self._instrument_id = cal.save_instrument(company_id(), user_id(), data, instrument_id)
        return self._run(save, "مشخصات ابزار ذخیره شد.")

    def change_status(self, status: str) -> bool:
        if self._instrument_id is None:
            self._status("یک ابزار را انتخاب کنید.", False)
            return False
        reason, ok = "", True
        if status != "ACTIVE":
            if self.ask_reason is not None:
                reason = self.ask_reason()
            else:
                reason, ok = QInputDialog.getText(self, cal.STATUS_LABELS[status], "دلیل:")
        instrument_id = self._instrument_id
        return ok and self._run(lambda: cal.set_status(company_id(), user_id(), instrument_id, status, reason),
                                f"وضعیت ابزار «{cal.STATUS_LABELS[status]}» شد.")

    # --- ثبت نتیجه -----------------------------------------------------------------------------------------------------
    def _record_tab(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        self.rec_date_field = JalaliDateEdit()
        self.result_combo = QComboBox()
        for code, label in cal.RESULT_LABELS.items():
            self.result_combo.addItem(label, code)
        self.performed_field, self.certificate_field, self.found_field = QLineEdit(), QLineEdit(), QLineEdit()
        self.left_field, self.cost_field, self.rec_notes_field = QLineEdit(), QLineEdit(), QLineEdit()
        self.ncr_box = QCheckBox("برای نتیجهٔ مردود، عدم‌انطباق کیفیت باز شود")
        self.ncr_box.setChecked(True)
        lay.addWidget(FieldGrid([
            FieldSpec("cal_rec_date", "تاریخ کالیبراسیون", self.rec_date_field, span=1),
            FieldSpec("cal_result", "نتیجه", self.result_combo, span=1),
            FieldSpec("cal_performed", "انجام‌دهنده", self.performed_field, span=2),
            FieldSpec("cal_certificate", "شمارهٔ گواهی", self.certificate_field, span=1),
            FieldSpec("cal_cost", "هزینه", self.cost_field, span=1),
            FieldSpec("cal_found", "خطای یافت‌شده", self.found_field, span=3),
            FieldSpec("cal_left", "وضعیت پس از تنظیم", self.left_field, span=3),
            FieldSpec("cal_rec_notes", "توضیحات", self.rec_notes_field, span=3),
            FieldSpec("cal_ncr", "عدم‌انطباق", self.ncr_box, span=3)]), 1)
        save = _btn("ثبت نتیجهٔ کالیبراسیون", "✅", "primary")
        save.clicked.connect(self.record)
        lay.addWidget(save, 0, Qt.AlignTop)
        self.rec_date_field.setDate(datetime.date.today())
        for widget, text in (
                (self.found_field, "خطای ابزار پیش از هر تنظیم؛ برای نتیجهٔ مردود الزامی است."),
                (self.left_field, "خطای ابزار پس از تنظیم، وقتی نتیجه «تنظیم و قبول» است."),
                (self.cost_field, "فقط برای سابقه؛ ثبت مالی با فاکتور خرید خدمات انجام می‌شود.")):
            set_widget_help(widget, text)
        return w

    def record(self) -> bool:
        if self._instrument_id is None:
            self._status("یک ابزار را انتخاب کنید.", False)
            return False
        instrument_id = self._instrument_id

        def save():
            cal.record_calibration(company_id(), user_id(), instrument_id, self.rec_date_field.date(), self.result_combo.currentData(),
                                   performed_by=self.performed_field.text(), certificate_no=self.certificate_field.text(),
                                   as_found=self.found_field.text(), as_left=self.left_field.text(), cost_amount=dec(self.cost_field.text()),
                                   notes=self.rec_notes_field.text(), open_ncr=self.ncr_box.isChecked())
            for f in (self.performed_field, self.certificate_field, self.found_field, self.left_field, self.cost_field, self.rec_notes_field):
                f.clear()
        if not self._run(save, "نتیجهٔ کالیبراسیون ثبت شد."):
            return False
        self.tabs.setCurrentIndex(2)
        return True
