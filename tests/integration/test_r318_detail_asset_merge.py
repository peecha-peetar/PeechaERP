"""R318: دارایی ثابت در فرم تعریف تفصیلی (مثل کالا)، انتقال ماندهٔ تفصیلی با سند و ادغام کامل گردش (برگشت‌پذیر،
با دسترسی و کلید جدا)."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r318"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.services import commercial_partners as partners
from peecha.services import detail_operations as ops
from peecha.services import journal_entries as je
from peecha.services import roles as roles_service
from peecha.services import users as users_service
from peecha.db.models.accounting import DetailAccount, DetailMergeRow, DetailOperation, JournalEntryLineDetail
from peecha.db.models.audit import ActivityLog

# --- حساب‌ها و تفصیلی‌ها ---------------------------------------------------------------------------------
person_type = dimensions_service.get_person_dimension_type_id(company_id)
cc_type = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.COST_CENTER_CODE)
g_ar = A("13", "دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
ar = A("131", "حساب‌های دریافتنی", "DEBIT", "ASSET", "PERMANENT", True, g_ar.account_id)
prepaid = A("132", "پیش‌پرداخت پروژه‌ای", "DEBIT", "ASSET", "PERMANENT", True, g_ar.account_id)
g_rev = A("4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False)
k_rev = A("41", "فروش", "CREDIT", "REVENUE", "TEMPORARY", False, g_rev.account_id)
rev = A("411", "فروش کالا", "CREDIT", "REVENUE", "TEMPORARY", True, k_rev.account_id)
dimensions_service.set_account_dimension_types(ar.account_id, company_id, [person_type])
dimensions_service.set_account_dimension_types(prepaid.account_id, company_id, [person_type, cc_type])
cc1 = dimensions_service.create_detail_account(company_id, cc_type, "901", name="مرکز فروش").detail_account_id

cust = {code: partners.create_customer_detail_account(company_id, code, name) for code, name in
        (("C-A", "مشتری الف"), ("C-B", "مشتری ب"), ("C-C", "مشتری ج"), ("C-D", "مشتری د"))}


def post(customer, amount, with_cc=False):
    account = prepaid if with_cc else ar
    details = {person_type: cust[customer]}
    if with_cc:
        details[cc_type] = cc1
    return je.create_journal_entry(company_id, uid, today, "فروش آزمایشی", [
        je.LineInput(account.account_id, "بدهکار", D(amount), D(0), details),
        je.LineInput(rev.account_id, "بستانکار", D(0), D(amount), {})]).journal_entry_id


post("C-A", "1000")
post("C-A", "300", with_cc=True)
post("C-A", "200")
post("C-C", "700")

# --- ۹-الف: انتقال مانده با سند ----------------------------------------------------------------------
check(raises(lambda: ops.transfer_balance(company_id, uid, cust["C-A"], cust["C-B"], today), "خاموش"),
      "transfer is blocked while its switch is off")
engine_service.set_feature_enabled(company_id, ops.FEATURE_TRANSFER, True)
rows = ops.balances(company_id, cust["C-A"])
check(len(rows) == 2 and sorted(r.balance_base for r in rows) == [D("300"), D("1200")],
      f"balance per account and accompanying cost center ({[(r.account_label, r.balance_base) for r in rows]})")
check(any(r.others == ((cc_type, cc1),) and "مرکز فروش" in r.others_label for r in rows), "cost center kept with the balance")
check(raises(lambda: ops.transfer_balance(company_id, uid, cust["C-A"], cust["C-A"], today), "یکی"), "same source and target rejected")
check(raises(lambda: ops.transfer_balance(company_id, uid, cust["C-A"], cc1, today), "یک گروه"), "different groups rejected")
res = ops.transfer_balance(company_id, uid, cust["C-A"], cust["C-B"], today)
check(res.line_count == 4 and not ops.balances(company_id, cust["C-A"]), "source balance cleared by one journal entry")
moved = ops.balances(company_id, cust["C-B"])
check(sorted(r.balance_base for r in moved) == [D("300"), D("1200")] and any(r.others == ((cc_type, cc1),) for r in moved),
      "target received the same balances with the same cost center")
lines = je.get_journal_entry_lines(res.journal_entry_id)
check(sum(l.debit for l in lines) == sum(l.credit for l in lines) == D("1500"), "transfer entry is balanced")
check(raises(lambda: ops.transfer_balance(company_id, uid, cust["C-A"], cust["C-B"], today), "مانده‌ای ندارد"),
      "nothing left to transfer")
opsl = ops.list_operations(company_id, cust["C-A"])
check(len(opsl) == 1 and opsl[0].type_label == "انتقال مانده" and opsl[0].status_label == "انجام‌شده", "operation history")
with new_session() as s:
    audit_rows = s.scalars(select(ActivityLog).where(ActivityLog.entity_type == "DetailAccount",
                                                     ActivityLog.entity_id == cust["C-A"])).all()
check(any(a.changes.get("operation") == "BALANCE_TRANSFER" for a in audit_rows), "transfer recorded in the audit log")
rev_res = ops.reverse(company_id, uid, res.operation_id)
check(rev_res.reversal_entry_id and sorted(r.balance_base for r in ops.balances(company_id, cust["C-A"])) == [D("300"), D("1200")]
      and not ops.balances(company_id, cust["C-B"]), "reversal entry puts the balance back")
check(ops.list_operations(company_id, cust["C-A"])[0].status_code == "REVERSED", "operation marked reversed")
check(raises(lambda: ops.reverse(company_id, uid, res.operation_id), "قبلاً"), "cannot reverse twice")

# --- دسترسی جدا ----------------------------------------------------------------------------------------
clerk = users_service.create_user("clerk318", "کاربر ساده", "secret123", None, lang_id, False, [company_id], company_id)
check(raises(lambda: ops.transfer_balance(company_id, clerk.user_id, cust["C-A"], cust["C-B"], today), "دسترسی"),
      "user without the transfer permission is refused")
forms = {f.code for f in roles_service.list_forms()}
check({ops.FORM_TRANSFER, ops.FORM_MERGE} <= forms, "two separate permissions in the roles table")

# --- ۹-ب: ادغام کامل --------------------------------------------------------------------------------------
partners.add_party_address(cust["C-C"], "OFFICE", "خیابان اول", is_default=True)
partners.add_party_address(cust["C-C"], "DELIVERY", "انبار شرق")
partners.add_party_address(cust["C-D"], "OFFICE", "خیابان دوم", is_default=True)
check(raises(lambda: ops.merge(company_id, uid, cust["C-C"], cust["C-D"]), "خاموش"), "merge blocked while its switch is off")
engine_service.set_feature_enabled(company_id, ops.FEATURE_MERGE, True)
pv = ops.merge_preview(company_id, cust["C-C"], cust["C-D"])
counts = dict(pv.counts)
check(counts.get("ردیف‌های سند حسابداری") == 1 and counts.get("آدرس‌ها") == 2 and pv.balance_rows == 1,
      f"merge preview lists what will move ({pv.counts})")
check("پروندهٔ مشتری" in pv.one_to_one, "one-to-one records flagged in the preview")
mr = ops.merge(company_id, uid, cust["C-C"], cust["C-D"], "مشتری تکراری")
with new_session() as s:
    c_det = s.get(DetailAccount, cust["C-C"])
    on_target = s.scalar(select(func.count()).select_from(JournalEntryLineDetail)
                         .where(JournalEntryLineDetail.detail_account_id == cust["C-D"]))
    logged = s.scalar(select(func.count()).select_from(DetailMergeRow).where(DetailMergeRow.operation_id == mr.operation_id))
addresses = partners.list_party_addresses(cust["C-D"])
check(not c_det.is_active and on_target == 1, "turnover moved to the target and the source deactivated")
check(len(addresses) == 2 and {a.line1 for a in addresses} == {"خیابان دوم", "انبار شرق"},
      "non-conflicting address moved, duplicate default kept on the source")
check(mr.moved == logged and mr.kept_on_source >= 2, f"every moved row logged ({mr.moved}/{logged}, kept {mr.kept_on_source})")
check(sum(r.balance_base for r in ops.balances(company_id, cust["C-D"])) == D("700") and not ops.balances(company_id, cust["C-C"]),
      "balance follows the merge")
check(raises(lambda: ops.merge(company_id, uid, cust["C-C"], cust["C-D"]), "غیرفعال"), "inactive source cannot merge again")
check(raises(lambda: ops.merge(company_id, clerk.user_id, cust["C-B"], cust["C-D"]), "دسترسی"), "merge needs its own permission")
rr = ops.reverse(company_id, uid, mr.operation_id)
with new_session() as s:
    c_det = s.get(DetailAccount, cust["C-C"])
check(c_det.is_active and rr.restored == mr.moved and rr.not_restored == 0, "merge fully reversed and the source reactivated")
check(len(partners.list_party_addresses(cust["C-C"])) == 2 and sum(r.balance_base for r in ops.balances(company_id, cust["C-C"])) == D("700"),
      "addresses and balance back on the source")
inv_type = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.INVENTORY_ITEM_CODE)
i1 = dimensions_service.create_detail_account(company_id, inv_type, "IT-1", name="کالای الف").detail_account_id
i2 = dimensions_service.create_detail_account(company_id, inv_type, "IT-2", name="کالای ب").detail_account_id
check(raises(lambda: ops.merge_preview(company_id, i1, i2), "کالا"), "items are not merged (stock ledger stays consistent)")

# --- رابط کاربری -----------------------------------------------------------------------------------------
from PySide6.QtWidgets import QApplication, QPushButton
import re

app = QApplication.instance() or QApplication([])
from peecha.ui import app_style

app_style.install(app)
from peecha.services.fixed_assets import assets as fa
from peecha.services.fixed_assets import detail_form as asset_form
from peecha.ui.screens.detail_dimensions import DetailDimensionsScreen
from peecha.ui.screens.detail_operations_dialog import DetailOperationsDialog

_LETTERS = re.compile(r"[A-Za-z\u0600-\u06FF]{2,}")


def text_buttons(root):
    return [b.text() for b in root.findChildren(QPushButton) if _LETTERS.search(b.text() or "")]


fa_type = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.FIXED_ASSET_CODE)
scr = DetailDimensionsScreen()
scr.refresh()
scr.select_type_for_new_entry(("dim", fa_type))
check(scr.asset_detail_panel is None or not scr.asset_detail_panel.isVisible(),
      "fixed asset group keeps the plain detail form while its switch is off")
engine_service.set_feature_enabled(company_id, asset_form.FEATURE, True)
scr.select_type_for_new_entry(("dim", fa_type))
panel = scr.asset_detail_panel
check(panel is not None and not panel.isHidden(), "asset panel shown inside the detail form (like items)")
from PySide6.QtWidgets import QLabel

captions = {l.text() for l in panel.findChildren(QLabel) if l.objectName() == "fieldCaption"}
need = {"طبقهٔ دارایی", "نوع", "برند", "مدل", "شمارهٔ سریال", "شمارهٔ قطعه", "بارکد", "روش استهلاک", "عمر مفید (خالی = پیش‌فرض)",
        "ارزش اسقاط", "محل", "مرکز هزینه", "پروژه", "تحویل‌گیرنده", "شعبه", "دپارتمان", "تامین‌کننده", "تاریخ تحصیل",
        "شمارهٔ فاکتور", "ارز خرید", "مرکز کار", "ساعت استاندارد سالانه", "قیمت خرید", "حساب طرف مقابل", "یادداشت"}
check(need <= captions, f"all asset fields present and labelled (missing {sorted(need - captions)})")
check(not panel.cost_box.isHidden(), "acquisition cost section offered for a new asset")
scr.account_code_field.setText("FA-100")
scr.account_name_field.setText("لیفتراک")
panel.w["brand"].setText("تویوتا")
panel.w["serial_no"].setText("SN-77")
panel.w["cost_center_detail_account_id"].setCurrentIndex(panel.w["cost_center_detail_account_id"].findData(cc1))
scr._save_account()
assets_now = [a for a in fa.list_assets(company_id) if a.asset_code == "FA-100"]
check(len(assets_now) == 1, f"saving the detail form created the asset ({scr.account_status_label.text()!r})")
asset = fa.get_asset(company_id, assets_now[0].asset_id) if assets_now else None
with new_session() as s:
    det = s.get(DetailAccount, asset.detail_account_id) if asset else None
check(det is not None and det.code == "FA-100" and det.name == "لیفتراک" and det.dimension_type_id == fa_type
      and asset.brand == "تویوتا" and asset.serial_no == "SN-77" and asset.cost_center_detail_account_id == cc1,
      "one detail account linked to the asset with the same code, name and fields")
check(asset is not None and asset.status_code == "DRAFT", "asset starts as draft (financial steps stay in the assets center)")
scr.edit_detail_account(asset.detail_account_id)
check(not scr.asset_detail_panel.isHidden() and scr.asset_detail_panel.w["brand"].text() == "تویوتا"
      and scr.asset_detail_panel.cost_box.isHidden(), "editing loads the asset fields; cost entry only at definition")
scr.asset_detail_panel.w["model"].setText("8FD25")
scr.account_name_field.setText("لیفتراک برقی")
scr._save_account()
asset = fa.get_asset(company_id, asset.asset_id)
with new_session() as s:
    det = s.get(DetailAccount, asset.detail_account_id)
check(asset.model == "8FD25" and asset.name == "لیفتراک برقی" and det.name == "لیفتراک برقی",
      "edit updates asset and detail together")
check(raises(lambda: asset_form.create(company_id, uid, "FA-100", "تکراری", fa.AssetFields("", "", asset.category_id)), "تکراری")
      or raises(lambda: asset_form.create(company_id, uid, "FA-100", "تکراری", fa.AssetFields("", "", asset.category_id)), "کد"),
      "duplicate code refused before anything is saved")
check(len([a for a in fa.list_assets(company_id) if a.name == "تکراری"]) == 0, "failed definition leaves nothing behind")
check(not text_buttons(scr.asset_detail_panel), f"asset panel uses icon buttons only ({text_buttons(scr.asset_detail_panel)})")
check(scr.detail_ops_button.isHidden(), "no transfer/merge button on assets (their own ledger)")

# دکمهٔ انتقال/ادغام روی فرم و دیالوگ
scr.select_type_for_new_entry(("person", dimensions_service.CUSTOMER_GROUP_CODE))
scr.edit_detail_account(cust["C-A"])
check(not scr.detail_ops_button.isHidden(), "transfer/merge button on the detail form when a switch is on")
dlg = DetailOperationsDialog(company_id, uid, cust["C-A"], "C-A — مشتری الف")
dlg.confirm = lambda _t: True
check(dlg.balance_table.rowCount() == 2, "dialog shows the balances to transfer")
dlg.transfer_target.setCurrentIndex(dlg.transfer_target.findData(cust["C-B"]))
op_id = dlg.do_transfer()
check(op_id and not ops.balances(company_id, cust["C-A"]) and dlg.history_table.rowCount() == 2,
      f"transfer from the dialog ({dlg.status_label.text()!r})")
dlg.history_table.setCurrentCell(0, 0)
dlg.reverse_selected()
check(ops.list_operations(company_id, cust["C-A"])[0].status_code == "REVERSED" and ops.balances(company_id, cust["C-A"]),
      "reverse from the history tab")
dlg.merge_target.setCurrentIndex(dlg.merge_target.findData(cust["C-D"]))
pv = dlg.preview_merge()
check(pv is not None and dlg.preview_table.rowCount() >= 1, "merge preview table")
check(not text_buttons(dlg), f"dialog uses icon buttons only ({text_buttons(dlg)})")
engine_service.set_feature_enabled(company_id, ops.FEATURE_MERGE, False)
dlg2 = DetailOperationsDialog(company_id, uid, cust["C-A"], "C-A")
check(not dlg2.merge_button.isEnabled() and dlg2.transfer_button.isEnabled(), "each tab follows its own switch")
dlg3 = DetailOperationsDialog(company_id, clerk.user_id, cust["C-A"], "C-A")
check(not dlg3.transfer_button.isEnabled(), "tab disabled without its permission")

# تنظیمات
from peecha.ui.screens.detail_feature_settings import DetailFeatureSettingsScreen
from peecha.ui.screens.system_settings import SystemSettingsScreen

ss = SystemSettingsScreen()
coding = ss.tabs.widget(0)
check("قابلیت‌های تفصیلی" in [coding.tabText(i) for i in range(coding.count())], "switches under coding › detail features")
fs = DetailFeatureSettingsScreen()
fs.refresh()
check(set(fs.toggles) == {asset_form.FEATURE, ops.FEATURE_TRANSFER, ops.FEATURE_MERGE}
      and fs.toggles[ops.FEATURE_TRANSFER].isChecked() and not fs.toggles[ops.FEATURE_MERGE].isChecked(), "three switches with state")
fs.toggles[ops.FEATURE_TRANSFER].setChecked(False)
check(not ops.is_on(company_id, ops.FEATURE_TRANSFER), "switch turns the feature off")
from peecha.ui.screens.inventory_settings import _FeatureToggleTab

inv_tab = _FeatureToggleTab()
inv_tab.refresh()
check(not (set(inv_tab._checkboxes) & {asset_form.FEATURE, ops.FEATURE_TRANSFER, ops.FEATURE_MERGE}),
      "accounting switches not duplicated in the inventory settings")

finish()
