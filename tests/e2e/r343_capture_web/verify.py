"""E2E verification in the DB after the browser run."""
import io, json, os, sys
os.environ.setdefault("PEECHA_DB_NAME", "peecha_e2e_r343")
os.environ.setdefault("PEECHA_DB_USER", "peecha"); os.environ.setdefault("PEECHA_DB_PASSWORD", "peecha")
os.environ.setdefault("PEECHA_DB_HOST", "localhost"); os.environ.setdefault("PEECHA_DB_PORT", "5432")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "src"))
from PIL import Image
from sqlalchemy import select
from peecha.db.base import new_session
from peecha.db.models.documents import DmsCaptureRequest, DmsEvent
from peecha.services.dms import documents as dms

s = json.load(open(os.path.join(sys.argv[1], "setup.json")))
bad = False
def check(c, m):
    global bad
    print(("OK: " if c else "FAIL: ") + m); bad |= not c
with new_session() as session:
    req = session.get(DmsCaptureRequest, s["request_id"])
    other = session.get(DmsCaptureRequest, s["cancel_id"])
    check(req.status_code == "COMPLETED" and req.result_document_id, f"request completed ({req.status_code})")
    check(other.status_code == "CANCELLED", f"second request cancelled ({other.status_code})")
    events = [e.event_code for e in session.scalars(select(DmsEvent).where(DmsEvent.document_id == req.result_document_id))]
uid = 1
rows = dms.documents_for_entity(s["company_id"], uid, "journal_entry", s["je_id"])
check(len(rows) == 1 and rows[0].document_id == req.result_document_id, "the photo is a document linked to the same journal entry")
doc = dms.get_document(s["company_id"], uid, req.result_document_id)
files = doc.versions[0].files
check(len(files) == 1, f"one photo stored ({len(files)})")
name, mime, data = dms.read_file(s["company_id"], uid, files[0].file_id)
img = Image.open(io.BytesIO(data))
exif = img.getexif()
check(mime == "image/jpeg" and 0x8825 not in exif, "stored JPEG has no GPS")
check(exif.get(0x010F) == "PhoneMaker", "other EXIF is kept (lossless strip)")
check(img.getpixel((10, 10))[2] > 100, "the retaken (teal) photo was sent, not the removed one")
print("version:", vars(doc.versions[0]).get("source_label") or vars(doc.versions[0]).get("source_code"))
print("events:", events)
print("SOME FAILED" if bad else "ALL PASS")
