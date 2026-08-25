"""مدل‌های ماژولِ خزانه‌داری (نگاشتِ حساب‌ها، دسته‌چک، چک‌هایِ دریافتی/پرداختی).

معادل db/schema/024_treasury.sql
"""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from peecha.db.base import Base


class TreasuryAccountMapping(Base):
    __tablename__ = "account_mappings"
    __table_args__ = {"schema": "treasury"}

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    mapping_key: Mapped[str] = mapped_column(String(30), primary_key=True)
    # طبقِ آیتمِ ۹: کلیدِ اصلی account_id را هم دربرمی‌گیرد تا چند معین
    # برایِ یک mapping_key مجاز باشد (اسکیمای ۰۳۴).
    account_id: Mapped[int] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"), primary_key=True)
    # طبقِ درخواستِ صریح: تفصیلیِ اختصاصیِ از‌پیش‌تخصیص‌یافته برایِ این روش —
    # اگر پر باشد، دیگر در فرمِ سند دوباره پرسیده نمی‌شود.
    detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))


class CounterpartyAccountMapping(Base):
    """نگاشتِ نوعِ تفصیلی <-> معینِ حساب برایِ دریافت/پرداخت — هر ردیف یا
    یک گروهِ تفصیلیِ اشخاص (person_group_id) یا یک نوع‌بُعدِ غیرِشخصی
    (dimension_type_id) را به یک معین نگاشت می‌کند."""

    __tablename__ = "counterparty_account_mappings"
    __table_args__ = {"schema": "treasury"}

    mapping_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    direction: Mapped[str] = mapped_column(String(10))  # RECEIPT | PAYMENT
    person_group_id: Mapped[int | None] = mapped_column(ForeignKey("acc.person_groups.person_group_id"))
    dimension_type_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_dimension_types.dimension_type_id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))


class DescriptionTemplate(Base):
    """متنِ خودکارِ شرحِ ردیف‌هایِ سندِ دریافت/پرداخت — قابلِ‌ویرایش توسطِ
    کاربر، با جای‌گذارهایی مثلِ {تفصیلی}/{مبلغ}/{طرف_حساب}."""

    __tablename__ = "description_templates"
    __table_args__ = {"schema": "treasury"}

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    template_key: Mapped[str] = mapped_column(String(30), primary_key=True)
    template_text: Mapped[str] = mapped_column(Text)


class Bank(Base):
    """فهرستِ مرجعِ نام‌هایِ بانک — برایِ انتخاب در فیلدِ «بانکِ صادرکننده»یِ
    فرمِ چکِ دریافتی، به‌جایِ تایپِ آزادِ نام."""

    __tablename__ = "banks"
    __table_args__ = {"schema": "treasury"}

    bank_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str | None] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(default=True)


class Checkbook(Base):
    __tablename__ = "checkbooks"
    __table_args__ = {"schema": "treasury"}

    checkbook_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    bank_account_detail_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    start_no: Mapped[int]
    end_no: Mapped[int]
    next_no: Mapped[int]
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class CheckStatus(Base):
    __tablename__ = "check_statuses"
    __table_args__ = {"schema": "treasury"}

    status_id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20))
    applies_to: Mapped[str] = mapped_column(String(10))  # RECEIVED | ISSUED


class ReceivedCheck(Base):
    __tablename__ = "received_checks"
    __table_args__ = {"schema": "treasury"}

    received_check_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    check_no: Mapped[str] = mapped_column(String(30))
    drawee_bank_name: Mapped[str | None] = mapped_column(String(150))
    drawer_name: Mapped[str | None] = mapped_column(String(150))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    due_date: Mapped[datetime.date]
    received_date: Mapped[datetime.date]
    counterparty_detail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc.detail_accounts.detail_account_id")
    )
    status_id: Mapped[int] = mapped_column(ForeignKey("treasury.check_statuses.status_id"))
    source_journal_entry_id: Mapped[int] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    endorsed_to_issued_check_id: Mapped[int | None] = mapped_column(
        ForeignKey("treasury.issued_checks.issued_check_id")
    )
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    # طبقِ درخواستِ صریح: فیلدهایِ تکمیلیِ چکِ دریافتی برایِ ثبتِ کاملِ
    # مشخصاتِ چکِ فیزیکی/صیادی.
    check_serial: Mapped[str | None] = mapped_column(String(30))
    iban: Mapped[str | None] = mapped_column(String(34))
    bank_account_no: Mapped[str | None] = mapped_column(String(40))
    drawer_national_id: Mapped[str | None] = mapped_column(String(15))
    drawer_phone: Mapped[str | None] = mapped_column(String(20))
    bank_id: Mapped[int | None] = mapped_column(ForeignKey("treasury.banks.bank_id"))
    # محلِ فعلیِ نگه‌داریِ چک (نزدِ کدام صندوق/بانکِ مشخص) — پیش‌نیازِ
    # زنجیره‌یِ چندمرحله‌ایِ چرخه‌یِ چک؛ هر مرحله بستانکارِ سندش را از رویِ
    # همین دو ستون می‌خواند، نه از رویِ یک کلیدِ نگاشتِ ثابت.
    current_location_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    current_location_detail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc.detail_accounts.detail_account_id")
    )
    # طبقِ گزارشِ صریح: شماره‌ی ردیفِ (line_no) سندِ اصلی که دقیقاً همین
    # چک از آن آمده — تا حذفِ این چک بتواند فقط همین یک ردیف را از سند
    # حذف/اصلاح کند، نه کلِ سند را. مقدارِ None یعنی داده‌یِ قدیمی (پیش
    # از این ستون) — رفتارِ قدیمی (حذفِ کلِ سند) برایش حفظ می‌شود.
    source_journal_entry_line_no: Mapped[int | None]


class IssuedCheck(Base):
    __tablename__ = "issued_checks"
    __table_args__ = {"schema": "treasury"}

    issued_check_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    checkbook_id: Mapped[int | None] = mapped_column(ForeignKey("treasury.checkbooks.checkbook_id"))
    check_no: Mapped[str] = mapped_column(String(30))
    bank_account_detail_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    payee_name: Mapped[str | None] = mapped_column(String(150))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    due_date: Mapped[datetime.date]
    issue_date: Mapped[datetime.date]
    counterparty_detail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc.detail_accounts.detail_account_id")
    )
    status_id: Mapped[int] = mapped_column(ForeignKey("treasury.check_statuses.status_id"))
    source_journal_entry_id: Mapped[int] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    # طبقِ درخواستِ صریح: هم‌ارزِ فیلدهایِ تکمیلیِ چکِ دریافتی — این‌جا
    # برایِ طرفِ دریافت‌کننده‌یِ چک (نه خودمان که صادرکننده‌ایم).
    check_serial: Mapped[str | None] = mapped_column(String(30))
    iban: Mapped[str | None] = mapped_column(String(34))
    payee_account_no: Mapped[str | None] = mapped_column(String(40))
    payee_national_id: Mapped[str | None] = mapped_column(String(15))
    payee_phone: Mapped[str | None] = mapped_column(String(20))
    payee_bank_id: Mapped[int | None] = mapped_column(ForeignKey("treasury.banks.bank_id"))
    # هم‌ارزِ source_journal_entry_line_no در ReceivedCheck.
    source_journal_entry_line_no: Mapped[int | None]
    # طبقِ درخواستِ صریح: شماره‌یِ صیادیِ چکِ پرداختی — شناسه‌یِ ۱۶رقمیِ
    # چاپ‌شده رویِ چک، مستقل از شماره‌یِ شبا.
    sayad_no: Mapped[str | None] = mapped_column(String(20))


class CheckStageEvent(Base):
    """تاریخچه‌یِ کاملِ چرخه‌یِ عمرِ یک چک — یک ردیف به‌ازایِ هر رویدادی که
    رویِ چک اتفاق می‌افتد (ثبت/انتقال/واگذاری/وصول/برگشت/…)."""

    __tablename__ = "check_stage_events"
    __table_args__ = {"schema": "treasury"}

    event_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    check_kind: Mapped[str] = mapped_column(String(10))  # RECEIVED | ISSUED
    check_id: Mapped[int]
    event_code: Mapped[str] = mapped_column(String(30))
    event_date: Mapped[datetime.date]
    from_status_code: Mapped[str | None] = mapped_column(String(20))
    to_status_code: Mapped[str] = mapped_column(String(20))
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    # طبقِ درخواستِ صریح: برایِ بازگردانیِ دقیقِ محلِ چک هنگامِ حذفِ سندِ این
    # مرحله، محلِ پیش‌از‌این‌مرحله هم نگه‌داری می‌شود.
    from_location_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    from_location_detail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc.detail_accounts.detail_account_id")
    )


class CustomMethod(Base):
    """طبقِ آیتمِ ۷: روشِ سفارشیِ دریافت/پرداختِ هر شرکت — کد و برچسبِ آن،
    که در کمبویِ روشِ ردیفِ فرمِ دریافت/پرداخت هم اضافه می‌شود."""

    __tablename__ = "custom_methods"
    __table_args__ = {"schema": "treasury"}

    custom_method_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    direction: Mapped[str] = mapped_column(String(10))
    code: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(default=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class PettyCashFund(Base):
    """یک «تنخواه»ِ بازِ متعلق به یک تنخواه‌دار (تفصیلیِ سطحِ آخرِ گروهِ
    «تنخواه») — طبقِ گزارشِ صریح، هر تنخواه‌دار می‌تواند هم‌زمان چند
    تنخواهِ باز داشته باشد، هرکدام با شماره‌یِ خودکارِ مستقلِ خودش."""

    __tablename__ = "petty_cash_funds"
    __table_args__ = {"schema": "treasury"}

    fund_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    custodian_detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    fund_no: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(10), default="OPEN")
    opening_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    opening_date: Mapped[datetime.date]
    opening_journal_entry_id: Mapped[int] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    closing_date: Mapped[datetime.date | None]
    closing_journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class PettyCashFundLine(Base):
    """ردیفِ ثبت‌شده در دورانِ بازبودنِ یک تنخواه — طبقِ درخواستِ صریح
    («حتی سندِ موقت هم ثبت نکند»)، این ردیف‌ها هیچ سندِ حسابداری‌ای
    نمی‌سازند؛ فقط هنگامِ بستنِ تنخواه، جمعشان یک سندِ موقتِ پیش‌نویس
    می‌سازد."""

    __tablename__ = "petty_cash_fund_lines"
    __table_args__ = {"schema": "treasury"}

    line_id: Mapped[int] = mapped_column(primary_key=True)
    fund_id: Mapped[int] = mapped_column(ForeignKey("treasury.petty_cash_funds.fund_id"))
    method: Mapped[str] = mapped_column(String(40))
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    description: Mapped[str | None] = mapped_column(String(300))
    detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    check_no: Mapped[str | None] = mapped_column(String(50))
    check_due_date: Mapped[datetime.date | None]
    line_date: Mapped[datetime.date]
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class PettyCashFundExtraDetail(Base):
    """بُعد/گروهِ اضافیِ الزامیِ حسابِ پیش‌پرداختِ تنخواه (غیر از خودِ بُعدِ
    تنخواه‌دار) — انتخابِ هنگامِ افتتاح، برایِ استفاده‌یِ دوباره هنگامِ
    بستنِ همین تنخواه (بدونِ پرسیدنِ دوباره)."""

    __tablename__ = "petty_cash_fund_extra_details"
    __table_args__ = {"schema": "treasury"}

    fund_id: Mapped[int] = mapped_column(ForeignKey("treasury.petty_cash_funds.fund_id"), primary_key=True)
    dimension_type_id: Mapped[int] = mapped_column(
        ForeignKey("acc.detail_dimension_types.dimension_type_id"), primary_key=True
    )
    detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
