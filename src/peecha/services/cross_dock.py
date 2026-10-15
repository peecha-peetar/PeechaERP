"""R309 — ارسال مستقیم از رسید (Cross-dock؛ کلید WMS_CROSS_DOCK).

اگر کالای رسیدهٔ تازه را سفارش فروش تاییدشده‌ای در همان انبار منتظر است (رزرو نشده و خارج نشده)، همان موجودی محل
رسید برای آن سفارش رزرو و وظیفهٔ برداشت از همان محل ساخته می‌شود؛ جانمایی فقط برای باقی آزاد ساخته می‌شود.
هیچ سند انبار تازه‌ای ثبت نمی‌شود — همان رزرو سفارش فروش و وظیفهٔ برداشت.
"""

from __future__ import annotations

import datetime
import decimal
from types import SimpleNamespace

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.inventory import Item, StockBalance, StockDocument, StockDocumentLine, StockLedger, Warehouse, WarehouseTask
from peecha.services import audit as audit_service
from peecha.services import stock_reservations

_ZERO = decimal.Decimal(0)
_ORDER_STATUSES = ("CONFIRMED", "APPROVED")


def _waiting_order_lines(session, company_id: int, warehouse_id: int, item_id: int) -> list[tuple]:
    """[(ردیف سفارش، سند، نیاز به واحد پایه)] — قدیمی‌ترین سفارش اول."""
    from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine

    rows = session.execute(
        select(CommercialDocumentLine, CommercialDocument)
        .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
        .where(CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "SALES_ORDER",
               CommercialDocument.status_code.in_(_ORDER_STATUSES), CommercialDocumentLine.item_id == item_id)
        .order_by(CommercialDocument.document_date, CommercialDocument.document_id, CommercialDocumentLine.line_no)).all()
    out = []
    for ln, doc in rows:
        if (ln.warehouse_id or doc.warehouse_id) != warehouse_id or not ln.quantity:
            continue
        factor = decimal.Decimal(ln.quantity_base) / decimal.Decimal(ln.quantity)
        issued = stock_reservations._issued_for_order_line(session, ln.line_id) * factor
        need = decimal.Decimal(ln.quantity_base) - issued - stock_reservations.order_line_reserved(session, ln.line_id)
        if need > 0:
            out.append((ln, doc, need))
    return out


def _receipt_bins(session, line_id: int) -> list[tuple[int, decimal.Decimal]]:
    """محل(های) ورود ردیف رسید و موجودی آزاد فعلی همان محل."""
    out = []
    for bin_id, item_id, warehouse_id in session.execute(
            select(StockLedger.bin_location_id, StockLedger.item_id, StockLedger.warehouse_id)
            .where(StockLedger.stock_document_line_id == line_id, StockLedger.movement_direction == "IN").distinct()).all():
        bal = session.scalar(select(StockBalance).where(
            StockBalance.item_id == item_id, StockBalance.warehouse_id == warehouse_id, StockBalance.bin_location_id == bin_id,
            StockBalance.batch_id.is_(None)))
        free = decimal.Decimal(bal.quantity_on_hand) - decimal.Decimal(bal.quantity_reserved or 0) if bal is not None else _ZERO
        if free > 0:
            out.append((bin_id, free))
    return out


def opportunities(company_id: int, warehouse_id: int | None = None, days: int = 7) -> list[SimpleNamespace]:
    """ردیف‌های رسید اخیر که سفارش فروش منتظر همان کالا دارند."""
    from peecha.services import quality_control

    since = datetime.date.today() - datetime.timedelta(days=days)
    out = []
    with new_session() as session:
        q = (select(StockDocumentLine, StockDocument)
             .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
             .where(StockDocument.company_id == company_id, StockDocument.document_type_code == "RECEIPT",
                    StockDocument.status_code == "POSTED", StockDocument.document_date >= since)
             .order_by(StockDocument.posted_at, StockDocumentLine.line_no))
        if warehouse_id is not None:
            q = q.where(StockDocument.destination_warehouse_id == warehouse_id)
        rows = session.execute(q).all()
        held = quality_control.waiting_line_ids(session, [ln.line_id for ln, _d in rows])
        whs = dict(session.execute(select(Warehouse.warehouse_id, Warehouse.name).where(Warehouse.company_id == company_id)).all())
        for ln, doc in rows:
            if ln.line_id in held:
                continue
            bins = _receipt_bins(session, ln.line_id)
            free = sum((q for _b, q in bins), _ZERO)
            if free <= 0:
                continue
            waiting = _waiting_order_lines(session, company_id, doc.destination_warehouse_id, ln.item_id)
            demand = sum((n for _l, _d, n in waiting), _ZERO)
            if demand <= 0:
                continue
            item = session.get(Item, ln.item_id)
            acc = session.get(DetailAccount, item.item_detail_account_id)
            out.append(SimpleNamespace(
                line_id=ln.line_id, stock_document_id=doc.stock_document_id, document_no=doc.document_no,
                warehouse_id=doc.destination_warehouse_id, warehouse_name=whs.get(doc.destination_warehouse_id, ""),
                item_id=ln.item_id, item_label=f"{acc.code} — {acc.name or ''}", free=free, demand=demand,
                quantity=min(free, demand), orders=sorted({d.document_no for _l, d, _n in waiting})))
    return out


def execute(company_id: int, user_id: int, stock_line_id: int) -> list[int]:
    """رزرو موجودی محل رسید برای سفارش‌های منتظر و ساخت وظیفهٔ برداشت از همان محل؛ خروجی = وظایف ساخته‌شده."""
    created = []
    with new_session() as session:
        ln = session.get(StockDocumentLine, stock_line_id)
        doc = session.get(StockDocument, ln.stock_document_id) if ln is not None else None
        if doc is None or doc.company_id != company_id or doc.document_type_code != "RECEIPT" or doc.status_code != "POSTED":
            raise ValueError("ردیف رسید نامعتبر است.")
        bins = _receipt_bins(session, stock_line_id)
        waiting = _waiting_order_lines(session, company_id, doc.destination_warehouse_id, ln.item_id)
        if not bins or not waiting:
            raise ValueError("برای این ردیف سفارش منتظر یا موجودی آزاد در محل رسید نیست.")
        existing = set(session.scalars(select(WarehouseTask.source_commercial_line_id).where(
            WarehouseTask.task_type_code == "PICK", WarehouseTask.status_code != "CANCELLED",
            WarehouseTask.source_commercial_line_id.in_([o.line_id for o, _d, _n in waiting]))))
        total = _ZERO
        for order_line, order, need in waiting:
            for i, (bin_id, free) in enumerate(bins):
                take = min(free, need)
                if take <= 0:
                    continue
                stock_reservations.add(session, company_id=company_id, item_id=ln.item_id, warehouse_id=doc.destination_warehouse_id,
                                       bin_location_id=bin_id, quantity=take, source_type=stock_reservations.SALES_ORDER,
                                       source_id=order_line.line_id)
                bins[i] = (bin_id, free - take)
                need -= take
                total += take
                if order_line.line_id not in existing:
                    task = WarehouseTask(company_id=company_id, warehouse_id=doc.destination_warehouse_id, task_type_code="PICK",
                                         source_commercial_document_id=order.document_id, source_commercial_line_id=order_line.line_id,
                                         item_id=ln.item_id, quantity_base=order_line.quantity_base, from_bin_location_id=bin_id,
                                         created_by_user_id=user_id, notes=f"ارسال مستقیم از رسید #{doc.document_no}")
                    session.add(task)
                    session.flush()
                    existing.add(order_line.line_id)
                    created.append(task.task_id)
                if need <= 0:
                    break
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="StockDocument",
                                   entity_id=doc.stock_document_id, action="EXECUTE",
                                   changes={"operation": "CROSS_DOCK", "stock_line_id": stock_line_id, "quantity": str(total),
                                            "tasks": created})
        session.commit()
    return created


def pending_by_warehouse(company_id: int) -> dict[int, int]:
    out: dict[int, int] = {}
    for o in opportunities(company_id):
        out[o.warehouse_id] = out.get(o.warehouse_id, 0) + 1
    return out
