"""مالی و خزانه: سند پرداخت، سند دریافت، هزینهٔ تنخواه و سند حسابداری دستی.

اقدام «تایید نهایی» همان تایید کارتابل سند است (موقت ← دائم) و دروازه از دائم‌شدن بدون تایید فرایند جلوگیری می‌کند.
سندهای خودکار ماژول‌ها (فروش، انبار، حقوق، دارایی) به گردش کار وصل نمی‌شوند.
"""

from __future__ import annotations

import decimal

from sqlalchemy import func, select, text

from peecha.db.base import new_session
from peecha.db.models.accounting import JournalEntry, JournalEntryLine, JournalEntryStatus, JournalEntryType
from peecha.services.workflow import model_events, registry
from peecha.services.workflow.adapters._common import ZERO, jdate, money, user_name
from peecha.services.workflow.common import WorkflowError
from peecha.services.workflow.model_events import Watch
from peecha.services.workflow.registry import ActionContext, ActionSpec, EntityAdapter, FieldSpec

# نوع سند حسابداری ← (نوع سند گردش کار، برچسب)
KINDS = {"PAYMENT": ("PAYMENT_VOUCHER", "سند پرداخت"), "RECEIPT": ("RECEIPT_VOUCHER", "سند دریافت"),
         "TANKHAH": ("PETTY_CASH_EXPENSE", "هزینهٔ تنخواه"), "NORMAL": ("JOURNAL_ENTRY", "سند حسابداری"),
         "ADJUSTING": ("JOURNAL_ENTRY", "سند حسابداری")}
FORMS = {"PAYMENT_VOUCHER": "treasury_voucher_payment", "RECEIPT_VOUCHER": "treasury_voucher_receipt",
         "PETTY_CASH_EXPENSE": "treasury_petty_cash", "JOURNAL_ENTRY": "journal_entry"}
STATUS = {"DRAFT": "پیش‌نویس", "TEMPORARY": "موقت", "PERMANENT": "دائم", "REVERSED": "برگشت‌خورده", "CANCELLED": "باطل‌شده"}
_TYPE_CODES: dict[int, str] = {}
_STATUS_CODES: dict[int, str] = {}


def _codes(model, key: str, cache: dict) -> dict:
    if not cache:
        with new_session() as session:
            cache.update({getattr(r, key): r.code for r in session.scalars(select(model))})
    return cache


def _entity_type(entry: JournalEntry) -> str | None:
    code = _codes(JournalEntryType, "entry_type_id", _TYPE_CODES).get(entry.entry_type_id)
    if code in ("NORMAL", "ADJUSTING") and entry.is_system_generated:
        return None
    return KINDS.get(code, (None,))[0]


def _status(conn, status_id) -> str | None:
    if not _STATUS_CODES:
        _STATUS_CODES.update({r[0]: r[1] for r in conn.execute(text("SELECT status_id, code FROM acc.journal_entry_statuses"))})
    return _STATUS_CODES.get(int(status_id))


def je_context(company_id: int, journal_entry_id: int) -> dict:
    with new_session() as session:
        e = session.get(JournalEntry, journal_entry_id)
        if e is None or e.company_id != company_id:
            raise WorkflowError("سند حسابداری پیدا نشد.")
        debit, lines = session.execute(select(func.coalesce(func.sum(JournalEntryLine.debit_amount_base), 0), func.count())
                                       .where(JournalEntryLine.journal_entry_id == journal_entry_id)).one()
        return {"journal_entry_id": e.journal_entry_id, "temporary_no": e.temporary_no, "permanent_no": e.permanent_no,
                "document_date": e.document_date, "description": e.description or "",
                "entry_type": _codes(JournalEntryType, "entry_type_id", _TYPE_CODES).get(e.entry_type_id),
                "status": _codes(JournalEntryStatus, "status_id", _STATUS_CODES).get(e.status_id),
                "amount": decimal.Decimal(debit or ZERO), "line_count": int(lines), "created_by": e.created_by_user_id,
                "created_by_name": user_name(session, e.created_by_user_id), "source_system": e.source_system,
                "is_system_generated": bool(e.is_system_generated)}


def _approve(ctx: ActionContext) -> dict:
    from peecha.services import journal_entries

    permanent_no = journal_entries.approve_journal_entry(int(ctx.entity_id), ctx.company_id, ctx.user_id)
    return {"permanent_no": permanent_no}


def _is_permanent(company_id: int, journal_entry_id: int) -> bool:
    return je_context(company_id, journal_entry_id)["status"] in ("PERMANENT", "REVERSED")


def _card(company_id: int, journal_entry_id: int) -> list[tuple[str, str]]:
    c = je_context(company_id, journal_entry_id)
    return [("شمارهٔ موقت", str(c["temporary_no"])), ("تاریخ", jdate(c["document_date"])), ("مبلغ", money(c["amount"])),
            ("شرح", c["description"] or "—"), ("ثبت‌کننده", c["created_by_name"] or "—"),
            ("وضعیت", STATUS.get(c["status"] or "", c["status"] or ""))]


FIELDS = (FieldSpec("amount", "مبلغ سند", "money"), FieldSpec("created_by", "ثبت‌کننده", "user"),
          FieldSpec("document_date", "تاریخ سند", "date"), FieldSpec("line_count", "تعداد ردیف", "number"),
          FieldSpec("status", "وضعیت", "choice", STATUS), FieldSpec("source_system", "منشأ سند", "text"),
          FieldSpec("is_system_generated", "سند خودکار", "bool"))

for _et, _label in {v[0]: v[1] for v in KINDS.values()}.items():
    registry.register_adapter(EntityAdapter(
        _et, _label, "ACCOUNTING", je_context, fields=FIELDS,
        events={f"{_et}_CREATED": f"ثبت «{_label}»", f"{_et}_TEMPORARY": f"موقت‌شدن «{_label}»",
                f"{_et}_PERMANENT": f"دائم‌شدن «{_label}»"},
        actions={"approve": ActionSpec("approve", "تایید نهایی (دائم‌کردن سند)", _approve, risk="HIGH", is_done=_is_permanent)},
        title=lambda c, _l=_label: f"{_l} شمارهٔ {c.get('temporary_no')} — {money(c.get('amount'))}",
        owner=lambda cid, eid: je_context(cid, eid)["created_by"], approval_context=_card, open_nav="GL_JE",
        open_method="edit_journal_entry", submitter_field="created_by", gate_statuses=("PERMANENT",),
        gate_label="تا تایید فرایند، سند دائم نمی‌شود", form_code=FORMS[_et]))

model_events.watch(Watch(JournalEntry, _entity_type, status_attr="status_id", status_code=_status,
                         actor=lambda e: e.created_by_user_id))
