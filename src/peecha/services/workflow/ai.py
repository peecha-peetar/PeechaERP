"""آمادگی هوش مصنوعی گردش کار (R298): رابط یکسان سرویس هوشمند + سرویس پیش‌فرض بدون اینترنت.

مسیر همیشه یکی است و هوش مصنوعی هیچ‌وقت مستقیم چیزی را منتشر نمی‌کند:
    توصیف فارسی ← پیش‌نویس (مشخصات ویزارد) ← اعتبارسنجی ← پیش‌نمایش و شبیه‌سازی ← تایید کاربر (ساخت پیش‌نویس)
    ← انتشار جداگانه توسط مدیر
سرویس پیش‌فرض (NullProvider) با قواعد ساده و بدون ارسال داده به بیرون کار می‌کند؛ سرویس هوشمند بیرونی با
set_provider جایگزین می‌شود و فقط باید همین قرارداد را رعایت کند (خروجی‌اش دوباره همین‌جا اعتبارسنجی می‌شود).
"""

from __future__ import annotations

import copy
import decimal
import re
from dataclasses import dataclass, field
from typing import Protocol

from peecha import numerals
from peecha.services.workflow import builder, definitions, registry, simulate, tasks
from peecha.services.workflow.builder import ApprovalLevel, WizardSpec
from peecha.services.workflow.common import WorkflowError


@dataclass
class DraftSpec:
    """خروجی هر سرویس هوشمند: همان مشخصات ویزارد به‌صورت دادهٔ ساده (قابل بررسی و قابل ذخیره)."""
    entity_type: str | None
    name: str
    trigger: dict
    condition: dict | None = None
    levels: list[dict] = field(default_factory=list)  # {"label", "approvers", "mode"?}
    actions: list[str] = field(default_factory=list)
    reject_actions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)  # برداشت‌ها، به زبان ساده برای کاربر


class WorkflowAIProvider(Protocol):
    name: str

    def draft_from_text(self, company_id: int, text: str) -> DraftSpec | None: ...

    def summarize_task(self, company_id: int, task_id: int) -> str: ...


# --- سرویس پیش‌فرض: قاعده‌محور، بدون اینترنت ----------------------------------------------------------------
_UNITS = {"هزار": 1_000, "میلیون": 1_000_000, "میلیارد": 1_000_000_000}
_MORE = r"(?:بیشتر از|بیش از|بالای|بالاتر از|بزرگ‌تر از|بزرگتر از|حداقل)"
_LESS = r"(?:کمتر از|زیر|پایین‌تر از|کوچک‌تر از)"
# (کلیدواژه، برچسب مرحله، گیرندگان) -- طولانی‌ترها اول، تا «مدیر مستقیم» با «مدیر» اشتباه نشود
_APPROVER_WORDS = [
    ("مدیر مستقیم", "تایید مدیر مستقیم", [{"kind": "REPORTING_MANAGER"}]),
    ("مدیر فروش", "تایید مدیر فروش", [{"kind": "PERMISSION", "form_code": "commercial_document_sales_order", "action": "APPROVE"}]),
    ("مدیر تولید", "تایید مدیر تولید", [{"kind": "PERMISSION", "form_code": "prd_orders", "action": "APPROVE"}]),
    ("منابع انسانی", "تایید منابع انسانی", [{"kind": "PERMISSION", "form_code": "hr_leave_requests", "action": "APPROVE"}]),
    ("خزانه", "تایید خزانه‌داری", [{"kind": "PERMISSION", "form_code": "treasury_voucher_payment", "action": "APPROVE"}]),
    ("مالی", "تایید مالی", [{"kind": "PERMISSION", "form_code": "journal_entry", "action": "APPROVE"}]),
    ("انباردار", "تایید انبار", [{"kind": "WAREHOUSE"}]),
    ("مسئول انبار", "تایید انبار", [{"kind": "WAREHOUSE"}]),
    ("مدیرعامل", "تایید مدیرعامل", [{"kind": "MANAGERS"}]),
    ("مدیر", "تایید مدیر", [{"kind": "MANAGERS"}]),
]
_EVENT_PREFERENCE = ("CONFIRMED", "SUBMITTED", "PENDING_APPROVAL", "TEMPORARY", "PLANNED", "CREATED")
_ACTION_WORDS = {"تصویب": ("approve",), "ثبت نهایی": ("post", "finalize"), "دائم": ("approve",), "صدور": ("release",),
                 "فعال": ("approve",), "درخواست خرید": ("create_purchase_request",), "واگذار": ("assign",)}


def _number(text: str) -> decimal.Decimal | None:
    ascii_text = numerals.to_ascii_digits(text).replace(",", "").replace("٬", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(هزار|میلیون|میلیارد)?", ascii_text)
    if not m:
        return None
    value = decimal.Decimal(m.group(1)) * _UNITS.get(m.group(2) or "", 1)
    return value


def _entity(text: str) -> tuple[str | None, str]:
    best, label = None, ""
    for a in registry.adapters():
        if a.label in text and len(a.label) > len(label):
            best, label = a.entity_type, a.label
    return best, label


def _money_field(entity_type: str | None) -> str | None:
    adapter = registry.get_adapter(entity_type)
    if adapter is None:
        return None
    for f in adapter.fields:
        if f.kind == "money":
            return f.key
    return None


class NullProvider:
    """پیش‌فرض بدون اینترنت: جمله‌های رایج مثل «اگر سفارش خرید بیشتر از ۵۰۰ میلیون بود، اول مدیر بعد مالی تایید کند
    و بعد تصویب شود» را می‌فهمد؛ هرچه را نفهمد، صادقانه در برداشت‌ها می‌گوید."""

    name = "قاعده‌محور (بدون اینترنت)"

    def draft_from_text(self, company_id: int, text: str) -> DraftSpec | None:
        text = re.sub(r"\s+", " ", numerals.to_persian_digits(text or "").replace("ي", "ی").replace("ك", "ک")).strip()
        if not text:
            return None
        notes: list[str] = []
        entity_type, label = _entity(text)
        if entity_type is None:
            notes.append("نوع سند پیدا نشد؛ فرایند عمومی ساخته می‌شود و با دکمهٔ «ارسال برای تایید» شروع می‌شود.")
        else:
            notes.append(f"نوع سند: «{label}»")
        adapter = registry.get_adapter(entity_type)
        # شروع
        trigger: dict = {"type": "MANUAL"}
        if adapter is not None and "دستی" not in text:
            for kind in _EVENT_PREFERENCE:
                code = f"{entity_type}_{kind}"
                if code in adapter.events:
                    trigger = {"type": "EVENT", "events": [code]}
                    notes.append(f"شروع خودکار با «{adapter.events[code]}»")
                    break
        if trigger["type"] == "MANUAL":
            notes.append("شروع: دستی (دکمهٔ «ارسال برای تایید» در سند)")
        if adapter is not None and (adapter.gate_statuses or adapter.form_gate_statuses) and \
                any(w in text for w in ("تا تایید نشده", "قفل", "بدون تایید نشود", "نباید")):
            trigger["gate"] = True
            notes.append("قفل تایید روشن شد: تا تایید نشود، مرحلهٔ حساس سند انجام نمی‌شود.")
        # شرط مبلغ
        condition = None
        money = _money_field(entity_type)
        m = re.search(_MORE + r"\s*([\d۰-۹٬,\.]+\s*(?:هزار|میلیون|میلیارد)?)", text) or \
            re.search(_LESS + r"\s*([\d۰-۹٬,\.]+\s*(?:هزار|میلیون|میلیارد)?)", text)
        if m and money:
            value = _number(m.group(1))
            if value is not None:
                op = ">" if re.match(_MORE, m.group(0)) else "<"
                condition = {"field": money, "op": op, "value": int(value) if value == int(value) else str(value)}
                notes.append(f"شرط: {adapter.field_map()[money].label} {'بیشتر' if op == '>' else 'کمتر'} از "
                             f"{numerals.to_persian_digits(f'{int(value):,}')}")
        elif m and not money:
            notes.append("مبلغ گفته شد ولی این نوع سند فیلد مبلغ ندارد؛ شرط مبلغ اعمال نشد.")
        # مراحل تایید به ترتیب گفته‌شده
        found: list[tuple[int, str, list[dict]]] = []
        taken: list[tuple[int, int]] = []
        for word, step_label, approvers in _APPROVER_WORDS:
            for hit in re.finditer(re.escape(word) + r"(?![\u0621-\u064A\u06A9\u06AF\u06CC\u067E\u0686\u0698])", text):
                span = (hit.start(), hit.end())
                if any(s <= span[0] < e for s, e in taken):
                    continue
                taken.append(span)
                found.append((span[0], step_label, approvers))
        levels = []
        for _pos, step_label, approvers in sorted(found):
            if levels and levels[-1]["label"] == step_label:
                continue
            levels.append({"label": step_label, "approvers": copy.deepcopy(approvers)})
        if not levels and any(w in text for w in ("تایید", "تأیید")):
            levels.append({"label": "تایید مدیر", "approvers": [{"kind": "MANAGERS"}]})
            notes.append("تاییدکننده مشخص نشد؛ مدیران سیستم تایید می‌کنند.")
        for lv in levels:
            notes.append(f"مرحله: {lv['label']}")
        # اقدام‌ها پس از تایید (فقط اقدام‌های همین نوع سند)
        actions: list[str] = []
        if adapter is not None:
            for word, codes in _ACTION_WORDS.items():
                if word in text:
                    for code in codes:
                        if code in adapter.actions and f"entity.{code}" not in actions:
                            actions.append(f"entity.{code}")
                            notes.append(f"پس از تایید: {adapter.actions[code].label}")
                            break
        reject = ["entity.reject"] if adapter is not None and "reject" in adapter.actions and levels else []
        name = f"تایید {label}" if label else "فرایند تایید"
        return DraftSpec(entity_type, name, trigger, condition, levels, actions, reject, notes)

    def summarize_task(self, company_id: int, task_id: int) -> str:
        d = tasks.task_detail(company_id, task_id)
        parts = [f"{k}: {v}" for k, v in d.context[:4]]
        return f"{d.row.title} — " + "، ".join(parts) if parts else d.row.title


_PROVIDER: WorkflowAIProvider = NullProvider()


def set_provider(provider: WorkflowAIProvider) -> None:
    """جایگزینی سرویس هوشمند (مثلاً مدل زبانی سازمان)؛ خروجی آن هم همین مسیر اعتبارسنجی را طی می‌کند."""
    global _PROVIDER
    _PROVIDER = provider


def get_provider() -> WorkflowAIProvider:
    return _PROVIDER


# --- مسیر امن: پیش‌نویس ← اعتبارسنجی ← پیش‌نمایش ← ساخت پیش‌نویس ------------------------------------------------
@dataclass
class Draft:
    spec: DraftSpec
    graph: dict
    problems: list[str]
    summary: list[str]
    simulation: list[str]
    risky: list[str]

    @property
    def ok(self) -> bool:
        return not self.problems


def draft(company_id: int, text: str) -> Draft:
    registry.ensure_loaded()
    spec = get_provider().draft_from_text(company_id, text)
    if spec is None:
        raise WorkflowError("توصیف فرایند خالی است.")
    if spec.entity_type and registry.get_adapter(spec.entity_type) is None:
        raise WorkflowError("نوع سند پیشنهادی در برنامه وجود ندارد.")
    if not spec.levels and not spec.actions:
        raise WorkflowError("از این توصیف مرحلهٔ تایید یا اقدامی برداشت نشد؛ مثلاً بنویسید «اول مدیر بعد مالی تایید کند».")
    allowed = {code for code, _l, _r in registry.action_choices(spec.entity_type)}
    unknown = [a for a in spec.actions + spec.reject_actions if a not in allowed]
    if unknown:
        raise WorkflowError("اقدام ناشناخته در پیشنهاد: " + "، ".join(unknown))
    graph = builder.build_graph(WizardSpec(
        name=spec.name, code="AI", entity_type=spec.entity_type, trigger=copy.deepcopy(spec.trigger),
        start_condition=copy.deepcopy(spec.condition),
        levels=[ApprovalLevel(label=lv["label"], approvers=lv["approvers"], mode=lv.get("mode") or "ANY",
                              fallback=[{"kind": "MANAGERS"}]) for lv in spec.levels],
        actions=list(spec.actions), reject_actions=list(spec.reject_actions)))
    problems = [p.message for p in definitions.errors(definitions.validate_graph(company_id, graph, spec.entity_type))]
    summary = builder.describe_graph(graph, spec.entity_type, company_id)
    trace = simulate.simulate(company_id, graph, spec.entity_type, context=_sample_context(spec))
    risky = []
    for code in spec.actions:
        action = registry.find_action(spec.entity_type, code)
        if action is not None and action.risk == "HIGH":
            risky.append(f"«{action.label}» پس از تایید خودکار انجام می‌شود.")
    return Draft(spec, graph, problems, summary, [f"{'✔' if t.ok else '✖'} {t.title}: {t.result}" for t in trace], risky)


def _sample_context(spec: DraftSpec) -> dict:
    """نمونهٔ سند برای شبیه‌سازی: اگر شرط مبلغ هست، مقداری که شرط را برقرار کند."""
    cond = spec.condition or {}
    if cond.get("field") and cond.get("op") in (">", ">="):
        return {cond["field"]: decimal.Decimal(str(cond["value"])) + 1}
    if cond.get("field") and cond.get("op") in ("<", "<="):
        return {cond["field"]: decimal.Decimal(str(cond["value"])) - 1}
    return {}


def create_from_draft(company_id: int, user_id: int | None, d: Draft, *, name: str | None = None, code: str | None = None) -> int:
    """فقط پس از تایید کاربر: پیش‌نویس فرایند ساخته می‌شود (منتشر نمی‌شود)."""
    if not d.ok:
        raise WorkflowError("پیش از ساخت، این ایرادها را رفع کنید:\n" + "\n".join(f"• {p}" for p in d.problems))
    base = (code or "AI").strip().upper() or "AI"
    existing = {r.code for r in definitions.list_definitions(company_id)}
    final, n = base, 1
    while final in existing:
        n += 1
        final = f"{base}_{n}"
    return definitions.create_definition(company_id, user_id, code=final, name=(name or d.spec.name).strip() or d.spec.name,
                                         entity_type=d.spec.entity_type, description="ساخته‌شده از توصیف متنی",
                                         graph=d.graph, template_code="AI")
