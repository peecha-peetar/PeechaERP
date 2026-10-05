"""گزارش‌هایِ حرفه‌ایِ حسابداری -- R245.

همان موتورِ گزارشِ خرید/فروش (ReportDef/ReportResult، مرتب‌سازی، گروه‌بندی، نمودار، نماهایِ
ذخیره‌شده، خروجی با لوگو) با side="ACCOUNTING". همه فقط-خواندنی از acc.journal_entries/lines
محاسبه می‌شوند؛ هیچ عددی ذخیره یا اصلاح نمی‌شود. فیلترهایِ مشترک: حساب (با همهٔ زیرحساب‌ها)،
حسابِ تفصیلی و گزینهٔ «وضعیتِ سند» (پیش‌فرض بدونِ پیش‌نویس، مثلِ تراز آزمایشی).
"""

from __future__ import annotations

import datetime
import decimal
from collections import defaultdict
from dataclasses import dataclass

import jdatetime
from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import (
    ChartOfAccount, JournalEntry, JournalEntryLine, JournalEntryLineDetail, JournalEntryStatus, JournalEntryType,
)
from peecha.db.models.security import User
from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import purchase_reports as base
from peecha.services import reports as gl

TEXT, DATE, MONEY, INT, PERCENT, DAYS = base.TEXT, base.DATE, base.MONEY, base.INT, base.PERCENT, base.DAYS
ReportResult = base.ReportResult
ReportDef = base.ReportDef
_ZERO = decimal.Decimal(0)
_REF = "JOURNAL_ENTRY"

STATUS_LABELS = {"DRAFT": "پیش‌نویس", "TEMPORARY": "موقت", "PERMANENT": "دائم", "REVERSED": "برگشت‌خورده", "CANCELLED": "باطل‌شده"}
TYPE_LABELS = {"NORMAL": "عادی", "OPENING": "افتتاحیه", "CLOSING": "اختتامیه", "ADJUSTING": "تعدیلی", "RECEIPT": "دریافت",
               "PAYMENT": "پرداخت", "PAYROLL": "حقوق", "TANKHAH": "تنخواه", "INVENTORY": "انبار", "COMMERCIAL": "بازرگانی",
               "FIXED_ASSET": "دارایی ثابت"}
SOURCE_LABELS = {"MANUAL": "دستی"}
_STATUS_OPTION = ("status", "وضعیتِ سند", (("EXCLUDE_DRAFT", "بدونِ پیش‌نویس"), ("ALL", "همه"),
                                           ("PERMANENT_ONLY", "فقط دائم"), ("DRAFT_ONLY", "فقط پیش‌نویس")))
_LEVEL_OPTION = ("level", "سطحِ حساب", (("2", "کل"), ("1", "گروه"), ("3", "معین")))


# ---------------------------------------------------------------------
# دادهٔ پایه
# ---------------------------------------------------------------------
@dataclass
class _Ctx:
    accounts: dict[int, coa_service.AccountRow]
    parent: dict[int, int | None]
    details: dict[int, str]

    def label(self, account_id: int | None) -> str:
        a = self.accounts.get(account_id)
        return f"{a.full_code} — {a.name}" if a else ""

    def ancestor(self, account_id: int, level: int) -> int | None:
        current = account_id
        while current is not None:
            a = self.accounts.get(current)
            if a is not None and a.account_level == level:
                return current
            if a is not None and a.account_level < level:
                return None
            current = self.parent.get(current)
        return None

    def subtree(self, account_id: int | None) -> set[int] | None:
        if account_id is None:
            return None
        out = {account_id}
        changed = True
        while changed:
            changed = False
            for child, parent in self.parent.items():
                if parent in out and child not in out:
                    out.add(child)
                    changed = True
        return out

    def signed(self, account_id: int, debit: decimal.Decimal, credit: decimal.Decimal) -> decimal.Decimal:
        a = self.accounts.get(account_id)
        return (credit - debit) if a is not None and a.nature_code == "CREDIT" else (debit - credit)


def _ctx(company_id: int) -> _Ctx:
    accounts = {a.account_id: a for a in coa_service.list_accounts(company_id)}
    with new_session() as session:
        parent = dict(session.execute(select(ChartOfAccount.account_id, ChartOfAccount.parent_account_id)
                                      .where(ChartOfAccount.company_id == company_id)).all())
    details = {d.detail_account_id: f"{d.full_code or d.code} — {d.name or ''}"
               for d in dimensions_service.list_all_detail_accounts(company_id)}
    return _Ctx(accounts, parent, details)


def _status(f) -> str:
    return f.options.get("status") or "EXCLUDE_DRAFT"


def _status_ok(code: str, status_filter: str) -> bool:
    if status_filter == "ALL":
        return True
    if status_filter == "DRAFT_ONLY":
        return code == "DRAFT"
    if status_filter == "PERMANENT_ONLY":
        return code == "PERMANENT"
    return code != "DRAFT"


@dataclass
class _Line:
    entry_id: int
    date: datetime.date
    temporary_no: int
    status: str
    line_id: int
    account_id: int
    description: str
    debit: decimal.Decimal
    credit: decimal.Decimal


def _lines(company_id: int, f, ctx: _Ctx, *, status_filter: str | None = None, date_from=None, date_to=None,
           account_filter: bool = True) -> list[_Line]:
    """ردیف‌هایِ سند در بازه، با فیلترِ حساب (زیرشاخه) و تفصیلی."""
    status_filter = status_filter or _status(f)
    date_from = f.date_from if date_from is None else date_from
    date_to = f.date_to if date_to is None else date_to
    with new_session() as session:
        q = (select(JournalEntryLine, JournalEntry.document_date, JournalEntry.temporary_no, JournalEntry.description,
                    JournalEntryStatus.code)
             .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
             .join(JournalEntryStatus, JournalEntryStatus.status_id == JournalEntry.status_id)
             .where(JournalEntry.company_id == company_id, JournalEntry.document_date >= date_from,
                    JournalEntry.document_date <= date_to))
        if f.detail_account_id is not None:
            q = q.where(JournalEntryLine.line_id.in_(select(JournalEntryLineDetail.line_id).where(
                JournalEntryLineDetail.detail_account_id == f.detail_account_id)))
        rows = session.execute(q.order_by(JournalEntry.document_date, JournalEntry.temporary_no, JournalEntryLine.line_no)).all()
    subtree = ctx.subtree(f.account_id) if account_filter else None
    out = []
    for ln, when, no, entry_desc, status in rows:
        if not _status_ok(status, status_filter) or (subtree is not None and ln.account_id not in subtree):
            continue
        out.append(_Line(ln.journal_entry_id, when, no, status, ln.line_id, ln.account_id,
                         ln.description or entry_desc or "", ln.debit_amount_base, ln.credit_amount_base))
    return out


@dataclass
class _Entry:
    entry_id: int
    date: datetime.date
    temporary_no: int
    permanent_no: int | None
    status: str
    type_code: str
    source: str
    description: str
    created_by: str
    posted_by: str
    created_at: datetime.datetime | None
    created_by_id: int | None
    posted_by_id: int | None
    reversed_entry_id: int | None
    fiscal_year_id: int
    debit: decimal.Decimal = _ZERO
    credit: decimal.Decimal = _ZERO
    line_count: int = 0


def _entries(company_id: int, f, ctx: _Ctx, *, status_filter: str | None = None, date_from=None, date_to=None) -> list[_Entry]:
    status_filter = status_filter or _status(f)
    date_from = f.date_from if date_from is None else date_from
    date_to = f.date_to if date_to is None else date_to
    with new_session() as session:
        users = dict(session.execute(select(User.user_id, User.full_name)).all())
        q = (select(JournalEntry, JournalEntryStatus.code, JournalEntryType.code)
             .join(JournalEntryStatus, JournalEntryStatus.status_id == JournalEntry.status_id)
             .join(JournalEntryType, JournalEntryType.entry_type_id == JournalEntry.entry_type_id)
             .where(JournalEntry.company_id == company_id, JournalEntry.document_date >= date_from,
                    JournalEntry.document_date <= date_to)
             .order_by(JournalEntry.document_date, JournalEntry.temporary_no))
        entries = [(e, s, t) for e, s, t in session.execute(q).all() if _status_ok(s, status_filter)]
        ids = [e.journal_entry_id for e, _s, _t in entries]
        sums: dict[int, tuple] = {}
        if ids:
            for eid, debit, credit, count in session.execute(
                    select(JournalEntryLine.journal_entry_id, func.coalesce(func.sum(JournalEntryLine.debit_amount_base), 0),
                           func.coalesce(func.sum(JournalEntryLine.credit_amount_base), 0), func.count())
                    .where(JournalEntryLine.journal_entry_id.in_(ids)).group_by(JournalEntryLine.journal_entry_id)).all():
                sums[eid] = (decimal.Decimal(debit), decimal.Decimal(credit), count)
    touching = None
    if f.account_id is not None or f.detail_account_id is not None:
        touching = {ln.entry_id for ln in _lines(company_id, f, ctx, status_filter="ALL", date_from=date_from, date_to=date_to)}
    out = []
    for e, status, type_code in entries:
        if touching is not None and e.journal_entry_id not in touching:
            continue
        debit, credit, count = sums.get(e.journal_entry_id, (_ZERO, _ZERO, 0))
        out.append(_Entry(e.journal_entry_id, e.document_date, e.temporary_no, e.permanent_no, status, type_code,
                          e.source_system, e.description or "", users.get(e.created_by_user_id, ""),
                          users.get(e.posted_by_user_id, "") if e.posted_by_user_id else "", e.created_at,
                          e.created_by_user_id, e.posted_by_user_id, e.reversed_entry_id, e.fiscal_year_id,
                          debit, credit, count))
    return out


def _ref(entry_id: int) -> tuple[int, str]:
    return (entry_id, _REF)


def _period_key(value: datetime.date, period: str) -> str:
    j = jdatetime.date.fromgregorian(date=value)
    if period == "YEAR":
        return f"{j.year}"
    if period == "QUARTER":
        return f"{j.year}-ف{(j.month - 1) // 3 + 1}"
    return f"{j.year}/{j.month:02d}"


def _pct(part: decimal.Decimal, whole: decimal.Decimal) -> decimal.Decimal | None:
    return (part * 100 / whole).quantize(decimal.Decimal("0.1")) if whole else None


def _require_account(f) -> None:
    if f.account_id is None:
        raise ValueError("برایِ این گزارش ابتدا «حساب» را انتخاب کنید.")


# ---------------------------------------------------------------------
# اسناد و دفاتر
# ---------------------------------------------------------------------
_ENTRY_COLUMNS = [("تاریخ", DATE), ("شمارهٔ موقت", INT), ("شمارهٔ دائم", INT), ("نوع", TEXT), ("وضعیت", TEXT),
                  ("شرح", TEXT), ("بدهکار", MONEY), ("بستانکار", MONEY)]


def _entry_result(columns: list) -> ReportResult:
    return ReportResult(columns, no_total={1, 2})


def _entry_cells(e: _Entry) -> list:
    return [e.date, e.temporary_no, e.permanent_no or "", TYPE_LABELS.get(e.type_code, e.type_code),
            STATUS_LABELS.get(e.status, e.status), e.description, e.debit, e.credit]


def voucher_register(company_id: int, f) -> ReportResult:
    ctx = _ctx(company_id)
    r = _entry_result(_ENTRY_COLUMNS + [("منبع", TEXT), ("تعدادِ ردیف", INT), ("صادرکننده", TEXT), ("تاییدکننده", TEXT)])
    for e in _entries(company_id, f, ctx):
        r.add(_entry_cells(e) + [SOURCE_LABELS.get(e.source, e.source), e.line_count, e.created_by, e.posted_by], _ref(e.entry_id))
    return r


def daily_summary(company_id: int, f) -> ReportResult:
    ctx = _ctx(company_id)
    days: dict[datetime.date, list] = {}
    for e in _entries(company_id, f, ctx):
        row = days.setdefault(e.date, [e.date, 0, 0, _ZERO, _ZERO])
        row[1] += 1
        row[2] += e.line_count
        row[3] += e.debit
        row[4] += e.credit
    r = ReportResult([("تاریخ", DATE), ("تعدادِ سند", INT), ("تعدادِ ردیف", INT), ("بدهکار", MONEY), ("بستانکار", MONEY)])
    for day in sorted(days):
        r.add(days[day])
    return r


_BY_OPTION = ("by", "تفکیک بر اساسِ", (("TYPE", "نوعِ سند"), ("STATUS", "وضعیت"), ("USER", "صادرکننده"),
                                       ("SOURCE", "منبعِ صدور"), ("MONTH", "ماه")))


def vouchers_by(company_id: int, f) -> ReportResult:
    ctx = _ctx(company_id)
    by = f.options.get("by") or "TYPE"
    groups: dict[str, list] = {}
    for e in _entries(company_id, f, ctx):
        key = {"TYPE": TYPE_LABELS.get(e.type_code, e.type_code), "STATUS": STATUS_LABELS.get(e.status, e.status),
               "USER": e.created_by or "—", "SOURCE": SOURCE_LABELS.get(e.source, e.source),
               "MONTH": _period_key(e.date, "MONTH")}[by]
        row = groups.setdefault(key, [key, 0, 0, _ZERO, None, None])
        row[1] += 1
        row[2] += e.line_count
        row[3] += e.debit
        row[4] = e.date if row[4] is None or e.date < row[4] else row[4]
        row[5] = e.date if row[5] is None or e.date > row[5] else row[5]
    total = sum((g[3] for g in groups.values()), _ZERO)
    r = ReportResult([("گروه", TEXT), ("تعدادِ سند", INT), ("تعدادِ ردیف", INT), ("جمعِ گردش", MONEY),
                      ("اولین تاریخ", DATE), ("آخرین تاریخ", DATE), ("سهم از گردش", PERCENT)])
    for key in sorted(groups):
        g = groups[key]
        r.add(g + [_pct(g[3], total)])
    r.no_total = {6}
    return r


def special_entries(company_id: int, f) -> ReportResult:
    ctx = _ctx(company_id)
    r = _entry_result(_ENTRY_COLUMNS + [("صادرکننده", TEXT)])
    for e in _entries(company_id, f, ctx, status_filter="ALL"):
        if e.type_code in ("OPENING", "CLOSING", "ADJUSTING"):
            r.add(_entry_cells(e) + [e.created_by], _ref(e.entry_id))
    if not r.rows:
        r.note = "در این بازه سندِ افتتاحیه/اختتامیه/تعدیلی وجود ندارد."
    return r


def reversed_entries(company_id: int, f) -> ReportResult:
    ctx = _ctx(company_id)
    all_entries = _entries(company_id, f, ctx, status_filter="ALL", date_from=datetime.date(1900, 1, 1))
    by_id = {e.entry_id: e for e in all_entries}
    r = _entry_result(_ENTRY_COLUMNS + [("سندِ مرتبط", TEXT), ("صادرکننده", TEXT)])
    for e in all_entries:
        if e.date < f.date_from:
            continue
        if e.status in ("REVERSED", "CANCELLED") or e.reversed_entry_id:
            target = by_id.get(e.reversed_entry_id)
            link = f"برگشتِ سندِ {target.temporary_no}" if target else ""
            r.add(_entry_cells(e) + [link, e.created_by], _ref(e.entry_id))
    return r


# ---------------------------------------------------------------------
# تحلیلِ حساب‌ها
# ---------------------------------------------------------------------
_PERIOD_OPTION = ("period", "دوره", (("MONTH", "ماهانه"), ("QUARTER", "فصلی"), ("YEAR", "سالانه")))
_MEASURE_OPTION = ("measure", "مقدار", (("NET", "خالص (طبقِ ماهیت)"), ("DEBIT", "گردشِ بدهکار"), ("CREDIT", "گردشِ بستانکار")))


def account_period_matrix(company_id: int, f) -> ReportResult:
    ctx = _ctx(company_id)
    level = int(f.options.get("level") or 2)
    period = f.options.get("period") or "MONTH"
    measure = f.options.get("measure") or "NET"
    cells: dict[int, dict[str, decimal.Decimal]] = defaultdict(lambda: defaultdict(lambda: _ZERO))
    keys: set[str] = set()
    for ln in _lines(company_id, f, ctx):
        target = ctx.ancestor(ln.account_id, level)
        if target is None:
            continue
        key = _period_key(ln.date, period)
        keys.add(key)
        value = ln.debit if measure == "DEBIT" else ln.credit if measure == "CREDIT" else ctx.signed(target, ln.debit, ln.credit)
        cells[target][key] += value
    ordered = sorted(keys)
    from peecha import numerals

    r = ReportResult([("حساب", TEXT)] + [(numerals.to_persian_digits(k), MONEY) for k in ordered] + [("جمع", MONEY), ("میانگینِ دوره", MONEY)])
    for account_id in sorted(cells, key=lambda a: ctx.accounts[a].full_code):
        values = [cells[account_id].get(k, _ZERO) for k in ordered]
        total = sum(values, _ZERO)
        r.add([ctx.label(account_id)] + values + [total, (total / len(ordered)).quantize(decimal.Decimal("0.01")) if ordered else _ZERO])
    r.no_total = {len(ordered) + 2}
    return r


def monthly_balance(company_id: int, f) -> ReportResult:
    _require_account(f)
    ctx = _ctx(company_id)
    opening = sum((ctx.signed(f.account_id, ln.debit, ln.credit) for ln in _lines(
        company_id, f, ctx, date_from=datetime.date(1900, 1, 1), date_to=f.date_from - datetime.timedelta(days=1))), _ZERO)
    months: dict[str, list] = {}
    for ln in _lines(company_id, f, ctx):
        row = months.setdefault(_period_key(ln.date, "MONTH"), [_ZERO, _ZERO, 0])
        row[0] += ln.debit
        row[1] += ln.credit
        row[2] += 1
    r = ReportResult([("ماه", TEXT), ("ماندهٔ ابتدا", MONEY), ("بدهکار", MONEY), ("بستانکار", MONEY), ("ماندهٔ انتها", MONEY),
                      ("تعدادِ ردیف", INT)])
    balance = opening
    for key in sorted(months):
        debit, credit, count = months[key]
        start = balance
        balance = start + ctx.signed(f.account_id, debit, credit)
        r.add([key, start, debit, credit, balance, count])
    r.no_total = {1, 4}
    r.note = f"حساب: {ctx.label(f.account_id)} -- مانده طبقِ ماهیتِ حساب؛ ماندهٔ اولِ بازه {gl_fmt(opening)}."
    return r


def gl_fmt(value: decimal.Decimal) -> str:
    from peecha import numerals

    return numerals.format_money(value, 0, None)


def contra_accounts(company_id: int, f) -> ReportResult:
    """برایِ هر سندی که حسابِ انتخابی در آن هست، بقیهٔ ردیف‌هایِ همان سند به‌عنوانِ طرف‌حساب جمع می‌شوند."""
    _require_account(f)
    ctx = _ctx(company_id)
    subtree = ctx.subtree(f.account_id)
    own = _lines(company_id, f, ctx)
    entry_ids = {ln.entry_id for ln in own}
    unfiltered = type(f)(f.date_from, f.date_to, side=f.side, options=f.options)
    level = int(f.options.get("level") or 3)
    groups: dict[int, list] = {}
    for ln in _lines(company_id, unfiltered, ctx, account_filter=False):
        if ln.entry_id not in entry_ids or ln.account_id in subtree:
            continue
        target = ctx.ancestor(ln.account_id, level) or ln.account_id
        row = groups.setdefault(target, [ctx.label(target), _ZERO, _ZERO, set()])
        row[1] += ln.debit
        row[2] += ln.credit
        row[3].add(ln.entry_id)
    r = ReportResult([("طرف‌حساب", TEXT), ("بدهکار", MONEY), ("بستانکار", MONEY), ("خالص", MONEY), ("تعدادِ سند", INT)])
    for target in sorted(groups, key=lambda a: ctx.accounts[a].full_code if a in ctx.accounts else ""):
        label, debit, credit, entries = groups[target]
        r.add([label, debit, credit, debit - credit, len(entries)])
    r.note = (f"حساب: {ctx.label(f.account_id)} -- در سندهایِ چندطرفه کلِ ردیفِ طرفِ مقابل به این حساب نسبت داده می‌شود "
              "(تخصیصِ نسبی انجام نمی‌شود).")
    return r


def detail_by_account(company_id: int, f) -> ReportResult:
    ctx = _ctx(company_id)
    lines = {ln.line_id: ln for ln in _lines(company_id, f, ctx)}
    groups: dict[tuple[int, int], list] = {}
    if lines:
        with new_session() as session:
            pairs = session.execute(select(JournalEntryLineDetail.line_id, JournalEntryLineDetail.detail_account_id)
                                    .where(JournalEntryLineDetail.line_id.in_(list(lines)))).all()
        for line_id, detail_id in pairs:
            if f.detail_account_id is not None and detail_id != f.detail_account_id:
                continue
            ln = lines[line_id]
            row = groups.setdefault((detail_id, ln.account_id), [_ZERO, _ZERO, 0])
            row[0] += ln.debit
            row[1] += ln.credit
            row[2] += 1
    r = ReportResult([("حسابِ تفصیلی", TEXT), ("حساب", TEXT), ("بدهکار", MONEY), ("بستانکار", MONEY), ("مانده", MONEY),
                      ("تعدادِ ردیف", INT)])
    for (detail_id, account_id), (debit, credit, count) in sorted(
            groups.items(), key=lambda kv: (ctx.details.get(kv[0][0], ""), ctx.label(kv[0][1]))):
        r.add([ctx.details.get(detail_id, str(detail_id)), ctx.label(account_id), debit, credit,
               ctx.signed(account_id, debit, credit), count])
    return r


def comparative_trial_balance(company_id: int, f) -> ReportResult:
    ctx = _ctx(company_id)
    level = int(f.options.get("level") or 2)
    compare = f.options.get("compare") or "PREV_YEAR"
    if compare == "PREV_YEAR":
        prev_from, prev_to = _shift_year(f.date_from, -1), _shift_year(f.date_to, -1)
    else:
        span = f.date_to - f.date_from
        prev_to = f.date_from - datetime.timedelta(days=1)
        prev_from = prev_to - span

    def totals(date_from, date_to):
        out: dict[int, decimal.Decimal] = defaultdict(lambda: _ZERO)
        for ln in _lines(company_id, f, ctx, date_from=date_from, date_to=date_to):
            target = ctx.ancestor(ln.account_id, level)
            if target is not None:
                out[target] += ctx.signed(target, ln.debit, ln.credit)
        return out

    current, previous = totals(f.date_from, f.date_to), totals(prev_from, prev_to)
    r = ReportResult([("حساب", TEXT), ("دورهٔ جاری", MONEY), ("دورهٔ مقایسه", MONEY), ("تغییر", MONEY), ("درصدِ تغییر", PERCENT)])
    for account_id in sorted(set(current) | set(previous), key=lambda a: ctx.accounts[a].full_code):
        cur, prev = current.get(account_id, _ZERO), previous.get(account_id, _ZERO)
        r.add([ctx.label(account_id), cur, prev, cur - prev, _pct(cur - prev, abs(prev))])
    r.no_total = {4}
    from peecha import numerals

    r.note = (f"گردشِ خالصِ دوره طبقِ ماهیتِ حساب؛ دورهٔ مقایسه: {numerals.format_jalali_date(prev_from)} تا "
              f"{numerals.format_jalali_date(prev_to)}.")
    return r


def _shift_year(value: datetime.date, years: int) -> datetime.date:
    j = jdatetime.date.fromgregorian(date=value)
    day = j.day
    while True:
        try:
            return jdatetime.date(j.year + years, j.month, day).togregorian()
        except ValueError:
            day -= 1


def abnormal_balances(company_id: int, f) -> ReportResult:
    ctx = _ctx(company_id)
    sums: dict[int, list] = defaultdict(lambda: [_ZERO, _ZERO])
    for ln in _lines(company_id, f, ctx):
        sums[ln.account_id][0] += ln.debit
        sums[ln.account_id][1] += ln.credit
    r = ReportResult([("حساب", TEXT), ("ماهیت", TEXT), ("جمعِ بدهکار", MONEY), ("جمعِ بستانکار", MONEY), ("ماندهٔ خلافِ ماهیت", MONEY)])
    for account_id in sorted(sums, key=lambda a: ctx.accounts[a].full_code if a in ctx.accounts else ""):
        a = ctx.accounts.get(account_id)
        if a is None or a.nature_code not in ("DEBIT", "CREDIT"):
            continue
        debit, credit = sums[account_id]
        wrong = (credit - debit) if a.nature_code == "DEBIT" else (debit - credit)
        if wrong > 0:
            r.add([ctx.label(account_id), "بدهکار" if a.nature_code == "DEBIT" else "بستانکار", debit, credit, wrong])
    if not r.rows:
        r.note = "هیچ حسابی ماندهٔ خلافِ ماهیت ندارد."
    return r


def dormant_accounts(company_id: int, f) -> ReportResult:
    ctx = _ctx(company_id)
    active = {ln.account_id for ln in _lines(company_id, f, ctx)}
    history = _lines(company_id, f, ctx, date_from=datetime.date(1900, 1, 1), date_to=f.date_to)
    last: dict[int, datetime.date] = {}
    balance: dict[int, decimal.Decimal] = defaultdict(lambda: _ZERO)
    for ln in history:
        last[ln.account_id] = max(last.get(ln.account_id, ln.date), ln.date)
        balance[ln.account_id] += ctx.signed(ln.account_id, ln.debit, ln.credit)
    subtree = ctx.subtree(f.account_id)
    r = ReportResult([("حساب", TEXT), ("آخرین گردش", DATE), ("روز از آخرین گردش", DAYS), ("مانده", MONEY), ("وضعیت", TEXT)])
    for a in sorted(ctx.accounts.values(), key=lambda x: x.full_code):
        if not a.is_postable or a.account_id in active or (subtree is not None and a.account_id not in subtree):
            continue
        when = last.get(a.account_id)
        r.add([ctx.label(a.account_id), when, (f.date_to - when).days if when else None, balance.get(a.account_id, _ZERO),
               "هرگز گردش نداشته" if when is None else ("راکد با مانده" if balance.get(a.account_id) else "راکد بدونِ مانده")])
    return r


# ---------------------------------------------------------------------
# تحلیلِ صورت‌هایِ مالی
# ---------------------------------------------------------------------
_CATEGORY_LABELS = {"REVENUE": "درآمد", "COGS": "بهایِ تمام‌شده", "EXPENSE": "هزینه",
                    "ASSET": "دارایی", "LIABILITY": "بدهی", "EQUITY": "حقوقِ صاحبانِ سهام"}


def income_statement_analysis(company_id: int, f) -> ReportResult:
    s = gl.compute_income_statement(company_id, f.date_from, f.date_to, status_filter=_status(f))
    prev_revenue = sum((row.previous_amount for row in s.rows if row.category_code == "REVENUE"), _ZERO)
    r = ReportResult([("بخش", TEXT), ("حساب", TEXT), ("دورهٔ جاری", MONEY), ("درصد از درآمد", PERCENT),
                      ("سالِ قبل", MONEY), ("درصد از درآمدِ سالِ قبل", PERCENT), ("تغییر", MONEY), ("درصدِ تغییر", PERCENT)])

    def add(section, label, cur, prev):
        r.add([section, label, cur, _pct(cur, s.total_revenue), prev, _pct(prev, prev_revenue), cur - prev, _pct(cur - prev, abs(prev))])

    for row in s.rows:
        add(_CATEGORY_LABELS.get(row.category_code, row.category_code), f"{row.full_code} — {row.name}",
            row.current_amount, row.previous_amount)
    prev = {c: sum((x.previous_amount for x in s.rows if x.category_code == c), _ZERO) for c in ("REVENUE", "COGS", "EXPENSE")}
    add("جمع", "سودِ ناخالص", s.gross_profit, prev["REVENUE"] - prev["COGS"])
    add("جمع", "سود (زیان) خالص", s.net_income, prev["REVENUE"] - prev["COGS"] - prev["EXPENSE"])
    r.no_total = set(range(2, 8))
    return r


def balance_sheet_analysis(company_id: int, f) -> ReportResult:
    current = gl.compute_balance_sheet(company_id, f.date_to, status_filter=_status(f))
    prev_date = _shift_year(f.date_to, -1)
    previous = gl.compute_balance_sheet(company_id, prev_date, status_filter=_status(f))
    prev_by_code = {row.full_code: row.balance for row in previous.asset_rows + previous.liability_rows + previous.equity_rows}
    r = ReportResult([("بخش", TEXT), ("حساب", TEXT), ("مانده", MONEY), ("درصد از جمعِ بخش", PERCENT),
                      ("سالِ قبل", MONEY), ("تغییر", MONEY), ("درصدِ تغییر", PERCENT)])
    total_le = current.total_liabilities + current.total_equity
    for section, rows, whole in (("دارایی", current.asset_rows, current.total_assets),
                                 ("بدهی", current.liability_rows, total_le), ("حقوقِ صاحبانِ سهام", current.equity_rows, total_le)):
        for row in rows:
            prev = prev_by_code.get(row.full_code, _ZERO)
            r.add([section, f"{row.full_code} — {row.name}", row.balance, _pct(row.balance, whole), prev, row.balance - prev,
                   _pct(row.balance - prev, abs(prev))])
    r.add(["جمع", "جمعِ دارایی‌ها", current.total_assets, None, previous.total_assets,
           current.total_assets - previous.total_assets, _pct(current.total_assets - previous.total_assets, abs(previous.total_assets))])
    r.no_total = set(range(2, 7))
    return r


# ---------------------------------------------------------------------
# کنترل و حسابرسیِ اسناد
# ---------------------------------------------------------------------
def unbalanced_entries(company_id: int, f) -> ReportResult:
    ctx = _ctx(company_id)
    r = _entry_result(_ENTRY_COLUMNS + [("اختلاف", MONEY), ("صادرکننده", TEXT)])
    for e in _entries(company_id, f, ctx, status_filter="ALL"):
        if e.debit != e.credit or e.line_count == 0:
            r.add(_entry_cells(e) + [e.debit - e.credit, e.created_by], _ref(e.entry_id))
    if not r.rows:
        r.note = "همهٔ اسنادِ بازه تراز هستند."
    return r


def number_gaps(company_id: int, f) -> ReportResult:
    """شکاف/تکرار در شماره‌هایِ موقت و دائمِ هر سالِ مالی (فقط گزارش؛ شماره‌ای اصلاح نمی‌شود)."""
    ctx = _ctx(company_id)
    by_year: dict[int, dict[str, list[int]]] = defaultdict(lambda: {"temporary": [], "permanent": []})
    for e in _entries(company_id, f, ctx, status_filter="ALL"):
        by_year[e.fiscal_year_id]["temporary"].append(e.temporary_no)
        if e.permanent_no:
            by_year[e.fiscal_year_id]["permanent"].append(e.permanent_no)
    r = ReportResult([("سالِ مالی", INT), ("نوعِ شماره", TEXT), ("مشکل", TEXT), ("از شماره", INT), ("تا شماره", INT), ("تعداد", INT)])
    for year in sorted(by_year):
        for kind, label in (("temporary", "موقت"), ("permanent", "دائم")):
            numbers = sorted(by_year[year][kind])
            seen: dict[int, int] = defaultdict(int)
            for n in numbers:
                seen[n] += 1
            for n, count in sorted(seen.items()):
                if count > 1:
                    r.add([year, label, "شمارهٔ تکراری", n, n, count])
            unique = sorted(seen)
            for a, b in zip(unique, unique[1:]):
                if b - a > 1:
                    r.add([year, label, "شکاف در شماره", a + 1, b - 1, b - a - 1])
    r.no_total = {0, 3, 4}
    if not r.rows:
        r.note = "شماره‌گذاریِ اسنادِ بازه پیوسته و بدونِ تکرار است."
    return r


def unposted_entries(company_id: int, f) -> ReportResult:
    ctx = _ctx(company_id)
    r = _entry_result(_ENTRY_COLUMNS + [("سن (روز)", DAYS), ("صادرکننده", TEXT)])
    for e in _entries(company_id, f, ctx, status_filter="ALL"):
        if e.status in ("DRAFT", "TEMPORARY"):
            r.add(_entry_cells(e) + [base._days(e.date), e.created_by], _ref(e.entry_id))
    return r


_LAG_OPTION = ("lag", "حداقلِ فاصله", (("7", "۷ روز"), ("30", "۳۰ روز"), ("90", "۹۰ روز"), ("1", "۱ روز")))


def backdated_entries(company_id: int, f) -> ReportResult:
    ctx = _ctx(company_id)
    lag = int(f.options.get("lag") or 7)
    r = _entry_result(_ENTRY_COLUMNS + [("تاریخِ ثبت در سیستم", DATE), ("فاصله (روز)", DAYS), ("جهت", TEXT), ("صادرکننده", TEXT)])
    for e in _entries(company_id, f, ctx):
        if e.created_at is None:
            continue
        diff = (e.created_at.date() - e.date).days
        if abs(diff) >= lag:
            r.add(_entry_cells(e) + [e.created_at.date(), abs(diff), "عطف به ماسبق" if diff > 0 else "تاریخِ آینده", e.created_by],
                  _ref(e.entry_id))
    return r


def off_hours_entries(company_id: int, f) -> ReportResult:
    ctx = _ctx(company_id)
    r = _entry_result(_ENTRY_COLUMNS + [("زمانِ ثبت", TEXT), ("علت", TEXT), ("صادرکننده", TEXT)])
    for e in _entries(company_id, f, ctx):
        reasons = []
        if e.date.weekday() == 4:
            reasons.append("تاریخِ سند جمعه")
        if e.created_at is not None:
            if e.created_at.weekday() == 4:
                reasons.append("ثبت در روزِ جمعه")
            if e.created_at.hour < 7 or e.created_at.hour >= 20:
                reasons.append("ثبت خارج از ساعتِ ۷ تا ۲۰")
        if reasons:
            stamp = f"{e.created_at:%H:%M}" if e.created_at else ""
            r.add(_entry_cells(e) + [stamp, "، ".join(reasons), e.created_by], _ref(e.entry_id))
    r.note = "زمانِ ثبت همان ساعتِ سرورِ پایگاهِ داده است."
    return r


_TOP_OPTION = ("top", "تعداد", (("50", "۵۰ ردیف"), ("100", "۱۰۰ ردیف"), ("500", "۵۰۰ ردیف")))


def large_lines(company_id: int, f) -> ReportResult:
    ctx = _ctx(company_id)
    top = int(f.options.get("top") or 50)
    lines = sorted(_lines(company_id, f, ctx), key=lambda ln: max(ln.debit, ln.credit), reverse=True)[:top]
    r = ReportResult([("تاریخ", DATE), ("شمارهٔ سند", INT), ("حساب", TEXT), ("شرح", TEXT), ("بدهکار", MONEY), ("بستانکار", MONEY)],
                     no_total={1})
    for ln in lines:
        r.add([ln.date, ln.temporary_no, ctx.label(ln.account_id), ln.description, ln.debit, ln.credit], _ref(ln.entry_id))
    return r


_ROUND_OPTION = ("unit", "مضربِ", (("1000000", "۱٬۰۰۰٬۰۰۰"), ("10000000", "۱۰٬۰۰۰٬۰۰۰"), ("100000", "۱۰۰٬۰۰۰")))


def round_amounts(company_id: int, f) -> ReportResult:
    ctx = _ctx(company_id)
    unit = decimal.Decimal(f.options.get("unit") or 1000000)
    r = ReportResult([("تاریخ", DATE), ("شمارهٔ سند", INT), ("حساب", TEXT), ("شرح", TEXT), ("بدهکار", MONEY), ("بستانکار", MONEY)],
                     no_total={1})
    for ln in _lines(company_id, f, ctx):
        amount = max(ln.debit, ln.credit)
        if amount and amount % unit == 0:
            r.add([ln.date, ln.temporary_no, ctx.label(ln.account_id), ln.description, ln.debit, ln.credit], _ref(ln.entry_id))
    r.note = "مبالغِ رُند لزوماً خطا نیستند؛ این فهرست برایِ بررسیِ برآوردها و ثبت‌هایِ دستی است."
    return r


def self_approved(company_id: int, f) -> ReportResult:
    ctx = _ctx(company_id)
    r = _entry_result(_ENTRY_COLUMNS + [("صادرکننده و تاییدکننده", TEXT)])
    for e in _entries(company_id, f, ctx, status_filter="ALL"):
        if e.posted_by_id is not None and e.posted_by_id == e.created_by_id:
            r.add(_entry_cells(e) + [e.created_by], _ref(e.entry_id))
    if not r.rows:
        r.note = "سندی که صادرکننده و تاییدکنندهٔ آن یک نفر باشد پیدا نشد."
    return r


# ---------------------------------------------------------------------
# فهرست
# ---------------------------------------------------------------------
_VR, _AA, _FS, _AU = "اسناد و دفاتر", "تحلیلِ حساب‌ها", "تحلیلِ صورت‌هایِ مالی", "کنترل و حسابرسیِ اسناد"
_AF = ("account", "detail")

ACCOUNTING_REPORTS: list[ReportDef] = [
    ReportDef("VOUCHER_REGISTER", "دفترِ ثبتِ اسنادِ حسابداری", voucher_register, _AF,
              "همهٔ اسنادِ بازه با شماره، نوع، وضعیت، جمعِ بدهکار/بستانکار، صادرکننده و تاییدکننده.", group=_VR,
              options=(_STATUS_OPTION,)),
    ReportDef("DAILY_SUMMARY", "خلاصهٔ روزانهٔ اسناد", daily_summary, _AF,
              "تعدادِ سند و ردیف و جمعِ گردشِ هر روز.", group=_VR, options=(_STATUS_OPTION,)),
    ReportDef("VOUCHERS_BY", "اسناد به تفکیکِ نوع/وضعیت/کاربر/منبع/ماه", vouchers_by, _AF,
              "تعداد و گردشِ اسناد به تفکیکِ بُعدِ انتخابی.", group=_VR, options=(_BY_OPTION, _STATUS_OPTION)),
    ReportDef("SPECIAL_ENTRIES", "اسنادِ افتتاحیه، اختتامیه و تعدیلی", special_entries, _AF,
              "اسنادِ غیرعادیِ پایانِ دوره که معمولاً بررسیِ جداگانه لازم دارند.", group=_VR),
    ReportDef("REVERSED_ENTRIES", "اسنادِ برگشتی و باطل‌شده", reversed_entries, _AF,
              "اسنادی که برگشت خورده‌اند، باطل شده‌اند یا خودشان سندِ برگشتِ سندِ دیگری هستند.", group=_VR),
    ReportDef("ACCOUNT_PERIOD_MATRIX", "گردشِ دوره‌ایِ حساب‌ها (ماهانه/فصلی/سالانه)", account_period_matrix, _AF,
              "ماتریسِ حساب × دوره برایِ دیدنِ روند؛ مقدار به‌صورتِ خالص طبقِ ماهیت یا گردشِ بدهکار/بستانکار.", group=_AA,
              options=(_PERIOD_OPTION, _LEVEL_OPTION, _MEASURE_OPTION, _STATUS_OPTION)),
    ReportDef("MONTHLY_BALANCE", "گردش و ماندهٔ ماهانهٔ حساب", monthly_balance, _AF,
              "برایِ یک حساب (با زیرحساب‌ها): ماندهٔ ابتدا، گردش و ماندهٔ انتهایِ هر ماه.", group=_AA, options=(_STATUS_OPTION,)),
    ReportDef("CONTRA_ACCOUNTS", "تحلیلِ طرف‌حساب", contra_accounts, _AF,
              "حسابِ انتخابی با چه حساب‌هایی در یک سند آمده و چه مبلغی -- منشأ و مصرفِ گردشِ حساب.", group=_AA,
              options=(("level", "سطحِ طرف‌حساب", (("3", "معین"), ("2", "کل"), ("1", "گروه"))), _STATUS_OPTION)),
    ReportDef("DETAIL_BY_ACCOUNT", "گردشِ تفصیلی‌ها به تفکیکِ حساب", detail_by_account, _AF,
              "هر حسابِ تفصیلی (شخص، مرکزِ هزینه، پروژه، ...) در کدام حساب‌ها و با چه مانده‌ای گردش داشته است.",
              group=_AA, options=(_STATUS_OPTION,)),
    ReportDef("COMPARATIVE_TB", "ترازِ مقایسه‌ای", comparative_trial_balance, _AF,
              "گردشِ خالصِ هر حساب در این بازه در برابرِ همان بازهٔ سالِ قبل یا دورهٔ قبل، با مبلغ و درصدِ تغییر.",
              group=_AA, options=(("compare", "مقایسه با", (("PREV_YEAR", "همان بازهٔ سالِ قبل"), ("PREV_PERIOD", "دورهٔ قبل"))),
                                  _LEVEL_OPTION, _STATUS_OPTION)),
    ReportDef("ABNORMAL_BALANCES", "حساب‌هایِ با ماندهٔ خلافِ ماهیت", abnormal_balances, _AF,
              "مثلاً صندوق یا موجودیِ بستانکار، یا درآمدِ بدهکار -- نشانهٔ خطایِ ثبت.", "as_of", _AA, options=(_STATUS_OPTION,)),
    ReportDef("DORMANT_ACCOUNTS", "حساب‌هایِ راکد", dormant_accounts, _AF,
              "حساب‌هایِ معینی که در بازه گردش نداشته‌اند، با تاریخِ آخرین گردش و ماندهٔ فعلی.", group=_AA,
              options=(_STATUS_OPTION,)),
    ReportDef("IS_ANALYSIS", "تحلیلِ عمودی و افقیِ سود و زیان", income_statement_analysis, (),
              "هر قلم به‌صورتِ درصد از درآمد، و تغییرِ آن نسبت به همان بازه در سالِ قبل.", group=_FS, options=(_STATUS_OPTION,)),
    ReportDef("BS_ANALYSIS", "تحلیلِ عمودی و افقیِ ترازنامه", balance_sheet_analysis, (),
              "دارایی‌ها درصد از جمعِ دارایی، بدهی و حقوقِ صاحبانِ سهام درصد از جمعِ آن دو؛ و تغییر نسبت به همین تاریخ در سالِ قبل.", "as_of", _FS,
              options=(_STATUS_OPTION,)),
    ReportDef("UNBALANCED", "اسنادِ نامتوازن", unbalanced_entries, _AF,
              "اسنادی که جمعِ بدهکار و بستانکارشان برابر نیست یا ردیف ندارند (همهٔ وضعیت‌ها).", group=_AU),
    ReportDef("NUMBER_GAPS", "شکاف و تکرار در شماره‌گذاریِ اسناد", number_gaps, (),
              "شماره‌هایِ موقت و دائمِ جاافتاده یا تکراری در هر سالِ مالی.", group=_AU),
    ReportDef("UNPOSTED", "اسنادِ پیش‌نویس و موقتِ قطعی‌نشده", unposted_entries, _AF,
              "اسنادی که هنوز دائم نشده‌اند، با سنِ هر سند.", group=_AU),
    ReportDef("BACKDATED", "اسنادِ عطف به ماسبق / تاریخِ آینده", backdated_entries, _AF,
              "اسنادی که تاریخِ سندشان با تاریخِ ثبت در سیستم فاصلهٔ زیادی دارد.", group=_AU, options=(_LAG_OPTION, _STATUS_OPTION)),
    ReportDef("OFF_HOURS", "اسنادِ ثبت‌شده در تعطیلی یا خارج از ساعتِ کاری", off_hours_entries, _AF,
              "تاریخ یا زمانِ ثبتِ جمعه یا پیش از ۷ صبح/پس از ۸ شب.", group=_AU, options=(_STATUS_OPTION,)),
    ReportDef("LARGE_LINES", "بزرگ‌ترین ردیف‌هایِ اسناد", large_lines, _AF,
              "ردیف‌هایِ با بیشترین مبلغ در بازه.", group=_AU, options=(_TOP_OPTION, _STATUS_OPTION)),
    ReportDef("ROUND_AMOUNTS", "ردیف‌هایِ با مبلغِ رُند", round_amounts, _AF,
              "ردیف‌هایی که مبلغشان مضربِ عددِ انتخابی است -- آزمونِ متداولِ حسابرسی.", group=_AU,
              options=(_ROUND_OPTION, _STATUS_OPTION)),
    ReportDef("SELF_APPROVED", "اسنادِ تاییدشده توسطِ صادرکننده (تفکیکِ وظایف)", self_approved, _AF,
              "اسنادی که صادرکننده و تاییدکنندهٔ آن یک کاربر است.", group=_AU),
]
ACCOUNTING_REPORTS_BY_CODE = {r.code: r for r in ACCOUNTING_REPORTS}
