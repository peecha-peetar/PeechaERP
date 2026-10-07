"""اتصال دارایی به تولید — R264: ماشین ← مرکز کار ← ساعت کارکرد ← استهلاک ← نرخ ماشین ← سفارش تولید.

نرخ هر ساعت ماشین در یک دوره = استهلاک ثبت‌شدهٔ همان دوره ÷ ساعت کارکرد همان دوره
(اگر «نرخ ماشین» دستی تعیین شده باشد، همان مبنا است). تخصیص به سفارش تولید فقط ثبت می‌شود (fa.machine_cost_allocations)
تا موتور بهای تولید در فاز بعد مصرفش کند — سند حسابداری نمی‌سازد (هزینهٔ استهلاک قبلاً با اجرای دوره ثبت شده).
"""

from __future__ import annotations

import decimal
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.fixed_assets import Asset, AssetUsage, MachineCostAllocation
from peecha.services.fixed_assets import common as c
from peecha.services.fixed_assets import depreciation as fd

ZERO = c.ZERO


def machine_rate(company_id: int, asset_id: int, period_code: str) -> SimpleNamespace:
    """(استهلاک دوره، ساعت کارکرد، نرخ محاسبه‌شده، نرخ مؤثر)."""
    code, start, end = c.period_from_code(period_code)
    with new_session() as session:
        asset = session.get(Asset, asset_id)
        if asset is None or asset.company_id != company_id:
            raise ValueError("دارایی نامعتبر است.")
        depreciation = fd.depreciation_for_period(session, asset_id, code)
        hours = fd.usage_between(session, asset_id, start, end)
        if not hours and asset.standard_hours:
            hours = decimal.Decimal(asset.standard_hours) / 12
        computed = (depreciation / hours).quantize(decimal.Decimal("0.000001")) if hours else None
        effective = decimal.Decimal(asset.machine_rate) if asset.machine_rate else computed
        return SimpleNamespace(asset_id=asset_id, period_code=code, depreciation=depreciation, hours=hours,
                               computed_rate=computed, rate=effective, work_center_code=asset.work_center_code,
                               cost_center_detail_account_id=asset.cost_center_detail_account_id)


def allocate_to_order(company_id: int, user_id: int | None, asset_id: int, period_code: str, production_order_ref: str,
                      hours: decimal.Decimal) -> SimpleNamespace:
    """بهای ماشین برای یک سفارش تولید = نرخ × ساعت؛ جمع ساعت‌های تخصیص از کارکرد دوره بیشتر نمی‌شود."""
    hours = decimal.Decimal(hours)
    if hours <= 0 or not (production_order_ref or "").strip():
        raise ValueError("سفارش تولید و ساعت مثبت الزامی است.")
    info = machine_rate(company_id, asset_id, period_code)
    if info.rate is None:
        raise ValueError("نرخ ماشین برای این دوره قابل‌محاسبه نیست (استهلاک یا کارکرد ثبت نشده).")
    with new_session() as session:
        asset = c.lock_asset(session, asset_id, company_id)
        if not asset.is_production_machine:
            raise ValueError("این دارایی «ماشین تولیدی» تعریف نشده است.")
        used = decimal.Decimal(session.scalar(select(func.coalesce(func.sum(MachineCostAllocation.hours), 0)).where(
            MachineCostAllocation.asset_id == asset_id, MachineCostAllocation.period_code == info.period_code)) or 0)
        if info.hours and used + hours > info.hours:
            raise ValueError(f"ساعت تخصیص ({used + hours}) از کارکرد ثبت‌شدهٔ دوره ({info.hours}) بیشتر است.")
        row = MachineCostAllocation(company_id=company_id, asset_id=asset_id, period_code=info.period_code,
                                    production_order_ref=production_order_ref.strip(), hours=hours, rate_per_hour=info.rate,
                                    amount=c.money(info.rate * hours),
                                    cost_center_detail_account_id=asset.cost_center_detail_account_id)
        session.add(row)
        session.flush()
        c.audit(session, company_id, user_id, asset_id, "MACHINE_COST",
                {"order": production_order_ref, "hours": str(hours), "amount": str(row.amount)})
        session.commit()
        return SimpleNamespace(allocation_id=row.allocation_id, amount=row.amount, rate=row.rate_per_hour)


def order_machine_cost(company_id: int, production_order_ref: str) -> decimal.Decimal:
    """جمع بهای ماشین یک سفارش تولید — نقطهٔ مصرف موتور بهای تولید."""
    with new_session() as session:
        return decimal.Decimal(session.scalar(select(func.coalesce(func.sum(MachineCostAllocation.amount), 0)).where(
            MachineCostAllocation.company_id == company_id, MachineCostAllocation.production_order_ref == production_order_ref)) or 0)


def machines(company_id: int, work_center_code: str | None = None) -> list[SimpleNamespace]:
    with new_session() as session:
        q = select(Asset).where(Asset.company_id == company_id, Asset.is_production_machine.is_(True),
                                Asset.status_code.not_in(c.CLOSED_STATUSES))
        if work_center_code:
            q = q.where(Asset.work_center_code == work_center_code)
        rows = list(session.scalars(q.order_by(Asset.work_center_code, Asset.asset_code)))
        hours = dict(session.execute(select(AssetUsage.asset_id, func.sum(AssetUsage.units))
                                     .where(AssetUsage.asset_id.in_([a.asset_id for a in rows] or [-1]))
                                     .group_by(AssetUsage.asset_id)).all())
        return [SimpleNamespace(asset_id=a.asset_id, asset_code=a.asset_code, name=a.name, work_center_code=a.work_center_code,
                                production_line=a.production_line, capacity_per_hour=a.capacity_per_hour,
                                standard_hours=a.standard_hours, actual_hours=decimal.Decimal(hours.get(a.asset_id) or 0),
                                machine_rate=a.machine_rate, book_value=a.book_value,
                                cost_center_detail_account_id=a.cost_center_detail_account_id) for a in rows]
