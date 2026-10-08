import os, sys, datetime, decimal, io
os.environ["PEECHA_DB_NAME"] = "peecha_test_r255_1"
os.environ["PEECHA_DB_USER"] = "peecha"
os.environ["PEECHA_DB_PASSWORD"] = "peecha"
os.environ["PEECHA_DB_HOST"] = "localhost"
os.environ["PEECHA_DB_PORT"] = "5432"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

FAIL = False
def check(cond, msg):
    global FAIL
    if not cond:
        FAIL = True
        print("FAIL:", msg)
    else:
        print("OK:", msg)

from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

from peecha.db.schema_bootstrap import apply_pending_schema_files
from peecha.db.base import get_engine, new_session
apply_pending_schema_files(get_engine())
from peecha.services.bootstrap import bootstrap_system
from peecha import session as sess
user = bootstrap_system("admin", "مدیر سیستم", "secret123", "شرکت آزمایشی")
sess.current_user = user
from sqlalchemy import select, text
from peecha.db.models.security import UserCompany
from peecha.db.models.core import Company
with new_session() as s:
    uc = s.scalar(select(UserCompany).where(UserCompany.user_id == user.user_id))
    company = s.get(Company, uc.company_id)
company_id = company.company_id
sess.current_company = company

from peecha.services import fiscal_years as fiscal_years_service
fiscal_years_service.create_fiscal_year_for_date(company_id, 1, 1, datetime.date.today())
from peecha.services import chart_of_accounts as coa_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import commercial_settings as csettings_service
from peecha.services import commercial_partners as partners_service
from peecha.services import inventory_engine as engine_service
from peecha.services import inventory_documents as inv_documents_service
from peecha.services import commercial_documents as documents_service
from peecha.services import detail_dimensions as dimensions_service

lang_id = company.default_language_id
A = lambda code, name, nature, typ, perm, post, parent=None: coa_service.create_account(company_id, code, name, nature, typ, perm, post, lang_id, parent_account_id=parent)
g1 = A("1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False)
k1 = A("11", "موجودی نقد", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
cash_gl = A("101", "صندوق", "DEBIT", "ASSET", "PERMANENT", True, k1.account_id)
k2 = A("13", "دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
ar_gl = A("1304", "دریافتنی مشتریان", "DEBIT", "ASSET", "PERMANENT", True, k2.account_id)
k3 = A("12", "موجودی انبار", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
inv_gl = A("121", "موجودی کالا", "DEBIT", "ASSET", "PERMANENT", True, k3.account_id)
g2 = A("4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False)
k4 = A("41", "درآمد عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, g2.account_id)
rev_gl = A("411", "فروش", "CREDIT", "REVENUE", "TEMPORARY", True, k4.account_id)
discount_gl = A("412", "تخفیف فروش", "DEBIT", "REVENUE", "TEMPORARY", True, k4.account_id)
g4 = A("2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False)
k7 = A("21", "بدهی مالیاتی", "CREDIT", "LIABILITY", "PERMANENT", False, g4.account_id)
tax_gl = A("2101", "مالیات ارزش‌افزودهٔ فروش", "CREDIT", "LIABILITY", "PERMANENT", True, k7.account_id)
g3 = A("5", "هزینه‌ها", "DEBIT", "EXPENSE", "TEMPORARY", False)
k5 = A("51", "بهای تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", False, g3.account_id)
cogs_gl = A("511", "بهای تمام‌شده", "DEBIT", "EXPENSE", "TEMPORARY", True, k5.account_id)
k6 = A("59", "سایر", "DEBIT", "EXPENSE", "TEMPORARY", False, g3.account_id)
adj_gl = A("599", "اصلاح موجودی", "DEBIT", "EXPENSE", "TEMPORARY", True, k6.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ASSET", inv_gl.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)
engine_service.set_account_mapping(company_id, "COGS", cogs_gl.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ADJUSTMENT_GAIN", adj_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_REVENUE", rev_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_DISCOUNT", discount_gl.account_id)
csettings_service.set_account_mapping(company_id, "SALES_TAX_PAYABLE", tax_gl.account_id)

from peecha.services import unit_conversion as uc
from peecha.services import stock_count as stock_count_service
from peecha.services import commercial_settlements as settlements_service

D = decimal.Decimal
def raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False

k8 = A("32", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g4.account_id)
ap_gl = A("3201", "پرداختنی تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k8.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ADJUSTMENT_LOSS", adj_gl.account_id)


from peecha.services import lot_tracking as lt
from peecha.services import warehouse_locations as wl
from peecha.services import warehouse_operations as ops
from peecha.services import users as users_service
from peecha.services import roles as roles_service
from peecha.db.models.inventory import BinLocation, Warehouse

today = datetime.date.today()
pcs = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT", decimal_places=0)
supplier = dimensions_service.create_supplier(company_id, "S1", "تامین‌کننده")
g1 = catalog_service.create_item(company_id, "G-1", "پیچ‌گوشتی", catalog_service.ItemFields(
    item_kind_code="GOOD", base_uom_id=pcs, barcode="6260000000011", weight_kg=D(2)))
g2 = catalog_service.create_item(company_id, "G-2", "انبردست", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))

# =====================================================================
# R249: بررسیِ محل در اسناد، سازگاری، رزرو، تأمینِ مجدد، سه‌بعدی، API
# =====================================================================
from sqlalchemy import func as sa_func
from peecha.db.models.inventory import WarehouseTask, StockDocument as SD
from peecha.db.models.audit import ActivityLog
LF = wl.LocationFields
item = g1
wh = locations_service.create_warehouse(company_id, "WH01", "مرکزی", locations_service.WarehouseFields(is_default=True, allow_negative_stock=True))
general = locations_service.get_default_bin_location(wh).bin_location_id
zb = wl.create_location(company_id, wh, "AREA", "Z01", fields=LF(location_type_code="BULK"))
zp = wl.create_location(company_id, wh, "AREA", "Z02", fields=LF(location_type_code="PICK_FACE"))
zc = wl.create_location(company_id, wh, "AREA", "Z03", fields=LF(location_type_code="COLD", temperature_min_c=D(2), temperature_max_c=D(6)))
zh = wl.create_location(company_id, wh, "AREA", "Z04", fields=LF(allows_hazardous=True))
zs = wl.create_location(company_id, wh, "AREA", "Z09", fields=LF(location_type_code="SHIPPING"))
def rack_with_bins(zone, rack_code):
    r = wl.create_location(company_id, wh, "RACK", rack_code, zone)
    shelves = [wl.create_location(company_id, wh, "SHELF", f"L0{i}", r) for i in (1, 2)]
    return r, [wl.create_location(company_id, wh, "BIN", f"B0{i}", shelves[0], LF(max_weight_kg=D(100))) for i in (1, 2)]
rb, (bulk1, bulk2) = rack_with_bins(zb, "R01")
rp, (pick1, pick2) = rack_with_bins(zp, "R02")
rc, (cold1, _c2) = rack_with_bins(zc, "R03")
rh, (haz1, _h2) = rack_with_bins(zh, "R04")
milk = catalog_service.create_item(company_id, "M-1", "شیر", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))
acid = catalog_service.create_item(company_id, "A-1", "اسید", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))

def draft(doc_type, item_id, qty, bin_id=None, dst_bin=None, src=None, dst=None):
    doc = inv_documents_service.create_stock_document(company_id, user.user_id, doc_type, today, inv_documents_service.DocumentHeaderFields(
        source_warehouse_id=src, destination_warehouse_id=dst, counterparty_detail_account_id=supplier if doc_type == "RECEIPT" else None))
    inv_documents_service.add_line(doc, company_id, inv_documents_service.LineFields(
        item_id=item_id, uom_id=pcs, quantity=D(qty), quantity_base=D(qty), unit_cost=D(1000) if doc_type == "RECEIPT" else None,
        bin_location_id=bin_id, destination_bin_location_id=dst_bin))
    return doc
def post(doc):
    inv_documents_service.confirm_stock_document(doc, company_id)
    inv_documents_service.post_stock_document(doc, company_id, user.user_id)
    return doc
post(draft("RECEIPT", item, 80, bin_id=bulk1, dst=wh))
post(draft("RECEIPT", item, 5, bin_id=pick1, dst=wh))
post(draft("RECEIPT", milk, 10, dst=wh))
post(draft("RECEIPT", acid, 10, dst=wh))

# =====================================================================
# R255: تاییدِ رسیدِ انباردار برایِ فاکتورِ خریدِ مستقیم (اختیاری) + برچسب/ماوس در سه‌بعدی + پنلِ نقشه
# =====================================================================
from peecha.db.models.inventory import StockBalance
from sqlalchemy import func as sa_func
from peecha.services import treasury as treasury_service
from PySide6.QtWidgets import QGraphicsSimpleTextItem, QScrollArea
from peecha import numerals
P = numerals.to_persian_digits

def qty_at(item_id, bin_id):
    with new_session() as s:
        return s.scalar(select(sa_func.coalesce(sa_func.sum(StockBalance.quantity_on_hand), 0)).where(
            StockBalance.item_id == item_id, StockBalance.bin_location_id == bin_id)) or 0

csettings_service.set_feature_enabled(company_id, "PURCHASE_INVOICE_SKIP_APPROVAL", True)
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_APPROVAL", True)
supplier_group_id = next(g.person_group_id for g in dimensions_service.list_person_groups(company_id) if g.code == "SUPPLIER")
treasury_service.create_counterparty_mapping(company_id, "PAYMENT", ap_gl.account_id, person_group_id=supplier_group_id)
HF = lambda: documents_service.DocumentHeaderFields(counterparty_detail_account_id=supplier, currency_id=company.base_currency_id, warehouse_id=wh)
def invoice(item_id, q, bin_id=None):
    d = documents_service.create_document(company_id, user.user_id, "PURCHASE_INVOICE", today, HF())
    ln = documents_service.add_line(d, company_id, item_id, pcs, D(q), D(q), unit_price=D(100))
    if bin_id:
        documents_service.set_line_bin(company_id, ln, bin_id)
    documents_service.confirm_document(d, company_id, user.user_id)
    settlements_service.auto_approve_settlement_plan(d, company_id, user.user_id, [])
    return d, ln
def status(d):
    return documents_service.get_document(d, company_id)[0]

# ۱) Toggle خاموش: رفتارِ قبلی
check(any(f.feature_code == "PURCHASE_INVOICE_WAREHOUSE_APPROVAL" for f in csettings_service.list_features(company_id)),
      "گزینهٔ «تایید رسید انباردار برای فاکتور خرید مستقیم» در تنظیمات تعریف شده")
inv0, _ = invoice(milk, 2, pick2)
check(not documents_service.invoice_requires_warehouse_approval(inv0, company_id), "بدون گزینه، تایید انبار لازم نیست")
documents_service.post_document(inv0, company_id, user.user_id)
check(status(inv0).status_code == "POSTED", "بدون گزینه، فاکتور مثل قبل مستقیم ثبت نهایی می‌شود")

# ۲) Toggle روشن: بدونِ تاییدِ انبار ثبتِ نهایی نمی‌شود
csettings_service.set_feature_enabled(company_id, "PURCHASE_INVOICE_WAREHOUSE_APPROVAL", True)
inv1, ln1 = invoice(milk, 5)
check(documents_service.invoice_requires_warehouse_approval(inv1, company_id), "فاکتور مستقیم تایید انبار لازم دارد")
check(raises(lambda: documents_service.post_document(inv1, company_id, user.user_id)), "ثبت نهایی بدون تایید رسید انباردار رد شد")
check(status(inv1).status_code != "POSTED", "فاکتور ثبت نشد و هیچ سندی نخورد")
queue = [d.document_id for d in documents_service.list_purchase_order_goods_receipt_queue(company_id)]
check(inv1 in queue and inv0 not in queue, "فاکتور در صف «تایید انبار» آمد (فاکتور ثبت‌شده نه)")

from peecha.ui.screens.commercial_documents_list import CommercialDocumentsListScreen
lst = CommercialDocumentsListScreen(None)
row = next(d for d in documents_service.list_documents(company_id, document_type_code="PURCHASE_INVOICE") if d.document_id == inv1)
step = lst._next_step(row, None, None)
check(step is not None and step[0] == "تایید انبار", f"فهرست اسناد: مرحلهٔ بعد «تایید انبار» (got {step and step[0]})")

# دیالوگِ انباردار: مقدار و انبار ثابت، مکان الزامی
from peecha.ui.screens.purchase_goods_receipt import _GoodsReceiptDialog, _BIN_COL, _status_label
dlg = _GoodsReceiptDialog(None, inv1, company_id)
check(not dlg._qty_fields[ln1].isEnabled() and not dlg._line_warehouse_combos[ln1].isEnabled(),
      "در فاکتور، مقدار و انبار همان فاکتور است (انباردار فقط تایید می‌کند)")
check(not dlg.lines_table.isColumnHidden(_BIN_COL), "ستون مکان در تایید رسید فاکتور دیده می‌شود")
check("فاکتور خرید" in _status_label(status(inv1)), "عنوان «فاکتور خرید» در صف تایید انبار")
dlg._toggle_receipt()
check(status(inv1).warehouse_approved_at is None and "مکان" in dlg.status_label.text(), "بی‌مکان تایید نمی‌شود")
dlg._line_bin_combos[ln1].setCurrentIndex(dlg._line_bin_combos[ln1].findData(bulk2))
dlg._toggle_receipt()
check(status(inv1).warehouse_approved_at is not None, "انباردار رسید فاکتور را با مکان تایید کرد")
check(raises(lambda: documents_service.revert_to_draft(inv1, company_id)), "پس از تایید انبار، فاکتور به پیش‌نویس برنمی‌گردد (ابتدا انباردار برگرداند)")
dlg.close()
documents_service.post_document(inv1, company_id, user.user_id)
check(status(inv1).status_code == "POSTED", "پس از تایید انبار، ثبت نهایی انجام شد")
check(qty_at(milk, bulk2) == 5, "کالا در مکان تعیین‌شدهٔ انباردار نشست")
check(raises(lambda: documents_service.revert_warehouse_approval(inv1, company_id)), "تایید رسید فاکتور ثبت‌شده برنمی‌گردد")
check(inv1 not in [d.document_id for d in documents_service.list_purchase_order_goods_receipt_queue(company_id)],
      "فاکتور ثبت‌شده از صف انبار خارج شد")

# بازگشتِ تایید پیش از ثبت
inv2, ln2 = invoice(acid, 1)
documents_service.approve_warehouse(inv2, company_id, user.user_id, line_bins={ln2: bulk1})
documents_service.revert_warehouse_approval(inv2, company_id)
check(status(inv2).warehouse_approved_at is None and raises(lambda: documents_service.post_document(inv2, company_id, user.user_id)),
      "با برگشت تایید انباردار، ثبت نهایی دوباره بسته شد")

# ۳) فاکتورِ تبدیل‌شده از سفارشِ رسیده: تاییدِ دوباره لازم نیست
csettings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_GOODS_RECEIPT", True)
po = documents_service.create_document(company_id, user.user_id, "PURCHASE_ORDER", today, HF())
pl = documents_service.add_line(po, company_id, acid, pcs, D(3), D(3), unit_price=D(100))
documents_service.confirm_document(po, company_id, user.user_id)
documents_service.post_document(po, company_id, user.user_id)
documents_service.approve_warehouse(po, company_id, user.user_id, warehouse_id=wh, line_bins={pl: pick1})
inv3 = documents_service.convert_to_invoice(po, company_id, user.user_id, today)
check(not documents_service.invoice_requires_warehouse_approval(inv3, company_id), "فاکتور سفارش رسیده، تایید دوبارهٔ انبار نمی‌خواهد")
documents_service.confirm_document(inv3, company_id, user.user_id)
settlements_service.auto_approve_settlement_plan(inv3, company_id, user.user_id, [])
documents_service.post_document(inv3, company_id, user.user_id)
check(status(inv3).status_code == "POSTED" and qty_at(acid, pick1) == 3, "فاکتور سفارش رسیده مستقیم ثبت شد")

# ۴) سه‌بعدی: برچسبِ قفسه/منطقه و نمایشِ اطلاعات با ماوس
from peecha.ui.screens.warehouse_map import WarehouseMapScreen
ms = WarehouseMapScreen(None); ms.refresh(); ms.load_warehouse(wh)
ms.view3d_check.setChecked(True)
v3 = ms.view3d
texts = [i.text() for i in v3.scene.items() if isinstance(i, QGraphicsSimpleTextItem)]
check(any(P("R01") in t for t in texts) and any(P("Z01") in t for t in texts), f"برچسب قفسه و منطقه در سه‌بعدی (got {texts[:6]})")
check("طبقه" in v3.info[rb] and "قفسه" in v3.info[rb], "اطلاعات قفسه (نوع و تعداد طبقه/محل) برای نمایش با ماوس")
v3.hover(bulk1, None)
check(P("B01") in v3.hover_label.text() and v3._hovered == bulk1, "با بردن ماوس روی خانه، کد و اطلاعاتش نمایش داده شد")
check(any(p.pen().widthF() >= 2.5 for p in v3.polygons[bulk1]), "محل زیر ماوس پررنگ می‌شود")
v3.hover(None, None)
v3.labels_check.setChecked(False)
check(not any(isinstance(i, QGraphicsSimpleTextItem) for i in v3.scene.items()), "برچسب‌ها قابل‌خاموش‌کردن")

# ۵) پنلِ سمتِ راستِ نقشه: دکمه‌ها با ارتفاعِ کافی، اسکرول، اطلاعاتِ قفسه
check(all(b.minimumHeight() >= 34 for b in ms.op_buttons.values()), "دکمه‌های عملیات ارتفاع کافی دارند")
check(isinstance(ms.side_tabs.widget(0), QScrollArea), "پنل جزئیات اسکرول دارد (هیچ بخشی پنهان/فشرده نمی‌شود)")
rack_d = wl.create_location(company_id, wh, "RACK", "R05", zb, LF(width_m=D(1), length_m=D(4), height_m=D(2)))
sh = wl.create_location(company_id, wh, "SHELF", "L01", rack_d, LF(height_m=D("0.8")))
bn = wl.create_location(company_id, wh, "BIN", "B01", sh, LF(width_m=D(1)))
ms.load_warehouse(wh)
ms.select_location(bn, focus=False)
check(P("R05") in ms.rack_title.text() and "طبقه" in ms.rack_info.text() and "عرض" in ms.rack_info.text(),
      f"اطلاعات قفسه (ابعاد، تعداد طبقه/محل) نمایش داده می‌شود (got {ms.rack_info.text()[:80]})")
check(P("0.8") in ms.elevation_table.verticalHeaderItem(0).text(),
      "ارتفاع طبقه در نمای قفسه")
check("ابعاد" in ms.detail_info.text(), "ابعاد محل در جزئیات")
ms.select_location(zb, focus=False)
check("انتخاب کنید" in ms.rack_info.text(), "بدون قفسه، راهنمای انتخاب نمایش داده می‌شود")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
