"""R319: پیامک و پیام‌رسان‌ها پس از فرایند — ربات رسمی بله/تلگرام/ایتا/روبیکا، درگاه عمومی واتس‌اپ، و قاعدهٔ «پس از رویداد X،
الگوی Y برای Z» روی موتور گردش کار (پشت کلید). ارتباط بیرونی با پاسخ ساختگی سنجیده می‌شود (بدون اینترنت)."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r319"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

import requests

from peecha.db.models.crm import Message
from peecha.services import commercial_partners as partners
from peecha.services import sms_gateway
from peecha.services.crm import communication as comm
from peecha.services.crm import messengers as msg

calls = []


class _Resp:
    def __init__(self, url):
        self.status_code = 200
        self.text = ""
        self._json = {"status": "OK"} if "rubika" in url else {"ok": True, "result": {}}

    def json(self):
        return self._json


def _fake_post(url, **kw):
    calls.append(("POST", url, kw))
    return _Resp(url)


def _fake_get(url, **kw):
    calls.append(("GET", url, kw))
    return _Resp(url)


requests.post, requests.get = _fake_post, _fake_get


def last_message():
    with new_session() as s:
        return s.scalar(select(Message).order_by(Message.message_id.desc()))


def message_count():
    with new_session() as s:
        return s.scalar(select(func.count()).select_from(Message))


# --- ۱۳: کانال‌ها و تنظیمات --------------------------------------------------------------------------------
check({"BALE", "TELEGRAM", "EITAA", "RUBIKA", "WHATSAPP", "SMS"} <= set(comm.CHANNELS), "all messengers in the communication hub")
check([s.channel for s in msg.list_settings(company_id)] == ["BALE", "TELEGRAM", "EITAA", "RUBIKA", "WHATSAPP"],
      "one settings row per messenger")
check(raises(lambda: msg.save_setting(company_id, uid, "BALE", secret="", is_active=True), "توکن"),
      "cannot switch on a bot without its token")
check(raises(lambda: msg.save_setting(company_id, uid, "WHATSAPP", secret="https://wa.example/send", is_active=True), "{phone}"),
      "gateway address must contain {phone} and {text}")
for ch, token in (("BALE", "bale-token"), ("TELEGRAM", "tg-token"), ("EITAA", "eitaa-token"), ("RUBIKA", "rubika-token")):
    msg.save_setting(company_id, uid, ch, secret=token, is_active=True)
msg.save_setting(company_id, uid, "WHATSAPP", secret="https://wa.example/send?to={phone}&msg={text}", is_active=True)
with new_session() as s:
    raw = s.execute(text("SELECT secret_encrypted FROM crm.messenger_settings WHERE channel = 'BALE'")).scalar()
check(raw is not None and b"bale-token" not in bytes(raw), "bot token stored encrypted")
check(all(s.is_active and s.has_secret for s in msg.list_settings(company_id)), "all five configured")
ok, info = msg.test_setting(company_id, "BALE")
check(ok and calls[-1][1] == "https://tapi.bale.ir/botbale-token/getMe", f"bot connection check ({info})")

cust = partners.create_customer_detail_account(company_id, "C-1", "فروشگاه نمونه", mobile="09120000001")
msg.set_chat_id(company_id, cust, "BALE", "5550001")
msg.set_chat_id(company_id, cust, "EITAA", "eitaa-77")
msg.set_chat_id(company_id, cust, "RUBIKA", "b0rubika")
check(raises(lambda: msg.set_chat_id(company_id, cust, "WHATSAPP", "x"), "فقط"), "WhatsApp uses the mobile, not a chat id")

calls.clear()
comm.send_message(company_id, uid, "BALE", "سلام {نام}", customer_id=cust)
m = last_message()
check(m.status_code == "SENT" and m.recipient == "5550001" and m.body == "سلام فروشگاه نمونه", "Bale bot message sent to the chat id")
check(calls and calls[-1][1] == "https://tapi.bale.ir/botbale-token/sendMessage" and calls[-1][2]["json"]["chat_id"] == "5550001",
      "official Bale Bot API used")
comm.send_message(company_id, uid, "EITAA", "پیام ایتا", customer_id=cust)
check(last_message().status_code == "SENT" and calls[-1][1] == "https://eitaayar.ir/api/eitaa-token/sendMessage"
      and calls[-1][2]["data"]["chat_id"] == "eitaa-77", "Eitaa bot (Eitaayar) message")
comm.send_message(company_id, uid, "RUBIKA", "پیام روبیکا", customer_id=cust)
check(last_message().status_code == "SENT" and calls[-1][1] == "https://botapi.rubika.ir/v3/rubika-token/sendMessage",
      "Rubika bot API message")
comm.send_message(company_id, uid, "WHATSAPP", "پیام واتس‌اپ", customer_id=cust)
check(last_message().status_code == "SENT" and calls[-1][0] == "GET" and "to=09120000001" in calls[-1][1],
      "WhatsApp through the generic URL gateway with the mobile")
comm.send_message(company_id, uid, "TELEGRAM", "بدون شناسه", customer_id=cust)
check(last_message().status_code == "FAILED" and "نشانی" in (last_message().error_message or ""),
      "no chat id: message logged as failed, nothing crashes")
msg.save_setting(company_id, uid, "RUBIKA", secret=None, is_active=False)
comm.send_message(company_id, uid, "RUBIKA", "خاموش", customer_id=cust)
check(last_message().status_code == "FAILED" and "خاموش" in last_message().error_message, "switched-off bot does not send")
msg.save_setting(company_id, uid, "RUBIKA", secret=None, is_active=True)

# --- ۱۴: پیام پس از فرایند -----------------------------------------------------------------------------------
from peecha.services.workflow import events as wf_events, notify as wf_notify, scheduler as wf_scheduler  # noqa: F401 -- مثل برنامه (shell_window)

sms_gateway.set_sms_gateway(company_id, "https://sms.example/send?to={phone}&text={text}", "GET", True)
events = {e.event_type: e for e in msg.event_choices()}
check("CUSTOMER_CREATED" in events and any(k.startswith("SALES_INVOICE") for k in events), f"process events offered ({len(events)})")
tpl = comm.save_template(company_id, uid, code="WELCOME", name="خوش‌آمد", channel="SMS", body="{نام} عزیز، به {شرکت} خوش آمدید.")
r1 = msg.save_rule(company_id, uid, name="خوش‌آمد پیامکی", event_type="CUSTOMER_CREATED", channel="SMS", template_id=tpl)
r2 = msg.save_rule(company_id, uid, name="خبر مشتری تازه در گروه بله", event_type="CUSTOMER_CREATED", channel="BALE",
                   body="مشتری تازه: {عنوان}", recipient="FIXED", target="-100999")
rules = msg.list_rules(company_id)
check(len(rules) == 2 and all(r.is_active for r in rules) and rules[0].event_label.startswith("مشتری جدید"), "two active rules")
check(raises(lambda: msg.save_rule(company_id, uid, name="x", event_type="CUSTOMER_CREATED", channel="BALE", body="b",
                                   recipient="FIXED", target=""), "ثابت"), "fixed recipient needs a target")

before = message_count()
partners.create_customer_detail_account(company_id, "C-2", "مشتری خاموش", mobile="09120000002")
check(message_count() == before, "switch off: no message after the process")
engine_service.set_feature_enabled(company_id, msg.FEATURE, True)
calls.clear()
partners.create_customer_detail_account(company_id, "C-3", "شرکت آفتاب", mobile="09120000003")
with new_session() as s:
    new_msgs = list(s.scalars(select(Message).where(Message.message_id > 0).order_by(Message.message_id.desc()).limit(2)))
by_channel = {m.channel: m for m in new_msgs}
sms = by_channel.get("SMS")
bale = by_channel.get("BALE")
check(sms is not None and sms.status_code == "SENT" and sms.recipient == "09120000003" and sms.body.startswith("شرکت آفتاب عزیز"),
      f"after customer creation the template went to the counterparty by SMS ({sms and sms.body})")
check(bale is not None and bale.status_code == "SENT" and bale.recipient == "-100999" and "شرکت آفتاب" in bale.body,
      "and the fixed Bale group got its notice")
check(any("sms.example" in c[1] for c in calls) and any(c[1].endswith("/sendMessage") for c in calls), "both gateways called")
msg.set_rule_active(company_id, uid, r2, False)
before = message_count()
partners.create_customer_detail_account(company_id, "C-4", "مشتری چهارم", mobile="09120000004")
check(message_count() == before + 1, "paused rule sends nothing; the other still works")
msg.delete_rule(company_id, uid, r2)
check(len(msg.list_rules(company_id)) == 1, "rule removed (archived when it has history)")

# --- رابط کاربری -------------------------------------------------------------------------------------------------
from PySide6.QtWidgets import QApplication, QPushButton
import re

app = QApplication.instance() or QApplication([])
from peecha.ui import app_style

app_style.install(app)
from peecha.ui.screens.messaging_settings import MessengersPanel, ProcessMessagesPanel
from peecha.ui.screens.system_settings import SystemSettingsScreen

letters = re.compile(r"[A-Za-z؀-ۿ]{2,}")
mp = MessengersPanel()
mp.refresh()
check(mp.t_channels.rowCount() == 5 and mp.feature.isChecked() and mp.t_chats.rowCount() == 3, "messengers panel lists bots, gateway and chat ids")
check(mp.edit_channel(values={"secret": "new-token", "base_url": "", "is_active": True}, channel="TELEGRAM"), "edit a bot from the panel")
check(mp.edit_chat(new=True, values={"party": cust, "channel": "TELEGRAM", "chat_id": "777"}) and mp.t_chats.rowCount() == 4,
      "add a chat id from the panel")
pp = ProcessMessagesPanel()
pp.refresh()
check(pp.t_rules.rowCount() == 1 and pp.off_note.isHidden(), "rules panel")
rid = pp.edit_rule(new=True, values={"name": "تشکر پس از تصویب فاکتور", "event_type": next(k for k in events if k.startswith("SALES_INVOICE")),
                                     "channel": "WHATSAPP", "template_id": None, "body": "فاکتور {شماره} به مبلغ {مبلغ} تصویب شد.",
                                     "recipient": "COUNTERPARTY", "target": "", "notify_user_id": None})
check(rid and pp.t_rules.rowCount() == 2, "new rule from the panel")
bad = [b.text() for w in (mp, pp) for b in w.findChildren(QPushButton) if letters.search(b.text() or "")]
check(not bad, f"icon buttons only ({bad})")
ss = SystemSettingsScreen()
crm_tab = ss.tabs.widget([ss.tabs.tabText(i) for i in range(ss.tabs.count())].index("ارتباط با مشتری"))
labels = [crm_tab.tabText(i) for i in range(crm_tab.count())]
check({"پیام‌رسان‌ها", "پیام پس از فرایند"} <= set(labels), f"settings › CRM sub-tabs ({labels})")
from peecha.ui.screens.inventory_settings import _FeatureToggleTab

inv = _FeatureToggleTab()
inv.refresh()
check(msg.FEATURE not in inv._checkboxes, "messaging switch not duplicated in inventory settings")

finish()
