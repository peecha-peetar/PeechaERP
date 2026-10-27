"""E2E setup: real DB, real journal entry, two capture requests; writes tokens and a GPS-tagged JPEG."""
import io, json, os, sys
os.environ.setdefault("PEECHA_DB_NAME", "peecha_e2e_r343")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "integration"))
from prd_fixture import *  # noqa
from PIL import Image
from peecha.services import journal_entries as je_service
from peecha.services.dms import capture, common as dc

out_dir = sys.argv[1]
je_id = je_service.create_journal_entry(company_id, uid, today, "سند هزینه حمل", [
    je_service.LineInput(inv_gl.account_id, "بدهکار", D(700), D(0)),
    je_service.LineInput(adj_gl.account_id, "بستانکار", D(0), D(700))]).journal_entry_id
dc.save_settings(company_id, uid, {"storage_mode": "DB", "mobile_base_url": os.environ.get("E2E_BASE", "http://127.0.0.1:8765"), "max_file_mb": 25,
                                   "capture_minutes": 10, "capture_max_photos": 3, "expiry_reminder_days": 30})
main = capture.create_request(company_id, uid, entity_type="journal_entry", entity_id=je_id, title="رسید حمل")
other = capture.create_request(company_id, uid, entity_type="journal_entry", entity_id=je_id, title="لغو")

def jpeg(path, color, gps):
    img = Image.new("RGB", (1200, 900), color)
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"
    if gps:
        exif[0x8825] = {1: "N", 2: (35.0, 41.0, 59.0), 3: "E", 4: (51.0, 23.0, 20.0)}
    img.save(path, "JPEG", exif=exif.tobytes(), quality=90)

jpeg(os.path.join(out_dir, "photo_a.jpg"), "orange", True)
jpeg(os.path.join(out_dir, "photo_b.jpg"), "teal", True)
open(os.path.join(out_dir, "fake.jpg"), "wb").write(b"<html>not an image</html>")
json.dump({"je_id": je_id, "token": main.token, "request_id": main.request_id, "cancel_token": other.token,
           "cancel_id": other.request_id, "company_id": company_id}, open(os.path.join(out_dir, "setup.json"), "w"))
print("SETUP OK", je_id, main.request_id, other.request_id)
