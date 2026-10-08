"""R301: حذف تفصیلی از ردیف، حذف کالای اصلی همراه متغیرها، پیام دقیق «کجا استفاده شده» و اصلاحات ظاهری."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r301"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from sqlalchemy import text
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
from peecha.db.models.inventory import Item
from peecha.services import detail_deletion, item_variants, unit_conversion, warehouse_locations
check, raises = fx.check, fx.raises

app = QApplication.instance() or QApplication([])
WARN, ASK = [], []
QMessageBox.warning = staticmethod(lambda *a, **k: WARN.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: (ASK.append(a[2] if len(a) > 2 else ""), QMessageBox.Yes)[1])


def item_exists(item_id):
    with new_session() as s:
        return s.get(Item, item_id) is not None


def detail_of(item_id):
    with new_session() as s:
        return s.get(Item, item_id).item_detail_account_id


def new_item(code, name):
    return catalog_service.create_item(company_id, code, name, IF(item_kind_code="GOOD", base_uom_id=pcs, is_sellable=True))


# ===== ۱) کالای اصلی با متغیرها: همه با هم حذف می‌شوند =====
color = item_variants.create_item_attribute(company_id, "CLR", "رنگ")
red = item_variants.add_item_attribute_value(color, "R", "قرمز")
blue = item_variants.add_item_attribute_value(color, "B", "آبی")
shirt = new_item("SH1", "پیراهن")
variants = item_variants.generate_item_variants(company_id, shirt, {color: [red, blue]})
check(len(variants) == 2, "two variants generated")
check(raises(lambda: catalog_service.delete_item(shirt, company_id), "متغیر"), "parent alone is refused with a clear reason")
p = detail_deletion.plan(company_id, detail_of(shirt), "پیراهن")
check(p.variant_count == 2 and "همهٔ متغیرهایش" in p.confirm_text, "confirmation says variants go too")
warehouse_locations.save_storage_profile(company_id, variants[0], warehouse_locations.StorageProfile(is_fragile=True))
detail_deletion.delete(company_id, detail_of(shirt))
check(not item_exists(shirt) and not any(item_exists(v) for v in variants), "parent and all variants deleted")
with new_session() as s:
    check(not s.execute(text("SELECT 1 FROM inv.item_storage_profiles WHERE item_id = ANY(:v)"), {"v": variants}).first(),
          "item-owned definitions removed with the item")

# ===== ۲) کالای استفاده‌شده: پیام دقیق که کجا =====
used = new_item("U1", "کالای استفاده‌شده")
doc = documents_service.create_document(company_id, uid, "SALES_ORDER", today, documents_service.DocumentHeaderFields(
    counterparty_detail_account_id=cust_a, currency_id=company.base_currency_id, warehouse_id=warehouse_id, channel_code=channel_code))
documents_service.add_line(doc, company_id, item_id=used, uom_id=pcs, quantity=D(1), quantity_base=D(1), unit_price=D(10))
usage = catalog_service.item_usage(company_id, used)
check(usage == [("ردیف اسناد خرید و فروش", 1)], f"where-used lists the sales line ({usage})")
WARN.clear()
try:
    detail_deletion.delete(company_id, detail_of(used))
    msg = ""
except ValueError as exc:
    msg = str(exc)
check("ردیف اسناد خرید و فروش" in msg and "۱ مورد" in msg and "متوقف‌شده" in msg and item_exists(used),
      f"delete refused with the exact place ({msg})")

# کالای با بارکد واحد (پس از خام کردن اطلاعات هم می‌ماند) دیگر «جای دیگر استفاده شده» نمی‌گیرد
plain = new_item("P1", "کالای ساده")
unit_conversion.set_item_base_barcode(company_id, plain, "6260000000017")
detail_deletion.delete(company_id, detail_of(plain))
check(not item_exists(plain), "item with its own barcode deletes cleanly")

# متغیر تنها هم از ردیف قابل حذف است و کالای اصلی دوباره قابل‌معامله می‌شود
cap = new_item("CP1", "کلاه")
(only,) = item_variants.generate_item_variants(company_id, cap, {color: [red]})
detail_deletion.delete(company_id, detail_of(only))
check(not item_exists(only) and catalog_service.get_item(cap).is_sellable, "single variant deleted; parent sellable again")

# ===== ۳) دکمه‌های ویرایش و حذف روی ردیف فهرست «تفصیلی‌ها» و دیالوگ فرم تعریف =====
from peecha.ui.screens.detail_accounts_list import DetailAccountsListScreen
from peecha.ui.screens.detail_dimensions import DetailDimensionsScreen
from PySide6.QtWidgets import QTreeWidgetItemIterator


class _MW:
    def __init__(self):
        self.opened = []

    def open_screen(self, code, then=None):
        self.opened.append(code)


def row_buttons(tree):
    out = {}
    it = QTreeWidgetItemIterator(tree)
    while it.value():
        w = tree.itemWidget(it.value(), tree.columnCount() - 1)
        if w is not None:
            out[it.value().text(1)] = [b for b in w.findChildren(QPushButton)]
        it += 1
    return out


cc = dimensions_service.create_cost_center(company_id, "901", "مرکز هزینهٔ آزمایشی") if hasattr(dimensions_service, "create_cost_center") else None
mw = _MW()
lst = DetailAccountsListScreen(mw)
lst.refresh()
rb = row_buttons(lst.tree)
check(rb.get("فروشگاه الف") and [b.toolTip() for b in rb["فروشگاه الف"]] == ["ویرایش", "حذف"], "edit/delete buttons on each list row")
rb["فروشگاه الف"][0].click()
check(mw.opened == ["GL_DIM"], "edit button opens the detail form")
gone = new_item("G1", "کالای حذفی")
lst.refresh()
ASK.clear()
row_buttons(lst.tree)["کالای حذفی"][1].click()
check(ASK and not item_exists(gone) and "کالای حذفی" not in row_buttons(lst.tree), "delete button deletes from the list row")

form = DetailDimensionsScreen()
form.refresh()
item_group = next(i for i in range(form.group_combo.count()) if form.group_combo.itemText(i) in ("کالا", "کالا و خدمت")
                  or "کالا" in form.group_combo.itemText(i))
form.group_combo.setCurrentIndex(item_group)
form._rebuild_accounts_tree()
pb = row_buttons(form.accounts_table)
check(pb.get("کالای الف") and len(pb["کالای الف"]) == 2, "edit/delete buttons in the detail form picker rows")
pb["کالای الف"][0].click()
check(form._editing_account_id is not None and "کالای الف" in form.account_name_field.text(), "picker edit button loads the record")

# ===== ۴) فرم تعریف تفصیلی: هدر فشرده، بخش خالی پنهان =====
form.show()
app.processEvents()
check(form.extra_fields_label.isHidden() and form._extra_fields_widget.isHidden(), "empty custom-fields section takes no space")
check(form.account_form_title.parentWidget() is form.level_info_label.parentWidget()
      and abs(form.account_form_title.y() - form.level_info_label.y()) < 12, "form title and level info share one row")
form.hide()

# ===== ۵) دکمه‌های پایین فرم سمت راست؛ تول‌تیپ خوانا =====
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from peecha.ui import theme
from peecha.ui.widgets import build_action_footer, FormScreenBase
host = QWidget()
host.setLayoutDirection(Qt.RightToLeft)
host.resize(800, 80)
from PySide6.QtWidgets import QVBoxLayout
QVBoxLayout(host).addWidget(build_action_footer([QPushButton("💾"), QPushButton("🗑️")]))
host.show()
app.processEvents()
btns = host.findChildren(QPushButton)
check(all(b.mapTo(host, b.rect().topLeft()).x() > 400 for b in btns), "action footer buttons sit on the right in RTL")
fsb = FormScreenBase()
check(not fsb.footer.testAttribute(Qt.WA_SetLayoutDirection), "form footer no longer forced left-to-right")
host.hide()
theme.set_theme_mode(app, False)
check("TOOLTIP_TEXT" in theme._LIGHT_TOKENS and theme._LIGHT_TOKENS["TOOLTIP_BG"].upper().startswith("#F"),
      "light theme uses a light tooltip with dark text")
check("padding: 0px 4px" in app.styleSheet() and "border-radius: 0px" in app.styleSheet().split("QToolTip")[1][:200],
      "compact square tooltip (no dark rounded corners)")

# ===== ۶) کارتابل: هدر و فوتر ثابت =====
from peecha.ui.screens.my_tasks import MyTasksScreen
check(MyTasksScreen.scroll_in_mdi is False, "cartable is not wrapped in one big scroll area")
cart = MyTasksScreen()
cart.resize(1200, 620)
cart.show()
cart.refresh()
app.processEvents()
foot = cart.buttons["approve"]
check(foot.isVisible() and foot.mapTo(cart, foot.rect().bottomLeft()).y() <= cart.height(), "cartable footer stays visible in a short window")
cart.hide()

# ===== ۷) نقشهٔ انبار: اطلاعات بیرون از نقشه، ترتیب رسم سه‌بعدی مستقل از زاویه =====
from types import SimpleNamespace as NS
from peecha.ui.screens.warehouse_3d import Warehouse3DView
v3 = Warehouse3DView()
v3.resize(900, 600)
v3.show()
boxes = [NS(location_id=1, level="AREA", code="Z1", x=0, y=0, z=0, w=400, d=300, h=0, status="ACTIVE", active=True),
         NS(location_id=2, level="RACK", code="R1", x=50, y=50, z=0, w=200, d=40, h=60, status="ACTIVE", active=True)]
parents = {1: None, 2: 1}
lid = 3
for lv in range(3):
    shelf = lid
    boxes.append(NS(location_id=shelf, level="SHELF", code=f"L{lv}", x=50, y=50, z=lv * 20, w=200, d=40, h=20, status="ACTIVE", active=True))
    parents[shelf] = 2
    lid += 1
    for b in range(4):
        boxes.append(NS(location_id=lid, level="BIN", code=f"B{lv}{b}", x=50 + b * 50, y=50, z=lv * 20, w=50, d=40, h=20,
                        status="ACTIVE", active=True))
        parents[lid] = shelf
        lid += 1
v3.set_data(boxes, info={b.location_id: f"<b>{b.code}</b><br>خط دوم<br>خط سوم<br>خط چهارم" for b in boxes},
            parents=parents)
ok = True
for az in range(0, 360, 15):
    v3.azimuth_slider.setValue(az)
    order = [b.location_id for b, _c in v3._draw_order(v3._projector())]
    pos = {x: i for i, x in enumerate(order)}
    ok = ok and order[0] == 1 and all(pos[p] < pos[c] for c, p in parents.items() if p is not None)
check(ok, "3D: container (area, rack, shelf) always drawn before its contents at every angle")
app.processEvents()
geo = v3.view.geometry()
v3.hover(boxes[-1].location_id, None)
app.processEvents()
check(v3.view.geometry() == geo and "B23" in v3.hover_label.text(), "hover info shown below the map without moving it")
check(not any(p.toolTip() for polys in v3.polygons.values() for p in polys), "no floating tooltip on the 3D map")
v3.hide()

# ===== ۸) تنظیمات: ساخت تنبل زیرتب‌ها و فهرست بخش‌ها =====
from peecha.ui.screens.system_settings import SystemSettingsScreen, _LazyPage
ss = SystemSettingsScreen()
ss.refresh()
lazy = ss.findChildren(_LazyPage)
check(len(lazy) > 40 and sum(1 for x in lazy if x.is_built()) <= 2, f"settings build only the visible page ({sum(1 for x in lazy if x.is_built())}/{len(lazy)})")
check(ss.section_list.count() == ss.tabs.count() and ss.tabs.tabBar().isHidden(), "sections listed on the side instead of an overflowing tab bar")
ss.section_list.setCurrentRow(7)
check(ss.tabs.currentIndex() == 7, "section list switches the settings section")
ss.select_tab(2)
check(ss.section_list.currentRow() == 2, "gear jump keeps the section list in sync")

# ===== ۹) سند حسابداری: عرض ستون ذخیره می‌شود، جستجوی حساب هم‌شکل بقیه =====
from PySide6.QtCore import QSettings
from peecha.ui.screens import journal_entry as je
QSettings("Peecha", "PeechaERP").remove("columnWidths/journalEntry/lines")
j1 = je.JournalEntryScreen()
j1.refresh()
j1.table.horizontalHeader().resizeSection(je._COL_ACCOUNT, 333)
j2 = je.JournalEntryScreen()
check(j2.table.columnWidth(je._COL_ACCOUNT) == 333, "manually resized row column width is remembered")
QSettings("Peecha", "PeechaERP").remove("columnWidths/journalEntry/lines")
j1.show()
app.processEvents()
row = j1._line_rows[0]
idx = next(i for i in range(1, row.account_combo.count()) if " — " in row.account_combo.itemText(i))
row.account_combo.setCurrentIndex(idx)
check(row.account_combo.currentText() == row.account_combo.itemText(idx), "selected account keeps «code — name» like other forms")
check(j1.date_field.width() >= 150 and j1.alt_number_field.width() == 130, "header fields sized to their content")
j1.hide()

# ===== ۱۰) صفحه‌بندی گزارش و دکمه‌های آیکونی =====
from peecha.ui.screens.purchase_requests import PurchaseRequestScreen
pr = PurchaseRequestScreen()
check(all(len(b.text()) <= 2 and b.toolTip() for b in pr.buttons.values()), "purchase request footer buttons are icons with tooltips")

fx.finish()
