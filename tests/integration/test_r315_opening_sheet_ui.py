"""R315: صفحهٔ «سند افتتاحیه» (offscreen) — درخت کدینگ، ورود مانده حساب ساده و تفصیلی، کالاها با مقدار و مبلغ در چند انبار،
اشخاص با سند باز خودکار، حساب افتتاحیه زنده، جستجو و «فقط دارای مانده»، ارسال/تأیید/ثبت/قفل از همین فرم با نقش‌های جدا،
نمایش فقط‌خواندنی پس از قفل، منو و ریبون و دکمه‌های آیکونی."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r315_ui"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from opn_fixture import *  # noqa: F401,F403
import opn_fixture as fx
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

check, raises = fx.check, fx.raises
app = QApplication.instance() or QApplication([])
from peecha import nav_catalog
from peecha import session as sess
from peecha.db.models.commercial import CommercialDocument
from peecha.ui.screens import opening as ui
from peecha.ui.screens.fixed_assets import set_combo

bd = oc.fmt_date
oc.save_settings(company_id, uid, clearing_gl.account_id, "BLOCK", None)
other_ar = A("133", "سایر دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", True, k_ar.account_id)
petty = A("134", "تنخواه پروژه‌ها", "DEBIT", "ASSET", "PERMANENT", True, k_ar.account_id)
dims.set_account_dimension_types(other_ar.account_id, company_id, [person_type])
dims.set_account_dimension_types(petty.account_id, company_id, [cc_type])
bt = item("BT-1", "کالای بچ‌دار", "GOOD", track_batch=True, track_expiry=True)
entry, approver, manager = user("w_entry", "OPN_ENTRY"), user("w_appr", "OPN_APPROVER"), user("w_mgr", "OPN_MANAGER")
admin_user = sess.current_user


def act_as(user_id):
    sess.current_user = admin_user if user_id == uid else type("U", (), {"user_id": user_id, "is_super_admin": False})()


class MainWindow:
    def __init__(self, screens=None):
        self.calls, self.screens = [], screens or {}

    def open_screen(self, code, then=None):
        self.calls.append(code)
        scr = self.screens.get(code)
        if then is not None and scr is not None:
            then(scr)


# ===== ۱) منو و ریبون =====
flat = {i["code"]: i for i in nav_catalog.flatten_nav_items()}
check(flat["OPN_SHEET"]["screen"] == "opn_sheet" and nav_catalog.DEFAULT_QUICK_ACCESS_BY_MODULE["OPN"][0][0] == "OPN_SHEET",
      "opening voucher form first in the menu and the ribbon")
check("opn_sheet" in {code for code, _m, _l in nav_catalog.build_form_catalog()}, "RBAC form for the voucher screen")

warnings = []
mw = MainWindow()
scr = ui.OpeningSheetScreen(mw)
scr.warn = warnings.append
act_as(manager)
scr.refresh()
check(scr.sheet is None and scr.buttons["new"].isEnabled() and not scr.buttons["post"].isEnabled(), "empty state: only «new» enabled")


def new_form(dlg):
    set_combo(dlg.widgets["fy"], fy_id)
    dlg.widgets["balance"].setDate(balance_date)
    dlg.widgets["go_live"].setDate(go_live)
    return True


scr.dialog_runner = new_form
run = scr.new_run()
check(run and scr.sheet.run.run_id == run and scr.tree.topLevelItemCount() >= 3, "voucher created from the form; chart shown as a tree")
codes = {r.code.split("-")[-1]: r for r in scr.sheet.rows}
check(codes["121"].kind_label.startswith("کالا") and codes["131"].kind == "RECEIVABLES" and codes["133"].kind == "DETAIL",
      "entry kind shown per account")

# ===== ۲) ورود مانده =====
act_as(entry)
scr.refresh()


def lines_runner(values):
    def run_(dlg):
        for code, (col, text) in values.items():
            r = dlg.row_of(code) if code is not None else 0
            dlg.set_text(r, dlg.amount_col + col, text)
        return True
    return run_


check(scr.select_account("111"), "account selected by code")
scr.dialog_runner = lines_runner({None: (0, "۱۰۶٬۰۰۰")})
check(scr.edit_account() and codes and scr._rows[cash_gl.account_id].debit == 106000, "plain account balance entered")
scr.select_account("133")
scr.dialog_runner = lines_runner({"C1": (0, "5000")})
check(scr.edit_account() and scr._rows[other_ar.account_id].debit == 5000, "person detail balance entered")
scr.select_account("134")
scr.dialog_runner = lines_runner({"CC1": (0, "3000")})
check(scr.edit_account() and scr._rows[petty.account_id].debit == 3000, "cost-center detail balance entered")

exp = bd(go_live + datetime.timedelta(days=400))
seen = {}


def items_runner(dlg):
    I = ui._ICOL
    set_combo(dlg.wh, "RM")
    r = dlg.row_of("RM-1")
    dlg.set_text(r, I["quantity"], "2")
    dlg.set_text(r, I["amount"], "۱٬۰۰۰")
    seen["unit"] = dlg.t.item(r, I["unit"]).text()
    r = dlg.row_of("BT-1")
    dlg.set_text(r, I["quantity"], "4")
    dlg.set_text(r, I["amount"], "4000")
    dlg.set_text(r, I["batch_no"], "B-7")
    dlg.set_text(r, I["expiry_date"], exp)
    dlg.t.setCurrentCell(r, 0)
    extra = dlg.add_same_item()
    seen["same"] = dlg.t.item(extra, 0).data(0x0101) == "BT-1"
    r = dlg.row_of("RM-2")
    dlg.set_text(r, I["quantity"], "2")
    dlg.set_text(r, I["amount"], "1000")
    dlg.only.setChecked(True)
    seen["visible"] = sum(1 for i in range(dlg.t.rowCount()) if not dlg.t.isRowHidden(i))
    dlg.only.setChecked(False)
    set_combo(dlg.wh, "LINE")
    seen["switched"] = len(dlg.saved_results) == 1 and dlg.row_of("RM-1") >= 0
    r = dlg.row_of("RM-1")
    dlg.set_text(r, I["quantity"], "1")
    dlg.set_text(r, I["amount"], "500")
    return True


scr.select_account("121")
scr.dialog_runner = items_runner
check(scr.edit_account(), "items dialog accepted")
check(seen["unit"] == ui.P(ui._money(D(500))) and seen["same"] and seen["visible"] == 3 and seen["switched"],
      f"unit cost computed live, extra batch line, «only with quantity», switching warehouse saves the previous one ({seen})")
check(scr._rows[inv_gl.account_id].debit == D(6500), f"inventory account = items total across warehouses ({scr._rows[inv_gl.account_id].debit})")
check(on_hand(r1, wh_rm) == 0, "nothing hits stock before final posting")


def parties_runner(values):
    def run_(dlg):
        for code, (col, text) in values.items():
            dlg.set_text(dlg.row_of(code), col, text)
        return True
    return run_


scr.select_account("131")
scr.dialog_runner = parties_runner({"C1": (2, "300000"), "C2": (3, "20000")})
check(scr.edit_account() and scr._rows[ar_gl.account_id].debit == 300000 and scr._rows[ar_gl.account_id].credit == 20000,
      "customer balances: debit and advance")
scr.select_account("211")
scr.dialog_runner = parties_runner({"S1": (3, "400000")})
check(scr.edit_account() and scr._rows[ap_gl.account_id].credit == 400000, "supplier balance")
check(not scr.sheet.closed and "بسته نیست" in scr.cards["closing"].text() and scr._rows[clearing_gl.account_id].credit == 500,
      f"opening account shows the open difference ({scr.cards['closing'].text()})")
scr.select_account("111")
scr.dialog_runner = lines_runner({None: (0, "105500")})
scr.edit_account()
check(scr.sheet.closed and "صفر" in scr.cards["closing"].text(), "voucher closes with the opening account at zero")

# جستجو، گروه و حساب افتتاحیه
scr.search.setText("131")
visible = [r for acc, r in scr._rows.items() if not scr._items[acc].isHidden()]
check({r.code.split("-")[-1] for r in visible} == {"1", "13", "131"}, "search shows the account with its parents")
scr.search.setText("")
scr.only.setChecked(True)
check(scr._items[dep_exp_gl.account_id].isHidden() and not scr._items[cash_gl.account_id].isHidden(), "«only with balance» filter")
scr.only.setChecked(False)
warnings.clear()
scr.select_account("13")
check(not scr.edit_account() and "حساب معین" in warnings[-1], "groups are totals only")
scr.select_account("391")
check(not scr.edit_account() and "خودکار بسته" in warnings[-1], "opening account is not entered by hand")
warnings.clear()

# ===== ۳) گردش از همین فرم =====
scr.confirm = lambda text: True
check(scr.buttons["submit"].isEnabled() and scr.submit(), "submitted from the form")
check(all(s == "READY" for s in scr.sheet.modules.values()), f"every part ready for review ({scr.sheet.modules})")
check(not scr.buttons["approve"].isEnabled(), "entry user has no approve action")
act_as(approver)
scr.refresh()
check(scr.approve() and all(s == "APPROVED" for s in scr.sheet.modules.values()), "approver approves from the form")
act_as(manager)
scr.refresh()
check(scr.buttons["post"].isEnabled() and scr.post() and scr.sheet.run.status_code == "POSTED", "posted from the form")
check(gl_balance(clearing_gl.account_id) == 0 and on_hand(r1, wh_rm) == 2 and on_hand(r1, wh_line) == 1, "ledger and stock updated")
with new_session() as s:
    open_items = s.scalar(select(func.count()).select_from(CommercialDocument).where(
        CommercialDocument.document_type_code.in_(("OPENING_RECEIVABLE", "OPENING_PAYABLE"))))
check(open_items == 2, "open documents for C1 and S1 only (C2 is an advance)")
check(scr.buttons["lock"].isEnabled() and scr.lock() and scr.sheet.run.status_code == "LOCKED", "locked from the form")

# ===== ۴) پس از قفل: فقط مشاهده =====
act_as(entry)
scr.refresh()
scr.select_account("133")
shown = {}


def look(dlg):
    shown["readonly"] = dlg.readonly
    return True


scr.dialog_runner = look
check(not scr.edit_account() and shown["readonly"], "after lock the balances open read-only")

# ===== ۵) دکمه‌های آیکونی =====


def _parents(w):
    out = []
    while w is not None:
        w = w.parentWidget()
        out.append(w)
    return out


own = lambda b: not any(isinstance(w, QDialog) for w in _parents(b))  # noqa: E731
texts = [b.text() for b in scr.findChildren(QPushButton) if own(b) and len(b.text()) > 3]
check(not texts, f"icon buttons only (no text buttons) {texts[:5]}")
check(not warnings, f"no unexpected warnings ({warnings})")
fx.finish()
sys.stdout.flush()
os._exit(0)
