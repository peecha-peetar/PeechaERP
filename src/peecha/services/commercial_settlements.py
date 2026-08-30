"""تسویه‌یِ فاکتور (comm.invoice_settlements/comm.settlement_alarm_settings)
-- طبقِ درخواستِ صریح («هر دریافت و پرداخت رفرنسِ فاکتور را داشته باشد و
مدیریتِ تسویه‌یِ فاکتورها را ایجاد کن»).

چون هر رسیدِ خزانه‌داری در این برنامه چیزی جز یک سندِ حسابداری
(acc.journal_entries) نیست (هیچ جدولِ «سندِ خزانه‌داری»یِ جداگانه‌ای وجود
ندارد)، تخصیصِ دریافت/پرداخت به فاکتور به‌صورتِ دستی -- از یک صفحه‌یِ
جداگانه‌یِ «مدیریتِ تسویه» -- به journal_entry_id وصل می‌شود؛ خودِ فرمِ
دریافت/پرداخت (treasury_voucher.py) دست‌نخورده می‌ماند."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import JournalEntry
from peecha.db.models.commercial import (
    CommercialDocument,
    CustomerProfile,
    InvoiceSettlement,
    SettlementAlarmSettings,
    SupplierProfile,
)

_ZERO = decimal.Decimal("0")
_INVOICE_TYPES = ("SALES_INVOICE", "PURCHASE_INVOICE")


def compute_due_date(
    company_id: int, document_type_code: str, counterparty_detail_account_id: int, document_date: datetime.date,
) -> datetime.date | None:
    """موعدِ تسویه از رویِ payment_term_days طرفِ‌حساب -- اگر طرفِ‌حساب
    پروفایلِ مشتری/تامین‌کننده نداشته باشد (مثلاً حسابِ عمومیِ نقدی)، None
    برمی‌گردد (یعنی «بدونِ موعدِ مشخص»)."""
    if document_type_code not in _INVOICE_TYPES:
        return None
    with new_session() as session:
        if document_type_code == "SALES_INVOICE":
            profile = session.get(CustomerProfile, counterparty_detail_account_id)
        else:
            profile = session.get(SupplierProfile, counterparty_detail_account_id)
        if profile is None:
            return None
        return document_date + datetime.timedelta(days=profile.payment_term_days)


@dataclass
class InvoiceSettlementStatus:
    document_id: int
    total_amount: decimal.Decimal
    settled_amount: decimal.Decimal
    remaining_amount: decimal.Decimal
    due_date: datetime.date | None

    @property
    def is_fully_settled(self) -> bool:
        return self.remaining_amount <= _ZERO


def _settled_amount(session, document_id: int) -> decimal.Decimal:
    return session.scalar(
        select(func.coalesce(func.sum(InvoiceSettlement.amount), 0)).where(
            InvoiceSettlement.invoice_document_id == document_id
        )
    ) or _ZERO


def get_invoice_settlement_status(document_id: int, company_id: int) -> InvoiceSettlementStatus:
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        settled = _settled_amount(session, document_id)
        return InvoiceSettlementStatus(
            document_id=document_id, total_amount=doc.total_amount, settled_amount=settled,
            remaining_amount=doc.total_amount - settled, due_date=doc.due_date,
        )


def list_unsettled_invoices(company_id: int, document_type_code: str | None = None) -> list[InvoiceSettlementStatus]:
    """طبقِ درخواستِ صریح: فهرستِ فاکتورهایِ ثبت‌شده که هنوز به‌طورِ کامل
    تسویه نشده‌اند -- برایِ صفحه‌یِ «فاکتورهایِ تسویه‌نشده» و ورودیِ
    صفحه‌یِ «مدیریتِ تسویه». عمداً فقط POSTED (نه CORRECTED) -- فاکتورِ
    اصلاح‌شده دیگر مبلغِ معتبر ندارد؛ فاکتورِ *جایگزین*ِ آن (که خودش POSTED
    است) همان است که باید تسویه شود."""
    with new_session() as session:
        stmt = select(CommercialDocument).where(
            CommercialDocument.company_id == company_id,
            CommercialDocument.status_code == "POSTED",
        )
        if document_type_code:
            stmt = stmt.where(CommercialDocument.document_type_code == document_type_code)
        else:
            stmt = stmt.where(CommercialDocument.document_type_code.in_(_INVOICE_TYPES))
        docs = session.scalars(stmt.order_by(CommercialDocument.document_id.desc())).all()
        result = []
        for doc in docs:
            settled = _settled_amount(session, doc.document_id)
            remaining = doc.total_amount - settled
            if remaining > _ZERO:
                result.append(InvoiceSettlementStatus(
                    document_id=doc.document_id, total_amount=doc.total_amount, settled_amount=settled,
                    remaining_amount=remaining, due_date=doc.due_date,
                ))
        return result


def list_invoices_due_soon(company_id: int) -> list[InvoiceSettlementStatus]:
    """طبقِ درخواستِ صریح («آپشنی که N روز مانده به موعدِ تسویه آلارم
    بدهد»): فقط اگر آلارم برایِ این شرکت فعال باشد، فاکتورهایِ
    تسویه‌نشده‌ای که سررسیدشان ظرفِ alarm_days_before روزِ آینده است (یا
    گذشته -- معوقه) را برمی‌گرداند."""
    settings = get_alarm_settings(company_id)
    if not settings.is_enabled or settings.alarm_days_before <= 0:
        return []
    threshold = datetime.date.today() + datetime.timedelta(days=settings.alarm_days_before)
    return [
        status for status in list_unsettled_invoices(company_id)
        if status.due_date is not None and status.due_date <= threshold
    ]


def list_settlements_for_invoice(document_id: int, company_id: int) -> list[InvoiceSettlement]:
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        return list(session.scalars(
            select(InvoiceSettlement).where(InvoiceSettlement.invoice_document_id == document_id)
            .order_by(InvoiceSettlement.settlement_date.desc(), InvoiceSettlement.settlement_id.desc())
        ))


def list_settlements_for_journal_entry(journal_entry_id: int, company_id: int) -> list[InvoiceSettlement]:
    with new_session() as session:
        je = session.get(JournalEntry, journal_entry_id)
        if je is None or je.company_id != company_id:
            raise ValueError("سندِ حسابداری نامعتبر است.")
        return list(session.scalars(
            select(InvoiceSettlement).where(InvoiceSettlement.journal_entry_id == journal_entry_id)
            .order_by(InvoiceSettlement.settlement_id.desc())
        ))


def allocate_settlement(
    company_id: int, invoice_document_id: int, journal_entry_id: int | None, settlement_date: datetime.date,
    amount: decimal.Decimal, created_by_user_id: int, reference_no: str | None = None, description: str | None = None,
) -> int:
    """طبقِ درخواستِ صریح: تخصیصِ (بخشی از) یک دریافت/پرداختِ ثبت‌شده به یک
    فاکتور -- تسویه‌یِ جزئی مجاز است (چند بار روی یک فاکتور)، اما مبلغِ
    هرباره نمی‌تواند از مانده‌یِ فاکتور بیشتر باشد."""
    if amount <= _ZERO:
        raise ValueError("مبلغِ تسویه باید مثبت باشد.")
    with new_session() as session:
        doc = session.get(CommercialDocument, invoice_document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("فاکتور نامعتبر است.")
        if doc.document_type_code not in _INVOICE_TYPES:
            raise ValueError("تسویه فقط برایِ فاکتورِ خرید/فروش ممکن است.")
        if doc.status_code != "POSTED":
            raise ValueError("فقط فاکتورِ ثبتِ‌نهایی‌شده (و نه اصلاح‌شده/لغوشده) قابلِ‌تسویه است.")
        if journal_entry_id is not None:
            je = session.get(JournalEntry, journal_entry_id)
            if je is None or je.company_id != company_id:
                raise ValueError("سندِ حسابداریِ دریافت/پرداخت نامعتبر است.")
        settled = _settled_amount(session, invoice_document_id)
        remaining = doc.total_amount - settled
        if amount > remaining:
            raise ValueError(f"مبلغِ تسویه از مانده‌یِ فاکتور ({remaining}) بیشتر است.")
        settlement = InvoiceSettlement(
            company_id=company_id, invoice_document_id=invoice_document_id, journal_entry_id=journal_entry_id,
            settlement_date=settlement_date, amount=amount, reference_no=(reference_no or None),
            description=(description or None), created_by_user_id=created_by_user_id,
        )
        session.add(settlement)
        session.commit()
        return settlement.settlement_id


def remove_settlement(settlement_id: int, company_id: int) -> None:
    with new_session() as session:
        settlement = session.get(InvoiceSettlement, settlement_id)
        if settlement is None or settlement.company_id != company_id:
            raise ValueError("تسویه نامعتبر است.")
        session.delete(settlement)
        session.commit()


def get_alarm_settings(company_id: int) -> SettlementAlarmSettings:
    with new_session() as session:
        settings = session.get(SettlementAlarmSettings, company_id)
        if settings is None:
            return SettlementAlarmSettings(company_id=company_id, is_enabled=False, alarm_days_before=2)
        session.expunge(settings)
        return settings


def set_alarm_settings(company_id: int, is_enabled: bool, alarm_days_before: int) -> None:
    if alarm_days_before < 0:
        raise ValueError("تعدادِ روز نمی‌تواند منفی باشد.")
    with new_session() as session:
        settings = session.get(SettlementAlarmSettings, company_id)
        if settings is None:
            session.add(SettlementAlarmSettings(
                company_id=company_id, is_enabled=is_enabled, alarm_days_before=alarm_days_before,
            ))
        else:
            settings.is_enabled = is_enabled
            settings.alarm_days_before = alarm_days_before
        session.commit()
