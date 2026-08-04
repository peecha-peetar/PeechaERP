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
    ChartOfAccount,
    DetailAccount,
    JournalEntryLine,
    JournalEntryLineDetail,
)
from peecha.db.models.treasury import (
    Bank,
    Checkbook,
    CheckStatus,
    CounterpartyAccountMapping,
    DescriptionTemplate,
    IssuedCheck,
    ReceivedCheck,
    TreasuryAccountMapping,
)
from peecha.services import audit as audit_service
from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import journal_entries as je_service

MAPPING_KEYS = [
    "RECEIPT_CASH",
    "RECEIPT_BANK",
    "RECEIPT_CHECK",
    "RECEIPT_DISCOUNT",
    "RECEIPT_NETTING",
    "RECEIPT_GOODS_COUPON",
    "RECEIPT_VOUCHER",
    "PAYMENT_CASH",
    "PAYMENT_BANK",
    "PAYMENT_CHECK",
    "PAYMENT_DISCOUNT",
    "PAYMENT_CHECK_DISBURSEMENT",
    "PAYMENT_NETTING",
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
    "PAYMENT_CASH": "پرداختِ نقدی",
    "PAYMENT_BANK": "پرداختِ بانکی",
    "PAYMENT_CHECK": "چک‌هایِ پرداختنی",
    "PAYMENT_DISCOUNT": "تخفیفاتِ نقدیِ دریافت‌شده",
    "PAYMENT_CHECK_DISBURSEMENT": "پرداخت با چکِ دریافتی (خرجِ چک)",
    "PAYMENT_NETTING": "تهاترِ پرداخت",
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
}

METHOD_CODES = ("CASH", "BANK", "CHECK", "DISCOUNT", "NETTING", "CHECK_DISBURSEMENT", "GOODS_COUPON", "VOUCHER")

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


def delete_bank(bank_id: int, company_id: int) -> None:
    with new_session() as session:
        bank = session.get(Bank, bank_id)
        if bank is None or bank.company_id != company_id:
            raise ValueError("بانک نامعتبر است.")
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
    with new_session() as session:
        rows = {
            m.mapping_key: (m.account_id, m.detail_account_id)
            for m in session.scalars(
                select(TreasuryAccountMapping).where(TreasuryAccountMapping.company_id == company_id)
            ).all()
        }
    accounts_by_id = {a.account_id: f"{a.full_code} — {a.name}" for a in coa_service.list_accounts(company_id)}
    details_by_id = {
        d.detail_account_id: d.name or d.full_code or d.code for d in dimensions_service.list_all_leaf_detail_accounts(company_id)
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


def set_account_mapping(company_id: int, mapping_key: str, account_id: int, detail_account_id: int | None = None) -> None:
    if mapping_key not in MAPPING_LABELS:
        raise ValueError("کلیدِ نگاشتِ نامعتبر است.")
    with new_session() as session:
        existing = session.get(TreasuryAccountMapping, (company_id, mapping_key))
        if existing is None:
            session.add(
                TreasuryAccountMapping(
                    company_id=company_id, mapping_key=mapping_key, account_id=account_id, detail_account_id=detail_account_id
                )
            )
        else:
            existing.account_id = account_id
            existing.detail_account_id = detail_account_id
        session.commit()


def _get_mapped_account_id(session, company_id: int, mapping_key: str) -> int:
    mapping = session.get(TreasuryAccountMapping, (company_id, mapping_key))
    if mapping is None:
        raise ValueError(
            f"حسابِ «{MAPPING_LABELS[mapping_key]}» هنوز در تنظیماتِ خزانه‌داری مشخص نشده است."
        )
    return mapping.account_id


def get_account_mapping(company_id: int, mapping_key: str) -> int | None:
    """نگاشتِ یک روش را برمی‌گرداند (یا None اگر هنوز تنظیم نشده) — برایِ
    UI که می‌خواهد بُعدِ الزامیِ همان معین را از رویِ آن استنتاج کند
    (مثلاً کدام تفصیلی برایِ ردیفِ نقدی/تخفیف/کالابرگ نشان داده شود)،
    بدونِ ریسکِ raise شدنِ خطا در میانه‌یِ رفرشِ فرم."""
    with new_session() as session:
        mapping = session.get(TreasuryAccountMapping, (company_id, mapping_key))
        return mapping.account_id if mapping is not None else None


def get_account_mapping_with_detail(company_id: int, mapping_key: str) -> tuple[int | None, int | None]:
    """مثلِ get_account_mapping، به‌همراهِ تفصیلیِ اختصاصیِ از‌پیش‌تخصیص‌یافته
    (اگر در تنظیمات مشخص شده باشد) — برایِ فرمِ سند تا اگر تفصیلی از پیش
    معلوم است، دیگر از کاربر دوباره نپرسد."""
    with new_session() as session:
        mapping = session.get(TreasuryAccountMapping, (company_id, mapping_key))
        if mapping is None:
            return None, None
        return mapping.account_id, mapping.detail_account_id


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
        status = session.scalar(
            select(CheckStatus).where(CheckStatus.code == "ENDORSED", CheckStatus.applies_to == "RECEIVED")
        )
        for ml in method_lines:
            if ml.method != "CHECK_DISBURSEMENT":
                continue
            check_ids = ml.received_check_ids or ([ml.received_check_id] if ml.received_check_id is not None else [])
            for received_check_id in check_ids:
                check = session.get(ReceivedCheck, received_check_id)
                check.status_id = status.status_id
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
                    session.add(
                        ReceivedCheck(
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
                        )
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
                    session.add(
                        IssuedCheck(
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
        for check in checks:
            check.current_location_account_id = account_id
            check.current_location_detail_account_id = target_fund_detail_id
        session.commit()

    return je_service.create_journal_entry(
        company_id, created_by_user_id, datetime.date.today(), "انتقالِ چکِ دریافتی بینِ صندوق‌ها", lines,
        entry_type_code="RECEIPT",
    )


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
        for check in checks:
            check.status_id = _status_id(session, "CLEARED", "RECEIVED")
        session.commit()

    return je_service.create_journal_entry(
        company_id, created_by_user_id, datetime.date.today(), "وصولِ نقدیِ چکِ دریافتیِ نزدِ صندوق", lines,
        entry_type_code="RECEIPT",
    )


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
        for check in checks:
            check.status_id = _status_id(session, "DEPOSITED", "RECEIVED")
            check.current_location_account_id = target_account_id
            check.current_location_detail_account_id = bank_detail_id
        session.commit()

    return je_service.create_journal_entry(
        company_id, created_by_user_id, datetime.date.today(), "واگذاریِ چکِ دریافتیِ نزدِ صندوق به بانک", lines,
        entry_type_code="RECEIPT",
    )


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
        for check in checks:
            check.status_id = _status_id(session, "CLEARED", "RECEIVED")
        session.commit()

    return je_service.create_journal_entry(
        company_id, created_by_user_id, datetime.date.today(), "اعلامِ وصولِ چکِ دریافتیِ نزدِ بانک", lines,
        entry_type_code="RECEIPT",
    )


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
        for check in checks:
            check.status_id = _status_id(session, "IN_HAND", "RECEIVED")
            check.current_location_account_id = target_account_id
            check.current_location_detail_account_id = target_fund_detail_id
        session.commit()

    return je_service.create_journal_entry(
        company_id, created_by_user_id, datetime.date.today(), "برگشتِ چکِ دریافتیِ نزدِ بانک به صندوق", lines,
        entry_type_code="RECEIPT",
    )


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
        for check in checks:
            check.status_id = _status_id(session, "BOUNCED", "RECEIVED")
        session.commit()

    return je_service.create_journal_entry(
        company_id, created_by_user_id, datetime.date.today(), description, lines, entry_type_code="RECEIPT",
    )


def unendorse_received_checks_to_fund(
    check_ids: list[int], company_id: int, target_fund_detail_id: int
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
        for check in checks:
            check.status_id = _status_id(session, "IN_HAND", "RECEIVED")
            check.current_location_account_id = fund_account_id
            check.current_location_detail_account_id = target_fund_detail_id
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
        for check in checks:
            check.status_id = _status_id(session, "CLEARED", "ISSUED")
        session.commit()

    return je_service.create_journal_entry(
        company_id, created_by_user_id, datetime.date.today(), "وصولِ چکِ پرداختی از بانک", lines,
        entry_type_code="PAYMENT",
    )


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
        for check in checks:
            check.status_id = _status_id(session, "VOIDED", "ISSUED")
        session.commit()

    return je_service.create_journal_entry(
        company_id, created_by_user_id, datetime.date.today(), "برگشتِ چکِ پرداختیِ وصول‌نشده", lines,
        entry_type_code="PAYMENT",
    )
