"""R375: زبانهٔ «زمان‌بندی و ارسال» گزارش‌ساز — زمان‌بندی‌های گزارش انتخاب‌شده، گیرندگان، اجرای فوری و فایل اجراها."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services.report_builder import schedule as rs
from peecha.ui.screens.fixed_assets import P, company_id, fill, selected_data, set_combo, table, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


def _when(value) -> str:
    return numerals.format_jalali_datetime(value.astimezone()) if value else "—"


class ReportSchedulePanel(QWidget):
    def __init__(self, status) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self._status = status
        self.report_id: int | None = None
        self.schedule_id: int | None = None
        self.schedules: list[rs.ScheduleRow] = []
        self.runs: list[rs.RunRow] = []
        self.ask_path = None  # برای آزمون: تابعی که مسیر ذخیرهٔ فایل را برمی‌گرداند
        v = QVBoxLayout(self)
        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        v.addWidget(self.hint_label)
        self.schedule_table = table(["تکرار", "ساعت", "بازهٔ تاریخ", "گیرندگان", "فعال", "اجرای بعدی", "آخرین اجرا"])
        self.schedule_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.schedule_table.setMaximumHeight(140)
        self.schedule_table.itemSelectionChanged.connect(self._load_schedule)
        v.addWidget(self.schedule_table)
        self.frequency_combo, self.period_combo, self.weekday_combo = QComboBox(), QComboBox(), QComboBox()
        for code, label in rs.FREQUENCIES.items():
            self.frequency_combo.addItem(label, code)
        for code, label in rs.PERIODS.items():
            self.period_combo.addItem(label, code)
        for code, label in rs.WEEKDAYS:
            self.weekday_combo.addItem(label, code)
        self.frequency_combo.currentIndexChanged.connect(self._frequency_changed)
        self.hour_field, self.month_day_field = QSpinBox(), QSpinBox()
        self.hour_field.setRange(0, 23)
        self.hour_field.setValue(7)
        self.month_day_field.setRange(1, 28)
        self.active_box = QCheckBox("فعال")
        self.active_box.setChecked(True)
        v.addWidget(FieldGrid([
            FieldSpec("rs_freq", "تکرار", self.frequency_combo, span=1), FieldSpec("rs_hour", "ساعت اجرا", self.hour_field, span=1),
            FieldSpec("rs_weekday", "روز هفته", self.weekday_combo, span=1), FieldSpec("rs_mday", "روز ماه", self.month_day_field, span=1),
            FieldSpec("rs_period", "بازهٔ تاریخ داده", self.period_combo, span=1), FieldSpec("rs_active", "وضعیت", self.active_box, span=1)]))
        v.addWidget(QLabel("گیرندگان (فقط کسانی که به این داده دسترسی دارند فایل می‌گیرند)"))
        self.recipient_list = QListWidget()
        self.recipient_list.setMaximumHeight(120)
        v.addWidget(self.recipient_list)
        bar = QHBoxLayout()
        for label, glyph, kind, slot in (("ذخیرهٔ زمان‌بندی", "💾", "primary", self.save), ("زمان‌بندی جدید", "🆕", "", self.new_schedule),
                                         ("حذف زمان‌بندی", "🗑️", "danger", self.delete), ("اجرا و ارسال همین حالا", "▶️", "", self.run_now)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            bar.addWidget(button)
        bar.addStretch(1)
        v.addLayout(bar)
        v.addWidget(QLabel("اجراهای انجام‌شده"))
        self.run_table = table(["گزارش", "زمان اجرا", "نتیجه", "ردیف‌ها", "فایل یا خطا"])
        v.addWidget(self.run_table, 1)
        row = QHBoxLayout()
        save_button = _btn("ذخیرهٔ فایل اکسل اجرای انتخاب‌شده", "📥")
        save_button.clicked.connect(lambda: self.save_file())
        row.addWidget(save_button)
        row.addStretch(1)
        v.addLayout(row)
        self._frequency_changed()

    def _frequency_changed(self) -> None:
        code = self.frequency_combo.currentData()
        self.weekday_combo.setEnabled(code == "WEEKLY")
        self.month_day_field.setEnabled(code == "MONTHLY")

    def _load_users(self) -> None:
        from peecha.services import users as users_service

        cid = company_id()
        self.recipient_list.clear()
        for u in users_service.list_users():
            if cid in u.company_ids and u.is_active:
                item = QListWidgetItem(f"{u.full_name} ({u.username})")
                item.setData(Qt.UserRole, u.user_id)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                self.recipient_list.addItem(item)

    def set_report(self, report_id: int | None) -> None:
        self.report_id = report_id
        self.hint_label.setText("گزارش ذخیره‌شده‌ای را باز کنید تا زمان‌بندی‌اش را ببینید." if report_id is None else
                                "زمان‌بندی‌های این گزارش؛ فایل اکسل هر اجرا در مرکز اعلان به گیرندگان خبر داده می‌شود.")
        self._load_users()
        self.new_schedule()
        self.refresh()

    def refresh(self) -> None:
        cid, uid = company_id(), user_id()
        if cid is None or uid is None:
            return
        self.schedules = rs.list_schedules(cid, self.report_id) if self.report_id else []
        fill(self.schedule_table, [[s.label, P(s.fields.run_hour), rs.PERIODS[s.fields.period_code], P(len(s.fields.recipient_user_ids)),
                                    "بله" if s.fields.is_active else "خیر", _when(s.next_run_at), _when(s.last_run_at)]
                                   for s in self.schedules], [s.schedule_id for s in self.schedules])
        self.runs = rs.list_runs(cid, uid, self.report_id)
        fill(self.run_table, [[r.report_name, _when(r.run_at), "انجام شد" if r.status_code == "OK" else "خطا", r.row_count,
                               r.file_name if r.status_code == "OK" else r.error_message] for r in self.runs],
             [r.run_id for r in self.runs])

    def _recipients(self) -> list[int]:
        return [self.recipient_list.item(i).data(Qt.UserRole) for i in range(self.recipient_list.count())
                if self.recipient_list.item(i).checkState() == Qt.Checked]

    def set_recipients(self, user_ids) -> None:
        for i in range(self.recipient_list.count()):
            item = self.recipient_list.item(i)
            item.setCheckState(Qt.Checked if item.data(Qt.UserRole) in set(user_ids) else Qt.Unchecked)

    def _load_schedule(self) -> None:
        sid = selected_data(self.schedule_table)
        s = next((x for x in self.schedules if x.schedule_id == sid), None)
        if s is None:
            return
        self.schedule_id = s.schedule_id
        f = s.fields
        set_combo(self.frequency_combo, f.frequency_code)
        self.hour_field.setValue(f.run_hour)
        set_combo(self.weekday_combo, f.weekday)
        self.month_day_field.setValue(f.month_day or 1)
        set_combo(self.period_combo, f.period_code)
        self.active_box.setChecked(f.is_active)
        self.set_recipients(f.recipient_user_ids)

    def new_schedule(self) -> None:
        self.schedule_id = None
        self.schedule_table.clearSelection()
        self.frequency_combo.setCurrentIndex(0)
        self.period_combo.setCurrentIndex(0)
        self.hour_field.setValue(7)
        self.active_box.setChecked(True)
        self.set_recipients([user_id()])

    def save(self) -> int | None:
        if self.report_id is None:
            self._status("اول گزارش را ذخیره یا از فهرست باز کنید.", False)
            return None
        fields = rs.ScheduleFields(self.frequency_combo.currentData(), self.hour_field.value(), self._recipients(),
                                   self.weekday_combo.currentData(), self.month_day_field.value(), self.period_combo.currentData(),
                                   self.active_box.isChecked())
        try:
            self.schedule_id = rs.save_schedule(company_id(), user_id(), self.report_id, fields, self.schedule_id)
        except ValueError as exc:
            self._status(str(exc), False)
            return None
        self.refresh()
        self._status("زمان‌بندی ذخیره شد.", True)
        return self.schedule_id

    def delete(self) -> bool:
        if self.schedule_id is None:
            self._status("یک زمان‌بندی را انتخاب کنید.", False)
            return False
        try:
            rs.delete_schedule(company_id(), user_id(), self.schedule_id)
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self.new_schedule()
        self.refresh()
        self._status("زمان‌بندی حذف شد.", True)
        return True

    def run_now(self) -> bool:
        if self.schedule_id is None:
            self._status("یک زمان‌بندی را انتخاب کنید.", False)
            return False
        try:
            runs = rs.run_now(company_id(), user_id(), self.schedule_id)
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self.refresh()
        self._status(f"گزارش اجرا و برای گیرندگان فرستاده شد ({P(len(runs))} فایل).", True)
        return True

    def save_file(self, path: str | None = None) -> str | None:
        run_id = selected_data(self.run_table)
        if run_id is None:
            self._status("یک اجرا را انتخاب کنید.", False)
            return None
        try:
            name, content = rs.run_file(company_id(), user_id(), run_id)
        except ValueError as exc:
            self._status(str(exc), False)
            return None
        if path is None:
            path = self.ask_path() if self.ask_path else QFileDialog.getSaveFileName(self, "ذخیرهٔ فایل گزارش", name, "Excel (*.xlsx)")[0]
        if not path:
            return None
        with open(path, "wb") as handle:
            handle.write(content)
        self._status("فایل ذخیره شد.", True)
        return path
