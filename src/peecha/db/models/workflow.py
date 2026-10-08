"""مدل‌های کارتابل (صف تایید سراسری).

معادل db/schema/004_workflow_cartable.sql
"""

from __future__ import annotations

import datetime

from typing import Any

from sqlalchemy import BigInteger, ForeignKey, ForeignKeyConstraint, SmallInteger, String, func
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
    submitted_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

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
    action_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    cartable_item: Mapped[CartableItem] = relationship(back_populates="actions")


# =========================================================================================================
# R291+: موتور گردش کار و اتوماسیون (db/schema/210_wf_engine_core.sql)
_WF = {"schema": "wf"}


class WfDefinition(Base):
    __tablename__ = "definitions"
    __table_args__ = _WF

    definition_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(1000))
    module_code: Mapped[str | None] = mapped_column(String(20))
    entity_type: Mapped[str | None] = mapped_column(String(50))
    category: Mapped[str | None] = mapped_column(String(30))
    template_code: Mapped[str | None] = mapped_column(String(60))
    status_code: Mapped[str] = mapped_column(String(12), default="DRAFT")
    active_version_id: Mapped[int | None] = mapped_column(ForeignKey("wf.definition_versions.version_id", use_alter=True))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class WfDefinitionVersion(Base):
    __tablename__ = "definition_versions"
    __table_args__ = _WF

    version_id: Mapped[int] = mapped_column(primary_key=True)
    definition_id: Mapped[int] = mapped_column(ForeignKey("wf.definitions.definition_id", ondelete="CASCADE"))
    version_no: Mapped[int]
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    checksum: Mapped[str | None] = mapped_column(String(64))
    status_code: Mapped[str] = mapped_column(String(12), default="DRAFT")
    notes: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    published_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    published_at: Mapped[datetime.datetime | None]


class WfDefinitionTrigger(Base):
    __tablename__ = "definition_triggers"
    __table_args__ = _WF

    trigger_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    definition_id: Mapped[int] = mapped_column(ForeignKey("wf.definitions.definition_id", ondelete="CASCADE"))
    version_id: Mapped[int] = mapped_column(ForeignKey("wf.definition_versions.version_id", ondelete="CASCADE"))
    trigger_type: Mapped[str] = mapped_column(String(12))
    event_type: Mapped[str | None] = mapped_column(String(80))
    entity_type: Mapped[str | None] = mapped_column(String(50))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(default=True)


class WfEvent(Base):
    __tablename__ = "events"
    __table_args__ = _WF

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    event_type: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    causation_instance_id: Mapped[int | None] = mapped_column(BigInteger)
    depth: Mapped[int] = mapped_column(SmallInteger, default=0)
    status_code: Mapped[str] = mapped_column(String(10), default="PENDING")
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    last_error: Mapped[str | None]
    locked_until: Mapped[datetime.datetime | None]
    occurred_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    processed_at: Mapped[datetime.datetime | None]


class WfInstance(Base):
    __tablename__ = "instances"
    __table_args__ = _WF

    instance_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    definition_id: Mapped[int] = mapped_column(ForeignKey("wf.definitions.definition_id"))
    version_id: Mapped[int] = mapped_column(ForeignKey("wf.definition_versions.version_id"))
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    title: Mapped[str | None] = mapped_column(String(300))
    status_code: Mapped[str] = mapped_column(String(12), default="RUNNING")
    outcome_code: Mapped[str | None] = mapped_column(String(20))
    tokens: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    variables: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    correlation_key: Mapped[str | None] = mapped_column(String(200))
    trigger_event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("wf.events.event_id"))
    started_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    started_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    ended_at: Mapped[datetime.datetime | None]
    row_version: Mapped[int] = mapped_column(default=1)
    step_count: Mapped[int] = mapped_column(default=0)
    depth: Mapped[int] = mapped_column(SmallInteger, default=0)
    last_error: Mapped[str | None]


class WfInstanceStep(Base):
    __tablename__ = "instance_steps"
    __table_args__ = _WF

    step_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    instance_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("wf.instances.instance_id", ondelete="CASCADE"))
    node_id: Mapped[str] = mapped_column(String(40))
    node_type: Mapped[str] = mapped_column(String(20))
    label: Mapped[str | None] = mapped_column(String(200))
    status_code: Mapped[str] = mapped_column(String(10), default="RUNNING")
    outcome: Mapped[str | None] = mapped_column(String(30))
    attempt: Mapped[int] = mapped_column(SmallInteger, default=1)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None]
    started_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    ended_at: Mapped[datetime.datetime | None]
    duration_ms: Mapped[int | None]


class WfActionExecution(Base):
    __tablename__ = "action_executions"
    __table_args__ = _WF

    execution_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    instance_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("wf.instances.instance_id", ondelete="CASCADE"))
    node_id: Mapped[str | None] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    action_code: Mapped[str] = mapped_column(String(80))
    status_code: Mapped[str] = mapped_column(String(10), default="PENDING")
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    next_retry_at: Mapped[datetime.datetime | None]
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    last_error: Mapped[str | None]
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class WfException(Base):
    __tablename__ = "exceptions"
    __table_args__ = _WF

    exception_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    instance_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("wf.instances.instance_id", ondelete="CASCADE"))
    node_id: Mapped[str | None] = mapped_column(String(40))
    execution_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("wf.action_executions.execution_id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    reason: Mapped[str]
    technical_detail: Mapped[str | None]
    priority_code: Mapped[str] = mapped_column(String(10), default="HIGH")
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    owner_role_id: Mapped[int | None] = mapped_column(ForeignKey("sec.roles.role_id"))
    status_code: Mapped[str] = mapped_column(String(10), default="OPEN")
    resolution_note: Mapped[str | None] = mapped_column(String(1000))
    resolved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    resolved_at: Mapped[datetime.datetime | None]
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class WfTimer(Base):
    __tablename__ = "timers"
    __table_args__ = _WF

    timer_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    kind: Mapped[str] = mapped_column(String(12))
    instance_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("wf.instances.instance_id", ondelete="CASCADE"))
    task_id: Mapped[int | None] = mapped_column(BigInteger)
    node_id: Mapped[str | None] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    due_at: Mapped[datetime.datetime]
    status_code: Mapped[str] = mapped_column(String(10), default="PENDING")
    locked_until: Mapped[datetime.datetime | None]
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    fired_at: Mapped[datetime.datetime | None]


class WfSettings(Base):
    __tablename__ = "settings"
    __table_args__ = _WF

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class WfTask(Base):
    __tablename__ = "tasks"
    __table_args__ = _WF

    task_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    instance_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("wf.instances.instance_id"))
    node_id: Mapped[str | None] = mapped_column(String(60))
    token_id: Mapped[str | None] = mapped_column(String(30))
    visit: Mapped[int] = mapped_column(default=1)
    kind: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(300))
    instructions: Mapped[str | None] = mapped_column(String(2000))
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    mode: Mapped[str] = mapped_column(String(12), default="ANY")
    required_percent: Mapped[int | None] = mapped_column(SmallInteger)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    form_fields: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status_code: Mapped[str] = mapped_column(String(10), default="OPEN")
    priority_code: Mapped[str] = mapped_column(String(10), default="NORMAL")
    requested_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    due_at: Mapped[datetime.datetime | None]
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    closed_at: Mapped[datetime.datetime | None]
    closed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    resumed_at: Mapped[datetime.datetime | None]
    row_version: Mapped[int] = mapped_column(default=1)


class WfTaskAssignee(Base):
    __tablename__ = "task_assignees"
    __table_args__ = _WF

    assignee_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("wf.tasks.task_id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    seq: Mapped[int] = mapped_column(SmallInteger, default=1)
    status_code: Mapped[str] = mapped_column(String(10), default="ACTIVE")
    decision: Mapped[str | None] = mapped_column(String(10))
    original_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    delegation_id: Mapped[int | None]
    activated_at: Mapped[datetime.datetime | None]
    decided_at: Mapped[datetime.datetime | None]


class WfTaskDecision(Base):
    __tablename__ = "task_decisions"
    __table_args__ = _WF

    decision_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("wf.tasks.task_id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    on_behalf_of_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    decision: Mapped[str] = mapped_column(String(10))
    comment: Mapped[str | None] = mapped_column(String(2000))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    client_ref: Mapped[str | None] = mapped_column(String(80))
    channel: Mapped[str] = mapped_column(String(10), default="DESKTOP")
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class WfDelegation(Base):
    __tablename__ = "delegations"
    __table_args__ = _WF

    delegation_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    from_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    to_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    starts_on: Mapped[datetime.date]
    ends_on: Mapped[datetime.date]
    definition_id: Mapped[int | None] = mapped_column(ForeignKey("wf.definitions.definition_id", ondelete="CASCADE"))
    entity_type: Mapped[str | None] = mapped_column(String(50))
    reason: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
