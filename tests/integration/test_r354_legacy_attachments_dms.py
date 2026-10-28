"""R354: پیوست قدیمی به سامانهٔ اسناد: پیوست سند حسابداری به همان سند پیوند می‌خورد، پیوست بی‌رکورد معادل (مرکز رسانه،
رکورد حذف‌شده) بدون پیوند حفظ می‌شود، فایل گم‌شده گزارش می‌شود، اصل پیوست دست نمی‌خورد، انتقال دوباره تکراری نمی‌سازد؛
انتقال سند حسابداری به شرکت دیگر اسناد سامانهٔ اسناد را هم با فایل منتقل می‌کند؛ و فرم تنظیمات اسناد."""
import os, sys, tempfile
from pathlib import Path
os.environ["PEECHA_DB_NAME"] = "peecha_test_r354"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.documents import Attachment
from peecha.db.models.security import Form
from peecha.services import companies, company_transfer, journal_entries as je, order_tracking, roles, users
from peecha.services.dms import documents as dms, legacy_import

k11 = A("11", "نقد", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
cash = A("111", "صندوق", "DEBIT", "ASSET", "PERMANENT", True, k11.account_id)
g_eq = A("3", "سرمایه", "CREDIT", "EQUITY", "PERMANENT", False)
k31 = A("31", "سرمایه", "CREDIT", "EQUITY", "PERMANENT", False, g_eq.account_id)
capital = A("311", "سرمایه", "CREDIT", "EQUITY", "PERMANENT", True, k31.account_id)
L = je.LineInput
entry = je.create_journal_entry(company_id, uid, today, "آوردهٔ سرمایه", [
    L(cash.account_id, "", D(1_000_000), D(0)), L(capital.account_id, "", D(0), D(1_000_000))]).journal_entry_id

from PIL import Image

folder = Path(tempfile.mkdtemp(prefix="r354_"))
receipt = folder / "رسید بانک.jpg"
Image.new("RGB", (40, 30), (200, 20, 20)).save(receipt, "JPEG")
receipt_bytes = receipt.read_bytes()
order_tracking.attach_file(company_id, entry, uid, str(receipt))
roles.ensure_catalog()


def legacy(form_code, record_id, name, path):
    with new_session() as s:
        form_id = s.scalar(select(Form.form_id).where(Form.code == form_code))
        row = Attachment(company_id=company_id, form_id=form_id, source_record_id=record_id, file_name=name,
                         file_extension=Path(name).suffix.lstrip("."), file_size_bytes=10, storage_key=str(path),
                         uploaded_by_user_id=uid)
        s.add(row)
        s.commit()
        return row.attachment_id


banner = folder / "banner.png"
Image.new("RGB", (60, 20), (20, 20, 200)).save(banner, "PNG")
broken = folder / "خراب.jpg"
broken.write_bytes(b"not really a jpeg")
legacy("media_center", company_id, "banner.png", banner)
legacy("fa_assets", 999_999, "تصویر دارایی.png", banner)  # دارایی‌اش دیگر وجود ندارد
legacy("journal_entry", entry, "گم‌شده.pdf", folder / "missing.pdf")
legacy("journal_entry", entry, "خراب.jpg", broken)
check(legacy_import.pending_count(company_id) == 5, "five legacy attachments wait for import")

report = legacy_import.import_all(company_id, uid)
check(report.imported == 3 and report.unlinked == 2 and report.missing_files == ["گم‌شده.pdf"]
      and len(report.rejected) == 1 and "خراب.jpg" in report.rejected[0],
      f"three are imported, two without a matching record; the missing and the corrupt file are reported ({report})")
linked = dms.documents_for_entity(company_id, uid, "journal_entry", entry)
check(len(linked) == 1 and linked[0].title == "رسید بانک" and linked[0].document_type_code == "IMAGE",
      "the accounting document's receipt is linked to the same entry in the document system")
doc = dms.get_document(company_id, uid, linked[0].document_id)
file_id = doc.versions[0].files[0].file_id
check(dms.read_file(company_id, uid, file_id)[2] == receipt_bytes and any("قدیمی" in t for t in doc.tags),
      "the file content and a source tag are kept")
with new_session() as s:
    still = s.scalar(select(func.count()).select_from(Attachment).where(Attachment.company_id == company_id,
                                                                        Attachment.is_deleted.is_(False)))
check(still == 5, "the legacy attachments stay as they were")
check(legacy_import.pending_count(company_id) == 2 and legacy_import.import_all(company_id, uid).imported == 0,
      "importing again creates nothing new (only the missing and corrupt files stay pending)")

# انتقال به شرکت دیگر
other = companies.create_company("C2", "شرکت دوم", "شرکت دوم", company.base_currency_id, company.default_language_id)
users.grant_company_access(uid, other.company_id)
new_ids = company_transfer.transfer_journal_entries(company_id, other.company_id, [entry], uid, void_originals=False,
                                                    target_language_id=company.default_language_id)
moved = dms.documents_for_entity(other.company_id, uid, "journal_entry", new_ids[0])
moved_doc = dms.get_document(other.company_id, uid, moved[0].document_id) if moved else None
check(len(moved) == 1 and dms.read_file(other.company_id, uid, moved_doc.versions[0].files[0].file_id)[2]
      == receipt_bytes, "the transferred entry brings its document-system files to the other company")

# فرم تنظیمات اسناد
from PySide6.QtWidgets import QApplication
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.dms import DmsSettingsScreen

screen = DmsSettingsScreen()
screen.refresh()
check("۲" in screen.legacy_label.text() and screen.legacy_button.isEnabled(), f"the settings show the pending count ({screen.legacy_label.text()})")

finish()
