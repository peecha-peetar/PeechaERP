"""R313: تعریف و گردش تأیید بودجه — دسترسی، تفکیک نقش، توزیع دوره‌ای و سازگاری جمع، تعیین مبلغ مصوب، رد و بازگشایی،
تاریخچهٔ تصمیم، قفل نسخهٔ مصوب و دفتر مصرف در پایگاه داده، دورهٔ بسته در اصلاحیه، بودجهٔ تکمیلی، انتقال بودجهٔ ساده و
دروازهٔ گردش کار (تأیید فقط از مسیر فرایند)."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r313_approval"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bud_fixture import *  # noqa: F401,F403
import bud_fixture as fx
from sqlalchemy import text as sql
from peecha.services import roles as roles_service
from peecha.services import users as users_service
from peecha.services import purchase_budgets as simple_budgets
from peecha.services.budgeting import roles_setup

check, raises = fx.check, fx.raises
roles_service.ensure_catalog()
roles = roles_setup.ensure_role_templates(company_id)
check(set(roles) == {"BUD_PREPARER", "BUD_OFFICER", "BUD_APPROVER", "BUD_CONTROLLER", "BUD_BUYER", "BUD_VIEWER"}
      and roles_setup.ensure_role_templates(company_id) == roles, "six ready-made budget roles; re-running does not duplicate")


def user(name, role):
    u = users_service.create_user(name, name, "secret123", None, None, False, [company_id], company_id).user_id
    roles_service.set_user_role(u, roles[role], company_id, True)
    return u


prep, officer, appr, viewer = user("prep", "BUD_PREPARER"), user("officer", "BUD_OFFICER"), user("appr", "BUD_APPROVER"), \
    user("viewer", "BUD_VIEWER")

# ===== ۱) تعریف و دسترسی =====
check(raises(lambda: bud.create_budget(company_id, viewer, fy_id, "X", "x"), "دسترسی"), "viewer cannot create a budget")
bid = bud.create_budget(company_id, prep, fy_id, "OPEX", "بودجهٔ عملیاتی", "QUARTER")
b = bud.get_budget(company_id, bid)
check(len(b.periods) == 4 and b.periods[0].date_from == fy_start and b.periods[-1].date_to == fy_end and b.versions[0].status_code == "DRAFT",
      "quarterly budget: 4 periods covering the fiscal year, original draft version")
check(raises(lambda: bud.create_budget(company_id, prep, fy_id, "opex", "دوباره"), "قبلاً"), "budget code is unique per company")
vid = b.versions[0].version_id
l1 = bud.add_line(company_id, prep, vid, P(cost_center_detail_account_id=cc_a), D(1_000_000), method="WEIGHTS", weights=[1, 2, 3, 4])
l2 = bud.add_line(company_id, prep, vid, bud.Dims("ACCOUNT", account_id=office_gl.account_id, cost_center_detail_account_id=cc_b), D(400_000))
v = bud.get_version(company_id, vid)
check(v.lines[0].periods == {1: D(100_000), 2: D(200_000), 3: D(300_000), 4: D(400_000)}, "weighted distribution 1:2:3:4")
check(v.lines[1].periods == {1: D(100_000), 2: D(100_000), 3: D(100_000), 4: D(100_000)}, "equal distribution by default")
check(raises(lambda: bud.add_line(company_id, prep, vid, P(cost_center_detail_account_id=cc_a), D(5)), "همین ابعاد"),
      "one line per dimension set in a version")
check(raises(lambda: bud.add_line(company_id, prep, vid, bud.Dims("ACCOUNT"), D(5)), "حساب"), "GL line needs an account")
check(raises(lambda: bud.add_line(company_id, prep, vid, P(account_id=office_gl.account_id), D(5)), "حساب دفتر کل"),
      "purchase line does not take an account")
check(raises(lambda: bud.set_period_amounts(company_id, prep, l1, {1: D(1), 2: D(2)}), "برابر نیست"), "manual periods must sum to the line")
bud.set_period_amounts(company_id, prep, l1, {1: D(250_000), 2: D(250_000), 3: D(250_000), 4: D(250_000)})
check(bud.get_version(company_id, vid).lines[0].periods[4] == D(250_000), "manual distribution saved")

# ===== ۲) گردش تأیید با تفکیک نقش =====
check(raises(lambda: bap.review(company_id, officer, vid), "وضعیت"), "cannot review before submission")
bap.submit(company_id, prep, vid, "پیشنهاد سال جدید")
check(raises(lambda: bud.update_line(company_id, prep, l1, D(1)), "پیش‌نویس"), "submitted version is not editable by the preparer")
check(raises(lambda: bap.review(company_id, prep, vid), "دسترسی"), "preparer cannot review")
bud.set_approved_amount(company_id, officer, l1, D(800_000), "کاهش به‌خاطر سقف کل")
v = bud.get_version(company_id, vid)
check(v.lines[0].approved_amount == D(800_000) and sum(v.lines[0].periods.values()) == D(800_000)
      and v.lines[0].periods[1] == D(200_000), "approved amount set at review; periods scaled proportionally")
bap.review(company_id, officer, vid, "بررسی شد")
check(raises(lambda: bap.approve(company_id, officer, vid), "دسترسی"), "reviewer has no approval permission")
bap.approve(company_id, appr, vid, "تصویب")
check(raises(lambda: bap.publish(company_id, appr, vid), "دسترسی"), "approver cannot publish (separate step)")
bap.publish(company_id, officer, vid)
v = bud.get_version(company_id, vid)
check(v.status_code == "PUBLISHED" and v.lines[1].approved_amount == D(400_000), "published; untouched line approved as proposed")
acts = [d.action_code for d in v.decisions]
check(acts == ["CREATE", "SUBMIT", "ADJUST", "REVIEW", "APPROVE", "PUBLISH"] and v.prepared_by == "prep" and v.approved_by == "appr",
      f"decision history with users and comments ({acts})")

# ===== ۳) قفل نسخهٔ مصوب و دفتر مصرف در پایگاه داده =====
check(raises(lambda: bud.update_line(company_id, prep, l1, D(1)), "پیش‌نویس"), "published line not editable in the service")
with new_session() as s:
    try:
        s.execute(sql("UPDATE bud.budget_lines SET approved_amount = 1 WHERE line_id = :l"), {"l": l1})
        s.commit()
        locked = False
    except Exception as e:  # noqa: BLE001
        locked = "BUD_LOCKED" in str(e)
check(locked, "database trigger rejects changing an approved line")
with new_session() as s:
    try:
        s.execute(sql("UPDATE bud.budget_versions SET valid_to = valid_from WHERE version_id = :v"), {"v": vid})
        s.commit()
        locked = False
    except Exception as e:  # noqa: BLE001
        locked = "BUD_LOCKED" in str(e)
check(locked, "database trigger rejects changing a published version")
o = po([(other, 1, 1000)], cc=cc_a)
with new_session() as s:
    try:
        s.execute(sql("UPDATE bud.consumption_entries SET amount = 0"))
        s.commit()
        locked = False
    except Exception as e:  # noqa: BLE001
        locked = "BUD_LOCKED" in str(e)
check(locked, "consumption ledger is append-only")

# ===== ۴) اصلاحیه: رد، بازگشایی، دورهٔ بسته =====
bud.set_period_closed(company_id, officer, bid, 1, True, "بستن فصل اول")
check(raises(lambda: bud.set_period_closed(company_id, prep, bid, 2, True), "دسترسی"), "closing a period needs the period permission")
am = bud.create_revision(company_id, prep, bid, "AMENDMENT", "اصلاحیهٔ میان‌سال")
line_a = next(x for x in bud.get_version(company_id, am).lines if x.key_id == key_of(l1))
check(raises(lambda: bud.set_period_amounts(company_id, prep, line_a.line_id, {1: D(0), 2: D(400_000), 3: D(200_000), 4: D(200_000)}),
             "بسته"), "closed period amount cannot change in an amendment")
bud.update_line(company_id, prep, line_a.line_id, D(1_000_000))
pa = bud.get_version(company_id, am).lines[0]
check(pa.periods[1] == D(200_000) and sum(pa.periods.values()) == D(1_000_000) and pa.change == D(200_000),
      "amendment keeps the closed period, spreads the rest; change = +200,000")
bap.submit(company_id, prep, am)
bap.review(company_id, officer, am)
check(raises(lambda: bap.reject(company_id, appr, am, ""), "دلیل"), "rejection needs a reason")
bap.reject(company_id, appr, am, "توجیه کافی نیست")
check(bud.get_version(company_id, am).status_code == "REJECTED" and bud.get_version(company_id, am).reject_reason == "توجیه کافی نیست",
      "rejected with reason")
bap.reopen(company_id, prep, am, "اصلاح توجیه")
check(bud.get_version(company_id, am).status_code == "DRAFT", "rejected version reopened for editing")
check([d.action_code for d in bud.get_version(company_id, am).decisions] == ["CREATE", "SUBMIT", "REVIEW", "REJECT", "REOPEN"],
      "amendment history kept")
bap.cancel(company_id, prep, am, "منصرف شدیم")

# ===== ۵) بودجهٔ تکمیلی فقط افزایشی =====
sup = bud.create_revision(company_id, prep, bid, "SUPPLEMENT")
sl = next(x for x in bud.get_version(company_id, sup).lines if x.key_id == key_of(l1))
bud.update_line(company_id, prep, sl.line_id, D(700_000))
check(raises(lambda: bap.submit(company_id, prep, sup), "تکمیلی فقط"), "supplementary budget cannot decrease a line")
bud.update_line(company_id, prep, sl.line_id, D(900_000))
bap.submit(company_id, prep, sup)
bap.reopen(company_id, prep, sup)
bap.cancel(company_id, prep, sup, "آزمون")

# ===== ۶) تفکیک نقش حتی با دسترسی کامل =====
both = user("both", "BUD_OFFICER")
roles_service.set_user_role(both, roles["BUD_PREPARER"], company_id, True)
b2 = bud.create_budget(company_id, both, fy_id, "CAPEX", "بودجهٔ سرمایه‌ای", "YEAR")
v2 = bud.list_budgets(company_id)[0].open_version_id
v2 = next(x.open_version_id for x in bud.list_budgets(company_id) if x.budget_id == b2)
bud.add_line(company_id, both, v2, P(project_detail_account_id=pj_1), D(2_000_000))
bap.submit(company_id, both, v2)
check(raises(lambda: bap.review(company_id, both, v2), "متفاوت"), "the preparer cannot review own budget even with the role")
toggle(sc.BUD_SELF_APPROVAL, True)
bap.review(company_id, both, v2)
toggle(sc.BUD_SELF_APPROVAL, False)
check(raises(lambda: bap.approve(company_id, appr, v2), "متفاوت") is False, "approver differs from preparer/reviewer → allowed")

# ===== ۷) انتقال بودجهٔ سادهٔ خرید (R243) =====
simple_budgets.save_budget(company_id, simple_budgets.BudgetFields("OLD", "بودجهٔ سادهٔ قدیمی", fy_start, fy_end, D(300_000),
                                                                    cost_center_detail_account_id=cc_b))
b3 = bud.create_budget(company_id, prep, fy_id, "IMPORT", "انتقال", "MONTH")
v3 = next(x.open_version_id for x in bud.list_budgets(company_id) if x.budget_id == b3)
check(bud.import_simple_budgets(company_id, prep, v3) == 1 and bud.import_simple_budgets(company_id, prep, v3) == 0,
      "simple purchase budgets imported once as draft lines")

# ===== ۸) دروازهٔ گردش کار: تأیید فقط از مسیر فرایند =====
from peecha.services.workflow import definitions as defs, runtime, tasks  # noqa: E402
graph = {"trigger": {"type": "EVENT", "events": ["BUDGET_VERSION_REVIEWED"], "gate": True},
         "nodes": [{"id": "ap", "type": "APPROVAL", "label": "تأیید هیئت‌مدیره", "approvers": [{"kind": "USER", "user_id": uid}]},
                   {"id": "act", "type": "ACTION", "label": "تأیید نسخه", "action": "entity.approve"},
                   {"id": "ok", "type": "END", "label": "تأیید", "outcome": "APPROVED"},
                   {"id": "no", "type": "END", "label": "رد", "outcome": "REJECTED"}],
         "edges": [{"from": "start", "to": "ap"}, {"from": "ap", "to": "act", "when": "approved"}, {"from": "act", "to": "ok"},
                   {"from": "ap", "to": "no", "when": "rejected"}]}
gd = defs.create_definition(company_id, uid, code="BUD_GATE", name="تأیید بودجه", entity_type="BUDGET_VERSION", graph=graph)
defs.publish(company_id, uid, gd)
b4 = bud.create_budget(company_id, prep, fy_id, "WF", "بودجه با فرایند", "YEAR")
v4 = next(x.open_version_id for x in bud.list_budgets(company_id) if x.budget_id == b4)
bud.add_line(company_id, prep, v4, P(cost_center_detail_account_id=cc_b), D(100_000))
bap.submit(company_id, prep, v4)
bap.review(company_id, officer, v4)
check(raises(lambda: bap.approve(company_id, appr, v4), "تایید"), "with a gated process the built-in approval is refused")
t = tasks.list_tasks(company_id, entity_type="BUDGET_VERSION", entity_id=v4, status="OPEN")
check(bool(t), "the approval task is in the workflow cartable")
tasks.decide(company_id, t[0].task_id, uid, "APPROVE", "تأیید هیئت‌مدیره")
check(bud.get_version(company_id, v4).status_code == "APPROVED", "workflow approval moves the version to approved")
bap.publish(company_id, officer, v4)
check(bud.get_version(company_id, v4).status_code == "PUBLISHED", "published after workflow approval")

fx.finish()
