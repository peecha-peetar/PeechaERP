"""R311: سیستم مدیریت کیفیت — رسید خرید: طرح نسخه‌دار با پارامتر، ثبت/تأیید جدا، سقف مقدار، بازرسی مجدد، قرنطینه،
عدم‌انطباق و اقدام اصلاحی، امتیاز تامین‌کننده، دسترسی نقش‌ها، گزارش‌ها، داشبورد و صفحه‌ها."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r311a"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from sqlalchemy import func, text, update
from sqlalchemy.exc import DBAPIError
from peecha.services import inventory_documents as inv_docs
from peecha.services import quality_control as qc
from peecha.services import roles as roles_service
from peecha.services import stock_controls as sc
from peecha.services.qms import common as qcm
from peecha.services.qms import dashboard as qdash
from peecha.services.qms import ncr
from peecha.services.qms import plans
from peecha.services.qms import queries
from peecha.services.qms import reports as qrep
from peecha.services.qms import scoring
from peecha.services.purchase_reports import PurchaseFilters
from peecha.db.models.audit import ActivityLog
from peecha.db.models.inventory import Item, QcInspection, StockBalance, StockDocument
from peecha.db.models.quality import CapaAction, InspectionResult, Nonconformance
check, raises = fx.check, fx.raises
RI = qc.ResultInput

g_l = A("2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False)
k_l = A("21", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g_l.account_id)
ap_gl = A("2101", "پرداختنی تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k_l.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)
adj_gl = A("512", "اختلاف انبار", "DEBIT", "EXPENSE", "TEMPORARY", True, k5.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ADJUSTMENT_GAIN", adj_gl.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ADJUSTMENT_LOSS", adj_gl.account_id)
sup1 = dimensions_service.create_supplier(company_id, "S1", "تامین‌کنندهٔ یک")
sup2 = dimensions_service.create_supplier(company_id, "S2", "تامین‌کنندهٔ دو")
approver = visitor.user_id
WF = locations_service.WarehouseFields
whn = locations_service.create_warehouse(company_id, "WH-N", "انبار اصلی", WF())
whq = locations_service.create_warehouse(company_id, "WH-Q", "انبار قرنطینه", WF(warehouse_type_code="QUARANTINE"))
med = catalog_service.create_item(company_id, "M1", "داروی الف", IF(item_kind_code="GOOD", base_uom_id=pcs, is_sellable=True))
bolt = catalog_service.create_item(company_id, "M2", "پیچ", IF(item_kind_code="GOOD", base_uom_id=pcs, is_sellable=True))
with new_session() as s:
    s.execute(update(Item).where(Item.item_id.in_([med, bolt])).values(requires_qc=True))
    s.commit()


def receipt(item, qty, supplier=sup1, cost=1000):
    d = inv_docs.create_stock_document(company_id, uid, "RECEIPT", today, inv_docs.DocumentHeaderFields(
        destination_warehouse_id=whn, counterparty_detail_account_id=supplier))
    line = inv_docs.add_line(d, company_id, inv_docs.LineFields(item_id=item, uom_id=pcs, quantity=D(qty), quantity_base=D(qty),
                                                                unit_cost=D(cost)))
    inv_docs.confirm_stock_document(d, company_id)
    inv_docs.post_stock_document(d, company_id, uid)
    return d, line


def stock(item, warehouse, field="quantity_on_hand"):
    with new_session() as s:
        return D(s.scalar(select(func.coalesce(func.sum(getattr(StockBalance, field)), 0)).where(
            StockBalance.item_id == item, StockBalance.warehouse_id == warehouse)) or 0)


def held(line_id):
    return next((p.quantity for p in qc.list_pending(company_id) if p.line_id == line_id), D(0))


def blocked(sql, **params):
    try:
        with new_session() as s:
            s.execute(text(sql), params)
            s.commit()
    except DBAPIError as exc:
        return "LOCKED" in str(exc)
    return False


def row(inspection_id):
    with new_session() as s:
        r = s.get(QcInspection, inspection_id)
        s.expunge(r)
        return r


switch = lambda code, on=True: engine_service.set_feature_enabled(company_id, code, on)  # noqa: E731

# ===== ۱) کلیدها: همه خاموش، وابسته به نگه‌داشت رسید =====
feats = {f.feature_code: f for f in engine_service.list_features(company_id)}
check(all(feats[k].category == "QUALITY" and not feats[k].is_enabled for k in sc.QC_ALL), "five quality switches, all off by default")
check(raises(lambda: switch(sc.QC_QUARANTINE_LOCK), "ابتدا"), "quarantine lock needs the receipt hold first")
check(qcm.settings(company_id).score_min_samples == 3, "default settings without writing a row")

# ===== ۲) رفتار قبلی دست نخورده: بازرسی یک‌مرحله‌ای =====
switch(sc.RESERVATION)
switch(sc.QC_HOLD)
d0, l0 = receipt(med, 10)
res = qc.inspect(company_id, l0, uid, D(2), whq, D(2), "بسته‌بندی آسیب‌دیده")
r0 = row(res.inspection_id)
check(r0.status_code == "APPROVED" and r0.stage_code == "RECEIPT" and r0.lot_quantity == 10 and r0.accepted_quantity == 8
      and r0.disposition_code == "PARTIAL" and r0.approved_by_user_id == uid, "legacy one-step inspect still approves in one go")
check(stock(med, whq) == 2 and stock(med, whn, "quantity_reserved") == 0, "rejected moved to quarantine, accepted released")
check(blocked("UPDATE inv.qc_inspections SET notes='x' WHERE qc_inspection_id=:i", i=r0.qc_inspection_id),
      "approved inspection is locked in the database")

# ===== ۳) طرح کیفیت نسخه‌دار =====
PF, PP = plans.PlanFields, plans.ParameterFields
params = [PP("قطر", "NUMERIC", "میلی‌متر", D("9.8"), D("10.2"), D(10), test_method="کولیس"),
          PP("ظاهر", "PASS_FAIL"),
          PP("رنگ", "OPTION", options=["سفید", {"value": "زرد", "ok": False}]),
          PP("یادداشت", "TEXT", is_mandatory=False)]
check(raises(lambda: plans.create_plan(company_id, uid, PF("P1", "طرح پیچ", "RECEIPT", item_id=bolt, sampling_method="FIXED"), params),
             "تعداد نمونه"), "fixed sampling needs a sample size")
check(raises(lambda: plans.create_plan(company_id, uid, PF("P1", "طرح پیچ", "RECEIPT", item_id=bolt), [PP("الف"), PP("الف")]),
             "تکراری"), "duplicate parameter names refused")
p1 = plans.create_plan(company_id, uid, PF("P1", "طرح پیچ", "RECEIPT", item_id=bolt, sampling_method="FIXED", sample_size=D(2),
                                          acceptance_number=0), params)
check(raises(lambda: plans.create_plan(company_id, uid, PF("P1", "تکراری", "RECEIPT"), params), "قبلاً"), "plan code is unique")
pcat = plans.create_plan(company_id, uid, PF("P-GEN", "طرح عمومی", "RECEIPT", sampling_method="PERCENT", sample_percent=D(10)),
                         [PP("ظاهر", "PASS_FAIL")])
plans.activate_plan(company_id, uid, p1)
plans.activate_plan(company_id, uid, pcat)
check(raises(lambda: plans.update_plan(company_id, uid, p1, PF("P1", "تغییر", "RECEIPT", item_id=bolt), params), "پیش‌نویس"),
      "an active plan cannot be edited")
with new_session() as s:
    found = plans.find_plan(s, company_id, "RECEIPT", bolt, supplier_id=sup1)
    general = plans.find_plan(s, company_id, "RECEIPT", med, supplier_id=sup1)
check(found.plan_id == p1 and general.plan_id == pcat, "most specific active plan is chosen (item plan over general)")
check(plans.sample_size(found, D(50)) == 2 and plans.sample_size(general, D(25)) == 3, "sample size from sampling rule")
p1v2 = plans.new_version(company_id, uid, p1)
v2 = plans.get_plan(company_id, p1v2)
check(v2.plan.version_no == 2 and v2.plan.status_code == "DRAFT" and len(v2.parameters) == 4, "new version is a draft copy")
plans.update_plan(company_id, uid, p1v2, PF("P1", "طرح پیچ نسخهٔ ۲", "RECEIPT", item_id=bolt, sampling_method="FIXED",
                                             sample_size=D(2), acceptance_number=1), params)
plans.activate_plan(company_id, uid, p1v2)
by_id = {p.plan_id: p for p in plans.list_plans(company_id)}
check(by_id[p1].status_code == "SUPERSEDED" and by_id[p1].valid_to == today - datetime.timedelta(days=1)
      and by_id[p1v2].status_code == "ACTIVE", "activating v2 supersedes v1 (validity closed)")
params2 = {p.name: p.parameter_id for p in plans.get_plan(company_id, p1v2).parameters}

# ===== ۴) ثبت نتیجه با پارامترها؛ سقف مقدار =====
d1, l1 = receipt(bolt, 10)
check(held(l1) == 10, "bolt receipt held for QC")
ok_results = lambda n=1: [RI(D("10.0"), params2["قطر"], sample_no=n), RI(True, params2["ظاهر"], sample_no=n),  # noqa: E731
                          RI("سفید", params2["رنگ"], sample_no=n)]
check(raises(lambda: qc.record_result(company_id, l1, uid, accepted=D(11)), "برابر"), "accepted cannot exceed held quantity")
check(raises(lambda: qc.record_result(company_id, l1, uid, accepted=D(6), rejected=D(3)), "برابر"),
      "accepted + rejected + pending must equal the held quantity")
check(raises(lambda: qc.record_result(company_id, l1, uid, accepted=D(10), rejected=D(-1)), "منفی"), "negative quantities refused")
check(raises(lambda: qc.record_result(company_id, l1, uid, accepted=D(10), results=[RI(D(10), params2["قطر"])]), "اجباری"),
      "mandatory parameters must be recorded")
bad = [RI(D("10.5"), params2["قطر"], sample_no=1), RI(True, params2["ظاهر"], sample_no=1), RI("سفید", params2["رنگ"], sample_no=1),
       RI(D("10.0"), params2["قطر"], sample_no=2), RI(False, params2["ظاهر"], sample_no=2), RI("زرد", params2["رنگ"], sample_no=2)]
check(raises(lambda: qc.record_result(company_id, l1, uid, accepted=D(10), sampled=D(2), results=bad), "عدد پذیرش"),
      "two defective samples > acceptance number 1: full acceptance refused")
check(raises(lambda: qc.record_result(company_id, l1, uid, accepted=D(10), results=ok_results() + ok_results()), "دو بار"),
      "same parameter twice for one sample refused")
with new_session() as s:
    check(s.scalar(select(func.count()).select_from(QcInspection).where(QcInspection.stock_document_line_id == l1)) == 0,
          "failed attempts leave nothing behind (one transaction)")

# ===== ۵) جداسازی ثبت و تأیید =====
switch(sc.QC_SEPARATE_APPROVAL)
i1 = qc.record_result(company_id, l1, uid, accepted=D(6), rejected=D(2), pending=D(2), sampled=D(2), results=bad,
                      notes="دو نمونه خارج از حد", idempotency_key="L1-A")
check(qc.record_result(company_id, l1, uid, accepted=D(6), rejected=D(2), pending=D(2), results=bad, idempotency_key="L1-A") == i1,
      "same idempotency key returns the same inspection (no duplicate)")
r1 = row(i1)
check(r1.status_code == "RECORDED" and r1.plan_id == p1v2 and r1.disposition_code == "PARTIAL" and held(l1) == 10
      and stock(bolt, whq) == 0, "recorded only: stock still held until final approval")
check(raises(lambda: qc.record_result(company_id, l1, uid, accepted=D(10), results=ok_results()), "منتظر تأیید"),
      "one open result per line")
with new_session() as s:
    snap = list(s.scalars(select(InspectionResult).where(InspectionResult.qc_inspection_id == i1)))
check(len(snap) == 6 and sum(1 for x in snap if x.is_conforming is False) == 3
      and next(x for x in snap if x.parameter_name == "قطر").max_value == D("10.2"), "results stored with a snapshot of the limits")
check(blocked("UPDATE qms.inspection_results SET value_text='x' WHERE qc_inspection_id=:i", i=i1), "results are immutable")
check(raises(lambda: qc.approve(company_id, i1, uid, whq), "فرد دیگری"), "recorder cannot approve own result (segregation)")
out = qc.approve(company_id, i1, approver, whq, "تأیید مدیر کیفیت")
r1 = row(i1)
check(r1.status_code == "APPROVED" and r1.approved_by_user_id == approver and r1.transfer_stock_document_id is not None,
      "another user approves; transfer document recorded")
check(stock(bolt, whq) == 2 and held(l1) == 2 and stock(bolt, whn, "quantity_reserved") == 2,
      "rejected 2 moved to quarantine, accepted 6 free, pending 2 still held")
check(qc.approve(company_id, i1, approver, whq).inspection_id == i1 and stock(bolt, whq) == 2, "approving twice is a no-op")
check(blocked("UPDATE inv.qc_inspections SET accepted_quantity=10 WHERE qc_inspection_id=:i", i=i1),
      "approved result cannot be changed without trace")
check(any(n.qc_inspection_id == r0.qc_inspection_id for n in ncr.list_ncrs(company_id)),
      "legacy one-step rejection also opens an NCR (setting «auto NCR» on by default)")
auto = [n for n in ncr.list_ncrs(company_id) if n.qc_inspection_id == i1]
check(len(auto) == 1 and auto[0].qc_inspection_id == i1 and auto[0].source_code == "RECEIPT" and auto[0].quantity == 2
      and auto[0].cost_amount == D(2000), "rejection opened an NCR automatically (qty × unit cost)")
qc.approve(company_id, i1, approver, whq)
check(len([n for n in ncr.list_ncrs(company_id) if n.qc_inspection_id == i1]) == 1, "no duplicate NCR on repeated approval")

# بازرسی مجدد مقدار در انتظار
i2 = qc.record_result(company_id, l1, uid, accepted=D(2), results=ok_results())
check(row(i2).reinspection_of_id == i1, "re-inspection links to the previous decision")
i2b = None
qc.cancel(company_id, i2, uid, "اشتباه در ورود")
check(row(i2).status_code == "CANCELLED" and held(l1) == 2, "unapproved result can be cancelled; stock stays held")
check(raises(lambda: qc.cancel(company_id, i1, uid, "x"), "فقط نتیجهٔ منتظر"), "approved result cannot be cancelled")
i2b = qc.record_result(company_id, l1, uid, accepted=D(2), results=ok_results())
qc.approve(company_id, i2b, approver)
check(held(l1) == 0 and stock(bolt, whn, "quantity_reserved") == 0, "re-inspection released the rest")
hist = queries.inspection_detail(company_id, i1).history
check([h.changes.get("operation") for h in hist] == ["QC_RECORD", "QC_APPROVE"], "decision history from the audit trail")

# ===== ۶) قفل قرنطینه، آزادسازی مجاز، برگشت به تامین‌کننده =====
switch(sc.QC_QUARANTINE_LOCK)


def issue_from(wh, item, qty, doc_type="ISSUE", dest=None):
    d = inv_docs.create_stock_document(company_id, uid, doc_type, today,
                                       inv_docs.DocumentHeaderFields(source_warehouse_id=wh, destination_warehouse_id=dest))
    inv_docs.add_line(d, company_id, inv_docs.LineFields(item_id=item, uom_id=pcs, quantity=D(qty), quantity_base=D(qty)))
    inv_docs.confirm_stock_document(d, company_id)
    inv_docs.post_stock_document(d, company_id, uid)


check(raises(lambda: issue_from(whq, bolt, 1), "قرنطینه"), "normal issue from quarantine blocked")
check(raises(lambda: issue_from(whq, bolt, 1, "TRANSFER", whn), "قرنطینه"), "normal transfer out of quarantine blocked")
check(stock(bolt, whq) == 2, "quarantine stock untouched")
check(raises(lambda: qc.release_from_quarantine(company_id, uid, whq, bolt, D(1), whn, ""), "دلیل"), "release needs a reason")
check(raises(lambda: qc.release_from_quarantine(company_id, uid, whq, bolt, D(5), whn, "x"), "کافی"),
      "cannot release more than in quarantine")
rel = qc.release_from_quarantine(company_id, uid, whq, bolt, D(1), whn, "آزمون مجدد قبول شد", auto[0].ncr_id)
check(rel and stock(bolt, whq) == 1 and stock(bolt, whn) == 9, "authorised release moved 1 back to usable stock")
with new_session() as s:
    log = s.scalar(select(ActivityLog).where(ActivityLog.entity_id == rel, ActivityLog.action == "EXECUTE")
                   .order_by(ActivityLog.log_id.desc()).limit(1))
check(log is not None and log.changes.get("operation") == "QC_RELEASE", "release is audited")
ret = qc.return_to_supplier(company_id, uid, whq, bolt, D(1), sup1, D(1000), auto[0].ncr_id)
docs, lines = documents_service.get_document(ret, company_id)
check(docs.document_type_code == "PURCHASE_RETURN" and docs.status_code == "DRAFT" and lines[0].quantity == 1,
      "return to supplier creates a draft purchase return through the commercial service")
with new_session() as s:
    check(s.get(Nonconformance, auto[0].ncr_id).disposition_code == "RETURN_TO_SUPPLIER", "NCR disposition follows the return")
switch(sc.QC_QUARANTINE_LOCK, False)

# ===== ۷) عدم‌انطباق و اقدام اصلاحی =====
NF = ncr.NcrFields
check(raises(lambda: ncr.create_ncr(company_id, uid, NF("", severity_code="MAJOR")), "عنوان"), "NCR needs a title")
n1 = ncr.create_ncr(company_id, uid, NF("ترک در بدنه", "SUPPLIER", "MAJOR", item_id=bolt, supplier_detail_account_id=sup1,
                                        quantity=D(3), cost_amount=D(500000), cause_code="SUPPLIER"))
check(ncr.get_ncr(company_id, n1).ncr.ncr_no == max(n.ncr_no for n in ncr.list_ncrs(company_id) if n.ncr_id != n1) + 1,
      "NCR numbers are sequential")
check(raises(lambda: ncr.set_status(company_id, uid, n1, "CLOSED"), "علت ریشه‌ای"), "cannot close without root cause")
check(raises(lambda: ncr.update_ncr(company_id, uid, n1, root_cause_method="FIVE_WHY", root_cause_details=["1"] * 6), "پنج"),
      "five-why has at most five answers")
ncr.update_ncr(company_id, uid, n1, root_cause_method="FIVE_WHY", root_cause_details=["قالب فرسوده", "نگهداری نشده"],
               root_cause="برنامهٔ نگهداری قالب تامین‌کننده", disposition_code="RETURN_TO_SUPPLIER", responsible_user_id=approver)
ncr.set_status(company_id, uid, n1, "INVESTIGATING")
check(raises(lambda: ncr.set_status(company_id, uid, n1, "CLOSED"), "اثربخش"), "major NCR needs a verified corrective action")
a1 = ncr.add_action(company_id, uid, n1, "CORRECTIVE", "تعویض قالب تامین‌کننده", approver, today + datetime.timedelta(days=5))
check(ncr.get_ncr(company_id, n1).ncr.status_code == "ACTION", "adding an action moves the NCR to action")
check(raises(lambda: ncr.verify_action(company_id, uid, a1, True), "انجام"), "cannot verify before completion")
ncr.complete_action(company_id, approver, a1, "گزارش بازدید شمارهٔ ۱۲")
check(raises(lambda: ncr.verify_action(company_id, approver, a1, True), "نمی‌تواند"), "completer cannot verify own action (separation on)")
check(raises(lambda: ncr.verify_action(company_id, uid, a1, False), "دلیل"), "ineffective needs a note")
ncr.verify_action(company_id, uid, a1, True, "سه محمولهٔ بعدی سالم")
ncr.set_status(company_id, uid, n1, "CLOSED")
n1row = ncr.get_ncr(company_id, n1)
check(n1row.ncr.status_code == "CLOSED" and n1row.ncr.closed_by_user_id == uid, "NCR closed after effective action")
check(raises(lambda: ncr.update_ncr(company_id, uid, n1, title="تغییر"), "")
      or blocked("UPDATE qms.nonconformances SET title='x' WHERE ncr_id=:i", i=n1), "closed NCR is locked")
check(blocked("UPDATE qms.capa_actions SET description='x' WHERE action_id=:i", i=a1), "verified action is locked")
check(len([h for h in n1row.history]) >= 6, "NCR and action history kept")
check(raises(lambda: ncr.set_status(company_id, uid, auto[0].ncr_id, "CANCELLED"), "علت"), "cancel needs a reason")

# ===== ۸) امتیاز تامین‌کننده از داده‌های واقعی =====
qcm.save_settings(company_id, uid, score_min_samples=4)
sc1 = {s.supplier_id: s for s in scoring.supplier_scores(company_id)}[sup1]
check(sc1.inspections == 3 and sc1.score is None and "ناکافی" in sc1.note and "4" in sc1.note, "below minimum samples: no score, says why")
d4, l4 = receipt(med, 5)
i4 = qc.record_result(company_id, l4, uid, accepted=D(5), results=[RI(True, plans.get_plan(company_id, pcat).parameters[0].parameter_id)])
qc.approve(company_id, i4, approver)
sc1 = {s.supplier_id: s for s in scoring.supplier_scores(company_id)}[sup1]
check(sc1.inspections == 4 and sc1.score is not None and sc1.reject_rate == D("16.0") and sc1.ncr_count == 3,
      f"score computed from 4 inspections, reject 4/25, 3 NCRs (got {sc1.inspections}, {sc1.reject_rate}, {sc1.ncr_count})")
check(raises(lambda: qcm.save_settings(company_id, uid, weight_reject=0, weight_return=0, weight_ncr=0, weight_delay=0,
                                       weight_trend=0), "وزن"), "at least one weight must be positive")
# اصلاح سند منبع: رسید برگشت بخورد، امتیاز دوباره حساب می‌شود
inv_docs.reverse_stock_document(d4, company_id, uid)
sc1b = {s.supplier_id: s for s in scoring.supplier_scores(company_id)}[sup1]
check(sc1b.inspections == 3 and sc1b.score is None, "reversed receipt drops out of the score (recalculated from source)")
qcm.save_settings(company_id, uid, score_min_samples=2, weight_delay=0)
sc1c = {s.supplier_id: s for s in scoring.supplier_scores(company_id)}[sup1]
check(sc1c.score is not None and "2 بازرسی" in scoring.formula_text(qcm.settings(company_id)).replace("کمتر از ", ""),
      "weights and minimum samples are configurable")
# بازرسی منتظر تأیید هنگام برگشت رسید لغو می‌شود
d5, l5 = receipt(med, 4)
i5 = qc.record_result(company_id, l5, uid, accepted=D(4), results=[RI(True, plans.get_plan(company_id, pcat).parameters[0].parameter_id)])
inv_docs.reverse_stock_document(d5, company_id, uid)
check(row(i5).status_code == "CANCELLED" and held(l5) == 0, "reversing a receipt cancels its open result and hold")

# ===== ۹) دسترسی جداگانهٔ نقش‌ها =====
switch(sc.QC_ROLE_PERMISSIONS)
d6, l6 = receipt(med, 3)
pid = plans.get_plan(company_id, pcat).parameters[0].parameter_id
check(raises(lambda: qc.record_result(company_id, l6, approver, accepted=D(3), results=[RI(True, pid)]), "دسترسی"),
      "user without inspector role cannot record")
check(not qcm.can(company_id, approver, qcm.FORM_APPROVE), "can() reflects the missing role")
forms = {f.code: f.form_id for f in roles_service.list_forms()}
check({"qc_inspect", "qc_approve", "qc_release", "qc_manage", "qc_ncr", "qc_queue", "qc_settings"} <= set(forms),
      "quality permissions are in the role table")
inspector = roles_service.create_role(company_id, "QC_INSPECTOR", None)
roles_service.set_role_permission(inspector.role_id, forms["qc_inspect"], "CREATE", True)
roles_service.set_user_role(approver, inspector.role_id, company_id, True)
i6 = qc.record_result(company_id, l6, approver, accepted=D(3), results=[RI(True, pid)])
check(row(i6).status_code == "RECORDED", "inspector role can record")
qc.approve(company_id, i6, uid)
check(row(i6).status_code == "APPROVED", "a user with approval rights approves the inspector's result")
check(raises(lambda: plans.create_plan(company_id, approver, PF("PX", "x", "RECEIPT"), [PP("الف")]), "دسترسی"),
      "inspector cannot manage plans")
check(raises(lambda: qc.release_from_quarantine(company_id, approver, whq, bolt, D(1), whn, "x"), "دسترسی"),
      "inspector cannot release quarantine")
check(raises(lambda: ncr.create_ncr(company_id, approver, NF("x")), "دسترسی"), "inspector cannot open NCRs without the role")
switch(sc.QC_ROLE_PERMISSIONS, False)

# ===== ۱۰) گزارش‌ها و داشبورد =====
f = PurchaseFilters(today - datetime.timedelta(days=30), today, side="INVENTORY", options={"stage": "ALL", "status": "ALL"})
log = qrep.inspection_log(company_id, f)
check(len(log.rows) >= 6 and all(r is None or r[1] == "RECEIPT" for r in log.refs), "inspection log lists all inspections with drill-down")
f_rec = PurchaseFilters(f.date_from, f.date_to, side="INVENTORY", options={"stage": "RECEIPT", "status": "RECORDED"})
check(len(qrep.inspection_log(company_id, f_rec).rows) == 0, "status filter (no open results left)")
f_insp = PurchaseFilters(f.date_from, f.date_to, side="INVENTORY", options={"stage": "ALL", "status": "ALL"}, inspector_id=approver)
check(len(qrep.inspection_log(company_id, f_insp).rows) == 1, "inspector filter")
f_item = PurchaseFilters(f.date_from, f.date_to, side="INVENTORY", item_id=bolt, options={"stage": "ALL", "status": "ALL"})
check(len(qrep.inspection_log(company_id, f_item).rows) == 3, "item filter")
pr = qrep.parameter_results(company_id, f)
check(len(pr.rows) >= 12 and any(r[12] == "خیر" for r in pr.rows), "parameter results report shows non-conforming values")
check(len(qrep.quarantine(company_id, f).rows) == 2, "quarantine report (bolt + med)")
check(len(qrep.ncr_report(company_id, PurchaseFilters(f.date_from, f.date_to, options={"status": "ALL", "severity": "ALL"})).rows) == 3,
      "NCR report")
check(len(qrep.capa_report(company_id, PurchaseFilters(f.date_from, f.date_to, options={"status": "ALL"})).rows) == 1, "CAPA report")
card = qrep.supplier_card(company_id, f)
check(card.rows and "بازه" in card.note and card.rows[0][1] >= 3, "supplier card with sample count and formula")
check(qrep.item_card(company_id, f).rows, "item quality card")
from peecha.services import warehouse_reports as wr
check(all(code in wr.WAREHOUSE_REPORTS_BY_CODE for code in ("QC_INSPECTION_LOG", "QC_NCR", "QC_SUPPLIER_CARD", "QC_QUARANTINE")),
      "quality reports registered on the standard report engine (PDF/Excel)")
kpis, charts, alerts = qdash.dashboard(company_id, today - datetime.timedelta(days=30), today)
k = {x.code: x for x in kpis}
print("KPIS", {x.code: x.value for x in kpis}, [a.kind for a in alerts])
check(k["INSPECTIONS"].value >= 5 and k["REJECT_RATE"].value is not None and k["NCR_OPEN"].value == 2 and k["AWAITING"].value == 0,
      "dashboard KPIs from real data")
check(not any(a.kind == "AWAITING" for a in alerts) and charts["by_period"]["labels"] and charts["by_severity"]["series"]["تعداد"],
      "dashboard alerts and charts")

# ===== ۱۱) صفحه‌ها =====
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from peecha.ui.screens import quality as ui
from peecha import nav_catalog
from peecha.ui import shell_window
flat = {i["code"]: i for i in nav_catalog.flatten_nav_items()}
check({"QC_DASHBOARD", "QC_QUEUE", "QC_QUARANTINE_STOCK", "QC_NCR", "QC_CAPA", "QC_PLANS", "QC_CARDS", "INV_RPT_QC_INSPECTION_LOG"}
      <= set(flat) and flat["QC_SETTINGS"].get("hidden_from_sidebar") and shell_window._SETTINGS_TAB_BY_GROUP_CODE["QC"] == 14,
      "quality module in the menu, settings behind the gear")
ribbon = nav_catalog.DEFAULT_QUICK_ACCESS_BY_MODULE.get("QC", [])
check(len(ribbon) >= 6 and all(code in flat for code, _ in ribbon), "quality ribbon shortcuts")
warnings = []
d7, l7 = receipt(med, 4)
q = ui.InspectionQueueScreen()
q.warn = warnings.append
q.refresh()
print("QUEUE", q.t_pending.rowCount(), q.t_recorded.rowCount(), q.cards["waiting"].text(), q.cards["awaiting"].text())
check(q.t_pending.rowCount() == 1 and q.t_recorded.rowCount() == 0 and q.cards["waiting"].text() == "۱", "queue shows waiting rows")
q.t_pending.selectRow(0)


def fill_result(dlg):
    dlg.set_value(0, True)
    dlg.accepted.setText("3")
    dlg.rejected.setText("1")
    return True


q.dialog_runner = fill_result
i7 = q.record_selected()
check(i7 and row(i7).status_code == "RECORDED" and row(i7).rejected_quantity == 1 and not warnings,
      f"result form records with plan parameters ({warnings})")
q.refresh()
recorded_ids = [q.t_recorded.item(r, 0).data(ui.Qt.UserRole) for r in range(q.t_recorded.rowCount())]
q.t_recorded.selectRow(recorded_ids.index(i7))
fx.sess.current_user = visitor
q.dialog_runner = lambda dlg: (ui.set_combo(dlg.widgets["reject_warehouse_id"], whq), True)[1]
check(q.approve_selected() and row(i7).status_code == "APPROVED" and stock(med, whq) >= 1, "approve from the queue")
fx.sess.current_user = user
q.tabs.setCurrentIndex(3)
q.t_history.selectRow(0)
q.dialog_runner = lambda dlg: True
q.show_detail(q.t_history)
check(q.last_detail.results.rowCount() >= 1 and q.last_detail.history.rowCount() >= 1, "inspection detail with results and history")
screens = [ui.QuarantineScreen(), ui.NcrScreen(), ui.CapaScreen(), ui.PlansScreen(), ui.QualityCardsScreen(), ui.QcDashboardScreen(),
           ui.QcSettingsScreen()]
for scr in screens:
    scr.warn = warnings.append
    scr.refresh()
qs, ns, cs, ps, cards_scr, dash, settings_scr = screens
print("SCREENS", qs.t.rowCount(), ns.t.rowCount(), ps.t.rowCount(), cards_scr.t_supplier.rowCount(), warnings)
check(qs.t.rowCount() == 2 and ns.t.rowCount() >= 1 and ps.t.rowCount() == 3 and cards_scr.t_supplier.rowCount() >= 1,
      "quarantine, NCR, plans and quality-card screens load")
check(dash.cards["INSPECTIONS"].findChild(ui.QLabel) is not None and settings_scr.toggles.get(sc.QC_SEPARATE_APPROVAL).isChecked(),
      "dashboard and settings load (toggles reflect state)")
ns.open_only.setChecked(False)
ns.dialog_runner = lambda dlg: (dlg.widgets["title"].setText("خراش سطحی"), ui.set_combo(dlg.widgets["severity_code"], "MINOR"), True)[2]
new_ncr = ns.new_ncr()
check(new_ncr and any(r.ncr_id == new_ncr for r in ns.rows), "NCR created from the screen")
ps.dialog_runner = lambda dlg: (dlg.code.setText("P-UI"), dlg.name.setText("طرح صفحه"), dlg.add_param(),
                                dlg.set_param(0, name="وزن", data_type="NUMERIC", min_value="1", max_value="2"), True)[4]
new_plan = ps.new_plan()
check(new_plan and plans.get_plan(company_id, new_plan).parameters[0].max_value == 2, "plan created from the plan form")
settings_scr.min_samples.setValue(5)
check(settings_scr.save() and qcm.settings(company_id).score_min_samples == 5, "settings saved from the screen")
from peecha.ui.screens.system_settings import SystemSettingsScreen
ss = SystemSettingsScreen()
labels = [ss.tabs.tabText(i) for i in range(ss.tabs.count())]
check(labels[14] == "کنترل کیفیت", f"quality tab in system settings at the gear index ({labels})")


def _parents(w):
    out = []
    while w is not None:
        w = w.parentWidget()
        out.append(w)
    return out


own = lambda b: not any(isinstance(w, ui.QDialog) for w in _parents(b))  # noqa: E731
check(all(len(b.text()) <= 3 for scr in screens[:5] + [q] for b in scr.findChildren(ui.QPushButton) if own(b)),
      "icon buttons only on the screens (no text buttons)")
check(not warnings, f"no warnings shown ({warnings})")

finish()
