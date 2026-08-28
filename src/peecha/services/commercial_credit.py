"""اعتبار (مرحلهٔ ۲/۵): بدونِ دفترِ اعتبارِ موازی — مواجهه = مانده‌یِ زندهٔ
AR (از موتورِ حسابداریِ ازپیش‌ساخته) + مبلغِ سفارش‌هایِ فروشِ
CONFIRMED/APPROVEDِ هنوز فاکتورنشده."""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.commercial import CommercialDocument, CreditHold, CreditPolicy
from peecha.services import treasury as treasury_service

_ZERO = decimal.Decimal(0)


def get_credit_policy(company_id: int, party_type_code: str) -> CreditPolicy | None:
    with new_session() as session:
        return session.scalar(
            select(CreditPolicy).where(CreditPolicy.company_id == company_id, CreditPolicy.party_type_code == party_type_code)
        )


def set_credit_policy(company_id: int, party_type_code: str, default_credit_limit: decimal.Decimal, default_payment_term_days: int, overdue_grace_days: int) -> None:
    if party_type_code not in ("CUSTOMER", "SUPPLIER"):
        raise ValueError("نوعِ طرفِ‌حساب نامعتبر است.")
    with new_session() as session:
        row = session.scalar(
            select(CreditPolicy).where(CreditPolicy.company_id == company_id, CreditPolicy.party_type_code == party_type_code)
        )
        if row is None:
            session.add(
                CreditPolicy(
                    company_id=company_id, party_type_code=party_type_code, default_credit_limit=default_credit_limit,
                    default_payment_term_days=default_payment_term_days, overdue_grace_days=overdue_grace_days,
                )
            )
        else:
            row.default_credit_limit = default_credit_limit
            row.default_payment_term_days = default_payment_term_days
            row.overdue_grace_days = overdue_grace_days
        session.commit()


def compute_customer_exposure(company_id: int, customer_detail_account_id: int) -> decimal.Decimal:
    balance, nature = treasury_service.get_counterparty_balance(company_id, customer_detail_account_id)
    ar_balance = balance if nature == "بدهکار" else _ZERO

    with new_session() as session:
        open_orders_total = session.scalar(
            select(func.coalesce(func.sum(CommercialDocument.total_amount), 0)).where(
                CommercialDocument.company_id == company_id,
                CommercialDocument.counterparty_detail_account_id == customer_detail_account_id,
                CommercialDocument.document_type_code == "SALES_ORDER",
                CommercialDocument.status_code.in_(("CONFIRMED", "APPROVED")),
            )
        )
    return ar_balance + decimal.Decimal(open_orders_total or 0)


def check_credit_exposure(company_id: int, customer_detail_account_id: int, additional_amount: decimal.Decimal) -> bool:
    """True یعنی مواجهه (پسِ افزودنِ additional_amount) از سقفِ اعتبار
    عبور می‌کند — سفارش باید به کارتابلِ اعتبار برود، نه Post شود."""
    from peecha.db.models.commercial import CustomerProfile

    with new_session() as session:
        profile = session.get(CustomerProfile, customer_detail_account_id)
        credit_limit = profile.credit_limit_amount if profile is not None else _ZERO
    exposure = compute_customer_exposure(company_id, customer_detail_account_id)
    return (exposure + additional_amount) > credit_limit


def create_credit_hold(party_detail_account_id: int, reason: str, held_by_user_id: int, related_document_id: int | None = None) -> int:
    with new_session() as session:
        row = CreditHold(
            party_detail_account_id=party_detail_account_id, related_document_id=related_document_id, reason=reason,
            held_by_user_id=held_by_user_id,
        )
        session.add(row)
        session.commit()
        return row.hold_id


def release_credit_hold(hold_id: int, released_by_user_id: int) -> None:
    with new_session() as session:
        row = session.get(CreditHold, hold_id)
        if row is None:
            raise ValueError("موردِ توقفِ اعتباری نامعتبر است.")
        if row.released_at is not None:
            raise ValueError("این موردِ توقف قبلاً آزاد شده است.")
        row.released_by_user_id = released_by_user_id
        row.released_at = datetime.datetime.now()
        session.commit()


def list_open_credit_holds(party_detail_account_id: int | None = None) -> list[CreditHold]:
    with new_session() as session:
        stmt = select(CreditHold).where(CreditHold.released_at.is_(None))
        if party_detail_account_id is not None:
            stmt = stmt.where(CreditHold.party_detail_account_id == party_detail_account_id)
        return list(session.scalars(stmt))
