"""R361: بسته‌بندی و کنترل ارسال سند فروش.

- اقلام هر سفارش یا فاکتور فروش با اسکن (بارکد کالا یا واحد، یا کد کالا) در بسته‌ها چیده می‌شود؛ کالای خارج از سند یا بیش از
  ماندهٔ ردیف پذیرفته نمی‌شود (کنترل بسته‌بندی). بارکد واحد بزرگ‌تر (مثلاً کارتن) به‌اندازهٔ ضریب همان واحد شمرده می‌شود.
- قابل بسته‌بندی هر ردیف = مقدار پایهٔ ردیف؛ اگر برای ردیف کار جمع‌آوری انبار ساخته شده، فقط مقدار کارهای انجام‌شده.
- بستن بسته وزن و ابعاد را ثبت می‌کند؛ ارسال، حمل همان سند را در «حمل» (comm.shipments) ثبت و بسته‌ها را ارسال‌شده می‌کند.
- موجودی و حسابداری دست نمی‌خورد؛ خروج کالا همچنان با حوالهٔ همان سند است.
"""

from __future__ import annotations

import datetime
import decimal
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine
from peecha.db.models.inventory import Item, PackPackage, PackPackageLine, WarehouseTask

PACKABLE_TYPES = {"SALES_ORDER": "سفارش فروش", "SALES_INVOICE": "فاکتور فروش"}
_OPEN_DOC = ("CONFIRMED", "APPROVED", "POSTED")
STATUSES = {"OPEN": "باز", "CLOSED": "بسته‌شده", "SHIPPED": "ارسال‌شده"}
SHIPPING_METHODS = {"COURIER": "پیک", "POST": "پست", "FREIGHT": "باربری", "PICKUP": "تحویل حضوری"}
_ZERO = decimal.Decimal(0)


def _labels(session, item_ids) -> dict[int, str]:
    """کد و نام کالا از حساب تفصیلی همان کالا."""
    return {item_id: f"{code} — {name}" for item_id, code, name in session.execute(
        select(Item.item_id, DetailAccount.code, DetailAccount.name)
        .join(DetailAccount, DetailAccount.detail_account_id == Item.item_detail_account_id)
        .where(Item.item_id.in_(set(item_ids) or {0})))}


def _document(session, company_id: int, document_id: int) -> CommercialDocument:
    doc = session.get(CommercialDocument, document_id)
    if doc is None or doc.company_id != company_id or doc.document_type_code not in PACKABLE_TYPES:
        raise ValueError("سند فروش برای بسته‌بندی نامعتبر است.")
    if doc.status_code not in _OPEN_DOC:
        raise ValueError("فقط سند فروش تاییدشده یا ثبت‌شده بسته‌بندی می‌شود.")
    return doc


def _lines(session, document_id: int) -> list[SimpleNamespace]:
    lines = list(session.scalars(select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id,
                                                                      CommercialDocumentLine.item_id.is_not(None))
                                 .order_by(CommercialDocumentLine.line_no)))
    ids = [ln.line_id for ln in lines] or [0]
    picks: dict[int, list] = {}
    for line_id, status, done in session.execute(select(WarehouseTask.source_commercial_line_id, WarehouseTask.status_code,
                                                        WarehouseTask.done_quantity_base)
                                                 .where(WarehouseTask.source_commercial_line_id.in_(ids),
                                                        WarehouseTask.task_type_code == "PICK",
                                                        WarehouseTask.status_code != "CANCELLED")):
        picks.setdefault(line_id, []).append((status, done))
    packed = dict(session.execute(select(PackPackageLine.document_line_id, func.sum(PackPackageLine.quantity_base))
                                  .where(PackPackageLine.document_line_id.in_(ids)).group_by(PackPackageLine.document_line_id)).all())
    labels = _labels(session, {ln.item_id for ln in lines})
    out = []
    for ln in lines:
        packable = decimal.Decimal(ln.quantity_base)
        if ln.line_id in picks:
            packable = sum((decimal.Decimal(done or 0) for status, done in picks[ln.line_id] if status == "DONE"), _ZERO)
        done = decimal.Decimal(packed.get(ln.line_id) or 0)
        out.append(SimpleNamespace(line_id=ln.line_id, item_id=ln.item_id, item_label=labels.get(ln.item_id, ""),
                                   ordered=decimal.Decimal(ln.quantity_base), packable=packable, packed=done,
                                   remaining=max(packable - done, _ZERO), picked=ln.line_id in picks))
    return out


def pack_status(company_id: int, document_id: int) -> list[SimpleNamespace]:
    with new_session() as session:
        _document(session, company_id, document_id)
        return _lines(session, document_id)


def _state(lines, packages) -> str:
    if packages and all(p.status_code == "SHIPPED" for p in packages):
        return "SHIPPED"
    if lines and all(ln.packed >= ln.ordered for ln in lines) and all(p.status_code != "OPEN" for p in packages):
        return "READY"
    return "PACKING" if packages else "WAITING"


DOCUMENT_STATES = {"WAITING": "منتظر بسته‌بندی", "PACKING": "در حال بسته‌بندی", "READY": "آمادهٔ ارسال", "SHIPPED": "ارسال‌شده"}


def packable_documents(company_id: int, warehouse_id: int | None = None, include_shipped: bool = False,
                       limit: int = 200) -> list[SimpleNamespace]:
    with new_session() as session:
        q = select(CommercialDocument).where(CommercialDocument.company_id == company_id,
                                             CommercialDocument.document_type_code.in_(list(PACKABLE_TYPES)),
                                             CommercialDocument.status_code.in_(_OPEN_DOC))
        if warehouse_id:
            q = q.where(CommercialDocument.warehouse_id == warehouse_id)
        docs = list(session.scalars(q.order_by(CommercialDocument.document_date.desc(), CommercialDocument.document_id.desc())
                                    .limit(limit * 2)))
        names = dict(session.execute(select(DetailAccount.detail_account_id, DetailAccount.name).where(
            DetailAccount.detail_account_id.in_({d.counterparty_detail_account_id for d in docs} or {0}))).all())
        packages: dict[int, list] = {}
        for p in session.scalars(select(PackPackage).where(PackPackage.document_id.in_([d.document_id for d in docs] or [0]))):
            packages.setdefault(p.document_id, []).append(p)
        out = []
        for d in docs:
            lines = _lines(session, d.document_id)
            state = _state(lines, packages.get(d.document_id, []))
            if state == "SHIPPED" and not include_shipped:
                continue
            ordered = sum((ln.ordered for ln in lines), _ZERO)
            out.append(SimpleNamespace(document_id=d.document_id, document_type_code=d.document_type_code,
                                       type_label=PACKABLE_TYPES[d.document_type_code], document_no=d.document_no,
                                       document_date=d.document_date, customer=names.get(d.counterparty_detail_account_id, ""),
                                       warehouse_id=d.warehouse_id, packages=len(packages.get(d.document_id, [])),
                                       packed_percent=(sum((ln.packed for ln in lines), _ZERO) * 100 / ordered) if ordered else _ZERO,
                                       state=state, state_label=DOCUMENT_STATES[state]))
            if len(out) >= limit:
                break
        return out


def list_packages(company_id: int, document_id: int) -> list[SimpleNamespace]:
    with new_session() as session:
        packages = list(session.scalars(select(PackPackage).where(PackPackage.company_id == company_id,
                                                                  PackPackage.document_id == document_id)
                                        .order_by(PackPackage.package_no)))
        lines: dict[int, list] = {}
        rows = list(session.scalars(select(PackPackageLine).where(
            PackPackageLine.package_id.in_([p.package_id for p in packages] or [0])).order_by(PackPackageLine.package_line_id)))
        labels = _labels(session, {ln.item_id for ln in rows})
        for ln in rows:
            lines.setdefault(ln.package_id, []).append(SimpleNamespace(package_line_id=ln.package_line_id, item_id=ln.item_id,
                                                                       item_label=labels.get(ln.item_id, ""),
                                                                       quantity=ln.quantity_base))
        return [SimpleNamespace(package_id=p.package_id, package_no=p.package_no, status_code=p.status_code,
                                status_label=STATUSES[p.status_code], weight_kg=p.weight_kg, length_cm=p.length_cm,
                                width_cm=p.width_cm, height_cm=p.height_cm, shipment_id=p.shipment_id,
                                lines=lines.get(p.package_id, []),
                                quantity=sum((ln.quantity for ln in lines.get(p.package_id, [])), _ZERO)) for p in packages]


def _open_package(session, company_id: int, doc: CommercialDocument, user_id: int | None) -> PackPackage:
    current = session.scalar(select(PackPackage).where(PackPackage.document_id == doc.document_id, PackPackage.status_code == "OPEN")
                             .with_for_update())
    if current is not None:
        return current
    no = (session.scalar(select(func.max(PackPackage.package_no)).where(PackPackage.document_id == doc.document_id)) or 0) + 1
    row = PackPackage(company_id=company_id, document_id=doc.document_id, package_no=no, packed_by_user_id=user_id)
    session.add(row)
    session.flush()
    return row


def new_package(company_id: int, document_id: int, user_id: int | None) -> int:
    """بستهٔ باز فعلی را می‌بندد (اگر خالی نیست) و بستهٔ جدید باز می‌کند."""
    with new_session() as session:
        doc = _document(session, company_id, document_id)
        current = session.scalar(select(PackPackage).where(PackPackage.document_id == document_id, PackPackage.status_code == "OPEN"))
        if current is not None:
            empty = not session.scalar(select(func.count()).where(PackPackageLine.package_id == current.package_id))
            if empty:
                return current.package_id
            current.status_code, current.closed_at = "CLOSED", datetime.datetime.now(datetime.timezone.utc)
            session.flush()
        row = _open_package(session, company_id, doc, user_id)
        session.commit()
        return row.package_id


def _resolve(company_id: int, code: str) -> tuple[int, decimal.Decimal] | None:
    from peecha import numerals
    from peecha.services import unit_conversion

    text = numerals.to_ascii_digits((code or "").strip())
    if not text:
        return None
    match = unit_conversion.resolve_barcode(company_id, text, with_price=False)
    if match is not None:
        return match.item_id, decimal.Decimal(match.factor)
    with new_session() as session:
        item_id = session.scalar(select(Item.item_id).join(DetailAccount, DetailAccount.detail_account_id == Item.item_detail_account_id)
                                 .where(Item.company_id == company_id, func.upper(DetailAccount.code) == text.upper()))
    return (item_id, decimal.Decimal(1)) if item_id else None


def pack(company_id: int, document_id: int, user_id: int | None, code: str | None = None, *, item_id: int | None = None,
         quantity: decimal.Decimal | None = None) -> SimpleNamespace:
    """یک اسکن یا یک ردیف دستی را در بستهٔ باز می‌گذارد. quantity به واحد پایه است؛ برای اسکن، تعداد واحد اسکن‌شده."""
    factor = decimal.Decimal(1)
    if item_id is None:
        hit = _resolve(company_id, code or "")
        if hit is None:
            raise ValueError(f"کالایی با «{code}» پیدا نشد.")
        item_id, factor = hit
    amount = (quantity or decimal.Decimal(1)) * factor
    if amount <= 0:
        raise ValueError("مقدار بسته‌بندی باید مثبت باشد.")
    with new_session() as session:
        doc = _document(session, company_id, document_id)
        session.execute(select(CommercialDocument.document_id).where(CommercialDocument.document_id == document_id).with_for_update())
        lines = [ln for ln in _lines(session, document_id) if ln.item_id == item_id]
        if not lines:
            raise ValueError("این کالا در این سند نیست.")
        if sum((ln.remaining for ln in lines), _ZERO) < amount:
            if any(ln.picked for ln in lines) and sum((ln.packable for ln in lines), _ZERO) < sum((ln.ordered for ln in lines), _ZERO):
                raise ValueError("این مقدار هنوز جمع‌آوری نشده است؛ اول کار جمع‌آوری را انجام دهید.")
            raise ValueError("بیش از مقدار سند است؛ این کالا قبلاً کامل بسته‌بندی شده است.")
        package = _open_package(session, company_id, doc, user_id)
        left = amount
        for ln in lines:
            take = min(ln.remaining, left)
            if take > 0:
                session.add(PackPackageLine(package_id=package.package_id, document_line_id=ln.line_id, item_id=item_id,
                                            quantity_base=take, packed_by_user_id=user_id))
                left -= take
        session.commit()
        remaining = sum((ln.remaining for ln in lines), _ZERO) - amount
        return SimpleNamespace(package_id=package.package_id, package_no=package.package_no, item_id=item_id, quantity=amount,
                               remaining=remaining)


def remove_line(company_id: int, package_line_id: int) -> None:
    with new_session() as session:
        row = session.get(PackPackageLine, package_line_id)
        package = session.get(PackPackage, row.package_id) if row is not None else None
        if package is None or package.company_id != company_id:
            raise ValueError("ردیف بسته نامعتبر است.")
        if package.status_code != "OPEN":
            raise ValueError("فقط از بستهٔ باز می‌شود کالا برداشت.")
        session.delete(row)
        session.commit()


def close_package(company_id: int, package_id: int, weight_kg: decimal.Decimal | None = None,
                  dimensions_cm: tuple | None = None, notes: str | None = None) -> None:
    with new_session() as session:
        p = session.get(PackPackage, package_id)
        if p is None or p.company_id != company_id:
            raise ValueError("بسته نامعتبر است.")
        if p.status_code == "SHIPPED":
            raise ValueError("بستهٔ ارسال‌شده تغییر نمی‌کند.")
        if not session.scalar(select(func.count()).where(PackPackageLine.package_id == package_id)):
            raise ValueError("بستهٔ خالی بسته نمی‌شود.")
        if weight_kg is not None and weight_kg < 0:
            raise ValueError("وزن نمی‌تواند منفی باشد.")
        p.weight_kg = weight_kg
        if dimensions_cm:
            p.length_cm, p.width_cm, p.height_cm = dimensions_cm
        p.notes = (notes or "").strip() or None
        p.status_code, p.closed_at = "CLOSED", p.closed_at or datetime.datetime.now(datetime.timezone.utc)
        session.commit()


def reopen_package(company_id: int, package_id: int) -> None:
    with new_session() as session:
        p = session.get(PackPackage, package_id)
        if p is None or p.company_id != company_id or p.status_code != "CLOSED":
            raise ValueError("فقط بستهٔ بسته‌شده و ارسال‌نشده باز می‌شود.")
        if session.scalar(select(PackPackage.package_id).where(PackPackage.document_id == p.document_id,
                                                               PackPackage.status_code == "OPEN")):
            raise ValueError("این سند یک بستهٔ باز دیگر دارد؛ اول آن را ببندید.")
        p.status_code, p.closed_at = "OPEN", None
        session.commit()


def ship(company_id: int, document_id: int, user_id: int | None, method_code: str, carrier: str | None = None,
         tracking_no: str | None = None, cost: decimal.Decimal = _ZERO, allow_partial: bool = False) -> int:
    """ارسال همهٔ بسته‌های بسته‌شدهٔ سند در یک حمل؛ بستهٔ باز یا اقلام بسته‌بندی‌نشده مانع است مگر ارسال ناقص خواسته شود."""
    from peecha.services import commercial_contracts

    if method_code not in SHIPPING_METHODS:
        raise ValueError("روش حمل نامعتبر است.")
    with new_session() as session:
        _document(session, company_id, document_id)
        packages = list(session.scalars(select(PackPackage).where(PackPackage.document_id == document_id)
                                        .order_by(PackPackage.package_no).with_for_update()))
        if any(p.status_code == "OPEN" for p in packages):
            raise ValueError("یک بسته هنوز باز است؛ اول آن را ببندید.")
        ready = [p for p in packages if p.status_code == "CLOSED"]
        if not ready:
            raise ValueError("بستهٔ آمادهٔ ارسالی نیست.")
        short = [ln for ln in _lines(session, document_id) if ln.packed < ln.ordered]
        if short and not allow_partial:
            raise ValueError(f"{len(short)} ردیف سند کامل بسته‌بندی نشده است؛ برای ارسال ناقص تایید کنید.")
        ids = [p.package_id for p in ready]
    shipment_id = commercial_contracts.create_shipment(document_id, method_code, (carrier or "").strip() or None,
                                                       (tracking_no or "").strip() or None, cost or _ZERO)
    commercial_contracts.mark_shipment_shipped(shipment_id)
    with new_session() as session:
        for p in session.scalars(select(PackPackage).where(PackPackage.package_id.in_(ids))):
            p.status_code, p.shipment_id = "SHIPPED", shipment_id
        session.commit()
    return shipment_id


def packing_list(company_id: int, document_id: int) -> tuple[list[str], list[list]]:
    """سرستون‌ها و ردیف‌های فهرست بسته‌بندی برای چاپ یا Excel."""
    headers = ["بسته", "کالا", "مقدار", "وزن (کیلوگرم)", "ابعاد (سانتی‌متر)", "وضعیت"]
    rows = []
    for p in list_packages(company_id, document_id):
        dims = "×".join(str(v) for v in (p.length_cm, p.width_cm, p.height_cm) if v is not None)
        for i, ln in enumerate(p.lines):
            rows.append([p.package_no if i == 0 else "", ln.item_label, ln.quantity, p.weight_kg if i == 0 else "",
                         dims if i == 0 else "", p.status_label if i == 0 else ""])
    return headers, rows
