"""R370: اثربخشی کلی تجهیزات (OEE).

هر گزارش شیفت ایستگاه: زمان برنامه‌ای تولید (دقیقه)، توقف‌های ناخواسته با علت، نرخ ایده‌آل (واحد در ساعت)، تولید کل و مردود.
- زمان کارکرد = برنامه‌ای − توقف‌ها؛ دسترس‌پذیری = کارکرد ÷ برنامه‌ای.
- عملکرد = (تولید کل ÷ نرخ ایده‌آل) ÷ زمان کارکرد؛ تولیدی که با نرخ ایده‌آل در زمان کارکرد جا نشود پذیرفته نمی‌شود (نرخ اشتباه است).
- کیفیت = سالم ÷ کل؛ OEE = دسترس‌پذیری × عملکرد × کیفیت (معیار جهانی ۸۵٪).
- پیشنهاد خودکار از داده‌های موجود (فقط پیشنهاد، چیزی ثبت نمی‌شود): زمان شیفت ایستگاه در روز کاری، توقف «خرابی» ماشین‌های
  ایستگاه در نگهداری، مقدار عملیات تمام‌شدهٔ دستورهای تولید در ایستگاه و ضایعات محصول همان دستورها در همان روز.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import cast, func, select
from sqlalchemy.types import Date

from peecha.db.base import new_session
from peecha.db.models.production import OeeLog, OeeStop, OrderOperation, OrderTransaction, ProductionOrder, WorkCenter

ZERO = decimal.Decimal(0)
HUNDRED = decimal.Decimal(100)
SIXTY = decimal.Decimal(60)
WORLD_CLASS = decimal.Decimal(85)
REASONS = {"BREAKDOWN": "خرابی", "SETUP": "راه‌اندازی و تعویض", "MATERIAL": "کمبود مواد", "QUALITY": "مشکل کیفیت",
           "OPERATOR": "نبود نیرو", "SMALL_STOP": "توقف‌های کوتاه", "OTHER": "سایر"}


@dataclass
class Stop:
    reason_code: str
    minutes: int
    note: str = ""


@dataclass
class LogFields:
    work_center_id: int
    log_date: datetime.date
    planned_minutes: int
    ideal_rate_per_hour: decimal.Decimal | None
    total_qty: decimal.Decimal = ZERO
    reject_qty: decimal.Decimal = ZERO
    shift_no: int = 1
    order_id: int | None = None
    notes: str | None = None
    stops: list[Stop] = field(default_factory=list)


@dataclass
class Metrics:
    planned_minutes: decimal.Decimal = ZERO
    downtime_minutes: decimal.Decimal = ZERO
    ideal_minutes: decimal.Decimal = ZERO
    total_qty: decimal.Decimal = ZERO
    reject_qty: decimal.Decimal = ZERO

    @property
    def run_minutes(self) -> decimal.Decimal:
        return self.planned_minutes - self.downtime_minutes

    @property
    def good_qty(self) -> decimal.Decimal:
        return self.total_qty - self.reject_qty

    @property
    def availability(self) -> decimal.Decimal | None:
        return (self.run_minutes * HUNDRED / self.planned_minutes).quantize(decimal.Decimal("0.1")) if self.planned_minutes else None

    @property
    def performance(self) -> decimal.Decimal | None:
        return (self.ideal_minutes * HUNDRED / self.run_minutes).quantize(decimal.Decimal("0.1")) if self.run_minutes else None

    @property
    def quality(self) -> decimal.Decimal | None:
        return (self.good_qty * HUNDRED / self.total_qty).quantize(decimal.Decimal("0.1")) if self.total_qty else None

    @property
    def oee(self) -> decimal.Decimal | None:
        if not self.planned_minutes:
            return None
        if not self.total_qty:
            return ZERO.quantize(decimal.Decimal("0.1"))
        # OEE = زمان ایده‌آل تولید سالم ÷ زمان برنامه‌ای
        good_ideal = self.ideal_minutes * self.good_qty / self.total_qty
        return (good_ideal * HUNDRED / self.planned_minutes).quantize(decimal.Decimal("0.1"))

    @property
    def speed_loss_minutes(self) -> decimal.Decimal:
        return max(ZERO, self.run_minutes - self.ideal_minutes)

    @property
    def quality_loss_minutes(self) -> decimal.Decimal:
        return (self.ideal_minutes * self.reject_qty / self.total_qty) if self.total_qty else ZERO

    def add(self, other: "Metrics") -> None:
        for name in ("planned_minutes", "downtime_minutes", "ideal_minutes", "total_qty", "reject_qty"):
            setattr(self, name, getattr(self, name) + getattr(other, name))


@dataclass
class LogRow:
    log_id: int
    work_center_id: int
    work_center: str
    log_date: datetime.date
    shift_no: int
    ideal_rate_per_hour: decimal.Decimal
    order_id: int | None
    notes: str
    stops: list[Stop]
    metrics: Metrics


def _work_center(session, company_id: int, work_center_id: int) -> WorkCenter:
    wc = session.get(WorkCenter, work_center_id)
    if wc is None or wc.company_id != company_id:
        raise ValueError("مرکز کاری نامعتبر است.")
    return wc


def _metrics(planned: int, stops: list[Stop], ideal_rate: decimal.Decimal, total: decimal.Decimal, reject: decimal.Decimal) -> Metrics:
    down = sum((decimal.Decimal(s.minutes) for s in stops), ZERO)
    return Metrics(decimal.Decimal(planned), down, decimal.Decimal(total) * SIXTY / decimal.Decimal(ideal_rate), decimal.Decimal(total),
                   decimal.Decimal(reject))


def _working_day(wc: WorkCenter, day: datetime.date) -> bool:
    return (day.weekday() + 2) % 7 < wc.working_days_per_week


def suggest(company_id: int, work_center_id: int, log_date: datetime.date, shift_no: int = 1) -> LogFields:
    """پیشنهاد گزارش شیفت از داده‌های موجود؛ مقدارهای روز بین شیفت‌های ایستگاه تقسیم می‌شوند."""
    from peecha.db.models.maintenance import DowntimeEvent
    from peecha.services.maintenance import availability as mnt
    from peecha.services.maintenance import common as mc
    from peecha.services.production import master as pm

    with new_session() as session:
        wc = _work_center(session, company_id, work_center_id)
        shifts = max(int(wc.shifts_per_day or 1), 1)
        planned = int(decimal.Decimal(wc.hours_per_shift) * SIXTY) if _working_day(wc, log_date) else 0
        machines, _linked = pm._machines(session, wc)
        d0 = datetime.datetime.combine(log_date, datetime.time()).astimezone()
        d1 = d0 + datetime.timedelta(days=1)
        now = datetime.datetime.now().astimezone()
        breakdown = ZERO
        for ev in session.scalars(select(DowntimeEvent).where(
                DowntimeEvent.asset_id.in_([a.asset_id for a in machines] or [0]), DowntimeEvent.downtime_type_code != "PLANNED",
                DowntimeEvent.down_from < d1)):
            start, end = mc.aware(ev.down_from), mc.aware(ev.available_at) or now
            if end > d0:
                breakdown += mnt.hours_between(max(start, d0), min(end, d1)) * SIXTY
        # چند ماشین: میانگین توقف هر ماشین (ایستگاه با یک ماشین از کار نمی‌افتد)
        if machines:
            breakdown = breakdown / len(machines)
        stops = []
        minutes = min(int(breakdown / shifts), planned)
        if minutes > 0:
            stops.append(Stop("BREAKDOWN", minutes, "از توقف‌های ثبت‌شده در نگهداری"))
        total = session.scalar(select(func.coalesce(func.sum(OrderOperation.completed_qty), 0)).where(
            OrderOperation.work_center_id == work_center_id, OrderOperation.status_code == "DONE",
            cast(OrderOperation.finished_at, Date) == log_date)) or ZERO
        orders = select(OrderOperation.order_id).where(OrderOperation.work_center_id == work_center_id)
        scrap = session.scalar(select(func.coalesce(func.sum(OrderTransaction.quantity), 0)).where(
            OrderTransaction.company_id == company_id, OrderTransaction.txn_type == "SCRAP", OrderTransaction.txn_date == log_date,
            OrderTransaction.material_id.is_(None), OrderTransaction.order_id.in_(orders))) or ZERO
        rate = decimal.Decimal(wc.hourly_capacity_qty) if wc.hourly_capacity_qty else None
    q = decimal.Decimal("0.001")
    total, scrap = (decimal.Decimal(total) / shifts).quantize(q), (decimal.Decimal(scrap) / shifts).quantize(q)
    return LogFields(work_center_id, log_date, planned, rate, total + scrap, scrap, shift_no, stops=stops)


def save_log(company_id: int, user_id: int | None, f: LogFields, log_id: int | None = None) -> int:
    if not 1 <= int(f.shift_no) <= 3:
        raise ValueError("شمارهٔ شیفت از ۱ تا ۳ است.")
    if int(f.planned_minutes or 0) <= 0 or int(f.planned_minutes) > 24 * 60:
        raise ValueError("زمان برنامه‌ای تولید (دقیقه) باید بیشتر از صفر و حداکثر یک شبانه‌روز باشد.")
    if f.ideal_rate_per_hour is None or decimal.Decimal(f.ideal_rate_per_hour) <= 0:
        raise ValueError("نرخ ایده‌آل تولید (واحد در ساعت) را وارد کنید.")
    total, reject = decimal.Decimal(f.total_qty or 0), decimal.Decimal(f.reject_qty or 0)
    if total < 0 or reject < 0 or reject > total:
        raise ValueError("مقدار مردود نمی‌تواند از تولید کل بیشتر باشد.")
    for s in f.stops:
        if s.reason_code not in REASONS or int(s.minutes or 0) <= 0:
            raise ValueError("هر توقف علت و دقیقهٔ مثبت می‌خواهد.")
    m = _metrics(int(f.planned_minutes), f.stops, decimal.Decimal(f.ideal_rate_per_hour), total, reject)
    if m.downtime_minutes > m.planned_minutes:
        raise ValueError("جمع توقف‌ها از زمان برنامه‌ای بیشتر است.")
    if m.ideal_minutes > m.run_minutes:
        raise ValueError("این مقدار تولید با نرخ ایده‌آل در زمان کارکرد جا نمی‌شود؛ نرخ ایده‌آل یا توقف‌ها را بررسی کنید.")
    if f.log_date is None or f.log_date > datetime.date.today():
        raise ValueError("گزارش روز آینده ثبت نمی‌شود.")
    with new_session() as session:
        _work_center(session, company_id, f.work_center_id)
        if f.order_id is not None:
            order = session.get(ProductionOrder, f.order_id)
            if order is None or order.company_id != company_id:
                raise ValueError("دستور تولید نامعتبر است.")
        if session.scalar(select(OeeLog.log_id).where(OeeLog.work_center_id == f.work_center_id, OeeLog.log_date == f.log_date,
                                                      OeeLog.shift_no == int(f.shift_no), OeeLog.log_id != (log_id or 0))):
            raise ValueError("برای این ایستگاه، روز و شیفت گزارش ثبت شده است.")
        if log_id is None:
            row = OeeLog(company_id=company_id, created_by_user_id=user_id)
            session.add(row)
        else:
            row = session.get(OeeLog, log_id)
            if row is None or row.company_id != company_id:
                raise ValueError("گزارش نامعتبر است.")
            for old in session.scalars(select(OeeStop).where(OeeStop.log_id == log_id)):
                session.delete(old)
        row.work_center_id, row.log_date, row.shift_no = f.work_center_id, f.log_date, int(f.shift_no)
        row.planned_minutes, row.ideal_rate_per_hour = int(f.planned_minutes), decimal.Decimal(f.ideal_rate_per_hour)
        row.total_qty, row.reject_qty, row.order_id = total, reject, f.order_id
        row.notes = (f.notes or "").strip() or None
        session.flush()
        for s in f.stops:
            session.add(OeeStop(log_id=row.log_id, reason_code=s.reason_code, minutes=int(s.minutes), note=(s.note or "").strip() or None))
        session.commit()
        return row.log_id


def delete_log(company_id: int, log_id: int) -> None:
    with new_session() as session:
        row = session.get(OeeLog, log_id)
        if row is None or row.company_id != company_id:
            raise ValueError("گزارش نامعتبر است.")
        session.delete(row)
        session.commit()


def list_logs(company_id: int, date_from: datetime.date, date_to: datetime.date, work_center_id: int | None = None) -> list[LogRow]:
    with new_session() as session:
        q = select(OeeLog, WorkCenter.name).join(WorkCenter, WorkCenter.work_center_id == OeeLog.work_center_id).where(
            OeeLog.company_id == company_id, OeeLog.log_date.between(date_from, date_to))
        if work_center_id is not None:
            q = q.where(OeeLog.work_center_id == work_center_id)
        rows = session.execute(q.order_by(OeeLog.log_date.desc(), WorkCenter.name, OeeLog.shift_no)).all()
        stops = defaultdict(list)
        for s in session.scalars(select(OeeStop).where(OeeStop.log_id.in_([r.log_id for r, _n in rows] or [0])).order_by(OeeStop.stop_id)):
            stops[s.log_id].append(Stop(s.reason_code, s.minutes, s.note or ""))
    return [LogRow(r.log_id, r.work_center_id, name, r.log_date, r.shift_no, r.ideal_rate_per_hour, r.order_id, r.notes or "",
                   stops[r.log_id], _metrics(r.planned_minutes, stops[r.log_id], r.ideal_rate_per_hour, r.total_qty, r.reject_qty))
            for r, name in rows]


@dataclass
class CenterSummary:
    work_center_id: int
    work_center: str
    logs: int
    metrics: Metrics
    losses: dict[str, decimal.Decimal]


def summary(company_id: int, date_from: datetime.date, date_to: datetime.date) -> tuple[Metrics, list[CenterSummary]]:
    """جمع کل و هر ایستگاه در بازه، با دقیقهٔ توقف هر علت؛ ایستگاه با کمترین OEE اول."""
    total = Metrics()
    centers: dict[int, CenterSummary] = {}
    for log in list_logs(company_id, date_from, date_to):
        c = centers.setdefault(log.work_center_id, CenterSummary(log.work_center_id, log.work_center, 0, Metrics(), defaultdict(lambda: ZERO)))
        c.logs += 1
        c.metrics.add(log.metrics)
        total.add(log.metrics)
        for s in log.stops:
            c.losses[s.reason_code] += decimal.Decimal(s.minutes)
    return total, sorted(centers.values(), key=lambda c: (c.metrics.oee if c.metrics.oee is not None else HUNDRED, c.work_center))


def losses(company_id: int, date_from: datetime.date, date_to: datetime.date) -> list[tuple[str, decimal.Decimal]]:
    """زیان‌های زمانی کل بازه (دقیقه): توقف هر علت، افت سرعت و افت کیفیت؛ بزرگ‌ترین اول."""
    out: dict[str, decimal.Decimal] = defaultdict(lambda: ZERO)
    speed = quality = ZERO
    for log in list_logs(company_id, date_from, date_to):
        for s in log.stops:
            out[REASONS[s.reason_code]] += decimal.Decimal(s.minutes)
        speed += log.metrics.speed_loss_minutes
        quality += log.metrics.quality_loss_minutes
    out["افت سرعت"] = speed
    out["تولید مردود"] = quality
    return sorted(((k, v.quantize(decimal.Decimal("0.1"))) for k, v in out.items() if v), key=lambda kv: -kv[1])


def daily_trend(company_id: int, work_center_id: int | None, date_from: datetime.date, date_to: datetime.date) -> list[tuple[datetime.date, Metrics]]:
    days: dict[datetime.date, Metrics] = defaultdict(Metrics)
    for log in list_logs(company_id, date_from, date_to, work_center_id):
        days[log.log_date].add(log.metrics)
    return sorted(days.items())
