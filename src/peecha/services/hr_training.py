"""R369: آموزش کارکنان.

- دوره: کد، عنوان، دسته، ساعت، اعتبار گواهی (ماه؛ خالی یعنی بی‌انقضا) و برگزارکننده؛ برای هر پست سازمانی دوره‌های الزامی.
- کلاس: یک اجرای دوره با تاریخ، مدرس، محل، ظرفیت و هزینه؛ برنامه‌ریزی‌شده ← برگزارشده یا لغوشده.
- ثبت‌نام فقط در کلاس برنامه‌ریزی‌شده، تا ظرفیت، برای کارمند فعال. نتیجه: حاضر، قبول (با نمره و شمارهٔ گواهی؛ تاریخ پایان
  کلاس تاریخ گواهی است و انقضا = آن تاریخ + اعتبار دوره)، مردود، غایب. کلاس فقط وقتی برگزارشده می‌شود که نتیجهٔ همه ثبت شده
  باشد؛ کلاسی که نتیجه دارد لغو نمی‌شود.
- ماتریس آموزش: برای هر کارمند فعال و هر دورهٔ الزامی پستش (از قرارداد فعال): معتبر، رو به انقضا (۳۰ روز)، منقضی، در برنامه
  (ثبت‌نام در کلاس آینده) یا انجام‌نشده. هزینهٔ کلاس به‌طور مساوی میان ثبت‌نام‌شدگان تقسیم می‌شود.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.hr import Employee, EmploymentContract, OrganizationalUnit, Position
from peecha.db.models.hr_talent import PositionTraining, TrainingCourse, TrainingEnrollment, TrainingSession

ZERO = decimal.Decimal(0)
FORM_CODE = "hr_training"
CATEGORIES = {"SAFETY": "ایمنی و بهداشت", "TECHNICAL": "فنی و تخصصی", "QUALITY": "کیفیت", "SOFT_SKILLS": "مهارت‌های عمومی",
              "COMPLIANCE": "الزامات قانونی", "OTHER": "سایر"}
SESSION_STATUSES = {"PLANNED": "برنامه‌ریزی‌شده", "COMPLETED": "برگزارشده", "CANCELLED": "لغوشده"}
RESULTS = {"ENROLLED": "ثبت‌نام‌شده", "ATTENDED": "حاضر", "PASSED": "قبول", "FAILED": "مردود", "ABSENT": "غایب"}
MATRIX = {"VALID": "معتبر", "EXPIRING": "رو به انقضا", "EXPIRED": "منقضی", "PLANNED": "در برنامه", "MISSING": "انجام‌نشده"}
EXPIRY_WARNING_DAYS = 30


def _name(e: Employee) -> str:
    return f"{e.first_name} {e.last_name}".strip()


def _add_months(d: datetime.date, months: int) -> datetime.date:
    month = d.month - 1 + months
    year, month = d.year + month // 12, month % 12 + 1
    for day in (d.day, 30, 29, 28):
        try:
            return datetime.date(year, month, day)
        except ValueError:
            continue
    raise ValueError("تاریخ نامعتبر")


# --- دوره ----------------------------------------------------------------------------------------------------------------
@dataclass
class CourseFields:
    code: str
    title: str
    hours: decimal.Decimal
    category_code: str = "OTHER"
    validity_months: int | None = None
    provider: str | None = None
    is_active: bool = True


@dataclass
class CourseRow:
    course_id: int
    code: str
    title: str
    category_code: str
    hours: decimal.Decimal
    validity_months: int | None
    provider: str
    is_active: bool
    position_ids: list[int]

    @property
    def category_label(self) -> str:
        return CATEGORIES[self.category_code]

    @property
    def label(self) -> str:
        return f"{self.code} — {self.title}"


def save_course(company_id: int, f: CourseFields, course_id: int | None = None) -> int:
    code, title = (f.code or "").strip().upper(), (f.title or "").strip()
    if not code or not title:
        raise ValueError("کد و عنوان دوره الزامی است.")
    if f.category_code not in CATEGORIES:
        raise ValueError("دستهٔ دوره نامعتبر است.")
    if decimal.Decimal(f.hours or 0) <= 0:
        raise ValueError("ساعت دوره باید بیشتر از صفر باشد.")
    if f.validity_months is not None and int(f.validity_months) <= 0:
        raise ValueError("اعتبار گواهی باید دست‌کم یک ماه باشد (برای بی‌انقضا خالی بگذارید).")
    with new_session() as session:
        if session.scalar(select(TrainingCourse.course_id).where(TrainingCourse.company_id == company_id, TrainingCourse.code == code,
                                                                 TrainingCourse.course_id != (course_id or 0))):
            raise ValueError(f"کد دورهٔ «{code}» تکراری است.")
        if course_id is None:
            row = TrainingCourse(company_id=company_id)
            session.add(row)
        else:
            row = session.get(TrainingCourse, course_id)
            if row is None or row.company_id != company_id:
                raise ValueError("دوره نامعتبر است.")
        row.code, row.title, row.category_code, row.hours = code, title, f.category_code, decimal.Decimal(f.hours)
        row.validity_months = int(f.validity_months) if f.validity_months else None
        row.provider, row.is_active = (f.provider or "").strip() or None, bool(f.is_active)
        session.commit()
        return row.course_id


def set_required_positions(company_id: int, course_id: int, position_ids: list[int]) -> None:
    with new_session() as session:
        course = session.get(TrainingCourse, course_id)
        if course is None or course.company_id != company_id:
            raise ValueError("دوره نامعتبر است.")
        valid = set(session.scalars(select(Position.position_id).where(Position.company_id == company_id,
                                                                       Position.position_id.in_(position_ids or [0]))))
        if valid != set(position_ids):
            raise ValueError("پست سازمانی نامعتبر است.")
        for row in session.scalars(select(PositionTraining).where(PositionTraining.course_id == course_id)):
            session.delete(row)
        session.flush()
        for pid in sorted(valid):
            session.add(PositionTraining(position_id=pid, course_id=course_id))
        session.commit()


def list_courses(company_id: int, active_only: bool = False) -> list[CourseRow]:
    with new_session() as session:
        q = select(TrainingCourse).where(TrainingCourse.company_id == company_id)
        if active_only:
            q = q.where(TrainingCourse.is_active.is_(True))
        rows = list(session.scalars(q.order_by(TrainingCourse.code)))
        required = defaultdict(list)
        for pt in session.scalars(select(PositionTraining).where(PositionTraining.course_id.in_([r.course_id for r in rows] or [0]))):
            required[pt.course_id].append(pt.position_id)
    return [CourseRow(r.course_id, r.code, r.title, r.category_code, r.hours, r.validity_months, r.provider or "", r.is_active,
                      required[r.course_id]) for r in rows]


# --- کلاس و ثبت‌نام ------------------------------------------------------------------------------------------------------
@dataclass
class SessionFields:
    course_id: int
    start_date: datetime.date
    end_date: datetime.date
    trainer: str | None = None
    location: str | None = None
    capacity: int | None = None
    cost: decimal.Decimal = ZERO


@dataclass
class SessionRow:
    session_id: int
    course_id: int
    course_label: str
    start_date: datetime.date
    end_date: datetime.date
    trainer: str
    location: str
    capacity: int | None
    cost: decimal.Decimal
    status_code: str
    enrolled: int

    @property
    def status_label(self) -> str:
        return SESSION_STATUSES[self.status_code]


@dataclass
class EnrollmentRow:
    enrollment_id: int
    session_id: int
    course_label: str
    employee_id: int
    employee_code: str
    employee_name: str
    status_code: str
    score: decimal.Decimal | None
    certificate_no: str
    completed_on: datetime.date | None
    expires_on: datetime.date | None
    start_date: datetime.date
    hours: decimal.Decimal

    @property
    def status_label(self) -> str:
        return RESULTS[self.status_code]


def save_session(company_id: int, f: SessionFields, session_id: int | None = None) -> int:
    if f.start_date is None or f.end_date is None or f.end_date < f.start_date:
        raise ValueError("تاریخ‌های کلاس نامعتبر است.")
    if f.capacity is not None and int(f.capacity) <= 0:
        raise ValueError("ظرفیت کلاس باید بیشتر از صفر باشد (برای بی‌سقف خالی بگذارید).")
    if decimal.Decimal(f.cost or 0) < 0:
        raise ValueError("هزینهٔ کلاس نمی‌تواند منفی باشد.")
    with new_session() as session:
        course = session.get(TrainingCourse, f.course_id)
        if course is None or course.company_id != company_id or not course.is_active:
            raise ValueError("دورهٔ فعال انتخاب کنید.")
        if session_id is None:
            row = TrainingSession(company_id=company_id)
            session.add(row)
        else:
            row = session.get(TrainingSession, session_id)
            if row is None or row.company_id != company_id:
                raise ValueError("کلاس نامعتبر است.")
            if row.status_code != "PLANNED":
                raise ValueError("فقط کلاس برنامه‌ریزی‌شده ویرایش می‌شود.")
            enrolled = session.scalar(select(func.count()).where(TrainingEnrollment.session_id == session_id)) or 0
            if f.capacity and enrolled > int(f.capacity):
                raise ValueError(f"در این کلاس {enrolled} نفر ثبت‌نام کرده‌اند؛ ظرفیت کمتر نمی‌شود.")
        row.course_id, row.start_date, row.end_date = f.course_id, f.start_date, f.end_date
        row.trainer, row.location = (f.trainer or "").strip() or None, (f.location or "").strip() or None
        row.capacity, row.cost = (int(f.capacity) if f.capacity else None), decimal.Decimal(f.cost or 0)
        session.commit()
        return row.session_id


def list_sessions(company_id: int, course_id: int | None = None) -> list[SessionRow]:
    with new_session() as session:
        q = select(TrainingSession, TrainingCourse).join(TrainingCourse, TrainingCourse.course_id == TrainingSession.course_id).where(
            TrainingSession.company_id == company_id)
        if course_id is not None:
            q = q.where(TrainingSession.course_id == course_id)
        rows = session.execute(q.order_by(TrainingSession.start_date.desc(), TrainingSession.session_id.desc())).all()
        counts = dict(session.execute(select(TrainingEnrollment.session_id, func.count()).where(
            TrainingEnrollment.session_id.in_([s.session_id for s, _c in rows] or [0])).group_by(TrainingEnrollment.session_id)).all())
    return [SessionRow(s.session_id, s.course_id, f"{c.code} — {c.title}", s.start_date, s.end_date, s.trainer or "", s.location or "",
                       s.capacity, s.cost, s.status_code, counts.get(s.session_id, 0)) for s, c in rows]


def _session(session, company_id: int, session_id: int) -> TrainingSession:
    row = session.get(TrainingSession, session_id)
    if row is None or row.company_id != company_id:
        raise ValueError("کلاس نامعتبر است.")
    return row


def enroll(company_id: int, session_id: int, employee_ids: list[int]) -> int:
    with new_session() as session:
        s = _session(session, company_id, session_id)
        if s.status_code != "PLANNED":
            raise ValueError("ثبت‌نام فقط در کلاس برنامه‌ریزی‌شده است.")
        existing = set(session.scalars(select(TrainingEnrollment.employee_id).where(TrainingEnrollment.session_id == session_id)))
        new = [e for e in dict.fromkeys(employee_ids) if e not in existing]
        if s.capacity is not None and len(existing) + len(new) > s.capacity:
            raise ValueError(f"ظرفیت کلاس {s.capacity} نفر است و {len(existing)} نفر ثبت‌نام کرده‌اند.")
        for eid in new:
            e = session.get(Employee, eid)
            if e is None or e.company_id != company_id or e.status != "ACTIVE":
                raise ValueError("فقط کارمند فعال ثبت‌نام می‌شود.")
            session.add(TrainingEnrollment(session_id=session_id, employee_id=eid))
        session.commit()
        return len(new)


def remove_enrollment(company_id: int, enrollment_id: int) -> None:
    with new_session() as session:
        row = session.get(TrainingEnrollment, enrollment_id)
        if row is None:
            raise ValueError("ثبت‌نام نامعتبر است.")
        s = _session(session, company_id, row.session_id)
        if s.status_code != "PLANNED" or row.status_code != "ENROLLED":
            raise ValueError("فقط ثبت‌نام بی‌نتیجه در کلاس برنامه‌ریزی‌شده حذف می‌شود.")
        session.delete(row)
        session.commit()


def record_result(company_id: int, enrollment_id: int, status_code: str, score: decimal.Decimal | None = None,
                  certificate_no: str | None = None) -> None:
    if status_code not in ("ATTENDED", "PASSED", "FAILED", "ABSENT"):
        raise ValueError("نتیجهٔ دوره نامعتبر است.")
    if score is not None and not ZERO <= decimal.Decimal(score) <= 100:
        raise ValueError("نمره از ۰ تا ۱۰۰ است.")
    with new_session() as session:
        row = session.get(TrainingEnrollment, enrollment_id)
        if row is None:
            raise ValueError("ثبت‌نام نامعتبر است.")
        s = _session(session, company_id, row.session_id)
        if s.status_code == "CANCELLED":
            raise ValueError("کلاس لغوشده نتیجه ندارد.")
        if s.start_date > datetime.date.today():
            raise ValueError("نتیجهٔ کلاسی که هنوز شروع نشده ثبت نمی‌شود.")
        course = session.get(TrainingCourse, s.course_id)
        row.status_code, row.score = status_code, (decimal.Decimal(score) if score is not None else None)
        if status_code == "PASSED":
            row.completed_on = s.end_date
            row.expires_on = _add_months(s.end_date, course.validity_months) if course.validity_months else None
            row.certificate_no = (certificate_no or "").strip() or None
        else:
            row.completed_on = row.expires_on = row.certificate_no = None
        session.commit()


def complete_session(company_id: int, session_id: int) -> None:
    with new_session() as session:
        s = _session(session, company_id, session_id)
        if s.status_code != "PLANNED":
            raise ValueError("فقط کلاس برنامه‌ریزی‌شده برگزارشده می‌شود.")
        left = session.scalar(select(func.count()).where(TrainingEnrollment.session_id == session_id,
                                                         TrainingEnrollment.status_code == "ENROLLED")) or 0
        if left:
            raise ValueError(f"نتیجهٔ {left} نفر هنوز ثبت نشده است.")
        s.status_code = "COMPLETED"
        session.commit()


def cancel_session(company_id: int, session_id: int) -> None:
    with new_session() as session:
        s = _session(session, company_id, session_id)
        if s.status_code != "PLANNED":
            raise ValueError("فقط کلاس برنامه‌ریزی‌شده لغو می‌شود.")
        if session.scalar(select(TrainingEnrollment.enrollment_id).where(TrainingEnrollment.session_id == session_id,
                                                                         TrainingEnrollment.status_code != "ENROLLED").limit(1)):
            raise ValueError("برای این کلاس نتیجه ثبت شده و لغو نمی‌شود.")
        s.status_code = "CANCELLED"
        session.commit()


def list_enrollments(company_id: int, session_id: int | None = None, employee_id: int | None = None) -> list[EnrollmentRow]:
    with new_session() as session:
        q = (select(TrainingEnrollment, TrainingSession, TrainingCourse, Employee)
             .join(TrainingSession, TrainingSession.session_id == TrainingEnrollment.session_id)
             .join(TrainingCourse, TrainingCourse.course_id == TrainingSession.course_id)
             .join(Employee, Employee.employee_id == TrainingEnrollment.employee_id)
             .where(TrainingSession.company_id == company_id))
        if session_id is not None:
            q = q.where(TrainingEnrollment.session_id == session_id)
        if employee_id is not None:
            q = q.where(TrainingEnrollment.employee_id == employee_id)
        rows = session.execute(q.order_by(TrainingSession.start_date.desc(), Employee.employee_code)).all()
    return [EnrollmentRow(en.enrollment_id, s.session_id, f"{c.code} — {c.title}", e.employee_id, e.employee_code, _name(e), en.status_code,
                          en.score, en.certificate_no or "", en.completed_on, en.expires_on, s.start_date, c.hours)
            for en, s, c, e in rows]


# --- ماتریس و گزارش ----------------------------------------------------------------------------------------------------
@dataclass
class MatrixCell:
    course_id: int
    status_code: str
    expires_on: datetime.date | None

    @property
    def status_label(self) -> str:
        return MATRIX[self.status_code]


@dataclass
class MatrixRow:
    employee_id: int
    employee_code: str
    employee_name: str
    position: str
    org_unit_id: int | None
    org_unit: str
    cells: dict[int, MatrixCell]


def matrix(company_id: int, org_unit_id: int | None = None, today: datetime.date | None = None) -> tuple[list[CourseRow], list[MatrixRow]]:
    """(دوره‌های الزامی که دست‌کم یک پست دارند، ردیف هر کارمند فعال با وضعیت هر دورهٔ الزامی پستش)"""
    today = today or datetime.date.today()
    courses = [c for c in list_courses(company_id) if c.position_ids]
    by_position = defaultdict(set)
    for c in courses:
        for pid in c.position_ids:
            by_position[pid].add(c.course_id)
    with new_session() as session:
        rows = session.execute(select(Employee, EmploymentContract, Position, OrganizationalUnit)
                               .join(EmploymentContract, EmploymentContract.employee_id == Employee.employee_id)
                               .join(Position, Position.position_id == EmploymentContract.position_id)
                               .join(OrganizationalUnit, OrganizationalUnit.org_unit_id == EmploymentContract.org_unit_id)
                               .where(Employee.company_id == company_id, Employee.status == "ACTIVE", EmploymentContract.status == "ACTIVE")
                               .order_by(Employee.employee_code)).all()
        ids = [e.employee_id for e, *_ in rows] or [0]
        results = session.execute(select(TrainingEnrollment, TrainingSession).join(
            TrainingSession, TrainingSession.session_id == TrainingEnrollment.session_id).where(
            TrainingEnrollment.employee_id.in_(ids), TrainingSession.status_code != "CANCELLED")).all()
    best: dict[tuple[int, int], datetime.date | None] = {}
    passed: set[tuple[int, int]] = set()
    planned: set[tuple[int, int]] = set()
    for en, s in results:
        key = (en.employee_id, s.course_id)
        if en.status_code == "PASSED":
            if key not in passed or (best[key] is not None and (en.expires_on is None or en.expires_on > best[key])):
                best[key] = en.expires_on
            passed.add(key)
        elif en.status_code == "ENROLLED" and s.status_code == "PLANNED":
            planned.add(key)
    out = []
    for e, _contract, position, unit in rows:
        if org_unit_id is not None and unit.org_unit_id != org_unit_id:
            continue
        cells = {}
        for cid in by_position.get(position.position_id, ()):
            key = (e.employee_id, cid)
            expires = best.get(key)
            if key in passed and (expires is None or expires >= today):
                code = "EXPIRING" if expires is not None and (expires - today).days <= EXPIRY_WARNING_DAYS else "VALID"
            elif key in planned:
                code = "PLANNED"
            elif key in passed:
                code = "EXPIRED"
            else:
                code = "MISSING"
            cells[cid] = MatrixCell(cid, code, expires)
        out.append(MatrixRow(e.employee_id, e.employee_code, _name(e), position.title, unit.org_unit_id, unit.name, cells))
    return courses, out


def gaps(company_id: int, today: datetime.date | None = None) -> dict[str, int]:
    """تعداد دوره‌های الزامی منقضی، رو به انقضا و انجام‌نشده (برای کارتابل و داشبورد)."""
    _courses, rows = matrix(company_id, today=today)
    counts = {k: 0 for k in MATRIX}
    for r in rows:
        for cell in r.cells.values():
            counts[cell.status_code] += 1
    return counts


def hours_report(company_id: int, date_from: datetime.date, date_to: datetime.date) -> list[tuple[str, str, decimal.Decimal, decimal.Decimal]]:
    """(کد، کارمند، ساعت آموزش قبول یا حاضر، سهم هزینه) برای کلاس‌های برگزارشده در بازه."""
    with new_session() as session:
        sessions = {s.session_id: s for s in session.scalars(select(TrainingSession).where(
            TrainingSession.company_id == company_id, TrainingSession.status_code == "COMPLETED",
            TrainingSession.end_date >= date_from, TrainingSession.end_date <= date_to))}
        counts = dict(session.execute(select(TrainingEnrollment.session_id, func.count()).where(
            TrainingEnrollment.session_id.in_(list(sessions) or [0])).group_by(TrainingEnrollment.session_id)).all())
        hours = {c.course_id: c.hours for c in session.scalars(select(TrainingCourse).where(TrainingCourse.company_id == company_id))}
        rows = session.execute(select(TrainingEnrollment, Employee).join(Employee, Employee.employee_id == TrainingEnrollment.employee_id)
                               .where(TrainingEnrollment.session_id.in_(list(sessions) or [0]))).all()
    totals: dict[int, list] = {}
    for en, e in rows:
        s = sessions[en.session_id]
        item = totals.setdefault(e.employee_id, [e.employee_code, _name(e), ZERO, ZERO])
        if en.status_code in ("PASSED", "ATTENDED", "FAILED"):
            item[2] += hours[s.course_id]
        item[3] += (s.cost / counts[en.session_id]).quantize(decimal.Decimal("0.01"))
    return sorted((tuple(v) for v in totals.values()), key=lambda t: t[0])
