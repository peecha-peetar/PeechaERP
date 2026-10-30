"""R311: کیفیت تولید — بازرسی حین تولید روی عملیات (پذیرفته/مردود/دوباره‌کاری)، قفل انجام عملیات کنترل‌دار، نگه‌داشت
رسید محصول تا بازرسی نهایی، انتقال مردود به ضایعات با همان موتور انبار و جلوگیری از بستن دستور با کیفیت باز."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r311b"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403
import prd_fixture as fx

from peecha.services.production import common as pc, master as pm, orders as po
from peecha.services import quality_control as qc
from peecha.services import stock_controls as sc
from peecha.services.qms import ncr, plans, production as qprod, queries
from peecha.services.qms import reports as qrep
from peecha.services.purchase_reports import PurchaseFilters
from peecha.db.models.inventory import QcInspection
check, raises = fx.check, fx.raises
RI = qc.ResultInput

wh_q = locations_service.create_warehouse(company_id, "SCR-Q", "ضایعات کیفیت", WF(warehouse_type_code="SCRAP"))
pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg, default_scrap_warehouse_id=wh_scrap)
BF, BL, WCF, RO = pm.BomFields, pm.BomLineFields, pm.WorkCenterFields, pm.RoutingOpFields
wc = pm.save_work_center(company_id, WCF(code="CUT", name="برش", labor_rate=D(100000)))
wq = pm.save_work_center(company_id, WCF(code="QCS", name="ایستگاه کنترل", labor_rate=D(100000)))
rt = pm.create_routing(company_id, fg, "مسیر با کنترل", [RO(10, "برش", wc, run_minutes=D(1)),
                                                         RO(20, "کنترل ابعاد", wq, run_minutes=D(1), is_qc=True)])
bom = pm.create_bom_version(company_id, fg, BF(batch_size_qty=D(1), routing_id=rt))
pm.add_bom_component(company_id, bom, BL(r1, D(1)))
receive(r1, 1000, 10000)
switch = lambda code, on=True: engine_service.set_feature_enabled(company_id, code, on)  # noqa: E731


def new_order(qty):
    oid = po.create_order(company_id, uid, po.OrderFields(item_id=fg, planned_qty=D(qty)))
    po.release_order(company_id, uid, oid)
    po.start_order(company_id, uid, oid)
    po.issue_all_remaining(company_id, uid, oid)
    return oid


def ops(oid):
    return {o.name: o for o in qprod.operations_for_order(company_id, oid)}


def row(i):
    with new_session() as s:
        r = s.get(QcInspection, i)
        s.expunge(r)
        return r


# ===== ۱) کلید خاموش: رفتار قبلی =====
oa = new_order(5)
op_qc = ops(oa)["کنترل ابعاد"]
po.set_operation_status(company_id, uid, op_qc.order_operation_id, "DONE")
po.report_production(company_id, uid, oa, po.ReceiptInput(quantity=D(5)))
po.complete_order(company_id, uid, oa)
check(qc.list_pending(company_id) == [] and len(po.closing_checklist(company_id, oa)) == 9, "switch off: no hold, checklist unchanged")
po.close_order(company_id, uid, oa)
check(po.get_order(company_id, oa).status_code == "CLOSED", "switch off: order closes as before")

# ===== ۲) کلیدها روشن + طرح بازرسی نهایی =====
switch(sc.RESERVATION)
switch(sc.QC_HOLD)
switch(sc.QC_PRODUCTION)
PF, PP = plans.PlanFields, plans.ParameterFields
check(raises(lambda: plans.create_plan(company_id, uid, PF("IP", "حین تولید", "IN_PROCESS"), [PP("ابعاد")]), "حین تولید"),
      "in-process plan must be tied to an item, work center or operation")
ip = plans.create_plan(company_id, uid, PF("IP", "کنترل ابعاد", "IN_PROCESS", item_id=fg, work_center_id=wq),
                       [PP("طول", "NUMERIC", "میلی‌متر", D(99), D(101))])
plans.activate_plan(company_id, uid, ip)
fp = plans.create_plan(company_id, uid, PF("FP", "بازرسی نهایی", "FINAL", item_id=fg), [PP("ظاهر", "PASS_FAIL")])
plans.activate_plan(company_id, uid, fp)
ip_len = plans.get_plan(company_id, ip).parameters[0].parameter_id
fp_look = plans.get_plan(company_id, fp).parameters[0].parameter_id

ob = new_order(10)
o = ops(ob)
op_cut, op_qc = o["برش"], o["کنترل ابعاد"]
check(op_qc.required and not op_cut.required and op_qc.plan_id == ip, "QC operation is mandatory and finds its in-process plan")
po.set_operation_status(company_id, uid, op_cut.order_operation_id, "DONE")
check(raises(lambda: po.set_operation_status(company_id, uid, op_qc.order_operation_id, "DONE"), "کنترل کیفیت اجباری"),
      "mandatory QC operation cannot be closed without an approved inspection")
check(raises(lambda: qprod.record_operation_result(company_id, op_qc.order_operation_id, uid, accepted=D(11)), "بیشتر"),
      "inspected quantity cannot exceed the order quantity")
check(raises(lambda: qprod.record_operation_result(company_id, op_qc.order_operation_id, uid, accepted=D(8)), "اجباری"),
      "plan parameters are required")
i1 = qprod.record_operation_result(company_id, op_qc.order_operation_id, uid, accepted=D(7), rejected=D(1), rework=D(2),
                                   results=[RI(D(100), ip_len), RI(D("101.5"), ip_len, sample_no=2)], idempotency_key="OP-1")
check(qprod.record_operation_result(company_id, op_qc.order_operation_id, uid, accepted=D(7), rejected=D(1), rework=D(2),
                                    results=[RI(D(100), ip_len)], idempotency_key="OP-1") == i1, "idempotent operation inspection")
r1 = row(i1)
check(r1.stage_code == "IN_PROCESS" and r1.status_code == "RECORDED" and r1.disposition_code == "REWORK"
      and r1.production_order_id == ob and r1.order_operation_id == op_qc.order_operation_id, "in-process result linked to order and operation")
check(raises(lambda: po.set_operation_status(company_id, uid, op_qc.order_operation_id, "DONE"), "کنترل کیفیت اجباری"),
      "unapproved result keeps the operation open")
qc.approve(company_id, i1, uid)
check(row(i1).status_code == "APPROVED" and row(i1).transfer_stock_document_id is None, "operation inspection approved (no stock move)")
check(raises(lambda: po.set_operation_status(company_id, uid, op_qc.order_operation_id, "DONE"), "کنترل کیفیت اجباری"),
      "rework pending: operation still blocked")
check(raises(lambda: qprod.record_operation_result(company_id, op_qc.order_operation_id, uid, accepted=D(3),
                                                   results=[RI(D(100), ip_len)]), "بیشتر"),
      "cumulative inspected quantity cannot exceed the order (8 decided + 3 > 10)")
i2 = qprod.record_operation_result(company_id, op_qc.order_operation_id, uid, accepted=D(2), results=[RI(D(100), ip_len)])
check(row(i2).reinspection_of_id == i1, "rework re-inspection linked to the previous result")
qc.approve(company_id, i2, uid)
po.set_operation_status(company_id, uid, op_qc.order_operation_id, "DONE")
check(ops(ob)["کنترل ابعاد"].status_code == "DONE", "approved inspection with accepted quantity opens the gate")
auto = [n for n in ncr.list_ncrs(company_id) if n.qc_inspection_id == i1]
check(len(auto) == 1 and auto[0].source_code == "IN_PROCESS", "in-process rejection opened an NCR")

# ===== ۳) نگه‌داشت رسید محصول تا بازرسی نهایی =====
po.report_production(company_id, uid, ob, po.ReceiptInput(quantity=D(9)))
pend = [p for p in qc.list_pending(company_id) if p.production_order_id == ob]
check(len(pend) == 1 and pend[0].stage_code == "FINAL" and pend[0].quantity == 9 and on_hand(fg, wh_fg) == 14,
      "finished goods received but held for final inspection")


def issue_fg(qty):
    d = inv_documents_service.create_stock_document(company_id, uid, "ISSUE", today,
                                                    inv_documents_service.DocumentHeaderFields(source_warehouse_id=wh_fg))
    inv_documents_service.add_line(d, company_id, inv_documents_service.LineFields(item_id=fg, uom_id=pcs, quantity=D(qty),
                                                                                   quantity_base=D(qty)))
    inv_documents_service.confirm_stock_document(d, company_id)
    inv_documents_service.post_stock_document(d, company_id, uid)


check(raises(lambda: issue_fg(6)) and on_hand(fg, wh_fg) == 14, "held product cannot be issued before release (only 5 free)")
po.complete_order(company_id, uid, ob)
checklist = {x.key: x for x in po.closing_checklist(company_id, ob)}
check(len(checklist) == 10 and not checklist["QUALITY"].ok and "بازرسی نهایی" in checklist["QUALITY"].note,
      "closing checklist shows the open final inspection")
check(raises(lambda: po.close_order(company_id, uid, ob), "کنترل کیفیت"), "order with open quality cannot be closed")
check(raises(lambda: qc.record_result(company_id, pend[0].line_id, uid, accepted=D(9)), "اجباری"), "final plan parameter required")
f1 = qc.record_result(company_id, pend[0].line_id, uid, accepted=D(8), rejected=D(1), results=[RI(True, fp_look)])
check(row(f1).stage_code == "FINAL" and row(f1).production_order_id == ob and row(f1).plan_id == fp, "final inspection recorded")
check(raises(lambda: po.close_order(company_id, uid, ob), "کنترل کیفیت"), "unapproved final result still blocks closing")
qc.approve(company_id, f1, uid, wh_q)
check(on_hand(fg, wh_fg) == 13 and on_hand(fg, wh_q) == 1 and qc.list_pending(company_id) == [],
      "final approval released 8 and moved 1 to scrap through the stock engine")
issue_fg(1)
check(on_hand(fg, wh_fg) == 12, "released product can be issued")
po.close_order(company_id, uid, ob)
check(po.get_order(company_id, ob).status_code == "CLOSED", "order closes after quality is settled")

# ===== ۴) مصرف مشروط =====
oc = new_order(4)
for name, op in ops(oc).items():
    if name == "کنترل ابعاد":
        ic = qprod.record_operation_result(company_id, op.order_operation_id, uid, accepted=D(4), results=[RI(D(100), ip_len)])
        qc.approve(company_id, ic, uid)
    po.set_operation_status(company_id, uid, op.order_operation_id, "DONE")
po.report_production(company_id, uid, oc, po.ReceiptInput(quantity=D(4)))
lc = [p for p in qc.list_pending(company_id) if p.production_order_id == oc][0]
check(raises(lambda: qc.record_result(company_id, lc.line_id, uid, accepted=D(4), results=[RI(False, fp_look)]), "مصرف مشروط"),
      "defect above acceptance number needs rejection or concession")
cc = qc.record_result(company_id, lc.line_id, uid, accepted=D(4), results=[RI(False, fp_look)], disposition="CONCESSION",
                      notes="خراش جزئی، با موافقت مشتری")
qc.approve(company_id, cc, uid)
check(row(cc).disposition_code == "CONCESSION" and on_hand(fg, wh_fg) == 16 and qc.list_pending(company_id) == [],
      "concession releases the lot with a recorded decision")

# ===== ۵) گزارش و صفحه =====
f = PurchaseFilters(today - datetime.timedelta(days=1), today, side="INVENTORY", options={"stage": "ALL", "status": "ALL"})
prod = qrep.production_quality(company_id, f)
check(len(prod.rows) >= 3 and any(r[2] == "محصول نهایی" for r in prod.rows) and any(r[3] == "کنترل ابعاد" for r in prod.rows),
      "production quality report by order and operation")
f_wc = PurchaseFilters(f.date_from, f.date_to, side="INVENTORY", work_center_id=wq, options={"stage": "IN_PROCESS", "status": "ALL"})
check(len(qrep.inspection_log(company_id, f_wc).rows) == 3, "work-center filter on the inspection log")

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from peecha.ui.screens import quality as ui
od = new_order(3)
q = ui.InspectionQueueScreen()
warnings = []
q.warn = warnings.append
q.refresh()
ui.set_combo(q.order_box, od)
check(q.t_ops.rowCount() == 2 and q.t_ops.item(1, 3).text() == "بله", "queue lists the order's operations with the QC flag")
q.t_ops.selectRow(1)


def op_result(dlg):
    dlg.set_value(0, "100")
    dlg.accepted.setText("3")
    return True


q.dialog_runner = op_result
iu = q.record_operation()
check(iu and row(iu).status_code == "APPROVED" and not warnings,
      f"in-process result from the screen (approved at once without separation) {warnings}")

finish()
