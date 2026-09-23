"""اعلان‌هایِ Field Sales (Phase 1) -- مفهومی که تا این نسخه اصلاً در ERP
وجود نداشت (نه دسکتاپ، نه API). عمداً از موتورِ کارتابل/گردشِ‌کارِ موجود
(services/cartable.py) جدا نگه داشته شده: کارتابل برایِ «تاییدِ
چندمرحله‌ایِ یک سند» است، اعلان برایِ «خبررسانیِ ساده به یک/چند کاربر»
-- دو نیازِ متفاوت که یکی جایگزینِ دیگری نیست."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.security import Notification, UserCompany
from peecha.services import roles as roles_service


@dataclass
class NotificationRow:
    notification_id: int
    type_code: str
    title: str
    body: str | None
    entity_type: str | None
    entity_id: int | None
    is_read: bool
    created_at: "object"


def create_notification(
    company_id: int, user_id: int, type_code: str, title: str, body: str = "",
    entity_type: str | None = None, entity_id: int | None = None,
) -> int:
    with new_session() as session:
        row = Notification(
            company_id=company_id, user_id=user_id, type_code=type_code, title=title, body=body or None,
            entity_type=entity_type, entity_id=entity_id,
        )
        session.add(row)
        session.commit()
        return row.notification_id


def notify_managers(
    company_id: int, type_code: str, title: str, body: str = "",
    entity_type: str | None = None, entity_id: int | None = None,
) -> list[int]:
    """طبقِ همان تعریفِ roles_service.is_manager -- به همه‌یِ کاربرانِ
    این شرکت که مدیر محسوب می‌شوند (نقشِ مدیریتی یا is_super_admin)."""
    with new_session() as session:
        user_ids = session.scalars(
            select(UserCompany.user_id).where(UserCompany.company_id == company_id)
        ).all()
    manager_ids = [uid for uid in user_ids if roles_service.is_manager(uid, company_id)]
    return [
        create_notification(company_id, uid, type_code, title, body, entity_type, entity_id)
        for uid in manager_ids
    ]


def list_notifications(user_id: int, company_id: int, unread_only: bool = False) -> list[NotificationRow]:
    with new_session() as session:
        query = select(Notification).where(Notification.user_id == user_id, Notification.company_id == company_id)
        if unread_only:
            query = query.where(Notification.is_read.is_(False))
        rows = session.scalars(query.order_by(Notification.created_at.desc())).all()
        return [
            NotificationRow(
                notification_id=r.notification_id, type_code=r.type_code, title=r.title, body=r.body,
                entity_type=r.entity_type, entity_id=r.entity_id, is_read=r.is_read, created_at=r.created_at,
            )
            for r in rows
        ]


def mark_read(notification_id: int, user_id: int) -> None:
    with new_session() as session:
        row = session.get(Notification, notification_id)
        if row is None or row.user_id != user_id:
            raise ValueError("اعلان نامعتبر است.")
        row.is_read = True
        session.commit()
