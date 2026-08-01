"""موتورِ عمومیِ کارتابل (صفِ تاییدِ سراسری) — مستقل از نوعِ سند، برایِ
استفاده‌یِ همه‌یِ ماژول‌هایِ ERP (حسابداری، خزانه‌داری، خرید، فروش، ...).

طبقِ کشفِ حسابرسی: جدول‌هایِ این موتور (wf.*، در db/schema/004_workflow_cartable.sql
و db/models/workflow.py) از همان روزِ اولِ پروژه با طراحیِ کامل و درست
ساخته شده بودند — تاییدِ چندمرحله‌ای، مسیریابیِ شرطی (آستانه‌یِ مبلغ)،
برگشت/تفویض/ارسالِ‌مجدد — ولی هیچ سرویسی هرگز از آن‌ها استفاده نکرده
بود. این ماژول همان زیرساختِ ازپیش‌طراحی‌شده را فعال می‌کند.

هر ماژولِ مصرف‌کننده (حسابداری، خزانه‌داری، ...) فقط با register_handler
رویِ form_code (همان کدِ screen در nav_catalog.py، مثلِ "journal_entry")
ثبت‌نام می‌کند — بدونِ جدول یا صفحه‌ی تازه.

اگر برایِ یک form هیچ ApprovalWorkflowِ فعالی تعریف نشده باشد،
submit_for_approval هیچ آیتمِ کارتابلی نمی‌سازد (None برمی‌گرداند) —
یعنی بدونِ پیکربندیِ صریحِ ادمین در «طراحیِ گردشِ کار»، رفتار دقیقاً مثلِ
حالتِ بدونِ‌کارتابل می‌ماند (مسیرِ مستقیمِ قبلی که ماژولِ صدازننده باید
خودش دنبال کند).

دامنه‌یِ این نسخه: فقط نوعِ درخواستِ CREATE (تاییدِ ثبت/نهایی‌سازی) واقعاً
سیم‌کشی شده؛ EDIT/DELETE و اقداماتِ RETURN/DELEGATE در جدول‌ها/enum ها
از قبل جا دارند ولی منطقِ سرویسشان بعداً در دورهایِ جداگانه اضافه
می‌شود (زیرساخت آماده است، بدونِ نیاز به migration تازه)."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.security import Form, User, UserRole
from peecha.db.models.workflow import (
    ApprovalStepCondition,
    ApprovalWorkflow,
    ApprovalWorkflowStep,
    CartableAction,
    CartableActionType,
    CartableItem,
    CartableItemStep,
    CartableRequestType,
    CartableStatus,
    ConditionType,
)


@dataclass
class _HandlerSpec:
    on_approved: Callable[[int, int, int], None]
    on_rejected: Callable[[int, int, int, str], None]
    describe: Callable[[int, int], str]


_HANDLERS: dict[str, _HandlerSpec] = {}


def register_handler(
    form_code: str,
    *,
    on_approved: Callable[[int, int, int], None],
    on_rejected: Callable[[int, int, int, str], None],
    describe: Callable[[int, int], str],
) -> None:
    """on_approved(company_id, source_record_id, approved_by_user_id)
    on_rejected(company_id, source_record_id, rejected_by_user_id, reason)
    describe(company_id, source_record_id) -> str (خلاصه‌یِ نمایشی برایِ کارتابل)"""
    _HANDLERS[form_code] = _HandlerSpec(on_approved=on_approved, on_rejected=on_rejected, describe=describe)


def _form_id(session, form_code: str) -> int | None:
    from peecha.services.roles import ensure_catalog

    ensure_catalog()
    return session.scalar(select(Form.form_id).where(Form.code == form_code))


def _request_type_id(session, code: str) -> int:
    row = session.scalar(select(CartableRequestType).where(CartableRequestType.code == code))
    if row is None:
        raise ValueError(f"نوعِ درخواستِ کارتابلِ «{code}» در دیتابیس یافت نشد.")
    return row.request_type_id


def _status_id(session, code: str) -> int:
    row = session.scalar(select(CartableStatus).where(CartableStatus.code == code))
    if row is None:
        raise ValueError(f"وضعیتِ کارتابلِ «{code}» در دیتابیس یافت نشد.")
    return row.status_id


def _action_type_id(session, code: str) -> int:
    row = session.scalar(select(CartableActionType).where(CartableActionType.code == code))
    if row is None:
        raise ValueError(f"نوعِ اقدامِ کارتابلِ «{code}» در دیتابیس یافت نشد.")
    return row.action_type_id


def has_active_workflow(company_id: int, form_code: str) -> bool:
    with new_session() as session:
        form_id = _form_id(session, form_code)
        if form_id is None:
            return False
        return (
            session.scalar(
                select(ApprovalWorkflow).where(
                    ApprovalWorkflow.company_id == company_id,
                    ApprovalWorkflow.form_id == form_id,
                    ApprovalWorkflow.is_active.is_(True),
                )
            )
            is not None
        )


def _evaluate_condition(condition_type_code: str, parameters: dict, amount: decimal.Decimal | None) -> bool:
    """اگر نوعِ شرط ناشناخته یا قابلِ‌ارزیابی نبود، fail-closed به‌سمتِ
    «شرط برقرار است» (یعنی مرحله را نگه می‌دارد، نه این‌که حذفش کند) —
    برایِ یک گیت‌ِ تایید، محافظه‌کاری یعنی تاییدِ بیشتر لازم باشد، نه کمتر."""
    if condition_type_code == "AMOUNT_THRESHOLD":
        if amount is None:
            return True
        operator = parameters.get("operator", ">=")
        threshold = decimal.Decimal(str(parameters.get("amount", 0)))
        if operator == ">=":
            return amount >= threshold
        if operator == ">":
            return amount > threshold
        if operator == "<=":
            return amount <= threshold
        if operator == "<":
            return amount < threshold
        if operator == "==":
            return amount == threshold
        return True
    return True


def submit_for_approval(
    company_id: int,
    form_code: str,
    source_record_id: int,
    request_type_code: str,
    submitted_by_user_id: int,
    *,
    amount: decimal.Decimal | None = None,
) -> int | None:
    """اگر گردشِ کارِ فعالی برایِ این form تعریف نشده باشد، یا هیچ مرحله‌ای
    برایِ این نوعِ درخواست نداشته باشد، یا هیچ مرحله‌ای شرطش برقرار نباشد
    -> None (ماژولِ صدازننده باید مسیرِ مستقیمِ بدونِ‌کارتابل را دنبال کند).
    وگرنه شناسه‌ی cartable_item ساخته‌شده را برمی‌گرداند."""
    with new_session() as session:
        form_id = _form_id(session, form_code)
        if form_id is None:
            return None
        workflow = session.scalar(
            select(ApprovalWorkflow).where(
                ApprovalWorkflow.company_id == company_id,
                ApprovalWorkflow.form_id == form_id,
                ApprovalWorkflow.is_active.is_(True),
            )
        )
        if workflow is None:
            return None

        request_type_id = _request_type_id(session, request_type_code)
        steps = session.scalars(
            select(ApprovalWorkflowStep)
            .where(
                ApprovalWorkflowStep.workflow_id == workflow.workflow_id,
                ApprovalWorkflowStep.request_type_id == request_type_id,
            )
            .order_by(ApprovalWorkflowStep.step_no)
        ).all()
        if not steps:
            return None

        conditions_by_step: dict[int, list[ApprovalStepCondition]] = {}
        for c in session.scalars(
            select(ApprovalStepCondition).where(
                ApprovalStepCondition.workflow_id == workflow.workflow_id,
                ApprovalStepCondition.request_type_id == request_type_id,
            )
        ):
            conditions_by_step.setdefault(c.step_no, []).append(c)
        condition_type_codes = {ct.condition_type_id: ct.code for ct in session.scalars(select(ConditionType))}

        matched_steps = [
            step
            for step in steps
            if all(
                _evaluate_condition(condition_type_codes[c.condition_type_id], c.parameters, amount)
                for c in conditions_by_step.get(step.step_no, [])
            )
        ]
        if not matched_steps:
            return None

        item = CartableItem(
            company_id=company_id,
            form_id=form_id,
            source_record_id=source_record_id,
            request_type_id=request_type_id,
            workflow_id=workflow.workflow_id,
            current_step_no=1,
            current_approver_role_id=matched_steps[0].approver_role_id,
            current_approver_user_id=None,
            status_id=_status_id(session, "PENDING"),
            submitted_by_user_id=submitted_by_user_id,
        )
        session.add(item)
        session.flush()

        for materialized_step_no, step in enumerate(matched_steps, start=1):
            session.add(
                CartableItemStep(
                    cartable_item_id=item.cartable_item_id,
                    step_no=materialized_step_no,
                    approver_role_id=step.approver_role_id,
                )
            )
        session.commit()
        return item.cartable_item_id


@dataclass
class CartableTaskRow:
    cartable_item_id: int
    form_code: str
    form_label: str
    request_type_code: str
    source_record_id: int
    company_id: int
    submitted_by_name: str
    submitted_at: datetime.datetime
    current_step_no: int
    total_steps: int
    description: str


def list_my_tasks(user_id: int, company_id: int) -> list[CartableTaskRow]:
    from peecha.services.roles import FORM_LABELS

    with new_session() as session:
        role_ids = {
            ur.role_id
            for ur in session.scalars(select(UserRole).where(UserRole.user_id == user_id, UserRole.company_id == company_id))
        }
        pending_status_id = _status_id(session, "PENDING")
        all_pending = session.scalars(
            select(CartableItem).where(
                CartableItem.company_id == company_id,
                CartableItem.status_id == pending_status_id,
            )
        ).all()
        items = [
            it
            for it in all_pending
            if it.current_approver_user_id == user_id
            or (it.current_approver_role_id is not None and it.current_approver_role_id in role_ids)
        ]
        if not items:
            return []

        forms = {f.form_id: f.code for f in session.scalars(select(Form))}
        request_type_codes = {rt.request_type_id: rt.code for rt in session.scalars(select(CartableRequestType))}
        user_names = {u.user_id: u.full_name for u in session.scalars(select(User))}
        item_ids = [it.cartable_item_id for it in items]
        total_steps_rows = session.execute(
            select(CartableItemStep.cartable_item_id, func.count())
            .where(CartableItemStep.cartable_item_id.in_(item_ids))
            .group_by(CartableItemStep.cartable_item_id)
        ).all()
        total_steps_by_item = dict(total_steps_rows)

        rows = []
        for it in items:
            form_code = forms.get(it.form_id, "?")
            handler = _HANDLERS.get(form_code)
            description = handler.describe(it.company_id, it.source_record_id) if handler else f"#{it.source_record_id}"
            rows.append(
                CartableTaskRow(
                    cartable_item_id=it.cartable_item_id,
                    form_code=form_code,
                    form_label=FORM_LABELS.get(form_code, form_code),
                    request_type_code=request_type_codes.get(it.request_type_id, "?"),
                    source_record_id=it.source_record_id,
                    company_id=it.company_id,
                    submitted_by_name=user_names.get(it.submitted_by_user_id, ""),
                    submitted_at=it.submitted_at,
                    current_step_no=it.current_step_no,
                    total_steps=total_steps_by_item.get(it.cartable_item_id, it.current_step_no),
                    description=description,
                )
            )
        rows.sort(key=lambda r: r.submitted_at)
        return rows


def _ensure_can_act(session, item: CartableItem, user_id: int) -> None:
    if item.current_approver_user_id == user_id:
        return
    if item.current_approver_role_id is not None:
        has_role = session.scalar(
            select(UserRole).where(
                UserRole.user_id == user_id,
                UserRole.role_id == item.current_approver_role_id,
                UserRole.company_id == item.company_id,
            )
        )
        if has_role is not None:
            return
    raise ValueError("شما مجاز به اقدام روی این موردِ کارتابل نیستید.")


def approve_item(cartable_item_id: int, user_id: int, comment: str = "") -> None:
    with new_session() as session:
        item = session.get(CartableItem, cartable_item_id)
        if item is None:
            raise ValueError("موردِ کارتابل نامعتبر است.")
        pending_status_id = _status_id(session, "PENDING")
        if item.status_id != pending_status_id:
            raise ValueError("این مورد دیگر در انتظارِ تایید نیست.")
        _ensure_can_act(session, item, user_id)

        session.add(
            CartableAction(
                cartable_item_id=item.cartable_item_id,
                step_no=item.current_step_no,
                action_type_id=_action_type_id(session, "APPROVE"),
                action_by_user_id=user_id,
                comment=comment or None,
            )
        )

        total_steps = session.scalar(
            select(func.count()).select_from(CartableItemStep).where(CartableItemStep.cartable_item_id == item.cartable_item_id)
        )
        form = session.get(Form, item.form_id)
        form_code = form.code
        company_id = item.company_id
        source_record_id = item.source_record_id
        is_final = item.current_step_no >= total_steps

        if not is_final:
            next_step = session.scalar(
                select(CartableItemStep).where(
                    CartableItemStep.cartable_item_id == item.cartable_item_id,
                    CartableItemStep.step_no == item.current_step_no + 1,
                )
            )
            item.current_step_no += 1
            item.current_approver_role_id = next_step.approver_role_id
            item.current_approver_user_id = None
        else:
            item.status_id = _status_id(session, "APPROVED")

        session.commit()

    if is_final:
        handler = _HANDLERS.get(form_code)
        if handler is not None:
            handler.on_approved(company_id, source_record_id, user_id)


def reject_item(cartable_item_id: int, user_id: int, reason: str) -> None:
    with new_session() as session:
        item = session.get(CartableItem, cartable_item_id)
        if item is None:
            raise ValueError("موردِ کارتابل نامعتبر است.")
        pending_status_id = _status_id(session, "PENDING")
        if item.status_id != pending_status_id:
            raise ValueError("این مورد دیگر در انتظارِ تایید نیست.")
        _ensure_can_act(session, item, user_id)

        session.add(
            CartableAction(
                cartable_item_id=item.cartable_item_id,
                step_no=item.current_step_no,
                action_type_id=_action_type_id(session, "REJECT"),
                action_by_user_id=user_id,
                comment=reason or None,
            )
        )
        item.status_id = _status_id(session, "REJECTED")
        form = session.get(Form, item.form_id)
        form_code = form.code
        company_id = item.company_id
        source_record_id = item.source_record_id
        session.commit()

    handler = _HANDLERS.get(form_code)
    if handler is not None:
        handler.on_rejected(company_id, source_record_id, user_id, reason)


# --- ادمین: تعریف/ویرایشِ گردشِ کار (صفحه‌ی «طراحیِ گردشِ کار») ------------


@dataclass
class WorkflowStepOption:
    step_no: int
    approver_role_id: int


def get_workflow_steps(company_id: int, form_code: str) -> tuple[bool, list[WorkflowStepOption]]:
    """برمی‌گرداند: (is_active، مراحلِ نوعِ درخواستِ CREATE به‌ترتیب)."""
    with new_session() as session:
        form_id = _form_id(session, form_code)
        if form_id is None:
            return True, []
        workflow = session.scalar(
            select(ApprovalWorkflow).where(ApprovalWorkflow.company_id == company_id, ApprovalWorkflow.form_id == form_id)
        )
        if workflow is None:
            return True, []
        request_type_id = _request_type_id(session, "CREATE")
        steps = session.scalars(
            select(ApprovalWorkflowStep)
            .where(
                ApprovalWorkflowStep.workflow_id == workflow.workflow_id,
                ApprovalWorkflowStep.request_type_id == request_type_id,
            )
            .order_by(ApprovalWorkflowStep.step_no)
        ).all()
        return workflow.is_active, [
            WorkflowStepOption(step_no=s.step_no, approver_role_id=s.approver_role_id) for s in steps
        ]


def save_workflow_steps(company_id: int, form_code: str, is_active: bool, approver_role_ids: list[int]) -> None:
    """approver_role_ids: نقشِ تاییدکننده‌یِ هر مرحله، به‌ترتیب (مرحله‌ی
    اول = ایندکسِ ۰). لیستِ خالی یعنی گردشِ کار برایِ این form حذف شود
    (برگشت به حالتِ بدونِ‌کارتابل)."""
    with new_session() as session:
        form_id = _form_id(session, form_code)
        if form_id is None:
            raise ValueError("فرمِ نامعتبر است.")
        workflow = session.scalar(
            select(ApprovalWorkflow).where(ApprovalWorkflow.company_id == company_id, ApprovalWorkflow.form_id == form_id)
        )
        if not approver_role_ids:
            if workflow is not None:
                workflow.is_active = False
                session.execute(
                    ApprovalWorkflowStep.__table__.delete().where(ApprovalWorkflowStep.workflow_id == workflow.workflow_id)
                )
            session.commit()
            return

        if workflow is None:
            workflow = ApprovalWorkflow(company_id=company_id, form_id=form_id, code=form_code, is_active=is_active)
            session.add(workflow)
            session.flush()
        else:
            workflow.is_active = is_active
            session.execute(
                ApprovalWorkflowStep.__table__.delete().where(ApprovalWorkflowStep.workflow_id == workflow.workflow_id)
            )

        request_type_id = _request_type_id(session, "CREATE")
        for step_no, role_id in enumerate(approver_role_ids, start=1):
            session.add(
                ApprovalWorkflowStep(
                    workflow_id=workflow.workflow_id,
                    request_type_id=request_type_id,
                    step_no=step_no,
                    approver_role_id=role_id,
                )
            )
        session.commit()
