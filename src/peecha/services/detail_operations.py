"""R318: انتقال ماندهٔ یک تفصیلی به تفصیلی دیگر، و ادغام کامل گردش دو تفصیلی — هر دو برگشت‌پذیر و ثبت‌شده در رخدادنگار.

- انتقال مانده: یک سند حسابداری با همان موتور سند؛ ماندهٔ هر حساب/ارز (با همان تفصیلی‌های همراه ردیف) از مبدأ برداشته
  و روی مقصد گذاشته می‌شود. برگشت = سند برگشتی همان موتور.
- ادغام کامل: همهٔ ارجاع‌های مبدأ (هر ستونی که به acc.detail_accounts اشاره می‌کند) به مقصد می‌رود و مبدأ غیرفعال می‌شود.
  هر ردیف جابه‌جاشده ثبت می‌شود تا برگشت دقیق باشد؛ ردیفی که با دادهٔ خود مقصد تکراری شود (مثلاً پروندهٔ یک‌به‌یک) روی
  مبدأ می‌ماند و در خلاصه شمرده می‌شود.
هر دو پشت کلید روشن/خاموش (تنظیمات › کدینگ حسابداری › قابلیت‌های تفصیلی) و دسترسی جدا هستند.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field

from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import IntegrityError

from peecha.db.base import new_session
from peecha.db.models.accounting import (
    DetailAccount,
    DetailDimensionType,
    DetailMergeRow,
    DetailOperation,
    JournalEntry,
    JournalEntryLine,
    JournalEntryLineDetail,
    JournalEntryStatus,
)
from peecha.db.models.core import Company, Currency
from peecha.services import detail_dimensions as dims

FEATURE_TRANSFER = "GL_DETAIL_BALANCE_TRANSFER"
FEATURE_MERGE = "GL_DETAIL_MERGE"
FORM_TRANSFER = "detail_balance_transfer"
FORM_MERGE = "detail_merge"
FORM_LABELS = {FORM_TRANSFER: "تفصیلی: انتقال مانده با سند", FORM_MERGE: "تفصیلی: ادغام کامل گردش"}
TYPE_LABELS = {"TRANSFER": "انتقال مانده", "MERGE": "ادغام کامل"}
STATUS_LABELS = {"DONE": "انجام‌شده", "REVERSED": "برگشت‌خورده"}
# کالا و دارایی دفتر فرعی خودشان را دارند (موجودی/دفتر دارایی)؛ جابه‌جایی فقط گردش مالی، آن‌ها را ناهمخوان می‌کند
BLOCKED_TYPES = {dims.INVENTORY_ITEM_CODE: "کالا", dims.FIXED_ASSET_CODE: "دارایی ثابت"}

_ZERO = decimal.Decimal("0")
_Q2 = decimal.Decimal("0.01")
_SKIP = {("acc", "detail_accounts", "parent_detail_account_id")}
_SKIP_TABLES = {("acc", "detail_operations"), ("acc", "detail_merge_rows")}
# ستون‌هایی که تفصیلی نگه می‌دارند ولی کلید خارجی ندارند
_EXTRA_COLUMNS = [("comm", "commission_entries", "rep_detail_account_id"),
                  ("comm", "customer_profiles", "default_sales_rep_detail_account_id")]
TABLE_LABELS = {
    "acc.journal_entry_line_details": "ردیف‌های سند حسابداری",
    "acc.customer_details": "پروندهٔ مشتری", "acc.supplier_details": "پروندهٔ تامین‌کننده",
    "acc.personnel_details": "پروندهٔ پرسنلی",
    "comm.commercial_documents": "اسناد خرید و فروش", "comm.commercial_contracts": "قراردادها",
    "comm.commercial_document_settlement_plan_lines": "برنامهٔ تسویهٔ اسناد",
    "comm.customer_visits": "ویزیت‌ها", "comm.visit_plans": "برنامهٔ ویزیت", "comm.customer_profiles": "پروفایل مشتری",
    "comm.party_addresses": "آدرس‌ها", "comm.party_contacts": "مخاطبان", "comm.customer_guarantees": "ضمانت‌ها",
    "comm.customer_activities": "فعالیت‌های مشتری", "comm.customer_call_logs": "تماس‌ها",
    "comm.installment_plans": "اقساط", "comm.credit_holds": "توقف اعتبار", "comm.loyalty_accounts": "باشگاه مشتریان",
    "comm.service_tickets": "درخواست‌های خدمات", "comm.rma_requests": "مرجوعی‌ها", "comm.coupons": "کوپن‌ها",
    "comm.purchase_requests": "درخواست‌های خرید", "comm.purchase_request_lines": "ردیف درخواست خرید",
    "comm.rfq_suppliers": "استعلام‌های قیمت", "comm.supplier_profiles": "پروفایل تامین‌کننده",
    "comm.commission_entries": "پورسانت‌ها", "comm.sales_representatives": "بازاریاب‌ها",
    "crm.opportunities": "فرصت‌های فروش", "crm.messages": "پیام‌ها", "crm.campaign_members": "اعضای کمپین",
    "crm.customer_scores": "امتیاز مشتری", "crm.leads": "سرنخ‌ها",
    "inv.stock_documents": "اسناد انبار", "inv.batches": "بچ‌ها", "inv.item_suppliers": "تامین‌کنندگان کالا",
    "treasury.received_checks": "چک‌های دریافتی", "treasury.issued_checks": "چک‌های پرداختی",
    "treasury.checkbooks": "دسته‌چک‌ها", "treasury.petty_cash_funds": "تنخواه‌ها",
    "treasury.petty_cash_fund_lines": "ردیف‌های تنخواه", "hr.employees": "کارمندان",
    "fa.assets": "دارایی‌ها", "prd.production_orders": "دستورهای تولید", "qms.nonconformances": "عدم‌انطباق‌ها",
}


# --- کلید و دسترسی ---------------------------------------------------------------------------------
def is_on(company_id: int, feature_code: str) -> bool:
    from peecha.services import inventory_engine as engine

    return engine.is_feature_enabled(company_id, feature_code)


def can(company_id: int, user_id: int | None, form_code: str, action: str = "CREATE") -> bool:
    from peecha.services import roles as roles_service

    return user_id is not None and roles_service.user_has_permission(user_id, company_id, form_code, action)


def _require(company_id: int, user_id: int | None, feature_code: str, form_code: str, action: str = "CREATE") -> None:
    if not is_on(company_id, feature_code):
        raise ValueError(f"قابلیت «{FORM_LABELS[form_code].split(': ')[1]}» در تنظیمات خاموش است.")
    if not can(company_id, user_id, form_code, action):
        raise ValueError(f"دسترسی «{FORM_LABELS[form_code]}» را ندارید.")


def _label(detail: DetailAccount) -> str:
    return f"{detail.code} — {detail.name or ''}".strip(" —")


def _pair(session, company_id: int, source_id: int, target_id: int) -> tuple[DetailAccount, DetailAccount, str]:
    if not source_id or not target_id:
        raise ValueError("تفصیلی مبدأ و مقصد را انتخاب کنید.")
    if source_id == target_id:
        raise ValueError("مبدأ و مقصد نمی‌توانند یکی باشند.")
    source, target = session.get(DetailAccount, source_id), session.get(DetailAccount, target_id)
    if source is None or target is None or source.company_id != company_id or target.company_id != company_id:
        raise ValueError("تفصیلی نامعتبر است.")
    if source.dimension_type_id != target.dimension_type_id:
        raise ValueError("مبدأ و مقصد باید از یک گروه تفصیلی باشند.")
    if dims.NO_DETAIL_CODE in (source.code, target.code):
        raise ValueError("تفصیلی «بدون تفصیلی» قابل انتقال یا ادغام نیست.")
    type_code = session.scalar(select(DetailDimensionType.code).where(
        DetailDimensionType.dimension_type_id == source.dimension_type_id)) or ""
    if type_code in BLOCKED_TYPES:
        raise ValueError(f"گردش {BLOCKED_TYPES[type_code]} دفتر جداگانه دارد و از این راه جابه‌جا نمی‌شود؛ "
                         "از عملیات خود همان بخش استفاده کنید.")
    if not target.is_active:
        raise ValueError(f"تفصیلی مقصد «{_label(target)}» غیرفعال است.")
    return source, target, type_code


# --- مانده ---------------------------------------------------------------------------------------
@dataclass
class BalanceRow:
    account_id: int
    account_label: str
    currency_id: int
    currency_code: str
    others: tuple[tuple[int, int], ...]  # (نوع بُعد، تفصیلی) همراه ردیف
    others_label: str
    balance_base: decimal.Decimal  # مثبت = بدهکار
    balance_fc: decimal.Decimal


def _balance_rows(session, company_id: int, detail: DetailAccount, as_of: datetime.date | None) -> list[BalanceRow]:
    q = (select(JournalEntryLine.line_id, JournalEntryLine.account_id, JournalEntryLine.currency_id,
                JournalEntryLine.debit_amount_fc - JournalEntryLine.credit_amount_fc,
                JournalEntryLine.debit_amount_base - JournalEntryLine.credit_amount_base)
         .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
         .join(JournalEntryStatus, JournalEntryStatus.status_id == JournalEntry.status_id)
         .join(JournalEntryLineDetail, JournalEntryLineDetail.line_id == JournalEntryLine.line_id)
         .where(JournalEntry.company_id == company_id, JournalEntryStatus.code != "DRAFT",
                JournalEntryLineDetail.detail_account_id == detail.detail_account_id))
    if as_of is not None:
        q = q.where(JournalEntry.document_date <= as_of)
    lines = session.execute(q).all()
    if not lines:
        return []
    others: dict[int, list[tuple[int, int]]] = {}
    for line_id, dim_type_id, detail_id in session.execute(
            select(JournalEntryLineDetail.line_id, JournalEntryLineDetail.dimension_type_id,
                   JournalEntryLineDetail.detail_account_id)
            .where(JournalEntryLineDetail.line_id.in_([ln[0] for ln in lines]),
                   JournalEntryLineDetail.dimension_type_id != detail.dimension_type_id)):
        others.setdefault(line_id, []).append((dim_type_id, detail_id))
    sums: dict[tuple, list[decimal.Decimal]] = {}
    for line_id, account_id, currency_id, net_fc, net_base in lines:
        key = (account_id, currency_id, tuple(sorted(others.get(line_id, []))))
        acc = sums.setdefault(key, [_ZERO, _ZERO])
        acc[0] += net_base or _ZERO
        acc[1] += net_fc or _ZERO
    from peecha.services import chart_of_accounts as coa_service

    accounts = {a.account_id: f"{a.full_code} — {a.name}" for a in coa_service.list_accounts(company_id)}
    currencies = dict(session.execute(select(Currency.currency_id, Currency.iso_code)).all())
    other_ids = {d for key in sums for _t, d in key[2]}
    other_names = {d.detail_account_id: _label(d) for d in session.scalars(
        select(DetailAccount).where(DetailAccount.detail_account_id.in_(other_ids)))} if other_ids else {}
    rows = []
    for (account_id, currency_id, extra), (base, fc) in sums.items():
        if base == 0 and fc == 0:
            continue
        rows.append(BalanceRow(account_id, accounts.get(account_id, str(account_id)), currency_id,
                               currencies.get(currency_id, ""), extra, "، ".join(other_names.get(d, "") for _t, d in extra),
                               base, fc))
    rows.sort(key=lambda r: (r.account_label, r.currency_code, r.others_label))
    return rows


def balances(company_id: int, detail_account_id: int, as_of: datetime.date | None = None) -> list[BalanceRow]:
    with new_session() as session:
        detail = session.get(DetailAccount, detail_account_id)
        if detail is None or detail.company_id != company_id:
            raise ValueError("تفصیلی نامعتبر است.")
        return _balance_rows(session, company_id, detail, as_of)


def _journal_lines(source: DetailAccount, target: DetailAccount, rows: list[BalanceRow], base_currency_id: int):
    from peecha.services import journal_entries as je_service

    out = []
    for row in rows:
        foreign = row.currency_id != base_currency_id and row.balance_fc != 0
        amount = abs(row.balance_fc if foreign else row.balance_base)
        rate = (abs(row.balance_base) / abs(row.balance_fc)).quantize(decimal.Decimal("0.000001")) if foreign else None
        debit_balance = (row.balance_fc if foreign else row.balance_base) > 0
        for detail, removes in ((source, True), (target, False)):
            details = {t: d for t, d in row.others}
            details[detail.dimension_type_id] = detail.detail_account_id
            on_debit = debit_balance != removes
            memo = (f"انتقال مانده به «{_label(target)}»" if removes else f"انتقال مانده از «{_label(source)}»")
            out.append(je_service.LineInput(
                account_id=row.account_id, description=memo, debit=amount if on_debit else _ZERO,
                credit=_ZERO if on_debit else amount, details=details,
                currency_id=row.currency_id if foreign else None, exchange_rate=rate))
    return out


@dataclass
class TransferResult:
    operation_id: int
    journal_entry_id: int
    line_count: int


def transfer_balance(company_id: int, user_id: int | None, source_id: int, target_id: int, date: datetime.date,
                     description: str | None = None) -> TransferResult:
    """ماندهٔ مبدأ تا تاریخ سند، با یک سند حسابداری به مقصد می‌رود؛ مبدأ فعال می‌ماند."""
    from peecha.services import audit as audit_service
    from peecha.services import journal_entries as je_service

    _require(company_id, user_id, FEATURE_TRANSFER, FORM_TRANSFER)
    with new_session() as session:
        source, target, _type = _pair(session, company_id, source_id, target_id)
        rows = _balance_rows(session, company_id, source, date)
        if not rows:
            raise ValueError(f"«{_label(source)}» تا این تاریخ مانده‌ای ندارد.")
        base_currency_id = session.scalar(select(Company.base_currency_id).where(Company.company_id == company_id))
        lines = _journal_lines(source, target, rows, base_currency_id)
        memo = (description or "").strip() or f"انتقال ماندهٔ تفصیلی «{_label(source)}» به «{_label(target)}»"
        entry = je_service.create_journal_entry(company_id, user_id, date, memo, lines, session=session)
        total = sum((abs(r.balance_base) for r in rows), _ZERO)
        op = DetailOperation(company_id=company_id, operation_type="TRANSFER", source_detail_account_id=source.detail_account_id,
                             target_detail_account_id=target.detail_account_id, status_code="DONE",
                             journal_entry_id=entry.journal_entry_id, operation_date=date, description=memo,
                             source_was_active=source.is_active, created_by_user_id=user_id,
                             summary={"rows": len(rows), "total": str(total.quantize(_Q2)),
                                      "temporary_no": entry.temporary_no})
        session.add(op)
        session.flush()
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="DetailAccount",
                                   entity_id=source.detail_account_id, action="UPDATE",
                                   changes={"operation": "BALANCE_TRANSFER", "operation_id": op.operation_id,
                                            "target": _label(target), "journal_entry_id": entry.journal_entry_id,
                                            "rows": len(rows), "total": str(total.quantize(_Q2))})
        session.commit()
        return TransferResult(op.operation_id, entry.journal_entry_id, len(lines))


# --- ادغام کامل ------------------------------------------------------------------------------------
@dataclass
class RefColumn:
    schema: str
    table: str
    column: str
    keys: list[str]
    unique: bool

    @property
    def name(self) -> str:
        return f"{self.schema}.{self.table}"

    @property
    def sql_table(self) -> str:
        return f'"{self.schema}"."{self.table}"'


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def reference_columns(session) -> list[RefColumn]:
    """هر ستونی که به acc.detail_accounts اشاره می‌کند (از کاتالوگ پایگاه داده؛ جدول‌های آینده هم خودکار پوشش داده می‌شوند)."""
    found = session.execute(text("""
        SELECT n.nspname, c.relname, a.attname
        FROM pg_constraint k
        JOIN pg_class c ON c.oid = k.conrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = k.conkey[1]
        WHERE k.contype = 'f' AND k.confrelid = 'acc.detail_accounts'::regclass AND array_length(k.conkey, 1) = 1
        ORDER BY 1, 2, 3""")).all()
    columns = {(s, t, c) for s, t, c in found}
    for s, t, c in _EXTRA_COLUMNS:
        exists = session.scalar(text("SELECT 1 FROM information_schema.columns WHERE table_schema = :s AND table_name = :t "
                                     "AND column_name = :c"), {"s": s, "t": t, "c": c})
        if exists:
            columns.add((s, t, c))
    out = []
    for s, t, c in sorted(columns):
        if (s, t, c) in _SKIP or (s, t) in _SKIP_TABLES:
            continue
        reg = f"{_quote(s)}.{_quote(t)}"
        keys = list(session.scalars(text("""
            SELECT a.attname FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = CAST(:reg AS regclass) AND i.indisprimary
            ORDER BY array_position(i.indkey::int2[], a.attnum)"""), {"reg": reg}))
        if not keys:
            continue
        unique = bool(session.scalar(text("""
            SELECT 1 FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = CAST(:reg AS regclass) AND i.indisunique AND a.attname = :c LIMIT 1"""), {"reg": reg, "c": c}))
        out.append(RefColumn(s, t, c, keys, unique))
    return out


@dataclass
class MergePreview:
    source_label: str
    target_label: str
    counts: list[tuple[str, int]]  # (عنوان، تعداد)
    total: int
    one_to_one: list[str] = field(default_factory=list)  # بخش‌هایی که اگر مقصد هم داشته باشد، روی مبدأ می‌مانند
    balance_rows: int = 0


def _count(session, col: RefColumn, detail_id: int) -> int:
    return session.scalar(text(f"SELECT count(*) FROM {col.sql_table} WHERE {_quote(col.column)} = :d"), {"d": detail_id}) or 0


def _check_merge(session, company_id: int, source: DetailAccount, target: DetailAccount) -> None:
    if not source.is_active:
        raise ValueError(f"«{_label(source)}» غیرفعال است (شاید قبلاً ادغام شده باشد).")
    for detail in (source, target):
        if session.scalar(select(func.count()).select_from(DetailAccount)
                          .where(DetailAccount.parent_detail_account_id == detail.detail_account_id)):
            raise ValueError(f"«{_label(detail)}» زیرمجموعه دارد؛ فقط تفصیلی‌های سطح آخر ادغام می‌شوند.")
    if source.person_group_id and target.person_group_id and source.person_group_id != target.person_group_id:
        raise ValueError("مبدأ و مقصد از دو گروه اشخاص متفاوت‌اند (مثلاً مشتری و تامین‌کننده)؛ فقط انتقال مانده ممکن است.")


def merge_preview(company_id: int, source_id: int, target_id: int) -> MergePreview:
    with new_session() as session:
        source, target, _type = _pair(session, company_id, source_id, target_id)
        _check_merge(session, company_id, source, target)
        grouped: dict[str, int] = {}
        one_to_one = []
        for col in reference_columns(session):
            n = _count(session, col, source.detail_account_id)
            if not n:
                continue
            label = TABLE_LABELS.get(col.name, "سایر اطلاعات مرتبط")
            grouped[label] = grouped.get(label, 0) + n
            if col.unique and label not in one_to_one:
                one_to_one.append(label)
        counts = sorted(grouped.items(), key=lambda kv: (kv[0] == "سایر اطلاعات مرتبط", -kv[1]))
        return MergePreview(_label(source), _label(target), counts, sum(grouped.values()), one_to_one,
                            len(_balance_rows(session, company_id, source, None)))


def _key_json(keys: list[str], values) -> list:
    return [[k, v if isinstance(v, (int, str)) or v is None else str(v), not isinstance(v, (int, str))]
            for k, v in zip(keys, values)]


def _key_where(key: list, prefix: str = "k") -> tuple[str, dict]:
    parts, params = [], {}
    for i, (name, value, as_text) in enumerate(key):
        col = f"CAST({_quote(name)} AS TEXT)" if as_text else _quote(name)
        parts.append(f"{col} = :{prefix}{i}")
        params[f"{prefix}{i}"] = value
    return " AND ".join(parts), params


@dataclass
class MergeResult:
    operation_id: int
    moved: int
    kept_on_source: int


def merge(company_id: int, user_id: int | None, source_id: int, target_id: int, reason: str | None = None) -> MergeResult:
    """همهٔ گردش و ارجاع‌های مبدأ به مقصد می‌رود و مبدأ غیرفعال می‌شود (همه در یک تراکنش)."""
    from peecha.services import audit as audit_service

    _require(company_id, user_id, FEATURE_MERGE, FORM_MERGE)
    with new_session() as session:
        source, target, _type = _pair(session, company_id, source_id, target_id)
        _check_merge(session, company_id, source, target)
        op = DetailOperation(company_id=company_id, operation_type="MERGE", source_detail_account_id=source.detail_account_id,
                             target_detail_account_id=target.detail_account_id, status_code="DONE",
                             operation_date=datetime.date.today(), description=(reason or "").strip() or None,
                             source_was_active=source.is_active, created_by_user_id=user_id, summary={})
        session.add(op)
        session.flush()
        src, tgt = source.detail_account_id, target.detail_account_id
        moved, kept, by_table = 0, 0, {}
        for col in reference_columns(session):
            keys_sql = ", ".join(_quote(k) for k in col.keys)
            rows = []
            if not col.unique:
                nested = session.begin_nested()
                try:
                    rows = session.execute(text(
                        f"UPDATE {col.sql_table} SET {_quote(col.column)} = :t WHERE {_quote(col.column)} = :s "
                        f"RETURNING {keys_sql}"), {"s": src, "t": tgt}).all()
                    nested.commit()
                except IntegrityError:
                    nested.rollback()
                    rows = None
            if col.unique or rows is None:
                rows = []
                for key_values in session.execute(text(
                        f"SELECT {keys_sql} FROM {col.sql_table} WHERE {_quote(col.column)} = :s"), {"s": src}).all():
                    where, params = _key_where(_key_json(col.keys, key_values))
                    nested = session.begin_nested()
                    try:
                        session.execute(text(f"UPDATE {col.sql_table} SET {_quote(col.column)} = :t WHERE {where}"),
                                        {"t": tgt, **params})
                        nested.commit()
                        rows.append(key_values)
                    except IntegrityError:
                        nested.rollback()
                        kept += 1
            if rows:
                session.execute(insert(DetailMergeRow), [
                    {"operation_id": op.operation_id, "table_name": col.name, "column_name": col.column,
                     "row_key": _key_json(col.keys, r)} for r in rows])
                moved += len(rows)
                label = TABLE_LABELS.get(col.name, "سایر اطلاعات مرتبط")
                by_table[label] = by_table.get(label, 0) + len(rows)
        source = session.get(DetailAccount, src)
        source.is_active = False
        op.summary = {"moved": moved, "kept_on_source": kept, "by_table": by_table}
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="DetailAccount",
                                   entity_id=src, action="UPDATE",
                                   changes={"operation": "MERGE", "operation_id": op.operation_id, "target": _label(target),
                                            "moved": moved, "kept_on_source": kept, "reason": reason or ""})
        session.commit()
        return MergeResult(op.operation_id, moved, kept)


# --- برگشت و فهرست ---------------------------------------------------------------------------------
@dataclass
class ReverseResult:
    restored: int = 0
    not_restored: int = 0
    reversal_entry_id: int | None = None


def _reverse_merge(session, op: DetailOperation) -> ReverseResult:
    result = ReverseResult()
    src, tgt = op.source_detail_account_id, op.target_detail_account_id
    for row in session.scalars(select(DetailMergeRow).where(DetailMergeRow.operation_id == op.operation_id)
                               .order_by(DetailMergeRow.merge_row_id)):
        schema, table = row.table_name.split(".", 1)
        where, params = _key_where(row.row_key)
        nested = session.begin_nested()
        try:
            done = session.execute(text(
                f"UPDATE {_quote(schema)}.{_quote(table)} SET {_quote(row.column_name)} = :s "
                f"WHERE {where} AND {_quote(row.column_name)} = :t"), {"s": src, "t": tgt, **params}).rowcount
            nested.commit()
        except IntegrityError:
            nested.rollback()
            done = 0
        if done:
            result.restored += 1
        else:
            result.not_restored += 1
    source = session.get(DetailAccount, src)
    if source is not None and op.source_was_active is not None:
        source.is_active = op.source_was_active
    return result


def reverse(company_id: int, user_id: int | None, operation_id: int) -> ReverseResult:
    """انتقال: سند برگشتی؛ ادغام: هر ردیف جابه‌جاشده (اگر هنوز روی مقصد است) به مبدأ برمی‌گردد و مبدأ دوباره فعال می‌شود."""
    from peecha.services import audit as audit_service
    from peecha.services import journal_entries as je_service

    with new_session() as session:
        op = session.get(DetailOperation, operation_id)
        if op is None or op.company_id != company_id:
            raise ValueError("عملیات نامعتبر است.")
        if op.status_code != "DONE":
            raise ValueError("این عملیات قبلاً برگشت خورده است.")
        kind, journal_entry_id = op.operation_type, op.journal_entry_id
    if kind == "TRANSFER":
        _require(company_id, user_id, FEATURE_TRANSFER, FORM_TRANSFER, "DELETE")
        reversal = je_service.reverse_journal_entry(journal_entry_id, company_id, user_id)
        result = ReverseResult(reversal_entry_id=reversal.journal_entry_id)
    else:
        _require(company_id, user_id, FEATURE_MERGE, FORM_MERGE, "DELETE")
        result = None
    with new_session() as session:
        op = session.get(DetailOperation, operation_id)
        if kind == "MERGE":
            result = _reverse_merge(session, op)
        op.status_code = "REVERSED"
        op.reversal_entry_id = result.reversal_entry_id
        op.reversed_by_user_id = user_id
        op.reversed_at = datetime.datetime.now().astimezone()
        op.summary = {**(op.summary or {}), "restored": result.restored, "not_restored": result.not_restored}
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="DetailAccount",
                                   entity_id=op.source_detail_account_id, action="UPDATE",
                                   changes={"operation": f"{kind}_REVERSE", "operation_id": op.operation_id,
                                            "reversal_entry_id": result.reversal_entry_id, "restored": result.restored,
                                            "not_restored": result.not_restored})
        session.commit()
    return result


@dataclass
class OperationRow:
    operation_id: int
    operation_type: str
    type_label: str
    status_code: str
    status_label: str
    source_id: int
    source_label: str
    target_id: int
    target_label: str
    operation_date: datetime.date
    description: str
    summary: dict


def list_operations(company_id: int, detail_account_id: int | None = None) -> list[OperationRow]:
    with new_session() as session:
        q = select(DetailOperation).where(DetailOperation.company_id == company_id)
        if detail_account_id is not None:
            q = q.where((DetailOperation.source_detail_account_id == detail_account_id)
                        | (DetailOperation.target_detail_account_id == detail_account_id))
        ops = list(session.scalars(q.order_by(DetailOperation.operation_id.desc())))
        ids = {o.source_detail_account_id for o in ops} | {o.target_detail_account_id for o in ops}
        names = {d.detail_account_id: _label(d) for d in session.scalars(
            select(DetailAccount).where(DetailAccount.detail_account_id.in_(ids)))} if ids else {}
        return [OperationRow(o.operation_id, o.operation_type, TYPE_LABELS.get(o.operation_type, o.operation_type),
                             o.status_code, STATUS_LABELS.get(o.status_code, o.status_code), o.source_detail_account_id,
                             names.get(o.source_detail_account_id, ""), o.target_detail_account_id,
                             names.get(o.target_detail_account_id, ""), o.operation_date, o.description or "",
                             dict(o.summary or {})) for o in ops]


def candidates(company_id: int, detail_account_id: int) -> list[tuple[str, int]]:
    """تفصیلی‌های هم‌گروه و فعال (مقصد ممکن)."""
    with new_session() as session:
        detail = session.get(DetailAccount, detail_account_id)
        if detail is None or detail.company_id != company_id:
            return []
        q = (select(DetailAccount).where(DetailAccount.company_id == company_id,
                                         DetailAccount.dimension_type_id == detail.dimension_type_id,
                                         DetailAccount.is_active.is_(True),
                                         DetailAccount.detail_account_id != detail_account_id,
                                         DetailAccount.code != dims.NO_DETAIL_CODE)
             .order_by(DetailAccount.code))
        return [(_label(d), d.detail_account_id) for d in session.scalars(q)]
