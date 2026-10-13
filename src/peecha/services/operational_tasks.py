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
    "GOODS_RECEIPT": "تایید انبار (رسید/حواله)",
    "PRE_SALES_WAREHOUSE": "تایید انبار سفارش",
    "SETTLEMENT_APPROVAL": "تایید نحوهٔ تسویه",
    "CONVERT_TO_INVOICE": "تبدیل به فاکتور",
    "POST_ORDER": "ثبت نهایی سفارش (پیش از رسید)",
    "INVENTORY_RESIDUAL": "اصلاح ماندهٔ ریالی موجودی صفر",
    "PUTAWAY_PENDING": "جانمایی رسیدهای انبار",
    "QC_PENDING": "کنترل کیفیت رسیدها",
    "EXPIRY_NEAR": "کالای نزدیک به انقضا",
    "EXPIRED_STOCK": "کالای منقضی در انبار",
    "TRANSIT_ARRIVING": "ارسال در راه به انبار",
    "CROSS_DOCK": "ارسال مستقیم از رسید",
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


def _putaway_pending(company_id: int, user_id: int, is_manager: bool) -> list[OperationalTask]:
    """R304 (کلید «رسیدهای جانمایی‌نشده در کارتابل انباردار»): یک کار برای هر انبار، برای انباردار همان انبار و مدیر."""
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
            f"{len(sources)} رسید با {lines} ردیف جانمایی‌نشده در «{w.name}»", w.name,
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
