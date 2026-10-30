"""R357: ناوگان پخش — خودرو (انبار نوع خودرو) وصل به تجهیز نگهداری، دفتر سوخت و کیلومتر، و هزینهٔ هر خودرو.

- کیلومتر پیموده از آخرین سوخت‌گیری به کارکرد تجهیز همان خودرو (fa.asset_usage، منبع «شمارنده»، همان ثبت کارکرد
  نگهداری) اضافه می‌شود تا برنامهٔ نگهداری کیلومتری سررسید شود. کیلومتر باید به ترتیب تاریخ ثبت شود.
- هزینهٔ خودرو = سوخت + هزینهٔ دستورهای کار نگهداری همان تجهیز (قطعه، نیروی کار، خدمات و سایر؛ همان جمع فرم دستور کار)
  با تاریخ پایان کار (یا ثبت) در بازه؛ در برابر فروش خالص همان خودرو (فاکتور فروش ثبت‌شده با انبار خودرو منهای برگشت،
  بدون مالیات). این سرویس هیچ سند حسابداری‌ای نمی‌سازد.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.inventory import VehicleFuelLog, Warehouse

FUEL_TYPES = {"GASOLINE": "بنزین", "DIESEL": "گازوئیل", "CNG": "گاز", "ELECTRIC": "برق"}
_ZERO = decimal.Decimal(0)
_CENT = decimal.Decimal("0.01")


@dataclass
class FuelFields:
    vehicle_warehouse_id: int
    log_date: datetime.date
    liters: decimal.Decimal
    amount: decimal.Decimal = _ZERO
    odometer_km: decimal.Decimal | None = None
    fuel_type_code: str = "GASOLINE"
    driver_detail_account_id: int | None = None
    note: str | None = None


def _vehicle(session, company_id: int, warehouse_id: int) -> Warehouse:
    w = session.get(Warehouse, warehouse_id)
    if w is None or w.company_id != company_id or w.warehouse_type_code != "VEHICLE":
        raise ValueError("خودروی پخش نامعتبر است.")
    return w


def _odometers(session, vehicle_id: int):
    return select(VehicleFuelLog.log_date, VehicleFuelLog.odometer_km).where(
        VehicleFuelLog.vehicle_warehouse_id == vehicle_id, VehicleFuelLog.odometer_km.is_not(None))


def add_fuel_log(company_id: int, user_id: int | None, f: FuelFields) -> tuple[int, str]:
    """(شناسه، یادداشت)؛ یادداشت خالی است مگر کیلومتر به کارکرد تجهیز نرسیده باشد."""
    if f.liters is None or f.liters <= 0:
        raise ValueError("مقدار سوخت (لیتر) باید بیشتر از صفر باشد.")
    if f.amount is None or f.amount < 0:
        raise ValueError("مبلغ سوخت نمی‌تواند منفی باشد.")
    if f.fuel_type_code not in FUEL_TYPES:
        raise ValueError("نوع سوخت نامعتبر است.")
    if f.odometer_km is not None and f.odometer_km < 0:
        raise ValueError("کیلومترشمار نمی‌تواند منفی باشد.")
    with new_session() as session:
        vehicle = _vehicle(session, company_id, f.vehicle_warehouse_id)
        previous = None
        if f.odometer_km is not None:
            rows = session.execute(_odometers(session, vehicle.warehouse_id)).all()
            if any(d > f.log_date for d, _o in rows):
                raise ValueError("برای این خودرو سوخت‌گیری با کیلومتر در تاریخ بعدی ثبت شده است؛ کیلومتر را به ترتیب تاریخ "
                                 "وارد کنید یا این ردیف را بدون کیلومتر ثبت کنید.")
            previous = max((o for _d, o in rows), default=None)
            if previous is not None and f.odometer_km < previous:
                raise ValueError(f"کیلومترشمار ({f.odometer_km}) از سوخت‌گیری قبلی ({previous}) کمتر است.")
        row = VehicleFuelLog(company_id=company_id, vehicle_warehouse_id=vehicle.warehouse_id, log_date=f.log_date,
                             odometer_km=f.odometer_km, liters=f.liters, amount=f.amount or _ZERO, fuel_type_code=f.fuel_type_code,
                             driver_detail_account_id=f.driver_detail_account_id, note=(f.note or "").strip() or None,
                             created_by_user_id=user_id)
        session.add(row)
        session.commit()
        log_id, asset_id, name = row.fuel_log_id, vehicle.vehicle_asset_id, vehicle.name
    distance = (f.odometer_km - previous) if f.odometer_km is not None and previous is not None else _ZERO
    if distance <= 0 or asset_id is None:
        return log_id, ""
    from peecha.services.fixed_assets import depreciation

    try:
        usage_id = depreciation.record_usage(company_id, user_id, asset_id, f.log_date, distance, source_code="METER",
                                             note=f"کیلومتر خودروی {name} (سوخت‌گیری)")
    except ValueError as exc:
        return log_id, f"کیلومتر به کارکرد تجهیز اضافه نشد: {exc}"
    with new_session() as session:
        session.get(VehicleFuelLog, log_id).usage_id = usage_id
        session.commit()
    return log_id, ""


def delete_fuel_log(company_id: int, fuel_log_id: int) -> None:
    """ردیف دارای کیلومتر فقط اگر آخرین کیلومتر همان خودرو باشد حذف می‌شود (کارکرد ثبت‌شده‌اش هم برمی‌گردد)."""
    from peecha.db.models.fixed_assets import AssetUsage, DepreciationLine, DepreciationRun
    from peecha.services.fixed_assets import common as fac

    with new_session() as session:
        row = session.get(VehicleFuelLog, fuel_log_id)
        if row is None or row.company_id != company_id:
            raise ValueError("سوخت‌گیری نامعتبر است.")
        if row.odometer_km is not None:
            later = session.scalar(select(func.count()).where(
                VehicleFuelLog.vehicle_warehouse_id == row.vehicle_warehouse_id, VehicleFuelLog.odometer_km.is_not(None),
                VehicleFuelLog.fuel_log_id != row.fuel_log_id,
                (VehicleFuelLog.log_date > row.log_date)
                | ((VehicleFuelLog.log_date == row.log_date) & (VehicleFuelLog.fuel_log_id > row.fuel_log_id))))
            if later:
                raise ValueError("فقط آخرین سوخت‌گیری دارای کیلومتر این خودرو حذف می‌شود.")
        usage = session.get(AssetUsage, row.usage_id) if row.usage_id else None
        if usage is not None:
            code, _s, _e = fac.period_of(usage.usage_date)
            posted = session.scalar(select(DepreciationRun.run_id).join(
                DepreciationLine, DepreciationLine.run_id == DepreciationRun.run_id).where(
                DepreciationLine.asset_id == usage.asset_id, DepreciationRun.period_code == code,
                DepreciationRun.status_code == "POSTED"))
            if posted:
                raise ValueError(f"استهلاک دورهٔ {code} این خودرو ثبت شده است؛ کارکرد آن دوره بسته است.")
        session.delete(row)
        session.flush()
        if usage is not None:
            session.delete(usage)
        session.commit()


def _names(session, ids) -> dict[int, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(session.execute(select(DetailAccount.detail_account_id, DetailAccount.name)
                                .where(DetailAccount.detail_account_id.in_(ids))).all())


def _with_distance(session, company_id: int, vehicle_id: int | None) -> list[tuple[VehicleFuelLog, decimal.Decimal | None]]:
    q = select(VehicleFuelLog).where(VehicleFuelLog.company_id == company_id)
    if vehicle_id:
        q = q.where(VehicleFuelLog.vehicle_warehouse_id == vehicle_id)
    last: dict[int, decimal.Decimal] = {}
    out = []
    for r in session.scalars(q.order_by(VehicleFuelLog.vehicle_warehouse_id, VehicleFuelLog.log_date, VehicleFuelLog.fuel_log_id)):
        distance = None
        if r.odometer_km is not None:
            if r.vehicle_warehouse_id in last:
                distance = r.odometer_km - last[r.vehicle_warehouse_id]
            last[r.vehicle_warehouse_id] = r.odometer_km
        out.append((r, distance))
    return out


def list_fuel_logs(company_id: int, vehicle_id: int | None = None, date_from: datetime.date | None = None,
                   date_to: datetime.date | None = None) -> list[SimpleNamespace]:
    with new_session() as session:
        rows = [(r, d) for r, d in _with_distance(session, company_id, vehicle_id)
                if (date_from is None or r.log_date >= date_from) and (date_to is None or r.log_date <= date_to)]
        vehicles = dict(session.execute(select(Warehouse.warehouse_id, Warehouse.name)
                                        .where(Warehouse.company_id == company_id)).all())
        drivers = _names(session, [r.driver_detail_account_id for r, _d in rows])
    out = [SimpleNamespace(fuel_log_id=r.fuel_log_id, vehicle_warehouse_id=r.vehicle_warehouse_id,
                           vehicle_name=vehicles.get(r.vehicle_warehouse_id, ""), log_date=r.log_date, odometer_km=r.odometer_km,
                           distance_km=d, liters=r.liters, amount=r.amount, fuel_type_code=r.fuel_type_code,
                           fuel_type_label=FUEL_TYPES.get(r.fuel_type_code, r.fuel_type_code),
                           driver_name=drivers.get(r.driver_detail_account_id, ""), note=r.note or "",
                           per_100km=(r.liters * 100 / d).quantize(_CENT) if d else None, usage_recorded=r.usage_id is not None)
           for r, d in rows]
    out.sort(key=lambda x: (x.log_date, x.fuel_log_id), reverse=True)
    return out


def vehicle_costs(company_id: int, date_from: datetime.date, date_to: datetime.date) -> list[SimpleNamespace]:
    """هر خودروی پخش: کیلومتر، سوخت، هزینهٔ نگهداری، جمع هزینه، هزینهٔ هر کیلومتر و نسبت به فروش خالص."""
    from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine
    from peecha.db.models.fixed_assets import Asset
    from peecha.db.models.maintenance import WorkOrder
    from peecha.services.maintenance import costs as mcost

    with new_session() as session:
        vehicles = list(session.scalars(select(Warehouse).where(Warehouse.company_id == company_id,
                                                                Warehouse.warehouse_type_code == "VEHICLE")
                                        .order_by(Warehouse.code)))
        if not vehicles:
            return []
        fuel: dict[int, list] = {w.warehouse_id: [_ZERO, _ZERO, _ZERO] for w in vehicles}  # کیلومتر، لیتر، مبلغ
        for r, d in _with_distance(session, company_id, None):
            if date_from <= r.log_date <= date_to and r.vehicle_warehouse_id in fuel:
                acc = fuel[r.vehicle_warehouse_id]
                acc[0] += d or _ZERO
                acc[1] += r.liters
                acc[2] += r.amount
        asset_ids = {w.vehicle_asset_id for w in vehicles if w.vehicle_asset_id}
        assets = {a.asset_id: f"{a.asset_code} — {a.name}" for a in session.scalars(
            select(Asset).where(Asset.asset_id.in_(asset_ids or {0})))}
        when = func.date(func.coalesce(WorkOrder.actual_end, WorkOrder.completed_at, WorkOrder.created_at))
        orders = session.execute(select(WorkOrder.work_order_id, WorkOrder.asset_id).where(
            WorkOrder.company_id == company_id, WorkOrder.asset_id.in_(asset_ids or {0}), WorkOrder.status_code != "CANCELLED",
            when.between(date_from, date_to))).all()
        totals = mcost.summary_in_session(session, [wid for wid, _a in orders])
        maintenance: dict[int, decimal.Decimal] = {}
        count: dict[int, int] = {}
        for wid, asset_id in orders:
            maintenance[asset_id] = maintenance.get(asset_id, _ZERO) + totals[wid].total
            count[asset_id] = count.get(asset_id, 0) + 1
        net = CommercialDocumentLine.quantity * CommercialDocumentLine.unit_price - func.coalesce(CommercialDocumentLine.discount_amount, 0)

        def posted_net(doc_type: str) -> dict[int, decimal.Decimal]:
            return {wid: decimal.Decimal(v or 0) for wid, v in session.execute(
                select(CommercialDocument.warehouse_id, func.sum(net))
                .join(CommercialDocumentLine, CommercialDocumentLine.document_id == CommercialDocument.document_id)
                .where(CommercialDocument.company_id == company_id, CommercialDocument.status_code == "POSTED",
                       CommercialDocument.document_type_code == doc_type, CommercialDocument.warehouse_id.in_(list(fuel)),
                       CommercialDocument.document_date.between(date_from, date_to))
                .group_by(CommercialDocument.warehouse_id)).all()}

        sales, returns = posted_net("SALES_INVOICE"), posted_net("SALES_RETURN")
    out = []
    for w in vehicles:
        km, liters, fuel_amount = fuel[w.warehouse_id]
        upkeep = maintenance.get(w.vehicle_asset_id, _ZERO) if w.vehicle_asset_id else _ZERO
        total = fuel_amount + upkeep
        net_sales = (sales.get(w.warehouse_id, _ZERO) - returns.get(w.warehouse_id, _ZERO)).quantize(_CENT)
        out.append(SimpleNamespace(
            vehicle_warehouse_id=w.warehouse_id, vehicle_name=w.name, plate=w.vehicle_plate_number or "",
            asset_label=assets.get(w.vehicle_asset_id, "") if w.vehicle_asset_id else "", km=km, liters=liters,
            fuel_amount=fuel_amount, work_orders=count.get(w.vehicle_asset_id, 0) if w.vehicle_asset_id else 0,
            maintenance_amount=upkeep, total_cost=total, net_sales=net_sales,
            per_km=(total / km).quantize(_CENT) if km else None,
            per_100km=(liters * 100 / km).quantize(_CENT) if km else None,
            cost_percent=(total * 100 / net_sales).quantize(_CENT) if net_sales > 0 else None))
    return out
