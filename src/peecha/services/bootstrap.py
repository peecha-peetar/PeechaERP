"""راه‌اندازی اولیه‌ی سیستم: وقتی دیتابیس تازه ساخته شده و هیچ کاربر/شرکتی
ندارد، این تابع اولین زبان (fa-IR)، اولین ارز (IRR)، اولین شرکت، و اولین
کاربر (مدیر سیستم) را یک‌جا می‌سازد — چون این‌ها به هم وابسته‌اند (کاربر به
شرکت، شرکت به ارز/زبان) و بدون این مرحله هیچ صفحه‌ی دیگری (کدینگ حسابداری،
داشبورد) داده‌ی معناداری برای کار کردن ندارد.
"""

from __future__ import annotations

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.core import Company, Currency, Language
from peecha.db.models.security import User, UserCompany
from peecha.services import detail_dimensions as dimensions_service
from peecha.services.auth import hash_password


def bootstrap_system(username: str, full_name: str, password: str, company_name: str) -> User:
    password_hash, password_salt = hash_password(password)
    with new_session() as db_session:
        language = db_session.scalar(select(Language).where(Language.code == "fa-IR"))
        if language is None:
            language = Language(code="fa-IR", native_name="فارسی", is_rtl=True, is_default=True, is_active=True)
            db_session.add(language)
            db_session.flush()

        currency = db_session.scalar(select(Currency).where(Currency.iso_code == "IRR"))
        if currency is None:
            currency = Currency(iso_code="IRR", symbol="ریال", decimal_places=0, is_active=True)
            db_session.add(currency)
            db_session.flush()

        # چند ارزِ رایجِ دیگر هم از ابتدا موجود باشند تا فرمِ تعریفِ شرکت
        # بدون نیاز به صفحه‌ی جداگانه‌ی مدیریتِ ارز، گزینه برای انتخاب داشته باشد.
        for iso_code, symbol, decimal_places in (("USD", "$", 2), ("EUR", "€", 2)):
            if not db_session.scalar(select(Currency).where(Currency.iso_code == iso_code)):
                db_session.add(Currency(iso_code=iso_code, symbol=symbol, decimal_places=decimal_places, is_active=True))
        db_session.flush()

        company = Company(
            code="C1",
            legal_name=company_name,
            display_name=company_name,
            base_currency_id=currency.currency_id,
            default_language_id=language.language_id,
        )
        db_session.add(company)
        db_session.flush()
        dimensions_service.ensure_person_dimension(db_session, company.company_id)
        dimensions_service.ensure_person_groups(db_session, company.company_id)

        user = User(
            username=username,
            full_name=full_name,
            password_hash=password_hash,
            password_salt=password_salt,
            is_super_admin=True,
            is_active=True,
            must_change_password=False,
            default_language_id=language.language_id,
        )
        db_session.add(user)
        db_session.flush()

        db_session.add(UserCompany(user_id=user.user_id, company_id=company.company_id, is_default=True))
        db_session.commit()
        db_session.refresh(user)
        db_session.expunge(user)
        return user
