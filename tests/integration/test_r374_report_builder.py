"""R374: گزارش‌ساز آزاد: دسترسی به هر داده با مجوز مشاهدهٔ فرم‌هایش، فیلتر متن و عدد و تاریخ (بازه در پایگاه داده)، برگشت با
علامت منفی، پیش‌نویس حساب نمی‌شود، گروه‌بندی با جمع و میانگین و تعداد و ماه شمسی، مرتب‌سازی و سقف، جمع ستونی فقط برای
ستون‌های جمع‌پذیر، ذخیره و اشتراک و ویرایش فقط با سازنده؛ و فرم."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r374"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

import jdatetime
from PySide6.QtCore import Qt
from sqlalchemy import update
from peecha import numerals
from peecha.db.models.commercial import CommercialDocument
from peecha.services import commercial_documents as documents_service, roles as roles_service, users as users_service
from peecha.services.production import common as pc, master as pm, orders as po
from peecha.services.report_builder import engine
from peecha.services.report_builder.engine import Definition, Filter

pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg)
customer = dimensions_service.create_customer(company_id, "C1", "مشتری الف")
customer2 = dimensions_service.create_customer(company_id, "C2", "مشتری ب")
wh_sales = locations_service.create_warehouse(company_id, "SALE", "انبار فروش", WF(allow_negative_stock=True))
receive(r1, 100, 1000)
receive(pk, 40, 500)
last_month = today.replace(day=1) - datetime.timedelta(days=1)


def doc(kind, party, day, lines, status="CONFIRMED"):
    d = documents_service.create_document(company_id, uid, kind, day, documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=party, currency_id=company.base_currency_id, warehouse_id=wh_sales))
    for item_id, qty, price in lines:
        documents_service.add_line(d, company_id, item_id=item_id, uom_id=base_uom(item_id), quantity=D(qty), quantity_base=D(qty),
                                   unit_price=D(price))
    with new_session() as s:
        s.execute(update(CommercialDocument).where(CommercialDocument.document_id == d).values(status_code=status))
        s.commit()
    return d


doc("SALES_INVOICE", customer, today, [(fg, 2, 1000), (pk, 10, 50)])
doc("SALES_INVOICE", customer2, last_month, [(fg, 5, 1000)])
doc("SALES_RETURN", customer, today, [(fg, 1, 1000)])
doc("SALES_INVOICE", customer2, today, [(fg, 100, 1000)], status="DRAFT")
bom = pm.create_bom_version(company_id, fg, pm.BomFields(batch_size_qty=D(1)))
pm.add_bom_component(company_id, bom, pm.BomLineFields(r1, D(1)))
po.create_order(company_id, uid, po.OrderFields(item_id=fg, planned_qty=D(10), start_date=today, due_date=today))

staff = users_service.create_user("staff", "کارشناس", "secret123", None, company.default_language_id, False, [company_id], company_id).user_id
check(engine.available(company_id, staff) == [], "no form, no data")
forms = {f.code: f.form_id for f in roles_service.list_forms()}
role = roles_service.create_role(company_id, "برنامه‌ریز", None)
roles_service.set_role_permission(role.role_id, forms["prd_orders"], "VIEW", True)
roles_service.set_user_role(staff, role.role_id, company_id, True)
check([d.code for d in engine.available(company_id, staff)] == ["production_orders"], "data follows the view permission of its forms")
sales = Definition("sales_lines", ["party", "item_name", "quantity", "net_amount"])
check(raises(lambda: engine.run(company_id, staff, sales), "دسترسی"), "no sales data without sales forms")
check(raises(lambda: engine.run(company_id, uid, Definition("sales_lines", [])), "ستون"), "columns are required")
check(raises(lambda: engine.run(company_id, uid, Definition("sales_lines", ["nope"])), "ستون"), "unknown columns are refused")
check(raises(lambda: engine.run(company_id, uid, Definition("sales_lines", ["party"], [Filter("party", "GT", "x")])), "فیلتر"),
      "operators follow the column type")

r = engine.run(company_id, uid, sales)
check(len(r.rows) == 4 and sorted(x[2] for x in r.rows) == [D(-1), D(2), D(5), D(10)], f"returns are negative and drafts are left out ({[x[2] for x in r.rows]})")
check(r.totals == [None, None, D(16), D(6500)], f"totals for additive columns ({r.totals})")
r = engine.run(company_id, uid, Definition("sales_lines", ["party", "quantity"], [Filter("party", "CONTAINS", "الف"),
                                                                                    Filter("quantity", "GT", "۱")]))
check([x[1] for x in r.rows] == [D(2), D(10)], "text and Persian-digit number filters")
r = engine.run(company_id, uid, Definition("sales_lines", ["date", "quantity"], [Filter("date", "FROM", today.replace(day=1))]))
check(len(r.rows) == 3 and r.filters_text[0][0] == "تاریخ", "date range")

grouped = Definition("sales_lines", ["party", "net_amount", "unit_price"], group=True, aggregates={"unit_price": "AVG"}, count_rows=True,
                     sort_key="net_amount", sort_desc=True)
r = engine.run(company_id, uid, grouped)
check(r.headers == ["مشتری", "جمع مبلغ پس از تخفیف", "میانگین بهای واحد", "تعداد ردیف"], f"grouped headers ({r.headers})")
check([x[0].endswith("مشتری ب") for x in r.rows] == [True, False] and r.rows[0][1:] == [D(5000), D(1000), 1]
      and r.rows[1][1:] == [D(1500), D("683.33"), 3], f"group sums, averages and counts sorted ({r.rows})")
check(r.totals == [None, D(6500), None, 4], "averages are not totalled")
j = jdatetime.date.fromgregorian(date=last_month)
r = engine.run(company_id, uid, Definition("sales_lines", ["date", "quantity"], group=True, date_group="MONTH", sort_key="date"))
check(r.rows[0][0] == numerals.to_persian_digits(f"{j.year}/{j.month:02d}") and r.rows[0][1] == D(5), f"Jalali months ({r.rows})")
check(len(engine.run(company_id, uid, Definition("sales_lines", ["item_name"], limit=2)).rows) == 2, "row limit")
r = engine.run(company_id, uid, Definition("stock", ["item_code", "on_hand", "value", "avg_cost"]))
check(sorted((x[1], x[2]) for x in r.rows) == [(D(40), D(20000)), (D(100), D(100000))] and r.totals[3] is None, "stock data")
r = engine.run(company_id, staff, Definition("production_orders", ["order_code", "planned_qty", "remaining_qty"]))
check(r.rows[0][1:] == [D(10), D(10)], "production data for the planner")
check(len(engine.run(company_id, uid, Definition("journal_lines", ["account_code", "debit", "credit"])).rows) >= 2, "journal lines")

rid = engine.save_report(company_id, uid, "فروش مشتریان", grouped, is_shared=False)
check(raises(lambda: engine.save_report(company_id, uid, "فروش مشتریان", grouped), "دارید"), "unique per owner")
check(engine.get_report(company_id, uid, rid).definition == grouped, "the definition round-trips")
dated = Definition("sales_lines", ["date", "quantity"], [Filter("date", "BETWEEN", last_month, today), Filter("quantity", "GE", D(2))])
rid2 = engine.save_report(company_id, uid, "بازهٔ تاریخ", dated, is_shared=True)
check(engine.get_report(company_id, uid, rid2).definition == dated, "dates and numbers in filters round-trip")
check(engine.list_reports(company_id, staff) == [], "shared sales reports are hidden from users without sales access")
prod = engine.save_report(company_id, uid, "دستورها", Definition("production_orders", ["order_code"]), is_shared=True)
check([x.report_id for x in engine.list_reports(company_id, staff)] == [prod], "shared reports for users with access")
check(raises(lambda: engine.delete_report(company_id, staff, prod), "سازنده"), "only the owner edits or deletes")

# فرم
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui import report_export
from peecha.ui.screens.fixed_assets import set_combo
from peecha.ui.screens.report_builder import ReportBuilderScreen

printed, exported = [], []
report_export.print_report = lambda parent, title, headers, rows, footer=None, **kw: printed.append((title, len(rows), footer))
report_export.export_report_excel = lambda parent, title, headers, rows, footer=None, **kw: exported.append(rows)
screen = ReportBuilderScreen()
screen.refresh()
check(screen.dataset_combo.count() == 5 and screen.saved_table.rowCount() == 3, "datasets and saved reports")
set_combo(screen.dataset_combo, "sales_lines")
for i in range(screen.column_list.count()):
    item = screen.column_list.item(i)
    item.setCheckState(Qt.Checked if item.data(Qt.UserRole) in ("party", "net_amount") else Qt.Unchecked)
set_combo(screen.filter_column, "party")
set_combo(screen.filter_op, "CONTAINS")
screen.value_text.setText("مشتری")
check(screen.add_filter() and screen.filter_table.rowCount() == 1, "filter added")
screen.group_box.setChecked(True)
check(screen.run() and screen.result_table.rowCount() == 3 and screen.result_table.item(2, 0).text() == "جمع", f"run with totals ({screen.status_label.text()})")
check(screen.export_excel() and exported[-1][0][1] in (D(5000), D(1500)), "excel export")
check(screen.print_result() and printed[-1][2][0] == "جمع", "print with totals")
screen.name_field.setText("از فرم")
check(screen.save_report() and screen.saved_table.rowCount() == 4, "saved from the form")
screen.new_report()
row = next(i for i, r in enumerate(screen.reports) if r.report_id == rid2)
screen.saved_table.setCurrentCell(row, 0)
check(screen.selected_columns() == ["date", "quantity"] and len(screen.filters) == 2 and screen.run()
      and screen.result_table.rowCount() == 4, "open a saved report and run it (three rows and the total)")
check(all(len(b.text()) <= 2 for b in screen.findChildren(QPushButton) if b.text()), "icon buttons only")

finish()
