"""انبارگردانی (شمارشِ موجودی) با واحدِ شمارش -- R225.

کاربر هر کالا را با واحدِ دلخواه (مثلاً «۱۰ کارتن») می‌شمارد؛ مقدار با
unit_conversion به واحدِ پایه تبدیل و اختلاف با موجودیِ دفتری به واحدِ پایه
محاسبه می‌شود. در پایان، یک سندِ اصلاحِ انبار (ADJUSTMENT) برایِ مازاد و یکی
برایِ کسری صادر و ثبت می‌شود -- همان موتورِ انبار/حسابداریِ موجود، بدونِ
منطقِ تازهٔ موجودی.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import CycleCountLine, CycleCountSession, Item, StockBalance, Warehouse
from peecha.services import inventory_documents as inv_documents_service
from peecha.services import inventory_locations as locations_service
from peecha.services import unit_conversion as uc

_ZERO = decimal.Decimal(0)
_COUNT_REASON_CODE = "STOCK-COUNT"


@dataclass
class CountLineRow:
    line_id: int
    item_id: int
    counted_uom_id: int | None
    counted_quantity: decimal.Decimal | None
    conversion_factor: decimal.Decimal | None
    expected_quantity_base: decimal.Decimal
    counted_quantity_base: decimal.Decimal | None
    variance_quantity_base: decimal.Decimal | None


@dataclass
class CountSessionRow:
    session_id: int
    session_code: str
    warehouse_id: int
    status_code: str
    snapshot_at: datetime.datetime | None
    resulting_stock_document_id: int | None
    lines: list[CountLineRow]


def _on_hand(session, warehouse_id: int, item_id: int) -> decimal.Decimal:
    return session.scalar(
        select(func.coalesce(func.sum(StockBalance.quantity_on_hand), 0)).where(
            StockBalance.warehouse_id == warehouse_id, StockBalance.item_id == item_id,
        )
    ) or _ZERO


def create_count_session(company_id: int, warehouse_id: int, created_by_user_id: int, session_code: str | None = None) -> int:
    with new_session() as session:
        warehouse = session.get(Warehouse, warehouse_id)
        if warehouse is None or warehouse.company_id != company_id:
            raise ValueError("انبار نامعتبر است.")
        if not warehouse.allow_cycle_count:
            raise ValueError("انبارگردانی برایِ این انبار مجاز نشده است (تنظیماتِ انبار).")
        if session_code is None:
            count = session.scalar(select(func.count()).select_from(CycleCountSession).where(CycleCountSession.company_id == company_id)) or 0
            session_code = f"CNT-{count + 1:05d}"
        row = CycleCountSession(
            company_id=company_id, warehouse_id=warehouse_id, session_code=session_code, scope_type_code="BY_ITEM",
            scope_filter={}, status_code="COUNTING", is_blind_count=False, snapshot_at=datetime.datetime.now(),
            created_by_user_id=created_by_user_id,
        )
        session.add(row)
        session.commit()
        return row.session_id


def record_count(
    session_id: int, company_id: int, item_id: int, uom_id: int, counted_quantity: decimal.Decimal,
) -> int:
    """ثبت/جایگزینیِ شمارشِ یک کالا با واحدِ شمارش (مثلاً ۱۰ کارتن = ۲۴۰ عدد)."""
    counted_quantity = decimal.Decimal(counted_quantity)
    if counted_quantity < 0:
        raise ValueError("مقدارِ شمارش‌شده نمی‌تواند منفی باشد.")
    if counted_quantity > 0:
        uc.validate_quantity(item_id, uom_id, counted_quantity, purpose="INVENTORY", check_min_max=False)
    counted_base, factor = uc.convert_to_base(item_id, counted_quantity, uom_id)
    with new_session() as session:
        count_session = session.get(CycleCountSession, session_id)
        if count_session is None or count_session.company_id != company_id:
            raise ValueError("جلسهٔ انبارگردانی نامعتبر است.")
        if count_session.status_code != "COUNTING":
            raise ValueError("این انبارگردانی بسته شده است.")
        bin_row = locations_service.get_default_bin_location(count_session.warehouse_id)
        if bin_row is None:
            raise ValueError("این انبار هیچ مکانی ندارد.")
        line = session.scalar(
            select(CycleCountLine).where(CycleCountLine.session_id == session_id, CycleCountLine.item_id == item_id)
        )
        if line is None:
            line = CycleCountLine(
                session_id=session_id, item_id=item_id, bin_location_id=bin_row.bin_location_id,
                expected_quantity_base=_on_hand(session, count_session.warehouse_id, item_id),
            )
            session.add(line)
        line.counted_uom_id = uom_id
        line.counted_quantity = counted_quantity
        line.conversion_factor = factor
        line.counted_quantity_base = counted_base
        session.commit()
        return line.line_id


def get_count_session(session_id: int, company_id: int) -> CountSessionRow:
    with new_session() as session:
        s = session.get(CycleCountSession, session_id)
        if s is None or s.company_id != company_id:
            raise ValueError("جلسهٔ انبارگردانی نامعتبر است.")
        lines = [
            CountLineRow(
                l.line_id, l.item_id, l.counted_uom_id, l.counted_quantity, l.conversion_factor,
                l.expected_quantity_base, l.counted_quantity_base,
                (l.counted_quantity_base - l.expected_quantity_base) if l.counted_quantity_base is not None else None,
            )
            for l in session.scalars(select(CycleCountLine).where(CycleCountLine.session_id == session_id).order_by(CycleCountLine.line_id))
        ]
        return CountSessionRow(s.session_id, s.session_code, s.warehouse_id, s.status_code, s.snapshot_at, s.resulting_stock_document_id, lines)


def list_count_sessions(company_id: int) -> list[CountSessionRow]:
    with new_session() as session:
        ids = list(session.scalars(
            select(CycleCountSession.session_id).where(CycleCountSession.company_id == company_id).order_by(CycleCountSession.session_id.desc())
        ))
    return [get_count_session(i, company_id) for i in ids]


def _reason_code(company_id: int) -> int:
    for row in inv_documents_service.list_reason_codes(company_id, "ADJUSTMENT", active_only=False):
        if row.code == _COUNT_REASON_CODE:
            return row.reason_code_id
    return inv_documents_service.create_reason_code(company_id, "ADJUSTMENT", _COUNT_REASON_CODE, "اختلافِ انبارگردانی")


def finalize_count_session(session_id: int, company_id: int, approved_by_user_id: int) -> list[int]:
    """اختلافِ هر ردیف (به واحدِ پایه) را با سندِ اصلاحِ انبار ثبت می‌کند؛
    شناسهٔ اسنادِ صادرشده را برمی‌گرداند (مازاد/کسری)."""
    data = get_count_session(session_id, company_id)
    if data.status_code != "COUNTING":
        raise ValueError("این انبارگردانی قبلاً بسته شده است.")
    gains = [l for l in data.lines if l.variance_quantity_base is not None and l.variance_quantity_base > 0]
    losses = [l for l in data.lines if l.variance_quantity_base is not None and l.variance_quantity_base < 0]
    reason_code_id = _reason_code(company_id) if gains or losses else None
    with new_session() as session:
        base_uom = {
            l.item_id: session.scalar(select(Item.base_uom_id).where(Item.item_id == l.item_id))
            for l in gains + losses
        }
    document_ids = []
    for rows, header in (
        (gains, inv_documents_service.DocumentHeaderFields(destination_warehouse_id=data.warehouse_id)),
        (losses, inv_documents_service.DocumentHeaderFields(source_warehouse_id=data.warehouse_id)),
    ):
        if not rows:
            continue
        header.reference_no = data.session_code
        header.description = f"اختلافِ انبارگردانیِ {data.session_code}"
        doc_id = inv_documents_service.create_stock_document(company_id, approved_by_user_id, "ADJUSTMENT", datetime.date.today(), header)
        for l in rows:
            qty = abs(l.variance_quantity_base)
            inv_documents_service.add_line(doc_id, company_id, inv_documents_service.LineFields(
                item_id=l.item_id, uom_id=base_uom[l.item_id], quantity=qty, quantity_base=qty,
                conversion_factor=decimal.Decimal(1), reason_code_id=reason_code_id,
                description=f"انبارگردانی: دفتری {l.expected_quantity_base.normalize()}، شمارش {l.counted_quantity_base.normalize()}",
            ))
        inv_documents_service.confirm_stock_document(doc_id, company_id)
        inv_documents_service.post_stock_document(doc_id, company_id, approved_by_user_id)
        document_ids.append(doc_id)
    with new_session() as session:
        s = session.get(CycleCountSession, session_id)
        s.status_code = "POSTED"
        s.approved_by_user_id = approved_by_user_id
        s.approved_at = datetime.datetime.now()
        s.resulting_stock_document_id = document_ids[0] if document_ids else None
        session.commit()
    return document_ids
