"""تنظیماتِ دامنهٔ مدیریتِ بازرگانی: نگاشتِ حساب‌ها، Feature Toggle، شماره‌گذاریِ
اسناد (طبقِ مرحلهٔ ۱۱). کلیدهایِ CUSTOMER_RECEIVABLE/SUPPLIER_PAYABLE عمداً
این‌جا نیستند — از inv.account_mappings مصرف می‌شوند (inventory_engine.
get_account_mapping)، نه تکرار."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.commercial import (
    CommercialAccountMapping,
    CommercialCompanyFeature,
    CommercialFeatureDefinition,
    DocumentNumberingSequence,
    IndustryProfile,
    IndustryProfileFeatureDefault,
)

MAPPING_LABELS: dict[str, str] = {
    "SALES_REVENUE": "درآمدِ فروش",
    "SALES_TAX_PAYABLE": "مالیاتِ فروشِ پرداختنی",
    "SALES_DISCOUNT": "تخفیفِ فروش",
    "PURCHASE_TAX_RECEIVABLE": "مالیاتِ خریدِ دریافتنی",
    "PURCHASE_DISCOUNT": "تخفیفِ خرید",
    "SHIPPING_REVENUE": "درآمدِ حمل",
    "SHIPPING_EXPENSE": "هزینهٔ حمل",
    "COMMISSION_EXPENSE": "هزینهٔ کمیسیون",
    "GIFT_CARD_LIABILITY": "بدهیِ کارتِ‌هدیه",
    "LOYALTY_LIABILITY": "بدهیِ باشگاهِ مشتریان",
    "ROUNDING": "مابه‌التفاوتِ گرد‌کردن",
    "LANDED_COST_CLEARING": "تسویهٔ بهایِ تمام‌شدهٔ وارداتی",
    "VENDOR_REBATE_RECEIVABLE": "ریبیتِ دریافتنیِ تامین‌کننده",
    "WARRANTY_EXPENSE": "هزینهٔ گارانتی",
}


@dataclass
class AccountMappingRow:
    mapping_key: str
    label: str
    account_id: int | None
    account_label: str | None
    detail_account_id: int | None = None


def get_account_mapping(company_id: int, mapping_key: str) -> int | None:
    with new_session() as session:
        row = session.get(CommercialAccountMapping, (company_id, mapping_key))
        return row.account_id if row is not None else None


def get_fixed_detail_for_mapping(company_id: int, mapping_key: str) -> tuple[int, int] | None:
    """(dimension_type_id, detail_account_id) تفصیلیِ ثابتِ این نقش، اگر
    تنظیم شده باشد -- طبقِ درخواستِ صریح («برایِ فاکتورِ فروش هم تفصیلیِ
    ثابت برایِ مالیات، مثلِ فاکتورِ خرید»)."""
    with new_session() as session:
        row = session.get(CommercialAccountMapping, (company_id, mapping_key))
        if row is None or row.detail_account_id is None:
            return None
        detail = session.get(DetailAccount, row.detail_account_id)
        if detail is None:
            return None
        return detail.dimension_type_id, detail.detail_account_id


def set_account_mapping(company_id: int, mapping_key: str, account_id: int, detail_account_id: int | None = None) -> None:
    if mapping_key not in MAPPING_LABELS:
        raise ValueError("کلیدِ نگاشتِ نامعتبر است.")
    with new_session() as session:
        row = session.get(CommercialAccountMapping, (company_id, mapping_key))
        if row is None:
            session.add(
                CommercialAccountMapping(
                    company_id=company_id, mapping_key=mapping_key, account_id=account_id,
                    detail_account_id=detail_account_id,
                )
            )
        else:
            row.account_id = account_id
            row.detail_account_id = detail_account_id
        session.commit()


def list_account_mappings(company_id: int) -> list[AccountMappingRow]:
    from peecha.services import chart_of_accounts as coa_service

    with new_session() as session:
        rows = {
            r.mapping_key: (r.account_id, r.detail_account_id)
            for r in session.scalars(
                select(CommercialAccountMapping).where(CommercialAccountMapping.company_id == company_id)
            )
        }
    accounts_by_id = {a.account_id: f"{a.full_code} — {a.name}" for a in coa_service.list_accounts(company_id)}
    result = []
    for key, label in MAPPING_LABELS.items():
        account_id, detail_account_id = rows.get(key, (None, None))
        result.append(
            AccountMappingRow(key, label, account_id, accounts_by_id.get(account_id) if account_id else None, detail_account_id)
        )
    return result


def resolve_role_account(session, company_id: int, mapping_key: str) -> int:
    row = session.get(CommercialAccountMapping, (company_id, mapping_key))
    if row is None:
        raise ValueError(f"حسابِ «{MAPPING_LABELS.get(mapping_key, mapping_key)}» هنوز در تنظیماتِ بازرگانی مشخص نشده است.")
    return row.account_id


# ---------------------------------------------------------------------
# Feature Toggle
# ---------------------------------------------------------------------
@dataclass
class FeatureRow:
    feature_code: str
    name: str
    module_scope: str
    requires_feature_code: str | None
    is_enabled: bool


def list_features(company_id: int) -> list[FeatureRow]:
    with new_session() as session:
        definitions = session.scalars(select(CommercialFeatureDefinition)).all()
        enabled = {
            r.feature_code
            for r in session.scalars(
                select(CommercialCompanyFeature).where(
                    CommercialCompanyFeature.company_id == company_id, CommercialCompanyFeature.is_enabled.is_(True)
                )
            )
        }
        return [
            FeatureRow(d.feature_code, d.name, d.module_scope, d.requires_feature_code, d.feature_code in enabled)
            for d in definitions
        ]


def set_feature_enabled(company_id: int, feature_code: str, is_enabled: bool) -> None:
    with new_session() as session:
        definition = session.get(CommercialFeatureDefinition, feature_code)
        if definition is None:
            raise ValueError("ویژگیِ نامعتبر است.")
        if is_enabled and definition.requires_feature_code is not None:
            dep_row = session.get(CommercialCompanyFeature, (company_id, definition.requires_feature_code))
            if dep_row is None or not dep_row.is_enabled:
                dep = session.get(CommercialFeatureDefinition, definition.requires_feature_code)
                raise ValueError(f"ابتدا باید ویژگیِ «{dep.name}» فعال شود.")
        row = session.get(CommercialCompanyFeature, (company_id, feature_code))
        if row is None:
            session.add(CommercialCompanyFeature(company_id=company_id, feature_code=feature_code, is_enabled=is_enabled))
        else:
            row.is_enabled = is_enabled
        session.commit()


def is_feature_enabled(company_id: int, feature_code: str) -> bool:
    with new_session() as session:
        row = session.get(CommercialCompanyFeature, (company_id, feature_code))
        return row is not None and row.is_enabled


def list_industry_profiles() -> list[IndustryProfile]:
    with new_session() as session:
        return list(session.scalars(select(IndustryProfile)))


def apply_industry_profile(company_id: int, profile_code: str) -> None:
    """فقط Toggleهایِ هنوز تنظیم‌نشده را پر می‌کند — هیچ Toggleِ
    ازقبل‌دستی‌تغییریافته را بازنویسی نمی‌کند (مرحلهٔ ۱۱، بخشِ ۵)."""
    with new_session() as session:
        profile = session.get(IndustryProfile, profile_code)
        if profile is None:
            raise ValueError("نمایهٔ صنعتی نامعتبر است.")
        defaults = session.scalars(
            select(IndustryProfileFeatureDefault).where(IndustryProfileFeatureDefault.profile_code == profile_code)
        ).all()
        for default in defaults:
            existing = session.get(CommercialCompanyFeature, (company_id, default.feature_code))
            if existing is None:
                session.add(
                    CommercialCompanyFeature(
                        company_id=company_id, feature_code=default.feature_code, is_enabled=default.default_enabled
                    )
                )
        session.commit()


# ---------------------------------------------------------------------
# شماره‌گذاریِ اسناد
# ---------------------------------------------------------------------
def get_numbering_sequence(company_id: int, document_type_code: str) -> DocumentNumberingSequence | None:
    with new_session() as session:
        return session.get(DocumentNumberingSequence, (company_id, document_type_code))


def set_numbering_sequence(company_id: int, document_type_code: str, prefix: str, reset_policy_code: str) -> None:
    if reset_policy_code not in ("YEARLY", "NEVER"):
        raise ValueError("سیاستِ بازنشانیِ نامعتبر است.")
    with new_session() as session:
        row = session.get(DocumentNumberingSequence, (company_id, document_type_code))
        if row is None:
            session.add(
                DocumentNumberingSequence(
                    company_id=company_id, document_type_code=document_type_code, prefix=prefix,
                    reset_policy_code=reset_policy_code,
                )
            )
        else:
            row.prefix = prefix
            row.reset_policy_code = reset_policy_code
        session.commit()
