"""«کارهای من» و «مرکز تایید»: همهٔ کارهای منتظر یک کاربر در یک فهرست.

منابع: کارها و تاییدهای موتور گردش کار، کارتابل اسناد (تایید چندمرحله‌ای قبلی)، مراحل منتظر اسناد خرید/فروش/انبار و
پیگیری‌های باز ارتباط با مشتری. هر منبع منطق خودش را نگه می‌دارد؛ این‌جا فقط کنار هم دیده و از یک‌جا انجام می‌شوند.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from peecha.services.workflow import tasks
from peecha.services.workflow.common import PRIORITIES, WorkflowError, now

SOURCES = {"WF": "گردش کار", "CARTABLE": "کارتابل اسناد", "DOC": "اسناد خرید، فروش و انبار", "CRM": "پیگیری مشتری"}
KINDS = {"APPROVAL": "تایید", "TASK": "کار", "STEP": "مرحلهٔ سند", "FOLLOWUP": "پیگیری"}
_REQUEST_TYPES = {"CREATE": "ثبت و تایید", "EDIT": "ویرایش", "DELETE": "حذف"}


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


def _end_of(day: datetime.date) -> datetime.datetime:
    return datetime.datetime.combine(day, datetime.time(23, 59)).astimezone()


def _wf_items(company_id: int, user_id: int) -> list[WorkItem]:
    out = []
    for t in tasks.list_my_tasks(company_id, user_id):
        note = t.sla_label if t.sla_status not in ("NONE", "ON_TRACK") else ""
        if t.on_behalf_of:
            note = (note + "، " if note else "") + f"به جای {t.on_behalf_of}"
        out.append(WorkItem(f"WF:{t.task_id}", "WF", SOURCES["WF"], t.kind, KINDS[t.kind], t.task_id, t.title,
                            t.requested_by, t.due_at, t.is_overdue, t.priority_code, t.priority_label, t.created_at,
                            t.kind == "APPROVAL", note,
                            {"row_version": t.row_version, "instance_id": t.instance_id, "entity_type": t.entity_type,
                             "entity_id": t.entity_id, "open_nav": t.open_nav, "definition": t.definition_name}))
    return out


def _cartable_items(company_id: int, user_id: int) -> list[WorkItem]:
    from peecha.services import cartable

    out = []
    for c in cartable.list_my_tasks(user_id, company_id):
        out.append(WorkItem(f"CARTABLE:{c.cartable_item_id}", "CARTABLE", SOURCES["CARTABLE"], "APPROVAL", KINDS["APPROVAL"],
                            c.cartable_item_id, f"{c.form_label}: {c.description}", c.submitted_by_name, None, False, "NORMAL",
                            PRIORITIES["NORMAL"], c.submitted_at, True,
                            f"مرحلهٔ {c.current_step_no} از {c.total_steps} — {_REQUEST_TYPES.get(c.request_type_code, '')}",
                            {"form_code": c.form_code, "source_record_id": c.source_record_id}))
    return out


def _doc_items(company_id: int, user_id: int) -> list[WorkItem]:
    from peecha.services import operational_tasks

    out = []
    for i, d in enumerate(operational_tasks.list_operational_tasks(company_id, user_id)):
        created = datetime.datetime.combine(d.document_date, datetime.time(8, 0)).astimezone() if d.document_date else None
        out.append(WorkItem(f"DOC:{d.kind}:{d.document_id}:{i}", "DOC", SOURCES["DOC"], "STEP", d.kind_label, d.document_id,
                            d.title, d.counterparty_name, None, False, "NORMAL", PRIORITIES["NORMAL"], created, False, "",
                            {"kind": d.kind, "document_type_code": d.document_type_code, "document_id": d.document_id}))
    return out


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
                            {"customer_id": a.customer_detail_account_id}))
    return out


_PROVIDERS = {"WF": _wf_items, "CARTABLE": _cartable_items, "DOC": _doc_items, "CRM": _crm_items}


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
    return [w for w in my_work(company_id, user_id, sources=("WF", "CARTABLE")) if w.kind == "APPROVAL"]


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
        return {"title": f"{row.form_label}: {row.description}", "requester": row.submitted_by_name,
                "context": [("فرم", row.form_label), ("درخواست", _REQUEST_TYPES.get(row.request_type_code, "")),
                            ("مرحله", f"{row.current_step_no} از {row.total_steps}")],
                "path": [], "history": [], "decisions": [("APPROVE", "تایید"), ("REJECT", "رد")], "assignees": [],
                "form_fields": [], "instructions": "", "due_at": None, "sla": "", "row_version": None}
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


def counts(company_id: int, user_id: int) -> dict[str, int]:
    """شمارش سریع برای نشانک منو/ریبون."""
    items = my_work(company_id, user_id)
    s = summarize(items)
    return {"total": s.total, "approvals": s.approvals, "overdue": s.overdue, "generated_at": int(now().timestamp())}
