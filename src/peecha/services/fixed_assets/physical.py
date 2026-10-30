"""شمارش فیزیکی دارایی (دستی/بارکد/QR/موبایل)، گارانتی و بیمه، هشدارها — R264."""

from __future__ import annotations

import datetime
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.fixed_assets import (
    Asset, AssetEvent, AssetInsurance, AssetLocation, AssetWarranty, PhysicalCount, PhysicalCountItem,
)
from peecha.services.fixed_assets import assets as fa
from peecha.services.fixed_assets import common as c

RESULT_LABELS = {"PENDING": "شمرده‌نشده", "FOUND": "یافت شد", "MISSING": "مفقود", "MOVED": "جابه‌جاشده", "DAMAGED": "آسیب‌دیده",
                 "WRONG_LOCATION": "محل نادرست", "WRONG_CUSTODIAN": "تحویل‌گیرندهٔ نادرست", "UNEXPECTED": "خارج از فهرست"}


def _subtree(session, company_id: int, location_id: int) -> set[int]:
    rows = session.execute(select(AssetLocation.location_id, AssetLocation.parent_location_id)
                           .where(AssetLocation.company_id == company_id)).all()
    children: dict[int, list[int]] = {}
    for lid, parent in rows:
        children.setdefault(parent, []).append(lid)
    out, stack = set(), [location_id]
    while stack:
        node = stack.pop()
        if node not in out:
            out.add(node)
            stack.extend(children.get(node, []))
    return out


def create_count(company_id: int, user_id: int | None, code: str, count_date: datetime.date, location_id: int | None = None,
                 notes: str | None = None) -> int:
    """شمارش برای یک محل (با زیرمحل‌ها) یا کل دارایی‌های فعال؛ فهرست مورد انتظار از شناسنامه‌ها."""
    with new_session() as session:
        if session.scalar(select(PhysicalCount.count_id).where(PhysicalCount.company_id == company_id,
                                                               PhysicalCount.code == code.strip())):
            raise ValueError("کد شمارش تکراری است.")
        count = PhysicalCount(company_id=company_id, code=code.strip(), count_date=count_date, location_id=location_id,
                              status_code="OPEN", notes=notes, created_by_user_id=user_id)
        session.add(count)
        session.flush()
        q = select(Asset).where(Asset.company_id == company_id, Asset.status_code.not_in(c.CLOSED_STATUSES | {"DRAFT"}))
        if location_id is not None:
            q = q.where(Asset.location_id.in_(_subtree(session, company_id, location_id)))
        for a in session.scalars(q):
            session.add(PhysicalCountItem(count_id=count.count_id, asset_id=a.asset_id, expected_location_id=a.location_id,
                                          expected_custodian_employee_id=a.custodian_employee_id, result_code="PENDING"))
        c.audit(session, company_id, user_id, count.count_id, "CREATE", {"code": code, "location_id": location_id},
                entity_type="AssetPhysicalCount")
        session.commit()
        return count.count_id


def _open(session, company_id: int, count_id: int) -> PhysicalCount:
    count = session.get(PhysicalCount, count_id)
    if count is None or count.company_id != company_id:
        raise ValueError("شمارش نامعتبر است.")
    if count.status_code != "OPEN":
        raise ValueError("این شمارش بسته شده است.")
    return count


def scan(company_id: int, count_id: int, code: str, found_location_id: int | None = None,
         found_custodian_employee_id: int | None = None, damaged: bool = False, method: str = "QR",
         note: str | None = None) -> SimpleNamespace:
    """ثبت یافتن دارایی با کد/بارکد/QR؛ نتیجه: یافت شد/محل نادرست/تحویل‌گیرندهٔ نادرست/آسیب‌دیده/جابه‌جاشده."""
    asset = fa.find_by_code(company_id, code)
    if asset is None:
        raise ValueError(f"دارایی با کد «{code}» یافت نشد.")
    with new_session() as session:
        count = _open(session, company_id, count_id)
        found_location_id = found_location_id or count.location_id
        item = session.scalar(select(PhysicalCountItem).where(PhysicalCountItem.count_id == count_id,
                                                              PhysicalCountItem.asset_id == asset.asset_id))
        if item is None:  # دارایی از جایِ دیگری اینجا پیدا شده
            item = PhysicalCountItem(count_id=count_id, asset_id=asset.asset_id, expected_location_id=asset.location_id,
                                     expected_custodian_employee_id=asset.custodian_employee_id)
            session.add(item)
            result = "MOVED"
        elif damaged:
            result = "DAMAGED"
        elif found_location_id and item.expected_location_id and found_location_id != item.expected_location_id:
            result = "WRONG_LOCATION"
        elif (found_custodian_employee_id and item.expected_custodian_employee_id
              and found_custodian_employee_id != item.expected_custodian_employee_id):
            result = "WRONG_CUSTODIAN"
        else:
            result = "FOUND"
        item.found_location_id, item.found_custodian_employee_id = found_location_id, found_custodian_employee_id
        item.result_code, item.is_damaged, item.scan_method = result, damaged, method
        item.scanned_at, item.note = datetime.datetime.now(), note
        session.commit()
        return SimpleNamespace(asset_id=asset.asset_id, asset_code=asset.asset_code, name=asset.name, result=result,
                               label=RESULT_LABELS[result])


def close_count(company_id: int, user_id: int, count_id: int, apply_moves: bool = False) -> dict[str, int]:
    """بستن شمارش: شمرده‌نشده‌ها «مفقود»؛ با apply_moves، محل یافت‌شده با «انتقال» در شناسنامه ثبت می‌شود."""
    with new_session() as session:
        count = _open(session, company_id, count_id)
        moves = []
        for item in session.scalars(select(PhysicalCountItem).where(PhysicalCountItem.count_id == count_id)):
            if item.result_code == "PENDING":
                item.result_code = "MISSING"
            elif item.result_code in ("WRONG_LOCATION", "MOVED") and item.found_location_id:
                moves.append((item.asset_id, item.found_location_id))
        count.status_code, count.closed_at = "CLOSED", datetime.datetime.now()
        summary = dict(session.execute(select(PhysicalCountItem.result_code, func.count()).where(
            PhysicalCountItem.count_id == count_id).group_by(PhysicalCountItem.result_code)).all())
        c.audit(session, company_id, user_id, count_id, "CLOSE", {"summary": summary, "apply_moves": apply_moves},
                entity_type="AssetPhysicalCount")
        session.commit()
    if apply_moves:
        for asset_id, location_id in moves:
            fa.transfer(company_id, user_id, asset_id, datetime.date.today(), reason=f"نتیجهٔ شمارش فیزیکی #{count_id}",
                        location_id=location_id, idempotency_key=f"COUNT-{count_id}-{asset_id}")
    return summary


def count_items(company_id: int, count_id: int, discrepancies_only: bool = False) -> list[SimpleNamespace]:
    with new_session() as session:
        count = session.get(PhysicalCount, count_id)
        if count is None or count.company_id != company_id:
            raise ValueError("شمارش نامعتبر است.")
        q = (select(PhysicalCountItem, Asset.asset_code, Asset.name).join(Asset, Asset.asset_id == PhysicalCountItem.asset_id)
             .where(PhysicalCountItem.count_id == count_id))
        if discrepancies_only:
            q = q.where(PhysicalCountItem.result_code.not_in(("FOUND",)))
        return [SimpleNamespace(asset_id=i.asset_id, asset_code=code, name=name, result=i.result_code,
                                label=RESULT_LABELS[i.result_code], expected_location=c.location_path(session, i.expected_location_id),
                                found_location=c.location_path(session, i.found_location_id), damaged=i.is_damaged,
                                scanned_at=i.scanned_at, method=i.scan_method, note=i.note)
                for i, code, name in session.execute(q.order_by(Asset.asset_code)).all()]


def list_counts(company_id: int) -> list[PhysicalCount]:
    with new_session() as session:
        rows = list(session.scalars(select(PhysicalCount).where(PhysicalCount.company_id == company_id)
                                    .order_by(PhysicalCount.count_date.desc(), PhysicalCount.count_id.desc())))
        for r in rows:
            session.expunge(r)
        return rows


# --- گارانتی و بیمه --------------------------------------------------------------------------------------
def add_warranty(company_id: int, asset_id: int, start_date: datetime.date, end_date: datetime.date, warranty_type: str | None = None,
                 supplier_detail_account_id: int | None = None, contract_no: str | None = None, note: str | None = None) -> int:
    if end_date < start_date:
        raise ValueError("پایان گارانتی پیش از شروع آن است.")
    fa.get_asset(company_id, asset_id)
    with new_session() as session:
        row = AssetWarranty(asset_id=asset_id, warranty_type=warranty_type, supplier_detail_account_id=supplier_detail_account_id,
                            contract_no=contract_no, start_date=start_date, end_date=end_date, note=note)
        session.add(row)
        session.commit()
        return row.warranty_id


def add_insurance(company_id: int, asset_id: int, insurer_name: str, start_date: datetime.date, end_date: datetime.date,
                  policy_no: str | None = None, premium=None, coverage: str | None = None, insured_value=None) -> int:
    if end_date < start_date:
        raise ValueError("پایان بیمه پیش از شروع آن است.")
    fa.get_asset(company_id, asset_id)
    with new_session() as session:
        row = AssetInsurance(asset_id=asset_id, insurer_name=insurer_name, policy_no=policy_no, start_date=start_date,
                             end_date=end_date, premium=premium, coverage=coverage, insured_value=insured_value)
        session.add(row)
        session.commit()
        return row.insurance_id


def warranties(asset_id: int) -> list[AssetWarranty]:
    with new_session() as session:
        rows = list(session.scalars(select(AssetWarranty).where(AssetWarranty.asset_id == asset_id).order_by(AssetWarranty.end_date)))
        for r in rows:
            session.expunge(r)
        return rows


def insurances(asset_id: int) -> list[AssetInsurance]:
    with new_session() as session:
        rows = list(session.scalars(select(AssetInsurance).where(AssetInsurance.asset_id == asset_id).order_by(AssetInsurance.end_date)))
        for r in rows:
            session.expunge(r)
        return rows


def _expiry_level(end: datetime.date, today: datetime.date) -> str | None:
    days = (end - today).days
    if days < 0:
        return "EXPIRED"
    if days <= 7:
        return "DAYS_7"
    if days <= 30:
        return "DAYS_30"
    return None


EXPIRY_LABELS = {"EXPIRED": "منقضی شده", "DAYS_7": "۷ روز مانده", "DAYS_30": "۳۰ روز مانده"}


def alerts(company_id: int, today: datetime.date | None = None) -> list[SimpleNamespace]:
    """هشدارها: انقضای گارانتی/بیمه (۳۰/۷ روز/منقضی)، پایان استهلاک، مفقودی، کاهش ارزش، در انتظار تایید."""
    from peecha.services.fixed_assets import depreciation as fd

    today = today or datetime.date.today()
    out = []
    with new_session() as session:
        open_assets = select(Asset.asset_id).where(Asset.company_id == company_id, Asset.status_code.not_in(c.CLOSED_STATUSES))
        latest_warranty = (select(AssetWarranty.asset_id, func.max(AssetWarranty.end_date).label("end"))
                           .where(AssetWarranty.asset_id.in_(open_assets)).group_by(AssetWarranty.asset_id).subquery())
        for asset_id, end in session.execute(select(latest_warranty.c.asset_id, latest_warranty.c.end)).all():
            level = _expiry_level(end, today)
            if level:
                out.append(SimpleNamespace(kind="WARRANTY", level=level, asset_id=asset_id, date=end,
                                           text=f"گارانتی: {EXPIRY_LABELS[level]}"))
        latest_ins = (select(AssetInsurance.asset_id, func.max(AssetInsurance.end_date).label("end"))
                      .where(AssetInsurance.asset_id.in_(open_assets)).group_by(AssetInsurance.asset_id).subquery())
        for asset_id, end in session.execute(select(latest_ins.c.asset_id, latest_ins.c.end)).all():
            level = _expiry_level(end, today)
            if level:
                out.append(SimpleNamespace(kind="INSURANCE", level=level, asset_id=asset_id, date=end,
                                           text=f"بیمه: {EXPIRY_LABELS[level]}"))
        for a in session.scalars(select(Asset).where(Asset.company_id == company_id, Asset.status_code.in_(("IMPAIRED",)))):
            out.append(SimpleNamespace(kind="IMPAIRMENT", level="INFO", asset_id=a.asset_id, date=None, text="کاهش ارزش"))
        last_count = session.scalar(select(PhysicalCount.count_id).where(PhysicalCount.company_id == company_id,
                                                                        PhysicalCount.status_code == "CLOSED")
                                    .order_by(PhysicalCount.closed_at.desc()).limit(1))
        if last_count:
            for (aid,) in session.execute(select(PhysicalCountItem.asset_id).where(PhysicalCountItem.count_id == last_count,
                                                                                    PhysicalCountItem.result_code == "MISSING")):
                out.append(SimpleNamespace(kind="MISSING", level="DANGER", asset_id=aid, date=None, text="مفقود در آخرین شمارش"))
        for ev in session.scalars(select(AssetEvent).where(AssetEvent.company_id == company_id,
                                                           AssetEvent.status_code == "PENDING_APPROVAL")):
            out.append(SimpleNamespace(kind="APPROVAL", level="INFO", asset_id=ev.asset_id, date=ev.event_date,
                                       text="در انتظار تایید", event_id=ev.event_id))
        depreciating = list(session.scalars(select(Asset.asset_id).where(
            Asset.company_id == company_id, Asset.status_code.in_(c.DEPRECIABLE_STATUSES), Asset.depreciation_method != "NONE")))
    for asset_id in depreciating:
        left = fd.forecast(company_id, asset_id, months=4)
        if left and len(left) <= 3 and left[-1].book_value <= 0:
            out.append(SimpleNamespace(kind="DEPRECIATION_END", level="INFO", asset_id=asset_id, date=None,
                                       text=f"پایان استهلاک تا {len(left)} ماه دیگر"))
    return out
