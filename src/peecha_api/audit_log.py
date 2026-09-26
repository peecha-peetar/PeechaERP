"""ثبتِ ردِ حسابرسی برایِ اقداماتِ حساسِ APIِ موبایل -- رویِ همان
services/audit.py موجود. تفاوتِ APIِ هم‌زمان‌چندکاربره با فراخوان‌هایِ
دسکتاپ: هر سرویسِ ERP (documents_service.create_document و...) خودش
new_session/commit جداگانه دارد، پس این‌جا (برخلافِ فراخوان‌هایِ داخلیِ
سرویس‌ها) نمی‌توان همان تراکنشِ اصلی را به‌اشتراک گذاشت -- رکوردِ
حسابرسی در یک تراکنشِ کوتاهِ جداگانه، بلافاصله بعدِ موفقیتِ عملیاتِ
اصلی، درج می‌شود."""

from __future__ import annotations

from typing import Any

from peecha.db.base import new_session
from peecha.services import audit as audit_service


def record(company_id: int, user_id: int, entity_type: str, entity_id: int, action: str, changes: dict[str, Any] | None = None) -> None:
    with new_session() as session:
        audit_service.log_activity(
            session, company_id=company_id, user_id=user_id,
            entity_type=entity_type, entity_id=entity_id, action=action, changes=changes,
        )
        session.commit()
