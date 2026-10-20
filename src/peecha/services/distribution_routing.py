"""R320: پیشنهاد مسیر پخش سرد بر اساس موقعیت مشتری (پشت کلید DIST_ROUTE_SUGGEST).

ترتیب تحویل فاکتورهای یک تیم پخش از روی مختصات ثبت‌شدهٔ مشتری پیشنهاد می‌شود: نزدیک‌ترین مقصد بعدی، سپس
بهبود با جابه‌جایی دوبه‌دو (2-opt) روی مسیر باز. فاصله خط مستقیم روی کرهٔ زمین است (بدون سرویس نقشه)؛ هدف
ترتیب منطقی تحویل است، نه مسیریابی خیابانی. مشتری بی‌موقعیت آخر فهرست می‌آید و جدا گزارش می‌شود.
هیچ سند مالی یا موجودی تغییر نمی‌کند؛ فقط ستون route_seq ردیف‌های تیم پخش پر می‌شود."""

from __future__ import annotations

import decimal
import math
from dataclasses import dataclass, field

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import (
    CommercialDocument, CustomerProfile, DistributionRun, DistributionRunDocument, PartyAddress,
)
from peecha.services import commercial_settings

FEATURE = "DIST_ROUTE_SUGGEST"
# آدرس تحویل دقیق‌ترین مقصد است، بعد فروشگاه، بعد هر آدرس دیگر
_ADDRESS_PRIORITY = {"DELIVERY": 0, "STORE": 1}


@dataclass
class RouteStop:
    document_id: int
    document_no: int
    counterparty_detail_account_id: int
    latitude: float | None = None
    longitude: float | None = None
    leg_km: float | None = None  # فاصله از توقف قبلی (یا نقطهٔ شروع)


@dataclass
class RoutePlan:
    stops: list[RouteStop] = field(default_factory=list)  # ترتیب پیشنهادی؛ بی‌موقعیت‌ها در انتها
    missing: list[RouteStop] = field(default_factory=list)
    total_km: float = 0.0
    start: tuple[float, float] | None = None


def is_on(company_id: int) -> bool:
    return commercial_settings.is_feature_enabled(company_id, FEATURE)


def _require_on(company_id: int) -> None:
    if not is_on(company_id):
        raise ValueError("پیشنهاد مسیر پخش خاموش است؛ از «تنظیمات › فروش › قابلیت‌های فعال» روشنش کنید.")


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def order_points(points: dict, start: tuple[float, float] | None = None) -> list:
    """کلیدهای points ({کلید: (عرض، طول)}) به ترتیب پیشنهادی تحویل."""
    keys = list(points)
    if len(keys) <= 1:
        return keys
    idx = {k: i for i, k in enumerate(keys)}
    if start is None:
        # بی‌نقطهٔ شروع، از دورترین مقصد نسبت به مرکز شروع می‌کنیم تا مسیر از یک سر به سر دیگر برود
        centre = (sum(p[0] for p in points.values()) / len(keys), sum(p[1] for p in points.values()) / len(keys))
        first = max(keys, key=lambda k: (distance_km(centre, points[k]), -idx[k]))
    else:
        first = min(keys, key=lambda k: (distance_km(start, points[k]), idx[k]))
    route, left = [first], [k for k in keys if k != first]
    while left:
        here = points[route[-1]]
        nxt = min(left, key=lambda k: (distance_km(here, points[k]), idx[k]))
        route.append(nxt)
        left.remove(nxt)
    return _two_opt(route, points, start)


def _two_opt(route: list, points: dict, start) -> list:
    def pos(i):
        return start if i < 0 else points[route[i]]

    n, improved, rounds = len(route), True, 0
    while improved and rounds < 50:
        improved, rounds = False, rounds + 1
        for i in range(n - 1):
            for j in range(i + 1, n):
                # برعکس‌کردن route[i..j]؛ مسیر باز است پس پس از آخرین توقف یالی نیست
                a = pos(i - 1) if (i > 0 or start is not None) else None
                b, c = pos(i), pos(j)
                d = pos(j + 1) if j + 1 < n else None
                before = (distance_km(a, b) if a else 0) + (distance_km(c, d) if d else 0)
                after = (distance_km(a, c) if a else 0) + (distance_km(b, d) if d else 0)
                if after + 1e-9 < before:
                    route[i:j + 1] = reversed(route[i:j + 1])
                    improved = True
    return route


def customer_locations(party_ids: set[int]) -> dict[int, tuple[float, float]]:
    """موقعیت هر مشتری: آدرس تحویل، فروشگاه، آدرس دیگر (پیش‌فرض اول) و در نبودشان مختصات پروندهٔ مشتری."""
    if not party_ids:
        return {}
    found: dict[int, tuple[tuple, tuple[float, float]]] = {}
    with new_session() as session:
        for a in session.scalars(select(PartyAddress).where(
                PartyAddress.party_detail_account_id.in_(party_ids), PartyAddress.gps_latitude.is_not(None),
                PartyAddress.gps_longitude.is_not(None))):
            rank = (_ADDRESS_PRIORITY.get(a.address_type_code, 2), not a.is_default, a.address_id)
            current = found.get(a.party_detail_account_id)
            if current is None or rank < current[0]:
                found[a.party_detail_account_id] = (rank, (float(a.gps_latitude), float(a.gps_longitude)))
        missing = party_ids - set(found)
        if missing:
            for p in session.scalars(select(CustomerProfile).where(
                    CustomerProfile.customer_detail_account_id.in_(missing), CustomerProfile.gps_latitude.is_not(None),
                    CustomerProfile.gps_longitude.is_not(None))):
                found[p.customer_detail_account_id] = ((9,), (float(p.gps_latitude), float(p.gps_longitude)))
    return {party: point for party, (_rank, point) in found.items()}


def _run(session, company_id: int, run_id: int) -> DistributionRun:
    run = session.get(DistributionRun, run_id)
    if run is None or run.company_id != company_id:
        raise ValueError("تیم پخش نامعتبر است.")
    return run


def _ordered_links(session, run_id: int) -> list[tuple[DistributionRunDocument, CommercialDocument]]:
    rows = session.execute(
        select(DistributionRunDocument, CommercialDocument)
        .join(CommercialDocument, CommercialDocument.document_id == DistributionRunDocument.document_id)
        .where(DistributionRunDocument.distribution_run_id == run_id)
    ).all()
    return sorted(rows, key=lambda r: (r[0].route_seq is None, r[0].route_seq or 0, r[1].document_id))


def start_point(company_id: int, run_id: int) -> tuple[float, float] | None:
    """نقطهٔ شروع همین تیم، وگرنه آخرین نقطهٔ شروع ثبت‌شده برای همان خودرو."""
    with new_session() as session:
        run = _run(session, company_id, run_id)
        if run.start_latitude is not None and run.start_longitude is not None:
            return float(run.start_latitude), float(run.start_longitude)
        prev = session.scalar(
            select(DistributionRun).where(
                DistributionRun.company_id == company_id, DistributionRun.vehicle_warehouse_id == run.vehicle_warehouse_id,
                DistributionRun.start_latitude.is_not(None), DistributionRun.start_longitude.is_not(None),
                DistributionRun.distribution_run_id != run_id,
            ).order_by(DistributionRun.run_date.desc(), DistributionRun.distribution_run_id.desc()).limit(1)
        )
        return (float(prev.start_latitude), float(prev.start_longitude)) if prev is not None else None


def set_start_point(company_id: int, run_id: int, latitude: float | None, longitude: float | None) -> None:
    _require_on(company_id)
    if (latitude is None) != (longitude is None):
        raise ValueError("عرض و طول جغرافیایی را با هم وارد کنید.")
    if latitude is not None and not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("مختصات نقطهٔ شروع نامعتبر است.")
    with new_session() as session:
        run = _run(session, company_id, run_id)
        run.start_latitude = None if latitude is None else decimal.Decimal(str(round(latitude, 6)))
        run.start_longitude = None if longitude is None else decimal.Decimal(str(round(longitude, 6)))
        session.commit()


def _plan(stops: list[RouteStop], start, ordered: bool) -> RoutePlan:
    located = {s.document_id: s for s in stops if s.latitude is not None}
    missing = [s for s in stops if s.latitude is None]
    keys = list(located) if ordered else order_points({k: (s.latitude, s.longitude) for k, s in located.items()}, start)
    plan, prev = RoutePlan(missing=missing, start=start), start
    for k in keys:
        stop = located[k]
        here = (stop.latitude, stop.longitude)
        stop.leg_km = round(distance_km(prev, here), 2) if prev is not None else None
        plan.total_km += stop.leg_km or 0.0
        prev = here
        plan.stops.append(stop)
    plan.stops.extend(missing)
    plan.total_km = round(plan.total_km, 2)
    return plan


def _stops(company_id: int, run_id: int) -> list[RouteStop]:
    with new_session() as session:
        _run(session, company_id, run_id)
        links = _ordered_links(session, run_id)
    points = customer_locations({doc.counterparty_detail_account_id for _l, doc in links})
    return [RouteStop(doc.document_id, doc.document_no, doc.counterparty_detail_account_id,
                      *points.get(doc.counterparty_detail_account_id, (None, None))) for _l, doc in links]


def suggest(company_id: int, run_id: int) -> RoutePlan:
    """ترتیب پیشنهادی (ذخیره نمی‌شود)."""
    _require_on(company_id)
    return _plan(_stops(company_id, run_id), start_point(company_id, run_id), ordered=False)


def current(company_id: int, run_id: int) -> RoutePlan:
    """ترتیب فعلی تیم با فاصلهٔ هر توقف از قبلی."""
    return _plan(_stops(company_id, run_id), start_point(company_id, run_id), ordered=True)


def apply(company_id: int, run_id: int, document_ids: list[int]) -> None:
    """ذخیرهٔ ترتیب تحویل (فقط تیم هنوز تحویل‌نشده)."""
    _require_on(company_id)
    with new_session() as session:
        run = _run(session, company_id, run_id)
        if run.status_code != "DRAFT":
            raise ValueError("ترتیب مسیر فقط پیش از تحویل به راننده قابل تغییر است.")
        links = {link.document_id: link for link, _doc in _ordered_links(session, run_id)}
        if sorted(document_ids) != sorted(links):
            raise ValueError("فهرست فاکتورهای مسیر با فاکتورهای این تیم یکی نیست؛ دوباره بارگذاری کنید.")
        for seq, document_id in enumerate(document_ids, start=1):
            links[document_id].route_seq = seq
        session.commit()


def apply_suggestion(company_id: int, run_id: int) -> RoutePlan:
    plan = suggest(company_id, run_id)
    apply(company_id, run_id, [s.document_id for s in plan.stops])
    return plan


def move(company_id: int, run_id: int, document_id: int, step: int) -> None:
    """جابه‌جایی دستی یک فاکتور در ترتیب تحویل (step منفی یعنی زودتر)."""
    with new_session() as session:
        _run(session, company_id, run_id)
        order = [doc.document_id for _l, doc in _ordered_links(session, run_id)]
    if document_id not in order:
        raise ValueError("این فاکتور در این تیم پخش نیست.")
    i = order.index(document_id)
    j = max(0, min(len(order) - 1, i + step))
    if i == j:
        return
    order.insert(j, order.pop(i))
    apply(company_id, run_id, order)
