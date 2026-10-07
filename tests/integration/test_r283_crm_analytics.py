import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r283"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from sqlalchemy import func
from peecha.db.models.accounting import CustomerDetail
from peecha.db.models.commercial import CustomerProfile
from peecha.db.models.crm import CustomerScore, Segment
from peecha.services.crm import activities as acts, analytics, customer360 as c360, insights, segments as seg
check = fx.check
ago = lambda n: today - datetime.timedelta(days=n)
later = today + datetime.timedelta(days=60)

# ===== داده: الف خریدار منظم، ب خریدار قدیمی خاموش با بدهی معوق، ج تازه و ویژه، د بدون خرید =====
for n in range(170, 0, -10):
    fx.invoice(cust_a, 1_000_000, date=ago(n), due_date=later)
for n in range(170, 90, -10):
    fx.invoice(cust_b, 1_000_000, date=ago(n), due_date=later)
fx.invoice(cust_b, 1_000_000, date=ago(120), due_date=ago(90))
cust_c = partners_service.create_customer(company_id, "C-3", "فروشگاه ج", fast_track=True, mobile="09120000003")
cust_d = partners_service.create_customer(company_id, "C-4", "فروشگاه د", fast_track=True, mobile="09120000004")
fx.invoice(cust_c, 1_000_000, date=ago(5), due_date=later)
with new_session() as s:
    s.get(CustomerProfile, cust_c).priority_code = "VIP"
    det = s.get(CustomerDetail, cust_a) or CustomerDetail(detail_account_id=cust_a)
    det.customer_type_code = "WHOLESALER"
    s.add(det)
    s.commit()
    n_profiles = s.scalar(select(func.count()).where(CustomerProfile.company_id == company_id))

# ===== امتیازها =====
check(analytics.refresh_scores(company_id) == n_profiles, "scores computed for every customer profile")
sc = {r["customer_detail_account_id"]: r for r in analytics.list_scores(company_id)}
a, b, c, d = sc[cust_a], sc[cust_b], sc[cust_c], sc[cust_d]
check(a["frequency_365"] == 17 and a["recency_days"] == 10 and a["monetary_365"] == D(17_000_000), "RFM inputs from posted invoices")
check(a["avg_gap_days"] == D("10.0"), "average purchase interval")
check(a["rfm_segment"] == "CHAMPIONS" and a["health_band"] == "HEALTHY" and a["churn_band"] == "LOW",
      f"regular buyer is champion/healthy ({a['rfm_segment']}, {a['health_score']}, {a['churn_risk']})")
check(b["churn_band"] == "HIGH" and b["health_band"] != "HEALTHY", f"silent buyer with overdue debt is at risk ({b['churn_risk']})")
check(b["overdue_amount"] == D(1_000_000), "overdue amount from settlements")
check({"interval", "frequency_drop", "amount_drop", "debt"} <= set(b["factors"]["churn"]), "churn factors are explainable")
check(c["rfm_segment"] == "NEW" and c["invoice_count_total"] == 1, "single recent purchase is a new customer")
check(d["rfm_segment"] == "NO_PURCHASE" and d["health_band"] == "ATTENTION" and d["churn_risk"] == 0, "no purchases")
check(a["clv_historical"] == D(17_000_000) and a["clv_predicted"] > 0, f"historical CLV = net revenue − COGS ({a['clv_historical']})")
check(b["clv_predicted"] < a["clv_predicted"], "churn risk lowers predicted CLV")
rows = analytics.compute_scores(company_id)
acts_b = next(r for r in rows if r["customer_detail_account_id"] == cust_b)["actions"]
check({"FOLLOW_UP_SALES", "COLLECTION"} <= {x["code"] for x in acts_b}, "next best actions for silent indebted customer")
check(next(r for r in rows if r["customer_detail_account_id"] == cust_d)["next_best_action"] == "معرفی محصولات و اولین سفارش",
      "first-sale action for customer without purchase")
check(analytics.list_scores(company_id)[0]["customer_detail_account_id"] == cust_b, "default order: highest churn first")
check(sum(m["count"] for m in analytics.rfm_matrix(company_id)) == n_profiles, "RFM matrix covers all customers")

# شکایت باز سلامت را کم می‌کند
before = a["health_score"]
acts.create_activity(company_id, uid, acts.ActivityFields("COMPLAINT", "تأخیر ارسال", customer_detail_account_id=cust_a))
analytics.refresh_scores(company_id)
after = analytics.get_score(company_id, cust_a)
check(after.open_complaints == 1 and after.factors["health"]["complaints"] == 5 and after.factors["health"]["engagement"] == 5,
      f"open complaint lowers complaint factor, the activity raises engagement ({before} → {after.health_score})")

# Provider قابل جایگزینی (آمادهٔ هوش مصنوعی)
class Fixed(insights.RuleBasedProvider):
    def health(self, s):
        return insights.Prediction(99, "HEALTHY", {"model": 99})
insights.set_provider(Fixed())
check(next(r for r in analytics.compute_scores(company_id) if r["customer_detail_account_id"] == cust_d)["health_score"] == 99,
      "custom insights provider is used")
insights.set_provider(None)
check(isinstance(insights.get_provider(), insights.RuleBasedProvider), "provider reset to rule-based")

# ===== سگمنت پویا =====
segs = {s.code: s for s in seg.list_segments(company_id)}
check(len([s for s in segs.values() if s.is_system]) == 10, "10 system segments seeded")
seg.list_segments(company_id)
with new_session() as s:
    check(s.scalar(select(func.count()).where(Segment.company_id == company_id)) == 10, "system segments idempotent")
m = lambda code: set(seg.members(company_id, segs[code].segment_id))
check(m("VIP") == {cust_a, cust_c}, f"VIP = champions + VIP priority ({m('VIP')})")
check(cust_b in m("AT_RISK") and cust_a not in m("AT_RISK"), "at-risk segment")
check(cust_b in m("DORMANT") and cust_a not in m("DORMANT"), "dormant segment (no purchase in 90 days)")
check(m("NEW") == {cust_c}, "new segment uses relative date (days_ago)")
check(m("WHOLESALE") == {cust_a}, "wholesale segment from ERP customer type")
rule = {"all": [{"field": "frequency_365", "op": ">=", "value": 5}, {"not": {"field": "churn_band", "op": "=", "value": "HIGH"}}]}
check(seg.evaluate(company_id, rule) == [cust_a], "custom rule with nested not")
check(seg.count(company_id, {"any": [{"field": "rfm_segment", "op": "in", "value": ["NEW", "NO_PURCHASE"]},
                                     {"field": "overdue_amount", "op": ">", "value": 0}]}) == 3, "any + in operators")
check(seg.count(company_id, {"all": []}) == n_profiles, "empty rule = all customers")
sid = seg.save_segment(company_id, uid, code="loyal_wh", name="عمده‌فروش وفادار", rule=rule)
check(seg.get_segment(company_id, sid).code == "LOYAL_WH", "custom segment saved")
check(fx.raises(lambda: seg.save_segment(company_id, uid, code="LOYAL_WH", name="x", rule=rule), "تکراری"), "duplicate code rejected")
check(fx.raises(lambda: seg.save_segment(company_id, uid, code="BAD", name="x", rule={"all": [{"field": "nope", "op": "="}]}), "ناشناخته"),
      "unknown field rejected")
check(fx.raises(lambda: seg.save_segment(company_id, uid, code="BAD", name="x", rule={"all": [{"field": "churn_risk", "op": "~"}]}), "عملگر"),
      "unknown operator rejected")
check(fx.raises(lambda: seg.delete_segment(company_id, uid, segs["VIP"].segment_id), "سیستمی"), "system segment cannot be deleted")
counts = seg.refresh_counts(company_id)
check(counts[sid] == 1 and seg.get_segment(company_id, sid).member_count == 1, "member counts cached")
check({s.code for s in seg.segments_of_customer(company_id, cust_a)} >= {"VIP", "LOYAL_WH", "WHOLESALE"}, "segments of one customer")

# ===== پروندهٔ ۳۶۰ =====
d360 = c360.customer_360(company_id, cust_a)
an = d360["analytics"]
check(an and an["health_label"] and an["rfm_label"] == "قهرمانان" and "مشتریان ویژه (VIP)" in an["segments"], "360 shows analytics block")

# ===== API =====
from fastapi.testclient import TestClient
from peecha_api.main import app
from peecha.services.crm import roles_setup
from peecha.services import roles as roles_service
client = TestClient(app)
login = lambda u: {"Authorization": "Bearer " + client.post("/auth/login", json={"username": u, "password": "secret123"}).json()["access_token"]}
hdr, vis = login("admin"), login("visitor1")
check(client.get("/crm/segments", headers=vis).status_code == 403, "analytics needs permission")
roles = roles_setup.ensure_role_templates(company_id)
roles_service.set_user_role(visitor.user_id, roles["CRM_USER"], company_id, True)
check(client.get("/crm/analytics/scores", headers=vis).status_code == 200, "CRM_USER can view analytics")
check(client.post("/crm/analytics/refresh", headers=vis).status_code == 403, "CRM_USER cannot recompute")
check(client.post("/crm/analytics/refresh", headers=hdr).json()["customers"] == n_profiles, "API refresh")
scores = client.get("/crm/analytics/scores", params={"churn_band": "HIGH"}, headers=hdr).json()
check([x["customer_detail_account_id"] for x in scores] == [cust_b], "API scores filtered by churn band")
check(client.get("/crm/analytics/scores", params={"segment_id": sid}, headers=hdr).json()[0]["customer_detail_account_id"] == cust_a,
      "API scores filtered by segment")
summ = client.get("/crm/analytics/summary", headers=hdr).json()
check(len(summ["rfm"]) == len(analytics.RFM_SEGMENTS) and "health" in summ["bands"], "API summary")
check("churn_risk" in client.get("/crm/segments/fields", headers=hdr).json()["fields"], "API segment field catalog")
check(client.post("/crm/segments/preview", json={"rule": rule}, headers=hdr).json()["count"] == 1, "API preview")
check(client.post("/crm/segments", json={"code": "X", "name": "x", "rule": {"all": [{"field": "zz"}]}}, headers=hdr).status_code == 400,
      "API invalid rule is 400")
new = client.post("/crm/segments", json={"code": "API_SEG", "name": "سگمنت API", "rule": {"all": [{"field": "rfm_segment", "op": "=", "value": "NEW"}]}},
                  headers=hdr).json()["segment_id"]
check([x["customer_detail_account_id"] for x in client.get(f"/crm/segments/{new}/members", headers=hdr).json()] == [cust_c], "API members")
check(client.put(f"/crm/segments/{new}", json={"code": "API_SEG", "name": "سگمنت ۲", "rule": {"all": []}}, headers=hdr).status_code == 200,
      "API update segment")
check(client.delete(f"/crm/segments/{new}", headers=vis).status_code == 403, "CRM_USER cannot delete segments")
check(client.delete(f"/crm/segments/{new}", headers=hdr).status_code == 200, "API delete segment")
check(client.get(f"/crm/customers/{cust_a}/360", headers=hdr).json()["analytics"]["rfm_segment"] == "CHAMPIONS", "API 360 analytics")

# ===== UI =====
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens import crm as crm_ui
scr = crm_ui.AnalyticsScreen()
scr.dialog_runner = lambda dlg: True
scr.refresh()
check(scr.t.rowCount() == n_profiles and scr.t_seg.rowCount() >= 11, "analytics screen lists customers and segments")
crm_ui.set_combo(scr.churn, "HIGH")
check(scr.t.rowCount() == 1, "screen churn filter")
crm_ui.set_combo(scr.churn, None)
dlg = crm_ui.SegmentDialog(seg.get_segment(company_id, sid))
check(dlg.values()["rule"]["all"] == [rule["all"][0]], f"segment dialog round-trips simple conditions ({dlg.values()['rule']})")
ui_sid = scr.edit_segment(new=True, values={"code": "UI_SEG", "name": "سگمنت فرم",
                                            "rule": {"all": [{"field": "health_band", "op": "=", "value": "HEALTHY"}]}})
check(ui_sid and any(s.segment_id == ui_sid for s in scr._segs), "segment created from screen")
scr.recompute()
check(analytics.get_score(company_id, cust_a) is not None, "screen recompute")
scr.t.selectRow(0)
aid = scr.follow_up(values={"activity_type_code": "FOLLOW_UP", "subject": ""})
check(aid and acts.get_activity(company_id, aid).customer_detail_account_id == cust_b, "follow-up from suggested action")

fx.finish()
