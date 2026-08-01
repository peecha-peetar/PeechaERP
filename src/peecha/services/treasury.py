"""سرویسِ خزانه‌داری: نگاشتِ حساب‌ها، دسته‌چک، سندِ چندروشیِ دریافت/پرداخت
(نقد/بانک/چک/تخفیف در یک سندِ واحد)، و چرخه‌یِ عمرِ چک‌هایِ دریافتی/پرداختی
— همه رویِ همان موتورِ اسنادِ حسابداری (journal_entries.py) و ابعادِ
تفصیلیِ موجود (detail_dimensions.py)، بدونِ موتورِ موازیِ تازه."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.accounting import (
    AccountDetailDimension,
    ChartOfAccount,
    DetailAccount,
    JournalEntryLine,
    JournalEntryLineDetail,
)
from peecha.db.models.treasury import Checkbook, CheckStatus, IssuedCheck, ReceivedCheck, TreasuryAccountMapping
from peecha.services import audit as audit_service
from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import journal_entries as je_service

MAPPING_KEYS = [
    "RECEIPT_CASH",
    "RECEIPT_BANK",
    "RECEIPT_CHECK",
    "RECEIPT_DISCOUNT",
    "PAYMENT_CASH",
    "PAYMENT_BANK",
    "PAYMENT_CHECK",
    "PAYMENT_DISCOUNT",
]

MAPPING_LABELS: dict[str, str] = {
    "RECEIPT_CASH": "دریافتِ نقدی",
    "RECEIPT_BANK": "دریافتِ بانکی",
    "RECEIPT_CHECK": "چک‌هایِ دریافتنی (در جریانِ وصول)",
    "RECEIPT_DISCOUNT": "تخفیفاتِ نقدیِ داده‌شده",
    "PAYMENT_CASH": "پرداختِ نقدی",
    "PAYMENT_BANK": "پرداختِ بانکی",
    "PAYMENT_CHECK": "چک‌هایِ پرداختنی",
    "PAYMENT_DISCOUNT": "تخفیفاتِ نقدیِ دریافت‌شده",
}

METHOD_CODES = ("CASH", "BANK", "CHECK", "DISCOUNT")


# --- تنظیماتِ نگاشتِ حساب‌ها -------------------------------------------------


@dataclass
class AccountMappingRow:
    mapping_key: str
    label: str
    account_id: int | None
    account_label: str | None


def list_account_mappings(company_id: int) -> list[AccountMappingRow]:
    with new_session() as session:
        rows = {
            m.mapping_key: m.account_id
            for m in session.scalars(
                select(TreasuryAccountMapping).where(TreasuryAccountMapping.company_id == company_id)
            ).all()
        }
    accounts_by_id = {a.account_id: f"{a.full_code} — {a.name}" for a in coa_service.list_accounts(company_id)}
    return [
        AccountMappingRow(
            mapping_key=key,
            label=MAPPING_LABELS[key],
            account_id=rows.get(key),
            account_label=accounts_by_id.get(rows.get(key)) if rows.get(key) is not None else None,
        )
        for key in MAPPING_KEYS
    ]


def set_account_mapping(company_id: int, mapping_key: str, account_id: int) -> None:
    if mapping_key not in MAPPING_LABELS:
        raise ValueError("کلیدِ نگاشتِ نامعتبر است.")
    with new_session() as session:
        existing = session.get(TreasuryAccountMapping, (company_id, mapping_key))
        if existing is None:
            session.add(TreasuryAccountMapping(company_id=company_id, mapping_key=mapping_key, account_id=account_id))
        else:
            existing.account_id = account_id
        session.commit()


def _get_mapped_account_id(session, company_id: int, mapping_key: str) -> int:
    mapping = session.get(TreasuryAccountMapping, (company_id, mapping_key))
    if mapping is None:
        raise ValueError(
            f"حسابِ «{MAPPING_LABELS[mapping_key]}» هنوز در تنظیماتِ خزانه‌داری مشخص نشده است."
        )
    return mapping.account_id


# --- دسته‌چک -----------------------------------------------------------------


@dataclass
class CheckbookRow:
    checkbook_id: int
    bank_account_detail_id: int
    bank_account_label: str
    start_no: int
    end_no: int
    next_no: int
    is_active: bool


def list_checkbooks(company_id: int, bank_account_detail_id: int | None = None) -> list[CheckbookRow]:
    with new_session() as session:
        query = select(Checkbook).where(Checkbook.company_id == company_id)
        if bank_account_detail_id is not None:
            query = query.where(Checkbook.bank_account_detail_id == bank_account_detail_id)
        rows = session.scalars(query.order_by(Checkbook.checkbook_id)).all()
        bank_detail_ids = {r.bank_account_detail_id for r in rows}
        labels: dict[int, str] = {}
        if bank_detail_ids:
            labels = {
                d.detail_account_id: d.name or d.code
                for d in session.scalars(
                    select(DetailAccount).where(DetailAccount.detail_account_id.in_(bank_detail_ids))
                ).all()
            }
        return [
            CheckbookRow(
                checkbook_id=r.checkbook_id,
                bank_account_detail_id=r.bank_account_detail_id,
                bank_account_label=labels.get(r.bank_account_detail_id, ""),
                start_no=r.start_no,
                end_no=r.end_no,
                next_no=r.next_no,
                is_active=r.is_active,
            )
            for r in rows
        ]


def create_checkbook(company_id: int, bank_account_detail_id: int, start_no: int, end_no: int) -> CheckbookRow:
    if start_no > end_no:
        raise ValueError("شماره‌یِ شروع نمی‌تواند از شماره‌یِ پایان بزرگ‌تر باشد.")
    with new_session() as session:
        detail = session.get(DetailAccount, bank_account_detail_id)
        if detail is None or detail.company_id != company_id:
            raise ValueError("حسابِ بانکیِ انتخاب‌شده نامعتبر است.")
        checkbook = Checkbook(
            company_id=company_id,
            bank_account_detail_id=bank_account_detail_id,
            start_no=start_no,
            end_no=end_no,
            next_no=start_no,
            is_active=True,
        )
        session.add(checkbook)
        session.commit()
        session.refresh(checkbook)
        return CheckbookRow(
            checkbook_id=checkbook.checkbook_id,
            bank_account_detail_id=bank_account_detail_id,
            bank_account_label=detail.name or detail.code,
            start_no=start_no,
            end_no=end_no,
            next_no=start_no,
            is_active=True,
        )


def set_checkbook_active(checkbook_id: int, company_id: int, is_active: bool) -> None:
    with new_session() as session:
        checkbook = session.get(Checkbook, checkbook_id)
        if checkbook is None or checkbook.company_id != company_id:
            raise ValueError("دسته‌چک نامعتبر است.")
        checkbook.is_active = is_active
        session.commit()


def _allocate_check_no(session, checkbook_id: int, company_id: int) -> tuple[str, int]:
    checkbook = session.get(Checkbook, checkbook_id)
    if checkbook is None or checkbook.company_id != company_id:
        raise ValueError("دسته‌چک نامعتبر است.")
    if not checkbook.is_active:
        raise ValueError("این دسته‌چک غیرِفعال است.")
    if checkbook.next_no > checkbook.end_no:
        raise ValueError("شماره‌هایِ این دسته‌چک تمام شده است.")
    allocated = checkbook.next_no
    checkbook.next_no += 1
    return str(allocated), checkbook.bank_account_detail_id


_SETTLEMENT_DIMENSION_CODES = (
    dimensions_service.CASH_BOX_CODE,
    dimensions_service.BANK_ACCOUNT_CODE,
    dimensions_service.PETTY_CASH_CODE,
)
# طبقِ درخواستِ صریح: مرکزِ هزینه/پروژه (اگر رویِ حسابِ طرف‌حساب الزامی
# باشند) باید بینِ همه‌ی ردیف‌هایِ یک سند مشترک باشند — نه فقط ردیفِ
# طرف‌حساب — چون این دو نوع‌بُعد ویژگیِ خودِ رویدادِ مالی‌اند (این تراکنش
# مربوط به کدام مرکزِ هزینه/پروژه است)، نه ویژگیِ یک طرفِ حسابِ خاص.
_SHARED_DIMENSION_CODES = (dimensions_service.COST_CENTER_CODE, dimensions_service.PROJECT_CODE)


def list_counterparty_account_options(company_id: int) -> list[tuple[int, str]]:
    """حساب‌هایِ قابلِ‌انتخاب به‌عنوانِ «طرفِ حساب» در فرمِ دریافت/پرداخت —
    طبقِ گزارشِ صریح: معین‌هایی که تفصیلیِ الزامی‌شان صندوق/بانک/تنخواه
    است اصلاً نباید این‌جا نمایش داده شوند، چون خودشان از طریقِ ردیف‌هایِ
    روش (نقد/بانک) مدیریت می‌شوند، نه به‌عنوانِ طرفِ حساب."""
    excluded_type_ids = {
        dimensions_service.get_specialized_dimension_type_id(company_id, code) for code in _SETTLEMENT_DIMENSION_CODES
    }
    with new_session() as session:
        excluded_account_ids = set(
            session.scalars(
                select(AccountDetailDimension.account_id).where(
                    AccountDetailDimension.dimension_type_id.in_(excluded_type_ids)
                )
            ).all()
        )
    return [
        (a.account_id, f"{a.full_code} — {a.name}")
        for a in coa_service.list_postable_accounts(company_id)
        if a.account_id not in excluded_account_ids
    ]


# --- سندِ چندروشیِ دریافت/پرداخت ---------------------------------------------


@dataclass
class MethodLine:
    """یک ردیفِ فرمِ دریافت/پرداخت — روش + مبلغ + فیلدهایِ مخصوصِ همان روش.
    detail_account_id: برایِ نقد (کدام صندوق/تنخواه) یا بانک (کدام حسابِ
    بانکی) — فقط اگر حسابِ نگاشت‌شده نیازِ تفصیلی داشته باشد و بیش از یک
    گزینه موجود باشد؛ در غیرِ این صورت None."""

    method: str
    amount: decimal.Decimal
    description: str = ""
    detail_account_id: int | None = None
    check_no: str | None = None
    check_bank_name: str | None = None
    check_due_date: datetime.date | None = None
    check_party_name: str | None = None
    checkbook_id: int | None = None  # فقط پرداختِ چک، اگر از یک دسته‌چک صادر می‌شود


def create_treasury_voucher(
    company_id: int,
    created_by_user_id: int,
    direction: str,
    counterparty_account_id: int,
    counterparty_details: dict[int, int],
    document_date: datetime.date,
    description: str,
    method_lines: list[MethodLine],
    alternative_number: str = "",
) -> je_service.JournalEntryResult:
    """طبقِ طرحِ تاییدشده: یک طرف‌حساب (بستانکار در دریافت، بدهکار در
    پرداخت) و چند ردیفِ روش (نقد/بانک/چک/تخفیف) که هرکدام طبقِ نگاشتِ
    تنظیماتِ خزانه‌داری به حسابِ کلِ خودش می‌رود — همه در یک سندِ حسابداریِ
    واحد، رویِ همان create_journal_entry موجود."""
    if direction not in ("RECEIPT", "PAYMENT"):
        raise ValueError("جهتِ سند نامعتبر است.")
    if not method_lines:
        raise ValueError("حداقل یک ردیفِ روش (نقد/بانک/چک/تخفیف) لازم است.")
    for ml in method_lines:
        if ml.method not in METHOD_CODES:
            raise ValueError("روشِ ردیف نامعتبر است.")
        if ml.amount <= 0:
            raise ValueError("مبلغِ هر ردیف باید مثبت باشد.")

    total = sum((ml.amount for ml in method_lines), decimal.Decimal(0))

    # طبقِ گزارشِ صریح: اگر رویِ حسابِ طرف‌حساب مرکزِ هزینه/پروژه الزامی
    # باشد، همان مقدارِ انتخاب‌شده باید بینِ همه‌ی ردیف‌هایِ سند (نه فقط
    # ردیفِ طرف‌حساب) مشترک باشد.
    shared_type_ids = {
        dimensions_service.get_specialized_dimension_type_id(company_id, code) for code in _SHARED_DIMENSION_CODES
    }
    shared_details = {k: v for k, v in counterparty_details.items() if k in shared_type_ids}

    with new_session() as session:
        detail_ids = {ml.detail_account_id for ml in method_lines if ml.detail_account_id is not None}
        dimension_type_by_detail_id: dict[int, int] = {}
        if detail_ids:
            dimension_type_by_detail_id = dict(
                session.execute(
                    select(DetailAccount.detail_account_id, DetailAccount.dimension_type_id).where(
                        DetailAccount.detail_account_id.in_(detail_ids)
                    )
                ).all()
            )

        # allocate کردنِ شماره‌یِ چکِ پرداختی از دسته‌چک (اگر مشخص شده) باید
        # پیش از ساختِ ردیف‌هایِ سند انجام شود — چون حسابِ بانکیِ همان
        # دسته‌چک، حسابِ تفصیلیِ ردیفِ چک هم می‌شود (details لازمش دارد).
        allocated_check_nos: dict[int, str] = {}
        for index, ml in enumerate(method_lines):
            if ml.method == "CHECK" and direction == "PAYMENT" and ml.checkbook_id is not None:
                check_no, bank_detail_id = _allocate_check_no(session, ml.checkbook_id, company_id)
                allocated_check_nos[index] = check_no
                if ml.detail_account_id is None:
                    ml.detail_account_id = bank_detail_id
                    dimension_type_by_detail_id[bank_detail_id] = session.scalar(
                        select(DetailAccount.dimension_type_id).where(DetailAccount.detail_account_id == bank_detail_id)
                    )
        # طبقِ همین دلیل، commit این تخصیص‌ها پیش از ساختِ خودِ سند انجام
        # می‌شود (create_journal_entry خودش new_session جداگانه باز می‌کند)
        # — در صورتِ خطایِ بعدی، شماره‌یِ چک مصرف‌شده باقی می‌ماند، دقیقاً
        # مثلِ یک دسته‌چکِ کاغذیِ واقعی که برگه‌اش را نمی‌شود «پس گذاشت».
        session.commit()

        lines: list[je_service.LineInput] = []
        counterparty_debit = total if direction == "PAYMENT" else decimal.Decimal(0)
        counterparty_credit = total if direction == "RECEIPT" else decimal.Decimal(0)
        lines.append(
            je_service.LineInput(
                account_id=counterparty_account_id,
                description=description,
                debit=counterparty_debit,
                credit=counterparty_credit,
                details=dict(counterparty_details),
            )
        )

        for ml in method_lines:
            mapping_key = f"{direction}_{ml.method}"
            account_id = _get_mapped_account_id(session, company_id, mapping_key)
            details: dict[int, int] = dict(shared_details)
            if ml.detail_account_id is not None:
                dimension_type_id = dimension_type_by_detail_id.get(ml.detail_account_id)
                if dimension_type_id is not None:
                    details[dimension_type_id] = ml.detail_account_id
            line_debit = ml.amount if direction == "RECEIPT" else decimal.Decimal(0)
            line_credit = ml.amount if direction == "PAYMENT" else decimal.Decimal(0)
            lines.append(
                je_service.LineInput(
                    account_id=account_id,
                    description=ml.description or description,
                    debit=line_debit,
                    credit=line_credit,
                    details=details,
                )
            )

    result = je_service.create_journal_entry(
        company_id,
        created_by_user_id,
        document_date,
        description,
        lines,
        alternative_number=alternative_number,
        entry_type_code=direction,
    )

    with new_session() as session:
        for index, ml in enumerate(method_lines):
            if ml.method != "CHECK":
                continue
            check_no = allocated_check_nos.get(index, ml.check_no or "")
            if direction == "RECEIPT":
                status = session.scalar(
                    select(CheckStatus).where(CheckStatus.code == "IN_HAND", CheckStatus.applies_to == "RECEIVED")
                )
                session.add(
                    ReceivedCheck(
                        company_id=company_id,
                        check_no=check_no,
                        drawee_bank_name=ml.check_bank_name,
                        drawer_name=ml.check_party_name,
                        amount=ml.amount,
                        due_date=ml.check_due_date or document_date,
                        received_date=document_date,
                        counterparty_detail_account_id=next(iter(counterparty_details.values()), None),
                        status_id=status.status_id,
                        source_journal_entry_id=result.journal_entry_id,
                        created_by_user_id=created_by_user_id,
                    )
                )
            else:
                status = session.scalar(
                    select(CheckStatus).where(CheckStatus.code == "ISSUED", CheckStatus.applies_to == "ISSUED")
                )
                session.add(
                    IssuedCheck(
                        company_id=company_id,
                        checkbook_id=ml.checkbook_id,
                        check_no=check_no,
                        bank_account_detail_id=ml.detail_account_id,
                        payee_name=ml.check_party_name,
                        amount=ml.amount,
                        due_date=ml.check_due_date or document_date,
                        issue_date=document_date,
                        counterparty_detail_account_id=next(iter(counterparty_details.values()), None),
                        status_id=status.status_id,
                        source_journal_entry_id=result.journal_entry_id,
                        created_by_user_id=created_by_user_id,
                    )
                )
        session.commit()

    return result


# --- چرخه‌یِ عمرِ چک -----------------------------------------------------------


@dataclass
class ReceivedCheckRow:
    received_check_id: int
    check_no: str
    drawee_bank_name: str | None
    drawer_name: str | None
    amount: decimal.Decimal
    due_date: datetime.date
    received_date: datetime.date
    status_code: str
    source_journal_entry_id: int


@dataclass
class IssuedCheckRow:
    issued_check_id: int
    check_no: str
    bank_account_label: str
    payee_name: str | None
    amount: decimal.Decimal
    due_date: datetime.date
    issue_date: datetime.date
    status_code: str
    source_journal_entry_id: int


def _status_id(session, code: str, applies_to: str) -> int:
    status = session.scalar(select(CheckStatus).where(CheckStatus.code == code, CheckStatus.applies_to == applies_to))
    if status is None:
        raise ValueError("وضعیتِ چک نامعتبر است.")
    return status.status_id


def _status_code_map(session, applies_to: str) -> dict[int, str]:
    return dict(
        session.execute(
            select(CheckStatus.status_id, CheckStatus.code).where(CheckStatus.applies_to == applies_to)
        ).all()
    )


def list_received_checks(company_id: int, status_codes: list[str] | None = None) -> list[ReceivedCheckRow]:
    with new_session() as session:
        codes = _status_code_map(session, "RECEIVED")
        query = select(ReceivedCheck).where(ReceivedCheck.company_id == company_id)
        if status_codes is not None:
            status_ids = [sid for sid, code in codes.items() if code in status_codes]
            query = query.where(ReceivedCheck.status_id.in_(status_ids))
        rows = session.scalars(query.order_by(ReceivedCheck.due_date)).all()
        return [
            ReceivedCheckRow(
                received_check_id=r.received_check_id,
                check_no=r.check_no,
                drawee_bank_name=r.drawee_bank_name,
                drawer_name=r.drawer_name,
                amount=r.amount,
                due_date=r.due_date,
                received_date=r.received_date,
                status_code=codes.get(r.status_id, ""),
                source_journal_entry_id=r.source_journal_entry_id,
            )
            for r in rows
        ]


def list_issued_checks(company_id: int, status_codes: list[str] | None = None) -> list[IssuedCheckRow]:
    with new_session() as session:
        codes = _status_code_map(session, "ISSUED")
        query = select(IssuedCheck).where(IssuedCheck.company_id == company_id)
        if status_codes is not None:
            status_ids = [sid for sid, code in codes.items() if code in status_codes]
            query = query.where(IssuedCheck.status_id.in_(status_ids))
        rows = session.scalars(query.order_by(IssuedCheck.due_date)).all()
        bank_detail_ids = {r.bank_account_detail_id for r in rows}
        labels: dict[int, str] = {}
        if bank_detail_ids:
            labels = {
                d.detail_account_id: d.name or d.code
                for d in session.scalars(
                    select(DetailAccount).where(DetailAccount.detail_account_id.in_(bank_detail_ids))
                ).all()
            }
        return [
            IssuedCheckRow(
                issued_check_id=r.issued_check_id,
                check_no=r.check_no,
                bank_account_label=labels.get(r.bank_account_detail_id, ""),
                payee_name=r.payee_name,
                amount=r.amount,
                due_date=r.due_date,
                issue_date=r.issue_date,
                status_code=codes.get(r.status_id, ""),
                source_journal_entry_id=r.source_journal_entry_id,
            )
            for r in rows
        ]


def _first_line_account_and_details(session, journal_entry_id: int) -> tuple[int, dict[int, int]]:
    """حساب و ابعادِ ردیفِ اولِ سند (طرف‌حساب، طبقِ ترتیبِ ساختِ
    create_treasury_voucher همیشه line_no=1) — برایِ ساختِ سندِ برگشتیِ
    برگشت‌خوردن/ابطالِ چک، بدونِ نیاز به ستونِ تازه‌یِ «حسابِ طرف‌حساب» رویِ
    خودِ چک."""
    line = session.scalar(
        select(JournalEntryLine).where(
            JournalEntryLine.journal_entry_id == journal_entry_id, JournalEntryLine.line_no == 1
        )
    )
    if line is None:
        raise ValueError("سندِ اصلیِ این چک یافت نشد.")
    details = dict(
        session.execute(
            select(JournalEntryLineDetail.dimension_type_id, JournalEntryLineDetail.detail_account_id).where(
                JournalEntryLineDetail.line_id == line.line_id
            )
        ).all()
    )
    return line.account_id, details


def deposit_received_check(received_check_id: int, company_id: int) -> None:
    """نزدِ صندوق -> واگذار به بانک برایِ وصول — فقط تغییرِ وضعیت، بدونِ
    سندِ حسابداریِ تازه (تا وصول‌نشدنِ واقعی، اثری در دفاتر ثبت نمی‌شود)."""
    with new_session() as session:
        check = session.get(ReceivedCheck, received_check_id)
        if check is None or check.company_id != company_id:
            raise ValueError("چک نامعتبر است.")
        check.status_id = _status_id(session, "DEPOSITED", "RECEIVED")
        session.commit()


def clear_received_check(
    received_check_id: int, company_id: int, created_by_user_id: int, bank_detail_account_id: int
) -> je_service.JournalEntryResult:
    """وصول شد: بدهکارِ حسابِ بانکیِ انتخاب‌شده / بستانکارِ چک‌هایِ دریافتنی."""
    with new_session() as session:
        check = session.get(ReceivedCheck, received_check_id)
        if check is None or check.company_id != company_id:
            raise ValueError("چک نامعتبر است.")
        current_code = session.get(CheckStatus, check.status_id).code
        if current_code not in ("IN_HAND", "DEPOSITED"):
            raise ValueError("فقط چکِ نزدِ صندوق یا واگذارشده‌ به بانک قابلِ وصول‌شدن است.")
        bank_account_id = _get_mapped_account_id(session, company_id, "RECEIPT_BANK")
        check_account_id = _get_mapped_account_id(session, company_id, "RECEIPT_CHECK")
        bank_detail = session.get(DetailAccount, bank_detail_account_id)
        if bank_detail is None or bank_detail.company_id != company_id:
            raise ValueError("حسابِ بانکیِ انتخاب‌شده نامعتبر است.")
        bank_dimension_type_id = bank_detail.dimension_type_id
        lines = [
            je_service.LineInput(
                account_id=bank_account_id,
                description=f"وصولِ چکِ شماره‌ی {check.check_no}",
                debit=check.amount,
                credit=decimal.Decimal(0),
                details={bank_dimension_type_id: bank_detail_account_id},
            ),
            je_service.LineInput(
                account_id=check_account_id,
                description=f"وصولِ چکِ شماره‌ی {check.check_no}",
                debit=decimal.Decimal(0),
                credit=check.amount,
            ),
        ]
        check_no = check.check_no
        check.status_id = _status_id(session, "CLEARED", "RECEIVED")
        session.commit()

    return je_service.create_journal_entry(
        company_id, created_by_user_id, datetime.date.today(),
        f"وصولِ چکِ دریافتیِ شماره‌ی {check_no}", lines, entry_type_code="RECEIPT",
    )


def bounce_received_check(received_check_id: int, company_id: int, created_by_user_id: int) -> je_service.JournalEntryResult:
    """برگشت‌خورد: بدهکارِ همان حساب/تفصیلیِ طرف‌حسابِ سندِ اصلی (دوباره
    بدهکار می‌شود) / بستانکارِ چک‌هایِ دریافتنی."""
    with new_session() as session:
        check = session.get(ReceivedCheck, received_check_id)
        if check is None or check.company_id != company_id:
            raise ValueError("چک نامعتبر است.")
        current_code = session.get(CheckStatus, check.status_id).code
        if current_code not in ("IN_HAND", "DEPOSITED"):
            raise ValueError("این چک دیگر قابلِ برگشت‌زدن نیست.")
        counterparty_account_id, counterparty_details = _first_line_account_and_details(
            session, check.source_journal_entry_id
        )
        check_account_id = _get_mapped_account_id(session, company_id, "RECEIPT_CHECK")
        lines = [
            je_service.LineInput(
                account_id=counterparty_account_id,
                description=f"برگشتِ چکِ شماره‌ی {check.check_no}",
                debit=check.amount,
                credit=decimal.Decimal(0),
                details=dict(counterparty_details),
            ),
            je_service.LineInput(
                account_id=check_account_id,
                description=f"برگشتِ چکِ شماره‌ی {check.check_no}",
                debit=decimal.Decimal(0),
                credit=check.amount,
            ),
        ]
        check_no = check.check_no
        check.status_id = _status_id(session, "BOUNCED", "RECEIVED")
        session.commit()

    return je_service.create_journal_entry(
        company_id, created_by_user_id, datetime.date.today(),
        f"برگشتِ چکِ دریافتیِ شماره‌ی {check_no}", lines, entry_type_code="RECEIPT",
    )


def endorse_received_check(received_check_id: int, company_id: int) -> None:
    """خرج‌شده نزدِ شخصِ ثالث — فقط تغییرِ وضعیت (بدونِ سندِ تازه)؛ اگر این
    چک بعداً به‌عنوانِ روشِ CHECK در یک سندِ پرداختِ دیگر استفاده شود، آن
    سند اثرِ حسابداریِ واقعی را ثبت می‌کند."""
    with new_session() as session:
        check = session.get(ReceivedCheck, received_check_id)
        if check is None or check.company_id != company_id:
            raise ValueError("چک نامعتبر است.")
        current_code = session.get(CheckStatus, check.status_id).code
        if current_code not in ("IN_HAND", "DEPOSITED"):
            raise ValueError("این چک دیگر قابلِ خرج‌کردن نیست.")
        check.status_id = _status_id(session, "ENDORSED", "RECEIVED")
        session.commit()


def clear_issued_check(issued_check_id: int, company_id: int, created_by_user_id: int) -> je_service.JournalEntryResult:
    """وصول شد توسطِ بانک: بدهکارِ چک‌هایِ پرداختنی / بستانکارِ همان حسابِ
    بانکی‌ای که موقعِ صدور مشخص شده بود."""
    with new_session() as session:
        check = session.get(IssuedCheck, issued_check_id)
        if check is None or check.company_id != company_id:
            raise ValueError("چک نامعتبر است.")
        current_code = session.get(CheckStatus, check.status_id).code
        if current_code != "ISSUED":
            raise ValueError("فقط چکِ صادرشده/نزدِ گیرنده قابلِ وصول‌شدن است.")
        check_account_id = _get_mapped_account_id(session, company_id, "PAYMENT_CHECK")
        bank_account_id = _get_mapped_account_id(session, company_id, "PAYMENT_BANK")
        bank_detail = session.get(DetailAccount, check.bank_account_detail_id)
        bank_dimension_type_id = bank_detail.dimension_type_id if bank_detail else None
        details = {bank_dimension_type_id: check.bank_account_detail_id} if bank_dimension_type_id else {}
        lines = [
            je_service.LineInput(
                account_id=check_account_id,
                description=f"وصولِ چکِ پرداختیِ شماره‌ی {check.check_no}",
                debit=check.amount,
                credit=decimal.Decimal(0),
            ),
            je_service.LineInput(
                account_id=bank_account_id,
                description=f"وصولِ چکِ پرداختیِ شماره‌ی {check.check_no}",
                debit=decimal.Decimal(0),
                credit=check.amount,
                details=details,
            ),
        ]
        check_no = check.check_no
        check.status_id = _status_id(session, "CLEARED", "ISSUED")
        session.commit()

    return je_service.create_journal_entry(
        company_id, created_by_user_id, datetime.date.today(),
        f"وصولِ چکِ پرداختیِ شماره‌ی {check_no}", lines, entry_type_code="PAYMENT",
    )


def bounce_issued_check(issued_check_id: int, company_id: int) -> None:
    """برگشت‌خورد (بانکِ گیرنده نتوانست وصول کند) — فقط تغییرِ وضعیت؛
    بدهیِ ما همچنان به‌عنوانِ چک‌هایِ پرداختنی برقرار می‌ماند تا با چکِ
    تازه یا نقد تسویه شود."""
    with new_session() as session:
        check = session.get(IssuedCheck, issued_check_id)
        if check is None or check.company_id != company_id:
            raise ValueError("چک نامعتبر است.")
        current_code = session.get(CheckStatus, check.status_id).code
        if current_code != "ISSUED":
            raise ValueError("این چک دیگر قابلِ برگشت‌خوردن نیست.")
        check.status_id = _status_id(session, "BOUNCED", "ISSUED")
        session.commit()


def void_issued_check(issued_check_id: int, company_id: int, created_by_user_id: int) -> je_service.JournalEntryResult:
    """ابطال شد (هرگز وصول نشد، پس گرفته شد): بدهکارِ چک‌هایِ پرداختنی /
    بستانکارِ همان حساب/تفصیلیِ طرف‌حسابِ سندِ اصلی (بدهیِ ما به او دوباره
    برمی‌گردد)."""
    with new_session() as session:
        check = session.get(IssuedCheck, issued_check_id)
        if check is None or check.company_id != company_id:
            raise ValueError("چک نامعتبر است.")
        current_code = session.get(CheckStatus, check.status_id).code
        if current_code not in ("ISSUED", "BOUNCED"):
            raise ValueError("این چک دیگر قابلِ ابطال‌شدن نیست.")
        counterparty_account_id, counterparty_details = _first_line_account_and_details(
            session, check.source_journal_entry_id
        )
        check_account_id = _get_mapped_account_id(session, company_id, "PAYMENT_CHECK")
        lines = [
            je_service.LineInput(
                account_id=check_account_id,
                description=f"ابطالِ چکِ شماره‌ی {check.check_no}",
                debit=check.amount,
                credit=decimal.Decimal(0),
            ),
            je_service.LineInput(
                account_id=counterparty_account_id,
                description=f"ابطالِ چکِ شماره‌ی {check.check_no}",
                debit=decimal.Decimal(0),
                credit=check.amount,
                details=dict(counterparty_details),
            ),
        ]
        check_no = check.check_no
        check.status_id = _status_id(session, "VOIDED", "ISSUED")
        session.commit()

    return je_service.create_journal_entry(
        company_id, created_by_user_id, datetime.date.today(),
        f"ابطالِ چکِ پرداختیِ شماره‌ی {check_no}", lines, entry_type_code="PAYMENT",
    )
