"""R343: استخراج متن محلی برای جست‌وجو در محتوای فایل‌ها: PDF متنی، Word و متن ساده در پس‌زمینه (tick) خوانده می‌شوند و
جست‌وجوی اسناد آن‌ها را پیدا می‌کند؛ عکس بدون OCR فعال دست نمی‌خورد؛ OCR بدون Tesseract نصب‌شده خطا نمی‌دهد و سند سالم
می‌ماند؛ خاموش‌کردن استخراج متن در تنظیمات رعایت می‌شود؛ جست‌وجو در متن هم فقط اسناد قابل دیدن را برمی‌گرداند."""
import io, os, sys, zipfile
from types import SimpleNamespace
os.environ["PEECHA_DB_NAME"] = "peecha_test_r343_text"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from PIL import Image, ImageDraw, ImageFont

from peecha.db.models.documents import DmsFile
from peecha.services import roles as roles_service, users as users_service
from peecha.services.dms import common as dc, documents as dms, reminders, storage


def text_pdf(line: str) -> bytes:
    stream = f"BT /F1 18 Tf 40 700 Td ({line}) Tj ET".encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def docx(text_value: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("word/document.xml", '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
                         f'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{text_value}</w:t></w:r></w:p></w:body></w:document>')
    return out.getvalue()


def png(words: str = "") -> bytes:
    img = Image.new("RGB", (1000, 200) if words else (40, 40), "white")
    if words:  # متن فارسی با فونت Vazirmatn همین پروژه، راست‌چین
        font = ImageFont.truetype(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "mobile", "assets", "fonts",
                                               "Vazirmatn-Regular.ttf"), 56)
        ImageDraw.Draw(img).text((970, 60), words, fill="black", font=font, anchor="ra", direction="rtl", language="fa")
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def file_row(document_id):
    detail = dms.get_document(company_id, uid, document_id)
    with new_session() as s:
        row = s.get(DmsFile, detail.versions[0].files[0].file_id)
        return SimpleNamespace(text_status=row.text_status, text_content=row.text_content)


def found(needle, user_id=None):
    rows, total = dms.search(company_id, user_id or uid, dms.SearchFilters(text=needle), 1, 50)
    return {r.document_id for r in rows}


dc.save_settings(company_id, uid, {"storage_mode": "DB", "max_file_mb": 25, "text_extraction": True, "image_ocr": False})
pdf_doc = dms.create_document(company_id, uid, dms.DocumentFields("صورت‌حساب حمل"), [("invoice.pdf", text_pdf("Freight invoice ACME-4471"))])
word_doc = dms.create_document(company_id, uid, dms.DocumentFields("قرارداد"), [("contract.docx", docx("قرارداد اجاره انبار شماره ۷۷"))])
txt_doc = dms.create_document(company_id, uid, dms.DocumentFields("یادداشت"), [("note.txt", "سریال دستگاه ZX-9001".encode())])
photo_doc = dms.create_document(company_id, uid, dms.DocumentFields("عکس تابلو"), [("board.png", png())])
for doc_id in (pdf_doc, word_doc, txt_doc):
    check(file_row(doc_id).text_status == "PENDING", f"text extraction is queued, not done during save ({doc_id})")
check(file_row(photo_doc).text_status == "NONE", "a photo is not queued while image OCR is off")
check(not found("ACME-4471"), "before extraction the file text is not searchable yet")

done = 0
for _ in range(5):
    done += reminders.tick(company_id)
pdf_row, word_row, txt_row = file_row(pdf_doc), file_row(word_doc), file_row(txt_doc)
check(pdf_row.text_status == "DONE" and "ACME-4471" in (pdf_row.text_content or ""), f"PDF text is extracted ({pdf_row.text_status})")
check(word_row.text_status == "DONE" and "اجاره انبار" in (word_row.text_content or ""), "Word text is extracted")
check(txt_row.text_status == "DONE" and "ZX-9001" in (txt_row.text_content or ""), "plain text is extracted")
check(found("ACME-4471") == {pdf_doc} and found("اجاره انبار") == {word_doc} and found("ZX-9001") == {txt_doc},
      "search finds documents by the text inside their files")

# OCR محلی عکس: با Tesseract نصب‌شده متن خوانده می‌شود؛ بدون آن، وضعیت «ناموفق» ثبت و سند سالم می‌ماند
import shutil
dc.save_settings(company_id, uid, {"image_ocr": True})
ocr_doc = dms.create_document(company_id, uid, dms.DocumentFields("عکس رسید"), [("receipt.png", png("صورتحساب حمل بار"))])
check(file_row(ocr_doc).text_status == "PENDING", "with image OCR on, photos are queued")
reminders.extract_pending_text(company_id)
ocr = file_row(ocr_doc)
if shutil.which("tesseract"):
    check(ocr.text_status == "DONE" and "حمل بار" in (ocr.text_content or "") and found("حمل بار") == {ocr_doc},
          f"local OCR reads the photo and makes it searchable ({ocr.text_status}: {ocr.text_content!r})")
else:
    print("NOTE: Tesseract is not installed here; only the no-OCR path is checked")
    check(ocr.text_status == "FAILED" and dms.get_document(company_id, uid, ocr_doc).title == "عکس رسید",
          "without Tesseract, OCR fails quietly and the document stays intact")

dc.save_settings(company_id, uid, {"text_extraction": False, "image_ocr": False})
off_doc = dms.create_document(company_id, uid, dms.DocumentFields("بدون متن"), [("off.txt", b"SECRET-TEXT-55")])
reminders.extract_pending_text(company_id)
check(file_row(off_doc).text_status == "NONE" and not found("SECRET-TEXT-55"), "turning text extraction off is respected")

# متن داخل فایل هم فقط برای کسی که سند را می‌بیند قابل جست‌وجوست
forms = {f.code: f.form_id for f in roles_service.list_forms()}
role = roles_service.create_role(company_id, "بدون اسناد", None)
roles_service.set_role_permission(role.role_id, forms["journal_entry"], "VIEW", True)
outsider = users_service.create_user("outsider", "بیرونی", "secret123", None, company.default_language_id, False, [company_id], company_id)
roles_service.set_user_role(outsider.user_id, role.role_id, company_id, True)
check(not found("ACME-4471", outsider.user_id), "a user without document access cannot find it by its text")
import inspect, re
check(not re.search(r"import (requests|httpx|urllib|socket)|from (requests|httpx|urllib)", inspect.getsource(storage)),
      "extraction is local only: the storage module has no network client")

finish()
