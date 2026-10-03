import os, sys, datetime, decimal
os.environ["PEECHA_DB_NAME"] = "peecha_test_r161_1"
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
from peecha.db.models.inventory import Warehouse
with new_session() as s:
    uc = s.scalar(select(UserCompany).where(UserCompany.user_id == user.user_id))
    company = s.get(Company, uc.company_id)
company_id = company.company_id
sess.current_company = company

from peecha.services import fiscal_years as fiscal_years_service
fiscal_years_service.create_fiscal_year_for_date(company_id, 1, 1, datetime.date.today())

from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import commercial_documents as documents_service


def set_company_tax(value):
    with new_session() as s:
        c = s.get(Company, company_id)
        c.default_tax_percent = value
        s.commit()


def set_warehouse_tax(warehouse_id, value):
    with new_session() as s:
        w = s.get(Warehouse, warehouse_id)
        w.default_tax_percent = value
        s.commit()


uom_id = catalog_service.create_uom(company_id, "PCS", "عدد", "COUNT")
item_id = catalog_service.create_item(
    company_id, "3001", "کالایِ آزمایشی",
    catalog_service.ItemFields(item_kind_code="GOOD", base_uom_id=uom_id, is_sellable=True, default_tax_percent=decimal.Decimal(3)),
)
warehouse_id = locations_service.create_warehouse(company_id, "WH-1", "انبارِ آزمایشی", locations_service.WarehouseFields())

# =========================================================================
# طبقِ درخواستِ صریحِ کاربر: «اگر رویِ تنظیماتِ شرکت بود برایِ همه لحاظ
# کند، اگر شرکت تنظیم نداشت رویِ انبار، و اگر انبار نداشت رویِ کالا
# نگاه کند» -- یعنی اولویتِ شرکت -> انبار -> کالا -> صفر.
# =========================================================================

# ۱: هیچ‌کدام تنظیم نشده (شرکت/انبار خالی، کالا هم فرضاً بدونِ مالیات) --
#    صفر.
tax = catalog_service.resolve_default_tax_percent(company_id, item_id, warehouse_id)
check(tax == decimal.Decimal(3), f"با شرکت/انبار خالی، مالیاتِ خودِ کالا (۳٪) به‌کار می‌رود (got {tax})")

# ۲: فقط انبار تنظیم شده (۵٪) -- باید بر کالا (۳٪) اولویت داشته باشد.
set_warehouse_tax(warehouse_id, decimal.Decimal(5))
tax = catalog_service.resolve_default_tax_percent(company_id, item_id, warehouse_id)
check(tax == decimal.Decimal(5), f"با انبارِ تنظیم‌شده، مالیاتِ انبار (۵٪) بر کالا اولویت دارد (got {tax})")

# ۳: هم شرکت (۹٪) و هم انبار (۵٪) تنظیم شده‌اند -- شرکت باید برنده شود.
set_company_tax(decimal.Decimal(9))
tax = catalog_service.resolve_default_tax_percent(company_id, item_id, warehouse_id)
check(tax == decimal.Decimal(9), f"وقتی شرکت تنظیم دارد، بر انبار و کالا اولویت دارد (got {tax})")

# ۴: اگر warehouse_id اصلاً پاس داده نشود (مثلاً سندی بدونِ انبارِ
#    مشخص) ولی شرکت تنظیم دارد -- باز هم شرکت برنده است.
tax = catalog_service.resolve_default_tax_percent(company_id, item_id, None)
check(tax == decimal.Decimal(9), f"بدونِ warehouse_id هم، مالیاتِ شرکت اعمال می‌شود (got {tax})")

# ۵: شرکت را خالی می‌کنیم، انبار هم پاس داده نمی‌شود -- باید مستقیم
#    سراغِ کالا برود.
set_company_tax(None)
tax = catalog_service.resolve_default_tax_percent(company_id, item_id, None)
check(tax == decimal.Decimal(3), f"بدونِ شرکت/انبار، مالیاتِ کالا اعمال می‌شود (got {tax})")

# =========================================================================
# ۶: امکانِ کنسل‌کردنِ مالیات رویِ فاکتور -- طبقِ درخواستِ صریح.
# =========================================================================
customer_id = dimensions_service.create_customer(company_id, "1", "مشتریِ آزمایشی")
set_company_tax(None)
set_warehouse_tax(warehouse_id, None)

doc_id = documents_service.create_document(
    company_id, user.user_id, "SALES_INVOICE", datetime.date.today(),
    documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=customer_id, currency_id=company.base_currency_id,
        warehouse_id=warehouse_id,
    ),
)
line_id = documents_service.add_line(
    doc_id, company_id, item_id, uom_id, decimal.Decimal(1), decimal.Decimal(1),
    unit_price=decimal.Decimal(1000), tax_percent=decimal.Decimal(9),
)
doc, lines = documents_service.get_document(doc_id, company_id)
check(doc.tax_amount == decimal.Decimal("90.00"), f"پیش از معافیت، مالیاتِ سند محاسبه شده است (got {doc.tax_amount})")
check(doc.tax_exempt is False, "پیش‌فرض، سند معاف از مالیات نیست")

documents_service.set_tax_exempt(doc_id, company_id, True)
doc, lines = documents_service.get_document(doc_id, company_id)
check(doc.tax_exempt is True, "پرچمِ معافیت روشن شد")
check(doc.tax_amount == decimal.Decimal("0.00"), f"مالیاتِ ردیفِ ازپیش‌ثبت‌شده هم صفر شد (got {doc.tax_amount})")
check(lines[0].tax_percent == decimal.Decimal("0.00"), f"درصدِ مالیاتِ ردیف هم صفر شد (got {lines[0].tax_percent})")

# ردیفِ تازه، حتی با tax_percent صریح، باید صفر بماند تا وقتی معافیت
# فعال است.
line2_id = documents_service.add_line(
    doc_id, company_id, item_id, uom_id, decimal.Decimal(1), decimal.Decimal(1),
    unit_price=decimal.Decimal(1000), tax_percent=decimal.Decimal(9),
)
doc, lines = documents_service.get_document(doc_id, company_id)
new_line = next(ln for ln in lines if ln.line_id == line2_id)
check(new_line.tax_percent == decimal.Decimal("0.00"), f"ردیفِ تازه هم در حالتِ معافیت مالیاتِ صفر می‌گیرد (got {new_line.tax_percent})")

# خاموش‌کردنِ معافیت -- ردیف‌هایِ ازپیش‌صفرشده خودشان بازنمی‌گردند، ولی
# ردیفِ تازه‌یِ بعدی دوباره از tax_percent واقعی پیروی می‌کند.
documents_service.set_tax_exempt(doc_id, company_id, False)
doc, lines = documents_service.get_document(doc_id, company_id)
check(doc.tax_exempt is False, "معافیت خاموش شد")
check(doc.tax_amount == decimal.Decimal("0.00"), "خاموش‌کردنِ معافیت، خودش مالیاتِ قبلی را بازنمی‌گرداند")

line3_id = documents_service.add_line(
    doc_id, company_id, item_id, uom_id, decimal.Decimal(1), decimal.Decimal(1),
    unit_price=decimal.Decimal(1000), tax_percent=decimal.Decimal(9),
)
doc, lines = documents_service.get_document(doc_id, company_id)
new_line3 = next(ln for ln in lines if ln.line_id == line3_id)
check(new_line3.tax_percent == decimal.Decimal("9.00"), f"بعدِ خاموش‌کردنِ معافیت، ردیفِ تازه دوباره مالیاتِ واقعی می‌گیرد (got {new_line3.tax_percent})")

# =========================================================================
# ۷: UIِ زنده -- فرمِ سندِ عمومی (CommercialDocumentScreen) و فرمِ فروشِ
#    حضوری (CommercialPosSaleScreen) باید تیکِ معافیت را داشته باشند و
#    با تغییرِ آن بلافاصله اعمال شود.
# =========================================================================
from peecha.ui.screens.commercial_document import CommercialDocumentScreen

screen = CommercialDocumentScreen("SALES_INVOICE", None)
check(hasattr(screen, "tax_exempt_checkbox"), "چک‌باکسِ معافیتِ مالیاتی در فرمِ عمومیِ سند وجود دارد")
screen.edit_document(doc_id)
check(screen.tax_exempt_checkbox.isChecked() is False, "با بارگذاریِ سند، تیک با وضعیتِ واقعیِ سند (خاموش) یکی است")

screen.tax_exempt_checkbox.setChecked(True)
doc, lines = documents_service.get_document(doc_id, company_id)
check(doc.tax_exempt is True, "تیک‌زدن در فرمِ زنده بلافاصله (بدونِ نیازِ دکمهٔ ذخیره) پرچمِ سند را روشن می‌کند")
check(doc.tax_amount == decimal.Decimal("0.00"), f"و بلافاصله مالیاتِ همه‌یِ ردیف‌ها را هم صفر می‌کند (got {doc.tax_amount})")

from peecha.ui.screens.commercial_pos_sale import CommercialPosSaleScreen
pos_screen = CommercialPosSaleScreen()
check(hasattr(pos_screen, "tax_exempt_checkbox"), "چک‌باکسِ معافیتِ مالیاتی در فرمِ فروشِ حضوری هم وجود دارد")

print("FAIL" if FAIL else "RESULT: ALL PASS")
sys.exit(1 if FAIL else 0)
