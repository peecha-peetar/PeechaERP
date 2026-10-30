"""R373: تعهد تحویل و سناریو: موجودی آزاد با رزرو سفارش (بدون شمارش دوباره)، تقاضای سفارش فروش و مواد دستور تولید، تامین
سفارش خرید و دستور تولید در تاریخ خودشان، قابل تعهد با نگاه به تعهدهای بعدی، برآورد با تولید از مواد و زمان تولید، سناریوی
تقاضا و تامین فرضی و اثرش روی مواد؛ و فرم."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r373"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.services import commercial_documents as documents_service, stock_controls as sc
from peecha.services.production import atp, common as pc, master as pm, orders as po, planning as pp

pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg)
bom = pm.create_bom_version(company_id, fg, pm.BomFields(batch_size_qty=D(1)))
pm.add_bom_component(company_id, bom, pm.BomLineFields(r1, D(2)))
pm.add_bom_component(company_id, bom, pm.BomLineFields(pk, D(1)))
pm.save_item_profile(company_id, fg, uid, lead_time_days=2)
wh_sales = locations_service.create_warehouse(company_id, "SALE", "انبار فروش", WF(allow_negative_stock=True))
receive(fg, 10, 300000, wh=wh_sales)
receive(r1, 100, 1000)
receive(pk, 60, 500)
DAY = lambda n: today + datetime.timedelta(days=n)  # noqa: E731
customer = dimensions_service.create_customer(company_id, "C1", "مشتری")


def sales_order(qty, day):
    doc = documents_service.create_document(company_id, uid, "SALES_ORDER", today, documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=customer, currency_id=company.base_currency_id, warehouse_id=wh_sales))
    documents_service.add_line(doc, company_id, item_id=fg, uom_id=pcs, quantity=D(qty), quantity_base=D(qty), unit_price=D(500000),
                               expected_delivery_date=day)
    documents_service.confirm_document(doc, company_id, uid)
    return doc


sales_order(30, DAY(3))
engine_service.set_feature_enabled(company_id, sc.SALES_ORDER_RESERVATION, True)
sales_order(5, DAY(10))   # با تایید از موجودی رزرو می‌شود
pord = documents_service.create_document(company_id, uid, "PURCHASE_ORDER", today, documents_service.DocumentHeaderFields(
    counterparty_detail_account_id=supplier, currency_id=company.base_currency_id, warehouse_id=wh_rm))
documents_service.add_line(pord, company_id, item_id=pk, uom_id=pcs, quantity=D(20), quantity_base=D(20), unit_price=D(500),
                           expected_delivery_date=DAY(5))
documents_service.confirm_document(pord, company_id, uid)
order = po.create_order(company_id, uid, po.OrderFields(item_id=fg, planned_qty=D(40), start_date=DAY(2), due_date=DAY(7)))
po.plan_order(company_id, uid, order)

check(pp.open_purchase_supply(company_id).get(pk) == D(20) and [r.date for r in pp.open_purchase_receipts(company_id)] == [DAY(5)],
      "purchase supply keeps its total and now has a date")
tl = atp.timeline(company_id, fg)
check(tl.free_now == D(5) and sorted((e.date, e.kind, e.quantity) for e in tl.events) == [(DAY(3), "DEMAND", D(30)), (DAY(7), "SUPPLY", D(40))],
      f"the reserved order is not counted twice ({tl.free_now}, {[(e.source, e.quantity) for e in tl.events]})")
check(tl.day(DAY(3)).balance == D(-25) and tl.day(DAY(7)).balance == D(15) and tl.shortage_date == DAY(3), "projected balance")
check(tl.atp_on(today) == 0 and tl.atp_on(DAY(6)) == 0 and tl.atp_on(DAY(7)) == D(15), "available to promise looks ahead")

p = atp.promise(company_id, fg, D(10), today)
check(p.atp_date == DAY(7) and p.ctp_date == DAY(2) and p.best_date == DAY(2) and p.lead_days == 2, f"ATP and with production ({p.atp_date}, {p.ctp_date})")
check([(ch.item_id, ch.required, ch.available) for ch in p.components] == [(r1, D(20), D(20)), (pk, D(10), D(20))],
      f"materials at the production start ({[(ch.item_label, ch.required, ch.available) for ch in p.components]})")
p = atp.promise(company_id, fg, D(15), DAY(8))
check(p.atp_date == DAY(8) and p.ctp_date is None and not p.components, "available on the requested day: no production estimate")
p = atp.promise(company_id, fg, D(16), today)
check(p.atp_date is None and p.ctp_date == DAY(7), "more than ever available: production covers the rest when materials allow")
p = atp.promise(company_id, pk, D(30), today)
check(p.atp_date == DAY(5) and not p.made and p.ctp_date is None, "a bought item waits for its purchase order")
check(raises(lambda: atp.promise(company_id, fg, D(0)), "بزرگ‌تر") and raises(lambda: atp.timeline(company_id, fg, horizon_days=0), "افق"),
      "quantity and horizon checked")

S = atp.ScenarioLineFields
check(raises(lambda: atp.save_scenario(company_id, uid, "خالی", "", []), "دست‌کم"), "a scenario needs lines")
check(raises(lambda: atp.save_scenario(company_id, uid, "", "", [S(fg, "DEMAND", DAY(4), D(10))]), "نام"), "a scenario needs a name")
sid = atp.save_scenario(company_id, uid, "رشد فروش", "سفارش بزرگ احتمالی", [S(fg, "DEMAND", DAY(4), D(10), "مشتری جدید"),
                                                                          S(pk, "SUPPLY", DAY(1), D(30))])
check(raises(lambda: atp.save_scenario(company_id, uid, "رشد فروش", "", [S(fg, "DEMAND", DAY(4), D(1))]), "هست"), "unique names")
r = atp.evaluate(company_id, sid)
pr = r.promises[0]
check((pr.promise_date, pr.delay_days, pr.short_at_wanted) == (DAY(7), 3, D(10)), f"the scenario demand gets a date ({pr.promise_date})")
out = {o.item_id: o for o in r.outcomes}
check(r.outcomes[0].item_id == fg and out[fg].base.min_balance == D(-25) and out[fg].scenario.min_balance == D(-35)
      and out[fg].extra_shortage == D(10), "the product shortage grows")
check(out[r1].scenario.day(DAY(2)).balance == D(0) and out[r1].extra_shortage == 0, "the shortfall is turned into materials at the production start")
check(out[pk].scenario.day(DAY(1)).supply == D(30) and out[pk].scenario.min_balance == D(40), "supply lines raise the balance")
with new_session() as s:
    from peecha.db.models.production import ProductionOrder
    check(s.scalar(select(func.count()).select_from(ProductionOrder)) == 1, "nothing is created")

# فرم
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha import numerals
from peecha.ui import report_export
from peecha.ui.screens.fixed_assets import set_combo
from peecha.ui.screens.production_atp import ProductionAtpScreen

printed = []
report_export.print_report = lambda parent, title, headers, rows, **kw: printed.append((title, len(rows)))
screen = ProductionAtpScreen()
screen.refresh()
set_combo(screen.item_combo, fg)
screen.qty_field.setText("۱۰")
screen.wanted_field.setDate(today)
check(screen.check() and numerals.format_jalali_date(DAY(7)) in screen.answer_label.text() and "با تولید" in screen.answer_label.text(),
      f"promise answer ({screen.answer_label.text()})")
check(screen.day_table.rowCount() == 3 and screen.event_table.rowCount() == 2 and screen.component_table.rowCount() == 2, "tables filled")
check(screen.print_timeline() and printed[-1] == ("تعهد تحویل و موجودی پیش‌بینی", 3), "print")
check(screen.scenario_table.rowCount() == 1, "scenarios listed")
screen.new_scenario()
screen.name_field.setText("تامین زودتر")
set_combo(screen.line_item_combo, fg)
set_combo(screen.kind_combo, "SUPPLY")
screen.line_qty_field.setText("۲۰")
check(screen.add_line() and screen.save_scenario() and screen.scenario_table.rowCount() == 2, f"scenario saved ({screen.status_label.text()})")
check(screen.run_scenario() and screen.outcome_table.rowCount() == 1 and screen.promise_table.rowCount() == 0
      and screen.print_outcome(), "scenario run and print")
check(screen.delete_scenario() and screen.scenario_table.rowCount() == 1, "scenario deleted")
check(all(len(b.text()) <= 2 for b in screen.findChildren(QPushButton) if b.text()), "icon buttons only")

finish()
