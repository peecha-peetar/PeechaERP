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
from peecha.services import commercial_credit as credit_service
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


def _jalali_year_bounds(today: datetime.date) -> tuple[datetime.date, datetime.date, datetime.date]:
    """طبقِ همان مبنایِ سالِ مالیِ کلِ برنامه (که بر اساسِ تقویمِ جلالی
    تعریف می‌شود، نه میلادی): «امسال»/«سالِ قبل» یعنی سالِ جلالیِ جاری و
    ماقبلش -- وگرنه مرزِ ۱ ژانویه هیچ معنایی برایِ کاربرِ فارسی‌زبان و
    برایِ سال‌هایِ مالیِ ثبت‌شده در دیتابیس ندارد. برمی‌گرداند:
    (شروعِ سالِ جاری، شروعِ سالِ قبل، همان‌روزِ سالِ قبل)."""
    jalali_today = jdatetime.date.fromgregorian(date=today)
    year_start = jdatetime.date(jalali_today.year, 1, 1).togregorian()
    last_year_start = jdatetime.date(jalali_today.year - 1, 1, 1).togregorian()
    try:
        last_year_same_day = jdatetime.date(jalali_today.year - 1, jalali_today.month, jalali_today.day).togregorian()
    except ValueError:
        # ۲۹/۳۰ اسفند در سالِ غیرِکبیسه -- طبقِ قاعده‌یِ رایج، به ۲۹ برمی‌گردیم.
        last_year_same_day = jdatetime.date(jalali_today.year - 1, jalali_today.month, 29).togregorian()
    return year_start, last_year_start, last_year_same_day


def _compute_growth_percent(
    docs_sorted: list,
    year_start: datetime.date,
    today: datetime.date,
    last_year_start: datetime.date,
    last_year_same_day: datetime.date,
) -> decimal.Decimal | None:
    """درصدِ رشدِ خریدِ امسال (تا امروز) نسبت به همان بازه‌یِ سالِ قبل --
    None یعنی مشتری سالِ قبل در این بازه خریدی نداشته (مبنایی برایِ
    مقایسه نیست)."""
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
    return decimal.Decimal(round(float((this_year_total - last_year_total) / last_year_total) * 100))


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
    growth_percent = _compute_growth_percent(docs_sorted, year_start, today, last_year_start, last_year_same_day)
    if growth_percent is None or growth_percent < _GROWTH_MIN_PERCENT:
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


def _credit_limit_exceeded_item(
    customer_id: int, customer_name: str, credit_limit_amount: decimal.Decimal, exposure: decimal.Decimal
) -> ActionItem | None:
    """طبقِ گزارشِ صریحِ کاربر («اعتبار ۵۰ میلیون بوده، بدهی ۸۰ میلیون شده،
    آیا نباید تاثیری داشته باشه؟»): طبقِ تصمیمِ طراحی، این یک هشدارِ
    مالیِ فوری و *مستقل* از امتیازِ ۰-۱۰۰ است -- عبورِ موقتِ یک مشتریِ
    باارزش از سقفِ اعتبار نباید امتیازِ کلیِ رابطه‌اش را پایین بیاورد،
    ولی همچنان باید فوراً به فروشنده هشدار داده شود، پس یک اقدامِ
    جداگانه با بالاترین اولویت (قرمز) در دستیارِ فروش می‌سازیم."""
    if not credit_limit_amount or exposure <= credit_limit_amount:
        return None
    from peecha import numerals

    over_amount = exposure - credit_limit_amount
    over_percent = min(decimal.Decimal(99), decimal.Decimal(round(float(over_amount / credit_limit_amount) * 100)))
    return ActionItem(
        severity="danger",
        category="credit_limit_exceeded",
        customer_id=customer_id,
        customer_name=customer_name,
        title=f"مشتری «{customer_name}»",
        detail_lines=[
            f"سقفِ اعتبار: {numerals.format_company_amount(credit_limit_amount)}",
            f"بدهیِ جاری: {numerals.format_company_amount(exposure)}",
            f"عبور از سقف: {numerals.format_company_amount(over_amount)} ({over_percent:.0f}٪)",
        ],
        suggested_action="توقفِ فروشِ نسیه تا وصولِ بخشی از مطالبات",
        metric_percent=over_percent,
    )


def get_daily_actions(company_id: int, limit: int = 5) -> list[ActionItem]:
    """فهرستِ رتبه‌بندی‌شده‌یِ مهم‌ترین اقداماتِ امروز -- طبقِ درخواستِ صریح
    («۵ اقدامِ مهمِ امروز»)، ابتدا بر اساسِ شدت (قرمز > زرد > سبز) و سپس
    بر اساسِ خودِ درصدِ معیار مرتب می‌شود."""
    today = datetime.date.today()
    year_start, last_year_start, last_year_same_day = _jalali_year_bounds(today)

    # باگِ واقعیِ کشف‌شده («رتبه‌بندی نمایش نمی‌دهد»): فیلترِ قبلیِ
    # status_code=="ACTIVE" با «فعال‌بودنِ حساب» (is_active) اشتباه گرفته
    # شده بود -- status_code وضعیتِ گردشِ کارِ *تاییدِ اعتباری* است
    # (comm.customer_profiles.status_code) که هر مشتریِ تازه‌ثبت‌شده از
    # طریقِ فرمِ معمولی با آن، در PENDING_APPROVAL می‌ماند مگر کسی صریحاً
    # «تاییدِ اعتباری» را بزند -- یعنی تقریباً هیچ مشتری‌ای امتیاز
    # نمی‌گرفت. list_customer_detail_accounts خودش از قبل فقط حساب‌هایِ
    # تفصیلیِ *فعالِ* برگ (is_active=True) را برمی‌گرداند، پس نیازی به
    # این فیلترِ اضافه‌یِ نادرست نیست.
    customers = partners_service.list_customer_detail_accounts(company_id)

    items: list[ActionItem] = []
    for customer in customers:
        customer_id = customer["detail_account_id"]
        customer_name = customer.get("name") or customer.get("code") or str(customer_id)

        credit_limit_amount = customer.get("credit_limit_amount")
        if credit_limit_amount:
            exposure = credit_service.compute_customer_exposure(company_id, customer_id)
            credit_item = _credit_limit_exceeded_item(customer_id, customer_name, credit_limit_amount, exposure)
            if credit_item is not None:
                items.append(credit_item)

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


# ---------------------------------------------------------------------
# رتبه‌بندیِ هوشمندِ مشتریان (طبقِ درخواستِ صریح: «Customer Score... هر
# مشتری یک امتیاز... VIP/در حالِ رشد/نیازمندِ پیگیری/در معرضِ ریزش/
# کم‌ارزش») -- طبقِ تصمیمِ طراحیِ توافق‌شده، این امتیاز به‌جایِ یک
# داشبوردِ جداگانه، به‌صورتِ یک بَج در فرم‌هایِ موجود (فرمِ فاکتور و فرمِ
# تعریفِ مشتری) نمایش داده می‌شود.
# ---------------------------------------------------------------------
_TIER_LABELS = {
    "VIP": "VIP",
    "GROWING": "در حالِ رشد",
    "NEEDS_ATTENTION": "نیازمندِ پیگیری",
    "AT_RISK": "در معرضِ ریزش",
    "LOW_VALUE": "کم‌ارزش",
}
_TIER_EMOJI = {"VIP": "🟢", "GROWING": "🔵", "NEEDS_ATTENTION": "🟡", "AT_RISK": "🔴", "LOW_VALUE": "⚫"}


@dataclass
class CustomerScoreRow:
    customer_id: int
    customer_name: str
    score: int  # ۰ تا ۱۰۰
    tier: str  # "VIP" | "GROWING" | "NEEDS_ATTENTION" | "AT_RISK" | "LOW_VALUE"
    invoice_count_12m: int
    revenue_12m: decimal.Decimal
    days_since_last: int | None
    avg_interval_days: float | None
    growth_percent: decimal.Decimal | None
    # طبقِ تصمیمِ طراحیِ توافق‌شده (بنگرید توضیحِ _credit_limit_exceeded_item):
    # عبورِ از سقفِ اعتبار عمداً در امتیازِ ۰-۱۰۰ بالا دخیل نمی‌شود --
    # یک پرچمِ کاملاً جدا و فوری است، مستقلِ از ارزشِ کلیِ رابطه.
    credit_limit_amount: decimal.Decimal | None = None
    current_exposure: decimal.Decimal | None = None

    @property
    def over_credit_limit(self) -> bool:
        return bool(self.credit_limit_amount) and self.current_exposure is not None and self.current_exposure > self.credit_limit_amount

    @property
    def emoji(self) -> str:
        return _TIER_EMOJI[self.tier]

    @property
    def tier_label(self) -> str:
        return _TIER_LABELS[self.tier]


def _percentile_rank(value: float, sorted_values: list[float]) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return 100.0 if value > 0 else 0.0
    rank = sum(1 for v in sorted_values if v <= value)
    return (rank - 1) / (len(sorted_values) - 1) * 100


def list_customer_scores(company_id: int) -> list[CustomerScoreRow]:
    """امتیازی از ۰ تا ۱۰۰ برایِ هر مشتریِ فعال، از ترکیبِ چهار معیارِ
    نرمال‌شده (صدک‌بندی‌شده در میانِ همان مشتریانِ فعال):
      - تکرارِ خرید (۳۰٪): تعدادِ فاکتورِ پُست‌شده‌یِ ۱۲‌ماهِ اخیر.
      - حجمِ مالی (۳۰٪): جمعِ مبلغِ فروشِ ۱۲‌ماهِ اخیر.
      - تازگیِ خرید (۲۵٪): فاصله‌یِ آخرین خرید نسبت به میانگینِ تاریخیِ
        خودِ همان مشتری (نه مقایسه با بقیه).
      - رشد (۱۵٪): رشدِ خریدِ امسال نسبت به مدتِ مشابهِ سالِ قبل.
    مشتریِ بدونِ هیچ فاکتورِ ۱۲‌ماهِ اخیر همیشه «کم‌ارزش» با امتیازِ صفر
    است -- بدونِ فعالیتِ اخیر، محاسبه‌یِ صدک بی‌معناست."""
    today = datetime.date.today()
    year_start, last_year_start, last_year_same_day = _jalali_year_bounds(today)
    twelve_months_ago = today - datetime.timedelta(days=365)

    # طبقِ رفعِ باگِ واقعی (نبودِ status_code=="ACTIVE" با is_active خلط
    # شده بود -- بنگرید توضیحِ کاملِ آن در get_daily_actions):
    # list_customer_detail_accounts خودش فقط حساب‌هایِ فعالِ برگ را
    # می‌دهد، پس فیلترِ اضافه‌یِ گردشِ‌کارِ اعتباری نباید این‌جا اعمال شود.
    customers = partners_service.list_customer_detail_accounts(company_id)

    raw: list[tuple] = []
    for customer in customers:
        customer_id = customer["detail_account_id"]
        customer_name = customer.get("name") or customer.get("code") or str(customer_id)
        credit_limit_amount = customer.get("credit_limit_amount") or None
        current_exposure = credit_service.compute_customer_exposure(company_id, customer_id) if credit_limit_amount else None
        docs = documents_service.list_documents(
            company_id, document_type_code="SALES_INVOICE", status_code="POSTED",
            counterparty_detail_account_id=customer_id,
        )
        if not docs:
            raw.append((customer_id, customer_name, 0, decimal.Decimal(0), None, None, None, credit_limit_amount, current_exposure))
            continue
        docs_sorted = sorted(docs, key=lambda d: (d.document_date or today, d.document_id))
        dates = [d.document_date for d in docs_sorted if d.document_date is not None]
        recent_docs = [d for d in docs_sorted if d.document_date and d.document_date >= twelve_months_ago]
        invoice_count_12m = len(recent_docs)
        revenue_12m = sum((d.total_amount or decimal.Decimal(0) for d in recent_docs), decimal.Decimal(0))
        days_since_last = (today - dates[-1]).days if dates else None
        avg_interval_days = None
        if len(dates) >= 2:
            span_days = (dates[-1] - dates[0]).days
            if span_days > 0:
                avg_interval_days = span_days / (len(dates) - 1)
        growth_percent = _compute_growth_percent(docs_sorted, year_start, today, last_year_start, last_year_same_day)
        raw.append(
            (
                customer_id, customer_name, invoice_count_12m, revenue_12m, days_since_last, avg_interval_days,
                growth_percent, credit_limit_amount, current_exposure,
            )
        )

    freq_values = [float(r[2]) for r in raw]
    revenue_values = [float(r[3]) for r in raw]

    rows: list[CustomerScoreRow] = []
    for (
        customer_id, customer_name, invoice_count_12m, revenue_12m, days_since_last, avg_interval_days,
        growth_percent, credit_limit_amount, current_exposure,
    ) in raw:
        if invoice_count_12m == 0:
            rows.append(
                CustomerScoreRow(
                    customer_id=customer_id, customer_name=customer_name, score=0, tier="LOW_VALUE",
                    invoice_count_12m=0, revenue_12m=decimal.Decimal(0), days_since_last=days_since_last,
                    avg_interval_days=avg_interval_days, growth_percent=growth_percent,
                    credit_limit_amount=credit_limit_amount, current_exposure=current_exposure,
                )
            )
            continue

        frequency_score = _percentile_rank(float(invoice_count_12m), freq_values)
        monetary_score = _percentile_rank(float(revenue_12m), revenue_values)
        if days_since_last is None or avg_interval_days is None or avg_interval_days <= 0:
            recency_score = 60.0
        else:
            ratio = days_since_last / avg_interval_days
            recency_score = max(0.0, min(100.0, 100 - (ratio - 1) * 50))
        growth_score = 50.0 if growth_percent is None else max(0.0, min(100.0, 50 + float(growth_percent) / 4))

        score = round(frequency_score * 0.30 + monetary_score * 0.30 + recency_score * 0.25 + growth_score * 0.15)
        score = max(1, min(100, score))
        if score >= 80:
            tier = "VIP"
        elif score >= 60:
            tier = "GROWING"
        elif score >= 40:
            tier = "NEEDS_ATTENTION"
        else:
            tier = "AT_RISK"

        rows.append(
            CustomerScoreRow(
                customer_id=customer_id, customer_name=customer_name, score=score, tier=tier,
                invoice_count_12m=invoice_count_12m, revenue_12m=revenue_12m, days_since_last=days_since_last,
                avg_interval_days=avg_interval_days, growth_percent=growth_percent,
                credit_limit_amount=credit_limit_amount, current_exposure=current_exposure,
            )
        )
    return rows


def get_customer_score(company_id: int, customer_id: int) -> CustomerScoreRow | None:
    return next((row for row in list_customer_scores(company_id) if row.customer_id == customer_id), None)
