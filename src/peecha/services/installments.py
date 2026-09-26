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

from sqlalchemy import case, func, or_, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.commercial import CommercialDocument, InstallmentCollection, InstallmentLine, InstallmentPlan

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


def get_installment_collected_amount(line_id: int, session=None) -> decimal.Decimal:
    def _query(s):
        return _money(
            s.scalar(
                select(func.coalesce(func.sum(InstallmentCollection.amount), _ZERO)).where(
                    InstallmentCollection.line_id == line_id
                )
            )
        )

    if session is not None:
        return _query(session)
    with new_session() as session:
        return _query(session)


def get_installment_remaining_amount(line_id: int) -> decimal.Decimal:
    with new_session() as session:
        line = session.get(InstallmentLine, line_id)
        if line is None:
            raise ValueError("قسط نامعتبر است.")
        return _money(line.amount - get_installment_collected_amount(line_id, session))


def record_installment_collection(
    line_id: int, amount: decimal.Decimal, journal_entry_id: int | None, collection_date: datetime.date,
    created_by_user_id: int, description: str | None = None,
) -> None:
    """طبقِ درخواستِ صریح («ممکنه بخشی از اقساط وصول بشه»): جایگزینِ
    mark_installment_paid که همیشه کلِ قسط را یک‌جا PAID می‌کرد -- این‌جا
    فقط amountِ واقعاً وصول‌شده (که می‌تواند کمتر از مبلغِ کلِ قسط باشد)
    به‌عنوانِ یک رویدادِ InstallmentCollection ثبت می‌شود؛ قسط فقط وقتی
    که مجموعِ همه‌یِ وصولی‌هایش به مبلغِ کلش برسد PAID می‌شود، وگرنه
    وضعیتش (PENDING/OVERDUE) دست‌نخورده می‌ماند و «مانده» از تفاضلِ
    amount منهایِ مجموعِ وصولی‌ها محاسبه می‌شود."""
    if amount <= _ZERO:
        raise ValueError("مبلغِ وصول باید مثبت باشد.")
    with new_session() as session:
        line = session.get(InstallmentLine, line_id)
        if line is None:
            raise ValueError("قسط نامعتبر است.")
        if line.status_code == "PAID":
            raise ValueError("این قسط قبلاً به‌طورِ کامل دریافت/پرداخت شده است.")
        collected_so_far = get_installment_collected_amount(line_id, session)
        remaining = _money(line.amount - collected_so_far)
        if amount > remaining:
            raise ValueError(f"مبلغِ واردشده از ماندهٔ این قسط ({_money(remaining)}) بیشتر است.")
        session.add(
            InstallmentCollection(
                line_id=line_id, journal_entry_id=journal_entry_id, collection_date=collection_date,
                amount=amount, description=description, created_by_user_id=created_by_user_id,
            )
        )
        line.paid_journal_entry_id = journal_entry_id
        if amount >= remaining:
            line.status_code = "PAID"
        session.commit()
        if line.status_code == "PAID":
            plan = session.get(InstallmentPlan, line.plan_id)
            still_open = session.scalar(
                select(InstallmentLine).where(InstallmentLine.plan_id == plan.plan_id, InstallmentLine.status_code != "PAID")
            )
            if still_open is None:
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
    document_type_code: str | None
    document_no: int | None
    installment_no: int
    due_date: datetime.date
    amount: decimal.Decimal
    status_code: str
    interest_fee_amount: decimal.Decimal = _ZERO
    counterparty_detail_account_id: int | None = None
    counterparty_label: str = ""
    direction: str | None = None  # RECEIPT | PAYMENT
    collected_amount: decimal.Decimal = _ZERO
    remaining_amount: decimal.Decimal = _ZERO


def list_installments(
    company_id: int, status_codes: list[str] | None = None, document_id: int | None = None,
    counterparty_detail_account_id: int | None = None,
    due_date_from: datetime.date | None = None, due_date_to: datetime.date | None = None,
) -> list[InstallmentLineRow]:
    """طبقِ درخواستِ صریح: فهرستِ اقساط (همه یا فیلترشده -- طرفِ‌حساب/
    بازه‌یِ تاریخِ سررسید) برایِ صفحه‌یِ مدیریتِ اقساط -- پیش از خواندن،
    معوقه‌هایِ تازه را OVERDUE علامت می‌زند تا وضعیتِ نمایش‌داده‌شده
    همیشه به‌روز باشد.

    طبقِ گزارشِ صریح («جدول نامِ طرفِ‌حساب را نمی‌آورد»): علتِ ریشه‌ای
    این بود که UI فقط از رویِ سند (که برایِ طرحِ اقساطِ بدونِ فاکتور
    اصلاً وجود ندارد) و فقط از فهرستِ مشتریان/تامین‌کنندگان (نه هر
    تفصیلیِ دیگری) طرفِ‌حساب را می‌ساخت -- این‌جا مستقیماً با join به
    acc.detail_accounts، برایِ هر دو حالت (بافاکتور/بدونِ فاکتور) و هر
    نوع تفصیلی‌ای برچسب ساخته می‌شود."""
    list_overdue_installments(company_id)
    with new_session() as session:
        collected_subq = (
            select(InstallmentCollection.line_id, func.sum(InstallmentCollection.amount).label("collected"))
            .group_by(InstallmentCollection.line_id)
            .subquery()
        )
        counterparty_id_expr = func.coalesce(
            CommercialDocument.counterparty_detail_account_id, InstallmentPlan.counterparty_detail_account_id
        )
        direction_expr = case(
            (CommercialDocument.document_id.is_(None), InstallmentPlan.direction),
            (CommercialDocument.document_type_code == "SALES_INVOICE", "RECEIPT"),
            else_="PAYMENT",
        )
        stmt = (
            select(
                InstallmentLine, InstallmentPlan.document_id, CommercialDocument.document_type_code,
                CommercialDocument.document_no, counterparty_id_expr, direction_expr,
                DetailAccount.code, DetailAccount.name,
                func.coalesce(collected_subq.c.collected, _ZERO),
            )
            .join(InstallmentPlan, InstallmentPlan.plan_id == InstallmentLine.plan_id)
            .outerjoin(CommercialDocument, CommercialDocument.document_id == InstallmentPlan.document_id)
            .outerjoin(collected_subq, collected_subq.c.line_id == InstallmentLine.line_id)
            .outerjoin(DetailAccount, DetailAccount.detail_account_id == counterparty_id_expr)
            .where(or_(CommercialDocument.company_id == company_id, InstallmentPlan.company_id == company_id))
        )
        if status_codes:
            stmt = stmt.where(InstallmentLine.status_code.in_(status_codes))
        if document_id is not None:
            stmt = stmt.where(InstallmentPlan.document_id == document_id)
        if counterparty_detail_account_id is not None:
            stmt = stmt.where(counterparty_id_expr == counterparty_detail_account_id)
        if due_date_from is not None:
            stmt = stmt.where(InstallmentLine.due_date >= due_date_from)
        if due_date_to is not None:
            stmt = stmt.where(InstallmentLine.due_date <= due_date_to)
        rows = session.execute(stmt.order_by(InstallmentLine.due_date)).all()
        result = []
        for line, doc_id, doc_type_code, doc_no, party_id, direction, party_code, party_name, collected in rows:
            collected = _money(collected)
            label = f"{party_code} — {party_name}" if party_name else (party_code or "")
            result.append(
                InstallmentLineRow(
                    line_id=line.line_id, plan_id=line.plan_id, document_id=doc_id, document_type_code=doc_type_code,
                    document_no=doc_no, installment_no=line.installment_no, due_date=line.due_date, amount=line.amount,
                    status_code=line.status_code, interest_fee_amount=line.interest_fee_amount,
                    counterparty_detail_account_id=party_id, counterparty_label=label, direction=direction,
                    collected_amount=collected, remaining_amount=_money(line.amount - collected),
                )
            )
        return result
