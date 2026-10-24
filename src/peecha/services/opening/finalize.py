"""قفل نهایی، افتتاحیهٔ اصلاحی و سیاست تاریخ برش (R314).

قفل: همهٔ اسناد حسابداری ساخته‌شده با سرویس رسمی دائم می‌شوند (approve_journal_entry) و ماژول‌ها/فرایند قفل می‌شوند؛
پس از آن تغییر فقط با «افتتاحیهٔ اصلاحی» است: ردیف‌های تازه (افزوده) مثل افتتاحیهٔ اصلی ثبت می‌شوند، تراز اصلاحی
«تفاوت» را می‌برد و سند باز منتقل‌شدهٔ اشتباه با سند برگشتی کنار می‌رود (همه با ردپا).
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.opening import OpeningRun, Posting, RunModule, StagedRow
from peecha.services.opening import common as c
from peecha.services.opening import reconcile, runs

PRE_CUTOVER_NOTE = "تسویه‌شده پیش از برش در سیستم قبلی"


def run_journal_entries(session, run_id: int) -> list[int]:
    return sorted(set(session.scalars(select(Posting.journal_entry_id).where(
        Posting.run_id == run_id, Posting.status_code == "DONE", Posting.journal_entry_id.is_not(None)))))


def lock_run(company_id: int, user_id: int, run_id: int, comment: str | None = None) -> SimpleNamespace:
    """قفل نهایی: فقط فرایند ثبت‌شده با حساب واسط صفر. اجرای دوباره، سندهای دائم‌شده را رد می‌کند و ادامه می‌دهد."""
    from peecha.db.models.accounting import JournalEntry, JournalEntryStatus
    from peecha.services import journal_entries as je_service

    c.require(company_id, user_id, c.FORM_POST)
    with new_session() as session:
        run = runs._run(session, company_id, run_id, lock=True)
        if run.status_code == "LOCKED":
            raise ValueError("این فرایند قبلاً قفل شده است.")
        if run.status_code != "POSTED":
            raise ValueError("فقط فرایندی که همهٔ ماژول‌هایش ثبت قطعی شده قفل می‌شود.")
        rec = reconcile.compute(session, company_id, run_id)
        if rec.clearing_posted:
            raise ValueError(f"ماندهٔ حساب واسط این فرایند صفر نیست ({rec.clearing_posted:,})؛ قفل ممکن نیست.")
        entries = run_journal_entries(session, run_id)
        temporary = session.scalar(select(JournalEntryStatus.status_id).where(JournalEntryStatus.code == "TEMPORARY"))
        pending = list(session.scalars(select(JournalEntry.journal_entry_id).where(
            JournalEntry.journal_entry_id.in_(entries or [-1]), JournalEntry.status_id == temporary)))
    for je in pending:
        je_service.approve_journal_entry(je, company_id, user_id)
    with new_session() as session:
        run = runs._run(session, company_id, run_id, lock=True)
        for m in session.scalars(select(RunModule).where(RunModule.run_id == run_id)):
            m.status_code = "LOCKED"
        run.status_code, run.locked_by_user_id, run.locked_at = "LOCKED", user_id, c.now()
        c.event(session, run_id, "LOCK", user_id, comment=comment, details={"journal_entries": entries})
        c.audit(session, company_id, user_id, run_id, "LOCK", {"journal_entries": entries})
        session.commit()
    return SimpleNamespace(journal_entries=entries, approved_now=len(pending))


# --- افتتاحیهٔ اصلاحی: برگشت سند باز منتقل‌شده ---------------------------------------------------------------
def reverse_open_item(company_id: int, user_id: int, run_id: int, original_row_id: int, reason: str) -> int:
    """سند باز دریافتنی/پرداختنی منتقل‌شدهٔ اشتباه: سند برگشتی (طرف مقابل حساب واسط) و ابطال سند باز. فقط اگر پس از
    برش تسویه‌ای روی آن ثبت نشده باشد. خروجی: شمارهٔ سند حسابداری برگشتی."""
    from peecha.db.models.accounting import JournalEntryLine, JournalEntryLineDetail
    from peecha.db.models.commercial import CommercialDocument, InvoiceSettlement
    from peecha.services import journal_entries as je_service

    if not (reason or "").strip():
        raise ValueError("دلیل برگشت را بنویسید.")
    c.require(company_id, user_id, c.FORM_CORRECT)
    with new_session() as session:
        run = runs._run(session, company_id, run_id, lock=True)
        if run.kind_code != "CORRECTION" or run.status_code not in runs.ENTRY_RUN:
            raise ValueError("برگشت ردیف ثبت‌شده فقط در افتتاحیهٔ اصلاحی در جریان ممکن است.")
        original = session.get(OpeningRun, run.corrects_run_id)
        if original.status_code != "LOCKED":
            raise ValueError("افتتاحیهٔ اصلی هنوز قفل نشده است.")
        row = session.scalar(select(StagedRow).where(StagedRow.row_id == original_row_id).with_for_update())
        if row is None or row.run_id != original.run_id or row.module_code not in ("RECEIVABLES", "PAYABLES"):
            raise ValueError("ردیف باید سند باز دریافتنی/پرداختنی همان افتتاحیهٔ اصلی باشد.")
        if row.status_code != "POSTED":
            raise ValueError("این ردیف ثبت‌شده نیست یا قبلاً برگشت خورده است.")
        runs._module(session, run_id, row.module_code)
        advance = bool(row.resolved.get("advance"))
        doc = None
        if not advance:
            doc = session.scalar(select(CommercialDocument).where(CommercialDocument.document_id == row.target_id).with_for_update())
            if doc is None or doc.status_code != "POSTED":
                raise ValueError("سند باز در وضعیت قابل برگشت نیست.")
            later = session.scalar(select(func.count()).select_from(InvoiceSettlement).where(
                InvoiceSettlement.invoice_document_id == doc.document_id, InvoiceSettlement.description != PRE_CUTOVER_NOTE))
            if later:
                raise ValueError("پس از افتتاحیه روی این سند تسویه ثبت شده است؛ ابتدا آن تسویه‌ها را بردارید.")
        # همان ردیف سند اصلی، معکوس؛ طرف مقابل حساب واسط. پیش‌دریافت/پیش‌پرداخت خلاف جهت سند باز است.
        lines = []
        receivable = row.module_code == "RECEIVABLES"
        debit_side = receivable != advance
        src = session.scalars(select(JournalEntryLine).where(
            JournalEntryLine.journal_entry_id == row.journal_entry_id,
            JournalEntryLine.account_id == int(row.resolved["account_id"]))).all()
        person = int(row.resolved["counterparty_id"])
        line = None
        for ln in src:
            dets = {d.dimension_type_id: d.detail_account_id for d in session.scalars(
                select(JournalEntryLineDetail).where(JournalEntryLineDetail.line_id == ln.line_id))}
            if person in dets.values() and (ln.debit_amount_fc if debit_side else ln.credit_amount_fc) == c.dec(row.resolved["open"]):
                line = (ln, dets)
                break
        if line is None:
            raise ValueError("ردیف سند حسابداری همین مانده پیدا نشد.")
        ln, dets = line
        amount = c.dec(row.resolved["open"])
        foreign = ln.currency_id != run.currency_id
        label = ("پیش‌دریافت" if receivable else "پیش‌پرداخت") if advance else "سند باز"
        lines.append(je_service.LineInput(
            account_id=ln.account_id, description=f"برگشت {label} افتتاحیه {row.resolved.get('legacy_no') or ''}".strip(), details=dets,
            debit=c.ZERO if debit_side else amount, credit=amount if debit_side else c.ZERO,
            currency_id=ln.currency_id if foreign else None, exchange_rate=ln.exchange_rate if foreign else None))
        base = je_service._base_amount(amount, ln.exchange_rate if foreign else c.dec(1))
        lines.append(je_service.LineInput(account_id=c.clearing_account_id(company_id), description="برگشت افتتاحیه — طرف مقابل",
                                          debit=base if debit_side else c.ZERO, credit=c.ZERO if debit_side else base))
        je = je_service.create_journal_entry(company_id, user_id, run.go_live_date, f"افتتاحیهٔ اصلاحی {run.code}: {reason.strip()}"[:250],
                                             lines, alternative_number=f"OPN-{run.code}", entry_type_code="OPENING",
                                             session=session).journal_entry_id
        if doc is not None:
            doc.status_code = "CANCELLED"
        row.status_code = "REVERSED"
        session.add(Posting(run_id=run_id, module_code=row.module_code, step_key=f"REV:{row.row_id}", status_code="DONE",
                            target_type="COMMERCIAL_DOCUMENT" if doc is not None else "JOURNAL_ENTRY",
                            target_id=doc.document_id if doc is not None else je, journal_entry_id=je, row_count=1,
                            amount=-base if debit_side else base, attempts=1, user_id=user_id, finished_at=c.now(),
                            message=reason.strip()))
        details = {"row_id": row.row_id, "document_id": doc.document_id if doc is not None else None, "journal_entry_id": je}
        c.event(session, run_id, "REVERSE", user_id, row.module_code, reason.strip(), details)
        c.event(session, original.run_id, "REVERSE", user_id, row.module_code, f"در افتتاحیهٔ اصلاحی {run.code}: {reason.strip()}",
                details)
        c.audit(session, company_id, user_id, run_id, "REVERSE", {**details, "reason": reason})
        session.commit()
        return je


def reversible_rows(company_id: int, run_id: int) -> list[SimpleNamespace]:
    """ردیف‌های دریافتنی/پرداختنی ثبت‌شدهٔ افتتاحیهٔ اصلی که در این اصلاحیه قابل برگشت‌اند."""
    with new_session() as session:
        run = runs._run(session, company_id, run_id)
        if run.kind_code != "CORRECTION":
            return []
        return [SimpleNamespace(row_id=r.row_id, module_code=r.module_code, module=c.MODULE_LABELS[r.module_code],
                                key=r.row_key, amount=c.dec(r.amount), payload=dict(r.payload or {}))
                for r in session.scalars(select(StagedRow).where(
                    StagedRow.run_id == run.corrects_run_id, StagedRow.module_code.in_(("RECEIVABLES", "PAYABLES")),
                    StagedRow.status_code == "POSTED").order_by(StagedRow.row_id))]


# --- سیاست تاریخ برش -----------------------------------------------------------------------------------------
def cutover_message(company_id: int, document_date: datetime.date | None) -> str | None:
    """هشدار برای سند عادی با تاریخ تا روز برش افتتاحیهٔ ثبت‌شده (رد نمی‌شود؛ منطق اسناد موجود عوض نمی‌شود)."""
    if document_date is None:
        return None
    with new_session() as session:
        balance_date = session.scalar(select(func.max(OpeningRun.balance_date)).where(
            OpeningRun.company_id == company_id, OpeningRun.kind_code == "ORIGINAL",
            OpeningRun.status_code.in_(("POSTING", "POSTED", "LOCKED"))))
    if balance_date is None or document_date > balance_date:
        return None
    return (f"تاریخ این سند ({c.fmt_date(document_date)}) پیش از شروع کار با سیستم است (افتتاحیه تا {c.fmt_date(balance_date)}); "
            "مانده‌های آن روز از سیستم قبلی منتقل شده‌اند و این سند ممکن است دوباره شمرده شود.")
