"""R309 — انتقال دومرحله‌ای بین انبارها از راه انبار ترانزیت (کلید WMS_TWO_STEP_TRANSFER).

مرحلهٔ ۱ (ارسال): همان سند انتقال پیش‌نویس کاربر، مقصدش انبار ترانزیت می‌شود و ثبت می‌شود؛ مقصد نهایی در شمارهٔ عطف
(«TRANSIT>شناسهٔ انبار») می‌ماند. مرحلهٔ ۲ (دریافت): سند انتقال عادی از ترانزیت به مقصد برای مقدار رسیده (با همان بچ‌ها).
هر دو مرحله همان موتور انبار و همان سند انتقال‌اند؛ مقدار نرسیده در انبار ترانزیت می‌ماند و در گزارش «در مسیر» دیده می‌شود.
"""

from __future__ import annotations

import datetime
import decimal
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.inventory import (
    Batch, Item, LotMovement, SerialNumber, StockDocument, StockDocumentLine, StockLedger, Warehouse,
)
from peecha.services import stock_controls

_ZERO = decimal.Decimal(0)
SEND_PREFIX = "TRANSIT>"
RECEIVE_PREFIX = "TRANSIT<"


def transit_warehouse(session, company_id: int) -> Warehouse | None:
    return session.scalars(select(Warehouse).where(
        Warehouse.company_id == company_id, Warehouse.is_active.is_(True), Warehouse.warehouse_type_code == "TRANSIT")
        .order_by(Warehouse.code)).first()


def send(company_id: int, user_id: int, stock_document_id: int) -> int:
    """سند انتقال پیش‌نویس/تاییدشدهٔ «مبدا ← مقصد» را از راه انبار ترانزیت ارسال می‌کند؛ خروجی = همان شناسهٔ سند."""
    from peecha.services import inventory_documents as inv_docs

    if not is_enabled(company_id):
        raise ValueError("قابلیت «انتقال دومرحله‌ای بین انبارها» در تنظیمات انبار خاموش است.")
    with new_session() as session:
        doc = session.get(StockDocument, stock_document_id)
        if doc is None or doc.company_id != company_id or doc.document_type_code != "TRANSFER":
            raise ValueError("فقط سند انتقال بین انبارها را می‌توان دومرحله‌ای فرستاد.")
        if doc.status_code not in ("DRAFT", "CONFIRMED"):
            raise ValueError("این سند پیش‌تر ثبت شده است.")
        transit = transit_warehouse(session, company_id)
        if transit is None:
            raise ValueError("یک انبار از نوع «ترانزیت» تعریف کنید.")
        destination = session.get(Warehouse, doc.destination_warehouse_id)
        if destination is None or doc.source_warehouse_id == doc.destination_warehouse_id:
            raise ValueError("انتقال دومرحله‌ای برای جابه‌جایی بین دو انبار جداست.")
        if transit.warehouse_id in (doc.source_warehouse_id, doc.destination_warehouse_id):
            raise ValueError("مبدا و مقصد نباید خود انبار ترانزیت باشند.")
        status, transit_id, dest_name = doc.status_code, transit.warehouse_id, destination.name
    if status == "CONFIRMED":
        inv_docs.revert_to_draft(stock_document_id, company_id)
    with new_session() as session:
        doc = session.get(StockDocument, stock_document_id)
        final = doc.destination_warehouse_id
        doc.destination_warehouse_id = transit_id
        doc.reference_no = f"{SEND_PREFIX}{final}"
        doc.description = ((doc.description or "") + f" — در راه به «{dest_name}»").strip(" —")
        for ln in session.scalars(select(StockDocumentLine).where(StockDocumentLine.stock_document_id == stock_document_id)):
            ln.destination_bin_location_id = None
        session.commit()
    inv_docs.confirm_stock_document(stock_document_id, company_id)
    inv_docs.post_stock_document(stock_document_id, company_id, user_id)
    return stock_document_id


def _received(session, send_id: int) -> dict[int, decimal.Decimal]:
    """کالا ← مقدار دریافت‌شده در اسناد مرحلهٔ ۲ همین ارسال."""
    rows = session.execute(
        select(StockDocumentLine.item_id, func.sum(StockDocumentLine.quantity_base))
        .join(StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id)
        .where(StockDocument.reference_no == f"{RECEIVE_PREFIX}{send_id}", StockDocument.status_code == "POSTED")
        .group_by(StockDocumentLine.item_id)).all()
    return {i: decimal.Decimal(q) for i, q in rows}


def _sent(session, send_id: int, transit_id: int) -> dict[int, decimal.Decimal]:
    rows = session.execute(
        select(StockLedger.item_id, func.sum(StockLedger.quantity_base))
        .join(StockDocumentLine, StockDocumentLine.line_id == StockLedger.stock_document_line_id)
        .where(StockDocumentLine.stock_document_id == send_id, StockLedger.warehouse_id == transit_id,
               StockLedger.movement_direction == "IN")
        .group_by(StockLedger.item_id)).all()
    return {i: decimal.Decimal(q) for i, q in rows}


def in_transit(company_id: int, destination_warehouse_id: int | None = None) -> list[SimpleNamespace]:
    """ارسال‌هایی که هنوز کامل دریافت نشده‌اند (قدیمی‌ترین اول)."""
    out = []
    with new_session() as session:
        transit = transit_warehouse(session, company_id)
        if transit is None:
            return []
        docs = list(session.scalars(select(StockDocument).where(
            StockDocument.company_id == company_id, StockDocument.document_type_code == "TRANSFER",
            StockDocument.status_code == "POSTED", StockDocument.reference_no.like(f"{SEND_PREFIX}%"))
            .order_by(StockDocument.posted_at, StockDocument.stock_document_id)))
        whs = dict(session.execute(select(Warehouse.warehouse_id, Warehouse.name).where(Warehouse.company_id == company_id)).all())
        for d in docs:
            final = int(d.reference_no[len(SEND_PREFIX):])
            if destination_warehouse_id is not None and final != destination_warehouse_id:
                continue
            sent, got = _sent(session, d.stock_document_id, d.destination_warehouse_id), _received(session, d.stock_document_id)
            lines = []
            for item_id, qty in sent.items():
                left = qty - got.get(item_id, _ZERO)
                if left > 0:
                    item = session.get(Item, item_id)
                    acc = session.get(DetailAccount, item.item_detail_account_id)
                    lines.append(SimpleNamespace(item_id=item_id, item_label=f"{acc.code} — {acc.name or ''}", sent=qty,
                                                 received=got.get(item_id, _ZERO), remaining=left, base_uom_id=item.base_uom_id))
            if lines:
                out.append(SimpleNamespace(stock_document_id=d.stock_document_id, document_no=d.document_no, posted_at=d.posted_at,
                                           source_warehouse_id=d.source_warehouse_id, source_name=whs.get(d.source_warehouse_id, ""),
                                           destination_warehouse_id=final, destination_name=whs.get(final, ""),
                                           transit_warehouse_id=d.destination_warehouse_id, lines=lines))
    return out


def _lots_for(session, send_id: int, transit_id: int, item_id: int, already: decimal.Decimal, qty: decimal.Decimal) -> list:
    """بچ/سریال‌های همان ارسال به ترتیب ورود، بعد از کسر آنچه پیش‌تر دریافت شده."""
    from peecha.services import lot_tracking

    out, skip, need = [], already, qty
    for m in session.scalars(select(LotMovement).join(StockDocumentLine, StockDocumentLine.line_id == LotMovement.stock_document_line_id)
                             .where(StockDocumentLine.stock_document_id == send_id, LotMovement.warehouse_id == transit_id,
                                    LotMovement.item_id == item_id, LotMovement.quantity_base > 0)
                             .order_by(LotMovement.movement_id)):
        q = decimal.Decimal(m.quantity_base)
        if skip > 0:
            used = min(skip, q)
            skip, q = skip - used, q - used
        take = min(q, need)
        if take <= 0:
            continue
        batch = session.get(Batch, m.batch_id) if m.batch_id else None
        serial = session.get(SerialNumber, m.serial_id) if m.serial_id else None
        out.append(lot_tracking.TrackingEntry(take, batch.batch_no if batch else None, batch.manufacture_date if batch else None,
                                              batch.expiry_date if batch else None, serial.serial_no if serial else None,
                                              m.supplier_detail_account_id, m.is_consignment))
        need -= take
        if need <= 0:
            break
    return out


def receive(company_id: int, user_id: int, send_id: int, quantities: dict[int, decimal.Decimal] | None = None) -> int:
    """مرحلهٔ ۲: دریافت در انبار مقصد (quantities: کالا ← مقدار رسیده؛ خالی = همهٔ ماندهٔ در راه)."""
    from peecha.services import inventory_documents as inv_docs

    shipment = next((s for s in in_transit(company_id) if s.stock_document_id == send_id), None)
    if shipment is None:
        raise ValueError("این ارسال در راه نیست یا پیش‌تر کامل دریافت شده است.")
    with new_session() as session:
        got = _received(session, send_id)
        lines, tracking = [], {}
        for ln in shipment.lines:
            qty = decimal.Decimal(quantities.get(ln.item_id, _ZERO)) if quantities is not None else ln.remaining
            if qty < 0 or qty > ln.remaining:
                raise ValueError(f"مقدار دریافتی «{ln.item_label}» باید بین صفر و {ln.remaining.normalize()} باشد.")
            if qty == 0:
                continue
            entries = _lots_for(session, send_id, shipment.transit_warehouse_id, ln.item_id, got.get(ln.item_id, _ZERO), qty)
            if entries:
                tracking[len(lines)] = entries
            lines.append(inv_docs.LineFields(item_id=ln.item_id, uom_id=ln.base_uom_id, quantity=qty, quantity_base=qty,
                                             conversion_factor=decimal.Decimal(1), description=f"دریافت ارسال #{shipment.document_no}"))
        if not lines:
            raise ValueError("مقدار دریافتی وارد نشده است.")
        result, _ids = inv_docs.create_and_post_in_session(
            session, company_id, user_id, "TRANSFER", datetime.date.today(),
            inv_docs.DocumentHeaderFields(source_warehouse_id=shipment.transit_warehouse_id,
                                          destination_warehouse_id=shipment.destination_warehouse_id,
                                          reference_no=f"{RECEIVE_PREFIX}{send_id}",
                                          description=f"دریافت ارسال #{shipment.document_no} از «{shipment.source_name}»"),
            lines, tracking=tracking)
        session.commit()
        return result.stock_document_id


def arriving_by_warehouse(company_id: int) -> dict[int, int]:
    """کارتابل: مقصد ← تعداد ارسال‌های در راه."""
    out: dict[int, int] = {}
    for s in in_transit(company_id):
        out[s.destination_warehouse_id] = out.get(s.destination_warehouse_id, 0) + 1
    return out


def is_enabled(company_id: int) -> bool:
    return stock_controls.is_on(company_id, stock_controls.TWO_STEP_TRANSFER)
