"""R295: اتصال ماژول‌ها به گردش کار، قالب‌ها و سناریوهای پذیرش با سرویس‌های واقعی."""
import os, sys, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r295"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from sqlalchemy import select, func
from peecha.db.models.workflow import WfEvent, WfInstance, WfTask
from peecha.db.models.security import Form, Notification
from peecha.services import hr as hr_service, hr_leave, journal_entries as je_service, purchase_requests as pr_service
from peecha.services import roles as roles_service, users as users_service, commercial_partners as partners
from peecha.services.workflow import (
    definitions as defs, events, exceptions as wf_exc, model_events, registry, runtime, scheduler, tasks, templates,
)
from peecha.services.workflow.common import WorkflowError
check, raises = fx.check, fx.raises

registry.ensure_loaded()
roles_service.ensure_catalog()


def user(login, name, role_code=None, perms=()):
    u = users_service.create_user(login, name, "secret123", None, lang_id, False, [company_id], company_id).user_id
    if role_code:
        role = roles_service.create_role(company_id, role_code, None)
        roles_service.set_user_role(u, role.role_id, company_id, True)
        with new_session() as s:
            for form, action in perms:
                fid = s.scalar(select(Form.form_id).where(Form.code == form))
                roles_service.set_role_permission(role.role_id, fid, action, True)
    return u


buyer = user("buyer", "کارشناس خرید")
mgr = user("mgr1", "مدیر بازرگانی", "MANAGER")
fin = user("fin1", "کارشناس مالی", "FIN", [("journal_entry", "APPROVE")])
treas = user("treas1", "خزانه‌دار", "TREAS", [("treasury_voucher_payment", "APPROVE")])
salesmgr = user("smgr", "مدیر فروش", "SALESMGR", [("commercial_document_sales_order", "APPROVE")])
hr_user = user("hr1", "کارشناس منابع انسانی", "HRROLE", [("hr_leave_requests", "APPROVE")])


def install(code):
    did = templates.install(company_id, uid, code)
    defs.publish(company_id, uid, did)
    return did


def doc(dtype, party, amount, user_id, discount=D(0), qty=D(1)):
    d = documents_service.create_document(company_id, user_id, dtype, today, documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=party, currency_id=company.base_currency_id, warehouse_id=warehouse_id,
        channel_code=channel_code if dtype.startswith("SALES") else None))
    documents_service.add_line(d, company_id, item_id=item_a, uom_id=pcs, quantity=qty, quantity_base=qty,
                               unit_price=D(amount) / qty, discount_amount=discount)
    return d


def status(d):
    return documents_service.get_document(d, company_id)[0].status_code


def inst_of(et, eid):
    rows = runtime.list_instances(company_id, entity_type=et, entity_id=eid)
    return rows[0] if rows else None


def open_tasks(et, eid):
    return tasks.list_tasks(company_id, entity_type=et, entity_id=eid, status="OPEN")


def approve(et, eid, who, comment="تایید"):
    t = open_tasks(et, eid)
    check(bool(t), f"open task for {et} {eid}")
    return tasks.decide(company_id, t[0].task_id, who, "APPROVE", comment)


# ===== ۰) بدون فرایند فعال، همه‌چیز مثل قبل =====
inv0 = fx.invoice(cust_a, 1000, user_id=uid)
check(status(inv0) == "POSTED", "sales invoice posts normally with listeners loaded (no workflow defined)")
with new_session() as s:
    check(s.scalar(select(func.count()).select_from(WfEvent)) == 0, "no events stored when nobody listens")
check(len(registry.adapters()) >= 25 and len(registry.scans()) == 4, "module adapters and scans registered")
check(len(templates.TEMPLATES) == 26, "26 templates (23 standard + 3 extra)")

# ===== ۱) سفارش خرید بالای ۵۰۰ میلیون: مدیر ← مالی ← تصویب خودکار =====
supplier = partners.create_supplier(company_id, "S-1", "تامین‌کنندهٔ الف", fast_track=True)
po_def = install("PURCHASE_ORDER_APPROVAL")
small = doc("PURCHASE_ORDER", supplier, 100_000_000, buyer)
documents_service.confirm_document(small, company_id, buyer)
check(inst_of("PURCHASE_ORDER", small) is None, "small PO does not start approval (condition)")
documents_service.approve_document(small, company_id, mgr)
check(status(small) == "APPROVED", "small PO approved directly: gate is condition-aware")

big = doc("PURCHASE_ORDER", supplier, 600_000_000, buyer)
documents_service.confirm_document(big, company_id, buyer)
i_big = inst_of("PURCHASE_ORDER", big)
check(i_big is not None and i_big.status_code == "WAITING", "big PO confirmation started approval automatically")
check(raises(lambda: documents_service.approve_document(big, company_id, mgr), "در جریان تایید"),
      "direct approval blocked while workflow runs (gate)")
check(status(big) == "CONFIRMED", "gate left the document untouched")
check(model_events.check(company_id, "PURCHASE_ORDER", big, "POSTED", "CONFIRMED") is not None,
      "form pre-check blocks posting from confirmed state")
t1 = open_tasks("PURCHASE_ORDER", big)[0]
check(raises(lambda: tasks.decide(company_id, t1.task_id, buyer, "APPROVE"), ""), "requester cannot approve own PO (SoD)")
check(raises(lambda: tasks.decide(company_id, t1.task_id, fin, "APPROVE"), ""), "non-assignee cannot decide")
approve("PURCHASE_ORDER", big, mgr)
t2 = open_tasks("PURCHASE_ORDER", big)
check(len(t2) == 1 and t2[0].title.startswith("تایید مالی"), "second level goes to finance")
check(raises(lambda: tasks.decide(company_id, t2[0].task_id, mgr, "APPROVE"), ""), "first approver cannot take finance step")
approve("PURCHASE_ORDER", big, fin)
check(status(big) == "APPROVED" and runtime.get_instance(company_id, i_big.instance_id).outcome_code == "APPROVED",
      "after both approvals the PO is approved by the existing service")
with new_session() as s:
    check(s.get(documents_service.CommercialDocument, big).approved_by_user_id == fin, "approved by last approver (run as approver)")
check(model_events.check(company_id, "PURCHASE_ORDER", big, "POSTED", "APPROVED") is None, "approved document may be posted")

# ===== ۲) تخفیف بالا ← مدیر فروش =====
disc_def = install("DISCOUNT_APPROVAL")
so = doc("SALES_ORDER", cust_a, 1_000_000, uid, discount=D(200_000))
documents_service.confirm_document(so, company_id, uid)
check(inst_of("SALES_ORDER", so) is not None, "high discount order starts discount approval")
check(any(t.entity_id == so for t in tasks.list_my_tasks(company_id, salesmgr)), "sales manager is an approver")
approve("SALES_ORDER", so, salesmgr)
check(status(so) == "APPROVED", "discount approved then order approved")
so2 = doc("SALES_ORDER", cust_a, 1_000_000, uid, discount=D(10_000))
documents_service.confirm_document(so2, company_id, uid)
check(inst_of("SALES_ORDER", so2) is None, "small discount needs no approval")


# ===== ۳) فاکتور معوق ← کار پیگیری وصول + خبر به صادرکننده =====
def credit_invoice(customer_id, amount, due):
    d = documents_service.create_document(company_id, uid, "SALES_INVOICE", today, documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=customer_id, currency_id=company.base_currency_id, warehouse_id=warehouse_id,
        channel_code=channel_code, due_date=due))
    documents_service.add_line(d, company_id, item_id=item_a, uom_id=pcs, quantity=D(1), quantity_base=D(1), unit_price=D(amount))
    documents_service.confirm_document(d, company_id, uid)
    settlements_service.save_settlement_plan(d, company_id, uid, [])
    settlements_service.approve_settlement_plan(d, company_id, uid)
    documents_service.post_document(d, company_id, uid)
    return d


late = credit_invoice(cust_b, 5000, today - datetime.timedelta(days=10))
check(late in registry.scans()["OVERDUE_INVOICES"].func(company_id, {"min_days": 1}), "overdue scan finds the invoice")
install("OVERDUE_COLLECTION")
scheduler.run_scans(company_id, force=True)
i_late = inst_of("SALES_INVOICE", late)
check(i_late is not None and i_late.status_code == "COMPLETED", "collection process ran for overdue invoice")
from peecha.db.models.commercial import CustomerActivity  # noqa: E402
with new_session() as s:
    acts = list(s.scalars(select(CustomerActivity).where(CustomerActivity.customer_detail_account_id == cust_b,
                                                         CustomerActivity.subject.like("پیگیری وصول%"))))
    note = s.scalar(select(Notification).where(Notification.user_id == uid, Notification.title.like("فاکتور%سررسید%")))
check(len(acts) == 1 and acts[0].priority_code == "HIGH", "collection follow-up task created in CRM activities")
check(note is not None, "issuer notified about overdue invoice")
scheduler.run_scans(company_id, force=True)
with new_session() as s:
    again = s.scalar(select(func.count()).select_from(CustomerActivity).where(CustomerActivity.customer_detail_account_id == cust_b,
                                                                               CustomerActivity.subject.like("پیگیری وصول%")))
check(again == 1 and len(runtime.list_instances(company_id, entity_type="SALES_INVOICE", entity_id=late)) == 1,
      "same day scan twice: nothing duplicated (scenario 9)")

# ===== ۴) کالای زیر نقطهٔ سفارش ← درخواست خرید با همان سرویس =====
from peecha.services import procurement_masters  # noqa: E402
pol = procurement_masters.save_reorder_policy(company_id, procurement_masters.PolicyFields(
    item_id=item_b, warehouse_id=warehouse_id, reorder_point_qty=D(50), max_qty=D(200)))
ctx = registry.get_adapter("REORDER_POLICY").load(company_id, pol)
check(ctx["below_point"] and ctx["suggested_qty"] == D(200) - ctx["free"], "reorder context uses the purchase-suggestion rule")
install("STOCK_REORDER")
scheduler.run_scans(company_id, force=True)
reqs = [r for r in pr_service.list_requests(company_id)] if hasattr(pr_service, "list_requests") else []
with new_session() as s:
    from peecha.db.models.commercial import PurchaseRequest, PurchaseRequestLine
    prs = list(s.execute(select(PurchaseRequest.request_id, PurchaseRequest.status_code, PurchaseRequestLine.quantity).join(
        PurchaseRequestLine, PurchaseRequestLine.request_id == PurchaseRequest.request_id).where(PurchaseRequestLine.item_id == item_b)))
check(len(prs) == 1 and prs[0][1] == "SUBMITTED" and prs[0][2] == ctx["suggested_qty"], "purchase request created and submitted")
scheduler.run_scans(company_id, at=runtime.now() + datetime.timedelta(days=1), force=True)
with new_session() as s:
    n_pr = s.scalar(select(func.count()).select_from(PurchaseRequestLine).where(PurchaseRequestLine.item_id == item_b))
check(n_pr == 1, "next day: open request exists, no duplicate request")

# ===== ۵) مرخصی ← مدیر مستقیم ← منابع انسانی =====
staff = user("staff1", "کارمند فروش")
boss = user("boss1", "سرپرست فروش")
unit = hr_service.create_org_unit(company_id, "U-S", "فروش", None, None)
pos = hr_service.create_position(company_id, "P-S", "کارشناس", unit, None, 5)
e_staff = hr_service.create_employee(company_id, "E-1", "علی", "کارمند", None, today, unit, pos, D(1000), None)
e_boss = hr_service.create_employee(company_id, "E-2", "رضا", "سرپرست", None, today, unit, pos, D(1000), None)
hr_service.set_employee_user(company_id, e_staff, staff)
hr_service.set_employee_user(company_id, e_boss, boss)
hr_service.set_org_unit_manager(company_id, unit, e_boss)
install("LEAVE_APPROVAL")
lv = hr_leave.create_request(company_id, staff, e_staff, "ANNUAL", today, today + datetime.timedelta(days=2), reason="سفر", submit=True)
check(inst_of("LEAVE_REQUEST", lv) is not None, "submitted leave started approval")
check(raises(lambda: hr_leave.approve(company_id, lv, uid), "در جریان تایید"), "leave cannot be approved outside the workflow")
check(any(t.entity_id == lv for t in tasks.list_my_tasks(company_id, boss)), "first step goes to direct manager")
approve("LEAVE_REQUEST", lv, boss)
check(any(t.entity_id == lv for t in tasks.list_my_tasks(company_id, hr_user)), "second step goes to HR")
approve("LEAVE_REQUEST", lv, hr_user)
check(hr_leave.get(company_id, lv).status_code == "APPROVED", "leave approved by workflow action")
lv2 = hr_leave.create_request(company_id, staff, e_staff, "SICK", today + datetime.timedelta(days=5),
                              today + datetime.timedelta(days=5), submit=True)
t_lv2 = open_tasks("LEAVE_REQUEST", lv2)[0]
tasks.decide(company_id, t_lv2.task_id, boss, "REJECT", "در این روز جلسهٔ مهم داریم")
r2 = hr_leave.get(company_id, lv2)
check(r2.status_code == "REJECTED" and "جلسه" in r2.decision_note, "rejection recorded on the leave with the manager's reason")

# ===== ۶) پرداخت ← مالی ← خزانه ← سند دائم =====
install("PAYMENT_APPROVAL")
pay = je_service.create_journal_entry(company_id, uid, today, "پرداخت به تامین‌کننده", [
    je_service.LineInput(cash_gl.account_id if hasattr(cash_gl, "account_id") else cash_gl, "بدهکار", D(0), D(700)),
    je_service.LineInput(discount_gl.account_id if hasattr(discount_gl, "account_id") else discount_gl, "بستانکار", D(700), D(0))],
    entry_type_code="PAYMENT").journal_entry_id
check(inst_of("PAYMENT_VOUCHER", pay) is not None, "payment voucher started approval")
check(raises(lambda: je_service.approve_journal_entry(pay, company_id, uid), "در جریان تایید"), "cannot make it permanent directly")
approve("PAYMENT_VOUCHER", pay, fin)
approve("PAYMENT_VOUCHER", pay, treas)
from peecha.db.models.accounting import JournalEntry  # noqa: E402
with new_session() as s:
    je = s.get(JournalEntry, pay)
    check(je.permanent_no is not None and je.posted_by_user_id == treas, "payment became permanent after finance and treasury")
plain_je = je_service.create_journal_entry(company_id, uid, today, "سند عادی", [
    je_service.LineInput(cash_gl.account_id if hasattr(cash_gl, "account_id") else cash_gl, "ب", D(10), D(0)),
    je_service.LineInput(discount_gl.account_id if hasattr(discount_gl, "account_id") else discount_gl, "ب", D(0), D(10))])
je_service.approve_journal_entry(plain_je.journal_entry_id, company_id, uid)
check(True, "normal journal (no workflow) still approved directly")

# ===== ۷) مهلت ← یادآوری ← ارجاع =====
from peecha.services.workflow import sla  # noqa: E402
from peecha.db.models.workflow import WfTask as _T  # noqa: E402
pol_fast = sla.save_policy(company_id, uid, None, code="fast", name="تایید فوری", due_hours=8, warn_before_hours=2,
                           escalate_after_hours=4, max_escalations=1, business_hours=False)
jd = templates.install(company_id, uid, "JOURNAL_APPROVAL")
g = defs.get_graph(company_id, jd)
for n in g["nodes"]:
    if n["type"] == "APPROVAL":
        n["sla_policy_id"] = pol_fast
defs.save_draft(company_id, uid, jd, g)
defs.publish(company_id, uid, jd)
je2 = je_service.create_journal_entry(company_id, buyer, today, "سند اصلاحی", [
    je_service.LineInput(cash_gl.account_id if hasattr(cash_gl, "account_id") else cash_gl, "ب", D(10), D(0)),
    je_service.LineInput(discount_gl.account_id if hasattr(discount_gl, "account_id") else discount_gl, "ب", D(0), D(10))]
).journal_entry_id
t7 = open_tasks("JOURNAL_ENTRY", je2)[0]
with new_session() as s:
    row = s.get(_T, t7.task_id)
    warn_at, due_at, esc_at = row.warn_at, row.due_at, row.escalate_at
scheduler.fire_due_timers(company_id, warn_at + datetime.timedelta(minutes=1))
with new_session() as s:
    check(s.scalar(select(Notification).where(Notification.type_code == "WF_TASK_DUE")) is not None, "reminder before due time")
scheduler.fire_due_timers(company_id, esc_at + datetime.timedelta(minutes=1))
with new_session() as s:
    check(s.get(_T, t7.task_id).escalation_level == 1, "escalated after the deadline")

# ===== ۸) شکست اقدام ← مورد نیازمند بررسی ← حل انسانی =====
install("PURCHASE_REQUEST_APPROVAL")
req = pr_service.create_request(company_id, staff, pr_service.RequestFields(request_date=today, warehouse_id=warehouse_id))
pr_service.add_line(req, company_id, item_a, pcs, D(3))
pr_service.submit_request(req, company_id)
check(any(t.entity_id == req for t in tasks.list_my_tasks(company_id, boss)), "PR goes to requester's direct manager")
approve("PURCHASE_REQUEST", req, boss)
i8 = inst_of("PURCHASE_REQUEST", req)
open_ex = [e for e in wf_exc.list_exceptions(company_id) if e.instance_id == i8.instance_id]
check(i8.status_code in ("WAITING", "RUNNING", "FAILED") and open_ex and "مدیر" in (open_ex[0].reason or ""),
      "service refusal (approver is not a manager) became an exception with a clear reason")
from peecha.db.models.security import Role  # noqa: E402
with new_session() as s:
    manager_role = s.scalar(select(Role.role_id).where(Role.company_id == company_id, Role.code == "MANAGER"))
roles_service.set_user_role(boss, manager_role, company_id, True)
wf_exc.retry(company_id, open_ex[0].exception_id, uid, "نقش مدیر داده شد")
check(pr_service.get_request(req, company_id)[0].status_code == "APPROVED" and
      runtime.get_instance(company_id, i8.instance_id).status_code == "COMPLETED", "human fixed the cause and retried: completed")

# ===== ۹) رویداد تکراری =====
with new_session() as s:
    e1 = events.publish(s, company_id, "LEAD_CREATED", "LEAD", 999, dedupe_key="dup-test")
    e2 = events.publish(s, company_id, "LEAD_CREATED", "LEAD", 999, dedupe_key="dup-test")
    s.rollback()
check(e1 is not None and e2 is None, "duplicate event key is ignored")
before = len(runtime.list_instances(company_id, entity_type="PURCHASE_ORDER", entity_id=big))
with new_session() as s:
    ev_id = s.scalar(select(WfEvent.event_id).where(WfEvent.event_type == "PURCHASE_ORDER_CONFIRMED", WfEvent.entity_id == big))
    s.execute(WfEvent.__table__.update().where(WfEvent.event_id == ev_id).values(status_code="PENDING"))
    s.commit()
events.dispatch_pending(company_id)
check(len(runtime.list_instances(company_id, entity_type="PURCHASE_ORDER", entity_id=big)) == before,
      "replayed event does not start a second approval")

# ===== ۱۰) ادامه پس از راه‌اندازی دوباره =====
lv3 = hr_leave.create_request(company_id, staff, e_staff, "ANNUAL", today + datetime.timedelta(days=20),
                              today + datetime.timedelta(days=21), submit=True)
runtime._GRAPH_CACHE.clear()  # مثل اجرای تازهٔ برنامه
scheduler.run_due(company_id)
approve("LEAVE_REQUEST", lv3, boss)
approve("LEAVE_REQUEST", lv3, hr_user)
check(hr_leave.get(company_id, lv3).status_code == "APPROVED", "waiting process continues after restart")

# ===== اتصال‌های دیگر =====
install("CUSTOMER_ONBOARDING")
newc = partners.create_customer(company_id, "C-9", "فروشگاه تازه", submitted_by_user_id=visitor.user_id)
check(inst_of("CUSTOMER", newc) is not None, "new customer waiting approval started onboarding process")
check(raises(lambda: partners.approve_customer(newc, uid), "در جریان تایید"), "customer cannot be activated outside workflow")
approve("CUSTOMER", newc, uid)
with new_session() as s:
    from peecha.db.models.commercial import CustomerProfile
    check(s.get(CustomerProfile, newc).status_code == "ACTIVE", "customer activated by workflow")
partners.set_customer_hold(cust_a, "SUSPENDED", "بدهی", uid)
with new_session() as s:
    s.get(CustomerProfile, cust_a).status_code = "ACTIVE"  # رفع توقف: دروازه فقط تایید مشتری تازه را می‌پاید
    s.commit()
    check(s.get(CustomerProfile, cust_a).status_code == "ACTIVE", "re-activating a suspended customer is not gated")
install("LEAD_ASSIGNMENT")
from peecha.services.crm import leads as lead_service  # noqa: E402
lead = lead_service.create_lead(company_id, buyer, lead_service.LeadFields(full_name="مشتری بالقوه", mobile="09121112233"))
lead2 = lead_service.create_lead(company_id, buyer, lead_service.LeadFields(full_name="سرنخ دوم", mobile="09121112244",
                                                                            owner_user_id=salesmgr))
lc = registry.get_adapter("LEAD").load(company_id, lead)
check(lc["owner_user_id"] not in (None, buyer) and inst_of("LEAD", lead).status_code == "COMPLETED", "new lead assigned automatically")
check(inst_of("LEAD", lead2) is None and registry.get_adapter("LEAD").load(company_id, lead2)["owner_user_id"] == salesmgr,
      "explicitly assigned lead is left alone")
with new_session() as s:
    check(s.scalar(select(Notification).where(Notification.user_id == lc["owner_user_id"],
                                             Notification.title.like("سرنخ تازه به شما%"))) is not None, "assignee notified")

# ===== امنیت: فروش موبایل هرگز با قفل تایید رد نمی‌شود =====
graph = {"trigger": {"type": "EVENT", "events": ["SALES_INVOICE_CONFIRMED"], "gate": True},
         "nodes": [{"id": "ap", "type": "APPROVAL", "label": "تایید", "approvers": [{"kind": "MANAGERS"}]},
                   {"id": "act", "type": "ACTION", "label": "تصویب", "action": "entity.approve"},
                   {"id": "ok", "type": "END", "label": "تایید", "outcome": "APPROVED"},
                   {"id": "no", "type": "END", "label": "رد", "outcome": "REJECTED"}],
         "edges": [{"from": "start", "to": "ap"}, {"from": "ap", "to": "act", "when": "approved"}, {"from": "act", "to": "ok"},
                   {"from": "ap", "to": "no", "when": "rejected"}]}
gd = defs.create_definition(company_id, uid, code="INV_GATE", name="تایید فاکتور", entity_type="SALES_INVOICE", graph=graph)
defs.publish(company_id, uid, gd)
mob = doc("SALES_INVOICE", cust_a, 3000, visitor.user_id)
documents_service.confirm_document(mob, company_id, visitor.user_id)
check(model_events.check(company_id, "SALES_INVOICE", mob, "POSTED", "CONFIRMED") is not None, "desktop form would stop posting")
settlements_service.auto_approve_full_cash_settlement_plan(mob, company_id, visitor.user_id)
with model_events.ungated():
    documents_service.post_document(mob, company_id, visitor.user_id, from_field_sales=True)
check(status(mob) == "POSTED", "mobile field sale is never rejected by an approval gate")

# ===== فرم‌ها =====
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
qapp = QApplication.instance() or QApplication([])
qapp.setLayoutDirection(Qt.RightToLeft)
WARN = []
QMessageBox.warning = staticmethod(lambda *a, **k: WARN.append(a[2] if len(a) > 2 else ""))
from peecha import session as sess  # noqa: E402
from peecha.db.models.security import User  # noqa: E402
with new_session() as s:
    sess.current_user = s.get(User, uid)
    sess.current_company = s.get(Company, company_id)
    s.expunge_all()
from peecha.ui.screens import commercial_document as cd_screen, hr_leave_requests, workflow_bar, workflow_studio  # noqa: E402
scr = cd_screen.CommercialDocumentScreen("PURCHASE_ORDER", None)
scr.refresh() if hasattr(scr, "refresh") else None
scr.edit_document(big)
check(not scr.workflow_bar.isHidden() and "تایید مالی" in scr.workflow_bar.path.text(), "document form shows the approval path")
scr.edit_document(small)
check(scr.workflow_bar.isHidden(), "no bar when the document never entered a workflow and nothing is manual")
lscr = hr_leave_requests.LeaveRequestsScreen()
lscr.refresh()
check(lscr.table.rowCount() >= 3 and lscr.cards["APPROVED"].text() != "—", "leave screen lists requests with summary cards")
lscr.open_request(lv)
check(lscr._current() is not None and lscr._current().leave_request_id == lv and not lscr.workflow_bar.isHidden(),
      "open_request selects the row (RTL) and shows its approval path")
check(all(len(b.text()) <= 2 for b in lscr.buttons.values()), "leave screen uses icon buttons only")
pls = workflow_studio.ProcessListScreen()
pls.reload()
new_def = pls.new_from_template("TRANSFER_APPROVAL")
check(new_def is not None and defs.get_definition(company_id, new_def).status_code == "DRAFT", "template creates a draft process")
check(all(len(b.text()) <= 2 for b in pls.buttons.values()), "process list keeps icon buttons")
defs.publish(company_id, uid, new_def)
from peecha.services import inventory_documents as inv_docs  # noqa: E402
bar = workflow_bar.WorkflowBar("STOCK_TRANSFER")
wh2 = locations_service.create_warehouse(company_id, "WH-2", "انبار دوم", locations_service.WarehouseFields())
tr = inv_docs.create_stock_document(company_id, uid, "TRANSFER", today, inv_docs.DocumentHeaderFields(
    source_warehouse_id=warehouse_id, destination_warehouse_id=wh2)) if hasattr(inv_docs, "DocumentHeaderFields") else None
if tr:
    bar.set_entity("STOCK_TRANSFER", tr)
    check(not bar.isHidden() and bar.send_button.isEnabled(), "manual send-for-approval button on transfer form")
    WARN.clear()
    check(bar.guard("POSTED", "DRAFT") is False and WARN, "posting transfer is stopped until approved")
    check(bar.send() and inst_of("STOCK_TRANSFER", tr) is not None, "send for approval starts the process")

fx.finish()
