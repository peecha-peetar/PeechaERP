"""سرویس کدینگ حسابداری — درخت سه‌سطحی گروه/کل/معین.

سطح از روی والدِ انتخابی محاسبه می‌شود (نه ورودی کاربر): بدون والد یعنی
سطح ۱ (گروه)، والدِ سطح ۱ یعنی سطح ۲ (کل)، والدِ سطح ۲ یعنی سطح ۳ (معین).
معین دیگر نمی‌تواند زیرشاخه بگیرد — طبق طراحی دیتابیس (account_level) که
فقط ۳ سطح را در نظر گرفته.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.accounting import AccountCategory, AccountNature, AccountType, ChartOfAccount
from peecha.db.models.core import Translation

MAX_ACCOUNT_LEVEL = 3


@dataclass
class AccountRow:
    account_id: int
    full_code: str
    name: str
    account_level: int
    is_postable: bool
    nature_code: str
    category_code: str
    account_type_code: str


def list_accounts(company_id: int) -> list[AccountRow]:
    with new_session() as session:
        accounts = session.scalars(
            select(ChartOfAccount)
            .where(ChartOfAccount.company_id == company_id)
            .order_by(ChartOfAccount.full_code)
        ).all()
        account_ids = [a.account_id for a in accounts]
        names: dict[int, str] = {}
        if account_ids:
            rows = session.execute(
                select(Translation.entity_id, Translation.value).where(
                    Translation.entity_type == "ChartOfAccount",
                    Translation.entity_id.in_(account_ids),
                    Translation.property_name == "Name",
                )
            ).all()
            names = dict(rows)

        nature_codes = dict(session.execute(select(AccountNature.nature_id, AccountNature.code)).all())
        category_codes = dict(session.execute(select(AccountCategory.category_id, AccountCategory.code)).all())
        account_type_codes = dict(session.execute(select(AccountType.account_type_id, AccountType.code)).all())

        return [
            AccountRow(
                account_id=a.account_id,
                full_code=a.full_code,
                name=names.get(a.account_id, a.segment_code),
                account_level=a.account_level,
                is_postable=a.is_postable,
                nature_code=nature_codes[a.nature_id],
                category_code=category_codes[a.category_id],
                account_type_code=account_type_codes[a.account_type_id],
            )
            for a in accounts
        ]


def list_postable_accounts(company_id: int) -> list[AccountRow]:
    """فقط حساب‌های قابل‌ثبت‌سند (معمولاً سطح معین) — برای انتخابگرِ ردیف سند."""
    return [row for row in list_accounts(company_id) if row.is_postable]


def create_account(
    company_id: int,
    segment_code: str,
    name: str,
    nature_code: str,
    category_code: str,
    account_type_code: str,
    is_postable: bool,
    language_id: int,
    parent_account_id: int | None = None,
) -> ChartOfAccount:
    with new_session() as session:
        nature = session.scalar(select(AccountNature).where(AccountNature.code == nature_code))
        category = session.scalar(select(AccountCategory).where(AccountCategory.code == category_code))
        account_type = session.scalar(select(AccountType).where(AccountType.code == account_type_code))
        if nature is None or category is None or account_type is None:
            raise ValueError("مقدار ماهیت/دسته/نوع حساب نامعتبر است.")

        if parent_account_id is None:
            account_level = 1
            full_code = segment_code
        else:
            parent = session.get(ChartOfAccount, parent_account_id)
            if parent is None or parent.company_id != company_id:
                raise ValueError("حساب والد نامعتبر است.")
            if parent.account_level >= MAX_ACCOUNT_LEVEL:
                raise ValueError("حساب سطح معین دیگر نمی‌تواند زیرشاخه بگیرد.")
            account_level = parent.account_level + 1
            full_code = f"{parent.full_code}-{segment_code}"

        account = ChartOfAccount(
            company_id=company_id,
            parent_account_id=parent_account_id,
            segment_code=segment_code,
            full_code=full_code,
            account_level=account_level,
            nature_id=nature.nature_id,
            category_id=category.category_id,
            account_type_id=account_type.account_type_id,
            is_postable=is_postable,
        )
        session.add(account)
        session.flush()

        session.add(
            Translation(
                entity_type="ChartOfAccount",
                entity_id=account.account_id,
                property_name="Name",
                language_id=language_id,
                value=name,
            )
        )
        session.commit()
        session.refresh(account)
        session.expunge(account)
        return account
