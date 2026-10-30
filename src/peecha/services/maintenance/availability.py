"""دسترس‌پذیری ماشین (R312): توقف و آماده‌به‌کاری، توقف برنامه‌ریزی‌شده، ظرفیت محدود.

منبع رسمی وضعیت ماشین همان وضعیت دارایی است: شروع توقف آن را «در تعمیر» و ثبت آماده‌به‌کاری آن را به وضعیت قبلی
برمی‌گرداند، هر دو با fixed_assets.set_status_in_session در همان تراکنش. ظرفیت تولید (production.master) همان تاریخچه
را می‌خواند؛ snapshot جداگانه‌ای وجود ندارد.
"""

from __future__ import annotations

import datetime
import decimal
from types import SimpleNamespace

from sqlalchemy import or_, select

from peecha.db.base import new_session
from peecha.db.models.fixed_assets import Asset
from peecha.db.models.maintenance import CapacityRestriction, DowntimeEvent, PlannedDowntime
from peecha.services import stock_controls
from peecha.services.fixed_assets.common import CLOSED_STATUSES
from peecha.services.maintenance import common as c

# وضعیت‌هایی که ماشین را از قبل خارج از تولید نشان می‌دهند (شروع توقف آن‌ها را عوض نمی‌کند)
_ALREADY_DOWN = {"UNDER_MAINTENANCE", "SUSPENDED", "UNDER_CONSTRUCTION", "DRAFT", "ACQUIRED"}
_ONE = decimal.Decimal(1)


def open_downtime(session, asset_id: int) -> DowntimeEvent | None:
    return session.scalar(select(DowntimeEvent).where(DowntimeEvent.asset_id == asset_id, DowntimeEvent.available_at.is_(None)))


def check_manual_status_change(session, asset: Asset, status: str) -> None:
    """با کلید «وضعیت ماشین فقط از نگهداری»، تا توقف باز است تغییر دستی وضعیت ممکن نیست."""
    if not c.is_on(asset.company_id, stock_controls.MNT_STATUS_LOCK, session):
        return
    if open_downtime(session, asset.asset_id) is not None:
        raise ValueError("این ماشین توقف ثبت‌شدهٔ نگهداری دارد؛ آماده‌به‌کاری فقط از دستور کار نگهداری ثبت می‌شود.")


def start(session, company_id: int, user_id: int | None, asset_id: int, down_from: datetime.datetime,
          type_code: str = "BREAKDOWN", request_id: int | None = None, work_order_id: int | None = None,
          note: str | None = None) -> tuple[DowntimeEvent, bool]:
    """(رویداد توقف، تازه‌ساخته؟). هر تجهیز فقط یک توقف باز دارد؛ گزارش دوم به همان توقف وصل می‌شود."""
    from peecha.services.fixed_assets import assets as fa

    if type_code not in c.DOWNTIME_TYPE_LABELS:
        raise ValueError("نوع توقف نامعتبر است.")
    asset = c.asset_of(session, company_id, asset_id, lock=True)
    if asset.status_code in CLOSED_STATUSES:
        raise ValueError("این تجهیز واگذار شده و توقف برای آن معنا ندارد.")
    down_from = c.aware(down_from) or c.now()
    if down_from > c.now() + datetime.timedelta(minutes=5):
        raise ValueError("زمان شروع توقف نمی‌تواند در آینده باشد.")
    current = open_downtime(session, asset_id)
    if current is not None:
        if work_order_id and current.work_order_id is None:
            current.work_order_id = work_order_id
        return current, False
    ev = DowntimeEvent(company_id=company_id, asset_id=asset_id, downtime_type_code=type_code, down_from=down_from,
                       reported_at=c.now(), request_id=request_id, work_order_id=work_order_id,
                       previous_asset_status=asset.status_code, note=note, created_by_user_id=user_id)
    session.add(ev)
    session.flush()
    if asset.status_code not in _ALREADY_DOWN:
        fa.set_status_in_session(session, company_id, user_id, asset_id, "UNDER_MAINTENANCE", down_from.date(),
                                 f"توقف نگهداری #{ev.downtime_id}", source="MAINTENANCE")
    c.audit(session, company_id, user_id, "MntDowntime", ev.downtime_id, "START",
            {"asset_id": asset_id, "type": type_code, "down_from": down_from.isoformat(), "request_id": request_id,
             "work_order_id": work_order_id})
    return ev, True


def release(session, company_id: int, user_id: int | None, ev: DowntimeEvent, available_at: datetime.datetime | None,
            note: str | None = None) -> None:
    """ثبت آماده‌به‌کاری: پایان توقف و برگشت وضعیت دارایی (اگر توقف آن را تغییر داده بود)."""
    from peecha.services.fixed_assets import assets as fa

    if ev.available_at is not None:
        raise ValueError("آماده‌به‌کاری این توقف قبلاً ثبت شده است.")
    available_at = c.aware(available_at) or c.now()
    if available_at < c.aware(ev.down_from):
        raise ValueError("زمان آماده‌به‌کاری نمی‌تواند پیش از شروع توقف باشد.")
    if available_at > c.now() + datetime.timedelta(minutes=5):
        raise ValueError("زمان آماده‌به‌کاری نمی‌تواند در آینده باشد.")
    asset = c.asset_of(session, company_id, ev.asset_id, lock=True)
    ev.available_at, ev.released_by_user_id = available_at, user_id
    if note:
        ev.note = ((ev.note + " | ") if ev.note else "") + note[:300]
    session.flush()
    # ماشین «متوقف» یا سرمایه‌ای‌نشده را توقف تغییر نداده بود؛ پس برگشت هم ندارد
    if asset.status_code == "UNDER_MAINTENANCE" and ev.previous_asset_status not in _ALREADY_DOWN - {"UNDER_MAINTENANCE"}:
        fa.set_status_in_session(session, company_id, user_id, ev.asset_id, "IN_SERVICE", available_at.date(),
                                 f"آماده‌به‌کاری پس از توقف #{ev.downtime_id}", source="MAINTENANCE")
    c.audit(session, company_id, user_id, "MntDowntime", ev.downtime_id, "COMPLETE",
            {"available_at": available_at.isoformat(), "note": note})


def release_downtime(company_id: int, user_id: int, downtime_id: int, available_at: datetime.datetime | None = None,
                     note: str | None = None) -> None:
    """آماده‌به‌کاری توقفی که دستور کار ندارد (مثلاً گزارش خرابی نادرست) — با علت."""
    if not (note or "").strip():
        raise ValueError("علت ثبت آماده‌به‌کاری بدون دستور کار را بنویسید.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_VERIFY, session=session)
        ev = session.scalar(select(DowntimeEvent).where(DowntimeEvent.downtime_id == downtime_id).with_for_update())
        if ev is None or ev.company_id != company_id:
            raise ValueError("توقف نامعتبر است.")
        if ev.work_order_id is not None:
            raise ValueError("این توقف دستور کار دارد؛ آماده‌به‌کاری پس از آزمون از همان دستور کار ثبت می‌شود.")
        release(session, company_id, user_id, ev, available_at, note.strip())
        session.commit()


def list_downtimes(company_id: int, open_only: bool = False, asset_id: int | None = None,
                   date_from: datetime.date | None = None, date_to: datetime.date | None = None) -> list[SimpleNamespace]:
    with new_session() as session:
        q = select(DowntimeEvent, Asset).join(Asset, Asset.asset_id == DowntimeEvent.asset_id).where(
            DowntimeEvent.company_id == company_id)
        if open_only:
            q = q.where(DowntimeEvent.available_at.is_(None))
        if asset_id:
            q = q.where(DowntimeEvent.asset_id == asset_id)
        if date_from:
            q = q.where(or_(DowntimeEvent.available_at.is_(None), DowntimeEvent.available_at >= _day_start(date_from)))
        if date_to:
            q = q.where(DowntimeEvent.down_from < _day_start(date_to + datetime.timedelta(days=1)))
        out = []
        now = c.now()
        for ev, asset in session.execute(q.order_by(DowntimeEvent.down_from.desc())).all():
            end = ev.available_at or now
            out.append(SimpleNamespace(
                downtime_id=ev.downtime_id, asset_id=asset.asset_id, asset_label=c.asset_label(asset), type_code=ev.downtime_type_code,
                type_label=c.DOWNTIME_TYPE_LABELS[ev.downtime_type_code], down_from=ev.down_from, reported_at=ev.reported_at,
                available_at=ev.available_at, hours=hours_between(ev.down_from, end), is_open=ev.available_at is None,
                request_id=ev.request_id, work_order_id=ev.work_order_id, note=ev.note))
        return out


def hours_between(a: datetime.datetime, b: datetime.datetime) -> decimal.Decimal:
    return (decimal.Decimal((c.aware(b) - c.aware(a)).total_seconds()) / 3600).quantize(decimal.Decimal("0.01"))


def _day_start(day: datetime.date) -> datetime.datetime:
    return datetime.datetime.combine(day, datetime.time()).astimezone()


# --- توقف برنامه‌ریزی‌شده -------------------------------------------------------------------
def propose_window(company_id: int, user_id: int, asset_id: int, start_at: datetime.datetime, end_at: datetime.datetime,
                   reason: str | None = None, work_order_id: int | None = None) -> int:
    start_at, end_at = c.aware(start_at), c.aware(end_at)
    if end_at <= start_at:
        raise ValueError("پایان توقف باید بعد از شروع آن باشد.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_PLAN, session=session)
        asset = c.asset_of(session, company_id, asset_id, lock=True)
        if asset.status_code in CLOSED_STATUSES:
            raise ValueError("این تجهیز واگذار شده است.")
        overlap = session.scalar(select(PlannedDowntime.window_id).where(
            PlannedDowntime.asset_id == asset_id, PlannedDowntime.status_code != "CANCELLED",
            PlannedDowntime.start_at < end_at, PlannedDowntime.end_at > start_at))
        if overlap:
            raise ValueError("برای این بازه توقف برنامه‌ریزی‌شدهٔ دیگری ثبت شده است.")
        row = PlannedDowntime(company_id=company_id, asset_id=asset_id, work_order_id=work_order_id, start_at=start_at,
                              end_at=end_at, status_code="PROPOSED", reason=(reason or "").strip() or None,
                              requested_by_user_id=user_id)
        session.add(row)
        session.flush()
        c.audit(session, company_id, user_id, "MntPlannedDowntime", row.window_id, "CREATE",
                {"asset_id": asset_id, "start_at": start_at.isoformat(), "end_at": end_at.isoformat(), "reason": reason})
        session.commit()
        return row.window_id


def decide_window(company_id: int, user_id: int, window_id: int, approve: bool, note: str | None = None) -> None:
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_APPROVE, session=session)
        row = session.scalar(select(PlannedDowntime).where(PlannedDowntime.window_id == window_id).with_for_update())
        if row is None or row.company_id != company_id:
            raise ValueError("توقف برنامه‌ریزی‌شده نامعتبر است.")
        if row.status_code != "PROPOSED" and approve:
            raise ValueError("فقط توقف پیشنهادی تأیید می‌شود.")
        if row.status_code == "CANCELLED":
            raise ValueError("این توقف قبلاً لغو شده است.")
        if not approve and not (note or "").strip():
            raise ValueError("علت لغو را بنویسید.")
        row.status_code = "APPROVED" if approve else "CANCELLED"
        if approve:
            row.approved_by_user_id, row.approved_at = user_id, c.now()
        c.audit(session, company_id, user_id, "MntPlannedDowntime", window_id, "APPROVE" if approve else "CANCEL", {"note": note})
        session.commit()


# --- ظرفیت محدود ----------------------------------------------------------------------------
def propose_restriction(company_id: int, user_id: int, asset_id: int, capacity_percent, start_date: datetime.date,
                        end_date: datetime.date | None, reason: str, work_order_id: int | None = None) -> int:
    pct = c.dec(capacity_percent)
    if not 0 < pct < 100:
        raise ValueError("ظرفیت در دسترس باید بین ۰ و ۱۰۰ درصد باشد (توقف کامل از توقف ثبت می‌شود).")
    if not (reason or "").strip():
        raise ValueError("علت محدودیت ظرفیت الزامی است.")
    if end_date is not None and end_date < start_date:
        raise ValueError("پایان محدودیت نمی‌تواند پیش از شروع آن باشد.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_PLAN, session=session)
        c.asset_of(session, company_id, asset_id, lock=True)
        far = datetime.date.max
        for r in session.scalars(select(CapacityRestriction).where(CapacityRestriction.asset_id == asset_id,
                                                                    CapacityRestriction.status_code != "CANCELLED")):
            if r.start_date <= (end_date or far) and start_date <= (r.end_date or far):
                raise ValueError("برای این بازه محدودیت ظرفیت دیگری ثبت شده است.")
        row = CapacityRestriction(company_id=company_id, asset_id=asset_id, capacity_percent=pct, start_date=start_date,
                                  end_date=end_date, status_code="PROPOSED", reason=reason.strip(), work_order_id=work_order_id,
                                  requested_by_user_id=user_id)
        session.add(row)
        session.flush()
        c.audit(session, company_id, user_id, "MntCapacityRestriction", row.restriction_id, "CREATE",
                {"asset_id": asset_id, "percent": str(pct), "start": str(start_date), "end": str(end_date), "reason": reason})
        session.commit()
        return row.restriction_id


def decide_restriction(company_id: int, user_id: int, restriction_id: int, approve: bool, note: str | None = None) -> None:
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_APPROVE, session=session)
        row = session.scalar(select(CapacityRestriction).where(CapacityRestriction.restriction_id == restriction_id)
                             .with_for_update())
        if row is None or row.company_id != company_id:
            raise ValueError("محدودیت ظرفیت نامعتبر است.")
        if row.status_code == "CANCELLED" or (approve and row.status_code != "PROPOSED"):
            raise ValueError("این محدودیت در وضعیت قابل تصمیم نیست.")
        if not approve and not (note or "").strip():
            raise ValueError("علت لغو را بنویسید.")
        row.status_code = "APPROVED" if approve else "CANCELLED"
        if approve:
            row.approved_by_user_id, row.approved_at = user_id, c.now()
        c.audit(session, company_id, user_id, "MntCapacityRestriction", restriction_id, "APPROVE" if approve else "CANCEL",
                {"note": note})
        session.commit()


def end_restriction(company_id: int, user_id: int, restriction_id: int, end_date: datetime.date) -> None:
    """پایان محدودیت تأییدشده (ماشین دوباره با ظرفیت کامل)."""
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_APPROVE, session=session)
        row = session.scalar(select(CapacityRestriction).where(CapacityRestriction.restriction_id == restriction_id)
                             .with_for_update())
        if row is None or row.company_id != company_id or row.status_code != "APPROVED":
            raise ValueError("فقط محدودیت تأییدشده پایان می‌یابد.")
        if end_date < row.start_date:
            raise ValueError("پایان محدودیت نمی‌تواند پیش از شروع آن باشد.")
        old = row.end_date
        row.end_date = end_date
        c.audit(session, company_id, user_id, "MntCapacityRestriction", restriction_id, "UPDATE",
                {"end_date": [str(old), str(end_date)]})
        session.commit()


def list_windows(company_id: int, include_cancelled: bool = False) -> list[SimpleNamespace]:
    with new_session() as session:
        q = select(PlannedDowntime, Asset).join(Asset, Asset.asset_id == PlannedDowntime.asset_id).where(
            PlannedDowntime.company_id == company_id)
        if not include_cancelled:
            q = q.where(PlannedDowntime.status_code != "CANCELLED")
        return [SimpleNamespace(window_id=w.window_id, asset_id=a.asset_id, asset_label=c.asset_label(a), start_at=w.start_at,
                                end_at=w.end_at, hours=hours_between(w.start_at, w.end_at), status_code=w.status_code,
                                status_label=c.APPROVAL_STATUS_LABELS[w.status_code], reason=w.reason,
                                work_order_id=w.work_order_id)
                for w, a in session.execute(q.order_by(PlannedDowntime.start_at.desc())).all()]


def list_restrictions(company_id: int, include_cancelled: bool = False) -> list[SimpleNamespace]:
    with new_session() as session:
        q = select(CapacityRestriction, Asset).join(Asset, Asset.asset_id == CapacityRestriction.asset_id).where(
            CapacityRestriction.company_id == company_id)
        if not include_cancelled:
            q = q.where(CapacityRestriction.status_code != "CANCELLED")
        return [SimpleNamespace(restriction_id=r.restriction_id, asset_id=a.asset_id, asset_label=c.asset_label(a),
                                percent=r.capacity_percent, start_date=r.start_date, end_date=r.end_date,
                                status_code=r.status_code, status_label=c.APPROVAL_STATUS_LABELS[r.status_code], reason=r.reason)
                for r, a in session.execute(q.order_by(CapacityRestriction.start_date.desc())).all()]


# --- اثر روی ظرفیت تولید (production.master.available_capacity) -------------------------------
def capacity_factors(session, company_id: int, asset_ids: list[int], days: list[datetime.date],
                     daily_hours) -> dict[tuple[int, datetime.date], decimal.Decimal]:
    """ضریب در دسترس هر ماشین-روز (۰ تا ۱) از توقف برنامه‌ریزی‌شده و ظرفیت محدود **تأییدشده**.

    فقط با کلید «کسر توقف برنامه‌ریزی‌شده و ظرفیت محدود»؛ بی‌کلید خالی (همان رفتار قبلی). ساعت توقف هر روز از ساعت
    کاری روزانهٔ مرکز کم می‌شود (حداکثر کل روز) و ظرفیت محدود، باقی‌مانده را به درصد مصوب می‌رساند.
    """
    if not asset_ids or not days or not c.is_on(company_id, stock_controls.MNT_CAPACITY_PLANNED, session):
        return {}
    daily = c.dec(daily_hours)
    lo, hi = _day_start(min(days)), _day_start(max(days) + datetime.timedelta(days=1))
    windows = session.execute(select(PlannedDowntime.asset_id, PlannedDowntime.start_at, PlannedDowntime.end_at).where(
        PlannedDowntime.asset_id.in_(asset_ids), PlannedDowntime.status_code == "APPROVED",
        PlannedDowntime.start_at < hi, PlannedDowntime.end_at > lo)).all()
    limits = session.execute(select(CapacityRestriction.asset_id, CapacityRestriction.capacity_percent,
                                    CapacityRestriction.start_date, CapacityRestriction.end_date).where(
        CapacityRestriction.asset_id.in_(asset_ids), CapacityRestriction.status_code == "APPROVED",
        CapacityRestriction.start_date <= max(days),
        or_(CapacityRestriction.end_date.is_(None), CapacityRestriction.end_date >= min(days)))).all()
    out: dict[tuple[int, datetime.date], decimal.Decimal] = {}
    for day in days:
        d0, d1 = _day_start(day), _day_start(day + datetime.timedelta(days=1))
        for aid in asset_ids:
            factor = _ONE
            off = sum((hours_between(max(s, d0), min(e, d1)) for a, s, e in windows if a == aid and s < d1 and e > d0),
                      decimal.Decimal(0))
            if off > 0:
                factor = max(decimal.Decimal(0), _ONE - (off / daily if daily > 0 else _ONE))
            pct = min((p for a, p, s, e in limits if a == aid and s <= day and (e is None or e >= day)), default=None)
            if pct is not None:
                factor = factor * c.dec(pct) / 100
            if factor != _ONE:
                out[(aid, day)] = factor
    return out


def notices(session, company_id: int, asset_ids: list[int], date_from: datetime.date, date_to: datetime.date) -> list[SimpleNamespace]:
    """هشدارهای برنامه‌ریزی (همیشه، با یا بی‌کلید): توقف برنامه‌ریزی‌شده و ظرفیت محدود در بازه، تأییدشده یا پیشنهادی."""
    if not asset_ids:
        return []
    lo, hi = _day_start(date_from), _day_start(date_to + datetime.timedelta(days=1))
    names = {a.asset_id: c.asset_label(a) for a in session.scalars(select(Asset).where(Asset.asset_id.in_(asset_ids)))}
    applied = c.is_on(company_id, stock_controls.MNT_CAPACITY_PLANNED, session)
    out = []
    for w in session.scalars(select(PlannedDowntime).where(PlannedDowntime.asset_id.in_(asset_ids),
                                                           PlannedDowntime.status_code != "CANCELLED",
                                                           PlannedDowntime.start_at < hi, PlannedDowntime.end_at > lo)):
        effect = applied and w.status_code == "APPROVED"
        out.append(SimpleNamespace(kind="PLANNED", asset_id=w.asset_id, asset_label=names.get(w.asset_id, ""),
                                   status_code=w.status_code, start=w.start_at, end=w.end_at, percent=None, reason=w.reason,
                                   applied=effect,
                                   message=f"توقف برنامه‌ریزی‌شدهٔ {names.get(w.asset_id, '')} "
                                           f"({c.APPROVAL_STATUS_LABELS[w.status_code]}، {hours_between(w.start_at, w.end_at)} ساعت)"
                                           + ("" if effect else " — در عدد ظرفیت کسر نشده است")))
    for r in session.scalars(select(CapacityRestriction).where(
            CapacityRestriction.asset_id.in_(asset_ids), CapacityRestriction.status_code != "CANCELLED",
            CapacityRestriction.start_date <= date_to,
            or_(CapacityRestriction.end_date.is_(None), CapacityRestriction.end_date >= date_from))):
        effect = applied and r.status_code == "APPROVED"
        out.append(SimpleNamespace(kind="RESTRICTED", asset_id=r.asset_id, asset_label=names.get(r.asset_id, ""),
                                   status_code=r.status_code, start=r.start_date, end=r.end_date, percent=r.capacity_percent,
                                   reason=r.reason, applied=effect,
                                   message=f"ظرفیت محدود {names.get(r.asset_id, '')}: {c.dec(r.capacity_percent).normalize():f}٪ "
                                           f"({c.APPROVAL_STATUS_LABELS[r.status_code]})"
                                           + ("" if effect else " — در عدد ظرفیت کسر نشده است")))
    return out
