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
from peecha.db.models.treasury import PettyCashFund, PettyCashFundLine
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import journal_entries as je_service
from peecha.services import treasury as treasury_service

PETTY_CASH_ADVANCE_MAPPING_KEY = "PETTY_CASH_ADVANCE"
ALLOWED_LINE_METHODS = ("CASH", "BANK", "CHECK")


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

    result = treasury_service.create_treasury_voucher(
        company_id, created_by_user_id, "PAYMENT", advance_account_id,
        {dim_type_id: custodian_detail_account_id}, opening_date, opening_description, method_lines,
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
    if method not in ALLOWED_LINE_METHODS:
        raise ValueError("روشِ ردیف نامعتبر است.")
    if amount <= 0:
        raise ValueError("مبلغِ ردیف باید مثبت باشد.")
    with new_session() as session:
        fund = session.get(PettyCashFund, fund_id)
        if fund is None:
            raise ValueError("تنخواه یافت نشد.")
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
            details={dim_type_id: custodian_detail_account_id},
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
