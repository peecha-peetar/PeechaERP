"""R351: پروموشن روی سند فروش: «بخر و ببر» ردیف هدیهٔ رایگان می‌سازد، فقط بزرگ‌ترین تخفیف پلکانی به نسبت مبلغ روی
ردیف‌ها پخش می‌شود (مالیات روی مبلغ بعد از تخفیف)، اعمال دوباره تکراری نیست، با تغییر سند اثر قبلی برداشته و دوباره
حساب می‌شود، فقط سند فروش پیش‌نویس، حذف قاعدهٔ استفاده‌شده رد می‌شود، فاکتور با هدیه ثبت می‌شود، و دکمهٔ فرم."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r351"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.services import commercial_documents as docs, commercial_partners as partners, commercial_settings as csettings, \
    commercial_settlements as settlements, promotions

k13 = A("13", "دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
ar_gl = A("131", "دریافتنی مشتریان", "DEBIT", "ASSET", "PERMANENT", True, k13.account_id)
g_rev = A("4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False)
k41 = A("41", "درآمد عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, g_rev.account_id)
rev_gl = A("411", "فروش", "CREDIT", "REVENUE", "TEMPORARY", True, k41.account_id)
disc_gl = A("412", "تخفیف فروش", "DEBIT", "REVENUE", "TEMPORARY", True, k41.account_id)
tax_gl = A("212", "مالیات فروش", "CREDIT", "LIABILITY", "PERMANENT", True, k7.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)
for key, account in (("SALES_REVENUE", rev_gl), ("SALES_DISCOUNT", disc_gl), ("SALES_TAX_PAYABLE", tax_gl)):
    csettings.set_account_mapping(company_id, key, account.account_id)

gift = item("GF-1", "کالای هدیه", "GOOD")
for it in (byp, gift, pk):
    receive(it, 100, 100_000)
customer = partners.create_customer(company_id, "C1", "فروشگاه", fast_track=True)
F = promotions.PromotionRuleFields
bxgy = promotions.create_promotion_rule(company_id, "B10", "ده تا بخر یکی هدیه", F(
    "BUY_X_GET_Y", applies_to_item_id=byp, buy_quantity=D(10), get_quantity=D(1), get_item_id=gift))
promotions.create_promotion_rule(company_id, "T5", "پنج درصد بالای پنج میلیون", F(
    "THRESHOLD_DISCOUNT", threshold_amount=D(5_000_000), discount_percent=D(5)))
t2 = promotions.create_promotion_rule(company_id, "T2", "دو درصد بالای سه میلیون", F(
    "THRESHOLD_DISCOUNT", threshold_amount=D(3_000_000), discount_percent=D(2)))

d = docs.create_document(company_id, uid, "SALES_INVOICE", today, docs.DocumentHeaderFields(
    counterparty_detail_account_id=customer, currency_id=company.base_currency_id, warehouse_id=wh_rm))
l1 = docs.add_line(d, company_id, byp, pcs, D(12), D(12), unit_price=D(500_000), tax_percent=D(10))
l2 = docs.add_line(d, company_id, pk, pcs, D(2), D(2), unit_price=D(1_000_000), discount_amount=D(100_000))


def state():
    _doc, lines = docs.get_document(d, company_id)
    return {ln.item_id: (ln.quantity, ln.unit_price, ln.discount_amount, ln.tax_amount, ln.description) for ln in lines}


effects = promotions.apply_to_document(d, company_id)
s1 = state()
check(sorted(e.code for e in effects) == ["B10", "T5"], f"buy-x-get-y and only the larger threshold apply ({[e.code for e in effects]})")
check(s1[gift][0] == D(1) and s1[gift][1] == 0 and "ده تا بخر" in s1[gift][4], "the gift is a free line naming the promotion")
check(s1[byp][2] == D(300_000) and s1[pk][2] == D(195_000) and s1[byp][3] == D(570_000),
      f"5% of 7.9M is spread by amount and tax is on the discounted amount ({s1[byp]}, {s1[pk]})")
promotions.apply_to_document(d, company_id)
check(state() == s1, "applying again changes nothing")
docs.update_line(l1, d, company_id, D(5), D(500_000), discount_amount=s1[byp][2], tax_percent=D(10))
effects = promotions.apply_to_document(d, company_id)
s2 = state()
check([e.code for e in effects] == ["T2"] and gift not in s2 and s2[byp][2] == D(50_000) and s2[pk][2] == D(138_000),
      f"after the change the gift goes and 2% of 4.4M replaces the old discount ({s2})")

check(raises(lambda: promotions.delete_promotion_rule(t2, company_id), "غیرفعال"), "a rule in use on a document cannot be deleted")
purchase = docs.create_document(company_id, uid, "PURCHASE_INVOICE", today, docs.DocumentHeaderFields(
    counterparty_detail_account_id=supplier, currency_id=company.base_currency_id, warehouse_id=wh_rm))
check(raises(lambda: promotions.apply_to_document(purchase, company_id), "فروش"), "only sales documents")

docs.update_line(l1, d, company_id, D(12), D(500_000), discount_amount=s2[byp][2], tax_percent=D(10))
promotions.apply_to_document(d, company_id)
docs.confirm_document(d, company_id, uid)
check(raises(lambda: promotions.apply_to_document(d, company_id), "پیش‌نویس"), "only draft documents")
settlements.auto_approve_settlement_plan(d, company_id, uid, [])
docs.post_document(d, company_id, uid)
header, _lines = docs.get_document(d, company_id)
check(header.status_code == "POSTED" and on_hand(gift, wh_rm) == D(99), "the invoice with the gift posts and issues the gift")

# دکمهٔ فرم
from PySide6.QtWidgets import QApplication
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.commercial_document import CommercialDocumentScreen

screen = CommercialDocumentScreen("SALES_INVOICE", None)
draft = docs.create_document(company_id, uid, "SALES_INVOICE", today, docs.DocumentHeaderFields(
    counterparty_detail_account_id=customer, currency_id=company.base_currency_id, warehouse_id=wh_rm))
screen.edit_document(draft)
check(screen.promotion_button.accessibleName() == "اعمال پروموشن‌ها" and screen.promotion_button.isEnabled(),
      "the sales form has an enabled promotion button for a draft")
screen.edit_document(d)
check(not screen.promotion_button.isEnabled(), "and it is disabled on a posted invoice")

finish()
