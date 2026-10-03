"""فهرست/خواندنِ اعلان‌هایِ خودِ کاربر -- رویِ services/notifications.py
(Phase 1، تازه). هر کاربر فقط اعلان‌هایِ خودش را می‌بیند/می‌تواند
بخواند -- کنترلِ دسترسی در خودِ سرویس (user_id match) انجام می‌شود."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from peecha.services import notifications as notifications_service
from peecha_api.deps import AuthContext, get_current_context

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(unread_only: bool = False, ctx: AuthContext = Depends(get_current_context)) -> list[dict]:
    rows = notifications_service.list_notifications(ctx.user_id, ctx.company_id, unread_only=unread_only)
    return [
        {
            "notification_id": r.notification_id, "type_code": r.type_code, "title": r.title, "body": r.body,
            "entity_type": r.entity_type, "entity_id": r.entity_id, "is_read": r.is_read,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, ctx: AuthContext = Depends(get_current_context)) -> dict:
    try:
        notifications_service.mark_read(notification_id, ctx.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"notification_id": notification_id, "is_read": True}
