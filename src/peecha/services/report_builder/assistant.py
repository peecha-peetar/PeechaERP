"""R376: دستیار پرسش از داده — فقط‌خواندنی.

- پرسش فارسی به یک «طرح گزارش‌ساز» تبدیل و با همان موتور گزارش‌ساز و با مجوز و شعبه‌های خود کاربر اجرا می‌شود؛ دستیار
  به هیچ جدولی جز مجموعه‌داده‌های گزارش‌ساز دسترسی ندارد و چیزی ثبت یا تغییر نمی‌دهد.
- هر پاسخ منبعش را نشان می‌دهد (داده، بازهٔ تاریخ و فیلترها) و همان طرح را می‌توان در گزارش‌ساز باز کرد.
- درخواست عملیات (صدور فاکتور، سند، پرداخت، تایید، حذف و ...) انجام نمی‌شود؛ فقط فرم مربوط پیشنهاد می‌شود تا خود کاربر
  آن را باز، بررسی و ثبت کند (تایید انسانی).
- فهم پرسش با قاعده‌های ثابت است. اگر کلید هوش مصنوعی در تنظیمات باشد و کاربر بخواهد، پرسشی که با قاعده‌ها فهمیده نشد
  (فقط متن پرسش و فهرست ستون‌ها، نه داده) برای تبدیل به طرح فرستاده می‌شود و طرح برگشتی پیش از اجرا اعتبارسنجی می‌شود.
- هر پرسش با نوع و داده‌اش ثبت می‌شود.
"""

from __future__ import annotations

import datetime
import decimal
import json
import re
from dataclasses import dataclass, field
from typing import Callable

import jdatetime
from sqlalchemy import select

from peecha import numerals
from peecha.db.base import new_session
from peecha.db.models.reporting import AssistantQuery
from peecha.services.report_builder import engine
from peecha.services.report_builder.datasets import DATASETS
from peecha.services.report_builder.engine import Definition, Filter

ZERO = decimal.Decimal(0)
EXAMPLES = [
    "فروش این ماه به تفکیک مشتری", "۵ کالای پرفروش ماه گذشته", "فروش امسال به تفکیک ماه", "خرید هفته گذشته به تفکیک تامین‌کننده",
    "موجودی کارتن", "دستورهای تولید دیرکرد", "مانده حساب صندوق", "کارهای من",
]
# درخواست عملیات ← (کد منو، نام فرم)؛ دستیار فقط فرم را پیشنهاد می‌کند
_ACTION_FORMS = [
    (("فاکتور فروش", "فروش"), "SALES_INVOICE", "فاکتور فروش"), (("فاکتور خرید", "خرید"), "PURCH_INVOICE", "فاکتور خرید"),
    (("پرداخت", "واریز"), "TREASURY_PAYMENT", "سند پرداخت"), (("دریافت",), "TREASURY_RECEIPT", "سند دریافت"),
    (("سند", "حساب"), "GL_JE", "صدور سند حسابداری"), (("سفارش",), "SALES_ORDER", "سفارش فروش"), (("حواله",), "INV_ISSUE", "حواله"),
]
_ACTION_VERBS = ("ثبت کن", "صادر کن", "بزن", "پرداخت کن", "واریز کن", "حذف کن", "پاک کن", "تایید کن", "تأیید کن", "ویرایش کن",
                 "عوض کن", "بساز", "ایجاد کن", "ارسال کن", "بفرست", "باطل کن", "برگشت بزن", "انجام بده")
_DIMENSIONS = [("گروه کالا", "item_group"), ("تامین کننده", "party"), ("مشتری", "party"), ("کالا", "item_name"), ("شعبه", "branch"),
               ("انبار", "warehouse"), ("ماه", "date:MONTH"), ("روز", "date:DAY"), ("سال", "date:YEAR")]


@dataclass
class Source:
    label: str
    details: list[tuple[str, str]]
    definition: Definition | None = None


@dataclass
class SuggestedAction:
    nav_code: str
    label: str


@dataclass
class Answer:
    question: str
    intent: str
    text: str
    headers: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    totals: list | None = None
    sources: list[Source] = field(default_factory=list)
    action: SuggestedAction | None = None
    used_ai: bool = False
    understood: bool = True


def normalize(text: str) -> str:
    text = numerals.to_ascii_digits(text or "").replace("ي", "ی").replace("ك", "ک").replace("‌", " ").replace("ـ", "")
    text = text.replace("آ", "آ").replace("أ", "ا").replace("ۀ", "ه").replace("ة", "ه")
    return re.sub(r"\s+", " ", text).strip()


def _has(text: str, *words: str) -> bool:
    return any(w in text for w in words)


# --- بازهٔ تاریخ ---------------------------------------------------------------------------------------------
def _jalali_month_start(d: datetime.date) -> datetime.date:
    j = jdatetime.date.fromgregorian(date=d)
    return jdatetime.date(j.year, j.month, 1).togregorian()


def period(text: str, today: datetime.date) -> tuple[datetime.date, datetime.date, str] | None:
    """بازهٔ تاریخ گفته‌شده در پرسش، یا None."""
    m = re.search(r"(\d+) (روز|هفته|ماه) (گذشته|اخیر|قبل)", text)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        days = n * {"روز": 1, "هفته": 7, "ماه": 30}[unit]
        return today - datetime.timedelta(days=days), today, f"{n} {unit} گذشته"
    if "امروز" in text:
        return today, today, "امروز"
    if "دیروز" in text:
        d = today - datetime.timedelta(days=1)
        return d, d, "دیروز"
    week_start = today - datetime.timedelta(days=(today.weekday() + 2) % 7)   # شنبه
    if _has(text, "هفته گذشته", "هفته قبل", "هفته پیش"):
        return week_start - datetime.timedelta(days=7), week_start - datetime.timedelta(days=1), "هفتهٔ گذشته"
    if _has(text, "این هفته", "هفته جاری"):
        return week_start, today, "این هفته"
    month_start = _jalali_month_start(today)
    if _has(text, "ماه گذشته", "ماه قبل", "ماه پیش"):
        end = month_start - datetime.timedelta(days=1)
        return _jalali_month_start(end), end, "ماه گذشته"
    if _has(text, "این ماه", "ماه جاری"):
        return month_start, today, "این ماه"
    j = jdatetime.date.fromgregorian(date=today)
    if _has(text, "سال گذشته", "سال قبل", "پارسال"):
        return jdatetime.date(j.year - 1, 1, 1).togregorian(), jdatetime.date(j.year, 1, 1).togregorian() - datetime.timedelta(days=1), "سال گذشته"
    if _has(text, "امسال", "سال جاری", "این سال"):
        return jdatetime.date(j.year, 1, 1).togregorian(), today, "امسال"
    return None


# --- قاعده‌ها -------------------------------------------------------------------------------------------------
def _dimension(text: str, party_word: str) -> str | None:
    for word, key in _DIMENSIONS:
        if word == "تامین کننده" and party_word != "تامین کننده":
            continue
        if word == "مشتری" and party_word != "مشتری":
            continue
        if re.search(rf"(تفکیک|بر اساس|براساس|هر|به ازای) {word}", text) or re.search(rf"{word} ?(ها|های)? ?(پر|بیشترین|برتر)", text) \
                or re.search(rf"(پر ?فروش ?ترین|پر ?خرید ?ترین|بیشترین|برترین|بهترین) {word}", text) \
                or re.search(rf"\d+ {word}", text):
            return key
    return None


def _top_n(text: str) -> int | None:
    if not _has(text, "پر فروش", "پرفروش", "پر خرید", "بیشترین", "برترین", "بهترین", "تاپ"):
        return None
    m = re.search(r"(\d+) ", text)
    return int(m.group(1)) if m and 0 < int(m.group(1)) <= 100 else 5


def _trade(text: str, today: datetime.date, purchase: bool) -> tuple[Definition, str]:
    dataset = "purchase_lines" if purchase else "sales_lines"
    party = "تامین کننده" if purchase else "مشتری"
    span = period(text, today) or (_jalali_month_start(today), today, "این ماه")
    filters = [Filter("date", "BETWEEN", span[0], span[1])]
    dim = _dimension(text, party)
    top = _top_n(text)
    if top and dim is None:
        dim = "item_name"
    if dim is None:
        definition = Definition(dataset, ["doc_type", "quantity", "net_amount", "total"], filters, group=True, count_rows=True)
    elif dim.startswith("date:"):
        definition = Definition(dataset, ["date", "net_amount", "total"], filters, group=True, date_group=dim[5:], sort_key="date")
    else:
        definition = Definition(dataset, [dim, "quantity", "net_amount"], filters, group=True, sort_key="net_amount", sort_desc=True,
                                limit=top)
    return definition, span[2]


def _stock(text: str) -> Definition:
    rest = re.sub(r".*موجودی", "", text).strip()
    rest = re.sub(r"^(کالا|کالای|انبار|فعلی|لحظه ای|چقدر|چند|است|هست|ی)\b ?", "", rest).strip(" ?؟")
    rest = re.sub(r" (چقدر|چند|است|هست|داریم|کجاست)( است)?$", "", rest).strip(" ?؟")
    filters = [Filter("item_name", "CONTAINS", rest)] if rest and not _has(rest, "تفکیک", "همه") else []
    if _has(text, "تفکیک انبار", "هر انبار", "به تفکیک انبار") or filters:
        return Definition("stock", ["item_name", "warehouse", "on_hand", "free", "value"], filters, sort_key="item_name")
    return Definition("stock", ["item_group", "on_hand", "value"], filters, group=True, sort_key="value", sort_desc=True)


def _production(text: str, today: datetime.date) -> Definition:
    if _has(text, "دیر", "عقب", "تاخیر", "تأخیر"):
        return Definition("production_orders", ["order_code", "item_name", "status", "due_date", "remaining_qty", "late_days"],
                          [Filter("late_days", "GT", "0")], sort_key="late_days", sort_desc=True)
    span = period(text, today)
    filters = [Filter("start_date", "BETWEEN", span[0], span[1])] if span else []
    return Definition("production_orders", ["status", "planned_qty", "done_qty", "remaining_qty"], filters, group=True, count_rows=True)


def _account(text: str, today: datetime.date) -> tuple[Definition, str]:
    m = re.search(r"(مانده|گردش|بدهکار|بستانکار)(ی)? (حساب|سرفصل)? ?(.+)", text)
    name = (m.group(4) if m else "").strip(" ?؟")
    name = re.sub(r" (چقدر|چند|است|هست|چیست|شد)( است)?$", "", name).strip()
    name = re.sub(r"\b(این ماه|ماه گذشته|امسال|امروز|دیروز|هفته گذشته|سال گذشته|ماه قبل|این هفته)\b", "", name).strip()
    filters = []
    if re.fullmatch(r"\d+", name or ""):
        filters.append(Filter("account_code", "STARTS", name))
    elif name:
        filters.append(Filter("account_name", "CONTAINS", name))
    span = period(text, today)
    if span:
        filters.append(Filter("date", "BETWEEN", span[0], span[1]))
    return (Definition("journal_lines", ["account_code", "account_name", "debit", "credit", "balance"], filters, group=True,
                       sort_key="account_code"), span[2] if span else "از ابتدا")


def interpret(question: str, today: datetime.date | None = None) -> tuple[str, Definition | None, str]:
    """(نوع پرسش، طرح، توضیح بازه). نوع: ACTION، TASKS، SALES، PURCHASE، STOCK، PRODUCTION، ACCOUNT یا UNKNOWN."""
    today = today or datetime.date.today()
    text = normalize(question)
    if _has(text, *_ACTION_VERBS):
        return "ACTION", None, ""
    if _has(text, "کارهای من", "کارتابل", "کار های من", "منتظر تایید من", "کارهام"):
        return "TASKS", None, ""
    if "موجودی" in text and not _has(text, "مانده حساب"):
        return "STOCK", _stock(text), ""
    if _has(text, "دستور تولید", "دستورهای تولید", "دستور های تولید", "تولید"):
        return "PRODUCTION", _production(text, today), ""
    if _has(text, "مانده", "گردش حساب", "بدهکار", "بستانکار") or re.search(r"\bحساب\b", text):
        definition, span = _account(text, today)
        return "ACCOUNT", definition, span
    if _has(text, "خرید", "خریدیم", "تامین کننده"):
        definition, span = _trade(text, today, purchase=True)
        return "PURCHASE", definition, span
    if _has(text, "فروش", "فروختیم", "مشتری", "درآمد"):
        definition, span = _trade(text, today, purchase=False)
        return "SALES", definition, span
    return "UNKNOWN", None, ""


# --- هوش مصنوعی اختیاری -------------------------------------------------------------------------------------------
def ai_available(company_id: int) -> bool:
    from peecha.services import commercial_social

    return commercial_social.has_ai_api_key(company_id)


def _catalog(company_id: int, user_id: int) -> str:
    lines = []
    for d in engine.available(company_id, user_id):
        cols = ", ".join(f"{c.key}({c.kind}:{c.label})" for c in d.columns)
        lines.append(f"- {d.code}: {d.label}. ستون‌ها: {cols}")
    return "\n".join(lines)


def _gemini(company_id: int) -> Callable[[str], str]:
    from peecha.db.models.commercial import AiContentSettings
    from peecha.integrations.ai import gemini_client
    from peecha.services import ecommerce_credentials

    with new_session() as session:
        row = session.get(AiContentSettings, company_id)
    api_key = ecommerce_credentials.decrypt_credentials(row.api_key_encrypted).get("api_key", "") if row else ""
    return lambda prompt: gemini_client.generate_text(api_key, prompt)


def plan_with_ai(company_id: int, user_id: int, question: str, today: datetime.date, ask: Callable[[str], str]) -> Definition:
    prompt = (
        "تو فقط پرسش کاربر را به یک طرح JSON برای گزارش‌ساز تبدیل می‌کنی؛ داده‌ای نمی‌بینی و جز JSON چیزی ننویس.\n"
        f"امروز {today.isoformat()} است. مجموعه‌داده‌ها:\n{_catalog(company_id, user_id)}\n"
        'قالب: {"dataset": "...", "columns": ["..."], "filters": [{"key": "...", "op": "...", "value": "...", "value2": null}], '
        '"group": false, "date_group": "DAY|MONTH|YEAR", "aggregates": {}, "count_rows": false, "sort_key": null, "sort_desc": false, '
        '"limit": null}\n'
        "شرط‌ها: متن CONTAINS/EQ/NE/STARTS، تاریخ FROM/TO/BETWEEN با مقدار YYYY-MM-DD، عدد EQ/NE/GT/GE/LT/LE/BETWEEN.\n"
        f"پرسش: {question}"
    )
    raw = ask(prompt)
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        raise ValueError("پاسخ هوش مصنوعی طرح معتبری نداشت.")
    data = json.loads(m.group(0))
    for f in data.get("filters", []):
        for k in ("value", "value2"):
            v = f.get(k)
            if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                f[k] = {"date": v}
    definition = Definition.from_json(data)
    engine.validate(definition)
    return definition


# --- پاسخ -------------------------------------------------------------------------------------------------------
def _log(company_id: int, user_id: int, question: str, intent: str, dataset: str | None, used_ai: bool) -> None:
    with new_session() as session:
        session.add(AssistantQuery(company_id=company_id, user_id=user_id, question=question[:500], intent_code=intent,
                                   dataset_code=dataset, used_ai=used_ai))
        session.commit()


def _money(value) -> str:
    return numerals.format_amount(value)


def _qty(value) -> str:
    return numerals.to_persian_digits(f"{decimal.Decimal(value).normalize():f}")


def _summary(intent: str, result: engine.Result, span: str) -> str:
    when = f" ({span})" if span else ""
    if not result.rows:
        return f"برای این پرسش{when} داده‌ای پیدا نشد."
    if intent in ("SALES", "PURCHASE"):
        label = "فروش" if intent == "SALES" else "خرید"
        net_index = next(i for i, h in enumerate(result.headers) if "مبلغ پس از تخفیف" in h)
        total = result.totals[net_index] if result.totals else ZERO
        return f"جمع {label}{when}: {_money(total)} (پس از تخفیف و منهای برگشت‌ها). ریز در جدول آمده است."
    if intent == "STOCK":
        index = next(i for i, h in enumerate(result.headers) if "موجودی" in h and "ارزش" not in h)
        return f"موجودی: {_qty(result.totals[index])} در {numerals.to_persian_digits(str(len(result.rows)))} ردیف."
    if intent == "ACCOUNT":
        index = result.headers.index(next(h for h in result.headers if "مانده" in h))
        balance = result.totals[index] if result.totals else ZERO
        side = "بدهکار" if balance >= 0 else "بستانکار"
        return f"ماندهٔ حساب‌ها{when}: {_money(abs(balance))} {side} ({numerals.to_persian_digits(str(len(result.rows)))} حساب)."
    if intent == "PRODUCTION":
        return f"{numerals.to_persian_digits(str(len(result.rows)))} ردیف دستور تولید{when}."
    return f"{numerals.to_persian_digits(str(len(result.rows)))} ردیف پیدا شد."


def ask(company_id: int, user_id: int, question: str, *, use_ai: bool = False, today: datetime.date | None = None,
        ai: Callable[[str], str] | None = None) -> Answer:
    question = (question or "").strip()
    if not question:
        raise ValueError("پرسش خود را بنویسید.")
    today = today or datetime.date.today()
    intent, definition, span = interpret(question, today)
    used_ai = False
    if intent == "ACTION":
        text = normalize(question)
        form = next(((code, label) for words, code, label in _ACTION_FORMS if _has(text, *words)), None)
        _log(company_id, user_id, question, intent, None, False)
        return Answer(question, intent, "دستیار فقط می‌خواند و هیچ سند، فاکتور، پرداخت یا تاییدی ثبت نمی‌کند. "
                      + (f"فرم «{form[1]}» را باز کنید، اطلاعات را بررسی و خودتان ثبت کنید." if form else
                         "این کار را از فرم مربوط خودتان انجام دهید."),
                      action=SuggestedAction(*form) if form else None)
    if intent == "TASKS":
        from peecha.services import operational_tasks

        tasks = operational_tasks.list_operational_tasks(company_id, user_id)
        counts: dict[str, int] = {}
        for t in tasks:
            counts[t.kind_label] = counts.get(t.kind_label, 0) + 1
        rows = [[label, n] for label, n in sorted(counts.items(), key=lambda kv: -kv[1])]
        _log(company_id, user_id, question, intent, None, False)
        return Answer(question, intent, f"{numerals.to_persian_digits(str(len(tasks)))} کار در کارتابل شماست.", ["نوع کار", "تعداد"],
                      ["TEXT", "INT"], rows, sources=[Source("کارتابل من", [])])
    if intent == "UNKNOWN" and use_ai:
        try:
            definition = plan_with_ai(company_id, user_id, question, today, ai or _gemini(company_id))
            intent, used_ai = "AI", True
        except Exception as exc:  # noqa: BLE001 -- پاسخ نامعتبر یا خطای سرویس: مثل پرسش نفهمیده رفتار می‌شود
            _log(company_id, user_id, question, "UNKNOWN", None, True)
            return Answer(question, "UNKNOWN", f"پرسش فهمیده نشد ({exc}). نمونه‌ها: " + "، ".join(EXAMPLES[:4]), understood=False,
                          used_ai=True)
    if definition is None:
        _log(company_id, user_id, question, "UNKNOWN", None, False)
        return Answer(question, "UNKNOWN", "پرسش فهمیده نشد. نمونه‌ها: " + "، ".join(EXAMPLES), understood=False)
    dataset = DATASETS[definition.dataset]
    if not engine.can_use(company_id, user_id, definition.dataset):
        _log(company_id, user_id, question, intent, definition.dataset, used_ai)
        return Answer(question, intent, f"به داده‌های «{dataset.label}» دسترسی ندارید؛ دستیار فقط داده‌هایی را نشان می‌دهد که خودتان "
                      "اجازهٔ دیدنشان را دارید.", understood=True, used_ai=used_ai)
    result = engine.run(company_id, user_id, definition, question)
    _log(company_id, user_id, question, intent, definition.dataset, used_ai)
    return Answer(question, intent, _summary(intent, result, span), result.headers, result.kinds, result.rows, result.totals,
                  [Source(result.source, result.filters_text, definition)], used_ai=used_ai)


def history(company_id: int, user_id: int, limit: int = 30) -> list[tuple[datetime.datetime, str]]:
    with new_session() as session:
        return [(r.created_at, r.question) for r in session.scalars(
            select(AssistantQuery).where(AssistantQuery.company_id == company_id, AssistantQuery.user_id == user_id)
            .order_by(AssistantQuery.query_id.desc()).limit(limit))]
