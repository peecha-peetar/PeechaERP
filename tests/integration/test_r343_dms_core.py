"""R343: هستهٔ مدیریت اسناد: ثبت سند با فایل، رد فایل نامعتبر/ناهم‌خوان/بزرگ، دریافت با مجوز و رد بدون مجوز (IDOR)،
نسخهٔ جدید با حفظ نسخهٔ قبلی و رد نسخهٔ تکراری، پیوند به رکورد واقعی و رد رکورد ناموجود یا شرکت دیگر، تفکیک
شرکت، گردش کار تایید و رد تایید نسخهٔ قدیمی، محرمانگی، جست‌وجو و صفحه‌بندی، رد رویدادها، یادآوری انقضا بدون تکرار،
حذف GPS عکس، حالت پوشه با جلوگیری از عبور مسیر، فایل گم‌شده و پاک‌کردن فایل یتیم."""
import datetime, io, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r343"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

import tempfile
from pathlib import Path

from PIL import Image

from peecha.db.models.documents import DmsEvent, DmsFile, DmsReminder, DmsSettings
from peecha.db.models.security import Notification
from peecha.services import companies as companies_service, roles as roles_service, users as users_service
from peecha.services.dms import common as dc, documents as dms, reminders, storage

D0 = datetime.date.today()


def jpeg(color="red", gps=False, size=(64, 48)) -> bytes:
    img = Image.new("RGB", size, color)
    exif = Image.Exif()
    exif[0x0112] = 1
    if gps:
        exif[0x8825] = {1: "N", 2: (35.0, 41.0, 0.0), 3: "E", 4: (51.0, 23.0, 0.0)}
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif.tobytes())
    return out.getvalue()


PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def err(fn, exc=Exception):
    try:
        fn()
    except exc as e:  # noqa: PERF203
        return str(e)
    return ""


# --- کاربران: مدیر کل، کاربر اسناد، کاربر فقط-فاکتور، کاربر بی‌دسترسی، شرکت دوم ---------------------------------
forms = {f.code: f.form_id for f in roles_service.list_forms()}
def role_with(code, perms):
    role = roles_service.create_role(company_id, code, None)
    for form, actions in perms.items():
        for action in actions:
            roles_service.set_role_permission(role.role_id, forms[form], action, True)
    return role
lang = company.default_language_id
clerk = users_service.create_user("clerk", "کارمند اسناد", "secret123", None, lang, False, [company_id], company_id)
roles_service.set_user_role(clerk.user_id, role_with("اسناد", {"dms_documents": ["VIEW", "CREATE", "EDIT"], "journal_entry": ["VIEW"],
                                                              "dms_categories": ["VIEW", "CREATE"]}).role_id, company_id, True)
reviewer = users_service.create_user("reviewer", "بررسی‌کننده", "secret123", None, lang, False, [company_id], company_id)
roles_service.set_user_role(reviewer.user_id, role_with("بررسی", {"dms_documents": ["VIEW"], "dms_approve": ["EDIT"]}).role_id,
                            company_id, True)
sales = users_service.create_user("sales", "فروشنده", "secret123", None, lang, False, [company_id], company_id)
roles_service.set_user_role(sales.user_id, role_with("فروش", {"commercial_document_sales_invoice": ["VIEW"]}).role_id, company_id, True)
outsider = users_service.create_user("outsider", "بی‌دسترسی", "secret123", None, lang, False, [company_id], company_id)
other = companies_service.create_company("C2", "شرکت دوم", "شرکت دوم", company.base_currency_id, company.default_language_id)
users_service.grant_company_access(uid, other.company_id)

from peecha.services import journal_entries as je_service
je_id = je_service.create_journal_entry(company_id, uid, today, "سند آزمایشی اسناد", [
    je_service.LineInput(inv_gl.account_id, "بدهکار", D(1000), D(0)),
    je_service.LineInput(adj_gl.account_id, "بستانکار", D(0), D(1000))]).journal_entry_id
check(je_id is not None, "a real journal entry to link to")

# --- ۱–۳) ثبت سند، فایل معتبر، رد فایل نامعتبر --------------------------------------------------------------------------
check("هم‌خوان نیست" in err(lambda: dms.create_document(company_id, clerk.user_id, dms.DocumentFields("پی‌دی‌اف جعلی"),
                                                        [("fake.pdf", b"MZ\x90\x00 not a pdf")])), "a file whose content does not match its type is refused")
check("پذیرفته نمی‌شود" in err(lambda: dms.create_document(company_id, clerk.user_id, dms.DocumentFields("صفحهٔ وب"),
                                                           [("page.html", b"<html><script>alert(1)</script></html>")])), "HTML is refused")
check("پذیرفته نمی‌شود" in err(lambda: dms.create_document(company_id, clerk.user_id, dms.DocumentFields("تصویر برداری"),
                                                           [("x.svg", b"<svg onload='x'/>")])), "SVG is refused")
check("مگابایت" in err(lambda: dms.create_document(company_id, clerk.user_id, dms.DocumentFields("بزرگ"),
                                                   [("big.pdf", b"%PDF-" + b"0" * (26 * 1024 * 1024))])), "an oversize file is refused")
check("دسترسی" in err(lambda: dms.create_document(company_id, outsider.user_id, dms.DocumentFields("بی‌اجازه"), [("a.pdf", PDF)])),
      "a user without «ثبت» cannot create documents")
doc_id = dms.create_document(company_id, clerk.user_id, dms.DocumentFields(
    "قرارداد اجارهٔ انبار", "CONTRACT", issue_date=D0, valid_from=D0, expiry_date=D0 + datetime.timedelta(days=10),
    responsible_user_id=clerk.user_id, tags=["اجاره", "انبار"]), [("contract.pdf", PDF), ("photo.jpg", jpeg(gps=True))],
    [("journal_entry", je_id)])
detail = dms.get_document(company_id, clerk.user_id, doc_id)
check(detail.document_no.startswith("DMS-") and detail.status_code == "DRAFT" and len(detail.versions) == 1
      and len(detail.versions[0].files) == 2 and detail.tags == ["اجاره", "انبار"],
      f"the document is saved with two files, tags and a link ({detail.document_no}, {detail.tags})")
photo = next(f for f in detail.versions[0].files if f.extension == "jpg")
_n, _m, photo_bytes = dms.read_file(company_id, clerk.user_id, photo.file_id)
check(not dict(Image.open(io.BytesIO(photo_bytes)).getexif().get_ifd(0x8825)), "GPS is removed from the stored photo")
_n, mime, thumb = dms.read_file(company_id, clerk.user_id, photo.file_id, thumbnail=True)
check(mime == "image/jpeg" and thumb[:3] == b"\xff\xd8\xff", "a thumbnail is made for the photo")

# --- ۴–۵، ۱۷) دریافت با مجوز، رد بدون مجوز و IDOR -------------------------------------------------------------------------
check(dms.read_file(company_id, clerk.user_id, detail.versions[0].files[0].file_id)[2] == PDF, "the owner downloads the original file")
check("پیدا نشد" in err(lambda: dms.read_file(company_id, outsider.user_id, photo.file_id)), "a user without access cannot download it")
check("پیدا نشد" in err(lambda: dms.get_document(company_id, outsider.user_id, doc_id)), "nor open the document")
check("پیدا نشد" in err(lambda: dms.read_file(other.company_id, uid, photo.file_id)), "another company cannot reach the file by its id")
check("پیدا نشد" in err(lambda: dms.get_document(other.company_id, uid, doc_id)), "nor the document by its id")
check("پیدا نشد" in err(lambda: dms.read_file(company_id, clerk.user_id, 999999)), "a made-up file id is refused")
with new_session() as s:
    denied = s.scalar(select(func.count()).select_from(DmsEvent).where(DmsEvent.document_id == doc_id, DmsEvent.event_code == "DENIED"))
check(denied >= 1, "refused attempts are recorded")

# --- ۶–۷) نسخهٔ جدید، حفظ نسخهٔ قبلی، رد نسخهٔ تکراری، رد ثبت هم‌زمان ------------------------------------------------------
check("همان فایل‌های نسخهٔ جاری" in err(lambda: dms.add_version(company_id, clerk.user_id, doc_id, [("contract.pdf", PDF),
                                                                                                 ("photo.jpg", photo_bytes)], "تکرار")),
      "re-uploading the same files does not create a duplicate version")
first_version = detail.current_version_id
pdf2 = PDF.replace(b"1 0 obj", b"2 0 obj")
v2 = dms.add_version(company_id, clerk.user_id, doc_id, [("contract-v2.pdf", pdf2)], "امضای طرف دوم",
                     expected_current_version_id=first_version)
check("نسخهٔ دیگری" in err(lambda: dms.add_version(company_id, clerk.user_id, doc_id, [("c3.pdf", PDF.replace(b"1 0", b"3 0"))], "هم‌زمان",
                                                   expected_current_version_id=first_version)), "a stale editor cannot add a conflicting version")
detail = dms.get_document(company_id, clerk.user_id, doc_id)
check([v.version_no for v in detail.versions] == [2, 1] and detail.versions[0].is_current and len(detail.versions[1].files) == 2
      and detail.versions[0].reason == "امضای طرف دوم", "the previous version and its files are kept, with reason and user")
check(dms.read_file(company_id, clerk.user_id, detail.versions[1].files[0].file_id)[2] == PDF, "an old version can still be downloaded")

# --- ۸–۱۰) پیوند به رکورد، رکورد ناموجود، شرکت دیگر و دسترسی رکورد ----------------------------------------------------------
check("پیدا نشد" in err(lambda: dms.link_document(company_id, clerk.user_id, doc_id, "journal_entry", 987654)), "linking to a missing record is refused")
check("معتبر نیست" in err(lambda: dms.link_document(company_id, clerk.user_id, doc_id, "users; drop table x", 1)),
      "an unknown record type is refused")
check("دسترسی" in err(lambda: dms.link_document(company_id, clerk.user_id, doc_id, "detail_account", supplier)),
      "the clerk cannot link to a supplier without access to its form")
dms.link_document(company_id, uid, doc_id, "detail_account", supplier)
foreign = dimensions_service.create_supplier(other.company_id, "S9", "تامین‌کنندهٔ شرکت دوم")
check("پیدا نشد" in err(lambda: dms.link_document(company_id, uid, doc_id, "detail_account", foreign)),
      "a record of another company is not found")
linked = dms.documents_for_entity(company_id, clerk.user_id, "journal_entry", je_id)
check([r.document_id for r in linked] == [doc_id], "the journal entry shows its related document")
check("دسترسی" in err(lambda: dms.documents_for_entity(company_id, sales.user_id, "journal_entry", je_id)),
      "a user without access to the record cannot list its documents")

# --- ۱۱–۱۲) گردش کار و رد تایید نسخهٔ قدیمی ---------------------------------------------------------------------------------
check("دسترسی" in err(lambda: dms.transition(company_id, clerk.user_id, doc_id, "approve")), "the clerk cannot approve")
dms.transition(company_id, clerk.user_id, doc_id, "submit")
dms.transition(company_id, reviewer.user_id, doc_id, "start_review")
check("توضیح" in err(lambda: dms.transition(company_id, reviewer.user_id, doc_id, "reject")), "rejecting needs a reason")
check("نسخهٔ جدیدی" in err(lambda: dms.transition(company_id, reviewer.user_id, doc_id, "approve", expected_version_id=first_version)),
      "approving the old version the reviewer saw is refused")
dms.transition(company_id, reviewer.user_id, doc_id, "approve", "مطابق اصل", expected_version_id=v2)
detail = dms.get_document(company_id, clerk.user_id, doc_id)
check(detail.status_code == "APPROVED" and detail.approved_version_id == v2, "the current version is approved")
v3 = dms.add_version(company_id, clerk.user_id, doc_id, [("contract-v3.pdf", PDF.replace(b"1 0 obj", b"4 0 obj"))], "اصلاح بند ۳")
detail = dms.get_document(company_id, clerk.user_id, doc_id)
check(detail.status_code == "DRAFT" and detail.approved_version_id == v2 and detail.current_version_id == v3
      and not next(v for v in detail.versions if v.version_id == v3).is_approved,
      "a new version is not covered by the old approval")
statuses = [(e.from_status, e.to_status) for e in detail.events if e.event_code == "STATUS"]
check(("در حال بررسی", "تاییدشده") in statuses and len(statuses) >= 4, "the workflow history is kept with users and times")
check("ممکن نیست" in err(lambda: dms.transition(company_id, reviewer.user_id, doc_id, "approve")), "an invalid transition is refused")

# --- محرمانگی ----------------------------------------------------------------------------------------------------------------
secret_id = dms.create_document(company_id, uid, dms.DocumentFields("حکم کارگزینی", "PERSONNEL", confidentiality_code="SECRET"),
                                [("hokm.pdf", PDF)])
check("پیدا نشد" in err(lambda: dms.get_document(company_id, clerk.user_id, secret_id)), "a secret document is hidden from others")
check(secret_id not in [r.document_id for r in dms.search(company_id, clerk.user_id)[0]], "and from their search results")

# --- ۱۳) جست‌وجو و صفحه‌بندی ---------------------------------------------------------------------------------------------------
for i in range(7):
    dms.create_document(company_id, clerk.user_id, dms.DocumentFields(f"رسید شمارهٔ {i}", "RECEIPT"), [(f"r{i}.pdf", PDF + bytes([i]))])
rows, total = dms.search(company_id, clerk.user_id, dms.SearchFilters(text="رسید"), page=2, page_size=5)
check(total == 7 and len(rows) == 2, f"search counts all matches and pages them ({total}, {len(rows)})")
check(dms.search(company_id, clerk.user_id, dms.SearchFilters(text="contract-v3"))[1] == 1, "search finds the file name")
check(dms.search(company_id, clerk.user_id, dms.SearchFilters(tag="اجاره"))[1] == 1, "search by tag")
check(dms.search(company_id, clerk.user_id, dms.SearchFilters(entity_type="journal_entry", entity_id=je_id))[1] == 1, "search by linked record")
check(dms.search(company_id, clerk.user_id, dms.SearchFilters(expiring_within_days=30))[1] == 1, "search by expiry")
check(dms.search(company_id, clerk.user_id, page_size=10_000)[0].__len__() <= dms.MAX_PAGE_SIZE, "page size is capped")
check(dms.search(company_id, outsider.user_id)[1] == 0, "a user without access sees no documents")
check(dms.search(company_id, sales.user_id)[1] == 0, "a user with record access only sees documents of those records")

# --- ۱۴) رد رویدادها ------------------------------------------------------------------------------------------------------------
codes = {e.event_code for e in dms.get_document(company_id, uid, doc_id).events}
check({"CREATE", "VERSION", "LINK", "STATUS", "DOWNLOAD"} <= codes, f"create, version, link, status and download are recorded ({codes})")
with new_session() as s:
    blob = " ".join(str(d) for d in s.scalars(select(DmsEvent.details)).all())
check("%PDF" not in blob, "no file content is written to the event log")

# --- ۱۵) یادآوری انقضا بدون تکرار ----------------------------------------------------------------------------------------------
first = reminders.send_expiry_reminders(company_id)
second = reminders.send_expiry_reminders(company_id)
with new_session() as s:
    notes = s.scalar(select(func.count()).select_from(Notification).where(Notification.type_code == "DMS_EXPIRY"))
    rem = s.scalar(select(DmsReminder).where(DmsReminder.document_id == doc_id))
check(first == 1 and second == 0 and notes == 1 and rem.notified_user_ids == [clerk.user_id],
      "the expiry reminder goes once to the responsible user")
dash = dms.dashboard(company_id, clerk.user_id)
check(dash.total == 8 and dash.expiring == 1 and dash.pending == 0, f"dashboard counts real visible documents ({dash.total}, {dash.expiring})")

# --- دسته‌بندی سلسله‌مراتبی ----------------------------------------------------------------------------------------------------
root = dms.save_category(company_id, clerk.user_id, None, "قراردادها", None)
child = dms.save_category(company_id, clerk.user_id, None, "اجاره", root)
check("خودش" in err(lambda: dms.save_category(company_id, uid, root, "قراردادها", child)), "a category cannot be put under its child")
detail = dms.get_document(company_id, clerk.user_id, doc_id)
fields = dms.DocumentFields(detail.title, detail.document_type_code, category_id=child, tags=detail.tags,
                            expiry_date=detail.expiry_date, issue_date=detail.issue_date, valid_from=detail.valid_from,
                            responsible_user_id=detail.responsible_user_id)
dms.update_document(company_id, clerk.user_id, doc_id, fields, detail.row_version)
check("کاربر دیگری" in err(lambda: dms.update_document(company_id, clerk.user_id, doc_id, fields, detail.row_version)),
      "a stale edit is refused")
check(dms.search(company_id, clerk.user_id, dms.SearchFilters(category_id=root))[1] == 1, "searching a category includes its children")

# --- ۱۶، ۱۸) حالت پوشه: عبور مسیر، فایل گم‌شده، فایل یتیم -----------------------------------------------------------------------
folder = Path(tempfile.mkdtemp())
with new_session() as s:
    cfg = s.get(DmsSettings, company_id)
    cfg.storage_mode, cfg.storage_root = "FS", str(folder)
    s.commit()
fs_doc = dms.create_document(company_id, clerk.user_id, dms.DocumentFields("فایل روی پوشه"), [("fs.pdf", PDF + b"fs")])
fs_file = dms.get_document(company_id, clerk.user_id, fs_doc).versions[0].files[0].file_id
with new_session() as s:
    key = s.get(DmsFile, fs_file).storage_key
check(key.endswith(".pdf") and "fs" not in key.rsplit("/", 1)[-1][:-4] and (folder / key).is_file(),
      "the file is stored under a random name inside the folder")
check(dms.read_file(company_id, clerk.user_id, fs_file)[2] == PDF + b"fs", "and read back")
check("نامعتبر" in err(lambda: storage._resolve(folder, "../../etc/passwd")), "a path that leaves the folder is refused")
check("نامعتبر" in err(lambda: storage._resolve(folder, f"{company_id}/2026/01/../../../../x.pdf")), "including dotted keys")
with new_session() as s:
    s.get(DmsFile, fs_file).storage_key = "../../etc/passwd"
    s.commit()
check("نامعتبر" in err(lambda: dms.read_file(company_id, clerk.user_id, fs_file)), "a tampered key in the database is refused")
with new_session() as s:
    s.get(DmsFile, fs_file).storage_key = key
    s.commit()
(folder / key).unlink()
check("پیدا نشد" in err(lambda: dms.read_file(company_id, clerk.user_id, fs_file)), "a missing file gives a clear message")
(folder / key).write_bytes(b"%PDF-changed")
check("تغییر کرده" in err(lambda: dms.read_file(company_id, clerk.user_id, fs_file)), "a changed file is detected")
blocker = folder / "not-a-folder"
blocker.write_bytes(b"x")
with new_session() as s:
    s.get(DmsSettings, company_id).storage_root = str(blocker)
    s.commit()
fail_msg = err(lambda: dms.create_document(company_id, clerk.user_id, dms.DocumentFields("پوشه خراب"), [("x.pdf", PDF + b"x")]))
with new_session() as s:
    s.get(DmsSettings, company_id).storage_root = str(folder)
    s.commit()
    orphan_rows = s.scalar(select(func.count()).select_from(DmsFile).where(DmsFile.original_name == "x.pdf"))
check("ممکن نشد" in fail_msg and orphan_rows == 0, f"a storage failure gives a clear message and leaves no rows ({fail_msg[:50]})")
before_files = set(p for p in folder.rglob("*") if p.is_file())
real_set_tags = dms._set_tags
dms._set_tags = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("قطع دیتابیس"))
try:
    err(lambda: dms.create_document(company_id, clerk.user_id, dms.DocumentFields("قطع وسط ثبت"), [("y.pdf", PDF + b"y")]))
finally:
    dms._set_tags = real_set_tags
with new_session() as s:
    rows_after = s.scalar(select(func.count()).select_from(DmsFile).where(DmsFile.original_name == "y.pdf"))
check(rows_after == 0 and set(p for p in folder.rglob("*") if p.is_file()) == before_files,
      "a database failure after the file was written removes the file (no orphan)")
stray = folder / str(company_id) / "2020" / "01"
stray.mkdir(parents=True, exist_ok=True)
(stray / ("a" * 32 + ".pdf")).write_bytes(b"%PDF-orphan")
os.utime(stray / ("a" * 32 + ".pdf"), (0, 0))
check(reminders.sweep_orphans(company_id) >= 1 and not (stray / ("a" * 32 + ".pdf")).exists(), "an orphan file in the folder is removed")
check((folder / key).exists(), "while referenced files stay")

# --- حذف منطقی --------------------------------------------------------------------------------------------------------------
check("دسترسی" in err(lambda: dms.delete_document(company_id, clerk.user_id, fs_doc)), "the clerk cannot delete")
dms.delete_document(company_id, uid, fs_doc, "تکراری")
check("پیدا نشد" in err(lambda: dms.get_document(company_id, uid, fs_doc)), "a deleted document is hidden")

finish()
