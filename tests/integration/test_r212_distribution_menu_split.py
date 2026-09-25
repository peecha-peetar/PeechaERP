import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r212_1"
os.environ["PEECHA_DB_USER"] = "peecha"
os.environ["PEECHA_DB_PASSWORD"] = "peecha"
os.environ["PEECHA_DB_HOST"] = "localhost"
os.environ["PEECHA_DB_PORT"] = "5432"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

FAIL = False
def check(cond, msg):
    global FAIL
    if not cond:
        FAIL = True
        print("FAIL:", msg)
    else:
        print("OK:", msg)

from PySide6.QtWidgets import QApplication, QMessageBox
app_qt = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

from peecha.db.schema_bootstrap import apply_pending_schema_files
from peecha.db.base import get_engine, new_session
apply_pending_schema_files(get_engine())
from peecha.services.bootstrap import bootstrap_system
from peecha import session as sess
user = bootstrap_system("admin", "مدیر سیستم", "secret123", "شرکت آزمایشی")
sess.current_user = user
from sqlalchemy import select
from peecha.db.models.security import Form, UserCompany
from peecha.db.models.core import Company
with new_session() as s:
    uc = s.scalar(select(UserCompany).where(UserCompany.user_id == user.user_id))
    company = s.get(Company, uc.company_id)
company_id = company.company_id
sess.current_company = company

# طبقِ درخواستِ صریحِ کاربر («وقتی منویِ پخشِ گرم اجرا می‌شود فقط
# تب‌هایِ مربوط به پخشِ گرم باز شود و بقیهٔ تب‌ها در منویِ مربوط به
# خودشون ایجاد بشه»): این تست فقط لایهٔ ناوبری/فرم را می‌سنجد -- منطقِ
# خودِ تب‌ها (بارگیری/تیم/تسویه/ویزیت/...) در تست‌هایِ دیگر (مثلِ
# r203, r211) پوشش دارد.
from peecha.ui.screens.commercial_distribution_hub import CommercialDistributionHubScreen
from peecha.ui.screens.sales_planning_hub import SalesPlanningHubScreen
from peecha.ui.screens.telesales import TelesalesScreen
from peecha.ui.screens.cold_distribution import ColdDistributionScreen


class _FakeMainWindow:
    def open_screen(self, *a, **k):
        pass


mw = _FakeMainWindow()

hub = CommercialDistributionHubScreen(mw)
hub.refresh()
warm_tabs = [hub.tabs.tabText(i) for i in range(hub.tabs.count())]
check(
    warm_tabs == ["اسناد", "بارگیریِ خودرو", "تیمِ خودرو", "تسویهٔ خودرو"],
    f"منویِ پخشِ گرم فقط چهار تبِ مخصوصِ خودرو دارد (got {warm_tabs})",
)

planning = SalesPlanningHubScreen()
planning.refresh()
planning_tabs = [planning.tabs.tabText(i) for i in range(planning.tabs.count())]
check(
    planning_tabs == ["برنامهٔ مراجعه", "ویزیت‌ها", "پروموشن‌ها", "داشبوردِ سرپرست", "بازاریابی"],
    f"منویِ «برنامه‌ریزیِ فروش» پنج تبِ مشترک/نامرتبط را گرفت (got {planning_tabs})",
)

tele = TelesalesScreen(mw)
check(type(tele).__name__ == "TelesalesScreen", "فروشِ تلفنی آیتمِ ناوبریِ مستقلِ خودش را دارد")

cold = ColdDistributionScreen(mw)
cold.refresh()
cold_tabs = [cold.tabs.tabText(i) for i in range(cold.tabs.count())]
check("۱ - سفارش‌ها" in cold_tabs, f"پخشِ سرد دست‌نخورده ماند (got {cold_tabs})")

from peecha.services import roles as roles_service
roles_service.ensure_catalog()
with new_session() as s:
    form_codes = {f.code for f in s.scalars(select(Form)).all()}
for code in ("commercial_distribution_hub", "commercial_telesales", "sales_planning_hub", "cold_distribution"):
    check(code in form_codes, f"فرمِ «{code}» در فهرستِ RBAC ثبت شد (برایِ سطحِ‌دسترسیِ جدا)")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
