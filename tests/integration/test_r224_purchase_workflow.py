import os, sys, datetime, decimal
os.environ["PEECHA_DB_NAME"] = "peecha_test_r224_1"
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

def raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False

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
from peecha.services import chart_of_accounts as coa_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import inventory_engine as engine_service
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_settings as settings_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import users as users_service

lang_id = company.default_language_id
A = lambda code, name, nature, typ, perm, post, parent=None: coa_service.create_account(company_id, code, name, nature, typ, perm, post, lang_id, parent_account_id=parent)
g1 = A("1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False)
k3 = A("12", "موجودیِ انبار", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
inv_gl = A("121", "موجودیِ کالا", "DEBIT", "ASSET", "PERMANENT", True, k3.account_id)
g2 = A("3", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False)
k2 = A("31", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g2.account_id)
ap_gl = A("3101", "حسابِ پرداختنیِ تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k2.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ASSET", inv_gl.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)

keeper = users_service.create_user("keeper1", "انباردارِ یک", "secret123", None, lang_id, False, [company_id], company_id)
wh_main = locations_service.create_warehouse(company_id, "WH1", "انبارِ اصلی", locations_service.WarehouseFields(manager_user_id=keeper.user_id))
wh_other = locations_service.create_warehouse(company_id, "WH2", "انبارِ دیگر", locations_service.WarehouseFields())

pcs = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT", decimal_places=0)
box = catalog_service.create_uom(company_id, "BOX", "کارتن", "COUNT", decimal_places=0)
item_id = catalog_service.create_item(company_id, "5001", "کنسرو", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))
catalog_service.set_item_uom_conversion(item_id, box, decimal.Decimal(24), is_purchase_default=True)
supplier = dimensions_service.create_supplier(company_id, "S1", "تامین‌کننده")

def new_po(qty, uom=pcs, price=1000):
    doc_id = documents_service.create_document(
        company_id, user.user_id, "PURCHASE_ORDER", datetime.date.today(),
        documents_service.DocumentHeaderFields(counterparty_detail_account_id=supplier, currency_id=company.base_currency_id),
    )
    line_id = documents_service.add_line(doc_id, company_id, item_id, uom, decimal.Decimal(qty), decimal.Decimal(qty), unit_price=decimal.Decimal(price))
    return doc_id, line_id

# ===== ۳: تبدیلِ واحد -- خرید به کارتن، موجودی به عدد =====
options = catalog_service.list_item_uom_options(item_id)
check([o.uom_id for o in options] == [pcs, box], "گزینه‌هایِ واحد: عدد (پایه) و کارتن")
po_box, po_box_line = new_po(2, uom=box, price=48000)
_, lines = documents_service.get_document(po_box, company_id)
check(lines[0].quantity == 2 and lines[0].quantity_base == 48, f"۲ کارتن = ۴۸ عدد در مقدارِ پایه (got {lines[0].quantity_base})")
check(documents_service.list_purchase_order_goods_receipt_queue(company_id) == [], "صفِ رسید بدونِ Toggle خالی است")

# ===== ۱: سفارشِ تاییدشده قابلِ‌ویرایش در فرم نیست =====
documents_service.confirm_document(po_box, company_id, user.user_id)
from peecha.ui.screens.commercial_document import CommercialDocumentScreen
screen = CommercialDocumentScreen("PURCHASE_ORDER", None)
screen.edit_document(po_box)
check(not screen._lines_are_editable(), "سفارشِ تاییدشده در فرم فقط-خواندنی است")
check(not screen.save_button.isEnabled(), "دکمهٔ ذخیره برایِ سفارشِ تاییدشده غیرفعال است")
check(screen.revert_button.isEnabled(), "بازگشت به پیش‌نویس برایِ ویرایش فعال است")
documents_service.approve_document(po_box, company_id)
screen.edit_document(po_box)
check(screen.revert_button.isEnabled(), "سفارشِ تصویب‌شده هم به پیش‌نویس برمی‌گردد")
documents_service.revert_to_draft(po_box, company_id)
screen.edit_document(po_box)
check(screen._lines_are_editable(), "بعدِ بازگشت به پیش‌نویس، سفارش دوباره قابلِ‌ویرایش است")
documents_service.confirm_document(po_box, company_id, user.user_id)

# ===== ۲/۴/۵: رسیدِ کالا =====
settings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_GOODS_RECEIPT", True)
check(raises(lambda: documents_service.convert_to_invoice(po_box, company_id, user.user_id, datetime.date.today())),
      "پیش از تاییدِ رسید، تبدیل به فاکتور مجاز نیست")
screen.edit_document(po_box)
check(not screen.convert_button.isEnabled(), "دکمهٔ تبدیل به فاکتور پیش از رسید غیرفعال است")
check("اختیاری" in screen.warehouse_label.text(), "انبارِ سفارشِ خرید اختیاری نمایش داده می‌شود")

queue_keeper = documents_service.list_purchase_order_goods_receipt_queue(company_id, keeper.user_id)
check(any(d.document_id == po_box for d in queue_keeper), "سفارشِ بدونِ انبار در صفِ انباردار دیده می‌شود")
check(raises(lambda: documents_service.approve_warehouse(po_box, company_id, keeper.user_id)), "رسید بدونِ انتخابِ انبار رد می‌شود")
check(raises(lambda: documents_service.approve_warehouse(po_box, company_id, keeper.user_id, warehouse_id=wh_other)),
      "انباردار نمی‌تواند در انباری که مسئولش نیست رسید بزند")
documents_service.approve_warehouse(po_box, company_id, keeper.user_id, warehouse_id=wh_main)
doc, _ = documents_service.get_document(po_box, company_id)
check(doc.warehouse_id == wh_main, "انبارِ سفارش در لحظه‌یِ رسید ثبت شد")
check(raises(lambda: documents_service.revert_to_draft(po_box, company_id)), "بعدِ رسید، بازگشت به پیش‌نویس ممنوع است")

po_other, _ = new_po(5)
documents_service.confirm_document(po_other, company_id, user.user_id)
documents_service.approve_warehouse(po_other, company_id, user.user_id, warehouse_id=wh_other)
queue_keeper = documents_service.list_purchase_order_goods_receipt_queue(company_id, keeper.user_id)
check(not any(d.document_id == po_other for d in queue_keeper), "سفارشِ انبارِ دیگر در صفِ این انباردار نیست")
check(any(d.document_id == po_other for d in documents_service.list_purchase_order_goods_receipt_queue(company_id, user.user_id)),
      "مدیر همه‌یِ سفارش‌ها را می‌بیند")

# ===== ۶: قفلِ مقدار پس از رسید =====
settings_service.set_feature_enabled(company_id, "RECEIPT_LOCKS_INVOICE_QUANTITY", True)
check(raises(lambda: documents_service.convert_to_invoice(po_box, company_id, user.user_id, datetime.date.today(), {po_box_line: decimal.Decimal(1)})),
      "تبدیلِ جزئی (کمتر از مقدارِ رسیدشده) با قفل ممنوع است")
inv_id = documents_service.convert_to_invoice(po_box, company_id, user.user_id, datetime.date.today())
inv_doc, inv_lines = documents_service.get_document(inv_id, company_id)
check(inv_doc.warehouse_id == wh_main, "فاکتور انبارِ رسید را گرفت")
check(inv_lines[0].uom_id == box and inv_lines[0].quantity_base == 48, "فاکتور با واحدِ کارتن و مقدارِ پایهٔ ۴۸")
locked = documents_service.get_quantity_locked_line_ids(inv_id, company_id)
check(inv_lines[0].line_id in locked, "ردیفِ فاکتور قفل است")
check(raises(lambda: documents_service.update_line(inv_lines[0].line_id, inv_id, company_id, decimal.Decimal(3), inv_lines[0].unit_price)),
      "تغییرِ مقدارِ ردیفِ قفل‌شده ممنوع است")
documents_service.update_line(inv_lines[0].line_id, inv_id, company_id, inv_lines[0].quantity, decimal.Decimal(50000))
check(True, "تغییرِ قیمت (بدونِ تغییرِ مقدار) مجاز است")
check(raises(lambda: documents_service.delete_line(inv_lines[0].line_id, inv_id, company_id)), "حذفِ ردیفِ قفل‌شده ممنوع است")
inv_screen = CommercialDocumentScreen("PURCHASE_INVOICE", None)
inv_screen.edit_document(inv_id)
qty_widget = inv_screen.lines_table.cellWidget(0, 2)
check(qty_widget is not None and not qty_widget.isEnabled(), "فیلدِ مقدار در فاکتور غیرفعال است")

# ===== ۷: مراحلِ فاکتور -- حذفِ تصویبِ مدیر =====
documents_service.confirm_document(inv_id, company_id, user.user_id)
settlements_service.save_settlement_plan(inv_id, company_id, user.user_id, [])
settlements_service.approve_settlement_plan(inv_id, company_id, user.user_id)
check(raises(lambda: documents_service.post_document(inv_id, company_id, user.user_id)), "بدونِ Toggle، فاکتورِ خرید تصویبِ مدیر لازم دارد")
settings_service.set_feature_enabled(company_id, "PURCHASE_INVOICE_SKIP_APPROVAL", True)
inv_screen.edit_document(inv_id)
check(not inv_screen.approve_button.isVisibleTo(inv_screen), "با Toggle، دکمهٔ تصویب در فاکتورِ خرید پنهان است")
documents_service.post_document(inv_id, company_id, user.user_id)
check(True, "با Toggle، فاکتورِ خریدِ تاییدشده مستقیم ثبتِ نهایی شد")

stock = {r.warehouse_id: r.quantity_on_hand for r in engine_service.get_item_stock_by_warehouse(company_id, item_id)}
check(stock.get(wh_main) == 48, f"موجودی به واحدِ پایه: ۴۸ عدد در انبارِ رسید (got {stock.get(wh_main)})")
balances = engine_service.list_balances(company_id, item_id=item_id)
avg = next(b.average_unit_cost for b in balances if b.warehouse_id == wh_main)
check(abs(avg - decimal.Decimal(50000) / 24) < decimal.Decimal("0.01"), f"بهایِ واحدِ پایه = ۵۰۰۰۰÷۲۴ (got {avg})")

# ===== ۷: ثبتِ یک‌مرحله‌ای =====
settings_service.set_feature_enabled(company_id, "INVOICE_ONE_STEP_POST", True)
inv2 = documents_service.create_document(
    company_id, user.user_id, "PURCHASE_INVOICE", datetime.date.today(),
    documents_service.DocumentHeaderFields(counterparty_detail_account_id=supplier, currency_id=company.base_currency_id, warehouse_id=wh_main),
)
documents_service.add_line(inv2, company_id, item_id, pcs, decimal.Decimal(3), decimal.Decimal(3), unit_price=decimal.Decimal(2000))
inv_screen.edit_document(inv2)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)  # «پرداختی انجام شده؟» خیر = نسیه
inv_screen._confirm_button_clicked()
doc2, _ = documents_service.get_document(inv2, company_id)
check(doc2.status_code == "POSTED", f"ثبتِ یک‌مرحله‌ای: فاکتور با دکمهٔ تایید ثبتِ نهایی شد (got {doc2.status_code})")

# ===== ۳: کمبویِ واحد در دیالوگِ ردیف =====
from peecha.ui.screens.commercial_document import _LineDialog
dialog = _LineDialog(None, catalog_service.list_items(company_id), company_id, None, 0, document_type_code="PURCHASE_ORDER")
dialog.item_combo.setCurrentIndex(dialog.item_combo.findData(item_id))
check(dialog.uom_combo.currentData() == box, "در سفارشِ خرید، واحدِ پیش‌فرضِ خرید (کارتن) انتخاب می‌شود")
dialog.quantity_field.setValue(3)
fields = dialog.result_fields()
check(fields["uom_id"] == box and fields["quantity_base"] == 72, f"۳ کارتن -> مقدارِ پایهٔ ۷۲ (got {fields['quantity_base']})")
dialog.uom_combo.setCurrentIndex(dialog.uom_combo.findData(pcs))
check(dialog.result_fields()["uom_id"] == pcs, "تغییرِ واحد به عدد در دیالوگ اعمال می‌شود")
dialog.close()

print("FAIL" if FAIL else "RESULT: ALL PASS")
sys.exit(1 if FAIL else 0)
