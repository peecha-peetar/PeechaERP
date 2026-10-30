"""R361: بسته‌بندی و کنترل ارسال: اسکن کد و بارکد کارتن (به‌اندازهٔ ضریب)، کالای خارج از سند و بیش از مقدار پذیرفته نمی‌شود،
ردیف جمع‌آوری‌شده فقط به مقدار جمع‌آوری، چند بسته با وزن و ابعاد، ارسال ناقص فقط با تایید، ثبت حمل و وضعیت سند؛ و فرم."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r361"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.commercial import Shipment
from peecha.services import commercial_documents as docs, commercial_pricing as pricing, unit_conversion as uc, wms_packing as wp
from peecha.services import warehouse_operations as ops

customer = dimensions_service.create_customer(company_id, "C1", "فروشگاه مرکزی")
channel = pricing.create_channel(company_id, "PS", "پخش سرد", "PRE_SALES")
ctn = catalog_service.create_uom(company_id, "CTN", "کارتن", "COUNT", decimal_places=0)
uc.set_item_unit(byp, ctn, D(6))
uc.add_barcode(company_id, byp, ctn, "CTNBY1")
other = item("OT-1", "کالای دیگر", "GOOD")
for it in (byp, pk, other):
    receive(it, 100, 1000)


def order(lines):
    d = docs.create_document(company_id, uid, "SALES_ORDER", today, docs.DocumentHeaderFields(
        counterparty_detail_account_id=customer, currency_id=company.base_currency_id, warehouse_id=wh_rm, channel_code=channel))
    for it, qty in lines:
        docs.add_line(d, company_id, item_id=it, uom_id=pcs, quantity=D(qty), quantity_base=D(qty), unit_price=D(5000))
    docs.confirm_document(d, company_id, uid)
    return d


so = order([(byp, 10), (pk, 4)])
check(raises(lambda: wp.pack(company_id, order([(byp, 1)]) + 10_000, uid, "BY-1"), "نامعتبر"), "an unknown document is refused")
rows = {d.document_id: d for d in wp.packable_documents(company_id)}
check(rows[so].state == "WAITING" and rows[so].packages == 0, "the confirmed order waits for packing")

r = wp.pack(company_id, so, uid, "CTNBY1")
check(r.quantity == 6 and r.remaining == 4 and r.package_no == 1, "a carton barcode packs six pieces into package 1")
wp.pack(company_id, so, uid, "by-1", quantity=D(4))
check(raises(lambda: wp.pack(company_id, so, uid, "BY-1"), "کامل"), "packing more than ordered is refused")
check(raises(lambda: wp.pack(company_id, so, uid, "OT-1"), "در این سند نیست"), "an item outside the order is refused")
check(raises(lambda: wp.pack(company_id, so, uid, "NO-SUCH"), "پیدا نشد"), "an unknown code is reported")
check(raises(lambda: wp.ship(company_id, so, uid, "COURIER"), "باز"), "shipping waits for the open package to be closed")
first_package = r.package_id
wp.close_package(company_id, first_package, D("12.5"), (D(40), D(30), D(30)))
p2 = wp.new_package(company_id, so, uid)
check(p2 != first_package and wp.new_package(company_id, so, uid) == p2, "a new empty package is reused, not duplicated")
wp.pack(company_id, so, uid, item_id=pk, quantity=D(3))
status = {ln.item_id: ln for ln in wp.pack_status(company_id, so)}
check(status[byp].remaining == 0 and status[pk].packed == 3 and status[pk].remaining == 1, "line status: packed and remaining")
line_in_p2 = wp.list_packages(company_id, so)[1].lines[0].package_line_id
check(raises(lambda: wp.remove_line(company_id, wp.list_packages(company_id, so)[0].lines[0].package_line_id), "باز"),
      "a closed package keeps its contents")
wp.remove_line(company_id, line_in_p2)
wp.pack(company_id, so, uid, "PK-1", quantity=D(3))
wp.close_package(company_id, p2, D(4))
check(raises(lambda: wp.ship(company_id, so, uid, "COURIER"), "کامل"), "an incomplete order is not shipped without confirmation")
shipment = wp.ship(company_id, so, uid, "POST", "پست پیشتاز", "TRK-1", D(150_000), allow_partial=True)
with new_session() as s:
    sh = s.get(Shipment, shipment)
check(sh.document_id == so and sh.status_code == "SHIPPED" and sh.tracking_no == "TRK-1" and sh.shipping_method_code == "POST"
      and all(p.status_code == "SHIPPED" and p.shipment_id == shipment for p in wp.list_packages(company_id, so)),
      "the shipment is recorded and both packages are shipped")
check(raises(lambda: wp.close_package(company_id, first_package, D(1)), "ارسال‌شده"), "a shipped package cannot change")
wp.pack(company_id, so, uid, "PK-1")
wp.close_package(company_id, wp.list_packages(company_id, so)[-1].package_id)
wp.ship(company_id, so, uid, "COURIER")
check(so not in {d.document_id for d in wp.packable_documents(company_id)}
      and next(d for d in wp.packable_documents(company_id, include_shipped=True) if d.document_id == so).state == "SHIPPED",
      "a fully shipped order leaves the packing list")
headers, rows = wp.packing_list(company_id, so)
check(len(rows) == 4 and rows[0][0] == 1 and rows[0][3] == D("12.5"), f"packing list rows ({rows})")

# ردیفی که کار جمع‌آوری دارد فقط به اندازهٔ جمع‌آوری بسته‌بندی می‌شود
so2 = order([(other, 5)])
tasks = ops.generate_tasks(company_id, "PICK", ("COMMERCIAL", so2), uid)
check(len(tasks) == 1, f"a pick task is created for the order ({tasks})")
check(raises(lambda: wp.pack(company_id, so2, uid, "OT-1"), "جمع‌آوری"), "nothing is packable before picking")
ops.start_task(tasks[0], company_id, uid)
ops.complete_pick(tasks[0], company_id, uid, D(2))
check(wp.pack(company_id, so2, uid, "OT-1", quantity=D(2)).remaining == 0
      and raises(lambda: wp.pack(company_id, so2, uid, "OT-1"), "جمع‌آوری"), "only the picked two pieces are packable")

# فرم
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui import report_export
from peecha.ui.screens.wms_packing import WmsPackingScreen

printed = []
report_export.print_report = lambda parent, title, headers, rows, **kw: printed.append((title, rows))
so3 = order([(byp, 2)])
screen = WmsPackingScreen()
screen.refresh()
index = next(i for i, d in enumerate(screen.documents) if d.document_id == so3)
screen.doc_table.selectRow(index)
screen.scan_field.setText("BY-1")
screen.qty_field.setValue(2)
check(screen.scan() and screen.line_table.item(0, 4).text() == "۰" and screen.content_table.rowCount() == 1,
      f"scanning from the form packs the item ({screen.status_label.text()})")
screen.weight_field.setValue(3)
check(screen.close_package() and screen.print_list() and printed and "فهرست بسته‌بندی" in printed[0][0], "close and print")
check(screen.ship() is not None and so3 not in {d.document_id for d in screen.documents}, "ship from the form")
check(all(len(b.text()) <= 2 for b in screen.findChildren(QPushButton) if b.text()), "icon buttons only")

finish()
