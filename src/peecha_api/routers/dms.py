"""R343: مدیریت اسناد روی API: صفحهٔ وب عکس‌برداری موبایل (با QR)، درخواست‌های عکس‌برداری اپ موبایل، فهرست اسناد
یک رکورد و دریافت فایل با کنترل دسترسی. منطق همه در services/dms است؛ این‌جا فقط ورود/خروج HTTP."""

from __future__ import annotations

import base64
import binascii
import secrets
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.documents import DmsCaptureRequest, DmsSettings
from peecha.db.models.security import UserCompany
from peecha.services.dms import capture as capture_service
from peecha.services.dms import documents as documents_service
from peecha_api import audit_log
from peecha_api.deps import AuthContext, get_current_context
from peecha_api.rate_limit import enforce_rate_limit

router = APIRouter(tags=["dms"])
_PAGE = Path(__file__).resolve().parent.parent / "static" / "capture.html"


class Photo(BaseModel):
    name: str = Field(max_length=200)
    data_base64: str


class UploadRequest(BaseModel):
    photos: list[Photo] = Field(min_length=1, max_length=30)


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, capture_service.CaptureError):
        return HTTPException(status_code=exc.status, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


def _view(v) -> dict:
    return {"request_id": v.request_id, "status": v.status_code, "status_label": v.status_label, "target_kind": v.target_kind,
            "target_label": v.target_label, "expires_at": v.expires_at.isoformat() if v.expires_at else None,
            "max_photos": v.max_photos, "result_document_id": v.result_document_id}


def _company_for(ctx: AuthContext, *, token: str | None = None, request_id: int | None = None) -> int:
    """درخواست ممکن است در شرکتی غیر از شرکت پیش‌فرض ورود موبایل ساخته شده باشد؛ اگر کاربر به آن شرکت دسترسی دارد، همان."""
    with new_session() as session:
        query = select(DmsCaptureRequest.company_id)
        query = query.where(DmsCaptureRequest.token_hash == capture_service.hash_token(token)) if token else \
            query.where(DmsCaptureRequest.request_id == (request_id or 0))
        company_id = session.scalar(query)
        if company_id is not None and session.scalar(select(UserCompany.user_id).where(
                UserCompany.user_id == ctx.user_id, UserCompany.company_id == company_id)):
            return company_id
    return ctx.company_id


def _decode(payload: UploadRequest, request: Request, company_id: int) -> list[tuple[str, bytes]]:
    with new_session() as session:
        cfg = session.get(DmsSettings, company_id)
        limit_mb = cfg.max_file_mb if cfg else 25
    declared = int(request.headers.get("content-length") or 0)
    if declared > (limit_mb * 1.4 + 1) * 1024 * 1024 * len(payload.photos):
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"حجم ارسال بیش از حد مجاز ({limit_mb} مگابایت برای هر عکس) است.")
    photos = []
    for photo in payload.photos:
        try:
            photos.append((photo.name, base64.b64decode(photo.data_base64, validate=True)))
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="دادهٔ عکس خراب است.") from exc
    return photos


def _limit(request: Request, key: str, max_calls: int = 30) -> None:
    enforce_rate_limit(request, "dms-capture", key, max_calls)


# --- صفحهٔ وب موبایل --------------------------------------------------------------------------------------
@router.get("/m/capture", response_class=HTMLResponse, include_in_schema=False)
def capture_page(request: Request) -> HTMLResponse:
    """صفحه فقط کد صفحه است و هیچ دادهٔ سند یا کاربری ندارد. توکن بعد از # در لینک QR است که به سرور (و لاگ‌ها) نمی‌رسد
    و فقط در سرآیند X-Capture-Token فرستاده می‌شود."""
    _limit(request, "page", 60)
    nonce = secrets.token_urlsafe(16)
    html = _PAGE.read_text(encoding="utf-8").replace("{{NONCE}}", nonce)
    return HTMLResponse(html, headers={
        "Content-Security-Policy": f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                                   "img-src 'self' blob: data:; connect-src 'self'; form-action 'none'; base-uri 'none'; "
                                   "frame-ancestors 'none'",
        "Referrer-Policy": "no-referrer", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY"})


# --- عکس‌برداری با توکن (صفحهٔ وب) ---------------------------------------------------------------------------------
def _capture_token(x_capture_token: str = Header(default="", alias="X-Capture-Token", max_length=200)) -> str:
    if not x_capture_token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="درخواست عکس‌برداری پیدا نشد یا برای حساب شما نیست.")
    return x_capture_token


def _by_token(fn, token: str, ctx: AuthContext, request: Request):
    _limit(request, token[:12])
    company_id = _company_for(ctx, token=token)
    try:
        return fn(company_id, ctx.user_id, token=token)
    except (capture_service.CaptureError, LookupError, PermissionError, ValueError) as exc:
        raise _http(exc) from exc


@router.post("/dms/capture/token/open")
def open_by_token(request: Request, token: str = Depends(_capture_token), ctx: AuthContext = Depends(get_current_context)) -> dict:
    return _view(_by_token(capture_service.open_request, token, ctx, request))


@router.post("/dms/capture/token/capturing")
def capturing_by_token(request: Request, token: str = Depends(_capture_token), ctx: AuthContext = Depends(get_current_context)) -> dict:
    return _view(_by_token(capture_service.mark_capturing, token, ctx, request))


@router.post("/dms/capture/token/cancel")
def cancel_by_token(request: Request, token: str = Depends(_capture_token), ctx: AuthContext = Depends(get_current_context)) -> dict:
    return _view(_by_token(capture_service.cancel, token, ctx, request))


@router.post("/dms/capture/token/upload")
def upload_by_token(payload: UploadRequest, request: Request, token: str = Depends(_capture_token),
                    ctx: AuthContext = Depends(get_current_context),
                    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict:
    _limit(request, token[:12], 10)
    company_id = _company_for(ctx, token=token)
    photos = _decode(payload, request, company_id)
    try:
        view = capture_service.upload(company_id, ctx.user_id, photos, idempotency_key or "", token=token, source="WEB")
    except capture_service.CaptureError as exc:
        raise _http(exc) from exc
    audit_log.record(company_id, ctx.user_id, "DmsCaptureRequest", view.request_id, "CREATE",
                     {"photos": len(photos), "document_id": view.result_document_id})
    return _view(view)


# --- عکس‌برداری با شناسه (اپ موبایل) --------------------------------------------------------------------------------
@router.get("/dms/capture/requests")
def list_requests(ctx: AuthContext = Depends(get_current_context)) -> list[dict]:
    with new_session() as session:
        companies = list(session.scalars(select(UserCompany.company_id).where(UserCompany.user_id == ctx.user_id)))
    rows = []
    for company_id in companies or [ctx.company_id]:
        rows += [_view(v) for v in capture_service.active_requests(company_id, ctx.user_id)]
    return sorted(rows, key=lambda r: -r["request_id"])


def _by_id(fn, request_id: int, ctx: AuthContext, request: Request):
    _limit(request, f"id{request_id}")
    company_id = _company_for(ctx, request_id=request_id)
    try:
        return fn(company_id, ctx.user_id, request_id=request_id)
    except (capture_service.CaptureError, LookupError, PermissionError, ValueError) as exc:
        raise _http(exc) from exc


@router.post("/dms/capture/requests/{request_id}/open")
def open_by_id(request_id: int, request: Request, ctx: AuthContext = Depends(get_current_context)) -> dict:
    return _view(_by_id(capture_service.open_request, request_id, ctx, request))


@router.post("/dms/capture/requests/{request_id}/capturing")
def capturing_by_id(request_id: int, request: Request, ctx: AuthContext = Depends(get_current_context)) -> dict:
    return _view(_by_id(capture_service.mark_capturing, request_id, ctx, request))


@router.post("/dms/capture/requests/{request_id}/cancel")
def cancel_by_id(request_id: int, request: Request, ctx: AuthContext = Depends(get_current_context)) -> dict:
    return _view(_by_id(capture_service.cancel, request_id, ctx, request))


@router.post("/dms/capture/requests/{request_id}/upload")
def upload_by_id(request_id: int, payload: UploadRequest, request: Request, ctx: AuthContext = Depends(get_current_context),
                 idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict:
    _limit(request, f"id{request_id}", 10)
    company_id = _company_for(ctx, request_id=request_id)
    photos = _decode(payload, request, company_id)
    try:
        view = capture_service.upload(company_id, ctx.user_id, photos, idempotency_key or "", request_id=request_id, source="APP")
    except capture_service.CaptureError as exc:
        raise _http(exc) from exc
    audit_log.record(company_id, ctx.user_id, "DmsCaptureRequest", view.request_id, "CREATE",
                     {"photos": len(photos), "document_id": view.result_document_id})
    return _view(view)


# --- اسناد ------------------------------------------------------------------------------------------------------
@router.get("/dms/documents")
def documents_for(entity_type: str, entity_id: int, ctx: AuthContext = Depends(get_current_context)) -> list[dict]:
    try:
        rows = documents_service.documents_for_entity(ctx.company_id, ctx.user_id, entity_type, entity_id)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http(exc) from exc
    return [{"document_id": r.document_id, "document_no": r.document_no, "title": r.title, "type": r.type_label,
             "status": r.status_label, "version_no": r.version_no, "file_count": r.file_count,
             "first_file_id": r.first_file_id} for r in rows]


@router.get("/dms/documents/{document_id}")
def document_detail(document_id: int, ctx: AuthContext = Depends(get_current_context)) -> dict:
    try:
        d = documents_service.get_document(ctx.company_id, ctx.user_id, document_id)
    except (LookupError, PermissionError) as exc:
        raise _http(exc) from exc
    current = next((v for v in d.versions if v.is_current), None)
    return {"document_id": d.document_id, "document_no": d.document_no, "title": d.title, "type": d.type_label,
            "status": d.status_label, "version_no": current.version_no if current else None,
            "files": [{"file_id": f.file_id, "name": f.name, "mime_type": f.mime_type, "size_bytes": f.size_bytes}
                      for f in (current.files if current else [])]}


@router.get("/dms/files/{file_id}")
def file_content(file_id: int, thumbnail: bool = False, ctx: AuthContext = Depends(get_current_context)) -> Response:
    try:
        name, mime, data = documents_service.read_file(ctx.company_id, ctx.user_id, file_id, thumbnail=thumbnail)
    except (LookupError, PermissionError) as exc:
        raise _http(exc) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc)) from exc
    inline = mime.startswith("image/") or mime == "application/pdf"
    disposition = f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(name)}"
    return Response(data, media_type=mime, headers={
        "Content-Disposition": disposition, "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
        "Content-Security-Policy": "default-src 'none'; sandbox"})
