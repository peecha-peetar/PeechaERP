"""R314 مرحلهٔ C+D: ثبت قطعی با سرویس‌های رسمی — موجودی (بچ/سریال/انقضا)، اسناد باز دریافتنی/پرداختنی (با تسویهٔ پیش از برش
و تسویهٔ بعدی)، چک‌های باز، دارایی ثابت (استهلاک بعدی فقط برای عمر باقی‌مانده)، سند تراز آخر از همه با حساب واسط صفر،
سیاست BLOCK اختلاف، ازسرگیری پس از خطا بدون تکرار، بازیابی پس از قطع میان ثبت چک، و ثبت هم‌زمان."""
import os, sys, tempfile, threading
os.environ["PEECHA_DB_NAME"] = "peecha_test_r314_post"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from opn_fixture import *  # noqa: F401,F403
import opn_fixture as fx
from peecha.db.models.commercial import CommercialDocument, InvoiceSettlement
from peecha.db.models.fixed_assets import Asset
from peecha.db.models.inventory import StockDocument
from peecha.db.models.opening import Posting
from peecha.db.models.treasury import IssuedCheck, ReceivedCheck
from peecha.services import commercial_settlements as settlements
from peecha.services import treasury as treasury_service
from peecha.services.fixed_assets import common as fac
from peecha.services.fixed_assets import depreciation as fdep
from peecha.services.opening import posting as opost
from peecha.services.opening import reconcile as orec

check, raises = fx.check, fx.raises
tmp = tempfile.mkdtemp(prefix="r314p_")
bd = oc.fmt_date

# ===== پیکربندی =====
chq_recv_gl = A("132", "اسناد دریافتنی", "DEBIT", "ASSET", "PERMANENT", True, k_ar.account_id)
k_chq_pay = A("22", "اسناد پرداختنی", "CREDIT", "LIABILITY", "PERMANENT", False, g4.account_id)
chq_pay_gl = A("221", "اسناد پرداختنی تجاری", "CREDIT", "LIABILITY", "PERMANENT", True, k_chq_pay.account_id)
treasury_service.set_account_mapping(company_id, "RECEIPT_CHECK", chq_recv_gl.account_id)
treasury_service.set_account_mapping(company_id, "PAYMENT_CHECK", chq_pay_gl.account_id)
bank_type = dims.get_specialized_dimension_type_id(company_id, dims.BANK_ACCOUNT_CODE)
bank1 = dims.create_detail_account(company_id, bank_type, "B01", "بانک ملت جاری").detail_account_id
oc.save_settings(company_id, uid, clearing_gl.account_id, "BLOCK", None)
cat_mch = fac.save_category(company_id, fac.CategoryFields("MCH", "ماشین‌آلات", default_life_months=120, accounts={
    "asset_account_id": fa_cost_gl.account_id, "accumulated_depreciation_account_id": fa_dep_gl.account_id,
    "depreciation_expense_account_id": dep_exp_gl.account_id}))
bt = item("BT-1", "کالای بچ‌دار", "GOOD", track_batch=True, track_expiry=True)
sr = item("SR-1", "کالای سریالی", "GOOD", track_serial=True)
entry, approver = user("p_entry", "OPN_ENTRY"), user("p_appr", "OPN_APPROVER")
manager, controller = user("p_mgr", "OPN_MANAGER"), user("p_ctrl", "OPN_CONTROLLER")

MODS = ["INVENTORY", "RECEIVABLES", "PAYABLES", "CHEQUES", "FIXED_ASSETS", "GL"]
run = orun.create_run(company_id, manager, "GO", "افتتاحیهٔ راه‌اندازی", fy_id, balance_date, MODS)
for m in MODS:
    orun.set_people(company_id, manager, run, m, entry, approver)


def load(module, header, rows, name=None):
    path = write_csv(os.path.join(tmp, name or f"{module}.csv"), header, rows)
    res = oim.import_file(company_id, entry, run, module, path, replace_missing=True)
    bad = [(r.source_row_no, r.errors) for r in rows_of(run, module) if r.status_code == "INVALID"]
    return res, bad


def ready(module):
    orun.submit(company_id, entry, run, module)
    orun.approve(company_id, approver, run, module)


exp = bd(go_live + datetime.timedelta(days=400))
_, bad = load("INVENTORY", ["کد انبار", "کد کالا", "مقدار", "بهای واحد", "شمارهٔ بچ", "تاریخ انقضا", "شمارهٔ سریال"], [
    ("RM", "RM-1", "10", "1000", "", "", ""), ("LINE", "RM-2", "2", "500", "", "", ""),
    ("RM", "BT-1", "4", "1000", "B-7", exp, ""), ("RM", "SR-1", "1", "5000", "", "", "S-001"),
    ("RM", "SR-1", "1", "5000", "", "", "S-002")])
check(not bad, f"inventory rows valid {bad}")
_, bad = load("RECEIVABLES", ["کد تفصیلی مشتری", "شمارهٔ سند در سیستم قبلی", "تاریخ سند", "سررسید", "مبلغ اصلی", "تسویه‌شده تا برش"], [
    ("C1", "F-100", bd(balance_date - datetime.timedelta(days=40)), bd(go_live + datetime.timedelta(days=20)), "800000", "300000"),
    ("C2", "F-200", bd(balance_date - datetime.timedelta(days=90)), bd(balance_date - datetime.timedelta(days=60)), "200000", "")])
check(not bad, f"receivable rows valid {bad}")
_, bad = load("PAYABLES", ["کد تفصیلی تامین‌کننده", "شمارهٔ سند در سیستم قبلی", "تاریخ سند", "مبلغ اصلی"], [
    ("S1", "P-1", bd(balance_date - datetime.timedelta(days=10)), "400000")])
check(not bad, f"payable rows valid {bad}")
_, bad = load("CHEQUES", ["نوع چک", "شمارهٔ چک", "سررسید", "مبلغ", "کد تفصیلی طرف‌حساب", "کد صندوق/حساب بانکی", "بانک"], [
    ("دریافتی", "771001", bd(go_live + datetime.timedelta(days=30)), "250000", "C1", "", "تجارت"),
    ("پرداختی", "880055", bd(go_live + datetime.timedelta(days=15)), "100000", "S1", "B01", "ملت")])
check(not bad, f"cheque rows valid {bad}")
start = fac.add_months(balance_date, -23)
_, bad = load("FIXED_ASSETS", ["کد دارایی", "نام دارایی", "کد طبقه", "بهای تمام‌شده", "استهلاک انباشته تا برش",
                               "تاریخ شروع استهلاک/بهره‌برداری"], [("M-1", "دستگاه برش", "MCH", "1200000", "240000", bd(start))])
check(not bad, f"asset rows valid {bad}")
GLH = ["کد حساب معین", "بدهکار", "بستانکار", "کد تفصیلی شخص", "شرح"]
gl_rows = [("121", "26000", "", "", "موجودی کالا"), ("131", "510000", "", "C1", "مشتری یک"), ("131", "200000", "", "C2", "مشتری دو"),
           ("211", "", "400000", "S1", "تامین‌کننده"), ("132", "250000", "", "", "اسناد دریافتنی"),
           ("221", "", "100000", "", "اسناد پرداختنی"), ("141", "1200000", "", "", "دارایی"), ("142", "", "240000", "", "استهلاک"),
           ("111", "66000", "", "", "صندوق"), ("311", "", "1512000", "", "سرمایه")]
_, bad = load("GL", GLH, gl_rows, "gl_wrong.csv")
check(not bad, f"trial balance rows valid {bad}")
check(any(w for r in rows_of(run, "GL") for w in (r.warnings or []) if "حساب کنترل" in w["msg"]),
      "control accounts in the trial balance are flagged (they go to the clearing account)")

rec = orec.report(company_id, run)
diffs = {(x.module_code, x.counterparty.split(" ")[0] if x.counterparty else ""): x.difference for x in rec.rows if x.difference}
check(rec.tb_balanced and diffs == {("INVENTORY", ""): D(1000), ("RECEIVABLES", "C1"): D(10000)},
      f"pre-posting reconciliation finds inventory +1,000 and receivable C1 +10,000 ({diffs})")
check(rec.projected_clearing == D(11000) and all(x.formula and x.source for x in rec.rows),
      "projected clearing residual 11,000; every row carries source and formula")

for m in MODS:
    ready(m)

# ===== ترتیب و دسترسی =====
check(raises(lambda: opost.post_module(company_id, manager, run, "GL"), "آخر از همه"), "trial balance is posted last")
check(raises(lambda: opost.post_module(company_id, entry, run, "INVENTORY"), "دسترسی"), "data-entry role cannot post")

# ===== موجودی، با خطای گام و ازسرگیری =====
from peecha.services import inventory_documents as inv_docs  # noqa: E402
real_create = inv_docs.create_and_post_in_session
calls = {"n": 0}


def flaky(session, company_id_, user_id, doc_type, date, header, lines, **kw):
    calls["n"] += 1
    if header.destination_warehouse_id == wh_line and calls["n"] <= 2:
        raise ValueError("قطع شبیه‌سازی‌شده")
    return real_create(session, company_id_, user_id, doc_type, date, header, lines, **kw)


inv_docs.create_and_post_in_session = flaky
r1_ = opost.post_module(company_id, manager, run, "INVENTORY")
check(r1_.module_status == "POSTING" and r1_.done == 1 and len(r1_.failed) == 1, f"one warehouse posted, the other failed ({r1_})")
failed_rows = [r for r in rows_of(run, "INVENTORY") if r.status_code == "FAILED"]
check(len(failed_rows) == 1 and "قطع" in str(failed_rows[0].errors), "failed step marks its rows FAILED with the message")
r2_ = opost.post_module(company_id, manager, run, "INVENTORY")
inv_docs.create_and_post_in_session = real_create
with new_session() as s:
    docs = s.scalar(select(func.count()).select_from(StockDocument).where(StockDocument.reference_no == "OPN-GO"))
    attempts = {p.step_key: (p.status_code, p.attempts) for p in s.scalars(select(Posting).where(Posting.module_code == "INVENTORY"))}
check(r2_.module_status == "POSTED" and r2_.done == 1 and not r2_.failed and docs == 2,
      f"resume posts only the failed warehouse: 2 stock documents, no duplicate ({r2_}, {docs})")
check(sorted(v for v in attempts.values()) == [("DONE", 1), ("DONE", 2)], f"posting log keeps attempts per step {attempts}")
check(on_hand(r1, wh_rm) == D(10) and on_hand(bt, wh_rm) == D(4) and on_hand(sr, wh_rm) == D(2) and on_hand(r2, wh_line) == D(2),
      "stock on hand by warehouse")
with new_session() as s:
    lots = s.execute(text("SELECT batch_no, expiry_date FROM inv.lot_balances lb JOIN inv.lots l ON l.lot_id = lb.lot_id "
                          "WHERE lb.item_id = :i"), {"i": bt}).all() if s.scalar(text(
        "SELECT to_regclass('inv.lot_balances') IS NOT NULL AND to_regclass('inv.lots') IS NOT NULL")) else []
    serials = set(s.scalars(text("SELECT serial_no FROM inv.serial_numbers WHERE item_id = :i"), {"i": sr}))
check(serials == {"S-001", "S-002"}, f"serial numbers registered ({serials})")
check(gl_balance(inv_gl.account_id) == D(25000) and gl_balance(clearing_gl.account_id) == D(-25000),
      "inventory account Dr 25,000 against the clearing account (no P&L touched)")
check(gl_balance(adj_gl.account_id) == 0, "inventory adjustment-gain account untouched")
check(raises(lambda: opost.post_module(company_id, manager, run, "INVENTORY"), "قبلاً"), "a posted module cannot be posted again")

# ===== دریافتنی / پرداختنی =====
opost.post_module(company_id, manager, run, "RECEIVABLES")
opost.post_module(company_id, manager, run, "PAYABLES")
with new_session() as s:
    odocs = {d.reference_no: d for d in s.scalars(select(CommercialDocument).where(
        CommercialDocument.document_type_code.in_(("OPENING_RECEIVABLE", "OPENING_PAYABLE"))))}
    pre = s.scalars(select(InvoiceSettlement).where(InvoiceSettlement.invoice_document_id == odocs["F-100"].document_id)).all()
    lines_count = s.scalar(text("SELECT count(*) FROM comm.commercial_document_lines WHERE document_id = :d"),
                           {"d": odocs["F-100"].document_id})
check(set(odocs) == {"F-100", "F-200", "P-1"} and all(d.status_code == "POSTED" and d.journal_entry_id for d in odocs.values()),
      "opening open items created as posted documents linked to the opening journal entry")
check(odocs["F-100"].total_amount == D(800000) and len(pre) == 1 and pre[0].amount == D(300000) and pre[0].journal_entry_id is None
      and lines_count == 0, "original 800,000 with a 300,000 pre-cutover settlement (no voucher), no item lines")
open_ar = {u.document_id: u.remaining_amount for u in settlements.list_unsettled_invoices(company_id, "SALES_INVOICE")}
check(open_ar == {odocs["F-100"].document_id: D(500000), odocs["F-200"].document_id: D(200000)},
      "unsettled receivables list includes opening items with their open balance")
check({u.document_id for u in settlements.list_unsettled_invoices_bulk(company_id, counterparty_ids=[cust2],
                                                                       due_on_or_before=go_live)} == {odocs["F-200"].document_id},
      "overdue opening receivable visible to aging/collection queries")
check([u.remaining_amount for u in settlements.list_unsettled_invoices(company_id, "PURCHASE_INVOICE")] == [D(400000)],
      "unsettled payables include the opening payable")
check(gl_balance(ar_gl.account_id) == D(700000) and gl_balance(ap_gl.account_id) == D(-400000), "AR/AP control accounts posted")
check(treasury_service.get_counterparty_balance(company_id, cust1)[0] == D(500000),
      "customer balance in the ledger = open items (no invoice re-created)")

# ===== چک‌ها: قطع میان ثبت و علامت‌گذاری + اجرای هم‌زمان =====
real_mark = opost._mark_done
broken = {"once": True}


def crash_after_voucher(session, run_id, module_code, step_key, *a, **kw):
    if module_code == "CHEQUES" and broken["once"]:
        broken["once"] = False
        raise RuntimeError("قطع برق پس از ساخت سند")
    return real_mark(session, run_id, module_code, step_key, *a, **kw)


opost._mark_done = crash_after_voucher
first = opost.post_module(company_id, manager, run, "CHEQUES")
opost._mark_done = real_mark
check(first.module_status == "POSTING" and len(first.failed) == 1, "crash after the treasury voucher leaves the step unfinished")
results, errors = [], []


def go():
    try:
        results.append(opost.post_module(company_id, manager, run, "CHEQUES"))
    except ValueError as exc:
        errors.append(str(exc))


ts = [threading.Thread(target=go) for _ in range(2)]
[t.start() for t in ts]
[t.join() for t in ts]
with new_session() as s:
    recv = s.scalars(select(ReceivedCheck).where(ReceivedCheck.check_no == "771001")).all()
    iss = s.scalars(select(IssuedCheck).where(IssuedCheck.check_no == "880055")).all()
    status_of = lambda tbl, sid: s.scalar(text(f"SELECT code FROM treasury.check_statuses WHERE status_id = :i"), {"i": sid})  # noqa: E731
    recv_status = status_of("r", recv[0].status_id) if recv else None
check(len(recv) == 1 and len(iss) == 1, f"recovery + concurrent run: exactly one received and one issued cheque ({len(recv)}, {len(iss)})")
check(len(results) >= 1 and results[0].module_status == "POSTED" and (len(results) == 2 or any("در جریان" in e or "قبلاً" in e for e in errors)),
      f"second concurrent call is refused or finds nothing left ({errors})")
check(recv[0].counterparty_detail_account_id == cust1 and recv[0].amount == D(250000) and recv_status == "IN_HAND"
      and iss[0].bank_account_detail_id == bank1, "received cheque in hand for C1; issued cheque on bank B01")
check(gl_balance(chq_recv_gl.account_id) == D(250000) and gl_balance(chq_pay_gl.account_id) == D(-100000),
      "cheque accounts posted once")

# ===== دارایی ثابت =====
fa_res = opost.post_module(company_id, manager, run, "FIXED_ASSETS")
check(fa_res.module_status == "POSTED", f"fixed assets posted {fa_res.failed}")
with new_session() as s:
    asset = s.scalar(select(Asset).where(Asset.asset_code == "M-1"))
check(asset.gross_cost == D(1200000) and asset.accumulated_depreciation == D(240000) and asset.source_code == "OPENING"
      and asset.depreciated_months_offset == 24 and asset.status_code == "IN_SERVICE", "asset with cost, accumulated depreciation, 24 months done")
check(gl_balance(fa_cost_gl.account_id) == D(1200000) and gl_balance(fa_dep_gl.account_id) == D(-240000), "asset control accounts posted")

# ===== سند تراز: BLOCK، اصلاح و ثبت =====
check(raises(lambda: opost.post_module(company_id, manager, run, "GL"), "تطبیق ندارند"), "BLOCK policy: GL refused while subledgers differ")
check(module_status(run, "GL") == "APPROVED", "refused GL stays approved (nothing posted)")
orun.reject(company_id, approver, run, "GL", "موجودی و مشتری یک با جزئیات نمی‌خواند")
gl_rows[0] = ("121", "25000", "", "", "موجودی کالا")
gl_rows[1] = ("131", "500000", "", "C1", "مشتری یک")
gl_rows[-1] = ("311", "", "1501000", "", "سرمایه")
load("GL", GLH, gl_rows, "gl_fixed.csv")
ready("GL")
rec = orec.report(company_id, run)
check(rec.projected_clearing == 0 and not [x for x in rec.rows if x.difference], "after correction every control account reconciles")
res = opost.post_module(company_id, manager, run, "GL")
r = orun.get_run(company_id, run)
check(res.module_status == "POSTED" and r.status_code == "POSTED", "GL posted; run POSTED")
check(gl_balance(clearing_gl.account_id) == 0, "clearing account ends at zero")
for acc, want in ((inv_gl, 25000), (ar_gl, 700000), (ap_gl, -400000), (chq_recv_gl, 250000), (chq_pay_gl, -100000),
                  (fa_cost_gl, 1200000), (fa_dep_gl, -240000), (cash_gl, 66000), (capital_gl, -1501000)):
    if gl_balance(acc.account_id) != D(want):
        check(False, f"ledger balance of {acc.segment_code}: {gl_balance(acc.account_id)} != {want}")
check(True, "every account in the ledger equals the trial balance (control accounts counted once, via subledgers)")
rec = orec.report(company_id, run)
check(rec.ok and rec.gl_posted and rec.clearing_posted == 0, f"post-posting reconciliation clean ({rec.problems})")
with new_session() as s:
    gl_je = s.scalar(select(Posting.journal_entry_id).where(Posting.step_key == f"GL:{run}"))
    je_type = s.scalar(text("SELECT t.code FROM acc.journal_entries j JOIN acc.journal_entry_types t ON t.entry_type_id = j.entry_type_id "
                            "WHERE j.journal_entry_id = :j"), {"j": gl_je})
check(je_type == "OPENING", "trial balance entry uses the OPENING journal type")

# ===== پس از افتتاحیه: تسویهٔ سند باز و استهلاک ماه بعد =====
settlements.allocate_settlement(company_id, odocs["F-100"].document_id, None, go_live, D(100000), uid, description="وصول")
check(settlements.get_invoice_settlement_status(odocs["F-100"].document_id, company_id).remaining_amount == D(400000),
      "later collection settles the transferred open item")
period = fac.period_of(go_live)[0]
dep_run = fdep.calculate_run(company_id, uid, period)
with new_session() as s:
    amount = s.scalar(text("SELECT amount FROM fa.depreciation_lines WHERE run_id = :r"), {"r": dep_run})
check(amount == D(10000), f"next depreciation = (1,200,000 − 240,000) / (120 − 24) = 10,000 per month ({amount})")

fx.finish()
