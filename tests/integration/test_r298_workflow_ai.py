"""R298: آمادگی هوش مصنوعی -- رابط سرویس، سرویس پیش‌فرض بدون اینترنت، توصیف فارسی ← پیش‌نویس امن."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r298"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from peecha.services import commercial_partners as partners, roles as roles_service
from peecha.services.workflow import ai, definitions as defs, registry, runtime, tasks
from peecha.services.workflow.common import WorkflowError
check, raises = fx.check, fx.raises

registry.ensure_loaded()
roles_service.ensure_catalog()
P = ai.NullProvider()

# ===== برداشت از متن فارسی =====
s1 = P.draft_from_text(company_id, "اگر سفارش خرید بیشتر از ۵۰۰ میلیون بود، اول مدیر بعد مالی تایید کند و بعد سفارش تصویب شود؛ "
                                   "تا تایید نشده قفل باشد")
check(s1.entity_type == "PURCHASE_ORDER", "document type recognized")
check(s1.trigger == {"type": "EVENT", "events": ["PURCHASE_ORDER_CONFIRMED"], "gate": True}, "event trigger with approval lock")
check(s1.condition == {"field": "total_amount", "op": ">", "value": 500_000_000}, "amount condition from Persian number and unit")
check([lv["label"] for lv in s1.levels] == ["تایید مدیر", "تایید مالی"], "approval steps in spoken order")
check(s1.actions == ["entity.approve"], "post-approval action recognized")
check(any("سفارش خرید" in a for a in s1.assumptions), "assumptions explained to the user")

s2 = P.draft_from_text(company_id, "درخواست مرخصی را اول مدیر مستقیم و بعد منابع انسانی تایید کنند")
check(s2.entity_type == "LEAVE_REQUEST" and s2.trigger["events"] == ["LEAVE_REQUEST_SUBMITTED"], "leave request on submit")
check([lv["approvers"][0]["kind"] for lv in s2.levels] == ["REPORTING_MANAGER", "PERMISSION"], "direct manager then HR")
check(s2.reject_actions == ["entity.reject"], "rejection recorded on the document")
s3 = P.draft_from_text(company_id, "سند حسابداری با مبلغ مالیات زیاد را مدیرعامل تایید کند و سند دائم شود")
check([lv["label"] for lv in s3.levels] == ["تایید مدیرعامل"], "«مالیات» is not taken as finance approval")
check(s3.actions == ["entity.approve"] and s3.entity_type == "JOURNAL_ENTRY", "journal becomes permanent after approval")
s4 = P.draft_from_text(company_id, "یک فرایند تایید ساده")
check(s4.entity_type is None and s4.trigger == {"type": "MANUAL"} and s4.levels[0]["approvers"] == [{"kind": "MANAGERS"}],
      "unknown document: general manual process approved by managers")
check(P.draft_from_text(company_id, "   ") is None, "empty text gives nothing")

# ===== مسیر امن: پیش‌نمایش، اعتبارسنجی، ساخت پیش‌نویس =====
check(raises(lambda: ai.draft(company_id, ""), "خالی"), "empty description refused")
check(raises(lambda: ai.draft(company_id, "سفارش خرید"), "مرحلهٔ تایید"), "text without steps refused with guidance")
d = ai.draft(company_id, "اگر سفارش خرید بیشتر از ۵۰۰ میلیون بود، اول مدیر بعد مالی تایید کند و بعد سفارش تصویب شود؛ "
                         "تا تایید نشده قفل باشد")
check(d.ok and d.graph["trigger"]["gate"] is True, "draft validates against the engine")
check(any("تایید «تایید مالی»" in x for x in d.summary), "readable Persian summary")
check(d.simulation[0].startswith("✔") and any("تصویب" in x for x in d.simulation), "simulation passes the condition")
check(d.risky and "تصویب سند" in d.risky[0], "high-risk automatic action highlighted")
did = ai.create_from_draft(company_id, uid, d, name="تایید خرید بزرگ")
row = defs.get_definition(company_id, did)
check(row.status_code == "DRAFT" and row.template_code == "AI", "only a draft is created (never auto-published)")
did2 = ai.create_from_draft(company_id, uid, d)
check(defs.get_definition(company_id, did2).code != row.code, "unique codes for repeated drafts")

# انتشار توسط مدیر و اجرای واقعی
defs.publish(company_id, uid, did)
supplier = partners.create_supplier(company_id, "S-9", "تامین‌کننده", fast_track=True)
po = documents_service.create_document(company_id, visitor.user_id, "PURCHASE_ORDER", today, documents_service.DocumentHeaderFields(
    counterparty_detail_account_id=supplier, currency_id=company.base_currency_id, warehouse_id=warehouse_id))
documents_service.add_line(po, company_id, item_id=item_a, uom_id=pcs, quantity=D(1), quantity_base=D(1), unit_price=D(700_000_000))
documents_service.confirm_document(po, company_id, visitor.user_id)
inst = runtime.list_instances(company_id, entity_type="PURCHASE_ORDER", entity_id=po)
check(len(inst) == 1 and inst[0].definition_id == did, "published AI draft runs on real purchase orders")
check(raises(lambda: documents_service.approve_document(po, company_id, uid), "در جریان تایید"), "its approval lock works")

# ===== سرویس بیرونی: خروجی‌اش هم اعتبارسنجی می‌شود =====
class BadProvider:
    name = "آزمایشی"

    def __init__(self, spec):
        self.spec = spec

    def draft_from_text(self, company_id, text):
        return self.spec

    def summarize_task(self, company_id, task_id):
        return "خلاصه"


ai.set_provider(BadProvider(ai.DraftSpec("NO_SUCH", "x", {"type": "MANUAL"}, levels=[{"label": "a", "approvers": [{"kind": "MANAGERS"}]}])))
check(raises(lambda: ai.draft(company_id, "هرچه"), "وجود ندارد"), "unknown document type from provider refused")
ai.set_provider(BadProvider(ai.DraftSpec("PURCHASE_ORDER", "x", {"type": "MANUAL"}, actions=["entity.drop_database"])))
check(raises(lambda: ai.draft(company_id, "هرچه"), "ناشناخته"), "unknown action from provider refused")
ai.set_provider(BadProvider(ai.DraftSpec("PURCHASE_ORDER", "x", {"type": "EVENT", "events": ["NOPE"]},
                                         levels=[{"label": "a", "approvers": [{"kind": "MANAGERS"}]}])))
bad = ai.draft(company_id, "هرچه")
check(not bad.ok and raises(lambda: ai.create_from_draft(company_id, uid, bad), "ایراد"), "invalid draft cannot be created")
ai.set_provider(ai.NullProvider())

# خلاصهٔ کار برای تصمیم سریع
t = tasks.list_tasks(company_id, entity_type="PURCHASE_ORDER", entity_id=po, status="OPEN")[0]
summary = ai.get_provider().summarize_task(company_id, t.task_id)
check("جمع کل" in summary and t.title.split(" — ")[0] in summary, "task summary built from document context")

# ===== فرم =====
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
qapp = QApplication.instance() or QApplication([])
qapp.setLayoutDirection(Qt.RightToLeft)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
from peecha import session as sess  # noqa: E402
from peecha.db.models.core import Company  # noqa: E402
from peecha.db.models.security import User  # noqa: E402
with new_session() as s:
    sess.current_user = s.get(User, uid)
    sess.current_company = s.get(Company, company_id)
    s.expunge_all()
from peecha.ui.screens import workflow_studio as st  # noqa: E402
dlg = st.AiDraftDialog()
dlg.text.setPlainText("درخواست مرخصی را اول مدیر مستقیم و بعد منابع انسانی تایید کنند")
check(dlg.make_preview() and "برداشت از متن شما" in dlg.preview.toHtml() and dlg.create_button.isEnabled(), "preview in dialog")
check(all(len(b.text()) <= 2 for b in (dlg.preview_button, dlg.create_button)), "dialog uses icon buttons")
pls = st.ProcessListScreen()
pls.reload()
new_id = pls.new_from_text("اگر سفارش خرید بیشتر از ۱۰۰ میلیون بود مدیر تایید کند و تصویب شود")
check(new_id is not None and defs.get_definition(company_id, new_id).status_code == "DRAFT", "build from text on process list")

fx.finish()
