"""شرکایِ تجاری (مرحلهٔ ۳): customer_profiles/supplier_profiles جدولِ
اقماریِ یک‌به‌یکِ تفصیلیِ گروهِ CUSTOMER/SUPPLIER هستند — هویت و مانده
هرگز این‌جا بازتعریف نمی‌شوند، فقط لایهٔ تجاری (فهرستِ قیمت، مهلت، سقفِ
اعتبار، گردشِ کارِ تایید) اضافه می‌شود."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.commercial import (
    CommercialContract,
    CommercialDocument,
    CommissionRule,
    CustomerGroup,
    CustomerProfile,
    PartyAddress,
    PartyContact,
    SalesRepresentative,
    SupplierGroup,
    SupplierProfile,
)
from peecha.services import detail_dimensions as dimensions_service

_CUSTOMER_STATUSES = ("DRAFT", "PENDING_APPROVAL", "ACTIVE", "SUSPENDED", "BLACKLISTED", "INACTIVE")
_SUPPLIER_STATUSES = ("DRAFT", "PENDING_APPROVAL", "ACTIVE", "ON_HOLD", "DISQUALIFIED", "INACTIVE")


# ---------------------------------------------------------------------
# گروه‌بندی و نمایندگانِ فروش
# ---------------------------------------------------------------------
def list_customer_groups(company_id: int) -> list[CustomerGroup]:
    with new_session() as session:
        return list(session.scalars(select(CustomerGroup).where(CustomerGroup.company_id == company_id)))


def create_customer_group(company_id: int, code: str, name: str, default_discount_rule_id: int | None = None) -> int:
    with new_session() as session:
        row = CustomerGroup(company_id=company_id, code=code, name=name, default_discount_rule_id=default_discount_rule_id)
        session.add(row)
        session.commit()
        return row.group_id


def list_supplier_groups(company_id: int) -> list[SupplierGroup]:
    with new_session() as session:
        return list(session.scalars(select(SupplierGroup).where(SupplierGroup.company_id == company_id)))


def create_supplier_group(company_id: int, code: str, name: str, default_discount_rule_id: int | None = None) -> int:
    with new_session() as session:
        row = SupplierGroup(company_id=company_id, code=code, name=name, default_discount_rule_id=default_discount_rule_id)
        session.add(row)
        session.commit()
        return row.group_id


def list_sales_representatives(company_id: int) -> list[SalesRepresentative]:
    with new_session() as session:
        from peecha.db.models.accounting import DetailAccount

        return list(
            session.scalars(
                select(SalesRepresentative)
                .join(DetailAccount, DetailAccount.detail_account_id == SalesRepresentative.rep_detail_account_id)
                .where(DetailAccount.company_id == company_id)
            )
        )


def create_sales_representative(
    rep_detail_account_id: int, default_commission_rule_id: int | None = None, territory_name: str | None = None
) -> None:
    with new_session() as session:
        session.add(
            SalesRepresentative(
                rep_detail_account_id=rep_detail_account_id, default_commission_rule_id=default_commission_rule_id,
                territory_name=territory_name,
            )
        )
        session.commit()


# ---------------------------------------------------------------------
# مشتری
# ---------------------------------------------------------------------
@dataclass
class CustomerProfileFields:
    customer_group_id: int | None = None
    default_price_list_id: int | None = None
    payment_term_days: int = 0
    credit_limit_amount: "decimal.Decimal | float" = 0
    default_channel_code: str | None = None
    default_sales_rep_detail_account_id: int | None = None
    onboarding_source_code: str | None = None
    is_tax_exempt: bool = False
    distribution_route_detail_account_id: int | None = None
    gps_latitude: "decimal.Decimal | None" = None
    gps_longitude: "decimal.Decimal | None" = None


def create_customer(
    company_id: int, code: str, name: str, fields: CustomerProfileFields | None = None,
    fast_track: bool = False, submitted_by_user_id: int | None = None, **extra_fields,
) -> int:
    """fast_track=True (مرحلهٔ ۳، پیشنهادِ معمار): مشتریِ کم‌ریسک بدونِ
    گذر از PENDING_APPROVAL مستقیم ACTIVE می‌شود.

    extra_fields (R134، برایِ APIِ موبایل): فیلدهایِ خودِ customer_details
    (مثلِ phone/address) -- مستقیم به dimensions_service.create_customer
    منتقل می‌شود، اختیاری و عطف‌به‌ماسبق‌سازگار (فراخوانی‌هایِ قبلی بدونِ
    این فیلدها دست‌نخورده می‌مانند)."""
    fields = fields or CustomerProfileFields()
    detail_account_id = dimensions_service.create_customer(company_id, code, name, **extra_fields)
    with new_session() as session:
        status = "ACTIVE" if fast_track else "PENDING_APPROVAL"
        session.add(
            CustomerProfile(
                customer_detail_account_id=detail_account_id, company_id=company_id,
                customer_group_id=fields.customer_group_id, default_price_list_id=fields.default_price_list_id,
                payment_term_days=fields.payment_term_days, credit_limit_amount=fields.credit_limit_amount,
                default_channel_code=fields.default_channel_code,
                default_sales_rep_detail_account_id=fields.default_sales_rep_detail_account_id,
                status_code=status, onboarding_source_code=fields.onboarding_source_code,
                is_tax_exempt=fields.is_tax_exempt,
                distribution_route_detail_account_id=fields.distribution_route_detail_account_id,
                gps_latitude=fields.gps_latitude, gps_longitude=fields.gps_longitude,
                submitted_by_user_id=submitted_by_user_id, submitted_at=datetime.datetime.now(),
            )
        )
        session.commit()
    return detail_account_id


def get_customer_profile(customer_detail_account_id: int) -> CustomerProfile | None:
    with new_session() as session:
        return session.get(CustomerProfile, customer_detail_account_id)


def list_customer_profiles(company_id: int, status_code: str | None = None) -> list[CustomerProfile]:
    with new_session() as session:
        stmt = select(CustomerProfile).where(CustomerProfile.company_id == company_id)
        if status_code:
            stmt = stmt.where(CustomerProfile.status_code == status_code)
        return list(session.scalars(stmt))


def approve_customer(customer_detail_account_id: int, approved_by_user_id: int) -> None:
    with new_session() as session:
        profile = session.get(CustomerProfile, customer_detail_account_id)
        if profile is None:
            raise ValueError("مشتری نامعتبر است.")
        if profile.status_code != "PENDING_APPROVAL":
            raise ValueError("فقط مشتریِ درانتظارِ تایید قابلِ‌تاییدِ اعتباری است.")
        profile.status_code = "ACTIVE"
        profile.approved_by_user_id = approved_by_user_id
        profile.approved_at = datetime.datetime.now()
        session.commit()


def reject_customer(customer_detail_account_id: int, rejected_by_user_id: int, reason: str) -> None:
    """طبقِ درخواستِ صریحِ کاربر («Manager بتواند Approve/Reject کند»):
    مشتریِ درانتظارِ تایید را غیرِفعال می‌کند -- comm.customer_profiles.
    status_code هیچ مقدارِ «REJECTED»یِ جداگانه ندارد (بدونِ migrationِ
    غیرضروری)، پس هم‌الگو با set_customer_hold از همان دو ستونِ عمومیِ
    hold_reason/held_at/held_by_user_id استفاده می‌کند."""
    with new_session() as session:
        profile = session.get(CustomerProfile, customer_detail_account_id)
        if profile is None:
            raise ValueError("مشتری نامعتبر است.")
        if profile.status_code != "PENDING_APPROVAL":
            raise ValueError("فقط مشتریِ درانتظارِ تایید قابلِ‌رد است.")
        profile.status_code = "INACTIVE"
        profile.hold_reason = reason
        profile.held_at = datetime.datetime.now()
        profile.held_by_user_id = rejected_by_user_id
        session.commit()


def set_customer_hold(
    customer_detail_account_id: int, status_code: str, reason: str, held_by_user_id: int
) -> None:
    if status_code not in ("SUSPENDED", "BLACKLISTED"):
        raise ValueError("وضعیتِ توقف نامعتبر است.")
    with new_session() as session:
        profile = session.get(CustomerProfile, customer_detail_account_id)
        if profile is None:
            raise ValueError("مشتری نامعتبر است.")
        profile.status_code = status_code
        profile.hold_reason = reason
        profile.held_at = datetime.datetime.now()
        profile.held_by_user_id = held_by_user_id
        session.commit()


def set_customer_status(customer_detail_account_id: int, status_code: str) -> None:
    if status_code not in _CUSTOMER_STATUSES:
        raise ValueError("وضعیتِ نامعتبر است.")
    with new_session() as session:
        profile = session.get(CustomerProfile, customer_detail_account_id)
        if profile is None:
            raise ValueError("مشتری نامعتبر است.")
        profile.status_code = status_code
        session.commit()


def count_new_customers(company_id: int, date_from: datetime.date, date_to: datetime.date) -> int:
    """طبقِ داشبوردِ مدیریتی (Phase 7): «مشتریِ جدید» یعنی ثبت‌شده
    (submitted_at، همان کدی که با ثبتِ مشتری از موبایل/دسکتاپ پر
    می‌شود) در بازهٔ درخواستی -- صرفِ نظر از این‌که هنوز تاییدشده باشد
    یا نه."""
    with new_session() as session:
        return session.scalar(
            select(func.count()).where(
                CustomerProfile.company_id == company_id,
                func.date(CustomerProfile.submitted_at) >= date_from,
                func.date(CustomerProfile.submitted_at) <= date_to,
            )
        ) or 0


def count_customers_without_purchase(company_id: int) -> int:
    """طبقِ داشبوردِ مدیریتی: مشتریانِ فعالی که هرگز فاکتورِ POSTED
    نداشته‌اند -- سرنخِ فروشِ ازدست‌رفته."""
    with new_session() as session:
        has_invoice_subquery = (
            select(CommercialDocument.document_id)
            .where(
                CommercialDocument.counterparty_detail_account_id == CustomerProfile.customer_detail_account_id,
                CommercialDocument.document_type_code == "SALES_INVOICE",
                CommercialDocument.status_code == "POSTED",
            )
            .exists()
        )
        return session.scalar(
            select(func.count()).where(
                CustomerProfile.company_id == company_id,
                CustomerProfile.status_code == "ACTIVE",
                ~has_invoice_subquery,
            )
        ) or 0


def set_customer_credit_limit(customer_detail_account_id: int, credit_limit_amount) -> None:
    """طبقِ درخواستِ صریح («دستیارِ فروش» -- پیشنهادِ افزایشِ سقفِ اعتبار
    برایِ مشتریِ روبه‌رشد): تغییرِ سریعِ یک فیلد، بدونِ نیاز به فرمِ کاملِ
    update_customer_detail_account."""
    if credit_limit_amount is None or credit_limit_amount < 0:
        raise ValueError("سقفِ اعتبار نامعتبر است.")
    with new_session() as session:
        profile = session.get(CustomerProfile, customer_detail_account_id)
        if profile is None:
            raise ValueError("مشتری نامعتبر است.")
        profile.credit_limit_amount = credit_limit_amount
        session.commit()


# ---------------------------------------------------------------------
# یکپارچه‌سازی با فرمِ واحدِ تفصیلی (مشتری) — همان الگویِ
# hr_service.*_personnel_detail_account: فیلدهایِ CustomerDetailِ قدیمی
# (اقتصادی/ملی/تماس) و فیلدهایِ CustomerProfileِ بازرگانی، هردو از یک
# فرمِ واحد ذخیره می‌شوند.
# ---------------------------------------------------------------------
_CUSTOMER_DETAIL_FIELD_KEYS = (
    "economic_code", "national_id", "phone", "mobile", "address", "notes",
    "customer_type_code", "person_type_code", "customer_class", "geographic_region",
)
_CUSTOMER_PROFILE_FIELD_KEYS = (
    "customer_group_id", "default_price_list_id", "default_channel_code", "payment_term_days",
    "credit_limit_amount", "is_tax_exempt", "distribution_route_detail_account_id",
    "gps_latitude", "gps_longitude",
)


def _split_customer_fields(person_fields: dict) -> tuple[dict, dict]:
    detail_fields = {k: person_fields.get(k) for k in _CUSTOMER_DETAIL_FIELD_KEYS}
    profile_fields = {k: person_fields.get(k) for k in _CUSTOMER_PROFILE_FIELD_KEYS}
    profile_fields["payment_term_days"] = int(profile_fields["payment_term_days"] or 0)
    profile_fields["credit_limit_amount"] = profile_fields["credit_limit_amount"] or 0
    profile_fields["is_tax_exempt"] = bool(profile_fields["is_tax_exempt"])
    return detail_fields, profile_fields


def find_duplicate_customers(
    company_id: int, name: str | None = None, mobile: str | None = None, phone: str | None = None, limit: int = 5,
) -> list[dict]:
    """طبقِ بازبینیِ ساختارِ «تعریفِ مشتری» (R216، بخشِ ۱۶ -- تشخیصِ مشتریِ
    تکراری): برایِ فرمِ ثبتِ سریعِ موبایل، پیش از ارسالِ واقعی -- موبایل/
    تلفنِ یکسان (بعدِ نرمال‌سازیِ ارقامِ فارسی) یا نامِ مشابه (زیررشته‌ای،
    غیرِحساس‌به‌بزرگی/کوچکی). ردِ ثبت نمی‌کند، فقط برایِ هشدار به کاربر
    برمی‌گردد -- تصمیمِ نهایی (ادامه یا مشاهده‌یِ مشتریِ موجود) با خودِ کاربر است."""
    from peecha import numerals

    name_norm = (name or "").strip().lower()
    mobile_norm = numerals.to_ascii_digits((mobile or "").strip())
    phone_norm = numerals.to_ascii_digits((phone or "").strip())
    if not name_norm and not mobile_norm and not phone_norm:
        return []
    matches = []
    for row in dimensions_service.list_customers(company_id):
        reasons = []
        row_mobile = numerals.to_ascii_digits((row.get("mobile") or "").strip())
        row_phone = numerals.to_ascii_digits((row.get("phone") or "").strip())
        row_name = (row.get("name") or "").strip().lower()
        if mobile_norm and row_mobile and row_mobile == mobile_norm:
            reasons.append("موبایلِ یکسان")
        if phone_norm and row_phone and row_phone == phone_norm:
            reasons.append("تلفنِ یکسان")
        if name_norm and row_name and (row_name == name_norm or name_norm in row_name or row_name in name_norm):
            reasons.append("نامِ مشابه")
        if reasons:
            matches.append({**row, "match_reasons": reasons})
    matches.sort(key=lambda r: len(r["match_reasons"]), reverse=True)
    return matches[:limit]


def list_customer_detail_accounts(company_id: int) -> list[dict]:
    profiles = {p.customer_detail_account_id: p for p in list_customer_profiles(company_id)}
    blank = {key: None for key in _CUSTOMER_PROFILE_FIELD_KEYS} | {"status_code": None}
    result = []
    for row in dimensions_service.list_customers(company_id):
        merged = dict(row)
        profile = profiles.get(row["detail_account_id"])
        if profile is not None:
            merged.update({key: getattr(profile, key) for key in _CUSTOMER_PROFILE_FIELD_KEYS})
            merged["status_code"] = profile.status_code
        else:
            merged.update(blank)
        result.append(merged)
    return result


def create_customer_detail_account(
    company_id: int, code: str, name: str, custom_fields: dict | None = None,
    parent_detail_account_id: int | None = None, **person_fields,
) -> int:
    detail_fields, profile_fields = _split_customer_fields(person_fields)
    detail_account_id = dimensions_service.create_customer(
        company_id, code, name, custom_fields=custom_fields, parent_detail_account_id=parent_detail_account_id,
        **detail_fields,
    )
    with new_session() as session:
        session.add(
            CustomerProfile(
                customer_detail_account_id=detail_account_id, company_id=company_id, status_code="PENDING_APPROVAL",
                submitted_at=datetime.datetime.now(), **profile_fields,
            )
        )
        session.commit()
    return detail_account_id


def update_customer_detail_account(
    detail_account_id: int, company_id: int, code: str, name: str, is_active: bool,
    custom_fields: dict | None = None, **person_fields,
) -> None:
    detail_fields, profile_fields = _split_customer_fields(person_fields)
    dimensions_service.update_customer(
        detail_account_id, company_id, code, name, is_active, custom_fields=custom_fields, **detail_fields
    )
    with new_session() as session:
        profile = session.get(CustomerProfile, detail_account_id)
        if profile is None:
            session.add(
                CustomerProfile(
                    customer_detail_account_id=detail_account_id, company_id=company_id, status_code="PENDING_APPROVAL",
                    submitted_at=datetime.datetime.now(), **profile_fields,
                )
            )
        else:
            for key, value in profile_fields.items():
                setattr(profile, key, value)
        session.commit()


def delete_customer_detail_account(detail_account_id: int, company_id: int) -> None:
    with new_session() as session:
        profile = session.get(CustomerProfile, detail_account_id)
        if profile is not None:
            session.delete(profile)
            session.commit()
    dimensions_service.delete_customer(detail_account_id, company_id)


# ---------------------------------------------------------------------
# تامین‌کننده
# ---------------------------------------------------------------------
@dataclass
class SupplierProfileFields:
    supplier_group_id: int | None = None
    default_price_list_id: int | None = None
    payment_term_days: int = 0
    credit_limit_amount: "decimal.Decimal | float" = 0
    default_lead_time_days: int | None = None
    incoterm_code: str | None = None
    preferred_currency_id: int | None = None


def create_supplier(
    company_id: int, code: str, name: str, fields: SupplierProfileFields | None = None,
    fast_track: bool = False, submitted_by_user_id: int | None = None,
) -> int:
    fields = fields or SupplierProfileFields()
    detail_account_id = dimensions_service.create_supplier(company_id, code, name)
    with new_session() as session:
        status = "ACTIVE" if fast_track else "PENDING_APPROVAL"
        session.add(
            SupplierProfile(
                supplier_detail_account_id=detail_account_id, company_id=company_id,
                supplier_group_id=fields.supplier_group_id, default_price_list_id=fields.default_price_list_id,
                payment_term_days=fields.payment_term_days, credit_limit_amount=fields.credit_limit_amount,
                default_lead_time_days=fields.default_lead_time_days, incoterm_code=fields.incoterm_code,
                preferred_currency_id=fields.preferred_currency_id, status_code=status,
                submitted_by_user_id=submitted_by_user_id, submitted_at=datetime.datetime.now(),
            )
        )
        session.commit()
    return detail_account_id


def get_supplier_profile(supplier_detail_account_id: int) -> SupplierProfile | None:
    with new_session() as session:
        return session.get(SupplierProfile, supplier_detail_account_id)


def list_supplier_profiles(company_id: int, status_code: str | None = None) -> list[SupplierProfile]:
    with new_session() as session:
        stmt = select(SupplierProfile).where(SupplierProfile.company_id == company_id)
        if status_code:
            stmt = stmt.where(SupplierProfile.status_code == status_code)
        return list(session.scalars(stmt))


def approve_supplier(supplier_detail_account_id: int, approved_by_user_id: int) -> None:
    with new_session() as session:
        profile = session.get(SupplierProfile, supplier_detail_account_id)
        if profile is None:
            raise ValueError("تامین‌کننده نامعتبر است.")
        if profile.status_code != "PENDING_APPROVAL":
            raise ValueError("فقط تامین‌کنندهٔ درانتظارِ تایید قابلِ‌تاییدِ اعتباری است.")
        profile.status_code = "ACTIVE"
        profile.approved_by_user_id = approved_by_user_id
        profile.approved_at = datetime.datetime.now()
        session.commit()


def set_supplier_hold(supplier_detail_account_id: int, status_code: str, reason: str, held_by_user_id: int) -> None:
    if status_code not in ("ON_HOLD", "DISQUALIFIED"):
        raise ValueError("وضعیتِ توقف نامعتبر است.")
    with new_session() as session:
        profile = session.get(SupplierProfile, supplier_detail_account_id)
        if profile is None:
            raise ValueError("تامین‌کننده نامعتبر است.")
        profile.status_code = status_code
        profile.hold_reason = reason
        profile.held_at = datetime.datetime.now()
        profile.held_by_user_id = held_by_user_id
        session.commit()


def update_supplier_quality_rating(supplier_detail_account_id: int, quality_rating) -> None:
    """فقط از رخدادهایِ QC انبار فراخوانی شود — هرگز از فرمِ کاربر مستقیم
    (مرحلهٔ ۳، بخشِ ۷)."""
    with new_session() as session:
        profile = session.get(SupplierProfile, supplier_detail_account_id)
        if profile is None:
            raise ValueError("تامین‌کننده نامعتبر است.")
        profile.quality_rating = quality_rating
        session.commit()


# ---------------------------------------------------------------------
# یکپارچه‌سازی با فرمِ واحدِ تفصیلی (تامین‌کننده) — هم‌الگو با مشتری.
# ---------------------------------------------------------------------
_SUPPLIER_DETAIL_FIELD_KEYS = ("economic_code", "national_id", "phone", "mobile", "address", "bank_account_no", "notes")
_SUPPLIER_PROFILE_FIELD_KEYS = (
    "supplier_group_id", "default_price_list_id", "payment_term_days", "credit_limit_amount",
    "default_lead_time_days", "incoterm_code",
)


def _split_supplier_fields(person_fields: dict) -> tuple[dict, dict]:
    detail_fields = {k: person_fields.get(k) for k in _SUPPLIER_DETAIL_FIELD_KEYS}
    profile_fields = {k: person_fields.get(k) for k in _SUPPLIER_PROFILE_FIELD_KEYS}
    profile_fields["payment_term_days"] = int(profile_fields["payment_term_days"] or 0)
    profile_fields["credit_limit_amount"] = profile_fields["credit_limit_amount"] or 0
    return detail_fields, profile_fields


def list_supplier_detail_accounts(company_id: int) -> list[dict]:
    profiles = {p.supplier_detail_account_id: p for p in list_supplier_profiles(company_id)}
    blank = {key: None for key in _SUPPLIER_PROFILE_FIELD_KEYS} | {"status_code": None}
    result = []
    for row in dimensions_service.list_suppliers(company_id):
        merged = dict(row)
        profile = profiles.get(row["detail_account_id"])
        if profile is not None:
            merged.update({key: getattr(profile, key) for key in _SUPPLIER_PROFILE_FIELD_KEYS})
            merged["status_code"] = profile.status_code
        else:
            merged.update(blank)
        result.append(merged)
    return result


def create_supplier_detail_account(
    company_id: int, code: str, name: str, custom_fields: dict | None = None,
    parent_detail_account_id: int | None = None, **person_fields,
) -> int:
    detail_fields, profile_fields = _split_supplier_fields(person_fields)
    detail_account_id = dimensions_service.create_supplier(
        company_id, code, name, custom_fields=custom_fields, parent_detail_account_id=parent_detail_account_id,
        **detail_fields,
    )
    with new_session() as session:
        session.add(
            SupplierProfile(
                supplier_detail_account_id=detail_account_id, company_id=company_id, status_code="PENDING_APPROVAL",
                submitted_at=datetime.datetime.now(), **profile_fields,
            )
        )
        session.commit()
    return detail_account_id


def update_supplier_detail_account(
    detail_account_id: int, company_id: int, code: str, name: str, is_active: bool,
    custom_fields: dict | None = None, **person_fields,
) -> None:
    detail_fields, profile_fields = _split_supplier_fields(person_fields)
    dimensions_service.update_supplier(
        detail_account_id, company_id, code, name, is_active, custom_fields=custom_fields, **detail_fields
    )
    with new_session() as session:
        profile = session.get(SupplierProfile, detail_account_id)
        if profile is None:
            session.add(
                SupplierProfile(
                    supplier_detail_account_id=detail_account_id, company_id=company_id, status_code="PENDING_APPROVAL",
                    submitted_at=datetime.datetime.now(), **profile_fields,
                )
            )
        else:
            for key, value in profile_fields.items():
                setattr(profile, key, value)
        session.commit()


def delete_supplier_detail_account(detail_account_id: int, company_id: int) -> None:
    with new_session() as session:
        profile = session.get(SupplierProfile, detail_account_id)
        if profile is not None:
            session.delete(profile)
            session.commit()
    dimensions_service.delete_supplier(detail_account_id, company_id)


# ---------------------------------------------------------------------
# آدرس و مخاطب (مشترک بینِ مشتری/تامین‌کننده)
# ---------------------------------------------------------------------
def list_party_addresses(party_detail_account_id: int) -> list[PartyAddress]:
    with new_session() as session:
        return list(
            session.scalars(select(PartyAddress).where(PartyAddress.party_detail_account_id == party_detail_account_id))
        )


_PARTY_ADDRESS_TYPES = ("OFFICE", "STORE", "WAREHOUSE", "DELIVERY", "BILLING", "RETURN")


def add_party_address(
    party_detail_account_id: int, address_type_code: str, line1: str, city: str | None = None,
    province: str | None = None, postal_code: str | None = None, is_default: bool = False,
    gps_latitude: "decimal.Decimal | None" = None, gps_longitude: "decimal.Decimal | None" = None,
    geofence_radius_meters: int | None = None,
) -> int:
    if address_type_code not in _PARTY_ADDRESS_TYPES:
        raise ValueError("نوعِ آدرس نامعتبر است.")
    with new_session() as session:
        if is_default:
            session.query(PartyAddress).filter(
                PartyAddress.party_detail_account_id == party_detail_account_id,
                PartyAddress.address_type_code == address_type_code,
                PartyAddress.is_default.is_(True),
            ).update({"is_default": False})
        row = PartyAddress(
            party_detail_account_id=party_detail_account_id, address_type_code=address_type_code, line1=line1,
            city=city, province=province, postal_code=postal_code, is_default=is_default,
            gps_latitude=gps_latitude, gps_longitude=gps_longitude, geofence_radius_meters=geofence_radius_meters,
        )
        session.add(row)
        session.commit()
        return row.address_id


def update_party_address(
    address_id: int, party_detail_account_id: int, address_type_code: str, line1: str, city: str | None = None,
    province: str | None = None, postal_code: str | None = None, is_default: bool = False,
    gps_latitude: "decimal.Decimal | None" = None, gps_longitude: "decimal.Decimal | None" = None,
    geofence_radius_meters: int | None = None,
) -> None:
    if address_type_code not in _PARTY_ADDRESS_TYPES:
        raise ValueError("نوعِ آدرس نامعتبر است.")
    with new_session() as session:
        row = session.get(PartyAddress, address_id)
        if row is None or row.party_detail_account_id != party_detail_account_id:
            raise ValueError("آدرس نامعتبر است.")
        if is_default and not row.is_default:
            session.query(PartyAddress).filter(
                PartyAddress.party_detail_account_id == party_detail_account_id,
                PartyAddress.address_type_code == address_type_code,
                PartyAddress.is_default.is_(True),
            ).update({"is_default": False})
        row.address_type_code = address_type_code
        row.line1 = line1
        row.city = city
        row.province = province
        row.postal_code = postal_code
        row.is_default = is_default
        row.gps_latitude = gps_latitude
        row.gps_longitude = gps_longitude
        row.geofence_radius_meters = geofence_radius_meters
        session.commit()


def delete_party_address(address_id: int, party_detail_account_id: int) -> None:
    with new_session() as session:
        row = session.get(PartyAddress, address_id)
        if row is None or row.party_detail_account_id != party_detail_account_id:
            raise ValueError("آدرس نامعتبر است.")
        session.delete(row)
        session.commit()


def list_party_contacts(party_detail_account_id: int) -> list[PartyContact]:
    with new_session() as session:
        return list(
            session.scalars(select(PartyContact).where(PartyContact.party_detail_account_id == party_detail_account_id))
        )


def add_party_contact(
    party_detail_account_id: int, full_name: str, role_title: str | None = None, phone: str | None = None,
    email: str | None = None, is_primary: bool = False,
) -> int:
    with new_session() as session:
        if is_primary:
            session.query(PartyContact).filter(
                PartyContact.party_detail_account_id == party_detail_account_id, PartyContact.is_primary.is_(True)
            ).update({"is_primary": False})
        row = PartyContact(
            party_detail_account_id=party_detail_account_id, full_name=full_name, role_title=role_title, phone=phone,
            email=email, is_primary=is_primary,
        )
        session.add(row)
        session.commit()
        return row.contact_id


# ---------------------------------------------------------------------
# قراردادها (خرید/فروش) — استفاده برایِ قیمتِ توافقی (مرحلهٔ ۶)
# ---------------------------------------------------------------------
def get_active_contract_price(
    counterparty_detail_account_id: int, item_id: int, contract_type_code: str, as_of_date: datetime.date
) -> "decimal.Decimal | None":
    with new_session() as session:
        contract = session.scalar(
            select(CommercialContract).where(
                CommercialContract.counterparty_detail_account_id == counterparty_detail_account_id,
                CommercialContract.item_id == item_id,
                CommercialContract.contract_type_code == contract_type_code,
                CommercialContract.status_code == "ACTIVE",
                CommercialContract.valid_from <= as_of_date,
                (CommercialContract.valid_to.is_(None)) | (CommercialContract.valid_to >= as_of_date),
            )
        )
        return contract.contract_price if contract is not None else None
