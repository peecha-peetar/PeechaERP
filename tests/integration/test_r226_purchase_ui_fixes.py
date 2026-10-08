import os, sys, datetime, decimal
os.environ["PEECHA_DB_NAME"] = "peecha_test_r226_1"
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
k3 = A("12", "موجودی انبار", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
inv_gl = A("121", "موجودی کالا", "DEBIT", "ASSET", "PERMANENT", True, k3.account_id)
g2 = A("3", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False)
k2 = A("31", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g2.account_id)
ap_gl = A("3101", "حساب پرداختنی تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k2.account_id)
engine_service.set_account_mapping(company_id, "INVENTORY_ASSET", inv_gl.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)

keeper = users_service.create_user("keeper1", "انباردار یک", "secret123", None, lang_id, False, [company_id], company_id)
wh_main = locations_service.create_warehouse(company_id, "WH1", "انبار اصلی", locations_service.WarehouseFields(manager_user_id=keeper.user_id))
wh_other = locations_service.create_warehouse(company_id, "WH2", "انبار دیگر", locations_service.WarehouseFields())

pcs = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT", decimal_places=0)
box = catalog_service.create_uom(company_id, "BOX", "کارتن", "COUNT", decimal_places=0)
item_id = catalog_service.create_item(company_id, "5001", "کنسرو", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))
catalog_service.set_item_uom_conversion(item_id, box, decimal.Decimal(24), is_purchase_default=True)
supplier = dimensions_service.create_supplier(company_id, "S1", "تامین‌کننده")
from PySide6.QtCore import Qt
from peecha.ui.screens.commercial_document import CommercialDocumentScreen
from peecha.services import inventory_documents as inv_documents_service
from peecha.services import operational_tasks as ops_service
D = decimal.Decimal
wh_keeper2 = locations_service.create_warehouse(company_id, "WH3", "انبار دوم انباردار", locations_service.WarehouseFields(manager_user_id=keeper.user_id))
item2 = catalog_service.create_item(company_id, "5002", "رب", catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=pcs))

def new_doc(doc_type, lines, warehouse_id=None):
    doc_id = documents_service.create_document(
        company_id, user.user_id, doc_type, datetime.date.today(),
        documents_service.DocumentHeaderFields(counterparty_detail_account_id=supplier, currency_id=company.base_currency_id, warehouse_id=warehouse_id),
    )
    ids = [documents_service.add_line(doc_id, company_id, it, pcs, D(q), D(q), unit_price=D(1000)) for it, q in lines]
    return doc_id, ids

def post_invoice(inv_id):
    documents_service.confirm_document(inv_id, company_id, user.user_id)
    documents_service.approve_document(inv_id, company_id)
    settlements_service.auto_approve_settlement_plan(inv_id, company_id, user.user_id, [])
    documents_service.post_document(inv_id, company_id, user.user_id)

# ===== ۱/۲: MDI -- فرمِ بسته از ناحیه جدا می‌شود؛ فرمِ تازه تمام‌عرض =====
from peecha.ui.shell_window import MainWindow
mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
mw.open_screen("PURCH_ORDER"); app.processEvents()
mw.open_screen("PURCH_DOCUMENTS_LIST"); app.processEvents()
sw = mw._mdi_subwindows["commercial_document_purchase_order"]
check(sw.isMaximized() or sw.geometry() == mw.mdi_area.viewport().rect(), "فرم تمام‌عرض ناحیهٔ اصلی باز می‌شود")
sw.close(); app.processEvents(); app.processEvents()
check(sw not in mw.mdi_area.subWindowList(), "فرم بسته‌شده از ناحیهٔ MDI جدا شد (دوباره کاشی‌ای ظاهر نمی‌شود)")
mw.mdi_area.tileSubWindows(); app.processEvents()
check(not sw.isVisible(), "کاشی‌کردن فرم بسته را دوباره نشان نمی‌دهد")
mw.open_screen("PURCH_ORDER"); app.processEvents()
check(sw in mw.mdi_area.subWindowList() and sw.isVisible(), "بازکردن دوباره همان فرم را برمی‌گرداند")

# ===== ۳: پیامِ ذخیره در پنجرهٔ تعاملی با «تایید» =====
from PySide6.QtWidgets import QMessageBox as _QMB
screen = mw._screens["commercial_document_purchase_order"]
screen.counterparty_combo.setCurrentIndex(screen.counterparty_combo.findData(supplier))
screen.save_button.click(); app.processEvents()
boxes = [w for w in screen.findChildren(_QMB) if w.isVisible()]
check(len(boxes) == 1 and "ذخیره شد" in boxes[0].text() and any(b.text() == "تایید" for b in boxes[0].buttons()),
      f"پیام ذخیره در پنجرهٔ تعاملی با دکمهٔ «تایید» (got {[b.text() for b in boxes]})")
for b in boxes:
    b.close()

# ===== ۴: کارتابل -- تصویب، رسید، تبدیل =====
settings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_GOODS_RECEIPT", True)
settings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_POST", True)  # R230: رفتارِ پیشین (رسید پیش از ثبتِ نهایی)
po, (l1, l2) = new_doc("PURCHASE_ORDER", [(item_id, 5), (item2, 7)])
documents_service.confirm_document(po, company_id, user.user_id)
kinds = {(t.kind, t.document_id) for t in ops_service.list_operational_tasks(company_id, user.user_id)}
check(("MANAGER_APPROVAL", po) in kinds, "کارتابل مدیر: سفارش تاییدشده منتظر تصویب")
documents_service.approve_document(po, company_id)
keeper_kinds = {(t.kind, t.document_id) for t in ops_service.list_operational_tasks(company_id, keeper.user_id)}
check(("GOODS_RECEIPT", po) in keeper_kinds, "کارتابل انباردار: رسید کالای سفارش")
from peecha.ui.screens.my_tasks import MyTasksScreen
tasks_screen = MyTasksScreen(mw); tasks_screen.refresh()
check(any(k.startswith("DOC:") for k in tasks_screen.cards_by_key), f"صفحهٔ کارتابل کارهای اسناد را نشان می‌دهد ({list(tasks_screen.cards_by_key)})")

# ===== ۵: انبارِ هر ردیف در تاییدِ رسید =====
check(raises(lambda: documents_service.approve_warehouse(po, company_id, keeper.user_id, line_warehouses={l1: wh_main, l2: wh_other})),
      "انباردار در انبار دیگران رسید نمی‌زند")
documents_service.approve_warehouse(po, company_id, keeper.user_id, line_warehouses={l1: wh_main, l2: wh_keeper2})
_, po_lines = documents_service.get_document(po, company_id)
check({l.line_id: l.warehouse_id for l in po_lines} == {l1: wh_main, l2: wh_keeper2}, "هر ردیف در انبار خودش رسید شد")
check(("CONVERT_TO_INVOICE", po) in {(t.kind, t.document_id) for t in ops_service.list_operational_tasks(company_id, user.user_id)},
      "پس از رسید، کارتابل «تبدیل به فاکتور» را نشان می‌دهد")
inv = documents_service.convert_to_invoice(po, company_id, user.user_id, datetime.date.today())
_, inv_lines = documents_service.get_document(inv, company_id)
check(sorted(l.warehouse_id for l in inv_lines) == sorted([wh_main, wh_keeper2]), "فاکتور انبار ردیفی رسید را گرفت")

# ===== ۱۰: قفلِ مقدار بدونِ Toggle =====
locked = documents_service.get_quantity_locked_line_ids(inv, company_id)
check(len(locked) == 2, "مقدار تاییدشدهٔ انبار در فاکتور قفل است (بدون تنظیم)")
check(raises(lambda: documents_service.update_line(inv_lines[0].line_id, inv, company_id, D(1), inv_lines[0].unit_price)),
      "تغییر مقدار ردیف فاکتور رد می‌شود")

# ===== ۷: مرکزِ هزینه/پروژه پس از تایید + برگشت/حذف =====
documents_service.confirm_document(inv, company_id, user.user_id)
documents_service.approve_document(inv, company_id)
documents_service.update_document_dimensions(inv, company_id, None, None)
check(True, "مرکز هزینه/پروژه پس از تصویب هم قابل‌ذخیره است")
check(raises(lambda: documents_service.delete_document(inv, company_id)), "فاکتور تاییدشده حذف نمی‌شود (فقط لغو)")
documents_service.revert_to_draft(inv, company_id)
doc_row, _ = documents_service.get_document(inv, company_id)
check(doc_row.status_code == "DRAFT", "فاکتور تصویب‌شده به پیش‌نویس برمی‌گردد")
draft_inv, _ = new_doc("PURCHASE_INVOICE", [(item_id, 1)], warehouse_id=wh_main)
settlements_service.save_settlement_plan(draft_inv, company_id, user.user_id, [])
documents_service.delete_document(draft_inv, company_id)
check(raises(lambda: documents_service.get_document(draft_inv, company_id)), "فاکتور پیش‌نویس دارای نقشهٔ تسویه واقعاً حذف می‌شود")

# ===== ۹: رسیدِ انبارِ صادرشده از فاکتور =====
post_invoice(inv)
inv_doc, _ = documents_service.get_document(inv, company_id)
stock_id = inv_doc.stock_document_id
check(stock_id is not None, "فاکتور رسید انبار صادر کرد")
check(raises(lambda: inv_documents_service.reverse_and_cancel_stock_document(stock_id, company_id, user.user_id)),
      "رسید صادرشده از فاکتور حذف/برگشت نمی‌شود")
row = next(r for r in inv_documents_service.list_stock_documents(company_id) if r.stock_document_id == stock_id)
check(row.origin_label is not None and "فاکتور خرید" in row.origin_label, f"مبدأ رسید در فهرست معلوم است (got {row.origin_label})")

# ===== ۱۵: اصلاحِ فاکتورِ ثبت‌شده همچنان قفلِ مقدار دارد =====
settings_service.set_feature_enabled(company_id, "ALLOW_EDIT_POSTED_INVOICE", True)
correction = documents_service.start_invoice_correction(inv, company_id, user.user_id)
corr_locked = documents_service.get_quantity_locked_line_ids(correction, company_id)
_, corr_lines = documents_service.get_document(correction, company_id)
check(len(corr_locked) == len(corr_lines) == 2, "ردیف‌های پیش‌نویس اصلاحیه هم قفل مقدار دارند")
check(raises(lambda: documents_service.update_line(corr_lines[0].line_id, correction, company_id, D(1), corr_lines[0].unit_price)),
      "تغییر مقدار در اصلاحیه رد می‌شود")

# ===== ۶: سفارشِ تاییدشده بی‌صدا ویرایش نمی‌شود =====
po2, (p2l1,) = new_doc("PURCHASE_ORDER", [(item_id, 3)])
documents_service.confirm_document(po2, company_id, user.user_id)
check(raises(lambda: documents_service.update_line(p2l1, po2, company_id, D(3), D(5))), "سرویس ویرایش ردیف سفارش تاییدشده را رد می‌کند")
check(raises(lambda: documents_service.delete_line(p2l1, po2, company_id)), "حذف ردیف سفارش تاییدشده رد می‌شود")
po_screen = CommercialDocumentScreen("PURCHASE_ORDER", None)
po_screen.edit_document(po2)
actions = po_screen.lines_table.cellWidget(0, po_screen.lines_table.columnCount() - 1)  # R253: «عملیات» ستونِ آخر است
from PySide6.QtWidgets import QPushButton as _QPB
edit_btns = [b for b in actions.findChildren(_QPB) if b.toolTip() and "فقط-خواندنی" in b.toolTip()]
check(len(edit_btns) == 2 and all(not b.isEnabled() for b in edit_btns), "دکمه‌های ویرایش/حذف ردیف سفارش تاییدشده غیرفعال‌اند")

# ===== ۸: انبارِ هر ردیف هنگامِ تبدیل (بدونِ رسید) =====
settings_service.set_feature_enabled(company_id, "PURCHASE_ORDER_GOODS_RECEIPT", False)
documents_service.approve_document(po2, company_id)
inv2 = documents_service.convert_to_invoice(po2, company_id, user.user_id, datetime.date.today(), line_warehouses={p2l1: wh_other})
inv2_doc, inv2_lines = documents_service.get_document(inv2, company_id)
check(inv2_lines[0].warehouse_id == wh_other and inv2_doc.warehouse_id == wh_other, "انبار ردیف در فرم تبدیل تعیین شد")

# ===== ۱۱-۱۴: دکمه‌هایِ ردیفِ فهرستِ اسنادِ خرید =====
documents_service.cancel_document(inv2, company_id)
from peecha.ui.screens.commercial_documents_list import CommercialDocumentsListScreen
lst = mw._screens["commercial_documents_list_purchase"]
lst.refresh()
def row_buttons(doc_id):
    for r in range(lst.table.rowCount()):
        if lst.table.item(r, 0).data(Qt.UserRole) == doc_id:
            w = lst.table.cellWidget(r, lst.table.columnCount() - 1)
            return {b.toolTip() or b.text(): b for b in w.findChildren(_QPB)}
    return {}
posted_btns = row_buttons(inv)
check("حذف سند" not in posted_btns and "نمایش چاپی" in posted_btns, f"فاکتور ثبت‌شده: بدون حذف، با نمایش چاپی (got {list(posted_btns)})")
cancelled_btns = row_buttons(inv2)
check(set(cancelled_btns) == {"نمایش چاپی"}, f"سند لغوشده فقط نمایش چاپی دارد (got {list(cancelled_btns)})")
po3, _ = new_doc("PURCHASE_ORDER", [(item_id, 2)])
documents_service.confirm_document(po3, company_id, user.user_id)
lst.refresh()
po3_btns = row_buttons(po3)
check("مرحلهٔ بعد: تصویب مدیر" in po3_btns, f"سفارش تاییدشده دکمهٔ مرحلهٔ بعد (تصویب) دارد (got {list(po3_btns)})")
po3_btns["مرحلهٔ بعد: تصویب مدیر"].click(); app.processEvents()
check(documents_service.get_document(po3, company_id)[0].status_code == "APPROVED", "مرحلهٔ بعد از همان ردیف انجام شد")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
