"""R312: نگهداری پیشگیرانه (تقویمی/کارکردی/هرکدام زودتر، بدون تکرار، تعویق با تأیید)، اتصال به ظرفیت تولید
(توقف برنامه‌ریزی‌شده و ظرفیت محدود، هشدار همیشگی) و شاخص‌های MTTR/MTBF با تعریف مستند و «داده ناکافی»."""
import os, sys, threading
os.environ["PEECHA_DB_NAME"] = "peecha_test_r312_pm"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mnt_fixture import *  # noqa: F401,F403
import mnt_fixture as fx
from peecha.db.models.maintenance import WorkOrder, PmPlan
from peecha.services import users as users_service

check, raises = fx.check, fx.raises

m1, m2, m3 = machine("M-01"), machine("M-02"), machine("M-03", production=False)
planner = users_service.create_user("planner1", "برنامه‌ریز", "secret123", None, None, False, [company_id], company_id)


def wo_count(plan_id):
    with new_session() as s:
        return s.scalar(select(func.count()).where(WorkOrder.pm_plan_id == plan_id))


# ===== ۱) تقویمی: سررسید گذشته → یک دستور، اجرای دوباره و هم‌زمان بی‌تکرار =====
p_cal = mpm.save_plan(company_id, uid, mpm.PlanInput(
    code="PM-OIL", asset_id=m1, title="روغن‌کاری ماهانه", trigger_code="CALENDAR", interval_days=30, start_date=today - days(5),
    estimated_hours=D(2), requires_shutdown=True, safety_instructions="قطع برق",
    tasks=[wos.TaskInput("بررسی سطح روغن"), wos.TaskInput("دمای یاتاقان", "NUMERIC", D(20), D(70), "درجه", is_safety=True)],
    parts=[(spare, wh_rm, D(1))]))
info = next(p for p in mpm.list_plans(company_id) if p.plan_id == p_cal).due
check(info.state == "OVERDUE" and info.due_date == today - days(5), "calendar plan: first due = start date, overdue")
created = mpm.generate_due(company_id, uid)
check(len(created) == 1 and wo_count(p_cal) == 1, "PM job creates one work order")
check(mpm.generate_due(company_id, uid) == [] and wo_count(p_cal) == 1, "re-running the PM job creates no duplicate")
results = []
threads = [threading.Thread(target=lambda: results.append(mpm.generate_due(company_id, uid))) for _ in range(4)]
for t in threads:
    t.start()
for t in threads:
    t.join()
check(wo_count(p_cal) == 1 and sum(len(r) for r in results) == 0, "four concurrent PM runs still leave exactly one work order")
w = wos.get(company_id, created[0])
check(w.pm_due_date == today - days(5) and len(w.tasks) == 2 and w.parts[0].planned_qty == 1 and w.requires_shutdown
      and w.safety_instructions == "قطع برق", "PM work order copies checklist, parts, safety and shutdown flag")
check(raises(lambda: wos.cancel(company_id, uid, created[0], "نمی‌خواهیم"), "تعویق"),
      "an active plan's PM job is not cancelled silently (postponement with approval instead)")

# تعویق با تأیید (درخواست‌کننده خودش تأیید نمی‌کند، مگر مدیر کل)
pp_id = mpm.request_postponement(company_id, planner.user_id, p_cal, today + days(3), "توقف خط در تعطیلات")
check(raises(lambda: mpm.request_postponement(company_id, uid, p_cal, today + days(4), "دوباره"), "منتظر تأیید"),
      "one pending postponement per plan")
check(raises(lambda: mpm.decide_postponement(company_id, planner.user_id, pp_id, True), "خودش"),
      "the requester cannot approve his own postponement")
mpm.decide_postponement(company_id, uid, pp_id, True, "موافق")
w = wos.get(company_id, created[0])
check(w.pm_due_date == today + days(3), "approved postponement moves the open PM job's due date")
check(mpm.generate_due(company_id, uid) == [], "after postponement still no extra job")

# انجام و بستن → سررسید بعدی = انجام + فاصله
wos.start(company_id, uid, created[0])
for t in wos.get(company_id, created[0]).tasks:
    if t.result_type == "NUMERIC":
        wos.record_task(company_id, uid, t.task_id, value_numeric="55")
    else:
        wos.record_task(company_id, uid, t.task_id, True)
wos.complete(company_id, uid, created[0], "روغن‌کاری انجام شد")
wos.verify(company_id, uid, created[0], "PASS")
wos.release_machine(company_id, uid, created[0])
wos.close(company_id, uid, created[0])
plan = next(p for p in mpm.list_plans(company_id) if p.plan_id == p_cal)
check(plan.last_completed_date == today and plan.due.due_date == today + days(30) and plan.due.state == "OK",
      "closing the PM job sets last completion; next due = completion + 30 days")
check(mpm.generate_due(company_id, uid) == [], "nothing due right after completion")
check(len(mpm.generate_due(company_id, uid, as_of=today + days(30))) == 1, "due again exactly one interval later")
cal = mpm.calendar(company_id, today, today + days(90), asset_id=m1)
check(any(e.kind == "WORK_ORDER" for e in cal) and any(e.kind == "FORECAST" for e in cal),
      "PM calendar shows generated jobs and forecast dues")

# ===== ۲) کارکردی بدون داده؛ «هرکدام زودتر» با تقویم مستقل کار می‌کند =====
p_meter = mpm.save_plan(company_id, uid, mpm.PlanInput(code="PM-HRS", asset_id=m2, title="سرویس ۵۰۰ ساعته",
                                                       trigger_code="METER", meter_interval=D(500), start_date=today - days(60)))
d = mpm.get_plan(company_id, p_meter).due
check(d.state == "NO_DATA" and d.state_label == "دادهٔ کارکرد ثبت نشده", "meter plan without usage data: 'no data', not 'due'")
check(mpm.generate_due(company_id, uid, plan_ids=[p_meter]) == [], "no meter data → no generated job")
p_both = mpm.save_plan(company_id, uid, mpm.PlanInput(code="PM-BOTH", asset_id=m3, title="بازرسی فصلی", work_type_code="INSPECTION",
                                                      trigger_code="BOTH", interval_days=90, meter_interval=D(1000),
                                                      start_date=today - days(1)))
d = mpm.get_plan(company_id, p_both).due
check(d.meter_state == "NO_DATA" and d.state == "OVERDUE", "BOTH without meter data still follows the calendar")
check(len(mpm.generate_due(company_id, uid, plan_ids=[p_both])) == 1, "calendar side generates the job")
mpm.record_meter(company_id, uid, m2, today - days(2), D(300))
check(mpm.get_plan(company_id, p_meter).due.state == "OK", "300 of 500 hours: not due")
mpm.record_meter(company_id, uid, m2, today - days(1), D(250))
d = mpm.get_plan(company_id, p_meter).due
check(d.state == "DUE" and d.meter_used == 550 and d.due_date == today, "550 ≥ 500 hours: due today")
check(len(mpm.generate_due(company_id, uid, plan_ids=[p_meter])) == 1 and mpm.generate_due(company_id, uid, plan_ids=[p_meter]) == [],
      "meter-due job generated once")
p_lead = mpm.save_plan(company_id, uid, mpm.PlanInput(code="PM-LEAD", asset_id=m2, title="کالیبراسیون", trigger_code="CALENDAR",
                                                      interval_days=180, lead_days=5, start_date=today + days(3)))
check(mpm.get_plan(company_id, p_lead).due.state == "DUE", "due within lead days is generated ahead")
check(raises(lambda: mpm.save_plan(company_id, uid, mpm.PlanInput(code="PM-OIL", asset_id=m2, title="x", interval_days=10)),
             "قبلاً"), "plan code is unique")
check(raises(lambda: mpm.save_plan(company_id, uid, mpm.PlanInput(code="PM-X", asset_id=m2, title="x", trigger_code="METER")),
             "کارکرد"), "meter plan needs an interval")

# ===== ۳) ظرفیت تولید: توقف برنامه‌ریزی‌شده و ظرفیت محدود =====
nxt = today + days(1)
while (nxt.weekday() + 2) % 7 >= 6:     # یک روز کاری
    nxt += days(1)
base = cap(nxt, nxt)
check(base.machines_total == 2 and base.capacity_hours == base.nominal_capacity_hours == 8, "work day: 2 machines, 8h")
w_start = datetime.datetime.combine(nxt, datetime.time(8, 0)).astimezone()
win = av.propose_window(company_id, uid, m1, w_start, w_start + days(hours=4), "تعویض تسمه")
check(raises(lambda: av.propose_window(company_id, uid, m1, w_start + days(hours=1), w_start + days(hours=2)), "دیگری"),
      "overlapping planned stoppage refused")
c1 = cap(nxt, nxt)
check(c1.capacity_hours == 8 and any(n.kind == "PLANNED" and not n.applied for n in c1.maintenance_notices),
      "proposed stoppage: capacity unchanged but the planner always sees a warning")
av.decide_window(company_id, uid, win, True)
c2 = cap(nxt, nxt)
check(c2.capacity_hours == 8 and any("کسر نشده" in n.message for n in c2.maintenance_notices),
      "approved stoppage without the toggle: warned, not deducted (no hidden plan change)")
toggle(sc.MNT_CAPACITY_PLANNED, True)
c3 = cap(nxt, nxt)
check(c3.capacity_hours == 6 and any(n.applied for n in c3.maintenance_notices),
      f"toggle on: 4h stoppage of one of two 8h machines → 6h (got {c3.capacity_hours})")
rid = av.propose_restriction(company_id, uid, m2, D(50), nxt, nxt, "لرزش؛ کار با نصف سرعت")
check(cap(nxt, nxt).capacity_hours == 6, "proposed restriction has no numeric effect")
av.decide_restriction(company_id, uid, rid, True)
c4 = cap(nxt, nxt)
check(c4.capacity_hours == 4, f"approved 50% restriction on the other machine → 4h (got {c4.capacity_hours})")
check(raises(lambda: av.propose_restriction(company_id, uid, m2, D(100), nxt, nxt, "x"), "بین"),
      "100% is not a restriction (full stop is recorded as downtime)")
toggle(sc.MNT_CAPACITY_PLANNED, False)
check(cap(nxt, nxt).capacity_hours == 8, "toggle off: back to previous behaviour")
from peecha.services.production import reports as prd_reports
from peecha.services import purchase_reports as pr
rep = prd_reports.capacity(company_id, pr.PurchaseFilters(nxt, nxt))
row = next(r for r in rep.rows if str(r[0]).startswith("CUT"))
check("هشدار نگهداری" in [c[0] for c in rep.columns] and "توقف برنامه‌ریزی‌شده" in row[-1],
      "capacity report carries the maintenance warning column")

# ===== ۴) شاخص‌ها: MTTR / MTBF / نرخ خرابی / سهم پیشگیرانه / انجام به‌موقع =====
now = datetime.datetime.now().astimezone().replace(microsecond=0)
f = rel.Filters(date_from=today - days(59), date_to=today, asset_id=m3)
k = rel.compute(company_id, f)
check(k.by_code["MTTR"].insufficient and k.by_code["MTTR"].display == "داده ناکافی" and k.by_code["MTBF"].insufficient,
      "no breakdowns: MTTR/MTBF show 'insufficient data', not zero")
for start_h, dur in ((24 * 30, 4), (24 * 10, 2)):
    with new_session() as s:
        ev, _ = av.start(s, company_id, uid, m3, now - days(hours=start_h), "BREAKDOWN")
        av.release(s, company_id, uid, ev, now - days(hours=start_h - dur))
        s.commit()
k = rel.compute(company_id, f)
lo = datetime.datetime.combine(f.date_from, datetime.time()).astimezone()
expected_op = D((datetime.datetime.now().astimezone() - lo).total_seconds()) / 3600 - 6
check(k.by_code["MTTR"].value == 3 and k.by_code["MTTR"].numerator == 6 and k.by_code["MTTR"].denominator == 2,
      f"MTTR = (4h + 2h) / 2 breakdowns = 3h (got {k.by_code['MTTR'].value})")
check(abs(k.by_code["MTBF"].value - expected_op / 2) < D("0.1") and k.by_code["MTBF"].denominator == 2,
      f"MTBF = operating hours (calendar − downtime) / 2 (got {k.by_code['MTBF'].value}, expected ≈ {expected_op / 2:.2f})")
check(abs(k.by_code["FAILURE_RATE"].value - D(2000) / expected_op) < D("0.01"), "failure rate per 1000 operating hours")
check(k.by_code["DOWNTIME"].value == 6 and k.breakdowns == 2, "downtime hours = 6")
check(all(x.definition and x.source for x in k.kpis), "every KPI carries its definition and source")
check(asset_status(m3) == "IN_SERVICE", "released breakdowns leave the asset in service")

k_all = rel.compute(company_id, rel.Filters(date_from=today - days(59), date_to=today))
check(k_all.by_code["PM_SHARE"].denominator >= 1 and k_all.by_code["PM_SHARE"].value == 100,
      "PM share: the only closed job is preventive → 100%")
check(k_all.by_code["PM_COMPLIANCE"].denominator >= 1, "PM compliance has a denominator from PM jobs due in the period")
k_type = rel.compute(company_id, rel.Filters(date_from=today - days(59), date_to=today, work_type_code="CORRECTIVE"))
check(k_type.by_code["PM_SHARE"].insufficient, "filter by work type: no corrective closed → insufficient data")
fc = eq.save_failure_code(company_id, uid, "CAUSE", "C-BRG", "خرابی بلبرینگ")
wo_c = wos.create(company_id, uid, wos.WorkOrderInput(asset_id=m3, work_type_code="CORRECTIVE", title="بلبرینگ"))
wos.start(company_id, uid, wo_c)
wos.complete(company_id, uid, wo_c, "تعویض", cause_code_id=fc)
wos.verify(company_id, uid, wo_c, "PASS")
wos.close(company_id, uid, wo_c)
k_all = rel.compute(company_id, rel.Filters(date_from=today - days(59), date_to=today))
check(k_all.by_code["PM_SHARE"].value == 50 and k_all.top_causes[0] == ("C-BRG — خرابی بلبرینگ", 1),
      "PM share 1 of 2 closed = 50%; top cause from coded work orders")
check(raises(lambda: wos.complete(company_id, uid, wos.create(company_id, uid, wos.WorkOrderInput(
    asset_id=m3, work_type_code="CORRECTIVE", title="y")), "x"), "در وضعیت"), "complete requires in-progress")
check(raises(lambda: rel.compute(company_id, rel.Filters(date_from=today, date_to=today - days(1))), "پایان دوره"),
      "invalid period refused")

fx.finish()
