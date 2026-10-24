"""R310: مرحلهٔ ۱ — ظرفیت تولید فقط با ماشین‌های در دسترس، امتیاز کیفیت تامین‌کننده از بازرسی‌های واقعی و قابل ردیابی،
و «بدون داده» به‌جای صفر در شاخص‌هایی که مخرج ندارند."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r310"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from sqlalchemy import update
from peecha.db.models.commercial import SupplierProfile
from peecha.db.models.inventory import Item
from peecha.services import inventory_documents as inv_docs
from peecha.services import purchase_reports as pr
from peecha.services import quality_control as qc
from peecha.services import stock_controls as sc
from peecha.services import supplier_quality as sq
from peecha.services.fixed_assets import assets as fa, common as fac, events as fe
from peecha.services.production import dashboard as pdash, master as pm, planning as pp
check, raises = fx.check, fx.raises
days = datetime.timedelta

g_l = A("2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False)
k_l = A("21", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g_l.account_id)
ap_gl = A("2101", "پرداختنی تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k_l.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)

# ===== ۱) ظرفیت تولید با ماشین‌های در دسترس =====
k_fa = A("14", "دارایی‌های ثابت", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
fa_asset = A("1401", "ماشین‌آلات", "DEBIT", "ASSET", "PERMANENT", True, k_fa.account_id)
fa_accum = A("1409", "استهلاک انباشته", "CREDIT", "ASSET", "PERMANENT", True, k_fa.account_id)
k_ex = A("62", "سایر هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False, g3.account_id)
dep_exp = A("6204", "هزینهٔ استهلاک", "DEBIT", "EXPENSE", "TEMPORARY", True, k_ex.account_id)
loss_gl = A("6201", "زیان واگذاری", "DEBIT", "EXPENSE", "TEMPORARY", True, k_ex.account_id)
mach = fac.save_category(company_id, fac.CategoryFields("MACH", "ماشین‌آلات", "STRAIGHT_LINE", 12, accounts=dict(
    asset_account_id=fa_asset.account_id, accumulated_depreciation_account_id=fa_accum.account_id,
    depreciation_expense_account_id=dep_exp.account_id, disposal_loss_account_id=loss_gl.account_id)))
seller = dimensions_service.create_supplier(company_id, "S-FA", "فروشندهٔ ماشین")

wc = pm.save_work_center(company_id, pm.WorkCenterFields(code="CUT", name="برش"), user_id=uid)
week = (today, today + days(6))
working = lambda d0, d1: [d0 + days(i) for i in range((d1 - d0).days + 1) if ((d0 + days(i)).weekday() + 2) % 7 < 6]  # noqa: E731
cap = lambda d0, d1: next(x for x in pp.capacity_load(company_id, d0, d1) if x.work_center_id == wc)  # noqa: E731
c0 = cap(*week)
check(c0.capacity_hours == c0.nominal_capacity_hours == 48 and pp.machines_label(c0) == "تعریف نشده",
      "a work center without machines keeps its nominal capacity (6 days × 8h)")


def machine(code):
    aid = fa.create_asset(company_id, uid, fa.AssetFields(asset_code=code, name="دستگاه " + code, category_id=mach,
                                                          is_production_machine=True, work_center_code="CUT"))
    fa.acquire(company_id, uid, aid, today - days(40), [fa.CostItem("PURCHASE", D(1_200_000), ap_gl.account_id, seller)])
    fa.capitalize(company_id, uid, aid, today - days(40), in_service_date=today - days(30))
    return aid


m1, m2 = machine("M-01"), machine("M-02")
c1 = cap(*week)
check(c1.capacity_hours == 48 and c1.machines_total == 2 and c1.machines_down == 0 and pp.machines_label(c1) == "2 از 2",
      "two machines in service: full capacity")

fa.set_status(company_id, uid, m1, "UNDER_MAINTENANCE", today - days(10), "تعویض تیغه")
fa.set_status(company_id, uid, m1, "IN_SERVICE", today - days(9))
past = (today - days(14), today - days(8))
expected = D(len(working(*past)) * 8) - (D(4) if today - days(10) in working(*past) else 0)
c2 = cap(*past)
check(c2.capacity_hours == expected and c2.nominal_capacity_hours == len(working(*past)) * 8,
      f"past window: the maintenance day of one machine removes half a day ({c2.capacity_hours} of {c2.nominal_capacity_hours})")
check(cap(*week).capacity_hours == 48, "machine back in service: future capacity is full again")

fa.set_status(company_id, uid, m1, "UNDER_MAINTENANCE", today, "خرابی موتور")
c3 = cap(*week)
check(c3.capacity_hours == 24 and c3.nominal_capacity_hours == 48 and pp.machines_label(c3) == "1 از 2"
      and [m.code for m in c3.down_machines] == ["M-01"] and c3.down_machines[0].status_label == "در تعمیر",
      "machine under repair is not counted: capacity halves and the report names it")

fe.scrap(company_id, uid, m2, today, "فرسودگی")
c4 = cap(*week)
check(c4.capacity_hours == 0 and c4.utilization is None and c4.free_hours == 0 and pp.machines_label(c4) == "0 از 2",
      "all machines unusable: zero capacity and utilization is 'no data', not a percentage")
c5 = cap(*past)
check(c5.capacity_hours == expected, "scrapping today does not rewrite past capacity")

from peecha.services.production import reports as prd_reports
rep = prd_reports.capacity(company_id, pr.PurchaseFilters(*week))
row = next(r for r in rep.rows if r[0].startswith("CUT"))
heads = [h for h, _k in rep.columns]
check(row[heads.index("ظرفیت اسمی (ساعت)")] == 48 and row[heads.index("ماشین در دسترس")] == "0 از 2"
      and "M-01" in row[heads.index("ماشین خارج از دسترس")] and row[heads.index("بهره‌برداری٪")] is None
      and "در دسترس" in rep.note, "capacity report shows nominal vs available capacity and the unusable machines")
check(pm.capacity_hours(pm.get_work_center(company_id, wc), *week) == 48, "nominal capacity function is unchanged")

# ===== ۲) امتیاز کیفیت تامین‌کننده از بازرسی‌های واقعی =====
supplier = partners_service.create_supplier(company_id, "S1", "تامین‌کنندهٔ دارو", fast_track=True)
other = partners_service.create_supplier(company_id, "S2", "تامین‌کنندهٔ بدون بازرسی", fast_track=True)
WF = locations_service.WarehouseFields
whn = locations_service.create_warehouse(company_id, "WH-N", "انبار اصلی", WF())
whq = locations_service.create_warehouse(company_id, "WH-Q", "انبار قرنطینه", WF(warehouse_type_code="QUARANTINE"))
med = catalog_service.create_item(company_id, "M1", "داروی الف", IF(item_kind_code="GOOD", base_uom_id=pcs, is_sellable=True))
with new_session() as s:
    s.execute(update(Item).where(Item.item_id == med).values(requires_qc=True))
    s.commit()
engine_service.set_feature_enabled(company_id, sc.RESERVATION, True)
engine_service.set_feature_enabled(company_id, sc.QC_HOLD, True)


def receipt(qtys, party=supplier):
    d = inv_docs.create_stock_document(company_id, uid, "RECEIPT", today, inv_docs.DocumentHeaderFields(
        destination_warehouse_id=whn, counterparty_detail_account_id=party))
    lines = [inv_docs.add_line(d, company_id, inv_docs.LineFields(item_id=med, uom_id=pcs, quantity=D(q), quantity_base=D(q),
                                                                 unit_cost=D(1000))) for q in qtys]
    inv_docs.confirm_stock_document(d, company_id)
    inv_docs.post_stock_document(d, company_id, uid)
    return d, lines


def profile_rating(sid):
    with new_session() as s:
        return s.get(SupplierProfile, sid).quality_rating


F = pr.PurchaseFilters(today - days(30), today)
rows = lambda code, f=F: pr.run_report(company_id, code, f).rows  # noqa: E731
check(profile_rating(supplier) is None and sq.label(None) == "بدون بازرسی", "no inspection yet: no score (not zero, not ten)")
terms = {r[0].split(" — ")[-1]: r[5] for r in rows("SUPPLIER_TERMS")}
check(terms.get("تامین‌کنندهٔ دارو") == "بدون بازرسی", "supplier terms report says 'no inspection' instead of a number")

_d1, (l1,) = receipt([10])
qc.inspect(company_id, l1, uid, D(2), whq, notes="بسته‌بندی آسیب‌دیده")
check(profile_rating(supplier) == D("8.0"), f"first inspection: 8 of 10 accepted → 8.0 ({profile_rating(supplier)})")
_d2, (l2,) = receipt([10])
qc.inspect(company_id, l2, uid)
check(profile_rating(supplier) == D("9.0") and profile_rating(other) is None,
      "second clean inspection: 18 of 20 accepted → 9.0; the other supplier stays without a score")

ins = rows("QC_INSPECTIONS")
check(len(ins) == 2 and [r[6] for r in ins] == [10, 10] and [r[7] for r in ins] == [2, 0] and [r[8] for r in ins] == [8, 10]
      and ins[0][9] == "پذیرش بخشی" and ins[1][9] == "پذیرفته" and ins[0][11] == "بسته‌بندی آسیب‌دیده" and ins[0][10],
      "inspection report lists every inspection behind the score (receipt, quantities, result, inspector, note)")
q = next(r for r in rows("QUALITY") if r[0].endswith("تامین‌کنندهٔ دارو"))
check(q[4] == 2 and q[5] == 2 and q[7] == 20 and q[6] == 10 and q[8] == D("9.0") and q[3] is None,
      f"quality report: reject rate = rejected ÷ inspected, score 9.0, return rate is 'no data' without purchases ({q})")
card = next(r for r in rows("SCORECARD") if r[0].endswith("تامین‌کنندهٔ دارو"))
check(card[8] == 90 and card[6] == 90 and card[5] is None, f"scorecard uses QC acceptance; missing indicators stay empty ({card})")
terms = {r[0].split(" — ")[-1]: r[5] for r in rows("SUPPLIER_TERMS")}
check(terms["تامین‌کنندهٔ دارو"] == "9 از ۱۰" and terms["تامین‌کنندهٔ بدون بازرسی"] == "بدون بازرسی",
      "supplier terms report shows the live score")
check(rows("QC_INSPECTIONS", pr.PurchaseFilters(today - days(30), today, supplier_id=other)) == [],
      "supplier filter applies to the inspection report")
from peecha.nav_catalog import PURCHASE_REPORT_MENU
vendor = next(items for code, _t, items in PURCHASE_REPORT_MENU if code == "VENDOR")
check(("QC_INSPECTIONS", "بازرسی‌های کیفیت رسید") in vendor and pr.report_def("QC_INSPECTIONS").title == "بازرسی‌های کیفیت رسید",
      "inspection report is in the supplier evaluation menu")

# ردیف بازرسی‌شده با شکست برگشت سند دوباره نگه داشته نمی‌شود
d3, (l3, l4) = receipt([5, 5])
qc.inspect(company_id, l3, uid)
out = inv_docs.create_stock_document(company_id, uid, "ISSUE", today, inv_docs.DocumentHeaderFields(source_warehouse_id=whn))
inv_docs.add_line(out, company_id, inv_docs.LineFields(item_id=med, uom_id=pcs, quantity=D(23), quantity_base=D(23)))
inv_docs.confirm_stock_document(out, company_id)
inv_docs.post_stock_document(out, company_id, uid)
check(raises(lambda: inv_docs.reverse_and_cancel_stock_document(d3, company_id, uid)), "reversal fails: accepted stock already issued")
with new_session() as s:
    waiting = qc.waiting_line_ids(s, [l3, l4])
check(waiting == {l4}, f"after the failed reversal only the uninspected line waits again ({waiting})")

# ===== ۳) بدون داده به‌جای صفر =====
kpis = {k.code: k.value for k in pdash.dashboard(company_id, today - days(30), today)[0]}
check(kpis["SCRAP"] is None and kpis["MAT_EFF"] is None and kpis["LAB_EFF"] is None and kpis["ORDERS"] == 0,
      "production dashboard: no production → scrap/efficiency are 'no data', counts stay zero")
from peecha.services.crm import opportunities as opp_service
check(opp_service.pipeline_summary(company_id)["conversion_rate"] is None, "CRM conversion rate without closed opportunities is 'no data'")
otd = rows("OTD")
check(all(r[4] is None for r in otd if r[1] == 0), "on-time delivery without deliveries is not shown as 0%")

from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)
token = client.post("/auth/login", json={"username": "admin", "password": "secret123"}).json()["access_token"]
body = client.get("/manager/dashboard", headers={"Authorization": "Bearer " + token},
                  params={"date_from": "2020-01-01", "date_to": "2020-01-02"}).json()
check(body["order_count"] == 0 and body["average_order_value"] is None and body["collection_rate"] is None
      and body["visit_to_order_conversion"] is None and body["sales_amount"] == "0",
      "mobile manager dashboard: rates without a base are null (shown as —), amounts stay zero")

# دسکتاپ
from PySide6.QtWidgets import QApplication
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.production import PlanningScreen
scr = PlanningScreen()
scr.refresh()
heads = [scr.t_capacity.horizontalHeaderItem(i).text() for i in range(scr.t_capacity.columnCount())]
r = next(i for i in range(scr.t_capacity.rowCount()) if scr.t_capacity.item(i, 0).text().startswith("CUT"))
check("ماشین در دسترس" in heads and "ظرفیت اسمی" in heads and scr.t_capacity.item(r, heads.index("بهره‌برداری٪")).text() == "—",
      "planning screen shows machine availability and '—' for undefined utilization")

fx.finish()
