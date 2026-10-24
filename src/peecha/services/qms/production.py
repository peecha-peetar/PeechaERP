"""کیفیت تولید (کلید QC_PRODUCTION).

- بازرسی حین تولید/بین مراحل روی عملیات دستور تولید (بدون جابه‌جایی موجودی): پذیرفته، مردود، دوباره‌کاری.
- رسید محصول نهایی با همان نگه‌داشت QC_HOLD کنترل می‌شود (quality_control.hold_production_receipt) و با همان ثبت/تأیید
  ردیف رسید تعیین تکلیف می‌شود (پذیرش، انتقال به ضایعات/قرنطینه، دوباره‌کاری = نگه‌داشت، مصرف مشروط).
- عملیاتی که کنترل کیفیت اجباری دارد (عملیات مسیر با «کنترل کیفیت» یا طرح حین تولید اجباری) بدون بازرسی تأییدشده
  تمام نمی‌شود و دستور با بازرسی باز یا محصول نگه‌داشته بسته نمی‌شود.
"""

from __future__ import annotations

import decimal
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import QcInspection, StockDocumentLine
from peecha.db.models.production import Operation, OrderOperation, OrderTransaction, ProductionOrder, RoutingOperation
from peecha.services import audit as audit_service
from peecha.services import stock_controls
from peecha.services.qms import common as c

_ZERO = decimal.Decimal(0)
_WORKING = ("RELEASED", "IN_PROGRESS", "ON_HOLD")


def enabled(company_id: int, session=None) -> bool:
    return c.is_on(company_id, stock_controls.QC_PRODUCTION, session) and c.is_on(company_id, stock_controls.QC_HOLD, session)


def operation_requirement(session, order: ProductionOrder, op: OrderOperation) -> SimpleNamespace:
    """(اجباری؟، طرح حین تولید) برای یک عملیات دستور."""
    from peecha.services.qms import plans

    ro = session.scalar(select(RoutingOperation).where(RoutingOperation.routing_id == order.routing_id,
                                                       RoutingOperation.seq == op.seq)) if order.routing_id else None
    operation_id = ro.operation_id if ro else None
    flagged = bool(ro and (ro.is_qc or (operation_id and session.get(Operation, operation_id).is_qc)))
    plan = plans.find_plan(session, order.company_id, "IN_PROCESS", order.item_id, work_center_id=op.work_center_id,
                           operation_id=operation_id)
    return SimpleNamespace(required=flagged or bool(plan and plan.is_mandatory), plan=plan, operation_id=operation_id)


def record_operation_result(company_id: int, order_operation_id: int, user_id: int, *, accepted, rejected=_ZERO,
                            rework=_ZERO, sampled=None, results=(), notes: str | None = None, plan_id: int | None = None,
                            idempotency_key: str | None = None) -> int:
    """نتیجهٔ بازرسی حین تولید؛ جمع بازرسی‌شدهٔ عملیات از مقدار دستور بیشتر نمی‌شود."""
    from peecha.services import quality_control as qc

    accepted, rejected, rework = (decimal.Decimal(str(accepted or 0)), decimal.Decimal(str(rejected or 0)),
                                  decimal.Decimal(str(rework or 0)))
    with new_session() as session:
        if idempotency_key:
            done = session.scalar(select(QcInspection.qc_inspection_id).where(QcInspection.company_id == company_id,
                                                                              QcInspection.idempotency_key == idempotency_key))
            if done:
                return done
        c.require(company_id, user_id, c.FORM_INSPECT, "CREATE", session=session)
        op = session.scalar(select(OrderOperation).where(OrderOperation.order_operation_id == order_operation_id).with_for_update())
        order = session.get(ProductionOrder, op.order_id) if op else None
        if order is None or order.company_id != company_id:
            raise ValueError("عملیات دستور تولید نامعتبر است.")
        if order.status_code not in _WORKING:
            raise ValueError("بازرسی حین تولید فقط برای دستور صادرشده یا در حال تولید ثبت می‌شود.")
        if min(accepted, rejected, rework) < 0:
            raise ValueError("مقدارها نمی‌توانند منفی باشند.")
        total = accepted + rejected + rework
        if total <= 0:
            raise ValueError("مقدار بازرسی‌شده صفر است.")
        before = decimal.Decimal(session.scalar(select(func.coalesce(func.sum(
            func.coalesce(QcInspection.accepted_quantity, 0) + func.coalesce(QcInspection.rejected_quantity, 0)), 0)).where(
            QcInspection.order_operation_id == order_operation_id, QcInspection.status_code == "APPROVED")) or 0)
        if before + total > decimal.Decimal(order.planned_qty):
            raise ValueError(f"جمع بازرسی این عملیات از مقدار دستور ({decimal.Decimal(order.planned_qty).normalize():f}) بیشتر می‌شود.")
        if sampled not in (None, "") and decimal.Decimal(str(sampled)) > total:
            raise ValueError("مقدار نمونه از مقدار بازرسی‌شده بیشتر است.")
        if session.scalar(select(QcInspection.qc_inspection_id).where(QcInspection.order_operation_id == order_operation_id,
                                                                      QcInspection.status_code == "RECORDED")):
            raise ValueError("برای این عملیات نتیجهٔ منتظر تأیید ثبت شده است.")
        req = operation_requirement(session, order, op)
        plan = qc._resolve_plan(session, company_id, "IN_PROCESS", order.item_id, plan_id, work_center_id=op.work_center_id,
                                operation_id=req.operation_id) if plan_id else req.plan
        code = qc._result_code(total, accepted, rejected, rework)
        disp = "REWORK" if rework > 0 else qc._disposition(code, None, _ZERO, accepted)
        previous = session.scalar(select(QcInspection.qc_inspection_id).where(
            QcInspection.order_operation_id == order_operation_id, QcInspection.status_code == "APPROVED")
            .order_by(QcInspection.qc_inspection_id.desc()).limit(1))
        row = QcInspection(company_id=company_id, inspected_by_user_id=user_id, result_code=code, stage_code="IN_PROCESS",
                           status_code="RECORDED", plan_id=plan.plan_id if plan else None, lot_quantity=total,
                           accepted_quantity=accepted, rejected_quantity=rejected, pending_quantity=rework,
                           sampled_quantity=decimal.Decimal(str(sampled)) if sampled not in (None, "") else None,
                           disposition_code=disp, production_order_id=order.order_id, order_operation_id=order_operation_id,
                           reinspection_of_id=previous, notes=(notes or "").strip() or None, idempotency_key=idempotency_key)
        session.add(row)
        session.flush()
        defective = qc._write_results(session, row, plan, results, user_id)
        qc._check_plan_verdict(plan, defective, rejected, rework, disp)
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="QcInspection",
                                   entity_id=row.qc_inspection_id, action="CREATE",
                                   changes={"operation": "QC_RECORD", "stage": "IN_PROCESS", "order_id": order.order_id,
                                            "order_operation_id": order_operation_id, "accepted": str(accepted),
                                            "rejected": str(rejected), "rework": str(rework), "plan_id": row.plan_id})
        session.commit()
        return row.qc_inspection_id


def check_operation_gate(session, order: ProductionOrder, op: OrderOperation) -> None:
    """پیش از «انجام‌شده» شدن عملیات: کنترل اجباری بدون بازرسی تأییدشده با مقدار پذیرفته = رد."""
    if not enabled(order.company_id, session):
        return
    if not operation_requirement(session, order, op).required:
        return
    last = session.scalar(select(QcInspection).where(QcInspection.order_operation_id == op.order_operation_id,
                                                     QcInspection.status_code != "CANCELLED")
                          .order_by(QcInspection.qc_inspection_id.desc()).limit(1))
    if last is None or last.status_code != "APPROVED" or last.disposition_code in ("PENDING", "REWORK") \
            or not decimal.Decimal(last.accepted_quantity or 0):
        raise ValueError(f"عملیات «{op.name}» کنترل کیفیت اجباری دارد و بازرسی تأییدشده با مقدار پذیرفته ندارد.")


def order_quality_issues(session, order: ProductionOrder) -> list[str]:
    """موارد باز کیفیت یک دستور (برای فهرست بستن دستور)."""
    from peecha.services import quality_control as qc

    if not enabled(order.company_id, session):
        return []
    issues = []
    doc_ids = set(session.scalars(select(OrderTransaction.stock_document_id).where(
        OrderTransaction.order_id == order.order_id, OrderTransaction.stock_document_id.is_not(None))))
    line_ids = list(session.scalars(select(StockDocumentLine.line_id).where(StockDocumentLine.stock_document_id.in_(doc_ids or {-1}))))
    held = qc.waiting_line_ids(session, line_ids)
    if held:
        issues.append(f"{len(held)} ردیف محصول منتظر بازرسی نهایی")
    open_rows = session.scalar(select(func.count()).select_from(QcInspection).where(
        QcInspection.production_order_id == order.order_id, QcInspection.status_code == "RECORDED"))
    if open_rows:
        issues.append(f"{open_rows} نتیجهٔ کیفیت منتظر تأیید")
    return issues


def operations_for_order(company_id: int, order_id: int) -> list[SimpleNamespace]:
    """عملیات دستور با وضعیت کنترل کیفیت (برای صفحهٔ کیفیت)."""
    with new_session() as session:
        order = session.get(ProductionOrder, order_id)
        if order is None or order.company_id != company_id:
            raise ValueError("دستور تولید نامعتبر است.")
        out = []
        for op in session.scalars(select(OrderOperation).where(OrderOperation.order_id == order_id).order_by(OrderOperation.seq)):
            req = operation_requirement(session, order, op)
            last = session.scalar(select(QcInspection).where(QcInspection.order_operation_id == op.order_operation_id,
                                                             QcInspection.status_code != "CANCELLED")
                                  .order_by(QcInspection.qc_inspection_id.desc()).limit(1))
            out.append(SimpleNamespace(order_operation_id=op.order_operation_id, seq=op.seq, name=op.name, status_code=op.status_code,
                                       required=req.required, plan_id=req.plan.plan_id if req.plan else None,
                                       plan_name=req.plan.name if req.plan else "",
                                       last_inspection_id=last.qc_inspection_id if last else None,
                                       last_status=c.STATUS_LABELS[last.status_code] if last else "",
                                       last_result=c.RESULT_LABELS.get(last.result_code, "") if last else ""))
        return out
