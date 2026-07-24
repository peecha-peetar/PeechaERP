"""کپیِ کدینگِ حساب‌ها و گروه‌هایِ تفصیلی از یک شرکتِ «مبدأ» به یک شرکتِ
«مقصد» — طبقِ درخواستِ صریح: «بتونم کد حسابها و تفضیلی‌ها و گروه‌ها را از
یک شرکت به شرکتِ دیگر ... کپی کنم یا یک شرکتِ جدید با ویژگی‌هایِ انتخابی یا
همه‌یِ ویژگی‌هایِ یک شرکت ایجاد کنم».

نکته‌یِ معماری (طبقِ گفتگویِ تکمیلی با کاربر): در این سیستم کدینگِ حساب‌ها و
گروه‌هایِ تفصیلی مختصِ خودِ شرکت‌اند نه سالِ مالی — یک سالِ مالیِ جدید برایِ
همان شرکت از همان کدینگِ موجود استفاده می‌کند، نیازی به کپیِ جداگانه برایِ
سالِ مالی نیست. پس این ماژول فقط کپیِ بین‌شرکتی را انجام می‌دهد.

نوع‌بُعدهایِ سیستمی (PERSON و ۷ نوعِ «فرمِ خاص») و ۳ گروهِ اشخاص (مشتری/
تامین‌کننده/پرسنل) برایِ هر شرکتِ تازه از قبل به‌طورِ خودکار seed می‌شوند
(companies_service.create_company)؛ این‌جا فقط تنظیماتشان (سقفِ سطح/رنگ)
از مبدأ کپی می‌شود و نگاشتِ شناسه بر اساسِ «کد» (که همیشه ثابت است) انجام
می‌شود — نه ساختنِ ردیفِ تازه برایِ آن‌ها. فقط گروه‌هایِ «سادهِ» کاربرساخته
(کدهایِ دلخواه) واقعاً ردیفِ تازه می‌گیرند.

طبقِ انتخابِ کاربر، «حساب‌هایِ تفصیلی» (خودِ رکوردها — کالا/بانک/صندوق/...
/مرکزِ هزینه/پروژه/گروه‌هایِ ساده) هم کپی می‌شوند، اما اشخاصِ واقعیِ
مشتری/تامین‌کننده/پرسنل عمداً کپی نمی‌شوند — چون این‌ها روابطِ تجاریِ
مختصِ همان شرکت‌اند، نه بخشی از «کدینگ»."""

from __future__ import annotations

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.accounting import (
    AccountDetailDimension,
    AccountPersonGroup,
    ChartOfAccount,
    ChartOfAccountLevelConfig,
    DetailAccount,
    DetailDimensionType,
    DetailGroupField,
    DetailGroupLevel,
    DetailLevelDigitConfig,
    PersonGroup,
)
from peecha.db.models.core import Company
from peecha.services import detail_dimensions as dimensions_service

# نوع‌بُعدهایی که برایِ هر شرکت به‌طورِ خودکار seed می‌شوند — این‌ها هرگز
# ردیفِ تازه نمی‌گیرند، فقط با کدشان به نمونه‌یِ همینِ شرکتِ مقصد نگاشته می‌شوند.
_AUTO_SEEDED_DIMENSION_CODES = {dimensions_service.PERSON_DIMENSION_CODE, *dimensions_service.SPECIALIZED_DIMENSION_LABELS}


def clone_company_setup(
    source_company_id: int,
    target_company_id: int,
    *,
    copy_coa: bool,
    copy_detail_dimensions: bool,
) -> None:
    if source_company_id == target_company_id:
        raise ValueError("شرکتِ مبدأ و مقصد نمی‌توانند یکی باشند.")
    if not copy_coa and not copy_detail_dimensions:
        return

    with new_session() as session:
        source = session.get(Company, source_company_id)
        target = session.get(Company, target_company_id)
        if source is None:
            raise ValueError("شرکتِ مبدأ نامعتبر است.")
        if target is None:
            raise ValueError("شرکتِ مقصد نامعتبر است.")

        account_id_map: dict[int, int] = {}
        dimension_type_id_map: dict[int, int] = {}
        detail_account_id_map: dict[int, int] = {}

        # نگاشتِ گروه‌هایِ اشخاصِ خودکار-seedشده از رویِ کد (CUSTOMER/SUPPLIER/PERSONNEL)
        source_person_groups = session.scalars(
            select(PersonGroup).where(PersonGroup.company_id == source_company_id)
        ).all()
        target_person_groups_by_code = {
            g.code: g
            for g in session.scalars(select(PersonGroup).where(PersonGroup.company_id == target_company_id)).all()
        }
        person_group_id_map: dict[int, int] = {}
        for g in source_person_groups:
            target_group = target_person_groups_by_code.get(g.code)
            if target_group is None:
                continue
            person_group_id_map[g.person_group_id] = target_group.person_group_id
            if copy_detail_dimensions:
                target_group.max_level_no = g.max_level_no
                target_group.color = g.color

        if copy_coa:
            _clone_chart_of_accounts(session, source_company_id, target_company_id, account_id_map)
            _clone_account_level_config(session, source_company_id, target_company_id)

        if copy_detail_dimensions:
            _clone_dimension_types(session, source_company_id, target_company_id, dimension_type_id_map)
            _clone_detail_level_digit_config(session, source_company_id, target_company_id)
            _clone_group_levels(session, dimension_type_id_map, person_group_id_map)
            _clone_group_fields(session, dimension_type_id_map, person_group_id_map)
            _clone_detail_accounts(
                session, source_company_id, target_company_id, dimension_type_id_map, detail_account_id_map
            )

        if copy_coa and copy_detail_dimensions:
            _clone_account_dimension_links(session, source_company_id, account_id_map, dimension_type_id_map)
            _clone_account_person_group_links(session, source_company_id, account_id_map, person_group_id_map)

        session.commit()


def _clone_chart_of_accounts(
    session, source_company_id: int, target_company_id: int, account_id_map: dict[int, int]
) -> None:
    rows = session.scalars(
        select(ChartOfAccount)
        .where(ChartOfAccount.company_id == source_company_id)
        .order_by(ChartOfAccount.account_level)
    ).all()
    for r in rows:
        new_account = ChartOfAccount(
            company_id=target_company_id,
            parent_account_id=account_id_map.get(r.parent_account_id) if r.parent_account_id else None,
            segment_code=r.segment_code,
            full_code=r.full_code,
            account_level=r.account_level,
            nature_id=r.nature_id,
            category_id=r.category_id,
            account_type_id=r.account_type_id,
            is_postable=r.is_postable,
            currency_id=r.currency_id,
            is_active=r.is_active,
        )
        session.add(new_account)
        session.flush()
        account_id_map[r.account_id] = new_account.account_id


def _clone_account_level_config(session, source_company_id: int, target_company_id: int) -> None:
    session.execute(
        ChartOfAccountLevelConfig.__table__.delete().where(
            ChartOfAccountLevelConfig.company_id == target_company_id
        )
    )
    rows = session.scalars(
        select(ChartOfAccountLevelConfig).where(ChartOfAccountLevelConfig.company_id == source_company_id)
    ).all()
    for r in rows:
        session.add(
            ChartOfAccountLevelConfig(
                company_id=target_company_id,
                account_level=r.account_level,
                code_length=r.code_length,
                range_from=r.range_from,
                range_to=r.range_to,
            )
        )


def _clone_dimension_types(
    session, source_company_id: int, target_company_id: int, dimension_type_id_map: dict[int, int]
) -> None:
    source_types = session.scalars(
        select(DetailDimensionType).where(DetailDimensionType.company_id == source_company_id)
    ).all()
    target_types_by_code = {
        t.code: t
        for t in session.scalars(
            select(DetailDimensionType).where(DetailDimensionType.company_id == target_company_id)
        ).all()
    }
    for t in source_types:
        target_type = target_types_by_code.get(t.code)
        if target_type is not None:
            # نوع‌بُعدِ خودکار-seedشده (PERSON یا یکی از ۷ نوعِ فرمِ خاص) — فقط تنظیماتش کپی می‌شود.
            target_type.max_level_no = t.max_level_no
            target_type.color = t.color
            dimension_type_id_map[t.dimension_type_id] = target_type.dimension_type_id
        else:
            # گروهِ «سادهِ» کاربرساخته — ردیفِ تازه.
            new_type = DetailDimensionType(
                company_id=target_company_id,
                code=t.code,
                is_active=t.is_active,
                max_level_no=t.max_level_no,
                color=t.color,
            )
            session.add(new_type)
            session.flush()
            dimension_type_id_map[t.dimension_type_id] = new_type.dimension_type_id


def _clone_detail_level_digit_config(session, source_company_id: int, target_company_id: int) -> None:
    session.execute(
        DetailLevelDigitConfig.__table__.delete().where(DetailLevelDigitConfig.company_id == target_company_id)
    )
    rows = session.scalars(
        select(DetailLevelDigitConfig).where(DetailLevelDigitConfig.company_id == source_company_id)
    ).all()
    for r in rows:
        session.add(
            DetailLevelDigitConfig(company_id=target_company_id, level_no=r.level_no, code_length=r.code_length)
        )


def _clone_group_levels(session, dimension_type_id_map: dict[int, int], person_group_id_map: dict[int, int]) -> None:
    rows = session.scalars(
        select(DetailGroupLevel).where(DetailGroupLevel.dimension_type_id.in_(dimension_type_id_map.keys()))
    ).all()
    for r in rows:
        target_dimension_type_id = dimension_type_id_map.get(r.dimension_type_id)
        if target_dimension_type_id is None:
            continue
        target_person_group_id = person_group_id_map.get(r.person_group_id, r.person_group_id) if r.person_group_id else 0
        session.execute(
            DetailGroupLevel.__table__.delete().where(
                DetailGroupLevel.dimension_type_id == target_dimension_type_id,
                DetailGroupLevel.person_group_id == target_person_group_id,
                DetailGroupLevel.level_no == r.level_no,
            )
        )
        session.add(
            DetailGroupLevel(
                dimension_type_id=target_dimension_type_id,
                person_group_id=target_person_group_id,
                level_no=r.level_no,
                range_from=r.range_from,
                range_to=r.range_to,
            )
        )


def _clone_group_fields(session, dimension_type_id_map: dict[int, int], person_group_id_map: dict[int, int]) -> None:
    rows = session.scalars(
        select(DetailGroupField).where(DetailGroupField.dimension_type_id.in_(dimension_type_id_map.keys()))
    ).all()
    for r in rows:
        target_dimension_type_id = dimension_type_id_map.get(r.dimension_type_id)
        if target_dimension_type_id is None:
            continue
        target_person_group_id = person_group_id_map.get(r.person_group_id, r.person_group_id) if r.person_group_id else 0
        session.execute(
            DetailGroupField.__table__.delete().where(
                DetailGroupField.dimension_type_id == target_dimension_type_id,
                DetailGroupField.person_group_id == target_person_group_id,
                DetailGroupField.field_key == r.field_key,
            )
        )
        session.add(
            DetailGroupField(
                dimension_type_id=target_dimension_type_id,
                person_group_id=target_person_group_id,
                field_key=r.field_key,
                label=r.label,
                kind=r.kind,
                is_required=r.is_required,
                sort_order=r.sort_order,
            )
        )


def _clone_detail_accounts(
    session,
    source_company_id: int,
    target_company_id: int,
    dimension_type_id_map: dict[int, int],
    detail_account_id_map: dict[int, int],
) -> None:
    """طبقِ درخواستِ صریح، خودِ حساب‌هایِ تفصیلی (کالا/بانک/صندوق/.../مرکزِ
    هزینه/پروژه/گروه‌هایِ ساده) هم کپی می‌شوند — به‌جز اشخاصِ واقعیِ
    مشتری/تامین‌کننده/پرسنل (روابطِ تجاریِ مختصِ همان شرکت، نه بخشی از
    کدینگ) و ردیفِ سیستمیِ «بدون تفصیلی» (که خودش برایِ شرکتِ مقصد seed شده)."""
    rows = session.scalars(
        select(DetailAccount)
        .where(DetailAccount.company_id == source_company_id, DetailAccount.person_group_id.is_(None))
        .order_by(DetailAccount.level_no)
    ).all()
    for r in rows:
        target_dimension_type_id = dimension_type_id_map.get(r.dimension_type_id)
        if target_dimension_type_id is None:
            continue
        if r.code == dimensions_service.NO_DETAIL_CODE:
            continue
        new_account = DetailAccount(
            company_id=target_company_id,
            dimension_type_id=target_dimension_type_id,
            code=r.code,
            name=r.name,
            person_group_id=None,
            is_active=r.is_active,
            parent_detail_account_id=detail_account_id_map.get(r.parent_detail_account_id)
            if r.parent_detail_account_id
            else None,
            level_no=r.level_no,
            extra_fields=dict(r.extra_fields or {}),
        )
        session.add(new_account)
        session.flush()
        detail_account_id_map[r.detail_account_id] = new_account.detail_account_id


def _clone_account_dimension_links(
    session, source_company_id: int, account_id_map: dict[int, int], dimension_type_id_map: dict[int, int]
) -> None:
    rows = session.scalars(
        select(AccountDetailDimension).where(AccountDetailDimension.account_id.in_(account_id_map.keys()))
    ).all()
    for r in rows:
        target_account_id = account_id_map.get(r.account_id)
        target_dimension_type_id = dimension_type_id_map.get(r.dimension_type_id)
        if target_account_id is None or target_dimension_type_id is None:
            continue
        session.add(
            AccountDetailDimension(
                account_id=target_account_id, dimension_type_id=target_dimension_type_id, is_required=r.is_required
            )
        )


def _clone_account_person_group_links(
    session, source_company_id: int, account_id_map: dict[int, int], person_group_id_map: dict[int, int]
) -> None:
    rows = session.scalars(
        select(AccountPersonGroup).where(AccountPersonGroup.account_id.in_(account_id_map.keys()))
    ).all()
    for r in rows:
        target_account_id = account_id_map.get(r.account_id)
        target_person_group_id = person_group_id_map.get(r.person_group_id)
        if target_account_id is None or target_person_group_id is None:
            continue
        session.add(AccountPersonGroup(account_id=target_account_id, person_group_id=target_person_group_id))
