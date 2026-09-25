import os, sys, decimal, datetime
os.environ["PEECHA_DB_NAME"] = "peecha_test_r179_1"
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
from peecha.db.models.security import UserCompany
from peecha.db.models.core import Company
with new_session() as s:
    uc = s.scalar(select(UserCompany).where(UserCompany.user_id == user.user_id))
    company = s.get(Company, uc.company_id)
company_id = company.company_id
sess.current_company = company

from peecha.services import fiscal_years as fiscal_years_service
fiscal_years_service.create_fiscal_year_for_date(company_id, 1, 1, datetime.date.today())

from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import treasury as treasury_service
from peecha.services import commercial_partners as partners_service
from peecha.services import users as users_service
from peecha.services import roles as roles_service

lang_id = company.default_language_id
g1 = coa_service.create_account(company_id, "1", "دارایی‌ها", "DEBIT", "ASSET", "PERMANENT", False, lang_id)
k1 = coa_service.create_account(company_id, "11", "صندوق", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
cash_gl = coa_service.create_account(company_id, "101", "صندوقِ اصلی", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k1.account_id)
k2 = coa_service.create_account(company_id, "13", "حساب‌هایِ دریافتنی", "DEBIT", "ASSET", "PERMANENT", False, lang_id, parent_account_id=g1.account_id)
ar_gl = coa_service.create_account(company_id, "1304", "حساب‌هایِ دریافتنیِ مشتریان", "DEBIT", "ASSET", "PERMANENT", True, lang_id, parent_account_id=k2.account_id)

customer_group_id = dimensions_service.get_person_group_id(company_id, dimensions_service.CUSTOMER_GROUP_CODE)
treasury_service.create_counterparty_mapping(company_id, "RECEIPT", ar_gl.account_id, person_group_id=customer_group_id)
treasury_service.set_account_mapping(company_id, "RECEIPT_CASH", cash_gl.account_id)

customer_id = dimensions_service.create_customer(company_id, "C-1", "مشتریِ آزمایشی")

visitor_user = users_service.create_user(
    "visitor1", "ویزیتورِ یک", "secret123", None, company.default_language_id, False, [company_id], company_id,
)

# ==========================================================================
# نقشِ RBACِ ویزیتور -- طبقِ فعال‌سازیِ تازه‌یِ roles_service.user_has_permission:
# بدونِ این نقش، ویزیتورِ غیرِمدیر دیگر حتی نباید بتواند مشتری/وصول ثبت کند.
# ==========================================================================
roles_service.ensure_catalog()
visitor_role = roles_service.create_role(company_id, "VISITOR", None)
gl_dim_form_id = next(f.form_id for f in roles_service.list_forms() if f.code == "detail_dimensions")
treasury_receipt_form_id = next(f.form_id for f in roles_service.list_forms() if f.code == "treasury_voucher_receipt")
roles_service.set_role_permission(visitor_role.role_id, gl_dim_form_id, "CREATE", True)
roles_service.set_role_permission(visitor_role.role_id, treasury_receipt_form_id, "CREATE", True)
roles_service.set_user_role(visitor_user.user_id, visitor_role.role_id, company_id, True)

from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)


def _login(username, password):
    resp = client.post("/auth/login", json={"username": username, "password": password, "device_name": "test"})
    check(resp.status_code == 200, f"ورودِ {username} موفق بود (status={resp.status_code})")
    return resp.json()["access_token"]


no_role_user = users_service.create_user(
    "norole1", "کاربرِ بدونِ نقش", "secret123", None, company.default_language_id, False, [company_id], company_id,
)

admin_token = _login("admin", "secret123")
visitor_token = _login("visitor1", "secret123")
no_role_token = _login("norole1", "secret123")


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ==========================================================================
# ۰: RBACِ واقعی -- کاربرِ بدونِ نقش (نه GL_DIM/CREATE، نه TREASURY_RECEIPT/CREATE)
# نباید بتواند مشتری بسازد یا وصول ثبت کند.
# ==========================================================================
resp = client.post("/customers", json={"code": "C-X", "name": "بدونِ‌دسترسی"}, headers=_auth(no_role_token))
check(resp.status_code == 403, f"کاربرِ بدونِ نقشِ GL_DIM/CREATE از ثبتِ مشتری منع شد (status={resp.status_code})")

resp = client.post(
    "/payments",
    json={"customer_detail_account_id": customer_id, "method_lines": [{"method": "CASH", "amount": "1000"}]},
    headers=_auth(no_role_token),
)
check(resp.status_code == 403, f"کاربرِ بدونِ نقشِ TREASURY_RECEIPT/CREATE از ثبتِ وصول منع شد (status={resp.status_code})")

# ==========================================================================
# ۱: پذیرشِ مشتری (Customer Acquisition) -- ویزیتور می‌سازد، ادمین تایید می‌کند.
# ==========================================================================
resp = client.post(
    "/customers",
    json={"code": "C-2", "name": "مشتریِ جدیدِ میدانی", "phone": "09120000000", "address": "تهران"},
    headers=_auth(visitor_token),
)
check(resp.status_code == 200, f"ثبتِ مشتریِ جدید از موبایل موفق بود (status={resp.status_code}, body={resp.text})")
new_customer_id = resp.json()["detail_account_id"]
check(resp.json()["status_code"] == "PENDING_APPROVAL", "مشتریِ تازه‌ساخته در وضعیتِ درانتظارِ تایید است")

with new_session() as s:
    from peecha.db.models.accounting import CustomerDetail
    detail = s.get(CustomerDetail, new_customer_id)
    check(detail is not None and detail.phone == "09120000000" and detail.address == "تهران", "فیلدهایِ تلفن/آدرس واقعاً ذخیره شدند")

# ویزیتور (غیرِمدیر) نباید بتواند تایید کند.
resp = client.post(f"/customers/{new_customer_id}/approve", headers=_auth(visitor_token))
check(resp.status_code == 403, f"تاییدِ مشتری توسطِ ویزیتورِ غیرِمدیر رد شد (status={resp.status_code})")

resp = client.post(f"/customers/{new_customer_id}/approve", headers=_auth(admin_token))
check(resp.status_code == 200 and resp.json()["status_code"] == "ACTIVE", "تاییدِ مشتری توسطِ ادمین موفق بود")

profile = partners_service.get_customer_profile(new_customer_id)
check(profile is not None and profile.status_code == "ACTIVE" and profile.submitted_by_user_id == visitor_user.user_id,
      "پروفایلِ مشتری واقعاً ACTIVE شد و ثبت‌کننده‌یِ اصلی حفظ شد")

# ==========================================================================
# ۲: وصول/دریافتِ وجه (Collection) از مشتریِ موجود.
# ==========================================================================
resp = client.post(
    "/payments",
    json={
        "customer_detail_account_id": customer_id,
        "method_lines": [{"method": "CASH", "amount": "150000"}],
        "customer_visit_id": 42,
    },
    headers=_auth(visitor_token),
)
check(resp.status_code == 200, f"ثبتِ وصولِ نقدی موفق بود (status={resp.status_code}, body={resp.text})")
je_id = resp.json()["journal_entry_id"]
check(je_id is not None, "شناسهٔ سندِ حسابداری برگردانده شد")

with new_session() as s:
    from peecha.db.models.accounting import JournalEntry, JournalEntryLine
    entry = s.get(JournalEntry, je_id)
    check(entry is not None, "سندِ حسابداریِ وصول واقعاً ساخته شد")
    check("بازدید #42" in (entry.description or ""), "شناسهٔ بازدید در توضیحاتِ سند حفظ شد")
    lines = s.scalars(select(JournalEntryLine).where(JournalEntryLine.journal_entry_id == je_id)).all()
    check(len(lines) == 2, "سند دقیقاً دو ردیف (طرفِ‌حساب + نقد) دارد")
    amounts = {ln.debit_amount_fc or ln.credit_amount_fc for ln in lines}
    check(decimal.Decimal("150000") in amounts, "مبلغِ وصول درست در سند ثبت شد")

# روشِ نامعتبر (مثلاً INSTALLMENT که فقط برایِ کاربردهایِ پیچیده‌ی دسکتاپ است) رد شود.
resp = client.post(
    "/payments",
    json={"customer_detail_account_id": customer_id, "method_lines": [{"method": "INSTALLMENT", "amount": "1000"}]},
    headers=_auth(visitor_token),
)
check(resp.status_code == 400, f"روشِ وصولِ نامعتبر رد شد (status={resp.status_code})")

# مشتریِ بدونِ نگاشتِ حساب (چون مشتریِ C-2 قبل از این تست نگاشتِ گروهیِ مشترکی دارد، یک تفصیلیِ غیرِمشتری امتحان می‌شود)
no_detail_id = dimensions_service.get_no_detail_account_id(company_id)
resp = client.post(
    "/payments",
    json={"customer_detail_account_id": no_detail_id, "method_lines": [{"method": "CASH", "amount": "1000"}]},
    headers=_auth(visitor_token),
)
check(resp.status_code == 400, f"طرفِ‌حسابِ بدونِ نگاشتِ حساب با خطایِ روشن رد شد (status={resp.status_code}, body={resp.text})")

# ==========================================================================
# ۳: ایدمپوتنسی -- تکرارِ همان کلید نباید سندِ دومی بسازد.
# ==========================================================================
idem_key = "test-idem-key-r179"
resp1 = client.post(
    "/payments",
    json={"customer_detail_account_id": customer_id, "method_lines": [{"method": "CASH", "amount": "5000"}]},
    headers={**_auth(visitor_token), "Idempotency-Key": idem_key},
)
resp2 = client.post(
    "/payments",
    json={"customer_detail_account_id": customer_id, "method_lines": [{"method": "CASH", "amount": "5000"}]},
    headers={**_auth(visitor_token), "Idempotency-Key": idem_key},
)
check(resp1.status_code == 200 and resp2.status_code == 200, "هردو درخواستِ ایدمپوتنت موفق برگشتند")
check(resp1.json() == resp2.json(), "پاسخِ دوم دقیقاً همانِ پاسخِ اول (بدونِ اجرایِ دوباره) بود")

with new_session() as s:
    from peecha.db.models.accounting import JournalEntry
    matching = s.scalars(
        select(JournalEntry).where(JournalEntry.company_id == company_id, JournalEntry.description.like("%وصولِ میدانی%"))
    ).all()
    # سه سند از قبل (وصولِ ۱۵۰۰۰۰ + وصولِ ایدمپوتنت که فقط یک‌بار باید ساخته شده باشد)
    cash_5000_count = sum(1 for e in matching if any(l.debit_amount_fc == decimal.Decimal(5000) or l.credit_amount_fc == decimal.Decimal(5000) for l in e.lines))
check(cash_5000_count == 1, f"با وجودِ دو درخواست، فقط یک سندِ ۵۰۰۰تومانی ساخته شد (count={cash_5000_count})")

# ==========================================================================
# ۴: Audit Log برایِ عملیاتِ حساس (ثبت/تاییدِ مشتری، ثبتِ وصول) از موبایل.
# ==========================================================================
with new_session() as s:
    from peecha.db.models.audit import ActivityLog
    actions = {
        (a.entity_type, a.action)
        for a in s.scalars(select(ActivityLog).where(ActivityLog.company_id == company_id)).all()
    }
check(("CustomerProfile", "CREATE") in actions, "ثبتِ مشتری از موبایل Audit شد")
check(("CustomerProfile", "APPROVE") in actions, "تاییدِ مشتری از موبایل Audit شد")
check(("JournalEntry", "CREATE") in actions, "ثبتِ وصول از موبایل Audit شد")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
