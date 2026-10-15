"""R307 — پایش انقضا (کلید WMS_EXPIRY_ALERTS).

بچ‌های نزدیک به انقضا و منقضی هر محل از inv.lot_movements خوانده می‌شوند (بیرون از انبار ضایعات/قرنطینه).
برای کالای منقضی فقط سند پیش‌نویس انتقال ساخته می‌شود؛ ثبتش با خود کاربر است (هیچ اصلاح خودکاری نیست).
"""

from __future__ import annotations

import datetime
import decimal
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.inventory import Batch, BinLocation, Item, LotMovement, StockDocument, Warehouse
from peecha.services import stock_controls

_ZERO = decimal.Decimal(0)
_REFERENCE = "EXPIRED-{}"


def lots(company_id: int, until: datetime.date, warehouse_id: int | None = None) -> list[SimpleNamespace]:
    """بچ‌های موجودی که تا تاریخ until (شامل) منقضی می‌شوند یا شده‌اند، قدیمی‌ترین انقضا اول."""
    today = datetime.date.today()
    with new_session() as session:
        q = (select(LotMovement.warehouse_id, LotMovement.bin_location_id, LotMovement.item_id, Batch.batch_id, Batch.batch_no,
                    Batch.expiry_date, func.sum(LotMovement.quantity_base))
             .join(Batch, Batch.batch_id == LotMovement.batch_id)
             .join(Warehouse, Warehouse.warehouse_id == LotMovement.warehouse_id)
             .where(LotMovement.company_id == company_id, Batch.expiry_date.is_not(None), Batch.expiry_date <= until,
                    Warehouse.warehouse_type_code.not_in(stock_controls.DISPOSAL_WAREHOUSE_TYPES))
             .group_by(LotMovement.warehouse_id, LotMovement.bin_location_id, LotMovement.item_id, Batch.batch_id, Batch.batch_no,
                       Batch.expiry_date))
        if warehouse_id is not None:
            q = q.where(LotMovement.warehouse_id == warehouse_id)
        rows = [r for r in session.execute(q).all() if r[6] and r[6] > 0]
        items = {i.item_id: i for i in session.scalars(select(Item).where(Item.item_id.in_({r[2] for r in rows} or {-1})))}
        names = dict(session.execute(select(DetailAccount.detail_account_id, DetailAccount.code + " — " + func.coalesce(DetailAccount.name, ""))
                                     .where(DetailAccount.detail_account_id.in_({i.item_detail_account_id for i in items.values()} or {-1}))).all())
        bins = dict(session.execute(select(BinLocation.bin_location_id, func.coalesce(BinLocation.location_code, BinLocation.code)).where(
            BinLocation.bin_location_id.in_({r[1] for r in rows if r[1]} or {-1}))).all())
        whs = dict(session.execute(select(Warehouse.warehouse_id, Warehouse.name).where(
            Warehouse.warehouse_id.in_({r[0] for r in rows} or {-1}))).all())
    out = [SimpleNamespace(warehouse_id=w, warehouse_name=whs.get(w, ""), bin_location_id=b, bin_code=bins.get(b, ""), item_id=i,
                           item_label=names.get(items[i].item_detail_account_id, ""), base_uom_id=items[i].base_uom_id,
                           batch_id=bid, batch_no=bno, expiry_date=exp, quantity=decimal.Decimal(q), days_left=(exp - today).days,
                           expired=exp < today)
           for w, b, i, bid, bno, exp, q in rows]
    return sorted(out, key=lambda r: (r.expiry_date, r.warehouse_name, r.item_label, r.batch_no))


def near_expiry(company_id: int, warehouse_id: int | None = None) -> list[SimpleNamespace]:
    until = datetime.date.today() + datetime.timedelta(days=stock_controls.expiry_alert_days(company_id))
    return lots(company_id, until, warehouse_id)


def disposal_target(session, company_id: int, warehouse_id: int) -> Warehouse | None:
    """انبار قرنطینهٔ پیش‌فرض همین انبار، وگرنه نخستین انبار ضایعات/قرنطینهٔ فعال."""
    source = session.get(Warehouse, warehouse_id)
    if source is not None and source.default_quarantine_warehouse_id:
        target = session.get(Warehouse, source.default_quarantine_warehouse_id)
        if target is not None and target.warehouse_type_code in stock_controls.DISPOSAL_WAREHOUSE_TYPES:
            return target
    return session.scalars(select(Warehouse).where(
        Warehouse.company_id == company_id, Warehouse.is_active.is_(True),
        Warehouse.warehouse_type_code.in_(stock_controls.DISPOSAL_WAREHOUSE_TYPES))
        .order_by(Warehouse.warehouse_type_code.desc(), Warehouse.code)).first()


def open_disposal_draft(company_id: int, warehouse_id: int) -> int | None:
    with new_session() as session:
        return session.scalar(select(StockDocument.stock_document_id).where(
            StockDocument.company_id == company_id, StockDocument.document_type_code == "TRANSFER",
            StockDocument.source_warehouse_id == warehouse_id, StockDocument.reference_no == _REFERENCE.format(warehouse_id),
            StockDocument.status_code.in_(("DRAFT", "CONFIRMED"))))


def create_disposal_draft(company_id: int, user_id: int, warehouse_id: int, target_warehouse_id: int | None = None) -> int:
    """سند پیش‌نویس انتقال همهٔ بچ‌های منقضی یک انبار به انبار ضایعات/قرنطینه (اگر پیش‌نویس ثبت‌نشده‌ای هست همان)."""
    from peecha.services import inventory_documents as inv_docs
    from peecha.services import lot_tracking

    existing = open_disposal_draft(company_id, warehouse_id)
    if existing is not None:
        return existing
    expired = [r for r in lots(company_id, datetime.date.today() - datetime.timedelta(days=1), warehouse_id)]
    if not expired:
        raise ValueError("در این انبار کالای منقضی نیست.")
    with new_session() as session:
        target = session.get(Warehouse, target_warehouse_id) if target_warehouse_id else disposal_target(session, company_id, warehouse_id)
        if target is None or target.company_id != company_id or target.warehouse_type_code not in stock_controls.DISPOSAL_WAREHOUSE_TYPES:
            raise ValueError("یک انبار از نوع ضایعات یا قرنطینه تعریف کنید یا برای این انبار انبار قرنطینهٔ پیش‌فرض بگذارید.")
        target_id = target.warehouse_id
    doc_id = inv_docs.create_stock_document(company_id, user_id, "TRANSFER", datetime.date.today(), inv_docs.DocumentHeaderFields(
        source_warehouse_id=warehouse_id, destination_warehouse_id=target_id, reference_no=_REFERENCE.format(warehouse_id),
        description="انتقال کالای منقضی به انبار ضایعات/قرنطینه (پیشنهاد پایش انقضا)"))
    for r in expired:
        line_id = inv_docs.add_line(doc_id, company_id, inv_docs.LineFields(
            item_id=r.item_id, uom_id=r.base_uom_id, quantity=r.quantity, quantity_base=r.quantity, conversion_factor=decimal.Decimal(1),
            bin_location_id=r.bin_location_id, description=f"بچ {r.batch_no} — منقضی"))
        lot_tracking.set_line_tracking(company_id, [lot_tracking.TrackingEntry(r.quantity, batch_no=r.batch_no, expiry_date=r.expiry_date)],
                                       stock_line_id=line_id)
    return doc_id


def summary_by_warehouse(company_id: int) -> dict[int, SimpleNamespace]:
    """کارتابل: برای هر انبار تعداد بچ منقضی و نزدیک به انقضا."""
    out: dict[int, SimpleNamespace] = {}
    for r in near_expiry(company_id):
        s = out.setdefault(r.warehouse_id, SimpleNamespace(name=r.warehouse_name, expired=0, near=0, first=r.expiry_date))
        if r.expired:
            s.expired += 1
        else:
            s.near += 1
    return out
