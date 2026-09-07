"""فروشگاه و صندوق (مرحلهٔ ۷): جلسهٔ صندوق، پرداختِ چندروشی، وفاداری،
کارتِ‌هدیه، فروشِ اقساطی. تراکنشِ POS خودش یک comm.commercial_documents
با channel_code='POS' است — این فایل فقط قابلیت‌هایِ واقعاً تازه را
اضافه می‌کند."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha import numerals
from peecha.db.base import new_session
from peecha.db.models.commercial import (
    CommercialDocumentLine,
    CommercialDocument,
    GiftCard,
    InstallmentLine,
    InstallmentPlan,
    LoyaltyAccount,
    LoyaltyTransaction,
    PosCashierSettings,
    PosInvoiceAuditLog,
    PosMenuGroup,
    PosPayment,
    PosSession,
    PosSettings,
    PosTerminal,
)
from peecha.db.models.inventory import Item
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import treasury as treasury_service

_ZERO = decimal.Decimal("0")
_Q2 = decimal.Decimal("0.01")


def _money(value: decimal.Decimal) -> decimal.Decimal:
    return value.quantize(_Q2, rounding=decimal.ROUND_HALF_UP)


# ---------------------------------------------------------------------
# ترمینال و جلسه
# ---------------------------------------------------------------------
def list_terminals(company_id: int) -> list[PosTerminal]:
    with new_session() as session:
        return list(session.scalars(select(PosTerminal).where(PosTerminal.company_id == company_id)))


def create_terminal(company_id: int, warehouse_id: int, code: str, name: str) -> int:
    with new_session() as session:
        row = PosTerminal(company_id=company_id, warehouse_id=warehouse_id, code=code, name=name)
        session.add(row)
        session.commit()
        return row.terminal_id


def get_open_session(terminal_id: int) -> PosSession | None:
    with new_session() as session:
        return session.scalar(select(PosSession).where(PosSession.terminal_id == terminal_id, PosSession.status_code == "OPEN"))


def get_session(session_id: int) -> PosSession | None:
    with new_session() as session:
        return session.get(PosSession, session_id)


def list_sessions(terminal_id: int) -> list[PosSession]:
    with new_session() as session:
        return list(session.scalars(select(PosSession).where(PosSession.terminal_id == terminal_id).order_by(PosSession.session_id.desc())))


def open_session(terminal_id: int, opened_by_user_id: int, opening_cash_amount: decimal.Decimal) -> int:
    with new_session() as session:
        terminal = session.get(PosTerminal, terminal_id)
        if terminal is None:
            raise ValueError("ترمینال نامعتبر است.")
        settings = session.get(PosSettings, terminal.company_id)
        threshold = settings.cash_variance_threshold_amount if settings is not None else _ZERO
        last_session = session.scalar(
            select(PosSession)
            .where(PosSession.terminal_id == terminal_id, PosSession.status_code == "CLOSED")
            .order_by(PosSession.session_id.desc())
        )
        if (
            last_session is not None and last_session.variance_amount is not None
            and abs(last_session.variance_amount) > threshold and last_session.variance_override_by_user_id is None
        ):
            raise ValueError("مغایرتِ جلسهٔ قبلیِ این ترمینال هنوز آزادسازی نشده — ابتدا مدیر باید تاییدِ استثنا کند.")
        open_row = session.scalar(select(PosSession).where(PosSession.terminal_id == terminal_id, PosSession.status_code == "OPEN"))
        if open_row is not None:
            raise ValueError("این ترمینال هم‌اکنون یک جلسهٔ باز دارد.")
        row = PosSession(terminal_id=terminal_id, opened_by_user_id=opened_by_user_id, opening_cash_amount=opening_cash_amount)
        session.add(row)
        session.commit()
        return row.session_id


def close_session(session_id: int, closed_by_user_id: int, closing_cash_amount: decimal.Decimal) -> decimal.Decimal:
    with new_session() as session:
        pos_session = session.get(PosSession, session_id)
        if pos_session is None or pos_session.status_code != "OPEN":
            raise ValueError("فقط جلسهٔ باز قابلِ‌بستن است.")
        open_drafts = session.scalar(
            select(CommercialDocument).where(
                CommercialDocument.pos_session_id == session_id, CommercialDocument.status_code.in_(("DRAFT", "CONFIRMED", "APPROVED"))
            )
        )
        if open_drafts is not None:
            raise ValueError("این جلسه سندِ ثبت‌نهایی‌نشده دارد — ابتدا Post یا لغو کنید.")
        total_cash = session.execute(
            select(PosPayment.amount)
            .join(CommercialDocument, CommercialDocument.document_id == PosPayment.document_id)
            .where(CommercialDocument.pos_session_id == session_id, PosPayment.method_code == "CASH")
        ).scalars().all()
        expected = pos_session.opening_cash_amount + sum(total_cash, _ZERO)
        pos_session.closing_cash_amount = closing_cash_amount
        pos_session.expected_cash_amount = expected
        pos_session.status_code = "CLOSED"
        pos_session.closed_by_user_id = closed_by_user_id
        pos_session.closed_at = datetime.datetime.now(datetime.timezone.utc)
        session.commit()
        return pos_session.variance_amount


@dataclass
class PosSessionSalesSummary:
    """طبقِ درخواستِ صریح («جمعِ فروشِ صندوق و تخفیف و تعدادِ فاکتور و
    مالیات در زیرِ صندوق نمایش داده شود»): رویِ همه‌یِ فروش‌هایِ همین
    شیفت (هر وضعیتی جز CANCELLED)، نه فقط فاکتورهایِ ثبتِ‌نهایی‌شده --
    چون هدف نمایشِ زنده‌یِ کارِ همین شیفت است، نه گزارشِ مالیِ رسمی."""

    invoice_count: int
    total_amount: decimal.Decimal
    discount_amount: decimal.Decimal
    tax_amount: decimal.Decimal


def get_session_sales_summary(session_id: int) -> PosSessionSalesSummary:
    with new_session() as session:
        rows = session.scalars(
            select(CommercialDocument).where(
                CommercialDocument.pos_session_id == session_id, CommercialDocument.status_code != "CANCELLED",
            )
        ).all()
        return PosSessionSalesSummary(
            invoice_count=len(rows),
            total_amount=sum((d.total_amount for d in rows), _ZERO),
            discount_amount=sum((d.discount_amount for d in rows), _ZERO),
            tax_amount=sum((d.tax_amount for d in rows), _ZERO),
        )


def override_session_variance(session_id: int, overridden_by_user_id: int, reason: str) -> None:
    with new_session() as session:
        pos_session = session.get(PosSession, session_id)
        if pos_session is None or pos_session.status_code != "CLOSED":
            raise ValueError("فقط جلسهٔ بستهٔ دارایِ مغایرت قابلِ‌آزادسازی است.")
        pos_session.variance_override_by_user_id = overridden_by_user_id
        pos_session.variance_override_reason = reason
        session.commit()


# ---------------------------------------------------------------------
# چرخهٔ تاییدِ فروشِ حضوری -- طبقِ تصمیمِ صریح («کاریر فقط تایید می‌کند،
# ثبتِ واقعیِ پرداخت/سندِ حسابداری با تاییدِ سرپرست انجام می‌شود»):
# کاریر فقط نوعِ پرداختِ موردنظرش را یادداشت می‌کند؛ خودِ POST/JE اینجا
# اتفاق نمی‌افتد.
# ---------------------------------------------------------------------
def set_intended_payment_type(document_id: int, company_id: int, payment_type: str) -> None:
    # طبقِ درخواستِ صریح («صندوق‌دار فقط نقد می‌تونه بزنه...»): «ترکیبی»
    # طبقِ همان الگو -- برایِ فروشی که صندوق‌دار از دیالوگِ «نحوهٔ
    # تسویه» (نه دو دکمهٔ نقدی/نسیه) استفاده کرده.
    if payment_type not in ("CASH", "CREDIT", "MIXED"):
        raise ValueError("نوعِ پرداخت نامعتبر است.")
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        doc.pos_intended_payment_type = payment_type
        session.commit()


def list_pending_pos_documents(company_id: int, pos_session_id: int) -> list[CommercialDocument]:
    """فاکتورهایِ این شیفت که کاریر تایید کرده ولی هنوز سرپرست
    approve/post نکرده -- برایِ صفحه‌یِ تاییدِ سرپرست و برایِ لیستِ
    «فروش‌هایِ درجریان/رزروشده» در خودِ صفحه‌یِ فروش."""
    with new_session() as session:
        return list(
            session.scalars(
                select(CommercialDocument)
                .where(
                    CommercialDocument.company_id == company_id,
                    CommercialDocument.document_type_code == "SALES_INVOICE",
                    CommercialDocument.pos_session_id == pos_session_id,
                    CommercialDocument.status_code.in_(("DRAFT", "CONFIRMED")),
                )
                .order_by(CommercialDocument.document_id.desc())
            )
        )


# ---------------------------------------------------------------------
# اصلاح/حذفِ فروشِ تاییدشده توسطِ صندوق‌دار (پیش از تاییدِ سرپرست) --
# طبقِ درخواستِ صریح («فاکتورهایِ صادرشده تا قبل از ثبتِ سند توسطِ
# صندوق‌دار هم بتونه حذف و اصلاح کنه و در هنگامِ بستنِ شیفت، فاکتورهایِ
# اصلاح‌شده و حذف‌شده به سرپرست گزارش بشه»).
# ---------------------------------------------------------------------
def _get_reopenable_pos_document(session, document_id: int, company_id: int) -> CommercialDocument:
    doc = session.get(CommercialDocument, document_id)
    if doc is None or doc.company_id != company_id:
        raise ValueError("سند نامعتبر است.")
    if doc.pos_session_id is None or doc.document_type_code != "SALES_INVOICE":
        raise ValueError("این عملیات فقط برایِ فروشِ صندوق ممکن است.")
    if doc.status_code != "CONFIRMED":
        raise ValueError("فقط فروشِ تاییدشده (پیش از تاییدِ سرپرست) قابلِ‌اصلاح/حذف است.")
    return doc


def reopen_confirmed_sale(document_id: int, company_id: int, user_id: int) -> None:
    """صندوق‌دار یک فروشِ تاییدشده را برایِ اصلاح (افزودن/حذف/تغییرِ
    ردیف) دوباره به پیش‌نویس برمی‌گرداند -- بعدِ اصلاح، دوباره از همان
    دکمه‌هایِ تاییدِ فروش عبور می‌کند. طبقِ درخواستِ صریح («روشِ
    پرداخت‌هایِ مربوط به همان فاکتور نیز به‌همراهِ فاکتور ویرایش یا حذف
    بشه»): نقشه‌یِ تسویه‌یِ قبلی (اگر باشد) هم حذف می‌شود -- چون بعدِ
    اصلاحِ سبد، مبلغِ کلِ فاکتور احتمالاً عوض شده و نقشه‌یِ قدیمی دیگر
    معتبر نیست؛ صندوق‌دار بعدِ تاییدِ دوباره، نحوه‌یِ تسویه را از نو
    مشخص می‌کند."""
    with new_session() as session:
        doc = _get_reopenable_pos_document(session, document_id, company_id)
        pos_session_id = doc.pos_session_id
        doc.status_code = "DRAFT"
        session.add(
            PosInvoiceAuditLog(
                company_id=company_id, pos_session_id=pos_session_id, document_id=document_id,
                action_code="REOPENED", performed_by_user_id=user_id,
            )
        )
        session.commit()
    settlements_service.delete_settlement_plan(document_id, company_id)


def delete_confirmed_sale(document_id: int, company_id: int, user_id: int) -> None:
    """صندوق‌دار یک فروشِ تاییدشده (پیش از تاییدِ سرپرست) را لغو می‌کند --
    طبقِ الگویِ عمومیِ برنامه، لغو (نه حذفِ خام) تا تاریخچه از بین
    نرود؛ در گزارشِ بستنِ شیفت به‌عنوانِ «حذف‌شده» نشان داده می‌شود. طبقِ
    همان درخواستِ صریح، نقشه‌یِ تسویه‌یِ این فاکتور هم همراهِ آن حذف
    می‌شود."""
    with new_session() as session:
        doc = _get_reopenable_pos_document(session, document_id, company_id)
        pos_session_id = doc.pos_session_id
        session.add(
            PosInvoiceAuditLog(
                company_id=company_id, pos_session_id=pos_session_id, document_id=document_id,
                action_code="DELETED", performed_by_user_id=user_id,
            )
        )
        session.commit()
    settlements_service.delete_settlement_plan(document_id, company_id)
    documents_service.cancel_document(document_id, company_id)


@dataclass
class PosInvoiceAuditEntry:
    document_id: int
    action_code: str
    performed_by_user_id: int
    performed_at: datetime.datetime


def list_session_audit_log(pos_session_id: int) -> list[PosInvoiceAuditEntry]:
    """فهرستِ فاکتورهایِ اصلاح‌شده/حذف‌شده‌یِ این شیفت -- برایِ گزارش به
    سرپرست هنگامِ بستنِ شیفت."""
    with new_session() as session:
        rows = session.scalars(
            select(PosInvoiceAuditLog)
            .where(PosInvoiceAuditLog.pos_session_id == pos_session_id)
            .order_by(PosInvoiceAuditLog.audit_id)
        ).all()
        return [
            PosInvoiceAuditEntry(
                document_id=r.document_id, action_code=r.action_code,
                performed_by_user_id=r.performed_by_user_id, performed_at=r.performed_at,
            )
            for r in rows
        ]


# ---------------------------------------------------------------------
# پرداختِ چندروشی
# ---------------------------------------------------------------------
def record_payment(document_id: int, method_code: str, amount: decimal.Decimal, reference_no: str | None = None) -> int:
    if method_code not in ("CASH", "CARD", "WALLET", "GIFT_CARD", "STORE_CREDIT"):
        raise ValueError("روشِ پرداخت نامعتبر است.")
    if amount <= 0:
        raise ValueError("مبلغ باید بزرگ‌تر از صفر باشد.")
    with new_session() as session:
        row = PosPayment(document_id=document_id, method_code=method_code, amount=amount, reference_no=reference_no)
        session.add(row)
        session.commit()
        return row.payment_id


def payments_cover_total(document_id: int) -> bool:
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None:
            raise ValueError("سند نامعتبر است.")
        paid = session.execute(select(PosPayment.amount).where(PosPayment.document_id == document_id)).scalars().all()
        plan_amounts = session.execute(
            select(InstallmentLine.amount)
            .join(InstallmentPlan, InstallmentPlan.plan_id == InstallmentLine.plan_id)
            .where(InstallmentPlan.document_id == document_id)
        ).scalars().all()
        return _money(sum(paid, _ZERO) + sum(plan_amounts, _ZERO)) == _money(doc.total_amount)


def _resolve_receivable_counterparty_details(
    company_id: int, person_dimension_type_id: int, customer_id: int, cost_center_type_id: int, project_type_id: int,
) -> dict[int, int]:
    """طبقِ رفعِ باگِ واقعیِ گزارش‌شده («در فرمِ تاییدِ سرپرست، برایِ حسابِ
    مشتری مرکزِ هزینه/پروژه می‌خواهد»): اگر حسابِ نگاشت‌شدهٔ دریافتِ
    مشتری این ابعاد را الزامی کرده باشد، پیش‌فرضِ تنظیم‌شده در
    PosSettings.default_receivable_cost_center/project به طرفِ حسابِ
    (بستانکارِ) سندِ RECEIPT هم اضافه می‌شود."""
    details = {person_dimension_type_id: customer_id}
    pos_settings = get_pos_settings(company_id)
    if pos_settings is not None:
        if pos_settings.default_receivable_cost_center_detail_account_id is not None:
            details[cost_center_type_id] = pos_settings.default_receivable_cost_center_detail_account_id
        if pos_settings.default_receivable_project_detail_account_id is not None:
            details[project_type_id] = pos_settings.default_receivable_project_detail_account_id
    return details


def record_payment_and_settle_batch(
    company_id: int, user_id: int, document_ids: list[int], method_code: str,
    amounts: dict[int, decimal.Decimal] | None = None, reference_no: str | None = None,
) -> list[int]:
    """طبقِ رفعِ شکافِ کشف‌شده: record_payment (بالا) از اول فقط یک
    ردیفِ comm.pos_payments ثبت می‌کرد -- بدونِ هیچ اثری در حساب‌هایِ
    نقد/بانک یا در comm.invoice_settlements؛ یعنی مشتری برایِ همیشه در
    گزارش‌هایِ تسویه «بدهکار» می‌ماند و نقدِ واقعاً دریافت‌شده هیچ‌وقت به
    صندوق/بانک نمی‌رسید. این تابع هر پرداختِ POS را به نتیجهٔ حسابداریِ
    واقعی‌اش وصل می‌کند:
    - نقد/کارت‌خوان: یک سندِ خزانه‌داریِ واقعی (create_treasury_voucher،
      دقیقاً هم‌الگو با فرمِ دریافتِ معمولی) ساخته و به فاکتور(ها) تسویه
      می‌شود.
    - کیف‌پول/کارتِ‌هدیه/اعتبارِ فروشگاهی: نیازی به سندِ خزانه‌داریِ تازه
      نیست (این‌ها از پیش داخلِ سیستم‌اند)، فقط تسویه (بدونِ ژورنالِ
      جدید) ثبت می‌شود.

    طبقِ تصمیمِ صریح («ادغام فقط رویِ سندِ حسابداری باشد، نه خودِ
    فاکتور -- تعداد فاکتورها ممکنه زیاد بشه»): وقتی چند document_id
    (همه‌ متعلق به یک طرفِ‌حساب) با هم پاس داده شوند و روشِ پرداخت
    نقد/کارت‌خوان باشد، به‌جایِ N سندِ حسابداریِ جدا، فقط یک سندِ واحد
    برایِ مجموع ساخته می‌شود -- خودِ فاکتورها دست‌نخورده و جدا می‌مانند،
    هرکدام فقط یک ردیفِ تسویه به همان یک سندِ حسابداری می‌گیرند (پس
    ریزِ فاکتورهایِ یک سند از طریقِ list_settlements_for_invoice/
    فیلترِ journal_entry_id هنوز قابلِ‌مشاهده است)."""
    with new_session() as session:
        docs = []
        for document_id in document_ids:
            doc = session.get(CommercialDocument, document_id)
            if doc is None or doc.company_id != company_id:
                raise ValueError("سند نامعتبر است.")
            docs.append(doc)
        if len({d.counterparty_detail_account_id for d in docs}) > 1:
            raise ValueError("ادغامِ سندِ حسابداری فقط برایِ فاکتورهایِ یک طرفِ‌حساب مجاز است.")
        customer_id = docs[0].counterparty_detail_account_id
        document_date = docs[0].document_date
        document_numbers = [d.document_no for d in docs]

    amounts = amounts or {d.document_id: d.total_amount for d in docs}

    payment_ids = []
    for doc in docs:
        amount = amounts[doc.document_id]
        if method_code == "GIFT_CARD":
            if not reference_no:
                raise ValueError("کدِ کارتِ‌هدیه را وارد کنید.")
            redeem_gift_card(reference_no, amount)
        elif method_code == "WALLET":
            redeem_wallet(customer_id, amount, document_id=doc.document_id)
        payment_ids.append(record_payment(doc.document_id, method_code, amount, reference_no=reference_no))

    journal_entry_id = None
    if method_code in ("CASH", "CARD"):
        person_dimension_type_id = dimensions_service.get_person_dimension_type_id(company_id)
        customer_group_id = next(
            (g.person_group_id for g in dimensions_service.list_person_groups(company_id) if g.code == "CUSTOMER"),
            None,
        )
        mapping_account_id = next(
            (
                m.account_id for m in treasury_service.list_counterparty_mappings(company_id, "RECEIPT")
                if m.person_group_id == customer_group_id
            ),
            None,
        )
        if mapping_account_id is None:
            raise ValueError("نگاشتِ حسابِ دریافت برایِ گروهِ «مشتری» در تنظیماتِ خزانه‌داری مشخص نشده است.")
        treasury_method = "CASH" if method_code == "CASH" else "BANK"
        total_amount = sum(amounts[d.document_id] for d in docs)
        description = (
            f"دریافتِ صندوق (POS) -- بابتِ فاکتورِ فروشِ #{document_numbers[0]}" if len(docs) == 1
            else f"دریافتِ صندوق (POS) -- بابتِ {numerals.to_persian_digits(str(len(docs)))} فاکتورِ فروش"
        )
        # طبقِ رفعِ باگِ واقعیِ گزارش‌شده («بعد از تاییدِ سرپرست می‌گوید
        # حساب مرکزِ هزینه و پروژه ندارد»): برخلافِ record_mixed_payment_
        # and_settle، این مسیرِ تک‌روشی (دکمه‌هایِ سادهٔ نقدی/نسیهٔ صندوق‌دار)
        # هیچ‌وقت پیش‌فرضِ تفصیلی/مرکزِهزینه/پروژهٔ همان روش (تنظیماتِ
        # «پیش‌فرضِ تسویه») را نمی‌خواند -- اگر حسابِ نگاشت‌شده نیازِ
        # این ابعاد را داشته باشد، create_treasury_voucher بدونِ آن‌ها
        # خطا می‌داد.
        cost_center_type_id = dimensions_service.get_specialized_dimension_type_id(
            company_id, dimensions_service.COST_CENTER_CODE
        )
        project_type_id = dimensions_service.get_specialized_dimension_type_id(
            company_id, dimensions_service.PROJECT_CODE
        )
        default = settlements_service.get_pos_settlement_method_default(company_id, treasury_method)
        detail_account_id = None
        extra_details: dict[int, int] = {}
        if default is not None:
            detail_account_id = default.detail_account_id
            if default.cost_center_detail_account_id is not None:
                extra_details[cost_center_type_id] = default.cost_center_detail_account_id
            if default.project_detail_account_id is not None:
                extra_details[project_type_id] = default.project_detail_account_id
        counterparty_details = _resolve_receivable_counterparty_details(
            company_id, person_dimension_type_id, customer_id, cost_center_type_id, project_type_id,
        )
        voucher_result = treasury_service.create_treasury_voucher(
            company_id, user_id, "RECEIPT", mapping_account_id,
            counterparty_details, document_date, description,
            [
                treasury_service.MethodLine(
                    method=treasury_method, amount=total_amount, detail_account_id=detail_account_id,
                    extra_details=(extra_details or None),
                )
            ],
        )
        journal_entry_id = voucher_result.journal_entry_id

    description = "تسویه‌یِ خودکارِ فروشِ حضوری (POS)" if len(docs) == 1 else "تسویه‌یِ ادغام‌شده‌یِ فروشِ حضوری (POS)"
    for doc in docs:
        settlements_service.allocate_settlement(
            company_id, doc.document_id, journal_entry_id, datetime.date.today(), amounts[doc.document_id], user_id,
            reference_no=reference_no, description=description,
        )
    return payment_ids


def record_payment_and_settle(
    company_id: int, user_id: int, document_id: int, method_code: str,
    amount: decimal.Decimal, reference_no: str | None = None,
) -> int:
    return record_payment_and_settle_batch(
        company_id, user_id, [document_id], method_code, {document_id: amount}, reference_no,
    )[0]


def record_mixed_payment_and_settle(
    company_id: int, user_id: int, document_id: int,
    method_lines: list[tuple], reference_no: str | None = None,
) -> int | None:
    """طبقِ درخواستِ صریح («صندوق‌دار فقط نقد می‌تونه بزنه، بانکی/سایرِ
    روش‌ها را نمی‌تونه ثبت کنه»): نسخهٔ چندروشیِ record_payment_and_settle
    -- برایِ فروشی که صندوق‌دار از دیالوگِ «نحوهٔ تسویه» (کدهایِ روشِ
    هم‌الگو با treasury.METHOD_CODES: CASH/BANK/DISCOUNT/GOODS_COUPON/
    VOUCHER، نه واژگانِ CARD/WALLET/GIFT_CARDِ منویِ تکی‌روشِ سرپرست)
    استفاده کرده. برخلافِ نسخهٔ تک‌روشی، همه‌یِ ردیف‌ها در یک سندِ
    حسابداریِ واحد (create_treasury_voucher با چند MethodLine) ثبت
    می‌شوند -- دقیقاً هم‌الگو با فرمِ فاکتورِ عمومی.

    هر ردیفِ method_lines می‌تواند ۲ تا ۴ عضو داشته باشد: (method_code,
    amount[, note[, detail_account_id]]) -- طبقِ درخواستِ صریح (تفصیلیِ
    انتخاب‌شده/پیش‌فرضِ همان روش هم به سندِ حسابداری منتقل شود). اگر
    تفصیلی صریحاً داده نشده باشد، پیش‌فرضِ همان روش (از تنظیماتِ
    pos_settlement_method_defaults) استفاده می‌شود؛ مرکزِ هزینه/پروژهٔ
    پیش‌فرضِ همان تنظیمات هم -- اگر معینِ نگاشته‌شده نیازشان داشته باشد --
    مستقیم به همان ردیف اضافه می‌شود."""
    if not method_lines:
        return None
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        customer_id = doc.counterparty_detail_account_id
        document_date = doc.document_date
        document_no = doc.document_no

    person_dimension_type_id = dimensions_service.get_person_dimension_type_id(company_id)
    customer_group_id = next(
        (g.person_group_id for g in dimensions_service.list_person_groups(company_id) if g.code == "CUSTOMER"),
        None,
    )
    mapping_account_id = next(
        (
            m.account_id for m in treasury_service.list_counterparty_mappings(company_id, "RECEIPT")
            if m.person_group_id == customer_group_id
        ),
        None,
    )
    if mapping_account_id is None:
        raise ValueError("نگاشتِ حسابِ دریافت برایِ گروهِ «مشتری» در تنظیماتِ خزانه‌داری مشخص نشده است.")

    cost_center_type_id = dimensions_service.get_specialized_dimension_type_id(
        company_id, dimensions_service.COST_CENTER_CODE
    )
    project_type_id = dimensions_service.get_specialized_dimension_type_id(
        company_id, dimensions_service.PROJECT_CODE
    )

    total_amount = decimal.Decimal("0")
    voucher_lines: list[treasury_service.MethodLine] = []
    for entry in method_lines:
        method_code, amount = entry[0], entry[1]
        note = entry[2] if len(entry) > 2 else None
        detail_account_id = entry[3] if len(entry) > 3 else None
        total_amount += amount
        default = settlements_service.get_pos_settlement_method_default(company_id, method_code)
        extra_details: dict[int, int] = {}
        if default is not None:
            if detail_account_id is None:
                detail_account_id = default.detail_account_id
            if default.cost_center_detail_account_id is not None:
                extra_details[cost_center_type_id] = default.cost_center_detail_account_id
            if default.project_detail_account_id is not None:
                extra_details[project_type_id] = default.project_detail_account_id
        voucher_lines.append(
            treasury_service.MethodLine(
                method=method_code, amount=amount, description=note or "",
                detail_account_id=detail_account_id, extra_details=(extra_details or None),
            )
        )

    description = f"دریافتِ صندوق (POS) -- بابتِ فاکتورِ فروشِ #{document_no}"
    counterparty_details = _resolve_receivable_counterparty_details(
        company_id, person_dimension_type_id, customer_id, cost_center_type_id, project_type_id,
    )
    voucher_result = treasury_service.create_treasury_voucher(
        company_id, user_id, "RECEIPT", mapping_account_id,
        counterparty_details, document_date, description,
        voucher_lines,
    )
    settlements_service.allocate_settlement(
        company_id, document_id, voucher_result.journal_entry_id, datetime.date.today(), total_amount, user_id,
        reference_no=reference_no, description=description,
    )
    return voucher_result.journal_entry_id


# ---------------------------------------------------------------------
# باشگاهِ مشتریان
# ---------------------------------------------------------------------
def get_or_create_loyalty_account(customer_detail_account_id: int) -> LoyaltyAccount:
    with new_session() as session:
        row = session.scalar(select(LoyaltyAccount).where(LoyaltyAccount.customer_detail_account_id == customer_detail_account_id))
        if row is None:
            row = LoyaltyAccount(customer_detail_account_id=customer_detail_account_id)
            session.add(row)
            session.commit()
            session.refresh(row)
        return row


def earn_points(customer_detail_account_id: int, points: int, document_id: int | None = None) -> None:
    account = get_or_create_loyalty_account(customer_detail_account_id)
    with new_session() as session:
        account_row = session.get(LoyaltyAccount, account.loyalty_account_id)
        account_row.points_balance += points
        session.add(LoyaltyTransaction(loyalty_account_id=account_row.loyalty_account_id, document_id=document_id, points_delta=points, transaction_type_code="EARN"))
        session.commit()


def redeem_wallet(customer_detail_account_id: int, amount: decimal.Decimal, document_id: int | None = None) -> None:
    account = get_or_create_loyalty_account(customer_detail_account_id)
    with new_session() as session:
        account_row = session.get(LoyaltyAccount, account.loyalty_account_id)
        if account_row.wallet_balance < amount:
            raise ValueError("موجودیِ کیف‌پول کافی نیست.")
        account_row.wallet_balance -= amount
        session.add(
            LoyaltyTransaction(
                loyalty_account_id=account_row.loyalty_account_id, document_id=document_id, wallet_delta=-amount,
                transaction_type_code="REDEEM",
            )
        )
        session.commit()


def top_up_wallet(customer_detail_account_id: int, amount: decimal.Decimal, document_id: int | None = None) -> None:
    account = get_or_create_loyalty_account(customer_detail_account_id)
    with new_session() as session:
        account_row = session.get(LoyaltyAccount, account.loyalty_account_id)
        account_row.wallet_balance += amount
        session.add(
            LoyaltyTransaction(
                loyalty_account_id=account_row.loyalty_account_id, document_id=document_id, wallet_delta=amount,
                transaction_type_code="ADJUST",
            )
        )
        session.commit()


# ---------------------------------------------------------------------
# کارتِ‌هدیه
# ---------------------------------------------------------------------
def issue_gift_card(company_id: int, code: str, initial_balance: decimal.Decimal, expires_at: datetime.datetime | None = None) -> int:
    with new_session() as session:
        row = GiftCard(company_id=company_id, code=code, initial_balance=initial_balance, current_balance=initial_balance, expires_at=expires_at)
        session.add(row)
        session.commit()
        return row.card_id


def redeem_gift_card(code: str, amount: decimal.Decimal) -> None:
    with new_session() as session:
        card = session.scalar(select(GiftCard).where(GiftCard.code == code))
        if card is None:
            raise ValueError("کارتِ‌هدیه نامعتبر است.")
        if card.status_code != "ACTIVE":
            raise ValueError("این کارتِ‌هدیه فعال نیست.")
        if card.expires_at is not None and card.expires_at < datetime.datetime.now(datetime.timezone.utc):
            card.status_code = "EXPIRED"
            session.commit()
            raise ValueError("کارتِ‌هدیه منقضی شده است.")
        if card.current_balance < amount:
            raise ValueError("موجودیِ کارتِ‌هدیه کافی نیست.")
        card.current_balance -= amount
        if card.current_balance == 0:
            card.status_code = "REDEEMED"
        session.commit()


# طبقِ عمومی‌سازیِ صریح («روشِ دریافت/پرداختِ اقساطی برایِ همه‌یِ
# فاکتورها، نه فقط POS»): create_installment_plan/mark_installment_paid/
# list_overdue_installments به services/installments.py منتقل شدند --
# این‌جا فقط payments_cover_total (بالا) مستقیماً از مدل‌هایِ
# InstallmentPlan/InstallmentLine برایِ جمعِ ساده استفاده می‌کند.


# ---------------------------------------------------------------------
# مشتریِ متفرقهٔ پیش‌فرض
# ---------------------------------------------------------------------
def get_pos_settings(company_id: int) -> PosSettings | None:
    with new_session() as session:
        return session.get(PosSettings, company_id)


def set_pos_settings(
    company_id: int, default_guest_customer_detail_account_id: int | None, cash_variance_threshold_amount: decimal.Decimal,
    quick_button_width: int = 110, quick_button_height: int = 64, quick_button_font_size: int = 10,
    quick_grid_columns: int = 6, allow_price_override: bool = True, allow_discount_override: bool = True,
    quick_access_enabled: bool = True, scan_beep_enabled: bool = True,
    receipt_header_text: str | None = None, receipt_footer_text: str | None = None,
    quick_access_position: str = "LEFT", quick_access_orientation: str = "HORIZONTAL",
    show_price_list_field: bool = True, show_tax_discount_breakdown: bool = True,
    show_customer_credit_warning: bool = True, recent_invoices_count: int = 10,
    fast_receipt_printing: bool = True,
) -> None:
    with new_session() as session:
        row = session.get(PosSettings, company_id)
        if row is None:
            session.add(
                PosSettings(
                    company_id=company_id, default_guest_customer_detail_account_id=default_guest_customer_detail_account_id,
                    cash_variance_threshold_amount=cash_variance_threshold_amount,
                    quick_button_width=quick_button_width, quick_button_height=quick_button_height,
                    quick_button_font_size=quick_button_font_size, quick_grid_columns=quick_grid_columns,
                    allow_price_override=allow_price_override, allow_discount_override=allow_discount_override,
                    quick_access_enabled=quick_access_enabled, scan_beep_enabled=scan_beep_enabled,
                    receipt_header_text=receipt_header_text, receipt_footer_text=receipt_footer_text,
                    quick_access_position=quick_access_position, quick_access_orientation=quick_access_orientation,
                    show_price_list_field=show_price_list_field, show_tax_discount_breakdown=show_tax_discount_breakdown,
                    show_customer_credit_warning=show_customer_credit_warning, recent_invoices_count=recent_invoices_count,
                    fast_receipt_printing=fast_receipt_printing,
                )
            )
        else:
            row.default_guest_customer_detail_account_id = default_guest_customer_detail_account_id
            row.cash_variance_threshold_amount = cash_variance_threshold_amount
            row.quick_button_width = quick_button_width
            row.quick_button_height = quick_button_height
            row.quick_button_font_size = quick_button_font_size
            row.quick_grid_columns = quick_grid_columns
            row.allow_price_override = allow_price_override
            row.allow_discount_override = allow_discount_override
            row.quick_access_enabled = quick_access_enabled
            row.scan_beep_enabled = scan_beep_enabled
            row.receipt_header_text = receipt_header_text
            row.receipt_footer_text = receipt_footer_text
            row.quick_access_position = quick_access_position
            row.quick_access_orientation = quick_access_orientation
            row.show_price_list_field = show_price_list_field
            row.show_tax_discount_breakdown = show_tax_discount_breakdown
            row.show_customer_credit_warning = show_customer_credit_warning
            row.recent_invoices_count = recent_invoices_count
            row.fast_receipt_printing = fast_receipt_printing
        session.commit()


def set_pos_receivable_dimension_defaults(
    company_id: int, cost_center_detail_account_id: int | None, project_detail_account_id: int | None,
) -> None:
    """طبقِ رفعِ باگِ واقعیِ گزارش‌شده («در فرمِ تاییدِ سرپرست، برایِ
    حسابِ مشتری مرکزِ هزینه/پروژه می‌خواهد»): جدا از set_pos_settings
    (که فیلدهایِ عمومیِ بیشتری دارد) -- فقط همین دو فیلد را به‌روز
    می‌کند، هم‌الگو با set_quick_button_layout."""
    with new_session() as session:
        row = session.get(PosSettings, company_id)
        if row is None:
            session.add(
                PosSettings(
                    company_id=company_id,
                    default_receivable_cost_center_detail_account_id=cost_center_detail_account_id,
                    default_receivable_project_detail_account_id=project_detail_account_id,
                )
            )
        else:
            row.default_receivable_cost_center_detail_account_id = cost_center_detail_account_id
            row.default_receivable_project_detail_account_id = project_detail_account_id
        session.commit()


# ---------------------------------------------------------------------
# گروه‌هایِ POS -- طبقِ درخواستِ صریح («کالا باید یک فیلدِ دسته‌بندیِ
# مخصوصِ POS داشته باشد که با دسته‌بندی‌هایِ دیگر فرق کند»): این
# گروه‌بندی کاملاً مستقل از inv.item_categories (دسته‌بندیِ عمومیِ
# انبار/گزارش) است -- فقط برایِ چیدمانِ تب‌هایِ دسترسیِ‌سریعِ صفحه‌یِ
# فروشِ حضوری، معادلِ «تعیینِ گروهِ کالاهایِ فروشگاه» در نمونه‌یِ ارجاعی.
# ---------------------------------------------------------------------
def list_menu_groups(company_id: int, active_only: bool = False) -> list[PosMenuGroup]:
    with new_session() as session:
        stmt = select(PosMenuGroup).where(PosMenuGroup.company_id == company_id)
        if active_only:
            stmt = stmt.where(PosMenuGroup.is_active.is_(True))
        stmt = stmt.order_by(PosMenuGroup.display_order, PosMenuGroup.group_id)
        return list(session.scalars(stmt))


def create_menu_group(company_id: int, name: str, display_order: int = 0) -> int:
    name = name.strip()
    if not name:
        raise ValueError("نامِ گروه را وارد کنید.")
    with new_session() as session:
        row = PosMenuGroup(company_id=company_id, name=name, display_order=display_order)
        session.add(row)
        session.commit()
        return row.group_id


def update_menu_group(
    group_id: int, company_id: int, name: str, display_order: int, is_active: bool,
    target_printer_name: str | None = None,
) -> None:
    name = name.strip()
    if not name:
        raise ValueError("نامِ گروه را وارد کنید.")
    with new_session() as session:
        row = session.get(PosMenuGroup, group_id)
        if row is None or row.company_id != company_id:
            raise ValueError("گروه نامعتبر است.")
        row.name = name
        row.display_order = display_order
        row.is_active = is_active
        row.target_printer_name = target_printer_name or None
        session.commit()


def resolve_target_printers_for_document(company_id: int, document_id: int) -> list[str]:
    """طبقِ درخواستِ صریح («ارسالِ هم‌زمانِ چند فاکتور به چند پرینترِ
    مختلف»): فهرستِ نام‌هایِ متمایزِ پرینترهایی که اقلامِ این فاکتور
    (بر اساسِ pos_menu_group_id) به آن‌ها تخصیص یافته‌اند -- خالی یعنی
    هیچ‌کدام از گروه‌هایِ اقلامِ این فاکتور پرینترِ اختصاصی ندارند (پس
    از همان جریانِ چاپِ معمولی/پیش‌فرض استفاده شود)."""
    with new_session() as session:
        line_item_ids = list(
            session.scalars(
                select(CommercialDocumentLine.item_id).where(CommercialDocumentLine.document_id == document_id)
            ).all()
        )
        if not line_item_ids:
            return []
        group_ids = set(
            session.scalars(
                select(Item.pos_menu_group_id).where(Item.item_id.in_(line_item_ids), Item.pos_menu_group_id.is_not(None))
            ).all()
        )
        if not group_ids:
            return []
        printer_names = session.scalars(
            select(PosMenuGroup.target_printer_name).where(
                PosMenuGroup.group_id.in_(group_ids), PosMenuGroup.company_id == company_id,
                PosMenuGroup.target_printer_name.is_not(None),
            )
        ).all()
        return sorted({name for name in printer_names if name})


def delete_menu_group(group_id: int, company_id: int) -> None:
    with new_session() as session:
        row = session.get(PosMenuGroup, group_id)
        if row is None or row.company_id != company_id:
            raise ValueError("گروه نامعتبر است.")
        in_use = session.scalar(select(func.count()).select_from(Item).where(Item.pos_menu_group_id == group_id))
        if in_use:
            raise ValueError("این گروه به کالایی نسبت داده شده و قابلِ‌حذف نیست.")
        session.delete(row)
        session.commit()


# ---------------------------------------------------------------------
# تنظیماتِ صندوق‌داریِ هر (کاربر، شرکت) -- طبقِ درخواستِ صریح («این
# تنظیمات در قسمتِ تنظیماتِ کاربر با نقشِ صندوق‌دار باید تعریف بشه»):
# هر کاربر می‌تواند ترمینال/فهرستِ‌قیمت/مشتریِ پیش‌فرضِ خودش را (به‌ازایِ
# هر شرکت، چون این‌ها همه چیزهایِ شرکت‌محورند) داشته باشد تا صفحه‌یِ
# فروشِ حضوری دیگر هر بار این‌ها را از او نپرسد.
# ---------------------------------------------------------------------
def get_cashier_settings(user_id: int, company_id: int) -> PosCashierSettings | None:
    with new_session() as session:
        return session.get(PosCashierSettings, {"user_id": user_id, "company_id": company_id})


def set_cashier_settings(
    user_id: int, company_id: int, default_terminal_id: int | None, default_price_list_id: int | None,
    default_customer_detail_account_id: int | None,
) -> None:
    with new_session() as session:
        row = session.get(PosCashierSettings, {"user_id": user_id, "company_id": company_id})
        if row is None:
            session.add(
                PosCashierSettings(
                    user_id=user_id, company_id=company_id, default_terminal_id=default_terminal_id,
                    default_price_list_id=default_price_list_id,
                    default_customer_detail_account_id=default_customer_detail_account_id,
                )
            )
        else:
            row.default_terminal_id = default_terminal_id
            row.default_price_list_id = default_price_list_id
            row.default_customer_detail_account_id = default_customer_detail_account_id
        session.commit()


def set_quick_button_layout(
    user_id: int, company_id: int, order: str | None, width_override: int | None, height_override: int | None,
) -> None:
    """طبقِ درخواستِ صریح («جابه‌جاییِ دستیِ کلیدهایِ فوری با ماوس + عرضِ
    قابلِ‌تنظیم، به‌ازایِ هر کاربر»): برخلافِ set_cashier_settings (که
    ترمینال/فهرستِ‌قیمت/مشتری را یک‌جا جایگزین می‌کند)، این تابع فقط
    همین سه فیلدِ چیدمان را به‌روز می‌کند -- بدونِ نیاز به دانستنِ سایرِ
    مقادیرِ تنظیماتِ صندوق‌دار در هر بار."""
    with new_session() as session:
        row = session.get(PosCashierSettings, {"user_id": user_id, "company_id": company_id})
        if row is None:
            session.add(
                PosCashierSettings(
                    user_id=user_id, company_id=company_id, quick_button_order=order,
                    quick_button_width_override=width_override, quick_button_height_override=height_override,
                )
            )
        else:
            row.quick_button_order = order
            row.quick_button_width_override = width_override
            row.quick_button_height_override = height_override
        session.commit()


def list_recent_pos_invoices(company_id: int, limit: int = 10) -> list[CommercialDocument]:
    """طبقِ درخواستِ صریح («۱۰ فاکتور یا تعدادِ دلخواهِ تک‌فروشی را نمایش
    و از همان‌جا هم بتوان اصلاح کرد»): برخلافِ list_pending_pos_documents
    (که فقط رزروها/تاییدشده‌هایِ همین شیفتِ باز را می‌خواند)، این‌جا
    آخرین فاکتورهایِ تک‌فروشیِ همین شرکت -- در هر وضعیت و هر شیفتی --
    برمی‌گردد."""
    with new_session() as session:
        stmt = (
            select(CommercialDocument)
            .where(
                CommercialDocument.company_id == company_id,
                CommercialDocument.document_type_code == "SALES_INVOICE",
                CommercialDocument.pos_session_id.is_not(None),
            )
            .order_by(CommercialDocument.document_id.desc())
            .limit(limit)
        )
        return list(session.scalars(stmt))
