"""عدم‌انطباق (NCR) و اقدام اصلاحی/پیشگیرانه (CAPA) با تاریخچهٔ کامل در audit.activity_log.

گردش پرونده: باز ← در حال بررسی ← در حال اقدام ← بسته (یا لغو). بستن پرونده: علت ریشه‌ای، تعیین تکلیف کالا و اثربخش‌بودن
همهٔ اقدام‌های باز لازم است؛ پرونده و اقدام بسته‌شده با تریگر پایگاه‌داده قفل است.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import func, select, text

from peecha.db.base import new_session
from peecha.db.models.audit import ActivityLog
from peecha.db.models.inventory import QcInspection, StockDocument, StockDocumentLine, Warehouse
from peecha.db.models.production import ProductionOrder
from peecha.db.models.quality import CapaAction, Nonconformance
from peecha.services import audit as audit_service
from peecha.services.qms import common as c

_ZERO = decimal.Decimal(0)
_TRANSITIONS = {"OPEN": {"INVESTIGATING", "ACTION", "CLOSED", "CANCELLED"}, "INVESTIGATING": {"ACTION", "CLOSED", "CANCELLED"},
                "ACTION": {"INVESTIGATING", "CLOSED", "CANCELLED"}}
_OPEN_ACTIONS = ("OPEN", "DONE")


@dataclass
class NcrFields:
    title: str
    source_code: str = "INTERNAL"
    severity_code: str = "MINOR"
    description: str | None = None
    item_id: int | None = None
    supplier_detail_account_id: int | None = None
    customer_detail_account_id: int | None = None
    production_order_id: int | None = None
    quantity: decimal.Decimal = _ZERO
    cause_code: str | None = None
    responsible_user_id: int | None = None
    cost_amount: decimal.Decimal = _ZERO
    disposition_code: str | None = None
    due_date: datetime.date | None = None


def _log(session, company_id: int, user_id: int | None, entity: str, entity_id: int, action: str, changes: dict) -> None:
    audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type=entity, entity_id=entity_id,
                               action=action, changes=changes)


def _next_no(session, company_id: int) -> int:
    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": 7311000000 + company_id})
    return (session.scalar(select(func.max(Nonconformance.ncr_no)).where(Nonconformance.company_id == company_id)) or 0) + 1


def _validate(f: NcrFields) -> None:
    if not (f.title or "").strip():
        raise ValueError("عنوان عدم‌انطباق الزامی است.")
    if f.source_code not in c.NCR_SOURCE_LABELS:
        raise ValueError("منبع عدم‌انطباق نامعتبر است.")
    if f.severity_code not in c.SEVERITY_LABELS:
        raise ValueError("شدت عدم‌انطباق نامعتبر است.")
    if f.cause_code and f.cause_code not in c.CAUSE_LABELS:
        raise ValueError("علت عدم‌انطباق نامعتبر است.")
    if f.disposition_code and f.disposition_code not in c.NCR_DISPOSITION_LABELS:
        raise ValueError("تعیین تکلیف نامعتبر است.")
    if decimal.Decimal(f.quantity or 0) < 0 or decimal.Decimal(f.cost_amount or 0) < 0:
        raise ValueError("مقدار و هزینه نمی‌توانند منفی باشند.")


def create_ncr(company_id: int, user_id: int, fields: NcrFields, *, qc_inspection_id: int | None = None) -> int:
    _validate(fields)
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_NCR, "CREATE", session=session)
        if qc_inspection_id is not None:
            insp = session.get(QcInspection, qc_inspection_id)
            if insp is None or insp.company_id != company_id:
                raise ValueError("بازرسی نامعتبر است.")
        row = _insert(session, company_id, user_id, fields, qc_inspection_id)
        session.commit()
        return row.ncr_id


def _insert(session, company_id: int, user_id: int, f: NcrFields, qc_inspection_id: int | None,
            stock_document_id: int | None = None) -> Nonconformance:
    row = Nonconformance(stock_document_id=stock_document_id,
        company_id=company_id, ncr_no=_next_no(session, company_id), source_code=f.source_code, qc_inspection_id=qc_inspection_id,
        item_id=f.item_id, supplier_detail_account_id=f.supplier_detail_account_id,
        customer_detail_account_id=f.customer_detail_account_id, production_order_id=f.production_order_id,
        quantity=decimal.Decimal(f.quantity or 0), severity_code=f.severity_code, title=f.title.strip(),
        description=(f.description or "").strip() or None, cause_code=f.cause_code or None,
        responsible_user_id=f.responsible_user_id, cost_amount=decimal.Decimal(f.cost_amount or 0).quantize(decimal.Decimal("0.01")),
        disposition_code=f.disposition_code or None, due_date=f.due_date, status_code="OPEN", created_by_user_id=user_id)
    session.add(row)
    session.flush()
    _log(session, company_id, user_id, "Nonconformance", row.ncr_id, "CREATE",
         {"ncr_no": row.ncr_no, "source": row.source_code, "severity": row.severity_code, "inspection": qc_inspection_id})
    return row


def auto_from_inspection(session, row: QcInspection, user_id: int) -> int | None:
    """پس از تأیید بازرسی با مقدار مردود، دوباره‌کاری یا مصرف مشروط (تنظیم «عدم‌انطباق خودکار»)؛ یک‌بار برای هر بازرسی."""
    rejected, pending, accepted = (decimal.Decimal(row.rejected_quantity or 0), decimal.Decimal(row.pending_quantity or 0),
                                   decimal.Decimal(row.accepted_quantity or 0))
    if not (rejected > 0 or row.disposition_code in ("REWORK", "CONCESSION")):
        return None
    if not c.settings(row.company_id, session).auto_ncr_on_reject:
        return None
    existing = session.scalar(select(Nonconformance.ncr_id).where(Nonconformance.qc_inspection_id == row.qc_inspection_id))
    if existing:
        return existing
    from peecha.db.models.accounting import DetailAccount
    from peecha.db.models.inventory import Item

    item_id, supplier_id, customer_id, doc_id, unit_cost = None, None, None, None, _ZERO
    if row.stock_document_line_id:
        ln = session.get(StockDocumentLine, row.stock_document_line_id)
        doc = session.get(StockDocument, ln.stock_document_id)
        item_id, doc_id, unit_cost = ln.item_id, doc.stock_document_id, decimal.Decimal(ln.unit_cost or 0)
        if row.stage_code == "RECEIPT":
            supplier_id = doc.counterparty_detail_account_id
        elif row.stage_code == "SALES_RETURN":
            customer_id = doc.counterparty_detail_account_id
    elif row.production_order_id:
        item_id = session.get(ProductionOrder, row.production_order_id).item_id
    if row.disposition_code == "REWORK":
        qty, disposition = pending + rejected, "REWORK"
    elif row.disposition_code == "CONCESSION":
        qty, disposition = accepted, "USE_AS_IS"
    else:
        qty, disposition = rejected, None
        if row.transfer_stock_document_id:
            target = session.get(Warehouse, session.get(StockDocument, row.transfer_stock_document_id).destination_warehouse_id)
            disposition = "SCRAP" if target is not None and target.warehouse_type_code == "SCRAP" else None
    lot = decimal.Decimal(row.lot_quantity or qty or 1)
    item = session.get(Item, item_id) if item_id else None
    label = (session.get(DetailAccount, item.item_detail_account_id).name or "") if item else ""
    f = NcrFields(title=f"عدم‌انطباق {c.STAGE_LABELS[row.stage_code]} — {label}".strip(" —"), source_code=row.stage_code,
                  severity_code="MAJOR" if (rejected >= lot and lot > 0) else "MINOR", item_id=item_id,
                  supplier_detail_account_id=supplier_id, customer_detail_account_id=customer_id,
                  production_order_id=row.production_order_id, quantity=qty, cost_amount=(qty * unit_cost) if unit_cost else _ZERO,
                  disposition_code=disposition, description=row.notes)
    return _insert(session, row.company_id, user_id, f, row.qc_inspection_id, doc_id).ncr_id


def _lock(session, company_id: int, ncr_id: int) -> Nonconformance:
    row = session.scalar(select(Nonconformance).where(Nonconformance.ncr_id == ncr_id).with_for_update())
    if row is None or row.company_id != company_id:
        raise ValueError("پروندهٔ عدم‌انطباق نامعتبر است.")
    if row.status_code in ("CLOSED", "CANCELLED"):
        raise ValueError("پروندهٔ بسته یا لغوشده قابل تغییر نیست.")
    return row


_UPDATABLE = {"title", "description", "severity_code", "cause_code", "root_cause_method", "root_cause_details", "root_cause",
              "responsible_user_id", "cost_amount", "disposition_code", "due_date", "quantity"}


def update_ncr(company_id: int, user_id: int, ncr_id: int, **values) -> None:
    unknown = set(values) - _UPDATABLE
    if unknown:
        raise ValueError(f"فیلد ناشناخته: {', '.join(sorted(unknown))}")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_NCR, session=session)
        row = _lock(session, company_id, ncr_id)
        probe = NcrFields(title=values.get("title", row.title), source_code=row.source_code,
                          severity_code=values.get("severity_code", row.severity_code),
                          cause_code=values.get("cause_code", row.cause_code),
                          disposition_code=values.get("disposition_code", row.disposition_code),
                          quantity=values.get("quantity", row.quantity), cost_amount=values.get("cost_amount", row.cost_amount))
        _validate(probe)
        method = values.get("root_cause_method", row.root_cause_method)
        if method and method not in c.ROOT_CAUSE_METHOD_LABELS:
            raise ValueError("روش تحلیل علت ریشه‌ای نامعتبر است.")
        details = values.get("root_cause_details")
        if details is not None:
            if method == "FIVE_WHY" and not (isinstance(details, list) and all(isinstance(x, str) for x in details) and len(details) <= 5):
                raise ValueError("پنج چرا فهرستی از حداکثر پنج پاسخ متنی است.")
            if method == "FISHBONE" and not (isinstance(details, dict) and set(details) <= set(c.CAUSE_LABELS)):
                raise ValueError("استخوان ماهی باید بر اساس عامل‌های تعریف‌شده باشد.")
        changes = {}
        for k, v in values.items():
            if k in ("cost_amount", "quantity"):
                v = decimal.Decimal(v or 0)
            old = getattr(row, k)
            if old != v:
                changes[k] = [str(old) if old is not None else None, str(v) if v is not None else None]
                setattr(row, k, v)
        if changes:
            _log(session, company_id, user_id, "Nonconformance", ncr_id, "UPDATE", changes)
        session.commit()


def set_status(company_id: int, user_id: int, ncr_id: int, status: str, note: str | None = None) -> None:
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_NCR, session=session)
        row = _lock(session, company_id, ncr_id)
        if status not in _TRANSITIONS.get(row.status_code, set()):
            raise ValueError(f"تغییر وضعیت از «{c.NCR_STATUS_LABELS[row.status_code]}» به «{c.NCR_STATUS_LABELS.get(status, status)}» مجاز نیست.")
        if status == "CANCELLED" and not (note or "").strip():
            raise ValueError("علت لغو پرونده الزامی است.")
        if status == "CLOSED":
            _check_closable(session, row)
        before = row.status_code
        row.status_code = status
        if status in ("CLOSED", "CANCELLED"):
            row.closed_at, row.closed_by_user_id = datetime.datetime.now(datetime.timezone.utc), user_id
        _log(session, company_id, user_id, "Nonconformance", ncr_id,
             {"CLOSED": "RESOLVE", "CANCELLED": "CANCEL"}.get(status, "UPDATE"),
             {"status": [before, status], "note": (note or "").strip() or None})
        session.commit()


def _check_closable(session, row: Nonconformance) -> None:
    if not (row.root_cause or "").strip():
        raise ValueError("پیش از بستن پرونده، علت ریشه‌ای را ثبت کنید.")
    if not row.disposition_code:
        raise ValueError("پیش از بستن پرونده، تعیین تکلیف کالا را مشخص کنید.")
    actions = list(session.scalars(select(CapaAction).where(CapaAction.ncr_id == row.ncr_id)))
    if any(a.status_code in _OPEN_ACTIONS for a in actions):
        raise ValueError("اقدام‌های باز یا بررسی‌نشدهٔ این پرونده هنوز اثربخشی‌شان تأیید نشده است.")
    if row.severity_code in ("MAJOR", "CRITICAL") and not any(
            a.action_type == "CORRECTIVE" and a.status_code == "VERIFIED" for a in actions):
        raise ValueError("عدم‌انطباق عمده یا بحرانی بدون اقدام اصلاحی اثربخش بسته نمی‌شود.")


# --- اقدام اصلاحی/پیشگیرانه ----------------------------------------------------------------------
def add_action(company_id: int, user_id: int, ncr_id: int, action_type: str, description: str,
               owner_user_id: int | None = None, due_date: datetime.date | None = None) -> int:
    if action_type not in c.CAPA_TYPE_LABELS:
        raise ValueError("نوع اقدام نامعتبر است.")
    if not (description or "").strip():
        raise ValueError("شرح اقدام الزامی است.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_NCR, "CREATE", session=session)
        ncr = _lock(session, company_id, ncr_id)
        act = CapaAction(company_id=company_id, ncr_id=ncr_id, action_type=action_type, description=description.strip(),
                         owner_user_id=owner_user_id, due_date=due_date, status_code="OPEN", created_by_user_id=user_id)
        session.add(act)
        session.flush()
        if ncr.status_code in ("OPEN", "INVESTIGATING"):
            before = ncr.status_code
            ncr.status_code = "ACTION"
            _log(session, company_id, user_id, "Nonconformance", ncr_id, "UPDATE", {"status": [before, "ACTION"]})
        _log(session, company_id, user_id, "CapaAction", act.action_id, "CREATE",
             {"ncr_id": ncr_id, "type": action_type, "owner": owner_user_id, "due": due_date.isoformat() if due_date else None})
        session.commit()
        return act.action_id


def _lock_action(session, company_id: int, action_id: int) -> tuple[CapaAction, Nonconformance]:
    act = session.scalar(select(CapaAction).where(CapaAction.action_id == action_id).with_for_update())
    if act is None or act.company_id != company_id:
        raise ValueError("اقدام نامعتبر است.")
    ncr = session.get(Nonconformance, act.ncr_id)
    if ncr.status_code in ("CLOSED", "CANCELLED"):
        raise ValueError("پروندهٔ این اقدام بسته شده است.")
    return act, ncr


def complete_action(company_id: int, user_id: int, action_id: int, evidence: str) -> None:
    if not (evidence or "").strip():
        raise ValueError("شواهد انجام اقدام را ثبت کنید.")
    with new_session() as session:
        act, _ncr = _lock_action(session, company_id, action_id)
        if act.owner_user_id != user_id:
            c.require(company_id, user_id, c.FORM_NCR, session=session)
        if act.status_code != "OPEN":
            raise ValueError("فقط اقدام باز انجام‌شده ثبت می‌شود.")
        act.status_code, act.evidence = "DONE", evidence.strip()
        act.completed_at, act.completed_by_user_id = datetime.datetime.now(datetime.timezone.utc), user_id
        _log(session, company_id, user_id, "CapaAction", action_id, "COMPLETE", {"status": ["OPEN", "DONE"]})
        session.commit()


def verify_action(company_id: int, user_id: int, action_id: int, effective: bool, note: str | None = None) -> None:
    """بررسی اثربخشی؛ بی‌اثر = پرونده باز می‌ماند و اقدام تازه لازم است."""
    from peecha.services import stock_controls

    with new_session() as session:
        c.require(company_id, user_id, c.FORM_NCR, session=session)
        act, _ncr = _lock_action(session, company_id, action_id)
        if act.status_code != "DONE":
            raise ValueError("اثربخشی فقط برای اقدام انجام‌شده بررسی می‌شود.")
        if act.completed_by_user_id == user_id and stock_controls.is_on(company_id, stock_controls.QC_SEPARATE_APPROVAL, session):
            raise ValueError("انجام‌دهندهٔ اقدام نمی‌تواند اثربخشی آن را تأیید کند.")
        if not effective and not (note or "").strip():
            raise ValueError("دلیل بی‌اثر بودن اقدام را بنویسید.")
        status = "VERIFIED" if effective else "INEFFECTIVE"
        act.status_code, act.effectiveness_note = status, (note or "").strip() or None
        act.verified_at, act.verified_by_user_id = datetime.datetime.now(datetime.timezone.utc), user_id
        _log(session, company_id, user_id, "CapaAction", action_id, "APPROVE" if effective else "REJECT",
             {"status": ["DONE", status], "note": act.effectiveness_note})
        session.commit()


def cancel_action(company_id: int, user_id: int, action_id: int, reason: str) -> None:
    if not (reason or "").strip():
        raise ValueError("علت لغو اقدام الزامی است.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_NCR, session=session)
        act, _ncr = _lock_action(session, company_id, action_id)
        if act.status_code not in _OPEN_ACTIONS:
            raise ValueError("این اقدام دیگر قابل لغو نیست.")
        before = act.status_code
        act.status_code, act.effectiveness_note = "CANCELLED", reason.strip()
        _log(session, company_id, user_id, "CapaAction", action_id, "CANCEL", {"status": [before, "CANCELLED"], "reason": reason.strip()})
        session.commit()


# --- خواندن ----------------------------------------------------------------------------------------
def list_ncrs(company_id: int, status: str | None = None, open_only: bool = False) -> list[SimpleNamespace]:
    from peecha.services.qms import labels

    today = datetime.date.today()
    with new_session() as session:
        q = select(Nonconformance).where(Nonconformance.company_id == company_id)
        if status:
            q = q.where(Nonconformance.status_code == status)
        if open_only:
            q = q.where(Nonconformance.status_code.not_in(("CLOSED", "CANCELLED")))
        rows = list(session.scalars(q.order_by(Nonconformance.ncr_no.desc())))
        acts: dict[int, list] = {}
        for a in session.scalars(select(CapaAction).where(CapaAction.ncr_id.in_([r.ncr_id for r in rows] or [-1]))):
            acts.setdefault(a.ncr_id, []).append(a)
        names = labels.Names(session)
        out = []
        for r in rows:
            mine = acts.get(r.ncr_id, [])
            out.append(SimpleNamespace(
                ncr_id=r.ncr_id, ncr_no=r.ncr_no, title=r.title, source_code=r.source_code, source_label=c.NCR_SOURCE_LABELS[r.source_code],
                severity_code=r.severity_code, severity_label=c.SEVERITY_LABELS[r.severity_code], status_code=r.status_code,
                status_label=c.NCR_STATUS_LABELS[r.status_code], item_label=names.item(r.item_id),
                party_label=names.party(r.supplier_detail_account_id or r.customer_detail_account_id), quantity=r.quantity,
                cost_amount=r.cost_amount, responsible=names.user(r.responsible_user_id), detected_at=r.detected_at,
                due_date=r.due_date, overdue=bool(r.due_date and r.due_date < today and r.status_code not in ("CLOSED", "CANCELLED")),
                cause_label=c.CAUSE_LABELS.get(r.cause_code or "", ""), qc_inspection_id=r.qc_inspection_id,
                actions=len(mine), open_actions=sum(1 for a in mine if a.status_code in _OPEN_ACTIONS)))
        return out


def get_ncr(company_id: int, ncr_id: int) -> SimpleNamespace:
    with new_session() as session:
        row = session.get(Nonconformance, ncr_id)
        if row is None or row.company_id != company_id:
            raise ValueError("پروندهٔ عدم‌انطباق نامعتبر است.")
        actions = list(session.scalars(select(CapaAction).where(CapaAction.ncr_id == ncr_id).order_by(CapaAction.action_id)))
        for a in actions:
            session.expunge(a)
        session.expunge(row)
    return SimpleNamespace(ncr=row, actions=actions, history=history("Nonconformance", ncr_id)
                           + [h for a in actions for h in history("CapaAction", a.action_id)])


def list_actions(company_id: int, open_only: bool = True) -> list[SimpleNamespace]:
    from peecha.services.qms import labels

    today = datetime.date.today()
    with new_session() as session:
        q = select(CapaAction, Nonconformance).join(Nonconformance, Nonconformance.ncr_id == CapaAction.ncr_id).where(
            CapaAction.company_id == company_id)
        if open_only:
            q = q.where(CapaAction.status_code.in_(_OPEN_ACTIONS))
        names = labels.Names(session)
        return [SimpleNamespace(action_id=a.action_id, ncr_id=n.ncr_id, ncr_no=n.ncr_no, ncr_title=n.title,
                                type_label=c.CAPA_TYPE_LABELS[a.action_type], action_type=a.action_type, description=a.description,
                                owner=names.user(a.owner_user_id), owner_user_id=a.owner_user_id, due_date=a.due_date,
                                status_code=a.status_code, status_label=c.CAPA_STATUS_LABELS[a.status_code], evidence=a.evidence,
                                overdue_days=(today - a.due_date).days if a.due_date and a.due_date < today
                                and a.status_code in _OPEN_ACTIONS else 0,
                                completed_by_user_id=a.completed_by_user_id)
                for a, n in session.execute(q.order_by(CapaAction.due_date.nulls_last(), CapaAction.action_id)).all()]


def history(entity_type: str, entity_id: int) -> list[SimpleNamespace]:
    """تاریخچهٔ تغییر وضعیت، تصمیم و تأیید از ردپای ممیزی."""
    from peecha.db.models.security import User

    with new_session() as session:
        rows = session.execute(select(ActivityLog, User.full_name).outerjoin(User, User.user_id == ActivityLog.user_id).where(
            ActivityLog.entity_type == entity_type, ActivityLog.entity_id == entity_id).order_by(ActivityLog.log_id)).all()
        return [SimpleNamespace(at=log.created_at, user=name or "", action=log.action, entity_type=entity_type,
                                entity_id=entity_id, changes=log.changes or {}) for log, name in rows]
