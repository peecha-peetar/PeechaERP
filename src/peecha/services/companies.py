"""سرویس مدیریت شرکت‌ها (core.companies) — چندشرکتی: هر شرکت ارز پایه و
زبانِ پیش‌فرضِ خودش را دارد؛ کاربران بعداً (سرویس users) به شرکت‌های مشخصی
دسترسی می‌گیرند."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.core import Company, Currency, Language
from peecha.db.models.security import UserCompany
from peecha.services import detail_dimensions as dimensions_service


@dataclass
class CompanyRow:
    company_id: int
    code: str
    legal_name: str
    display_name: str
    economic_code: str | None
    registration_no: str | None
    national_id: str | None
    fiscal_year_start_month: int
    fiscal_year_start_day: int
    base_currency_id: int
    base_currency_code: str
    default_language_id: int
    default_language_name: str
    is_active: bool


@dataclass
class CurrencyOption:
    currency_id: int
    iso_code: str
    decimal_places: int


def get_company_model(company_id: int) -> Company | None:
    """شیءِ کاملِ ORM (نه فقط CompanyRow) — برای session.current_company، چون
    بقیه‌ی برنامه به ستون‌های خامِ مدل (مثلاً fiscal_year_start_month) نیاز
    دارد، نه dataclass خلاصه‌شده."""
    with new_session() as session:
        return session.get(Company, company_id)


def list_currencies() -> list[CurrencyOption]:
    with new_session() as session:
        rows = session.scalars(select(Currency).where(Currency.is_active).order_by(Currency.iso_code)).all()
        return [
            CurrencyOption(currency_id=c.currency_id, iso_code=c.iso_code, decimal_places=c.decimal_places)
            for c in rows
        ]


def update_currency_decimal_places(currency_id: int, decimal_places: int) -> None:
    if decimal_places < 0 or decimal_places > 6:
        raise ValueError("رقم اعشار باید بین ۰ تا ۶ باشد.")
    with new_session() as session:
        currency = session.get(Currency, currency_id)
        if currency is None:
            raise ValueError("ارز نامعتبر است.")
        currency.decimal_places = decimal_places
        session.commit()


def list_companies() -> list[CompanyRow]:
    with new_session() as session:
        companies = session.scalars(select(Company).order_by(Company.code)).all()
        currencies = {c.currency_id: c.iso_code for c in session.scalars(select(Currency))}
        langs = {l.language_id: l.native_name for l in session.scalars(select(Language))}
        return [
            CompanyRow(
                company_id=c.company_id,
                code=c.code,
                legal_name=c.legal_name,
                display_name=c.display_name,
                economic_code=c.economic_code,
                registration_no=c.registration_no,
                national_id=c.national_id,
                fiscal_year_start_month=c.fiscal_year_start_month,
                fiscal_year_start_day=c.fiscal_year_start_day,
                base_currency_id=c.base_currency_id,
                base_currency_code=currencies.get(c.base_currency_id, "?"),
                default_language_id=c.default_language_id,
                default_language_name=langs.get(c.default_language_id, "?"),
                is_active=c.is_active,
            )
            for c in companies
        ]


def list_companies_for_user(user_id: int) -> list[CompanyRow]:
    """فقط شرکت‌هایی که کاربر از طریق sec.user_companies دسترسی دارد —
    برای سوییچرِ «شرکتِ فعال» در هدر، که طبق درخواستِ صریح باید محدود به
    شرکت‌های قابل‌دسترسِ همان کاربر باشد، نه فهرستِ کاملِ همه‌ی شرکت‌ها."""
    with new_session() as session:
        company_ids = {
            row for row in session.scalars(
                select(UserCompany.company_id).where(UserCompany.user_id == user_id)
            )
        }
        if not company_ids:
            return []
        companies = session.scalars(
            select(Company).where(Company.company_id.in_(company_ids)).order_by(Company.code)
        ).all()
        currencies = {c.currency_id: c.iso_code for c in session.scalars(select(Currency))}
        langs = {l.language_id: l.native_name for l in session.scalars(select(Language))}
        return [
            CompanyRow(
                company_id=c.company_id,
                code=c.code,
                legal_name=c.legal_name,
                display_name=c.display_name,
                economic_code=c.economic_code,
                registration_no=c.registration_no,
                national_id=c.national_id,
                fiscal_year_start_month=c.fiscal_year_start_month,
                fiscal_year_start_day=c.fiscal_year_start_day,
                base_currency_id=c.base_currency_id,
                base_currency_code=currencies.get(c.base_currency_id, "?"),
                default_language_id=c.default_language_id,
                default_language_name=langs.get(c.default_language_id, "?"),
                is_active=c.is_active,
            )
            for c in companies
        ]


def create_company(
    code: str,
    legal_name: str,
    display_name: str,
    base_currency_id: int,
    default_language_id: int,
    fiscal_year_start_month: int = 1,
    fiscal_year_start_day: int = 1,
    economic_code: str | None = None,
    registration_no: str | None = None,
    national_id: str | None = None,
) -> Company:
    with new_session() as session:
        if session.scalar(select(Company).where(Company.code == code)):
            raise ValueError("این کدِ شرکت قبلاً استفاده شده است.")
        company = Company(
            code=code,
            legal_name=legal_name,
            display_name=display_name,
            economic_code=economic_code or None,
            registration_no=registration_no or None,
            national_id=national_id or None,
            fiscal_year_start_month=fiscal_year_start_month,
            fiscal_year_start_day=fiscal_year_start_day,
            base_currency_id=base_currency_id,
            default_language_id=default_language_id,
            is_active=True,
        )
        session.add(company)
        session.flush()
        dimensions_service.ensure_person_dimension(session, company.company_id)
        session.commit()
        session.refresh(company)
        session.expunge(company)
        return company


def update_company(
    company_id: int,
    legal_name: str,
    display_name: str,
    base_currency_id: int,
    default_language_id: int,
    fiscal_year_start_month: int,
    fiscal_year_start_day: int,
    is_active: bool,
    economic_code: str | None = None,
    registration_no: str | None = None,
    national_id: str | None = None,
) -> Company:
    with new_session() as session:
        company = session.get(Company, company_id)
        if company is None:
            raise ValueError("شرکت نامعتبر است.")
        company.legal_name = legal_name
        company.display_name = display_name
        company.economic_code = economic_code or None
        company.registration_no = registration_no or None
        company.national_id = national_id or None
        company.base_currency_id = base_currency_id
        company.default_language_id = default_language_id
        company.fiscal_year_start_month = fiscal_year_start_month
        company.fiscal_year_start_day = fiscal_year_start_day
        company.is_active = is_active
        session.commit()
        session.refresh(company)
        session.expunge(company)
        return company
