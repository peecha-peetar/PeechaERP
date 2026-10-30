"""R343: درخواست عکس‌برداری با موبایل.

دسکتاپ درخواست می‌سازد (توکن تصادفی ۱۹۲بیتی؛ فقط هش SHA-256 آن ذخیره می‌شود) و برای همان کاربر اعلان داخل برنامه
ثبت می‌کند. گوشی با QR (صفحهٔ وب موبایل) یا از فهرست درخواست‌های اپ موبایل درخواست را باز می‌کند؛ در هر دو حالت
کاربر باید با همان حساب ERP وارد شده باشد و درخواست فقط برای کاربر و شرکت درخواست‌دهنده باز می‌شود. ارسال عکس
دوباره دسترسی را می‌سنجد، فایل را بررسی می‌کند و در یک تراکنش سند/نسخه و پیوند را می‌سازد. تکرار همان ارسال (با
همان کلید) نتیجهٔ قبلی را برمی‌گرداند و پیوست تکراری نمی‌سازد؛ درخواست تکمیل‌شده، لغوشده یا منقضی دوباره باز نمی‌شود."""

from __future__ import annotations

import datetime
import hashlib
import secrets
from types import SimpleNamespace

from sqlalchemy import select, update

from peecha.db.base import new_session
from peecha.db.models.documents import DmsCaptureRequest, DmsDocument
from peecha.services.dms import common as c
from peecha.services.dms import documents as docs_service
from peecha.services.dms import entities

STATUS_LABELS = {
    "PENDING": "در انتظار گوشی", "OPENED": "روی گوشی باز شد", "CAPTURING": "در حال عکس‌برداری", "UPLOADING": "در حال ارسال",
    "COMPLETED": "تکمیل شد", "CANCELLED": "لغو شد", "EXPIRED": "منقضی شد", "FAILED": "ناموفق",
}
ACTIVE = ("PENDING", "OPENED", "CAPTURING", "UPLOADING", "FAILED")
_ALLOWED = {
    "PENDING": {"OPENED", "CANCELLED", "EXPIRED"},
    "OPENED": {"OPENED", "CAPTURING", "UPLOADING", "CANCELLED", "EXPIRED", "FAILED"},
    "CAPTURING": {"CAPTURING", "UPLOADING", "CANCELLED", "EXPIRED", "FAILED"},
    # ارسال تکراری (قطع شبکه پیش از پاسخ) دوباره پردازش می‌شود؛ فقط یکی در تراکنش نهایی تکمیل می‌کند
    "UPLOADING": {"UPLOADING", "COMPLETED", "FAILED", "EXPIRED", "CANCELLED"},
    "FAILED": {"OPENED", "CAPTURING", "UPLOADING", "CANCELLED", "EXPIRED"},
    "COMPLETED": set(), "CANCELLED": set(), "EXPIRED": set(),
}
MAX_ATTEMPTS = 5


class CaptureError(Exception):
    """خطای درخواست عکس‌برداری با کد وضعیت HTTP مناسب (برای لایهٔ API)."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def hash_token(token: str) -> bytes:
    return hashlib.sha256((token or "").encode("utf-8")).digest()


def _move(req: DmsCaptureRequest, to: str) -> None:
    if to not in _ALLOWED[req.status_code]:
        raise CaptureError(f"درخواست {STATUS_LABELS[req.status_code]}؛ این کار دیگر ممکن نیست.", 409)
    req.status_code = to


def _expire_if_due(req: DmsCaptureRequest) -> None:
    if req.status_code in ACTIVE and req.expires_at <= c.now():
        req.status_code = "EXPIRED"


def _target_label(session, req: DmsCaptureRequest) -> tuple[str, str]:
    if req.target_document_id:
        doc = session.get(DmsDocument, req.target_document_id)
        return "سند", f"{doc.document_no} — {doc.title}" if doc else "سند"
    entity = entities.ENTITY_TYPES.get(req.target_entity_type or "")
    found = entities.describe(session, req.company_id, req.target_entity_type, req.target_entity_id) if entity else None
    return (entity.label if entity else "رکورد"), (found[0] if found else "رکورد پیدا نشد")


def _view(session, req: DmsCaptureRequest, token: str | None = None) -> SimpleNamespace:
    kind, label = _target_label(session, req)
    return SimpleNamespace(
        request_id=req.request_id, status_code=req.status_code, status_label=STATUS_LABELS[req.status_code],
        target_kind=kind, target_label=label, expires_at=req.expires_at, max_photos=req.max_photos,
        result_document_id=req.result_document_id, result_version_id=req.result_version_id, token=token,
        failure_reason=req.failure_reason, created_at=req.created_at)


# --- دسکتاپ ---------------------------------------------------------------------------------------------
def create_request(company_id: int, user_id: int, *, entity_type: str | None = None, entity_id: int | None = None,
                   document_id: int | None = None, title: str | None = None, document_type_code: str = "IMAGE",
                   branch_id: int | None = None) -> SimpleNamespace:
    """درخواست جدید برای همین کاربر؛ خروجی token فقط همین‌جا برمی‌گردد (برای QR) و جایی ذخیره نمی‌شود."""
    if document_type_code not in c.DOCUMENT_TYPES:
        raise ValueError("نوع سند معتبر نیست.")
    with new_session() as session:
        if document_id is not None:
            doc = c.load_for(session, user_id, company_id, document_id)
            c.require(user_id, company_id, c.FORM_DOCS, "EDIT", "افزودن تصویر به سند")
            if doc.status_code == "ARCHIVED":
                raise ValueError("به سند بایگانی‌شده تصویر اضافه نمی‌شود.")
            label = f"{doc.document_no} — {doc.title}"
        elif entity_type and entity_id:
            c.require(user_id, company_id, c.FORM_DOCS, "CREATE", "ثبت سند از عکس موبایل")
            label = entities.validate(session, user_id, company_id, entity_type, int(entity_id))
        else:
            raise ValueError("مقصد عکس (سند یا رکورد) مشخص نیست.")
        cfg = c.settings(session, company_id)
        token = secrets.token_urlsafe(24)
        req = DmsCaptureRequest(
            company_id=company_id, branch_id=branch_id, token_hash=hash_token(token), requested_by_user_id=user_id,
            target_entity_type=entity_type if document_id is None else None,
            target_entity_id=int(entity_id) if document_id is None else None, target_document_id=document_id,
            document_type_code=document_type_code, title=(title or "").strip()[:300] or None, max_photos=cfg.capture_max_photos,
            status_code="PENDING", expires_at=c.now() + datetime.timedelta(minutes=cfg.capture_minutes))
        session.add(req)
        session.flush()
        c.log(session, company_id, document_id, "CAPTURE", user_id, note=f"درخواست عکس‌برداری برای {label}",
              details={"request_id": req.request_id, "action": "create"})
        session.commit()
        view = _view(session, req, token)
    from peecha.services import notifications as notifications_service

    try:  # اعلان داخل برنامه (موبایل و زنگولهٔ دسکتاپ)؛ نبودنش مانع درخواست نیست
        notifications_service.create_notification(company_id, user_id, "DMS_CAPTURE", "درخواست عکس‌برداری جدید",
                                                  f"{view.target_kind}: {view.target_label}", "DmsCaptureRequest", view.request_id)
    except Exception:  # noqa: BLE001
        pass
    return view


def mobile_url(company_id: int, token: str) -> str | None:
    with new_session() as session:
        base = (c.settings(session, company_id).mobile_base_url or "").strip().rstrip("/")
        session.commit()
    return f"{base}/m/capture#{token}" if base else None


def status(company_id: int, user_id: int, request_id: int) -> SimpleNamespace:
    """برای به‌روزرسانی پنجرهٔ دسکتاپ (هر چند ثانیه)."""
    with new_session() as session:
        req = session.get(DmsCaptureRequest, request_id)
        if req is None or req.company_id != company_id or req.requested_by_user_id != user_id:
            raise LookupError("درخواست پیدا نشد.")
        _expire_if_due(req)
        session.commit()
        return _view(session, req)


def cancel(company_id: int, user_id: int, *, request_id: int | None = None, token: str | None = None) -> SimpleNamespace:
    with new_session() as session:
        req = _load(session, company_id, user_id, request_id=request_id, token=token, lock=True)
        _move(req, "CANCELLED")
        req.cancelled_at = c.now()
        req.cancelled_by_user_id = user_id
        c.log(session, company_id, req.target_document_id, "CAPTURE", user_id, note="درخواست عکس‌برداری لغو شد",
              details={"request_id": req.request_id, "action": "cancel"})
        session.commit()
        return _view(session, req)


# --- گوشی --------------------------------------------------------------------------------------------
def _load(session, company_id: int, user_id: int, *, request_id: int | None = None, token: str | None = None,
          lock: bool = False) -> DmsCaptureRequest:
    """فقط درخواست همین کاربر و شرکت؛ توکن نامعتبر، ناموجود یا مال کاربر دیگر همه یک پیام می‌گیرند."""
    query = select(DmsCaptureRequest)
    query = query.where(DmsCaptureRequest.token_hash == hash_token(token)) if token else \
        query.where(DmsCaptureRequest.request_id == (request_id or 0))
    req = session.scalar(query.with_for_update() if lock else query)
    if req is None or req.company_id != company_id or req.requested_by_user_id != user_id:
        raise CaptureError("درخواست عکس‌برداری پیدا نشد یا برای حساب شما نیست.", 404)
    _expire_if_due(req)
    if req.status_code == "EXPIRED" and not req.consumed_at:
        session.commit()
    return req


def open_request(company_id: int, user_id: int, *, request_id: int | None = None, token: str | None = None) -> SimpleNamespace:
    with new_session() as session:
        req = _load(session, company_id, user_id, request_id=request_id, token=token, lock=True)
        if req.status_code in ("COMPLETED", "CANCELLED", "EXPIRED"):
            raise CaptureError(f"این درخواست {STATUS_LABELS[req.status_code]} و دیگر قابل استفاده نیست.", 410)
        _move(req, "OPENED")
        req.opened_at = req.opened_at or c.now()
        session.commit()
        return _view(session, req)


def mark_capturing(company_id: int, user_id: int, *, request_id: int | None = None, token: str | None = None) -> SimpleNamespace:
    with new_session() as session:
        req = _load(session, company_id, user_id, request_id=request_id, token=token, lock=True)
        if req.status_code in ("COMPLETED", "CANCELLED", "EXPIRED"):
            raise CaptureError(f"این درخواست {STATUS_LABELS[req.status_code]} و دیگر قابل استفاده نیست.", 410)
        _move(req, "CAPTURING")
        session.commit()
        return _view(session, req)


def active_requests(company_id: int, user_id: int) -> list[SimpleNamespace]:
    """درخواست‌های باز همین کاربر (فهرست اپ موبایل)."""
    with new_session() as session:
        rows = session.scalars(select(DmsCaptureRequest).where(
            DmsCaptureRequest.company_id == company_id, DmsCaptureRequest.requested_by_user_id == user_id,
            DmsCaptureRequest.status_code.in_(ACTIVE)).order_by(DmsCaptureRequest.request_id.desc()).limit(20)).all()
        views = []
        for req in rows:
            _expire_if_due(req)
            if req.status_code != "EXPIRED":
                views.append(_view(session, req))
        session.commit()
        return views


def upload(company_id: int, user_id: int, photos: list[tuple[str, bytes]], upload_key: str, *, request_id: int | None = None,
           token: str | None = None, source: str = "WEB") -> SimpleNamespace:
    """ارسال عکس‌ها. upload_key کلید تکرارنشدن همین ارسال است: تکرار با همان کلید نتیجهٔ قبلی را برمی‌گرداند."""
    upload_key = (upload_key or "").strip()[:80]
    if not upload_key:
        raise CaptureError("کلید ارسال لازم است.", 400)
    with new_session() as session:
        req = _load(session, company_id, user_id, request_id=request_id, token=token, lock=True)
        if req.status_code == "COMPLETED":
            if req.upload_key == upload_key:
                return _view(session, req)
            raise CaptureError("این درخواست قبلاً تکمیل شده و دوباره استفاده نمی‌شود.", 409)
        if req.status_code in ("CANCELLED", "EXPIRED"):
            raise CaptureError(f"این درخواست {STATUS_LABELS[req.status_code]} و دیگر قابل استفاده نیست.", 410)
        if req.attempt_count >= MAX_ATTEMPTS:
            raise CaptureError("تعداد تلاش‌های ارسال از حد مجاز گذشت؛ از کامپیوتر درخواست جدید بسازید.", 429)
        if not photos:
            raise CaptureError("دست‌کم یک عکس بفرستید.", 400)
        if len(photos) > req.max_photos:
            raise CaptureError(f"حداکثر {req.max_photos} عکس در هر درخواست پذیرفته می‌شود.", 400)
        _move(req, "UPLOADING")
        req.attempt_count += 1
        session.commit()
        request_id, target_document_id = req.request_id, req.target_document_id
        target = (req.target_entity_type, req.target_entity_id)
        title, type_code, branch_id = req.title, req.document_type_code, req.branch_id
    try:
        images = [(name, data) for name, data in photos]
        if any(not name.lower().rsplit(".", 1)[-1] in ("jpg", "jpeg", "png", "webp") for name, _data in images):
            raise ValueError("فقط عکس (JPEG، PNG یا WEBP) پذیرفته می‌شود.")
        if target_document_id is not None:
            result_document_id, result_version_id = _append_to_document(company_id, user_id, target_document_id, images,
                                                                        request_id, upload_key, source)
        else:
            result_document_id, result_version_id = _new_document(company_id, user_id, target, title, type_code, branch_id,
                                                                  images, request_id, upload_key, source)
    except CaptureError:
        _fail(company_id, request_id, "ارسال تکمیل نشد")
        raise
    except (ValueError, LookupError, PermissionError) as exc:
        _fail(company_id, request_id, str(exc)[:300])
        raise CaptureError(str(exc), 403 if isinstance(exc, PermissionError) else 422) from exc
    except Exception as exc:  # noqa: BLE001 - علت فنی به گوشی فرستاده نمی‌شود
        _fail(company_id, request_id, "خطای ذخیره‌سازی")
        raise CaptureError("ذخیرهٔ عکس ممکن نشد؛ دوباره تلاش کنید.", 503) from exc
    with new_session() as session:
        return _view(session, session.get(DmsCaptureRequest, request_id))


def _finish(session, company_id: int, request_id: int, upload_key: str, document_id: int, version_id: int) -> None:
    """درخواست در همان تراکنش ساخت سند تکمیل می‌شود؛ اگر هم‌زمان ارسال دیگری آن را بسته باشد، کل تراکنش برمی‌گردد."""
    done = session.execute(update(DmsCaptureRequest).where(
        DmsCaptureRequest.request_id == request_id, DmsCaptureRequest.status_code == "UPLOADING").values(
        status_code="COMPLETED", completed_at=c.now(), consumed_at=c.now(), upload_key=upload_key,
        result_document_id=document_id, result_version_id=version_id, failure_reason=None))
    if done.rowcount != 1:
        raise CaptureError("این درخواست هم‌زمان تکمیل یا لغو شده است.", 409)


def _new_document(company_id, user_id, target, title, type_code, branch_id, images, request_id, upload_key, source):
    entity_type, entity_id = target

    def work(session, written):
        label = entities.validate(session, user_id, company_id, entity_type, entity_id)
        c.require(user_id, company_id, c.FORM_DOCS, "CREATE", "ثبت سند از عکس موبایل")
        fields = docs_service.DocumentFields(title=title or f"تصویر {entities.get(entity_type).label} {label}"[:300],
                                             document_type_code=type_code, branch_id=branch_id)
        docs_service._validate(session, company_id, fields)
        cfg = c.settings(session, company_id)
        doc = DmsDocument(company_id=company_id, branch_id=branch_id, document_no=docs_service._next_no(session, company_id),
                          title=fields.title, document_type_code=type_code, confidentiality_code="INTERNAL", status_code="DRAFT",
                          owner_user_id=user_id, created_by_user_id=user_id, updated_by_user_id=user_id)
        session.add(doc)
        session.flush()
        c.log(session, company_id, doc.document_id, "CREATE", user_id, to_status="DRAFT", note=doc.title)
        rows = docs_service._store_files(session, company_id, user_id, images, cfg, written)
        version = docs_service._new_version(session, doc, user_id, rows, "عکس‌برداری با موبایل", "MOBILE" if source == "APP" else "WEB")
        c.log(session, company_id, doc.document_id, "VERSION", user_id, version_id=version.version_id,
              note=f"نسخهٔ {version.version_no}", details={"files": len(rows), "source": source, "request_id": request_id})
        docs_service._link(session, company_id, user_id, doc.document_id, entity_type, entity_id)
        c.log(session, company_id, doc.document_id, "CAPTURE", user_id, note=f"{len(rows)} عکس از موبایل",
              details={"request_id": request_id, "action": "complete"})
        _finish(session, company_id, request_id, upload_key, doc.document_id, version.version_id)
        return doc.document_id, version.version_id

    return docs_service._run(work)


def _append_to_document(company_id, user_id, document_id, images, request_id, upload_key, source):
    def work(session, written):
        doc = c.load_for(session, user_id, company_id, document_id, lock=True)
        c.require(user_id, company_id, c.FORM_DOCS, "EDIT", "افزودن تصویر به سند")
        version_id = docs_service._add_version_locked(session, written, doc, user_id, images, "افزودن عکس از موبایل", True, None,
                                                      "MOBILE" if source == "APP" else "WEB")
        c.log(session, company_id, doc.document_id, "CAPTURE", user_id, note=f"{len(images)} عکس از موبایل",
              details={"request_id": request_id, "action": "complete"})
        _finish(session, company_id, request_id, upload_key, doc.document_id, version_id)
        return doc.document_id, version_id

    return docs_service._run(work)


def _fail(company_id: int, request_id: int, reason: str) -> None:
    with new_session() as session:
        req = session.scalar(select(DmsCaptureRequest).where(DmsCaptureRequest.request_id == request_id).with_for_update())
        if req is not None and req.status_code == "UPLOADING":
            req.status_code = "FAILED"
            req.failure_reason = reason[:300]
            c.log(session, company_id, req.target_document_id, "CAPTURE", req.requested_by_user_id,
                  note="ارسال عکس ناموفق بود", details={"request_id": request_id, "action": "fail"})
            session.commit()


def expire_due(company_id: int | None = None) -> int:
    """درخواست‌های گذشته از زمان را منقضی می‌کند (تیک دوره‌ای)."""
    with new_session() as session:
        query = update(DmsCaptureRequest).where(DmsCaptureRequest.status_code.in_(ACTIVE), DmsCaptureRequest.expires_at <= c.now())
        if company_id is not None:
            query = query.where(DmsCaptureRequest.company_id == company_id)
        count = session.execute(query.values(status_code="EXPIRED")).rowcount
        session.commit()
        return count
