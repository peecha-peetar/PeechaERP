"""تنظیماتِ اتصالِ سانترال/وویپ (AMIِ آستریسک/ایزابل) -- طبقِ درخواستِ
صریحِ کاربر: «وصل بشه به سیستمِ سانترال یا وویپ». هم‌الگو با
commercial_pricing.get_pricing_policy/set_pricing_policy -- یک ردیفِ
یکتا به‌ازایِ هر شرکت. اعتبارنامه (نامِ‌کاربری/رمزِ AMI) با همان
کلیدِ Fernدِ موجود در ecommerce_credentials.py رمزنگاری می‌شود، دقیقاً
هم‌الگو با bot_token_encrypted در commercial_social.py."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import VoipConnection
from peecha.services import ecommerce_credentials


@dataclass
class VoipConnectionInfo:
    connection_id: int
    host: str
    port: int
    dial_context: str
    channel_tech_prefix: str
    ami_username: str
    ami_secret: str
    is_active: bool
    consecutive_failure_count: int
    last_error_message: str | None


def get_voip_connection(company_id: int) -> VoipConnectionInfo | None:
    with new_session() as session:
        row = session.scalar(select(VoipConnection).where(VoipConnection.company_id == company_id))
        if row is None:
            return None
        creds = ecommerce_credentials.decrypt_credentials(row.credentials_encrypted)
        return VoipConnectionInfo(
            connection_id=row.connection_id, host=row.host, port=row.port, dial_context=row.dial_context,
            channel_tech_prefix=row.channel_tech_prefix, ami_username=creds.get("ami_username", ""),
            ami_secret=creds.get("ami_secret", ""), is_active=row.is_active,
            consecutive_failure_count=row.consecutive_failure_count, last_error_message=row.last_error_message,
        )


def set_voip_connection(
    company_id: int, host: str, port: int, dial_context: str, channel_tech_prefix: str,
    ami_username: str, ami_secret: str, is_active: bool,
) -> None:
    encrypted = ecommerce_credentials.encrypt_credentials({"ami_username": ami_username, "ami_secret": ami_secret})
    with new_session() as session:
        row = session.scalar(select(VoipConnection).where(VoipConnection.company_id == company_id))
        if row is None:
            row = VoipConnection(company_id=company_id)
            session.add(row)
        row.host = host.strip()
        row.port = port
        row.dial_context = dial_context.strip() or "from-internal"
        row.channel_tech_prefix = channel_tech_prefix.strip() or "PJSIP"
        row.credentials_encrypted = encrypted
        row.is_active = is_active
        session.commit()


def record_connection_result(company_id: int, success: bool, error_message: str | None = None) -> None:
    """طبقِ الگویِ «نگهبانِ اتصال» (هم‌الگو با MarketplaceConnection/SocialConnection):
    هر تلاشِ Originate (موفق یا ناموفق) این‌جا ثبت می‌شود -- شکستِ متوالی
    بعداً می‌تواند در پنلِ سلامتِ اتصالات نمایش داده شود."""
    from datetime import datetime

    with new_session() as session:
        row = session.scalar(select(VoipConnection).where(VoipConnection.company_id == company_id))
        if row is None:
            return
        row.last_checked_at = datetime.now()
        if success:
            row.consecutive_failure_count = 0
            row.last_error_message = None
        else:
            row.consecutive_failure_count += 1
            row.last_error_message = (error_message or "")[:500]
        session.commit()
