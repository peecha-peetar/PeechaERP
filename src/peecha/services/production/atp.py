"""R373: تعهد تحویل (ATP) و سناریوی تقاضا — فقط محاسبه؛ در سفارش، رزرو یا دستور تولید چیزی ثبت نمی‌شود.

- منابع همان منابع برنامه‌ریزی تولید است: موجودی آزاد (موجودی منهای رزرو)، ماندهٔ سفارش‌های خرید باز در تاریخ تحویل،
  ماندهٔ دستورهای تولید باز در تاریخ موعد، ماندهٔ فاکتورنشدهٔ سفارش‌های فروش باز (منهای بخشی که رزرو شده و از موجودی آزاد
  کم شده است) و نیاز مواد دستورهای باز در تاریخ شروع. ردیف‌های سررسیدگذشته در روز اول حساب می‌شوند.
- موجودی پیش‌بینی هر روز = روز قبل + ورودی − خروجی. «قابل تعهد» هر روز کمترین موجودی پیش‌بینی از همان روز تا پایان افق است
  (تا تعهدهای بعدی بی‌پوشش نمانند). زودترین تاریخ تعهد مقدار، اولین روزی از تاریخ درخواست است که قابل تعهدش کافی باشد.
- برآورد با تولید (فقط کالای ساختنی): کسری با فهرست مواد معتبر و زمان تولید کالا به نیاز سطح اول مواد تبدیل می‌شود؛ اولین
  روزی که مواد لازم در «روز − زمان تولید» قابل تعهد باشد. ظرفیت مراکز کاری در این برآورد نیست (زمان‌بندی با ظرفیت محدود).
- سناریو: تقاضا یا تامین فرضی روی همین محاسبه؛ تقاضاها به‌ترتیب تاریخ تعهد می‌گیرند و کسری کالای ساختنی به نیاز مواد تبدیل
  می‌شود تا اثرش روی کالاهای دیگر هم دیده شود.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.inventory import BomHeader, BomLine
from peecha.db.models.production import AtpScenario, AtpScenarioLine, ItemProductionProfile
from peecha.services.production import common as c
from peecha.services.production import master as pm

ZERO = decimal.Decimal(0)
KINDS = {"DEMAND": "تقاضای فرضی", "SUPPLY": "تامین فرضی"}
MAX_HORIZON = 366


@dataclass
class Event:
    date: datetime.date
    kind: str                # SUPPLY | DEMAND
    source: str
    quantity: decimal.Decimal
    scenario: bool = False


@dataclass
class Day:
    date: datetime.date
    supply: decimal.Decimal
    demand: decimal.Decimal
    balance: decimal.Decimal
    atp: decimal.Decimal = ZERO


@dataclass
class Timeline:
    item_id: int
    item_label: str
    start: datetime.date
    end: datetime.date
    free_now: decimal.Decimal
    events: list[Event]
    days: list[Day]

    def day(self, d: datetime.date) -> Day | None:
        index = (d - self.start).days
        return self.days[index] if 0 <= index < len(self.days) else None

    def atp_on(self, d: datetime.date) -> decimal.Decimal:
        day = self.day(max(d, self.start))
        return day.atp if day is not None else ZERO

    def promise_date(self, quantity, wanted: datetime.date | None = None) -> datetime.date | None:
        wanted = max(wanted or self.start, self.start)
        return next((d.date for d in self.days if d.date >= wanted and d.atp >= decimal.Decimal(quantity)), None)

    @property
    def min_balance(self) -> decimal.Decimal:
        return min((d.balance for d in self.days), default=self.free_now)

    @property
    def shortage_date(self) -> datetime.date | None:
        return next((d.date for d in self.days if d.balance < 0), None)

    @property
    def active_days(self) -> list[Day]:
        """روز اول و روزهایی که ورودی یا خروجی دارند."""
        return [d for i, d in enumerate(self.days) if i == 0 or d.supply or d.demand]


@dataclass
class ComponentCheck:
    item_id: int
    item_label: str
    required: decimal.Decimal
    available: decimal.Decimal

    @property
    def short(self) -> decimal.Decimal:
        return max(ZERO, self.required - self.available)


@dataclass
class Promise:
    item_id: int
    item_label: str
    quantity: decimal.Decimal
    wanted: datetime.date
    atp_at_wanted: decimal.Decimal
    atp_date: datetime.date | None
    ctp_date: datetime.date | None
    made: bool
    lead_days: int
    timeline: Timeline
    components: list[ComponentCheck] = field(default_factory=list)

    @property
    def best_date(self) -> datetime.date | None:
        dates = [d for d in (self.atp_date, self.ctp_date) if d]
        return min(dates) if dates else None


class _Data:
    """یک بار خواندن موجودی و تقاضا و تامین باز همهٔ کالاهای شرکت."""

    def __init__(self, company_id: int) -> None:
        from peecha.services import stock_reservations as sr
        from peecha.services.production import planning as pp

        self.company_id = company_id
        sales = pp.open_sales_demand(company_id)
        purchases = pp.open_purchase_receipts(company_id)
        with new_session() as session:
            on_hand, reserved = pp._stock(session, company_id)
            production = pp.open_production_receipts(session, company_id)
            materials = pp.open_order_material_demand(session, company_id)
            held: dict[int, decimal.Decimal] = defaultdict(lambda: ZERO)
            for r in sr.active(session, sr.SALES_ORDER, [d.line_id for d in sales], lock=False):
                held[r.source_record_id] += sr.remaining(r)
            self._made: dict[int, tuple[bool, int, list]] = {}
            self._session_labels = c.item_labels(session, set(on_hand) | {d.item_id for d in sales} | {r.item_id for r in purchases}
                                                 | {r.item_id for r in production} | {m.item_id for m in materials})
        self.free = {i: on_hand[i] - reserved[i] for i in set(on_hand)}
        self.events: dict[int, list[Event]] = defaultdict(list)
        for d in sales:
            quantity = d.quantity - held.get(d.line_id, ZERO)
            if quantity > 0:
                self.events[d.item_id].append(Event(d.date, "DEMAND", f"سفارش فروش {d.document_no}", quantity))
        for r in purchases:
            self.events[r.item_id].append(Event(r.date, "SUPPLY", f"سفارش خرید {r.document_no}", r.quantity))
        for r in production:
            if r.quantity > 0:
                self.events[r.item_id].append(Event(r.date, "SUPPLY", f"دستور تولید {r.order_code}", decimal.Decimal(r.quantity)))
        for m in materials:
            self.events[m.item_id].append(Event(m.date, "DEMAND", f"مواد دستور تولید {m.order_code}", m.quantity))

    def label(self, item_id: int) -> str:
        if item_id not in self._session_labels:
            with new_session() as session:
                self._session_labels.update(c.item_labels(session, [item_id]))
        return self._session_labels.get(item_id, "")

    def recipe(self, item_id: int, on_date: datetime.date) -> tuple[bool, int, list]:
        """(ساختنی؟، زمان تولید به روز، ردیف‌های اجباری فهرست مواد معتبر)."""
        key = (item_id, on_date)
        if key not in self._made:
            from peecha.services.production import planning as pp

            with new_session() as session:
                made = pp._is_made(session, item_id)
                prof = session.get(ItemProductionProfile, item_id)
                lead = int(prof.lead_time_days or 0) if prof else 0
                lines = []
                bom_id = pm.effective_bom_id(session, item_id, on_date) if made else None
                if bom_id:
                    bom = session.get(BomHeader, bom_id)
                    for ln in session.scalars(select(BomLine).where(BomLine.bom_id == bom_id).order_by(BomLine.line_no)):
                        if not ln.is_optional:
                            lines.append((ln.component_item_id, decimal.Decimal(ln.quantity_per) * decimal.Decimal(ln.conversion_factor or 1),
                                          ln.quantity_type or "VARIABLE",
                                          decimal.Decimal(ln.scrap_percent or 0) or decimal.Decimal(bom.scrap_percent or 0),
                                          decimal.Decimal(bom.batch_size_qty or 1)))
            self._made[key] = (made and bool(lines), lead, lines)
        return self._made[key]

    def timeline(self, item_id: int, start: datetime.date, end: datetime.date, extra: list[Event] = ()) -> Timeline:
        events = sorted([e for e in self.events.get(item_id, []) + list(extra) if e.date <= end], key=lambda e: (e.date, e.kind))
        free = decimal.Decimal(self.free.get(item_id, ZERO))
        count = (end - start).days + 1
        supply, demand = [ZERO] * count, [ZERO] * count
        for e in events:
            index = max(0, (e.date - start).days)
            if e.kind == "SUPPLY":
                supply[index] += e.quantity
            else:
                demand[index] += e.quantity
        days, balance = [], free
        for i in range(count):
            balance = balance + supply[i] - demand[i]
            days.append(Day(start + datetime.timedelta(days=i), supply[i], demand[i], balance))
        low = None
        for d in reversed(days):
            low = d.balance if low is None else min(low, d.balance)
            d.atp = max(ZERO, low)
        return Timeline(item_id, self.label(item_id), start, end, free, events, days)


def _requirements(lines: list, quantity: decimal.Decimal) -> list[tuple[int, decimal.Decimal]]:
    return [(item, pm.line_requirement(base, qty_type, scrap, quantity, batch)[1]) for item, base, qty_type, scrap, batch in lines]


def _window(start: datetime.date | None, horizon_days: int) -> tuple[datetime.date, datetime.date]:
    if not 1 <= int(horizon_days) <= MAX_HORIZON:
        raise ValueError("افق بررسی از ۱ تا ۳۶۶ روز است.")
    start = start or datetime.date.today()
    return start, start + datetime.timedelta(days=int(horizon_days) - 1)


def timeline(company_id: int, item_id: int, start: datetime.date | None = None, horizon_days: int = 60) -> Timeline:
    start, end = _window(start, horizon_days)
    with new_session() as session:
        c.item_of(session, company_id, item_id)
    return _Data(company_id).timeline(item_id, start, end)


def _ctp(data: _Data, item_id: int, quantity: decimal.Decimal, wanted: datetime.date, tl: Timeline,
         until: datetime.date | None) -> tuple[datetime.date | None, list[ComponentCheck]]:
    made, lead, lines = data.recipe(item_id, wanted)
    if not made:
        return None, []
    components = {item: data.timeline(item, tl.start, tl.end) for item, *_rest in lines}
    first_check: list[ComponentCheck] = []
    d = wanted
    while d <= tl.end and (until is None or d < until):
        short = quantity - tl.atp_on(d)
        need_by = d - datetime.timedelta(days=lead)
        if short > 0 and need_by >= tl.start:
            checks = [ComponentCheck(item, data.label(item), req, components[item].atp_on(need_by))
                      for item, req in _requirements(lines, short)]
            if not first_check:
                first_check = checks
            if all(ch.short <= 0 for ch in checks):
                return d, checks
        d += datetime.timedelta(days=1)
    if not first_check:
        short = max(ZERO, quantity - tl.atp_on(wanted))
        first_check = [ComponentCheck(item, data.label(item), req, components[item].atp_on(max(tl.start, wanted - datetime.timedelta(days=lead))))
                       for item, req in _requirements(lines, short or quantity)]
    return None, first_check


def promise(company_id: int, item_id: int, quantity, wanted: datetime.date | None = None, horizon_days: int = 90) -> Promise:
    """زودترین تاریخ تعهد مقدار از موجودی و تامین‌های باز، و برآورد با تولید برای کالای ساختنی."""
    quantity = decimal.Decimal(quantity or 0)
    if quantity <= 0:
        raise ValueError("مقدار باید بزرگ‌تر از صفر باشد.")
    start, end = _window(None, horizon_days)
    with new_session() as session:
        c.item_of(session, company_id, item_id)
    wanted = max(wanted or start, start)
    if wanted > end:
        raise ValueError("تاریخ درخواست بیرون از افق بررسی است.")
    data = _Data(company_id)
    tl = data.timeline(item_id, start, end)
    atp_date = tl.promise_date(quantity, wanted)
    made, lead, _lines = data.recipe(item_id, wanted)
    ctp_date, components = (None, [])
    if made and atp_date != wanted:
        ctp_date, components = _ctp(data, item_id, quantity, wanted, tl, atp_date)
    return Promise(item_id, tl.item_label, quantity, wanted, tl.atp_on(wanted), atp_date, ctp_date, made, lead, tl, components)


# --- سناریو ---------------------------------------------------------------------------------------------
@dataclass
class ScenarioLineFields:
    item_id: int
    kind_code: str
    line_date: datetime.date
    quantity: decimal.Decimal
    note: str = ""


@dataclass
class ScenarioRow:
    scenario_id: int
    name: str
    description: str
    created_at: datetime.datetime
    lines: list[ScenarioLineFields] = field(default_factory=list)


@dataclass
class LinePromise:
    item_id: int
    item_label: str
    wanted: datetime.date
    quantity: decimal.Decimal
    promise_date: datetime.date | None
    short_at_wanted: decimal.Decimal
    made: bool

    @property
    def delay_days(self) -> int | None:
        return None if self.promise_date is None else (self.promise_date - self.wanted).days


@dataclass
class ItemOutcome:
    item_id: int
    item_label: str
    base: Timeline
    scenario: Timeline

    @property
    def extra_shortage(self) -> decimal.Decimal:
        return max(ZERO, -self.scenario.min_balance) - max(ZERO, -self.base.min_balance)


@dataclass
class ScenarioResult:
    start: datetime.date
    end: datetime.date
    promises: list[LinePromise]
    outcomes: list[ItemOutcome]


def _clean(session, company_id: int, lines: list[ScenarioLineFields]) -> list[ScenarioLineFields]:
    if not lines:
        raise ValueError("دست‌کم یک ردیف تقاضا یا تامین فرضی لازم است.")
    out = []
    for ln in lines:
        if ln.kind_code not in KINDS:
            raise ValueError("نوع ردیف سناریو نامعتبر است.")
        if not ln.item_id or ln.line_date is None:
            raise ValueError("کالا و تاریخ هر ردیف سناریو الزامی است.")
        c.item_of(session, company_id, ln.item_id)
        quantity = decimal.Decimal(ln.quantity or 0)
        if quantity <= 0:
            raise ValueError("مقدار هر ردیف سناریو باید بزرگ‌تر از صفر باشد.")
        out.append(ScenarioLineFields(ln.item_id, ln.kind_code, ln.line_date, quantity, (ln.note or "").strip()[:300]))
    return out


def save_scenario(company_id: int, user_id: int | None, name: str, description: str, lines: list[ScenarioLineFields],
                  scenario_id: int | None = None) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("نام سناریو را بنویسید.")
    with new_session() as session:
        clean = _clean(session, company_id, lines)
        clash = session.scalar(select(AtpScenario.scenario_id).where(AtpScenario.company_id == company_id, AtpScenario.name == name,
                                                                     AtpScenario.scenario_id != (scenario_id or 0)))
        if clash:
            raise ValueError(f"سناریویی با نام «{name}» هست.")
        if scenario_id is None:
            row = AtpScenario(company_id=company_id, created_by_user_id=user_id, name=name)
            session.add(row)
        else:
            row = session.get(AtpScenario, scenario_id)
            if row is None or row.company_id != company_id:
                raise ValueError("سناریو نامعتبر است.")
            for old in session.scalars(select(AtpScenarioLine).where(AtpScenarioLine.scenario_id == scenario_id)):
                session.delete(old)
        row.name, row.description = name, (description or "").strip()[:500] or None
        session.flush()
        for ln in clean:
            session.add(AtpScenarioLine(scenario_id=row.scenario_id, item_id=ln.item_id, kind_code=ln.kind_code, line_date=ln.line_date,
                                        quantity=ln.quantity, note=ln.note or None))
        session.commit()
        return row.scenario_id


def delete_scenario(company_id: int, scenario_id: int) -> None:
    with new_session() as session:
        row = session.get(AtpScenario, scenario_id)
        if row is None or row.company_id != company_id:
            raise ValueError("سناریو نامعتبر است.")
        session.delete(row)
        session.commit()


def list_scenarios(company_id: int) -> list[ScenarioRow]:
    with new_session() as session:
        rows = list(session.scalars(select(AtpScenario).where(AtpScenario.company_id == company_id).order_by(AtpScenario.name)))
        lines: dict[int, list[ScenarioLineFields]] = defaultdict(list)
        for ln in session.scalars(select(AtpScenarioLine).where(AtpScenarioLine.scenario_id.in_([r.scenario_id for r in rows] or [0]))
                                  .order_by(AtpScenarioLine.line_date, AtpScenarioLine.line_id)):
            lines[ln.scenario_id].append(ScenarioLineFields(ln.item_id, ln.kind_code, ln.line_date, ln.quantity, ln.note or ""))
    return [ScenarioRow(r.scenario_id, r.name, r.description or "", r.created_at, lines.get(r.scenario_id, [])) for r in rows]


def evaluate(company_id: int, scenario_id: int, horizon_days: int = 90) -> ScenarioResult:
    scenario = next((s for s in list_scenarios(company_id) if s.scenario_id == scenario_id), None)
    if scenario is None:
        raise ValueError("سناریو نامعتبر است.")
    start, end = _window(None, horizon_days)
    data = _Data(company_id)
    extras: dict[int, list[Event]] = defaultdict(list)
    for ln in scenario.lines:
        if ln.kind_code == "SUPPLY":
            extras[ln.item_id].append(Event(ln.line_date, "SUPPLY", f"سناریو: {ln.note or KINDS['SUPPLY']}", ln.quantity, True))
    promises = []
    for ln in sorted((x for x in scenario.lines if x.kind_code == "DEMAND"), key=lambda x: x.line_date):
        wanted = max(ln.line_date, start)
        tl = data.timeline(ln.item_id, start, end, extras[ln.item_id])
        short = max(ZERO, ln.quantity - tl.atp_on(wanted))
        made, lead, lines = data.recipe(ln.item_id, wanted)
        promises.append(LinePromise(ln.item_id, tl.item_label, ln.line_date, ln.quantity, tl.promise_date(ln.quantity, wanted), short, made))
        extras[ln.item_id].append(Event(ln.line_date, "DEMAND", f"سناریو: {ln.note or KINDS['DEMAND']}", ln.quantity, True))
        if short > 0 and made:
            need_by = max(start, wanted - datetime.timedelta(days=lead))
            for item, req in _requirements(lines, short):
                extras[item].append(Event(need_by, "DEMAND", f"سناریو: مواد {tl.item_label}", req, True))
    outcomes = [ItemOutcome(item, data.label(item), data.timeline(item, start, end), data.timeline(item, start, end, extras[item]))
                for item in extras]
    outcomes.sort(key=lambda o: (-o.extra_shortage, o.item_label))
    return ScenarioResult(start, end, promises, outcomes)
