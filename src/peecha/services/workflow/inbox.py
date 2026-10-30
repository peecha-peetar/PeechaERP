"""کارتابل یکپارچه: همهٔ کارهای منتظر یک کاربر و درخواست‌های در جریان خودش در یک جا (R293، یکپارچه در R300).

منابع: کارها و تاییدهای موتور گردش کار، کارتابل اسناد (تایید چندمرحله‌ای قبلی)، مراحل منتظر اسناد خرید/فروش/انبار،
پیگیری‌های باز ارتباط با مشتری، تیکت‌های ارجاع‌شده (R356) و مشتریان جدید منتظر تایید. هر منبع منطق خودش را نگه می‌دارد؛ این‌جا فقط کنار هم
دیده و از یک‌جا انجام می‌شوند. هر مورد یک «جملهٔ کار» (action) و رنگ (tone) دارد تا کاربر با یک نگاه بداند چه کند.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from peecha.services.workflow import registry, tasks
from peecha.services.workflow.common import PRIORITIES, WorkflowError, now

SOURCES = {"WF": "گردش کار", "CARTABLE": "کارتابل اسناد", "DOC": "اسناد خرید، فروش و انبار", "CRM": "پیگیری مشتری",
           "CUSTOMER": "مشتری جدید", "TICKET": "تیکت مشتری", "MINE": "درخواست‌های من", "STUCK": "مرحلهٔ بی‌گیرنده",
           "FAILED": "اقدام خودکار ناموفق"}
KINDS = {"APPROVAL": "تایید", "TASK": "کار", "STEP": "مرحلهٔ سند", "FOLLOWUP": "پیگیری", "REQUEST": "درخواست من"}
_REQUEST_TYPES = {"CREATE": "ثبت و تایید", "EDIT": "ویرایش", "DELETE": "حذف"}
# مرحلهٔ منتظر اسناد ← جملهٔ کاری که کاربر باید انجام دهد
DOC_ACTIONS = {
    "MANAGER_APPROVAL": "سند را تصویب کنید", "PR_APPROVAL": "درخواست خرید را باز کنید و تصویب یا رد کنید", "GOODS_RECEIPT": "رسید یا حوالهٔ انبار را تایید کنید",
    "PRE_SALES_WAREHOUSE": "تایید انبار سفارش را بزنید", "SETTLEMENT_APPROVAL": "نحوهٔ تسویه را تایید کنید",
    "CONVERT_TO_INVOICE": "سند را به فاکتور تبدیل کنید", "POST_ORDER": "سفارش را ثبت نهایی کنید",
    "INVENTORY_RESIDUAL": "سند اصلاح ماندهٔ ریالی را ثبت کنید",
    "PUTAWAY_PENDING": "کالای رسیده را در قفسه بچینید (کار چیدن در قفسه بسازید)",
    "QC_PENDING": "نتیجهٔ کنترل کیفیت رسیدها را ثبت کنید",
    "EXPIRY_NEAR": "کالای نزدیک به انقضا را زودتر بفروشید یا جابه‌جا کنید",
    "EXPIRED_STOCK": "سند انتقال کالای منقضی به ضایعات را بسازید و ثبت کنید",
    "TRANSIT_ARRIVING": "پس از رسیدن کالا، دریافت ارسال را ثبت کنید",
    "CROSS_DOCK": "کالای رسیده را بدون چیدن در قفسه، مستقیم برای سفارش‌های منتظر آماده کنید",
    "MNT_MY_WORK": "دستور کار نگهداری را انجام دهید", "MNT_TO_VERIFY": "تعمیر انجام‌شده را آزمون و تأیید کنید",
    "MNT_NEW_REQUEST": "درخواست تعمیر را بررسی و اولویت‌بندی کنید",
    "MNT_APPROVAL": "توقف برنامه‌ریزی‌شده یا تعویق نگهداری را تأیید یا رد کنید",
    "BUD_REVIEW": "نسخهٔ بودجه را بررسی کنید و تأیید یا رد کنید", "BUD_APPROVE": "نسخهٔ بررسی‌شدهٔ بودجه را تأیید یا رد کنید",
    "BUD_PUBLISH": "نسخهٔ تأییدشدهٔ بودجه را منتشر کنید", "BUD_REVISE": "نسخهٔ ردشدهٔ بودجه را اصلاح و دوباره ارسال کنید",
    "BUD_EXCEPTION": "درخواست مجوز تجاوز از بودجه را تأیید یا رد کنید",
    "OPN_ENTER": "اطلاعات افتتاحیهٔ این ماژول را وارد یا اصلاح کنید و برای بررسی بفرستید",
    "OPN_APPROVE": "اطلاعات افتتاحیهٔ این ماژول را بررسی و تأیید یا رد کنید",
    "OPN_POST": "ماژول تأییدشدهٔ افتتاحیه را ثبت قطعی کنید", "OPN_LOCK": "تطبیق را ببینید و افتتاحیه را قفل نهایی کنید",
    "HR_LEAVE": "درخواست مرخصی را تایید یا رد کنید", "HR_ATTENDANCE": "ورود و خروج‌های ثبت‌شده را بررسی و تایید کنید",
    "HR_OVERTIME": "اضافه‌کاری‌های ثبت‌شده را بررسی و تایید کنید",
    "VAN_SETTLE_WAREHOUSE": "کالای برگشتی خودرو را بشمارید و تسویه را از نظر انبار تایید کنید",
    "VAN_SETTLE_ACCOUNTING": "وجه نقد و فاکتورهای خودرو را بررسی و تسویه را از نظر حسابداری تایید کنید",
    "PRJ_TIMESHEET": "کارکردهای ارسال‌شدهٔ پروژه را بررسی و تایید یا رد کنید",  # R364
    "PRJ_CHANGE": "درخواست تغییر پروژه را بررسی و تایید یا رد کنید",  # R366
    "HR_INTERVIEW": "مصاحبه را انجام دهید و امتیاز و پیشنهادتان را ثبت کنید",  # R367
    "HR_APPLICATIONS": "درخواست‌های استخدام جدید را بررسی کنید و به مرحلهٔ بعد ببرید یا رد کنید",  # R367
    "HR_APPRAISAL_SELF": "به معیارهای ارزیابی خودتان امتیاز بدهید و خودارزیابی را ثبت کنید",  # R368
    "HR_APPRAISAL_REVIEW": "ارزیابی کارکنانتان را با امتیاز هر معیار ثبت کنید",  # R368
    "HR_TRAINING_GAPS": "ماتریس آموزش را ببینید و برای دوره‌های الزامی کلاس بگذارید",  # R369
    "PRD_ECO_APPROVE": "اثر تغییر مهندسی را ببینید و آن را تایید یا رد کنید",  # R372
    "PRD_ECO_IMPLEMENT": "تغییر تاییدشده را اجرا کنید تا نسخهٔ جدید فهرست مواد ساخته شود",  # R372
    "PUR_THREE_WAY": "مغایرت فاکتورهای خرید را بررسی کنید و پس از رفع یا با ذکر دلیل پرداخت را آزاد کنید",  # R379
}
_CUSTOMER_FORM = "detail_dimensions"  # همان دسترسی ویرایش مشتریان که صندوق تایید قبلی موبایل می‌خواست


@dataclass
class WorkItem:
    key: str
    source: str
    source_label: str
    kind: str
    kind_label: str
    ref_id: int
    title: str
    subtitle: str
    due_at: datetime.datetime | None
    is_overdue: bool
    priority_code: str
    priority_label: str
    created_at: datetime.datetime | None
    can_quick_decide: bool
    status_note: str = ""
    extra: dict = field(default_factory=dict)
    action: str = ""  # جملهٔ کار، مثل «تایید یا رد کنید»
    tone: str = ""  # approve | task | doc | followup | customer | mine
    step_no: int | None = None
    step_total: int | None = None
    path: list = field(default_factory=list)  # [(برچسب مرحله، done|current|pending|failed)]


def _end_of(day: datetime.date) -> datetime.datetime:
    return datetime.datetime.combine(day, datetime.time(23, 59)).astimezone()


def _progress(path: list[tuple[str, str]]) -> tuple[int | None, int | None]:
    if not path:
        return None, None
    current = next((i for i, (_l, s) in enumerate(path, start=1) if s in ("current", "failed")), None)
    return current, len(path)


def _wf_path(company_id: int, instance_id: int | None) -> list[tuple[str, str]]:
    if not instance_id:
        return []
    from peecha.services.workflow import runtime

    try:
        return runtime.status_path(company_id, instance_id)
    except Exception:  # noqa: BLE001 -- نبود مسیر نباید کارتابل را خالی کند
        return []


def _wf_items(company_id: int, user_id: int) -> list[WorkItem]:
    out = []
    for t in tasks.list_my_tasks(company_id, user_id):
        note = t.sla_label if t.sla_status not in ("NONE", "ON_TRACK") else ""
        if t.on_behalf_of:
            note = (note + "، " if note else "") + f"به جای {t.on_behalf_of}"
        path = _wf_path(company_id, t.instance_id)
        step_no, step_total = _progress(path)
        out.append(WorkItem(f"WF:{t.task_id}", "WF", SOURCES["WF"], t.kind, KINDS[t.kind], t.task_id, t.title,
                            t.requested_by, t.due_at, t.is_overdue, t.priority_code, t.priority_label, t.created_at,
                            t.kind == "APPROVAL", note,
                            {"row_version": t.row_version, "instance_id": t.instance_id, "entity_type": t.entity_type,
                             "entity_id": t.entity_id, "open_nav": t.open_nav, "definition": t.definition_name,
                             "entity_label": t.entity_label},
                            "تایید یا رد کنید" if t.kind == "APPROVAL" else "انجام دهید",
                            "approve" if t.kind == "APPROVAL" else "task", step_no, step_total, path))
    return out


def _legacy_steps(current: int, total: int) -> list[tuple[str, str]]:
    from peecha import numerals

    return [(f"مرحلهٔ {numerals.to_persian_digits(str(i))}", "done" if i < current else "current" if i == current else "pending")
            for i in range(1, total + 1)]


def _cartable_items(company_id: int, user_id: int) -> list[WorkItem]:
    from peecha.services import cartable

    out = []
    for c in cartable.list_my_tasks(user_id, company_id):
        request_type = _REQUEST_TYPES.get(c.request_type_code, "")
        path = _legacy_steps(c.current_step_no, c.total_steps)
        out.append(WorkItem(f"CARTABLE:{c.cartable_item_id}", "CARTABLE", SOURCES["CARTABLE"], "APPROVAL", KINDS["APPROVAL"],
                            c.cartable_item_id, f"{c.form_label}: {c.description}", c.submitted_by_name, None, False, "NORMAL",
                            PRIORITIES["NORMAL"], c.submitted_at, True,
                            f"مرحلهٔ {c.current_step_no} از {c.total_steps} — {request_type}",
                            {"form_code": c.form_code, "source_record_id": c.source_record_id, "form_label": c.form_label,
                             "description": c.description, "request_type": request_type},
                            "تایید یا رد کنید", "approve", c.current_step_no, c.total_steps, path))
    return out


def _doc_items(company_id: int, user_id: int) -> list[WorkItem]:
    from peecha.services import operational_tasks

    out = []
    for i, d in enumerate(operational_tasks.list_operational_tasks(company_id, user_id)):
        created = datetime.datetime.combine(d.document_date, datetime.time(8, 0)).astimezone() if d.document_date else None
        out.append(WorkItem(f"DOC:{d.kind}:{d.document_id}:{i}", "DOC", SOURCES["DOC"], "STEP", d.kind_label, d.document_id,
                            d.title, d.counterparty_name, None, False, "NORMAL", PRIORITIES["NORMAL"], created, False, "",
                            {"kind": d.kind, "document_type_code": d.document_type_code, "document_id": d.document_id,
                             "document_date": d.document_date},
                            _doc_action(d.kind, d.document_type_code, d.kind_label), "doc"))
    return out


def _doc_action(kind: str, document_type_code: str, fallback: str) -> str:
    if kind == "GOODS_RECEIPT" and document_type_code:
        from peecha.services.operational_tasks import warehouse_word

        return f"{warehouse_word(document_type_code)} انبار را تایید کنید"
    return DOC_ACTIONS.get(kind, fallback)


def _crm_items(company_id: int, user_id: int) -> list[WorkItem]:
    from peecha.services.crm import activities

    today = datetime.date.today()
    out = []
    for a in activities.list_activities(company_id, assigned_to_user_id=user_id, open_only=True, limit=200):
        due = _end_of(a.due_date) if a.due_date else None
        out.append(WorkItem(f"CRM:{a.activity_id}", "CRM", SOURCES["CRM"], "FOLLOWUP", a.type_label, a.activity_id, a.subject,
                            a.customer_name or (f"سرنخ: {a.lead_name}" if a.lead_name else ""), due,
                            bool(a.due_date and a.due_date < today), a.priority_code or "NORMAL",
                            PRIORITIES.get(a.priority_code or "NORMAL", ""), a.created_at, False, a.next_action or "",
                            {"customer_id": a.customer_detail_account_id},
                            f"پیگیری کنید ({a.type_label})" if a.type_label else "پیگیری کنید", "followup"))
    return out


def _ticket_items(company_id: int, user_id: int) -> list[WorkItem]:
    """R356: تیکت‌های باز ارجاع‌شده به کاربر؛ موعد همان موعد حل تعهد زمانی است."""
    from peecha.services.crm import tickets

    out = []
    for t in tickets.list_tickets(company_id, open_only=True, assignee_user_id=user_id, limit=300):
        state = t.sla_state()
        out.append(WorkItem(f"TICKET:{t.ticket_id}", "TICKET", SOURCES["TICKET"], "FOLLOWUP", t.type_label, t.ticket_id,
                            f"تیکت {t.ticket_no or t.ticket_id}: {t.subject}", t.customer_name or "", t.resolution_due_at,
                            state == "BREACHED", t.priority_code or "NORMAL", PRIORITIES.get(t.priority_code or "NORMAL", ""),
                            t.opened_at, False, t.status_label + (" — نزدیک به پایان مهلت" if state == "AT_RISK" else ""),
                            {"ticket_id": t.ticket_id, "customer_id": t.customer_detail_account_id},
                            "به تیکت رسیدگی و پاسخ کنید", "followup"))
    return out


def _can_approve_customers(company_id: int, user_id: int) -> bool:
    from peecha.services import roles as roles_service

    return roles_service.user_has_permission(user_id, company_id, _CUSTOMER_FORM, "EDIT")


def _customer_items(company_id: int, user_id: int) -> list[WorkItem]:
    """مشتریان تازهٔ منتظر تایید (همان صندوق تایید قبلی موبایل)؛ اگر فرایند گردش کار تاییدشان را در دست دارد، فقط آن دیده می‌شود."""
    from sqlalchemy import select

    from peecha.db.base import new_session
    from peecha.db.models.accounting import DetailAccount
    from peecha.db.models.commercial import CustomerProfile
    from peecha.db.models.workflow import WfInstance
    from peecha.services.workflow.common import OPEN_INSTANCE_STATUSES, user_names

    if not _can_approve_customers(company_id, user_id):
        return []
    with new_session() as session:
        profiles = list(session.scalars(select(CustomerProfile).where(CustomerProfile.company_id == company_id,
                                                                      CustomerProfile.status_code == "PENDING_APPROVAL")))
        if not profiles:
            return []
        ids = [p.customer_detail_account_id for p in profiles]
        governed = set(session.scalars(select(WfInstance.entity_id).where(
            WfInstance.company_id == company_id, WfInstance.entity_type == "CUSTOMER", WfInstance.entity_id.in_(ids),
            WfInstance.status_code.in_(OPEN_INSTANCE_STATUSES))))
        names = {d.detail_account_id: (d.code, d.name) for d in session.scalars(
            select(DetailAccount).where(DetailAccount.detail_account_id.in_(ids)))}
        people = user_names(session, {p.submitted_by_user_id for p in profiles if p.submitted_by_user_id})
    out = []
    for p in profiles:
        cid = p.customer_detail_account_id
        if cid in governed:
            continue
        code, name = names.get(cid, ("", f"#{cid}"))
        created = p.submitted_at.astimezone() if p.submitted_at and p.submitted_at.tzinfo is None else p.submitted_at
        out.append(WorkItem(f"CUSTOMER:{cid}", "CUSTOMER", SOURCES["CUSTOMER"], "APPROVAL", KINDS["APPROVAL"], cid,
                            f"مشتری جدید: {name}", people.get(p.submitted_by_user_id, ""), None, False, "NORMAL",
                            PRIORITIES["NORMAL"], created, True, f"کد {code}" if code else "",
                            {"customer_id": cid, "code": code, "name": name},
                            "مشتری جدید را تایید یا رد کنید", "customer"))
    return out


def _stuck_items(company_id: int, user_id: int) -> list[WorkItem]:
    """R325: مرحلهٔ گردش کاری که کسی برای انجامش پیدا نشد؛ مدیر باید ارجاعش دهد وگرنه سند گیر می‌کند."""
    if not tasks.can_reassign(company_id, user_id):
        return []
    from sqlalchemy import select

    from peecha.db.base import new_session
    from peecha.db.models.workflow import WfException, WfTask

    rows = tasks.list_unassigned(company_id)
    if not rows:
        return []
    with new_session() as session:
        reasons = {(e.instance_id, e.node_id): e.reason for e in session.scalars(select(WfException).where(
            WfException.company_id == company_id, WfException.status_code.in_(("OPEN", "ESCALATED")),
            WfException.instance_id.in_({t.instance_id for t in rows if t.instance_id})))}
        nodes = dict(session.execute(select(WfTask.task_id, WfTask.node_id).where(WfTask.task_id.in_([t.task_id for t in rows]))).all())
    out = []
    for t in rows:
        path = _wf_path(company_id, t.instance_id)
        step_no, step_total = _progress(path)
        reason = reasons.get((t.instance_id, nodes.get(t.task_id))) or "کسی برای انجام این مرحله پیدا نشد."
        out.append(WorkItem(f"STUCK:{t.task_id}", "STUCK", SOURCES["STUCK"], "STEP", "مرحلهٔ بی‌گیرنده", t.task_id, t.title,
                            t.requested_by, t.due_at, t.is_overdue, "HIGH", PRIORITIES["HIGH"], t.created_at, False, reason,
                            {"instance_id": t.instance_id, "entity_type": t.entity_type, "entity_id": t.entity_id,
                             "open_nav": t.open_nav, "definition": t.definition_name, "requested_by_user_id": t.requested_by_user_id},
                            "این مرحله گیرنده ندارد؛ آن را به فرد مناسب ارجاع دهید", "task", step_no, step_total, path))
    return out


def _failed_items(company_id: int, user_id: int) -> list[WorkItem]:
    """R328: اقدام خودکار فرایند (مثلاً تصویب یا ثبت سند) انجام نشد؛ بدون این کارت فقط یک اعلان می‌رفت و سند بی‌صدا
    منتظر می‌ماند. برای مدیران و مسئول همان مورد، با «اجرای دوباره»."""
    from sqlalchemy import select

    from peecha.db.base import new_session
    from peecha.db.models.workflow import WfDefinitionVersion, WfException, WfInstance

    manager = tasks.can_reassign(company_id, user_id)
    with new_session() as session:
        q = select(WfException, WfInstance).join(WfInstance, WfInstance.instance_id == WfException.instance_id).where(
            WfException.company_id == company_id, WfException.status_code.in_(("OPEN", "RETRYING", "ESCALATED")),
            WfInstance.status_code.in_(("RUNNING", "WAITING")))
        if not manager:
            q = q.where(WfException.owner_user_id == user_id)
        rows = []
        for ex, inst in session.execute(q.order_by(WfException.exception_id)):
            graph = session.get(WfDefinitionVersion, inst.version_id).graph or {}
            node = next((n for n in graph.get("nodes") or [] if n.get("id") == ex.node_id), {})
            if node.get("type") == "ACTION":
                rows.append((ex.exception_id, ex.title, ex.reason, ex.created_at, inst.instance_id, inst.entity_type,
                             inst.entity_id, inst.title or "", node.get("label") or ""))
    out = []
    for exception_id, title, reason, created_at, instance_id, entity_type, entity_id, inst_title, label in rows:
        adapter = registry.get_adapter(entity_type)
        path = _wf_path(company_id, instance_id)
        step_no, step_total = _progress(path)
        out.append(WorkItem(f"FAILED:{exception_id}", "FAILED", SOURCES["FAILED"], "STEP", "اقدام ناموفق", exception_id,
                            inst_title or title, label, None, True, "HIGH", PRIORITIES["HIGH"], created_at, False, reason or "",
                            {"instance_id": instance_id, "entity_type": entity_type, "entity_id": entity_id,
                             "open_nav": adapter.open_nav if adapter else None, "exception_id": exception_id},
                            f"«{label or 'اقدام خودکار'}» انجام نشد؛ علت را برطرف کنید و «اجرای دوباره» را بزنید", "task",
                            step_no, step_total, path))
    return out


_PROVIDERS = {"WF": _wf_items, "CARTABLE": _cartable_items, "DOC": _doc_items, "CRM": _crm_items, "CUSTOMER": _customer_items,
              "TICKET": _ticket_items, "STUCK": _stuck_items, "FAILED": _failed_items}


def my_work(company_id: int, user_id: int, *, sources: tuple[str, ...] | None = None) -> list[WorkItem]:
    items: list[WorkItem] = []
    for code, provider in _PROVIDERS.items():
        if sources and code not in sources:
            continue
        try:
            items += provider(company_id, user_id)
        except Exception:  # noqa: BLE001 -- خطای یک منبع نباید کل کارتابل را خالی کند
            continue
    rank = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}
    far = datetime.datetime.max.replace(tzinfo=datetime.timezone.utc)
    items.sort(key=lambda w: (not w.is_overdue, rank.get(w.priority_code, 2), w.due_at or far,
                              -(w.created_at.timestamp() if w.created_at else 0)))
    return items


def approvals(company_id: int, user_id: int) -> list[WorkItem]:
    return [w for w in my_work(company_id, user_id, sources=("WF", "CARTABLE", "CUSTOMER")) if w.kind == "APPROVAL"]


def my_requests(company_id: int, user_id: int, limit: int = 100) -> list[WorkItem]:
    """درخواست‌های در جریانی که خود کاربر فرستاده؛ منتظر چه کسی است و در کدام مرحله."""
    from sqlalchemy import select

    from peecha.db.base import new_session
    from peecha.db.models.workflow import WfDefinition, WfInstance, WfTask, WfTaskAssignee
    from peecha.services.workflow.common import user_names

    with new_session() as session:
        rows = list(session.scalars(select(WfInstance).where(
            WfInstance.company_id == company_id, WfInstance.started_by_user_id == user_id,
            WfInstance.status_code.in_(("RUNNING", "WAITING"))).order_by(WfInstance.instance_id.desc()).limit(limit)))
        if not rows:
            return _my_orders(company_id, user_id, set(), limit)
        ids = [r.instance_id for r in rows]
        defs = dict(session.execute(select(WfDefinition.definition_id, WfDefinition.name).where(
            WfDefinition.definition_id.in_({r.definition_id for r in rows}))).all())
        open_tasks = list(session.scalars(select(WfTask).where(WfTask.instance_id.in_(ids), WfTask.status_code == "OPEN")))
        seats = session.execute(select(WfTaskAssignee.task_id, WfTaskAssignee.user_id).where(
            WfTaskAssignee.task_id.in_([t.task_id for t in open_tasks] or [-1]), WfTaskAssignee.status_code == "ACTIVE")).all()
        names = user_names(session, {u for _t, u in seats})
    by_instance: dict[int, list] = {}
    for t in open_tasks:
        by_instance.setdefault(t.instance_id, []).append(t)
    who_by_task: dict[int, list[str]] = {}
    for task_id, uid in seats:
        who_by_task.setdefault(task_id, []).append(names.get(uid, ""))
    t_now = now()
    out = []
    for r in rows:
        open_ = by_instance.get(r.instance_id, [])
        who = "، ".join(sorted({n for t in open_ for n in who_by_task.get(t.task_id, []) if n}))
        dues = [t.due_at for t in open_ if t.due_at]
        due = min(dues) if dues else None
        path = _wf_path(company_id, r.instance_id)
        step_no, step_total = _progress(path)
        waiting = next((label for label, state in path if state == "current"), "")
        out.append(WorkItem(f"MINE:{r.instance_id}", "MINE", SOURCES["MINE"], "REQUEST", KINDS["REQUEST"], r.instance_id,
                            r.title or defs.get(r.definition_id, ""), f"منتظر: {who}" if who else "در حال انجام خودکار",
                            due, bool(due and due < t_now), "NORMAL", PRIORITIES["NORMAL"], r.started_at, False,
                            waiting, {"instance_id": r.instance_id, "entity_type": r.entity_type, "entity_id": r.entity_id,
                                      "definition": defs.get(r.definition_id, ""), "open_task_ids": [t.task_id for t in open_],
                                      "waiting_on": who},
                            f"منتظر {who}" if who else "در حال انجام", "mine", step_no, step_total, path))
    return out + _my_orders(company_id, user_id, {(r.entity_type, r.entity_id) for r in rows}, limit)


def _my_orders(company_id: int, user_id: int, in_workflow: set, limit: int) -> list[WorkItem]:
    """R302: سفارش خرید/فروشی که خود کاربر صادر کرده و هنوز کامل فاکتور نشده، با مرحلهٔ فعلی و منتظر چه کسی است
    (فقط نمایش؛ سفارشی که فرایند گردش کار دارد همان‌جا دیده می‌شود و تکرار نمی‌شود)."""
    from peecha.services import operational_tasks

    try:
        orders = operational_tasks.list_my_orders_in_progress(company_id, user_id, limit)
    except Exception:  # noqa: BLE001 -- خطای این بخش نباید درخواست‌های گردش کار را پنهان کند
        return []
    out = []
    for o in orders:
        if (o.document_type_code, o.document_id) in in_workflow:
            continue
        step_no, step_total = _progress(o.path)
        out.append(WorkItem(f"MYDOC:{o.document_id}", "MINE", SOURCES["MINE"], "REQUEST", KINDS["REQUEST"], o.document_id,
                            o.title, f"منتظر: {o.waiting_on}", None, False, "NORMAL", PRIORITIES["NORMAL"], o.created_at, False,
                            o.current_step, {"document_id": o.document_id, "document_type_code": o.document_type_code,
                                             "counterparty": o.counterparty_name, "document_date": o.document_date,
                                             "definition": "مراحل سفارش", "open_task_ids": [], "waiting_on": o.waiting_on},
                            f"منتظر {o.waiting_on}", "mine", step_no, step_total, o.path))
    return out


@dataclass
class Summary:
    total: int
    approvals: int
    overdue: int
    due_today: int
    on_behalf: int


def summarize(items: list[WorkItem]) -> Summary:
    end = _end_of(datetime.date.today())
    return Summary(len(items), sum(1 for w in items if w.kind == "APPROVAL"), sum(1 for w in items if w.is_overdue),
                   sum(1 for w in items if w.due_at and not w.is_overdue and w.due_at <= end),
                   sum(1 for w in items if "به جای" in w.status_note))


def detail(company_id: int, user_id: int, key: str) -> dict:
    """جزئیات برای تصمیم سریع: اطلاعات کلیدی، مسیر، تاریخچه و تصمیم‌های مجاز."""
    source, _sep, rest = key.partition(":")
    empty = {"path": [], "history": [], "decisions": [], "assignees": [], "form_fields": [], "instructions": "", "due_at": None,
             "sla": "", "row_version": None}
    if source == "FAILED":
        item = next((w for w in _failed_items(company_id, user_id) if w.key == key), None)
        if item is None:
            raise WorkflowError("این مورد دیگر باز نیست.")
        return {**empty, "title": item.title, "requester": item.subtitle, "path": item.path, "instructions": item.status_note,
                "context": tasks.context_rows(company_id, item.extra.get("entity_type"), item.extra.get("entity_id"))}
    if source == "STUCK":
        d = tasks.task_detail(company_id, int(rest), user_id)
        item = next((w for w in _stuck_items(company_id, user_id) if w.key == key), None)
        return {**empty, "title": d.row.title, "requester": d.row.requested_by, "context": d.context, "path": d.path,
                "history": d.history, "instructions": item.status_note if item else "", "due_at": d.row.due_at,
                "row_version": d.row.row_version}
    if source == "WF":
        d = tasks.task_detail(company_id, int(rest), user_id)
        return {"title": d.row.title, "requester": d.row.requested_by, "context": d.context, "path": d.path,
                "history": d.history, "decisions": d.decisions, "assignees": d.assignees, "form_fields": d.form_fields,
                "instructions": d.row.instructions, "due_at": d.row.due_at, "sla": d.row.sla_label,
                "row_version": d.row.row_version}
    if source == "CARTABLE":
        from peecha.services import cartable

        row = next((c for c in cartable.list_my_tasks(user_id, company_id) if c.cartable_item_id == int(rest)), None)
        if row is None:
            raise WorkflowError("این مورد دیگر منتظر تایید شما نیست.")
        steps = _legacy_steps(row.current_step_no, row.total_steps)
        return {**empty, "title": f"{row.form_label}: {row.description}", "requester": row.submitted_by_name,
                "context": [("فرم", row.form_label), ("شرح", row.description),
                            ("درخواست", _REQUEST_TYPES.get(row.request_type_code, "")),
                            ("مرحله", f"{row.current_step_no} از {row.total_steps}"), ("صادرکننده", row.submitted_by_name)],
                "path": steps, "decisions": [("APPROVE", "تایید"), ("REJECT", "رد")]}
    if source == "CUSTOMER":
        from peecha.services.workflow import registry

        item = next((w for w in _customer_items(company_id, user_id) if w.key == key), None)
        if item is None:
            raise WorkflowError("این مشتری دیگر منتظر تایید شما نیست.")
        adapter = registry.get_adapter("CUSTOMER")
        try:
            context = list(adapter.approval_context(company_id, item.ref_id)) if adapter and adapter.approval_context else []
        except Exception:  # noqa: BLE001
            context = []
        return {**empty, "title": item.title, "requester": item.subtitle, "context": context or [("مشتری", item.extra["name"])],
                "decisions": [("APPROVE", "تایید"), ("REJECT", "رد")]}
    if source == "MINE":
        item = next((w for w in my_requests(company_id, user_id) if w.key == key), None)
        if item is None:
            raise WorkflowError("این درخواست دیگر در جریان نیست.")
        history = []
        if item.extra["open_task_ids"]:
            d = tasks.task_detail(company_id, item.extra["open_task_ids"][0], user_id)
            history = d.history
        return {**empty, "title": item.title, "requester": "شما", "path": item.path, "history": history, "due_at": item.due_at,
                "context": [("فرایند", item.extra["definition"]), ("منتظر", item.extra["waiting_on"] or "—"),
                            ("مرحلهٔ جاری", item.status_note or "—")]}
    if source == "MYDOC":
        item = next((w for w in my_requests(company_id, user_id) if w.key == key), None)
        if item is None:
            raise WorkflowError("این سفارش دیگر در جریان نیست.")
        from peecha import numerals

        context = [("سند", item.title), ("طرف حساب", item.extra["counterparty"] or "—"),
                   ("مرحلهٔ جاری", item.status_note), ("منتظر", item.extra["waiting_on"])]
        if item.extra.get("document_date"):
            context.insert(2, ("تاریخ", numerals.format_jalali_date(item.extra["document_date"])))
        return {**empty, "title": item.title, "requester": "شما", "path": item.path, "context": context,
                "instructions": "برای دیدن یا ادامهٔ کار، سند را باز کنید."}
    if source in ("DOC", "CRM", "TICKET"):
        item = next((w for w in my_work(company_id, user_id, sources=(source,)) if w.key == key), None)
        if item is None:
            raise WorkflowError("این کار دیگر منتظر شما نیست.")
        context = [("کار لازم", item.kind_label), ("سند" if source == "DOC" else "موضوع", item.title),
                   ("طرف حساب" if source == "DOC" else "مشتری", item.subtitle or "—")]
        if source == "DOC" and item.extra.get("document_date"):
            from peecha import numerals

            context.append(("تاریخ", numerals.format_jalali_date(item.extra["document_date"])))
        if item.status_note:
            context.append(("وضعیت" if source == "TICKET" else "اقدام بعدی", item.status_note))
        instructions = {"DOC": "برای انجام، سند را باز کنید.", "TICKET": "برای پاسخ و رسیدگی، تیکت را باز کنید."}
        return {**empty, "title": item.title, "requester": item.subtitle, "context": context, "due_at": item.due_at,
                "instructions": instructions.get(source, "برای پیگیری، پروندهٔ مشتری را باز کنید.")}
    raise WorkflowError("برای این مورد تصمیم سریع وجود ندارد؛ سند را باز کنید.")


def quick_decide(company_id: int, user_id: int, key: str, decision: str, comment: str = "", *,
                 row_version: int | None = None, data: dict | None = None, channel: str = "DESKTOP") -> str:
    """تصمیم از کارتابل یکپارچه؛ پیام نتیجه به فارسی برمی‌گردد."""
    source, _sep, rest = key.partition(":")
    decision = (decision or "").upper()
    if source == "WF":
        return tasks.decide(company_id, int(rest), user_id, decision, comment, row_version=row_version, data=data,
                            channel=channel).message
    if source == "CARTABLE":
        from peecha.services import cartable

        if decision == "APPROVE":
            cartable.approve_item(int(rest), user_id, comment or "")
            return "تایید شد."
        if decision == "REJECT":
            if not (comment or "").strip():
                raise WorkflowError("لطفاً علت رد را بنویسید.")
            cartable.reject_item(int(rest), user_id, comment)
            return "رد شد."
        raise WorkflowError("در کارتابل اسناد فقط تایید یا رد ممکن است.")
    if source == "CUSTOMER":
        from peecha.services import commercial_partners

        if not _can_approve_customers(company_id, user_id):
            raise WorkflowError("دسترسی تایید مشتری را ندارید.")
        if decision == "APPROVE":
            commercial_partners.approve_customer(int(rest), user_id)
            return "مشتری تایید و فعال شد."
        if decision == "REJECT":
            if not (comment or "").strip():
                raise WorkflowError("لطفاً علت رد را بنویسید.")
            commercial_partners.reject_customer(int(rest), user_id, comment)
            return "مشتری رد شد."
        raise WorkflowError("برای مشتری جدید فقط تایید یا رد ممکن است.")
    raise WorkflowError("برای این مورد تصمیم سریع وجود ندارد؛ سند را باز کنید.")


def bulk_approve(company_id: int, user_id: int, keys: list[str], comment: str = "") -> list[tuple[str, bool, str]]:
    """تایید گروهی؛ هر مورد جدا (شکست یکی بقیه را متوقف نمی‌کند)."""
    results = []
    for key in keys:
        try:
            results.append((key, True, quick_decide(company_id, user_id, key, "APPROVE", comment)))
        except ValueError as exc:
            results.append((key, False, str(exc)))
    return results


def remind(company_id: int, user_id: int, key: str, note: str = "") -> int:
    """یادآوری به گیرندگان کارهای باز یک درخواست خودم؛ تعداد گیرندگان برمی‌گردد."""
    from peecha.services.workflow import sla

    item = next((w for w in my_requests(company_id, user_id) if w.key == key), None)
    if item is None or not item.extra["open_task_ids"]:
        raise WorkflowError("این درخواست کار بازی ندارد که یادآوری شود.")
    return sum(sla.remind_now(company_id, task_id, user_id, note) for task_id in item.extra["open_task_ids"])


def withdraw(company_id: int, user_id: int, key: str, reason: str = "") -> None:
    source, _sep, rest = key.partition(":")
    if source == "MYDOC":
        raise WorkflowError("این سفارش درخواست گردش کار نیست؛ برای لغو، خود سند را باز کنید.")
    if source != "MINE":
        raise WorkflowError("فقط درخواست‌های خودتان را می‌توانید پس بگیرید.")
    tasks.withdraw_request(company_id, int(rest), user_id, reason)


def counts(company_id: int, user_id: int) -> dict[str, int]:
    """شمارش سریع برای نشانک منو/ریبون."""
    items = my_work(company_id, user_id)
    s = summarize(items)
    return {"total": s.total, "approvals": s.approvals, "overdue": s.overdue, "generated_at": int(now().timestamp())}
