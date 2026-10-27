"""R343: ورودی‌های خطرناک و شعبه در مدیریت اسناد: متن‌های شبیه SQL در جست‌وجو، برچسب، عنوان و جست‌وجوی رکورد فقط متن
جست‌وجو هستند و چیزی را دور نمی‌زنند یا خراب نمی‌کنند؛ نوع رکورد ساختگی رد می‌شود؛ شعبهٔ شرکت دیگر پذیرفته نمی‌شود و
فیلتر شعبه فقط اسناد همان شعبه را نشان می‌دهد؛ نام فایل با مسیر یا کاراکتر خطرناک فقط به‌عنوان نام نمایشی امن نگه داشته
می‌شود."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r343_sec"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.documents import DmsDocument, DmsFile
from peecha.services import companies as companies_service, procurement_masters, roles as roles_service, users as users_service
from peecha.services.dms import common as dc, documents as dms, entities

dc.save_settings(company_id, uid, {"storage_mode": "DB", "max_file_mb": 25})
north = procurement_masters.save_branch(company_id, "N1", "شعبه شمال")
south = procurement_masters.save_branch(company_id, "S1", "شعبه جنوب")
other = companies_service.create_company("C2", "شرکت دوم", "شرکت دوم", company.base_currency_id, company.default_language_id)
foreign_branch = procurement_masters.save_branch(other.company_id, "F1", "شعبهٔ شرکت دوم")

doc_n = dms.create_document(company_id, uid, dms.DocumentFields("قرارداد شمال", branch_id=north), [("n.txt", b"north")])
doc_s = dms.create_document(company_id, uid, dms.DocumentFields("قرارداد جنوب", branch_id=south), [("s.txt", b"south")])
try:
    dms.create_document(company_id, uid, dms.DocumentFields("شعبهٔ بیگانه", branch_id=foreign_branch), [("f.txt", b"x")])
    refused = ""
except ValueError as exc:
    refused = str(exc)
check("شعبه" in refused, f"a branch of another company is refused ({refused})")
rows, total = dms.search(company_id, uid, dms.SearchFilters(branch_id=north), 1, 50)
check({r.document_id for r in rows} == {doc_n} and total == 1, "the branch filter shows only that branch's documents")

with new_session() as s:
    before = s.scalar(select(func.count()).select_from(DmsDocument))
for needle in ("' OR 1=1 --", "%' OR '1'='1", "x'); DELETE FROM doc.documents; --", "\\", "%", "_"):
    rows, total = dms.search(company_id, uid, dms.SearchFilters(text=needle), 1, 50)
    check(total == 0, f"search text {needle!r} matches nothing instead of everything")
    with new_session() as s:
        check(entities.search(s, company_id, "detail_account", needle) == [], f"record search {needle!r} is only text")
rows, total = dms.search(company_id, uid, dms.SearchFilters(tag="' OR 1=1 --"), 1, 50)
check(total == 0, "a tag filter with SQL text matches nothing")
with new_session() as s:
    check(s.scalar(select(func.count()).select_from(DmsDocument)) == before, "no input changed or deleted any row")

nasty = dms.create_document(company_id, uid, dms.DocumentFields("'; DROP TABLE doc.files; --", tags=["' OR 1=1 --"]),
                            [("../../etc/passwd.txt", b"hello"), ("a\\..\\..\\b<script>.txt", b"hi")])
detail = dms.get_document(company_id, uid, nasty)
names = [f.name for f in detail.versions[0].files]
check(detail.title == "'; DROP TABLE doc.files; --" and "' OR 1=1 --" in detail.tags, "dangerous text is stored as plain text")
check(all("/" not in n and "\\" not in n for n in names), f"file names keep no path parts ({names})")
with new_session() as s:
    keys = list(s.scalars(select(DmsFile.storage_key).where(DmsFile.storage_key.is_not(None))))
check(keys == [], "in database mode no file path is built from user input")

for bad_type in ("journal_entry; DROP TABLE x", "acc.journal_entries", "../journal_entry"):
    try:
        dms.link_document(company_id, uid, doc_n, bad_type, 1)
        msg = ""
    except (ValueError, LookupError) as exc:
        msg = str(exc)
    check("معتبر نیست" in msg, f"record type {bad_type!r} is refused")

forms = {f.code: f.form_id for f in roles_service.list_forms()}
role = roles_service.create_role(company_id, "اسناد", None)
roles_service.set_role_permission(role.role_id, forms["dms_documents"], "VIEW", True)
clerk = users_service.create_user("clerk", "کارمند", "secret123", None, company.default_language_id, False, [company_id], company_id)
roles_service.set_user_role(clerk.user_id, role.role_id, company_id, True)
rows, total = dms.search(company_id, clerk.user_id, dms.SearchFilters(text="' OR confidentiality_code <> '"), 1, 50)
check(total == 0, "SQL text cannot widen what a limited user sees")

# ابزار پاک‌سازی داده‌های شرکت: پاک‌کردن اسناد مالی و انبار بایگانی اسناد را نگه می‌دارد؛ اطلاعات پایه آن را هم پاک می‌کند
from peecha.services import data_reset
from peecha.services.dms import capture
capture.create_request(company_id, uid, document_id=doc_n)
other_doc = dms.create_document(other.company_id, uid, dms.DocumentFields("سند شرکت دوم"), [("o.txt", b"other")])
data_reset.wipe_documents(company_id)
with new_session() as s:
    kept = s.scalar(select(func.count()).select_from(DmsDocument).where(DmsDocument.company_id == company_id))
check(kept == before + 1, f"wiping financial and stock documents keeps the document archive ({kept})")
data_reset.wipe_master_data(company_id)
with new_session() as s:
    left = {t: s.execute(text(f"SELECT count(*) FROM doc.{t} WHERE company_id = :c"), {"c": company_id}).scalar()
            for t in ("documents", "files", "tags", "categories", "document_links", "document_events", "capture_requests")}
    survivor = s.get(DmsDocument, other_doc)
check(not any(left.values()), f"wiping master data removes the company's document archive ({left})")
check(survivor is not None, "another company's documents are untouched")
data_reset.wipe_settings(company_id)
with new_session() as s:
    check(s.execute(text("SELECT count(*) FROM doc.dms_settings WHERE company_id = :c"), {"c": company_id}).scalar() == 0,
          "wiping settings removes the document settings")

finish()
