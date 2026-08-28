"""سرویسِ واقعیِ «تنخواه‌گردان» (طبقِ گزارشِ صریح — نه یک فرمِ پرداختِ
سرپوش‌دار): هر تنخواه‌دار (تفصیلیِ سطحِ آخرِ گروهِ «تنخواه») می‌تواند
هم‌زمان چند تنخواهِ باز داشته باشد، هرکدام با شماره‌یِ خودکارِ مستقلِ
خودش. افتتاحِ یک تنخواه یک سندِ پرداختِ واقعی است (واریزیِ اولیه به
تنخواه‌دار)؛ ردیف‌هایی که در دورانِ بازبودن ثبت می‌شوند هیچ سندِ
حسابداری‌ای نمی‌سازند؛ بستنِ تنخواه یک سندِ موقتِ پیش‌نویس می‌سازد که
تنخواه‌دار را به‌اندازه‌یِ جمعِ ردیف‌ها بستانکار می‌کند (مثلِ تسویه‌حساب)."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.treasury import PettyCashFund, PettyCashFundExtraDetail, PettyCashFundLine
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import journal_entries as je_service
from peecha.services import treasury as treasury_service

PETTY_CASH_ADVANCE_MAPPING_KEY = "PETTY_CASH_ADVANCE"
ALLOWED_LINE_METHODS = ("CASH", "BANK", "CHECK", "DISCOUNT", "NETTING")


@dataclass
class ExtraDetailRequirement:
    """یک بُعد/گروهِ شخصِ اضافیِ الزامیِ حسابِ پیش‌پرداختِ تنخواه — یعنی
    چیزی غیر از خودِ بُعدِ تنخواه‌دار که با انتخابِ تنخواه‌دار در بالای
    فرم قبلاً پوشش داده می‌شود."""

    dimension_type_id: int
    label: str
    options: list


_HEADER_SHARED_DIMENSION_CODES = (dimensions_service.COST_CENTER_CODE, dimensions_service.PROJECT_CODE)


def get_advance_shared_dimension_options(company_id: int, code: str) -> tuple[bool, list]:
    """طبقِ هم‌الگو با هدرِ فرمِ دریافت/پرداخت: مرکزِ هزینه/پروژه فیلدهایِ
    همیشه‌حاضرِ هدرند (فقط enable/disable می‌شوند، نه پویا مثلِ بقیه‌یِ
    ابعادِ اضافی) — تا کاربر بتواند شرح/مرکزِ هزینه/پروژه را در یک ردیفِ
    واحد ببیند، دقیقاً مثلِ فرمِ دریافت/پرداخت. خروجی: (آیا الزامی است, گزینه‌ها)."""
    dim_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, code)
    if dim_type_id is None:
        return False, []
    options = dimensions_service.list_leaf_detail_accounts(company_id, dim_type_id)
    advance_account_id = treasury_service.get_account_mapping(company_id, PETTY_CASH_ADVANCE_MAPPING_KEY)
    is_required = False
    if advance_account_id is not None:
        required = dimensions_service.get_required_dimensions_for_account(advance_account_id)
        is_required = any(r.dimension_type_id == dim_type_id for r in required)
    return is_required, options


def get_advance_extra_requirements(company_id: int) -> list[ExtraDetailRequirement]:
    """طبقِ رفعِ باگِ واقعی («برایِ حساب X انتخابِ گروه‌هایِ تفصیلیِ الزامی
    فراموش شده است» حتی وقتی روش/تفصیلیِ ردیف‌ها درست بودند): حسابِ
    پیش‌پرداختِ تنخواه ممکن است، جدا از بُعدِ تنخواه‌دار، بُعد/گروهِ شخصِ
    دیگری هم رویش الزامی شده باشد. قبلاً open_fund/close_fund فقط بُعدِ
    تنخواه‌دار را می‌فرستادند و هر نیازِ دیگری را نادیده می‌گرفتند — نتیجه
    این بود که create_journal_entry همیشه رد می‌کرد، مستقل از این‌که
    کاربر چه روشی/تفصیلی‌ای در ردیف‌ها انتخاب کرده بود. مرکزِ هزینه/پروژه
    این‌جا نیستند — آن‌ها فیلدهایِ همیشه‌حاضرِ هدرند (get_advance_shared_dimension_options)."""
    advance_account_id = treasury_service.get_account_mapping(company_id, PETTY_CASH_ADVANCE_MAPPING_KEY)
    if advance_account_id is None:
        return []
    petty_cash_dim_id = dimensions_service.get_specialized_dimension_type_id(
        company_id, dimensions_service.PETTY_CASH_CODE
    )
    shared_type_ids = {
        dimensions_service.get_specialized_dimension_type_id(company_id, code)
        for code in _HEADER_SHARED_DIMENSION_CODES
    }
    requirements: list[ExtraDetailRequirement] = []
    for dim in dimensions_service.get_required_dimensions_for_account(advance_account_id):
        if dim.dimension_type_id == petty_cash_dim_id or dim.dimension_type_id in shared_type_ids:
            continue
        label = dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(dim.code, dim.code)
        requirements.append(ExtraDetailRequirement(dim.dimension_type_id, label, dim.detail_accounts))
    person_groups = dimensions_service.get_required_person_groups_for_account(advance_account_id)
    if person_groups:
        person_dim_id = dimensions_service.get_person_dimension_type_id(company_id)
        group_ids = {g.person_group_id for g in person_groups}
        persons = [p for p in dimensions_service.list_active_persons(company_id) if p.person_group_id in group_ids]
        requirements.append(ExtraDetailRequirement(person_dim_id, "تفصیلیِ اشخاص", persons))
    return requirements


def list_custodians(company_id: int) -> list[dimensions_service.DetailAccountRow]:
    """تفصیلی‌هایِ سطحِ آخرِ گروهِ «تنخواه» — همان‌هایی که می‌توانند
    تنخواه‌دار باشند."""
    dim_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.PETTY_CASH_CODE)
    return dimensions_service.list_leaf_detail_accounts(company_id, dim_type_id)


def _custodian_label_map(company_id: int) -> dict[int, str]:
    return {r.detail_account_id: (f"{r.full_code} — {r.name}" if r.name else r.full_code) for r in list_custodians(company_id)}


@dataclass
class PettyCashFundRow:
    fund_id: int
    company_id: int
    custodian_detail_account_id: int
    custodian_label: str
    fund_no: int
    status: str
    opening_amount: decimal.Decimal
    opening_date: datetime.date
    opening_journal_entry_id: int
    closing_date: datetime.date | None
    closing_journal_entry_id: int | None


def _fund_row(f: PettyCashFund, labels: dict[int, str]) -> PettyCashFundRow:
    return PettyCashFundRow(
        f.fund_id, f.company_id, f.custodian_detail_account_id,
        labels.get(f.custodian_detail_account_id, str(f.custodian_detail_account_id)),
        f.fund_no, f.status, f.opening_amount, f.opening_date, f.opening_journal_entry_id,
        f.closing_date, f.closing_journal_entry_id,
    )


def list_funds(
    company_id: int, custodian_detail_account_id: int | None = None, status: str | None = None
) -> list[PettyCashFundRow]:
    with new_session() as session:
        query = select(PettyCashFund).where(PettyCashFund.company_id == company_id)
        if custodian_detail_account_id is not None:
            query = query.where(PettyCashFund.custodian_detail_account_id == custodian_detail_account_id)
        if status is not None:
            query = query.where(PettyCashFund.status == status)
        rows = session.scalars(query.order_by(PettyCashFund.custodian_detail_account_id, PettyCashFund.fund_no)).all()
    labels = _custodian_label_map(company_id)
    return [_fund_row(f, labels) for f in rows]


def get_fund(fund_id: int) -> PettyCashFundRow | None:
    with new_session() as session:
        f = session.get(PettyCashFund, fund_id)
        if f is None:
            return None
        labels = _custodian_label_map(f.company_id)
        return _fund_row(f, labels)


def open_fund(
    company_id: int,
    created_by_user_id: int,
    custodian_detail_account_id: int,
    opening_date: datetime.date,
    opening_description: str,
    method_lines: list[treasury_service.MethodLine],
    extra_details: dict[int, int] | None = None,
) -> tuple[int, je_service.JournalEntryResult]:
    dim_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.PETTY_CASH_CODE)
    leaves = {r.detail_account_id for r in dimensions_service.list_leaf_detail_accounts(company_id, dim_type_id)}
    if custodian_detail_account_id not in leaves:
        raise ValueError("تنخواه‌دار باید یک تفصیلیِ سطحِ آخرِ گروهِ «تنخواه» باشد.")
    if not method_lines:
        raise ValueError("برایِ افتتاحِ تنخواه حداقل یک ردیفِ روشِ پرداخت لازم است.")
    advance_account_id = treasury_service.get_account_mapping(company_id, PETTY_CASH_ADVANCE_MAPPING_KEY)
    if advance_account_id is None:
        raise ValueError("حسابِ پیش‌پرداختِ تنخواه در تنظیماتِ خزانه‌داری مشخص نشده است.")
    opening_amount = sum((ml.amount for ml in method_lines), decimal.Decimal(0))
    if opening_amount <= 0:
        raise ValueError("مبلغِ افتتاحِ تنخواه باید مثبت باشد.")

    extra_details = dict(extra_details or {})
    requirements = get_advance_extra_requirements(company_id)
    missing = [r.label for r in requirements if r.dimension_type_id not in extra_details]
    if missing:
        raise ValueError(
            "برایِ حسابِ پیش‌پرداختِ تنخواه انتخابِ " + "، ".join(missing) + " الزامی است."
        )
    counterparty_details = {dim_type_id: custodian_detail_account_id, **extra_details}

    result = treasury_service.create_treasury_voucher(
        company_id, created_by_user_id, "PAYMENT", advance_account_id,
        counterparty_details, opening_date, opening_description, method_lines,
    )

    with new_session() as session:
        max_no = session.scalar(
            select(func.max(PettyCashFund.fund_no)).where(
                PettyCashFund.custodian_detail_account_id == custodian_detail_account_id
            )
        ) or 0
        fund = PettyCashFund(
            company_id=company_id, custodian_detail_account_id=custodian_detail_account_id, fund_no=max_no + 1,
            status="OPEN", opening_amount=opening_amount, opening_date=opening_date,
            opening_journal_entry_id=result.journal_entry_id, created_by_user_id=created_by_user_id,
        )
        session.add(fund)
        session.flush()
        for extra_dim_type_id, extra_detail_account_id in extra_details.items():
            session.add(
                PettyCashFundExtraDetail(
                    fund_id=fund.fund_id, dimension_type_id=extra_dim_type_id, detail_account_id=extra_detail_account_id
                )
            )
        session.commit()
        return fund.fund_id, result


@dataclass
class PettyCashFundLineRow:
    line_id: int
    fund_id: int
    method: str
    amount: decimal.Decimal
    description: str | None
    detail_account_id: int | None
    check_no: str | None
    check_due_date: datetime.date | None
    line_date: datetime.date


def list_lines(fund_id: int) -> list[PettyCashFundLineRow]:
    with new_session() as session:
        rows = session.scalars(
            select(PettyCashFundLine).where(PettyCashFundLine.fund_id == fund_id).order_by(PettyCashFundLine.line_id)
        ).all()
        return [
            PettyCashFundLineRow(
                r.line_id, r.fund_id, r.method, r.amount, r.description, r.detail_account_id,
                r.check_no, r.check_due_date, r.line_date,
            )
            for r in rows
        ]


def is_allowed_line_method(company_id: int, method: str) -> bool:
    """طبقِ آیتمِ ۹: علاوه بر نقد/بانک/چک/تخفیف/تهاتر، روش‌هایِ سفارشیِ
    فعالِ همین شرکت (کدشان با CUSTOM_ شروع می‌شود) هم مجازند — دقیقاً
    همان روش‌هایِ پرداختیِ فرمِ دریافت/پرداخت، به‌جز خرجِ چک
    (CHECK_DISBURSEMENT) که به‌دلیلِ منطقِ حسابداریِ کاملاً متفاوتش
    (بازنشستگیِ یک چکِ دریافتیِ خاص، نه یک ردیفِ بدهکارِ ساده) عمداً از
    این فرم خارج نگه داشته شده است."""
    if method in ALLOWED_LINE_METHODS:
        return True
    if method.startswith("CUSTOM_"):
        active_codes = {
            f"CUSTOM_{cm.custom_method_id}"
            for cm in treasury_service.list_custom_methods(company_id, "PAYMENT", active_only=True)
        }
        return method in active_codes
    return False


def add_line(
    fund_id: int,
    method: str,
    amount: decimal.Decimal,
    description: str | None,
    *,
    detail_account_id: int | None = None,
    check_no: str | None = None,
    check_due_date: datetime.date | None = None,
    line_date: datetime.date | None = None,
) -> int:
    if amount <= 0:
        raise ValueError("مبلغِ ردیف باید مثبت باشد.")
    with new_session() as session:
        fund = session.get(PettyCashFund, fund_id)
        if fund is None:
            raise ValueError("تنخواه یافت نشد.")
        if not is_allowed_line_method(fund.company_id, method):
            raise ValueError("روشِ ردیف نامعتبر است.")
        if fund.status != "OPEN":
            raise ValueError("این تنخواه بسته شده و دیگر قابلِ ثبتِ ردیفِ تازه نیست.")
        line = PettyCashFundLine(
            fund_id=fund_id, method=method, amount=amount, description=(description or None),
            detail_account_id=detail_account_id, check_no=check_no, check_due_date=check_due_date,
            line_date=line_date or datetime.date.today(),
        )
        session.add(line)
        session.commit()
        return line.line_id


def delete_line(line_id: int) -> None:
    with new_session() as session:
        line = session.get(PettyCashFundLine, line_id)
        if line is None:
            return
        fund = session.get(PettyCashFund, line.fund_id)
        if fund is not None and fund.status != "OPEN":
            raise ValueError("این تنخواه بسته شده و دیگر قابلِ ویرایش نیست.")
        session.delete(line)
        session.commit()


def close_fund(
    fund_id: int, created_by_user_id: int, closing_date: datetime.date, closing_description: str | None = None
) -> je_service.JournalEntryResult:
    with new_session() as session:
        fund = session.get(PettyCashFund, fund_id)
        if fund is None:
            raise ValueError("تنخواه یافت نشد.")
        if fund.status != "OPEN":
            raise ValueError("این تنخواه قبلاً بسته شده است.")
        lines = session.scalars(select(PettyCashFundLine).where(PettyCashFundLine.fund_id == fund_id)).all()
        if not lines:
            raise ValueError("برایِ بستنِ تنخواه حداقل یک ردیف لازم است.")
        company_id = fund.company_id
        custodian_detail_account_id = fund.custodian_detail_account_id
        fund_no = fund.fund_no
        line_data = [(l.method, l.amount, l.detail_account_id) for l in lines]
        extra_rows = session.scalars(
            select(PettyCashFundExtraDetail).where(PettyCashFundExtraDetail.fund_id == fund_id)
        ).all()
        extra_details = {r.dimension_type_id: r.detail_account_id for r in extra_rows}

    advance_account_id = treasury_service.get_account_mapping(company_id, PETTY_CASH_ADVANCE_MAPPING_KEY)
    if advance_account_id is None:
        raise ValueError("حسابِ پیش‌پرداختِ تنخواه در تنظیماتِ خزانه‌داری مشخص نشده است.")
    dim_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.PETTY_CASH_CODE)

    # همان روش‌هایِ پرداختِ ازپیش‌تعریف‌شده (PAYMENT_CASH/PAYMENT_BANK/
    # PAYMENT_CHECK) برایِ حل‌کردنِ حسابِ هر ردیف — طبقِ درخواستِ صریحِ کاربر.
    debit_lines: dict[tuple[int, int | None], decimal.Decimal] = {}
    for method, amount, detail_account_id in line_data:
        account_id = treasury_service.get_account_mapping(company_id, f"PAYMENT_{method}")
        if account_id is None:
            raise ValueError(f"حسابِ روشِ «{method}» در تنظیماتِ پرداخت مشخص نشده است.")
        key = (account_id, detail_account_id)
        debit_lines[key] = debit_lines.get(key, decimal.Decimal(0)) + amount

    total = sum((amount for _, amount, _ in line_data), decimal.Decimal(0))
    description = closing_description or f"بستنِ تنخواهِ شماره‌یِ {fund_no}"

    def to_details(detail_account_id: int | None) -> dict[int, int]:
        if detail_account_id is None:
            return {}
        with new_session() as session:
            da = session.get(DetailAccount, detail_account_id)
            return {da.dimension_type_id: detail_account_id} if da is not None else {}

    lines_input = [
        je_service.LineInput(
            account_id=account_id, description=description, debit=amount, credit=decimal.Decimal(0),
            details=to_details(detail_account_id),
        )
        for (account_id, detail_account_id), amount in debit_lines.items()
    ] + [
        je_service.LineInput(
            account_id=advance_account_id, description=description, debit=decimal.Decimal(0), credit=total,
            details={dim_type_id: custodian_detail_account_id, **extra_details},
        )
    ]

    je_result = je_service.create_journal_entry(
        company_id, created_by_user_id, closing_date, description, lines_input,
        entry_type_code="TANKHAH", as_draft=True,
    )

    with new_session() as session:
        fund = session.get(PettyCashFund, fund_id)
        fund.status = "CLOSED"
        fund.closing_date = closing_date
        fund.closing_journal_entry_id = je_result.journal_entry_id
        session.commit()

    return je_result


def delete_fund(fund_id: int, company_id: int, changed_by_user_id: int) -> None:
    """طبقِ گزارشِ صریح («سندِ صادرشده‌یِ تنخواه را نمی‌توان حذف کرد»):
    چون petty_cash_funds با کلیدِ خارجیِ الزامی به سندِ افتتاح (و اگر
    بسته باشد، سندِ بستن) اشاره می‌کند، تلاش برایِ حذفِ مستقیمِ آن سند از
    صفحه‌ی عمومیِ اسناد همیشه با خطایِ خامِ کلیدِ خارجی رد می‌شد (نه یک
    پیامِ روشن). این تابع، هم‌الگو با delete_received_check/
    delete_issued_check (که پیش از حذفِ سندِ حسابداری، ابتدا رکوردِ
    وابسته را پاک می‌کنند)، کلِ تنخواه — ردیف‌ها، تفصیلی‌هایِ اضافی، و در
    آخر خودِ سند(هایِ) حسابداری — را یک‌جا حذف می‌کند؛ فقط وقتی همه‌ی
    سندهایِ مربوطه هنوز موقت/پیش‌نویس‌اند (وگرنه ابتدا اعتبارسنجی می‌شود،
    پیش از دست‌زدن به هیچ رکوردی)."""
    from peecha.db.models.accounting import FiscalYear, JournalEntry, JournalEntryStatus
    from peecha.services.journal_entries import _ensure_fiscal_period_open, _ensure_fiscal_year_open

    with new_session() as session:
        fund = session.get(PettyCashFund, fund_id)
        if fund is None or fund.company_id != company_id:
            raise ValueError("تنخواه یافت نشد.")
        entry_ids = [fund.opening_journal_entry_id]
        if fund.closing_journal_entry_id is not None:
            entry_ids.append(fund.closing_journal_entry_id)
        for entry_id in entry_ids:
            entry = session.get(JournalEntry, entry_id)
            if entry is None:
                continue
            status = session.get(JournalEntryStatus, entry.status_id)
            if status is None or status.code not in ("TEMPORARY", "DRAFT"):
                raise ValueError("این تنخواه دیگر قابلِ حذف نیست، چون سندِ حسابداریِ آن به وضعیتِ دائم رسیده است.")
            fiscal_year = session.get(FiscalYear, entry.fiscal_year_id)
            if fiscal_year is not None:
                _ensure_fiscal_year_open(fiscal_year)
                _ensure_fiscal_period_open(session, fiscal_year.fiscal_year_id, entry.document_date)

        opening_journal_entry_id = fund.opening_journal_entry_id
        closing_journal_entry_id = fund.closing_journal_entry_id
        session.execute(PettyCashFundExtraDetail.__table__.delete().where(PettyCashFundExtraDetail.fund_id == fund_id))
        session.execute(PettyCashFundLine.__table__.delete().where(PettyCashFundLine.fund_id == fund_id))
        session.delete(fund)
        session.commit()

    if closing_journal_entry_id is not None:
        je_service.delete_journal_entry(closing_journal_entry_id, company_id, changed_by_user_id)
    je_service.delete_journal_entry(opening_journal_entry_id, company_id, changed_by_user_id)
