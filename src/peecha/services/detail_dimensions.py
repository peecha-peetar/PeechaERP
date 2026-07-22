"""سرویسِ ابعادِ تفصیلی/مراکزِ هزینه (Detail Dimensions).

هر «نوعِ بُعد» (مثل COST_CENTER، PROJECT، CUSTOMER) چند «حسابِ تفصیلی»
(مثلاً مرکزِ هزینه‌ی «فروش»، «تولید») دارد. هر حسابِ کدینگ می‌تواند
مشخص کند کدام نوع‌بُعدها برایش الزامی‌اند (acc.account_detail_dimensions)؛
هنگامِ ثبتِ سند، هر ردیف که حسابش این الزام را دارد باید یک حسابِ تفصیلی
از همان نوع‌بُعد را انتخاب کند (acc.journal_entry_line_details)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import (
    AccountDetailDimension,
    AccountPersonGroup,
    ChartOfAccount,
    CustomerDetail,
    DetailAccount,
    DetailDimensionType,
    JournalEntryLineDetail,
    PersonGroup,
    PersonnelDetail,
    SupplierDetail,
)

# نوع‌بُعدِ سیستمی/رزروشده‌ی «تفصیلیِ اشخاص» — بر خلافِ نوع‌بُعدهایی مثلِ
# مرکزِ هزینه/پروژه که کاربر خودش می‌سازد، این یکی برای هر شرکت خودکار
# ساخته می‌شود (008_person_dimension.sql برای شرکت‌های موجود، و
# ensure_person_dimension برای شرکت‌های تازه) و همیشه در هر ردیفِ سند
# حاضر است — با پیش‌فرضِ NO_DETAIL_CODE اگر شخصِ خاصی انتخاب نشده باشد.
PERSON_DIMENSION_CODE = "PERSON"
NO_DETAIL_CODE = "NONE"
NO_DETAIL_LABEL = "بدون تفصیلی"


@dataclass
class DimensionTypeRow:
    dimension_type_id: int
    code: str
    is_active: bool
    detail_account_count: int


@dataclass
class DetailAccountRow:
    detail_account_id: int
    dimension_type_id: int
    code: str
    name: str | None
    is_active: bool
    person_group_id: int | None = None


def list_dimension_types(company_id: int, *, include_system: bool = False) -> list[DimensionTypeRow]:
    with new_session() as session:
        query = select(DetailDimensionType).where(DetailDimensionType.company_id == company_id)
        if not include_system:
            query = query.where(DetailDimensionType.code != PERSON_DIMENSION_CODE)
        types = session.scalars(query.order_by(DetailDimensionType.code)).all()
        counts = dict(
            session.execute(
                select(DetailAccount.dimension_type_id, func.count())
                .where(DetailAccount.company_id == company_id)
                .group_by(DetailAccount.dimension_type_id)
            ).all()
        )
        return [
            DimensionTypeRow(
                dimension_type_id=t.dimension_type_id,
                code=t.code,
                is_active=t.is_active,
                detail_account_count=counts.get(t.dimension_type_id, 0),
            )
            for t in types
        ]


def list_active_dimension_types(company_id: int) -> list[DimensionTypeRow]:
    return [row for row in list_dimension_types(company_id) if row.is_active]


def create_dimension_type(company_id: int, code: str) -> DetailDimensionType:
    with new_session() as session:
        dimension_type = DetailDimensionType(company_id=company_id, code=code.strip().upper())
        session.add(dimension_type)
        session.commit()
        session.refresh(dimension_type)
        session.expunge(dimension_type)
        return dimension_type


def update_dimension_type(dimension_type_id: int, company_id: int, code: str, is_active: bool) -> None:
    with new_session() as session:
        dimension_type = session.get(DetailDimensionType, dimension_type_id)
        if dimension_type is None or dimension_type.company_id != company_id:
            raise ValueError("نوعِ بُعدِ تفصیلی نامعتبر است.")
        dimension_type.code = code.strip().upper()
        dimension_type.is_active = is_active
        session.commit()


def delete_dimension_type(dimension_type_id: int, company_id: int) -> None:
    with new_session() as session:
        dimension_type = session.get(DetailDimensionType, dimension_type_id)
        if dimension_type is None or dimension_type.company_id != company_id:
            raise ValueError("نوعِ بُعدِ تفصیلی نامعتبر است.")

        detail_count = session.scalar(
            select(func.count())
            .select_from(DetailAccount)
            .where(DetailAccount.dimension_type_id == dimension_type_id)
        )
        if detail_count:
            raise ValueError("این نوعِ بُعد حسابِ تفصیلی دارد؛ اول آن‌ها را حذف کنید.")

        usage_count = session.scalar(
            select(func.count())
            .select_from(AccountDetailDimension)
            .where(AccountDetailDimension.dimension_type_id == dimension_type_id)
        )
        if usage_count:
            raise ValueError("این نوعِ بُعد روی حساب‌های کدینگ استفاده شده؛ ابتدا آن ارتباط را حذف کنید.")

        session.delete(dimension_type)
        session.commit()


def list_detail_accounts(company_id: int, dimension_type_id: int) -> list[DetailAccountRow]:
    with new_session() as session:
        rows = session.scalars(
            select(DetailAccount)
            .where(DetailAccount.company_id == company_id, DetailAccount.dimension_type_id == dimension_type_id)
            .order_by(DetailAccount.code)
        ).all()
        return [
            DetailAccountRow(
                detail_account_id=r.detail_account_id,
                dimension_type_id=r.dimension_type_id,
                code=r.code,
                name=r.name,
                is_active=r.is_active,
            )
            for r in rows
        ]


def create_detail_account(company_id: int, dimension_type_id: int, code: str, name: str | None = None) -> DetailAccount:
    with new_session() as session:
        dimension_type = session.get(DetailDimensionType, dimension_type_id)
        if dimension_type is None or dimension_type.company_id != company_id:
            raise ValueError("نوعِ بُعدِ تفصیلی نامعتبر است.")
        detail_account = DetailAccount(
            company_id=company_id, dimension_type_id=dimension_type_id, code=code.strip(), name=(name or None)
        )
        session.add(detail_account)
        session.commit()
        session.refresh(detail_account)
        session.expunge(detail_account)
        return detail_account


def update_detail_account(
    detail_account_id: int, company_id: int, code: str, is_active: bool, name: str | None = None
) -> None:
    with new_session() as session:
        detail_account = session.get(DetailAccount, detail_account_id)
        if detail_account is None or detail_account.company_id != company_id:
            raise ValueError("حسابِ تفصیلی نامعتبر است.")
        detail_account.code = code.strip()
        detail_account.name = name or None
        detail_account.is_active = is_active
        session.commit()


def delete_detail_account(detail_account_id: int, company_id: int) -> None:
    with new_session() as session:
        detail_account = session.get(DetailAccount, detail_account_id)
        if detail_account is None or detail_account.company_id != company_id:
            raise ValueError("حسابِ تفصیلی نامعتبر است.")

        usage_count = session.scalar(
            select(func.count())
            .select_from(JournalEntryLineDetail)
            .where(JournalEntryLineDetail.detail_account_id == detail_account_id)
        )
        if usage_count:
            raise ValueError("این حسابِ تفصیلی در سندهای حسابداری استفاده شده؛ قابل حذف نیست.")

        session.delete(detail_account)
        session.commit()


def get_account_dimension_type_ids(account_id: int) -> list[int]:
    """نوع‌بُعدهایی که برای این حسابِ کدینگ الزامی‌اند (برای پرکردنِ چک‌باکس‌های فرم)."""
    with new_session() as session:
        return list(
            session.scalars(
                select(AccountDetailDimension.dimension_type_id).where(
                    AccountDetailDimension.account_id == account_id
                )
            ).all()
        )


def set_account_dimension_types(account_id: int, company_id: int, dimension_type_ids: list[int]) -> None:
    """جایگزینیِ کاملِ نوع‌بُعدهای الزامیِ یک حساب — همه‌ی انتخاب‌شده‌ها
    is_required=True هستند (در این نسخه هیچ نوع‌بُعدی اختیاری تعریف نمی‌شود)."""
    with new_session() as session:
        account = session.get(ChartOfAccount, account_id)
        if account is None or account.company_id != company_id:
            raise ValueError("حساب نامعتبر است.")

        session.execute(
            AccountDetailDimension.__table__.delete().where(AccountDetailDimension.account_id == account_id)
        )
        for dimension_type_id in dimension_type_ids:
            session.add(
                AccountDetailDimension(account_id=account_id, dimension_type_id=dimension_type_id, is_required=True)
            )
        session.commit()


@dataclass
class RequiredDimension:
    dimension_type_id: int
    code: str
    detail_accounts: list[DetailAccountRow]


def get_required_dimensions_for_account(account_id: int) -> list[RequiredDimension]:
    """برای صفحه‌ی صدور سند: وقتی حسابی در یک ردیف انتخاب می‌شود، این تابع
    نوع‌بُعدهای الزامیِ آن حساب را به‌همراه فهرستِ حساب‌های تفصیلیِ فعالِ هرکدام
    برمی‌گرداند تا در ردیف، انتخابگرِ مربوطه ساخته شود."""
    with new_session() as session:
        account = session.get(ChartOfAccount, account_id)
        if account is None:
            return []

        dimension_type_ids = list(
            session.scalars(
                select(AccountDetailDimension.dimension_type_id).where(
                    AccountDetailDimension.account_id == account_id,
                    AccountDetailDimension.is_required.is_(True),
                )
            ).all()
        )
        if not dimension_type_ids:
            return []

        types_by_id = {
            t.dimension_type_id: t
            for t in session.scalars(
                select(DetailDimensionType).where(DetailDimensionType.dimension_type_id.in_(dimension_type_ids))
            ).all()
        }

        result: list[RequiredDimension] = []
        for dimension_type_id in dimension_type_ids:
            dimension_type = types_by_id.get(dimension_type_id)
            if dimension_type is None or not dimension_type.is_active:
                continue
            detail_rows = session.scalars(
                select(DetailAccount)
                .where(DetailAccount.dimension_type_id == dimension_type_id, DetailAccount.is_active.is_(True))
                .order_by(DetailAccount.code)
            ).all()
            result.append(
                RequiredDimension(
                    dimension_type_id=dimension_type_id,
                    code=dimension_type.code,
                    detail_accounts=[
                        DetailAccountRow(
                            detail_account_id=d.detail_account_id,
                            dimension_type_id=d.dimension_type_id,
                            code=d.code,
                            name=d.name,
                            is_active=d.is_active,
                        )
                        for d in detail_rows
                    ],
                )
            )
        return result


# --- تفصیلیِ اشخاص (سیستمی/همیشه‌حاضر) ------------------------------------


def ensure_person_dimension(session, company_id: int) -> int:
    """نوعِ‌بُعدِ PERSON و حسابِ تفصیلیِ پیش‌فرضِ «بدون تفصیلی» را برای این
    شرکت تضمین می‌کند (اگر نبود می‌سازد) و شناسه‌ی نوعِ‌بُعد را برمی‌گرداند.
    باید با همان session/تراکنشِ ساختِ شرکت صدا زده شود (bootstrap یا
    companies.create_company) تا هر شرکتِ تازه از همان لحظه‌ی ساخت این را
    داشته باشد؛ برای شرکت‌های موجودِ قبل از این ویژگی هم
    008_person_dimension.sql همین کار را یک‌بار برایِ همه انجام داده."""
    dimension_type = session.scalar(
        select(DetailDimensionType).where(
            DetailDimensionType.company_id == company_id, DetailDimensionType.code == PERSON_DIMENSION_CODE
        )
    )
    if dimension_type is None:
        dimension_type = DetailDimensionType(company_id=company_id, code=PERSON_DIMENSION_CODE, is_active=True)
        session.add(dimension_type)
        session.flush()

    no_detail = session.scalar(
        select(DetailAccount).where(
            DetailAccount.company_id == company_id,
            DetailAccount.dimension_type_id == dimension_type.dimension_type_id,
            DetailAccount.code == NO_DETAIL_CODE,
        )
    )
    if no_detail is None:
        session.add(
            DetailAccount(
                company_id=company_id,
                dimension_type_id=dimension_type.dimension_type_id,
                code=NO_DETAIL_CODE,
                name=NO_DETAIL_LABEL,
                is_active=True,
            )
        )
        session.flush()

    return dimension_type.dimension_type_id


def get_person_dimension_type_id(company_id: int) -> int:
    with new_session() as session:
        return ensure_person_dimension(session, company_id)


def get_no_detail_account_id(company_id: int) -> int:
    with new_session() as session:
        dimension_type_id = ensure_person_dimension(session, company_id)
        session.commit()
        no_detail = session.scalar(
            select(DetailAccount).where(
                DetailAccount.company_id == company_id,
                DetailAccount.dimension_type_id == dimension_type_id,
                DetailAccount.code == NO_DETAIL_CODE,
            )
        )
        return no_detail.detail_account_id


def list_persons(company_id: int) -> list[DetailAccountRow]:
    with new_session() as session:
        dimension_type_id = ensure_person_dimension(session, company_id)
        session.commit()
        rows = session.scalars(
            select(DetailAccount)
            .where(DetailAccount.company_id == company_id, DetailAccount.dimension_type_id == dimension_type_id)
            .order_by(DetailAccount.code)
        ).all()
        return [
            DetailAccountRow(
                detail_account_id=r.detail_account_id,
                dimension_type_id=r.dimension_type_id,
                code=r.code,
                name=r.name,
                is_active=r.is_active,
                person_group_id=r.person_group_id,
            )
            for r in rows
        ]


def list_active_persons(company_id: int) -> list[DetailAccountRow]:
    return [row for row in list_persons(company_id) if row.is_active]


# --- گروه‌های تفصیلیِ اشخاص (مشتری/تامین‌کننده/پرسنل) ----------------------
# طبقِ درخواستِ صریح: به‌جای یک فرمِ عمومیِ «شخص»، هر شخص باید به یکی از این
# گروه‌ها تعلق داشته باشد و فقط از فرمِ اختصاصیِ همان گروه (مشتریان/
# تامین‌کنندگان/پرسنل) تعریف/ویرایش شود؛ هر گروه جدولِ جزئیاتِ تکمیلیِ خودش
# را دارد (acc.customer_details/supplier_details/personnel_details).

CUSTOMER_GROUP_CODE = "CUSTOMER"
SUPPLIER_GROUP_CODE = "SUPPLIER"
PERSONNEL_GROUP_CODE = "PERSONNEL"

_PERSON_GROUP_SEED = ((CUSTOMER_GROUP_CODE, "مشتری"), (SUPPLIER_GROUP_CODE, "تامین‌کننده"), (PERSONNEL_GROUP_CODE, "پرسنل"))


@dataclass
class PersonGroupRow:
    person_group_id: int
    code: str
    name: str
    is_active: bool


def ensure_person_groups(session, company_id: int) -> dict[str, int]:
    """سه گروهِ تفصیلیِ سیستمی (مشتری/تامین‌کننده/پرسنل) را برای این شرکت
    تضمین می‌کند و نگاشتِ کد→شناسه را برمی‌گرداند. باید با همان session/
    تراکنشِ ساختِ شرکت صدا زده شود (مثلِ ensure_person_dimension)."""
    existing = {
        g.code: g.person_group_id
        for g in session.scalars(select(PersonGroup).where(PersonGroup.company_id == company_id)).all()
    }
    for code, name in _PERSON_GROUP_SEED:
        if code not in existing:
            group = PersonGroup(company_id=company_id, code=code, name=name, is_active=True)
            session.add(group)
            session.flush()
            existing[code] = group.person_group_id
    return existing


def list_person_groups(company_id: int) -> list[PersonGroupRow]:
    with new_session() as session:
        ensure_person_groups(session, company_id)
        session.commit()
        rows = session.scalars(
            select(PersonGroup).where(PersonGroup.company_id == company_id).order_by(PersonGroup.person_group_id)
        ).all()
        return [PersonGroupRow(g.person_group_id, g.code, g.name, g.is_active) for g in rows]


def get_person_group_id(company_id: int, code: str) -> int:
    with new_session() as session:
        groups = ensure_person_groups(session, company_id)
        session.commit()
        return groups[code]


def _group_row_to_person_row(
    detail_account: DetailAccount,
    extra,
    extra_field_names: tuple[str, ...],
) -> dict:
    row = {
        "detail_account_id": detail_account.detail_account_id,
        "code": detail_account.code,
        "name": detail_account.name,
        "is_active": detail_account.is_active,
    }
    for field_name in extra_field_names:
        row[field_name] = getattr(extra, field_name, None) if extra is not None else None
    return row


def _list_group_persons(company_id: int, group_code: str, detail_model, extra_field_names: tuple[str, ...]) -> list[dict]:
    with new_session() as session:
        dimension_type_id = ensure_person_dimension(session, company_id)
        person_group_id = ensure_person_groups(session, company_id)[group_code]
        session.commit()
        rows = session.scalars(
            select(DetailAccount)
            .where(
                DetailAccount.company_id == company_id,
                DetailAccount.dimension_type_id == dimension_type_id,
                DetailAccount.person_group_id == person_group_id,
            )
            .order_by(DetailAccount.code)
        ).all()
        detail_account_ids = [r.detail_account_id for r in rows]
        extras_by_id = {
            e.detail_account_id: e
            for e in session.scalars(
                select(detail_model).where(detail_model.detail_account_id.in_(detail_account_ids))
            ).all()
        }
        return [
            _group_row_to_person_row(r, extras_by_id.get(r.detail_account_id), extra_field_names) for r in rows
        ]


def _create_group_person(
    company_id: int,
    group_code: str,
    code: str,
    name: str,
    detail_model,
    extra_fields: dict,
) -> int:
    with new_session() as session:
        dimension_type_id = ensure_person_dimension(session, company_id)
        person_group_id = ensure_person_groups(session, company_id)[group_code]
        detail_account = DetailAccount(
            company_id=company_id,
            dimension_type_id=dimension_type_id,
            person_group_id=person_group_id,
            code=code.strip(),
            name=name.strip() or None,
        )
        session.add(detail_account)
        session.flush()
        session.add(detail_model(detail_account_id=detail_account.detail_account_id, **extra_fields))
        session.commit()
        return detail_account.detail_account_id


def _update_group_person(
    detail_account_id: int,
    company_id: int,
    code: str,
    name: str,
    is_active: bool,
    detail_model,
    extra_fields: dict,
) -> None:
    with new_session() as session:
        detail_account = session.get(DetailAccount, detail_account_id)
        if detail_account is None or detail_account.company_id != company_id:
            raise ValueError("شخص نامعتبر است.")
        detail_account.code = code.strip()
        detail_account.name = name.strip() or None
        detail_account.is_active = is_active

        extra = session.get(detail_model, detail_account_id)
        if extra is None:
            session.add(detail_model(detail_account_id=detail_account_id, **extra_fields))
        else:
            for field_name, value in extra_fields.items():
                setattr(extra, field_name, value)
        session.commit()


def _delete_group_person(detail_account_id: int, company_id: int, detail_model) -> None:
    with new_session() as session:
        detail_account = session.get(DetailAccount, detail_account_id)
        if detail_account is None or detail_account.company_id != company_id:
            raise ValueError("شخص نامعتبر است.")

        usage_count = session.scalar(
            select(func.count())
            .select_from(JournalEntryLineDetail)
            .where(JournalEntryLineDetail.detail_account_id == detail_account_id)
        )
        if usage_count:
            raise ValueError("این شخص در سندهای حسابداری استفاده شده؛ قابل حذف نیست.")

        extra = session.get(detail_model, detail_account_id)
        if extra is not None:
            session.delete(extra)
        session.delete(detail_account)
        session.commit()


_CUSTOMER_FIELDS = ("economic_code", "national_id", "phone", "mobile", "address", "credit_limit", "notes")
_SUPPLIER_FIELDS = ("economic_code", "national_id", "phone", "mobile", "address", "bank_account_no", "notes")
_PERSONNEL_FIELDS = (
    "national_id",
    "personnel_no",
    "position_title",
    "phone",
    "mobile",
    "hire_date",
    "bank_account_no",
    "notes",
)


def list_customers(company_id: int) -> list[dict]:
    return _list_group_persons(company_id, CUSTOMER_GROUP_CODE, CustomerDetail, _CUSTOMER_FIELDS)


def create_customer(company_id: int, code: str, name: str, **extra_fields) -> int:
    return _create_group_person(company_id, CUSTOMER_GROUP_CODE, code, name, CustomerDetail, extra_fields)


def update_customer(detail_account_id: int, company_id: int, code: str, name: str, is_active: bool, **extra_fields) -> None:
    _update_group_person(detail_account_id, company_id, code, name, is_active, CustomerDetail, extra_fields)


def delete_customer(detail_account_id: int, company_id: int) -> None:
    _delete_group_person(detail_account_id, company_id, CustomerDetail)


def list_suppliers(company_id: int) -> list[dict]:
    return _list_group_persons(company_id, SUPPLIER_GROUP_CODE, SupplierDetail, _SUPPLIER_FIELDS)


def create_supplier(company_id: int, code: str, name: str, **extra_fields) -> int:
    return _create_group_person(company_id, SUPPLIER_GROUP_CODE, code, name, SupplierDetail, extra_fields)


def update_supplier(detail_account_id: int, company_id: int, code: str, name: str, is_active: bool, **extra_fields) -> None:
    _update_group_person(detail_account_id, company_id, code, name, is_active, SupplierDetail, extra_fields)


def delete_supplier(detail_account_id: int, company_id: int) -> None:
    _delete_group_person(detail_account_id, company_id, SupplierDetail)


def list_personnel(company_id: int) -> list[dict]:
    return _list_group_persons(company_id, PERSONNEL_GROUP_CODE, PersonnelDetail, _PERSONNEL_FIELDS)


def create_personnel(company_id: int, code: str, name: str, **extra_fields) -> int:
    return _create_group_person(company_id, PERSONNEL_GROUP_CODE, code, name, PersonnelDetail, extra_fields)


def update_personnel(detail_account_id: int, company_id: int, code: str, name: str, is_active: bool, **extra_fields) -> None:
    _update_group_person(detail_account_id, company_id, code, name, is_active, PersonnelDetail, extra_fields)


def delete_personnel(detail_account_id: int, company_id: int) -> None:
    _delete_group_person(detail_account_id, company_id, PersonnelDetail)


# --- محدودکردنِ معین به گروهِ تفصیلیِ خاص ----------------------------------


def get_account_person_group_ids(account_id: int) -> list[int]:
    with new_session() as session:
        return list(
            session.scalars(
                select(AccountPersonGroup.person_group_id).where(AccountPersonGroup.account_id == account_id)
            ).all()
        )


def get_required_person_groups_for_account(account_id: int) -> list[PersonGroupRow]:
    """برای صفحه‌ی صدور سند: گروه(های) تفصیلیِ مجازِ حسابِ انتخاب‌شده در یک
    ردیف — اگر خالی باشد یعنی این معین به گروهی محدود نشده (انتخابِ تفصیلی آزاد است)."""
    with new_session() as session:
        group_ids = list(
            session.scalars(
                select(AccountPersonGroup.person_group_id).where(AccountPersonGroup.account_id == account_id)
            ).all()
        )
        if not group_ids:
            return []
        groups = session.scalars(select(PersonGroup).where(PersonGroup.person_group_id.in_(group_ids))).all()
        return [PersonGroupRow(g.person_group_id, g.code, g.name, g.is_active) for g in groups]


def set_account_person_groups(account_id: int, company_id: int, person_group_ids: list[int]) -> None:
    with new_session() as session:
        account = session.get(ChartOfAccount, account_id)
        if account is None or account.company_id != company_id:
            raise ValueError("حساب نامعتبر است.")
        session.execute(AccountPersonGroup.__table__.delete().where(AccountPersonGroup.account_id == account_id))
        for person_group_id in person_group_ids:
            session.add(AccountPersonGroup(account_id=account_id, person_group_id=person_group_id))
        session.commit()
