"""R366: سبد پروژه‌ها با مدیریت ارزش کسب‌شده.

- بودجهٔ کل (BAC): هزینهٔ خط مبنا، یا اگر خط مبنا ندارد هزینهٔ برنامه‌ای فعالیت‌ها.
- ارزش برنامه‌ای (PV) = BAC × پیشرفت برنامه‌ای تا امروز؛ ارزش کسب‌شده (EV) = BAC × پیشرفت واقعی.
- هزینهٔ واقعی (AC) = هزینهٔ دفاتر با تفصیلی پروژه + هزینهٔ کارکرد تاییدشده.
- شاخص زمان SPI = EV ÷ PV و شاخص هزینه CPI = EV ÷ AC (اگر مخرج صفر باشد خالی)؛ برآورد هزینهٔ تکمیل EAC = BAC ÷ CPI.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from peecha.services.projects import billing, changes, core, costs
from peecha.services.projects import schedule as sch

ZERO = decimal.Decimal(0)
_R = decimal.Decimal("0.01")


@dataclass
class PortfolioRow:
    project_id: int
    code: str
    name: str
    customer: str
    manager: str
    status_code: str
    status_label: str
    start: datetime.date
    finish: datetime.date | None
    target_end_date: datetime.date | None
    percent: decimal.Decimal
    planned_percent: decimal.Decimal
    contract_amount: decimal.Decimal
    approved_changes: decimal.Decimal
    open_changes: int
    bac: decimal.Decimal
    pv: decimal.Decimal
    ev: decimal.Decimal
    ac: decimal.Decimal
    revenue: decimal.Decimal
    billed: decimal.Decimal
    invoiced: decimal.Decimal
    late_tasks: int

    @property
    def spi(self) -> decimal.Decimal | None:
        return (self.ev / self.pv).quantize(_R) if self.pv else None

    @property
    def cpi(self) -> decimal.Decimal | None:
        return (self.ev / self.ac).quantize(_R) if self.ac else None

    @property
    def eac(self) -> decimal.Decimal:
        cpi = self.cpi
        return (self.bac / cpi).quantize(_R) if cpi else self.bac

    @property
    def margin(self) -> decimal.Decimal:
        return self.revenue - self.ac

    @property
    def late(self) -> bool:
        return bool(self.finish and self.target_end_date and self.finish > self.target_end_date)

    @property
    def health(self) -> str:
        """سبز/زرد/قرمز: قرمز اگر پایان برنامه از هدف بگذرد یا یکی از شاخص‌ها زیر ۰٫۹ باشد؛ زرد زیر ۱."""
        values = [v for v in (self.spi, self.cpi) if v is not None]
        if self.late or any(v < decimal.Decimal("0.9") for v in values):
            return "RED"
        if self.late_tasks or any(v < 1 for v in values):
            return "AMBER"
        return "GREEN"


HEALTH = {"GREEN": "در مسیر", "AMBER": "نیازمند توجه", "RED": "در خطر"}


def portfolio(company_id: int, statuses: tuple[str, ...] | None = ("PLANNING", "ACTIVE", "ON_HOLD"),
              as_of: datetime.date | None = None) -> list[PortfolioRow]:
    out = []
    for p in core.list_projects(company_id, statuses):
        plan = sch.compute(company_id, p.project_id, as_of)
        c = costs.project_cost(company_id, p.project_id)
        bill = billing.billing_summary(company_id, p.project_id)
        approved, _days, open_count = changes.approved_totals(company_id, p.project_id)
        bac = c.baseline_cost if c.baseline_cost is not None else c.planned_cost
        out.append(PortfolioRow(
            p.project_id, p.code, p.name, p.customer, p.manager, p.status_code, p.status_label, p.start_date,
            plan.finish if plan.tasks else None, p.target_end_date, plan.percent, plan.planned_percent, p.contract_amount, approved,
            open_count, bac, (bac * plan.planned_percent / 100).quantize(_R), (bac * plan.percent / 100).quantize(_R), c.total_cost,
            c.revenue, bill["gross"], bill["invoiced"], plan.late_count))
    return out


def totals(rows: list[PortfolioRow]) -> dict[str, decimal.Decimal | int]:
    return {"count": len(rows), "contract": sum((r.contract_amount for r in rows), ZERO), "bac": sum((r.bac for r in rows), ZERO),
            "ev": sum((r.ev for r in rows), ZERO), "ac": sum((r.ac for r in rows), ZERO), "billed": sum((r.billed for r in rows), ZERO),
            "late": sum(1 for r in rows if r.late), "red": sum(1 for r in rows if r.health == "RED")}
