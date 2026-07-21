"""سرویسِ ردِ حسابرسیِ تغییرناپذیر (audit.activity_log).

log_activity() باید با همان session/تراکنشِ عملیاتِ اصلی صدا زده شود
(نه new_session جدا) — اگر عملیاتِ اصلی rollback شود، رکوردِ حسابرسیِ
مربوط به آن هم نباید ثبت شود. خودِ جدول در دیتابیس با تریگر از هر
UPDATE/DELETE محافظت شده (006_audit_log.sql)، پس هرچه اینجا INSERT شود
برای همیشه ثابت می‌ماند."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from peecha.db.base import new_session
from peecha.db.models.audit import ActivityLog
from peecha.db.models.security import User


@dataclass
class ActivityLogRow:
    log_id: int
    company_id: int | None
    user_id: int | None
    user_full_name: str | None
    entity_type: str
    entity_id: int
    action: str
    changes: dict[str, Any]
    created_at: datetime.datetime


def log_activity(
    session: Session,
    *,
    company_id: int | None,
    user_id: int | None,
    entity_type: str,
    entity_id: int,
    action: str,
    changes: dict[str, Any] | None = None,
) -> None:
    session.add(
        ActivityLog(
            company_id=company_id,
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            changes=changes or {},
        )
    )


def list_entity_types() -> list[str]:
    with new_session() as session:
        return list(session.scalars(select(ActivityLog.entity_type).distinct().order_by(ActivityLog.entity_type)).all())


def list_activity_log(
    company_id: int | None = None,
    entity_type: str | None = None,
    limit: int = 500,
) -> list[ActivityLogRow]:
    with new_session() as session:
        query = select(ActivityLog).order_by(ActivityLog.created_at.desc(), ActivityLog.log_id.desc()).limit(limit)
        if company_id is not None:
            query = query.where(ActivityLog.company_id == company_id)
        if entity_type is not None:
            query = query.where(ActivityLog.entity_type == entity_type)
        rows = session.scalars(query).all()

        user_ids = {r.user_id for r in rows if r.user_id is not None}
        names: dict[int, str] = {}
        if user_ids:
            names = dict(session.execute(select(User.user_id, User.full_name).where(User.user_id.in_(user_ids))).all())

        return [
            ActivityLogRow(
                log_id=r.log_id,
                company_id=r.company_id,
                user_id=r.user_id,
                user_full_name=names.get(r.user_id) if r.user_id is not None else None,
                entity_type=r.entity_type,
                entity_id=r.entity_id,
                action=r.action,
                changes=r.changes or {},
                created_at=r.created_at,
            )
            for r in rows
        ]
