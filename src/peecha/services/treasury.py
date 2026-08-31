"""سرویسِ خزانه‌داری: نگاشتِ حساب‌ها، دسته‌چک، سندِ چندروشیِ دریافت/پرداخت
(نقد/بانک/چک/تخفیف در یک سندِ واحد)، و چرخه‌یِ عمرِ چک‌هایِ دریافتی/پرداختی
— همه رویِ همان موتورِ اسنادِ حسابداری (journal_entries.py) و ابعادِ
تفصیلیِ موجود (detail_dimensions.py)، بدونِ موتورِ موازیِ تازه."""

from __future__ import annotations

import datetime
import decimal
import re
from dataclasses import dataclass, field

from sqlalchemy import func, select

from peecha import numerals
from peecha.db.base import new_session
from peecha.db.models.accounting import (
    ChartOfAccount,
    DetailAccount,
    JournalEntry,
    JournalEntryLine,
    JournalEntryLineDetail,
    JournalEntryStatus,
)
from peecha.db.models.core import Company, Currency
from peecha.db.models.treasury import (
    Bank,
    Checkbook,
    CheckStageEvent,
    CheckStatus,
    CounterpartyAccountMapping,
    CustomMethod,
    DescriptionTemplate,
    IssuedCheck,
    ReceivedCheck,
    TreasuryAccountMapping,
)
from peecha.db.models.commercial import CommercialDocument
from peecha.services import audit as audit_service
from peecha.services import chart_of_accounts as coa_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import installments as installments_service
from peecha.services import journal_entries as je_service

_MONEY_Q = decimal.Decimal("0.01")


def _money(value: decimal.Decimal) -> decimal.Decimal:
    return value.quantize(_MONEY_Q, rounding=decimal.ROUND_HALF_UP)


MAPPING_KEYS = [
    "RECEIPT_CASH",
    "RECEIPT_BANK",
    "RECEIPT_CHECK",
    "RECEIPT_DISCOUNT",
    "RECEIPT_NETTING",
    "RECEIPT_GOODS_COUPON",
    "RECEIPT_VOUCHER",
    "RECEIPT_INSTALLMENT",
    "RECEIPT_INSTALLMENT_INTEREST",
    "PAYMENT_CASH",
    "PAYMENT_BANK",
    "PAYMENT_CHECK",
    "PAYMENT_DISCOUNT",
    "PAYMENT_CHECK_DISBURSEMENT",
    "PAYMENT_NETTING",
    "PAYMENT_INSTALLMENT",
    "PAYMENT_INSTALLMENT_INTEREST",
    # طبقِ درخواستِ صریح: «برایِ هرِ مرحله یک ردیفِ جداگانه در تنظیمات باشه»
    # — این‌ها مستقل از کلیدهایِ فرمِ دریافت/پرداختِ بالا، مخصوصِ مراحلِ
    # چرخه‌یِ عمرِ چک‌اند (حتی اگر عملاً به همان حساب اشاره کنند).
    "CHECK_RECEIVED_FUND_TRANSFER",
    "CHECK_RECEIVED_CASH_COLLECT",
    "CHECK_RECEIVED_BANK_DEPOSIT",
    "CHECK_RECEIVED_BANK_CLEAR",
    "CHECK_RECEIVED_BANK_RETURN",
    "CHECK_ISSUED_BANK_CLEAR",
    "CHECK_ISSUED_RETURN_TO_FUND",
]

MAPPING_LABELS: dict[str, str] = {
    "RECEIPT_CASH": "دریافتِ نقدی",
    "RECEIPT_BANK": "دریافتِ بانکی",
    "RECEIPT_CHECK": "چک‌هایِ دریافتنی (در جریانِ وصول)",
    "RECEIPT_DISCOUNT": "تخفیفاتِ نقدیِ داده‌شده",
    "RECEIPT_NETTING": "تهاترِ دریافت",
    "RECEIPT_GOODS_COUPON": "کالابرگِ دریافتی",
    "RECEIPT_VOUCHER": "بنِ دریافتی",
    # طبقِ درخواستِ صریح («روشِ دریافت/پرداختِ اقساطی»): این حساب، سهمی از
    # طلب/بدهیِ همان طرفِ‌حساب را که قرار است طیِ چند قسط دریافت/پرداخت
    # شود نگه می‌دارد -- معمولاً یک زیرحسابِ اختصاصیِ «دریافتنی/پرداختنیِ
    # اقساطی» (تا از AR/APِ عادی جدا و قابلِ‌ردیابی بماند).
    "RECEIPT_INSTALLMENT": "دریافتنیِ اقساطی",
    # طبقِ موردِ ۶ («درصدِ بهرهٔ اقساط و هزینه‌هایِ متفرقه»): سهمِ بهره/
    # هزینه‌یِ متفرقه‌یِ اقساط (مازاد بر اصلِ مبلغ) در همان سندِ ساختِ طرحِ
    # اقساط، مستقیماً به‌عنوانِ درآمد شناسایی می‌شود.
    "RECEIPT_INSTALLMENT_INTEREST": "درآمدِ بهره/کارمزدِ اقساط",
    "PAYMENT_CASH": "پرداختِ نقدی",
    "PAYMENT_BANK": "پرداختِ بانکی",
    "PAYMENT_CHECK": "چک‌هایِ پرداختنی",
    "PAYMENT_DISCOUNT": "تخفیفاتِ نقدیِ دریافت‌شده",
    "PAYMENT_CHECK_DISBURSEMENT": "پرداخت با چکِ دریافتی (خرجِ چک)",
    "PAYMENT_NETTING": "تهاترِ پرداخت",
    "PAYMENT_INSTALLMENT": "پرداختنیِ اقساطی",
    # طبقِ همان موردِ ۶، سمتِ پرداخت: سهمِ بهره/هزینه‌یِ متفرقه به‌عنوانِ
    # هزینه شناسایی می‌شود (حسابِ هزینه‌یِ انتخابی).
    "PAYMENT_INSTALLMENT_INTEREST": "هزینه‌یِ بهره/کارمزدِ اقساط",
    "CHECK_RECEIVED_FUND_TRANSFER": "انتقالِ چکِ دریافتی بینِ صندوق‌ها",
    "CHECK_RECEIVED_CASH_COLLECT": "وصولِ نقدیِ چکِ دریافتیِ نزدِ صندوق",
    "CHECK_RECEIVED_BANK_DEPOSIT": "واگذاریِ چکِ دریافتیِ نزدِ صندوق به بانک",
    "CHECK_RECEIVED_BANK_CLEAR": "اعلامِ وصولِ چکِ دریافتیِ نزدِ بانک",
    "CHECK_RECEIVED_BANK_RETURN": "برگشتِ چکِ دریافتیِ نزدِ بانک به صندوق",
    "CHECK_ISSUED_BANK_CLEAR": "وصولِ چکِ پرداختی از بانک",
    "CHECK_ISSUED_RETURN_TO_FUND": "چکِ پرداختیِ وصول‌نشده جهتِ برگشت",
    # این دو مرحله (برگشتِ چک به طرفِ‌حساب / برگشتِ چکِ خرجی به صندوق) حسابِ
    # کلِ تازه لازم ندارند — هر دو طرفِ سندشان پویا از رویِ خودِ چک تعیین
    # می‌شود؛ فقط این‌جا برایِ برچسبِ ردیفِ متنِ‌شرحِ قابل‌ویرایش (پایین)
    # استفاده می‌شوند، نه به‌عنوانِ کلیدِ نگاشتِ حساب.
    "CHECK_RECEIVED_CUSTOMER_RETURN": "برگشتِ چکِ دریافتیِ نزدِ صندوق به طرفِ‌حساب",
    "CHECK_RECEIVED_ENDORSED_RETURN": "برگشتِ چکِ خرجی به صندوق",
    # طبقِ ساختارِ واقعیِ تنخواه‌گردان (services/petty_cash.py): حسابِ
    # پیش‌پرداختِ تنخواه‌داران — در افتتاح بدهکار، در بستن بستانکار می‌شود.
    "PETTY_CASH_ADVANCE": "پیش‌پرداختِ تنخواه‌گردان",
}

METHOD_CODES = ("CASH", "BANK", "CHECK", "DISCOUNT", "NETTING", "CHECK_DISBURSEMENT", "GOODS_COUPON", "VOUCHER", "INSTALLMENT")

# --- تاریخچه‌یِ چرخه‌یِ عمرِ چک -----------------------------------------------
# طبقِ درخواستِ صریح: «چک‌ها باید در هر مرحله ثبت بشه و بتوان گزارش گرفت» —
# هر تابعِ تغییرِ مرحله‌یِ پایین‌تر، یک ردیف در treasury.check_stage_events
# با یکی از این کدها ثبت می‌کند.
CHECK_EVENT_LABELS: dict[str, str] = {
    "REGISTERED": "ثبتِ چک (سندِ دریافت/پرداخت)",
    "FUND_TRANSFER": "انتقال بینِ صندوق‌ها",
    "CASH_COLLECT": "وصولِ نقدیِ نزدِ صندوق",
    "BANK_DEPOSIT": "واگذاری به بانک",
    "BANK_CLEAR": "اعلامِ وصول نزدِ بانک",
    "BANK_RETURN": "برگشت از بانک به صندوق",
    "BOUNCED": "برگشت‌خوردنِ چک به طرفِ‌حساب",
    "ENDORSED": "خرج‌شدنِ چک (پرداخت با چکِ دریافتی)",
    "UNENDORSED_RETURN": "برگشتِ چکِ خرجی به صندوق",
    "ISSUED_CLEARED": "وصول از بانک",
    "ISSUED_RETURNED": "برگشت/ابطالِ چکِ پرداختیِ وصول‌نشده",
}


def _log_check_event(
    session,
    company_id: int,
    check_kind: str,
    check_id: int,
    event_code: str,
    event_date: datetime.date,
    from_status_code: str | None,
    to_status_code: str,
    journal_entry_id: int | None,
    created_by_user_id: int,
    from_location_account_id: int | None = None,
    from_location_detail_account_id: int | None = None,
) -> None:
    session.add(
        CheckStageEvent(
            company_id=company_id,
            check_kind=check_kind,
            check_id=check_id,
            event_code=event_code,
            event_date=event_date,
            from_status_code=from_status_code,
            to_status_code=to_status_code,
            journal_entry_id=journal_entry_id,
            created_by_user_id=created_by_user_id,
            from_location_account_id=from_location_account_id,
            from_location_detail_account_id=from_location_detail_account_id,
        )
    )


@dataclass
class CheckStageEventRow:
    event_id: int
    event_code: str
    event_label: str
    event_date: datetime.date
    from_status_code: str | None
    to_status_code: str
    journal_entry_id: int | None
    journal_temporary_no: int | None
    journal_permanent_no: int | None
    created_by_user_id: int


def get_check_stage_history(company_id: int, check_kind: str, check_id: int) -> list[CheckStageEventRow]:
    """تاریخچه‌یِ کاملِ یک چکِ خاص (دریافتی یا پرداختی)، به‌ترتیبِ زمانی —
    برایِ هر رویداد، شماره‌یِ سندِ حسابداری‌یی که آن مرحله را ثبت کرده هم
    برگردانده می‌شود (اگر مرحله سند داشته باشد)."""
    with new_session() as session:
        from peecha.db.models.accounting import JournalEntry

        events = session.scalars(
            select(CheckStageEvent)
            .where(
                CheckStageEvent.company_id == company_id,
                CheckStageEvent.check_kind == check_kind,
                CheckStageEvent.check_id == check_id,
            )
            .order_by(CheckStageEvent.event_id)
        ).all()
        journal_entry_ids = {e.journal_entry_id for e in events if e.journal_entry_id is not None}
        journal_numbers: dict[int, tuple[int, int | None]] = {}
        if journal_entry_ids:
            journal_numbers = {
                je.journal_entry_id: (je.temporary_no, je.permanent_no)
                for je in session.scalars(
                    select(JournalEntry).where(JournalEntry.journal_entry_id.in_(journal_entry_ids))
                ).all()
            }
        return [
            CheckStageEventRow(
                event_id=e.event_id,
                event_code=e.event_code,
                event_label=CHECK_EVENT_LABELS.get(e.event_code, e.event_code),
                event_date=e.event_date,
                from_status_code=e.from_status_code,
                to_status_code=e.to_status_code,
                journal_entry_id=e.journal_entry_id,
                journal_temporary_no=journal_numbers.get(e.journal_entry_id, (None, None))[0]
                if e.journal_entry_id is not None
                else None,
                journal_permanent_no=journal_numbers.get(e.journal_entry_id, (None, None))[1]
                if e.journal_entry_id is not None
                else None,
                created_by_user_id=e.created_by_user_id,
            )
            for e in events
        ]


def undo_last_check_stage(check_kind: str, check_id: int, company_id: int, changed_by_user_id: int) -> None:
    """طبقِ درخواستِ صریح: «سندِ مرحله‌یِ آخر حذف بشه تا چک برگرده به
    حالتِ اول» — آخرین رویدادِ چک را برمی‌دارد، سندِ حسابداریِ همان مرحله
    را حذف می‌کند (فقط اگر هنوز موقت باشد)، و وضعیت/محلِ چک را دقیقاً به
    همانی که پیش‌از‌آن مرحله بود برمی‌گرداند. رویدادِ REGISTERED با این
    تابع قابلِ‌برداشتن نیست — برایِ آن از حذفِ کاملِ چک استفاده کنید."""
    with new_session() as session:
        latest_event = session.scalar(
            select(CheckStageEvent)
            .where(
                CheckStageEvent.company_id == company_id,
                CheckStageEvent.check_kind == check_kind,
                CheckStageEvent.check_id == check_id,
            )
            .order_by(CheckStageEvent.event_id.desc())
        )
        if latest_event is None:
            raise ValueError("برایِ این چک هیچ رویدادِ قابلِ‌برگشتی ثبت نشده است.")
        if latest_event.event_code == "REGISTERED":
            raise ValueError("این چک هنوز هیچ مرحله‌ای طی نکرده — برایِ حذفِ کاملِ آن از دکمه‌یِ «حذفِ چک» استفاده کنید.")

        journal_entry_id = latest_event.journal_entry_id
        model_cls = ReceivedCheck if check_kind == "RECEIVED" else IssuedCheck
        check = session.get(model_cls, check_id)
        if check is None or check.company_id != company_id:
            raise ValueError("چک نامعتبر است.")

        # طبقِ درخواستِ صریح، ولی با احتیاطِ لازم: اگر همین سند به‌طورِ
        # گروهی چند چکِ دیگر را هم پوشش می‌دهد (رویدادِ آن‌ها هنوز به همین
        # journal_entry_id اشاره دارد)، سند حذف نمی‌شود — فقط وضعیت/محلِ
        # همین چک برمی‌گردد؛ سند وقتی حذف‌شدنی می‌شود که آخرین چکِ وابسته
        # به آن هم برگردد.
        shared_by_other_check = False
        if journal_entry_id is not None:
            shared_by_other_check = (
                session.scalar(
                    select(CheckStageEvent.event_id).where(
                        CheckStageEvent.journal_entry_id == journal_entry_id,
                        CheckStageEvent.event_id != latest_event.event_id,
                    )
                )
                is not None
            )

        check.status_id = _status_id(session, latest_event.from_status_code, "RECEIVED" if check_kind == "RECEIVED" else "ISSUED")
        if check_kind == "RECEIVED":
            check.current_location_account_id = latest_event.from_location_account_id
            check.current_location_detail_account_id = latest_event.from_location_detail_account_id

        session.delete(latest_event)
        session.commit()

    if journal_entry_id is not None and not shared_by_other_check:
        je_service.delete_journal_entry(journal_entry_id, company_id, changed_by_user_id)


_FA_DIGITS_BEFORE_FAGHARE_RE = re.compile(r"[۰-۹]+(?=\s*فقره)")


def _fix_partial_check_line_description(
    company_id: int,
    description: str,
    old_amount: decimal.Decimal,
    new_amount: decimal.Decimal,
    remaining_check_count: int,
) -> str:
    """طبقِ گزارشِ صریح: وقتی حذفِ یک چک فقط باعثِ کم‌شدنِ مبلغِ همان ردیف
    می‌شود (نه حذفِ کاملِ ردیف، چون چکِ دیگری هم در همان ردیف مانده)، شرحِ
    قدیمیِ ردیف دیگر درست نیست — چون هم مبلغ و هم تعدادِ «فقره چک»یِ
    ذکرشده در آن به‌حالِ قبل از حذف اشاره دارند. این‌جا (۱) پیشوندِ «سندِ
    اصلاح‌شده» اضافه می‌شود، (۲) مبلغِ قدیمی در متن، اگر عیناً پیدا شود، با
    مبلغِ تازه جایگزین می‌شود، و (۳) عددِ جلویِ «فقره» هم به تعدادِ
    باقی‌ماندهِ چک‌ها به‌روز می‌شود."""
    if not description:
        return description
    with new_session() as session:
        company = session.get(Company, company_id)
        base_decimal_places = 0
        if company is not None:
            base_decimal_places = (
                session.scalar(
                    select(Currency.decimal_places).where(Currency.currency_id == company.base_currency_id)
                )
                or 0
            )
    old_amount_text = numerals.format_money(old_amount, base_decimal_places)
    new_amount_text = numerals.format_money(new_amount, base_decimal_places)
    fixed = description.replace(old_amount_text, new_amount_text) if old_amount_text in description else description
    if remaining_check_count > 0:
        count_text = numerals.to_persian_digits(str(remaining_check_count))
        fixed = _FA_DIGITS_BEFORE_FAGHARE_RE.sub(count_text, fixed, count=1)
    prefix = "سندِ اصلاح‌شده — "
    if not fixed.startswith(prefix):
        fixed = prefix + fixed
    return fixed


def _remove_check_amount_from_source_entry(
    company_id: int,
    journal_entry_id: int,
    line_no: int | None,
    amount: decimal.Decimal,
    changed_by_user_id: int | None,
    remaining_check_count: int = 0,
) -> bool:
    """طبقِ گزارشِ صریح: حذفِ یک چک نباید کلِ سندِ چندروشیِ مربوطه را حذف
    کند — ممکن است همان سند روش‌هایِ دیگری هم (نقد، چکِ دیگر، …) داشته
    باشد، یا خودِ همان ردیف چند چکِ دیگر را هم دربرگرفته باشد. این تابع
    فقط سهمِ همین یک چک را از سند کم می‌کند: اگر ردیفِ مربوطه مبلغِ
    بیشتری هم داشت (چکِ دیگری در همان ردیف)، فقط مبلغِ ردیف کم می‌شود؛
    اگر این چک تنها موردِ آن ردیف بود، کلِ ردیف حذف می‌شود. ردیفِ اولِ سند
    (طرفِ‌حساب) هم به همان اندازه اصلاح می‌شود تا سند تراز بماند. اگر
    بعدِ این کار چیزی جز ردیفِ طرفِ‌حساب باقی نماند، سند دیگر معنایی
    ندارد و باید کلاً حذف شود (رفتارِ قدیم) — اما چون received_checks/
    issued_checks با FK به journal_entry_id وصل‌اند، خودِ حذفِ سند باید
    بعد از حذفِ ردیفِ چک (توسطِ فراخوان‌کننده) انجام شود، وگرنه با خطایِ
    نقضِ FK رد می‌شود. برایِ همین این تابع در آن حالت فقط True برمی‌گرداند
    («حذفِ کاملِ سند لازم است») و خودش سند را حذف نمی‌کند. اگر line_no
    مشخص نباشد (داده‌یِ ثبت‌شده پیش از این ستون)، محافظه‌کارانه همان
    رفتارِ قدیمی لازم است — چون معلوم نیست دقیقاً کدام ردیف مالِ این چک
    بوده."""
    if line_no is None:
        return True

    lines = je_service.get_journal_entry_lines(journal_entry_id)
    target_index = line_no - 1
    if target_index <= 0 or target_index >= len(lines):
        # ردیفِ ثبت‌شده دیگر معتبر نیست (داده‌یِ ناسازگار) — محافظه‌کارانه
        # کلِ سند حذف شود، نه این‌که به ردیفِ اشتباهی دست بزنیم.
        return True

    counterparty = lines[0]
    counterparty_amount = counterparty.debit or counterparty.credit
    counterparty_is_debit = bool(counterparty.debit)
    new_counterparty_amount = counterparty_amount - amount
    if new_counterparty_amount <= 0:
        # این چک عملاً تمامِ مبلغِ سند بود -> کلِ سند باید حذف شود.
        return True
    if counterparty_is_debit:
        counterparty.debit = new_counterparty_amount
    else:
        counterparty.credit = new_counterparty_amount

    target = lines[target_index]
    target_amount = target.debit or target.credit
    target_is_debit = bool(target.debit)
    if amount >= target_amount:
        new_lines = [ln for i, ln in enumerate(lines) if i != target_index]
    else:
        new_target_amount = target_amount - amount
        if target_is_debit:
            target.debit = new_target_amount
        else:
            target.credit = new_target_amount
        # طبقِ گزارشِ صریح: ردیف حذف نشد (چکِ دیگری در همان ردیف باقی
        # مانده)، پس شرحِ ردیف هم که هنوز به مبلغ/تعدادِ قبل از حذف اشاره
        # می‌کند، باید اصلاح شود — نه این‌که شرحِ کهنه بدونِ تغییر بماند.
        target.description = _fix_partial_check_line_description(
            company_id, target.description or "", target_amount, new_target_amount, remaining_check_count
        )
        new_lines = lines

    if len(new_lines) < 2:
        return True

    with new_session() as session:
        entry = session.get(JournalEntry, journal_entry_id)
        if entry is None or entry.company_id != company_id:
            raise ValueError("سندِ اصلیِ این چک یافت نشد.")
        document_date = entry.document_date
        description = entry.description or ""
        alternative_number = entry.alternative_number or ""
    je_service.update_journal_entry(
        journal_entry_id, company_id, document_date, description, new_lines, changed_by_user_id, alternative_number
    )
    return False


def delete_received_check(received_check_id: int, company_id: int, changed_by_user_id: int) -> None:
    """طبقِ گزارشِ صریح: حذفِ کاملِ یک چکِ دریافتی — فقط وقتی چک هنوز به
    همان حالتِ اولِ ثبت (نزدِ صندوق، بدونِ هیچ پیشرفتی) برگشته باشد. فقط
    سهمِ همین چک از سندِ ثبتِ اولیه کم می‌شود (نه کلِ سند)، مگر این‌که این
    چک تنها ردیفِ باقی‌مانده‌یِ سند بوده باشد."""
    with new_session() as session:
        check = session.get(ReceivedCheck, received_check_id)
        if check is None or check.company_id != company_id:
            raise ValueError("چک نامعتبر است.")
        status_code = session.scalar(select(CheckStatus.code).where(CheckStatus.status_id == check.status_id))
        if status_code != "IN_HAND":
            raise ValueError(
                "فقط چکِ «نزدِ صندوق» (بدونِ پیشرفتِ بیشتر) قابلِ‌حذف است — "
                "ابتدا با «حذفِ آخرین سندِ مرحله» آن را به همین حالت برگردانید."
            )
        source_journal_entry_id = check.source_journal_entry_id
        source_line_no = check.source_journal_entry_line_no
        amount = check.amount
        remaining_check_count = 0
        if source_line_no is not None:
            # طبقِ گزارشِ صریح: برایِ اصلاحِ شرحِ ردیف (تعدادِ «فقره چک») باید
            # تعدادِ چک‌هایِ *باقی‌مانده* در همین ردیف را از قبل بدانیم — قبل
            # از این‌که خودِ این چک واقعاً حذف شود.
            remaining_check_count = (
                session.scalar(
                    select(func.count()).select_from(ReceivedCheck).where(
                        ReceivedCheck.company_id == company_id,
                        ReceivedCheck.source_journal_entry_id == source_journal_entry_id,
                        ReceivedCheck.source_journal_entry_line_no == source_line_no,
                        ReceivedCheck.received_check_id != received_check_id,
                    )
                )
                or 0
            )

    # طبقِ باگ‌فیکسِ گزارش‌شده: اگر سند فقط اصلاح می‌شود (نه حذفِ کامل)،
    # این اصلاح قبل از حذفِ خودِ چک انجام می‌شود — تا اگر به هر دلیلی
    # (مثلاً سند دیگر موقت نیست) رد شود، چک نیمه‌حذف‌شده نماند. اگر کلِ
    # سند باید حذف شود، آن حذف باید بعد از حذفِ چک انجام شود (به‌خاطرِ FK).
    delete_whole_entry = _remove_check_amount_from_source_entry(
        company_id, source_journal_entry_id, source_line_no, amount, changed_by_user_id, remaining_check_count
    )

    with new_session() as session:
        check = session.get(ReceivedCheck, received_check_id)
        session.execute(
            CheckStageEvent.__table__.delete().where(
                CheckStageEvent.company_id == company_id,
                CheckStageEvent.check_kind == "RECEIVED",
                CheckStageEvent.check_id == received_check_id,
            )
        )
        session.delete(check)
        session.commit()

    if delete_whole_entry:
        je_service.delete_journal_entry(source_journal_entry_id, company_id, changed_by_user_id)


def delete_issued_check(issued_check_id: int, company_id: int, changed_by_user_id: int) -> None:
    """هم‌ارزِ delete_received_check برایِ چکِ پرداختی — فقط وقتی هنوز
    «صادرشده» (بدونِ پیشرفتِ بیشتر) باشد."""
    with new_session() as session:
        check = session.get(IssuedCheck, issued_check_id)
        if check is None or check.company_id != company_id:
            raise ValueError("چک نامعتبر است.")
        status_code = session.scalar(select(CheckStatus.code).where(CheckStatus.status_id == check.status_id))
        if status_code != "ISSUED":
            raise ValueError(
                "فقط چکِ «صادرشده» (بدونِ پیشرفتِ بیشتر) قابلِ‌حذف است — "
                "ابتدا با «حذفِ آخرین سندِ مرحله» آن را به همین حالت برگردانید."
            )
        source_journal_entry_id = check.source_journal_entry_id
        source_line_no = check.source_journal_entry_line_no
        amount = check.amount
        remaining_check_count = 0
        if source_line_no is not None:
            remaining_check_count = (
                session.scalar(
                    select(func.count()).select_from(IssuedCheck).where(
                        IssuedCheck.company_id == company_id,
                        IssuedCheck.source_journal_entry_id == source_journal_entry_id,
                        IssuedCheck.source_journal_entry_line_no == source_line_no,
                        IssuedCheck.issued_check_id != issued_check_id,
                    )
                )
                or 0
            )

    delete_whole_entry = _remove_check_amount_from_source_entry(
        company_id, source_journal_entry_id, source_line_no, amount, changed_by_user_id, remaining_check_count
    )

    with new_session() as session:
        check = session.get(IssuedCheck, issued_check_id)
        session.execute(
            CheckStageEvent.__table__.delete().where(
                CheckStageEvent.company_id == company_id,
                CheckStageEvent.check_kind == "ISSUED",
                CheckStageEvent.check_id == issued_check_id,
            )
        )
        session.delete(check)
        session.commit()

    if delete_whole_entry:
        je_service.delete_journal_entry(source_journal_entry_id, company_id, changed_by_user_id)


def list_check_numbers_on_journal_entry_line(company_id: int, journal_entry_id: int, line_no: int) -> list[str]:
    """طبقِ گزارشِ صریح: کاربر از فرمِ عمومیِ سندِ حسابداری توانسته بود ردیفِ
    مربوط به یک چک را مستقیماً حذف کند — بدونِ این‌که چکِ خزانه‌داری هم
    حذف/اصلاح شود، یعنی چک به یک ردیفِ دیگر (یا هیچ ردیفی) اشاره می‌کرد.
    این تابع برایِ اعتبارسنجیِ همان فرم استفاده می‌شود: اگر ردیفِ line_no
    از سندِ journal_entry_id چک(هایِ) دریافتی/پرداختی داشته باشد، شماره‌یِ
    آن‌ها را برمی‌گرداند تا فرمِ سند حذفِ آن ردیف را رد کند (باید کاربر از
    صفحه‌یِ چک‌ها اقدام کند، جایی که مبلغ/شرحِ سند هم به‌درستی اصلاح
    می‌شود)."""
    with new_session() as session:
        received = session.scalars(
            select(ReceivedCheck.check_no).where(
                ReceivedCheck.company_id == company_id,
                ReceivedCheck.source_journal_entry_id == journal_entry_id,
                ReceivedCheck.source_journal_entry_line_no == line_no,
            )
        ).all()
        issued = session.scalars(
            select(IssuedCheck.check_no).where(
                IssuedCheck.company_id == company_id,
                IssuedCheck.source_journal_entry_id == journal_entry_id,
                IssuedCheck.source_journal_entry_line_no == line_no,
            )
        ).all()
        return list(received) + list(issued)


# --- متنِ خودکارِ شرحِ ردیف‌ها ---------------------------------------------
# طبقِ درخواستِ صریح: کاربر خودش می‌تواند این قالب‌ها را ویرایش کند —
# جای‌گذارهایِ مجاز: {تفصیلی} (تفصیلیِ خودِ ردیف، مثلاً صندوق/بانک)،
# {مبلغ}، {طرف_حساب} (تفصیلیِ بالایِ فرم)، {تعداد} (فقط چک)، {یادداشت}
# (فقط بن — سریال/مشخصات).
DEFAULT_DESCRIPTION_TEMPLATES: dict[str, str] = {
    "RECEIPT_CASH": "دریافتِ نقدی «{تفصیلی}» به مبلغِ {مبلغ} ریال از {طرف_حساب}",
    "RECEIPT_BANK": "دریافتِ بانکی «{تفصیلی}» به مبلغِ {مبلغ} ریال از {طرف_حساب}",
    "RECEIPT_CHECK": "دریافتِ {تعداد} فقره چک به مبلغِ {مبلغ} ریال از {طرف_حساب}",
    "RECEIPT_DISCOUNT": "تخفیفِ نقدیِ داده‌شده به مبلغِ {مبلغ} ریال به {طرف_حساب}",
    "RECEIPT_GOODS_COUPON": "دریافتِ کالابرگِ «{تفصیلی}» به مبلغِ {مبلغ} ریال از {طرف_حساب}",
    "RECEIPT_VOUCHER": "دریافتِ بنِ {یادداشت} به مبلغِ {مبلغ} ریال از {طرف_حساب}",
    "RECEIPT_NETTING": "تهاترِ حساب به مبلغِ {مبلغ} ریال با {طرف_حساب}",
    # طبقِ درخواستِ صریحِ «مدلِ تنظیماتِ روش‌هایِ پرداخت مثلِ روش‌هایِ دریافت»:
    # قالب‌هایِ پیش‌فرضِ پرداخت هم، هم‌ارزِ دریافت، تعریف می‌شوند.
    "PAYMENT_CASH": "پرداختِ نقدی «{تفصیلی}» به مبلغِ {مبلغ} ریال به {طرف_حساب}",
    "PAYMENT_BANK": "پرداختِ بانکی «{تفصیلی}» به مبلغِ {مبلغ} ریال به {طرف_حساب}",
    "PAYMENT_CHECK": "پرداختِ {تعداد} فقره چک به مبلغِ {مبلغ} ریال به {طرف_حساب}",
    "PAYMENT_DISCOUNT": "تخفیفِ نقدیِ دریافت‌شده به مبلغِ {مبلغ} ریال از {طرف_حساب}",
    "PAYMENT_CHECK_DISBURSEMENT": "پرداخت با خرجِ {تعداد} فقره چکِ دریافتی به مبلغِ {مبلغ} ریال به {طرف_حساب}",
    "PAYMENT_NETTING": "تهاترِ حساب به مبلغِ {مبلغ} ریال با {طرف_حساب}",
    "CHECK_RECEIVED_CUSTOMER_RETURN": "برگشتِ چکِ دریافتیِ نزدِ صندوق به طرفِ‌حساب به مبلغِ {مبلغ} ریال",
    "CHECK_RECEIVED_ENDORSED_RETURN": "برگشتِ چکِ خرجی‌شده به صندوق به مبلغِ {مبلغ} ریال",
}


@dataclass
class DescriptionTemplateRow:
    template_key: str
    label: str
    template_text: str
    is_default: bool


def get_description_template(company_id: int, template_key: str) -> str:
    with new_session() as session:
        row = session.get(DescriptionTemplate, (company_id, template_key))
        if row is not None:
            return row.template_text
    return DEFAULT_DESCRIPTION_TEMPLATES.get(template_key, "")


def set_description_template(company_id: int, template_key: str, template_text: str) -> None:
    with new_session() as session:
        existing = session.get(DescriptionTemplate, (company_id, template_key))
        if existing is None:
            session.add(DescriptionTemplate(company_id=company_id, template_key=template_key, template_text=template_text))
        else:
            existing.template_text = template_text
        session.commit()


def list_description_templates(company_id: int, direction: str) -> list[DescriptionTemplateRow]:
    keys = [k for k in DEFAULT_DESCRIPTION_TEMPLATES if k.startswith(f"{direction}_")]
    with new_session() as session:
        saved = {
            r.template_key: r.template_text
            for r in session.scalars(
                select(DescriptionTemplate).where(
                    DescriptionTemplate.company_id == company_id, DescriptionTemplate.template_key.in_(keys)
                )
            ).all()
        }
    return [
        DescriptionTemplateRow(
            template_key=key,
            label=MAPPING_LABELS.get(key, key),
            template_text=saved.get(key, DEFAULT_DESCRIPTION_TEMPLATES[key]),
            is_default=key not in saved,
        )
        for key in keys
    ]


class _SafeFormatDict(dict):
    def __missing__(self, key):
        return ""


def render_description_template(template_text: str, context: dict[str, str]) -> str:
    """جایگذاریِ امنِ جای‌گذارهایِ قالب — کلیدِ ناشناخته/نبود به‌جایِ خطا،
    رشته‌یِ خالی می‌شود؛ فرمتِ نامعتبر هم به‌جایِ کرش، همان متنِ خام را
    برمی‌گرداند (تایپوی کاربر در قالب نباید فرم را از کار بیندازد)."""
    try:
        return template_text.format_map(_SafeFormatDict(context)).strip()
    except (ValueError, IndexError, KeyError):
        return template_text


# --- بانک‌هایِ مرجع -----------------------------------------------------------


@dataclass
class BankRow:
    bank_id: int
    code: str | None
    name: str
    is_active: bool


def list_banks(company_id: int, active_only: bool = False) -> list[BankRow]:
    with new_session() as session:
        query = select(Bank).where(Bank.company_id == company_id)
        if active_only:
            query = query.where(Bank.is_active.is_(True))
        rows = session.scalars(query.order_by(Bank.name)).all()
        return [BankRow(bank_id=r.bank_id, code=r.code, name=r.name, is_active=r.is_active) for r in rows]


def create_bank(company_id: int, name: str, code: str = "") -> BankRow:
    name = name.strip()
    if not name:
        raise ValueError("نامِ بانک نمی‌تواند خالی باشد.")
    with new_session() as session:
        bank = Bank(company_id=company_id, name=name, code=code.strip() or None, is_active=True)
        session.add(bank)
        session.commit()
        session.refresh(bank)
        return BankRow(bank_id=bank.bank_id, code=bank.code, name=bank.name, is_active=bank.is_active)


def update_bank(bank_id: int, company_id: int, name: str, code: str = "") -> None:
    name = name.strip()
    if not name:
        raise ValueError("نامِ بانک نمی‌تواند خالی باشد.")
    with new_session() as session:
        bank = session.get(Bank, bank_id)
        if bank is None or bank.company_id != company_id:
            raise ValueError("بانک نامعتبر است.")
        bank.name = name
        bank.code = code.strip() or None
        session.commit()


def delete_bank(bank_id: int, company_id: int) -> None:
    with new_session() as session:
        bank = session.get(Bank, bank_id)
        if bank is None or bank.company_id != company_id:
            raise ValueError("بانک نامعتبر است.")
        # طبقِ الگویِ رفعِ باگِ گروه‌هایِ تفصیلی: FKِ خامِ بدونِ چک، خطایِ
        # IntegrityErrorِ غیرِقابلِ‌مدیریت در UI می‌دهد — این‌جا هم چک/بچِ
        # حقوقی که به این بانک ارجاع دارند باید صریحاً بررسی شوند.
        usage_count = session.scalar(
            select(func.count())
            .select_from(ReceivedCheck)
            .where(ReceivedCheck.bank_id == bank_id)
        )
        usage_count += session.scalar(
            select(func.count())
            .select_from(IssuedCheck)
            .where(IssuedCheck.payee_bank_id == bank_id)
        )
        if usage_count:
            raise ValueError("این بانک در چک‌هایِ ثبت‌شده استفاده شده؛ قابلِ‌حذف نیست.")
        session.delete(bank)
        session.commit()


# --- تنظیماتِ نگاشتِ حساب‌ها -------------------------------------------------


@dataclass
class AccountMappingRow:
    mapping_key: str
    label: str
    account_id: int | None
    account_label: str | None
    detail_account_id: int | None = None
    detail_account_label: str | None = None


def list_account_mappings(company_id: int) -> list[AccountMappingRow]:
    """یک ردیفِ خلاصه به‌ازایِ هر mapping_key — برایِ کلیدهایی که طبقِ آیتمِ
    ۹ ممکن است چند معین داشته باشند (RECEIPT_*)، فقط اولین معینِ تنظیم‌شده
    نشان داده می‌شود (فهرستِ کاملشان: list_mapped_accounts_for_key)."""
    with new_session() as session:
        rows: dict[str, tuple[int, int | None]] = {}
        for m in session.scalars(
            select(TreasuryAccountMapping)
            .where(TreasuryAccountMapping.company_id == company_id)
            .order_by(TreasuryAccountMapping.account_id)
        ).all():
            rows.setdefault(m.mapping_key, (m.account_id, m.detail_account_id))
    accounts_by_id = {a.account_id: f"{a.full_code} — {a.name}" for a in coa_service.list_accounts(company_id)}
    details_by_id = {
        d.detail_account_id: (f"{d.full_code} — {d.name}" if d.name else d.full_code)
        for d in dimensions_service.list_all_leaf_detail_accounts(company_id)
    }
    result = []
    for key in MAPPING_KEYS:
        account_id, detail_account_id = rows.get(key, (None, None))
        result.append(
            AccountMappingRow(
                mapping_key=key,
                label=MAPPING_LABELS[key],
                account_id=account_id,
                account_label=accounts_by_id.get(account_id) if account_id is not None else None,
                detail_account_id=detail_account_id,
                detail_account_label=details_by_id.get(detail_account_id) if detail_account_id is not None else None,
            )
        )
    return result


def _mapping_rows_query(session, company_id: int, mapping_key: str):
    return session.scalars(
        select(TreasuryAccountMapping).where(
            TreasuryAccountMapping.company_id == company_id,
            TreasuryAccountMapping.mapping_key == mapping_key,
        )
    ).all()


def set_account_mapping(company_id: int, mapping_key: str, account_id: int, detail_account_id: int | None = None) -> None:
    """نگاشتِ تک‌معینیِ قدیمی — همه‌ی ردیف‌هایِ این کلید را با فقط همین یک
    معین جایگزین می‌کند (برایِ کلیدهایی مثلِ PAYMENT_*/CHECK_* که طبقِ
    خواسته‌یِ صریحِ کاربر همچنان فقط یک معین دارند)."""
    set_account_mappings(company_id, mapping_key, [(account_id, detail_account_id)])


def _is_valid_custom_method_mapping_key(company_id: int, mapping_key: str) -> bool:
    for direction in ("RECEIPT", "PAYMENT"):
        prefix = f"{direction}_CUSTOM_"
        if not mapping_key.startswith(prefix):
            continue
        try:
            custom_method_id = int(mapping_key[len(prefix):])
        except ValueError:
            return False
        with new_session() as session:
            row = session.get(CustomMethod, custom_method_id)
            return row is not None and row.company_id == company_id and row.direction == direction
    return False


def set_account_mappings(company_id: int, mapping_key: str, entries: list[tuple[int, int | None]]) -> None:
    """طبقِ آیتمِ ۹: جایگزینِ کاملِ همه‌ی ردیف‌هایِ یک mapping_key — هر ورودی
    یک (account_id, detail_account_id) است. برایِ RECEIPT_* اجازه می‌دهد
    چند معین هم‌زمان تنظیم شود؛ برایِ بقیه‌یِ کلیدها معمولاً یک ورودی."""
    # طبقِ آیتمِ ۷: کلیدهایِ روش‌هایِ سفارشی (مثلِ RECEIPT_CUSTOM_5) در
    # MAPPING_LABELِ ثابت نیستند — چون هر شرکت روش‌هایِ خودش را دارد؛
    # این‌ها با وجودِ همان custom_method_id در جدولِ سفارشی‌ها تایید می‌شوند.
    if mapping_key not in MAPPING_LABELS and not _is_valid_custom_method_mapping_key(company_id, mapping_key):
        raise ValueError("کلیدِ نگاشتِ نامعتبر است.")
    with new_session() as session:
        for existing in _mapping_rows_query(session, company_id, mapping_key):
            session.delete(existing)
        session.flush()
        for account_id, detail_account_id in entries:
            session.add(
                TreasuryAccountMapping(
                    company_id=company_id,
                    mapping_key=mapping_key,
                    account_id=account_id,
                    detail_account_id=detail_account_id,
                )
            )
        session.commit()


def _get_mapped_account_id(session, company_id: int, mapping_key: str) -> int:
    mapping = next(iter(_mapping_rows_query(session, company_id, mapping_key)), None)
    if mapping is None:
        raise ValueError(
            f"حسابِ «{MAPPING_LABELS[mapping_key]}» هنوز در تنظیماتِ خزانه‌داری مشخص نشده است."
        )
    return mapping.account_id


def get_account_mapping(company_id: int, mapping_key: str) -> int | None:
    """نگاشتِ یک روش را برمی‌گرداند (یا None اگر هنوز تنظیم نشده) — برایِ
    UI که می‌خواهد بُعدِ الزامیِ همان معین را از رویِ آن استنتاج کند
    (مثلاً کدام تفصیلی برایِ ردیفِ نقدی/تخفیف/کالابرگ نشان داده شود)،
    بدونِ ریسکِ raise شدنِ خطا در میانه‌یِ رفرشِ فرم. اگر چند معین تنظیم
    شده باشد (RECEIPT_*)، اولین‌شان برمی‌گردد."""
    with new_session() as session:
        mapping = next(iter(_mapping_rows_query(session, company_id, mapping_key)), None)
        return mapping.account_id if mapping is not None else None


def get_account_mapping_with_detail(company_id: int, mapping_key: str) -> tuple[int | None, int | None]:
    """مثلِ get_account_mapping، به‌همراهِ تفصیلیِ اختصاصیِ از‌پیش‌تخصیص‌یافته
    (اگر در تنظیمات مشخص شده باشد) — برایِ فرمِ سند تا اگر تفصیلی از پیش
    معلوم است، دیگر از کاربر دوباره نپرسد. فقط وقتی دقیقاً یک معین تنظیم
    شده باشد معنی دارد؛ اگر چند معین باشد، پیش‌تخصیص نادیده گرفته می‌شود
    (list_mapped_accounts_for_key/آیتمِ ۹ برایِ حالتِ چندمعینی مصرف می‌شود)."""
    with new_session() as session:
        rows = _mapping_rows_query(session, company_id, mapping_key)
        if len(rows) != 1:
            return (rows[0].account_id, None) if rows else (None, None)
        return rows[0].account_id, rows[0].detail_account_id


@dataclass
class MappedAccountRow:
    account_id: int
    account_label: str
    detail_account_id: int | None
    detail_account_label: str | None


def list_mapped_accounts_for_key(company_id: int, mapping_key: str) -> list[MappedAccountRow]:
    """طبقِ آیتمِ ۹: همه‌ی معین‌هایِ تنظیم‌شده برایِ یک mapping_key (نه فقط
    یکی) — فرمِ سند موقعِ ثبت، تفصیلی‌هایِ همه‌شان را با هم union می‌کند."""
    with new_session() as session:
        raw = [(m.account_id, m.detail_account_id) for m in _mapping_rows_query(session, company_id, mapping_key)]
    accounts_by_id = {a.account_id: f"{a.full_code} — {a.name}" for a in coa_service.list_accounts(company_id)}
    details_by_id = {
        d.detail_account_id: (f"{d.full_code} — {d.name}" if d.name else d.full_code)
        for d in dimensions_service.list_all_leaf_detail_accounts(company_id)
    }
    return [
        MappedAccountRow(
            account_id=account_id,
            account_label=accounts_by_id.get(account_id, ""),
            detail_account_id=detail_account_id,
            detail_account_label=details_by_id.get(detail_account_id) if detail_account_id is not None else None,
        )
        for account_id, detail_account_id in raw
    ]


@dataclass
class CustomMethodRow:
    custom_method_id: int
    direction: str
    code: str
    label: str
    is_active: bool
    sort_order: int


def custom_method_mapping_key(direction: str, custom_method_id: int) -> str:
    """کلیدِ نگاشتِ حسابِ کلِ یک روشِ سفارشی — چون custom_method_id
    منحصربه‌فردِ کلِ جدول است (نه فقط هر شرکت)، این کلید هم بینِ همه‌یِ
    شرکت‌ها منحصربه‌فرد می‌ماند."""
    return f"{direction}_CUSTOM_{custom_method_id}"


def create_custom_method(company_id: int, direction: str, code: str, label: str) -> CustomMethodRow:
    """طبقِ آیتمِ ۷ (درخواستِ صریح: «بتونیم روش پرداخت و دریافت خودمون
    درست کنیم غیر از موارد پیش‌فرض») — بر اساسِ توافقِ تاییدشده با کاربر،
    روشِ سفارشی «ساده» است (مثلِ نقد/تخفیف/بن): فقط مبلغ + تفصیلیِ اختیاری
    که به یک حسابِ کلِ ثابت می‌رود؛ نگاشتِ همان حسابِ کل جداگانه، از همان
    فرمِ تنظیماتِ روش‌هایِ موجود (set_account_mapping/set_account_mappings
    با mapping_key حاصل از custom_method_mapping_key) تنظیم می‌شود."""
    if direction not in ("RECEIPT", "PAYMENT"):
        raise ValueError("جهتِ روش نامعتبر است.")
    code = code.strip()
    label = label.strip()
    if not code or not label:
        raise ValueError("کد و برچسبِ روش را وارد کنید.")
    with new_session() as session:
        existing = session.scalar(
            select(CustomMethod).where(
                CustomMethod.company_id == company_id,
                CustomMethod.direction == direction,
                CustomMethod.code == code,
            )
        )
        if existing is not None:
            raise ValueError("روشی با همین کد از قبل وجود دارد.")
        max_sort = session.scalar(
            select(func.max(CustomMethod.sort_order)).where(
                CustomMethod.company_id == company_id, CustomMethod.direction == direction
            )
        )
        row = CustomMethod(
            company_id=company_id, direction=direction, code=code, label=label,
            is_active=True, sort_order=(max_sort or 0) + 1,
        )
        session.add(row)
        session.commit()
        return CustomMethodRow(
            custom_method_id=row.custom_method_id, direction=row.direction, code=row.code,
            label=row.label, is_active=row.is_active, sort_order=row.sort_order,
        )


def list_custom_methods(company_id: int, direction: str, *, active_only: bool = False) -> list[CustomMethodRow]:
    with new_session() as session:
        stmt = select(CustomMethod).where(
            CustomMethod.company_id == company_id, CustomMethod.direction == direction
        )
        if active_only:
            stmt = stmt.where(CustomMethod.is_active.is_(True))
        stmt = stmt.order_by(CustomMethod.sort_order, CustomMethod.custom_method_id)
        return [
            CustomMethodRow(
                custom_method_id=r.custom_method_id, direction=r.direction, code=r.code,
                label=r.label, is_active=r.is_active, sort_order=r.sort_order,
            )
            for r in session.scalars(stmt).all()
        ]


def set_custom_method_active(company_id: int, custom_method_id: int, is_active: bool) -> None:
    with new_session() as session:
        row = session.get(CustomMethod, custom_method_id)
        if row is None or row.company_id != company_id:
            raise ValueError("روشِ سفارشی یافت نشد.")
        row.is_active = is_active
        session.commit()


def delete_custom_method(company_id: int, custom_method_id: int) -> None:
    """حذفِ کاملِ روش — چون سندهایِ قبلاً ثبت‌شده فقط به account_id (نه
    خودِ کدِ روش) وصل‌اند، حذفِ این ردیف به سندهایِ قدیمی آسیبی نمی‌زند؛
    نگاشتِ حسابِ متناظر (اگر تنظیم شده بود) هم همراه حذف می‌شود."""
    with new_session() as session:
        row = session.get(CustomMethod, custom_method_id)
        if row is None or row.company_id != company_id:
            raise ValueError("روشِ سفارشی یافت نشد.")
        mapping_key = custom_method_mapping_key(row.direction, custom_method_id)
        session.execute(
            TreasuryAccountMapping.__table__.delete().where(
                TreasuryAccountMapping.company_id == company_id, TreasuryAccountMapping.mapping_key == mapping_key
            )
        )
        session.delete(row)
        session.commit()


def compute_check_ras(
    entries: list[tuple[decimal.Decimal, datetime.date]], base_date: datetime.date | None = None
) -> tuple[datetime.date, decimal.Decimal]:
    """طبقِ آیتمِ ۶: «راس‌گیریِ» چند چک با سررسیدهایِ مختلف — تاریخِ
    میانگینِ وزنی (بر اساسِ مبلغِ هر چک) که معادلِ تنزیل/بهره‌یِ همه‌ی
    چک‌ها با یک تاریخِ واحد است:

        روزهایِ راس = Σ(مبلغ_i × (سررسید_i − تاریخِ‌مبنا)) / Σ(مبلغ_i)
        تاریخِ راس = تاریخِ‌مبنا + روزهایِ راس

    خروجی: (تاریخِ راس، جمعِ مبالغ). اگر فهرست خالی یا جمعِ مبالغ صفر
    باشد، تاریخِ‌مبنا (پیش‌فرض: امروز) بدونِ تغییر برمی‌گردد."""
    base = base_date or datetime.date.today()
    total = sum((amount for amount, _due in entries), decimal.Decimal(0))
    if not entries or total <= 0:
        return base, decimal.Decimal(0)
    weighted_days = sum((amount * (due - base).days for amount, due in entries), decimal.Decimal(0))
    avg_days = round(float(weighted_days / total))
    return base + datetime.timedelta(days=avg_days), total


def get_counterparty_balance(company_id: int, detail_account_id: int) -> tuple[decimal.Decimal, str]:
    """طبقِ آیتمِ ۸: ماندهٔ فعلیِ یک طرفِ‌حسابِ خاص (خالصِ همه‌یِ گردش‌هایِ
    ثبت‌شده تا امروز، بدونِ اسنادِ پیش‌نویس) + ماهیتِ همان مانده. طبقِ
    قراردادِ استانداردِ حسابداری: اگر خالصِ بدهکار از بستانکار بیشتر باشد،
    طرفِ‌حساب به ما بدهکار است («بدهکار»)؛ وگرنه ما به او بدهکاریم
    («بستانکار»)."""
    with new_session() as session:
        query = (
            select(
                func.coalesce(func.sum(JournalEntryLine.debit_amount_base), 0),
                func.coalesce(func.sum(JournalEntryLine.credit_amount_base), 0),
            )
            .join(JournalEntryLineDetail, JournalEntryLineDetail.line_id == JournalEntryLine.line_id)
            .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
            .join(JournalEntryStatus, JournalEntryStatus.status_id == JournalEntry.status_id)
            .where(
                JournalEntry.company_id == company_id,
                JournalEntryLineDetail.detail_account_id == detail_account_id,
                JournalEntryStatus.code != "DRAFT",
            )
        )
        debit, credit = session.execute(query).one()
    net = decimal.Decimal(debit) - decimal.Decimal(credit)
    nature = "بدهکار" if net >= 0 else "بستانکار"
    return abs(net), nature


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


# طبقِ درخواستِ صریح: مرکزِ هزینه/پروژه (اگر رویِ حسابِ طرف‌حساب الزامی
# باشند) باید بینِ همه‌ی ردیف‌هایِ یک سند مشترک باشند — نه فقط ردیفِ
# طرف‌حساب — چون این دو نوع‌بُعد ویژگیِ خودِ رویدادِ مالی‌اند (این تراکنش
# مربوط به کدام مرکزِ هزینه/پروژه است)، نه ویژگیِ یک طرفِ حسابِ خاص.
_SHARED_DIMENSION_CODES = (dimensions_service.COST_CENTER_CODE, dimensions_service.PROJECT_CODE)


# --- نگاشتِ نوعِ تفصیلی <-> معین (دریافت/پرداخت) ------------------------------
# طبقِ درخواستِ صریح: هر ردیف یک «نوعِ تفصیلی» (مثلاً «مشتری») را به یک
# معینِ حساب نگاشت می‌کند — سمتِ بستانکار برایِ دریافت، سمتِ بدهکار برایِ
# پرداخت. «نوعِ تفصیلی» یا یک گروهِ تفصیلیِ اشخاص است (person_group_id) یا
# یک نوع‌بُعدِ غیرِشخصی (dimension_type_id) — دقیقاً یکی از این دو.


@dataclass
class CounterpartyMappingRow:
    mapping_id: int
    direction: str
    person_group_id: int | None
    dimension_type_id: int | None
    group_label: str
    account_id: int
    account_label: str


def list_counterparty_mappings(company_id: int, direction: str | None = None) -> list[CounterpartyMappingRow]:
    with new_session() as session:
        query = select(CounterpartyAccountMapping).where(CounterpartyAccountMapping.company_id == company_id)
        if direction is not None:
            query = query.where(CounterpartyAccountMapping.direction == direction)
        rows = session.scalars(query.order_by(CounterpartyAccountMapping.mapping_id)).all()

    accounts_by_id = {a.account_id: f"{a.full_code} — {a.name}" for a in coa_service.list_accounts(company_id)}
    person_groups_by_id = {g.person_group_id: g.name for g in dimensions_service.list_person_groups(company_id)}
    dim_types_by_id = {
        t.dimension_type_id: dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(t.code, t.code)
        for t in dimensions_service.list_dimension_types(company_id)
    }
    result: list[CounterpartyMappingRow] = []
    for r in rows:
        group_label = (
            person_groups_by_id.get(r.person_group_id, "")
            if r.person_group_id is not None
            else dim_types_by_id.get(r.dimension_type_id, "")
        )
        result.append(
            CounterpartyMappingRow(
                mapping_id=r.mapping_id,
                direction=r.direction,
                person_group_id=r.person_group_id,
                dimension_type_id=r.dimension_type_id,
                group_label=group_label,
                account_id=r.account_id,
                account_label=accounts_by_id.get(r.account_id, ""),
            )
        )
    return result


def create_counterparty_mapping(
    company_id: int,
    direction: str,
    account_id: int,
    person_group_id: int | None = None,
    dimension_type_id: int | None = None,
) -> None:
    if direction not in ("RECEIPT", "PAYMENT"):
        raise ValueError("جهت نامعتبر است.")
    if (person_group_id is None) == (dimension_type_id is None):
        raise ValueError("دقیقاً یکی از گروهِ تفصیلی/نوعِ تفصیلی باید مشخص شود.")
    with new_session() as session:
        session.add(
            CounterpartyAccountMapping(
                company_id=company_id,
                direction=direction,
                person_group_id=person_group_id,
                dimension_type_id=dimension_type_id,
                account_id=account_id,
            )
        )
        session.commit()


def delete_counterparty_mapping(mapping_id: int, company_id: int) -> None:
    with new_session() as session:
        row = session.get(CounterpartyAccountMapping, mapping_id)
        if row is None or row.company_id != company_id:
            raise ValueError("ردیف نامعتبر است.")
        session.delete(row)
        session.commit()


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
    received_check_id: int | None = None  # فقط CHECK_DISBURSEMENT — کدام چکِ دریافتیِ نزدِ صندوق خرج می‌شود (تک‌چکی، برایِ سازگاری با فرمِ قدیمی)
    # فقط CHECK_DISBURSEMENT — طبقِ درخواستِ صریح: یک ردیفِ خرجِ چک هم
    # می‌تواند چند چکِ دریافتی را هم‌زمان خرج کند. اگر پر باشد، جایگزینِ
    # received_check_id تکی بالا می‌شود.
    received_check_ids: list[int] | None = None
    # فقط CHECK در دریافت — طبقِ درخواستِ صریح، یک ردیف می‌تواند چند چکِ
    # دریافتی را هم‌زمان دربرگیرد؛ هرکدام یک دیکشنری با کلیدهایِ check_no،
    # check_serial، bank_id، check_bank_name، iban، bank_account_no،
    # due_date، party_name، national_id، phone، amount. اگر پر باشد،
    # جایگزینِ فیلدهایِ تکیِ check_no/check_bank_name/... بالا می‌شود.
    checks: list[dict] | None = None
    # فقط CHECK/CHECK_DISBURSEMENT — طبقِ باگ‌فیکسِ گزارش‌شده: این دو روش
    # فیلدِ تخصصیِ خودشان را برایِ detail_account_id دارند (حسابِ بانکیِ
    # صادرکننده / چکِ دریافتیِ خرج‌شونده)، پس اگر معینِ نگاشته‌شده‌یِ همان
    # روش، جدا از آن، به یک گروهِ شخص هم محدود شده باشد (مثلاً «فقط
    # مشتری/تامین‌کننده»)، این فیلدِ دومِ تفصیلی همان محدودیت را حمل می‌کند.
    person_detail_account_id: int | None = None
    # طبقِ آیتمِ ۹: وقتی چند معین برایِ mapping_key این روش تنظیم شده باشد،
    # کاربر از میانِ تفصیلی‌هایِ unionِ همه‌شان یکی را انتخاب می‌کند — این
    # فیلد همان معینِ متناظر با انتخابش را حمل می‌کند تا به‌جایِ resolveِ
    # خودکار (که در حالتِ چندمعینی مبهم است) مستقیم استفاده شود. اگر فقط
    # یک معین تنظیم شده باشد، همیشه None می‌ماند و رفتار دقیقاً مثلِ قبل
    # از رویِ mapping_key به‌تنهایی resolve می‌شود.
    account_id_override: int | None = None
    # طبقِ درخواستِ صریح («روشِ دریافت/پرداختِ اقساطی»): فقط برایِ
    # method == "INSTALLMENT" -- کدام فاکتورِ ثبت‌شده (همانِ طرفِ‌حسابِ
    # سند) قرار است طیِ چند قسط دریافت/پرداخت شود، به همراهِ تعدادِ اقساط
    # و تاریخِ سررسیدِ اولین قسط (بقیه هرکدام ۳۰ روز بعدِ قبلی).
    installment_document_id: int | None = None
    installment_count: int | None = None
    installment_first_due_date: datetime.date | None = None
    # طبقِ موردِ ۵ («روشِ اقساط منوط به فاکتور نباشد»): installment_document_id
    # حالا اختیاری است -- اگر None باشد، طرحِ اقساط بدونِ فاکتور و رویِ
    # مبلغِ آزادِ همین ردیف (ml.amount به‌عنوانِ اصلِ مبلغ) ساخته می‌شود،
    # با استفاده از company_id/طرفِ‌حسابِ شخصِ همین سند.
    # طبقِ موردِ ۶ («درصدِ بهره/هزینه‌یِ متفرقه + فاصله‌یِ سررسیدِ آزاد»):
    # این سه فیلد اختیاری‌اند (پیش‌فرض بدونِ بهره/هزینه، فاصله‌یِ ۳۰روزه --
    # دقیقاً رفتارِ قبلی) و فقط برایِ method == "INSTALLMENT" معنا دارند.
    installment_interest_rate_percent: decimal.Decimal | None = None
    installment_misc_fee_amount: decimal.Decimal | None = None
    installment_due_interval_days: int | None = None
    # طبقِ همان درخواست: برایِ هر روشِ دیگر (نقد/بانک/چک/...)، اگر این
    # ردیف در واقع وصولِ یکی از همان اقساطِ ازپیش‌برنامه‌ریزی‌شده باشد،
    # با تنظیمِ همین فیلد، آن قسط PAID علامت می‌خورد و خودکار به‌عنوانِ
    # یک تسویه (comm.invoice_settlements) رویِ فاکتورِ اصلیِ همان طرح هم
    # ثبت می‌شود -- هم‌افزایی با سیستمِ تسویه‌یِ فاکتورها.
    collect_installment_line_id: int | None = None


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
    currency_id: int | None = None,
    exchange_rate: decimal.Decimal | None = None,
    as_draft: bool = False,
    entry_type_code: str | None = None,
) -> je_service.JournalEntryResult:
    """طبقِ طرحِ تاییدشده: یک طرف‌حساب (بستانکار در دریافت، بدهکار در
    پرداخت) و چند ردیفِ روش (نقد/بانک/چک/تخفیف) که هرکدام طبقِ نگاشتِ
    تنظیماتِ خزانه‌داری به حسابِ کلِ خودش می‌رود — همه در یک سندِ حسابداریِ
    واحد، رویِ همان create_journal_entry موجود.

    currency_id/exchange_rate: طبقِ درخواستِ صریح («دریافتِ ارزی هم داشته
    باشیم»)؛ None یعنی ارزِ پایه‌یِ شرکت (رفتارِ قبلی، بدونِ تغییر). اگر
    پر باشند، همه‌یِ ردیف‌هایِ همین سند (طرفِ‌حساب + هر روش) با همان یک
    ارز/نرخ ثبت می‌شوند — create_journal_entry خودش تبدیل به ارزِ پایه و
    تراز کردن را انجام می‌دهد (هم‌الگو با ارزِ سندِ حسابداریِ عمومی)."""
    if direction not in ("RECEIPT", "PAYMENT"):
        raise ValueError("جهتِ سند نامعتبر است.")
    if not method_lines:
        raise ValueError("حداقل یک ردیفِ روش (نقد/بانک/چک/تخفیف) لازم است.")
    # طبقِ آیتمِ ۷: روش‌هایِ سفارشیِ همین شرکت/جهت هم (کدشان با CUSTOM_
    # شروع می‌شود) کنارِ روش‌هایِ ثابتِ بالا مجازند — فعال‌بودنشان همین‌جا
    # بررسی می‌شود تا روشی که بعداً غیرفعال/حذف شده دیگر قابلِ ثبت نباشد.
    active_custom_codes = {
        f"CUSTOM_{cm.custom_method_id}" for cm in list_custom_methods(company_id, direction, active_only=True)
    }
    for ml in method_lines:
        if ml.method not in METHOD_CODES and ml.method not in active_custom_codes:
            raise ValueError("روشِ ردیف نامعتبر است.")
        if ml.amount <= 0:
            raise ValueError("مبلغِ هر ردیف باید مثبت باشد.")
        if ml.method == "INSTALLMENT":
            # طبقِ موردِ ۵: installment_document_id دیگر الزامی نیست --
            # نبودنش یعنی طرحِ اقساطِ آزاد (بدونِ فاکتور)، که در ادامه
            # (پس از تعیینِ counterparty_person_detail_id) اعتبارسنجی می‌شود.
            if ml.installment_count is None or ml.installment_first_due_date is None:
                raise ValueError("برایِ روشِ اقساط، تعدادِ اقساط و تاریخِ سررسیدِ اولین قسط را مشخص کنید.")
            if ml.installment_count < 2:
                raise ValueError("تعدادِ اقساط باید حداقل ۲ باشد.")
            if ml.installment_interest_rate_percent is not None and ml.installment_interest_rate_percent < 0:
                raise ValueError("درصدِ بهرهٔ اقساط نمی‌تواند منفی باشد.")
            if ml.installment_misc_fee_amount is not None and ml.installment_misc_fee_amount < 0:
                raise ValueError("هزینهٔ متفرقهٔ اقساط نمی‌تواند منفی باشد.")
            if ml.installment_due_interval_days is not None and ml.installment_due_interval_days < 1:
                raise ValueError("فاصلهٔ سررسیدِ اقساط باید حداقل ۱ روز باشد.")

    total = sum((ml.amount for ml in method_lines), decimal.Decimal(0))

    # طبقِ گزارشِ صریح: اگر رویِ حسابِ طرف‌حساب مرکزِ هزینه/پروژه الزامی
    # باشد، همان مقدارِ انتخاب‌شده باید بینِ همه‌ی ردیف‌هایِ سند (نه فقط
    # ردیفِ طرف‌حساب) مشترک باشد.
    shared_type_ids = {
        dimensions_service.get_specialized_dimension_type_id(company_id, code) for code in _SHARED_DIMENSION_CODES
    }
    shared_details = {k: v for k, v in counterparty_details.items() if k in shared_type_ids}

    # طبقِ گزارشِ صریح: اگر معینِ نگاشته‌شده‌یِ یک روش هم به همان گروهِ
    # شخصی محدود باشد که طرفِ‌حسابِ هدر از آن انتخاب شده (مثلاً هم طرفِ‌حساب
    # هم چکِ پرداخت هردو «تامین‌کننده» می‌خواهند)، تکرارِ همان انتخاب در
    # ردیف معنی ندارد — همان تفصیلیِ هدر خودکار اعمال می‌شود. اگر روش به
    # گروهِ دیگری محدود باشد (مثلاً تهاتر با تامین‌کننده در حالی که
    # طرفِ‌حساب مشتری است)، همچنان جداگانه پرسیده می‌شود.
    person_dimension_type_id = dimensions_service.get_person_dimension_type_id(company_id)
    counterparty_person_detail_id = counterparty_details.get(person_dimension_type_id)

    with new_session() as session:
        counterparty_person_group_id = None
        if counterparty_person_detail_id is not None:
            counterparty_person_group_id = session.scalar(
                select(DetailAccount.person_group_id).where(
                    DetailAccount.detail_account_id == counterparty_person_detail_id
                )
            )

        detail_ids = {ml.detail_account_id for ml in method_lines if ml.detail_account_id is not None}
        detail_ids |= {ml.person_detail_account_id for ml in method_lines if ml.person_detail_account_id is not None}
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
            # طبقِ درخواستِ صریح: یک ردیفِ چکِ پرداختی هم می‌تواند چند چک را
            # هم‌زمان دربرگیرد (ml.checks) — در این حالت حسابِ بانکیِ
            # صادرکننده همیشه صریحاً در خودِ دیالوگ انتخاب می‌شود (نه فقط
            # از رویِ دسته‌چک)، پس این تخصیصِ زودهنگام فقط برایِ حالتِ
            # قدیمیِ تک‌چکی لازم است — شماره‌هایِ چندچکی جداگانه، در حلقه‌ی
            # ساختِ IssuedCheckها پایین‌تر، تخصیص می‌یابند.
            if ml.method == "CHECK" and direction == "PAYMENT" and ml.checkbook_id is not None and not ml.checks:
                check_no, bank_detail_id = _allocate_check_no(session, ml.checkbook_id, company_id)
                allocated_check_nos[index] = check_no
                if ml.detail_account_id is None:
                    ml.detail_account_id = bank_detail_id
                    dimension_type_by_detail_id[bank_detail_id] = session.scalar(
                        select(DetailAccount.dimension_type_id).where(DetailAccount.detail_account_id == bank_detail_id)
                    )
        # اعتبارسنجیِ چکِ خرج‌شونده (CHECK_DISBURSEMENT) هم باید همین‌جا،
        # پیش از ساختِ سند، انجام شود — نه بعد از آن.
        for ml in method_lines:
            if ml.method != "CHECK_DISBURSEMENT":
                continue
            check_ids = ml.received_check_ids or ([ml.received_check_id] if ml.received_check_id is not None else [])
            if not check_ids:
                raise ValueError("چکِ دریافتی‌ای که خرج می‌شود را انتخاب کنید.")
            for received_check_id in check_ids:
                check = session.get(ReceivedCheck, received_check_id)
                if check is None or check.company_id != company_id:
                    raise ValueError("چکِ دریافتیِ انتخاب‌شده نامعتبر است.")
                current_code = session.scalar(select(CheckStatus.code).where(CheckStatus.status_id == check.status_id))
                if current_code not in ("IN_HAND", "DEPOSITED"):
                    raise ValueError(f"چکِ شماره‌ی {check.check_no} دیگر قابلِ خرج‌کردن نیست.")

        # اعتبارسنجیِ روشِ اقساط (INSTALLMENT) -- اگر فاکتور انتخاب شده،
        # باید متعلق به همین شرکت، ثبتِ‌نهایی‌شده، از نوعِ فروش/خرید، و
        # هم‌طرفِ‌حسابِ همین سند باشد؛ اگر فاکتور انتخاب نشده (طرحِ اقساطِ
        # آزاد -- موردِ ۵)، طرحِ اقساط به تفصیلیِ شخصِ همین سند
        # (counterparty_person_detail_id) وصل می‌شود -- برایِ همین، سند
        # باید دارایِ تفصیلیِ شخص باشد.
        for ml in method_lines:
            if ml.method != "INSTALLMENT":
                continue
            if ml.installment_document_id is None:
                if counterparty_person_detail_id is None:
                    raise ValueError("برایِ طرحِ اقساطِ بدونِ فاکتور، طرفِ‌حسابِ سند باید دارایِ تفصیلیِ شخص باشد.")
                continue
            doc = session.get(CommercialDocument, ml.installment_document_id)
            if doc is None or doc.company_id != company_id:
                raise ValueError("فاکتورِ انتخاب‌شده برایِ اقساط نامعتبر است.")
            if doc.document_type_code not in ("SALES_INVOICE", "PURCHASE_INVOICE"):
                raise ValueError("اقساط فقط برایِ فاکتورِ فروش/خرید ممکن است.")
            if doc.status_code != "POSTED":
                raise ValueError("فقط فاکتورِ ثبتِ‌نهایی‌شده قابلِ‌تقسیط است.")
            if doc.counterparty_detail_account_id != counterparty_account_id:
                raise ValueError("طرفِ‌حسابِ فاکتورِ انتخاب‌شده با طرفِ‌حسابِ این سند یکی نیست.")

        # اعتبارسنجیِ وصولِ قسط (هر روشِ دیگری که collect_installment_line_id
        # داشته باشد) -- قسط باید معتبر، متعلق به همین شرکت، و هنوز
        # پرداخت‌نشده باشد.
        for ml in method_lines:
            if ml.collect_installment_line_id is None:
                continue
            line = installments_service.get_installment_line(ml.collect_installment_line_id)
            if line is None:
                raise ValueError("قسطِ انتخاب‌شده نامعتبر است.")
            if line.status_code == "PAID":
                raise ValueError("این قسط قبلاً دریافت/پرداخت شده است.")
            plan = installments_service.get_installment_plan(line.plan_id)
            if plan is None:
                raise ValueError("طرحِ اقساطِ مربوط به این قسط یافت نشد.")
            if plan.document_id is not None:
                plan_doc = session.get(CommercialDocument, plan.document_id)
                if plan_doc is None or plan_doc.company_id != company_id:
                    raise ValueError("قسطِ انتخاب‌شده متعلق به این شرکت نیست.")
            elif plan.company_id != company_id:
                raise ValueError("قسطِ انتخاب‌شده متعلق به این شرکت نیست.")

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
                currency_id=currency_id,
                exchange_rate=exchange_rate,
            )
        )

        for ml in method_lines:
            mapping_key = f"{direction}_{ml.method}"
            account_id = ml.account_id_override or _get_mapped_account_id(session, company_id, mapping_key)
            details: dict[int, int] = dict(shared_details)
            if counterparty_person_group_id is not None:
                required_person_group_ids = {
                    g.person_group_id for g in dimensions_service.get_required_person_groups_for_account(account_id)
                }
                if counterparty_person_group_id in required_person_group_ids:
                    details[person_dimension_type_id] = counterparty_person_detail_id
            if ml.detail_account_id is not None:
                dimension_type_id = dimension_type_by_detail_id.get(ml.detail_account_id)
                if dimension_type_id is not None:
                    details[dimension_type_id] = ml.detail_account_id
            if ml.person_detail_account_id is not None:
                person_dimension_type_id = dimension_type_by_detail_id.get(ml.person_detail_account_id)
                if person_dimension_type_id is not None:
                    details[person_dimension_type_id] = ml.person_detail_account_id
            # طبقِ موردِ ۶: برایِ روشِ اقساط، اگر درصدِ بهره/هزینه‌یِ متفرقه
            # تنظیم شده باشد، مبلغِ این ردیف (که رویِ حسابِ دریافتنی/
            # پرداختنیِ اقساطی می‌رود) بزرگ‌تر از اصلِ مبلغ می‌شود -- چون
            # آن حساب باید کلِ مبلغِ نهاییِ قابلِ‌وصول/پرداخت را نگه دارد --
            # و سهمِ بهره/هزینه به‌صورتِ یک ردیفِ جداگانه، همین‌جا (در همان
            # سندِ ساختِ طرح) به‌عنوانِ درآمد/هزینه شناسایی می‌شود.
            installment_interest_fee = decimal.Decimal(0)
            if ml.method == "INSTALLMENT":
                rate = ml.installment_interest_rate_percent or decimal.Decimal(0)
                fee = ml.installment_misc_fee_amount or decimal.Decimal(0)
                installment_interest_fee = _money(ml.amount * rate / decimal.Decimal(100)) + fee
            method_amount = ml.amount + installment_interest_fee
            line_debit = method_amount if direction == "RECEIPT" else decimal.Decimal(0)
            line_credit = method_amount if direction == "PAYMENT" else decimal.Decimal(0)
            lines.append(
                je_service.LineInput(
                    account_id=account_id,
                    description=ml.description or description,
                    debit=line_debit,
                    credit=line_credit,
                    details=details,
                    currency_id=currency_id,
                    exchange_rate=exchange_rate,
                )
            )
            if installment_interest_fee > 0:
                interest_account_id = _get_mapped_account_id(session, company_id, f"{direction}_INSTALLMENT_INTEREST")
                interest_debit = decimal.Decimal(0) if direction == "RECEIPT" else installment_interest_fee
                interest_credit = installment_interest_fee if direction == "RECEIPT" else decimal.Decimal(0)
                lines.append(
                    je_service.LineInput(
                        account_id=interest_account_id,
                        description=ml.description or description,
                        debit=interest_debit,
                        credit=interest_credit,
                        details=dict(shared_details),
                        currency_id=currency_id,
                        exchange_rate=exchange_rate,
                    )
                )

    result = je_service.create_journal_entry(
        company_id,
        created_by_user_id,
        document_date,
        description,
        lines,
        alternative_number=alternative_number,
        entry_type_code=entry_type_code or direction,
        as_draft=as_draft,
    )

    with new_session() as session:
        status = session.scalar(
            select(CheckStatus).where(CheckStatus.code == "ENDORSED", CheckStatus.applies_to == "RECEIVED")
        )
        status_codes = _status_code_map(session, "RECEIVED")
        for ml in method_lines:
            if ml.method != "CHECK_DISBURSEMENT":
                continue
            check_ids = ml.received_check_ids or ([ml.received_check_id] if ml.received_check_id is not None else [])
            for received_check_id in check_ids:
                check = session.get(ReceivedCheck, received_check_id)
                from_status_code = status_codes.get(check.status_id)
                check.status_id = status.status_id
                _log_check_event(
                    session, company_id, "RECEIVED", received_check_id, "ENDORSED", document_date,
                    from_status_code, "ENDORSED", result.journal_entry_id, created_by_user_id,
                )
        session.commit()

    with new_session() as session:
        for index, ml in enumerate(method_lines):
            if ml.method != "CHECK":
                continue
            if direction == "RECEIPT":
                # طبقِ درخواستِ صریح: یک ردیفِ چکِ دریافتی می‌تواند چند چکِ
                # جداگانه را دربرگیرد (checks) — اگر پر نباشد، برایِ
                # سازگاری با فرمِ قدیمی، همان یک چکِ تکیِ ml خودش ثبت می‌شود.
                status = session.scalar(
                    select(CheckStatus).where(CheckStatus.code == "IN_HAND", CheckStatus.applies_to == "RECEIVED")
                )
                check_entries = ml.checks or [
                    {
                        "check_no": ml.check_no or "",
                        "check_bank_name": ml.check_bank_name,
                        "party_name": ml.check_party_name,
                        "amount": ml.amount,
                        "due_date": ml.check_due_date,
                    }
                ]
                # طبقِ درخواستِ صریح: هر چکِ دریافتی از همین لحظه محلِ فعلیِ
                # نگه‌داری‌اش (نزدِ کدام صندوق) را ثبت می‌کند — پیش‌نیازِ
                # زنجیره‌یِ ۷مرحله‌ایِ چرخه‌یِ چک؛ ml.detail_account_id همان
                # صندوقی است که در دیالوگِ چندچکی انتخاب شد.
                receipt_check_account_id = _get_mapped_account_id(session, company_id, "RECEIPT_CHECK")
                for entry in check_entries:
                    received_check = ReceivedCheck(
                        company_id=company_id,
                        check_no=entry.get("check_no") or "",
                        drawee_bank_name=entry.get("check_bank_name"),
                        drawer_name=entry.get("party_name"),
                        amount=entry.get("amount") or ml.amount,
                        due_date=entry.get("due_date") or document_date,
                        received_date=document_date,
                        counterparty_detail_account_id=next(iter(counterparty_details.values()), None),
                        status_id=status.status_id,
                        source_journal_entry_id=result.journal_entry_id,
                        created_by_user_id=created_by_user_id,
                        check_serial=entry.get("check_serial"),
                        iban=entry.get("iban"),
                        bank_account_no=entry.get("bank_account_no"),
                        drawer_national_id=entry.get("national_id"),
                        drawer_phone=entry.get("phone"),
                        bank_id=entry.get("bank_id"),
                        current_location_account_id=receipt_check_account_id,
                        current_location_detail_account_id=ml.detail_account_id,
                        # طبقِ گزارشِ صریح: شماره‌ی ردیفِ سند (همان ترتیبی که
                        # پایین‌تر در create_journal_entry به‌کار می‌رود: ردیفِ
                        # ۱ طرفِ‌حساب، بعد یک ردیف به‌ازایِ هر روش به همان
                        # ترتیبِ method_lines) — تا حذفِ این چک بتواند دقیقاً
                        # همین یک ردیف را هدف بگیرد.
                        source_journal_entry_line_no=index + 2,
                    )
                    session.add(received_check)
                    session.flush()
                    _log_check_event(
                        session, company_id, "RECEIVED", received_check.received_check_id, "REGISTERED",
                        document_date, None, "IN_HAND", result.journal_entry_id, created_by_user_id,
                    )
            else:
                # طبقِ درخواستِ صریح: یک ردیفِ چکِ پرداختی هم می‌تواند چند
                # چکِ جداگانه را دربرگیرد (ml.checks) — اگر پر نباشد، برایِ
                # سازگاری با فرمِ قدیمی، همان یک چکِ تکیِ ml خودش ثبت می‌شود.
                status = session.scalar(
                    select(CheckStatus).where(CheckStatus.code == "ISSUED", CheckStatus.applies_to == "ISSUED")
                )
                check_entries = ml.checks or [
                    {
                        "check_no": allocated_check_nos.get(index, ml.check_no or ""),
                        "payee_name": ml.check_party_name,
                        "amount": ml.amount,
                        "due_date": ml.check_due_date,
                    }
                ]
                for entry in check_entries:
                    check_no = entry.get("check_no") or ""
                    if not check_no and ml.checkbook_id is not None:
                        check_no, _bank_detail_id = _allocate_check_no(session, ml.checkbook_id, company_id)
                    issued_check = IssuedCheck(
                        company_id=company_id,
                        checkbook_id=ml.checkbook_id,
                        check_no=check_no,
                        bank_account_detail_id=ml.detail_account_id,
                        payee_name=entry.get("payee_name") or ml.check_party_name,
                        amount=entry.get("amount") or ml.amount,
                        due_date=entry.get("due_date") or ml.check_due_date or document_date,
                        issue_date=document_date,
                        counterparty_detail_account_id=next(iter(counterparty_details.values()), None),
                        status_id=status.status_id,
                        source_journal_entry_id=result.journal_entry_id,
                        created_by_user_id=created_by_user_id,
                        check_serial=entry.get("check_serial"),
                        iban=entry.get("iban"),
                        payee_account_no=entry.get("payee_account_no"),
                        payee_national_id=entry.get("payee_national_id"),
                        payee_phone=entry.get("payee_phone"),
                        payee_bank_id=entry.get("payee_bank_id"),
                        sayad_no=entry.get("sayad_no"),
                        source_journal_entry_line_no=index + 2,
                    )
                    session.add(issued_check)
                    session.flush()
                    _log_check_event(
                        session, company_id, "ISSUED", issued_check.issued_check_id, "REGISTERED",
                        document_date, None, "ISSUED", result.journal_entry_id, created_by_user_id,
                    )
        session.commit()

    # طبقِ درخواستِ صریح («روشِ دریافت/پرداختِ اقساطی»): بعدِ ثبتِ موفقِ
    # خودِ سند -- تا خطایِ احتمالیِ بالاتر هرگز یک طرحِ اقساطِ یتیم/بی‌سند
    # نسازد -- ردیفِ INSTALLMENT طرحِ اقساط را می‌سازد، و هر ردیفی که
    # collect_installment_line_id داشته باشد آن قسط را PAID می‌کند و
    # خودکار به‌عنوانِ تسویه‌یِ همان فاکتور هم ثبت می‌شود.
    for ml in method_lines:
        if ml.method == "INSTALLMENT":
            installments_service.create_installment_plan(
                ml.installment_document_id, ml.installment_count, ml.installment_first_due_date, ml.amount,
                company_id=company_id if ml.installment_document_id is None else None,
                counterparty_detail_account_id=counterparty_person_detail_id if ml.installment_document_id is None else None,
                direction=direction if ml.installment_document_id is None else None,
                interest_rate_percent=ml.installment_interest_rate_percent or decimal.Decimal(0),
                misc_fee_amount=ml.installment_misc_fee_amount or decimal.Decimal(0),
                due_interval_days=ml.installment_due_interval_days or 30,
            )
        if ml.collect_installment_line_id is not None:
            installments_service.mark_installment_paid(ml.collect_installment_line_id, result.journal_entry_id)
            line = installments_service.get_installment_line(ml.collect_installment_line_id)
            plan = installments_service.get_installment_plan(line.plan_id)
            # طبقِ موردِ ۵: طرحِ اقساطِ بدونِ فاکتور، سندی برایِ تخصیصِ
            # تسویه ندارد -- allocate_settlement فقط برایِ طرحِ متصل‌به‌فاکتور
            # فراخوانی می‌شود.
            if plan.document_id is not None:
                settlements_service.allocate_settlement(
                    company_id, plan.document_id, result.journal_entry_id, document_date, ml.amount, created_by_user_id,
                    description=f"وصولِ قسطِ #{line.installment_no}",
                )

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
    current_location_label: str | None = None


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
        location_detail_ids = {r.current_location_detail_account_id for r in rows if r.current_location_detail_account_id}
        location_labels: dict[int, str] = {}
        if location_detail_ids:
            location_labels = {
                d.detail_account_id: d.name or d.code
                for d in session.scalars(
                    select(DetailAccount).where(DetailAccount.detail_account_id.in_(location_detail_ids))
                ).all()
            }
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
                current_location_label=location_labels.get(r.current_location_detail_account_id),
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


def _load_checks_for_stage(
    session, check_ids: list[int], company_id: int, eligible_status_codes: tuple[str, ...]
) -> list[ReceivedCheck]:
    if not check_ids:
        raise ValueError("هیچ چکی انتخاب نشده است.")
    checks = session.scalars(select(ReceivedCheck).where(ReceivedCheck.received_check_id.in_(check_ids))).all()
    if len(checks) != len(set(check_ids)):
        raise ValueError("چکِ انتخاب‌شده نامعتبر است.")
    for check in checks:
        if check.company_id != company_id:
            raise ValueError("چک نامعتبر است.")
        if session.get(CheckStatus, check.status_id).code not in eligible_status_codes:
            raise ValueError(f"چکِ شماره‌ی {check.check_no} در این مرحله قابلِ‌پردازش نیست.")
    return checks


def _detail_dict(session, detail_id: int | None) -> dict[int, int]:
    if detail_id is None:
        return {}
    detail = session.get(DetailAccount, detail_id)
    if detail is None:
        return {}
    return {detail.dimension_type_id: detail_id}


def _group_received_checks_by_source(
    session, checks: list[ReceivedCheck], company_id: int
) -> dict[tuple[int, int | None], list[ReceivedCheck]]:
    """چک‌هایِ انتخاب‌شده را بر اساسِ محلِ فعلیِ نگه‌داری‌شان (حساب+تفصیلی)
    گروه‌بندی می‌کند — هر گروه یک خطِ جداگانه در سندِ bulk می‌شود. چکِ
    بدونِ محلِ ثبت‌شده (داده‌یِ قدیمی، پیش‌ازِ این ویژگی) با حسابِ نگاشتِ
    RECEIPT_CHECK و بدونِ تفصیلی جایگزین می‌شود."""
    fallback_account_id = _get_mapped_account_id(session, company_id, "RECEIPT_CHECK")
    groups: dict[tuple[int, int | None], list[ReceivedCheck]] = {}
    for check in checks:
        key = (check.current_location_account_id or fallback_account_id, check.current_location_detail_account_id)
        groups.setdefault(key, []).append(check)
    return groups


def _validate_detail_account(session, detail_account_id: int, company_id: int) -> DetailAccount:
    detail = session.get(DetailAccount, detail_account_id)
    if detail is None or detail.company_id != company_id:
        raise ValueError("تفصیلیِ انتخاب‌شده نامعتبر است.")
    return detail


def transfer_received_checks_between_funds(
    check_ids: list[int], company_id: int, created_by_user_id: int, target_fund_detail_id: int
) -> je_service.JournalEntryResult:
    """مرحله‌ی ۱ — انتقالِ چکِ نزدِ صندوق بینِ صندوق‌ها: بدهکارِ حسابِ نگاشتِ
    CHECK_RECEIVED_FUND_TRANSFER با تفصیلیِ صندوقِ مقصد / بستانکارِ همان
    حساب با تفصیلیِ صندوق(هایِ) مبدأِ هرکدام."""
    with new_session() as session:
        checks = _load_checks_for_stage(session, check_ids, company_id, ("IN_HAND",))
        account_id = _get_mapped_account_id(session, company_id, "CHECK_RECEIVED_FUND_TRANSFER")
        _validate_detail_account(session, target_fund_detail_id, company_id)
        groups = _group_received_checks_by_source(session, checks, company_id)
        total = sum((c.amount for c in checks), decimal.Decimal(0))
        description = "انتقالِ چکِ دریافتی بینِ صندوق‌ها"
        lines = [
            je_service.LineInput(
                account_id=account_id, description=description, debit=total, credit=decimal.Decimal(0),
                details=_detail_dict(session, target_fund_detail_id),
            )
        ]
        for (src_account_id, src_detail_id), group_checks in groups.items():
            group_total = sum((c.amount for c in group_checks), decimal.Decimal(0))
            lines.append(
                je_service.LineInput(
                    account_id=src_account_id, description=description, debit=decimal.Decimal(0), credit=group_total,
                    details=_detail_dict(session, src_detail_id),
                )
            )
        from_location_by_check_id = {
            c.received_check_id: (c.current_location_account_id, c.current_location_detail_account_id) for c in checks
        }
        check_ids_processed = [c.received_check_id for c in checks]

    # طبقِ باگ‌فیکسِ گزارش‌شده: قبلاً وضعیت/محلِ چک همین‌جا commit می‌شد و
    # فقط بعد از آن سندِ حسابداری ساخته می‌شد — اگر create_journal_entry
    # (مثلاً به‌خاطرِ کمبودِ تفصیلیِ الزامیِ حسابِ مقصد) رد می‌شد، چک
    # همچنان به‌عنوانِ منتقل‌شده ثبت می‌ماند، بدونِ هیچ سندی — دقیقاً همان
    # چیزی که گزارش شد («واگذار/انتقال داد بدونِ ثبتِ سندِ حسابداری»).
    # حالا سند اول ساخته می‌شود؛ فقط اگر موفق شد، وضعیت/محلِ چک تغییر
    # می‌کند.
    event_date = datetime.date.today()
    result = je_service.create_journal_entry(
        company_id, created_by_user_id, event_date, "انتقالِ چکِ دریافتی بینِ صندوق‌ها", lines,
        entry_type_code="RECEIPT",
    )
    with new_session() as session:
        checks = session.scalars(
            select(ReceivedCheck).where(ReceivedCheck.received_check_id.in_(check_ids_processed))
        ).all()
        for check in checks:
            check.current_location_account_id = account_id
            check.current_location_detail_account_id = target_fund_detail_id
        for check_id in check_ids_processed:
            from_loc_account_id, from_loc_detail_id = from_location_by_check_id[check_id]
            _log_check_event(
                session, company_id, "RECEIVED", check_id, "FUND_TRANSFER", event_date,
                "IN_HAND", "IN_HAND", result.journal_entry_id, created_by_user_id,
                from_loc_account_id, from_loc_detail_id,
            )
        session.commit()
    return result


def collect_received_checks_cash(
    check_ids: list[int], company_id: int, created_by_user_id: int, cash_box_detail_id: int
) -> je_service.JournalEntryResult:
    """مرحله‌ی ۲ — وصولِ نقدیِ چکِ نزدِ صندوق: بدهکارِ حسابِ نگاشتِ
    CHECK_RECEIVED_CASH_COLLECT با تفصیلیِ صندوقِ نقدیِ مقصد / بستانکارِ
    محلِ فعلیِ هرچک."""
    with new_session() as session:
        checks = _load_checks_for_stage(session, check_ids, company_id, ("IN_HAND",))
        target_account_id = _get_mapped_account_id(session, company_id, "CHECK_RECEIVED_CASH_COLLECT")
        _validate_detail_account(session, cash_box_detail_id, company_id)
        groups = _group_received_checks_by_source(session, checks, company_id)
        total = sum((c.amount for c in checks), decimal.Decimal(0))
        description = "وصولِ نقدیِ چکِ دریافتیِ نزدِ صندوق"
        lines = [
            je_service.LineInput(
                account_id=target_account_id, description=description, debit=total, credit=decimal.Decimal(0),
                details=_detail_dict(session, cash_box_detail_id),
            )
        ]
        for (src_account_id, src_detail_id), group_checks in groups.items():
            group_total = sum((c.amount for c in group_checks), decimal.Decimal(0))
            lines.append(
                je_service.LineInput(
                    account_id=src_account_id, description=description, debit=decimal.Decimal(0), credit=group_total,
                    details=_detail_dict(session, src_detail_id),
                )
            )
        from_location_by_check_id = {
            c.received_check_id: (c.current_location_account_id, c.current_location_detail_account_id) for c in checks
        }
        check_ids_processed = [c.received_check_id for c in checks]

    # طبقِ باگ‌فیکسِ گزارش‌شده: سند اول ساخته می‌شود؛ فقط اگر موفق شد،
    # وضعیتِ چک تغییر می‌کند (نه برعکس).
    event_date = datetime.date.today()
    result = je_service.create_journal_entry(
        company_id, created_by_user_id, event_date, "وصولِ نقدیِ چکِ دریافتیِ نزدِ صندوق", lines,
        entry_type_code="RECEIPT",
    )
    with new_session() as session:
        checks = session.scalars(
            select(ReceivedCheck).where(ReceivedCheck.received_check_id.in_(check_ids_processed))
        ).all()
        for check in checks:
            check.status_id = _status_id(session, "CLEARED", "RECEIVED")
        for check_id in check_ids_processed:
            from_loc_account_id, from_loc_detail_id = from_location_by_check_id[check_id]
            _log_check_event(
                session, company_id, "RECEIVED", check_id, "CASH_COLLECT", event_date,
                "IN_HAND", "CLEARED", result.journal_entry_id, created_by_user_id,
                from_loc_account_id, from_loc_detail_id,
            )
        session.commit()
    return result


def deposit_received_checks_to_bank(
    check_ids: list[int], company_id: int, created_by_user_id: int, bank_detail_id: int
) -> je_service.JournalEntryResult:
    """مرحله‌ی ۳ — واگذاریِ چکِ نزدِ صندوق به بانک: بدهکارِ حسابِ نگاشتِ
    CHECK_RECEIVED_BANK_DEPOSIT با تفصیلیِ بانکِ مقصد / بستانکارِ محلِ
    فعلیِ هرچک."""
    with new_session() as session:
        checks = _load_checks_for_stage(session, check_ids, company_id, ("IN_HAND",))
        target_account_id = _get_mapped_account_id(session, company_id, "CHECK_RECEIVED_BANK_DEPOSIT")
        _validate_detail_account(session, bank_detail_id, company_id)
        groups = _group_received_checks_by_source(session, checks, company_id)
        total = sum((c.amount for c in checks), decimal.Decimal(0))
        description = "واگذاریِ چکِ دریافتیِ نزدِ صندوق به بانک"
        lines = [
            je_service.LineInput(
                account_id=target_account_id, description=description, debit=total, credit=decimal.Decimal(0),
                details=_detail_dict(session, bank_detail_id),
            )
        ]
        for (src_account_id, src_detail_id), group_checks in groups.items():
            group_total = sum((c.amount for c in group_checks), decimal.Decimal(0))
            lines.append(
                je_service.LineInput(
                    account_id=src_account_id, description=description, debit=decimal.Decimal(0), credit=group_total,
                    details=_detail_dict(session, src_detail_id),
                )
            )
        from_location_by_check_id = {
            c.received_check_id: (c.current_location_account_id, c.current_location_detail_account_id) for c in checks
        }
        check_ids_processed = [c.received_check_id for c in checks]

    # طبقِ باگ‌فیکسِ گزارش‌شده («پیام داد نمی‌شه واگذار کنی، ولی واگذار
    # کرد بدونِ ثبتِ سندِ حسابداری»): قبلاً وضعیتِ چک به «واگذارشده به
    # بانک» همین‌جا commit می‌شد و بعد سندِ حسابداری ساخته می‌شد — اگر
    # create_journal_entry رد می‌شد (مثلاً کمبودِ تفصیلیِ الزامیِ حسابِ
    # نگاشتِ CHECK_RECEIVED_BANK_DEPOSIT)، چک همچنان به‌عنوانِ واگذارشده
    # می‌ماند، بدونِ هیچ سندی. حالا سند اول ساخته می‌شود؛ فقط اگر موفق
    # شد، وضعیت/محلِ چک تغییر می‌کند.
    event_date = datetime.date.today()
    result = je_service.create_journal_entry(
        company_id, created_by_user_id, event_date, "واگذاریِ چکِ دریافتیِ نزدِ صندوق به بانک", lines,
        entry_type_code="RECEIPT",
    )
    with new_session() as session:
        checks = session.scalars(
            select(ReceivedCheck).where(ReceivedCheck.received_check_id.in_(check_ids_processed))
        ).all()
        for check in checks:
            check.status_id = _status_id(session, "DEPOSITED", "RECEIVED")
            check.current_location_account_id = target_account_id
            check.current_location_detail_account_id = bank_detail_id
        for check_id in check_ids_processed:
            from_loc_account_id, from_loc_detail_id = from_location_by_check_id[check_id]
            _log_check_event(
                session, company_id, "RECEIVED", check_id, "BANK_DEPOSIT", event_date,
                "IN_HAND", "DEPOSITED", result.journal_entry_id, created_by_user_id,
                from_loc_account_id, from_loc_detail_id,
            )
        session.commit()
    return result


def clear_deposited_received_checks(
    check_ids: list[int], company_id: int, created_by_user_id: int
) -> je_service.JournalEntryResult:
    """مرحله‌ی ۴ — اعلامِ وصولِ چکِ نزدِ بانک: بدهکارِ حسابِ نگاشتِ
    CHECK_RECEIVED_BANK_CLEAR / بستانکارِ محلِ فعلیِ هرچک (همان بانکی که
    در مرحله‌ی ۳ انتخاب شده بود) — بدونِ نیازِ انتخابِ مقصد، چون بانک از
    رویِ خودِ چک معلوم است."""
    with new_session() as session:
        checks = _load_checks_for_stage(session, check_ids, company_id, ("DEPOSITED",))
        target_account_id = _get_mapped_account_id(session, company_id, "CHECK_RECEIVED_BANK_CLEAR")
        groups = _group_received_checks_by_source(session, checks, company_id)
        description = "اعلامِ وصولِ چکِ دریافتیِ نزدِ بانک"
        lines: list[je_service.LineInput] = []
        for (src_account_id, src_detail_id), group_checks in groups.items():
            group_total = sum((c.amount for c in group_checks), decimal.Decimal(0))
            details = _detail_dict(session, src_detail_id)
            lines.append(
                je_service.LineInput(
                    account_id=target_account_id, description=description, debit=group_total, credit=decimal.Decimal(0),
                    details=details,
                )
            )
            lines.append(
                je_service.LineInput(
                    account_id=src_account_id, description=description, debit=decimal.Decimal(0), credit=group_total,
                    details=details,
                )
            )
        from_location_by_check_id = {
            c.received_check_id: (c.current_location_account_id, c.current_location_detail_account_id) for c in checks
        }
        check_ids_processed = [c.received_check_id for c in checks]

    # طبقِ باگ‌فیکسِ گزارش‌شده: سند اول ساخته می‌شود؛ فقط اگر موفق شد،
    # وضعیتِ چک تغییر می‌کند.
    event_date = datetime.date.today()
    result = je_service.create_journal_entry(
        company_id, created_by_user_id, event_date, "اعلامِ وصولِ چکِ دریافتیِ نزدِ بانک", lines,
        entry_type_code="RECEIPT",
    )
    with new_session() as session:
        checks = session.scalars(
            select(ReceivedCheck).where(ReceivedCheck.received_check_id.in_(check_ids_processed))
        ).all()
        for check in checks:
            check.status_id = _status_id(session, "CLEARED", "RECEIVED")
        for check_id in check_ids_processed:
            from_loc_account_id, from_loc_detail_id = from_location_by_check_id[check_id]
            _log_check_event(
                session, company_id, "RECEIVED", check_id, "BANK_CLEAR", event_date,
                "DEPOSITED", "CLEARED", result.journal_entry_id, created_by_user_id,
                from_loc_account_id, from_loc_detail_id,
            )
        session.commit()
    return result


def return_deposited_received_checks_to_fund(
    check_ids: list[int], company_id: int, created_by_user_id: int, target_fund_detail_id: int
) -> je_service.JournalEntryResult:
    """مرحله‌ی ۵ — برگشتِ چکِ نزدِ بانک به صندوق: بدهکارِ حسابِ نگاشتِ
    CHECK_RECEIVED_BANK_RETURN با تفصیلیِ صندوقِ مقصد / بستانکارِ محلِ
    فعلیِ هرچک (بانکِ مبدأ)."""
    with new_session() as session:
        checks = _load_checks_for_stage(session, check_ids, company_id, ("DEPOSITED",))
        target_account_id = _get_mapped_account_id(session, company_id, "CHECK_RECEIVED_BANK_RETURN")
        _validate_detail_account(session, target_fund_detail_id, company_id)
        groups = _group_received_checks_by_source(session, checks, company_id)
        total = sum((c.amount for c in checks), decimal.Decimal(0))
        description = "برگشتِ چکِ دریافتیِ نزدِ بانک به صندوق"
        lines = [
            je_service.LineInput(
                account_id=target_account_id, description=description, debit=total, credit=decimal.Decimal(0),
                details=_detail_dict(session, target_fund_detail_id),
            )
        ]
        for (src_account_id, src_detail_id), group_checks in groups.items():
            group_total = sum((c.amount for c in group_checks), decimal.Decimal(0))
            lines.append(
                je_service.LineInput(
                    account_id=src_account_id, description=description, debit=decimal.Decimal(0), credit=group_total,
                    details=_detail_dict(session, src_detail_id),
                )
            )
        from_location_by_check_id = {
            c.received_check_id: (c.current_location_account_id, c.current_location_detail_account_id) for c in checks
        }
        check_ids_processed = [c.received_check_id for c in checks]

    # طبقِ باگ‌فیکسِ گزارش‌شده: سند اول ساخته می‌شود؛ فقط اگر موفق شد،
    # وضعیت/محلِ چک تغییر می‌کند.
    event_date = datetime.date.today()
    result = je_service.create_journal_entry(
        company_id, created_by_user_id, event_date, "برگشتِ چکِ دریافتیِ نزدِ بانک به صندوق", lines,
        entry_type_code="RECEIPT",
    )
    with new_session() as session:
        checks = session.scalars(
            select(ReceivedCheck).where(ReceivedCheck.received_check_id.in_(check_ids_processed))
        ).all()
        for check in checks:
            check.status_id = _status_id(session, "IN_HAND", "RECEIVED")
            check.current_location_account_id = target_account_id
            check.current_location_detail_account_id = target_fund_detail_id
        for check_id in check_ids_processed:
            from_loc_account_id, from_loc_detail_id = from_location_by_check_id[check_id]
            _log_check_event(
                session, company_id, "RECEIVED", check_id, "BANK_RETURN", event_date,
                "DEPOSITED", "IN_HAND", result.journal_entry_id, created_by_user_id,
                from_loc_account_id, from_loc_detail_id,
            )
        session.commit()
    return result


def bounce_received_checks(
    check_ids: list[int], company_id: int, created_by_user_id: int
) -> je_service.JournalEntryResult:
    """مرحله‌ی ۶ — برگشتِ چکِ نزدِ صندوق به طرفِ‌حساب: بدهکارِ همان
    حساب/تفصیلیِ طرف‌حسابِ سندِ اصلیِ هرچک (دوباره بدهکار می‌شود) /
    بستانکارِ محلِ فعلیِ همان چک."""
    with new_session() as session:
        checks = _load_checks_for_stage(session, check_ids, company_id, ("IN_HAND",))
        description = "برگشتِ چکِ دریافتی به طرفِ‌حساب"
        lines: list[je_service.LineInput] = []
        for check in checks:
            counterparty_account_id, counterparty_details = _first_line_account_and_details(
                session, check.source_journal_entry_id
            )
            lines.append(
                je_service.LineInput(
                    account_id=counterparty_account_id,
                    description=f"{description} — چکِ شماره‌ی {check.check_no}",
                    debit=check.amount, credit=decimal.Decimal(0), details=dict(counterparty_details),
                )
            )
        groups = _group_received_checks_by_source(session, checks, company_id)
        for (src_account_id, src_detail_id), group_checks in groups.items():
            group_total = sum((c.amount for c in group_checks), decimal.Decimal(0))
            lines.append(
                je_service.LineInput(
                    account_id=src_account_id, description=description, debit=decimal.Decimal(0), credit=group_total,
                    details=_detail_dict(session, src_detail_id),
                )
            )
        from_location_by_check_id = {
            c.received_check_id: (c.current_location_account_id, c.current_location_detail_account_id) for c in checks
        }
        check_ids_processed = [c.received_check_id for c in checks]

    # طبقِ باگ‌فیکسِ گزارش‌شده: سند اول ساخته می‌شود؛ فقط اگر موفق شد،
    # وضعیتِ چک تغییر می‌کند.
    event_date = datetime.date.today()
    result = je_service.create_journal_entry(
        company_id, created_by_user_id, event_date, description, lines, entry_type_code="RECEIPT",
    )
    with new_session() as session:
        checks = session.scalars(
            select(ReceivedCheck).where(ReceivedCheck.received_check_id.in_(check_ids_processed))
        ).all()
        for check in checks:
            check.status_id = _status_id(session, "BOUNCED", "RECEIVED")
        for check_id in check_ids_processed:
            from_loc_account_id, from_loc_detail_id = from_location_by_check_id[check_id]
            _log_check_event(
                session, company_id, "RECEIVED", check_id, "BOUNCED", event_date,
                "IN_HAND", "BOUNCED", result.journal_entry_id, created_by_user_id,
                from_loc_account_id, from_loc_detail_id,
            )
        session.commit()
    return result


def unendorse_received_checks_to_fund(
    check_ids: list[int], company_id: int, target_fund_detail_id: int, created_by_user_id: int
) -> None:
    """مرحله‌ی ۷ — برگشتِ چکِ خرجی به صندوق: فقط تغییرِ وضعیت/محل، بدونِ
    سندِ حسابداری — چون این نسخه ردی از «کدام سندِ CHECK_DISBURSEMENT این
    چک را واقعاً خرج کرد» ندارد؛ اگر این چک واقعاً در یک سندِ پرداخت خرج
    شده، آن سند باید جداگانه در دفترِ روزنامه اصلاح شود (این تابع فقط
    برایِ چکی است که «خرج‌شده» علامت خورده ولی عملاً برنگشته)."""
    with new_session() as session:
        checks = _load_checks_for_stage(session, check_ids, company_id, ("ENDORSED",))
        _validate_detail_account(session, target_fund_detail_id, company_id)
        fund_account_id = _get_mapped_account_id(session, company_id, "RECEIPT_CHECK")
        event_date = datetime.date.today()
        for check in checks:
            from_loc_account_id = check.current_location_account_id
            from_loc_detail_id = check.current_location_detail_account_id
            check.status_id = _status_id(session, "IN_HAND", "RECEIVED")
            check.current_location_account_id = fund_account_id
            check.current_location_detail_account_id = target_fund_detail_id
            _log_check_event(
                session, company_id, "RECEIVED", check.received_check_id, "UNENDORSED_RETURN", event_date,
                "ENDORSED", "IN_HAND", None, created_by_user_id,
                from_loc_account_id, from_loc_detail_id,
            )
        session.commit()


def clear_issued_checks(
    check_ids: list[int], company_id: int, created_by_user_id: int
) -> je_service.JournalEntryResult:
    """وصولِ چکِ پرداختی از بانک: بدهکارِ حسابِ نگاشتِ CHECK_ISSUED_BANK_CLEAR
    / بستانکارِ همان حسابِ بانکی‌ای که موقعِ صدورِ هرچک مشخص شده بود."""
    with new_session() as session:
        if not check_ids:
            raise ValueError("هیچ چکی انتخاب نشده است.")
        checks = session.scalars(select(IssuedCheck).where(IssuedCheck.issued_check_id.in_(check_ids))).all()
        if len(checks) != len(set(check_ids)):
            raise ValueError("چکِ انتخاب‌شده نامعتبر است.")
        for check in checks:
            if check.company_id != company_id:
                raise ValueError("چک نامعتبر است.")
            if session.get(CheckStatus, check.status_id).code != "ISSUED":
                raise ValueError(f"چکِ شماره‌ی {check.check_no} در این مرحله قابلِ‌پردازش نیست.")
        debit_account_id = _get_mapped_account_id(session, company_id, "CHECK_ISSUED_BANK_CLEAR")
        bank_account_id = _get_mapped_account_id(session, company_id, "PAYMENT_BANK")
        description = "وصولِ چکِ پرداختی از بانک"
        total = sum((c.amount for c in checks), decimal.Decimal(0))
        lines = [
            je_service.LineInput(
                account_id=debit_account_id, description=description, debit=total, credit=decimal.Decimal(0),
            )
        ]
        by_bank_detail: dict[int, decimal.Decimal] = {}
        for check in checks:
            by_bank_detail[check.bank_account_detail_id] = (
                by_bank_detail.get(check.bank_account_detail_id, decimal.Decimal(0)) + check.amount
            )
        for bank_detail_id, group_total in by_bank_detail.items():
            lines.append(
                je_service.LineInput(
                    account_id=bank_account_id, description=description, debit=decimal.Decimal(0), credit=group_total,
                    details=_detail_dict(session, bank_detail_id),
                )
            )
        check_ids_processed = [c.issued_check_id for c in checks]

    # طبقِ باگ‌فیکسِ گزارش‌شده: سند اول ساخته می‌شود؛ فقط اگر موفق شد،
    # وضعیتِ چک تغییر می‌کند.
    event_date = datetime.date.today()
    result = je_service.create_journal_entry(
        company_id, created_by_user_id, event_date, "وصولِ چکِ پرداختی از بانک", lines,
        entry_type_code="PAYMENT",
    )
    with new_session() as session:
        checks = session.scalars(
            select(IssuedCheck).where(IssuedCheck.issued_check_id.in_(check_ids_processed))
        ).all()
        for check in checks:
            check.status_id = _status_id(session, "CLEARED", "ISSUED")
        for check_id in check_ids_processed:
            _log_check_event(
                session, company_id, "ISSUED", check_id, "ISSUED_CLEARED", event_date,
                "ISSUED", "CLEARED", result.journal_entry_id, created_by_user_id,
            )
        session.commit()
    return result


def return_issued_checks_to_fund(
    check_ids: list[int], company_id: int, created_by_user_id: int
) -> je_service.JournalEntryResult:
    """چکِ پرداختیِ وصول‌نشده جهتِ برگشت (ابطال): بدهکارِ حسابِ نگاشتِ
    CHECK_ISSUED_RETURN_TO_FUND / بستانکارِ همان حساب/تفصیلیِ طرف‌حسابِ
    سندِ اصلیِ هرچک (بدهیِ ما به او دوباره برمی‌گردد)."""
    with new_session() as session:
        if not check_ids:
            raise ValueError("هیچ چکی انتخاب نشده است.")
        checks = session.scalars(select(IssuedCheck).where(IssuedCheck.issued_check_id.in_(check_ids))).all()
        if len(checks) != len(set(check_ids)):
            raise ValueError("چکِ انتخاب‌شده نامعتبر است.")
        for check in checks:
            if check.company_id != company_id:
                raise ValueError("چک نامعتبر است.")
            if session.get(CheckStatus, check.status_id).code not in ("ISSUED", "BOUNCED"):
                raise ValueError(f"چکِ شماره‌ی {check.check_no} در این مرحله قابلِ‌پردازش نیست.")
        debit_account_id = _get_mapped_account_id(session, company_id, "CHECK_ISSUED_RETURN_TO_FUND")
        description = "برگشتِ چکِ پرداختیِ وصول‌نشده"
        total = sum((c.amount for c in checks), decimal.Decimal(0))
        lines = [
            je_service.LineInput(
                account_id=debit_account_id, description=description, debit=total, credit=decimal.Decimal(0),
            )
        ]
        for check in checks:
            counterparty_account_id, counterparty_details = _first_line_account_and_details(
                session, check.source_journal_entry_id
            )
            lines.append(
                je_service.LineInput(
                    account_id=counterparty_account_id,
                    description=f"{description} — چکِ شماره‌ی {check.check_no}",
                    debit=decimal.Decimal(0), credit=check.amount, details=dict(counterparty_details),
                )
            )
        status_codes = _status_code_map(session, "ISSUED")
        from_status_by_check_id = {c.issued_check_id: status_codes.get(c.status_id) for c in checks}
        check_ids_processed = [c.issued_check_id for c in checks]

    # طبقِ باگ‌فیکسِ گزارش‌شده: سند اول ساخته می‌شود؛ فقط اگر موفق شد،
    # وضعیتِ چک تغییر می‌کند.
    event_date = datetime.date.today()
    result = je_service.create_journal_entry(
        company_id, created_by_user_id, event_date, "برگشتِ چکِ پرداختیِ وصول‌نشده", lines,
        entry_type_code="PAYMENT",
    )
    with new_session() as session:
        checks = session.scalars(
            select(IssuedCheck).where(IssuedCheck.issued_check_id.in_(check_ids_processed))
        ).all()
        for check in checks:
            check.status_id = _status_id(session, "VOIDED", "ISSUED")
        for check_id in check_ids_processed:
            _log_check_event(
                session, company_id, "ISSUED", check_id, "ISSUED_RETURNED", event_date,
                from_status_by_check_id.get(check_id), "VOIDED", result.journal_entry_id, created_by_user_id,
            )
        session.commit()
    return result
