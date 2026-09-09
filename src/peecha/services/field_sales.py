"""پخشِ سرد/گرم -- R129، بخشِ برنامهٔ مراجعه و ویزیتِ واقعی. طبقِ طرحِ
تاییدشده: این فاز فقط دیتامدل+منطقِ سرویس است -- بدونِ UI دسکتاپی/موبایل/
API، که در فازهایِ بعدی (R130+) اضافه می‌شوند.

برنامهٔ مراجعه (VisitPlan) یعنی «این مشتری این روزِ هفته باید دیده
شود»؛ ویزیتِ واقعی (CustomerVisit) یک حضورِ واقعی است -- یا از رویِ
همان برنامه، یا بی‌برنامه (visit_plan_id=None)."""

from __future__ import annotations

import datetime
import decimal
import math
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import CustomerProfile, CustomerVisit, VisitPlan

VISIT_STATUS_CODES = ("IN_PROGRESS", "COMPLETED", "SKIPPED")


@dataclass
class VisitPlanRow:
    visit_plan_id: int
    customer_detail_account_id: int
    visit_day_of_week: int
    sequence_order: int
    assigned_visitor_user_id: int | None
    is_active: bool


def create_visit_plan(
    company_id: int, customer_detail_account_id: int, visit_day_of_week: int,
    sequence_order: int = 0, assigned_visitor_user_id: int | None = None,
) -> int:
    if not (0 <= visit_day_of_week <= 6):
        raise ValueError("روزِ هفته باید بینِ ۰ تا ۶ باشد.")
    with new_session() as session:
        existing = session.scalar(
            select(VisitPlan).where(
                VisitPlan.customer_detail_account_id == customer_detail_account_id,
                VisitPlan.visit_day_of_week == visit_day_of_week,
            )
        )
        if existing is not None:
            raise ValueError("برنامهٔ مراجعه برایِ این مشتری در این روز از قبل وجود دارد.")
        plan = VisitPlan(
            company_id=company_id, customer_detail_account_id=customer_detail_account_id,
            visit_day_of_week=visit_day_of_week, sequence_order=sequence_order,
            assigned_visitor_user_id=assigned_visitor_user_id,
        )
        session.add(plan)
        session.commit()
        return plan.visit_plan_id


def update_visit_plan(
    visit_plan_id: int, company_id: int, sequence_order: int, assigned_visitor_user_id: int | None, is_active: bool,
) -> None:
    with new_session() as session:
        plan = session.get(VisitPlan, visit_plan_id)
        if plan is None or plan.company_id != company_id:
            raise ValueError("برنامهٔ مراجعه نامعتبر است.")
        plan.sequence_order = sequence_order
        plan.assigned_visitor_user_id = assigned_visitor_user_id
        plan.is_active = is_active
        session.commit()


def delete_visit_plan(visit_plan_id: int, company_id: int) -> None:
    with new_session() as session:
        plan = session.get(VisitPlan, visit_plan_id)
        if plan is None or plan.company_id != company_id:
            raise ValueError("برنامهٔ مراجعه نامعتبر است.")
        session.delete(plan)
        session.commit()


def list_visit_plans(
    company_id: int, visitor_user_id: int | None = None, visit_day_of_week: int | None = None,
    active_only: bool = False,
) -> list[VisitPlanRow]:
    with new_session() as session:
        stmt = select(VisitPlan).where(VisitPlan.company_id == company_id)
        if visitor_user_id is not None:
            stmt = stmt.where(VisitPlan.assigned_visitor_user_id == visitor_user_id)
        if visit_day_of_week is not None:
            stmt = stmt.where(VisitPlan.visit_day_of_week == visit_day_of_week)
        if active_only:
            stmt = stmt.where(VisitPlan.is_active.is_(True))
        stmt = stmt.order_by(VisitPlan.visit_day_of_week, VisitPlan.sequence_order)
        rows = session.scalars(stmt).all()
        return [
            VisitPlanRow(
                r.visit_plan_id, r.customer_detail_account_id, r.visit_day_of_week,
                r.sequence_order, r.assigned_visitor_user_id, r.is_active,
            )
            for r in rows
        ]


@dataclass
class CustomerVisitRow:
    customer_visit_id: int
    visit_plan_id: int | None
    customer_detail_account_id: int
    visitor_user_id: int
    status_code: str
    skip_reason: str | None
    checked_in_at: datetime.datetime
    checked_out_at: datetime.datetime | None
    check_in_latitude: decimal.Decimal | None
    check_in_longitude: decimal.Decimal | None
    distance_from_customer_m: decimal.Decimal | None
    notes: str | None


def _haversine_distance_m(lat1: decimal.Decimal, lon1: decimal.Decimal, lat2: decimal.Decimal, lon2: decimal.Decimal) -> decimal.Decimal:
    """فاصلهٔ خط‌مستقیمِ رویِ کرهٔ زمین (متر) -- برایِ تشخیصِ «ویزیتِ صوری»
    کافی است، بدونِ نیازِ به PostGIS."""
    earth_radius_m = 6_371_000
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    d_phi = math.radians(float(lat2) - float(lat1))
    d_lambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return decimal.Decimal(str(round(earth_radius_m * c, 1)))


def start_visit(
    company_id: int, customer_detail_account_id: int, visitor_user_id: int,
    visit_plan_id: int | None = None, check_in_latitude: decimal.Decimal | None = None,
    check_in_longitude: decimal.Decimal | None = None,
) -> int:
    distance_from_customer_m = None
    if check_in_latitude is not None and check_in_longitude is not None:
        with new_session() as session:
            profile = session.get(CustomerProfile, customer_detail_account_id)
            if profile is not None and profile.gps_latitude is not None and profile.gps_longitude is not None:
                distance_from_customer_m = _haversine_distance_m(
                    check_in_latitude, check_in_longitude, profile.gps_latitude, profile.gps_longitude
                )
    with new_session() as session:
        visit = CustomerVisit(
            company_id=company_id, visit_plan_id=visit_plan_id, customer_detail_account_id=customer_detail_account_id,
            visitor_user_id=visitor_user_id, check_in_latitude=check_in_latitude, check_in_longitude=check_in_longitude,
            distance_from_customer_m=distance_from_customer_m,
        )
        session.add(visit)
        session.commit()
        return visit.customer_visit_id


def complete_visit(customer_visit_id: int, company_id: int, notes: str | None = None) -> None:
    with new_session() as session:
        visit = session.get(CustomerVisit, customer_visit_id)
        if visit is None or visit.company_id != company_id:
            raise ValueError("ویزیت نامعتبر است.")
        if visit.status_code != "IN_PROGRESS":
            raise ValueError("این ویزیت قبلاً بسته شده است.")
        visit.status_code = "COMPLETED"
        visit.checked_out_at = datetime.datetime.now()
        visit.notes = notes or visit.notes
        session.commit()


def skip_visit(customer_visit_id: int, company_id: int, skip_reason: str) -> None:
    if not skip_reason.strip():
        raise ValueError("دلیلِ ردِ ویزیت را وارد کنید.")
    with new_session() as session:
        visit = session.get(CustomerVisit, customer_visit_id)
        if visit is None or visit.company_id != company_id:
            raise ValueError("ویزیت نامعتبر است.")
        if visit.status_code != "IN_PROGRESS":
            raise ValueError("این ویزیت قبلاً بسته شده است.")
        visit.status_code = "SKIPPED"
        visit.skip_reason = skip_reason.strip()
        visit.checked_out_at = datetime.datetime.now()
        session.commit()


def list_customer_visits(
    company_id: int, visitor_user_id: int | None = None, customer_detail_account_id: int | None = None,
    status_code: str | None = None, date_from: datetime.date | None = None, date_to: datetime.date | None = None,
) -> list[CustomerVisitRow]:
    """date_from/date_to (طبقِ R134، برایِ داشبوردِ سرپرست) رویِ
    checked_in_at فیلتر می‌کنند -- شاملِ کلِ آن روز (بدونِ نیاز به دانستنِ
    ساعتِ دقیق)."""
    with new_session() as session:
        stmt = select(CustomerVisit).where(CustomerVisit.company_id == company_id)
        if visitor_user_id is not None:
            stmt = stmt.where(CustomerVisit.visitor_user_id == visitor_user_id)
        if customer_detail_account_id is not None:
            stmt = stmt.where(CustomerVisit.customer_detail_account_id == customer_detail_account_id)
        if status_code is not None:
            stmt = stmt.where(CustomerVisit.status_code == status_code)
        if date_from is not None:
            stmt = stmt.where(CustomerVisit.checked_in_at >= datetime.datetime.combine(date_from, datetime.time.min))
        if date_to is not None:
            stmt = stmt.where(CustomerVisit.checked_in_at <= datetime.datetime.combine(date_to, datetime.time.max))
        stmt = stmt.order_by(CustomerVisit.checked_in_at.desc())
        rows = session.scalars(stmt).all()
        return [
            CustomerVisitRow(
                r.customer_visit_id, r.visit_plan_id, r.customer_detail_account_id, r.visitor_user_id,
                r.status_code, r.skip_reason, r.checked_in_at, r.checked_out_at,
                r.check_in_latitude, r.check_in_longitude, r.distance_from_customer_m, r.notes,
            )
            for r in rows
        ]
