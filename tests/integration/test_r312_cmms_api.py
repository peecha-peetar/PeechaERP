"""R312: API موبایل تکنسین — اسکن برچسب، ثبت سریع درخواست (تکرار بی‌اثر)، عکس، کارهای من، چک‌لیست و ثبت انجام؛
دسترسی با نقش‌های آماده و «انجام‌شده» بدون آماده‌شدن ماشین."""
import base64
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r312_api"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mnt_fixture import *  # noqa: F401,F403
import mnt_fixture as fx
from fastapi.testclient import TestClient
from peecha_api.main import app
from peecha.services import roles as roles_service
from peecha.services import users as users_service
from peecha.services.maintenance import roles_setup

check, raises = fx.check, fx.raises
client = TestClient(app)
m1 = machine("M-01")
tech = users_service.create_user("tech1", "تکنسین یک", "secret123", None, None, False, [company_id], company_id)
nobody = users_service.create_user("nobody", "بی‌نقش", "secret123", None, None, False, [company_id], company_id)
roles_service.ensure_catalog()
roles = roles_setup.ensure_role_templates(company_id)
roles_service.set_user_role(tech.user_id, roles["MNT_TECHNICIAN"], company_id, True)
login = lambda u: {"Authorization": "Bearer " + client.post("/auth/login", json={"username": u, "password": "secret123"}).json()["access_token"]}  # noqa: E731
h = login("tech1")
qr = fa.qr_payload(fa.get_asset(company_id, m1))

r = client.get("/maintenance/equipment/lookup", params={"code": qr}, headers=h)
check(r.status_code == 200 and r.json()["code"] == "M-01" and r.json()["serial_no"] == "SN-M-01" and not r.json()["down_now"],
      f"scan → equipment card ({r.status_code})")
check(client.get("/maintenance/equipment/lookup", params={"code": "X"}, headers=h).status_code == 404, "unknown label → 404")
check(client.get("/maintenance/equipment/lookup", params={"code": qr}, headers=login("nobody")).status_code == 403,
      "user without a maintenance role → 403")

body = {"code": qr, "title": "صدای غیرعادی گیربکس", "machine_stopped": True, "severity_code": "HIGH", "scanned": True}
r1 = client.post("/maintenance/requests", json=body, headers={**h, "Idempotency-Key": "mob-req-1"})
r2 = client.post("/maintenance/requests", json=body, headers={**h, "Idempotency-Key": "mob-req-1"})
check(r1.status_code == 201 and r2.json()["request_id"] == r1.json()["request_id"], "offline retry with the same key → same request")
rid = r1.json()["request_id"]
check(mreq.get(company_id, rid).source_label == "اسکن برچسب" and asset_status(m1) == "UNDER_MAINTENANCE",
      "request from a scanned label; machine stopped → asset under maintenance")
check(client.post("/maintenance/requests", json={"title": "بدون تجهیز"}, headers=h).status_code == 400,
      "request without equipment → 400 with a clear message")
photo = client.post(f"/maintenance/requests/{rid}/photos",
                    json={"file_name": "leak.jpg", "content_base64": base64.b64encode(b"\xff\xd8img").decode()}, headers=h)
check(photo.status_code == 201, f"photo attached from the phone ({photo.status_code})")

wo = mreq.convert(company_id, uid, rid, wos.WorkOrderInput(asset_id=m1, work_type_code="EMERGENCY", title="تعمیر گیربکس",
                                                            tasks=[wos.TaskInput("قطع برق", is_safety=True),
                                                                   wos.TaskInput("دمای روغن", "NUMERIC", D(20), D(60), "درجه")]))
wos.assign(company_id, uid, wo, [tech.user_id])
mine = client.get("/maintenance/my-work-orders", headers=h).json()
check([x["work_order_id"] for x in mine] == [wo], "my work orders lists the assigned job")
check(client.post(f"/maintenance/work-orders/{wo}/start", headers=h).json()["ok"], "start from the phone")
d = client.get(f"/maintenance/work-orders/{wo}", headers=h).json()
check(len(d["tasks"]) == 2 and d["machine_down"], "detail with checklist; machine shown as stopped")
t1, t2 = d["tasks"]
check(client.post(f"/maintenance/tasks/{t1['task_id']}", json={"done": True}, headers=h).json()["is_ok"], "check task done")
bad = client.post(f"/maintenance/tasks/{t2['task_id']}", json={"value_numeric": "75"}, headers=h).json()
check(bad["is_ok"] is False, "measured value outside limits flagged")
client.post(f"/maintenance/tasks/{t2['task_id']}", json={"value_numeric": "45"}, headers=h)
lab1 = client.post(f"/maintenance/work-orders/{wo}/labor", json={"hours": "1.5"}, headers={**h, "Idempotency-Key": "lab-1"})
client.post(f"/maintenance/work-orders/{wo}/labor", json={"hours": "1.5"}, headers={**h, "Idempotency-Key": "lab-1"})
check(lab1.status_code == 200 and len(wos.get(company_id, wo).labor) == 1, "labour from the phone, retry not duplicated")
check(client.post(f"/maintenance/work-orders/{wo}/hold", json={"reason": "انتظار قطعه"}, headers=h).json()["ok"]
      and client.post(f"/maintenance/work-orders/{wo}/resume", headers=h).json()["ok"], "hold and resume")
c = client.post(f"/maintenance/work-orders/{wo}/complete", json={"note": "کاسه‌نمد تعویض شد"}, headers=h)
check(c.status_code == 200 and wos.get(company_id, wo).status_code == "COMPLETED" and asset_status(m1) == "UNDER_MAINTENANCE",
      "completed from the phone; machine stays out of service until test and release")
again = client.post(f"/maintenance/work-orders/{wo}/complete", json={"note": "x"}, headers=h)
check(again.status_code == 400 and "وضعیت" in again.json()["detail"], "second completion → 400 with reason")
check(client.get("/maintenance/my-work-orders", headers=h).json()[0]["status_code"] == "COMPLETED", "job still listed until closed")

fx.finish()
