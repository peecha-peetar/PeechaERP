"""مدل‌هایِ ماژولِ مدیریتِ بازرگانی (Commercial Management).

معادلِ db/schema/065 تا 077_commercial_*.sql — طبقِ سندِ معماریِ
۱۱مرحله‌ای: خرید و فروش یک اسکلتِ سندِ واحد دارند (commercial_documents/
_lines، متمایزشده با document_type_code)؛ مشتری/تامین‌کننده جدولِ
اقماریِ یک‌به‌یکِ تفصیلیِ گروهِ CUSTOMER/SUPPLIER هستند (هم‌الگو با
inv.items)؛ POS/عمده/آنلاین/نماینده/مارکت‌پلیس همگی کانال (بُعدی رویِ
همان سند) هستند، نه ماژولِ جدا.
"""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from peecha.db.base import Base


# =======================================================================
# قیمت‌گذاری و کانال‌ها — معادلِ 065_commercial_pricing_channels.sql
# =======================================================================
class PriceList(Base):
    __tablename__ = "price_lists"
    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_comm_price_lists_dates"),
        {"schema": "comm"},
    )

    price_list_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    price_list_type_code: Mapped[str] = mapped_column(String(10))  # SALES | PURCHASE
    currency_id: Mapped[int] = mapped_column(ForeignKey("core.currencies.currency_id"))
    channel_code: Mapped[str | None] = mapped_column(String(20))
    valid_from: Mapped[datetime.date] = mapped_column(Date)
    valid_to: Mapped[datetime.date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(default=True)


class Channel(Base):
    __tablename__ = "channels"
    __table_args__ = ({"schema": "comm"},)

    channel_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    channel_type_code: Mapped[str] = mapped_column(String(15))  # POS|WHOLESALE|ONLINE|AGENT|MARKETPLACE
    default_price_list_id: Mapped[int | None] = mapped_column(ForeignKey("comm.price_lists.price_list_id"))
    default_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    is_active: Mapped[bool] = mapped_column(default=True)


class PriceListItem(Base):
    __tablename__ = "price_list_items"
    __table_args__ = (
        UniqueConstraint("price_list_id", "item_id", "uom_id", "min_quantity"),
        {"schema": "comm"},
    )

    price_list_item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    price_list_id: Mapped[int] = mapped_column(ForeignKey("comm.price_lists.price_list_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    uom_id: Mapped[int] = mapped_column(ForeignKey("inv.uom.uom_id"))
    min_quantity: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=1)
    unit_price: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))


class PriceListItemPriceHistory(Base):
    """طبقِ درخواستِ صریح («لاگِ قیمت‌ها را نگه دار تا سابقه حفظ شود و
    اگر اشتباهی شد بشه قیمتو برگردوند»): هر تغییرِ unit_price در
    PriceListItem (چه دستی، چه از وارداتِ قیمتِ تامین‌کننده) این‌جا یک
    ردیف ثبت می‌کند -- old_price=NULL یعنی این اولین‌بار است که این
    ترکیب (کالا/واحد/حداقلِ‌مقدار) در این فهرستِ قیمت مقدار گرفته."""

    __tablename__ = "price_list_item_price_history"
    __table_args__ = {"schema": "comm"}

    history_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    price_list_id: Mapped[int] = mapped_column(ForeignKey("comm.price_lists.price_list_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    uom_id: Mapped[int] = mapped_column(ForeignKey("inv.uom.uom_id"))
    min_quantity: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    old_price: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    new_price: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    source_code: Mapped[str] = mapped_column(String(30), default="MANUAL")
    note: Mapped[str | None] = mapped_column(String(255))
    changed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    changed_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class SupplierPriceImportTemplate(Base):
    """طبقِ درخواستِ صریح («این تطبیق را برایِ دفعاتِ بعد ذخیره کن»):
    تنظیماتِ ستون‌بندیِ فایلِ قیمتِ هر تامین‌کننده (اکسل/PDF) -- کدامین
    ستون کد است، کدامین قیمت، و چند ردیفِ اول (هدر/عنوان) نادیده گرفته
    شود -- تا واردکردنِ دفعاتِ بعدیِ همان تامین‌کننده نیازِ تطبیقِ دستی
    نداشته باشد."""

    __tablename__ = "supplier_price_import_templates"
    __table_args__ = (
        UniqueConstraint("company_id", "supplier_detail_account_id"),
        {"schema": "comm"},
    )

    template_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    supplier_detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    code_column_index: Mapped[int | None] = mapped_column(SmallInteger)
    price_column_index: Mapped[int] = mapped_column(SmallInteger)
    header_row_index: Mapped[int] = mapped_column(SmallInteger, default=0)
    sheet_name: Mapped[str | None] = mapped_column(String(100))
    name_column_index: Mapped[int | None] = mapped_column(SmallInteger)


class DiscountRule(Base):
    __tablename__ = "discount_rules"
    __table_args__ = (UniqueConstraint("company_id", "code"), {"schema": "comm"})

    rule_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    discount_type_code: Mapped[str] = mapped_column(String(10))  # PERCENT|AMOUNT|TIERED|BUNDLE
    scope_type_code: Mapped[str] = mapped_column(String(20))  # ITEM|CATEGORY|CUSTOMER_GROUP|ALL
    scope_ref_id: Mapped[int | None]
    discount_value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    priority: Mapped[int] = mapped_column(SmallInteger, default=100)
    is_stackable: Mapped[bool] = mapped_column(default=False)
    valid_from: Mapped[datetime.date] = mapped_column(Date)
    valid_to: Mapped[datetime.date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(default=True)


class DiscountRuleTier(Base):
    __tablename__ = "discount_rule_tiers"
    __table_args__ = ({"schema": "comm"},)

    tier_id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("comm.discount_rules.rule_id"))
    min_quantity: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    min_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    discount_value: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))


class Promotion(Base):
    __tablename__ = "promotions"
    __table_args__ = (UniqueConstraint("company_id", "code"), {"schema": "comm"})

    promotion_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    promotion_type_code: Mapped[str] = mapped_column(String(15))  # BUY_X_GET_Y|SEASONAL|BUNDLE
    channel_scope: Mapped[str | None] = mapped_column(String(20))
    valid_from: Mapped[datetime.date] = mapped_column(Date)
    valid_to: Mapped[datetime.date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(default=True)


class Coupon(Base):
    __tablename__ = "coupons"
    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        CheckConstraint("used_count <= max_uses", name="ck_comm_coupons_used"),
        {"schema": "comm"},
    )

    coupon_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    promotion_id: Mapped[int | None] = mapped_column(ForeignKey("comm.promotions.promotion_id"))
    discount_value: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    max_uses: Mapped[int] = mapped_column(default=1)
    used_count: Mapped[int] = mapped_column(default=0)
    customer_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    valid_from: Mapped[datetime.date] = mapped_column(Date)
    valid_to: Mapped[datetime.date | None] = mapped_column(Date)


class PricingPolicy(Base):
    __tablename__ = "pricing_policies"
    __table_args__ = (UniqueConstraint("company_id"), {"schema": "comm"})

    policy_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    min_margin_percent_default: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2))
    below_margin_requires_approval: Mapped[bool] = mapped_column(default=True)


class BundleDefinition(Base):
    __tablename__ = "bundle_definitions"
    __table_args__ = ({"schema": "comm"},)

    bundle_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    bundle_item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(default=True)


class BundleComponent(Base):
    __tablename__ = "bundle_components"
    __table_args__ = (UniqueConstraint("bundle_id", "component_item_id"), {"schema": "comm"})

    bundle_component_id: Mapped[int] = mapped_column(primary_key=True)
    bundle_id: Mapped[int] = mapped_column(ForeignKey("comm.bundle_definitions.bundle_id"))
    component_item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    quantity_per_bundle: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    price_allocation_percent: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2))


# =======================================================================
# جلسهٔ صندوق و وفاداری — معادلِ 066_commercial_pos_sessions.sql
# =======================================================================
class PosTerminal(Base):
    __tablename__ = "pos_terminals"
    __table_args__ = (UniqueConstraint("company_id", "code"), {"schema": "comm"})

    terminal_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(default=True)


class PosSession(Base):
    __tablename__ = "pos_sessions"
    __table_args__ = ({"schema": "comm"},)

    session_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    terminal_id: Mapped[int] = mapped_column(ForeignKey("comm.pos_terminals.terminal_id"))
    opened_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    opened_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    opening_cash_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    closed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    closed_at: Mapped[datetime.datetime | None]
    closing_cash_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    expected_cash_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    variance_amount: Mapped[decimal.Decimal | None] = mapped_column(
        Numeric(18, 2), Computed("closing_cash_amount - expected_cash_amount")
    )
    status_code: Mapped[str] = mapped_column(String(10), default="OPEN")
    variance_override_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    variance_override_reason: Mapped[str | None] = mapped_column(String(500))


class LoyaltyAccount(Base):
    __tablename__ = "loyalty_accounts"
    __table_args__ = ({"schema": "comm"},)

    loyalty_account_id: Mapped[int] = mapped_column(primary_key=True)
    customer_detail_account_id: Mapped[int] = mapped_column(
        ForeignKey("acc.detail_accounts.detail_account_id"), unique=True
    )
    points_balance: Mapped[int] = mapped_column(default=0)
    wallet_balance: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    tier_code: Mapped[str] = mapped_column(String(20), default="STANDARD")


class GiftCard(Base):
    __tablename__ = "gift_cards"
    __table_args__ = (
        UniqueConstraint("code"),
        CheckConstraint("current_balance BETWEEN 0 AND initial_balance", name="ck_comm_gift_cards_balance"),
        {"schema": "comm"},
    )

    card_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    initial_balance: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    current_balance: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    issued_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    expires_at: Mapped[datetime.datetime | None]
    status_code: Mapped[str] = mapped_column(String(10), default="ACTIVE")


class PosSettings(Base):
    __tablename__ = "pos_settings"
    __table_args__ = ({"schema": "comm"},)

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    default_guest_customer_detail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc.detail_accounts.detail_account_id")
    )
    cash_variance_threshold_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    # طبقِ بازخوردِ صریح («اندازه/جهتِ کلیدهایِ فوری قابلِ‌تنظیم باشد»):
    # اندازه‌یِ دکمه‌هایِ گریدِ دسترسیِ‌سریعِ کالا در صفحه‌یِ فروشِ حضوری.
    quick_button_width: Mapped[int] = mapped_column(default=110)
    quick_button_height: Mapped[int] = mapped_column(default=64)
    quick_button_font_size: Mapped[int] = mapped_column(default=10)
    quick_grid_columns: Mapped[int] = mapped_column(default=6)


class PosMenuGroup(Base):
    """گروه‌بندیِ کاملاً مستقلِ POS برایِ چیدمانِ تب‌هایِ دسترسیِ‌سریع --
    معادلِ 113_pos_menu_groups.sql. طبقِ درخواستِ صریح («دسته‌بندیِ
    مخصوصِ POS، جدا از دسته‌بندیِ عمومیِ انبار»)، این هیچ ربطی به
    inv.item_categories (سلسله‌مراتبِ کاردکس/گزارش) ندارد."""

    __tablename__ = "pos_menu_groups"
    __table_args__ = ({"schema": "comm"},)

    group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    name: Mapped[str] = mapped_column(String(100))
    display_order: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)


class PosCashierSettings(Base):
    """تنظیماتِ صندوق‌داریِ هر (کاربر، شرکت) -- معادلِ
    112_pos_cashier_settings.sql. ترمینال/فهرستِ‌قیمت/مشتری هرکدام به یک
    شرکتِ مشخص تعلق دارند، پس این تنظیمات هم به‌ازایِ شرکت جداست."""

    __tablename__ = "pos_cashier_settings"
    __table_args__ = ({"schema": "comm"},)

    user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"), primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    default_terminal_id: Mapped[int | None] = mapped_column(ForeignKey("comm.pos_terminals.terminal_id"))
    default_price_list_id: Mapped[int | None] = mapped_column(ForeignKey("comm.price_lists.price_list_id"))
    default_customer_detail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc.detail_accounts.detail_account_id")
    )


# =======================================================================
# اسکلتِ یکپارچهٔ سند — معادلِ 067_commercial_documents.sql
# =======================================================================
class CommercialDocument(Base):
    __tablename__ = "commercial_documents"
    __table_args__ = (
        UniqueConstraint("company_id", "fiscal_year_id", "document_type_code", "document_no"),
        ForeignKeyConstraint(["company_id", "channel_code"], ["comm.channels.company_id", "comm.channels.channel_code"]),
        {"schema": "comm"},
    )

    document_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    fiscal_year_id: Mapped[int] = mapped_column(ForeignKey("acc.fiscal_years.fiscal_year_id"))
    document_type_code: Mapped[str] = mapped_column(String(20))
    document_no: Mapped[int]
    document_date: Mapped[datetime.date] = mapped_column(Date)
    status_code: Mapped[str] = mapped_column(String(15), default="DRAFT")
    channel_code: Mapped[str | None] = mapped_column(String(20))
    counterparty_detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    # طبقِ درخواستِ صریح («فاکتورِ امانی، هردو جهت»): فقط برایِ
    # CONSIGNMENT_OUT پر می‌شود -- انبارِ مقصد/محلِ‌نگه‌داریِ کالایِ امانی
    # نزدِ طرفِ‌حساب (warehouse_id همان انبارِ مبدا/اصلیِ شرکت می‌ماند).
    consignment_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    price_list_id: Mapped[int | None] = mapped_column(ForeignKey("comm.price_lists.price_list_id"))
    source_document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("comm.commercial_documents.document_id"))
    linked_exchange_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("comm.commercial_documents.document_id")
    )
    pos_session_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("comm.pos_sessions.session_id"))
    # طبقِ رفعِ شکافِ کشف‌شده: کاریرِ POS فقط confirm می‌کند و نوعِ پرداختِ
    # موردنظرش (نقدی/نسیه) را یادداشت می‌کند؛ ثبتِ واقعیِ پرداخت/سندِ
    # حسابداری با تاییدِ سرپرست، جداگانه (در زمانِ approve/post) انجام می‌شود.
    pos_intended_payment_type: Mapped[str | None] = mapped_column(String(10))
    currency_id: Mapped[int] = mapped_column(ForeignKey("core.currencies.currency_id"))
    exchange_rate: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=1)
    requested_delivery_date: Mapped[datetime.date | None] = mapped_column(Date)
    # طبقِ درخواستِ صریح («موعدِ تسویه را بر اساسِ تعاریفِ طرفِ‌حساب نمایش
    # بدهد و بتوان ویرایشش کرد»): در لحظه‌یِ ساخت از رویِ payment_term_days
    # طرفِ‌حساب محاسبه می‌شود، ولی دستی هم قابلِ‌تغییر است.
    due_date: Mapped[datetime.date | None] = mapped_column(Date)
    sales_rep_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    cost_center_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    project_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    reference_no: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    # طبقِ درخواستِ صریح («دو نوعِ ثبت: رسمی/غیررسمی»): NULL یعنی از
    # پیش‌فرضِ سراسریِ شرکت (Feature Toggleِ INFORMAL_TAX_POSTING) پیروی
    # کن؛ OFFICIAL/INFORMAL یعنی override رویِ همین سند.
    tax_posting_mode: Mapped[str | None] = mapped_column(String(10))
    subtotal_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    discount_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    tax_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    shipping_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    total_amount: Mapped[decimal.Decimal] = mapped_column(
        Numeric(18, 2), Computed("subtotal_amount - discount_amount + tax_amount + shipping_amount")
    )
    stock_document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("inv.stock_documents.stock_document_id"))
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    # طبقِ درخواستِ صریح («مدیر بتواند فاکتورِ ثبت‌شده را اصلاح کند، بدونِ
    # backdate»): این فاکتور به‌جایِ ویرایشِ فاکتورِ قدیمی، رفرنسِ صریح به
    # آن دارد (corrects_document_id) و فاکتورِ قدیمی هم رفرنسِ برعکس به
    # این یکی دارد (corrected_by_document_id) -- هردو self-FK.
    corrects_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("comm.commercial_documents.document_id")
    )
    corrected_by_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("comm.commercial_documents.document_id")
    )
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    posted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    posted_at: Mapped[datetime.datetime | None]


class CommercialDocumentLine(Base):
    __tablename__ = "commercial_document_lines"
    __table_args__ = (UniqueConstraint("document_id", "line_no"), {"schema": "comm"})

    line_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("comm.commercial_documents.document_id"))
    line_no: Mapped[int] = mapped_column(SmallInteger)
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    uom_id: Mapped[int] = mapped_column(ForeignKey("inv.uom.uom_id"))
    quantity: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    quantity_base: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    unit_price: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    discount_percent: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), default=0)
    discount_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    tax_percent: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), default=0)
    tax_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    line_total: Mapped[decimal.Decimal] = mapped_column(
        Numeric(18, 2), Computed("round(quantity * unit_price - discount_amount + tax_amount, 2)")
    )
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("inv.batches.batch_id"))
    serial_id: Mapped[int | None] = mapped_column(ForeignKey("inv.serial_numbers.serial_id"))
    # طبقِ درخواستِ صریح («کالایِ ردیف بتواند انبارِ مستقل از هدر داشته
    # باشد») — Toggleِ اختیاریِ PER_LINE_WAREHOUSE. خالی یعنی از انبارِ
    # هدر استفاده شود (رفتارِ قدیم، بدونِ تغییر).
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    source_line_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("comm.commercial_document_lines.line_id"))
    stock_document_line_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("inv.stock_document_lines.line_id")
    )
    reservation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("inv.stock_reservations.reservation_id"))
    received_quantity_total: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=0)
    invoiced_quantity_total: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=0)
    # طبقِ درخواستِ صریح («فاکتورِ امانی، هردو جهت»): فقط برایِ ردیفِ
    # CONSIGNMENT_OUT/CONSIGNMENT_IN معنا دارد -- مقدارِ بازگردانده‌شده
    # (کالایِ فروخته‌نشده/مصرف‌نشده)، مکمّلِ source_line_id (که مقدارِ
    # تسویه‌شده را نشان می‌دهد) برایِ محاسبه‌یِ مانده‌یِ واقعی.
    returned_quantity: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=0)
    bundle_parent_line_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("comm.commercial_document_lines.line_id")
    )
    promotion_id: Mapped[int | None] = mapped_column(ForeignKey("comm.promotions.promotion_id"))
    coupon_id: Mapped[int | None] = mapped_column(ForeignKey("comm.coupons.coupon_id"))
    description: Mapped[str | None] = mapped_column(String(500))


# =======================================================================
# شرکا — معادلِ 068_commercial_partners.sql
# =======================================================================
class CommissionRule(Base):
    __tablename__ = "commission_rules"
    __table_args__ = (UniqueConstraint("company_id", "code"), {"schema": "comm"})

    rule_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    basis_code: Mapped[str] = mapped_column(String(20))  # PERCENT_OF_TOTAL|PERCENT_OF_MARGIN|FLAT_PER_UNIT|TIERED
    rate_value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    is_active: Mapped[bool] = mapped_column(default=True)


class CustomerGroup(Base):
    __tablename__ = "customer_groups"
    __table_args__ = (UniqueConstraint("company_id", "code"), {"schema": "comm"})

    group_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    default_discount_rule_id: Mapped[int | None] = mapped_column(ForeignKey("comm.discount_rules.rule_id"))


class SupplierGroup(Base):
    __tablename__ = "supplier_groups"
    __table_args__ = (UniqueConstraint("company_id", "code"), {"schema": "comm"})

    group_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    default_discount_rule_id: Mapped[int | None] = mapped_column(ForeignKey("comm.discount_rules.rule_id"))


class SalesRepresentative(Base):
    __tablename__ = "sales_representatives"
    __table_args__ = ({"schema": "comm"},)

    rep_detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"), primary_key=True)
    default_commission_rule_id: Mapped[int | None] = mapped_column(ForeignKey("comm.commission_rules.rule_id"))
    territory_name: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(default=True)


class CustomerProfile(Base):
    __tablename__ = "customer_profiles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "default_channel_code"], ["comm.channels.company_id", "comm.channels.channel_code"]
        ),
        {"schema": "comm"},
    )

    customer_detail_account_id: Mapped[int] = mapped_column(
        ForeignKey("acc.detail_accounts.detail_account_id"), primary_key=True
    )
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    customer_group_id: Mapped[int | None] = mapped_column(ForeignKey("comm.customer_groups.group_id"))
    default_price_list_id: Mapped[int | None] = mapped_column(ForeignKey("comm.price_lists.price_list_id"))
    payment_term_days: Mapped[int] = mapped_column(SmallInteger, default=0)
    credit_limit_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    default_channel_code: Mapped[str | None] = mapped_column(String(20))
    default_sales_rep_detail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("comm.sales_representatives.rep_detail_account_id")
    )
    status_code: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    onboarding_source_code: Mapped[str | None] = mapped_column(String(15))
    is_tax_exempt: Mapped[bool] = mapped_column(default=False)
    submitted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    submitted_at: Mapped[datetime.datetime | None]
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    approved_at: Mapped[datetime.datetime | None]
    hold_reason: Mapped[str | None] = mapped_column(String(500))
    held_at: Mapped[datetime.datetime | None]
    held_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))


class SupplierProfile(Base):
    __tablename__ = "supplier_profiles"
    __table_args__ = ({"schema": "comm"},)

    supplier_detail_account_id: Mapped[int] = mapped_column(
        ForeignKey("acc.detail_accounts.detail_account_id"), primary_key=True
    )
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    supplier_group_id: Mapped[int | None] = mapped_column(ForeignKey("comm.supplier_groups.group_id"))
    default_price_list_id: Mapped[int | None] = mapped_column(ForeignKey("comm.price_lists.price_list_id"))
    payment_term_days: Mapped[int] = mapped_column(SmallInteger, default=0)
    credit_limit_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    default_lead_time_days: Mapped[int | None] = mapped_column(SmallInteger)
    incoterm_code: Mapped[str | None] = mapped_column(String(10))
    preferred_currency_id: Mapped[int | None] = mapped_column(ForeignKey("core.currencies.currency_id"))
    quality_rating: Mapped[decimal.Decimal | None] = mapped_column(Numeric(3, 1))
    status_code: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    submitted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    submitted_at: Mapped[datetime.datetime | None]
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    approved_at: Mapped[datetime.datetime | None]
    hold_reason: Mapped[str | None] = mapped_column(String(500))
    held_at: Mapped[datetime.datetime | None]
    held_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))


class PartyAddress(Base):
    __tablename__ = "party_addresses"
    __table_args__ = ({"schema": "comm"},)

    address_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    party_detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    address_type_code: Mapped[str] = mapped_column(String(15))  # BILLING|SHIPPING|PICKUP
    line1: Mapped[str] = mapped_column(String(300))
    city: Mapped[str | None] = mapped_column(String(100))
    province: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    is_default: Mapped[bool] = mapped_column(default=False)


class PartyContact(Base):
    __tablename__ = "party_contacts"
    __table_args__ = ({"schema": "comm"},)

    contact_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    party_detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    full_name: Mapped[str] = mapped_column(String(150))
    role_title: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(200))
    is_primary: Mapped[bool] = mapped_column(default=False)


# =======================================================================
# قرارداد، کمیسیون، حمل، اشتراک — معادلِ
# 069_commercial_contracts_commission_shipping.sql
# =======================================================================
class CommercialContract(Base):
    __tablename__ = "commercial_contracts"
    __table_args__ = ({"schema": "comm"},)

    contract_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    contract_type_code: Mapped[str] = mapped_column(String(10))  # SALES | PURCHASE
    counterparty_detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("inv.items.item_id"))
    committed_quantity: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    consumed_quantity: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6), default=0)
    contract_price: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))
    valid_from: Mapped[datetime.date] = mapped_column(Date)
    valid_to: Mapped[datetime.date | None] = mapped_column(Date)
    status_code: Mapped[str] = mapped_column(String(15), default="ACTIVE")


class CommissionEntry(Base):
    __tablename__ = "commission_entries"
    __table_args__ = ({"schema": "comm"},)

    entry_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_line_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("comm.commercial_document_lines.line_id"))
    rep_detail_account_id: Mapped[int] = mapped_column(
        ForeignKey("comm.sales_representatives.rep_detail_account_id")
    )
    rule_id: Mapped[int] = mapped_column(ForeignKey("comm.commission_rules.rule_id"))
    base_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    commission_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    status_code: Mapped[str] = mapped_column(String(15), default="PENDING")
    payment_journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))


class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = ({"schema": "comm"},)

    shipment_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("comm.commercial_documents.document_id"))
    carrier_name: Mapped[str | None] = mapped_column(String(150))
    tracking_no: Mapped[str | None] = mapped_column(String(100))
    shipping_method_code: Mapped[str] = mapped_column(String(15))  # PICKUP|COURIER|POST|FREIGHT
    shipping_cost: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    billed_to_customer: Mapped[bool] = mapped_column(default=False)
    status_code: Mapped[str] = mapped_column(String(15), default="PENDING")
    shipped_at: Mapped[datetime.datetime | None]
    delivered_at: Mapped[datetime.datetime | None]


class RecurringBillingSchedule(Base):
    __tablename__ = "recurring_billing_schedules"
    __table_args__ = ({"schema": "comm"},)

    schedule_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("comm.commercial_contracts.contract_id"))
    customer_detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    interval_code: Mapped[str] = mapped_column(String(10))  # MONTHLY|QUARTERLY|ANNUAL
    next_run_date: Mapped[datetime.date] = mapped_column(Date)
    auto_post: Mapped[bool] = mapped_column(default=False)
    last_generated_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("comm.commercial_documents.document_id")
    )
    status_code: Mapped[str] = mapped_column(String(15), default="ACTIVE")


# =======================================================================
# اعتبار — معادلِ 070_commercial_credit.sql
# =======================================================================
class CreditPolicy(Base):
    __tablename__ = "credit_policies"
    __table_args__ = (UniqueConstraint("company_id", "party_type_code"), {"schema": "comm"})

    policy_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    party_type_code: Mapped[str] = mapped_column(String(10))  # CUSTOMER | SUPPLIER
    default_credit_limit: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    default_payment_term_days: Mapped[int] = mapped_column(SmallInteger, default=0)
    overdue_grace_days: Mapped[int] = mapped_column(SmallInteger, default=0)


class CreditHold(Base):
    __tablename__ = "credit_holds"
    __table_args__ = ({"schema": "comm"},)

    hold_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    party_detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    related_document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("comm.commercial_documents.document_id"))
    reason: Mapped[str] = mapped_column(String(500))
    held_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    held_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    released_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    released_at: Mapped[datetime.datetime | None]


# =======================================================================
# پرداختِ چندروشی، وفاداری، اقساط — معادلِ
# 071_commercial_pos_transactions.sql
# =======================================================================
class PosPayment(Base):
    __tablename__ = "pos_payments"
    __table_args__ = ({"schema": "comm"},)

    payment_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("comm.commercial_documents.document_id"))
    method_code: Mapped[str] = mapped_column(String(15))  # CASH|CARD|WALLET|GIFT_CARD|STORE_CREDIT
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    reference_no: Mapped[str | None] = mapped_column(String(100))


class LoyaltyTransaction(Base):
    __tablename__ = "loyalty_transactions"
    __table_args__ = ({"schema": "comm"},)

    transaction_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    loyalty_account_id: Mapped[int] = mapped_column(ForeignKey("comm.loyalty_accounts.loyalty_account_id"))
    document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("comm.commercial_documents.document_id"))
    points_delta: Mapped[int] = mapped_column(default=0)
    wallet_delta: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    transaction_type_code: Mapped[str] = mapped_column(String(10))  # EARN | REDEEM | ADJUST
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class InstallmentPlan(Base):
    __tablename__ = "installment_plans"
    __table_args__ = ({"schema": "comm"},)

    plan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # طبقِ موردِ ۵ («روشِ اقساط منوط به فاکتور نباشد»): document_id دیگر
    # الزامی نیست -- NULL یعنی طرحِ اقساطِ آزاد، که در آن صورت سه فیلدِ
    # زیر (company_id/counterparty_detail_account_id/direction) جایگزینِ
    # همان اطلاعاتی می‌شوند که پیش‌تر از رویِ سند استنتاج می‌شد.
    document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("comm.commercial_documents.document_id"))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("core.companies.company_id"))
    counterparty_detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    direction: Mapped[str | None] = mapped_column(String(10))  # RECEIPT | PAYMENT -- فقط برایِ طرحِ بدونِ فاکتور
    number_of_installments: Mapped[int] = mapped_column(SmallInteger)
    first_due_date: Mapped[datetime.date] = mapped_column(Date)
    status_code: Mapped[str] = mapped_column(String(15), default="ACTIVE")
    # طبقِ موردِ ۶ («درصدِ بهرهٔ اقساط و هزینه‌هایِ متفرقه»): اصلِ مبلغ
    # (بدونِ بهره/هزینه) + پارامترهایِ محاسبه‌یِ مبلغِ نهایی + فاصله‌یِ
    # سررسیدِ قابلِ‌تنظیم (پیش‌فرض ۳۰ روز، رفتارِ قبلی).
    principal_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    interest_rate_percent: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 3), default=decimal.Decimal("0"))
    misc_fee_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal("0"))
    due_interval_days: Mapped[int] = mapped_column(SmallInteger, default=30)


class InstallmentLine(Base):
    __tablename__ = "installment_lines"
    __table_args__ = (UniqueConstraint("plan_id", "installment_no"), {"schema": "comm"})

    line_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("comm.installment_plans.plan_id"))
    installment_no: Mapped[int] = mapped_column(SmallInteger)
    due_date: Mapped[datetime.date] = mapped_column(Date)
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    # طبقِ موردِ ۶: سهمِ این قسط از بهره/هزینه‌یِ متفرقه (زیرمجموعه‌یِ
    # amount، نه جدا از آن) -- برایِ تفکیکِ اصل/بهره در گزارش‌گیری.
    interest_fee_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=decimal.Decimal("0"))
    status_code: Mapped[str] = mapped_column(String(15), default="PENDING")
    paid_journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))


class InstallmentCollection(Base):
    """طبقِ درخواستِ صریح («ممکنه بخشی از اقساط وصول بشه»): هر رویدادِ
    وصول (کامل یا جزئی) رویِ یک قسط، جداگانه این‌جا ثبت می‌شود -- مجموعِ
    amount این ردیف‌ها برایِ یک line_id همان مبلغِ وصول‌شده‌یِ آن قسط
    است. هم‌الگو با InvoiceSettlement برایِ فاکتورها."""

    __tablename__ = "installment_collections"
    __table_args__ = ({"schema": "comm"},)

    collection_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    line_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("comm.installment_lines.line_id"))
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    collection_date: Mapped[datetime.date] = mapped_column(Date)
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    description: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


# =======================================================================
# اتصال‌گرِ انتزاعی و DOM — معادلِ 072_commercial_ecommerce.sql
# =======================================================================
class MarketplaceConnection(Base):
    __tablename__ = "marketplace_connections"
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "channel_code"], ["comm.channels.company_id", "comm.channels.channel_code"]),
        {"schema": "comm"},
    )

    connection_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    platform_code: Mapped[str] = mapped_column(String(20))  # WOOCOMMERCE|PRESTASHOP|OTHER
    store_url: Mapped[str] = mapped_column(String(300))
    credentials_encrypted: Mapped[bytes | None]
    channel_code: Mapped[str] = mapped_column(String(20))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    sync_status: Mapped[str] = mapped_column(String(15), default="ACTIVE")
    last_synced_at: Mapped[datetime.datetime | None]


class MarketplaceOrderSyncLog(Base):
    __tablename__ = "marketplace_order_sync_log"
    __table_args__ = (UniqueConstraint("connection_id", "external_order_id"), {"schema": "comm"})

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("comm.marketplace_connections.connection_id"))
    external_order_id: Mapped[str] = mapped_column(String(100))
    document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("comm.commercial_documents.document_id"))
    sync_status: Mapped[str] = mapped_column(String(15))  # IMPORTED|FAILED|DUPLICATE
    error_message: Mapped[str | None] = mapped_column(String(500))
    synced_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class MarketplaceItemMapping(Base):
    __tablename__ = "marketplace_item_mappings"
    __table_args__ = (UniqueConstraint("connection_id", "external_sku"), {"schema": "comm"})

    mapping_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("comm.marketplace_connections.connection_id"))
    external_sku: Mapped[str] = mapped_column(String(100))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    external_price: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 6))


class MarketplaceCustomerMapping(Base):
    __tablename__ = "marketplace_customer_mappings"
    __table_args__ = (UniqueConstraint("connection_id", "external_customer_id"), {"schema": "comm"})

    mapping_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("comm.marketplace_connections.connection_id"))
    external_customer_id: Mapped[str] = mapped_column(String(100))
    customer_detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))


class MarketplaceInventoryPushLog(Base):
    __tablename__ = "marketplace_inventory_push_log"
    __table_args__ = ({"schema": "comm"},)

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("comm.marketplace_connections.connection_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    pushed_atp_quantity: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    pushed_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    push_status: Mapped[str] = mapped_column(String(15), default="OK")


class FulfillmentRoutingRule(Base):
    __tablename__ = "fulfillment_routing_rules"
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "channel_code"], ["comm.channels.company_id", "comm.channels.channel_code"]),
        {"schema": "comm"},
    )

    rule_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    channel_code: Mapped[str | None] = mapped_column(String(20))
    strategy_code: Mapped[str] = mapped_column(String(20))  # MOST_STOCK|REGION_MATCH|LOWEST_COST|FIXED_WAREHOUSE
    fallback_warehouse_id: Mapped[int] = mapped_column(ForeignKey("inv.warehouses.warehouse_id"))
    priority: Mapped[int] = mapped_column(SmallInteger, default=100)


# =======================================================================
# گارانتی، تیکت، RMA — معادلِ 073_commercial_aftersales.sql
# =======================================================================
class Warranty(Base):
    __tablename__ = "warranties"
    __table_args__ = (
        CheckConstraint("end_date > start_date", name="ck_comm_warranties_dates"),
        {"schema": "comm"},
    )

    warranty_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sales_document_line_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("comm.commercial_document_lines.line_id"))
    serial_id: Mapped[int | None] = mapped_column(ForeignKey("inv.serial_numbers.serial_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    start_date: Mapped[datetime.date] = mapped_column(Date)
    end_date: Mapped[datetime.date] = mapped_column(Date)
    terms: Mapped[str | None] = mapped_column(String(500))
    status_code: Mapped[str] = mapped_column(String(15), default="ACTIVE")
    voided_reason: Mapped[str | None] = mapped_column(String(500))


class ServiceTicket(Base):
    __tablename__ = "service_tickets"
    __table_args__ = ({"schema": "comm"},)

    ticket_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    customer_detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    warranty_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("comm.warranties.warranty_id"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("inv.items.item_id"))
    subject: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status_code: Mapped[str] = mapped_column(String(15), default="OPEN")
    is_billable: Mapped[bool] = mapped_column(default=False)
    resulting_invoice_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("comm.commercial_documents.document_id")
    )
    assigned_to_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    opened_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    closed_at: Mapped[datetime.datetime | None]


class RmaRequest(Base):
    __tablename__ = "rma_requests"
    __table_args__ = ({"schema": "comm"},)

    rma_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    customer_detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    original_document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("comm.commercial_documents.document_id"))
    related_ticket_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("comm.service_tickets.ticket_id"))
    reason_code: Mapped[str] = mapped_column(String(20))  # DEFECTIVE|WRONG_ITEM|NOT_SATISFIED|DAMAGED_IN_TRANSIT
    requested_quantity: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    status_code: Mapped[str] = mapped_column(String(15), default="REQUESTED")
    resulting_return_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("comm.commercial_documents.document_id")
    )


class ServiceTicketPartUsed(Base):
    __tablename__ = "service_ticket_parts_used"
    __table_args__ = ({"schema": "comm"},)

    usage_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("comm.service_tickets.ticket_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inv.items.item_id"))
    quantity: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    stock_document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("inv.stock_documents.stock_document_id"))


# =======================================================================
# بهایِ تمام‌شدهٔ وارداتی و ریبیت — معادلِ
# 074_commercial_purchase_extras.sql
# =======================================================================
class LandedCostAllocation(Base):
    __tablename__ = "landed_cost_allocations"
    __table_args__ = ({"schema": "comm"},)

    allocation_id: Mapped[int] = mapped_column(primary_key=True)
    purchase_invoice_document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("comm.commercial_documents.document_id")
    )
    cost_type_code: Mapped[str | None] = mapped_column(String(15))  # FREIGHT|CUSTOMS|INSURANCE|HANDLING|OTHER
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    allocation_method_code: Mapped[str | None] = mapped_column(String(15))  # BY_VALUE|BY_QUANTITY|BY_WEIGHT
    notes: Mapped[str | None] = mapped_column(String(500))
    # طبقِ درخواستِ صریح («فرمِ تسهیمِ هزینه، حسابِ معین و تفصیلیِ
    # بستانکار را بتوانیم وارد کنیم»): حسابِ آزادانه‌ای که با ثبتِ نهاییِ
    # فاکتورِ خرید بستانکار می‌شود (مثلاً یک تفصیلیِ گروهِ «سفارشاتِ در
    # راه») -- نه یک نقشِ ثابت.
    credit_account_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("acc.chart_of_accounts.account_id"))
    credit_detail_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("acc.detail_accounts.detail_account_id")
    )


class VendorRebateAgreement(Base):
    __tablename__ = "vendor_rebate_agreements"
    __table_args__ = ({"schema": "comm"},)

    agreement_id: Mapped[int] = mapped_column(primary_key=True)
    supplier_detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("inv.items.item_id"))
    rebate_basis_code: Mapped[str] = mapped_column(String(15))  # FLAT_PERCENT | VOLUME_TIER
    valid_from: Mapped[datetime.date] = mapped_column(Date)
    valid_to: Mapped[datetime.date | None] = mapped_column(Date)
    status_code: Mapped[str] = mapped_column(String(15), default="ACTIVE")


class VendorRebateTier(Base):
    __tablename__ = "vendor_rebate_tiers"
    __table_args__ = ({"schema": "comm"},)

    tier_id: Mapped[int] = mapped_column(primary_key=True)
    agreement_id: Mapped[int] = mapped_column(ForeignKey("comm.vendor_rebate_agreements.agreement_id"))
    min_purchase_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    rebate_percent: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2))


class VendorRebateAccrual(Base):
    __tablename__ = "vendor_rebate_accruals"
    __table_args__ = (
        CheckConstraint("period_to > period_from", name="ck_comm_vendor_rebate_accruals_period"),
        {"schema": "comm"},
    )

    accrual_id: Mapped[int] = mapped_column(primary_key=True)
    agreement_id: Mapped[int] = mapped_column(ForeignKey("comm.vendor_rebate_agreements.agreement_id"))
    period_from: Mapped[datetime.date] = mapped_column(Date)
    period_to: Mapped[datetime.date] = mapped_column(Date)
    accrued_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    status_code: Mapped[str] = mapped_column(String(15), default="ACCRUING")
    settlement_journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))


# =======================================================================
# اسنپ‌شاتِ داشبوردِ اجرایی — معادلِ 075_commercial_dashboard.sql
# =======================================================================
class DailyKpiSnapshot(Base):
    __tablename__ = "daily_kpi_snapshots"
    __table_args__ = (UniqueConstraint("company_id", "snapshot_date"), {"schema": "comm"})

    snapshot_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    snapshot_date: Mapped[datetime.date] = mapped_column(Date)
    total_sales_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    total_purchase_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    total_orders_count: Mapped[int] = mapped_column(default=0)
    open_credit_holds_count: Mapped[int] = mapped_column(default=0)
    pos_cash_variance_total: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    gift_card_liability_outstanding: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    loyalty_wallet_liability_outstanding: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)
    open_service_tickets_count: Mapped[int] = mapped_column(default=0)
    overdue_installment_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), default=0)


# =======================================================================
# نگاشتِ حساب، Feature Toggle، شماره‌گذاری — معادلِ
# 076_commercial_settings.sql
# =======================================================================
class CommercialAccountMapping(Base):
    __tablename__ = "account_mappings"
    __table_args__ = ({"schema": "comm"},)

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    mapping_key: Mapped[str] = mapped_column(String(30), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("acc.chart_of_accounts.account_id"))
    # طبقِ درخواستِ صریح («برایِ فاکتورِ فروش هم تفصیلیِ ثابت برایِ
    # مالیات، مثلِ فاکتورِ خرید»): تفصیلیِ ثابتِ ازپیش‌تخصیص‌یافته برایِ
    # این حسابِ نقش‌محور -- دقیقاً هم‌الگو با
    # inv.account_mappings.detail_account_id.
    detail_account_id: Mapped[int | None] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"))


class CommercialFeatureDefinition(Base):
    __tablename__ = "feature_definitions"
    __table_args__ = ({"schema": "comm"},)

    feature_code: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    module_scope: Mapped[str] = mapped_column(String(30))
    requires_feature_code: Mapped[str | None] = mapped_column(ForeignKey("comm.feature_definitions.feature_code"))
    requires_account_mapping_keys: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)


class CommercialCompanyFeature(Base):
    __tablename__ = "company_features"
    __table_args__ = ({"schema": "comm"},)

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    feature_code: Mapped[str] = mapped_column(ForeignKey("comm.feature_definitions.feature_code"), primary_key=True)
    is_enabled: Mapped[bool] = mapped_column(default=False)


class IndustryProfile(Base):
    __tablename__ = "industry_profiles"
    __table_args__ = ({"schema": "comm"},)

    profile_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class IndustryProfileFeatureDefault(Base):
    __tablename__ = "industry_profile_feature_defaults"
    __table_args__ = ({"schema": "comm"},)

    profile_code: Mapped[str] = mapped_column(ForeignKey("comm.industry_profiles.profile_code"), primary_key=True)
    feature_code: Mapped[str] = mapped_column(ForeignKey("comm.feature_definitions.feature_code"), primary_key=True)
    default_enabled: Mapped[bool] = mapped_column(default=False)


class DocumentNumberingSequence(Base):
    __tablename__ = "document_numbering_sequences"
    __table_args__ = ({"schema": "comm"},)

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    document_type_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    prefix: Mapped[str] = mapped_column(String(10), default="")
    next_number: Mapped[int] = mapped_column(BigInteger, default=1)
    reset_policy_code: Mapped[str] = mapped_column(String(10), default="YEARLY")


# =======================================================================
# تسویه‌یِ فاکتور — معادلِ 094_invoice_settlements.sql /
# 095_settlement_alarm_settings.sql
# =======================================================================
class InvoiceSettlement(Base):
    __tablename__ = "invoice_settlements"
    __table_args__ = ({"schema": "comm"},)

    settlement_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    invoice_document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("comm.commercial_documents.document_id"))
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc.journal_entries.journal_entry_id"))
    settlement_date: Mapped[datetime.date] = mapped_column(Date)
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2))
    reference_no: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")


class SettlementAlarmSettings(Base):
    __tablename__ = "settlement_alarm_settings"
    __table_args__ = ({"schema": "comm"},)

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    is_enabled: Mapped[bool] = mapped_column(default=False)
    alarm_days_before: Mapped[int] = mapped_column(SmallInteger, default=2)


# =======================================================================
# مدیریتِ سفارشات — معادلِ 103_order_management.sql
# =======================================================================
class OrderTrackingSetting(Base):
    """تنظیمِ یک‌بارهٔ هر شرکت: کدام گروهِ تفصیلی «سفارشاتِ در راه» است."""

    __tablename__ = "order_tracking_settings"
    __table_args__ = ({"schema": "comm"},)

    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    dimension_type_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_dimension_types.dimension_type_id"))
    # طبقِ درخواستِ صریح («امکانِ دیدنِ عکس برایِ همه‌یِ کاربرانِ شبکه»):
    # اگر تنظیم شود، ضمیمه‌ها این‌جا (مثلاً یک مسیرِ شبکه‌ایِ اشتراکی)
    # ذخیره می‌شوند، نه در پوشهٔ محلیِ تنظیماتِ همان کامپیوتر.
    attachments_dir: Mapped[str | None] = mapped_column(String(500))


class OrderTracking(Base):
    """یک سفارش -- دقیقاً یک تفصیلیِ همان گروهِ تعیین‌شده در
    OrderTrackingSetting را دنبال می‌کند. پرداخت‌هایِ خودِ سفارش این‌جا
    ذخیره نمی‌شوند -- با پرس‌وجویِ acc.journal_entry_line_details بر
    اساسِ همین detail_account_id به‌دست می‌آیند (طبقِ اصلِ «هرچه از
    داده‌هایِ حسابداریِ موجود مشتق می‌شود، دوباره ذخیره نشود»)."""

    __tablename__ = "order_trackings"
    __table_args__ = ({"schema": "comm"},)

    order_tracking_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    detail_account_id: Mapped[int] = mapped_column(ForeignKey("acc.detail_accounts.detail_account_id"), unique=True)
    description: Mapped[str | None] = mapped_column(String(500))
    status_code: Mapped[str] = mapped_column(String(15), default="OPEN")  # OPEN | CLOSED
    opened_by_user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"))
    opened_at: Mapped[datetime.datetime] = mapped_column(server_default="now()")
    closed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sec.users.user_id"))
    closed_at: Mapped[datetime.datetime | None]


class OrderPaymentTitle(Base):
    """طبقِ درخواستِ صریح («عنوانِ پرداخت» در فرمِ افزودنِ پرداختِ سفارش):
    فهرستِ قابلِ‌گسترشِ عنوان‌هایی مثلِ «هزینه‌یِ ترخیص»/«بهایِ اولیه‌یِ
    کالا» که کاربر با دکمه‌یِ + همان‌جا اضافه می‌کند -- معادلِ
    104_order_payment_titles.sql."""

    __tablename__ = "order_payment_titles"
    __table_args__ = (UniqueConstraint("company_id", "label"), {"schema": "comm"})

    payment_title_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    label: Mapped[str] = mapped_column(String(200))
