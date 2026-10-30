"""R357: سوخت و هزینهٔ خودروهای پخش — ثبت سوخت‌گیری با کیلومترشمار و هزینهٔ هر خودرو (سوخت + نگهداری) در برابر فروش."""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget

from peecha import numerals
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import fleet as fleet_service
from peecha.services import inventory_locations as locations_service
from peecha.ui import report_export, theme
from peecha.ui.persian_numbers import NumberEdit
from peecha.ui.screens.fixed_assets import P, combo, company_id, dec, fill, selected_data, table, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec, JalaliDateEdit, build_page_header

_LOG_HEADERS = ["تاریخ", "خودرو", "کیلومترشمار", "کیلومتر پیموده", "لیتر", "مصرف در ۱۰۰ کیلومتر", "مبلغ", "نوع سوخت", "راننده",
                "کارکرد تجهیز", "توضیح"]
_COST_HEADERS = ["خودرو", "پلاک", "تجهیز نگهداری", "کیلومتر", "لیتر", "مصرف در ۱۰۰ کیلومتر", "هزینهٔ سوخت", "دستور کار",
                 "هزینهٔ نگهداری", "جمع هزینه", "هزینهٔ هر کیلومتر", "فروش خالص", "درصد هزینه از فروش"]


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


def _num(value) -> str:
    return P(numerals.format_amount(value)) if value is not None else "—"


class FleetScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.logs: list = []
        self.costs: list = []
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header("سوخت و هزینهٔ خودروهای پخش",
                                           "سوخت‌گیری با کیلومترشمار و هزینهٔ هر خودرو (سوخت + نگهداری) در برابر فروش همان خودرو."))
        hint = QLabel("کیلومتر پیموده از آخرین سوخت‌گیری به کارکرد تجهیز همان خودرو در نگهداری اضافه می‌شود تا نگهداری کیلومتری "
                      "سررسید شود؛ تجهیز را در فرم انبار خودرو انتخاب کنید. کیلومتر را به ترتیب تاریخ وارد کنید.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.vehicle_combo, self.fuel_combo, self.driver_combo = combo([]), combo([]), combo([], "—")
        self.date_field = JalaliDateEdit()
        self.date_field.setDate(datetime.date.today())
        self.odometer_field, self.liters_field, self.amount_field = NumberEdit(), NumberEdit(), NumberEdit()
        self.note_field = QLineEdit()
        layout.addWidget(FieldGrid([
            FieldSpec("vehicle", "خودرو", self.vehicle_combo, span=2), FieldSpec("log_date", "تاریخ", self.date_field, span=1),
            FieldSpec("odometer", "کیلومترشمار", self.odometer_field, span=1), FieldSpec("liters", "لیتر", self.liters_field, span=1),
            FieldSpec("amount", "مبلغ", self.amount_field, span=1), FieldSpec("fuel_type", "نوع سوخت", self.fuel_combo, span=1),
            FieldSpec("driver", "راننده", self.driver_combo, span=2), FieldSpec("note", "توضیح", self.note_field, span=2),
        ]))
        bar = QHBoxLayout()
        self.add_button = _btn("ثبت سوخت‌گیری", "➕", "primary")
        self.delete_button = _btn("حذف سوخت‌گیری انتخاب‌شده", "🗑️", "danger")
        for button, handler in ((self.add_button, self.add_log), (self.delete_button, self.delete_log)):
            button.clicked.connect(handler)
            bar.addWidget(button)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        bar.addWidget(self.status_label, 1)
        layout.addLayout(bar)
        self.log_table = table(_LOG_HEADERS)
        layout.addWidget(self.log_table, 2)

        title = QLabel("هزینهٔ خودروها")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        today = datetime.date.today()
        self.from_field, self.to_field = JalaliDateEdit(), JalaliDateEdit()
        self.from_field.setDate(today.replace(day=1))
        self.to_field.setDate(today)
        range_bar = QHBoxLayout()
        range_bar.addWidget(FieldGrid([FieldSpec("date_from", "از تاریخ", self.from_field, span=1),
                                       FieldSpec("date_to", "تا تاریخ", self.to_field, span=1)]), 1)
        self.costs_button = _btn("محاسبهٔ هزینهٔ خودروها", "🔄")
        self.export_button = _btn("خروجی Excel هزینهٔ خودروها", "📊")
        for button, handler in ((self.costs_button, self.load_costs), (self.export_button, self.export_costs)):
            button.clicked.connect(handler)
            range_bar.addWidget(button)
        layout.addLayout(range_bar)
        note = QLabel("جمع هزینه = سوخت + هزینهٔ دستورهای کار نگهداری تجهیز همان خودرو (قطعه، نیروی کار، خدمات و سایر). "
                      "فروش خالص = فاکتور فروش ثبت‌شده با انبار همان خودرو منهای برگشت، بدون مالیات.")
        note.setObjectName("sectionHint")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.cost_table = table(_COST_HEADERS)
        layout.addWidget(self.cost_table, 2)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        for box, items in ((self.vehicle_combo, [(f"{v.code} — {v.name}", v.warehouse_id)
                                                 for v in locations_service.list_vehicles(cid, active_only=True)]),
                           (self.fuel_combo, [(label, code) for code, label in fleet_service.FUEL_TYPES.items()]),
                           (self.driver_combo, [(f"{p['code']} — {p['name'] or ''}", p["detail_account_id"])
                                                for p in dimensions_service.list_personnel(cid)])):
            current = box.currentData()
            box.clear()
            if box is self.driver_combo:
                box.addItem("—", None)
            for label, data in items:
                box.addItem(P(label), data)
            index = box.findData(current)
            box.setCurrentIndex(index if index >= 0 else 0)
        self.load_logs()
        self.load_costs()

    def load_logs(self) -> None:
        self.logs = fleet_service.list_fuel_logs(company_id())
        fill(self.log_table, [[r.log_date, r.vehicle_name, _num(r.odometer_km), _num(r.distance_km), _num(r.liters),
                               _num(r.per_100km), r.amount, r.fuel_type_label, r.driver_name, "ثبت شد" if r.usage_recorded else "—",
                               r.note] for r in self.logs], [r.fuel_log_id for r in self.logs])

    def _fields(self) -> fleet_service.FuelFields:
        odometer = self.odometer_field.text().strip()
        return fleet_service.FuelFields(
            vehicle_warehouse_id=self.vehicle_combo.currentData(), log_date=self.date_field.date(), liters=dec(self.liters_field.text()),
            amount=dec(self.amount_field.text()), odometer_km=dec(odometer) if odometer else None,
            fuel_type_code=self.fuel_combo.currentData() or "GASOLINE", driver_detail_account_id=self.driver_combo.currentData(),
            note=self.note_field.text())

    def add_log(self) -> int | None:
        if self.vehicle_combo.currentData() is None:
            theme.set_status_label(self.status_label, "اول خودرو را انتخاب کنید (انبار نوع خودرو).", ok=False)
            return None
        try:
            log_id, warning = fleet_service.add_fuel_log(company_id(), user_id(), self._fields())
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return None
        for field in (self.odometer_field, self.liters_field, self.amount_field, self.note_field):
            field.clear()
        theme.set_status_label(self.status_label, warning or "سوخت‌گیری ثبت شد.", ok=not warning)
        self.load_logs()
        self.load_costs()
        return log_id

    def delete_log(self) -> bool:
        log_id = selected_data(self.log_table)
        if log_id is None:
            theme.set_status_label(self.status_label, "یک سوخت‌گیری را از جدول انتخاب کنید.", ok=False)
            return False
        if QMessageBox.question(self, "حذف سوخت‌گیری", "این سوخت‌گیری حذف شود؟") != QMessageBox.Yes:
            return False
        try:
            fleet_service.delete_fuel_log(company_id(), log_id)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return False
        theme.set_status_label(self.status_label, "سوخت‌گیری حذف شد.", ok=True)
        self.load_logs()
        self.load_costs()
        return True

    def _cost_rows(self) -> list[list]:
        return [[r.vehicle_name, r.plate, r.asset_label or "—", r.km, r.liters, r.per_100km, r.fuel_amount, r.work_orders,
                 r.maintenance_amount, r.total_cost, r.per_km, r.net_sales, r.cost_percent] for r in self.costs]

    def load_costs(self) -> None:
        self.costs = fleet_service.vehicle_costs(company_id(), self.from_field.date(), self.to_field.date())
        fill(self.cost_table, [[r.vehicle_name, r.plate, r.asset_label or "—", _num(r.km), _num(r.liters), _num(r.per_100km),
                                r.fuel_amount, P(r.work_orders), r.maintenance_amount, r.total_cost, _num(r.per_km), r.net_sales,
                                f"{_num(r.cost_percent)}٪" if r.cost_percent is not None else "—"] for r in self.costs],
             [r.vehicle_warehouse_id for r in self.costs])

    def export_costs(self) -> None:
        from peecha import session as app_session

        company = app_session.current_company
        report_export.export_report_excel(
            self, "هزینهٔ خودروهای پخش", _COST_HEADERS, self._cost_rows(), company_name=company.display_name if company else "",
            filters=[("از تاریخ", numerals.format_jalali_date(self.from_field.date())),
                     ("تا تاریخ", numerals.format_jalali_date(self.to_field.date()))])
