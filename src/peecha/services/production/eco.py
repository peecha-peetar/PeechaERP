"""R372: تغییر مهندسی محصول (ECO) روی نسخه‌های فهرست مواد.

- هر درخواست برای یک محصول و یک نسخهٔ فعال فهرست مواد (نسخهٔ مبنا) است؛ ردیف‌ها: افزودن جزء، تغییر مقدار یا ضایعات،
  جایگزینی جزء با کالای دیگر و حذف جزء. مقدار قبلی هنگام ذخیره از نسخهٔ مبنا برداشته می‌شود.
- پیش‌نویس ← ارسال‌شده ← تاییدشده یا ردشده ← اجراشده؛ لغو تا پیش از اجرا. ردشده پس از ویرایش دوباره پیش‌نویس می‌شود.
  تاییدکننده: مدیر سیستم یا دارندهٔ مجوز «تایید» همین فرم؛ درخواست‌دهنده درخواست خودش را تایید نمی‌کند (جز مدیر سیستم).
- اجرا: نسخهٔ جدید از روی نسخهٔ مبنا با همان سرویس‌های فهرست مواد ساخته می‌شود (همان بررسی‌های جزء، حلقه و قفل)؛ اگر یکی از
  ردیف‌ها پذیرفته نشود نسخهٔ نیمه‌کاره حذف می‌شود. نسخهٔ جدید از تاریخ اجرا (یا امروز اگر گذشته باشد) معتبر است و اعتبار
  نسخهٔ مبنا روز قبلش پایان می‌یابد؛ اگر تاریخ اجرا رسیده باشد نسخهٔ جدید پیش‌فرض می‌شود. دستورهای تولید موجود دست نمی‌خورند.
- نسخهٔ مبنایی که با درخواست دیگری جایگزین شده، مبنای درخواست جدید نمی‌شود.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import BomHeader, BomLine, Item, StockBalance
from peecha.db.models.production import EcoLine, EcoOrder, ProductionOrder
from peecha.services.production import common as c
from peecha.services.production import master as pm

ZERO = decimal.Decimal(0)
FORM_CODE = "prd_eco"
STATUSES = {"DRAFT": "پیش‌نویس", "SUBMITTED": "ارسال‌شده", "APPROVED": "تاییدشده", "REJECTED": "ردشده",
            "IMPLEMENTED": "اجراشده", "CANCELLED": "لغوشده"}
REASONS = {"DESIGN": "بهبود طراحی", "COST": "کاهش هزینه", "QUALITY": "مشکل کیفیت", "SUPPLY": "تامین مواد",
           "CUSTOMER": "درخواست مشتری", "REGULATION": "الزام قانونی یا استاندارد", "OTHER": "سایر"}
ACTIONS = {"ADD": "افزودن جزء", "CHANGE": "تغییر مقدار", "REPLACE": "جایگزینی جزء", "REMOVE": "حذف جزء"}
DISPOSITIONS = {"USE_UP": "مصرف تا اتمام موجودی", "REWORK": "اصلاح و مصرف", "SCRAP": "کنار گذاشتن موجودی قدیمی"}
OPEN_ORDERS = ("DRAFT", "PLANNED", "RELEASED", "IN_PROGRESS", "ON_HOLD")


@dataclass
class LineFields:
    action_code: str
    component_item_id: int | None = None   # برای افزودن؛ برای بقیه از ردیف نسخهٔ مبنا
    base_line_no: int | None = None
    new_item_id: int | None = None          # جایگزینی
    new_quantity: decimal.Decimal | None = None
    new_scrap_percent: decimal.Decimal | None = None
    notes: str = ""


@dataclass
class EcoFields:
    title: str
    item_id: int
    base_bom_id: int
    effective_date: datetime.date
    reason_code: str = "DESIGN"
    description: str = ""
    stock_disposition: str = "USE_UP"
    lines: list[LineFields] = field(default_factory=list)


@dataclass
class EcoRow:
    eco_id: int
    eco_no: int
    title: str
    item_id: int
    item_label: str
    base_bom_id: int
    base_version: int
    new_bom_id: int | None
    new_version: int | None
    reason_code: str
    description: str
    effective_date: datetime.date
    stock_disposition: str
    status_code: str
    requested_by_user_id: int | None
    decision_note: str
    created_at: datetime.datetime
    implemented_at: datetime.datetime | None
    lines: list[SimpleNamespace] = field(default_factory=list)

    @property
    def status_label(self) -> str:
        return STATUSES[self.status_code]

    @property
    def reason_label(self) -> str:
        return REASONS.get(self.reason_code, self.reason_code)

    @property
    def code(self) -> str:
        return f"ECO-{self.eco_no:04d}"


def _eco(session, company_id: int, eco_id: int) -> EcoOrder:
    row = session.get(EcoOrder, eco_id)
    if row is None or row.company_id != company_id:
        raise ValueError("درخواست تغییر مهندسی نامعتبر است.")
    return row


def _superseded_by(session, base_bom_id: int, except_eco: int | None = None) -> EcoOrder | None:
    q = select(EcoOrder).where(EcoOrder.base_bom_id == base_bom_id, EcoOrder.status_code == "IMPLEMENTED")
    if except_eco is not None:
        q = q.where(EcoOrder.eco_id != except_eco)
    return session.scalar(q.limit(1))


def _qty(value) -> decimal.Decimal | None:
    return None if value in (None, "") else decimal.Decimal(value)


def _clean_lines(session, company_id: int, item_id: int, base_bom_id: int, lines: list[LineFields]) -> list[dict]:
    if not lines:
        raise ValueError("دست‌کم یک ردیف تغییر (افزودن، تغییر، جایگزینی یا حذف جزء) لازم است.")
    base = {ln.line_no: ln for ln in session.scalars(select(BomLine).where(BomLine.bom_id == base_bom_id))}
    in_base = {ln.component_item_id for ln in base.values()}
    out, touched, added = [], set(), set()
    for f in lines:
        if f.action_code not in ACTIONS:
            raise ValueError("نوع تغییر ردیف نامعتبر است.")
        quantity, scrap = _qty(f.new_quantity), _qty(f.new_scrap_percent)
        if quantity is not None and quantity <= 0:
            raise ValueError("مقدار جدید باید بزرگ‌تر از صفر باشد.")
        if scrap is not None and not ZERO <= scrap < 100:
            raise ValueError("درصد ضایعات نامعتبر است.")
        row = dict(action_code=f.action_code, base_line_no=None, component_item_id=None, new_item_id=None, old_quantity=None,
                   new_quantity=quantity, new_scrap_percent=scrap, notes=(f.notes or "").strip()[:300] or None)
        if f.action_code == "ADD":
            if not f.component_item_id:
                raise ValueError("کالای جزء جدید را انتخاب کنید.")
            comp = c.item_of(session, company_id, f.component_item_id)
            if comp.item_id == item_id:
                raise ValueError("یک کالا نمی‌تواند جزو مواد خودش باشد.")
            if comp.item_id in in_base or comp.item_id in added:
                raise ValueError(f"«{c.item_label(session, comp.item_id)}» در فهرست مواد هست؛ برای آن «تغییر مقدار» را انتخاب کنید.")
            if quantity is None:
                raise ValueError("مقدار جزء جدید را وارد کنید.")
            added.add(comp.item_id)
            row["component_item_id"] = comp.item_id
        else:
            line = base.get(f.base_line_no)
            if line is None:
                raise ValueError("ردیف نسخهٔ مبنا را انتخاب کنید.")
            if line.line_no in touched:
                raise ValueError(f"ردیف {line.line_no} نسخهٔ مبنا دو بار در درخواست آمده است.")
            touched.add(line.line_no)
            row.update(base_line_no=line.line_no, component_item_id=line.component_item_id, old_quantity=line.quantity_per)
            if f.action_code == "CHANGE":
                if quantity is None and scrap is None:
                    raise ValueError("برای تغییر، مقدار یا درصد ضایعات جدید را وارد کنید.")
                if (quantity is None or quantity == line.quantity_per) and (scrap is None or scrap == (line.scrap_percent or ZERO)):
                    raise ValueError(f"مقدار ردیف {line.line_no} تغییری نکرده است.")
            elif f.action_code == "REPLACE":
                if not f.new_item_id:
                    raise ValueError("کالای جایگزین را انتخاب کنید.")
                new = c.item_of(session, company_id, f.new_item_id)
                if new.item_id == line.component_item_id or new.item_id == item_id:
                    raise ValueError("کالای جایگزین باید کالای دیگری باشد.")
                if new.item_id in in_base or new.item_id in added:
                    raise ValueError(f"«{c.item_label(session, new.item_id)}» در فهرست مواد هست.")
                added.add(new.item_id)
                row["new_item_id"] = new.item_id
            else:
                row["new_quantity"] = row["new_scrap_percent"] = None
        out.append(row)
    return out


def _check_base(session, company_id: int, item_id: int, base_bom_id: int, eco_id: int | None = None) -> BomHeader:
    c.item_of(session, company_id, item_id)
    bom = session.get(BomHeader, base_bom_id)
    if bom is None or bom.finished_item_id != item_id:
        raise ValueError("نسخهٔ مبنای فهرست مواد برای این محصول نیست.")
    if bom.status_code != "ACTIVE":
        raise ValueError("نسخهٔ مبنا باید فعال باشد.")
    other = _superseded_by(session, base_bom_id, eco_id)
    if other is not None:
        raise ValueError(f"نسخهٔ مبنا با درخواست ECO-{other.eco_no:04d} جایگزین شده است؛ درخواست را روی نسخهٔ جدید ثبت کنید.")
    return bom


def save_eco(company_id: int, user_id: int | None, f: EcoFields, eco_id: int | None = None, *, submit: bool = False) -> int:
    title = (f.title or "").strip()
    if not title:
        raise ValueError("عنوان درخواست تغییر را بنویسید.")
    if f.reason_code not in REASONS or f.stock_disposition not in DISPOSITIONS:
        raise ValueError("علت یا تکلیف موجودی نامعتبر است.")
    if f.effective_date is None:
        raise ValueError("تاریخ اجرا را وارد کنید.")
    with new_session() as session:
        base = _check_base(session, company_id, f.item_id, f.base_bom_id, eco_id)
        if base.valid_from and f.effective_date <= base.valid_from:
            raise ValueError("تاریخ اجرا باید بعد از شروع اعتبار نسخهٔ مبنا باشد.")
        lines = _clean_lines(session, company_id, f.item_id, f.base_bom_id, f.lines)
        if eco_id is None:
            row = EcoOrder(company_id=company_id, requested_by_user_id=user_id, eco_no=(session.scalar(
                select(func.max(EcoOrder.eco_no)).where(EcoOrder.company_id == company_id)) or 0) + 1)
            session.add(row)
        else:
            row = _eco(session, company_id, eco_id)
            if row.status_code not in ("DRAFT", "REJECTED"):
                raise ValueError("درخواست ارسال‌شده، تاییدشده یا اجراشده ویرایش نمی‌شود.")
            for old in session.scalars(select(EcoLine).where(EcoLine.eco_id == row.eco_id)):
                session.delete(old)
        row.title, row.item_id, row.base_bom_id = title, f.item_id, f.base_bom_id
        row.reason_code, row.description = f.reason_code, (f.description or "").strip() or None
        row.effective_date, row.stock_disposition = f.effective_date, f.stock_disposition
        row.status_code = "SUBMITTED" if submit else "DRAFT"
        row.decision_note, row.decided_by_user_id, row.decided_at = None, None, None
        session.flush()
        for n, ln in enumerate(lines, start=1):
            session.add(EcoLine(eco_id=row.eco_id, line_no=n, **ln))
        c.audit(session, company_id, user_id, "ECO", row.eco_id, "CREATE" if eco_id is None else "SAVE",
                {"status": row.status_code, "lines": len(lines)})
        session.commit()
        return row.eco_id


def submit(company_id: int, user_id: int | None, eco_id: int) -> None:
    with new_session() as session:
        row = _eco(session, company_id, eco_id)
        if row.status_code != "DRAFT":
            raise ValueError("فقط درخواست پیش‌نویس ارسال می‌شود.")
        row.status_code = "SUBMITTED"
        c.audit(session, company_id, user_id, "ECO", eco_id, "SUBMIT", {})
        session.commit()


def can_decide(company_id: int, user_id: int) -> bool:
    from peecha.services import roles

    return roles.is_manager(user_id, company_id) or roles.user_has_permission(user_id, company_id, FORM_CODE, "APPROVE")


def _check_decider(company_id: int, user_id: int, row: EcoOrder, status: str = "SUBMITTED") -> None:
    from peecha.services import roles

    if row.status_code != status:
        raise ValueError("فقط درخواست ارسال‌شده تایید یا رد می‌شود." if status == "SUBMITTED" else "فقط درخواست تاییدشده اجرا می‌شود.")
    if not can_decide(company_id, user_id):
        raise ValueError("تایید و اجرای تغییر مهندسی با دارندهٔ مجوز تایید همین فرم است.")
    if status == "SUBMITTED" and row.requested_by_user_id == user_id and not roles.is_manager(user_id, company_id):
        raise ValueError("درخواست تغییر خودتان را نمی‌توانید تایید یا رد کنید.")


def approve(company_id: int, user_id: int, eco_id: int, note: str | None = None) -> None:
    with new_session() as session:
        row = _eco(session, company_id, eco_id)
        _check_decider(company_id, user_id, row)
        _check_base(session, company_id, row.item_id, row.base_bom_id, eco_id)
        row.status_code, row.decision_note = "APPROVED", (note or "").strip() or None
        row.decided_by_user_id, row.decided_at = user_id, datetime.datetime.now(datetime.timezone.utc)
        c.audit(session, company_id, user_id, "ECO", eco_id, "APPROVE", {"note": row.decision_note})
        session.commit()


def reject(company_id: int, user_id: int, eco_id: int, reason: str) -> None:
    if not (reason or "").strip():
        raise ValueError("دلیل رد درخواست را بنویسید.")
    with new_session() as session:
        row = _eco(session, company_id, eco_id)
        _check_decider(company_id, user_id, row)
        row.status_code, row.decision_note = "REJECTED", reason.strip()
        row.decided_by_user_id, row.decided_at = user_id, datetime.datetime.now(datetime.timezone.utc)
        c.audit(session, company_id, user_id, "ECO", eco_id, "REJECT", {"reason": row.decision_note})
        session.commit()


def cancel(company_id: int, user_id: int | None, eco_id: int, reason: str) -> None:
    if not (reason or "").strip():
        raise ValueError("دلیل لغو را بنویسید.")
    with new_session() as session:
        row = _eco(session, company_id, eco_id)
        if row.status_code in ("IMPLEMENTED", "CANCELLED"):
            raise ValueError("درخواست اجراشده یا لغوشده دوباره لغو نمی‌شود.")
        row.status_code, row.decision_note = "CANCELLED", reason.strip()
        c.audit(session, company_id, user_id, "ECO", eco_id, "CANCEL", {"reason": row.decision_note})
        session.commit()


def delete_eco(company_id: int, user_id: int | None, eco_id: int) -> None:
    with new_session() as session:
        row = _eco(session, company_id, eco_id)
        if row.status_code not in ("DRAFT", "REJECTED"):
            raise ValueError("فقط درخواست پیش‌نویس یا ردشده حذف می‌شود.")
        c.audit(session, company_id, user_id, "ECO", eco_id, "DELETE", {"eco_no": row.eco_no})
        session.delete(row)
        session.commit()


def _line_fields(cur: SimpleNamespace, **changes) -> pm.BomLineFields:
    values = dict(component_item_id=cur.item_id, quantity=cur.quantity, uom_id=cur.uom_id, scrap_percent=cur.scrap_percent,
                  quantity_type=cur.quantity_type, component_type=cur.component_type, warehouse_id=cur.warehouse_id,
                  operation_seq=cur.operation_seq, substitute_item_id=cur.substitute_item_id, is_optional=cur.is_optional,
                  notes=cur.notes)
    values.update(changes)
    return pm.BomLineFields(**values)


def implement(company_id: int, user_id: int, eco_id: int) -> int:
    """نسخهٔ جدید فهرست مواد را می‌سازد و شناسه‌اش را برمی‌گرداند."""
    today = datetime.date.today()
    with new_session() as session:
        row = _eco(session, company_id, eco_id)
        _check_decider(company_id, user_id, row, "APPROVED")
        base = _check_base(session, company_id, row.item_id, row.base_bom_id, eco_id)
        effective = max(row.effective_date, today)
        if base.valid_from and effective <= base.valid_from:
            raise ValueError("تاریخ اجرا باید بعد از شروع اعتبار نسخهٔ مبنا باشد.")
        lines = list(session.scalars(select(EcoLine).where(EcoLine.eco_id == eco_id).order_by(EcoLine.line_no)))
        code, title, item_id, base_bom_id = f"ECO-{row.eco_no:04d}", row.title, row.item_id, row.base_bom_id
        base_fields = pm.BomFields(batch_size_qty=base.batch_size_qty, scrap_percent=base.scrap_percent, name=base.name,
                                   valid_from=base.valid_from, valid_to=base.valid_to, routing_id=base.routing_id,
                                   production_time_minutes=base.production_time_minutes, notes=base.notes, status_code=base.status_code)
    new_to = None if base_fields.valid_to is None or base_fields.valid_to < effective else base_fields.valid_to
    new_bom = pm.create_bom_version(company_id, item_id, pm.BomFields(
        batch_size_qty=base_fields.batch_size_qty, scrap_percent=base_fields.scrap_percent, name=base_fields.name,
        valid_from=effective, valid_to=new_to, routing_id=base_fields.routing_id,
        production_time_minutes=base_fields.production_time_minutes, notes=f"{code}: {title}"[:500]),
        copy_from_bom_id=base_bom_id, make_default=False, user_id=user_id)
    try:
        current = {x.line_no: x for x in pm.bom_components(company_id, new_bom)}
        for ln in lines:
            if ln.action_code == "ADD":
                pm.add_bom_component(company_id, new_bom, pm.BomLineFields(
                    ln.component_item_id, ln.new_quantity, scrap_percent=ln.new_scrap_percent or ZERO, notes=ln.notes), user_id)
                continue
            cur = current[ln.base_line_no]
            if ln.action_code == "REMOVE":
                pm.remove_bom_component(company_id, cur.bom_line_id, user_id)
            elif ln.action_code == "REPLACE":
                pm.update_bom_component(company_id, cur.bom_line_id, _line_fields(
                    cur, component_item_id=ln.new_item_id, uom_id=None, substitute_item_id=None,
                    quantity=ln.new_quantity or cur.base_quantity,
                    scrap_percent=cur.scrap_percent if ln.new_scrap_percent is None else ln.new_scrap_percent), user_id, reason=code)
            else:
                pm.update_bom_component(company_id, cur.bom_line_id, _line_fields(
                    cur, quantity=ln.new_quantity or cur.quantity,
                    scrap_percent=cur.scrap_percent if ln.new_scrap_percent is None else ln.new_scrap_percent), user_id, reason=code)
        problems = [p for p in pm.validate_bom(company_id, new_bom) if "جزء اجباری" in p or "حلقه" in p]
        if problems:
            raise ValueError(problems[0])
    except ValueError as exc:
        pm.delete_bom_version(company_id, new_bom, user_id)
        raise ValueError(f"اجرای {code} انجام نشد: {exc}") from exc
    if base_fields.valid_to is None or base_fields.valid_to >= effective:
        base_fields.valid_to = effective - datetime.timedelta(days=1)
        pm.update_bom(company_id, base_bom_id, base_fields, user_id, reason=code)
    if effective <= today:
        pm.set_default_bom(company_id, new_bom, user_id)
    with new_session() as session:
        row = _eco(session, company_id, eco_id)
        row.status_code, row.new_bom_id = "IMPLEMENTED", new_bom
        row.implemented_by_user_id, row.implemented_at = user_id, datetime.datetime.now(datetime.timezone.utc)
        c.audit(session, company_id, user_id, "ECO", eco_id, "IMPLEMENT", {"new_bom_id": new_bom, "effective": str(effective)})
        session.commit()
    return new_bom


def list_ecos(company_id: int, item_id: int | None = None, status: str | None = None) -> list[EcoRow]:
    with new_session() as session:
        q = select(EcoOrder).where(EcoOrder.company_id == company_id)
        if item_id is not None:
            q = q.where(EcoOrder.item_id == item_id)
        if status is not None:
            q = q.where(EcoOrder.status_code == status)
        rows = list(session.scalars(q.order_by(EcoOrder.eco_no.desc())))
        ids = [r.eco_id for r in rows] or [0]
        lines = list(session.scalars(select(EcoLine).where(EcoLine.eco_id.in_(ids)).order_by(EcoLine.eco_id, EcoLine.line_no)))
        labels = c.item_labels(session, [r.item_id for r in rows] + [ln.component_item_id for ln in lines]
                               + [ln.new_item_id for ln in lines])
        versions = dict(session.execute(select(BomHeader.bom_id, BomHeader.version_no).where(BomHeader.bom_id.in_(
            [r.base_bom_id for r in rows] + [r.new_bom_id for r in rows if r.new_bom_id] or [0]))).all())
    by_eco: dict[int, list[SimpleNamespace]] = {}
    for ln in lines:
        by_eco.setdefault(ln.eco_id, []).append(SimpleNamespace(
            line_no=ln.line_no, action_code=ln.action_code, action_label=ACTIONS[ln.action_code], base_line_no=ln.base_line_no,
            component_item_id=ln.component_item_id, component_label=labels.get(ln.component_item_id, ""),
            new_item_id=ln.new_item_id, new_item_label=labels.get(ln.new_item_id, ""), old_quantity=ln.old_quantity,
            new_quantity=ln.new_quantity, new_scrap_percent=ln.new_scrap_percent, notes=ln.notes or ""))
    return [EcoRow(r.eco_id, r.eco_no, r.title, r.item_id, labels.get(r.item_id, ""), r.base_bom_id, versions.get(r.base_bom_id, 0),
                   r.new_bom_id, versions.get(r.new_bom_id), r.reason_code, r.description or "", r.effective_date,
                   r.stock_disposition, r.status_code, r.requested_by_user_id, r.decision_note or "", r.created_at,
                   r.implemented_at, by_eco.get(r.eco_id, [])) for r in rows]


def get_eco(company_id: int, eco_id: int) -> EcoRow:
    row = next((r for r in list_ecos(company_id) if r.eco_id == eco_id), None)
    if row is None:
        raise ValueError("درخواست تغییر مهندسی نامعتبر است.")
    return row


def _unit_costs(session, company_id: int, item_ids) -> dict[int, decimal.Decimal]:
    """میانگین موزون بهای موجودی هر کالا در همهٔ انبارها."""
    rows = session.execute(select(StockBalance.item_id, func.sum(StockBalance.quantity_on_hand),
                                  func.sum(StockBalance.quantity_on_hand * StockBalance.average_unit_cost))
                           .where(StockBalance.company_id == company_id, StockBalance.item_id.in_(list(item_ids) or [0]))
                           .group_by(StockBalance.item_id)).all()
    return {i: (v / q) if q else ZERO for i, q, v in rows}


def impact(company_id: int, eco_id: int) -> SimpleNamespace:
    """اثر درخواست پیش از اجرا: دستورهای باز روی نسخهٔ مبنا، محصولاتی که این کالا جزوشان است، موجودی جزءهای کنارگذاشته
    (و این‌که در فهرست مواد دیگری مصرف می‌شوند یا نه) و برآورد تغییر بهای مواد هر واحد با میانگین بهای موجودی."""
    from peecha.services.production import orders as po

    eco = get_eco(company_id, eco_id)
    with new_session() as session:
        base = session.get(BomHeader, eco.base_bom_id)
        batch = decimal.Decimal(base.batch_size_qty or 1)
        orders = [SimpleNamespace(order_id=o.order_id, order_code=o.order_code, status_label=po.STATUS_LABELS.get(o.status_code, o.status_code),
                                  remaining_qty=o.remaining_qty, due_date=o.due_date)
                  for o in session.scalars(select(ProductionOrder).where(ProductionOrder.bom_id == eco.base_bom_id,
                                                                        ProductionOrder.status_code.in_(OPEN_ORDERS))
                                           .order_by(ProductionOrder.due_date))]
        base_lines = {ln.line_no: ln for ln in session.scalars(select(BomLine).where(BomLine.bom_id == eco.base_bom_id))}
        ids = {ln.component_item_id for ln in base_lines.values()} | {ln.component_item_id for ln in eco.lines} | {
            ln.new_item_id for ln in eco.lines if ln.new_item_id}
        costs = _unit_costs(session, company_id, ids)
        stock = dict(session.execute(select(StockBalance.item_id, func.sum(StockBalance.quantity_on_hand))
                                     .where(StockBalance.company_id == company_id, StockBalance.item_id.in_(list(ids) or [0]))
                                     .group_by(StockBalance.item_id)).all())
        components = []
        for ln in eco.lines:
            dropped = ln.component_item_id if ln.action_code in ("REMOVE", "REPLACE") else None
            other_use = None
            if dropped:
                other_use = session.scalar(select(func.count(func.distinct(BomHeader.bom_id))).join(BomLine, BomLine.bom_id == BomHeader.bom_id)
                                           .where(BomLine.component_item_id == dropped, BomHeader.status_code == "ACTIVE",
                                                  BomHeader.bom_id != eco.base_bom_id))
            components.append(SimpleNamespace(line_no=ln.line_no, action_label=ln.action_label, item_label=ln.component_label,
                                              new_item_label=ln.new_item_label, on_hand=decimal.Decimal(stock.get(ln.component_item_id) or 0),
                                              used_elsewhere=other_use, obsolete=bool(dropped) and not other_use
                                              and decimal.Decimal(stock.get(dropped) or 0) > 0))

        def per_unit(lines) -> decimal.Decimal:
            return sum((decimal.Decimal(q) * costs.get(i, ZERO) for i, q in lines), ZERO) / batch

        before = [(ln.component_item_id, decimal.Decimal(ln.quantity_per) * decimal.Decimal(ln.conversion_factor or 1))
                  for ln in base_lines.values() if not ln.is_optional]
        after = {n: (ln.component_item_id, decimal.Decimal(ln.quantity_per) * decimal.Decimal(ln.conversion_factor or 1))
                 for n, ln in base_lines.items() if not ln.is_optional}
        for ln in eco.lines:
            if ln.action_code == "ADD":
                after[("ADD", ln.line_no)] = (ln.component_item_id, ln.new_quantity)
            elif ln.base_line_no in after:
                item, quantity = after[ln.base_line_no]
                if ln.action_code == "REMOVE":
                    del after[ln.base_line_no]
                elif ln.action_code == "REPLACE":
                    after[ln.base_line_no] = (ln.new_item_id, ln.new_quantity or quantity)
                elif ln.new_quantity:
                    factor = decimal.Decimal(base_lines[ln.base_line_no].conversion_factor or 1)
                    after[ln.base_line_no] = (item, ln.new_quantity * factor)
        parents = [r for r in pm.where_used(company_id, eco.item_id) if r.status_code == "ACTIVE"]
        cost_before, cost_after = per_unit(before), per_unit(after.values())
    return SimpleNamespace(orders=orders, parents=parents, components=components,
                           cost_before=cost_before.quantize(decimal.Decimal("0.01")), cost_after=cost_after.quantize(decimal.Decimal("0.01")),
                           cost_delta=(cost_after - cost_before).quantize(decimal.Decimal("0.01")))


def compare_boms(company_id: int, bom_a: int, bom_b: int) -> list[SimpleNamespace]:
    """مقایسهٔ دو نسخهٔ فهرست مواد بر اساس کالای جزء (مقدار به واحد پایه): افزوده، حذف‌شده، تغییرکرده، بدون تغییر."""
    a = pm.bom_components(company_id, bom_a)
    b = pm.bom_components(company_id, bom_b)

    def totals(rows):
        out: dict[int, list] = {}
        for r in rows:
            entry = out.setdefault(r.item_id, [r.item_label, ZERO, ZERO])
            entry[1] += r.base_quantity
            entry[2] = max(entry[2], decimal.Decimal(r.scrap_percent or 0))
        return out

    ta, tb = totals(a), totals(b)
    order = list(dict.fromkeys([r.item_id for r in a] + [r.item_id for r in b]))
    result = []
    for item_id in order:
        x, y = ta.get(item_id), tb.get(item_id)
        status = "ADDED" if x is None else "REMOVED" if y is None else "CHANGED" if (x[1], x[2]) != (y[1], y[2]) else "SAME"
        result.append(SimpleNamespace(item_id=item_id, item_label=(x or y)[0], qty_a=x[1] if x else None, qty_b=y[1] if y else None,
                                      scrap_a=x[2] if x else None, scrap_b=y[2] if y else None, status_code=status,
                                      status_label={"ADDED": "افزوده", "REMOVED": "حذف‌شده", "CHANGED": "تغییرکرده",
                                                    "SAME": "بدون تغییر"}[status]))
    return result


def history(company_id: int, item_id: int) -> list[SimpleNamespace]:
    """تاریخچهٔ مهندسی محصول: نسخه‌های فهرست مواد با بازهٔ اعتبار و درخواست تغییری که هر نسخه را ساخته است."""
    versions = pm.list_bom_versions(company_id, item_id)
    made_by = {r.new_bom_id: r for r in list_ecos(company_id, item_id) if r.new_bom_id}
    return [SimpleNamespace(bom_id=v.bom_id, version_no=v.version_no, status_code=v.status_code, is_default=v.is_default,
                            valid_from=v.valid_from, valid_to=v.valid_to, component_count=v.component_count,
                            eco_code=made_by[v.bom_id].code if v.bom_id in made_by else "",
                            eco_title=made_by[v.bom_id].title if v.bom_id in made_by else "") for v in versions]


def pending_for(company_id: int, user_id: int) -> tuple[list[EcoRow], list[EcoRow]]:
    """(درخواست‌های منتظر تایید، درخواست‌های تاییدشدهٔ منتظر اجرا) برای دارندهٔ مجوز تایید؛ درخواست خود کاربر برای تایید
    نمی‌آید مگر مدیر سیستم باشد."""
    from peecha.services import roles

    if not can_decide(company_id, user_id):
        return [], []
    rows = [r for r in list_ecos(company_id) if r.status_code in ("SUBMITTED", "APPROVED")]
    manager = roles.is_manager(user_id, company_id)
    return ([r for r in rows if r.status_code == "SUBMITTED" and (r.requested_by_user_id != user_id or manager)],
            [r for r in rows if r.status_code == "APPROVED"])


def item_ids_with_bom(company_id: int) -> list[int]:
    with new_session() as session:
        return list(session.scalars(select(BomHeader.finished_item_id).join(Item, Item.item_id == BomHeader.finished_item_id)
                                    .where(Item.company_id == company_id, BomHeader.status_code == "ACTIVE").distinct()))
