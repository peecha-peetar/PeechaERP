import os, sys, decimal, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r173_1"
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

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

from peecha.db.schema_bootstrap import apply_pending_schema_files
from peecha.db.base import get_engine, new_session
apply_pending_schema_files(get_engine())
from peecha import session as sess
from sqlalchemy import select
from peecha.db.models.security import UserCompany
from peecha.db.models.core import Company

# از همان دیتابیسِ تستِ قبلی (peecha_test_r173_1) که یک شرکت و یک کانالِ
# COLD-1 (نوعِ PRE_SALES) از پیش دارد استفاده می‌کند.
from peecha.services.bootstrap import bootstrap_system
with new_session() as s:
    uc = s.scalar(select(UserCompany))
    company = s.get(Company, uc.company_id)
company_id = company.company_id
sess.current_company = company

from peecha.db.models.security import User
with new_session() as s:
    user = s.get(User, uc.user_id)
    s.expunge(user)
sess.current_user = user

from peecha.ui.screens.commercial_documents_list import CommercialDocumentsListScreen

pre_sales = CommercialDocumentsListScreen(
    None, type_filter_codes=("SALES_ORDER", "SALES_INVOICE"), channel_type_code="PRE_SALES",
)
online = CommercialDocumentsListScreen(None, type_filter_codes=("SALES_ORDER",), channel_type_code="ONLINE")
generic = CommercialDocumentsListScreen(None, type_filter_codes=("SALES_ORDER", "SALES_INVOICE"))

def count_new_buttons(screen):
    return sum(1 for w in screen.findChildren(QPushButton) if w.text().startswith("➕"))

check(count_new_buttons(pre_sales) == 2, f"دکمه‌هایِ «سندِ تازه» در تبِ پخشِ سرد نمایش داده می‌شوند (got {count_new_buttons(pre_sales)})")
check(count_new_buttons(online) == 0, f"دکمه‌هایِ «سندِ تازه» در تبِ فروشِ اینترنتی (سینک‌محور) همچنان پنهانند (got {count_new_buttons(online)})")
check(count_new_buttons(generic) == 2, f"دکمه‌هایِ «سندِ تازه» در فهرستِ عمومی (بدونِ کانال) دست‌نخورده مانده‌اند (got {count_new_buttons(generic)})")

default_channel = pre_sales._default_channel_code()
check(default_channel == "COLD-1", f"کانالِ پیش‌فرضِ تبِ پخشِ سرد درست تشخیص داده شد (got {default_channel})")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
