"""R324: «اتمام تولید» پس از «ثبت تولید» دوباره تولید نمی‌گیرد (پیش‌فرض صفر با توضیح)، و پیش از رسیدی که بهایش صفر/ناقص
می‌شود هشدار داده می‌شود؛ توضیح دکمه‌های دستور تولید."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r324_prd"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)
from prd_fixture import *  # noqa: F401,F403
import prd_fixture as fx
from peecha import numerals
from peecha.services.production import common as pc, master as pm, orders as po
check = fx.check
P = numerals.to_persian_digits

pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg,
                   default_scrap_warehouse_id=wh_scrap, auto_consumption=False)
BF, BL = pm.BomFields, pm.BomLineFields
bom = pm.create_bom_version(company_id, fg, BF(batch_size_qty=D(1)))
pm.add_bom_component(company_id, bom, BL(r1, D(2)))
receive(r1, 1000, 100)

from peecha.ui.screens import production as ui

oid = po.create_order(company_id, uid, po.OrderFields(item_id=fg, planned_qty=D(10)))
po.release_order(company_id, uid, oid)
scr = ui.OrdersScreen()
asked = []
scr.confirm = lambda text: asked.append(text) or False
scr.refresh()
scr.open_order(oid)

# --- ثبت تولید پیش از مصرف مواد: هشدار بهای صفر -------------------------------------------------------------------
w = po.zero_cost_warning(company_id, oid)
check(w and "مصرف نشده" in w, f"warning before a receipt without any material consumption ({w})")
check(not scr.action("receipt", {"quantity": D(10)}) and asked and "صفر" in asked[-1]
      and po.order_view(company_id, oid).order.produced_qty == 0, "user can stop the zero-cost receipt")

po.issue_all_remaining(company_id, uid, oid)
check(po.zero_cost_warning(company_id, oid) is None, "no warning once materials are consumed")
scr.confirm = lambda text: asked.append(text) or True
check(scr.action("receipt", {"quantity": D(10)}), "production registered")
v = po.order_view(company_id, oid)
check(v.order.produced_qty == 10 and v.outputs[0].produced_amount > 0, f"receipt carries the material cost ({v.outputs[0].produced_amount})")

# --- اتمام تولید: پیش‌فرض صفر و توضیح ---------------------------------------------------------------------------
seen = {}


def runner(dlg):
    seen["qty"] = dlg.widgets["quantity"].text()
    seen["hint"] = " ".join(lb.text() for lb in dlg.findChildren(ui.QLabel))
    return False


scr.dialog_runner = runner
scr.load_order(oid)
check(not scr.action("complete"), "complete dialog cancelled")
check(seen.get("qty") in (P("0"), "0", ""), f"«complete» does not suggest producing again ({seen.get('qty')})")
check("صفر بگذارید" in seen.get("hint", "") and P("10") in seen.get("hint", ""), "the dialog explains what to enter and shows what is done")
w2 = po.zero_cost_warning(company_id, oid)
check(w2 and "قبلاً با «ثبت تولید»" in w2, f"entering production again would be warned ({w2})")
scr.dialog_runner = None
scr.confirm = lambda text: asked.append(text) or ("قابل بازگشت" in text)
check(not scr.action("complete", {"quantity": D(10)}) and po.order_view(company_id, oid).order.produced_qty == 10,
      "complete with a duplicate quantity is stopped at the warning")
check(scr.action("complete", {"quantity": D(0)}), "complete with zero")
v = po.order_view(company_id, oid)
check(v.order.status_code == "COMPLETED" and v.order.produced_qty == 10, "completed without double production")

check("پایان کار ساخت" in scr.actions["complete"].toolTip() and "بخش‌بخش" not in scr.actions["complete"].toolTip()
      and "چند بار" in scr.actions["receipt"].toolTip(), "buttons explain receipt vs. complete")

fx.finish()
