"""مدل‌های CRM — R281 (اسکیمای crm).

فقط موجودیت‌هایی که واقعاً متعلق به CRM‌اند: سرنخ، قیف فروش، فرصت. مشتری، سند فروش، کالا، کاربر و فعالیت
(comm.customer_activities) همان جدول‌های موجود ERP هستند و اینجا فقط ارجاع داده می‌شوند.
"""

from __future__ import annotations

import datetime
import decimal
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Numeric, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from peecha.db.base import Base

_CRM = {"schema": "crm"}


class LeadSource(Base):
    __tablename__ = "lead_sources"
    __table_args__ = _CRM

    source_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=100)
    is_active: Mapped[bool] = mapped_column(default=True)


class Pipeline(Base):
    __tablename__ = "pipelines"
    __table_args__ = _CRM

    pipeline_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(100))
    is_default: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class PipelineStage(Base):
    __tablename__ = "pipeline_stages"
    __table_args__ = _CRM

    stage_id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("crm.pipelines.pipeline_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)
    probability_percent: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), default=decimal.Decimal(0))
    stage_type: Mapped[str] = mapped_column(String(5), default="OPEN")
    sla_hours: Mapped[int | None]
    required_fields: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    next_action: Mapped[str | None] = mapped_column(String(300))
    auto_activity: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(default=True)


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = _CRM

    lead_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    lead_no: Mapped[int]
    full_name: Mapped[str] = mapped_column(String(150))
    company_name: Mapped[str | None] = mapped_column(String(150))
    mobile: Mapped[str | None] = mapped_column(String(20))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(150))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("crm.lead_sources.source_id"))
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("crm.campaigns.campaign_id"))  # R284
    interested_item_id: Mapped[int | None] = mapped_column(ForeignKey("inv.items.item_id"))
    interested_text: Mapped[str | None] = mapped_column(String(300))
    estimated_value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    status_code: Mapped[str] = mapped_column(String(12), default="NEW")
    score: Mapped[int] = mapped_column(SmallInteger, default=0)
    score_band: Mapped[str] = mapped_column(String(8), default="COLD")
    city: Mapped[str | None] = mapped_column(String(100))
    province: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(String(2000))
    next_action: Mapped[str | None] = mapped_column(String(300))
    next_action_date: Mapped[datetime.date | None]
    last_activity_at: Mapped[datetime.datetime | None]
    converted_customer_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    converted_opportunity_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("crm.opportunities.opportunity_id"))
    converted_at: Mapped[datetime.datetime | None]
    lost_reason: Mapped[str | None] = mapped_column(String(300))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = _CRM

    opportunity_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    opportunity_no: Mapped[int]
    title: Mapped[str] = mapped_column(String(200))
    customer_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    lead_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("crm.leads.lead_id"))
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("crm.pipelines.pipeline_id"))
    stage_id: Mapped[int] = mapped_column(ForeignKey("crm.pipeline_stages.stage_id"))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    probability_percent: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), default=decimal.Decimal(0))
    expected_close_date: Mapped[datetime.date | None]
    source_id: Mapped[int | None] = mapped_column(ForeignKey("crm.lead_sources.source_id"))
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("crm.campaigns.campaign_id"))  # R284
    description: Mapped[str | None] = mapped_column(String(2000))
    status_code: Mapped[str] = mapped_column(String(5), default="OPEN")
    lost_reason: Mapped[str | None] = mapped_column(String(300))
    stage_entered_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    closed_at: Mapped[datetime.datetime | None]
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class OpportunityLine(Base):
    __tablename__ = "opportunity_lines"
    __table_args__ = _CRM

    line_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("crm.opportunities.opportunity_id", ondelete="CASCADE"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("inv.items.item_id"))
    description: Mapped[str | None] = mapped_column(String(300))
    quantity: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=decimal.Decimal(1))
    unit_price: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    discount_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))


class OpportunityDocument(Base):
    __tablename__ = "opportunity_documents"
    __table_args__ = _CRM

    opportunity_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("crm.opportunities.opportunity_id", ondelete="CASCADE"), primary_key=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("comm.commercial_documents.document_id"), primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


# --- R283: تحلیل مشتری ---------------------------------------------------------------------------------
class CrmSettings(Base):
    __tablename__ = "settings"
    __table_args__ = _CRM

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class Segment(Base):
    __tablename__ = "segments"
    __table_args__ = _CRM

    segment_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(String(500))
    rule: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_system: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    member_count: Mapped[int | None]
    refreshed_at: Mapped[datetime.datetime | None]
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class CustomerScore(Base):
    """کش محاسباتی تحلیل مشتری؛ با refresh از دادهٔ فروش/حسابداری دوباره ساخته می‌شود."""

    __tablename__ = "customer_scores"
    __table_args__ = _CRM

    customer_detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"), primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    recency_days: Mapped[int | None]
    frequency_365: Mapped[int] = mapped_column(default=0)
    monetary_365: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    sales_90d: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    invoice_count_total: Mapped[int] = mapped_column(default=0)
    first_purchase: Mapped[datetime.date | None]
    last_purchase: Mapped[datetime.date | None]
    avg_gap_days: Mapped[decimal.Decimal | None] = mapped_column(Numeric(8, 1))
    r_score: Mapped[int | None] = mapped_column(SmallInteger)
    f_score: Mapped[int | None] = mapped_column(SmallInteger)
    m_score: Mapped[int | None] = mapped_column(SmallInteger)
    rfm_segment: Mapped[str | None] = mapped_column(String(20))
    health_score: Mapped[int] = mapped_column(SmallInteger, default=0)
    health_band: Mapped[str] = mapped_column(String(10), default="ATTENTION")
    churn_risk: Mapped[int] = mapped_column(SmallInteger, default=0)
    churn_band: Mapped[str] = mapped_column(String(10), default="LOW")
    clv_historical: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    clv_predicted: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    overdue_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    open_complaints: Mapped[int] = mapped_column(default=0)
    activities_90d: Mapped[int] = mapped_column(default=0)
    factors: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    next_best_action: Mapped[str | None] = mapped_column(String(300))
    computed_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


# --- R284: بازاریابی -----------------------------------------------------------------------------------
class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = _CRM

    campaign_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    campaign_no: Mapped[int]
    name: Mapped[str] = mapped_column(String(150))
    campaign_type: Mapped[str] = mapped_column(String(15), default="SMS")
    status_code: Mapped[str] = mapped_column(String(12), default="DRAFT")
    segment_id: Mapped[int | None] = mapped_column(ForeignKey("crm.segments.segment_id"))
    lead_source_id: Mapped[int | None] = mapped_column(ForeignKey("crm.lead_sources.source_id"))
    start_date: Mapped[datetime.date | None]
    end_date: Mapped[datetime.date | None]
    attribution_days: Mapped[int] = mapped_column(default=30)
    budget_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    actual_cost: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal(0))
    expected_revenue: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    message_text: Mapped[str | None] = mapped_column(String(1000))
    scheduled_at: Mapped[datetime.datetime | None]
    sms_campaign_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("comm.sms_campaigns.campaign_id"))
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    description: Mapped[str | None] = mapped_column(String(1000))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class CampaignMember(Base):
    __tablename__ = "campaign_members"
    __table_args__ = _CRM

    member_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("crm.campaigns.campaign_id", ondelete="CASCADE"))
    customer_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    lead_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("crm.leads.lead_id", ondelete="CASCADE"))
    contact: Mapped[str | None] = mapped_column(String(150))
    status_code: Mapped[str] = mapped_column(String(12), default="TARGETED")
    responded_at: Mapped[datetime.datetime | None]
    converted_at: Mapped[datetime.datetime | None]
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
