"""فروشگاه و صندوق (مرحلهٔ ۷): جلسهٔ صندوق، پرداختِ چندروشی، وفاداری،
کارتِ‌هدیه، فروشِ اقساطی. تراکنشِ POS خودش یک comm.commercial_documents
با channel_code='POS' است — این فایل فقط قابلیت‌هایِ واقعاً تازه را
اضافه می‌کند."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import (
    CommercialDocument,
    GiftCard,
    InstallmentLine,
    InstallmentPlan,
    LoyaltyAccount,
    LoyaltyTransaction,
    PosPayment,
    PosSession,
    PosSettings,
    PosTerminal,
)

_ZERO = decimal.Decimal("0")
_Q2 = decimal.Decimal("0.01")


def _money(value: decimal.Decimal) -> decimal.Decimal:
    return value.quantize(_Q2, rounding=decimal.ROUND_HALF_UP)


# ---------------------------------------------------------------------
# ترمینال و جلسه
# ---------------------------------------------------------------------
def list_terminals(company_id: int) -> list[PosTerminal]:
    with new_session() as session:
        return list(session.scalars(select(PosTerminal).where(PosTerminal.company_id == company_id)))


def create_terminal(company_id: int, warehouse_id: int, code: str, name: str) -> int:
    with new_session() as session:
        row = PosTerminal(company_id=company_id, warehouse_id=warehouse_id, code=code, name=name)
        session.add(row)
        session.commit()
        return row.terminal_id


def get_open_session(terminal_id: int) -> PosSession | None:
    with new_session() as session:
        return session.scalar(select(PosSession).where(PosSession.terminal_id == terminal_id, PosSession.status_code == "OPEN"))


def get_session(session_id: int) -> PosSession | None:
    with new_session() as session:
        return session.get(PosSession, session_id)


def list_sessions(terminal_id: int) -> list[PosSession]:
    with new_session() as session:
        return list(session.scalars(select(PosSession).where(PosSession.terminal_id == terminal_id).order_by(PosSession.session_id.desc())))


def open_session(terminal_id: int, opened_by_user_id: int, opening_cash_amount: decimal.Decimal) -> int:
    with new_session() as session:
        terminal = session.get(PosTerminal, terminal_id)
        if terminal is None:
            raise ValueError("ترمینال نامعتبر است.")
        settings = session.get(PosSettings, terminal.company_id)
        threshold = settings.cash_variance_threshold_amount if settings is not None else _ZERO
        last_session = session.scalar(
            select(PosSession)
            .where(PosSession.terminal_id == terminal_id, PosSession.status_code == "CLOSED")
            .order_by(PosSession.session_id.desc())
        )
        if (
            last_session is not None and last_session.variance_amount is not None
            and abs(last_session.variance_amount) > threshold and last_session.variance_override_by_user_id is None
        ):
            raise ValueError("مغایرتِ جلسهٔ قبلیِ این ترمینال هنوز آزادسازی نشده — ابتدا مدیر باید تاییدِ استثنا کند.")
        open_row = session.scalar(select(PosSession).where(PosSession.terminal_id == terminal_id, PosSession.status_code == "OPEN"))
        if open_row is not None:
            raise ValueError("این ترمینال هم‌اکنون یک جلسهٔ باز دارد.")
        row = PosSession(terminal_id=terminal_id, opened_by_user_id=opened_by_user_id, opening_cash_amount=opening_cash_amount)
        session.add(row)
        session.commit()
        return row.session_id


def close_session(session_id: int, closed_by_user_id: int, closing_cash_amount: decimal.Decimal) -> decimal.Decimal:
    with new_session() as session:
        pos_session = session.get(PosSession, session_id)
        if pos_session is None or pos_session.status_code != "OPEN":
            raise ValueError("فقط جلسهٔ باز قابلِ‌بستن است.")
        open_drafts = session.scalar(
            select(CommercialDocument).where(
                CommercialDocument.pos_session_id == session_id, CommercialDocument.status_code.in_(("DRAFT", "CONFIRMED", "APPROVED"))
            )
        )
        if open_drafts is not None:
            raise ValueError("این جلسه سندِ ثبت‌نهایی‌نشده دارد — ابتدا Post یا لغو کنید.")
        total_cash = session.execute(
            select(PosPayment.amount)
            .join(CommercialDocument, CommercialDocument.document_id == PosPayment.document_id)
            .where(CommercialDocument.pos_session_id == session_id, PosPayment.method_code == "CASH")
        ).scalars().all()
        expected = pos_session.opening_cash_amount + sum(total_cash, _ZERO)
        pos_session.closing_cash_amount = closing_cash_amount
        pos_session.expected_cash_amount = expected
        pos_session.status_code = "CLOSED"
        pos_session.closed_by_user_id = closed_by_user_id
        pos_session.closed_at = datetime.datetime.now(datetime.timezone.utc)
        session.commit()
        return pos_session.variance_amount


def override_session_variance(session_id: int, overridden_by_user_id: int, reason: str) -> None:
    with new_session() as session:
        pos_session = session.get(PosSession, session_id)
        if pos_session is None or pos_session.status_code != "CLOSED":
            raise ValueError("فقط جلسهٔ بستهٔ دارایِ مغایرت قابلِ‌آزادسازی است.")
        pos_session.variance_override_by_user_id = overridden_by_user_id
        pos_session.variance_override_reason = reason
        session.commit()


# ---------------------------------------------------------------------
# پرداختِ چندروشی
# ---------------------------------------------------------------------
def record_payment(document_id: int, method_code: str, amount: decimal.Decimal, reference_no: str | None = None) -> int:
    if method_code not in ("CASH", "CARD", "WALLET", "GIFT_CARD", "STORE_CREDIT"):
        raise ValueError("روشِ پرداخت نامعتبر است.")
    if amount <= 0:
        raise ValueError("مبلغ باید بزرگ‌تر از صفر باشد.")
    with new_session() as session:
        row = PosPayment(document_id=document_id, method_code=method_code, amount=amount, reference_no=reference_no)
        session.add(row)
        session.commit()
        return row.payment_id


def payments_cover_total(document_id: int) -> bool:
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None:
            raise ValueError("سند نامعتبر است.")
        paid = session.execute(select(PosPayment.amount).where(PosPayment.document_id == document_id)).scalars().all()
        plan_amounts = session.execute(
            select(InstallmentLine.amount)
            .join(InstallmentPlan, InstallmentPlan.plan_id == InstallmentLine.plan_id)
            .where(InstallmentPlan.document_id == document_id)
        ).scalars().all()
        return _money(sum(paid, _ZERO) + sum(plan_amounts, _ZERO)) == _money(doc.total_amount)


# ---------------------------------------------------------------------
# باشگاهِ مشتریان
# ---------------------------------------------------------------------
def get_or_create_loyalty_account(customer_detail_account_id: int) -> LoyaltyAccount:
    with new_session() as session:
        row = session.scalar(select(LoyaltyAccount).where(LoyaltyAccount.customer_detail_account_id == customer_detail_account_id))
        if row is None:
            row = LoyaltyAccount(customer_detail_account_id=customer_detail_account_id)
            session.add(row)
            session.commit()
            session.refresh(row)
        return row


def earn_points(customer_detail_account_id: int, points: int, document_id: int | None = None) -> None:
    account = get_or_create_loyalty_account(customer_detail_account_id)
    with new_session() as session:
        account_row = session.get(LoyaltyAccount, account.loyalty_account_id)
        account_row.points_balance += points
        session.add(LoyaltyTransaction(loyalty_account_id=account_row.loyalty_account_id, document_id=document_id, points_delta=points, transaction_type_code="EARN"))
        session.commit()


def redeem_wallet(customer_detail_account_id: int, amount: decimal.Decimal, document_id: int | None = None) -> None:
    account = get_or_create_loyalty_account(customer_detail_account_id)
    with new_session() as session:
        account_row = session.get(LoyaltyAccount, account.loyalty_account_id)
        if account_row.wallet_balance < amount:
            raise ValueError("موجودیِ کیف‌پول کافی نیست.")
        account_row.wallet_balance -= amount
        session.add(
            LoyaltyTransaction(
                loyalty_account_id=account_row.loyalty_account_id, document_id=document_id, wallet_delta=-amount,
                transaction_type_code="REDEEM",
            )
        )
        session.commit()


def top_up_wallet(customer_detail_account_id: int, amount: decimal.Decimal, document_id: int | None = None) -> None:
    account = get_or_create_loyalty_account(customer_detail_account_id)
    with new_session() as session:
        account_row = session.get(LoyaltyAccount, account.loyalty_account_id)
        account_row.wallet_balance += amount
        session.add(
            LoyaltyTransaction(
                loyalty_account_id=account_row.loyalty_account_id, document_id=document_id, wallet_delta=amount,
                transaction_type_code="ADJUST",
            )
        )
        session.commit()


# ---------------------------------------------------------------------
# کارتِ‌هدیه
# ---------------------------------------------------------------------
def issue_gift_card(company_id: int, code: str, initial_balance: decimal.Decimal, expires_at: datetime.datetime | None = None) -> int:
    with new_session() as session:
        row = GiftCard(company_id=company_id, code=code, initial_balance=initial_balance, current_balance=initial_balance, expires_at=expires_at)
        session.add(row)
        session.commit()
        return row.card_id


def redeem_gift_card(code: str, amount: decimal.Decimal) -> None:
    with new_session() as session:
        card = session.scalar(select(GiftCard).where(GiftCard.code == code))
        if card is None:
            raise ValueError("کارتِ‌هدیه نامعتبر است.")
        if card.status_code != "ACTIVE":
            raise ValueError("این کارتِ‌هدیه فعال نیست.")
        if card.expires_at is not None and card.expires_at < datetime.datetime.now(datetime.timezone.utc):
            card.status_code = "EXPIRED"
            session.commit()
            raise ValueError("کارتِ‌هدیه منقضی شده است.")
        if card.current_balance < amount:
            raise ValueError("موجودیِ کارتِ‌هدیه کافی نیست.")
        card.current_balance -= amount
        if card.current_balance == 0:
            card.status_code = "REDEEMED"
        session.commit()


# ---------------------------------------------------------------------
# فروشِ اقساطی
# ---------------------------------------------------------------------
def create_installment_plan(document_id: int, number_of_installments: int, first_due_date: datetime.date, total_amount: decimal.Decimal) -> int:
    if number_of_installments <= 0:
        raise ValueError("تعدادِ اقساط باید بزرگ‌تر از صفر باشد.")
    per_installment = _money(total_amount / number_of_installments)
    with new_session() as session:
        plan = InstallmentPlan(document_id=document_id, number_of_installments=number_of_installments, first_due_date=first_due_date)
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


def mark_installment_paid(line_id: int, paid_journal_entry_id: int | None = None) -> None:
    with new_session() as session:
        line = session.get(InstallmentLine, line_id)
        if line is None:
            raise ValueError("قسط نامعتبر است.")
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


def list_overdue_installments(as_of_date: datetime.date | None = None) -> list[InstallmentLine]:
    as_of_date = as_of_date or datetime.date.today()
    with new_session() as session:
        lines = session.scalars(select(InstallmentLine).where(InstallmentLine.status_code == "PENDING", InstallmentLine.due_date < as_of_date)).all()
        for line in lines:
            line.status_code = "OVERDUE"
        session.commit()
        return list(lines)


# ---------------------------------------------------------------------
# مشتریِ متفرقهٔ پیش‌فرض
# ---------------------------------------------------------------------
def get_pos_settings(company_id: int) -> PosSettings | None:
    with new_session() as session:
        return session.get(PosSettings, company_id)


def set_pos_settings(company_id: int, default_guest_customer_detail_account_id: int | None, cash_variance_threshold_amount: decimal.Decimal) -> None:
    with new_session() as session:
        row = session.get(PosSettings, company_id)
        if row is None:
            session.add(
                PosSettings(
                    company_id=company_id, default_guest_customer_detail_account_id=default_guest_customer_detail_account_id,
                    cash_variance_threshold_amount=cash_variance_threshold_amount,
                )
            )
        else:
            row.default_guest_customer_detail_account_id = default_guest_customer_detail_account_id
            row.cash_variance_threshold_amount = cash_variance_threshold_amount
        session.commit()
