"""کنترل بودجه در سرویس سند (R313) — داخل همان تراکنش سند خرید.

فقط «افزایش مصرف» سنجیده می‌شود (تایید سفارش، فاکتور گران‌تر از سفارش، تغییر مرکز هزینه، بازگشایی تعهد، تصویب درخواست
خرید با کلید پیش‌تعهد). لغو، بازگشت، حذف، بستن تعهد، انتشار نسخه و تطبیق دوباره هرگز رد نمی‌شوند.

مانده = مبلغ مصوب − (واقعی + تعهد [+ پیش‌تعهد با کلید BUD_PR_COMMIT])، در سطح «کل دوره» یا «تجمعی تا پایان دورهٔ سند».
کلیدهای درگیر به ترتیب ثابت با FOR NO KEY UPDATE قفل می‌شوند: دو کاربر هم‌زمان نمی‌توانند هر دو از مانده عبور کنند.

سیاست: هشدار ← سند تایید و هشدار ثبت می‌شود؛ تأیید سطح بالاتر یا مسدود ← سند تایید نمی‌شود و درخواست مجوز (در تراکنش
جداگانه، تا با برگشت سند گم نشود) ساخته می‌شود؛ پس از تأیید مجوز، تایید دوبارهٔ سند همان مجوز را مصرف می‌کند.
دورهٔ بسته و خرید خارج از بودجه (با سیاست «جلوگیری») فقط با مجوز استثنای ویژه.
"""

from __future__ import annotations

import decimal
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha import numerals
from peecha.db.base import new_session
from peecha.db.models.budgeting import BudgetException, BudgetPeriod, ControlEvent, ControlKey, LinePeriodAmount
from peecha.services import stock_controls
from peecha.services.budgeting import budgets as bud
from peecha.services.budgeting import common as c
from peecha.services.budgeting import ledger

RELEASE_EVENTS = {"CANCEL", "REVERT", "DELETE", "CLOSE", "RESYNC", "VERSION", "APPROVE_DOC", "REJECT"}
ORIGIN_EVENTS = {"CONFIRM", "APPROVE", "DIMENSION"}  # جایی که خرید خارج از بودجه سنجیده می‌شود


@dataclass
class Check:
    budget_id: int | None
    key_id: int | None
    level: str  # OK | NEAR | WARN | APPROVAL | BLOCK | CLOSED | UNBUDGETED
    policy: str | None
    budget_amount: decimal.Decimal | None
    before: decimal.Decimal | None
    increase: decimal.Decimal
    after: decimal.Decimal | None
    excess: decimal.Decimal = c.ZERO
    label: str = ""


def _fmt(v) -> str:
    return numerals.format_money(c.dec(v), 0, None)


def counted_kinds(company_id: int, session=None) -> tuple[str, ...]:
    return ("ACTUAL", "COMMIT", "PRE") if c.is_on(company_id, stock_controls.BUD_PR_COMMIT, session) else ("ACTUAL", "COMMIT")


def process(session, company_id: int, sources: set[tuple[str, int]], event: str, user_id: int | None,
            primary: tuple[str, int, int | None], deleted: set[tuple[str, int]] = frozenset(), *, mode: str = "STRICT",
            assume: dict[int, str] | None = None) -> list[str]:
    """تطبیق دفتر مصرف با اسناد + اجرای سیاست. خروجی: پیام‌های هشدار.

    mode: STRICT = کنترل و ثبت در همین تراکنش (تجاوز بدون مجوز ValueError)؛ CHECK = فقط پیش‌بررسی بدون نوشتن
    (ثبت نهایی و اصلاح فاکتور پیش از ساخت سند انبار و حسابداری)؛ RECORD = گام پایانی همان عملیات: ثبت و ردپا، هرگز رد نمی‌کند.
    """
    if not sources or not ledger.has_budgets(session, company_id):
        return []
    ledger.lock_sources(session, sources)
    plan = ledger.Plan(session, company_id)
    result = ledger.compute(session, company_id, sources, plan, deleted, assume)
    messages: list[str] = []
    if event not in RELEASE_EVENTS and c.is_on(company_id, stock_controls.BUD_ENFORCE, session):
        messages = _enforce(session, company_id, plan, result, event, user_id, primary, mode)
    if mode != "CHECK":
        ledger.write(session, company_id, result.deltas, event, user_id)
    return messages


def _enforce(session, company_id: int, plan: ledger.Plan, result: ledger.Result, event: str, user_id: int | None,
             primary: tuple[str, int, int | None], mode: str = "STRICT") -> list[str]:
    settings = c.settings(company_id, session)
    kinds = counted_kinds(company_id, session)
    increase: dict[tuple[int, int], decimal.Decimal] = defaultdict(lambda: c.ZERO)
    when = {}
    for d in result.deltas:
        if d.kind in kinds:
            increase[(d.budget_id, d.key_id)] += d.amount
            if d.amount > 0:
                when[(d.budget_id, d.key_id)] = max(when.get((d.budget_id, d.key_id), d.period_date), d.period_date)
    targets = sorted(k for k, v in increase.items() if v > 0)
    checks: list[Check] = []
    if targets:
        session.execute(select(ControlKey.key_id).where(ControlKey.key_id.in_([k for _b, k in targets]))
                        .order_by(ControlKey.key_id).with_for_update(key_share=True)).all()
        lines = {key.key_id: line for pb in plan.budgets for key, line in pb.keys}
        periods = defaultdict(list)
        for p in session.scalars(select(BudgetPeriod).where(BudgetPeriod.budget_id.in_({b for b, _k in targets}))
                                 .order_by(BudgetPeriod.period_no)):
            periods[p.budget_id].append(p)
        for budget_id, key_id in targets:
            line, inc = lines[key_id], increase[(budget_id, key_id)]
            period = bud.period_of(periods[budget_id], when[(budget_id, key_id)])
            if settings.control_level == "CUMULATIVE" and period is not None:
                amount = c.dec(session.scalar(select(func.coalesce(func.sum(LinePeriodAmount.amount), 0)).where(
                    LinePeriodAmount.line_id == line.line_id, LinePeriodAmount.period_no <= period.period_no)))
                totals = ledger.key_totals(session, [key_id], date_to=period.date_to)[key_id]
            else:
                amount = bud.line_amount(line)
                totals = ledger.key_totals(session, [key_id])[key_id]
            before = sum((totals[k] for k in kinds), c.ZERO)
            after = before + inc
            policy = line.policy_code or settings.policy_code
            warn = c.dec(line.warn_percent or settings.warn_percent)
            check = Check(budget_id, key_id, "OK", policy, amount, before, inc, after)
            if period is not None and period.is_closed:
                check.level, check.excess = "CLOSED", inc
            elif after > amount:
                check.excess = min(inc, after - amount)
                check.level = "WARN" if policy == "WARN" else policy
            elif amount > 0 and after * 100 >= amount * warn:
                check.level = "NEAR"
            checks.append(check)
    stype, sid, sno = primary
    if event in ORIGIN_EVENTS and settings.unbudgeted_policy != "ALLOW":
        free = sum((u[4] for u in result.unbudgeted if (u[0], u[1]) == (stype, sid) and u[4] > 0), c.ZERO)
        if free > 0:
            checks.append(Check(None, None, "UNBUDGETED" if settings.unbudgeted_policy == "BLOCK" else "WARN", settings.unbudgeted_policy,
                                None, None, free, None, free, "خارج از همهٔ ردیف‌های بودجه"))
    if not checks:
        return []
    lookups = None
    for ch in checks:
        if ch.key_id and ch.level != "OK":
            lookups = lookups or bud.Lookups(company_id)
            ch.label = lookups.key_label(session.get(ControlKey, ch.key_id))
    blocking = [ch for ch in checks if ch.level in ("APPROVAL", "BLOCK", "CLOSED", "UNBUDGETED")]
    unresolved, used = [], {}
    for ch in blocking:
        q = select(BudgetException).where(
            BudgetException.source_type == stype, BudgetException.source_document_id == sid, BudgetException.level_code == ch.level,
            BudgetException.status_code == "APPROVED",
            BudgetException.key_id.is_(None) if ch.key_id is None else BudgetException.key_id == ch.key_id)
        exc = session.scalar(q if mode == "CHECK" else q.with_for_update())
        if exc is not None and c.dec(exc.excess_amount) >= ch.excess:
            if mode != "CHECK":
                exc.status_code, exc.used_at = "USED", c.now()
            used[id(ch)] = exc.exception_id
        else:
            unresolved.append(ch)
    if unresolved and mode != "RECORD":
        _record_blocked(company_id, user_id, event, primary, unresolved)
        raise ValueError(_block_message(unresolved))
    if mode == "CHECK":
        return [_check_text(ch) for ch in checks if ch.level in ("WARN", "NEAR")]
    messages = []
    for ch in checks:
        outcome = "EXCEPTION_USED" if id(ch) in used else ("UNBUDGETED" if ch.key_id is None else ch.level)
        if outcome in ("APPROVAL", "BLOCK", "CLOSED"):  # فقط در گام پایانی پس از پیش‌بررسی (تغییر هم‌زمان مانده)
            outcome = "WARN"
        text = _check_text(ch)
        if ch.level in ("WARN", "NEAR") or id(ch) in used:
            messages.append(text)
        session.add(ControlEvent(company_id=company_id, budget_id=ch.budget_id, key_id=ch.key_id, source_type=stype,
                                 source_document_id=sid, source_no=sno, stage_code=event, outcome_code=outcome, policy_code=ch.policy,
                                 budget_amount=ch.budget_amount, consumed_before=ch.before, delta=ch.increase,
                                 available_after=(ch.budget_amount - ch.after) if ch.budget_amount is not None else None,
                                 exception_id=used.get(id(ch)), message=text, user_id=user_id))
    session.flush()
    return messages


def _check_text(ch: Check) -> str:
    if ch.key_id is None:
        return f"خرید خارج از بودجه به مبلغ {_fmt(ch.increase)}."
    rest = ch.budget_amount - ch.before
    head = f"بودجهٔ «{ch.label}»: مانده {_fmt(rest)}، این سند {_fmt(ch.increase)}"
    if ch.level == "CLOSED":
        return f"{head} — دورهٔ بودجهٔ این سند بسته است."
    if ch.excess > 0:
        return f"{head} — {_fmt(ch.excess)} بیشتر از بودجه."
    if ch.level == "NEAR":
        return f"{head} — نزدیک به سقف ({numerals.format_money(ch.after * 100 / ch.budget_amount, 1, None)}٪)."
    return head


def _block_message(checks: list[Check]) -> str:
    lines = [_check_text(ch) for ch in checks]
    if any(ch.level in ("BLOCK", "CLOSED", "UNBUDGETED") for ch in checks):
        tail = ("این سند تا اصلاح بودجه یا صدور مجوز استثنای ویژه تایید نمی‌شود. درخواست مجوز ثبت شد؛ "
                "پس از تأیید آن، سند را دوباره تایید کنید.")
    else:
        tail = "این سند به تأیید سطح بالاتر نیاز دارد. درخواست مجوز تجاوز ثبت شد؛ پس از تأیید آن، سند را دوباره تایید کنید."
    return "\n".join(lines + [tail])


def _record_blocked(company_id: int, user_id: int | None, event: str, primary: tuple[str, int, int | None], checks: list[Check]) -> None:
    """درخواست مجوز و ردپا در تراکنش جداگانه (سند برمی‌گردد ولی درخواست و ردپا می‌ماند)."""
    stype, sid, sno = primary
    with new_session() as session:
        for ch in checks:
            q = select(BudgetException).where(BudgetException.source_type == stype, BudgetException.source_document_id == sid,
                                              BudgetException.level_code == ch.level,
                                              BudgetException.status_code.in_(("PENDING", "APPROVED")),
                                              BudgetException.key_id.is_(None) if ch.key_id is None else BudgetException.key_id == ch.key_id)
            exc = session.scalar(q.with_for_update())
            if exc is not None and exc.status_code == "APPROVED":
                exc.status_code, exc.decision_note = "CANCELLED", "مبلغ تجاوز سند بیشتر از مجوز شد؛ درخواست جدید ثبت شد."
                session.flush()
                exc = None
            if exc is None:
                exc = BudgetException(company_id=company_id, budget_id=ch.budget_id, key_id=ch.key_id, source_type=stype,
                                      source_document_id=sid, source_no=sno, level_code=ch.level, excess_amount=ch.excess,
                                      reason=_check_text(ch), requested_by_user_id=user_id)
                session.add(exc)
            else:
                exc.excess_amount, exc.reason, exc.requested_by_user_id, exc.requested_at = ch.excess, _check_text(ch), user_id, c.now()
            session.flush()
            session.add(ControlEvent(company_id=company_id, budget_id=ch.budget_id, key_id=ch.key_id, source_type=stype,
                                     source_document_id=sid, source_no=sno, stage_code=event,
                                     outcome_code="NEEDS_APPROVAL" if ch.level == "APPROVAL" else "BLOCKED", policy_code=ch.policy,
                                     budget_amount=ch.budget_amount, consumed_before=ch.before, delta=ch.increase,
                                     available_after=(ch.budget_amount - ch.after) if ch.budget_amount is not None else None,
                                     exception_id=exc.exception_id, message=_check_text(ch), user_id=user_id))
            c.audit(session, company_id, user_id, c.ENTITY_EXCEPTION, exc.exception_id, "REQUEST",
                    {"source": stype, "document": sid, "level": ch.level, "excess": ch.excess})
        session.commit()


# --- پیام برای فرم سند ---------------------------------------------------------------------------------------
def document_messages(company_id: int, source_type: str, document_id: int) -> list[str]:
    """پیام‌های آخرین کنترل همین سند (هشدار، نزدیک به سقف، مجوز مصرف‌شده)."""
    with new_session() as session:
        last = session.scalar(select(func.max(ControlEvent.created_at)).where(
            ControlEvent.company_id == company_id, ControlEvent.source_type == source_type, ControlEvent.source_document_id == document_id))
        if last is None:
            return []
        return [e.message for e in session.scalars(select(ControlEvent).where(
            ControlEvent.company_id == company_id, ControlEvent.source_type == source_type, ControlEvent.source_document_id == document_id,
            ControlEvent.created_at == last, ControlEvent.outcome_code.in_(("WARN", "NEAR", "EXCEPTION_USED", "UNBUDGETED")))
            .order_by(ControlEvent.event_id)) if e.message]


def precheck(company_id: int, source_type: str, document_id: int, event: str, user_id: int | None,
             assume: dict[int, str]) -> list[str]:
    """پیش‌بررسی عملیات چندمرحله‌ای (ثبت نهایی، اصلاح فاکتور) پیش از ساخت هر سند انبار یا حسابداری."""
    from peecha.db.models.commercial import CommercialDocument

    with new_session() as session:
        if not ledger.has_budgets(session, company_id) or not c.is_on(company_id, stock_controls.BUD_ENFORCE, session):
            return []
        doc = session.get(CommercialDocument, document_id)
        if (doc is None or doc.company_id != company_id or doc.document_type_code not in ledger.DOC_TYPES
                or doc.status_code not in ("CONFIRMED", "APPROVED")):
            return []
        sources = ledger.related_sources(session, doc)
        return process(session, company_id, sources, event, user_id, (doc.document_type_code, doc.document_id, doc.document_no),
                       mode="CHECK", assume=assume)
