"""R363: تعریف پروژه، فاز و فعالیت، پیوند فعالیت‌ها، ثبت پیشرفت و خط مبنا.

- هر پروژه دقیقاً به یک تفصیلی آخرین سطح از نوع «پروژه» وصل است (همان که اسناد مالی، خرید، انبار و بودجه برچسب می‌زنند)؛
  تفصیلی جدید هم از همین فرم ساخته می‌شود.
- فعالیتی که زیرمجموعه دارد «فاز» است: مدت، تاریخ، هزینه و پیشرفتش از زیرمجموعه‌ها می‌آید و پیوند نمی‌گیرد.
- پیشرفت فقط روی فعالیت ثبت می‌شود؛ پیشرفت بیش از صفر شروع واقعی و ۱۰۰٪ پایان واقعی می‌خواهد (اگر خالی بماند امروز).
- خط مبنا تصویر تاریخ و هزینهٔ برنامه‌ریزی‌شدهٔ همهٔ فعالیت‌هاست تا پیشرفت برنامه‌ای و انحراف با آن سنجیده شود.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.hr import Employee
from peecha.db.models.projects import Project, ProjectTask, TaskLink
from peecha.services.projects import schedule as sch

ZERO = decimal.Decimal(0)
STATUSES = {"PLANNING": "برنامه‌ریزی", "ACTIVE": "در حال اجرا", "ON_HOLD": "متوقف", "COMPLETED": "پایان‌یافته", "CANCELLED": "لغوشده"}
LINK_TYPES = {"FS": "پایان به شروع", "SS": "شروع به شروع", "FF": "پایان به پایان"}
_MAX_DURATION = 3650


@dataclass
class ProjectFields:
    start_date: datetime.date
    project_detail_account_id: int | None = None
    code: str = ""
    name: str = ""
    customer_detail_account_id: int | None = None
    manager_employee_id: int | None = None
    target_end_date: datetime.date | None = None
    contract_amount: decimal.Decimal = ZERO
    description: str | None = None
    status_code: str = "PLANNING"


@dataclass
class ProjectRow:
    project_id: int
    project_detail_account_id: int
    code: str
    name: str
    customer_detail_account_id: int | None
    customer: str
    manager_employee_id: int | None
    manager: str
    status_code: str
    start_date: datetime.date
    target_end_date: datetime.date | None
    contract_amount: decimal.Decimal
    description: str
    baseline_set_at: datetime.datetime | None
    task_count: int

    @property
    def label(self) -> str:
        return f"{self.code} — {self.name}"

    @property
    def status_label(self) -> str:
        return STATUSES[self.status_code]


@dataclass
class TaskFields:
    name: str
    duration_days: int = 1
    parent_task_id: int | None = None
    start_no_earlier: datetime.date | None = None
    responsible_employee_id: int | None = None
    planned_hours: decimal.Decimal = ZERO
    planned_cost: decimal.Decimal = ZERO
    notes: str | None = None


@dataclass
class LinkRow:
    link_id: int
    predecessor_task_id: int
    successor_task_id: int
    link_type: str
    lag_days: int

    @property
    def type_label(self) -> str:
        return LINK_TYPES[self.link_type]


def _project_type_id(company_id: int) -> int:
    from peecha.services import detail_dimensions as dims

    return dims.get_specialized_dimension_type_id(company_id, dims.PROJECT_CODE)


def _project(session, company_id: int, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.company_id != company_id:
        raise ValueError("پروژه نامعتبر است.")
    return project


def _task(session, company_id: int, task_id: int) -> tuple[ProjectTask, Project]:
    task = session.get(ProjectTask, task_id)
    project = session.get(Project, task.project_id) if task else None
    if task is None or project is None or project.company_id != company_id:
        raise ValueError("فعالیت نامعتبر است.")
    return task, project


def _employee_ok(session, company_id: int, employee_id: int | None) -> None:
    if employee_id is not None:
        e = session.get(Employee, employee_id)
        if e is None or e.company_id != company_id:
            raise ValueError("کارمند انتخاب‌شده نامعتبر است.")


def _has_children(session, task_id: int) -> bool:
    return bool(session.scalar(select(ProjectTask.task_id).where(ProjectTask.parent_task_id == task_id).limit(1)))


def _has_links(session, task_id: int) -> bool:
    return bool(session.scalar(select(TaskLink.link_id).where(
        (TaskLink.predecessor_task_id == task_id) | (TaskLink.successor_task_id == task_id)).limit(1)))


# --- پروژه ------------------------------------------------------------------------------------------------------------
def save_project(company_id: int, user_id: int | None, f: ProjectFields, project_id: int | None = None) -> int:
    if f.status_code not in STATUSES:
        raise ValueError("وضعیت پروژه نامعتبر است.")
    if f.start_date is None:
        raise ValueError("تاریخ شروع پروژه را وارد کنید.")
    if f.target_end_date and f.target_end_date < f.start_date:
        raise ValueError("تاریخ پایان هدف نمی‌تواند پیش از شروع پروژه باشد.")
    if (f.contract_amount or ZERO) < 0:
        raise ValueError("مبلغ قرارداد نمی‌تواند منفی باشد.")
    type_id = _project_type_id(company_id)
    detail_id = f.project_detail_account_id
    if project_id is None and detail_id is None:
        from peecha.services import detail_dimensions as dims

        if not (f.code or "").strip() or not (f.name or "").strip():
            raise ValueError("برای پروژهٔ جدید کد و نام را وارد کنید یا تفصیلی پروژهٔ موجود را انتخاب کنید.")
        detail_id = dims.create_detail_account(company_id, type_id, f.code.strip(), f.name.strip()).detail_account_id
    with new_session() as session:
        if f.customer_detail_account_id is not None:
            customer = session.get(DetailAccount, f.customer_detail_account_id)
            if customer is None or customer.company_id != company_id:
                raise ValueError("کارفرما نامعتبر است.")
        _employee_ok(session, company_id, f.manager_employee_id)
        if project_id is None:
            detail = session.get(DetailAccount, detail_id)
            if detail is None or detail.company_id != company_id or detail.dimension_type_id != type_id:
                raise ValueError("تفصیلی انتخاب‌شده از نوع «پروژه» نیست.")
            if session.scalar(select(DetailAccount.detail_account_id).where(DetailAccount.parent_detail_account_id == detail_id).limit(1)):
                raise ValueError("فقط تفصیلی آخرین سطح پروژه انتخاب می‌شود.")
            if session.scalar(select(Project.project_id).where(Project.project_detail_account_id == detail_id)):
                raise ValueError("برای این تفصیلی پروژه تعریف شده است.")
            row = Project(company_id=company_id, project_detail_account_id=detail_id, created_by_user_id=user_id)
            session.add(row)
        else:
            row = _project(session, company_id, project_id)
            detail = session.get(DetailAccount, row.project_detail_account_id)
            if (f.name or "").strip() and detail.name != f.name.strip():
                detail.name = f.name.strip()
        row.customer_detail_account_id = f.customer_detail_account_id
        row.manager_employee_id = f.manager_employee_id
        row.status_code = f.status_code
        row.start_date = f.start_date
        row.target_end_date = f.target_end_date
        row.contract_amount = f.contract_amount or ZERO
        row.description = (f.description or "").strip() or None
        session.commit()
        return row.project_id


def _rows(session, projects: list[Project]) -> list[ProjectRow]:
    ids = {p.project_detail_account_id for p in projects} | {p.customer_detail_account_id for p in projects if p.customer_detail_account_id}
    details = {d.detail_account_id: d for d in session.scalars(select(DetailAccount).where(DetailAccount.detail_account_id.in_(ids or {0})))}
    managers = {e.employee_id: f"{e.first_name} {e.last_name}".strip() for e in session.scalars(select(Employee).where(
        Employee.employee_id.in_({p.manager_employee_id for p in projects if p.manager_employee_id} or {0})))}
    counts = dict(session.execute(select(ProjectTask.project_id, func.count()).where(
        ProjectTask.project_id.in_([p.project_id for p in projects] or [0])).group_by(ProjectTask.project_id)).all())
    out = []
    for p in projects:
        d = details[p.project_detail_account_id]
        c = details.get(p.customer_detail_account_id)
        out.append(ProjectRow(p.project_id, p.project_detail_account_id, d.code, d.name or "", p.customer_detail_account_id,
                              (c.name or c.code) if c else "", p.manager_employee_id, managers.get(p.manager_employee_id, ""),
                              p.status_code, p.start_date, p.target_end_date, p.contract_amount, p.description or "",
                              p.baseline_set_at, counts.get(p.project_id, 0)))
    return out


def list_projects(company_id: int, statuses: tuple[str, ...] | None = None) -> list[ProjectRow]:
    with new_session() as session:
        q = select(Project).where(Project.company_id == company_id)
        if statuses:
            q = q.where(Project.status_code.in_(statuses))
        return _rows(session, list(session.scalars(q.order_by(Project.start_date.desc(), Project.project_id.desc()))))


def get_project(company_id: int, project_id: int) -> ProjectRow:
    with new_session() as session:
        return _rows(session, [_project(session, company_id, project_id)])[0]


def free_project_details(company_id: int) -> list[tuple[str, int]]:
    """تفصیلی‌های آخرین سطح پروژه که هنوز پروژه ندارند."""
    from peecha.services import detail_dimensions as dims

    with new_session() as session:
        used = set(session.scalars(select(Project.project_detail_account_id).where(Project.company_id == company_id)))
    return [(f"{d.code} — {d.name or ''}", d.detail_account_id)
            for d in dims.list_leaf_detail_accounts(company_id, _project_type_id(company_id)) if d.detail_account_id not in used]


def delete_project(company_id: int, project_id: int) -> None:
    """فقط پروژهٔ «برنامه‌ریزی» یا «لغوشده» حذف می‌شود؛ تفصیلی پروژه و اسناد برچسب‌خورده سر جایشان می‌مانند."""
    with new_session() as session:
        row = _project(session, company_id, project_id)
        if row.status_code not in ("PLANNING", "CANCELLED"):
            raise ValueError("فقط پروژهٔ در حال برنامه‌ریزی یا لغوشده حذف می‌شود؛ پروژهٔ در جریان را «لغوشده» یا «پایان‌یافته» کنید.")
        from peecha.services.projects import timesheets

        if timesheets.entries_exist(session, project_id=project_id):
            raise ValueError("برای این پروژه کارکرد ثبت شده است؛ به‌جای حذف، آن را «لغوشده» کنید.")
        session.delete(row)
        session.commit()


# --- فعالیت‌ها -----------------------------------------------------------------------------------------------------------
def _descendants(session, task_id: int) -> set[int]:
    out, frontier = set(), [task_id]
    while frontier:
        rows = list(session.scalars(select(ProjectTask.task_id).where(ProjectTask.parent_task_id.in_(frontier))))
        frontier = [r for r in rows if r not in out]
        out.update(frontier)
    return out


def save_task(company_id: int, project_id: int, f: TaskFields, task_id: int | None = None) -> int:
    name = (f.name or "").strip()
    if not name:
        raise ValueError("نام فعالیت را وارد کنید.")
    if not 0 <= int(f.duration_days) <= _MAX_DURATION:
        raise ValueError(f"مدت فعالیت باید بین ۰ و {_MAX_DURATION} روز کاری باشد.")
    if (f.planned_hours or ZERO) < 0 or (f.planned_cost or ZERO) < 0:
        raise ValueError("ساعت و هزینهٔ برنامه‌ای نمی‌تواند منفی باشد.")
    with new_session() as session:
        _project(session, company_id, project_id)
        _employee_ok(session, company_id, f.responsible_employee_id)
        if f.parent_task_id is not None:
            parent = session.get(ProjectTask, f.parent_task_id)
            if parent is None or parent.project_id != project_id:
                raise ValueError("فاز انتخاب‌شده در این پروژه نیست.")
            if task_id is not None and (f.parent_task_id == task_id or f.parent_task_id in _descendants(session, task_id)):
                raise ValueError("فعالیت نمی‌تواند زیرمجموعهٔ خودش یا زیرمجموعه‌هایش باشد.")
            if _has_links(session, f.parent_task_id):
                raise ValueError(f"«{parent.name}» پیوند دارد و نمی‌تواند فاز شود؛ ابتدا پیوندهایش را بردارید.")
        if task_id is None:
            row = ProjectTask(project_id=project_id, sort_order=(session.scalar(select(func.max(ProjectTask.sort_order)).where(
                ProjectTask.project_id == project_id, ProjectTask.parent_task_id.is_(None) if f.parent_task_id is None
                else ProjectTask.parent_task_id == f.parent_task_id)) or 0) + 1)
            session.add(row)
        else:
            row, project = _task(session, company_id, task_id)
            if project.project_id != project_id:
                raise ValueError("فعالیت در این پروژه نیست.")
            if row.parent_task_id != f.parent_task_id:
                row.sort_order = (session.scalar(select(func.max(ProjectTask.sort_order)).where(
                    ProjectTask.project_id == project_id, ProjectTask.parent_task_id.is_(None) if f.parent_task_id is None
                    else ProjectTask.parent_task_id == f.parent_task_id)) or 0) + 1
        row.parent_task_id = f.parent_task_id
        row.name = name
        row.duration_days = int(f.duration_days)
        row.start_no_earlier = f.start_no_earlier
        row.responsible_employee_id = f.responsible_employee_id
        row.planned_hours = f.planned_hours or ZERO
        row.planned_cost = f.planned_cost or ZERO
        row.notes = (f.notes or "").strip() or None
        session.commit()
        return row.task_id


def delete_task(company_id: int, task_id: int) -> None:
    with new_session() as session:
        task, _project_row = _task(session, company_id, task_id)
        ids = _descendants(session, task_id) | {task_id}
        if session.scalar(select(ProjectTask.task_id).where(ProjectTask.task_id.in_(ids), (ProjectTask.percent_complete > 0)
                                                            | ProjectTask.actual_start.is_not(None)).limit(1)):
            raise ValueError("فعالیتی که پیشرفت یا شروع واقعی دارد (یا زیرمجموعه‌اش) حذف نمی‌شود.")
        from peecha.services.projects import timesheets

        if timesheets.entries_exist(session, task_ids=ids):
            raise ValueError("برای این فعالیت (یا زیرمجموعه‌اش) کارکرد ثبت شده است و حذف نمی‌شود.")
        session.delete(task)
        session.commit()


def move_task(company_id: int, task_id: int, step: int) -> bool:
    """جابه‌جایی فعالیت میان هم‌سطح‌ها (step = −۱ بالا، +۱ پایین)."""
    with new_session() as session:
        task, project = _task(session, company_id, task_id)
        siblings = list(session.scalars(select(ProjectTask).where(
            ProjectTask.project_id == project.project_id,
            ProjectTask.parent_task_id.is_(None) if task.parent_task_id is None else ProjectTask.parent_task_id == task.parent_task_id)
            .order_by(ProjectTask.sort_order, ProjectTask.task_id)))
        i = next(n for n, t in enumerate(siblings) if t.task_id == task_id)
        j = i + (1 if step > 0 else -1)
        if not 0 <= j < len(siblings):
            return False
        siblings[i], siblings[j] = siblings[j], siblings[i]
        for n, t in enumerate(siblings, start=1):
            t.sort_order = n
        session.commit()
        return True


def update_progress(company_id: int, task_id: int, percent: decimal.Decimal, actual_start: datetime.date | None = None,
                    actual_finish: datetime.date | None = None, today: datetime.date | None = None) -> None:
    today = today or datetime.date.today()
    percent = decimal.Decimal(percent)
    if not ZERO <= percent <= 100:
        raise ValueError("درصد پیشرفت باید بین ۰ و ۱۰۰ باشد.")
    with new_session() as session:
        task, _project_row = _task(session, company_id, task_id)
        if _has_children(session, task_id):
            raise ValueError("پیشرفت فاز از فعالیت‌هایش محاسبه می‌شود؛ پیشرفت را روی فعالیت‌ها ثبت کنید.")
        if percent > 0 or actual_start:
            actual_start = actual_start or task.actual_start or today
        if percent >= 100:
            actual_finish = actual_finish or task.actual_finish or today
        else:
            actual_finish = None
        if (actual_start and actual_start > today) or (actual_finish and actual_finish > today):
            raise ValueError("تاریخ واقعی نمی‌تواند بعد از امروز باشد.")
        if actual_start and actual_finish and actual_finish < actual_start:
            raise ValueError("پایان واقعی نمی‌تواند پیش از شروع واقعی باشد.")
        task.percent_complete, task.actual_start, task.actual_finish = percent, actual_start, actual_finish
        session.commit()


# --- پیوندها ------------------------------------------------------------------------------------------------------------
def list_links(company_id: int, project_id: int) -> list[LinkRow]:
    with new_session() as session:
        _project(session, company_id, project_id)
        ids = select(ProjectTask.task_id).where(ProjectTask.project_id == project_id)
        return [LinkRow(ln.link_id, ln.predecessor_task_id, ln.successor_task_id, ln.link_type, ln.lag_days)
                for ln in session.scalars(select(TaskLink).where(TaskLink.successor_task_id.in_(ids)).order_by(TaskLink.link_id))]


def add_link(company_id: int, predecessor_task_id: int, successor_task_id: int, link_type: str = "FS", lag_days: int = 0) -> int:
    if link_type not in LINK_TYPES:
        raise ValueError("نوع پیوند نامعتبر است.")
    if predecessor_task_id == successor_task_id:
        raise ValueError("فعالیت نمی‌تواند پیش‌نیاز خودش باشد.")
    with new_session() as session:
        pred, project = _task(session, company_id, predecessor_task_id)
        succ, _p2 = _task(session, company_id, successor_task_id)
        if succ.project_id != pred.project_id:
            raise ValueError("دو فعالیت باید در یک پروژه باشند.")
        for t in (pred, succ):
            if _has_children(session, t.task_id):
                raise ValueError(f"«{t.name}» فاز است؛ پیوند فقط میان فعالیت‌ها برقرار می‌شود.")
        links = list(session.scalars(select(TaskLink).where(TaskLink.successor_task_id.in_(
            select(ProjectTask.task_id).where(ProjectTask.project_id == project.project_id)))))
        if any({ln.predecessor_task_id, ln.successor_task_id} == {predecessor_task_id, successor_task_id} for ln in links):
            raise ValueError("میان این دو فعالیت پیوند وجود دارد.")
        nxt = defaultdict(set)
        for ln in links:
            nxt[ln.predecessor_task_id].add(ln.successor_task_id)
        frontier, seen = [successor_task_id], set()
        while frontier:
            t = frontier.pop()
            if t == predecessor_task_id:
                raise ValueError("این پیوند حلقه می‌سازد (جانشین، خودش پیش‌نیاز این فعالیت است).")
            if t not in seen:
                seen.add(t)
                frontier.extend(nxt[t])
        row = TaskLink(predecessor_task_id=predecessor_task_id, successor_task_id=successor_task_id, link_type=link_type,
                       lag_days=int(lag_days))
        session.add(row)
        session.commit()
        return row.link_id


def remove_link(company_id: int, link_id: int) -> None:
    with new_session() as session:
        row = session.get(TaskLink, link_id)
        if row is None:
            raise ValueError("پیوند نامعتبر است.")
        _task(session, company_id, row.successor_task_id)
        session.delete(row)
        session.commit()


# --- خط مبنا ------------------------------------------------------------------------------------------------------------
def set_baseline(company_id: int, project_id: int) -> int:
    """تاریخ و هزینهٔ برنامه‌ریزی‌شدهٔ کنونی فعالیت‌ها خط مبنا می‌شود (خط مبنای قبلی جایگزین می‌شود)."""
    plan = sch.compute(company_id, project_id)
    if not plan.tasks:
        raise ValueError("پروژه فعالیتی ندارد.")
    rows = {r.task_id: r for r in plan.tasks if not r.is_summary}
    with new_session() as session:
        project = _project(session, company_id, project_id)
        for task in session.scalars(select(ProjectTask).where(ProjectTask.project_id == project_id)):
            r = rows.get(task.task_id)
            task.baseline_start, task.baseline_finish = (r.start, r.finish) if r else (None, None)
            task.baseline_cost = task.planned_cost if r else None
        project.baseline_set_at = datetime.datetime.now(datetime.timezone.utc)
        session.commit()
    return len(rows)
