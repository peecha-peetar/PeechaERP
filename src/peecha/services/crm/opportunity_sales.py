"""اتصال فرصت فروش به فروش واقعی ERP (فاز ۳، R282).

فرصت ← پیش‌فاکتور/سفارش فروش فقط با commercial_documents.create_document/add_line ساخته می‌شود (همان قیمت‌گذاری،
مالیات، اعتبار و گردش تایید). تبدیل به فاکتور، ثبت، تسویه و دریافت همچنان در فرم‌های فروش و خزانهٔ موجود انجام
می‌شود؛ اینجا فقط زنجیرهٔ اسناد خوانده و وضعیت فرصت هم‌گام می‌شود.
"""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import CommercialDocument, CustomerProfile
from peecha.db.models.core import Company
from peecha.db.models.crm import Opportunity, OpportunityDocument, OpportunityLine, PipelineStage
from peecha.db.models.inventory import Item, Warehouse
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services.crm import opportunities as opp_service

SALES_DOC_TYPES = ("SALES_PROFORMA", "SALES_ORDER", "SALES_INVOICE")
_WON_TRIGGERS = {"SALES_ORDER": ("CONFIRMED", "APPROVED", "CONVERTED", "POSTED"), "SALES_INVOICE": ("POSTED",)}


def _header(session, company_id: int, customer_id: int, warehouse_id: int | None, description: str):
    company = session.get(Company, company_id)
    prof = session.get(CustomerProfile, customer_id)
    if warehouse_id is None:
        warehouse_id = (prof.default_warehouse_id if prof else None) or session.scalar(
            select(Warehouse.warehouse_id).where(Warehouse.company_id == company_id, Warehouse.is_default.is_(True)).limit(1))
    return documents_service.DocumentHeaderFields(
        counterparty_detail_account_id=customer_id, currency_id=company.base_currency_id, warehouse_id=warehouse_id,
        channel_code=prof.default_channel_code if prof else None, price_list_id=prof.default_price_list_id if prof else None,
        sales_rep_detail_account_id=prof.default_sales_rep_detail_account_id if prof else None, description=description[:500])


def create_customer_document(company_id: int, user_id: int, customer_id: int, document_type_code: str = "SALES_ORDER",
                             warehouse_id: int | None = None, description: str = "") -> int:
    """سند پیش‌نویس فروش برای مشتری (اقدام سریع «سفارش» در پروندهٔ ۳۶۰)؛ ردیف‌ها در فرم فروش اضافه می‌شوند."""
    if document_type_code not in SALES_DOC_TYPES:
        raise ValueError("نوع سند فروش نامعتبر است.")
    with new_session() as session:
        header = _header(session, company_id, customer_id, warehouse_id, description or "ثبت از پروندهٔ مشتری")
    return documents_service.create_document(company_id, user_id, document_type_code, datetime.date.today(), header)


def create_sales_document(company_id: int, user_id: int, opportunity_id: int, document_type_code: str = "SALES_PROFORMA",
                          warehouse_id: int | None = None, document_date: datetime.date | None = None) -> int:
    """فرصت ← پیش‌فاکتور یا سفارش فروش با اقلام فرصت. ردیف بدون قیمت با قیمت‌گذاری خود ERP پر می‌شود.
    پیش‌فاکتور فرصت را به مرحلهٔ «ارسال پیشنهاد» می‌برد (اگر عقب‌تر باشد) و سفارش آن را «برنده» می‌کند."""
    if document_type_code not in ("SALES_PROFORMA", "SALES_ORDER"):
        raise ValueError("از فرصت فقط پیش‌فاکتور یا سفارش فروش ساخته می‌شود.")
    with new_session() as session:
        opp = session.get(Opportunity, opportunity_id)
        if opp is None or opp.company_id != company_id:
            raise ValueError("فرصت فروش نامعتبر است.")
        if not opp.customer_detail_account_id:
            raise ValueError("فرصت هنوز مشتری ندارد — ابتدا سرنخ را به مشتری تبدیل کنید.")
        if opp.status_code == "LOST":
            raise ValueError("از فرصت بازنده سند فروش ساخته نمی‌شود.")
        lines = list(session.scalars(select(OpportunityLine).where(OpportunityLine.opportunity_id == opportunity_id,
                                                                   OpportunityLine.item_id.is_not(None)).order_by(OpportunityLine.line_id)))
        if not lines:
            raise ValueError("فرصت اقلام کالایی ندارد — ابتدا «اقلام پیشنهادی» را ثبت کنید.")
        uoms = dict(session.execute(select(Item.item_id, Item.base_uom_id).where(Item.item_id.in_([ln.item_id for ln in lines]))).all())
        header = _header(session, company_id, opp.customer_detail_account_id, warehouse_id,
                         f"فرصت فروش {opp.opportunity_no}: {opp.title}")
        header.reference_no = f"CRM-{opp.opportunity_no}"
        line_data = [(ln.item_id, ln.quantity, ln.unit_price, ln.discount_amount, ln.description) for ln in lines]
    doc_id = documents_service.create_document(company_id, user_id, document_type_code, document_date or datetime.date.today(), header)
    for item_id, qty, price, discount, desc in line_data:
        documents_service.add_line(doc_id, company_id, item_id=item_id, uom_id=uoms[item_id], quantity=qty, quantity_base=qty,
                                   unit_price=price if price else None, discount_amount=discount or decimal.Decimal(0),
                                   description=desc)
    opp_service.link_document(company_id, user_id, opportunity_id, doc_id)
    _advance(company_id, user_id, opportunity_id, document_type_code)
    return doc_id


def _advance(company_id: int, user_id: int, opportunity_id: int, document_type_code: str) -> None:
    """پیشروی خودکار قیف؛ اگر فیلد الزامی مرحله کامل نباشد، فرصت در همان مرحله می‌ماند (سند ساخته شده است)."""
    with new_session() as session:
        opp = session.get(Opportunity, opportunity_id)
        current = session.get(PipelineStage, opp.stage_id)
        if opp.status_code != "OPEN":
            return
        target = None
        if document_type_code == "SALES_PROFORMA":
            target = session.scalar(select(PipelineStage).where(
                PipelineStage.pipeline_id == opp.pipeline_id, PipelineStage.code == "PROPOSAL",
                PipelineStage.sort_order > current.sort_order))
    try:
        if document_type_code == "SALES_ORDER":
            opp_service.mark_won(company_id, user_id, opportunity_id)
        elif target is not None:
            opp_service.move_stage(company_id, user_id, opportunity_id, target.stage_id)
    except ValueError:
        pass


def _descendants(session, root_ids: list[int]) -> list[CommercialDocument]:
    out, frontier, seen = [], list(root_ids), set()
    while frontier:
        docs = list(session.scalars(select(CommercialDocument).where(CommercialDocument.document_id.in_(frontier))))
        for d in docs:
            if d.document_id not in seen:
                seen.add(d.document_id)
                out.append(d)
        frontier = [i for i in session.scalars(select(CommercialDocument.document_id).where(
            CommercialDocument.source_document_id.in_([d.document_id for d in docs]))) if i not in seen]
    return out


def sales_chain(company_id: int, opportunity_id: int) -> list[dict]:
    """اسناد فروش فرصت و اسناد تبدیل‌شده از آن‌ها (پیش‌فاکتور ← سفارش ← فاکتور) با ماندهٔ تسویهٔ هر فاکتور."""
    with new_session() as session:
        opp = session.get(Opportunity, opportunity_id)
        if opp is None or opp.company_id != company_id:
            raise ValueError("فرصت فروش نامعتبر است.")
        roots = list(session.scalars(select(OpportunityDocument.document_id).where(OpportunityDocument.opportunity_id == opportunity_id)))
        docs = _descendants(session, roots)
    unsettled = {u.document_id: u for u in settlements_service.list_unsettled_invoices_bulk(
        company_id, counterparty_ids=list({d.counterparty_detail_account_id for d in docs}))} if docs else {}
    out = []
    for d in sorted(docs, key=lambda x: (x.document_date, x.document_id)):
        is_invoice = d.document_type_code == "SALES_INVOICE"
        remaining = unsettled[d.document_id].remaining_amount if d.document_id in unsettled else (
            decimal.Decimal(0) if is_invoice and d.status_code == "POSTED" else None)
        out.append({"document_id": d.document_id, "document_type_code": d.document_type_code,
                    "type_label": documents_service._DOC_TYPE_TITLES.get(d.document_type_code, d.document_type_code),
                    "document_no": d.document_no, "document_date": d.document_date, "status_code": d.status_code,
                    "total_amount": d.total_amount, "remaining_amount": remaining,
                    "paid": is_invoice and d.status_code == "POSTED" and remaining == 0, "source_document_id": d.source_document_id})
    return out


def sync_won_from_sales(company_id: int, user_id: int | None = None) -> list[int]:
    """فرصت‌های باز که سفارش تأییدشده یا فاکتور ثبت‌شده در زنجیره‌شان دارند «برنده» می‌شوند. برمی‌گرداند: شناسه‌ها."""
    with new_session() as session:
        pairs = session.execute(select(Opportunity.opportunity_id, OpportunityDocument.document_id).join(
            OpportunityDocument, OpportunityDocument.opportunity_id == Opportunity.opportunity_id).where(
            Opportunity.company_id == company_id, Opportunity.status_code == "OPEN")).all()
        roots: dict[int, list[int]] = {}
        for oid, did in pairs:
            roots.setdefault(oid, []).append(did)
        won = []
        for oid, ids in roots.items():
            if any(d.status_code in _WON_TRIGGERS.get(d.document_type_code, ()) for d in _descendants(session, ids)):
                won.append(oid)
    done = []
    for oid in won:
        try:
            opp_service.mark_won(company_id, user_id or _owner(oid), oid)
            done.append(oid)
        except ValueError:
            continue
    return done


def _owner(opportunity_id: int) -> int:
    with new_session() as session:
        opp = session.get(Opportunity, opportunity_id)
        return opp.owner_user_id or opp.created_by_user_id


def documents_for_customer_lookup(company_id: int, document_id: int) -> int | None:
    """شناسهٔ فرصت مرتبط با یک سند فروش (برای نمایش در فرم فروش یا گزارش‌ها)."""
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            return None
        chain = [doc]
        while chain[-1].source_document_id:
            parent = session.get(CommercialDocument, chain[-1].source_document_id)
            if parent is None:
                break
            chain.append(parent)
        return session.scalar(select(OpportunityDocument.opportunity_id).where(
            OpportunityDocument.document_id.in_([d.document_id for d in chain])).limit(1))

