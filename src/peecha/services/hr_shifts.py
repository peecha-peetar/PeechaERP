"""R359: شیفت کاری، واگذاری شیفت به کارکنان و گزارش تأخیر، تعجیل، اضافه‌ماندن و غیبت از روی حضور و غیاب.

برای هر روز کارمند از تاریخ واگذاری شیفت (فقط تا امروز):
- تعطیل: روز تقویم تعطیلات شرکت (همان تقویم گردش کار)؛ استراحت: روز استراحت هفتگی شیفت.
- مرخصی/مأموریت: مرخصی تاییدشدهٔ روزانه که این روز را پوشش می‌دهد (مرخصی ساعتی روز را کامل نمی‌کند).
- حاضر: رکورد حضور ردنشده؛ تأخیر = ورود − شروع شیفت اگر از دقیقهٔ ارفاق بیشتر باشد (همهٔ دقیقه‌ها)، تعجیل = پایان شیفت −
  خروج، اضافه‌ماندن = خروج − پایان شیفت. رکورد «فقط مجموع ساعات» حاضر است ولی تأخیرش معلوم نیست.
- غیبت: روز کاری بدون حضور و بدون مرخصی.
گزارش فقط محاسبه است: اضافه‌کاری یا کسر حقوق خودبه‌خود ثبت نمی‌شود.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.hr import AttendanceRecord, Employee, EmployeeShiftAssignment, LeaveRequest, WorkShift

WEEKDAYS = {5: "شنبه", 6: "یکشنبه", 0: "دوشنبه", 1: "سه‌شنبه", 2: "چهارشنبه", 3: "پنجشنبه", 4: "جمعه"}
DAY_KINDS = {"PRESENT": "حاضر", "ABSENT": "غایب", "LEAVE": "مرخصی", "MISSION": "مأموریت", "OFF": "استراحت", "HOLIDAY": "تعطیل"}


@dataclass
class ShiftFields:
    code: str
    name: str
    start_time: datetime.time
    end_time: datetime.time
    break_minutes: int = 0
    grace_minutes: int = 0
    off_weekdays: tuple[int, ...] = (4,)
    is_active: bool = True


@dataclass
class ShiftRow:
    shift_id: int
    code: str
    name: str
    start_time: datetime.time
    end_time: datetime.time
    break_minutes: int
    grace_minutes: int
    off_weekdays: tuple[int, ...]
    is_active: bool

    @property
    def work_minutes(self) -> int:
        return _minutes(self.end_time) - _minutes(self.start_time) - self.break_minutes

    @property
    def off_label(self) -> str:
        return "، ".join(WEEKDAYS[d] for d in sorted(self.off_weekdays, key=lambda d: (d - 5) % 7)) or "—"


def _minutes(t: datetime.time) -> int:
    return t.hour * 60 + t.minute


def _off(text: str | None) -> tuple[int, ...]:
    return tuple(sorted({int(x) for x in (text or "").split(",") if x.strip().isdigit() and 0 <= int(x) <= 6}))


def _row(s: WorkShift) -> ShiftRow:
    return ShiftRow(s.shift_id, s.code, s.name, s.start_time, s.end_time, s.break_minutes, s.grace_minutes, _off(s.off_weekdays),
                    s.is_active)


def save_shift(company_id: int, f: ShiftFields, shift_id: int | None = None) -> int:
    code, name = (f.code or "").strip().upper(), (f.name or "").strip()
    if not code or not name:
        raise ValueError("کد و نام شیفت الزامی است.")
    if f.end_time <= f.start_time:
        raise ValueError("پایان شیفت باید بعد از شروع آن باشد (شیفت شب‌گذر پشتیبانی نمی‌شود).")
    if f.break_minutes < 0 or f.grace_minutes < 0:
        raise ValueError("دقیقهٔ استراحت و ارفاق نمی‌تواند منفی باشد.")
    if f.break_minutes >= _minutes(f.end_time) - _minutes(f.start_time):
        raise ValueError("استراحت از طول شیفت بیشتر است.")
    if len(set(f.off_weekdays)) >= 7:
        raise ValueError("دست‌کم یک روز کاری در هفته لازم است.")
    with new_session() as session:
        clash = session.scalar(select(WorkShift.shift_id).where(WorkShift.company_id == company_id, WorkShift.code == code))
        if clash is not None and clash != shift_id:
            raise ValueError("این کد شیفت قبلاً تعریف شده است.")
        row = session.get(WorkShift, shift_id) if shift_id else WorkShift(company_id=company_id)
        if row is None or row.company_id != company_id:
            raise ValueError("شیفت نامعتبر است.")
        row.code, row.name, row.start_time, row.end_time = code, name, f.start_time, f.end_time
        row.break_minutes, row.grace_minutes, row.is_active = f.break_minutes, f.grace_minutes, f.is_active
        row.off_weekdays = ",".join(str(d) for d in sorted(set(f.off_weekdays)))
        session.add(row)
        session.commit()
        return row.shift_id


def list_shifts(company_id: int, active_only: bool = False) -> list[ShiftRow]:
    with new_session() as session:
        q = select(WorkShift).where(WorkShift.company_id == company_id)
        if active_only:
            q = q.where(WorkShift.is_active.is_(True))
        return [_row(s) for s in session.scalars(q.order_by(WorkShift.code))]


def delete_shift(company_id: int, shift_id: int) -> None:
    with new_session() as session:
        row = session.get(WorkShift, shift_id)
        if row is None or row.company_id != company_id:
            raise ValueError("شیفت نامعتبر است.")
        if session.scalar(select(EmployeeShiftAssignment.assignment_id).where(EmployeeShiftAssignment.shift_id == shift_id).limit(1)):
            raise ValueError("این شیفت به کارمندی واگذار شده است؛ غیرفعالش کنید.")
        session.delete(row)
        session.commit()


@dataclass
class AssignmentRow:
    assignment_id: int
    employee_id: int
    employee_name: str
    shift_id: int
    shift_label: str
    valid_from: datetime.date


def assign_shift(company_id: int, employee_id: int, shift_id: int, valid_from: datetime.date) -> int:
    """از valid_from این شیفت برای کارمند است (واگذاری همان روز جایگزین می‌شود)."""
    with new_session() as session:
        emp, shift = session.get(Employee, employee_id), session.get(WorkShift, shift_id)
        if emp is None or emp.company_id != company_id:
            raise ValueError("کارمند نامعتبر است.")
        if shift is None or shift.company_id != company_id:
            raise ValueError("شیفت نامعتبر است.")
        row = session.scalar(select(EmployeeShiftAssignment).where(EmployeeShiftAssignment.employee_id == employee_id,
                                                                   EmployeeShiftAssignment.valid_from == valid_from))
        row = row or EmployeeShiftAssignment(company_id=company_id, employee_id=employee_id, valid_from=valid_from)
        row.shift_id = shift_id
        session.add(row)
        session.commit()
        return row.assignment_id


def remove_assignment(company_id: int, assignment_id: int) -> None:
    with new_session() as session:
        row = session.get(EmployeeShiftAssignment, assignment_id)
        if row is None or row.company_id != company_id:
            raise ValueError("واگذاری نامعتبر است.")
        session.delete(row)
        session.commit()


def _name(e: Employee) -> str:
    return " ".join(p for p in (e.first_name, e.last_name) if p)


def list_assignments(company_id: int, employee_id: int | None = None) -> list[AssignmentRow]:
    with new_session() as session:
        q = (select(EmployeeShiftAssignment, Employee, WorkShift)
             .join(Employee, Employee.employee_id == EmployeeShiftAssignment.employee_id)
             .join(WorkShift, WorkShift.shift_id == EmployeeShiftAssignment.shift_id)
             .where(EmployeeShiftAssignment.company_id == company_id))
        if employee_id:
            q = q.where(EmployeeShiftAssignment.employee_id == employee_id)
        return [AssignmentRow(a.assignment_id, e.employee_id, _name(e), s.shift_id, f"{s.code} — {s.name}", a.valid_from)
                for a, e, s in session.execute(q.order_by(Employee.employee_code, EmployeeShiftAssignment.valid_from.desc()))]


# --- گزارش ---------------------------------------------------------------------------------------------------
@dataclass
class DayRow:
    employee_id: int
    employee_code: str
    employee_name: str
    work_date: datetime.date
    shift_label: str
    kind: str
    clock_in: datetime.time | None = None
    clock_out: datetime.time | None = None
    late_minutes: int = 0
    early_minutes: int = 0
    extra_minutes: int = 0
    pending: bool = False

    @property
    def kind_label(self) -> str:
        return DAY_KINDS[self.kind]


@dataclass
class SummaryRow:
    employee_id: int
    employee_code: str
    employee_name: str
    workdays: int = 0
    present: int = 0
    absent: int = 0
    leave: int = 0
    late_days: int = 0
    late_minutes: int = 0
    early_minutes: int = 0
    extra_minutes: int = 0
    absent_dates: list = field(default_factory=list)


def daily_report(company_id: int, start: datetime.date, end: datetime.date, employee_id: int | None = None,
                 today: datetime.date | None = None) -> list[DayRow]:
    from peecha.services.workflow import calendar

    end = min(end, today or datetime.date.today())
    if end < start:
        return []
    with new_session() as session:
        q = (select(EmployeeShiftAssignment, WorkShift).join(WorkShift, WorkShift.shift_id == EmployeeShiftAssignment.shift_id)
             .where(EmployeeShiftAssignment.company_id == company_id, EmployeeShiftAssignment.valid_from <= end))
        if employee_id:
            q = q.where(EmployeeShiftAssignment.employee_id == employee_id)
        plans: dict[int, list] = {}
        for a, s in session.execute(q.order_by(EmployeeShiftAssignment.valid_from)):
            plans.setdefault(a.employee_id, []).append((a.valid_from, _row(s)))
        if not plans:
            return []
        employees = {e.employee_id: e for e in session.scalars(select(Employee).where(Employee.employee_id.in_(list(plans))))}
        records = {(r.employee_id, r.work_date): r for r in session.scalars(select(AttendanceRecord).where(
            AttendanceRecord.employee_id.in_(list(plans)), AttendanceRecord.work_date.between(start, end),
            AttendanceRecord.status != "REJECTED"))}
        leaves = [r for r in session.scalars(select(LeaveRequest).where(
            LeaveRequest.employee_id.in_(list(plans)), LeaveRequest.status_code == "APPROVED", LeaveRequest.leave_type != "HOURLY",
            LeaveRequest.from_date <= end, LeaveRequest.to_date >= start))]
    holidays = calendar.holiday_dates(company_id, start, end)
    out: list[DayRow] = []
    for emp_id, plan in plans.items():
        e = employees[emp_id]
        day = max(start, plan[0][0])
        while day <= end:
            shift = next(s for since, s in reversed(plan) if since <= day)
            row = DayRow(emp_id, e.employee_code, _name(e), day, f"{shift.code} — {shift.name}", "ABSENT")
            record = records.get((emp_id, day))
            leave = next((lv for lv in leaves if lv.employee_id == emp_id and lv.from_date <= day <= lv.to_date), None)
            if day in holidays:
                row.kind = "HOLIDAY"
            elif day.weekday() in shift.off_weekdays:
                row.kind = "OFF"
            elif record is not None:
                row.kind, row.clock_in, row.clock_out = "PRESENT", record.clock_in, record.clock_out
                row.pending = record.status != "APPROVED"
                if record.clock_in is not None:
                    late = _minutes(record.clock_in) - _minutes(shift.start_time)
                    row.late_minutes = late if late > shift.grace_minutes else 0
                if record.clock_out is not None:
                    gap = _minutes(shift.end_time) - _minutes(record.clock_out)
                    row.early_minutes, row.extra_minutes = max(gap, 0), max(-gap, 0)
            elif leave is not None:
                row.kind = "MISSION" if leave.leave_type == "MISSION" else "LEAVE"
            out.append(row)
            day += datetime.timedelta(days=1)
    out.sort(key=lambda r: (r.employee_code, r.work_date))
    return out


def summary(company_id: int, start: datetime.date, end: datetime.date, employee_id: int | None = None,
            today: datetime.date | None = None) -> list[SummaryRow]:
    out: dict[int, SummaryRow] = {}
    for d in daily_report(company_id, start, end, employee_id, today):
        s = out.setdefault(d.employee_id, SummaryRow(d.employee_id, d.employee_code, d.employee_name))
        if d.kind in ("HOLIDAY", "OFF"):
            continue
        s.workdays += 1
        if d.kind == "PRESENT" or d.kind == "MISSION":
            s.present += 1
        elif d.kind == "LEAVE":
            s.leave += 1
        else:
            s.absent += 1
            s.absent_dates.append(d.work_date)
        s.late_days += 1 if d.late_minutes else 0
        s.late_minutes += d.late_minutes
        s.early_minutes += d.early_minutes
        s.extra_minutes += d.extra_minutes
    return sorted(out.values(), key=lambda s: s.employee_code)
