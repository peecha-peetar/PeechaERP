"""R376: دستیار فقط‌خواندنی: فهم پرسش فارسی (بازهٔ شمسی، تفکیک، پرفروش‌ترین‌ها، موجودی، دیرکرد تولید، ماندهٔ حساب، کارتابل)،
اجرا با مجوز خود کاربر، نمایش منبع، درخواست عملیات فقط با پیشنهاد فرم و بدون ثبت، هوش مصنوعی اختیاری فقط با متن پرسش و
طرح اعتبارسنجی‌شده، ردپای پرسش‌ها؛ و فرم."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r376"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

import jdatetime
from peecha import numerals
from sqlalchemy import update
from peecha.db.models.accounting import JournalEntry
from peecha.db.models.commercial import CommercialDocument
from peecha.db.models.reporting import AssistantQuery
from peecha.services import commercial_documents as documents_service, users as users_service
from peecha.services.report_builder import assistant

today_j = jdatetime.date.fromgregorian(date=today)
month_start = jdatetime.date(today_j.year, today_j.month, 1).togregorian()
last_month_day = month_start - datetime.timedelta(days=1)
check(assistant.interpret("فروش این ماه به تفکیک مشتری", today)[1].filters[0].value == month_start, "this Jalali month")
intent, d, span = assistant.interpret("۵ کالای پرفروش ماه گذشته", today)
check(intent == "SALES" and d.limit == 5 and d.columns[0] == "item_name" and d.sort_desc and span == "ماه گذشته"
      and d.filters[0].value2 == last_month_day, "top five items of last month")
check(assistant.interpret("فروش امسال به تفکیک ماه", today)[1].date_group == "MONTH", "by Jalali month")
check(assistant.interpret("خرید هفته گذشته به تفکیک تامین‌کننده", today)[1].dataset == "purchase_lines", "purchases by supplier")
check(assistant.interpret("مانده حساب ۱۲۱", today)[1].filters[0].op == "STARTS", "account by code (Persian digits)")
check(assistant.interpret("لطفا یک فاکتور فروش صادر کن", today)[0] == "ACTION", "requests to act are recognized")

wh_sales = locations_service.create_warehouse(company_id, "SALE", "انبار فروش", WF(allow_negative_stock=True))
customer = dimensions_service.create_customer(company_id, "C1", "مشتری الف")
receive(pk, 40, 500)


def invoice(day, item_id, qty, price):
    doc = documents_service.create_document(company_id, uid, "SALES_INVOICE", day, documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=customer, currency_id=company.base_currency_id, warehouse_id=wh_sales))
    documents_service.add_line(doc, company_id, item_id=item_id, uom_id=base_uom(item_id), quantity=D(qty), quantity_base=D(qty),
                               unit_price=D(price))
    with new_session() as s:
        s.execute(update(CommercialDocument).where(CommercialDocument.document_id == doc).values(status_code="CONFIRMED"))
        s.commit()


invoice(today, fg, 2, 1000)
invoice(today, pk, 10, 50)
invoice(last_month_day, fg, 7, 1000)

a = assistant.ask(company_id, uid, "فروش این ماه به تفکیک مشتری")
check(a.intent == "SALES" and len(a.rows) == 1 and a.rows[0][2] == D(2500) and numerals.format_amount(D(2500)) in a.text,
      f"sales this month by customer ({a.text})")
check(a.sources[0].definition is not None and a.sources[0].label.startswith("ردیف‌های فروش")
      and any(k == "تاریخ" for k, _v in a.sources[0].details), "the answer shows its source and date range")
a = assistant.ask(company_id, uid, "۵ کالای پرفروش ماه گذشته")
check([r[0] for r in a.rows] == ["محصول A"] and a.rows[0][2] == D(7000), f"top items of last month ({a.rows})")
a = assistant.ask(company_id, uid, "موجودی کارتن")
check(a.intent == "STOCK" and a.rows[0][2] == D(40) and "۴۰" in a.text, f"stock of an item ({a.text})")
a = assistant.ask(company_id, uid, "مانده حساب موجودی کالا")
check(a.intent == "ACCOUNT" and len(a.rows) == 1 and a.rows[0][4] == D(20000) and "بدهکار" in a.text, f"account balance ({a.rows}, {a.text})")
check(assistant.ask(company_id, uid, "کارهای من").intent == "TASKS", "my tasks")

with new_session() as s:
    entries_before = s.scalar(select(func.count()).select_from(JournalEntry))
a = assistant.ask(company_id, uid, "یک سند پرداخت به تامین‌کننده بزن")
with new_session() as s:
    entries_after = s.scalar(select(func.count()).select_from(JournalEntry))
check(a.intent == "ACTION" and a.action.nav_code == "TREASURY_PAYMENT" and "ثبت نمی‌کند" in a.text and entries_before == entries_after,
      "a payment request only suggests the form; nothing is recorded")
a = assistant.ask(company_id, uid, "هوا چطوره")
check(not a.understood and "نمونه" in a.text, "unknown questions get examples")

staff = users_service.create_user("staff", "کارشناس", "secret123", None, company.default_language_id, False, [company_id], company_id).user_id
a = assistant.ask(company_id, staff, "فروش این ماه")
check("دسترسی ندارید" in a.text and not a.rows, "the assistant answers only from data the user may see")

prompts = []


def fake_ai(reply):
    def call(prompt):
        prompts.append(prompt)
        return reply
    return call


a = assistant.ask(company_id, uid, "اقلام انبار را نشان بده", use_ai=True,
                  ai=fake_ai('طرح: {"dataset": "stock", "columns": ["item_code", "on_hand"], "filters": [{"key": "on_hand", "op": "GT", "value": "1"}]}'))
check(a.intent == "AI" and a.used_ai and len(a.rows) == 1 and "کارتن" not in prompts[-1] and "40" not in prompts[-1],
      "AI only turns the question into a validated plan; no data in the prompt")
a = assistant.ask(company_id, uid, "یک چیز عجیب", use_ai=True, ai=fake_ai('{"dataset": "stock", "columns": ["password"]}'))
check(not a.understood and a.used_ai, "an invalid AI plan is refused")
a = assistant.ask(company_id, staff, "اقلام انبار", use_ai=True, ai=fake_ai('{"dataset": "sales_lines", "columns": ["party"]}'))
check("دسترسی ندارید" in a.text, "AI plans obey the same permissions")
check(assistant.ai_available(company_id) is False, "AI is off without a key")
with new_session() as s:
    logged = s.scalar(select(func.count()).select_from(AssistantQuery).where(AssistantQuery.user_id == uid))
check(logged == 9 and len(assistant.history(company_id, uid)) == 9, f"every question is logged ({logged})")

# فرم
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.assistant import AssistantScreen
from peecha.ui.screens.report_builder import ReportBuilderScreen


class FakeWindow:
    def __init__(self):
        self.opened = []
        self.builder = ReportBuilderScreen()
        self.builder.refresh()

    def open_screen(self, code, then=None):
        self.opened.append(code)
        if then:
            then(self.builder)


win = FakeWindow()
screen = AssistantScreen(win)
screen.refresh()
check(screen.history_list.count() == 9 and not screen.ai_box.isEnabled(), "history and AI switch")
screen.question_field.setText("فروش این ماه به تفکیک کالا")
check(screen.ask() and screen.result_table.rowCount() == 3 and screen.source_label.text().startswith("منبع:"), "answer with source")
check(screen.open_in_builder() and win.opened[-1] == "REPORTS_BUILDER" and win.builder.result is not None
      and len(win.builder.result.rows) == 2 and win.builder.report_id is None, "the same plan opens in the report builder")
check(not screen.open_form_button.isEnabled(), "no form for read-only questions")
screen.question_field.setText("فاکتور فروش جدید ثبت کن")
check(screen.ask() and screen.open_form_button.isEnabled() and screen.open_form() and win.opened[-1] == "SALES_INVOICE",
      "a request to act opens the form for the user to fill and save")
check(all(len(b.text()) <= 2 for b in screen.findChildren(QPushButton) if b.text()), "icon buttons only")

finish()
