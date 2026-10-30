"""تقویم کاری شرکت: ساعت کاری هر روز هفته و تعطیلات رسمی؛ موعد کارها با «ساعت کاری» محاسبه می‌شود.

مثال: کاری که پنجشنبه ساعت ۱۱ با مهلت ۴ ساعت کاری می‌رسد، با پنجشنبهٔ نیمه‌وقت و جمعهٔ تعطیل، شنبه ساعت ۱۱ سررسید
می‌شود.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.workflow import WfHoliday
from peecha.services.workflow.common import DEFAULT_WORK_HOURS, WorkflowError, audit, save_settings, settings

WEEKDAYS = {5: "شنبه", 6: "یکشنبه", 0: "دوشنبه", 1: "سه‌شنبه", 2: "چهارشنبه", 3: "پنجشنبه", 4: "جمعه"}
WEEK_ORDER = (5, 6, 0, 1, 2, 3, 4)
_MAX_DAYS = 800


def _parse(t: str) -> datetime.time:
    hh, mm = (int(x) for x in str(t).split(":")[:2])
    return datetime.time(hh, mm)


def work_hours(company_id: int) -> dict[int, tuple[datetime.time, datetime.time]]:
    raw = settings(company_id).get("work_hours") or DEFAULT_WORK_HOURS
    out = {}
    for day, span in raw.items():
        try:
            start, end = _parse(span[0]), _parse(span[1])
        except (TypeError, ValueError, IndexError):
            continue
        if end > start:
            out[int(day)] = (start, end)
    return out


def save_work_hours(company_id: int, user_id: int | None, hours: dict[int, tuple[str, str] | None]) -> None:
    """hours: {روز هفته: ("08:00", "16:00") یا None برای تعطیل}"""
    clean = {}
    for day, span in hours.items():
        if not span:
            continue
        try:
            start, end = _parse(span[0]), _parse(span[1])
        except (TypeError, ValueError, IndexError):
            raise WorkflowError(f"ساعت کاری {WEEKDAYS.get(int(day), day)} نامعتبر است (مثال درست: ۰۸:۰۰).") from None
        if end <= start:
            raise WorkflowError(f"در {WEEKDAYS.get(int(day), day)} پایان کار باید بعد از شروع باشد.")
        clean[str(int(day))] = [start.strftime("%H:%M"), end.strftime("%H:%M")]
    if not clean:
        raise WorkflowError("دست‌کم یک روز کاری لازم است.")
    save_settings(company_id, user_id, work_hours=clean)


def holiday_dates(company_id: int, start: datetime.date, end: datetime.date) -> set[datetime.date]:
    with new_session() as session:
        return set(session.scalars(select(WfHoliday.holiday_date).where(
            WfHoliday.company_id == company_id, WfHoliday.holiday_date >= start, WfHoliday.holiday_date <= end)))


def _local(at: datetime.datetime) -> datetime.datetime:
    return (at if at.tzinfo else at.replace(tzinfo=datetime.timezone.utc)).astimezone()


def add_business_hours(company_id: int, start: datetime.datetime, hours: float) -> datetime.datetime:
    """زمانی که پس از «hours» ساعت کاری از «start» می‌رسد (روزهای تعطیل و بیرون از ساعت کاری شمرده نمی‌شوند)."""
    schedule = work_hours(company_id)
    cursor = _local(start)
    remaining = datetime.timedelta(hours=float(hours))
    if not schedule or remaining.total_seconds() <= 0:
        return cursor + remaining
    holidays = holiday_dates(company_id, cursor.date(), cursor.date() + datetime.timedelta(days=_MAX_DAYS))
    tz = cursor.tzinfo
    for _ in range(_MAX_DAYS):
        day = cursor.date()
        span = schedule.get(day.weekday())
        if span and day not in holidays:
            day_start = datetime.datetime.combine(day, span[0], tz)
            day_end = datetime.datetime.combine(day, span[1], tz)
            begin = max(cursor, day_start)
            if begin < day_end:
                available = day_end - begin
                if remaining <= available:
                    return begin + remaining
                remaining -= available
        cursor = datetime.datetime.combine(day + datetime.timedelta(days=1), datetime.time(0, 0), tz)
    return cursor + remaining


def business_hours_between(company_id: int, a: datetime.datetime, b: datetime.datetime) -> float:
    """ساعت کاری سپری‌شده بین دو زمان (برای سنجش تعهد زمانی و گلوگاه‌ها)."""
    a, b = _local(a), _local(b)
    if b <= a:
        return 0.0
    schedule = work_hours(company_id)
    if not schedule:
        return (b - a).total_seconds() / 3600
    holidays = holiday_dates(company_id, a.date(), b.date())
    total = datetime.timedelta()
    day = a.date()
    while day <= b.date():
        span = schedule.get(day.weekday())
        if span and day not in holidays:
            s = max(a, datetime.datetime.combine(day, span[0], a.tzinfo))
            e = min(b, datetime.datetime.combine(day, span[1], a.tzinfo))
            if e > s:
                total += e - s
        day += datetime.timedelta(days=1)
    return total.total_seconds() / 3600


def is_working_time(company_id: int, at: datetime.datetime) -> bool:
    at = _local(at)
    span = work_hours(company_id).get(at.weekday())
    return bool(span) and at.date() not in holiday_dates(company_id, at.date(), at.date()) and span[0] <= at.time() < span[1]


@dataclass
class HolidayRow:
    holiday_id: int
    holiday_date: datetime.date
    title: str


def list_holidays(company_id: int, year_from: datetime.date | None = None) -> list[HolidayRow]:
    with new_session() as session:
        q = select(WfHoliday).where(WfHoliday.company_id == company_id)
        if year_from:
            q = q.where(WfHoliday.holiday_date >= year_from)
        return [HolidayRow(h.holiday_id, h.holiday_date, h.title) for h in session.scalars(q.order_by(WfHoliday.holiday_date))]


def add_holiday(company_id: int, user_id: int | None, holiday_date: datetime.date, title: str) -> int:
    title = (title or "").strip()
    if not holiday_date or not title:
        raise WorkflowError("تاریخ و عنوان تعطیلی الزامی است.")
    with new_session() as session:
        if session.scalar(select(WfHoliday.holiday_id).where(WfHoliday.company_id == company_id,
                                                             WfHoliday.holiday_date == holiday_date)):
            raise WorkflowError("این روز قبلاً تعطیل ثبت شده است.")
        row = WfHoliday(company_id=company_id, holiday_date=holiday_date, title=title[:150])
        session.add(row)
        session.flush()
        audit(session, company_id, user_id, "Holiday", row.holiday_id, "CREATE", {"date": holiday_date, "title": title})
        session.commit()
        return row.holiday_id


def delete_holiday(company_id: int, user_id: int | None, holiday_id: int) -> None:
    with new_session() as session:
        row = session.get(WfHoliday, holiday_id)
        if row is None or row.company_id != company_id:
            raise WorkflowError("تعطیلی نامعتبر است.")
        audit(session, company_id, user_id, "Holiday", holiday_id, "DELETE", {"date": row.holiday_date, "title": row.title})
        session.delete(row)
        session.commit()
