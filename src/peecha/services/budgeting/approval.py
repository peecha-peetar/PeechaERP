"""گردش تأیید نسخهٔ بودجه (R313).

پیش‌نویس ← ارسال (تهیه‌کننده) ← بررسی مسئول بودجه ← تأیید مدیر مجاز ← انتشار؛ رد در هر گام با دلیل (← ردشده ← بازگشت
به پیش‌نویس). تفکیک نقش: بررسی‌کننده ≠ تهیه‌کننده؛ تأییدکننده ≠ تهیه‌کننده و ≠ بررسی‌کننده (کلید BUD_SELF_APPROVAL
برای شرکت‌های کوچک). اگر فرایند گردش کار «با دروازه» برای «نسخهٔ بودجه» فعال باشد، تأیید فقط از مسیر همان فرایند
ممکن است (دروازهٔ موجود موتور) و تفویض اختیار هم از همان‌جا کار می‌کند.
"""

from __future__ import annotations

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.budgeting import BudgetLine, BudgetVersion
from peecha.services import stock_controls
from peecha.services.budgeting import budgets as bud
from peecha.services.budgeting import common as c


def _load(session, company_id: int, version_id: int) -> BudgetVersion:
    version, _budget = bud._version(session, company_id, version_id, lock=True)
    return version


def _expect(version: BudgetVersion, *statuses: str) -> None:
    if version.status_code not in statuses:
        raise ValueError(f"نسخه در وضعیت «{c.VERSION_STATUS_LABELS[version.status_code]}» است و این گام ممکن نیست.")


def _engine_acting() -> bool:
    from peecha.services.workflow import model_events

    return model_events._acting() is not None


def _sod(company_id: int, session, user_id: int, *others: int | None) -> None:
    if _engine_acting() or c.is_on(company_id, stock_controls.BUD_SELF_APPROVAL, session):
        return
    if user_id in {o for o in others if o}:
        raise ValueError("تهیه‌کننده، بررسی‌کننده و تأییدکنندهٔ بودجه باید افراد متفاوتی باشند.")


def _require(company_id: int, user_id: int | None, form_code: str) -> None:
    if not _engine_acting():  # موتور گردش کار گیرندهٔ کار را خودش تعیین و دسترسی را کنترل می‌کند
        c.require(company_id, user_id, form_code)


def _move(session, company_id: int, version: BudgetVersion, action: str, new: str, user_id: int | None,
          comment: str | None = None) -> None:
    old = version.status_code
    version.status_code = new
    session.flush()
    bud.decide(session, version, action, old, new, user_id, comment)
    c.audit(session, company_id, user_id, c.ENTITY_VERSION, version.version_id,
            "APPROVE" if action == "APPROVE" else ("REJECT" if action == "REJECT" else action),
            {"from": old, "to": new, "comment": comment})


def submit(company_id: int, user_id: int, version_id: int, comment: str | None = None) -> None:
    c.require(company_id, user_id, c.FORM_PREPARE)
    with new_session() as session:
        version = _load(session, company_id, version_id)
        _expect(version, "DRAFT")
        problems = bud.validate(session, version)
        if problems:
            raise ValueError("نسخه هنوز کامل نیست:\n" + "\n".join(problems))
        version.submitted_by_user_id, version.submitted_at, version.reject_reason = user_id, c.now(), None
        _move(session, company_id, version, "SUBMIT", "SUBMITTED", user_id, comment)
        session.commit()


def review(company_id: int, user_id: int, version_id: int, comment: str | None = None) -> None:
    """بررسی مسئول بودجه: تأیید بررسی (ردیف‌هایی که مبلغ مصوب نگرفته‌اند همان پیشنهادی را می‌گیرند)."""
    _require(company_id, user_id, c.FORM_REVIEW)
    with new_session() as session:
        version = _load(session, company_id, version_id)
        _expect(version, "SUBMITTED")
        _sod(company_id, session, user_id, version.prepared_by_user_id, version.submitted_by_user_id)
        problems = bud.validate(session, version)
        if problems:
            raise ValueError("\n".join(problems))
        version.reviewed_by_user_id, version.reviewed_at = user_id, c.now()
        _move(session, company_id, version, "REVIEW", "REVIEWED", user_id, comment)
        session.commit()


def approve(company_id: int, user_id: int, version_id: int, comment: str | None = None) -> None:
    _require(company_id, user_id, c.FORM_APPROVE)
    with new_session() as session:
        version = _load(session, company_id, version_id)
        _expect(version, "REVIEWED")
        _sod(company_id, session, user_id, version.prepared_by_user_id, version.submitted_by_user_id, version.reviewed_by_user_id)
        for ln in session.scalars(select(BudgetLine).where(BudgetLine.version_id == version_id)):
            if ln.approved_amount is None:
                ln.approved_amount = ln.proposed_amount
        session.flush()
        problems = bud.validate(session, version)
        if problems:
            raise ValueError("\n".join(problems))
        version.approved_by_user_id, version.approved_at = user_id, c.now()
        _move(session, company_id, version, "APPROVE", "APPROVED", user_id, comment)
        session.commit()


def publish(company_id: int, user_id: int, version_id: int, comment: str | None = None) -> None:
    """نسخهٔ تأییدشده جایگزین نسخهٔ منتشرشدهٔ قبلی می‌شود و مصرف اسناد با کلیدهای تازه تطبیق داده می‌شود."""
    from peecha.services.budgeting import ledger

    _require(company_id, user_id, c.FORM_PUBLISH)
    with new_session() as session:
        version = _load(session, company_id, version_id)
        _expect(version, "APPROVED")
        old = bud.published_version(session, version.budget_id)
        if old is not None:
            old.status_code = "SUPERSEDED"
            session.flush()
            bud.decide(session, old, "PUBLISH", "PUBLISHED", "SUPERSEDED", user_id,
                       f"جایگزین با نسخهٔ {version.version_no}")
        version.published_by_user_id, version.published_at = user_id, c.now()
        _move(session, company_id, version, "PUBLISH", "PUBLISHED", user_id, comment)
        ledger.resync_in_session(session, company_id, "VERSION", user_id)
        session.commit()


def reject(company_id: int, user_id: int, version_id: int, reason: str) -> None:
    if not (reason or "").strip():
        raise ValueError("دلیل رد را بنویسید.")
    with new_session() as session:
        version = _load(session, company_id, version_id)
        _expect(version, "SUBMITTED", "REVIEWED")
        _require(company_id, user_id, c.FORM_REVIEW if version.status_code == "SUBMITTED" else c.FORM_APPROVE)
        version.reject_reason = reason.strip()
        _move(session, company_id, version, "REJECT", "REJECTED", user_id, reason.strip())
        session.commit()


def reopen(company_id: int, user_id: int, version_id: int, comment: str | None = None) -> None:
    """نسخهٔ ردشده به پیش‌نویس برمی‌گردد تا تهیه‌کننده اصلاح و دوباره ارسال کند (تاریخچه می‌ماند)."""
    c.require(company_id, user_id, c.FORM_PREPARE)
    with new_session() as session:
        version = _load(session, company_id, version_id)
        _expect(version, "REJECTED", "SUBMITTED")
        if version.status_code == "SUBMITTED" and version.submitted_by_user_id != user_id:
            raise ValueError("فقط ارسال‌کننده می‌تواند نسخهٔ ارسال‌شده را پس بگیرد.")
        version.reviewed_by_user_id = version.reviewed_at = None
        _move(session, company_id, version, "REOPEN", "DRAFT", user_id, comment)
        session.commit()


def cancel(company_id: int, user_id: int, version_id: int, reason: str) -> None:
    if not (reason or "").strip():
        raise ValueError("دلیل لغو را بنویسید.")
    c.require(company_id, user_id, c.FORM_PREPARE)
    with new_session() as session:
        version = _load(session, company_id, version_id)
        _expect(version, "DRAFT", "REJECTED")
        _move(session, company_id, version, "CANCEL", "CANCELLED", user_id, reason.strip())
        session.commit()


def allowed_actions(company_id: int, user_id: int, version) -> dict[str, bool]:
    """دکمه‌های فعال پروندهٔ نسخه برای این کاربر (فقط برای نمایش؛ سرویس دوباره بررسی می‌کند)."""
    status = version.status_code
    self_ok = c.is_on(company_id, stock_controls.BUD_SELF_APPROVAL)
    is_preparer = user_id in {version.prepared_by_user_id}
    return {
        "edit": status == "DRAFT" and c.can(company_id, user_id, c.FORM_PREPARE),
        "submit": status == "DRAFT" and c.can(company_id, user_id, c.FORM_PREPARE),
        "adjust": (status == "SUBMITTED" and c.can(company_id, user_id, c.FORM_REVIEW))
        or (status == "REVIEWED" and c.can(company_id, user_id, c.FORM_APPROVE)),
        "review": status == "SUBMITTED" and c.can(company_id, user_id, c.FORM_REVIEW) and (self_ok or not is_preparer),
        "approve": status == "REVIEWED" and c.can(company_id, user_id, c.FORM_APPROVE)
        and (self_ok or (not is_preparer and user_id != version.reviewed_by_user_id)),
        "publish": status == "APPROVED" and c.can(company_id, user_id, c.FORM_PUBLISH),
        "reject": (status == "SUBMITTED" and c.can(company_id, user_id, c.FORM_REVIEW))
        or (status == "REVIEWED" and c.can(company_id, user_id, c.FORM_APPROVE)),
        "reopen": status == "REJECTED" and c.can(company_id, user_id, c.FORM_PREPARE),
        "cancel": status in ("DRAFT", "REJECTED") and c.can(company_id, user_id, c.FORM_PREPARE),
    }
