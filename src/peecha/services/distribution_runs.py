"""تیمِ پخش -- طبقِ درخواستِ صریحِ کاربر (روالِ کاملِ پخشِ سرد): فاکتورهایِ
فروشِ ثبت‌نهایی‌شده‌یِ کانالِ «پخشِ سرد» که از گیتِ تاییدِ انبار/توزینِ
سفارشِ مبدا (commercial_documents.approve_warehouse/approve_weighing)
عبور کرده‌اند، اینجا به یک خودرو (inv.warehouses با
warehouse_type_code='VEHICLE' -- که از پیش پلاک/رانندهٔ خودش را دارد) +
تاریخِ مشخص الصاق می‌شوند. هر تیم یک «مانیفستِ» چاپ‌پذیر است: فهرستِ
فاکتورها + جمعِ هر کالا در همه‌یِ آن فاکتورها -- که به راننده تحویل داده
می‌شود."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import aliased

from peecha.db.base import new_session
from peecha.db.models.commercial import (
    Channel, CommercialDocument, CommercialDocumentLine, CustomerProfile, DistributionRun, DistributionRunDocument,
)
from peecha.db.models.inventory import Warehouse
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service


def list_order_visitors(company_id: int) -> list[tuple[int, str]]:
    """طبقِ درخواستِ صریح («ویزیتور هم به فیلترهایِ تیمِ پخش اضافه
    بشه»): هم‌الگو با field_sales_dashboard._visitor_names -- «ویزیتور»
    در این پروژه یعنی همان کاربری که سفارش را ثبت کرده (created_by_
    user_id)، نه فیلدِ کم‌استفاده‌یِ sales_rep_detail_account_id."""
    from peecha.services import users as users_service

    return sorted(
        ((u.user_id, u.full_name) for u in users_service.list_users() if company_id in u.company_ids),
        key=lambda item: item[1],
    )


@dataclass
class EligibleInvoiceRow:
    document_id: int
    document_no: int
    document_date: datetime.date
    counterparty_detail_account_id: int
    total_amount: decimal.Decimal
    settlement_type_code: str | None = None


def _route_and_descendant_ids(company_id: int, route_detail_account_id: int) -> set[int]:
    """طبقِ درخواستِ صریح («فیلترِ منطقه‌بندی و مسیر رویِ تیمِ پخش»):
    مسیرِ توزیع یک بُعدِ سلسله‌مراتبی است (منطقه > زیرمنطقه > مسیر) --
    انتخابِ یک گره باید همه‌یِ زیرگره‌هایش را هم شاملِ فیلتر کند."""
    dimension_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.DISTRIBUTION_ROUTE_CODE)
    all_rows = dimensions_service.list_detail_accounts(company_id, dimension_type_id)
    children_by_parent: dict[int | None, list[int]] = {}
    for r in all_rows:
        children_by_parent.setdefault(r.parent_detail_account_id, []).append(r.detail_account_id)
    result: set[int] = set()
    stack = [route_detail_account_id]
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.add(current)
        stack.extend(children_by_parent.get(current, []))
    return result


def list_eligible_invoices(
    company_id: int, customer_group_id: int | None = None, route_detail_account_id: int | None = None,
    visitor_user_id: int | None = None,
) -> list[EligibleInvoiceRow]:
    """فاکتورهایِ فروشِ ثبت‌نهایی‌شده‌یِ کانالِ پخشِ سرد که هنوز به هیچ
    تیمِ فعالی (DRAFT/CONFIRMED) الصاق نشده‌اند -- طبقِ درخواستِ صریح،
    قابلِ‌فیلتر بر اساسِ گروهِ مشتریان، مسیر/منطقه‌یِ توزیعِ مشتری
    (comm.customer_profiles)، و ویزیتوری که سفارشِ مبدا را ثبت کرده
    (از رویِ source_document_id، چون فاکتور را معمولاً شخصِ دیگری --
    انبار/دفتر -- می‌سازد، نه خودِ ویزیتور) تا بتوان فاکتورهایِ یک
    منطقه/ویزیتور را یک‌جا به یک خودرو تخصیص داد."""
    route_ids = _route_and_descendant_ids(company_id, route_detail_account_id) if route_detail_account_id is not None else None
    with new_session() as session:
        already_attached = set(
            session.scalars(
                select(DistributionRunDocument.document_id)
                .join(DistributionRun, DistributionRun.distribution_run_id == DistributionRunDocument.distribution_run_id)
                .where(DistributionRun.status_code != "CANCELLED")
            )
        )
        stmt = (
            select(CommercialDocument)
            .join(Channel, (Channel.channel_code == CommercialDocument.channel_code) & (Channel.company_id == CommercialDocument.company_id))
            .where(
                CommercialDocument.company_id == company_id, CommercialDocument.document_type_code == "SALES_INVOICE",
                CommercialDocument.status_code == "POSTED", Channel.channel_type_code == "PRE_SALES",
            )
        )
        if customer_group_id is not None or route_ids is not None:
            stmt = stmt.join(
                CustomerProfile, CustomerProfile.customer_detail_account_id == CommercialDocument.counterparty_detail_account_id,
            )
            if customer_group_id is not None:
                stmt = stmt.where(CustomerProfile.customer_group_id == customer_group_id)
            if route_ids is not None:
                stmt = stmt.where(CustomerProfile.distribution_route_detail_account_id.in_(route_ids))
        if visitor_user_id is not None:
            source_order = aliased(CommercialDocument)
            stmt = stmt.join(source_order, source_order.document_id == CommercialDocument.source_document_id)
            stmt = stmt.where(source_order.created_by_user_id == visitor_user_id)
        stmt = stmt.order_by(CommercialDocument.document_id)
        rows = session.scalars(stmt).all()
        return [
            EligibleInvoiceRow(
                d.document_id, d.document_no, d.document_date, d.counterparty_detail_account_id, d.total_amount,
                d.settlement_type_code,
            )
            for d in rows
            if d.document_id not in already_attached
        ]


@dataclass
class DistributionRunInvoiceRow:
    document_id: int
    document_no: int
    document_date: datetime.date
    counterparty_detail_account_id: int
    total_amount: decimal.Decimal
    settlement_type_code: str | None = None


@dataclass
class DistributionRunItemSummaryRow:
    item_id: int
    item_code: str
    item_name: str | None
    uom_code: str
    total_quantity: decimal.Decimal


@dataclass
class DistributionRunRow:
    distribution_run_id: int
    run_date: datetime.date
    vehicle_warehouse_id: int
    vehicle_warehouse_label: str
    status_code: str
    notes: str | None
    created_by_user_id: int
    confirmed_by_user_id: int | None
    confirmed_at: datetime.datetime | None
    invoices: list[DistributionRunInvoiceRow] = field(default_factory=list)
    item_summary: list[DistributionRunItemSummaryRow] = field(default_factory=list)


def _vehicle_label(warehouse: Warehouse) -> str:
    plate = f" — پلاک {warehouse.vehicle_plate_number}" if warehouse.vehicle_plate_number else ""
    return f"{warehouse.code} — {warehouse.name}{plate}"


def create_distribution_run(
    company_id: int, created_by_user_id: int, run_date: datetime.date, vehicle_warehouse_id: int,
    notes: str | None = None,
) -> int:
    with new_session() as session:
        vehicle_warehouse = session.get(Warehouse, vehicle_warehouse_id)
        if vehicle_warehouse is None or vehicle_warehouse.company_id != company_id:
            raise ValueError("انبار/خودروی انتخاب‌شده نامعتبر است.")
        if vehicle_warehouse.warehouse_type_code != "VEHICLE":
            raise ValueError("فقط انبارِ نوعِ «خودرو» می‌تواند تیمِ پخش داشته باشد.")
        run = DistributionRun(
            company_id=company_id, run_date=run_date, vehicle_warehouse_id=vehicle_warehouse_id,
            notes=notes or None, created_by_user_id=created_by_user_id,
        )
        session.add(run)
        session.commit()
        return run.distribution_run_id


def add_document_to_run(distribution_run_id: int, company_id: int, document_id: int) -> None:
    with new_session() as session:
        run = session.get(DistributionRun, distribution_run_id)
        if run is None or run.company_id != company_id:
            raise ValueError("تیمِ پخش نامعتبر است.")
        if run.status_code != "DRAFT":
            raise ValueError("فقط تیمِ پخشِ هنوز تاییدنشده قابلِ‌ویرایش است.")
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("فاکتور نامعتبر است.")
        if doc.document_type_code != "SALES_INVOICE" or doc.status_code != "POSTED":
            raise ValueError("فقط فاکتورِ فروشِ ثبت‌نهایی‌شده قابلِ‌الصاق است.")
        existing = session.scalar(
            select(DistributionRunDocument)
            .join(DistributionRun, DistributionRun.distribution_run_id == DistributionRunDocument.distribution_run_id)
            .where(DistributionRunDocument.document_id == document_id, DistributionRun.status_code != "CANCELLED")
        )
        if existing is not None:
            raise ValueError("این فاکتور قبلاً به یک تیمِ پخشِ فعال الصاق شده است.")
        session.add(DistributionRunDocument(distribution_run_id=distribution_run_id, document_id=document_id))
        session.commit()


def remove_document_from_run(distribution_run_id: int, company_id: int, document_id: int) -> None:
    with new_session() as session:
        run = session.get(DistributionRun, distribution_run_id)
        if run is None or run.company_id != company_id:
            raise ValueError("تیمِ پخش نامعتبر است.")
        if run.status_code != "DRAFT":
            raise ValueError("فقط تیمِ پخشِ هنوز تاییدنشده قابلِ‌ویرایش است.")
        link = session.get(DistributionRunDocument, (distribution_run_id, document_id))
        if link is None:
            raise ValueError("این فاکتور در این تیمِ پخش نیست.")
        session.delete(link)
        session.commit()


def get_distribution_run(distribution_run_id: int, company_id: int) -> DistributionRunRow:
    with new_session() as session:
        run = session.get(DistributionRun, distribution_run_id)
        if run is None or run.company_id != company_id:
            raise ValueError("تیمِ پخش نامعتبر است.")
        vehicle_warehouse = session.get(Warehouse, run.vehicle_warehouse_id)
        document_ids = list(
            session.scalars(
                select(DistributionRunDocument.document_id).where(DistributionRunDocument.distribution_run_id == distribution_run_id)
            )
        )
        invoices: list[DistributionRunInvoiceRow] = []
        if document_ids:
            docs = session.scalars(select(CommercialDocument).where(CommercialDocument.document_id.in_(document_ids))).all()
            invoices = [
                DistributionRunInvoiceRow(
                    d.document_id, d.document_no, d.document_date, d.counterparty_detail_account_id, d.total_amount,
                    d.settlement_type_code,
                )
                for d in sorted(docs, key=lambda d: d.document_id)
            ]

        item_totals: dict[int, decimal.Decimal] = {}
        if document_ids:
            lines = session.scalars(
                select(CommercialDocumentLine).where(CommercialDocumentLine.document_id.in_(document_ids))
            ).all()
            for line in lines:
                item_totals[line.item_id] = item_totals.get(line.item_id, decimal.Decimal(0)) + line.quantity

    items_by_id = {it.item_id: it for it in catalog_service.list_items(company_id)}
    item_summary = [
        DistributionRunItemSummaryRow(
            item_id=item_id, item_code=items_by_id[item_id].code if item_id in items_by_id else str(item_id),
            item_name=items_by_id[item_id].name if item_id in items_by_id else None,
            uom_code=items_by_id[item_id].base_uom_code if item_id in items_by_id else "",
            total_quantity=quantity,
        )
        for item_id, quantity in item_totals.items()
    ]
    item_summary.sort(key=lambda r: r.item_code)

    return DistributionRunRow(
        distribution_run_id=run.distribution_run_id, run_date=run.run_date, vehicle_warehouse_id=run.vehicle_warehouse_id,
        vehicle_warehouse_label=_vehicle_label(vehicle_warehouse) if vehicle_warehouse else str(run.vehicle_warehouse_id),
        status_code=run.status_code, notes=run.notes, created_by_user_id=run.created_by_user_id,
        confirmed_by_user_id=run.confirmed_by_user_id, confirmed_at=run.confirmed_at,
        invoices=invoices, item_summary=item_summary,
    )


def list_distribution_runs(
    company_id: int, status_code: str | None = None, date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> list[DistributionRunRow]:
    with new_session() as session:
        stmt = select(DistributionRun.distribution_run_id).where(DistributionRun.company_id == company_id)
        if status_code is not None:
            stmt = stmt.where(DistributionRun.status_code == status_code)
        if date_from is not None:
            stmt = stmt.where(DistributionRun.run_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(DistributionRun.run_date <= date_to)
        stmt = stmt.order_by(DistributionRun.run_date.desc(), DistributionRun.distribution_run_id.desc())
        ids = session.scalars(stmt).all()
    return [get_distribution_run(run_id, company_id) for run_id in ids]


def confirm_distribution_run(distribution_run_id: int, company_id: int, confirmed_by_user_id: int) -> None:
    with new_session() as session:
        run = session.get(DistributionRun, distribution_run_id)
        if run is None or run.company_id != company_id:
            raise ValueError("تیمِ پخش نامعتبر است.")
        if run.status_code != "DRAFT":
            raise ValueError("این تیمِ پخش قبلاً تایید/لغو شده است.")
        has_documents = session.scalar(
            select(DistributionRunDocument).where(DistributionRunDocument.distribution_run_id == distribution_run_id)
        )
        if has_documents is None:
            raise ValueError("حداقل یک فاکتور باید به این تیمِ پخش الصاق شده باشد.")
        run.status_code = "CONFIRMED"
        run.confirmed_by_user_id = confirmed_by_user_id
        run.confirmed_at = datetime.datetime.now()
        session.commit()


def cancel_distribution_run(distribution_run_id: int, company_id: int) -> None:
    with new_session() as session:
        run = session.get(DistributionRun, distribution_run_id)
        if run is None or run.company_id != company_id:
            raise ValueError("تیمِ پخش نامعتبر است.")
        if run.status_code != "DRAFT":
            raise ValueError("فقط تیمِ پخشِ هنوز تاییدنشده قابلِ‌لغو است.")
        run.status_code = "CANCELLED"
        session.commit()
