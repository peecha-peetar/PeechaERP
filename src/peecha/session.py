"""وضعیت نشست جاری (کاربر/شرکت لاگین‌شده).

اپ دسکتاپ تک‌کاربره است در هر لحظه (یک پنجره = یک کاربر لاگین‌شده)، پس
نگه‌داشتن این وضعیت به‌صورت متغیرهای سطح‌ماژول ساده و کافی است — نیازی به
مدیریت نشست پیچیده (مثل یک سرور چندکاربره) نیست.
"""

from __future__ import annotations

from peecha.db.models.core import Company
from peecha.db.models.security import User

current_user: User | None = None
current_company: Company | None = None


def is_logged_in() -> bool:
    return current_user is not None


def log_out() -> None:
    global current_user, current_company
    current_user = None
    current_company = None
