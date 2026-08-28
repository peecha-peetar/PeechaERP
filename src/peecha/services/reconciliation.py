"""مغایرتِ بانکی/حساب از اکسل — طبقِ آیتمِ ۵ (درخواستِ صریح: «مغایرتِ
بانکی/حساب از اکسل») و پاسخِ تاییدشده‌یِ کاربر به پرسشِ روشن‌سازی («فقط
نمایشِ اختلاف‌ها»، بدونِ مکانیزمِ تطبیق‌دادن/رفع‌مغایرتِ دستی): صورت‌حسابِ
بانک (از اکسل) با گردشِ همان حسابِ کدینگی در بازه‌یِ مشخص مقایسه می‌شود.

تطبیق بر اساسِ مبلغِ بدهکار/بستانکار است، نه تاریخِ دقیق — چون تاریخِ
تسویه‌یِ بانکی معمولاً چند روز با تاریخِ ثبتِ دفتر فرق دارد؛ هر ردیفِ دفتر
که مبلغِ برابری در صورت‌حسابِ اکسل نداشته باشد (و برعکس)، به‌عنوانِ
اختلاف فهرست می‌شود."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from peecha.services import reports as reports_service


@dataclass
class StatementRow:
    row_no: int
    date: datetime.date | None
    description: str
    debit: decimal.Decimal
    credit: decimal.Decimal


@dataclass
class DifferenceRow:
    source: str  # "LEDGER" (فقط در دفترِ حساب) | "STATEMENT" (فقط در صورت‌حسابِ اکسل)
    date: datetime.date | None
    reference: str
    description: str
    debit: decimal.Decimal
    credit: decimal.Decimal


def compute_differences(
    company_id: int,
    account_id: int,
    date_from: datetime.date,
    date_to: datetime.date,
    statement_rows: list[StatementRow],
) -> list[DifferenceRow]:
    """ردیف‌هایِ دفترِ حساب که در صورت‌حسابِ اکسل نیستند، و برعکس — تناظرِ
    حریصانه بر اساسِ (بدهکار، بستانکار)ِ برابر، بدونِ توجه به ترتیب/تاریخ."""
    _opening_debit, _opening_credit, ledger_lines = reports_service.list_ledger_entries(
        company_id, date_from, date_to, account_id=account_id
    )

    unmatched_statement = list(statement_rows)
    differences: list[DifferenceRow] = []
    for ln in ledger_lines:
        match_index = next(
            (i for i, s in enumerate(unmatched_statement) if s.debit == ln.debit and s.credit == ln.credit),
            None,
        )
        if match_index is not None:
            unmatched_statement.pop(match_index)
            continue
        differences.append(
            DifferenceRow("LEDGER", ln.document_date, str(ln.temporary_no), ln.description or "", ln.debit, ln.credit)
        )

    for s in unmatched_statement:
        differences.append(DifferenceRow("STATEMENT", s.date, str(s.row_no), s.description, s.debit, s.credit))

    return differences
