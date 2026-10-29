"""R362: گواهی آنالیز: فقط بازرسی تأییدشده با پارامترهای الزامی منطبق، شماره‌گذاری پیاپی، مشتری از سند فروش و رد سند بی‌آن
کالا، نتایج ثابت پس از صدور، لغو فقط با دلیل، جدول چاپ؛ و فرم."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r362"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403
from sqlalchemy import update

from peecha.db.models.inventory import Item
from peecha.services import commercial_documents as docs, commercial_pricing as pricing, inventory_documents as inv_docs
from peecha.services import quality_control as qc
from peecha.services.qms import certificates as coa, plans

from peecha.services import stock_controls as sc

RI = qc.ResultInput
for code in (sc.RESERVATION, sc.QC_HOLD):
    engine_service.set_feature_enabled(company_id, code, True)
med = item("MD-1", "داروی الف", "GOOD", is_sellable=True)
with new_session() as s:
    s.execute(update(Item).where(Item.item_id == med).values(requires_qc=True))
    s.commit()
PF, PP = plans.PlanFields, plans.ParameterFields
plan = plans.create_plan(company_id, uid, PF("P1", "طرح دارو", "RECEIPT", item_id=med), [
    PP("خلوص", "NUMERIC", "درصد", D("98"), D("100"), D("99.5"), test_method="HPLC"),
    PP("ظاهر", "PASS_FAIL"), PP("یادداشت", "TEXT", is_mandatory=False)])
plans.activate_plan(company_id, uid, plan)
params = {p.name: p.parameter_id for p in plans.get_plan(company_id, plan).parameters}


def receipt(qty=10, it=None):
    d = inv_docs.create_stock_document(company_id, uid, "RECEIPT", today, inv_docs.DocumentHeaderFields(
        destination_warehouse_id=wh_rm, counterparty_detail_account_id=supplier))
    line = inv_docs.add_line(d, company_id, inv_docs.LineFields(item_id=it or med, uom_id=pcs, quantity=D(qty), quantity_base=D(qty),
                                                                unit_cost=D(1000)))
    inv_docs.confirm_stock_document(d, company_id)
    inv_docs.post_stock_document(d, company_id, uid)
    return line


good = qc.record_result(company_id, receipt(), uid, accepted=D(10), results=[
    RI(D("99.7"), params["خلوص"]), RI(True, params["ظاهر"]), RI("بدون ایراد", params["یادداشت"])])
# کالای دوم با عدد پذیرش ۱: یک نمونهٔ خارج از حد پذیرفته می‌شود ولی گواهی آنالیز نمی‌گیرد
med2 = item("MD-2", "داروی ب", "GOOD", is_sellable=True)
with new_session() as s:
    s.execute(update(Item).where(Item.item_id == med2).values(requires_qc=True))
    s.commit()
plan2 = plans.create_plan(company_id, uid, PF("P2", "طرح داروی ب", "RECEIPT", item_id=med2, acceptance_number=1), [
    PP("خلوص", "NUMERIC", "درصد", D("98"), D("100")), PP("ظاهر", "PASS_FAIL")])
plans.activate_plan(company_id, uid, plan2)
params2 = {p.name: p.parameter_id for p in plans.get_plan(company_id, plan2).parameters}
weak = qc.record_result(company_id, receipt(it=med2), uid, accepted=D(10),
                        results=[RI(D("97.1"), params2["خلوص"]), RI(True, params2["ظاهر"])])
med3 = item("MD-3", "داروی بدون طرح", "GOOD", is_sellable=True)
with new_session() as s:
    s.execute(update(Item).where(Item.item_id == med3).values(requires_qc=True))
    s.commit()
plain = qc.inspect(company_id, receipt(it=med3), uid, D(0)).inspection_id  # بازرسی ساده بدون نتیجهٔ پارامتر

check(raises(lambda: coa.issue(company_id, uid, good), "تأییدشده"), "a recorded but unapproved inspection gets no certificate")
qc.approve(company_id, good, uid)
qc.approve(company_id, weak, uid)
eligible = {e.inspection_id: e for e in coa.eligible_inspections(company_id)}
check(good in eligible and plain not in eligible and weak not in eligible and "MD-1" in eligible[good].item_label,
      f"only an approved inspection with conforming mandatory results is eligible ({list(eligible)})")
check(raises(lambda: coa.issue(company_id, uid, plain), "بدون نتیجه"), "no certificate without parameter results")
check(raises(lambda: coa.issue(company_id, uid, weak), "خارج از حد"), "an out-of-limit mandatory result blocks the certificate")

customer = dimensions_service.create_customer(company_id, "C1", "داروخانهٔ مرکزی")
other_customer = dimensions_service.create_customer(company_id, "C2", "مشتری دیگر")
channel = pricing.create_channel(company_id, "PS", "پخش سرد", "PRE_SALES")


def sales_order(it):
    d = docs.create_document(company_id, uid, "SALES_ORDER", today, docs.DocumentHeaderFields(
        counterparty_detail_account_id=customer, currency_id=company.base_currency_id, warehouse_id=wh_rm, channel_code=channel))
    docs.add_line(d, company_id, item_id=it, uom_id=pcs, quantity=D(2), quantity_base=D(2), unit_price=D(5000))
    return d


receive(byp, 10, 1000)
so, so_other = sales_order(med), sales_order(byp)
check(raises(lambda: coa.issue(company_id, uid, good, sales_document_id=so_other), "در سند فروش"), "the sales document must contain the item")
check(raises(lambda: coa.issue(company_id, uid, good, customer_id=other_customer, sales_document_id=so), "یکی نیست"),
      "the customer must match the sales document")
c1 = coa.issue(company_id, uid, good, sales_document_id=so, notes="برای مناقصه")
c2 = coa.issue(company_id, uid, good)
first, second = coa.get_certificate(company_id, c1), coa.get_certificate(company_id, c2)
check(first.certificate_no == 1 and second.certificate_no == 2 and first.customer == "داروخانهٔ مرکزی"
      and first.sales_document_id == so, "numbered in sequence; the customer comes from the sales document")
res = {r["name"]: r for r in first.snapshot["results"]}
check(res["خلوص"]["value"] == "99.7" and res["خلوص"]["min"] == "98" and res["خلوص"]["conforming"] is True and len(res) == 3,
      f"results are captured with limits ({res['خلوص']})")
title, headers, rows, head = coa.print_table(first)
check("۱" in title and rows[0][0] == "خلوص" and rows[0][6] == "منطبق" and ("مشتری", "داروخانهٔ مرکزی") in head, "print table")
check(raises(lambda: coa.revoke(company_id, uid, c2, " "), "دلیل"), "revoking needs a reason")
coa.revoke(company_id, uid, c2, "صادرشده به اشتباه")
check(coa.get_certificate(company_id, c2).status_code == "REVOKED"
      and raises(lambda: coa.revoke(company_id, uid, c2, "دوباره"), "قبلاً") and len(coa.list_certificates(company_id)) == 2,
      "a revoked certificate stays on record and cannot be revoked twice")
check(any("لغوشده" in v for _k, v in coa.print_table(coa.get_certificate(company_id, c2))[3]), "the printout shows the revocation")

# فرم
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui import report_export
from peecha.ui.screens.qc_certificates import QcCertificatesScreen

printed = []
report_export.print_report = lambda parent, title, headers, rows, **kw: printed.append((title, kw.get("filters")))
screen = QcCertificatesScreen()
screen.refresh()
check(screen.eligible_table.rowCount() == 1 and screen.cert_table.rowCount() == 2, "the form lists eligible inspections and certificates")
screen.eligible_table.setCurrentCell(0, 0)
screen.document_combo.setCurrentIndex(screen.document_combo.findData(so))
cert = screen.issue()
check(cert is not None and screen.cert_table.rowCount() == 3, f"a certificate is issued from the form ({screen.status_label.text()})")
screen.cert_table.setCurrentCell(0, 0)
check(screen.print_certificate() and "۳" in printed[0][0], "print from the form")
screen.ask_reason = lambda: "آزمون"
check(screen.revoke() and coa.get_certificate(company_id, cert).status_code == "REVOKED", "revoke from the form")
check(all(len(b.text()) <= 2 for b in screen.findChildren(QPushButton) if b.text()), "icon buttons only")

finish()
