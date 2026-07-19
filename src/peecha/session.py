"""وضعیت نشست جاری (کاربر/شرکت/سالِ مالی/زبانِ لاگین‌شده).

اپ دسکتاپ تک‌کاربره است در هر لحظه (یک پنجره = یک کاربر لاگین‌شده)، پس
نگه‌داشتن این وضعیت به‌صورت متغیرهای سطح‌ماژول ساده و کافی است — نیازی به
مدیریت نشست پیچیده (مثل یک سرور چندکاربره) نیست.

current_fiscal_year/current_language زمینه‌ی نمایشی/پیش‌فرض‌اند (سوییچرِ
هدر، طبق درخواستِ صریح)، نه محدودکننده‌ی داده: سالِ مالیِ واقعیِ هر سند طبق
تاریخِ خودِ آن سند تعیین می‌شود (services/journal_entries.py)، نه سوییچرِ
هدر — چون سندی با تاریخِ یک دوره باید همیشه در همان دوره ثبت شود، حتی اگر
کاربر لحظه‌ای «سالِ فعال» دیگری را در هدر انتخاب کرده باشد.
"""

from __future__ import annotations

from peecha.db.models.core import Company
from peecha.db.models.security import User
from peecha.services.fiscal_years import FiscalYearRow
from peecha.services.languages import LanguageRow

current_user: User | None = None
current_company: Company | None = None
current_fiscal_year: FiscalYearRow | None = None
current_language: LanguageRow | None = None


def is_logged_in() -> bool:
    return current_user is not None


def log_out() -> None:
    global current_user, current_company, current_fiscal_year, current_language
    current_user = None
    current_company = None
    current_fiscal_year = None
    current_language = None
