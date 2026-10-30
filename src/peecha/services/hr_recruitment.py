"""R367: جذب و استخدام.

- فرصت شغلی روی یک پست سازمانی با تعداد نیرو، بازهٔ حقوق و مدیر استخدام؛ باز، متوقف، بسته یا تکمیل‌شده.
- متقاضی یک بار ثبت می‌شود (کد ملی تکراری پذیرفته نمی‌شود) و می‌تواند برای چند فرصت درخواست بدهد.
- مراحل درخواست: دریافت ← بررسی اولیه ← مصاحبه ← پیشنهاد ← استخدام؛ رد (با دلیل) یا انصراف از هر مرحلهٔ باز؛ ردشده یا
  منصرف‌شده دوباره به بررسی اولیه برمی‌گردد. هر تغییر مرحله با کاربر و زمان در سابقه می‌ماند.
- پیشنهاد حقوق و تاریخ شروع می‌خواهد؛ استخدام فقط از مرحلهٔ پیشنهاد و برای فرصت باز، با همان سرویس تعریف کارمند پرونده
  می‌سازد (پست و واحد فرصت، حقوق پیشنهادی، تاریخ شروع). با پرشدن تعداد نیرو فرصت «تکمیل‌شده» می‌شود.
- مصاحبه: زمان، مصاحبه‌گر و نوع؛ نتیجه امتیاز ۱ تا ۵ و پیشنهاد (استخدام، شاید، خیر). امتیاز درخواست میانگین مصاحبه‌های انجام‌شده است.
"""

from __future__ import annotations

import datetime
import decimal
from collections import Counter, defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.hr import Employee, Position
from peecha.db.models.hr_talent import ApplicationEvent, Candidate, Interview, JobApplication, JobOpening

OPENING_STATUSES = {"OPEN": "باز", "ON_HOLD": "متوقف", "CLOSED": "بسته", "FILLED": "تکمیل‌شده"}
STAGES = {"APPLIED": "دریافت درخواست", "SCREENING": "بررسی اولیه", "INTERVIEW": "مصاحبه", "OFFER": "پیشنهاد همکاری",
          "HIRED": "استخدام‌شده", "REJECTED": "ردشده", "WITHDRAWN": "انصراف"}
PIPELINE = ("APPLIED", "SCREENING", "INTERVIEW", "OFFER", "HIRED")
CLOSED_STAGES = ("HIRED", "REJECTED", "WITHDRAWN")
SOURCES = {"WEBSITE": "سایت شرکت", "JOB_BOARD": "سایت کاریابی", "REFERRAL": "معرفی همکاران", "AGENCY": "مؤسسهٔ کاریابی",
           "CAMPUS": "دانشگاه", "OTHER": "سایر"}
MODES = {"IN_PERSON": "حضوری", "PHONE": "تلفنی", "VIDEO": "تصویری"}
RECOMMENDATIONS = {"HIRE": "استخدام شود", "MAYBE": "شاید", "NO": "خیر"}
INTERVIEW_STATUSES = {"SCHEDULED": "برنامه‌ریزی‌شده", "DONE": "انجام‌شده", "CANCELLED": "لغوشده"}


def _name(first: str | None, last: str | None) -> str:
    return f"{first or ''} {last or ''}".strip()


# --- فرصت شغلی --------------------------------------------------------------------------------------------------------
@dataclass
class OpeningFields:
    code: str
    title: str
    position_id: int
    opened_on: datetime.date
    headcount: int = 1
    status_code: str = "OPEN"
    close_by: datetime.date | None = None
    salary_min: decimal.Decimal | None = None
    salary_max: decimal.Decimal | None = None
    hiring_manager_employee_id: int | None = None
    description: str | None = None
    requirements: str | None = None


@dataclass
class OpeningRow:
    opening_id: int
    code: str
    title: str
    position_id: int
    position_title: str
    org_unit_id: int
    headcount: int
    status_code: str
    opened_on: datetime.date
    close_by: datetime.date | None
    salary_min: decimal.Decimal | None
    salary_max: decimal.Decimal | None
    hiring_manager_employee_id: int | None
    hiring_manager: str
    description: str
    requirements: str
    applications: int
    hired: int

    @property
    def status_label(self) -> str:
        return OPENING_STATUSES[self.status_code]

    @property
    def label(self) -> str:
        return f"{self.code} — {self.title}"


def save_opening(company_id: int, user_id: int | None, f: OpeningFields, opening_id: int | None = None) -> int:
    code, title = (f.code or "").strip().upper(), (f.title or "").strip()
    if not code or not title:
        raise ValueError("کد و عنوان فرصت شغلی الزامی است.")
    if f.status_code not in OPENING_STATUSES:
        raise ValueError("وضعیت فرصت شغلی نامعتبر است.")
    if int(f.headcount or 0) < 1:
        raise ValueError("تعداد نیروی موردنیاز دست‌کم یک نفر است.")
    if f.close_by and f.opened_on and f.close_by < f.opened_on:
        raise ValueError("مهلت جذب نمی‌تواند پیش از تاریخ شروع باشد.")
    if f.salary_min is not None and f.salary_max is not None and f.salary_max < f.salary_min:
        raise ValueError("سقف حقوق نمی‌تواند کمتر از کف آن باشد.")
    with new_session() as session:
        position = session.get(Position, f.position_id)
        if position is None or position.company_id != company_id:
            raise ValueError("پست سازمانی نامعتبر است.")
        if f.hiring_manager_employee_id is not None:
            e = session.get(Employee, f.hiring_manager_employee_id)
            if e is None or e.company_id != company_id:
                raise ValueError("مدیر استخدام نامعتبر است.")
        if session.scalar(select(JobOpening.opening_id).where(JobOpening.company_id == company_id, JobOpening.code == code,
                                                              JobOpening.opening_id != (opening_id or 0))):
            raise ValueError(f"کد فرصت شغلی «{code}» تکراری است.")
        if opening_id is None:
            row = JobOpening(company_id=company_id, created_by_user_id=user_id)
            session.add(row)
        else:
            row = session.get(JobOpening, opening_id)
            if row is None or row.company_id != company_id:
                raise ValueError("فرصت شغلی نامعتبر است.")
            hired = session.scalar(select(func.count()).where(JobApplication.opening_id == opening_id,
                                                              JobApplication.stage_code == "HIRED")) or 0
            if int(f.headcount) < hired:
                raise ValueError(f"برای این فرصت {hired} نفر استخدام شده‌اند؛ تعداد نیرو کمتر از آن نمی‌شود.")
        row.code, row.title, row.position_id, row.headcount = code, title, f.position_id, int(f.headcount)
        row.status_code, row.opened_on, row.close_by = f.status_code, f.opened_on, f.close_by
        row.salary_min, row.salary_max = f.salary_min, f.salary_max
        row.hiring_manager_employee_id = f.hiring_manager_employee_id
        row.description, row.requirements = (f.description or "").strip() or None, (f.requirements or "").strip() or None
        session.commit()
        return row.opening_id


def list_openings(company_id: int, statuses: tuple[str, ...] | None = None) -> list[OpeningRow]:
    with new_session() as session:
        q = select(JobOpening, Position).join(Position, Position.position_id == JobOpening.position_id).where(
            JobOpening.company_id == company_id)
        if statuses:
            q = q.where(JobOpening.status_code.in_(statuses))
        rows = session.execute(q.order_by(JobOpening.opened_on.desc(), JobOpening.opening_id.desc())).all()
        ids = [o.opening_id for o, _p in rows] or [0]
        apps = dict(session.execute(select(JobApplication.opening_id, func.count()).where(JobApplication.opening_id.in_(ids))
                                    .group_by(JobApplication.opening_id)).all())
        hired = dict(session.execute(select(JobApplication.opening_id, func.count()).where(
            JobApplication.opening_id.in_(ids), JobApplication.stage_code == "HIRED").group_by(JobApplication.opening_id)).all())
        managers = {e.employee_id: _name(e.first_name, e.last_name) for e in session.scalars(select(Employee).where(
            Employee.employee_id.in_({o.hiring_manager_employee_id for o, _p in rows if o.hiring_manager_employee_id} or {0})))}
    return [OpeningRow(o.opening_id, o.code, o.title, o.position_id, p.title, p.org_unit_id, o.headcount, o.status_code, o.opened_on,
                       o.close_by, o.salary_min, o.salary_max, o.hiring_manager_employee_id, managers.get(o.hiring_manager_employee_id, ""),
                       o.description or "", o.requirements or "", apps.get(o.opening_id, 0), hired.get(o.opening_id, 0))
            for o, p in rows]


# --- متقاضی -----------------------------------------------------------------------------------------------------------
@dataclass
class CandidateFields:
    first_name: str
    last_name: str
    national_id: str | None = None
    mobile: str | None = None
    email: str | None = None
    education: str | None = None
    experience_years: decimal.Decimal | None = None
    source_code: str = "OTHER"
    notes: str | None = None


@dataclass
class CandidateRow:
    candidate_id: int
    first_name: str
    last_name: str
    national_id: str
    mobile: str
    email: str
    education: str
    experience_years: decimal.Decimal | None
    source_code: str
    notes: str
    applications: int

    @property
    def full_name(self) -> str:
        return _name(self.first_name, self.last_name)

    @property
    def source_label(self) -> str:
        return SOURCES[self.source_code]


def save_candidate(company_id: int, f: CandidateFields, candidate_id: int | None = None) -> int:
    from peecha import numerals

    first, last = (f.first_name or "").strip(), (f.last_name or "").strip()
    if not first or not last:
        raise ValueError("نام و نام خانوادگی متقاضی الزامی است.")
    if f.source_code not in SOURCES:
        raise ValueError("منبع آشنایی نامعتبر است.")
    national = numerals.to_ascii_digits((f.national_id or "").strip()) or None
    if national and (not national.isdigit() or len(national) != 10):
        raise ValueError("کد ملی باید ۱۰ رقم باشد.")
    if f.experience_years is not None and f.experience_years < 0:
        raise ValueError("سابقهٔ کار نمی‌تواند منفی باشد.")
    with new_session() as session:
        if national and session.scalar(select(Candidate.candidate_id).where(
                Candidate.company_id == company_id, Candidate.national_id == national, Candidate.candidate_id != (candidate_id or 0))):
            raise ValueError("متقاضی با این کد ملی قبلاً ثبت شده است.")
        if candidate_id is None:
            row = Candidate(company_id=company_id)
            session.add(row)
        else:
            row = session.get(Candidate, candidate_id)
            if row is None or row.company_id != company_id:
                raise ValueError("متقاضی نامعتبر است.")
        row.first_name, row.last_name, row.national_id = first, last, national
        row.mobile = numerals.to_ascii_digits((f.mobile or "").strip()) or None
        row.email = (f.email or "").strip() or None
        row.education, row.experience_years = (f.education or "").strip() or None, f.experience_years
        row.source_code, row.notes = f.source_code, (f.notes or "").strip() or None
        session.commit()
        return row.candidate_id


def list_candidates(company_id: int, search: str = "") -> list[CandidateRow]:
    with new_session() as session:
        q = select(Candidate).where(Candidate.company_id == company_id)
        needle = (search or "").strip()
        if needle:
            from peecha import numerals

            like = f"%{numerals.to_ascii_digits(needle)}%"
            q = q.where((Candidate.first_name + " " + Candidate.last_name).ilike(f"%{needle}%") | Candidate.national_id.ilike(like)
                        | Candidate.mobile.ilike(like))
        rows = list(session.scalars(q.order_by(Candidate.candidate_id.desc())))
        counts = dict(session.execute(select(JobApplication.candidate_id, func.count()).where(
            JobApplication.candidate_id.in_([r.candidate_id for r in rows] or [0])).group_by(JobApplication.candidate_id)).all())
    return [CandidateRow(r.candidate_id, r.first_name, r.last_name, r.national_id or "", r.mobile or "", r.email or "", r.education or "",
                         r.experience_years, r.source_code, r.notes or "", counts.get(r.candidate_id, 0)) for r in rows]


# --- درخواست و مراحل ----------------------------------------------------------------------------------------------------
@dataclass
class ApplicationRow:
    application_id: int
    opening_id: int
    opening_label: str
    candidate_id: int
    candidate_name: str
    source_code: str
    stage_code: str
    applied_on: datetime.date
    offer_salary: decimal.Decimal | None
    offer_start_date: datetime.date | None
    decision_note: str
    employee_id: int | None
    hired_on: datetime.date | None
    rating: decimal.Decimal | None
    interviews: int

    @property
    def stage_label(self) -> str:
        return STAGES[self.stage_code]

    @property
    def is_open(self) -> bool:
        return self.stage_code not in CLOSED_STAGES


def _event(session, application_id: int, from_stage: str | None, to_stage: str, user_id: int | None, note: str | None = None) -> None:
    session.add(ApplicationEvent(application_id=application_id, from_stage=from_stage, to_stage=to_stage, user_id=user_id,
                                 note=(note or "").strip() or None))


def _application(session, company_id: int, application_id: int) -> JobApplication:
    row = session.get(JobApplication, application_id)
    if row is None or row.company_id != company_id:
        raise ValueError("درخواست نامعتبر است.")
    return row


def apply(company_id: int, user_id: int | None, opening_id: int, candidate_id: int, applied_on: datetime.date | None = None) -> int:
    with new_session() as session:
        opening = session.get(JobOpening, opening_id)
        candidate = session.get(Candidate, candidate_id)
        if opening is None or opening.company_id != company_id or candidate is None or candidate.company_id != company_id:
            raise ValueError("فرصت شغلی یا متقاضی نامعتبر است.")
        if opening.status_code != "OPEN":
            raise ValueError("برای فرصت شغلی غیرباز درخواست ثبت نمی‌شود.")
        if session.scalar(select(JobApplication.application_id).where(JobApplication.opening_id == opening_id,
                                                                      JobApplication.candidate_id == candidate_id)):
            raise ValueError("این متقاضی برای همین فرصت درخواست دارد.")
        row = JobApplication(company_id=company_id, opening_id=opening_id, candidate_id=candidate_id,
                             applied_on=applied_on or datetime.date.today())
        session.add(row)
        session.flush()
        _event(session, row.application_id, None, "APPLIED", user_id)
        session.commit()
        return row.application_id


def advance(company_id: int, user_id: int | None, application_id: int, note: str | None = None) -> str:
    """یک مرحله جلو (دریافت ← بررسی ← مصاحبه ← پیشنهاد)؛ پیشنهاد با make_offer و استخدام با hire."""
    with new_session() as session:
        row = _application(session, company_id, application_id)
        if row.stage_code not in ("APPLIED", "SCREENING"):
            raise ValueError("از این مرحله با «پیشنهاد همکاری» یا «استخدام» جلو بروید." if row.stage_code in ("INTERVIEW", "OFFER")
                             else "درخواست بسته‌شده جلو نمی‌رود.")
        nxt = PIPELINE[PIPELINE.index(row.stage_code) + 1]
        _event(session, row.application_id, row.stage_code, nxt, user_id, note)
        row.stage_code = nxt
        session.commit()
        return nxt


def make_offer(company_id: int, user_id: int | None, application_id: int, salary: decimal.Decimal, start_date: datetime.date,
               note: str | None = None) -> None:
    if salary is None or decimal.Decimal(salary) <= 0:
        raise ValueError("حقوق پیشنهادی را وارد کنید.")
    if start_date is None:
        raise ValueError("تاریخ شروع همکاری را وارد کنید.")
    with new_session() as session:
        row = _application(session, company_id, application_id)
        if row.stage_code not in ("SCREENING", "INTERVIEW", "OFFER"):
            raise ValueError("پیشنهاد همکاری پس از بررسی اولیه یا مصاحبه داده می‌شود.")
        opening = session.get(JobOpening, row.opening_id)
        if opening.salary_max is not None and decimal.Decimal(salary) > opening.salary_max:
            raise ValueError("حقوق پیشنهادی از سقف حقوق این فرصت شغلی بیشتر است.")
        if row.stage_code != "OFFER":
            _event(session, row.application_id, row.stage_code, "OFFER", user_id, note)
        row.stage_code, row.offer_salary, row.offer_start_date = "OFFER", decimal.Decimal(salary), start_date
        session.commit()


def close(company_id: int, user_id: int | None, application_id: int, stage: str, reason: str | None = None) -> None:
    """رد (با دلیل) یا انصراف متقاضی."""
    if stage not in ("REJECTED", "WITHDRAWN"):
        raise ValueError("بستن درخواست فقط با رد یا انصراف است.")
    if stage == "REJECTED" and not (reason or "").strip():
        raise ValueError("دلیل رد متقاضی را بنویسید.")
    with new_session() as session:
        row = _application(session, company_id, application_id)
        if row.stage_code in CLOSED_STAGES:
            raise ValueError("این درخواست قبلاً بسته شده است.")
        _event(session, row.application_id, row.stage_code, stage, user_id, reason)
        row.stage_code, row.decision_note = stage, (reason or "").strip() or None
        session.commit()


def reopen(company_id: int, user_id: int | None, application_id: int) -> None:
    with new_session() as session:
        row = _application(session, company_id, application_id)
        if row.stage_code not in ("REJECTED", "WITHDRAWN"):
            raise ValueError("فقط درخواست ردشده یا منصرف‌شده دوباره باز می‌شود.")
        if session.get(JobOpening, row.opening_id).status_code != "OPEN":
            raise ValueError("فرصت شغلی این درخواست دیگر باز نیست.")
        _event(session, row.application_id, row.stage_code, "SCREENING", user_id, "بازگشایی")
        row.stage_code, row.decision_note = "SCREENING", None
        session.commit()


def hire(company_id: int, user_id: int | None, application_id: int, employee_code: str) -> int:
    """پروندهٔ پرسنلی با همان سرویس تعریف کارمند؛ برمی‌گرداند: شناسهٔ کارمند."""
    from peecha.services import hr

    with new_session() as session:
        row = _application(session, company_id, application_id)
        if row.stage_code != "OFFER":
            raise ValueError("استخدام فقط پس از پیشنهاد همکاری است.")
        opening = session.get(JobOpening, row.opening_id)
        if opening.status_code != "OPEN":
            raise ValueError("فرصت شغلی این درخواست باز نیست.")
        hired = session.scalar(select(func.count()).where(JobApplication.opening_id == opening.opening_id,
                                                          JobApplication.stage_code == "HIRED")) or 0
        if hired >= opening.headcount:
            raise ValueError("ظرفیت این فرصت شغلی تکمیل شده است.")
        c = session.get(Candidate, row.candidate_id)
        position = session.get(Position, opening.position_id)
        data = (c.first_name, c.last_name, c.national_id, c.mobile, position.org_unit_id, opening.position_id, row.offer_salary,
                row.offer_start_date)
    first, last, national, mobile, org_unit_id, position_id, salary, start = data
    employee_id = hr.create_employee(company_id, employee_code, first, last, national, start, org_unit_id, position_id, salary, None,
                                     mobile=mobile)
    with new_session() as session:
        row = _application(session, company_id, application_id)
        _event(session, row.application_id, row.stage_code, "HIRED", user_id)
        row.stage_code, row.employee_id, row.hired_on = "HIRED", employee_id, start
        session.flush()
        opening = session.get(JobOpening, row.opening_id)
        hired = session.scalar(select(func.count()).where(JobApplication.opening_id == opening.opening_id,
                                                          JobApplication.stage_code == "HIRED")) or 0
        if hired >= opening.headcount:
            opening.status_code = "FILLED"
        session.commit()
    return employee_id


def list_applications(company_id: int, opening_id: int | None = None, candidate_id: int | None = None,
                      open_only: bool = False) -> list[ApplicationRow]:
    with new_session() as session:
        q = (select(JobApplication, JobOpening, Candidate)
             .join(JobOpening, JobOpening.opening_id == JobApplication.opening_id)
             .join(Candidate, Candidate.candidate_id == JobApplication.candidate_id)
             .where(JobApplication.company_id == company_id))
        if opening_id is not None:
            q = q.where(JobApplication.opening_id == opening_id)
        if candidate_id is not None:
            q = q.where(JobApplication.candidate_id == candidate_id)
        if open_only:
            q = q.where(JobApplication.stage_code.not_in(CLOSED_STAGES))
        rows = session.execute(q.order_by(JobApplication.application_id.desc())).all()
        ids = [a.application_id for a, _o, _c in rows] or [0]
        scores = {aid: (avg, n) for aid, avg, n in session.execute(
            select(Interview.application_id, func.avg(Interview.score), func.count()).where(
                Interview.application_id.in_(ids), Interview.status_code == "DONE").group_by(Interview.application_id))}
        counts = dict(session.execute(select(Interview.application_id, func.count()).where(
            Interview.application_id.in_(ids), Interview.status_code != "CANCELLED").group_by(Interview.application_id)).all())
    out = []
    for a, o, c in rows:
        avg = scores.get(a.application_id, (None, 0))[0]
        out.append(ApplicationRow(a.application_id, a.opening_id, f"{o.code} — {o.title}", a.candidate_id, _name(c.first_name, c.last_name),
                                  c.source_code, a.stage_code, a.applied_on, a.offer_salary, a.offer_start_date, a.decision_note or "",
                                  a.employee_id, a.hired_on, decimal.Decimal(avg).quantize(decimal.Decimal("0.1")) if avg is not None else None,
                                  counts.get(a.application_id, 0)))
    return out


def history(company_id: int, application_id: int) -> list[tuple[datetime.datetime, str, str, str]]:
    """(زمان، از، به، یادداشت)"""
    with new_session() as session:
        _application(session, company_id, application_id)
        return [(e.at, STAGES.get(e.from_stage, "") if e.from_stage else "", STAGES[e.to_stage], e.note or "") for e in session.scalars(
            select(ApplicationEvent).where(ApplicationEvent.application_id == application_id).order_by(ApplicationEvent.event_id))]


# --- مصاحبه ------------------------------------------------------------------------------------------------------------
@dataclass
class InterviewRow:
    interview_id: int
    application_id: int
    candidate_name: str
    opening_label: str
    scheduled_at: datetime.datetime
    interviewer_employee_id: int | None
    interviewer: str
    mode_code: str
    status_code: str
    score: int | None
    recommendation_code: str | None
    notes: str

    @property
    def status_label(self) -> str:
        return INTERVIEW_STATUSES[self.status_code]


def schedule_interview(company_id: int, user_id: int | None, application_id: int, scheduled_at: datetime.datetime,
                       interviewer_employee_id: int | None, mode_code: str = "IN_PERSON") -> int:
    if mode_code not in MODES:
        raise ValueError("نوع مصاحبه نامعتبر است.")
    with new_session() as session:
        row = _application(session, company_id, application_id)
        if row.stage_code in CLOSED_STAGES:
            raise ValueError("برای درخواست بسته‌شده مصاحبه گذاشته نمی‌شود.")
        if interviewer_employee_id is not None:
            e = session.get(Employee, interviewer_employee_id)
            if e is None or e.company_id != company_id:
                raise ValueError("مصاحبه‌گر نامعتبر است.")
        interview = Interview(application_id=application_id, scheduled_at=scheduled_at, interviewer_employee_id=interviewer_employee_id,
                              mode_code=mode_code)
        session.add(interview)
        if row.stage_code in ("APPLIED", "SCREENING"):
            _event(session, row.application_id, row.stage_code, "INTERVIEW", user_id)
            row.stage_code = "INTERVIEW"
        session.commit()
        return interview.interview_id


def record_interview(company_id: int, interview_id: int, score: int, recommendation_code: str, notes: str | None = None) -> None:
    if not 1 <= int(score) <= 5:
        raise ValueError("امتیاز مصاحبه از ۱ تا ۵ است.")
    if recommendation_code not in RECOMMENDATIONS:
        raise ValueError("پیشنهاد مصاحبه‌گر را انتخاب کنید.")
    with new_session() as session:
        interview = session.get(Interview, interview_id)
        if interview is None:
            raise ValueError("مصاحبه نامعتبر است.")
        _application(session, company_id, interview.application_id)
        if interview.status_code == "CANCELLED":
            raise ValueError("مصاحبهٔ لغوشده نتیجه نمی‌گیرد.")
        interview.status_code, interview.score, interview.recommendation_code = "DONE", int(score), recommendation_code
        interview.notes = (notes or "").strip() or None
        session.commit()


def cancel_interview(company_id: int, interview_id: int) -> None:
    with new_session() as session:
        interview = session.get(Interview, interview_id)
        if interview is None:
            raise ValueError("مصاحبه نامعتبر است.")
        _application(session, company_id, interview.application_id)
        if interview.status_code != "SCHEDULED":
            raise ValueError("فقط مصاحبهٔ برنامه‌ریزی‌شده لغو می‌شود.")
        interview.status_code = "CANCELLED"
        session.commit()


def list_interviews(company_id: int, application_id: int | None = None, interviewer_employee_id: int | None = None,
                    pending_only: bool = False) -> list[InterviewRow]:
    with new_session() as session:
        q = (select(Interview, JobApplication, Candidate, JobOpening)
             .join(JobApplication, JobApplication.application_id == Interview.application_id)
             .join(Candidate, Candidate.candidate_id == JobApplication.candidate_id)
             .join(JobOpening, JobOpening.opening_id == JobApplication.opening_id)
             .where(JobApplication.company_id == company_id))
        if application_id is not None:
            q = q.where(Interview.application_id == application_id)
        if interviewer_employee_id is not None:
            q = q.where(Interview.interviewer_employee_id == interviewer_employee_id)
        if pending_only:
            q = q.where(Interview.status_code == "SCHEDULED", JobApplication.stage_code.not_in(CLOSED_STAGES))
        rows = session.execute(q.order_by(Interview.scheduled_at)).all()
        names = {e.employee_id: _name(e.first_name, e.last_name) for e in session.scalars(select(Employee).where(
            Employee.employee_id.in_({i.interviewer_employee_id for i, *_ in rows if i.interviewer_employee_id} or {0})))}
    return [InterviewRow(i.interview_id, i.application_id, _name(c.first_name, c.last_name), f"{o.code} — {o.title}", i.scheduled_at,
                         i.interviewer_employee_id, names.get(i.interviewer_employee_id, ""), i.mode_code, i.status_code, i.score,
                         i.recommendation_code, i.notes or "") for i, _a, c, o in rows]


# --- گزارش --------------------------------------------------------------------------------------------------------------
def pipeline_report(company_id: int) -> list[dict]:
    """برای هر فرصت: تعداد درخواست در هر مرحله، استخدام‌شده از ظرفیت و میانگین روز تا استخدام."""
    apps = list_applications(company_id)
    by_opening: dict[int, list[ApplicationRow]] = defaultdict(list)
    for a in apps:
        by_opening[a.opening_id].append(a)
    out = []
    for o in list_openings(company_id):
        rows = by_opening.get(o.opening_id, [])
        counts = Counter(a.stage_code for a in rows)
        days = [(a.hired_on - a.applied_on).days for a in rows if a.stage_code == "HIRED" and a.hired_on]
        out.append({"opening": o, "counts": {s: counts.get(s, 0) for s in STAGES},
                    "days_to_hire": round(sum(days) / len(days), 1) if days else None})
    return out


def source_report(company_id: int) -> list[tuple[str, int, int]]:
    """(منبع، تعداد درخواست، تعداد استخدام) برای سنجش اثربخشی منابع جذب."""
    apps = list_applications(company_id)
    total, hired = Counter(a.source_code for a in apps), Counter(a.source_code for a in apps if a.stage_code == "HIRED")
    return [(SOURCES[s], total[s], hired[s]) for s in SOURCES if total[s]]
