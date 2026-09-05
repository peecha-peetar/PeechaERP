"""تسویه‌یِ فاکتور (comm.invoice_settlements/comm.settlement_alarm_settings)
-- طبقِ درخواستِ صریح («هر دریافت و پرداخت رفرنسِ فاکتور را داشته باشد و
مدیریتِ تسویه‌یِ فاکتورها را ایجاد کن»).

چون هر رسیدِ خزانه‌داری در این برنامه چیزی جز یک سندِ حسابداری
(acc.journal_entries) نیست (هیچ جدولِ «سندِ خزانه‌داری»یِ جداگانه‌ای وجود
ندارد)، تخصیصِ دریافت/پرداخت به فاکتور به‌صورتِ دستی -- از یک صفحه‌یِ
جداگانه‌یِ «مدیریتِ تسویه» -- به journal_entry_id وصل می‌شود؛ خودِ فرمِ
دریافت/پرداخت (treasury_voucher.py) دست‌نخورده می‌ماند."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import JournalEntry
from peecha.db.models.commercial import (
    CommercialDocument,
    CommercialDocumentSettlementPlan,
    CommercialDocumentSettlementPlanLine,
    CustomerProfile,
    InvoiceSettlement,
    SettlementAlarmSettings,
    SupplierProfile,
)
from peecha.services import roles as roles_service

_ZERO = decimal.Decimal("0")
_INVOICE_TYPES = ("SALES_INVOICE", "PURCHASE_INVOICE")

# طبقِ درخواستِ صریح («نقد/نسیه/بانک یا همون کارتخوان/بن/کالابرگ/تخفیف»):
# «نسیه» ردیفِ روش نیست -- همان مانده‌یِ پوشش‌داده‌نشده‌یِ فاکتور است که
# خودکار محاسبه می‌شود؛ «بانک یا همون کارتخوان» هم یک روش است (BANK) --
# کارتخوان صرفاً روشِ وصولِ همان تسویه‌یِ بانکی است. کدها/برچسب‌ها هم‌الگو
# با METHOD_CODES/_METHOD_LABELS در services/treasury.py و
# ui/screens/treasury_voucher.py (زیرمجموعه‌یِ همان‌ها، بدونِ چک/تهاتر/
# اقساط که این‌جا موضوعیت ندارند).
SETTLEMENT_PLAN_METHOD_LABELS = {
    "CASH": "نقدی",
    "BANK": "بانکی / کارتخوان",
    "DISCOUNT": "تخفیف",
    "GOODS_COUPON": "کالابرگ",
    "VOUCHER": "بن",
}
_SETTLEMENT_PLAN_RECEIPT_METHODS = ("CASH", "BANK", "GOODS_COUPON", "VOUCHER", "DISCOUNT")
_SETTLEMENT_PLAN_PAYMENT_METHODS = ("CASH", "BANK", "DISCOUNT")


def settlement_plan_method_codes(document_type_code: str) -> tuple[str, ...]:
    return _SETTLEMENT_PLAN_RECEIPT_METHODS if document_type_code == "SALES_INVOICE" else _SETTLEMENT_PLAN_PAYMENT_METHODS


@dataclass
class SettlementPlanLine:
    method_code: str
    amount: decimal.Decimal
    note: str | None = None


@dataclass
class SettlementPlan:
    plan_id: int
    document_id: int
    status_code: str
    total_amount: decimal.Decimal
    lines: list[SettlementPlanLine]
    created_by_user_id: int
    created_at: datetime.datetime
    approved_by_user_id: int | None
    approved_at: datetime.datetime | None

    @property
    def is_approved(self) -> bool:
        return self.status_code == "APPROVED"

    @property
    def lines_total(self) -> decimal.Decimal:
        return sum((ln.amount for ln in self.lines), _ZERO)

    @property
    def remaining_on_credit(self) -> decimal.Decimal:
        """طبقِ درخواستِ صریح: مانده‌یِ پوشش‌داده‌نشده‌یِ فاکتور یعنی «نسیه» --
        نیازی به ردیفِ جداگانه ندارد."""
        return self.total_amount - self.lines_total


def get_settlement_plan(document_id: int, company_id: int) -> SettlementPlan | None:
    with new_session() as session:
        plan = session.scalar(
            select(CommercialDocumentSettlementPlan).where(
                CommercialDocumentSettlementPlan.document_id == document_id,
                CommercialDocumentSettlementPlan.company_id == company_id,
            )
        )
        if plan is None:
            return None
        line_rows = session.scalars(
            select(CommercialDocumentSettlementPlanLine)
            .where(CommercialDocumentSettlementPlanLine.plan_id == plan.plan_id)
            .order_by(CommercialDocumentSettlementPlanLine.display_order)
        ).all()
        return SettlementPlan(
            plan_id=plan.plan_id, document_id=plan.document_id, status_code=plan.status_code,
            total_amount=plan.total_amount,
            lines=[SettlementPlanLine(method_code=ln.method_code, amount=ln.amount, note=ln.note) for ln in line_rows],
            created_by_user_id=plan.created_by_user_id, created_at=plan.created_at,
            approved_by_user_id=plan.approved_by_user_id, approved_at=plan.approved_at,
        )


def save_settlement_plan(
    document_id: int, company_id: int, created_by_user_id: int, lines: list[tuple[str, decimal.Decimal, str | None]],
) -> int:
    """ذخیره/بازنویسیِ نقشه‌یِ تسویه‌یِ یک فاکتورِ خرید/فروش -- طبقِ درخواستِ
    صریح («چند تا مورد از این نحوه تسویه... و با تاییدِ مدیر»): هر بار که
    نقشه ذخیره می‌شود (حتی بعدِ تایید)، وضعیت به PENDING_APPROVAL برمی‌گردد
    -- تاییدِ قبلی برایِ ترکیبِ تازه دیگر معتبر نیست و باید دوباره تاییدشود."""
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("فاکتور نامعتبر است.")
        if doc.document_type_code not in _INVOICE_TYPES:
            raise ValueError("نقشه‌یِ تسویه فقط برایِ فاکتورِ خرید/فروش ممکن است.")
        if doc.status_code == "POSTED":
            raise ValueError("فاکتورِ ثبتِ‌نهایی‌شده دیگر نقشه‌یِ تسویه‌اش قابلِ‌تغییر نیست.")
        allowed_methods = set(settlement_plan_method_codes(doc.document_type_code))
        cleaned: list[tuple[str, decimal.Decimal, str | None]] = []
        for method_code, amount, note in lines:
            if method_code not in allowed_methods:
                raise ValueError("روشِ ردیف نامعتبر است.")
            if amount <= _ZERO:
                raise ValueError("مبلغِ هر ردیف باید مثبت باشد.")
            cleaned.append((method_code, amount, note))
        lines_total = sum((amount for _m, amount, _n in cleaned), _ZERO)
        if lines_total > doc.total_amount:
            raise ValueError(f"جمعِ ردیف‌ها ({lines_total}) از مبلغِ کلِ فاکتور ({doc.total_amount}) بیشتر است.")

        plan = session.scalar(
            select(CommercialDocumentSettlementPlan).where(CommercialDocumentSettlementPlan.document_id == document_id)
        )
        if plan is None:
            plan = CommercialDocumentSettlementPlan(
                company_id=company_id, document_id=document_id, status_code="PENDING_APPROVAL",
                total_amount=doc.total_amount, created_by_user_id=created_by_user_id,
            )
            session.add(plan)
            session.flush()
        else:
            session.execute(
                CommercialDocumentSettlementPlanLine.__table__.delete().where(
                    CommercialDocumentSettlementPlanLine.plan_id == plan.plan_id
                )
            )
            plan.status_code = "PENDING_APPROVAL"
            plan.total_amount = doc.total_amount
            plan.approved_by_user_id = None
            plan.approved_at = None

        for display_order, (method_code, amount, note) in enumerate(cleaned):
            session.add(
                CommercialDocumentSettlementPlanLine(
                    plan_id=plan.plan_id, method_code=method_code, amount=amount, note=(note or None),
                    display_order=display_order,
                )
            )
        session.commit()
        return plan.plan_id


def can_approve_settlement_plan(user_id: int, company_id: int) -> bool:
    """طبقِ درخواستِ صریح: فقط برایِ نمایش/پنهان‌کردنِ دکمه‌یِ «تاییدِ
    مدیر» در UI -- خودِ approve_settlement_plan هم دوباره همین شرط را
    اعتبارسنجی می‌کند (هم‌الگو با can_correct_posted_document)."""
    return roles_service.is_manager(user_id, company_id)


def approve_settlement_plan(document_id: int, company_id: int, approved_by_user_id: int) -> None:
    if not roles_service.is_manager(approved_by_user_id, company_id):
        raise ValueError("تاییدِ نحوه‌یِ تسویه فقط برایِ مدیر (نقشِ ادمین/سوپروایزر/مدیر) ممکن است.")
    with new_session() as session:
        plan = session.scalar(
            select(CommercialDocumentSettlementPlan).where(
                CommercialDocumentSettlementPlan.document_id == document_id,
                CommercialDocumentSettlementPlan.company_id == company_id,
            )
        )
        if plan is None:
            raise ValueError("ابتدا نحوه‌یِ تسویه را ذخیره کنید.")
        if plan.status_code == "APPROVED":
            raise ValueError("این نقشه‌یِ تسویه قبلاً تاییدشده است.")
        doc = session.get(CommercialDocument, document_id)
        if doc is not None and plan.total_amount != doc.total_amount:
            raise ValueError("مبلغِ فاکتور پس از ذخیره‌یِ نقشه تغییر کرده — ابتدا نقشه را دوباره ذخیره کنید.")
        plan.status_code = "APPROVED"
        plan.approved_by_user_id = approved_by_user_id
        plan.approved_at = datetime.datetime.now()
        session.commit()


def require_approved_settlement_plan(document_id: int, company_id: int) -> SettlementPlan:
    """طبقِ درخواستِ صریح («با تاییدِ مدیر... فاکتور سند بخوره و تسویه
    بشه»): برایِ فاکتورِ خرید/فروش، ثبتِ نهایی بدونِ نقشه‌یِ تسویه‌یِ
    تاییدشده مسدود می‌شود -- این تابع همان دروازه است (هم در سرویسِ
    ثبتِ‌نهایی و هم در UI بررسی می‌شود)."""
    plan = get_settlement_plan(document_id, company_id)
    if plan is None:
        raise ValueError("پیش از ثبتِ نهایی، ابتدا از دکمه‌یِ «نحوه‌یِ تسویه» نحوه‌یِ پرداخت را مشخص کنید.")
    if not plan.is_approved:
        raise ValueError("نحوه‌یِ تسویه هنوز توسطِ مدیر تاییدنشده است.")
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is not None and plan.total_amount != doc.total_amount:
            raise ValueError("مبلغِ فاکتور پس از تاییدِ نقشه‌یِ تسویه تغییر کرده — نقشه را دوباره ذخیره و تایید کنید.")
    return plan


def auto_approve_full_cash_settlement_plan(document_id: int, company_id: int, user_id: int) -> None:
    """میان‌بُرِ برنامه‌نویسی/تستی -- برایِ جاهایی (مثلاً ابزارهایِ داخلی
    یا فراخوانی‌هایِ خودکار) که واقعاً به ترکیبِ تسویه اهمیتی نمی‌دهند و
    فقط می‌خواهند مسیرِ استانداردِ ثبتِ نهایی را طیّ کنند: کلِ مبلغِ فاکتور
    را یک‌جا «نقدی» ثبت و بلافاصله (با همین کاربر) تاییدِ مدیر می‌کند.
    گذرگاهِ واقعیِ کاربرِ نهایی همچنان دکمه‌یِ «نحوه‌یِ تسویه» در UI است."""
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("فاکتور نامعتبر است.")
        total_amount = doc.total_amount
    lines = [("CASH", total_amount, None)] if total_amount > _ZERO else []
    save_settlement_plan(document_id, company_id, user_id, lines)
    approve_settlement_plan(document_id, company_id, user_id)


def compute_due_date(
    company_id: int, document_type_code: str, counterparty_detail_account_id: int, document_date: datetime.date,
) -> datetime.date | None:
    """موعدِ تسویه از رویِ payment_term_days طرفِ‌حساب -- اگر طرفِ‌حساب
    پروفایلِ مشتری/تامین‌کننده نداشته باشد (مثلاً حسابِ عمومیِ نقدی)، None
    برمی‌گردد (یعنی «بدونِ موعدِ مشخص»)."""
    if document_type_code not in _INVOICE_TYPES:
        return None
    with new_session() as session:
        if document_type_code == "SALES_INVOICE":
            profile = session.get(CustomerProfile, counterparty_detail_account_id)
        else:
            profile = session.get(SupplierProfile, counterparty_detail_account_id)
        if profile is None:
            return None
        return document_date + datetime.timedelta(days=profile.payment_term_days)


@dataclass
class InvoiceSettlementStatus:
    document_id: int
    total_amount: decimal.Decimal
    settled_amount: decimal.Decimal
    remaining_amount: decimal.Decimal
    due_date: datetime.date | None

    @property
    def is_fully_settled(self) -> bool:
        return self.remaining_amount <= _ZERO


def _settled_amount(session, document_id: int) -> decimal.Decimal:
    return session.scalar(
        select(func.coalesce(func.sum(InvoiceSettlement.amount), 0)).where(
            InvoiceSettlement.invoice_document_id == document_id
        )
    ) or _ZERO


def get_invoice_settlement_status(document_id: int, company_id: int) -> InvoiceSettlementStatus:
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        settled = _settled_amount(session, document_id)
        return InvoiceSettlementStatus(
            document_id=document_id, total_amount=doc.total_amount, settled_amount=settled,
            remaining_amount=doc.total_amount - settled, due_date=doc.due_date,
        )


def list_unsettled_invoices(company_id: int, document_type_code: str | None = None) -> list[InvoiceSettlementStatus]:
    """طبقِ درخواستِ صریح: فهرستِ فاکتورهایِ ثبت‌شده که هنوز به‌طورِ کامل
    تسویه نشده‌اند -- برایِ صفحه‌یِ «فاکتورهایِ تسویه‌نشده» و ورودیِ
    صفحه‌یِ «مدیریتِ تسویه». عمداً فقط POSTED (نه CORRECTED) -- فاکتورِ
    اصلاح‌شده دیگر مبلغِ معتبر ندارد؛ فاکتورِ *جایگزین*ِ آن (که خودش POSTED
    است) همان است که باید تسویه شود."""
    with new_session() as session:
        stmt = select(CommercialDocument).where(
            CommercialDocument.company_id == company_id,
            CommercialDocument.status_code == "POSTED",
        )
        if document_type_code:
            stmt = stmt.where(CommercialDocument.document_type_code == document_type_code)
        else:
            stmt = stmt.where(CommercialDocument.document_type_code.in_(_INVOICE_TYPES))
        docs = session.scalars(stmt.order_by(CommercialDocument.document_id.desc())).all()
        result = []
        for doc in docs:
            settled = _settled_amount(session, doc.document_id)
            remaining = doc.total_amount - settled
            if remaining > _ZERO:
                result.append(InvoiceSettlementStatus(
                    document_id=doc.document_id, total_amount=doc.total_amount, settled_amount=settled,
                    remaining_amount=remaining, due_date=doc.due_date,
                ))
        return result


def list_invoices_due_soon(company_id: int, document_type_code: str | None = None) -> list[InvoiceSettlementStatus]:
    """طبقِ درخواستِ صریح («آپشنی که N روز مانده به موعدِ تسویه آلارم
    بدهد»): فقط اگر آلارم برایِ این شرکت فعال باشد، فاکتورهایِ
    تسویه‌نشده‌ای که سررسیدشان ظرفِ alarm_days_before روزِ آینده است (یا
    گذشته -- معوقه) را برمی‌گرداند.

    طبقِ رفعِ باگِ واقعی («این آلارم کجا نمایش داده می‌شود؟» -- تا این‌جا
    هیچ صفحه‌ای این تابع را صدا نمی‌زد): حالا در commercial_settlement.py
    مستقیماً به‌عنوانِ یک بنرِ هشدار در بالایِ فرمِ تسویه استفاده می‌شود."""
    settings = get_alarm_settings(company_id)
    if not settings.is_enabled or settings.alarm_days_before <= 0:
        return []
    threshold = datetime.date.today() + datetime.timedelta(days=settings.alarm_days_before)
    return [
        status for status in list_unsettled_invoices(company_id, document_type_code)
        if status.due_date is not None and status.due_date <= threshold
    ]


def list_settlements_for_invoice(document_id: int, company_id: int) -> list[InvoiceSettlement]:
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند نامعتبر است.")
        return list(session.scalars(
            select(InvoiceSettlement).where(InvoiceSettlement.invoice_document_id == document_id)
            .order_by(InvoiceSettlement.settlement_date.desc(), InvoiceSettlement.settlement_id.desc())
        ))


def list_settlements_for_journal_entry(journal_entry_id: int, company_id: int) -> list[InvoiceSettlement]:
    with new_session() as session:
        je = session.get(JournalEntry, journal_entry_id)
        if je is None or je.company_id != company_id:
            raise ValueError("سندِ حسابداری نامعتبر است.")
        return list(session.scalars(
            select(InvoiceSettlement).where(InvoiceSettlement.journal_entry_id == journal_entry_id)
            .order_by(InvoiceSettlement.settlement_id.desc())
        ))


def allocate_settlement(
    company_id: int, invoice_document_id: int, journal_entry_id: int | None, settlement_date: datetime.date,
    amount: decimal.Decimal, created_by_user_id: int, reference_no: str | None = None, description: str | None = None,
) -> int:
    """طبقِ درخواستِ صریح: تخصیصِ (بخشی از) یک دریافت/پرداختِ ثبت‌شده به یک
    فاکتور -- تسویه‌یِ جزئی مجاز است (چند بار روی یک فاکتور)، اما مبلغِ
    هرباره نمی‌تواند از مانده‌یِ فاکتور بیشتر باشد."""
    if amount <= _ZERO:
        raise ValueError("مبلغِ تسویه باید مثبت باشد.")
    with new_session() as session:
        doc = session.get(CommercialDocument, invoice_document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("فاکتور نامعتبر است.")
        if doc.document_type_code not in _INVOICE_TYPES:
            raise ValueError("تسویه فقط برایِ فاکتورِ خرید/فروش ممکن است.")
        if doc.status_code != "POSTED":
            raise ValueError("فقط فاکتورِ ثبتِ‌نهایی‌شده (و نه اصلاح‌شده/لغوشده) قابلِ‌تسویه است.")
        if journal_entry_id is not None:
            je = session.get(JournalEntry, journal_entry_id)
            if je is None or je.company_id != company_id:
                raise ValueError("سندِ حسابداریِ دریافت/پرداخت نامعتبر است.")
        settled = _settled_amount(session, invoice_document_id)
        remaining = doc.total_amount - settled
        if amount > remaining:
            raise ValueError(f"مبلغِ تسویه از مانده‌یِ فاکتور ({remaining}) بیشتر است.")
        settlement = InvoiceSettlement(
            company_id=company_id, invoice_document_id=invoice_document_id, journal_entry_id=journal_entry_id,
            settlement_date=settlement_date, amount=amount, reference_no=(reference_no or None),
            description=(description or None), created_by_user_id=created_by_user_id,
        )
        session.add(settlement)
        session.commit()
        return settlement.settlement_id


def remove_settlement(settlement_id: int, company_id: int) -> None:
    with new_session() as session:
        settlement = session.get(InvoiceSettlement, settlement_id)
        if settlement is None or settlement.company_id != company_id:
            raise ValueError("تسویه نامعتبر است.")
        session.delete(settlement)
        session.commit()


def get_alarm_settings(company_id: int) -> SettlementAlarmSettings:
    with new_session() as session:
        settings = session.get(SettlementAlarmSettings, company_id)
        if settings is None:
            return SettlementAlarmSettings(company_id=company_id, is_enabled=False, alarm_days_before=2)
        session.expunge(settings)
        return settings


def set_alarm_settings(company_id: int, is_enabled: bool, alarm_days_before: int) -> None:
    if alarm_days_before < 0:
        raise ValueError("تعدادِ روز نمی‌تواند منفی باشد.")
    with new_session() as session:
        settings = session.get(SettlementAlarmSettings, company_id)
        if settings is None:
            session.add(SettlementAlarmSettings(
                company_id=company_id, is_enabled=is_enabled, alarm_days_before=alarm_days_before,
            ))
        else:
            settings.is_enabled = is_enabled
            settings.alarm_days_before = alarm_days_before
        session.commit()
