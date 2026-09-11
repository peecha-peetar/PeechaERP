"""بهایِ تمام‌شدهٔ وارداتی و ریبیتِ تامین‌کننده (مرحلهٔ ۴)."""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.commercial import (
    CommercialDocument,
    LandedCostAllocation,
    VendorRebateAccrual,
    VendorRebateAgreement,
    VendorRebateTier,
)
from peecha.services import journal_entries as je_service

_ZERO = decimal.Decimal("0")
_Q2 = decimal.Decimal("0.01")


def _money(value: decimal.Decimal) -> decimal.Decimal:
    return value.quantize(_Q2, rounding=decimal.ROUND_HALF_UP)


# ---------------------------------------------------------------------
# هزینه‌هایِ جانبیِ خرید (تسهیمِ ترخیص/گمرک/هزینه‌هایِ ارزیِ دیگر)
# ---------------------------------------------------------------------
# طبقِ درخواستِ صریح («فرمِ تسهیمِ هزینه رویِ فاکتورِ خرید — مبلغ + حسابِ
# معین و تفصیلیِ بستانکار برایِ هر ردیف»): برخلافِ نسخهٔ قبلی (که فقط یک
# دسته‌بندیِ ثابت داشت و هیچ اثرِ حسابداری‌ای تولید نمی‌کرد)، هر ردیفِ
# هزینه حالا یک حسابِ آزادانه دارد که با Postِ فاکتور بستانکار می‌شود —
# تسهیمِ خودِ هزینه‌ها رویِ ردیف‌هایِ فاکتور (متناسب با ارزش) و ساختِ
# ردیف‌هایِ اعتباریِ سندِ حسابداری، هردو درونِ commercial_documents.
# post_document انجام می‌شود (همراهِ خودِ سندِ فاکتور، طبقِ تصمیمِ صریح).
def add_landed_cost_line(
    purchase_invoice_document_id: int, amount: decimal.Decimal, credit_account_id: int,
    credit_detail_account_id: int | None = None, notes: str | None = None,
) -> int:
    if amount <= 0:
        raise ValueError("مبلغ باید بزرگ‌تر از صفر باشد.")
    with new_session() as session:
        doc = session.get(CommercialDocument, purchase_invoice_document_id)
        if doc is None or doc.document_type_code != "PURCHASE_INVOICE":
            raise ValueError("فقط رویِ فاکتورِ خرید قابلِ‌ثبت است.")
        if doc.status_code != "DRAFT":
            raise ValueError("پسِ Post، هزینه‌هایِ جانبیِ خرید فقط از طریقِ اصلاحیه قابلِ‌تغییر است.")
        row = LandedCostAllocation(
            purchase_invoice_document_id=purchase_invoice_document_id, amount=amount,
            credit_account_id=credit_account_id, credit_detail_account_id=credit_detail_account_id, notes=notes,
        )
        session.add(row)
        session.commit()
        return row.allocation_id


def list_landed_cost_allocations(purchase_invoice_document_id: int) -> list[LandedCostAllocation]:
    with new_session() as session:
        return list(session.scalars(select(LandedCostAllocation).where(LandedCostAllocation.purchase_invoice_document_id == purchase_invoice_document_id)))


def delete_landed_cost_line(allocation_id: int, company_id: int) -> None:
    with new_session() as session:
        row = session.get(LandedCostAllocation, allocation_id)
        if row is None:
            raise ValueError("ردیف نامعتبر است.")
        doc = session.get(CommercialDocument, row.purchase_invoice_document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        if doc.status_code != "DRAFT":
            raise ValueError("پسِ Post، هزینه‌هایِ جانبیِ خرید فقط از طریقِ اصلاحیه قابلِ‌تغییر است.")
        session.delete(row)
        session.commit()


# ---------------------------------------------------------------------
# ریبیتِ تامین‌کننده
# ---------------------------------------------------------------------
def create_rebate_agreement(supplier_detail_account_id: int, rebate_basis_code: str, valid_from: datetime.date, item_id: int | None = None, valid_to: datetime.date | None = None) -> int:
    if rebate_basis_code not in ("FLAT_PERCENT", "VOLUME_TIER"):
        raise ValueError("مبنایِ ریبیت نامعتبر است.")
    with new_session() as session:
        row = VendorRebateAgreement(supplier_detail_account_id=supplier_detail_account_id, item_id=item_id, rebate_basis_code=rebate_basis_code, valid_from=valid_from, valid_to=valid_to)
        session.add(row)
        session.commit()
        return row.agreement_id


def list_rebate_agreements(company_id: int) -> list[VendorRebateAgreement]:
    with new_session() as session:
        stmt = (
            select(VendorRebateAgreement)
            .join(DetailAccount, VendorRebateAgreement.supplier_detail_account_id == DetailAccount.detail_account_id)
            .where(DetailAccount.company_id == company_id)
            .order_by(VendorRebateAgreement.agreement_id.desc())
        )
        return list(session.scalars(stmt))


def list_rebate_tiers(agreement_id: int) -> list[VendorRebateTier]:
    with new_session() as session:
        return list(session.scalars(select(VendorRebateTier).where(VendorRebateTier.agreement_id == agreement_id)))


def add_rebate_tier(agreement_id: int, min_purchase_amount: decimal.Decimal, rebate_percent: decimal.Decimal) -> int:
    with new_session() as session:
        agreement = session.get(VendorRebateAgreement, agreement_id)
        if agreement is None:
            raise ValueError("قراردادِ ریبیت نامعتبر است.")
        row = VendorRebateTier(agreement_id=agreement_id, min_purchase_amount=min_purchase_amount, rebate_percent=rebate_percent)
        session.add(row)
        session.commit()
        return row.tier_id


def accrue_rebate_for_invoice(purchase_invoice_document_id: int, company_id: int, period_from: datetime.date, period_to: datetime.date) -> None:
    """پسِ Postِ فاکتورِ خرید فراخوانی شود؛ فقط تخمین می‌سازد/به‌روزرسانی
    می‌کند — هرگز رویِ حساب‌ها اثر نمی‌گذارد (مرحلهٔ ۴، بخشِ ۴)."""
    with new_session() as session:
        doc = session.get(CommercialDocument, purchase_invoice_document_id)
        if doc is None or doc.status_code != "POSTED":
            raise ValueError("فقط فاکتورِ Postشده قابلِ‌محاسبهٔ ریبیت است.")
        agreements = session.scalars(
            select(VendorRebateAgreement).where(
                VendorRebateAgreement.supplier_detail_account_id == doc.counterparty_detail_account_id,
                VendorRebateAgreement.status_code == "ACTIVE",
            )
        ).all()
        for agreement in agreements:
            rebate_percent = _ZERO
            if agreement.rebate_basis_code == "FLAT_PERCENT":
                tiers = session.scalars(select(VendorRebateTier).where(VendorRebateTier.agreement_id == agreement.agreement_id)).all()
                rebate_percent = tiers[0].rebate_percent if tiers else _ZERO
            else:
                tier = session.scalar(
                    select(VendorRebateTier)
                    .where(VendorRebateTier.agreement_id == agreement.agreement_id, VendorRebateTier.min_purchase_amount <= doc.total_amount)
                    .order_by(VendorRebateTier.min_purchase_amount.desc())
                )
                rebate_percent = tier.rebate_percent if tier is not None else _ZERO
            if rebate_percent <= 0:
                continue
            accrual = session.scalar(
                select(VendorRebateAccrual).where(
                    VendorRebateAccrual.agreement_id == agreement.agreement_id, VendorRebateAccrual.period_from == period_from,
                    VendorRebateAccrual.period_to == period_to, VendorRebateAccrual.status_code == "ACCRUING",
                )
            )
            increment = _money(doc.total_amount * rebate_percent / 100)
            if accrual is None:
                session.add(VendorRebateAccrual(agreement_id=agreement.agreement_id, period_from=period_from, period_to=period_to, accrued_amount=increment))
            else:
                accrual.accrued_amount += increment
        session.commit()


def settle_rebate_accrual(accrual_id: int, company_id: int, posted_by_user_id: int, rebate_receivable_account_id: int, purchase_discount_account_id: int) -> int:
    with new_session() as session:
        accrual = session.get(VendorRebateAccrual, accrual_id)
        if accrual is None or accrual.status_code != "ACCRUING":
            raise ValueError("فقط تعهدِ درحالِ‌تجمیع قابلِ‌تسویه است.")
        amount = accrual.accrued_amount

    result = je_service.create_journal_entry(
        company_id, posted_by_user_id, datetime.date.today(), "تسویهٔ ریبیتِ تامین‌کننده",
        [
            je_service.LineInput(account_id=rebate_receivable_account_id, description="تسویهٔ ریبیتِ تامین‌کننده", debit=amount, credit=_ZERO),
            je_service.LineInput(account_id=purchase_discount_account_id, description="تسویهٔ ریبیتِ تامین‌کننده", debit=_ZERO, credit=amount),
        ],
        entry_type_code="COMMERCIAL",
    )
    with new_session() as session:
        accrual = session.get(VendorRebateAccrual, accrual_id)
        accrual.status_code = "SETTLED"
        accrual.settlement_journal_entry_id = result.journal_entry_id
        session.commit()
    return result.journal_entry_id


def list_rebate_accruals(agreement_id: int | None = None, status_code: str | None = None) -> list[VendorRebateAccrual]:
    with new_session() as session:
        stmt = select(VendorRebateAccrual)
        if agreement_id is not None:
            stmt = stmt.where(VendorRebateAccrual.agreement_id == agreement_id)
        if status_code is not None:
            stmt = stmt.where(VendorRebateAccrual.status_code == status_code)
        return list(session.scalars(stmt))
