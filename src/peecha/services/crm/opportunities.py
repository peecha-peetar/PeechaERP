"""فرصت فروش و قیف Kanban.

ورود به هر مرحله: کنترل فیلدهای الزامی، به‌روزرسانی احتمال، شروع SLA و ساخت فعالیت خودکار مرحله.
برنده‌شدن فقط وضعیت فرصت را می‌بندد؛ سند فروش واقعی (پیش‌فاکتور/سفارش/فاکتور) همیشه با سرویس فروش موجود ساخته
می‌شود (opportunity_sales) و اینجا فقط پیوندش نگه داشته می‌شود.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field

from sqlalchemy import func, or_, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.commercial import CustomerActivity
from peecha.db.models.crm import Lead, LeadSource, Opportunity, OpportunityDocument, OpportunityLine, PipelineStage
from peecha.services.crm import activities as act_service
from peecha.services.crm import common as c
from peecha.services.crm import pipelines as pl_service

ZERO = decimal.Decimal(0)


@dataclass
class OpportunityFields:
    title: str
    customer_detail_account_id: int | None = None
    lead_id: int | None = None
    owner_user_id: int | None = None
    pipeline_id: int | None = None
    stage_id: int | None = None
    amount: decimal.Decimal = ZERO
    probability_percent: decimal.Decimal | None = None
    expected_close_date: datetime.date | None = None
    source_id: int | None = None
    description: str | None = None


@dataclass
class LineFields:
    item_id: int | None
    quantity: decimal.Decimal = decimal.Decimal(1)
    unit_price: decimal.Decimal = ZERO
    discount_amount: decimal.Decimal = ZERO
    description: str | None = None


@dataclass
class OpportunityRow:
    opportunity_id: int
    opportunity_no: int
    title: str
    customer_detail_account_id: int | None
    customer_name: str
    lead_id: int | None
    lead_name: str
    owner_user_id: int | None
    owner_name: str
    pipeline_id: int
    stage_id: int
    stage_name: str
    stage_type: str
    amount: decimal.Decimal
    probability_percent: decimal.Decimal
    expected_close_date: datetime.date | None
    source_id: int | None
    source_name: str
    description: str | None
    status_code: str
    status_label: str
    lost_reason: str | None
    stage_entered_at: datetime.datetime
    sla_hours: int | None
    created_at: datetime.datetime
    closed_at: datetime.datetime | None
    document_ids: list[int] = field(default_factory=list)

    @property
    def weighted_amount(self) -> decimal.Decimal:
        return (decimal.Decimal(self.amount) * decimal.Decimal(self.probability_percent) / 100).quantize(decimal.Decimal("0.01"))

    @property
    def days_in_stage(self) -> int:
        return max(0, (c.now() - self.stage_entered_at).days)

    @property
    def sla_overdue(self) -> bool:
        return (self.status_code == "OPEN" and self.sla_hours is not None
                and (c.now() - self.stage_entered_at).total_seconds() > self.sla_hours * 3600)


def _stage(session, pipeline_id: int, stage_id: int) -> PipelineStage:
    st = session.get(PipelineStage, stage_id)
    if st is None or st.pipeline_id != pipeline_id:
        raise ValueError("مرحلهٔ قیف نامعتبر است.")
    return st


def _missing_fields(session, opp: Opportunity, stage: PipelineStage) -> list[str]:
    missing = []
    for key in stage.required_fields or []:
        if key == "amount" and not opp.amount:
            missing.append(key)
        elif key == "expected_close_date" and not opp.expected_close_date:
            missing.append(key)
        elif key == "customer" and not opp.customer_detail_account_id:
            missing.append(key)
        elif key == "owner" and not opp.owner_user_id:
            missing.append(key)
        elif key == "description" and not (opp.description or "").strip():
            missing.append(key)
        elif key == "lines" and not session.scalar(select(OpportunityLine.line_id).where(
                OpportunityLine.opportunity_id == opp.opportunity_id).limit(1)):
            missing.append(key)
    return missing


def _enter_stage(session, company_id: int, user_id: int, opp: Opportunity, stage: PipelineStage,
                 lost_reason: str | None = None) -> None:
    missing = _missing_fields(session, opp, stage)
    if missing:
        hint = " (برای مشتری‌شدن، سرنخ را به مشتری تبدیل کنید)" if "customer" in missing else ""
        raise ValueError(f"برای ورود به مرحلهٔ «{stage.name}» این موارد لازم است: "
                         + "، ".join(pl_service.STAGE_FIELDS[m] for m in missing) + hint)
    if stage.stage_type == "LOST" and not (lost_reason or opp.lost_reason or "").strip():
        raise ValueError("دلیل از دست رفتن فرصت را بنویسید.")
    opp.stage_id, opp.stage_entered_at = stage.stage_id, c.now()
    opp.probability_percent = stage.probability_percent
    opp.status_code = stage.stage_type if stage.stage_type in ("WON", "LOST") else "OPEN"
    opp.closed_at = c.now() if opp.status_code != "OPEN" else None
    if stage.stage_type == "LOST":
        opp.lost_reason = (lost_reason or "").strip() or opp.lost_reason
    elif stage.stage_type == "OPEN":
        opp.lost_reason = None
    auto = stage.auto_activity or {}
    if stage.stage_type == "OPEN" and auto.get("type") in c.ACTIVITY_TYPES:
        act_service.create_activity(company_id, user_id, act_service.ActivityFields(
            auto["type"], f"{auto.get('subject') or stage.next_action or stage.name} — {opp.title}"[:200],
            customer_detail_account_id=opp.customer_detail_account_id, lead_id=opp.lead_id,
            opportunity_id=opp.opportunity_id, assigned_to_user_id=opp.owner_user_id or user_id,
            due_date=datetime.date.today() + datetime.timedelta(days=int(auto.get("due_in_days") or 0))), session=session)


def _apply(session, company_id: int, opp: Opportunity, f: OpportunityFields) -> None:
    if not (f.title or "").strip():
        raise ValueError("عنوان فرصت الزامی است.")
    if decimal.Decimal(f.amount or 0) < 0:
        raise ValueError("مبلغ فرصت نمی‌تواند منفی باشد.")
    if f.customer_detail_account_id:
        da = session.get(DetailAccount, f.customer_detail_account_id)
        if da is None or da.company_id != company_id:
            raise ValueError("مشتری نامعتبر است.")
    if f.lead_id:
        lead = session.get(Lead, f.lead_id)
        if lead is None or lead.company_id != company_id:
            raise ValueError("سرنخ نامعتبر است.")
        f.customer_detail_account_id = f.customer_detail_account_id or lead.converted_customer_detail_account_id
    if not f.customer_detail_account_id and not f.lead_id:
        raise ValueError("فرصت باید به یک مشتری یا سرنخ مربوط باشد.")
    for k in ("title", "customer_detail_account_id", "lead_id", "owner_user_id", "amount", "expected_close_date",
              "source_id", "description"):
        v = getattr(f, k)
        setattr(opp, k, v.strip() if isinstance(v, str) else v)
    if f.probability_percent is not None:
        if not 0 <= decimal.Decimal(f.probability_percent) <= 100:
            raise ValueError("احتمال موفقیت باید بین ۰ تا ۱۰۰ باشد.")
        opp.probability_percent = f.probability_percent


def create_opportunity(company_id: int, user_id: int, f: OpportunityFields, lines: list[LineFields] | None = None) -> int:
    pipeline_id = f.pipeline_id or pl_service.ensure_default_pipeline(company_id)
    stages = pl_service.list_stages(company_id, pipeline_id)
    stage_id = f.stage_id or next((s.stage_id for s in stages if s.stage_type == "OPEN"), None)
    if stage_id is None:
        raise ValueError("قیف فروش هیچ مرحلهٔ بازی ندارد.")
    with new_session() as session:
        stage = _stage(session, pipeline_id, stage_id)
        opp = Opportunity(company_id=company_id, created_by_user_id=user_id, pipeline_id=pipeline_id, stage_id=stage_id,
                          opportunity_no=c.next_number(session, Opportunity, company_id, Opportunity.opportunity_no))
        _apply(session, company_id, opp, f)
        opp.owner_user_id = opp.owner_user_id or user_id
        session.add(opp)
        session.flush()
        if lines:
            _write_lines(session, opp, lines)
        probability = f.probability_percent
        _enter_stage(session, company_id, user_id, opp, stage)
        if probability is not None:
            opp.probability_percent = probability
        c.audit(session, company_id, user_id, "Opportunity", opp.opportunity_id, "CREATE",
                {"no": opp.opportunity_no, "title": opp.title, "customer": opp.customer_detail_account_id,
                 "lead": opp.lead_id, "amount": opp.amount, "stage": stage.code, "owner": opp.owner_user_id})
        session.commit()
        opp_id, owner, title = opp.opportunity_id, opp.owner_user_id, opp.title
    if owner != user_id:
        c.notify(company_id, owner, "CRM_OPPORTUNITY_ASSIGNED", "فرصت فروش تازه به شما واگذار شد", title, "CrmOpportunity", opp_id)
    return opp_id


def _get(session, company_id: int, opportunity_id: int) -> Opportunity:
    opp = session.get(Opportunity, opportunity_id)
    if opp is None or opp.company_id != company_id:
        raise ValueError("فرصت فروش نامعتبر است.")
    return opp


def update_opportunity(company_id: int, user_id: int, opportunity_id: int, f: OpportunityFields) -> None:
    with new_session() as session:
        opp = _get(session, company_id, opportunity_id)
        before = {k: getattr(opp, k) for k in ("title", "customer_detail_account_id", "owner_user_id", "amount",
                                                "probability_percent", "expected_close_date", "description")}
        _apply(session, company_id, opp, f)
        missing = _missing_fields(session, opp, session.get(PipelineStage, opp.stage_id))
        if missing and opp.status_code == "OPEN":
            raise ValueError("این فیلدها در مرحلهٔ فعلی الزامی‌اند: " + "، ".join(pl_service.STAGE_FIELDS[m] for m in missing))
        opp.updated_at = c.now()
        changes = {k: [v, getattr(opp, k)] for k, v in before.items() if v != getattr(opp, k)}
        if changes:
            c.audit(session, company_id, user_id, "Opportunity", opportunity_id, "UPDATE", changes)
        session.commit()
        new_owner, title = opp.owner_user_id, opp.title
    if "owner_user_id" in changes and new_owner and new_owner != user_id:
        c.notify(company_id, new_owner, "CRM_OPPORTUNITY_ASSIGNED", "فرصت فروش به شما واگذار شد", title, "CrmOpportunity", opportunity_id)


def move_stage(company_id: int, user_id: int, opportunity_id: int, stage_id: int, lost_reason: str | None = None) -> None:
    with new_session() as session:
        opp = _get(session, company_id, opportunity_id)
        if opp.stage_id == stage_id:
            return
        old = session.get(PipelineStage, opp.stage_id)
        stage = _stage(session, opp.pipeline_id, stage_id)
        _enter_stage(session, company_id, user_id, opp, stage, lost_reason)
        opp.updated_at = c.now()
        c.audit(session, company_id, user_id, "Opportunity", opportunity_id, "STAGE",
                {"stage": [old.code if old else None, stage.code], "status": opp.status_code, "lost_reason": lost_reason})
        session.commit()


def mark_won(company_id: int, user_id: int, opportunity_id: int) -> None:
    with new_session() as session:
        opp = _get(session, company_id, opportunity_id)
        won = session.scalar(select(PipelineStage.stage_id).where(PipelineStage.pipeline_id == opp.pipeline_id,
                                                                  PipelineStage.stage_type == "WON").order_by(PipelineStage.sort_order))
    if won is None:
        raise ValueError("قیف این فرصت مرحلهٔ «برنده» ندارد.")
    move_stage(company_id, user_id, opportunity_id, won)


def mark_lost(company_id: int, user_id: int, opportunity_id: int, reason: str) -> None:
    with new_session() as session:
        opp = _get(session, company_id, opportunity_id)
        lost = session.scalar(select(PipelineStage.stage_id).where(PipelineStage.pipeline_id == opp.pipeline_id,
                                                                   PipelineStage.stage_type == "LOST").order_by(PipelineStage.sort_order))
    if lost is None:
        raise ValueError("قیف این فرصت مرحلهٔ «بازنده» ندارد.")
    move_stage(company_id, user_id, opportunity_id, lost, reason)


def _write_lines(session, opp: Opportunity, lines: list[LineFields]) -> None:
    session.query(OpportunityLine).filter(OpportunityLine.opportunity_id == opp.opportunity_id).delete()
    total = ZERO
    for ln in lines:
        qty, price, disc = decimal.Decimal(ln.quantity), decimal.Decimal(ln.unit_price), decimal.Decimal(ln.discount_amount or 0)
        if qty <= 0 or price < 0 or disc < 0:
            raise ValueError("مقدار باید مثبت و قیمت و تخفیف نامنفی باشند.")
        if not ln.item_id and not (ln.description or "").strip():
            raise ValueError("برای هر ردیف کالا یا شرح لازم است.")
        session.add(OpportunityLine(opportunity_id=opp.opportunity_id, item_id=ln.item_id, quantity=qty, unit_price=price,
                                    discount_amount=disc, description=(ln.description or "").strip() or None))
        total += qty * price - disc
    if lines:
        opp.amount = max(ZERO, total).quantize(decimal.Decimal("0.01"))


def set_lines(company_id: int, user_id: int, opportunity_id: int, lines: list[LineFields]) -> decimal.Decimal:
    """اقلام پیشنهادی؛ مبلغ فرصت = جمع (مقدار × قیمت − تخفیف). قیمت‌گذاری رسمی در سند فروش انجام می‌شود."""
    with new_session() as session:
        opp = _get(session, company_id, opportunity_id)
        _write_lines(session, opp, lines)
        opp.updated_at = c.now()
        c.audit(session, company_id, user_id, "Opportunity", opportunity_id, "LINES", {"count": len(lines), "amount": opp.amount})
        session.commit()
        return opp.amount


def list_lines(company_id: int, opportunity_id: int) -> list[OpportunityLine]:
    with new_session() as session:
        _get(session, company_id, opportunity_id)
        rows = list(session.scalars(select(OpportunityLine).where(OpportunityLine.opportunity_id == opportunity_id)
                                    .order_by(OpportunityLine.line_id)))
        for r in rows:
            session.expunge(r)
        return rows


def delete_opportunity(company_id: int, user_id: int, opportunity_id: int) -> None:
    with new_session() as session:
        opp = _get(session, company_id, opportunity_id)
        if session.scalar(select(OpportunityDocument.document_id).where(OpportunityDocument.opportunity_id == opportunity_id).limit(1)):
            raise ValueError("برای این فرصت سند فروش صادر شده و قابل حذف نیست — آن را «بازنده» یا «برنده» ببندید.")
        session.query(CustomerActivity).filter(CustomerActivity.opportunity_id == opportunity_id).update({"opportunity_id": None})
        session.query(Lead).filter(Lead.converted_opportunity_id == opportunity_id).update({"converted_opportunity_id": None})
        c.audit(session, company_id, user_id, "Opportunity", opportunity_id, "DELETE", {"no": opp.opportunity_no, "title": opp.title})
        session.delete(opp)
        session.commit()


def link_document(company_id: int, user_id: int, opportunity_id: int, document_id: int, session=None) -> None:
    own = session is None
    session = session or new_session()
    try:
        _get(session, company_id, opportunity_id)
        if session.get(OpportunityDocument, (opportunity_id, document_id)) is None:
            session.add(OpportunityDocument(opportunity_id=opportunity_id, document_id=document_id))
            c.audit(session, company_id, user_id, "Opportunity", opportunity_id, "LINK_DOCUMENT", {"document": document_id})
        if own:
            session.commit()
    finally:
        if own:
            session.close()


# --- فهرست و Kanban ---------------------------------------------------------------------------------
def list_opportunities(company_id: int, *, pipeline_id: int | None = None, stage_id: int | None = None,
                       status: str | None = None, owner_user_id: int | None = None,
                       customer_detail_account_id: int | None = None, lead_id: int | None = None, search: str | None = None,
                       close_from: datetime.date | None = None, close_to: datetime.date | None = None,
                       opportunity_ids: list[int] | None = None, limit: int = 1000, offset: int = 0) -> list[OpportunityRow]:
    with new_session() as session:
        q = select(Opportunity, PipelineStage).join(PipelineStage, PipelineStage.stage_id == Opportunity.stage_id).where(
            Opportunity.company_id == company_id)
        for col, val in ((Opportunity.pipeline_id, pipeline_id), (Opportunity.stage_id, stage_id), (Opportunity.status_code, status),
                         (Opportunity.owner_user_id, owner_user_id), (Opportunity.lead_id, lead_id),
                         (Opportunity.customer_detail_account_id, customer_detail_account_id)):
            if val:
                q = q.where(col == val)
        if close_from:
            q = q.where(Opportunity.expected_close_date >= close_from)
        if close_to:
            q = q.where(Opportunity.expected_close_date <= close_to)
        if opportunity_ids:
            q = q.where(Opportunity.opportunity_id.in_(opportunity_ids))
        if search:
            q = q.where(or_(Opportunity.title.ilike(f"%{search.strip()}%"), Opportunity.description.ilike(f"%{search.strip()}%")))
        pairs = session.execute(q.order_by(Opportunity.expected_close_date.nulls_last(), Opportunity.opportunity_id.desc())
                                .limit(limit).offset(offset)).all()
        opps = [o for o, _s in pairs]
        customers = dict(session.execute(select(DetailAccount.detail_account_id, DetailAccount.name).where(
            DetailAccount.detail_account_id.in_({o.customer_detail_account_id for o in opps if o.customer_detail_account_id} or {-1}))).all())
        leads = dict(session.execute(select(Lead.lead_id, Lead.full_name).where(
            Lead.lead_id.in_({o.lead_id for o in opps if o.lead_id} or {-1}))).all())
        sources = dict(session.execute(select(LeadSource.source_id, LeadSource.name)).all())
        docs: dict[int, list[int]] = {}
        for oid, did in session.execute(select(OpportunityDocument.opportunity_id, OpportunityDocument.document_id).where(
                OpportunityDocument.opportunity_id.in_([o.opportunity_id for o in opps] or [-1]))):
            docs.setdefault(oid, []).append(did)
        users = c.user_names(session, [o.owner_user_id for o in opps])
        return [OpportunityRow(
            opportunity_id=o.opportunity_id, opportunity_no=o.opportunity_no, title=o.title,
            customer_detail_account_id=o.customer_detail_account_id, customer_name=customers.get(o.customer_detail_account_id, ""),
            lead_id=o.lead_id, lead_name=leads.get(o.lead_id, ""), owner_user_id=o.owner_user_id, owner_name=users.get(o.owner_user_id, ""),
            pipeline_id=o.pipeline_id, stage_id=o.stage_id, stage_name=s.name, stage_type=s.stage_type, amount=o.amount,
            probability_percent=o.probability_percent, expected_close_date=o.expected_close_date, source_id=o.source_id,
            source_name=sources.get(o.source_id, ""), description=o.description, status_code=o.status_code,
            status_label=c.OPP_STATUS[o.status_code], lost_reason=o.lost_reason, stage_entered_at=o.stage_entered_at,
            sla_hours=s.sla_hours, created_at=o.created_at, closed_at=o.closed_at, document_ids=docs.get(o.opportunity_id, []))
            for o, s in pairs]


def get_opportunity(company_id: int, opportunity_id: int) -> OpportunityRow:
    rows = list_opportunities(company_id, opportunity_ids=[opportunity_id])
    if not rows:
        raise ValueError("فرصت فروش نامعتبر است.")
    return rows[0]


@dataclass
class KanbanColumn:
    stage_id: int
    code: str
    name: str
    stage_type: str
    probability_percent: decimal.Decimal
    sla_hours: int | None
    cards: list[OpportunityRow]

    @property
    def total(self) -> decimal.Decimal:
        return sum((o.amount for o in self.cards), ZERO)

    @property
    def weighted(self) -> decimal.Decimal:
        return sum((o.weighted_amount for o in self.cards), ZERO)


def kanban(company_id: int, pipeline_id: int | None = None, owner_user_id: int | None = None,
           closed_days: int = 30) -> list[KanbanColumn]:
    """ستون‌های قیف؛ فرصت‌های بسته‌شده فقط برای closed_days روز اخیر نمایش داده می‌شوند."""
    pipeline_id = pipeline_id or pl_service.ensure_default_pipeline(company_id)
    stages = pl_service.list_stages(company_id, pipeline_id)
    opps = list_opportunities(company_id, pipeline_id=pipeline_id, owner_user_id=owner_user_id)
    cutoff = c.now() - datetime.timedelta(days=closed_days)
    cols = [KanbanColumn(s.stage_id, s.code, s.name, s.stage_type, s.probability_percent, s.sla_hours, []) for s in stages]
    by_id = {col.stage_id: col for col in cols}
    for o in opps:
        if o.status_code != "OPEN" and (o.closed_at is None or o.closed_at < cutoff):
            continue
        if o.stage_id in by_id:
            by_id[o.stage_id].cards.append(o)
    return cols


def pipeline_summary(company_id: int, pipeline_id: int | None = None, owner_user_id: int | None = None) -> dict:
    """ارزش قیف، ارزش وزنی (پیش‌بینی)، برنده/بازنده و نرخ تبدیل — مقادیر از همان جدول فرصت."""
    with new_session() as session:
        q = select(Opportunity.status_code, func.count(), func.coalesce(func.sum(Opportunity.amount), 0),
                   func.coalesce(func.sum(Opportunity.amount * Opportunity.probability_percent / 100), 0)).where(
            Opportunity.company_id == company_id)
        if pipeline_id:
            q = q.where(Opportunity.pipeline_id == pipeline_id)
        if owner_user_id:
            q = q.where(Opportunity.owner_user_id == owner_user_id)
        stats = {s: (n, decimal.Decimal(a), decimal.Decimal(w)) for s, n, a, w in session.execute(q.group_by(Opportunity.status_code))}
    won, lost, open_ = (stats.get(k, (0, ZERO, ZERO)) for k in ("WON", "LOST", "OPEN"))
    closed = won[0] + lost[0]
    return {"open_count": open_[0], "pipeline_value": open_[1], "weighted_value": open_[2].quantize(decimal.Decimal("0.01")),
            "won_count": won[0], "won_value": won[1], "lost_count": lost[0], "lost_value": lost[1],
            "conversion_rate": (decimal.Decimal(won[0]) * 100 / closed).quantize(decimal.Decimal("0.1")) if closed else ZERO}
