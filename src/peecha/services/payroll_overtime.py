"""سرویسِ اضافه‌کاری، شب‌کاری، تعطیل‌کاری و شیفتِ گردشی (فصلِ ۱۲).

⚠ طبقِ یادداشتِ db/schema/046: منبعِ «چند ساعت» به‌جایِ استخراجِ خودکار از
hr.attendance_records (که در فازِ ۱ از هستهٔ منابعِ انسانی ساخته نشد)،
ثبتِ دستی است — منطقِ نرخِ ساعتی و ترکیبِ ضرایب دقیقاً طبقِ سند است.

ترکیبِ هم‌زمانِ چند شرط (مثلِ اضافه‌کاریِ شب‌کاریِ تعطیل): چون هر ردیفِ
overtime_entries یک عددِ ساعتِ مستقل دارد (نه یک شناسهٔ «بازهٔ ساعتیِ
مشترک»)، ردیف‌هایی که در یک دوره برایِ یک کارمند عددِ ساعتِ یکسان دارند
به‌عنوانِ توصیف‌کنندهٔ همان ساعت‌ها از زاویه‌هایِ مختلف (شرط‌هایِ هم‌زمان)
درنظر گرفته می‌شوند و ضرایب‌شان طبقِ stacking_mode با هم ترکیب می‌شوند؛
ردیف‌هایی با عددِ ساعتِ متفاوت مستقل محاسبه می‌شوند. این همان مثالِ سند
(اضافه‌کاریِ شب‌کاریِ تعطیل = ۱ + ۰٫۴ + ۰٫۳۵ + ۱٫۰ = ۲٫۷۵) را با
هم‌ساعت‌بودنِ ردیف‌ها بازتولید می‌کند."""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.payroll import OvertimeEntry, OvertimeRule

_RULE_CODES = ("OVERTIME", "NIGHT_SHIFT", "HOLIDAY_WORK", "FRIDAY_WORK", "ROTATING_SHIFT_BONUS")
_STACKING_MODES = ("ADDITIVE", "MULTIPLICATIVE", "MAX_ONLY")
_HOURS_PER_MONTH_DIVISOR = decimal.Decimal("7.33")


def _overlaps(a_from: datetime.date, a_to: datetime.date | None, b_from: datetime.date, b_to: datetime.date | None) -> bool:
    if a_to is not None and b_from > a_to:
        return False
    if b_to is not None and a_from > b_to:
        return False
    return True


@dataclass
class OvertimeRuleRow:
    overtime_rule_id: int
    code: str
    multiplier: decimal.Decimal
    stacking_mode: str
    max_monthly_hours_policy_code: str | None
    effective_from: datetime.date
    effective_to: datetime.date | None


def _rule_row(r: OvertimeRule) -> OvertimeRuleRow:
    return OvertimeRuleRow(
        r.overtime_rule_id, r.code, r.multiplier, r.stacking_mode, r.max_monthly_hours_policy_code, r.effective_from, r.effective_to
    )


def list_overtime_rules(company_id: int) -> list[OvertimeRuleRow]:
    with new_session() as session:
        rows = session.scalars(
            select(OvertimeRule).where(OvertimeRule.company_id == company_id).order_by(OvertimeRule.code, OvertimeRule.effective_from.desc())
        ).all()
        return [_rule_row(r) for r in rows]


def create_overtime_rule(
    company_id: int,
    code: str,
    multiplier: decimal.Decimal,
    stacking_mode: str,
    max_monthly_hours_policy_code: str | None,
    effective_from: datetime.date,
    effective_to: datetime.date | None,
) -> int:
    if code not in _RULE_CODES:
        raise ValueError("نوعِ قانونِ اضافه‌کاری نامعتبر است.")
    if stacking_mode not in _STACKING_MODES:
        raise ValueError("حالتِ ترکیبِ ضرایب نامعتبر است.")
    if multiplier < 1:
        raise ValueError("ضریب باید حداقل ۱ باشد.")
    if effective_to is not None and effective_to < effective_from:
        raise ValueError("تاریخِ پایان نمی‌تواند قبل از تاریخِ شروع باشد.")
    with new_session() as session:
        existing = session.scalars(
            select(OvertimeRule).where(OvertimeRule.company_id == company_id, OvertimeRule.code == code)
        ).all()
        for row in existing:
            if _overlaps(effective_from, effective_to, row.effective_from, row.effective_to):
                raise ValueError("این بازه با یک قانونِ اضافه‌کاریِ دیگر با همین کد هم‌پوشانی دارد.")
        rule = OvertimeRule(
            company_id=company_id, code=code, multiplier=multiplier, stacking_mode=stacking_mode,
            max_monthly_hours_policy_code=max_monthly_hours_policy_code,
            effective_from=effective_from, effective_to=effective_to,
        )
        session.add(rule)
        session.commit()
        return rule.overtime_rule_id


def update_overtime_rule(
    overtime_rule_id: int, multiplier: decimal.Decimal, stacking_mode: str, max_monthly_hours_policy_code: str | None
) -> None:
    if stacking_mode not in _STACKING_MODES:
        raise ValueError("حالتِ ترکیبِ ضرایب نامعتبر است.")
    if multiplier < 1:
        raise ValueError("ضریب باید حداقل ۱ باشد.")
    with new_session() as session:
        rule = session.get(OvertimeRule, overtime_rule_id)
        if rule is None:
            raise ValueError("این قانون یافت نشد.")
        rule.multiplier = multiplier
        rule.stacking_mode = stacking_mode
        rule.max_monthly_hours_policy_code = max_monthly_hours_policy_code
        session.commit()


def delete_overtime_rule(overtime_rule_id: int) -> None:
    with new_session() as session:
        used = session.scalar(select(OvertimeEntry).where(OvertimeEntry.overtime_rule_id == overtime_rule_id))
        if used is not None:
            raise ValueError("این قانون در ثبت‌هایِ اضافه‌کاریِ موجود استفاده شده و قابلِ حذف نیست.")
        rule = session.get(OvertimeRule, overtime_rule_id)
        if rule is not None:
            session.delete(rule)
            session.commit()


def get_active_overtime_rule(company_id: int, code: str, as_of_date: datetime.date) -> OvertimeRuleRow | None:
    with new_session() as session:
        row = session.scalar(
            select(OvertimeRule).where(
                OvertimeRule.company_id == company_id,
                OvertimeRule.code == code,
                OvertimeRule.effective_from <= as_of_date,
                (OvertimeRule.effective_to.is_(None)) | (OvertimeRule.effective_to >= as_of_date),
            )
        )
        return _rule_row(row) if row is not None else None


@dataclass
class OvertimeEntryRow:
    overtime_entry_id: int
    employee_id: int
    period_id: int
    overtime_rule_id: int
    rule_code: str
    hours: decimal.Decimal
    status: str


def list_overtime_entries(period_id: int, employee_id: int | None = None) -> list[OvertimeEntryRow]:
    with new_session() as session:
        query = (
            select(OvertimeEntry, OvertimeRule)
            .join(OvertimeRule, OvertimeRule.overtime_rule_id == OvertimeEntry.overtime_rule_id)
            .where(OvertimeEntry.period_id == period_id)
        )
        if employee_id is not None:
            query = query.where(OvertimeEntry.employee_id == employee_id)
        rows = session.execute(query).all()
        return [
            OvertimeEntryRow(e.overtime_entry_id, e.employee_id, e.period_id, e.overtime_rule_id, r.code, e.hours, e.status)
            for e, r in rows
        ]


def create_overtime_entry(employee_id: int, period_id: int, overtime_rule_id: int, hours: decimal.Decimal) -> int:
    if hours <= 0:
        raise ValueError("ساعت باید بزرگ‌تر از صفر باشد.")
    with new_session() as session:
        exists = session.scalar(
            select(OvertimeEntry).where(
                OvertimeEntry.employee_id == employee_id,
                OvertimeEntry.period_id == period_id,
                OvertimeEntry.overtime_rule_id == overtime_rule_id,
            )
        )
        if exists is not None:
            raise ValueError("برایِ این کارمند/دوره/نوعِ اضافه‌کاری، ثبتی از قبل موجود است.")
        entry = OvertimeEntry(employee_id=employee_id, period_id=period_id, overtime_rule_id=overtime_rule_id, hours=hours)
        session.add(entry)
        session.commit()
        return entry.overtime_entry_id


def set_overtime_entry_status(overtime_entry_id: int, status: str) -> None:
    if status not in ("PENDING_APPROVAL", "APPROVED", "REJECTED"):
        raise ValueError("وضعیتِ نامعتبر.")
    with new_session() as session:
        entry = session.get(OvertimeEntry, overtime_entry_id)
        if entry is None:
            raise ValueError("این ثبت یافت نشد.")
        entry.status = status
        session.commit()


def delete_overtime_entry(overtime_entry_id: int) -> None:
    with new_session() as session:
        entry = session.get(OvertimeEntry, overtime_entry_id)
        if entry is not None:
            session.delete(entry)
            session.commit()


def compute_hourly_base_rate(base_salary: decimal.Decimal, continuous_benefits_total: decimal.Decimal, standard_month_days: int) -> decimal.Decimal:
    """نرخِ_ساعتیِ_پایه = (حقوقِ‌پایه + مزایایِ پیوسته) ÷ (روزهایِ‌استانداردِ‌ماه × ۷٫۳۳)."""
    denominator = decimal.Decimal(standard_month_days) * _HOURS_PER_MONTH_DIVISOR
    if denominator == 0:
        return decimal.Decimal(0)
    return (base_salary + continuous_benefits_total) / denominator


def _combine_multiplier(rules: list[OvertimeRuleRow]) -> decimal.Decimal:
    additive_sum = decimal.Decimal(0)
    multiplicative_product = decimal.Decimal(1)
    max_only_best = None
    for rule in rules:
        if rule.stacking_mode == "ADDITIVE":
            additive_sum += rule.multiplier - 1
        elif rule.stacking_mode == "MULTIPLICATIVE":
            multiplicative_product *= rule.multiplier
        else:  # MAX_ONLY
            max_only_best = rule.multiplier if max_only_best is None else max(max_only_best, rule.multiplier)
    combined = (decimal.Decimal(1) + additive_sum) * multiplicative_product
    if max_only_best is not None:
        combined *= max_only_best
    return combined


def compute_overtime_pay(
    company_id: int, employee_id: int, period_id: int, base_salary: decimal.Decimal,
    continuous_benefits_total: decimal.Decimal, standard_month_days: int,
) -> decimal.Decimal:
    """جمعِ مبلغِ اضافه‌کاریِ یک کارمند در یک دوره، فقط از ثبت‌هایِ APPROVED.
    ردیف‌هایِ هم‌ساعت با هم ترکیب می‌شوند (نکتهٔ بالایِ فایل)؛ بقیه مستقل."""
    hourly_rate = compute_hourly_base_rate(base_salary, continuous_benefits_total, standard_month_days)
    entries = [e for e in list_overtime_entries(period_id, employee_id) if e.status == "APPROVED"]
    if not entries:
        return decimal.Decimal(0)
    with new_session() as session:
        rule_by_id = {
            r.overtime_rule_id: _rule_row(r)
            for r in session.scalars(select(OvertimeRule).where(OvertimeRule.overtime_rule_id.in_({e.overtime_rule_id for e in entries})))
        }
    groups: dict[decimal.Decimal, list[OvertimeRuleRow]] = defaultdict(list)
    for entry in entries:
        groups[entry.hours].append(rule_by_id[entry.overtime_rule_id])
    total = decimal.Decimal(0)
    for hours, rules in groups.items():
        combined_multiplier = _combine_multiplier(rules)
        total += hours * hourly_rate * combined_multiplier
    return total
