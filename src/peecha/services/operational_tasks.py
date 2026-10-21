"""کارهای عملیاتی در انتظار کاربر — R226.

کارتابل گردش کار (services/cartable.py) فقط آیتم‌های ثبت‌شده در موتور
گردش کار را دارد؛ مراحل اسناد بازرگانی (تصویب مدیر، رسید کالا، تایید
نحوهٔ تسویه، تبدیل سفارش رسیده به فاکتور) هیچ‌وقت آن‌جا نمی‌رسیدند. این
سرویس همان صف‌های موجود را (بدون منطق تازه) برای همین کاربر جمع می‌کند.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.commercial import CommercialDocument, CommercialDocumentSettlementPlan
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_settings as settings_service
from peecha.services import roles as roles_service

_DOC_TYPE_TITLES = {
    "SALES_ORDER": "سفارش فروش", "SALES_PROFORMA": "پیش‌فاکتور فروش", "SALES_INVOICE": "فاکتور فروش",
    "SALES_RETURN": "برگشت از فروش", "PURCHASE_ORDER": "سفارش خرید", "PURCHASE_PROFORMA": "پیش‌فاکتور خرید",
    "PURCHASE_INVOICE": "فاکتور خرید", "PURCHASE_RETURN": "برگشت به تامین‌کننده",
    "CONSIGNMENT_IN": "امانی ورودی", "CONSIGNMENT_OUT": "امانی خروجی",
}

# نوعِ کار -> برچسب
KIND_LABELS = {
    "MANAGER_APPROVAL": "تصویب مدیر",
    "PR_APPROVAL": "تصویب درخواست خرید",
    "GOODS_RECEIPT": "تایید انبار (رسید/حواله)",
    "PRE_SALES_WAREHOUSE": "تایید انبار سفارش",
    "SETTLEMENT_APPROVAL": "تایید نحوهٔ تسویه",
    "CONVERT_TO_INVOICE": "تبدیل به فاکتور",
    "POST_ORDER": "ثبت نهایی سفارش (پیش از رسید)",
    "INVENTORY_RESIDUAL": "اصلاح ماندهٔ ریالی موجودی صفر",
    "PUTAWAY_PENDING": "چیدن کالای رسیده در قفسه",
    "QC_PENDING": "کنترل کیفیت رسیدها",
    "EXPIRY_NEAR": "کالای نزدیک به انقضا",
    "EXPIRED_STOCK": "کالای منقضی در انبار",
    "TRANSIT_ARRIVING": "ارسال در راه به انبار",
    "CROSS_DOCK": "ارسال مستقیم از رسید",
    # R312: نگهداری و تعمیرات
    "MNT_MY_WORK": "دستور کار نگهداری",
    "MNT_TO_VERIFY": "آزمون دستور کار نگهداری",
    "MNT_NEW_REQUEST": "درخواست تعمیر بررسی‌نشده",
    "MNT_APPROVAL": "تأیید نگهداری",
    # R313: بودجه‌ریزی
    "BUD_REVIEW": "بررسی نسخهٔ بودجه",
    "BUD_APPROVE": "تأیید نسخهٔ بودجه",
    "BUD_PUBLISH": "انتشار نسخهٔ بودجه",
    "BUD_REVISE": "اصلاح نسخهٔ ردشدهٔ بودجه",
    "BUD_EXCEPTION": "مجوز تجاوز از بودجه",
    "OPN_ENTER": "ورود اطلاعات افتتاحیه",
    "OPN_APPROVE": "بررسی و تأیید اطلاعات افتتاحیه",
    "OPN_POST": "ثبت قطعی افتتاحیه",
    "OPN_LOCK": "قفل نهایی افتتاحیه",
}


# R302: برای فروش «حواله» و برای خرید «رسید» (برچسب یکسان «رسید/حواله» گیج‌کننده بود)
def warehouse_word(document_type_code: str) -> str:
    return "حواله" if document_type_code.startswith("SALES_") or document_type_code == "CONSIGNMENT_OUT" else "رسید"


def kind_label(kind: str, document_type_code: str) -> str:
    if kind == "GOODS_RECEIPT" and document_type_code:
        return f"تایید {warehouse_word(document_type_code)} انبار"
    if kind == "POST_ORDER" and document_type_code:
        return f"ثبت نهایی سفارش (پیش از {warehouse_word(document_type_code)})"
    return KIND_LABELS[kind]


@dataclass
class OperationalTask:
    kind: str
    kind_label: str
    document_id: int
    document_type_code: str
    title: str
    counterparty_name: str
    document_date: datetime.date | None
    status_code: str


def _rows(company_id: int, docs: list[CommercialDocument], kind: str) -> list[OperationalTask]:
    if not docs:
        return []
    with new_session() as session:
        names = dict(session.execute(
            select(DetailAccount.detail_account_id, DetailAccount.name).where(
                DetailAccount.detail_account_id.in_({d.counterparty_detail_account_id for d in docs})
            )
        ).all())
    return [
        OperationalTask(
            kind, kind_label(kind, d.document_type_code), d.document_id, d.document_type_code,
            f"{_DOC_TYPE_TITLES.get(d.document_type_code, d.document_type_code)} {d.document_no}",
            names.get(d.counterparty_detail_account_id) or "", d.document_date, d.status_code,
        )
        for d in docs
    ]


def list_operational_tasks(company_id: int, user_id: int) -> list[OperationalTask]:
    is_manager = roles_service.is_manager(user_id, company_id)
    tasks: list[OperationalTask] = []
    with new_session() as session:
        if is_manager:
            # R232: خرید و فروش با همان قاعدهٔ تنظیمی
            approval_types = [
                t for t in ("PURCHASE_ORDER", "PURCHASE_INVOICE", "PURCHASE_PROFORMA", "SALES_ORDER", "SALES_INVOICE", "SALES_PROFORMA")
                if documents_service.requires_manager_approval(company_id, t)
            ]
            manager_docs = list(session.scalars(
                select(CommercialDocument).where(
                    CommercialDocument.company_id == company_id, CommercialDocument.status_code == "CONFIRMED",
                    CommercialDocument.document_type_code.in_(approval_types),
                ).order_by(CommercialDocument.document_id)
            )) if approval_types else []
            plan_docs = list(session.scalars(
                select(CommercialDocument)
                .join(CommercialDocumentSettlementPlan, CommercialDocumentSettlementPlan.document_id == CommercialDocument.document_id)
                .where(
                    CommercialDocument.company_id == company_id,
                    CommercialDocumentSettlementPlan.status_code == "PENDING_APPROVAL",
                    CommercialDocument.status_code.in_(("DRAFT", "CONFIRMED", "APPROVED")),
                ).order_by(CommercialDocument.document_id)
            ))
        else:
            manager_docs, plan_docs = [], []
    tasks += _rows(company_id, manager_docs, "MANAGER_APPROVAL")
    tasks += _purchase_request_approvals(company_id, is_manager)

    # R230/R232: سفارشی که تا ثبتِ نهایی نشود به تاییدِ رسید/حوالهٔ انبار نمی‌رسد
    for order_type in ("PURCHASE_ORDER", "SALES_ORDER"):
        if not is_manager or documents_service.receipt_eligible_statuses(company_id, order_type) != ("POSTED",):
            continue
        ready = ("APPROVED",) if documents_service.requires_manager_approval(company_id, order_type) else ("CONFIRMED", "APPROVED")
        with new_session() as session:
            to_post = [
                d for d in session.scalars(
                    select(CommercialDocument).where(
                        CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == order_type,
                        CommercialDocument.status_code.in_(ready),
                    ).order_by(CommercialDocument.document_id)
                ) if not documents_service._is_pre_sales_order(session, d)
            ]
        tasks += _rows(company_id, to_post, "POST_ORDER")

    receipt_queue = documents_service.list_purchase_order_goods_receipt_queue(company_id, user_id)
    tasks += _rows(company_id, [d for d in receipt_queue if d.warehouse_approved_at is None], "GOODS_RECEIPT")

    allowed = documents_service.receivable_warehouse_ids(company_id, user_id)
    pre_sales = [
        d for d in documents_service.list_pre_sales_pending_warehouse_approval(company_id)
        if allowed is None or d.warehouse_id in allowed
    ]
    tasks += _rows(company_id, pre_sales, "PRE_SALES_WAREHOUSE")
    tasks += _rows(company_id, plan_docs, "SETTLEMENT_APPROVAL")

    # سفارشِ خرید/فروشِ رسیده/حواله‌شده که هنوز فاکتور نشده: برایِ ثبت‌کنندهٔ سفارش و مدیر
    received = [
        d for d in documents_service.list_purchase_order_goods_receipt_queue(company_id)
        if d.warehouse_approved_at is not None and d.document_type_code in ("PURCHASE_ORDER", "SALES_ORDER")
        and (is_manager or d.created_by_user_id == user_id)
    ]
    tasks += _rows(company_id, received, "CONVERT_TO_INVOICE")

    tasks += _putaway_pending(company_id, user_id, is_manager)
    tasks += _qc_pending(company_id, user_id, is_manager)
    tasks += _expiry_alerts(company_id, user_id, is_manager)
    tasks += _flow_tasks(company_id, user_id, is_manager)
    tasks += _maintenance_tasks(company_id, user_id, is_manager)
    tasks += _budget_tasks(company_id, user_id)
    tasks += _opening_tasks(company_id, user_id)

    if is_manager:
        from peecha.services import inventory_residual as residual_service

        try:
            residuals = residual_service.list_residuals(company_id)
        except Exception:  # noqa: BLE001 -- هشدارِ اختیاری نباید کارتابل را از کار بیندازد
            residuals = []
        if residuals:
            tasks.append(OperationalTask(
                "INVENTORY_RESIDUAL", KIND_LABELS["INVENTORY_RESIDUAL"], 0, "",
                f"{len(residuals)} کالا با موجودی صفر و ماندهٔ ریالی — پیشنهاد سند تسعیر", "", None, "",
            ))
    return tasks


def _purchase_request_approvals(company_id: int, is_manager: bool) -> list[OperationalTask]:
    """R326: درخواست خرید ارسال‌شده برای تصویب، برای مدیر. اگر گردش کار تایید آن را در دست دارد، کارش همان‌جا
    (کار تایید در کارتابل تاییدکننده) دیده می‌شود و این‌جا تکرار نمی‌شود."""
    if not is_manager:
        return []
    from peecha.db.models.commercial import PurchaseRequest
    from peecha.db.models.workflow import WfInstance
    from peecha.services.workflow.common import OPEN_INSTANCE_STATUSES

    with new_session() as session:
        rows = list(session.scalars(select(PurchaseRequest).where(
            PurchaseRequest.company_id == company_id, PurchaseRequest.status_code == "SUBMITTED"
        ).order_by(PurchaseRequest.request_id)))
        governed = set(session.scalars(select(WfInstance.entity_id).where(
            WfInstance.company_id == company_id, WfInstance.entity_type == "PURCHASE_REQUEST",
            WfInstance.status_code.in_(OPEN_INSTANCE_STATUSES)))) if rows else set()
    return [OperationalTask("PR_APPROVAL", KIND_LABELS["PR_APPROVAL"], r.request_id, "PURCHASE_REQUEST",
                            f"درخواست خرید شمارهٔ {r.request_no}", "", r.request_date, r.status_code)
            for r in rows if r.request_id not in governed]


def _putaway_pending(company_id: int, user_id: int, is_manager: bool) -> list[OperationalTask]:
    """R304 (کلید «رسیدهای در قفسه چیده‌نشده در کارتابل انباردار»): یک کار برای هر انبار، برای انباردار همان انبار و مدیر."""
    from peecha.db.models.inventory import Warehouse
    from peecha.services import stock_controls
    from peecha.services import warehouse_operations as ops

    if not stock_controls.is_on(company_id, stock_controls.PUTAWAY_IN_CARTABLE):
        return []
    by_warehouse: dict[int, list] = {}
    for src in ops.putaway_sources(company_id):
        by_warehouse.setdefault(src.doc.destination_warehouse_id, []).append(src)
    if not by_warehouse:
        return []
    with new_session() as session:
        warehouses = {w.warehouse_id: w for w in session.scalars(select(Warehouse).where(Warehouse.warehouse_id.in_(by_warehouse)))}
    out = []
    for warehouse_id, sources in sorted(by_warehouse.items()):
        w = warehouses.get(warehouse_id)
        if w is None or not (is_manager or w.manager_user_id == user_id):
            continue
        lines = sum(s.open_lines for s in sources)
        out.append(OperationalTask(
            "PUTAWAY_PENDING", KIND_LABELS["PUTAWAY_PENDING"], 0, "",
            f"{len(sources)} رسید با {lines} ردیف در قفسه چیده‌نشده در «{w.name}»", w.name,
            max(s.doc.document_date for s in sources), "",
        ))
    return out


def _qc_pending(company_id: int, user_id: int, is_manager: bool) -> list[OperationalTask]:
    """R306 (کلید «نگه‌داشت رسید تا تایید کیفیت»): ردیف‌های منتظر بازرسی، یک کار برای هر انبار."""
    from peecha.db.models.inventory import Warehouse
    from peecha.services import quality_control

    counts = quality_control.pending_by_warehouse(company_id)
    if not counts:
        return []
    with new_session() as session:
        warehouses = {w.warehouse_id: w for w in session.scalars(select(Warehouse).where(Warehouse.warehouse_id.in_(counts)))}
    out = []
    for warehouse_id, n in sorted(counts.items()):
        w = warehouses.get(warehouse_id)
        if w is None or not (is_manager or w.manager_user_id == user_id):
            continue
        out.append(OperationalTask(
            "QC_PENDING", KIND_LABELS["QC_PENDING"], 0, "", f"{n} ردیف رسید در «{w.name}» منتظر کنترل کیفیت است", w.name, None, "",
        ))
    return out


def _maintenance_tasks(company_id: int, user_id: int, is_manager: bool) -> list[OperationalTask]:
    """R312: کارهای واگذارشده به من، آزمون منتظر، درخواست بررسی‌نشده و تأییدهای نگهداری.

    کارهای تجمیعی برای مدیر، و با کلید «دسترسی‌های جداگانهٔ نگهداری» برای دارندهٔ همان گام.
    """
    from sqlalchemy import func

    from peecha.db.models.maintenance import CapacityRestriction, PlannedDowntime, PmPlan, PmPostponement, WorkRequest
    from peecha.services import stock_controls
    from peecha.services.maintenance import common as mc
    from peecha.services.maintenance import work_orders as wos

    try:
        mine = wos.my_work(company_id, user_id)
    except Exception:  # noqa: BLE001 -- کارتابل نباید به‌خاطر ماژول اختیاری از کار بیفتد
        return []
    out = [OperationalTask("MNT_MY_WORK", KIND_LABELS["MNT_MY_WORK"], r.work_order_id, "MNT_WORK_ORDER",
                           f"دستور کار {r.wo_no}: {r.title}", r.asset_label,
                           r.planned_start.date() if r.planned_start else None, r.status_code)
           for r in mine if r.status_code not in ("COMPLETED", "VERIFIED")]
    roles_on = stock_controls.is_on(company_id, stock_controls.MNT_ROLE_PERMISSIONS)

    def may(form: str) -> bool:
        return is_manager or (roles_on and mc.can(company_id, user_id, form))

    with new_session() as session:
        if may(mc.FORM_VERIFY):
            n = len(wos.board(company_id, status_codes=("COMPLETED",)))
            if n:
                out.append(OperationalTask("MNT_TO_VERIFY", KIND_LABELS["MNT_TO_VERIFY"], 0, "", f"{n} دستور کار انجام‌شده منتظر آزمون "
                                           "و تأیید است", "", None, ""))
        if may(mc.FORM_PLAN):
            n = session.scalar(select(func.count()).where(WorkRequest.company_id == company_id, WorkRequest.status_code == "NEW"))
            if n:
                out.append(OperationalTask("MNT_NEW_REQUEST", KIND_LABELS["MNT_NEW_REQUEST"], 0, "", f"{n} درخواست تعمیر تازه منتظر "
                                           "بررسی است", "", None, ""))
        for req in session.scalars(select(WorkRequest).where(WorkRequest.company_id == company_id,
                                                             WorkRequest.assigned_to_user_id == user_id,
                                                             WorkRequest.status_code.in_(("NEW", "UNDER_REVIEW")))):
            out.append(OperationalTask("MNT_NEW_REQUEST", "درخواست تعمیر ارجاع‌شده به شما", req.request_id, "MNT_REQUEST",
                                       f"درخواست {req.request_no}: {req.title}", "", req.reported_at.date() if req.reported_at else None,
                                       req.status_code))
        if may(mc.FORM_APPROVE):
            n = (session.scalar(select(func.count()).where(PlannedDowntime.company_id == company_id,
                                                           PlannedDowntime.status_code == "PROPOSED")) or 0) \
                + (session.scalar(select(func.count()).where(CapacityRestriction.company_id == company_id,
                                                             CapacityRestriction.status_code == "PROPOSED")) or 0) \
                + (session.scalar(select(func.count()).select_from(PmPostponement).join(
                    PmPlan, PmPlan.plan_id == PmPostponement.plan_id).where(PmPlan.company_id == company_id,
                                                                            PmPostponement.status_code == "PENDING")) or 0)
            if n:
                out.append(OperationalTask("MNT_APPROVAL", KIND_LABELS["MNT_APPROVAL"], 0, "", f"{n} توقف برنامه‌ریزی‌شده، ظرفیت محدود "
                                           "یا تعویق منتظر تأیید است", "", None, ""))
    return out


def _budget_tasks(company_id: int, user_id: int) -> list[OperationalTask]:
    """R313: گام‌های نسخهٔ بودجه و مجوزهای تجاوز که این کاربر اجازهٔ انجامشان را دارد (همان قاعدهٔ دکمه‌های پرونده).

    گامی که فرایند فعال «با دروازه» دارد از کارتابل گردش کار می‌آید و این‌جا تکرار نمی‌شود.
    """
    from peecha.db.models.budgeting import Budget, BudgetVersion
    from peecha.services.budgeting import approval as bap
    from peecha.services.budgeting import exceptions as bex
    from peecha.services.workflow import model_events

    steps = {"SUBMITTED": ("BUD_REVIEW", "review"), "REVIEWED": ("BUD_APPROVE", "approve"), "APPROVED": ("BUD_PUBLISH", "publish")}
    out: list[OperationalTask] = []
    try:
        with new_session() as session:
            rows = list(session.execute(select(BudgetVersion, Budget).join(Budget, Budget.budget_id == BudgetVersion.budget_id).where(
                Budget.company_id == company_id, BudgetVersion.status_code.in_((*steps, "REJECTED")))))
            gated = {et for et in ("BUDGET_VERSION", "BUDGET_EXCEPTION")
                     if model_events.gate_definitions(session.connection(), company_id, et)}
        for v, b in rows:
            if v.status_code == "REJECTED":
                if v.prepared_by_user_id == user_id:
                    out.append(OperationalTask("BUD_REVISE", KIND_LABELS["BUD_REVISE"], v.version_id, "BUDGET_VERSION",
                                               f"بودجهٔ {b.code} — {b.name}، نسخهٔ {v.version_no}", v.reject_reason or "",
                                               v.created_at.date() if v.created_at else None, v.status_code))
                continue
            kind, action = steps[v.status_code]
            if kind == "BUD_APPROVE" and "BUDGET_VERSION" in gated:
                continue
            if bap.allowed_actions(company_id, user_id, v).get(action):
                when = v.approved_at or v.reviewed_at or v.submitted_at or v.created_at
                out.append(OperationalTask(kind, KIND_LABELS[kind], v.version_id, "BUDGET_VERSION",
                                           f"بودجهٔ {b.code} — {b.name}، نسخهٔ {v.version_no}: {v.title or ''}".rstrip(": "), "",
                                           when.date() if when else None, v.status_code))
        if "BUDGET_EXCEPTION" not in gated:
            for e in bex.list_exceptions(company_id, "PENDING", user_id):
                if e.can_decide:
                    out.append(OperationalTask("BUD_EXCEPTION", KIND_LABELS["BUD_EXCEPTION"], e.exception_id, "BUDGET_EXCEPTION",
                                               f"{e.source_label} — {e.key_label}", e.requested_by, e.requested_at.date(), e.status_code))
    except Exception:  # noqa: BLE001 -- کارتابل نباید به‌خاطر ماژول اختیاری از کار بیفتد
        return []
    return out


def _opening_tasks(company_id: int, user_id: int) -> list[OperationalTask]:
    """R314: گام بعدی هر ماژول افتتاحیه برای همان کسی که انجامش با اوست (مسئول ورود، تأییدکننده، ثبت‌کننده)."""
    from peecha.db.models.opening import OpeningRun, RunModule
    from peecha.services.opening import common as oc

    out: list[OperationalTask] = []
    try:
        with new_session() as session:
            rows = list(session.execute(select(RunModule, OpeningRun).join(OpeningRun, OpeningRun.run_id == RunModule.run_id).where(
                OpeningRun.company_id == company_id, OpeningRun.status_code.in_(("DRAFT", "IN_PROGRESS", "POSTING")))))
            to_lock = list(session.scalars(select(OpeningRun).where(OpeningRun.company_id == company_id,
                                                                    OpeningRun.status_code == "POSTED")))
        can_approve = oc.can(company_id, user_id, oc.FORM_APPROVE)
        can_post = oc.can(company_id, user_id, oc.FORM_POST)
        for m, run in rows:
            title = f"افتتاحیهٔ {run.code} — {oc.MODULE_LABELS[m.module_code]}"
            if m.status_code in ("NOT_STARTED", "ENTERING", "HAS_ERRORS") and m.owner_user_id == user_id:
                kind = "OPN_ENTER"
            elif m.status_code == "READY" and can_approve and m.approver_user_id in (None, user_id) \
                    and m.submitted_by_user_id != user_id:
                kind = "OPN_APPROVE"
            elif m.status_code in ("APPROVED", "POSTING") and can_post:
                kind = "OPN_POST"
            else:
                continue
            note = m.reject_reason if kind == "OPN_ENTER" and m.reject_reason else oc.MODULE_STATUS_LABELS[m.status_code]
            when = m.approved_at or m.submitted_at or run.created_at
            out.append(OperationalTask(kind, KIND_LABELS[kind], run.run_id, "OPENING_RUN", title, note,
                                       when.date() if when else None, m.module_code))
        if can_post:
            for run in to_lock:
                out.append(OperationalTask("OPN_LOCK", KIND_LABELS["OPN_LOCK"], run.run_id, "OPENING_RUN",
                                           f"افتتاحیهٔ {run.code} — {run.title}", "ثبت قطعی کامل شد؛ تطبیق را ببینید و قفل کنید",
                                           run.posted_at.date() if run.posted_at else None, ""))
    except Exception:  # noqa: BLE001 -- کارتابل نباید به‌خاطر ماژول اختیاری از کار بیفتد
        return []
    return out


def _expiry_alerts(company_id: int, user_id: int, is_manager: bool) -> list[OperationalTask]:
    """R307 (کلید «هشدار انقضا و انتقال کالای منقضی»): برای هر انبار یک کار نزدیک‌انقضا و یک کار منقضی."""
    from peecha.db.models.inventory import Warehouse
    from peecha.services import expiry_watch, stock_controls

    if not stock_controls.is_on(company_id, stock_controls.EXPIRY_ALERTS):
        return []
    summary = expiry_watch.summary_by_warehouse(company_id)
    if not summary:
        return []
    days = stock_controls.expiry_alert_days(company_id)
    with new_session() as session:
        keepers = dict(session.execute(select(Warehouse.warehouse_id, Warehouse.manager_user_id).where(
            Warehouse.warehouse_id.in_(summary))).all())
    out = []
    for warehouse_id, s in sorted(summary.items()):
        if not (is_manager or keepers.get(warehouse_id) == user_id):
            continue
        if s.expired:
            out.append(OperationalTask("EXPIRED_STOCK", KIND_LABELS["EXPIRED_STOCK"], 0, "",
                                       f"{s.expired} بچ منقضی در «{s.name}»", s.name, s.first, ""))
        if s.near:
            out.append(OperationalTask("EXPIRY_NEAR", KIND_LABELS["EXPIRY_NEAR"], 0, "",
                                       f"{s.near} بچ در «{s.name}» تا {days} روز دیگر منقضی می‌شود", s.name, None, ""))
    return out


def _flow_tasks(company_id: int, user_id: int, is_manager: bool) -> list[OperationalTask]:
    """R309: ارسال‌های در راه برای انباردار مقصد و رسیدهایی که سفارش منتظر دارند (هر کدام با کلید خودش)."""
    from peecha.db.models.inventory import Warehouse
    from peecha.services import cross_dock, stock_controls, transit_transfer

    on = stock_controls.enabled_codes(company_id)
    counts = []
    if stock_controls.TWO_STEP_TRANSFER in on:
        counts.append(("TRANSIT_ARRIVING", transit_transfer.arriving_by_warehouse(company_id), "{n} ارسال در راه به «{w}»"))
    if stock_controls.CROSS_DOCK in on:
        counts.append(("CROSS_DOCK", cross_dock.pending_by_warehouse(company_id), "{n} ردیف رسید در «{w}» سفارش منتظر دارد"))
    ids = {w for _k, c, _t in counts for w in c}
    if not ids:
        return []
    with new_session() as session:
        whs = {w.warehouse_id: w for w in session.scalars(select(Warehouse).where(Warehouse.warehouse_id.in_(ids)))}
    out = []
    for kind, by_wh, title in counts:
        for warehouse_id, n in sorted(by_wh.items()):
            w = whs.get(warehouse_id)
            if w is None or not (is_manager or w.manager_user_id == user_id):
                continue
            out.append(OperationalTask(kind, KIND_LABELS[kind], 0, "", title.format(n=n, w=w.name), w.name, None, ""))
    return out


# =====================================================================
# R302: سفارش‌هایی که خود کاربر صادر کرده و هنوز در جریان‌اند (فقط نمایش،
# برای «درخواست‌های در جریان من» کارتابل). مراحل از همان قاعده‌های
# تنظیمی خود سند خوانده می‌شود؛ هیچ وضعیتی تغییر نمی‌کند.
# =====================================================================
_ORDER_TYPES = ("SALES_ORDER", "PURCHASE_ORDER")


@dataclass
class OrderProgress:
    document_id: int
    document_type_code: str
    title: str
    counterparty_name: str
    document_date: datetime.date | None
    created_at: datetime.datetime | None
    path: list[tuple[str, str]]  # [(مرحله، done|current|pending)]
    current_step: str
    waiting_on: str


def _remaining_by_document(session, docs: list[CommercialDocument]) -> dict[int, tuple[bool, bool]]:
    """سند ← (هنوز چیزی برای فاکتور مانده؟، بخشی فاکتور شده؟) -- همان مبنای convert_to_invoice."""
    from sqlalchemy import func

    from peecha.db.models.commercial import CommercialDocumentLine as Line

    lines = session.execute(select(Line.document_id, Line.line_id, Line.quantity, Line.warehouse_delivered_quantity).where(
        Line.document_id.in_([d.document_id for d in docs]))).all()
    invoiced = dict(session.execute(
        select(Line.source_line_id, func.sum(Line.quantity))
        .join(CommercialDocument, CommercialDocument.document_id == Line.document_id)
        .where(Line.source_line_id.in_([ln.line_id for ln in lines] or [-1]), CommercialDocument.status_code != "CANCELLED")
        .group_by(Line.source_line_id)).all())
    out: dict[int, tuple[bool, bool]] = {}
    for doc_id, line_id, qty, delivered in lines:
        done = invoiced.get(line_id) or 0
        base = delivered if delivered is not None else qty
        left, partly = out.get(doc_id, (False, False))
        out[doc_id] = (left or base - done > 0, partly or done > 0)
    return out


def list_my_orders_in_progress(company_id: int, user_id: int, limit: int = 100) -> list[OrderProgress]:
    from peecha.db.models.inventory import Warehouse
    from peecha.db.models.security import User

    with new_session() as session:
        docs = list(session.scalars(select(CommercialDocument).where(
            CommercialDocument.company_id == company_id, CommercialDocument.created_by_user_id == user_id,
            CommercialDocument.document_type_code.in_(_ORDER_TYPES),
            CommercialDocument.status_code.in_(("CONFIRMED", "APPROVED", "POSTED")),
        ).order_by(CommercialDocument.document_id.desc()).limit(limit)))
        if not docs:
            return []
        remaining = _remaining_by_document(session, docs)
        pre_sales = {d.document_id for d in docs if documents_service._is_pre_sales_order(session, d)}
        names = dict(session.execute(select(DetailAccount.detail_account_id, DetailAccount.name).where(
            DetailAccount.detail_account_id.in_({d.counterparty_detail_account_id for d in docs}))).all())
        keepers = dict(session.execute(
            select(Warehouse.warehouse_id, User.full_name).join(User, User.user_id == Warehouse.manager_user_id)
            .where(Warehouse.warehouse_id.in_({d.warehouse_id for d in docs if d.warehouse_id} or {-1}))).all())

    rules = {t: (documents_service.requires_manager_approval(company_id, t),
                 documents_service.order_warehouse_step_enabled(company_id, t),
                 documents_service.receipt_eligible_statuses(company_id, t) == ("POSTED",)) for t in _ORDER_TYPES}
    out = []
    for d in docs:
        left, partly = remaining.get(d.document_id, (False, False))
        if not left:
            continue
        needs_approval, warehouse_step, post_first = rules[d.document_type_code]
        is_pre_sales = d.document_id in pre_sales
        word = warehouse_word(d.document_type_code)
        keeper = keepers.get(d.warehouse_id) or "انباردار"
        steps: list[tuple[str, bool, str]] = [("ثبت سفارش", True, "")]
        if needs_approval:
            steps.append(("تصویب مدیر", d.status_code in ("APPROVED", "POSTED"), "مدیر"))
        if warehouse_step and post_first and not is_pre_sales:
            steps.append(("ثبت نهایی", d.status_code == "POSTED", "مدیر"))
        if warehouse_step or is_pre_sales:
            steps.append(("تایید انبار و توزین" if is_pre_sales else f"{word} انبار", d.warehouse_approved_at is not None, keeper))
        steps.append(("تبدیل به فاکتور" + (" (بخشی انجام شده)" if partly else ""), False, "شما"))
        current = next(i for i, (_l, done, _w) in enumerate(steps) if not done)
        path = [(label, "done" if done else "current" if i == current else "pending") for i, (label, done, _w) in enumerate(steps)]
        out.append(OrderProgress(
            d.document_id, d.document_type_code, f"{_DOC_TYPE_TITLES[d.document_type_code]} {d.document_no}",
            names.get(d.counterparty_detail_account_id) or "", d.document_date, d.created_at, path,
            steps[current][0], steps[current][2]))
    return out
