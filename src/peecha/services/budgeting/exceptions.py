"""مجوز تجاوز از بودجه و بستن تعهد سفارش (R313).

- مجوز «تأیید سطح بالاتر» با دسترسی «تأیید مجوز تجاوز از بودجه»؛ مجوز بودجهٔ مسدود، دورهٔ بسته و خرید خارج از بودجه با
  دسترسی «مجوز استثنای ویژه». درخواست‌کننده خودش را تأیید نمی‌کند (مگر با کلید BUD_SELF_APPROVAL). همه با دلیل و ردپا.
- بستن تعهد: ماندهٔ فاکتورنشدهٔ ردیف سفارش از تعهد آزاد می‌شود؛ وضعیت خود سفارش خرید تغییر نمی‌کند.
"""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.budgeting import BudgetException, CommitmentClosure, ControlKey
from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine
from peecha.services import stock_controls
from peecha.services.budgeting import budgets as bud
from peecha.services.budgeting import common as c
from peecha.services.budgeting import control, ledger


def _form(level: str) -> str:
    return c.FORM_EXCEPTION if level == "APPROVAL" else c.FORM_OVERRIDE


def _engine_acting() -> bool:
    from peecha.services.workflow import model_events

    return model_events._acting() is not None


def _load(session, company_id: int, exception_id: int) -> BudgetException:
    row = session.scalar(select(BudgetException).where(BudgetException.exception_id == exception_id).with_for_update())
    if row is None or row.company_id != company_id:
        raise ValueError("درخواست مجوز نامعتبر است.")
    return row


def decide(company_id: int, user_id: int, exception_id: int, approve: bool, note: str | None = None) -> None:
    if not approve and not (note or "").strip():
        raise ValueError("دلیل رد مجوز را بنویسید.")
    with new_session() as session:
        row = _load(session, company_id, exception_id)
        if row.status_code != "PENDING":
            raise ValueError(f"این درخواست در وضعیت «{c.EXCEPTION_STATUS_LABELS[row.status_code]}» است.")
        if not _engine_acting():
            c.require(company_id, user_id, _form(row.level_code))
            if row.requested_by_user_id == user_id and not c.is_on(company_id, stock_controls.BUD_SELF_APPROVAL, session):
                raise ValueError("درخواست‌کنندهٔ مجوز نمی‌تواند آن را خودش تأیید یا رد کند.")
        row.status_code = "APPROVED" if approve else "REJECTED"
        row.decided_by_user_id, row.decided_at, row.decision_note = user_id, c.now(), (note or None)
        session.flush()
        c.audit(session, company_id, user_id, c.ENTITY_EXCEPTION, exception_id, "APPROVE" if approve else "REJECT",
                {"level": row.level_code, "excess": row.excess_amount, "note": note, "source": row.source_type,
                 "document": row.source_document_id})
        session.commit()


def cancel(company_id: int, user_id: int, exception_id: int, note: str | None = None) -> None:
    with new_session() as session:
        row = _load(session, company_id, exception_id)
        if row.status_code not in ("PENDING", "APPROVED"):
            raise ValueError("فقط مجوز باز لغو می‌شود.")
        if row.requested_by_user_id != user_id and not c.can(company_id, user_id, _form(row.level_code)):
            raise ValueError("فقط درخواست‌کننده یا تصمیم‌گیرنده می‌تواند مجوز را لغو کند.")
        row.status_code, row.decision_note = "CANCELLED", note or None
        session.flush()
        c.audit(session, company_id, user_id, c.ENTITY_EXCEPTION, exception_id, "CANCEL", {"note": note})
        session.commit()


def _source_label(session, source_type: str, document_id: int, source_no: int | None) -> str:
    return f"{c.SOURCE_LABELS.get(source_type, source_type)} {source_no or document_id}"


def list_exceptions(company_id: int, status: str | None = None, user_id: int | None = None) -> list[SimpleNamespace]:
    lookups = bud.Lookups(company_id)
    with new_session() as session:
        q = select(BudgetException).where(BudgetException.company_id == company_id).order_by(BudgetException.requested_at.desc())
        if status:
            q = q.where(BudgetException.status_code == status)
        rows = list(session.scalars(q))
        keys = {k.key_id: k for k in session.scalars(select(ControlKey).where(ControlKey.key_id.in_([r.key_id for r in rows if r.key_id] or [0])))}
        names = c.user_names(session, [r.requested_by_user_id for r in rows] + [r.decided_by_user_id for r in rows])
        out = []
        for r in rows:
            out.append(SimpleNamespace(
                exception_id=r.exception_id, level_code=r.level_code, level_label=c.EXCEPTION_LEVEL_LABELS[r.level_code],
                status_code=r.status_code, status_label=c.EXCEPTION_STATUS_LABELS[r.status_code], source_type=r.source_type,
                document_id=r.source_document_id, source_label=_source_label(session, r.source_type, r.source_document_id, r.source_no),
                key_label=lookups.key_label(keys[r.key_id]) if r.key_id in keys else "خارج از بودجه", excess_amount=r.excess_amount,
                reason=r.reason, requested_by=names.get(r.requested_by_user_id, ""), requested_by_user_id=r.requested_by_user_id,
                requested_at=r.requested_at, decided_by=names.get(r.decided_by_user_id, ""), decided_at=r.decided_at,
                decision_note=r.decision_note, used_at=r.used_at,
                can_decide=r.status_code == "PENDING" and user_id is not None and c.can(company_id, user_id, _form(r.level_code))
                and (r.requested_by_user_id != user_id or c.is_on(company_id, stock_controls.BUD_SELF_APPROVAL))))
        return out


def pending_count(company_id: int, user_id: int) -> int:
    return sum(1 for e in list_exceptions(company_id, "PENDING", user_id) if e.can_decide)


# --- بستن تعهد سفارش -----------------------------------------------------------------------------------------
def open_order_lines(company_id: int, document_id: int) -> list[SimpleNamespace]:
    """ردیف‌های سفارش با مقدار باز (فاکتورنشده و بسته‌نشده) برای صفحهٔ بستن تعهد."""
    from peecha.services import purchase_reports as base

    ctx = base._ctx(company_id)
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id or doc.document_type_code != "PURCHASE_ORDER":
            raise ValueError("سفارش خرید نامعتبر است.")
        lines = list(session.scalars(select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id)
                                     .order_by(CommercialDocumentLine.line_no)))
        open_qty = ledger.po_open_quantities(session, lines)
        closed = ledger.closed_quantities(session, [ln.line_id for ln in lines])
        return [SimpleNamespace(line_id=ln.line_id, line_no=ln.line_no, item=ctx.item_label(ln.item_id), quantity=ln.quantity_base,
                                open_qty=open_qty[ln.line_id], closed_qty=closed.get(ln.line_id, c.ZERO),
                                open_amount=c.money(ledger._net(ln) * open_qty[ln.line_id] / c.dec(ln.quantity_base) * c.dec(doc.exchange_rate or 1))
                                if ln.quantity_base else c.ZERO) for ln in lines]


def close_commitment(company_id: int, user_id: int, document_id: int, reason: str, line_ids: list[int] | None = None) -> int:
    """ماندهٔ تعهد ردیف‌های سفارش آزاد می‌شود (فاکتورهای بعدی همچنان «واقعی» می‌شوند)."""
    if not (reason or "").strip():
        raise ValueError("علت بستن تعهد را بنویسید.")
    c.require(company_id, user_id, c.FORM_COMMITMENT)
    with new_session() as session:
        doc = session.scalar(select(CommercialDocument).where(CommercialDocument.document_id == document_id).with_for_update())
        if doc is None or doc.company_id != company_id or doc.document_type_code != "PURCHASE_ORDER":
            raise ValueError("سفارش خرید نامعتبر است.")
        if doc.status_code not in ("CONFIRMED", "APPROVED", "POSTED"):
            raise ValueError("فقط تعهد سفارش تاییدشده بسته می‌شود؛ سفارش پیش‌نویس یا لغوشده تعهدی ندارد.")
        lines = list(session.scalars(select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id)))
        if line_ids:
            lines = [ln for ln in lines if ln.line_id in set(line_ids)]
        open_qty = ledger.po_open_quantities(session, lines)
        closed = 0
        for ln in lines:
            if open_qty[ln.line_id] <= 0:
                continue
            if session.scalar(select(CommitmentClosure.closure_id).where(CommitmentClosure.line_id == ln.line_id,
                                                                         CommitmentClosure.reopened_at.is_(None))):
                continue
            session.add(CommitmentClosure(company_id=company_id, document_id=document_id, line_id=ln.line_id,
                                          closed_qty_base=open_qty[ln.line_id], reason=reason.strip(), closed_by_user_id=user_id))
            closed += 1
        if not closed:
            raise ValueError("این سفارش ماندهٔ تعهد باز ندارد.")
        session.flush()
        control.process(session, company_id, ledger.related_sources(session, doc), "CLOSE", user_id,
                        ("PURCHASE_ORDER", doc.document_id, doc.document_no))
        c.audit(session, company_id, user_id, c.ENTITY_BUDGET, 0, "COMMITMENT_CLOSE",
                {"document": document_id, "lines": closed, "reason": reason})
        session.commit()
        return closed


def reopen_commitment(company_id: int, user_id: int, document_id: int, note: str) -> int:
    """بازگشایی تعهد بسته‌شده؛ چون مصرف بیشتر می‌شود، سیاست بودجه دوباره اجرا می‌شود."""
    if not (note or "").strip():
        raise ValueError("علت بازگشایی تعهد را بنویسید.")
    c.require(company_id, user_id, c.FORM_COMMITMENT)
    with new_session() as session:
        doc = session.scalar(select(CommercialDocument).where(CommercialDocument.document_id == document_id).with_for_update())
        if doc is None or doc.company_id != company_id:
            raise ValueError("سفارش خرید نامعتبر است.")
        rows = list(session.scalars(select(CommitmentClosure).where(CommitmentClosure.document_id == document_id,
                                                                    CommitmentClosure.reopened_at.is_(None))))
        if not rows:
            raise ValueError("تعهد بسته‌شده‌ای برای این سفارش نیست.")
        for r in rows:
            r.reopened_by_user_id, r.reopened_at, r.reopen_note = user_id, c.now(), note.strip()
        session.flush()
        control.process(session, company_id, ledger.related_sources(session, doc), "REOPEN", user_id,
                        ("PURCHASE_ORDER", doc.document_id, doc.document_no))
        c.audit(session, company_id, user_id, c.ENTITY_BUDGET, 0, "COMMITMENT_REOPEN", {"document": document_id, "note": note})
        session.commit()
        return len(rows)


def open_commitments(company_id: int, include_closed: bool = True) -> list[SimpleNamespace]:
    """سفارش‌های خرید با ماندهٔ تعهد (و سفارش‌های دارای تعهد بسته‌شده) برای صفحهٔ «بستن تعهد سفارش»."""
    from sqlalchemy import func

    from peecha.db.models.budgeting import ConsumptionEntry
    from peecha.db.models.accounting import DetailAccount

    with new_session() as session:
        bal = dict(session.execute(
            select(ConsumptionEntry.source_document_id, func.sum(ConsumptionEntry.amount))
            .where(ConsumptionEntry.company_id == company_id, ConsumptionEntry.source_type == "PURCHASE_ORDER",
                   ConsumptionEntry.kind_code == "COMMIT")
            .group_by(ConsumptionEntry.source_document_id)).all())
        closed: dict[int, list] = {}
        for r in session.scalars(select(CommitmentClosure).where(CommitmentClosure.company_id == company_id,
                                                                 CommitmentClosure.reopened_at.is_(None))):
            closed.setdefault(r.document_id, []).append(r)
        ids = {d for d, v in bal.items() if c.dec(v) > 0} | (set(closed) if include_closed else set())
        docs = list(session.scalars(select(CommercialDocument).where(CommercialDocument.document_id.in_(ids or {0}))
                                    .order_by(CommercialDocument.document_date, CommercialDocument.document_no)))
        names = {d.detail_account_id: f"{d.code} — {d.name or ''}" for d in session.scalars(
            select(DetailAccount).where(DetailAccount.detail_account_id.in_({x.counterparty_detail_account_id for x in docs} or {0})))}
        statuses = {"CONFIRMED": "تاییدشده", "APPROVED": "تصویب‌شده", "POSTED": "ثبت‌شده", "CANCELLED": "لغوشده"}
        return [SimpleNamespace(document_id=d.document_id, document_no=d.document_no, document_date=d.document_date,
                                supplier=names.get(d.counterparty_detail_account_id, ""), status_label=statuses.get(d.status_code, d.status_code),
                                open_amount=c.dec(bal.get(d.document_id)), closed_lines=len(closed.get(d.document_id, [])),
                                closed_reason=closed[d.document_id][0].reason if d.document_id in closed else "")
                for d in docs]
