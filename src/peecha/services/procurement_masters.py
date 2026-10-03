"""اطلاعاتِ پایهٔ تدارکات -- R240: انواعِ خرید، علت‌هایِ لغو، سیاستِ سفارشِ کالا.

جدول‌ها: comm.purchase_types، comm.cancellation_reasons (migration 177) و
inv.reorder_policies (از قبل موجود، تا کنون بدونِ فرمِ ورود)."""

from __future__ import annotations

import decimal
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import CancellationReason, CommercialDocument, PurchaseType
from peecha.db.models.inventory import ReorderPolicy

_DEFAULT_PURCHASE_TYPES = (("PLANNED", "برنامه‌ریزی‌شده", False), ("EMERGENCY", "اضطراری", True))
_DEFAULT_CANCEL_REASONS = (
    ("SUPPLIER", "انصرافِ تامین‌کننده"), ("PRICE", "قیمتِ نامناسب"), ("NO_NEED", "رفعِ نیاز"),
    ("DUPLICATE", "سندِ تکراری"), ("ERROR", "خطایِ ثبت"), ("OTHER", "سایر"),
)


# --- انواعِ خرید ------------------------------------------------------------
def list_purchase_types(company_id: int, active_only: bool = False) -> list[PurchaseType]:
    with new_session() as session:
        rows = list(session.scalars(select(PurchaseType).where(PurchaseType.company_id == company_id).order_by(PurchaseType.code)))
        if not rows:
            for code, name, emergency in _DEFAULT_PURCHASE_TYPES:
                session.add(PurchaseType(company_id=company_id, code=code, name=name, is_emergency=emergency, is_active=True))
            session.commit()
            rows = list(session.scalars(select(PurchaseType).where(PurchaseType.company_id == company_id).order_by(PurchaseType.code)))
    return [r for r in rows if r.is_active or not active_only]


def save_purchase_type(company_id: int, code: str, name: str, is_emergency: bool = False, is_active: bool = True,
                       purchase_type_id: int | None = None) -> int:
    code, name = (code or "").strip().upper(), (name or "").strip()
    if not code or not name:
        raise ValueError("کد و نامِ نوعِ خرید الزامی است.")
    with new_session() as session:
        clash = session.scalar(select(PurchaseType).where(PurchaseType.company_id == company_id, PurchaseType.code == code))
        if clash is not None and clash.purchase_type_id != purchase_type_id:
            raise ValueError("این کد قبلاً تعریف شده است.")
        row = session.get(PurchaseType, purchase_type_id) if purchase_type_id else PurchaseType(company_id=company_id)
        if row is None or row.company_id != company_id:
            raise ValueError("نوعِ خرید نامعتبر است.")
        row.code, row.name, row.is_emergency, row.is_active = code, name, is_emergency, is_active
        session.add(row)
        session.commit()
        return row.purchase_type_id


# --- علت‌هایِ لغو -----------------------------------------------------------
def list_cancellation_reasons(company_id: int, active_only: bool = False) -> list[CancellationReason]:
    with new_session() as session:
        rows = list(session.scalars(
            select(CancellationReason).where(CancellationReason.company_id == company_id).order_by(CancellationReason.code)))
        if not rows:
            for code, name in _DEFAULT_CANCEL_REASONS:
                session.add(CancellationReason(company_id=company_id, code=code, name=name, is_active=True))
            session.commit()
            rows = list(session.scalars(
                select(CancellationReason).where(CancellationReason.company_id == company_id).order_by(CancellationReason.code)))
    return [r for r in rows if r.is_active or not active_only]


def save_cancellation_reason(company_id: int, code: str, name: str, is_active: bool = True, reason_id: int | None = None) -> int:
    code, name = (code or "").strip().upper(), (name or "").strip()
    if not code or not name:
        raise ValueError("کد و عنوانِ علت الزامی است.")
    with new_session() as session:
        clash = session.scalar(select(CancellationReason).where(
            CancellationReason.company_id == company_id, CancellationReason.code == code))
        if clash is not None and clash.reason_id != reason_id:
            raise ValueError("این کد قبلاً تعریف شده است.")
        row = session.get(CancellationReason, reason_id) if reason_id else CancellationReason(company_id=company_id)
        if row is None or row.company_id != company_id:
            raise ValueError("علتِ لغو نامعتبر است.")
        row.code, row.name, row.is_active = code, name, is_active
        session.add(row)
        session.commit()
        return row.reason_id


def usage_count(column, value_id: int) -> int:
    with new_session() as session:
        return len(session.scalars(select(CommercialDocument.document_id).where(column == value_id)).all())


# --- سیاستِ سفارشِ کالا (inv.reorder_policies) ------------------------------
@dataclass
class PolicyFields:
    item_id: int
    warehouse_id: int | None = None
    min_qty: decimal.Decimal | None = None
    max_qty: decimal.Decimal | None = None
    reorder_point_qty: decimal.Decimal | None = None
    reorder_qty: decimal.Decimal | None = None
    lead_time_days: int | None = None
    is_active: bool = True


def list_reorder_policies(company_id: int) -> list[ReorderPolicy]:
    with new_session() as session:
        return list(session.scalars(select(ReorderPolicy).where(ReorderPolicy.company_id == company_id)
                                    .order_by(ReorderPolicy.item_id, ReorderPolicy.warehouse_id)))


def save_reorder_policy(company_id: int, fields: PolicyFields, policy_id: int | None = None) -> int:
    for value in (fields.min_qty, fields.max_qty, fields.reorder_point_qty, fields.reorder_qty):
        if value is not None and value < 0:
            raise ValueError("مقادیرِ سیاستِ سفارش نمی‌توانند منفی باشند.")
    if fields.min_qty is not None and fields.reorder_point_qty is not None and fields.reorder_point_qty < fields.min_qty:
        raise ValueError("نقطهٔ سفارش نباید کمتر از حداقلِ موجودی باشد.")
    if fields.max_qty is not None and fields.reorder_point_qty is not None and fields.max_qty <= fields.reorder_point_qty:
        raise ValueError("حداکثرِ موجودی باید بیشتر از نقطهٔ سفارش باشد.")
    with new_session() as session:
        clash = session.scalar(select(ReorderPolicy).where(
            ReorderPolicy.company_id == company_id, ReorderPolicy.item_id == fields.item_id,
            ReorderPolicy.warehouse_id.is_(None) if fields.warehouse_id is None else ReorderPolicy.warehouse_id == fields.warehouse_id))
        if clash is not None and clash.policy_id != policy_id:
            raise ValueError("برایِ این کالا در این انبار قبلاً سیاستِ سفارش تعریف شده است.")
        row = session.get(ReorderPolicy, policy_id) if policy_id else ReorderPolicy(company_id=company_id)
        if row is None or row.company_id != company_id:
            raise ValueError("سیاستِ سفارش نامعتبر است.")
        for name in ("item_id", "warehouse_id", "min_qty", "max_qty", "reorder_point_qty", "reorder_qty", "lead_time_days", "is_active"):
            setattr(row, name, getattr(fields, name))
        session.add(row)
        session.commit()
        return row.policy_id


def delete_reorder_policy(company_id: int, policy_id: int) -> None:
    with new_session() as session:
        row = session.get(ReorderPolicy, policy_id)
        if row is None or row.company_id != company_id:
            raise ValueError("سیاستِ سفارش نامعتبر است.")
        session.delete(row)
        session.commit()
