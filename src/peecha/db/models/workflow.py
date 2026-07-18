"""مدل‌های کارتابل (صف تایید سراسری).

معادل db/schema/004_workflow_cartable.sql
"""

from __future__ import annotations

import datetime

from sqlalchemy import ForeignKey, ForeignKeyConstraint, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from peecha.db.base import Base


class CartableRequestType(Base):
    __tablename__ = "cartable_request_types"
    __table_args__ = {"schema": "wf"}

    request_type_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # CREATE | EDIT | DELETE


class CartableStatus(Base):
    __tablename__ = "cartable_statuses"
    __table_args__ = {"schema": "wf"}

    status_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # PENDING | APPROVED | REJECTED | CANCELLED


class CartableActionType(Base):
    __tablename__ = "cartable_action_types"
    __table_args__ = {"schema": "wf"}

    action_type_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # APPROVE|REJECT|RETURN|CANCEL|DELEGATE|RESUBMIT


class ApprovalWorkflow(Base):
    __tablename__ = "approval_workflows"
    __table_args__ = {"schema": "wf"}

    workflow_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    form_id: Mapped[int] = mapped_column(ForeignKey("sec.forms.form_id"))
    code: Mapped[str] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(default=True)


class ApprovalWorkflowStep(Base):
    __tablename__ = "approval_workflow_steps"
    __table_args__ = {"schema": "wf"}

    workflow_id: Mapped[int] = mapped_column(ForeignKey("wf.approval_workflows.workflow_id"), primary_key=True)
    request_type_id: Mapped[int] = mapped_column(
        ForeignKey("wf.cartable_request_types.request_type_id"), primary_key=True
    )
    step_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    approver_role_id: Mapped[int] = mapped_column(ForeignKey("sec.roles.role_id"))


class ConditionType(Base):
    __tablename__ = "condition_types"
    __table_args__ = {"schema": "wf"}

    condition_type_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)  # فعلاً فقط AMOUNT_THRESHOLD


class ApprovalStepCondition(Base):
    __tablename__ = "approval_step_conditions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_id", "request_type_id", "step_no"],
            [
                "wf.approval_workflow_steps.workflow_id",
                "wf.approval_workflow_steps.request_type_id",
                "wf.approval_workflow_steps.step_no",
            ],
        ),
        {"schema": "wf"},
    )

    condition_id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int]
    request_type_id: Mapped[int]
    step_no: Mapped[int] = mapped_column(SmallInteger)
    condition_type_id: Mapped[int] = mapped_column(ForeignKey("wf.condition_types.condition_type_id"))
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict)


class CartableItem(Base):
    __tablename__ = "cartable_items"
    __table_args__ = {"schema": "wf"}

    cartable_item_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    form_id: Mapped[int] = mapped_column(ForeignKey("sec.forms.form_id"))
    source_record_id: Mapped[int]  # ارجاع نرم؛ بدون FK واقعی چون نوع منبع بسته به form_id فرق می‌کند
    request_type_id: Mapped[int] = mapped_column(ForeignKey("wf.cartable_request_types.request_type_id"))
    workflow_id: Mapped[int | None] = mapped_column(ForeignKey("wf.approval_workflows.workflow_id"))
    current_step_no: Mapped[int] = mapped_column(SmallInteger, default=1)
    current_approver_role_id: Mapped[int | None] = mapped_column(ForeignKey("sec.roles.role_id"))
    current_approver_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    status_id: Mapped[int] = mapped_column(ForeignKey("wf.cartable_statuses.status_id"))
    submitted_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    submitted_at: Mapped[datetime.datetime]

    steps: Mapped[list["CartableItemStep"]] = relationship(back_populates="cartable_item")
    actions: Mapped[list["CartableAction"]] = relationship(back_populates="cartable_item")


class CartableItemStep(Base):
    __tablename__ = "cartable_item_steps"
    __table_args__ = {"schema": "wf"}

    cartable_item_id: Mapped[int] = mapped_column(ForeignKey("wf.cartable_items.cartable_item_id"), primary_key=True)
    step_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    approver_role_id: Mapped[int] = mapped_column(ForeignKey("sec.roles.role_id"))

    cartable_item: Mapped[CartableItem] = relationship(back_populates="steps")


class CartableAction(Base):
    __tablename__ = "cartable_actions"
    __table_args__ = {"schema": "wf"}

    action_id: Mapped[int] = mapped_column(primary_key=True)
    cartable_item_id: Mapped[int] = mapped_column(ForeignKey("wf.cartable_items.cartable_item_id"))
    step_no: Mapped[int] = mapped_column(SmallInteger)
    action_type_id: Mapped[int] = mapped_column(ForeignKey("wf.cartable_action_types.action_type_id"))
    action_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    comment: Mapped[str | None]
    action_at: Mapped[datetime.datetime]

    cartable_item: Mapped[CartableItem] = relationship(back_populates="actions")
