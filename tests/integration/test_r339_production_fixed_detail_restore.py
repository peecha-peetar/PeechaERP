"""R339: حساب تولیدی که گروه تفصیلی ساخت کاربر را الزامی کرده و آن گروه هنوز تفصیلی ندارد (از R340 فقط برای حساب‌هایی
مثل کالای در جریان ساخت که سند انبار هم رویشان می‌نشیند): از همان ابتدا با نام حساب، نقش و هر دو راه‌حل گفته می‌شود؛ تفصیلی ثابت همان نقش در «تنظیم حساب‌ها» الزام را
پر می‌کند و «اتمام تولید» انجام می‌شود؛ پشتیبان کامل (ستون محاسبه‌شده، چرخهٔ انبار ↔ محل پیش‌فرض) بی‌کم‌وکاست بازیابی می‌شود."""
import os, subprocess, sys, tempfile
os.environ["PEECHA_DB_NAME"] = "peecha_test_r339"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication([])
warned = []
QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[2]))
QMessageBox.information = staticmethod(lambda *a, **k: None)

from peecha.db.models.accounting import ChartOfAccount, JournalEntryLine, JournalEntryLineDetail
from peecha.services import backup as backup_service, detail_dimensions as dims
from peecha.services.production import common as pc, master as pm, orders as po
from peecha.ui.screens import production as screen_mod

pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg,
                   default_scrap_warehouse_id=wh_scrap, auto_cost_calculation=True)
wc = pm.save_work_center(company_id, pm.WorkCenterFields(code="CUT", name="برش", labor_rate=D(500000),
                                                        machine_rate=D(800000), overhead_rate=D(200000)))
px = item("PX", "محصول X", "FINISHED_GOOD")
rt = pm.create_routing(company_id, px, "مسیر", [pm.RoutingOpFields(10, "برش", wc, run_minutes=D(6), machine_minutes=D(12))])
bom = pm.create_bom_version(company_id, px, pm.BomFields(batch_size_qty=D(1), routing_id=rt))
pm.add_bom_component(company_id, bom, pm.BomLineFields(r1, D(1)))
receive(r1, 1000, 10000)
WIP_ROLE = pc.ROLE_LABELS[pc.WIP]

# دستوری که پیش از الزام صادر شده (مثل PO-1 کاربر)
old = po.create_order(company_id, uid, po.OrderFields(item_id=px, planned_qty=D(10)))
po.release_order(company_id, uid, old)
po.start_order(company_id, uid, old)
po.issue_all_remaining(company_id, uid, old)

# --- حساب کالای در جریان ساخت گروه «هزینه ها»ی کاربر را می‌خواهد که هنوز تفصیلی ندارد --------------------------------------------
costs_type = dims.create_dimension_type(company_id, "هزینه ها").dimension_type_id
dims.set_account_dimension_types(wip_gl.account_id, company_id, [costs_type])
with new_session() as s:
    m_code = s.get(ChartOfAccount, wip_gl.account_id).full_code
rules = po.dimension_rules(company_id)
check(rules.other == [(m_code, "هزینه ها", WIP_ROLE, True)] and not rules.cost_center and not rules.project,
      f"the empty required group is found with its account and role ({rules.other})")
advice = po.dimension_problem(company_id)
check(advice and all(t in advice for t in (f"«{m_code}»", "«هزینه ها»", WIP_ROLE, "هیچ تفصیلی‌ای", "تنظیم حساب‌ها",
                                           "کدینگ حساب‌ها")), f"the advice names the account, group, role and both remedies ({advice})")
check(raises(lambda: po.create_order(company_id, uid, po.OrderFields(item_id=px, planned_qty=D(5))), "تنظیم حساب‌ها"),
      "a new order is refused at creation with the remedies")

scr = screen_mod.OrdersScreen()
scr.refresh()
scr.open_order(old)
asked = []
scr.confirm = lambda text: (asked.append(text), True)[1]
scr._skip_confirm = True
scr.dialog_runner = lambda dlg: True
warned.clear()
ok = scr.action("complete", {"quantity": D(10), "joint_method": None})
check(not ok and not asked and len(warned) == 1 and "تنظیم حساب‌ها" in warned[0]
      and po.get_order(company_id, old).status_code == "IN_PROGRESS", f"one clear warning, no «set it now?» ({asked}, {warned})")

# خطای خود سند حسابداری (پیام PO-1 کاربر): راه‌حل به پیام اضافه می‌شود
real_complete = po.complete_order
po.complete_order = lambda *a, **k: (_ for _ in ()).throw(ValueError(
    f"برای حساب «{m_code}» انتخاب «هزینه ها» الزامی است و فراموش شده است."))
warned.clear()
try:
    scr.action("complete", {"quantity": D(10), "joint_method": None})
finally:
    po.complete_order = real_complete
check(warned and "فراموش شده" in warned[0] and "تنظیم حساب‌ها" in warned[0] and not asked,
      "the posting error gets the remedy appended")

# --- راه اول: تفصیلی در همان گروه + تفصیلی ثابت همان نقش ------------------------------------------------------------------------
fixed = dims.create_detail_account(company_id, costs_type, "H1", "هزینهٔ ماشین‌آلات").detail_account_id
rules = po.dimension_rules(company_id)
check(rules.other and rules.other[0][3] is False and "هیچ تفصیلی‌ای" not in po.dimension_problem(company_id),
      "once the group has a detail the advice no longer says it is empty")
other_type = dims.create_dimension_type(company_id, "سربار کارگاه").dimension_type_id
dims.set_account_dimension_types(overhead_gl.account_id, company_id, [other_type])
engine_service.set_account_mapping(company_id, "PRODUCTION_OVERHEAD_APPLIED", overhead_gl.account_id, fixed)
check(any(g.label == "سربار کارگاه" for g in po.dimension_rules(company_id).extra),
      "a fixed detail from another group does not satisfy the requirement")
engine_service.set_account_mapping(company_id, "PRODUCTION_OVERHEAD_APPLIED", overhead_gl.account_id)
# --- راه دوم: برداشتن الزام از حساب ---------------------------------------------------------------------------------------------
dims.set_account_dimension_types(overhead_gl.account_id, company_id, [])
check(not any(g.label == "سربار کارگاه" for g in po.dimension_rules(company_id).extra), "removing the requirement clears it")

engine_service.set_account_mapping(company_id, "PRODUCTION_WIP", wip_gl.account_id, fixed)
check(not po.dimension_rules(company_id).other and po.dimension_problem(company_id) is None,
      "the role's fixed detail fills the required group")
warned.clear()
ok = scr.action("complete", {"quantity": D(10), "joint_method": None})
check(ok and po.get_order(company_id, old).status_code == "COMPLETED", f"«اتمام تولید» goes through ({warned})")
with new_session() as s:
    posted = s.scalar(select(func.count()).select_from(JournalEntryLine).join(
        JournalEntryLineDetail, JournalEntryLineDetail.line_id == JournalEntryLine.line_id).where(
        JournalEntryLine.account_id == wip_gl.account_id, JournalEntryLineDetail.detail_account_id == fixed))
check(posted > 0, "the work in progress is posted with the fixed detail")
new = po.create_order(company_id, uid, po.OrderFields(item_id=px, planned_qty=D(5)))
check(po.get_order(company_id, new) is not None, "new orders can be created again")

# --- پشتیبان کامل و بازیابی در دیتابیس خالی ---------------------------------------------------------------------------------
bin_id = locations_service.create_bin_location(wh_rm, "A-01", "قفسهٔ یک")
locations_service.set_default_bin_location(company_id, wh_rm, bin_id, uid)
work = tempfile.mkdtemp()
path = os.path.join(work, "backup.json.gz")
manifest = backup_service.export_backup(get_engine(), path)
restore_db = "peecha_test_r339_restore"
env = {**os.environ, "PGPASSWORD": "peecha"}
for sql in (f"DROP DATABASE IF EXISTS {restore_db}", f"CREATE DATABASE {restore_db}"):
    subprocess.run(["psql", "-h", "localhost", "-U", "peecha", "-d", "postgres", "-qc", sql], env=env, check=True, capture_output=True)
from sqlalchemy import create_engine  # noqa: E402

restored = create_engine(get_engine().url.set(database=restore_db))
report = backup_service.import_backup(restored, path)
errors = [(r.full_name, r.error_samples[:1]) for r in report.tables if r.errors]
check(not errors, f"no restore errors ({errors[:3]})")
lost = []
with restored.connect() as conn:
    for t in manifest["tables"]:
        schema, name = t["name"].split(".", 1)
        n = conn.execute(text(f'SELECT count(*) FROM "{schema}"."{name}"')).scalar()
        if n < t["row_count"]:
            lost.append(f'{t["name"]} {n}/{t["row_count"]}')
    default_bin = conn.execute(text("SELECT default_bin_location_id FROM inv.warehouses WHERE warehouse_id = :w"),
                               {"w": wh_rm}).scalar()
    restored_base = conn.execute(text("SELECT sum(debit_amount_base) FROM acc.journal_entry_lines")).scalar()
    restored_order = conn.execute(text("SELECT status_code FROM prd.production_orders WHERE order_id = :o"),
                                  {"o": old}).scalar()
check(not lost, f"every row of every table is restored ({lost[:5]})")
check(default_bin == bin_id, "the warehouse ↔ default location cycle is restored with its link")
with new_session() as s:
    source_base = s.scalar(text("SELECT sum(debit_amount_base) FROM acc.journal_entry_lines"))
check(restored_base == source_base and restored_base, "journal lines with computed columns are restored")
check(restored_order == "COMPLETED", "the production order is restored")
restored.dispose()
subprocess.run(["psql", "-h", "localhost", "-U", "peecha", "-d", "postgres", "-qc", f"DROP DATABASE IF EXISTS {restore_db}"],
               env=env, capture_output=True)

finish()
