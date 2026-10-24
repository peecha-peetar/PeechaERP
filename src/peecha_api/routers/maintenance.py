"""نگهداری و تعمیرات برای موبایل تکنسین — R312: اسکن برچسب تجهیز، ثبت سریع درخواست، کارهای من، چک‌لیست و ثبت انجام.

نازک: همهٔ منطق در services/maintenance؛ دسترسی با RBAC موجود (فرم‌های صفحه‌های نگهداری) و گام‌ها با کلید
«دسترسی‌های جداگانهٔ نگهداری» در خود سرویس.
"""

from __future__ import annotations

import base64
import datetime
import decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from peecha.services.maintenance import common as mc
from peecha.services.maintenance import documents as mdocs
from peecha.services.maintenance import equipment as eq
from peecha.services.maintenance import requests as mreq
from peecha.services.maintenance import work_orders as wos
from peecha_api.deps import AuthContext, get_idempotency_key
from peecha_api.idempotency import IdempotentReplay, run_idempotent
from peecha_api.permissions import require_permission

router = APIRouter(prefix="/maintenance", tags=["maintenance"])
_EQUIP = Depends(require_permission("mnt_equipment", "VIEW"))
_REQUEST = Depends(require_permission("mnt_requests", "CREATE"))
_WORK_VIEW = Depends(require_permission("mnt_work_orders", "VIEW"))
_WORK = Depends(require_permission("mnt_work_orders", "EDIT"))
_KEY = Depends(get_idempotency_key)


def _bad(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _iso(v):
    return v.isoformat() if isinstance(v, (datetime.date, datetime.datetime)) else v


def _num(v):
    return None if v is None else str(v)


@router.get("/equipment/lookup")
def lookup(code: str, ctx: AuthContext = _EQUIP) -> dict:
    """اسکن QR یا بارکد ← کارت خلاصهٔ تجهیز (برای ثبت درخواست یا دیدن کارهای باز)."""
    asset_id = eq.find(ctx.company_id, code)
    if asset_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="تجهیز یافت نشد.")
    k = eq.card(ctx.company_id, asset_id)
    return {"asset_id": k.asset_id, "code": k.code, "name": k.name, "serial_no": k.serial_no, "manufacturer": k.manufacturer,
            "model": k.model, "location": k.location, "line": k.line, "status_label": k.status_label,
            "criticality_label": k.criticality_label, "down_now": k.down_now, "down_since": _iso(k.down_since),
            "safety_notes": k.safety_notes, "open_requests": k.open_requests,
            "open_work_orders": [{"work_order_id": w.work_order_id, "wo_no": w.wo_no, "title": w.title, "status_label": w.status_label}
                                 for w in k.work_orders if w.status_code in mc.OPEN_WO]}


class RequestIn(BaseModel):
    asset_id: int | None = None
    code: str | None = None
    title: str
    description: str | None = None
    machine_stopped: bool = False
    severity_code: str = "MEDIUM"
    probable_cause: str | None = None
    failure_at: datetime.datetime | None = None
    scanned: bool = False


@router.post("/requests", status_code=status.HTTP_201_CREATED)
def create_request(body: RequestIn, ctx: AuthContext = _REQUEST, idempotency_key: str | None = _KEY) -> dict:
    """ثبت سریع درخواست تعمیر؛ «ماشین متوقف است» همان لحظه توقف و کسر ظرفیت را ثبت می‌کند."""
    def compute():
        asset_id = body.asset_id or (eq.find(ctx.company_id, body.code) if body.code else None)
        if asset_id is None:
            raise ValueError("تجهیز مشخص نیست؛ برچسب را اسکن کنید یا تجهیز را انتخاب کنید.")
        return mreq.create(ctx.company_id, ctx.user_id, asset_id, body.title, body.description, failure_at=body.failure_at,
                           machine_stopped=body.machine_stopped, severity_code=body.severity_code,
                           probable_cause=body.probable_cause, source_code="QR" if body.scanned else "MOBILE",
                           idempotency_key=f"API:{idempotency_key}" if idempotency_key else None)

    try:
        return run_idempotent(idempotency_key, "mnt_request", ctx.user_id, ctx.company_id, status.HTTP_201_CREATED, compute,
                              lambda rid: {"request_id": rid, "request_no": mreq.get(ctx.company_id, rid).request_no})
    except IdempotentReplay as replay:
        return replay.body
    except ValueError as exc:
        raise _bad(exc) from exc


class PhotoIn(BaseModel):
    file_name: str
    content_base64: str


@router.post("/requests/{request_id}/photos", status_code=status.HTTP_201_CREATED)
def add_photo(request_id: int, body: PhotoIn, ctx: AuthContext = _REQUEST) -> dict:
    try:
        content = base64.b64decode(body.content_base64, validate=True)
        return {"attachment_id": mdocs.add(ctx.company_id, ctx.user_id, "REQUEST", request_id, None, "IMAGE", content=content,
                                           file_name=body.file_name)}
    except (ValueError, base64.binascii.Error) as exc:
        raise _bad(ValueError(str(exc) or "فایل نامعتبر است.")) from exc


def _wo_row(r) -> dict:
    return {"work_order_id": r.work_order_id, "wo_no": r.wo_no, "asset_label": r.asset_label, "title": r.title,
            "work_type_label": r.work_type_label, "priority_code": r.priority_code, "priority_label": r.priority_label,
            "status_code": r.status_code, "status_label": r.status_label, "planned_start": _iso(r.planned_start),
            "requires_shutdown": r.requires_shutdown}


@router.get("/my-work-orders")
def my_work(ctx: AuthContext = _WORK_VIEW) -> list[dict]:
    """دستورهای باز واگذارشده به من یا به مسئولیت من (فوری‌ها اول)."""
    return [_wo_row(r) for r in wos.my_work(ctx.company_id, ctx.user_id)]


@router.get("/work-orders/{work_order_id}")
def work_order(work_order_id: int, ctx: AuthContext = _WORK_VIEW) -> dict:
    try:
        d = wos.get(ctx.company_id, work_order_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {**_wo_row(d), "description": d.description, "safety_instructions": d.safety_instructions,
            "required_skills": d.required_skills, "hold_reason": d.hold_reason, "completion_note": d.completion_note,
            "verification_label": d.verification_label, "machine_down": any(x.is_open for x in d.downtime),
            "tasks": [{"task_id": t.task_id, "seq": t.seq, "description": t.description, "result_type": t.result_type,
                       "min_value": _num(t.min_value), "max_value": _num(t.max_value), "uom_label": t.uom_label,
                       "is_mandatory": t.is_mandatory, "is_safety": t.is_safety, "is_done": t.is_done,
                       "value_numeric": _num(t.value_numeric), "value_text": t.value_text, "is_ok": t.is_ok} for t in d.tasks],
            "parts": [{"item": f"{p.item_code} — {p.item_name}", "planned": _num(p.planned_qty), "issued": _num(p.net_qty)}
                      for p in d.parts]}


def _act(fn, *args, **kwargs) -> dict:
    try:
        fn(*args, **kwargs)
    except ValueError as exc:
        raise _bad(exc) from exc
    return {"ok": True}


@router.post("/work-orders/{work_order_id}/start")
def start(work_order_id: int, ctx: AuthContext = _WORK) -> dict:
    return _act(wos.start, ctx.company_id, ctx.user_id, work_order_id)


class ReasonIn(BaseModel):
    reason: str


@router.post("/work-orders/{work_order_id}/hold")
def hold(work_order_id: int, body: ReasonIn, ctx: AuthContext = _WORK) -> dict:
    return _act(wos.hold, ctx.company_id, ctx.user_id, work_order_id, body.reason)


@router.post("/work-orders/{work_order_id}/resume")
def resume(work_order_id: int, ctx: AuthContext = _WORK) -> dict:
    return _act(wos.resume, ctx.company_id, ctx.user_id, work_order_id)


class TaskIn(BaseModel):
    done: bool = True
    value_numeric: decimal.Decimal | None = None
    value_text: str | None = None


@router.post("/tasks/{task_id}")
def record_task(task_id: int, body: TaskIn, ctx: AuthContext = _WORK) -> dict:
    try:
        ok = wos.record_task(ctx.company_id, ctx.user_id, task_id, body.done, body.value_numeric, body.value_text)
    except ValueError as exc:
        raise _bad(exc) from exc
    return {"ok": True, "is_ok": ok}


class LaborIn(BaseModel):
    hours: decimal.Decimal
    work_date: datetime.date | None = None
    note: str | None = None


@router.post("/work-orders/{work_order_id}/labor")
def labor(work_order_id: int, body: LaborIn, ctx: AuthContext = _WORK, idempotency_key: str | None = _KEY) -> dict:
    return _act(wos.add_labor, ctx.company_id, ctx.user_id, work_order_id, ctx.user_id, body.work_date or datetime.date.today(),
                body.hours, body.note, idempotency_key=idempotency_key)


class CompleteIn(BaseModel):
    note: str


@router.post("/work-orders/{work_order_id}/complete")
def complete(work_order_id: int, body: CompleteIn, ctx: AuthContext = _WORK) -> dict:
    """ثبت «انجام‌شده»؛ ماشین تا آزمون و ثبت آماده‌به‌کاری در دسکتاپ، هنوز در دسترس تولید نیست."""
    return _act(wos.complete, ctx.company_id, ctx.user_id, work_order_id, body.note)
