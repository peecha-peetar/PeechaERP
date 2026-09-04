"""دستیارِ فروش (طبقِ درخواستِ صریحِ کاربر: «دستیار فروش داخل ERP»):
هر بار که این پنل باز می‌شود، فهرستی از مهم‌ترین اقداماتِ امروز را از
رویِ سابقه‌یِ اسنادِ فروشِ ثبت‌نهایی‌شده محاسبه می‌کند -- بدونِ هیچ مدلِ
یادگیریِ ماشین، فقط آمارِ ساده‌یِ توصیفی رویِ همان جدول‌هایِ موجود:

۱. ریسکِ ریزش (قرمز/زرد): فاصله‌یِ روزهایِ سپری‌شده از آخرین خرید نسبت
   به میانگینِ فاصله‌یِ خریدهایِ همان مشتری بسیار بیشتر شده.
۲. فروشِ مکمل (زرد): کالایی که در آخرین فاکتورِ مشتری بوده، طبقِ آمارِ
   هم‌خریدی (همان suggest_frequently_bought_together) معمولاً با کالایِ
   دیگری همراه است که این مشتری هنوز نخریده.
۳. فرصتِ رشد (سبز): حجمِ خریدِ امسالِ مشتری (تا امروز) نسبت به مدتِ
   مشابهِ سالِ قبل رشدِ قابل‌توجه داشته -- پیشنهادِ افزایشِ سقفِ اعتبار."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field

import jdatetime
from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import CommercialDocumentLine
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_partners as partners_service
from peecha.services import inventory_catalog as catalog_service

_SEVERITY_RANK = {"danger": 0, "warning": 1, "success": 2}
# طبقِ درخواستِ صریح: زیرِ آستانه‌هایِ زیر، آیتم اصلاً «قابلِ‌اقدام» به
# حساب نمی‌آید و نمایش داده نمی‌شود.
_CHURN_RISK_MIN_PERCENT = decimal.Decimal(40)
_CROSS_SELL_MIN_CONFIDENCE_PERCENT = decimal.Decimal(40)
_GROWTH_MIN_PERCENT = decimal.Decimal(20)


@dataclass
class ActionItem:
    severity: str  # "danger" | "warning" | "success"
    category: str  # "churn_risk" | "cross_sell" | "growth"
    customer_id: int
    customer_name: str
    title: str
    detail_lines: list[str] = field(default_factory=list)
    suggested_action: str = ""
    metric_percent: decimal.Decimal | None = None


def _churn_risk_item(
    customer_id: int, customer_name: str, dates: list[datetime.date], today: datetime.date
) -> ActionItem | None:
    if len(dates) < 2:
        return None
    span_days = (dates[-1] - dates[0]).days
    if span_days <= 0:
        return None
    avg_interval = span_days / (len(dates) - 1)
    if avg_interval <= 0:
        return None
    days_since_last = (today - dates[-1]).days
    if days_since_last <= avg_interval:
        return None
    risk_percent = min(decimal.Decimal(99), decimal.Decimal(round((days_since_last / avg_interval - 1) * 100)))
    if risk_percent < _CHURN_RISK_MIN_PERCENT:
        return None
    severity = "danger" if risk_percent >= 70 else "warning"
    return ActionItem(
        severity=severity,
        category="churn_risk",
        customer_id=customer_id,
        customer_name=customer_name,
        title=f"مشتری «{customer_name}»",
        detail_lines=[
            f"آخرین خرید: {days_since_last} روز پیش",
            f"میانگینِ فاصله‌یِ خرید: هر {round(avg_interval)} روز",
            f"احتمالِ ریزش: {risk_percent:.0f}٪",
        ],
        suggested_action="تماس با مشتری",
        metric_percent=risk_percent,
    )


def _growth_item(
    customer_id: int,
    customer_name: str,
    docs_sorted: list,
    year_start: datetime.date,
    today: datetime.date,
    last_year_start: datetime.date,
    last_year_same_day: datetime.date,
    credit_limit_amount,
) -> ActionItem | None:
    this_year_total = sum(
        (d.total_amount or decimal.Decimal(0) for d in docs_sorted if d.document_date and year_start <= d.document_date <= today),
        decimal.Decimal(0),
    )
    last_year_total = sum(
        (
            d.total_amount or decimal.Decimal(0)
            for d in docs_sorted
            if d.document_date and last_year_start <= d.document_date <= last_year_same_day
        ),
        decimal.Decimal(0),
    )
    if last_year_total <= 0:
        return None
    growth_percent = decimal.Decimal(round(float((this_year_total - last_year_total) / last_year_total) * 100))
    if growth_percent < _GROWTH_MIN_PERCENT:
        return None
    from peecha import numerals

    credit_line = (
        f"سقفِ اعتبارِ فعلی: {numerals.format_company_amount(credit_limit_amount)}"
        if credit_limit_amount
        else "بدونِ سقفِ اعتبارِ تعریف‌شده"
    )
    return ActionItem(
        severity="success",
        category="growth",
        customer_id=customer_id,
        customer_name=customer_name,
        title=f"مشتری «{customer_name}»",
        detail_lines=[
            f"رشدِ خرید نسبت به مدتِ مشابهِ سالِ قبل: {growth_percent:.0f}٪",
            credit_line,
        ],
        suggested_action="افزایشِ سقفِ اعتبارِ مشتری",
        metric_percent=growth_percent,
    )


def _cross_sell_item(company_id: int, customer_id: int, customer_name: str, docs_sorted: list) -> ActionItem | None:
    doc_ids = [d.document_id for d in docs_sorted]
    if not doc_ids:
        return None
    latest_doc_id = docs_sorted[-1].document_id
    with new_session() as session:
        latest_item_ids = list(
            dict.fromkeys(
                session.scalars(
                    select(CommercialDocumentLine.item_id).where(CommercialDocumentLine.document_id == latest_doc_id)
                ).all()
            )
        )
    if not latest_item_ids:
        return None

    items_by_id = {i.item_id: i for i in catalog_service.list_items(company_id)}
    best_source_id = None
    best_suggestion = None
    for item_id in latest_item_ids:
        suggestions = documents_service.suggest_frequently_bought_together(
            company_id, item_id, limit=5, counterparty_detail_account_id=customer_id
        )
        for suggestion in suggestions:
            # طبقِ درخواستِ صریح («در ۳ خریدِ اخیر محصولِ A را خریده... این‌بار
            # محصولِ B را نخریده»): فقط کالاهایی که در همین آخرین فاکتور
            # هستند فیلتر می‌شوند، نه کلِ سابقه‌یِ عمرِ مشتری -- وگرنه کالایِ
            # مکملی که قبلاً هم خریداری شده دیگر هرگز دوباره پیشنهاد نمی‌شد.
            if suggestion.item_id in latest_item_ids:
                continue
            if best_suggestion is None or suggestion.confidence_percent > best_suggestion.confidence_percent:
                best_source_id = item_id
                best_suggestion = suggestion

    if best_suggestion is None or best_suggestion.confidence_percent < _CROSS_SELL_MIN_CONFIDENCE_PERCENT:
        return None
    source_item = items_by_id.get(best_source_id)
    source_name = source_item.name if source_item else ""
    return ActionItem(
        severity="warning",
        category="cross_sell",
        customer_id=customer_id,
        customer_name=customer_name,
        title=f"مشتری «{customer_name}»",
        detail_lines=[
            f"در خریدِ اخیر، «{source_name}» را خریداری کرده.",
            f"«{best_suggestion.item_name}» معمولاً همراهِ آن خریداری می‌شود.",
            f"احتمالِ خرید: {best_suggestion.confidence_percent:.0f}٪",
        ],
        suggested_action=f"پیشنهادِ فروشِ مکملِ «{best_suggestion.item_name}»",
        metric_percent=best_suggestion.confidence_percent,
    )


def get_daily_actions(company_id: int, limit: int = 5) -> list[ActionItem]:
    """فهرستِ رتبه‌بندی‌شده‌یِ مهم‌ترین اقداماتِ امروز -- طبقِ درخواستِ صریح
    («۵ اقدامِ مهمِ امروز»)، ابتدا بر اساسِ شدت (قرمز > زرد > سبز) و سپس
    بر اساسِ خودِ درصدِ معیار مرتب می‌شود."""
    today = datetime.date.today()
    # طبقِ همان مبنایِ سالِ مالیِ کلِ برنامه (که بر اساسِ تقویمِ جلالی
    # تعریف می‌شود، نه میلادی): «امسال»/«سالِ قبل» یعنی سالِ جلالیِ جاری
    # و ماقبلش -- وگرنه مرزِ ۱ ژانویه هیچ معنایی برایِ کاربرِ فارسی‌زبان
    # و برایِ سال‌هایِ مالیِ ثبت‌شده در دیتابیس ندارد.
    jalali_today = jdatetime.date.fromgregorian(date=today)
    year_start = jdatetime.date(jalali_today.year, 1, 1).togregorian()
    last_year_start = jdatetime.date(jalali_today.year - 1, 1, 1).togregorian()
    try:
        last_year_same_day = jdatetime.date(jalali_today.year - 1, jalali_today.month, jalali_today.day).togregorian()
    except ValueError:
        # ۲۹/۳۰ اسفند در سالِ غیرِکبیسه -- طبقِ قاعده‌یِ رایج، به ۲۹ برمی‌گردیم.
        last_year_same_day = jdatetime.date(jalali_today.year - 1, jalali_today.month, 29).togregorian()

    customers = [
        c for c in partners_service.list_customer_detail_accounts(company_id) if c.get("status_code") == "ACTIVE"
    ]

    items: list[ActionItem] = []
    for customer in customers:
        customer_id = customer["detail_account_id"]
        customer_name = customer.get("name") or customer.get("code") or str(customer_id)
        docs = documents_service.list_documents(
            company_id, document_type_code="SALES_INVOICE", status_code="POSTED",
            counterparty_detail_account_id=customer_id,
        )
        if not docs:
            continue
        docs_sorted = sorted(docs, key=lambda d: (d.document_date or today, d.document_id))
        dates = [d.document_date for d in docs_sorted if d.document_date is not None]

        churn_item = _churn_risk_item(customer_id, customer_name, dates, today)
        if churn_item is not None:
            items.append(churn_item)

        growth_item = _growth_item(
            customer_id, customer_name, docs_sorted, year_start, today, last_year_start, last_year_same_day,
            customer.get("credit_limit_amount"),
        )
        if growth_item is not None:
            items.append(growth_item)

        cross_sell_item = _cross_sell_item(company_id, customer_id, customer_name, docs_sorted)
        if cross_sell_item is not None:
            items.append(cross_sell_item)

    items.sort(key=lambda item: (_SEVERITY_RANK[item.severity], -float(item.metric_percent or 0)))
    return items[:limit]
