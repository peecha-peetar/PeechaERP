"""R366: درخواست تغییر پروژه.

- پیش‌نویس ← ارسال‌شده ← تاییدشده یا ردشده (با دلیل)؛ ردشده پس از ویرایش دوباره پیش‌نویس می‌شود.
- تغییر مبلغ (افزایش یا کاهش قرارداد)، تغییر مدت (روز تقویمی، روی پایان هدف) و ردیف‌های جدید فهرست بها.
- با تایید، در یک تراکنش: مبلغ قرارداد و پایان هدف پروژه تغییر می‌کند و ردیف‌های جدید به فهرست بها اضافه می‌شوند (کد تکراری
  پذیرفته نمی‌شود). مبلغ قرارداد منفی نمی‌شود.
- تاییدکننده: مدیر سیستم یا دارندهٔ مجوز «تایید» فرم پروژه‌ها؛ درخواست‌دهنده درخواست خودش را تایید نمی‌کند (جز مدیر سیستم).
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.projects import ChangeOrder, ChangeOrderLine, ContractItem, Project

ZERO = decimal.Decimal(0)
STATUSES = {"DRAFT": "پیش‌نویس", "SUBMITTED": "ارسال‌شده", "APPROVED": "تاییدشده", "REJECTED": "ردشده"}
FORM_CODE = "projects"


@dataclass
class LineFields:
    code: str
    description: str
    unit: str
    quantity: decimal.Decimal
    unit_price: decimal.Decimal


@dataclass
class ChangeFields:
    title: str
    reason: str = ""
    amount_change: decimal.Decimal = ZERO
    days_change: int = 0
    lines: list[LineFields] = field(default_factory=list)


@dataclass
class ChangeRow:
    change_id: int
    project_id: int
    change_no: int
    title: str
    reason: str
    amount_change: decimal.Decimal
    days_change: int
    status_code: str
    decision_note: str
    requested_by_user_id: int | None
    created_at: datetime.datetime
    lines: list[LineFields] = field(default_factory=list)

    @property
    def status_label(self) -> str:
        return STATUSES[self.status_code]

    @property
    def lines_total(self) -> decimal.Decimal:
        return sum(((ln.quantity * ln.unit_price).quantize(decimal.Decimal("0.01")) for ln in self.lines), ZERO)


def _project(session, company_id: int, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.company_id != company_id:
        raise ValueError("پروژه نامعتبر است.")
    return project


def _change(session, company_id: int, change_id: int) -> ChangeOrder:
    row = session.get(ChangeOrder, change_id)
    if row is None or row.company_id != company_id:
        raise ValueError("درخواست تغییر نامعتبر است.")
    return row


def clean_lines(lines: list[LineFields]) -> list[LineFields]:
    out, codes = [], set()
    for ln in lines:
        code, description, unit = (ln.code or "").strip(), (ln.description or "").strip(), (ln.unit or "").strip()
        if not code or not description or not unit:
            raise ValueError("کد، شرح و واحد هر ردیف جدید فهرست بها الزامی است.")
        if code.upper() in codes:
            raise ValueError(f"کد «{code}» در همین درخواست تکراری است.")
        codes.add(code.upper())
        quantity, price = decimal.Decimal(ln.quantity or 0), decimal.Decimal(ln.unit_price or 0)
        if quantity <= 0 or price < 0:
            raise ValueError("مقدار ردیف جدید باید بیشتر از صفر و بهای واحد نامنفی باشد.")
        out.append(LineFields(code, description, unit, quantity, price))
    return out


def save_change(company_id: int, user_id: int | None, project_id: int, f: ChangeFields, change_id: int | None = None, *,
                submit: bool = False) -> int:
    title = (f.title or "").strip()
    if not title:
        raise ValueError("عنوان درخواست تغییر را بنویسید.")
    lines = clean_lines(f.lines)
    if not f.amount_change and not f.days_change and not lines:
        raise ValueError("درخواست تغییر باید مبلغ، مدت یا ردیف جدید فهرست بها را تغییر دهد.")
    with new_session() as session:
        project = _project(session, company_id, project_id)
        if project.status_code in ("COMPLETED", "CANCELLED"):
            raise ValueError("برای پروژهٔ پایان‌یافته یا لغوشده درخواست تغییر ثبت نمی‌شود.")
        if change_id is None:
            row = ChangeOrder(company_id=company_id, project_id=project_id, requested_by_user_id=user_id, change_no=(session.scalar(
                select(func.max(ChangeOrder.change_no)).where(ChangeOrder.project_id == project_id)) or 0) + 1)
            session.add(row)
        else:
            row = _change(session, company_id, change_id)
            if row.project_id != project_id:
                raise ValueError("درخواست تغییر در این پروژه نیست.")
            if row.status_code not in ("DRAFT", "REJECTED"):
                raise ValueError("درخواست ارسال‌شده یا تاییدشده ویرایش نمی‌شود.")
            for old in session.scalars(select(ChangeOrderLine).where(ChangeOrderLine.change_id == row.change_id)):
                session.delete(old)
        row.title, row.reason = title, (f.reason or "").strip() or None
        row.amount_change, row.days_change = decimal.Decimal(f.amount_change or 0), int(f.days_change or 0)
        row.status_code = "SUBMITTED" if submit else "DRAFT"
        row.decision_note, row.decided_by_user_id, row.decided_at = None, None, None
        session.flush()
        for ln in lines:
            session.add(ChangeOrderLine(change_id=row.change_id, code=ln.code, description=ln.description, unit=ln.unit,
                                        quantity=ln.quantity, unit_price=ln.unit_price))
        session.commit()
        return row.change_id


def submit(company_id: int, change_id: int) -> None:
    with new_session() as session:
        row = _change(session, company_id, change_id)
        if row.status_code != "DRAFT":
            raise ValueError("فقط درخواست پیش‌نویس ارسال می‌شود.")
        row.status_code = "SUBMITTED"
        session.commit()


def can_decide(company_id: int, user_id: int) -> bool:
    from peecha.services import roles

    return roles.is_manager(user_id, company_id) or roles.user_has_permission(user_id, company_id, FORM_CODE, "APPROVE")


def _check_decider(company_id: int, user_id: int, row: ChangeOrder) -> None:
    from peecha.services import roles

    if row.status_code != "SUBMITTED":
        raise ValueError("فقط درخواست ارسال‌شده تایید یا رد می‌شود.")
    if not can_decide(company_id, user_id):
        raise ValueError("تایید درخواست تغییر با دارندهٔ مجوز تایید پروژه‌هاست.")
    if row.requested_by_user_id == user_id and not roles.is_manager(user_id, company_id):
        raise ValueError("درخواست تغییر خودتان را نمی‌توانید تایید یا رد کنید.")


def approve(company_id: int, user_id: int, change_id: int, note: str | None = None) -> None:
    with new_session() as session:
        row = _change(session, company_id, change_id)
        _check_decider(company_id, user_id, row)
        project = session.get(Project, row.project_id)
        amount = project.contract_amount + row.amount_change
        if amount < 0:
            raise ValueError("با این تغییر، مبلغ قرارداد منفی می‌شود.")
        lines = list(session.scalars(select(ChangeOrderLine).where(ChangeOrderLine.change_id == change_id).order_by(ChangeOrderLine.line_id)))
        existing = {c.upper() for c in session.scalars(select(ContractItem.code).where(ContractItem.project_id == project.project_id))}
        clash = next((ln.code for ln in lines if ln.code.upper() in existing), None)
        if clash:
            raise ValueError(f"کد «{clash}» در فهرست بهای پروژه وجود دارد؛ درخواست را با کد دیگری اصلاح کنید.")
        order = session.scalar(select(func.max(ContractItem.sort_order)).where(ContractItem.project_id == project.project_id)) or 0
        for n, ln in enumerate(lines, start=1):
            item = ContractItem(project_id=project.project_id, code=ln.code, description=ln.description, unit=ln.unit,
                                contract_quantity=ln.quantity, unit_price=ln.unit_price, sort_order=order + n)
            session.add(item)
            session.flush()
            ln.contract_item_id = item.contract_item_id
        project.contract_amount = amount
        if row.days_change and project.target_end_date:
            project.target_end_date = max(project.start_date, project.target_end_date + datetime.timedelta(days=row.days_change))
        row.status_code, row.decision_note = "APPROVED", (note or "").strip() or None
        row.decided_by_user_id, row.decided_at = user_id, datetime.datetime.now(datetime.timezone.utc)
        session.commit()


def reject(company_id: int, user_id: int, change_id: int, reason: str) -> None:
    if not (reason or "").strip():
        raise ValueError("دلیل رد درخواست تغییر را بنویسید.")
    with new_session() as session:
        row = _change(session, company_id, change_id)
        _check_decider(company_id, user_id, row)
        row.status_code, row.decision_note = "REJECTED", reason.strip()
        row.decided_by_user_id, row.decided_at = user_id, datetime.datetime.now(datetime.timezone.utc)
        session.commit()


def delete_change(company_id: int, change_id: int) -> None:
    with new_session() as session:
        row = _change(session, company_id, change_id)
        if row.status_code not in ("DRAFT", "REJECTED"):
            raise ValueError("فقط درخواست پیش‌نویس یا ردشده حذف می‌شود.")
        session.delete(row)
        session.commit()


def list_changes(company_id: int, project_id: int | None = None, status: str | None = None) -> list[ChangeRow]:
    with new_session() as session:
        q = select(ChangeOrder).where(ChangeOrder.company_id == company_id)
        if project_id is not None:
            q = q.where(ChangeOrder.project_id == project_id)
        if status is not None:
            q = q.where(ChangeOrder.status_code == status)
        rows = list(session.scalars(q.order_by(ChangeOrder.project_id, ChangeOrder.change_no.desc())))
        lines: dict[int, list[LineFields]] = {}
        for ln in session.scalars(select(ChangeOrderLine).where(ChangeOrderLine.change_id.in_([r.change_id for r in rows] or [0]))
                                  .order_by(ChangeOrderLine.line_id)):
            lines.setdefault(ln.change_id, []).append(LineFields(ln.code, ln.description, ln.unit, ln.quantity, ln.unit_price))
    return [ChangeRow(r.change_id, r.project_id, r.change_no, r.title, r.reason or "", r.amount_change, r.days_change, r.status_code,
                      r.decision_note or "", r.requested_by_user_id, r.created_at, lines.get(r.change_id, [])) for r in rows]


def approved_totals(company_id: int, project_id: int) -> tuple[decimal.Decimal, int, int]:
    """(جمع مبلغ تغییرات تاییدشده، جمع روزها، تعداد درخواست‌های باز)."""
    rows = list_changes(company_id, project_id)
    approved = [r for r in rows if r.status_code == "APPROVED"]
    return (sum((r.amount_change for r in approved), ZERO), sum(r.days_change for r in approved),
            sum(1 for r in rows if r.status_code in ("DRAFT", "SUBMITTED")))
