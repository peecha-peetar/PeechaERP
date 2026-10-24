"""طرح کیفیت نسخه‌دار: دامنه (کالا، گروه، تامین‌کننده، مرکز کاری، عملیات، مرحله، نوع سند)، پارامترها، نمونه‌برداری.

نسخهٔ فعال تغییر نمی‌کند؛ تغییر = نسخهٔ تازه (پیش‌نویس) که با فعال‌شدن، نسخهٔ قبل را «نسخهٔ قبلی» می‌کند.
نتایج گذشته مشخصات پارامتر را هنگام ثبت در خودشان نگه می‌دارند، پس تغییر طرح آن‌ها را عوض نمی‌کند.
"""

from __future__ import annotations

import datetime
import decimal
import math
from dataclasses import dataclass, field
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.inventory import Item
from peecha.db.models.quality import InspectionPlan, PlanParameter
from peecha.services import audit as audit_service
from peecha.services.qms import common as c

_ZERO = decimal.Decimal(0)
STAGES = tuple(c.STAGE_LABELS)
DATA_TYPES = tuple(c.DATA_TYPE_LABELS)


@dataclass
class PlanFields:
    code: str
    name: str
    stage_code: str
    item_id: int | None = None
    category_id: int | None = None
    supplier_detail_account_id: int | None = None
    work_center_id: int | None = None
    operation_id: int | None = None
    document_type_code: str | None = None
    sampling_method: str = "FULL"
    sample_size: decimal.Decimal | None = None
    sample_percent: decimal.Decimal | None = None
    acceptance_number: int = 0
    is_mandatory: bool = True
    valid_from: datetime.date | None = None
    valid_to: datetime.date | None = None
    notes: str | None = None


@dataclass
class ParameterFields:
    name: str
    data_type: str = "NUMERIC"
    uom_label: str | None = None
    min_value: decimal.Decimal | None = None
    max_value: decimal.Decimal | None = None
    target_value: decimal.Decimal | None = None
    options: list = field(default_factory=list)   # گزینه‌ای: ["سالم", {"value": "شکسته", "ok": False}]
    test_method: str | None = None
    is_mandatory: bool = True


def _dec(v):
    return None if v is None or v == "" else decimal.Decimal(str(v))


def _validate(f: PlanFields, params: list[ParameterFields]) -> None:
    if not (f.code or "").strip() or not (f.name or "").strip():
        raise ValueError("کد و نام طرح کیفیت الزامی است.")
    if f.stage_code not in STAGES:
        raise ValueError("مرحلهٔ بازرسی نامعتبر است.")
    if f.sampling_method not in c.SAMPLING_LABELS:
        raise ValueError("روش نمونه‌برداری نامعتبر است.")
    if f.sampling_method == "FIXED" and not (_dec(f.sample_size) and _dec(f.sample_size) > 0):
        raise ValueError("برای نمونه‌برداری با تعداد ثابت، تعداد نمونه را وارد کنید.")
    if f.sampling_method == "PERCENT" and not (_dec(f.sample_percent) and 0 < _dec(f.sample_percent) <= 100):
        raise ValueError("درصد نمونه باید بین صفر و ۱۰۰ باشد.")
    if (f.acceptance_number or 0) < 0:
        raise ValueError("عدد پذیرش نمی‌تواند منفی باشد.")
    if f.valid_from and f.valid_to and f.valid_to < f.valid_from:
        raise ValueError("تاریخ پایان اعتبار پیش از تاریخ شروع است.")
    if f.stage_code in ("IN_PROCESS",) and not (f.work_center_id or f.operation_id or f.item_id):
        raise ValueError("طرح حین تولید باید به کالا، مرکز کاری یا عملیات وصل باشد.")
    names = set()
    for p in params:
        if not (p.name or "").strip():
            raise ValueError("نام همهٔ پارامترها الزامی است.")
        if p.name.strip() in names:
            raise ValueError(f"پارامتر «{p.name}» تکراری است.")
        names.add(p.name.strip())
        if p.data_type not in DATA_TYPES:
            raise ValueError(f"نوع دادهٔ پارامتر «{p.name}» نامعتبر است.")
        lo, hi = _dec(p.min_value), _dec(p.max_value)
        if lo is not None and hi is not None and hi < lo:
            raise ValueError(f"در پارامتر «{p.name}» حداکثر از حداقل کمتر است.")
        if p.data_type == "OPTION" and not p.options:
            raise ValueError(f"پارامتر گزینه‌ای «{p.name}» گزینه ندارد.")


def _options(opts: list) -> list[dict]:
    out = []
    for o in opts or []:
        if isinstance(o, dict):
            out.append({"value": str(o.get("value", "")).strip(), "ok": bool(o.get("ok", True))})
        else:
            out.append({"value": str(o).strip(), "ok": True})
    return [o for o in out if o["value"]]


def _apply(plan: InspectionPlan, f: PlanFields) -> None:
    plan.code, plan.name, plan.stage_code = f.code.strip(), f.name.strip(), f.stage_code
    plan.item_id, plan.category_id, plan.supplier_detail_account_id = f.item_id, f.category_id, f.supplier_detail_account_id
    plan.work_center_id, plan.operation_id, plan.document_type_code = f.work_center_id, f.operation_id, f.document_type_code or None
    plan.sampling_method = f.sampling_method
    plan.sample_size = _dec(f.sample_size) if f.sampling_method == "FIXED" else None
    plan.sample_percent = _dec(f.sample_percent) if f.sampling_method == "PERCENT" else None
    plan.acceptance_number, plan.is_mandatory = int(f.acceptance_number or 0), bool(f.is_mandatory)
    plan.valid_from, plan.valid_to, plan.notes = f.valid_from, f.valid_to, (f.notes or "").strip() or None


def _write_parameters(session, plan_id: int, params: list[ParameterFields]) -> None:
    for old in session.scalars(select(PlanParameter).where(PlanParameter.plan_id == plan_id)):
        session.delete(old)
    session.flush()
    for i, p in enumerate(params, start=1):
        session.add(PlanParameter(plan_id=plan_id, seq=i, name=p.name.strip(), data_type=p.data_type,
                                  uom_label=(p.uom_label or "").strip() or None, min_value=_dec(p.min_value),
                                  max_value=_dec(p.max_value), target_value=_dec(p.target_value),
                                  options=_options(p.options) if p.data_type == "OPTION" else None,
                                  test_method=(p.test_method or "").strip() or None, is_mandatory=bool(p.is_mandatory)))


def create_plan(company_id: int, user_id: int, fields: PlanFields, parameters: list[ParameterFields]) -> int:
    _validate(fields, parameters)
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_MANAGE, session=session)
        if session.scalar(select(InspectionPlan.plan_id).where(InspectionPlan.company_id == company_id,
                                                               InspectionPlan.code == fields.code.strip())):
            raise ValueError("این کد طرح قبلاً تعریف شده است؛ برای تغییر، نسخهٔ جدید بسازید.")
        plan = InspectionPlan(company_id=company_id, version_no=1, status_code="DRAFT", created_by_user_id=user_id)
        _apply(plan, fields)
        session.add(plan)
        session.flush()
        _write_parameters(session, plan.plan_id, parameters)
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="InspectionPlan",
                                   entity_id=plan.plan_id, action="CREATE", changes={"code": plan.code, "version": 1})
        session.commit()
        return plan.plan_id


def _own_plan(session, company_id: int, plan_id: int, lock: bool = False) -> InspectionPlan:
    q = select(InspectionPlan).where(InspectionPlan.plan_id == plan_id)
    plan = session.scalar(q.with_for_update() if lock else q)
    if plan is None or plan.company_id != company_id:
        raise ValueError("طرح کیفیت نامعتبر است.")
    return plan


def update_plan(company_id: int, user_id: int, plan_id: int, fields: PlanFields, parameters: list[ParameterFields]) -> None:
    _validate(fields, parameters)
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_MANAGE, session=session)
        plan = _own_plan(session, company_id, plan_id, lock=True)
        if plan.status_code != "DRAFT":
            raise ValueError("فقط طرح پیش‌نویس ویرایش می‌شود؛ برای تغییر طرح فعال، نسخهٔ جدید بسازید.")
        if fields.code.strip() != plan.code:
            raise ValueError("کد طرح در نسخه‌های بعدی ثابت می‌ماند.")
        _apply(plan, fields)
        _write_parameters(session, plan_id, parameters)
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="InspectionPlan",
                                   entity_id=plan_id, action="UPDATE", changes={"parameters": len(parameters)})
        session.commit()


def activate_plan(company_id: int, user_id: int, plan_id: int) -> None:
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_MANAGE, session=session)
        plan = _own_plan(session, company_id, plan_id, lock=True)
        if plan.status_code != "DRAFT":
            raise ValueError("فقط طرح پیش‌نویس فعال می‌شود.")
        if not session.scalar(select(func.count()).select_from(PlanParameter).where(PlanParameter.plan_id == plan_id)):
            raise ValueError("طرح بدون پارامتر فعال نمی‌شود.")
        now = datetime.datetime.now(datetime.timezone.utc)
        for old in session.scalars(select(InspectionPlan).where(
                InspectionPlan.company_id == company_id, InspectionPlan.code == plan.code,
                InspectionPlan.status_code == "ACTIVE").with_for_update()):
            old.status_code = "SUPERSEDED"
            if old.valid_to is None or old.valid_to >= datetime.date.today():
                old.valid_to = datetime.date.today() - datetime.timedelta(days=1)
                if old.valid_from and old.valid_to < old.valid_from:
                    old.valid_to = old.valid_from
            audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="InspectionPlan",
                                       entity_id=old.plan_id, action="UPDATE", changes={"status": ["ACTIVE", "SUPERSEDED"]})
        session.flush()
        plan.status_code, plan.activated_by_user_id, plan.activated_at = "ACTIVE", user_id, now
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="InspectionPlan",
                                   entity_id=plan_id, action="APPROVE", changes={"status": ["DRAFT", "ACTIVE"],
                                                                                 "version": plan.version_no})
        session.commit()


def deactivate_plan(company_id: int, user_id: int, plan_id: int) -> None:
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_MANAGE, session=session)
        plan = _own_plan(session, company_id, plan_id, lock=True)
        if plan.status_code not in ("ACTIVE", "DRAFT"):
            raise ValueError("این طرح فعال نیست.")
        before = plan.status_code
        plan.status_code = "INACTIVE"
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="InspectionPlan",
                                   entity_id=plan_id, action="UPDATE", changes={"status": [before, "INACTIVE"]})
        session.commit()


def new_version(company_id: int, user_id: int, plan_id: int) -> int:
    """نسخهٔ پیش‌نویس تازه از روی یک نسخه (با همهٔ پارامترها)."""
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_MANAGE, session=session)
        src = _own_plan(session, company_id, plan_id)
        if session.scalar(select(InspectionPlan.plan_id).where(InspectionPlan.company_id == company_id,
                                                               InspectionPlan.code == src.code,
                                                               InspectionPlan.status_code == "DRAFT")):
            raise ValueError("برای این طرح یک نسخهٔ پیش‌نویس باز وجود دارد.")
        last = session.scalar(select(func.max(InspectionPlan.version_no)).where(InspectionPlan.company_id == company_id,
                                                                               InspectionPlan.code == src.code))
        copy = InspectionPlan(company_id=company_id, version_no=(last or 0) + 1, status_code="DRAFT", previous_plan_id=src.plan_id,
                              created_by_user_id=user_id)
        for col in ("code", "name", "stage_code", "item_id", "category_id", "supplier_detail_account_id", "work_center_id",
                    "operation_id", "document_type_code", "sampling_method", "sample_size", "sample_percent",
                    "acceptance_number", "is_mandatory", "notes"):
            setattr(copy, col, getattr(src, col))
        copy.valid_from = datetime.date.today()
        session.add(copy)
        session.flush()
        for p in session.scalars(select(PlanParameter).where(PlanParameter.plan_id == src.plan_id).order_by(PlanParameter.seq)):
            session.add(PlanParameter(plan_id=copy.plan_id, seq=p.seq, name=p.name, data_type=p.data_type, uom_label=p.uom_label,
                                      min_value=p.min_value, max_value=p.max_value, target_value=p.target_value,
                                      options=p.options, test_method=p.test_method, is_mandatory=p.is_mandatory))
        audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type="InspectionPlan",
                                   entity_id=copy.plan_id, action="CREATE",
                                   changes={"code": copy.code, "version": copy.version_no, "from": src.plan_id})
        session.commit()
        return copy.plan_id


def list_plans(company_id: int, status: str | None = None) -> list[SimpleNamespace]:
    with new_session() as session:
        q = select(InspectionPlan).where(InspectionPlan.company_id == company_id)
        if status:
            q = q.where(InspectionPlan.status_code == status)
        plans = list(session.scalars(q.order_by(InspectionPlan.code, InspectionPlan.version_no.desc())))
        counts = dict(session.execute(select(PlanParameter.plan_id, func.count()).where(
            PlanParameter.plan_id.in_([p.plan_id for p in plans] or [-1])).group_by(PlanParameter.plan_id)).all())
        return [SimpleNamespace(plan_id=p.plan_id, code=p.code, version_no=p.version_no, name=p.name, stage_code=p.stage_code,
                                stage_label=c.STAGE_LABELS[p.stage_code], status_code=p.status_code,
                                status_label=c.PLAN_STATUS_LABELS[p.status_code], item_id=p.item_id, category_id=p.category_id,
                                supplier_id=p.supplier_detail_account_id, work_center_id=p.work_center_id,
                                operation_id=p.operation_id, sampling_label=c.SAMPLING_LABELS[p.sampling_method],
                                valid_from=p.valid_from, valid_to=p.valid_to, parameters=counts.get(p.plan_id, 0),
                                is_mandatory=p.is_mandatory) for p in plans]


def get_plan(company_id: int, plan_id: int) -> SimpleNamespace:
    with new_session() as session:
        plan = _own_plan(session, company_id, plan_id)
        params = list(session.scalars(select(PlanParameter).where(PlanParameter.plan_id == plan_id).order_by(PlanParameter.seq)))
        for p in params:
            session.expunge(p)
        session.expunge(plan)
        return SimpleNamespace(plan=plan, parameters=params)


def find_plan(session, company_id: int, stage_code: str, item_id: int | None, *, supplier_id: int | None = None,
              work_center_id: int | None = None, operation_id: int | None = None, document_type_code: str | None = None,
              on_date: datetime.date | None = None) -> InspectionPlan | None:
    """دقیق‌ترین طرح فعال و معتبر: هر دامنهٔ تعیین‌شده باید بخواند؛ کالا > گروه > تامین‌کننده/مرکز/عملیات > نوع سند."""
    on_date = on_date or datetime.date.today()
    category_id = session.scalar(select(Item.category_id).where(Item.item_id == item_id)) if item_id else None
    best, best_score = None, -1
    for p in session.scalars(select(InspectionPlan).where(InspectionPlan.company_id == company_id,
                                                          InspectionPlan.stage_code == stage_code,
                                                          InspectionPlan.status_code == "ACTIVE")):
        if (p.valid_from and p.valid_from > on_date) or (p.valid_to and p.valid_to < on_date):
            continue
        score, ok = 0, True
        for value, wanted, weight in ((p.item_id, item_id, 16), (p.category_id, category_id, 8),
                                      (p.supplier_detail_account_id, supplier_id, 4), (p.work_center_id, work_center_id, 2),
                                      (p.operation_id, operation_id, 2), (p.document_type_code, document_type_code, 1)):
            if value is None:
                continue
            if value != wanted:
                ok = False
                break
            score += weight
        if ok and (score > best_score or (score == best_score and best is not None and p.version_no > best.version_no)):
            best, best_score = p, score
    return best


def sample_size(plan: InspectionPlan | None, lot_quantity: decimal.Decimal) -> decimal.Decimal:
    """تعداد نمونهٔ پیشنهادی (هیچ‌گاه بیش از محموله)."""
    lot = decimal.Decimal(lot_quantity or 0)
    if plan is None or plan.sampling_method == "FULL":
        return lot
    if plan.sampling_method == "FIXED":
        return min(lot, decimal.Decimal(plan.sample_size))
    return min(lot, decimal.Decimal(math.ceil(lot * decimal.Decimal(plan.sample_percent) / 100)))


def evaluate(data_type: str, value, min_value=None, max_value=None, options=None) -> bool | None:
    """انطباق یک مقدار با مشخصات؛ متن آزاد = نامشخص (None)."""
    if value is None or value == "":
        return None
    if data_type == "NUMERIC":
        v = decimal.Decimal(str(value))
        return (min_value is None or v >= decimal.Decimal(min_value)) and (max_value is None or v <= decimal.Decimal(max_value))
    if data_type == "PASS_FAIL":
        return bool(value)
    if data_type == "OPTION":
        match = next((o for o in options or [] if o.get("value") == str(value)), None)
        if match is None:
            raise ValueError(f"گزینهٔ «{value}» در طرح تعریف نشده است.")
        return bool(match.get("ok", True))
    return None


def verdict(plan: InspectionPlan | None, defective_samples: int) -> str:
    """پیشنهاد طرح برای محموله: نمونهٔ معیوب بیش از عدد پذیرش = رد."""
    limit = plan.acceptance_number if plan is not None else 0
    return "REJECT" if defective_samples > limit else "ACCEPT"
