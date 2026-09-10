"""بازاریابی/کمپینِ پیامکِ زمان‌بندی‌شده -- طبقِ درخواستِ صریحِ کاربر
(«یک تب برایِ بازاریابی و ارسالِ پیامکِ زمان‌بندی‌شده»). طبقِ تصمیمِ
طراحیِ MVP، گیرندگانِ هر کمپین در لحظهٔ ساخت از فهرستِ مشتریانِ
اختصاص‌یافته به کاربرِ سازنده (telesales.list_assigned_customers، R135)
عکس‌برداری می‌شوند -- بدونِ ساختِ یک فرمِ فیلترِ مشتریِ جداگانه؛
ارسالِ واقعی هم از همان sms_gateway.send_sms (R139) عبور می‌کند."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import SmsCampaign, SmsCampaignRecipient
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import sms_gateway as sms_gateway_service
from peecha.services import telesales as telesales_service


@dataclass
class CampaignRow:
    campaign_id: int
    name: str
    message_text: str
    scheduled_at: datetime.datetime
    status_code: str
    recipient_count: int
    sent_count: int
    failed_count: int


def create_campaign(
    company_id: int, created_by_user_id: int, name: str, message_text: str, scheduled_at: datetime.datetime,
) -> int:
    name = name.strip()
    message_text = message_text.strip()
    if not name:
        raise ValueError("نامِ کمپین نمی‌تواند خالی باشد.")
    if not message_text:
        raise ValueError("متنِ پیامک نمی‌تواند خالی باشد.")

    assigned = telesales_service.list_assigned_customers(company_id, created_by_user_id)
    customers_by_id = {c["detail_account_id"]: c for c in dimensions_service.list_customers(company_id)}
    recipients: list[tuple[int, str]] = []
    for row in assigned:
        customer = customers_by_id.get(row.customer_detail_account_id)
        if customer is None:
            continue
        phone_number = customer.get("mobile") or customer.get("phone")
        if phone_number:
            recipients.append((row.customer_detail_account_id, phone_number))
    if not recipients:
        raise ValueError("هیچ‌کدام از مشتریانِ اختصاص‌یافته به شما شماره‌تماس ندارند.")

    with new_session() as session:
        campaign = SmsCampaign(
            company_id=company_id, name=name, message_text=message_text, scheduled_at=scheduled_at,
            created_by_user_id=created_by_user_id,
        )
        session.add(campaign)
        session.flush()
        for customer_detail_account_id, phone_number in recipients:
            session.add(
                SmsCampaignRecipient(
                    campaign_id=campaign.campaign_id, customer_detail_account_id=customer_detail_account_id,
                    phone_number=phone_number,
                )
            )
        session.commit()
        return campaign.campaign_id


def list_campaigns(company_id: int) -> list[CampaignRow]:
    with new_session() as session:
        campaigns = session.scalars(
            select(SmsCampaign).where(SmsCampaign.company_id == company_id).order_by(SmsCampaign.scheduled_at.desc())
        ).all()
        result: list[CampaignRow] = []
        for campaign in campaigns:
            recipients = session.scalars(
                select(SmsCampaignRecipient).where(SmsCampaignRecipient.campaign_id == campaign.campaign_id)
            ).all()
            result.append(
                CampaignRow(
                    campaign_id=campaign.campaign_id, name=campaign.name, message_text=campaign.message_text,
                    scheduled_at=campaign.scheduled_at, status_code=campaign.status_code,
                    recipient_count=len(recipients),
                    sent_count=sum(1 for r in recipients if r.status_code == "SENT"),
                    failed_count=sum(1 for r in recipients if r.status_code == "FAILED"),
                )
            )
        return result


def run_due_campaigns(company_id: int) -> None:
    """طبقِ همان الگویِ commercial_ecommerce.run_due_auto_syncs/
    commercial_social.run_due_posts -- با تیکِ QTimerِ shell_window.py
    صدا زده می‌شود؛ هیچ‌وقت raise نمی‌کند تا تیکِ پس‌زمینه‌ای برنامه را
    متوقف نکند."""
    gateway = sms_gateway_service.get_sms_gateway(company_id)
    now = datetime.datetime.now(datetime.timezone.utc)
    with new_session() as session:
        due_campaigns = session.scalars(
            select(SmsCampaign).where(
                SmsCampaign.company_id == company_id, SmsCampaign.status_code == "PENDING",
                SmsCampaign.scheduled_at <= now,
            )
        ).all()
        for campaign in due_campaigns:
            recipients = session.scalars(
                select(SmsCampaignRecipient).where(
                    SmsCampaignRecipient.campaign_id == campaign.campaign_id,
                    SmsCampaignRecipient.status_code == "PENDING",
                )
            ).all()
            any_success = False
            for recipient in recipients:
                if gateway is None or not gateway.is_active:
                    recipient.status_code = "FAILED"
                    recipient.error_message = "درگاهِ پیامک تنظیم نشده یا غیرفعال است."
                    continue
                result = sms_gateway_service.send_sms(
                    gateway.request_template, gateway.http_method, recipient.phone_number, campaign.message_text,
                )
                recipient.status_code = "SENT" if result.success else "FAILED"
                recipient.sent_at = datetime.datetime.now()
                recipient.error_message = None if result.success else result.message
                any_success = any_success or result.success
            campaign.status_code = "SENT" if any_success else "FAILED"
            campaign.sent_at = datetime.datetime.now()
        session.commit()
