"""R312: دسترسی نقش‌ها (درخواست‌کننده/برنامه‌ریز/تکنسین/سرپرست/انباردار/تأییدکننده)، هم‌زمانی (صدور، توقف، بستن)،
اتمیک بودن تراکنش، پاک‌سازی دادهٔ شرکت و مهاجرت (برگشت و اجرای دوباره)."""
import os, sys, threading
os.environ["PEECHA_DB_NAME"] = "peecha_test_r312_sec"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mnt_fixture import *  # noqa: F401,F403
import mnt_fixture as fx
from peecha.db.models.inventory import StockDocument
from peecha.db.models.maintenance import DowntimeEvent, WorkRequest
from peecha.services import roles as roles_service
from peecha.services import users as users_service
from peecha.services.maintenance import roles_setup

check, raises = fx.check, fx.raises

m1, m2 = machine("M-01"), machine("M-02")


def user(name):
    return users_service.create_user(name, name, "secret123", None, None, False, [company_id], company_id).user_id


requester, planner, tech, supervisor, store, approver, outsider = (user(n) for n in (
    "req1", "plan1", "tech1", "sup1", "store1", "appr1", "out1"))

# ===== ۱) بدون کلید: رفتار بی‌محدودیت قبلی؛ با کلید: هر گام فقط برای نقش خودش =====
r0 = mreq.create(company_id, outsider, m2, "بدون کلید", machine_stopped=False)
check(r0 > 0, "toggle off: any user who sees the screen can file a request (previous behaviour)")
toggle(sc.MNT_ROLE_PERMISSIONS, True)
roles = roles_setup.ensure_role_templates(company_id)
check(set(roles) == {"MNT_REQUESTER", "MNT_PLANNER", "MNT_TECHNICIAN", "MNT_SUPERVISOR", "MNT_STOREKEEPER", "MNT_APPROVER"}
      and roles_setup.ensure_role_templates(company_id) == roles, "six ready-made roles; re-running does not duplicate")
for uid_, code in ((requester, "MNT_REQUESTER"), (planner, "MNT_PLANNER"), (tech, "MNT_TECHNICIAN"), (supervisor, "MNT_SUPERVISOR"),
                   (store, "MNT_STOREKEEPER"), (approver, "MNT_APPROVER")):
    roles_service.set_user_role(uid_, roles[code], company_id, True)

check(raises(lambda: mreq.create(company_id, outsider, m1, "x"), "ثبت درخواست تعمیر"), "user without a role cannot file a request")
r1 = mreq.create(company_id, requester, m1, "صدای غیرعادی", machine_stopped=True)
check(r1 > 0, "requester files a request")
check(raises(lambda: mreq.approve(company_id, requester, r1), "بررسی درخواست"), "requester cannot approve")
check(raises(lambda: mreq.approve(company_id, tech, r1), "بررسی درخواست"), "technician cannot approve")
mreq.evaluate(company_id, planner, r1, "HIGH")
wo = mreq.convert(company_id, planner, r1)
wos.assign(company_id, planner, wo, [tech])
check(raises(lambda: wos.assign(company_id, tech, wo, [tech]), "بررسی درخواست"), "technician cannot re-plan / assign")
wos.start(company_id, tech, wo)
p = mparts.add_part(company_id, planner, wo, spare, wh_rm, D(1))
check(raises(lambda: mparts.issue(company_id, tech, wo, [mparts.PartLine(p, D(1))]), "صدور و برگشت قطعه"),
      "technician cannot issue stock")
mparts.issue(company_id, store, wo, [mparts.PartLine(p, D(1))])
check(raises(lambda: mparts.issue(company_id, planner, wo, [mparts.PartLine(p, D(1))]), "صدور و برگشت قطعه"),
      "planner cannot issue stock either (storekeeper only)")
cost = mcost.add_cost(company_id, tech, wo, "OTHER", "حمل قطعه", D(200_000))
check(raises(lambda: mcost.post(company_id, tech, cost, ap_gl.account_id), "ثبت مالی"), "technician cannot post a cost")
check(raises(lambda: mcost.mark_none(company_id, supervisor, cost, "x"), "ثبت مالی"), "supervisor cannot decide accounting")
mcost.mark_none(company_id, approver, cost, "در هزینهٔ حمل کلی")
wos.complete(company_id, tech, wo, "انجام شد")
check(raises(lambda: wos.verify(company_id, tech, wo, "PASS"), "آزمون"), "technician cannot verify (role)")
wos.verify(company_id, supervisor, wo, "PASS")
wos.release_machine(company_id, supervisor, wo)
wos.close(company_id, supervisor, wo)
check(wos.get(company_id, wo).status_code == "CLOSED", "full flow with separated roles reaches 'closed'")
win = av.propose_window(company_id, planner, m2, datetime.datetime.now().astimezone() + days(days=2),
                        datetime.datetime.now().astimezone() + days(days=2, hours=3), "سرویس")
check(raises(lambda: av.decide_window(company_id, planner, win, True), "تأیید توقف"), "planner cannot approve his planned stoppage")
av.decide_window(company_id, approver, win, True)
r2 = mreq.create(company_id, requester, m2, "اشتباه")
mreq.cancel(company_id, requester, r2, "اشتباه ثبت کردم")
check(mreq.get(company_id, r2).status_code == "CANCELLED", "requester can cancel his own request")
check(mc.can(company_id, uid, mc.FORM_COST), "super admin always passes")
toggle(sc.MNT_ROLE_PERMISSIONS, False)

# ===== ۲) هم‌زمانی =====
wo2 = wos.create(company_id, uid, wos.WorkOrderInput(asset_id=m2, work_type_code="CORRECTIVE", title="هم‌زمانی"))
p2 = mparts.add_part(company_id, uid, wo2, spare, wh_rm, D(2))
wos.start(company_id, uid, wo2)
with new_session() as s:
    docs_before = s.scalar(select(func.count()).select_from(StockDocument))
qty_before = on_hand(spare, wh_rm)
errors = []


def issue_once():
    try:
        mparts.issue(company_id, uid, wo2, [mparts.PartLine(p2, D(1))], idempotency_key="SAME-KEY")
    except Exception as e:   # noqa: BLE001
        errors.append(str(e))


threads = [threading.Thread(target=issue_once) for _ in range(5)]
for t in threads:
    t.start()
for t in threads:
    t.join()
with new_session() as s:
    docs_after = s.scalar(select(func.count()).select_from(StockDocument))
check(docs_after - docs_before == 1 and on_hand(spare, wh_rm) == qty_before - 1 and not errors,
      f"5 concurrent issues with one key → one stock document, stock −1 (errors: {errors[:1]})")

m3 = machine("M-03")
stop_errors = []


def stop_once(i):
    try:
        mreq.create(company_id, uid, m3, f"خرابی {i}", machine_stopped=True)
    except Exception as e:   # noqa: BLE001
        stop_errors.append(str(e))


threads = [threading.Thread(target=stop_once, args=(i,)) for i in range(4)]
for t in threads:
    t.start()
for t in threads:
    t.join()
with new_session() as s:
    open_downs = s.scalar(select(func.count()).where(DowntimeEvent.asset_id == m3, DowntimeEvent.available_at.is_(None)))
    reqs = s.scalar(select(func.count()).where(WorkRequest.asset_id == m3))
check(open_downs == 1 and reqs == 4 and not stop_errors, "4 concurrent 'machine stopped' reports → 4 requests, one open downtime")
with new_session() as s:
    nums = list(s.scalars(select(WorkRequest.request_no).where(WorkRequest.company_id == company_id)))
check(len(nums) == len(set(nums)), "request numbers stay unique under concurrency")

wos.complete(company_id, uid, wo2, "انجام شد")
wos.verify(company_id, uid, wo2, "PASS")
close_errors = []


def close_once():
    try:
        wos.close(company_id, uid, wo2)
    except Exception as e:   # noqa: BLE001
        close_errors.append(str(e))


threads = [threading.Thread(target=close_once) for _ in range(3)]
for t in threads:
    t.start()
for t in threads:
    t.join()
hist = [h.operation for h in wos.history(company_id, wo2)]
check(hist.count("CLOSE") == 1 and len(close_errors) == 2, "3 concurrent closes → closed exactly once")

# ===== ۳) اتمیک: خطا در تغییر وضعیت دارایی = نه درخواست، نه توقف =====
import peecha.services.fixed_assets.assets as fa_mod
orig = fa_mod.set_status_in_session


def boom(*a, **k):
    raise ValueError("خطای آزمایشی وضعیت دارایی")


fa_mod.set_status_in_session = boom
m4 = machine("M-04")
with new_session() as s:
    n_req = s.scalar(select(func.count()).select_from(WorkRequest))
check(raises(lambda: mreq.create(company_id, uid, m4, "خرابی", machine_stopped=True), "آزمایشی"), "failure inside the transaction surfaces")
fa_mod.set_status_in_session = orig
with new_session() as s:
    check(s.scalar(select(func.count()).select_from(WorkRequest)) == n_req
          and not s.scalar(select(func.count()).where(DowntimeEvent.asset_id == m4)) and asset_status(m4) == "IN_SERVICE",
          "rollback: no request, no downtime, asset status unchanged")

# ===== ۴) پاک‌سازی دادهٔ شرکت و مهاجرت =====
from peecha.services import data_reset
for t in ("mnt.work_orders", "mnt.work_requests", "mnt.downtime_events", "mnt.pm_plans", "mnt.equipment_profiles",
          "mnt.failure_codes", "mnt.work_order_part_moves"):
    check(t in data_reset.covered_tables(), f"data reset covers {t}")
data_reset.wipe_documents(company_id)
with new_session() as s:
    left = s.scalar(text("SELECT (SELECT count(*) FROM mnt.work_orders) + (SELECT count(*) FROM mnt.work_requests) "
                         "+ (SELECT count(*) FROM mnt.downtime_events)"))
check(left == 0, "wiping company documents removes maintenance records without FK errors")

root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
down = open(os.path.join(root, "db", "rollback", "222_maintenance_down.sql"), encoding="utf-8").read()
fac.save_location(company_id, "PL-X", "کارخانهٔ ایکس", "PLANT")
with get_engine().begin() as conn:
    conn.exec_driver_sql(down)
with new_session() as s:
    gone = s.scalar(text("SELECT count(*) FROM information_schema.schemata WHERE schema_name = 'mnt'")) == 0
    feats = s.scalar(text("SELECT count(*) FROM inv.feature_definitions WHERE feature_code LIKE 'MNT_%'"))
    plant_left = s.scalar(text("SELECT count(*) FROM fa.asset_locations WHERE location_type IN ('PLANT', 'AREA')"))
check(gone and feats == 0 and plant_left == 0, "rollback script removes the schema, toggles and new location types")
apply_pending_schema_files(get_engine())
apply_pending_schema_files(get_engine())
with new_session() as s:
    back = s.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'mnt'"))
    feats = s.scalar(text("SELECT count(*) FROM inv.feature_definitions WHERE feature_code LIKE 'MNT_%'"))
check(back == 17 and feats == 4, f"re-applying the migration (twice) restores 17 tables and 4 toggles (got {back}, {feats})")
m9 = machine("M-09")   # دارایی‌ها هم با پاک‌سازی اسناد رفته‌اند
check(mreq.create(company_id, uid, m9, "پس از مهاجرت", machine_stopped=True) > 0 and asset_status(m9) == "UNDER_MAINTENANCE",
      "module works again after re-applying the migration")

fx.finish()
