"""پخشِ سرد/گرم -- R129، بخشِ تاییدِ تحویل (Proof of Delivery). طبقِ
سندِ کاربر: امضا/عکس/GPS/ساعت/مقدارِ واقعیِ تحویلی رویِ یک فاکتورِ
فروشِ ثبت‌شده -- بدونِ اینکه چیزی از خودِ سندِ بازرگانی/مالی تغییر کند؛
این فقط یک لایهٔ اثباتِ جداگانه رویِ همان سندِ موجود است. کسری/مغایرت
(delivered_quantity < مقدارِ فاکتورشده) این‌جا فقط ثبت می‌شود، نه
اصلاحِ خودکارِ فاکتور -- اصلاحِ واقعی از طریقِ همان مکانیزمِ برگشت‌ازفروش/
اصلاحِ فاکتورِ موجود انجام می‌شود."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import DeliveryConfirmation, DeliveryConfirmationLine
from peecha.services import commercial_documents as documents_service


@dataclass
class DeliveryLineFields:
    document_line_id: int
    delivered_quantity: decimal.Decimal
    shortage_reason: str | None = None


@dataclass
class DeliveryConfirmationLineRow:
    delivery_confirmation_line_id: int
    document_line_id: int
    delivered_quantity: decimal.Decimal
    shortage_reason: str | None


@dataclass
class DeliveryConfirmationRow:
    delivery_confirmation_id: int
    document_id: int
    customer_visit_id: int | None
    confirmed_at: datetime.datetime
    confirmed_by_user_id: int
    received_by_name: str | None
    signature_storage_key: str | None
    photo_storage_key: str | None
    gps_latitude: decimal.Decimal | None
    gps_longitude: decimal.Decimal | None
    notes: str | None
    lines: list[DeliveryConfirmationLineRow]


def create_delivery_confirmation(
    company_id: int, document_id: int, confirmed_by_user_id: int, lines: list[DeliveryLineFields],
    customer_visit_id: int | None = None, received_by_name: str | None = None,
    signature_storage_key: str | None = None, photo_storage_key: str | None = None,
    gps_latitude: decimal.Decimal | None = None, gps_longitude: decimal.Decimal | None = None,
    notes: str | None = None,
) -> int:
    doc, doc_lines = documents_service.get_document(document_id, company_id)
    valid_line_ids = {line.line_id for line in doc_lines}
    if not lines:
        raise ValueError("حداقل یک ردیفِ تحویل لازم است.")
    for line_fields in lines:
        if line_fields.document_line_id not in valid_line_ids:
            raise ValueError("ردیفِ سند نامعتبر است.")
        if line_fields.delivered_quantity < 0:
            raise ValueError("مقدارِ تحویلی نمی‌تواند منفی باشد.")
    with new_session() as session:
        existing = session.scalar(select(DeliveryConfirmation).where(DeliveryConfirmation.document_id == document_id))
        if existing is not None:
            raise ValueError("این سند قبلاً تاییدِ تحویل دارد.")
        confirmation = DeliveryConfirmation(
            company_id=company_id, document_id=document_id, customer_visit_id=customer_visit_id,
            confirmed_by_user_id=confirmed_by_user_id, received_by_name=received_by_name or None,
            signature_storage_key=signature_storage_key or None, photo_storage_key=photo_storage_key or None,
            gps_latitude=gps_latitude, gps_longitude=gps_longitude, notes=notes or None,
        )
        session.add(confirmation)
        session.flush()
        for line_fields in lines:
            session.add(
                DeliveryConfirmationLine(
                    delivery_confirmation_id=confirmation.delivery_confirmation_id,
                    document_line_id=line_fields.document_line_id, delivered_quantity=line_fields.delivered_quantity,
                    shortage_reason=line_fields.shortage_reason or None,
                )
            )
        session.commit()
        return confirmation.delivery_confirmation_id


def get_delivery_confirmation_for_document(document_id: int, company_id: int) -> DeliveryConfirmationRow | None:
    with new_session() as session:
        confirmation = session.scalar(
            select(DeliveryConfirmation).where(
                DeliveryConfirmation.document_id == document_id, DeliveryConfirmation.company_id == company_id
            )
        )
        if confirmation is None:
            return None
        line_rows = session.scalars(
            select(DeliveryConfirmationLine).where(
                DeliveryConfirmationLine.delivery_confirmation_id == confirmation.delivery_confirmation_id
            )
        ).all()
        return DeliveryConfirmationRow(
            confirmation.delivery_confirmation_id, confirmation.document_id, confirmation.customer_visit_id,
            confirmation.confirmed_at, confirmation.confirmed_by_user_id, confirmation.received_by_name,
            confirmation.signature_storage_key, confirmation.photo_storage_key, confirmation.gps_latitude,
            confirmation.gps_longitude, confirmation.notes,
            [
                DeliveryConfirmationLineRow(r.delivery_confirmation_line_id, r.document_line_id, r.delivered_quantity, r.shortage_reason)
                for r in line_rows
            ],
        )
