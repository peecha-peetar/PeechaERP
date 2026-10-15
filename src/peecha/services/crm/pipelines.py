"""قیف فروش قابل تنظیم و منابع سرنخ."""

from __future__ import annotations

import decimal
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_, select

from peecha.db.base import new_session
from peecha.db.models.crm import LeadSource, Opportunity, Pipeline, PipelineStage
from peecha.services.crm import common as c

STAGE_FIELDS = {"amount": "مبلغ احتمالی", "expected_close_date": "تاریخ پیش‌بینی فروش", "customer": "مشتری",
                "owner": "مسئول فروش", "lines": "اقلام پیشنهادی", "description": "توضیحات"}


def _expunge(session, rows):
    for r in rows:
        session.expunge(r)
    return rows


# --- منابع سرنخ ------------------------------------------------------------------------------------
def list_lead_sources(company_id: int, active_only: bool = True) -> list[LeadSource]:
    with new_session() as session:
        q = select(LeadSource).where(or_(LeadSource.company_id.is_(None), LeadSource.company_id == company_id))
        if active_only:
            q = q.where(LeadSource.is_active.is_(True))
        return _expunge(session, list(session.scalars(q.order_by(LeadSource.sort_order, LeadSource.name))))


def save_lead_source(company_id: int, code: str, name: str, source_id: int | None = None, sort_order: int = 150,
                     is_active: bool = True) -> int:
    code, name = (code or "").strip().upper(), (name or "").strip()
    if not code or not name:
        raise ValueError("کد و نام منبع الزامی است.")
    with new_session() as session:
        dup = session.scalar(select(LeadSource.source_id).where(
            or_(LeadSource.company_id.is_(None), LeadSource.company_id == company_id), LeadSource.code == code))
        if dup is not None and dup != source_id:
            raise ValueError("این کد منبع قبلاً تعریف شده است.")
        row = session.get(LeadSource, source_id) if source_id else None
        if source_id and (row is None or row.company_id != company_id):
            raise ValueError("منابع پیش‌فرض سیستم قابل ویرایش نیستند؛ منبع تازه بسازید.")
        row = row or LeadSource(company_id=company_id)
        row.code, row.name, row.sort_order, row.is_active = code, name, sort_order, is_active
        session.add(row)
        session.commit()
        return row.source_id


# --- قیف ------------------------------------------------------------------------------------------
@dataclass
class StageFields:
    code: str
    name: str
    probability_percent: decimal.Decimal = decimal.Decimal(0)
    stage_type: str = "OPEN"
    sla_hours: int | None = None
    required_fields: list[str] = field(default_factory=list)
    next_action: str | None = None
    auto_activity: dict[str, Any] | None = None
    sort_order: int | None = None
    is_active: bool = True


def ensure_default_pipeline(company_id: int) -> int:
    """قیف پیش‌فرض شرکت را (اگر نیست) با مراحل استاندارد می‌سازد."""
    with new_session() as session:
        pid = session.scalar(select(Pipeline.pipeline_id).where(Pipeline.company_id == company_id, Pipeline.is_default.is_(True)))
        if pid is not None:
            return pid
        pipe = Pipeline(company_id=company_id, code="SALES", name="قیف فروش", is_default=True)
        session.add(pipe)
        session.flush()
        for i, (code, name, prob, kind, sla, req, nxt) in enumerate(c.DEFAULT_STAGES, start=1):
            session.add(PipelineStage(pipeline_id=pipe.pipeline_id, code=code, name=name, sort_order=i * 10,
                                      probability_percent=decimal.Decimal(prob), stage_type=kind, sla_hours=sla,
                                      required_fields=list(req), next_action=nxt, auto_activity=c.DEFAULT_STAGE_ACTIVITIES.get(code)))
        session.commit()
        return pipe.pipeline_id


def list_pipelines(company_id: int) -> list[Pipeline]:
    ensure_default_pipeline(company_id)
    with new_session() as session:
        return _expunge(session, list(session.scalars(select(Pipeline).where(Pipeline.company_id == company_id)
                                                      .order_by(Pipeline.is_default.desc(), Pipeline.name))))


def create_pipeline(company_id: int, user_id: int | None, code: str, name: str, copy_stages_from: int | None = None) -> int:
    code, name = (code or "").strip().upper(), (name or "").strip()
    if not code or not name:
        raise ValueError("کد و نام قیف الزامی است.")
    source = copy_stages_from or ensure_default_pipeline(company_id)
    with new_session() as session:
        if session.scalar(select(Pipeline.pipeline_id).where(Pipeline.company_id == company_id, Pipeline.code == code)):
            raise ValueError("این کد قیف قبلاً تعریف شده است.")
        pipe = Pipeline(company_id=company_id, code=code, name=name, is_default=False)
        session.add(pipe)
        session.flush()
        for st in session.scalars(select(PipelineStage).where(PipelineStage.pipeline_id == source)):
            session.add(PipelineStage(pipeline_id=pipe.pipeline_id, **{k: getattr(st, k) for k in (
                "code", "name", "sort_order", "probability_percent", "stage_type", "sla_hours", "required_fields",
                "next_action", "auto_activity", "is_active")}))
        c.audit(session, company_id, user_id, "Pipeline", pipe.pipeline_id, "CREATE", {"code": code})
        session.commit()
        return pipe.pipeline_id


def _pipeline(session, company_id: int, pipeline_id: int) -> Pipeline:
    pipe = session.get(Pipeline, pipeline_id)
    if pipe is None or pipe.company_id != company_id:
        raise ValueError("قیف فروش نامعتبر است.")
    return pipe


def list_stages(company_id: int, pipeline_id: int | None = None, active_only: bool = True) -> list[PipelineStage]:
    pipeline_id = pipeline_id or ensure_default_pipeline(company_id)
    with new_session() as session:
        _pipeline(session, company_id, pipeline_id)
        q = select(PipelineStage).where(PipelineStage.pipeline_id == pipeline_id)
        if active_only:
            q = q.where(PipelineStage.is_active.is_(True))
        return _expunge(session, list(session.scalars(q.order_by(PipelineStage.sort_order, PipelineStage.stage_id))))


def save_stage(company_id: int, user_id: int | None, pipeline_id: int, f: StageFields, stage_id: int | None = None) -> int:
    f.code = (f.code or "").strip().upper()
    if not f.code or not (f.name or "").strip():
        raise ValueError("کد و نام مرحله الزامی است.")
    if f.stage_type not in ("OPEN", "WON", "LOST"):
        raise ValueError("نوع مرحله نامعتبر است.")
    if not 0 <= decimal.Decimal(f.probability_percent) <= 100:
        raise ValueError("احتمال موفقیت باید بین ۰ تا ۱۰۰ باشد.")
    unknown = set(f.required_fields) - set(STAGE_FIELDS)
    if unknown:
        raise ValueError("فیلد الزامی نامعتبر: " + "، ".join(sorted(unknown)))
    with new_session() as session:
        _pipeline(session, company_id, pipeline_id)
        dup = session.scalar(select(PipelineStage.stage_id).where(PipelineStage.pipeline_id == pipeline_id, PipelineStage.code == f.code))
        if dup is not None and dup != stage_id:
            raise ValueError("این کد مرحله در قیف تکراری است.")
        row = session.get(PipelineStage, stage_id) if stage_id else PipelineStage(pipeline_id=pipeline_id)
        if row is None or row.pipeline_id != pipeline_id:
            raise ValueError("مرحله نامعتبر است.")
        if f.sort_order is None and stage_id is None:
            last = session.scalars(select(PipelineStage.sort_order).where(PipelineStage.pipeline_id == pipeline_id)).all()
            f.sort_order = (max(last) if last else 0) + 10
        for k, v in f.__dict__.items():
            if not (k == "sort_order" and v is None):
                setattr(row, k, v)
        row.name = f.name.strip()
        session.add(row)
        session.flush()
        c.audit(session, company_id, user_id, "PipelineStage", row.stage_id, "SAVE", {"code": f.code, "probability": f.probability_percent})
        session.commit()
        return row.stage_id


def delete_stage(company_id: int, user_id: int | None, stage_id: int) -> None:
    with new_session() as session:
        row = session.get(PipelineStage, stage_id)
        if row is None:
            raise ValueError("مرحله نامعتبر است.")
        _pipeline(session, company_id, row.pipeline_id)
        if session.scalar(select(Opportunity.opportunity_id).where(Opportunity.stage_id == stage_id).limit(1)):
            raise ValueError("فرصت‌هایی در این مرحله هستند — مرحله را غیرفعال کنید یا فرصت‌ها را جابه‌جا کنید.")
        c.audit(session, company_id, user_id, "PipelineStage", stage_id, "DELETE", {"code": row.code})
        session.delete(row)
        session.commit()
