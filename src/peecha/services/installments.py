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

from sqlalchemy import or_, select

from peecha.db.base import new_session
from peecha.db.models.commercial import CommercialDocument, InstallmentLine, InstallmentPlan

_ZERO = decimal.Decimal("0")
_Q2 = decimal.Decimal("0.01")


def _money(value: decimal.Decimal) -> decimal.Decimal:
    return value.quantize(_Q2, rounding=decimal.ROUND_HALF_UP)


def create_installment_plan(
    document_id: int | None, number_of_installments: int, first_due_date: datetime.date, principal_amount: decimal.Decimal,
    *,
    company_id: int | None = None,
    counterparty_detail_account_id: int | None = None,
    direction: str | None = None,
    interest_rate_percent: decimal.Decimal = _ZERO,
    misc_fee_amount: decimal.Decimal = _ZERO,
    due_interval_days: int = 30,
) -> int:
    """طبقِ فاصله‌یِ قابلِ‌تنظیم (پیش‌فرض ۳۰ روز، طبقِ موردِ ۶): هر قسط
    due_interval_days روز بعدِ قبلی سررسید می‌شود. مبلغِ هر قسط یکسان
    است، بجز قسطِ آخر که مانده‌یِ دقیقِ گِردکردن را جذب می‌کند.

    document_id: طبقِ موردِ ۵، اختیاری است -- None یعنی طرحِ اقساطِ آزاد
    (بدونِ فاکتور)، که در این حالت company_id/counterparty_detail_account_id/
    direction الزامی‌اند تا طرح بتواند بدونِ فاکتور به طرفِ‌حساب و شرکتِ
    خودش وصل بماند.

    interest_rate_percent/misc_fee_amount: طبقِ موردِ ۶ -- مازاد بر اصلِ
    مبلغ محاسبه و به‌صورتِ مساوی بینِ اقساط تقسیم می‌شود (سهمِ هر قسط در
    InstallmentLine.interest_fee_amount نگه‌داری می‌شود تا در تسویه قابلِ
    تفکیک از اصلِ مبلغ باشد)؛ اثرِ حسابداریِ این مازاد (شناساییِ درآمد/
    هزینه) در همان سندی که این طرح را می‌سازد ثبت می‌شود، نه این‌جا."""
    if number_of_installments < 2:
        raise ValueError("تعدادِ اقساط باید حداقل ۲ باشد.")
    if principal_amount <= _ZERO:
        raise ValueError("مبلغِ کل باید مثبت باشد.")
    if document_id is None and (company_id is None or counterparty_detail_account_id is None or direction is None):
        raise ValueError("برایِ طرحِ اقساطِ بدونِ فاکتور، شرکت، طرفِ‌حساب، و جهت (دریافت/پرداخت) الزامی است.")
    if interest_rate_percent < 0:
        raise ValueError("درصدِ بهره نمی‌تواند منفی باشد.")
    if misc_fee_amount < 0:
        raise ValueError("هزینهٔ متفرقه نمی‌تواند منفی باشد.")
    if due_interval_days < 1:
        raise ValueError("فاصلهٔ سررسید باید حداقل ۱ روز باشد.")

    total_interest_fee = _money(principal_amount * interest_rate_percent / decimal.Decimal(100)) + misc_fee_amount
    total_payable = principal_amount + total_interest_fee
    per_installment = _money(total_payable / number_of_installments)
    per_installment_fee = _money(total_interest_fee / number_of_installments)
    with new_session() as session:
        plan = InstallmentPlan(
            document_id=document_id, company_id=company_id, counterparty_detail_account_id=counterparty_detail_account_id,
            direction=direction, number_of_installments=number_of_installments, first_due_date=first_due_date,
            principal_amount=principal_amount, interest_rate_percent=interest_rate_percent,
            misc_fee_amount=misc_fee_amount, due_interval_days=due_interval_days,
        )
        session.add(plan)
        session.flush()
        remaining_total = total_payable
        remaining_fee = total_interest_fee
        due_date = first_due_date
        for i in range(1, number_of_installments + 1):
            if i < number_of_installments:
                amount, fee = per_installment, per_installment_fee
            else:
                amount, fee = _money(remaining_total), _money(remaining_fee)
            remaining_total -= amount
            remaining_fee -= fee
            session.add(
                InstallmentLine(
                    plan_id=plan.plan_id, installment_no=i, due_date=due_date, amount=amount, interest_fee_amount=fee,
                )
            )
            due_date = due_date + datetime.timedelta(days=due_interval_days)
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
        # طبقِ موردِ ۵: document_id ممکن است NULL باشد (طرحِ اقساطِ آزاد) --
        # با outerjoin به‌جایِ join، این ردیف‌ها هم با فیلترِ company_idِ
        # خودِ InstallmentPlan (نه فقط از رویِ سند) شامل می‌شوند.
        lines = session.scalars(
            select(InstallmentLine)
            .join(InstallmentPlan, InstallmentPlan.plan_id == InstallmentLine.plan_id)
            .outerjoin(CommercialDocument, CommercialDocument.document_id == InstallmentPlan.document_id)
            .where(
                or_(CommercialDocument.company_id == company_id, InstallmentPlan.company_id == company_id),
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
    document_id: int | None
    installment_no: int
    due_date: datetime.date
    amount: decimal.Decimal
    status_code: str
    interest_fee_amount: decimal.Decimal = _ZERO


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
            .outerjoin(CommercialDocument, CommercialDocument.document_id == InstallmentPlan.document_id)
            .where(or_(CommercialDocument.company_id == company_id, InstallmentPlan.company_id == company_id))
        )
        if status_codes:
            stmt = stmt.where(InstallmentLine.status_code.in_(status_codes))
        if document_id is not None:
            stmt = stmt.where(InstallmentPlan.document_id == document_id)
        if counterparty_detail_account_id is not None:
            stmt = stmt.where(
                or_(
                    CommercialDocument.counterparty_detail_account_id == counterparty_detail_account_id,
                    InstallmentPlan.counterparty_detail_account_id == counterparty_detail_account_id,
                )
            )
        rows = session.execute(stmt.order_by(InstallmentLine.due_date)).all()
        return [
            InstallmentLineRow(
                line_id=line.line_id, plan_id=line.plan_id, document_id=doc_id, installment_no=line.installment_no,
                due_date=line.due_date, amount=line.amount, status_code=line.status_code,
                interest_fee_amount=line.interest_fee_amount,
            )
            for line, doc_id in rows
        ]
