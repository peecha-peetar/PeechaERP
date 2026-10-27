"""R343: کارهای دوره‌ای اسناد روی همان زمان‌بند موجود (workflow.scheduler.register_tick، تیک دقیقه‌ای دسکتاپ):
یادآوری پیش و پس از انقضا (یک بار برای هر تاریخ انقضا)، منقضی‌کردن درخواست‌های عکس‌برداری، استخراج متن فایل‌ها
و پاک‌کردن فایل‌های یتیم."""

from __future__ import annotations

import datetime
import time

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert

from peecha.db.base import new_session
from peecha.db.models.documents import DmsDocument, DmsFile, DmsReminder, DmsVersionFile
from peecha.db.models.security import Notification, UserCompany
from peecha.services.dms import capture, storage
from peecha.services.dms import common as c

ORPHAN_AGE = datetime.timedelta(days=1)


def send_expiry_reminders(company_id: int | None, today: datetime.date | None = None) -> int:
    today = today or datetime.date.today()
    sent = 0
    with new_session() as session:
        companies = [company_id] if company_id else list(session.scalars(select(DmsDocument.company_id).distinct()))
        for cid in companies:
            days = c.settings(session, cid).expiry_reminder_days
            rows = session.scalars(select(DmsDocument).where(
                DmsDocument.company_id == cid, DmsDocument.is_deleted.is_(False), DmsDocument.expiry_date.isnot(None),
                DmsDocument.expiry_date <= today + datetime.timedelta(days=days),
                DmsDocument.status_code.notin_(("ARCHIVED", "OBSOLETE")))).all()
            for doc in rows:
                kind = "EXPIRED" if doc.expiry_date < today else "BEFORE_EXPIRY"
                users = sorted({u for u in (doc.responsible_user_id, doc.owner_user_id) if u})
                users = [u for u in users if session.scalar(select(UserCompany.user_id).where(
                    UserCompany.user_id == u, UserCompany.company_id == cid))]
                claimed = session.execute(insert(DmsReminder).values(
                    document_id=doc.document_id, reminder_kind=kind, expiry_date=doc.expiry_date, notified_user_ids=users,
                    result_code="SENT" if users else "NO_USER").on_conflict_do_nothing().returning(DmsReminder.reminder_id)).first()
                if claimed is None:
                    continue
                title = ("سند منقضی شده است" if kind == "EXPIRED" else "انقضای سند نزدیک است") + f": {doc.document_no}"
                body = f"{doc.title} — تاریخ انقضا {doc.expiry_date:%Y-%m-%d}"
                for user_id in users:
                    session.add(Notification(
                        company_id=cid, user_id=user_id, type_code="DMS_EXPIRY", title=title, body=body,
                        entity_type="DmsDocument", entity_id=doc.document_id))
                c.log(session, cid, doc.document_id, "REMINDER", None, note=title, details={"kind": kind, "users": users})
                sent += 1
        session.commit()
    return sent


def extract_pending_text(company_id: int | None, limit: int = 3, budget_seconds: float = 8.0) -> int:
    started, done = time.monotonic(), 0
    with new_session() as session:
        query = select(DmsFile.file_id).where(DmsFile.text_status == "PENDING").order_by(DmsFile.file_id).limit(limit)
        if company_id:
            query = query.where(DmsFile.company_id == company_id)
        ids = list(session.scalars(query))
    for file_id in ids:
        if time.monotonic() - started > budget_seconds:
            break
        with new_session() as session:
            row = session.scalar(select(DmsFile).where(DmsFile.file_id == file_id, DmsFile.text_status == "PENDING")
                                 .with_for_update(skip_locked=True))
            if row is None:
                continue
            cfg = c.settings(session, row.company_id)
            try:
                status_code, text_value = storage.extract_text(storage.read(session, row), row.extension, cfg.image_ocr)
            except FileNotFoundError:
                status_code, text_value = "FAILED", ""
            row.text_status, row.text_content = status_code, text_value or None
            session.commit()
            done += 1
    return done


def sweep_orphans(company_id: int | None = None, now: datetime.datetime | None = None) -> int:
    """فایل‌هایی که به هیچ نسخه‌ای نرسیده‌اند (تراکنش شکست‌خورده یا قطع ارتباط) پس از یک روز پاک می‌شوند؛ در حالت
    FS فایل‌های پوشهٔ اسناد که ردیفی در دیتابیس ندارند هم."""
    now = now or c.now()
    removed = 0
    with new_session() as session:
        query = select(DmsFile).where(DmsFile.created_at < now - ORPHAN_AGE, ~exists().where(DmsVersionFile.file_id == DmsFile.file_id))
        if company_id:
            query = query.where(DmsFile.company_id == company_id)
        for row in session.scalars(query).all():
            if row.storage_mode == "FS" and row.storage_key:
                try:
                    storage.discard([storage._resolve(storage.storage_root(c.settings(session, row.company_id)), row.storage_key)])
                except ValueError:
                    pass
            session.delete(row)
            removed += 1
        session.commit()
        companies = [company_id] if company_id else list(session.scalars(select(DmsFile.company_id).distinct()))
        for cid in companies:
            cfg = c.settings(session, cid)
            folder = storage.storage_root(cfg) / str(cid)
            if not folder.is_dir():
                continue
            known = set(session.scalars(select(DmsFile.storage_key).where(DmsFile.company_id == cid, DmsFile.storage_key.isnot(None))))
            for path in folder.rglob("*"):
                if not path.is_file():
                    continue
                key = path.relative_to(storage.storage_root(cfg)).as_posix()
                if key in known or now.timestamp() - path.stat().st_mtime < ORPHAN_AGE.total_seconds():
                    continue
                storage.discard([path])
                removed += 1
        session.commit()
    return removed


_last_daily: dict[int | None, datetime.date] = {}


def tick(company_id: int | None) -> int:
    count = capture.expire_due(company_id)
    count += extract_pending_text(company_id)
    if _last_daily.get(company_id) != datetime.date.today():
        _last_daily[company_id] = datetime.date.today()
        count += send_expiry_reminders(company_id)
        count += sweep_orphans(company_id)
    return count


def register() -> None:
    from peecha.services.workflow import scheduler

    scheduler.register_tick("dms", tick)
