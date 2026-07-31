"""سرویسِ ابعادِ تفصیلی/مراکزِ هزینه (Detail Dimensions).

هر «نوعِ بُعد» (مثل COST_CENTER، PROJECT، CUSTOMER) چند «حسابِ تفصیلی»
(مثلاً مرکزِ هزینه‌ی «فروش»، «تولید») دارد. هر حسابِ کدینگ می‌تواند
مشخص کند کدام نوع‌بُعدها برایش الزامی‌اند (acc.account_detail_dimensions)؛
هنگامِ ثبتِ سند، هر ردیف که حسابش این الزام را دارد باید یک حسابِ تفصیلی
از همان نوع‌بُعد را انتخاب کند (acc.journal_entry_line_details)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError

from peecha.db.base import new_session
from peecha.db.models.accounting import (
    AccountDetailDimension,
    AccountPersonGroup,
    ChartOfAccount,
    CustomerDetail,
    DetailAccount,
    DetailDimensionType,
    DetailGroupField,
    DetailGroupLevel,
    DetailLevelDigitConfig,
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
# طبقِ درخواستِ صریح: کدِ تفصیلیِ پیش‌فرض («بدون تفصیلی») باید «۰۰۰۰۰۰»
# باشد (نه یک کدِ متنیِ دلخواه مثلِ "NONE") — 011_coding_settings.sql
# رکوردهایِ already-seeded را هم به همین کد به‌روز کرده.
NO_DETAIL_CODE = "000000"
NO_DETAIL_LABEL = "بدون تفصیلی"

# طبقِ درخواستِ صریح: حسابِ تفصیلی می‌تواند تا ۴ سطح سلسله‌مراتب داشته باشد
# (مثلِ گروه/کل/معین/تفصیلیِ خودِ کدینگِ حسابداری، اما این‌جا برایِ خودِ
# تفصیلی) — طولِ کدِ هر سطح اختیاری و به‌ازایِ هر گروه جداگانه قابل‌تعریف
# است (acc.detail_group_levels)؛ گروهی که پیکربندی نداشته باشد همچنان
# تخت/بدونِ محدودیتِ طول می‌ماند (سازگار با گروه‌های موجود).
MAX_DETAIL_LEVEL = 4
_VALID_FIELD_KINDS = ("text", "decimal", "date", "boolean")


@dataclass
class DimensionTypeRow:
    dimension_type_id: int
    code: str
    is_active: bool
    detail_account_count: int
    color: str | None = None


@dataclass
class DetailAccountRow:
    detail_account_id: int
    dimension_type_id: int
    code: str
    name: str | None
    is_active: bool
    person_group_id: int | None = None
    parent_detail_account_id: int | None = None
    level_no: int = 1
    full_code: str = ""
    extra_fields: dict[str, Any] = field(default_factory=dict)


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
                color=t.color,
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
        if dimension_type.code in SPECIALIZED_DIMENSION_LABELS or dimension_type.code == PERSON_DIMENSION_CODE:
            raise ValueError("عنوانِ گروه‌هایِ سیستمی (کالا/بانک/... و اشخاص) قابلِ‌تغییر نیست.")
        dimension_type.code = code.strip().upper()
        dimension_type.is_active = is_active
        session.commit()


def set_dimension_type_color(dimension_type_id: int, company_id: int, color: str | None) -> None:
    """طبقِ درخواستِ صریح: در هنگامِ پیکربندیِ یک گروهِ تفصیلی بتوان رنگِ
    اختصاصیِ آن را مشخص کرد — این رنگ در فهرستِ واحدِ تفصیلی‌ها (نمایِ
    درختی) و کمبویِ تفصیلیِ فرمِ صدورِ سند استفاده می‌شود."""
    with new_session() as session:
        dimension_type = session.get(DetailDimensionType, dimension_type_id)
        if dimension_type is None or dimension_type.company_id != company_id:
            raise ValueError("نوعِ بُعدِ تفصیلی نامعتبر است.")
        dimension_type.color = color or None
        session.commit()


def set_person_group_color(person_group_id: int, company_id: int, color: str | None) -> None:
    with new_session() as session:
        group = session.get(PersonGroup, person_group_id)
        if group is None or group.company_id != company_id:
            raise ValueError("گروه نامعتبر است.")
        group.color = color or None
        session.commit()


def get_group_color(dimension_type_id: int, person_group_id: int = 0) -> str | None:
    with new_session() as session:
        if person_group_id:
            group = session.get(PersonGroup, person_group_id)
            return group.color if group is not None else None
        dimension_type = session.get(DetailDimensionType, dimension_type_id)
        return dimension_type.color if dimension_type is not None else None


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


def group_has_any_usage(dimension_type_id: int, company_id: int, person_group_id: int = 0) -> bool:
    """آیا حتی یکی از حساب‌هایِ تفصیلیِ همین گروه (نه کلِ شرکت) در سندی
    استفاده شده — طبقِ درخواستِ صریح، قفلِ ویرایشِ سطح/بازه/سقفِ سطح باید
    مخصوصِ همین گروه باشد، نه قفلِ سراسریِ «شرکت سند دارد»."""
    with new_session() as session:
        query = select(DetailAccount.detail_account_id).where(
            DetailAccount.company_id == company_id, DetailAccount.dimension_type_id == dimension_type_id
        )
        if person_group_id:
            query = query.where(DetailAccount.person_group_id == person_group_id)
        else:
            query = query.where(DetailAccount.person_group_id.is_(None))
        account_ids = session.scalars(query).all()
        if not account_ids:
            return False
        return (
            session.scalar(
                select(func.count())
                .select_from(JournalEntryLineDetail)
                .where(JournalEntryLineDetail.detail_account_id.in_(account_ids))
            )
            > 0
        )


def set_person_group_name(person_group_id: int, company_id: int, name: str) -> None:
    """طبقِ درخواستِ صریح: عنوانِ گروه (اینجا برایِ مشتری/تامین‌کننده/پرسنل)
    باید در هر شرایطی (حتی وقتی حساب‌هایِ تفصیلی‌اش سند دارند) قابلِ‌اصلاح
    باشد — بر خلافِ سطح/بازه که بعدِ سنددارشدن قفل می‌شود."""
    with new_session() as session:
        group = session.get(PersonGroup, person_group_id)
        if group is None or group.company_id != company_id:
            raise ValueError("گروه نامعتبر است.")
        name = name.strip()
        if not name:
            raise ValueError("نام نمی‌تواند خالی باشد.")
        group.name = name
        session.commit()


def delete_custom_group_completely(dimension_type_id: int, company_id: int) -> None:
    """حذفِ کاملِ یک گروهِ «سادهِ کاربرساخته» — طبقِ درخواستِ صریح: اگر
    زیرمجموعه‌هایِ آن (حساب‌هایِ تفصیلی) سند نداشته باشند، کاملِ گروه
    (حساب‌های تفصیلی + سطوح + فیلدهایِ اختصاصی + خودِ نوع‌بُعد) حذف شود.
    فقط برای گروه‌هایِ سادهِ کاربرساخته مجاز است — ۷ نوعِ فرمِ خاص
    (کالا/بانک/...) و مشتری/تامین‌کننده/پرسنل فیکسچرهایِ خودکارساخته‌اند
    که صفحه‌ی اختصاصیِ خودشان به وجودشان متکی است."""
    with new_session() as session:
        dimension_type = session.get(DetailDimensionType, dimension_type_id)
        if dimension_type is None or dimension_type.company_id != company_id:
            raise ValueError("نوعِ بُعدِ تفصیلی نامعتبر است.")
        if dimension_type.code in SPECIALIZED_DIMENSION_LABELS or dimension_type.code == PERSON_DIMENSION_CODE:
            raise ValueError("این گروه سیستمی است و قابلِ‌حذفِ کامل نیست.")

        account_ids = session.scalars(
            select(DetailAccount.detail_account_id).where(DetailAccount.dimension_type_id == dimension_type_id)
        ).all()
        if account_ids:
            usage_count = session.scalar(
                select(func.count())
                .select_from(JournalEntryLineDetail)
                .where(JournalEntryLineDetail.detail_account_id.in_(account_ids))
            )
            if usage_count:
                raise ValueError("این گروه دارای حساب‌هایِ تفصیلیِ سنددار است؛ ابتدا سندهایِ مربوطه را حذف کنید.")

        usage_on_coding = session.scalar(
            select(func.count())
            .select_from(AccountDetailDimension)
            .where(AccountDetailDimension.dimension_type_id == dimension_type_id)
        )
        if usage_on_coding:
            raise ValueError("این نوعِ بُعد روی حساب‌های کدینگ استفاده شده؛ ابتدا آن ارتباط را حذف کنید.")

        # حذفِ حساب‌هایِ تفصیلی از عمیق‌ترین سطح به سمتِ ریشه — چون
        # parent_detail_account_id یک FKِ خودارجاع (RESTRICT پیش‌فرض) است.
        for level_no in range(MAX_DETAIL_LEVEL, 0, -1):
            session.execute(
                delete(DetailAccount).where(
                    DetailAccount.dimension_type_id == dimension_type_id, DetailAccount.level_no == level_no
                )
            )
        session.execute(delete(DetailGroupLevel).where(DetailGroupLevel.dimension_type_id == dimension_type_id))
        session.execute(delete(DetailGroupField).where(DetailGroupField.dimension_type_id == dimension_type_id))
        session.delete(dimension_type)
        session.commit()


def _compute_full_codes(rows: list[DetailAccount]) -> dict[int, str]:
    """کدِ کاملِ هر حسابِ تفصیلی را از زنجیره‌ی والدهایش می‌سازد (مثلِ
    full_code در کدینگِ حسابداری) — چون سلسله‌مراتب همیشه درونِ همان گروه
    است، والدها همیشه در همین فهرست حاضرند (نیازی به کوئریِ اضافه نیست)."""
    by_id = {r.detail_account_id: r for r in rows}
    cache: dict[int, str] = {}

    def resolve(row: DetailAccount) -> str:
        if row.detail_account_id in cache:
            return cache[row.detail_account_id]
        parent = by_id.get(row.parent_detail_account_id) if row.parent_detail_account_id else None
        full = f"{resolve(parent)}-{row.code}" if parent is not None else row.code
        cache[row.detail_account_id] = full
        return full

    return {r.detail_account_id: resolve(r) for r in rows}


def _to_detail_account_row(r: DetailAccount, full_codes: dict[int, str]) -> DetailAccountRow:
    return DetailAccountRow(
        detail_account_id=r.detail_account_id,
        dimension_type_id=r.dimension_type_id,
        code=r.code,
        name=r.name,
        is_active=r.is_active,
        person_group_id=r.person_group_id,
        parent_detail_account_id=r.parent_detail_account_id,
        level_no=r.level_no,
        full_code=full_codes.get(r.detail_account_id, r.code),
        extra_fields=dict(r.extra_fields or {}),
    )


def list_detail_accounts(company_id: int, dimension_type_id: int) -> list[DetailAccountRow]:
    with new_session() as session:
        rows = session.scalars(
            select(DetailAccount)
            .where(DetailAccount.company_id == company_id, DetailAccount.dimension_type_id == dimension_type_id)
            .order_by(DetailAccount.code)
        ).all()
        full_codes = _compute_full_codes(rows)
        return [_to_detail_account_row(r, full_codes) for r in rows]


def _validate_code_length(
    session, company_id: int, dimension_type_id: int, level_no: int, segment_code: str, person_group_id: int = 0
) -> None:
    """طبقِ درخواستِ صریح: «تعداد ارقام در همه گروهها مشابه هم باشه فقط
    بازه فرق داشته باشه» — طولِ کدِ هر سطح از acc.detail_level_digit_config
    (سراسری/یکسان برایِ همه‌ی گروه‌هایِ این شرکت) خوانده می‌شود؛ بازه‌ی
    از-تا همچنان مخصوصِ همین گروه (acc.detail_group_levels) می‌ماند.

    person_group_id=0 یعنی «بدونِ محدودیت به گروهِ خاصِ اشخاص» (همه‌ی
    گروه‌ها بجز مشتری/تامین‌کننده/پرسنل)؛ آن سه گروه شناسه‌ی واقعیِ
    person_group_id خودشان را می‌دهند تا بازه‌شان مستقل از هم بماند."""
    digit_config = session.get(DetailLevelDigitConfig, (company_id, level_no))
    if digit_config is not None and digit_config.code_length is not None:
        if len(segment_code) != digit_config.code_length:
            raise ValueError(f"طولِ کدِ سطحِ {level_no} باید دقیقاً {digit_config.code_length} رقم باشد.")

    range_config = session.get(DetailGroupLevel, (dimension_type_id, person_group_id, level_no))
    if range_config is not None and (range_config.range_from is not None or range_config.range_to is not None):
        if not segment_code.isdigit():
            raise ValueError(f"کدِ سطحِ {level_no} برایِ این گروه باید رقمی باشد (بازه‌ی از-تا تنظیم شده).")
        value = int(segment_code)
        if range_config.range_from is not None and value < range_config.range_from:
            raise ValueError(f"کدِ سطحِ {level_no} باید حداقل {range_config.range_from} باشد.")
        if range_config.range_to is not None and value > range_config.range_to:
            raise ValueError(f"کدِ سطحِ {level_no} باید حداکثر {range_config.range_to} باشد.")


def _get_group_max_level_no(session, dimension_type_id: int, person_group_id: int = 0) -> int:
    """سقفِ تعدادِ سطحِ سلسله‌مراتبِ این گروه — برایِ مشتری/تامین‌کننده/پرسنل
    از acc.person_groups.max_level_no، برایِ بقیه‌ی گروه‌ها از
    acc.detail_dimension_types.max_level_no."""
    if person_group_id:
        group = session.get(PersonGroup, person_group_id)
        return group.max_level_no if group is not None else 1
    dimension_type = session.get(DetailDimensionType, dimension_type_id)
    return dimension_type.max_level_no if dimension_type is not None else MAX_DETAIL_LEVEL


def get_group_max_level_no(dimension_type_id: int, person_group_id: int = 0) -> int:
    with new_session() as session:
        return _get_group_max_level_no(session, dimension_type_id, person_group_id)


def set_group_max_level_no(dimension_type_id: int, company_id: int, max_level_no: int, person_group_id: int = 0) -> None:
    if not (1 <= max_level_no <= MAX_DETAIL_LEVEL):
        raise ValueError(f"تعدادِ سطح باید بینِ ۱ تا {MAX_DETAIL_LEVEL} باشد.")
    with new_session() as session:
        if person_group_id:
            group = session.get(PersonGroup, person_group_id)
            if group is None or group.company_id != company_id:
                raise ValueError("گروه نامعتبر است.")
            group.max_level_no = max_level_no
        else:
            dimension_type = session.get(DetailDimensionType, dimension_type_id)
            if dimension_type is None or dimension_type.company_id != company_id:
                raise ValueError("گروه نامعتبر است.")
            dimension_type.max_level_no = max_level_no
        session.commit()


def suggest_next_code(company_id: int, dimension_type_id: int, level_no: int, person_group_id: int = 0) -> str:
    """پیشنهادِ کدِ بعدی برایِ این سطح: بزرگ‌ترینِ کدِ عددیِ موجود در همین
    نوع‌بُعد + ۱ (چونuq_detail_accounts رویِ کلِ dimension_type_id یکتاست، نه
    فقط هم‌سطح‌ها)؛ اگر حسابی نبود، از range_fromِ همین سطح/گروه (اگر
    تنظیم شده) شروع می‌شود وگرنه از ۱، و با تعدادِ رقمِ سراسریِ همین سطح
    (اگر تنظیم شده) صفر-پَد می‌شود. پیشنهاد است، نه اجبار — کاربر می‌تواند
    آن را در فرم عوض کند."""
    with new_session() as session:
        existing_codes = session.scalars(
            select(DetailAccount.code).where(
                DetailAccount.company_id == company_id,
                DetailAccount.dimension_type_id == dimension_type_id,
            )
        ).all()
        numeric_codes = [int(c) for c in existing_codes if c.isdigit()]

        range_config = session.get(DetailGroupLevel, (dimension_type_id, person_group_id, level_no))
        range_from = range_config.range_from if range_config is not None else None
        base = range_from if range_from is not None else 1

        next_value = max(numeric_codes, default=base - 1) + 1
        next_value = max(next_value, base)

        digit_config = session.get(DetailLevelDigitConfig, (company_id, level_no))
        code_length = digit_config.code_length if digit_config is not None else None
        return str(next_value).zfill(code_length) if code_length else str(next_value)


def create_detail_account(
    company_id: int,
    dimension_type_id: int,
    code: str,
    name: str | None = None,
    parent_detail_account_id: int | None = None,
    extra_fields: dict | None = None,
) -> DetailAccount:
    with new_session() as session:
        dimension_type = session.get(DetailDimensionType, dimension_type_id)
        if dimension_type is None or dimension_type.company_id != company_id:
            raise ValueError("نوعِ بُعدِ تفصیلی نامعتبر است.")

        max_level_no = _get_group_max_level_no(session, dimension_type_id)
        segment_code = code.strip()
        level_no = 1
        if parent_detail_account_id is not None:
            parent = session.get(DetailAccount, parent_detail_account_id)
            if (
                parent is None
                or parent.company_id != company_id
                or parent.dimension_type_id != dimension_type_id
            ):
                raise ValueError("حسابِ تفصیلیِ والد نامعتبر است.")
            if parent.level_no >= max_level_no:
                raise ValueError(f"این گروه حداکثر {max_level_no} سطح می‌تواند داشته باشد.")
            level_no = parent.level_no + 1

        _validate_code_length(session, company_id, dimension_type_id, level_no, segment_code)

        detail_account = DetailAccount(
            company_id=company_id,
            dimension_type_id=dimension_type_id,
            code=segment_code,
            name=(name or None),
            parent_detail_account_id=parent_detail_account_id,
            level_no=level_no,
            extra_fields=dict(extra_fields or {}),
        )
        session.add(detail_account)
        session.commit()
        session.refresh(detail_account)
        session.expunge(detail_account)
        return detail_account


def update_detail_account(
    detail_account_id: int,
    company_id: int,
    code: str,
    is_active: bool,
    name: str | None = None,
    extra_fields: dict | None = None,
) -> None:
    with new_session() as session:
        detail_account = session.get(DetailAccount, detail_account_id)
        if detail_account is None or detail_account.company_id != company_id:
            raise ValueError("حسابِ تفصیلی نامعتبر است.")
        segment_code = code.strip()
        _validate_code_length(session, company_id, detail_account.dimension_type_id, detail_account.level_no, segment_code)
        detail_account.code = segment_code
        detail_account.name = name or None
        detail_account.is_active = is_active
        if extra_fields is not None:
            detail_account.extra_fields = dict(extra_fields)
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

        # باگِ واقعیِ کشف‌شده (با عکسِ خطایِ واقعیِ کاربر): این تابعِ عمومی
        # (که specialized_dimensions.py برایِ مرکزِ هزینه/پروژه/بانک/... صدا
        # می‌زند) فقط acc.detail_accounts را حذف می‌کرد — اگر همان
        # detail_account_id (مثلاً به‌خاطرِ جابه‌جاییِ گروه یا مسیرِ دیگری)
        # ردیفِ نظیر در customer_details/supplier_details/personnel_details
        # هم داشته باشد، حذف با نقضِ کلیدِ خارجی شکست می‌خورد. _delete_group_person
        # این پاک‌سازی را برایِ مسیرهایِ اختصاصیِ خودش انجام می‌دهد؛ این‌جا هم
        # همان‌طور، هرکدام از این سه جدولِ ویژه که ردیفی داشته باشند، اول
        # پاک می‌شوند.
        for detail_model in (CustomerDetail, SupplierDetail, PersonnelDetail):
            extra = session.get(detail_model, detail_account_id)
            if extra is not None:
                session.delete(extra)
        # نکته‌یِ فنیِ کشف‌شده حینِ تست: بدونِ relationship()یِ ORM تعریف‌شده،
        # SQLAlchemy ترتیبِ حذفِ این جدول‌هایِ ویژه در برابرِ detail_accounts
        # را خودکار درست تضمین نمی‌کند؛ flush()ِ صریح، این پاک‌سازی‌ها را
        # قبل از حذفِ خودِ detail_account مطمئن می‌کند.
        session.flush()

        session.delete(detail_account)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError(
                "این حسابِ تفصیلی در جایِ دیگری استفاده شده و قابلِ حذف نیست."
            ) from exc


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


# --- تعدادِ رقمِ سراسریِ هر سطحِ تفصیلی (یکسان برایِ همه‌ی گروه‌ها) ---------
# طبقِ درخواستِ صریح: «تعداد ارقام در همه گروهها مشابه هم باشه فقط بازه فرق
# داشته باشه» — این تنظیم مخصوصِ یک گروه نیست، برایِ کلِ شرکت و همه‌ی
# گروه‌هایِ تفصیلی (کالا/بانک/مشتری/...) یکسان است.


@dataclass
class LevelDigitConfigRow:
    level_no: int
    code_length: int | None


def list_level_digit_config(company_id: int) -> list[LevelDigitConfigRow]:
    with new_session() as session:
        rows = session.scalars(
            select(DetailLevelDigitConfig)
            .where(DetailLevelDigitConfig.company_id == company_id)
            .order_by(DetailLevelDigitConfig.level_no)
        ).all()
        return [LevelDigitConfigRow(level_no=r.level_no, code_length=r.code_length) for r in rows]


def set_level_digit_config(company_id: int, config: dict[int, int | None]) -> None:
    """جایگزینیِ کاملِ تعدادِ رقمِ سراسریِ هر سطح — config یعنی {شماره‌ی سطح
    (۱ تا ۴): تعدادِ رقم یا None برایِ بدونِ محدودیت}.

    طبقِ درخواستِ صریح: بعدِ اولین سندِ شرکت، این تنظیمات دیگر قابلِ‌تغییر
    نیستند (تا کدهایِ ثبت‌شده‌ی موجود ناسازگار نشوند) — هم‌الگو با
    chart_of_accounts.set_account_level_config."""
    with new_session() as session:
        # importِ داخلِ تابع: journal_entries از detail_dimensions در سطحِ
        # ماژول import می‌کند، پس import سطحِ ماژول در جهتِ عکس یک وابستگیِ
        # چرخشی می‌ساخت.
        from peecha.services import journal_entries as je_service  # noqa: PLC0415

        if je_service.company_has_any_entries(company_id):
            raise ValueError("این شرکت سند دارد؛ تعدادِ رقمِ سطوحِ تفصیلی دیگر قابلِ‌تغییر نیست.")

        session.execute(
            DetailLevelDigitConfig.__table__.delete().where(DetailLevelDigitConfig.company_id == company_id)
        )
        for level_no, code_length in config.items():
            if not (1 <= level_no <= MAX_DETAIL_LEVEL):
                raise ValueError(f"شماره‌ی سطح باید بینِ ۱ تا {MAX_DETAIL_LEVEL} باشد.")
            if code_length is not None and not (1 <= code_length <= 10):
                raise ValueError("تعدادِ رقمِ کد باید بینِ ۱ تا ۱۰ باشد.")
            if code_length is None:
                continue
            session.add(DetailLevelDigitConfig(company_id=company_id, level_no=level_no, code_length=code_length))
        session.commit()


# --- پیکربندیِ بازه‌یِ از-تایِ هر سطحِ هر گروهِ تفصیلی (تا ۴ سطح) -----------
# طبقِ درخواستِ صریح: «فقط بازه فرق داشته باشه» — تعدادِ رقم سراسری شد
# (بالا)، ولی بازه‌ی از-تا همچنان مخصوصِ هر گروه (و برایِ اشخاص، مخصوصِ هر
# زیرگروه) می‌ماند.


@dataclass
class GroupLevelRow:
    level_no: int
    range_from: int | None = None
    range_to: int | None = None


def list_group_levels(dimension_type_id: int, person_group_id: int = 0) -> list[GroupLevelRow]:
    with new_session() as session:
        rows = session.scalars(
            select(DetailGroupLevel)
            .where(
                DetailGroupLevel.dimension_type_id == dimension_type_id,
                DetailGroupLevel.person_group_id == person_group_id,
            )
            .order_by(DetailGroupLevel.level_no)
        ).all()
        return [GroupLevelRow(level_no=r.level_no, range_from=r.range_from, range_to=r.range_to) for r in rows]


def _dimension_group_label(code: str, person_group_name: str | None) -> str:
    if person_group_name:
        return person_group_name
    return SPECIALIZED_DIMENSION_LABELS.get(code, code)


def _fetch_other_ranges(session, company_id: int) -> list:
    return session.execute(
        select(
            DetailGroupLevel.dimension_type_id,
            DetailGroupLevel.person_group_id,
            DetailGroupLevel.level_no,
            DetailGroupLevel.range_from,
            DetailGroupLevel.range_to,
            DetailDimensionType.code,
            PersonGroup.name,
        )
        .join(DetailDimensionType, DetailGroupLevel.dimension_type_id == DetailDimensionType.dimension_type_id)
        .outerjoin(PersonGroup, DetailGroupLevel.person_group_id == PersonGroup.person_group_id)
        .where(
            DetailDimensionType.company_id == company_id,
            or_(DetailGroupLevel.range_from.is_not(None), DetailGroupLevel.range_to.is_not(None)),
        )
    ).all()


def check_range_conflict(
    company_id: int,
    dimension_type_id: int,
    level_no: int,
    range_from: int | None,
    range_to: int | None,
    person_group_id: int = 0,
) -> str | None:
    """بدونِ هیچ اثرِ جانبی (بدونِ ذخیره)، چک می‌کند آیا این بازه با بازه‌یِ
    ذخیره‌شده‌یِ همین سطح در گروهِ تفصیلیِ دیگری هم‌پوشانی دارد یا نه —
    برایِ اعتبارسنجیِ زنده (رنگِ قرمز/سبز) در UI حینِ تایپ، پیش از کلیکِ
    دکمه‌ی ذخیره. اگر هم‌پوشانی باشد پیامِ خطا برمی‌گرداند، وگرنه None."""
    if range_from is None and range_to is None:
        return None
    new_from = range_from if range_from is not None else 0
    new_to = range_to if range_to is not None else 999_999_999
    with new_session() as session:
        other_ranges = _fetch_other_ranges(session, company_id)
        for other in other_ranges:
            if other.level_no != level_no:
                continue
            if other.dimension_type_id == dimension_type_id and other.person_group_id == person_group_id:
                continue
            other_from = other.range_from if other.range_from is not None else 0
            other_to = other.range_to if other.range_to is not None else 999_999_999
            if new_from <= other_to and other_from <= new_to:
                other_label = _dimension_group_label(other.code, other.name)
                return f"بازه‌ی سطحِ {level_no} با بازه‌ی «{other_label}» هم‌پوشانی دارد."
    return None


def set_group_levels(dimension_type_id: int, company_id: int, levels: dict[int, dict], person_group_id: int = 0) -> None:
    """جایگزینیِ کاملِ پیکربندیِ بازه‌یِ سطح‌های این گروه — levels یعنی
    {شماره‌ی سطح (۱ تا ۴): {"range_from": ..|None, "range_to": ..|None}}؛
    سطحی که در دیکشنری نباشد (یا هر دو بازه‌اش None باشد) بدونِ محدودیتِ
    بازه می‌ماند.

    person_group_id غیرِصفر یعنی این پیکربندی مخصوصِ یکی از زیرگروه‌هایِ
    اشخاص (مشتری/تامین‌کننده/پرسنل) است — مستقل از بقیه‌یِ زیرگروه‌ها و از
    پیکربندیِ عمومیِ (person_group_id=0) همان دیمنشن‌تایپ.

    طبقِ درخواستِ صریح، دو اعتبارسنجیِ تازه:
    ۱. بازه باید با تعدادِ رقمِ سراسریِ همان سطح (اگر تنظیم شده باشد،
       acc.detail_level_digit_config) سازگار باشد — عددی بزرگ‌تر از
       بزرگ‌ترین مقدارِ قابل‌نمایش با آن تعداد رقم پذیرفته نمی‌شود.
    ۲. بازه‌ی هر گروه باید مختصِ همان گروه بماند — اگر بازه‌ای برایِ
       همین سطح، با بازه‌یِ گروهِ دیگری هم‌پوشانی داشته باشد، رد می‌شود
       (تا مثلاً بازه‌ی بانک با بازه‌ی صندوق قاطی نشود).

    طبقِ درخواستِ صریح: بعدِ اولین سندِ شرکت، این تنظیمات دیگر قابلِ‌تغییر
    نیستند (تا کدهایِ ثبت‌شده‌ی موجود ناسازگار نشوند)."""
    with new_session() as session:
        dimension_type = session.get(DetailDimensionType, dimension_type_id)
        if dimension_type is None or dimension_type.company_id != company_id:
            raise ValueError("گروهِ تفصیلی نامعتبر است.")

        # importِ داخلِ تابع: journal_entries از detail_dimensions در سطحِ
        # ماژول import می‌کند، پس import سطحِ ماژول در جهتِ عکس یک وابستگیِ
        # چرخشی می‌ساخت.
        from peecha.services import journal_entries as je_service  # noqa: PLC0415

        if je_service.company_has_any_entries(company_id):
            raise ValueError("این شرکت سند دارد؛ تنظیماتِ کدینگِ تفصیلی دیگر قابلِ‌تغییر نیست.")

        digit_config_by_level = {
            r.level_no: r.code_length
            for r in session.scalars(
                select(DetailLevelDigitConfig).where(DetailLevelDigitConfig.company_id == company_id)
            ).all()
        }

        # بازه‌هایِ همه‌ی گروه‌هایِ دیگرِ همین شرکت که برایِ (هر) سطحی بازه
        # تنظیم کرده‌اند — برایِ چکِ هم‌پوشانی؛ گروه‌هایی که اصلاً بازه
        # تنظیم نکرده‌اند مشمولِ این چک نیستند.
        other_ranges = _fetch_other_ranges(session, company_id)

        session.execute(
            DetailGroupLevel.__table__.delete().where(
                DetailGroupLevel.dimension_type_id == dimension_type_id,
                DetailGroupLevel.person_group_id == person_group_id,
            )
        )
        for level_no, config in levels.items():
            if not (1 <= level_no <= MAX_DETAIL_LEVEL):
                raise ValueError(f"شماره‌ی سطح باید بینِ ۱ تا {MAX_DETAIL_LEVEL} باشد.")
            range_from = config.get("range_from")
            range_to = config.get("range_to")
            if range_from is not None and range_to is not None and range_from > range_to:
                raise ValueError("مقدارِ «از» نمی‌تواند بزرگ‌تر از «تا» باشد.")

            code_length = digit_config_by_level.get(level_no)
            if code_length is not None:
                max_value = 10**code_length - 1
                if range_from is not None and range_from > max_value:
                    raise ValueError(
                        f"مقدارِ «از» در سطحِ {level_no} نمی‌تواند بیشتر از {max_value} باشد "
                        f"(تعدادِ رقمِ سراسریِ این سطح {code_length} رقم است)."
                    )
                if range_to is not None and range_to > max_value:
                    raise ValueError(
                        f"مقدارِ «تا» در سطحِ {level_no} نمی‌تواند بیشتر از {max_value} باشد "
                        f"(تعدادِ رقمِ سراسریِ این سطح {code_length} رقم است)."
                    )

            if range_from is None and range_to is None:
                continue

            new_from = range_from if range_from is not None else 0
            new_to = range_to if range_to is not None else 999_999_999
            for other in other_ranges:
                if other.level_no != level_no:
                    continue
                if other.dimension_type_id == dimension_type_id and other.person_group_id == person_group_id:
                    continue
                other_from = other.range_from if other.range_from is not None else 0
                other_to = other.range_to if other.range_to is not None else 999_999_999
                if new_from <= other_to and other_from <= new_to:
                    other_label = _dimension_group_label(other.code, other.name)
                    raise ValueError(
                        f"بازه‌ی سطحِ {level_no} با بازه‌ی «{other_label}» هم‌پوشانی دارد؛ "
                        "بازه‌ی هر گروه باید مختصِ همان گروه بماند."
                    )

            session.add(
                DetailGroupLevel(
                    dimension_type_id=dimension_type_id,
                    person_group_id=person_group_id,
                    level_no=level_no,
                    range_from=range_from,
                    range_to=range_to,
                )
            )
        session.commit()


# --- فیلدهای اختصاصیِ قابل‌تعریفِ هر گروهِ تفصیلی --------------------------
# طبقِ درخواستِ صریح: «بتوان گروه تفصیلی هم تعریف کرد و ویژگی‌های یک گروه
# تفصیلی مثل مشتری را بگیرد» — برایِ گروه‌های تازه‌تعریف‌شده (مثلِ بانک/
# کالا)، کاربر خودش فیلدهای اختصاصی تعریف می‌کند (نه هاردکد در کد، مثلِ
# customer_details/supplier_details/personnel_details که مخصوصِ آن سه
# گروهِ سیستمی‌اند)؛ مقدارِشان در DetailAccount.extra_fields ذخیره می‌شود.


@dataclass
class GroupFieldRow:
    detail_group_field_id: int
    field_key: str
    label: str
    kind: str
    is_required: bool
    sort_order: int


def list_group_fields(dimension_type_id: int, person_group_id: int = 0) -> list[GroupFieldRow]:
    with new_session() as session:
        rows = session.scalars(
            select(DetailGroupField)
            .where(
                DetailGroupField.dimension_type_id == dimension_type_id,
                DetailGroupField.person_group_id == person_group_id,
            )
            .order_by(DetailGroupField.sort_order, DetailGroupField.detail_group_field_id)
        ).all()
        return [
            GroupFieldRow(
                detail_group_field_id=r.detail_group_field_id,
                field_key=r.field_key,
                label=r.label,
                kind=r.kind,
                is_required=r.is_required,
                sort_order=r.sort_order,
            )
            for r in rows
        ]


def set_group_fields(dimension_type_id: int, company_id: int, fields: list[dict], person_group_id: int = 0) -> None:
    """جایگزینیِ کاملِ فهرستِ فیلدهای اختصاصیِ این گروه — هر آیتمِ fields:
    {"field_key": ..., "label": ..., "kind": "text"|"decimal"|"date"|"boolean", "is_required": bool}.

    person_group_id غیرِصفر یعنی این فیلدها فقط مخصوصِ یکی از زیرگروه‌هایِ
    اشخاص‌اند (مثلاً فیلدِ اختصاصیِ تازه‌ای فقط برایِ مشتری، نه تامین‌کننده)."""
    with new_session() as session:
        dimension_type = session.get(DetailDimensionType, dimension_type_id)
        if dimension_type is None or dimension_type.company_id != company_id:
            raise ValueError("گروهِ تفصیلی نامعتبر است.")

        session.execute(
            DetailGroupField.__table__.delete().where(
                DetailGroupField.dimension_type_id == dimension_type_id,
                DetailGroupField.person_group_id == person_group_id,
            )
        )
        for i, f in enumerate(fields):
            kind = f["kind"]
            if kind not in _VALID_FIELD_KINDS:
                raise ValueError(f"نوعِ فیلدِ نامعتبر: {kind}")
            field_key = f["field_key"].strip()
            if not field_key:
                raise ValueError("کلیدِ فیلد نمی‌تواند خالی باشد.")
            session.add(
                DetailGroupField(
                    dimension_type_id=dimension_type_id,
                    person_group_id=person_group_id,
                    field_key=field_key,
                    label=f["label"].strip(),
                    kind=kind,
                    is_required=bool(f.get("is_required", False)),
                    sort_order=f.get("sort_order", i),
                )
            )
        session.commit()


# --- فهرستِ واحدِ همه‌ی تفصیلی‌ها (همه‌ی گروه‌ها، یک‌جا) ---------------------
# طبقِ درخواستِ صریح: «تمامِ تفصیلی‌ها در یک فرم» با ستونِ نوعِ تفصیلی و
# ستونِ سطح — این تابع مشتری/تامین‌کننده/پرسنل (از person_groups) و
# مرکزِهزینه/پروژه/گروه‌های دیگرِ کاربرساخته (از detail_dimension_types) را
# یک‌جا برمی‌گرداند؛ ردیفِ سیستمیِ «بدون تفصیلی» و خودِ نوعِ‌بُعدِ سیستمیِ
# PERSON (که خودش گروه نیست، فقط بستر است) کنار گذاشته می‌شوند.


@dataclass
class UnifiedDetailAccountRow:
    detail_account_id: int
    dimension_type_id: int
    group_name: str
    person_group_code: str | None  # CUSTOMER/SUPPLIER/PERSONNEL برایِ مسیریابیِ فرمِ درست؛ برایِ گروه‌های عمومی None
    level_no: int
    full_code: str
    name: str | None
    is_active: bool
    parent_detail_account_id: int | None = None
    code: str = ""
    color: str | None = None


def list_all_detail_accounts(company_id: int) -> list[UnifiedDetailAccountRow]:
    with new_session() as session:
        person_dimension_type_id = ensure_person_dimension(session, company_id)
        session.commit()

        all_rows = session.scalars(select(DetailAccount).where(DetailAccount.company_id == company_id)).all()
        full_codes = _compute_full_codes(all_rows)

        dimension_types_by_id = {
            t.dimension_type_id: t
            for t in session.scalars(
                select(DetailDimensionType).where(DetailDimensionType.company_id == company_id)
            ).all()
        }
        person_groups_by_id = {
            g.person_group_id: g
            for g in session.scalars(select(PersonGroup).where(PersonGroup.company_id == company_id)).all()
        }

        result: list[UnifiedDetailAccountRow] = []
        for r in all_rows:
            if r.dimension_type_id == person_dimension_type_id and r.code == NO_DETAIL_CODE:
                continue  # ردیفِ سیستمیِ «بدون تفصیلی» برایِ کاربر معنادار نیست
            person_group_code = None
            color = None
            if r.person_group_id is not None:
                group = person_groups_by_id.get(r.person_group_id)
                group_name = group.name if group is not None else "?"
                person_group_code = group.code if group is not None else None
                color = group.color if group is not None else None
            else:
                group = dimension_types_by_id.get(r.dimension_type_id)
                group_name = group.code if group is not None else "?"
                color = group.color if group is not None else None
            result.append(
                UnifiedDetailAccountRow(
                    detail_account_id=r.detail_account_id,
                    dimension_type_id=r.dimension_type_id,
                    group_name=group_name,
                    person_group_code=person_group_code,
                    level_no=r.level_no,
                    full_code=full_codes.get(r.detail_account_id, r.code),
                    name=r.name,
                    is_active=r.is_active,
                    parent_detail_account_id=r.parent_detail_account_id,
                    code=r.code,
                    color=color,
                )
            )
        result.sort(key=lambda row: (row.group_name, row.full_code))
        return result


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
            # همه‌ی ردیف‌های فعالِ این گروه (برایِ محاسبه‌ی full_code و
            # تشخیصِ برگ نیاز به کلِ درخت داریم، نه فقط برگ‌ها).
            all_rows = session.scalars(
                select(DetailAccount).where(DetailAccount.dimension_type_id == dimension_type_id)
            ).all()
            full_codes = _compute_full_codes(all_rows)
            parent_ids = {r.parent_detail_account_id for r in all_rows if r.parent_detail_account_id is not None}
            # طبقِ درخواستِ صریح: در سلسله‌مراتبِ تا ۴سطحی، فقط برگ‌ها
            # (پایین‌ترین سطح، مثلِ معینِ کدینگِ حسابداری) در سند قابل‌انتخاب‌اند؛
            # گروه‌های تختِ موجود (مشتری/مرکز هزینه و ...) چون فرزندی ندارند،
            # همه‌شان همچنان برگ محسوب می‌شوند — رفتارشان دست‌نخورده می‌ماند.
            leaf_rows = [r for r in all_rows if r.is_active and r.detail_account_id not in parent_ids]
            leaf_rows.sort(key=lambda r: r.code)
            result.append(
                RequiredDimension(
                    dimension_type_id=dimension_type_id,
                    code=dimension_type.code,
                    detail_accounts=[_to_detail_account_row(r, full_codes) for r in leaf_rows],
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
        full_codes = _compute_full_codes(rows)
        return [_to_detail_account_row(r, full_codes) for r in rows]


def list_active_persons(company_id: int) -> list[DetailAccountRow]:
    return [row for row in list_persons(company_id) if row.is_active]


# --- ۷ نوع‌بُعدِ «فرمِ خاص»یِ تازه (کالا/دارایی‌ثابت/بانک/صندوق/تنخواه/ -----
# مرکزِهزینه/پروژه) -----------------------------------------------------
# طبقِ درخواستِ صریح، این‌ها مثلِ مشتری/تامین‌کننده/پرسنل صفحه‌ی اختصاصیِ
# خودشان را دارند و برایِ هر شرکت به‌طورِ خودکار ساخته می‌شوند — با این
# تفاوت که (بر خلافِ مشتری/تامین‌کننده/پرسنل که همه زیرگروهِ نوع‌بُعدِ
# سیستمیِ PERSON‌اند) این ۷ تا خودشان نوع‌بُعدِ مستقل‌اند، چون کالا/
# دارایی‌ثابت/... اصلاً شخص نیستند. فیلدهایِ اختصاصیِ هرکدام (اگر لازم شد)
# از همان مکانیزمِ عمومیِ acc.detail_group_fields/extra_fields JSONB
# تعریف می‌شود، نه ستونِ SQL هاردکد.

INVENTORY_ITEM_CODE = "INVENTORY_ITEM"
FIXED_ASSET_CODE = "FIXED_ASSET"
BANK_ACCOUNT_CODE = "BANK_ACCOUNT"
CASH_BOX_CODE = "CASH_BOX"
PETTY_CASH_CODE = "PETTY_CASH"
COST_CENTER_CODE = "COST_CENTER"
PROJECT_CODE = "PROJECT"

SPECIALIZED_DIMENSION_LABELS: dict[str, str] = {
    INVENTORY_ITEM_CODE: "کالا",
    FIXED_ASSET_CODE: "دارایی ثابت",
    BANK_ACCOUNT_CODE: "بانک",
    CASH_BOX_CODE: "صندوق",
    PETTY_CASH_CODE: "تنخواه",
    COST_CENTER_CODE: "مرکز هزینه",
    PROJECT_CODE: "پروژه",
}


def ensure_specialized_dimensions(session, company_id: int) -> dict[str, int]:
    """این ۷ نوع‌بُعد را برای این شرکت تضمین می‌کند (اگر نبود می‌سازد) و
    نگاشتِ کد→شناسه را برمی‌گرداند — باید با همان session/تراکنشِ ساختِ
    شرکت صدا زده شود (مثلِ ensure_person_dimension/ensure_person_groups)؛
    برایِ شرکت‌هایِ موجود، 011_coding_settings.sql همین کار را یک‌بار
    برایِ همه انجام داده."""
    existing = {
        t.code: t.dimension_type_id
        for t in session.scalars(
            select(DetailDimensionType).where(DetailDimensionType.company_id == company_id)
        ).all()
    }
    for code in SPECIALIZED_DIMENSION_LABELS:
        if code not in existing:
            dimension_type = DetailDimensionType(company_id=company_id, code=code, is_active=True)
            session.add(dimension_type)
            session.flush()
            existing[code] = dimension_type.dimension_type_id
    return existing


def get_specialized_dimension_type_id(company_id: int, code: str) -> int:
    with new_session() as session:
        dimension_type_id = ensure_specialized_dimensions(session, company_id)[code]
        session.commit()
        return dimension_type_id


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
    color: str | None = None


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
        return [PersonGroupRow(g.person_group_id, g.code, g.name, g.is_active, g.color) for g in rows]


def get_person_group_id(company_id: int, code: str) -> int:
    with new_session() as session:
        groups = ensure_person_groups(session, company_id)
        session.commit()
        return groups[code]


def _group_row_to_person_row(
    detail_account: DetailAccount,
    extra,
    extra_field_names: tuple[str, ...],
    full_code: str,
) -> dict:
    row = {
        "detail_account_id": detail_account.detail_account_id,
        "code": detail_account.code,
        "name": detail_account.name,
        "is_active": detail_account.is_active,
        # فیلدهایِ اختصاصیِ عمومی/قابلِ‌پیکربندی (DetailGroupField)، جدا از
        # فیلدهایِ هاردکدِ SQL بالا — برایِ پیش‌پر کردنِ فرمِ ویرایش.
        "custom_fields": dict(detail_account.extra_fields or {}),
        # طبقِ درخواستِ صریح، مشتری/تامین‌کننده/پرسنل هم می‌توانند تا سقفِ
        # max_level_noِ خودشان سلسله‌مراتب داشته باشند (مثلِ کالا/بانک).
        "parent_detail_account_id": detail_account.parent_detail_account_id,
        "level_no": detail_account.level_no,
        "full_code": full_code,
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
        full_codes = _compute_full_codes(rows)
        detail_account_ids = [r.detail_account_id for r in rows]
        extras_by_id = {
            e.detail_account_id: e
            for e in session.scalars(
                select(detail_model).where(detail_model.detail_account_id.in_(detail_account_ids))
            ).all()
        }
        return [
            _group_row_to_person_row(
                r, extras_by_id.get(r.detail_account_id), extra_field_names, full_codes.get(r.detail_account_id, r.code)
            )
            for r in rows
        ]


def _create_group_person(
    company_id: int,
    group_code: str,
    code: str,
    name: str,
    detail_model,
    model_fields: dict,
    custom_fields: dict | None = None,
    parent_detail_account_id: int | None = None,
) -> int:
    with new_session() as session:
        dimension_type_id = ensure_person_dimension(session, company_id)
        person_group_id = ensure_person_groups(session, company_id)[group_code]

        max_level_no = _get_group_max_level_no(session, dimension_type_id, person_group_id)
        level_no = 1
        if parent_detail_account_id is not None:
            parent = session.get(DetailAccount, parent_detail_account_id)
            if (
                parent is None
                or parent.company_id != company_id
                or parent.dimension_type_id != dimension_type_id
                or parent.person_group_id != person_group_id
            ):
                raise ValueError("والدِ انتخاب‌شده نامعتبر است.")
            if parent.level_no >= max_level_no:
                raise ValueError(f"این گروه حداکثر {max_level_no} سطح می‌تواند داشته باشد.")
            level_no = parent.level_no + 1

        _validate_code_length(session, company_id, dimension_type_id, level_no, code.strip(), person_group_id=person_group_id)

        detail_account = DetailAccount(
            company_id=company_id,
            dimension_type_id=dimension_type_id,
            person_group_id=person_group_id,
            code=code.strip(),
            name=name.strip() or None,
            parent_detail_account_id=parent_detail_account_id,
            level_no=level_no,
            extra_fields=dict(custom_fields or {}),
        )
        session.add(detail_account)
        session.flush()
        session.add(detail_model(detail_account_id=detail_account.detail_account_id, **model_fields))
        session.commit()
        return detail_account.detail_account_id


def _update_group_person(
    detail_account_id: int,
    company_id: int,
    code: str,
    name: str,
    is_active: bool,
    detail_model,
    model_fields: dict,
    custom_fields: dict | None = None,
) -> None:
    with new_session() as session:
        detail_account = session.get(DetailAccount, detail_account_id)
        if detail_account is None or detail_account.company_id != company_id:
            raise ValueError("شخص نامعتبر است.")

        _validate_code_length(
            session,
            company_id,
            detail_account.dimension_type_id,
            detail_account.level_no,
            code.strip(),
            person_group_id=detail_account.person_group_id or 0,
        )

        detail_account.code = code.strip()
        detail_account.name = name.strip() or None
        detail_account.is_active = is_active
        if custom_fields is not None:
            detail_account.extra_fields = dict(custom_fields)

        extra = session.get(detail_model, detail_account_id)
        if extra is None:
            session.add(detail_model(detail_account_id=detail_account_id, **model_fields))
        else:
            for field_name, value in model_fields.items():
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

        # نکته‌یِ فنیِ کشف‌شده حینِ تست: چون هیچ relationship()یِ ORM بینِ
        # DetailAccount و این جدولِ ویژه تعریف نشده (فقط یک ستونِ FKِ خام)،
        # SQLAlchemy نمی‌تواند ترتیبِ حذف را خودکار بر اساسِ وابستگی مرتب
        # کند و ممکن است هر دو DELETE را در یک flush و به ترتیبِ اشتباه
        # بفرستد (parent قبل از child) — نقضِ FK. یک flush()ِ صریح بینِ
        # این دو حذف، ترتیب را تضمین می‌کند.
        extra = session.get(detail_model, detail_account_id)
        if extra is not None:
            session.delete(extra)
            session.flush()
        session.delete(detail_account)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError("این شخص در جایِ دیگری استفاده شده و قابلِ حذف نیست.") from exc


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


def create_customer(
    company_id: int,
    code: str,
    name: str,
    custom_fields: dict | None = None,
    parent_detail_account_id: int | None = None,
    **extra_fields,
) -> int:
    return _create_group_person(
        company_id, CUSTOMER_GROUP_CODE, code, name, CustomerDetail, extra_fields, custom_fields, parent_detail_account_id
    )


def update_customer(
    detail_account_id: int,
    company_id: int,
    code: str,
    name: str,
    is_active: bool,
    custom_fields: dict | None = None,
    **extra_fields,
) -> None:
    _update_group_person(detail_account_id, company_id, code, name, is_active, CustomerDetail, extra_fields, custom_fields)


def delete_customer(detail_account_id: int, company_id: int) -> None:
    _delete_group_person(detail_account_id, company_id, CustomerDetail)


def list_suppliers(company_id: int) -> list[dict]:
    return _list_group_persons(company_id, SUPPLIER_GROUP_CODE, SupplierDetail, _SUPPLIER_FIELDS)


def create_supplier(
    company_id: int,
    code: str,
    name: str,
    custom_fields: dict | None = None,
    parent_detail_account_id: int | None = None,
    **extra_fields,
) -> int:
    return _create_group_person(
        company_id, SUPPLIER_GROUP_CODE, code, name, SupplierDetail, extra_fields, custom_fields, parent_detail_account_id
    )


def update_supplier(
    detail_account_id: int,
    company_id: int,
    code: str,
    name: str,
    is_active: bool,
    custom_fields: dict | None = None,
    **extra_fields,
) -> None:
    _update_group_person(detail_account_id, company_id, code, name, is_active, SupplierDetail, extra_fields, custom_fields)


def delete_supplier(detail_account_id: int, company_id: int) -> None:
    _delete_group_person(detail_account_id, company_id, SupplierDetail)


def list_personnel(company_id: int) -> list[dict]:
    return _list_group_persons(company_id, PERSONNEL_GROUP_CODE, PersonnelDetail, _PERSONNEL_FIELDS)


def create_personnel(
    company_id: int,
    code: str,
    name: str,
    custom_fields: dict | None = None,
    parent_detail_account_id: int | None = None,
    **extra_fields,
) -> int:
    return _create_group_person(
        company_id, PERSONNEL_GROUP_CODE, code, name, PersonnelDetail, extra_fields, custom_fields, parent_detail_account_id
    )


def update_personnel(
    detail_account_id: int,
    company_id: int,
    code: str,
    name: str,
    is_active: bool,
    custom_fields: dict | None = None,
    **extra_fields,
) -> None:
    _update_group_person(detail_account_id, company_id, code, name, is_active, PersonnelDetail, extra_fields, custom_fields)


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
        return [PersonGroupRow(g.person_group_id, g.code, g.name, g.is_active, g.color) for g in groups]


def set_account_person_groups(account_id: int, company_id: int, person_group_ids: list[int]) -> None:
    with new_session() as session:
        account = session.get(ChartOfAccount, account_id)
        if account is None or account.company_id != company_id:
            raise ValueError("حساب نامعتبر است.")
        session.execute(AccountPersonGroup.__table__.delete().where(AccountPersonGroup.account_id == account_id))
        for person_group_id in person_group_ids:
            session.add(AccountPersonGroup(account_id=account_id, person_group_id=person_group_id))
        session.commit()
