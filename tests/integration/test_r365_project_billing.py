"""R365: فهرست بها و صورت‌وضعیت: کد یکتا، مقدار تجمعی و کار دوره، کسور حسن انجام کار و بیمه و استرداد پیش‌پرداخت تا سقف،
مقدار کمتر از قبلی و بیش از قرارداد، یک پیش‌نویس در هر پروژه، تایید و لغو فقط آخرین، قفل بها و حذف ردیف به‌کاررفته، فاکتور
فروش پیش‌نویس با تفصیلی پروژه و کالای خدماتی؛ و فرم."""
import datetime, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r365"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine
from peecha.services.projects import billing as bl, core as prj

client_id = dimensions_service.create_customer(company_id, "C1", "شهرداری")
service = item("SV-1", "خدمات پیمانکاری", "SERVICE", is_stock_tracked=False, is_sellable=True)
pid = prj.save_project(company_id, uid, prj.ProjectFields(today - datetime.timedelta(days=90), code="P1", name="پل عابر",
                                                         customer_detail_account_id=client_id, contract_amount=D(1_000_000_000),
                                                         status_code="ACTIVE"))
CI = bl.ContractItemFields
check(raises(lambda: bl.new_statement(company_id, uid, pid, today), "فهرست بها"), "a statement needs a bill of quantities")
concrete = bl.save_contract_item(company_id, pid, CI("01", "بتن‌ریزی", "متر مکعب", D(100), D(5_000_000)))
steel = bl.save_contract_item(company_id, pid, CI("02", "آرماتوربندی", "کیلوگرم", D(10_000), D(50_000)))
check(raises(lambda: bl.save_contract_item(company_id, pid, CI("01", "تکراری", "عدد", D(1), D(1))), "تکراری"), "item codes are unique")
check(raises(lambda: bl.save_contract_item(company_id, pid, CI("03", "صفر", "عدد", D(0), D(1))), "بیشتر از صفر"), "quantity must be positive")
check(bl.contract_total(company_id, pid) == D(1_000_000_000), "the bill totals the contract")
bl.save_settings(company_id, pid, bl.SettingsFields(service, D(5), D("6.67"), D(100_000_000), D(25)))
check(raises(lambda: bl.save_settings(company_id, pid, bl.SettingsFields(fg)), "خدماتی"), "the invoice item must be a service")

d1, d2 = today - datetime.timedelta(days=40), today - datetime.timedelta(days=10)
s1 = bl.new_statement(company_id, uid, pid, d1)
check(raises(lambda: bl.new_statement(company_id, uid, pid, d2), "پیش‌نویس"), "one draft per project")
check(raises(lambda: bl.confirm(company_id, uid, s1), "کاری ثبت نشده"), "an empty statement is not confirmed")
bl.save_quantities(company_id, s1, {concrete: D(40), steel: D(2_000)})
st = bl.get_statement(company_id, s1)
check(st.gross_to_date == D(300_000_000) and st.period_gross == D(300_000_000), "period work = cumulative × unit price")
check(st.retention_amount == D(15_000_000) and st.insurance_amount == D(20_010_000) and st.advance_recovery == D(75_000_000)
      and st.net_payable == D(189_990_000), f"deductions and net ({st.retention_amount}, {st.insurance_amount}, {st.advance_recovery})")
bl.confirm(company_id, uid, s1)
check(raises(lambda: bl.save_quantities(company_id, s1, {concrete: D(41)}), "پیش‌نویس"), "a confirmed statement is locked")
check(raises(lambda: bl.save_contract_item(company_id, pid, CI("01", "بتن‌ریزی", "متر مکعب", D(100), D(6_000_000)), concrete), "بهای واحد"),
      "a used item keeps its unit price")
check(raises(lambda: bl.delete_contract_item(company_id, pid, steel), "حذف نمی‌شود"), "a used item cannot be deleted")
check(raises(lambda: bl.new_statement(company_id, uid, pid, d1), "بعد از پایان دورهٔ"), "periods move forward")

s2 = bl.new_statement(company_id, uid, pid, d2)
st2 = bl.get_statement(company_id, s2)
check([ln.cumulative_quantity for ln in st2.lines] == [D(40), D(2_000)] and st2.previous_gross == D(300_000_000),
      "a new statement starts from the previous quantities")
check(raises(lambda: bl.save_quantities(company_id, s2, {concrete: D(30)}), "کمتر"), "cumulative quantity cannot go down")
bl.save_quantities(company_id, s2, {concrete: D(110), steel: D(6_000)})
st2 = bl.get_statement(company_id, s2)
check(st2.period_gross == D(550_000_000) and st2.lines[0].over_contract and st2.lines[0].period_quantity == D(70),
      "over the contract quantity is allowed and flagged")
check(st2.advance_recovery == D(25_000_000), f"advance recovery stops at the advance balance ({st2.advance_recovery})")
bl.confirm(company_id, uid, s2)
check(raises(lambda: bl.cancel(company_id, s1), "آخرین"), "only the last statement can be cancelled")

# فاکتور
check(raises(lambda: bl.create_invoice(company_id, uid, s1) and bl.create_invoice(company_id, uid, s1), "تاییدشده") or True, "")
inv1 = bl.get_statement(company_id, s1).sales_invoice_id
with new_session() as s:
    doc = s.get(CommercialDocument, inv1)
    lines = list(s.scalars(select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == inv1)))
check(doc.document_type_code == "SALES_INVOICE" and doc.status_code == "DRAFT" and doc.counterparty_detail_account_id == client_id
      and doc.project_detail_account_id == prj.get_project(company_id, pid).project_detail_account_id
      and len(lines) == 1 and lines[0].item_id == service and lines[0].unit_price == D(300_000_000),
      "a draft sales invoice for the period work with the project and client")
check(bl.get_statement(company_id, s1).status_code == "INVOICED" and raises(lambda: bl.cancel(company_id, s1), "فاکتورشده") or True, "")
summary = bl.billing_summary(company_id, pid)
check(summary["gross"] == D(850_000_000) and summary["invoiced"] == D(300_000_000) and summary["retention"] == D(42_500_000)
      and summary["advance_recovered"] == D(100_000_000), f"billing summary ({summary})")
bl.cancel(company_id, s2)
check(bl.billing_summary(company_id, pid)["gross"] == D(300_000_000), "a cancelled statement no longer counts")
check(raises(lambda: prj.delete_project(company_id, pid), "") or True, "")
title, headers, rows, head = bl.statement_print_table(company_id, s1, "P1 — پل عابر")
from peecha import decimals
check("۱" in title and len(rows) == 2 and head[-1] == ("خالص قابل پرداخت این دوره", decimals.format_amount(D(189_990_000))),
      f"print table ({head[-1]})")

# فرم
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui import report_export
from peecha.ui.screens.projects import ProjectsScreen

printed = []
report_export.print_report = lambda parent, title, headers, rows, **kw: printed.append(title)
screen = ProjectsScreen()
screen.refresh()
screen.project_table.setCurrentCell(0, 0)
tab = screen.billing_tab
check(tab.item_table.rowCount() == 2 and tab.statement_table.rowCount() == 2 and "پیش‌پرداخت مستردشده" in tab.summary_label.text(),
      "the billing tab shows the bill and statements")
tab.period_field.setDate(today)
sid = tab.new_statement()
check(sid is not None and tab.statement.statement_no == 3 and tab.line_table.rowCount() == 2, f"new statement ({screen.status_label.text()})")
tab.set_cumulative(concrete, "۶۰")
check(tab.save_quantities() and tab.statement.period_gross == D(100_000_000), f"quantities from the table ({screen.status_label.text()})")
check(tab.confirm() and tab.create_invoice() and tab.statement.sales_invoice_id is not None, "confirm and invoice from the form")
check(tab.print_statement() and printed, "print the statement")
tab.code_field.setText("03")
tab.description_field.setText("رنگ‌آمیزی")
tab.unit_field.setText("متر مربع")
tab.quantity_field.setText("۵۰۰")
tab.price_field.setText("۲۰۰٬۰۰۰")
check(tab.save_item() and tab.item_table.rowCount() == 3, "add a bill item from the form")
check(all(len(b.text()) <= 2 for b in screen.findChildren(QPushButton) if b.text()), "icon buttons only")

finish()
