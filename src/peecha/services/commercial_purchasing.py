"""بهایِ تمام‌شدهٔ وارداتی و ریبیتِ تامین‌کننده (مرحلهٔ ۴)."""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.commercial import (
    CommercialDocument,
    CommercialDocumentLine,
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
# بهایِ تمام‌شدهٔ وارداتی
# ---------------------------------------------------------------------
def add_landed_cost_allocation(purchase_invoice_document_id: int, cost_type_code: str, amount: decimal.Decimal, allocation_method_code: str, notes: str | None = None) -> int:
    if cost_type_code not in ("FREIGHT", "CUSTOMS", "INSURANCE", "HANDLING", "OTHER"):
        raise ValueError("نوعِ هزینه نامعتبر است.")
    if allocation_method_code not in ("BY_VALUE", "BY_QUANTITY", "BY_WEIGHT"):
        raise ValueError("روشِ تسهیم نامعتبر است.")
    with new_session() as session:
        doc = session.get(CommercialDocument, purchase_invoice_document_id)
        if doc is None or doc.document_type_code != "PURCHASE_INVOICE":
            raise ValueError("فقط رویِ فاکتورِ خرید قابلِ‌ثبت است.")
        if doc.status_code != "DRAFT":
            raise ValueError("پسِ Post، هزینهٔ تمام‌شدهٔ وارداتی فقط از طریقِ اصلاحیه قابلِ‌تغییر است.")
        row = LandedCostAllocation(purchase_invoice_document_id=purchase_invoice_document_id, cost_type_code=cost_type_code, amount=amount, allocation_method_code=allocation_method_code, notes=notes)
        session.add(row)
        session.commit()
        return row.allocation_id


def list_landed_cost_allocations(purchase_invoice_document_id: int) -> list[LandedCostAllocation]:
    with new_session() as session:
        return list(session.scalars(select(LandedCostAllocation).where(LandedCostAllocation.purchase_invoice_document_id == purchase_invoice_document_id)))


def apply_landed_costs(purchase_invoice_document_id: int, company_id: int) -> None:
    """تناسبیِ هر هزینه بینِ ردیف‌هایِ فاکتور توزیع و مستقیماً به
    unit_price هر ردیف اضافه می‌شود — پیش از Confirm/Post فراخوانی شود
    تا بهایِ واحدِ ورودی به موتورِ هزینه‌یابیِ انبار شاملِ این سهم باشد
    (مرحلهٔ ۴، بخشِ ۲)."""
    with new_session() as session:
        doc = session.get(CommercialDocument, purchase_invoice_document_id)
        if doc is None or doc.company_id != company_id or doc.document_type_code != "PURCHASE_INVOICE":
            raise ValueError("سند نامعتبر است.")
        if doc.status_code != "DRAFT":
            raise ValueError("فقط سندِ پیش‌نویس قابلِ‌اعمالِ هزینهٔ تمام‌شده است.")
        allocations = session.scalars(select(LandedCostAllocation).where(LandedCostAllocation.purchase_invoice_document_id == purchase_invoice_document_id)).all()
        if not allocations:
            return
        lines = session.scalars(select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == purchase_invoice_document_id)).all()
        if not lines:
            raise ValueError("سند حداقل باید یک ردیف داشته باشد.")
        total_value = sum((ln.quantity * ln.unit_price for ln in lines), _ZERO)
        total_qty = sum((ln.quantity for ln in lines), _ZERO)

        for allocation in allocations:
            for line in lines:
                if allocation.allocation_method_code == "BY_VALUE" and total_value > 0:
                    share = (line.quantity * line.unit_price) / total_value
                elif allocation.allocation_method_code in ("BY_QUANTITY", "BY_WEIGHT") and total_qty > 0:
                    # BY_WEIGHT بدونِ وزنِ کالا در این نسخه به BY_QUANTITY تنزل می‌کند.
                    share = line.quantity / total_qty
                else:
                    share = _ZERO
                extra_per_unit = _money(allocation.amount * share / line.quantity) if line.quantity else _ZERO
                line.unit_price = line.unit_price + extra_per_unit
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
