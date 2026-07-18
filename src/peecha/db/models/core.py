"""مدل‌های schema هسته: چندزبانگی، چندشرکتی، چندارزی.

معادل db/schema/001_core_i18n_and_tenancy.sql
"""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from peecha.db.base import Base


class Language(Base):
    __tablename__ = "languages"
    __table_args__ = {"schema": "core"}

    language_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)
    native_name: Mapped[str] = mapped_column(String(50))
    is_rtl: Mapped[bool] = mapped_column(Boolean, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)


class Translation(Base):
    __tablename__ = "translations"
    __table_args__ = {"schema": "core"}

    translation_id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int]
    property_name: Mapped[str] = mapped_column(String(50))
    language_id: Mapped[int] = mapped_column(ForeignKey("core.languages.language_id"))
    value: Mapped[str] = mapped_column(String(400))


class Currency(Base):
    __tablename__ = "currencies"
    __table_args__ = {"schema": "core"}

    currency_id: Mapped[int] = mapped_column(primary_key=True)
    iso_code: Mapped[str] = mapped_column(String(3), unique=True)
    symbol: Mapped[str | None] = mapped_column(String(10))
    decimal_places: Mapped[int] = mapped_column(SmallInteger, default=2)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = {"schema": "core"}

    company_id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    legal_name: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(200))
    economic_code: Mapped[str | None] = mapped_column(String(30))
    registration_no: Mapped[str | None] = mapped_column(String(30))
    national_id: Mapped[str | None] = mapped_column(String(30))
    fiscal_year_start_month: Mapped[int] = mapped_column(SmallInteger, default=1)
    fiscal_year_start_day: Mapped[int] = mapped_column(SmallInteger, default=1)
    base_currency_id: Mapped[int] = mapped_column(ForeignKey("core.currencies.currency_id"))
    default_language_id: Mapped[int] = mapped_column(ForeignKey("core.languages.language_id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime]

    base_currency: Mapped[Currency] = relationship(foreign_keys=[base_currency_id])
    default_language: Mapped[Language] = relationship(foreign_keys=[default_language_id])


class CompanyCurrency(Base):
    __tablename__ = "company_currencies"
    __table_args__ = {"schema": "core"}

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    currency_id: Mapped[int] = mapped_column(ForeignKey("core.currencies.currency_id"), primary_key=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    __table_args__ = {"schema": "core"}

    exchange_rate_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    currency_id: Mapped[int] = mapped_column(ForeignKey("core.currencies.currency_id"))
    rate_date: Mapped[datetime.date] = mapped_column(Date)
    rate_to_base: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
