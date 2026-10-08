"""قالب‌های آمادهٔ فرایند (R295): ۲۳ قالب استاندارد + پیگیری وصول، سفارش مجدد و درخواست عملیات دارایی.

هر قالب فقط یک «پیش‌نویس» می‌سازد؛ مدیر سیستم تاییدکننده‌ها و سقف‌ها را در طراح فرایند می‌بیند، در صورت نیاز عوض
می‌کند و بعد منتشر می‌کند. تاییدکننده‌ها از نقش‌ها و دسترسی‌های همین شرکت پیدا می‌شوند و اگر کسی پیدا نشد، کار به
مدیران سیستم می‌رسد (هیچ کاری بی‌صاحب نمی‌ماند).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.services.workflow import builder, definitions, registry
from peecha.services.workflow.builder import ApprovalLevel, WizardSpec
from peecha.services.workflow.common import WorkflowError

MANAGERS = [{"kind": "MANAGERS"}]


def perm(form_code: str, action: str = "APPROVE") -> list[dict]:
    return [{"kind": "PERMISSION", "form_code": form_code, "action": action}]


DIRECT_MANAGER = [{"kind": "REPORTING_MANAGER"}]
FINANCE = perm("journal_entry")
TREASURY = perm("treasury_voucher_payment")
HR = perm("hr_leave_requests")


def level(label: str, approvers: list[dict], **kw) -> ApprovalLevel:
    return ApprovalLevel(label=label, approvers=approvers, fallback=kw.pop("fallback", MANAGERS), **kw)


def gt(field_key: str, value) -> dict:
    return {"field": field_key, "op": ">", "value": value}


@dataclass(frozen=True)
class Template:
    code: str
    name: str
    group: str
    description: str
    entity_type: str | None
    make: Callable[[], dict]  # گراف
    tags: tuple[str, ...] = field(default_factory=tuple)


def _wizard(code: str, name: str, entity_type: str, *, trigger: dict, levels: list[ApprovalLevel], actions: list[str] = (),
            reject_actions: list[str] = (), condition: dict | None = None, notify_extra: list[dict] | None = None,
            action_params: dict[str, dict] | None = None, distinct: bool = False) -> Callable[[], dict]:
    def make() -> dict:
        graph = builder.build_graph(WizardSpec(name=name, code=code, entity_type=entity_type, trigger=copy.deepcopy(trigger),
                                               start_condition=copy.deepcopy(condition), levels=copy.deepcopy(levels),
                                               actions=list(actions), reject_actions=list(reject_actions),
                                               notify_extra=copy.deepcopy(notify_extra or [])))
        for node in graph["nodes"]:
            if node["type"] == "ACTION" and node["action"] in (action_params or {}):
                node["params"] = copy.deepcopy(action_params[node["action"]])
            if distinct and node["type"] == "APPROVAL":
                node["distinct_approvers"] = True  # تاییدکنندهٔ مرحلهٔ دوم کسی غیر از مرحلهٔ اول است
        return graph
    return make


def _event(*events: str, gate: bool = False) -> dict:
    return {"type": "EVENT", "events": list(events), **({"gate": True} if gate else {})}


def _graph(trigger: dict, nodes: list[dict], edges: list[dict]) -> Callable[[], dict]:
    def make() -> dict:
        return builder.auto_layout({"trigger": copy.deepcopy(trigger), "nodes": copy.deepcopy(nodes), "edges": copy.deepcopy(edges),
                                    "settings": {"allow_self_approval": False, "max_steps": 200}})
    return make


_MANUAL = {"type": "MANUAL", "gate": True}

TEMPLATES: list[Template] = [
    # --- فروش ---------------------------------------------------------------------------------------------------
    Template("SALES_ORDER_APPROVAL", "تایید سفارش فروش", "فروش",
             "سفارش‌های بزرگ پس از تایید کاربر به مدیر فروش می‌رود و پس از تایید خودکار تصویب می‌شود.",
             "SALES_ORDER", _wizard("SALES_ORDER_APPROVAL", "تایید سفارش فروش", "SALES_ORDER",
                                    trigger=_event("SALES_ORDER_CONFIRMED", gate=True), condition=gt("total_amount", 200_000_000),
                                    levels=[level("تایید مدیر فروش", perm("commercial_document_sales_order"))],
                                    actions=["entity.approve"])),
    Template("DISCOUNT_APPROVAL", "تایید تخفیف", "فروش",
             "سفارشی که تخفیفش از سقف مجاز بیشتر است، پیش از تصویب به تایید مدیر فروش می‌رسد.",
             "SALES_ORDER", _wizard("DISCOUNT_APPROVAL", "تایید تخفیف", "SALES_ORDER",
                                    trigger=_event("SALES_ORDER_CONFIRMED", gate=True), condition=gt("discount_percent", 10),
                                    levels=[level("تایید تخفیف توسط مدیر فروش", perm("commercial_document_sales_order"))],
                                    actions=["entity.approve"])),
    Template("CREDIT_APPROVAL", "تایید اعتبار مشتری", "فروش",
             "وقتی سفارش از سقف اعتبار مشتری عبور کند، مدیر مالی تصمیم می‌گیرد؛ با تایید، قفل آزاد و سفارش تصویب می‌شود.",
             "CREDIT_HOLD", _wizard("CREDIT_APPROVAL", "تایید اعتبار مشتری", "CREDIT_HOLD",
                                    trigger=_event("CREDIT_HOLD_CREATED"),
                                    levels=[level("تصمیم مدیر مالی دربارهٔ اعتبار", FINANCE)],
                                    actions=["entity.release", "entity.approve_document"])),
    Template("SALES_RETURN_APPROVAL", "تایید برگشت از فروش", "فروش",
             "برگشت از فروش پیش از تصویب و ثبت به تایید مدیر فروش می‌رسد.",
             "SALES_RETURN", _wizard("SALES_RETURN_APPROVAL", "تایید برگشت از فروش", "SALES_RETURN",
                                     trigger=_event("SALES_RETURN_CONFIRMED", gate=True),
                                     levels=[level("تایید مدیر فروش", perm("commercial_document_sales_return"))],
                                     actions=["entity.approve"])),
    # --- خرید ----------------------------------------------------------------------------------------------------
    Template("PURCHASE_REQUEST_APPROVAL", "تایید درخواست خرید", "خرید",
             "درخواست خرید ارسال‌شده به مدیر مستقیم درخواست‌کننده می‌رسد؛ تایید یا رد در خود درخواست ثبت می‌شود.",
             "PURCHASE_REQUEST", _wizard("PURCHASE_REQUEST_APPROVAL", "تایید درخواست خرید", "PURCHASE_REQUEST",
                                         trigger=_event("PURCHASE_REQUEST_SUBMITTED", gate=True),
                                         levels=[level("تایید مدیر مستقیم", DIRECT_MANAGER)],
                                         actions=["entity.approve"], reject_actions=["entity.reject"])),
    Template("PURCHASE_ORDER_APPROVAL", "تایید سفارش خرید", "خرید",
             "سفارش خرید بیش از ۵۰۰ میلیون ریال: ابتدا مدیر، سپس مالی؛ پس از تایید هر دو، سفارش خودکار تصویب می‌شود.",
             "PURCHASE_ORDER", _wizard("PURCHASE_ORDER_APPROVAL", "تایید سفارش خرید", "PURCHASE_ORDER",
                                       trigger=_event("PURCHASE_ORDER_CONFIRMED", gate=True), condition=gt("total_amount", 500_000_000),
                                       levels=[level("تایید مدیر", MANAGERS), level("تایید مالی", FINANCE)],
                                       actions=["entity.approve"], distinct=True)),
    Template("SUPPLIER_INVOICE_APPROVAL", "تایید فاکتور خرید", "خرید",
             "فاکتور تامین‌کننده پیش از تصویب و ثبت به تایید واحد مالی می‌رسد.",
             "PURCHASE_INVOICE", _wizard("SUPPLIER_INVOICE_APPROVAL", "تایید فاکتور خرید", "PURCHASE_INVOICE",
                                         trigger=_event("PURCHASE_INVOICE_CONFIRMED", gate=True),
                                         levels=[level("تایید مالی", FINANCE)], actions=["entity.approve"])),
    # --- مالی ----------------------------------------------------------------------------------------------------
    Template("PAYMENT_APPROVAL", "تایید پرداخت", "مالی",
             "سند پرداخت: تایید مالی، سپس تایید خزانه‌داری؛ بعد سند خودکار دائم می‌شود.",
             "PAYMENT_VOUCHER", _wizard("PAYMENT_APPROVAL", "تایید پرداخت", "PAYMENT_VOUCHER",
                                        trigger=_event("PAYMENT_VOUCHER_TEMPORARY", gate=True),
                                        levels=[level("تایید مالی", FINANCE), level("تایید خزانه‌داری", TREASURY)],
                                        actions=["entity.approve"], distinct=True)),
    Template("EXPENSE_APPROVAL", "تایید هزینه", "مالی",
             "هزینهٔ تنخواه به تایید مدیر مستقیم و سپس مالی می‌رسد و بعد سندش دائم می‌شود.",
             "PETTY_CASH_EXPENSE", _wizard("EXPENSE_APPROVAL", "تایید هزینه", "PETTY_CASH_EXPENSE",
                                           trigger=_event("PETTY_CASH_EXPENSE_TEMPORARY", gate=True),
                                           levels=[level("تایید مدیر مستقیم", DIRECT_MANAGER), level("تایید مالی", FINANCE)],
                                           actions=["entity.approve"])),
    Template("JOURNAL_APPROVAL", "تایید سند حسابداری", "مالی",
             "سند حسابداری دستی پیش از دائم‌شدن به تایید مسئول مالی می‌رسد.",
             "JOURNAL_ENTRY", _wizard("JOURNAL_APPROVAL", "تایید سند حسابداری", "JOURNAL_ENTRY",
                                      trigger=_event("JOURNAL_ENTRY_TEMPORARY", gate=True),
                                      levels=[level("تایید مسئول مالی", FINANCE)], actions=["entity.approve"])),
    # --- انبار ----------------------------------------------------------------------------------------------------
    Template("STOCK_ADJUSTMENT_APPROVAL", "تایید اصلاح موجودی", "انبار",
             "اصلاح موجودی پس از تایید کاربر به تایید مسئول انبار می‌رسد و بعد خودکار ثبت نهایی می‌شود.",
             "STOCK_ADJUSTMENT", _wizard("STOCK_ADJUSTMENT_APPROVAL", "تایید اصلاح موجودی", "STOCK_ADJUSTMENT",
                                         trigger=_event("STOCK_ADJUSTMENT_CONFIRMED", gate=True),
                                         levels=[level("تایید مسئول انبار", [{"kind": "WAREHOUSE", "field": "source_warehouse_id",
                                                                              "can": "can_adjust"}])],
                                         actions=["entity.post"])),
    Template("TRANSFER_APPROVAL", "تایید انتقال بین انبارها", "انبار",
             "با دکمهٔ «ارسال برای تایید» در سند انتقال، مسئول انبار مقصد تایید می‌کند و سند ثبت نهایی می‌شود.",
             "STOCK_TRANSFER", _wizard("TRANSFER_APPROVAL", "تایید انتقال بین انبارها", "STOCK_TRANSFER", trigger=_MANUAL,
                                       levels=[level("تایید انبار مقصد", [{"kind": "WAREHOUSE", "field": "destination_warehouse_id"}])],
                                       actions=["entity.post"])),
    Template("INVENTORY_COUNT_APPROVAL", "تایید انبارگردانی", "انبار",
             "نتیجهٔ انبارگردانی پیش از ثبت اختلاف‌ها به تایید مدیر می‌رسد.",
             "INVENTORY_COUNT", _wizard("INVENTORY_COUNT_APPROVAL", "تایید انبارگردانی", "INVENTORY_COUNT", trigger=_MANUAL,
                                        levels=[level("تایید مدیر", MANAGERS)], actions=["entity.finalize"])),
    # --- منابع انسانی ---------------------------------------------------------------------------------------------
    Template("LEAVE_APPROVAL", "تایید مرخصی", "منابع انسانی",
             "درخواست مرخصی: تایید مدیر مستقیم، سپس منابع انسانی.",
             "LEAVE_REQUEST", _wizard("LEAVE_APPROVAL", "تایید مرخصی", "LEAVE_REQUEST",
                                      trigger=_event("LEAVE_REQUEST_SUBMITTED", gate=True),
                                      levels=[level("تایید مدیر مستقیم", [{"kind": "REPORTING_MANAGER", "field": "employee_user_id"}]),
                                              level("تایید منابع انسانی", HR)],
                                      actions=["entity.approve"], reject_actions=["entity.reject"])),
    Template("OVERTIME_APPROVAL", "تایید اضافه‌کاری", "منابع انسانی",
             "اضافه‌کاری ثبت‌شده به تایید مدیر مستقیم کارمند می‌رسد.",
             "OVERTIME", _wizard("OVERTIME_APPROVAL", "تایید اضافه‌کاری", "OVERTIME",
                                 trigger=_event("OVERTIME_PENDING_APPROVAL", gate=True),
                                 levels=[level("تایید مدیر مستقیم", [{"kind": "REPORTING_MANAGER", "field": "employee_user_id"}])],
                                 actions=["entity.approve"], reject_actions=["entity.reject"])),
    Template("EMPLOYEE_REQUEST", "درخواست کارکنان", "منابع انسانی",
             "درخواست‌های عمومی کارکنان (گواهی اشتغال، تجهیزات، ...): مدیر مستقیم، سپس منابع انسانی.",
             "EMPLOYEE", _wizard("EMPLOYEE_REQUEST", "درخواست کارکنان", "EMPLOYEE", trigger={"type": "MANUAL"},
                                 levels=[level("تایید مدیر مستقیم", [{"kind": "REPORTING_MANAGER", "field": "employee_user_id"}]),
                                         level("بررسی منابع انسانی", HR)])),
    # --- تولید ---------------------------------------------------------------------------------------------------
    Template("PRODUCTION_RELEASE", "تایید صدور دستور تولید", "تولید",
             "دستور تولید برنامه‌ریزی‌شده پس از تایید مدیر تولید خودکار صادر می‌شود.",
             "PRODUCTION_ORDER", _wizard("PRODUCTION_RELEASE", "تایید صدور دستور تولید", "PRODUCTION_ORDER",
                                         trigger=_event("PRODUCTION_ORDER_PLANNED", gate=True),
                                         levels=[level("تایید مدیر تولید", perm("prd_orders"))], actions=["entity.release"])),
    Template("MATERIAL_SHORTAGE", "هشدار کمبود مواد", "تولید",
             "هر روز دستورهای تولیدی که مواد کافی ندارند پیدا می‌شوند و به مسئول تولید و خرید خبر داده می‌شود.",
             "PRODUCTION_ORDER", _graph(
                 {"type": "SCAN", "scan": "MATERIAL_SHORTAGE", "every_minutes": 1440},
                 [{"id": "n1", "type": "NOTIFY", "label": "خبر کمبود مواد", "to": [{"kind": "OWNER"}] + perm("purchase_requests", "CREATE"),
                   "title": "کمبود مواد: {عنوان}", "body": "اقلام: {shortage_text}"},
                  {"id": "t1", "type": "TASK", "label": "تامین مواد", "assignees": perm("purchase_requests", "CREATE"),
                   "fallback": MANAGERS, "instructions": "برای اقلام کمبود درخواست خرید یا انتقال ثبت کنید: {shortage_text}"},
                  {"id": "end", "type": "END", "label": "پایان", "outcome": "DONE"}],
                 [{"from": "start", "to": "n1"}, {"from": "n1", "to": "t1"}, {"from": "t1", "to": "end", "when": "done"}])),
    Template("PRODUCTION_COMPLETION", "پس از تکمیل تولید", "تولید",
             "با تکمیل دستور تولید، به ثبت‌کننده خبر داده و کار «کنترل کیفیت» برای مسئول تولید ساخته می‌شود.",
             "PRODUCTION_ORDER", _graph(
                 _event("PRODUCTION_ORDER_COMPLETED"),
                 [{"id": "n1", "type": "NOTIFY", "label": "خبر تکمیل", "to": [{"kind": "STARTER"}, {"kind": "OWNER"}],
                   "title": "تولید تکمیل شد: {عنوان}"},
                  {"id": "t1", "type": "TASK", "label": "کنترل کیفیت محصول", "assignees": perm("prd_orders", "EDIT"),
                   "fallback": MANAGERS, "fields": [{"key": "result", "label": "نتیجهٔ کنترل", "kind": "text", "required": True}]},
                  {"id": "end", "type": "END", "label": "پایان", "outcome": "DONE"}],
                 [{"from": "start", "to": "n1"}, {"from": "n1", "to": "t1"}, {"from": "t1", "to": "end", "when": "done"}])),
    # --- ارتباط با مشتری ------------------------------------------------------------------------------------------
    Template("LEAD_ASSIGNMENT", "واگذاری خودکار سرنخ", "ارتباط با مشتری",
             "سرنخ تازه‌ای که مسئول مشخصی ندارد به نوبت به کم‌کارترین کارشناس فروش واگذار و به او خبر داده می‌شود.",
             "LEAD", _graph(
                 {**_event("LEAD_CREATED"), "condition": {"any": [
                     {"field": "owner_user_id", "op": "is_empty"},
                     {"field": "owner_user_id", "op": "=", "value_field": "created_by"}]}},
                 [{"id": "a1", "type": "ACTION", "label": "واگذاری سرنخ", "action": "entity.assign",
                   "retry": {"max": 3, "backoff_minutes": 5}},
                  {"id": "n1", "type": "NOTIFY", "label": "خبر به مسئول", "to": [{"kind": "FIELD", "field": "owner_user_id"}],
                   "title": "سرنخ تازه به شما واگذار شد: {عنوان}"},
                  {"id": "end", "type": "END", "label": "پایان", "outcome": "DONE"}],
                 [{"from": "start", "to": "a1"}, {"from": "a1", "to": "n1"}, {"from": "n1", "to": "end"}])),
    Template("OPPORTUNITY_APPROVAL", "تایید فرصت فروش بزرگ", "ارتباط با مشتری",
             "فرصت فروش بالای یک میلیارد ریال به تایید مدیر فروش می‌رسد تا منابع لازم برایش گذاشته شود.",
             "OPPORTUNITY", _wizard("OPPORTUNITY_APPROVAL", "تایید فرصت فروش بزرگ", "OPPORTUNITY",
                                    trigger=_event("OPPORTUNITY_CREATED"), condition=gt("amount", 1_000_000_000),
                                    levels=[level("تایید مدیر فروش", perm("crm_pipeline"))])),
    Template("CUSTOMER_ONBOARDING", "تایید مشتری تازه", "ارتباط با مشتری",
             "مشتری تازه‌ای که منتظر تایید است به مدیر فروش می‌رسد؛ با تایید فعال و با رد غیرفعال می‌شود.",
             "CUSTOMER", _wizard("CUSTOMER_ONBOARDING", "تایید مشتری تازه", "CUSTOMER",
                                 trigger=_event("CUSTOMER_PENDING_APPROVAL", gate=True),
                                 levels=[level("تایید مدیر فروش", perm("detail_dimensions"))],
                                 actions=["entity.approve"], reject_actions=["entity.reject"])),
    Template("FOLLOWUP_AUTOMATION", "پیگیری مشتریان غیرفعال", "ارتباط با مشتری",
             "هر هفته برای مشتریانی که مدتی خرید نکرده‌اند، کار «تماس پیگیری» ساخته می‌شود.",
             "CUSTOMER", _graph(
                 {"type": "SCAN", "scan": "CUSTOMER_INACTIVE", "params": {"days": 60}, "every_minutes": 1440},
                 [{"id": "a1", "type": "ACTION", "label": "ثبت تماس پیگیری", "action": "create_followup",
                   "params": {"subject": "تماس با مشتری غیرفعال: {customer_name}", "activity_type": "CALL", "due_in_days": 2,
                              "customer_field": "customer_id", "priority": "NORMAL"}},
                  {"id": "end", "type": "END", "label": "پایان", "outcome": "DONE"}],
                 [{"from": "start", "to": "a1"}, {"from": "a1", "to": "end"}])),
    # --- قالب‌های تکمیلی -------------------------------------------------------------------------------------------
    Template("OVERDUE_COLLECTION", "پیگیری وصول فاکتور معوق", "مالی",
             "هر روز فاکتورهای فروش سررسیدگذشته پیدا می‌شوند؛ برای هر کدام کار پیگیری وصول ساخته و به صادرکننده خبر داده می‌شود.",
             "SALES_INVOICE", _graph(
                 {"type": "SCAN", "scan": "OVERDUE_INVOICES", "params": {"min_days": 1}, "every_minutes": 1440},
                 [{"id": "a1", "type": "ACTION", "label": "ثبت کار پیگیری وصول", "action": "create_followup",
                   "params": {"subject": "پیگیری وصول فاکتور {document_no} — {counterparty_name}", "activity_type": "FOLLOW_UP",
                              "due_in_days": 1, "customer_field": "counterparty_id", "priority": "HIGH"}},
                  {"id": "n1", "type": "NOTIFY", "label": "خبر سررسید", "to": [{"kind": "OWNER"}],
                   "title": "فاکتور {document_no} سررسید گذشته است",
                   "body": "مشتری: {counterparty_name} — {overdue_days} روز از سررسید گذشته است."},
                  {"id": "end", "type": "END", "label": "پایان", "outcome": "DONE"}],
                 [{"from": "start", "to": "a1"}, {"from": "a1", "to": "n1"}, {"from": "n1", "to": "end"}])),
    Template("STOCK_REORDER", "سفارش مجدد خودکار", "انبار",
             "کالایی که موجودی آزادش به نقطهٔ سفارش برسد، خودکار درخواست خرید می‌گیرد (درخواست تکراری ساخته نمی‌شود).",
             "REORDER_POLICY", _graph(
                 {"type": "SCAN", "scan": "STOCK_BELOW_MIN", "every_minutes": 360},
                 [{"id": "a1", "type": "ACTION", "label": "ساخت درخواست خرید", "action": "entity.create_purchase_request",
                   "params": {"submit": "true", "priority": "NORMAL"}, "retry": {"max": 3, "backoff_minutes": 10}},
                  {"id": "end", "type": "END", "label": "پایان", "outcome": "DONE"}],
                 [{"from": "start", "to": "a1"}, {"from": "a1", "to": "end"}])),
    Template("FA_REQUEST_APPROVAL", "تایید عملیات دارایی ثابت", "دارایی ثابت",
             "فروش، اسقاط، تجدید ارزیابی و دیگر عملیات حساس دارایی: تایید مدیر و مالی، سپس اجرای خودکار عملیات.",
             "FA_REQUEST", _wizard("FA_REQUEST_APPROVAL", "تایید عملیات دارایی ثابت", "FA_REQUEST",
                                   trigger=_event("FA_REQUEST_CREATED"),
                                   levels=[level("تایید مدیر", MANAGERS), level("تایید مالی", FINANCE)],
                                   actions=["entity.approve"], reject_actions=["entity.reject"], distinct=True)),
]

_BY_CODE = {t.code: t for t in TEMPLATES}
GROUPS = tuple(dict.fromkeys(t.group for t in TEMPLATES))


def get(code: str) -> Template:
    t = _BY_CODE.get(code)
    if t is None:
        raise WorkflowError("قالب پیدا نشد.")
    return t


def preview(code: str) -> dict:
    return get(code).make()


def installed_codes(company_id: int) -> set[str]:
    from peecha.db.models.workflow import WfDefinition

    with new_session() as session:
        return {c for c in session.scalars(select(WfDefinition.template_code).where(
            WfDefinition.company_id == company_id, WfDefinition.template_code.isnot(None),
            WfDefinition.status_code != "ARCHIVED"))}


def install(company_id: int, user_id: int | None, code: str, *, new_code: str | None = None, name: str | None = None) -> int:
    """پیش‌نویس تازه از قالب (پس از بازبینی در طراح منتشر می‌شود)."""
    t = get(code)
    registry.ensure_loaded()
    graph = t.make()
    problems = definitions.errors(definitions.validate_graph(company_id, graph, t.entity_type))
    if problems:
        raise WorkflowError("قالب با تنظیمات این شرکت سازگار نیست:\n" + "\n".join(f"• {p.message}" for p in problems))
    return definitions.create_definition(company_id, user_id, code=new_code or t.code, name=name or t.name,
                                         entity_type=t.entity_type, description=t.description, category=t.group,
                                         graph=graph, template_code=t.code)


# --- انتقال گردش کار کارتابل قدیمی ------------------------------------------------------------------------------
def legacy_workflows(company_id: int) -> list[tuple[str, str, int, bool]]:
    """(کد فرم، نام نوع سند، تعداد مرحله، فعال؟) برای گردش‌کارهای کارتابل قدیمی که نوع سند متناظر دارند."""
    from peecha.services import cartable
    from peecha.db.models.security import Form

    with new_session() as session:
        forms = [f.code for f in session.scalars(select(Form))]
    by_form = {a.form_code: a for a in registry.adapters() if a.form_code}
    out = []
    for form in forms:
        adapter = by_form.get(form)
        if adapter is None:
            continue
        active, steps = cartable.get_workflow_steps(company_id, form)
        if steps:
            out.append((form, adapter.label, len(steps), active))
    return out


def import_legacy(company_id: int, user_id: int | None, form_code: str) -> int:
    """مراحل کارتابل قدیمی (نقش هر مرحله، به ترتیب) ← پیش‌نویس فرایند تازه با دکمهٔ «ارسال برای تایید»."""
    from peecha.services import cartable

    adapter = next((a for a in registry.adapters() if a.form_code == form_code), None)
    if adapter is None:
        raise WorkflowError("برای این فرم نوع سند گردش کار تعریف نشده است.")
    _active, steps = cartable.get_workflow_steps(company_id, form_code)
    if not steps:
        raise WorkflowError("گردش کار کارتابل قدیمی برای این فرم مرحله‌ای ندارد.")
    levels = [level(f"مرحلهٔ {i}", [{"kind": "ROLE", "role_id": s.approver_role_id}]) for i, s in enumerate(steps, start=1)]
    approve = ["entity.approve"] if "approve" in adapter.actions else []
    graph = builder.build_graph(WizardSpec(name=f"تایید {adapter.label}", code=f"LEGACY_{form_code}", entity_type=adapter.entity_type,
                                           trigger={"type": "MANUAL", "gate": True}, levels=levels, actions=approve))
    return definitions.create_definition(company_id, user_id, code=f"LEGACY_{form_code}"[:40], name=f"تایید {adapter.label} (از کارتابل قبلی)",
                                         entity_type=adapter.entity_type, description="منتقل‌شده از کارتابل قدیمی",
                                         graph=graph, template_code=f"LEGACY:{form_code}")


# --- یک مسیر تایید برای هر سند (R300) ---------------------------------------------------------------------------
def legacy_forms(entity_type: str | None) -> list[str]:
    """فرم‌های کارتابل قبلی که همین نوع سند را تایید می‌کنند."""
    if entity_type == "FA_REQUEST":
        from peecha.services.fixed_assets.approval import OPERATIONS

        return [form for form, _event, _label in OPERATIONS.values()]
    adapter = registry.get_adapter(entity_type)
    return [adapter.form_code] if adapter and adapter.form_code else []


def governs_approvals(graph: dict) -> bool:
    """فرایندی که روی خود سند مرحلهٔ تایید دارد (نه فقط بررسی دوره‌ای یا اعلان)."""
    trigger = graph.get("trigger") or {}
    return trigger.get("type") in ("EVENT", "MANUAL") and any(n.get("type") == "APPROVAL" for n in graph.get("nodes") or [])


def _active_graph(company_id: int, definition_id: int) -> dict:
    d = definitions.get_definition(company_id, definition_id)
    return definitions.get_graph(company_id, definition_id, d.active_version_id) if d.active_version_id else {}


def active_legacy_for(company_id: int, entity_type: str | None) -> list[str]:
    """نام فرم‌هایی که کارتابل قبلی‌شان برای این نوع سند هنوز روشن است."""
    from peecha.services import cartable
    from peecha.services.roles import FORM_LABELS

    out = []
    for form in legacy_forms(entity_type):
        active, steps = cartable.get_workflow_steps(company_id, form)
        if active and steps:
            out.append(FORM_LABELS.get(form, form))
    return out


def retire_legacy(company_id: int, user_id: int | None, definition_id: int) -> list[str]:
    """با اجرایی شدن فرایند تایید یک سند، کارتابل قبلی همان سند خاموش می‌شود (مراحلش برای برگرداندن می‌ماند).

    موارد در جریان کارتابل قبلی تا پایان همان‌جا تایید می‌شوند؛ فقط درخواست تازه به آن نمی‌رود."""
    from peecha.services import cartable
    from peecha.services.roles import FORM_LABELS

    d = definitions.get_definition(company_id, definition_id)
    if not d.entity_type or not governs_approvals(_active_graph(company_id, definition_id)):
        return []
    retired = []
    for form in legacy_forms(d.entity_type):
        active, steps = cartable.get_workflow_steps(company_id, form)
        if active and steps:
            cartable.save_workflow_steps(company_id, form, False, [s.approver_role_id for s in steps])
            retired.append(FORM_LABELS.get(form, form))
    return retired


definitions.RUNNABLE_HOOKS.append(retire_legacy)


def governing_process(company_id: int, form_code: str) -> str | None:
    """نام فرایند اجرایی‌ای که تایید سندهای این فرم را در دست دارد (برای جلوگیری از روشن کردن دوبارهٔ کارتابل قبلی)."""
    from peecha.services.workflow.common import RUNNABLE_STATUSES

    entity_types = [a.entity_type for a in registry.adapters() if form_code in legacy_forms(a.entity_type)]
    for entity_type in entity_types:
        for d in definitions.list_definitions(company_id, include_archived=False, entity_type=entity_type):
            if d.status_code in RUNNABLE_STATUSES and governs_approvals(_active_graph(company_id, d.definition_id)):
                return d.name
    return None
