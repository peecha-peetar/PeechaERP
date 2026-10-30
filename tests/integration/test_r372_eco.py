"""R372: تغییر مهندسی محصول: اعتبارسنجی ردیف‌ها، ارسال و تایید (نه توسط درخواست‌دهنده)، کارتابل، اثر تغییر (دستور باز، جزء
بی‌مصرف، بهای مواد)، اجرا با نسخهٔ جدید از تاریخ اجرا و پایان اعتبار نسخهٔ مبنا، اجرای آینده، برگشت اجرای ناموفق، مقایسه و
تاریخچه، رد و لغو؛ و فرم."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r372"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.inventory import BomHeader
from peecha.services import operational_tasks, users as users_service
from peecha.services.dms import entities
from peecha.services.production import common as pc, eco, master as pm, orders as po

staff = users_service.create_user("staff", "کارشناس", "secret123", None, company.default_language_id, False, [company_id], company_id).user_id
pc.update_settings(company_id, uid, default_material_warehouse_id=wh_rm, default_fg_warehouse_id=wh_fg)
BL = pm.BomLineFields
v1 = pm.create_bom_version(company_id, fg, pm.BomFields(batch_size_qty=D(1)))
for comp, q in ((r1, 2), (r2, 1), (pk, 1)):
    pm.add_bom_component(company_id, v1, BL(comp, D(q)))
sf_bom = pm.create_bom_version(company_id, semi, pm.BomFields(batch_size_qty=D(1)))
pm.add_bom_component(company_id, sf_bom, BL(r2, D(1)))
kit = item("FG-B", "محصول B", "FINISHED_GOOD")
kit_bom = pm.create_bom_version(company_id, kit, pm.BomFields(batch_size_qty=D(1)))
pm.add_bom_component(company_id, kit_bom, BL(fg, D(2)))
for comp, q, cost in ((r1, 100, 1000), (r2, 50, 2000), (pk, 20, 500), (r3, 30, 1500)):
    receive(comp, q, cost)
order = po.create_order(company_id, uid, po.OrderFields(item_id=fg, planned_qty=D(10), start_date=today, due_date=today))
po.plan_order(company_id, uid, order)

F, L = eco.EcoFields, eco.LineFields
lines = [L("CHANGE", base_line_no=1, new_quantity=D(3)), L("REPLACE", base_line_no=2, new_item_id=r3, new_quantity=D("1.5")),
         L("REMOVE", base_line_no=3), L("ADD", component_item_id=semi, new_quantity=D(1), notes="نیمه‌ساخته جدا")]
f = lambda title, ls, bom=v1, day=today: F(title, fg, bom, day, "COST", "کاهش وزن", "USE_UP", ls)  # noqa: E731
check(raises(lambda: eco.save_eco(company_id, staff, f("خالی", [])), "دست‌کم"), "a change needs lines")
check(raises(lambda: eco.save_eco(company_id, staff, f("x", [L("ADD", component_item_id=r1, new_quantity=D(1))])), "تغییر مقدار"),
      "adding a component already in the BOM is refused")
check(raises(lambda: eco.save_eco(company_id, staff, f("x", [L("CHANGE", base_line_no=1, new_quantity=D(2))])), "تغییری نکرده"),
      "a change must change something")
check(raises(lambda: eco.save_eco(company_id, staff, f("x", [L("REMOVE", base_line_no=1), L("CHANGE", base_line_no=1, new_quantity=D(5))])),
             "دو بار"), "one action per BOM line")
check(raises(lambda: eco.save_eco(company_id, staff, f("x", [L("REPLACE", base_line_no=1, new_item_id=r2)])), "هست"),
      "replacement cannot already be in the BOM")
check(raises(lambda: eco.save_eco(company_id, staff, f("", lines)), "عنوان"), "title is required")

e1 = eco.save_eco(company_id, staff, f("سبک‌سازی محصول A", lines), submit=True)
row = eco.get_eco(company_id, e1)
check(row.code == "ECO-0001" and row.status_code == "SUBMITTED" and [ln.old_quantity for ln in row.lines[:3]] == [D(2), D(1), D(1)],
      "saved with the old quantities from the base version")
check(not eco.can_decide(company_id, staff) and raises(lambda: eco.approve(company_id, staff, e1), "مجوز"), "staff cannot approve")
check(not [t for t in operational_tasks.list_operational_tasks(company_id, staff) if t.kind.startswith("PRD_ECO")], "nothing in the requester's inbox")
check([t.document_id for t in operational_tasks.list_operational_tasks(company_id, uid) if t.kind == "PRD_ECO_APPROVE"] == [e1],
      "the approver sees it")
check(raises(lambda: eco.implement(company_id, uid, e1), "تاییدشده"), "only an approved change is implemented")

imp = eco.impact(company_id, e1)
comps = {x.line_no: x for x in imp.components}
check([o.order_id for o in imp.orders] == [order], "open orders on the base version")
check(comps[3].obsolete and comps[3].on_hand == D(20) and not comps[2].obsolete and comps[2].used_elsewhere == 1,
      "the removed carton is left with no use; the replaced material is still used elsewhere")
check((imp.cost_before, imp.cost_after, imp.cost_delta) == (D("4500.00"), D("5250.00"), D("750.00")),
      f"material cost per unit before and after ({imp.cost_before}, {imp.cost_after})")
check([p.item_id for p in imp.parents] == [kit], "parent products that use this product")

eco.approve(company_id, uid, e1, "با تست نمونه")
check(raises(lambda: eco.approve(company_id, uid, e1), "ارسال‌شده"), "approved only once")
check(raises(lambda: eco.save_eco(company_id, staff, f("x", lines), e1), "ویرایش"), "an approved change is locked")
check([t.document_id for t in operational_tasks.list_operational_tasks(company_id, uid) if t.kind == "PRD_ECO_IMPLEMENT"] == [e1],
      "approved changes wait for implementation")
v2 = eco.implement(company_id, uid, e1)
with new_session() as s:
    b1, b2 = s.get(BomHeader, v1), s.get(BomHeader, v2)
    check(b2.version_no == 2 and b2.valid_from == today and b2.is_default and not b1.is_default
          and b1.valid_to == today - datetime.timedelta(days=1), "new version from today; the base version ends yesterday")
    check(pm.effective_bom_id(s, fg, today) == v2 and pm.effective_bom_id(s, fg, today - datetime.timedelta(days=1)) == v1,
          "effective version by date")
new = {c.item_id: c.quantity for c in pm.bom_components(company_id, v2)}
check(new == {r1: D(3), r3: D("1.5"), semi: D(1)}, f"changes applied to the new version ({new})")
with new_session() as s:
    from peecha.db.models.production import ProductionOrder
    check(s.get(ProductionOrder, order).bom_id == v1, "existing orders keep their version")
check(eco.get_eco(company_id, e1).status_code == "IMPLEMENTED" and eco.get_eco(company_id, e1).new_version == 2, "implemented")
cmp = {r.item_id: r.status_code for r in eco.compare_boms(company_id, v1, v2)}
check(cmp == {r1: "CHANGED", r2: "REMOVED", pk: "REMOVED", r3: "ADDED", semi: "ADDED"}, f"version comparison ({cmp})")
check([(h.version_no, h.eco_code) for h in eco.history(company_id, fg)] == [(1, ""), (2, "ECO-0001")], "product history")
check(raises(lambda: eco.save_eco(company_id, staff, f("دوباره", [L("REMOVE", base_line_no=1)])), "جایگزین شده"),
      "a superseded version cannot be changed again")

# اجرای آینده
later = today + datetime.timedelta(days=10)
e2 = eco.save_eco(company_id, staff, f("افزایش مادهٔ ۱", [L("CHANGE", base_line_no=1, new_quantity=D(4))], v2, later), submit=True)
eco.approve(company_id, uid, e2)
v3 = eco.implement(company_id, uid, e2)
with new_session() as s:
    check(pm.effective_bom_id(s, fg, today) == v2 and pm.effective_bom_id(s, fg, later) == v3 and s.get(BomHeader, v2).is_default
          and s.get(BomHeader, v2).valid_to == later - datetime.timedelta(days=1), "a future change takes over on its date")

# اجرای ناموفق: افزودن محصول B که خودش محصول A را دارد حلقه می‌سازد
count = len(pm.list_bom_versions(company_id, fg))
e3 = eco.save_eco(company_id, staff, f("حلقه", [L("ADD", component_item_id=kit, new_quantity=D(1))], v3, later + datetime.timedelta(days=1)),
                  submit=True)
eco.approve(company_id, uid, e3)
check(raises(lambda: eco.implement(company_id, uid, e3), "حلقه"), "an invalid change is refused by the BOM rules")
check(len(pm.list_bom_versions(company_id, fg)) == count and eco.get_eco(company_id, e3).status_code == "APPROVED",
      "the half-built version is removed and the request stays approved")
check(raises(lambda: eco.cancel(company_id, uid, e3, ""), "دلیل"), "cancel needs a reason")
eco.cancel(company_id, uid, e3, "طراحی دوباره")
check(eco.get_eco(company_id, e3).status_code == "CANCELLED", "cancelled")

# رد، اصلاح و حذف
e4 = eco.save_eco(company_id, staff, f("کارتن بزرگ‌تر", [L("ADD", component_item_id=pk, new_quantity=D(1))], v3, later + datetime.timedelta(days=2)),
                  submit=True)
check(raises(lambda: eco.reject(company_id, uid, e4, " "), "دلیل"), "rejection needs a reason")
eco.reject(company_id, uid, e4, "کارتن فعلی کافی است")
check(eco.save_eco(company_id, staff, f("کارتن بزرگ‌تر", [L("ADD", component_item_id=pk, new_quantity=D(2))], v3,
                                        later + datetime.timedelta(days=2)), e4) == e4 and eco.get_eco(company_id, e4).status_code == "DRAFT",
      "a rejected change returns to draft when edited")
eco.delete_eco(company_id, staff, e4)
check(raises(lambda: eco.get_eco(company_id, e4), "نامعتبر"), "draft deleted")
with new_session() as s:
    check(entities.describe(s, company_id, "eco", e1)[0].startswith("ECO-۰۰۰۱ — سبک"), "drawings attach to the change in documents")

# فرم
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui import report_export
from peecha.ui.screens.fixed_assets import set_combo
from peecha.ui.screens.production_eco import ProductionEcoScreen

printed = []
report_export.print_report = lambda parent, title, headers, rows, **kw: printed.append((title, len(rows)))
screen = ProductionEcoScreen()
screen.refresh()
check(screen.eco_table.rowCount() == 3, "requests listed")
screen.new_eco()
set_combo(screen.item_combo, fg)
set_combo(screen.base_combo, v3)
check(screen.base_line_combo.count() == 3, "base lines offered")
screen.title_field.setText("تغییر از فرم")
screen.effective_field.setDate(later + datetime.timedelta(days=3))
set_combo(screen.action_combo, "CHANGE")
screen.base_line_combo.setCurrentIndex(0)
screen.qty_field.setText("۵")
check(screen.add_line() and not screen.add_line(), "a BOM line is added once")
check(screen.save(True) and screen.eco_table.rowCount() == 4, f"saved from the form ({screen.status_label.text()})")
check(screen.approve() and screen.show_impact() and screen.impact_orders.rowCount() == 0, "approve and impact")
check(screen.implement() and "نسخهٔ جدید" in screen.status_label.text() and screen.compare_table.rowCount() == 3,
      f"implement and compare ({screen.status_label.text()})")
check(screen.history_table.rowCount() == 4 and screen.history_table.item(3, 6).text() == "ECO-۰۰۰۴", "history in the form")
check(screen.print_eco() and printed[-1] == ("درخواست تغییر مهندسی ECO-0004", 1), "print")
screen.ask_reason = lambda: "نیاز نیست"
screen.open_eco(e3)
check(screen.tabs.currentIndex() == 1 and screen.eco_id == e3 and not screen.reject(), "open from the inbox; a cancelled request is not rejected")
check(all(len(b.text()) <= 2 for b in screen.findChildren(QPushButton) if b.text()), "icon buttons only")

finish()
