"""درخواست تعمیر (R312): ثبت (رومیزی/موبایل/اسکن برچسب) ← بررسی و اولویت ← ارجاع ← تأیید/رد ← تبدیل به دستور کار.

درخواستی که «ماشین متوقف است» دارد همان لحظه توقف را شروع می‌کند (availability.start) تا ظرفیت تولید فوراً کم شود.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.audit import ActivityLog
from peecha.db.models.fixed_assets import Asset
from peecha.db.models.maintenance import DowntimeEvent, WorkOrder, WorkRequest
from peecha.services.fixed_assets.common import CLOSED_STATUSES
from peecha.services.maintenance import availability
from peecha.services.maintenance import common as c
from peecha.services.maintenance import work_orders as wos

ENTITY = "MntWorkRequest"
_OPEN = ("NEW", "UNDER_REVIEW", "APPROVED")


def _lock(session, company_id: int, request_id: int) -> WorkRequest:
    row = session.scalar(select(WorkRequest).where(WorkRequest.request_id == request_id).with_for_update())
    if row is None or row.company_id != company_id:
        raise ValueError("درخواست تعمیر نامعتبر است.")
    return row


def _status(session, req: WorkRequest, user_id: int | None, status: str, operation: str, **changes) -> None:
    previous = req.status_code
    req.status_code = status
    session.flush()
    c.audit(session, req.company_id, user_id, ENTITY, req.request_id, operation, {"status_code": [previous, status], **changes})


def create(company_id: int, user_id: int, asset_id: int, title: str, description: str | None = None, *,
           failure_at: datetime.datetime | None = None, machine_stopped: bool = False, severity_code: str = "MEDIUM",
           probable_cause: str | None = None, suggested_work_type: str | None = None, source_code: str = "DESKTOP",
           idempotency_key: str | None = None) -> int:
    if not (title or "").strip():
        raise ValueError("شرح کوتاه خرابی الزامی است.")
    if severity_code not in c.SEVERITY_LABELS:
        raise ValueError("شدت نامعتبر است.")
    if suggested_work_type is not None and suggested_work_type not in c.WORK_TYPE_LABELS:
        raise ValueError("نوع کار پیشنهادی نامعتبر است.")
    if source_code not in c.SOURCE_LABELS:
        raise ValueError("منبع ثبت نامعتبر است.")
    failure_at = c.aware(failure_at)
    if failure_at is not None and failure_at > c.now() + datetime.timedelta(minutes=5):
        raise ValueError("زمان وقوع خرابی نمی‌تواند در آینده باشد.")
    with new_session() as session:
        if idempotency_key:
            done = session.scalar(select(WorkRequest.request_id).where(WorkRequest.company_id == company_id,
                                                                       WorkRequest.idempotency_key == idempotency_key))
            if done:
                return done
        c.require(company_id, user_id, c.FORM_REQUEST, "CREATE", session=session)
        asset = c.asset_of(session, company_id, asset_id)
        if asset.status_code in CLOSED_STATUSES:
            raise ValueError("این تجهیز واگذار شده و درخواست تعمیر نمی‌پذیرد.")
        req = WorkRequest(company_id=company_id, request_no=c.next_no(session, WorkRequest, WorkRequest.request_no, company_id),
                          asset_id=asset_id, title=title.strip()[:200], description=(description or "").strip()[:2000] or None,
                          failure_at=failure_at, reported_at=c.now(), reported_by_user_id=user_id,
                          machine_stopped=machine_stopped, severity_code=severity_code,
                          probable_cause=(probable_cause or "").strip()[:500] or None, suggested_work_type=suggested_work_type,
                          status_code="NEW", source_code=source_code, idempotency_key=idempotency_key)
        session.add(req)
        session.flush()
        c.audit(session, company_id, user_id, ENTITY, req.request_id, "CREATE",
                {"request_no": req.request_no, "asset_id": asset_id, "status_code": [None, "NEW"],
                 "machine_stopped": machine_stopped, "severity": severity_code, "source": source_code})
        if machine_stopped:
            availability.start(session, company_id, user_id, asset_id, failure_at or c.now(), "BREAKDOWN",
                               request_id=req.request_id, note=title.strip()[:300])
        session.commit()
        return req.request_id


def evaluate(company_id: int, user_id: int, request_id: int, priority_code: str, severity_code: str | None = None,
             suggested_work_type: str | None = None, note: str | None = None) -> None:
    """ارزیابی و اولویت‌بندی."""
    if priority_code not in c.PRIORITY_LABELS:
        raise ValueError("اولویت نامعتبر است.")
    if severity_code is not None and severity_code not in c.SEVERITY_LABELS:
        raise ValueError("شدت نامعتبر است.")
    if suggested_work_type is not None and suggested_work_type not in c.WORK_TYPE_LABELS:
        raise ValueError("نوع کار نامعتبر است.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_PLAN, session=session)
        req = _lock(session, company_id, request_id)
        if req.status_code not in ("NEW", "UNDER_REVIEW"):
            raise ValueError(f"درخواست در وضعیت «{c.REQUEST_STATUS_LABELS[req.status_code]}» است.")
        changes = {"priority": [req.priority_code, priority_code]}
        req.priority_code = priority_code
        if severity_code:
            changes["severity"] = [req.severity_code, severity_code]
            req.severity_code = severity_code
        if suggested_work_type:
            req.suggested_work_type = suggested_work_type
        req.evaluated_by_user_id, req.evaluated_at = user_id, c.now()
        if note:
            req.decision_note = note.strip()[:500]
        _status(session, req, user_id, "UNDER_REVIEW", "EVALUATE", note=note, **changes)
        session.commit()


def refer(company_id: int, user_id: int, request_id: int, to_user_id: int, note: str) -> None:
    if not (note or "").strip():
        raise ValueError("علت ارجاع را بنویسید.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_PLAN, session=session)
        req = _lock(session, company_id, request_id)
        if req.status_code not in _OPEN:
            raise ValueError(f"درخواست در وضعیت «{c.REQUEST_STATUS_LABELS[req.status_code]}» است.")
        old = req.assigned_to_user_id
        req.assigned_to_user_id, req.decision_note = to_user_id, note.strip()[:500]
        _status(session, req, user_id, "UNDER_REVIEW" if req.status_code == "NEW" else req.status_code, "REFER",
                assigned_to=[old, to_user_id], note=note.strip())
        session.commit()


def approve(company_id: int, user_id: int, request_id: int, priority_code: str | None = None, note: str | None = None) -> None:
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_PLAN, session=session)
        req = _lock(session, company_id, request_id)
        _approve(session, req, user_id, priority_code, note)
        session.commit()


def _approve(session, req: WorkRequest, user_id: int, priority_code: str | None, note: str | None) -> None:
    if req.status_code not in ("NEW", "UNDER_REVIEW"):
        raise ValueError(f"درخواست در وضعیت «{c.REQUEST_STATUS_LABELS[req.status_code]}» است و تأیید نمی‌شود.")
    if priority_code is not None:
        if priority_code not in c.PRIORITY_LABELS:
            raise ValueError("اولویت نامعتبر است.")
        req.priority_code = priority_code
    req.priority_code = req.priority_code or ("URGENT" if req.severity_code == "CRITICAL" else "NORMAL")
    req.approved_by_user_id, req.approved_at = user_id, c.now()
    if note:
        req.decision_note = note.strip()[:500]
    _status(session, req, user_id, "APPROVED", "APPROVE", priority=req.priority_code, note=note)


def _open_downtime(session, req: WorkRequest) -> DowntimeEvent | None:
    return session.scalar(select(DowntimeEvent).where(DowntimeEvent.request_id == req.request_id,
                                                      DowntimeEvent.available_at.is_(None)))


def reject(company_id: int, user_id: int, request_id: int, reason: str) -> None:
    _close(company_id, user_id, request_id, reason, "REJECTED", "REJECT", c.FORM_PLAN)


def cancel(company_id: int, user_id: int, request_id: int, reason: str) -> None:
    """لغو توسط ثبت‌کننده یا برنامه‌ریز."""
    with new_session() as session:
        req = session.get(WorkRequest, request_id)
        own = req is not None and req.reported_by_user_id == user_id
    _close(company_id, user_id, request_id, reason, "CANCELLED", "CANCEL", c.FORM_REQUEST if own else c.FORM_PLAN)


def _close(company_id: int, user_id: int, request_id: int, reason: str, status: str, operation: str, form: str) -> None:
    if not (reason or "").strip():
        raise ValueError("علت را بنویسید.")
    with new_session() as session:
        c.require(company_id, user_id, form, session=session)
        req = _lock(session, company_id, request_id)
        if req.status_code not in _OPEN:
            raise ValueError(f"درخواست در وضعیت «{c.REQUEST_STATUS_LABELS[req.status_code]}» است.")
        if _open_downtime(session, req) is not None:
            raise ValueError("ماشین این درخواست متوقف ثبت شده است؛ رد یا لغو درخواست به معنای آماده‌بودن ماشین نیست. "
                             "ابتدا آماده‌به‌کاری را با علت ثبت کنید یا درخواست را به دستور کار تبدیل کنید.")
        req.decision_note = reason.strip()[:500]
        _status(session, req, user_id, status, operation, reason=reason.strip())
        session.commit()


def convert(company_id: int, user_id: int, request_id: int, data: wos.WorkOrderInput | None = None) -> int:
    """تبدیل به دستور کار؛ درخواست تأییدنشده با همین اقدام تأیید هم ثبت می‌شود (همان کاربر، در تاریخچه)."""
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_PLAN, session=session)
        req = _lock(session, company_id, request_id)
        if req.status_code == "CONVERTED":
            done = session.scalar(select(WorkOrder.work_order_id).where(WorkOrder.request_id == request_id))
            if done:
                return done
        if req.status_code in ("NEW", "UNDER_REVIEW"):
            _approve(session, req, user_id, None, None)
        if req.status_code != "APPROVED":
            raise ValueError(f"درخواست در وضعیت «{c.REQUEST_STATUS_LABELS[req.status_code]}» است و تبدیل نمی‌شود.")
        if data is None:
            data = wos.WorkOrderInput(asset_id=req.asset_id, work_type_code=req.suggested_work_type or (
                "EMERGENCY" if req.machine_stopped and req.severity_code in ("HIGH", "CRITICAL") else "CORRECTIVE"),
                title=req.title, description=req.description, priority_code=req.priority_code or "NORMAL")
        if data.asset_id != req.asset_id:
            raise ValueError("تجهیز دستور کار باید همان تجهیز درخواست باشد.")
        data.machine_stopped = False   # توقف درخواست به دستور کار منتقل می‌شود، نه توقف تازه
        wo = wos.create_in_session(session, company_id, user_id, data, request_id=request_id)
        ev = _open_downtime(session, req)
        if ev is not None:
            ev.work_order_id = wo.work_order_id
        _status(session, req, user_id, "CONVERTED", "CONVERT", work_order_id=wo.work_order_id, wo_no=wo.wo_no)
        session.commit()
        return wo.work_order_id


def queue(company_id: int, *, statuses: tuple[str, ...] | None = None, asset_id: int | None = None,
          assigned_to_user_id: int | None = None, reported_by_user_id: int | None = None, search: str | None = None,
          limit: int = 500) -> list[SimpleNamespace]:
    with new_session() as session:
        q = select(WorkRequest, Asset).join(Asset, Asset.asset_id == WorkRequest.asset_id).where(
            WorkRequest.company_id == company_id, WorkRequest.status_code.in_(statuses or _OPEN))
        if asset_id:
            q = q.where(WorkRequest.asset_id == asset_id)
        if assigned_to_user_id:
            q = q.where(WorkRequest.assigned_to_user_id == assigned_to_user_id)
        if reported_by_user_id:
            q = q.where(WorkRequest.reported_by_user_id == reported_by_user_id)
        if search:
            like = f"%{search.strip()}%"
            q = q.where(WorkRequest.title.ilike(like) | Asset.asset_code.ilike(like) | Asset.name.ilike(like))
        rows = session.execute(q.order_by(WorkRequest.request_no.desc()).limit(limit)).all()
        names = c.user_names(session, [r.reported_by_user_id for r, _a in rows] + [r.assigned_to_user_id for r, _a in rows])
        stopped = set(session.scalars(select(DowntimeEvent.request_id).where(
            DowntimeEvent.request_id.in_([r.request_id for r, _a in rows] or [-1]), DowntimeEvent.available_at.is_(None))))
        wo_of = dict(session.execute(select(WorkOrder.request_id, WorkOrder.work_order_id).where(
            WorkOrder.request_id.in_([r.request_id for r, _a in rows] or [-1]))).all())
        return [SimpleNamespace(
            request_id=r.request_id, request_no=r.request_no, asset_id=a.asset_id, asset_label=c.asset_label(a), title=r.title,
            description=r.description, failure_at=r.failure_at, reported_at=r.reported_at,
            reported_by=names.get(r.reported_by_user_id, ""), reported_by_user_id=r.reported_by_user_id,
            machine_stopped=r.machine_stopped, machine_down_now=r.request_id in stopped, severity_code=r.severity_code,
            severity_label=c.SEVERITY_LABELS[r.severity_code], priority_code=r.priority_code,
            priority_label=c.PRIORITY_LABELS.get(r.priority_code, "تعیین‌نشده"), status_code=r.status_code,
            status_label=c.REQUEST_STATUS_LABELS[r.status_code], probable_cause=r.probable_cause,
            suggested_work_type=r.suggested_work_type, source_label=c.SOURCE_LABELS[r.source_code],
            assigned_to=names.get(r.assigned_to_user_id, ""), decision_note=r.decision_note,
            work_order_id=wo_of.get(r.request_id)) for r, a in rows]


def get(company_id: int, request_id: int) -> SimpleNamespace:
    rows = [r for r in queue(company_id, statuses=tuple(c.REQUEST_STATUS_LABELS)) if r.request_id == request_id]
    if not rows:
        raise ValueError("درخواست تعمیر نامعتبر است.")
    return rows[0]


def history(company_id: int, request_id: int) -> list[SimpleNamespace]:
    with new_session() as session:
        rows = list(session.scalars(select(ActivityLog).where(ActivityLog.company_id == company_id, ActivityLog.entity_type == ENTITY,
                                                              ActivityLog.entity_id == request_id).order_by(ActivityLog.log_id)))
        names = c.user_names(session, [r.user_id for r in rows])
        out = []
        for r in rows:
            ch = dict(r.changes or {})
            status = ch.get("status_code")
            out.append(SimpleNamespace(at=r.created_at, user=names.get(r.user_id, ""), operation=ch.pop("operation", r.action),
                                       to_status=c.REQUEST_STATUS_LABELS.get(status[1], "") if isinstance(status, list) else "",
                                       note=ch.get("reason") or ch.get("note") or "", changes=ch))
        return out
