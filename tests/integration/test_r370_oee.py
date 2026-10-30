"""R370: اثربخشی کلی تجهیزات: محاسبهٔ دسترس‌پذیری، عملکرد، کیفیت و اثربخشی، اعتبارسنجی (توقف بیش از برنامه، تولید بیش از نرخ
ایده‌آل، مردود بیش از کل، شیفت تکراری، روز آینده)، پیشنهاد از توقف نگهداری و عملیات و ضایعات دستور تولید، جمع ایستگاه‌ها و
زیان‌ها؛ و فرم."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r370"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mnt_fixture import *  # noqa: F401,F403

from sqlalchemy import update
from peecha.db.models.production import OrderOperation
from peecha.services.production import common as pc, oee, orders as po

pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg)
pm.save_work_center(company_id, pm.WorkCenterFields(code="CUT", name="برش", hours_per_shift=D(8), working_days_per_week=7,
                                                    hourly_capacity_qty=D(60)), wc, user_id=uid)
pack = pm.save_work_center(company_id, pm.WorkCenterFields(code="PAK", name="بسته‌بندی", hours_per_shift=D(8), working_days_per_week=7))
m1 = machine("CUT-1")
d1, d2 = today - days(2), today - days(1)

L, S = oee.LogFields, oee.Stop
check(raises(lambda: oee.save_log(company_id, uid, L(wc, d1, 480, D(60), D(100), D(5), stops=[S("SETUP", 500)])), "بیشتر"),
      "stops cannot exceed planned time")
check(raises(lambda: oee.save_log(company_id, uid, L(wc, d1, 480, D(60), D(500))), "جا نمی‌شود"),
      "output above the ideal rate in the run time is refused")
check(raises(lambda: oee.save_log(company_id, uid, L(wc, d1, 480, D(60), D(10), D(11))), "مردود"), "rejects cannot exceed output")
check(raises(lambda: oee.save_log(company_id, uid, L(wc, today + days(1), 480, D(60), D(10))), "آینده"), "no future logs")
check(raises(lambda: oee.save_log(company_id, uid, L(wc, d1, 480, None, D(10))), "نرخ ایده‌آل"), "the ideal rate is required")
# ۴۸۰ دقیقه، ۶۰ توقف، ۳۷۸ عدد با نرخ ۶۰ در ساعت (۳۷۸ دقیقه)، ۱۸ مردود
log1 = oee.save_log(company_id, uid, L(wc, d1, 480, D(60), D(378), D(18), stops=[S("BREAKDOWN", 40), S("SETUP", 20, "تعویض قالب")]))
check(raises(lambda: oee.save_log(company_id, uid, L(wc, d1, 480, D(60), D(10))), "ثبت شده"), "one log per center, day and shift")
m = oee.list_logs(company_id, d1, d1)[0].metrics
check((m.availability, m.performance, m.quality) == (D("87.5"), D("90.0"), D("95.2")), f"A, P, Q ({m.availability}, {m.performance}, {m.quality})")
check(m.oee == D("75.0") and m.run_minutes == 420 and m.speed_loss_minutes == 42, f"OEE = good ideal time ÷ planned ({m.oee})")
oee.save_log(company_id, uid, L(wc, d2, 480, D(60), D(450), D(0)))
oee.save_log(company_id, uid, L(pack, d2, 480, D(30), D(120), D(6), stops=[S("MATERIAL", 120)]))
total, centers = oee.summary(company_id, d1, d2)
check([c.work_center_id for c in centers] == [pack, wc] and centers[1].logs == 2, "centers sorted by lowest OEE")
cut = centers[1].metrics
check(cut.availability == D("93.8") and cut.oee == D("84.4"), f"two shifts combine by time, not by average ({cut.availability}, {cut.oee})")
check(total.planned_minutes == 1440 and total.downtime_minutes == 180, "company totals")
loss = dict(oee.losses(company_id, d1, d2))
check(loss["کمبود مواد"] == D(120) and loss["خرابی"] == D(40) and loss["افت سرعت"] == D(192), f"time losses ({loss})")
check([d for d, _m in oee.daily_trend(company_id, wc, d1, d2)] == [d1, d2], "daily trend")
oee.save_log(company_id, uid, L(wc, d1, 480, D(60), D(378), D(18), stops=[S("BREAKDOWN", 40)]), log1)
check(oee.list_logs(company_id, d1, d1)[0].metrics.downtime_minutes == 40, "editing a log replaces its stops")

# پیشنهاد از داده‌های موجود: توقف ماشین در نگهداری، عملیات تمام‌شده و ضایعات
d3 = today - days(3)
with new_session() as s:
    ev, _new = av.start(s, company_id, uid, m1, datetime.datetime.combine(d3, datetime.time(10)).astimezone())
    s.commit()
    ev_id = ev.downtime_id
av.release_downtime(company_id, uid, ev_id, datetime.datetime.combine(d3, datetime.time(11, 30)).astimezone(), "رفع گیر قطعه")
rt = pm.create_routing(company_id, fg, "مسیر برش", [pm.RoutingOpFields(10, "برش", wc, run_minutes=D(1))])
bom = pm.create_bom_version(company_id, fg, pm.BomFields(batch_size_qty=D(1), routing_id=rt))
pm.add_bom_component(company_id, bom, pm.BomLineFields(r1, D(1)))
receive(r1, 500, 1000)
order = po.create_order(company_id, uid, po.OrderFields(item_id=fg, planned_qty=D(100)))
po.release_order(company_id, uid, order)
with new_session() as s:
    op = s.scalar(select(OrderOperation.order_operation_id).where(OrderOperation.order_id == order))
po.set_operation_status(company_id, uid, op, "DONE", D(95))
with new_session() as s:
    s.execute(update(OrderOperation).where(OrderOperation.order_operation_id == op).values(
        finished_at=datetime.datetime.combine(d3, datetime.time(15))))
    s.commit()
po.report_scrap(company_id, uid, order, D(5), "ترک", date=d3)
f = oee.suggest(company_id, wc, d3)
check(f.planned_minutes == 480 and f.ideal_rate_per_hour == D(60) and [(x.reason_code, x.minutes) for x in f.stops] == [("BREAKDOWN", 90)],
      f"suggested time and breakdown ({f.planned_minutes}, {[(x.reason_code, x.minutes) for x in f.stops]})")
check(f.total_qty == D(100) and f.reject_qty == D(5), f"suggested output and rejects ({f.total_qty}, {f.reject_qty})")
check(oee.suggest(company_id, pack, d3).ideal_rate_per_hour is None, "no ideal rate without the center's hourly capacity")

# فرم
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.production_oee import ProductionOeeScreen

screen = ProductionOeeScreen()
screen.refresh()
check(screen.log_table.rowCount() == 3, "logs listed")
screen.wc_combo.setCurrentIndex(screen.wc_combo.findData(wc))
screen.day_field.setDate(d3)
check(screen.suggest() and screen.planned_field.value() == 480 and screen.stop_table.rowCount() == 1, "suggest from the form")
check(screen.save_log() and screen.log_table.rowCount() == 4, f"save from the form ({screen.status_label.text()})")
screen.from_field.setDate(d3)
screen.refresh_dashboard()
check(screen.center_table.rowCount() == 2 and screen.loss_table.rowCount() >= 3, "dashboard tables")
check(all(len(b.text()) <= 2 for b in screen.findChildren(QPushButton) if b.text()), "icon buttons only")

finish()
