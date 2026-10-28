"""R353: اعمال خودکار پروموشن: با قابلیت خاموش هیچ اثری نیست؛ روشن: سفارش فروش موبایل در سرور هدیه می‌گیرد و یادداشت
برمی‌گرداند، فاکتور فوری پخش گرم دست نمی‌خورد، و فروش حضوری پیش از تایید هدیه و تخفیف را اعمال می‌کند."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r353"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.services import commercial_documents as docs, commercial_partners as partners, commercial_pos as pos, \
    commercial_pricing as pricing, commercial_settings as csettings, promotions

k13 = A("13", "دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
ar_gl = A("131", "دریافتنی مشتریان", "DEBIT", "ASSET", "PERMANENT", True, k13.account_id)
g_rev = A("4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False)
k41 = A("41", "درآمد عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, g_rev.account_id)
rev_gl = A("411", "فروش", "CREDIT", "REVENUE", "TEMPORARY", True, k41.account_id)
disc_gl = A("412", "تخفیف فروش", "DEBIT", "REVENUE", "TEMPORARY", True, k41.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)
for key, account in (("SALES_REVENUE", rev_gl), ("SALES_DISCOUNT", disc_gl)):
    csettings.set_account_mapping(company_id, key, account.account_id)

gift = item("GF-1", "کالای هدیه", "GOOD")
for it in (byp, gift):
    receive(it, 100, 100_000)
customer = partners.create_customer(company_id, "C1", "فروشگاه", fast_track=True)
channel = pricing.create_channel(company_id, "PS", "پخش سرد", "PRE_SALES")
promotions.create_promotion_rule(company_id, "B10", "ده تا بخر یکی هدیه", promotions.PromotionRuleFields(
    "BUY_X_GET_Y", applies_to_item_id=byp, buy_quantity=D(10), get_quantity=D(1), get_item_id=gift))

from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)
token = client.post("/auth/login", json={"username": "admin", "password": "secret123"}).json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}


def order(doc_type="SALES_ORDER", post=False):
    body = {"document_type_code": doc_type, "counterparty_detail_account_id": customer, "currency_id": company.base_currency_id,
            "warehouse_id": wh_rm, "channel_code": channel, "post_immediately": post,
            "lines": [{"item_id": byp, "uom_id": pcs, "quantity": "12", "unit_price": "500000"}]}
    resp = client.post("/orders", headers=headers, json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return data, {ln.item_id: ln for ln in docs.get_document(data["document_id"], company_id)[1]}


data, lines = order()
check(gift not in lines and not data["settlement_warning"], "with the feature off a mobile order is unchanged")
csettings.set_feature_enabled(company_id, promotions.FEATURE_AUTO_APPLY, True)
data, lines = order()
check(gift in lines and lines[gift].unit_price == 0 and "ده تا بخر" in (data["settlement_warning"] or "")
      and len(data["line_ids"]) == 1, f"the mobile order gets the gift on the server and a note ({data['settlement_warning']})")
data, lines = order("SALES_INVOICE", post=True)
check(gift not in lines, "an immediately posted van-sales invoice is left as the visitor collected it")

# فروش حضوری
from PySide6.QtWidgets import QApplication
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.commercial_pos_sale import CommercialPosSaleScreen

terminal = pos.create_terminal(company_id, wh_rm, "T1", "صندوق ۱")
pos.open_session(terminal, uid, D(0))
screen = CommercialPosSaleScreen()
screen.refresh()
screen.terminal_combo.setCurrentIndex(max(0, screen.terminal_combo.findData(terminal)))
screen.customer_combo.setCurrentIndex(max(0, screen.customer_combo.findData(customer)))
check(screen._ensure_document(), f"the POS creates a sale ({screen.status_label.text()})")
docs.add_line(screen._document_id, company_id, byp, pcs, D(10), D(10), unit_price=D(500_000))
screen._load_document()
sale = screen._document_id
screen._confirm_sale("CASH", print_receipt=False)
header, sale_lines = docs.get_document(sale, company_id)
pos_lines = {ln.item_id: ln for ln in sale_lines}
check(gift in pos_lines and pos_lines[gift].quantity == 1 and "ده تا بخر" in str(pos_lines[gift].description)
      and header.status_code == "CONFIRMED", f"the POS applies the promotion before confirming the sale ({header.status_code})")

finish()
