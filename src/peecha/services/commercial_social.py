"""پستِ خودکار در تلگرام/بله + تقویمِ محتوایی (طبقِ درخواستِ صریحِ کاربر).

بله (tapi.bale.ir) دقیقاً همان Bot APIِ استانداردِ تلگرام را پیاده
می‌کند -- پس این‌جا با یک platform_code واحد به هردو سرویس می‌شود.
معماری هم‌الگو با commercial_ecommerce.py است: توکنِ بات رمزنگاری‌شده
ذخیره می‌شود، و run_due_posts (تیکِ دوره‌ایِ شل) دقیقاً هم‌شکلِ
run_due_auto_syncs عمل می‌کند."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import ContentCalendarPost, SocialConnection

_SUPPORTED_PLATFORMS = ("TELEGRAM", "BALE")


def list_connections(company_id: int) -> list[SocialConnection]:
    with new_session() as session:
        return list(session.scalars(select(SocialConnection).where(SocialConnection.company_id == company_id)))


def create_connection(company_id: int, platform_code: str, display_name: str, chat_id: str, bot_token: str) -> int:
    if platform_code not in _SUPPORTED_PLATFORMS:
        raise ValueError("پلتفرمِ نامعتبر است.")
    if not display_name.strip() or not chat_id.strip() or not bot_token.strip():
        raise ValueError("نام، شناسه‌یِ چت، و توکنِ بات الزامی‌اند.")
    from peecha.services import ecommerce_credentials

    with new_session() as session:
        row = SocialConnection(
            company_id=company_id, platform_code=platform_code, display_name=display_name.strip(),
            chat_id=chat_id.strip(), bot_token_encrypted=ecommerce_credentials.encrypt_credentials({"bot_token": bot_token.strip()}),
        )
        session.add(row)
        session.commit()
        return row.connection_id


def set_active(connection_id: int, is_active: bool) -> None:
    with new_session() as session:
        row = session.get(SocialConnection, connection_id)
        if row is None:
            raise ValueError("اتصال نامعتبر است.")
        row.is_active = is_active
        session.commit()


def _get_connection(connection_id: int) -> SocialConnection:
    with new_session() as session:
        row = session.get(SocialConnection, connection_id)
        if row is None:
            raise ValueError("اتصال نامعتبر است.")
        return row


def _decrypt_bot_token(connection: SocialConnection) -> str:
    from peecha.services import ecommerce_credentials

    creds = ecommerce_credentials.decrypt_credentials(connection.bot_token_encrypted)
    bot_token = creds.get("bot_token", "")
    if not bot_token:
        raise ValueError("این اتصال توکنِ باتِ معتبری ندارد.")
    return bot_token


def test_connection(connection_id: int) -> tuple[bool, str]:
    from peecha.integrations.social import telegram_client

    connection = _get_connection(connection_id)
    bot_token = _decrypt_bot_token(connection)
    return telegram_client.check_connection(connection.platform_code, bot_token)


def send_message_now(connection_id: int, text: str) -> None:
    from peecha.integrations.social import telegram_client

    connection = _get_connection(connection_id)
    bot_token = _decrypt_bot_token(connection)
    telegram_client.send_message(connection.platform_code, bot_token, connection.chat_id, text)


# ---------------------------------------------------------------------
# تقویمِ محتوا
# ---------------------------------------------------------------------
def create_post(company_id: int, connection_id: int, title: str | None, body_text: str, scheduled_at: datetime.datetime) -> int:
    if not body_text.strip():
        raise ValueError("متنِ پست نمی‌تواند خالی باشد.")
    with new_session() as session:
        row = ContentCalendarPost(
            company_id=company_id, connection_id=connection_id, title=(title or "").strip() or None,
            body_text=body_text.strip(), scheduled_at=scheduled_at, status_code="SCHEDULED",
        )
        session.add(row)
        session.commit()
        return row.post_id


def list_posts(company_id: int, date_from: datetime.date | None = None, date_to: datetime.date | None = None) -> list[ContentCalendarPost]:
    with new_session() as session:
        stmt = select(ContentCalendarPost).where(ContentCalendarPost.company_id == company_id)
        if date_from is not None:
            stmt = stmt.where(ContentCalendarPost.scheduled_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(ContentCalendarPost.scheduled_at < date_to + datetime.timedelta(days=1))
        stmt = stmt.order_by(ContentCalendarPost.scheduled_at)
        return list(session.scalars(stmt))


def cancel_post(post_id: int) -> None:
    with new_session() as session:
        row = session.get(ContentCalendarPost, post_id)
        if row is None:
            raise ValueError("پست نامعتبر است.")
        if row.status_code != "SCHEDULED":
            raise ValueError("فقط پستِ زمان‌بندی‌شده قابلِ‌لغو است.")
        row.status_code = "CANCELED"
        session.commit()


def send_post_now(post_id: int) -> None:
    """طبقِ رفعِ باگِ واقعیِ بالقوه (هم‌الگو با انضباطِ سینکِ فروشِ
    اینترنتی): وضعیت همیشه صریحاً به SENT یا FAILED به‌روزرسانی می‌شود --
    نه اینکه در حالتِ نامشخص باقی بماند."""
    with new_session() as session:
        row = session.get(ContentCalendarPost, post_id)
        if row is None:
            raise ValueError("پست نامعتبر است.")
        connection_id, body_text, title = row.connection_id, row.body_text, row.title

    text = f"{title}\n\n{body_text}" if title else body_text
    try:
        send_message_now(connection_id, text)
    except Exception as exc:  # noqa: BLE001 -- شکستِ ارسال نباید استثنایِ خام بالا برود
        with new_session() as session:
            row = session.get(ContentCalendarPost, post_id)
            row.status_code = "FAILED"
            row.error_message = str(exc)
            session.commit()
        raise
    with new_session() as session:
        row = session.get(ContentCalendarPost, post_id)
        row.status_code = "SENT"
        row.sent_at = datetime.datetime.now(datetime.timezone.utc)
        row.error_message = None
        session.commit()


def list_due_posts(company_id: int, now: datetime.datetime | None = None) -> list[ContentCalendarPost]:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    with new_session() as session:
        stmt = select(ContentCalendarPost).where(
            ContentCalendarPost.company_id == company_id,
            ContentCalendarPost.status_code == "SCHEDULED",
            ContentCalendarPost.scheduled_at <= now,
        )
        return list(session.scalars(stmt))


@dataclass
class PostSendResult:
    post_id: int
    error_message: str | None


def run_due_posts(company_id: int, now: datetime.datetime | None = None) -> list[PostSendResult]:
    """طبقِ درخواستِ صریح («تقویمِ محتوایی» + «پستِ خودکار»): تیکِ دوره‌ایِ
    شل (هم‌الگو با run_due_auto_syncs) این تابع را صدا می‌زند -- شکستِ
    ارسالِ یک پست نباید بقیه را متوقف کند."""
    results: list[PostSendResult] = []
    for post in list_due_posts(company_id, now):
        try:
            send_post_now(post.post_id)
            results.append(PostSendResult(post_id=post.post_id, error_message=None))
        except Exception as exc:  # noqa: BLE001 -- شکستِ یک پست نباید بقیه را متوقف کند
            results.append(PostSendResult(post_id=post.post_id, error_message=str(exc)))
    return results
