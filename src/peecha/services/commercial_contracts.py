"""قرارداد، کمیسیون، حمل (مرحلهٔ ۲)."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import (
    CommercialContract,
    CommercialDocumentLine,
    CommissionEntry,
    CommissionRule,
    Shipment,
)

_ZERO = decimal.Decimal(0)


def list_contracts(company_id: int, counterparty_detail_account_id: int | None = None) -> list[CommercialContract]:
    with new_session() as session:
        stmt = select(CommercialContract).where(CommercialContract.company_id == company_id)
        if counterparty_detail_account_id is not None:
            stmt = stmt.where(CommercialContract.counterparty_detail_account_id == counterparty_detail_account_id)
        return list(session.scalars(stmt))


def create_contract(
    company_id: int, contract_type_code: str, counterparty_detail_account_id: int, valid_from: datetime.date,
    item_id: int | None = None, committed_quantity: decimal.Decimal | None = None,
    contract_price: decimal.Decimal | None = None, valid_to: datetime.date | None = None,
) -> int:
    if contract_type_code not in ("SALES", "PURCHASE"):
        raise ValueError("نوعِ قرارداد نامعتبر است.")
    with new_session() as session:
        row = CommercialContract(
            company_id=company_id, contract_type_code=contract_type_code,
            counterparty_detail_account_id=counterparty_detail_account_id, item_id=item_id,
            committed_quantity=committed_quantity, contract_price=contract_price, valid_from=valid_from,
            valid_to=valid_to,
        )
        session.add(row)
        session.commit()
        return row.contract_id


def cancel_contract(contract_id: int, company_id: int) -> None:
    with new_session() as session:
        row = session.get(CommercialContract, contract_id)
        if row is None or row.company_id != company_id:
            raise ValueError("قرارداد نامعتبر است.")
        row.status_code = "CANCELLED"
        session.commit()


# ---------------------------------------------------------------------
# کمیسیون
# ---------------------------------------------------------------------
def list_commission_rules(company_id: int) -> list[CommissionRule]:
    with new_session() as session:
        return list(session.scalars(select(CommissionRule).where(CommissionRule.company_id == company_id)))


def create_commission_rule(company_id: int, code: str, name: str, basis_code: str, rate_value: decimal.Decimal | None = None) -> int:
    if basis_code not in ("PERCENT_OF_TOTAL", "PERCENT_OF_MARGIN", "FLAT_PER_UNIT", "TIERED"):
        raise ValueError("مبنایِ کمیسیون نامعتبر است.")
    with new_session() as session:
        row = CommissionRule(company_id=company_id, code=code, name=name, basis_code=basis_code, rate_value=rate_value)
        session.add(row)
        session.commit()
        return row.rule_id


def create_commission_entry_for_line(
    document_line_id: int, rep_detail_account_id: int, rule_id: int, base_amount: decimal.Decimal
) -> int:
    with new_session() as session:
        rule = session.get(CommissionRule, rule_id)
        if rule is None:
            raise ValueError("قاعدهٔ کمیسیون نامعتبر است.")
        commission_amount = _ZERO
        if rule.basis_code in ("PERCENT_OF_TOTAL", "PERCENT_OF_MARGIN") and rule.rate_value is not None:
            commission_amount = base_amount * (rule.rate_value / 100)
        elif rule.basis_code == "FLAT_PER_UNIT" and rule.rate_value is not None:
            line = session.get(CommercialDocumentLine, document_line_id)
            commission_amount = rule.rate_value * (line.quantity if line is not None else 1)
        row = CommissionEntry(
            document_line_id=document_line_id, rep_detail_account_id=rep_detail_account_id, rule_id=rule_id,
            base_amount=base_amount, commission_amount=commission_amount,
        )
        session.add(row)
        session.commit()
        return row.entry_id


def reverse_commission_entries_for_document(document_id: int) -> None:
    """طبقِ مرحلهٔ ۵، بخشِ ۶: برگشتِ فاکتور، کمیسیونِ متناظر را REVERSED
    می‌کند."""
    with new_session() as session:
        entries = session.scalars(
            select(CommissionEntry)
            .join(CommercialDocumentLine, CommercialDocumentLine.line_id == CommissionEntry.document_line_id)
            .where(CommercialDocumentLine.document_id == document_id)
        ).all()
        for entry in entries:
            entry.status_code = "REVERSED"
        session.commit()


def list_commission_entries(rep_detail_account_id: int | None = None, status_code: str | None = None) -> list[CommissionEntry]:
    with new_session() as session:
        stmt = select(CommissionEntry)
        if rep_detail_account_id is not None:
            stmt = stmt.where(CommissionEntry.rep_detail_account_id == rep_detail_account_id)
        if status_code is not None:
            stmt = stmt.where(CommissionEntry.status_code == status_code)
        return list(session.scalars(stmt))


# ---------------------------------------------------------------------
# حمل
# ---------------------------------------------------------------------
def create_shipment(
    document_id: int, shipping_method_code: str, carrier_name: str | None = None, tracking_no: str | None = None,
    shipping_cost: decimal.Decimal = _ZERO, billed_to_customer: bool = False,
) -> int:
    if shipping_method_code not in ("PICKUP", "COURIER", "POST", "FREIGHT"):
        raise ValueError("روشِ حمل نامعتبر است.")
    with new_session() as session:
        row = Shipment(
            document_id=document_id, carrier_name=carrier_name, tracking_no=tracking_no,
            shipping_method_code=shipping_method_code, shipping_cost=shipping_cost, billed_to_customer=billed_to_customer,
        )
        session.add(row)
        session.commit()
        return row.shipment_id


def mark_shipment_shipped(shipment_id: int) -> None:
    with new_session() as session:
        row = session.get(Shipment, shipment_id)
        if row is None:
            raise ValueError("حمل نامعتبر است.")
        row.status_code = "SHIPPED"
        row.shipped_at = datetime.datetime.now()
        session.commit()


def mark_shipment_delivered(shipment_id: int) -> None:
    with new_session() as session:
        row = session.get(Shipment, shipment_id)
        if row is None:
            raise ValueError("حمل نامعتبر است.")
        row.status_code = "DELIVERED"
        row.delivered_at = datetime.datetime.now()
        session.commit()
