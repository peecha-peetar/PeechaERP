"""کمک‌های مشترک Adapterها (فقط خواندن و قالب‌بندی)."""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import select

from peecha import numerals
from peecha.db.models.security import User
from peecha.services.workflow.common import display

ZERO = decimal.Decimal(0)


def money(value) -> str:
    return display(decimal.Decimal(value or 0))


def jdate(value) -> str:
    return numerals.format_jalali_date(value) if value else "—"


def detail_name(session, detail_account_id: int | None) -> str:
    from peecha.db.models.accounting import DetailAccount

    if not detail_account_id:
        return ""
    row = session.get(DetailAccount, detail_account_id)
    return row.name if row else ""


def user_name(session, user_id: int | None) -> str:
    if not user_id:
        return ""
    row = session.get(User, user_id)
    return (row.full_name or row.username) if row else ""


def days_between(a: datetime.date | None, b: datetime.date | None) -> int | None:
    return (b - a).days if a and b else None


def status_events(entity_label: str, statuses: dict[str, str]) -> dict[str, str]:
    """{وضعیت: برچسب} ← {نوع رویداد: برچسب فارسی} برای سازندهٔ فرایند."""
    return {code: f"{label} «{entity_label}»" for code, label in statuses.items()}


def item_code_name(session, item_id: int | None) -> tuple[str, str]:
    """کد و نام کالا (از حساب تفصیلی کالا)."""
    from peecha.db.models.accounting import DetailAccount
    from peecha.db.models.inventory import Item

    if not item_id:
        return "", ""
    row = session.execute(select(DetailAccount.code, DetailAccount.name).join(
        Item, Item.item_detail_account_id == DetailAccount.detail_account_id).where(Item.item_id == item_id)).first()
    return (row[0], row[1]) if row else ("", "")
