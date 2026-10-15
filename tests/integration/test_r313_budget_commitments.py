"""R313: چرخهٔ تعهد و واقعی بودجه — تایید/بازگشت/لغو/حذف سفارش، فاکتور جزئی با قیمت متفاوت، بستن تعهد، برگشت از خرید،
فاکتور مستقیم، چند ارز، تغییر مرکز هزینه، اصلاح فاکتور، درخواست خرید، دقیق‌ترین ردیف و اصلاحیه؛ بدون دوباره‌شماری."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r313_commit"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bud_fixture import *  # noqa: F401,F403
import bud_fixture as fx

check, raises = fx.check, fx.raises

# ردیف‌ها: کل خرید / مرکز هزینهٔ A / مرکز هزینهٔ A + گروه مواد اولیه
bid, vid, (l_all, l_cc, l_raw) = make_budget([(P(), D(10_000_000)), (P(cost_center_detail_account_id=cc_a), D(5_000_000)),
                                              (P(cost_center_detail_account_id=cc_a, category_id=cat_raw), D(3_000_000))])
check(len(bud.split_periods(fy_start, fy_end, "MONTH")) == 12 and len(bud.split_periods(fy_start, fy_end, "QUARTER")) == 4,
      "fiscal year split into 12 months / 4 quarters")
v = bud.get_version(company_id, vid)
check(v.status_code == "PUBLISHED" and all(sum(ln.periods.values()) == ln.amount for ln in v.lines),
      "published version; every line's periods sum to its amount")

# ===== ۱) سفارش: تایید ← تعهد؛ بازگشت ← آزاد؛ دقیق‌ترین ردیف =====
o1 = po([(mat, 10, 100_000)], cc=cc_a)                       # 1,000,000 → CC-A + مواد اولیه
o2 = po([(other, 5, 100_000)], cc=cc_a)                      # 500,000 → CC-A
o3 = po([(other, 2, 100_000)])                               # 200,000 → کل خرید
check(totals(l_raw)["COMMIT"] == D(1_000_000) and totals(l_cc)["COMMIT"] == D(500_000) and totals(l_all)["COMMIT"] == D(200_000),
      "each order line hits exactly one (the most specific) budget line")
docs.revert_to_draft(o3, company_id)
check(totals(l_all)["COMMIT"] == 0 and entries(o3)[-1].event_code == "REVERT", "revert to draft releases the commitment (event REVERT)")
confirm(o3)
check(totals(l_all)["COMMIT"] == D(200_000), "re-confirm commits again")
docs.cancel_document(o3, company_id, note="منصرف شدیم", cancelled_by_user_id=uid)
check(totals(l_all)["COMMIT"] == 0 and entries(o3)[-1].event_code == "CANCEL" and entries(o3)[-1].amount == D(-200_000),
      "order cancellation releases the commitment (traceable negative entry)")

# ===== ۲) فاکتور جزئی با قیمت بیشتر از سفارش =====
post(o1)                                                     # ثبت نهایی سفارش: فقط قفل، بی‌اثر بر بودجه
check(totals(l_raw)["COMMIT"] == D(1_000_000), "posting the order does not change the commitment")
inv1 = invoice_from(o1, qty=4, price=110_000)
check(totals(l_raw)["COMMIT"] == D(1_000_000), "draft invoice from the order changes nothing")
confirm(inv1)
t = totals(l_raw)
check(t["COMMIT"] == D(600_000) + D(440_000) and t["ACTUAL"] == 0,
      f"confirmed partial invoice: order keeps 6×100k, invoice commits 4×110k ({t})")
post(inv1)
t = totals(l_raw)
check(t["COMMIT"] == D(600_000) and t["ACTUAL"] == D(440_000), f"posted invoice becomes actual; no double counting ({t})")

# ===== ۳) بستن تعهد ماندهٔ سفارش و بازگشایی =====
rows = bex.open_order_lines(company_id, o1)
check(rows[0].open_qty == 6 and rows[0].open_amount == D(600_000), "open order lines: 6 left = 600,000")
check(bex.close_commitment(company_id, uid, o1, "تامین‌کننده باقی را تحویل نمی‌دهد") == 1 and totals(l_raw)["COMMIT"] == 0,
      "closing the order commitment releases the remainder")
check(raises(lambda: bex.close_commitment(company_id, uid, o1, "دوباره"), "باز ندارد"), "nothing left to close")
check(entries(o1)[-1].event_code == "CLOSE" and entries(o1)[-1].amount == D(-600_000), "closure is a traceable CLOSE entry")
bex.reopen_commitment(company_id, uid, o1, "تحویل باقی‌مانده هماهنگ شد")
check(totals(l_raw)["COMMIT"] == D(600_000), "reopening restores the commitment")
bex.close_commitment(company_id, uid, o1, "بستن نهایی")

# ===== ۴) برگشت از خرید و فاکتور مستقیم =====
ret = make_doc("PURCHASE_RETURN", [(mat, 1, 110_000)], cc=cc_a)
confirm(ret)
post(ret)
check(totals(l_raw)["ACTUAL"] == D(330_000), "purchase return reduces actual")
dinv = make_doc("PURCHASE_INVOICE", [(other, 3, 50_000)], cc=cc_a)
confirm(dinv)
check(totals(l_cc)["COMMIT"] == D(650_000), "confirmed direct invoice is a commitment")
post(dinv)
t = totals(l_cc)
check(t["COMMIT"] == D(500_000) and t["ACTUAL"] == D(150_000), f"posted direct invoice moves commitment to actual ({t})")

# ===== ۵) چند ارز: مبلغ با نرخ خود سند به ارز پایه =====
o4 = po([(other, 2, 10)], currency=usd, rate=D(50_000))
e = entries(o4)[-1]
check(totals(l_all)["COMMIT"] == D(1_000_000) and e.amount_fc == D(20) and e.currency_id == usd and e.exchange_rate == D(50_000),
      "foreign-currency order: 2×10 USD × 50,000 = 1,000,000 base; original currency kept")

# ===== ۶) تغییر مرکز هزینه پس از تایید ← انتقال تعهد =====
docs.update_document_dimensions(o4, company_id, cc_a, None)
check(totals(l_all)["COMMIT"] == 0 and totals(l_cc)["COMMIT"] == D(1_500_000) and entries(o4)[-1].event_code == "DIMENSION",
      "changing the cost center moves the commitment to the matching line")

# ===== ۷) حذف سفارش تاییدشده (سابقه دارد و حذف نمی‌شود) ← تعهد دست‌نخورده؛ پیش‌نویس حذف‌شدنی بی‌اثر =====
check(raises(lambda: docs.delete_document(o4, company_id), "وابسته") and totals(l_cc)["COMMIT"] == D(1_500_000),
      "a confirmed order with history is not deleted and its commitment stays")
docs.cancel_document(o4, company_id, note="حذف", cancelled_by_user_id=uid)
check(totals(l_cc)["COMMIT"] == D(500_000), "cancelling it releases the commitment")
o5 = make_doc("PURCHASE_ORDER", [(other, 1, 1_000)], cc=cc_a)
docs.delete_document(o5, company_id)
check(not entries(o5), "deleting a draft order leaves no budget trace")

# ===== ۸) اصلاح فاکتور ثبت‌شده =====
corr = docs.start_invoice_correction(dinv, company_id, uid)
cl = docs.get_document(corr, company_id)[1][0]
docs.update_line(cl.line_id, corr, company_id, D(3), D(60_000))
confirm(corr)
check(totals(l_cc)["ACTUAL"] == D(150_000), "confirmed correction draft changes nothing yet")
docs.post_invoice_correction(corr, company_id, uid)
check(totals(l_cc)["ACTUAL"] == D(180_000) and status(dinv) == "CORRECTED",
      "posted correction replaces the original actual (150k → 180k), original not counted twice")

# ===== ۹) درخواست خرید: پیش‌تعهد ← سفارش =====
req = prs.create_request(company_id, uid, prs.RequestFields(today, cost_center_detail_account_id=cc_b))
prs.add_line(req, company_id, other, base_uom(other), D(10), estimated_unit_price=D(20_000))
prs.submit_request(req, company_id)
prs.approve_request(req, company_id, uid)
check(totals(l_all)["PRE"] == D(200_000), "approved purchase request is a pre-commitment")
orders = prs.convert_to_orders(req, company_id, uid, supplier_id=supplier, quantities={
    prs.get_request(req, company_id)[1][0].line_id: D(4)})
check(totals(l_all)["PRE"] == D(200_000), "draft order from the request does not move the amount yet")
confirm(orders[0])
t = totals(l_all)
check(t["PRE"] == D(120_000) and t["COMMIT"] == D(80_000), f"confirmed order: pre-commitment 6 left, commitment 4 ({t})")

# ===== ۱۰) تطبیق دوباره: دفتر با اسناد یکی است =====
with new_session() as s:
    again = bl.compute(s, company_id, bl.all_sources(s, company_id))
check(not again.deltas, f"full re-match finds no difference ({len(again.deltas)})")

# ===== ۱۱) اصلاحیه با ردیف دقیق‌تر ← انتقال مصرف پس از انتشار =====
toggle(sc.BUD_SELF_APPROVAL, True)
av = bud.create_revision(company_id, uid, bid, "AMENDMENT", "افزودن بودجهٔ واحد اداری")
check(raises(lambda: bud.create_revision(company_id, uid, bid), "نسخهٔ باز"), "only one open version at a time")
l_ccb = bud.add_line(company_id, uid, av, P(cost_center_detail_account_id=cc_b), D(1_000_000))
for step in (bap.submit, bap.review, bap.approve, bap.publish):
    step(company_id, uid, av)
toggle(sc.BUD_SELF_APPROVAL, False)
check(totals(l_ccb)["PRE"] == D(120_000) and totals(l_ccb)["COMMIT"] == D(80_000) and totals(l_all)["PRE"] == 0,
      "after publishing the amendment, CC-B documents move to the new, more specific line")
with new_session() as s:
    vers = {v.status_code for v in bud.get_budget(company_id, bid).versions}
check(vers == {"SUPERSEDED", "PUBLISHED"}, "previous version superseded, new one published")
check(any(x.event_code == "VERSION" for x in entries(orders[0])), "remap entries carry the VERSION event")
nv = bud.get_version(company_id, av)
check(next(ln for ln in nv.lines if ln.line_id == l_ccb).previous_amount is None
      and next(ln for ln in nv.lines if ln.key_id == key_of(l_cc)).previous_amount == D(5_000_000),
      "amendment keeps the previous approved amount per line")

fx.finish()
