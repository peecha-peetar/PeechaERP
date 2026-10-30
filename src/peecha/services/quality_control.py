"""R306 — نگه‌داشت رسید تا تایید کیفیت (کلید WMS_QC_HOLD)؛ R311 — گردش دومرحله‌ای کیفیت.

ردیف رسید تامین‌کننده که کالا یا انبارش «نیازمند کنترل کیفیت» است، پس از ثبت با یک رزرو QC_HOLD روی همان محل
نگه داشته می‌شود؛ کنترل رزرو موتور انبار مانع فروش و خروجش است. R311 همین نگه‌داشت را برای رسید محصول تولیدی
(کلید QC_PRODUCTION) و رسید مرجوعی فروش (کلید QC_SALES_RETURN) هم به‌کار می‌برد.

گردش: ثبت نتیجه (بازرس؛ پذیرفته + مردود + در انتظار = مقدار تحت کنترل، نتایج پارامترهای طرح) ← تأیید نهایی
(تعیین تکلیف موجودی: پذیرفته آزاد، مردود با سند انتقال عادی به قرنطینه/ضایعات، در انتظار نگه‌داشته برای بازرسی
مجدد). بازرسی تأییدشده با تریگر پایگاه‌داده قفل است. inspect() همان گردش یک‌مرحله‌ای قبلی است (ثبت + تأیید در یک
تراکنش) و با کلید «جداسازی ثبت و تأیید» فقط نتیجه را ثبت می‌کند.
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
from peecha.db.models.production import OrderTransaction, ProductionOrder
from peecha.db.models.quality import InspectionPlan, InspectionResult, PlanParameter
from peecha.services import audit as audit_service
from peecha.services import stock_controls, stock_reservations, supplier_quality

SOURCE = "QC_HOLD"
_TYPES = ("RECEIPT", "CONSIGNMENT_IN")
_ZERO = decimal.Decimal(0)
RESULT_LABELS = {"APPROVED": "پذیرفته", "REJECTED": "ردشده", "PARTIAL": "پذیرش بخشی", "PENDING": "در انتظار تصمیم"}


@dataclasses.dataclass
class ResultInput:
    """نتیجهٔ یک پارامتر: از طرح (parameter_id) یا پارامتر آزاد (name + data_type + حدود)."""

    value: object
    parameter_id: int | None = None
    name: str | None = None
    data_type: str = "NUMERIC"
    min_value: decimal.Decimal | None = None
    max_value: decimal.Decimal | None = None
    sample_no: int = 1


# =====================================================================================
# نگه‌داشت
# =====================================================================================
def _is_sales_return(session, doc: StockDocument) -> bool:
    from peecha.db.models.commercial import CommercialDocument

    ref = doc.reference_no or ""
    if not ref.startswith("COMM-") or not ref[5:].isdigit():
        return False
    return session.scalar(select(CommercialDocument.document_type_code).where(
        CommercialDocument.document_id == int(ref[5:]))) == "SALES_RETURN"


def _hold_line(session, doc: StockDocument, ln: StockDocumentLine) -> int:
    if stock_reservations.active(session, SOURCE, [ln.line_id], lock=False):
        return 0
    if session.scalar(select(QcInspection.qc_inspection_id).where(QcInspection.stock_document_line_id == ln.line_id).limit(1)):
        return 0   # R310: ردیف بازرسی‌شده با شکست برگشت سند دوباره نگه داشته نمی‌شود
    for bin_id, qty in session.execute(
            select(StockLedger.bin_location_id, func.sum(StockLedger.quantity_base))
            .where(StockLedger.stock_document_line_id == ln.line_id, StockLedger.movement_direction == "IN")
            .group_by(StockLedger.bin_location_id)).all():
        if qty and qty > 0:
            stock_reservations.add(session, company_id=doc.company_id, item_id=ln.item_id, warehouse_id=doc.destination_warehouse_id,
                                   bin_location_id=bin_id, quantity=decimal.Decimal(qty), source_type=SOURCE, source_id=ln.line_id)
    ln.quality_status_code = "PENDING"
    return 1


def hold_receipt(session, doc: StockDocument) -> int:
    """پس از موتور انبار و در همان تراکنش ثبت؛ خروجی = تعداد ردیف‌های نگه‌داشته."""
    if not stock_controls.is_on(doc.company_id, stock_controls.QC_HOLD, session):
        return 0
    lines = list(session.scalars(select(StockDocumentLine).where(StockDocumentLine.stock_document_id == doc.stock_document_id)))
    if doc.document_type_code in _TYPES and doc.counterparty_detail_account_id is not None:
        warehouse = session.get(Warehouse, doc.destination_warehouse_id)
        lines = [ln for ln in lines if ln.quality_status_code == "PENDING" or session.get(Item, ln.item_id).requires_qc
                 or (warehouse is not None and warehouse.requires_qc)]
    elif (doc.document_type_code == "RETURN_IN" and stock_controls.is_on(doc.company_id, stock_controls.QC_SALES_RETURN, session)
          and _is_sales_return(session, doc)):
        pass   # R311: همهٔ کالای مرجوعی مشتری تا بازرسی
    else:
        return 0
    return sum(_hold_line(session, doc, ln) for ln in lines)


def hold_production_receipt(session, order: ProductionOrder, stock_document_id: int) -> int:
    """R311 (کلید QC_PRODUCTION): رسید محصولی که کالایش نیازمند کیفیت است یا طرح بازرسی نهایی فعال دارد."""
    from peecha.services.qms import plans as qms_plans

    if not (stock_controls.is_on(order.company_id, stock_controls.QC_HOLD, session)
            and stock_controls.is_on(order.company_id, stock_controls.QC_PRODUCTION, session)):
        return 0
    doc = session.get(StockDocument, stock_document_id)
    n = 0
    for ln in session.scalars(select(StockDocumentLine).where(StockDocumentLine.stock_document_id == stock_document_id)):
        item = session.get(Item, ln.item_id)
        if item.requires_qc or qms_plans.find_plan(session, order.company_id, "FINAL", ln.item_id,
                                                   work_center_id=order.work_center_id) is not None:
            n += _hold_line(session, doc, ln)
    return n


def release_document(stock_document_id: int) -> int:
    """برگشت/حذف رسید: نگه‌داشت ردیف‌هایش آزاد می‌شود. خروجی = تعداد رزروهای آزادشده."""
    with new_session() as session:
        ids = list(session.scalars(select(StockDocumentLine.line_id).where(StockDocumentLine.stock_document_id == stock_document_id)))
        rows = stock_reservations.active(session, SOURCE, ids)
        for res in rows:
            stock_reservations.release(session, res)
        # نتیجهٔ تأییدنشدهٔ ردیف برگشت‌خورده دیگر کالایی برای تعیین تکلیف ندارد
        for q in session.scalars(select(QcInspection).where(QcInspection.stock_document_line_id.in_(ids or [-1]),
                                                            QcInspection.status_code == "RECORDED")):
            q.status_code, q.decision_notes = "CANCELLED", "سند منبع برگشت خورد."
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


def source_of(session, doc: StockDocument) -> tuple[str, int | None]:
    """(مرحله، دستور تولید) برای یک سند ورودی تحت کنترل."""
    if doc.document_type_code == "RETURN_IN":
        return "SALES_RETURN", None
    order_id = session.scalar(select(OrderTransaction.order_id).where(
        OrderTransaction.stock_document_id == doc.stock_document_id).limit(1))
    return ("FINAL", order_id) if order_id else ("RECEIPT", None)


def list_pending(company_id: int, warehouse_id: int | None = None) -> list[SimpleNamespace]:
    """ردیف‌های منتظر کنترل کیفیت (قدیمی‌ترین اول)، با نتیجهٔ ثبت‌شدهٔ منتظر تأیید اگر باشد."""
    with new_session() as session:
        q = select(StockReservation).where(StockReservation.company_id == company_id, StockReservation.source_type_code == SOURCE,
                                           StockReservation.status_code == "ACTIVE")
        if warehouse_id is not None:
            q = q.where(StockReservation.warehouse_id == warehouse_id)
        held: dict[int, decimal.Decimal] = {}
        for res in session.scalars(q):
            held[res.source_record_id] = held.get(res.source_record_id, _ZERO) + stock_reservations.remaining(res)
        open_rows = {r.stock_document_line_id: r for r in session.scalars(select(QcInspection).where(
            QcInspection.stock_document_line_id.in_(list(held) or [-1]), QcInspection.status_code == "RECORDED"))}
        out = []
        for line_id, qty in held.items():
            ln = session.get(StockDocumentLine, line_id)
            doc = session.get(StockDocument, ln.stock_document_id)
            item = session.get(Item, ln.item_id)
            item_acc = session.get(DetailAccount, item.item_detail_account_id)
            batches = sorted({e.batch_no for e in session.scalars(select(LineTrackingEntry).where(
                LineTrackingEntry.stock_line_id == line_id)) if e.batch_no})
            party = session.get(DetailAccount, doc.counterparty_detail_account_id) if doc.counterparty_detail_account_id else None
            stage, order_id = source_of(session, doc)
            rec = open_rows.get(line_id)
            out.append(SimpleNamespace(
                line_id=line_id, stock_document_id=doc.stock_document_id, document_no=doc.document_no,
                document_type_code=doc.document_type_code, document_date=doc.document_date, posted_at=doc.posted_at,
                warehouse_id=doc.destination_warehouse_id, item_id=item.item_id, item_code=item_acc.code, item_name=item_acc.name or "",
                quantity=qty, batch_nos=batches, supplier_name=party.name if party and stage == "RECEIPT" else "",
                party_name=party.name if party else "", stage_code=stage, production_order_id=order_id,
                qc_standard=item.qc_standard, qc_test_spec=item.qc_test_spec,
                open_inspection_id=rec.qc_inspection_id if rec else None,
                recorded_by_user_id=rec.inspected_by_user_id if rec else None))
    return sorted(out, key=lambda r: (r.posted_at or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc), r.line_id))


def reject_warehouses(company_id: int) -> list[Warehouse]:
    with new_session() as session:
        return list(session.scalars(select(Warehouse).where(
            Warehouse.company_id == company_id, Warehouse.is_active.is_(True),
            Warehouse.warehouse_type_code.in_(stock_controls.DISPOSAL_WAREHOUSE_TYPES)).order_by(Warehouse.code)))


def _decided_before(session, line_id: int, exclude_id: int | None = None) -> decimal.Decimal:
    q = select(func.coalesce(func.sum(func.coalesce(QcInspection.accepted_quantity, 0) + func.coalesce(QcInspection.rejected_quantity, 0)), 0)
               ).where(QcInspection.stock_document_line_id == line_id, QcInspection.status_code == "APPROVED")
    if exclude_id is not None:
        q = q.where(QcInspection.qc_inspection_id != exclude_id)
    return decimal.Decimal(session.scalar(q) or 0)


def _reject_tracking(session, line_id: int, quantity: decimal.Decimal, skip: decimal.Decimal = _ZERO) -> list:
    """بچ/سریال‌های ردیف رسید به ترتیب ورود، پس از کسر مقدار تصمیم‌گرفتهٔ قبلی، تا سقف مقدار ردشده."""
    from peecha.services import lot_tracking

    out, left = [], quantity
    for e in session.scalars(select(LineTrackingEntry).where(LineTrackingEntry.stock_line_id == line_id)
                             .order_by(LineTrackingEntry.entry_id)):
        if left <= 0:
            break
        q = decimal.Decimal(e.quantity)
        if skip > 0:
            used = min(skip, q)
            skip, q = skip - used, q - used
        take = min(q, left)
        if take <= 0:
            continue
        out.append(lot_tracking.TrackingEntry(take, e.batch_no, e.manufacture_date, e.expiry_date, e.serial_no,
                                              e.supplier_detail_account_id, e.is_consignment))
        left -= take
    return out


# =====================================================================================
# ثبت نتیجه
# =====================================================================================
def _result_code(lot: decimal.Decimal, accepted: decimal.Decimal, rejected: decimal.Decimal, pending: decimal.Decimal) -> str:
    if pending == lot:
        return "PENDING"
    if rejected == 0 and pending == 0:
        return "APPROVED"
    if accepted == 0 and pending == 0:
        return "REJECTED"
    return "PARTIAL"


def _disposition(result_code: str, requested: str | None, pending: decimal.Decimal, accepted: decimal.Decimal) -> str:
    if requested == "REWORK":
        if pending <= 0:
            raise ValueError("برای دوباره‌کاری، مقدار «در انتظار» را برابر مقدار دوباره‌کاری ثبت کنید.")
        return "REWORK"
    if requested == "CONCESSION":
        if accepted <= 0:
            raise ValueError("مصرف مشروط بدون مقدار پذیرفته معنا ندارد.")
        return "CONCESSION"
    if requested not in (None, ""):
        raise ValueError("تصمیم کیفیت نامعتبر است.")
    return {"APPROVED": "ACCEPT", "REJECTED": "REJECT", "PARTIAL": "PARTIAL", "PENDING": "PENDING"}[result_code]


def _write_results(session, row: QcInspection, plan: InspectionPlan | None, results, user_id: int) -> int:
    """نتایج پارامترها با مشخصات ثابت‌شده؛ خروجی = تعداد نمونه‌های دارای عدم‌انطباق."""
    from peecha.services.qms import plans as qms_plans

    params = {p.parameter_id: p for p in session.scalars(select(PlanParameter).where(PlanParameter.plan_id == plan.plan_id))} \
        if plan is not None else {}
    given, defective, seen = set(), set(), set()
    for r in results or []:
        sample_no = int(r.sample_no or 1)
        if sample_no < 1:
            raise ValueError("شمارهٔ نمونه باید از ۱ شروع شود.")
        if r.parameter_id is not None:
            p = params.get(r.parameter_id)
            if p is None:
                raise ValueError("پارامتر در طرح کیفیت این بازرسی نیست.")
            spec = (p.name, p.data_type, p.uom_label, p.min_value, p.max_value, p.target_value, p.options, p.is_mandatory)
        else:
            if not (r.name or "").strip() or r.data_type not in ("NUMERIC", "PASS_FAIL", "TEXT"):
                raise ValueError("پارامتر آزاد نام و نوع دادهٔ معتبر لازم دارد.")
            spec = (r.name.strip(), r.data_type, None, r.min_value, r.max_value, None, None, False)
        key = (r.parameter_id, spec[0], sample_no)
        if key in seen:
            raise ValueError(f"نتیجهٔ «{spec[0]}» برای نمونهٔ {sample_no} دو بار وارد شده است.")
        seen.add(key)
        name, data_type, uom, lo, hi, target, options, mandatory = spec
        value = r.value
        if (value is None or value == "") and mandatory:
            raise ValueError(f"مقدار پارامتر اجباری «{name}» خالی است.")
        ok = qms_plans.evaluate(data_type, value, lo, hi, options)
        session.add(InspectionResult(
            company_id=row.company_id, qc_inspection_id=row.qc_inspection_id, parameter_id=r.parameter_id, sample_no=sample_no,
            parameter_name=name, data_type=data_type, uom_label=uom, min_value=lo, max_value=hi, target_value=target,
            options=options, is_mandatory=mandatory,
            value_numeric=decimal.Decimal(str(value)) if data_type == "NUMERIC" and value not in (None, "") else None,
            value_bool=bool(value) if data_type == "PASS_FAIL" and value not in (None, "") else None,
            value_text=str(value)[:500] if data_type in ("OPTION", "TEXT") and value not in (None, "") else None,
            is_conforming=ok, recorded_by_user_id=user_id))
        given.add(r.parameter_id)
        if ok is False:
            defective.add(sample_no)
    missing = [p.name for p in params.values() if p.is_mandatory and p.parameter_id not in given]
    if missing:
        raise ValueError(f"نتیجهٔ پارامترهای اجباری طرح «{plan.name}» ثبت نشده: {'، '.join(missing)}")
    return len(defective)


def _check_plan_verdict(plan, defective: int, rejected, pending, disposition) -> None:
    from peecha.services.qms import plans as qms_plans

    if plan is not None and qms_plans.verdict(plan, defective) == "REJECT" and rejected == 0 and pending == 0 \
            and disposition != "CONCESSION":
        raise ValueError(f"طبق طرح «{plan.name}» نمونه‌های معیوب ({defective}) از عدد پذیرش ({plan.acceptance_number}) بیشترند؛ "
                         "مقدار مردود یا در انتظار را ثبت کنید یا «مصرف مشروط» را انتخاب کنید.")


def _resolve_plan(session, company_id: int, stage: str, item_id: int, plan_id: int | None, supplier_id: int | None = None,
                  work_center_id: int | None = None, operation_id: int | None = None, doc_type: str | None = None):
    from peecha.services.qms import plans as qms_plans

    if plan_id is not None:
        plan = session.get(InspectionPlan, plan_id)
        if plan is None or plan.company_id != company_id or plan.status_code != "ACTIVE":
            raise ValueError("طرح کیفیت انتخاب‌شده فعال نیست.")
        if plan.stage_code != stage:
            raise ValueError("مرحلهٔ طرح کیفیت با این بازرسی نمی‌خواند.")
        return plan
    return qms_plans.find_plan(session, company_id, stage, item_id, supplier_id=supplier_id, work_center_id=work_center_id,
                               operation_id=operation_id, document_type_code=doc_type)


def _dec(value) -> decimal.Decimal:
    return decimal.Decimal(str(value or 0))


def _record(session, company_id: int, line_id: int, user_id: int, accepted, rejected, pending, sampled, results, notes,
            plan_id, disposition, idempotency_key, log: bool = True) -> QcInspection:
    from peecha.services.qms import common as qc_common

    if idempotency_key:
        done = session.scalar(select(QcInspection).where(QcInspection.company_id == company_id,
                                                         QcInspection.idempotency_key == idempotency_key))
        if done is not None:
            return done
    qc_common.require(company_id, user_id, qc_common.FORM_INSPECT, "CREATE", session=session)
    accepted, rejected, pending = _dec(accepted), _dec(rejected), _dec(pending)
    if min(accepted, rejected, pending) < 0:
        raise ValueError("مقدارها نمی‌توانند منفی باشند.")
    ln = session.get(StockDocumentLine, line_id)
    doc = session.get(StockDocument, ln.stock_document_id) if ln is not None else None
    if doc is None or doc.company_id != company_id:
        raise ValueError("ردیف رسید نامعتبر است.")
    holds = stock_reservations.active(session, SOURCE, [line_id])
    if not holds:
        raise ValueError("این ردیف منتظر کنترل کیفیت نیست.")
    held = sum((stock_reservations.remaining(r) for r in holds), _ZERO)
    if accepted + rejected + pending != held:
        raise ValueError(f"جمع پذیرفته، مردود و در انتظار باید برابر مقدار تحت کنترل ({held.normalize():f}) باشد.")
    if sampled is not None and _dec(sampled) > held:
        raise ValueError("مقدار نمونه از مقدار تحت کنترل بیشتر است.")
    if session.scalar(select(QcInspection.qc_inspection_id).where(QcInspection.stock_document_line_id == line_id,
                                                                  QcInspection.status_code == "RECORDED")):
        raise ValueError("برای این ردیف نتیجهٔ منتظر تأیید ثبت شده است؛ آن را تأیید یا لغو کنید.")
    stage, order_id = source_of(session, doc)
    order = session.get(ProductionOrder, order_id) if order_id else None
    plan = _resolve_plan(session, company_id, stage, ln.item_id, plan_id,
                         supplier_id=doc.counterparty_detail_account_id if stage == "RECEIPT" else None,
                         work_center_id=order.work_center_id if order else None, doc_type=doc.document_type_code)
    result_code = _result_code(held, accepted, rejected, pending)
    disp = _disposition(result_code, disposition, pending, accepted)
    previous = session.scalar(select(QcInspection.qc_inspection_id).where(
        QcInspection.stock_document_line_id == line_id, QcInspection.status_code == "APPROVED")
        .order_by(QcInspection.qc_inspection_id.desc()).limit(1))
    row = QcInspection(company_id=company_id, stock_document_line_id=line_id, inspected_by_user_id=user_id,
                       result_code=result_code, sampled_quantity=_dec(sampled) if sampled not in (None, "") else None,
                       rejected_quantity=rejected, accepted_quantity=accepted, pending_quantity=pending, lot_quantity=held,
                       notes=(notes or "").strip() or None, stage_code=stage, status_code="RECORDED",
                       plan_id=plan.plan_id if plan else None, disposition_code=disp, production_order_id=order_id,
                       reinspection_of_id=previous, idempotency_key=idempotency_key)
    session.add(row)
    session.flush()
    defective = _write_results(session, row, plan, results, user_id)
    _check_plan_verdict(plan, defective, rejected, pending, disp)
    if log:
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="QcInspection",
                                   entity_id=row.qc_inspection_id, action="CREATE",
                                   changes={"operation": "QC_RECORD", "stock_line_id": line_id, "stage": stage,
                                            "accepted": str(accepted), "rejected": str(rejected), "pending": str(pending),
                                            "plan_id": row.plan_id, "defective_samples": defective, "disposition": disp})
    return row


def record_result(company_id: int, line_id: int, user_id: int, *, accepted, rejected=_ZERO, pending=_ZERO,
                  sampled=None, results=(), notes: str | None = None, plan_id: int | None = None,
                  disposition: str | None = None, idempotency_key: str | None = None) -> int:
    """ثبت نتیجهٔ بازرسی یک ردیف نگه‌داشته (بدون تغییر موجودی تا تأیید نهایی). خروجی = شناسهٔ بازرسی."""
    with new_session() as session:
        row = _record(session, company_id, line_id, user_id, accepted, rejected, pending, sampled, results, notes, plan_id,
                      disposition, idempotency_key)
        session.commit()
        return row.qc_inspection_id


# =====================================================================================
# تأیید نهایی و تعیین تکلیف موجودی
# =====================================================================================
def _reject_target(session, row: QcInspection, doc: StockDocument, reject_warehouse_id: int | None) -> Warehouse:
    source = session.get(Warehouse, doc.destination_warehouse_id)
    target_id = reject_warehouse_id or source.default_quarantine_warehouse_id
    if target_id is None and row.production_order_id:
        target_id = session.get(ProductionOrder, row.production_order_id).scrap_warehouse_id
    target = session.get(Warehouse, target_id) if target_id else None
    if target is None or target.company_id != row.company_id:
        raise ValueError("برای مقدار ردشده، انبار قرنطینه یا ضایعات را انتخاب کنید.")
    if target.warehouse_type_code not in stock_controls.DISPOSAL_WAREHOUSE_TYPES:
        raise ValueError(f"انبار «{target.name}» از نوع قرنطینه یا ضایعات نیست.")
    return target


def _dispose(session, row: QcInspection, user_id: int, reject_warehouse_id: int | None) -> int | None:
    """آزادسازی پذیرفته، انتقال مردود، نگه‌داشت دوبارهٔ «در انتظار» — همه در تراکنش فراخواننده."""
    from peecha.services import inventory_documents as inv_docs

    ln = session.get(StockDocumentLine, row.stock_document_line_id)
    doc = session.get(StockDocument, ln.stock_document_id)
    holds = stock_reservations.active(session, SOURCE, [ln.line_id])
    held = sum((stock_reservations.remaining(r) for r in holds), _ZERO)
    if held != decimal.Decimal(row.lot_quantity):
        raise ValueError("مقدار تحت کنترل این ردیف پس از ثبت نتیجه تغییر کرده است؛ نتیجه را لغو و دوباره ثبت کنید.")
    rejected, pending = _dec(row.rejected_quantity), _dec(row.pending_quantity)
    target = _reject_target(session, row, doc, reject_warehouse_id) if rejected > 0 else None
    portions = [(res.bin_location_id, stock_reservations.remaining(res)) for res in holds]
    for res in holds:
        stock_reservations.release(session, res, "FULFILLED")
    session.flush()
    transfer_id = None
    if rejected > 0:
        item = session.get(Item, ln.item_id)
        entries = _reject_tracking(session, ln.line_id, rejected, _decided_before(session, ln.line_id, row.qc_inspection_id)) \
            if (item.track_batch or item.track_serial) else []
        lines, tracking, left, after = [], {}, rejected, []
        for bin_id, qty in portions:
            take = min(qty, left) if left > 0 else _ZERO
            after.append((bin_id, qty - take))
            if take <= 0:
                continue
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
            session, row.company_id, user_id, "TRANSFER", datetime.date.today(),
            inv_docs.DocumentHeaderFields(source_warehouse_id=doc.destination_warehouse_id, destination_warehouse_id=target.warehouse_id,
                                          reference_no=f"QC-{ln.line_id}", description=f"انتقال کالای ردشده در کنترل کیفیت رسید #{doc.document_no}"),
            lines, tracking=tracking)
        transfer_id = result.stock_document_id
        portions = after
    need = pending
    for bin_id, qty in portions:   # «در انتظار» دوباره نگه داشته می‌شود تا بازرسی مجدد
        take = min(qty, need)
        if take > 0:
            stock_reservations.add(session, company_id=row.company_id, item_id=ln.item_id, warehouse_id=doc.destination_warehouse_id,
                                   bin_location_id=bin_id, quantity=take, source_type=SOURCE, source_id=ln.line_id)
            need -= take
    accepted_total = _dec(session.scalar(select(func.coalesce(func.sum(QcInspection.accepted_quantity), 0)).where(
        QcInspection.stock_document_line_id == ln.line_id, QcInspection.status_code == "APPROVED",
        QcInspection.qc_inspection_id != row.qc_inspection_id))) + _dec(row.accepted_quantity)
    status = "PENDING" if pending > 0 else ("APPROVED" if accepted_total > 0 else "REJECTED")
    ln.quality_status_code = status
    for batch in session.scalars(select(Batch).where(Batch.source_line_id == ln.line_id)):
        batch.qc_status_code = status
    return transfer_id


def _approve(session, row: QcInspection, user_id: int, reject_warehouse_id: int | None, notes: str | None,
             operation: str = "QC_APPROVE") -> SimpleNamespace:
    from peecha.services.qms import common as qc_common
    from peecha.services.qms import ncr as qms_ncr

    qc_common.require(row.company_id, user_id, qc_common.FORM_APPROVE, session=session)
    if row.disposition_code == "CONCESSION":
        qc_common.require(row.company_id, user_id, qc_common.FORM_RELEASE, session=session)
    if operation == "QC_APPROVE" and row.inspected_by_user_id == user_id \
            and stock_controls.is_on(row.company_id, stock_controls.QC_SEPARATE_APPROVAL, session):
        raise ValueError("ثبت‌کنندهٔ نتیجه نمی‌تواند همان نتیجه را تأیید کند؛ تأیید با فرد دیگری است.")
    transfer_id = _dispose(session, row, user_id, reject_warehouse_id) if row.stock_document_line_id else None
    row.status_code, row.approved_by_user_id = "APPROVED", user_id
    row.approved_at = datetime.datetime.now(datetime.timezone.utc)
    row.decision_notes = (notes or "").strip() or None
    row.transfer_stock_document_id = transfer_id
    session.flush()
    ncr_id = qms_ncr.auto_from_inspection(session, row, user_id)
    if row.stage_code == "RECEIPT" and row.stock_document_line_id:
        doc = session.get(StockDocument, session.get(StockDocumentLine, row.stock_document_line_id).stock_document_id)
        if doc.counterparty_detail_account_id:
            supplier_quality.refresh(session, row.company_id, doc.counterparty_detail_account_id)  # R310
    audit_service.log_activity(session, company_id=row.company_id, user_id=user_id, entity_type="QcInspection",
                               entity_id=row.qc_inspection_id, action="APPROVE",
                               changes={"operation": operation, "stock_line_id": row.stock_document_line_id, "stage": row.stage_code,
                                        "result": row.result_code, "accepted": str(row.accepted_quantity),
                                        "rejected": str(row.rejected_quantity), "pending": str(row.pending_quantity),
                                        "disposition": row.disposition_code, "transfer_stock_document_id": transfer_id,
                                        "ncr_id": ncr_id})
    return SimpleNamespace(inspection_id=row.qc_inspection_id, result_code=row.result_code,
                           transfer_stock_document_id=transfer_id, ncr_id=ncr_id, status_code="APPROVED")


def _lock_inspection(session, company_id: int, inspection_id: int) -> QcInspection:
    row = session.scalar(select(QcInspection).where(QcInspection.qc_inspection_id == inspection_id).with_for_update())
    if row is None or row.company_id != company_id:
        raise ValueError("بازرسی نامعتبر است.")
    return row


def approve(company_id: int, inspection_id: int, user_id: int, reject_warehouse_id: int | None = None,
            notes: str | None = None) -> SimpleNamespace:
    """تأیید نهایی نتیجهٔ ثبت‌شده و تعیین تکلیف موجودی. تأیید دوباره بی‌اثر است (همان نتیجه برمی‌گردد)."""
    with new_session() as session:
        row = _lock_inspection(session, company_id, inspection_id)
        if row.status_code == "APPROVED":
            return SimpleNamespace(inspection_id=row.qc_inspection_id, result_code=row.result_code,
                                   transfer_stock_document_id=row.transfer_stock_document_id, ncr_id=None, status_code="APPROVED")
        if row.status_code != "RECORDED":
            raise ValueError("این بازرسی لغو شده و قابل تأیید نیست.")
        out = _approve(session, row, user_id, reject_warehouse_id, notes)
        session.commit()
        return out


def cancel(company_id: int, inspection_id: int, user_id: int, reason: str) -> None:
    """لغو نتیجهٔ تأییدنشده (برای اصلاح پیش از تأیید). بازرسی تأییدشده لغو نمی‌شود."""
    from peecha.services.qms import common as qc_common

    if not (reason or "").strip():
        raise ValueError("علت لغو نتیجه الزامی است.")
    with new_session() as session:
        row = _lock_inspection(session, company_id, inspection_id)
        if row.status_code != "RECORDED":
            raise ValueError("فقط نتیجهٔ منتظر تأیید لغو می‌شود؛ نتیجهٔ تأییدشده با بازرسی مجدد اصلاح می‌شود.")
        if row.inspected_by_user_id != user_id:
            qc_common.require(company_id, user_id, qc_common.FORM_APPROVE, session=session)
        else:
            qc_common.require(company_id, user_id, qc_common.FORM_INSPECT, "CREATE", session=session)
        row.status_code, row.decision_notes = "CANCELLED", reason.strip()
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="QcInspection",
                                   entity_id=inspection_id, action="CANCEL", changes={"operation": "QC_CANCEL", "reason": reason.strip()})
        session.commit()


def inspect(company_id: int, line_id: int, user_id: int, rejected_quantity: decimal.Decimal = _ZERO,
            reject_warehouse_id: int | None = None, sampled_quantity: decimal.Decimal | None = None,
            notes: str | None = None) -> SimpleNamespace:
    """ثبت نتیجهٔ بازرسی یک ردیف رسید؛ مقدار ردشده به انبار قرنطینه/ضایعات منتقل می‌شود (یک تراکنش).
    با کلید «جداسازی ثبت و تأیید» فقط نتیجه ثبت می‌شود (status_code = RECORDED) و موجودی منتظر تأیید می‌ماند."""
    rejected = _dec(rejected_quantity)
    if rejected < 0:
        raise ValueError("مقدار ردشده نمی‌تواند منفی باشد.")
    with new_session() as session:
        holds = stock_reservations.active(session, SOURCE, [line_id])
        if not holds:
            raise ValueError("این ردیف منتظر کنترل کیفیت نیست.")
        held = sum((stock_reservations.remaining(r) for r in holds), _ZERO)
        if rejected > held:
            raise ValueError(f"مقدار ردشده از مقدار منتظر کنترل ({held.normalize()}) بیشتر است.")
        separate = stock_controls.is_on(company_id, stock_controls.QC_SEPARATE_APPROVAL, session)
        row = _record(session, company_id, line_id, user_id, held - rejected, rejected, _ZERO, sampled_quantity, (), notes,
                      None, None, None, log=separate)
        if separate:
            session.commit()
            return SimpleNamespace(inspection_id=row.qc_inspection_id, result_code=row.result_code,
                                   transfer_stock_document_id=None, ncr_id=None, status_code="RECORDED")
        out = _approve(session, row, user_id, reject_warehouse_id, notes, operation="QC_INSPECT")
        session.commit()
        return out


def pending_by_warehouse(company_id: int) -> dict[int, int]:
    """کارتابل: تعداد ردیف‌های منتظر کنترل کیفیت هر انبار."""
    with new_session() as session:
        rows = session.execute(select(StockReservation.warehouse_id, func.count(func.distinct(StockReservation.source_record_id)))
                               .where(StockReservation.company_id == company_id, StockReservation.source_type_code == SOURCE,
                                      StockReservation.status_code == "ACTIVE")
                               .group_by(StockReservation.warehouse_id)).all()
    return dict(rows)


# =====================================================================================
# R311: قرنطینه — موجودی، آزادسازی با مجوز، پیش‌نویس برگشت به تامین‌کننده
# =====================================================================================
def quarantine_stock(company_id: int, warehouse_id: int | None = None) -> list[SimpleNamespace]:
    """موجودی انبارهای قرنطینه و ضایعات به تفکیک کالا (مقدار، ارزش، آخرین ورود)."""
    from peecha.db.models.inventory import StockBalance
    from peecha.services.qms.labels import Names

    with new_session() as session:
        q = (select(StockBalance.warehouse_id, StockBalance.item_id, func.sum(StockBalance.quantity_on_hand),
                    func.sum(StockBalance.quantity_reserved), func.sum(StockBalance.total_value))
             .join(Warehouse, Warehouse.warehouse_id == StockBalance.warehouse_id)
             .where(StockBalance.company_id == company_id,
                    Warehouse.warehouse_type_code.in_(stock_controls.DISPOSAL_WAREHOUSE_TYPES))
             .group_by(StockBalance.warehouse_id, StockBalance.item_id))
        if warehouse_id is not None:
            q = q.where(StockBalance.warehouse_id == warehouse_id)
        names = Names(session)
        out = []
        for wh, item_id, on_hand, reserved, value in session.execute(q).all():
            if not on_hand or on_hand <= 0:
                continue
            last_in = session.scalar(select(func.max(StockLedger.movement_date)).where(
                StockLedger.item_id == item_id, StockLedger.warehouse_id == wh, StockLedger.movement_direction == "IN"))
            w = session.get(Warehouse, wh)
            out.append(SimpleNamespace(warehouse_id=wh, warehouse_name=w.name, warehouse_type=w.warehouse_type_code,
                                       item_id=item_id, item_label=names.item(item_id), quantity=decimal.Decimal(on_hand),
                                       free=decimal.Decimal(on_hand) - decimal.Decimal(reserved or 0),
                                       value=decimal.Decimal(value or 0), last_in=last_in,
                                       age_days=(datetime.date.today() - last_in).days if last_in else None))
        return sorted(out, key=lambda r: (r.warehouse_name, r.item_label))


def _lots_in_warehouse(session, item_id: int, warehouse_id: int, quantity: decimal.Decimal) -> list:
    from peecha.db.models.inventory import LotMovement, SerialNumber
    from peecha.services import lot_tracking

    rows = session.execute(
        select(LotMovement.batch_id, LotMovement.serial_id, LotMovement.supplier_detail_account_id, LotMovement.is_consignment,
               func.sum(LotMovement.quantity_base), func.min(LotMovement.movement_id))
        .where(LotMovement.item_id == item_id, LotMovement.warehouse_id == warehouse_id)
        .group_by(LotMovement.batch_id, LotMovement.serial_id, LotMovement.supplier_detail_account_id, LotMovement.is_consignment)
        .order_by(func.min(LotMovement.movement_id))).all()
    out, need = [], quantity
    for batch_id, serial_id, supplier_id, consignment, qty, _first in rows:
        if need <= 0:
            break
        qty = decimal.Decimal(qty or 0)
        if qty <= 0:
            continue
        take = min(qty, need)
        batch = session.get(Batch, batch_id) if batch_id else None
        serial = session.get(SerialNumber, serial_id) if serial_id else None
        out.append(lot_tracking.TrackingEntry(take, batch.batch_no if batch else None, batch.manufacture_date if batch else None,
                                              batch.expiry_date if batch else None, serial.serial_no if serial else None,
                                              supplier_id, consignment))
        need -= take
    if need > 0:
        raise ValueError("بچ/سریال کافی برای این مقدار در انبار قرنطینه ثبت نشده است.")
    return out


def _bins_with_free(session, item_id: int, warehouse_id: int, quantity: decimal.Decimal) -> list[tuple[int, decimal.Decimal]]:
    from peecha.db.models.inventory import StockBalance

    out, need = [], quantity
    for bal in session.scalars(select(StockBalance).where(StockBalance.item_id == item_id, StockBalance.warehouse_id == warehouse_id)
                               .order_by(StockBalance.bin_location_id).with_for_update()):
        free = decimal.Decimal(bal.quantity_on_hand) - decimal.Decimal(bal.quantity_reserved or 0)
        take = min(free, need)
        if take > 0:
            out.append((bal.bin_location_id, take))
            need -= take
        if need <= 0:
            break
    if need > 0:
        raise ValueError("موجودی آزاد این کالا در انبار قرنطینه کافی نیست.")
    return out


def release_from_quarantine(company_id: int, user_id: int, warehouse_id: int, item_id: int, quantity,
                            target_warehouse_id: int, reason: str, ncr_id: int | None = None) -> int:
    """آزادسازی مجاز کالای قرنطینه به انبار قابل‌استفاده با سند انتقال عادی (کلید «قفل انبار قرنطینه» آن را مجاز می‌داند)."""
    from peecha.services import inventory_documents as inv_docs
    from peecha.services.qms import common as qc_common

    quantity = _dec(quantity)
    if quantity <= 0:
        raise ValueError("مقدار آزادسازی باید بزرگ‌تر از صفر باشد.")
    if not (reason or "").strip():
        raise ValueError("دلیل آزادسازی (مثلاً شمارهٔ مجوز یا نتیجهٔ بازرسی مجدد) الزامی است.")
    with new_session() as session:
        qc_common.require(company_id, user_id, qc_common.FORM_RELEASE, session=session)
        src, tgt = session.get(Warehouse, warehouse_id), session.get(Warehouse, target_warehouse_id)
        if src is None or src.company_id != company_id or src.warehouse_type_code not in stock_controls.DISPOSAL_WAREHOUSE_TYPES:
            raise ValueError("انبار مبدأ باید قرنطینه یا ضایعات باشد.")
        if tgt is None or tgt.company_id != company_id or tgt.warehouse_type_code in stock_controls.DISPOSAL_WAREHOUSE_TYPES:
            raise ValueError("انبار مقصد آزادسازی باید انبار قابل‌استفاده (غیر از قرنطینه و ضایعات) باشد.")
        item = session.get(Item, item_id)
        bins = _bins_with_free(session, item_id, warehouse_id, quantity)
        entries = _lots_in_warehouse(session, item_id, warehouse_id, quantity) if (item.track_batch or item.track_serial) else []
        lines, tracking = [], {}
        for bin_id, take in bins:
            part, need = [], take
            while entries and need > 0:
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
            lines.append(inv_docs.LineFields(item_id=item_id, uom_id=item.base_uom_id, quantity=take, quantity_base=take,
                                             conversion_factor=decimal.Decimal(1), bin_location_id=bin_id,
                                             description=f"آزادسازی کیفیت: {reason.strip()}"[:250]))
        session.info["qc_release"] = True
        try:
            result, _ids = inv_docs.create_and_post_in_session(
                session, company_id, user_id, "TRANSFER", datetime.date.today(),
                inv_docs.DocumentHeaderFields(source_warehouse_id=warehouse_id, destination_warehouse_id=target_warehouse_id,
                                              reference_no="QC-REL", description=f"آزادسازی کالای قرنطینه — {reason.strip()}"[:250]),
                lines, tracking=tracking)
        finally:
            session.info.pop("qc_release", None)
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="StockDocument",
                                   entity_id=result.stock_document_id, action="EXECUTE",
                                   changes={"operation": "QC_RELEASE", "item_id": item_id, "quantity": str(quantity),
                                            "from": warehouse_id, "to": target_warehouse_id, "reason": reason.strip(),
                                            "ncr_id": ncr_id})
        session.commit()
        return result.stock_document_id


def return_to_supplier(company_id: int, user_id: int, warehouse_id: int, item_id: int, quantity, supplier_id: int,
                       unit_price=None, ncr_id: int | None = None) -> int:
    """پیش‌نویس «برگشت از خرید» از انبار قرنطینه؛ ثبت و سند مالی با همان سرویس بازرگانی (نه این‌جا)."""
    from peecha.db.models.core import Company
    from peecha.db.models.quality import Nonconformance
    from peecha.services import commercial_documents as documents_service
    from peecha.services.qms import common as qc_common

    quantity = _dec(quantity)
    if quantity <= 0:
        raise ValueError("مقدار برگشت باید بزرگ‌تر از صفر باشد.")
    with new_session() as session:
        qc_common.require(company_id, user_id, qc_common.FORM_RELEASE, session=session)
        src = session.get(Warehouse, warehouse_id)
        if src is None or src.company_id != company_id or src.warehouse_type_code not in stock_controls.DISPOSAL_WAREHOUSE_TYPES:
            raise ValueError("برگشت به تامین‌کننده از انبار قرنطینه یا ضایعات انجام می‌شود.")
        _bins_with_free(session, item_id, warehouse_id, quantity)
        item = session.get(Item, item_id)
        currency_id = session.get(Company, company_id).base_currency_id
        if unit_price is None:
            unit_price = session.scalar(select(StockLedger.unit_cost).join(
                StockDocumentLine, StockDocumentLine.line_id == StockLedger.stock_document_line_id).join(
                StockDocument, StockDocument.stock_document_id == StockDocumentLine.stock_document_id).where(
                StockLedger.item_id == item_id, StockLedger.movement_direction == "IN", StockDocument.document_type_code == "RECEIPT",
                StockDocument.counterparty_detail_account_id == supplier_id).order_by(StockLedger.ledger_id.desc()).limit(1)) or _ZERO
    doc_id = documents_service.create_document(company_id, user_id, "PURCHASE_RETURN", datetime.date.today(),
                                               documents_service.DocumentHeaderFields(
                                                   counterparty_detail_account_id=supplier_id, currency_id=currency_id,
                                                   warehouse_id=warehouse_id,
                                                   description=f"برگشت کالای مردود کیفیت{f' — عدم‌انطباق #{ncr_id}' if ncr_id else ''}"))
    documents_service.add_line(doc_id, company_id, item_id, item.base_uom_id, quantity, quantity, unit_price=_dec(unit_price),
                               warehouse_id=warehouse_id, description="مردود در کنترل کیفیت")
    with new_session() as session:
        if ncr_id:
            ncr = session.get(Nonconformance, ncr_id)
            if ncr is not None and ncr.company_id == company_id and ncr.status_code not in ("CLOSED", "CANCELLED"):
                before = ncr.disposition_code
                ncr.disposition_code = "RETURN_TO_SUPPLIER"
                audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="Nonconformance",
                                           entity_id=ncr_id, action="UPDATE",
                                           changes={"disposition_code": [before, "RETURN_TO_SUPPLIER"], "purchase_return_id": doc_id})
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="CommercialDocument",
                                   entity_id=doc_id, action="CREATE",
                                   changes={"operation": "QC_RETURN_TO_SUPPLIER", "item_id": item_id, "quantity": str(quantity),
                                            "warehouse_id": warehouse_id, "ncr_id": ncr_id})
        session.commit()
    return doc_id
