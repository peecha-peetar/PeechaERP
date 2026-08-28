"""قیمت‌گذاری و تخفیف (مرحلهٔ ۶): زنجیرهٔ قطعیِ پنج‌گامی —
قرارداد → فهرستِ قیمتِ پلکانی → تخفیفِ قاعده‌ای → کوپن/پروموشن →
محافظِ حاشیهٔ سود. هر ردیفِ هر سند، صرفِ‌نظر از کانال، از همین تابع
عبور می‌کند."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import (
    BundleComponent,
    BundleDefinition,
    Channel,
    Coupon,
    DiscountRule,
    DiscountRuleTier,
    PriceList,
    PriceListItem,
    PricingPolicy,
    Promotion,
)
from peecha.services import commercial_partners as partners_service

_ZERO = decimal.Decimal(0)


# ---------------------------------------------------------------------
# کانال (بُعدِ فروش، نه ماژول — مرحلهٔ ۲)
# ---------------------------------------------------------------------
def list_channels(company_id: int) -> list[Channel]:
    with new_session() as session:
        return list(session.scalars(select(Channel).where(Channel.company_id == company_id)))


def create_channel(
    company_id: int, channel_code: str, name: str, channel_type_code: str,
    default_price_list_id: int | None = None, default_warehouse_id: int | None = None,
) -> str:
    if channel_type_code not in ("POS", "WHOLESALE", "ONLINE", "AGENT", "MARKETPLACE"):
        raise ValueError("نوعِ کانال نامعتبر است.")
    with new_session() as session:
        row = Channel(
            company_id=company_id, channel_code=channel_code, name=name, channel_type_code=channel_type_code,
            default_price_list_id=default_price_list_id, default_warehouse_id=default_warehouse_id,
        )
        session.add(row)
        session.commit()
        return row.channel_code


# ---------------------------------------------------------------------
# فهرستِ قیمت
# ---------------------------------------------------------------------
def list_price_lists(company_id: int, price_list_type_code: str | None = None) -> list[PriceList]:
    with new_session() as session:
        stmt = select(PriceList).where(PriceList.company_id == company_id)
        if price_list_type_code:
            stmt = stmt.where(PriceList.price_list_type_code == price_list_type_code)
        return list(session.scalars(stmt))


def create_price_list(
    company_id: int, code: str, name: str, price_list_type_code: str, currency_id: int,
    valid_from: datetime.date, channel_code: str | None = None, valid_to: datetime.date | None = None,
) -> int:
    if price_list_type_code not in ("SALES", "PURCHASE"):
        raise ValueError("نوعِ فهرستِ قیمت نامعتبر است.")
    with new_session() as session:
        row = PriceList(
            company_id=company_id, code=code, name=name, price_list_type_code=price_list_type_code,
            currency_id=currency_id, channel_code=channel_code, valid_from=valid_from, valid_to=valid_to,
        )
        session.add(row)
        session.commit()
        return row.price_list_id


def set_price_list_item(price_list_id: int, item_id: int, uom_id: int, unit_price: decimal.Decimal, min_quantity: decimal.Decimal = decimal.Decimal(1)) -> int:
    with new_session() as session:
        row = session.scalar(
            select(PriceListItem).where(
                PriceListItem.price_list_id == price_list_id, PriceListItem.item_id == item_id,
                PriceListItem.uom_id == uom_id, PriceListItem.min_quantity == min_quantity,
            )
        )
        if row is None:
            row = PriceListItem(
                price_list_id=price_list_id, item_id=item_id, uom_id=uom_id, min_quantity=min_quantity,
                unit_price=unit_price,
            )
            session.add(row)
        else:
            row.unit_price = unit_price
        session.commit()
        return row.price_list_item_id


def list_price_list_items(price_list_id: int) -> list[PriceListItem]:
    with new_session() as session:
        return list(session.scalars(select(PriceListItem).where(PriceListItem.price_list_id == price_list_id)))


def _lookup_tiered_price(session, price_list_id: int, item_id: int, uom_id: int, quantity: decimal.Decimal) -> decimal.Decimal | None:
    row = session.scalar(
        select(PriceListItem)
        .where(
            PriceListItem.price_list_id == price_list_id, PriceListItem.item_id == item_id,
            PriceListItem.uom_id == uom_id, PriceListItem.min_quantity <= quantity,
        )
        .order_by(PriceListItem.min_quantity.desc())
    )
    return row.unit_price if row is not None else None


# ---------------------------------------------------------------------
# تخفیف/پروموشن/کوپن
# ---------------------------------------------------------------------
def list_discount_rules(company_id: int, active_only: bool = True) -> list[DiscountRule]:
    with new_session() as session:
        stmt = select(DiscountRule).where(DiscountRule.company_id == company_id)
        if active_only:
            stmt = stmt.where(DiscountRule.is_active.is_(True))
        return list(session.scalars(stmt.order_by(DiscountRule.priority)))


def create_discount_rule(
    company_id: int, code: str, name: str, discount_type_code: str, scope_type_code: str,
    priority: int = 100, is_stackable: bool = False, discount_value: decimal.Decimal | None = None,
    scope_ref_id: int | None = None, valid_from: datetime.date | None = None, valid_to: datetime.date | None = None,
) -> int:
    with new_session() as session:
        row = DiscountRule(
            company_id=company_id, code=code, name=name, discount_type_code=discount_type_code,
            scope_type_code=scope_type_code, scope_ref_id=scope_ref_id, discount_value=discount_value,
            priority=priority, is_stackable=is_stackable, valid_from=valid_from or datetime.date.today(),
            valid_to=valid_to,
        )
        session.add(row)
        session.commit()
        return row.rule_id


def add_discount_rule_tier(rule_id: int, discount_value: decimal.Decimal, min_quantity: decimal.Decimal | None = None, min_amount: decimal.Decimal | None = None) -> int:
    if min_quantity is None and min_amount is None:
        raise ValueError("یکی از مقدارِ حداقل یا مبلغِ حداقل باید مشخص شود.")
    with new_session() as session:
        row = DiscountRuleTier(rule_id=rule_id, min_quantity=min_quantity, min_amount=min_amount, discount_value=discount_value)
        session.add(row)
        session.commit()
        return row.tier_id


def redeem_coupon(coupon_id: int, company_id: int) -> decimal.Decimal:
    """اعتبارسنجی + افزایشِ اتمیکِ used_count؛ مقدارِ تخفیف را برمی‌گرداند."""
    with new_session() as session:
        coupon = session.get(Coupon, coupon_id)
        if coupon is None or coupon.company_id != company_id:
            raise ValueError("کوپن نامعتبر است.")
        today = datetime.date.today()
        if coupon.valid_to is not None and coupon.valid_to < today:
            raise ValueError("کوپن منقضی شده است.")
        if coupon.valid_from > today:
            raise ValueError("کوپن هنوز فعال نشده است.")
        if coupon.used_count >= coupon.max_uses:
            raise ValueError("سقفِ استفاده از این کوپن پر شده است.")
        coupon.used_count += 1
        session.commit()
        return coupon.discount_value


# ---------------------------------------------------------------------
# محافظِ حاشیهٔ سود
# ---------------------------------------------------------------------
def get_pricing_policy(company_id: int) -> PricingPolicy | None:
    with new_session() as session:
        return session.scalar(select(PricingPolicy).where(PricingPolicy.company_id == company_id))


def set_pricing_policy(company_id: int, min_margin_percent_default: decimal.Decimal | None, below_margin_requires_approval: bool) -> None:
    with new_session() as session:
        row = session.scalar(select(PricingPolicy).where(PricingPolicy.company_id == company_id))
        if row is None:
            session.add(
                PricingPolicy(
                    company_id=company_id, min_margin_percent_default=min_margin_percent_default,
                    below_margin_requires_approval=below_margin_requires_approval,
                )
            )
        else:
            row.min_margin_percent_default = min_margin_percent_default
            row.below_margin_requires_approval = below_margin_requires_approval
        session.commit()


@dataclass
class MarginCheckResult:
    is_below_floor: bool
    margin_percent: decimal.Decimal | None
    requires_approval: bool


def check_margin_floor(company_id: int, unit_price: decimal.Decimal, unit_cost: decimal.Decimal) -> MarginCheckResult:
    policy = get_pricing_policy(company_id)
    if policy is None or policy.min_margin_percent_default is None or unit_price == 0:
        return MarginCheckResult(False, None, False)
    margin_percent = ((unit_price - unit_cost) / unit_price) * 100
    is_below = margin_percent < policy.min_margin_percent_default
    return MarginCheckResult(is_below, margin_percent, is_below and policy.below_margin_requires_approval)


# ---------------------------------------------------------------------
# زنجیرهٔ قیمت‌گذاری
# ---------------------------------------------------------------------
@dataclass
class ResolvedPrice:
    unit_price: decimal.Decimal
    source: str  # CONTRACT | PRICE_LIST | MANUAL
    discount_amount: decimal.Decimal = field(default=_ZERO)
    applied_discount_rule_id: int | None = None


def resolve_price(
    company_id: int, counterparty_detail_account_id: int, item_id: int, uom_id: int, quantity: decimal.Decimal,
    price_list_id: int | None, document_type_code: str, as_of_date: datetime.date | None = None,
) -> ResolvedPrice:
    as_of_date = as_of_date or datetime.date.today()
    contract_type = "SALES" if document_type_code.startswith("SALES") else "PURCHASE"

    contract_price = partners_service.get_active_contract_price(
        counterparty_detail_account_id, item_id, contract_type, as_of_date
    )
    if contract_price is not None:
        return ResolvedPrice(unit_price=contract_price, source="CONTRACT")

    if price_list_id is None:
        raise ValueError("فهرستِ قیمت مشخص نشده و قراردادِ فعالی هم وجود ندارد.")

    with new_session() as session:
        base_price = _lookup_tiered_price(session, price_list_id, item_id, uom_id, quantity)
        if base_price is None:
            raise ValueError("قیمتی برایِ این کالا در فهرستِ قیمتِ انتخاب‌شده تعریف نشده است.")

        best_rule = session.scalar(
            select(DiscountRule)
            .where(
                DiscountRule.company_id == company_id, DiscountRule.is_active.is_(True),
                DiscountRule.scope_type_code == "ALL", DiscountRule.valid_from <= as_of_date,
                (DiscountRule.valid_to.is_(None)) | (DiscountRule.valid_to >= as_of_date),
            )
            .order_by(DiscountRule.priority)
        )
        discount_amount = _ZERO
        applied_rule_id = None
        if best_rule is not None:
            if best_rule.discount_type_code == "PERCENT" and best_rule.discount_value is not None:
                discount_amount = (base_price * quantity) * (best_rule.discount_value / 100)
            elif best_rule.discount_type_code == "AMOUNT" and best_rule.discount_value is not None:
                discount_amount = best_rule.discount_value * quantity
            elif best_rule.discount_type_code == "TIERED":
                tier = session.scalar(
                    select(DiscountRuleTier)
                    .where(DiscountRuleTier.rule_id == best_rule.rule_id, DiscountRuleTier.min_quantity <= quantity)
                    .order_by(DiscountRuleTier.min_quantity.desc())
                )
                if tier is not None:
                    discount_amount = (base_price * quantity) * (tier.discount_value / 100)
            applied_rule_id = best_rule.rule_id

    return ResolvedPrice(unit_price=base_price, source="PRICE_LIST", discount_amount=discount_amount, applied_discount_rule_id=applied_rule_id)


# ---------------------------------------------------------------------
# فروشِ ترکیبی (CPQِ سبک)
# ---------------------------------------------------------------------
def list_bundle_components(bundle_item_id: int) -> list[BundleComponent]:
    with new_session() as session:
        bundle = session.scalar(select(BundleDefinition).where(BundleDefinition.bundle_item_id == bundle_item_id))
        if bundle is None:
            return []
        return list(session.scalars(select(BundleComponent).where(BundleComponent.bundle_id == bundle.bundle_id)))


def create_bundle(company_id: int, bundle_item_id: int, name: str) -> int:
    with new_session() as session:
        row = BundleDefinition(company_id=company_id, bundle_item_id=bundle_item_id, name=name)
        session.add(row)
        session.commit()
        return row.bundle_id


def add_bundle_component(bundle_id: int, component_item_id: int, quantity_per_bundle: decimal.Decimal, price_allocation_percent: decimal.Decimal) -> int:
    with new_session() as session:
        row = BundleComponent(
            bundle_id=bundle_id, component_item_id=component_item_id, quantity_per_bundle=quantity_per_bundle,
            price_allocation_percent=price_allocation_percent,
        )
        session.add(row)
        session.commit()
        return row.bundle_component_id
