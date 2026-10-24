"""داشبورد مدیریتی و داشبورد استثناهای خرید — R239 (مرحلهٔ ۲).

فقط لایهٔ نمایش: هر شاخص/استثنا از خروجی همان گزارش‌های services/purchase_reports
ساخته می‌شود (منطق جدیدی برای محاسبه ندارد) و کد گزارش مبدا را برای ریزنمایی
همراه دارد؛ پس عدد داشبورد همیشه با جمع گزارش مربوط یکی است.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field

from peecha.services import inventory_catalog as catalog_service
from peecha.services import purchase_reports as reports

_ZERO = decimal.Decimal(0)
_EPOCH = datetime.date(1900, 1, 1)


def filters_for(code: str, date_from: datetime.date, date_to: datetime.date, side: str = "PURCHASE",
                **kw) -> reports.PurchaseFilters:
    """همان قاعدهٔ صفحهٔ گزارش برای تاریخ: as_of = از ابتدا، none = از ابتدا تا امروز."""
    mode = reports.report_def(code, side).date_mode
    if mode == "none":
        date_from, date_to = _EPOCH, datetime.date.today()
    elif mode == "as_of":
        date_from = _EPOCH
    return reports.PurchaseFilters(date_from, date_to, side=side, **kw)


def _run(company_id: int, code: str, date_from, date_to, **options) -> reports.ReportResult:
    return reports.run_report(company_id, code, filters_for(code, date_from, date_to, options=options))


def column(result: reports.ReportResult, header: str) -> int:
    return [h for h, _k in result.columns].index(header)


def total(result: reports.ReportResult, header: str) -> decimal.Decimal:
    i = column(result, header)
    return sum((decimal.Decimal(r[i]) for r in result.rows if r[i] not in (None, "")), _ZERO)


@dataclass
class Kpi:
    code: str
    title: str
    value: decimal.Decimal | int | None
    kind: str  # MONEY | INT | PERCENT | DAYS
    report_code: str
    formula: str
    options: dict = field(default_factory=dict)


def executive_kpis(company_id: int, date_from: datetime.date, date_to: datetime.date) -> list[Kpi]:
    by_supplier = _run(company_id, "BY_SUPPLIER", date_from, date_to)
    gross = total(by_supplier, "مبلغ ناخالص")
    net = total(by_supplier, "خالص خرید")
    otd = _run(company_id, "OTD", date_from, date_to)
    received, on_time = total(otd, "سفارش‌های دریافت‌شده"), total(otd, "به‌موقع")
    aging = _run(company_id, "AGING", date_from, date_to)
    overdue = sum((total(aging, h) for h in ("۱–۳۰ روز", "۳۱–۶۰ روز", "۶۱–۹۰ روز", "بیش از ۹۰ روز")), _ZERO)
    returns = total(_run(company_id, "RETURNS", date_from, date_to), "مبلغ")
    cycle = _run(company_id, "CYCLE_TIME", date_from, date_to)
    overall = [r for r in cycle.rows if r[0].startswith("—")]
    po_to_receipt = overall[0][column(cycle, "سفارش→رسید")] if overall else None
    return [
        Kpi("NET", "خالص خرید", net, "MONEY", "BY_SUPPLIER", "Σ (مبلغ خالص فاکتورهای خرید − برگشتی‌ها)، بدون مالیات"),
        Kpi("INVOICES", "تعداد فاکتور خرید", int(total(by_supplier, "تعداد فاکتور")), "INT", "REG_INVOICE",
            "تعداد فاکتورهای خرید ثبت‌شده در بازه"),
        Kpi("SUPPLIERS", "تامین‌کنندگان فعال", len(by_supplier.rows), "INT", "BY_SUPPLIER", "تامین‌کنندگان دارای خرید در بازه"),
        Kpi("OPEN_PO", "ارزش سفارش‌های باز", total(_run(company_id, "OPEN_PO", date_from, date_to), "ارزش مانده"), "MONEY",
            "OPEN_PO", "Σ (مقدار ماندهٔ سفارش × فی واحد پایه)"),
        Kpi("GRIR", "رسیده ولی فاکتورنشده", total(_run(company_id, "GRIR", date_from, date_to), "ارزش فاکتورنشده"), "MONEY",
            "GRIR", "Σ (رسیده − فاکتورشده) × فی سفارش"),
        Kpi("PAYABLE", "بدهی به تامین‌کنندگان", total(_run(company_id, "BALANCES", date_from, date_to), "ماندهٔ پایان دوره"),
            "MONEY", "BALANCES", "ماندهٔ حساب پرداختنی تامین‌کنندگان در «تا تاریخ»"),
        Kpi("OVERDUE", "بدهی سررسیدگذشته", overdue, "MONEY", "UNPAID", "Σ ماندهٔ فاکتورهای باز گذشته از سررسید",
            {"view": "OVERDUE"}),
        Kpi("OTD", "تحویل به‌موقع", (on_time * 100 / received) if received else None, "PERCENT", "OTD",
            "سفارش‌های رسیده تا تاریخ تحویل مورد انتظار ÷ سفارش‌های رسیدهٔ دارای تاریخ تحویل"),
        Kpi("RETURN_RATE", "نرخ برگشت", (returns * 100 / gross) if gross else None, "PERCENT", "RETURNS",
            "مبلغ برگشت به تامین‌کننده ÷ مبلغ ناخالص خرید"),
        Kpi("PPV", "اثر انحراف قیمت", total(_run(company_id, "PPV", date_from, date_to), "اثر ریالی"), "MONEY", "PPV",
            "Σ (فی فاکتور − فی مبنا) × مقدار؛ مثبت = گران‌تر"),
        Kpi("CYCLE", "میانگین سفارش تا رسید", po_to_receipt, "DAYS", "CYCLE_TIME", "میانگین روز از تاریخ سفارش تا رسید انبار"),
        Kpi("APPROVALS", "منتظر تصویب مدیر", len(_run(company_id, "APPROVAL_PENDING", date_from, date_to).rows), "INT",
            "APPROVAL_PENDING", "اسناد تاییدشده‌ای که تصویب مدیر لازم دارند و هنوز تصویب نشده‌اند"),
    ]


def executive_charts(company_id: int, date_from: datetime.date, date_to: datetime.date) -> dict[str, list[tuple[str, decimal.Decimal]]]:
    monthly = _run(company_id, "MONTHLY", date_from, date_to)
    by_supplier = _run(company_id, "BY_SUPPLIER", date_from, date_to)
    by_item = _run(company_id, "BY_ITEM", date_from, date_to)
    by_category = _run(company_id, "BY_CATEGORY", date_from, date_to)
    aging = _run(company_id, "AGING", date_from, date_to)

    def top(result, label_header, value_header, n=10):
        li, vi = column(result, label_header), column(result, value_header)
        rows = sorted(((r[li], decimal.Decimal(r[vi] or 0)) for r in result.rows), key=lambda x: -x[1])
        return rows[:n]

    mi, mv = column(monthly, "ماه"), column(monthly, "خالص")
    buckets = ("سررسیدنشده", "۱–۳۰ روز", "۳۱–۶۰ روز", "۶۱–۹۰ روز", "بیش از ۹۰ روز")
    return {
        "monthly": [(r[mi], decimal.Decimal(r[mv] or 0)) for r in monthly.rows],
        "suppliers": top(by_supplier, "تامین‌کننده", "خالص خرید"),
        "items": top(by_item, "کالا", "خالص مبلغ"),
        "categories": top(by_category, "گروه کالا", "خالص", 8),
        "aging": [(b, total(aging, b)) for b in buckets],
    }


@dataclass
class ExceptionRow:
    code: str
    title: str
    severity: str  # HIGH | MEDIUM | LOW
    count: int
    amount: decimal.Decimal | None
    report_code: str
    hint: str
    options: dict = field(default_factory=dict)


SEVERITY_LABELS = {"HIGH": "بالا", "MEDIUM": "متوسط", "LOW": "پایین"}

# (کد، عنوان، شدت، گزارش، گزینه‌ها، ستونِ مبلغ، توضیح)
_EXCEPTIONS = (
    ("THREE_WAY", "مغایرت سه‌طرفهٔ سفارش/رسید/فاکتور", "HIGH", "THREE_WAY", {"view": "ISSUES"}, "اختلاف ریالی فی",
     "ردیف‌های سفارش با مغایرت مقدار یا فی"),
    ("INVOICE_NO_RECEIPT", "فاکتور بدون رسید", "HIGH", "INVOICE_NO_RECEIPT", {}, None, "پرداختنی ثبت‌شده برای کالای نرسیده"),
    ("INVOICE_OVER_PO", "فاکتور بیش از سفارش", "HIGH", "INVOICE_OVER_PO", {}, "اختلاف ریالی فی", "مقدار یا فی فاکتور بالاتر از سفارش"),
    ("RECEIPT_OVER_PO", "رسید بیش از سفارش", "MEDIUM", "RECEIPT_OVER_PO", {}, None, "کالای مازاد بر سفارش"),
    ("PRICE_ABOVE", "خرید بالاتر از فی سفارش", "MEDIUM", "PRICE_VS_REFERENCE", {"reference": "ORDER", "direction": "ABOVE"},
     "اثر ریالی", "فاکتورهایی که از فی سفارش مبدا گران‌ترند"),
    ("NO_PO", "خرید بدون سفارش", "MEDIUM", "NO_PO", {}, "مبلغ خالص", "خرید مستقیم بدون سفارش/پیش‌فاکتور"),
    ("OVERDUE", "بدهی سررسیدگذشته", "HIGH", "UNPAID", {"view": "OVERDUE"}, "مانده", "فاکتورهای پرداخت‌نشدهٔ گذشته از سررسید"),
    ("LATE_ORDERS", "سفارش‌های دیرکرد", "MEDIUM", "LATE_ORDERS", {}, "مبلغ", "گذشته از تاریخ تحویل مورد انتظار"),
    ("APPROVALS", "منتظر تصویب مدیر", "LOW", "APPROVAL_PENDING", {}, "مبلغ", "اسناد معطل تصویب"),
    ("BELOW_ROP", "کالای زیر نقطهٔ سفارش", "HIGH", "STOCK_POLICY", {"view": "BELOW_ROP"}, None, "نیاز به سفارش خرید"),
    ("DEMAND_NO_PO", "تقاضای فروش بدون پوشش", "HIGH", "DEMAND_NO_PO", {}, None, "سفارش فروشی که موجودی/خرید درراه ندارد"),
    ("GRIR", "رسیده ولی فاکتورنشده", "LOW", "GRIR", {}, "ارزش فاکتورنشده", "رسیدهای منتظر فاکتور"),
    ("DEAD_STOCK", "کالای راکد", "LOW", "SLOW_DEAD", {"view": "DEAD"}, "ارزش موجودی", "موجودی بدون فروش/مصرف در ۱۸۰ روز"),
    ("CANCELLED", "اسناد خرید لغوشده", "LOW", "CANCELLED", {}, "مبلغ", "لغوشده در بازه"),
)


def exceptions(company_id: int, date_from: datetime.date, date_to: datetime.date) -> list[ExceptionRow]:
    out = []
    for code, title, severity, report_code, options, amount_header, hint in _EXCEPTIONS:
        result = _run(company_id, report_code, date_from, date_to, **options)
        amount = total(result, amount_header) if amount_header else None
        out.append(ExceptionRow(code, title, severity, len(result.rows), amount, report_code, hint, dict(options)))
    return out


# =====================================================================
# Drill-down از ردیفِ تجمیعی (تامین‌کننده/مشتری، کالا، گروهِ کالا) به ریزِ آن
# =====================================================================
_FINANCE_GROUPS = ("مالی و بدهی", "مالی و مطالبات")


def drill_target(company_id: int, code: str, side: str, row: list) -> tuple[str, dict] | None:
    """ردیفی که سند نیست: اولین برچسب شناخته‌شده (طرف حساب/کالا/گروه) را پیدا می‌کند و
    (کد گزارش مقصد، فیلترها) برمی‌گرداند — مالی → صورت‌حساب، بقیه → ریز اقلام فاکتور."""
    ctx = reports._ctx(company_id)
    parties = {label: pid for pid, label in ctx.names.items()}
    items = {ctx.item_label(i): i for i in ctx.items}
    categories = {f"{c.code} — {c.name}": c.category_id for c in catalog_service.list_categories(company_id)}
    defn = reports.report_def(code, side)
    for cell in row:
        if not isinstance(cell, str) or " — " not in cell:
            continue
        if cell in items:
            return "REG_INVOICE_LINES", {"item_id": items[cell]}
        if cell in categories:
            return "REG_INVOICE_LINES", {"category_id": categories[cell]}
        if cell in parties:
            target = "STATEMENT" if defn.group in _FINANCE_GROUPS else "REG_INVOICE_LINES"
            return target, {"supplier_id": parties[cell]}
    return None
