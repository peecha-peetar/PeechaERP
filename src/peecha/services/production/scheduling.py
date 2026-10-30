"""R371: زمان‌بندی با ظرفیت محدود (شبیه‌سازی؛ در دستورها چیزی ثبت نمی‌شود).

- عملیات باقی‌ماندهٔ دستورهای باز (برنامه‌ریزی‌شده، آزادشده، در جریان) با همان ساعت استانداردی که بار ظرفیت حساب می‌کند
  (بیشینهٔ ساعت دستمزد، ماشین و کل عملیات × نسبت مقدار مانده؛ دستور بدون عملیات از مسیر تولیدش).
- ظرفیت هر مرکز کاری در هر روز همان ظرفیت در دسترس برنامه‌ریزی است (روز کاری، شیفت، راندمان، ماشین‌های خارج از دسترس و توقف
  برنامه‌ریزی‌شدهٔ نگهداری).
- ترتیب دستورها: اولویت (۱ بالاترین) و بعد موعد، یا فقط موعد؛ عملیات هر دستور به‌ترتیب و هر عملیات بعد از پایان قبلی (همان روز
  اگر ظرفیت باشد) و نه پیش از تاریخ شروع دستور. ساعت هر عملیات روی ظرفیت آزاد روزها پخش می‌شود.
- عملیاتی که در افق جا نشود «خارج از افق» است؛ دستوری که پایانش بعد از موعد باشد «دیرکرد» دارد.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.production import OrderOperation, ProductionOrder, RoutingOperation, WorkCenter
from peecha.services.production import common as c
from peecha.services.production import master as pm

ZERO = decimal.Decimal(0)
OPEN = ("PLANNED", "RELEASED", "IN_PROGRESS")
RULES = {"PRIORITY": "اولویت، سپس موعد", "EDD": "زودترین موعد"}
_EPS = decimal.Decimal("0.0001")


@dataclass
class SlotOp:
    order_id: int
    order_code: str
    seq: int
    name: str
    work_center_id: int | None
    work_center: str
    hours: decimal.Decimal
    start: datetime.date | None = None
    finish: datetime.date | None = None
    scheduled: bool = True


@dataclass
class OrderPlan:
    order_id: int
    order_code: str
    item_label: str
    quantity: decimal.Decimal
    priority: int
    start_date: datetime.date
    due_date: datetime.date
    status_code: str
    ops: list[SlotOp] = field(default_factory=list)

    @property
    def finish(self) -> datetime.date | None:
        if any(not o.scheduled for o in self.ops):
            return None
        dates = [o.finish for o in self.ops if o.finish]
        return max(dates) if dates else None

    @property
    def late_days(self) -> int | None:
        if self.finish is None:
            return None
        return max(0, (self.finish - self.due_date).days)


@dataclass
class CenterDay:
    capacity: decimal.Decimal
    used: decimal.Decimal = ZERO


@dataclass
class Result:
    start: datetime.date
    end: datetime.date
    rule: str
    orders: list[OrderPlan]
    load: dict[int, dict[datetime.date, CenterDay]]
    centers: dict[int, str]

    @property
    def late(self) -> list[OrderPlan]:
        return [o for o in self.orders if o.finish is None or (o.late_days or 0) > 0]

    def utilization(self, work_center_id: int) -> decimal.Decimal | None:
        days = self.load.get(work_center_id, {})
        cap = sum((d.capacity for d in days.values()), ZERO)
        used = sum((d.used for d in days.values()), ZERO)
        return (used * 100 / cap).quantize(decimal.Decimal("0.1")) if cap else None


def _remaining_ops(session, o: ProductionOrder, centers: dict[int, WorkCenter]) -> list[SlotOp]:
    ratio = decimal.Decimal(o.remaining_qty) / decimal.Decimal(o.planned_qty) if o.planned_qty else ZERO
    out = []
    ops = list(session.scalars(select(OrderOperation).where(OrderOperation.order_id == o.order_id).order_by(OrderOperation.seq)))
    if ops:
        for op in ops:
            if op.status_code in ("DONE", "SKIPPED"):
                continue
            hours = max(decimal.Decimal(op.std_labor_hours), decimal.Decimal(op.std_machine_hours), decimal.Decimal(op.std_elapsed_hours)) * ratio
            out.append(SlotOp(o.order_id, o.order_code, op.seq, op.name, op.work_center_id,
                              centers[op.work_center_id].name if op.work_center_id in centers else "", hours.quantize(_EPS)))
    elif o.routing_id:
        for op in session.scalars(select(RoutingOperation).where(RoutingOperation.routing_id == o.routing_id).order_by(RoutingOperation.seq)):
            hours = pm.op_hours(op, o.remaining_qty).elapsed_hours
            out.append(SlotOp(o.order_id, o.order_code, op.seq, op.name, op.work_center_id,
                              centers[op.work_center_id].name if op.work_center_id in centers else "", hours))
    return out


def schedule(company_id: int, start: datetime.date | None = None, horizon_days: int = 60, rule: str = "PRIORITY") -> Result:
    if rule not in RULES:
        raise ValueError("قاعدهٔ ترتیب نامعتبر است.")
    if not 1 <= int(horizon_days) <= 366:
        raise ValueError("افق زمان‌بندی از ۱ تا ۳۶۶ روز است.")
    start = start or datetime.date.today()
    end = start + datetime.timedelta(days=int(horizon_days) - 1)
    days = [start + datetime.timedelta(days=i) for i in range(int(horizon_days))]
    with new_session() as session:
        centers = {w.work_center_id: w for w in session.scalars(select(WorkCenter).where(WorkCenter.company_id == company_id))}
        load: dict[int, dict[datetime.date, CenterDay]] = {}
        for wc_id, wc in centers.items():
            if wc.is_active:
                load[wc_id] = {d: CenterDay(pm.available_capacity(session, wc, d, d).hours) for d in days}
        orders = list(session.scalars(select(ProductionOrder).where(ProductionOrder.company_id == company_id,
                                                                   ProductionOrder.status_code.in_(OPEN))))
        labels = c.item_labels(session, [o.item_id for o in orders])
        key = (lambda o: (o.priority, o.due_date, o.order_id)) if rule == "PRIORITY" else (lambda o: (o.due_date, o.priority, o.order_id))
        plans = []
        for o in sorted(orders, key=key):
            plan = OrderPlan(o.order_id, o.order_code, labels.get(o.item_id, ""), decimal.Decimal(o.remaining_qty), o.priority,
                             o.start_date, o.due_date, o.status_code, _remaining_ops(session, o, centers))
            plans.append(plan)
    for plan in plans:
        earliest = max(start, plan.start_date)
        blocked = False
        for op in plan.ops:
            if blocked:
                op.scheduled = False
                continue
            if op.work_center_id not in load or op.hours <= 0:
                op.start = op.finish = earliest   # بدون مرکز کاری یا بدون ساعت: محدودیت ظرفیت ندارد
                continue
            need = op.hours
            for d in days:
                if d < earliest:
                    continue
                slot = load[op.work_center_id][d]
                free = slot.capacity - slot.used
                if free <= _EPS:
                    continue
                take = min(free, need)
                slot.used += take
                need -= take
                op.start = op.start or d
                op.finish = d
                if need <= _EPS:
                    break
            if need > _EPS:
                op.scheduled = False
                blocked = True
                continue
            earliest = op.finish
    return Result(start, end, rule, plans, load, {k: w.name for k, w in centers.items() if k in load})


def gantt_rows(result: Result) -> list:
    """ردیف‌های نمودار گانت (همان نمودار پروژه): هر دستور یک فاز و عملیاتش زیر آن؛ دیرکرد قرمز."""
    from types import SimpleNamespace

    rows = []
    for n, o in enumerate(result.orders, start=1):
        dated = [op for op in o.ops if op.start]
        if not dated:
            continue
        late = o.finish is None or (o.late_days or 0) > 0
        rows.append(SimpleNamespace(wbs=str(n), name=f"{o.order_code} {o.item_label}", level=0, is_summary=True, is_milestone=False,
                                    start=min(op.start for op in dated), finish=max(op.finish for op in dated), critical=late,
                                    percent=decimal.Decimal(0), baseline_start=None, baseline_finish=o.due_date, total_float=0))
        for op in dated:
            rows.append(SimpleNamespace(wbs=f"{n}.{op.seq}", name=f"{op.name} ({op.work_center})", level=1, is_summary=False,
                                        is_milestone=False, start=op.start, finish=op.finish, critical=late, percent=decimal.Decimal(0),
                                        baseline_start=None, baseline_finish=None, total_float=0))
    starts = [r.start for r in rows] or [result.start]
    finishes = [r.finish for r in rows] or [result.start]
    return SimpleNamespace(tasks=rows, start=min(starts), finish=max(finishes), calendar=None)
