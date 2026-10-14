"""R306 — نگه‌داشت رسید تا تایید کیفیت (کلید WMS_QC_HOLD).

ردیف رسید تامین‌کننده که کالا یا انبارش «نیازمند کنترل کیفیت» است، پس از ثبت با یک رزرو QC_HOLD روی همان محل
نگه داشته می‌شود؛ کنترل رزرو موتور انبار مانع فروش و خروجش است. بازرسی: مقدار پذیرفته آزاد می‌شود و مقدار ردشده
با سند انتقال عادی به انبار قرنطینه/ضایعات می‌رود (همان تراکنش). نتیجه در inv.qc_inspections می‌نشیند.
"""

from __future__ import annotations

import dataclasses
import datetime
import decimal
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.inventory import (
    Batch, Item, LineTrackingEntry, QcInspection, StockDocument, StockDocumentLine, StockLedger, StockReservation, Warehouse,
)
from peecha.services import audit as audit_service
from peecha.services import stock_controls, stock_reservations, supplier_quality

SOURCE = "QC_HOLD"
_TYPES = ("RECEIPT", "CONSIGNMENT_IN")
_ZERO = decimal.Decimal(0)
RESULT_LABELS = {"APPROVED": "پذیرفته", "REJECTED": "ردشده", "PARTIAL": "پذیرش بخشی"}


def hold_receipt(session, doc: StockDocument) -> int:
    """پس از موتور انبار و در همان تراکنش ثبت؛ خروجی = تعداد ردیف‌های نگه‌داشته."""
    if doc.document_type_code not in _TYPES or doc.counterparty_detail_account_id is None:
        return 0
    if not stock_controls.is_on(doc.company_id, stock_controls.QC_HOLD, session):
        return 0
    warehouse = session.get(Warehouse, doc.destination_warehouse_id)
    n = 0
    for ln in session.scalars(select(StockDocumentLine).where(StockDocumentLine.stock_document_id == doc.stock_document_id)):
        item = session.get(Item, ln.item_id)
        if not (ln.quality_status_code == "PENDING" or item.requires_qc or (warehouse is not None and warehouse.requires_qc)):
            continue
        if stock_reservations.active(session, SOURCE, [ln.line_id], lock=False):
            continue
        if session.scalar(select(QcInspection.qc_inspection_id).where(QcInspection.stock_document_line_id == ln.line_id).limit(1)):
            continue   # R310: ردیف بازرسی‌شده با شکست برگشت سند دوباره نگه داشته نمی‌شود
        for bin_id, qty in session.execute(
                select(StockLedger.bin_location_id, func.sum(StockLedger.quantity_base))
                .where(StockLedger.stock_document_line_id == ln.line_id, StockLedger.movement_direction == "IN")
                .group_by(StockLedger.bin_location_id)).all():
            if qty and qty > 0:
                stock_reservations.add(session, company_id=doc.company_id, item_id=ln.item_id, warehouse_id=doc.destination_warehouse_id,
                                       bin_location_id=bin_id, quantity=decimal.Decimal(qty), source_type=SOURCE, source_id=ln.line_id)
        ln.quality_status_code = "PENDING"
        n += 1
    return n


def release_document(stock_document_id: int) -> int:
    """برگشت/حذف رسید: نگه‌داشت ردیف‌هایش آزاد می‌شود. خروجی = تعداد رزروهای آزادشده."""
    with new_session() as session:
        ids = list(session.scalars(select(StockDocumentLine.line_id).where(StockDocumentLine.stock_document_id == stock_document_id)))
        rows = stock_reservations.active(session, SOURCE, ids)
        for res in rows:
            stock_reservations.release(session, res)
        session.commit()
        return len(rows)


def rehold_document(stock_document_id: int) -> None:
    with new_session() as session:
        doc = session.get(StockDocument, stock_document_id)
        if doc is not None and doc.status_code == "POSTED":
            hold_receipt(session, doc)
            session.commit()


def waiting_line_ids(session, line_ids=None) -> set[int]:
    q = select(StockReservation.source_record_id).where(StockReservation.source_type_code == SOURCE,
                                                        StockReservation.status_code == "ACTIVE")
    if line_ids is not None:
        q = q.where(StockReservation.source_record_id.in_(list(line_ids) or [-1]))
    return set(session.scalars(q))


def list_pending(company_id: int, warehouse_id: int | None = None) -> list[SimpleNamespace]:
    """ردیف‌های رسید منتظر کنترل کیفیت (قدیمی‌ترین اول)."""

    with new_session() as session:
        q = select(StockReservation).where(StockReservation.company_id == company_id, StockReservation.source_type_code == SOURCE,
                                           StockReservation.status_code == "ACTIVE")
        if warehouse_id is not None:
            q = q.where(StockReservation.warehouse_id == warehouse_id)
        held: dict[int, decimal.Decimal] = {}
        for res in session.scalars(q):
            held[res.source_record_id] = held.get(res.source_record_id, _ZERO) + stock_reservations.remaining(res)
        out = []
        for line_id, qty in held.items():
            ln = session.get(StockDocumentLine, line_id)
            doc = session.get(StockDocument, ln.stock_document_id)
            item = session.get(Item, ln.item_id)
            item_acc = session.get(DetailAccount, item.item_detail_account_id)
            batches = sorted({e.batch_no for e in session.scalars(select(LineTrackingEntry).where(
                LineTrackingEntry.stock_line_id == line_id)) if e.batch_no})
            supplier = session.get(DetailAccount, doc.counterparty_detail_account_id) if doc.counterparty_detail_account_id else None
            out.append(SimpleNamespace(
                line_id=line_id, stock_document_id=doc.stock_document_id, document_no=doc.document_no,
                document_type_code=doc.document_type_code, document_date=doc.document_date, posted_at=doc.posted_at,
                warehouse_id=doc.destination_warehouse_id, item_id=item.item_id, item_code=item_acc.code, item_name=item_acc.name or "",
                quantity=qty, batch_nos=batches, supplier_name=supplier.name if supplier else "",
                qc_standard=item.qc_standard, qc_test_spec=item.qc_test_spec))
    return sorted(out, key=lambda r: (r.posted_at or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc), r.line_id))


def reject_warehouses(company_id: int) -> list[Warehouse]:
    with new_session() as session:
        return list(session.scalars(select(Warehouse).where(
            Warehouse.company_id == company_id, Warehouse.is_active.is_(True),
            Warehouse.warehouse_type_code.in_(stock_controls.DISPOSAL_WAREHOUSE_TYPES)).order_by(Warehouse.code)))


def _reject_tracking(session, line_id: int, quantity: decimal.Decimal) -> list:
    """بچ/سریال‌های ردیف رسید به ترتیب ورود، تا سقف مقدار ردشده."""
    from peecha.services import lot_tracking

    out, left = [], quantity
    for e in session.scalars(select(LineTrackingEntry).where(LineTrackingEntry.stock_line_id == line_id)
                             .order_by(LineTrackingEntry.entry_id)):
        if left <= 0:
            break
        take = min(decimal.Decimal(e.quantity), left)
        out.append(lot_tracking.TrackingEntry(take, e.batch_no, e.manufacture_date, e.expiry_date, e.serial_no,
                                              e.supplier_detail_account_id, e.is_consignment))
        left -= take
    return out


def inspect(company_id: int, line_id: int, user_id: int, rejected_quantity: decimal.Decimal = _ZERO,
            reject_warehouse_id: int | None = None, sampled_quantity: decimal.Decimal | None = None,
            notes: str | None = None) -> SimpleNamespace:
    """ثبت نتیجهٔ بازرسی یک ردیف رسید؛ مقدار ردشده به انبار قرنطینه/ضایعات منتقل می‌شود."""
    from peecha.services import inventory_documents as inv_docs

    rejected = decimal.Decimal(rejected_quantity or 0)
    if rejected < 0:
        raise ValueError("مقدار ردشده نمی‌تواند منفی باشد.")
    with new_session() as session:
        ln = session.get(StockDocumentLine, line_id)
        doc = session.get(StockDocument, ln.stock_document_id) if ln is not None else None
        if doc is None or doc.company_id != company_id:
            raise ValueError("ردیف رسید نامعتبر است.")
        holds = stock_reservations.active(session, SOURCE, [line_id])
        if not holds:
            raise ValueError("این ردیف منتظر کنترل کیفیت نیست.")
        held = sum((stock_reservations.remaining(r) for r in holds), _ZERO)
        if rejected > held:
            raise ValueError(f"مقدار ردشده از مقدار منتظر کنترل ({held.normalize()}) بیشتر است.")
        transfer_id = None
        if rejected > 0:
            source = session.get(Warehouse, doc.destination_warehouse_id)
            target_id = reject_warehouse_id or source.default_quarantine_warehouse_id
            target = session.get(Warehouse, target_id) if target_id else None
            if target is None or target.company_id != company_id:
                raise ValueError("برای مقدار ردشده، انبار قرنطینه یا ضایعات را انتخاب کنید.")
            if target.warehouse_type_code not in stock_controls.DISPOSAL_WAREHOUSE_TYPES:
                raise ValueError(f"انبار «{target.name}» از نوع قرنطینه یا ضایعات نیست.")
        portions = [(res.bin_location_id, stock_reservations.remaining(res)) for res in holds]
        for res in holds:
            stock_reservations.release(session, res, "FULFILLED")
        session.flush()
        if rejected > 0:
            item = session.get(Item, ln.item_id)
            entries = _reject_tracking(session, line_id, rejected) if (item.track_batch or item.track_serial) else []
            lines, tracking, left = [], {}, rejected
            for bin_id, qty in portions:
                if left <= 0:
                    break
                take = min(qty, left)
                part, need = [], take
                while entries and need > 0:  # بچ/سریال‌ها به ترتیب، بین محل‌ها تقسیم می‌شوند
                    e = entries[0]
                    q = min(decimal.Decimal(e.quantity), need)
                    part.append(dataclasses.replace(e, quantity=q))
                    need -= q
                    if q == e.quantity:
                        entries.pop(0)
                    else:
                        entries[0] = dataclasses.replace(e, quantity=decimal.Decimal(e.quantity) - q)
                if part:
                    tracking[len(lines)] = part
                lines.append(inv_docs.LineFields(item_id=ln.item_id, uom_id=item.base_uom_id, quantity=take, quantity_base=take,
                                                 conversion_factor=decimal.Decimal(1), bin_location_id=bin_id,
                                                 description=f"ردشده در کنترل کیفیت — رسید #{doc.document_no}"))
                left -= take
            result, _ids = inv_docs.create_and_post_in_session(
                session, company_id, user_id, "TRANSFER", datetime.date.today(),
                inv_docs.DocumentHeaderFields(source_warehouse_id=doc.destination_warehouse_id, destination_warehouse_id=target.warehouse_id,
                                              reference_no=f"QC-{line_id}", description=f"انتقال کالای ردشده در کنترل کیفیت رسید #{doc.document_no}"),
                lines, tracking=tracking)
            transfer_id = result.stock_document_id
        accepted = held - rejected
        result_code = "APPROVED" if rejected == 0 else ("REJECTED" if accepted == 0 else "PARTIAL")
        status = "REJECTED" if result_code == "REJECTED" else "APPROVED"
        ln.quality_status_code = status
        for batch in session.scalars(select(Batch).where(Batch.source_line_id == line_id)):
            batch.qc_status_code = status
        row = QcInspection(company_id=company_id, stock_document_line_id=line_id, inspected_by_user_id=user_id,
                           result_code=result_code, sampled_quantity=sampled_quantity, rejected_quantity=rejected,
                           notes=(notes or "").strip() or None)
        session.add(row)
        session.flush()
        supplier_quality.refresh(session, company_id, doc.counterparty_detail_account_id)  # R310
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="QcInspection",
                                   entity_id=row.qc_inspection_id, action="APPROVE",
                                   changes={"operation": "QC_INSPECT", "stock_line_id": line_id, "result": result_code,
                                            "accepted": str(accepted), "rejected": str(rejected), "transfer_stock_document_id": transfer_id})
        session.commit()
        return SimpleNamespace(inspection_id=row.qc_inspection_id, result_code=result_code, transfer_stock_document_id=transfer_id)


def pending_by_warehouse(company_id: int) -> dict[int, int]:
    """کارتابل: تعداد ردیف‌های منتظر کنترل کیفیت هر انبار."""
    with new_session() as session:
        rows = session.execute(select(StockReservation.warehouse_id, func.count(func.distinct(StockReservation.source_record_id)))
                               .where(StockReservation.company_id == company_id, StockReservation.source_type_code == SOURCE,
                                      StockReservation.status_code == "ACTIVE")
                               .group_by(StockReservation.warehouse_id)).all()
    return dict(rows)
