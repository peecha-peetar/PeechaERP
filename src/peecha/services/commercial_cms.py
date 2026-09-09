"""سینکِ مقاله با CMS (وردپرس) -- طبقِ ادامه‌یِ اولویتِ بخشِ محتوا/
بازاریابی («قسمتِ سئو و پست خودکار ... و تقویمِ محتوایی» → مرحله‌یِ
بعدی: سینکِ محتوا با وردپرس). معماری هم‌الگو با commercial_social.py:
اعتبارِ اتصال (نامِ‌کاربری + رمزِ‌کاره/Application Password) رمزنگاری‌شده
ذخیره می‌شود؛ هر مقاله به یک اتصال متصل است و external_post_id پس از
اولین انتشار برایِ به‌روزرسانی‌هایِ بعدی نگه داشته می‌شود."""

from __future__ import annotations

import datetime

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import CmsArticle, CmsConnection

_SUPPORTED_PLATFORMS = ("WORDPRESS",)


def list_connections(company_id: int) -> list[CmsConnection]:
    with new_session() as session:
        return list(session.scalars(select(CmsConnection).where(CmsConnection.company_id == company_id)))


def create_connection(company_id: int, platform_code: str, display_name: str, site_url: str, username: str, app_password: str) -> int:
    if platform_code not in _SUPPORTED_PLATFORMS:
        raise ValueError("پلتفرمِ نامعتبر است.")
    if not display_name.strip() or not site_url.strip() or not username.strip() or not app_password.strip():
        raise ValueError("نام، آدرسِ سایت، نامِ‌کاربری، و رمزِ‌کاره الزامی‌اند.")
    from peecha.services import ecommerce_credentials

    with new_session() as session:
        row = CmsConnection(
            company_id=company_id, platform_code=platform_code, display_name=display_name.strip(),
            site_url=site_url.strip(), username=username.strip(),
            app_password_encrypted=ecommerce_credentials.encrypt_credentials({"app_password": app_password.strip()}),
        )
        session.add(row)
        session.commit()
        return row.connection_id


def set_active(connection_id: int, is_active: bool) -> None:
    with new_session() as session:
        row = session.get(CmsConnection, connection_id)
        if row is None:
            raise ValueError("اتصال نامعتبر است.")
        row.is_active = is_active
        session.commit()


def _get_connection(connection_id: int) -> CmsConnection:
    with new_session() as session:
        row = session.get(CmsConnection, connection_id)
        if row is None:
            raise ValueError("اتصال نامعتبر است.")
        return row


def _decrypt_app_password(connection: CmsConnection) -> str:
    from peecha.services import ecommerce_credentials

    creds = ecommerce_credentials.decrypt_credentials(connection.app_password_encrypted)
    app_password = creds.get("app_password", "")
    if not app_password:
        raise ValueError("این اتصال رمزِ‌کاره‌یِ معتبری ندارد.")
    return app_password


def _record_connection_health(connection_id: int, error_message: str | None) -> None:
    """طبقِ ادامه‌یِ اولویت‌بندی («نگهبانِ اتصال»/«بررسیِ سلامتِ سایت»):
    هم‌الگو با commercial_ecommerce/commercial_social._record_connection_health."""
    with new_session() as session:
        row = session.get(CmsConnection, connection_id)
        if row is None:
            return
        row.last_checked_at = datetime.datetime.now(datetime.timezone.utc)
        if error_message is None:
            row.consecutive_failure_count = 0
            row.last_error_message = None
        else:
            row.consecutive_failure_count += 1
            row.last_error_message = error_message
        session.commit()


def test_connection(connection_id: int) -> tuple[bool, str]:
    from peecha.integrations.cms import wordpress_client

    connection = _get_connection(connection_id)
    app_password = _decrypt_app_password(connection)
    ok, message = wordpress_client.check_connection(connection.site_url, connection.username, app_password)
    _record_connection_health(connection_id, None if ok else message)
    return ok, message


def create_article(company_id: int, connection_id: int, title: str, body_html: str) -> int:
    if not title.strip():
        raise ValueError("عنوانِ مقاله نمی‌تواند خالی باشد.")
    if not body_html.strip():
        raise ValueError("متنِ مقاله نمی‌تواند خالی باشد.")
    with new_session() as session:
        row = CmsArticle(
            company_id=company_id, connection_id=connection_id, title=title.strip(),
            body_html=body_html.strip(), status_code="DRAFT",
        )
        session.add(row)
        session.commit()
        return row.article_id


def list_articles(company_id: int) -> list[CmsArticle]:
    with new_session() as session:
        stmt = select(CmsArticle).where(CmsArticle.company_id == company_id).order_by(CmsArticle.created_at.desc())
        return list(session.scalars(stmt))


def publish_article(article_id: int) -> None:
    """طبقِ هم‌الگو با پستِ خودکار: وضعیت همیشه صریحاً به PUBLISHED یا
    FAILED به‌روزرسانی می‌شود -- نه اینکه در حالتِ نامشخص باقی بماند.
    اگر مقاله قبلاً منتشر شده باشد (external_post_id موجود است)، همان
    پستِ وردپرس به‌روزرسانی می‌شود، نه اینکه پستِ تازه ساخته شود."""
    from peecha.integrations.cms import wordpress_client

    with new_session() as session:
        row = session.get(CmsArticle, article_id)
        if row is None:
            raise ValueError("مقاله نامعتبر است.")
        connection_id, title, body_html, external_post_id = row.connection_id, row.title, row.body_html, row.external_post_id

    connection = _get_connection(connection_id)
    app_password = _decrypt_app_password(connection)
    try:
        if external_post_id:
            data = wordpress_client.update_post(connection.site_url, connection.username, app_password, external_post_id, title, body_html)
        else:
            data = wordpress_client.create_post(connection.site_url, connection.username, app_password, title, body_html)
    except Exception as exc:  # noqa: BLE001 -- شکستِ انتشار نباید استثنایِ خام بالا برود
        _record_connection_health(connection_id, str(exc))
        with new_session() as session:
            row = session.get(CmsArticle, article_id)
            row.status_code = "FAILED"
            row.error_message = str(exc)
            row.updated_at = datetime.datetime.now(datetime.timezone.utc)
            session.commit()
        raise

    _record_connection_health(connection_id, None)
    with new_session() as session:
        row = session.get(CmsArticle, article_id)
        row.status_code = "PUBLISHED"
        row.external_post_id = str(data.get("id", external_post_id or ""))
        row.external_url = data.get("link")
        row.published_at = datetime.datetime.now(datetime.timezone.utc)
        row.error_message = None
        row.updated_at = datetime.datetime.now(datetime.timezone.utc)
        session.commit()
