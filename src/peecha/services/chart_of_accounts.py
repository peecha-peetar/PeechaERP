"""سرویس کدینگ حسابداری — فقط ساخت حساب‌های سطح گروه (بدون والد) در این
نسخه؛ افزودن زیرشاخه (کل/معین) با انتخاب والد یک قدم بعدی است."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.accounting import AccountCategory, AccountNature, AccountType, ChartOfAccount
from peecha.db.models.core import Translation


@dataclass
class AccountRow:
    account_id: int
    full_code: str
    name: str
    account_level: int
    is_postable: bool


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
        return [
            AccountRow(
                account_id=a.account_id,
                full_code=a.full_code,
                name=names.get(a.account_id, a.segment_code),
                account_level=a.account_level,
                is_postable=a.is_postable,
            )
            for a in accounts
        ]


def create_root_account(
    company_id: int,
    segment_code: str,
    name: str,
    nature_code: str,
    category_code: str,
    account_type_code: str,
    is_postable: bool,
    language_id: int,
) -> ChartOfAccount:
    with new_session() as session:
        nature = session.scalar(select(AccountNature).where(AccountNature.code == nature_code))
        category = session.scalar(select(AccountCategory).where(AccountCategory.code == category_code))
        account_type = session.scalar(select(AccountType).where(AccountType.code == account_type_code))
        if nature is None or category is None or account_type is None:
            raise ValueError("مقدار ماهیت/دسته/نوع حساب نامعتبر است.")

        account = ChartOfAccount(
            company_id=company_id,
            parent_account_id=None,
            segment_code=segment_code,
            full_code=segment_code,
            account_level=1,
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
