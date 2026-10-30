"""R314 مرحلهٔ E+F: کالای در جریان ساخت (دستور تازه برای باقی‌مانده، بدون حوالهٔ دوبارهٔ مواد)، سند باز ارزی، سیاست
«ادامه با مجوز» (دلیل + دسترسی جدا + حساب اختلاف صریح)، قفل نهایی (اسناد دائم)، افتتاحیهٔ اصلاحی (برگشت سند باز،
افزودن سند تازه، تراز تفاوت) و هشدار تاریخ برش."""
import os, sys, tempfile
os.environ["PEECHA_DB_NAME"] = "peecha_test_r314_final"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from opn_fixture import *  # noqa: F401,F403
import opn_fixture as fx
from peecha.db.models.accounting import JournalEntry
from peecha.db.models.commercial import CommercialDocument
from peecha.db.models.inventory import StockDocument
from peecha.db.models.opening import Posting
from peecha.db.models.production import OrderTransaction, ProductionOrder
from peecha.services import commercial_settlements as settlements
from peecha.services import currencies as currencies_service
from peecha.services.opening import finalize as ofin
from peecha.services.opening import posting as opost
from peecha.services.opening import reconcile as orec
from peecha.services.production import common as pc, master as pm, orders as po

check, raises = fx.check, fx.raises
tmp = tempfile.mkdtemp(prefix="r314f_")
bd = oc.fmt_date

pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg,
                   default_scrap_warehouse_id=wh_scrap)
bom = pm.create_bom_version(company_id, fg, pm.BomFields(batch_size_qty=D(1)), user_id=uid)
pm.add_bom_component(company_id, bom, pm.BomLineFields(r1, D(2)), uid)
usd = next(cur.currency_id for cur in currencies_service.list_all_currencies() if cur.iso_code == "USD")
currencies_service.set_company_currency(company_id, usd, True)
oc.save_settings(company_id, uid, clearing_gl.account_id, "APPROVAL", diff_gl.account_id)
entry, approver = user("f_entry", "OPN_ENTRY"), user("f_appr", "OPN_APPROVER")
manager, controller = user("f_mgr", "OPN_MANAGER"), user("f_ctrl", "OPN_CONTROLLER")
MODS = ["RECEIVABLES", "WIP", "GL"]
run = orun.create_run(company_id, manager, "F1", "افتتاحیه", fy_id, balance_date, MODS)
for m in MODS:
    orun.set_people(company_id, manager, run, m, entry, approver)


def load(run_id, module, header, rows, name):
    path = write_csv(os.path.join(tmp, name), header, rows)
    oim.import_file(company_id, entry, run_id, module, path, replace_missing=True)
    return [(r.source_row_no, r.errors) for r in rows_of(run_id, module) if r.status_code == "INVALID"]


def ready(run_id, module):
    orun.submit(company_id, entry, run_id, module)
    orun.approve(company_id, approver, run_id, module)


ARH = ["کد تفصیلی مشتری", "شمارهٔ سند در سیستم قبلی", "تاریخ سند", "مبلغ اصلی", "ارز", "نرخ تبدیل"]
bad = load(run, "RECEIVABLES", ARH, [("C1", "F-100", bd(balance_date), "300000", "", ""),
                                      ("C2", "F-200", bd(balance_date), "200000", "", ""),
                                      ("C1", "FX-1", bd(balance_date), "100", "USD", "50000")], "ar.csv")
check(not bad, f"receivables valid {bad}")
bad = load(run, "WIP", ["شمارهٔ دستور در سیستم قبلی", "کد محصول", "مقدار باقی‌مانده برای تولید", "هزینهٔ انباشتهٔ در جریان ساخت"],
           [("OLD-77", "FG-A", "40", "750000"), ("OLD-78", "RM-3", "5", "1")], "wip.csv")
check(len(bad) == 1 and "فهرست مواد" in str(bad[0][1]), f"WIP for an item without BOM is refused ({bad})")
load(run, "WIP", ["شمارهٔ دستور در سیستم قبلی", "کد محصول", "مقدار باقی‌مانده برای تولید", "هزینهٔ انباشتهٔ در جریان ساخت"],
     [("OLD-77", "FG-A", "40", "750000")], "wip2.csv")
GLH = ["کد حساب معین", "بدهکار", "بستانکار", "کد تفصیلی شخص"]
# مشتری یک در تراز ۵٬۰۰۰ بیشتر از جزئیات (۳۰۰٬۰۰۰ + ۵٬۰۰۰٬۰۰۰ ارزی)
bad = load(run, "GL", GLH, [("131", "5305000", "", "C1"), ("131", "200000", "", "C2"), ("122", "750000", "", ""),
                            ("311", "", "6255000", "")], "gl.csv")
check(not bad, f"trial balance valid {bad}")
for m in MODS:
    ready(run, m)

# ===== کالای در جریان ساخت =====
stock_docs_before = 0
with new_session() as s:
    stock_docs_before = s.scalar(select(func.count()).select_from(StockDocument))
check(opost.post_module(company_id, manager, run, "WIP").module_status == "POSTED", "WIP module posted")
with new_session() as s:
    order = s.scalar(select(ProductionOrder).where(ProductionOrder.idempotency_key.like(f"OPN{run}-WIP%")))
    txns = s.scalars(select(OrderTransaction).where(OrderTransaction.order_id == order.order_id)).all()
    wip = po.wip_balance(s, order.order_id)
    stock_docs_after = s.scalar(select(func.count()).select_from(StockDocument))
check(order.planned_qty == D(40) and order.status_code == "DRAFT" and order.bom_id == bom and "OLD-77" in (order.notes or ""),
      "production order created for the remaining 40 units (draft, effective BOM, legacy number noted)")
check([t.txn_type for t in txns] == ["OPENING"] and wip == D(750000), "accumulated cost carried into the order's WIP (OPENING txn)")
check(stock_docs_after == stock_docs_before, "no material issue created (already-consumed materials are not issued again)")
check(gl_balance(wip_gl.account_id) == D(750000), "WIP account Dr 750,000 against the clearing account")

# ===== دریافتنی ارزی =====
opost.post_module(company_id, manager, run, "RECEIVABLES")
with new_session() as s:
    fx_doc = s.scalar(select(CommercialDocument).where(CommercialDocument.reference_no == "FX-1"))
    fx_line = s.execute(text("SELECT currency_id, exchange_rate, debit_amount_fc, debit_amount_base FROM acc.journal_entry_lines "
                             "WHERE journal_entry_id = :j AND debit_amount_fc = 100"), {"j": fx_doc.journal_entry_id}).one()
check(fx_doc.currency_id == usd and fx_doc.total_amount == D(100) and fx_line[0] == usd and fx_line[3] == D(5000000),
      "foreign-currency open item: 100 USD at 50,000 = 5,000,000 base")

# ===== اختلاف با مجوز =====
rec = orec.report(company_id, run)
check(rec.projected_clearing == D(5000) and [x.counterparty.split(" ")[0] for x in rec.rows if x.difference] == ["C1"],
      "reconciliation shows the 5,000 difference on customer C1")
check(raises(lambda: opost.post_module(company_id, manager, run, "GL"), "دلیل"), "APPROVAL policy still needs a reason")
check(raises(lambda: opost.post_module(company_id, manager, run, "GL", "تفاوت گرد کردن"), "دسترسی"),
      "posting with a difference needs the separate difference permission")
check(module_status(run, "GL") == "APPROVED", "refusals leave GL approved")
res = opost.post_module(company_id, controller, run, "GL", "تفاوت تسعیر سیستم قبلی؛ تأیید مدیر مالی")
check(res.module_status == "POSTED" and orun.get_run(company_id, run).status_code == "POSTED", "GL posted with an approved difference")
check(gl_balance(clearing_gl.account_id) == 0 and gl_balance(diff_gl.account_id) == D(5000),
      "clearing back to zero; the 5,000 sits in the explicit difference account")
events = [e.code for e in orun.get_run(company_id, run).events]
check("DIFFERENCE" in events, "difference approval recorded as an event (reason, user, amount)")

# ===== قفل نهایی =====
check(raises(lambda: ofin.lock_run(company_id, entry, run), "دسترسی"), "data-entry role cannot lock")
lk = ofin.lock_run(company_id, manager, run, "پایان افتتاحیه")
with new_session() as s:
    statuses = set(s.scalars(text("SELECT s.code FROM acc.journal_entries j JOIN acc.journal_entry_statuses s ON s.status_id = j.status_id "
                                  "WHERE j.journal_entry_id = ANY(:ids)"), {"ids": lk.journal_entries}))
r = orun.get_run(company_id, run)
check(statuses == {"PERMANENT"} and len(lk.journal_entries) == 3, f"all opening journal entries are permanent ({statuses}, {lk.journal_entries})")
check(r.status_code == "LOCKED" and all(m.status_code == "LOCKED" for m in r.modules), "run and modules locked")
from peecha.services import journal_entries as je_service  # noqa: E402
check(raises(lambda: je_service.delete_journal_entry(lk.journal_entries[0], company_id, uid)), "permanent opening entry cannot be deleted")
check(raises(lambda: ofin.lock_run(company_id, manager, run), "قبلاً"), "lock is one-time")
check(raises(lambda: oim.save_row(company_id, entry, run, "GL", {"account_code": "111", "debit": "1"}), "پیش از ثبت"),
      "locked run accepts no data")
check(raises(lambda: orun.create_run(company_id, manager, "F2", "دوباره", fy_id, balance_date, ["GL"]), "اصلاحی"),
      "no second original run: only a correction")

# ===== هشدار تاریخ برش =====
check(ofin.cutover_message(company_id, balance_date) and ofin.cutover_message(company_id, go_live) is None,
      "documents dated up to the cutover get a warning; later ones do not")

# ===== افتتاحیهٔ اصلاحی =====
check(raises(lambda: orun.create_run(company_id, manager, "C1", "اصلاحی", fy_id, balance_date, ["RECEIVABLES", "GL"],
                                     corrects_run_id=run), "دسترسی"), "correction needs its own permission")
crun = orun.create_run(company_id, controller, "C1", "اصلاح سند مشتری دو", fy_id, balance_date, ["RECEIVABLES", "GL"],
                       corrects_run_id=run)
for m in ("RECEIVABLES", "GL"):
    orun.set_people(company_id, controller, crun, m, entry, approver)
f200 = next(x for x in ofin.reversible_rows(company_id, crun) if x.key == "C2|F-200")
check(raises(lambda: ofin.reverse_open_item(company_id, controller, crun, f200.row_id, ""), "دلیل"), "reversal needs a reason")
je_rev = ofin.reverse_open_item(company_id, controller, crun, f200.row_id, "مبلغ اشتباه منتقل شده بود")
with new_session() as s:
    doc200 = s.scalar(select(CommercialDocument).where(CommercialDocument.reference_no == "F-200"))
check(doc200.status_code == "CANCELLED" and doc200.document_id not in
      {u.document_id for u in settlements.list_unsettled_invoices(company_id, "SALES_INVOICE")},
      "reversed open item cancelled and gone from open-item lists")
check(raises(lambda: ofin.reverse_open_item(company_id, controller, crun, f200.row_id, "دوباره"), "برگشت خورده"),
      "a row is reversed only once")
bad = load(crun, "RECEIVABLES", ARH, [("C2", "F-201", bd(balance_date), "150000", "", ""),
                                       ("C1", "F-100", bd(balance_date), "300000", "", "")], "ar_fix.csv")
check(len(bad) == 1 and "منتقل شده" in str(bad[0][1]), "an item already transferred cannot be added again")
load(crun, "RECEIVABLES", ARH, [("C2", "F-201", bd(balance_date), "150000", "", "")], "ar_fix2.csv")
load(crun, "GL", GLH, [("131", "", "50000", "C2"), ("311", "50000", "", "")], "gl_fix.csv")
for m in ("RECEIVABLES", "GL"):
    ready(crun, m)
rec = orec.report(company_id, crun)
check(rec.projected_clearing == 0, f"correction reconciles: −200,000 reversal + 150,000 new = −50,000 delta ({rec.problems})")
opost.post_module(company_id, controller, crun, "RECEIVABLES")
opost.post_module(company_id, controller, crun, "GL")
ofin.lock_run(company_id, manager, crun)
check(orun.get_run(company_id, crun).status_code == "LOCKED" and gl_balance(clearing_gl.account_id) == 0,
      "correction posted and locked; clearing still zero")
with new_session() as s:
    c2 = s.execute(text("SELECT coalesce(sum(l.debit_amount_base - l.credit_amount_base), 0) FROM acc.journal_entry_lines l "
                        "JOIN acc.journal_entry_line_details d ON d.line_id = l.line_id WHERE l.account_id = :a AND d.detail_account_id = :p"),
                   {"a": ar_gl.account_id, "p": cust2}).scalar()
    rev_status = s.scalar(text("SELECT status_code FROM opn.staged_rows WHERE row_id = :r"), {"r": f200.row_id})
check(c2 == D(150000) and rev_status == "REVERSED", "customer C2 ends at 150,000; original row marked REVERSED (audit trail kept)")

fx.finish()
