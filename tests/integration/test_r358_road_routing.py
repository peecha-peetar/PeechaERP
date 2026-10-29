"""R358: فاصلهٔ جاده‌ای نشان برای مسیر پخش (با سرویس ساختگی؛ سرور واقعی نشان در دسترس آزمون نیست): کلید رمزشده و الزامی،
قالب درخواست (Api-Key، origins/destinations)، ماتریس تکه‌تکهٔ ۱۰×۱۰، ترتیب و طول مسیر با فاصلهٔ جاده‌ای، خطای سرویس ←
خط مستقیم با یادداشت و بدون تلاش پشت‌سرهم، ثبت آخرین خطا، و فرم تنظیمات."""
import json, os, sys, urllib.parse
os.environ["PEECHA_DB_NAME"] = "peecha_test_r358"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.commercial import RoadRoutingSettings
from peecha.services import distribution_routing as routing, road_distance as rd

depot = (35.69, 51.39)
pts = {"a": (35.70, 51.40), "e": (35.72, 51.42), "b": (35.75, 51.45)}
river = {pts["a"], pts["e"]}  # بین الف و هـ پل نیست: راه جاده‌ای ۵۰ کیلومتر
calls = []


def road_km(p, q):
    return 50.0 if {p, q} == river else routing.distance_km(p, q) * 1.3


def fake(url, headers):
    calls.append((url, headers))
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    parse = lambda text: [tuple(float(x) for x in p.split(",")) for p in text.split("|")]  # noqa: E731
    origins, destinations = parse(q["origins"][0]), parse(q["destinations"][0])
    rows = [{"elements": [{"status": "Ok", "distance": {"value": round(road_km(o, d) * 1000), "text": ""},
                           "duration": {"value": 60, "text": ""}} for d in destinations]} for o in origins]
    return 200, json.dumps({"status": "Ok", "rows": rows})


def down(url, headers):
    calls.append((url, headers))
    raise rd.RoadDistanceError("اتصال به سرویس نقشه برقرار نشد: شبکه قطع است")


rd.urllib_transport = fake
check(not rd.is_on(company_id) and rd.road_matrix(company_id, list(pts.values())) is None and not calls,
      "off by default: straight-line distances, no call")
check(raises(lambda: rd.save_settings(company_id, uid, "NESHAN"), "کلید") and raises(
    lambda: rd.save_settings(company_id, uid, "NONE", api_url="http://api.neshan.org"), "https"), "a key and https are required")
rd.save_settings(company_id, uid, "NESHAN", "service.secret-key-123")
with new_session() as s:
    blob = s.get(RoadRoutingSettings, company_id).api_key_encrypted
check(b"secret-key-123" not in bytes(blob) and rd.get_settings(company_id).has_key, "the API key is stored encrypted")
rd.save_settings(company_id, uid, "NESHAN", "", vehicle_type="motorcycle")
check(rd.client_for(company_id).api_key == "service.secret-key-123", "saving with an empty key keeps the old key")

stops = [routing.RouteStop(i, i, 0, *pts[k]) for i, k in enumerate("aeb", start=1)]
straight = routing._plan(stops, depot, ordered=False)
check([s.document_id for s in straight.stops] == [1, 2, 3] and not straight.road, "straight line: a, e, b")
plan = routing._plan([routing.RouteStop(i, i, 0, *pts[k]) for i, k in enumerate("aeb", start=1)], depot, ordered=False,
                     company_id=company_id)
url, headers = calls[0]
check(headers == {"Api-Key": "service.secret-key-123"} and url.startswith("https://api.neshan.org/v1/distance-matrix?")
      and "type=motorcycle" in url and "origins=35.690000,51.390000|" in url, f"request format ({url[:120]})")
legs = [road_km(depot, pts["a"]), road_km(pts["a"], pts["b"]), road_km(pts["b"], pts["e"])]
check([s.document_id for s in plan.stops] == [1, 3, 2] and plan.road and abs(plan.total_km - sum(legs)) < 0.05,
      f"by road the river crossing is avoided: a, b, e ({[s.document_id for s in plan.stops]}, {plan.total_km} km)")
n = len(calls)
routing._plan([routing.RouteStop(i, i, 0, *pts[k]) for i, k in enumerate("aeb", start=1)], depot, ordered=True, company_id=company_id)
check(len(calls) == n, "the same points reuse the cached matrix")

many = [(35.60 + i * 0.01, 51.30 + i * 0.01) for i in range(12)]
calls.clear()
matrix = rd.road_matrix(company_id, many)
check(len(calls) == 4 and all(v is not None for row in matrix for v in row) and len(matrix) == 12,
      f"12 points are asked in 10×10 blocks ({len(calls)} requests)")

rd.clear_cache()
rd.urllib_transport = down
calls.clear()
failed = routing._plan([routing.RouteStop(i, i, 0, *pts[k]) for i, k in enumerate("aeb", start=1)], depot, ordered=False,
                       company_id=company_id)
check(not failed.road and "خط مستقیم" in failed.note and [s.document_id for s in failed.stops] == [1, 2, 3],
      f"service down: straight line with a note ({failed.note})")
routing._plan([routing.RouteStop(1, 1, 0, *pts["a"]), routing.RouteStop(2, 2, 0, *pts["b"])], depot, ordered=True,
              company_id=company_id)
check(len(calls) == 1 and "قطع" in (rd.get_settings(company_id).last_error or ""),
      "no repeated waiting on a dead network; the last error is recorded")
rd.clear_cache()
rd.urllib_transport = lambda url, headers: (401, json.dumps({"status": "ERROR", "message": "Invalid Api Key"}))
check(raises(lambda: rd.test_connection(company_id), "Invalid Api Key"), "an API error is reported with its message")

# فرم تنظیمات
rd.urllib_transport = fake
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.road_routing_settings import RoadRoutingSettingsTab

tab = RoadRoutingSettingsTab()
tab.refresh()
check(tab.provider_combo.currentData() == "NESHAN" and "ذخیره شده" in tab.key_field.placeholderText() and not tab.key_field.text()
      and all(not b.text().strip() or len(b.text()) <= 2 for b in tab.findChildren(QPushButton)),
      "the settings tab shows the provider, hides the key and uses icon buttons")
check(tab.test() and "کیلومتر" in tab.status_label.text(), f"connection test from the tab ({tab.status_label.text()})")
tab.provider_combo.setCurrentIndex(tab.provider_combo.findData("NONE"))
check(tab.save() and not rd.is_on(company_id), "switching back to straight line")

finish()
