"""R343: عکس‌برداری با موبایل از سمت API (کلاینت شبیه‌سازی‌شده، نه گوشی واقعی): ساخت درخواست از رکورد ERP، لینک امن،
بازکردن با توکن پس از ورود، رد توکن نامعتبر/منقضی/لغوشده و کاربر دیگر، نمایش مقصد درست، ارسال عکس معتبر، رد فایل
غیرعکس و بزرگ، تکمیل و پیوست به همان رکورد، دریافت فایل فقط با مجوز، ارسال تکراری بدون پیوست تکراری، قطع ارتباط و
خطای ذخیره‌سازی با امکان تلاش دوباره، لغو، رد استفادهٔ دوباره از توکن، شرکت دیگر، سقف تلاش و نرخ، مسیر اپ موبایل
(با شناسه) و منقضی‌کردن درخواست‌ها."""
import base64, datetime, io, os, sys, uuid
os.environ["PEECHA_DB_NAME"] = "peecha_test_r343_cap"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from fastapi.testclient import TestClient
from PIL import Image

from peecha.db.models.documents import DmsCaptureRequest, DmsDocument, DmsFile, DmsLink, DmsSettings
from peecha.db.models.security import Notification
from peecha.services import companies as companies_service, roles as roles_service, users as users_service
from peecha.services.dms import capture, documents as dms, storage
from peecha_api import rate_limit
from peecha_api.main import app

client = TestClient(app)


def jpeg(color="blue") -> str:
    out = io.BytesIO()
    Image.new("RGB", (80, 60), color).save(out, "JPEG")
    return base64.b64encode(out.getvalue()).decode()


def login(username):
    r = client.post("/auth/login", json={"username": username, "password": "secret123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def tok(token, action, headers=None):
    return client.post(f"/dms/capture/token/{action}", headers={**(headers or {}), "X-Capture-Token": token})


def up(token, headers, photos=None, key=None):
    return client.post("/dms/capture/token/upload", headers={**headers, "Idempotency-Key": key or uuid.uuid4().hex,
                                                             "X-Capture-Token": token},
                       json={"photos": photos or [{"name": "photo-1.jpg", "data_base64": jpeg()}]})


forms = {f.code: f.form_id for f in roles_service.list_forms()}
role = roles_service.create_role(company_id, "انبار و اسناد", None)
for form, actions in {"dms_documents": ["VIEW", "CREATE", "EDIT"], "inventory_document_receipt": ["VIEW"],
                      "inventory_documents_list": ["VIEW"]}.items():
    for action in actions:
        roles_service.set_role_permission(role.role_id, forms[form], action, True)
lang = company.default_language_id
keeper = users_service.create_user("keeper", "انباردار", "secret123", None, lang, False, [company_id], company_id)
roles_service.set_user_role(keeper.user_id, role.role_id, company_id, True)
stranger = users_service.create_user("stranger", "کاربر دیگر", "secret123", None, lang, False, [company_id], company_id)
roles_service.set_user_role(stranger.user_id, role.role_id, company_id, True)
receipt = receive(r1, 5, 1000)
with new_session() as s:
    s.merge(DmsSettings(company_id=company_id, mobile_base_url="https://erp.example.ir:8443/", storage_mode="DB", max_file_mb=1,
                        capture_minutes=10, capture_max_photos=3, expiry_reminder_days=30, keep_gps=False, text_extraction=True,
                        image_ocr=False))
    s.commit()


def new_request(user=None, **target):
    target = target or {"entity_type": "stock_document", "entity_id": receipt}
    return capture.create_request(company_id, (user or keeper).user_id, **target)


# --- ۱–۲) درخواست از رکورد ERP و لینک امن --------------------------------------------------------------------------------
req = new_request()
url = capture.mobile_url(company_id, req.token)
check(url == f"https://erp.example.ir:8443/m/capture#{req.token}" and len(req.token) >= 32,
      "the QR link carries only a random token, after # so it never reaches server or proxy logs")
with new_session() as s:
    row = s.get(DmsCaptureRequest, req.request_id)
    stored_token = row.token_hash
    note = s.scalar(select(Notification).where(Notification.type_code == "DMS_CAPTURE", Notification.user_id == keeper.user_id))
check(stored_token != req.token.encode() and len(stored_token) == 32, "only the token hash is stored")
check(note is not None and note.entity_type == "DmsCaptureRequest" and note.entity_id == req.request_id,
      "an in-app notification is created for the user's phone")
try:
    capture.create_request(company_id, keeper.user_id, entity_type="stock_document", entity_id=987654)
    missing = ""
except LookupError as exc:
    missing = str(exc)
check("پیدا نشد" in missing, "a request for a missing record is refused")
try:
    capture.create_request(company_id, keeper.user_id, entity_type="journal_entry", entity_id=1)
    denied = ""
except (PermissionError, LookupError) as exc:
    denied = str(exc)
check(denied != "", "a request for a record the user cannot see is refused")

# --- صفحهٔ وب: کد صفحه بدون داده و با سرآیندهای امن -----------------------------------------------------------------------
page = client.get("/m/capture")
check(page.status_code == 200 and "افزودن تصویر به سند" in page.text and "انبار" not in page.text
      and "nonce-" in page.headers["content-security-policy"] and page.headers["referrer-policy"] == "no-referrer"
      and page.headers["cache-control"] == "no-store", "the mobile page has no record data and strict security headers")
check('capture="environment"' in page.text and 'accept="image/*"' in page.text, "the page opens the rear camera directly")

# --- ۳–۸) بازکردن، توکن نامعتبر، بدون ورود، کاربر دیگر، مقصد درست --------------------------------------------------------
keeper_h, stranger_h, admin_h = login("keeper"), login("stranger"), login("admin")
check(tok(req.token, "open").status_code == 401, "without login the request cannot be opened")
check(tok('x' * 32, "open", keeper_h).status_code == 404, "an invalid token is refused")
check(client.post("/dms/capture/token/open", headers=keeper_h).status_code == 404, "without the token header nothing is found")
check(not any("token}" in getattr(r, "path", "") or "/m/capture/" in getattr(r, "path", "") for r in client.app.routes),
      "no route carries the token in its path, so access logs never contain it")
check(tok(req.token, "open", stranger_h).status_code == 404, "another user cannot open it")
opened = tok(req.token, "open", keeper_h)
check(opened.status_code == 200 and opened.json()["status"] == "OPENED" and opened.json()["target_kind"] == "سند انبار"
      and "رسید" in opened.json()["target_label"], f"the phone sees the right target ({opened.json()})")
check(capture.status(company_id, keeper.user_id, req.request_id).status_code == "OPENED", "the desktop sees «opened»")

# --- ۹–۱۰) رد فایل غیرعکس و بزرگ؛ درخواست پس از شکست دوباره قابل ارسال است -------------------------------------------------
pdf = base64.b64encode(b"%PDF-1.4 fake").decode()
bad = up(req.token, keeper_h, [{"name": "doc.pdf", "data_base64": pdf}])
check(bad.status_code == 422 and capture.status(company_id, keeper.user_id, req.request_id).status_code == "FAILED",
      "a non-image is refused and the request is marked failed")
fake = up(req.token, keeper_h, [{"name": "x.jpg", "data_base64": base64.b64encode(b"MZ" + b"0" * 100).decode()}])
check(fake.status_code == 422, "a file pretending to be a JPEG is refused")
big = io.BytesIO()
Image.effect_noise((1400, 1400), 90).convert("RGB").save(big, "JPEG", quality=100)
large = up(req.token, keeper_h, [{"name": "big.jpg", "data_base64": base64.b64encode(big.getvalue()).decode()}])
check(large.status_code in (413, 422) and "مگابایت" in large.text, f"an oversize photo is refused ({large.status_code})")
check(up(req.token, keeper_h, [{"name": f"p{i}.jpg", "data_base64": jpeg()} for i in range(4)]).status_code == 400,
      "more photos than allowed are refused")

# --- ۱۱–۱۴) ارسال موفق، پیوست به همان رکورد، تکرار بدون پیوست تکراری ---------------------------------------------------
key = uuid.uuid4().hex
done = up(req.token, keeper_h, [{"name": "photo-1.jpg", "data_base64": jpeg("red")}, {"name": "photo-2.png", "data_base64":
         base64.b64encode((lambda b: (Image.new("RGB", (20, 20), "green").save(b, "PNG"), b.getvalue())[1])(io.BytesIO())).decode()}], key)
check(done.status_code == 200 and done.json()["status"] == "COMPLETED" and done.json()["result_document_id"], f"upload completes ({done.text[:120]})")
doc_id = done.json()["result_document_id"]
again = up(req.token, keeper_h, key=key)
with new_session() as s:
    docs_for_receipt = s.scalar(select(func.count()).select_from(DmsLink).where(
        DmsLink.entity_type == "stock_document", DmsLink.entity_id == receipt, DmsLink.is_active.is_(True)))
check(again.status_code == 200 and again.json()["result_document_id"] == doc_id and docs_for_receipt == 1,
      "repeating the same upload (lost response) returns the same result without a duplicate attachment")
check(up(req.token, keeper_h).status_code == 409, "the used token cannot be used again for another upload")
check(tok(req.token, "open", keeper_h).status_code == 410, "nor reopened")
related = client.get("/dms/documents", params={"entity_type": "stock_document", "entity_id": receipt}, headers=keeper_h).json()
check([d["document_id"] for d in related] == [doc_id] and related[0]["file_count"] == 2, "the record lists the new document with both photos")
detail = dms.get_document(company_id, keeper.user_id, doc_id)
check(detail.versions[0].source_code == "WEB" and any(e.event_code == "CAPTURE" for e in detail.events),
      "the version is marked as from the phone and the capture is recorded")
check(capture.status(company_id, keeper.user_id, req.request_id).status_code == "COMPLETED", "the desktop sees «completed»")
file_id = related[0]["first_file_id"]
got = client.get(f"/dms/files/{file_id}", headers=keeper_h)
check(got.status_code == 200 and got.headers["content-type"] == "image/jpeg" and got.content[:3] == b"\xff\xd8\xff"
      and "sandbox" in got.headers["content-security-policy"], "the owner can download the photo with safe headers")
thumb = client.get(f"/dms/files/{file_id}", params={"thumbnail": True}, headers=keeper_h)
check(thumb.status_code == 200 and thumb.content[:3] == b"\xff\xd8\xff", "and its thumbnail")

# --- IDOR و دسترسی ------------------------------------------------------------------------------------------------------
outsider = users_service.create_user("outsider", "بی‌دسترسی", "secret123", None, lang, False, [company_id], company_id)
outsider_h = login("outsider")
check(client.get(f"/dms/files/{file_id}", headers=outsider_h).status_code == 404, "a user without access cannot download it")
check(client.get(f"/dms/documents/{doc_id}", headers=outsider_h).status_code == 404, "nor read the document")
check(client.get(f"/dms/files/{file_id}").status_code == 401, "nor anyone without login")
other = companies_service.create_company("C2", "شرکت دوم", "شرکت دوم", company.base_currency_id, lang)
lone = users_service.create_user("lone", "کاربر شرکت دوم", "secret123", None, lang, True, [other.company_id], other.company_id)
lone_h = login("lone")
check(client.get(f"/dms/files/{file_id}", headers=lone_h).status_code == 404, "even an administrator of another company cannot reach the file")

# --- ۵–۶، ۱۷) منقضی و لغو ----------------------------------------------------------------------------------------------------
expired = new_request()
with new_session() as s:
    s.get(DmsCaptureRequest, expired.request_id).expires_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)
    s.commit()
check(tok(expired.token, "open", keeper_h).status_code == 410, "an expired token is refused")
check(up(expired.token, keeper_h).status_code == 410, "and cannot upload")
cancelled = new_request()
check(tok(cancelled.token, "cancel", stranger_h).status_code == 404, "another user cannot cancel it")
check(tok(cancelled.token, "cancel", keeper_h).json()["status"] == "CANCELLED", "the requester cancels it")
check(tok(cancelled.token, "open", keeper_h).status_code == 410 and up(cancelled.token, keeper_h).status_code == 410,
      "a cancelled request cannot be opened or used")

# --- ۱۵–۱۶) قطع ارتباط و خطای ذخیره‌سازی: درخواست ناموفق، بدون ردیف یتیم، تلاش دوباره موفق ---------------------------------
flaky = new_request()
tok(flaky.token, "open", keeper_h)
real_put = storage.put
storage.put = lambda *a, **k: (_ for _ in ()).throw(OSError("disk"))
broken = up(flaky.token, keeper_h)
storage.put = real_put
with new_session() as s:
    left = s.scalar(select(func.count()).select_from(DmsDocument).where(DmsDocument.title.like("%رسید%")))
check(broken.status_code == 503 and "دوباره تلاش" in broken.json()["detail"] and "disk" not in broken.text
      and capture.status(company_id, keeper.user_id, flaky.request_id).status_code == "FAILED" and left == 1,
      "a storage failure fails the request without leaving a half-made document or leaking details")
retry = up(flaky.token, keeper_h)
check(retry.status_code == 200 and retry.json()["status"] == "COMPLETED", "a retry after the failure completes")

fs_req = new_request()
tok(fs_req.token, "open", keeper_h)
with new_session() as s:
    cfg = s.get(DmsSettings, company_id)
    cfg.storage_mode, cfg.storage_root = "FS", "/proc/peecha-not-writable"
    s.commit()
fs_fail = up(fs_req.token, keeper_h)
with new_session() as s:
    cfg = s.get(DmsSettings, company_id)
    cfg.storage_mode, cfg.storage_root = "DB", None
    s.commit()
    files_fs = s.scalar(select(func.count()).select_from(DmsFile).where(DmsFile.storage_mode == "FS"))
check(fs_fail.status_code == 422 and files_fs == 0, "an unwritable folder fails cleanly with no file rows")

# --- سقف تلاش و نرخ درخواست -------------------------------------------------------------------------------------------------
capped = new_request()
tok(capped.token, "open", keeper_h)
codes = [up(capped.token, keeper_h, [{"name": "a.pdf", "data_base64": pdf}]).status_code for _ in range(6)]
check(codes[:5] == [422] * 5 and codes[5] == 429, f"after five failed attempts the request is locked ({codes})")
rate_limit._buckets.clear()
burst = new_request()
statuses = [tok(burst.token, "capturing", keeper_h).status_code for _ in range(32)]
check(429 in statuses, "too many calls on one request are throttled")
rate_limit._buckets.clear()

# --- ۱۹) شرکت دیگر: درخواست شرکت دوم برای کاربر همان شرکت؛ رکورد شرکت دیگر پیوست نمی‌شود -------------------------------------
users_service.grant_company_access(keeper.user_id, other.company_id)
try:
    capture.create_request(other.company_id, keeper.user_id, entity_type="stock_document", entity_id=receipt)
    cross = ""
except (LookupError, PermissionError) as exc:
    cross = str(exc)
check(cross != "", "a request cannot target a record of another company")

# --- مسیر اپ موبایل (با شناسه) ----------------------------------------------------------------------------------------------
app_req = new_request()
listed = client.get("/dms/capture/requests", headers=keeper_h).json()
check(app_req.request_id in [r["request_id"] for r in listed] and all("token" not in r for r in listed),
      "the app lists the user's open requests without tokens")
check(client.post(f"/dms/capture/requests/{app_req.request_id}/open", headers=stranger_h).status_code == 404, "another user cannot open it by id")
client.post(f"/dms/capture/requests/{app_req.request_id}/open", headers=keeper_h)
client.post(f"/dms/capture/requests/{app_req.request_id}/capturing", headers=keeper_h)
app_done = client.post(f"/dms/capture/requests/{app_req.request_id}/upload", headers={**keeper_h, "Idempotency-Key": "k1"},
                       json={"photos": [{"name": "app.jpg", "data_base64": jpeg("yellow")}]})
check(app_done.status_code == 200 and app_done.json()["status"] == "COMPLETED", "the app upload completes")
with new_session() as s:
    source = s.scalar(text("SELECT v.source_code FROM doc.document_versions v WHERE v.document_id = :d"),
                      {"d": app_done.json()["result_document_id"]})
check(source == "MOBILE", "the app version is marked as from the mobile app")

# --- افزودن عکس به سند موجود (نسخهٔ جدید با حفظ فایل‌های قبلی) ---------------------------------------------------------------
add_req = new_request(document_id=doc_id)
tok(add_req.token, "open", keeper_h)
added = up(add_req.token, keeper_h)
detail = dms.get_document(company_id, keeper.user_id, doc_id)
check(added.status_code == 200 and len(detail.versions) == 2 and len(detail.versions[0].files) == 3 and len(detail.versions[1].files) == 2,
      "a photo added to an existing document makes a new version keeping the earlier files")

# --- ۲۰) منقضی‌کردن درخواست‌ها -----------------------------------------------------------------------------------------------
stale = new_request()
with new_session() as s:
    s.get(DmsCaptureRequest, stale.request_id).expires_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)
    s.commit()
check(capture.expire_due(company_id) >= 1 and capture.status(company_id, keeper.user_id, stale.request_id).status_code == "EXPIRED",
      "the periodic task expires old requests")

finish()
