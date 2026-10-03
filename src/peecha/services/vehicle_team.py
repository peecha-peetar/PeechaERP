"""تیمِ خودرو (فازِ ۲ از پخشِ گرم) -- طبقِ درخواستِ صریحِ کاربر: هر خودرو
(inv.warehouses با warehouse_type_code='VEHICLE') تا سه نقشِ مستقل دارد
-- راننده (مسئولِ کلی/تحویلِ کلی/برگشتِ کالا)، ویزیتور (ثبتِ سفارش/
فاکتور + تسویه‌حساب)، موزع (تحویلِ فیزیکیِ کالا بر اساسِ فاکتورِ صادره +
تسویه‌حساب). ممکن است هر سه نقش رویِ یک نفر باشد -- طراحیِ این جدول
عمداً هر سه را مستقل نگه می‌دارد تا کسب‌وکاری که بعداً خواست این نقش‌ها
را از هم جدا کند نیازی به تغییرِ ساختارِ داده نداشته باشد."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.inventory import VehicleTeamAssignment, Warehouse

ROLE_CODES = ("DRIVER", "VISITOR", "DISTRIBUTOR")


@dataclass
class VehicleTeamRow:
    vehicle_warehouse_id: int
    driver_user_id: int | None
    visitor_user_id: int | None
    distributor_user_id: int | None


def get_team(vehicle_warehouse_id: int, company_id: int) -> VehicleTeamRow:
    with new_session() as session:
        rows = session.scalars(
            select(VehicleTeamAssignment).where(
                VehicleTeamAssignment.vehicle_warehouse_id == vehicle_warehouse_id,
                VehicleTeamAssignment.company_id == company_id,
            )
        ).all()
        by_role = {r.role_code: r.user_id for r in rows}
    return VehicleTeamRow(
        vehicle_warehouse_id=vehicle_warehouse_id,
        driver_user_id=by_role.get("DRIVER"),
        visitor_user_id=by_role.get("VISITOR"),
        distributor_user_id=by_role.get("DISTRIBUTOR"),
    )


def list_teams(company_id: int) -> list[VehicleTeamRow]:
    with new_session() as session:
        vehicle_ids = session.scalars(
            select(Warehouse.warehouse_id).where(
                Warehouse.company_id == company_id, Warehouse.warehouse_type_code == "VEHICLE"
            )
        ).all()
    return [get_team(vehicle_id, company_id) for vehicle_id in vehicle_ids]


def set_team_member(vehicle_warehouse_id: int, company_id: int, role_code: str, user_id: int | None) -> None:
    if role_code not in ROLE_CODES:
        raise ValueError("نقش نامعتبر است.")
    with new_session() as session:
        vehicle = session.get(Warehouse, vehicle_warehouse_id)
        if vehicle is None or vehicle.company_id != company_id:
            raise ValueError("خودرو نامعتبر است.")
        if vehicle.warehouse_type_code != "VEHICLE":
            raise ValueError("فقط انبارِ نوعِ «خودرو» می‌تواند تیمِ خودرو داشته باشد.")
        existing = session.get(VehicleTeamAssignment, (vehicle_warehouse_id, role_code))
        if user_id is None:
            if existing is not None:
                session.delete(existing)
        elif existing is not None:
            existing.user_id = user_id
        else:
            session.add(
                VehicleTeamAssignment(
                    vehicle_warehouse_id=vehicle_warehouse_id, role_code=role_code,
                    user_id=user_id, company_id=company_id,
                )
            )
        session.commit()


def get_assigned_vehicle_warehouse_id(user_id: int, company_id: int, role_code: str) -> int | None:
    """طبقِ نیازِ اپِ موبایل: این کاربر به‌عنوانِ role_code به کدام خودرو
    وصل است -- برایِ پخشِ گرم، به‌جایِ انبارِ پیش‌فرضِ شرکت، فروش باید
    از رویِ موجودیِ همین انبار انجام شود. اگر کاربر به چند خودرو با این
    نقش وصل باشد (حالتِ نامتعارف)، اولین مورد برمی‌گردد."""
    if role_code not in ROLE_CODES:
        raise ValueError("نقش نامعتبر است.")
    with new_session() as session:
        return session.scalar(
            select(VehicleTeamAssignment.vehicle_warehouse_id).where(
                VehicleTeamAssignment.user_id == user_id,
                VehicleTeamAssignment.company_id == company_id,
                VehicleTeamAssignment.role_code == role_code,
            )
        )
