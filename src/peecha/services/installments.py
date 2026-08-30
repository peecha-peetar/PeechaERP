"""اقساط -- عمومی‌سازیِ InstallmentPlan/InstallmentLineِ ازپیش‌موجود که
قبلاً فقط در commercial_pos.py، بدونِ هیچ فراخوان‌کننده‌یِ واقعی (نه در
UI، نه در ثبتِ حسابداری)، تعریف شده بودند. طبقِ درخواستِ صریح («روشِ
دریافت و پرداختِ اقساطی»)، این ماژول از همان‌جا کاملاً منتقل و عمومی شده
تا موردِ استفاده‌یِ اصلی‌اش (فرمِ عمومیِ دریافت/پرداخت treasury_voucher.py،
نه فقط POS) را هم پوشش بدهد."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import CommercialDocument, InstallmentLine, InstallmentPlan

_ZERO = decimal.Decimal("0")
_Q2 = decimal.Decimal("0.01")


def _money(value: decimal.Decimal) -> decimal.Decimal:
    return value.quantize(_Q2, rounding=decimal.ROUND_HALF_UP)


def create_installment_plan(
    document_id: int, number_of_installments: int, first_due_date: datetime.date, total_amount: decimal.Decimal,
) -> int:
    """طبقِ فاصله‌یِ ازپیش‌تعیین‌شده در همین مدل (commercial_pos.py قدیم):
    هر قسط ۳۰ روز بعدِ قبلی سررسید می‌شود. مبلغِ هر قسط یکسان است، بجز
    قسطِ آخر که مانده‌یِ دقیقِ گِردکردن را جذب می‌کند."""
    if number_of_installments < 2:
        raise ValueError("تعدادِ اقساط باید حداقل ۲ باشد.")
    if total_amount <= _ZERO:
        raise ValueError("مبلغِ کل باید مثبت باشد.")
    per_installment = _money(total_amount / number_of_installments)
    with new_session() as session:
        plan = InstallmentPlan(
            document_id=document_id, number_of_installments=number_of_installments, first_due_date=first_due_date,
        )
        session.add(plan)
        session.flush()
        remaining = total_amount
        due_date = first_due_date
        for i in range(1, number_of_installments + 1):
            amount = per_installment if i < number_of_installments else _money(remaining)
            remaining -= amount
            session.add(InstallmentLine(plan_id=plan.plan_id, installment_no=i, due_date=due_date, amount=amount))
            due_date = due_date + datetime.timedelta(days=30)
        session.commit()
        return plan.plan_id


def get_installment_line(installment_line_id: int) -> InstallmentLine | None:
    with new_session() as session:
        return session.get(InstallmentLine, installment_line_id)


def get_installment_plan(plan_id: int) -> InstallmentPlan | None:
    with new_session() as session:
        return session.get(InstallmentPlan, plan_id)


def mark_installment_paid(line_id: int, paid_journal_entry_id: int | None = None) -> None:
    with new_session() as session:
        line = session.get(InstallmentLine, line_id)
        if line is None:
            raise ValueError("قسط نامعتبر است.")
        if line.status_code == "PAID":
            raise ValueError("این قسط قبلاً دریافت/پرداخت شده است.")
        line.status_code = "PAID"
        line.paid_journal_entry_id = paid_journal_entry_id
        session.commit()
        plan = session.get(InstallmentPlan, line.plan_id)
        remaining = session.scalar(
            select(InstallmentLine).where(InstallmentLine.plan_id == plan.plan_id, InstallmentLine.status_code != "PAID")
        )
        if remaining is None:
            plan.status_code = "COMPLETED"
            session.commit()


def list_overdue_installments(company_id: int, as_of_date: datetime.date | None = None) -> list[InstallmentLine]:
    as_of_date = as_of_date or datetime.date.today()
    with new_session() as session:
        lines = session.scalars(
            select(InstallmentLine)
            .join(InstallmentPlan, InstallmentPlan.plan_id == InstallmentLine.plan_id)
            .join(CommercialDocument, CommercialDocument.document_id == InstallmentPlan.document_id)
            .where(
                CommercialDocument.company_id == company_id,
                InstallmentLine.status_code == "PENDING",
                InstallmentLine.due_date < as_of_date,
            )
        ).all()
        for line in lines:
            line.status_code = "OVERDUE"
        session.commit()
        return list(lines)


@dataclass
class InstallmentLineRow:
    line_id: int
    plan_id: int
    document_id: int
    installment_no: int
    due_date: datetime.date
    amount: decimal.Decimal
    status_code: str


def list_installments(
    company_id: int, status_codes: list[str] | None = None, document_id: int | None = None,
    counterparty_detail_account_id: int | None = None,
) -> list[InstallmentLineRow]:
    """طبقِ درخواستِ صریح: فهرستِ اقساط (همه یا فیلترشده) برایِ صفحه‌یِ
    مدیریتِ اقساط -- پیش از خواندن، معوقه‌هایِ تازه را OVERDUE علامت
    می‌زند تا وضعیتِ نمایش‌داده‌شده همیشه به‌روز باشد."""
    list_overdue_installments(company_id)
    with new_session() as session:
        stmt = (
            select(InstallmentLine, InstallmentPlan.document_id)
            .join(InstallmentPlan, InstallmentPlan.plan_id == InstallmentLine.plan_id)
            .join(CommercialDocument, CommercialDocument.document_id == InstallmentPlan.document_id)
            .where(CommercialDocument.company_id == company_id)
        )
        if status_codes:
            stmt = stmt.where(InstallmentLine.status_code.in_(status_codes))
        if document_id is not None:
            stmt = stmt.where(InstallmentPlan.document_id == document_id)
        if counterparty_detail_account_id is not None:
            stmt = stmt.where(CommercialDocument.counterparty_detail_account_id == counterparty_detail_account_id)
        rows = session.execute(stmt.order_by(InstallmentLine.due_date)).all()
        return [
            InstallmentLineRow(
                line_id=line.line_id, plan_id=line.plan_id, document_id=doc_id, installment_no=line.installment_no,
                due_date=line.due_date, amount=line.amount, status_code=line.status_code,
            )
            for line, doc_id in rows
        ]
