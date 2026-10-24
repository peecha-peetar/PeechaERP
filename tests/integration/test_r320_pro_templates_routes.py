"""R320: قالب‌های چاپ با طرح حرفه‌ای (راست‌به‌چپ، فارسی) و پیشنهاد مسیر پخش سرد بر اساس موقعیت مشتری — هر دو پشت کلید."""
import os, re, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r320"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

import xml.etree.ElementTree as ET
from pathlib import Path

from peecha.db.models.commercial import CreditHold, CustomerProfile, DistributionRunDocument
from peecha.reporting import jasper_bridge
from peecha.reporting.registry import FORM_DEFINITIONS
from peecha.services import commercial_credit as credit_service
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_partners as partners
from peecha.services import commercial_pricing as pricing_service
from peecha.services import commercial_settings as csettings_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import distribution_routing as routing
from peecha.services import distribution_runs as runs
from peecha.services import report_templates as rt

TEMPLATES = Path(jasper_bridge.template_path("invoice.jrxml")).parent


def decl(name):
    text_ = (TEMPLATES / name).read_text(encoding="utf-8")
    return (set(re.findall(r'<parameter name="([^"]+)"', text_)), set(re.findall(r'<field name="([^"]+)"', text_)))


# --- ۱۵: طرح حرفه‌ای ---------------------------------------------------------------------------------------
pro_forms = {k: v for k, v in FORM_DEFINITIONS.items() if v.get("pro_template")}
check(len(pro_forms) == 9 and "POS_RECEIPT" not in pro_forms, f"professional design for every printable form but the POS slip ({len(pro_forms)})")
for code, d in pro_forms.items():
    root = ET.parse(TEMPLATES / d["pro_template"]).getroot()
    check(root.tag.endswith("jasperReport") and decl(d["pro_template"]) == decl(d["base_template"]),
          f"{d['pro_template']}: valid and same parameters/fields as {d['base_template']}")
inv_pro = (TEMPLATES / "invoice_pro.jrxml").read_text(encoding="utf-8")
check('evaluationTime="Master"' in inv_pro and "MASTER_TOTAL_PAGES" in inv_pro and '"۰"' in inv_pro,
      "footer shows page x of y in Persian digits")
check("REPORT_COUNT} % 2 == 0" in inv_pro and "مهر و امضای فروشنده" in inv_pro and "مبلغ به حروف" in inv_pro,
      "zebra rows, signatures and amount in words")

check(rt.fallback_template_path(company_id, "COMMERCIAL_INVOICE").name == "invoice.jrxml"
      and rt.fallback_template_path(company_id, "STOCK_DOCUMENT").name == "stock_document.jrxml", "switch off: built-in basic templates")
r_basic = rt.create_template(company_id, "COMMERCIAL_INVOICE", "فاکتور ساده")
check(rt.get_template_path(r_basic.report_template_id, company_id).read_text(encoding="utf-8")
      == (TEMPLATES / "invoice.jrxml").read_text(encoding="utf-8"), "switch off: new report starts from the basic design")
engine_service.set_feature_enabled(company_id, rt.FEATURE_PRO, True)
check(rt.fallback_template_path(company_id, "COMMERCIAL_INVOICE").name == "invoice_pro.jrxml"
      and rt.fallback_template_path(company_id, "STOCK_DOCUMENT").name == "stock_document_pro.jrxml"
      and rt.fallback_template_path(company_id, "POS_RECEIPT").name == "pos_receipt.jrxml", "switch on: professional fallback")
r_pro = rt.create_template(company_id, "TRIAL_BALANCE", "تراز حرفه‌ای")
check(rt.get_template_path(r_pro.report_template_id, company_id).read_text(encoding="utf-8")
      == (TEMPLATES / "trial_balance_pro.jrxml").read_text(encoding="utf-8"), "switch on: new report starts from the professional design")
r_b2 = rt.create_template(company_id, "TRIAL_BALANCE", "تراز ساده", design="BASIC")
check(rt.get_template_path(r_b2.report_template_id, company_id).read_text(encoding="utf-8")
      == (TEMPLATES / "trial_balance.jrxml").read_text(encoding="utf-8"), "basic design can still be chosen")
check(raises(lambda: rt.create_template(company_id, "POS_RECEIPT", "فیش", design="PRO"), "حرفه‌ای"), "POS slip has no professional design")

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)
from peecha.ui import app_style

app_style.install(app)
from peecha.ui.screens.inventory_settings import _FeatureToggleTab
from peecha.ui.screens.report_template_settings import _NewReportDialog, _ReportTemplatesTab

letters = re.compile(r"[A-Za-z؀-ۿ]{2,}")
tab = _ReportTemplatesTab()
tab.refresh()
check(tab.pro_box.isChecked() and tab.table.rowCount() == 3, "settings › reports: switch and report list")
check(tab._add({"form_code": "STOCK_DOCUMENT", "name": "سند انبار حرفه‌ای", "design": "PRO"}) and tab.table.rowCount() == 4,
      "add a professional report from the settings tab")
tab.pro_box.setChecked(False)
check(not rt.pro_by_default(company_id), "switch turned off from the settings tab")
dlg = _NewReportDialog(tab, pro_default=True)
dlg.form_combo.setCurrentIndex(dlg.form_combo.findData("JOURNAL_BOOK"))
check(dlg.selected_design() == "PRO" and dlg.design_combo.isEnabled(), "new report dialog proposes the professional design")
dlg.form_combo.setCurrentIndex(dlg.form_combo.findData("POS_RECEIPT"))
check(dlg.selected_design() == "BASIC" and not dlg.design_combo.isEnabled(), "and locks it for forms without one")
bad = [b.text() for b in tab.findChildren(QPushButton) if letters.search(b.text() or "")]
check(not bad, f"report settings buttons are icon-only ({bad})")
inv_tab = _FeatureToggleTab()
inv_tab.refresh()
check(rt.FEATURE_PRO not in inv_tab._checkboxes, "report switch not duplicated in inventory settings")

# --- ۱۸: مسیر پخش سرد -----------------------------------------------------------------------------------------
pts = {"a": (35.70, 51.40), "b": (35.75, 51.45), "c": (35.80, 51.50), "e": (35.72, 51.42)}
check(routing.order_points(pts, (35.69, 51.39)) == ["a", "e", "b", "c"], "from the depot: nearest first, along the line")
check(routing.order_points(pts) == ["c", "b", "e", "a"], "no depot: start from one end")
check(abs(routing.distance_km((35.70, 51.40), (35.80, 51.40)) - 11.12) < 0.05, "great-circle distance in km")

g_ar = A("13", "دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
ar = A("131", "حساب‌های دریافتنی", "DEBIT", "ASSET", "PERMANENT", True, g_ar.account_id)
g_rev = A("4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False)
k_rev = A("41", "درآمد عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, g_rev.account_id)
rev = A("411", "درآمد فروش", "CREDIT", "REVENUE", "TEMPORARY", True, k_rev.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar.account_id)
csettings_service.set_account_mapping(company_id, "SALES_REVENUE", rev.account_id)
sell = item("SL-1", "کالای فروشی", "GOOD", is_sellable=True)
receive(sell, 100, 500)
channel = pricing_service.create_channel(company_id, "COLD", "پخش سرد", "PRE_SALES")
vehicle = locations_service.create_warehouse(company_id, "VEH", "وانت پخش", WF(warehouse_type_code="VEHICLE", vehicle_plate_number="12ب345"))


def posted_invoice(customer):
    order = documents_service.create_document(company_id, uid, "SALES_ORDER", today, documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=customer, currency_id=company.base_currency_id, warehouse_id=wh_rm, channel_code=channel))
    documents_service.add_line(order, company_id, item_id=sell, uom_id=pcs, quantity=D(1), quantity_base=D(1), unit_price=D(1000))
    documents_service.confirm_document(order, company_id, uid)
    with new_session() as s:
        hold = s.scalar(select(CreditHold).where(CreditHold.related_document_id == order, CreditHold.released_at.is_(None)))
    if hold is not None:
        credit_service.release_credit_hold(hold.hold_id, uid)
    documents_service.approve_document(order, company_id)
    documents_service.approve_warehouse(order, company_id, uid)
    if documents_service.document_requires_weighing(order, company_id):
        documents_service.approve_weighing(order, company_id, uid)
    invoice = documents_service.convert_to_invoice(order, company_id, uid, today)
    documents_service.confirm_document(invoice, company_id, uid)
    settlements_service.auto_approve_full_cash_settlement_plan(invoice, company_id, uid)
    documents_service.post_document(invoice, company_id, uid)
    return invoice


cust = {k: dimensions_service.create_customer(company_id, f"C-{k}", f"مشتری {k}") for k in "abcde"}
partners.add_party_address(cust["a"], "DELIVERY", "آدرس تحویل الف", gps_latitude=D("35.70"), gps_longitude=D("51.40"))
partners.add_party_address(cust["b"], "OFFICE", "دفتر دور", is_default=True, gps_latitude=D("36.50"), gps_longitude=D("52.50"))
partners.add_party_address(cust["b"], "STORE", "فروشگاه ب", gps_latitude=D("35.75"), gps_longitude=D("51.45"))
partners.add_party_address(cust["e"], "DELIVERY", "آدرس تحویل هـ", gps_latitude=D("35.72"), gps_longitude=D("51.42"))
partners.add_party_address(cust["d"], "STORE", "فروشگاه بی‌مختصات")
with new_session() as s:
    profile = s.get(CustomerProfile, cust["c"])
    if profile is None:
        profile = CustomerProfile(customer_detail_account_id=cust["c"], company_id=company_id)
        s.add(profile)
    profile.gps_latitude, profile.gps_longitude = D("35.80"), D("51.50")
    s.commit()
locs = routing.customer_locations(set(cust.values()))
check(locs[cust["b"]] == (35.75, 51.45) and locs[cust["c"]] == (35.80, 51.50) and cust["d"] not in locs,
      "location: delivery/store address before others, then the customer file; none for d")

invoices = {k: posted_invoice(cust[k]) for k in "dcabe"}
check(len(runs.list_eligible_invoices(company_id)) == 5, "five posted cold-distribution invoices")
run_id = runs.create_distribution_run(company_id, uid, today, vehicle)
for k in "dcabe":
    runs.add_document_to_run(run_id, company_id, invoices[k])
order_of = lambda: [next(k for k, v in invoices.items() if v == i.document_id) for i in runs.get_distribution_run(run_id, company_id).invoices]
check(order_of() == list("dcabe"), "before routing the run keeps its old order (document id)")
check(raises(lambda: routing.suggest(company_id, run_id), "خاموش"), "switch off: no route suggestion")
check(any(f.feature_code == routing.FEATURE and not f.is_enabled for f in csettings_service.list_features(company_id)),
      "switch listed under sales › features")
csettings_service.set_feature_enabled(company_id, routing.FEATURE, True)

plan = routing.suggest(company_id, run_id)
keys = [next(k for k, v in invoices.items() if v == s_.document_id) for s_ in plan.stops]
check(keys == list("cbead") and [s_.document_id for s_ in plan.missing] == [invoices["d"]] and plan.start is None,
      f"no start point: from the far end, customer without location last ({keys})")
check(order_of() == list("dcabe"), "suggesting alone saves nothing")
routing.set_start_point(company_id, run_id, 35.69, 51.39)
plan = routing.apply_suggestion(company_id, run_id)
check(order_of() == list("aebcd"), f"from the depot the invoices are sorted by route priority ({order_of()})")
with new_session() as s:
    seqs = dict(s.execute(select(DistributionRunDocument.document_id, DistributionRunDocument.route_seq)
                          .where(DistributionRunDocument.distribution_run_id == run_id)).all())
check(sorted(seqs.values()) == [1, 2, 3, 4, 5] and seqs[invoices["a"]] == 1, "route order stored on the run rows")
check(plan.stops[0].leg_km is not None and 1.0 < plan.stops[0].leg_km < 2.0 and plan.stops[-1].leg_km is None
      and 15 < plan.total_km < 20, f"leg and total distances ({plan.total_km} km)")
routing.move(company_id, run_id, invoices["e"], -1)
check(order_of() == list("eabcd"), "manual move up")
routing.move(company_id, run_id, invoices["e"], 10)
check(order_of() == list("abcde"), "manual move to the end")
check(raises(lambda: routing.apply(company_id, run_id, [invoices["a"]]), "یکی نیست"), "partial order rejected")
check(raises(lambda: routing.set_start_point(company_id, run_id, 35.0, None), "با هم"), "start point needs both coordinates")
check([i.route_seq for i in runs.get_distribution_run(run_id, company_id).invoices] == [1, 2, 3, 4, 5], "route order exposed on the run")

run2 = runs.create_distribution_run(company_id, uid, today, vehicle)
check(routing.start_point(company_id, run2) == (35.69, 51.39), "next run of the same vehicle reuses its start point")

# --- رابط کاربری تیم پخش -------------------------------------------------------------------------------------
from peecha.ui import report_export
from peecha.ui.screens.distribution_team import DistributionTeamScreen

printed = []
report_export.print_report = lambda parent, title, headers, rows, **kw: printed.append((headers, rows))
scr = DistributionTeamScreen()
scr.refresh()
scr._load_run(run_id)
check(not scr.route_bar.isHidden() and not scr.attached_table.isColumnHidden(0), "route bar and order columns shown when on")
check(scr.attached_table.item(0, 0).text() == "۱" and "کیلومتر" in scr.attached_table.item(0, 1).text()
      and scr.attached_table.item(3, 1).text() == "—", "order and leg distance per row (none for a customer without location)")
check(scr.suggest_route() and scr.attached_table.item(0, 2).data(0x0100) == invoices["a"] and "مشتری بی‌موقعیت" in scr.route_label.text(),
      f"suggest from the screen ({scr.route_label.text()})")
scr.attached_table.setCurrentCell(1, 2)
check(scr.move_stop(-1) and scr.attached_table.item(0, 2).data(0x0100) == invoices["e"]
      and scr.attached_table.currentRow() == 0,
      "move a stop from the screen")
check(scr.pick_start_point((35.68, 51.38)) and routing.start_point(company_id, run_id) == (35.68, 51.38), "start point from the screen")
scr._print_invoice_list()
check(printed and printed[-1][0][0] == "ترتیب" and printed[-1][1][0][0] == "۱", "driver list printed in route order")
bad = [b.text() for b in scr.route_bar.findChildren(QPushButton) if letters.search(b.text() or "")]
check(not bad and len(scr.route_buttons) == 4, f"route buttons are icon-only ({bad})")

runs.confirm_distribution_run(run_id, company_id, uid)
check(raises(lambda: routing.move(company_id, run_id, invoices["a"], 1), "پیش از تحویل"), "no reordering after hand-over")
csettings_service.set_feature_enabled(company_id, routing.FEATURE, False)
scr.refresh()
scr._load_run(run_id)
check(scr.route_bar.isHidden() and scr.attached_table.isColumnHidden(0) and scr.attached_table.isColumnHidden(1),
      "switch off: screen as before")
scr._print_invoice_list()
check(printed[-1][0][0] == "شماره", "switch off: driver list as before")

finish()
