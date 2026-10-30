"""R312: قطعه و هزینهٔ دستور کار — رزرو، صدور و برگشت فقط با موتور انبار (موجودی و سند حسابداری درست، مرکز هزینهٔ
دارایی)، کلید یکتایی، درخواست خرید کمبود، خدمات پیمانکار از مسیر دارایی یا فاکتور خرید، و نبودِ هزینهٔ دوباره پس از بستن."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r312_parts"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mnt_fixture import *  # noqa: F401,F403
import mnt_fixture as fx
from peecha.db.models.accounting import JournalEntryLine, JournalEntryLineDetail
from peecha.db.models.commercial import PurchaseRequest, PurchaseRequestLine
from peecha.db.models.inventory import StockDocument, StockReservation
from peecha.db.models.maintenance import WorkOrderPartMove
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_settings as csettings_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import treasury as treasury_service

check, raises = fx.check, fx.raises

m1 = machine("M-01")
wo = wos.create(company_id, uid, wos.WorkOrderInput(asset_id=m1, work_type_code="CORRECTIVE", title="تعویض بلبرینگ"))
p_spare = mparts.add_part(company_id, uid, wo, spare, wh_rm, D(3))
check(mparts.add_part(company_id, uid, wo, spare, wh_rm, D(1)) == p_spare
      and mparts.list_parts(company_id, wo)[0].planned_qty == 4, "same item/warehouse is one planned line (quantity adds up)")
check(raises(lambda: mparts.add_part(company_id, uid, wo, spare, wh_rm, D(0)), "بزرگ‌تر از صفر"), "zero quantity refused")

# ===== ۱) رزرو با همان رزرو مشترک انبار =====
reserved = mparts.reserve(company_id, uid, wo)
check(reserved == 4, f"reserved free stock for the planned parts (got {reserved})")
with new_session() as s:
    res = list(s.scalars(select(StockReservation).where(StockReservation.source_type_code == "MNT_PART",
                                                        StockReservation.status_code == "ACTIVE")))
check(len(res) >= 1 and sum(r.quantity for r in res) == 4, "reservation rows are in inv.stock_reservations (source MNT_PART)")
check(mparts.reserve(company_id, uid, wo) == 0, "re-reserving does not double the reservation")

# ===== ۲) صدور: موجودی و سند حسابداری با مرکز هزینهٔ دارایی =====
before_qty, before_gl = on_hand(spare, wh_rm), gl_balance(parts_gl.account_id)
docs = mparts.issue(company_id, uid, wo, [mparts.PartLine(p_spare, D(2))], idempotency_key="ISS-1")
check(on_hand(spare, wh_rm) == before_qty - 2, "issue reduces on-hand through the inventory engine")
check(gl_balance(parts_gl.account_id) - before_gl == 1_000_000, "debit «maintenance parts expense» at inventory cost (2 × 500,000)")
with new_session() as s:
    doc = s.get(StockDocument, docs[0])
    check(doc.document_type_code == "ISSUE" and doc.status_code == "POSTED" and doc.reference_no.startswith("WO-")
          and doc.cost_center_detail_account_id == cc_line, "posted stock issue, referenced to the work order, with the asset's cost centre")
    dims = set(s.scalars(select(JournalEntryLineDetail.detail_account_id).join(
        JournalEntryLine, JournalEntryLine.line_id == JournalEntryLineDetail.line_id).where(
        JournalEntryLine.account_id == parts_gl.account_id)))
check(cc_line in dims, "expense line carries the asset's cost-centre dimension")
again = mparts.issue(company_id, uid, wo, [mparts.PartLine(p_spare, D(2))], idempotency_key="ISS-1")
check(again == docs and on_hand(spare, wh_rm) == before_qty - 2, "repeating the issue with the same key: no second document")
pl = mparts.list_parts(company_id, wo)[0]
check(pl.issued_qty == 2 and pl.net_amount == 1_000_000 and pl.reserved == 2, "part line: issued 2, reservation consumed 2 of 4")

# خطا در وسط عملیات = هیچ چیز ثبت نمی‌شود (اتمیک)
with new_session() as s:
    moves_before = s.scalar(select(func.count()).select_from(WorkOrderPartMove))
    docs_before = s.scalar(select(func.count()).select_from(StockDocument))
check(raises(lambda: mparts.issue(company_id, uid, wo, [mparts.PartLine(p_spare, D(50))]), "کافی نیست"),
      "issuing more than stock is refused")
with new_session() as s:
    check(s.scalar(select(func.count()).select_from(WorkOrderPartMove)) == moves_before
          and s.scalar(select(func.count()).select_from(StockDocument)) == docs_before
          and on_hand(spare, wh_rm) == before_qty - 2, "failed issue leaves no part move, no stock document, no stock change")

# ===== ۳) برگشت =====
mparts.return_parts(company_id, uid, wo, [mparts.PartLine(p_spare, D(1))], idempotency_key="RET-1")
mparts.return_parts(company_id, uid, wo, [mparts.PartLine(p_spare, D(1))], idempotency_key="RET-1")
check(on_hand(spare, wh_rm) == before_qty - 1 and gl_balance(parts_gl.account_id) - before_gl == 500_000,
      "return of 1 at the issued average cost credits the expense once (same key)")
check(raises(lambda: mparts.return_parts(company_id, uid, wo, [mparts.PartLine(p_spare, D(5))]), "بیشتر"),
      "cannot return more than net issued")
pl = mparts.list_parts(company_id, wo)[0]
check(pl.net_qty == 1 and pl.net_amount == 500_000, "net consumption 1 piece, 500,000")

# ===== ۴) کمبود ← درخواست خرید (همان مسیر خرید) =====
p_belt = mparts.add_part(company_id, uid, wo, belt, wh_rm, D(5))
short = {a.part_id: a for a in mparts.availability_of(company_id, wo)}
check(short[p_belt].shortage == 3, f"shortage = need − free stock (got {short[p_belt].shortage})")
pr_id = mparts.request_purchase(company_id, uid, wo, required_date=today + days(5))
with new_session() as s:
    pr = s.get(PurchaseRequest, pr_id)
    lines = list(s.scalars(select(PurchaseRequestLine).where(PurchaseRequestLine.request_id == pr_id)))
check(pr.status_code == "DRAFT" and pr.cost_center_detail_account_id == cc_line and len(lines) == 1
      and lines[0].item_id == belt and lines[0].quantity == 3,
      "a draft purchase request (authorised purchasing flow) for the shortage, with the asset's cost centre")
check(mparts.request_purchase(company_id, uid, wo) is None, "no second purchase request while one is open")
check(mparts.list_parts(company_id, wo)[1].purchase_request_no == pr.request_no, "part line shows its purchase request")

# نگاشت حساب نداشتن = پیام روشن، نه سند ناقص
with new_session() as s:
    s.execute(text("DELETE FROM inv.account_mappings WHERE company_id = :c AND mapping_key = 'MAINTENANCE_EXPENSE'"), {"c": company_id})
    s.commit()
check(raises(lambda: mparts.issue(company_id, uid, wo, [mparts.PartLine(p_spare, D(1))]), "هزینهٔ قطعات تعمیر و نگهداری"),
      "missing mapping: clear message, nothing posted")
engine_service.set_account_mapping(company_id, "MAINTENANCE_EXPENSE", parts_gl.account_id)

# ===== ۵) خدمات پیمانکار: ثبت از مسیر دارایی (تعمیر یا افزایش سرمایه‌ای طبق سیاست) =====
fac.update_settings(company_id, uid, improvement_capitalize_min=D(50_000_000))
c_srv = mcost.add_cost(company_id, uid, wo, "SERVICE", "بالانس اسپیندل توسط پیمانکار", D(2_000_000), contractor)
before_repair = gl_balance(repair_gl.account_id)
st = mcost.post(company_id, uid, c_srv, ap_gl.account_id, contractor)
row = next(x for x in mcost.list_costs(company_id, wo) if x.cost_id == c_srv)
check(st == "POSTED" and row.accounting_code == "EXPENSE" and gl_balance(repair_gl.account_id) - before_repair == 2_000_000,
      "service below the capitalisation threshold → repair expense through fixed_assets.improve (category repair account)")
check(raises(lambda: mcost.post(company_id, uid, c_srv, ap_gl.account_id, contractor), "وضعیت"),
      "posting the same cost again is refused")
with new_session() as s:
    n_ev = s.scalar(text("SELECT count(*) FROM fa.asset_events WHERE idempotency_key = :k"), {"k": f"MNT-COST-{c_srv}"})
check(n_ev == 1, "exactly one asset event for the cost (idempotency key MNT-COST-<id>)")
gross_before = fa.get_asset(company_id, m1).gross_cost
c_cap = mcost.add_cost(company_id, uid, wo, "SERVICE", "بازسازی کامل گیربکس", D(60_000_000), contractor)
mcost.post(company_id, uid, c_cap, ap_gl.account_id, contractor)
check(next(x for x in mcost.list_costs(company_id, wo) if x.cost_id == c_cap).accounting_code == "CAPITALIZE"
      and fa.get_asset(company_id, m1).gross_cost - gross_before == 60_000_000,
      "above the threshold the existing policy capitalises the improvement (asset cost increases)")
c_none = mcost.add_cost(company_id, uid, wo, "OTHER", "کار زیر پوشش ضمانت", D(300_000))
check(raises(lambda: mcost.mark_none(company_id, uid, c_none, ""), "علت"), "no-posting needs a reason")
mcost.mark_none(company_id, uid, c_none, "زیر پوشش ضمانت فروشنده")
c_draft = mcost.add_cost(company_id, uid, wo, "OTHER", "حمل", D(100_000))

# ===== ۶) اتصال به فاکتور خرید ثبت‌شده (بدون ثبت دوباره) =====
csettings_service.set_feature_enabled(company_id, "PURCHASE_INVOICE_SKIP_APPROVAL", True)
supplier_group_id = next(g.person_group_id for g in dimensions_service.list_person_groups(company_id) if g.code == "SUPPLIER")
treasury_service.create_counterparty_mapping(company_id, "PAYMENT", ap_gl.account_id, person_group_id=supplier_group_id)
inv = documents_service.create_document(company_id, uid, "PURCHASE_INVOICE", today, documents_service.DocumentHeaderFields(
    counterparty_detail_account_id=contractor, currency_id=company.base_currency_id, warehouse_id=wh_rm))
documents_service.add_line(inv, company_id, belt, pcs, D(1), D(1), unit_price=D(150_000))
documents_service.confirm_document(inv, company_id, uid)
settlements_service.auto_approve_settlement_plan(inv, company_id, uid, [])
documents_service.post_document(inv, company_id, uid)
c_inv = mcost.add_cost(company_id, uid, wo, "SERVICE", "قطعه و خدمت طبق فاکتور", D(100_000), contractor)
gl_snapshot = gl_balance(repair_gl.account_id)
mcost.link_invoice(company_id, uid, c_inv, inv)
check(next(x for x in mcost.list_costs(company_id, wo) if x.cost_id == c_inv).status_code == "LINKED"
      and gl_balance(repair_gl.account_id) == gl_snapshot, "linking to a posted purchase invoice creates no new posting")
c_over = mcost.add_cost(company_id, uid, wo, "SERVICE", "بیش از فاکتور", D(100_000), contractor)
check(raises(lambda: mcost.link_invoice(company_id, uid, c_over, inv), "بیشتر"),
      "links to one invoice cannot exceed the invoice total")
mcost.cancel_cost(company_id, uid, c_over, "اشتباه")

# ===== ۷) بستن: هزینهٔ تعیین‌تکلیف‌نشده مانع است؛ پس از بستن نه قطعه نه هزینه =====
wos.start(company_id, uid, wo)
wos.complete(company_id, uid, wo, "انجام شد")
wos.verify(company_id, uid, wo, "PASS")
check(raises(lambda: wos.close(company_id, uid, wo), "تعیین تکلیف"), "an undecided cost blocks closing")
mcost.mark_none(company_id, uid, c_draft, "در هزینهٔ حمل کلی شرکت")
summary = mcost.summary(company_id, wo)
wos.close(company_id, uid, wo)
with new_session() as s:
    left = s.scalar(select(func.count()).where(StockReservation.source_type_code == "MNT_PART", StockReservation.status_code == "ACTIVE"))
check(left == 0, "closing releases the remaining part reservation")
check(raises(lambda: mparts.issue(company_id, uid, wo, [mparts.PartLine(p_spare, D(1))]), "بسته‌شده"),
      "closed work order: no further part consumption")
check(raises(lambda: mcost.add_cost(company_id, uid, wo, "OTHER", "x", D(1)), "بسته"), "closed work order: no further cost")
check(mcost.summary(company_id, wo).total == summary.total, "cost summary is unchanged after close")
check(summary.parts == 500_000 and summary.services == 2_000_000 + 60_000_000 + 100_000
      and summary.other == 300_000 + 100_000 and summary.total == summary.parts + summary.labor + summary.services + summary.other,
      f"cost per work order = parts (net) + labour + services + other (got {summary})")

fx.finish()
