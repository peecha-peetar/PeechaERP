"""R315: فرم سند افتتاحیه روی کدینگ حساب‌ها — مانده هر حساب، مانده تفصیلی‌ها، کالاها (مقدار و مبلغ)، اشخاص با سند باز
خودکار و پیش‌دریافت، ردیف خودکار حساب‌های کنترل، بستن با حساب افتتاحیه (بدون ثبت نیمه‌کاره)، گردش ارسال/تأیید/ثبت/قفل
از همین فرم و ثبت با همان سرویس‌های رسمی."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r315_sheet"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from opn_fixture import *  # noqa: F401,F403
import opn_fixture as fx
from peecha.db.models.commercial import CommercialDocument
from peecha.db.models.accounting import JournalEntryLine, JournalEntryLineDetail
from peecha.services import commercial_settlements as settlements
from peecha.services.opening import finalize as ofin
from peecha.services.opening import reconcile as orec
from peecha.services.opening import sheet as osh

check, raises = fx.check, fx.raises
bd = oc.fmt_date

oc.save_settings(company_id, uid, clearing_gl.account_id, "BLOCK", None)
other_ar = A("133", "سایر دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", True, k_ar.account_id)
petty = A("134", "تنخواه پروژه‌ها", "DEBIT", "ASSET", "PERMANENT", True, k_ar.account_id)
dims.set_account_dimension_types(other_ar.account_id, company_id, [person_type])
dims.set_account_dimension_types(petty.account_id, company_id, [cc_type])
bt = item("BT-1", "کالای بچ‌دار", "GOOD", track_batch=True, track_expiry=True)
entry, approver = user("s_entry", "OPN_ENTRY"), user("s_appr", "OPN_APPROVER")
manager = user("s_mgr", "OPN_MANAGER")

# ===== ۱) فرایند از خود فرم =====
run = osh.create_run(company_id, manager, fy_id, balance_date, go_live)
info = orun.get_run(company_id, run)
check(info.code.startswith("OPN-") and {m.module_code for m in info.modules} == set(osh.SHEET_MODULES),
      f"run created from the form with ledger, stock and party modules ({info.code})")
check(osh.default_run(company_id) == run, "form opens the run in progress")
sh = osh.sheet(company_id, run)
kinds = {r.code.split("-")[-1]: r.kind for r in sh.rows}
check(kinds["111"] == "PLAIN" and kinds["121"] == "INVENTORY" and kinds["131"] == "RECEIVABLES" and kinds["211"] == "PAYABLES"
      and kinds["133"] == "DETAIL" and kinds["134"] == "DETAIL" and kinds["391"] == "CLEARING" and kinds["11"] == "GROUP",
      f"every account of the chart is listed with its entry kind ({kinds})")
check(sh.closed and sh.debit == 0 and sh.clearing and "391" in sh.clearing, "empty sheet is closed; opening account shown")

# ===== ۲) حساب ساده و تفصیلی =====
check(osh.save_account_detail(company_id, entry, run, cash_gl.account_id, [{"debit": D(66000)}]).invalid == 0, "plain balance saved")
det = osh.account_detail(company_id, run, other_ar.account_id)
codes = [code for code, _n in det.candidates]
check(det.primary.field == "person_code" and {"C1", "C2", "S1"} <= set(codes), f"person detail list for the account ({codes})")
res = osh.save_account_detail(company_id, entry, run, other_ar.account_id, [
    {"details": {"person_code": "C1"}, "debit": D(5000)}, {"details": {"person_code": "S1"}, "credit": D(2000)},
    {"details": {"person_code": "C2"}}])
check(res.invalid == 0 and len(res.saved) == 2, "detail balances per person (empty person skipped)")
det = osh.account_detail(company_id, run, petty.account_id)
check(det.primary.field == "cost_center_code" and det.candidates == [("CC1", "تولید")], "cost-center detail list")
osh.save_account_detail(company_id, entry, run, petty.account_id, [{"details": {"cost_center_code": "CC1"}, "debit": D(3000)}])
raises(lambda: osh.save_account_detail(company_id, entry, run, inv_gl.account_id, [{"debit": D(1)}]), "زیرسیستم")
raises(lambda: osh.save_account_detail(company_id, entry, run, clearing_gl.account_id, [{"debit": D(1)}]), "حساب افتتاحیه")
raises(lambda: osh.save_account_detail(company_id, entry, run, other_ar.account_id, [
    {"details": {"person_code": "C2"}, "debit": D(1)}, {"details": {"person_code": "C2"}, "debit": D(2)}]), "دو ردیف")
lines = osh.account_detail(company_id, run, other_ar.account_id).lines
s1 = next(x for x in lines if x.details.get("person_code") == "S1")
osh.save_account_detail(company_id, entry, run, other_ar.account_id, [{"row_id": s1.row_id, "details": {"person_code": "S1"}}])
check(len(osh.account_detail(company_id, run, other_ar.account_id).lines) == 1, "clearing a line's amount removes it")

# ===== ۳) کالاها: مقدار و مبلغ =====
exp = bd(go_live + datetime.timedelta(days=400))
inv = osh.inventory_detail(company_id, run, "RM")
listed = {x.item_code for x in inv.lines}
check({"RM-1", "RM-2", "BT-1", "FG-A"} <= listed and all(x.row_id is None for x in inv.lines), "all stock items listed for the warehouse")
res = osh.save_inventory(company_id, entry, run, "RM", [
    {"item_code": "RM-1", "quantity": D(3), "amount": D(1000)}, {"item_code": "BT-1", "quantity": D(4), "amount": D(4000),
                                                                  "batch_no": "B-7", "expiry_date": exp},
    {"item_code": "RM-2", "quantity": D(2), "amount": None}, {"item_code": "FG-A", "quantity": None, "amount": None}])
check(len(res.saved) == 3 and res.invalid == 1, "items saved; missing amount is an error, not a zero cost")
inv = osh.inventory_detail(company_id, run, "RM")
rm1 = next(x for x in inv.lines if x.item_code == "RM-1")
check(rm1.amount == D(1000) and rm1.quantity == D(3), f"amount kept exactly from quantity × unit cost ({rm1.amount})")
rm2 = next(x for x in inv.lines if x.item_code == "RM-2" and x.row_id)
check("بها" in rm2.problem, f"error shown on the item line ({rm2.problem})")
osh.save_inventory(company_id, entry, run, "RM", [{"row_id": rm2.row_id, "item_code": "RM-2", "quantity": D(2), "amount": D(1000)}])
res = osh.save_inventory(company_id, entry, run, "RM", [{"item_code": "BT-1", "quantity": D(1), "amount": D(1000)}])
check(res.invalid == 1, "batch item without batch number is an error")
bad = next(x for x in osh.inventory_detail(company_id, run, "RM").lines if x.item_code == "BT-1" and x.problem)
osh.save_inventory(company_id, entry, run, "RM", [{"row_id": bad.row_id, "item_code": "BT-1"}])

# ===== ۴) اشخاص: سند باز خودکار و پیش‌دریافت =====
par = osh.party_detail(company_id, run, "RECEIVABLES")
check({"C1", "C2"} <= {x.person_code for x in par.lines} and "S1" not in {x.person_code for x in par.lines},
      "customer account lists customers only")
due = go_live + datetime.timedelta(days=30)
res = osh.save_parties(company_id, entry, run, "RECEIVABLES", [
    {"person_code": "C1", "debit": D(300000), "due_date": bd(due)}, {"person_code": "C2", "credit": D(20000)}])
check(res.invalid == 0, f"customer balances saved {[x.errors for x in res.saved]}")
par = {x.person_code: x for x in osh.party_detail(company_id, run, "RECEIVABLES").lines}
check(par["C1"].debit == 300000 and par["C2"].credit == 20000 and par["C1"].due_date, "debit and advance balances read back")
osh.save_parties(company_id, entry, run, "PAYABLES", [{"person_code": "S1", "credit": D(400000)}])

# ===== ۵) ردیف خودکار حساب‌های کنترل و حساب افتتاحیه =====
changed = osh.sync_control_rows(company_id, entry, run)
check(changed == 4, f"control-account rows built from the sub-ledgers ({changed})")
check(osh.sync_control_rows(company_id, entry, run) == 0, "second sync changes nothing")
sh = osh.sheet(company_id, run)
by = {r.code.split("-")[-1]: r for r in sh.rows}
check(by["121"].debit == 6000 and by["131"].debit == 300000 and by["131"].credit == 20000 and by["211"].credit == 400000,
      "control account balances = sub-ledger totals")
check(by["12"].debit == 6000 and by["1"].debit == by["11"].debit + by["12"].debit + by["13"].debit, "group totals roll up")
check(sh.debit == D(380000) and sh.credit == D(420000) and sh.difference == D(-40000) and not sh.closed
      and by["391"].debit == D(40000), f"opening account shows the closing amount; sheet not closed ({sh.debit}, {sh.credit})")

# ===== ۶) گردش: ارسال، تأیید با تفکیک وظایف، ثبت فقط با سند بسته =====
res = osh.submit_all(company_id, entry, run)
check(len(res.done) == 4, f"all entered parts sent for review ({res.done})")
raises(lambda: osh.approve_all(company_id, entry, run), "تفکیک وظایف")
check(len(osh.approve_all(company_id, approver, run).done) == 4, "approver approves all parts")
raises(lambda: osh.post_all(company_id, manager, run), "حساب افتتاحیه")
check(all(m.status_code == "APPROVED" for m in orun.get_run(company_id, run).modules), "nothing posted while the sheet is open")
osh.save_account_detail(company_id, entry, run, cash_gl.account_id,
                        [{"row_id": osh.account_detail(company_id, run, cash_gl.account_id).lines[0].row_id, "debit": D(106000)}])
check(fx.module_status(run, "GL") == "ENTERING", "changing a balance sends the ledger part back to entry")
osh.submit_all(company_id, entry, run)
osh.approve_all(company_id, approver, run)
sh = osh.sheet(company_id, run)
check(sh.closed and sh.debit == sh.credit == D(420000), "sheet closes with the opening account at zero")
res = osh.post_all(company_id, manager, run)
check(res.run_status == "POSTED" and not res.failed and res.posted[-1] == oc.MODULE_LABELS["GL"],
      f"posted in the official order, ledger last ({res.posted})")

# ===== ۷) نتیجه در دفاتر =====
check(gl_balance(clearing_gl.account_id) == 0 and gl_balance(inv_gl.account_id) == D(6000) and gl_balance(ap_gl.account_id) == D(-400000)
      and gl_balance(cash_gl.account_id) == D(106000) and gl_balance(petty.account_id) == D(3000), "ledger matches the sheet")
check(on_hand(r1, wh_rm) == D(3) and on_hand(r2, wh_rm) == D(2) and on_hand(bt, wh_rm) == D(4), "stock received by item")


def person_balance(account_id, person):
    with new_session() as s:
        rows = s.execute(select(JournalEntryLine.debit_amount_base, JournalEntryLine.credit_amount_base).join(
            JournalEntryLineDetail, JournalEntryLineDetail.line_id == JournalEntryLine.line_id).where(
            JournalEntryLine.account_id == account_id, JournalEntryLineDetail.detail_account_id == person)).all()
    return sum((D(d) - D(c_) for d, c_ in rows), D(0))


check(person_balance(ar_gl.account_id, cust1) == D(300000) and person_balance(ar_gl.account_id, cust2) == D(-20000),
      "customer debit balance and advance land on the customer account per person")
with new_session() as s:
    docs = {d.counterparty_detail_account_id: d for d in s.scalars(select(CommercialDocument).where(
        CommercialDocument.document_type_code.in_(("OPENING_RECEIVABLE", "OPENING_PAYABLE"))))}
check(set(docs) == {cust1, supplier} and docs[cust1].total_amount == D(300000) and docs[cust1].due_date == due,
      "open item only for the debit balance (with due date); the advance has no open document")
check(any(u.document_id == docs[cust1].document_id for u in settlements.list_unsettled_invoices(company_id, "SALES_INVOICE")),
      "opening balance appears in invoice settlement")
check(orec.report(company_id, run).ok, "reconciliation clean")
ofin.lock_run(company_id, manager, run)
check(orun.get_run(company_id, run).status_code == "LOCKED", "locked from the form flow")
raises(lambda: osh.save_parties(company_id, entry, run, "RECEIVABLES", [{"person_code": "C1", "debit": D(1)}]), "")
check(osh.sync_control_rows(company_id, entry, run) == 0, "locked run is never re-synced")

# ===== ۸) اصلاحیه: برگشت پیش‌دریافت =====
toggle(oc.OPN_SELF_APPROVAL, True)
corr = orun.create_run(company_id, uid, "OPN-C1", "اصلاحیه", fy_id, balance_date, ["RECEIVABLES", "GL"], go_live_date=go_live,
                       corrects_run_id=run)
adv_row = next(x for x in ofin.reversible_rows(company_id, corr) if x.payload.get("counterparty_code") == "C2")
je = ofin.reverse_open_item(company_id, uid, corr, adv_row.row_id, "پیش‌دریافت اشتباه")
check(je and person_balance(ar_gl.account_id, cust2) == 0, "an advance (no open document) is reversed in a correction run")
fx.finish()
