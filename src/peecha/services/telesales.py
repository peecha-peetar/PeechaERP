"""فروشِ تلفنی -- طبقِ درخواستِ صریحِ کاربر: پخشِ سرد از ۳ مسیر سفارش
می‌گیرد (عمده/دسکتاپ، موبایل، تلفنی)؛ این ماژول همان چیزی را که فازِ
میدانی (field_sales.py، R129) برایِ «کدام مشتری مالِ کدام ویزیتور
است» می‌سازد -- برنامهٔ مراجعه (VisitPlan.assigned_visitor_user_id) --
دوباره برایِ ویزیتورِ تلفنی استفاده می‌کند، بدونِ ساختِ جدولِ تخصیصِ
جداگانه: تفاوتِ «ویزیتورِ مقیم» و «ویزیتورِ تلفنی» فقط در نحوهٔ کارشان
است، نه در ساختارِ دیتا."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import CustomerSalesNote
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import field_sales as field_sales_service


@dataclass
class AssignedCustomerRow:
    customer_detail_account_id: int
    code: str
    name: str


def list_assigned_customers(company_id: int, visitor_user_id: int) -> list[AssignedCustomerRow]:
    """فهرستِ یکتایِ مشتریانِ این ویزیتور -- بدونِ توجه به روزِ هفته، چون
    ویزیتورِ تلفنی معمولاً کلِ فهرستِ خودش را زنگ می‌زند، نه فقط برنامهٔ
    امروز (برخلافِ تبِ «ویزیت‌ها»یِ ویزیتورِ میدانی)."""
    plans = field_sales_service.list_visit_plans(company_id, visitor_user_id=visitor_user_id, active_only=True)
    customers_by_id = {c["detail_account_id"]: c for c in dimensions_service.list_customers(company_id)}
    seen: set[int] = set()
    rows: list[AssignedCustomerRow] = []
    for plan in plans:
        if plan.customer_detail_account_id in seen:
            continue
        seen.add(plan.customer_detail_account_id)
        customer = customers_by_id.get(plan.customer_detail_account_id)
        if customer is None:
            continue
        rows.append(AssignedCustomerRow(plan.customer_detail_account_id, customer["code"], customer["name"] or ""))
    rows.sort(key=lambda r: r.code)
    return rows


@dataclass
class CustomerNoteRow:
    note_id: int
    created_by_user_id: int
    note_text: str
    created_at: datetime.datetime


def add_customer_note(company_id: int, customer_detail_account_id: int, created_by_user_id: int, note_text: str) -> int:
    note_text = note_text.strip()
    if not note_text:
        raise ValueError("متنِ یادداشت نمی‌تواند خالی باشد.")
    with new_session() as session:
        row = CustomerSalesNote(
            company_id=company_id, customer_detail_account_id=customer_detail_account_id,
            created_by_user_id=created_by_user_id, note_text=note_text,
        )
        session.add(row)
        session.commit()
        return row.note_id


def list_customer_notes(company_id: int, customer_detail_account_id: int, limit: int = 20) -> list[CustomerNoteRow]:
    with new_session() as session:
        rows = session.scalars(
            select(CustomerSalesNote)
            .where(
                CustomerSalesNote.company_id == company_id,
                CustomerSalesNote.customer_detail_account_id == customer_detail_account_id,
            )
            .order_by(CustomerSalesNote.created_at.desc())
            .limit(limit)
        ).all()
        return [CustomerNoteRow(r.note_id, r.created_by_user_id, r.note_text, r.created_at) for r in rows]


def get_latest_customer_note(company_id: int, customer_detail_account_id: int) -> CustomerNoteRow | None:
    notes = list_customer_notes(company_id, customer_detail_account_id, limit=1)
    return notes[0] if notes else None
