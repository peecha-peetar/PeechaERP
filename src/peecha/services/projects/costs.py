"""R364: هزینه و درآمد واقعی پروژه.

- از دفاتر: ردیف‌های اسناد حسابداری غیر پیش‌نویس که تفصیلی همین پروژه را دارند؛ حساب‌های گروه «هزینه» و «بهای تمام‌شده»
  (بدهکار − بستانکار) هزینه، و حساب‌های «درآمد» (بستانکار − بدهکار) درآمد پروژه‌اند. خرید کالا به انبار پروژه تا مصرف
  نشده دارایی است و هزینه حساب نمی‌شود.
- کارکرد: ساعت تاییدشده × نرخ ثابت‌شده هنگام تایید؛ محاسباتی است و در دفاتر نیست (اگر حقوق را با تفصیلی پروژه در دفاتر
  ثبت می‌کنید، هزینهٔ کارکرد را جدا نخوانید تا دو بار شمرده نشود).
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import (
    AccountCategory, ChartOfAccount, JournalEntry, JournalEntryLine, JournalEntryLineDetail, JournalEntryStatus,
)
from peecha.db.models.projects import Project, TimesheetEntry
from peecha.services.projects import schedule as sch

ZERO = decimal.Decimal(0)
_COST_CATEGORIES = ("EXPENSE", "COGS")


@dataclass
class AccountAmount:
    full_code: str
    name: str
    amount: decimal.Decimal


@dataclass
class TaskLabor:
    task_id: int | None
    wbs: str
    name: str
    planned_hours: decimal.Decimal
    planned_cost: decimal.Decimal
    hours: decimal.Decimal = ZERO
    cost: decimal.Decimal = ZERO


@dataclass
class ProjectCost:
    project_id: int
    contract_amount: decimal.Decimal
    planned_cost: decimal.Decimal
    baseline_cost: decimal.Decimal | None
    gl_cost: decimal.Decimal = ZERO
    revenue: decimal.Decimal = ZERO
    cost_accounts: list[AccountAmount] = field(default_factory=list)
    revenue_accounts: list[AccountAmount] = field(default_factory=list)
    labor_hours: decimal.Decimal = ZERO
    labor_cost: decimal.Decimal = ZERO
    unpriced_hours: decimal.Decimal = ZERO
    pending_hours: decimal.Decimal = ZERO
    tasks: list[TaskLabor] = field(default_factory=list)

    @property
    def total_cost(self) -> decimal.Decimal:
        return self.gl_cost + self.labor_cost

    @property
    def margin(self) -> decimal.Decimal:
        return self.revenue - self.total_cost

    @property
    def budget_left(self) -> decimal.Decimal:
        return (self.baseline_cost if self.baseline_cost is not None else self.planned_cost) - self.total_cost


def ledger_amounts(session, company_id: int, project_detail_ids: list[int], date_from: datetime.date | None = None,
                   date_to: datetime.date | None = None) -> dict[int, tuple[dict, dict]]:
    """{تفصیلی پروژه: ({حساب: هزینه}, {حساب: درآمد})} از اسناد غیر پیش‌نویس."""
    from peecha.services import detail_dimensions as dims

    type_id = dims.ensure_specialized_dimensions(session, company_id)[dims.PROJECT_CODE]
    q = (select(JournalEntryLineDetail.detail_account_id, JournalEntryLine.account_id, AccountCategory.code,
                func.sum(JournalEntryLine.debit_amount_base), func.sum(JournalEntryLine.credit_amount_base))
         .join(JournalEntryLine, JournalEntryLine.line_id == JournalEntryLineDetail.line_id)
         .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
         .join(JournalEntryStatus, JournalEntryStatus.status_id == JournalEntry.status_id)
         .join(ChartOfAccount, ChartOfAccount.account_id == JournalEntryLine.account_id)
         .join(AccountCategory, AccountCategory.category_id == ChartOfAccount.category_id)
         .where(JournalEntry.company_id == company_id, JournalEntryStatus.code != "DRAFT",
                JournalEntryLineDetail.dimension_type_id == type_id,
                JournalEntryLineDetail.detail_account_id.in_(project_detail_ids or [0]),
                AccountCategory.code.in_(_COST_CATEGORIES + ("REVENUE",))))
    if date_from:
        q = q.where(JournalEntry.document_date >= date_from)
    if date_to:
        q = q.where(JournalEntry.document_date <= date_to)
    out: dict[int, tuple[dict, dict]] = defaultdict(lambda: ({}, {}))
    for detail_id, account_id, category, debit, credit in session.execute(
            q.group_by(JournalEntryLineDetail.detail_account_id, JournalEntryLine.account_id, AccountCategory.code)):
        cost, revenue = out[detail_id]
        if category == "REVENUE":
            revenue[account_id] = (credit or ZERO) - (debit or ZERO)
        else:
            cost[account_id] = (debit or ZERO) - (credit or ZERO)
    return out


def project_cost(company_id: int, project_id: int, date_from: datetime.date | None = None,
                 date_to: datetime.date | None = None) -> ProjectCost:
    plan = sch.compute(company_id, project_id)
    leaves = [t for t in plan.tasks if not t.is_summary]
    baselines = [t.baseline_cost for t in leaves if t.baseline_cost is not None]
    with new_session() as session:
        project = session.get(Project, project_id)
        result = ProjectCost(project_id, project.contract_amount, plan.planned_cost, sum(baselines, ZERO) if baselines else None)
        cost, revenue = ledger_amounts(session, company_id, [project.project_detail_account_id], date_from, date_to).get(
            project.project_detail_account_id, ({}, {}))
        q = select(TimesheetEntry).where(TimesheetEntry.project_id == project_id, TimesheetEntry.status_code.in_(("APPROVED", "SUBMITTED")))
        if date_from:
            q = q.where(TimesheetEntry.work_date >= date_from)
        if date_to:
            q = q.where(TimesheetEntry.work_date <= date_to)
        entries = list(session.scalars(q))
    from peecha.services import chart_of_accounts as coa

    accounts = {a.account_id: a for a in coa.list_accounts(company_id)} if cost or revenue else {}
    result.cost_accounts = sorted((AccountAmount(accounts[a].full_code, accounts[a].name, v) for a, v in cost.items() if v),
                                  key=lambda r: r.full_code)
    result.revenue_accounts = sorted((AccountAmount(accounts[a].full_code, accounts[a].name, v) for a, v in revenue.items() if v),
                                     key=lambda r: r.full_code)
    result.gl_cost = sum((r.amount for r in result.cost_accounts), ZERO)
    result.revenue = sum((r.amount for r in result.revenue_accounts), ZERO)
    by_task = {t.task_id: TaskLabor(t.task_id, t.wbs, t.name, t.planned_hours, t.planned_cost) for t in leaves}
    for e in entries:
        if e.status_code == "SUBMITTED":
            result.pending_hours += e.hours
            continue
        row = by_task.get(e.task_id)
        if row is None:
            row = by_task.setdefault(None, TaskLabor(None, "", "بدون فعالیت", ZERO, ZERO))
        row.hours += e.hours
        result.labor_hours += e.hours
        if e.hourly_cost is None:
            result.unpriced_hours += e.hours
        else:
            amount = (e.hours * e.hourly_cost).quantize(decimal.Decimal("0.01"))
            row.cost += amount
            result.labor_cost += amount
    result.tasks = [by_task[t.task_id] for t in leaves] + ([by_task[None]] if None in by_task else [])
    return result
