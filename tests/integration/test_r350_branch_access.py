"""R350: محدودیت دسترسی شعبه: کاربر محدود به یک شعبه فقط اسناد همان شعبه و اسناد بی‌شعبه را در فهرست و گزارش فروش
می‌بیند، سند شعبهٔ دیگر را باز، ذخیره یا ثبت نمی‌کند، فقط انبار و شعبهٔ مجاز انتخاب می‌کند؛ کاربر بی‌محدودیت و مدیر کل
همه را می‌بینند؛ شعبهٔ شرکت دیگر پذیرفته نیست؛ تغییر دسترسی در رخدادنگار؛ فرم کاربر."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r350"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.audit import ActivityLog
from peecha.db.models.security import User
from peecha.services import branch_access, commercial_documents as docs, commercial_partners as partners, \
    commercial_settings as csettings, commercial_settlements as settlements, procurement_masters as masters, \
    purchase_reports, users

k13 = A("13", "دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
ar_gl = A("131", "دریافتنی مشتریان", "DEBIT", "ASSET", "PERMANENT", True, k13.account_id)
g_rev = A("4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False)
k41 = A("41", "درآمد عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, g_rev.account_id)
rev_gl = A("411", "فروش", "CREDIT", "REVENUE", "TEMPORARY", True, k41.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)
csettings.set_account_mapping(company_id, "SALES_REVENUE", rev_gl.account_id)

b1 = masters.save_branch(company_id, "B1", "شعبهٔ تهران")
b2 = masters.save_branch(company_id, "B2", "شعبهٔ اصفهان")
w1 = locations_service.create_warehouse(company_id, "W1", "انبار تهران", WF())
w2 = locations_service.create_warehouse(company_id, "W2", "انبار اصفهان", WF())
masters.set_warehouse_branch(company_id, w1, b1)
masters.set_warehouse_branch(company_id, w2, b2)
for wh in (w1, w2, wh_rm):
    receive(byp, 50, 100_000, wh=wh)
customer = partners.create_customer(company_id, "C1", "مشتری", fast_track=True)


def invoice(warehouse, post=True):
    d = docs.create_document(company_id, uid, "SALES_INVOICE", today, docs.DocumentHeaderFields(
        counterparty_detail_account_id=customer, currency_id=company.base_currency_id, warehouse_id=warehouse))
    docs.add_line(d, company_id, byp, pcs, D(1), D(1), unit_price=D(500_000))
    if post:
        docs.confirm_document(d, company_id, uid)
        settlements.auto_approve_settlement_plan(d, company_id, uid, [])
        docs.post_document(d, company_id, uid)
    return d


doc1, doc2, doc0 = invoice(w1), invoice(w2), invoice(wh_rm)
pending2 = invoice(w2, post=False)
docs.confirm_document(pending2, company_id, uid)
settlements.auto_approve_settlement_plan(pending2, company_id, uid, [])
with new_session() as s:
    from peecha.db.models.commercial import CommercialDocument
    branches = {d: s.get(CommercialDocument, d).branch_id for d in (doc1, doc2, doc0)}
check(branches == {doc1: b1, doc2: b2, doc0: None}, "documents take their warehouse's branch")

clerk = users.create_user("clerk", "کارمند تهران", "Clerk12345", None, None, False, [company_id], company_id)
free = users.create_user("free", "کارمند آزاد", "Free123456", None, None, False, [company_id], company_id)
check(raises(lambda: branch_access.set_user_branches(clerk.user_id, company_id, [999_999]), "شعبه"),
      "a branch of another company is refused")
branch_access.set_user_branches(clerk.user_id, company_id, [b1])
with new_session() as s:
    logged = s.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.entity_type == "UserBranch"))
check(logged == 1 and branch_access.get_user_branches(clerk.user_id, company_id) == [b1], "the access change is audited")
check(branch_access.allowed_branch_ids(company_id, free.user_id) is None
      and branch_access.allowed_branch_ids(company_id, uid) is None, "users without branches and the super admin are unrestricted")

sales = purchase_reports.PurchaseFilters(today, today, side="SALES")
admin_user = sess.current_user
with new_session() as s:
    sess.current_user = s.get(User, clerk.user_id)
    s.expunge(sess.current_user)
try:
    listed = {d.document_id for d in docs.list_documents(company_id, "SALES_INVOICE")}
    check(doc1 in listed and doc0 in listed and doc2 not in listed and pending2 not in listed,
          f"the clerk lists only their branch and branchless documents ({listed})")
    check(raises(lambda: docs.get_document(doc2, company_id), "شعبه") and docs.get_document(doc1, company_id)[0].document_id == doc1,
          "another branch's document cannot be opened")
    check(raises(lambda: docs.post_document(pending2, company_id, clerk.user_id), "شعبه"), "nor posted")
    check(raises(lambda: invoice(w2, post=False), "شعبه"), "nor created in the other branch's warehouse")
    own = invoice(w1, post=False)
    check(raises(lambda: docs.update_document_header(own, company_id, today, docs.DocumentHeaderFields(
        counterparty_detail_account_id=customer, currency_id=company.base_currency_id, warehouse_id=w2)), "شعبه"),
          "a document cannot be moved to the other branch's warehouse")
    visible = {w.warehouse_id for w in branch_access.filter_warehouses(company_id, locations_service.list_warehouses(company_id))}
    check(w1 in visible and wh_rm in visible and w2 not in visible, "only the allowed and branchless warehouses are offered")
    check([b.branch_id for b in branch_access.filter_branches(company_id, masters.list_branches(company_id))] == [b1],
          "only the allowed branch is offered")
    report = purchase_reports.purchases_by_item(company_id, sales)
    clerk_qty = sum(r[2] for r in report.rows if isinstance(r[2], (int, decimal.Decimal)))
finally:
    sess.current_user = admin_user
admin_report = purchase_reports.purchases_by_item(company_id, sales)
admin_qty = sum(r[2] for r in admin_report.rows if isinstance(r[2], (int, decimal.Decimal)))
check(clerk_qty == D(2) and admin_qty == D(3), f"the sales report shows the clerk two invoices and the admin three ({clerk_qty}, {admin_qty})")
check(doc2 in {d.document_id for d in docs.list_documents(company_id, "SALES_INVOICE")}, "the admin still sees every branch")

# فرم کاربر
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.users import UsersScreen

screen = UsersScreen()
screen.refresh()
row = next(i for i in range(screen.table.rowCount()) if screen.table.item(i, 0).data(Qt.UserRole) == clerk.user_id)
screen._on_row_clicked(row, 0)
checked = [screen.branch_list.item(i).data(Qt.UserRole) for i in range(screen.branch_list.count())
           if screen.branch_list.item(i).checkState() == Qt.Checked]
check(screen.branch_list.count() == 2 and checked == [b1], "the user form shows the branches with the allowed one checked")

finish()
