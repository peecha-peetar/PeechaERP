"""R364: ثبت و تایید کارکرد پروژه و نرخ ساعتی.

- کارکرد: کارمند، پروژه (در حال برنامه‌ریزی یا اجرا)، فعالیت (اختیاری، فقط فعالیت نه فاز)، روز و ساعت؛ جمع ساعت هر کارمند در
  یک روز (بدون ردشده‌ها) از ۲۴ بیشتر نمی‌شود و روز آینده پذیرفته نمی‌شود.
- گردش: پیش‌نویس ← ارسال‌شده ← تاییدشده یا ردشده (با دلیل)؛ ردشده پس از ویرایش دوباره پیش‌نویس می‌شود.
- تاییدکننده: مدیر پروژهٔ همان پروژه یا دارندهٔ مجوز «تایید» فرم کارکرد (یا مدیر سیستم)؛ کسی کارکرد خودش را تایید نمی‌کند
  مگر مدیر سیستم.
- نرخ ساعتی: نرخ همان کارمند از تاریخ (آخرین نرخ تا روز کارکرد)، وگرنه نرخ پیش‌فرض شرکت؛ هنگام تایید روی ردیف ثابت می‌شود.
  هزینهٔ کارکرد فقط برای کنترل پروژه است و سند حسابداری نمی‌سازد.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.hr import Employee
from peecha.db.models.projects import LaborRate, Project, ProjectTask, TimesheetEntry

ZERO = decimal.Decimal(0)
STATUSES = {"DRAFT": "پیش‌نویس", "SUBMITTED": "ارسال‌شده", "APPROVED": "تاییدشده", "REJECTED": "ردشده"}
OPEN_PROJECT_STATUSES = ("PLANNING", "ACTIVE")
FORM_CODE = "project_timesheets"


@dataclass
class EntryFields:
    project_id: int
    employee_id: int
    work_date: datetime.date
    hours: decimal.Decimal
    task_id: int | None = None
    description: str | None = None


@dataclass
class EntryRow:
    entry_id: int
    project_id: int
    project_label: str
    task_id: int | None
    task_name: str
    employee_id: int
    employee_name: str
    work_date: datetime.date
    hours: decimal.Decimal
    description: str
    status_code: str
    hourly_cost: decimal.Decimal | None
    decision_note: str

    @property
    def status_label(self) -> str:
        return STATUSES[self.status_code]

    @property
    def cost(self) -> decimal.Decimal | None:
        return None if self.hourly_cost is None else (self.hours * self.hourly_cost).quantize(decimal.Decimal("0.01"))


@dataclass
class RateRow:
    rate_id: int
    employee_id: int | None
    employee_name: str
    valid_from: datetime.date
    hourly_cost: decimal.Decimal


def _name(e: Employee | None) -> str:
    return f"{e.first_name} {e.last_name}".strip() if e else ""


# --- نرخ ساعتی ---------------------------------------------------------------------------------------------------------
def save_rate(company_id: int, employee_id: int | None, valid_from: datetime.date, hourly_cost: decimal.Decimal) -> int:
    if valid_from is None:
        raise ValueError("تاریخ شروع اعتبار نرخ را وارد کنید.")
    hourly_cost = decimal.Decimal(hourly_cost)
    if hourly_cost < 0:
        raise ValueError("نرخ ساعتی نمی‌تواند منفی باشد.")
    with new_session() as session:
        if employee_id is not None:
            e = session.get(Employee, employee_id)
            if e is None or e.company_id != company_id:
                raise ValueError("کارمند انتخاب‌شده نامعتبر است.")
        row = session.scalar(select(LaborRate).where(
            LaborRate.company_id == company_id, LaborRate.valid_from == valid_from,
            LaborRate.employee_id.is_(None) if employee_id is None else LaborRate.employee_id == employee_id))
        if row is None:
            row = LaborRate(company_id=company_id, employee_id=employee_id, valid_from=valid_from)
            session.add(row)
        row.hourly_cost = hourly_cost
        session.commit()
        return row.rate_id


def delete_rate(company_id: int, rate_id: int) -> None:
    with new_session() as session:
        row = session.get(LaborRate, rate_id)
        if row is None or row.company_id != company_id:
            raise ValueError("نرخ نامعتبر است.")
        session.delete(row)
        session.commit()


def list_rates(company_id: int) -> list[RateRow]:
    with new_session() as session:
        rows = session.execute(select(LaborRate, Employee).outerjoin(Employee, Employee.employee_id == LaborRate.employee_id)
                               .where(LaborRate.company_id == company_id)
                               .order_by(LaborRate.employee_id.nulls_first(), LaborRate.valid_from.desc())).all()
    return [RateRow(r.rate_id, r.employee_id, _name(e) if e else "همهٔ کارکنان (پیش‌فرض)", r.valid_from, r.hourly_cost) for r, e in rows]


def rate_for(session, company_id: int, employee_id: int, on: datetime.date) -> decimal.Decimal | None:
    for who in (LaborRate.employee_id == employee_id, LaborRate.employee_id.is_(None)):
        value = session.scalar(select(LaborRate.hourly_cost).where(LaborRate.company_id == company_id, who, LaborRate.valid_from <= on)
                               .order_by(LaborRate.valid_from.desc()).limit(1))
        if value is not None:
            return value
    return None


# --- کارکرد ------------------------------------------------------------------------------------------------------------
def _check(session, company_id: int, f: EntryFields, entry_id: int | None, today: datetime.date) -> None:
    project = session.get(Project, f.project_id)
    if project is None or project.company_id != company_id:
        raise ValueError("پروژه نامعتبر است.")
    if project.status_code not in OPEN_PROJECT_STATUSES:
        raise ValueError("کارکرد فقط روی پروژهٔ در حال برنامه‌ریزی یا اجرا ثبت می‌شود.")
    employee = session.get(Employee, f.employee_id)
    if employee is None or employee.company_id != company_id:
        raise ValueError("کارمند انتخاب‌شده نامعتبر است.")
    if employee.status != "ACTIVE":
        raise ValueError("برای کارمند غیرفعال کارکرد ثبت نمی‌شود.")
    if f.task_id is not None:
        task = session.get(ProjectTask, f.task_id)
        if task is None or task.project_id != f.project_id:
            raise ValueError("فعالیت انتخاب‌شده در این پروژه نیست.")
        if session.scalar(select(ProjectTask.task_id).where(ProjectTask.parent_task_id == f.task_id).limit(1)):
            raise ValueError("کارکرد روی فعالیت ثبت می‌شود، نه روی فاز.")
    if f.work_date is None or f.work_date > today:
        raise ValueError("روز کارکرد نمی‌تواند بعد از امروز باشد.")
    hours = decimal.Decimal(f.hours or 0)
    if not ZERO < hours <= 24:
        raise ValueError("ساعت کارکرد باید بیشتر از صفر و حداکثر ۲۴ باشد.")
    used = session.scalar(select(func.coalesce(func.sum(TimesheetEntry.hours), 0)).where(
        TimesheetEntry.employee_id == f.employee_id, TimesheetEntry.work_date == f.work_date,
        TimesheetEntry.status_code != "REJECTED", TimesheetEntry.entry_id != (entry_id or 0)))
    if used + hours > 24:
        raise ValueError(f"جمع کارکرد این کارمند در این روز از ۲۴ ساعت بیشتر می‌شود (ثبت‌شده: {used.normalize():f} ساعت).")


def save_entry(company_id: int, user_id: int | None, f: EntryFields, entry_id: int | None = None, *, submit: bool = False,
               today: datetime.date | None = None) -> int:
    today = today or datetime.date.today()
    with new_session() as session:
        _check(session, company_id, f, entry_id, today)
        if entry_id is None:
            row = TimesheetEntry(company_id=company_id, created_by_user_id=user_id)
            session.add(row)
        else:
            row = session.get(TimesheetEntry, entry_id)
            if row is None or row.company_id != company_id:
                raise ValueError("ردیف کارکرد نامعتبر است.")
            if row.status_code not in ("DRAFT", "REJECTED"):
                raise ValueError("کارکرد ارسال‌شده یا تاییدشده ویرایش نمی‌شود.")
        row.project_id, row.task_id, row.employee_id = f.project_id, f.task_id, f.employee_id
        row.work_date, row.hours = f.work_date, decimal.Decimal(f.hours)
        row.description = (f.description or "").strip() or None
        row.status_code = "SUBMITTED" if submit else "DRAFT"
        row.decision_note, row.decided_by_user_id, row.decided_at = None, None, None
        session.commit()
        return row.entry_id


def submit(company_id: int, entry_ids: list[int]) -> int:
    with new_session() as session:
        rows = _rows_for(session, company_id, entry_ids)
        for row in rows:
            if row.status_code != "DRAFT":
                raise ValueError("فقط کارکرد پیش‌نویس ارسال می‌شود.")
            row.status_code = "SUBMITTED"
        session.commit()
        return len(rows)


def _rows_for(session, company_id: int, entry_ids: list[int]) -> list[TimesheetEntry]:
    rows = list(session.scalars(select(TimesheetEntry).where(TimesheetEntry.entry_id.in_(entry_ids or [0]))))
    if not rows or len(rows) != len(set(entry_ids)) or any(r.company_id != company_id for r in rows):
        raise ValueError("ردیف کارکرد نامعتبر است.")
    return rows


def can_approve(company_id: int, user_id: int, project_id: int) -> bool:
    from peecha.services import roles

    if roles.is_manager(user_id, company_id) or roles.user_has_permission(user_id, company_id, FORM_CODE, "APPROVE"):
        return True
    with new_session() as session:
        project = session.get(Project, project_id)
        manager = session.get(Employee, project.manager_employee_id) if project and project.manager_employee_id else None
        return manager is not None and manager.user_id == user_id


def _decide(company_id: int, user_id: int, entry_ids: list[int], approve: bool, note: str | None) -> int:
    from peecha.services import roles

    super_user = roles.is_manager(user_id, company_id)
    with new_session() as session:
        rows = _rows_for(session, company_id, entry_ids)
        for row in rows:
            if row.status_code != "SUBMITTED":
                raise ValueError("فقط کارکرد ارسال‌شده تایید یا رد می‌شود.")
        allowed = {pid: can_approve(company_id, user_id, pid) for pid in {r.project_id for r in rows}}
        own = {e.employee_id for e in session.scalars(select(Employee).where(Employee.user_id == user_id, Employee.company_id == company_id))}
        now = datetime.datetime.now(datetime.timezone.utc)
        for row in rows:
            if not allowed[row.project_id]:
                raise ValueError("تایید کارکرد این پروژه با مدیر پروژه یا دارندهٔ مجوز تایید کارکرد است.")
            if row.employee_id in own and not super_user:
                raise ValueError("کارکرد خودتان را نمی‌توانید تایید یا رد کنید.")
            row.status_code = "APPROVED" if approve else "REJECTED"
            row.hourly_cost = rate_for(session, company_id, row.employee_id, row.work_date) if approve else None
            row.decision_note = (note or "").strip() or None
            row.decided_by_user_id, row.decided_at = user_id, now
        session.commit()
        return len(rows)


def approve(company_id: int, user_id: int, entry_ids: list[int], note: str | None = None) -> int:
    return _decide(company_id, user_id, entry_ids, True, note)


def reject(company_id: int, user_id: int, entry_ids: list[int], reason: str) -> int:
    if not (reason or "").strip():
        raise ValueError("دلیل رد کارکرد را بنویسید.")
    return _decide(company_id, user_id, entry_ids, False, reason)


def delete_entry(company_id: int, entry_id: int) -> None:
    with new_session() as session:
        row = _rows_for(session, company_id, [entry_id])[0]
        if row.status_code not in ("DRAFT", "REJECTED"):
            raise ValueError("فقط کارکرد پیش‌نویس یا ردشده حذف می‌شود.")
        session.delete(row)
        session.commit()


def list_entries(company_id: int, *, project_id: int | None = None, employee_id: int | None = None, status: str | None = None,
                 date_from: datetime.date | None = None, date_to: datetime.date | None = None, limit: int = 1000) -> list[EntryRow]:
    with new_session() as session:
        q = (select(TimesheetEntry, Employee, DetailAccount, ProjectTask.name)
             .join(Employee, Employee.employee_id == TimesheetEntry.employee_id)
             .join(Project, Project.project_id == TimesheetEntry.project_id)
             .join(DetailAccount, DetailAccount.detail_account_id == Project.project_detail_account_id)
             .outerjoin(ProjectTask, ProjectTask.task_id == TimesheetEntry.task_id)
             .where(TimesheetEntry.company_id == company_id))
        if project_id is not None:
            q = q.where(TimesheetEntry.project_id == project_id)
        if employee_id is not None:
            q = q.where(TimesheetEntry.employee_id == employee_id)
        if status is not None:
            q = q.where(TimesheetEntry.status_code == status)
        if date_from is not None:
            q = q.where(TimesheetEntry.work_date >= date_from)
        if date_to is not None:
            q = q.where(TimesheetEntry.work_date <= date_to)
        rows = session.execute(q.order_by(TimesheetEntry.work_date.desc(), TimesheetEntry.entry_id.desc()).limit(limit)).all()
    return [EntryRow(t.entry_id, t.project_id, f"{d.code} — {d.name or ''}", t.task_id, task_name or "", t.employee_id, _name(e),
                     t.work_date, t.hours, t.description or "", t.status_code, t.hourly_cost, t.decision_note or "")
            for t, e, d, task_name in rows]


def pending_for(company_id: int, user_id: int) -> list[EntryRow]:
    """کارکردهای ارسال‌شده‌ای که این کاربر می‌تواند تایید کند."""
    rows = list_entries(company_id, status="SUBMITTED")
    allowed = {pid: can_approve(company_id, user_id, pid) for pid in {r.project_id for r in rows}}
    return [r for r in rows if allowed[r.project_id]]


def entries_exist(session, *, project_id: int | None = None, task_ids: set[int] | None = None) -> bool:
    q = select(TimesheetEntry.entry_id)
    q = q.where(TimesheetEntry.project_id == project_id) if project_id is not None else q.where(TimesheetEntry.task_id.in_(task_ids or {0}))
    return bool(session.scalar(q.limit(1)))
