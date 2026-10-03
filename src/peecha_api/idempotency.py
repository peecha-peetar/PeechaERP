"""دیدوپلیکیتِ درخواست‌هایِ ایجادکننده -- طبقِ R133، رفعِ محدودیتِ
مستندشده در R132: اپِ موبایل برایِ هر اقدامِ صف‌آفلاین یک کلید می‌سازد؛
اگر همان کلید دوباره ببینیم (چون پاسخِ اجرایِ قبلی به کلاینت نرسیده
بود)، به‌جایِ اجرایِ دوباره‌یِ منطق، همان پاسخِ ذخیره‌شده برگردانده
می‌شود."""

from __future__ import annotations

from typing import Callable, TypeVar

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.security import ApiIdempotencyKey

T = TypeVar("T")


class IdempotentReplay(Exception):
    """اگر این کلید قبلاً با موفقیت اجرا شده، پاسخِ ذخیره‌شده را حمل می‌کند
    -- روتر باید این را بگیرد و مستقیماً همان status/body را برگرداند."""

    def __init__(self, status: int, body: dict):
        super().__init__("idempotent replay")
        self.status = status
        self.body = body


def run_idempotent(
    idempotency_key: str | None, endpoint: str, user_id: int, company_id: int,
    success_status: int, compute: Callable[[], T], serialize: Callable[[T], dict],
) -> dict:
    """همیشه دیکشنریِ سریالایزشده را برمی‌گرداند (نه T خام) -- طبقِ
    قراردادِ روترها که پاسخِ JSON برمی‌گردانند. اگر idempotency_key داده
    نشده (کلاینتِ قدیمی/دسکتاپ)، رفتارِ قبلی بدونِ دیدوپلیکیت اجرا
    می‌شود -- این ویژگی کاملاً اختیاری و عطف‌به‌ماسبق‌سازگار است. اگر
    کلید داده شده و قبلاً دیده شده، IdempotentReplay پرتاب می‌شود؛ در
    غیرِ این‌صورت compute() اجرا و پاسخ ذخیره می‌شود."""
    if idempotency_key is None:
        return serialize(compute())

    with new_session() as session:
        existing = session.get(ApiIdempotencyKey, (user_id, idempotency_key))
        if existing is not None:
            raise IdempotentReplay(existing.response_status, existing.response_body)

    result = compute()
    body = serialize(result)
    with new_session() as session:
        # اگر بینِ چکِ بالا و این‌جا (مثلاً دو درخواستِ هم‌زمان از یک
        # ریتریِ کلاینت) رکورد از قبل ساخته شده باشد، همان را نگه می‌داریم
        # -- تصادفِ کلیدِ همان کاربر با محتوایِ متفاوت عملاً رخ نمی‌دهد
        # چون کلیدها با ترکیبِ زمان+رندوم در کلاینت ساخته می‌شوند.
        existing = session.get(ApiIdempotencyKey, (user_id, idempotency_key))
        if existing is None:
            session.add(
                ApiIdempotencyKey(
                    user_id=user_id, company_id=company_id, idempotency_key=idempotency_key,
                    endpoint=endpoint, response_status=success_status, response_body=body,
                )
            )
            session.commit()
    return body
