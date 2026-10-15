"""تجهیز (R312) = همان دارایی ثابت. این‌جا فقط مشخصات نگهداری (اهمیت، مشخصات فنی، مسئول، شمارنده) روی همان
دارایی ذخیره می‌شود؛ کد، نام، سریال، سازنده، مدل، محل، تامین‌کننده و ضمانت همیشه از خود دارایی خوانده می‌شود.

سلسله‌مراتب: سایت › کارخانه › ناحیه › خط (محل‌های درختی دارایی) › ماشین › زیرتجهیز (دارایی با والد).
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.fixed_assets import Asset, AssetLocation, AssetWarranty
from peecha.db.models.maintenance import EquipmentProfile, FailureCode, PmPlan, WorkOrder, WorkRequest
from peecha.services.fixed_assets.common import CLOSED_STATUSES, STATUS_LABELS, TYPE_LABELS, location_path
from peecha.services.maintenance import availability
from peecha.services.maintenance import common as c

LOCATION_TYPE_LABELS = {"SITE": "سایت", "PLANT": "کارخانه", "BUILDING": "ساختمان", "AREA": "ناحیه", "FLOOR": "طبقه",
                        "ROOM": "اتاق", "LINE": "خط تولید", "OTHER": "سایر"}
# نوع‌های دارایی که در فهرست تجهیزات نگهداری می‌آیند (بقیه فقط با پروفایل نگهداری)
EQUIPMENT_TYPES = ("MACHINE", "EQUIPMENT", "VEHICLE", "IT", "TOOL", "INSTALLATION", "BUILDING")


def save_profile(company_id: int, user_id: int, asset_id: int, *, criticality_code: str = "MEDIUM",
                 technical_specs: list[tuple[str, str]] | None = None, meter_unit: str | None = None,
                 responsible_user_id: int | None = None, default_technician_user_id: int | None = None,
                 service_supplier_detail_account_id: int | None = None, safety_notes: str | None = None,
                 notes: str | None = None) -> int:
    if criticality_code not in c.CRITICALITY_LABELS:
        raise ValueError("میزان اهمیت نامعتبر است.")
    specs = [{"name": n.strip(), "value": (v or "").strip()} for n, v in (technical_specs or []) if (n or "").strip()]
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_MANAGE, session=session)
        c.asset_of(session, company_id, asset_id)
        row = session.scalar(select(EquipmentProfile).where(EquipmentProfile.asset_id == asset_id).with_for_update())
        before = {}
        if row is None:
            row = EquipmentProfile(company_id=company_id, asset_id=asset_id)
            session.add(row)
        else:
            before = {"criticality": row.criticality_code, "responsible": row.responsible_user_id}
        row.criticality_code, row.technical_specs = criticality_code, specs or None
        row.meter_unit = (meter_unit or "").strip() or None
        row.responsible_user_id, row.default_technician_user_id = responsible_user_id, default_technician_user_id
        row.service_supplier_detail_account_id = service_supplier_detail_account_id
        row.safety_notes, row.notes = (safety_notes or "").strip()[:1000] or None, (notes or "").strip()[:1000] or None
        row.updated_by_user_id, row.updated_at = user_id, c.now()
        session.flush()
        c.audit(session, company_id, user_id, "MntEquipment", asset_id, "UPDATE" if before else "CREATE",
                {"criticality": [before.get("criticality"), criticality_code],
                 "responsible": [before.get("responsible"), responsible_user_id], "specs": len(specs)})
        session.commit()
        return row.profile_id


def find(company_id: int, code: str) -> int | None:
    """کد، بارکد یا محتوای برچسب QR دارایی ← شناسهٔ تجهیز."""
    from peecha.services.fixed_assets import assets as fa

    asset = fa.find_by_code(company_id, code)
    return asset.asset_id if asset is not None else None


def _line_of(session, asset: Asset, cache: dict) -> str:
    if asset.production_line:
        return asset.production_line
    node = asset.location_id
    while node is not None:
        loc = cache.get(node) or session.get(AssetLocation, node)
        cache[node] = loc
        if loc is None:
            break
        if loc.location_type == "LINE":
            return loc.name
        node = loc.parent_location_id
    return ""


def list_equipment(company_id: int, *, search: str | None = None, location_id: int | None = None,
                   criticality_code: str | None = None, line: str | None = None, include_closed: bool = False,
                   machines_only: bool = False) -> list[SimpleNamespace]:
    """فهرست تجهیزات: دارایی‌های تجهیزاتی + هر دارایی که پروفایل نگهداری دارد."""
    with new_session() as session:
        profiles = {p.asset_id: p for p in session.scalars(select(EquipmentProfile).where(EquipmentProfile.company_id == company_id))}
        q = select(Asset).where(Asset.company_id == company_id)
        if not include_closed:
            q = q.where(Asset.status_code.not_in(CLOSED_STATUSES))
        if machines_only:
            q = q.where(Asset.is_production_machine.is_(True))
        if search:
            like = f"%{search.strip()}%"
            q = q.where(Asset.asset_code.ilike(like) | Asset.name.ilike(like) | Asset.serial_no.ilike(like)
                        | Asset.barcode.ilike(like))
        if location_id:
            q = q.where(Asset.location_id.in_(_subtree(session, company_id, location_id)))
        assets = [a for a in session.scalars(q.order_by(Asset.asset_code))
                  if a.asset_type_code in EQUIPMENT_TYPES or a.is_production_machine or a.asset_id in profiles]
        downs = set(session.scalars(select(availability.DowntimeEvent.asset_id).where(
            availability.DowntimeEvent.company_id == company_id, availability.DowntimeEvent.available_at.is_(None))))
        open_wo = dict(session.execute(select(WorkOrder.asset_id, func.count()).where(
            WorkOrder.company_id == company_id, WorkOrder.status_code.in_(c.OPEN_WO)).group_by(WorkOrder.asset_id)).all())
        cache: dict = {}
        out = []
        for a in assets:
            prof = profiles.get(a.asset_id)
            crit = prof.criticality_code if prof else None
            if criticality_code and crit != criticality_code:
                continue
            ln = _line_of(session, a, cache)
            if line and ln != line:
                continue
            out.append(SimpleNamespace(
                asset_id=a.asset_id, code=a.asset_code, name=a.name, label=c.asset_label(a), serial_no=a.serial_no,
                manufacturer=a.brand, model=a.model, type_label=TYPE_LABELS.get(a.asset_type_code, a.asset_type_code),
                status_code=a.status_code, status_label=STATUS_LABELS.get(a.status_code, a.status_code),
                location=location_path(session, a.location_id), line=ln, parent_asset_id=a.parent_asset_id,
                criticality_code=crit, criticality_label=c.CRITICALITY_LABELS.get(crit, "تعیین‌نشده"),
                is_production_machine=a.is_production_machine, down_now=a.asset_id in downs,
                open_work_orders=open_wo.get(a.asset_id, 0), has_profile=prof is not None))
        return out


def _subtree(session, company_id: int, location_id: int) -> set[int]:
    rows = session.execute(select(AssetLocation.location_id, AssetLocation.parent_location_id).where(
        AssetLocation.company_id == company_id)).all()
    children: dict = {}
    for lid, parent in rows:
        children.setdefault(parent, []).append(lid)
    out, stack = set(), [location_id]
    while stack:
        n = stack.pop()
        if n in out:
            continue
        out.add(n)
        stack.extend(children.get(n, []))
    return out


def tree(company_id: int) -> list[SimpleNamespace]:
    """درخت سایت › کارخانه › ناحیه › خط › ماشین › زیرتجهیز. هر گره: kind (LOCATION/ASSET)، label، children."""
    equipment = {e.asset_id: e for e in list_equipment(company_id)}
    with new_session() as session:
        locs = list(session.scalars(select(AssetLocation).where(AssetLocation.company_id == company_id,
                                                                AssetLocation.is_active.is_(True)).order_by(AssetLocation.code)))
        loc_of = dict(session.execute(select(Asset.asset_id, Asset.location_id).where(
            Asset.asset_id.in_(list(equipment) or [-1]))).all())
    loc_nodes = {l.location_id: SimpleNamespace(kind="LOCATION", id=l.location_id,
                                                label=f"{LOCATION_TYPE_LABELS.get(l.location_type, '')}: {l.name}",
                                                type_code=l.location_type, children=[]) for l in locs}
    asset_nodes = {aid: SimpleNamespace(kind="ASSET", id=aid, label=e.label, item=e, children=[]) for aid, e in equipment.items()}
    roots = []
    for l in locs:
        parent = loc_nodes.get(l.parent_location_id)
        (parent.children if parent else roots).append(loc_nodes[l.location_id])
    unplaced = SimpleNamespace(kind="LOCATION", id=None, label="بدون محل", type_code="OTHER", children=[])
    for aid, node in asset_nodes.items():
        e = equipment[aid]
        if e.parent_asset_id in asset_nodes:
            asset_nodes[e.parent_asset_id].children.append(node)
        elif loc_of.get(aid) in loc_nodes:
            loc_nodes[loc_of[aid]].children.append(node)
        else:
            unplaced.children.append(node)
    if unplaced.children:
        roots.append(unplaced)
    return roots


def card(company_id: int, asset_id: int) -> SimpleNamespace:
    """کارت تجهیز: شناسنامه از دارایی + مشخصات نگهداری + ضمانت + وضعیت لحظه‌ای + سوابق."""
    from peecha.services.fixed_assets import assets as fa
    from peecha.services.maintenance import pm, reliability
    from peecha.services.maintenance import requests as reqs
    from peecha.services.maintenance import work_orders as wos

    with new_session() as session:
        a = c.asset_of(session, company_id, asset_id)
        prof = session.scalar(select(EquipmentProfile).where(EquipmentProfile.asset_id == asset_id))
        names = c.user_names(session, [prof.responsible_user_id, prof.default_technician_user_id] if prof else [])
        detail_ids = [x for x in (a.supplier_detail_account_id, prof.service_supplier_detail_account_id if prof else None) if x]
        dnames = {d.detail_account_id: d.name for d in session.scalars(select(DetailAccount).where(
            DetailAccount.detail_account_id.in_(detail_ids or [-1])))}
        warranties = [SimpleNamespace(type=w.warranty_type or "", contract_no=w.contract_no or "", start=w.start_date, end=w.end_date,
                                      active=w.end_date >= datetime.date.today(), supplier=dnames.get(w.supplier_detail_account_id, ""))
                      for w in session.scalars(select(AssetWarranty).where(AssetWarranty.asset_id == asset_id)
                                               .order_by(AssetWarranty.end_date.desc()))]
        children = [SimpleNamespace(asset_id=x.asset_id, label=c.asset_label(x)) for x in session.scalars(
            select(Asset).where(Asset.parent_asset_id == asset_id).order_by(Asset.asset_code))]
        parent = session.get(Asset, a.parent_asset_id) if a.parent_asset_id else None
        open_down = availability.open_downtime(session, asset_id)
        out = SimpleNamespace(
            asset_id=a.asset_id, code=a.asset_code, name=a.name, label=c.asset_label(a), serial_no=a.serial_no,
            manufacturer=a.brand, model=a.model, part_no=a.part_no, barcode=a.barcode, qr=fa.qr_payload(a),
            type_label=TYPE_LABELS.get(a.asset_type_code, a.asset_type_code), status_code=a.status_code,
            status_label=STATUS_LABELS.get(a.status_code, a.status_code), location=location_path(session, a.location_id),
            line=_line_of(session, a, {}), in_service_date=a.in_service_date, supplier=dnames.get(a.supplier_detail_account_id, ""),
            is_production_machine=a.is_production_machine, work_center_code=a.work_center_code,
            parent=c.asset_label(parent) if parent else "", children=children,
            criticality_code=prof.criticality_code if prof else None,
            criticality_label=c.CRITICALITY_LABELS.get(prof.criticality_code, "تعیین‌نشده") if prof else "تعیین‌نشده",
            technical_specs=[(s.get("name", ""), s.get("value", "")) for s in (prof.technical_specs or [])] if prof else [],
            meter_unit=prof.meter_unit if prof else None,
            responsible=names.get(prof.responsible_user_id, "") if prof else "",
            responsible_user_id=prof.responsible_user_id if prof else None,
            default_technician=names.get(prof.default_technician_user_id, "") if prof else "",
            default_technician_user_id=prof.default_technician_user_id if prof else None,
            service_supplier=dnames.get(prof.service_supplier_detail_account_id, "") if prof else "",
            service_supplier_detail_account_id=prof.service_supplier_detail_account_id if prof else None,
            safety_notes=prof.safety_notes if prof else None, notes=prof.notes if prof else None,
            warranties=warranties, down_now=open_down is not None,
            down_since=open_down.down_from if open_down else None,
            open_requests=session.scalar(select(func.count()).where(WorkRequest.asset_id == asset_id,
                                                                    WorkRequest.status_code.in_(("NEW", "UNDER_REVIEW", "APPROVED")))),
            pm_plans=session.scalar(select(func.count()).where(PmPlan.asset_id == asset_id, PmPlan.is_active.is_(True))),
        )
    from peecha.services.fixed_assets import documents

    out.documents = [SimpleNamespace(attachment_id=d.attachment_id, file_name=d.file_name,
                                     type_label=documents.DOCUMENT_TYPES.get(d.document_type_code, ""))
                     for d in documents.list_documents(company_id, asset_id)]
    out.work_orders = wos.board(company_id, asset_id=asset_id, include_closed=True, limit=100)
    out.requests = reqs.queue(company_id, asset_id=asset_id, statuses=tuple(c.REQUEST_STATUS_LABELS), limit=100)
    out.plans = pm.list_plans(company_id, asset_id=asset_id)
    out.downtimes = availability.list_downtimes(company_id, asset_id=asset_id)[:50]
    out.kpi = reliability.asset_summary(company_id, asset_id)
    return out


# --- کدهای خرابی ----------------------------------------------------------------------------
def save_failure_code(company_id: int, user_id: int, kind_code: str, code: str, name: str, is_active: bool = True,
                      failure_code_id: int | None = None) -> int:
    if kind_code not in c.FAILURE_KIND_LABELS:
        raise ValueError("نوع کد نامعتبر است.")
    if not (code or "").strip() or not (name or "").strip():
        raise ValueError("کد و شرح الزامی است.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_MANAGE, session=session)
        dup = session.scalar(select(FailureCode.failure_code_id).where(
            FailureCode.company_id == company_id, FailureCode.kind_code == kind_code, FailureCode.code == code.strip()))
        if dup is not None and dup != failure_code_id:
            raise ValueError("این کد قبلاً تعریف شده است.")
        row = session.get(FailureCode, failure_code_id) if failure_code_id else FailureCode(company_id=company_id)
        if row is None or row.company_id != company_id:
            raise ValueError("کد نامعتبر است.")
        row.kind_code, row.code, row.name, row.is_active = kind_code, code.strip(), name.strip(), is_active
        if failure_code_id is None:
            session.add(row)
        session.flush()
        c.audit(session, company_id, user_id, "MntFailureCode", row.failure_code_id, "UPDATE" if failure_code_id else "CREATE",
                {"kind": kind_code, "code": code.strip()})
        session.commit()
        return row.failure_code_id


def list_failure_codes(company_id: int, kind_code: str | None = None, active_only: bool = False) -> list[SimpleNamespace]:
    with new_session() as session:
        q = select(FailureCode).where(FailureCode.company_id == company_id)
        if kind_code:
            q = q.where(FailureCode.kind_code == kind_code)
        if active_only:
            q = q.where(FailureCode.is_active.is_(True))
        return [SimpleNamespace(failure_code_id=f.failure_code_id, kind_code=f.kind_code, kind_label=c.FAILURE_KIND_LABELS[f.kind_code],
                                code=f.code, name=f.name, label=f"{f.code} — {f.name}", is_active=f.is_active)
                for f in session.scalars(q.order_by(FailureCode.kind_code, FailureCode.code))]
