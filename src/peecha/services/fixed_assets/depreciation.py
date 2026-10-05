"""موتورِ استهلاک -- R262.

روش‌ها (آینده‌نگر؛ تغییرِ بها/کاهشِ ارزش/تجدیدِ ارزیابی از دورهٔ بعد اثر می‌گذارد):
  خطِ مستقیم: (ارزشِ دفتری − اسقاط) ÷ ماه‌هایِ باقی‌ماندهٔ عمر  ← برایِ داراییِ دست‌نخورده = (بها − اسقاط) ÷ عمر
  نزولی: ارزشِ دفتری × نرخِ سالانه ÷ ۱۲ (کف = اسقاط؛ ماهِ آخرِ عمر تمامِ مانده)
  بر اساسِ تولید: (ارزشِ دفتری − اسقاط) × کارکردِ دوره ÷ کارکردِ باقی‌مانده
اجرایِ دوره: محاسبه ← بررسی ← تأیید ← ثبت (اتمیک: سند + دفترِ دارایی + وضعیت؛ هر خطا = هیچ تغییری).
هر دوره/دفتر فقط یک اجرایِ فعال دارد (ایندکسِ یکتا)؛ ثبتِ دوباره سندِ دوم نمی‌سازد. اصلاح فقط با برگشت.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.fixed_assets import (
    Asset, AssetCategory, AssetTransaction, AssetUsage, DepreciationLine, DepreciationRun,
)
from peecha.services.fixed_assets import common as c

ZERO = c.ZERO
RUN_STATUS_LABELS = {"CALCULATED": "محاسبه‌شده", "REVIEWED": "بررسی‌شده", "APPROVED": "تأییدشده", "POSTED": "ثبت‌شده",
                     "REVERSED": "برگشت‌خورده"}


def life_months(asset) -> int | None:
    if asset.useful_life is None or asset.useful_life_unit not in ("MONTH", "YEAR"):
        return None
    months = asset.useful_life * (12 if asset.useful_life_unit == "YEAR" else 1)
    return int(months.to_integral_value(rounding=decimal.ROUND_HALF_UP))


def annual_rate(asset) -> decimal.Decimal:
    if asset.declining_rate:
        return decimal.Decimal(asset.declining_rate)
    months = life_months(asset)
    return decimal.Decimal(2) * 12 / months if months else ZERO


def usage_between(session, asset_id: int, start: datetime.date, end: datetime.date) -> decimal.Decimal:
    return decimal.Decimal(session.scalar(select(func.coalesce(func.sum(AssetUsage.units), 0)).where(
        AssetUsage.asset_id == asset_id, AssetUsage.usage_date.between(start, end))) or 0)


@dataclass
class Calc:
    amount: decimal.Decimal
    opening: decimal.Decimal
    closing: decimal.Decimal
    units: decimal.Decimal | None = None


def compute(asset, period_start: datetime.date, period_end: datetime.date, *, book_value: decimal.Decimal | None = None,
            units: decimal.Decimal | None = None, units_consumed: decimal.Decimal | None = None,
            months_done: int = 0) -> Calc:
    """استهلاکِ یک دوره برایِ یک دارایی (بدونِ اثر روی دیتابیس). months_done = ماه‌هایِ ثبت‌شدهٔ قبلی؛
    ماه‌هایِ عقب‌افتاده در همین دوره جبران می‌شوند."""
    nbv = asset.book_value if book_value is None else book_value
    zero = Calc(ZERO, nbv, nbv, units)
    if (asset.depreciation_method == "NONE" or asset.depreciation_start_date is None
            or asset.depreciation_start_date > period_end):
        return zero
    remaining_value = nbv - (asset.residual_value or ZERO)
    if remaining_value <= 0:
        return zero
    method = asset.depreciation_method
    if method == "UNITS_OF_PRODUCTION":
        total = decimal.Decimal(asset.useful_life or 0)
        used = decimal.Decimal(asset.units_consumed if units_consumed is None else units_consumed)
        left = total - used
        if not units or left <= 0:
            return zero
        amount = remaining_value if units >= left else remaining_value * units / left
    else:
        months = life_months(asset)
        due = max(c.months_between(asset.depreciation_start_date, period_end) - months_done, 0)
        if due <= 0:
            return zero
        left = (months - months_done) if months else None
        if method == "STRAIGHT_LINE":
            amount = remaining_value if not left or due >= left else remaining_value * due / left
        else:  # DECLINING_BALANCE: ترکیبیِ ماهانه
            monthly = annual_rate(asset) / 12
            amount = nbv * (1 - (1 - monthly) ** due)
            if left is not None and due >= left:
                amount = remaining_value
    amount = min(c.money(amount), c.money(remaining_value))
    return Calc(amount, nbv, nbv - amount, units)


def months_done(session, asset_id: int) -> int:
    """ماه‌هایِ مستهلک‌شده = از شروعِ استهلاک تا پایانِ آخرین دورهٔ ثبت‌شده (هر اجرا ماه‌هایِ عقب‌افتاده را هم پوشش
    می‌دهد). داراییِ حاصل از تقسیم/جزء پیش از نخستین اجرایِ خودش ماه‌هایِ مبدأ را دارد (depreciated_months_offset)."""
    last_end = session.scalar(select(func.max(DepreciationRun.period_end)).join(
        DepreciationLine, DepreciationLine.run_id == DepreciationRun.run_id).where(
        DepreciationLine.asset_id == asset_id, DepreciationRun.status_code == "POSTED"))
    start, offset = session.execute(select(Asset.depreciation_start_date, Asset.depreciated_months_offset)
                                    .where(Asset.asset_id == asset_id)).one()
    by_runs = c.months_between(start, last_end) if last_end and start and last_end >= start else 0
    return max(by_runs, offset or 0)


# --- اجرایِ دوره ---------------------------------------------------------------------------------
def _eligible_assets(session, company_id: int, period_end: datetime.date) -> list[Asset]:
    return list(session.scalars(select(Asset).where(
        Asset.company_id == company_id, Asset.status_code.in_(c.DEPRECIABLE_STATUSES),
        Asset.depreciation_method != "NONE", Asset.depreciation_start_date.is_not(None),
        Asset.depreciation_start_date <= period_end).order_by(Asset.asset_id)))


def _active_run(session, company_id: int, book_id: int, period_code: str) -> DepreciationRun | None:
    return session.scalar(select(DepreciationRun).where(
        DepreciationRun.company_id == company_id, DepreciationRun.book_id == book_id,
        DepreciationRun.period_code == period_code, DepreciationRun.status_code != "REVERSED").with_for_update())


def calculate_run(company_id: int, user_id: int | None, period_code: str, posting_date: datetime.date | None = None,
                  book_id: int | None = None) -> int:
    """محاسبه (یا محاسبهٔ دوباره تا پیش از ثبت). دورهٔ ثبت‌شده/دورهٔ پیش از آخرین ثبت قفل است."""
    code, start, end = c.period_from_code(period_code)
    with new_session() as session:
        book = c.primary_book(session, company_id) if book_id is None else session.get(c.AssetBook, book_id)
        if book is None or not book.is_primary:
            raise ValueError("فعلاً فقط دفترِ اصلیِ حسابداری فعال است.")
        run = _active_run(session, company_id, book.book_id, code)
        if run is not None and run.status_code == "POSTED":
            raise ValueError(f"استهلاکِ دورهٔ {code} قبلاً ثبت شده است؛ برایِ اصلاح ابتدا آن را برگشت بزنید.")
        later = session.scalar(select(DepreciationRun.period_code).where(
            DepreciationRun.company_id == company_id, DepreciationRun.book_id == book.book_id,
            DepreciationRun.status_code == "POSTED", DepreciationRun.period_start > start).limit(1))
        if later:
            raise ValueError(f"دورهٔ بعدی ({later}) ثبت شده است؛ دورهٔ قبلی قابلِ‌محاسبه نیست.")
        if run is None:
            run = DepreciationRun(company_id=company_id, book_id=book.book_id, period_code=code, period_start=start,
                                  period_end=end, posting_date=posting_date or end, created_by_user_id=user_id)
            session.add(run)
            session.flush()
        else:
            for ln in session.scalars(select(DepreciationLine).where(DepreciationLine.run_id == run.run_id)):
                session.delete(ln)
            run.posting_date = posting_date or run.posting_date
            session.flush()
        run.status_code, run.reviewed_by_user_id, run.approved_by_user_id = "CALCULATED", None, None
        problems, total, count = [], ZERO, 0
        categories: dict[int, AssetCategory] = {}
        for asset in _eligible_assets(session, company_id, end):
            units = usage_between(session, asset.asset_id, start, end) if asset.depreciation_method == "UNITS_OF_PRODUCTION" else None
            calc = compute(asset, start, end, units=units, months_done=months_done(session, asset.asset_id))
            if calc.amount <= 0:
                continue
            cat = categories.setdefault(asset.category_id, session.get(AssetCategory, asset.category_id))
            missing = c.missing_accounts(cat, ("depreciation_expense_account_id", "accumulated_depreciation_account_id"))
            if missing:
                problems.append(f"{asset.asset_code}: {'، '.join(missing)}")
                continue
            session.add(DepreciationLine(
                run_id=run.run_id, asset_id=asset.asset_id, method=asset.depreciation_method, opening_book_value=calc.opening,
                amount=calc.amount, closing_book_value=calc.closing, units=units,
                cost_center_detail_account_id=asset.cost_center_detail_account_id or cat.default_cost_center_detail_account_id,
                expense_account_id=cat.depreciation_expense_account_id,
                accumulated_account_id=cat.accumulated_depreciation_account_id))
            total += calc.amount
            count += 1
        if problems:
            raise ValueError("نگاشتِ حسابِ استهلاک ناقص است:\n" + "\n".join(problems))
        run.total_amount, run.asset_count = total, count
        c.audit(session, company_id, user_id, run.run_id, "CALCULATE", {"period": code, "total": str(total), "assets": count},
                entity_type="DepreciationRun")
        session.commit()
        return run.run_id


def _transition(company_id: int, user_id: int | None, run_id: int, from_states: tuple[str, ...], to_state: str, attr: str) -> None:
    with new_session() as session:
        run = session.scalar(select(DepreciationRun).where(DepreciationRun.run_id == run_id).with_for_update())
        if run is None or run.company_id != company_id:
            raise ValueError("اجرایِ استهلاک نامعتبر است.")
        if run.status_code not in from_states:
            raise ValueError(f"اجرا در وضعیتِ «{RUN_STATUS_LABELS[run.status_code]}» است.")
        run.status_code = to_state
        setattr(run, attr, user_id)
        c.audit(session, company_id, user_id, run_id, to_state, {"period": run.period_code}, entity_type="DepreciationRun")
        session.commit()


def review_run(company_id: int, user_id: int | None, run_id: int) -> None:
    _transition(company_id, user_id, run_id, ("CALCULATED",), "REVIEWED", "reviewed_by_user_id")


def approve_run(company_id: int, user_id: int | None, run_id: int) -> None:
    _transition(company_id, user_id, run_id, ("CALCULATED", "REVIEWED"), "APPROVED", "approved_by_user_id")


def post_run(company_id: int, user_id: int, run_id: int) -> int | None:
    """ثبتِ اتمیک: سندِ حسابداری (هزینه به مرکزِ هزینهٔ هر دارایی) + دفترِ دارایی + وضعیت. ثبتِ دوباره = همان سند."""
    with new_session() as session:
        run = session.scalar(select(DepreciationRun).where(DepreciationRun.run_id == run_id).with_for_update())
        if run is None or run.company_id != company_id:
            raise ValueError("اجرایِ استهلاک نامعتبر است.")
        if run.status_code == "POSTED":
            return run.journal_entry_id
        if run.status_code != "APPROVED":
            raise ValueError("فقط اجرایِ تأییدشده قابلِ‌ثبت است.")
        lines = list(session.scalars(select(DepreciationLine).where(DepreciationLine.run_id == run_id)
                                     .order_by(DepreciationLine.asset_id)))
        assets = {}
        jl = []
        for ln in lines:
            asset = c.lock_asset(session, ln.asset_id, company_id)
            if asset.book_value != ln.opening_book_value or asset.status_code not in c.DEPRECIABLE_STATUSES:
                raise ValueError(f"دارایی «{asset.asset_code}» پس از محاسبه تغییر کرده است؛ دوباره محاسبه کنید.")
            assets[ln.asset_id] = asset
            dims = (ln.cost_center_detail_account_id, asset.project_detail_account_id)
            jl.append(c.JLine(ln.expense_account_id, debit=ln.amount, detail_ids=dims))
            jl.append(c.JLine(ln.accumulated_account_id, credit=ln.amount, detail_ids=(ln.cost_center_detail_account_id,)))
        memo = f"استهلاکِ دارایی‌هایِ ثابت -- دورهٔ {run.period_code}"
        je_id = c.post_journal(session, company_id, user_id, run.posting_date, memo, jl) if jl else None
        for ln in lines:
            asset = assets[ln.asset_id]
            txn = c.record_txn(session, asset, run.book_id, "DEPRECIATION", run.posting_date, depreciation=ln.amount,
                               units=ln.units, description=memo, reference=run.period_code, journal_entry_id=je_id,
                               source_type="DEPR_RUN", source_id=run.run_id, user_id=user_id)
            ln.txn_id = txn.txn_id
            if asset.book_value <= (asset.residual_value or ZERO):
                asset.status_code = "FULLY_DEPRECIATED"
        run.status_code, run.journal_entry_id = "POSTED", je_id
        run.posted_by_user_id, run.posted_at = user_id, datetime.datetime.now()
        c.audit(session, company_id, user_id, run_id, "POST", {"period": run.period_code, "total": str(run.total_amount),
                                                               "journal_entry_id": je_id}, entity_type="DepreciationRun")
        session.commit()
        return je_id


def reverse_run(company_id: int, user_id: int, run_id: int, date: datetime.date | None = None, reason: str | None = None) -> int | None:
    """برگشتِ آخرین اجرایِ ثبت‌شده با سندِ معکوس و ردیف‌هایِ برگشتیِ دفترِ دارایی (هیچ ردیفی حذف/ویرایش نمی‌شود)."""
    with new_session() as session:
        run = session.scalar(select(DepreciationRun).where(DepreciationRun.run_id == run_id).with_for_update())
        if run is None or run.company_id != company_id or run.status_code != "POSTED":
            raise ValueError("فقط اجرایِ ثبت‌شده قابلِ‌برگشت است.")
        later = session.scalar(select(DepreciationRun.period_code).where(
            DepreciationRun.company_id == company_id, DepreciationRun.book_id == run.book_id,
            DepreciationRun.status_code == "POSTED", DepreciationRun.period_start > run.period_start).limit(1))
        if later:
            raise ValueError(f"ابتدا دورهٔ بعدی ({later}) را برگشت بزنید.")
        date = date or run.posting_date
        lines = list(session.scalars(select(DepreciationLine).where(DepreciationLine.run_id == run_id)))
        jl, assets = [], {}
        for ln in lines:
            asset = c.lock_asset(session, ln.asset_id, company_id)
            c.ensure_open(asset)
            assets[ln.asset_id] = asset
            jl.append(c.JLine(ln.accumulated_account_id, debit=ln.amount, detail_ids=(ln.cost_center_detail_account_id,)))
            jl.append(c.JLine(ln.expense_account_id, credit=ln.amount,
                              detail_ids=(ln.cost_center_detail_account_id, asset.project_detail_account_id)))
        memo = f"برگشتِ استهلاکِ دورهٔ {run.period_code}" + (f" -- {reason}" if reason else "")
        je_id = c.post_journal(session, company_id, user_id, date, memo, jl) if jl else None
        for ln in lines:
            asset = assets[ln.asset_id]
            c.record_txn(session, asset, run.book_id, "REVERSAL", date, depreciation=-ln.amount,
                         units=-ln.units if ln.units else None, description=memo, reference=run.period_code,
                         journal_entry_id=je_id, source_type="DEPR_RUN", source_id=run.run_id, user_id=user_id,
                         reversed_txn_id=ln.txn_id)
            if asset.status_code == "FULLY_DEPRECIATED" and asset.book_value > (asset.residual_value or ZERO):
                asset.status_code = "IN_SERVICE"
        run.status_code, run.reversal_journal_entry_id = "REVERSED", je_id
        c.audit(session, company_id, user_id, run_id, "REVERSE", {"period": run.period_code, "reason": reason,
                                                                  "journal_entry_id": je_id}, entity_type="DepreciationRun")
        session.commit()
        return je_id


def list_runs(company_id: int) -> list[DepreciationRun]:
    with new_session() as session:
        rows = list(session.scalars(select(DepreciationRun).where(DepreciationRun.company_id == company_id)
                                    .order_by(DepreciationRun.period_start.desc(), DepreciationRun.run_id.desc())))
        for r in rows:
            session.expunge(r)
        return rows


def run_lines(run_id: int) -> list[SimpleNamespace]:
    with new_session() as session:
        rows = session.execute(select(DepreciationLine, Asset.asset_code, Asset.name)
                               .join(Asset, Asset.asset_id == DepreciationLine.asset_id)
                               .where(DepreciationLine.run_id == run_id).order_by(Asset.asset_code)).all()
        return [SimpleNamespace(asset_id=ln.asset_id, asset_code=code, name=name, method=ln.method, opening=ln.opening_book_value,
                                amount=ln.amount, closing=ln.closing_book_value, units=ln.units,
                                cost_center_detail_account_id=ln.cost_center_detail_account_id) for ln, code, name in rows]


# --- کارکرد و پیش‌بینی ---------------------------------------------------------------------------
def record_usage(company_id: int, user_id: int | None, asset_id: int, date: datetime.date, units: decimal.Decimal,
                 source_code: str = "MANUAL", production_order_ref: str | None = None, note: str | None = None) -> int:
    if decimal.Decimal(units) <= 0:
        raise ValueError("کارکرد باید مثبت باشد.")
    with new_session() as session:
        asset = c.lock_asset(session, asset_id, company_id)
        c.ensure_open(asset)
        code, start, _end = c.period_of(date)
        posted = session.scalar(select(DepreciationRun.run_id).join(DepreciationLine, DepreciationLine.run_id == DepreciationRun.run_id)
                                .where(DepreciationLine.asset_id == asset_id, DepreciationRun.period_code == code,
                                       DepreciationRun.status_code == "POSTED"))
        if posted:
            raise ValueError(f"استهلاکِ دورهٔ {code} برایِ این دارایی ثبت شده است؛ کارکردِ آن دوره بسته است.")
        row = AssetUsage(company_id=company_id, asset_id=asset_id, usage_date=date, units=decimal.Decimal(units),
                         source_code=source_code, production_order_ref=production_order_ref, note=note,
                         created_by_user_id=user_id)
        session.add(row)
        session.flush()
        session.commit()
        return row.usage_id


def forecast(company_id: int, asset_id: int, months: int | None = None,
             monthly_units: decimal.Decimal | None = None) -> list[SimpleNamespace]:
    """پیش‌بینیِ استهلاک تا پایانِ عمر (یا n ماه) از دورهٔ ثبت‌نشدهٔ بعدی -- بدونِ اثر روی دیتابیس."""
    with new_session() as session:
        asset = session.get(Asset, asset_id)
        if asset is None or asset.company_id != company_id:
            raise ValueError("دارایی نامعتبر است.")
        session.expunge(asset)
        done = months_done(session, asset_id)
        last = session.scalar(select(func.max(DepreciationRun.period_start)).join(
            DepreciationLine, DepreciationLine.run_id == DepreciationRun.run_id).where(
            DepreciationLine.asset_id == asset_id, DepreciationRun.status_code == "POSTED"))
    if asset.depreciation_start_date is None or asset.depreciation_method == "NONE":
        return []
    start = c.add_months(last, 1) if last else max(asset.depreciation_start_date, datetime.date.today().replace(day=1))
    start = c.period_of(start)[1]
    units_per_month = monthly_units if monthly_units is not None else (
        (asset.standard_hours / 12) if asset.standard_hours else None)
    out, nbv, used = [], asset.book_value, asset.units_consumed or ZERO
    limit = months or 600
    for i in range(limit):
        code, p_start, p_end = c.period_of(c.add_months(start, i))
        calc = compute(asset, p_start, p_end, book_value=nbv, units=units_per_month, units_consumed=used, months_done=done)
        done = max(done, c.months_between(asset.depreciation_start_date, p_end)) if calc.amount > 0 else done
        if calc.amount <= 0 and i > 0 and (asset.depreciation_method != "UNITS_OF_PRODUCTION" or not units_per_month):
            break
        nbv = calc.closing
        used += units_per_month or ZERO
        out.append(SimpleNamespace(period_code=code, amount=calc.amount, book_value=nbv))
        if nbv <= (asset.residual_value or ZERO):
            break
    return out


def schedule(company_id: int, asset_id: int) -> list[SimpleNamespace]:
    """جدولِ کاملِ استهلاک: دوره‌هایِ ثبت‌شده + پیش‌بینی تا پایانِ عمر."""
    with new_session() as session:
        posted = session.execute(select(DepreciationRun.period_code, DepreciationLine.amount, DepreciationLine.closing_book_value)
                                 .join(DepreciationLine, DepreciationLine.run_id == DepreciationRun.run_id)
                                 .where(DepreciationLine.asset_id == asset_id, DepreciationRun.status_code == "POSTED")
                                 .order_by(DepreciationRun.period_start)).all()
    rows = [SimpleNamespace(period_code=p, amount=a, book_value=b, posted=True) for p, a, b in posted]
    for f in forecast(company_id, asset_id):
        f.posted = False
        rows.append(f)
    return rows


def depreciation_for_period(session, asset_id: int, period_code: str) -> decimal.Decimal:
    """استهلاکِ ثبت‌شدهٔ یک دارایی در یک دوره (برایِ بهایِ ماشین در تولید)."""
    return decimal.Decimal(session.scalar(select(func.coalesce(func.sum(AssetTransaction.depreciation_delta), 0)).where(
        AssetTransaction.asset_id == asset_id, AssetTransaction.reference == period_code,
        AssetTransaction.txn_type.in_(("DEPRECIATION", "REVERSAL")))) or 0)
