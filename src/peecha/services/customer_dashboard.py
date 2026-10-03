"""داشبوردِ معلقِ مشتری (Customer 360) -- طبقِ درخواستِ صریحِ کاربر برایِ
حرفه‌ای‌سازیِ فروشِ تلفنی: «با زدنِ اطلاعاتِ مشتری خلاصه‌اطلاعات و یک
داشبوردِ معلق از مشتری نشان بده... حتی گزارشِ آماری از فروش و چک‌ها و
فروش بر اساسِ کالا و ماه به‌صورتِ نموداری و شماره‌تماس». این ماژول فقط
تجمیع/فرمتِ داده است -- هیچ منطقِ محاسباتیِ تازه‌ای ندارد: مانده از
treasury.get_counterparty_balance، روندِ ماهانه از
dashboard.commercial_amount_per_month (با فیلترِ تازه‌یِ counterparty)،
و چک‌ها از treasury.list_received_checks/list_issued_checks (هم با
همان فیلترِ تازه) -- فقط جمعِ فروش به‌تفکیکِ کالا این‌جا برایِ اولین‌بار
نوشته شده، چون هیچ‌جایِ دیگری چنین تجمیعی وجود نداشت."""

from __future__ import annotations

import decimal
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine
from peecha.services import dashboard as dashboard_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import treasury as treasury_service

_ZERO = decimal.Decimal(0)


@dataclass
class CustomerContactInfo:
    customer_detail_account_id: int
    code: str
    name: str
    phone: str | None
    mobile: str | None
    address: str | None
    balance_amount: decimal.Decimal
    balance_nature: str


def get_contact_info(company_id: int, customer_detail_account_id: int) -> CustomerContactInfo | None:
    customer = next(
        (c for c in dimensions_service.list_customers(company_id) if c["detail_account_id"] == customer_detail_account_id),
        None,
    )
    if customer is None:
        return None
    balance_amount, balance_nature = treasury_service.get_counterparty_balance(company_id, customer_detail_account_id)
    return CustomerContactInfo(
        customer_detail_account_id=customer_detail_account_id,
        code=customer["code"],
        name=customer["name"] or "",
        phone=customer.get("phone"),
        mobile=customer.get("mobile"),
        address=customer.get("address"),
        balance_amount=balance_amount,
        balance_nature=balance_nature,
    )


def sales_by_month(
    company_id: int, customer_detail_account_id: int, months: int = 6,
) -> tuple[list[str], list[decimal.Decimal]]:
    return dashboard_service.commercial_amount_per_month(
        company_id, "SALES_INVOICE", months=months, counterparty_detail_account_id=customer_detail_account_id,
    )


@dataclass
class ItemSalesRow:
    item_id: int
    item_name: str
    total_quantity: decimal.Decimal
    total_amount: decimal.Decimal


def sales_by_item(company_id: int, customer_detail_account_id: int, limit: int = 10) -> list[ItemSalesRow]:
    """جمعِ فروشِ ثبت‌نهایی‌شده به تفکیکِ کالا برایِ این مشتری -- بدونِ
    محدودیتِ بازه‌یِ زمانی (تصویرِ کلیِ سابقه‌یِ خرید)، مرتب‌شده نزولی بر
    اساسِ مبلغ و فقط N کالایِ برتر (تا نمودار شلوغ نشود)."""
    amount_sum = func.coalesce(func.sum(CommercialDocumentLine.line_total), 0)
    with new_session() as session:
        stmt = (
            select(CommercialDocumentLine.item_id, func.coalesce(func.sum(CommercialDocumentLine.quantity_base), 0), amount_sum)
            .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
            .where(
                CommercialDocument.company_id == company_id,
                CommercialDocument.document_type_code == "SALES_INVOICE",
                CommercialDocument.status_code == "POSTED",
                CommercialDocument.counterparty_detail_account_id == customer_detail_account_id,
            )
            .group_by(CommercialDocumentLine.item_id)
            .order_by(amount_sum.desc())
            .limit(limit)
        )
        rows = session.execute(stmt).all()

    result: list[ItemSalesRow] = []
    for item_id, qty, amount in rows:
        item = catalog_service.get_item(item_id)
        # طبقِ ساختارِ inv.items («کد/نامِ کالا رویِ acc.detail_accounts
        # است، نه خودِ items») -- نامِ نمایشی از رویِ همان تفصیلی خوانده
        # می‌شود.
        item_name = dimensions_service.get_detail_account_label(item.item_detail_account_id) if item else str(item_id)
        result.append(ItemSalesRow(item_id, item_name, decimal.Decimal(qty), decimal.Decimal(amount)))
    return result


@dataclass
class CustomerChequesSummary:
    received: list  # treasury_service.ReceivedCheckRow
    issued: list  # treasury_service.IssuedCheckRow


def get_cheques(company_id: int, customer_detail_account_id: int) -> CustomerChequesSummary:
    return CustomerChequesSummary(
        received=treasury_service.list_received_checks(company_id, counterparty_detail_account_id=customer_detail_account_id),
        issued=treasury_service.list_issued_checks(company_id, counterparty_detail_account_id=customer_detail_account_id),
    )
