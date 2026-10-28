"""R356: کارتابل یکپارچه — صف‌هایی که بیرون مانده بودند: مرخصی ارسال‌شده (بیرون از گردش کار)، ورود و خروج و اضافه‌کاری
منتظر تایید، تسویهٔ خودروی پخش (تایید انبار و حسابداری) و تیکت‌های ارجاع‌شده به کاربر با موعد تعهد زمانی؛ هر کدام فقط
برای کسی که اجازهٔ همان کار را دارد، با جزئیات، از سرویس موبایل هم دیده می‌شوند و از کارتابل دسکتاپ باز می‌شوند."""
import datetime, os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r356"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.db.models.inventory import VehicleSettlement
from peecha.db.models.security import Form
from peecha.services import commercial_partners as partners, hr, hr_attendance, hr_leave, payroll, payroll_overtime, roles, \
    users as users_service
from peecha.services.crm import tickets
from peecha.services.workflow import inbox

roles.ensure_catalog()
lang_id = company.default_language_id


def user(login, perms=()):
    u = users_service.create_user(login, login, "secret123", None, lang_id, False, [company_id], company_id).user_id
    if perms:
        role = roles.create_role(company_id, login.upper(), None)
        roles.set_user_role(u, role.role_id, company_id, True)
        with new_session() as s:
            for form, action in perms:
                roles.set_role_permission(role.role_id, s.scalar(select(Form.form_id).where(Form.code == form)), action, True)
    return u


hr_user = user("hr1", [("hr_leave_requests", "APPROVE"), ("hr_attendance_entries", "EDIT"), ("payroll_overtime_entries", "EDIT")])
van_user = user("van1", [("commercial_distribution_hub", "EDIT")])
agent = user("agent1")
plain = user("plain1")

org = hr.create_org_unit(company_id, "ADM", "اداری", None, None)
pos = hr.create_position(company_id, "CLK", "کارمند", org, None, 5)
emp = hr.create_employee(company_id, "E1", "علی", "رضایی", None, today, org, pos, D(100_000_000), None)
leave = hr_leave.create_request(company_id, uid, emp, "ANNUAL", today, today + datetime.timedelta(days=2), reason="سفر", submit=True)
hr_leave.create_request(company_id, uid, emp, "SICK", today + datetime.timedelta(days=10), today + datetime.timedelta(days=10))  # پیش‌نویس: کاری برای کسی نیست
for day in range(3):
    hr_attendance.create_attendance_record(company_id, emp, today - datetime.timedelta(days=day + 1), worked_hours=D(8))
period = payroll.create_period(company_id, 1405, 1, today.replace(day=1), today.replace(day=1) + datetime.timedelta(days=29))
rule = payroll_overtime.create_overtime_rule(company_id, "OVERTIME", D("1.4"), "ADDITIVE", None, today.replace(day=1), None)
payroll_overtime.create_overtime_entry(emp, period, rule, D(6))
with new_session() as s:
    s.add(VehicleSettlement(company_id=company_id, vehicle_warehouse_id=wh_rm, return_destination_warehouse_id=wh_rm,
                            settlement_date=today, submitted_by_user_id=uid))
    s.add(VehicleSettlement(company_id=company_id, vehicle_warehouse_id=wh_rm, return_destination_warehouse_id=wh_rm,
                            settlement_date=today, submitted_by_user_id=uid, status_code="WAREHOUSE_APPROVED"))
    s.commit()
customer = partners.create_customer(company_id, "C1", "فروشگاه مرکزی", fast_track=True)
ticket = tickets.create_ticket(company_id, uid, tickets.TicketFields(customer, "کالای معیوب", "COMPLAINT", "HIGH",
                                                                     assigned_to_user_id=agent))
tickets.create_ticket(company_id, uid, tickets.TicketFields(customer, "سؤال فاکتور", "INQUIRY", assigned_to_user_id=plain))


def kinds(user_id):
    return {w.extra.get("kind") or w.source for w in inbox.my_work(company_id, user_id)}


hr_kinds = kinds(hr_user)
check({"HR_LEAVE", "HR_ATTENDANCE", "HR_OVERTIME"} <= hr_kinds and not hr_kinds & {"VAN_SETTLE_WAREHOUSE", "TICKET"},
      f"the HR approver sees the submitted leave, pending attendance and overtime ({hr_kinds})")
leave_item = next(w for w in inbox.my_work(company_id, hr_user) if w.extra.get("kind") == "HR_LEAVE")
check(leave_item.ref_id == leave and "علی رضایی" in leave_item.subtitle and "استحقاقی" in leave_item.title,
      f"the leave card names the employee and type ({leave_item.title} / {leave_item.subtitle})")
attendance_item = next(w for w in inbox.my_work(company_id, hr_user) if w.extra.get("kind") == "HR_ATTENDANCE")
check(attendance_item.title.startswith("3 "), f"attendance is one summary card ({attendance_item.title})")
van_kinds = kinds(van_user)
check({"VAN_SETTLE_WAREHOUSE", "VAN_SETTLE_ACCOUNTING"} <= van_kinds and "HR_LEAVE" not in van_kinds,
      f"the distribution user sees both settlement steps ({van_kinds})")
check(kinds(plain) - {"TICKET"} == set(), "a user without these permissions only sees their own ticket")
ticket_item = next(w for w in inbox.my_work(company_id, agent) if w.source == "TICKET")
check(ticket_item.ref_id == ticket and ticket_item.priority_code == "HIGH" and ticket_item.due_at is not None
      and "کالای معیوب" in ticket_item.title and ticket_item.subtitle == "فروشگاه مرکزی",
      "the assigned ticket carries its priority and resolution due time")
d = inbox.detail(company_id, agent, ticket_item.key)
check(d["title"] == ticket_item.title and any("فروشگاه" in str(v) for _k, v in d["context"]), "the ticket detail opens")
check(inbox.detail(company_id, hr_user, leave_item.key)["title"] == leave_item.title, "the leave detail opens")
hr_kinds_all = {w.extra.get("kind") for w in inbox.my_work(company_id, uid)}
check({"HR_LEAVE", "HR_ATTENDANCE", "HR_OVERTIME", "VAN_SETTLE_WAREHOUSE", "VAN_SETTLE_ACCOUNTING"} <= hr_kinds_all,
      "the system administrator sees every queue")

# پس از تصمیم، کار از کارتابل می‌رود
hr_leave.approve(company_id, leave, hr_user)
hr_attendance.bulk_set_attendance_status([r.attendance_id for r in hr_attendance.list_attendance_records(company_id)], "APPROVED")
check(not {"HR_LEAVE", "HR_ATTENDANCE"} & kinds(hr_user), "decided leave and attendance leave the inbox")

# موبایل
from fastapi.testclient import TestClient
from peecha_api.main import app
client = TestClient(app)
token = client.post("/auth/login", json={"username": "van1", "password": "secret123"}).json()["access_token"]
resp = client.get("/workflow/inbox", headers={"Authorization": f"Bearer {token}"})
check(resp.status_code == 200 and any("تسویه" in (i.get("title") or "") for i in resp.json().get("items", [])),
      f"the mobile inbox lists the settlement steps ({resp.status_code})")

# دسکتاپ
from PySide6.QtWidgets import QApplication
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens import my_tasks
from peecha.ui.screens.workflow_center import open_work_item


class FakeMain:
    def __init__(self):
        self.opened = []

    def open_screen(self, code, then=None):
        self.opened.append(code)


main = FakeMain()
for kind, code in (("HR_LEAVE", "HR_LEAVE_REQUESTS"), ("HR_OVERTIME", "HR_PAYROLL_OVERTIME"),
                   ("VAN_SETTLE_WAREHOUSE", "SALES_DISTRIBUTION")):
    my_tasks.open_operational_task(main, kind, "", 1)
check(main.opened == ["HR_LEAVE_REQUESTS", "HR_PAYROLL_OVERTIME", "SALES_DISTRIBUTION"], f"each card opens its form ({main.opened})")
check(open_work_item(main, ticket_item) and main.opened[-1] == "CRM_TICKETS", "the ticket card opens the tickets form")
from peecha.ui.screens.crm import TicketsScreen

screen = TicketsScreen()
screen.refresh()
screen.mine.setChecked(True)  # فیلتر «ارجاع به من» تیکت کاربر دیگر را پنهان کرده است
check(screen.open_ticket(ticket) and screen._row() is not None and screen._row().ticket_id == ticket, "the tickets form selects the ticket")
inbox_screen = my_tasks.MyTasksScreen(main)
inbox_screen.refresh()
inbox_screen.source.setCurrentIndex(inbox_screen.source.findData("DOC"))
check(any("تسویهٔ خودرو" in w.title for w in inbox_screen.shown) and inbox_screen.source.findData("TICKET") >= 0,
      "the desktop inbox shows the new cards and lists tickets as a section")
tickets.resolve_ticket(company_id, agent, ticket, "کالا تعویض شد")
check("TICKET" not in kinds(agent), "a resolved ticket leaves the inbox")

finish()
