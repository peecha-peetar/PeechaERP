"""نماهای ذخیره‌شدهٔ گزارش — R244: شخصی یا اشتراکی (در پایگاه‌داده، برای همهٔ کاربران شرکت).

payload همان دیکشنری نما (فیلترها، گزینه‌ها، مرتب‌سازی، گروه‌بندی، ستون‌های پنهان) به‌صورت JSON است."""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass

from sqlalchemy import or_, select

from peecha.db.base import new_session
from peecha.db.models.commercial import ReportView


@dataclass
class ViewRow:
    view_id: int
    name: str
    owner_user_id: int
    is_shared: bool
    payload: dict
    is_mine: bool


def list_views(company_id: int, report_key: str, user_id: int | None) -> list[ViewRow]:
    with new_session() as session:
        rows = session.scalars(select(ReportView).where(
            ReportView.company_id == company_id, ReportView.report_key == report_key,
            or_(ReportView.owner_user_id == user_id, ReportView.is_shared.is_(True)),
        ).order_by(ReportView.name)).all()
        out = []
        for r in rows:
            try:
                payload = json.loads(r.payload)
            except ValueError:
                payload = {}
            out.append(ViewRow(r.view_id, r.name, r.owner_user_id, r.is_shared, payload, r.owner_user_id == user_id))
        return out


def save_view(company_id: int, report_key: str, user_id: int, name: str, payload: dict, is_shared: bool = False) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("نام نما الزامی است.")
    with new_session() as session:
        row = session.scalar(select(ReportView).where(
            ReportView.company_id == company_id, ReportView.report_key == report_key, ReportView.owner_user_id == user_id,
            ReportView.name == name))
        if row is None:
            row = ReportView(company_id=company_id, report_key=report_key, owner_user_id=user_id, name=name)
            session.add(row)
        row.payload = json.dumps(payload, ensure_ascii=False)
        row.is_shared = is_shared
        row.updated_at = datetime.datetime.now()
        session.commit()
        return row.view_id


def delete_view(company_id: int, view_id: int, user_id: int) -> None:
    with new_session() as session:
        row = session.get(ReportView, view_id)
        if row is None or row.company_id != company_id:
            raise ValueError("نما نامعتبر است.")
        if row.owner_user_id != user_id:
            raise ValueError("فقط سازندهٔ نما می‌تواند آن را حذف کند.")
        session.delete(row)
        session.commit()
