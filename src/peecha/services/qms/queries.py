"""خواندن بازرسی‌ها برای صف، کارت و گزارش (بدون نوشتن)."""

from __future__ import annotations

import datetime
import decimal
from types import SimpleNamespace

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.inventory import QcInspection, StockDocument, StockDocumentLine
from peecha.db.models.production import OrderOperation, ProductionOrder
from peecha.db.models.quality import InspectionPlan, InspectionResult
from peecha.services.qms import common as c
from peecha.services.qms.labels import Names

_ZERO = decimal.Decimal(0)


def _row(session, names: Names, q: QcInspection) -> SimpleNamespace:
    doc = ln = order = op = None
    if q.stock_document_line_id:
        ln = session.get(StockDocumentLine, q.stock_document_line_id)
        doc = session.get(StockDocument, ln.stock_document_id)
    if q.production_order_id:
        order = session.get(ProductionOrder, q.production_order_id)
    if q.order_operation_id:
        op = session.get(OrderOperation, q.order_operation_id)
    item_id = ln.item_id if ln else (order.item_id if order else None)
    plan = session.get(InspectionPlan, q.plan_id) if q.plan_id else None
    return SimpleNamespace(
        inspection_id=q.qc_inspection_id, stage_code=q.stage_code, stage_label=c.STAGE_LABELS[q.stage_code],
        status_code=q.status_code, status_label=c.STATUS_LABELS[q.status_code], result_code=q.result_code,
        result_label=c.RESULT_LABELS.get(q.result_code, q.result_code),
        disposition_label=c.DISPOSITION_LABELS.get(q.disposition_code or "", ""), disposition_code=q.disposition_code,
        inspected_at=q.inspected_at, approved_at=q.approved_at, inspector=names.user(q.inspected_by_user_id),
        inspected_by_user_id=q.inspected_by_user_id, approver=names.user(q.approved_by_user_id),
        item_id=item_id, item_label=names.item(item_id), line_id=q.stock_document_line_id,
        document_no=doc.document_no if doc else None, document_type_code=doc.document_type_code if doc else None,
        stock_document_id=doc.stock_document_id if doc else None, warehouse_id=doc.destination_warehouse_id if doc else None,
        warehouse_name=names.warehouse(doc.destination_warehouse_id) if doc else "",
        party_id=doc.counterparty_detail_account_id if doc else None,
        party_label=names.party(doc.counterparty_detail_account_id) if doc else "",
        order_id=order.order_id if order else None, order_code=order.order_code if order else "",
        work_center_id=(op.work_center_id if op else (order.work_center_id if order else None)),
        operation_name=op.name if op else "", plan_label=f"{plan.code} (نسخهٔ {plan.version_no})" if plan else "",
        lot=decimal.Decimal(q.lot_quantity) if q.lot_quantity is not None else None,
        accepted=decimal.Decimal(q.accepted_quantity) if q.accepted_quantity is not None else None,
        rejected=decimal.Decimal(q.rejected_quantity or 0), pending=decimal.Decimal(q.pending_quantity or 0),
        sampled=q.sampled_quantity, notes=q.notes or "", decision_notes=q.decision_notes or "",
        transfer_stock_document_id=q.transfer_stock_document_id, reinspection_of_id=q.reinspection_of_id)


def list_inspections(company_id: int, *, status: str | None = None, stage: str | None = None,
                     date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                     limit: int = 1000) -> list[SimpleNamespace]:
    with new_session() as session:
        q = select(QcInspection).where(QcInspection.company_id == company_id)
        if status:
            q = q.where(QcInspection.status_code == status)
        if stage:
            q = q.where(QcInspection.stage_code == stage)
        if date_from:
            q = q.where(QcInspection.inspected_at >= datetime.datetime.combine(date_from, datetime.time.min))
        if date_to:
            q = q.where(QcInspection.inspected_at < datetime.datetime.combine(date_to + datetime.timedelta(days=1), datetime.time.min))
        names = Names(session)
        return [_row(session, names, r) for r in session.scalars(q.order_by(QcInspection.qc_inspection_id.desc()).limit(limit))]


def inspection_detail(company_id: int, inspection_id: int) -> SimpleNamespace:
    from peecha.services.qms import ncr

    with new_session() as session:
        q = session.get(QcInspection, inspection_id)
        if q is None or q.company_id != company_id:
            raise ValueError("بازرسی نامعتبر است.")
        names = Names(session)
        head = _row(session, names, q)
        results = [SimpleNamespace(sample_no=r.sample_no, name=r.parameter_name, data_type=r.data_type,
                                   data_type_label=c.DATA_TYPE_LABELS[r.data_type], unit=r.uom_label or "",
                                   min_value=r.min_value, max_value=r.max_value, target_value=r.target_value,
                                   value=(r.value_numeric if r.data_type == "NUMERIC" else
                                          (("قبول" if r.value_bool else "رد") if r.data_type == "PASS_FAIL" and r.value_bool is not None
                                           else r.value_text)),
                                   conforming=r.is_conforming, mandatory=r.is_mandatory)
                   for r in session.scalars(select(InspectionResult).where(InspectionResult.qc_inspection_id == inspection_id)
                                            .order_by(InspectionResult.sample_no, InspectionResult.result_id))]
    return SimpleNamespace(header=head, results=results, history=ncr.history("QcInspection", inspection_id))


def _plan_view(session, plan, lot) -> SimpleNamespace | None:
    from peecha.db.models.quality import PlanParameter
    from peecha.services.qms import plans

    if plan is None:
        return None
    params = list(session.scalars(select(PlanParameter).where(PlanParameter.plan_id == plan.plan_id).order_by(PlanParameter.seq)))
    return SimpleNamespace(plan_id=plan.plan_id, code=plan.code, name=plan.name, version_no=plan.version_no,
                           acceptance_number=plan.acceptance_number, sampling_label=c.SAMPLING_LABELS[plan.sampling_method],
                           suggested_sample=plans.sample_size(plan, lot) if lot is not None else None,
                           parameters=[SimpleNamespace(parameter_id=p.parameter_id, name=p.name, data_type=p.data_type,
                                                       uom_label=p.uom_label or "", min_value=p.min_value, max_value=p.max_value,
                                                       target_value=p.target_value, options=p.options or [],
                                                       test_method=p.test_method or "", is_mandatory=p.is_mandatory)
                                       for p in params])


def plan_for_line(company_id: int, line_id: int, plan_id: int | None = None, lot=None) -> SimpleNamespace | None:
    """طرحی که ثبت نتیجهٔ این ردیف به آن بسته می‌شود (همان انتخاب سرویس ثبت؛ بدون نوشتن)."""
    from peecha.services import quality_control as qc

    with new_session() as session:
        ln = session.get(StockDocumentLine, line_id)
        doc = session.get(StockDocument, ln.stock_document_id) if ln else None
        if doc is None or doc.company_id != company_id:
            raise ValueError("ردیف رسید نامعتبر است.")
        stage, order_id = qc.source_of(session, doc)
        order = session.get(ProductionOrder, order_id) if order_id else None
        plan = qc._resolve_plan(session, company_id, stage, ln.item_id, plan_id,
                                supplier_id=doc.counterparty_detail_account_id if stage == "RECEIPT" else None,
                                work_center_id=order.work_center_id if order else None, doc_type=doc.document_type_code)
        return _plan_view(session, plan, lot)


def plan_for_operation(company_id: int, order_operation_id: int, plan_id: int | None = None) -> SimpleNamespace | None:
    from peecha.services import quality_control as qc
    from peecha.services.qms import production

    with new_session() as session:
        op = session.get(OrderOperation, order_operation_id)
        order = session.get(ProductionOrder, op.order_id) if op else None
        if order is None or order.company_id != company_id:
            raise ValueError("عملیات دستور تولید نامعتبر است.")
        req = production.operation_requirement(session, order, op)
        plan = qc._resolve_plan(session, company_id, "IN_PROCESS", order.item_id, plan_id, work_center_id=op.work_center_id,
                                operation_id=req.operation_id) if plan_id else req.plan
        return _plan_view(session, plan, None)


def active_plans(company_id: int, stage: str) -> list[tuple[str, int]]:
    with new_session() as session:
        return [(f"{p.code} — {p.name} (نسخهٔ {p.version_no})", p.plan_id) for p in session.scalars(
            select(InspectionPlan).where(InspectionPlan.company_id == company_id, InspectionPlan.stage_code == stage,
                                         InspectionPlan.status_code == "ACTIVE").order_by(InspectionPlan.code))]


def open_orders(company_id: int) -> list[tuple[str, int]]:
    from peecha.services.qms.labels import Names

    with new_session() as session:
        names = Names(session)
        return [(f"{o.order_code} — {names.item(o.item_id)}", o.order_id) for o in session.scalars(
            select(ProductionOrder).where(ProductionOrder.company_id == company_id,
                                          ProductionOrder.status_code.in_(("RELEASED", "IN_PROGRESS", "ON_HOLD")))
            .order_by(ProductionOrder.order_code))]
