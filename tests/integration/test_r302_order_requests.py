"""R302: سفارش صادرشده در «درخواست‌های در جریان من» صادرکننده (با مرحله و منتظر چه کسی) + برچسب «حواله» برای فروش."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r302"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from fastapi.testclient import TestClient
from peecha.services import operational_tasks
from peecha.services.workflow import inbox
check, raises = fx.check, fx.raises
cs = csettings_service

keeper = visitor.user_id
wh2 = locations_service.create_warehouse(company_id, "WH-2", "انبار دوم",
                                         locations_service.WarehouseFields(allow_negative_stock=True, manager_user_id=keeper))


def order(doc_type="SALES_ORDER", wh=warehouse_id):
    doc = documents_service.create_document(company_id, uid, doc_type, today, documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=cust_a, currency_id=company.base_currency_id, warehouse_id=wh,
        channel_code=channel_code if doc_type.startswith("SALES") else None))
    documents_service.add_line(doc, company_id, item_id=item_a, uom_id=pcs, quantity=D(2), quantity_base=D(2), unit_price=D(10))
    return doc


def request_of(doc_id, user=uid):
    return next((w for w in inbox.my_requests(company_id, user) if w.key == f"MYDOC:{doc_id}"), None)


def states(item):
    return [(label, state) for label, state in item.path]


# ===== ۱) برچسب‌ها: فروش «حواله»، خرید «رسید» =====
check(operational_tasks.kind_label("GOODS_RECEIPT", "SALES_ORDER") == "تایید حواله انبار"
      and operational_tasks.kind_label("GOODS_RECEIPT", "PURCHASE_ORDER") == "تایید رسید انبار", "warehouse task label by document type")
check(operational_tasks.kind_label("POST_ORDER", "SALES_ORDER") == "ثبت نهایی سفارش (پیش از حواله)"
      and operational_tasks.kind_label("POST_ORDER", "PURCHASE_ORDER") == "ثبت نهایی سفارش (پیش از رسید)", "post-order label by type")

# ===== ۲) تنظیمات پیش‌فرض: پیش‌نویس نه، سفارش ثبت‌شده بله =====
so = order()
check(request_of(so) is None, "a draft is not shown as an issued request")
documents_service.confirm_document(so, company_id, uid)
r = request_of(so)
check(r is not None and r.tone == "mine" and r.source == "MINE", "confirmed sales order appears in the issuer's requests")
check(states(r) == [("ثبت سفارش", "done"), ("تبدیل به فاکتور", "current")] and r.subtitle == "منتظر: شما",
      f"default path: only conversion left, waiting on the issuer ({states(r)})")
check(request_of(so, keeper) is None, "other users do not see someone else's order")
d = inbox.detail(company_id, uid, r.key)
check(d["path"] == r.path and dict(d["context"])["مرحلهٔ جاری"] == "تبدیل به فاکتور", "detail panel shows stage and path")
check(raises(lambda: inbox.withdraw(company_id, uid, r.key), "خود سند"), "withdraw explains that the order is cancelled from the document")
documents_service.convert_to_invoice(so, company_id, uid, today)
check(request_of(so) is None, "fully invoiced order leaves the in-progress list")

# ===== ۳) تصویب مدیر =====
cs.set_feature_enabled(company_id, "SALES_ORDER_MANAGER_APPROVAL", True)
so2 = order()
documents_service.confirm_document(so2, company_id, uid)
r = request_of(so2)
check(states(r)[1] == ("تصویب مدیر", "current") and r.subtitle == "منتظر: مدیر", "waiting on the manager's approval")
documents_service.approve_document(so2, company_id, uid)
check(states(request_of(so2))[1] == ("تصویب مدیر", "done") and request_of(so2).status_note == "تبدیل به فاکتور", "after approval")
cs.set_feature_enabled(company_id, "SALES_ORDER_MANAGER_APPROVAL", False)
documents_service.convert_to_invoice(so2, company_id, uid, today)

# ===== ۴) حوالهٔ انبار با انباردار مشخص =====
cs.set_feature_enabled(company_id, "SALES_ORDER_WAREHOUSE_ISSUE", True)
so3 = order(wh=wh2)
documents_service.confirm_document(so3, company_id, uid)
check([lbl for lbl, _s in request_of(so3).path] == ["ثبت سفارش", "ثبت نهایی", "حواله انبار", "تبدیل به فاکتور"]
      and request_of(so3).status_note == "ثبت نهایی", "warehouse issue flow: post first")
documents_service.post_document(so3, company_id, uid)
r = request_of(so3)
check(r.status_note == "حواله انبار" and r.subtitle == "منتظر: ویزیتور یک", f"waiting on the named warehouse keeper ({r.subtitle})")
task = next((w for w in inbox.my_work(company_id, keeper) if w.source == "DOC" and w.ref_id == so3), None)
check(task is not None and task.kind_label == "تایید حواله انبار" and task.action == "حواله انبار را تایید کنید",
      "keeper's task says «حواله», not «رسید/حواله»")
documents_service.approve_warehouse(so3, company_id, keeper)
check(request_of(so3).status_note == "تبدیل به فاکتور", "after the warehouse issue only conversion is left")
cs.set_feature_enabled(company_id, "SALES_ORDER_WAREHOUSE_ISSUE", False)

# ===== ۵) سفارش خرید هم =====
po = order("PURCHASE_ORDER")
documents_service.confirm_document(po, company_id, uid)
r = request_of(po)
check(r is not None and ("تصویب مدیر", "current") in states(r), "purchase order (manager approval on by default) in requests")

# ===== ۶) موبایل و دسکتاپ =====
from peecha_api.main import app as api
client = TestClient(api)
token = client.post("/auth/login", json={"username": "admin", "password": "secret123"}).json()["access_token"]
reqs = client.get("/workflow/inbox", headers={"Authorization": "Bearer " + token}).json()["requests"]
m = next((q for q in reqs if q["key"] == f"MYDOC:{so3}"), None)
check(m and m["definition"] == "مراحل سفارش" and m["path"] and m["action"].startswith("منتظر"), "mobile «درخواست‌های من» shows the order")

from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)
from peecha.ui.screens.my_tasks import MyTasksScreen


class _MW:
    def __init__(self):
        self.opened = []

    def open_screen(self, code, then=None):
        self.opened.append(code)


mw = MyTasksScreen(_MW())
mw.refresh()
mw.set_view("MINE")
check(f"MYDOC:{so3}" in mw.cards_by_key, "desktop cartable lists the order under «درخواست‌های من»")
mw.select_key(f"MYDOC:{so3}")
check(not mw.buttons["withdraw"].isEnabled() and not mw.buttons["remind"].isEnabled() and mw.buttons["open"].isEnabled(),
      "only «بازکردن سند» is offered for an order")
check(mw.open_selected() and mw._main_window.opened == ["SALES_ORDER"], "open button opens the sales order form")

fx.finish()
