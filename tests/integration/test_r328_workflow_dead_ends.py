"""R328: بازبینی بن‌بست‌های گردش کار با سرویس‌های واقعی: رد (سند قفل نمی‌ماند)، برگشت برای اصلاح (سند باز و ارسال
دوباره همان تایید را ادامه می‌دهد)، برگرداندن سند وسط تایید، فرایند تکراری، و ارسال دوبارهٔ سند ردشده از نوار گردش کار."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r328"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx

from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)

from peecha.db.models.security import User
from peecha.services import journal_entries as je_service, purchase_requests as pr_service, users as users_service
from peecha.services.workflow import builder, definitions as defs, events, model_events, registry, runtime, tasks
from peecha.services.workflow.adapters.finance import je_context
check, raises = fx.check, fx.raises

registry.ensure_loaded()
seller = users_service.create_user("seller1", "کارشناس فروش", "secret123", None, lang_id, False, [company_id], company_id).user_id
boss = users_service.create_user("boss1", "سرپرست فروش", "secret123", None, lang_id, False, [company_id], company_id).user_id


def login(u):
    with new_session() as s:
        sess.current_user = s.get(User, u)
        s.expunge_all()


def publish(code, entity_type, events_, *, changes=True, reject=True):
    spec = builder.WizardSpec(code, code, entity_type, "", {"type": "EVENT", "events": events_, "gate": True}, None,
                              [builder.ApprovalLevel("تایید سرپرست", [{"kind": "USER", "user_id": boss}], allow_changes=changes)],
                              ["entity.approve"], reject_actions=["entity.reject"] if reject else [])
    did = defs.create_definition(company_id, uid, code=code, name=code, entity_type=entity_type)
    defs.save_draft(company_id, uid, did, builder.build_graph(spec))
    defs.publish(company_id, uid, did)
    return did


def order():
    d = documents_service.create_document(company_id, seller, "SALES_ORDER", today, documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=cust_a, currency_id=company.base_currency_id, warehouse_id=warehouse_id,
        channel_code=channel_code))
    documents_service.add_line(d, company_id, item_id=item_a, uom_id=pcs, quantity=D(1), quantity_base=D(1), unit_price=D(1000))
    documents_service.confirm_document(d, company_id, seller)
    return d


def status(d):
    return documents_service.get_document(d, company_id)[0].status_code


def running(et, eid):
    return [i for i in runtime.list_instances(company_id, entity_type=et, entity_id=eid) if i.status_code in ("RUNNING", "WAITING")]


def task_of(et, eid, user=None):
    rows = tasks.list_tasks(company_id, entity_type=et, entity_id=eid, status="OPEN")
    if user is not None:
        mine = {t.task_id for t in tasks.list_my_tasks(company_id, user)}
        rows = [t for t in rows if t.task_id in mine]
    return rows[0] if rows else None


so_def = publish("so_flow", "SALES_ORDER", ["SALES_ORDER_CONFIRMED"])
check(registry.find_action("SALES_ORDER", "entity.reject") is not None, "sales documents now have a «reject» action")

# --- ۱: رد ← سفارش به پیش‌نویس برمی‌گردد (قبلاً «تاییدشده» و قفل می‌ماند) -------------------------------------------
so1 = order()
tasks.decide(company_id, task_of("SALES_ORDER", so1, boss).task_id, boss, "REJECT", "قیمت اشتباه است")
check(status(so1) == "DRAFT" and not running("SALES_ORDER", so1), f"rejected order is back in draft ({status(so1)})")
documents_service.confirm_document(so1, company_id, seller)
check(len(running("SALES_ORDER", so1)) == 1 and task_of("SALES_ORDER", so1, boss), "re-confirming starts the approval again")
tasks.decide(company_id, task_of("SALES_ORDER", so1, boss).task_id, boss, "APPROVE", "")
check(status(so1) == "APPROVED", "approved the second time")

# --- ۲: برگشت برای اصلاح ← سند باز می‌شود؛ تایید دوباره همان فرایند را ادامه می‌دهد -------------------------------------
so2 = order()
tasks.decide(company_id, task_of("SALES_ORDER", so2, boss).task_id, boss, "CHANGES", "تخفیف را کم کنید")
check(status(so2) == "DRAFT", f"returned for correction: the order is editable again ({status(so2)})")
fix = task_of("SALES_ORDER", so2, seller)
check(fix is not None and tasks.rework_note(company_id, "SALES_ORDER", so2) == "تخفیف را کم کنید",
      "the creator has the correction step with the reviewer's note")
check(raises(lambda: tasks.decide(company_id, fix.task_id, seller, "DONE", "", data={"note": "انجام شد"}), "دوباره ارسال"),
      "«done» before re-sending explains what to do")
from peecha.ui.screens.workflow_bar import WorkflowBar  # noqa: E402

login(seller)
bar = WorkflowBar("SALES_ORDER")
bar.set_entity("SALES_ORDER", so2)
check(not bar.warning.isHidden() and "برای اصلاح برگشت" in bar.warning.text() and "تخفیف" in bar.warning.text(),
      f"the order shows why it came back ({bar.warning.text()})")
documents_service.confirm_document(so2, company_id, seller)
check(len(runtime.list_instances(company_id, entity_type="SALES_ORDER", entity_id=so2)) == 1,
      "re-confirming continues the same process (no duplicate)")
check(task_of("SALES_ORDER", so2, seller) is None and task_of("SALES_ORDER", so2, boss) is not None,
      "correction step closed automatically; the reviewer has it again")
tasks.decide(company_id, task_of("SALES_ORDER", so2, boss).task_id, boss, "APPROVE", "")
check(status(so2) == "APPROVED" and runtime.list_instances(company_id, entity_type="SALES_ORDER", entity_id=so2)[0].status_code
      == "COMPLETED", "approved after the correction")

# --- ۳: صادرکننده سند را وسط تایید به پیش‌نویس برمی‌گرداند ← فرایند لغو می‌شود، نه گیر --------------------------------
so3 = order()
check(task_of("SALES_ORDER", so3, boss) is not None, "waiting for the reviewer")
documents_service.revert_to_draft(so3, company_id)
check(not running("SALES_ORDER", so3) and task_of("SALES_ORDER", so3) is None,
      "withdrawn order: its pending approval is cancelled and leaves the reviewer's cartable")
last = runtime.list_instances(company_id, entity_type="SALES_ORDER", entity_id=so3)[0]
check(last.status_code == "CANCELLED" and "پیش‌نویس" in (last.last_error or ""), f"with a clear reason ({last.last_error})")
documents_service.confirm_document(so3, company_id, seller)
check(len(running("SALES_ORDER", so3)) == 1, "confirming again starts a fresh approval")

# --- ۴: رویداد تکراری فرایند دوم روی همان سند نمی‌سازد ----------------------------------------------------------------
with new_session() as s:
    events.publish(s, company_id, "SALES_ORDER_CONFIRMED", "SALES_ORDER", so3, {"to": "CONFIRMED"}, actor_user_id=seller)
    s.commit()
events.dispatch_pending(company_id)
check(len(running("SALES_ORDER", so3)) == 1, "the same document never runs the same process twice")

# --- ۵: سند حسابداری (بدون اقدام «رد»): پس از رد از نوار گردش کار دوباره فرستاده می‌شود ---------------------------------
je_def = publish("je_flow", "JOURNAL_ENTRY", ["JOURNAL_ENTRY_TEMPORARY"], changes=False, reject=False)
je = je_service.create_journal_entry(company_id, seller, today, "سند اصلاحی", [
    je_service.LineInput(cash_gl.account_id, "ب", D(10), D(0)), je_service.LineInput(discount_gl.account_id, "ب", D(0), D(10))]
).journal_entry_id
tasks.decide(company_id, task_of("JOURNAL_ENTRY", je, boss).task_id, boss, "REJECT", "شرح ناقص است")
check(je_context(company_id, je)["status"] == "TEMPORARY" and model_events.unsent_gate(company_id, "JOURNAL_ENTRY", je) == [je_def],
      "rejected entry stays editable and can be sent again")
check(raises(lambda: je_service.approve_journal_entry(je, company_id, boss), "برای تایید بفرستید"),
      "making it permanent still needs the process")
bar = WorkflowBar()
bar.set_entity("JOURNAL_ENTRY", je)
check(bar.send_button.isEnabled() and "رد شد" in bar.warning.text(), f"the bar offers «send again» ({bar.warning.text()})")
check(bar.send() and len(running("JOURNAL_ENTRY", je)) == 1, "sent again from the document")
tasks.decide(company_id, task_of("JOURNAL_ENTRY", je, boss).task_id, boss, "APPROVE", "")
check(je_context(company_id, je)["status"] == "PERMANENT", "approved and made permanent")
draft_je = je_service.create_journal_entry(company_id, seller, today, "بدون فرایند", [
    je_service.LineInput(cash_gl.account_id, "ب", D(5), D(0)), je_service.LineInput(discount_gl.account_id, "ب", D(0), D(5))]
).journal_entry_id
check(len(running("JOURNAL_ENTRY", draft_je)) == 1, "a new entry starts the process by itself")

# --- ۶: درخواست خرید: برگشت برای اصلاح در خود فرم ---------------------------------------------------------------------
pr_def = publish("pr_flow", "PURCHASE_REQUEST", ["PURCHASE_REQUEST_SUBMITTED"])
login(seller)
req = pr_service.create_request(company_id, seller, pr_service.RequestFields(request_date=today, warehouse_id=warehouse_id))
pr_service.add_line(req, company_id, item_a, pcs, D(3))
pr_service.submit_request(req, company_id)
tasks.decide(company_id, task_of("PURCHASE_REQUEST", req, boss).task_id, boss, "CHANGES", "مقدار را دو برابر کنید")
check(pr_service.get_request(req, company_id)[0].status_code == "DRAFT", "the request is editable again")
from peecha.ui.screens.purchase_requests import PurchaseRequestScreen  # noqa: E402

scr = PurchaseRequestScreen()
scr.refresh()
scr.edit_document(req)
check(scr.buttons["save"].isEnabled() and scr.buttons["submit"].isEnabled() and "دو برابر" in scr.workflow_bar.warning.text(),
      "the requester can edit and re-send, and sees the reviewer's note")
line = pr_service.get_request(req, company_id)[1][0]
pr_service.update_line(line.line_id, req, company_id, D(6), None, None, None, None)
scr.submit()
check(len(runtime.list_instances(company_id, entity_type="PURCHASE_REQUEST", entity_id=req)) == 1
      and task_of("PURCHASE_REQUEST", req, boss) is not None, "re-sending goes back to the same reviewer")
tasks.decide(company_id, task_of("PURCHASE_REQUEST", req, boss).task_id, boss, "APPROVE", "")
check(pr_service.get_request(req, company_id)[0].status_code == "APPROVED", "approved after the correction")

# --- ۷: اقدام خودکار ناموفق در «کارتابل من» مدیر، با «اجرای دوباره» --------------------------------------------------
from peecha.services.workflow import inbox  # noqa: E402

real = documents_service.approve_document


def refuse(*_a, **_k):
    raise ValueError("قفل اعتباری مشتری باز است.")


documents_service.approve_document = refuse
so4 = order()
tasks.decide(company_id, task_of("SALES_ORDER", so4, boss).task_id, boss, "APPROVE", "")
documents_service.approve_document = real
check(status(so4) == "CONFIRMED", "the automatic approval failed")
cards = [w for w in inbox.my_work(company_id, uid) if w.source == "FAILED"]
check(len(cards) == 1 and "تصویب سند" in cards[0].action and "قفل اعتباری" in cards[0].status_note,
      f"the failure is a card in the manager's cartable ({[(w.action, w.status_note) for w in cards]})")
check(not [w for w in inbox.my_work(company_id, boss) if w.source == "FAILED"], "not in a non-manager approver's cartable")
from peecha.ui.screens.my_tasks import MyTasksScreen  # noqa: E402

login(uid)
mt = MyTasksScreen(None)
mt.refresh()
check(mt.select_key(cards[0].key) and inbox.detail(company_id, uid, cards[0].key)["instructions"], "card opens with the reason")
check(mt.retry_failed() and status(so4) == "APPROVED", "retried from the cartable: the order is approved")
check(not [w for w in inbox.my_work(company_id, uid) if w.source == "FAILED"], "the card is gone")

fx.finish()
