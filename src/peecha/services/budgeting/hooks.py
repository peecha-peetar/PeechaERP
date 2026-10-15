"""نقطهٔ اتصال اسناد خرید به بودجه (R313) — یک فراخوانی کوتاه داخل همان تراکنش سند.

خطای پیش‌بینی‌نشدهٔ بودجه با savepoint جدا می‌شود: با کلید «کنترل بودجه» سند متوقف می‌شود (کنترل دور زده نمی‌شود)؛
بدون آن، سند خرید مثل قبل ادامه می‌دهد و «تطبیق دوباره» بعداً دفتر مصرف را درست می‌کند.
"""

from __future__ import annotations

import logging

from peecha.services import stock_controls
from peecha.services.budgeting import common as c
from peecha.services.budgeting import control, ledger

log = logging.getLogger(__name__)


def _guard(session, company_id: int, fn, can_block: bool = True) -> list[str]:
    # آزاد/برگشت savepoint رویداد after_commit/after_rollback می‌دهد و صف ارسال گردش کار سند (wf_companies) را
    # پیش از commit واقعی خالی می‌کند؛ صف بیرون از savepoint نگه داشته و بعد برگردانده می‌شود.
    session.flush()
    pending = session.info.pop("wf_companies", None) or set()
    try:
        with session.begin_nested():
            result = fn()
            pending |= session.info.pop("wf_companies", None) or set()
        return result
    except ValueError:
        if can_block:
            raise
        log.exception("budget record step failed")
        return []
    except Exception as exc:  # noqa: BLE001
        log.exception("budget hook failed")
        if can_block and c.is_on(company_id, stock_controls.BUD_ENFORCE, session):
            raise ValueError("کنترل بودجه انجام نشد؛ دوباره تلاش کنید یا با مسئول بودجه تماس بگیرید.") from exc
        return []
    finally:
        if pending:
            session.info.setdefault("wf_companies", set()).update(pending)


def sources_of(session, doc) -> set[tuple[str, int]]:
    """اسناد مرتبط، پیش از حذف ردیف‌ها (برای حذف سند)."""
    if doc is None or doc.document_type_code not in ledger.DOC_TYPES or not ledger.has_budgets(session, doc.company_id):
        return set()
    return ledger.related_sources(session, doc)


def document_changed(session, doc, event: str, user_id: int | None, *, deleted: bool = False,
                     sources: set[tuple[str, int]] | None = None, record_only: bool = False) -> list[str]:
    """سند خرید (سفارش، فاکتور، برگشت) تغییر وضعیت داد؛ پیش از commit همان سند صدا زده می‌شود.

    record_only: گام پایانی عملیات چندمرحله‌ای که پیش‌تر پیش‌بررسی شده (ثبت نهایی، اصلاح) — هرگز رد نمی‌کند.
    """
    if doc is None or doc.document_type_code not in ledger.DOC_TYPES:
        return []
    company_id = doc.company_id

    def run():
        if not ledger.has_budgets(session, company_id):
            return []
        session.flush()
        related = sources if sources is not None else ledger.related_sources(session, doc)
        gone = {(doc.document_type_code, doc.document_id)} if deleted else set()
        return control.process(session, company_id, related, event, user_id,
                               (doc.document_type_code, doc.document_id, doc.document_no), gone,
                               mode="RECORD" if record_only else "STRICT")
    return _guard(session, company_id, run, can_block=not record_only)


def precheck(company_id: int, document_id: int, event: str, user_id: int | None, assume: dict[int, str]) -> list[str]:
    """پیش‌بررسی ثبت نهایی/اصلاح فاکتور پیش از ساخت سند انبار و حسابداری (تجاوز بدون مجوز ValueError)."""
    try:
        return control.precheck(company_id, "", document_id, event, user_id, assume)
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("budget precheck failed")
        if c.is_on(company_id, stock_controls.BUD_ENFORCE):
            raise ValueError("کنترل بودجه انجام نشد؛ دوباره تلاش کنید یا با مسئول بودجه تماس بگیرید.") from exc
        return []


def request_changed(session, req, event: str, user_id: int | None) -> list[str]:
    """درخواست خرید تصویب، لغو یا رد شد."""
    if req is None:
        return []
    company_id = req.company_id

    def run():
        if not ledger.has_budgets(session, company_id):
            return []
        session.flush()
        return control.process(session, company_id, {(ledger.PR, req.request_id)}, event, user_id,
                               (ledger.PR, req.request_id, req.request_no))
    return _guard(session, company_id, run)
