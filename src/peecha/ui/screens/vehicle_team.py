"""تیمِ خودرو (فازِ ۲ از پخشِ گرم) -- طبقِ درخواستِ صریحِ کاربر: هر خودرو
سه نقشِ مستقل دارد (راننده/ویزیتور/موزع)؛ ممکن است هر سه رویِ یک نفر
باشد."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from peecha import session as app_session
from peecha.services import inventory_locations as locations_service
from peecha.services import users as users_service
from peecha.services import vehicle_team as vehicle_team_service
from peecha.ui.widgets import FieldGrid, FieldHelpMixin, FieldSpec, LayoutEditMixin

_ROLE_LABELS = {"DRIVER": "راننده", "VISITOR": "ویزیتور", "DISTRIBUTOR": "موزع"}


class VehicleTeamScreen(FieldHelpMixin, LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        title = QLabel("تیمِ خودرو")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "هر خودرو تا سه نقشِ مستقل می‌تواند داشته باشد: راننده (مسئولِ کلی/تحویلِ کلی/برگشتِ کالا)، "
            "ویزیتور (ثبتِ سفارش/فاکتور + تسویه‌حساب)، موزع (تحویلِ فیزیکیِ کالا بر اساسِ فاکتور + تسویه‌حساب). "
            "اگر یک نفر هر سه کار را انجام می‌دهد، همان فرد را در هر سه انتخاب کنید."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QHBoxLayout()
        self.vehicle_combo = QComboBox()
        self.vehicle_combo.currentIndexChanged.connect(self._load_team)
        form.addWidget(self.vehicle_combo)
        layout.addLayout(form)

        self.driver_combo = QComboBox()
        self.visitor_combo = QComboBox()
        self.distributor_combo = QComboBox()
        self.grid = FieldGrid([
            FieldSpec("driver", _ROLE_LABELS["DRIVER"], self.driver_combo, span=1),
            FieldSpec("visitor", _ROLE_LABELS["VISITOR"], self.visitor_combo, span=1),
            FieldSpec("distributor", _ROLE_LABELS["DISTRIBUTOR"], self.distributor_combo, span=1),
        ])
        layout.addWidget(self.grid)
        self.register_field_grids("vehicle_team", [self.grid])

        save_button = QPushButton("ذخیره")
        save_button.clicked.connect(self._save)
        layout.addWidget(save_button)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)
        layout.addStretch(1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def _role_combos(self) -> dict[str, QComboBox]:
        return {"DRIVER": self.driver_combo, "VISITOR": self.visitor_combo, "DISTRIBUTOR": self.distributor_combo}

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self.status_label.setText("")

        current_vehicle = self.vehicle_combo.currentData()
        self.vehicle_combo.blockSignals(True)
        self.vehicle_combo.clear()
        vehicles = locations_service.list_vehicles(company_id, active_only=True)
        for v in vehicles:
            self.vehicle_combo.addItem(f"{v.code} — {v.name}", v.warehouse_id)
        if current_vehicle is not None:
            index = self.vehicle_combo.findData(current_vehicle)
            if index >= 0:
                self.vehicle_combo.setCurrentIndex(index)
        self.vehicle_combo.blockSignals(False)

        company_users = [u for u in users_service.list_users() if company_id in u.company_ids]
        for combo in self._role_combos().values():
            combo.clear()
            combo.addItem("(تعیین نشده)", None)
            for u in company_users:
                combo.addItem(u.full_name, u.user_id)

        if not vehicles:
            self.status_label.setText("هنوز هیچ انبارِ نوعِ «خودرو»ای تعریف نشده -- ابتدا از تنظیماتِ انبار بسازید.")
            return
        self._load_team()

    def _load_team(self) -> None:
        company_id = self._company_id()
        vehicle_warehouse_id = self.vehicle_combo.currentData()
        if company_id is None or vehicle_warehouse_id is None:
            return
        team = vehicle_team_service.get_team(vehicle_warehouse_id, company_id)
        role_user_ids = {
            "DRIVER": team.driver_user_id, "VISITOR": team.visitor_user_id, "DISTRIBUTOR": team.distributor_user_id,
        }
        for role_code, combo in self._role_combos().items():
            index = combo.findData(role_user_ids[role_code])
            combo.setCurrentIndex(index if index >= 0 else 0)

    def _save(self) -> None:
        company_id = self._company_id()
        vehicle_warehouse_id = self.vehicle_combo.currentData()
        if company_id is None or vehicle_warehouse_id is None:
            self.status_label.setText("ابتدا یک خودرو انتخاب کنید.")
            return
        try:
            for role_code, combo in self._role_combos().items():
                vehicle_team_service.set_team_member(vehicle_warehouse_id, company_id, role_code, combo.currentData())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("تیمِ این خودرو ذخیره شد.")
