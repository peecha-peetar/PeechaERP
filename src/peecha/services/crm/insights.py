"""لایهٔ «بینش» CRM — آمادهٔ اتصال هوش مصنوعی، بدون وابستگی اجباری به آن.

هر قابلیت پیش‌بینی (امتیاز سلامت، ریسک ریزش، اقدام پیشنهادی، خلاصهٔ مشتری) پشت یک Provider است. پیش‌فرض
RuleBasedProvider (قاعده‌محور و قابل توضیح) است؛ سرویس هوشمند بعدی فقط با set_provider جایگزین می‌شود و بقیهٔ کد
(تحلیل، ۳۶۰، داشبورد، API) دست نمی‌خورد.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

HEALTH_BANDS = {"HEALTHY": ("سالم", "🟢"), "ATTENTION": ("نیازمند توجه", "🟡"), "AT_RISK": ("در معرض خطر", "🔴")}
CHURN_BANDS = {"LOW": "کم", "MEDIUM": "متوسط", "HIGH": "زیاد"}


@dataclass
class CustomerSignals:
    """ورودی‌های قابل توضیح هر مشتری (همه از دادهٔ ERP)."""
    recency_days: int | None
    avg_gap_days: float | None
    frequency_365: int
    monetary_365: float
    r_score: int | None
    f_score: int | None
    m_score: int | None
    freq_recent_90: int
    freq_prev_90: int
    amount_recent_90: float
    amount_prev_90: float
    overdue_amount: float
    max_days_overdue: int
    open_complaints: int
    activities_90d: int
    priority_code: str | None = None
    has_purchases: bool = True
    extra: dict = field(default_factory=dict)


@dataclass
class Prediction:
    score: int
    band: str
    factors: dict[str, int]


class InsightsProvider(Protocol):
    def health(self, s: CustomerSignals) -> Prediction: ...

    def churn(self, s: CustomerSignals) -> Prediction: ...

    def next_best_actions(self, s: CustomerSignals) -> list[dict]: ...


class RuleBasedProvider:
    """وزن‌ها شفاف‌اند و در factors برگردانده می‌شوند تا کاربر بداند امتیاز از کجا آمده."""

    def health(self, s: CustomerSignals) -> Prediction:
        if not s.has_purchases:
            return Prediction(45, "ATTENTION", {"no_purchase": 45})
        f = {
            "recency": round(5 * (s.r_score or 1)),               # ۵ تا ۲۵
            "frequency": round(3 * (s.f_score or 1)),             # ۳ تا ۱۵
            "revenue": round(3 * (s.m_score or 1)),               # ۳ تا ۱۵
            "payment": 20 if s.overdue_amount <= 0 else 10 if s.max_days_overdue <= 30 else 0,
            "complaints": max(0, 10 - 5 * s.open_complaints),
            "engagement": min(15, 5 * s.activities_90d),
        }
        score = max(0, min(100, sum(f.values())))
        return Prediction(score, "HEALTHY" if score >= 70 else "ATTENTION" if score >= 40 else "AT_RISK", f)

    def churn(self, s: CustomerSignals) -> Prediction:
        if not s.has_purchases:
            return Prediction(0, "LOW", {})
        f: dict[str, int] = {}
        if s.recency_days is not None:
            if s.avg_gap_days:
                ratio = s.recency_days / max(s.avg_gap_days, 1)
                f["interval"] = 35 if ratio >= 3 else 25 if ratio >= 2 else 12 if ratio >= 1.4 else 0
            else:
                f["interval"] = 30 if s.recency_days >= 120 else 15 if s.recency_days >= 60 else 0
        if s.freq_prev_90 and s.freq_recent_90 < s.freq_prev_90:
            f["frequency_drop"] = round(20 * (1 - s.freq_recent_90 / s.freq_prev_90))
        if s.amount_prev_90 and s.amount_recent_90 < s.amount_prev_90:
            f["amount_drop"] = round(15 * (1 - s.amount_recent_90 / s.amount_prev_90))
        if s.overdue_amount > 0:
            f["debt"] = 15 if s.max_days_overdue > 30 else 8
        if s.open_complaints:
            f["complaints"] = min(10, 5 * s.open_complaints)
        if s.activities_90d == 0:
            f["no_engagement"] = 5
        score = max(0, min(100, sum(f.values())))
        return Prediction(score, "HIGH" if score >= 60 else "MEDIUM" if score >= 30 else "LOW", f)

    def next_best_actions(self, s: CustomerSignals) -> list[dict]:
        out = []
        if s.has_purchases and s.recency_days is not None and s.avg_gap_days and s.recency_days > s.avg_gap_days * 1.4 and s.recency_days >= 14:
            out.append({"code": "FOLLOW_UP_SALES", "action": "FOLLOW_UP", "severity": "warning", "suggestion": "پیگیری فروش",
                        "text": f"معمولاً هر {round(s.avg_gap_days)} روز خرید می‌کند و اکنون {s.recency_days} روز گذشته است."})
        elif s.has_purchases and s.recency_days is not None and s.recency_days >= 60:
            out.append({"code": "INACTIVE", "action": "CALL", "severity": "warning", "suggestion": "تماس پیگیری",
                        "text": f"{s.recency_days} روز است خرید نکرده."})
        if s.overdue_amount > 0:
            out.append({"code": "COLLECTION", "action": "FOLLOW_UP", "severity": "danger", "suggestion": "پیگیری وصول",
                        "text": f"بدهی معوق دارد (بیشترین تأخیر {s.max_days_overdue} روز)."})
        if s.open_complaints:
            out.append({"code": "SERVICE", "action": "TASK", "severity": "warning", "suggestion": "رسیدگی به شکایت",
                        "text": f"{s.open_complaints} شکایت یا درخواست باز دارد."})
        if s.priority_code == "VIP":
            out.append({"code": "VIP", "action": "TASK", "severity": "info", "suggestion": "خدمت با اولویت", "text": "مشتری ویژه است."})
        if s.freq_prev_90 and s.freq_recent_90 < s.freq_prev_90 / 2:
            out.append({"code": "DECLINE", "action": "MEETING", "severity": "warning", "suggestion": "جلسه برای بررسی نیاز",
                        "text": "دفعات خرید سه ماه اخیر به کمتر از نصف رسیده است."})
        if not s.has_purchases:
            out.append({"code": "FIRST_SALE", "action": "CALL", "severity": "info", "suggestion": "معرفی محصولات و اولین سفارش",
                        "text": "هنوز خریدی ثبت نکرده است."})
        return out


_provider: InsightsProvider = RuleBasedProvider()


def get_provider() -> InsightsProvider:
    return _provider


def set_provider(provider: InsightsProvider) -> None:
    """نقطهٔ اتصال سرویس هوشمند (مثلاً مدل پیش‌بینی ریزش)؛ None یعنی بازگشت به قاعده‌محور."""
    global _provider
    _provider = provider or RuleBasedProvider()
