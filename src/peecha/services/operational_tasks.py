"""کارهایِ عملیاتیِ در انتظارِ کاربر -- R226.

کارتابلِ گردشِ کار (services/cartable.py) فقط آیتم‌هایِ ثبت‌شده در موتورِ
گردشِ کار را دارد؛ مراحلِ اسنادِ بازرگانی (تصویبِ مدیر، رسیدِ کالا، تاییدِ
نحوهٔ تسویه، تبدیلِ سفارشِ رسیده به فاکتور) هیچ‌وقت آن‌جا نمی‌رسیدند. این
سرویس همان صف‌هایِ موجود را (بدونِ منطقِ تازه) برایِ همین کاربر جمع می‌کند.
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
    "SALES_ORDER": "سفارشِ فروش", "SALES_PROFORMA": "پیش‌فاکتورِ فروش", "SALES_INVOICE": "فاکتورِ فروش",
    "SALES_RETURN": "برگشت از فروش", "PURCHASE_ORDER": "سفارشِ خرید", "PURCHASE_PROFORMA": "پیش‌فاکتورِ خرید",
    "PURCHASE_INVOICE": "فاکتورِ خرید", "PURCHASE_RETURN": "برگشت به تامین‌کننده",
    "CONSIGNMENT_IN": "امانیِ ورودی", "CONSIGNMENT_OUT": "امانیِ خروجی",
}

# نوعِ کار -> برچسب
KIND_LABELS = {
    "MANAGER_APPROVAL": "تصویبِ مدیر",
    "GOODS_RECEIPT": "تاییدِ رسیدِ کالا",
    "PRE_SALES_WAREHOUSE": "تاییدِ انبارِ سفارش",
    "SETTLEMENT_APPROVAL": "تاییدِ نحوهٔ تسویه",
    "CONVERT_TO_INVOICE": "تبدیل به فاکتور",
    "POST_ORDER": "ثبتِ نهاییِ سفارش (پیش از رسید)",
    "INVENTORY_RESIDUAL": "اصلاحِ ماندهٔ ریالیِ موجودیِ صفر",
}


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
            kind, KIND_LABELS[kind], d.document_id, d.document_type_code,
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
            approval_types = []
            if not settings_service.is_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_APPROVAL"):
                approval_types.append("PURCHASE_ORDER")
            if not settings_service.is_feature_enabled(company_id, "PURCHASE_INVOICE_SKIP_APPROVAL"):
                approval_types += ["PURCHASE_INVOICE", "PURCHASE_PROFORMA"]
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

    # R230: سفارشِ خریدی که تا ثبتِ نهایی نشود به تاییدِ رسید نمی‌رسد
    if is_manager and settings_service.is_feature_enabled(company_id, "PURCHASE_ORDER_GOODS_RECEIPT") \
            and not settings_service.is_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_POST"):
        skip_approval = settings_service.is_feature_enabled(company_id, "PURCHASE_ORDER_SKIP_APPROVAL")
        with new_session() as session:
            to_post = list(session.scalars(
                select(CommercialDocument).where(
                    CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "PURCHASE_ORDER",
                    CommercialDocument.status_code.in_(("CONFIRMED", "APPROVED") if skip_approval else ("APPROVED",)),
                ).order_by(CommercialDocument.document_id)
            ))
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

    # سفارشِ خریدِ رسیده که هنوز فاکتور نشده: برایِ ثبت‌کنندهٔ سفارش و مدیر
    received = [
        d for d in documents_service.list_purchase_order_goods_receipt_queue(company_id)
        if d.warehouse_approved_at is not None and (is_manager or d.created_by_user_id == user_id)
    ]
    tasks += _rows(company_id, received, "CONVERT_TO_INVOICE")

    if is_manager:
        from peecha.services import inventory_residual as residual_service

        try:
            residuals = residual_service.list_residuals(company_id)
        except Exception:  # noqa: BLE001 -- هشدارِ اختیاری نباید کارتابل را از کار بیندازد
            residuals = []
        if residuals:
            tasks.append(OperationalTask(
                "INVENTORY_RESIDUAL", KIND_LABELS["INVENTORY_RESIDUAL"], 0, "",
                f"{len(residuals)} کالا با موجودیِ صفر و ماندهٔ ریالی -- پیشنهادِ سندِ تسعیر", "", None, "",
            ))
    return tasks
