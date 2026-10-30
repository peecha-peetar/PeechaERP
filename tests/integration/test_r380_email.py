"""R380: ارسال ایمیل با SMTP: تنظیم و رمزنگاری رمز، اعتبارسنجی، ورود به سرور، متن فارسی و نسخهٔ HTML راست‌به‌چپ، خطای ورود
در «آخرین خطا»، پیام ایمیلی مرکز ارتباطات، کمپین ایمیلی (ارسال هنگام اجرا و ناموفق برای مخاطب بی‌ایمیل) و اعلان کانال ایمیل؛
و فرم تنظیمات. سرور SMTP ساختگی محلی است؛ STARTTLS و SSL واقعی این‌جا آزموده نمی‌شوند."""
import base64, email, os, socketserver, sys, threading
os.environ["PEECHA_DB_NAME"] = "peecha_test_r380"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from email import policy
from peecha.db.models.crm import Message, MessengerSetting
from peecha.db.models.security import Notification
from peecha.services import messaging_email as me, users as users_service
from peecha.services.crm import campaigns, communication as comm, leads
from peecha.services.workflow import notify

received = []


class FakeSmtp(socketserver.StreamRequestHandler):
    def handle(self):
        def w(text):
            self.wfile.write((text + "\r\n").encode())

        w("220 fake ESMTP")
        data_mode, buf, rcpts = False, [], []
        while True:
            line = self.rfile.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            if data_mode:
                raw = line.rstrip(b"\r\n")
                if raw == b".":
                    received.append({"to": rcpts[:], "message": email.message_from_bytes(b"\r\n".join(buf), policy=policy.default)})
                    buf, rcpts, data_mode = [], [], False
                    w("250 OK")
                else:
                    buf.append(raw[1:] if raw.startswith(b"..") else raw)
                continue
            cmd = text[:4].upper()
            if cmd == "EHLO":
                w("250-fake")
                w("250-AUTH PLAIN")
                w("250 8BITMIME")
            elif cmd == "AUTH":
                creds = base64.b64decode(text.split()[2]).split(b"\0")
                w("235 OK" if creds[1:] == [b"erp", b"pw-123"] else "535 authentication failed")
            elif cmd == "RCPT":
                rcpts.append(text.split(":", 1)[1].strip("<> "))
                w("250 OK")
            elif cmd == "DATA":
                data_mode = True
                w("354 go")
            elif cmd == "QUIT":
                w("221 bye")
                break
            else:
                w("250 OK")


server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), FakeSmtp)
threading.Thread(target=server.serve_forever, daemon=True).start()
PORT = server.server_address[1]


def refused(fn, needle):
    try:
        fn()
    except ValueError as exc:
        return needle in str(exc)
    return False


S = dict(host="127.0.0.1", port=PORT, security="NONE", username="erp", from_address="noreply@shop.ir", from_name="فروشگاه پیچا")
check(refused(lambda: me.save_settings(company_id, uid, **{**S, "from_address": "bad"}), "فرستنده"), "sender address is checked")
check(refused(lambda: me.save_settings(company_id, uid, **{**S, "host": " "}), "سرور"), "host is required")
check(me.send_email(company_id, "a@b.ir", "x", "y") == (False, "سرور ایمیل تنظیم نشده یا خاموش است."), "nothing is sent before setup")
me.save_settings(company_id, uid, **S, password="pw-123")
with new_session() as s:
    raw = s.scalar(select(MessengerSetting.secret_encrypted).where(MessengerSetting.channel == "EMAIL"))
st = me.get_settings(company_id)
check(st.has_password and st.is_active and b"pw-123" not in bytes(raw), "the password is stored encrypted and never shown")
me.save_settings(company_id, uid, **S, password=None)
check(me.get_settings(company_id).has_password, "an empty password keeps the old one")
check(me.send_email(company_id, "not-an-address", "x", "y")[0] is False, "recipient address is checked")
ok, msg = me.test_settings(company_id, "admin@shop.ir")
m = received[-1]["message"]
check(ok and received[-1]["to"] == ["admin@shop.ir"] and m["Subject"] == "آزمون ایمیل پیچا" and "فروشگاه پیچا" in str(m["From"]),
      f"test email with Persian subject and sender name ({msg})")
plain = m.get_body(("plain",)).get_content()
html_part = m.get_body(("html",)).get_content()
check("تنظیمات سرور ایمیل" in plain and 'dir="rtl"' in html_part, "plain text and right-to-left HTML")

me.save_settings(company_id, uid, **S, password="wrong-pw")
ok, msg = me.test_settings(company_id, "admin@shop.ir")
check(not ok and "انجام نشد" in msg and "انجام نشد" in (me.get_settings(company_id).last_error or ""), "a login failure is reported and kept")
me.save_settings(company_id, uid, **S, password="pw-123")
me.test_settings(company_id, "admin@shop.ir")
check(me.get_settings(company_id).last_error is None, "the error clears after a successful send")

# پیام مرکز ارتباطات
count = len(received)
mid = comm.send_message(company_id, uid, "EMAIL", "سلام {name}، سفارش شما آماده است.", subject="سفارش", to="client@mail.ir")
with new_session() as s:
    row = s.get(Message, mid)
check(row.status_code == "SENT" and row.provider_code == "SMTP" and len(received) == count + 1 and received[-1]["message"]["Subject"] == "سفارش"
      and "سفارش شما آماده است" in received[-1]["message"].get_body(("plain",)).get_content(), "communication center email")

# کمپین ایمیلی
l1 = leads.create_lead(company_id, uid, leads.LeadFields("مریم", email="maryam@mail.ir"))
l2 = leads.create_lead(company_id, uid, leads.LeadFields("علی", mobile="09120000000"))
camp = campaigns.create_campaign(company_id, uid, campaigns.CampaignFields("جشنواره", campaign_type="EMAIL", message_text="تخفیف {name}"))
campaigns.add_leads(company_id, uid, camp, [l1, l2])
count = len(received)
result = campaigns.launch(company_id, uid, camp)
check(result.get("emails_sent") == 1 and result.get("emails_failed") == 1 and len(received) == count + 1
      and received[-1]["to"] == ["maryam@mail.ir"] and "تخفیف مریم" in received[-1]["message"].get_body(("plain",)).get_content(),
      f"campaign emails go out on launch ({result})")
from peecha.db.models.crm import CampaignMember
with new_session() as s:
    member_status = sorted((r.lead_id, r.status_code) for r in s.scalars(select(CampaignMember).where(CampaignMember.campaign_id == camp)))
check(member_status == sorted([(l1, "SENT"), (l2, "FAILED")]), f"member delivery status ({member_status})")

# اعلان کانال ایمیل
users_service.update_user(uid, "مدیر سیستم", "admin@shop.ir", company.default_language_id, True, True, [company_id], company_id)
notify.save_preference(company_id, uid, "WF_MESSAGE", email=True)
count = len(received)
notify.send(company_id, [uid], "WF_MESSAGE", "یادآوری جلسه", "ساعت ده")
notify.deliver_pending(company_id)
with new_session() as s:
    note = s.scalar(select(Notification).where(Notification.title == "یادآوری جلسه"))
check(note.channels.get("email") == "SENT" and len(received) == count + 1 and received[-1]["message"]["Subject"] == "یادآوری جلسه",
      f"notification by email ({note.channels})")
me.save_settings(company_id, uid, **S, is_active=False)
check(me.notify_user(company_id, uid, "x", "y") == "NOT_CONFIGURED", "switched off: not configured")

# فرم
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.messaging_settings import EmailSettingsPanel

panel = EmailSettingsPanel()
panel.refresh()
check(panel.host_field.text() == "127.0.0.1" and panel.password_field.text() == "" and "قبلی" in panel.password_field.placeholderText()
      and not panel.active_box.isChecked(), "the form loads the settings without the password")
panel.active_box.setChecked(True)
check(panel.save() and me.get_settings(company_id).is_active, "saved from the form")
panel.test_to_field.setText("boss@shop.ir")
check(panel.test() and received[-1]["to"] == ["boss@shop.ir"], "test email from the form")
check(all(len(b.text()) <= 2 for b in panel.findChildren(QPushButton) if b.text()), "icon buttons only")
server.shutdown()

finish()
