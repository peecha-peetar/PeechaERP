"""قواعد باشگاه مشتریان در CRM (فاز ۵، R284).

حساب امتیاز و تراکنش‌ها همان comm.loyalty_accounts / loyalty_transactions فروش حضوری است و امتیاز با همان
commercial_pos.earn_points ثبت می‌شود؛ اینجا فقط قاعده‌ها (امتیاز به ازای مبلغ فاکتور، جایزهٔ اولین خرید و خرید
تکراری، معرفی) و سطح‌بندی تعریف می‌شود. هر فاکتور فقط یک بار امتیاز می‌گیرد (تراکنش با document_id).
"""

from __future__ import annotations

import decimal

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.audit import ActivityLog
from peecha.db.models.commercial import CommercialDocument, LoyaltyAccount, LoyaltyTransaction
from peecha.db.models.crm import CrmSettings
from peecha.services import commercial_pos as pos_service
from peecha.services.crm import common as c

TIERS = {"STANDARD": "عادی", "SILVER": "نقره‌ای", "GOLD": "طلایی", "PLATINUM": "پلاتینی"}
DEFAULTS = {"enabled": False, "amount_per_point": 1_000_000, "first_purchase_bonus": 50, "repeat_every": 5,
            "repeat_bonus": 20, "referral_points": 100, "tiers": {"SILVER": 500, "GOLD": 2000, "PLATINUM": 5000}}


def get_rules(company_id: int) -> dict:
    with new_session() as session:
        row = session.get(CrmSettings, company_id)
        saved = (row.options or {}).get("loyalty", {}) if row else {}
    return {**DEFAULTS, **saved, "tiers": {**DEFAULTS["tiers"], **(saved.get("tiers") or {})}}


def save_rules(company_id: int, user_id: int | None, **rules) -> dict:
    unknown = set(rules) - set(DEFAULTS)
    if unknown:
        raise ValueError("قاعدهٔ نامعتبر: " + "، ".join(sorted(unknown)))
    merged = {**get_rules(company_id), **rules}
    if decimal.Decimal(merged["amount_per_point"]) <= 0:
        raise ValueError("مبلغ هر امتیاز باید بیشتر از صفر باشد.")
    for k in ("first_purchase_bonus", "repeat_every", "repeat_bonus", "referral_points"):
        if int(merged[k]) < 0:
            raise ValueError("مقدار قاعده‌های امتیاز نمی‌تواند منفی باشد.")
    t = {**DEFAULTS["tiers"], **(merged.get("tiers") or {})}
    if not 0 < int(t["SILVER"]) < int(t["GOLD"]) < int(t["PLATINUM"]):
        raise ValueError("مرز سطح‌ها باید به ترتیب «نقره‌ای < طلایی < پلاتینی» باشد.")
    merged["tiers"] = {k: int(v) for k, v in t.items()}
    with new_session() as session:
        row = session.get(CrmSettings, company_id) or CrmSettings(company_id=company_id, options={})
        row.options = {**(row.options or {}), "loyalty": merged}
        row.updated_at = c.now()
        session.add(row)
        c.audit(session, company_id, user_id, "Settings", company_id, "UPDATE", {"loyalty": merged})
        session.commit()
    return merged


def tier_for(lifetime_points: int, tiers: dict) -> str:
    for code in ("PLATINUM", "GOLD", "SILVER"):
        if lifetime_points >= int(tiers[code]):
            return code
    return "STANDARD"


def invoice_points(rules: dict, net_amount: decimal.Decimal, invoice_index: int) -> int:
    """امتیاز یک فاکتور: مبلغ خالص ÷ مبلغ هر امتیاز + جایزهٔ اولین خرید + جایزهٔ هر N امین خرید."""
    pts = int(decimal.Decimal(net_amount) // decimal.Decimal(rules["amount_per_point"]))
    if invoice_index == 1:
        pts += int(rules["first_purchase_bonus"])
    every = int(rules["repeat_every"])
    if every and invoice_index > 1 and invoice_index % every == 0:
        pts += int(rules["repeat_bonus"])
    return max(0, pts)


def award_for_invoices(company_id: int) -> dict:
    """به فاکتورهای ثبت‌شده‌ای که هنوز امتیاز نگرفته‌اند امتیاز می‌دهد و سطح مشتری را به‌روز می‌کند."""
    rules = get_rules(company_id)
    if not rules["enabled"]:
        return {"invoices": 0, "points": 0}
    net = CommercialDocument.subtotal_amount - CommercialDocument.discount_amount
    with new_session() as session:
        awarded = set(session.scalars(select(LoyaltyTransaction.document_id).where(LoyaltyTransaction.document_id.is_not(None))))
        rows = session.execute(select(CommercialDocument.document_id, CommercialDocument.counterparty_detail_account_id, net).where(
            CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "SALES_INVOICE",
            CommercialDocument.status_code == "POSTED").order_by(CommercialDocument.document_date, CommercialDocument.document_id)).all()
    seen: dict[int, int] = {}
    invoices = points = 0
    for doc_id, cust, amount in rows:
        seen[cust] = seen.get(cust, 0) + 1
        if doc_id in awarded:
            continue
        pts = invoice_points(rules, amount, seen[cust])
        if pts:
            pos_service.earn_points(cust, pts, doc_id)
            invoices, points = invoices + 1, points + pts
    _update_tiers(company_id, rules)
    return {"invoices": invoices, "points": points}


def _update_tiers(company_id: int, rules: dict) -> None:
    with new_session() as session:
        lifetime = dict(session.execute(select(LoyaltyAccount.loyalty_account_id, func.coalesce(func.sum(LoyaltyTransaction.points_delta), 0))
                                        .join(LoyaltyTransaction, LoyaltyTransaction.loyalty_account_id == LoyaltyAccount.loyalty_account_id)
                                        .join(DetailAccount, DetailAccount.detail_account_id == LoyaltyAccount.customer_detail_account_id)
                                        .where(DetailAccount.company_id == company_id, LoyaltyTransaction.transaction_type_code == "EARN")
                                        .group_by(LoyaltyAccount.loyalty_account_id)).all())
        for acc in session.scalars(select(LoyaltyAccount).where(LoyaltyAccount.loyalty_account_id.in_(list(lifetime) or [-1]))):
            acc.tier_code = tier_for(int(lifetime[acc.loyalty_account_id]), rules["tiers"])
        session.commit()


def award_referral(company_id: int, user_id: int, referrer_id: int, referred_id: int) -> int:
    """امتیاز معرفی مشتری تازه به معرف (یک بار به ازای هر مشتری معرفی‌شده)."""
    rules = get_rules(company_id)
    if not rules["enabled"]:
        raise ValueError("باشگاه مشتریان در تنظیمات CRM فعال نیست.")
    if referrer_id == referred_id:
        raise ValueError("مشتری نمی‌تواند معرف خودش باشد.")
    with new_session() as session:
        for cid in (referrer_id, referred_id):
            da = session.get(DetailAccount, cid)
            if da is None or da.company_id != company_id:
                raise ValueError("مشتری نامعتبر است.")
        if session.scalar(select(func.count()).where(ActivityLog.company_id == company_id, ActivityLog.entity_type == "CrmLoyaltyReferral",
                                                     ActivityLog.entity_id == referred_id)):
            raise ValueError("امتیاز معرفی این مشتری قبلاً داده شده است.")
        c.audit(session, company_id, user_id, "LoyaltyReferral", referred_id, "CREATE", {"referrer": referrer_id})
        session.commit()
    pts = int(rules["referral_points"])
    if pts:
        pos_service.earn_points(referrer_id, pts)
        _update_tiers(company_id, rules)
    return pts


def adjust_points(company_id: int, user_id: int, customer_id: int, points: int, reason: str) -> int:
    """اصلاح دستی امتیاز (مثبت یا منفی) با ثبت در گزارش ممیزی. برمی‌گرداند: ماندهٔ امتیاز."""
    if not points:
        raise ValueError("مقدار امتیاز صفر است.")
    if not (reason or "").strip():
        raise ValueError("علت اصلاح امتیاز الزامی است.")
    with new_session() as session:
        da = session.get(DetailAccount, customer_id)
        if da is None or da.company_id != company_id:
            raise ValueError("مشتری نامعتبر است.")
    acc = pos_service.get_or_create_loyalty_account(customer_id)
    with new_session() as session:
        row = session.get(LoyaltyAccount, acc.loyalty_account_id)
        if row.points_balance + points < 0:
            raise ValueError("امتیاز مشتری کافی نیست.")
        row.points_balance += points
        session.add(LoyaltyTransaction(loyalty_account_id=row.loyalty_account_id, points_delta=points, transaction_type_code="ADJUST"))
        c.audit(session, company_id, user_id, "LoyaltyAccount", row.loyalty_account_id, "UPDATE",
                {"points": points, "reason": reason.strip(), "customer": customer_id})
        session.commit()
        return row.points_balance


def summary(company_id: int, customer_id: int, limit: int = 20) -> dict:
    with new_session() as session:
        acc = session.scalar(select(LoyaltyAccount).where(LoyaltyAccount.customer_detail_account_id == customer_id))
        if acc is None:
            return {"points": 0, "wallet": decimal.Decimal(0), "tier": "STANDARD", "tier_label": TIERS["STANDARD"],
                    "lifetime_points": 0, "transactions": []}
        lifetime = session.scalar(select(func.coalesce(func.sum(LoyaltyTransaction.points_delta), 0)).where(
            LoyaltyTransaction.loyalty_account_id == acc.loyalty_account_id, LoyaltyTransaction.transaction_type_code == "EARN"))
        tx = session.execute(select(LoyaltyTransaction, CommercialDocument.document_no).outerjoin(
            CommercialDocument, CommercialDocument.document_id == LoyaltyTransaction.document_id).where(
            LoyaltyTransaction.loyalty_account_id == acc.loyalty_account_id).order_by(LoyaltyTransaction.transaction_id.desc()).limit(limit)).all()
        return {"points": acc.points_balance, "wallet": acc.wallet_balance, "tier": acc.tier_code,
                "tier_label": TIERS.get(acc.tier_code, acc.tier_code), "lifetime_points": int(lifetime),
                "transactions": [{"at": t.created_at, "type": t.transaction_type_code, "points": t.points_delta,
                                  "wallet": t.wallet_delta, "document_no": no} for t, no in tx]}
