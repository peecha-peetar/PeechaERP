"""R313: کنترل بودجه در سرویس — هشدار، تأیید سطح بالاتر، مسدودسازی، مجوز استثنا با تفکیک نقش، بودجهٔ صفر، دورهٔ بسته،
خرید خارج از بودجه، کنترل تجمعی، پیش‌تعهد درخواست خرید، پیش‌بررسی اصلاح فاکتور، آزادسازی بی‌مانع و دو کاربر هم‌زمان."""
import os, sys, threading
os.environ["PEECHA_DB_NAME"] = "peecha_test_r313_control"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bud_fixture import *  # noqa: F401,F403
import bud_fixture as fx
from peecha.services import roles as roles_service
from peecha.services import users as users_service
from peecha.services.budgeting import roles_setup
from peecha.db.models.budgeting import BudgetException, ControlEvent
from peecha.db.models.audit import ActivityLog

check, raises = fx.check, fx.raises
roles_service.ensure_catalog()
roles = roles_setup.ensure_role_templates(company_id)


def user(name, role):
    u = users_service.create_user(name, name, "secret123", None, None, False, [company_id], company_id).user_id
    roles_service.set_user_role(u, roles[role], company_id, True)
    return u


approver, controller = user("bud_appr", "BUD_APPROVER"), user("bud_ctrl", "BUD_CONTROLLER")

bid, vid, (l_a, l_b, l_pj) = make_budget([
    (P(cost_center_detail_account_id=cc_a), D(1_000_000)), (P(cost_center_detail_account_id=cc_b), D(500_000)),
    (P(project_detail_account_id=pj_1), D(0))])
# سیاست ردیف B: مسدود
from peecha.db.models.budgeting import BudgetLine  # noqa: E402
toggle(sc.BUD_ENFORCE, True)


def exceptions_of(doc_id):
    with new_session() as s:
        return list(s.scalars(select(BudgetException).where(BudgetException.source_document_id == doc_id)
                              .order_by(BudgetException.exception_id)))


def events_of(doc_id):
    with new_session() as s:
        return [e.outcome_code for e in s.scalars(select(ControlEvent).where(ControlEvent.source_document_id == doc_id)
                                                  .order_by(ControlEvent.event_id))]


# ===== ۱) فقط هشدار (پیش‌فرض) =====
o1 = po([(other, 12, 100_000)], cc=cc_a)                      # 1,200,000 > 1,000,000
check(status(o1) == "CONFIRMED" and "WARN" in events_of(o1), "WARN policy: order confirmed, warning recorded")
msgs = bctl.document_messages(company_id, "PURCHASE_ORDER", o1)
check(msgs and "بیشتر از بودجه" in msgs[0], f"warning text for the document form ({msgs})")
docs.cancel_document(o1, company_id, note="x", cancelled_by_user_id=uid)
check(totals(l_a)["COMMIT"] == 0, "release is never blocked")

# ===== ۲) نیاز به تأیید سطح بالاتر =====
bc.save_settings(company_id, uid, "APPROVAL", 90, "ANNUAL", "ALLOW")
with new_session() as s:
    logged = s.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.entity_type == "BUDGET_SETTINGS"))
check(logged == 1, "policy change is audited")
o2 = make_doc("PURCHASE_ORDER", [(other, 11, 100_000)], cc=cc_a)  # 1,100,000
check(raises(lambda: confirm(o2), "تأیید سطح بالاتر") and status(o2) == "DRAFT", "APPROVAL policy: confirmation stopped in the service")
ex = exceptions_of(o2)
check(len(ex) == 1 and ex[0].status_code == "PENDING" and ex[0].level_code == "APPROVAL" and ex[0].excess_amount == D(100_000)
      and events_of(o2) == ["NEEDS_APPROVAL"], "pending permission request (excess 100,000) and control trail survive the rollback")
check(totals(l_a)["COMMIT"] == 0, "nothing committed while waiting")
check(raises(lambda: bex.decide(company_id, uid, ex[0].exception_id, True, "خودم"), "خودش"), "requester cannot approve own request")
check(raises(lambda: bex.decide(company_id, controller, ex[0].exception_id, False, ""), "دلیل"), "rejection needs a reason")
bex.decide(company_id, approver, ex[0].exception_id, True, "پروژهٔ فوری")
confirm(o2)
ex = exceptions_of(o2)
check(status(o2) == "CONFIRMED" and ex[0].status_code == "USED" and events_of(o2)[-1] == "EXCEPTION_USED"
      and totals(l_a)["COMMIT"] == D(1_100_000), "after approval the confirmation consumes the permission")
docs.revert_to_draft(o2, company_id)
check(raises(lambda: confirm(o2), "تأیید سطح بالاتر"), "a used permission is not reusable after revert")
docs.cancel_document(o2, company_id, note="x", cancelled_by_user_id=uid)

# ===== ۳) مسدود (سیاست ردیف) و مجوز ویژه =====
from peecha.db.base import new_session as _ns  # noqa: E402
toggle(sc.BUD_SELF_APPROVAL, True)
rv = bud.create_revision(company_id, uid, bid, "AMENDMENT", "مسدودسازی ردیف B")
bline = next(x for x in bud.get_version(company_id, rv).lines if x.key_id == key_of(l_b))
bud.update_line(company_id, uid, bline.line_id, D(500_000), policy_code="BLOCK")
for step in (bap.submit, bap.review, bap.approve, bap.publish):
    step(company_id, uid, rv)
toggle(sc.BUD_SELF_APPROVAL, False)
o3 = make_doc("PURCHASE_ORDER", [(other, 6, 100_000)], cc=cc_b)
check(raises(lambda: confirm(o3), "استثنای ویژه"), "BLOCK line: confirmation stopped")
e3 = exceptions_of(o3)[0]
check(e3.level_code == "BLOCK" and raises(lambda: bex.decide(company_id, approver, e3.exception_id, True, "ok"), "مجوز استثنای ویژه"),
      "a normal approver cannot lift a BLOCK; the special-exception permission is required")
bex.decide(company_id, controller, e3.exception_id, True, "تصمیم هیئت‌مدیره")
confirm(o3)
check(status(o3) == "CONFIRMED", "special exception lets the blocked order through")

# ===== ۴) بودجهٔ صفر =====
o4 = make_doc("PURCHASE_ORDER", [(other, 1, 10_000)], pj=pj_1)
check(raises(lambda: confirm(o4), "تأیید سطح بالاتر") and exceptions_of(o4)[0].excess_amount == D(10_000),
      "zero budget: any spending is over budget")

# ===== ۵) خرید خارج از بودجه =====
o5 = make_doc("PURCHASE_ORDER", [(other, 1, 10_000)])
confirm(o5)
check(status(o5) == "CONFIRMED", "unbudgeted purchase allowed by default")
bc.save_settings(company_id, uid, "APPROVAL", 90, "ANNUAL", "BLOCK")
o6 = make_doc("PURCHASE_ORDER", [(other, 1, 10_000)])
check(raises(lambda: confirm(o6), "خارج از بودجه") and exceptions_of(o6)[0].level_code == "UNBUDGETED",
      "unbudgeted policy BLOCK stops it and asks for a special exception")
bc.save_settings(company_id, uid, "APPROVAL", 90, "ANNUAL", "ALLOW")

# ===== ۶) دورهٔ بسته =====
cur = bud.period_of(bud.get_budget(company_id, bid).periods, today)
bud.set_period_closed(company_id, uid, bid, cur.period_no, True, "بستن ماه")
o7 = make_doc("PURCHASE_ORDER", [(other, 1, 10_000)], cc=cc_a)
check(raises(lambda: confirm(o7), "بسته") and exceptions_of(o7)[0].level_code == "CLOSED", "closed period: no new consumption")
check(raises(lambda: bud.set_period_closed(company_id, uid, bid, cur.period_no, False), "علت"), "reopening a period needs a reason")
bud.set_period_closed(company_id, uid, bid, cur.period_no, False, "اصلاح سند جاافتاده")
confirm(o7)
check(status(o7) == "CONFIRMED", "after reopening the period the order passes")

# ===== ۷) کنترل تجمعی تا پایان دوره =====
cum = sum((amt for no, amt in bud.get_version(company_id, rv).lines[0].periods.items() if no <= cur.period_no), D(0))
used = totals(l_a)["COMMIT"] + totals(l_a)["ACTUAL"]
bc.save_settings(company_id, uid, "APPROVAL", 90, "CUMULATIVE", "ALLOW")
room = cum - used
o8 = make_doc("PURCHASE_ORDER", [(other, 1, room + 1000)], cc=cc_a)
check(room > 0 and raises(lambda: confirm(o8), "تأیید سطح بالاتر"),
      f"cumulative control: only {room} of the year's budget is available up to this period")
bc.save_settings(company_id, uid, "APPROVAL", 90, "ANNUAL", "ALLOW")
confirm(o8)
check(status(o8) == "CONFIRMED", "annual control lets the same order through")

# ===== ۸) پیش‌تعهد درخواست خرید =====
toggle(sc.BUD_PR_COMMIT, True)
left = D(1_000_000) - totals(l_a)["COMMIT"]
req = prs.create_request(company_id, uid, prs.RequestFields(today, cost_center_detail_account_id=cc_a))
prs.add_line(req, company_id, other, base_uom(other), D(1), estimated_unit_price=left + 5000)
prs.submit_request(req, company_id)
check(raises(lambda: prs.approve_request(req, company_id, uid), "تأیید سطح بالاتر"), "approving a purchase request is controlled too")
toggle(sc.BUD_PR_COMMIT, False)

# ===== ۹) پیش‌بررسی اصلاح فاکتور پیش از هر اثر انبار و حسابداری =====
bc.save_settings(company_id, uid, "WARN", 90, "ANNUAL", "ALLOW")
inv = make_doc("PURCHASE_INVOICE", [(other, 1, 100_000)], pj=pj_1)
confirm(inv)
post(inv)
bc.save_settings(company_id, uid, "BLOCK", 90, "ANNUAL", "ALLOW")
corr = docs.start_invoice_correction(inv, company_id, uid)
docs.update_line(docs.get_document(corr, company_id)[1][0].line_id, corr, company_id, D(1), D(300_000))
confirm(corr)
with new_session() as s:
    from peecha.db.models.accounting import JournalEntry
    je_before = s.scalar(select(func.count()).select_from(JournalEntry))
check(raises(lambda: docs.post_invoice_correction(corr, company_id, uid), "اصلاح بودجه"), "correction that raises spending is checked first")
with new_session() as s:
    je_after = s.scalar(select(func.count()).select_from(JournalEntry))
check(je_before == je_after and status(corr) == "CONFIRMED" and status(inv) == "POSTED",
      "rejected correction left no journal entry or stock document behind")

# ===== ۱۰) دو کاربر هم‌زمان: فقط یکی از مانده عبور می‌کند =====
bc.save_settings(company_id, uid, "BLOCK", 90, "ANNUAL", "ALLOW")
with new_session() as s:
    pass
spent = totals(l_a)["COMMIT"] + totals(l_a)["ACTUAL"]
left = D(1_000_000) - spent
part = (left * D("0.6")).quantize(D(1))
racers = [make_doc("PURCHASE_ORDER", [(other, 1, part)], cc=cc_a) for _ in range(2)]
gate, results = threading.Barrier(2), {}


def race(d):
    gate.wait()
    try:
        confirm(d)
        results[d] = "ok"
    except ValueError as e:
        results[d] = str(e)


threads = [threading.Thread(target=race, args=(d,)) for d in racers]
[t.start() for t in threads]
[t.join() for t in threads]
ok = [d for d, r in results.items() if r == "ok"]
check(len(ok) == 1 and totals(l_a)["COMMIT"] + totals(l_a)["ACTUAL"] <= D(1_000_000),
      f"two concurrent confirmations: exactly one passes, budget never exceeded ({list(results.values())})")

fx.finish()
