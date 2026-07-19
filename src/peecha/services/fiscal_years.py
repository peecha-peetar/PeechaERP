"""سرویس مدیریت سال‌های مالی (acc.fiscal_years/acc.fiscal_periods).

با ثبتِ سند حسابداری، سالِ مالیِ لازم به‌صورت خودکار ساخته می‌شود
(journal_entries._get_or_create_fiscal_year) — این سرویس همان منطقِ محاسبه‌ی
بازه (journal_entries.fiscal_year_bounds) را برای تعریفِ صریح/از‌پیش سال
مالی به‌کار می‌برد تا کدها/تاریخ‌ها هیچ‌وقت با هم ناسازگار نشوند، و برخلافِ
مسیرِ خودکار، ۱۲ دوره‌ی ماهانه هم می‌سازد (چون آنجا فقط خودِ سند لازم است،
نه گزارش‌گیریِ دوره‌ای)."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import jdatetime
from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.accounting import FiscalPeriod, FiscalYear
from peecha.services.journal_entries import fiscal_year_bounds

_DAYS_IN_MONTH = jdatetime.j_days_in_month  # اندیس ۰..۱۱ برای ماه‌های ۱..۱۲


@dataclass
class FiscalYearRow:
    fiscal_year_id: int
    code: str
    start_date: datetime.date
    end_date: datetime.date
    is_closed: bool
    period_count: int


def list_fiscal_years(company_id: int) -> list[FiscalYearRow]:
    with new_session() as session:
        years = session.scalars(
            select(FiscalYear).where(FiscalYear.company_id == company_id).order_by(FiscalYear.code.desc())
        ).all()
        counts: dict[int, int] = {}
        if years:
            rows = session.execute(
                select(FiscalPeriod.fiscal_year_id, FiscalPeriod.fiscal_period_id).where(
                    FiscalPeriod.fiscal_year_id.in_([y.fiscal_year_id for y in years])
                )
            ).all()
            for fy_id, _period_id in rows:
                counts[fy_id] = counts.get(fy_id, 0) + 1
        return [
            FiscalYearRow(
                fiscal_year_id=y.fiscal_year_id,
                code=y.code,
                start_date=y.start_date,
                end_date=y.end_date,
                is_closed=y.is_closed,
                period_count=counts.get(y.fiscal_year_id, 0),
            )
            for y in years
        ]


def pick_current(company_id: int, on_date: datetime.date) -> FiscalYearRow | None:
    """سالِ مالیِ دربرگیرنده‌ی on_date را برمی‌گرداند (برای پیش‌فرضِ سوییچرِ
    «سالِ مالیِ فعال» در هدر)؛ اگر چنین سالی تعریف نشده بود، جدیدترین سالِ
    مالیِ موجود (طبق end_date) را برمی‌گرداند، وگرنه None (هنوز هیچ سالِ
    مالی‌ای برای این شرکت تعریف نشده)."""
    years = list_fiscal_years(company_id)
    if not years:
        return None
    containing = next((y for y in years if y.start_date <= on_date <= y.end_date), None)
    if containing is not None:
        return containing
    return max(years, key=lambda y: y.end_date)


def _clamp_day(month: int, day: int) -> int:
    return min(day, _DAYS_IN_MONTH[month - 1])


def _generate_periods(start_month: int, start_day: int, code: str) -> list[tuple[datetime.date, datetime.date]]:
    year = int(code)
    periods: list[tuple[datetime.date, datetime.date]] = []
    for period_no in range(12):
        cur_month = ((start_month - 1 + period_no) % 12) + 1
        cur_year = year + (start_month - 1 + period_no) // 12
        period_start = jdatetime.date(cur_year, cur_month, _clamp_day(cur_month, start_day))

        next_month = ((start_month - 1 + period_no + 1) % 12) + 1
        next_year = year + (start_month - 1 + period_no + 1) // 12
        next_start = jdatetime.date(next_year, next_month, _clamp_day(next_month, start_day))
        period_end = next_start - datetime.timedelta(days=1)

        periods.append((period_start.togregorian(), period_end.togregorian()))
    return periods


def create_fiscal_year_for_date(
    company_id: int, start_month: int, start_day: int, on_date: datetime.date
) -> FiscalYear:
    """سالِ مالیِ دربرگیرنده‌ی on_date را می‌سازد (طبقِ الگوی شروعِ سالِ مالیِ
    شرکت) — برای صفحه‌ی «افزودن سال مالی» که کاربر فقط یک تاریخِ دلخواه در
    آن سال را وارد می‌کند، نه مستقیم کد/تاریخ شروع/پایان را."""
    code, start, end = fiscal_year_bounds(start_month, start_day, on_date)
    with new_session() as session:
        if session.scalar(select(FiscalYear).where(FiscalYear.company_id == company_id, FiscalYear.code == code)):
            raise ValueError(f"سالِ مالیِ «{code}» قبلاً برای این شرکت تعریف شده است.")

        fiscal_year = FiscalYear(company_id=company_id, code=code, start_date=start, end_date=end, is_closed=False)
        session.add(fiscal_year)
        session.flush()

        for period_no, (period_start, period_end) in enumerate(_generate_periods(start_month, start_day, code), 1):
            session.add(
                FiscalPeriod(
                    fiscal_year_id=fiscal_year.fiscal_year_id,
                    period_no=period_no,
                    start_date=period_start,
                    end_date=period_end,
                    is_closed=False,
                )
            )
        session.commit()
        session.refresh(fiscal_year)
        session.expunge(fiscal_year)
        return fiscal_year


def set_closed(fiscal_year_id: int, company_id: int, is_closed: bool) -> None:
    with new_session() as session:
        fiscal_year = session.get(FiscalYear, fiscal_year_id)
        if fiscal_year is None or fiscal_year.company_id != company_id:
            raise ValueError("سال مالی نامعتبر است.")
        fiscal_year.is_closed = is_closed
        session.commit()
