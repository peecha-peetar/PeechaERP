"""نگهبانِ اتصال -- طبقِ ادامه‌یِ اولویت‌بندیِ بخشِ عملیاتی: قبل از این،
شکستِ تیکِ خودکارِ سینکِ فروشِ اینترنتی و پستِ خودکار کاملاً بی‌صدا رد
می‌شد (نه در دیتابیس، نه در UI اثری داشت) -- یعنی یک توکن/رمزِ منقضی‌شده
می‌توانست هفته‌ها بدونِ آنکه کسی متوجه شود، همگام‌سازی را متوقف کرده
باشد. این ماژول اتصال‌هایِ فروشگاهی (WooCommerce/PrestaShop/Torob) و
اتصال‌هایِ تلگرام/بله را که شمارندهٔ شکستِ پیاپی‌شان از آستانه گذشته،
یک‌جا فهرست می‌کند."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import MarketplaceConnection, SocialConnection

_UNHEALTHY_THRESHOLD = 3

_ECOMMERCE_PLATFORM_LABELS = {"WOOCOMMERCE": "ووکامرس", "PRESTASHOP": "پرستاشاپ", "TOROB": "ترب", "OTHER": "سایر"}
_SOCIAL_PLATFORM_LABELS = {"TELEGRAM": "تلگرام", "BALE": "بله"}


@dataclass
class ConnectionHealthRow:
    connection_type: str  # ECOMMERCE|SOCIAL
    connection_id: int
    platform_label: str
    display_name: str
    consecutive_failure_count: int
    last_error_message: str | None
    last_checked_at: object | None


def list_unhealthy_connections(company_id: int) -> list[ConnectionHealthRow]:
    rows: list[ConnectionHealthRow] = []
    with new_session() as session:
        ecommerce_rows = session.scalars(
            select(MarketplaceConnection).where(
                MarketplaceConnection.company_id == company_id,
                MarketplaceConnection.consecutive_failure_count >= _UNHEALTHY_THRESHOLD,
            )
        )
        for c in ecommerce_rows:
            rows.append(ConnectionHealthRow(
                connection_type="ECOMMERCE", connection_id=c.connection_id,
                platform_label=_ECOMMERCE_PLATFORM_LABELS.get(c.platform_code, c.platform_code),
                display_name=c.store_url, consecutive_failure_count=c.consecutive_failure_count,
                last_error_message=c.last_error_message, last_checked_at=c.last_checked_at,
            ))

        social_rows = session.scalars(
            select(SocialConnection).where(
                SocialConnection.company_id == company_id,
                SocialConnection.consecutive_failure_count >= _UNHEALTHY_THRESHOLD,
            )
        )
        for c in social_rows:
            rows.append(ConnectionHealthRow(
                connection_type="SOCIAL", connection_id=c.connection_id,
                platform_label=_SOCIAL_PLATFORM_LABELS.get(c.platform_code, c.platform_code),
                display_name=c.display_name, consecutive_failure_count=c.consecutive_failure_count,
                last_error_message=c.last_error_message, last_checked_at=c.last_checked_at,
            ))

    rows.sort(key=lambda r: r.consecutive_failure_count, reverse=True)
    return rows


def list_all_connection_health(company_id: int) -> list[ConnectionHealthRow]:
    """طبقِ ادامه‌یِ اولویت‌بندی: برخلافِ list_unhealthy_connections
    (فقط اتصال‌هایِ ناسالم)، این تابع همه‌یِ اتصال‌ها را با وضعیتِ سلامت
    برمی‌گرداند -- برایِ نمایِ کاملِ صفحه‌یِ نگهبان."""
    rows: list[ConnectionHealthRow] = []
    with new_session() as session:
        for c in session.scalars(select(MarketplaceConnection).where(MarketplaceConnection.company_id == company_id)):
            rows.append(ConnectionHealthRow(
                connection_type="ECOMMERCE", connection_id=c.connection_id,
                platform_label=_ECOMMERCE_PLATFORM_LABELS.get(c.platform_code, c.platform_code),
                display_name=c.store_url, consecutive_failure_count=c.consecutive_failure_count,
                last_error_message=c.last_error_message, last_checked_at=c.last_checked_at,
            ))
        for c in session.scalars(select(SocialConnection).where(SocialConnection.company_id == company_id)):
            rows.append(ConnectionHealthRow(
                connection_type="SOCIAL", connection_id=c.connection_id,
                platform_label=_SOCIAL_PLATFORM_LABELS.get(c.platform_code, c.platform_code),
                display_name=c.display_name, consecutive_failure_count=c.consecutive_failure_count,
                last_error_message=c.last_error_message, last_checked_at=c.last_checked_at,
            ))
    rows.sort(key=lambda r: r.consecutive_failure_count, reverse=True)
    return rows
