"""امتیاز کیفیت تامین‌کننده از داده‌های واقعی و قابل ردیابی، با وزن قابل تنظیم و حداقل تعداد نمونه.

شاخص‌ها در بازهٔ تنظیم‌شده (پیش‌فرض یک سال): نرخ مردودی بازرسی رسید، نرخ برگشت خرید، تعداد عدم‌انطباق به ازای
بازرسی، میانگین تأخیر رسیدگی (رسید تا تأیید بازرسی) و روند مردودی (نیمهٔ اول در برابر نیمهٔ دوم بازه).
هر بار از اسناد منبع حساب می‌شود؛ رسید برگشت‌خورده، بازرسی لغوشده و پروندهٔ لغوشده حساب نمی‌شوند.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.quality import Nonconformance
from peecha.services import supplier_quality
from peecha.services.qms import common as c

_ZERO = decimal.Decimal(0)
_HUNDRED = decimal.Decimal(100)
_Q1 = decimal.Decimal("0.1")


def formula_text(st) -> str:
    def n(v) -> str:
        return f"{decimal.Decimal(str(v)).normalize():f}"

    return (f"امتیاز (از ۱۰۰) = میانگین وزنی شاخص‌های دارای داده: (۱۰۰ − نرخ مردودی) با وزن {n(st.weight_reject)}، "
            f"(۱۰۰ − نرخ برگشت خرید) با وزن {n(st.weight_return)}، (۱۰۰ − عدم‌انطباق به ازای هر بازرسی × ۱۰۰) با وزن "
            f"{n(st.weight_ncr)}، تأخیر رسیدگی (۱۰۰ تا {n(st.target_handling_days)} روز، سپس کاهشی) با وزن "
            f"{n(st.weight_delay)} و روند مردودی با وزن {n(st.weight_trend)}. "
            f"بازه: {st.score_window_days} روز اخیر؛ کمتر از {st.score_min_samples} بازرسی = داده ناکافی.")


def _pct(part, whole) -> decimal.Decimal | None:
    return (decimal.Decimal(part) * _HUNDRED / decimal.Decimal(whole)).quantize(_Q1) if whole else None


def supplier_scores(company_id: int, as_of: datetime.date | None = None, supplier_id: int | None = None) -> list[SimpleNamespace]:
    from peecha.services import purchase_reports as pr

    st = c.settings(company_id)
    date_to = as_of or datetime.date.today()
    date_from = date_to - datetime.timedelta(days=int(st.score_window_days))
    mid = date_from + datetime.timedelta(days=int(st.score_window_days) // 2)
    with new_session() as session:
        rows = supplier_quality.inspections(session, company_id, date_from, date_to, supplier_id)
        ncr_counts = dict(session.execute(
            select(Nonconformance.supplier_detail_account_id, func.count()).where(
                Nonconformance.company_id == company_id, Nonconformance.supplier_detail_account_id.is_not(None),
                Nonconformance.status_code != "CANCELLED",
                Nonconformance.detected_at >= datetime.datetime.combine(date_from, datetime.time.min),
                Nonconformance.detected_at < datetime.datetime.combine(date_to + datetime.timedelta(days=1), datetime.time.min))
            .group_by(Nonconformance.supplier_detail_account_id)).all())
    agg: dict[int, dict] = defaultdict(lambda: {"n": 0, "qty": _ZERO, "rej": _ZERO, "old": [_ZERO, _ZERO], "new": [_ZERO, _ZERO],
                                                "delays": [], "bought": _ZERO, "returned": _ZERO})
    for r in rows:
        a = agg[r.supplier_id]
        a["n"] += 1
        a["qty"] += r.inspected
        a["rej"] += r.rejected
        half = a["old"] if (r.approved_at and r.approved_at.date() < mid) else a["new"]
        half[0] += r.inspected
        half[1] += r.rejected
        if r.posted_at and r.approved_at:
            a["delays"].append(max(0.0, (r.approved_at - r.posted_at).total_seconds() / 86400))
    ctx = pr._ctx(company_id)
    purchases, returns = pr._posted_purchase_and_returns(company_id, pr.PurchaseFilters(date_from, date_to, supplier_id=supplier_id), ctx)
    for doc, ln in purchases:
        agg[doc.counterparty_detail_account_id]["bought"] += ln.quantity_base
    for doc, ln in returns:
        agg[doc.counterparty_detail_account_id]["returned"] += ln.quantity_base
    for sid in ncr_counts:
        if supplier_id is None or sid == supplier_id:
            agg[sid]  # noqa: B018 — تامین‌کننده‌ای که فقط عدم‌انطباق دارد هم دیده شود
    weights = {"reject": decimal.Decimal(st.weight_reject), "return": decimal.Decimal(st.weight_return),
               "ncr": decimal.Decimal(st.weight_ncr), "delay": decimal.Decimal(st.weight_delay), "trend": decimal.Decimal(st.weight_trend)}
    target = decimal.Decimal(st.target_handling_days)
    out = []
    for sid, a in agg.items():
        reject_rate = _pct(a["rej"], a["qty"])
        return_rate = _pct(a["returned"], a["bought"])
        ncr = ncr_counts.get(sid, 0)
        ncr_rate = (decimal.Decimal(ncr) / a["n"]) if a["n"] else None
        delay = decimal.Decimal(str(round(sum(a["delays"]) / len(a["delays"]), 2))) if a["delays"] else None
        old_rate, new_rate = _pct(a["old"][1], a["old"][0]), _pct(a["new"][1], a["new"][0])
        trend = (old_rate - new_rate) if old_rate is not None and new_rate is not None else None
        subs = {
            "reject": _HUNDRED - reject_rate if reject_rate is not None else None,
            "return": max(_ZERO, _HUNDRED - return_rate) if return_rate is not None else None,
            "ncr": max(_ZERO, _HUNDRED - ncr_rate * _HUNDRED) if ncr_rate is not None else None,
            "delay": (_HUNDRED if delay <= target else max(_ZERO, _HUNDRED - (delay - target) * _HUNDRED / (3 * target)))
            if delay is not None else None,
            "trend": min(_HUNDRED, max(_ZERO, 50 + trend * 5)) if trend is not None else None,
        }
        used = [(weights[k], v) for k, v in subs.items() if v is not None and weights[k] > 0]
        sufficient = a["n"] >= int(st.score_min_samples)
        score = (sum(w * v for w, v in used) / sum(w for w, _v in used)).quantize(_Q1) if used and sufficient else None
        out.append(SimpleNamespace(
            supplier_id=sid, supplier_label=ctx.names.get(sid, ""), inspections=a["n"], inspected_qty=a["qty"], rejected_qty=a["rej"],
            reject_rate=reject_rate, purchased_qty=a["bought"], returned_qty=a["returned"], return_rate=return_rate, ncr_count=ncr,
            delay_days=delay, trend=trend, sub_scores=subs, score=score, sufficient=sufficient, date_from=date_from, date_to=date_to,
            note="" if sufficient else f"داده ناکافی: {a['n']} از حداقل {st.score_min_samples} بازرسی"))
    return sorted(out, key=lambda x: (x.score is None, -(x.score or 0), x.supplier_label))
