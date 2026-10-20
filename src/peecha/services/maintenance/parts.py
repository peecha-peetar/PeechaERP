"""قطعات دستور کار (R312): برنامه، رزرو، صدور، برگشت و درخواست خرید کمبود — فقط از موتور انبار.

صدور = حوالهٔ ISSUE و برگشت = رسید RECEIPT با inventory_documents.create_and_post_in_session در همان تراکنش؛
بدهکار/بستانکار نقش «هزینهٔ قطعات تعمیر و نگهداری» (تنظیم حساب انبار) با مرکز هزینه و پروژهٔ همان دارایی.
CMMS فقط شناسهٔ سند انبار را نگه می‌دارد؛ هیچ ردیف موجودی یا سند حسابداری را مستقیم نمی‌نویسد.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.fixed_assets import Asset
from peecha.db.models.inventory import InventoryAccountMapping, Item, StockBalance, StockLedger, Warehouse
from peecha.db.models.maintenance import WorkOrder, WorkOrderPart, WorkOrderPartMove
from peecha.services import inventory_documents as inv_docs
from peecha.services import stock_controls, stock_reservations
from peecha.services.maintenance import common as c
from peecha.services.maintenance import work_orders as wos

RESERVATION_SOURCE = "MNT_PART"
EXPENSE_ROLE = "MAINTENANCE_EXPENSE"
_ISSUE_ROLES = {"COGS": EXPENSE_ROLE}
_RETURN_ROLES = {"INVENTORY_ADJUSTMENT_GAIN": EXPENSE_ROLE, "INVENTORY_COST_VARIANCE": EXPENSE_ROLE}
_ONE = decimal.Decimal(1)
_Q6 = decimal.Decimal("0.000001")
_ACTIVE_WO = ("OPEN", "PLANNED", "ASSIGNED", "IN_PROGRESS", "ON_HOLD", "COMPLETED", "VERIFIED")


@dataclass
class PartLine:
    part_id: int
    quantity: decimal.Decimal


def _q(v) -> decimal.Decimal:
    return c.dec(v).quantize(_Q6)


def _item(session, company_id: int, item_id: int) -> Item:
    item = session.get(Item, item_id)
    if item is None or item.company_id != company_id:
        raise ValueError("کالا نامعتبر است.")
    if session.scalar(select(Item.item_id).where(Item.variant_parent_item_id == item_id).limit(1)) is not None:
        raise ValueError("کالای اصلی دارای متغیر قابل مصرف نیست؛ یکی از متغیرها را انتخاب کنید.")
    return item


def _warehouse(session, company_id: int, warehouse_id: int) -> Warehouse:
    wh = session.get(Warehouse, warehouse_id)
    if wh is None or wh.company_id != company_id:
        raise ValueError("انبار نامعتبر است.")
    return wh


def add_part(company_id: int, user_id: int, work_order_id: int, item_id: int, warehouse_id: int, planned_qty) -> int:
    """ردیف قطعهٔ برنامه‌ای (همان کالا و انبار دوبار ثبت نمی‌شود؛ مقدار جمع می‌شود)."""
    qty = _q(planned_qty)
    if qty <= 0:
        raise ValueError("مقدار قطعه باید بزرگ‌تر از صفر باشد.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_PLAN, session=session)
        wo = wos.lock(session, company_id, work_order_id)
        if wo.status_code not in _ACTIVE_WO:
            raise ValueError("دستور کار بسته یا لغوشده قطعهٔ تازه نمی‌پذیرد.")
        _item(session, company_id, item_id)
        _warehouse(session, company_id, warehouse_id)
        row = session.scalar(select(WorkOrderPart).where(WorkOrderPart.work_order_id == work_order_id,
                                                         WorkOrderPart.item_id == item_id, WorkOrderPart.warehouse_id == warehouse_id))
        if row is None:
            row = WorkOrderPart(work_order_id=work_order_id, item_id=item_id, warehouse_id=warehouse_id, planned_qty=qty,
                                created_by_user_id=user_id)
            session.add(row)
        else:
            row.planned_qty = c.dec(row.planned_qty) + qty
        session.flush()
        c.audit(session, company_id, user_id, wos.ENTITY, work_order_id, "PART_ADD",
                {"part_id": row.part_id, "item_id": item_id, "warehouse_id": warehouse_id, "quantity": str(qty)})
        session.commit()
        return row.part_id


def add_parts_in_session(session, work_order_id: int, user_id: int | None, parts: list[tuple[int, int | None, decimal.Decimal]],
                         default_warehouse_id: int | None) -> None:
    """قطعه‌های برنامهٔ پیشگیرانه هنگام ساخت دستور کار (بدون انبار پیش‌فرض، ردیف ساخته نمی‌شود)."""
    for item_id, warehouse_id, qty in parts:
        wh = warehouse_id or default_warehouse_id
        if wh is None or c.dec(qty) <= 0:
            continue
        session.add(WorkOrderPart(work_order_id=work_order_id, item_id=item_id, warehouse_id=wh, planned_qty=_q(qty),
                                  created_by_user_id=user_id))


def _reserved(session, part_id: int) -> decimal.Decimal:
    return sum((stock_reservations.remaining(r) for r in stock_reservations.active(session, RESERVATION_SOURCE, [part_id],
                                                                                    lock=False)), c.ZERO)


def _bins(session, item_id: int, warehouse_id: int, free_only: bool) -> list[tuple[int | None, decimal.Decimal]]:
    rows = session.execute(select(StockBalance.bin_location_id, StockBalance.quantity_on_hand, StockBalance.quantity_reserved)
                           .where(StockBalance.item_id == item_id, StockBalance.warehouse_id == warehouse_id,
                                  StockBalance.batch_id.is_(None), StockBalance.quantity_on_hand > 0)).all()
    out = [(b, c.dec(q) - (c.dec(r) if free_only else c.ZERO)) for b, q, r in rows]
    return sorted([x for x in out if x[1] > 0], key=lambda x: (-x[1], x[0] or 0))


def item_label(session, item_id: int) -> str:
    row = session.execute(select(DetailAccount.code, DetailAccount.name).join(Item, Item.item_detail_account_id ==
                                                                             DetailAccount.detail_account_id)
                          .where(Item.item_id == item_id)).first()
    return f"{row[0]} {row[1]}" if row else str(item_id)


def _need(part: WorkOrderPart) -> decimal.Decimal:
    return max(c.ZERO, c.dec(part.planned_qty) - (c.dec(part.issued_qty) - c.dec(part.returned_qty)))


def reserve(company_id: int, user_id: int, work_order_id: int) -> decimal.Decimal:
    """رزرو موجودی آزاد برای باقی‌ماندهٔ قطعه‌های برنامه‌ای (همان رزرو مشترک انبار)."""
    total = c.ZERO
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_PLAN, session=session)
        wo = wos.lock(session, company_id, work_order_id)
        if wo.status_code not in _ACTIVE_WO:
            raise ValueError("دستور کار بسته یا لغوشده رزرو نمی‌پذیرد.")
        for part in session.scalars(select(WorkOrderPart).where(WorkOrderPart.work_order_id == work_order_id)
                                    .order_by(WorkOrderPart.part_id).with_for_update()):
            gap = _need(part) - _reserved(session, part.part_id)
            for bin_id, free in _bins(session, part.item_id, part.warehouse_id, free_only=True):
                if gap <= 0:
                    break
                take = min(free, gap)
                stock_reservations.add(session, company_id=company_id, item_id=part.item_id, warehouse_id=part.warehouse_id,
                                       bin_location_id=bin_id, quantity=take, source_type=RESERVATION_SOURCE,
                                       source_id=part.part_id)
                gap -= take
                total += take
        c.audit(session, company_id, user_id, wos.ENTITY, work_order_id, "PART_RESERVE", {"quantity": str(total)})
        session.commit()
    return total


def release_reservations(session, work_order_id: int) -> None:
    ids = list(session.scalars(select(WorkOrderPart.part_id).where(WorkOrderPart.work_order_id == work_order_id)))
    for res in stock_reservations.active(session, RESERVATION_SOURCE, ids):
        stock_reservations.release(session, res)


def _consume_reservation(session, part_id: int, qty: decimal.Decimal) -> None:
    left = qty
    for res in stock_reservations.active(session, RESERVATION_SOURCE, [part_id]):
        if left <= 0:
            break
        left -= stock_reservations.fulfil(session, res, left)


def _header(wo: WorkOrder, asset: Asset, what: str, **kw) -> inv_docs.DocumentHeaderFields:
    return inv_docs.DocumentHeaderFields(cost_center_detail_account_id=asset.cost_center_detail_account_id,
                                         project_detail_account_id=asset.project_detail_account_id,
                                         reference_no=f"WO-{wo.wo_no}",
                                         description=f"دستور کار نگهداری {wo.wo_no} — {asset.asset_code} — {what}", **kw)


def _require_mapping(session, company_id: int) -> None:
    row = session.get(InventoryAccountMapping, (company_id, EXPENSE_ROLE))
    if row is None or row.account_id is None:
        raise ValueError("حساب «هزینهٔ قطعات تعمیر و نگهداری» در تنظیم حساب‌های انبار تعیین نشده است "
                         "(تنظیمات › انبار › تنظیم حساب‌ها).")


def _replayed(session, work_order_id: int, key: str | None) -> WorkOrderPartMove | None:
    if not key:
        return None
    return session.scalar(select(WorkOrderPartMove).join(WorkOrderPart, WorkOrderPart.part_id == WorkOrderPartMove.part_id)
                          .where(WorkOrderPart.work_order_id == work_order_id, WorkOrderPartMove.idempotency_key == key))


def _ledger_amounts(session, line_ids: list[int], direction: str) -> dict[int, decimal.Decimal]:
    out: dict[int, decimal.Decimal] = {}
    for lid, q, uc in session.execute(select(StockLedger.stock_document_line_id, StockLedger.quantity_base, StockLedger.unit_cost)
                                      .where(StockLedger.stock_document_line_id.in_(line_ids or [-1]),
                                             StockLedger.movement_direction == direction)):
        out[lid] = out.get(lid, c.ZERO) + c.money(c.dec(q) * c.dec(uc))
    return out


def issue(company_id: int, user_id: int, work_order_id: int, lines: list[PartLine], date: datetime.date | None = None,
          idempotency_key: str | None = None) -> list[int]:
    """صدور قطعه (حوالهٔ انبار)؛ تکرار با همان کلید یکتایی سند دوم نمی‌سازد. خروجی = شناسهٔ اسناد انبار."""
    date = date or datetime.date.today()
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_PARTS, session=session)
        wo = wos.lock(session, company_id, work_order_id)
        done = _replayed(session, work_order_id, idempotency_key)
        if done is not None:
            return [done.stock_document_id]
        if wo.status_code not in _ACTIVE_WO:
            raise ValueError(f"دستور کار در وضعیت «{c.WO_STATUS_LABELS[wo.status_code]}» است و صدور قطعه ممکن نیست.")
        _require_mapping(session, company_id)
        asset = session.get(Asset, wo.asset_id)
        enforce = stock_controls.is_on(company_id, stock_controls.RESERVATION, session)
        by_wh: dict[int, list[tuple[WorkOrderPart, decimal.Decimal]]] = {}
        for ln in lines:
            qty = _q(ln.quantity)
            if qty <= 0:
                continue
            part = session.scalar(select(WorkOrderPart).where(WorkOrderPart.part_id == ln.part_id).with_for_update())
            if part is None or part.work_order_id != work_order_id:
                raise ValueError("ردیف قطعهٔ دستور کار نامعتبر است.")
            by_wh.setdefault(part.warehouse_id, []).append((part, qty))
        if not by_wh:
            raise ValueError("مقداری برای صدور وارد نشده است.")
        docs, n = [], 0
        for wh, group in by_wh.items():
            doc_lines, owners = [], []
            for part, qty in group:
                item = session.get(Item, part.item_id)
                if enforce:
                    _consume_reservation(session, part.part_id, qty)   # رزرو خود دستور کار اول آزاد می‌شود
                left = qty
                for bin_id, avail in _bins(session, part.item_id, wh, free_only=enforce):
                    take = min(avail, left)
                    if take <= 0:
                        break
                    doc_lines.append(inv_docs.LineFields(item_id=part.item_id, uom_id=item.base_uom_id, quantity=take,
                                                         quantity_base=take, bin_location_id=bin_id, conversion_factor=_ONE))
                    owners.append((part, take))
                    left -= take
                if left > 0:
                    raise ValueError(f"موجودی «{item_label(session, part.item_id)}» در انبار کافی نیست (کمبود {left.normalize():f}). "
                                     "برای کمبود می‌توانید درخواست خرید ثبت کنید.")
            result, line_ids = inv_docs.create_and_post_in_session(
                session, company_id, user_id, "ISSUE", date, _header(wo, asset, "صدور قطعه", source_warehouse_id=wh),
                doc_lines, role_overrides=_ISSUE_ROLES)
            amounts = _ledger_amounts(session, line_ids, "OUT")
            per_part: dict[int, list] = {}
            for (part, take), lid in zip(owners, line_ids):
                acc = per_part.setdefault(part.part_id, [part, c.ZERO, c.ZERO])
                acc[1] += take
                acc[2] += amounts.get(lid, c.ZERO)
            for part, take, amount in per_part.values():
                part.issued_qty = c.dec(part.issued_qty) + take
                part.issued_amount = c.dec(part.issued_amount) + amount
                if not enforce:
                    _consume_reservation(session, part.part_id, take)
                key = idempotency_key if (idempotency_key and n == 0) else (f"{idempotency_key}:{n}" if idempotency_key else None)
                session.add(WorkOrderPartMove(part_id=part.part_id, direction_code="ISSUE", quantity=take, amount=c.money(amount),
                                              stock_document_id=result.stock_document_id, idempotency_key=key,
                                              created_by_user_id=user_id))
                n += 1
            session.flush()
            docs.append(result.stock_document_id)
            c.audit(session, company_id, user_id, wos.ENTITY, work_order_id, "PART_ISSUE",
                    {"stock_document_id": result.stock_document_id, "lines": len(owners)})
        session.commit()
        return docs


def return_parts(company_id: int, user_id: int, work_order_id: int, lines: list[PartLine], date: datetime.date | None = None,
                 idempotency_key: str | None = None) -> list[int]:
    """برگشت قطعهٔ مصرف‌نشده با میانگین بهای صادرشدهٔ همین دستور کار (بستانکار هزینهٔ قطعات)."""
    date = date or datetime.date.today()
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_PARTS, session=session)
        wo = wos.lock(session, company_id, work_order_id)
        done = _replayed(session, work_order_id, idempotency_key)
        if done is not None:
            return [done.stock_document_id]
        if wo.status_code not in _ACTIVE_WO:
            raise ValueError(f"دستور کار در وضعیت «{c.WO_STATUS_LABELS[wo.status_code]}» است و برگشت قطعه ممکن نیست.")
        _require_mapping(session, company_id)
        asset = session.get(Asset, wo.asset_id)
        by_wh: dict[int, list] = {}
        for ln in lines:
            qty = _q(ln.quantity)
            if qty <= 0:
                continue
            part = session.scalar(select(WorkOrderPart).where(WorkOrderPart.part_id == ln.part_id).with_for_update())
            if part is None or part.work_order_id != work_order_id:
                raise ValueError("ردیف قطعهٔ دستور کار نامعتبر است.")
            net_qty = c.dec(part.issued_qty) - c.dec(part.returned_qty)
            if qty > net_qty:
                raise ValueError(f"مقدار برگشت از خالص صادرشده ({net_qty.normalize():f}) بیشتر است.")
            net_amount = c.dec(part.issued_amount) - c.dec(part.returned_amount)
            unit = (net_amount / net_qty).quantize(_Q6) if net_qty else c.ZERO
            by_wh.setdefault(part.warehouse_id, []).append((part, qty, unit))
        if not by_wh:
            raise ValueError("مقداری برای برگشت وارد نشده است.")
        docs, n = [], 0
        for wh, group in by_wh.items():
            doc_lines = [inv_docs.LineFields(item_id=p.item_id, uom_id=session.get(Item, p.item_id).base_uom_id, quantity=q,
                                             quantity_base=q, unit_cost=u, conversion_factor=_ONE) for p, q, u in group]
            result, _line_ids = inv_docs.create_and_post_in_session(
                session, company_id, user_id, "RECEIPT", date, _header(wo, asset, "برگشت قطعه", destination_warehouse_id=wh),
                doc_lines, role_overrides=_RETURN_ROLES)
            for part, qty, unit in group:
                net_qty = c.dec(part.issued_qty) - c.dec(part.returned_qty)
                # برگشت کل مانده = کل ماندهٔ مبلغ (اختلاف گرد کردن نمی‌ماند)
                amount = c.dec(part.issued_amount) - c.dec(part.returned_amount) if qty == net_qty else c.money(unit * qty)
                part.returned_qty = c.dec(part.returned_qty) + qty
                part.returned_amount = c.dec(part.returned_amount) + amount
                key = idempotency_key if (idempotency_key and n == 0) else (f"{idempotency_key}:{n}" if idempotency_key else None)
                session.add(WorkOrderPartMove(part_id=part.part_id, direction_code="RETURN", quantity=qty, amount=c.money(amount),
                                              stock_document_id=result.stock_document_id, idempotency_key=key,
                                              created_by_user_id=user_id))
                n += 1
            session.flush()
            docs.append(result.stock_document_id)
            c.audit(session, company_id, user_id, wos.ENTITY, work_order_id, "PART_RETURN",
                    {"stock_document_id": result.stock_document_id, "lines": len(group)})
        session.commit()
        return docs


def availability_of(company_id: int, work_order_id: int) -> list[SimpleNamespace]:
    """نیاز، رزرو، موجودی آزاد و کمبود هر قطعه."""
    with new_session() as session:
        out = []
        for part in session.scalars(select(WorkOrderPart).where(WorkOrderPart.work_order_id == work_order_id)
                                    .order_by(WorkOrderPart.part_id)):
            need = _need(part)
            reserved = _reserved(session, part.part_id)
            free = sum((q for _b, q in _bins(session, part.item_id, part.warehouse_id, free_only=True)), c.ZERO)
            out.append(SimpleNamespace(part_id=part.part_id, item_id=part.item_id, warehouse_id=part.warehouse_id, need=need,
                                       reserved=reserved, free=free, shortage=max(c.ZERO, need - reserved - free)))
        return out


def request_purchase(company_id: int, user_id: int, work_order_id: int, required_date: datetime.date | None = None) -> int | None:
    """درخواست خرید پیش‌نویس برای کمبود قطعه‌ها؛ از همان مسیر مجاز خرید (ارسال و تصویب) می‌گذرد.

    قطعه‌ای که درخواست خرید فعال دارد دوباره درخواست نمی‌شود. خروجی = شناسهٔ درخواست خرید (یا None اگر کمبودی نیست).
    """
    from peecha.db.models.commercial import PurchaseRequest
    from peecha.services import purchase_requests as prs

    with new_session() as session:
        c.require(company_id, user_id, c.FORM_PLAN, session=session)
        wo = session.get(WorkOrder, work_order_id)
        if wo is None or wo.company_id != company_id:
            raise ValueError("دستور کار نامعتبر است.")
        if wo.status_code not in _ACTIVE_WO:
            raise ValueError("دستور کار بسته یا لغوشده درخواست خرید نمی‌سازد.")
        asset = session.get(Asset, wo.asset_id)
        linked = {p.part_id: p.purchase_request_id for p in session.scalars(select(WorkOrderPart).where(
            WorkOrderPart.work_order_id == work_order_id, WorkOrderPart.purchase_request_id.isnot(None)))}
        live = set(session.scalars(select(PurchaseRequest.request_id).where(
            PurchaseRequest.request_id.in_(set(linked.values()) or {-1}),
            PurchaseRequest.status_code.not_in(("CANCELLED", "REJECTED")))))
        wo_no, cc, prj = wo.wo_no, asset.cost_center_detail_account_id, asset.project_detail_account_id
        priority = "URGENT" if wo.priority_code == "URGENT" else ("HIGH" if wo.priority_code == "HIGH" else "NORMAL")
    rows = [r for r in availability_of(company_id, work_order_id) if r.shortage > 0 and linked.get(r.part_id) not in live]
    if not rows:
        return None
    from peecha.services.purchase_requests import PRIORITY_LABELS

    pr_id = prs.create_request(company_id, user_id, prs.RequestFields(
        request_date=datetime.date.today(), required_date=required_date, priority_code=priority if priority in PRIORITY_LABELS
        else "NORMAL", warehouse_id=rows[0].warehouse_id, cost_center_detail_account_id=cc, project_detail_account_id=prj,
        description=f"کمبود قطعهٔ دستور کار نگهداری {wo_no}"))
    line_of = {}
    with new_session() as session:
        uoms = {i.item_id: i.base_uom_id for i in session.scalars(select(Item).where(Item.item_id.in_([r.item_id for r in rows])))}
    for r in rows:
        line_of[r.part_id] = prs.add_line(pr_id, company_id, r.item_id, uoms[r.item_id], r.shortage, required_date=required_date,
                                          description=f"دستور کار نگهداری {wo_no}")
    with new_session() as session:
        for r in rows:
            part = session.get(WorkOrderPart, r.part_id)
            part.purchase_request_id, part.purchase_request_line_id = pr_id, line_of[r.part_id]
        c.audit(session, company_id, user_id, wos.ENTITY, work_order_id, "PURCHASE_REQUEST",
                {"purchase_request_id": pr_id, "lines": len(rows)})
        session.commit()
    return pr_id


def list_parts(company_id: int, work_order_id: int) -> list[SimpleNamespace]:
    from peecha.db.models.commercial import PurchaseRequest

    avail = {a.part_id: a for a in availability_of(company_id, work_order_id)}
    with new_session() as session:
        rows = session.execute(select(WorkOrderPart, Item, Warehouse, DetailAccount)
                               .join(Item, Item.item_id == WorkOrderPart.item_id)
                               .join(DetailAccount, DetailAccount.detail_account_id == Item.item_detail_account_id)
                               .join(Warehouse, Warehouse.warehouse_id == WorkOrderPart.warehouse_id)
                               .where(WorkOrderPart.work_order_id == work_order_id).order_by(WorkOrderPart.part_id)).all()
        pr_no = dict(session.execute(select(PurchaseRequest.request_id, PurchaseRequest.request_no).where(
            PurchaseRequest.request_id.in_([p.purchase_request_id for p, _i, _w, _d in rows if p.purchase_request_id] or [-1]))).all())
        out = []
        for p, item, wh, da in rows:
            a = avail.get(p.part_id)
            out.append(SimpleNamespace(
                part_id=p.part_id, item_id=item.item_id, item_code=da.code, item_name=da.name, warehouse_id=wh.warehouse_id,
                warehouse_name=wh.name, planned_qty=p.planned_qty, issued_qty=p.issued_qty, returned_qty=p.returned_qty,
                net_qty=c.dec(p.issued_qty) - c.dec(p.returned_qty), net_amount=c.dec(p.issued_amount) - c.dec(p.returned_amount),
                reserved=a.reserved if a else c.ZERO, free=a.free if a else c.ZERO, shortage=a.shortage if a else c.ZERO,
                purchase_request_no=pr_no.get(p.purchase_request_id)))
        return out


def moves(company_id: int, work_order_id: int) -> list[SimpleNamespace]:
    with new_session() as session:
        rows = session.execute(select(WorkOrderPartMove, WorkOrderPart).join(WorkOrderPart, WorkOrderPart.part_id == WorkOrderPartMove.part_id)
                               .where(WorkOrderPart.work_order_id == work_order_id).order_by(WorkOrderPartMove.move_id)).all()
        return [SimpleNamespace(move_id=m.move_id, part_id=p.part_id, item_id=p.item_id, direction_code=m.direction_code,
                                quantity=m.quantity, amount=m.amount, stock_document_id=m.stock_document_id, created_at=m.created_at)
                for m, p in rows]


def issued_total(session, work_order_ids) -> dict[int, decimal.Decimal]:
    """خالص مبلغ قطعهٔ هر دستور کار (صادر − برگشت) — برای خلاصهٔ هزینه و شاخص‌ها."""
    ids = list(work_order_ids)
    if not ids:
        return {}
    return {wid: c.dec(v) for wid, v in session.execute(
        select(WorkOrderPart.work_order_id, func.sum(WorkOrderPart.issued_amount - WorkOrderPart.returned_amount))
        .where(WorkOrderPart.work_order_id.in_(ids)).group_by(WorkOrderPart.work_order_id)).all()}
