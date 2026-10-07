"""گزارش‌های تکمیلی خرید — R245 (فقط خواندنی، مثل بقیهٔ گزارش‌ها).

مالیات بر ارزش افزوده، مقایسهٔ دوره‌ای، آخرین خرید، فاکتور تکراری، خرید به تفکیک ارز،
قراردادهای در آستانهٔ انقضا، سهم تامین‌کنندگان از هر کالا، دورهٔ پرداخت بدهی،
قیمت خرید در برابر فروش.
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict

import jdatetime
from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import CommercialContract, CommercialDocument
from peecha.db.models.core import Currency
from peecha.services import purchase_reports as base
from peecha.services.purchase_reports import DATE, DAYS, INT, MONEY, PERCENT, QTY, TEXT, ReportDef, ReportResult

_ZERO = decimal.Decimal(0)
_Q2 = decimal.Decimal("0.01")
_LIVE = ("CONFIRMED", "APPROVED", "POSTED")


def _pct(part, whole):
    return (part * 100 / whole).quantize(decimal.Decimal("0.1")) if whole else None


def _period(value: datetime.date, period: str) -> str:
    j = jdatetime.date.fromgregorian(date=value)
    return f"{j.year}-فصل {(j.month - 1) // 3 + 1}" if period == "QUARTER" else f"{j.year}/{j.month:02d}"


def _shift(f, compare: str):
    if compare == "PREV_YEAR":
        from peecha.services.accounting_reports import _shift_year

        return _shift_year(f.date_from, -1), _shift_year(f.date_to, -1)
    span = f.date_to - f.date_from
    prev_to = f.date_from - datetime.timedelta(days=1)
    return prev_to - span, prev_to


def vat_report(company_id: int, f) -> ReportResult:
    """مبلغ خالص و مالیات فاکتورهای ثبت‌شده منهای برگشتی‌ها، به تفکیک دوره و تامین‌کننده."""
    S = base._side(f)
    ctx = base._ctx(company_id)
    period = f.options.get("period") or "QUARTER"
    agg: dict[tuple, list] = {}
    for sign, type_code in ((1, S.invoice), (-1, S.ret)):
        for doc, ln in base._lines(company_id, (type_code,), ("POSTED",), f, ctx):
            key = (_period(doc.document_date, period), doc.counterparty_detail_account_id)
            row = agg.setdefault(key, [_ZERO, _ZERO, set(), set()])
            row[0] += sign * base._net(ln)
            row[1] += sign * (ln.tax_amount or _ZERO)
            (row[2] if sign > 0 else row[3]).add(doc.document_id)
    r = ReportResult([("دوره", TEXT), ("تامین‌کننده", TEXT), ("مبلغ خالص", MONEY), ("مالیات و عوارض", MONEY),
                      ("جمع با مالیات", MONEY), ("تعداد فاکتور", INT), ("تعداد برگشتی", INT)])
    for (key_period, party), (net, tax, invoices, returns) in sorted(agg.items(), key=lambda kv: (kv[0][0], ctx.names.get(kv[0][1], ""))):
        r.add([key_period, ctx.names.get(party, ""), net, tax, net + tax, len(invoices), len(returns)])
    r.note = "برگشتی‌ها با علامت منفی کسر شده‌اند؛ اسناد معاف از مالیات با مالیات صفر آمده‌اند."
    return r


_COMPARE_BY = (("SUPPLIER", "تامین‌کننده"), ("ITEM", "کالا"), ("CATEGORY", "گروه کالا"))


def period_comparison(company_id: int, f) -> ReportResult:
    S = base._side(f)
    ctx = base._ctx(company_id)
    by = f.options.get("by") or "SUPPLIER"
    prev_from, prev_to = _shift(f, f.options.get("compare") or "PREV_YEAR")
    categories = {}
    if by == "CATEGORY":
        from peecha.services import inventory_catalog as catalog_service

        categories = {c.category_id: f"{c.code} — {c.name}" for c in catalog_service.list_categories(company_id)}

    def label(doc, ln):
        if by == "ITEM":
            return ctx.item_label(ln.item_id)
        if by == "CATEGORY":
            item = ctx.items.get(ln.item_id)
            return categories.get(item.category_id, "—") if item else "—"
        return ctx.names.get(doc.counterparty_detail_account_id, "")

    def totals(date_from, date_to):
        g = base.PurchaseFilters(date_from, date_to, f.supplier_id, f.item_id, f.category_id, f.warehouse_id, f.side)
        out: dict[str, decimal.Decimal] = defaultdict(lambda: _ZERO)
        for sign, type_code in ((1, S.invoice), (-1, S.ret)):
            for doc, ln in base._lines(company_id, (type_code,), ("POSTED",), g, ctx):
                out[label(doc, ln)] += sign * base._net(ln)
        return out

    current, previous = totals(f.date_from, f.date_to), totals(prev_from, prev_to)
    r = ReportResult([(dict(_COMPARE_BY)[by], TEXT), ("خرید دورهٔ جاری", MONEY), ("خرید دورهٔ مقایسه", MONEY), ("تغییر", MONEY),
                      ("درصد تغییر", PERCENT)], no_total={4})
    for key in sorted(set(current) | set(previous), key=lambda k: -(current.get(k, _ZERO))):
        cur, prev = current.get(key, _ZERO), previous.get(key, _ZERO)
        r.add([key, cur, prev, cur - prev, _pct(cur - prev, abs(prev))])
    from peecha import numerals

    r.note = f"دورهٔ مقایسه: {numerals.format_jalali_date(prev_from)} تا {numerals.format_jalali_date(prev_to)} -- خالص خرید پس از برگشتی."
    return r


def last_purchase(company_id: int, f) -> ReportResult:
    S = base._side(f)
    ctx = base._ctx(company_id)
    last: dict[int, tuple] = {}
    suppliers: dict[int, set] = defaultdict(set)
    for doc, ln in base._lines(company_id, (S.invoice,), _LIVE, f, ctx, dated=False):
        if doc.document_date > f.date_to:
            continue
        suppliers[ln.item_id].add(doc.counterparty_detail_account_id)
        last[ln.item_id] = (doc, ln)
    r = ReportResult([("کالا", TEXT), ("واحد", TEXT), ("تاریخ آخرین خرید", DATE), ("روز از آخرین خرید", DAYS), ("تامین‌کننده", TEXT),
                      ("مقدار", QTY), ("فی واحد پایه", MONEY), ("تعداد تامین‌کنندهٔ سابقه‌دار", INT)], no_total={6, 7})
    for item_id, (doc, ln) in sorted(last.items(), key=lambda kv: kv[1][0].document_date):
        r.add([ctx.item_label(item_id), ctx.base_uom(item_id), doc.document_date, (f.date_to - doc.document_date).days,
               ctx.names.get(doc.counterparty_detail_account_id, ""), ln.quantity_base, base._base_price(ln),
               len(suppliers[item_id])], (doc.document_id, doc.document_type_code))
    return r


def duplicate_invoices(company_id: int, f) -> ReportResult:
    """هم‌تامین‌کننده با شمارهٔ مرجع یکسان، یا هم‌تامین‌کننده و هم‌مبلغ با فاصلهٔ حداکثر ۷ روز."""
    S = base._side(f)
    with new_session() as session:
        docs = list(session.scalars(select(CommercialDocument).where(
            CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == S.invoice,
            CommercialDocument.status_code != "CANCELLED", CommercialDocument.corrects_document_id.is_(None),
            CommercialDocument.document_date.between(f.date_from, f.date_to))
            .order_by(CommercialDocument.document_date)))
    if f.supplier_id is not None:
        docs = [d for d in docs if d.counterparty_detail_account_id == f.supplier_id]
    ctx = base._ctx(company_id)
    flagged: dict[int, str] = {}
    by_ref: dict[tuple, list] = defaultdict(list)
    by_party: dict[int, list] = defaultdict(list)
    for d in docs:
        if (d.reference_no or "").strip():
            by_ref[(d.counterparty_detail_account_id, d.reference_no.strip())].append(d)
        by_party[d.counterparty_detail_account_id].append(d)
    for group in by_ref.values():
        if len(group) > 1:
            for d in group:
                flagged[d.document_id] = f"شمارهٔ مرجع تکراری «{d.reference_no.strip()}»"
    for group in by_party.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if (b.document_date - a.document_date).days > 7:
                    break
                if a.total_amount == b.total_amount and a.total_amount:
                    for d in (a, b):
                        flagged.setdefault(d.document_id, "مبلغ یکسان در فاصلهٔ ۷ روز")
    r = ReportResult([("تاریخ", DATE), ("شماره", TEXT), ("تامین‌کننده", TEXT), ("شمارهٔ مرجع", TEXT), ("مبلغ", MONEY),
                      ("وضعیت", TEXT), ("علت", TEXT)])
    for d in docs:
        if d.document_id in flagged:
            r.add([d.document_date, d.document_no or str(d.document_id), ctx.names.get(d.counterparty_detail_account_id, ""),
                   d.reference_no or "", d.total_amount, base._STAGE_LABELS.get(d.status_code, d.status_code),
                   flagged[d.document_id]], (d.document_id, d.document_type_code))
    if not r.rows:
        r.note = "فاکتور مشکوک به تکرار پیدا نشد."
    return r


def by_currency(company_id: int, f) -> ReportResult:
    S = base._side(f)
    ctx = base._ctx(company_id)
    with new_session() as session:
        codes = dict(session.execute(select(Currency.currency_id, Currency.iso_code)).all())
    base_id = None
    try:
        from peecha.services import purchase_requests as pr_service

        base_id = pr_service._base_currency(company_id)
    except Exception:  # noqa: BLE001 -- فقط برایِ علامت‌گذاریِ ارزِ پایه
        base_id = None
    agg: dict[int, list] = {}
    for doc, ln in base._lines(company_id, (S.invoice,), ("POSTED",), f, ctx):
        row = agg.setdefault(doc.currency_id, [set(), _ZERO, _ZERO, set()])
        row[0].add(doc.document_id)
        net = base._net(ln)
        row[1] += net
        row[2] += (net * (doc.exchange_rate or 1)).quantize(_Q2)
        row[3].add(doc.counterparty_detail_account_id)
    total = sum((v[2] for v in agg.values()), _ZERO)
    r = ReportResult([("ارز", TEXT), ("تعداد فاکتور", INT), ("مبلغ به ارز سند", MONEY), ("معادل ارز پایه", MONEY),
                      ("نرخ میانگین", MONEY), ("تعداد تامین‌کننده", INT), ("سهم", PERCENT)], no_total={2, 4})
    for currency_id, (docs, fc, base_amount, parties) in sorted(agg.items(), key=lambda kv: -kv[1][2]):
        label = codes.get(currency_id, str(currency_id)) + (" (پایه)" if currency_id == base_id else "")
        r.add([label, len(docs), fc, base_amount, (base_amount / fc).quantize(_Q2) if fc else None, len(parties),
               _pct(base_amount, total)])
    if len(agg) > 1:
        r.note = ("توجه: بقیهٔ گزارش‌های خرید مبلغ را به ارز سند جمع می‌زنند؛ وقتی فاکتور ارزی دارید، "
                  "برای مبلغ ریالی از ستون «معادل ارز پایه» همین گزارش استفاده کنید.")
    return r


_DAYS_OPTION = ("days", "بازهٔ هشدار", (("60", "۶۰ روز"), ("30", "۳۰ روز"), ("90", "۹۰ روز"), ("180", "۱۸۰ روز")))


def expiring_contracts(company_id: int, f) -> ReportResult:
    S = base._side(f)
    ctx = base._ctx(company_id)
    days = int(f.options.get("days") or 60)
    with new_session() as session:
        contracts = list(session.scalars(select(CommercialContract).where(
            CommercialContract.company_id == company_id, CommercialContract.contract_type_code == S.code,
            CommercialContract.status_code == "ACTIVE", CommercialContract.valid_to.is_not(None))))
    r = ReportResult([("تامین‌کننده", TEXT), ("کالا", TEXT), ("شروع", DATE), ("پایان", DATE), ("روز مانده", DAYS),
                      ("مقدار تعهد", QTY), ("مصرف‌شده", QTY), ("درصد مصرف مقدار", PERCENT), ("مبلغ تعهد", MONEY),
                      ("مبلغ مصرف‌شده", MONEY), ("وضعیت", TEXT)], no_total={4, 7})
    for c in sorted(contracts, key=lambda c: c.valid_to):
        if f.supplier_id is not None and c.counterparty_detail_account_id != f.supplier_id:
            continue
        left = (c.valid_to - f.date_to).days
        if left > days:
            continue
        r.add([ctx.names.get(c.counterparty_detail_account_id, ""), ctx.item_label(c.item_id) if c.item_id else "همهٔ کالاها",
               c.valid_from, c.valid_to, left, c.committed_quantity, c.consumed_quantity,
               _pct(c.consumed_quantity or _ZERO, c.committed_quantity or _ZERO), c.committed_amount, c.consumed_amount,
               "منقضی‌شده ولی فعال" if left < 0 else "در آستانهٔ انقضا"])
    return r


def supplier_share_by_item(company_id: int, f) -> ReportResult:
    S = base._side(f)
    ctx = base._ctx(company_id)
    agg: dict[tuple, list] = {}
    item_total: dict[int, decimal.Decimal] = defaultdict(lambda: _ZERO)
    for doc, ln in base._lines(company_id, (S.invoice,), ("POSTED",), f, ctx):
        row = agg.setdefault((ln.item_id, doc.counterparty_detail_account_id), [_ZERO, _ZERO, set()])
        net = base._net(ln)
        row[0] += ln.quantity_base
        row[1] += net
        row[2].add(doc.document_id)
        item_total[ln.item_id] += net
    r = ReportResult([("کالا", TEXT), ("تامین‌کننده", TEXT), ("مقدار", QTY), ("مبلغ", MONEY), ("فی میانگین", MONEY),
                      ("سهم از خرید کالا", PERCENT), ("رتبه", INT), ("تعداد فاکتور", INT)], no_total={4, 6})
    ranked = sorted(agg.items(), key=lambda kv: (ctx.item_label(kv[0][0]), -kv[1][1]))
    rank, current = 0, None
    for (item_id, party), (qty, amount, docs) in ranked:
        rank = rank + 1 if item_id == current else 1
        current = item_id
        r.add([ctx.item_label(item_id), ctx.names.get(party, ""), qty, amount, (amount / qty).quantize(_Q2) if qty else None,
               _pct(amount, item_total[item_id]), rank, len(docs)])
    return r


def days_payable(company_id: int, f) -> ReportResult:
    """DPO = ماندهٔ پایان دوره ÷ بستانکار دوره (خرید) × تعداد روز بازه — از روی حساب پرداختنی دفتر."""
    S = base._side(f)
    ctx = base._ctx(company_id)
    days = (f.date_to - f.date_from).days + 1
    r = ReportResult([("تامین‌کننده", TEXT), ("ماندهٔ ابتدا", MONEY), ("خرید/بستانکار دوره", MONEY), ("پرداخت/بدهکار دوره", MONEY),
                      ("ماندهٔ پایان", MONEY), ("دورهٔ پرداخت (روز)", DAYS)], no_total={5})
    for party, a in sorted(base._balances(company_id, f).items(), key=lambda kv: ctx.names.get(kv[0], "")):
        purchases = a["credit"] if S.sign > 0 else a["debit"]
        payments = a["debit"] if S.sign > 0 else a["credit"]
        closing = a["open"] + S.sign * (a["credit"] - a["debit"])
        dpo = int(closing / purchases * days) if purchases and closing > 0 else None
        r.add([ctx.names.get(party, ""), a["open"], purchases, payments, closing, dpo])
    r.note = f"بازه {days} روز؛ دورهٔ پرداخت برای تامین‌کننده‌ای که در بازه خرید نداشته محاسبه نمی‌شود."
    return r


def purchase_vs_sale_price(company_id: int, f) -> ReportResult:
    ctx = base._ctx(company_id)
    buy: dict[int, list] = defaultdict(lambda: [_ZERO, _ZERO])
    sell: dict[int, list] = defaultdict(lambda: [_ZERO, _ZERO])
    g = base.PurchaseFilters(f.date_from, f.date_to, None, f.item_id, f.category_id, f.warehouse_id)
    for doc, ln in base._lines(company_id, ("PURCHASE_INVOICE",), ("POSTED",), g, ctx):
        buy[ln.item_id][0] += ln.quantity_base
        buy[ln.item_id][1] += base._net(ln)
    for doc, ln in base._lines(company_id, ("SALES_INVOICE",), ("POSTED",), g, ctx):
        sell[ln.item_id][0] += ln.quantity_base
        sell[ln.item_id][1] += base._net(ln)
    r = ReportResult([("کالا", TEXT), ("واحد", TEXT), ("مقدار خرید", QTY), ("فی میانگین خرید", MONEY), ("مقدار فروش", QTY),
                      ("فی میانگین فروش", MONEY), ("اختلاف فی", MONEY), ("حاشیه بر فروش", PERCENT)], no_total={3, 5, 6, 7})
    for item_id in sorted(set(buy) | set(sell), key=ctx.item_label):
        bq, ba = buy[item_id]
        sq, sa = sell[item_id]
        bp = (ba / bq).quantize(_Q2) if bq else None
        sp = (sa / sq).quantize(_Q2) if sq else None
        diff = (sp - bp) if bp is not None and sp is not None else None
        r.add([ctx.item_label(item_id), ctx.base_uom(item_id), bq, bp, sq, sp, diff, _pct(diff, sp) if diff is not None else None])
    r.note = "مقایسهٔ فی میانگین خرید و فروش همان بازه (نه بهای تمام‌شدهٔ انبار)؛ برای سود واقعی از گزارش‌های سود فروش استفاده کنید."
    return r


_AN, _PR, _FI, _CT = "تحلیل خرید", "قیمت و هزینه", "مالی و بدهی", "کنترل و حسابرسی"
_ALL = ("supplier", "item", "category", "warehouse")

PURCHASE_R245_REPORTS: list[ReportDef] = [
    ReportDef("VAT", "مالیات بر ارزش افزودهٔ خرید", vat_report, ("supplier",),
              "مبلغ خالص و مالیات خرید به تفکیک دوره و تامین‌کننده — مبنای اظهارنامه.", group=_FI,
              options=(("period", "دوره", (("QUARTER", "فصلی"), ("MONTH", "ماهانه"))),)),
    ReportDef("DPO", "دورهٔ پرداخت بدهی", days_payable, ("supplier",),
              "میانگین روزهایی که پرداخت به هر تامین‌کننده طول می‌کشد، از روی حساب پرداختنی.", group=_FI),
    ReportDef("BY_CURRENCY", "خرید به تفکیک ارز", by_currency, _ALL,
              "خرید ارزی و معادل ارز پایهٔ آن با نرخ هر سند.", group=_AN),
    ReportDef("PERIOD_COMPARE", "مقایسهٔ خرید با دورهٔ قبل", period_comparison, _ALL,
              "خالص خرید در این بازه در برابر همان بازهٔ سال قبل یا دورهٔ قبل.", group=_AN,
              options=(("by", "به تفکیک", _COMPARE_BY),
                       ("compare", "مقایسه با", (("PREV_YEAR", "همان بازهٔ سال قبل"), ("PREV_PERIOD", "دورهٔ قبل"))))),
    ReportDef("SUPPLIER_SHARE", "سهم تامین‌کنندگان از هر کالا", supplier_share_by_item, _ALL,
              "هر کالا از کدام تامین‌کنندگان، با چه سهم و فی میانگینی خریده شده است.", group=_AN),
    ReportDef("LAST_PURCHASE", "آخرین خرید هر کالا", last_purchase, _ALL,
              "تاریخ، تامین‌کننده و فی آخرین خرید هر کالا تا تاریخ گزارش.", "as_of", _PR),
    ReportDef("PURCHASE_VS_SALE", "قیمت خرید در برابر فروش", purchase_vs_sale_price, ("item", "category", "warehouse"),
              "فی میانگین خرید و فروش هر کالا در بازه و حاشیهٔ آن.", group=_PR),
    ReportDef("DUPLICATE_INVOICES", "فاکتورهای خرید احتمالاً تکراری", duplicate_invoices, ("supplier",),
              "هم‌تامین‌کننده با شمارهٔ مرجع یکسان، یا با مبلغ یکسان در فاصلهٔ ۷ روز.", group=_CT),
    ReportDef("EXPIRING_CONTRACTS", "قراردادهای خرید در آستانهٔ انقضا", expiring_contracts, ("supplier",),
              "قراردادهای فعالی که تا چند روز آینده تمام می‌شوند یا تاریخشان گذشته ولی هنوز فعال‌اند.", "as_of", _CT,
              options=(_DAYS_OPTION,)),
]
base.register_reports(PURCHASE_R245_REPORTS)
