"""R312: گردش کامل نگهداری — درخواست (ماشین متوقف) ← توقف و کسر ظرفیت ← بررسی/تأیید ← دستور کار ← اجرا و چک‌لیست ←
انجام‌شده (ماشین هنوز آماده نیست) ← آزمون ← آماده‌به‌کاری ← بستن؛ رد/لغو، تعلیق، بازگشایی، قفل وضعیت، تأیید جداگانه."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r312_flow"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mnt_fixture import *  # noqa: F401,F403
import mnt_fixture as fx
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError
from peecha.db.models.maintenance import WorkOrder, DowntimeEvent
from peecha.services import users as users_service

check, raises = fx.check, fx.raises

# ===== ۱) تجهیز = همان دارایی؛ سلسله‌مراتب و کارت =====
m1 = machine("M-01")
m2 = machine("M-02")
spindle = machine("M-01-SP", parent=m1, production=False)
eq.save_profile(company_id, uid, m1, criticality_code="HIGH", technical_specs=[("توان", "۱۵ کیلووات"), ("دور", "۱۴۵۰")],
                meter_unit="ساعت کارکرد", responsible_user_id=uid, safety_notes="قفل و برچسب پیش از باز کردن قاب")
rows = {r.asset_id: r for r in eq.list_equipment(company_id)}
check(set(rows) >= {m1, m2, spindle} and rows[m1].criticality_label == "حیاتی" and rows[m1].line == "خط ۱"
      and rows[m1].serial_no == "SN-M-01" and rows[m1].manufacturer == "سازندهٔ الف",
      "equipment list reads identity (serial, manufacturer, line) from the fixed asset itself")
tree = eq.tree(company_id)
site_node = next(n for n in tree if n.id == fx.site)
plant_node = site_node.children[0]
area_node = plant_node.children[0]
line_node = area_node.children[0]
m1_node = next(n for n in line_node.children if n.id == m1)
check(plant_node.label.startswith("کارخانه") and area_node.label.startswith("ناحیه") and line_node.label.startswith("خط تولید")
      and [ch.id for ch in m1_node.children] == [spindle],
      "hierarchy: site › plant › area › line › machine › sub-equipment")
check(eq.find(company_id, fa.qr_payload(fa.get_asset(company_id, m1))) == m1 and eq.find(company_id, "M-02") == m2
      and eq.find(company_id, "NOPE") is None, "QR payload / code opens the same equipment")
card = eq.card(company_id, m1)
check(card.serial_no == "SN-M-01" and card.supplier == "فروشندهٔ ماشین" and card.criticality_label == "حیاتی"
      and ("توان", "۱۵ کیلووات") in card.technical_specs and card.children[0].asset_id == spindle and card.qr.startswith("PEECHA-FA:")
      and card.kpi.mttr.insufficient and card.kpi.mttr.display == "داده ناکافی",
      "equipment card: identity from the asset, maintenance profile, sub-equipment, KPI 'insufficient data'")
with new_session() as s:
    n_profiles = s.scalar(text("SELECT count(*) FROM mnt.equipment_profiles WHERE asset_id = :a"), {"a": m1})
eq.save_profile(company_id, uid, m1, criticality_code="HIGH")
with new_session() as s:
    check(s.scalar(text("SELECT count(*) FROM mnt.equipment_profiles WHERE asset_id = :a"), {"a": m1}) == n_profiles == 1,
          "one maintenance profile per asset (no duplicate equipment master)")

# ===== ۲) درخواست با ماشین متوقف: توقف + وضعیت دارایی + ظرفیت =====
week = (today, today + days(6))
full = cap(*week)
check(full.machines_total == 2 and full.capacity_hours == full.nominal_capacity_hours, "both machines available before the failure")
stop_at = (datetime.datetime.now() - days(hours=10)).replace(second=0, microsecond=0).astimezone()
r1 = mreq.create(company_id, uid, m1, "لرزش شدید و صدای غیرعادی", "از شیفت صبح", failure_at=stop_at, machine_stopped=True,
                 severity_code="HIGH", probable_cause="بلبرینگ", source_code="QR", idempotency_key="REQ-1")
check(mreq.create(company_id, uid, m1, "لرزش شدید و صدای غیرعادی", failure_at=stop_at, machine_stopped=True,
                  idempotency_key="REQ-1") == r1, "same idempotency key → same request (no duplicate from mobile retry)")
check(asset_status(m1) == "UNDER_MAINTENANCE", "machine-stopped request puts the asset under maintenance (same transaction)")
downs = av.list_downtimes(company_id, open_only=True)
check(len(downs) == 1 and downs[0].asset_id == m1 and downs[0].request_id == r1 and downs[0].type_code == "BREAKDOWN",
      "one open breakdown downtime is recorded with the failure time")
c_down = cap(*week)
check(c_down.capacity_hours == c_down.nominal_capacity_hours / 2 and [m.code for m in c_down.down_machines] == ["M-01"],
      "out-of-service machine is not counted in available capacity")
r2 = mreq.create(company_id, uid, m1, "نشت روغن", machine_stopped=True)
check(len(av.list_downtimes(company_id, open_only=True)) == 1, "second report on a stopped machine joins the same downtime")

# قفل وضعیت: بدون کلید، تغییر دستی آزاد (رفتار قبلی)؛ با کلید، تا توقف باز است ممنوع
toggle(sc.MNT_STATUS_LOCK, True)
check(raises(lambda: fa.set_status(company_id, uid, m1, "IN_SERVICE", today), "آماده‌به‌کاری فقط از دستور کار"),
      "status lock: a manual 'in service' while the downtime is open is refused")
check(asset_status(m1) == "UNDER_MAINTENANCE", "status unchanged after the refused manual change")
fa.set_status(company_id, uid, m2, "SUSPENDED", today, "بدون سفارش")
fa.set_status(company_id, uid, m2, "IN_SERVICE", today)
check(asset_status(m2) == "IN_SERVICE", "status lock does not affect machines without an open downtime")
toggle(sc.MNT_STATUS_LOCK, False)

# ===== ۳) بررسی، ارجاع، رد، تبدیل =====
tech = users_service.create_user("tech1", "تکنسین یک", "secret123", None, None, False, [company_id], company_id)
sup = users_service.create_user("sup1", "سرپرست یک", "secret123", None, None, False, [company_id], company_id)
mreq.evaluate(company_id, uid, r1, "URGENT", note="خط متوقف است")
mreq.refer(company_id, uid, r1, sup.user_id, "بررسی سرپرست")
q = {r.request_id: r for r in mreq.queue(company_id)}
check(q[r1].status_code == "UNDER_REVIEW" and q[r1].priority_label == "فوری" and q[r1].assigned_to == "سرپرست یک"
      and q[r1].machine_down_now, "evaluation and referral are recorded on the request")
check(raises(lambda: mreq.reject(company_id, uid, r1, "تکراری"), "آماده‌بودن ماشین نیست"),
      "rejecting a request with an open stoppage is refused (rejecting is not 'machine ready')")
mreq.reject(company_id, uid, r2, "همان خرابی درخواست قبلی")
check(mreq.get(company_id, r2).status_label == "ردشده", "duplicate request rejected with reason")
check(raises(lambda: mreq.approve(company_id, uid, r2), "ردشده"), "a rejected request cannot be approved")
mreq.approve(company_id, uid, r1, note="تأیید شد")
wo1 = mreq.convert(company_id, uid, r1, wos.WorkOrderInput(
    asset_id=m1, work_type_code="EMERGENCY", title="تعویض بلبرینگ اسپیندل", priority_code="URGENT", requires_shutdown=True,
    safety_instructions="قطع برق و قفل", tasks=[wos.TaskInput("قطع برق و نصب قفل", is_safety=True),
                                                wos.TaskInput("اندازه‌گیری لرزش پس از تعمیر", "NUMERIC", D(0), D("4.5"), "میلی‌متر بر ثانیه"),
                                                wos.TaskInput("تمیزکاری محل", is_mandatory=False)]))
check(mreq.convert(company_id, uid, r1) == wo1, "converting twice returns the same work order (no duplicate)")
with new_session() as s:
    ev = s.scalar(select(DowntimeEvent).where(DowntimeEvent.request_id == r1))
    check(ev.work_order_id == wo1 and ev.available_at is None, "the request's downtime moves to the work order")
check(mreq.get(company_id, r1).status_label == "تبدیل به دستور کار", "request status: converted")

# ===== ۴) برنامه‌ریزی، واگذاری، اجرا، تعلیق =====
wos.update_plan(company_id, uid, wo1, planned_start=stop_at + days(hours=1), planned_end=stop_at + days(hours=5), estimated_hours=D(4))
wos.assign(company_id, uid, wo1, [tech.user_id, uid], lead_user_id=tech.user_id)
d = wos.get(company_id, wo1)
check(d.status_code == "ASSIGNED" and {t.name for t in d.technicians} == {"تکنسین یک", "مدیر سیستم"}
      and next(t for t in d.technicians if t.is_lead).user_id == tech.user_id, "assigned to technicians with a lead")
check(raises(lambda: wos.complete(company_id, uid, wo1, "x"), "در وضعیت"), "cannot complete before starting")
wos.start(company_id, uid, wo1, at=stop_at + days(hours=1))
check(len(av.list_downtimes(company_id, open_only=True)) == 1, "starting a shutdown job reuses the open downtime (no second stop)")
wos.hold(company_id, uid, wo1, "انتظار قطعه")
check(raises(lambda: wos.hold(company_id, uid, wo1, ""), "علت"), "hold needs a reason")
check(wos.get(company_id, wo1).hold_reason == "انتظار قطعه", "hold reason stored")
wos.resume(company_id, uid, wo1)
check(wos.get(company_id, wo1).status_code == "IN_PROGRESS", "resume returns to in-progress")
tasks = {t.seq: t for t in wos.get(company_id, wo1).tasks}
check(raises(lambda: wos.complete(company_id, uid, wo1, "بلبرینگ تعویض شد"), "چک‌لیست"),
      "incomplete mandatory checklist blocks 'completed'")
wos.record_task(company_id, uid, tasks[1].task_id, True)
ok = wos.record_task(company_id, uid, tasks[2].task_id, value_numeric="6.1")
check(ok is False, "measured value outside the allowed range is flagged as not OK")
wos.record_task(company_id, uid, tasks[2].task_id, value_numeric="3.2")
wos.add_labor(company_id, uid, wo1, tech.user_id, today, D("3.5"), "تعویض", idempotency_key="L1")
wos.add_labor(company_id, uid, wo1, tech.user_id, today, D("3.5"), "تعویض", idempotency_key="L1")
check(len(wos.get(company_id, wo1).labor) == 1, "labor entry with the same key is not duplicated")
done_at = stop_at + days(hours=4)
wos.complete(company_id, tech.user_id, wo1, "بلبرینگ و کاسه‌نمد تعویض شد", at=done_at)
check(wos.get(company_id, wo1).status_code == "COMPLETED" and asset_status(m1) == "UNDER_MAINTENANCE"
      and len(av.list_downtimes(company_id, open_only=True)) == 1,
      "'completed' by the technician does NOT make the machine ready: still under maintenance, downtime open")
check(raises(lambda: wos.close(company_id, uid, wo1), "در وضعیت"), "a completed (unverified) work order cannot be closed")
check(raises(lambda: wos.release_machine(company_id, uid, wo1), "آزمون"), "machine cannot be released before verification")

# آزمون جداگانه: با کلید، تکنسین خودش تأیید نمی‌کند
toggle(sc.MNT_SEPARATE_VERIFY, True)
check(raises(lambda: wos.verify(company_id, tech.user_id, wo1, "PASS"), "غیر از تکنسین"),
      "separate verification: the technician cannot verify his own job")
check(raises(lambda: wos.verify(company_id, uid, wo1, "PASS"), "غیر از تکنسین"),
      "separate verification: an assigned technician (even admin) cannot verify")
wos.verify(company_id, sup.user_id, wo1, "FAIL", "لرزش هنوز زیاد است")
d = wos.get(company_id, wo1)
check(d.status_code == "IN_PROGRESS" and d.verification_label == "مردود" and d.completed_by == "",
      "failed test returns the job to in-progress")
wos.complete(company_id, tech.user_id, wo1, "بالانس مجدد انجام شد", at=done_at)
wos.verify(company_id, sup.user_id, wo1, "PASS", "لرزش ۳٫۲")
toggle(sc.MNT_SEPARATE_VERIFY, False)
check(wos.get(company_id, wo1).status_code == "VERIFIED", "verified after passing the test")
check(raises(lambda: wos.close(company_id, uid, wo1), "آماده‌به‌کاری"), "close is blocked until the machine is released")
release_at = stop_at + days(hours=5)
wos.release_machine(company_id, sup.user_id, wo1, available_at=release_at, note="تحویل به تولید")
check(asset_status(m1) == "IN_SERVICE" and not av.list_downtimes(company_id, open_only=True),
      "release after verification: downtime closed, asset back in service")
dt = [x for x in av.list_downtimes(company_id, asset_id=m1)][0]
check(dt.hours == D("5.00"), f"downtime = failure → ready-for-use (5h), independent of the job time (got {dt.hours})")
check(cap(today + days(1), today + days(6)).machines_down == 0, "future capacity is full again after release")

# ===== ۵) بستن، قفل پایگاه‌داده، بازگشایی =====
wos.close(company_id, sup.user_id, wo1, "تمام")
check(wos.get(company_id, wo1).status_code == "CLOSED", "work order closed")
with new_session() as s:
    try:
        s.execute(update(WorkOrder).where(WorkOrder.work_order_id == wo1).values(title="دستکاری"))
        s.commit()
        locked = False
    except DBAPIError as e:
        locked = "MNT_LOCKED" in str(e)
check(locked, "database trigger refuses any direct change to a closed work order")
check(raises(lambda: wos.hold(company_id, uid, wo1, "x"), "در وضعیت"), "closed work order accepts no operation")
check(raises(lambda: wos.reopen(company_id, uid, wo1, ""), "علت"), "reopen needs a reason")
wos.reopen(company_id, sup.user_id, wo1, "لرزش دوباره برگشت")
d = wos.get(company_id, wo1)
check(d.status_code == "IN_PROGRESS" and d.reopened_count == 1 and d.verification_result is None,
      "authorised reopen: back to in-progress, count recorded, test must be repeated")
wos.complete(company_id, tech.user_id, wo1, "پیچ‌های پایه سفت شد", at=release_at)
wos.verify(company_id, sup.user_id, wo1, "PASS")
wos.close(company_id, sup.user_id, wo1)
check(wos.get(company_id, wo1).status_code == "CLOSED", "closed again after the second test (no open downtime needed)")
hist = wos.history(company_id, wo1)
ops = [h.operation for h in hist]
check(ops[0] == "CREATE" and "ASSIGN" in ops and "HOLD" in ops and ops.count("VERIFY") == 3 and "RELEASE_MACHINE" in ops
      and ops.count("CLOSE") == 2 and "REOPEN" in ops and any(h.to_status == "بسته‌شده" for h in hist),
      "status history keeps every step, user and reason")
check([h.operation for h in mreq.history(company_id, r1)] == ["CREATE", "EVALUATE", "REFER", "APPROVE", "CONVERT"],
      "request history: create → evaluate → refer → approve → convert")

# ===== ۶) دستور کار اضطراری مستقیم و لغو =====
wo2 = wos.create(company_id, uid, wos.WorkOrderInput(asset_id=m2, work_type_code="EMERGENCY", title="قطع برق موتور",
                                                     machine_stopped=True), idempotency_key="WO-EM-1")
check(wos.create(company_id, uid, wos.WorkOrderInput(asset_id=m2, work_type_code="EMERGENCY", title="قطع برق موتور",
                                                     machine_stopped=True), idempotency_key="WO-EM-1") == wo2,
      "emergency work order is idempotent")
check(asset_status(m2) == "UNDER_MAINTENANCE", "direct emergency work order stops the machine")
check(raises(lambda: wos.cancel(company_id, uid, wo2, "اشتباه"), "آماده‌به‌کاری"),
      "cancelling does not silently make a stopped machine ready")
dt2 = av.list_downtimes(company_id, open_only=True)[0]
check(raises(lambda: av.release_downtime(company_id, uid, dt2.downtime_id, note="اشتباه"), "دستور کار"),
      "a downtime owned by a work order is released only from the work order")
wo3 = wos.create(company_id, uid, wos.WorkOrderInput(asset_id=spindle, work_type_code="CORRECTIVE", title="بازدید اسپیندل"))
wos.cancel(company_id, uid, wo3, "نیازی نیست")
check(wos.get(company_id, wo3).status_code == "CANCELLED", "a job without parts/costs/stoppage can be cancelled with reason")
r3 = mreq.create(company_id, uid, m2, "گزارش اشتباه", machine_stopped=False)
mreq.cancel(company_id, uid, r3, "اشتباه ثبت شد")
check(mreq.get(company_id, r3).status_code == "CANCELLED", "requester cancels own request")

# ===== ۷) پیوست (همان DMS) =====
from peecha.services.maintenance import documents as mdocs
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mnt_photo.jpg")
with open(p, "wb") as fh:
    fh.write(b"\xff\xd8photo")
att = mdocs.add(company_id, uid, "WORK_ORDER", wo1, p, "IMAGE")
att2 = mdocs.add(company_id, uid, "REQUEST", r1, None, "IMAGE", content=b"\xff\xd8mobile", file_name="crack.jpg")
os.remove(p)
check([a.attachment_id for a in mdocs.list_for(company_id, "WORK_ORDER", wo1)] == [att]
      and mdocs.list_for(company_id, "REQUEST", r1)[0].file_name == "crack.jpg",
      "photos/attachments stored in the existing document store, per request and work order")

# ===== ۸) کارتابل =====
from peecha.services import operational_tasks as ot
tasks = ot.list_operational_tasks(company_id, tech.user_id)
check(not [t for t in tasks if t.kind.startswith("MNT_") and t.kind != "MNT_MY_WORK"],
      "a technician without approval rights sees no aggregated maintenance approvals")
wo4 = wos.create(company_id, uid, wos.WorkOrderInput(asset_id=spindle, work_type_code="CORRECTIVE", title="روغن‌کاری"))
wos.assign(company_id, uid, wo4, [tech.user_id])
mine = [t for t in ot.list_operational_tasks(company_id, tech.user_id) if t.kind == "MNT_MY_WORK"]
check([t.document_id for t in mine] == [wo4], "the assigned job appears in the technician's cartable")
r5 = mreq.create(company_id, uid, m2, "بررسی کنید")
admin_kinds = {t.kind for t in ot.list_operational_tasks(company_id, uid)}
check("MNT_NEW_REQUEST" in admin_kinds, "manager's cartable shows new requests waiting for review")

fx.finish()
