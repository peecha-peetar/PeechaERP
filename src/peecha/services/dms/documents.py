"""R343: سند، نسخه، پیوند به رکورد ERP، گردش کار تایید، جست‌وجو و دریافت فایل.

همهٔ تابع‌ها (شرکت، کاربر) می‌گیرند و دسترسی را خودشان می‌سنجند (common.can_view / require)؛ شناسهٔ سند یا فایل
شرکت دیگر یا بدون اجازه همان پیام «پیدا نشد» را می‌گیرد تا وجود آن هم فاش نشود."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from types import SimpleNamespace

from sqlalchemy import and_, exists, func, or_, select, text

from peecha.db.base import new_session
from peecha.db.models.documents import (
    DmsCategory, DmsDocument, DmsDocumentTag, DmsEvent, DmsFile, DmsLink, DmsTag, DmsVersion, DmsVersionFile,
)
from peecha.db.models.security import User, UserCompany
from peecha.services.dms import common as c
from peecha.services.dms import entities, storage

MAX_PAGE_SIZE = 200


@dataclass
class DocumentFields:
    title: str
    document_type_code: str = "OTHER"
    category_id: int | None = None
    confidentiality_code: str = "INTERNAL"
    responsible_user_id: int | None = None
    branch_id: int | None = None
    issue_date: datetime.date | None = None
    valid_from: datetime.date | None = None
    expiry_date: datetime.date | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)


# --- اعتبارسنجی ---------------------------------------------------------------------------------
def _validate(session, company_id: int, f: DocumentFields) -> None:
    f.title = (f.title or "").strip()
    if not f.title:
        raise ValueError("عنوان سند را وارد کنید.")
    if len(f.title) > 300:
        raise ValueError("عنوان سند بیش از ۳۰۰ نویسه است.")
    if f.document_type_code not in c.DOCUMENT_TYPES:
        raise ValueError("نوع سند معتبر نیست.")
    if f.confidentiality_code not in c.CONFIDENTIALITY:
        raise ValueError("سطح محرمانگی معتبر نیست.")
    if f.category_id is not None:
        category = session.get(DmsCategory, f.category_id)
        if category is None or category.company_id != company_id or not category.is_active:
            raise ValueError("دسته‌بندی سند معتبر نیست.")
    if f.branch_id is not None:
        found = session.execute(text("SELECT 1 FROM comm.branches WHERE branch_id = :b AND company_id = :c"),
                                {"b": f.branch_id, "c": company_id}).first()
        if found is None:
            raise ValueError("شعبه متعلق به همین شرکت نیست.")
    if f.responsible_user_id is not None:
        member = session.scalar(select(UserCompany.user_id).where(
            UserCompany.user_id == f.responsible_user_id, UserCompany.company_id == company_id))
        if member is None:
            raise ValueError("مسئول پیگیری باید از کاربران همین شرکت باشد.")
    if f.valid_from and f.expiry_date and f.expiry_date < f.valid_from:
        raise ValueError("تاریخ انقضا پیش از تاریخ اعتبار است.")
    if f.issue_date and f.expiry_date and f.expiry_date < f.issue_date:
        raise ValueError("تاریخ انقضا پیش از تاریخ صدور است.")


def _next_no(session, company_id: int) -> str:
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext('doc.documents.no'), :c)"), {"c": company_id})
    count = session.scalar(select(func.count()).select_from(DmsDocument).where(DmsDocument.company_id == company_id))
    return f"DMS-{(count or 0) + 1:06d}"


def _set_tags(session, company_id: int, document_id: int, names: list[str]) -> list[str]:
    clean = []
    for name in names or []:
        name = " ".join(str(name).split())[:80]
        if name and name not in clean:
            clean.append(name)
    session.query(DmsDocumentTag).filter(DmsDocumentTag.document_id == document_id).delete()
    for name in clean:
        tag = session.scalar(select(DmsTag).where(DmsTag.company_id == company_id, DmsTag.name == name))
        if tag is None:
            tag = DmsTag(company_id=company_id, name=name)
            session.add(tag)
            session.flush()
        session.add(DmsDocumentTag(document_id=document_id, tag_id=tag.tag_id))
    return clean


def _store_files(session, company_id: int, user_id: int, files: list[tuple[str, bytes]], cfg, written) -> list[DmsFile]:
    checked = [storage.check(name, data, cfg.max_file_mb, cfg.keep_gps) for name, data in files]
    return [storage.put(session, company_id, user_id, item, cfg, written, cfg.text_extraction) for item in checked]


def _new_version(session, doc: DmsDocument, user_id: int, file_rows: list[DmsFile], reason: str | None, source: str) -> DmsVersion:
    number = (session.scalar(select(func.max(DmsVersion.version_no)).where(DmsVersion.document_id == doc.document_id)) or 0) + 1
    version = DmsVersion(document_id=doc.document_id, version_no=number, change_reason=(reason or None) and reason[:500],
                         source_code=source, created_by_user_id=user_id)
    session.add(version)
    session.flush()
    for position, row in enumerate(file_rows, start=1):
        session.add(DmsVersionFile(version_id=version.version_id, position=position, file_id=row.file_id))
    doc.current_version_id = version.version_id
    return version


def _current_files(session, version_id: int | None) -> list[DmsFile]:
    if version_id is None:
        return []
    return list(session.scalars(select(DmsFile).join(DmsVersionFile, DmsVersionFile.file_id == DmsFile.file_id).where(
        DmsVersionFile.version_id == version_id).order_by(DmsVersionFile.position)))


def _link(session, company_id: int, user_id: int, document_id: int, entity_type: str, entity_id: int) -> DmsLink:
    label = entities.validate(session, user_id, company_id, entity_type, entity_id)
    existing = session.scalar(select(DmsLink).where(
        DmsLink.document_id == document_id, DmsLink.entity_type == entity_type, DmsLink.entity_id == entity_id,
        DmsLink.is_active.is_(True)))
    if existing is not None:
        return existing
    link = DmsLink(document_id=document_id, company_id=company_id, entity_type=entity_type, entity_id=int(entity_id),
                   created_by_user_id=user_id)
    session.add(link)
    session.flush()
    c.log(session, company_id, document_id, "LINK", user_id, note=f"{entities.get(entity_type).label}: {label}",
          details={"entity_type": entity_type, "entity_id": int(entity_id)})
    return link


def _run(fn):
    """ثبت در یک تراکنش؛ در شکست، فایل‌هایی که در حالت FS نوشته شده‌اند پاک می‌شوند."""
    written: list = []
    try:
        with new_session() as session:
            result = fn(session, written)
            session.commit()
            return result
    except BaseException:
        storage.discard(written)
        raise


# --- ایجاد و ویرایش ------------------------------------------------------------------------------
def create_document(company_id: int, user_id: int, fields: DocumentFields, files: list[tuple[str, bytes]] = (),
                    links: list[tuple[str, int]] = (), *, source: str = "DESKTOP", reason: str | None = None) -> int:
    c.require(user_id, company_id, c.FORM_DOCS, "CREATE", "ثبت سند")

    def work(session, written):
        _validate(session, company_id, fields)
        cfg = c.settings(session, company_id)
        for entity_type, entity_id in links:
            entities.validate(session, user_id, company_id, entity_type, entity_id)
        doc = DmsDocument(
            company_id=company_id, branch_id=fields.branch_id, document_no=_next_no(session, company_id), title=fields.title,
            document_type_code=fields.document_type_code, category_id=fields.category_id,
            confidentiality_code=fields.confidentiality_code, status_code="DRAFT", owner_user_id=user_id,
            responsible_user_id=fields.responsible_user_id, issue_date=fields.issue_date, valid_from=fields.valid_from,
            expiry_date=fields.expiry_date, description=(fields.description or "").strip() or None,
            created_by_user_id=user_id, updated_by_user_id=user_id)
        session.add(doc)
        session.flush()
        c.log(session, company_id, doc.document_id, "CREATE", user_id, to_status="DRAFT", note=doc.title)
        if files:
            rows = _store_files(session, company_id, user_id, list(files), cfg, written)
            version = _new_version(session, doc, user_id, rows, reason or "نسخهٔ اول", source)
            c.log(session, company_id, doc.document_id, "VERSION", user_id, version_id=version.version_id,
                  note=f"نسخهٔ {version.version_no}", details={"files": len(rows), "source": source})
        _set_tags(session, company_id, doc.document_id, fields.tags)
        for entity_type, entity_id in links:
            _link(session, company_id, user_id, doc.document_id, entity_type, entity_id)
        return doc.document_id

    return _run(work)


def update_document(company_id: int, user_id: int, document_id: int, fields: DocumentFields, expected_row_version: int) -> None:
    def work(session, _written):
        doc = c.load_for(session, user_id, company_id, document_id, lock=True)
        c.require(user_id, company_id, c.FORM_DOCS, "EDIT", "ویرایش سند")
        if doc.row_version != expected_row_version:
            raise ValueError("این سند در این فاصله توسط کاربر دیگری تغییر کرده است؛ دوباره بازش کنید.")
        if doc.status_code == "ARCHIVED":
            raise ValueError("سند بایگانی‌شده ویرایش نمی‌شود؛ اول آن را از بایگانی بازگردانید.")
        _validate(session, company_id, fields)
        changes = {}
        for name in ("title", "document_type_code", "category_id", "confidentiality_code", "responsible_user_id", "branch_id",
                     "issue_date", "valid_from", "expiry_date", "description"):
            value = getattr(fields, name)
            if name == "description":
                value = (value or "").strip() or None
            if getattr(doc, name) != value:
                changes[name] = [str(getattr(doc, name)), str(value)]
                setattr(doc, name, value)
        old_tags = sorted(t for t in session.scalars(select(DmsTag.name).join(
            DmsDocumentTag, DmsDocumentTag.tag_id == DmsTag.tag_id).where(DmsDocumentTag.document_id == document_id)))
        new_tags = _set_tags(session, company_id, document_id, fields.tags)
        if sorted(new_tags) != old_tags:
            changes["tags"] = [old_tags, sorted(new_tags)]
        if changes:
            doc.row_version += 1
            doc.updated_by_user_id = user_id
            doc.updated_at = c.now()
            c.log(session, company_id, document_id, "UPDATE", user_id, details=changes)

    _run(work)


def add_version(company_id: int, user_id: int, document_id: int, files: list[tuple[str, bytes]], reason: str,
                *, keep_current_files: bool = False, expected_current_version_id: int | None = None,
                source: str = "DESKTOP") -> int:
    """نسخهٔ جدید: نسخهٔ قبلی می‌ماند؛ keep_current_files یعنی فایل‌های جدید به فایل‌های نسخهٔ جاری اضافه شوند."""
    if not files:
        raise ValueError("برای نسخهٔ جدید دست‌کم یک فایل لازم است.")

    def work(session, written):
        doc = c.load_for(session, user_id, company_id, document_id, lock=True)
        c.require(user_id, company_id, c.FORM_DOCS, "EDIT", "افزودن نسخهٔ سند")
        return _add_version_locked(session, written, doc, user_id, files, reason, keep_current_files,
                                   expected_current_version_id, source)

    return _run(work)


def _add_version_locked(session, written, doc: DmsDocument, user_id: int, files, reason, keep_current_files,
                        expected_current_version_id, source) -> int:
    if doc.status_code == "ARCHIVED":
        raise ValueError("به سند بایگانی‌شده نسخه اضافه نمی‌شود؛ اول آن را از بایگانی بازگردانید.")
    if expected_current_version_id is not None and doc.current_version_id != expected_current_version_id:
        raise ValueError("در این فاصله نسخهٔ دیگری برای این سند ثبت شده است؛ فهرست نسخه‌ها را دوباره ببینید.")
    cfg = c.settings(session, doc.company_id)
    current = _current_files(session, doc.current_version_id)
    rows = _store_files(session, doc.company_id, user_id, list(files), cfg, written)
    if not keep_current_files and sorted(bytes(r.sha256) for r in rows) == sorted(bytes(r.sha256) for r in current):
        raise ValueError("فایل‌های انتخاب‌شده همان فایل‌های نسخهٔ جاری‌اند؛ نسخهٔ تکراری ساخته نشد.")
    version = _new_version(session, doc, user_id, (current if keep_current_files else []) + rows, reason, source)
    c.log(session, doc.company_id, doc.document_id, "VERSION", user_id, version_id=version.version_id,
          note=f"نسخهٔ {version.version_no}" + (f" — {reason}" if reason else ""),
          details={"files": len(rows), "kept": len(current) if keep_current_files else 0, "source": source})
    if doc.status_code in ("APPROVED", "OBSOLETE"):
        c.log(session, doc.company_id, doc.document_id, "STATUS", user_id, from_status=doc.status_code, to_status="DRAFT",
              note="نسخهٔ جدید هنوز تایید نشده است")
        doc.status_code = "DRAFT"
    doc.row_version += 1
    doc.updated_by_user_id = user_id
    doc.updated_at = c.now()
    return version.version_id


def link_document(company_id: int, user_id: int, document_id: int, entity_type: str, entity_id: int) -> int:
    def work(session, _written):
        c.load_for(session, user_id, company_id, document_id)
        if not (c.can(user_id, company_id, c.FORM_DOCS, "EDIT") or c.can(user_id, company_id, c.FORM_DOCS, "CREATE")):
            raise PermissionError("برای پیوست سند به رکورد دسترسی لازم را ندارید.")
        return _link(session, company_id, user_id, document_id, entity_type, entity_id).link_id

    return _run(work)


def unlink_document(company_id: int, user_id: int, link_id: int) -> None:
    def work(session, _written):
        link = session.get(DmsLink, link_id)
        if link is None or link.company_id != company_id or not link.is_active:
            raise LookupError("پیوند پیدا نشد.")
        c.load_for(session, user_id, company_id, link.document_id)
        c.require(user_id, company_id, c.FORM_DOCS, "EDIT", "حذف پیوند سند")
        link.is_active = False
        link.removed_by_user_id = user_id
        link.removed_at = c.now()
        c.log(session, company_id, link.document_id, "UNLINK", user_id,
              details={"entity_type": link.entity_type, "entity_id": link.entity_id})

    _run(work)


# --- گردش کار ------------------------------------------------------------------------------------
def transition(company_id: int, user_id: int, document_id: int, action: str, note: str | None = None,
               expected_version_id: int | None = None) -> str:
    def work(session, _written):
        doc = c.load_for(session, user_id, company_id, document_id, lock=True)
        if action in ("archive", "restore"):
            c.require(user_id, company_id, c.FORM_DOCS, "EDIT", c.ACTION_LABELS[action])
            if action == "archive":
                if doc.status_code == "ARCHIVED":
                    raise ValueError("سند از قبل بایگانی شده است.")
                frm, to = doc.status_code, "ARCHIVED"
                doc.archived_from_status = frm
            else:
                if doc.status_code != "ARCHIVED":
                    raise ValueError("سند بایگانی نشده است.")
                frm, to = "ARCHIVED", doc.archived_from_status or "DRAFT"
                doc.archived_from_status = None
        else:
            rule = c.TRANSITIONS.get(action)
            if rule is None:
                raise ValueError("اقدام گردش کار معتبر نیست.")
            sources, to, form, needs_note = rule
            if action == "submit" and not (c.can(user_id, company_id, c.FORM_DOCS, "EDIT") or user_id == doc.owner_user_id):
                raise PermissionError("فقط مالک سند یا کاربر دارای دسترسی ویرایش، آن را برای بررسی می‌فرستد.")
            if action != "submit":
                c.require(user_id, company_id, form, "EDIT", c.ACTION_LABELS[action])
            if doc.status_code not in sources:
                raise ValueError(f"«{c.ACTION_LABELS[action]}» برای سند {c.STATUSES[doc.status_code]} ممکن نیست.")
            if needs_note and not (note or "").strip():
                raise ValueError("برای این تصمیم، توضیح لازم است.")
            if action in ("submit", "approve") and doc.current_version_id is None:
                raise ValueError("سند هنوز فایلی ندارد.")
            if action == "approve":
                if expected_version_id is not None and expected_version_id != doc.current_version_id:
                    raise ValueError("پس از شروع بررسی، نسخهٔ جدیدی ثبت شده است؛ نسخهٔ جاری را بررسی و دوباره تایید کنید.")
                doc.approved_version_id = doc.current_version_id
            frm = doc.status_code
        doc.status_code = to
        doc.row_version += 1
        doc.updated_by_user_id = user_id
        doc.updated_at = c.now()
        c.log(session, company_id, document_id, "STATUS", user_id, from_status=frm, to_status=to, note=note,
              version_id=doc.current_version_id, details={"action": action})
        return to

    return _run(work)


def delete_document(company_id: int, user_id: int, document_id: int, reason: str | None = None) -> None:
    def work(session, _written):
        doc = c.load_for(session, user_id, company_id, document_id, lock=True)
        c.require(user_id, company_id, c.FORM_DOCS, "DELETE", "حذف سند")
        doc.is_deleted = True
        doc.deleted_by_user_id = user_id
        doc.deleted_at = c.now()
        c.log(session, company_id, document_id, "DELETE", user_id, note=reason)

    _run(work)


# --- خواندن ---------------------------------------------------------------------------------------
def _visibility(user_id: int, company_id: int):
    """شرط SQL همان قاعدهٔ common.can_view برای فهرست و آمار."""
    conditions = [DmsDocument.company_id == company_id, DmsDocument.is_deleted.is_(False)]
    if not c.can(user_id, company_id, c.FORM_CONFIDENTIAL, "VIEW"):
        conditions.append(or_(DmsDocument.confidentiality_code.in_(("PUBLIC", "INTERNAL")),
                              DmsDocument.owner_user_id == user_id, DmsDocument.responsible_user_id == user_id,
                              DmsDocument.created_by_user_id == user_id))
    if not c.can(user_id, company_id, c.FORM_DOCS, "VIEW"):
        allowed = [code for code in entities.ENTITY_TYPES if entities.can_access(user_id, company_id, code)]
        conditions.append(exists().where(DmsLink.document_id == DmsDocument.document_id, DmsLink.is_active.is_(True),
                                         DmsLink.entity_type.in_(allowed or [""])))
    return and_(*conditions)


@dataclass
class SearchFilters:
    text: str | None = None
    document_type_code: str | None = None
    category_id: int | None = None
    tag: str | None = None
    statuses: list[str] | None = None
    include_archived: bool = False
    created_from: datetime.date | None = None
    created_to: datetime.date | None = None
    issue_from: datetime.date | None = None
    issue_to: datetime.date | None = None
    expiry_from: datetime.date | None = None
    expiry_to: datetime.date | None = None
    expiring_within_days: int | None = None
    expired_only: bool = False
    created_by_user_id: int | None = None
    responsible_user_id: int | None = None
    branch_id: int | None = None
    entity_type: str | None = None
    entity_id: int | None = None


def _category_tree(session, company_id: int, category_id: int) -> list[int]:
    rows = session.execute(text("""
        WITH RECURSIVE tree AS (SELECT category_id FROM doc.categories WHERE category_id = :id AND company_id = :c
                                UNION ALL SELECT k.category_id FROM doc.categories k JOIN tree t ON k.parent_category_id = t.category_id)
        SELECT category_id FROM tree"""), {"id": category_id, "c": company_id}).scalars().all()
    return list(rows) or [-1]


def search(company_id: int, user_id: int, filters: SearchFilters | None = None, page: int = 1,
           page_size: int = 50) -> tuple[list[SimpleNamespace], int]:
    f = filters or SearchFilters()
    page, page_size = max(1, int(page)), max(1, min(MAX_PAGE_SIZE, int(page_size)))
    today = datetime.date.today()
    with new_session() as session:
        where = [_visibility(user_id, company_id)]
        if f.statuses:
            where.append(DmsDocument.status_code.in_(f.statuses))
        elif not f.include_archived:
            where.append(DmsDocument.status_code != "ARCHIVED")
        if f.text and f.text.strip():
            needle = "%" + c.escape_like(f.text.strip()) + "%"
            file_match = exists().where(DmsVersionFile.version_id == DmsDocument.current_version_id,
                                        DmsFile.file_id == DmsVersionFile.file_id,
                                        or_(DmsFile.original_name.ilike(needle, escape="\\"),
                                            DmsFile.text_content.ilike(needle, escape="\\")))
            where.append(or_(DmsDocument.title.ilike(needle, escape="\\"), DmsDocument.document_no.ilike(needle, escape="\\"),
                             DmsDocument.description.ilike(needle, escape="\\"), file_match))
        if f.document_type_code:
            where.append(DmsDocument.document_type_code == f.document_type_code)
        if f.category_id:
            where.append(DmsDocument.category_id.in_(_category_tree(session, company_id, f.category_id)))
        if f.tag:
            where.append(exists().where(DmsDocumentTag.document_id == DmsDocument.document_id,
                                        DmsTag.tag_id == DmsDocumentTag.tag_id, DmsTag.name == f.tag.strip()))
        for column, low, high in ((func.date(DmsDocument.created_at), f.created_from, f.created_to),
                                  (DmsDocument.issue_date, f.issue_from, f.issue_to),
                                  (DmsDocument.expiry_date, f.expiry_from, f.expiry_to)):
            if low:
                where.append(column >= low)
            if high:
                where.append(column <= high)
        if f.expiring_within_days is not None:
            where.append(DmsDocument.expiry_date.between(today, today + datetime.timedelta(days=int(f.expiring_within_days))))
        if f.expired_only:
            where.append(DmsDocument.expiry_date < today)
        if f.created_by_user_id:
            where.append(DmsDocument.created_by_user_id == f.created_by_user_id)
        if f.responsible_user_id:
            where.append(DmsDocument.responsible_user_id == f.responsible_user_id)
        if f.branch_id:
            where.append(DmsDocument.branch_id == f.branch_id)
        if f.entity_type and f.entity_id:
            where.append(exists().where(DmsLink.document_id == DmsDocument.document_id, DmsLink.is_active.is_(True),
                                        DmsLink.entity_type == f.entity_type, DmsLink.entity_id == f.entity_id))
        total = session.scalar(select(func.count()).select_from(DmsDocument).where(*where))
        version_no = select(DmsVersion.version_no).where(DmsVersion.version_id == DmsDocument.current_version_id).scalar_subquery()
        file_count = select(func.count()).select_from(DmsVersionFile).where(
            DmsVersionFile.version_id == DmsDocument.current_version_id).scalar_subquery()
        first_file = select(DmsVersionFile.file_id).where(DmsVersionFile.version_id == DmsDocument.current_version_id).order_by(
            DmsVersionFile.position).limit(1).scalar_subquery()
        rows = session.execute(
            select(DmsDocument, version_no, file_count, first_file, DmsCategory.name, User.full_name)
            .outerjoin(DmsCategory, DmsCategory.category_id == DmsDocument.category_id)
            .outerjoin(User, User.user_id == DmsDocument.responsible_user_id)
            .where(*where).order_by(DmsDocument.document_id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
        return [_row(doc, vno, count, first, category, responsible) for doc, vno, count, first, category, responsible in rows], total


def _row(doc: DmsDocument, version_no, file_count, first_file_id, category, responsible) -> SimpleNamespace:
    return SimpleNamespace(
        document_id=doc.document_id, document_no=doc.document_no, title=doc.title, document_type_code=doc.document_type_code,
        type_label=c.DOCUMENT_TYPES.get(doc.document_type_code, doc.document_type_code), status_code=doc.status_code,
        status_label=c.STATUSES[doc.status_code], confidentiality_code=doc.confidentiality_code,
        confidentiality_label=c.CONFIDENTIALITY[doc.confidentiality_code], category_name=category,
        responsible_name=responsible, issue_date=doc.issue_date, expiry_date=doc.expiry_date, created_at=doc.created_at,
        version_no=version_no, file_count=file_count or 0, first_file_id=first_file_id, branch_id=doc.branch_id,
        approved_is_current=doc.approved_version_id is not None and doc.approved_version_id == doc.current_version_id)


def get_document(company_id: int, user_id: int, document_id: int) -> SimpleNamespace:
    with new_session() as session:
        doc = c.load_for(session, user_id, company_id, document_id)
        names = dict(session.execute(select(User.user_id, User.full_name)).all())
        versions = []
        for version in session.scalars(select(DmsVersion).where(DmsVersion.document_id == document_id).order_by(
                DmsVersion.version_no.desc())):
            files = [SimpleNamespace(file_id=f.file_id, name=f.original_name, mime_type=f.mime_type, extension=f.extension,
                                     size_bytes=f.size_bytes, width=f.width, height=f.height, text_status=f.text_status)
                     for f in _current_files(session, version.version_id)]
            versions.append(SimpleNamespace(
                version_id=version.version_id, version_no=version.version_no, reason=version.change_reason,
                source_code=version.source_code, created_by=names.get(version.created_by_user_id, ""),
                created_at=version.created_at, files=files, is_current=version.version_id == doc.current_version_id,
                is_approved=version.version_id == doc.approved_version_id))
        links = []
        for link in session.scalars(select(DmsLink).where(DmsLink.document_id == document_id, DmsLink.is_active.is_(True))):
            found = entities.describe(session, company_id, link.entity_type, link.entity_id)
            links.append(SimpleNamespace(
                link_id=link.link_id, entity_type=link.entity_type, entity_id=link.entity_id,
                type_label=entities.ENTITY_TYPES[link.entity_type].label if link.entity_type in entities.ENTITY_TYPES else link.entity_type,
                label=found[0] if found else "رکورد حذف شده است", record_active=bool(found and found[1]),
                created_by=names.get(link.created_by_user_id, ""), created_at=link.created_at))
        events = [SimpleNamespace(
            event_code=e.event_code, label=c.EVENT_LABELS.get(e.event_code, e.event_code), user=names.get(e.user_id, ""),
            from_status=c.STATUSES.get(e.from_status or "", None), to_status=c.STATUSES.get(e.to_status or "", None),
            note=e.note, created_at=e.created_at)
            for e in session.scalars(select(DmsEvent).where(DmsEvent.document_id == document_id, DmsEvent.event_code != "DENIED")
                                     .order_by(DmsEvent.event_id.desc()).limit(300))]
        tags = sorted(session.scalars(select(DmsTag.name).join(DmsDocumentTag, DmsDocumentTag.tag_id == DmsTag.tag_id).where(
            DmsDocumentTag.document_id == document_id)))
        fields = {k: getattr(doc, k) for k in (
            "document_id", "document_no", "title", "document_type_code", "category_id", "confidentiality_code", "status_code",
            "owner_user_id", "responsible_user_id", "branch_id", "issue_date", "valid_from", "expiry_date", "description",
            "current_version_id", "approved_version_id", "row_version", "created_at", "updated_at", "created_by_user_id")}
        return SimpleNamespace(**fields, tags=tags, versions=versions, links=links, events=events,
                               status_label=c.STATUSES[doc.status_code],
                               type_label=c.DOCUMENT_TYPES.get(doc.document_type_code, doc.document_type_code),
                               owner_name=names.get(doc.owner_user_id, ""), responsible_name=names.get(doc.responsible_user_id, ""),
                               can_edit=c.can(user_id, company_id, c.FORM_DOCS, "EDIT") and doc.status_code != "ARCHIVED",
                               can_decide=c.can(user_id, company_id, c.FORM_APPROVE, "EDIT"),
                               can_delete=c.can(user_id, company_id, c.FORM_DOCS, "DELETE"))


def read_file(company_id: int, user_id: int, file_id: int, *, thumbnail: bool = False) -> tuple[str, str, bytes]:
    """(نام، نوع، بایت‌ها) فقط اگر فایل در نسخه‌ای از سندی باشد که کاربر اجازهٔ دیدنش را دارد."""
    with new_session() as session:
        row = session.get(DmsFile, file_id)
        document_ids = session.scalars(select(DmsVersion.document_id).join(
            DmsVersionFile, DmsVersionFile.version_id == DmsVersion.version_id).where(DmsVersionFile.file_id == file_id)).all()
        doc = None
        for document_id in set(document_ids):
            candidate = session.get(DmsDocument, document_id)
            if c.can_view(session, user_id, company_id, candidate):
                doc = candidate
                break
        if row is None or row.company_id != company_id or doc is None:
            raise LookupError("فایل پیدا نشد یا اجازهٔ دیدن آن را ندارید.")
        if thumbnail:
            if row.thumbnail is None:
                raise LookupError("برای این فایل تصویر کوچک وجود ندارد.")
            return row.original_name, "image/jpeg", bytes(row.thumbnail)
        data = storage.read(session, row)
        c.log(session, company_id, doc.document_id, "DOWNLOAD", user_id, details={"file_id": file_id})
        session.commit()
        return row.original_name, row.mime_type, data


def documents_for_entity(company_id: int, user_id: int, entity_type: str, entity_id: int) -> list[SimpleNamespace]:
    """اسناد پیوسته به یک رکورد (برای پنل «اسناد مرتبط» در فرم همان رکورد)."""
    entities.get(entity_type)
    if not (entities.can_access(user_id, company_id, entity_type) or c.can(user_id, company_id, c.FORM_DOCS, "VIEW")):
        raise PermissionError("به این رکورد دسترسی ندارید.")
    rows, _total = search(company_id, user_id, SearchFilters(entity_type=entity_type, entity_id=int(entity_id),
                                                             include_archived=True), page_size=MAX_PAGE_SIZE)
    return rows


# --- دسته‌بندی ------------------------------------------------------------------------------------
def list_categories(company_id: int, include_inactive: bool = False) -> list[SimpleNamespace]:
    with new_session() as session:
        rows = session.scalars(select(DmsCategory).where(DmsCategory.company_id == company_id).order_by(DmsCategory.name)).all()
        by_id = {r.category_id: r for r in rows}

        def path(row) -> str:
            parts, seen = [], set()
            while row is not None and row.category_id not in seen:
                seen.add(row.category_id)
                parts.append(row.name)
                row = by_id.get(row.parent_category_id)
            return " › ".join(reversed(parts))

        return sorted((SimpleNamespace(category_id=r.category_id, name=r.name, parent_category_id=r.parent_category_id,
                                       is_active=r.is_active, path=path(r))
                       for r in rows if include_inactive or r.is_active), key=lambda r: r.path)


def save_category(company_id: int, user_id: int, category_id: int | None, name: str, parent_category_id: int | None,
                  is_active: bool = True) -> int:
    c.require(user_id, company_id, c.FORM_CATEGORIES, "EDIT" if category_id else "CREATE", "تعریف دسته‌بندی اسناد")
    name = " ".join((name or "").split())
    if not name:
        raise ValueError("نام دسته‌بندی را وارد کنید.")
    with new_session() as session:
        if parent_category_id is not None:
            parent = session.get(DmsCategory, parent_category_id)
            if parent is None or parent.company_id != company_id:
                raise ValueError("دستهٔ والد معتبر نیست.")
            node = parent
            while node is not None:
                if category_id is not None and node.category_id == category_id:
                    raise ValueError("دسته نمی‌تواند زیرمجموعهٔ خودش باشد.")
                node = session.get(DmsCategory, node.parent_category_id) if node.parent_category_id else None
        duplicate = session.scalar(select(DmsCategory.category_id).where(
            DmsCategory.company_id == company_id, DmsCategory.name == name,
            DmsCategory.parent_category_id.is_(None) if parent_category_id is None else DmsCategory.parent_category_id == parent_category_id,
            DmsCategory.category_id != (category_id or 0)))
        if duplicate:
            raise ValueError("دسته‌ای با همین نام در همین سطح وجود دارد.")
        if category_id is None:
            row = DmsCategory(company_id=company_id, name=name, parent_category_id=parent_category_id, is_active=is_active)
            session.add(row)
        else:
            row = session.get(DmsCategory, category_id)
            if row is None or row.company_id != company_id:
                raise LookupError("دسته‌بندی پیدا نشد.")
            row.name, row.parent_category_id, row.is_active = name, parent_category_id, is_active
        session.commit()
        return row.category_id


def list_tags(company_id: int) -> list[str]:
    with new_session() as session:
        return list(session.scalars(select(DmsTag.name).where(DmsTag.company_id == company_id).order_by(DmsTag.name)))


# --- داشبورد ---------------------------------------------------------------------------------------
def dashboard(company_id: int, user_id: int) -> SimpleNamespace:
    """آمار واقعی با همان شرط دسترسی فهرست اسناد."""
    from peecha.db.models.documents import DmsCaptureRequest

    today = datetime.date.today()
    with new_session() as session:
        cfg = c.settings(session, company_id)
        visible = _visibility(user_id, company_id)

        def count(*extra) -> int:
            return session.scalar(select(func.count()).select_from(DmsDocument).where(visible, *extra)) or 0

        by_status = dict(session.execute(select(DmsDocument.status_code, func.count()).where(visible).group_by(
            DmsDocument.status_code)).all())
        by_category = session.execute(select(func.coalesce(DmsCategory.name, "بدون دسته"), func.count()).select_from(DmsDocument)
                                      .outerjoin(DmsCategory, DmsCategory.category_id == DmsDocument.category_id)
                                      .where(visible).group_by(DmsCategory.name).order_by(func.count().desc())).all()
        recent, _total = search(company_id, user_id, page_size=8)
        mine = DmsCaptureRequest.company_id == company_id
        if not c.can(user_id, company_id, c.FORM_DOCS, "VIEW"):
            mine = and_(mine, DmsCaptureRequest.requested_by_user_id == user_id)
        captures = dict(session.execute(select(DmsCaptureRequest.status_code, func.count()).where(
            mine, DmsCaptureRequest.created_at >= c.now() - datetime.timedelta(days=7)).group_by(DmsCaptureRequest.status_code)).all())
        active = session.scalar(select(func.count()).select_from(DmsCaptureRequest).where(
            mine, DmsCaptureRequest.status_code.in_(("PENDING", "OPENED", "CAPTURING", "UPLOADING")),
            DmsCaptureRequest.expires_at > c.now())) or 0
        session.commit()
        return SimpleNamespace(
            total=sum(by_status.values()), by_status=by_status, pending=by_status.get("PENDING", 0) + by_status.get("IN_REVIEW", 0),
            needs_changes=by_status.get("NEEDS_CHANGES", 0),
            expiring=count(DmsDocument.expiry_date.between(today, today + datetime.timedelta(days=cfg.expiry_reminder_days)),
                           DmsDocument.status_code != "ARCHIVED"),
            expired=count(DmsDocument.expiry_date < today, DmsDocument.status_code.notin_(("ARCHIVED", "OBSOLETE"))),
            by_category=[(name, n) for name, n in by_category], recent=recent, captures_active=active,
            captures_completed=captures.get("COMPLETED", 0),
            captures_failed=captures.get("FAILED", 0) + captures.get("EXPIRED", 0) + captures.get("CANCELLED", 0))
