"""هستهٔ مشترکِ دارایی‌هایِ ثابت -- R262: تنظیمات، دفتر، گروه/طبقه/محل، ثبتِ حسابداری و دفترِ دارایی.

قاعده: هیچ ثبتِ مالی بیرون از موتورِ سندِ حسابداریِ موجود (journal_entries.create_journal_entry) ساخته نمی‌شود؛
سند و دفترِ دارایی در یک تراکنش (session) ثبت می‌شوند تا یا هر دو بنشینند یا هیچ‌کدام (Phase 35).
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

import jdatetime
from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.fixed_assets import (
    Asset, AssetBook, AssetCategory, AssetGroup, AssetLocation, AssetSettings, AssetTransaction,
)

ZERO = decimal.Decimal(0)
_Q2 = decimal.Decimal("0.01")
ENTRY_TYPE = "FIXED_ASSET"

STATUS_LABELS = {
    "DRAFT": "پیش‌نویس", "UNDER_CONSTRUCTION": "در جریانِ تکمیل", "ACQUIRED": "تحصیل‌شده", "CAPITALIZED": "سرمایه‌ای‌شده",
    "IN_SERVICE": "در حالِ بهره‌برداری", "UNDER_MAINTENANCE": "در تعمیر", "TRANSFERRED": "منتقل‌شده", "SUSPENDED": "متوقف",
    "IMPAIRED": "کاهشِ ارزش‌یافته", "FULLY_DEPRECIATED": "کاملاً مستهلک", "DISPOSED": "واگذارشده", "SOLD": "فروخته‌شده",
    "SCRAPPED": "اسقاط‌شده", "MERGED": "ادغام‌شده", "SPLIT": "تقسیم‌شده",
}
METHOD_LABELS = {"STRAIGHT_LINE": "خطِ مستقیم", "DECLINING_BALANCE": "نزولی", "UNITS_OF_PRODUCTION": "بر اساسِ تولید/کارکرد",
                 "NONE": "بدونِ استهلاک"}
TYPE_LABELS = {"LAND": "زمین", "BUILDING": "ساختمان", "MACHINE": "ماشین‌آلات", "EQUIPMENT": "تجهیزات", "VEHICLE": "وسیلهٔ نقلیه",
               "IT": "تجهیزاتِ رایانه‌ای", "FURNITURE": "اثاثیه", "TOOL": "ابزارآلات", "INSTALLATION": "تأسیسات",
               "INTANGIBLE": "نامشهود", "OTHER": "سایر"}
TXN_LABELS = {"ACQUISITION": "تحصیل", "CAPITALIZATION": "سرمایه‌ای‌شدن", "DEPRECIATION": "استهلاک", "IMPROVEMENT": "افزایشِ سرمایه‌ای",
              "IMPAIRMENT": "کاهشِ ارزش", "REVALUATION": "تجدیدِ ارزیابی", "TRANSFER": "انتقال", "RECLASS": "تغییرِ طبقه",
              "SPLIT_OUT": "تقسیم (خروج)", "SPLIT_IN": "تقسیم (ورود)", "MERGE_OUT": "ادغام (خروج)", "MERGE_IN": "ادغام (ورود)",
              "DISPOSAL": "واگذاری", "SALE": "فروش", "SCRAP": "اسقاط", "REVERSAL": "برگشت", "ADJUSTMENT": "اصلاح", "OPENING": "افتتاحیه"}
# وضعیت‌هایی که دیگر هیچ عملیاتِ مالی نمی‌پذیرند
CLOSED_STATUSES = {"DISPOSED", "SOLD", "SCRAPPED", "MERGED", "SPLIT"}
# وضعیت‌هایی که استهلاک می‌خورند
DEPRECIABLE_STATUSES = {"CAPITALIZED", "IN_SERVICE", "UNDER_MAINTENANCE", "TRANSFERRED", "IMPAIRED"}

DEFAULT_CATEGORIES = (
    ("LAND", "زمین", "NONE", None), ("BUILDING", "ساختمان", "STRAIGHT_LINE", 300), ("MACHINERY", "ماشین‌آلات", "STRAIGHT_LINE", 120),
    ("PRODUCTION", "تجهیزاتِ تولید", "STRAIGHT_LINE", 120), ("VEHICLE", "وسایطِ نقلیه", "DECLINING_BALANCE", 72),
    ("OFFICE", "تجهیزاتِ اداری", "STRAIGHT_LINE", 60), ("IT", "تجهیزاتِ IT", "STRAIGHT_LINE", 36),
    ("TOOLS", "ابزارآلات", "STRAIGHT_LINE", 48), ("FURNITURE", "اثاثیه و منصوبات", "STRAIGHT_LINE", 120),
    ("INSTALLATIONS", "تأسیسات", "STRAIGHT_LINE", 180), ("OTHER", "سایر دارایی‌ها", "STRAIGHT_LINE", 60),
)
ACCOUNT_FIELDS = {
    "asset_account_id": "حسابِ دارایی", "accumulated_depreciation_account_id": "استهلاکِ انباشته",
    "depreciation_expense_account_id": "هزینهٔ استهلاک", "disposal_gain_account_id": "سودِ واگذاری",
    "disposal_loss_account_id": "زیانِ واگذاری", "impairment_account_id": "زیانِ کاهشِ ارزش",
    "revaluation_account_id": "مازادِ تجدیدِ ارزیابی", "cip_account_id": "دارایی در جریانِ تکمیل",
    "maintenance_expense_account_id": "هزینهٔ تعمیر و نگهداری",
}


def money(value) -> decimal.Decimal:
    return decimal.Decimal(value).quantize(_Q2, rounding=decimal.ROUND_HALF_UP)


# --- دوره‌هایِ شمسی ------------------------------------------------------------------
def period_of(date: datetime.date) -> tuple[str, datetime.date, datetime.date]:
    """(کدِ دوره «۱۴۰۵/۰۲»، اولِ ماه، آخرِ ماه) -- تقویمِ شمسیِ ERP."""
    j = jdatetime.date.fromgregorian(date=date)
    start = j.replace(day=1)
    nxt = (start + jdatetime.timedelta(days=32)).replace(day=1)
    return f"{j.year}/{j.month:02d}", start.togregorian(), nxt.togregorian() - datetime.timedelta(days=1)


def period_from_code(code: str) -> tuple[str, datetime.date, datetime.date]:
    year, month = (int(x) for x in code.split("/"))
    return period_of(jdatetime.date(year, month, 1).togregorian())


def months_between(start: datetime.date, end: datetime.date) -> int:
    """تعدادِ ماه‌هایِ شمسیِ کاملِ [start, end] (هر دو ماه شمرده می‌شوند)."""
    a, b = jdatetime.date.fromgregorian(date=start), jdatetime.date.fromgregorian(date=end)
    return (b.year - a.year) * 12 + (b.month - a.month) + 1


def add_months(date: datetime.date, months: int) -> datetime.date:
    j = jdatetime.date.fromgregorian(date=date).replace(day=1)
    total = j.year * 12 + (j.month - 1) + months
    return jdatetime.date(total // 12, total % 12 + 1, 1).togregorian()


# --- تنظیمات و دفتر -------------------------------------------------------------------
def settings(session, company_id: int) -> AssetSettings:
    row = session.get(AssetSettings, company_id)
    if row is None:
        row = AssetSettings(company_id=company_id, depreciation_start_rule="IN_SERVICE", depreciation_frequency="MONTHLY",
                            improvement_capitalize_min=ZERO, require_cost_center=False)
        session.add(row)
        session.flush()
    return row


def get_settings(company_id: int) -> AssetSettings:
    with new_session() as session:
        row = settings(session, company_id)
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def update_settings(company_id: int, user_id: int | None = None, **fields) -> None:
    from peecha.services import audit as audit_service

    allowed = {"depreciation_start_rule", "depreciation_frequency", "improvement_capitalize_min", "require_cost_center",
               "large_improvement_approval_min"}
    with new_session() as session:
        row = settings(session, company_id)
        changes = {}
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"تنظیمِ نامعتبر: {key}")
            if getattr(row, key) != value:
                changes[key] = [str(getattr(row, key)), str(value)]
                setattr(row, key, value)
        row.updated_at = datetime.datetime.now()
        if changes:
            audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="AssetSettings",
                                       entity_id=company_id, action="UPDATE", changes=changes)
        session.commit()


def primary_book(session, company_id: int) -> AssetBook:
    book = session.scalar(select(AssetBook).where(AssetBook.company_id == company_id, AssetBook.is_primary.is_(True)))
    if book is None:
        book = AssetBook(company_id=company_id, code="ACC", name="دفترِ حسابداری", is_primary=True, posts_to_gl=True,
                         is_active=True)
        session.add(book)
        session.flush()
    return book


def list_books(company_id: int) -> list[AssetBook]:
    with new_session() as session:
        primary_book(session, company_id)
        session.commit()
        rows = list(session.scalars(select(AssetBook).where(AssetBook.company_id == company_id).order_by(AssetBook.book_id)))
        for r in rows:
            session.expunge(r)
        return rows


# --- طبقه / گروه / محل ----------------------------------------------------------------
@dataclass
class CategoryFields:
    code: str
    name: str
    default_method: str = "STRAIGHT_LINE"
    default_life_months: int | None = None
    default_residual_percent: decimal.Decimal = ZERO
    default_declining_rate: decimal.Decimal | None = None
    cost_center_required: bool = False
    default_cost_center_detail_account_id: int | None = None
    accounts: dict | None = None
    is_active: bool = True


def save_category(company_id: int, fields: CategoryFields, category_id: int | None = None, user_id: int | None = None) -> int:
    from peecha.services import audit as audit_service

    if not fields.code.strip() or not fields.name.strip():
        raise ValueError("کد و نامِ طبقهٔ دارایی الزامی است.")
    if fields.default_method not in METHOD_LABELS:
        raise ValueError("روشِ استهلاکِ نامعتبر.")
    with new_session() as session:
        dup = session.scalar(select(AssetCategory.category_id).where(
            AssetCategory.company_id == company_id, AssetCategory.code == fields.code.strip()))
        if dup is not None and dup != category_id:
            raise ValueError("این کدِ طبقه قبلاً تعریف شده است.")
        row = session.get(AssetCategory, category_id) if category_id else AssetCategory(company_id=company_id)
        if row is None or row.company_id != company_id:
            raise ValueError("طبقهٔ دارایی نامعتبر است.")
        before = {k: getattr(row, k, None) for k in ("default_method", "default_life_months", *ACCOUNT_FIELDS)}
        row.code, row.name = fields.code.strip(), fields.name.strip()
        row.default_method, row.default_life_months = fields.default_method, fields.default_life_months
        row.default_residual_percent = decimal.Decimal(fields.default_residual_percent or 0)
        row.default_declining_rate = fields.default_declining_rate
        row.cost_center_required = fields.cost_center_required
        row.default_cost_center_detail_account_id = fields.default_cost_center_detail_account_id
        row.is_active = fields.is_active
        for key, value in (fields.accounts or {}).items():
            if key not in ACCOUNT_FIELDS:
                raise ValueError(f"حسابِ نامعتبر: {key}")
            setattr(row, key, value)
        if category_id is None:
            session.add(row)
        session.flush()
        after = {k: getattr(row, k) for k in before}
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="AssetCategory",
                                   entity_id=row.category_id, action="CREATE" if category_id is None else "UPDATE",
                                   changes={k: [str(before[k]), str(after[k])] for k in before if before[k] != after[k]})
        session.commit()
        return row.category_id


def ensure_default_categories(company_id: int) -> None:
    """طبقه‌هایِ پیش‌فرض (زمین، ساختمان، ماشین‌آلات، ...) بدونِ حساب -- حساب‌ها را کاربر در تنظیمات تعیین می‌کند."""
    with new_session() as session:
        existing = set(session.scalars(select(AssetCategory.code).where(AssetCategory.company_id == company_id)))
        for code, name, method, life in DEFAULT_CATEGORIES:
            if code not in existing:
                session.add(AssetCategory(company_id=company_id, code=code, name=name, default_method=method,
                                          default_life_months=life, default_residual_percent=ZERO,
                                          default_declining_rate=decimal.Decimal("0.25") if method == "DECLINING_BALANCE" else None,
                                          cost_center_required=False, is_active=True))
        primary_book(session, company_id)
        settings(session, company_id)
        session.commit()


def list_categories(company_id: int, active_only: bool = False) -> list[AssetCategory]:
    with new_session() as session:
        q = select(AssetCategory).where(AssetCategory.company_id == company_id)
        if active_only:
            q = q.where(AssetCategory.is_active.is_(True))
        rows = list(session.scalars(q.order_by(AssetCategory.code)))
        for r in rows:
            session.expunge(r)
        return rows


def missing_accounts(category: AssetCategory, needed: tuple[str, ...]) -> list[str]:
    return [ACCOUNT_FIELDS[k] for k in needed if getattr(category, k) is None]


def require_accounts(category: AssetCategory, needed: tuple[str, ...]) -> None:
    missing = missing_accounts(category, needed)
    if missing:
        raise ValueError(f"نگاشتِ حسابِ طبقهٔ «{category.name}» ناقص است: {'، '.join(missing)}")


def save_group(company_id: int, code: str, name: str, group_id: int | None = None) -> int:
    with new_session() as session:
        dup = session.scalar(select(AssetGroup.group_id).where(AssetGroup.company_id == company_id, AssetGroup.code == code.strip()))
        if dup is not None and dup != group_id:
            raise ValueError("این کدِ گروه قبلاً تعریف شده است.")
        row = session.get(AssetGroup, group_id) if group_id else AssetGroup(company_id=company_id, is_active=True)
        row.code, row.name = code.strip(), name.strip()
        if group_id is None:
            session.add(row)
        session.commit()
        return row.group_id


def list_groups(company_id: int) -> list[AssetGroup]:
    with new_session() as session:
        rows = list(session.scalars(select(AssetGroup).where(AssetGroup.company_id == company_id).order_by(AssetGroup.code)))
        for r in rows:
            session.expunge(r)
        return rows


def save_location(company_id: int, code: str, name: str, location_type: str = "ROOM", parent_location_id: int | None = None,
                  branch_id: int | None = None, location_id: int | None = None) -> int:
    with new_session() as session:
        dup = session.scalar(select(AssetLocation.location_id).where(
            AssetLocation.company_id == company_id, AssetLocation.code == code.strip()))
        if dup is not None and dup != location_id:
            raise ValueError("این کدِ محل قبلاً تعریف شده است.")
        if parent_location_id is not None and location_id is not None:
            node = parent_location_id
            while node is not None:  # جلوگیری از حلقه
                if node == location_id:
                    raise ValueError("محل نمی‌تواند زیرمجموعهٔ خودش باشد.")
                node = session.scalar(select(AssetLocation.parent_location_id).where(AssetLocation.location_id == node))
        row = session.get(AssetLocation, location_id) if location_id else AssetLocation(company_id=company_id, is_active=True)
        row.code, row.name, row.location_type = code.strip(), name.strip(), location_type
        row.parent_location_id, row.branch_id = parent_location_id, branch_id
        if location_id is None:
            session.add(row)
        session.commit()
        return row.location_id


def list_locations(company_id: int) -> list[AssetLocation]:
    with new_session() as session:
        rows = list(session.scalars(select(AssetLocation).where(AssetLocation.company_id == company_id)
                                    .order_by(AssetLocation.code)))
        for r in rows:
            session.expunge(r)
        return rows


def location_path(session, location_id: int | None) -> str:
    parts, node = [], location_id
    while node is not None and len(parts) < 10:
        loc = session.get(AssetLocation, node)
        if loc is None:
            break
        parts.append(loc.name)
        node = loc.parent_location_id
    return " ‹ ".join(reversed(parts))


# --- ثبتِ حسابداری (فقط از موتورِ موجود) و دفترِ دارایی ---------------------------------------
@dataclass
class JLine:
    account_id: int | None
    debit: decimal.Decimal = ZERO
    credit: decimal.Decimal = ZERO
    detail_ids: tuple[int | None, ...] = ()
    description: str = ""


def post_journal(session, company_id: int, user_id: int | None, date: datetime.date, description: str,
                 lines: list[JLine]) -> int | None:
    """سندِ حسابداری در همان تراکنش؛ ردیف‌هایِ صفر حذف و ردیف‌هایِ هم‌حساب/هم‌تفصیلی تجمیع می‌شوند."""
    from peecha.services import journal_entries as je_service

    merged: dict[tuple, list] = {}
    for ln in lines:
        if ln.account_id is None:
            raise ValueError("نگاشتِ حسابِ دارایی ناقص است (حسابِ یکی از ردیف‌هایِ سند تعیین نشده).")
        details = tuple(sorted(d for d in ln.detail_ids if d))
        key = (ln.account_id, details, ln.description)
        acc = merged.setdefault(key, [ZERO, ZERO])
        acc[0] += money(ln.debit)
        acc[1] += money(ln.credit)
    inputs = []
    dim_of: dict[int, int] = {}
    all_details = {d for k in merged for d in k[1]}
    if all_details:
        dim_of = dict(session.execute(select(DetailAccount.detail_account_id, DetailAccount.dimension_type_id)
                                      .where(DetailAccount.detail_account_id.in_(all_details))).all())
    for (account_id, details, desc), (debit, credit) in merged.items():
        net = debit - credit
        if net == 0:
            continue
        inputs.append(je_service.LineInput(
            account_id=account_id, description=desc or description, debit=net if net > 0 else ZERO,
            credit=-net if net < 0 else ZERO, details={dim_of[d]: d for d in details if d in dim_of}))
    if not inputs:
        return None
    if user_id is None:
        raise ValueError("کاربرِ ثبت‌کننده مشخص نیست.")
    return je_service.create_journal_entry(company_id, user_id, date, description, inputs, entry_type_code=ENTRY_TYPE,
                                           session=session).journal_entry_id


def record_txn(session, asset: Asset, book_id: int, txn_type: str, date: datetime.date, *, cost=ZERO, depreciation=ZERO,
               impairment=ZERO, revaluation=ZERO, units=None, description=None, reference=None, journal_entry_id=None,
               source_type=None, source_id=None, user_id=None, reversed_txn_id=None, primary: bool = True) -> AssetTransaction:
    """ردیفِ دفترِ دارایی + به‌روزرسانیِ ارقامِ کش‌شدهٔ دارایی (در همان تراکنش)."""
    txn = AssetTransaction(
        company_id=asset.company_id, asset_id=asset.asset_id, book_id=book_id, txn_type=txn_type, txn_date=date,
        cost_delta=money(cost), depreciation_delta=money(depreciation), impairment_delta=money(impairment),
        revaluation_delta=money(revaluation), units=units, description=description, reference=reference,
        journal_entry_id=journal_entry_id, source_type=source_type, source_id=source_id, created_by_user_id=user_id,
        reversed_txn_id=reversed_txn_id)
    session.add(txn)
    if primary:
        asset.gross_cost = money(asset.gross_cost + txn.cost_delta)
        asset.accumulated_depreciation = money(asset.accumulated_depreciation + txn.depreciation_delta)
        asset.accumulated_impairment = money(asset.accumulated_impairment + txn.impairment_delta)
        asset.revaluation_surplus = money(asset.revaluation_surplus + txn.revaluation_delta)
        if units:
            asset.units_consumed = (asset.units_consumed or ZERO) + decimal.Decimal(units)
        asset.updated_at = datetime.datetime.now()
    session.flush()
    return txn


def lock_asset(session, asset_id: int, company_id: int) -> Asset:
    asset = session.scalar(select(Asset).where(Asset.asset_id == asset_id).with_for_update())
    if asset is None or asset.company_id != company_id:
        raise ValueError("دارایی نامعتبر است.")
    return asset


def ensure_open(asset: Asset) -> None:
    if asset.status_code in CLOSED_STATUSES:
        raise ValueError(f"دارایی «{asset.asset_code}» در وضعیتِ «{STATUS_LABELS[asset.status_code]}» است و عملیاتِ مالی نمی‌پذیرد.")


def ledger_totals(session, asset_id: int, book_id: int | None = None) -> dict[str, decimal.Decimal]:
    q = select(func.coalesce(func.sum(AssetTransaction.cost_delta), 0), func.coalesce(func.sum(AssetTransaction.depreciation_delta), 0),
               func.coalesce(func.sum(AssetTransaction.impairment_delta), 0),
               func.coalesce(func.sum(AssetTransaction.revaluation_delta), 0)).where(AssetTransaction.asset_id == asset_id)
    if book_id is not None:
        q = q.where(AssetTransaction.book_id == book_id)
    cost, dep, imp, rev = session.execute(q).one()
    return {"cost": decimal.Decimal(cost), "depreciation": decimal.Decimal(dep), "impairment": decimal.Decimal(imp),
            "revaluation": decimal.Decimal(rev)}


def audit(session, company_id: int, user_id: int | None, asset_id: int, operation: str, changes: dict,
          entity_type: str = "FixedAsset") -> None:
    """Audit با همان سرویسِ موجود؛ نامِ عملیاتِ دارایی (انتقال، فروش، ...) در changes.operation می‌ماند."""
    from peecha.services import audit as audit_service

    action = operation if operation in ("CREATE", "DELETE") else "UPDATE"
    audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type=entity_type, entity_id=asset_id,
                               action=action, changes={"operation": operation, **changes})
