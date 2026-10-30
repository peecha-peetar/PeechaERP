"""R343: رابط دسکتاپ مدیریت اسناد: منو و صفحه‌ها، فهرست با جست‌وجو و صفحه‌بندی، فرم سند جدید با فایل و پیوند، نسخه‌ها و
تاریخچه، دکمه‌های گردش کار بر اساس دسترسی، پیش‌نمایش عکس و PDF، دکمهٔ «اسناد مرتبط» در فرم‌های ERP، پنجرهٔ عکس‌برداری
با QR که بدون بازکردن دوباره پس از ارسال گوشی «تکمیل شد» نشان می‌دهد و عکس در اسناد همان رکورد دیده می‌شود، داشبورد
و تنظیمات."""
import io, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r343_ui"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from PIL import Image
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

app = QApplication.instance() or QApplication([])
warned = []
QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[2]))
QMessageBox.information = staticmethod(lambda *a, **k: warned.append(a[2]))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

from peecha.services import journal_entries as je_service, roles as roles_service, users as users_service
from peecha.services.dms import capture, common as dc, documents as dms
from peecha.ui.screens import dms as screens


def jpeg(color="red", orientation=None) -> bytes:
    img = Image.new("RGB", (60, 30), color)
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif.tobytes())
    return out.getvalue()


def pdf_bytes() -> bytes:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument.new()
    pdf.new_page(200, 300)
    pdf.new_page(200, 300)
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


je_id = je_service.create_journal_entry(company_id, uid, today, "سند آزمایشی", [
    je_service.LineInput(inv_gl.account_id, "بدهکار", D(500), D(0)),
    je_service.LineInput(adj_gl.account_id, "بستانکار", D(0), D(500))]).journal_entry_id
dc.save_settings(company_id, uid, {"storage_mode": "DB", "mobile_base_url": "https://erp.example.ir:8443", "max_file_mb": 25,
                                   "capture_minutes": 10, "capture_max_photos": 5, "expiry_reminder_days": 30})

# --- منو و صفحه‌ها ---------------------------------------------------------------------------------------------------
from peecha.ui.shell_window import MainWindow

win = MainWindow()
win.load_context_switcher()
check("DMS" in win._sidebar_groups and not win._sidebar_groups["DMS"].isHidden(), "the documents module is in the menu")
for code, screen in (("DMS_DOCUMENTS", "dms_documents"), ("DMS_DASHBOARD", "dms_dashboard"), ("DMS_CATEGORIES", "dms_categories"),
                     ("DMS_SETTINGS", "dms_settings")):
    win.open_screen(code)
    check(win._mdi_subwindows.get(screen) is not None, f"«{code}» opens")
je_screen = win.get_screen("journal_entry")
check(any(b.accessibleName() == "اسناد مرتبط" for b in je_screen.findChildren(QPushButton)), "the journal entry form has «related documents»")
for name in ("commercial_document_purchase_invoice", "inventory_document_receipt", "detail_dimensions"):
    screen = win.get_screen(name)
    check(screen is not None and any(b.accessibleName() == "اسناد مرتبط" for b in screen.findChildren(QPushButton)),
          f"the «{name}» form has «related documents»")
prd_screen = win.get_screen("prd_orders")
prd_button = next((b for b in prd_screen.findChildren(QPushButton) if b.accessibleName() == "اسناد مرتبط"), None) if prd_screen else None
check(prd_button is not None, "the production order form has «related documents»")
if prd_button is not None:
    prd_button.click()
    check(warned and "ذخیره" in warned[-1], "with no order selected it asks to open one first")
win.hide()

# --- فرم سند جدید از داخل رکورد با فایل و پیوند --------------------------------------------------------------------------
related = screens.RelatedDocumentsDialog(None, "journal_entry", je_id)
check("سند" in related.title.text() and related.table.rowCount() == 0, f"the related list opens empty ({related.title.text()})")
dialog = screens.DocumentDialog(related, link=("journal_entry", je_id, "سند آزمایشی"), files=[("receipt.jpg", jpeg(orientation=6)),
                                                                                             ("scan.pdf", pdf_bytes())])
dialog.title.setText("رسید پرداخت اجاره")
screens.set_combo(dialog.type_box, "RECEIPT")
dialog.tags.setText("اجاره، بانک")
dialog._save()
check(dialog.document_id is not None and dialog.tabs.isTabEnabled(1), f"the new document is saved from the record ({warned[-1:]})")
related.refresh()
check(related.table.rowCount() == 1 and related.rows[0].file_count == 2, "it shows in the record's related documents")
related.table.setCurrentCell(0, 0)
check(related.thumbnail.pixmap() is not None and not related.thumbnail.pixmap().isNull(), "with a thumbnail")

# --- نسخه‌ها، تاریخچه، پیش‌نمایش ----------------------------------------------------------------------------------------
dialog.load()
version = dialog.versions.topLevelItem(0)
check(version.childCount() == 2 and "جاری" in version.text(0), "the versions tab lists the current version and its files")
check(dialog.events.rowCount() >= 3 and dialog.links.rowCount() == 1, "history and links are shown")
photo_id = next(version.child(i).data(0, 0x0100) for i in range(2) if version.child(i).text(4) == "jpg")
pdf_id = next(version.child(i).data(0, 0x0100) for i in range(2) if version.child(i).text(4) == "pdf")
name, mime, data = dms.read_file(company_id, uid, photo_id)
preview = screens.PreviewDialog(name, mime, data)
check(preview.kind == "image" and preview._pixmap.width() == 30 and preview._pixmap.height() == 60,
      "the photo preview applies the camera orientation")
preview._set_zoom(2.0)
check(preview.image.pixmap().width() == 60, "and zooms")
name, mime, data = dms.read_file(company_id, uid, pdf_id)
preview = screens.PreviewDialog(name, mime, data)
check(preview.kind == "pdf" and preview._pixmap is not None and "۲" in preview.page_label.text(), "a PDF is shown page by page")
preview._show_page(1)
check("صفحهٔ ۲" in preview.page_label.text(), "and moves to the next page")
html = screens.PreviewDialog("x.txt", "text/plain", "<script>alert(1)</script>".encode())
check(html.kind == "text" and html.text.toPlainText().startswith("<script>"), "text is shown as plain text, never run")
preview.done(0)

# --- دکمه‌های گردش کار بر اساس دسترسی --------------------------------------------------------------------------------------
forms = {f.code: f.form_id for f in roles_service.list_forms()}
role = roles_service.create_role(company_id, "مشاهده‌گر", None)
roles_service.set_role_permission(role.role_id, forms["dms_documents"], "VIEW", True)
viewer = users_service.create_user("viewer", "مشاهده‌گر", "secret123", None, company.default_language_id, False, [company_id], company_id)
roles_service.set_user_role(viewer.user_id, role.role_id, company_id, True)
check(not dialog.action_buttons["submit"].isHidden() and dialog.action_buttons["approve"].isHidden(),
      "a draft offers «send for review», not «approve»")
import peecha.session as app_session
admin_user = app_session.current_user
app_session.current_user = viewer
viewer_dialog = screens.DocumentDialog(None, dialog.document_id)
check(not viewer_dialog.save_button.isEnabled() and all(b.isHidden() for b in viewer_dialog.action_buttons.values())
      and viewer_dialog.delete_button.isHidden(), "a view-only user cannot edit, decide or delete")
app_session.current_user = admin_user
dialog._transition("submit")
check(dms.get_document(company_id, uid, dialog.document_id).status_code == "PENDING" and not dialog.action_buttons["approve"].isHidden(),
      "after sending, the reviewer sees «approve»")

# --- عکس‌برداری با موبایل: QR، وضعیت زنده، پیوست به همان رکورد ----------------------------------------------------------
cap = screens.CaptureDialog(related, entity_type="journal_entry", entity_id=je_id)
done = []
cap.completed.connect(done.append)
check(cap.qr.pixmap() is not None and not cap.qr.pixmap().isNull() and cap.link.text().startswith("https://erp.example.ir:8443/m/capture#"),
      "the capture window shows a QR code and the secure link")
check(cap.timer.isActive() and cap.timer.interval() == 2000 and "در انتظار گوشی" in cap.status_label.text(), "and polls the status")
token = cap.link.text().rsplit("#", 1)[-1]
capture.open_request(company_id, uid, token=token)
cap.poll()
check("روی گوشی باز شد" in cap.status_label.text(), "the desktop sees the phone opening it without reopening the window")
capture.upload(company_id, uid, [("photo-1.jpg", jpeg("green"))], "k-ui", token=token)
cap.poll()
check(done and "پیوست شد" in cap.status_label.text() and not cap.timer.isActive(), "and the completion, then stops polling")
related.refresh()
check(related.table.rowCount() == 2 and any(r.document_id == done[0] for r in related.rows), "the photo is in the record's documents")
cap.close()

pending = screens.CaptureDialog(None, document_id=dialog.document_id)
request_id = pending.view.request_id
pending.close()
check(not pending.timer.isActive() and capture.status(company_id, uid, request_id).status_code == "CANCELLED",
      "closing an unused capture window stops its timer and cancels the request")

# --- فهرست اسناد، داشبورد، دسته‌ها و تنظیمات ---------------------------------------------------------------------------------
for i in range(55):
    dms.create_document(company_id, uid, dms.DocumentFields(f"مدرک {i}"), [(f"m{i}.txt", f"متن {i}".encode())])
docs = screens.DmsDocumentsScreen()
docs.refresh()
check(docs.table.rowCount() == 50 and "از ۲" in docs.page_label.text() and docs.next_button.isEnabled(), "the list pages by 50")
docs.load(2)
check(docs.table.rowCount() == 7 and not docs.next_button.isEnabled(), f"the second page has the rest ({docs.table.rowCount()})")
docs.search_box.setText("اجاره")
docs.load(1)
check(docs.table.rowCount() == 1, "search narrows the list")
dash = screens.DmsDashboardScreen()
dash.refresh()
check(dash.cards["total"].value_label.text() == "۵۷" and dash.cards["pending"].value_label.text() == "۱"
      and dash.cards["captures_completed"].value_label.text() == "۱", "the dashboard shows real counts")
cats = screens.DmsCategoriesScreen()
cats.refresh()
cats._save(None, None, "قراردادها")
check(cats.tree.topLevelItemCount() == 1 and cats.tags.count() == 2, "categories are added and tags listed")
settings_screen = screens.DmsSettingsScreen()
settings_screen.refresh()
settings_screen.url.setText("ftp://bad")
settings_screen.save()
check(warned and "https" in warned[-1], "an invalid mobile server address is refused")
settings_screen.url.setText("https://erp.example.ir:9443")
settings_screen.save()
check(capture.mobile_url(company_id, "t") == "https://erp.example.ir:9443/m/capture#t", "settings are saved")

finish()
