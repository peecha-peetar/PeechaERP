import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r276"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from prd_fixture import *  # noqa: F401,F403
import prd_fixture as fx
from peecha.services import detail_dimensions as dd, commercial_partners as cp
from peecha.ui.screens.detail_dimensions import DetailDimensionsScreen
check = fx.check

# ۱) تفصیلیِ چندسطحیِ مشتری: والدها، زیرمجموعه‌ها و سطح درست نمایش داده می‌شوند
person_dim = dd.get_person_dimension_type_id(company_id)
cust_group = dd.get_person_group_id(company_id, dd.CUSTOMER_GROUP_CODE)
dd.set_group_max_level_no(person_dim, company_id, 2, cust_group)
region = cp.create_customer_detail_account(company_id, dd.suggest_next_code(company_id, person_dim, 1, cust_group), "منطقهٔ شمال")
child1 = cp.create_customer_detail_account(
    company_id, dd.suggest_next_code(company_id, person_dim, 2, cust_group), "فروشگاه الف", parent_detail_account_id=region)
leaves = {r["detail_account_id"] for r in cp.list_customer_detail_accounts(company_id)}
check(region not in leaves and child1 in leaves, "pickers in documents still list only leaf customers")
all_rows = {r["detail_account_id"]: r for r in cp.list_customer_detail_accounts(company_id, all_levels=True)}
check(region in all_rows and all_rows[child1]["level_no"] == 2, "definition form gets every level")

scr = DetailDimensionsScreen()
scr.refresh()
scr.select_type_for_new_entry(("person", dd.CUSTOMER_GROUP_CODE))
check(scr.parent_combo.findData(region) >= 0, "parent that already has a child stays selectable")
scr.parent_combo.setCurrentIndex(scr.parent_combo.findData(region))
check("سطحِ 2 از 2" in scr.level_info_label.text(), "level info shows leaf level under parent")
scr.edit_detail_account(child1)
check(scr._current_level_no() == 2 and scr.parent_combo.currentData() == region, "editing a level-2 customer keeps its level")
check(scr.person_fields_label.isVisibleTo(scr), "leaf customer shows its fields on edit")
scr.show_all_levels_checkbox.setChecked(True)
scr._rebuild_accounts_tree()
top = scr.accounts_table.topLevelItem(0)
check(top is not None and top.data(0, 0x0100) == region and top.childCount() == 1, "picker shows tree with parent and child")
scr.picker_search_field.setText("الف")
check(scr.accounts_table.topLevelItemCount() == 1 and scr.accounts_table.topLevelItem(0).childCount() == 1,
      "picker search keeps the ancestor of a match")
scr.picker_search_field.setText("")
code_err = ""
try:
    cp.create_supplier_detail_account(company_id, all_rows[region]["code"], "تکراری")
except ValueError as exc:
    code_err = str(exc)
check("قبلاً" in code_err, "duplicate code across person groups gives a clear message")
supp_group = dd.get_person_group_id(company_id, dd.SUPPLIER_GROUP_CODE)
next_code = dd.suggest_next_code(company_id, person_dim, 1, supp_group)
check(next_code not in {r["code"] for r in all_rows.values()} and next_code != "S1", "suggested code is free in the whole group")

# ۲) حذفِ امن: حذفِ ردیفِ آزاد، غیرفعال‌سازیِ ردیفِ استفاده‌شده
from peecha.services import master_data, commercial_pricing as pricing, commercial_pos as pos
from peecha.services.fixed_assets import common as fac
from peecha.db.models import fixed_assets as fam
from peecha.db.models.commercial import PriceList, PriceListItem
gid = fac.save_group(company_id, "G1", "گروهِ ۱")
fac.save_group(company_id, "G1", "گروهِ یک", group_id=gid)
check([g.name for g in fac.list_groups(company_id) if g.group_id == gid] == ["گروهِ یک"], "FA group edit")
check(master_data.delete_or_deactivate(fam.AssetGroup, gid, company_id) == master_data.DELETED, "FA group delete")
lid = fac.save_location(company_id, "L1", "اتاقِ ۱")
check(master_data.delete_or_deactivate(fam.AssetLocation, lid, company_id) == master_data.DELETED, "FA location delete")
check(fx.raises(lambda: master_data.delete_or_deactivate(fam.AssetGroup, 999999, company_id), "پیدا نشد"), "missing row message")

pricing.create_channel(company_id, "WEB", "وب", "ONLINE")
pricing.update_channel(company_id, "WEB", "فروشگاهِ وب", "ONLINE", False)
ch = next(c for c in pricing.list_channels(company_id) if c.channel_code == "WEB")
check(ch.name == "فروشگاهِ وب" and not ch.is_active, "channel update")
pl = pricing.create_price_list(company_id, "PL1", "فهرستِ ۱", "SALES", company.base_currency_id, today)
check(fx.raises(lambda: pricing.create_price_list(company_id, "PL1", "x", "SALES", company.base_currency_id, today), ""),
      "duplicate price list code rejected")
pricing.update_price_list(company_id, pl, "فهرستِ اصلی", False)
row = next(p for p in pricing.list_price_lists(company_id) if p.price_list_id == pl)
check(row.name == "فهرستِ اصلی" and not row.is_active, "price list update")
check(master_data.delete_or_deactivate(PriceList, pl, company_id, children=[(PriceListItem, "price_list_id")])
      == master_data.DELETED, "price list delete with its items")

term = pos.create_terminal(company_id, wh_fg, "T1", "صندوقِ ۱")
pos.update_terminal(company_id, term, wh_rm, "صندوقِ اصلی", False)
t = next(t for t in pos.list_terminals(company_id) if t.terminal_id == term)
check(t.name == "صندوقِ اصلی" and t.warehouse_id == wh_rm and not t.is_active, "POS terminal update")

# ۳) داشبورد: نمایِ مدیریتی + تب‌هایِ تولید/دارایی + پیوند به داشبوردهایِ ماژول
from peecha import nav_catalog
from peecha.services import dashboard as dash_service
from peecha.ui.screens.dashboard import DashboardScreen, MODULE_DASHBOARD_LINKS
overview = dash_service.executive_overview(company_id)
check(overview.inventory_value is not None and overview.open_production_orders >= 0, "executive overview service")
flat = {i["code"] for i in nav_catalog.flatten_nav_items()}
check(all(code in flat for _l, code in MODULE_DASHBOARD_LINKS), "module dashboard links point to real screens")
opened = []
class _MW:
    def open_screen(self, code, then=None):
        opened.append(code)
dash = DashboardScreen(_MW())
titles = [dash.tabs.tabText(i) for i in range(dash.tabs.count())]
check({"کلی", "تولید", "دارایی‌هایِ ثابت", "منابعِ‌انسانی"} <= set(titles), f"dashboard tabs {titles}")
errors = []
for i in range(dash.tabs.count()):
    try:
        dash.tabs.setCurrentIndex(i)
        dash.refresh()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{titles[i]}: {exc}")
check(not errors, f"every dashboard tab refreshes {errors}")
check(len(dash._overview_tab._exec_cards) == 8, "overview shows 8 executive KPIs")
dash._overview_tab.module_link_buttons[0].click()
dash._inventory_tab.link_buttons[0].click()
check(opened == ["PURCH_RPT_DASH_EXEC", "INV_RPT_DASHBOARD"], f"links open module dashboards {opened}")

fx.finish()
