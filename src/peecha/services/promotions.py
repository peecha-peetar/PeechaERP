"""پخشِ سرد/گرم -- R129، بخشِ موتورِ پروموشن. طبقِ طرحِ تاییدشده، در این
فاز فقط دیتامدل+محاسبهٔ مستقل ساخته می‌شود (قابلِ‌فراخوانی/تست بدونِ
وابستگی به فرمِ فاکتور)؛ اتصالِ آن به محاسبهٔ زندهٔ قیمتِ فاکتور
(commercial_documents.py) یک گامِ جداگانه و حساس است که در فازِ بعدی
به‌طورِ مستقل بررسی/تست می‌شود -- تا منطقِ تخفیف/مالياتِ فعلاً
تست‌شدهٔ فاکتور دوباره در جایی دیگر بازنویسی/دست‌کاری نشود."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import PromotionRule

PROMOTION_TYPE_CODES = ("BUY_X_GET_Y", "THRESHOLD_DISCOUNT")


@dataclass
class PromotionRuleFields:
    promotion_type_code: str
    channel_type_code: str | None = None
    applies_to_item_id: int | None = None
    buy_quantity: decimal.Decimal | None = None
    get_quantity: decimal.Decimal | None = None
    get_item_id: int | None = None
    threshold_amount: decimal.Decimal | None = None
    discount_percent: decimal.Decimal | None = None
    valid_from: datetime.date | None = None
    valid_to: datetime.date | None = None


@dataclass
class PromotionRuleRow:
    promotion_rule_id: int
    code: str
    name: str
    is_active: bool
    fields: PromotionRuleFields


def _validate_fields(fields: PromotionRuleFields) -> None:
    if fields.promotion_type_code not in PROMOTION_TYPE_CODES:
        raise ValueError("نوعِ پروموشن نامعتبر است.")
    if fields.promotion_type_code == "BUY_X_GET_Y":
        if not fields.applies_to_item_id or not fields.buy_quantity or not fields.get_quantity:
            raise ValueError("برایِ «بخر و ببر»، کالا، تعدادِ خرید و تعدادِ هدیه الزامی است.")
        if fields.buy_quantity <= 0 or fields.get_quantity <= 0:
            raise ValueError("تعدادها باید بزرگ‌تر از صفر باشند.")
    if fields.promotion_type_code == "THRESHOLD_DISCOUNT":
        if not fields.threshold_amount or not fields.discount_percent:
            raise ValueError("برایِ تخفیفِ پلکانی، سقفِ مبلغ و درصدِ تخفیف الزامی است.")
        if fields.threshold_amount <= 0 or not (0 < fields.discount_percent <= 100):
            raise ValueError("سقفِ مبلغ باید مثبت و درصدِ تخفیف بینِ ۰ تا ۱۰۰ باشد.")
    if fields.valid_from and fields.valid_to and fields.valid_from > fields.valid_to:
        raise ValueError("تاریخِ شروع نمی‌تواند بعد از تاریخِ پایان باشد.")


def create_promotion_rule(company_id: int, code: str, name: str, fields: PromotionRuleFields) -> int:
    _validate_fields(fields)
    with new_session() as session:
        existing = session.scalar(select(PromotionRule).where(PromotionRule.company_id == company_id, PromotionRule.code == code))
        if existing is not None:
            raise ValueError("کدِ پروموشن تکراری است.")
        rule = PromotionRule(
            company_id=company_id, code=code.strip(), name=name.strip(), promotion_type_code=fields.promotion_type_code,
            channel_type_code=fields.channel_type_code, applies_to_item_id=fields.applies_to_item_id,
            buy_quantity=fields.buy_quantity, get_quantity=fields.get_quantity, get_item_id=fields.get_item_id,
            threshold_amount=fields.threshold_amount, discount_percent=fields.discount_percent,
            valid_from=fields.valid_from, valid_to=fields.valid_to,
        )
        session.add(rule)
        session.commit()
        return rule.promotion_rule_id


def update_promotion_rule(promotion_rule_id: int, company_id: int, name: str, is_active: bool, fields: PromotionRuleFields) -> None:
    _validate_fields(fields)
    with new_session() as session:
        rule = session.get(PromotionRule, promotion_rule_id)
        if rule is None or rule.company_id != company_id:
            raise ValueError("پروموشن نامعتبر است.")
        rule.name = name.strip()
        rule.is_active = is_active
        rule.promotion_type_code = fields.promotion_type_code
        rule.channel_type_code = fields.channel_type_code
        rule.applies_to_item_id = fields.applies_to_item_id
        rule.buy_quantity = fields.buy_quantity
        rule.get_quantity = fields.get_quantity
        rule.get_item_id = fields.get_item_id
        rule.threshold_amount = fields.threshold_amount
        rule.discount_percent = fields.discount_percent
        rule.valid_from = fields.valid_from
        rule.valid_to = fields.valid_to
        session.commit()


def delete_promotion_rule(promotion_rule_id: int, company_id: int) -> None:
    with new_session() as session:
        rule = session.get(PromotionRule, promotion_rule_id)
        if rule is None or rule.company_id != company_id:
            raise ValueError("پروموشن نامعتبر است.")
        session.delete(rule)
        session.commit()


def list_promotion_rules(company_id: int, active_only: bool = False) -> list[PromotionRuleRow]:
    with new_session() as session:
        stmt = select(PromotionRule).where(PromotionRule.company_id == company_id)
        if active_only:
            stmt = stmt.where(PromotionRule.is_active.is_(True))
        rows = session.scalars(stmt.order_by(PromotionRule.code)).all()
        return [
            PromotionRuleRow(
                r.promotion_rule_id, r.code, r.name, r.is_active,
                PromotionRuleFields(
                    r.promotion_type_code, r.channel_type_code, r.applies_to_item_id, r.buy_quantity, r.get_quantity,
                    r.get_item_id, r.threshold_amount, r.discount_percent, r.valid_from, r.valid_to,
                ),
            )
            for r in rows
        ]


@dataclass
class PromotionEffect:
    promotion_rule_id: int
    code: str
    name: str
    promotion_type_code: str
    free_item_id: int | None = None
    free_quantity: decimal.Decimal | None = None
    discount_amount: decimal.Decimal | None = None


def compute_applicable_promotions(
    company_id: int, channel_type_code: str | None, as_of_date: datetime.date,
    item_quantities: dict[int, decimal.Decimal], order_net_amount: decimal.Decimal,
) -> list[PromotionEffect]:
    """طبقِ درخواستِ صریح: مستقل از فرمِ فاکتور قابلِ‌فراخوانی/تست است --
    ورودی همان دو چیزی که هر فاکتوری دارد (مقدارِ هر کالا + جمعِ خالصِ
    سند)، خروجی فهرستِ اثرهایِ قابلِ‌اعمال (هدیه/تخفیف)."""
    effects: list[PromotionEffect] = []
    for rule in list_promotion_rules(company_id, active_only=True):
        f = rule.fields
        if f.channel_type_code is not None and f.channel_type_code != channel_type_code:
            continue
        if f.valid_from is not None and as_of_date < f.valid_from:
            continue
        if f.valid_to is not None and as_of_date > f.valid_to:
            continue
        if f.promotion_type_code == "BUY_X_GET_Y":
            bought_qty = item_quantities.get(f.applies_to_item_id, decimal.Decimal(0))
            if bought_qty < f.buy_quantity:
                continue
            multiples = int(bought_qty // f.buy_quantity)
            free_quantity = f.get_quantity * multiples
            effects.append(
                PromotionEffect(
                    rule.promotion_rule_id, rule.code, rule.name, f.promotion_type_code,
                    free_item_id=(f.get_item_id or f.applies_to_item_id), free_quantity=free_quantity,
                )
            )
        elif f.promotion_type_code == "THRESHOLD_DISCOUNT":
            if order_net_amount < f.threshold_amount:
                continue
            discount_amount = (order_net_amount * f.discount_percent / decimal.Decimal(100)).quantize(decimal.Decimal("0.01"))
            effects.append(
                PromotionEffect(rule.promotion_rule_id, rule.code, rule.name, f.promotion_type_code, discount_amount=discount_amount)
            )
    return effects
