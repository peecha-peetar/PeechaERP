"""رویدادهایِ مالیِ دارایی -- R263: بهسازی/تعمیر، کاهشِ ارزش، تجدیدِ ارزیابی، فروش/اسقاط/واگذاری، تقسیم، ادغام، جزء، CIP.

هر عملیات اتمیک است (سند + دفترِ دارایی + وضعیت در یک تراکنش) و با idempotency_key تکرارِ مالی ندارد.
عملیاتِ حساس می‌تواند پیش از ثبت در انتظارِ تأیید بماند (approval.py): ابتدا رویدادِ PENDING_APPROVAL ساخته
و پس از تأیید همین توابع با execute اجرا می‌شوند.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import replace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.fixed_assets import Asset, AssetCategory, AssetEvent, CipCost, CipProject
from peecha.services.fixed_assets import assets as fa
from peecha.services.fixed_assets import common as c

ZERO = c.ZERO
DISPOSAL_KINDS = {"SALE": ("SOLD", "SALE", "فروش"), "SCRAP": ("SCRAPPED", "SCRAP", "اسقاط"),
                  "DONATION": ("DISPOSED", "DISPOSAL", "اهدا"), "WRITE_OFF": ("DISPOSED", "DISPOSAL", "حذف از دفاتر")}
CIP_COST_TYPES = {"MATERIAL": "مواد", "LABOR": "دستمزد", "INSTALLATION": "نصب", "TRANSPORT": "حمل", "ENGINEERING": "مهندسی",
                  "OTHER": "سایر هزینه‌هایِ سرمایه‌ای"}


def _done(session, company_id: int, key: str | None) -> AssetEvent | None:
    if not key:
        return None
    return session.scalar(select(AssetEvent).where(AssetEvent.company_id == company_id, AssetEvent.idempotency_key == key))


def _event(session, asset: Asset, event_type: str, date: datetime.date, user_id: int | None, **kw) -> AssetEvent:
    ev = AssetEvent(company_id=asset.company_id, asset_id=asset.asset_id, event_type=event_type, event_date=date,
                    status_code="POSTED", created_by_user_id=user_id, posted_at=datetime.datetime.now(), **kw)
    session.add(ev)
    session.flush()
    return ev


def _dims(asset: Asset) -> tuple:
    return (asset.cost_center_detail_account_id, asset.project_detail_account_id)


def _category(session, asset: Asset) -> AssetCategory:
    return session.get(AssetCategory, asset.category_id)


def _capitalized(asset: Asset) -> None:
    if asset.status_code in ("DRAFT", "ACQUIRED", "UNDER_CONSTRUCTION"):
        raise ValueError("این عملیات فقط برایِ داراییِ سرمایه‌ای‌شده مجاز است.")


# --- بهسازی (سرمایه‌ای) و تعمیر (هزینه) ---------------------------------------------------------------
def improve(company_id: int, user_id: int, asset_id: int, date: datetime.date, amount: decimal.Decimal, offset_account_id: int,
            offset_detail_account_id: int | None = None, description: str | None = None, capital: bool | None = None,
            extend_life_months: int = 0, idempotency_key: str | None = None) -> AssetEvent:
    """capital=None → طبقِ سیاست: مبلغ ≥ حدِ سرمایه‌ای‌شدن (تنظیمات) = افزایشِ سرمایه‌ای، کمتر = هزینهٔ تعمیر.
    سرمایه‌ای: بدهکارِ حسابِ دارایی (و تمدیدِ اختیاریِ عمر)؛ تعمیر: بدهکارِ هزینهٔ تعمیر با مرکزِ هزینهٔ دارایی."""
    amount = c.money(amount)
    if amount <= 0:
        raise ValueError("مبلغ باید مثبت باشد.")
    with new_session() as session:
        done = _done(session, company_id, idempotency_key)
        if done is not None:
            return done
        asset = c.lock_asset(session, asset_id, company_id)
        c.ensure_open(asset)
        _capitalized(asset)
        if capital is None:
            capital = amount >= c.settings(session, company_id).improvement_capitalize_min
        cat = _category(session, asset)
        c.require_accounts(cat, ("asset_account_id",) if capital else ("maintenance_expense_account_id",))
        memo = f"{'افزایشِ سرمایه‌ای' if capital else 'تعمیر و نگهداری'} -- {asset.asset_code}" + (f": {description}" if description else "")
        debit_account = cat.asset_account_id if capital else cat.maintenance_expense_account_id
        je_id = c.post_journal(session, company_id, user_id, date, memo, [
            c.JLine(debit_account, debit=amount, detail_ids=_dims(asset)),
            c.JLine(offset_account_id, credit=amount, detail_ids=(offset_detail_account_id,))])
        ev = _event(session, asset, "IMPROVEMENT" if capital else "MAINTENANCE", date, user_id, amount=amount,
                    reason=description, offset_account_id=offset_account_id,
                    counterparty_detail_account_id=offset_detail_account_id, journal_entry_id=je_id,
                    idempotency_key=idempotency_key, previous_book_value=asset.book_value,
                    details={"capital": capital, "extend_life_months": extend_life_months})
        if capital:
            c.record_txn(session, asset, c.primary_book(session, company_id).book_id, "IMPROVEMENT", date, cost=amount,
                         description=memo, journal_entry_id=je_id, source_type="EVENT", source_id=ev.event_id, user_id=user_id)
            if extend_life_months and asset.useful_life is not None and asset.useful_life_unit in ("MONTH", "YEAR"):
                extra = decimal.Decimal(extend_life_months) / (12 if asset.useful_life_unit == "YEAR" else 1)
                asset.useful_life += extra
            if asset.status_code == "FULLY_DEPRECIATED":
                asset.status_code = "IN_SERVICE"
            ev.new_value = asset.book_value
        c.audit(session, company_id, user_id, asset_id, "IMPROVE" if capital else "MAINTENANCE",
                {"amount": str(amount), "capital": capital, "journal_entry_id": je_id})
        session.commit()
        session.refresh(ev)
        session.expunge(ev)
        return ev


# --- کاهشِ ارزش -----------------------------------------------------------------------------------------
def impair(company_id: int, user_id: int, asset_id: int, date: datetime.date, recoverable_amount: decimal.Decimal,
           reason: str, idempotency_key: str | None = None, approved_by_user_id: int | None = None) -> AssetEvent:
    """کاهشِ ارزش = ارزشِ دفتری − مبلغِ بازیافتنی: بدهکارِ زیانِ کاهشِ ارزش، بستانکارِ استهلاک/کاهشِ ارزشِ انباشته."""
    if not (reason or "").strip():
        raise ValueError("علتِ کاهشِ ارزش الزامی است.")
    with new_session() as session:
        done = _done(session, company_id, idempotency_key)
        if done is not None:
            return done
        asset = c.lock_asset(session, asset_id, company_id)
        c.ensure_open(asset)
        _capitalized(asset)
        previous = asset.book_value
        amount = c.money(previous - decimal.Decimal(recoverable_amount))
        if amount <= 0:
            raise ValueError("مبلغِ بازیافتنی کمتر از ارزشِ دفتری نیست؛ کاهشِ ارزشی وجود ندارد.")
        cat = _category(session, asset)
        c.require_accounts(cat, ("impairment_account_id", "accumulated_depreciation_account_id"))
        memo = f"کاهشِ ارزشِ دارایی {asset.asset_code}: {reason}"
        je_id = c.post_journal(session, company_id, user_id, date, memo, [
            c.JLine(cat.impairment_account_id, debit=amount, detail_ids=_dims(asset)),
            c.JLine(cat.accumulated_depreciation_account_id, credit=amount, detail_ids=(asset.cost_center_detail_account_id,))])
        ev = _event(session, asset, "IMPAIRMENT", date, user_id, amount=amount, previous_book_value=previous,
                    new_value=c.money(recoverable_amount), reason=reason, journal_entry_id=je_id,
                    idempotency_key=idempotency_key, approved_by_user_id=approved_by_user_id)
        c.record_txn(session, asset, c.primary_book(session, company_id).book_id, "IMPAIRMENT", date, impairment=amount,
                     description=memo, journal_entry_id=je_id, source_type="EVENT", source_id=ev.event_id, user_id=user_id)
        asset.status_code = "IMPAIRED"
        c.audit(session, company_id, user_id, asset_id, "IMPAIR", {"book_value": [str(previous), str(asset.book_value)],
                                                                   "reason": reason, "journal_entry_id": je_id})
        session.commit()
        session.refresh(ev)
        session.expunge(ev)
        return ev


# --- تجدیدِ ارزیابی ----------------------------------------------------------------------------------------
def revalue(company_id: int, user_id: int, asset_id: int, date: datetime.date, new_value: decimal.Decimal, reason: str,
            idempotency_key: str | None = None, approved_by_user_id: int | None = None) -> AssetEvent:
    """مدلِ تجدیدِ ارزیابی (روشِ حذفِ استهلاکِ انباشته): استهلاک و کاهشِ ارزشِ انباشته با بها تهاتر و بها به ارزشِ
    جدید می‌رسد. افزایش ← مازادِ تجدیدِ ارزیابی (حقوقِ مالکانه)؛ کاهش ← ابتدا از مازادِ قبلی، باقی‌مانده زیان.
    استهلاکِ بعدی از ارزشِ جدید و عمرِ باقی‌مانده محاسبه می‌شود."""
    new_value = c.money(new_value)
    if new_value < 0 or not (reason or "").strip():
        raise ValueError("ارزشِ جدید و علت الزامی است.")
    with new_session() as session:
        done = _done(session, company_id, idempotency_key)
        if done is not None:
            return done
        asset = c.lock_asset(session, asset_id, company_id)
        c.ensure_open(asset)
        _capitalized(asset)
        previous, accumulated = asset.book_value, asset.accumulated_depreciation + asset.accumulated_impairment
        diff = new_value - previous
        if diff == 0:
            raise ValueError("ارزشِ جدید با ارزشِ دفتری برابر است.")
        cat = _category(session, asset)
        c.require_accounts(cat, ("asset_account_id", "revaluation_account_id") + (
            ("accumulated_depreciation_account_id",) if accumulated else ()))
        dims = _dims(asset)
        lines = []
        if accumulated:
            lines += [c.JLine(cat.accumulated_depreciation_account_id, debit=accumulated, detail_ids=(asset.cost_center_detail_account_id,)),
                      c.JLine(cat.asset_account_id, credit=accumulated, detail_ids=dims)]
        surplus_change, loss = ZERO, ZERO
        if diff > 0:
            surplus_change = diff
            lines += [c.JLine(cat.asset_account_id, debit=diff, detail_ids=dims),
                      c.JLine(cat.revaluation_account_id, credit=diff)]
        else:
            from_surplus = min(-diff, max(asset.revaluation_surplus, ZERO))
            loss = -diff - from_surplus
            surplus_change = -from_surplus
            if loss:
                c.require_accounts(cat, ("impairment_account_id",))
            lines += [c.JLine(cat.revaluation_account_id, debit=from_surplus),
                      c.JLine(cat.impairment_account_id, debit=loss, detail_ids=dims),
                      c.JLine(cat.asset_account_id, credit=-diff, detail_ids=dims)]
        memo = f"تجدیدِ ارزیابیِ دارایی {asset.asset_code}: {reason}"
        je_id = c.post_journal(session, company_id, user_id, date, memo, lines)
        ev = _event(session, asset, "REVALUATION", date, user_id, amount=diff, previous_book_value=previous, new_value=new_value,
                    gain_loss=-loss if loss else None, reason=reason, journal_entry_id=je_id, idempotency_key=idempotency_key,
                    approved_by_user_id=approved_by_user_id, details={"surplus_change": str(surplus_change), "loss": str(loss)})
        c.record_txn(session, asset, c.primary_book(session, company_id).book_id, "REVALUATION", date, cost=diff - accumulated,
                     depreciation=-asset.accumulated_depreciation, impairment=-asset.accumulated_impairment,
                     revaluation=surplus_change, description=memo, journal_entry_id=je_id, source_type="EVENT",
                     source_id=ev.event_id, user_id=user_id)
        if asset.status_code in ("IMPAIRED", "FULLY_DEPRECIATED"):
            asset.status_code = "IN_SERVICE"
        c.audit(session, company_id, user_id, asset_id, "REVALUE", {"book_value": [str(previous), str(new_value)], "reason": reason,
                                                                    "journal_entry_id": je_id})
        session.commit()
        session.refresh(ev)
        session.expunge(ev)
        return ev


# --- فروش / اسقاط / اهدا / حذف ----------------------------------------------------------------------------
def dispose(company_id: int, user_id: int, asset_id: int, date: datetime.date, kind: str, proceeds: decimal.Decimal = ZERO,
            proceeds_account_id: int | None = None, counterparty_detail_account_id: int | None = None, reason: str | None = None,
            condition_note: str | None = None, idempotency_key: str | None = None,
            approved_by_user_id: int | None = None) -> AssetEvent:
    """بها، استهلاکِ انباشته، ارزشِ دفتری، مبلغِ دریافتی و سود/زیان خودکار؛ سند از موتورِ حسابداری.
    فروش: proceeds = مبلغِ فروش (بدهکارِ دریافتنی/بانک)؛ اسقاط: proceeds = ارزشِ ضایعات (اختیاری)."""
    if kind not in DISPOSAL_KINDS:
        raise ValueError("نوعِ واگذاری نامعتبر است.")
    proceeds = c.money(proceeds or 0)
    if proceeds < 0:
        raise ValueError("مبلغِ دریافتی نمی‌تواند منفی باشد.")
    if proceeds and proceeds_account_id is None:
        raise ValueError("حسابِ دریافتِ مبلغ (دریافتنی/بانک) مشخص نشده است.")
    if kind == "SALE" and proceeds <= 0:
        raise ValueError("مبلغِ فروش الزامی است.")
    status, txn_type, label = DISPOSAL_KINDS[kind]
    with new_session() as session:
        done = _done(session, company_id, idempotency_key)
        if done is not None:
            return done
        asset = c.lock_asset(session, asset_id, company_id)
        if asset.status_code in c.CLOSED_STATUSES:
            raise ValueError(f"دارایی «{asset.asset_code}» قبلاً {c.STATUS_LABELS[asset.status_code]} است.")
        if asset.status_code == "DRAFT":
            raise ValueError("داراییِ پیش‌نویس واگذارشدنی نیست.")
        active_children = session.scalar(select(func.count()).select_from(Asset).where(
            Asset.parent_asset_id == asset_id, Asset.status_code.not_in(c.CLOSED_STATUSES)))
        if active_children:
            raise ValueError("این دارایی جزءِ فعال دارد؛ ابتدا اجزا را واگذار یا جدا کنید.")
        gross, dep, imp = asset.gross_cost, asset.accumulated_depreciation, asset.accumulated_impairment
        nbv = asset.book_value
        gain = proceeds - nbv
        cat = _category(session, asset)
        needed = ["asset_account_id"]
        if dep + imp:
            needed.append("accumulated_depreciation_account_id")
        if gain > 0:
            needed.append("disposal_gain_account_id")
        elif gain < 0:
            needed.append("disposal_loss_account_id")
        c.require_accounts(cat, tuple(needed))
        dims = _dims(asset)
        memo = f"{label}ِ دارایی {asset.asset_code} -- {asset.name}" + (f": {reason}" if reason else "")
        lines = [c.JLine(cat.asset_account_id, credit=gross, detail_ids=dims)]
        if dep + imp:
            lines.append(c.JLine(cat.accumulated_depreciation_account_id, debit=dep + imp, detail_ids=(asset.cost_center_detail_account_id,)))
        if proceeds:
            lines.append(c.JLine(proceeds_account_id, debit=proceeds, detail_ids=(counterparty_detail_account_id,)))
        if gain > 0:
            lines.append(c.JLine(cat.disposal_gain_account_id, credit=gain, detail_ids=dims))
        elif gain < 0:
            lines.append(c.JLine(cat.disposal_loss_account_id, debit=-gain, detail_ids=dims))
        je_id = c.post_journal(session, company_id, user_id, date, memo, lines)
        ev = _event(session, asset, kind, date, user_id, amount=gross, proceeds=proceeds, previous_book_value=nbv, new_value=ZERO,
                    gain_loss=gain, reason=reason, condition_note=condition_note, offset_account_id=proceeds_account_id,
                    counterparty_detail_account_id=counterparty_detail_account_id, journal_entry_id=je_id,
                    idempotency_key=idempotency_key, approved_by_user_id=approved_by_user_id,
                    details={"cost": str(gross), "accumulated_depreciation": str(dep), "impairment": str(imp)})
        c.record_txn(session, asset, c.primary_book(session, company_id).book_id, txn_type, date, cost=-gross, depreciation=-dep,
                     impairment=-imp, description=memo, journal_entry_id=je_id, source_type="EVENT", source_id=ev.event_id,
                     user_id=user_id)
        asset.status_code = status
        c.audit(session, company_id, user_id, asset_id, kind, {"proceeds": str(proceeds), "book_value": str(nbv),
                                                               "gain_loss": str(gain), "journal_entry_id": je_id, "reason": reason})
        session.commit()
        session.refresh(ev)
        session.expunge(ev)
        return ev


def sell(company_id: int, user_id: int, asset_id: int, date: datetime.date, price: decimal.Decimal, receivable_account_id: int,
         customer_detail_account_id: int | None = None, reason: str | None = None, idempotency_key: str | None = None,
         approved_by_user_id: int | None = None) -> AssetEvent:
    return dispose(company_id, user_id, asset_id, date, "SALE", price, receivable_account_id, customer_detail_account_id, reason,
                   idempotency_key=idempotency_key, approved_by_user_id=approved_by_user_id)


def scrap(company_id: int, user_id: int, asset_id: int, date: datetime.date, reason: str, condition_note: str | None = None,
          scrap_value: decimal.Decimal = ZERO, scrap_value_account_id: int | None = None, idempotency_key: str | None = None,
          approved_by_user_id: int | None = None) -> AssetEvent:
    if not (reason or "").strip():
        raise ValueError("علتِ اسقاط الزامی است.")
    return dispose(company_id, user_id, asset_id, date, "SCRAP", scrap_value, scrap_value_account_id, None, reason,
                   condition_note, idempotency_key, approved_by_user_id)


# --- انتقالِ ارزش بینِ دو دارایی (تقسیم/ادغام/جزء) ----------------------------------------------------------
def _move_value(session, source: Asset, target: Asset, cost, dep, imp, date, user_id, out_type: str, in_type: str,
                memo: str, event_id: int) -> int | None:
    """بها/استهلاک/کاهشِ ارزش را از مبدأ به مقصد می‌برد؛ اگر حساب‌هایِ طبقه فرق کند سندِ جابه‌جایی می‌خورد."""
    book_id = c.primary_book(session, source.company_id).book_id
    je_id = None
    if source.category_id != target.category_id and (cost or dep or imp):
        s_cat, t_cat = _category(session, source), _category(session, target)
        c.require_accounts(t_cat, ("asset_account_id",) + (("accumulated_depreciation_account_id",) if dep + imp else ()))
        lines = [c.JLine(t_cat.asset_account_id, debit=cost, detail_ids=_dims(target)),
                 c.JLine(s_cat.asset_account_id, credit=cost, detail_ids=_dims(source))]
        if dep + imp:
            lines += [c.JLine(s_cat.accumulated_depreciation_account_id, debit=dep + imp),
                      c.JLine(t_cat.accumulated_depreciation_account_id, credit=dep + imp)]
        je_id = c.post_journal(session, source.company_id, user_id, date, memo, lines)
    c.record_txn(session, source, book_id, out_type, date, cost=-cost, depreciation=-dep, impairment=-imp, description=memo,
                 journal_entry_id=je_id, source_type="EVENT", source_id=event_id, user_id=user_id)
    c.record_txn(session, target, book_id, in_type, date, cost=cost, depreciation=dep, impairment=imp, description=memo,
                 journal_entry_id=je_id, source_type="EVENT", source_id=event_id, user_id=user_id)
    return je_id


def _share(total: decimal.Decimal, weights: list[decimal.Decimal]) -> list[decimal.Decimal]:
    """تقسیمِ total به نسبتِ weights با جمعِ دقیق (اختلافِ گردکردن رویِ آخرین سهم)."""
    s = sum(weights, ZERO)
    parts = [c.money(total * w / s) for w in weights[:-1]] if s else [ZERO] * (len(weights) - 1)
    return parts + [total - sum(parts, ZERO)]


def split(company_id: int, user_id: int, asset_id: int, date: datetime.date, parts: list[tuple[str, str, decimal.Decimal]],
          reason: str | None = None) -> list[int]:
    """تقسیمِ یک دارایی به چند دارایی: parts = [(کد، نام، بها)] -- جمعِ بهاها باید دقیقاً برابرِ بهایِ دارایی باشد.
    استهلاک/کاهشِ ارزش به نسبتِ بها تقسیم، عمرِ گذشته منتقل و داراییِ مبدأ «تقسیم‌شده» می‌شود (تاریخچه می‌ماند)."""
    if len(parts) < 2:
        raise ValueError("تقسیم حداقل به دو بخش لازم است.")
    with new_session() as session:
        source = c.lock_asset(session, asset_id, company_id)
        c.ensure_open(source)
        _capitalized(source)
        amounts = [c.money(p[2]) for p in parts]
        if any(a <= 0 for a in amounts) or sum(amounts, ZERO) != source.gross_cost:
            raise ValueError(f"جمعِ بهایِ بخش‌ها ({sum(amounts, ZERO)}) باید برابرِ بهایِ دارایی ({source.gross_cost}) باشد.")
        from peecha.services.fixed_assets import depreciation as fd

        months = fd.months_done(session, asset_id)
        deps = _share(source.accumulated_depreciation, amounts)
        imps = _share(source.accumulated_impairment, amounts)
        residuals = _share(source.residual_value or ZERO, amounts)
        units = source.units_consumed
        ev = _event(session, source, "SPLIT", date, user_id, amount=source.gross_cost, previous_book_value=source.book_value,
                    reason=reason, details={"parts": [[p[0], str(a)] for p, a in zip(parts, amounts)]})
        base = fa.fields_of(source)
        new_ids = []
        for (code, name, _amount), cost, dep, imp, res in zip(parts, amounts, deps, imps, residuals):
            child = fa.insert_asset(session, company_id, user_id, replace(base, asset_code=code, name=name, source_code="SPLIT",
                                                                          residual_value=res, barcode=None), status=source.status_code)
            for key in ("acquisition_date", "capitalization_date", "in_service_date", "depreciation_start_date"):
                setattr(child, key, getattr(source, key))
            child.depreciated_months_offset = months
            child.units_consumed = units
            child.purchase_price = c.money(source.purchase_price * cost / source.gross_cost) if source.gross_cost else ZERO
            _move_value(session, source, child, cost, dep, imp, date, user_id, "SPLIT_OUT", "SPLIT_IN",
                        f"تقسیمِ {source.asset_code} ← {code}", ev.event_id)
            new_ids.append(child.asset_id)
        source.status_code = "SPLIT"
        ev.details = {**ev.details, "new_asset_ids": new_ids}
        c.audit(session, company_id, user_id, asset_id, "SPLIT", {"new_asset_ids": new_ids, "reason": reason})
        session.commit()
        return new_ids


def merge(company_id: int, user_id: int, target_asset_id: int, source_asset_ids: list[int], date: datetime.date,
          reason: str | None = None) -> int:
    """ادغامِ چند دارایی در یک دارایی (مثلاً ماشین + تجهیزاتِ جانبی ← خطِ تولید)؛ مبدأها «ادغام‌شده» و تاریخچه حفظ."""
    if not source_asset_ids or target_asset_id in source_asset_ids:
        raise ValueError("دارایی‌هایِ مبدأ نامعتبر است.")
    with new_session() as session:
        ids = sorted({target_asset_id, *source_asset_ids})
        locked = {i: c.lock_asset(session, i, company_id) for i in ids}
        target = locked[target_asset_id]
        c.ensure_open(target)
        _capitalized(target)
        ev = _event(session, target, "MERGE", date, user_id, previous_book_value=target.book_value, reason=reason,
                    details={"sources": source_asset_ids})
        for sid in source_asset_ids:
            src = locked[sid]
            c.ensure_open(src)
            _capitalized(src)
            target.residual_value = c.money((target.residual_value or ZERO) + (src.residual_value or ZERO))
            _move_value(session, src, target, src.gross_cost, src.accumulated_depreciation, src.accumulated_impairment, date,
                        user_id, "MERGE_OUT", "MERGE_IN", f"ادغامِ {src.asset_code} ← {target.asset_code}", ev.event_id)
            src.status_code = "MERGED"
        ev.new_value = target.book_value
        c.audit(session, company_id, user_id, target_asset_id, "MERGE", {"sources": source_asset_ids, "reason": reason})
        session.commit()
        return ev.event_id


def carve_component(company_id: int, user_id: int, parent_asset_id: int, f: fa.AssetFields, cost: decimal.Decimal,
                    date: datetime.date) -> int:
    """جداکردنِ یک جزء (مثلاً موتورِ CNC) با عمر/روشِ مستقل از بهایِ داراییِ اصلی؛ استهلاکِ گذشته به نسبت منتقل می‌شود."""
    cost = c.money(cost)
    with new_session() as session:
        parent = c.lock_asset(session, parent_asset_id, company_id)
        c.ensure_open(parent)
        _capitalized(parent)
        if cost <= 0 or cost >= parent.gross_cost:
            raise ValueError("بهایِ جزء باید مثبت و کمتر از بهایِ داراییِ اصلی باشد.")
        ratio = cost / parent.gross_cost
        dep, imp = c.money(parent.accumulated_depreciation * ratio), c.money(parent.accumulated_impairment * ratio)
        from peecha.services.fixed_assets import depreciation as fd

        child = fa.insert_asset(session, company_id, user_id, replace(f, parent_asset_id=parent_asset_id, source_code="SPLIT"),
                                status=parent.status_code)
        for key in ("acquisition_date", "capitalization_date", "in_service_date", "depreciation_start_date",
                    "cost_center_detail_account_id", "location_id"):
            if getattr(child, key) is None:
                setattr(child, key, getattr(parent, key))
        child.depreciated_months_offset = fd.months_done(session, parent_asset_id)
        ev = _event(session, parent, "SPLIT", date, user_id, amount=cost, reason=f"جداکردنِ جزء {f.asset_code}",
                    details={"component": True})
        _move_value(session, parent, child, cost, dep, imp, date, user_id, "SPLIT_OUT", "SPLIT_IN",
                    f"جزءِ {f.asset_code} از {parent.asset_code}", ev.event_id)
        c.audit(session, company_id, user_id, parent_asset_id, "COMPONENT", {"component_id": child.asset_id, "cost": str(cost)})
        session.commit()
        return child.asset_id


def components(company_id: int, parent_asset_id: int) -> list[fa.AssetRow]:
    return [r for r in fa.list_assets(company_id) if r.parent_asset_id == parent_asset_id]


# --- دارایی در جریانِ تکمیل (CIP) ------------------------------------------------------------------------------
def create_cip(company_id: int, user_id: int | None, code: str, name: str, category_id: int, start_date: datetime.date,
               cost_center_detail_account_id: int | None = None, project_detail_account_id: int | None = None,
               notes: str | None = None) -> int:
    with new_session() as session:
        if session.scalar(select(CipProject.cip_id).where(CipProject.company_id == company_id, CipProject.code == code.strip())):
            raise ValueError("کدِ پروژهٔ در جریانِ تکمیل تکراری است.")
        cat = session.get(AssetCategory, category_id)
        if cat is None or cat.company_id != company_id:
            raise ValueError("طبقهٔ دارایی نامعتبر است.")
        row = CipProject(company_id=company_id, code=code.strip(), name=name.strip(), category_id=category_id, start_date=start_date,
                         status_code="OPEN", cost_center_detail_account_id=cost_center_detail_account_id,
                         project_detail_account_id=project_detail_account_id, notes=notes, created_by_user_id=user_id)
        session.add(row)
        session.flush()
        c.audit(session, company_id, user_id, row.cip_id, "CREATE", {"code": row.code, "name": row.name}, entity_type="CipProject")
        session.commit()
        return row.cip_id


def _open_cip(session, company_id: int, cip_id: int) -> CipProject:
    cip = session.scalar(select(CipProject).where(CipProject.cip_id == cip_id).with_for_update())
    if cip is None or cip.company_id != company_id:
        raise ValueError("پروژهٔ در جریانِ تکمیل نامعتبر است.")
    if cip.status_code != "OPEN":
        raise ValueError("این پروژه بسته شده است.")
    return cip


def add_cip_cost(company_id: int, user_id: int, cip_id: int, date: datetime.date, cost_type: str, amount: decimal.Decimal,
                 offset_account_id: int, offset_detail_account_id: int | None = None, description: str | None = None) -> int:
    """هزینهٔ سرمایه‌ای (دستمزد، نصب، حمل، مهندسی، ...): بدهکارِ حسابِ CIP، بستانکارِ حسابِ طرفِ مقابل -- اتمیک."""
    amount = c.money(amount)
    if cost_type not in CIP_COST_TYPES or amount <= 0:
        raise ValueError("هزینهٔ نامعتبر است.")
    with new_session() as session:
        cip = _open_cip(session, company_id, cip_id)
        cat = session.get(AssetCategory, cip.category_id)
        c.require_accounts(cat, ("cip_account_id",))
        memo = f"{CIP_COST_TYPES[cost_type]} -- دارایی در جریانِ تکمیل {cip.code}" + (f": {description}" if description else "")
        je_id = c.post_journal(session, company_id, user_id, date, memo, [
            c.JLine(cat.cip_account_id, debit=amount, detail_ids=(cip.cost_center_detail_account_id, cip.project_detail_account_id)),
            c.JLine(offset_account_id, credit=amount, detail_ids=(offset_detail_account_id,))])
        row = CipCost(cip_id=cip_id, cost_date=date, cost_type=cost_type, amount=amount, description=description,
                      offset_account_id=offset_account_id, offset_detail_account_id=offset_detail_account_id,
                      journal_entry_id=je_id, created_by_user_id=user_id)
        session.add(row)
        session.flush()
        c.audit(session, company_id, user_id, cip_id, "COST", {"type": cost_type, "amount": str(amount), "journal_entry_id": je_id},
                entity_type="CipProject")
        session.commit()
        return row.cip_cost_id


def add_cip_material(company_id: int, user_id: int, cip_id: int, date: datetime.date, item_id: int, warehouse_id: int,
                     quantity: decimal.Decimal, uom_id: int) -> int:
    """مصرفِ مواد در ساخت: خروج از انبار فقط با موتورِ انبار، سپس بهایِ واقعیِ خروج به حسابِ CIP."""
    from peecha.db.models.inventory import StockDocumentLine, StockLedger
    from peecha.services import inventory_documents as inv_docs
    from peecha.services import inventory_engine

    with new_session() as session:
        cip = _open_cip(session, company_id, cip_id)
        c.require_accounts(session.get(AssetCategory, cip.category_id), ("cip_account_id",))
        code = cip.code
    loss_account = inventory_engine.get_account_mapping(company_id, "INVENTORY_ADJUSTMENT_LOSS")
    if loss_account is None:
        raise ValueError("حسابِ «کسریِ انبار» در تنظیماتِ انبار مشخص نشده است.")
    doc = inv_docs.create_stock_document(company_id, user_id, "ADJUSTMENT", date, inv_docs.DocumentHeaderFields(
        source_warehouse_id=warehouse_id, reference_no=f"CIP-{cip_id}", description=f"مصرف در دارایی در جریانِ تکمیل {code}"))
    inv_docs.add_line(doc, company_id, inv_docs.LineFields(item_id=item_id, uom_id=uom_id, quantity=decimal.Decimal(quantity),
                                                           quantity_base=decimal.Decimal(quantity), unit_cost=None,
                                                           reason_code_id=fa._fa_reason_code(company_id)))
    inv_docs.confirm_stock_document(doc, company_id)
    inv_docs.post_stock_document(doc, company_id, user_id)
    with new_session() as session:
        issued = c.money(session.scalar(select(func.coalesce(func.sum(StockLedger.quantity_base * StockLedger.unit_cost), 0))
                                        .join(StockDocumentLine, StockDocumentLine.line_id == StockLedger.stock_document_line_id)
                                        .where(StockDocumentLine.stock_document_id == doc, StockLedger.movement_direction == "OUT")))
    cost_id = add_cip_cost(company_id, user_id, cip_id, date, "MATERIAL", issued, loss_account,
                           description=f"مواد از انبار (سندِ انبار {doc})")
    with new_session() as session:
        session.get(CipCost, cost_id).stock_document_id = doc
        session.commit()
    return cost_id


def cip_total(session, cip_id: int) -> decimal.Decimal:
    return decimal.Decimal(session.scalar(select(func.coalesce(func.sum(CipCost.amount), 0)).where(CipCost.cip_id == cip_id)) or 0)


def capitalize_cip(company_id: int, user_id: int, cip_id: int, date: datetime.date, f: fa.AssetFields,
                   in_service_date: datetime.date | None = None) -> int:
    """CIP ← دارایی: پروژه بسته، دارایی با جمعِ بهایِ سرمایه‌ای ساخته (بدهکارِ دارایی/بستانکارِ CIP) و برنامهٔ استهلاک
    فعال می‌شود -- همه در یک تراکنش."""
    with new_session() as session:
        cip = _open_cip(session, company_id, cip_id)
        total = cip_total(session, cip_id)
        if total <= 0:
            raise ValueError("هیچ هزینه‌ای برایِ این پروژه ثبت نشده است.")
        cat = session.get(AssetCategory, f.category_id or cip.category_id)
        c.require_accounts(cat, ("asset_account_id",))
        c.require_accounts(session.get(AssetCategory, cip.category_id), ("cip_account_id",))
        asset = fa.insert_asset(session, company_id, user_id, replace(
            f, category_id=cat.category_id, source_code="CONSTRUCTION",
            cost_center_detail_account_id=f.cost_center_detail_account_id or cip.cost_center_detail_account_id,
            project_detail_account_id=f.project_detail_account_id or cip.project_detail_account_id), status="UNDER_CONSTRUCTION")
        memo = f"سرمایه‌ای‌شدنِ دارایی در جریانِ تکمیل {cip.code} ← {asset.asset_code}"
        cip_cat = session.get(AssetCategory, cip.category_id)
        je_id = c.post_journal(session, company_id, user_id, date, memo, [
            c.JLine(cat.asset_account_id, debit=total, detail_ids=_dims(asset)),
            c.JLine(cip_cat.cip_account_id, credit=total, detail_ids=(cip.cost_center_detail_account_id, cip.project_detail_account_id))])
        c.record_txn(session, asset, c.primary_book(session, company_id).book_id, "ACQUISITION", date, cost=total, description=memo,
                     journal_entry_id=je_id, source_type="CIP", source_id=cip_id, user_id=user_id)
        asset.acquisition_date = asset.acquisition_date or date
        asset.purchase_price = total
        cip.status_code, cip.capitalized_asset_id, cip.capitalized_at, cip.journal_entry_id = "CAPITALIZED", asset.asset_id, date, je_id
        c.audit(session, company_id, user_id, cip_id, "CAPITALIZE", {"asset_id": asset.asset_id, "total": str(total),
                                                                     "journal_entry_id": je_id}, entity_type="CipProject")
        session.commit()
        asset_id = asset.asset_id
    fa.capitalize(company_id, user_id, asset_id, date, in_service_date=in_service_date)
    return asset_id


def list_cip(company_id: int) -> list:
    from types import SimpleNamespace

    with new_session() as session:
        rows = list(session.scalars(select(CipProject).where(CipProject.company_id == company_id).order_by(CipProject.code)))
        return [SimpleNamespace(cip_id=r.cip_id, code=r.code, name=r.name, status=r.status_code, start_date=r.start_date,
                                total=cip_total(session, r.cip_id), category_id=r.category_id,
                                capitalized_asset_id=r.capitalized_asset_id) for r in rows]
