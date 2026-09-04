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
    PosCashierSettings,
    PosPayment,
    PosSession,
    PosSettings,
    PosTerminal,
)
from peecha.services import commercial_settlements as settlements_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import treasury as treasury_service

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
# چرخهٔ تاییدِ فروشِ حضوری -- طبقِ تصمیمِ صریح («کاریر فقط تایید می‌کند،
# ثبتِ واقعیِ پرداخت/سندِ حسابداری با تاییدِ سرپرست انجام می‌شود»):
# کاریر فقط نوعِ پرداختِ موردنظرش را یادداشت می‌کند؛ خودِ POST/JE اینجا
# اتفاق نمی‌افتد.
# ---------------------------------------------------------------------
def set_intended_payment_type(document_id: int, company_id: int, payment_type: str) -> None:
    if payment_type not in ("CASH", "CREDIT"):
        raise ValueError("نوعِ پرداخت نامعتبر است.")
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        doc.pos_intended_payment_type = payment_type
        session.commit()


def list_pending_pos_documents(company_id: int, pos_session_id: int) -> list[CommercialDocument]:
    """فاکتورهایِ این شیفت که کاریر تایید کرده ولی هنوز سرپرست
    approve/post نکرده -- برایِ صفحه‌یِ تاییدِ سرپرست و برایِ لیستِ
    «فروش‌هایِ درجریان/رزروشده» در خودِ صفحه‌یِ فروش."""
    with new_session() as session:
        return list(
            session.scalars(
                select(CommercialDocument)
                .where(
                    CommercialDocument.company_id == company_id,
                    CommercialDocument.document_type_code == "SALES_INVOICE",
                    CommercialDocument.pos_session_id == pos_session_id,
                    CommercialDocument.status_code.in_(("DRAFT", "CONFIRMED")),
                )
                .order_by(CommercialDocument.document_id.desc())
            )
        )


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


def record_payment_and_settle(
    company_id: int, user_id: int, document_id: int, method_code: str,
    amount: decimal.Decimal, reference_no: str | None = None,
) -> int:
    """طبقِ رفعِ شکافِ کشف‌شده: record_payment (بالا) از اول فقط یک
    ردیفِ comm.pos_payments ثبت می‌کرد -- بدونِ هیچ اثری در حساب‌هایِ
    نقد/بانک یا در comm.invoice_settlements؛ یعنی مشتری برایِ همیشه در
    گزارش‌هایِ تسویه «بدهکار» می‌ماند و نقدِ واقعاً دریافت‌شده هیچ‌وقت به
    صندوق/بانک نمی‌رسید. این تابع هر پرداختِ POS را به نتیجهٔ حسابداریِ
    واقعی‌اش وصل می‌کند:
    - نقد/کارت‌خوان: یک سندِ خزانه‌داریِ واقعی (create_treasury_voucher،
      دقیقاً هم‌الگو با فرمِ دریافتِ معمولی) ساخته و به فاکتور تسویه
      می‌شود.
    - کیف‌پول/کارتِ‌هدیه/اعتبارِ فروشگاهی: نیازی به سندِ خزانه‌داریِ تازه
      نیست (این‌ها از پیش داخلِ سیستم‌اند)، فقط تسویه (بدونِ ژورنالِ
      جدید) ثبت می‌شود."""
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        customer_id = doc.counterparty_detail_account_id
        document_date = doc.document_date
        document_no = doc.document_no

    if method_code == "GIFT_CARD":
        if not reference_no:
            raise ValueError("کدِ کارتِ‌هدیه را وارد کنید.")
        redeem_gift_card(reference_no, amount)
    elif method_code == "WALLET":
        redeem_wallet(customer_id, amount, document_id=document_id)

    payment_id = record_payment(document_id, method_code, amount, reference_no=reference_no)

    journal_entry_id = None
    if method_code in ("CASH", "CARD"):
        person_dimension_type_id = dimensions_service.get_person_dimension_type_id(company_id)
        customer_group_id = next(
            (g.person_group_id for g in dimensions_service.list_person_groups(company_id) if g.code == "CUSTOMER"),
            None,
        )
        mapping_account_id = next(
            (
                m.account_id for m in treasury_service.list_counterparty_mappings(company_id, "RECEIPT")
                if m.person_group_id == customer_group_id
            ),
            None,
        )
        if mapping_account_id is None:
            raise ValueError("نگاشتِ حسابِ دریافت برایِ گروهِ «مشتری» در تنظیماتِ خزانه‌داری مشخص نشده است.")
        treasury_method = "CASH" if method_code == "CASH" else "BANK"
        voucher_result = treasury_service.create_treasury_voucher(
            company_id, user_id, "RECEIPT", mapping_account_id,
            {person_dimension_type_id: customer_id}, document_date,
            f"دریافتِ صندوق (POS) -- بابتِ فاکتورِ فروشِ #{document_no}",
            [treasury_service.MethodLine(method=treasury_method, amount=amount)],
        )
        journal_entry_id = voucher_result.journal_entry_id

    settlements_service.allocate_settlement(
        company_id, document_id, journal_entry_id, datetime.date.today(), amount, user_id,
        reference_no=reference_no, description="تسویه‌یِ خودکارِ فروشِ حضوری (POS)",
    )
    return payment_id


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


# طبقِ عمومی‌سازیِ صریح («روشِ دریافت/پرداختِ اقساطی برایِ همه‌یِ
# فاکتورها، نه فقط POS»): create_installment_plan/mark_installment_paid/
# list_overdue_installments به services/installments.py منتقل شدند --
# این‌جا فقط payments_cover_total (بالا) مستقیماً از مدل‌هایِ
# InstallmentPlan/InstallmentLine برایِ جمعِ ساده استفاده می‌کند.


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


# ---------------------------------------------------------------------
# تنظیماتِ صندوق‌داریِ هر (کاربر، شرکت) -- طبقِ درخواستِ صریح («این
# تنظیمات در قسمتِ تنظیماتِ کاربر با نقشِ صندوق‌دار باید تعریف بشه»):
# هر کاربر می‌تواند ترمینال/فهرستِ‌قیمت/مشتریِ پیش‌فرضِ خودش را (به‌ازایِ
# هر شرکت، چون این‌ها همه چیزهایِ شرکت‌محورند) داشته باشد تا صفحه‌یِ
# فروشِ حضوری دیگر هر بار این‌ها را از او نپرسد.
# ---------------------------------------------------------------------
def get_cashier_settings(user_id: int, company_id: int) -> PosCashierSettings | None:
    with new_session() as session:
        return session.get(PosCashierSettings, {"user_id": user_id, "company_id": company_id})


def set_cashier_settings(
    user_id: int, company_id: int, default_terminal_id: int | None, default_price_list_id: int | None,
    default_customer_detail_account_id: int | None,
) -> None:
    with new_session() as session:
        row = session.get(PosCashierSettings, {"user_id": user_id, "company_id": company_id})
        if row is None:
            session.add(
                PosCashierSettings(
                    user_id=user_id, company_id=company_id, default_terminal_id=default_terminal_id,
                    default_price_list_id=default_price_list_id,
                    default_customer_detail_account_id=default_customer_detail_account_id,
                )
            )
        else:
            row.default_terminal_id = default_terminal_id
            row.default_price_list_id = default_price_list_id
            row.default_customer_detail_account_id = default_customer_detail_account_id
        session.commit()
