"""نگهبانِ اتصال و بررسیِ سلامتِ سایت -- طبقِ ادامه‌یِ اولویت‌بندیِ بخشِ
عملیاتی: قبل از این، شکستِ تیکِ خودکارِ سینکِ فروشِ اینترنتی و پستِ
خودکار کاملاً بی‌صدا رد می‌شد (نه در دیتابیس، نه در UI اثری داشت) --
یعنی یک توکن/رمزِ منقضی‌شده می‌توانست هفته‌ها بدونِ آنکه کسی متوجه شود،
همگام‌سازی را متوقف کرده باشد. این ماژول اتصال‌هایِ فروشگاهی
(WooCommerce/PrestaShop/Torob)، تلگرام/بله، و وردپرس را که شمارندهٔ
شکستِ پیاپی‌شان از آستانه گذشته، یک‌جا فهرست می‌کند -- هم منفعلانه (از
رویِ تیک‌هایِ خودکارِ گذشته) و هم فعالانه (run_health_check_now: آزمایشِ
همینِ الانِ همه‌یِ اتصال‌ها، بدونِ نیاز به منتظرِ تیکِ بعدی بودن)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import CmsConnection, MarketplaceConnection, SocialConnection

_UNHEALTHY_THRESHOLD = 3

_ECOMMERCE_PLATFORM_LABELS = {"WOOCOMMERCE": "ووکامرس", "PRESTASHOP": "پرستاشاپ", "TOROB": "ترب", "OTHER": "سایر"}
_SOCIAL_PLATFORM_LABELS = {"TELEGRAM": "تلگرام", "BALE": "بله"}
_CMS_PLATFORM_LABELS = {"WORDPRESS": "وردپرس"}


@dataclass
class ConnectionHealthRow:
    connection_type: str  # ECOMMERCE|SOCIAL|CMS
    connection_id: int
    platform_label: str
    display_name: str
    consecutive_failure_count: int
    last_error_message: str | None
    last_checked_at: object | None


def _all_connection_rows(company_id: int) -> list[ConnectionHealthRow]:
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
        for c in session.scalars(select(CmsConnection).where(CmsConnection.company_id == company_id)):
            rows.append(ConnectionHealthRow(
                connection_type="CMS", connection_id=c.connection_id,
                platform_label=_CMS_PLATFORM_LABELS.get(c.platform_code, c.platform_code),
                display_name=c.display_name, consecutive_failure_count=c.consecutive_failure_count,
                last_error_message=c.last_error_message, last_checked_at=c.last_checked_at,
            ))
    return rows


def list_all_connection_health(company_id: int) -> list[ConnectionHealthRow]:
    """طبقِ ادامه‌یِ اولویت‌بندی: برخلافِ list_unhealthy_connections
    (فقط اتصال‌هایِ ناسالم)، این تابع همه‌یِ اتصال‌ها را با وضعیتِ سلامت
    برمی‌گرداند -- برایِ نمایِ کاملِ صفحه‌یِ نگهبان."""
    rows = _all_connection_rows(company_id)
    rows.sort(key=lambda r: r.consecutive_failure_count, reverse=True)
    return rows


def list_unhealthy_connections(company_id: int) -> list[ConnectionHealthRow]:
    rows = [r for r in _all_connection_rows(company_id) if r.consecutive_failure_count >= _UNHEALTHY_THRESHOLD]
    rows.sort(key=lambda r: r.consecutive_failure_count, reverse=True)
    return rows


def run_health_check_now(company_id: int) -> list[ConnectionHealthRow]:
    """طبقِ ادامه‌یِ اولویت‌بندی («بررسیِ سلامتِ سایت»): برخلافِ فهرستِ
    منفعلانه (که فقط شکستِ تیک‌هایِ خودکارِ گذشته را نشان می‌دهد)، این
    تابع همینِ الان به هر اتصال سر می‌زند -- برایِ اتصالی که هنوز هیچ
    تیکِ خودکاری برایش اجرا نشده (یا اتصالی که کاربر تازه فعالش کرده)
    هم بلافاصله وضعیتِ واقعی را نشان می‌دهد."""
    from peecha.services import commercial_cms as cms_service
    from peecha.services import commercial_ecommerce as ecommerce_service
    from peecha.services import commercial_social as social_service

    for connection in ecommerce_service.list_connections(company_id):
        try:
            ecommerce_service.test_connection(connection.connection_id)
        except Exception:  # noqa: BLE001 -- شکستِ آزمایشِ یک اتصال نباید بقیه را متوقف کند
            pass
    for connection in social_service.list_connections(company_id):
        try:
            social_service.test_connection(connection.connection_id)
        except Exception:  # noqa: BLE001
            pass
    for connection in cms_service.list_connections(company_id):
        try:
            cms_service.test_connection(connection.connection_id)
        except Exception:  # noqa: BLE001
            pass

    return list_all_connection_health(company_id)
