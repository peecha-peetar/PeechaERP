"""R368: ارزیابی عملکرد.

- قالب: معیارها با وزن؛ جمع وزن‌ها باید ۱۰۰ باشد تا قالب در دوره استفاده شود. قالبی که در دوره آمده دیگر تغییر معیار نمی‌پذیرد.
- دوره: پیش‌نویس ← باز ← بسته. با بازکردن، برای همهٔ کارکنان فعال (یا یک واحد) ارزیابی ساخته می‌شود؛ ارزیاب مدیر واحد
  سازمانی قرارداد فعال کارمند است (اگر خودش مدیر واحد است، مدیر واحد بالاتر).
- گردش هر ارزیابی: خودارزیابی (اگر دوره خواسته باشد) ← ارزیابی مدیر ← نهایی (منابع انسانی). امتیاز هر معیار ۱ تا ۵؛
  امتیاز کل = میانگین وزنی امتیاز مدیر. ارزیابی نهایی‌شده و دورهٔ بسته تغییر نمی‌کند.
- ارزیاب فقط ارزیابی‌هایی را که خودش ارزیابشان است ثبت می‌کند (مدیر سیستم و دارندهٔ مجوز ویرایش فرم ارزیابی هم می‌توانند).
"""

from __future__ import annotations

import datetime
import decimal
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.hr import Employee, EmploymentContract, OrganizationalUnit
from peecha.db.models.hr_talent import Appraisal, AppraisalCriterion, AppraisalCycle, AppraisalScore, AppraisalTemplate

ZERO = decimal.Decimal(0)
HUNDRED = decimal.Decimal(100)
FORM_CODE = "hr_appraisals"
CYCLE_STATUSES = {"DRAFT": "پیش‌نویس", "OPEN": "باز", "CLOSED": "بسته"}
STATUSES = {"PENDING_SELF": "منتظر خودارزیابی", "PENDING_MANAGER": "منتظر ارزیابی مدیر", "REVIEWED": "ارزیابی‌شده",
            "FINALIZED": "نهایی"}
BANDS = (("EXCELLENT", "عالی", decimal.Decimal("4.5")), ("GOOD", "خوب", decimal.Decimal("3.5")),
         ("ACCEPTABLE", "قابل قبول", decimal.Decimal("2.5")), ("NEEDS_IMPROVEMENT", "نیازمند بهبود", decimal.Decimal("1.5")),
         ("POOR", "ضعیف", ZERO))
BAND_LABELS = {code: label for code, label, _min in BANDS}


def band(score: decimal.Decimal | None) -> str | None:
    if score is None:
        return None
    return next(code for code, _label, low in BANDS if score >= low)


def _name(e: Employee | None) -> str:
    return f"{e.first_name} {e.last_name}".strip() if e else ""


# --- قالب ----------------------------------------------------------------------------------------------------------------
@dataclass
class CriterionFields:
    title: str
    weight: decimal.Decimal
    description: str | None = None


@dataclass
class TemplateRow:
    template_id: int
    code: str
    name: str
    is_active: bool
    criteria: list[AppraisalCriterion]
    in_use: bool

    @property
    def total_weight(self) -> decimal.Decimal:
        return sum((c.weight for c in self.criteria), ZERO)


def _template_in_use(session, template_id: int) -> bool:
    return bool(session.scalar(select(AppraisalCycle.cycle_id).where(AppraisalCycle.template_id == template_id,
                                                                     AppraisalCycle.status_code != "DRAFT").limit(1)))


def save_template(company_id: int, code: str, name: str, criteria: list[CriterionFields], template_id: int | None = None,
                  is_active: bool = True) -> int:
    code, name = (code or "").strip().upper(), (name or "").strip()
    if not code or not name:
        raise ValueError("کد و نام قالب ارزیابی الزامی است.")
    if not criteria:
        raise ValueError("دست‌کم یک معیار لازم است.")
    for c in criteria:
        if not (c.title or "").strip() or decimal.Decimal(c.weight or 0) <= 0:
            raise ValueError("هر معیار عنوان و وزن مثبت می‌خواهد.")
    if sum((decimal.Decimal(c.weight) for c in criteria), ZERO) != HUNDRED:
        raise ValueError("جمع وزن معیارها باید ۱۰۰ باشد.")
    with new_session() as session:
        if session.scalar(select(AppraisalTemplate.template_id).where(AppraisalTemplate.company_id == company_id,
                                                                      AppraisalTemplate.code == code,
                                                                      AppraisalTemplate.template_id != (template_id or 0))):
            raise ValueError(f"کد قالب «{code}» تکراری است.")
        same = False
        if template_id is None:
            row = AppraisalTemplate(company_id=company_id, code=code, name=name)
            session.add(row)
            session.flush()
        else:
            row = session.get(AppraisalTemplate, template_id)
            if row is None or row.company_id != company_id:
                raise ValueError("قالب ارزیابی نامعتبر است.")
            existing = list(session.scalars(select(AppraisalCriterion).where(AppraisalCriterion.template_id == template_id)
                                            .order_by(AppraisalCriterion.sort_order)))
            same = [(c.title, c.weight) for c in existing] == [(c.title.strip(), decimal.Decimal(c.weight)) for c in criteria]
            if _template_in_use(session, template_id) and not same:
                raise ValueError("معیارهای قالبی که در دورهٔ ارزیابی به کار رفته تغییر نمی‌کند؛ قالب جدید بسازید.")
            if not same:
                for c in existing:
                    session.delete(c)
                session.flush()
        row.code, row.name, row.is_active = code, name, is_active
        if not same:
            for n, c in enumerate(criteria, start=1):
                session.add(AppraisalCriterion(template_id=row.template_id, title=c.title.strip(), weight=decimal.Decimal(c.weight),
                                               description=(c.description or "").strip() or None, sort_order=n))
        session.commit()
        return row.template_id


def list_templates(company_id: int) -> list[TemplateRow]:
    with new_session() as session:
        rows = list(session.scalars(select(AppraisalTemplate).where(AppraisalTemplate.company_id == company_id)
                                    .order_by(AppraisalTemplate.code)))
        criteria = defaultdict(list)
        for c in session.scalars(select(AppraisalCriterion).where(AppraisalCriterion.template_id.in_([r.template_id for r in rows] or [0]))
                                 .order_by(AppraisalCriterion.sort_order)):
            criteria[c.template_id].append(c)
        used = {r.template_id: _template_in_use(session, r.template_id) for r in rows}
        session.expunge_all()
    return [TemplateRow(r.template_id, r.code, r.name, r.is_active, criteria[r.template_id], used[r.template_id]) for r in rows]


# --- دوره ----------------------------------------------------------------------------------------------------------------
@dataclass
class CycleRow:
    cycle_id: int
    title: str
    template_id: int
    template_name: str
    period_from: datetime.date
    period_to: datetime.date
    self_assessment: bool
    status_code: str
    total: int
    finalized: int

    @property
    def status_label(self) -> str:
        return CYCLE_STATUSES[self.status_code]


def save_cycle(company_id: int, title: str, template_id: int, period_from: datetime.date, period_to: datetime.date,
               self_assessment: bool = True, cycle_id: int | None = None) -> int:
    title = (title or "").strip()
    if not title:
        raise ValueError("عنوان دورهٔ ارزیابی را وارد کنید.")
    if period_from is None or period_to is None or period_to < period_from:
        raise ValueError("بازهٔ دورهٔ ارزیابی نامعتبر است.")
    with new_session() as session:
        template = session.get(AppraisalTemplate, template_id)
        if template is None or template.company_id != company_id or not template.is_active:
            raise ValueError("قالب ارزیابی فعال انتخاب کنید.")
        if cycle_id is None:
            row = AppraisalCycle(company_id=company_id)
            session.add(row)
        else:
            row = session.get(AppraisalCycle, cycle_id)
            if row is None or row.company_id != company_id:
                raise ValueError("دورهٔ ارزیابی نامعتبر است.")
            if row.status_code != "DRAFT":
                raise ValueError("فقط دورهٔ پیش‌نویس ویرایش می‌شود.")
        row.title, row.template_id, row.period_from, row.period_to = title, template_id, period_from, period_to
        row.self_assessment = bool(self_assessment)
        session.commit()
        return row.cycle_id


def _reviewer(session, employee_id: int) -> int | None:
    contract = session.scalar(select(EmploymentContract).where(EmploymentContract.employee_id == employee_id,
                                                               EmploymentContract.status == "ACTIVE")
                              .order_by(EmploymentContract.contract_id.desc()).limit(1))
    unit = session.get(OrganizationalUnit, contract.org_unit_id) if contract else None
    while unit is not None:
        if unit.manager_employee_id and unit.manager_employee_id != employee_id:
            return unit.manager_employee_id
        unit = session.get(OrganizationalUnit, unit.parent_org_unit_id) if unit.parent_org_unit_id else None
    return None


def open_cycle(company_id: int, cycle_id: int, org_unit_id: int | None = None) -> int:
    """ساخت ارزیابی برای کارکنان فعال (یا یک واحد)؛ برمی‌گرداند: تعداد ارزیابی ساخته‌شده."""
    with new_session() as session:
        cycle = session.get(AppraisalCycle, cycle_id)
        if cycle is None or cycle.company_id != company_id:
            raise ValueError("دورهٔ ارزیابی نامعتبر است.")
        if cycle.status_code == "CLOSED":
            raise ValueError("دورهٔ بسته دوباره باز نمی‌شود.")
        weights = list(session.scalars(select(AppraisalCriterion.weight).where(AppraisalCriterion.template_id == cycle.template_id)))
        if sum(weights, ZERO) != HUNDRED:
            raise ValueError("جمع وزن معیارهای قالب این دوره ۱۰۰ نیست.")
        q = select(Employee).where(Employee.company_id == company_id, Employee.status == "ACTIVE",
                                   Employee.hire_date <= cycle.period_to)
        if org_unit_id is not None:
            q = q.where(Employee.employee_id.in_(select(EmploymentContract.employee_id).where(
                EmploymentContract.org_unit_id == org_unit_id, EmploymentContract.status == "ACTIVE")))
        existing = set(session.scalars(select(Appraisal.employee_id).where(Appraisal.cycle_id == cycle_id)))
        criteria = list(session.scalars(select(AppraisalCriterion.criterion_id).where(AppraisalCriterion.template_id == cycle.template_id)))
        made = 0
        for e in session.scalars(q.order_by(Employee.employee_code)):
            if e.employee_id in existing:
                continue
            a = Appraisal(company_id=company_id, cycle_id=cycle_id, employee_id=e.employee_id, reviewer_employee_id=_reviewer(session, e.employee_id),
                          status_code="PENDING_SELF" if cycle.self_assessment else "PENDING_MANAGER")
            session.add(a)
            session.flush()
            for cid in criteria:
                session.add(AppraisalScore(appraisal_id=a.appraisal_id, criterion_id=cid))
            made += 1
        if not made and not existing:
            raise ValueError("کارمند فعالی برای این دوره پیدا نشد.")
        cycle.status_code = "OPEN"
        session.commit()
        return made


def close_cycle(company_id: int, cycle_id: int) -> int:
    """بستن دوره؛ برمی‌گرداند تعداد ارزیابی‌های نهایی‌نشده (که همان‌طور می‌مانند)."""
    with new_session() as session:
        cycle = session.get(AppraisalCycle, cycle_id)
        if cycle is None or cycle.company_id != company_id:
            raise ValueError("دورهٔ ارزیابی نامعتبر است.")
        if cycle.status_code != "OPEN":
            raise ValueError("فقط دورهٔ باز بسته می‌شود.")
        left = session.scalar(select(func.count()).where(Appraisal.cycle_id == cycle_id, Appraisal.status_code != "FINALIZED")) or 0
        cycle.status_code = "CLOSED"
        session.commit()
        return left


def list_cycles(company_id: int) -> list[CycleRow]:
    with new_session() as session:
        rows = session.execute(select(AppraisalCycle, AppraisalTemplate.name).join(
            AppraisalTemplate, AppraisalTemplate.template_id == AppraisalCycle.template_id).where(AppraisalCycle.company_id == company_id)
            .order_by(AppraisalCycle.period_to.desc(), AppraisalCycle.cycle_id.desc())).all()
        ids = [c.cycle_id for c, _n in rows] or [0]
        total = dict(session.execute(select(Appraisal.cycle_id, func.count()).where(Appraisal.cycle_id.in_(ids)).group_by(Appraisal.cycle_id)).all())
        done = dict(session.execute(select(Appraisal.cycle_id, func.count()).where(Appraisal.cycle_id.in_(ids),
                                                                                    Appraisal.status_code == "FINALIZED")
                                    .group_by(Appraisal.cycle_id)).all())
    return [CycleRow(c.cycle_id, c.title, c.template_id, n, c.period_from, c.period_to, c.self_assessment, c.status_code,
                     total.get(c.cycle_id, 0), done.get(c.cycle_id, 0)) for c, n in rows]


# --- ارزیابی ------------------------------------------------------------------------------------------------------------
@dataclass
class ScoreRow:
    criterion_id: int
    title: str
    weight: decimal.Decimal
    self_score: int | None
    manager_score: int | None
    comment: str


@dataclass
class AppraisalRow:
    appraisal_id: int
    cycle_id: int
    cycle_title: str
    employee_id: int
    employee_code: str
    employee_name: str
    org_unit: str
    reviewer_employee_id: int | None
    reviewer_name: str
    status_code: str
    overall_score: decimal.Decimal | None
    self_comment: str
    manager_comment: str
    strengths: str
    improvements: str
    goals: str
    scores: list[ScoreRow] = field(default_factory=list)

    @property
    def status_label(self) -> str:
        return STATUSES[self.status_code]

    @property
    def band_label(self) -> str:
        code = band(self.overall_score)
        return BAND_LABELS[code] if code else "—"


def _org_units(session, employee_ids) -> dict[int, str]:
    rows = session.execute(select(EmploymentContract.employee_id, OrganizationalUnit.name).join(
        OrganizationalUnit, OrganizationalUnit.org_unit_id == EmploymentContract.org_unit_id).where(
        EmploymentContract.employee_id.in_(employee_ids or [0]), EmploymentContract.status == "ACTIVE")).all()
    return dict(rows)


def list_appraisals(company_id: int, cycle_id: int | None = None, reviewer_employee_id: int | None = None,
                    employee_id: int | None = None, with_scores: bool = False) -> list[AppraisalRow]:
    with new_session() as session:
        q = select(Appraisal, AppraisalCycle.title).join(AppraisalCycle, AppraisalCycle.cycle_id == Appraisal.cycle_id).where(
            Appraisal.company_id == company_id)
        if cycle_id is not None:
            q = q.where(Appraisal.cycle_id == cycle_id)
        if reviewer_employee_id is not None:
            q = q.where(Appraisal.reviewer_employee_id == reviewer_employee_id)
        if employee_id is not None:
            q = q.where(Appraisal.employee_id == employee_id)
        rows = session.execute(q.order_by(Appraisal.cycle_id.desc(), Appraisal.appraisal_id)).all()
        people = {e.employee_id: e for e in session.scalars(select(Employee).where(Employee.employee_id.in_(
            {a.employee_id for a, _t in rows} | {a.reviewer_employee_id for a, _t in rows if a.reviewer_employee_id} or {0})))}
        units = _org_units(session, [a.employee_id for a, _t in rows])
        scores = defaultdict(list)
        if with_scores and rows:
            for s, c in session.execute(select(AppraisalScore, AppraisalCriterion).join(
                    AppraisalCriterion, AppraisalCriterion.criterion_id == AppraisalScore.criterion_id).where(
                    AppraisalScore.appraisal_id.in_([a.appraisal_id for a, _t in rows])).order_by(AppraisalCriterion.sort_order)):
                scores[s.appraisal_id].append(ScoreRow(c.criterion_id, c.title, c.weight, s.self_score, s.manager_score, s.comment or ""))
    return [AppraisalRow(a.appraisal_id, a.cycle_id, title, a.employee_id, people[a.employee_id].employee_code, _name(people[a.employee_id]),
                         units.get(a.employee_id, ""), a.reviewer_employee_id, _name(people.get(a.reviewer_employee_id)), a.status_code,
                         a.overall_score, a.self_comment or "", a.manager_comment or "", a.strengths or "", a.improvements or "",
                         a.goals or "", scores.get(a.appraisal_id, [])) for a, title in rows]


def get_appraisal(company_id: int, appraisal_id: int) -> AppraisalRow:
    with new_session() as session:
        a = session.get(Appraisal, appraisal_id)
        if a is None or a.company_id != company_id:
            raise ValueError("ارزیابی نامعتبر است.")
        cycle_id, employee_id = a.cycle_id, a.employee_id
    return next(r for r in list_appraisals(company_id, cycle_id, employee_id=employee_id, with_scores=True))


def _editable(session, company_id: int, appraisal_id: int) -> tuple[Appraisal, AppraisalCycle]:
    a = session.get(Appraisal, appraisal_id)
    if a is None or a.company_id != company_id:
        raise ValueError("ارزیابی نامعتبر است.")
    cycle = session.get(AppraisalCycle, a.cycle_id)
    if cycle.status_code != "OPEN":
        raise ValueError("دورهٔ این ارزیابی باز نیست.")
    return a, cycle


def _scores(scores: dict[int, int]) -> dict[int, int]:
    out = {}
    for cid, value in scores.items():
        if value is None or not 1 <= int(value) <= 5:
            raise ValueError("امتیاز هر معیار از ۱ تا ۵ است.")
        out[int(cid)] = int(value)
    return out


def submit_self(company_id: int, user_id: int, appraisal_id: int, scores: dict[int, int], comment: str | None = None) -> None:
    from peecha.services import hr_leave

    scores = _scores(scores)
    with new_session() as session:
        a, _cycle = _editable(session, company_id, appraisal_id)
        if hr_leave.employee_of_user(company_id, user_id) != a.employee_id:
            raise ValueError("خودارزیابی را فقط خود کارمند ثبت می‌کند.")
        if a.status_code != "PENDING_SELF":
            raise ValueError("خودارزیابی این دوره ثبت شده است.")
        rows = {s.criterion_id: s for s in session.scalars(select(AppraisalScore).where(AppraisalScore.appraisal_id == appraisal_id))}
        if set(scores) != set(rows):
            raise ValueError("به همهٔ معیارها امتیاز بدهید.")
        for cid, value in scores.items():
            rows[cid].self_score = value
        a.self_comment, a.status_code = (comment or "").strip() or None, "PENDING_MANAGER"
        session.commit()


def can_review(company_id: int, user_id: int, appraisal: AppraisalRow | Appraisal) -> bool:
    from peecha.services import hr_leave, roles

    if roles.is_manager(user_id, company_id) or roles.user_has_permission(user_id, company_id, FORM_CODE, "EDIT"):
        return True
    return appraisal.reviewer_employee_id is not None and hr_leave.employee_of_user(company_id, user_id) == appraisal.reviewer_employee_id


def submit_review(company_id: int, user_id: int, appraisal_id: int, scores: dict[int, int], *, comment: str | None = None,
                  strengths: str | None = None, improvements: str | None = None, goals: str | None = None) -> decimal.Decimal:
    from peecha.services import hr_leave

    scores = _scores(scores)
    with new_session() as session:
        a, _cycle = _editable(session, company_id, appraisal_id)
        if not can_review(company_id, user_id, a):
            raise ValueError("ارزیابی این کارمند با ارزیاب او (مدیر واحد) یا کارشناس منابع انسانی است.")
        if hr_leave.employee_of_user(company_id, user_id) == a.employee_id:
            raise ValueError("ارزیابی مدیر برای خودتان را نمی‌توانید ثبت کنید.")
        if a.status_code == "PENDING_SELF":
            raise ValueError("کارمند هنوز خودارزیابی را ثبت نکرده است.")
        if a.status_code == "FINALIZED":
            raise ValueError("ارزیابی نهایی‌شده تغییر نمی‌کند.")
        rows = {s.criterion_id: s for s in session.scalars(select(AppraisalScore).where(AppraisalScore.appraisal_id == appraisal_id))}
        if set(scores) != set(rows):
            raise ValueError("به همهٔ معیارها امتیاز بدهید.")
        weights = {c.criterion_id: c.weight for c in session.scalars(select(AppraisalCriterion).where(AppraisalCriterion.criterion_id.in_(list(rows))))}
        for cid, value in scores.items():
            rows[cid].manager_score = value
        total = sum((weights[cid] * value for cid, value in scores.items()), ZERO) / sum(weights.values(), ZERO)
        a.overall_score = total.quantize(decimal.Decimal("0.01"))
        a.manager_comment, a.strengths = (comment or "").strip() or None, (strengths or "").strip() or None
        a.improvements, a.goals = (improvements or "").strip() or None, (goals or "").strip() or None
        a.status_code = "REVIEWED"
        session.commit()
        return a.overall_score


def finalize(company_id: int, user_id: int, appraisal_ids: list[int]) -> int:
    from peecha.services import roles

    if not (roles.is_manager(user_id, company_id) or roles.user_has_permission(user_id, company_id, FORM_CODE, "APPROVE")):
        raise ValueError("نهایی‌کردن ارزیابی با دارندهٔ مجوز تایید ارزیابی عملکرد است.")
    with new_session() as session:
        rows = [_editable(session, company_id, i)[0] for i in appraisal_ids]
        for a in rows:
            if a.status_code != "REVIEWED":
                raise ValueError("فقط ارزیابی‌ای که مدیر ثبت کرده نهایی می‌شود.")
            a.status_code, a.finalized_by_user_id = "FINALIZED", user_id
            a.finalized_at = datetime.datetime.now(datetime.timezone.utc)
        session.commit()
        return len(rows)


def reassign_reviewer(company_id: int, appraisal_id: int, reviewer_employee_id: int | None) -> None:
    with new_session() as session:
        a, _cycle = _editable(session, company_id, appraisal_id)
        if a.status_code == "FINALIZED":
            raise ValueError("ارزیابی نهایی‌شده تغییر نمی‌کند.")
        if reviewer_employee_id == a.employee_id:
            raise ValueError("کارمند ارزیاب خودش نمی‌شود.")
        a.reviewer_employee_id = reviewer_employee_id
        session.commit()


# --- گزارش --------------------------------------------------------------------------------------------------------------
def cycle_report(company_id: int, cycle_id: int) -> dict:
    rows = [r for r in list_appraisals(company_id, cycle_id) if r.overall_score is not None]
    bands = Counter(band(r.overall_score) for r in rows)
    units: dict[str, list[decimal.Decimal]] = defaultdict(list)
    for r in rows:
        units[r.org_unit or "—"].append(r.overall_score)
    avg = lambda xs: (sum(xs, ZERO) / len(xs)).quantize(decimal.Decimal("0.01")) if xs else None  # noqa: E731
    return {"average": avg([r.overall_score for r in rows]), "bands": [(BAND_LABELS[c], bands.get(c, 0)) for c, _l, _m in BANDS],
            "units": sorted(((u, len(xs), avg(xs)) for u, xs in units.items()), key=lambda t: -t[2])}


def history(company_id: int, employee_id: int) -> list[tuple[str, decimal.Decimal | None, str]]:
    """(دوره، امتیاز، رده) ارزیابی‌های نهایی یک کارمند، جدیدترین اول."""
    return [(r.cycle_title, r.overall_score, r.band_label) for r in list_appraisals(company_id, employee_id=employee_id)
            if r.status_code == "FINALIZED"]
