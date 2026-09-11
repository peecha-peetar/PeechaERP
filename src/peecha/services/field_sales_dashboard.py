"""داشبوردِ سرپرست -- R134 (آخرین فازِ ماژولِ پخشِ سرد/گرم، طبقِ نقشه‌راهِ
تاییدشده R128→R134). این ماژول هیچ منطقِ تجاریِ جدیدی ندارد -- فقط
دیتایِ سرویس‌هایِ موجود (field_sales.py, vehicle_loading.py,
commercial_documents.py, delivery_confirmation.py) را برایِ نمایشِ
KPIِ سرپرستی تجمیع می‌کند."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import Channel, CommercialDocument, DeliveryConfirmation
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import field_sales as field_sales_service
from peecha.services import inventory_locations as locations_service
from peecha.services import users as users_service
from peecha.services import vehicle_loading as vehicle_loading_service

_ZERO = decimal.Decimal(0)


def _visitor_names(company_id: int) -> dict[int, str]:
    return {u.user_id: u.full_name for u in users_service.list_users() if company_id in u.company_ids}


# ---------------------------------------------------------------------
# پوششِ ویزیت -- برایِ یک روزِ مشخص (چون برنامهٔ مراجعه هفتگی/تکرارشونده
# است، «پوششِ بازه» معنایِ روشنی ندارد؛ سرپرست معمولاً «امروز» را می‌بیند)
# ---------------------------------------------------------------------
@dataclass
class VisitCoverageRow:
    visitor_user_id: int
    visitor_name: str
    planned_count: int
    completed_count: int
    skipped_count: int
    in_progress_count: int
    not_visited_count: int
    completion_rate_percent: decimal.Decimal


def compute_visit_coverage(company_id: int, target_date: datetime.date, visitor_user_id: int | None = None) -> list[VisitCoverageRow]:
    plans = field_sales_service.list_visit_plans(
        company_id, visitor_user_id=visitor_user_id, visit_day_of_week=target_date.weekday(), active_only=True,
    )
    visits = field_sales_service.list_customer_visits(
        company_id, visitor_user_id=visitor_user_id, date_from=target_date, date_to=target_date,
    )
    visited_plan_ids = {v.visit_plan_id for v in visits if v.visit_plan_id is not None}
    names = _visitor_names(company_id)

    by_visitor: dict[int, list] = {}
    for plan in plans:
        if plan.assigned_visitor_user_id is None:
            continue
        by_visitor.setdefault(plan.assigned_visitor_user_id, []).append(plan)

    rows: list[VisitCoverageRow] = []
    for visitor_id, visitor_plans in by_visitor.items():
        visitor_visits = [v for v in visits if v.visitor_user_id == visitor_id]
        completed = sum(1 for v in visitor_visits if v.status_code == "COMPLETED")
        skipped = sum(1 for v in visitor_visits if v.status_code == "SKIPPED")
        in_progress = sum(1 for v in visitor_visits if v.status_code == "IN_PROGRESS")
        not_visited = sum(1 for p in visitor_plans if p.visit_plan_id not in visited_plan_ids)
        planned = len(visitor_plans)
        rate = (decimal.Decimal(completed) / planned * 100) if planned else _ZERO
        rows.append(
            VisitCoverageRow(
                visitor_id, names.get(visitor_id, f"کاربرِ #{visitor_id}"), planned, completed, skipped,
                in_progress, not_visited, rate.quantize(decimal.Decimal("0.1")),
            )
        )
    rows.sort(key=lambda r: r.completion_rate_percent)
    return rows


# ---------------------------------------------------------------------
# عملکردِ فروشِ هر ویزیتور در یک بازهٔ تاریخ -- پخشِ سرد (سفارش) در
# برابرِ پخشِ گرم (فاکتورِ پست‌شده)، بر اساسِ created_by_user_id
# ---------------------------------------------------------------------
@dataclass
class VisitorPerformanceRow:
    visitor_user_id: int
    visitor_name: str
    pre_sales_order_count: int
    pre_sales_order_amount: decimal.Decimal
    van_sales_invoice_count: int
    van_sales_invoice_amount: decimal.Decimal


def compute_visitor_performance(company_id: int, date_from: datetime.date, date_to: datetime.date) -> list[VisitorPerformanceRow]:
    names = _visitor_names(company_id)
    with new_session() as session:
        rows = session.execute(
            select(
                CommercialDocument.created_by_user_id, CommercialDocument.document_type_code,
                Channel.channel_type_code, CommercialDocument.total_amount,
            )
            .join(Channel, (Channel.channel_code == CommercialDocument.channel_code) & (Channel.company_id == CommercialDocument.company_id))
            .where(
                CommercialDocument.company_id == company_id,
                CommercialDocument.document_date >= date_from, CommercialDocument.document_date <= date_to,
                CommercialDocument.status_code != "DRAFT",
                Channel.channel_type_code.in_(("PRE_SALES", "VAN_SALES")),
            )
        ).all()

    by_visitor: dict[int, VisitorPerformanceRow] = {}
    for created_by_user_id, document_type_code, channel_type_code, total_amount in rows:
        row = by_visitor.setdefault(
            created_by_user_id,
            VisitorPerformanceRow(created_by_user_id, names.get(created_by_user_id, f"کاربرِ #{created_by_user_id}"), 0, _ZERO, 0, _ZERO),
        )
        if channel_type_code == "PRE_SALES" and document_type_code == "SALES_ORDER":
            row.pre_sales_order_count += 1
            row.pre_sales_order_amount += total_amount
        elif channel_type_code == "VAN_SALES" and document_type_code == "SALES_INVOICE":
            row.van_sales_invoice_count += 1
            row.van_sales_invoice_amount += total_amount
    return sorted(by_visitor.values(), key=lambda r: r.van_sales_invoice_amount + r.pre_sales_order_amount, reverse=True)


# ---------------------------------------------------------------------
# فاکتورهایِ پخشِ گرمِ بدونِ رسیدِ تحویل -- طبقِ تصمیمِ طراحیِ R133
# (رسیدِ تحویل جایگزینِ تاییدِ مدیر برایِ تسویهٔ نقدیِ فی‌المجلس است)،
# نبودنِ رسید برایِ سرپرست یک هشدارِ واقعی است، نه صرفاً یک آمار.
# ---------------------------------------------------------------------
@dataclass
class MissingDeliveryConfirmationRow:
    document_id: int
    document_no: int
    document_date: datetime.date
    customer_label: str
    total_amount: decimal.Decimal
    visitor_name: str


def compute_delivery_compliance(company_id: int, date_from: datetime.date, date_to: datetime.date) -> list[MissingDeliveryConfirmationRow]:
    names = _visitor_names(company_id)
    with new_session() as session:
        candidates = session.execute(
            select(
                CommercialDocument.document_id, CommercialDocument.document_no, CommercialDocument.document_date,
                CommercialDocument.counterparty_detail_account_id, CommercialDocument.total_amount,
                CommercialDocument.created_by_user_id,
            )
            .join(Channel, (Channel.channel_code == CommercialDocument.channel_code) & (Channel.company_id == CommercialDocument.company_id))
            .where(
                CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "SALES_INVOICE",
                CommercialDocument.status_code == "POSTED", Channel.channel_type_code == "VAN_SALES",
                CommercialDocument.document_date >= date_from, CommercialDocument.document_date <= date_to,
            )
        ).all()
        if not candidates:
            return []
        document_ids = [c.document_id for c in candidates]
        confirmed_ids = set(
            session.scalars(select(DeliveryConfirmation.document_id).where(DeliveryConfirmation.document_id.in_(document_ids))).all()
        )

    return [
        MissingDeliveryConfirmationRow(
            c.document_id, c.document_no, c.document_date,
            dimensions_service.get_detail_account_label(c.counterparty_detail_account_id), c.total_amount,
            names.get(c.created_by_user_id, f"کاربرِ #{c.created_by_user_id}"),
        )
        for c in candidates
        if c.document_id not in confirmed_ids
    ]


# ---------------------------------------------------------------------
# کسریِ بارگیریِ خودرو در یک بازهٔ تاریخ -- یعنی روزهایی که موجودیِ
# انبارِ مرکزی کمتر از نیازِ بارگیریِ برنامه‌ریزی‌شده بوده است.
# ---------------------------------------------------------------------
@dataclass
class LoadingShortageRow:
    vehicle_loading_id: int
    loading_date: datetime.date
    vehicle_warehouse_label: str
    item_count_short: int
    total_shortage_quantity: decimal.Decimal


def compute_vehicle_loading_variance(company_id: int, date_from: datetime.date, date_to: datetime.date) -> list[LoadingShortageRow]:
    loadings = vehicle_loading_service.list_vehicle_loadings(company_id, date_from=date_from, date_to=date_to)
    rows: list[LoadingShortageRow] = []
    for loading in loadings:
        short_lines = [line for line in loading.lines if line.shortage_quantity > 0]
        if not short_lines:
            continue
        vehicle = locations_service.get_warehouse(loading.vehicle_warehouse_id, company_id)
        rows.append(
            LoadingShortageRow(
                loading.vehicle_loading_id, loading.loading_date,
                vehicle.name if vehicle is not None else f"خودروی #{loading.vehicle_warehouse_id}",
                len(short_lines), sum((line.shortage_quantity for line in short_lines), _ZERO),
            )
        )
    return rows
