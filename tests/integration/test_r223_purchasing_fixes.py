import os, sys, datetime, decimal
os.environ["PEECHA_DB_NAME"] = "peecha_test_r223_1"
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
from sqlalchemy import select
from peecha.db.models.security import UserCompany
from peecha.db.models.core import Company
with new_session() as s:
    uc = s.scalar(select(UserCompany).where(UserCompany.user_id == user.user_id))
    company = s.get(Company, uc.company_id)
company_id = company.company_id
sess.current_company = company

from peecha.services import fiscal_years as fiscal_years_service
fiscal_years_service.create_fiscal_year_for_date(company_id, 1, 1, datetime.date.today())

from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_settings as settings_service

# =========================================================================
# ۱: اتصالِ تعدادِ اعشارِ مقدار به decimal_places واحد -- طبقِ گزارشِ
#    صریحِ کاربر («وقتی در تعریفِ واحدِ کالا عددِ اعشار نداره و عدده،
#    چرا در همه‌جایِ برنامه اعشار داره و در سفارش مقدار هم عدد اعشار
#    داره؟»). واحدِ «عدد» بدونِ اعشار (decimal_places=0) تعریف می‌شود.
# =========================================================================
count_uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT", decimal_places=0)
weight_uom_id = catalog_service.create_uom(company_id, "KG", "کیلوگرم", "WEIGHT", decimal_places=3)

count_item_id = catalog_service.create_item(
    company_id, "4001", "کالای شمارشی",
    catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=count_uom_id, is_sellable=True, is_purchasable=True),
)
weight_item_id = catalog_service.create_item(
    company_id, "4002", "کالای وزنی",
    catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=weight_uom_id, is_sellable=True, is_purchasable=True),
)

from peecha.ui.screens.commercial_document import _LineDialog

items = catalog_service.list_items(company_id)
dialog = _LineDialog(None, items, company_id, None, 2, document_type_code="PURCHASE_ORDER")
dialog.item_combo.setCurrentIndex(dialog.item_combo.findData(count_item_id))
check(
    dialog.quantity_field._decimals == 0,
    f"با انتخاب کالای شمارشی (واحد بدون اعشار)، فیلد مقدار اعشار نمی‌پذیرد (got {dialog.quantity_field._decimals})",
)
dialog.item_combo.setCurrentIndex(dialog.item_combo.findData(weight_item_id))
check(
    dialog.quantity_field._decimals == 3,
    f"با انتخاب کالای وزنی، فیلد مقدار سه‌رقم اعشار می‌پذیرد (got {dialog.quantity_field._decimals})",
)
dialog.close()

# همین رفتار در ردیفِ ورودیِ درون‌خطیِ خودِ فرمِ سند (نه دیالوگِ جدا).
from peecha.ui.screens.commercial_document import CommercialDocumentScreen

supplier_id = dimensions_service.create_supplier(company_id, "S1", "تامین‌کنندهٔ آزمایشی")
doc_id = documents_service.create_document(
    company_id, user.user_id, "PURCHASE_ORDER", datetime.date.today(),
    documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=supplier_id, currency_id=company.base_currency_id,
    ),
)
screen = CommercialDocumentScreen("PURCHASE_ORDER", None)
screen.edit_document(doc_id)
entry_widgets = screen._entry_row_widgets
entry_widgets["item_combo"].setCurrentIndex(entry_widgets["item_combo"].findData(count_item_id))
check(
    entry_widgets["qty"]._decimals == 0,
    f"ردیف ورودی سفارش خرید هم برای کالای شمارشی اعشار نمی‌پذیرد (got {entry_widgets['qty']._decimals})",
)

# =========================================================================
# ۲: Toggleِ PURCHASE_ORDER_SKIP_APPROVAL -- طبقِ گزارشِ صریحِ کاربر
#    («سفارشِ خرید و مراحلِ آن قابلِ‌تنظیم باشد... بسیار پیچیده است برایِ
#    سازمان‌هایی که نیازِ این مراحل را ندارند»). پیش‌فرض خاموش -- دکمهٔ
#    تصویب باید نمایان بماند؛ با روشن‌کردنِ Toggle باید پنهان شود.
# =========================================================================
check(screen.approve_button.isVisibleTo(screen), "پیش‌فرض (Toggle خاموش)، دکمهٔ تصویب سفارش خرید نمایان است")

settings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_APPROVAL", True)
screen.refresh()
check(not screen.approve_button.isVisibleTo(screen), "با روشن‌کردن Toggle، دکمهٔ تصویب پنهان می‌شود")

settings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_APPROVAL", False)
screen.refresh()
check(screen.approve_button.isVisibleTo(screen), "با خاموش‌کردن دوبارهٔ Toggle، دکمهٔ تصویب برمی‌گردد")

# =========================================================================
# ۳: UIِ تبدیلِ واحدِ کالا (ItemUomConversion) در فرمِ کالا -- طبقِ گزارشِ
#    صریحِ کاربر («تعریفِ واحدهایِ اندازه‌گیری خیلی ساده و غیراستاندارد
#    برایِ یک سیستمِ ERP است»). بک‌اند از قبل ساخته شده بود؛ این‌جا فقط
#    اتصالِ آن به UIِ فرمِ کالا تاییدِ می‌شود.
# =========================================================================
from peecha.ui.screens.inventory_item_panel import ItemDetailPanel

panel = ItemDetailPanel()
panel.refresh(company_id)
item_row = next(r for r in catalog_service.list_items(company_id) if r.item_id == count_item_id)
panel.load(item_row)

check(
    panel.uom_conversion_combo.findData(count_uom_id) < 0,
    "واحد پایهٔ خود کالا در فهرست تبدیل واحد نیست (تبدیل واحد پایه به خودش بی‌معناست)",
)
box_uom_id = catalog_service.create_uom(company_id, "BOX", "کارتن", "COUNT", decimal_places=0)
panel.refresh(company_id)
panel.load(item_row)
panel.uom_conversion_combo.setCurrentIndex(panel.uom_conversion_combo.findData(box_uom_id))
panel.uom_conversion_factor_field.setText("24")
panel.uom_conversion_purchase_default_checkbox.setChecked(True)
panel._add_uom_conversion()

rows = catalog_service.list_item_uom_conversions(count_item_id)
check(len(rows) == 1, f"ردیف تبدیل واحد ذخیره شد (got {len(rows)})")
check(rows[0].uom_id == box_uom_id and rows[0].conversion_factor == decimal.Decimal(24), "واحد و ضریب درست ذخیره شدند")
check(rows[0].is_purchase_default is True, "پرچم پیش‌فرض خرید ذخیره شد")
# R225: جدولِ واحدها ردیفِ واحدِ پایه را هم نشان می‌دهد (پایه + کارتن).
check(panel.uom_conversion_table.rowCount() == 2, "جدول تبدیل واحد در UI هم رفرش شد")

panel._select_unit_row(rows[0].conversion_id)
panel._remove_uom_conversion()
rows = catalog_service.list_item_uom_conversions(count_item_id)
check(len(rows) == 0, "حذف ردیف تبدیل واحد از UI کار می‌کند")

# =========================================================================
# ۴: تاییدِ رسیدِ کالا برایِ سفارشِ خرید -- طبقِ گزارشِ صریحِ کاربر («بعدِ
#    تاییدِ سفارش، انباردار کجا رسیدنِ کالا را تایید کند، بدونِ دیدنِ
#    قیمت، و این تنظیمی باشد»). پیش‌فرضِ خاموش: مثلِ قبل، عملیاتِ تاییدِ
#    انبار فقط برایِ سفارشِ فروشِ پخشِ سرد معنا دارد.
# =========================================================================
from peecha.services import commercial_documents as documents_service
from peecha.ui.screens.purchase_goods_receipt import PurchaseGoodsReceiptScreen, _GoodsReceiptDialog, _LINE_COLUMNS

receipt_doc_id = documents_service.create_document(
    company_id, user.user_id, "PURCHASE_ORDER", datetime.date.today(),
    documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=supplier_id, currency_id=company.base_currency_id,
    ),
)
receipt_line_id = documents_service.add_line(
    receipt_doc_id, company_id, count_item_id, count_uom_id, decimal.Decimal(9), decimal.Decimal(9),
    unit_price=decimal.Decimal(5000),
)
documents_service.confirm_document(receipt_doc_id, company_id, user.user_id)

try:
    documents_service.approve_warehouse(receipt_doc_id, company_id, user.user_id)
    check(False, "پیش‌فرض (Toggle خاموش)، تایید انبار سفارش خرید باید رد شود")
except ValueError:
    check(True, "پیش‌فرض (Toggle خاموش)، تایید انبار سفارش خرید رد می‌شود (رفتار قبلی دست‌نخورده)")

check(
    documents_service.list_purchase_order_goods_receipt_queue(company_id) == [],
    "پیش‌فرض (Toggle خاموش)، صف تایید رسید کالا خالی است",
)

settings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_GOODS_RECEIPT", True)
settings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_POST", True)  # R230: رفتارِ پیشین (رسید پیش از ثبتِ نهایی)

queue = documents_service.list_purchase_order_goods_receipt_queue(company_id)
check(any(d.document_id == receipt_doc_id for d in queue), "با روشن‌کردن Toggle، سفارش خرید در صف تایید رسید ظاهر می‌شود")

check("قیمت" not in "".join(_LINE_COLUMNS), "جدول تایید رسید کالا هیچ ستون قیمتی ندارد")

from peecha.services import inventory_locations as locations_service
receipt_wh = locations_service.create_warehouse(company_id, "WH-R", "انبار رسید", locations_service.WarehouseFields())
documents_service.approve_warehouse(receipt_doc_id, company_id, user.user_id, warehouse_id=receipt_wh)
documents_service.set_warehouse_delivered_quantities(receipt_doc_id, company_id, {receipt_line_id: decimal.Decimal(8)})

receipt_screen = PurchaseGoodsReceiptScreen()
receipt_screen.refresh()
check(
    any(d.document_id == receipt_doc_id for d in receipt_screen._queue),
    "صفحهٔ تایید رسید کالا هم سفارش را نشان می‌دهد",
)

dialog = _GoodsReceiptDialog(None, receipt_doc_id, company_id)
check(
    dialog._qty_fields[receipt_line_id].value() == 8.0,
    f"دیالوگ رسید مقدار واقعی دریافتی (۸) را نشان می‌دهد (got {dialog._qty_fields[receipt_line_id].value()})",
)
dialog.close()

new_invoice_id = documents_service.convert_to_invoice(receipt_doc_id, company_id, user.user_id, datetime.date.today())
_, invoice_lines = documents_service.get_document(new_invoice_id, company_id)
check(
    invoice_lines[0].quantity == decimal.Decimal(8),
    f"تبدیل به فاکتور از مقدار دریافتی تاییدشده (۸) استفاده می‌کند، نه مقدار اولیهٔ سفارش (۹) (got {invoice_lines[0].quantity})",
)

settings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_GOODS_RECEIPT", False)
check(
    documents_service.list_purchase_order_goods_receipt_queue(company_id) == [],
    "با خاموش‌کردن دوبارهٔ Toggle، صف تایید رسید دوباره خالی می‌شود",
)

print("FAIL" if FAIL else "RESULT: ALL PASS")
sys.exit(1 if FAIL else 0)
