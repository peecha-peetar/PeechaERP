"""سگمنت پویای مشتری (فاز ۴، R283).

قاعدهٔ هر سگمنت JSON است و هر بار روی دادهٔ روز ارزیابی می‌شود (عضویت ذخیره نمی‌شود، فقط تعداد کش می‌شود):
    {"all": [{"field": "churn_risk", "op": ">=", "value": 60}, {"any": [...]}, {"not": {...}}]}
فیلدها از پروفایل مشتری ERP و کش امتیاز CRM (crm.customer_scores) خوانده می‌شوند. برای فیلد تاریخ، مقدار
{"days_ago": N} یعنی «N روز پیش از امروز».
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import and_, false, func, not_, or_, select, true

from peecha.db.base import new_session
from peecha.db.models.accounting import CustomerDetail, DetailAccount
from peecha.db.models.commercial import CustomerProfile
from peecha.db.models.crm import CustomerScore, Segment
from peecha.services.crm import analytics
from peecha.services.crm import common as c


@dataclass(frozen=True)
class FieldDef:
    label: str
    kind: str  # number | text | choice | date
    column: object
    choices: dict | None = None


_CUSTOMER_TYPES = {"INDIVIDUAL": "شخص", "COMPANY": "شرکت", "STORE": "فروشگاه", "ORGANIZATION": "سازمان",
                   "WHOLESALER": "عمده‌فروش", "RETAILER": "خرده‌فروش", "AGENT": "نماینده/توزیع‌کننده", "ONLINE": "آنلاین"}
_OUTLETS = {"SUPERMARKET": "سوپرمارکت", "CHAIN_STORE": "فروشگاه زنجیره‌ای", "WHOLESALE": "عمده‌فروشی", "RESTAURANT": "رستوران",
            "PHARMACY": "داروخانه", "SPECIALTY_STORE": "فروشگاه تخصصی", "ORGANIZATIONAL": "سازمانی", "OTHER": "سایر"}

FIELDS: dict[str, FieldDef] = {
    "recency_days": FieldDef("روز از آخرین خرید", "number", CustomerScore.recency_days),
    "frequency_365": FieldDef("دفعات خرید ۱۲ ماه", "number", CustomerScore.frequency_365),
    "monetary_365": FieldDef("مبلغ خرید ۱۲ ماه", "number", CustomerScore.monetary_365),
    "sales_90d": FieldDef("فروش ۹۰ روز", "number", CustomerScore.sales_90d),
    "invoice_count_total": FieldDef("تعداد کل فاکتورها", "number", CustomerScore.invoice_count_total),
    "first_purchase": FieldDef("تاریخ اولین خرید", "date", CustomerScore.first_purchase),
    "last_purchase": FieldDef("تاریخ آخرین خرید", "date", CustomerScore.last_purchase),
    "r_score": FieldDef("امتیاز تازگی (R)", "number", CustomerScore.r_score),
    "f_score": FieldDef("امتیاز تکرار (F)", "number", CustomerScore.f_score),
    "m_score": FieldDef("امتیاز مبلغ (M)", "number", CustomerScore.m_score),
    "rfm_segment": FieldDef("بخش RFM", "choice", CustomerScore.rfm_segment, analytics.RFM_SEGMENTS),
    "health_score": FieldDef("امتیاز سلامت", "number", CustomerScore.health_score),
    "health_band": FieldDef("وضعیت سلامت", "choice", CustomerScore.health_band,
                            {k: v[0] for k, v in analytics.insights.HEALTH_BANDS.items()}),
    "churn_risk": FieldDef("ریسک ریزش", "number", CustomerScore.churn_risk),
    "churn_band": FieldDef("سطح ریسک ریزش", "choice", CustomerScore.churn_band, analytics.insights.CHURN_BANDS),
    "clv_historical": FieldDef("ارزش طول عمر (تاکنون)", "number", CustomerScore.clv_historical),
    "clv_predicted": FieldDef("ارزش طول عمر (پیش‌بینی)", "number", CustomerScore.clv_predicted),
    "overdue_amount": FieldDef("بدهی معوق", "number", CustomerScore.overdue_amount),
    "open_complaints": FieldDef("شکایت‌های باز", "number", CustomerScore.open_complaints),
    "activities_90d": FieldDef("تعامل ۹۰ روز", "number", CustomerScore.activities_90d),
    "customer_group_id": FieldDef("گروه مشتری", "number", CustomerProfile.customer_group_id),
    "priority_code": FieldDef("اولویت مشتری", "choice", CustomerProfile.priority_code,
                              {"LOW": "کم", "NORMAL": "عادی", "HIGH": "بالا", "VIP": "ویژه"}),
    "outlet_type_code": FieldDef("نوع فروشگاه", "choice", CustomerProfile.outlet_type_code, _OUTLETS),
    "default_channel_code": FieldDef("کانال فروش", "text", CustomerProfile.default_channel_code),
    "credit_limit_amount": FieldDef("سقف اعتبار", "number", CustomerProfile.credit_limit_amount),
    "status_code": FieldDef("وضعیت مشتری", "text", CustomerProfile.status_code),
    "customer_type_code": FieldDef("نوع مشتری", "choice", CustomerDetail.customer_type_code, _CUSTOMER_TYPES),
    "person_type_code": FieldDef("حقیقی/حقوقی", "choice", CustomerDetail.person_type_code, {"NATURAL": "حقیقی", "LEGAL": "حقوقی"}),
    "customer_class": FieldDef("کلاس مشتری", "text", CustomerDetail.customer_class),
    "geographic_region": FieldDef("منطقهٔ جغرافیایی", "text", CustomerDetail.geographic_region),
}
OPERATORS = {"=": "برابر", "!=": "نابرابر", ">": "بزرگ‌تر", ">=": "بزرگ‌تر یا برابر", "<": "کوچک‌تر", "<=": "کوچک‌تر یا برابر",
             "in": "یکی از", "not_in": "هیچ‌کدام از", "between": "بین", "contains": "شامل", "is_null": "خالی", "not_null": "پر"}

SYSTEM_SEGMENTS = (
    ("VIP", "مشتریان ویژه (VIP)", {"any": [{"field": "priority_code", "op": "=", "value": "VIP"},
                                          {"field": "rfm_segment", "op": "=", "value": "CHAMPIONS"}]}),
    ("HIGH_VALUE", "ارزش بالا", {"all": [{"field": "m_score", "op": ">=", "value": 4}]}),
    ("NEW", "مشتریان جدید", {"all": [{"field": "first_purchase", "op": ">=", "value": {"days_ago": 90}}]}),
    ("DORMANT", "غیرفعال (خواب)", {"all": [{"field": "recency_days", "op": ">=", "value": 90}]}),
    ("AT_RISK", "در معرض ریزش", {"any": [{"field": "churn_band", "op": "=", "value": "HIGH"},
                                        {"field": "health_band", "op": "=", "value": "AT_RISK"}]}),
    ("LOYAL", "وفادار", {"all": [{"field": "rfm_segment", "op": "in", "value": ["LOYAL", "CHAMPIONS"]}]}),
    ("WHOLESALE", "عمده‌فروش", {"any": [{"field": "customer_type_code", "op": "=", "value": "WHOLESALER"},
                                       {"field": "outlet_type_code", "op": "=", "value": "WHOLESALE"}]}),
    ("RETAIL", "خرده‌فروش", {"all": [{"field": "customer_type_code", "op": "in", "value": ["RETAILER", "STORE", "INDIVIDUAL", "ONLINE"]}]}),
    ("DISTRIBUTOR", "توزیع‌کننده/نماینده", {"all": [{"field": "customer_type_code", "op": "=", "value": "AGENT"}]}),
    ("CORPORATE", "سازمانی", {"any": [{"field": "customer_type_code", "op": "in", "value": ["COMPANY", "ORGANIZATION"]},
                                     {"field": "outlet_type_code", "op": "=", "value": "ORGANIZATIONAL"}]}),
)


def _value(fd: FieldDef, v):
    if isinstance(v, dict) and "days_ago" in v:
        return datetime.date.today() - datetime.timedelta(days=int(v["days_ago"]))
    if fd.kind == "date" and isinstance(v, str):
        return datetime.date.fromisoformat(v)
    if fd.kind == "number" and v is not None and not isinstance(v, (int, float, decimal.Decimal)):
        return decimal.Decimal(str(v))
    return v


def _cond(rule: dict):
    """قاعدهٔ JSON ← عبارت SQL. قاعدهٔ نامعتبر ValueError می‌دهد (پیش از ذخیره)."""
    if not isinstance(rule, dict):
        raise ValueError("قاعدهٔ سگمنت نامعتبر است.")
    if "all" in rule or "any" in rule:
        parts = [_cond(r) for r in rule.get("all", rule.get("any")) or []]
        if not parts:
            return true() if "all" in rule else false()
        return and_(*parts) if "all" in rule else or_(*parts)
    if "not" in rule:
        return not_(_cond(rule["not"]))
    fd = FIELDS.get(rule.get("field"))
    if fd is None:
        raise ValueError(f"فیلد سگمنت ناشناخته است: {rule.get('field')}")
    col, op, raw = fd.column, rule.get("op"), rule.get("value")
    if op == "is_null":
        return col.is_(None)
    if op == "not_null":
        return col.is_not(None)
    if op in ("in", "not_in"):
        values = [_value(fd, v) for v in (raw if isinstance(raw, list) else [raw])]
        return col.in_(values) if op == "in" else or_(col.is_(None), col.not_in(values))
    if op == "between":
        if not isinstance(raw, list) or len(raw) != 2:
            raise ValueError("عملگر «بین» دو مقدار لازم دارد.")
        return col.between(_value(fd, raw[0]), _value(fd, raw[1]))
    if op == "contains":
        return col.ilike(f"%{raw}%")
    ops = {"=": lambda v: col == v, "!=": lambda v: col != v, ">": lambda v: col > v, ">=": lambda v: col >= v,
           "<": lambda v: col < v, "<=": lambda v: col <= v}
    if op not in ops:
        raise ValueError(f"عملگر نامعتبر: {op}")
    if raw is None or raw == "":
        raise ValueError(f"برای شرط «{fd.label}» مقدار وارد نشده است.")
    return ops[op](_value(fd, raw))


def _base(company_id: int):
    return (select(CustomerProfile.customer_detail_account_id)
            .join(DetailAccount, DetailAccount.detail_account_id == CustomerProfile.customer_detail_account_id)
            .outerjoin(CustomerDetail, CustomerDetail.detail_account_id == CustomerProfile.customer_detail_account_id)
            .outerjoin(CustomerScore, CustomerScore.customer_detail_account_id == CustomerProfile.customer_detail_account_id)
            .where(CustomerProfile.company_id == company_id, DetailAccount.is_active.is_(True)))


def validate_rule(rule: dict) -> None:
    _cond(rule)


def evaluate(company_id: int, rule: dict) -> list[int]:
    with new_session() as session:
        return list(session.scalars(_base(company_id).where(_cond(rule)).order_by(CustomerProfile.customer_detail_account_id)))


def count(company_id: int, rule: dict) -> int:
    with new_session() as session:
        return session.scalar(select(func.count()).select_from(_base(company_id).where(_cond(rule)).subquery())) or 0


def ensure_system_segments(company_id: int) -> None:
    with new_session() as session:
        have = set(session.scalars(select(Segment.code).where(Segment.company_id == company_id)))
        for code, name, rule in SYSTEM_SEGMENTS:
            if code not in have:
                session.add(Segment(company_id=company_id, code=code, name=name, rule=rule, is_system=True))
        session.commit()


def list_segments(company_id: int, active_only: bool = False) -> list[Segment]:
    ensure_system_segments(company_id)
    with new_session() as session:
        q = select(Segment).where(Segment.company_id == company_id)
        if active_only:
            q = q.where(Segment.is_active.is_(True))
        rows = list(session.scalars(q.order_by(Segment.is_system.desc(), Segment.name)))
        session.expunge_all()
        return rows


def get_segment(company_id: int, segment_id: int) -> Segment:
    with new_session() as session:
        seg = session.get(Segment, segment_id)
        if seg is None or seg.company_id != company_id:
            raise ValueError("سگمنت نامعتبر است.")
        session.expunge(seg)
        return seg


def save_segment(company_id: int, user_id: int | None, *, segment_id: int | None = None, code: str, name: str,
                 rule: dict, description: str | None = None, is_active: bool = True) -> int:
    code, name = (code or "").strip().upper(), (name or "").strip()
    if not code or not name:
        raise ValueError("کد و نام سگمنت الزامی است.")
    validate_rule(rule)
    with new_session() as session:
        dup = session.scalar(select(Segment.segment_id).where(Segment.company_id == company_id, Segment.code == code))
        if dup and dup != segment_id:
            raise ValueError("کد سگمنت تکراری است.")
        if segment_id:
            seg = session.get(Segment, segment_id)
            if seg is None or seg.company_id != company_id:
                raise ValueError("سگمنت نامعتبر است.")
            if seg.is_system and seg.code != code:
                raise ValueError("کد سگمنت سیستمی قابل تغییر نیست.")
        else:
            seg = Segment(company_id=company_id, created_by_user_id=user_id, is_system=False)
            session.add(seg)
        seg.code, seg.name, seg.rule, seg.description, seg.is_active = code, name, rule, description, is_active
        session.flush()
        c.audit(session, company_id, user_id, "Segment", seg.segment_id, "UPDATE" if segment_id else "CREATE",
                {"code": code, "rule": rule})
        session.commit()
        return seg.segment_id


def delete_segment(company_id: int, user_id: int | None, segment_id: int) -> None:
    with new_session() as session:
        seg = session.get(Segment, segment_id)
        if seg is None or seg.company_id != company_id:
            raise ValueError("سگمنت نامعتبر است.")
        if seg.is_system:
            raise ValueError("سگمنت سیستمی حذف نمی‌شود؛ می‌توانید آن را غیرفعال کنید.")
        c.audit(session, company_id, user_id, "Segment", segment_id, "DELETE", {"code": seg.code})
        session.delete(seg)
        session.commit()


def members(company_id: int, segment_id: int) -> list[int]:
    return evaluate(company_id, get_segment(company_id, segment_id).rule)


def refresh_counts(company_id: int) -> dict[int, int]:
    """تعداد اعضای هر سگمنت فعال را دوباره می‌شمارد (پس از refresh_scores)."""
    out = {}
    segs = list_segments(company_id, active_only=True)
    with new_session() as session:
        for s in segs:
            n = session.scalar(select(func.count()).select_from(_base(company_id).where(_cond(s.rule)).subquery())) or 0
            row = session.get(Segment, s.segment_id)
            row.member_count, row.refreshed_at = n, c.now()
            out[s.segment_id] = n
        session.commit()
    return out


def segments_of_customer(company_id: int, customer_id: int) -> list[Segment]:
    """سگمنت‌هایی که مشتری الان عضو آن‌هاست (برای برچسب‌های پروندهٔ ۳۶۰)."""
    out = []
    with new_session() as session:
        for s in list_segments(company_id, active_only=True):
            hit = session.scalar(_base(company_id).where(
                CustomerProfile.customer_detail_account_id == customer_id, _cond(s.rule)).limit(1))
            if hit:
                out.append(s)
    return out
